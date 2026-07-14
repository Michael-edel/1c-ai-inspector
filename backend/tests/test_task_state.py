import pytest

from app.services.task_state import InvalidTaskTransition, validate_transition


def test_valid_task_transitions() -> None:
    validate_transition("created", "discovering")
    validate_transition("discovering", "analyzing")
    validate_transition("analyzing", "reporting")
    validate_transition("reporting", "completed")


def test_invalid_task_transition_is_rejected() -> None:
    with pytest.raises(InvalidTaskTransition):
        validate_transition("completed", "discovering")


def test_task_cannot_skip_a_required_phase() -> None:
    with pytest.raises(InvalidTaskTransition):
        validate_transition("discovering", "reporting")


def test_legacy_queue_states_can_enter_the_v01_machine() -> None:
    validate_transition("queued", "discovering")
    validate_transition("running", "analyzing")
