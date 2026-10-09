"""A v2 bot with explicit inference budgets and append-only local decision logs."""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol, TextIO

from ..bot import Decision, GameOver, GameStart
from .prompt import (CardCatalog, PROMPT_FORMATS, PUBLIC_HISTORY_SUFFIX, Prompt, PromptSizeError, canonical_json,
                     public_history_events, render_prompt, sha256, system_prompt)
from .provider import Completion, ProviderError


class Provider(Protocol):
    def complete(self, prompt: Prompt, *, timeout_s: float) -> Completion: ...


@dataclass(frozen=True)
class AgentConfig:
    max_calls_per_game: int = 256
    max_tokens_per_game: int = 250_000
    max_prompt_bytes: int = 64_000
    history_decisions: int = 8
    timeout_ms: int = 20_000
    deadline_margin_ms: int = 100
    record_prompts: bool = False
    prompt_format: str = "json-v1"
    # 0 leaves x_public_history_v1 unaccepted; otherwise the most recent events kept in each prompt.
    public_history_events: int = 0

    def __post_init__(self) -> None:
        if self.prompt_format not in PROMPT_FORMATS:
            raise ValueError("unsupported prompt format")
        for name in ("max_calls_per_game", "max_tokens_per_game", "max_prompt_bytes", "timeout_ms"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("history_decisions", "deadline_margin_ms", "public_history_events"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")


class LlmAgent:
    def __init__(
        self, provider: Provider, *, settings: dict[str, Any], max_completion_tokens: int,
        config: AgentConfig = AgentConfig(), catalog: CardCatalog | None = None,
        log: TextIO, monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.config = config
        self.catalog = catalog
        self.max_completion_tokens = max_completion_tokens
        self.log = log
        self._monotonic = monotonic
        self._game: GameStart | None = None
        self._calls = self._tokens = 0
        self._failed = False
        self._history: deque[dict[str, Any]] = deque(maxlen=config.history_decisions)
        self._public_events: deque[dict[str, Any]] = deque(maxlen=config.public_history_events or None)
        self._public_seen = 0
        self._public_step: int | None = None
        self._aliases: dict[str, str] = {}
        public = config.public_history_events > 0
        version = PROMPT_FORMATS[config.prompt_format] + (PUBLIC_HISTORY_SUFFIX if public else "")
        metadata = {"provider": settings, "agent": asdict(config), "prompt_version": version,
                    "system_prompt_sha256": sha256(system_prompt(config.prompt_format, public_history=public).encode("utf-8")),
                    "catalog_sha256": None if catalog is None else catalog.sha256}
        self._write("configuration", configuration_sha256=sha256(canonical_json(metadata).encode("utf-8")), **metadata)

    def _write(self, event: str, **fields: Any) -> None:
        self.log.write(canonical_json({"schema": "spellbench-llm-log/v1", "event": event, **fields}) + "\n")
        self.log.flush()

    def on_game_start(self, game: GameStart) -> None:
        self._game = game
        self._calls = self._tokens = 0
        self._failed = False
        self._history.clear()
        self._reset_public_history()
        self._write("game_start", game_id=game.game_id, seat=game.seat,
                    own_deck_sha256=sha256(canonical_json(game.own_deck).encode("utf-8")))

    def on_game_over(self, game: GameOver) -> None:
        self._write("game_over", game_id=game.game_id, calls=self._calls, tokens=self._tokens, terminal=game.terminal)
        self._game = None
        self._history.clear()
        self._reset_public_history()

    def _reset_public_history(self) -> None:
        self._aliases.clear()
        self._public_events.clear()
        self._public_seen = 0
        self._public_step = None

    def _observe_public_history(self, decision: Decision) -> dict[str, Any] | None:
        if not self.config.public_history_events:
            return None
        events = public_history_events(decision.extensions)
        # A retransmitted decision repeats its delta; a rewind carries none.
        if self._public_step is None or decision.seat_step is None or decision.seat_step > self._public_step:
            self._public_events.extend(events)
            self._public_seen += len(events)
            self._public_step = decision.seat_step
        return {"events": list(self._public_events), "omitted_earlier_events": self._public_seen - len(self._public_events)}

    def choose(self, decision: Decision) -> int:
        started = self._monotonic()
        if self._game is None or self._game.game_id != decision.game_id or self._game.seat != decision.acting_seat:
            raise ValueError("decision does not name the agent's active seat and game")
        fields: dict[str, Any] = {"game_id": decision.game_id, "seat_step": decision.seat_step}
        attempted = False
        known_usage = False
        try:
            if self._failed:
                raise ProviderError("game_already_failed")
            public_history = self._observe_public_history(decision)
            if len(decision.candidates) == 1:
                candidate_id = decision.candidates[0].candidate_id
                fields.update(status="forced", candidate_id=candidate_id)
            else:
                prompt = render_prompt(decision, own_deck=self._game.own_deck, history=self._history,
                                       catalog=self.catalog, max_bytes=self.config.max_prompt_bytes,
                                       prompt_format=self.config.prompt_format, public_history=public_history,
                                       aliases=self._aliases)
                fields.update(prompt_sha256=prompt.sha256, prompt_bytes=prompt.bytes)
                if self.config.record_prompts:
                    fields["messages"] = list(prompt.messages)
                if self._calls >= self.config.max_calls_per_game:
                    raise ProviderError("call_budget_exhausted")
                # UTF-8 byte count is a conservative input-token reservation for
                # standard byte-tokenized models, not provider billing evidence.
                if self._tokens + prompt.bytes + self.max_completion_tokens > self.config.max_tokens_per_game:
                    raise ProviderError("token_budget_exhausted")
                clock = decision.clock
                if any(type(clock.get(key)) is not int or clock[key] < 0 for key in ("remaining_ms", "max_decision_ms")):
                    raise ProviderError("invalid_clock")
                budget_ms = min(self.config.timeout_ms, clock["remaining_ms"], clock["max_decision_ms"])
                elapsed_ms = (self._monotonic() - started) * 1000
                timeout_s = (budget_ms - elapsed_ms - self.config.deadline_margin_ms) / 1000
                if timeout_s <= 0:
                    raise ProviderError("deadline_exhausted")
                self._calls += 1  # failures count too; never retry this request
                attempted = True
                completion = self.provider.complete(prompt, timeout_s=timeout_s)
                known_usage = True
                self._tokens += completion.prompt_tokens + completion.completion_tokens
                fields.update(returned_model=completion.model, response_id=completion.response_id,
                              system_fingerprint=completion.system_fingerprint,
                              prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens,
                              response_content_sha256=sha256(completion.content.encode("utf-8")))
                if completion.completion_tokens > self.max_completion_tokens:
                    raise ProviderError("output_token_limit_exceeded")
                if (self._monotonic() - started) * 1000 >= budget_ms:
                    raise ProviderError("timeout")
                if self._tokens > self.config.max_tokens_per_game:
                    raise ProviderError("token_budget_exceeded")
                candidate_id = parse_choice(completion.content, {item.candidate_id for item in decision.candidates})
                fields.update(status="chosen", candidate_id=candidate_id)
            chosen = next(item for item in decision.candidates if item.candidate_id == candidate_id)
            self._history.append({"seat_step": decision.seat_step, "turn": decision.observation.get("turn"),
                                  "phase_step": decision.observation.get("phase_step"), "choice": chosen.semantic})
            return candidate_id
        except (ValueError, ProviderError) as exc:
            self._failed = True
            fields.update(status="error", error=exc.code if isinstance(exc, ProviderError) else "invalid_observation_or_prompt",
                          unknown_usage=attempted and not known_usage)
            if isinstance(exc, PromptSizeError):
                fields.update(error="prompt_byte_cap_exceeded", prompt_bytes=exc.actual_bytes,
                              max_prompt_bytes=exc.maximum_bytes)
            raise
        finally:
            fields.update(elapsed_ms=max(0, round((self._monotonic() - started) * 1000)),
                          calls=self._calls, tokens=self._tokens)
            self._write("decision", **fields)


def parse_choice(content: str, offered: set[int]) -> int:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=unique_pairs)
    except (ValueError, TypeError):
        raise ProviderError("invalid_choice_json") from None
    if not isinstance(value, dict) or set(value) != {"candidate_id"} or type(value["candidate_id"]) is not int:
        raise ProviderError("invalid_choice_shape")
    if value["candidate_id"] not in offered:
        raise ProviderError("unoffered_candidate")
    return value["candidate_id"]
