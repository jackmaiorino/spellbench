"""The tours pass the live validator and cover every v2.0 kind, group shape and board field."""

from __future__ import annotations

from spellbench.candidates import V2_KINDS

import fake_v2_scenario_board
import fake_v2_scenario_kinds
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
