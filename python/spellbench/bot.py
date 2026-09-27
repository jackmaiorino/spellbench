"""The reference agent-role server and the views bots read (spec 4.2 and 10).

A bot supplies ``choose(decision) -> candidate_id`` and, optionally,
``on_game_start(game)`` and ``on_game_over(game_over)``. ``serve`` runs it
over stdin and stdout; ``BotSession.handle_line`` answers one request line,
so a bot can also be driven in process.

Agents read leniently (spec 4.2): unknown fields are ignored everywhere, and
a view reads a missing or mistyped field as ``None`` or ``{}`` (each view
keeps the whole request as ``raw``). The server
checks only what it needs: the envelope (spec 4.1), the game a request names,
and the candidate ids. Hosts never pipeline or retransmit to agents (spec 2,
4.1), so each line is answered before the next is read, with no response
cache and no ``decision_pending``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from . import wire
from .errors import MalformedJsonError

PROTOCOL = "spellbench/v2"
# Error messages are human-facing only (spec 9.8, 10.5); keep them short.
_MAX_MESSAGE_CHARS = 240


@dataclass(frozen=True)
class Candidate:
    """One offered candidate (spec 7.1)."""

    candidate_id: int
    semantic: dict[str, Any]
    display_text: str | None


@dataclass(frozen=True)
class Decision:
    """A ``choose`` request as a bot reads it: the forwarded seat decision and the clock (spec 9.3, 10.3)."""

    game_id: str
    candidates: tuple[Candidate, ...]
    acting_seat: str | None
    seat_step: int | None
    observation: dict
    context: dict
    group: dict
    extensions: dict
    clock: dict
    raw: dict

    @classmethod
    def from_request(cls, request: Mapping[str, Any]) -> Decision:
        """Read a ``choose`` request.

        Raises ``ValueError`` when ``game_id`` is not a string or the candidates
        are unusable: not a nonempty list of objects with integer ``candidate_id``.
        """
        game_id = _game_id(request)
        decision = _object(request.get("decision"))
        candidates = decision.get("candidates")
        if not isinstance(candidates, (list, tuple)) or not candidates:
            raise ValueError("decision.candidates must be a nonempty list")
        views = []
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping) or type(candidate.get("candidate_id")) is not int:
                raise ValueError(f"decision.candidates[{index}] has no integer candidate_id")
            views.append(
                Candidate(
                    candidate_id=candidate["candidate_id"],
                    semantic=_object(candidate.get("semantic")),
                    display_text=_text(candidate.get("display_text")),
                )
            )
        return cls(
            game_id=game_id,
            candidates=tuple(views),
            acting_seat=_text(decision.get("acting_seat")),
            seat_step=_integer(decision.get("seat_step")),
            observation=_object(decision.get("observation")),
            context=_object(decision.get("context")),
            group=_object(decision.get("group")),
            extensions=_object(decision.get("extensions")),
            clock=_object(request.get("clock")),
            raw=dict(request),
        )


@dataclass(frozen=True)
class GameStart:
    """A ``game_start`` request as a bot reads it (spec 10.2); ``opponent_deck`` is ``None`` when hidden."""

    game_id: str
    seat: str | None
    format: str | None
    own_deck: dict | None
    opponent_deck: dict | None
    rules: dict
    engine: dict
    engine_profile: dict
    time_control: dict
    limits: dict
    resources: dict
    agent_seed: int | None
    raw: dict

    @classmethod
    def from_request(cls, request: Mapping[str, Any]) -> GameStart:
        """Read a ``game_start`` request; raises ``ValueError`` when ``game_id`` is not a string."""
        return cls(
            game_id=_game_id(request),
            seat=_text(request.get("seat")),
            format=_text(request.get("format")),
            own_deck=_object_or_none(request.get("own_deck")),
            opponent_deck=_object_or_none(request.get("opponent_deck")),
            rules=_object(request.get("rules")),
            engine=_object(request.get("engine")),
            engine_profile=_object(request.get("engine_profile")),
            time_control=_object(request.get("time_control")),
            limits=_object(request.get("limits")),
            resources=_object(request.get("resources")),
            agent_seed=_integer(request.get("agent_seed")),
            raw=dict(request),
        )


@dataclass(frozen=True)
class GameOver:
    """A ``game_over`` request as a bot reads it (spec 10.4)."""

    game_id: str
    terminal: dict
    raw: dict

    @classmethod
    def from_request(cls, request: Mapping[str, Any]) -> GameOver:
        """Read a ``game_over`` request; raises ``ValueError`` when ``game_id`` is not a string."""
        return cls(game_id=_game_id(request), terminal=_object(request.get("terminal")), raw=dict(request))


class BotSession:
    """The agent role of one bot process: one answer line per request line (spec 10)."""

    def __init__(
        self,
        *,
        choose: Callable[[Decision], int],
        on_game_start: Callable[[GameStart], None] | None = None,
        on_game_over: Callable[[GameOver], None] | None = None,
        name: str,
        version: str,
        requires_observation: Sequence[str] = (),
        requires_extensions: Sequence[str] = (),
        extensions_accepted: Sequence[str] = (),
    ) -> None:
        for label, value in (("name", name), ("version", version)):
            if type(value) is not str or not value:
                raise ValueError(f"the bot {label} must be a nonempty string (spec 10.1)")
        self._choose = choose
        self._on_game_start = on_game_start
        self._on_game_over = on_game_over
        self._hello_fields = {
            "bot": {"name": name, "version": version},
            "requires": {
                "observation": _names(requires_observation, "requires_observation"),
                "extensions": _names(requires_extensions, "requires_extensions"),
            },
            "extensions_accepted": _names(extensions_accepted, "extensions_accepted"),
        }
        self._game_id: str | None = None

    def handle_line(self, line: bytes) -> bytes:
        """Answer one request line (its terminator optional) with one canonical response line."""
        try:
            value = wire.strict_json_loads(line)
        except MalformedJsonError as exc:
            return _error("", "malformed_json", str(exc))
        request_id = value.get("request_id")
        if type(request_id) is not str or not request_id:
            return _error("", "malformed_request", "request_id must be a nonempty string")
        protocol = value.get("protocol")
        if type(protocol) is not str:
            return _error(request_id, "malformed_request", "protocol must be a string")
        if protocol != PROTOCOL:
            return _error(request_id, "protocol_mismatch", f'protocol must be "{PROTOCOL}"')
        request_type = value.get("request_type")
        if type(request_type) is not str:  # a list or an object cannot even be looked up
            return _error(request_id, "malformed_request", "request_type must be a string")
        answer = {
            "hello": self._answer_hello,
            "game_start": self._answer_game_start,
            "choose": self._answer_choose,
            "game_over": self._answer_game_over,
        }.get(request_type)
        if answer is None:
            return _error(request_id, "malformed_request", "unknown request_type")
        return answer(request_id, value)

    def _answer_hello(self, request_id: str, value: dict[str, Any]) -> bytes:
        return _response("hello_ok", request_id, **self._hello_fields)

    def _answer_game_start(self, request_id: str, value: dict[str, Any]) -> bytes:
        if self._game_id is not None:
            return _error(request_id, "game_already_active", "a game is already active")
        try:
            game = GameStart.from_request(value)
        except ValueError as exc:
            return _error(request_id, "malformed_request", str(exc))
        if self._on_game_start is not None:
            try:
                self._on_game_start(game)
            except Exception as exc:
                # The game did not start, so a later game_start is still welcome.
                return _error(request_id, "internal_error", f"on_game_start failed: {type(exc).__name__}")
        self._game_id = game.game_id
        return _response("ack", request_id)

    def _answer_choose(self, request_id: str, value: dict[str, Any]) -> bytes:
        refusal = self._refuse_unless_active(request_id, value)
        if refusal is not None:
            return refusal
        try:
            decision = Decision.from_request(value)
        except ValueError as exc:
            return _error(request_id, "malformed_request", str(exc))
        try:
            candidate_id = self._choose(decision)
        except Exception as exc:
            return _error(request_id, "internal_error", f"choose failed: {type(exc).__name__}")
        if type(candidate_id) is not int:
            returned = type(candidate_id).__name__
            return _error(request_id, "internal_error", f"choose must return an int candidate_id, not {returned}")
        if all(candidate.candidate_id != candidate_id for candidate in decision.candidates):
            return _error(request_id, "internal_error", "choose returned a candidate_id that was not offered")
        return _response("choice", request_id, selection={"candidate_id": candidate_id})

    def _answer_game_over(self, request_id: str, value: dict[str, Any]) -> bytes:
        refusal = self._refuse_unless_active(request_id, value)
        if refusal is not None:
            return refusal
        game_over = GameOver.from_request(value)
        self._game_id = None  # the game is over even if the hook fails
        if self._on_game_over is not None:
            try:
                self._on_game_over(game_over)
            except Exception as exc:
                return _error(request_id, "internal_error", f"on_game_over failed: {type(exc).__name__}")
        return _response("ack", request_id)

    def _refuse_unless_active(self, request_id: str, value: dict[str, Any]) -> bytes | None:
        """The error for a request that does not name the active game (spec 10.5), else ``None``."""
        game_id = value.get("game_id")
        if type(game_id) is not str:
            return _error(request_id, "malformed_request", "game_id must be a string")
        if game_id != self._game_id:
            return _error(request_id, "unknown_game", "game_id names no active game")
        return None


def serve(
    handler: Any = None,
    *,
    choose: Callable[[Decision], int] | None = None,
    on_game_start: Callable[[GameStart], None] | None = None,
    on_game_over: Callable[[GameOver], None] | None = None,
    name: str = "spellbench-bot",
    version: str = "0.0.0",
    requires_observation: Sequence[str] = (),
    requires_extensions: Sequence[str] = (),
    extensions_accepted: Sequence[str] = (),
    stdin: Any = None,
    stdout: Any = None,
) -> int:
    """Serve the agent role on binary stdin and stdout until EOF; returns the exit code 0.

    ``handler`` is an object with ``choose`` and, optionally, ``on_game_start``
    and ``on_game_over`` (keyword callables take precedence over its methods),
    or a bare ``choose`` callable. Requests are read as bytes, never decoded
    with the locale's code page, and ``\\r\\n`` is tolerated (spec 2).
    """
    if handler is not None:
        if callable(handler) and not hasattr(handler, "choose"):
            if choose is not None:
                raise ValueError("choose given twice")
            choose = handler
        else:
            choose = choose if choose is not None else getattr(handler, "choose", None)
            on_game_start = on_game_start if on_game_start is not None else getattr(handler, "on_game_start", None)
            on_game_over = on_game_over if on_game_over is not None else getattr(handler, "on_game_over", None)
    if choose is None:
        raise ValueError("serve needs a choose(decision) -> candidate_id callable")
    session = BotSession(
        choose=choose,
        on_game_start=on_game_start,
        on_game_over=on_game_over,
        name=name,
        version=version,
        requires_observation=requires_observation,
        requires_extensions=requires_extensions,
        extensions_accepted=extensions_accepted,
    )
    in_stream = sys.stdin.buffer if stdin is None else stdin
    out_stream = sys.stdout.buffer if stdout is None else stdout
    while True:
        try:
            line = wire.read_line(in_stream)
        except MalformedJsonError as exc:  # framing: a line over 8 MiB, or no terminator before EOF
            answer = _error("", "malformed_json", str(exc))
        else:
            if line is None:
                return 0
            answer = session.handle_line(line)
        out_stream.write(answer)
        out_stream.flush()


def _game_id(request: Mapping[str, Any]) -> str:
    game_id = request.get("game_id")
    if type(game_id) is not str:
        raise ValueError("game_id must be a string")
    return game_id


def _object(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _object_or_none(value: Any) -> dict | None:
    return dict(value) if isinstance(value, Mapping) else None


def _text(value: Any) -> str | None:
    return value if type(value) is str else None


def _integer(value: Any) -> int | None:
    return value if type(value) is int else None


def _names(values: Sequence[str], label: str) -> list[str]:
    names = None if isinstance(values, str) else list(values)
    if names is None or not all(type(name) is str for name in names):
        raise ValueError(f"{label} must be a sequence of strings")
    return names


def _response(response_type: str, request_id: str, **fields: Any) -> bytes:
    message = {"response_type": response_type, "protocol": PROTOCOL, "request_id": request_id, **fields}
    return wire.canonical_json_line(message)


def _error(request_id: str, code: str, message: str) -> bytes:
    # A parser message may quote the request (a duplicate key, say); a lone surrogate in it cannot be UTF-8.
    text = " ".join(message.encode("utf-8", "backslashreplace").decode("utf-8").split())
    return _response("error", request_id, error={"code": code, "message": text[:_MAX_MESSAGE_CHARS]})
