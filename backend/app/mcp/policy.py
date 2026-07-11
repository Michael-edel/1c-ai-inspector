import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from app.core.enums import ToolMode
from app.mcp.contracts import PolicyFile, ToolContract


class PolicyError(ValueError):
    """Raised when an MCP policy cannot be safely activated."""


class PolicySnapshot:
    def __init__(self, policy: PolicyFile, checksum: str, normalized_tools: dict[str, ToolContract]):
        self.policy = policy
        self.checksum = checksum
        self.normalized_tools = normalized_tools
        self.toolset_checksum = self._calculate_toolset_checksum(normalized_tools)

    @property
    def published_tools(self) -> dict[str, ToolContract]:
        return {
            name: tool
            for name, tool in self.normalized_tools.items()
            if tool.mode is ToolMode.READ_ONLY
        }

    @staticmethod
    def _calculate_toolset_checksum(tools: dict[str, ToolContract]) -> str:
        canonical = json.dumps(
            {
                name: tool.model_dump(mode="json")
                for name, tool in sorted(tools.items())
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


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
        normalized_tools: dict[str, ToolContract] = {}
        for original_name, tool in policy.tools.items():
            normalized_name = self._normalize_tool_name(original_name)
            if normalized_name in normalized_tools:
                raise PolicyError(f"duplicate normalized tool name: {normalized_name}")
            normalized_tools[normalized_name] = tool.model_copy(update={"name": normalized_name})

        return PolicySnapshot(policy, hashlib.sha256(canonical).hexdigest(), normalized_tools)

    @staticmethod
    def _normalize_tool_name(name: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
        if not normalized:
            raise PolicyError(f"tool name cannot be normalized: {name!r}")
        return normalized
