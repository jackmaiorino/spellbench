"""The engine conformance runner that engine adapters are held to (spec 4, 9, 11.4, 16).

``check_engine(argv, format=..., decks=..., games=4)`` runs every check of
:data:`CHECK_NAMES` against the engine command ``argv``, each in a fresh engine
process that it closes afterwards, and returns a :class:`ConformanceReport`, one
:class:`CheckResult` per check, which ``render()`` prints one line each. An
exception inside a check is that check's failure, never the runner's;
``KeyboardInterrupt`` still stops the run, once the check's engine is closed.

Timeouts: every request is bounded by ``timeout_s``, :data:`REQUEST_TIMEOUT_S`
(30 s) by default. A process has that long from its start to ``hello_ok``, and
again for each later answer (and each write), and the ``games`` check uses the
same bound for ``startup_ms`` and ``engine_step_ms`` (spec 11.4). A hung engine
fails the check it hangs in once the bound passes, and the runner moves on.

The protocol checks reset games of the first deck in both seats under the rules
a benchmark sends (spec 12.2, Decision 8): opponent decklist visible, ``london``
mulligan when the engine supports it, else ``none``, ``host_assigned`` with
``p0`` when supported, no extension, probe off, that deck's card names as the
domain, a fresh game secret, and both caps at 2000, so a game of first
candidates always ends (spec 9.2). Each check names the rule it holds:

- ``hello``: a strict ``hello_ok`` (spec 9.1) that offers the format and lists
  every deck in its catalog.
- ``protocol_mismatch``: a ``protocol`` other than ``spellbench/v2``, on the
  first request and on a later reset (spec 4.1).
- ``malformed_json``: lines that break strict JSON (spec 2): not JSON, a
  duplicate key, a fraction, an exponent, an integer beyond 2^53 - 1, nesting
  over 64 levels, invalid UTF-8, an unpaired surrogate escape, a line over
  8 MiB; each answered with ``request_id`` ``""`` (spec 4.1, 9.8), and the
  request after the long line answered as usual (spec 2: one answer per line).
- ``malformed_request``: an unknown field (also in ``reset.rules``, on a line of
  8 MiB minus 16 bytes, and at the nesting depth of 64 that strict JSON
  allows), an unknown ``request_type``, a missing or non-string ``protocol``, a
  missing field and a mistyped field, each answered with the request's id; a
  missing or non-string ``request_id``, answered with ``""`` (spec 4.1, 9.8).
- ``malformed_request_non_object``: the lines ``[1,2]``, ``"spellbench/v2"``,
  ``42`` and ``null``, valid JSON whose top level is not an object, answered
  ``malformed_request`` with ``request_id`` ``""`` (spec 9.8; R1-3).
- ``unsupported_rule``: a reset with ``rules.probe: true`` (unless the engine
  declares the probe), one enabling an extension ``hello_ok`` does not declare,
  and one for each vocabulary that has a value outside ``rules_supported``
  (spec 9.2; R3-10).
- ``game_id_reuse``: a reset reusing a finished game's ``game_id`` is
  ``malformed_request``, and a fresh id is still played (spec 9.2).
- ``never_cached``: a reset, then a step, that fails parsing, and the same
  ``request_id`` with a valid payload, answered as usual (spec 4.1).
- ``step_check_order``: steps with two faults get the earlier code of spec 9.4,
  before any reset, during a game (``game_id_mismatch`` before
  ``expected_step_mismatch``, R1-20, and that before
  ``candidate_id_out_of_range``) and after the terminal (``game_id_mismatch``
  before ``game_already_terminal``, and that before ``expected_step_mismatch``).
- ``step_before_reset``: a step (and ``probe_resample``, when the engine
  declares the probe) before any reset, and a step after a refused reset
  (spec 9.4, 9.8).
- ``unsupported_format``: a format ``hello_ok`` does not offer (spec 9.2).
- ``unsupported_deck``: the catalog id ``spellbench-conformance-no-such-deck``
  in either seat, and a decklist of a made-up card (spec 9.2).
- ``unsupported_request``: ``probe_resample`` during a game, answered
  ``probe_refused`` by an engine that declares the probe (spec 9.7).
- ``game_already_active``, ``game_id_mismatch``, ``expected_step_mismatch``
  (ahead and stale), ``candidate_id_out_of_range`` (the candidate count, and
  2^32 - 1), ``semantic_echo_mismatch``: the fault alone, after which the
  pending decision is still answered as usual (spec 9.2, 9.4).
- ``retransmission``: a reset and a step sent again byte for byte get the same
  answer, compared as parsed JSON, without side effects; the same ``request_id``
  with a changed payload is ``request_id_reuse_mismatch`` (spec 4.1).
- ``game_already_terminal``: a step after a first-candidate game's terminal
  (spec 9.4).
- ``games``: ``games`` full games of the builtin ``first`` against ``uniform``,
  seat-swapped, the decks in turn, through ``preflight``, ``schedule``,
  ``game_setup`` and ``play_game`` with a fresh run secret; a host halt
  (``host_validator:*`` or ``host_engine_fault:*``) or a forfeit fails it with
  the game's reason (spec 11.3, 11.5), while an engine's own ``halted``
  terminal is an ending like any other (spec 9.5).

``replay_engine_transcript(argv, path)`` replays a golden transcript's engine
rows (spec 16): each ``host_to_engine`` row goes to one engine process, a
string row (the offending line of a ``malformed_json`` or non-object golden,
Decision 7) as its UTF-8 bytes unchanged and any other row as canonical JSON
(R3-11), and each answer is compared with its ``engine_to_host`` row as parsed
JSON, since an engine's layout is its own (spec 4.3).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import digests, wire
from .arena.config import CONFIG_SCHEMA, DEFAULT_TIME_CONTROL, TournamentConfig, TournamentError
from .arena.drivers import BuiltinDriver
from .arena.schedule import EnginePin, GameContext, RunSetup, game_setup, preflight, schedule
from .builtins import BUILTIN_VERSIONS
from .errors import (
    EngineError,
    LineTooLongError,
    MalformedJsonError,
    PeerTimeoutError,
    ProtocolError,
    RemoteError,
    TransportError,
    ValidationError,
)
from .host.engine_process import EngineProcess
from .host.game import GameResult, play_game
from .messages import (
    ENGINE_ERROR_CODES,
    MULLIGAN_RULES,
    PROTOCOL,
    PROTOCOL_MINOR,
    STARTING_PLAYER_RULES,
    CardNameDomain,
    Decision,
    DeckRow,
    EnvHelloOk,
    ErrorResponse,
    HelloRequest,
    ResetRequest,
    Rules,
    Selection,
    StepRequest,
    Terminal,
    WireDeck,
)
from .run_secret import RunSecret

CHECK_NAMES = (
    "hello",
    "protocol_mismatch",
    "malformed_json",
    "malformed_request",
    "malformed_request_non_object",
    "unsupported_rule",
    "game_id_reuse",
    "never_cached",
    "step_check_order",
    "step_before_reset",
    "unsupported_format",
    "unsupported_deck",
    "unsupported_request",
    "game_already_active",
    "game_id_mismatch",
    "expected_step_mismatch",
    "candidate_id_out_of_range",
    "semantic_echo_mismatch",
    "retransmission",
    "game_already_terminal",
    "games",
)
# The bound on every request, and on process start to hello_ok (module docstring).
REQUEST_TIMEOUT_S = 30.0
# max_decisions and max_steps of every protocol reset: a first-candidate game ends by then (spec 9.2).
CONFORMANCE_CAP = 2000
NO_SUCH_DECK = "spellbench-conformance-no-such-deck"
NO_SUCH_FORMAT = "spellbench-conformance-no-such-format"
NO_SUCH_CARD = "Spellbench Conformance No Such Card"
UNDECLARED_EXTENSION = "x_spellbench_conformance_undeclared"
_UNKNOWN_FIELD = "spellbench_conformance_unknown"
_U32_MAX = (1 << 32) - 1
_MAX_TIMEOUT_S = 86400.0
_PASS = {"kind": "pass"}
# Reasons only the host records for a halt (spec 11.3, 11.5): the games check fails on these, not on an engine's halt.
_HOST_HALTS = ("host_validator:", "host_engine_fault:")
_MAX_DETAIL_CHARS = 1000
_QUOTE_CHARS = 120
_DIRECTIONS = ("host_to_engine", "engine_to_host", "host_to_agent", "agent_to_host")
_ABSENT = object()


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome; ``detail`` says what failed (or, for a pass, what was checked)."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ConformanceReport:
    """Every check's result, in :data:`CHECK_NAMES` order."""

    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        """True when there is a check and every check passed."""
        return bool(self.checks) and all(check.passed for check in self.checks)

    def render(self) -> str:
        """One line per check: ``PASS <name>``, or ``FAIL <name>: <detail>`` with the detail on one line."""
        return "\n".join(f"PASS {check.name}" if check.passed else f"FAIL {check.name}: {_one_line(check.detail)}"
                         for check in self.checks)


class _Failed(Exception):
    """A check's failure; its text is the check's detail."""


@dataclass(frozen=True)
class _Run:
    """What every check of one ``check_engine`` call shares."""

    argv: tuple[str, ...]
    format: str
    decks: tuple[str, ...]
    games: int
    timeout_s: float
    secret: RunSecret          # the game secrets and ids of the protocol resets (spec 11.6)


# ---------------------------------------------------------------------------
# Text for details: one line, bounded, quoting only what the engine sent
# ---------------------------------------------------------------------------


def _one_line(text: str) -> str:
    """``text`` on one line (whitespace runs become one space), cut to ``_MAX_DETAIL_CHARS``."""
    line = " ".join(text.split())
    return line if len(line) <= _MAX_DETAIL_CHARS else line[: _MAX_DETAIL_CHARS - 3] + "..."


def _clip(text: str, limit: int = _QUOTE_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _seconds(value: float) -> str:
    return f"{value:g}"


def _id(request_id: Any) -> str:
    """A request id as JSON text, so ``""`` shows and a non-string id shows as what it is."""
    return _clip(json.dumps(request_id))


def _error_text(code: str, request_id: Any) -> str:
    return f"error {code} with request_id {_id(request_id)}"


def _said(message: str) -> str:
    return f" ({_clip(message)!r})" if message else ""


def _json_text(value: Any) -> str:
    return wire.canonical_json_dumps(value).decode("utf-8")


def _describe(answer: Mapping[str, Any]) -> str:
    """What an answer is: an error with its code and id, another response with its type and id, or neither."""
    kind = answer.get("response_type")
    if kind == "error":
        try:
            error = ErrorResponse.from_json(answer, codes=ENGINE_ERROR_CODES)
        except ValidationError as exc:
            return f"an invalid error response ({exc})"
        return _error_text(error.code, error.request_id) + _said(error.message)
    if isinstance(kind, str):
        return f"a {_clip(kind, 40)} answer with request_id {_id(answer.get('request_id'))}"
    return f"an answer without a response_type: {_clip(_json_text(answer))}"


def _is_error(answer: Mapping[str, Any], code: str, request_id: str) -> bool:
    """``answer`` is a valid error envelope with this code, answering this ``request_id`` (spec 4.1, 9.8)."""
    try:
        error = ErrorResponse.from_json(answer, codes=ENGINE_ERROR_CODES)
    except ValidationError:
        return False
    return error.code == code and error.request_id == request_id


def _difference(expected: Any, actual: Any, path: str = "$") -> str:
    """The first JSON path where two parsed values differ, type-exact as canonical JSON compares them (spec 4.3)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            left, right = expected.get(key, _ABSENT), actual.get(key, _ABSENT)
            if left is _ABSENT or right is _ABSENT or _json_text(left) != _json_text(right):
                return _difference(left, right, f"{path}.{key}")
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        for index, (left, right) in enumerate(zip(expected, actual)):
            if _json_text(left) != _json_text(right):
                return _difference(left, right, f"{path}[{index}]")
    return f"{path}: expected {_shown(expected)}, got {_shown(actual)}"


def _shown(value: Any) -> str:
    return "(absent)" if value is _ABSENT else _clip(_json_text(value))


# ---------------------------------------------------------------------------
# Requests the checks send
# ---------------------------------------------------------------------------


def _hello(request_id: str) -> dict[str, Any]:
    return HelloRequest(request_id, PROTOCOL_MINOR).to_json()


def _hello_bytes(request_id: bytes, *, minor: bytes = b"0", tail: bytes = b"") -> bytes:
    """A hello line written byte by byte, keys in canonical order, holding what canonical JSON cannot."""
    return b'{"protocol":"%s","protocol_minor":%s,"request_id":"%s","request_type":"hello"%s}' % (
        PROTOCOL.encode("ascii"), minor, request_id, tail)


def _padded_hello(request_id: str, length: int) -> bytes:
    """A hello of exactly ``length`` bytes, padded by an unknown field (``malformed_request`` when it is read)."""
    unknown, encoded = _UNKNOWN_FIELD.encode("ascii"), request_id.encode("ascii")
    bare = len(_hello_bytes(encoded, tail=b',"%s":""' % unknown))
    return _hello_bytes(encoded, tail=b',"%s":"%s"' % (unknown, b"a" * (length - bare)))


def _step(request_id: str, game_id: str, expected_step: int, candidate_id: int,
          echo: Mapping[str, Any]) -> dict[str, Any]:
    return StepRequest(request_id, game_id, expected_step, Selection(candidate_id, dict(echo))).to_json()


def _probe(request_id: str, game_id: str) -> dict[str, Any]:
    """``probe_resample`` (spec 9.7): reserved, so only its refusal is checked."""
    return {"request_type": "probe_resample", "protocol": PROTOCOL, "request_id": request_id, "game_id": game_id,
            "samples": 1}


def _absent(name: str, taken: Iterable[str]) -> str:
    """``name``, lengthened until ``taken`` lacks it."""
    values = set(taken)
    while name in values:
        name += "_x"
    return name


def _candidates(decision: Decision) -> list[Any]:
    candidates = decision.seat_decision.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise _Failed(f"the decision at step {decision.step} has no candidates (spec 9.3)")
    return candidates


def _semantic(decision: Decision, index: int) -> dict[str, Any]:
    """Candidate ``index``'s ``semantic`` (candidate ids are dense, spec 7.1), echoed by every step (spec 9.4)."""
    candidates = _candidates(decision)
    candidate = candidates[index] if index < len(candidates) else None
    semantic = candidate.get("semantic") if isinstance(candidate, dict) else None
    if not isinstance(semantic, dict):
        raise _Failed(f"the decision at step {decision.step} has no semantic object for candidate {index} (spec 7.1)")
    return semantic


# ---------------------------------------------------------------------------
# One check's engine process
# ---------------------------------------------------------------------------


class _Tap:
    """The engine's pipe, keeping the last line read so a failure can quote what the engine sent."""

    def __init__(self, peer: wire.SubprocessPeer) -> None:
        self._peer = peer
        self.last_line: bytes | None = None

    def write_line(self, payload: bytes) -> None:
        self._peer.write_line(payload)

    def read_line(self) -> bytes:
        self.last_line = self._peer.read_line()
        return self.last_line

    def set_timeout(self, seconds: float | None) -> None:
        self._peer.set_timeout(seconds)

    def stderr_text(self) -> str:
        return self._peer.stderr_text()

    def close(self) -> None:
        self._peer.close()


class _Session:
    """A fresh engine process for one check (spec 2: one process hosts at most one game)."""

    def __init__(self, run: _Run) -> None:
        self.run = run
        try:
            peer = wire.SubprocessPeer(run.argv, timeout_s=run.timeout_s)
        except TransportError as exc:
            raise _Failed(f"the engine could not start: {exc}") from exc
        self.tap = _Tap(peer)
        self.engine = EngineProcess(peer=self.tap)
        self._hello: EnvHelloOk | None = None

    def close(self) -> None:
        self.engine.close()

    def next_id(self) -> str:
        return self.engine.next_request_id()

    def _call(self, label: str, expected: str, call: Callable[[], Any]) -> Any:
        """One exchange; anything short of ``expected`` fails the check, naming ``label``."""
        try:
            return call()
        except EngineError as exc:
            request_id = (self.engine.last_request or {}).get("request_id", "")
            raise _Failed(f"{label}: expected {expected}, got {_error_text(exc.code, request_id)}"
                          f"{_said(exc.message)}") from exc
        except PeerTimeoutError as exc:
            raise _Failed(f"{label}: no answer within {_seconds(self.run.timeout_s)} s (the request timeout)") from exc
        except LineTooLongError as exc:
            raise _Failed(f"{label}: the answer is a line over 8 MiB (spec 2)") from exc
        except MalformedJsonError as exc:
            raise _Failed(f"{label}: the answer is not strict JSON ({exc}): {_clip(repr(self.tap.last_line))}") from exc
        except ProtocolError as exc:
            raise _Failed(f"{label}: expected {expected}, but the answer is invalid: {exc}") from exc
        except TransportError as exc:
            raise _Failed(f"{label}: the engine process failed: {exc}") from exc

    def hello(self) -> EnvHelloOk:
        """The engine's ``hello_ok``, which ``EngineProcess`` checks strictly (spec 9.1)."""
        self._hello = self._call("hello", "a hello_ok", self.engine.hello)
        return self._hello

    @property
    def declared(self) -> EnvHelloOk:
        if self._hello is None:
            raise RuntimeError("the check sent no hello")
        return self._hello

    def send(self, label: str, payload: Mapping[str, Any] | bytes) -> dict[str, Any]:
        """Send a message as canonical JSON, or bytes unchanged, and return the strict-parsed answer."""
        line = payload if isinstance(payload, bytes) else wire.canonical_json_dumps(payload)
        return self._call(label, "an answer", lambda: self.engine.send_line(line))

    def expect_error(self, label: str, payload: Mapping[str, Any] | bytes, code: str, request_id: str) -> None:
        """The answer to ``payload`` is the error ``code`` answering ``request_id`` (spec 9.8)."""
        answer = self.send(label, payload)
        if not _is_error(answer, code, request_id):
            raise _Failed(f"{label}: expected {_error_text(code, request_id)}, got {_describe(answer)}")

    def expect_play(self, label: str, payload: Mapping[str, Any] | bytes, request_id: str, *, game_id: str,
                    step: int) -> Decision | Terminal:
        return self.play_answer(label, self.send(label, payload), request_id, game_id=game_id, step=step)

    def play_answer(self, label: str, answer: Mapping[str, Any], request_id: str, *, game_id: str,
                    step: int) -> Decision | Terminal:
        """``answer`` as the decision numbered ``step``, or a terminal, of ``game_id`` for ``request_id``.

        Spec 9.3 and 9.5: the binding the engine client checks for the requests it sends itself.
        """
        kind = answer.get("response_type")
        if kind not in ("decision", "terminal"):
            raise _Failed(f"{label}: expected a decision or a terminal, got {_describe(answer)}")
        try:
            parsed = Decision.from_json(answer) if kind == "decision" else Terminal.from_json(answer)
        except ValidationError as exc:
            raise _Failed(f"{label}: the {kind} is invalid: {exc}") from exc
        if parsed.request_id != request_id:
            raise _Failed(f"{label}: the {kind} answers request_id {_id(parsed.request_id)}, "
                          f"not {_id(request_id)} (spec 4.1)")
        if parsed.game_id != game_id:
            raise _Failed(f"{label}: the {kind} names game {_id(parsed.game_id)}, not {_id(game_id)} (spec 9.3)")
        if isinstance(parsed, Decision) and parsed.step != step:
            raise _Failed(f"{label}: the decision has step {parsed.step}, not {step} (spec 9.3)")
        return parsed

    def reset(self, label: str, request: ResetRequest) -> Decision | Terminal:
        return self._call(label, "a decision or a terminal", lambda: self.engine.reset(request))

    def decision(self, label: str, request: ResetRequest) -> Decision:
        """A reset that must pose a decision, which the check then works on."""
        response = self.reset(label, request)
        if not isinstance(response, Decision):
            raise _Failed(f"{label}: the reset ended the game at once (a {response.result.classification} terminal), "
                          "so no decision was pending; this check needs a deck whose game poses one")
        return response

    def step(self, label: str, decision: Decision, index: int = 0) -> Decision | Terminal:
        semantic = _semantic(decision, index)
        return self._call(label, "a decision or a terminal",
                          lambda: self.engine.step(candidate_id=index, semantic=semantic))

    def play_out(self, label: str, response: Decision | Terminal) -> Terminal:
        """Answer candidate 0 until the terminal, which the caps bring within CONFORMANCE_CAP answers (spec 9.2)."""
        for _ in range(CONFORMANCE_CAP):
            if isinstance(response, Terminal):
                return response
            response = self.step(label, response)
        if isinstance(response, Terminal):
            return response
        raise _Failed(f"{label}: the game did not end within {CONFORMANCE_CAP} answers, its max_steps (spec 9.2)")

    def first_deck(self) -> tuple[WireDeck, CardNameDomain]:
        """The first deck as a reset carries it, and its card names as the domain (spec 4.3, 12.2)."""
        catalog_id = self.run.decks[0]
        for deck in self.declared.catalog:
            if deck.catalog_id == catalog_id:
                context = f"hello_ok.catalog ({catalog_id}).decklist"
                rows = digests.deck_rows([row.to_json() for row in deck.decklist], context)
                domain = CardNameDomain.from_json(digests.card_name_domain(row["name"] for row in rows))
                return WireDeck(digests.deck_id(rows), catalog_id=catalog_id), domain
        raise _Failed(f"deck {catalog_id!r} is not in hello_ok.catalog, so no game can be reset (spec 9.2)")

    def rules(self, **changes: Any) -> Rules:
        """The rules a benchmark sends this engine (spec 12.2, Decision 8), with ``changes``."""
        supported = self.declared.profile.rules_supported
        host_assigned = "host_assigned" in supported["starting_player"]
        rules = Rules(
            opponent_decklist="visible",
            mulligan="london" if "london" in supported["mulligan"] else "none",
            starting_player="host_assigned" if host_assigned else "toss_winner_chooses",
            starting_seat="p0" if host_assigned else None,
            card_name_domain=self.first_deck()[1],
            extensions=(),
            probe=False,
        )
        return replace(rules, **changes)

    def reset_request(self, game: int, *, request_id: str | None = None, format: str | None = None,
                      seats: tuple[WireDeck, WireDeck] | None = None, rules: Rules | None = None) -> ResetRequest:
        """A reset of this check's game ``game``: the first deck in both seats, unless ``seats`` says otherwise."""
        deck = self.first_deck()[0]
        return ResetRequest(
            request_id=self.next_id() if request_id is None else request_id,
            game_id=self.run.secret.game_id(game),
            format=self.run.format if format is None else format,
            seats=(deck, deck) if seats is None else seats,
            rules=self.rules() if rules is None else rules,
            game_secret=self.run.secret.game_secret(game).hex(),
            max_decisions=CONFORMANCE_CAP,
            max_steps=CONFORMANCE_CAP,
        )


# ---------------------------------------------------------------------------
# The protocol checks: each gets its own process and returns what it checked
# ---------------------------------------------------------------------------


def _check_hello(session: _Session) -> str:
    hello = session.hello()
    run = session.run
    if run.format not in hello.formats:
        raise _Failed(f"format {run.format!r} is not in hello_ok.formats {list(hello.formats)} (spec 9.1)")
    catalog = {deck.catalog_id for deck in hello.catalog}
    missing = [deck for deck in run.decks if deck not in catalog]
    if missing:
        raise _Failed(f"hello_ok.catalog lacks {', '.join(map(repr, missing))} (spec 9.1, 12.1)")
    return f"{hello.engine.name} {hello.engine.version} offers {run.format} and {len(run.decks)} catalog decks"


def _check_protocol_mismatch(session: _Session) -> str:
    request_id = session.next_id()
    session.expect_error('a hello with protocol "spellbench/v1" before any hello',
                         {**_hello(request_id), "protocol": "spellbench/v1"}, "protocol_mismatch", request_id)
    session.hello()
    request = session.reset_request(0)
    session.expect_error('a reset with protocol "spellbench/v1"', {**request.to_json(), "protocol": "spellbench/v1"},
                         "protocol_mismatch", request.request_id)
    return "a hello and a reset of another protocol"


def _check_malformed_json(session: _Session) -> str:
    session.hello()
    probes = [("a line that is not JSON", b"{not json")]
    for label, minor in (("a duplicate key", b'0,"protocol_minor":0'), ("a number with a fraction", b"0.5"),
                         ("a number with an exponent", b"1e0"), ("an integer beyond 2^53 - 1", b"9007199254740992"),
                         ("nesting deeper than 64 levels", b"[" * 64 + b"0" + b"]" * 64)):   # levels 2 to 65
        probes.append((label, _hello_bytes(session.next_id().encode("ascii"), minor=minor)))
    probes.append(("invalid UTF-8", _hello_bytes(session.next_id().encode("ascii") + b"\xff")))
    probes.append(("an unpaired surrogate escape", _hello_bytes(session.next_id().encode("ascii") + b"\\ud800")))
    probes.append(("a line over 8 MiB", _padded_hello(session.next_id(), wire.MAX_LINE_BYTES + 16)))
    for label, line in probes:
        session.expect_error(label, line, "malformed_json", "")
    request_id = session.next_id()
    session.expect_error("the next request after the line over 8 MiB",
                         _step(request_id, session.run.secret.game_id(0), 0, 0, _PASS), "step_before_reset", request_id)
    return f"{len(probes)} lines that are not strict JSON"


def _without(message: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != field}


def _check_malformed_request(session: _Session) -> str:
    session.hello()
    # (label, request, the request_id its error echoes)
    probes: list[tuple[str, Mapping[str, Any] | bytes, str]] = []
    request_id = session.next_id()
    probes.append(("an unknown field", {**_hello(request_id), _UNKNOWN_FIELD: 0}, request_id))
    reset = session.reset_request(0).to_json()
    reset["rules"][_UNKNOWN_FIELD] = True
    probes.append(("an unknown field in reset.rules", reset, reset["request_id"]))
    request_id = session.next_id()
    probes.append(("an unknown request_type",
                   {"request_type": _UNKNOWN_FIELD, "protocol": PROTOCOL, "request_id": request_id}, request_id))
    request_id = session.next_id()
    probes.append(("a missing protocol", _without(_hello(request_id), "protocol"), request_id))
    request_id = session.next_id()
    probes.append(("a protocol that is not a string", {**_hello(request_id), "protocol": 2}, request_id))
    # An unreadable request_id is answered with "" (spec 4.1).
    probes.append(("a missing request_id", _without(_hello("unused"), "request_id"), ""))
    probes.append(("a request_id that is not a string", {**_hello("unused"), "request_id": 7}, ""))
    request_id = session.next_id()
    probes.append(("a missing field", _without(_hello(request_id), "protocol_minor"), request_id))
    request_id = session.next_id()
    probes.append(("a mistyped field", {**_hello(request_id), "protocol_minor": "0"}, request_id))
    request_id = session.next_id()
    probes.append(("an unknown field on a line of 8 MiB minus 16 bytes",
                   _padded_hello(request_id, wire.MAX_LINE_BYTES - 16), request_id))
    request_id = session.next_id()
    deep = b"[" * 63 + b"]" * 63                     # levels 2 to 64 under the top-level object: strict JSON (spec 2)
    probes.append(("an unknown field at a nesting depth of 64",
                   _hello_bytes(request_id.encode("ascii"), tail=b',"%s":%s' % (_UNKNOWN_FIELD.encode("ascii"), deep)),
                   request_id))
    for label, payload, echoed in probes:
        session.expect_error(label, payload, "malformed_request", echoed)
    return f"{len(probes)} malformed requests"


def _check_malformed_request_non_object(session: _Session) -> str:
    session.hello()
    lines = (b"[1,2]", b'"spellbench/v2"', b"42", b"null")
    for line in lines:
        session.expect_error(f"the line {line.decode('ascii')}", line, "malformed_request", "")
    return f"{len(lines)} lines whose top level is not an object"


def _check_unsupported_rule(session: _Session) -> str:
    hello = session.hello()
    probes = []
    if not hello.profile.fairness["noninterference_probe"]:
        probes.append(("a reset with rules.probe true", session.rules(probe=True)))
    extension = _absent(UNDECLARED_EXTENSION, (declared.name for declared in hello.profile.extensions))
    probes.append((f"a reset enabling the undeclared extension {extension}", session.rules(extensions=(extension,))))
    supported = hello.profile.rules_supported
    for value in MULLIGAN_RULES:
        if value not in supported["mulligan"]:
            label = f'a reset with rules.mulligan "{value}", outside rules_supported'
            probes.append((label, session.rules(mulligan=value)))
    for value in STARTING_PLAYER_RULES:
        if value not in supported["starting_player"]:
            seat = "p0" if value == "host_assigned" else None       # spec 12.2: a seat only with host_assigned
            probes.append((f'a reset with rules.starting_player "{value}", outside rules_supported',
                           session.rules(starting_player=value, starting_seat=seat)))
    for game, (label, rules) in enumerate(probes):
        request = session.reset_request(game, rules=rules)
        session.expect_error(label, request.to_json(), "unsupported_rule", request.request_id)
    return f"{len(probes)} resets with an unsupported rule"


def _check_game_id_reuse(session: _Session) -> str:
    session.hello()
    terminal = session.play_out("the first game", session.reset("a reset", session.reset_request(0)))
    request = session.reset_request(0)
    session.expect_error("a reset reusing the finished game's game_id", request.to_json(), "malformed_request",
                         request.request_id)
    session.reset("a reset with a fresh game_id after that", session.reset_request(1))
    return f"a reset reusing the id of a game ended at step_count {terminal.result.step_count}"


def _check_never_cached(session: _Session) -> str:
    session.hello()
    request_id = session.next_id()
    broken = {**session.reset_request(0, request_id=request_id).to_json(), _UNKNOWN_FIELD: True}
    session.expect_error("a reset with an unknown field", broken, "malformed_request", request_id)
    decision = session.decision("a valid reset under the request_id of a reset that failed parsing",
                                session.reset_request(1, request_id=request_id))
    request_id = session.next_id()
    valid = _step(request_id, decision.game_id, decision.step, 0, _semantic(decision, 0))
    session.expect_error("a step with an unknown field", {**valid, _UNKNOWN_FIELD: True}, "malformed_request",
                         request_id)
    session.expect_play("a valid step under the request_id of a step that failed parsing", valid, request_id,
                        game_id=decision.game_id, step=decision.step + 1)
    return "a reset and a step whose request_id first failed parsing"


def _check_step_check_order(session: _Session) -> str:
    session.hello()
    other = session.run.secret.game_id(9)            # a game this process never saw
    request_id = session.next_id()
    session.expect_error("before any reset, a step naming a game with a wrong expected_step",
                         _step(request_id, other, 3, 0, _PASS), "step_before_reset", request_id)
    decision = session.decision("a reset", session.reset_request(0))
    first = _semantic(decision, 0)
    request_id = session.next_id()
    session.expect_error("a step naming another game with a wrong expected_step",
                         _step(request_id, other, decision.step + 5, 0, first), "game_id_mismatch", request_id)
    request_id = session.next_id()
    session.expect_error("a step with a wrong expected_step and an out-of-range candidate_id",
                         _step(request_id, decision.game_id, decision.step + 5, len(_candidates(decision)), first),
                         "expected_step_mismatch", request_id)
    steps = session.play_out("the game", decision).result.step_count
    request_id = session.next_id()
    session.expect_error("after the terminal, a step naming another game", _step(request_id, other, steps, 0, _PASS),
                         "game_id_mismatch", request_id)
    request_id = session.next_id()
    session.expect_error("after the terminal, a step with a wrong expected_step",
                         _step(request_id, decision.game_id, steps + 5, 0, _PASS), "game_already_terminal", request_id)
    return "5 steps with two faults each"


def _check_step_before_reset(session: _Session) -> str:
    hello = session.hello()
    game_id = session.run.secret.game_id(0)
    request_id = session.next_id()
    session.expect_error("a step before any reset", _step(request_id, game_id, 0, 0, _PASS), "step_before_reset",
                         request_id)
    if hello.profile.fairness["noninterference_probe"]:
        request_id = session.next_id()
        session.expect_error("a probe_resample before any reset", _probe(request_id, game_id), "step_before_reset",
                             request_id)
    name = _absent(NO_SUCH_FORMAT, hello.formats)
    request = session.reset_request(0, format=name)
    session.expect_error(f'a reset with format "{name}"', request.to_json(), "unsupported_format", request.request_id)
    request_id = session.next_id()
    session.expect_error("a step after a refused reset", _step(request_id, game_id, 0, 0, _PASS), "step_before_reset",
                         request_id)
    return "steps before any game was reset"


def _check_unsupported_format(session: _Session) -> str:
    hello = session.hello()
    name = _absent(NO_SUCH_FORMAT, hello.formats)
    request = session.reset_request(0, format=name)
    session.expect_error(f'a reset with format "{name}"', request.to_json(), "unsupported_format", request.request_id)
    return f"a reset with the format {name}"


def _check_unsupported_deck(session: _Session) -> str:
    session.hello()
    deck = session.first_deck()[0]
    unknown = WireDeck(deck.deck_id, catalog_id=NO_SUCH_DECK)
    rows = (DeckRow(NO_SUCH_CARD, 60),)
    listed = WireDeck(digests.deck_id([row.to_json() for row in rows]), decklist=rows)
    probes = ((f'a reset with the unknown catalog_id "{NO_SUCH_DECK}" in seat p0', (unknown, deck)),
              (f'a reset with the unknown catalog_id "{NO_SUCH_DECK}" in seat p1', (deck, unknown)),
              (f'a reset whose p0 deck is a decklist of the made-up card "{NO_SUCH_CARD}"', (listed, deck)))
    for game, (label, seats) in enumerate(probes):
        request = session.reset_request(game, seats=seats)
        session.expect_error(label, request.to_json(), "unsupported_deck", request.request_id)
    return f"{len(probes)} resets with a deck no engine can play"


def _check_unsupported_request(session: _Session) -> str:
    hello = session.hello()
    decision = session.decision("a reset", session.reset_request(0))
    code = "probe_refused" if hello.profile.fairness["noninterference_probe"] else "unsupported_request"
    request_id = session.next_id()
    session.expect_error("a probe_resample during a game", _probe(request_id, decision.game_id), code, request_id)
    return f"probe_resample answered {code}"


def _check_game_already_active(session: _Session) -> str:
    session.hello()
    decision = session.decision("a reset", session.reset_request(0))
    request = session.reset_request(1)
    session.expect_error("a reset while a game is active", request.to_json(), "game_already_active", request.request_id)
    session.step("the pending decision, answered after that", decision)
    return "a second reset during a game"


def _check_game_id_mismatch(session: _Session) -> str:
    session.hello()
    decision = session.decision("a reset", session.reset_request(0))
    request_id = session.next_id()
    session.expect_error("a step naming another game",
                         _step(request_id, session.run.secret.game_id(1), decision.step, 0, _semantic(decision, 0)),
                         "game_id_mismatch", request_id)
    session.step("the pending decision, answered after that", decision)
    return "a step naming another game"


def _check_expected_step_mismatch(session: _Session) -> str:
    session.hello()
    decision = session.decision("a reset", session.reset_request(0))
    request_id = session.next_id()
    session.expect_error("a step with an expected_step ahead of the pending decision",
                         _step(request_id, decision.game_id, decision.step + 1, 0, _semantic(decision, 0)),
                         "expected_step_mismatch", request_id)
    after = session.step("the pending decision, answered after that", decision)
    if not isinstance(after, Decision):
        return "a step ahead of the pending decision (the game ended before a stale one could be sent)"
    request_id = session.next_id()
    session.expect_error(f"a step with the stale expected_step {decision.step}",
                         _step(request_id, after.game_id, decision.step, 0, _semantic(after, 0)),
                         "expected_step_mismatch", request_id)
    session.step("the next decision, answered after that", after)
    return "a step ahead of the pending decision and a stale one"


def _check_candidate_id_out_of_range(session: _Session) -> str:
    session.hello()
    decision = session.decision("a reset", session.reset_request(0))
    count = len(_candidates(decision))
    for candidate_id in (count, _U32_MAX):
        request_id = session.next_id()
        session.expect_error(f"a step with candidate_id {candidate_id}, past the {count} candidates",
                             _step(request_id, decision.game_id, decision.step, candidate_id, _semantic(decision, 0)),
                             "candidate_id_out_of_range", request_id)
    session.step("the pending decision, answered after that", decision)
    return f"candidate_id {count} and {_U32_MAX} among {count} candidates"


def _check_semantic_echo_mismatch(session: _Session) -> str:
    session.hello()
    response = session.reset("a reset", session.reset_request(0))
    for _ in range(CONFORMANCE_CAP):
        if not isinstance(response, Decision) or len(_candidates(response)) >= 2:
            break
        response = session.step("a decision with one candidate", response)
    if isinstance(response, Terminal):
        raise _Failed(f"no decision offered two candidates before the game ended at step_count "
                      f"{response.result.step_count}, so no echo could name another candidate (spec 9.4)")
    if len(_candidates(response)) < 2:
        raise _Failed(f"no decision offered two candidates within {CONFORMANCE_CAP} answers, the game's max_steps "
                      "(spec 9.2)")
    request_id = session.next_id()
    session.expect_error("a step echoing another candidate's semantic",
                         _step(request_id, response.game_id, response.step, 0, _semantic(response, 1)),
                         "semantic_echo_mismatch", request_id)
    session.step("the pending decision, answered after that", response)
    return f"candidate 0 with candidate 1's semantic at step {response.step}"


def _check_retransmission(session: _Session) -> str:
    session.hello()
    reset = session.reset_request(0)
    reset_line = wire.canonical_json_dumps(reset.to_json())
    first = session.send("the reset", reset_line)
    decision = session.play_answer("the reset", first, reset.request_id, game_id=reset.game_id, step=0)
    if not isinstance(decision, Decision):
        raise _Failed("the reset: the reset ended the game at once, so no step could be sent again; this check needs "
                      "a deck whose game poses a decision")
    _expect_same(session, "the reset sent again byte for byte", reset_line, first)
    changed = {**reset.to_json(), "max_steps": CONFORMANCE_CAP + 1}
    session.expect_error("the reset changed under the same request_id", changed, "request_id_reuse_mismatch",
                         reset.request_id)
    request_id = session.next_id()
    step = _step(request_id, decision.game_id, decision.step, 0, _semantic(decision, 0))
    step_line = wire.canonical_json_dumps(step)
    answer = session.send("the step", step_line)
    after = session.play_answer("the step", answer, request_id, game_id=decision.game_id, step=decision.step + 1)
    _expect_same(session, "the step sent again byte for byte", step_line, answer)
    session.expect_error("the step changed under the same request_id", {**step, "expected_step": decision.step + 1},
                         "request_id_reuse_mismatch", request_id)
    if isinstance(after, Decision):
        request_id = session.next_id()
        session.expect_play("the next step", _step(request_id, after.game_id, after.step, 0, _semantic(after, 0)),
                            request_id, game_id=after.game_id, step=after.step + 1)
    return "a reset and a step, each sent again and changed"


def _expect_same(session: _Session, label: str, line: bytes, first: Mapping[str, Any]) -> None:
    """The identical request gets the first answer again, compared as parsed JSON (spec 4.1, 4.3)."""
    again = session.send(label, line)
    if wire.canonical_json_dumps(again) != wire.canonical_json_dumps(first):
        raise _Failed(f"{label}: expected the first answer again, got {_describe(again)}; "
                      f"the first difference is at {_difference(first, again)}")


def _check_game_already_terminal(session: _Session) -> str:
    session.hello()
    request = session.reset_request(0)
    terminal = session.play_out("the game", session.reset("a reset", request))
    request_id = session.next_id()
    late = _step(request_id, request.game_id, terminal.result.step_count, 0, _PASS)
    session.expect_error("a step after the terminal", late, "game_already_terminal", request_id)
    return f"a step after a {terminal.result.classification} terminal at step_count {terminal.result.step_count}"


_SESSION_CHECKS: dict[str, Callable[[_Session], str]] = {
    "hello": _check_hello,
    "protocol_mismatch": _check_protocol_mismatch,
    "malformed_json": _check_malformed_json,
    "malformed_request": _check_malformed_request,
    "malformed_request_non_object": _check_malformed_request_non_object,
    "unsupported_rule": _check_unsupported_rule,
    "game_id_reuse": _check_game_id_reuse,
    "never_cached": _check_never_cached,
    "step_check_order": _check_step_check_order,
    "step_before_reset": _check_step_before_reset,
    "unsupported_format": _check_unsupported_format,
    "unsupported_deck": _check_unsupported_deck,
    "unsupported_request": _check_unsupported_request,
    "game_already_active": _check_game_already_active,
    "game_id_mismatch": _check_game_id_mismatch,
    "expected_step_mismatch": _check_expected_step_mismatch,
    "candidate_id_out_of_range": _check_candidate_id_out_of_range,
    "semantic_echo_mismatch": _check_semantic_echo_mismatch,
    "retransmission": _check_retransmission,
    "game_already_terminal": _check_game_already_terminal,
}


# ---------------------------------------------------------------------------
# The games check (spec 11.1 to 11.5)
# ---------------------------------------------------------------------------


def _games_config(run: _Run) -> TournamentConfig:
    """``first`` against ``uniform``, seat-swapped pairs over the decks in turn, bounded by the request timeout."""
    # Enough seat-swapped pairs for ``games`` games, a multiple of the pool as the config requires.
    pairs = math.ceil(math.ceil(run.games / 2) / len(run.decks)) * len(run.decks)
    bound_ms = math.ceil(run.timeout_s * 1000)
    try:
        return TournamentConfig.from_json({
            "schema": CONFIG_SCHEMA,
            "tournament_dir": "conformance",
            "format": run.format,
            "deck_pool": [{"catalog_id": deck} for deck in run.decks],
            "engine": {"command": list(run.argv)},
            "bots": [{"name": name, "version": BUILTIN_VERSIONS[name], "type": "builtin"}
                     for name in ("first", "uniform")],
            "pairs_per_matchup": pairs,
            "stats_seed": 0,
            "include_self_play": False,
            "time_control": {**DEFAULT_TIME_CONTROL.to_json(), "startup_ms": bound_ms, "engine_step_ms": bound_ms},
            "bootstrap_replicates": 1000,
        })
    except TournamentError as exc:
        raise _Failed(f"the games cannot be set up: {exc}") from exc


def _game_label(number: int, total: int, context: GameContext) -> str:
    (_, first), (_, second) = context.seat_specs
    return f"game {number} of {total} ({context.decks[0].catalog_id}, {first.name} as p0 against {second.name})"


def _play(config: TournamentConfig, setup: RunSetup, context: GameContext, secret: RunSecret, pin: EnginePin,
          label: str) -> GameResult:
    """One scheduled game in its own engine process, with builtin seats (spec 11.2)."""
    game = game_setup(config, setup, context, secret)
    try:
        engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
    except TransportError as exc:
        raise _Failed(f"{label}: the engine could not start: {exc}") from exc
    seats = {seat: BuiltinDriver(spec) for seat, spec in context.seat_specs}
    try:
        try:
            hello = engine.hello()
        except (TransportError, RemoteError, ProtocolError) as exc:
            raise _Failed(f"{label}: hello failed: {exc}") from exc
        try:
            pin.check(hello.engine)            # every process reports the identity the first one did (spec 11.3 V10)
        except TournamentError as exc:
            raise _Failed(f"{label}: {exc}") from exc
        return play_game(game, engine=engine, seats=seats)
    finally:
        for driver in seats.values():
            driver.close()
        engine.close()


def _check_games(run: _Run) -> str:
    config = _games_config(run)
    secret = RunSecret.generate()              # fresh, so no other run's ids or seeds (spec 11.6)
    pin = EnginePin()
    try:
        setup = preflight(config, secret, pin=pin)
    except TournamentError as exc:
        raise _Failed(str(exc)) from exc
    contexts = schedule(config, secret)[: run.games]
    endings: Counter[str] = Counter()
    for number, context in enumerate(contexts, 1):
        label = _game_label(number, len(contexts), context)
        result = _play(config, setup, context, secret, pin, label)
        adjudication = result.adjudication or {}
        if result.classification == "forfeit":
            seat = adjudication.get("loser_seat")
            bot = dict(context.seat_specs)[seat].name if seat in ("p0", "p1") else "?"
            raise _Failed(f"{label}: {result.reason}: {seat} ({bot}) forfeited: {adjudication.get('detail')}")
        if result.classification == "halted" and result.reason.startswith(_HOST_HALTS):
            cause = f" ({_clip(result.diagnostics[0], 300)})" if result.diagnostics else ""
            raise _Failed(f"{label}: halted {result.reason}: {adjudication.get('detail')}{cause}")
        endings[result.classification] += 1
    played = ", ".join(f"{count} {classification}" for classification, count in sorted(endings.items()))
    return f"played {len(contexts)} game{'' if len(contexts) == 1 else 's'}: {played}"


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def _run_check(name: str, run: _Run) -> CheckResult:
    """One check; its failure, and any exception inside it, becomes its result (``KeyboardInterrupt`` propagates)."""
    try:
        if name == "games":
            detail = _check_games(run)
        else:
            session = _Session(run)
            try:
                detail = _SESSION_CHECKS[name](session)
            finally:
                session.close()
    except _Failed as failure:
        return CheckResult(name, False, _one_line(str(failure)))
    except Exception as exc:  # noqa: BLE001 - an exception inside a check is that check's failure, never the runner's
        return CheckResult(name, False, _one_line(f"{type(exc).__name__}: {exc}"))
    return CheckResult(name, True, _one_line(detail))


def _command(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)) or not argv or not all(isinstance(part, str) and part for part in argv):
        raise ValueError("argv must be a nonempty sequence of nonempty strings")
    return tuple(argv)


def _timeout(timeout_s: float) -> float:
    if type(timeout_s) not in (int, float) or not 0 < timeout_s <= _MAX_TIMEOUT_S:   # NaN fails the comparison too
        raise ValueError(f"timeout_s must be a number of seconds above 0 and at most {_MAX_TIMEOUT_S:g}")
    return float(timeout_s)


def _selected(only: Iterable[str] | None) -> tuple[str, ...]:
    if only is None:
        return CHECK_NAMES
    if isinstance(only, (str, bytes)):
        raise ValueError("only must be a collection of check names, not one string")
    try:
        names = set(only)
    except TypeError as exc:
        raise ValueError("only must be a collection of check names") from exc
    unknown = sorted(names - set(CHECK_NAMES), key=str)
    if unknown or not names:
        raise ValueError(f"only must name checks of CHECK_NAMES; unknown: {unknown}")
    return tuple(name for name in CHECK_NAMES if name in names)


def check_engine(argv: Sequence[str], *, format: str, decks: Sequence[str], games: int = 4,
                 timeout_s: float = REQUEST_TIMEOUT_S, only: Iterable[str] | None = None) -> ConformanceReport:
    """Hold the engine command ``argv`` to every check, or to those named in ``only`` (module docstring).

    ``decks`` are catalog ids: the first is played by the protocol checks, all in turn by the games.
    Arguments no check can use raise ``ValueError``; whatever the engine does is reported, never raised.
    """
    if not isinstance(format, str) or not format:
        raise ValueError("format must be a nonempty string")
    if isinstance(decks, (str, bytes)) or not decks or not all(isinstance(deck, str) and deck for deck in decks):
        raise ValueError("decks must be a nonempty sequence of catalog ids")
    if len(set(decks)) != len(decks):
        raise ValueError(f"decks must be distinct, got {list(decks)}")
    if type(games) is not int or games < 1:
        raise ValueError("games must be an integer of at least 1")
    run = _Run(argv=_command(argv), format=format, decks=tuple(decks), games=games, timeout_s=_timeout(timeout_s),
               secret=RunSecret.generate())
    return ConformanceReport(tuple(_run_check(name, run) for name in _selected(only)))


# ---------------------------------------------------------------------------
# Golden transcript replay (spec 16; Decision 7, R3-11)
# ---------------------------------------------------------------------------


def _engine_exchanges(path: Path) -> list[tuple[int, dict[str, Any] | str, int, dict[str, Any] | str]]:
    """The engine rows as (request line number, request, answer line number, answer); agent rows are skipped."""
    exchanges: list[tuple[int, dict[str, Any] | str, int, dict[str, Any] | str]] = []
    pending: tuple[int, dict[str, Any] | str] | None = None
    for number, raw in enumerate(path.read_bytes().splitlines(), 1):
        where = f"{path.name} line {number}"
        try:
            row = wire.strict_json_loads(raw)
        except MalformedJsonError as exc:
            raise ValueError(f"{where}: not a transcript row: {exc}") from exc
        if set(row) != {"dir", "message"} or row["dir"] not in _DIRECTIONS:
            raise ValueError(f'{where}: a row is exactly {{"dir", "message"}}, dir one of '
                             f'{", ".join(_DIRECTIONS)} (spec 16)')
        direction, message = row["dir"], row["message"]
        if direction not in ("host_to_engine", "engine_to_host"):
            continue
        if not isinstance(message, (dict, str)):
            raise ValueError(f"{where}: an engine row's message is an object, or a string holding a raw line "
                             "(Decision 7)")
        if direction == "host_to_engine":
            if pending is not None:
                raise ValueError(f"{path.name} line {pending[0]}: the request has no engine answer before "
                                 f"line {number}")
            if isinstance(message, str) and ("\n" in message or "\r" in message):
                raise ValueError(f"{where}: a raw line holds no line break")
            pending = (number, message)
        else:
            if pending is None:
                raise ValueError(f"{where}: an engine answer with no request before it")
            exchanges.append((pending[0], pending[1], number, message))
            pending = None
    if pending is not None:
        raise ValueError(f"{path.name} line {pending[0]}: the request has no engine answer")
    return exchanges


def _recorded(line: bytes) -> dict[str, Any] | str:
    """An answer as a golden records it: parsed, or its text when it is not strict JSON (Decision 7)."""
    try:
        return wire.strict_json_loads(line)
    except MalformedJsonError:
        return line.decode("utf-8", errors="replace")


def _request_label(request: dict[str, Any] | str) -> str:
    if isinstance(request, str):
        return f"the raw line {_clip(request, 40)!r}"
    return f"{_clip(str(request.get('request_type')), 40)} {_clip(str(request.get('request_id')), 40)}"


def replay_engine_transcript(argv: Sequence[str], path: Path, *, timeout_s: float = REQUEST_TIMEOUT_S) -> list[str]:
    """Replay a transcript's engine rows in one engine process and return every answer that differs (module docstring).

    A malformed transcript raises ``ValueError``; an engine that cannot start, stops answering or fails is reported
    as a mismatch, after which the replay stops.
    """
    exchanges = _engine_exchanges(Path(path))
    command, seconds = _command(argv), _timeout(timeout_s)
    if not exchanges:
        return []
    try:
        peer = wire.SubprocessPeer(command, timeout_s=seconds)
    except TransportError as exc:
        return [f"the engine could not start: {exc}"]
    mismatches: list[str] = []
    try:
        for request_number, request, answer_number, expected in exchanges:
            label = _request_label(request)
            # A string row is the offending line itself, sent unchanged; any other row as canonical JSON (R3-11).
            line = request.encode("utf-8") if isinstance(request, str) else wire.canonical_json_dumps(request)
            try:
                peer.write_line(line)
                answer = _recorded(peer.read_line())
            except PeerTimeoutError:
                mismatches.append(f"line {request_number}: {label} got no answer within {_seconds(seconds)} s "
                                  "(the request timeout)")
                break
            except LineTooLongError:
                mismatches.append(f"line {request_number}: {label} was answered with a line over 8 MiB (spec 2)")
                break
            except TransportError as exc:
                mismatches.append(_one_line(f"line {request_number}: {label}: the engine process failed: {exc}"))
                break
            if wire.canonical_json_dumps(answer) != wire.canonical_json_dumps(expected):
                difference = _difference(expected, answer)
                mismatches.append(f"line {answer_number}: the answer to {label} differs at {difference}")
    finally:
        peer.close()
    return mismatches
