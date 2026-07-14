"""Run fixed operator commands without a shell or inherited application secrets."""

import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class SandboxCommandError(ValueError):
    """Raised when an operator command is absent or unsafe."""


@dataclass(frozen=True)
class SandboxCommandResult:
    exit_code: int | None
    duration_ms: int
    output: str
    output_bytes: int
    output_sha256: str
    timed_out: bool

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def as_record(self) -> dict[str, object]:
        return {
            "exitCode": self.exit_code,
            "durationMs": self.duration_ms,
            "output": self.output,
            "outputBytes": self.output_bytes,
            "outputSha256": self.output_sha256,
            "timedOut": self.timed_out,
        }


def run_operator_command(
    command_json: str | None,
    workspace: Path,
    sandbox_root: Path | None,
    timeout_seconds: int,
    output_limit: int = 64_000,
) -> SandboxCommandResult:
    command = _parse_command(command_json)
    root = _existing_directory(sandbox_root, "SANDBOX_ROOT_UNAVAILABLE")
    resolved_workspace = workspace.resolve()
    if resolved_workspace.parent != root or not resolved_workspace.is_dir():
        raise SandboxCommandError("SANDBOX_WORKTREE_PATH_INVALID")
    if output_limit < 1:
        raise SandboxCommandError("SANDBOX_OUTPUT_LIMIT_INVALID")

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=resolved_workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_command_environment(resolved_workspace),
        shell=False,
    )
    output = bytearray()
    digest = hashlib.sha256()
    output_bytes = 0

    def drain_output() -> None:
        nonlocal output_bytes
        assert process.stdout is not None
        while chunk := process.stdout.read(8192):
            digest.update(chunk)
            output_bytes += len(chunk)
            output.extend(chunk)
            if len(output) > output_limit:
                del output[: len(output) - output_limit]

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    timed_out = False
    try:
        exit_code: int | None = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        exit_code = None
    reader.join(timeout=5)
    duration_ms = int((time.monotonic() - started) * 1000)
    return SandboxCommandResult(
        exit_code=exit_code,
        duration_ms=duration_ms,
        output=bytes(output).decode("utf-8", errors="replace"),
        output_bytes=output_bytes,
        output_sha256=digest.hexdigest(),
        timed_out=timed_out,
    )


def _parse_command(command_json: str | None) -> list[str]:
    if not command_json:
        raise SandboxCommandError("SANDBOX_COMMAND_NOT_CONFIGURED")
    try:
        command = json.loads(command_json)
    except json.JSONDecodeError as exc:
        raise SandboxCommandError("SANDBOX_COMMAND_INVALID") from exc
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 32
        or any(not isinstance(value, str) or not value or len(value) > 4_096 for value in command)
    ):
        raise SandboxCommandError("SANDBOX_COMMAND_INVALID")
    return command


def _existing_directory(path: Path | None, error_code: str) -> Path:
    if path is None:
        raise SandboxCommandError(error_code)
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise SandboxCommandError(error_code)
    return resolved


def _command_environment(workspace: Path) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["HOME"] = str(workspace)
    environment["INSPECTOR_SANDBOX_WORKSPACE"] = str(workspace)
    return environment
