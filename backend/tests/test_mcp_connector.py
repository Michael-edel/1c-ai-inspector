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
        if body["method"] == "tools/list":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [
                    {"name": "Read Module.Source", "inputSchema": {"type": "object"}}
                ]}},
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}},
        )

    connector = McpConnector(
        "http://mcp.test",
        _policy(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    discovered = asyncio.run(connector.discover_tools())
    result = asyncio.run(connector.call_tool("read_module_source", {"object": "Catalog.X"}))

    assert [tool.name for tool in discovered] == ["read_module_source"]
    assert discovered[0].input_schema == {"type": "object"}
    assert result == {"content": []}
    assert requests[-1]["params"]["name"] == "Read Module.Source"


def test_unknown_tool_is_rejected_before_http(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: pytest.fail("HTTP must not be called"))
    connector = McpConnector("http://mcp.test", _policy(tmp_path), transport=transport)

    with pytest.raises(ToolNotAllowedError):
        asyncio.run(connector.call_tool("delete_module", {}))
