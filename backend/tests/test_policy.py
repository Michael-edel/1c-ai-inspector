from pathlib import Path

import pytest

from app.mcp.policy import PolicyError, PolicyProvider


def test_empty_policy_is_valid() -> None:
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    assert snapshot.policy.version == "1.0.0"
    assert snapshot.published_tools == {}
    assert len(snapshot.checksum) == 64


def test_write_tool_cannot_be_activated(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n  write: {name: write, category: test, mode: write}\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="non-read-only"):
        PolicyProvider(path).load()
