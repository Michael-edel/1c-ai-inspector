from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any


_SOURCE_AWARE_AGENTS = {"1c_code_assistant", "1c_audit_agent"}
_V09_AUTOMATION_TOOLS = {
    "resolve_symbol",
    "get_source_checksum",
    "estimate_tool_payload",
    "read_method_source",
    "find_references",
}
_SOURCE_NAVIGATION_TOOLS = _V09_AUTOMATION_TOOLS | {
    "bsl_syntax_help",
    "read_source",
    "search_code",
}
_OBJECT_REFERENCE = re.compile(
    r"(?:^|[\s(])"
    r"(?P<type>документ[A-Za-zА-Яа-яЁё0-9_]*|справочник[A-Za-zА-Яа-яЁё0-9_]*|"
    r"регистр[A-Za-zА-Яа-яЁё0-9_]*(?:\s+(?:сведени[йя]|накоплени[йя]))?)"
    r"\s*[.:]?\s*(?P<name>[A-Za-zА-Яа-яЁё0-9_]+)",
    re.IGNORECASE,
)
_METHOD_REFERENCE = re.compile(
    r"\b(?:процедур\w*|функци\w*|метод\w*)\s+"
    r"(?P<name>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\b",
    re.IGNORECASE,
)
_QUERY_START = re.compile(
    r"(?:^|[\r\n:])\s*(?P<query>ВЫБРАТЬ\b[\s\S]*)",
    re.IGNORECASE,
)


def extract_method_reference(request: dict[str, Any]) -> str | None:
    text = request.get("text")
    if not isinstance(text, str):
        return None
    match = _METHOD_REFERENCE.search(text)
    return match.group("name") if match is not None else None


def extract_query_text(request: dict[str, Any]) -> str | None:
    candidates: list[Any] = [request.get("query"), request.get("queryText"), request.get("text")]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        match = _QUERY_START.search(candidate)
        if match is not None:
            return match.group("query").removesuffix("```").strip()
    return None


def query_agent_request_is_supported(request: dict[str, Any]) -> bool:
    return extract_query_text(request) is not None


def _object_source_target(object_match: re.Match[str]) -> tuple[str, str, str]:
    object_type = re.sub(r"\s+", "", object_match.group("type").casefold())
    if object_type.startswith("документ"):
        return "Документ", "МодульОбъекта", "Документ"
    if object_type.startswith("справочник"):
        return "Справочник", "МодульОбъекта", "Справочник"
    if object_type.startswith("регистр") and "накоплен" in object_type:
        return "РегистрНакопления", "МодульНабораЗаписей", "РегистрНакопления"
    return "РегистрСведений", "МодульНабораЗаписей", "РегистрСведений"


def _v09_method_plan(
    request: dict[str, Any],
    method: str,
    object_match: re.Match[str] | None,
    published_tools: Collection[str],
) -> dict[str, Any]:
    preserved: list[Any] = []
    has_metadata_summary = False
    for step in request.get("retrieval", []):
        if not isinstance(step, dict):
            preserved.append(step)
            continue
        tool_name = step.get("tool")
        if tool_name in _SOURCE_NAVIGATION_TOOLS:
            continue
        if (
            object_match is not None
            and tool_name == "get_object_structure"
            and "get_edt_metadata_summary" in published_tools
        ):
            continue
        if tool_name == "get_edt_metadata_summary":
            has_metadata_summary = True
        preserved.append(step)

    resolve_arguments: dict[str, Any] = {"symbol": method}
    if object_match is not None:
        category, module_type, metadata_type = _object_source_target(object_match)
        resolve_arguments["module"] = f"{category}.{object_match.group('name')}.{module_type}"
        if not has_metadata_summary and "get_edt_metadata_summary" in published_tools:
            preserved.append({
                "tool": "get_edt_metadata_summary",
                "arguments": {"objectType": metadata_type, "name": object_match.group("name")},
            })

    return {
        **request,
        "retrieval": [
            {"tool": "resolve_symbol", "arguments": resolve_arguments},
            *preserved,
        ],
    }


def ensure_full_source_retrieval(
    request: dict[str, Any],
    agent_code: str,
    published_tools: Collection[str],
) -> dict[str, Any]:
    """Normalize retrieval and enforce full-source reads for source-aware requests."""
    plan = request.get("retrieval", [])
    if not isinstance(plan, list):
        return request

    if agent_code == "1c_query_agent":
        query_text = extract_query_text(request)
        if query_text is None:
            return request
        normalized_plan = []
        for step in plan:
            if not isinstance(step, dict) or step.get("tool") != "validate_query":
                normalized_plan.append(step)
                continue
            arguments = step.get("arguments")
            normalized_plan.append({
                **step,
                "arguments": {**(arguments if isinstance(arguments, dict) else {}), "query": query_text},
            })
        return request if normalized_plan == plan else {**request, "retrieval": normalized_plan}

    if agent_code not in _SOURCE_AWARE_AGENTS:
        return request

    method = extract_method_reference(request)
    text = request.get("text")
    object_match = _OBJECT_REFERENCE.search(text) if isinstance(text, str) else None
    if method is not None and _V09_AUTOMATION_TOOLS <= set(published_tools):
        return _v09_method_plan(request, method, object_match, published_tools)
    direct_method_read = (
        method is not None
        and object_match is not None
        and "read_method_source" in published_tools
    )
    normalized_plan: list[Any] = []
    has_search = False
    has_metadata_summary = False
    for step in plan:
        if not isinstance(step, dict):
            normalized_plan.append(step)
            continue
        tool_name = step.get("tool")
        arguments = step.get("arguments")
        normalized_arguments = arguments if isinstance(arguments, dict) else {}
        if method and tool_name == "bsl_syntax_help":
            continue
        if direct_method_read and tool_name == "search_code":
            continue
        if method and tool_name == "read_source" and "read_method_source" in published_tools:
            continue
        if method and tool_name == "read_method_source":
            normalized_arguments = {**normalized_arguments, "method": method}
        if (
            object_match is not None
            and tool_name == "get_object_structure"
            and "get_edt_metadata_summary" in published_tools
        ):
            continue
        if tool_name == "get_edt_metadata_summary":
            has_metadata_summary = True
        if method and tool_name == "search_code":
            normalized_arguments = {**normalized_arguments, "query": method}
            has_search = True
            normalized_arguments["mode"] = "exact"
            limit = normalized_arguments.get("limit", 0)
            normalized_arguments["limit"] = max(limit if isinstance(limit, int) else 0, 50)
        elif tool_name == "search_code":
            has_search = True
        normalized_plan.append({**step, "arguments": normalized_arguments})

    if method and not direct_method_read and not has_search and "search_code" in published_tools:
        normalized_plan.append({
            "tool": "search_code",
            "arguments": {"query": method, "limit": 50, "mode": "exact"},
        })

    if object_match is not None and not has_metadata_summary and "get_edt_metadata_summary" in published_tools:
        object_type = re.sub(r"\s+", "", object_match.group("type").casefold())
        normalized_plan.append({
            "tool": "get_edt_metadata_summary",
            "arguments": {
                "objectType": (
                    "Документ" if object_type.startswith("документ")
                    else "Справочник" if object_type.startswith("справочник")
                    else "РегистрНакопления" if object_type.startswith("регистр") and "накоплен" in object_type
                    else "РегистрСведений"
                ),
                "name": object_match.group("name"),
            },
        })

    normalized_request = request if normalized_plan == plan else {**request, "retrieval": normalized_plan}
    source_tool = (
        "read_method_source"
        if method is not None and "read_method_source" in published_tools
        else "read_source"
    )
    if source_tool not in published_tools:
        return normalized_request
    if object_match is None:
        return normalized_request

    normalized_plan = normalized_request.get("retrieval", [])
    if any(isinstance(step, dict) and step.get("tool") == source_tool for step in normalized_plan):
        return normalized_request

    category, module_type, _ = _object_source_target(object_match)

    module = f"{category}.{object_match.group('name')}.{module_type}"
    source_arguments = {"module": module}
    if source_tool == "read_method_source" and method is not None:
        source_arguments["method"] = method
    return {
        **normalized_request,
        "retrieval": [
            {"tool": source_tool, "arguments": source_arguments},
            *normalized_plan,
        ],
    }
