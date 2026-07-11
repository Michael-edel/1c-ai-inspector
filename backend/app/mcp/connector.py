from typing import Any

import httpx

from app.mcp.policy import PolicySnapshot


class ToolNotAllowedError(PermissionError):
    """Raised before a forbidden tool can reach the MCP server."""


class McpConnector:
    def __init__(self, endpoint_url: str, policy: PolicySnapshot):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.policy = policy

    async def initialize(self) -> dict[str, Any]:
        return await self._request("initialize", {"protocolVersion": "2025-06-18"})

    async def list_tools(self) -> dict[str, Any]:
        return await self._request("tools/list", {})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = self.policy.published_tools.get(name)
        if contract is None:
            raise ToolNotAllowedError(f"MCP tool is not published: {name}")
        return await self._request("tools/call", {"name": name, "arguments": arguments})

    async def close(self) -> None:
        return None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.endpoint_url, json=payload)
            response.raise_for_status()
            body = response.json()
        if "error" in body:
            raise RuntimeError(f"MCP request failed: {body['error']}")
        return body.get("result", {})
