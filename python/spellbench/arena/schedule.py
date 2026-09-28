"""Preflight, the schedule and per-game setup (spec 11.1, 11.6, 12).

Preflight proves a tournament can start before anything is written and before
any game: the engine starts and answers ``hello`` with a valid ``hello_ok``
(an invalid one, such as a catalog name that is not NFC, reports the parse
error, which names the card and the deck), the format is offered, every
configured deck resolves (a catalog id through ``hello_ok.catalog``, needing
``catalog`` in ``deck_sources``; an inline list needing ``decklist``), the
information rules resolve against ``rules_supported`` (``mulligan: "auto"``
becomes ``london`` where the engine has it, else ``none``, spec 12.2) with
``card_name_domain`` over every resolved deck's names, every enabled
extension is declared (a ``native_ids: true`` one needs its audit in
``native_id_audits``, recorded as ``{"name", "audit"}``), each deck pairing
resets once in its own engine process under a host-internal preflight secret
and game id (never a scheduled game's, spec 11.6 and Decision 9), and every
subprocess bot starts, names its config entry and has its ``requires`` met.
A failure is a :class:`~spellbench.arena.config.TournamentError` naming the
engine, deck or bot; a bot's stderr never enters it (R3-32).

Each per-pairing reset carries the run's rules, the object every game sends,
bounded by ``engine_step_ms`` (spec 11.4: it bounds each engine response),
while process start through ``hello_ok`` is bounded by ``startup_ms``. An
engine that declares a rule it cannot play with these decks is refused here,
before any game (spec 11.1), instead of after a schedule's worth of halts.

The schedule is the v1 round robin: matchups in
``itertools.combinations_with_replacement`` order over the config's bots
(mirrors included unless ``include_self_play`` is false), each matchup
``pairs_per_matchup`` seat-swapped pairs (``pair_slot`` 0 then 1), pair ``p``
playing ``deck_pool[p % len(deck_pool)]`` in both seats, or the fixed
``decks``. ``game_index`` counts from 0 in schedule order and
``game_id = run_secret.game_id(game_index)`` (spec 11.6: opaque ids), so the
same config and run secret give the same schedule, ids and seeds on every
machine.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from itertools import combinations_with_replacement

from .. import digests
from ..agent_messages import OwnDeck
from ..errors import ProtocolError, RemoteError, TransportError
from ..host.agent_process import AgentProcess
from ..host.engine_process import EngineProcess
from ..host.seat import SeatFailure
from ..host.setup import GameSetup
from ..messages import (
    CardNameDomain,
    DeckRow,
    EngineIdentity,
    EngineProfile,
    EnvHelloOk,
    ResetRequest,
    Rules,
    WireDeck,
)
from ..run_secret import RunSecret
from .config import BotSpec, DeckSpec, TournamentConfig, TournamentError
from .drivers import bot_environment
from .ledger import LedgerDeck


@dataclass(frozen=True)
class ResolvedDeck:
    """One configured deck resolved against the engine's declarations (spec 11.1, 12.1).

    ``name`` is the catalog deck's published name, or the inline deck's configured one;
    ``decklist`` holds the rows sorted in code point order (``digests.deck_rows``).
    """

    deck_id: str
    name: str
    catalog_id: str | None
    decklist: tuple[DeckRow, ...]

    def wire(self) -> WireDeck:
        """The deck as ``reset`` carries it: ``{deck_id, catalog_id}`` or ``{deck_id, decklist}`` (spec 9.2)."""
        if self.catalog_id is not None:
            return WireDeck(self.deck_id, catalog_id=self.catalog_id)
        return WireDeck(self.deck_id, decklist=self.decklist)

    def own(self) -> OwnDeck:
        """The deck as ``game_start.own_deck`` carries it (spec 10.2, 12.1)."""
        return OwnDeck(self.deck_id, self.name, self.decklist)

    def ledger(self) -> LedgerDeck:
        """The deck as a ledger row records it (R2-14)."""
        return LedgerDeck(self.deck_id, self.name, self.catalog_id)


@dataclass(frozen=True)
class RunSetup:
    """What preflight resolved for the whole run: the first hello, the decks and the rules."""

    hello: EnvHelloOk
    decks: dict[DeckSpec, ResolvedDeck]
    rules: Rules
    native_id_extensions: tuple[dict, ...]

    @property
    def engine(self) -> EngineIdentity:
        """The pinned engine identity (``hello.engine``)."""
        return self.hello.engine

    @property
    def profile(self) -> EngineProfile:
        """The engine's declared profile (``hello.profile``)."""
        return self.hello.profile


@dataclass(frozen=True)
class GameContext:
    """One scheduled game: its place in the round robin, its opaque id, and its seats and decks."""

    game_index: int
    game_id: str
    matchup_index: int
    pair_index: int
    pair_slot: int
    seat_specs: tuple[tuple[str, BotSpec], tuple[str, BotSpec]]  # (seat, spec) for p0, p1
    decks: tuple[DeckSpec, DeckSpec]  # (p0, p1)


class EnginePin:
    """The engine identity pinned by the first ``hello`` of the tournament.

    Every later engine process must report the identical identity; drift is a
    :class:`TournamentError`. Shared by concurrently running games, hence the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._identity: EngineIdentity | None = None

    def check(self, identity: EngineIdentity) -> None:
        with self._lock:
            if self._identity is None:
                self._identity = identity
            elif identity != self._identity:
                raise TournamentError(
                    f"engine identity drifted between processes: {identity} != {self._identity}"
                )

    @property
    def identity(self) -> EngineIdentity:
        if self._identity is None:
            raise TournamentError("no engine identity was pinned (no engine process said hello)")
        return self._identity


def matchup_indexes(bot_count: int, *, include_self_play: bool = True) -> list[tuple[int, int]]:
    """Unordered bot-list index pairs in schedule order; mirrors unless self-play is off."""
    return [
        (i, j)
        for i, j in combinations_with_replacement(range(bot_count), 2)
        if include_self_play or i != j
    ]


# ---------------------------------------------------------------------------
# Preflight (spec 11.1)
# ---------------------------------------------------------------------------


def preflight(config: TournamentConfig, run_secret: RunSecret, *, pin: EnginePin | None = None) -> RunSetup:
    """Start the engine once per deck pairing and every subprocess bot once, before any game.

    A missing executable, a deck the engine refuses, a rule outside ``rules_supported``
    or a bot whose ``requires`` are unmet is a config error: it stops the tournament
    here, before anything is written, instead of turning every game into a forfeit or
    a halt. ``pin`` is shared with the run's per-game engine processes when given.
    """
    pin = EnginePin() if pin is None else pin
    pairs = config.preflight_deck_pairs()
    with _engine(config) as engine:
        hello = _hello(engine, pin, config)
        decks = _resolve_decks(config, hello)
        rules = _resolve_rules(config, hello, decks)
        native = _native_id_extensions(config, hello)
        _reset_pairing(engine, config, run_secret, 0, pairs[0], decks, rules, hello)
    for index, pair in enumerate(pairs[1:], 1):
        # One engine process per deck pairing: an engine hosts one active game at a
        # time (spec 2), and the preflight never finishes its game.
        with _engine(config) as engine:
            process_hello = _hello(engine, pin, config)
            _reset_pairing(engine, config, run_secret, index, pair, decks, rules, process_hello)
    for spec in config.bots:
        if spec.type == "subprocess":
            _preflight_bot(config, hello, rules, spec)
    return RunSetup(hello=hello, decks=decks, rules=rules, native_id_extensions=native)


def _engine(config: TournamentConfig) -> EngineProcess:
    """The engine process, bounded by ``startup_ms`` (spec 11.4: at preflight a failure is a config error)."""
    try:
        return EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
    except TransportError as exc:
        raise TournamentError(f"preflight: the engine could not start: {exc}") from exc


def _hello(engine: EngineProcess, pin: EnginePin, config: TournamentConfig) -> EnvHelloOk:
    """One engine process's ``hello``: valid, pinned, and offering the format."""
    try:
        hello = engine.hello()
    except (TransportError, RemoteError, ProtocolError) as exc:
        # The parse error of an invalid hello_ok names the card and the deck.
        raise TournamentError(f"preflight: engine hello failed: {exc}") from exc
    pin.check(hello.engine)
    if config.format not in hello.formats:
        raise TournamentError(
            f"preflight: the engine does not support format {config.format!r}: offers {sorted(hello.formats)}"
        )
    return hello


def _resolve_decks(config: TournamentConfig, hello: EnvHelloOk) -> dict[DeckSpec, ResolvedDeck]:
    """Every configured deck, in first-use order."""
    return {spec: _resolve_deck(spec, hello) for spec in config.deck_specs()}


def _resolve_deck(spec: DeckSpec, hello: EnvHelloOk) -> ResolvedDeck:
    """One deck: a catalog id through ``hello_ok.catalog``, or an inline list (spec 12.1)."""
    if spec.catalog_id is not None:
        if "catalog" not in hello.deck_sources:
            raise TournamentError(
                f"preflight: deck {spec.catalog_id!r}: the engine declares no catalog deck source (deck_sources)"
            )
        for deck in hello.catalog:
            if deck.catalog_id == spec.catalog_id:
                rows = digests.deck_rows(
                    [row.to_json() for row in deck.decklist], f"preflight: deck {spec.catalog_id!r}"
                )
                return ResolvedDeck(
                    deck_id=digests.deck_id(rows),
                    name=deck.name,
                    catalog_id=deck.catalog_id,
                    decklist=tuple(DeckRow(row["name"], row["count"]) for row in rows),
                )
        raise TournamentError(f"preflight: deck {spec.catalog_id!r}: not in the engine's hello_ok.catalog")
    assert spec.name is not None and spec.decklist is not None
    if "decklist" not in hello.deck_sources:
        raise TournamentError(
            f"preflight: deck {spec.name!r}: the engine declares no decklist deck source (deck_sources)"
        )
    return ResolvedDeck(
        deck_id=digests.deck_id([row.to_json() for row in spec.decklist]),
        name=spec.name,
        catalog_id=None,
        decklist=spec.decklist,
    )


def _resolve_rules(config: TournamentConfig, hello: EnvHelloOk, decks: dict[DeckSpec, ResolvedDeck]) -> Rules:
    """The run's information rules against ``rules_supported`` and the resolved decks (spec 11.1, 12.2)."""
    supported = hello.profile.rules_supported
    mulligan = config.rules.mulligan
    if mulligan == "auto":
        mulligan = "london" if "london" in supported["mulligan"] else "none"
    elif mulligan not in supported["mulligan"]:
        raise TournamentError(
            f"preflight: rules.mulligan {mulligan!r} is not in the engine's rules_supported.mulligan "
            f"({', '.join(supported['mulligan'])})"
        )
    starting_player = config.rules.starting_player
    if starting_player not in supported["starting_player"]:
        raise TournamentError(
            f"preflight: rules.starting_player {starting_player!r} is not in the engine's "
            f"rules_supported.starting_player ({', '.join(supported['starting_player'])})"
        )
    declared = {extension.name for extension in hello.profile.extensions}
    for name in config.extensions:
        if name not in declared:
            raise TournamentError(
                f"preflight: extension {name!r} is not declared in the engine's hello_ok.extensions"
            )
    names = [row.name for spec in config.deck_specs() for row in decks[spec].decklist]
    return Rules(
        opponent_decklist=config.rules.opponent_decklist,
        mulligan=mulligan,
        starting_player=starting_player,
        starting_seat=config.rules.starting_seat,
        card_name_domain=CardNameDomain.from_json(digests.card_name_domain(names)),
        extensions=config.extensions,
        probe=False,  # hosts never enable the probe (spec 14)
    )


def _native_id_extensions(config: TournamentConfig, hello: EnvHelloOk) -> tuple[dict, ...]:
    """Each enabled extension the engine declares with ``native_ids: true``, with its audit (spec 14)."""
    declared = {extension.name: extension.native_ids for extension in hello.profile.extensions}
    recorded = []
    for name in config.extensions:
        if declared.get(name, False):
            audit = config.native_id_audits.get(name)
            if audit is None:
                raise TournamentError(
                    f"preflight: extension {name!r} is declared with native_ids: true, so "
                    "config.native_id_audits must name its audit (spec 14)"
                )
            recorded.append({"name": name, "audit": audit})
    return tuple(recorded)


def _reset_pairing(
    engine: EngineProcess,
    config: TournamentConfig,
    run_secret: RunSecret,
    index: int,
    pair: tuple[DeckSpec, DeckSpec],
    decks: dict[DeckSpec, ResolvedDeck],
    rules: Rules,
    hello: EnvHelloOk,
) -> None:
    """One preflight reset of deck pairing ``index``, under its preflight secret and id (spec 11.6).

    The reset carries ``rules``, the object every game sends: a declared rule the engine
    cannot play with these decks stops the run here, before any game (spec 11.1). It is
    bounded by ``engine_step_ms`` (spec 11.4: it bounds each engine response), as a game's
    own reset is.
    """
    engine.set_timeout(config.time_control.engine_step_ms / 1000)
    request = ResetRequest(
        request_id=engine.next_request_id(),
        game_id=run_secret.preflight_game_id(index),
        format=config.format,
        seats=(decks[pair[0]].wire(), decks[pair[1]].wire()),
        rules=rules,
        game_secret=run_secret.preflight_secret(index).hex(),
        max_decisions=config.limits.max_decisions,
        max_steps=config.limits.max_steps,
    )
    try:
        engine.reset(request)
    except (TransportError, RemoteError, ProtocolError) as exc:
        labels = [decks[spec].name for spec in pair]
        raise TournamentError(
            f"preflight: engine {hello.engine.name} {hello.engine.version} could not start a game "
            f"with decks {labels}: {exc}"
        ) from exc


def _preflight_bot(config: TournamentConfig, hello: EnvHelloOk, rules: Rules, spec: BotSpec) -> None:
    """Start one subprocess bot once: its hello, its identity and its ``requires`` (spec 10.1, 11.1)."""
    try:
        agent = AgentProcess(
            list(spec.command), startup_timeout_s=config.time_control.startup_ms / 1000, env=bot_environment()
        )
    except TransportError as exc:
        raise TournamentError(f"preflight: bot {spec.name}: could not start: {exc}") from exc
    try:
        hello_ok = agent.hello()
    except SeatFailure as exc:
        # Cause and detail only: the diagnostic holds the bot's stderr (R3-32).
        raise TournamentError(f"preflight: bot {spec.name}: {exc.cause}: {exc.detail}") from exc
    finally:
        agent.close()
    if (hello_ok.bot.name, hello_ok.bot.version) != (spec.name, spec.version):
        raise TournamentError(
            f"preflight: bot {spec.name}: answered hello as {hello_ok.bot.name!r} {hello_ok.bot.version!r}"
        )
    for flag in hello_ok.requires_observation:
        if not hello.profile.observation.get(flag, False):
            raise TournamentError(
                f"preflight: bot {spec.name}: requires the observation flag {flag!r}, "
                "which the engine does not declare"
            )
    for name in hello_ok.requires_extensions:
        if name not in rules.extensions:
            raise TournamentError(
                f"preflight: bot {spec.name}: requires the extension {name!r}, which this run does not enable"
            )


# ---------------------------------------------------------------------------
# The schedule (spec 11.6) and per-game setup
# ---------------------------------------------------------------------------


def schedule(config: TournamentConfig, run_secret: RunSecret) -> list[GameContext]:
    """Every game of the round robin, in schedule (ledger) order."""
    games: list[GameContext] = []
    matchups = matchup_indexes(len(config.bots), include_self_play=config.include_self_play)
    for matchup_index, (i, j) in enumerate(matchups):
        for pair_index in range(config.pairs_per_matchup):
            decks = config.decks_for_pair(pair_index)
            for pair_slot in (0, 1):
                game_index = len(games)
                if pair_slot == 0:
                    seat_specs = (("p0", config.bots[i]), ("p1", config.bots[j]))
                else:
                    seat_specs = (("p0", config.bots[j]), ("p1", config.bots[i]))
                games.append(
                    GameContext(
                        game_index=game_index,
                        game_id=run_secret.game_id(game_index),
                        matchup_index=matchup_index,
                        pair_index=pair_index,
                        pair_slot=pair_slot,
                        seat_specs=seat_specs,
                        decks=decks,
                    )
                )
    return games


def game_setup(
    config: TournamentConfig, setup: RunSetup, context: GameContext, run_secret: RunSecret
) -> GameSetup:
    """One scheduled game's bindings, derived from the run secret (spec 11.6).

    ``own_decks[i]`` is the resolved deck of seat ``i``; the game loop decides what
    ``opponent_deck`` shows (Task 23).
    """
    resolved = tuple(setup.decks[spec] for spec in context.decks)
    return GameSetup(
        game_index=context.game_index,
        game_id=context.game_id,
        game_secret_hex=run_secret.game_secret(context.game_index).hex(),
        format=config.format,
        wire_decks=(resolved[0].wire(), resolved[1].wire()),
        own_decks=(resolved[0].own(), resolved[1].own()),
        rules=setup.rules,
        time_control=config.time_control,
        limits=config.limits,
        resources=config.resources,
        agent_seeds=(
            run_secret.agent_seed(context.game_index, "p0"),
            run_secret.agent_seed(context.game_index, "p1"),
        ),
    )
