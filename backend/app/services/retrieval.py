import json
import re
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from app.agents.registry import AgentDefinition
from app.mcp.connector import McpConnector, McpTaskTimeoutError, ToolNotAllowedError
from app.mcp.policy import PolicySnapshot
from app.services.source_retrieval_plan import extract_method_reference
from app.services.traffic import TrafficLimitExceeded


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


def _serialized_bytes(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    )


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


def _module_defining_method(output: Any, method: str) -> str | None:
    if not isinstance(output, dict):
        return None
    content = output.get("content")
    if not isinstance(content, list):
        return None
    declaration = re.compile(
        rf"^\s*(?:Процедура|Функция)\s+{re.escape(method)}\s*\(",
        re.IGNORECASE | re.MULTILINE,
    )
    modules: set[str] = set()
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            continue
        for section in re.split(r"(?=^### )", block["text"], flags=re.MULTILINE):
            if not section.startswith("### ") or declaration.search(section) is None:
                continue
            header = section.splitlines()[0]
            match = re.match(r"^###\s+(.+?)\s+\((?:строка|line)\b", header, re.IGNORECASE)
            if match is not None:
                modules.add(match.group(1).strip())
    return next(iter(modules)) if len(modules) == 1 else None


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
    max_result_bytes: int | None = None,
    max_task_mcp_bytes: int | None = None,
    max_methods_read: int | None = None,
    reserve_traffic: Callable[[int], Any] | None = None,
    finalize_traffic: Callable[[Any, int], None] | None = None,
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
    task_traffic_bytes = 0
    pending = list(plan)
    requested_method = extract_method_reference(request)

    def enqueue_source_read(output: Any, tool_name: str, arguments: dict[str, Any]) -> None:
        if (
            tool_name != "search_code"
            or definition.code not in {"1c_code_assistant", "1c_audit_agent"}
            or requested_method is None
            or str(arguments.get("query", "")).casefold() != requested_method.casefold()
        ):
            return
        module = _module_defining_method(output, requested_method)
        if module is None:
            return
        source_arguments = {"module": module}
        already_planned = any(
            isinstance(step, dict)
            and step.get("tool") == "read_source"
            and step.get("arguments") == source_arguments
            for step in pending
        )
        already_called = any(
            call.get("toolName") == "read_source" and call.get("input") == source_arguments
            for call in calls
        )
        if already_planned or already_called:
            return
        contract = snapshot.published_tools.get("read_source")
        if contract is None or contract.category not in allowed_categories:
            return
        if len(calls) + len(pending) + 1 > max_tool_calls:
            raise RetrievalError("RETRIEVAL_LIMIT_EXCEEDED", calls)
        pending.insert(0, {"tool": "read_source", "arguments": source_arguments})

    while pending:
        item = pending.pop(0)
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
            result_size_chars = _serialized_size(output)
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
                "resultSizeChars": result_size_chars,
                "reused": True,
            })
            context.append({"source": "MCP", "tool": tool_name, "data": compacted_output})
            enqueue_source_read(compacted_output, tool_name, arguments)
            continue
        request_size_bytes = _serialized_bytes({"tool": tool_name, "arguments": arguments})
        reservation = None
        reservation_bytes = request_size_bytes + (max_result_bytes or 0)
        if max_task_mcp_bytes is not None and task_traffic_bytes + reservation_bytes > max_task_mcp_bytes:
            raise RetrievalError("TASK_TRAFFIC_LIMIT_EXCEEDED", calls)
        if reserve_traffic is not None and reservation_bytes > 0:
            try:
                reservation = reserve_traffic(reservation_bytes)
            except TrafficLimitExceeded as exc:
                raise RetrievalError("MONTHLY_TRAFFIC_LIMIT_EXCEEDED", calls) from exc
        started = time.perf_counter()
        try:
            if deadline is None:
                output = await connector.call_tool(tool_name, arguments)
            else:
                output = await connector.call_tool(tool_name, arguments, deadline=deadline)
        except McpTaskTimeoutError as exc:
            if reservation is not None and finalize_traffic is not None:
                finalize_traffic(reservation, request_size_bytes)
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "TASK_TIMEOUT",
                "durationMs": int((time.perf_counter() - started) * 1000),
                "requestSizeBytes": request_size_bytes,
            }
            calls.append(call)
            if on_tool_call is not None:
                on_tool_call(call)
            raise RetrievalError("TASK_TIMEOUT", calls) from exc
        except Exception as exc:
            if reservation is not None and finalize_traffic is not None:
                finalize_traffic(reservation, request_size_bytes)
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "MCP_TOOL_CALL_FAILED",
                "durationMs": int((time.perf_counter() - started) * 1000),
                "requestSizeBytes": request_size_bytes,
            }
            calls.append(call)
            if on_tool_call is not None:
                on_tool_call(call)
            raise RetrievalError("MCP_TOOL_CALL_FAILED", calls) from exc
        result_size_chars = _serialized_size(output)
        result_size_bytes = _serialized_bytes(output)
        actual_traffic_bytes = request_size_bytes + result_size_bytes
        if reservation is not None and finalize_traffic is not None:
            finalize_traffic(reservation, actual_traffic_bytes)
        task_traffic_bytes += actual_traffic_bytes
        if max_result_bytes is not None and result_size_bytes > max_result_bytes:
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "MCP_RESULT_TOO_LARGE",
                "durationMs": int((time.perf_counter() - started) * 1000),
                "requestSizeBytes": request_size_bytes,
                "resultSizeChars": result_size_chars,
                "resultSizeBytes": result_size_bytes,
            }
            calls.append(call)
            if on_tool_call is not None:
                on_tool_call(call)
            raise RetrievalError("MCP_RESULT_TOO_LARGE", calls)
        if max_result_chars is not None and result_size_chars > max_result_chars:
            call = {
                "toolName": tool_name,
                "input": arguments,
                "output": None,
                "status": "failed",
                "errorCode": "MCP_RESULT_TOO_LARGE",
                "durationMs": int((time.perf_counter() - started) * 1000),
                "requestSizeBytes": request_size_bytes,
                "resultSizeChars": result_size_chars,
                "resultSizeBytes": result_size_bytes,
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
            "requestSizeBytes": request_size_bytes,
            "resultSizeChars": result_size_chars,
            "resultSizeBytes": result_size_bytes,
        }
        calls.append(call)
        if on_tool_call is not None:
            on_tool_call(call)
        context.append({"source": "MCP", "tool": tool_name, "data": compacted_output})
        enqueue_source_read(compacted_output, tool_name, arguments)
    return RetrievalResult(context=context, calls=calls)
