"""Feature-flagged Sandbox Executor API."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_identity
from app.db.session import get_db
from app.models import (
    PatchPackageVersion,
    PatchProposal,
    SandboxExecution,
    SandboxExecutionEvent,
)
from app.services.auth import AuthContext
from app.services.sandbox_audit import record_sandbox_event
from app.services.sandbox_apply import SandboxApplyError, apply_verified_package
from app.services.sandbox_command import SandboxCommandError, run_operator_command
from app.services.sandbox_workflow import SandboxWorkflowError, validate_execution_request
from app.services.sandbox_git import SandboxGitError, prepare_sandbox_worktree
from app.services.sandbox_workflow import transition_sandbox_status

router = APIRouter(prefix="/api/v1/sandbox-executions", tags=["sandbox-executions"])


class SandboxExecutionCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proposal_id: str = Field(alias="proposalId", min_length=1)
    package_version: int = Field(alias="packageVersion", ge=1)
    package_sha256: str = Field(alias="packageSha256", pattern=r"^[0-9a-f]{64}$")
    note: str = Field(min_length=1, max_length=10_000)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_sandbox_execution(
    payload: SandboxExecutionCreateRequest,
    request: Request,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, payload.proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Sandbox proposal not found")
    package = db.scalar(
        select(PatchPackageVersion).where(
            PatchPackageVersion.proposal_id == proposal.id,
            PatchPackageVersion.version == payload.package_version,
        )
    )
    if package is None:
        raise HTTPException(status_code=404, detail="Sandbox package not found")
    secret = request.app.state.settings.inspector_package_signing_secret
    if not secret:
        raise HTTPException(status_code=503, detail="SANDBOX_SIGNING_NOT_CONFIGURED")
    try:
        validate_execution_request(
            proposal,
            package,
            identity.role,
            payload.package_sha256,
            secret,
        )
    except SandboxWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    execution = SandboxExecution(
        id=f"sbe_{uuid4().hex}",
        proposal_id=proposal.id,
        package_version=package.version,
        package_sha256=package.package_sha256,
        source_commit=str(proposal.source_revision),
        status="created",
        validation_json="{}",
        test_json="{}",
        created_by=identity.subject,
    )
    db.add(execution)
    db.flush()
    record_sandbox_event(
        db,
        execution.id,
        "execution_created",
        identity.subject,
        {
            "proposalId": proposal.id,
            "packageVersion": package.version,
            "packageSha256": package.package_sha256,
            "sourceCommit": execution.source_commit,
            "note": payload.note,
        },
    )
    db.commit()
    return _execution_response(execution)


@router.get("")
def list_sandbox_executions(
    limit: int = Query(default=20, ge=1, le=100),
    _: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.scalars(
        select(SandboxExecution)
        .order_by(SandboxExecution.created_at.desc(), SandboxExecution.id.desc())
        .limit(limit)
    ).all()
    return [_execution_response(row) for row in rows]


@router.post("/{execution_id}/prepare")
def prepare_sandbox_execution(
    execution_id: str,
    request: Request,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if identity.role != "owner":
        raise HTTPException(status_code=403, detail="SANDBOX_OWNER_REQUIRED")
    execution = db.get(SandboxExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Sandbox execution not found")
    try:
        execution.status = transition_sandbox_status(execution.status, "preparing")
    except SandboxWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_sandbox_event(db, execution.id, "sandbox_preparing", identity.subject)
    db.commit()
    try:
        prepared = prepare_sandbox_worktree(
            request.app.state.settings.sandbox_source_repository,
            request.app.state.settings.sandbox_root,
            execution.id,
            execution.source_commit,
        )
    except SandboxGitError as exc:
        execution.status = transition_sandbox_status(execution.status, "failed")
        execution.last_error_code = str(exc)
        record_sandbox_event(
            db,
            execution.id,
            "sandbox_prepare_failed",
            identity.subject,
            {"errorCode": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    execution.branch_name = prepared.branch_name
    execution.worktree_path = str(prepared.worktree_path)
    execution.status = transition_sandbox_status(execution.status, "prepared")
    record_sandbox_event(
        db,
        execution.id,
        "sandbox_prepared",
        identity.subject,
        {"branchName": prepared.branch_name, "sourceCommit": prepared.commit_sha},
    )
    db.commit()
    return _execution_response(execution)


@router.post("/{execution_id}/apply")
def apply_sandbox_execution(
    execution_id: str,
    request: Request,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if identity.role != "owner":
        raise HTTPException(status_code=403, detail="SANDBOX_OWNER_REQUIRED")
    execution = db.get(SandboxExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Sandbox execution not found")
    proposal = db.get(PatchProposal, execution.proposal_id)
    package = db.scalar(
        select(PatchPackageVersion).where(
            PatchPackageVersion.proposal_id == execution.proposal_id,
            PatchPackageVersion.version == execution.package_version,
        )
    )
    if proposal is None or package is None:
        raise HTTPException(status_code=409, detail="SANDBOX_PACKAGE_UNAVAILABLE")
    secret = request.app.state.settings.inspector_package_signing_secret
    if not secret:
        raise HTTPException(status_code=503, detail="SANDBOX_SIGNING_NOT_CONFIGURED")
    try:
        execution.status = transition_sandbox_status(execution.status, "applying")
    except SandboxWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_sandbox_event(db, execution.id, "sandbox_applying", identity.subject)
    db.commit()
    try:
        result = apply_verified_package(
            execution,
            proposal,
            package,
            request.app.state.settings.sandbox_root,
            secret,
        )
    except SandboxApplyError as exc:
        execution.status = transition_sandbox_status(execution.status, "rollback_required")
        execution.last_error_code = str(exc)
        record_sandbox_event(
            db,
            execution.id,
            "sandbox_apply_failed",
            identity.subject,
            {"errorCode": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    execution.status = transition_sandbox_status(execution.status, "validating")
    execution.last_error_code = None
    record_sandbox_event(
        db,
        execution.id,
        "sandbox_applied",
        identity.subject,
        {"changedPaths": list(result.changed_paths), "diffSha256": result.diff_sha256},
    )
    db.commit()
    return _execution_response(execution)


@router.post("/{execution_id}/validate")
def validate_sandbox_execution(
    execution_id: str,
    request: Request,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if identity.role != "owner":
        raise HTTPException(status_code=403, detail="SANDBOX_OWNER_REQUIRED")
    execution = db.get(SandboxExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Sandbox execution not found")
    settings = request.app.state.settings
    if not settings.sandbox_validation_command:
        raise HTTPException(status_code=503, detail="SANDBOX_VALIDATION_NOT_CONFIGURED")
    if not execution.worktree_path:
        raise HTTPException(status_code=409, detail="SANDBOX_WORKTREE_NOT_PREPARED")
    if execution.status != "validating":
        raise HTTPException(status_code=409, detail="SANDBOX_STATE_TRANSITION_INVALID")
    record_sandbox_event(db, execution.id, "sandbox_validation_started", identity.subject)
    db.commit()
    try:
        result = run_operator_command(
            settings.sandbox_validation_command,
            Path(execution.worktree_path),
            settings.sandbox_root,
            settings.sandbox_command_timeout_sec,
        )
    except SandboxCommandError as exc:
        execution.status = transition_sandbox_status(execution.status, "rollback_required")
        execution.last_error_code = str(exc)
        record_sandbox_event(
            db,
            execution.id,
            "sandbox_validation_failed",
            identity.subject,
            {"errorCode": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    execution.validation_json = json.dumps(result.as_record(), ensure_ascii=False)
    if result.succeeded:
        execution.status = transition_sandbox_status(execution.status, "testing")
        execution.last_error_code = None
        event_type = "sandbox_validation_passed"
    else:
        execution.status = transition_sandbox_status(execution.status, "rollback_required")
        execution.last_error_code = (
            "SANDBOX_VALIDATION_TIMEOUT" if result.timed_out else "SANDBOX_VALIDATION_FAILED"
        )
        event_type = "sandbox_validation_failed"
    record_sandbox_event(
        db,
        execution.id,
        event_type,
        identity.subject,
        {
            "exitCode": result.exit_code,
            "durationMs": result.duration_ms,
            "outputBytes": result.output_bytes,
            "outputSha256": result.output_sha256,
            "timedOut": result.timed_out,
        },
    )
    db.commit()
    return _execution_response(execution)


@router.get("/{execution_id}")
def get_sandbox_execution(
    execution_id: str,
    _: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    execution = db.get(SandboxExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Sandbox execution not found")
    return _execution_response(execution)


@router.get("/{execution_id}/events")
def get_sandbox_events(
    execution_id: str,
    _: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if db.get(SandboxExecution, execution_id) is None:
        raise HTTPException(status_code=404, detail="Sandbox execution not found")
    events = db.scalars(
        select(SandboxExecutionEvent)
        .where(SandboxExecutionEvent.execution_id == execution_id)
        .order_by(SandboxExecutionEvent.id)
    ).all()
    return {
        "executionId": execution_id,
        "events": [
            {
                "id": event.id,
                "type": event.event_type,
                "actor": event.actor,
                "payload": json.loads(event.payload_json),
                "createdAt": event.created_at.isoformat(),
            }
            for event in events
        ],
    }


def _execution_response(execution: SandboxExecution) -> dict[str, object]:
    return {
        "id": execution.id,
        "proposalId": execution.proposal_id,
        "packageVersion": execution.package_version,
        "packageSha256": execution.package_sha256,
        "sourceCommit": execution.source_commit,
        "status": execution.status,
        "branchName": execution.branch_name,
        "validation": json.loads(execution.validation_json),
        "test": json.loads(execution.test_json),
        "lastErrorCode": execution.last_error_code,
        "createdBy": execution.created_by,
        "createdAt": execution.created_at.isoformat(),
        "updatedAt": execution.updated_at.isoformat(),
        "appliedToInformationBase": False,
    }
