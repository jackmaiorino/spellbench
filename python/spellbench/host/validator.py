"""The live validator: V1 to V10 in rule order, with its counters (spec 11.3).

Each rule after V1 has its check in a sibling module, imported by name so a
caller (or a test) can replace one: V2 and V4 and V6 in ``host.refs``, V5 in
``host.hidden``, V8 and V9 in ``host.declarations``, and the cross-decision V3
counters and V7 id history in ``host.tracking``. This module owns:

- V1 (spec 6, 7, 11.3): the whole ``seat_decision`` schema, everything Section
  8's observation and candidate schemas do not already cover on their own:
  the seven top-level fields, ``group`` and ``context``, that the candidate
  list is 1 to 4096 entries, dense, pairwise distinct (by canonical bytes)
  and poses ``pass`` only at index 0, that ``extensions`` keys match
  ``x_[a-z0-9_]+``, that a ``choose_name`` value is NFC and inside its
  purpose's domain (Task 7 checks only that it is a nonempty string), that a
  ``search`` selection allows finding nothing, and the ``choose_starting_player``
  and ``mulligan`` shapes of spec 7.5.
- The V3 group shapes of spec 7.5 and 8 (``check_group_shape``, R2-7): sizes
  that never depend on hidden facts, so they are checkable without the
  cross-decision state ``host.tracking.GroupTracker`` keeps.
- ``LiveValidator``, which runs V1 to V10 in rule order on every decision of
  one game, so the lowest-numbered broken rule is the one reported (spec
  11.3), and ``check_terminal``, the interruption rule of spec 8 and Decision
  13 plus a last V10 check.

V7 (spec 5.3) is only ever checked from one seat's own decision stream: an id
never keeps two zones and never returns after leaving that seat's
observation. The other half of spec 5.3, that a fresh look always mints a
genuinely fresh id, is not checkable this way: nothing here knows an
engine's internal identity for an object, so an engine that happened never to
repeat an id would pass even if its ids leaked information they should not.
That half is for the reserved probe and adapter audits (spec 11.3), not this
validator.
"""

from __future__ import annotations

from typing import Any, Mapping

from .._schema import (
    EXTENSION_KEY_RE,
    SEATS,
    array,
    as_object,
    boolean,
    card_name,
    exact_keys,
    fail,
    nullable,
    object_ref,
    safe_int,
    seat,
    snake,
    text,
    u32,
    vocab,
)
from ..candidates import MAX_CANDIDATES, validate_candidate
from ..messages import Decision, EnvHelloOk, Provenance, Rules, Terminal
from ..observation import CARD_TYPES, observation_objects, validate_observation
from ..wire import canonical_json_dumps
from .declarations import check_context, check_declarations
from .hidden import check_hidden_zones
from .refs import check_face_down, check_references, check_seat
from .tracking import GroupTracker, IdTracker
from .violation import ValidatorViolation

VALIDATOR_VERSION = "spellbench-live-validator/2.0"
# Spec 7.5: the normalized subtypes a choose_name "basic_land_type" may name.
BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

_SEAT_DECISION_FIELDS = ("acting_seat", "seat_step", "group", "context", "observation", "candidates", "extensions")
_GROUP_FIELDS = ("group_id", "substep_index", "substep_count")
_CONTEXT_FIELDS = ("kind", "source", "purpose", "text", "rewind")
_CONTEXT_KINDS = ("priority", "choice")
# Spec 7.5 naming: purposes checked as snake_case subtypes, apart from card_name and basic_land_type/card_type.
_SNAKE_NAME_PURPOSES = ("creature_type", "land_type")


def validate_seat_decision_schema(seat_decision: Any, rules: Rules) -> dict:
    """V1 alone (spec 6, 7, 11.3): raises ``errors.ValidationError``; ``LiveValidator.check`` reports it as V1."""
    sd = as_object(seat_decision, "seat_decision")
    exact_keys(sd, _SEAT_DECISION_FIELDS, "seat_decision")
    seat(sd["acting_seat"], "acting_seat")
    safe_int(sd["seat_step"], "seat_step")
    _check_group(sd["group"], "group")
    _check_context(sd["context"], "context")
    validate_observation(sd["observation"], "observation")
    _check_candidates(sd["candidates"], sd["observation"], rules, "candidates")
    _check_extensions(sd["extensions"], "extensions")
    return sd


def _check_group(value: Any, context: str) -> None:
    """``group`` (spec 8): ``1 <= substep_count`` and ``substep_index < substep_count``."""
    group = as_object(value, context)
    exact_keys(group, _GROUP_FIELDS, context)
    safe_int(group["group_id"], f"{context}.group_id")
    substep_count = u32(group["substep_count"], f"{context}.substep_count")
    substep_index = u32(group["substep_index"], f"{context}.substep_index")
    if substep_count < 1:
        fail(f"{context}.substep_count", "must be at least 1")
    if substep_index >= substep_count:
        fail(f"{context}.substep_index", f"must be less than substep_count {substep_count}, got {substep_index}")


def _check_context(value: Any, context: str) -> None:
    """``context`` (spec 9.3): exactly ``{kind, source, purpose, text, rewind}``."""
    ctx = as_object(value, context)
    exact_keys(ctx, _CONTEXT_FIELDS, context)
    vocab(ctx["kind"], _CONTEXT_KINDS, f"{context}.kind")
    nullable(ctx["source"], object_ref, f"{context}.source")
    nullable(ctx["purpose"], snake, f"{context}.purpose")
    nullable(ctx["text"], text, f"{context}.text")
    boolean(ctx["rewind"], f"{context}.rewind")


def _check_candidates(value: Any, observation: Mapping[str, Any], rules: Rules, context: str) -> None:
    """1 to 4096 candidates, each valid, dense, pairwise distinct, ``pass`` only at index 0 (spec 7.1)."""
    candidates = array(value, context, min_length=1, max_length=MAX_CANDIDATES)
    seen: set[bytes] = set()
    for index, candidate in enumerate(candidates):
        validate_candidate(candidate, f"{context}[{index}]")
        if candidate["candidate_id"] != index:
            fail(f"{context}[{index}].candidate_id", f"must equal its index {index}, got {candidate['candidate_id']}")
        digest = canonical_json_dumps(candidate["semantic"])
        if digest in seen:
            fail(f"{context}[{index}].semantic", "duplicates an earlier candidate's semantic (spec 7.1)")
        seen.add(digest)
        semantic = candidate["semantic"]
        if semantic["kind"] == "pass" and index != 0:
            fail(f"{context}[{index}]", "pass is legal only as candidate 0 (spec 7.1)")
        if semantic["kind"] == "choose_name":
            _check_choose_name(semantic, rules, f"{context}[{index}].semantic.value")
        if semantic["kind"] == "select_object" and semantic["purpose"] == "search" and semantic["minimum"] != 0:
            fail(f"{context}[{index}].semantic.minimum", "a library search always allows finding nothing (spec 7.5, F3)")
    _check_starting_player_and_mulligan(candidates, observation, context)


def _check_choose_name(semantic: Mapping[str, Any], rules: Rules, context: str) -> None:
    """``choose_name`` values inside their purpose's domain (spec 7.5); ``other`` is free-form."""
    purpose, value = semantic["purpose"], semantic["value"]
    if purpose == "card_name":
        card_name(value, context)   # NFC (Task 7 checks only that it is a nonempty string)
        if value not in rules.card_name_domain.names:
            fail(context, f"{value!r} is not in rules.card_name_domain.names")
    elif purpose in _SNAKE_NAME_PURPOSES:
        snake(value, context)
    elif purpose == "basic_land_type":
        vocab(value, BASIC_LAND_TYPES, context)
    elif purpose == "card_type":
        vocab(value, CARD_TYPES, context)


def _check_starting_player_and_mulligan(candidates: list, observation: Mapping[str, Any], context: str) -> None:
    """A ``choose_starting_player`` or ``mulligan`` decision's shape (spec 7.5; R2-25)."""
    starting = [candidate["semantic"] for candidate in candidates if candidate["semantic"]["kind"] == "choose_starting_player"]
    if starting and sorted(entry["player"] for entry in starting) != list(SEATS):
        fail(context, "a choose_starting_player decision offers exactly one candidate per seat (spec 7.5)")
    mulligans = [candidate["semantic"] for candidate in candidates if candidate["semantic"]["kind"] == "mulligan"]
    if mulligans:
        viewer_player = observation["players"][SEATS.index(observation["viewer"])]
        if not any(entry["keep"] for entry in mulligans):
            fail(context, "a mulligan decision offers keep: true (spec 7.5)")
        for entry in mulligans:
            if entry["hand_size"] != viewer_player["hand_count"] or entry["mulligans_taken"] != viewer_player["mulligans_taken"]:
                fail(context, "a mulligan candidate must match the viewer's hand_count and mulligans_taken (R2-25)")


def _check_extensions(value: Any, context: str) -> None:
    """``extensions`` (spec 14): an object whose keys are ``x_[a-z0-9_]+``."""
    extensions = as_object(value, context)
    for key in extensions:
        if not EXTENSION_KEY_RE.fullmatch(key):
            fail(context, f"{key!r} is not an extension key (x_[a-z0-9_]+)")


def check_group_shape(sd: Mapping[str, Any]) -> None:
    """V3 group shapes (spec 7.5, 8, F3): sizes that never depend on hidden facts."""
    group = sd["group"]
    kinds = [candidate["semantic"]["kind"] for candidate in sd["candidates"]]
    if sd["context"]["kind"] == "priority" and group["substep_count"] != 1:
        raise ValidatorViolation("V3", "a priority decision is one decision (substep_count 1)")
    if {"finish_target_selection", "finish_selection"} & set(kinds) and group["substep_count"] != 1:
        raise ValidatorViolation("V3", "a decision offering a finish candidate is its own group (substep_count 1)")
    if group["substep_index"] == 0 and "arrange_card" in kinds:
        cards = next(c["semantic"]["card_count"] for c in sd["candidates"] if c["semantic"]["kind"] == "arrange_card")
        if group["substep_count"] != 2 * cards - 1:
            raise ValidatorViolation("V3", f"an arrangement of {cards} cards is {2 * cards - 1} decisions, not {group['substep_count']}")


class LiveValidator:
    """Live validation of one game's seat decisions, V1 to V10 in rule order (spec 11.3)."""

    def __init__(self, hello: EnvHelloOk, rules: Rules) -> None:
        self._profile = hello.profile
        self._rules = rules
        self._provenance = hello.engine.provenance()
        self._groups = GroupTracker()
        self._ids = IdTracker()
        self.decisions_checked = 0

    @property
    def answered_steps(self) -> int:
        return self._groups.answered_steps

    @property
    def completed_groups(self) -> int:
        return self._groups.completed_groups

    def answered_by(self, seat: str) -> int:
        return self._groups.answered_by(seat)

    def check(self, decision: Decision) -> dict:
        """The validated seat decision, or raise the ``ValidatorViolation`` of the first rule it breaks."""
        self.decisions_checked += 1
        try:
            return self._check(decision)
        except ValidatorViolation:
            raise
        except Exception as exc:   # a check meeting input it cannot read is a schema failure, never a crash (R1-8)
            raise ValidatorViolation("V1", f"the seat decision broke a validator check ({type(exc).__name__}: {exc})") from exc

    def _check(self, decision: Decision) -> dict:
        sd = validate_seat_decision_schema(decision.seat_decision, self._rules)        # V1
        check_seat(sd)                                                                 # V2
        self._groups.check(sd)                                                         # V3 counters
        check_group_shape(sd)                                                          # V3 group shapes (R2-7)
        check_references(sd)                                                           # V4
        check_hidden_zones(sd)                                                         # V5
        check_face_down(sd)                                                            # V6
        # V7 (spec 5.3): what one seat's stream can show, an id never keeps two zones
        # and never returns after leaving it (module docstring).
        self._ids.check(sd["acting_seat"], {ref["object_id"]: ref["zone"] for _, ref in observation_objects(sd["observation"])})
        check_declarations(sd, self._profile, self._rules)                             # V8
        check_context(sd)                                                              # V9
        self._check_provenance(decision.provenance)                                    # V10
        return sd

    def answered(self, sd: Mapping[str, Any], candidate_id: int) -> None:
        self._groups.answered(sd, chosen_kind=sd["candidates"][candidate_id]["semantic"]["kind"])

    def check_terminal(self, terminal: Terminal) -> None:
        """V3 (spec 8, Decision 13): only a halted or truncated terminal may interrupt a partial group; then V10."""
        partial_seat = self._groups.partial_seat
        if partial_seat is not None and terminal.result.classification not in ("halted", "truncated"):
            raise ValidatorViolation(
                "V3", f"a {terminal.result.classification} terminal interrupted {partial_seat}'s partial group"
            )
        self._check_provenance(terminal.provenance)                                    # V10

    def _check_provenance(self, provenance: Provenance) -> None:
        if provenance != self._provenance:
            raise ValidatorViolation("V10", "the engine identity drifted from its hello")
