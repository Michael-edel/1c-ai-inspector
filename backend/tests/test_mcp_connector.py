import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.mcp.connector import McpConnector, ToolNotAllowedError
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


def test_unknown_tool_is_rejected_before_http(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: pytest.fail("HTTP must not be called"))
    connector = McpConnector("http://mcp.test", _policy(tmp_path), transport=transport)

    with pytest.raises(ToolNotAllowedError):
        asyncio.run(connector.call_tool("delete_module", {}))
