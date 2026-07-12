import pytest

from app.services.patch_proposals import PatchProposalError, build_patch_snapshot


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
