"""Inference RPC over a sandbox's existing stdio pipes, with host-owned policy.

The outer wire is still Spellbench v2. An isolated child may request one
completion while answering a choose request. This is not a network proxy:
the host owns the provider, model, endpoint, settings and budgets.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, TextIO

from .. import wire
from ..bot import Decision
from ..errors import MalformedJsonError, PeerTimeoutError, TransportError
from .agent import AgentConfig, Provider, parse_choice
from .prompt import Prompt, canonical_json, sha256
from .provider import Completion, ProviderError

RPC = "spellbench-inference/v1"


class StdioProvider:
    """The child-side capability. It never reads credentials or opens a socket."""

    def __init__(self, *, stdin: Any = None, stdout: Any = None) -> None:
        self.stdin = sys.stdin.buffer if stdin is None else stdin
        self.stdout = sys.stdout.buffer if stdout is None else stdout
        self._counter = 0

    def complete(self, prompt: Prompt, *, timeout_s: float) -> Completion:
        request_id = f"i-{self._counter}"
        self._counter += 1
        self.stdout.write(wire.canonical_json_line({"broker": RPC, "request_id": request_id,
                                                  "messages": list(prompt.messages),
                                                  "timeout_ms": max(1, int(timeout_s * 1000))}))
        self.stdout.flush()
        # The broker owns the deadline and the host bounds the entire exchange.
        # This read shares the bot's stdin: only the broker's answer is legal here.
        try:
            line = wire.read_line(self.stdin)
            if line is None:
                raise ProviderError("broker_eof")
            response = wire.strict_json_loads(line)
            if response.get("broker") != RPC or response.get("request_id") != request_id:
                raise ProviderError("broker_response_mismatch")
            if "error" in response:
                raise ProviderError("broker_error")
            value = response["completion"]
            content, model = value["content"], value["model"]
            counts = value["prompt_tokens"], value["completion_tokens"]
            if not isinstance(content, str) or not isinstance(model, str) or not model:
                raise ValueError
            if any(type(count) is not int or count < 0 for count in counts):
                raise ValueError
            return Completion(content, model, *counts, value.get("response_id"), value.get("system_fingerprint"))
        except (MalformedJsonError, KeyError, ValueError, TypeError):
            raise ProviderError("invalid_broker_response") from None


@dataclass(frozen=True)
class BrokerLimits:
    max_calls_total: int = 1024
    max_tokens_total: int = 1_000_000
    startup_ms: int = 120_000

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise ValueError("broker limits must be positive integers")


class BrokerSession:
    """One host/child connection. ``peer`` is supplied by the isolation owner.

    The library does not grant sandbox admission or launch arbitrary host code.
    A transport or uncertain-usage failure poisons the connection, not just the
    current game, so a child cannot reset a failed budget by changing game IDs.
    """

    def __init__(self, peer: Any, provider: Provider, *, settings: dict[str, Any], max_completion_tokens: int,
                 log: TextIO, config: AgentConfig = AgentConfig(), limits: BrokerLimits = BrokerLimits(),
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.peer, self.provider, self.log = peer, provider, log
        self.config, self.limits = config, limits
        if type(max_completion_tokens) is not int or max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be a positive integer")
        self.max_completion_tokens = max_completion_tokens
        self.now = monotonic
        self._game: str | None = None
        self._calls = self._tokens = self._game_calls = self._game_tokens = 0
        self._failed = False
        self._log("configuration", provider=settings, agent=asdict(config), limits=asdict(limits))

    def _log(self, event: str, **fields: Any) -> None:
        self.log.write(canonical_json({"schema": "spellbench-llm-broker-log/v1", "event": event, **fields}) + "\n")
        self.log.flush()

    def _budget(self, deadline: float) -> None:
        remaining = deadline - self.now()
        if remaining <= 0:
            raise ProviderError("timeout")
        self.peer.set_timeout(remaining)

    def _complete(self, request: dict[str, Any], decision: Decision, deadline: float) -> dict[str, Any]:
        if set(request) != {"broker", "request_id", "messages", "timeout_ms"}:
            raise ProviderError("invalid_inference_request")
        if request["broker"] != RPC or not isinstance(request["request_id"], str) or not request["request_id"]:
            raise ProviderError("invalid_inference_request")
        messages = request["messages"]
        if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
            raise ProviderError("invalid_messages")
        if any(not isinstance(item, dict) or set(item) != {"role", "content"}
               or not isinstance(item["role"], str) or item["role"] not in {"system", "user", "assistant"}
               or not isinstance(item["content"], str) for item in messages):
            raise ProviderError("invalid_messages")
        if type(request["timeout_ms"]) is not int or request["timeout_ms"] < 1:
            raise ProviderError("invalid_inference_request")
        encoded = canonical_json(messages).encode("utf-8")
        if len(encoded) > self.config.max_prompt_bytes:
            raise ProviderError("prompt_too_large")
        prompt = Prompt(tuple(messages), sha256(encoded), len(encoded))
        reservation = prompt.bytes + self.max_completion_tokens
        if self._calls >= self.limits.max_calls_total or self._game_calls >= self.config.max_calls_per_game:
            raise ProviderError("call_budget_exhausted")
        if (self._tokens + reservation > self.limits.max_tokens_total
                or self._game_tokens + reservation > self.config.max_tokens_per_game):
            raise ProviderError("token_budget_exhausted")
        timeout_s = min(request["timeout_ms"] / 1000, deadline - self.now())
        if timeout_s <= 0:
            raise ProviderError("timeout")
        self._calls += 1
        self._game_calls += 1
        started = self.now()
        fields: dict[str, Any] = {"game_id": decision.game_id, "seat_step": decision.seat_step,
                                  "prompt_sha256": prompt.sha256, "prompt_bytes": prompt.bytes, "unknown_usage": True}
        if self.config.record_prompts:
            fields["messages"] = messages
        try:
            try:
                result = self.provider.complete(prompt, timeout_s=timeout_s)
            except ProviderError:
                raise
            except Exception:
                raise ProviderError("provider_internal_error") from None
            if (not isinstance(result, Completion) or not isinstance(result.content, str)
                    or not isinstance(result.model, str) or not result.model
                    or any(type(count) is not int or count < 0
                           for count in (result.prompt_tokens, result.completion_tokens))
                    or any(value is not None and not isinstance(value, str)
                           for value in (result.response_id, result.system_fingerprint))):
                raise ProviderError("invalid_provider_result")
            self._tokens += result.prompt_tokens + result.completion_tokens
            self._game_tokens += result.prompt_tokens + result.completion_tokens
            fields.update(unknown_usage=False, returned_model=result.model, prompt_tokens=result.prompt_tokens,
                          completion_tokens=result.completion_tokens, response_id=result.response_id,
                          system_fingerprint=result.system_fingerprint)
            if self._tokens > self.limits.max_tokens_total or self._game_tokens > self.config.max_tokens_per_game:
                raise ProviderError("token_budget_exceeded")
            if self.now() >= deadline:
                raise ProviderError("timeout")
            candidate_id = parse_choice(result.content, {item.candidate_id for item in decision.candidates})
            fields.update(status="chosen", candidate_id=candidate_id)
            return {"broker": RPC, "request_id": request["request_id"], "completion": asdict(result)}
        except ProviderError as exc:
            fields.update(status="error", error=exc.code)
            raise
        finally:
            fields.update(calls=self._calls, tokens=self._tokens, elapsed_ms=max(0, round((self.now() - started) * 1000)))
            self._log("inference", **fields)

    def exchange(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("request_id", "")
        try:
            if self._failed:
                raise ProviderError("broker_already_failed")
            if request.get("protocol") != "spellbench/v2" or not isinstance(request_id, str) or not request_id:
                raise ProviderError("invalid_host_envelope")
            kind = request.get("request_type")
            decision: Decision | None = None
            budget_ms = self.limits.startup_ms
            if kind == "choose":
                decision = Decision.from_request(request)
                if decision.game_id != self._game:
                    raise ProviderError("unknown_game")
                clock = decision.clock
                if any(type(clock.get(key)) is not int or clock[key] < 0 for key in ("remaining_ms", "max_decision_ms")):
                    raise ProviderError("invalid_clock")
                budget_ms = min(self.config.timeout_ms, clock["remaining_ms"], clock["max_decision_ms"])
            elif kind not in {"hello", "game_start", "game_over"}:
                raise ProviderError("invalid_host_request")
            deadline = self.now() + max(0, budget_ms - self.config.deadline_margin_ms) / 1000
            self._budget(deadline)
            self.peer.write_line(wire.canonical_json_dumps(request))
            inferred = False
            while True:
                self._budget(deadline)
                response = wire.strict_json_loads(self.peer.read_line())
                if "broker" not in response:
                    if response.get("protocol") != "spellbench/v2" or response.get("request_id") != request_id:
                        raise ProviderError("child_response_mismatch")
                    if kind == "game_start" and response.get("response_type") == "ack":
                        self._game = request.get("game_id")
                        self._game_calls = self._game_tokens = 0
                    if kind == "game_over" and response.get("response_type") == "ack":
                        self._game = None
                    return response
                if decision is None or inferred or len(decision.candidates) == 1:
                    raise ProviderError("inference_not_allowed")
                inferred = True
                result = self._complete(response, decision, deadline)
                self._budget(deadline)
                self.peer.write_line(wire.canonical_json_dumps(result))
        except (ProviderError, ValueError, MalformedJsonError, PeerTimeoutError, TransportError) as exc:
            self._failed = True
            code = exc.code if isinstance(exc, ProviderError) else "child_transport_or_protocol_error"
            self._log("error", request_id=request_id, error=code, calls=self._calls, tokens=self._tokens)
            return {"response_type": "error", "protocol": "spellbench/v2", "request_id": request_id,
                    "error": {"code": "internal_error", "message": "inference broker failed: " + code}}


def serve_broker(session: BrokerSession, *, stdin: Any = None, stdout: Any = None) -> int:
    incoming = sys.stdin.buffer if stdin is None else stdin
    outgoing = sys.stdout.buffer if stdout is None else stdout
    try:
        while True:
            line = wire.read_line(incoming)
            if line is None:
                return 0
            response = session.exchange(wire.strict_json_loads(line))
            outgoing.write(wire.canonical_json_line(response))
            outgoing.flush()
            if session._failed:
                return 1
    finally:
        session.peer.close()
