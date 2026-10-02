"""Replay the v2 goldens in both roles (spec 16).

Each golden's ``roles`` in ``index.json`` name the replays that apply to it (Decision 7), and each replay runs for
exactly those transcripts:

- ``host``: the host plays the game again from the recorded engine and agent answers, and must write every host row
  byte for byte, in the transcript's order, and reach the recorded game digest.
- ``bot_server``: the reference bot server (``BotSession``), playing the bot each seat's ``hello_ok`` names, must give
  every agent answer byte for byte.
- ``engine``: the listed engine, started with its arguments, must give every engine answer by value
  (``conformance.replay_engine_transcript``), so a child's ``\\r\\n`` line ends never matter.

A replay reads as little as it can from the rows it checks. The host replay takes the game's id, secret and agent
seeds from the spec 16 vector secret (game 0, as the index notes say) and the bots' version from ``BOT_VERSION``; the
rest of its setup comes from the reset and game_start rows, and the host writes each of those values again in another
row or into the digest, so a changed one still shows. The bot server replay plays the policy of the bot each hello_ok
names (``BOTS``), never the recorded picks.

Every replay reads the goldens when it runs (``golden_helpers.GOLDENS_V2_DIR``), so the tests at the end point it at a
corrupted copy and show that it notices. The index must list every replay a transcript's rows allow, each listed
replay must be parametrized, and each must run to its end.
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from spellbench import wire
from spellbench._schema import SEATS
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.bot import BotSession, Decision as BotDecision
from spellbench.conformance import replay_engine_transcript
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.messages import Limits, ResetRequest, Resources, TimeControl
from spellbench.run_secret import RunSecret

import fake_v2_scenario_kinds
import golden_helpers
from conftest import ScriptedPeer
from golden_helpers import golden_index, load_transcript_v2

TESTS = Path(__file__).resolve().parent
INDEX = golden_index()                            # the committed index, read once to parametrize the replays
ROLES = ("host", "bot_server", "engine")
SECRET = RunSecret(bytes(range(32)))              # spec 16's vector run secret: every game golden is its game 0
BOT_VERSION = "1.0.0"                             # every golden bot's; none declares a requirement or an extension


def _first_land(decision: BotDecision) -> int:
    return next((c.candidate_id for c in decision.candidates if c.semantic.get("kind") == "play_land"), 0)


# The goldens' bots (tools/generate_goldens_v2.py) by the name a seat's hello_ok gives, each a policy the reference
# bot server plays. golden-nine answers every choose by hand with a candidate no decision offers, an answer the
# reference bot server refuses to send, so no bot server replays it (its game lists no bot_server role).
BOTS: dict[str, Callable[[BotDecision], int] | None] = {
    "golden-first": lambda decision: 0,
    "golden-lands": _first_land,
    "golden-last": lambda decision: decision.candidates[-1].candidate_id,
    "golden-kinds-tour": lambda decision: fake_v2_scenario_kinds.pick(decision.raw["decision"]),
    "golden-unoffered": lambda decision: 99,     # agent_error_internal_error: a candidate_id never offered (R3-26)
    "golden-nine": None,
}


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One transcript row: its line number, its direction and message, and the line exactly as the golden holds it."""

    number: int
    direction: str
    message: Any
    line: bytes


def _rows(name: str) -> list[Row]:
    lines = (golden_helpers.GOLDENS_V2_DIR / name).read_bytes().splitlines()
    return [Row(number, direction, message, line)
            for number, ((direction, message), line) in enumerate(zip(load_transcript_v2(name), lines), 1)]


def _line(direction: str, payload: bytes) -> bytes:
    """The transcript line holding ``payload`` unchanged (canonical JSON orders ``dir`` before ``message``)."""
    return b'{"dir":"%s","message":%s}' % (direction.encode("ascii"), payload)


def _difference(number: int, golden: bytes, replayed: bytes, who: str) -> str:
    """Where ``replayed`` first differs from the golden's line ``number``, with a little of each around it."""
    at = next((i for i, (a, b) in enumerate(zip(golden, replayed)) if a != b), min(len(golden), len(replayed)))

    def near(line: bytes) -> str:
        return repr(line[max(0, at - 30):at + 30].decode("utf-8", errors="replace"))

    return f"line {number}, byte {at}: {who} {near(replayed)} where the golden has {near(golden)}"


def _entry(name: str, role: str) -> dict[str, Any]:
    """The golden's index entry, read now: a replay runs only for a transcript whose roles name it (Decision 7)."""
    entry = golden_index()[name]
    if role not in entry["roles"]:
        raise ValueError(f"index.json lists no {role} replay for {name}")
    return entry


def _agent_exchanges(rows: list[Row]) -> list[tuple[Row, Row]]:
    """The agent rows as (request, answer) pairs, each request answered by the next agent row (spec 2)."""
    pairs: list[tuple[Row, Row]] = []
    pending: Row | None = None
    for row in rows:
        if row.direction == "host_to_agent":
            if pending is not None:
                raise ValueError(f"line {pending.number}: a request with no answer before line {row.number}")
            pending = row
        elif row.direction == "agent_to_host":
            if pending is None:
                raise ValueError(f"line {row.number}: an answer with no request before it")
            pairs.append((pending, row))
            pending = None
    if pending is not None:
        raise ValueError(f"line {pending.number}: a request with no answer")
    return pairs


def exchanges_by_seat(rows: list[Row]) -> dict[str, list[tuple[Row, Row]]]:
    """A game's (request, answer) pairs per seat: hellos and game_overs go p0 then p1 (the index notes), game_start
    names its seat, choose its acting seat."""
    by_seat: dict[str, list[tuple[Row, Row]]] = {seat: [] for seat in SEATS}
    hellos = overs = 0
    for request, answer in _agent_exchanges(rows):
        kind = request.message["request_type"]
        if kind == "hello":
            seat, hellos = SEATS[hellos], hellos + 1
        elif kind == "game_start":
            seat = request.message["seat"]
        elif kind == "choose":
            seat = request.message["decision"]["acting_seat"]
        else:
            seat, overs = SEATS[overs], overs + 1
        by_seat[seat].append((request, answer))
    return by_seat


# ---------------------------------------------------------------------------
# The three replays: each returns every difference it finds, and raises ValueError for a transcript it cannot replay
# ---------------------------------------------------------------------------

FINISHED: set[tuple[str, str, Path]] = set()     # (role, name, goldens directory) of every replay that ran to its end


def _finished(role: str, name: str, problems: list[str]) -> list[str]:
    FINISHED.add((role, name, golden_helpers.GOLDENS_V2_DIR))
    return problems


class _Transcript:
    """The lines the host replay writes and reads, in the goldens' order (the index notes).

    The host starts both seats at once, each on its own thread, so a row a seat logs off the test's thread waits for
    the next row logged on it, and the waiting rows go in p0's first; every other row goes in as it crossed its pipe.
    """

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.starts: dict[str, list[bytes]] = {seat: [] for seat in SEATS}
        self.thread = threading.get_ident()

    def log(self, channel: str, line: bytes) -> None:
        if threading.get_ident() != self.thread:
            self.starts[channel].append(line)
            return
        self.done()
        self.lines.append(line)

    def done(self) -> list[bytes]:
        for seat in SEATS:
            self.lines.extend(self.starts[seat])
            self.starts[seat].clear()
        return self.lines


class _Recorded(ScriptedPeer):
    """A peer that answers with one channel's recorded answers and logs every line written and read."""

    def __init__(self, answers: list[Row], transcript: _Transcript, channel: str, out_dir: str, in_dir: str) -> None:
        super().__init__([wire.canonical_json_dumps(row.message) for row in answers])
        self.transcript, self.channel, self.out_dir, self.in_dir = transcript, channel, out_dir, in_dir

    def write_line(self, data: bytes) -> None:
        super().write_line(data)
        self.transcript.log(self.channel, _line(self.out_dir, data))

    def read_line(self) -> bytes:
        line = super().read_line()
        self.transcript.log(self.channel, _line(self.in_dir, line))
        return line


def setup_from(rows: list[Row]) -> GameSetup:
    """The game's bindings: game 0 of the vector secret, and the decks, rules, clocks, caps and resources its rows name.

    Each value read from a row comes back in another the host writes (the other seat's game_start, the reset's
    limits) or in the digest (the reset's decks), so a changed one still shows.
    """
    reset = ResetRequest.from_json(next(row.message for row in rows if row.direction == "host_to_engine"
                                        and row.message["request_type"] == "reset"))
    starts = {row.message["seat"]: row.message for row in rows if row.direction == "host_to_agent"
              and row.message["request_type"] == "game_start"}
    first = starts["p0"]
    return GameSetup(game_index=0, game_id=SECRET.game_id(0), game_secret_hex=SECRET.game_secret(0).hex(),
                     format=reset.format, wire_decks=reset.seats,
                     own_decks=tuple(OwnDeck.from_json(starts[seat]["own_deck"]) for seat in SEATS),
                     rules=reset.rules, time_control=TimeControl.from_json(first["time_control"]),
                     limits=Limits.from_json(first["limits"]), resources=Resources.from_json(first["resources"]),
                     agent_seeds=(SECRET.agent_seed(0, "p0"), SECRET.agent_seed(0, "p1")))


def replay_host(name: str) -> list[str]:
    """Play the game again from its recorded answers; where the host's transcript or digest differs from the golden."""
    entry, rows = _entry(name, "host"), _rows(name)
    transcript = _Transcript()
    engine = EngineProcess(peer=_Recorded([row for row in rows if row.direction == "engine_to_host"], transcript,
                                          "engine", "host_to_engine", "engine_to_host"))
    seats = {}
    for seat, pairs in exchanges_by_seat(rows).items():
        peer = _Recorded([answer for _, answer in pairs], transcript, seat, "host_to_agent", "agent_to_host")
        bot = next(answer.message["bot"]["name"] for request, answer in pairs
                   if request.message["request_type"] == "hello")
        if bot not in BOTS:
            raise ValueError(f"{name}: {seat}'s hello_ok names {bot!r}, not one of the goldens' bots")
        spec = BotSpec(name=bot, version=BOT_VERSION, type="subprocess", command=("recorded",))
        seats[seat] = SubprocessDriver(spec, startup_ms=30_000, agent_factory=lambda peer=peer: AgentProcess(peer=peer))
    engine.hello()
    result = play_game(setup_from(rows), engine=engine, seats=seats, clock_ns=lambda: 0)
    lines = transcript.done()
    problems = [_difference(row.number, row.line, line, "the host replay has")
                for row, line in zip(rows, lines) if line != row.line][:1]      # the first: later rows follow from it
    if len(lines) != len(rows):
        problems.append(f"the host replay has {len(lines)} rows, the golden {len(rows)}")
    if result.game_digest != entry["game_digest"]:
        problems.append(f"the game digest is {result.game_digest}, the index records {entry['game_digest']}")
    return _finished("host", name, problems)


def _bot_session(pairs: list[tuple[Row, Row]]) -> BotSession:
    """The reference bot server playing the bot the session's hello_ok names. A session whose hello is refused names
    no bot and has no answer a bot could change, so it plays golden-first."""
    names = [answer.message["bot"]["name"] for _, answer in pairs if answer.message.get("response_type") == "hello_ok"]
    name = names[0] if names else "golden-first"
    policy = BOTS.get(name)
    if policy is None:
        raise ValueError(f"{name!r} is not a bot the reference bot server plays")
    return BotSession(choose=policy, name=name, version=BOT_VERSION)


def _bot_sessions(rows: list[Row]) -> list[tuple[BotSession, list[tuple[Row, Row]]]]:
    """A bot server per agent session (one per seat in a game) and its exchanges; ValueError for agent rows the
    reference bot server cannot answer."""
    if any(row.direction == "host_to_engine" for row in rows):
        sessions = list(exchanges_by_seat(rows).values())
    else:
        sessions = [_agent_exchanges(rows)]                  # an agent error golden: one session
    return [(_bot_session(pairs), pairs) for pairs in sessions]


def replay_bot_server(name: str) -> list[str]:
    """Answer every recorded request with the reference bot server; each answer that differs from the golden's line."""
    _entry(name, "bot_server")
    rows = _rows(name)
    problems, answered = [], 0
    for session, pairs in _bot_sessions(rows):
        for request, answer in pairs:
            # A string row is the offending line itself, sent unchanged (Decision 7).
            line = request.message.encode("utf-8") if isinstance(request.message, str) \
                else wire.canonical_json_dumps(request.message)
            given = _line("agent_to_host", wire.strip_line_terminator(session.handle_line(line)))
            answered += 1
            if given != answer.line:
                problems.append(_difference(answer.number, answer.line, given, "the bot server gave"))
    recorded = sum(row.direction == "agent_to_host" for row in rows)
    if not answered or answered != recorded:
        problems.append(f"the bot server gave {answered} answers, the golden records {recorded}")
    return _finished("bot_server", name, problems)


def replay_engine(name: str) -> list[str]:
    """Replay the engine rows in the engine the index lists, started with its arguments (spec 16)."""
    entry = _entry(name, "engine")
    if not any(row.direction == "engine_to_host" for row in _rows(name)):
        return [f"{name} records no engine answer to replay"]
    argv = [sys.executable, str(TESTS / entry["engine"]), *entry["engine_args"]]
    return _finished("engine", name, replay_engine_transcript(argv, golden_helpers.GOLDENS_V2_DIR / name))


# ---------------------------------------------------------------------------
# Every replay the index lists
# ---------------------------------------------------------------------------

REPLAYS = {role: sorted(name for name, entry in INDEX.items() if role in entry["roles"]) for role in ROLES}


@pytest.mark.parametrize("name", REPLAYS["host"])
def test_the_host_replays_every_game_byte_for_byte(name: str) -> None:
    assert replay_host(name) == []


@pytest.mark.parametrize("name", REPLAYS["bot_server"])
def test_the_bot_server_replays_every_answer_byte_for_byte(name: str) -> None:
    assert replay_bot_server(name) == []


@pytest.mark.parametrize("name", REPLAYS["engine"])
def test_the_fake_engine_replays_every_engine_answer(name: str) -> None:
    assert replay_engine(name) == []


REPLAY_TESTS = {test_the_host_replays_every_game_byte_for_byte: "host",
                test_the_bot_server_replays_every_answer_byte_for_byte: "bot_server",
                test_the_fake_engine_replays_every_engine_answer: "engine"}


def _replays_allowed(rows: list[Row]) -> list[str]:
    """The replays a transcript's rows allow: the engine replay for engine rows, the host replay for a game (engine and
    agent rows), the bot server replay for agent rows the reference bot server can answer."""
    directions = {row.direction for row in rows}
    roles = []
    if "engine_to_host" in directions:
        roles += ["engine", "host"] if "agent_to_host" in directions else ["engine"]
    if "agent_to_host" in directions:
        try:
            _bot_sessions(rows)
            roles.append("bot_server")
        except ValueError:
            pass
    return sorted(roles)


def _unreplayed() -> list[str]:
    """How the replays fall short of the goldens as they read now: a transcript whose index entry lists fewer (or
    other) replays than its rows allow, a role no test replays or that no transcript lists (its test would pass as a
    skip), or a replay test parametrized otherwise than the index lists, per role."""
    index = golden_index()
    problems = []
    for name, entry in index.items():
        allowed = _replays_allowed(_rows(name))
        if sorted(entry["roles"]) != allowed:
            problems.append(f"{name}: index.json lists {entry['roles']}, its rows allow {allowed}")
    problems += [f"index.json lists the role {role!r}, which no test replays"
                 for role in sorted({role for entry in index.values() for role in entry["roles"]} - set(ROLES))]
    listed = {role: sorted(name for name, entry in index.items() if role in entry["roles"]) for role in ROLES}
    problems += [f"index.json lists no transcript for {role}" for role in ROLES if not listed[role]]
    replayed = {}
    for test, role in REPLAY_TESTS.items():
        (mark,) = [mark for mark in test.pytestmark if mark.name == "parametrize"]
        replayed[role] = sorted(mark.args[1])
    counts = [{role: len(names[role]) for role in ROLES} for names in (replayed, listed)]
    if counts[0] != counts[1]:
        problems.append(f"replays per role: the tests run {counts[0]}, index.json lists {counts[1]}")
    problems += [f"{role}: the tests replay {replayed[role]}, index.json lists {listed[role]}"
                 for role in ROLES if replayed[role] != listed[role]]
    return problems


def test_every_replay_the_goldens_allow_is_listed_and_parametrized() -> None:
    assert _unreplayed() == []


def test_no_replay_stopped_before_its_checks(request: pytest.FixtureRequest) -> None:
    """A replay that stopped before its checks would pass silently, so each records that it finished; every replay
    this session ran before this test (all of them, in a module's own order) must have."""
    if hasattr(request.config, "workerinput"):
        pytest.skip("an xdist worker runs only some of the items before this one")
    items = request.session.items
    selected = {(REPLAY_TESTS[item.function], item.callspec.params["name"])
                for item in items[:items.index(request.node)] if getattr(item, "function", None) in REPLAY_TESTS}
    finished = {(role, name) for role, name, where in FINISHED if where == golden_helpers.GOLDENS_V2_DIR}
    assert sorted(selected - finished) == []


# ---------------------------------------------------------------------------
# The replays notice a corrupted golden (in a copy: the committed goldens stay as they are)
# ---------------------------------------------------------------------------

SCORING = "game_scoring.transcript.jsonl"


@pytest.fixture()
def copy_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Copy the named goldens and the index to where every replay will read them; returns that directory."""

    def copy(*names: str) -> Path:
        for file in (*names, "index.json"):
            shutil.copyfile(golden_helpers.GOLDENS_V2_DIR / file, tmp_path / file)
        monkeypatch.setattr(golden_helpers, "GOLDENS_V2_DIR", tmp_path)
        return tmp_path

    return copy


def _write_lines(path: Path, lines: list[bytes]) -> None:
    path.write_bytes(b"".join(line + b"\n" for line in lines))


def _edit_row(path: Path, number: int, change: Callable[[Any], None]) -> None:
    """Change row ``number``'s message in place, keeping every line canonical."""
    lines = path.read_bytes().splitlines()
    row = wire.strict_json_loads(lines[number - 1])
    change(row["message"])
    lines[number - 1] = wire.canonical_json_dumps(row)
    _write_lines(path, lines)


def _edit_index(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    index = wire.strict_json_loads(path.read_bytes())
    change(index["transcripts"])
    path.write_bytes(wire.canonical_json_line(index))


def _number(rows: list[Row], direction: str, kind: str) -> int:
    """The line number of the first row in ``direction`` whose request or response type is ``kind``."""
    return next(row.number for row in rows if row.direction == direction
                and (row.message.get("request_type") or row.message.get("response_type")) == kind)


def test_the_host_replay_notices_one_changed_byte_of_a_host_row(copy_of: Callable[..., Path]) -> None:
    path = copy_of(SCORING) / SCORING
    number = _number(_rows(SCORING), "host_to_agent", "choose")
    lines = path.read_bytes().splitlines()
    assert lines[number - 1].count(b'"remaining_ms":600000}') == 1
    lines[number - 1] = lines[number - 1].replace(b'"remaining_ms":600000}', b'"remaining_ms":600001}')
    _write_lines(path, lines)
    (problem,) = replay_host(SCORING)
    assert problem.startswith(f"line {number}, byte ")


def test_the_host_replay_notices_a_changed_digest(copy_of: Callable[..., Path]) -> None:
    goldens = copy_of(SCORING)
    recorded = INDEX[SCORING]["game_digest"]
    changed = recorded[:-1] + ("1" if recorded.endswith("0") else "0")
    _edit_index(goldens / "index.json", lambda transcripts: transcripts[SCORING].update(game_digest=changed))
    assert replay_host(SCORING) == [f"the game digest is {recorded}, the index records {changed}"]


def test_the_replays_notice_a_changed_agent_answer(copy_of: Callable[..., Path]) -> None:
    """p0 (golden-lands) plays a land first; recorded as passing instead, the host's step differs, and so does the
    bot server's answer."""
    path = copy_of(SCORING) / SCORING
    rows = _rows(SCORING)
    number = _number(rows, "agent_to_host", "choice")
    assert rows[number - 1].message["selection"]["candidate_id"] == 1
    _edit_row(path, number, lambda message: message["selection"].update(candidate_id=0))
    host = replay_host(SCORING)
    assert host[0].startswith(f"line {_number(rows, 'host_to_engine', 'step')}, byte ")
    assert host[-1].startswith("the game digest is ")
    assert [problem.split(",")[0] for problem in replay_bot_server(SCORING)] == [f"line {number}"]


def test_the_replays_notice_a_changed_engine_answer(copy_of: Callable[..., Path]) -> None:
    """The first decision recorded with p1 at 19 life: the engine gives 20, and the host forwards the 19 it read."""
    path = copy_of(SCORING) / SCORING
    number = _number(_rows(SCORING), "engine_to_host", "decision")

    def lose_a_life(message: dict[str, Any]) -> None:
        p1 = message["seat_decision"]["observation"]["players"][1]
        assert (p1["seat"], p1["life"]) == ("p1", 20)
        p1["life"] = 19

    _edit_row(path, number, lose_a_life)
    (engine,) = replay_engine(SCORING)
    assert engine.startswith(f"line {number}: the answer to reset ")
    host = replay_host(SCORING)
    assert host[0].startswith(f"line {number + 1}, byte ") and host[-1].startswith("the game digest is ")


def test_the_replays_notice_a_dropped_row(copy_of: Callable[..., Path]) -> None:
    """Without p1's last ack, the host and bot server replays refuse a request with no answer; without the first
    decision, the host reads the next one as the answer to reset, and the engine replay refuses the transcript."""
    path = copy_of(SCORING) / SCORING
    lines = path.read_bytes().splitlines()
    _write_lines(path, lines[:-1])
    for replay in (replay_host, replay_bot_server):
        with pytest.raises(ValueError, match=f"^line {len(lines) - 1}: a request with no answer$"):
            replay(SCORING)
    dropped = _number(_rows(SCORING), "engine_to_host", "decision")
    _write_lines(path, [line for number, line in enumerate(lines, 1) if number != dropped])
    assert replay_host(SCORING)[0].startswith(f"line {dropped}, byte ")
    engine_rows = [row.number for row in _rows(SCORING) if row.direction in ("host_to_engine", "engine_to_host")]
    reset, following = [number for number in engine_rows if number >= dropped - 1][:2]
    with pytest.raises(ValueError, match=re.escape(f"line {reset}: the request has no engine answer before line "
                                                   f"{following}")):
        replay_engine(SCORING)


def test_a_role_the_index_drops_is_noticed(copy_of: Callable[..., Path]) -> None:
    """An index that lists fewer replays than a transcript's rows allow: the replay refuses the transcript, and the
    coverage check names it and the role counts that no longer match."""
    goldens = copy_of(*INDEX)
    _edit_index(goldens / "index.json", lambda transcripts: transcripts[SCORING]["roles"].remove("engine"))
    with pytest.raises(ValueError, match="^" + re.escape(f"index.json lists no engine replay for {SCORING}") + "$"):
        replay_engine(SCORING)
    problems = _unreplayed()
    assert problems[0] == f"{SCORING}: index.json lists ['bot_server', 'host'], its rows allow " \
                          "['bot_server', 'engine', 'host']"
    assert [problem.split(":")[0] for problem in problems[1:]] == ["replays per role", "engine"]
