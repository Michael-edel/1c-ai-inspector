import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.enums import PatchStatus
from app.db.session import get_db
from app.models import PatchProposal, Project, Task
from app.services.patch_proposals import PatchProposalError, build_patch_snapshot, serialize_snapshot
from app.services.patch_impact import analyze_patch_impact

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
    db.commit()
    return {"proposalId": proposal.id, "status": "analyzed", "impact": impacts}


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
        "approvalNote": proposal.approval_note,
    }
