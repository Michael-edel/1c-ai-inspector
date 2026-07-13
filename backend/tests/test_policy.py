from pathlib import Path

import pytest

from app.mcp.policy import PolicyError, PolicyProvider


def test_bridge_policy_is_read_only() -> None:
    snapshot = PolicyProvider(Path(__file__).parents[2] / "mcp_policy.yaml").load()
    assert snapshot.policy.version == "1.1.0"
    assert set(snapshot.published_tools) == {
        "bsl_syntax_help",
        "get_configuration_info",
        "get_event_log",
        "get_form_structure",
        "get_metadata_tree",
        "get_object_structure",
        "read_source",
        "search_code",
        "validate_query",
    }
    assert "execute_query" not in snapshot.published_tools
    assert len(snapshot.checksum) == 64
    assert len(snapshot.toolset_checksum) == 64


def test_tool_names_are_normalized(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n  Read Module.Source: {name: raw, category: bsl.read, mode: read-only}\n",
        encoding="utf-8",
    )
    snapshot = PolicyProvider(path).load()
    assert list(snapshot.normalized_tools) == ["read_module_source"]
    assert snapshot.published_tools["read_module_source"].name == "read_module_source"


def test_write_tool_cannot_be_activated(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "policyId: test\nversion: 1.0.0\ntools:\n  write: {name: write, category: test, mode: write}\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="non-read-only"):
        PolicyProvider(path).load()
