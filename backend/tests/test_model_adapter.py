import json

import httpx

from app.core.config import get_settings
from app.modeling import OpenAICompatibleAdapter


def test_openai_compatible_adapter_parses_content_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
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
