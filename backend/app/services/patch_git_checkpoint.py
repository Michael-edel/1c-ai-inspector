"""Verify immutable Git revisions without modifying the repository."""

import hashlib
import hmac
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitCheckpointError(ValueError):
    """Raised when an immutable Git checkpoint cannot be verified."""


@dataclass(frozen=True)
class GitCheckpoint:
    commit_sha: str
    paths: tuple[str, ...]


def verify_git_checkpoint(
    repository: Path | None,
    revision: str | None,
    files: list[dict[str, str]],
) -> GitCheckpoint:
    if repository is None:
        raise GitCheckpointError("PATCH_GIT_REPOSITORY_NOT_CONFIGURED")
    repository = repository.resolve()
    if not repository.is_dir():
        raise GitCheckpointError("PATCH_GIT_REPOSITORY_UNAVAILABLE")
    if not revision or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
        raise GitCheckpointError("PATCH_GIT_COMMIT_REQUIRED")
    normalized_files = tuple(_validate_file(item) for item in files)
    normalized_paths = tuple(path for path, _ in normalized_files)
    if not normalized_paths:
        raise GitCheckpointError("PATCH_GIT_PATH_REQUIRED")

    commit_sha = _git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if commit_sha.casefold() != revision.casefold():
        raise GitCheckpointError("PATCH_GIT_COMMIT_REQUIRED")
    for path, expected_sha256 in normalized_files:
        blob = _git_bytes(repository, "cat-file", "blob", f"{commit_sha}:{path}")
        if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), expected_sha256):
            raise GitCheckpointError("PATCH_GIT_SOURCE_MISMATCH")
    return GitCheckpoint(commit_sha=commit_sha, paths=normalized_paths)


def create_git_checkpoint_ref(proposal_id: str, commit_sha: str, diff_text: str | None) -> str:
    digest = hashlib.sha256(f"{commit_sha}\0{diff_text or ''}".encode("utf-8")).hexdigest()
    return f"git-checkpoint:{proposal_id}:{commit_sha}:{digest}"


def _validate_file(item: dict[str, str]) -> tuple[str, str]:
    path = item.get("path", "")
    normalized = path.replace("\\", "/").strip()
    if not normalized or ":" in normalized or normalized.startswith("/"):
        raise GitCheckpointError("PATCH_GIT_PATH_INVALID")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise GitCheckpointError("PATCH_GIT_PATH_INVALID")
    original_sha256 = item.get("originalSha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", original_sha256):
        raise GitCheckpointError("PATCH_GIT_SOURCE_HASH_INVALID")
    return normalized, original_sha256


def _git(repository: Path, *arguments: str) -> str:
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repository}", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise GitCheckpointError("PATCH_GIT_VERIFICATION_FAILED") from exc
    value = result.stdout.strip()
    return value


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repository}", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            timeout=5,
            env=environment,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise GitCheckpointError("PATCH_GIT_VERIFICATION_FAILED") from exc
    return result.stdout
