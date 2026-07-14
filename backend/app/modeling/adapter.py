from dataclasses import dataclass
import hashlib
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
    response_checksum: str = ""
    cached_input_tokens: int = 0


class ModelAdapter(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> ModelResult: ...


class ModelError(RuntimeError):
    """Raised when the configured model cannot produce a usable response."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _RetryableModelError(ModelError):
    """Raised for model failures that are safe to retry."""


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
        for attempt in range(self.settings.model_retries + 1):
            try:
                return self._complete_once(messages)
            except ModelTimeoutError:
                raise
            except _RetryableModelError as exc:
                if attempt >= self.settings.model_retries:
                    raise ModelError(exc.code) from exc
                if self.deadline is not None and time.monotonic() >= self.deadline:
                    raise ModelTimeoutError("TASK_TIMEOUT") from exc
        raise ModelError("MODEL_REQUEST_FAILED")

    def _complete_once(self, messages: list[dict[str, str]]) -> ModelResult:
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
            raise _RetryableModelError("MODEL_REQUEST_FAILED") from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 409, 425, 429} or status_code >= 500:
                raise _RetryableModelError("MODEL_REQUEST_FAILED") from exc
            raise ModelError("MODEL_REQUEST_FAILED") from exc
        except httpx.HTTPError as exc:
            raise _RetryableModelError("MODEL_REQUEST_FAILED") from exc
        except ValueError as exc:
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
            input_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
            return ModelResult(
                content=content,
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                response_checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                cached_input_tokens=int(input_details.get("cached_tokens", 0)),
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelError("MODEL_RESPONSE_INVALID") from exc
