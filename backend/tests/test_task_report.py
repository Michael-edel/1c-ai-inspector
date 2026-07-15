import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.tasks import task_report
from app.models import Base, Finding, ModelUsage, PromptExecutionSnapshot, Task


def test_task_report_returns_full_persisted_finding() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    evidence = [{
        "type": "source_range",
        "objectFqn": "Document.SalesOrder",
        "module": "ObjectModule",
        "method": "BeforeWrite",
        "lineStart": 12,
        "lineEnd": 14,
        "excerpt": "Status = NewStatus;",
        "description": "Direct assignment",
        "toolCallId": "call_1",
    }]

    with Session(engine) as session:
        session.add(Task(
            id="tsk_report",
            project_id="prj_report",
            agent_id="agt_report",
            status="completed",
            request_json="{}",
            result_json=json.dumps({"taskId": "tsk_report", "findings": []}),
            available_at=datetime.now(timezone.utc),
        ))
        session.add(PromptExecutionSnapshot(
            id="snap_report",
            task_id="tsk_report",
            prompt_version="1.0.0",
            model_provider="openai",
            model_name="test-model",
            policy_version="1.1.0",
            policy_checksum="policy-checksum",
            toolset_checksum="toolset-checksum",
        ))
        session.add(ModelUsage(
            task_id="tsk_report",
            provider="openai",
            model="test-model",
            input_tokens=11,
            output_tokens=7,
            cached_input_tokens=3,
            duration_ms=23,
            estimated_cost=0.12,
            estimated_cost_kzt=10.5,
            pricing_source="environment",
        ))
        session.add(Finding(
            id="fnd_report",
            task_id="tsk_report",
            category="business_logic_validation",
            severity="medium",
            confidence=0.75,
            object_fqn="Document.SalesOrder",
            module="ObjectModule",
            method="BeforeWrite",
            line_start=12,
            line_end=14,
            description="Direct assignment",
            risk="Invalid transition",
            recommendation="Validate transition",
            evidence_json=json.dumps(evidence),
        ))
        session.commit()

        report = task_report("tsk_report", session)

    assert report["persistedFindings"] == [{
        "id": "fnd_report",
        "category": "business_logic_validation",
        "severity": "medium",
        "confidence": 0.75,
        "objectFqn": "Document.SalesOrder",
        "module": "ObjectModule",
        "method": "BeforeWrite",
        "lineStart": 12,
        "lineEnd": 14,
        "description": "Direct assignment",
        "risk": "Invalid transition",
        "recommendation": "Validate transition",
        "evidence": evidence,
    }]
    assert report["execution"] == {
        "promptVersion": "1.0.0",
        "modelProvider": "openai",
        "modelName": "test-model",
        "policyVersion": "1.1.0",
        "policyChecksum": "policy-checksum",
        "toolsetChecksum": "toolset-checksum",
    }
    assert report["modelUsage"] == {
        "model": "test-model",
        "inputTokens": 11,
        "outputTokens": 7,
        "cachedInputTokens": 3,
        "durationMs": 23,
        "estimatedCost": 0.12,
        "estimatedCostKzt": 11,
        "usdKztRate": 0.0,
        "pricingSource": "environment",
    }


def test_task_report_normalizes_legacy_minimal_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Task(
            id="tsk_legacy_failure",
            project_id="prj_report",
            agent_id="agt_report",
            status="failed",
            request_json="{}",
            result_json=json.dumps({"status": "failed", "errorCode": "MCP_TOOL_CALL_FAILED"}),
            last_error_code=None,
            available_at=datetime.now(timezone.utc),
        ))
        session.commit()

        report = task_report("tsk_legacy_failure", session)

    assert report["taskId"] == "tsk_legacy_failure"
    assert report["summary"]
    assert report["findings"] == []
    assert report["validation"]["errorCode"] == "MCP_TOOL_CALL_FAILED"
    assert report["toolUsage"] == {"calls": 0, "durationMs": 0}
