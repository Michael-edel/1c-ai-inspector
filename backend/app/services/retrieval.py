import time
from dataclasses import dataclass
from typing import Any

from app.agents.registry import AgentDefinition
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicySnapshot


class RetrievalError(ValueError):
    """Raised when a task requests an unsafe or malformed retrieval call."""


@dataclass(frozen=True)
class RetrievalResult:
    context: list[dict[str, Any]]
    calls: list[dict[str, Any]]


async def retrieve_task_context(
    request: dict[str, Any],
    definition: AgentDefinition,
    snapshot: PolicySnapshot,
    connector: McpConnector,
    max_tool_calls: int = 30,
) -> RetrievalResult:
    plan = request.get("retrieval", [])
    if not isinstance(plan, list):
        raise RetrievalError("RETRIEVAL_PLAN_INVALID")
    if len(plan) > max_tool_calls:
        raise RetrievalError("RETRIEVAL_LIMIT_EXCEEDED")
    allowed_categories = set(definition.required_capabilities)
    context: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for item in plan:
        if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
            raise RetrievalError("RETRIEVAL_STEP_INVALID")
        tool_name = item["tool"]
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            raise RetrievalError("RETRIEVAL_ARGUMENTS_INVALID")
        contract = snapshot.published_tools.get(tool_name)
        if contract is None:
            raise ToolNotAllowedError(f"MCP tool is not published: {tool_name}")
        if contract.category not in allowed_categories:
            raise RetrievalError("RETRIEVAL_CAPABILITY_NOT_ALLOWED")
        started = time.perf_counter()
        try:
            output = await connector.call_tool(tool_name, arguments)
        except Exception as exc:
            calls.append({
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "MCP_TOOL_CALL_FAILED",
                "durationMs": int((time.perf_counter() - started) * 1000),
            })
            raise RetrievalError("MCP_TOOL_CALL_FAILED") from exc
        calls.append({
            "toolName": tool_name,
            "input": arguments,
            "output": output,
            "status": "completed",
            "durationMs": int((time.perf_counter() - started) * 1000),
        })
        context.append({"source": "MCP", "tool": tool_name, "data": output})
    return RetrievalResult(context=context, calls=calls)
