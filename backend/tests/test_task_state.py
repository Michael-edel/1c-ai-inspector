import pytest

from app.services.task_state import InvalidTaskTransition, validate_transition


def test_valid_task_transitions() -> None:
    validate_transition("created", "queued")
    validate_transition("queued", "running")
    validate_transition("running", "completed")
    validate_transition("failed", "queued")


def test_invalid_task_transition_is_rejected() -> None:
    with pytest.raises(InvalidTaskTransition):
        validate_transition("completed", "running")
