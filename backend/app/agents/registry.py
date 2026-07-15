from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    prompt_version: str
    required_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    task_kind: str


class AgentNotReadyError(ValueError):
    """Raised when an agent cannot run with the project's capabilities."""


DEFAULT_AGENTS: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        code="1c_code_assistant",
        name="1C Code Assistant",
        prompt_version="1.1.0",
        required_capabilities=("bsl.read", "code.search", "references.read"),
        task_kind="code_question",
    ),
    AgentDefinition(
        code="1c_query_agent",
        name="1C Query Agent",
        prompt_version="1.1.0",
        required_capabilities=("query.validate", "metadata.read"),
        task_kind="query_validation",
    ),
    AgentDefinition(
        code="1c_audit_agent",
        name="1C Audit Agent",
        prompt_version="1.1.0",
        required_capabilities=("bsl.read", "code.search", "references.read"),
        task_kind="module_audit",
    ),
    AgentDefinition(
        code="1c_data_audit_agent",
        name="1C Data Audit Agent",
        prompt_version="1.0.0",
        required_capabilities=("register.records.read",),
        task_kind="register_data_audit",
    ),
)


class AgentRegistry:
    def __init__(self, definitions: tuple[AgentDefinition, ...] = DEFAULT_AGENTS):
        self._definitions = {definition.code: definition for definition in definitions}

    def list(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, code: str) -> AgentDefinition:
        try:
            return self._definitions[code]
        except KeyError as exc:
            raise AgentNotReadyError(f"unknown agent: {code}") from exc

    def validate_capabilities(self, code: str, available: set[str]) -> AgentDefinition:
        definition = self.get(code)
        missing = sorted(set(definition.required_capabilities) - available)
        if missing:
            raise AgentNotReadyError(f"agent {code} is missing capabilities: {', '.join(missing)}")
        return definition

    def as_dicts(self) -> list[dict[str, Any]]:
        return [definition.model_dump() for definition in self.list()]
