from app.core.enums import TaskStatus


class InvalidTaskTransition(ValueError):
    """Raised when a task state transition is outside the v0.1 state machine."""


ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.FAILED: frozenset({TaskStatus.QUEUED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def validate_transition(current: str, target: str) -> None:
    try:
        current_status = TaskStatus(current)
        target_status = TaskStatus(target)
    except ValueError as exc:
        raise InvalidTaskTransition(f"unknown task transition: {current} -> {target}") from exc
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidTaskTransition(f"invalid task transition: {current} -> {target}")
