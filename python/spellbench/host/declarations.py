"""V8 declarations and V9 context (spec 6.7, 6.9, 7.1, 7.6, 8, 11.3, 12.2, 14).

``check_declarations`` applies V8, the seat decision against the engine's
declarations, in this order:

1. every optional field follows its ``observation`` flag (spec 6.9): a field is
   null everywhere with its flag false, and non-null everywhere with its flag
   true, except the nulls spec 6.9 allows (``full_name``, ``exiled_by``, stack
   ``text``, and ``class_level`` on a permanent that is not a Class; a Class is
   a permanent whose subtypes include ``class``, and with the flag true only a
   Class carries a level);
2. with ``known_cards`` false, ``known`` lists only cards looked at, revealed
   or searched in the current decision, each with a fresh object id (spec 6.7;
   over-informing is never allowed, R2-6);
3. every candidate kind is in ``profile.decision_kinds`` (spec 9.1);
4. no ``mulligan`` candidate while ``rules.mulligan`` is ``none``, and no
   ``choose_starting_player`` while ``rules.starting_player`` is
   ``host_assigned``: the declared rule answers those decisions (spec 7.6, 12.2);
   likewise no decision an ``engine_defaults`` entry answers (spec 7.6): an
   ``order_pick`` of ``triggers`` under ``trigger_order``, a
   ``choose_replacement`` under ``replacement_order``, a ``distribute`` of
   ``combat_damage`` under ``combat_damage_assignment``, and a mana ability in a
   choice decision under ``engine_autopay``;
5. ``context.rewind`` only when the profile declares ``rewind`` (spec 8);
6. every ``extensions`` key is declared in ``hello_ok.extensions`` and enabled
   in ``rules.extensions`` (spec 14).

``check_context`` applies V9 (spec 7.1, 9.3): the candidates are all of
``context.kind``'s family, with one exception. A choice decision whose
``context.purpose`` is ``mana_payment`` offers ``optional_cost`` and
``activate_mana_ability`` candidates only, always offers an ``optional_cost``
with ``pay: false``, and pays one cost of one source; that purpose appears
only on a choice decision, and ``activate_mana_ability`` appears in a choice
decision only under it. Any other ``context.purpose`` is null or repeats the
purpose every candidate carrying one shares.

Inputs are seat decisions that already passed V1, so every field has its type,
every candidate a valid v2.0 kind. Details start with the path of the offending
value, relative to the seat decision.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Mapping

from .._schema import quoted
from ..candidates import family
from ..messages import EngineProfile, Rules
from ..observation import zone_records
from .violation import ValidatorViolation

# Spec 6.7: the hows of a card being looked at, revealed or searched in the current decision.
_CURRENT_LOOKS = ("looked_at", "revealed", "searching")
# Spec 7.1: the only kinds a mana_payment choice offers.
_MANA_PAYMENT_KINDS = ("optional_cost", "activate_mana_ability")
# Spec 7.6: an engine default, the value under which the engine answers that decision itself, and whether a
# candidate belongs to that decision. Under engine_autopay a seat still decides whether to pay a cost
# (optional_cost), never how: no choice decision offers it a mana ability.
_ENGINE_DEFAULTS: tuple[tuple[str, str, Callable[[Mapping[str, Any], Mapping[str, Any]], bool]], ...] = (
    ("trigger_order", "engine_order",
     lambda semantic, sd: semantic["kind"] == "order_pick" and semantic["purpose"] == "triggers"),
    ("replacement_order", "engine_order", lambda semantic, sd: semantic["kind"] == "choose_replacement"),
    ("combat_damage_assignment", "engine_order",
     lambda semantic, sd: semantic["kind"] == "distribute" and semantic["purpose"] == "combat_damage"),
    ("mana_payment", "engine_autopay",
     lambda semantic, sd: semantic["kind"] == "activate_mana_ability" and sd["context"]["kind"] == "choice"),
)


def check_declarations(seat_decision: Mapping[str, Any], profile: EngineProfile, rules: Rules) -> None:
    """V8: raise ``ValidatorViolation("V8", ...)`` at the first broken rule, in the module docstring's order."""
    flags = profile.observation
    for flag, path, value, may_be_null in _optional_fields(seat_decision):
        if value is None:
            if flags[flag] and not may_be_null:
                raise ValidatorViolation("V8", f"{path} does not match the {flag} flag")
        elif not flags[flag] or (flag == "permanent_details" and may_be_null):
            # may_be_null under permanent_details is class_level on a non-Class, where a level is never allowed.
            raise ValidatorViolation("V8", f"{path} does not match the {flag} flag")
    if not flags["known_cards"]:
        for index, entry in enumerate(seat_decision["observation"]["known"]):
            if entry["object_id"] is None or entry["how"] not in _CURRENT_LOOKS:
                raise ValidatorViolation(
                    "V8",
                    f"observation.known[{index}] is not a card looked at, revealed or searched in this decision, "
                    "and known_cards is false (spec 6.7)",
                )
    kinds = [candidate["semantic"]["kind"] for candidate in seat_decision["candidates"]]
    for index, kind in enumerate(kinds):
        if kind not in profile.decision_kinds:
            raise ValidatorViolation("V8", f"candidates[{index}].semantic.kind {kind!r} is not in the declared decision_kinds")
    if rules.mulligan == "none" and "mulligan" in kinds:
        raise ValidatorViolation("V8", "a mulligan candidate while rules.mulligan is none (spec 7.6)")
    if rules.starting_player == "host_assigned" and "choose_starting_player" in kinds:
        raise ValidatorViolation("V8", "a choose_starting_player candidate while rules.starting_player is host_assigned (spec 7.6)")
    semantics = [candidate["semantic"] for candidate in seat_decision["candidates"]]
    for default, value, answers in _ENGINE_DEFAULTS:
        if profile.engine_defaults[default] == value and any(answers(semantic, seat_decision) for semantic in semantics):
            raise ValidatorViolation("V8", f"a decision the engine answers itself under engine_defaults.{default} {value} "
                                           "is posed (spec 7.6)")
    if seat_decision["context"]["rewind"] and not profile.rewind:
        raise ValidatorViolation("V8", "context.rewind is true but the profile does not declare rewind (spec 8)")
    declared = {extension.name for extension in profile.extensions}
    for key in seat_decision["extensions"]:
        if key not in declared:
            raise ValidatorViolation("V8", f"extensions key {quoted(key)} is not declared in hello_ok.extensions (spec 14)")
        if key not in rules.extensions:
            raise ValidatorViolation("V8", f"extensions key {quoted(key)} is not enabled in rules.extensions (spec 14)")


def check_context(seat_decision: Mapping[str, Any]) -> None:
    """V9: raise ``ValidatorViolation("V9", ...)`` when the candidates disagree with the context (spec 7.1)."""
    context = seat_decision["context"]
    kind, purpose = context["kind"], context["purpose"]
    candidates = seat_decision["candidates"]
    if purpose == "mana_payment":
        if kind != "choice":
            raise ValidatorViolation("V9", f"context.purpose mana_payment appears only on a choice decision, got kind {kind!r}")
        for index, candidate in enumerate(candidates):
            offered = candidate["semantic"]["kind"]
            if offered not in _MANA_PAYMENT_KINDS:
                raise ValidatorViolation(
                    "V9",
                    f"candidates[{index}].semantic.kind is {offered!r}; a mana_payment decision offers "
                    "only optional_cost and activate_mana_ability",
                )
        pays = [candidate["semantic"] for candidate in candidates if candidate["semantic"]["kind"] == "optional_cost"]
        if not any(semantic["pay"] is False for semantic in pays):
            raise ValidatorViolation("V9", "a mana_payment decision always includes an optional_cost with pay false")
        if any((semantic["source"], semantic["cost"]) != (pays[0]["source"], pays[0]["cost"]) for semantic in pays):
            raise ValidatorViolation("V9", "a mana_payment decision pays one cost of one source: its optional_cost "
                                           "candidates share source and cost")
        return
    for index, candidate in enumerate(candidates):
        offered = candidate["semantic"]["kind"]
        if family(offered) != kind:
            detail = f"candidates[{index}].semantic.kind is {offered!r}, a {family(offered)} kind, in a {kind} decision"
            if offered == "activate_mana_ability":   # a priority kind a choice decision may offer under mana_payment
                detail += "; a choice decision offers it only with context.purpose mana_payment"
            raise ValidatorViolation("V9", detail)
    shared = {candidate["semantic"]["purpose"] for candidate in candidates if "purpose" in candidate["semantic"]}
    if purpose is not None and shared != {purpose}:
        raise ValidatorViolation("V9", f"context.purpose {quoted(purpose)} is not the purpose every candidate carrying "
                                       "one shares (spec 9.3)")


def _optional_fields(seat_decision: Mapping[str, Any]) -> Iterator[tuple[str, str, Any, bool]]:
    """Yield ``(flag, path, value, may_be_null)`` for every optional field (spec 6.9).

    ``path`` is relative to the seat decision; ``may_be_null`` marks the nulls
    spec 6.9 allows with the flag true: ``full_name``, ``exiled_by``, stack
    ``text``, and ``class_level`` on a permanent whose subtypes lack ``class``.
    """
    observation = seat_decision["observation"]
    for index, player in enumerate(observation["players"]):
        path = f"observation.players[{index}]"
        yield "poison", f"{path}.poison", player["poison"], False
        yield "player_counters", f"{path}.counters", player["counters"], False
        yield "designations", f"{path}.designations", player["designations"], False
        yield "player_progress", f"{path}.progress", player["progress"], False
    yield "day_night", "observation.day_night", observation["day_night"], False
    yield "passed_seats", "observation.passed_seats", observation["passed_seats"], False
    yield "pending_triggers", "observation.pending_triggers", observation["pending_triggers"], False
    for path, _, record in zone_records(observation):
        where = f"observation.{path}"
        yield "full_name", f"{where}.full_name", record["full_name"], True
        yield "exiled_by", f"{where}.exiled_by", record["exiled_by"], True
        characteristics = record["characteristics"]
        if characteristics is not None:
            yield "keywords", f"{where}.characteristics.keywords", characteristics["keywords"], False
        permanent = record["permanent"]
        if permanent is not None:
            # A battlefield record always has characteristics (V1), so its subtypes are here.
            is_class = "class" in characteristics["subtypes"]
            yield "permanent_details", f"{where}.permanent.statuses", permanent["statuses"], False
            yield "permanent_details", f"{where}.permanent.class_level", permanent["class_level"], not is_class
            yield "permanent_details", f"{where}.permanent.chosen", permanent["chosen"], False
    for index, entry in enumerate(observation["stack"]):
        where = f"observation.stack[{index}]"
        yield "stack_text", f"{where}.text", entry["text"], True
        if entry["characteristics"] is not None:
            yield "keywords", f"{where}.characteristics.keywords", entry["characteristics"]["keywords"], False
