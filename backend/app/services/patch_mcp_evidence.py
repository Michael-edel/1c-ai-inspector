"""Collect bounded evidence from a published read-only MCP search tool."""

from typing import Any


def extract_search_evidence(result: dict[str, Any], limit: int = 20) -> list[str]:
    values: list[str] = []

    def visit(value: Any) -> None:
        if len(values) >= limit:
            return
        if isinstance(value, dict):
            if isinstance(value.get("path"), str):
                line = value.get("line") or value.get("lineNumber")
                text = value.get("text") or value.get("snippet") or value.get("match")
                if isinstance(text, str):
                    location = f"{value['path']}:{line}" if line is not None else value["path"]
                    values.append(f"{location}: {text[:400]}")
                    return
            if isinstance(value.get("text"), str) and value.get("type") == "text":
                values.append(value["text"][:400])
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(result)
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique[:limit]
