"""Append-only Sandbox Executor audit helpers."""

import json

from sqlalchemy.orm import Session

from app.models import SandboxExecutionEvent


def record_sandbox_event(
    db: Session,
    execution_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, object] | None = None,
) -> SandboxExecutionEvent:
    event = SandboxExecutionEvent(
        execution_id=execution_id,
        event_type=event_type,
        actor=actor,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(event)
    return event
