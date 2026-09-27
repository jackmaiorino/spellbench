"""Engine-role messages and the protocol types both roles share (spec 4, 9, 11.4, 12).

The authority is ``spec/SPELLBENCH_PROTOCOL_V2.md``. Engines and the host fail closed
(spec 4.2): ``from_json`` accepts exactly the fields a message or object lists, and the
first problem raises :class:`ValidationError` (``malformed_request``) whose message starts
with its path, for example ``hello_ok.catalog[0] (Burn).decklist[2].name``. Each class
keeps its rules in one ``_check`` over the JSON form, which ``from_json`` applies to its
input and ``__post_init__`` to ``to_json()``, so constructing a message checks it too and
the host cannot build one the spec does not license.

Python values hold tuples where the JSON holds arrays, and ``to_json`` returns new
containers, except for the two objects carried as received: a decision's
``seat_decision``, which the host's live validator checks before forwarding it (spec
11.3), and a selection's ``semantic_echo``, which the engine compares field for field
with the chosen candidate's ``semantic`` (spec 9.4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import digests
from ._schema import (
    EXTENSION_KEY_RE,
    OBSERVATION_FLAGS,
    REQUIRED_KINDS,
    RESERVED_KINDS,
    SEATS,
    V2_KINDS,
    array,
    as_object,
    boolean,
    card_name,
    exact_keys,
    fail,
    nonempty,
    nullable,
    safe_int,
    snake,
    text,
    u32,
    vocab,
)

PROTOCOL = "spellbench/v2"
PROTOCOL_MINOR = 0
# Spec 9.8, in table order.
ENGINE_ERROR_CODES = frozenset(
    {
        "malformed_json",
        "malformed_request",
        "protocol_mismatch",
        "request_id_reuse_mismatch",
        "step_before_reset",
        "game_already_active",
        "game_id_mismatch",
        "expected_step_mismatch",
        "candidate_id_out_of_range",
        "semantic_echo_mismatch",
        "unsupported_format",
        "unsupported_deck",
        "deck_id_mismatch",
        "unsupported_rule",
        "unsupported_request",
        "probe_refused",
        "game_already_terminal",
    }
)
MULLIGAN_RULES = ("london", "none")
STARTING_PLAYER_RULES = ("host_assigned", "toss_winner_chooses")
DECK_SOURCES = ("catalog", "decklist")
ENGINE_DEFAULT_KEYS = ("trigger_order", "replacement_order", "combat_damage_assignment", "mana_payment")

# Spec 7.6, 9.1: each engine default is null or this one value.
_ENGINE_DEFAULT_VALUES = {
    "trigger_order": "engine_order",
    "replacement_order": "engine_order",
    "combat_damage_assignment": "engine_order",
    "mana_payment": "engine_autopay",
}
# Spec 9.1: rules_supported holds exactly these vocabularies.
_RULE_VOCABULARIES = {"mulligan": MULLIGAN_RULES, "starting_player": STARTING_PLAYER_RULES}
# Spec 12.2.
_OPPONENT_DECKLIST_RULES = ("visible", "hidden")
# Spec 9.5; forfeit is the host's classification alone (spec 11.5).
_OUTCOMES = ("p0_win", "p1_win", "draw", "truncated", "halted")
_CLASSIFICATIONS = ("natural", "truncated", "halted")
_NATURAL_WINNERS = {"p0_win": "p0", "p1_win": "p1", "draw": None}
# Spec 4.3: "sha256:" and 64 lowercase hex digits. Spec 9.2: a game secret is 64 lowercase hex digits.
_DECK_ID_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_GAME_SECRET_RE = re.compile(r"\A[0-9a-f]{64}\Z")

_PROVENANCE_FIELDS = ("engine_name", "engine_version", "rules_snapshot_id", "card_pool_identity")
_ENGINE_FIELDS = ("name", "version", "source_revision", "rules_snapshot_id", "card_pool_identity")
_PROFILE_FIELDS = (
    "rules_supported",
    "observation",
    "decision_kinds",
    "engine_defaults",
    "rewind",
    "fairness",
    "extensions",
)
_HELLO_OK_FIELDS = ("protocol_minor", "engine", "formats", "deck_sources", "catalog", *_PROFILE_FIELDS)
_RULES_FIELDS = (
    "opponent_decklist",
    "mulligan",
    "starting_player",
    "starting_seat",
    "card_name_domain",
    "extensions",
    "probe",
)
_RESET_FIELDS = ("game_id", "format", "seats", "rules", "game_secret", "max_decisions", "max_steps")
_RESULT_FIELDS = ("outcome", "classification", "winner", "reason", "step_count", "decision_count")
_TIME_CONTROL_FIELDS = ("startup_ms", "game_start_ms", "bank_ms", "increment_ms", "max_decision_ms", "engine_step_ms")
_LIMITS_FIELDS = (
    "max_decisions",
    "max_steps",
    "max_seat_decisions_per_turn",
    "max_seat_decisions_per_game",
    "max_seat_steps_per_game",
)
# Spec 11.1, 11.4: each per-seat per-game cap is strictly below half of the matching game cap.
_SEAT_CAPS = (("max_seat_decisions_per_game", "max_decisions"), ("max_seat_steps_per_game", "max_steps"))
_RESOURCES_FIELDS = ("cpus", "memory_mb", "gpu", "engine_cpus")


def _object(value: Any, fields: Iterable[str], context: str) -> dict[str, Any]:
    """An object with exactly ``fields`` (spec 4.2: every listed field is required, and no other is allowed)."""
    checked = as_object(value, context)
    exact_keys(checked, fields, context)
    return checked


def _message(value: Any, context: str, tag_key: str, tag: str, fields: Iterable[str]) -> dict[str, Any]:
    """A request or response: exactly the envelope and ``fields``, with its type and protocol (spec 4.1)."""
    message = _object(value, (tag_key, "protocol", "request_id", *fields), context)
    received = text(message[tag_key], f"{context}.{tag_key}")
    if received != tag:
        fail(f"{context}.{tag_key}", f'must be "{tag}", got {received!r}')
    protocol = text(message["protocol"], f"{context}.protocol")
    if protocol != PROTOCOL:
        fail(f"{context}.protocol", f'must be "{PROTOCOL}", got {protocol!r}')
    return message


def _envelope(tag_key: str, tag: str, request_id: str) -> dict[str, Any]:
    return {tag_key: tag, "protocol": PROTOCOL, "request_id": request_id}


def _at_least(value: Any, minimum: int, context: str, bounded: Callable[[Any, str], int] = safe_int) -> int:
    """An integer that ``bounded`` accepts (spec 4.4) and that is at least ``minimum``."""
    if bounded(value, context) < minimum:
        fail(context, f"must be at least {minimum}")
    return value


def _distinct(values: Sequence[Any], context: str, suffix: str = "") -> None:
    """No value repeats (the values are checked strings, so they hash); the error names the repeat."""
    seen: set[Any] = set()
    for index, value in enumerate(values):
        if value in seen:
            fail(f"{context}[{index}]{suffix}", f"{value!r} appears twice")
        seen.add(value)


def _subset(value: Any, allowed: Sequence[str], context: str) -> list[Any]:
    """A nonempty array of distinct members of a closed vocabulary."""
    items = array(value, context, min_length=1)
    for index, item in enumerate(items):
        vocab(item, allowed, f"{context}[{index}]")
    _distinct(items, context)
    return items


def _extension_name(value: Any, context: str) -> str:
    """An extension name, ``x_[a-z0-9_]+`` (spec 14)."""
    if not EXTENSION_KEY_RE.fullmatch(text(value, context)):
        fail(context, f"{value!r} is not an extension name (x_[a-z0-9_]+)")
    return value


def _check_decision_kinds(value: Any, context: str) -> None:
    """Distinct v2.0 kinds that include the required five (spec 9.1); a reserved kind fails as reserved (spec 7.7)."""
    kinds = array(value, context)
    for index, kind in enumerate(kinds):
        where = f"{context}[{index}]"
        if text(kind, where) in RESERVED_KINDS:
            fail(where, f"{kind!r} is reserved for a later minor version (spec 7.7)")
        if kind not in V2_KINDS:
            fail(where, f"{kind!r} is not a v2.0 decision kind")
    _distinct(kinds, context)
    missing = REQUIRED_KINDS.difference(kinds)
    if missing:
        fail(context, f"must include {', '.join(sorted(missing))}")


def _check_decklist(value: Any, context: str) -> None:
    """A decklist (spec 12.1), checked by ``digests.deck_rows``, whose errors name the card after ``context``."""
    digests.deck_rows(array(value, context), context)


def _rows(rows: Iterable[Mapping[str, Any]]) -> tuple[DeckRow, ...]:
    """Checked decklist rows as DeckRows, in the order given."""
    return tuple(DeckRow(row["name"], row["count"]) for row in rows)


def _instance(value: Any, kind: type, context: str) -> Any:
    """A nested Python value: an instance of ``kind``."""
    if not isinstance(value, kind):
        fail(context, f"must be {kind.__name__}, got {type(value).__name__}")
    return value


def _tuple(value: Any, context: str, kind: type | None = None) -> tuple[Any, ...]:
    """A Python array: a tuple, of ``kind`` instances when given (checked before ``to_json`` reads it)."""
    if type(value) is not tuple:
        fail(context, f"must be a tuple, got {type(value).__name__}")
    if kind is not None:
        for index, item in enumerate(value):
            _instance(item, kind, f"{context}[{index}]")
    return value


# ---------------------------------------------------------------------------
# Engine identity, decks and the engine profile (spec 9.1, 12.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """The engine identity that every ``decision`` and ``terminal`` repeats (spec 9.3, 9.5)."""

    engine_name: str
    engine_version: str
    rules_snapshot_id: str
    card_pool_identity: str

    def __post_init__(self) -> None:
        self._check(self.to_json(), "provenance")

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _PROVENANCE_FIELDS}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        provenance = _object(value, _PROVENANCE_FIELDS, context)
        for name in _PROVENANCE_FIELDS:
            nonempty(provenance[name], f"{context}.{name}")

    @classmethod
    def from_json(cls, value: Any, context: str = "provenance") -> Provenance:
        cls._check(value, context)
        return cls(**value)


@dataclass(frozen=True)
class EngineIdentity:
    """The ``engine`` object of ``hello_ok`` and ``game_start`` (spec 9.1, 10.2)."""

    name: str
    version: str
    source_revision: str | None
    rules_snapshot_id: str
    card_pool_identity: str

    def __post_init__(self) -> None:
        self._check(self.to_json(), "engine")

    def provenance(self) -> Provenance:
        """The identity as decisions and terminals repeat it."""
        return Provenance(self.name, self.version, self.rules_snapshot_id, self.card_pool_identity)

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _ENGINE_FIELDS}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        engine = _object(value, _ENGINE_FIELDS, context)
        for name in _ENGINE_FIELDS:
            if name == "source_revision":
                nullable(engine[name], text, f"{context}.{name}")  # a string or null
            else:
                nonempty(engine[name], f"{context}.{name}")

    @classmethod
    def from_json(cls, value: Any, context: str = "engine") -> EngineIdentity:
        cls._check(value, context)
        return cls(**value)


@dataclass(frozen=True)
class DeckRow:
    """A decklist row: an Oracle name in NFC and a count of at least 1 (spec 12.1)."""

    name: str
    count: int

    def __post_init__(self) -> None:
        self._check(self.to_json(), "deck_row")

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "count": self.count}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        row = _object(value, ("name", "count"), context)
        card_name(row["name"], f"{context}.name")
        _at_least(row["count"], 1, f"{context}.count", u32)

    @classmethod
    def from_json(cls, value: Any, context: str = "deck_row") -> DeckRow:
        cls._check(value, context)
        return cls(value["name"], value["count"])


@dataclass(frozen=True)
class CatalogDeck:
    """A deck of ``hello_ok.catalog`` with its full list (spec 9.1, 12.1)."""

    catalog_id: str
    name: str
    decklist: tuple[DeckRow, ...]

    def __post_init__(self) -> None:
        _tuple(self.decklist, "catalog_deck.decklist", DeckRow)
        self._check(self.to_json(), "catalog_deck")

    def to_json(self) -> dict[str, Any]:
        return {"catalog_id": self.catalog_id, "name": self.name, "decklist": [row.to_json() for row in self.decklist]}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        deck = _object(value, ("catalog_id", "name", "decklist"), context)
        catalog_id = nonempty(deck["catalog_id"], f"{context}.catalog_id")
        nonempty(deck["name"], f"{context}.name")
        # The context names the deck, and deck_rows names the card, for example a name that is not NFC.
        _check_decklist(deck["decklist"], f"{context} ({catalog_id}).decklist")

    @classmethod
    def from_json(cls, value: Any, context: str = "catalog_deck") -> CatalogDeck:
        cls._check(value, context)
        return cls(value["catalog_id"], value["name"], _rows(value["decklist"]))


@dataclass(frozen=True)
class ExtensionDecl:
    """An ``x_`` key the engine can emit, and whether it carries engine-native ids (spec 9.1, 14)."""

    name: str
    native_ids: bool

    def __post_init__(self) -> None:
        self._check(self.to_json(), "extension")

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "native_ids": self.native_ids}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        declaration = _object(value, ("name", "native_ids"), context)
        _extension_name(declaration["name"], f"{context}.name")
        boolean(declaration["native_ids"], f"{context}.native_ids")

    @classmethod
    def from_json(cls, value: Any, context: str = "extension") -> ExtensionDecl:
        cls._check(value, context)
        return cls(value["name"], value["native_ids"])


@dataclass(frozen=True)
class EngineProfile:
    """What an engine declares about play (spec 9.1).

    ``hello_ok`` holds these fields at its top level; ``to_json()`` is the ``game_start.engine_profile``
    object (spec 10.2).
    """

    rules_supported: dict[str, tuple[str, ...]]
    observation: dict[str, bool]
    decision_kinds: tuple[str, ...]
    engine_defaults: dict[str, str | None]
    rewind: bool
    fairness: dict[str, bool]
    extensions: tuple[ExtensionDecl, ...]

    def __post_init__(self) -> None:
        for name in ("rules_supported", "observation", "engine_defaults", "fairness"):
            _instance(getattr(self, name), dict, f"engine_profile.{name}")
        for key, values in self.rules_supported.items():
            _tuple(values, f"engine_profile.rules_supported.{key}")
        _tuple(self.decision_kinds, "engine_profile.decision_kinds")
        _tuple(self.extensions, "engine_profile.extensions", ExtensionDecl)
        self._check(self.to_json(), "engine_profile")

    def to_json(self) -> dict[str, Any]:
        return {
            "rules_supported": {key: list(values) for key, values in self.rules_supported.items()},
            "observation": dict(self.observation),
            "decision_kinds": list(self.decision_kinds),
            "engine_defaults": dict(self.engine_defaults),
            "rewind": self.rewind,
            "fairness": dict(self.fairness),
            "extensions": [declaration.to_json() for declaration in self.extensions],
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        EngineProfile._check_fields(_object(value, _PROFILE_FIELDS, context), context)

    @staticmethod
    def _check_fields(value: Mapping[str, Any], context: str) -> None:
        """The profile fields of ``value``, a profile or a ``hello_ok``, whose keys are already checked."""
        supported = _object(value["rules_supported"], _RULE_VOCABULARIES.keys(), f"{context}.rules_supported")
        for key, vocabulary in _RULE_VOCABULARIES.items():
            _subset(supported[key], vocabulary, f"{context}.rules_supported.{key}")
        flags = _object(value["observation"], OBSERVATION_FLAGS, f"{context}.observation")
        for flag in OBSERVATION_FLAGS:
            boolean(flags[flag], f"{context}.observation.{flag}")
        _check_decision_kinds(value["decision_kinds"], f"{context}.decision_kinds")
        defaults = _object(value["engine_defaults"], ENGINE_DEFAULT_KEYS, f"{context}.engine_defaults")
        for key in ENGINE_DEFAULT_KEYS:
            allowed = _ENGINE_DEFAULT_VALUES[key]
            if defaults[key] is not None and defaults[key] != allowed:
                fail(f"{context}.engine_defaults.{key}", f'must be null or "{allowed}", got {defaults[key]!r}')
        boolean(value["rewind"], f"{context}.rewind")
        fairness = _object(value["fairness"], ("noninterference_probe",), f"{context}.fairness")
        boolean(fairness["noninterference_probe"], f"{context}.fairness.noninterference_probe")
        extensions = array(value["extensions"], f"{context}.extensions")
        for index, declaration in enumerate(extensions):
            ExtensionDecl._check(declaration, f"{context}.extensions[{index}]")
        # One entry per key: a repeated name could declare native_ids both ways.
        _distinct([declaration["name"] for declaration in extensions], f"{context}.extensions", ".name")

    @classmethod
    def from_json(cls, value: Any, context: str = "engine_profile") -> EngineProfile:
        cls._check(value, context)
        return cls(
            rules_supported={key: tuple(value["rules_supported"][key]) for key in _RULE_VOCABULARIES},
            observation={flag: value["observation"][flag] for flag in OBSERVATION_FLAGS},
            decision_kinds=tuple(value["decision_kinds"]),
            engine_defaults={key: value["engine_defaults"][key] for key in ENGINE_DEFAULT_KEYS},
            rewind=value["rewind"],
            fairness={"noninterference_probe": value["fairness"]["noninterference_probe"]},
            extensions=tuple(
                ExtensionDecl.from_json(declaration, f"{context}.extensions[{index}]")
                for index, declaration in enumerate(value["extensions"])
            ),
        )


# ---------------------------------------------------------------------------
# hello (spec 9.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HelloRequest:
    """The host's ``hello``, with its minor version (spec 4.2, 9.1)."""

    request_id: str
    protocol_minor: int

    def __post_init__(self) -> None:
        self._check(self.to_json(), "hello")

    def to_json(self) -> dict[str, Any]:
        return {**_envelope("request_type", "hello", self.request_id), "protocol_minor": self.protocol_minor}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        hello = _message(value, context, "request_type", "hello", ("protocol_minor",))
        nonempty(hello["request_id"], f"{context}.request_id")
        u32(hello["protocol_minor"], f"{context}.protocol_minor")

    @classmethod
    def from_json(cls, value: Any, context: str = "hello") -> HelloRequest:
        cls._check(value, context)
        return cls(value["request_id"], value["protocol_minor"])


@dataclass(frozen=True)
class EnvHelloOk:
    """An engine's ``hello_ok`` (spec 9.1); its JSON holds the profile fields at the top level."""

    request_id: str
    protocol_minor: int
    engine: EngineIdentity
    formats: tuple[str, ...]
    deck_sources: tuple[str, ...]
    catalog: tuple[CatalogDeck, ...]
    profile: EngineProfile

    def __post_init__(self) -> None:
        _instance(self.engine, EngineIdentity, "hello_ok.engine")
        _tuple(self.formats, "hello_ok.formats")
        _tuple(self.deck_sources, "hello_ok.deck_sources")
        _tuple(self.catalog, "hello_ok.catalog", CatalogDeck)
        _instance(self.profile, EngineProfile, "hello_ok.profile")
        self._check(self.to_json(), "hello_ok")

    def to_json(self) -> dict[str, Any]:
        return {
            **_envelope("response_type", "hello_ok", self.request_id),
            "protocol_minor": self.protocol_minor,
            "engine": self.engine.to_json(),
            "formats": list(self.formats),
            "deck_sources": list(self.deck_sources),
            "catalog": [deck.to_json() for deck in self.catalog],
            **self.profile.to_json(),
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        hello = _message(value, context, "response_type", "hello_ok", _HELLO_OK_FIELDS)
        nonempty(hello["request_id"], f"{context}.request_id")
        u32(hello["protocol_minor"], f"{context}.protocol_minor")  # spec 4.2
        EngineIdentity._check(hello["engine"], f"{context}.engine")
        formats = array(hello["formats"], f"{context}.formats", min_length=1)
        for index, format_id in enumerate(formats):
            nonempty(format_id, f"{context}.formats[{index}]")
        sources = _subset(hello["deck_sources"], DECK_SOURCES, f"{context}.deck_sources")
        catalog = array(hello["catalog"], f"{context}.catalog")
        if catalog and "catalog" not in sources:
            fail(f"{context}.catalog", "must be empty when deck_sources lacks catalog")
        for index, deck in enumerate(catalog):
            CatalogDeck._check(deck, f"{context}.catalog[{index}]")
        _distinct([deck["catalog_id"] for deck in catalog], f"{context}.catalog", ".catalog_id")
        EngineProfile._check_fields(hello, context)

    @classmethod
    def from_json(cls, value: Any, context: str = "hello_ok") -> EnvHelloOk:
        cls._check(value, context)
        return cls(
            request_id=value["request_id"],
            protocol_minor=value["protocol_minor"],
            engine=EngineIdentity.from_json(value["engine"], f"{context}.engine"),
            formats=tuple(value["formats"]),
            deck_sources=tuple(value["deck_sources"]),
            catalog=tuple(
                CatalogDeck.from_json(deck, f"{context}.catalog[{index}]")
                for index, deck in enumerate(value["catalog"])
            ),
            profile=EngineProfile.from_json({key: value[key] for key in _PROFILE_FIELDS}, context),
        )


# ---------------------------------------------------------------------------
# reset and the information rules (spec 9.2, 12.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardNameDomain:
    """``rules.card_name_domain``: the public names a card-name choice offers, and their id (spec 4.3, 12.2)."""

    domain_id: str
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        _tuple(self.names, "card_name_domain.names")
        self._check(self.to_json(), "card_name_domain")

    def to_json(self) -> dict[str, Any]:
        return {"domain_id": self.domain_id, "names": list(self.names)}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        domain = _object(value, ("domain_id", "names"), context)
        names = array(domain["names"], f"{context}.names")
        for index, name in enumerate(names):
            card_name(name, f"{context}.names[{index}]")
        _distinct(names, f"{context}.names")
        expected = digests.domain_id(names)
        if text(domain["domain_id"], f"{context}.domain_id") != expected:
            fail(f"{context}.domain_id", f"does not match the names, whose domain_id is {expected}")

    @classmethod
    def from_json(cls, value: Any, context: str = "card_name_domain") -> CardNameDomain:
        cls._check(value, context)
        return cls(value["domain_id"], tuple(value["names"]))


@dataclass(frozen=True)
class Rules:
    """The information rules that ``reset`` and ``game_start`` carry (spec 9.2, 12.2)."""

    opponent_decklist: str
    mulligan: str
    starting_player: str
    starting_seat: str | None
    card_name_domain: CardNameDomain
    extensions: tuple[str, ...]
    probe: bool

    def __post_init__(self) -> None:
        _instance(self.card_name_domain, CardNameDomain, "rules.card_name_domain")
        _tuple(self.extensions, "rules.extensions")
        self._check(self.to_json(), "rules")

    def to_json(self) -> dict[str, Any]:
        return {
            "opponent_decklist": self.opponent_decklist,
            "mulligan": self.mulligan,
            "starting_player": self.starting_player,
            "starting_seat": self.starting_seat,
            "card_name_domain": self.card_name_domain.to_json(),
            "extensions": list(self.extensions),
            "probe": self.probe,
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        rules = _object(value, _RULES_FIELDS, context)
        vocab(rules["opponent_decklist"], _OPPONENT_DECKLIST_RULES, f"{context}.opponent_decklist")
        vocab(rules["mulligan"], MULLIGAN_RULES, f"{context}.mulligan")
        starting_player = vocab(rules["starting_player"], STARTING_PLAYER_RULES, f"{context}.starting_player")
        starting_seat = rules["starting_seat"]
        if starting_player == "host_assigned":
            if type(starting_seat) is not str or starting_seat not in SEATS:
                fail(f"{context}.starting_seat", f"must be p0 or p1 with host_assigned, got {starting_seat!r}")
        elif starting_seat is not None:
            fail(f"{context}.starting_seat", f"must be null with toss_winner_chooses, got {starting_seat!r}")
        CardNameDomain._check(rules["card_name_domain"], f"{context}.card_name_domain")
        extensions = array(rules["extensions"], f"{context}.extensions")
        for index, name in enumerate(extensions):
            _extension_name(name, f"{context}.extensions[{index}]")
        _distinct(extensions, f"{context}.extensions")
        boolean(rules["probe"], f"{context}.probe")

    @classmethod
    def from_json(cls, value: Any, context: str = "rules") -> Rules:
        cls._check(value, context)
        return cls(
            opponent_decklist=value["opponent_decklist"],
            mulligan=value["mulligan"],
            starting_player=value["starting_player"],
            starting_seat=value["starting_seat"],
            card_name_domain=CardNameDomain.from_json(value["card_name_domain"], f"{context}.card_name_domain"),
            extensions=tuple(value["extensions"]),
            probe=value["probe"],
        )


@dataclass(frozen=True)
class WireDeck:
    """A seat's deck in ``reset``: exactly ``{deck_id, catalog_id}`` or ``{deck_id, decklist}`` (spec 9.2).

    Only the form of ``deck_id`` is checked: an engine may compare it with the list and answer
    ``deck_id_mismatch``, which is not ``malformed_request`` (spec 9.2, 9.8).
    """

    deck_id: str
    catalog_id: str | None = None
    decklist: tuple[DeckRow, ...] | None = None

    def __post_init__(self) -> None:
        if self.decklist is not None:
            _tuple(self.decklist, "deck.decklist", DeckRow)
        self._check(self.to_json(), "deck")

    def to_json(self) -> dict[str, Any]:
        deck: dict[str, Any] = {"deck_id": self.deck_id}
        if self.catalog_id is not None:
            deck["catalog_id"] = self.catalog_id
        if self.decklist is not None:
            deck["decklist"] = [row.to_json() for row in self.decklist]
        return deck

    @staticmethod
    def _check(value: Any, context: str) -> None:
        deck = as_object(value, context)
        if deck.keys() not in ({"deck_id", "catalog_id"}, {"deck_id", "decklist"}):
            shapes = "{deck_id, catalog_id} or {deck_id, decklist}"
            fail(context, f"must be exactly {shapes}, got fields {sorted(deck)}")
        deck_id = text(deck["deck_id"], f"{context}.deck_id")
        if not _DECK_ID_RE.fullmatch(deck_id):
            fail(f"{context}.deck_id", f'must be "sha256:" and 64 lowercase hex digits, got {deck_id!r}')
        if "catalog_id" in deck:
            nonempty(deck["catalog_id"], f"{context}.catalog_id")
        else:
            _check_decklist(deck["decklist"], f"{context}.decklist")

    @classmethod
    def from_json(cls, value: Any, context: str = "deck") -> WireDeck:
        cls._check(value, context)
        if "catalog_id" in value:
            return cls(value["deck_id"], catalog_id=value["catalog_id"])
        return cls(value["deck_id"], decklist=_rows(value["decklist"]))


@dataclass(frozen=True)
class ResetRequest:
    """The ``reset`` request (spec 9.2). ``game_secret`` stays out of the repr, so no error message prints it."""

    request_id: str
    game_id: str
    format: str
    seats: tuple[WireDeck, WireDeck]
    rules: Rules
    game_secret: str = field(repr=False)
    max_decisions: int
    max_steps: int

    def __post_init__(self) -> None:
        _tuple(self.seats, "reset.seats", WireDeck)
        if len(self.seats) != len(SEATS):
            fail("reset.seats", "must hold the p0 deck and the p1 deck")
        _instance(self.rules, Rules, "reset.rules")
        self._check(self.to_json(), "reset")

    def to_json(self) -> dict[str, Any]:
        return {
            **_envelope("request_type", "reset", self.request_id),
            "game_id": self.game_id,
            "format": self.format,
            "seats": [{"seat": name, "deck": deck.to_json()} for name, deck in zip(SEATS, self.seats)],
            "rules": self.rules.to_json(),
            "game_secret": self.game_secret,
            "max_decisions": self.max_decisions,
            "max_steps": self.max_steps,
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        reset = _message(value, context, "request_type", "reset", _RESET_FIELDS)
        nonempty(reset["request_id"], f"{context}.request_id")
        nonempty(reset["game_id"], f"{context}.game_id")
        nonempty(reset["format"], f"{context}.format")
        seats = array(reset["seats"], f"{context}.seats", min_length=len(SEATS), max_length=len(SEATS))
        for index, entry in enumerate(seats):
            where = f"{context}.seats[{index}]"
            seat_entry = _object(entry, ("seat", "deck"), where)
            if seat_entry["seat"] != SEATS[index]:
                fail(f"{where}.seat", f"must be {SEATS[index]} (seats list p0 then p1), got {seat_entry['seat']!r}")
            WireDeck._check(seat_entry["deck"], f"{where}.deck")
        Rules._check(reset["rules"], f"{context}.rules")
        secret = reset["game_secret"]
        if type(secret) is not str or not _GAME_SECRET_RE.fullmatch(secret):
            fail(f"{context}.game_secret", "must be 64 lowercase hex digits")  # the value is never quoted
        safe_int(reset["max_decisions"], f"{context}.max_decisions")
        safe_int(reset["max_steps"], f"{context}.max_steps")

    @classmethod
    def from_json(cls, value: Any, context: str = "reset") -> ResetRequest:
        cls._check(value, context)
        return cls(
            request_id=value["request_id"],
            game_id=value["game_id"],
            format=value["format"],
            seats=tuple(
                WireDeck.from_json(entry["deck"], f"{context}.seats[{index}].deck")
                for index, entry in enumerate(value["seats"])
            ),
            rules=Rules.from_json(value["rules"], f"{context}.rules"),
            game_secret=value["game_secret"],
            max_decisions=value["max_decisions"],
            max_steps=value["max_steps"],
        )


# ---------------------------------------------------------------------------
# decision, step and terminal (spec 9.3 to 9.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """A ``decision`` response (spec 9.3): the binding, with ``seat_decision`` checked only as an object.

    The host's live validator checks the seat decision before forwarding it (spec 11.3).
    """

    request_id: str
    game_id: str
    step: int
    seat_decision: dict[str, Any]
    provenance: Provenance

    def __post_init__(self) -> None:
        _instance(self.provenance, Provenance, "decision.provenance")
        self._check(self.to_json(), "decision")

    @property
    def acting_seat(self) -> str | None:
        """The seat decision's ``acting_seat`` when it is a seat, else None (the validator reports why)."""
        acting = self.seat_decision.get("acting_seat")
        return acting if type(acting) is str and acting in SEATS else None

    def to_json(self) -> dict[str, Any]:
        return {
            **_envelope("response_type", "decision", self.request_id),
            "game_id": self.game_id,
            "step": self.step,
            "seat_decision": self.seat_decision,
            "provenance": self.provenance.to_json(),
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        fields = ("game_id", "step", "seat_decision", "provenance")
        decision = _message(value, context, "response_type", "decision", fields)
        nonempty(decision["request_id"], f"{context}.request_id")
        nonempty(decision["game_id"], f"{context}.game_id")
        safe_int(decision["step"], f"{context}.step")
        as_object(decision["seat_decision"], f"{context}.seat_decision")
        Provenance._check(decision["provenance"], f"{context}.provenance")

    @classmethod
    def from_json(cls, value: Any, context: str = "decision") -> Decision:
        cls._check(value, context)
        return cls(
            request_id=value["request_id"],
            game_id=value["game_id"],
            step=value["step"],
            seat_decision=value["seat_decision"],
            provenance=Provenance.from_json(value["provenance"], f"{context}.provenance"),
        )


@dataclass(frozen=True)
class Selection:
    """A ``step`` selection: the candidate, and the echo of its ``semantic`` the host always sends (spec 9.4)."""

    candidate_id: int
    semantic_echo: dict[str, Any]

    def __post_init__(self) -> None:
        self._check(self.to_json(), "selection")

    def to_json(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "semantic_echo": self.semantic_echo}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        selection = _object(value, ("candidate_id", "semantic_echo"), context)
        u32(selection["candidate_id"], f"{context}.candidate_id")
        as_object(selection["semantic_echo"], f"{context}.semantic_echo")

    @classmethod
    def from_json(cls, value: Any, context: str = "selection") -> Selection:
        cls._check(value, context)
        return cls(value["candidate_id"], value["semantic_echo"])


@dataclass(frozen=True)
class StepRequest:
    """The ``step`` request (spec 9.4)."""

    request_id: str
    game_id: str
    expected_step: int
    selection: Selection

    def __post_init__(self) -> None:
        _instance(self.selection, Selection, "step.selection")
        self._check(self.to_json(), "step")

    def to_json(self) -> dict[str, Any]:
        return {
            **_envelope("request_type", "step", self.request_id),
            "game_id": self.game_id,
            "expected_step": self.expected_step,
            "selection": self.selection.to_json(),
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        step = _message(value, context, "request_type", "step", ("game_id", "expected_step", "selection"))
        nonempty(step["request_id"], f"{context}.request_id")
        nonempty(step["game_id"], f"{context}.game_id")
        safe_int(step["expected_step"], f"{context}.expected_step")
        Selection._check(step["selection"], f"{context}.selection")

    @classmethod
    def from_json(cls, value: Any, context: str = "step") -> StepRequest:
        cls._check(value, context)
        return cls(
            request_id=value["request_id"],
            game_id=value["game_id"],
            expected_step=value["expected_step"],
            selection=Selection.from_json(value["selection"], f"{context}.selection"),
        )


@dataclass(frozen=True)
class TerminalResult:
    """How a game ended, as its engine reports it (spec 9.5)."""

    outcome: str
    classification: str
    winner: str | None
    reason: str
    step_count: int
    decision_count: int

    def __post_init__(self) -> None:
        self._check(self.to_json(), "terminal")

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _RESULT_FIELDS}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        TerminalResult._check_fields(_object(value, _RESULT_FIELDS, context), context)

    @staticmethod
    def _check_fields(value: Mapping[str, Any], context: str) -> None:
        """The result fields of ``value``, a result or a ``terminal``, whose keys are already checked."""
        if value["classification"] == "forfeit":
            fail(f"{context}.classification", "forfeit is recorded by the host only; engines never send it (spec 11.5)")
        classification = vocab(value["classification"], _CLASSIFICATIONS, f"{context}.classification")
        outcome = vocab(value["outcome"], _OUTCOMES, f"{context}.outcome")
        winner = value["winner"]
        if classification == "natural":
            if outcome not in _NATURAL_WINNERS:
                fail(f"{context}.outcome", f"must be p0_win, p1_win or draw in a natural terminal, got {outcome!r}")
            expected = _NATURAL_WINNERS[outcome]
            if winner != expected:
                shown = "null" if expected is None else expected
                fail(f"{context}.winner", f"must be {shown} with outcome {outcome}, got {winner!r}")
        else:
            if outcome != classification:
                fail(f"{context}.outcome", f"must be {classification} in a {classification} terminal, got {outcome!r}")
            if winner is not None:
                fail(f"{context}.winner", f"must be null in a {classification} terminal, got {winner!r}")
        nonempty(value["reason"], f"{context}.reason")
        safe_int(value["step_count"], f"{context}.step_count")
        safe_int(value["decision_count"], f"{context}.decision_count")

    @classmethod
    def from_json(cls, value: Any, context: str = "terminal") -> TerminalResult:
        cls._check(value, context)
        return cls(**value)


@dataclass(frozen=True)
class Terminal:
    """A ``terminal`` response (spec 9.5); its JSON holds the result fields at the top level."""

    request_id: str
    game_id: str
    result: TerminalResult
    provenance: Provenance

    def __post_init__(self) -> None:
        _instance(self.result, TerminalResult, "terminal.result")
        _instance(self.provenance, Provenance, "terminal.provenance")
        self._check(self.to_json(), "terminal")

    def to_json(self) -> dict[str, Any]:
        return {
            **_envelope("response_type", "terminal", self.request_id),
            "game_id": self.game_id,
            **self.result.to_json(),
            "provenance": self.provenance.to_json(),
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        terminal = _message(value, context, "response_type", "terminal", ("game_id", *_RESULT_FIELDS, "provenance"))
        nonempty(terminal["request_id"], f"{context}.request_id")
        nonempty(terminal["game_id"], f"{context}.game_id")
        TerminalResult._check_fields(terminal, context)
        Provenance._check(terminal["provenance"], f"{context}.provenance")

    @classmethod
    def from_json(cls, value: Any, context: str = "terminal") -> Terminal:
        cls._check(value, context)
        return cls(
            request_id=value["request_id"],
            game_id=value["game_id"],
            result=TerminalResult(**{name: value[name] for name in _RESULT_FIELDS}),
            provenance=Provenance.from_json(value["provenance"], f"{context}.provenance"),
        )


# ---------------------------------------------------------------------------
# validate_deck and error (spec 9.6, 9.8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidateDeckRequest:
    """The optional ``validate_deck`` request (spec 9.6); its deck is ``{catalog_id}`` or ``{decklist}``."""

    request_id: str
    format: str
    catalog_id: str | None
    decklist: tuple[DeckRow, ...] | None

    def __post_init__(self) -> None:
        if self.decklist is not None:
            _tuple(self.decklist, "validate_deck.deck.decklist", DeckRow)
        self._check(self.to_json(), "validate_deck")

    def to_json(self) -> dict[str, Any]:
        deck: dict[str, Any] = {}
        if self.catalog_id is not None:
            deck["catalog_id"] = self.catalog_id
        if self.decklist is not None:
            deck["decklist"] = [row.to_json() for row in self.decklist]
        return {**_envelope("request_type", "validate_deck", self.request_id), "format": self.format, "deck": deck}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        request = _message(value, context, "request_type", "validate_deck", ("format", "deck"))
        nonempty(request["request_id"], f"{context}.request_id")
        nonempty(request["format"], f"{context}.format")
        deck = as_object(request["deck"], f"{context}.deck")
        if deck.keys() == {"catalog_id"}:
            nonempty(deck["catalog_id"], f"{context}.deck.catalog_id")
        elif deck.keys() == {"decklist"}:
            _check_decklist(deck["decklist"], f"{context}.deck.decklist")
        else:
            fail(f"{context}.deck", f"must be exactly {{catalog_id}} or {{decklist}}, got fields {sorted(deck)}")

    @classmethod
    def from_json(cls, value: Any, context: str = "validate_deck") -> ValidateDeckRequest:
        cls._check(value, context)
        deck = value["deck"]
        decklist = _rows(deck["decklist"]) if "decklist" in deck else None
        return cls(value["request_id"], value["format"], deck.get("catalog_id"), decklist)


@dataclass(frozen=True)
class DeckOk:
    """The ``deck_ok`` answer to ``validate_deck`` (spec 9.6)."""

    request_id: str

    def __post_init__(self) -> None:
        self._check(self.to_json(), "deck_ok")

    def to_json(self) -> dict[str, Any]:
        return _envelope("response_type", "deck_ok", self.request_id)

    @staticmethod
    def _check(value: Any, context: str) -> None:
        response = _message(value, context, "response_type", "deck_ok", ())
        nonempty(response["request_id"], f"{context}.request_id")

    @classmethod
    def from_json(cls, value: Any, context: str = "deck_ok") -> DeckOk:
        cls._check(value, context)
        return cls(value["request_id"])


@dataclass(frozen=True)
class ErrorResponse:
    """An ``error`` response (spec 9.8); ``request_id`` is ``""`` when the request's id was unreadable (spec 4.1)."""

    request_id: str
    code: str
    message: str

    def __post_init__(self) -> None:
        self._check(self.to_json(), "error")

    def to_json(self) -> dict[str, Any]:
        return {
            **_envelope("response_type", "error", self.request_id),
            "error": {"code": self.code, "message": self.message},
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        response = _message(value, context, "response_type", "error", ("error",))
        text(response["request_id"], f"{context}.request_id")
        error = _object(response["error"], ("code", "message"), f"{context}.error")
        snake(error["code"], f"{context}.error.code")
        text(error["message"], f"{context}.error.message")  # human-facing only (spec 9.8)

    @classmethod
    def from_json(cls, value: Any, *, codes: frozenset[str], context: str = "error") -> ErrorResponse:
        """The error, whose code must be in ``codes``, a role's closed table such as :data:`ENGINE_ERROR_CODES`."""
        cls._check(value, context)
        error = value["error"]
        if error["code"] not in codes:
            fail(f"{context}.error.code", f"{error['code']!r} is not in the closed code table")
        return cls(value["request_id"], error["code"], error["message"])


# ---------------------------------------------------------------------------
# Clocks, limits and resources (spec 11.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeControl:
    """A benchmark's clocks in milliseconds (spec 11.4): ``increment_ms`` at least 0, the others at least 1."""

    startup_ms: int
    game_start_ms: int
    bank_ms: int
    increment_ms: int
    max_decision_ms: int
    engine_step_ms: int

    def __post_init__(self) -> None:
        self._check(self.to_json(), "time_control")

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _TIME_CONTROL_FIELDS}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        clocks = _object(value, _TIME_CONTROL_FIELDS, context)
        for name in _TIME_CONTROL_FIELDS:
            _at_least(clocks[name], 0 if name == "increment_ms" else 1, f"{context}.{name}")

    @classmethod
    def from_json(cls, value: Any, context: str = "time_control") -> TimeControl:
        cls._check(value, context)
        return cls(**value)


@dataclass(frozen=True)
class Limits:
    """A benchmark's caps (spec 11.4); each per-seat per-game cap is strictly below half of its game cap (spec 11.1)."""

    max_decisions: int
    max_steps: int
    max_seat_decisions_per_turn: int
    max_seat_decisions_per_game: int
    max_seat_steps_per_game: int

    def __post_init__(self) -> None:
        self._check(self.to_json(), "limits")

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _LIMITS_FIELDS}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        limits = _object(value, _LIMITS_FIELDS, context)
        for name in _LIMITS_FIELDS:
            _at_least(limits[name], 1, f"{context}.{name}")
        for seat_cap, game_cap in _SEAT_CAPS:
            if not 2 * limits[seat_cap] < limits[game_cap]:
                fail(
                    f"{context}.{seat_cap}",
                    f"must be strictly below half of {game_cap} ({limits[game_cap]}), got {limits[seat_cap]}",
                )

    @classmethod
    def from_json(cls, value: Any, context: str = "limits") -> Limits:
        cls._check(value, context)
        return cls(**value)


@dataclass(frozen=True)
class Resources:
    """The declared cores, memory and GPU of each agent, and the engine's cores (spec 11.4)."""

    cpus: int
    memory_mb: int
    gpu: bool
    engine_cpus: int

    def __post_init__(self) -> None:
        self._check(self.to_json(), "resources")

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _RESOURCES_FIELDS}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        resources = _object(value, _RESOURCES_FIELDS, context)
        for name in ("cpus", "memory_mb", "engine_cpus"):
            _at_least(resources[name], 1, f"{context}.{name}", u32)  # counts and amounts are u32 (spec 4.4)
        boolean(resources["gpu"], f"{context}.gpu")

    @classmethod
    def from_json(cls, value: Any, context: str = "resources") -> Resources:
        cls._check(value, context)
        return cls(**value)
