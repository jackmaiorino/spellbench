"""Tournament runner: round-robin match scheduling and game adjudication.

Schedule: round-robin over all unordered bot pairs INCLUDING mirrors
(``itertools.combinations_with_replacement`` order over the config bot list).
Each matchup is ``pairs_per_matchup`` seat-swapped PAIRS of games; both games
of a pair share one ``game_seed`` (common random numbers: the engine sees
identical randomness, only the seats swap).

Seed schedule (``spellbench-arena-seed-v1``; SplitMix64 as ported in
``bots/uniform.py`` from mtg-kernel ``python/mtg_kernel_rl/determinism.py``)::

    game_seed(m, p) = SplitMix64(
        base_seed ^ 0x5350_5f47_414d_4553 ^ m * 0x9e3779b97f4a7c15 ^ p * 0xd1b54a32d192ed03
    ).next() & (2**53 - 1)

where ``m`` is the matchup index and ``p`` the pair index. The mask keeps the
seed inside the protocol's integer range (spec section 2: |x| <= 2^53).
Statistics seeds (bootstrap, matchup CIs) are derived separately in
``leaderboard.py``.

Each game spawns ONE engine child process via ``EngineProcess`` and one agent
per seat: builtin bots run in process but are driven through the same
``game_start``/``choose``/``game_over`` call sequence (validated by the same
models); subprocess bots are driven via ``AgentProcess``. Every ``choose``
carries a wall-clock timeout (default 30 s, ``choose_timeout_ms``).

Games are independent (their own engine process, fresh bot handlers or
processes, seeds fixed by the schedule), so ``workers`` games run
concurrently. Results do not depend on the worker count: the ledger is
written in schedule order. Budget ``workers`` to the host's free cores,
since ``choose_timeout_ms`` is wall-clock time.

Adjudication (there are no timeouts in the protocol itself, spec section 11):
a choose timeout, a malformed agent response, an invalid selection, an agent
error response, or an agent transport failure is a FORFEIT LOSS for the
acting seat's bot, recorded in the ledger with an ``adjudication`` object.
A host-detected engine contract failure records a ``halted`` row with an
``engine_halt`` adjudication. Only natural terminals enter ratings.
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any, Callable, Sequence

from .. import __version__, models
from ..agent_client import AgentProcess
from ..engine_client import EngineProcess
from ..errors import (
    AgentError,
    ProtocolError,
    RemoteError,
    TransportError,
    ValidationError,
)
from . import leaderboard, registry, store
from .bots import BUILTIN_VERSIONS, create_builtin_bot
from .bots.uniform import GOLDEN_RATIO_64, MASK64, SplitMix64

SEED_SCHEDULE_VERSION = "spellbench-arena-seed-v1"
_GAME_SEED_DOMAIN = 0x5350_5F47_414D_4553
_PAIR_SEED_MIXER = 0xD1B5_4A32_D192_ED03

DEFAULT_MAX_DECISIONS = 10_000
DEFAULT_MAX_STEPS = 100_000
DEFAULT_CHOOSE_TIMEOUT_MS = 30_000
DEFAULT_ENGINE_TIMEOUT_MS = 120_000
DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_WORKERS = 1
MAX_WORKERS = 256

BOT_TYPES = frozenset({"builtin", "subprocess"})


class TournamentError(Exception):
    """The tournament cannot proceed (bad config or a broken engine)."""


class ForfeitError(Exception):
    """The acting bot loses this game by forfeit; carries the ledger cause."""

    def __init__(self, cause: str, detail: str) -> None:
        if cause not in store.FORFEIT_CAUSES:
            raise ValueError(f"unknown forfeit cause: {cause!r}")
        super().__init__(f"{cause}: {detail}")
        self.cause = cause
        self.detail = " ".join(detail.split())[:240]


def derive_game_seed(base_seed: int, matchup_index: int, pair_index: int) -> int:
    """The CRN game seed shared by both games of pair (matchup_index, pair_index)."""
    mixed = (
        base_seed
        ^ _GAME_SEED_DOMAIN
        ^ ((matchup_index * GOLDEN_RATIO_64) & MASK64)
        ^ ((pair_index * _PAIR_SEED_MIXER) & MASK64)
    ) & MASK64
    return SplitMix64(mixed).next() & ((1 << 53) - 1)


def matchup_indexes(bot_count: int) -> list[tuple[int, int]]:
    """All unordered bot-list index pairs including mirrors, in schedule order."""
    return list(combinations_with_replacement(range(bot_count), 2))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BotSpec:
    name: str
    version: str
    type: str  # "builtin" | "subprocess"
    seed: int = 0
    command: tuple[str, ...] = ()
    checkpoint: str | None = None
    engine: str = "any"
    owner: str = "unspecified"
    training_style_tags: tuple[str, ...] = ()
    registered_at: int = 0

    def registry_entry(self) -> registry.RegistryEntry:
        if self.type == "builtin":
            descriptor = registry.builtin_descriptor(self.name, self.version)
        else:
            weights = (
                registry.checkpoint_sha256(Path(self.checkpoint)) if self.checkpoint is not None else None
            )
            descriptor = registry.subprocess_descriptor(
                self.name, self.version, self.command, weights_sha256=weights
            )
        return registry.build_entry(
            name=self.name,
            version=self.version,
            engine=self.engine,
            training_style_tags=self.training_style_tags,
            owner=self.owner,
            registered_at=self.registered_at,
            descriptor=descriptor,
        )

    def to_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "seed": self.seed,
            "engine": self.engine,
            "owner": self.owner,
            "training_style_tags": list(self.training_style_tags),
            "registered_at": self.registered_at,
        }
        if self.type == "subprocess":
            doc["command"] = list(self.command)
            if self.checkpoint is not None:
                doc["checkpoint"] = self.checkpoint
        return doc


def _req_str(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise TournamentError(f"{context}: must be a nonempty string")
    return value


def _req_uint(value: Any, context: str, *, minimum: int = 0, maximum: int = (1 << 53)) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise TournamentError(f"{context}: must be an integer in [{minimum}, {maximum}]")
    return value


def _bot_spec_from_json(value: Any, context: str) -> BotSpec:
    if not isinstance(value, dict):
        raise TournamentError(f"{context}: must be an object")
    allowed = {
        "name",
        "version",
        "type",
        "seed",
        "command",
        "checkpoint",
        "engine",
        "owner",
        "training_style_tags",
        "registered_at",
    }
    required = {"name", "version", "type"}
    missing = required - set(value)
    extra = set(value) - allowed
    if missing or extra:
        raise TournamentError(f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    name = _req_str(value["name"], f"{context}.name")
    version = _req_str(value["version"], f"{context}.version")
    bot_type = _req_str(value["type"], f"{context}.type")
    if bot_type not in BOT_TYPES:
        raise TournamentError(f"{context}.type: must be one of {sorted(BOT_TYPES)}")
    seed = _req_uint(value.get("seed", 0), f"{context}.seed")
    engine = _req_str(value.get("engine", "any"), f"{context}.engine")
    owner = _req_str(value.get("owner", "unspecified"), f"{context}.owner")
    registered_at = _req_uint(value.get("registered_at", 0), f"{context}.registered_at")
    raw_tags = value.get("training_style_tags", [])
    if not isinstance(raw_tags, list) or any(type(tag) is not str or not tag for tag in raw_tags):
        raise TournamentError(f"{context}.training_style_tags: must be a list of nonempty strings")
    tags = tuple(raw_tags)
    if len(set(tags)) != len(tags):
        raise TournamentError(f"{context}.training_style_tags: duplicate tags")
    command = value.get("command")
    checkpoint = value.get("checkpoint")
    if bot_type == "builtin":
        if name not in BUILTIN_VERSIONS:
            raise TournamentError(
                f"{context}: unknown builtin bot {name!r} (known: {sorted(BUILTIN_VERSIONS)})"
            )
        if version != BUILTIN_VERSIONS[name]:
            raise TournamentError(
                f"{context}: builtin {name!r} is version {BUILTIN_VERSIONS[name]}, not {version!r}"
            )
        if command is not None or checkpoint is not None:
            raise TournamentError(f"{context}: builtin bots take no command/checkpoint")
        return BotSpec(
            name=name,
            version=version,
            type=bot_type,
            seed=seed,
            engine=engine,
            owner=owner,
            training_style_tags=tags,
            registered_at=registered_at,
        )
    if not isinstance(command, list) or not command or any(type(part) is not str or not part for part in command):
        raise TournamentError(f"{context}.command: subprocess bots require a nonempty command list")
    if checkpoint is not None:
        _req_str(checkpoint, f"{context}.checkpoint")
    return BotSpec(
        name=name,
        version=version,
        type=bot_type,
        seed=seed,
        command=tuple(command),
        checkpoint=checkpoint,
        engine=engine,
        owner=owner,
        training_style_tags=tags,
        registered_at=registered_at,
    )


@dataclass(frozen=True)
class TournamentConfig:
    tournament_dir: str
    format: str
    decks: tuple[models.Deck, models.Deck]
    engine_command: tuple[str, ...]
    engine_timeout_ms: int
    bots: tuple[BotSpec, ...]
    pairs_per_matchup: int
    base_seed: int
    max_decisions: int
    max_steps: int
    choose_timeout_ms: int
    bootstrap_replicates: int
    rating_anchor: str  # bot name from the bots list
    workers: int = DEFAULT_WORKERS

    def anchor_bot_id(self) -> str:
        for spec in self.bots:
            if spec.name == self.rating_anchor:
                return spec.registry_entry().bot_id
        raise TournamentError(f"rating_anchor {self.rating_anchor!r} is not a configured bot")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": store.CONFIG_SCHEMA,
            "tournament_dir": self.tournament_dir,
            "format": self.format,
            "decks": [self.decks[0].to_json(), self.decks[1].to_json()],
            "engine": {"command": list(self.engine_command), "timeout_ms": self.engine_timeout_ms},
            "bots": [spec.to_json() for spec in self.bots],
            "pairs_per_matchup": self.pairs_per_matchup,
            "base_seed": self.base_seed,
            "max_decisions": self.max_decisions,
            "max_steps": self.max_steps,
            "choose_timeout_ms": self.choose_timeout_ms,
            "bootstrap_replicates": self.bootstrap_replicates,
            "rating_anchor": self.rating_anchor,
            "workers": self.workers,
        }

    @classmethod
    def from_json(cls, value: Any) -> "TournamentConfig":
        context = "config"
        if not isinstance(value, dict):
            raise TournamentError("config: must be an object")
        allowed = {
            "schema",
            "tournament_dir",
            "format",
            "decks",
            "engine",
            "bots",
            "pairs_per_matchup",
            "base_seed",
            "max_decisions",
            "max_steps",
            "choose_timeout_ms",
            "bootstrap_replicates",
            "rating_anchor",
            "workers",
        }
        required = {
            "schema",
            "tournament_dir",
            "format",
            "decks",
            "engine",
            "bots",
            "pairs_per_matchup",
            "base_seed",
        }
        missing = required - set(value)
        extra = set(value) - allowed
        if missing or extra:
            raise TournamentError(
                f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}"
            )
        if value["schema"] != store.CONFIG_SCHEMA:
            raise TournamentError(f'{context}.schema: must be "{store.CONFIG_SCHEMA}"')
        tournament_dir = _req_str(value["tournament_dir"], f"{context}.tournament_dir")
        format_ = _req_str(value["format"], f"{context}.format")
        raw_decks = value["decks"]
        if not isinstance(raw_decks, list) or len(raw_decks) != 2:
            raise TournamentError(f"{context}.decks: must be a list of two decks (p0 first)")
        try:
            decks = tuple(models.Deck.from_json(item, f"{context}.decks[{i}]") for i, item in enumerate(raw_decks))
        except ValidationError as exc:
            raise TournamentError(str(exc)) from exc
        raw_engine = value["engine"]
        if not isinstance(raw_engine, dict):
            raise TournamentError(f"{context}.engine: must be an object")
        if set(raw_engine) - {"command", "timeout_ms"} or "command" not in raw_engine:
            raise TournamentError(f"{context}.engine: requires command; optional timeout_ms")
        command = raw_engine["command"]
        if not isinstance(command, list) or not command or any(type(p) is not str or not p for p in command):
            raise TournamentError(f"{context}.engine.command: must be a nonempty list of strings")
        engine_timeout_ms = _req_uint(raw_engine.get("timeout_ms", DEFAULT_ENGINE_TIMEOUT_MS), f"{context}.engine.timeout_ms", minimum=1)
        raw_bots = value["bots"]
        if not isinstance(raw_bots, list) or not raw_bots:
            raise TournamentError(f"{context}.bots: must be a nonempty list")
        bots = tuple(_bot_spec_from_json(item, f"{context}.bots[{i}]") for i, item in enumerate(raw_bots))
        names = [spec.name for spec in bots]
        if len(set(names)) != len(names):
            raise TournamentError(f"{context}.bots: names must be unique, got {names}")
        pairs_per_matchup = _req_uint(value["pairs_per_matchup"], f"{context}.pairs_per_matchup", minimum=1)
        base_seed = _req_uint(value["base_seed"], f"{context}.base_seed")
        max_decisions = _req_uint(value.get("max_decisions", DEFAULT_MAX_DECISIONS), f"{context}.max_decisions", minimum=1)
        max_steps = _req_uint(value.get("max_steps", DEFAULT_MAX_STEPS), f"{context}.max_steps", minimum=1)
        choose_timeout_ms = _req_uint(
            value.get("choose_timeout_ms", DEFAULT_CHOOSE_TIMEOUT_MS), f"{context}.choose_timeout_ms", minimum=1
        )
        bootstrap_replicates = _req_uint(
            value.get("bootstrap_replicates", DEFAULT_BOOTSTRAP_REPLICATES),
            f"{context}.bootstrap_replicates",
            minimum=1_000,
            maximum=100_000,
        )
        rating_anchor = value.get("rating_anchor", bots[0].name)
        _req_str(rating_anchor, f"{context}.rating_anchor")
        if rating_anchor not in names:
            raise TournamentError(f"{context}.rating_anchor: not a configured bot: {rating_anchor!r}")
        workers = _req_uint(
            value.get("workers", DEFAULT_WORKERS), f"{context}.workers", minimum=1, maximum=MAX_WORKERS
        )
        return cls(
            tournament_dir=tournament_dir,
            format=format_,
            decks=(decks[0], decks[1]),
            engine_command=tuple(command),
            engine_timeout_ms=engine_timeout_ms,
            bots=bots,
            pairs_per_matchup=pairs_per_matchup,
            base_seed=base_seed,
            max_decisions=max_decisions,
            max_steps=max_steps,
            choose_timeout_ms=choose_timeout_ms,
            bootstrap_replicates=bootstrap_replicates,
            rating_anchor=rating_anchor,
            workers=workers,
        )


# ---------------------------------------------------------------------------
# Seat drivers: builtin (in-process) and subprocess agents, one per seat/game
# ---------------------------------------------------------------------------


class _BuiltinDriver:
    """Drives an in-process builtin bot through the agent-role call sequence."""

    def __init__(self, spec: BotSpec, timeout_s: float) -> None:
        self._spec = spec
        self._timeout_s = timeout_s
        self._handler: Any = None
        self._game_id: str = ""

    def start(
        self,
        *,
        game_id: str,
        seat: str,
        format: str,
        decks: tuple[models.Deck, models.Deck],
        engine: models.EngineIdentity,
    ) -> None:
        self._handler = create_builtin_bot(self._spec.name, seed=self._spec.seed)
        self._game_id = game_id
        request = models.GameStartRequest(
            request_id="arena-game-start",
            game_id=game_id,
            seat=seat,
            format=format,
            decks=decks,
            engine=engine,
        )
        try:
            self._handler.on_game_start(request)
        except Exception as exc:
            raise ForfeitError("agent_error", f"on_game_start raised {type(exc).__name__}: {exc}") from exc

    def choose(self, decision: models.Decision) -> models.Selection:
        result_queue: "queue.Queue[int | BaseException]" = queue.Queue(maxsize=1)

        def call() -> None:
            try:
                result_queue.put(self._handler.choose(decision))
            except BaseException as exc:
                result_queue.put(exc)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            result = result_queue.get(timeout=self._timeout_s)
        except queue.Empty as exc:
            raise ForfeitError("timeout", f"choose exceeded {self._timeout_s}s") from exc
        if isinstance(result, BaseException):
            raise ForfeitError("agent_error", f"choose raised {type(result).__name__}: {result}")
        if type(result) is not int or not 0 <= result < len(decision.candidates):
            raise ForfeitError(
                "invalid_selection",
                f"choose returned {result!r}, not a candidate index in [0, {len(decision.candidates)})",
            )
        return models.Selection(
            candidate_id=result,
            semantic_echo=dict(decision.candidates[result].semantic),
        )

    def game_over(self, terminal: models.TerminalResult) -> None:
        if self._handler is None:
            return
        request = models.GameOverRequest(
            request_id="arena-game-over", game_id=self._game_id, terminal=terminal
        )
        try:
            self._handler.on_game_over(request)
        except Exception:
            pass  # the game result already stands; game_over errors are not adjudicated

    def close(self) -> None:
        self._handler = None


class _SubprocessDriver:
    """Drives one subprocess bot via AgentProcess (one process per seat per game)."""

    def __init__(self, spec: BotSpec, timeout_s: float) -> None:
        self._spec = spec
        self._timeout_s = timeout_s
        self._agent: AgentProcess | None = None

    def start(
        self,
        *,
        game_id: str,
        seat: str,
        format: str,
        decks: tuple[models.Deck, models.Deck],
        engine: models.EngineIdentity,
    ) -> None:
        try:
            self._agent = AgentProcess(list(self._spec.command), timeout_s=self._timeout_s)
            hello = self._agent.hello()
        except (TransportError, RemoteError, ProtocolError) as exc:
            self.close()
            raise ForfeitError(_classify_agent_failure(exc), f"hello failed: {exc}") from exc
        if hello.bot.name != self._spec.name or hello.bot.version != self._spec.version:
            self.close()
            raise ForfeitError(
                "malformed_response",
                f"hello identity mismatch: expected {self._spec.name} {self._spec.version}, "
                f"got {hello.bot.name} {hello.bot.version}",
            )
        try:
            self._agent.game_start(game_id=game_id, seat=seat, format=format, decks=decks, engine=engine)
        except (TransportError, RemoteError, ProtocolError) as exc:
            raise ForfeitError(_classify_agent_failure(exc), f"game_start failed: {exc}") from exc

    def choose(self, decision: models.Decision) -> models.Selection:
        assert self._agent is not None
        try:
            return self._agent.choose(decision)
        except (TransportError, RemoteError, ProtocolError) as exc:
            raise ForfeitError(_classify_agent_failure(exc), str(exc)) from exc

    def game_over(self, terminal: models.TerminalResult) -> None:
        if self._agent is None:
            return
        try:
            self._agent.game_over(terminal)
        except (TransportError, RemoteError, ProtocolError):
            pass  # the game result already stands; game_over errors are not adjudicated

    def close(self) -> None:
        if self._agent is not None:
            self._agent.close()
            self._agent = None


def _classify_agent_failure(exc: BaseException) -> str:
    """Map a client-side failure to a forfeit cause (closed set in store.py).

    NOTE: AgentProcess reports both malformed frames and invalid selections
    as ProtocolError; the distinction below relies on the reference client's
    stable messages (spellbench 0.1.0) and defaults to the more conservative
    "malformed_response".
    """
    if isinstance(exc, TransportError):
        return "timeout" if "timeout" in str(exc).lower() else "transport_error"
    if isinstance(exc, AgentError):
        return "agent_error"
    message = str(exc)
    if "outside the offered candidate list" in message or "semantic_echo does not match" in message:
        return "invalid_selection"
    return "malformed_response"


# ---------------------------------------------------------------------------
# Game execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GameContext:
    game_id: str
    matchup_index: int
    pair_index: int
    game_index: int
    game_seed: int
    seat_specs: tuple[tuple[str, BotSpec], tuple[str, BotSpec]]  # (seat, spec) for p0, p1


def _ledger_seats(ctx: _GameContext, entries: dict[str, registry.RegistryEntry]) -> tuple[store.LedgerSeat, store.LedgerSeat]:
    seats = []
    for seat, spec in ctx.seat_specs:
        entry = entries[spec.name]
        seats.append(
            store.LedgerSeat(seat=seat, bot_id=entry.bot_id, name=entry.name, version=entry.version)
        )
    return (seats[0], seats[1])


class _EnginePin:
    """The engine identity pinned by the first ``hello`` of the tournament.

    Every later engine process must report the identical identity. Shared
    by concurrently running games, hence the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._identity: models.EngineIdentity | None = None

    def check(self, identity: models.EngineIdentity) -> None:
        with self._lock:
            if self._identity is None:
                self._identity = identity
            elif identity != self._identity:
                raise TournamentError(
                    f"engine identity drifted between processes: {identity} != {self._identity}"
                )

    @property
    def identity(self) -> models.EngineIdentity:
        if self._identity is None:
            raise TournamentError("no engine identity was pinned (no game reached hello)")
        return self._identity


def _play_game(
    config: TournamentConfig,
    ctx: _GameContext,
    entries: dict[str, registry.RegistryEntry],
    pin: _EnginePin,
) -> store.LedgerRow:
    """Play (or adjudicate) one game; returns its ledger row.

    The first game to reach ``hello`` pins the engine identity in ``pin``;
    every other game must match it exactly.
    """
    seats = _ledger_seats(ctx, entries)
    decks_json = (config.decks[0].to_json(), config.decks[1].to_json())
    choose_timeout_s = config.choose_timeout_ms / 1000.0

    def row_for(
        *,
        outcome: str,
        classification: str,
        winner: str | None,
        reason: str,
        adjudication: store.Adjudication | None,
        step_count: int,
        decision_count: int,
    ) -> store.LedgerRow:
        winner_bot_id = None if winner is None else seats[0 if winner == "p0" else 1].bot_id
        return store.LedgerRow(
            game_id=ctx.game_id,
            matchup_index=ctx.matchup_index,
            pair_index=ctx.pair_index,
            game_index=ctx.game_index,
            format=config.format,
            game_seed=ctx.game_seed,
            seats=seats,
            decks=decks_json,
            outcome=outcome,
            classification=classification,
            winner=winner,
            winner_bot_id=winner_bot_id,
            reason=reason,
            adjudication=adjudication,
            step_count=step_count,
            decision_count=decision_count,
            engine=pin.identity.provenance(),
        )

    engine = EngineProcess(list(config.engine_command), timeout_s=config.engine_timeout_ms / 1000.0)
    drivers: list[Any] = []
    decision: models.Decision | None = None
    try:
        try:
            hello = engine.hello()
        except (TransportError, RemoteError, ProtocolError) as exc:
            raise TournamentError(f"engine hello failed: {exc}") from exc
        identity = hello.engine
        pin.check(identity)
        if config.format not in hello.formats:
            raise TournamentError(
                f"engine does not support format {config.format!r}: offers {sorted(hello.formats)}"
            )
        for seat, spec in ctx.seat_specs:
            driver: Any = (
                _BuiltinDriver(spec, choose_timeout_s)
                if spec.type == "builtin"
                else _SubprocessDriver(spec, choose_timeout_s)
            )
            drivers.append((seat, driver))
        for seat, driver in drivers:
            try:
                driver.start(
                    game_id=ctx.game_id,
                    seat=seat,
                    format=config.format,
                    decks=config.decks,
                    engine=identity,
                )
            except ForfeitError as exc:
                winner = "p1" if seat == "p0" else "p0"
                return row_for(
                    outcome=f"{winner}_win",
                    classification="forfeit",
                    winner=winner,
                    reason=f"forfeit:{exc.cause}",
                    adjudication=store.Adjudication(
                        kind="forfeit", cause=exc.cause, loser_seat=seat, detail=exc.detail
                    ),
                    step_count=0,
                    decision_count=0,
                )
        try:
            response = engine.reset(
                game_id=ctx.game_id,
                format=config.format,
                decks=config.decks,
                game_seed=ctx.game_seed,
                max_decisions=config.max_decisions,
                max_steps=config.max_steps,
            )
        except (TransportError, RemoteError, ProtocolError) as exc:
            return row_for(
                outcome="halted",
                classification="halted",
                winner=None,
                reason="engine error at reset",
                adjudication=store.Adjudication(kind="engine_halt", detail=str(exc)[:240]),
                step_count=0,
                decision_count=0,
            )
        while isinstance(response, models.Decision):
            decision = response
            seat = decision.acting_seat
            driver = next(drv for drv_seat, drv in drivers if drv_seat == seat)
            try:
                selection = driver.choose(decision)
            except ForfeitError as exc:
                winner = "p1" if seat == "p0" else "p0"
                terminal_notice = models.TerminalResult(
                    outcome="halted",
                    classification="halted",
                    winner=winner,
                    reason=f"forfeit:{exc.cause}",
                    step_count=decision.step,
                    decision_count=decision.group.group_id,
                )
                for other_seat, other in drivers:
                    if other_seat != seat:
                        other.game_over(terminal_notice)
                return row_for(
                    outcome=f"{winner}_win",
                    classification="forfeit",
                    winner=winner,
                    reason=f"forfeit:{exc.cause}",
                    adjudication=store.Adjudication(
                        kind="forfeit", cause=exc.cause, loser_seat=seat, detail=exc.detail
                    ),
                    step_count=decision.step,
                    decision_count=decision.group.group_id,
                )
            try:
                response = engine.step(selection)
            except (TransportError, RemoteError, ProtocolError) as exc:
                terminal_notice = models.TerminalResult(
                    outcome="halted",
                    classification="halted",
                    winner=None,
                    reason="engine error",
                    step_count=decision.step,
                    decision_count=decision.group.group_id,
                )
                for _, drv in drivers:
                    drv.game_over(terminal_notice)
                return row_for(
                    outcome="halted",
                    classification="halted",
                    winner=None,
                    reason="engine error mid-game",
                    adjudication=store.Adjudication(kind="engine_halt", detail=str(exc)[:240]),
                    step_count=decision.step,
                    decision_count=decision.group.group_id,
                )
        terminal = response
        assert isinstance(terminal, models.Terminal)
        for _, drv in drivers:
            drv.game_over(terminal.result)
        return row_for(
            outcome=terminal.result.outcome,
            classification=terminal.result.classification,
            winner=terminal.result.winner,
            reason=terminal.result.reason,
            adjudication=None,
            step_count=terminal.result.step_count,
            decision_count=terminal.result.decision_count,
        )
    finally:
        for _, drv in drivers:
            drv.close()
        engine.close()


# ---------------------------------------------------------------------------
# Tournament execution
# ---------------------------------------------------------------------------


def _schedule(config: TournamentConfig) -> list[_GameContext]:
    """Every game of the round-robin, in ledger order."""
    schedule: list[_GameContext] = []
    for matchup_index, (i, j) in enumerate(matchup_indexes(len(config.bots))):
        for pair_index in range(config.pairs_per_matchup):
            game_seed = derive_game_seed(config.base_seed, matchup_index, pair_index)
            for game_index in (0, 1):
                if game_index == 0:
                    seat_specs = (("p0", config.bots[i]), ("p1", config.bots[j]))
                else:
                    seat_specs = (("p0", config.bots[j]), ("p1", config.bots[i]))
                schedule.append(
                    _GameContext(
                        game_id=f"m{matchup_index:04d}p{pair_index:04d}g{game_index}",
                        matchup_index=matchup_index,
                        pair_index=pair_index,
                        game_index=game_index,
                        game_seed=game_seed,
                        seat_specs=seat_specs,
                    )
                )
    return schedule


@dataclass(frozen=True)
class TournamentSummary:
    tournament_dir: Path
    games_total: int
    games_rated: int
    games_truncated: int
    games_halted: int
    games_forfeit: int
    leaderboard_status: str
    manifest: dict[str, Any]


def run_tournament(
    config: TournamentConfig,
    *,
    on_game: Callable[[store.LedgerRow], None] | None = None,
) -> TournamentSummary:
    """Run the full schedule and publish the tournament artifacts."""
    directory = Path(config.tournament_dir)
    store.prepare_tournament_dir(directory)
    entries_list = [spec.registry_entry() for spec in config.bots]
    entries = {entry.name: entry for entry in entries_list}
    anchor_bot_id = config.anchor_bot_id()

    store.write_json_atomic(directory / store.CONFIG_NAME, config.to_json())
    registry.write_registry(directory / store.REGISTRY_NAME, entries_list)
    ledger_path = directory / store.LEDGER_NAME
    ledger_path.write_bytes(b"")  # truncate/create the ledger before the first game

    rows: list[store.LedgerRow] = []
    pin = _EnginePin()

    def record(row: store.LedgerRow) -> None:
        rows.append(row)
        store.append_ledger_row(ledger_path, row.to_json())
        if on_game is not None:
            on_game(row)

    schedule = _schedule(config)
    if config.workers == 1:
        for ctx in schedule:
            record(_play_game(config, ctx, entries, pin))
    else:
        pool = ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="spellbench-game")
        try:
            futures = [pool.submit(_play_game, config, ctx, entries, pin) for ctx in schedule]
            for future in futures:  # schedule order, whatever the completion order
                record(future.result())
        finally:
            # On an abort (a TournamentError or an interrupt) the queued games
            # are dropped; games already running finish before the raise.
            pool.shutdown(wait=True, cancel_futures=True)

    document, markdown = leaderboard.build_leaderboard(
        rows,
        entries_list,
        anchor_bot_id=anchor_bot_id,
        base_seed=config.base_seed,
        bootstrap_replicates=config.bootstrap_replicates,
        format=config.format,
    )
    store.write_json_atomic(directory / store.LEADERBOARD_JSON_NAME, document)
    store.write_bytes_atomic(directory / store.LEADERBOARD_MD_NAME, markdown.encode("utf-8"))

    counts = {"natural": 0, "truncated": 0, "halted": 0, "forfeit": 0}
    for row in rows:
        counts[row.classification] += 1
    manifest = {
        "schema": store.TOURNAMENT_SCHEMA,
        "tournament": {
            "format": config.format,
            "base_seed": config.base_seed,
            "pairs_per_matchup": config.pairs_per_matchup,
            "max_decisions": config.max_decisions,
            "max_steps": config.max_steps,
            "choose_timeout_ms": config.choose_timeout_ms,
            "engine_timeout_ms": config.engine_timeout_ms,
            "bootstrap_replicates": config.bootstrap_replicates,
            "seed_schedule": SEED_SCHEDULE_VERSION,
            "rating_anchor": {"name": config.rating_anchor, "bot_id": anchor_bot_id},
            "arena_version": __version__,
            "workers": config.workers,
            "bots": [entry.to_json() for entry in entries_list],
        },
        "engine": pin.identity.to_json(),
        "games": {
            "total": len(rows),
            "natural": counts["natural"],
            "truncated": counts["truncated"],
            "halted": counts["halted"],
            "forfeit": counts["forfeit"],
        },
        "leaderboard_status": document["status"],
        "files": [store.file_entry(directory / name, name) for name in store.DATA_FILE_NAMES],
    }
    store.publish_manifest(directory, manifest)
    return TournamentSummary(
        tournament_dir=directory,
        games_total=len(rows),
        games_rated=counts["natural"],
        games_truncated=counts["truncated"],
        games_halted=counts["halted"],
        games_forfeit=counts["forfeit"],
        leaderboard_status=document["status"],
        manifest=manifest,
    )
