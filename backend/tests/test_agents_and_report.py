import pytest
from pydantic import ValidationError

from app.agents.registry import AgentNotReadyError, AgentRegistry
from app.reports.schema import StructuredReport


def test_registry_exposes_three_v01_agents() -> None:
    registry = AgentRegistry()
    assert {agent.code for agent in registry.list()} == {
        "1c_code_assistant",
        "1c_query_agent",
        "1c_audit_agent",
    }
    assert {agent.prompt_version for agent in registry.list()} == {"1.1.0"}


def test_registry_rejects_missing_capability() -> None:
    with pytest.raises(AgentNotReadyError, match="missing capabilities"):
        AgentRegistry().validate_capabilities("1c_code_assistant", set())


def test_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        StructuredReport.model_validate(
            {
                "taskId": "tsk_1",
                "status": "completed",
                "summary": "No evidence",
                "findings": [{
                    "category": "performance",
                    "severity": "high",
                    "confidence": 0.9,
                    "objectFqn": "Catalog.Items",
                    "module": "ObjectModule",
                    "description": "Issue",
                    "risk": "Risk",
                    "recommendation": "Fix",
                    "evidence": [],
                }],
                "toolUsage": {"calls": 0, "durationMs": 0},
                "modelUsage": {"inputTokens": 0, "outputTokens": 0, "estimatedCost": 0},
            }
        )
