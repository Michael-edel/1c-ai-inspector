import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.sandbox_git import SandboxGitError, prepare_sandbox_worktree


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_prepare_worktree_keeps_source_checkout_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source"
    root = tmp_path / "sandboxes"
    source.mkdir()
    root.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "sandbox@example.invalid")
    _git(source, "config", "user.name", "Sandbox Test")
    (source / "module.bsl").write_text("Procedure Test()\nEndProcedure\n", encoding="utf-8")
    _git(source, "add", "module.bsl")
    _git(source, "commit", "-m", "fixture")
    commit_sha = _git(source, "rev-parse", "HEAD")
    source_branch = _git(source, "branch", "--show-current")
    source_status = _git(source, "status", "--porcelain")
    execution_id = "sbe_0123456789abcdef0123456789abcdef"

    prepared = prepare_sandbox_worktree(source, root, execution_id, commit_sha)

    assert prepared.worktree_path == (root / execution_id).resolve()
    assert prepared.branch_name == f"inspector/{execution_id}"
    assert _git(prepared.worktree_path, "rev-parse", "HEAD") == commit_sha
    assert _git(prepared.worktree_path, "branch", "--show-current") == prepared.branch_name
    assert _git(source, "branch", "--show-current") == source_branch
    assert _git(source, "rev-parse", "HEAD") == commit_sha
    assert _git(source, "status", "--porcelain") == source_status


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_prepare_worktree_rejects_overlapping_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    root = source / "sandboxes"
    source.mkdir()
    root.mkdir()

    with pytest.raises(SandboxGitError, match="SANDBOX_PATHS_OVERLAP"):
        prepare_sandbox_worktree(
            source,
            root,
            "sbe_0123456789abcdef0123456789abcdef",
            "0" * 40,
        )
