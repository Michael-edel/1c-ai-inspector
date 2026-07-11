from dataclasses import dataclass
import json
from typing import Protocol

import httpx

from app.core.config import Settings


@dataclass(frozen=True)
class ModelResult:
    content: str
    input_tokens: int
    output_tokens: int


class ModelAdapter(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> ModelResult: ...


class ModelError(RuntimeError):
    """Raised when the configured model cannot produce a usable response."""


class OpenAICompatibleAdapter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        url = f"{str(self.settings.model_api_url).rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=self.settings.task_timeout_sec, transport=self.transport) as client:
                response = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.model_api_key}"},
                    json={
                        "model": self.settings.model_name,
                        "messages": messages,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelError("MODEL_REQUEST_FAILED") from exc

        try:
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) for item in content if isinstance(item, dict)
                )
            content = str(content).strip()
            if content.startswith("```"):
                content = content.removeprefix("```").removeprefix("json").removesuffix("```").strip()
            json.loads(content)
            usage = body.get("usage", {})
            return ModelResult(
                content=content,
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelError("MODEL_RESPONSE_INVALID") from exc
