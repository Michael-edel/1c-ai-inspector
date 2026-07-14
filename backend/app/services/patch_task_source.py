"""Resolve a patch source from persisted read-only task evidence."""

import json
from dataclasses import dataclass
from typing import Any, Iterable


class PatchTaskSourceError(ValueError):
    """Raised when persisted task evidence cannot identify one source module."""


@dataclass(frozen=True)
class PersistedTaskSource:
    module: str
    source: str
    tool_call_id: str
    revision: str | None = None


def resolve_task_source(
    object_fqn: str,
    finding_module: str,
    tool_calls: Iterable[Any],
) -> PersistedTaskSource:
    sources: list[PersistedTaskSource] = []
    for call in tool_calls:
        if (
            getattr(call, "tool_name", None) != "read_source"
            or getattr(call, "mode", None) != "read-only"
            or getattr(call, "status", None) != "completed"
        ):
            continue
        output_json = getattr(call, "output_json", None)
        if not output_json:
            continue
        try:
            output = json.loads(output_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(output, dict):
            continue
        sources.extend(_sources_from_output(output, str(getattr(call, "id", ""))))

    if not sources:
        raise PatchTaskSourceError("PATCH_SOURCE_NOT_AVAILABLE")

    scored = [
        (source, _source_match_score(source.module, object_fqn, finding_module))
        for source in sources
    ]
    best_score = max(score for _, score in scored)
    best = [source for source, score in scored if score == best_score]
    unique = {(source.module, source.source): source for source in best}
    if best_score <= 0 and len(sources) != 1:
        raise PatchTaskSourceError("PATCH_SOURCE_NOT_AVAILABLE")
    if len(unique) != 1:
        raise PatchTaskSourceError("PATCH_SOURCE_AMBIGUOUS")
    return next(iter(unique.values()))


def _sources_from_output(output: dict[str, Any], tool_call_id: str) -> list[PersistedTaskSource]:
    candidates = [output]
    content = output.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                continue
            try:
                payload = json.loads(block["text"])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                candidates.append(payload)

    complete = output.get("sourceComplete") is True
    result: list[PersistedTaskSource] = []
    for candidate in candidates:
        module = candidate.get("module")
        source = candidate.get("source")
        if not (complete or candidate.get("sourceComplete") is True):
            continue
        if not isinstance(module, str) or not module.strip() or not isinstance(source, str):
            continue
        revision: str | None = None
        for key in ("sourceRevision", "revision", "commit"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                revision = value.strip()[:128]
                break
        result.append(
            PersistedTaskSource(
                module=module.strip(),
                source=source,
                tool_call_id=tool_call_id,
                revision=revision,
            )
        )
    return result


def _source_match_score(source_module: str, object_fqn: str, finding_module: str) -> int:
    source = source_module.casefold()
    module = finding_module.strip().casefold()
    object_name = object_fqn.rsplit(".", 1)[-1].strip().casefold()
    expected = f"{object_fqn}.{finding_module}".casefold()
    if source == expected:
        return 100
    score = 0
    if module and (source == module or source.endswith(f".{module}")):
        score += 40
    if object_name and object_name in source.split("."):
        score += 40
    return score
