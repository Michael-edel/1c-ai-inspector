from app.core.enums import TaskStatus
from app.models import Task
from app.services.audit import AuditRecorder
from sqlalchemy.orm import Session


class InvalidTaskTransition(ValueError):
    """Raised when a task state transition is outside the v0.1 state machine."""


ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.DISCOVERING, TaskStatus.CANCELLED}),
    TaskStatus.DISCOVERING: frozenset(
        {TaskStatus.ANALYZING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.ANALYZING: frozenset(
        {TaskStatus.REPORTING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.REPORTING: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    # Legacy states remain readable and recoverable during rolling deployment.
    TaskStatus.QUEUED: frozenset({TaskStatus.DISCOVERING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.DISCOVERING,
            TaskStatus.ANALYZING,
            TaskStatus.REPORTING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

ACTIVE_TASK_STATUSES = frozenset(
    {
        TaskStatus.DISCOVERING.value,
        TaskStatus.ANALYZING.value,
        TaskStatus.REPORTING.value,
        TaskStatus.RUNNING.value,
    }
)

CLAIMABLE_TASK_STATUSES = frozenset(
    {TaskStatus.CREATED.value, TaskStatus.QUEUED.value}
)


def validate_transition(current: str, target: str) -> None:
    try:
        current_status = TaskStatus(current)
        target_status = TaskStatus(target)
    except ValueError as exc:
        raise InvalidTaskTransition(f"unknown task transition: {current} -> {target}") from exc
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidTaskTransition(f"invalid task transition: {current} -> {target}")


def transition_task(
    session: Session,
    task: Task,
    target: str,
    *,
    details: dict[str, object] | None = None,
) -> None:
    current = task.status
    validate_transition(current, target)
    task.status = target
    AuditRecorder(session).record_event(
        task.id,
        "task_status_changed",
        {"from": current, "to": target, **(details or {})},
    )
