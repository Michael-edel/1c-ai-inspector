import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from collections.abc import Callable
from copy import deepcopy
from threading import RLock
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


class SourcePayloadCache:
    """Bounded process-local cache for checksum-addressed method source."""

    def __init__(self, max_entries: int = 32, max_bytes: int = 8_000_000):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._items: OrderedDict[
            tuple[str, str, str], tuple[dict[str, Any], int]
        ] = OrderedDict()
        self._total_bytes = 0
        self._lock = RLock()

    def get(self, module: str, method: str, checksum: str) -> dict[str, Any] | None:
        key = (module, method, checksum)
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return deepcopy(item[0])

    def put(
        self,
        module: str,
        method: str,
        checksum: str,
        output: dict[str, Any],
    ) -> None:
        size = _serialized_bytes(output)
        if size > self.max_bytes:
            return
        key = (module, method, checksum)
        with self._lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._total_bytes -= previous[1]
            self._items[key] = (deepcopy(output), size)
            self._total_bytes += size
            while (
                len(self._items) > self.max_entries
                or self._total_bytes > self.max_bytes
            ):
                _, (_, evicted_size) = self._items.popitem(last=False)
                self._total_bytes -= evicted_size


_SOURCE_PAYLOAD_CACHE = SourcePayloadCache()
_V09_AUTOMATION_TOOLS = {
    "resolve_symbol",
    "get_source_checksum",
    "estimate_tool_payload",
    "read_method_source",
    "find_references",
}
_AUDIT_ONLY_TOOLS = {"get_source_checksum", "estimate_tool_payload"}


def _mcp_json_payload(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    content = output.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                continue
            try:
                payload = json.loads(item["text"])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                return payload
    return output


def _resolved_module(output: Any, symbol: str) -> str | None:
    matches = _mcp_json_payload(output).get("matches")
    if not isinstance(matches, list):
        return None
    modules = {
        item["module"].strip()
        for item in matches
        if isinstance(item, dict)
        and isinstance(item.get("module"), str)
        and item["module"].strip()
        and (
            not isinstance(item.get("symbol"), str)
            or item["symbol"].casefold() == symbol.casefold()
        )
    }
    return next(iter(modules)) if len(modules) == 1 else None


def _source_checksum(output: Any, module: str) -> tuple[str, str] | None:
    payload = _mcp_json_payload(output)
    checksum = payload.get("sha256")
    resolved_module = payload.get("module", module)
    if (
        not isinstance(resolved_module, str)
        or not resolved_module.strip()
        or not isinstance(checksum, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", checksum) is None
    ):
        return None
    return resolved_module.strip(), checksum.lower()


def _estimated_response_bytes(output: Any) -> int | None:
    value = _mcp_json_payload(output).get("responseBytes")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


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
        rf"^[ \t]*(?:Процедура|Функция)[ \t]+{re.escape(method)}[ \t]*\(",
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


def _compact_read_source_output(output: Any, method: str) -> Any:
    if not isinstance(output, dict):
        return output
    content = output.get("content")
    if not isinstance(content, list):
        return output
    declaration = re.compile(
        rf"^[ \t]*(?P<kind>Процедура|Функция)[ \t]+{re.escape(method)}[ \t]*\(",
        re.IGNORECASE | re.MULTILINE,
    )
    compacted: list[Any] = []
    found = False
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            continue
        try:
            payload = json.loads(block["text"])
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("source"), str):
            continue
        source = payload["source"]
        match = declaration.search(source)
        if match is None:
            continue
        terminator_name = "КонецПроцедуры" if match.group("kind").casefold() == "процедура" else "КонецФункции"
        terminator = re.compile(
            rf"^[ \t]*{terminator_name}[ \t]*;?[ \t]*\r?$",
            re.IGNORECASE | re.MULTILINE,
        ).search(source, match.start())
        if terminator is None:
            continue
        line_start = source.count("\n", 0, match.start()) + 1
        line_end = source.count("\n", 0, terminator.start()) + 1
        snippet = source[match.start():terminator.end()]
        scoped_source = "\n" * (line_start - 1) + snippet
        scoped_payload = {
            **payload,
            "source": scoped_source,
            "sourceComplete": True,
            "sourceScope": "method",
            "method": method,
            "sourceLineStart": line_start,
            "sourceLineEnd": line_end,
            "moduleTotalLines": len(source.splitlines()),
        }
        compacted.append({**block, "text": json.dumps(scoped_payload, ensure_ascii=False)})
        found = True
    if not found:
        return {
            "sourceComplete": False,
            "sourceScope": "method_not_found",
            "method": method,
            "content": [],
        }
    return {
        **output,
        "sourceComplete": True,
        "sourceScope": "method",
        "method": method,
        "content": compacted,
    }


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
    source_cache: SourcePayloadCache | None = None,
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
    source_cache = source_cache or _SOURCE_PAYLOAD_CACHE
    source_checksums: dict[str, str] = {}
    v09_available = _V09_AUTOMATION_TOOLS <= set(snapshot.published_tools)
    source_aware = definition.code in {"1c_code_assistant", "1c_audit_agent"}

    def enqueue_steps(steps: list[dict[str, Any]]) -> None:
        additions: list[dict[str, Any]] = []
        for step in steps:
            tool_name = step["tool"]
            arguments = step["arguments"]
            contract = snapshot.published_tools.get(tool_name)
            if contract is None or contract.category not in allowed_categories:
                continue
            duplicate = any(
                isinstance(item, dict)
                and item.get("tool") == tool_name
                and item.get("arguments") == arguments
                for item in [*pending, *additions]
            ) or any(
                call.get("toolName") == tool_name and call.get("input") == arguments
                for call in calls
            )
            if not duplicate:
                additions.append(step)
        if len(calls) + len(pending) + len(additions) > max_tool_calls:
            raise RetrievalError("RETRIEVAL_LIMIT_EXCEEDED", calls)
        pending[0:0] = additions

    def enqueue_search_fallback() -> None:
        if requested_method is None:
            return
        enqueue_steps([{
            "tool": "search_code",
            "arguments": {"query": requested_method, "mode": "exact", "limit": 50},
        }])

    def enqueue_source_chain(module: str) -> None:
        if requested_method is None:
            return
        if v09_available:
            enqueue_steps([
                {"tool": "get_source_checksum", "arguments": {"module": module}},
                {
                    "tool": "estimate_tool_payload",
                    "arguments": {
                        "tool": "read_method_source",
                        "module": module,
                        "method": requested_method,
                    },
                },
                {
                    "tool": "read_method_source",
                    "arguments": {"module": module, "method": requested_method},
                },
                {
                    "tool": "find_references",
                    "arguments": {"symbol": requested_method, "maxResults": 50},
                },
            ])
            return
        source_tool = (
            "read_method_source"
            if "read_method_source" in snapshot.published_tools
            else "read_source"
        )
        arguments = {"module": module}
        if source_tool == "read_method_source":
            arguments["method"] = requested_method
        enqueue_steps([{"tool": source_tool, "arguments": arguments}])

    def handle_navigation_output(
        output: Any, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        if not source_aware or requested_method is None:
            return
        if tool_name == "resolve_symbol":
            module = _resolved_module(output, requested_method)
            if module is None:
                enqueue_search_fallback()
            else:
                enqueue_source_chain(module)
            return
        if (
            tool_name == "search_code"
            and str(arguments.get("query", "")).casefold()
            == requested_method.casefold()
        ):
            module = _module_defining_method(output, requested_method)
            if module is not None:
                enqueue_source_chain(module)
            return
        if tool_name == "get_source_checksum":
            checksum = _source_checksum(output, str(arguments.get("module", "")))
            if checksum is not None:
                source_checksums[checksum[0]] = checksum[1]
            return
        if tool_name == "estimate_tool_payload":
            estimated_bytes = _estimated_response_bytes(output)
            if estimated_bytes is None:
                return
            if (
                max_result_bytes is not None
                and estimated_bytes > max_result_bytes
            ) or (
                max_task_mcp_bytes is not None
                and task_traffic_bytes + estimated_bytes > max_task_mcp_bytes
            ):
                raise RetrievalError("MCP_RESULT_TOO_LARGE", calls)

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
        if tool_name in {"read_source", "read_method_source"}:
            if max_methods_read is not None and methods_read >= max_methods_read:
                raise RetrievalError("METHOD_READ_LIMIT_EXCEEDED", calls)
            methods_read += 1
        if deadline is not None and time.monotonic() >= deadline:
            raise RetrievalError("TASK_TIMEOUT", calls)
        if before_tool_call is not None and not before_tool_call():
            raise RetrievalError("TASK_CANCELLED_BY_USER", calls)
        if tool_name == "read_method_source":
            module = arguments.get("module")
            method = arguments.get("method")
            checksum = source_checksums.get(module) if isinstance(module, str) else None
            cached_output = (
                source_cache.get(module, method, checksum)
                if isinstance(module, str)
                and isinstance(method, str)
                and checksum is not None
                else None
            )
            if cached_output is not None:
                result_size_chars = _serialized_size(cached_output)
                if max_result_chars is not None and result_size_chars > max_result_chars:
                    raise RetrievalError("MCP_RESULT_TOO_LARGE", calls)
                calls.append({
                    "toolName": tool_name,
                    "input": arguments,
                    "output": cached_output,
                    "status": "completed",
                    "durationMs": 0,
                    "requestSizeBytes": 0,
                    "resultSizeChars": result_size_chars,
                    "resultSizeBytes": 0,
                    "cachedPayloadBytes": _serialized_bytes(cached_output),
                    "sourceChecksum": checksum,
                    "reused": True,
                    "cacheHit": True,
                })
                context.append({
                    "source": "MCP",
                    "tool": tool_name,
                    "data": cached_output,
                })
                continue
        cached_call = (completed_calls or {}).get(tool_call_fingerprint(tool_name, arguments))
        if cached_call is not None:
            if not contract.idempotent:
                raise RetrievalError("NON_IDEMPOTENT_RETRY_BLOCKED", calls)
            output = cached_call.get("output")
            if not isinstance(output, dict):
                output = {}
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
            context_output = (
                _compact_read_source_output(compacted_output, requested_method)
                if tool_name == "read_source" and requested_method is not None
                else compacted_output
            )
            if max_result_chars is not None and _serialized_size(context_output) > max_result_chars:
                raise RetrievalError("MCP_RESULT_TOO_LARGE", calls)
            calls.append({
                "toolName": tool_name,
                "input": arguments,
                "output": compacted_output,
                "status": "completed",
                "durationMs": 0,
                "resultSizeChars": result_size_chars,
                "requestSizeBytes": 0,
                "resultSizeBytes": 0,
                "reused": True,
            })
            if tool_name not in _AUDIT_ONLY_TOOLS:
                context.append({"source": "MCP", "tool": tool_name, "data": context_output})
            handle_navigation_output(compacted_output, tool_name, arguments)
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
        compacted_output = _compact_search_output(
            output,
            arguments.get("query", ""),
            arguments.get("category"),
            arguments.get("module"),
        ) if tool_name == "search_code" else output
        context_output = (
            _compact_read_source_output(compacted_output, requested_method)
            if tool_name == "read_source" and requested_method is not None
            else compacted_output
        )
        if max_result_chars is not None and _serialized_size(context_output) > max_result_chars:
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
        if tool_name == "read_method_source" and isinstance(compacted_output, dict):
            module = arguments.get("module")
            method = arguments.get("method")
            checksum = source_checksums.get(module) if isinstance(module, str) else None
            if (
                isinstance(module, str)
                and isinstance(method, str)
                and checksum is not None
            ):
                source_cache.put(module, method, checksum, compacted_output)
                call["sourceChecksum"] = checksum
        if tool_name not in _AUDIT_ONLY_TOOLS:
            context.append({"source": "MCP", "tool": tool_name, "data": context_output})
        handle_navigation_output(compacted_output, tool_name, arguments)
    return RetrievalResult(context=context, calls=calls)
