from sqlalchemy.orm import Session

from app.core.enums import TaskStatus
from app.models import Task
from app.services.audit import AuditRecorder
from app.services.task_state import ACTIVE_TASK_STATUSES, transition_task

CANCELLED_BY_USER = "TASK_CANCELLED_BY_USER"


class TaskNotCancellable(ValueError):
    """Raised when a terminal task cannot be cancelled."""


def request_task_cancellation(session: Session, task: Task, actor: str) -> None:
    if task.status == TaskStatus.CANCELLED.value:
        return
    if task.status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
        raise TaskNotCancellable("TASK_NOT_CANCELLABLE")
    if task.status in {TaskStatus.CREATED.value, TaskStatus.QUEUED.value}:
        transition_task(
            session,
            task,
            TaskStatus.CANCELLED.value,
            details={"actor": actor, "reason": CANCELLED_BY_USER},
        )
        task.last_error_code = CANCELLED_BY_USER
        task.cancel_requested = True
        AuditRecorder(session).record_event(
            task.id,
            "task_cancelled",
            {"actor": actor, "reason": CANCELLED_BY_USER},
        )
        return
    if task.status in ACTIVE_TASK_STATUSES:
        task.cancel_requested = True
        AuditRecorder(session).record_event(
            task.id,
            "task_cancel_requested",
            {"actor": actor, "reason": CANCELLED_BY_USER},
        )
        return
    raise TaskNotCancellable("TASK_NOT_CANCELLABLE")


def finalize_task_cancellation(session: Session, task: Task, actor: str) -> None:
    if task.status != TaskStatus.CANCELLED.value:
        transition_task(
            session,
            task,
            TaskStatus.CANCELLED.value,
            details={"actor": actor, "reason": CANCELLED_BY_USER},
        )
        task.last_error_code = CANCELLED_BY_USER
        task.cancel_requested = True
        task.locked_by = None
        task.locked_at = None
        task.heartbeat_at = None
        AuditRecorder(session).record_event(
            task.id,
            "task_cancelled",
            {"actor": actor, "reason": CANCELLED_BY_USER},
        )
