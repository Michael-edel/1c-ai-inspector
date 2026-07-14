"""Fail-closed state and package gates for Sandbox Executor."""

import hashlib
import hmac

from app.core.enums import SandboxExecutionStatus
from app.models import PatchPackageVersion, PatchProposal
from app.services.patch_package import verify_patch_package


class SandboxWorkflowError(ValueError):
    """Raised when a sandbox execution violates an authorization or state gate."""


ALLOWED_TRANSITIONS = {
    SandboxExecutionStatus.CREATED.value: {SandboxExecutionStatus.PREPARING.value},
    SandboxExecutionStatus.PREPARING.value: {
        SandboxExecutionStatus.PREPARED.value,
        SandboxExecutionStatus.FAILED.value,
    },
    SandboxExecutionStatus.PREPARED.value: {SandboxExecutionStatus.APPLYING.value},
    SandboxExecutionStatus.APPLYING.value: {
        SandboxExecutionStatus.VALIDATING.value,
        SandboxExecutionStatus.ROLLBACK_REQUIRED.value,
    },
    SandboxExecutionStatus.VALIDATING.value: {
        SandboxExecutionStatus.TESTING.value,
        SandboxExecutionStatus.ROLLBACK_REQUIRED.value,
    },
    SandboxExecutionStatus.TESTING.value: {
        SandboxExecutionStatus.AWAITING_ACCEPTANCE.value,
        SandboxExecutionStatus.ROLLBACK_REQUIRED.value,
    },
    SandboxExecutionStatus.AWAITING_ACCEPTANCE.value: {
        SandboxExecutionStatus.ROLLBACK_REQUIRED.value
    },
    SandboxExecutionStatus.ROLLBACK_REQUIRED.value: {
        SandboxExecutionStatus.ROLLING_BACK.value
    },
    SandboxExecutionStatus.ROLLING_BACK.value: {
        SandboxExecutionStatus.ROLLED_BACK.value,
        SandboxExecutionStatus.ROLLBACK_REQUIRED.value,
    },
}


def validate_execution_request(
    proposal: PatchProposal,
    package: PatchPackageVersion,
    role: str,
    requested_sha256: str,
    signing_secret: str,
) -> None:
    if role != "owner":
        raise SandboxWorkflowError("SANDBOX_OWNER_REQUIRED")
    if proposal.status != "approved":
        raise SandboxWorkflowError("SANDBOX_PROPOSAL_NOT_APPROVED")
    if not proposal.source_revision or len(proposal.source_revision) not in {40, 64}:
        raise SandboxWorkflowError("SANDBOX_SOURCE_COMMIT_REQUIRED")
    if not hmac.compare_digest(package.package_sha256, requested_sha256):
        raise SandboxWorkflowError("SANDBOX_PACKAGE_HASH_MISMATCH")
    if not hmac.compare_digest(
        hashlib.sha256(package.package_bytes).hexdigest(), package.package_sha256
    ):
        raise SandboxWorkflowError("SANDBOX_PACKAGE_STORAGE_MISMATCH")
    verification = verify_patch_package(package.package_bytes, signing_secret, proposal.id)
    if verification.get("valid") is not True or verification.get("status") != "approved":
        raise SandboxWorkflowError("SANDBOX_PACKAGE_INVALID")
    if verification.get("checkpointRef") != proposal.checkpoint_ref:
        raise SandboxWorkflowError("SANDBOX_CHECKPOINT_MISMATCH")


def transition_sandbox_status(current: str, target: str) -> str:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise SandboxWorkflowError("SANDBOX_STATE_TRANSITION_INVALID")
    return target
