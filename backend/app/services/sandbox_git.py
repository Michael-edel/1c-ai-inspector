"""Create disposable Git worktrees without accepting client filesystem input."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class SandboxGitError(ValueError):
    """Raised when a disposable worktree cannot be created safely."""


@dataclass(frozen=True)
class PreparedSandbox:
    branch_name: str
    worktree_path: Path
    commit_sha: str


def prepare_sandbox_worktree(
    source_repository: Path | None,
    sandbox_root: Path | None,
    execution_id: str,
    source_commit: str,
) -> PreparedSandbox:
    if not re.fullmatch(r"sbe_[0-9a-f]{32}", execution_id):
        raise SandboxGitError("SANDBOX_EXECUTION_ID_INVALID")
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", source_commit):
        raise SandboxGitError("SANDBOX_SOURCE_COMMIT_REQUIRED")
    repository = _existing_directory(source_repository, "SANDBOX_SOURCE_REPOSITORY_UNAVAILABLE")
    root = _existing_directory(sandbox_root, "SANDBOX_ROOT_UNAVAILABLE")
    if repository == root or repository in root.parents or root in repository.parents:
        raise SandboxGitError("SANDBOX_PATHS_OVERLAP")
    if not (repository / ".git").exists():
        raise SandboxGitError("SANDBOX_SOURCE_REPOSITORY_INVALID")

    worktree = (root / execution_id).resolve()
    if worktree.parent != root:
        raise SandboxGitError("SANDBOX_PATH_INVALID")
    if worktree.exists():
        raise SandboxGitError("SANDBOX_WORKTREE_EXISTS")
    branch_name = f"inspector/{execution_id}"
    commit_sha = _git(repository, "rev-parse", "--verify", f"{source_commit}^{{commit}}")
    if commit_sha.casefold() != source_commit.casefold():
        raise SandboxGitError("SANDBOX_SOURCE_COMMIT_REQUIRED")
    if _branch_exists(repository, branch_name):
        raise SandboxGitError("SANDBOX_BRANCH_EXISTS")

    try:
        _git(repository, "worktree", "add", "-b", branch_name, str(worktree), commit_sha)
        actual_commit = _git(worktree, "rev-parse", "HEAD")
        actual_branch = _git(worktree, "branch", "--show-current")
        if actual_commit != commit_sha or actual_branch != branch_name:
            raise SandboxGitError("SANDBOX_WORKTREE_VERIFICATION_FAILED")
    except SandboxGitError:
        _cleanup_partial_worktree(repository, worktree, branch_name)
        raise
    return PreparedSandbox(branch_name, worktree, commit_sha)


def _existing_directory(path: Path | None, error_code: str) -> Path:
    if path is None:
        raise SandboxGitError(error_code)
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise SandboxGitError(error_code)
    return resolved


def _branch_exists(repository: Path, branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repository), "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        check=False,
        capture_output=True,
        timeout=5,
        env=_git_environment(),
    )
    return result.returncode == 0


def _git(repository: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repository}", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=_git_environment(),
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise SandboxGitError("SANDBOX_GIT_FAILED") from exc
    return result.stdout.strip()


def _cleanup_partial_worktree(repository: Path, worktree: Path, branch_name: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "remove", "--force", str(worktree)],
        check=False,
        capture_output=True,
        timeout=15,
        env=_git_environment(),
    )
    subprocess.run(
        ["git", "-C", str(repository), "branch", "-D", branch_name],
        check=False,
        capture_output=True,
        timeout=15,
        env=_git_environment(),
    )


def _git_environment() -> dict[str, str]:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
