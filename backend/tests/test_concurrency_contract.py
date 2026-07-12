import inspect

from app.api.patches import _locked_proposal


def test_proposal_transition_helper_uses_row_lock() -> None:
    assert ".with_for_update()" in inspect.getsource(_locked_proposal)
