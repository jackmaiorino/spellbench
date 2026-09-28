"""Seat drivers: what plays one seat of one game (spec 10, 11.5).

Two ``SeatDriver`` implementations: :class:`BuiltinDriver` for an in-process
builtin bot, :class:`SubprocessDriver` for a bot spoken to over a child
process's stdin and stdout via :class:`~spellbench.host.agent_process.AgentProcess`.
``make_driver`` picks the right one from a :class:`~spellbench.arena.config.BotSpec`.

The builtin driver hands its bot the payloads round-tripped through canonical
JSON, so a builtin bot sees exactly what a subprocess bot would (a plain dict,
never the host's own object) and cannot mutate the host's copy. Each call into
the bot runs on a bounded worker thread (the same thread-and-queue pattern the
v1 arena runner used), so a stuck or crashing builtin bot cannot hang or take
down the host: a slow ``choose`` forfeits ``timeout``, a raised exception
forfeits ``agent_error``, and a non-integer ``choose`` return forfeits
``malformed_response`` (spec 11.5). ``game_over`` never raises: by the time it
is sent the game's outcome is already decided, so a builtin bot's own
``game_over`` failure is swallowed rather than adjudicated, matching the v1
arena runner's ``_BuiltinDriver.game_over``.

The subprocess driver starts a fresh process per game with an environment
stripped of every ``SPELLBENCH_*`` key (``bot_environment``, R3-9): a bot
never learns where the run secret lives (``SPELLBENCH_SECRETS_DIR``) or any
other local value. Beyond that, it is a thin wrapper over ``AgentProcess``:
``choose`` and ``game_over`` delegate straight through, so a genuine host bug
in the transport is never quietly charged to the bot as a forfeit.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any, Callable, Mapping, TypeVar

from .. import wire
from ..agent_messages import Choice
from ..bot import Decision, GameOver, GameStart
from ..builtins import create_builtin_bot
from ..host.agent_process import AgentProcess
from ..host.seat import SeatDriver, SeatFailure
from ..messages import TimeControl
from .config import BotSpec

_T = TypeVar("_T")


def bot_environment() -> dict[str, str]:
    """The host's environment without any ``SPELLBENCH_*`` key (R3-9).

    Passed to every subprocess bot, so it never learns where the run secret
    lives (``SPELLBENCH_SECRETS_DIR``) or any other local value.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("SPELLBENCH_")}


def _round_trip(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy of ``payload`` through canonical JSON: exactly what a subprocess bot would read."""
    return json.loads(wire.canonical_json_dumps(payload))


class BuiltinDriver:
    """Drives an in-process builtin bot through the agent-role call sequence (spec 10.6)."""

    def __init__(self, spec: BotSpec, *, factory: Callable[[], Any] | None = None) -> None:
        self._spec = spec
        self._factory = factory
        self._bot: Any = None

    def start(self, game_start: Mapping[str, Any], *, timeout_s: float) -> None:
        """A fresh bot instance per call: ``factory()``, or ``create_builtin_bot`` from the spec."""
        self._bot = self._factory() if self._factory is not None else create_builtin_bot(self._spec.name, seed=self._spec.seed)
        game = GameStart.from_request(_round_trip(game_start))
        self._call(lambda: self._bot.on_game_start(game), timeout_s=timeout_s, phase="game_start")

    def choose(self, choose: Mapping[str, Any], *, timeout_s: float) -> Choice:
        decision = Decision.from_request(_round_trip(choose))
        result = self._call(lambda: self._bot.choose(decision), timeout_s=timeout_s, phase="choose")
        if type(result) is not int:
            raise SeatFailure(
                "malformed_response",
                f"choose must return an int candidate_id, not {type(result).__name__}",
            )
        return Choice(request_id="builtin", candidate_id=result, echoes={})

    def game_over(self, game_over: Mapping[str, Any], *, timeout_s: float) -> None:
        """Never raises: the game's result already stands, so a bot's own failure here is swallowed."""
        if self._bot is None:
            return
        terminal = GameOver.from_request(_round_trip(game_over))
        try:
            self._call(lambda: self._bot.on_game_over(terminal), timeout_s=timeout_s, phase="game_over")
        except SeatFailure:
            pass

    def close(self) -> None:
        self._bot = None

    def _call(self, fn: Callable[[], _T], *, timeout_s: float, phase: str) -> _T:
        """Run ``fn`` on a bounded worker thread; ``timeout`` on expiry, ``agent_error`` if it raises."""
        result_queue: "queue.Queue[_T | BaseException]" = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                result_queue.put(fn())
            except BaseException as exc:  # noqa: BLE001 - reported back to this call, once it is done
                result_queue.put(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            result = result_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            raise SeatFailure("timeout", f"no answer to {phase} within {round(timeout_s * 1000)} ms") from exc
        if isinstance(result, BaseException):
            raise SeatFailure(
                "agent_error", f"the builtin bot raised during {phase}", diagnostic=f"{type(result).__name__}: {result}"
            )
        return result


class SubprocessDriver:
    """Drives one subprocess bot via :class:`AgentProcess`: a fresh process per game (spec 10)."""

    def __init__(
        self,
        spec: BotSpec,
        *,
        startup_ms: int,
        agent_factory: Callable[[], AgentProcess] | None = None,
    ) -> None:
        self._spec = spec
        self._startup_ms = startup_ms
        self._agent_factory = agent_factory
        self._agent: AgentProcess | None = None

    def start(self, game_start: Mapping[str, Any], *, timeout_s: float) -> None:
        """Spawn a fresh process, check its ``hello``, then send ``game_start``; ``SeatFailure`` propagates unchanged."""
        self.close()
        agent = (
            self._agent_factory()
            if self._agent_factory is not None
            else AgentProcess(list(self._spec.command), startup_timeout_s=self._startup_ms / 1000, env=bot_environment())
        )
        self._agent = agent  # assigned before hello(), so close() can clean up a failed start
        hello = agent.hello()
        if hello.bot.name != self._spec.name or hello.bot.version != self._spec.version:
            raise SeatFailure(
                "malformed_response",
                "hello named a different bot than its config entry",
                diagnostic=f"expected {self._spec.name} {self._spec.version}, got {hello.bot.name} {hello.bot.version}",
            )
        agent.game_start(game_start, timeout_s=timeout_s)

    def choose(self, choose: Mapping[str, Any], *, timeout_s: float) -> Choice:
        assert self._agent is not None, "choose before start"
        return self._agent.choose(choose, timeout_s=timeout_s)

    def game_over(self, game_over: Mapping[str, Any], *, timeout_s: float) -> None:
        if self._agent is not None:
            self._agent.game_over(game_over, timeout_s=timeout_s)

    def close(self) -> None:
        """Idempotent: safe to call after a failed start, or more than once."""
        if self._agent is not None:
            self._agent.close()
            self._agent = None


def make_driver(spec: BotSpec, time_control: TimeControl) -> SeatDriver:
    """The seat driver ``spec`` needs: an in-process bot, or a subprocess started within ``time_control``."""
    if spec.type == "builtin":
        return BuiltinDriver(spec)
    if spec.type == "subprocess":
        return SubprocessDriver(spec, startup_ms=time_control.startup_ms)
    raise ValueError(f"unknown bot type: {spec.type!r}")
