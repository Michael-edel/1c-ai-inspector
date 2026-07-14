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
