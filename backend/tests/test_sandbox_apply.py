import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import PatchPackageVersion, PatchProposal, SandboxExecution
from app.services.patch_package import build_patch_package, verify_patch_package
from app.services.patch_proposals import build_patch_snapshot, serialize_snapshot
from app.services.sandbox_apply import SandboxApplyError, apply_verified_package
from app.services.sandbox_git import prepare_sandbox_worktree


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_apply_verified_package_changes_only_disposable_worktree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    root = tmp_path / "sandboxes"
    source.mkdir()
    root.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "sandbox@example.invalid")
    _git(source, "config", "user.name", "Sandbox Test")
    original = "Procedure Test()\nEndProcedure\n"
    proposed = "Procedure Test()\n    Message(\"sandbox\");\nEndProcedure\n"
    (source / "module.bsl").write_text(original, encoding="utf-8")
    _git(source, "add", "module.bsl")
    _git(source, "commit", "-m", "fixture")
    commit_sha = _git(source, "rev-parse", "HEAD")
    diff, files = build_patch_snapshot(
        [{"path": "module.bsl", "original": original, "proposed": proposed}]
    )
    proposal = PatchProposal(
        id="pp_apply",
        project_id="prj_apply",
        status="approved",
        title="Apply",
        summary="Sandbox apply",
        target_environment="sandbox",
        source_revision=commit_sha,
        diff_text=diff,
        files_json=serialize_snapshot(files),
        impact_json="[]",
        checkpoint_ref=f"git-checkpoint:pp_apply:{commit_sha}:diff",
    )
    package_bytes = build_patch_package(proposal, "s" * 32)
    package = PatchPackageVersion(
        id="pkg_apply",
        proposal_id=proposal.id,
        version=1,
        package_bytes=package_bytes,
        package_sha256=hashlib.sha256(package_bytes).hexdigest(),
        created_by="owner-1",
    )
    execution_id = "sbe_abcdef0123456789abcdef0123456789"
    prepared = prepare_sandbox_worktree(source, root, execution_id, commit_sha)
    execution = SandboxExecution(
        id=execution_id,
        proposal_id=proposal.id,
        package_version=1,
        package_sha256=package.package_sha256,
        source_commit=commit_sha,
        status="prepared",
        branch_name=prepared.branch_name,
        worktree_path=str(prepared.worktree_path),
        validation_json="{}",
        test_json="{}",
        created_by="owner-1",
    )

    result = apply_verified_package(execution, proposal, package, root, "s" * 32)

    assert verify_patch_package(package_bytes, "s" * 32)["sandboxApplyAllowed"] is True
    assert result.changed_paths == ("module.bsl",)
    assert len(result.diff_sha256) == 64
    assert (prepared.worktree_path / "module.bsl").read_text(encoding="utf-8") == proposed
    assert (source / "module.bsl").read_text(encoding="utf-8") == original
    assert _git(source, "status", "--porcelain") == ""
    assert _git(source, "rev-parse", "HEAD") == commit_sha


def test_apply_verified_package_rejects_package_hash_mismatch(tmp_path: Path) -> None:
    proposal = PatchProposal(
        id="pp_hash",
        project_id="prj_hash",
        status="approved",
        title="Hash",
        summary="Hash mismatch",
        target_environment="sandbox",
        source_revision="a" * 40,
        diff_text="diff",
        files_json="[]",
        impact_json="[]",
        checkpoint_ref=f"git-checkpoint:pp_hash:{'a' * 40}:diff",
    )
    package_bytes = build_patch_package(proposal, "s" * 32)
    package = PatchPackageVersion(
        id="pkg_hash",
        proposal_id=proposal.id,
        version=1,
        package_bytes=package_bytes,
        package_sha256=hashlib.sha256(package_bytes).hexdigest(),
        created_by="owner-1",
    )
    execution = SandboxExecution(
        id="sbe_abcdef0123456789abcdef0123456789",
        proposal_id=proposal.id,
        package_version=1,
        package_sha256="0" * 64,
        source_commit="a" * 40,
        status="prepared",
        validation_json="{}",
        test_json="{}",
        created_by="owner-1",
    )

    with pytest.raises(SandboxApplyError, match="SANDBOX_PACKAGE_HASH_MISMATCH"):
        apply_verified_package(execution, proposal, package, tmp_path, "s" * 32)
