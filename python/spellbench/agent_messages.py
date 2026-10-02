"""Agent-role messages (spec 10): what the host sends a bot, and what it reads back.

Agents are lenient readers, and the host reading agent responses is lenient too (spec 4.2,
10 intro): unknown fields anywhere are ignored, and the host needs only the fields each
response marks required. ``AgentHelloOk`` and ``Choice`` read leniently: ``from_json`` ignores
extra fields but still enforces the envelope binding (``response_type``, ``protocol``,
``request_id``) and every required field, so a present-but-malformed optional field (a bad
``requires`` or ``extensions_accepted``, a non-integer ``candidate_id``) fails fast rather than
being guessed at. ``OwnDeck``, ``Clock`` and ``AgentTerminal`` are messages the host itself
builds, so their ``from_json`` stays strict (spec 4.2), matching the engine-role messages in
``messages.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from . import digests
from ._schema import array, as_object, exact_keys, fail, nonempty, safe_int, text, vocab
from .messages import PROTOCOL, DeckRow, EngineIdentity, EngineProfile, Limits, Resources, Rules, TimeControl

# Spec 10.5, table order, R3-26.
AGENT_ERROR_CODES = frozenset(
    {
        "malformed_json",
        "malformed_request",
        "protocol_mismatch",
        "unknown_game",
        "game_already_active",
        "decision_pending",
        "internal_error",
    }
)

# Spec 9.5, reused for the forfeit pairing an agent's game_over adds (spec 11.5).
_NATURAL_WINNERS = {"p0_win": "p0", "p1_win": "p1", "draw": None}
_FORFEIT_WINNERS = {"p0_win": "p0", "p1_win": "p1"}
_TERMINAL_CLASSIFICATIONS = ("natural", "truncated", "halted", "forfeit")
# Spec 4.3: "sha256:" and 64 lowercase hex digits.
_DECK_ID_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


def _object(value: Any, fields: tuple[str, ...], context: str) -> dict[str, Any]:
    """A strictly-read object: exactly ``fields``, no more and no less (spec 4.2)."""
    checked = as_object(value, context)
    exact_keys(checked, fields, context)
    return checked


def _strings(value: Any, context: str) -> tuple[str, ...]:
    """A (possibly empty) array of strings; a present-but-malformed value fails, never guesses."""
    items = array(value, context)
    for index, item in enumerate(items):
        text(item, f"{context}[{index}]")
    return tuple(items)


def _rows(rows: Iterable[Mapping[str, Any]]) -> tuple[DeckRow, ...]:
    """Checked decklist rows as DeckRows, in the order given (matches ``messages._rows``)."""
    return tuple(DeckRow(row["name"], row["count"]) for row in rows)


# ---------------------------------------------------------------------------
# hello (spec 10.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BotIdentity:
    """A bot's self-reported name and version (``hello_ok.bot``, spec 10.1)."""

    name: str
    version: str


@dataclass(frozen=True)
class AgentHelloOk:
    """An agent's ``hello_ok`` (spec 10.1), read leniently: unknown fields anywhere are ignored."""

    request_id: str
    bot: BotIdentity
    requires_observation: tuple[str, ...] = ()
    requires_extensions: tuple[str, ...] = ()
    extensions_accepted: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, value: Any, *, request_id: str) -> AgentHelloOk:
        hello = as_object(value, "hello_ok")
        if hello.get("response_type") != "hello_ok":
            fail("hello_ok.response_type", f'must be "hello_ok", got {hello.get("response_type")!r}')
        if hello.get("protocol") != PROTOCOL:
            fail("hello_ok.protocol", f'must be "{PROTOCOL}", got {hello.get("protocol")!r}')
        if hello.get("request_id") != request_id:
            fail("hello_ok.request_id", f"must echo {request_id!r}, got {hello.get('request_id')!r}")
        bot = as_object(hello.get("bot"), "hello_ok.bot")
        identity = BotIdentity(nonempty(bot.get("name"), "hello_ok.bot.name"), nonempty(bot.get("version"), "hello_ok.bot.version"))
        observation: tuple[str, ...] = ()
        extensions: tuple[str, ...] = ()
        requires = hello.get("requires")
        if requires is not None:
            requires_obj = as_object(requires, "hello_ok.requires")
            if "observation" in requires_obj:
                observation = _strings(requires_obj["observation"], "hello_ok.requires.observation")
            if "extensions" in requires_obj:
                extensions = _strings(requires_obj["extensions"], "hello_ok.requires.extensions")
        accepted: tuple[str, ...] = ()
        if "extensions_accepted" in hello:
            accepted = _strings(hello["extensions_accepted"], "hello_ok.extensions_accepted")
        return cls(request_id, identity, observation, extensions, accepted)


# ---------------------------------------------------------------------------
# game_start (spec 10.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnDeck:
    """A seat's full deck as ``game_start`` sends it (spec 10.2): ``own_deck`` always, ``opponent_deck`` when visible."""

    deck_id: str
    name: str
    decklist: tuple[DeckRow, ...]

    def to_json(self) -> dict[str, Any]:
        return {"deck_id": self.deck_id, "name": self.name, "decklist": [row.to_json() for row in self.decklist]}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        deck = _object(value, ("deck_id", "name", "decklist"), context)
        deck_id = text(deck["deck_id"], f"{context}.deck_id")
        if not _DECK_ID_RE.fullmatch(deck_id):
            fail(f"{context}.deck_id", f'must be "sha256:" and 64 lowercase hex digits, got {deck_id!r}')
        nonempty(deck["name"], f"{context}.name")
        digests.deck_rows(array(deck["decklist"], f"{context}.decklist"), f"{context}.decklist")

    @classmethod
    def from_json(cls, value: Any, context: str = "own_deck") -> OwnDeck:
        cls._check(value, context)
        return cls(value["deck_id"], value["name"], _rows(value["decklist"]))


def game_start_payload(
    *,
    game_id: str,
    seat: str,
    format: str,
    own_deck: OwnDeck,
    opponent_deck: OwnDeck | None,
    rules: Rules,
    engine: EngineIdentity,
    engine_profile: EngineProfile,
    time_control: TimeControl,
    limits: Limits,
    resources: Resources,
    agent_seed: int,
) -> dict[str, Any]:
    """The ``game_start`` payload past the envelope (spec 10.2); ``request()`` adds the envelope."""
    return {
        "game_id": game_id,
        "seat": seat,
        "format": format,
        "own_deck": own_deck.to_json(),
        "opponent_deck": None if opponent_deck is None else opponent_deck.to_json(),
        "rules": rules.to_json(),
        "engine": engine.to_json(),
        "engine_profile": engine_profile.to_json(),
        "time_control": time_control.to_json(),
        "limits": limits.to_json(),
        "resources": resources.to_json(),
        "agent_seed": agent_seed,
    }


# ---------------------------------------------------------------------------
# choose (spec 10.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Clock:
    """The seat's clock as sent with each ``choose`` (spec 10.3, 11.4)."""

    remaining_ms: int
    max_decision_ms: int

    def to_json(self) -> dict[str, Any]:
        return {"remaining_ms": self.remaining_ms, "max_decision_ms": self.max_decision_ms}

    @staticmethod
    def _check(value: Any, context: str) -> None:
        clock = _object(value, ("remaining_ms", "max_decision_ms"), context)
        safe_int(clock["remaining_ms"], f"{context}.remaining_ms")
        safe_int(clock["max_decision_ms"], f"{context}.max_decision_ms")

    @classmethod
    def from_json(cls, value: Any, context: str = "clock") -> Clock:
        cls._check(value, context)
        return cls(value["remaining_ms"], value["max_decision_ms"])


@dataclass(frozen=True)
class Choice:
    """A ``choice`` response (spec 10.3), read leniently: only ``selection.candidate_id`` is required.

    ``echoes`` keeps whichever of ``seat_step`` and ``semantic_echo`` the agent sent, raw and
    unchecked: the game loop compares them against the offered decision, not this reader.
    """

    request_id: str
    candidate_id: int
    echoes: dict[str, Any]

    @classmethod
    def from_json(cls, value: Any, *, request_id: str) -> Choice:
        choice = as_object(value, "choice")
        if choice.get("response_type") != "choice":
            fail("choice.response_type", f'must be "choice", got {choice.get("response_type")!r}')
        if choice.get("protocol") != PROTOCOL:
            fail("choice.protocol", f'must be "{PROTOCOL}", got {choice.get("protocol")!r}')
        if choice.get("request_id") != request_id:
            fail("choice.request_id", f"must echo {request_id!r}, got {choice.get('request_id')!r}")
        selection = as_object(choice.get("selection"), "choice.selection")
        candidate_id = selection.get("candidate_id")
        # Any JSON integer (R2-16): the game loop, not this reader, judges the range.
        if type(candidate_id) is not int:
            fail("choice.selection.candidate_id", f"must be an integer, got {type(candidate_id).__name__}")
        echoes = {key: selection[key] for key in ("seat_step", "semantic_echo") if key in selection}
        return cls(request_id, candidate_id, echoes)


def choose_payload(*, game_id: str, seat_decision: Mapping[str, Any], clock: Clock) -> dict[str, Any]:
    """The ``choose`` payload past the envelope (spec 10.3); ``seat_decision`` is the validated, canonical decision."""
    return {"game_id": game_id, "decision": dict(seat_decision), "clock": clock.to_json()}


# ---------------------------------------------------------------------------
# game_over and error codes (spec 10.4, 10.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentTerminal:
    """How a game ended, as the host reports it to an agent (spec 10.4); ``classification`` may be ``forfeit`` (spec 11.5)."""

    outcome: str
    classification: str
    winner: str | None
    reason: str
    seat_step_count: int

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "classification": self.classification,
            "winner": self.winner,
            "reason": self.reason,
            "seat_step_count": self.seat_step_count,
        }

    @staticmethod
    def _check(value: Any, context: str) -> None:
        fields = ("outcome", "classification", "winner", "reason", "seat_step_count")
        terminal = _object(value, fields, context)
        classification = vocab(terminal["classification"], _TERMINAL_CLASSIFICATIONS, f"{context}.classification")
        outcome = terminal["outcome"]
        winner = terminal["winner"]
        if classification == "natural":
            vocab(outcome, tuple(_NATURAL_WINNERS), f"{context}.outcome")
            expected = _NATURAL_WINNERS[outcome]
            if winner != expected:
                shown = "null" if expected is None else expected
                fail(f"{context}.winner", f"must be {shown} with outcome {outcome!r} in a natural terminal, got {winner!r}")
        elif classification == "forfeit":
            vocab(outcome, tuple(_FORFEIT_WINNERS), f"{context}.outcome")
            expected = _FORFEIT_WINNERS[outcome]
            if winner != expected:
                fail(f"{context}.winner", f"must be {expected!r} with outcome {outcome!r} in a forfeit terminal, got {winner!r}")
        else:
            vocab(outcome, (classification,), f"{context}.outcome")
            if winner is not None:
                fail(f"{context}.winner", f"must be null in a {classification} terminal, got {winner!r}")
        nonempty(terminal["reason"], f"{context}.reason")
        safe_int(terminal["seat_step_count"], f"{context}.seat_step_count")

    @classmethod
    def from_json(cls, value: Any, context: str = "terminal") -> AgentTerminal:
        cls._check(value, context)
        return cls(**value)


def game_over_payload(*, game_id: str, terminal: AgentTerminal) -> dict[str, Any]:
    """The ``game_over`` payload past the envelope (spec 10.4)."""
    return {"game_id": game_id, "terminal": terminal.to_json()}


def read_ack(value: Any, *, request_id: str) -> None:
    """Validate an ``ack`` response to ``game_start`` or ``game_over`` (spec 10.2, 10.4).

    Raises :class:`~spellbench.errors.ValidationError` when the envelope does not bind.
    """
    ack = as_object(value, "ack")
    if ack.get("response_type") != "ack":
        fail("ack.response_type", f'must be "ack", got {ack.get("response_type")!r}')
    if ack.get("protocol") != PROTOCOL:
        fail("ack.protocol", f'must be "{PROTOCOL}", got {ack.get("protocol")!r}')
    if ack.get("request_id") != request_id:
        fail("ack.request_id", f"must echo {request_id!r}, got {ack.get('request_id')!r}")


def read_error(value: Any, *, request_id: str) -> tuple[str, str] | None:
    """The ``code`` and ``message`` of an ``error`` envelope (spec 9.8, 10.5); ``None`` when ``value`` is not one.

    Read leniently (spec 10 intro): only ``response_type`` gates whether this is an error at
    all, and ``request_id`` may echo the request or be ``""`` (spec 4.1: unreadable on the
    agent's side). Once ``response_type`` is ``"error"`` the ``error`` object is still required
    and well-typed, so a broken error envelope fails fast rather than being read as some other
    response type.
    """
    if not isinstance(value, dict) or value.get("response_type") != "error":
        return None
    error = as_object(value.get("error"), "error.error")
    code = text(error.get("code"), "error.error.code")
    message = text(error.get("message"), "error.error.message")
    got_id = value.get("request_id")
    if got_id != request_id and got_id != "":
        fail("error.request_id", f"must echo {request_id!r} or be empty, got {got_id!r}")
    return code, message


def request(request_type: str, request_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """The envelope plus ``payload`` (spec 4.1): every host-to-agent request is built this way."""
    return {"request_type": request_type, "protocol": PROTOCOL, "request_id": request_id, **payload}
