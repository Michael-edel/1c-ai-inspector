from typing import Any

import httpx

from app.mcp.contracts import McpToolDefinition, McpToolsList, ToolContract
from app.mcp.policy import PolicySnapshot


class ToolNotAllowedError(PermissionError):
    """Raised before a forbidden tool can reach the MCP server."""


class McpConnector:
    def __init__(
        self,
        endpoint_url: str,
        policy: PolicySnapshot,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.policy = policy
        self.transport = transport

    async def initialize(self) -> dict[str, Any]:
        return await self._request("initialize", {"protocolVersion": "2025-06-18"})

    async def list_tools(self) -> dict[str, Any]:
        return await self._request("tools/list", {})

    async def discover_tools(self) -> list[ToolContract]:
        result = McpToolsList.model_validate(await self.list_tools())
        discovered: list[ToolContract] = []
        for raw_tool in result.tools:
            contract = self.policy.contract_for_raw_name(raw_tool.name)
            if contract is None:
                continue
            discovered.append(
                contract.model_copy(
                    update={"input_schema": raw_tool.input_schema or contract.input_schema}
                )
            )
        return discovered

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = self.policy.published_tools.get(name)
        if contract is None:
            contract = self.policy.contract_for_raw_name(name)
        if contract is None:
            raise ToolNotAllowedError(f"MCP tool is not published: {name}")
        if contract.original_name is None:
            raise ToolNotAllowedError(f"MCP tool has no original name: {name}")
        return await self._request(
            "tools/call", {"name": contract.original_name, "arguments": arguments}
        )

    async def close(self) -> None:
        return None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(self.endpoint_url, json=payload)
            response.raise_for_status()
            body = response.json()
        if "error" in body:
            raise RuntimeError(f"MCP request failed: {body['error']}")
        return body.get("result", {})
