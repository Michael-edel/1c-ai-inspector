import pytest
from pydantic import ValidationError

from app.agents.registry import AgentNotReadyError, AgentRegistry
from app.reports.schema import StructuredReport


def test_registry_exposes_four_v01_agents() -> None:
    registry = AgentRegistry()
    assert {agent.code for agent in registry.list()} == {
        "1c_code_assistant",
        "1c_query_agent",
        "1c_audit_agent",
        "1c_data_audit_agent",
    }
    assert {agent.prompt_version for agent in registry.list()} == {"1.1.0", "1.0.0"}


def test_data_row_is_valid_report_evidence() -> None:
    report = StructuredReport.model_validate({
        "taskId": "tsk_data",
        "status": "completed",
        "summary": "Проверена выборка.",
        "findings": [{
            "category": "duplicate_registration",
            "severity": "high",
            "confidence": 0.9,
            "objectFqn": "РегистрНакопления.НДСЗаписиКнигиПродаж",
            "module": "РегистрНакопления.НДСЗаписиКнигиПродаж",
            "description": "Повторная запись.",
            "risk": "Дублирование НДС.",
            "recommendation": "Проверить регистратор.",
            "evidence": [{
                "type": "data_row",
                "objectFqn": "РегистрНакопления.НДСЗаписиКнигиПродаж",
                "module": "РегистрНакопления.НДСЗаписиКнигиПродаж",
                "description": "Регистратор=A, сумма=1000",
            }],
        }],
        "toolUsage": {"calls": 1, "durationMs": 1},
        "modelUsage": {"inputTokens": 1, "outputTokens": 1, "estimatedCost": 0},
    })
    assert report.findings[0].evidence[0].type == "data_row"


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
