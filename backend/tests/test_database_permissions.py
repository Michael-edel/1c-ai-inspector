from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_new_runtime_default_privileges_are_not_mutating() -> None:
    roles_script = (ROOT / "infra/postgres/init/001_roles.sh").read_text(encoding="utf-8")

    assert "GRANT SELECT, INSERT ON TABLES TO" in roles_script
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO" not in roles_script


def test_existing_audit_tables_are_append_only_for_runtime_role() -> None:
    migration = (ROOT / "backend/migrations/versions/0011_append_only_audit.py").read_text(
        encoding="utf-8"
    )

    for table in (
        "task_events",
        "tool_calls",
        "findings",
        "finding_status_events",
        "model_usage",
        "prompt_execution_snapshots",
    ):
        assert f'"{table}"' in migration
    assert "REVOKE UPDATE, DELETE ON" in migration
    assert "REVOKE UPDATE, DELETE ON TABLES FROM" in migration


def test_foundation_defers_columns_owned_by_later_migrations() -> None:
    foundation = (ROOT / "backend/migrations/versions/0001_foundation.py").read_text(
        encoding="utf-8"
    )

    for table_name, column_name in (
        ("tasks", "cancel_requested"),
        ("tool_calls", "result_size_chars"),
        ("model_usage", "response_checksum"),
        ("model_usage", "cached_input_tokens"),
        ("model_usage", "pricing_source"),
        ("model_usage", "duration_ms"),
    ):
        assert f'(\"{table_name}\", \"{column_name}\")' in foundation
    assert "op.drop_column(table_name, column_name)" in foundation
