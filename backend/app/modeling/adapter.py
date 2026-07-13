from dataclasses import dataclass
import json
import time
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


class ModelTimeoutError(ModelError):
    """Raised when the model reaches the parent task deadline."""


class OpenAICompatibleAdapter:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        deadline: float | None = None,
    ):
        self.settings = settings
        self.transport = transport
        self.deadline = deadline

    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        url = f"{str(self.settings.model_api_url).rstrip('/')}/chat/completions"
        try:
            payload = {
                "model": self.settings.model_name,
                "messages": messages,
                "response_format": {"type": "json_object"},
            }
            if not self.settings.model_name.lower().startswith("gpt-5"):
                payload["temperature"] = 0
            deadline_limited = False
            timeout = float(self.settings.task_timeout_sec)
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelTimeoutError("TASK_TIMEOUT")
                timeout = min(timeout, remaining)
                deadline_limited = remaining <= self.settings.task_timeout_sec
            with httpx.Client(timeout=timeout, transport=self.transport) as client:
                response = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.settings.model_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except ModelTimeoutError:
            raise
        except httpx.TimeoutException as exc:
            if self.deadline is not None and deadline_limited:
                raise ModelTimeoutError("TASK_TIMEOUT") from exc
            raise ModelError("MODEL_REQUEST_FAILED") from exc
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
