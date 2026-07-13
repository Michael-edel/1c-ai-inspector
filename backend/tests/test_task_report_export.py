import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.tasks import export_task_report
from app.models import Base, Task


def test_task_report_export_contains_report_and_audit() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Task(
            id="tsk_export",
            project_id="prj_export",
            agent_id="agt_export",
            status="completed",
            request_json='{"text":"private request"}',
            result_json=json.dumps({"status": "completed", "summary": "Safe report", "findings": []}),
            available_at=datetime.now(timezone.utc),
        ))
        session.commit()

        response = export_task_report("tsk_export", session)

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="tsk_export-report.json"'
    assert payload["taskId"] == "tsk_export"
    assert payload["report"]["summary"] == "Safe report"
    assert payload["report"]["persistedFindings"] == []
    assert payload["audit"]["task_id"] == "tsk_export"
    assert "private request" not in response.body.decode()
