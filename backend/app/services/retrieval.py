import json
import re
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from app.agents.registry import AgentDefinition
from app.mcp.connector import McpConnector, McpTaskTimeoutError, ToolNotAllowedError
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


def tool_call_fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        [tool_name, arguments],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _serialized_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


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
    before_tool_call: Callable[[], bool] | None = None,
    completed_calls: dict[str, dict[str, Any]] | None = None,
    on_tool_call: Callable[[dict[str, Any]], None] | None = None,
    deadline: float | None = None,
    max_result_chars: int | None = None,
    max_methods_read: int | None = None,
) -> RetrievalResult:
    plan = request.get("retrieval", [])
    if not isinstance(plan, list):
        raise RetrievalError("RETRIEVAL_PLAN_INVALID")
    if len(plan) > max_tool_calls:
        raise RetrievalError("RETRIEVAL_LIMIT_EXCEEDED")
    allowed_categories = set(definition.required_capabilities)
    context: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    methods_read = 0
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
        if tool_name == "read_source":
            if max_methods_read is not None and methods_read >= max_methods_read:
                raise RetrievalError("METHOD_READ_LIMIT_EXCEEDED", calls)
            methods_read += 1
        if deadline is not None and time.monotonic() >= deadline:
            raise RetrievalError("TASK_TIMEOUT", calls)
        if before_tool_call is not None and not before_tool_call():
            raise RetrievalError("TASK_CANCELLED_BY_USER", calls)
        cached_call = (completed_calls or {}).get(tool_call_fingerprint(tool_name, arguments))
        if cached_call is not None:
            if not contract.idempotent:
                raise RetrievalError("NON_IDEMPOTENT_RETRY_BLOCKED", calls)
            output = cached_call.get("output")
            if not isinstance(output, dict):
                output = {}
            if max_result_chars is not None and _serialized_size(output) > max_result_chars:
                raise RetrievalError("MCP_RESULT_TOO_LARGE", calls)
            compacted_output = (
                _compact_search_output(
                    output,
                    arguments.get("query", ""),
                    arguments.get("category"),
                    arguments.get("module"),
                )
                if tool_name == "search_code"
                else output
            )
            calls.append({
                "toolName": tool_name,
                "input": arguments,
                "output": compacted_output,
                "status": "completed",
                "durationMs": 0,
                "reused": True,
            })
            context.append({"source": "MCP", "tool": tool_name, "data": compacted_output})
            continue
        started = time.perf_counter()
        try:
            if deadline is None:
                output = await connector.call_tool(tool_name, arguments)
            else:
                output = await connector.call_tool(tool_name, arguments, deadline=deadline)
        except McpTaskTimeoutError as exc:
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "TASK_TIMEOUT",
                "durationMs": int((time.perf_counter() - started) * 1000),
            }
            calls.append(call)
            if on_tool_call is not None:
                on_tool_call(call)
            raise RetrievalError("TASK_TIMEOUT", calls) from exc
        except Exception as exc:
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "MCP_TOOL_CALL_FAILED",
                "durationMs": int((time.perf_counter() - started) * 1000),
            }
            calls.append(call)
            if on_tool_call is not None:
                on_tool_call(call)
            raise RetrievalError("MCP_TOOL_CALL_FAILED", calls) from exc
        if max_result_chars is not None and _serialized_size(output) > max_result_chars:
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "MCP_RESULT_TOO_LARGE",
                "durationMs": int((time.perf_counter() - started) * 1000),
            }
            calls.append(call)
            if on_tool_call is not None:
                on_tool_call(call)
            raise RetrievalError("MCP_RESULT_TOO_LARGE", calls)
        compacted_output = _compact_search_output(
            output,
            arguments.get("query", ""),
            arguments.get("category"),
            arguments.get("module"),
        ) if tool_name == "search_code" else output
        call = {
            "toolName": tool_name,
            "input": arguments,
            "output": compacted_output,
            "status": "completed",
            "durationMs": int((time.perf_counter() - started) * 1000),
        }
        calls.append(call)
        if on_tool_call is not None:
            on_tool_call(call)
        context.append({"source": "MCP", "tool": tool_name, "data": compacted_output})
    return RetrievalResult(context=context, calls=calls)
