"""The engine conformance runner: the checks a v2 engine adapter is held to (spec 4.1, 9, 11).

``check_engine`` runs every probe below against one engine command, each in a fresh engine
process, and records a :class:`CheckResult` per check; an exception inside a check is that
check's failure, never the runner's. The probes are the wire contract's mechanical core: a
strict ``hello_ok`` offering the format and every deck; the spec 9.8 error table, one probe
per code the host can drive (a non-JSON line, a non-object line, an unknown field, an unknown
format or deck, an undeclared rule, a reused game id or request id, each ``step`` refusal in
its check order); the retransmission cache of spec 4.1 (a parse failure is never cached; the
identical request is answered identically); and ``games`` whole games of builtin ``first``
against ``uniform``, seat-swapped, the decks in turn, through the arena's own machinery
(``preflight``, ``schedule``, ``game_setup``, ``play_game``) with a fresh run secret, each
required to end without a host halt or a forfeit.

``replay_engine_transcript`` sends every ``host_to_engine`` row of a golden transcript to a
fresh engine and compares each answer with its ``engine_to_host`` row as parsed JSON (R3-11):
a row whose ``message`` is a string (the offending line of a ``malformed_json`` or non-object
golden, Decision 7) is written as its UTF-8 bytes unchanged; every other row as canonical JSON.

The CLI is ``spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...] [--games N] -- ARGV...``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn, Sequence

from . import digests, wire
from .arena.config import CONFIG_SCHEMA, TournamentConfig
from .arena.drivers import BuiltinDriver
from .arena.schedule import GameContext, RunSetup, game_setup, preflight, schedule
from .builtins import BUILTIN_VERSIONS
from .errors import MalformedJsonError, ValidationError
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
    DeckOk,
    EnvHelloOk,
    ErrorResponse,
    ResetRequest,
    Rules,
    Selection,
    StepRequest,
    Terminal,
    WireDeck,
)
from .run_secret import RunSecret

# Probe values no conformant engine offers: a catalog id, a format and an extension name.
_NO_SUCH_DECK = "spellbench-conformance-no-such-deck"
_NO_SUCH_FORMAT = "spellbench-conformance-no-such-format"
_EXTENSION = "x_spellbench_conformance"
# Conformance resets are not a run: one fixed secret keeps every probe reproducible.
_GAME_SECRET = "0123456789abcdef" * 4
_CAPS = {"max_decisions": 2000, "max_steps": 2000}
_HOST_HALT_PREFIXES = ("host_validator:", "host_engine_fault:")
_TIMEOUT_S = 30.0
_NO_ANSWER: Any = object()  # a transcript's host_to_engine row with no engine_to_host row


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome; ``detail`` says why it failed ("" when it passed)."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ConformanceReport:
    """Every check's outcome, in run order."""

    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def render(self) -> str:
        """One line per check: ``PASS <name>`` or ``FAIL <name>: <detail>``."""
        return "\n".join(
            f"PASS {check.name}" if check.passed else f"FAIL {check.name}: {check.detail}" for check in self.checks
        )


class _CheckFailure(Exception):
    """One check's failure; its message is the check's detail."""


def _fail(detail: str) -> NoReturn:
    raise _CheckFailure(detail)


def _open(argv: Sequence[str]) -> EngineProcess:
    """A fresh engine process with a bounded exchange, the unit every check runs in."""
    return EngineProcess(list(argv), timeout_s=_TIMEOUT_S)


def _expect_error(answer: dict[str, Any], code: str, request_id: str) -> None:
    """The answer must be a strict error response (spec 9.8) with this code and request id."""
    try:
        error = ErrorResponse.from_json(answer, codes=ENGINE_ERROR_CODES)
    except ValidationError as exc:
        _fail(f"the answer is not a valid error response: {exc}")
    if error.code != code:
        _fail(f"expected {code}, got {error.code}: {error.message}")
    if error.request_id != request_id:
        _fail(f"the error's request_id is {error.request_id!r}, not {request_id!r}")


def _expect_deck_ok(answer: dict[str, Any], request_id: str) -> None:
    if answer.get("response_type") == "error":
        code = answer.get("error", {}).get("code") if isinstance(answer.get("error"), dict) else None
        _fail(f"expected deck_ok, got the error {code}: {wire.canonical_json_dumps(answer).decode('utf-8')}")
    try:
        deck_ok = DeckOk.from_json(answer)
    except ValidationError as exc:
        _fail(f"the answer is not a valid deck_ok: {exc}")
    if deck_ok.request_id != request_id:
        _fail(f"the deck_ok's request_id is {deck_ok.request_id!r}, not {request_id!r}")


# ---------------------------------------------------------------------------
# Probe message builders: a valid reset of one mirrored catalog deck
# ---------------------------------------------------------------------------


def _wire_deck(hello: EnvHelloOk, catalog_id: str) -> tuple[WireDeck, list[dict[str, Any]]]:
    """The catalog deck as ``reset`` carries it, with its checked rows (code point order)."""
    for deck in hello.catalog:
        if deck.catalog_id == catalog_id:
            rows = digests.deck_rows([row.to_json() for row in deck.decklist], f"hello_ok.catalog deck {catalog_id!r}")
            return WireDeck(digests.deck_id(rows), catalog_id=catalog_id), rows
    _fail(f"deck {catalog_id!r} is not in the engine's hello_ok.catalog")


def _rules(names: Sequence[str], **overrides: Any) -> Rules:
    """The spec 12.2 benchmark rules over these card names, plus ``overrides`` for one probe."""
    values: dict[str, Any] = {
        "opponent_decklist": "visible",
        "mulligan": "none",
        "starting_player": "host_assigned",
        "starting_seat": "p0",
        "extensions": (),
        "probe": False,
    }
    values.update(overrides)
    return Rules(
        opponent_decklist=values["opponent_decklist"],
        mulligan=values["mulligan"],
        starting_player=values["starting_player"],
        starting_seat=values["starting_seat"],
        card_name_domain=CardNameDomain.from_json(digests.card_name_domain(names)),
        extensions=values["extensions"],
        probe=values["probe"],
    )


def _reset_json(
    request_id: str,
    game_id: str,
    format: str,
    seats: tuple[WireDeck, WireDeck],
    rules: Rules,
    **caps: int,
) -> dict[str, Any]:
    caps = {**_CAPS, **caps}
    return ResetRequest(
        request_id=request_id, game_id=game_id, format=format, seats=seats, rules=rules,
        game_secret=_GAME_SECRET, max_decisions=caps["max_decisions"], max_steps=caps["max_steps"],
    ).to_json()


def _step_json(request_id: str, game_id: str, expected_step: int, candidate_id: int, semantic: Mapping[str, Any]) -> dict[str, Any]:
    return StepRequest(
        request_id=request_id, game_id=game_id, expected_step=expected_step,
        selection=Selection(candidate_id=candidate_id, semantic_echo=dict(semantic)),
    ).to_json()


def _mirror(hello: EnvHelloOk, catalog_id: str) -> tuple[tuple[WireDeck, WireDeck], Rules]:
    """Both seats on one catalog deck, with the rules a probe reset carries."""
    seat, rows = _wire_deck(hello, catalog_id)
    return (seat, seat), _rules([row["name"] for row in rows])


def _play_first(engine: EngineProcess, reset: dict[str, Any], *, max_steps: int) -> Terminal:
    """Play a game out taking candidate 0 (the semantic echoed as offered); the engine's terminal."""
    response = engine.reset(ResetRequest.from_json(reset))
    steps = 0
    while isinstance(response, Decision):
        if steps > max_steps:
            _fail(f"the game did not end within max_steps {max_steps}")
        semantic = response.seat_decision["candidates"][0]["semantic"]
        response = engine.step(candidate_id=0, semantic=semantic)
        steps += 1
    assert isinstance(response, Terminal)
    return response


# ---------------------------------------------------------------------------
# The checks, each in a fresh engine process (spec 9.2, 9.4, 9.8)
# ---------------------------------------------------------------------------


def _check_hello(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """A strict hello_ok, the format offered, every deck in the catalog."""
    with _open(argv) as engine:
        hello = engine.hello()
    if format not in hello.formats:
        _fail(f"format {format!r} is not offered: hello_ok.formats is {sorted(hello.formats)}")
    catalog = {deck.catalog_id for deck in hello.catalog}
    missing = [deck for deck in decks if deck not in catalog]
    if missing:
        _fail(f"decks missing from hello_ok.catalog: {', '.join(missing)}")


def _check_protocol_mismatch(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        answer = engine.send_raw(
            {"request_type": "hello", "protocol": "spellbench/v1", "request_id": "pm-1", "protocol_minor": PROTOCOL_MINOR}
        )
        _expect_error(answer, "protocol_mismatch", "pm-1")


def _check_malformed_json(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """A non-JSON line is answered ``malformed_json`` with ``request_id`` "" (spec 9.8)."""
    with _open(argv) as engine:
        _expect_error(engine.send_line(b"{not json"), "malformed_json", "")


def _check_malformed_request(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """An unknown field makes the request ``malformed_request`` (spec 4.2)."""
    with _open(argv) as engine:
        answer = engine.send_raw(
            {"request_type": "hello", "protocol": PROTOCOL, "request_id": "mr-1", "protocol_minor": PROTOCOL_MINOR,
             "no_such_field": 1}
        )
        _expect_error(answer, "malformed_request", "mr-1")


def _check_malformed_request_non_object(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """The line ``[1,2]``: valid JSON, a non-object top level (spec 9.8; R1-3)."""
    with _open(argv) as engine:
        _expect_error(engine.send_line(b"[1,2]"), "malformed_request", "")


def _check_unsupported_rule(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """Three resets, each expecting ``unsupported_rule`` (spec 9.2; R3-10)."""
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        probes = 0

        def reset_once(tag: str, **overrides: Any) -> None:
            request = _reset_json(f"rule-{tag}", f"g-conformance-rule-{tag}", format, seats, _rules(rules.card_name_domain.names, **overrides))
            _expect_error(engine.send_raw(request), "unsupported_rule", f"rule-{tag}")

        # rules.probe: true on an engine without the probe (spec 9.7 is reserved).
        if not hello.profile.fairness["noninterference_probe"]:
            probes += 1
            reset_once("probe", probe=True)
        # A rules.extensions entry the engine's hello_ok does not declare.
        if _EXTENSION not in {extension.name for extension in hello.profile.extensions}:
            probes += 1
            reset_once("extension", extensions=(_EXTENSION,))
        # A mulligan or starting-player value outside rules_supported, when the vocabulary has one.
        supported = hello.profile.rules_supported
        mulligan = next((rule for rule in MULLIGAN_RULES if rule not in supported["mulligan"]), None)
        starting = next((rule for rule in STARTING_PLAYER_RULES if rule not in supported["starting_player"]), None)
        if mulligan is not None:
            probes += 1
            reset_once("mulligan", mulligan=mulligan)
        elif starting is not None:
            probes += 1
            reset_once("starting", starting_player=starting, starting_seat=None)
        if probes == 0:
            _fail("the engine declares the probe, the probe extension and every rule value: nothing to refuse")


def _check_game_id_reuse(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """A reset reusing a finished game's game_id is ``malformed_request`` (spec 9.2)."""
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        game_id = "g-conformance-reuse"
        _play_first(engine, _reset_json("reuse-1", game_id, format, seats, rules), max_steps=_CAPS["max_steps"])
        answer = engine.send_raw(_reset_json("reuse-2", game_id, format, seats, rules))
        _expect_error(answer, "malformed_request", "reuse-2")


def _check_never_cached(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """A request that fails parsing is never cached: the same request_id with a valid payload is answered normally."""
    with _open(argv) as engine:
        engine.hello()
        broken = {"request_type": "validate_deck", "protocol": PROTOCOL, "request_id": "cache-1", "format": format,
                  "deck": {"catalog_id": decks[0]}, "no_such_field": 1}
        valid = {"request_type": "validate_deck", "protocol": PROTOCOL, "request_id": "cache-1", "format": format,
                 "deck": {"catalog_id": decks[0]}}
        _expect_error(engine.send_raw(broken), "malformed_request", "cache-1")
        _expect_deck_ok(engine.send_raw(valid), "cache-1")


def _check_step_check_order(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """A step with both a wrong game_id and a wrong expected_step is ``game_id_mismatch`` (spec 9.4; R1-20)."""
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        engine.reset(ResetRequest.from_json(_reset_json("order-1", "g-conformance-order", format, seats, rules)))
        answer = engine.send_raw(_step_json("order-2", "g-conformance-other", 99, 0, {"kind": "pass"}))
        _expect_error(answer, "game_id_mismatch", "order-2")


def _check_step_before_reset(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        engine.hello()
        answer = engine.send_raw(_step_json("sbr-1", "g-conformance-none", 0, 0, {"kind": "pass"}))
        _expect_error(answer, "step_before_reset", "sbr-1")


def _check_unsupported_format(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        if _NO_SUCH_FORMAT in hello.formats:
            _fail(f"the engine offers the probe format {_NO_SUCH_FORMAT!r}: the check cannot run")
        seats, rules = _mirror(hello, decks[0])
        answer = engine.send_raw(_reset_json("fmt-1", "g-conformance-format", _NO_SUCH_FORMAT, seats, rules))
        _expect_error(answer, "unsupported_format", "fmt-1")


def _check_unsupported_deck(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        if _NO_SUCH_DECK in {deck.catalog_id for deck in hello.catalog}:
            _fail(f"the engine's catalog holds the probe deck {_NO_SUCH_DECK!r}: the check cannot run")
        seat, rows = _wire_deck(hello, decks[0])
        bogus = WireDeck("sha256:" + "0" * 64, catalog_id=_NO_SUCH_DECK)
        rules = _rules([row["name"] for row in rows])
        answer = engine.send_raw(_reset_json("deck-1", "g-conformance-deck", format, (bogus, seat), rules))
        _expect_error(answer, "unsupported_deck", "deck-1")


def _check_unsupported_request(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """``probe_resample``: ``unsupported_request``, or ``probe_refused`` after a reset when the probe is declared."""
    with _open(argv) as engine:
        hello = engine.hello()
        if not hello.profile.fairness["noninterference_probe"]:
            answer = engine.send_raw({"request_type": "probe_resample", "protocol": PROTOCOL, "request_id": "probe-1",
                                      "game_id": "g-conformance-probe", "samples": 1})
            _expect_error(answer, "unsupported_request", "probe-1")
            return
        seats, rules = _mirror(hello, decks[0])
        engine.reset(ResetRequest.from_json(_reset_json("probe-1", "g-conformance-probe", format, seats, rules)))
        answer = engine.send_raw({"request_type": "probe_resample", "protocol": PROTOCOL, "request_id": "probe-2",
                                  "game_id": "g-conformance-probe", "samples": 1})
        _expect_error(answer, "probe_refused", "probe-2")


def _check_game_already_active(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        engine.reset(ResetRequest.from_json(_reset_json("active-1", "g-conformance-active", format, seats, rules)))
        answer = engine.send_raw(_reset_json("active-2", "g-conformance-other", format, seats, rules))
        _expect_error(answer, "game_already_active", "active-2")


def _check_game_id_mismatch(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        engine.reset(ResetRequest.from_json(_reset_json("gim-1", "g-conformance-mismatch", format, seats, rules)))
        answer = engine.send_raw(_step_json("gim-2", "g-conformance-other", 0, 0, {"kind": "pass"}))
        _expect_error(answer, "game_id_mismatch", "gim-2")


def _check_expected_step_mismatch(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        game_id = "g-conformance-step"
        engine.reset(ResetRequest.from_json(_reset_json("esm-1", game_id, format, seats, rules)))
        answer = engine.send_raw(_step_json("esm-2", game_id, 7, 0, {"kind": "pass"}))
        _expect_error(answer, "expected_step_mismatch", "esm-2")


def _check_candidate_id_out_of_range(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        game_id = "g-conformance-candidate"
        decision = engine.reset(ResetRequest.from_json(_reset_json("cid-1", game_id, format, seats, rules)))
        assert isinstance(decision, Decision)
        out_of_range = len(decision.seat_decision["candidates"])
        answer = engine.send_raw(_step_json("cid-2", game_id, 0, out_of_range, {"kind": "pass"}))
        _expect_error(answer, "candidate_id_out_of_range", "cid-2")


def _check_semantic_echo_mismatch(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        game_id = "g-conformance-echo"
        decision = engine.reset(ResetRequest.from_json(_reset_json("sem-1", game_id, format, seats, rules)))
        assert isinstance(decision, Decision)
        candidates = decision.seat_decision["candidates"]
        # Another offered candidate's semantic is a valid semantic under the wrong candidate id.
        semantic = candidates[1]["semantic"] if len(candidates) > 1 else {**candidates[0]["semantic"], "x_conformance": True}
        answer = engine.send_raw(_step_json("sem-2", game_id, 0, 0, semantic))
        _expect_error(answer, "semantic_echo_mismatch", "sem-2")


def _check_retransmission(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """The identical request returns the identical parsed answer; a changed payload is ``request_id_reuse_mismatch``."""
    with _open(argv) as engine:
        engine.hello()
        request = {"request_type": "validate_deck", "protocol": PROTOCOL, "request_id": "rt-1", "format": format,
                   "deck": {"catalog_id": decks[0]}}
        first = engine.send_raw(request)
        _expect_deck_ok(first, "rt-1")
        again = engine.send_raw(request)
        if again != first:
            _fail("the identical request was not answered with the identical parsed answer (spec 4.1)")
        changed = dict(request, deck={"catalog_id": _NO_SUCH_DECK})
        _expect_error(engine.send_raw(changed), "request_id_reuse_mismatch", "rt-1")


def _check_game_already_terminal(argv: Sequence[str], *, format: str, decks: Sequence[str]) -> None:
    """A step after the terminal is ``game_already_terminal`` (a first-candidate game, max_steps 2000)."""
    with _open(argv) as engine:
        hello = engine.hello()
        seats, rules = _mirror(hello, decks[0])
        game_id = "g-conformance-terminal"
        terminal = _play_first(engine, _reset_json("gat-1", game_id, format, seats, rules), max_steps=2000)
        answer = engine.send_raw(_step_json("gat-2", game_id, terminal.result.step_count, 0, {"kind": "pass"}))
        _expect_error(answer, "game_already_terminal", "gat-2")


def _check_games(argv: Sequence[str], *, format: str, decks: Sequence[str], games: int) -> None:
    """``games`` full games (builtin ``first`` against ``uniform``, seat-swapped, the decks in turn)."""
    # The pool constraint: pairs_per_matchup is a multiple of the pool size, and covers ``games`` seat-swapped games.
    pairs = len(decks) * max(1, -(-games // (2 * len(decks))))
    config = TournamentConfig.from_json(
        {
            "schema": CONFIG_SCHEMA,
            "tournament_dir": "unused",  # preflight, schedule and play_game write nothing
            "format": format,
            "deck_pool": [{"catalog_id": deck} for deck in decks],
            "engine": {"command": list(argv)},
            "bots": [
                {"name": "first", "version": BUILTIN_VERSIONS["first"], "type": "builtin"},
                {"name": "uniform", "version": BUILTIN_VERSIONS["uniform"], "type": "builtin"},
            ],
            "pairs_per_matchup": pairs,
            "stats_seed": 0,
            "include_self_play": False,
        }
    )
    run_secret = RunSecret.generate()
    setup = preflight(config, run_secret)
    for context in schedule(config, run_secret)[:games]:
        result = _play_context(config, setup, context, run_secret)
        if result.classification == "forfeit" or (
            result.classification == "halted" and result.reason.startswith(_HOST_HALT_PREFIXES)
        ):
            _fail(f"game {context.game_index} ended {result.classification}: {result.reason}")


def _play_context(config: TournamentConfig, setup: RunSetup, context: GameContext, run_secret: RunSecret) -> GameResult:
    """One scheduled game on a fresh engine process with builtin drivers; the caller judges the result."""
    engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
    seats = {seat: BuiltinDriver(spec) for seat, spec in context.seat_specs}
    try:
        engine.hello()
        return play_game(game_setup(config, setup, context, run_secret), engine=engine, seats=seats)
    finally:
        engine.close()
        for driver in seats.values():
            driver.close()


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

_PROBES: tuple[tuple[str, Callable[..., None]], ...] = (
    ("hello", _check_hello),
    ("protocol_mismatch", _check_protocol_mismatch),
    ("malformed_json", _check_malformed_json),
    ("malformed_request", _check_malformed_request),
    ("malformed_request_non_object", _check_malformed_request_non_object),
    ("unsupported_rule", _check_unsupported_rule),
    ("game_id_reuse", _check_game_id_reuse),
    ("never_cached", _check_never_cached),
    ("step_check_order", _check_step_check_order),
    ("step_before_reset", _check_step_before_reset),
    ("unsupported_format", _check_unsupported_format),
    ("unsupported_deck", _check_unsupported_deck),
    ("unsupported_request", _check_unsupported_request),
    ("game_already_active", _check_game_already_active),
    ("game_id_mismatch", _check_game_id_mismatch),
    ("expected_step_mismatch", _check_expected_step_mismatch),
    ("candidate_id_out_of_range", _check_candidate_id_out_of_range),
    ("semantic_echo_mismatch", _check_semantic_echo_mismatch),
    ("retransmission", _check_retransmission),
    ("game_already_terminal", _check_game_already_terminal),
)


def _run(name: str, probe: Callable[..., None], argv: Sequence[str], **kwargs: Any) -> CheckResult:
    """One check: an exception inside it is that check's failure, never the runner's."""
    try:
        probe(argv, **kwargs)
    except _CheckFailure as exc:
        return CheckResult(name, False, str(exc))
    except Exception as exc:  # noqa: BLE001 - the engine's failure modes are what a check reports
        return CheckResult(name, False, f"{type(exc).__name__}: {exc}")
    return CheckResult(name, True, "")


def check_engine(argv: Sequence[str], *, format: str, decks: Sequence[str], games: int = 4) -> ConformanceReport:
    """Run every conformance check against ``argv``'s engine; each check in a fresh engine process."""
    if not decks:
        raise ValueError("check_engine needs at least one deck")
    if games < 1:
        raise ValueError("check_engine needs at least one game")
    checks = [_run(name, probe, argv, format=format, decks=decks) for name, probe in _PROBES]
    checks.append(_run("games", _check_games, argv, format=format, decks=decks, games=games))
    return ConformanceReport(tuple(checks))


# ---------------------------------------------------------------------------
# Golden transcript replay
# ---------------------------------------------------------------------------


def _transcript_pairs(path: Path) -> list[tuple[Any, Any]]:
    """The transcript's (request message, expected answer message) pairs, in row order."""
    rows = []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        row = wire.strict_json_loads(line)
        if set(row) != {"dir", "message"} or row["dir"] not in ("host_to_engine", "engine_to_host"):
            raise ValueError(f"{path}:{number}: a transcript row is exactly {{'dir', 'message'}} with a known direction")
        rows.append((row["dir"], row["message"]))
    pairs: list[tuple[Any, Any]] = []
    index = 0
    while index < len(rows):
        direction, message = rows[index]
        if direction != "host_to_engine":
            raise ValueError(f"{path}: row {index + 1}: expected a host_to_engine row, got {direction}")
        expected: Any = _NO_ANSWER
        if index + 1 < len(rows) and rows[index + 1][0] == "engine_to_host":
            expected = rows[index + 1][1]
            index += 1
        pairs.append((message, expected))
        index += 1
    return pairs


def replay_engine_transcript(argv: Sequence[str], path: Path) -> list[str]:
    """Send every ``host_to_engine`` row of a golden transcript to a fresh engine; the mismatches found.

    Each answer is compared with its ``engine_to_host`` row as parsed JSON. A row whose ``message``
    is a string is written as its UTF-8 bytes unchanged; every other row as canonical JSON (R3-11).
    """
    mismatches: list[str] = []
    engine = _open(argv)
    try:
        for number, (message, expected) in enumerate(_transcript_pairs(path), 1):
            where = f"exchange {number}"
            if isinstance(message, dict) and "request_id" in message:
                where += f" (request_id {message['request_id']!r})"
            payload = message.encode("utf-8") if isinstance(message, str) else wire.canonical_json_dumps(message)
            try:
                answer = engine.send_line(payload)
            except Exception as exc:  # noqa: BLE001 - an engine that cannot answer strictly is the mismatch
                mismatches.append(f"{where}: the engine did not answer with a strict JSON object: {exc}")
                break
            if expected is _NO_ANSWER:
                mismatches.append(f"{where}: the transcript holds no engine_to_host row, but the engine answered")
                continue
            if isinstance(expected, str):
                try:
                    expected = wire.strict_json_loads(expected.encode("utf-8"))
                except MalformedJsonError as exc:
                    mismatches.append(f"{where}: the engine_to_host row is a raw line that is not strict JSON: {exc}")
                    continue
            if answer != expected:
                mismatches.append(
                    f"{where}: expected {wire.canonical_json_dumps(expected).decode('utf-8')}, "
                    f"got {wire.canonical_json_dumps(answer).decode('utf-8')}"
                )
    finally:
        engine.close()
    return mismatches
