import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.agents.registry import AgentRegistry
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicyProvider
from app.services.retrieval import RetrievalError, _compact_search_output, retrieve_task_context


def _snapshot(tmp_path: Path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Read Source: {name: raw, category: bsl.read, mode: read-only}\n",
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
