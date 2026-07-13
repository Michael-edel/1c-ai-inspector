import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.executor import AgentExecutionError, execute_agent
from app.agents.registry import AgentRegistry
from app.core.config import get_settings
from app.modeling import ModelResult
from app.models import Base, ModelUsage, Task


class FakeAdapter:
    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        payload = json.loads(messages[-1]["content"].split("Task envelope:\n", 1)[1])
        report = {
            "taskId": payload["taskId"],
            "status": "completed",
            "summary": "No issues found",
            "findings": [],
            "objectsReviewed": [],
            "validation": {"readOnly": True},
            "toolUsage": {"calls": 0, "durationMs": 0},
            "modelUsage": {"inputTokens": 3, "outputTokens": 5, "estimatedCost": 0},
            "limitations": [],
            "nextActions": [],
        }
        return ModelResult(json.dumps(report), 3, 5)


class SchemaCheckingAdapter(FakeAdapter):
    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        assert "StructuredReport JSON Schema" in messages[0]["content"]
        assert '"taskId"' in messages[0]["content"]
        return super().complete(messages)


class TooManyFindingsAdapter(FakeAdapter):
    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        report = json.loads(super().complete(messages).content)
        finding = {
            "category": "business_logic",
            "severity": "low",
            "confidence": 0.8,
            "objectFqn": "Документ.ЗаказКлиента",
            "module": "Документ.ЗаказКлиента.МодульОбъекта",
            "description": "Issue",
            "risk": "Risk",
            "recommendation": "Fix",
            "evidence": [{
                "type": "reference",
                "objectFqn": "Документ.ЗаказКлиента",
                "module": "Документ.ЗаказКлиента.МодульОбъекта",
            }],
        }
        report["findings"] = [finding, finding]
        return ModelResult(json.dumps(report, ensure_ascii=False), 3, 5)


class SourceEvidenceAdapter(FakeAdapter):
    def __init__(self, *, valid: bool, excerpt_valid: bool = True, require_source_limits: bool = False):
        self.valid = valid
        self.excerpt_valid = excerpt_valid
        self.require_source_limits = require_source_limits

    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        if self.require_source_limits:
            assert "Full source line limits:" in messages[0]["content"]
        payload = json.loads(messages[-1]["content"].split("Task envelope:\n", 1)[1])
        report = {
            "taskId": payload["taskId"],
            "status": "completed",
            "summary": "Source evidence checked",
            "findings": [{
                "category": "business_logic",
                "severity": "medium",
                "confidence": 0.8,
                "objectFqn": "Документ.ЗаказКлиента",
                "module": "Документ.ЗаказКлиента.МодульОбъекта",
                "lineStart": 2,
                "lineEnd": 2,
                "description": "Issue",
                "risk": "Risk",
                "recommendation": "Fix",
                "evidence": [{
                    "type": "source_range",
                    "objectFqn": "Документ.ЗаказКлиента",
                    "module": "Документ.ЗаказКлиента.МодульОбъекта",
                    "lineStart": 99 if not self.valid else 2,
                    "lineEnd": 99 if not self.valid else 2,
                    "excerpt": "А = 1;" if self.valid and self.excerpt_valid else "Неизвестный код",
                }],
            }],
            "objectsReviewed": [],
            "validation": {"readOnly": True},
            "toolUsage": {"calls": 0, "durationMs": 0},
            "modelUsage": {"inputTokens": 3, "outputTokens": 5, "estimatedCost": 0},
            "limitations": [],
            "nextActions": [],
        }
        return ModelResult(json.dumps(report, ensure_ascii=False), 3, 5)


def test_agent_execution_persists_model_usage() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_test",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "inspect"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_code_assistant"),
            get_settings(),
            FakeAdapter(),
            tool_calls=[{"durationMs": 17}],
        )
        session.commit()
        assert report.status == "completed"
        assert report.tool_usage.calls == 1
        assert report.tool_usage.duration_ms == 17
        assert report.model_usage.input_tokens == 3
        assert report.model_usage.output_tokens == 5
        usage = session.scalars(select(ModelUsage).where(ModelUsage.task_id == task.id)).one()
        assert usage.input_tokens == 3
        assert usage.output_tokens == 5


def test_agent_execution_rejects_too_many_findings() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_findings_limit",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "inspect"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()

        with pytest.raises(AgentExecutionError, match="FINDINGS_LIMIT_EXCEEDED"):
            execute_agent(
                session,
                task,
                AgentRegistry().get("1c_code_assistant"),
                get_settings().model_copy(update={"max_findings": 1}),
                TooManyFindingsAdapter(),
            )


def test_agent_prompt_contains_structured_report_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_schema",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "inspect"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_code_assistant"),
            get_settings(),
            SchemaCheckingAdapter(),
        )
        assert report.status == "completed"


def test_module_audit_marks_partial_source_context() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_partial_source",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "audit"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_audit_agent"),
            get_settings(),
            FakeAdapter(),
            extra_context=[
                {
                    "source": "MCP",
                    "tool": "search_code",
                    "data": {
                        "content": [
                            {
                                "type": "text",
                                "text": "### Документ.ЗаказКлиента.МодульОбъекта\n```bsl\nВызов();\n```",
                            }
                        ]
                    },
                }
            ],
        )
        assert report.source_coverage == "partial"
        assert any("частичн" in item and "search_code" in item for item in report.limitations)
        assert report.next_actions


def test_module_audit_marks_complete_source_context() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_full_source",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "audit"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_audit_agent"),
            get_settings(),
            FakeAdapter(),
            extra_context=[
                {
                    "source": "MCP",
                    "tool": "read_source",
                    "data": {
                        "sourceComplete": True,
                        "content": [{"type": "text", "text": "full module source"}],
                    },
                }
            ],
        )
        assert report.source_coverage == "full"
        assert report.limitations == []


def test_source_range_evidence_is_validated_against_full_source() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_valid_source_evidence",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "audit"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        source_context = [{
            "source": "MCP",
            "tool": "read_source",
            "data": {
                "sourceComplete": True,
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "module": "Документ.ЗаказКлиента.МодульОбъекта",
                        "source": "Процедура Тест()\nА = 1;\nКонецПроцедуры",
                        "sourceComplete": True,
                    }, ensure_ascii=False),
                }],
            },
        }]
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_audit_agent"),
            get_settings(),
            SourceEvidenceAdapter(valid=True, require_source_limits=True),
            extra_context=source_context,
        )
        assert report.source_coverage == "full"
        task_sanitized = Task(
            id="tsk_sanitized_source_evidence",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "audit"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task_sanitized)
        session.commit()
        sanitized = execute_agent(
            session,
            task_sanitized,
            AgentRegistry().get("1c_audit_agent"),
            get_settings(),
            SourceEvidenceAdapter(valid=True, excerpt_valid=False),
            extra_context=source_context,
        )
        assert sanitized.findings[0].evidence[0].excerpt is None
        assert sanitized.validation["sourceEvidence"]["excerptCount"] == 1


def test_invalid_source_range_evidence_is_filtered() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        task = Task(
            id="tsk_invalid_source_evidence",
            project_id="prj_test",
            agent_id="agt_test",
            status="running",
            request_json=json.dumps({"text": "audit"}),
            available_at=datetime.now(timezone.utc),
        )
        session.add(task)
        session.commit()
        report = execute_agent(
            session,
            task,
            AgentRegistry().get("1c_audit_agent"),
            get_settings(),
            SourceEvidenceAdapter(valid=False),
            extra_context=[{
                "source": "MCP",
                "tool": "read_source",
                "data": {
                    "sourceComplete": True,
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "module": "Документ.ЗаказКлиента.МодульОбъекта",
                            "source": "Процедура Тест()\nА = 1;\nКонецПроцедуры",
                            "sourceComplete": True,
                        }, ensure_ascii=False),
                    }],
                },
            }],
        )
        assert report.findings == []
        assert any("неподтвержденные" in item for item in report.limitations)
        assert report.validation["sourceEvidence"]["invalidCount"] == 1
