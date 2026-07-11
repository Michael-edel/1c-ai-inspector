import pytest

from app.services.costs import estimate_cost


def test_estimate_cost() -> None:
    assert estimate_cost(1500, 500, 0.2, 0.4) == 0.5


def test_negative_cost_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_cost(-1, 0, 0, 0)
