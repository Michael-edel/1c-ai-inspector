import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PatchStatus
from app.api.dependencies import require_identity
from app.db.session import get_db
from app.models import PatchEvent, PatchPackageVersion, PatchProposal, Project, Task
from app.services.patch_audit import record_patch_event
from app.services.patch_proposals import PatchProposalError, build_patch_snapshot, serialize_snapshot
from app.services.patch_impact import analyze_patch_impact, enrich_patch_impact
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
from app.services.patch_mcp_evidence import extract_search_evidence
from app.mcp.connector import McpConnector, ToolNotAllowedError
from app.services.auth import AuthContext
from app.services.patch_policy import PatchPolicyError, authorize_environment

router = APIRouter(prefix="/api/v1/patch-proposals", tags=["patch-proposals"])


class PatchFileInput(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    original: str = Field(max_length=500_000)
    proposed: str = Field(max_length=500_000)


class PatchProposalCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1)
    task_id: str | None = Field(default=None, alias="taskId")
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1, max_length=10_000)
    source_revision: str | None = Field(default=None, alias="sourceRevision", max_length=128)
    files: list[PatchFileInput] = Field(min_length=1, max_length=50)


class PatchDecisionRequest(BaseModel):
    note: str = Field(min_length=1, max_length=10_000)


class PatchSourceFileInput(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    current: str = Field(max_length=500_000)


class PatchRevalidateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_revision: str | None = Field(default=None, alias="currentRevision", max_length=128)
    files: list[PatchSourceFileInput] = Field(min_length=1, max_length=50)


class PatchImpactEvidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    object_fqn: str = Field(alias="objectFqn", min_length=1, max_length=500)
    relation: str = Field(min_length=1, max_length=100)
    source_tool: Literal["search_code", "get_object_structure"] = Field(alias="sourceTool")
    evidence: list[str] = Field(min_length=1, max_length=20)


class PatchImpactRequest(BaseModel):
    evidence: list[PatchImpactEvidence] = Field(default_factory=list, max_length=100)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_patch_proposal(
    payload: PatchProposalCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.task_id and db.get(Task, payload.task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        diff_text, snapshot = build_patch_snapshot([item.model_dump() for item in payload.files])
    except PatchProposalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    proposal = PatchProposal(
        id=f"pp_{uuid4().hex}",
        project_id=project.id,
        task_id=payload.task_id,
        status=PatchStatus.PROPOSED.value,
        title=payload.title,
        summary=payload.summary,
        target_environment=project.environment,
        source_revision=payload.source_revision,
        diff_text=diff_text,
        files_json=serialize_snapshot(snapshot),
        impact_json="[]",
    )
    db.add(proposal)
    db.flush()
    record_patch_event(db, proposal.id, "created", "system", {"status": proposal.status})
    db.commit()
    return _proposal_response(proposal)


@router.get("/{proposal_id}")
def get_patch_proposal(proposal_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    return _proposal_response(proposal)


@router.post("/{proposal_id}/impact")
def analyze_proposal_impact(
    proposal_id: str,
    payload: PatchImpactRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    impacts = analyze_patch_impact(json.loads(proposal.files_json))
    if payload and payload.evidence:
        impacts = enrich_patch_impact(
            impacts,
            [item.model_dump(by_alias=True) for item in payload.evidence],
        )
    proposal.impact_json = json.dumps(impacts, ensure_ascii=False)
    record_patch_event(db, proposal.id, "impact_analyzed", "system", {"candidateCount": len(impacts)})
    db.commit()
    return {"proposalId": proposal.id, "status": "analyzed", "impact": impacts}


@router.post("/{proposal_id}/impact/mcp")
async def analyze_mcp_impact(
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    settings = request.app.state.settings
    tool_name = settings.mcp_patch_search_tool
    contract = request.app.state.policy_snapshot.published_tools.get(tool_name)
    if contract is None or contract.category != "code.search":
        raise HTTPException(status_code=503, detail="MCP search tool is not published as read-only")
    candidates = analyze_patch_impact(json.loads(proposal.files_json))
    connector = McpConnector(
        str(settings.mcp_server_url),
        request.app.state.policy_snapshot,
        transport_mode=settings.mcp_transport,
        access_token=settings.mcp_bridge_token,
    )
    evidence: list[dict[str, object]] = []
    try:
        for candidate in candidates:
            result = await connector.call_tool(
                tool_name,
                {settings.mcp_patch_search_argument: candidate["objectFqn"]},
            )
            matches = extract_search_evidence(result)
            record_patch_event(
                db,
                proposal.id,
                "mcp_search_completed",
                "system",
                {
                    "tool": tool_name,
                    "objectFqn": candidate["objectFqn"],
                    "evidenceCount": len(matches),
                },
            )
            if matches:
                evidence.append(
                    {
                        "objectFqn": candidate["objectFqn"],
                        "relation": candidate["relation"],
                        "sourceTool": tool_name,
                        "evidence": matches,
                    }
                )
    except (httpx.HTTPError, RuntimeError, ToolNotAllowedError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="MCP read-only impact search is unavailable") from exc
    finally:
        await connector.close()
    impacts = enrich_patch_impact(candidates, evidence)
    proposal.impact_json = json.dumps(impacts, ensure_ascii=False)
    record_patch_event(
        db,
        proposal.id,
        "impact_mcp_analyzed",
        "system",
        {"tool": tool_name, "candidateCount": len(candidates), "evidencedCount": len(evidence)},
    )
    db.commit()
    return {"proposalId": proposal.id, "status": "analyzed_mcp", "tool": tool_name, "impact": impacts}


@router.post("/{proposal_id}/revalidate")
def revalidate_patch_source(
    proposal_id: str,
    payload: PatchRevalidateRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    result = revalidate_source(
        json.loads(proposal.files_json),
        [item.model_dump() for item in payload.files],
        proposal.source_revision,
        payload.current_revision,
    )
    proposal.source_validation_status = "valid" if result["valid"] else "stale"
    proposal.source_validation_json = json.dumps(result, ensure_ascii=False)
    proposal.source_validated_at = datetime.now(timezone.utc)
    record_patch_event(
        db,
        proposal.id,
        "source_revalidated" if result["valid"] else "source_stale",
        "system",
        result,
    )
    db.commit()
    return {"proposalId": proposal.id, "status": proposal.source_validation_status, "validation": result}


@router.post("/{proposal_id}/validate")
def validate_patch(proposal_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    result = validate_patch_proposal(
        json.loads(proposal.files_json),
        proposal.diff_text,
        proposal.source_validation_status,
    )
    proposal.validation_status = "valid" if result["valid"] else "invalid"
    proposal.validation_json = json.dumps(result, ensure_ascii=False)
    proposal.validated_at = datetime.now(timezone.utc)
    record_patch_event(
        db,
        proposal.id,
        "validated" if result["valid"] else "validation_failed",
        "system",
        result,
    )
    db.commit()
    return {"proposalId": proposal.id, "status": proposal.validation_status, "validation": result}


@router.post("/{proposal_id}/checkpoint")
def checkpoint_patch_proposal(proposal_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    if proposal.status not in {PatchStatus.PROPOSED.value, PatchStatus.CHECKPOINTED.value}:
        raise HTTPException(status_code=409, detail="Patch proposal is not checkpointable")
    if proposal.source_validation_status != "valid":
        raise HTTPException(status_code=409, detail="PATCH_SOURCE_NOT_VALIDATED")
    proposal.checkpoint_ref = create_checkpoint_ref(
        proposal.id,
        proposal.source_revision,
        proposal.diff_text,
    )
    proposal.status = PatchStatus.CHECKPOINTED.value
    record_patch_event(
        db,
        proposal.id,
        "checkpointed",
        "system",
        {"checkpointRef": proposal.checkpoint_ref, "applied": False},
    )
    db.commit()
    return {
        "proposalId": proposal.id,
        "status": proposal.status,
        "checkpointRef": proposal.checkpoint_ref,
        "applied": False,
    }


@router.post("/{proposal_id}/approve")
def approve_patch_proposal(
    proposal_id: str,
    payload: PatchDecisionRequest,
    request: Request,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    if proposal.source_validation_status != "valid" or proposal.validation_status != "valid":
        raise HTTPException(status_code=409, detail="PATCH_NOT_VALIDATED")
    try:
        authorize_approval(identity.role)
        authorize_environment(
            identity.role,
            proposal.target_environment,
            request.app.state.settings.app_environment,
            json.loads(proposal.impact_json),
        )
        proposal.status = approve_status(proposal.status)
    except (PatchWorkflowError, PatchPolicyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    proposal.approved_by = identity.subject
    proposal.approval_note = payload.note
    proposal.decision_role = identity.role
    record_patch_event(
        db,
        proposal.id,
        "approved",
        identity.subject,
        {
            "note": payload.note,
            "role": identity.role,
            "environment": proposal.target_environment,
            "unresolvedCandidates": sum(
                1 for item in json.loads(proposal.impact_json) if item.get("risk") == "candidate"
            ),
            "applied": False,
        },
    )
    db.commit()
    return {
        "proposalId": proposal.id,
        "status": proposal.status,
        "approvedBy": proposal.approved_by,
        "approvalNote": proposal.approval_note,
        "decisionRole": proposal.decision_role,
        "sourceValidationStatus": proposal.source_validation_status,
        "sourceValidation": json.loads(proposal.source_validation_json),
        "applied": False,
    }


@router.post("/{proposal_id}/reject")
def reject_patch_proposal(
    proposal_id: str,
    payload: PatchDecisionRequest,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    try:
        authorize_rejection(identity.role)
        proposal.status = reject_status(proposal.status)
    except PatchWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    proposal.approved_by = identity.subject
    proposal.approval_note = payload.note
    proposal.decision_role = identity.role
    record_patch_event(
        db,
        proposal.id,
        "rejected",
        identity.subject,
        {"note": payload.note, "role": identity.role, "applied": False},
    )
    db.commit()
    return {
        "proposalId": proposal.id,
        "status": proposal.status,
        "decidedBy": proposal.approved_by,
        "decisionNote": proposal.approval_note,
        "applied": False,
    }


def _proposal_response(proposal: PatchProposal) -> dict[str, object]:
    return {
        "id": proposal.id,
        "projectId": proposal.project_id,
        "taskId": proposal.task_id,
        "status": proposal.status,
        "title": proposal.title,
        "summary": proposal.summary,
        "targetEnvironment": proposal.target_environment,
        "sourceRevision": proposal.source_revision,
        "diff": proposal.diff_text,
        "files": json.loads(proposal.files_json),
        "impact": json.loads(proposal.impact_json),
        "checkpointRef": proposal.checkpoint_ref,
        "approvedBy": proposal.approved_by,
        "approvalNote": proposal.approval_note,
        "decisionRole": proposal.decision_role,
        "sourceValidationStatus": proposal.source_validation_status,
        "sourceValidation": json.loads(proposal.source_validation_json),
        "validationStatus": proposal.validation_status,
        "validation": json.loads(proposal.validation_json),
    }


@router.get("/{proposal_id}/events")
def get_patch_events(proposal_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    if db.get(PatchProposal, proposal_id) is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    events = db.scalars(
        select(PatchEvent)
        .where(PatchEvent.proposal_id == proposal_id)
        .order_by(PatchEvent.created_at, PatchEvent.id)
    ).all()
    return {
        "proposalId": proposal_id,
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


@router.get("/{proposal_id}/package/versions")
def list_patch_package_versions(
    proposal_id: str,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if db.get(PatchProposal, proposal_id) is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    versions = db.scalars(
        select(PatchPackageVersion)
        .where(PatchPackageVersion.proposal_id == proposal_id)
        .order_by(PatchPackageVersion.version.desc())
    ).all()
    return {
        "proposalId": proposal_id,
        "versions": [
            {
                "version": item.version,
                "sha256": item.package_sha256,
                "createdBy": item.created_by,
                "createdAt": item.created_at.isoformat(),
            }
            for item in versions
        ],
    }


@router.get("/{proposal_id}/package")
def download_patch_package(
    proposal_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> Response:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    package_record = _find_package_version(db, proposal_id, version)
    if package_record is None:
        if version is not None:
            raise HTTPException(status_code=404, detail="Patch package version not found")
        package = build_patch_package(proposal, _package_signing_secret(request))
        package_record = PatchPackageVersion(
            id=f"pkg_{uuid4().hex}",
            proposal_id=proposal.id,
            version=1,
            package_bytes=package,
            package_sha256=hashlib.sha256(package).hexdigest(),
            created_by=identity.subject,
        )
        db.add(package_record)
        db.flush()
        record_patch_event(
            db,
            proposal.id,
            "package_stored",
            identity.subject,
            {"version": package_record.version, "sha256": package_record.package_sha256, "applyAllowed": False},
        )
    else:
        package = package_record.package_bytes
    record_patch_event(
        db,
        proposal.id,
        "package_exported",
        identity.subject,
        {"version": package_record.version, "applyAllowed": False},
    )
    db.commit()
    return Response(
        content=package,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{proposal.id}-v{package_record.version}.zip"',
            "X-Package-Version": str(package_record.version),
            "X-Package-Sha256": package_record.package_sha256,
        },
    )


@router.post("/{proposal_id}/package/verify")
async def verify_downloaded_package(
    proposal_id: str,
    request: Request,
    identity: AuthContext = Depends(require_identity),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if db.get(PatchProposal, proposal_id) is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    package = await request.body()
    if len(package) > 10_000_000:
        raise HTTPException(status_code=413, detail="Package is too large")
    result = verify_patch_package(
        package,
        _package_signing_secret(request),
        expected_proposal_id=proposal_id,
    )
    if not result["valid"]:
        raise HTTPException(status_code=422, detail=result["reason"])
    return result


def _find_package_version(db: Session, proposal_id: str, version: int | None) -> PatchPackageVersion | None:
    statement = select(PatchPackageVersion).where(PatchPackageVersion.proposal_id == proposal_id)
    if version is not None:
        statement = statement.where(PatchPackageVersion.version == version)
    else:
        statement = statement.order_by(PatchPackageVersion.version.desc())
    return db.scalars(statement).first()


def _package_signing_secret(request: Request) -> str:
    settings = request.app.state.settings
    secret = settings.inspector_package_signing_secret or settings.inspector_auth_secret
    if not secret:
        raise HTTPException(status_code=503, detail="PACKAGE_SIGNING_NOT_CONFIGURED")
    return secret
