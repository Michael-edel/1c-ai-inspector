import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.agents.registry import AgentRegistry
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicyProvider
from app.services.retrieval import retrieve_task_context


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
