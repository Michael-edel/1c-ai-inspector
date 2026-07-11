import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from app.core.enums import ToolMode
from app.mcp.contracts import PolicyFile, ToolContract


class PolicyError(ValueError):
    """Raised when an MCP policy cannot be safely activated."""


class PolicySnapshot:
    def __init__(self, policy: PolicyFile, checksum: str):
        self.policy = policy
        self.checksum = checksum

    @property
    def published_tools(self) -> dict[str, ToolContract]:
        return {
            name: tool
            for name, tool in self.policy.tools.items()
            if tool.mode is ToolMode.READ_ONLY
        }


class PolicyProvider:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> PolicySnapshot:
        if not self.path.is_file():
            raise PolicyError(f"MCP policy file not found: {self.path}")
        try:
            raw: dict[str, Any] = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            policy = PolicyFile.model_validate(raw)
        except Exception as exc:
            raise PolicyError(f"Invalid MCP policy: {exc}") from exc

        for name, tool in policy.tools.items():
            if tool.mode is ToolMode.CONDITIONAL_WRITE and not tool.write_conditions:
                raise PolicyError(f"conditional-write tool requires writeConditions: {name}")
            if tool.mode is not ToolMode.READ_ONLY:
                raise PolicyError(f"v0.1 cannot publish non-read-only tool: {name}")
            if tool.side_effects:
                raise PolicyError(f"read-only tool has side effects: {name}")

        canonical = json.dumps(
            policy.model_dump(by_alias=True, mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return PolicySnapshot(policy, hashlib.sha256(canonical).hexdigest())
