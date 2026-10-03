"""Tournament config v2: the parsed, checked tournament configuration.

One config drives a whole tournament: the engine command, the bots, the
deck pair or rotating deck pool, the information rules (spec 12.2), and the
clocks, caps and declared resources (spec 11.4). Benchmarks fix their rules
(opponent decklist visible, mulligan "auto": london when the engine supports
it, else none, per spec 12.2; host-assigned starting player with seat p0),
so the defaults below are the benchmark values.

v1 config fields (``base_seed``, ``max_decisions``, ``max_steps``,
``choose_timeout_ms``, ``startup_timeout_ms``, ``engine.timeout_ms``) are
rejected with the name of their v2 replacement. There is no ``probe`` field:
hosts never enable the probe (spec 9.7, 12.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import digests
from .._schema import EXTENSION_KEY_RE
from ..builtins import BUILTIN_VERSIONS
from ..errors import ValidationError
from ..messages import DeckRow, Limits, Resources, TimeControl
from . import ratings, registry

CONFIG_SCHEMA = "spellbench-tournament-config/v2"
# The most worker processes Windows can wait on; one limit keeps configs portable.
MAX_WORKERS = 61
DEFAULT_TIME_CONTROL = TimeControl(300000, 60000, 600000, 2000, 60000, 120000)
DEFAULT_LIMITS = Limits(10000, 100000, 500, 4999, 49999)
DEFAULT_RESOURCES = Resources(cpus=1, memory_mb=4096, gpu=False, engine_cpus=1)
# Config-level mulligan rules; "auto" resolves to london or none per engine support (spec 12.2).
MULLIGAN_CHOICES = ("auto", "london", "none")

DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_WORKERS = 1

BOT_TYPES = frozenset({"builtin", "subprocess"})

# v1 config fields and the v2 field that replaces each.
_V1_FIELDS = {
    "base_seed": "stats_seed",
    "max_decisions": "limits.max_decisions",
    "max_steps": "limits.max_steps",
    "choose_timeout_ms": "time_control.max_decision_ms",
    "startup_timeout_ms": "time_control.startup_ms",
}


class TournamentError(Exception):
    """The tournament cannot proceed (bad config or a broken engine)."""


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
    evaluation_identity: str | None = None
    evaluation_inputs: tuple[str, ...] = ()

    def registry_entry(self, *, checkpoint_path: str | None = None) -> registry.RegistryEntry:
        """This bot's registry entry. The descriptor records the command as
        written; ``checkpoint_path`` (the resolved path, when the recorded
        one holds a placeholder) is where the checkpoint bytes are read."""
        if self.type == "builtin":
            descriptor = registry.builtin_descriptor(self.name, self.version)
        else:
            path = self.checkpoint if checkpoint_path is None else checkpoint_path
            weights = registry.checkpoint_sha256(Path(path)) if path is not None else None
            descriptor = registry.subprocess_descriptor(
                self.name, self.version, self.command, weights_sha256=weights
            )
        if self.evaluation_identity is not None:
            descriptor["evaluation_identity"] = self.evaluation_identity
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
        if self.evaluation_identity is not None:
            doc["evaluation_identity"] = self.evaluation_identity
        if self.evaluation_inputs:
            doc["evaluation_inputs"] = list(self.evaluation_inputs)
        return doc


def _req_str(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise TournamentError(f"{context}: must be a nonempty string")
    return value


def _req_uint(value: Any, context: str, *, minimum: int = 0, maximum: int = (1 << 53) - 1) -> int:
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
        "evaluation_identity",
        "evaluation_inputs",
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
    identity = value.get("evaluation_identity")
    if "evaluation_identity" in value and (
        type(identity) is not str or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity)
    ):
        raise TournamentError(f"{context}.evaluation_identity: must be 64 lowercase hex characters")
    inputs = value.get("evaluation_inputs", [])
    if not isinstance(inputs, list) or any(type(item) is not str or not item for item in inputs):
        raise TournamentError(f"{context}.evaluation_inputs: must be a list of nonempty paths")
    if len(set(inputs)) != len(inputs):
        raise TournamentError(f"{context}.evaluation_inputs: duplicate paths")
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
            evaluation_identity=identity,
            evaluation_inputs=tuple(inputs),
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
        evaluation_identity=identity,
        evaluation_inputs=tuple(inputs),
    )


@dataclass(frozen=True)
class DeckSpec:
    """One configured deck: a catalog reference or an inline list (spec 12.1).

    Exactly one shape: ``catalog_id`` alone, or ``name`` with ``decklist``.
    """

    catalog_id: str | None = None
    name: str | None = None
    decklist: tuple[DeckRow, ...] | None = None

    def __post_init__(self) -> None:
        catalog_form = self.catalog_id is not None
        inline_form = self.name is not None or self.decklist is not None
        if catalog_form == inline_form or (inline_form and (self.name is None or self.decklist is None)):
            raise TournamentError(
                "deck: a deck is exactly {catalog_id} or {name, decklist}"
            )

    def to_json(self) -> dict[str, Any]:
        if self.catalog_id is not None:
            return {"catalog_id": self.catalog_id}
        assert self.name is not None and self.decklist is not None
        return {"name": self.name, "decklist": [row.to_json() for row in self.decklist]}

    @classmethod
    def from_json(cls, value: Any, context: str) -> "DeckSpec":
        if not isinstance(value, dict):
            raise TournamentError(f"{context}: must be an object")
        keys = set(value)
        if keys == {"catalog_id"}:
            return cls(catalog_id=_req_str(value["catalog_id"], f"{context}.catalog_id"))
        if keys == {"name", "decklist"}:
            name = _req_str(value["name"], f"{context}.name")
            try:
                rows = digests.deck_rows(value["decklist"], f"{context} ({name}).decklist")
            except ValidationError as exc:
                raise TournamentError(f"{context}: {exc}") from exc
            return cls(name=name, decklist=tuple(DeckRow(row["name"], row["count"]) for row in rows))
        raise TournamentError(
            f"{context}: a deck is exactly {{catalog_id}} or {{name, decklist}}; got {sorted(keys)}"
        )


@dataclass(frozen=True)
class RulesSpec:
    """The information rules of every game (spec 12.2).

    ``starting_seat`` is ``p0`` or ``p1`` with ``host_assigned`` and null
    with ``toss_winner_chooses``; ``mulligan`` ``auto`` lets the benchmark
    play london where the engine supports it and none otherwise.
    """

    opponent_decklist: str = "visible"
    mulligan: str = "auto"
    starting_player: str = "host_assigned"
    starting_seat: str | None = "p0"

    def __post_init__(self) -> None:
        # Messages carry the bare field name; from_json prefixes its context.
        if self.opponent_decklist not in ("visible", "hidden"):
            raise TournamentError("opponent_decklist: must be visible or hidden")
        if self.mulligan not in MULLIGAN_CHOICES:
            raise TournamentError(f"mulligan: must be one of {list(MULLIGAN_CHOICES)}")
        if self.starting_player not in ("host_assigned", "toss_winner_chooses"):
            raise TournamentError("starting_player: must be host_assigned or toss_winner_chooses")
        if self.starting_player == "host_assigned":
            if self.starting_seat not in ("p0", "p1"):
                raise TournamentError("starting_seat: must be p0 or p1 with host_assigned (spec 12.2)")
        elif self.starting_seat is not None:
            raise TournamentError("starting_seat: must be null with toss_winner_chooses (spec 12.2)")

    def to_json(self) -> dict[str, Any]:
        return {
            "opponent_decklist": self.opponent_decklist,
            "mulligan": self.mulligan,
            "starting_player": self.starting_player,
            "starting_seat": self.starting_seat,
        }

    @classmethod
    def from_json(cls, value: Any, context: str) -> "RulesSpec":
        if not isinstance(value, dict):
            raise TournamentError(f"{context}: must be an object")
        allowed = {"opponent_decklist", "mulligan", "starting_player", "starting_seat"}
        extra = set(value) - allowed
        if extra:
            raise TournamentError(f"{context}: unknown fields {sorted(extra)}")
        try:
            return cls(
                opponent_decklist=value.get("opponent_decklist", "visible"),
                mulligan=value.get("mulligan", "auto"),
                starting_player=value.get("starting_player", "host_assigned"),
                starting_seat=value.get("starting_seat", "p0"),
            )
        except TournamentError as exc:
            raise TournamentError(f"{context}.{exc}") from exc


def _spec_block(block_type: Any, value: Any, context: str) -> Any:
    """A complete ``time_control``/``limits``/``resources`` block from ``messages``."""
    try:
        return block_type.from_json(value, context)
    except ValidationError as exc:
        raise TournamentError(f"{context}: {exc}") from exc


@dataclass(frozen=True)
class TournamentConfig:
    tournament_dir: str
    format: str
    decks: tuple[DeckSpec, DeckSpec] | None  # None when a deck_pool is used
    deck_pool: tuple[DeckSpec, ...] | None
    engine_command: tuple[str, ...]
    bots: tuple[BotSpec, ...]
    pairs_per_matchup: int
    stats_seed: int
    rules: RulesSpec
    extensions: tuple[str, ...]
    native_id_audits: dict[str, str]
    time_control: TimeControl
    limits: Limits
    resources: Resources
    bootstrap_replicates: int
    rating_anchor: str  # bot name from the bots list
    workers: int
    include_self_play: bool
    matchups: tuple[tuple[str, str], ...] | None = None
    opponent_panel: tuple[str, ...] = ()
    evaluation_version: str | None = None
    evaluation_engine_identity: str | None = None
    evaluation_engine_inputs: tuple[str, ...] = ()

    def decks_for_pair(self, pair_index: int) -> tuple[DeckSpec, DeckSpec]:
        """The (p0, p1) decks of both games of pair ``pair_index``."""
        if self.deck_pool is None:
            assert self.decks is not None
            return self.decks
        deck = self.deck_pool[pair_index % len(self.deck_pool)]
        return (deck, deck)

    def preflight_deck_pairs(self) -> tuple[tuple[DeckSpec, DeckSpec], ...]:
        """Every deck pairing the schedule uses, in first-use order."""
        if self.deck_pool is None:
            assert self.decks is not None
            return (self.decks,)
        return tuple((deck, deck) for deck in self.deck_pool)

    def deck_specs(self) -> tuple[DeckSpec, ...]:
        """The distinct decks the schedule uses, in first-use order."""
        ordered = self.deck_pool if self.deck_pool is not None else self.decks
        assert ordered is not None
        return tuple(dict.fromkeys(ordered))

    def per_game_cores(self) -> int:
        """Cores one game needs: the engine's, plus two per-seat shares when a bot is a subprocess."""
        cores = self.resources.engine_cpus
        if any(spec.type == "subprocess" for spec in self.bots):
            cores += 2 * self.resources.cpus
        return cores

    def to_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "schema": CONFIG_SCHEMA,
            "tournament_dir": self.tournament_dir,
            "format": self.format,
            "engine": {"command": list(self.engine_command)},
            "bots": [spec.to_json() for spec in self.bots],
            "pairs_per_matchup": self.pairs_per_matchup,
            "stats_seed": self.stats_seed,
            "rules": self.rules.to_json(),
            "extensions": list(self.extensions),
            "native_id_audits": dict(self.native_id_audits),
            "time_control": self.time_control.to_json(),
            "limits": self.limits.to_json(),
            "resources": self.resources.to_json(),
            "bootstrap_replicates": self.bootstrap_replicates,
            "rating_anchor": self.rating_anchor,
            "workers": self.workers,
            "include_self_play": self.include_self_play,
        }
        if self.deck_pool is None:
            assert self.decks is not None
            doc["decks"] = [deck.to_json() for deck in self.decks]
        else:
            doc["deck_pool"] = [deck.to_json() for deck in self.deck_pool]
        if self.matchups is not None:
            doc["matchups"] = [list(pair) for pair in self.matchups]
        if self.opponent_panel:
            doc["opponent_panel"] = list(self.opponent_panel)
            doc["evaluation_version"] = self.evaluation_version
            if self.evaluation_engine_identity is not None:
                doc["evaluation_engine_identity"] = self.evaluation_engine_identity
            if self.evaluation_engine_inputs:
                doc["evaluation_engine_inputs"] = list(self.evaluation_engine_inputs)
        return doc

    @classmethod
    def from_json(cls, value: Any) -> "TournamentConfig":
        context = "config"
        if not isinstance(value, dict):
            raise TournamentError("config: must be an object")
        for field in sorted(_V1_FIELDS):
            if field in value:
                raise TournamentError(
                    f"{context}.{field}: v1 field; the v2 replacement is {_V1_FIELDS[field]}"
                )
        if "probe" in value:
            raise TournamentError(f"{context}.probe: reserved in protocol v2.0; hosts never set it")
        allowed = {
            "schema",
            "tournament_dir",
            "format",
            "decks",
            "deck_pool",
            "engine",
            "bots",
            "pairs_per_matchup",
            "stats_seed",
            "rules",
            "extensions",
            "native_id_audits",
            "time_control",
            "limits",
            "resources",
            "bootstrap_replicates",
            "rating_anchor",
            "workers",
            "include_self_play",
            "matchups",
            "opponent_panel",
            "evaluation_version",
            "evaluation_engine_identity",
            "evaluation_engine_inputs",
        }
        required = {
            "schema",
            "tournament_dir",
            "format",
            "engine",
            "bots",
            "pairs_per_matchup",
            "stats_seed",
        }
        missing = required - set(value)
        extra = set(value) - allowed
        if missing or extra:
            raise TournamentError(
                f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}"
            )
        if value["schema"] != CONFIG_SCHEMA:
            raise TournamentError(f'{context}.schema: must be "{CONFIG_SCHEMA}"')
        has_decks, has_pool = "decks" in value, "deck_pool" in value
        if has_decks and has_pool:
            raise TournamentError(f"{context}: give decks or deck_pool, not both")
        if not has_decks and not has_pool:
            raise TournamentError(f"{context}: requires decks (a fixed pair) or deck_pool")
        decks: tuple[DeckSpec, DeckSpec] | None = None
        deck_pool: tuple[DeckSpec, ...] | None = None
        if has_decks:
            raw_decks = value["decks"]
            if not isinstance(raw_decks, list) or len(raw_decks) != 2:
                raise TournamentError(f"{context}.decks: must be a list of two decks (p0 first)")
            decks = (
                DeckSpec.from_json(raw_decks[0], f"{context}.decks[0]"),
                DeckSpec.from_json(raw_decks[1], f"{context}.decks[1]"),
            )
        else:
            raw_pool = value["deck_pool"]
            if not isinstance(raw_pool, list) or not raw_pool:
                raise TournamentError(f"{context}.deck_pool: must be a nonempty list of decks")
            deck_pool = tuple(
                DeckSpec.from_json(item, f"{context}.deck_pool[{i}]") for i, item in enumerate(raw_pool)
            )
            if len(set(deck_pool)) != len(deck_pool):
                raise TournamentError(f"{context}.deck_pool: decks must be distinct")
        tournament_dir = _req_str(value["tournament_dir"], f"{context}.tournament_dir")
        format_ = _req_str(value["format"], f"{context}.format")
        raw_engine = value["engine"]
        if not isinstance(raw_engine, dict):
            raise TournamentError(f"{context}.engine: must be an object")
        if "timeout_ms" in raw_engine:
            raise TournamentError(
                f"{context}.engine.timeout_ms: v1 field; the v2 replacement is time_control.engine_step_ms"
            )
        if set(raw_engine) != {"command"}:
            raise TournamentError(f"{context}.engine: holds exactly one field, command")
        command = raw_engine["command"]
        if not isinstance(command, list) or not command or any(type(p) is not str or not p for p in command):
            raise TournamentError(f"{context}.engine.command: must be a nonempty list of strings")
        raw_bots = value["bots"]
        if not isinstance(raw_bots, list) or not raw_bots:
            raise TournamentError(f"{context}.bots: must be a nonempty list")
        bots = tuple(_bot_spec_from_json(item, f"{context}.bots[{i}]") for i, item in enumerate(raw_bots))
        names = [spec.name for spec in bots]
        if len(set(names)) != len(names):
            raise TournamentError(f"{context}.bots: names must be unique, got {names}")
        pairs_per_matchup = _req_uint(value["pairs_per_matchup"], f"{context}.pairs_per_matchup", minimum=1)
        if deck_pool is not None and pairs_per_matchup % len(deck_pool):
            raise TournamentError(
                f"{context}.pairs_per_matchup: {pairs_per_matchup} is not a multiple of the "
                f"{len(deck_pool)} deck_pool decks (every matchup plays every deck equally)"
            )
        include_self_play = value.get("include_self_play", True)
        if type(include_self_play) is not bool:
            raise TournamentError(f"{context}.include_self_play: must be true or false")
        if not include_self_play and len(bots) < 2:
            raise TournamentError(f"{context}.include_self_play: false needs at least two bots")
        matchups = None
        if "matchups" in value:
            raw = value["matchups"]
            if not isinstance(raw, list):
                raise TournamentError("config.matchups: must be a list of bot-name pairs")
            checked = []
            seen = set()
            for pair in raw:
                if not isinstance(pair, list) or len(pair) != 2 or any(type(n) is not str or n not in names for n in pair):
                    raise TournamentError("config.matchups: every pair must name two configured bots")
                key = tuple(sorted(pair))
                if pair[0] == pair[1] or key in seen:
                    raise TournamentError("config.matchups: self-play and duplicate matchups are not allowed")
                seen.add(key)
                checked.append(tuple(pair))
            matchups = tuple(checked)
        panel = value.get("opponent_panel", [])
        if not isinstance(panel, list) or any(type(n) is not str or n not in names for n in panel) or len(set(panel)) != len(panel):
            raise TournamentError("config.opponent_panel: must name distinct configured bots")
        evaluation_version = value.get("evaluation_version")
        if panel:
            _req_str(evaluation_version, "config.evaluation_version")
        elif "evaluation_version" in value:
            raise TournamentError("config.evaluation_version: requires opponent_panel")
        engine_identity = value.get("evaluation_engine_identity")
        if "evaluation_engine_identity" in value and (not panel or type(engine_identity) is not str or len(engine_identity) != 64 or any(c not in "0123456789abcdef" for c in engine_identity)):
            raise TournamentError("config.evaluation_engine_identity: needs a panel and 64 lowercase hex characters")
        engine_inputs = value.get("evaluation_engine_inputs", [])
        if not isinstance(engine_inputs, list) or any(type(path) is not str or not path for path in engine_inputs) or len(set(engine_inputs)) != len(engine_inputs) or (engine_inputs and not panel):
            raise TournamentError("config.evaluation_engine_inputs: must name distinct input files for a panel")
        stats_seed = _req_uint(value["stats_seed"], f"{context}.stats_seed")
        rules = RulesSpec.from_json(value["rules"], f"{context}.rules") if "rules" in value else RulesSpec()
        raw_extensions = value.get("extensions", [])
        if not isinstance(raw_extensions, list) or any(
            type(item) is not str or not EXTENSION_KEY_RE.fullmatch(item) for item in raw_extensions
        ):
            raise TournamentError(f"{context}.extensions: must be a list of extension names (x_[a-z0-9_]+)")
        extensions = tuple(raw_extensions)
        if len(set(extensions)) != len(extensions):
            raise TournamentError(f"{context}.extensions: duplicate names")
        raw_audits = value.get("native_id_audits", {})
        if not isinstance(raw_audits, dict):
            raise TournamentError(f"{context}.native_id_audits: must be an object of extension: audit reference")
        native_id_audits: dict[str, str] = {}
        for extension, reference in raw_audits.items():
            if extension not in extensions:
                raise TournamentError(
                    f"{context}.native_id_audits: {extension!r} is not one of config.extensions"
                )
            native_id_audits[extension] = _req_str(reference, f"{context}.native_id_audits[{extension!r}]")
        time_control = _spec_block(
            TimeControl, value.get("time_control", DEFAULT_TIME_CONTROL.to_json()), f"{context}.time_control"
        )
        limits = _spec_block(Limits, value.get("limits", DEFAULT_LIMITS.to_json()), f"{context}.limits")
        resources = _spec_block(
            Resources, value.get("resources", DEFAULT_RESOURCES.to_json()), f"{context}.resources"
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
        # The leaderboard's bootstraps refuse oversized inputs; refuse such a
        # config now rather than after every game has been played.
        rated_pairs = (len(matchups) if matchups is not None else len(bots) * (len(bots) - 1) // 2) * pairs_per_matchup
        if (
            pairs_per_matchup > ratings.MAX_PAIR_COUNT
            or max(pairs_per_matchup, rated_pairs) * bootstrap_replicates > ratings.MAX_BOOTSTRAP_DRAWS
        ):
            raise TournamentError(
                f"{context}: the bootstrap would draw {max(pairs_per_matchup, rated_pairs) * bootstrap_replicates} "
                f"pairs (limit {ratings.MAX_BOOTSTRAP_DRAWS}, at most {ratings.MAX_PAIR_COUNT} pairs per "
                "matchup); lower bootstrap_replicates or pairs_per_matchup"
            )
        return cls(
            tournament_dir=tournament_dir,
            format=format_,
            decks=decks,
            deck_pool=deck_pool,
            engine_command=tuple(command),
            bots=bots,
            pairs_per_matchup=pairs_per_matchup,
            stats_seed=stats_seed,
            rules=rules,
            extensions=extensions,
            native_id_audits=native_id_audits,
            time_control=time_control,
            limits=limits,
            resources=resources,
            bootstrap_replicates=bootstrap_replicates,
            rating_anchor=rating_anchor,
            workers=workers,
            include_self_play=include_self_play,
            matchups=matchups,
            opponent_panel=tuple(panel),
            evaluation_version=evaluation_version,
            evaluation_engine_identity=engine_identity,
            evaluation_engine_inputs=tuple(engine_inputs),
        )
