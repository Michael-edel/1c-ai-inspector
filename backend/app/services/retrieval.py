import re
import time
from dataclasses import dataclass
from typing import Any

from app.agents.registry import AgentDefinition
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.mcp.policy import PolicySnapshot


class RetrievalError(ValueError):
    """Raised when a task requests an unsafe or malformed retrieval call."""

    def __init__(self, code: str, calls: list[dict[str, Any]] | None = None):
        super().__init__(code)
        self.code = code
        self.calls = calls or []


@dataclass(frozen=True)
class RetrievalResult:
    context: list[dict[str, Any]]
    calls: list[dict[str, Any]]


def _compact_search_output(output: Any, query: str, category: Any, module: Any) -> Any:
    if not isinstance(output, dict) or not isinstance(query, str) or not query.strip():
        return output
    if not isinstance(category, str) or not isinstance(module, str):
        return output
    content = output.get("content")
    if not isinstance(content, list):
        return output

    needle = query.strip().casefold()
    compacted: list[Any] = []
    for item in content:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            compacted.append(item)
            continue
        text = item["text"]
        sections = re.split(r"(?=^### )", text, flags=re.MULTILINE)
        matches = []
        for section in sections:
            if not section.startswith("### "):
                continue
            header = section.splitlines()[0].casefold()
            if needle not in header:
                continue
            if isinstance(category, str) and isinstance(module, str):
                if category.casefold() not in header or module.casefold() not in header:
                    continue
            matches.append(section.strip())
        if isinstance(category, str) and isinstance(module, str):
            compacted_text = "\n\n".join(matches)
        else:
            compacted_text = "\n\n".join(matches) if matches else text
        compacted.append({**item, "text": compacted_text})
    return {**output, "content": compacted}


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
            raise RetrievalError("MCP_TOOL_CALL_FAILED", calls) from exc
        compacted_output = _compact_search_output(
            output,
            arguments.get("query", ""),
            arguments.get("category"),
            arguments.get("module"),
        ) if tool_name == "search_code" else output
        calls.append({
            "toolName": tool_name,
            "input": arguments,
            "output": compacted_output,
            "status": "completed",
            "durationMs": int((time.perf_counter() - started) * 1000),
        })
        context.append({"source": "MCP", "tool": tool_name, "data": compacted_output})
    return RetrievalResult(context=context, calls=calls)
