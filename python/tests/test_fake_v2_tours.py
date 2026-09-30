"""The tours pass the live validator and cover every v2.0 kind, group shape and board field."""

from __future__ import annotations

import sys

import pytest

from spellbench._schema import OBSERVATION_FLAGS, PRIORITY_KINDS
from spellbench.candidates import V2_KINDS
from spellbench.host.engine_process import EngineProcess

import fake_v2_scenario_board
import fake_v2_scenario_kinds
import tour_helpers
from fake_v2_world import CARDS, World
from tour_helpers import play_tour


def test_the_kinds_tour_covers_every_kind_and_group_shape() -> None:
    decisions = play_tour(fake_v2_scenario_kinds)                          # answered by fake_v2_scenario_kinds.pick
    kinds = {c["semantic"]["kind"] for sd in decisions for c in sd["candidates"]}
    assert kinds == V2_KINDS
    multi = {(sd["candidates"][0]["semantic"]["kind"], sd["group"]["substep_count"]) for sd in decisions if sd["group"]["substep_count"] > 1}
    assert {"declare_attack", "declare_block", "choose_target", "select_object", "choose_spell_mode", "distribute", "arrange_card"} <= {kind for kind, _ in multi}
    assert ("arrange_card", 3) in multi                                  # scry 2: 2n - 1 decisions
    assert any(sd["group"]["substep_index"] == 0 and sd["group"]["substep_count"] > 1
               and sd["candidates"][0]["semantic"]["kind"] == "order_pick" for sd in decisions)      # an order block (R2-9)
    finishes = [sd for sd in decisions if any(c["semantic"]["kind"].startswith("finish_") for c in sd["candidates"])]
    assert finishes and all(sd["group"]["substep_count"] == 1 for sd in finishes)
    assert any(sd["context"]["rewind"] for sd in decisions)
    payments = [sd for sd in decisions if sd["context"]["purpose"] == "mana_payment"]
    first_pays = {c["semantic"].get("pay") for c in payments[0]["candidates"]}
    assert first_pays == {None, False} and any(c["semantic"].get("pay") is True for c in payments[-1]["candidates"])  # R2-22


def _board_features(sd: dict) -> set[str]:
    """Name each board feature a decision shows; 0, {}, "none" and empty lists count as absent (R2-10)."""
    o = sd["observation"]
    found: set[str] = set()

    def add(name: str, present) -> None:
        if present:
            found.add(name)

    add("pregame", o["phase_step"] == "pregame" and o["active_seat"] is None and o["priority_seat"] is None)
    add("passed_seats", o["passed_seats"])
    add("day", o["day_night"] == "day")
    add("night", o["day_night"] == "night")
    add("pending_triggers", o["pending_triggers"])
    add("known", o["known"])
    for p in o["players"]:
        progress = p["progress"] or {}
        add("poison", p["poison"])
        add("player_counters", p["counters"])
        add("mana_pool", any(p["mana_pool"].values()))
        add("lands_played", p["lands_played_this_turn"])
        add("mulligans_taken", p["mulligans_taken"])
        add("designations", p["designations"])
        add("dungeon_room", progress.get("dungeon_room") is not None)
        add("ring_tempted", progress.get("ring_tempted"))
        add("speed", progress.get("speed") is not None)
        add("graveyard", p["graveyard"])
        add("command", p["command"])
    records = [r for p in o["players"] for zone in ("hand", "battlefield", "graveyard", "exile", "command") for r in (p[zone] or [])]
    for r in records:
        add("full_name", r["full_name"] is not None)
        add("keywords", (r["characteristics"] or {}).get("keywords"))
        add("exiled_by", r["exiled_by"] is not None)
        add("token_copy", r["token"] and r["copy"])
        add("face_down_own", r["face_down"] and r["zone"] == "battlefield" and r["card_name"] is not None)
        add("face_down_other", r["face_down"] and r["zone"] == "battlefield" and r["card_name"] is None)
        add("face_down_exile_hidden", r["face_down"] and r["zone"] == "exile" and r["characteristics"] is None)
        permanent = r["permanent"]
        if permanent:
            add("tapped", permanent["tapped"])
            add("summoning_sick", permanent["summoning_sick"])
            add("damage", permanent["damage"])
            add("permanent_counters", permanent["counters"])
            add("attached_to", permanent["attached_to"] is not None)
            add("attack_planeswalker", permanent["attack_target"] is not None and "object" in permanent["attack_target"])
            add("blocked_attackers", permanent["blocked_attackers"])
            add("phased_out", permanent["phased_out"])
            add("statuses", permanent["statuses"])
            add("class_level", permanent["class_level"] is not None)
            add("chosen", permanent["chosen"])
    for entry in o["stack"]:
        add(entry["stack_kind"], True)
        add("departed_source", entry["stack_kind"] != "spell" and entry["source"] is None)
        add("face_down_spell", entry["face_down"])
        add("copied_spell", entry["stack_kind"] == "spell" and entry["copy"])
        add("null_target", None in entry["targets"])
        add("divided", entry["divided"] is not None)
        add("modes", entry["modes"] is not None)
        add("x_value", entry["x_value"] is not None)
        add("stack_text", entry["text"] is not None)
    return found


BOARD_FEATURES = {
    "pregame", "passed_seats", "day", "night", "pending_triggers", "known",
    "poison", "player_counters", "mana_pool", "lands_played", "mulligans_taken", "designations", "dungeon_room",
    "ring_tempted", "speed", "graveyard", "command",
    "full_name", "keywords", "exiled_by", "token_copy", "face_down_own", "face_down_other", "face_down_exile_hidden",
    "tapped", "summoning_sick", "damage", "permanent_counters", "attached_to", "attack_planeswalker", "blocked_attackers",
    "phased_out", "statuses", "class_level", "chosen",
    "spell", "activated_ability", "triggered_ability", "departed_source", "face_down_spell", "copied_spell", "null_target",
    "divided", "modes", "x_value", "stack_text",
}


def _flagged_values(sd: dict) -> list:
    """Every optional field of spec 6.9, each null when its flag is off."""
    o = sd["observation"]
    records = [r for p in o["players"] for zone in ("hand", "battlefield", "graveyard", "exile", "command") for r in (p[zone] or [])]
    permanents = [r["permanent"] for r in records if r["permanent"]]
    characteristics = [r["characteristics"] for r in records + o["stack"] if r["characteristics"]]
    return ([o["passed_seats"], o["day_night"], o["pending_triggers"]]
            + [p[field] for p in o["players"] for field in ("poison", "counters", "designations", "progress")]
            + [r["full_name"] for r in records] + [r["exiled_by"] for r in records]
            + [c["keywords"] for c in characteristics] + [entry["text"] for entry in o["stack"]]
            + [permanent[field] for permanent in permanents for field in ("statuses", "class_level", "chosen")])


def test_the_board_tour_shows_every_board_field_and_nothing_flagged_off() -> None:
    on = play_tour(fake_v2_scenario_board, "--all-flags")
    assert set().union(*(_board_features(sd) for sd in on)) == BOARD_FEATURES     # spec 6.2 to 6.6, every 6.9 flag
    off = play_tour(fake_v2_scenario_board)
    assert all(value is None for sd in off for value in _flagged_values(sd))


# Fix round 1: the tours follow the answers they are given and show only states the spec allows.

KINDS_BRIEF_ORDER = (         # the brief's items in its order, each named by its first decision (_first_steps)
    "choose_starting_player", "mulligan", "order_pick:mulligan_bottom", "play_land", "cast_spell", "choose_cast_method",
    "special_action", "activate_mana_ability", "activate_ability", "choose_target", "finish_target_selection",
    "choose_spell_mode", "finish_selection:modes", "choose_option", "choose_color", "choose_number", "choose_boolean",
    "choose_name", "select_object:discard", "select_object:search", "optional_cost:kicker", "optional_cast",
    "optional_cost:unless_payment", "order_pick:triggers", "arrange_card:scry", "choose_replacement", "declare_attack",
    "declare_block", "distribute", "arrange_card:pile_split", "choose_pile", "rewind",
)
MODAL_CARDS = {"Cryptic Command", "Borrowed Hostility"}
X_CARDS = {"Fireball"}
# The catalog cards (fake_v2_world.CARDS) with a triggered ability, and the object costs they can pay.
TRIGGER_SOURCES = {"Monastery Swiftspear", "Spellstutter Sprite", "Fathom Seer", "Journey to Nowhere", "Rancor",
                   "Fiery Temper", "Chandra, Torch of Defiance Emblem"}
OBJECT_COSTS = {("Fathom Seer", "return_to_hand")}


def _answered(decisions: list[dict], module) -> list[tuple[dict, dict]]:
    """Each decision with the semantic its tour answered (the module's pick, else candidate 0)."""
    pick = getattr(module, "pick", lambda sd: 0)
    return [(sd, sd["candidates"][pick(sd)]["semantic"]) for sd in decisions]


def _records(observation: dict) -> dict[str, dict]:
    zones = ("hand", "battlefield", "graveyard", "exile", "command")
    return {r["object_id"]: r for p in observation["players"] for zone in zones for r in (p[zone] or [])}


def _kinds_of(sd: dict) -> set[str]:
    return {c["semantic"]["kind"] for c in sd["candidates"]}


def test_the_stack_shows_the_targets_modes_and_x_the_tour_picked() -> None:
    picked: dict[tuple[str, str], dict] = {}   # (seat, stack object id) -> the targets, modes and X picked so far
    shown = {"choose_target": "targets", "choose_spell_mode": "modes", "choose_number": "x_value"}
    for sd, answer in _answered(play_tour(fake_v2_scenario_kinds), fake_v2_scenario_kinds):
        seat, stack = sd["acting_seat"], sd["observation"]["stack"]
        for entry in stack:
            assert None not in entry["targets"]           # no target of the kinds tour ever leaves (spec 6.5)
            for field, value in picked.get((seat, entry["object_id"]), {}).items():
                assert entry[field] == value              # what was picked stays shown while the entry is there
        source, field = sd["context"]["source"], shown.get(answer["kind"])
        if source is None or source["zone"] != "stack" or field is None:
            continue
        chosen = picked.setdefault((seat, source["object_id"]), {})
        entry = next(e for e in stack if e["object_id"] == source["object_id"])
        assert entry[field] == chosen.get(field, None if field == "x_value" else [])   # only what was picked so far
        if field == "targets":
            chosen[field] = entry[field] + [answer["target"]]
        elif field == "modes":
            chosen[field] = sorted(entry[field] + [answer["mode_index"]])
        else:
            chosen[field] = answer["value"]


def test_each_division_assigns_the_amount_picked_and_completes() -> None:
    splits: dict[tuple[str, int], list[tuple[dict, dict]]] = {}
    for sd, answer in _answered(play_tour(fake_v2_scenario_kinds), fake_v2_scenario_kinds):
        if "distribute" in _kinds_of(sd):
            splits.setdefault((sd["acting_seat"], sd["group"]["group_id"]), []).append((sd, answer))
    assert splits
    for split in splits.values():
        remaining = split[0][1]["remaining"]
        for index, (sd, answer) in enumerate(split):
            assert {c["semantic"]["remaining"] for c in sd["candidates"]} == {remaining}   # spec 7.5
            if index == len(split) - 1:                   # the last recipient takes the rest (CR 510.1a)
                assert [c["semantic"]["amount"] for c in sd["candidates"]] == [remaining]
            remaining -= answer["amount"]
        assert remaining == 0


def test_the_first_mana_payment_is_posed_on_an_empty_pool() -> None:
    decisions = play_tour(fake_v2_scenario_kinds)
    payments = [sd for sd in decisions if sd["context"]["purpose"] == "mana_payment"]
    first, last = payments[0], payments[-1]
    payer = first["observation"]["players"][("p0", "p1").index(first["acting_seat"])]
    assert not any(payer["mana_pool"].values())                                          # R2-22
    land = next(c["semantic"]["source"] for c in first["candidates"] if c["semantic"]["kind"] == "activate_mana_ability")
    assert _records(first["observation"])[land["object_id"]]["permanent"]["tapped"] is False
    assert _records(last["observation"])[land["object_id"]]["permanent"]["tapped"] is True
    assert last["observation"]["players"][("p0", "p1").index(last["acting_seat"])]["mana_pool"]["R"] == 1
    for sd in decisions:                                   # a {T} mana ability is offered only for an untapped source
        for c in sd["candidates"]:
            if c["semantic"]["kind"] == "activate_mana_ability":
                assert _records(sd["observation"])[c["semantic"]["source"]["object_id"]]["permanent"]["tapped"] is False


def test_every_catalog_row_names_a_card_and_a_double_faced_card_by_its_full_name() -> None:
    faces = {name for name, card in CARDS.items() if card["full_name"] is not None}     # spec 4.4
    no_card = {name for name, card in CARDS.items() if not card["types"]}               # an emblem (spec 12.1)
    engine = EngineProcess([sys.executable, str(tour_helpers.ENGINE)], timeout_s=30)
    try:
        rows = [row.name for deck in engine.hello().catalog for row in deck.decklist]
    finally:
        engine.close()
    for module in (fake_v2_scenario_kinds, fake_v2_scenario_board):
        assert {row["name"] for row in module.SCENARIO.decklist} <= set(rows)
    assert not set(rows) & (faces | no_card)
    assert all(name in CARDS or name in {card["full_name"] for card in CARDS.values()} for name in rows)


def test_combat_is_declared_by_the_right_seats_over_attacking_creatures() -> None:
    for sd in play_tour(fake_v2_scenario_kinds):
        observation, kinds = sd["observation"], _kinds_of(sd)
        records = _records(observation)
        if "declare_attack" in kinds:
            assert sd["acting_seat"] == observation["active_seat"]                        # CR 508.1
        if "declare_block" in kinds:
            assert sd["acting_seat"] != observation["active_seat"]                        # CR 509.1
            for c in sd["candidates"]:
                assert c["semantic"]["blocker"]["controller_seat"] == sd["acting_seat"]
                if c["semantic"]["attacker"] is not None:                                 # spec 7.5
                    assert records[c["semantic"]["attacker"]["object_id"]]["permanent"]["attacking"]
        if "distribute" in kinds and sd["candidates"][0]["semantic"]["purpose"] == "combat_damage":
            assert sd["candidates"][0]["semantic"]["source"]["controller_seat"] == sd["acting_seat"]   # CR 510.1


def test_a_blocker_lists_only_attacking_creatures_it_blocks() -> None:
    for sd in play_tour(fake_v2_scenario_kinds) + play_tour(fake_v2_scenario_board, "--all-flags"):
        records = _records(sd["observation"])
        for record in records.values():
            permanent = record["permanent"]
            for attacker in (permanent or {}).get("blocked_attackers") or []:              # spec 6.4
                assert permanent["blocking"] and records[attacker["object_id"]]["permanent"]["attacking"]
                assert attacker["controller_seat"] != record["controller_seat"]
            if permanent and permanent["attacking"]:
                assert record["controller_seat"] == sd["observation"]["active_seat"]
                assert sd["observation"]["phase_step"] in ("declare_attackers", "declare_blockers", "combat_damage",
                                                           "end_of_combat")


def test_both_seats_are_asked_to_mulligan_under_london() -> None:
    for tour in (play_tour(fake_v2_scenario_kinds), play_tour(fake_v2_scenario_board)):
        assert {sd["acting_seat"] for sd in tour if "mulligan" in _kinds_of(sd)} == {"p0", "p1"}     # spec 7.6


def test_stack_entries_show_modes_and_x_only_on_cards_that_have_them() -> None:
    for sd in play_tour(fake_v2_scenario_kinds) + play_tour(fake_v2_scenario_board, "--all-flags"):
        for entry in sd["observation"]["stack"]:
            if entry["face_down"] and entry["stack_kind"] == "spell":                   # a textless 2/2 (CR 708.4)
                assert (entry["targets"], entry["divided"], entry["modes"], entry["x_value"]) == ([], None, None, None)
            if entry["stack_kind"] == "spell" and entry["card_name"] not in MODAL_CARDS:
                assert entry["modes"] is None                                             # spec 6.5
            if entry["stack_kind"] == "spell" and entry["card_name"] not in X_CARDS:
                assert entry["x_value"] is None


def test_the_tours_keep_the_cards_rules() -> None:
    for sd in play_tour(fake_v2_scenario_kinds) + play_tour(fake_v2_scenario_board, "--all-flags"):
        for c in sd["candidates"]:
            semantic = c["semantic"]
            if semantic.get("method") == "flashback":                                   # CR 702.34a
                assert (semantic.get("source") or semantic.get("card"))["zone"] == "graveyard"
            if semantic["kind"] == "order_pick" and semantic["purpose"] == "triggers":   # CR 603.3b
                assert semantic["item"]["trigger"]["source"]["controller_seat"] == sd["acting_seat"]
            if semantic["kind"] == "choose_cost_target":
                assert (semantic["source"]["card_name"], semantic["cost_kind"]) in OBJECT_COSTS
        for p in sd["observation"]["players"]:
            if p["progress"] is not None and p["progress"]["dungeon_room"] is not None:
                assert p["progress"]["dungeon"] is not None                              # a room is in a dungeon
        for entry in sd["observation"]["stack"]:
            if entry["stack_kind"] == "triggered_ability":
                assert entry["card_name"] in TRIGGER_SOURCES


def _first_steps(decisions: list[dict]) -> dict[str, int]:
    """The index of the first decision of each brief item, named ``kind``, ``kind:purpose`` or ``kind:cost``."""
    first: dict[str, int] = {}
    for index, sd in enumerate(decisions):
        names = {"rewind"} if sd["context"]["rewind"] else set()
        for c in sd["candidates"]:
            semantic = c["semantic"]
            names.add(semantic["kind"])
            for field in ("purpose", "cost"):
                if field in semantic:
                    names.add(f"{semantic['kind']}:{semantic[field]}")
        for name in names:
            first.setdefault(name, index)
    return first


def test_the_kinds_tour_poses_the_brief_items_in_order() -> None:
    first = _first_steps(play_tour(fake_v2_scenario_kinds))
    assert [first[item] for item in KINDS_BRIEF_ORDER] == sorted(first[item] for item in KINDS_BRIEF_ORDER)


def _drive(script, answer) -> None:
    """Run a scenario script in process as the engine does, answering each Posed with ``answer(posed)``."""
    posed = script.send(None)
    while True:
        posed = script.send(answer(posed))


def _pick_posed(posed) -> int:
    """fake_v2_scenario_kinds.pick read from a Posed: the last candidate of a priority decision, else 0."""
    priority = posed.kind is None and posed.candidates[0]["kind"] in PRIORITY_KINDS
    return len(posed.candidates) - 1 if priority and len(posed.candidates) > 1 else 0


def test_a_step_that_assumes_an_answer_fails_loudly_when_given_another() -> None:
    def passes_instead_of_playing_a_land(posed) -> int:
        return 0 if any(c["kind"] == "play_land" for c in posed.candidates) else _pick_posed(posed)

    world = World(b"\x22" * 32, flags=dict.fromkeys(OBSERVATION_FLAGS, False))
    with pytest.raises(AssertionError, match="play_land"):
        _drive(fake_v2_scenario_kinds.SCENARIO.script(world), passes_instead_of_playing_a_land)


# T26b (Task 26 re-review): the tours play only cards whose rules text fits the play, show a waiting
# trigger only in the one window the rules allow it, and decline an attack.

def test_the_unless_payment_is_a_force_spike() -> None:
    # Counterspell imposes no unless-payment, and Mana Leak's {3} would break the one-activation payment.
    payments = [c["semantic"] for sd in play_tour(fake_v2_scenario_kinds) for c in sd["candidates"]
                if c["semantic"].get("cost") == "unless_payment"]
    assert payments and all(semantic["source"]["card_name"] == "Force Spike" for semantic in payments)


def test_the_additional_blocker_is_a_night_market_guard() -> None:
    extra = []
    for sd, answer in _answered(play_tour(fake_v2_scenario_kinds), fake_v2_scenario_kinds):
        if answer["kind"] == "declare_block" and answer["attacker"] is not None:
            record = _records(sd["observation"])[answer["blocker"]["object_id"]]
            if record["permanent"]["blocked_attackers"]:            # already blocking one: an additional block
                extra.append(record["card_name"])
    assert extra == ["Night Market Guard"]       # the only catalog card that can block a second creature


def test_a_waiting_trigger_shows_only_while_its_controller_orders_it() -> None:
    for sd in play_tour(fake_v2_scenario_board, "--all-flags"):
        triggers = sd["observation"]["pending_triggers"] or []
        if not triggers:
            continue
        # CR 117.5 and 603.3: a waiting trigger goes on the stack before anyone next receives priority, so
        # an observation can show one only in a window without priority — here, while p0 orders its triggers.
        assert sd["observation"]["priority_seat"] is None
        assert any(c["semantic"]["kind"] == "order_pick" and c["semantic"].get("purpose") == "triggers"
                   for c in sd["candidates"])
        assert any(trigger["source_name"] == "Monastery Swiftspear" and trigger["controller_seat"] == "p0"
                   for trigger in triggers)                        # the prowess trigger the re-review held


def test_the_kinds_tour_holds_one_creature_back() -> None:
    answers = [answer for _, answer in _answered(play_tour(fake_v2_scenario_kinds), fake_v2_scenario_kinds)
               if answer["kind"] == "declare_attack"]
    assert sum(answer["defender"] is not None for answer in answers) == 2
    assert any(answer["defender"] is None for answer in answers)   # a declined attack (declare with nothing)
