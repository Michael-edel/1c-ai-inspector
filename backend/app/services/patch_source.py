"""Compare a proposal with a caller-provided current source snapshot."""

from hashlib import sha256
from typing import Any


def revalidate_source(
    expected_files: list[dict[str, Any]],
    current_files: list[dict[str, Any]],
    expected_revision: str | None,
    current_revision: str | None,
) -> dict[str, object]:
    mismatches: list[dict[str, object]] = []
    expected = {str(item.get("path")): item for item in expected_files}
    current: dict[str, dict[str, Any]] = {}
    for item in current_files:
        path = str(item.get("path", ""))
        if path in current:
            mismatches.append({"type": "duplicate_path", "path": path})
        current[path] = item

    if expected_revision is not None and current_revision != expected_revision:
        mismatches.append(
            {
                "type": "revision_mismatch",
                "expected": expected_revision,
                "actual": current_revision,
            }
        )

    for path, item in expected.items():
        current_item = current.get(path)
        if current_item is None:
            mismatches.append({"type": "missing_file", "path": path})
            continue
        content = current_item.get("current")
        if not isinstance(content, str):
            mismatches.append({"type": "content_invalid", "path": path})
            continue
        actual_sha = sha256(content.encode("utf-8")).hexdigest()
        expected_sha = item.get("originalSha256")
        if actual_sha != expected_sha:
            mismatches.append(
                {
                    "type": "content_mismatch",
                    "path": path,
                    "expectedSha256": expected_sha,
                    "actualSha256": actual_sha,
                }
            )

    for path in current:
        if path not in expected:
            mismatches.append({"type": "unexpected_file", "path": path})

    return {
        "valid": not mismatches,
        "sourceRevision": current_revision,
        "checkedFiles": len(current_files),
        "mismatches": mismatches,
    }
