"""Seat drivers: what plays one seat of one game (spec 10, 11.4, 11.5).

Two ``SeatDriver`` implementations: :class:`BuiltinDriver` for an in-process
builtin bot, :class:`SubprocessDriver` for a bot spoken to over a child
process's stdin and stdout via :class:`~spellbench.host.agent_process.AgentProcess`.
``make_driver`` picks the right one from a :class:`~spellbench.arena.config.BotSpec`.

The builtin driver hands its bot each request exactly as a subprocess bot would
read it: the envelope (``request_type``, ``protocol``, and a ``request_id``
numbered as a fresh bot process numbers it) and the payload, round-tripped
through canonical JSON, so the bot reads plain dicts, never the host's own
objects, and cannot mutate the host's copy. Each call into the bot runs on a
worker thread bounded by ``timeout_s`` (the thread-and-queue pattern the v1
arena runner used): a slow call forfeits ``timeout``, a raised exception
forfeits ``agent_error``, and a non-integer ``choose`` return forfeits
``malformed_response`` (spec 11.5). Python cannot kill a thread, so a worker
whose call timed out runs on until the bot returns; it holds only its own
game's bot and request and answers only its own call's queue, and every
``start`` builds a fresh bot, so it cannot reach a later game. ``game_over``
never raises for the bot: by the time it is sent the game's outcome is already
decided, so a builtin bot's own ``game_over`` failure is swallowed rather than
adjudicated, matching the v1 arena runner's ``_BuiltinDriver.game_over``. A
bot's ``on_game_start`` and ``on_game_over`` are optional, as ``serve`` reads
them: a missing one is skipped (its request is still numbered).

The subprocess driver starts a fresh process per game with an environment
stripped of every ``SPELLBENCH_*`` key (``bot_environment``, R3-9): a bot
never learns where the run secret lives (``SPELLBENCH_SECRETS_DIR``) or any
other local value. A process that cannot be started forfeits
``transport_error``, as in v1 (spec 11.4: a start failure during a run is a
forfeit). Past that, it is a thin wrapper over ``AgentProcess``, whose
failures are already ``SeatFailure``: nothing else is caught, so a host bug
is never quietly charged to the bot as a forfeit.

Calling ``choose`` before ``start`` or after ``close`` is such a host bug: both
drivers raise the same ``RuntimeError`` on the host's thread, and neither
charges the bot.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any, Callable, Mapping, TypeVar

from .. import wire
from ..agent_messages import Choice, request
from ..bot import Decision, GameOver, GameStart
from ..builtins import create_builtin_bot
from ..errors import TransportError
from ..host.agent_process import AgentProcess
from ..host.seat import SeatDriver, SeatFailure
from ..messages import TimeControl
from .config import BotSpec

_T = TypeVar("_T")

# The host sequencing bug both drivers raise on the host's thread; never charged to the bot.
_NO_GAME = "choose before start or after close"


def bot_environment() -> dict[str, str]:
    """The host's environment without any ``SPELLBENCH_*`` key (R3-9).

    Passed to every subprocess bot, so it never learns where the run secret
    lives (``SPELLBENCH_SECRETS_DIR``) or any other local value.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith("SPELLBENCH_")}


class BuiltinDriver:
    """Drives an in-process builtin bot through the agent-role call sequence (spec 10.6)."""

    def __init__(self, spec: BotSpec, *, factory: Callable[[], Any] | None = None) -> None:
        self._spec = spec
        self._factory = factory
        self._bot: Any = None
        self._count = 0  # the number in the next request_id

    def start(self, game_start: Mapping[str, Any], *, timeout_s: float) -> None:
        """A fresh bot instance per call: ``factory()``, or ``create_builtin_bot`` from the spec."""
        factory = self._factory
        bot = self._bot = factory() if factory is not None else create_builtin_bot(self._spec.name, seed=self._spec.seed)
        self._count = 1  # request ids restart per game; a bot process's hello takes r-0
        game = GameStart.from_request(self._view("game_start", game_start))
        hook = getattr(bot, "on_game_start", None)  # optional, as serve reads it (bot.py)
        if hook is not None:
            self._call(hook, game, timeout_s=timeout_s, phase="game_start")

    def choose(self, choose: Mapping[str, Any], *, timeout_s: float) -> Choice:
        bot = self._bot
        if bot is None:
            raise RuntimeError(_NO_GAME)
        decision = Decision.from_request(self._view("choose", choose))
        result = self._call(bot.choose, decision, timeout_s=timeout_s, phase="choose")
        if type(result) is not int:
            raise SeatFailure(
                "malformed_response",
                f"choose must return an int candidate_id, not {type(result).__name__}",
            )
        return Choice(request_id="builtin", candidate_id=result, echoes={})

    def game_over(self, game_over: Mapping[str, Any], *, timeout_s: float) -> None:
        """Never raises for the bot: the game's result already stands, so its failure here is swallowed."""
        bot = self._bot
        if bot is None:
            return
        terminal = GameOver.from_request(self._view("game_over", game_over))
        hook = getattr(bot, "on_game_over", None)  # optional, as serve reads it (bot.py)
        if hook is None:
            return
        try:
            self._call(hook, terminal, timeout_s=timeout_s, phase="game_over")
        except SeatFailure:
            pass

    def close(self) -> None:
        self._bot = None

    def _view(self, request_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """The request as a subprocess bot reads it: envelope and payload, through canonical JSON."""
        request_id = f"r-{self._count}"
        self._count += 1
        return json.loads(wire.canonical_json_dumps(request(request_type, request_id, payload)))

    @staticmethod
    def _call(method: Callable[[Any], _T], argument: Any, *, timeout_s: float, phase: str) -> _T:
        """Run the bot's ``method(argument)`` on a worker thread; ``timeout`` on expiry, ``agent_error`` if it raises.

        The worker gets only the bot's bound method and this call's argument, and answers into a
        queue made for this call alone: a worker that outlives its timeout cannot answer for, or
        touch the state of, a later call or game.
        """
        answers: "queue.Queue[_T | BaseException]" = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                answers.put(method(argument))
            except BaseException as exc:  # noqa: BLE001 - only the bot's own code runs here; reported to this call
                answers.put(exc)

        threading.Thread(target=run, daemon=True).start()
        try:
            result = answers.get(timeout=timeout_s)
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
        """Spawn a fresh process, check its ``hello``, then send ``game_start``.

        A process that cannot be started forfeits ``transport_error`` (spec 11.4); every later
        failure is already a ``SeatFailure`` from ``AgentProcess`` and propagates unchanged.
        """
        self.close()
        try:
            agent = (
                self._agent_factory()
                if self._agent_factory is not None
                else AgentProcess(list(self._spec.command), startup_timeout_s=self._startup_ms / 1000, env=bot_environment())
            )
        except TransportError as exc:  # the spawn only: an empty command, a config bug, still raises ValueError
            raise SeatFailure("transport_error", "the bot process could not be started", diagnostic=str(exc)) from exc
        self._agent = agent  # tracked before hello(), so close() can end a process whose start failed
        hello = agent.hello()
        if hello.bot.name != self._spec.name or hello.bot.version != self._spec.version:
            raise SeatFailure(
                "malformed_response",
                "hello named a different bot than its config entry",
                diagnostic=f"expected {self._spec.name} {self._spec.version}, got {hello.bot.name} {hello.bot.version}",
            )
        agent.game_start(game_start, timeout_s=timeout_s)

    def choose(self, choose: Mapping[str, Any], *, timeout_s: float) -> Choice:
        agent = self._agent
        if agent is None:
            raise RuntimeError(_NO_GAME)
        return agent.choose(choose, timeout_s=timeout_s)

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
