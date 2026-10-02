"""One bounded Chat Completions request, with no SDK retries or redirects."""

from __future__ import annotations

import json
import math
import queue
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .prompt import Prompt, canonical_json


class ProviderError(RuntimeError):
    """A stable failure code; provider bodies and secrets never enter diagnostics."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Completion:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    response_id: str | None = None
    system_fingerprint: str | None = None


@dataclass(frozen=True)
class ProviderConfig:
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = field(default=None, repr=False)
    max_completion_tokens: int = 1024
    temperature: float | None = None
    reasoning_effort: str | None = None
    response_format: str = "json_schema"

    def __post_init__(self) -> None:
        url = urllib.parse.urlsplit(self.base_url)
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("base URL requires a host and cannot contain credentials, query or fragment")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("base URL requires HTTPS except for a loopback server")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("an explicit model is required")
        if type(self.max_completion_tokens) is not int or self.max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be a positive integer")
        if self.temperature is not None and (not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2):
            raise ValueError("temperature must be finite and between 0 and 2")
        if self.reasoning_effort not in {None, "minimal", "low", "medium", "high"}:
            raise ValueError("unsupported reasoning effort")
        if self.response_format not in {"json_schema", "json_object"}:
            raise ValueError("response_format must be json_schema or json_object")

    def public_settings(self) -> dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url, "max_completion_tokens": self.max_completion_tokens,
                "temperature": self.temperature, "reasoning_effort": self.reasoning_effort,
                "response_format": self.response_format}


def request_body(config: ProviderConfig, prompt: Prompt) -> dict[str, Any]:
    # A plain integer schema also handles the protocol's 4096-candidate cap,
    # above the provider's enum limit. Offered-ID membership is checked locally.
    response_format: dict[str, Any] = {"type": config.response_format}
    if config.response_format == "json_schema":
        response_format["json_schema"] = {
            "name": "spellbench_choice", "strict": True,
            "schema": {"type": "object", "properties": {"candidate_id": {"type": "integer"}},
                       "required": ["candidate_id"], "additionalProperties": False},
        }
    body: dict[str, Any] = {"model": config.model, "messages": list(prompt.messages),
                            "max_completion_tokens": config.max_completion_tokens, "response_format": response_format}
    if config.temperature is not None:
        body["temperature"] = config.temperature
    if config.reasoning_effort is not None:
        body["reasoning_effort"] = config.reasoning_effort
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise ProviderError("redirect_rejected")


class ChatCompletionsProvider:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def complete(self, prompt: Prompt, *, timeout_s: float) -> Completion:
        # Socket timeouts alone are not a total deadline when a server dribbles
        # bytes. Bound the whole exchange as well. A timeout poisons the agent's
        # game, so it never starts another request with unknown usage.
        return _bounded(lambda: self._exchange(prompt, timeout_s), timeout_s)

    def _exchange(self, prompt: Prompt, timeout_s: float) -> Completion:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        request = urllib.request.Request(self.config.base_url.rstrip("/") + "/chat/completions",
                                         canonical_json(request_body(self.config, prompt)).encode("utf-8"), headers)
        try:
            with self._opener.open(request, timeout=timeout_s) as response:
                raw = response.read(1_048_577)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise ProviderError(f"http_{status}") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("timeout") from None
        except urllib.error.URLError:
            raise ProviderError("transport_error") from None
        if len(raw) > 1_048_576:
            raise ProviderError("response_too_large")
        try:
            value = json.loads(raw)
            choice = value["choices"][0]
            message = choice["message"]
            if message.get("refusal"):
                raise ProviderError("refusal")
            if choice.get("finish_reason") != "stop":
                raise ProviderError("incomplete_response")
            content = message["content"]
            model = value["model"]
            usage = value["usage"]
            inputs, outputs = usage["prompt_tokens"], usage["completion_tokens"]
            if not isinstance(content, str) or not isinstance(model, str) or not model:
                raise ValueError
            if any(type(count) is not int or count < 0 for count in (inputs, outputs)):
                raise ValueError
            return Completion(content, model, inputs, outputs,
                              value.get("id") if isinstance(value.get("id"), str) else None,
                              value.get("system_fingerprint") if isinstance(value.get("system_fingerprint"), str) else None)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError("invalid_response_or_usage") from None


def _bounded(call: Callable[[], Completion], timeout_s: float) -> Completion:
    if timeout_s <= 0:
        raise ProviderError("timeout")
    replies: queue.Queue[Completion | Exception] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            replies.put(call())
        except Exception as exc:
            replies.put(exc)

    threading.Thread(target=worker, daemon=True, name="spellbench-llm-http").start()
    try:
        reply = replies.get(timeout=timeout_s)
    except queue.Empty:
        raise ProviderError("timeout") from None
    if isinstance(reply, ProviderError):
        raise reply
    if isinstance(reply, Exception):
        raise ProviderError("transport_error") from None
    return reply
