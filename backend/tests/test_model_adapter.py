import json
import hashlib
import time

import httpx
import pytest

from app.core.config import get_settings
from app.modeling import ModelError, ModelTimeoutError, OpenAICompatibleAdapter
from app.services.traffic import TrafficLimitExceeded


def test_openai_compatible_adapter_parses_content_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            },
        )

    settings = get_settings()
    adapter = OpenAICompatibleAdapter(
        settings,
        transport=httpx.MockTransport(handler),
    )
    result = adapter.complete([{"role": "user", "content": "test"}])

    assert json.loads(result.content) == {"ok": True}
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.cached_input_tokens == 4
    assert result.response_checksum == hashlib.sha256(result.content.encode("utf-8")).hexdigest()
    assert result.request_size_bytes > 0
    assert result.response_size_bytes > 0


def test_openai_compatible_adapter_accepts_content_blocks_and_json_fence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": [{"text": '```json\n{"ok":true}\n```'}]}}],
                "usage": {},
            },
        )

    result = OpenAICompatibleAdapter(
        get_settings(), transport=httpx.MockTransport(handler)
    ).complete([])
    assert json.loads(result.content) == {"ok": True}


def test_openai_compatible_adapter_retries_transient_http_failure(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []
    monkeypatch.setattr(time, "sleep", delays.append)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    settings = get_settings().model_copy(update={"model_retries": 1})
    result = OpenAICompatibleAdapter(
        settings, transport=httpx.MockTransport(handler)
    ).complete([])

    assert json.loads(result.content) == {"ok": True}
    assert attempts == 2
    assert delays == [1]


def test_openai_compatible_adapter_does_not_retry_invalid_json_response() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    settings = get_settings().model_copy(update={"model_retries": 2})
    with pytest.raises(ModelError, match="MODEL_RESPONSE_INVALID"):
        OpenAICompatibleAdapter(
            settings, transport=httpx.MockTransport(handler)
        ).complete([])

    assert attempts == 1


def test_gpt5_adapter_uses_model_default_temperature() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "temperature" not in payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":true}'}}]},
        )

    settings = get_settings().model_copy(update={"model_name": "gpt-5.5"})
    result = OpenAICompatibleAdapter(
        settings, transport=httpx.MockTransport(handler)
    ).complete([])
    assert json.loads(result.content) == {"ok": True}


def test_model_adapter_rejects_an_expired_parent_deadline() -> None:
    adapter = OpenAICompatibleAdapter(
        get_settings(),
        transport=httpx.MockTransport(lambda _: pytest.fail("expired task must not call model")),
        deadline=time.monotonic() - 1,
    )

    with pytest.raises(ModelTimeoutError, match="TASK_TIMEOUT"):
        adapter.complete([])


def test_model_adapter_stops_before_call_when_monthly_traffic_is_exhausted() -> None:
    class BlockingTrafficController:
        def reserve(self, _: int):
            raise TrafficLimitExceeded("MONTHLY_TRAFFIC_LIMIT_EXCEEDED")

    adapter = OpenAICompatibleAdapter(
        get_settings(),
        transport=httpx.MockTransport(lambda _: pytest.fail("blocked traffic must not call model")),
        traffic_controller=BlockingTrafficController(),  # type: ignore[arg-type]
    )

    with pytest.raises(ModelError, match="MONTHLY_TRAFFIC_LIMIT_EXCEEDED"):
        adapter.complete([])
