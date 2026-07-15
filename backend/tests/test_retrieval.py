import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from app.agents.registry import AgentRegistry
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicyProvider
from app.services.retrieval import (
    RetrievalError,
    _compact_read_source_output,
    _compact_search_output,
    retrieve_task_context,
    tool_call_fingerprint,
)


def _snapshot(tmp_path: Path, idempotent: bool = True):
    path = tmp_path / "policy.yaml"
    idempotent_value = "true" if idempotent else "false"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        f"  Read Source: {{name: raw, category: bsl.read, mode: read-only, idempotent: {idempotent_value}}}\n"
        "  Search Code: {name: raw_search, category: code.search, mode: read-only, idempotent: true}\n",
        encoding="utf-8",
    )
    return PolicyProvider(path).load()


def _compact_snapshot(tmp_path: Path):
    path = tmp_path / "compact-policy.yaml"
    path.write_text(
        "policyId: compact\nversion: 1.0.0\ntools:\n"
        "  Read Method Source: {name: raw_method, category: bsl.read, mode: read-only, idempotent: true}\n"
        "  Search Code: {name: raw_search, category: code.search, mode: read-only, idempotent: true}\n",
        encoding="utf-8",
    )
    return PolicyProvider(path).load()


def test_retrieval_calls_only_published_capability(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, headers={"Mcp-Session-Id": "session-1"}, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        assert body["method"] == "tools/call"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})

    result = asyncio.run(
        retrieve_task_context(
            {"retrieval": [{"tool": "read_source", "arguments": {"object": "Catalog.X"}}]},
            AgentRegistry().get("1c_code_assistant"),
            snapshot,
            McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler)),
        )
    )
    assert result.calls[0]["status"] == "completed"
    assert result.context[0]["source"] == "MCP"


def test_retrieval_rejects_missing_tool_before_http(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    connector = McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(lambda _: pytest.fail("no http")))
    with pytest.raises(ToolNotAllowedError):
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "write_source", "arguments": {}}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                connector,
            )
        )


def test_retrieval_limit_is_enforced_before_http(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    connector = McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(lambda _: pytest.fail("no http")))
    with pytest.raises(ValueError, match="RETRIEVAL_LIMIT_EXCEEDED"):
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {}}] * 2},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                connector,
                max_tool_calls=1,
            )
        )


def test_failed_mcp_call_keeps_audit_record(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(500)

    connector = McpConnector(
        "http://mcp.test", snapshot, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {}}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                connector,
            )
        )
    assert error.value.calls[0]["status"] == "failed"


def test_retrieval_reuses_completed_idempotent_call(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    arguments = {"object": "Catalog.X"}
    cached_output = {"content": [{"type": "text", "text": "cached source"}]}
    connector = McpConnector(
        "http://mcp.test",
        snapshot,
        transport=httpx.MockTransport(lambda _: pytest.fail("cached call must not reach MCP")),
    )

    result = asyncio.run(
        retrieve_task_context(
            {"retrieval": [{"tool": "read_source", "arguments": arguments}]},
            AgentRegistry().get("1c_code_assistant"),
            snapshot,
            connector,
            completed_calls={
                tool_call_fingerprint("read_source", arguments): {
                    "toolName": "read_source",
                    "input": arguments,
                    "output": cached_output,
                    "status": "completed",
                    "durationMs": 12,
                }
            },
        )
    )

    assert result.calls[0]["reused"] is True
    assert result.calls[0]["durationMs"] == 0
    assert result.context[0]["data"] == cached_output


def test_retrieval_blocks_cached_non_idempotent_call(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path, idempotent=False)
    arguments = {"object": "Catalog.X"}
    connector = McpConnector(
        "http://mcp.test",
        snapshot,
        transport=httpx.MockTransport(lambda _: pytest.fail("blocked retry must not reach MCP")),
    )

    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": arguments}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                connector,
                completed_calls={
                    tool_call_fingerprint("read_source", arguments): {
                        "output": {"content": []},
                        "status": "completed",
                    }
                },
            )
        )

    assert error.value.code == "NON_IDEMPOTENT_RETRY_BLOCKED"


def test_retrieval_stops_before_next_tool_after_cancellation(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    tool_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tool_calls
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        tool_calls += 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})

    checks = 0

    def before_tool_call() -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {}}, {"tool": "read_source", "arguments": {}}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler)),
                before_tool_call=before_tool_call,
            )
        )

    assert error.value.code == "TASK_CANCELLED_BY_USER"
    assert len(error.value.calls) == 1
    assert tool_calls == 1


def test_retrieval_records_parent_task_timeout(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {}}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler)),
                deadline=time.monotonic() + 0.05,
            )
        )

    assert error.value.code == "TASK_TIMEOUT"
    assert error.value.calls[0]["errorCode"] == "TASK_TIMEOUT"


def test_retrieval_rejects_an_oversized_mcp_result(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"content": [{"type": "text", "text": "x" * 100}]},
            },
        )

    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {}}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler)),
                max_result_chars=50,
            )
        )

    assert error.value.code == "MCP_RESULT_TOO_LARGE"
    assert error.value.calls[0]["errorCode"] == "MCP_RESULT_TOO_LARGE"
    assert error.value.calls[0]["resultSizeChars"] > 50
    assert error.value.calls[0]["resultSizeBytes"] > 50


def test_retrieval_stops_before_task_traffic_budget_is_exceeded(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    tool_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tool_calls
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        tool_calls += 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {"retrieval": [{"tool": "read_source", "arguments": {}}]},
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler)),
                max_result_bytes=1_000,
                max_task_mcp_bytes=500,
            )
        )

    assert error.value.code == "TASK_TRAFFIC_LIMIT_EXCEEDED"
    assert tool_calls == 0


def test_retrieval_limits_read_source_module_reads(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    tool_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tool_calls
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        tool_calls += 1
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}},
        )

    with pytest.raises(RetrievalError) as error:
        asyncio.run(
            retrieve_task_context(
                {
                    "retrieval": [
                        {"tool": "read_source", "arguments": {"module": "Catalog.A"}},
                        {"tool": "read_source", "arguments": {"module": "Catalog.B"}},
                    ]
                },
                AgentRegistry().get("1c_code_assistant"),
                snapshot,
                McpConnector("http://mcp.test", snapshot, transport=httpx.MockTransport(handler)),
                max_methods_read=1,
            )
        )

    assert error.value.code == "METHOD_READ_LIMIT_EXCEEDED"
    assert len(error.value.calls) == 1
    assert tool_calls == 1


def test_object_aware_search_context_keeps_matching_modules() -> None:
    output = {
        "content": [
            {
                "type": "text",
                "text": "## Results\n### Документ.Другой.МодульОбъекта (строка 1)\n```bsl\nA\n```\n"
                "### Документ.ЗаказКлиента.МодульОбъекта (строка 2)\n```bsl\nB\n```",
            }
        ]
    }

    compacted = _compact_search_output(output, "ЗаказКлиента", "Документ", "МодульОбъекта")

    text = compacted["content"][0]["text"]
    assert "Документ.ЗаказКлиента.МодульОбъекта" in text
    assert "Документ.Другой.МодульОбъекта" not in text


def test_object_aware_search_context_does_not_leak_other_documents() -> None:
    output = {
        "content": [{
            "type": "text",
            "text": "## Results\n### Документ.АктВыполненныхРабот.МодульОбъекта (строка 274)\n```bsl\nЗаказКлиента\n```\n"
            "### Документ.ЗаказКлиента.МодульОбъекта (строка 12)\n```bsl\nЗаказКлиента\n```",
        }]
    }

    compacted = _compact_search_output(output, "ЗаказКлиента", "Документ", "МодульОбъекта")

    text = compacted["content"][0]["text"]
    assert "Документ.ЗаказКлиента.МодульОбъекта" in text
    assert "Документ.АктВыполненныхРабот.МодульОбъекта" not in text


def test_exact_method_search_reads_the_single_defining_module(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    class Connector:
        def __init__(self) -> None:
            self.calls = []

        async def call_tool(self, tool_name, arguments, deadline=None):
            self.calls.append((tool_name, arguments))
            if tool_name == "search_code":
                return {
                    "content": [{
                        "type": "text",
                        "text": "### Документ.ЗаказКлиента.МодульОбъекта (строка 42, score: 1)\n"
                        "```bsl\nПроцедура РассчитатьСебестоимость()\nКонецПроцедуры\n```",
                    }]
                }
            return {
                "sourceComplete": True,
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "module": arguments["module"],
                        "source": "Процедура РассчитатьСебестоимость()\nКонецПроцедуры",
                    }, ensure_ascii=False),
                }],
            }

    connector = Connector()
    result = asyncio.run(retrieve_task_context(
        {
            "text": "Объясни процедуру РассчитатьСебестоимость",
            "retrieval": [{"tool": "search_code", "arguments": {"query": "РассчитатьСебестоимость", "mode": "exact"}}],
        },
        AgentRegistry().get("1c_code_assistant"),
        snapshot,
        connector,
    ))

    assert [call[0] for call in connector.calls] == ["search_code", "read_source"]
    assert connector.calls[1][1] == {"module": "Документ.ЗаказКлиента.МодульОбъекта"}
    assert [call["toolName"] for call in result.calls] == ["search_code", "read_source"]
    assert result.context[-1]["data"]["sourceComplete"] is True


def test_exact_method_search_prefers_compact_method_tool(tmp_path: Path) -> None:
    snapshot = _compact_snapshot(tmp_path)

    class Connector:
        def __init__(self) -> None:
            self.calls = []

        async def call_tool(self, tool_name, arguments, deadline=None):
            self.calls.append((tool_name, arguments))
            if tool_name == "search_code":
                return {"content": [{
                    "type": "text",
                    "text": "### Документ.ЗаказКлиента.МодульОбъекта (строка 42)\n"
                    "```bsl\nПроцедура РассчитатьСебестоимость()\nКонецПроцедуры\n```",
                }]}
            return {
                "sourceComplete": True,
                "sourceScope": "method",
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "module": arguments["module"],
                        "method": arguments["method"],
                        "source": "Процедура РассчитатьСебестоимость()\nКонецПроцедуры",
                        "sourceComplete": True,
                    }, ensure_ascii=False),
                }],
            }

    connector = Connector()
    result = asyncio.run(retrieve_task_context(
        {
            "text": "Объясни процедуру РассчитатьСебестоимость",
            "retrieval": [{"tool": "search_code", "arguments": {"query": "РассчитатьСебестоимость"}}],
        },
        AgentRegistry().get("1c_code_assistant"),
        snapshot,
        connector,
    ))

    assert connector.calls == [
        ("search_code", {"query": "РассчитатьСебестоимость"}),
        ("read_method_source", {
            "module": "Документ.ЗаказКлиента.МодульОбъекта",
            "method": "РассчитатьСебестоимость",
        }),
    ]
    assert result.context[-1]["tool"] == "read_method_source"
    assert result.context[-1]["data"]["sourceScope"] == "method"


def test_method_search_does_not_guess_between_multiple_modules(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    class Connector:
        def __init__(self) -> None:
            self.calls = []

        async def call_tool(self, tool_name, arguments, deadline=None):
            self.calls.append((tool_name, arguments))
            return {"content": [{
                "type": "text",
                "text": "\n".join([
                    "### ОбщийМодуль.А.Модуль (строка 1)",
                    "```bsl\nФункция РассчитатьСебестоимость()\nКонецФункции\n```",
                    "### ОбщийМодуль.Б.Модуль (строка 1)",
                    "```bsl\nФункция РассчитатьСебестоимость()\nКонецФункции\n```",
                ]),
            }]}

    connector = Connector()
    asyncio.run(retrieve_task_context(
        {
            "text": "Объясни функцию РассчитатьСебестоимость",
            "retrieval": [{"tool": "search_code", "arguments": {"query": "РассчитатьСебестоимость"}}],
        },
        AgentRegistry().get("1c_code_assistant"),
        snapshot,
        connector,
    ))

    assert [call[0] for call in connector.calls] == ["search_code"]


def test_read_source_context_keeps_only_complete_requested_method() -> None:
    source = (
        "НеСвязанныйКод = 1;\n" * 100
        + "Процедура РассчитатьСебестоимость()\nРезультат = 42;\nКонецПроцедуры\n"
        + "ДругойКод = 2;\n" * 1_000
    )
    output = {
        "sourceComplete": True,
        "content": [{
            "type": "text",
            "text": json.dumps({
                "module": "Документ.ЗаказКлиента.МодульОбъекта",
                "source": source,
            }, ensure_ascii=False),
        }],
    }

    compacted = _compact_read_source_output(output, "РассчитатьСебестоимость")
    payload = json.loads(compacted["content"][0]["text"])

    assert compacted["sourceScope"] == "method"
    assert payload["sourceLineStart"] == 101
    assert payload["sourceLineEnd"] == 103
    assert len(payload["source"].splitlines()) == payload["sourceLineEnd"]
    assert payload["source"].splitlines()[100] == "Процедура РассчитатьСебестоимость()"
    assert "Результат = 42;" in payload["source"]
    assert "ДругойКод" not in payload["source"]


def test_read_source_method_lines_are_exact_for_crlf_source() -> None:
    source = (
        "Префикс = 1;\r\n" * 7
        + "\tПроцедура РассчитатьСкидку()\r\n"
        + "\tРезультат = 42;\r\n"
        + "\tКонецПроцедуры;\r\n"
        + "Хвост = 2;\r\n"
    )
    output = {
        "sourceComplete": True,
        "content": [{
            "type": "text",
            "text": json.dumps({
                "module": "ОбщийМодуль.СкидкиНаценкиСервер.Модуль",
                "source": source,
            }, ensure_ascii=False),
        }],
    }

    compacted = _compact_read_source_output(output, "РассчитатьСкидку")
    payload = json.loads(compacted["content"][0]["text"])

    assert payload["sourceLineStart"] == 8
    assert payload["sourceLineEnd"] == 10
    assert len(payload["source"].splitlines()) == 10
    assert payload["source"].splitlines()[7:] == [
        "\tПроцедура РассчитатьСкидку()",
        "\tРезультат = 42;",
        "\tКонецПроцедуры;",
    ]
    assert "Хвост" not in payload["source"]


def test_large_module_is_compacted_before_character_limit(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    class Connector:
        async def call_tool(self, tool_name, arguments, deadline=None):
            if tool_name == "search_code":
                return {"content": [{
                    "type": "text",
                    "text": "### ОбщийМодуль.РасчетСебестоимости.Модуль (строка 101)\n"
                    "```bsl\nФункция РассчитатьСебестоимость()\nКонецФункции\n```",
                }]}
            source = (
                "Префикс = 1;\n" * 100
                + "Функция РассчитатьСебестоимость()\nВозврат 42;\nКонецФункции\n"
                + "ОченьБольшойХвост = 2;\n" * 10_000
            )
            return {
                "sourceComplete": True,
                "content": [{
                    "type": "text",
                    "text": json.dumps({"module": arguments["module"], "source": source}, ensure_ascii=False),
                }],
            }

    result = asyncio.run(retrieve_task_context(
        {
            "text": "Объясни функцию РассчитатьСебестоимость",
            "retrieval": [{"tool": "search_code", "arguments": {"query": "РассчитатьСебестоимость"}}],
        },
        AgentRegistry().get("1c_code_assistant"),
        snapshot,
        Connector(),
        max_result_chars=2_000,
    ))

    assert result.calls[1]["resultSizeChars"] > 200_000
    scoped_payload = json.loads(result.context[1]["data"]["content"][0]["text"])
    assert "Возврат 42;" in scoped_payload["source"]
    assert "ОченьБольшойХвост" not in scoped_payload["source"]
