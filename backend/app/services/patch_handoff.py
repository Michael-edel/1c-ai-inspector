"""Validate a signed package before recording a manual operator handoff."""

import hashlib
import hmac
from dataclasses import dataclass

from app.models import PatchPackageVersion, PatchProposal
from app.services.patch_package import verify_patch_package


class PatchHandoffError(ValueError):
    """Raised when a package cannot enter the manual handoff workflow."""


@dataclass(frozen=True)
class ManualHandoff:
    package_version: int
    package_sha256: str
    target_environment: str


def validate_manual_handoff(
    proposal: PatchProposal,
    package: PatchPackageVersion,
    role: str,
    target_environment: str,
    expected_sha256: str,
    signing_secret: str,
) -> ManualHandoff:
    if role not in {"maintainer", "owner"}:
        raise PatchHandoffError("PATCH_HANDOFF_ROLE_REQUIRED")
    if proposal.status != "approved":
        raise PatchHandoffError("PATCH_HANDOFF_REQUIRES_APPROVAL")
    if target_environment != proposal.target_environment:
        raise PatchHandoffError("PATCH_HANDOFF_ENVIRONMENT_MISMATCH")
    actual_sha256 = hashlib.sha256(package.package_bytes).hexdigest()
    if not (
        hmac.compare_digest(actual_sha256, package.package_sha256)
        and hmac.compare_digest(actual_sha256, expected_sha256)
    ):
        raise PatchHandoffError("PATCH_HANDOFF_PACKAGE_HASH_MISMATCH")
    verification = verify_patch_package(
        package.package_bytes,
        signing_secret,
        expected_proposal_id=proposal.id,
    )
    if not verification["valid"]:
        raise PatchHandoffError("PATCH_HANDOFF_PACKAGE_INVALID")
    if verification.get("status") != "approved":
        raise PatchHandoffError("PATCH_HANDOFF_PACKAGE_NOT_APPROVED")
    if verification.get("targetEnvironment") != proposal.target_environment:
        raise PatchHandoffError("PATCH_HANDOFF_PACKAGE_ENVIRONMENT_MISMATCH")
    if verification.get("checkpointRef") != proposal.checkpoint_ref:
        raise PatchHandoffError("PATCH_HANDOFF_PACKAGE_CHECKPOINT_MISMATCH")
    return ManualHandoff(
        package_version=package.version,
        package_sha256=actual_sha256,
        target_environment=target_environment,
    )
