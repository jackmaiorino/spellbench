"""ChatGPT-plan Responses inference, using an explicitly authorized OAuth token."""

from __future__ import annotations

import json
import math
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .prompt import Prompt, canonical_json
from .provider import Completion, ProviderError, _bounded
from .tls import native_opener

BASE_URL = "https://api.openai.com/v1"
MAX_RESPONSE_BYTES = 1_048_576


@dataclass(frozen=True)
class ChatGptConfig:
    model: str
    access_token: str = field(repr=False)
    reasoning_effort: str = "low"
    expires_at: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("an explicit model is required")
        if not isinstance(self.access_token, str) or not self.access_token.strip():
            raise ValueError("a ChatGPT-plan OAuth access token is required")
        if self.reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported reasoning effort")
        if self.expires_at is not None and (type(self.expires_at) not in {int, float} or not math.isfinite(self.expires_at)):
            raise ValueError("invalid credential expiry")

    def public_settings(self) -> dict[str, Any]:
        return {"transport": "chatgpt-plan", "model": self.model, "base_url": BASE_URL,
                "reasoning_effort": self.reasoning_effort, "response_format": "json_schema",
                "output_token_limit": "checked_after_response", "retries": 0, "certificate_validation": "system-truststore"}


def request_body(config: ChatGptConfig, prompt: Prompt) -> dict[str, Any]:
    # This route rejects system-role input and max_output_tokens. Developer
    # messages preserve the existing prompt's instruction priority. No tools,
    # external context, persistent conversation or Codex configuration is sent.
    inputs = [{"role": "developer" if item["role"] == "system" else item["role"],
               "content": item["content"]} for item in prompt.messages]
    return {"model": config.model, "input": inputs, "store": False, "stream": True,
            "reasoning": {"effort": config.reasoning_effort},
            "text": {"format": {"type": "json_schema", "name": "spellbench_choice", "strict": True,
                                "schema": {"type": "object", "properties": {"candidate_id": {"type": "integer"}},
                                           "required": ["candidate_id"], "additionalProperties": False}}}}


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _completion(response: dict[str, Any]) -> Completion:
    try:
        if response["status"] != "completed":
            raise ProviderError("incomplete_response")
        content: list[str] = []
        for item in response["output"]:
            if item["type"] == "reasoning":
                continue
            if item["type"] != "message" or item["role"] != "assistant" or item["status"] != "completed":
                raise ProviderError("unexpected_response_item")
            for part in item["content"]:
                if part["type"] == "refusal":
                    raise ProviderError("refusal")
                if part["type"] != "output_text" or not isinstance(part["text"], str):
                    raise ProviderError("unexpected_response_content")
                content.append(part["text"])
        model, response_id = response["model"], response["id"]
        inputs, outputs = response["usage"]["input_tokens"], response["usage"]["output_tokens"]
        if not content or not isinstance(model, str) or not model or not isinstance(response_id, str) or not response_id:
            raise ValueError
        if any(type(count) is not int or count < 0 for count in (inputs, outputs)):
            raise ValueError
        return Completion("".join(content), model, inputs, outputs, response_id)
    except (KeyError, ValueError, TypeError):
        raise ProviderError("invalid_response_or_usage") from None


def read_completion(stream: Any) -> Completion:
    """Consume SSE until its authoritative completed event, never use a delta."""
    total = 0
    data: list[bytes] = []
    while True:
        line = stream.readline(MAX_RESPONSE_BYTES - total + 1)
        total += len(line)
        if total > MAX_RESPONSE_BYTES:
            raise ProviderError("response_too_large")
        if not line:
            raise ProviderError("interrupted_stream")
        stripped = line.rstrip(b"\r\n")
        if stripped.startswith(b"data:"):
            data.append(stripped[5:].lstrip(b" "))
        elif not stripped and data:
            raw = b"\n".join(data)
            data.clear()
            try:
                event = json.loads(raw, object_pairs_hook=_unique)
                kind = event["type"]
                if kind == "response.completed":
                    return _completion(event["response"])
                if kind in {"response.failed", "response.incomplete", "error"}:
                    raise ProviderError("inference_failed" if kind != "response.incomplete" else "incomplete_response")
            except (KeyError, ValueError, TypeError):
                raise ProviderError("invalid_stream_event") from None


class ChatGptProvider:
    def __init__(self, config: ChatGptConfig) -> None:
        self.config = config
        self._endpoint = BASE_URL + "/responses"
        self._opener = native_opener()
        self._failed = False

    def complete(self, prompt: Prompt, *, timeout_s: float) -> Completion:
        if self._failed:
            raise ProviderError("provider_already_failed")
        if self.config.expires_at is not None and self.config.expires_at <= time.time() + max(0, timeout_s) + 60:
            raise ProviderError("credentials_expired")
        try:
            return _bounded(lambda: self._exchange(prompt, timeout_s), timeout_s)
        except ProviderError:
            self._failed = True
            raise

    def _exchange(self, prompt: Prompt, timeout_s: float) -> Completion:
        request = urllib.request.Request(self._endpoint, canonical_json(request_body(self.config, prompt)).encode("utf-8"),
                                         {"Content-Type": "application/json", "Accept": "text/event-stream",
                                          "Authorization": "Bearer " + self.config.access_token})
        try:
            with self._opener.open(request, timeout=timeout_s) as response:
                if response.headers.get_content_type() != "text/event-stream":
                    raise ProviderError("invalid_stream_content_type")
                return read_completion(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise ProviderError(f"http_{status}") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("timeout") from None
        except urllib.error.URLError:
            raise ProviderError("transport_error") from None
