"""Run deterministic, proposal-only validation gates before approval."""

from pathlib import PurePosixPath
from typing import Any


ALLOWED_EXTENSIONS = {".bsl", ".xml", ".json", ".mdo", ".yaml", ".yml"}


def validate_patch_proposal(
    files: list[dict[str, Any]], diff_text: str | None, source_status: str
) -> dict[str, object]:
    issues: list[dict[str, str]] = []
    if source_status != "valid":
        issues.append({"code": "SOURCE_NOT_VALIDATED", "message": "Source snapshot is not valid"})
    if not diff_text or not diff_text.strip():
        issues.append({"code": "PATCH_DIFF_EMPTY", "message": "Unified diff is empty"})
    elif "--- a/" not in diff_text or "+++ b/" not in diff_text:
        issues.append({"code": "PATCH_DIFF_INVALID", "message": "Unified diff headers are missing"})

    for item in files:
        path = PurePosixPath(str(item.get("path", "")))
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            issues.append(
                {
                    "code": "PATCH_FILE_TYPE_UNSUPPORTED",
                    "message": f"Unsupported patch file type: {path.suffix or '<none>'}",
                }
            )
        if item.get("originalSha256") == item.get("proposedSha256"):
            issues.append({"code": "PATCH_NO_CHANGE", "message": f"No change in {path}"})
        if int(item.get("addedLines", 0)) + int(item.get("removedLines", 0)) <= 0:
            issues.append({"code": "PATCH_DIFF_COUNTS_EMPTY", "message": f"No changed lines in {path}"})

    return {"valid": not issues, "checkedFiles": len(files), "issues": issues}
