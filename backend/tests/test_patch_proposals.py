import pytest
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

from app.services.patch_proposals import PatchProposalError, build_patch_snapshot
from app.services.patch_checkpoint import create_checkpoint_ref
from app.services.patch_workflow import (
    PatchWorkflowError,
    approve_status,
    authorize_approval,
    authorize_rejection,
    reject_status,
)
from app.services.patch_package import build_patch_package, verify_patch_package
from app.services.patch_source import revalidate_source
from app.services.patch_validation import validate_patch_proposal
from app.services.auth import AuthError, issue_auth_token, verify_auth_token, verify_auth_token_with_rotation
from app.services.patch_policy import PatchPolicyError, authorize_environment


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


def test_patch_workflow_requires_maintainer_or_owner_for_approval() -> None:
    authorize_approval("maintainer")
    authorize_approval("owner")
    with pytest.raises(PatchWorkflowError, match="PATCH_APPROVAL_ROLE_REQUIRED"):
        authorize_approval("reviewer")
    authorize_rejection("reviewer")


def test_patch_package_contains_manifest_and_diff_without_apply_permission() -> None:
    from app.models import PatchProposal
    import json

    proposal = PatchProposal(
        id="pp_package",
        project_id="prj_package",
        status="checkpointed",
        title="Package test",
        summary="Portable proposal package",
        target_environment="sandbox",
        source_revision="rev-package",
        diff_text="--- a/module.bsl\n+++ b/module.bsl\n",
        files_json="[]",
        impact_json="[]",
        checkpoint_ref="proposal-checkpoint:pp_package:hash",
    )
    package = build_patch_package(proposal, "s" * 32)

    with ZipFile(BytesIO(package)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "proposal.diff", "README.txt", "signature.json"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["proposalId"] == "pp_package"
        assert manifest["applyAllowed"] is False
        assert manifest["signatureAlgorithm"] == "HMAC-SHA256"
        assert archive.read("proposal.diff").startswith(b"--- a/module.bsl")
    assert verify_patch_package(package, "s" * 32, "pp_package")["valid"] is True
    tampered_buffer = BytesIO()
    with ZipFile(BytesIO(package)) as source, ZipFile(tampered_buffer, "w") as tampered:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "proposal.diff":
                content = content.replace(b"module.bsl", b"changed.bsl")
            tampered.writestr(entry, content)
    assert verify_patch_package(tampered_buffer.getvalue(), "s" * 32, "pp_package")["valid"] is False


def test_source_revalidation_accepts_matching_snapshot() -> None:
    original = "A\n"
    expected = [{"path": "module.bsl", "originalSha256": sha256(original.encode()).hexdigest()}]

    result = revalidate_source(expected, [{"path": "module.bsl", "current": original}], "rev-1", "rev-1")

    assert result["valid"] is True
    assert result["mismatches"] == []


def test_source_revalidation_rejects_changed_content_and_revision() -> None:
    original = "A\n"
    expected = [{"path": "module.bsl", "originalSha256": sha256(original.encode()).hexdigest()}]

    result = revalidate_source(expected, [{"path": "module.bsl", "current": "B\n"}], "rev-1", "rev-2")

    assert result["valid"] is False
    assert {item["type"] for item in result["mismatches"]} == {"revision_mismatch", "content_mismatch"}


def test_patch_validation_accepts_valid_source_and_bsl_diff() -> None:
    result = validate_patch_proposal(
        [
            {
                "path": "CommonModules/Orders.bsl",
                "originalSha256": "a",
                "proposedSha256": "b",
                "addedLines": 1,
                "removedLines": 0,
            }
        ],
        "--- a/CommonModules/Orders.bsl\n+++ b/CommonModules/Orders.bsl\n",
        "valid",
    )

    assert result["valid"] is True
    assert result["issues"] == []


def test_patch_validation_reports_source_and_file_gate_failures() -> None:
    result = validate_patch_proposal(
        [
            {
                "path": "unsafe.exe",
                "originalSha256": "a",
                "proposedSha256": "b",
                "addedLines": 0,
                "removedLines": 0,
            }
        ],
        "--- a/unsafe.exe\n+++ b/unsafe.exe\n",
        "stale",
    )

    assert result["valid"] is False
    assert {issue["code"] for issue in result["issues"]} == {
        "SOURCE_NOT_VALIDATED",
        "PATCH_FILE_TYPE_UNSUPPORTED",
        "PATCH_DIFF_COUNTS_EMPTY",
    }


def test_auth_token_verifies_claims_and_rejects_tampering() -> None:
    secret = "s" * 32
    token = issue_auth_token("user-1", "maintainer", secret, ttl_seconds=60)
    identity = verify_auth_token(token, secret, now=1)

    assert identity.subject == "user-1"
    assert identity.role == "maintainer"
    with pytest.raises(AuthError, match="AUTH_TOKEN_INVALID"):
        verify_auth_token(token + "x", secret, now=1)


def test_auth_token_rotation_accepts_previous_secret_only_until_deadline() -> None:
    current = "c" * 32
    previous = "p" * 32
    token = issue_auth_token("user-1", "reviewer", previous, ttl_seconds=60)

    identity = verify_auth_token_with_rotation(token, current, previous, previous_secret_until=100, now=1)
    assert identity.subject == "user-1"
    with pytest.raises(AuthError, match="AUTH_TOKEN_INVALID"):
        verify_auth_token_with_rotation(token, current, previous, previous_secret_until=1, now=1)


def test_patch_policy_requires_owner_for_candidates_and_test() -> None:
    with pytest.raises(PatchPolicyError, match="PATCH_CANDIDATE_OWNER_REQUIRED"):
        authorize_environment("maintainer", "sandbox", "sandbox", [{"risk": "candidate"}])
    with pytest.raises(PatchPolicyError, match="PATCH_TEST_OWNER_REQUIRED"):
        authorize_environment("maintainer", "test", "test", [{"risk": "evidenced"}])
    authorize_environment("maintainer", "sandbox", "sandbox", [{"risk": "evidenced"}])
