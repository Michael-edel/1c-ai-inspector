"""Persist a small, append-only audit trail for proposal workflow actions."""

import json

from sqlalchemy.orm import Session

from app.models import PatchEvent


def record_patch_event(
    db: Session,
    proposal_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, object] | None = None,
) -> PatchEvent:
    event = PatchEvent(
        proposal_id=proposal_id,
        event_type=event_type,
        actor=actor,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(event)
    return event
