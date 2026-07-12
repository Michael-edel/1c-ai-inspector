"""Validate proposal-only approval transitions."""

from app.core.enums import PatchStatus


class PatchWorkflowError(ValueError):
    """Raised when a proposal cannot enter the requested decision state."""


def authorize_approval(role: str) -> None:
    if role not in {"maintainer", "owner"}:
        raise PatchWorkflowError("PATCH_APPROVAL_ROLE_REQUIRED")


def authorize_rejection(role: str) -> None:
    if role not in {"reviewer", "maintainer", "owner"}:
        raise PatchWorkflowError("PATCH_DECISION_ROLE_INVALID")


def approve_status(current_status: str) -> str:
    if current_status not in {PatchStatus.CHECKPOINTED.value, PatchStatus.AWAITING_APPROVAL.value}:
        raise PatchWorkflowError("PATCH_NOT_READY_FOR_APPROVAL")
    return PatchStatus.APPROVED.value


def reject_status(current_status: str) -> str:
    if current_status in {PatchStatus.APPROVED.value, PatchStatus.REJECTED.value}:
        raise PatchWorkflowError("PATCH_DECISION_ALREADY_FINAL")
    return PatchStatus.REJECTED.value
