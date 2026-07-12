import difflib
import hashlib
import json
import re
from typing import Any


class PatchProposalError(ValueError):
    """Raised when a patch proposal is unsafe or has no actual changes."""


def _safe_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise PatchProposalError("PATCH_PATH_INVALID")
    return normalized


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_patch_snapshot(files: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    chunks: list[str] = []
    snapshot: list[dict[str, Any]] = []
    for item in files:
        path = _safe_path(str(item.get("path", "")))
        original = item.get("original")
        proposed = item.get("proposed")
        if not isinstance(original, str) or not isinstance(proposed, str):
            raise PatchProposalError("PATCH_CONTENT_INVALID")
        if original == proposed:
            continue
        original_lines = original.splitlines(keepends=True)
        proposed_lines = proposed.splitlines(keepends=True)
        diff = "".join(
            difflib.unified_diff(
                original_lines,
                proposed_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="\n",
            )
        )
        added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++") )
        removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
        chunks.append(diff)
        snapshot.append(
            {
                "path": path,
                "originalSha256": _sha256(original),
                "proposedSha256": _sha256(proposed),
                "addedLines": added,
                "removedLines": removed,
            }
        )
    if not snapshot:
        raise PatchProposalError("PATCH_NO_CHANGES")
    return "\n".join(chunks), snapshot


def serialize_snapshot(snapshot: list[dict[str, Any]]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
