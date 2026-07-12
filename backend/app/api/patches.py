import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PatchStatus
from app.db.session import get_db
from app.models import PatchEvent, PatchProposal, Project, Task
from app.services.patch_audit import record_patch_event
from app.services.patch_proposals import PatchProposalError, build_patch_snapshot, serialize_snapshot
from app.services.patch_impact import analyze_patch_impact
from app.services.patch_checkpoint import create_checkpoint_ref
from app.services.patch_workflow import PatchWorkflowError, approve_status, reject_status
from app.services.patch_package import build_patch_package

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
    actor: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=10_000)


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
def analyze_proposal_impact(proposal_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    impacts = analyze_patch_impact(json.loads(proposal.files_json))
    proposal.impact_json = json.dumps(impacts, ensure_ascii=False)
    record_patch_event(db, proposal.id, "impact_analyzed", "system", {"candidateCount": len(impacts)})
    db.commit()
    return {"proposalId": proposal.id, "status": "analyzed", "impact": impacts}


@router.post("/{proposal_id}/checkpoint")
def checkpoint_patch_proposal(proposal_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    if proposal.status not in {PatchStatus.PROPOSED.value, PatchStatus.CHECKPOINTED.value}:
        raise HTTPException(status_code=409, detail="Patch proposal is not checkpointable")
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
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    try:
        proposal.status = approve_status(proposal.status)
    except PatchWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    proposal.approved_by = payload.actor
    proposal.approval_note = payload.note
    record_patch_event(db, proposal.id, "approved", payload.actor, {"note": payload.note, "applied": False})
    db.commit()
    return {
        "proposalId": proposal.id,
        "status": proposal.status,
        "approvedBy": proposal.approved_by,
        "approvalNote": proposal.approval_note,
        "applied": False,
    }


@router.post("/{proposal_id}/reject")
def reject_patch_proposal(
    proposal_id: str,
    payload: PatchDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    try:
        proposal.status = reject_status(proposal.status)
    except PatchWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    proposal.approved_by = payload.actor
    proposal.approval_note = payload.note
    record_patch_event(db, proposal.id, "rejected", payload.actor, {"note": payload.note, "applied": False})
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


@router.get("/{proposal_id}/package")
def download_patch_package(proposal_id: str, db: Session = Depends(get_db)) -> Response:
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Patch proposal not found")
    package = build_patch_package(proposal)
    record_patch_event(db, proposal.id, "package_exported", "system", {"applyAllowed": False})
    db.commit()
    return Response(
        content=package,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{proposal.id}.zip"'},
    )
