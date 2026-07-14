from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any


_SOURCE_AWARE_AGENTS = {"1c_code_assistant", "1c_audit_agent"}
_OBJECT_REFERENCE = re.compile(
    r"(?:^|[\s(])"
    r"(?P<type>документ[A-Za-zА-Яа-яЁё0-9_]*|справочник[A-Za-zА-Яа-яЁё0-9_]*|регистр[A-Za-zА-Яа-яЁё0-9_]*)"
    r"(?:\s+сведени[йя])?"
    r"\s*[.:]?\s*(?P<name>[A-Za-zА-Яа-яЁё0-9_]+)",
    re.IGNORECASE,
)


def ensure_full_source_retrieval(
    request: dict[str, Any],
    agent_code: str,
    published_tools: Collection[str],
) -> dict[str, Any]:
    """Prepend a policy-published full-source read for an explicit 1C object reference."""
    if agent_code not in _SOURCE_AWARE_AGENTS or "read_source" not in published_tools:
        return request

    text = request.get("text")
    if not isinstance(text, str):
        return request
    match = _OBJECT_REFERENCE.search(text)
    if match is None:
        return request

    plan = request.get("retrieval", [])
    if not isinstance(plan, list):
        return request
    if any(isinstance(step, dict) and step.get("tool") == "read_source" for step in plan):
        return request

    object_type = match.group("type").casefold()
    if object_type.startswith("документ"):
        category = "Документ"
        module_type = "МодульОбъекта"
    elif object_type.startswith("справочник"):
        category = "Справочник"
        module_type = "МодульОбъекта"
    else:
        category = "РегистрСведений"
        module_type = "МодульНабораЗаписей"

    module = f"{category}.{match.group('name')}.{module_type}"
    return {
        **request,
        "retrieval": [
            {"tool": "read_source", "arguments": {"module": module}},
            *plan,
        ],
    }
