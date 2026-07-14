"""Apply one verified proposal only inside its disposable Git worktree."""

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from app.models import PatchPackageVersion, PatchProposal, SandboxExecution
from app.services.patch_package import verify_patch_package


class SandboxApplyError(ValueError):
    """Raised when a signed patch cannot be applied safely."""


@dataclass(frozen=True)
class SandboxApplyResult:
    changed_paths: tuple[str, ...]
    diff_sha256: str


def apply_verified_package(
    execution: SandboxExecution,
    proposal: PatchProposal,
    package: PatchPackageVersion,
    sandbox_root: Path | None,
    signing_secret: str,
) -> SandboxApplyResult:
    if package.version != execution.package_version:
        raise SandboxApplyError("SANDBOX_PACKAGE_VERSION_MISMATCH")
    package_sha256 = hashlib.sha256(package.package_bytes).hexdigest()
    if package_sha256 != package.package_sha256 or package_sha256 != execution.package_sha256:
        raise SandboxApplyError("SANDBOX_PACKAGE_HASH_MISMATCH")
    verification = verify_patch_package(package.package_bytes, signing_secret, proposal.id)
    if verification.get("valid") is not True or verification.get("sandboxApplyAllowed") is not True:
        raise SandboxApplyError("SANDBOX_PACKAGE_NOT_APPLICABLE")
    if verification.get("checkpointRef") != proposal.checkpoint_ref:
        raise SandboxApplyError("SANDBOX_CHECKPOINT_MISMATCH")
    if not execution.worktree_path or not execution.branch_name:
        raise SandboxApplyError("SANDBOX_WORKTREE_NOT_PREPARED")

    root = _existing_directory(sandbox_root, "SANDBOX_ROOT_UNAVAILABLE")
    worktree = Path(execution.worktree_path).resolve()
    if worktree.parent != root or worktree.name != execution.id or not worktree.is_dir():
        raise SandboxApplyError("SANDBOX_WORKTREE_PATH_INVALID")
    expected_branch = f"inspector/{execution.id}"
    if execution.branch_name != expected_branch:
        raise SandboxApplyError("SANDBOX_BRANCH_INVALID")
    if _git(worktree, "branch", "--show-current") != expected_branch:
        raise SandboxApplyError("SANDBOX_BRANCH_INVALID")
    if _git(worktree, "rev-parse", "HEAD") != execution.source_commit:
        raise SandboxApplyError("SANDBOX_SOURCE_COMMIT_CHANGED")
    if _git(worktree, "status", "--porcelain"):
        raise SandboxApplyError("SANDBOX_WORKTREE_NOT_CLEAN")

    try:
        with ZipFile(BytesIO(package.package_bytes)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            diff = archive.read("proposal.diff")
    except (KeyError, ValueError) as exc:
        raise SandboxApplyError("SANDBOX_PACKAGE_FORMAT_INVALID") from exc
    files = manifest.get("files")
    if files != json.loads(proposal.files_json) or not isinstance(files, list) or not files:
        raise SandboxApplyError("SANDBOX_PACKAGE_FILES_MISMATCH")
    expected_paths = {_verified_path(worktree, item) for item in files}

    _git_with_input(worktree, diff, "apply", "--check", "--whitespace=error-all", "-")
    _git_with_input(worktree, diff, "apply", "--whitespace=error-all", "-")
    changed_paths = set(_git(worktree, "diff", "--name-only").splitlines())
    if changed_paths != expected_paths:
        raise SandboxApplyError("SANDBOX_CHANGED_PATHS_MISMATCH")
    for item in files:
        relative_path = str(item["path"])
        target = _contained_file(worktree, relative_path)
        actual_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_sha256 != item.get("proposedSha256"):
            raise SandboxApplyError("SANDBOX_PROPOSED_HASH_MISMATCH")
    applied_diff = _git_bytes(worktree, "diff", "--binary", "--no-ext-diff")
    return SandboxApplyResult(tuple(sorted(changed_paths)), hashlib.sha256(applied_diff).hexdigest())


def _verified_path(worktree: Path, item: object) -> str:
    if not isinstance(item, dict):
        raise SandboxApplyError("SANDBOX_PACKAGE_FILES_MISMATCH")
    relative_path = str(item.get("path", ""))
    target = _contained_file(worktree, relative_path)
    if hashlib.sha256(target.read_bytes()).hexdigest() != item.get("originalSha256"):
        raise SandboxApplyError("SANDBOX_ORIGINAL_HASH_MISMATCH")
    return relative_path.replace("\\", "/")


def _contained_file(worktree: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise SandboxApplyError("SANDBOX_FILE_PATH_INVALID")
    candidate = worktree / relative_path
    target = candidate.resolve()
    if worktree not in target.parents or not target.is_file() or candidate.is_symlink():
        raise SandboxApplyError("SANDBOX_FILE_PATH_INVALID")
    return target


def _existing_directory(path: Path | None, error_code: str) -> Path:
    if path is None:
        raise SandboxApplyError(error_code)
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise SandboxApplyError(error_code)
    return resolved


def _git(worktree: Path, *arguments: str) -> str:
    return _run_git(worktree, arguments).stdout.decode("utf-8").strip()


def _git_bytes(worktree: Path, *arguments: str) -> bytes:
    return _run_git(worktree, arguments).stdout


def _git_with_input(worktree: Path, value: bytes, *arguments: str) -> None:
    _run_git(worktree, arguments, value)


def _run_git(worktree: Path, arguments: tuple[str, ...], value: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={worktree}",
                "-c",
                "core.autocrlf=false",
                "-C",
                str(worktree),
                *arguments,
            ],
            input=value,
            check=True,
            capture_output=True,
            timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise SandboxApplyError("SANDBOX_GIT_APPLY_FAILED") from exc
