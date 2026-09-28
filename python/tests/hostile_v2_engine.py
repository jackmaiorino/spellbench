"""Test fixture: a v2 environment-role engine that injects one fault in the mode named by argv[1].

``python hostile_v2_engine.py MODE [fake engine args...]`` serves ``fake_v2_engine``'s scoring game
with one mutation applied at the second decision (step 1, p1's first decision) or at its terminal,
so exactly one rule or fault shows. ``MODES`` maps each mode to the outcome the host records: a
validator rule (``"V1"`` to ``"V10"``, spec 11.3) or a fault (``"malformed"``, ``"error"``,
``"timeout"``, ``"transport"``, ``"terminal_counts"``). ``DETAILS`` maps each mode to a fragment of
the text that names its cause, specific to the injected fault, so a mode caught by another check
under the same rule or fault does not pass: a violation's detail, a fault's message, the engine's
exit code for ``transport``, and for ``bad-terminal-counts`` the count comparison the game loop
makes (spec 9.5, 11.5; the test writes it as ``terminal decision_count N is not the M completed groups``).

- ``unknown-kind``, ``reserved-kind``: candidate 1's semantic kind is no v2.0 kind / is a reserved one.
- ``duplicate-semantics``: a third candidate repeats candidate 1's semantic (spec 7.1).
- ``pass-not-first``: the priority decision offers no ``pass`` at all (spec 7.1, CR 117.3).
- ``nfd-name``: the hand card no candidate references has an NFD name, not NFC (spec 4.4).
- ``search-minimum``: a ``select_object`` search with ``minimum`` 1, ``finish_selection`` offered (spec 7.5, F3).
- ``order-pick-source``: an ``order_pick`` trigger item whose source is a face-down permanent the viewer
  may not look at, nameless as it must be, still gives ``source_name`` (spec 5.1, 6.8).
- ``viewer-mismatch``: the observation's viewer is not the acting seat.
- ``priority-holder``: the priority decision goes to the seat that does not hold priority (spec 6.2, 7.1).
- ``seat-step-gap``, ``group-skip``: the seat step jumps ahead / the group id skips the next one (spec 8, 9.3).
- ``arrangement-size``: a two-card arrangement posed as a group of 2, not 2 * 2 - 1 = 3 (spec 7.5, R2-7).
- ``stale-reference``, ``absent-reference``: the ``play_land`` source differs from its record / names no held object.
- ``duplicate-id``: both of the viewer's hand records share one object id (spec 5.1).
- ``opponent-hand``, ``hand-count``, ``library-record``, ``known-unsorted`` (with ``--flags known_cards``):
  V5's hand, count, library and known-order rules (spec 6.3, 6.7).
- ``face-down-name``, ``face-down-characteristics``: a face-down permanent the viewer may not look at
  still shows its name (with the face-down 2/2's characteristics) / its printed characteristics
  (nameless) (spec 6.4, 6.8).
- ``id-two-zones`` (at step 2): p0's played Mountain keeps its hand id (spec 5.3).
- ``undeclared-kind`` (with ``--kinds pass,play_land,cast_spell,declare_attack,declare_block``):
  a ``choose_boolean`` the hello never declared (spec 9.1).
- ``flag-off-value``: ``poison`` is 0 while its observation flag is off (spec 6.9).
- ``undeclared-extension``: an ``x_leak`` extension key the hello never declared (spec 14).
- ``family-mismatch``: a ``choose_boolean`` candidate in a priority decision (spec 7.1, 9.3).
- ``provenance-drift``: the decision's provenance differs from the hello's.
- ``garbage-json``, ``wrong-request-id``, ``deep-json``: a line that is not JSON, a request id the
  step never sent, an extension nested 70 levels (past the 64-level wire cap, spec 2).
- ``error-on-step``: the step is answered with an error envelope.
- ``hang-on-step``: the step is never answered (the mutation sleeps 60 s).
- ``crash-on-step``: the engine exits 5 at the step.
- ``bad-terminal-counts``, ``bad-terminal-steps``: the terminal's ``decision_count`` / ``step_count``
  is one too high (spec 9.5, 11.5).

``MODES``, ``DETAILS``, the fixed engine arguments and the mutation table live at module level (R2-20):
importing this file for them reads no ``sys.argv`` and serves no stdin.
"""

from __future__ import annotations

import copy
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from spellbench._schema import REFERENCE_FIELDS

import fake_v2_engine

Mutate = Callable[[int, dict], "dict | bytes"]

# As a macOS file system writes it: NFD, with a combining circumflex (spec 4.4 wants NFC).
_NFD_VAULT = "Lim-Du\u0302l's Vault"

MODES: dict[str, str] = {
    "unknown-kind": "V1",
    "reserved-kind": "V1",
    "duplicate-semantics": "V1",
    "pass-not-first": "V1",
    "nfd-name": "V1",
    "search-minimum": "V1",
    "order-pick-source": "V1",
    "viewer-mismatch": "V2",
    "priority-holder": "V2",
    "seat-step-gap": "V3",
    "group-skip": "V3",
    "arrangement-size": "V3",
    "stale-reference": "V4",
    "absent-reference": "V4",
    "duplicate-id": "V4",
    "opponent-hand": "V5",
    "hand-count": "V5",
    "library-record": "V5",
    "known-unsorted": "V5",
    "face-down-name": "V6",
    "face-down-characteristics": "V6",
    "id-two-zones": "V7",
    "undeclared-kind": "V8",
    "flag-off-value": "V8",
    "undeclared-extension": "V8",
    "family-mismatch": "V9",
    "provenance-drift": "V10",
    "garbage-json": "malformed",
    "wrong-request-id": "malformed",
    "deep-json": "malformed",
    "error-on-step": "error",
    "hang-on-step": "timeout",
    "crash-on-step": "transport",
    "bad-terminal-counts": "terminal_counts",
    "bad-terminal-steps": "terminal_counts",
}

# A fragment of the text naming each mode's cause (module docstring): the path and value the mutation
# broke, so a mode that another check catches under the same rule, or a fault with another cause, fails.
DETAILS: dict[str, str] = {
    "unknown-kind": "candidates[1].semantic.kind: 'dance' is an unknown kind",
    "reserved-kind": "candidates[1].semantic.kind: 'pay_mana' is a reserved kind",
    "duplicate-semantics": "candidates[2].semantic: duplicates an earlier candidate's semantic",
    "pass-not-first": "candidates[0].semantic.kind: a priority decision offers pass as candidate 0",
    "nfd-name": f"observation.players[1].hand[1].card_name: card name {_NFD_VAULT!r} is not in Unicode NFC",
    "search-minimum": "candidates[0].semantic.minimum: a library search always allows finding nothing",
    "order-pick-source": "candidates[0].semantic.item.trigger.source_name: must be null when its source's name is hidden",
    "viewer-mismatch": "observation.viewer p0 is not acting_seat p1",
    "priority-holder": "observation.priority_seat p0 is not acting_seat p1",
    "seat-step-gap": "p1 seat_step 5 is not 0",
    "group-skip": "p1 must start group 0 at substep 0, got 1 at 0",
    "arrangement-size": "an arrangement of 2 cards is 3 decisions, not 2",
    "stale-reference": "candidates[1].semantic.source differs from the observation record",
    "absent-reference": "candidates[1].semantic.source references obj-no-such-object, which is not in the observation",
    "duplicate-id": "appears twice in the observation (players[1].hand[0] and players[1].hand[1])",
    "opponent-hand": "observation.players[0].hand must be null",
    "hand-count": "observation.players[1].hand must hold hand_count 1 records, got 2",
    "library-record": "observation.players[1].graveyard[0].zone is library",
    "known-unsorted": "observation.known[0] and observation.known[1] are out of order",
    "face-down-name": "observation.players[0].battlefield[0].card_name must be null",
    "face-down-characteristics": "observation.players[0].battlefield[0].characteristics.supertypes must be []",
    "id-two-zones": "appeared in zones hand and battlefield",
    "undeclared-kind": "candidates[0].semantic.kind 'choose_boolean' is not in the declared decision_kinds",
    "flag-off-value": "observation.players[0].poison does not match the poison flag",
    "undeclared-extension": "extensions key 'x_leak' is not declared in hello_ok.extensions",
    "family-mismatch": "candidates[2].semantic.kind is 'choose_boolean', a choice kind, in a priority decision",
    "provenance-drift": "the engine identity drifted from its hello",
    "garbage-json": "line is not strict JSON",
    "wrong-request-id": "response request_id mismatch",
    "deep-json": "JSON nesting deeper than 64 levels",
    "error-on-step": "unsupported_request: the engine refuses this step",
    "hang-on-step": "timeout waiting for peer stdout",           # the read timed out, not the write
    "crash-on-step": "exit code 5",
    "bad-terminal-counts": "decision_count 5 is not the 4 completed groups",
    "bad-terminal-steps": "step_count 5 does not match the answered count 4",
}

# The engine arguments a mode needs beyond what its caller passes.
FIXED_ARGS: dict[str, tuple[str, ...]] = {
    "known-unsorted": ("--flags", "known_cards"),
    "undeclared-kind": ("--kinds", "pass,play_land,cast_spell,declare_attack,declare_block"),
}

# Spec 6.4 (CR 708.2): the characteristics a face-down permanent shows a viewer who may not look at it, a
# colorless nameless 2/2 creature; its keywords stay as the keywords flag has them (V8: null while it is off).
_FACE_DOWN_2_2: dict[str, Any] = {"supertypes": [], "types": ["creature"], "subtypes": [], "colors": [],
                                  "mana_value": 0, "power": 2, "toughness": 2}


def _is_decision(message: dict[str, Any], step: int) -> bool:
    return message.get("response_type") == "decision" and message.get("step") == step


def _seat_decision(message: dict[str, Any]) -> dict[str, Any]:
    return message["seat_decision"]


def _players(message: dict[str, Any]) -> list[dict[str, Any]]:
    return _seat_decision(message)["observation"]["players"]


def _turn_face_down(record: dict[str, Any]) -> dict[str, Any]:
    """``record`` as a face-down permanent shows to a seat not controlling it: a nameless 2/2 (spec 6.4, 6.8)."""
    record.update(face_down=True, card_name=None, full_name=None)
    record["characteristics"].update(copy.deepcopy(_FACE_DOWN_2_2))
    return record


def _reference(record: dict[str, Any]) -> dict[str, Any]:
    """The object reference equal to ``record`` (spec 5.1), as V4 compares them."""
    return {field: record[field] for field in REFERENCE_FIELDS}


# ---------------------------------------------------------------------------
# V1: the seat decision's schema (spec 6, 7)
# ---------------------------------------------------------------------------


def _unknown_kind(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["candidates"][1]["semantic"] = {"kind": "dance"}
    return message


def _reserved_kind(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["candidates"][1]["semantic"] = {"kind": "pay_mana"}
    return message


def _duplicate_semantics(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        candidates = _seat_decision(message)["candidates"]
        candidates.append({"candidate_id": len(candidates), "semantic": candidates[1]["semantic"],
                           "display_text": None})
    return message


def _pass_not_first(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        candidates = _seat_decision(message)["candidates"]
        _seat_decision(message)["candidates"] = [dict(candidates[1], candidate_id=0)]
    return message


def _nfd_name(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        # hand[1]: candidate 1 plays hand[0], so renaming that card would break V4's reference equality too.
        _players(message)[1]["hand"][1]["card_name"] = _NFD_VAULT
    return message


def _search_minimum(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        seat_decision = _seat_decision(message)
        seat_decision["context"]["kind"] = "choice"
        seat_decision["candidates"] = [
            {"candidate_id": 0,
             "semantic": {"kind": "select_object", "source": None, "purpose": "search",
                          "choice": {"player": "p1"}, "selected_count": 0, "minimum": 1, "maximum": 2},
             "display_text": None},
            {"candidate_id": 1,
             "semantic": {"kind": "finish_selection", "source": None, "purpose": "search", "selected_count": 0},
             "display_text": None},
        ]
    return message


def _order_pick_source(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        seat_decision = _seat_decision(message)
        # p0's battlefield Mountain, face down and properly hidden from p1 (V6 holds), so the trigger's source
        # reference equals its record (V4 holds) and only the leaked source_name breaks a rule.
        hidden = _turn_face_down(_players(message)[0]["battlefield"][0])
        seat_decision["context"]["kind"] = "choice"
        seat_decision["candidates"] = [
            {"candidate_id": 0,
             "semantic": {"kind": "order_pick", "source": None, "purpose": "triggers",
                          "item": {"trigger": {"source": _reference(hidden), "source_name": "Mountain",
                                               "ability_index": 0, "event_objects": [], "instance": 0,
                                               "label": None}},
                          "position": 0, "count": 2},
             "display_text": None},
        ]
    return message


# ---------------------------------------------------------------------------
# V2: the acting seat's view (spec 6.2, 7.1)
# ---------------------------------------------------------------------------


def _viewer_mismatch(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["observation"]["viewer"] = "p0"   # the decision is p1's
    return message


def _priority_holder(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["observation"]["priority_seat"] = "p0"   # p1 acts without holding priority
    return message


# ---------------------------------------------------------------------------
# V3: steps and groups (spec 7.5, 8, 9.3)
# ---------------------------------------------------------------------------


def _seat_step_gap(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["seat_step"] = 5   # p1's first decision, so 0
    return message


def _group_skip(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["group"]["group_id"] = 1   # p1's first group is 0
    return message


def _arrangement_size(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        seat_decision = _seat_decision(message)
        card = seat_decision["candidates"][1]["semantic"]["source"]   # the acting seat's hand Mountain
        seat_decision["context"]["kind"] = "choice"
        seat_decision["group"]["substep_count"] = 2   # an arrangement of 2 cards is 2 * 2 - 1 = 3 substeps
        seat_decision["candidates"] = [
            {"candidate_id": index,
             "semantic": {"kind": "arrange_card", "source": None, "purpose": "scry", "card": card,
                          "card_index": 0, "card_count": 2, "destination": destination},
             "display_text": None}
            for index, destination in enumerate(("top", "bottom"))
        ]
    return message


# ---------------------------------------------------------------------------
# V4: reference equality (spec 5.1)
# ---------------------------------------------------------------------------


def _stale_reference(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["candidates"][1]["semantic"]["source"]["card_name"] = "Island"
    return message


def _absent_reference(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["candidates"][1]["semantic"]["source"]["object_id"] = "obj-no-such-object"
    return message


def _duplicate_id(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        hand = _players(message)[1]["hand"]
        hand[1]["object_id"] = hand[0]["object_id"]
    return message


# ---------------------------------------------------------------------------
# V5: hidden zones and knowledge (spec 6.3, 6.7)
# ---------------------------------------------------------------------------


def _opponent_hand(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        players = _players(message)
        record = copy.deepcopy(players[1]["hand"][0])
        record["object_id"] += "-p0"                          # a fresh id, so V4's uniqueness stays intact
        record["owner_seat"] = record["controller_seat"] = "p0"   # V1: a hand record belongs to its holder
        players[0]["hand"] = [record]                         # the viewer is p1: p0's hand must be null
    return message


def _hand_count(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _players(message)[1]["hand_count"] = 1   # the viewer's hand holds 2 records
    return message


def _library_record(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        player = _players(message)[1]
        record = copy.deepcopy(player["hand"][1])
        record["object_id"] += "-library"
        record["zone"] = "library"   # library knowledge lives only in known (spec 6.7)
        player["graveyard"].append(record)
    return message


def _known_entry(card: str) -> dict[str, Any]:
    return {"owner_seat": "p0", "zone": "library", "card_name": card, "object_id": None,
            "position_from_top": None, "position_from_bottom": None, "how": "searching"}


def _known_unsorted(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        # "Mountain" sorts after "Lightning Bolt" in the spec 6.7 order, so this pair is out of order.
        known = [_known_entry("Mountain"), _known_entry("Lightning Bolt")]
        _seat_decision(message)["observation"]["known"] = known
    return message


# ---------------------------------------------------------------------------
# V6: face-down objects (spec 6.4, 6.8)
# ---------------------------------------------------------------------------


def _face_down_name(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        # p0's battlefield Mountain, face down with the face-down 2/2's characteristics, but still named for
        # a viewer who may not look at it: the name is the one thing it leaks.
        record = _players(message)[0]["battlefield"][0]
        name = record["card_name"]
        _turn_face_down(record)["card_name"] = name
    return message


def _face_down_characteristics(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        record = _players(message)[0]["battlefield"][0]
        record["face_down"] = True
        record["card_name"] = None   # nameless, but still showing the printed land characteristics
        record["full_name"] = None
    return message


# ---------------------------------------------------------------------------
# V7: id history (spec 5.3)
# ---------------------------------------------------------------------------


def _make_id_two_zones() -> Mutate:
    played: dict[str, str] = {}

    def mutate(step: int, message: dict) -> dict:
        if message.get("response_type") == "decision":
            if step == 0:
                # p0's play_land source: the hand id its played Mountain must not keep (spec 5.3).
                played["id"] = _seat_decision(message)["candidates"][1]["semantic"]["source"]["object_id"]
            elif step == 2 and "id" in played:
                _players(message)[0]["battlefield"][0]["object_id"] = played["id"]
        return message

    return mutate


# ---------------------------------------------------------------------------
# V8 and V9: declarations and context (spec 6.9, 7.1, 9.1, 9.3, 14)
# ---------------------------------------------------------------------------


def _choose_boolean() -> dict:
    return {"kind": "choose_boolean", "source": None, "purpose": "may_ability", "value": True}


def _undeclared_kind(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        seat_decision = _seat_decision(message)
        seat_decision["context"]["kind"] = "choice"
        seat_decision["candidates"] = [{"candidate_id": 0, "semantic": _choose_boolean(), "display_text": None}]
    return message


def _flag_off_value(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _players(message)[0]["poison"] = 0   # the poison flag is off
    return message


def _undeclared_extension(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["extensions"] = {"x_leak": 1}
    return message


def _family_mismatch(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        _seat_decision(message)["candidates"].append(
            {"candidate_id": 2, "semantic": _choose_boolean(), "display_text": None})
    return message


# ---------------------------------------------------------------------------
# V10 and the wire faults
# ---------------------------------------------------------------------------


def _provenance_drift(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        message["provenance"]["engine_version"] = "0.0.0"
    return message


def _garbage_json(step: int, message: dict) -> dict | bytes:
    if _is_decision(message, 1):
        return b"this is not json"
    return message


def _wrong_request_id(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        message["request_id"] = "h-0"   # the step's request id is h-3
    return message


def _deep_json(step: int, message: dict) -> dict | bytes:
    if _is_decision(message, 1):
        nested: list = []
        for _ in range(67):
            nested = [nested]
        # Root, seat_decision, extensions, then 67 lists: the innermost sits at level 70, past the
        # wire's 64-level cap (spec 2), which canonical_json_dumps would refuse, so write raw bytes.
        _seat_decision(message)["extensions"] = {"x_deep": nested}
        return json.dumps(message).encode("utf-8")
    return message


def _error_on_step(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        return {"response_type": "error", "protocol": message["protocol"], "request_id": message["request_id"],
                "error": {"code": "unsupported_request", "message": "the engine refuses this step (injected fault)"}}
    return message


def _hang_on_step(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        time.sleep(60)
    return message


def _crash_on_step(step: int, message: dict) -> dict:
    if _is_decision(message, 1):
        sys.exit(5)
    return message


def _bad_terminal_counts(step: int, message: dict) -> dict:
    if message.get("response_type") == "terminal":
        message["decision_count"] += 1
    return message


def _bad_terminal_steps(step: int, message: dict) -> dict:
    if message.get("response_type") == "terminal":
        message["step_count"] += 1
    return message


def _copied(fn: Mutate) -> Mutate:
    """Every mutation edits a deep copy and leaves the message otherwise valid, so exactly one rule breaks."""

    def mutate(step: int, message: dict) -> dict | bytes:
        return fn(step, copy.deepcopy(message))

    return mutate


MUTATIONS: dict[str, Mutate] = {
    "unknown-kind": _copied(_unknown_kind),
    "reserved-kind": _copied(_reserved_kind),
    "duplicate-semantics": _copied(_duplicate_semantics),
    "pass-not-first": _copied(_pass_not_first),
    "nfd-name": _copied(_nfd_name),
    "search-minimum": _copied(_search_minimum),
    "order-pick-source": _copied(_order_pick_source),
    "viewer-mismatch": _copied(_viewer_mismatch),
    "priority-holder": _copied(_priority_holder),
    "seat-step-gap": _copied(_seat_step_gap),
    "group-skip": _copied(_group_skip),
    "arrangement-size": _copied(_arrangement_size),
    "stale-reference": _copied(_stale_reference),
    "absent-reference": _copied(_absent_reference),
    "duplicate-id": _copied(_duplicate_id),
    "opponent-hand": _copied(_opponent_hand),
    "hand-count": _copied(_hand_count),
    "library-record": _copied(_library_record),
    "known-unsorted": _copied(_known_unsorted),
    "face-down-name": _copied(_face_down_name),
    "face-down-characteristics": _copied(_face_down_characteristics),
    "id-two-zones": _copied(_make_id_two_zones()),
    "undeclared-kind": _copied(_undeclared_kind),
    "flag-off-value": _copied(_flag_off_value),
    "undeclared-extension": _copied(_undeclared_extension),
    "family-mismatch": _copied(_family_mismatch),
    "provenance-drift": _copied(_provenance_drift),
    "garbage-json": _copied(_garbage_json),
    "wrong-request-id": _copied(_wrong_request_id),
    "deep-json": _copied(_deep_json),
    "error-on-step": _copied(_error_on_step),
    "hang-on-step": _copied(_hang_on_step),
    "crash-on-step": _copied(_crash_on_step),
    "bad-terminal-counts": _copied(_bad_terminal_counts),
    "bad-terminal-steps": _copied(_bad_terminal_steps),
}

assert set(MUTATIONS) == set(MODES) == set(DETAILS)   # every mode has its mutation and its cause's text

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        raise SystemExit(f"usage: hostile_v2_engine.py MODE [fake engine args...]; modes: {', '.join(sorted(MODES))}")
    MODE = sys.argv[1]
    sys.exit(fake_v2_engine.serve([*sys.argv[2:], *FIXED_ARGS.get(MODE, ())], mutate=MUTATIONS[MODE]))
