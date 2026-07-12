import pytest

from app.services.patch_proposals import PatchProposalError, build_patch_snapshot
from app.services.patch_checkpoint import create_checkpoint_ref
from app.services.patch_workflow import PatchWorkflowError, approve_status, reject_status


def test_patch_snapshot_generates_unified_diff_and_hashes() -> None:
    diff, files = build_patch_snapshot(
        [{"path": "CommonModules/Orders.bsl", "original": "A\n", "proposed": "B\n"}]
    )
    assert "--- a/CommonModules/Orders.bsl" in diff
    assert "+++ b/CommonModules/Orders.bsl" in diff
    assert "+B" in diff
    assert files[0]["addedLines"] == 1
    assert len(files[0]["originalSha256"]) == 64


@pytest.mark.parametrize("path", ["../unsafe.bsl", "/absolute.bsl", "C:/outside.bsl"])
def test_patch_snapshot_rejects_paths_outside_workspace(path: str) -> None:
    with pytest.raises(PatchProposalError, match="PATCH_PATH_INVALID"):
        build_patch_snapshot([{"path": path, "original": "A", "proposed": "B"}])


def test_patch_snapshot_rejects_noop() -> None:
    with pytest.raises(PatchProposalError, match="PATCH_NO_CHANGES"):
        build_patch_snapshot([{"path": "module.bsl", "original": "A", "proposed": "A"}])


def test_checkpoint_ref_is_deterministic_and_content_bound() -> None:
    first = create_checkpoint_ref("pp_123", "rev-1", "diff-1")
    second = create_checkpoint_ref("pp_123", "rev-1", "diff-1")
    changed = create_checkpoint_ref("pp_123", "rev-1", "diff-2")

    assert first == second
    assert first.startswith("proposal-checkpoint:pp_123:")
    assert first != changed


def test_patch_workflow_requires_checkpoint_before_approval() -> None:
    assert approve_status("checkpointed") == "approved"
    assert approve_status("awaiting_approval") == "approved"
    with pytest.raises(PatchWorkflowError, match="PATCH_NOT_READY_FOR_APPROVAL"):
        approve_status("proposed")


def test_patch_workflow_rejects_only_final_decisions() -> None:
    assert reject_status("proposed") == "rejected"
    assert reject_status("checkpointed") == "rejected"
    with pytest.raises(PatchWorkflowError, match="PATCH_DECISION_ALREADY_FINAL"):
        reject_status("approved")
