import json

from sqlalchemy.orm import Session

from app.agents.registry import AgentDefinition
from app.core.config import Settings
from app.models import Task
from app.modeling import ModelAdapter, ModelError
from app.reports.schema import StructuredReport
from app.services.audit import AuditRecorder
from app.services.context import ContextBuilder, ContextLimitError


class AgentExecutionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def execute_agent(
    session: Session,
    task: Task,
    definition: AgentDefinition,
    settings: Settings,
    adapter: ModelAdapter,
    extra_context: list[dict[str, object]] | None = None,
) -> StructuredReport:
    try:
        request = json.loads(task.request_json)
        if extra_context:
            request = dict(request)
            request["context"] = list(request.get("context", [])) + extra_context
        context = ContextBuilder(settings).build(request)
    except ContextLimitError as exc:
        raise AgentExecutionError(str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise AgentExecutionError("TASK_REQUEST_INVALID") from exc

    messages = [
        {
            "role": "system",
            "content": (
                "You are a read-only 1C inspection agent. Return JSON matching the StructuredReport "
                "schema. Every finding must include at least one evidence item. Do not invent evidence."
            ),
        },
        {
            "role": "user",
            "content": f"{context}\n\nTask envelope:\n" + json.dumps(
                {"taskId": task.id, "agent": definition.code, "request": request},
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = adapter.complete(messages)
        report = StructuredReport.model_validate_json(result.content)
    except ModelError as exc:
        raise AgentExecutionError(str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise AgentExecutionError("MODEL_REPORT_INVALID") from exc

    if report.task_id != task.id:
        raise AgentExecutionError("MODEL_REPORT_TASK_MISMATCH")
    AuditRecorder(session).record_model_usage(
        task.id,
        settings.model_provider,
        settings.model_name,
        result.input_tokens,
        result.output_tokens,
        settings.model_input_cost_per_1k,
        settings.model_output_cost_per_1k,
    )
    return report
