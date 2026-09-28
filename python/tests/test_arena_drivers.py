"""Builtin and subprocess seat drivers."""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from spellbench.agent_messages import Choice
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import BuiltinDriver, SubprocessDriver, bot_environment, make_driver
from spellbench.bot import BotSession
from spellbench.builtins.uniform import UniformBot
from spellbench.errors import TransportError, ValidationError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.seat import SeatFailure
from spellbench.messages import TimeControl

MINIMAL = Path(__file__).resolve().parents[2] / "examples" / "minimal_bot.py"
DECISION = {"acting_seat": "p0", "seat_step": 0, "candidates": [
    {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None},
    {"candidate_id": 1, "semantic": {"kind": "play_land", "face": 0}, "display_text": None}]}
CHOOSE = {"game_id": "g-1", "decision": DECISION, "clock": {"remaining_ms": 1000, "max_decision_ms": 1000}}
START = {"game_id": "g-1", "seat": "p0", "agent_seed": 42}
OVER = {"game_id": "g-1", "terminal": {"outcome": "p0_win", "classification": "natural", "winner": "p0",
                                       "reason": "p1_life_zero", "seat_step_count": 1}}
# 24 decisions of 2 to 6 candidates: enough for seeded picks to tell seeds apart.
CHOICES = [{**CHOOSE, "decision": {"acting_seat": "p0", "seat_step": step, "candidates": [
    {"candidate_id": index, "semantic": {"kind": "play_land", "face": index}, "display_text": None}
    for index in range(2 + step % 5)]}} for step in range(24)]
CLOCKS = TimeControl(startup_ms=1_000, game_start_ms=60_000, bank_ms=600_000, increment_ms=2_000,
                     max_decision_ms=60_000, engine_step_ms=120_000)
# A bot process that never answers hello: it exits when its stdin closes, or after 5 s at the latest.
SILENT = (sys.executable, "-c",
          "import os, sys, threading; threading.Timer(5, os._exit, (0,)).start(); sys.stdin.buffer.read(); os._exit(0)")
STARTUP_S = 30.0


def builtin(name: str) -> BotSpec:
    return BotSpec(name=name, version="2.0.0", type="builtin")


class SessionPeer:
    """A bot process in process: a ``BotSession`` answers each request line, as ``serve`` would."""

    def __init__(self, session: BotSession) -> None:
        self.session = session
        self.requests: list[str] = []                    # the request_type of every line written, in order
        self.timeouts: dict[str, float | None] = {}      # the budget each request type was sent under
        self.closed = False
        self._budget: float | None = None
        self._answers: list[bytes] = []

    def set_timeout(self, timeout_s: float | None) -> None:
        self._budget = timeout_s

    def write_line(self, payload: bytes) -> None:
        if self.closed:
            raise TransportError("peer is closed")
        request_type = json.loads(payload)["request_type"]
        self.requests.append(request_type)
        self.timeouts[request_type] = self._budget
        self._answers.append(self.session.handle_line(payload).rstrip(b"\n"))

    def read_line(self) -> bytes:
        return self._answers.pop(0)

    def close(self) -> None:
        self.closed = True


class InProcessBots:
    """An ``agent_factory`` whose every process is a ``SessionPeer``; ``peers`` keeps them in start order."""

    def __init__(self, *, name: str = "minimal", version: str = "1.0.0", **hooks: Any) -> None:
        self._session = {"choose": lambda decision: 0, "name": name, "version": version, **hooks}
        self.peers: list[SessionPeer] = []

    def __call__(self) -> AgentProcess:
        self.peers.append(SessionPeer(BotSession(**self._session)))
        return AgentProcess(peer=self.peers[-1], startup_timeout_s=STARTUP_S)


def served(bots: InProcessBots, *, name: str = "minimal", version: str = "1.0.0") -> SubprocessDriver:
    """A subprocess driver for the config entry ``name`` ``version``, its processes run in process by ``bots``."""
    spec = BotSpec(name=name, version=version, type="subprocess", command=("unused",))
    return SubprocessDriver(spec, startup_ms=1_000, agent_factory=bots)


class Recorder:
    """A bot that keeps the raw view of every request it reads."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def on_game_start(self, game) -> None:
        self.seen.append(game.raw)

    def choose(self, decision) -> int:
        self.seen.append(decision.raw)
        return 0

    def on_game_over(self, game_over) -> None:
        self.seen.append(game_over.raw)


def play(driver: Any, *, agent_seed: int = 42) -> list[int]:
    """One game of CHOICES on ``driver``; the candidate ids it answered."""
    driver.start({**START, "agent_seed": agent_seed}, timeout_s=5)
    picks = [driver.choose(choose, timeout_s=5).candidate_id for choose in CHOICES]
    driver.game_over(OVER, timeout_s=5)
    return picks


# -- the brief's tests -------------------------------------------------------------------------------


def test_builtin_bots_play_and_cannot_mutate_the_host_copy() -> None:
    class Mutator:
        def on_game_start(self, game): pass
        def choose(self, decision):
            decision.raw["decision"]["candidates"].clear()
            return 1
        def on_game_over(self, game_over): pass

    driver = BuiltinDriver(builtin("first"), factory=Mutator)
    driver.start(START, timeout_s=5)
    assert driver.choose(CHOOSE, timeout_s=5).candidate_id == 1
    assert len(CHOOSE["decision"]["candidates"]) == 2
    heuristic = BuiltinDriver(builtin("heuristic"))
    heuristic.start(START, timeout_s=5)
    assert heuristic.choose(CHOOSE, timeout_s=5).candidate_id == 1


@pytest.mark.parametrize(
    ("choose", "cause"),
    [(lambda decision: time.sleep(5), "timeout"), (lambda decision: 1 / 0, "agent_error"), (lambda decision: "1", "malformed_response"),
     (lambda decision: True, "malformed_response")],
)
def test_builtin_failures(choose, cause: str) -> None:
    class Bot:
        def on_game_start(self, game): pass
        def on_game_over(self, game_over): pass

    Bot.choose = staticmethod(choose)
    driver = BuiltinDriver(builtin("first"), factory=Bot)
    driver.start(START, timeout_s=5)
    with pytest.raises(SeatFailure) as caught:
        driver.choose(CHOOSE, timeout_s=0.3)
    assert caught.value.cause == cause


def test_a_subprocess_bot_per_game() -> None:
    spec = BotSpec(name="minimal", version="1.0.0", type="subprocess", command=(sys.executable, str(MINIMAL)))
    driver = SubprocessDriver(spec, startup_ms=30_000)
    try:
        driver.start(START, timeout_s=30)
        assert driver.choose(CHOOSE, timeout_s=30).candidate_id == 0
        driver.game_over({"game_id": "g-1", "terminal": {}}, timeout_s=30)
    finally:
        driver.close()


def test_a_subprocess_bot_must_name_its_config_entry() -> None:
    spec = BotSpec(name="someone-else", version="1.0.0", type="subprocess", command=(sys.executable, str(MINIMAL)))
    driver = SubprocessDriver(spec, startup_ms=30_000)
    try:
        with pytest.raises(SeatFailure, match="different bot"):
            driver.start(START, timeout_s=30)
    finally:
        driver.close()


def test_a_subprocess_bot_never_sees_spellbench_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPELLBENCH_SECRETS_DIR", str(tmp_path / "secrets"))         # where a committed run keeps its secret
    monkeypatch.setenv("SPELLBENCH_PIN_ROOT", str(tmp_path / "pins"))               # and the other local values (R3-9)
    monkeypatch.setenv("SPELLBENCH_ARTIFACT_REGISTER", str(tmp_path / "register.jsonl"))
    bot = tmp_path / "env_bot.py"
    bot.write_text("import os, sys\nfrom spellbench.bot import serve\n"
                   "name = 'leaky' if any(key.startswith('SPELLBENCH_') for key in os.environ) else 'clean'\n"
                   "sys.exit(serve(choose=lambda d: 0, name=name, version='1'))\n", encoding="utf-8")
    driver = SubprocessDriver(BotSpec(name="clean", version="1", type="subprocess", command=(sys.executable, str(bot))),
                              startup_ms=30_000)
    try:
        driver.start(START, timeout_s=30)        # a bot that saw SPELLBENCH_* would name itself "leaky" and be refused (R3-9)
    finally:
        driver.close()


# -- bot_environment and make_driver -----------------------------------------------------------------


def test_bot_environment_drops_every_spellbench_key_and_keeps_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SECRETS_DIR", "PIN_ROOT", "ARTIFACT_REGISTER", "ANY_LATER_SETTING"):
        monkeypatch.setenv(f"SPELLBENCH_{key}", "local value")
    monkeypatch.setenv("NOT_SPELLBENCH_SETTING", "kept")
    environment = bot_environment()
    assert not [key for key in environment if key.startswith("SPELLBENCH_")]
    assert environment["NOT_SPELLBENCH_SETTING"] == "kept"
    assert all(key.startswith("SPELLBENCH_") for key in set(os.environ) - set(environment))


def test_make_driver_picks_the_driver_and_bounds_hello_by_startup_ms() -> None:
    assert isinstance(make_driver(builtin("uniform"), CLOCKS), BuiltinDriver)
    driver = make_driver(BotSpec(name="silent", version="1", type="subprocess", command=SILENT), CLOCKS)
    assert isinstance(driver, SubprocessDriver)
    try:
        with pytest.raises(SeatFailure) as caught:
            driver.start(START, timeout_s=60)        # hello is bounded by startup_ms, not by game_start_ms or this
    finally:
        driver.close()
    assert (caught.value.cause, caught.value.detail) == ("timeout", "no answer to hello within 1000 ms")


# -- the builtin driver ------------------------------------------------------------------------------


def test_a_builtin_uniform_bot_follows_its_configured_seed_and_the_agent_seed() -> None:
    """The rating anchor's picks are a function of ``spec.seed`` and of ``agent_seed``, read in ``on_game_start``."""
    def uniform(seed: int) -> BuiltinDriver:
        return BuiltinDriver(BotSpec(name="uniform", version="2.0.0", type="builtin", seed=seed))

    driver = uniform(7)
    picks = play(driver)
    assert play(driver) == picks                    # a second game on the same driver replays the first
    assert play(uniform(7)) == picks
    assert play(uniform(0)) != picks                # the configured seed reaches the bot
    assert play(driver, agent_seed=43) != picks     # and so does the game's agent_seed
    bot = UniformBot(7)                             # the same bot served as a bot process picks the same
    process = served(InProcessBots(name="uniform", version="2.0.0", choose=bot.choose,
                                   on_game_start=bot.on_game_start, on_game_over=bot.on_game_over),
                     name="uniform", version="2.0.0")
    try:
        assert play(process) == picks
    finally:
        process.close()


def test_every_builtin_start_builds_a_fresh_bot() -> None:
    made: list[Any] = []

    class Bot:
        def __init__(self) -> None:
            made.append(self)
        def on_game_start(self, game): pass
        def choose(self, decision): return made.index(self)
        def on_game_over(self, game_over): pass

    driver = BuiltinDriver(builtin("first"), factory=Bot)
    answers = []
    for _ in range(2):                              # two games, no close() between them
        driver.start(START, timeout_s=5)
        answers.append(driver.choose(CHOOSE, timeout_s=5))
        driver.game_over(OVER, timeout_s=5)
    assert answers == [Choice(request_id="builtin", candidate_id=0, echoes={}),
                       Choice(request_id="builtin", candidate_id=1, echoes={})]


@pytest.mark.parametrize("on_game_over", [lambda game_over: 1 / 0, lambda game_over: time.sleep(2)])
def test_a_builtin_bots_game_over_failure_is_never_adjudicated(on_game_over) -> None:
    class Bot:
        def on_game_start(self, game): pass
        def choose(self, decision): return 0

    Bot.on_game_over = staticmethod(on_game_over)
    driver = BuiltinDriver(builtin("first"), factory=Bot)
    driver.start(START, timeout_s=5)
    assert driver.game_over(OVER, timeout_s=0.2) is None


def test_a_builtin_bot_cannot_mutate_the_host_copy_at_game_start_or_game_over() -> None:
    start = {**START, "rules": {"extensions": []}}
    over = copy.deepcopy(OVER)
    before = copy.deepcopy((start, over))

    class Vandal:
        def on_game_start(self, game): game.raw["rules"]["extensions"].append("x_vandal")
        def choose(self, decision): return 0
        def on_game_over(self, game_over): game_over.raw["terminal"].clear()

    driver = BuiltinDriver(builtin("first"), factory=Vandal)
    driver.start(start, timeout_s=5)
    driver.game_over(over, timeout_s=5)
    assert (start, over) == before


def test_a_builtin_bot_reads_exactly_what_a_subprocess_bot_reads() -> None:
    """The full envelope (request_type, protocol, request_id), numbered per game as a fresh bot process numbers it."""
    in_process, as_process = Recorder(), Recorder()
    hooks = {name: getattr(as_process, name) for name in ("choose", "on_game_start", "on_game_over")}
    for driver in (BuiltinDriver(builtin("first"), factory=lambda: in_process), served(InProcessBots(**hooks))):
        try:
            for _ in range(2):
                driver.start(START, timeout_s=5)
                driver.choose(CHOOSE, timeout_s=5)
                driver.game_over(OVER, timeout_s=5)
        finally:
            driver.close()
    assert in_process.seen == as_process.seen
    envelopes = [(raw["request_type"], raw["protocol"], raw["request_id"]) for raw in in_process.seen]
    game = [(kind, "spellbench/v2", f"r-{number}") for number, kind in enumerate(("game_start", "choose", "game_over"), 1)]
    assert envelopes == game + game


def test_a_timed_out_builtin_call_cannot_reach_a_later_game() -> None:
    """Python cannot kill the stuck worker, but it answers only its own call, on its own game's bot."""
    release, stuck = threading.Event(), threading.Event()
    bots: list[Any] = []

    class Bot:
        def __init__(self) -> None:
            self.games: list[str] = []
            self.worker: threading.Thread | None = None
            bots.append(self)
        def on_game_start(self, game): pass
        def choose(self, decision):
            self.games.append(decision.game_id)
            if self is not bots[0]:
                return 1
            self.worker = threading.current_thread()
            stuck.set()
            release.wait(10)
            return 0                                # game 1's answer, delivered after its call timed out
        def on_game_over(self, game_over): pass

    driver = BuiltinDriver(builtin("first"), factory=Bot)
    try:
        driver.start(START, timeout_s=5)
        with pytest.raises(SeatFailure, match="timeout"):
            driver.choose(CHOOSE, timeout_s=0.2)
        assert stuck.wait(5)
        driver.start({**START, "game_id": "g-2"}, timeout_s=5)      # the next game, while game 1's worker still runs
        release.set()
        bots[0].worker.join(5)                                      # game 1's late answer is now delivered
        assert driver.choose({**CHOOSE, "game_id": "g-2"}, timeout_s=5).candidate_id == 1
        assert [bot.games for bot in bots] == [["g-1"], ["g-2"]]
    finally:
        release.set()


# -- the subprocess driver ---------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["bare name", "absolute path"])
def test_a_bot_process_that_cannot_start_forfeits(tmp_path: Path, where: str) -> None:
    """Spec 11.4: a start failure during a run is a forfeit (``transport_error``, as in v1), never a raw error."""
    program = "no-such-spellbench-bot" if where == "bare name" else str(tmp_path / "no-such-spellbench-bot.exe")
    spec = BotSpec(name="ghost", version="1", type="subprocess", command=(program,))
    driver = SubprocessDriver(spec, startup_ms=5_000)
    try:
        with pytest.raises(SeatFailure) as caught:
            driver.start(START, timeout_s=5)
    finally:
        driver.close()
    assert (caught.value.cause, caught.value.detail) == ("transport_error", "the bot process could not be started")
    assert "no-such-spellbench-bot" in caught.value.diagnostic      # the OS error stays in the diagnostic only


@pytest.mark.parametrize(("name", "version"), [("someone-else", "1.0.0"), ("minimal", "2.0.0")])
def test_a_bot_naming_another_entry_is_refused_before_game_start(name: str, version: str) -> None:
    bots = InProcessBots(name=name, version=version)
    driver = served(bots)                           # the config entry is minimal 1.0.0
    try:
        with pytest.raises(SeatFailure, match="different bot") as caught:
            driver.start(START, timeout_s=5)
        assert caught.value.cause == "malformed_response"
        assert bots.peers[0].requests == ["hello"]  # no game_start for a bot that is not its config entry
    finally:
        driver.close()
    assert bots.peers[0].closed                     # the failed start's process was tracked, so close() ended it


def test_each_start_closes_the_previous_games_process() -> None:
    bots = InProcessBots()
    driver = served(bots)
    driver.start(START, timeout_s=5)
    driver.start(START, timeout_s=5)                # the next game, with no close() between
    assert [peer.closed for peer in bots.peers] == [True, False]
    driver.close()
    assert [peer.closed for peer in bots.peers] == [True, True]


def test_the_subprocess_driver_bounds_each_request_by_the_callers_timeout() -> None:
    bots = InProcessBots()
    driver = served(bots)
    try:
        driver.start(START, timeout_s=7.5)
        driver.choose(CHOOSE, timeout_s=2.5)
        driver.game_over(OVER, timeout_s=1.5)
    finally:
        driver.close()
    assert bots.peers[0].timeouts == {"hello": STARTUP_S, "game_start": 7.5, "choose": 2.5, "game_over": 1.5}


# -- both drivers ------------------------------------------------------------------------------------


def test_choose_outside_a_game_is_the_hosts_error_for_both_drivers() -> None:
    """A host sequencing bug: the same RuntimeError from both drivers, and the bot is never asked or charged."""
    asked: list[Any] = []

    class Bot:
        def on_game_start(self, game): pass
        def choose(self, decision): return asked.append(decision) or 0
        def on_game_over(self, game_over): pass

    for driver in (BuiltinDriver(builtin("first"), factory=Bot), served(InProcessBots(choose=Bot().choose))):
        with pytest.raises(RuntimeError, match="^choose before start or after close$"):
            driver.choose(CHOOSE, timeout_s=5)
        driver.start(START, timeout_s=5)
        driver.close()
        with pytest.raises(RuntimeError, match="^choose before start or after close$"):
            driver.choose(CHOOSE, timeout_s=5)
    assert asked == []


def test_game_over_outside_a_game_is_a_no_op_and_close_is_idempotent() -> None:
    for driver in (BuiltinDriver(builtin("first")), served(InProcessBots())):
        driver.close()                              # before any start
        assert driver.game_over(OVER, timeout_s=5) is None
        driver.start(START, timeout_s=5)
        driver.close()
        driver.close()
        assert driver.game_over(OVER, timeout_s=5) is None


def test_a_host_payload_bug_is_never_charged_to_the_bot() -> None:
    """A float is not protocol JSON (spec 2): the host's own ValidationError escapes every call, never a forfeit."""
    float_start = {**START, "agent_seed": 0.5}
    float_choose = {**CHOOSE, "clock": {"remaining_ms": 1.5, "max_decision_ms": 1000}}
    float_over = {**OVER, "terminal": {**OVER["terminal"], "seat_step_count": 0.5}}
    for driver in (BuiltinDriver(builtin("first")), served(InProcessBots())):
        try:
            with pytest.raises(ValidationError):
                driver.start(float_start, timeout_s=5)
            driver.start(START, timeout_s=5)
            with pytest.raises(ValidationError):
                driver.choose(float_choose, timeout_s=5)
            with pytest.raises(ValidationError):
                driver.game_over(float_over, timeout_s=5)
        finally:
            driver.close()
