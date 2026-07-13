import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import ModelUsage, TaskEvent, ToolCall
from app.services.costs import estimate_cost


class AuditRecorder:
    def __init__(self, session: Session):
        self.session = session

    def record_tool_call(
        self,
        task_id: str,
        tool_name: str,
        mode: str,
        input_payload: dict[str, object],
        output_payload: dict[str, object] | None = None,
        status: str = "completed",
        duration_ms: int | None = None,
        error_code: str | None = None,
        result_size_chars: int | None = None,
    ) -> str:
        call_id = f"call_{uuid4().hex}"
        self.session.add(
            ToolCall(
                id=call_id,
                task_id=task_id,
                tool_name=tool_name,
                mode=mode,
                status=status,
                input_json=json.dumps(input_payload, ensure_ascii=False),
                output_json=json.dumps(output_payload, ensure_ascii=False) if output_payload else None,
                result_size_chars=result_size_chars,
                duration_ms=duration_ms,
                error_code=error_code,
            )
        )
        return call_id

    def record_model_usage(
        self,
        task_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        input_cost_per_1k: float,
        output_cost_per_1k: float,
        response_checksum: str | None = None,
    ) -> None:
        self.session.add(
            ModelUsage(
                task_id=task_id,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                response_checksum=response_checksum,
                estimated_cost=estimate_cost(
                    input_tokens, output_tokens, input_cost_per_1k, output_cost_per_1k
                ),
            )
        )

    def record_event(self, task_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.session.add(
            TaskEvent(
                task_id=task_id,
                event_type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
        )
