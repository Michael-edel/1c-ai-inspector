import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import ModelUsage, TaskEvent, ToolCall


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
        request_size_bytes: int | None = None,
        result_size_bytes: int | None = None,
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
                request_size_bytes=request_size_bytes,
                result_size_chars=result_size_chars,
                result_size_bytes=result_size_bytes,
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
        estimated_cost: float,
        estimated_cost_kzt: float,
        usd_kzt_rate: float,
        response_checksum: str | None = None,
        cached_input_tokens: int = 0,
        pricing_source: str = "environment",
        duration_ms: int = 0,
        request_size_bytes: int = 0,
        response_size_bytes: int = 0,
    ) -> None:
        self.session.add(
            ModelUsage(
                task_id=task_id,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                duration_ms=duration_ms,
                request_size_bytes=request_size_bytes,
                response_size_bytes=response_size_bytes,
                response_checksum=response_checksum,
                pricing_source=pricing_source,
                estimated_cost=estimated_cost,
                estimated_cost_kzt=estimated_cost_kzt,
                usd_kzt_rate=usd_kzt_rate,
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
