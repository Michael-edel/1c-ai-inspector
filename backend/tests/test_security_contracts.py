from pathlib import Path

import pytest

from app.mcp.policy import PolicyError, PolicyProvider


def test_policy_rejects_write_tools_before_activation(tmp_path: Path) -> None:
    path = tmp_path / "write-policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n"
        "  Write Module: {name: raw, category: bsl.write, mode: write}\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="cannot publish"):
        PolicyProvider(path).load()
