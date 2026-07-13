import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.tasks import task_report
from app.models import Base, Finding, Task


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
