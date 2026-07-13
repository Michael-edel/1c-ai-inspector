import asyncio
import json
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
        transport_mode: str = "streamable-http",
        access_token: str | None = None,
    ):
        self.endpoint_url = endpoint_url.rstrip("/")
        self.policy = policy
        self.transport = transport
        self.transport_mode = transport_mode
        self.access_token = access_token
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        self._session_id: str | None = None
        self._initialized = False
        self._protocol_version = "2025-06-18"

    async def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return {}
        if self.transport_mode == "bridge":
            result = await self._bridge_request("GET", "/health")
            self._initialized = True
            return result
        result = await self._request(
            "initialize",
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "1c-ai-inspector", "version": "0.1.0"},
            },
        )
        self._initialized = True
        try:
            await self._notify("notifications/initialized", {})
        except Exception:
            self._initialized = False
            raise
        return result

    async def list_tools(self) -> dict[str, Any]:
        if self.transport_mode == "bridge":
            await self.initialize()
            return await self._bridge_request("GET", "/tools")
        await self.initialize()
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
        await self.initialize()
        for attempt in range(contract.retries + 1):
            try:
                return await asyncio.wait_for(
                    self._call_tool_once(contract.original_name, arguments),
                    timeout=contract.timeout_sec,
                )
            except (httpx.RequestError, httpx.HTTPStatusError, asyncio.TimeoutError):
                if attempt >= contract.retries or not contract.idempotent:
                    raise
                await asyncio.sleep(min(2**attempt, 5))
        raise RuntimeError("MCP retry loop ended unexpectedly")

    async def _call_tool_once(self, original_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.transport_mode == "bridge":
            return await self._bridge_request(
                "POST", "/tools/call", {"name": original_name, "arguments": arguments}
            )
        return await self._request(
            "tools/call", {"name": original_name, "arguments": arguments}
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        response = await self._post(payload)
        body = self._decode_response(response)
        if body.get("id") != self._request_id:
            raise RuntimeError("MCP response id does not match request")
        if "error" in body:
            raise RuntimeError(f"MCP request failed: {body['error']}")
        return body.get("result", {})

    async def _bridge_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30, transport=self.transport)
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        response = await self._client.request(
            method,
            f"{self.endpoint_url}{path}",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("MCP bridge response is not an object")
        if "error" in body:
            raise RuntimeError(f"MCP bridge request failed: {body['error']}")
        return body.get("result", body)

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            events = [
                line.removeprefix("data: ").strip()
                for line in response.text.splitlines()
                if line.startswith("data:")
            ]
            if not events:
                raise RuntimeError("MCP stream contained no data")
            return json.loads(events[-1])
        return response.json()

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params})

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30, transport=self.transport)
        headers = {"Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self._initialized:
            headers["MCP-Protocol-Version"] = self._protocol_version
        response = await self._client.post(self.endpoint_url, json=payload, headers=headers)
        response.raise_for_status()
        self._session_id = response.headers.get("Mcp-Session-Id", self._session_id)
        return response
