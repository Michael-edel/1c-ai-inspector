import json
import sys
from pathlib import Path

import pytest

from app.services.sandbox_command import SandboxCommandError, run_operator_command


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "sandboxes"
    workspace = root / "sbe_0123456789abcdef0123456789abcdef"
    workspace.mkdir(parents=True)
    return root, workspace


def test_operator_command_runs_json_argv_without_application_secrets(tmp_path: Path, monkeypatch) -> None:
    root, workspace = _workspace(tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "must-not-leak")
    command = json.dumps(
        [
            sys.executable,
            "-c",
            "import os; print(os.getenv('MODEL_API_KEY', 'clean')); print(os.getcwd())",
        ]
    )

    result = run_operator_command(command, workspace, root, 10)

    assert result.succeeded is True
    assert "clean" in result.output
    assert "must-not-leak" not in result.output
    assert str(workspace) in result.output
    assert len(result.output_sha256) == 64


def test_operator_command_limits_output_and_reports_failure(tmp_path: Path) -> None:
    root, workspace = _workspace(tmp_path)
    command = json.dumps([sys.executable, "-c", "print('x' * 1000); raise SystemExit(7)"])

    result = run_operator_command(command, workspace, root, 10, output_limit=100)

    assert result.succeeded is False
    assert result.exit_code == 7
    assert result.output_bytes > 100
    assert len(result.output.encode("utf-8")) <= 100


def test_operator_command_times_out(tmp_path: Path) -> None:
    root, workspace = _workspace(tmp_path)
    command = json.dumps([sys.executable, "-c", "import time; time.sleep(5)"])

    result = run_operator_command(command, workspace, root, 1)

    assert result.timed_out is True
    assert result.exit_code is None


def test_operator_command_rejects_shell_string_and_outside_workspace(tmp_path: Path) -> None:
    root, workspace = _workspace(tmp_path)
    with pytest.raises(SandboxCommandError, match="SANDBOX_COMMAND_INVALID"):
        run_operator_command("echo unsafe", workspace, root, 10)
    with pytest.raises(SandboxCommandError, match="SANDBOX_WORKTREE_PATH_INVALID"):
        run_operator_command(json.dumps([sys.executable, "--version"]), tmp_path, root, 10)
