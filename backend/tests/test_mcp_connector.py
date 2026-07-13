import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.contracts import ToolContract
from app.mcp.policy import PolicyProvider


def _policy(tmp_path: Path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Read Module.Source: {name: raw, category: bsl.read, mode: read-only}\n",
        encoding="utf-8",
    )
    return PolicyProvider(path).load()


def test_discovery_uses_policy_and_call_sends_raw_name(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body["method"] == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-1"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"serverInfo": {}}},
            )
        if body["method"] == "tools/list":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [
                    {"name": "Read Module.Source", "inputSchema": {"type": "object"}}
                ]}},
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}},
            )

    connector = McpConnector(
        "http://mcp.test",
        _policy(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    async def scenario() -> tuple[list[object], dict[str, object]]:
        discovered = await connector.discover_tools()
        result = await connector.call_tool("read_module_source", {"object": "Catalog.X"})
        await connector.close()
        return discovered, result

    discovered, result = asyncio.run(scenario())

    assert [tool.name for tool in discovered] == ["read_module_source"]
    assert discovered[0].input_schema == {"type": "object"}
    assert result == {"content": []}
    assert requests[-1]["params"]["name"] == "Read Module.Source"
    assert requests[0]["method"] == "initialize"
    assert requests[1]["method"] == "notifications/initialized"
    assert all(request["method"] != "tools/call" or request["id"] > 1 for request in requests)


def test_protocol_header_is_sent_after_initialize(tmp_path: Path) -> None:
    headers_seen: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        headers_seen.append(request.headers.get("MCP-Protocol-Version"))
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}})

    async def scenario() -> None:
        connector = McpConnector(
            "http://mcp.test", _policy(tmp_path), transport=httpx.MockTransport(handler)
        )
        await connector.list_tools()
        await connector.close()

    asyncio.run(scenario())
    assert headers_seen[:2] == [None, "2025-06-18"]


def test_mismatched_response_id_is_rejected(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id", 99) + 1, "result": {}})

    connector = McpConnector(
        "http://mcp.test", _policy(tmp_path), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match="response id"):
        asyncio.run(connector.initialize())


def test_read_only_tool_retries_transient_http_failure(tmp_path: Path) -> None:
    path = tmp_path / "retry-policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Read Module.Source: {name: raw, category: bsl.read, mode: read-only, retries: 1}\n",
        encoding="utf-8",
    )
    policy = PolicyProvider(path).load()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})

    async def scenario() -> dict[str, object]:
        connector = McpConnector("http://mcp.test", policy, transport=httpx.MockTransport(handler))
        try:
            return await connector.call_tool("read_module_source", {})
        finally:
            await connector.close()

    assert asyncio.run(scenario()) == {"content": []}
    assert calls == 2


def test_non_idempotent_tool_does_not_retry_transient_http_failure(tmp_path: Path) -> None:
    path = tmp_path / "non-idempotent-policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Read Module.Source: {name: raw, category: bsl.read, mode: read-only, retries: 2, idempotent: false}\n",
        encoding="utf-8",
    )
    policy = PolicyProvider(path).load()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        calls += 1
        return httpx.Response(503)

    async def scenario() -> None:
        connector = McpConnector("http://mcp.test", policy, transport=httpx.MockTransport(handler))
        try:
            await connector.call_tool("read_module_source", {})
        finally:
            await connector.close()

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(scenario())
    assert calls == 1


def test_bridge_transport_uses_rest_endpoints_and_bearer_token(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer bridge-secret"
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "tools_count": 1})
        if request.url.path == "/tools":
            return httpx.Response(200, json={"tools": [{"name": "Read Module.Source"}]})
        body = json.loads(request.content)
        assert request.url.path == "/tools/call"
        assert body == {"name": "Read Module.Source", "arguments": {"object": "Catalog.X"}}
        return httpx.Response(200, json={"tool": body["name"], "result": {"content": []}})

    async def scenario() -> tuple[list[ToolContract], dict[str, object]]:
        connector = McpConnector(
            "http://bridge.test",
            _policy(tmp_path),
            transport=httpx.MockTransport(handler),
            transport_mode="bridge",
            access_token="bridge-secret",
        )
        try:
            return (
                await connector.discover_tools(),
                await connector.call_tool("read_module_source", {"object": "Catalog.X"}),
            )
        finally:
            await connector.close()

    discovered, result = asyncio.run(scenario())
    assert [tool.name for tool in discovered] == ["read_module_source"]
    assert result == {"content": []}
    assert [request.url.path for request in requests] == ["/health", "/tools", "/tools/call"]


def test_unknown_tool_is_rejected_before_http(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: pytest.fail("HTTP must not be called"))
    connector = McpConnector("http://mcp.test", _policy(tmp_path), transport=transport)

    with pytest.raises(ToolNotAllowedError):
        asyncio.run(connector.call_tool("delete_module", {}))


def test_streamable_http_sse_response_is_decoded(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content='event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n\n',
        )

    async def scenario() -> list[object]:
        connector = McpConnector(
            "http://mcp.test",
            _policy(tmp_path),
            transport=httpx.MockTransport(handler),
        )
        result = await connector.discover_tools()
        await connector.close()
        return result

    assert asyncio.run(scenario()) == []
