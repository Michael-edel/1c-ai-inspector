import pytest
import shutil
import subprocess
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
from app.services.patch_task_source import PatchTaskSourceError, resolve_task_source
from app.services.patch_git_checkpoint import (
    GitCheckpointError,
    create_git_checkpoint_ref,
    verify_git_checkpoint,
)
from app.services.patch_handoff import PatchHandoffError, validate_manual_handoff


class StoredToolCall:
    def __init__(self, call_id: str, output: dict[str, object], *, mode: str = "read-only") -> None:
        import json

        self.id = call_id
        self.tool_name = "read_source"
        self.mode = mode
        self.status = "completed"
        self.output_json = json.dumps(output, ensure_ascii=False)


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


def test_task_source_resolves_matching_persisted_read_only_module() -> None:
    call = StoredToolCall(
        "call_source",
        {
            "sourceComplete": True,
            "module": "Документ.ЗаказКлиента.МодульОбъекта",
            "source": "Процедура Проверить()\nКонецПроцедуры",
            "sourceRevision": "commit-123",
        },
    )

    source = resolve_task_source("Документ.ЗаказКлиента", "МодульОбъекта", [call])

    assert source.tool_call_id == "call_source"
    assert source.revision == "commit-123"
    assert source.source.startswith("Процедура")


def test_task_source_rejects_non_read_only_and_ambiguous_evidence() -> None:
    writable = StoredToolCall(
        "call_write",
        {"sourceComplete": True, "module": "Module", "source": "A"},
        mode="write",
    )
    with pytest.raises(PatchTaskSourceError, match="PATCH_SOURCE_NOT_AVAILABLE"):
        resolve_task_source("Document.Order", "ObjectModule", [writable])

    first = StoredToolCall(
        "call_1",
        {"sourceComplete": True, "module": "Document.Order.ObjectModule", "source": "A"},
    )
    second = StoredToolCall(
        "call_2",
        {"sourceComplete": True, "module": "Document.Order.ObjectModule", "source": "B"},
    )
    with pytest.raises(PatchTaskSourceError, match="PATCH_SOURCE_AMBIGUOUS"):
        resolve_task_source("Document.Order", "ObjectModule", [first, second])


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_git_checkpoint_verifies_full_commit_and_paths_without_changes(tmp_path) -> None:
    source_path = tmp_path / "CommonModules" / "Orders.bsl"
    source_path.parent.mkdir()
    source_path.write_text("Procedure Check()\nEndProcedure\n", encoding="utf-8")
    for arguments in (
        ("init",),
        ("config", "user.email", "inspector@example.test"),
        ("config", "user.name", "Inspector Test"),
        ("add", "CommonModules/Orders.bsl"),
        ("commit", "-m", "source revision"),
    ):
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True)
    commit_sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    before = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    checkpoint = verify_git_checkpoint(tmp_path, commit_sha, ["CommonModules/Orders.bsl"])
    checkpoint_ref = create_git_checkpoint_ref("pp_git", checkpoint.commit_sha, "diff")

    after = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert checkpoint.commit_sha == commit_sha
    assert checkpoint_ref.startswith(f"git-checkpoint:pp_git:{commit_sha}:")
    assert before == after == ""


def test_git_checkpoint_fails_closed_without_repository_or_full_sha(tmp_path) -> None:
    with pytest.raises(GitCheckpointError, match="PATCH_GIT_REPOSITORY_NOT_CONFIGURED"):
        verify_git_checkpoint(None, "a" * 40, ["module.bsl"])
    with pytest.raises(GitCheckpointError, match="PATCH_GIT_COMMIT_REQUIRED"):
        verify_git_checkpoint(tmp_path, "HEAD", ["module.bsl"])


def test_manual_handoff_requires_approved_signed_matching_package() -> None:
    from app.models import PatchPackageVersion, PatchProposal

    proposal = PatchProposal(
        id="pp_handoff",
        project_id="prj_handoff",
        status="approved",
        title="Manual handoff",
        summary="Approved proposal package",
        target_environment="sandbox",
        source_revision="a" * 40,
        diff_text="--- a/module.bsl\n+++ b/module.bsl\n",
        files_json="[]",
        impact_json="[]",
        checkpoint_ref="git-checkpoint:pp_handoff:commit:diff",
    )
    package_bytes = build_patch_package(proposal, "s" * 32)
    package = PatchPackageVersion(
        id="pkg_handoff",
        proposal_id=proposal.id,
        version=1,
        package_bytes=package_bytes,
        package_sha256=sha256(package_bytes).hexdigest(),
        created_by="maintainer-1",
    )

    handoff = validate_manual_handoff(
        proposal,
        package,
        "maintainer",
        "sandbox",
        package.package_sha256,
        "s" * 32,
    )

    assert handoff.package_version == 1
    assert handoff.package_sha256 == package.package_sha256
    with pytest.raises(PatchHandoffError, match="PATCH_HANDOFF_ROLE_REQUIRED"):
        validate_manual_handoff(
            proposal,
            package,
            "reviewer",
            "sandbox",
            package.package_sha256,
            "s" * 32,
        )
    with pytest.raises(PatchHandoffError, match="PATCH_HANDOFF_PACKAGE_HASH_MISMATCH"):
        validate_manual_handoff(
            proposal,
            package,
            "owner",
            "sandbox",
            "0" * 64,
            "s" * 32,
        )
