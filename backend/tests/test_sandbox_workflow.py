from hashlib import sha256

import pytest

from app.models import PatchPackageVersion, PatchProposal
from app.services.patch_package import build_patch_package
from app.services.sandbox_workflow import (
    SandboxWorkflowError,
    transition_sandbox_status,
    validate_execution_request,
)


def _approved_package() -> tuple[PatchProposal, PatchPackageVersion]:
    proposal = PatchProposal(
        id="pp_sandbox",
        project_id="prj_sandbox",
        status="approved",
        title="Sandbox",
        summary="Approved sandbox proposal",
        target_environment="sandbox",
        source_revision="a" * 40,
        diff_text="--- a/module.bsl\n+++ b/module.bsl\n",
        files_json="[]",
        impact_json="[]",
        checkpoint_ref=f"git-checkpoint:pp_sandbox:{'a' * 40}:diff",
    )
    package_bytes = build_patch_package(proposal, "s" * 32)
    package = PatchPackageVersion(
        id="pkg_sandbox",
        proposal_id=proposal.id,
        version=1,
        package_bytes=package_bytes,
        package_sha256=sha256(package_bytes).hexdigest(),
        created_by="owner-1",
    )
    return proposal, package


def test_sandbox_creation_requires_owner_and_verified_approved_package() -> None:
    proposal, package = _approved_package()

    validate_execution_request(proposal, package, "owner", package.package_sha256, "s" * 32)

    with pytest.raises(SandboxWorkflowError, match="SANDBOX_OWNER_REQUIRED"):
        validate_execution_request(proposal, package, "maintainer", package.package_sha256, "s" * 32)
    with pytest.raises(SandboxWorkflowError, match="SANDBOX_PACKAGE_HASH_MISMATCH"):
        validate_execution_request(proposal, package, "owner", "0" * 64, "s" * 32)


def test_sandbox_state_machine_rejects_skipped_gates() -> None:
    assert transition_sandbox_status("created", "preparing") == "preparing"
    assert transition_sandbox_status("testing", "awaiting_acceptance") == "awaiting_acceptance"
    assert transition_sandbox_status("rollback_required", "rolling_back") == "rolling_back"
    with pytest.raises(SandboxWorkflowError, match="SANDBOX_STATE_TRANSITION_INVALID"):
        transition_sandbox_status("created", "applying")
