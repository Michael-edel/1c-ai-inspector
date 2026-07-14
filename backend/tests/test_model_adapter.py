import json
import hashlib
import time

import httpx
import pytest

from app.core.config import get_settings
from app.modeling import ModelTimeoutError, OpenAICompatibleAdapter


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
