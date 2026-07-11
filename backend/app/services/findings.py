import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import Finding, FindingStatusEvent
from app.reports.schema import StructuredReport


def persist_findings(session: Session, report: StructuredReport) -> None:
    for item in report.findings:
        finding_id = f"fnd_{uuid4().hex}"
        session.add(
            Finding(
                id=finding_id,
                task_id=report.task_id,
                category=item.category,
                severity=item.severity,
                confidence=item.confidence,
                object_fqn=item.object_fqn,
                module=item.module,
                method=item.method,
                line_start=item.line_start,
                line_end=item.line_end,
                description=item.description,
                risk=item.risk,
                recommendation=item.recommendation,
                evidence_json=json.dumps(
                    [evidence.model_dump(by_alias=True, mode="json") for evidence in item.evidence],
                    ensure_ascii=False,
                ),
            )
        )
        session.add(
            FindingStatusEvent(
                finding_id=finding_id,
                status="open",
                actor="agent",
            )
        )
