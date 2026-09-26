"""A conformant agent-role stdio server (spec section 10).

``serve`` wraps user handler callables — ``on_game_start``,
``choose(decision) -> candidate_id``, ``on_game_over`` — as an agent-role
process speaking strict NDJSON on stdin/stdout. The server owns all protocol
state: the idempotent-retry cache (single entry, spec section 4.1), the
one-game-at-a-time rule, the pending-decision rule, and the closed error-code
set for the agent role.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from . import wire
from .errors import MalformedJsonError, ValidationError
from .models import (
    PROTOCOL,
    Ack,
    AgentHelloOk,
    BotIdentity,
    Choice,
    ChooseRequest,
    Decision,
    ErrorResponse,
    GameOverRequest,
    GameStartRequest,
    Selection,
)

HandlerChoose = Callable[[Decision], int]


class _Session:
    def __init__(
        self,
        *,
        on_game_start: Callable[[GameStartRequest], None],
        choose: HandlerChoose,
        on_game_over: Callable[[GameOverRequest], None],
        bot: BotIdentity,
        extensions_accepted: tuple[str, ...],
    ) -> None:
        self._on_game_start = on_game_start
        self._choose = choose
        self._on_game_over = on_game_over
        self._bot = bot
        self._extensions_accepted = extensions_accepted
        self._game_id: str | None = None
        self._pending: Decision | None = None
        self._last: tuple[str, bytes, bytes] | None = None

    def handle_line(self, line: bytes) -> bytes:
        """Process one request line; returns the response line to emit."""
        try:
            value = wire.strict_json_loads(line)
        except MalformedJsonError as exc:
            return self._error("", "malformed_json", str(exc))
        request_id = value.get("request_id")
        if type(request_id) is not str or not request_id:
            return self._error("", "malformed_request", "request_id must be a nonempty string")
        protocol = value.get("protocol")
        if type(protocol) is not str:
            return self._error(request_id, "malformed_request", "protocol must be a string")
        if protocol != PROTOCOL:
            return self._error(request_id, "protocol_mismatch", f'protocol must be "{PROTOCOL}"')
        if self._last is not None and self._last[0] == request_id:
            last_id, last_request, last_response = self._last
            if last_request == line:
                return last_response
            return self._error(request_id, "request_id_reuse_mismatch", "request_id reused with a different payload")
        response = self._dispatch(request_id, value)
        self._last = (request_id, line, response)
        return response

    def _dispatch(self, request_id: str, value: dict[str, Any]) -> bytes:
        request_type = value.get("request_type")
        if type(request_type) is not str:
            return self._error(request_id, "malformed_request", "request_type must be a string")
        if request_type == "hello":
            return self._hello(request_id, value)
        if request_type == "game_start":
            return self._game_start(request_id, value)
        if request_type == "choose":
            return self._choose_request(request_id, value)
        if request_type == "game_over":
            return self._game_over(request_id, value)
        return self._error(request_id, "malformed_request", f"unknown request_type: {request_type!r}")

    def _hello(self, request_id: str, value: dict[str, Any]) -> bytes:
        if set(value) != {"request_type", "protocol", "request_id"}:
            return self._error(request_id, "malformed_request", "hello carries exactly request_type/protocol/request_id")
        if self._pending is not None:
            return self._error(request_id, "decision_pending", "a decision is pending")
        return self._respond(
            AgentHelloOk(
                request_id=request_id,
                bot=self._bot,
                extensions_accepted=self._extensions_accepted,
            ).to_json()
        )

    def _game_start(self, request_id: str, value: dict[str, Any]) -> bytes:
        if self._pending is not None:
            return self._error(request_id, "decision_pending", "a decision is pending")
        if self._game_id is not None:
            return self._error(request_id, "game_already_active", "a game is already active on this agent")
        try:
            request = GameStartRequest.from_json(value)
        except ValidationError as exc:
            return self._error(request_id, "malformed_request", str(exc))
        try:
            self._on_game_start(request)
        except Exception as exc:
            return self._error(request_id, "internal_error", f"on_game_start failed: {type(exc).__name__}")
        self._game_id = request.game_id
        return self._respond(Ack(request_id=request_id).to_json())

    def _choose_request(self, request_id: str, value: dict[str, Any]) -> bytes:
        if self._game_id is None:
            return self._error(request_id, "unknown_game", "no active game")
        if self._pending is not None:
            return self._error(request_id, "decision_pending", "a decision is pending")
        try:
            request = ChooseRequest.from_json(value)
        except ValidationError as exc:
            return self._error(request_id, "malformed_request", str(exc))
        if request.game_id != self._game_id:
            return self._error(request_id, "unknown_game", f"unknown game_id: {request.game_id!r}")
        self._pending = request.decision
        try:
            candidate_id = self._choose(request.decision)
        except Exception as exc:
            return self._error(request_id, "internal_error", f"choose failed: {type(exc).__name__}")
        if type(candidate_id) is not int or not 0 <= candidate_id < len(request.decision.candidates):
            return self._error(
                request_id,
                "internal_error",
                "handler returned a candidate_id outside the offered list",
            )
        selection = Selection(
            candidate_id=candidate_id,
            semantic_echo=dict(request.decision.candidates[candidate_id].semantic),
        )
        self._pending = None
        return self._respond(Choice(request_id=request_id, selection=selection).to_json())

    def _game_over(self, request_id: str, value: dict[str, Any]) -> bytes:
        if self._game_id is None:
            return self._error(request_id, "unknown_game", "no active game")
        if self._pending is not None:
            return self._error(request_id, "decision_pending", "a decision is pending")
        try:
            request = GameOverRequest.from_json(value)
        except ValidationError as exc:
            return self._error(request_id, "malformed_request", str(exc))
        if request.game_id != self._game_id:
            return self._error(request_id, "unknown_game", f"unknown game_id: {request.game_id!r}")
        try:
            self._on_game_over(request)
        except Exception as exc:
            return self._error(request_id, "internal_error", f"on_game_over failed: {type(exc).__name__}")
        self._game_id = None
        return self._respond(Ack(request_id=request_id).to_json())

    def _respond(self, message: dict[str, Any]) -> bytes:
        return wire.canonical_json_line(message)

    def _error(self, request_id: str, code: str, message: str) -> bytes:
        return _error_line(request_id, code, message)


def serve(
    handler: Any = None,
    *,
    on_game_start: Callable[[GameStartRequest], None] | None = None,
    choose: HandlerChoose | None = None,
    on_game_over: Callable[[GameOverRequest], None] | None = None,
    bot_name: str = "spellbench-agent",
    bot_version: str | None = None,
    extensions_accepted: tuple[str, ...] = (),
    stdin: Any = None,
    stdout: Any = None,
) -> int:
    """Serve the agent role on stdin/stdout until EOF; returns the exit code.

    ``handler`` may be an object with ``choose(decision) -> int`` and optional
    ``on_game_start``/``on_game_over`` methods, a bare ``choose`` callable, or
    omitted entirely when the keyword callables are given.
    """
    if handler is not None:
        if callable(handler) and not hasattr(handler, "choose"):
            if choose is not None:
                raise ValueError("choose given twice")
            choose = handler
        else:
            if choose is None:
                choose = getattr(handler, "choose", None)
            if on_game_start is None:
                on_game_start = getattr(handler, "on_game_start", None)
            if on_game_over is None:
                on_game_over = getattr(handler, "on_game_over", None)
    if choose is None:
        raise ValueError("a choose(decision) -> candidate_id callable is required")
    session = _Session(
        on_game_start=on_game_start if on_game_start is not None else lambda request: None,
        choose=choose,
        on_game_over=on_game_over if on_game_over is not None else lambda request: None,
        bot=BotIdentity(name=bot_name, version=bot_version if bot_version is not None else _bot_version()),
        extensions_accepted=extensions_accepted,
    )
    in_stream = stdin if stdin is not None else sys.stdin.buffer
    out_stream = stdout if stdout is not None else sys.stdout.buffer
    while True:
        try:
            line = wire.read_line(in_stream)
        except MalformedJsonError as exc:
            out_stream.write(_error_line("", "malformed_json", str(exc)))
            out_stream.flush()
            continue
        if line is None:
            return 0
        response = session.handle_line(line)
        out_stream.write(response)
        out_stream.flush()


def _error_line(request_id: str, code: str, message: str) -> bytes:
    sanitized = " ".join(message.split())[:240]
    return wire.canonical_json_line(
        ErrorResponse(request_id=request_id, code=code, message=sanitized).to_json()
    )


def _bot_version() -> str:
    from . import __version__

    return __version__


def main() -> int:
    """Run a minimal conformance bot that always picks candidate 0."""

    class FirstCandidate:
        def choose(self, decision: Decision) -> int:
            return 0

    return serve(FirstCandidate(), bot_name="first-candidate")


if __name__ == "__main__":
    sys.exit(main())
