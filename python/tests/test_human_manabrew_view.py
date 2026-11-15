"""The Manabrew game view: stack order, game over, attachments, haste, designations, stack objects, turn number.

The cases marked recorded run over the operator engine records of the human games (skipped when they are not on this
machine); the others build the same shapes by hand, so they also run in CI.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from spellbench.human import replay, text
from spellbench.human.manabrew import view
from spellbench.human.manabrew.host import Bridge
from spellbench.human.server import Hub

ME, OPP = "p0", "p1"
SEATS = view.Seats(ME, "player-0", "player-1", {"player-0": "human", "player-1": "Basilisk 2"})

ROOT = Path(os.environ.get("SPELLBENCH_HUMAN_RECORDS", "E:/artifacts/chains-20261107-human-interim/engine-records/cold"))
RECORDS = sorted(ROOT.glob("game-*/engine.jsonl.gz"))
recorded = pytest.mark.skipif(not RECORDS, reason="the recorded human games are not on this machine")


def creature(oid: str, name: str, seat: str, zone: str = "battlefield", *, keywords=(), **permanent: Any) -> dict:
    entry = {"object_id": oid, "card_name": name, "full_name": name, "owner_seat": seat, "controller_seat": seat,
             "zone": zone, "token": False, "copy": False, "face_down": False,
             "characteristics": {"colors": ["red"], "keywords": list(keywords), "mana_value": 2, "power": 2,
                                 "toughness": 2, "subtypes": [], "supertypes": [], "types": ["creature"]}}
    if zone == "battlefield":
        entry["permanent"] = {"tapped": False, "attacking": False, "blocking": False, "blocked_attackers": [],
                              "counters": {}, "damage": 0, "summoning_sick": False, "attached_to": None, **permanent}
    return entry


def board(stack=(), **top) -> dict:
    return {"turn": 5, "active_seat": ME, "priority_seat": ME, "phase_step": "precombat_main", "stack": list(stack),
            "known": [], "players": [
                {"seat": ME, "life": 20, "hand": [], "hand_count": 0, "library_count": 40, "battlefield": [],
                 "graveyard": [], "exile": [], "mana_pool": {}, "lands_played_this_turn": 0, "designations": []},
                {"seat": OPP, "life": 20, "hand": None, "hand_count": 3, "library_count": 40, "battlefield": [],
                 "graveyard": [], "exile": [], "mana_pool": {}, "lands_played_this_turn": 0, "designations": []}],
            **top}


def spell(oid: str, name: str, seat: str, *, types=("creature",)) -> dict:
    return {"object_id": oid, "card_name": name, "owner_seat": seat, "controller_seat": seat, "zone": "stack",
            "stack_kind": "spell", "source": None, "face_down": False, "copy": False, "targets": [], "text": None,
            "modes": [0], "x_value": 0, "divided": None,
            "characteristics": {"colors": [], "keywords": [], "mana_value": 4, "power": 2, "toughness": 3,
                                "subtypes": [], "supertypes": [], "types": list(types)}}


def ability(oid: str, kind: str, source: dict, seat: str) -> dict:
    ref = {k: source[k] for k in ("card_name", "controller_seat", "object_id", "owner_seat", "zone")}
    return {"object_id": oid, "card_name": source["card_name"], "owner_seat": seat, "controller_seat": seat,
            "zone": "stack", "stack_kind": kind, "source": ref, "face_down": False, "copy": False, "targets": [],
            "text": None, "modes": [0], "x_value": 0, "divided": None, "characteristics": None}


# The stack of a recorded game (turn 5 of the Wildfire against Faeries game), top first as the engine lists it: the
# opponent flashed in Humbling Elder in response to the Writhing Chrysalis cast trigger, which sits on the Chrysalis.
CHRYSALIS = spell("795a9cf5a8ba2d843dfc61ce445d4d0b", "Writhing Chrysalis", ME)
TRIGGER = ability("743cab39a6605fe4a30dce83ed2b6f02", "triggered_ability", CHRYSALIS, ME)
ELDER = spell("dfca3fb36afd53de0dbbfcd4f102833b", "Humbling Elder", OPP)
ENGINE_STACK = [ELDER, TRIGGER, CHRYSALIS]


# -- item 9: the stack order, settled by the engine's own records ---------------------------------------------------------


def test_the_client_gets_the_stack_bottom_first_so_its_last_entry_is_the_engines_top() -> None:
    gv = view.game_view(board(ENGINE_STACK), SEATS, "g1")
    assert [s["id"] for s in gv["stack"]] == [CHRYSALIS["object_id"], TRIGGER["object_id"], ELDER["object_id"]]
    assert gv["stack"][-1]["identity"]["name"] == "Humbling Elder"  # the client draws the last entry as the top


def test_every_reader_names_the_same_top_of_the_stack() -> None:
    observation = board(ENGINE_STACK)
    assert text.stack_top(observation["stack"]) is ELDER and text.stack_top([]) is None
    assert text.stack_bottom_first(observation["stack"]) == [CHRYSALIS, TRIGGER, ELDER]
    decision = {"context": {"kind": "priority"}, "candidates": [], "group": {}, "observation": observation}
    assert text.prompt(decision, ME) == "Opp: Humbling Elder on the stack. Respond?"
    hub = Hub(opponent="Basilisk 2")
    hub.game = {"seat": ME}
    hub.stops = {"opp_stack": True, "own_stack": False}
    assert hub._stops_here(decision) is True  # the top is the opponent's Humbling Elder
    own_top = board([TRIGGER, CHRYSALIS, ELDER])
    assert hub._stops_here({**decision, "observation": own_top}) is False  # the top is our own trigger


def test_no_code_reads_the_stack_end_outside_the_one_place_that_knows_the_order() -> None:
    package = Path(text.__file__).parent
    pattern = re.compile(r"stack\w*\)?\[-1\]|reversed\([^)]*stack|stack\w*\[::-1\]|stack\w*\[0\]")
    offenders = []
    for path in sorted(package.rglob("*.py")):
        if path.name == "text.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []


def walk_records() -> Iterator[tuple[Path, list[dict]]]:
    for path in RECORDS:
        yield path, list(replay.decisions(replay.read_record(path)))


@recorded
def test_recorded_stacks_are_top_first_at_every_hop() -> None:
    """Between two consecutive decisions of a recorded game, a stack that loses one object loses index 0 (the one that
    resolves first) and one that gains an object gains it at index 0, in every game with a stack of two or more."""
    pops, pushes, multi = 0, 0, 0
    for _, decisions in walk_records():
        previous: list[str] | None = None
        for sd in decisions:
            ids = [e["object_id"] for e in sd["observation"]["stack"]]
            multi += len(ids) >= 2
            if previous is not None and len(previous) >= 2 and len(ids) == len(previous) - 1:
                gone = [i for i, oid in enumerate(previous) if oid not in ids]
                if len(gone) == 1 and [o for o in previous if o != previous[gone[0]]] == ids:
                    assert gone == [0], (previous, ids)
                    pops += 1
            if previous is not None and len(ids) >= 2 and len(ids) == len(previous) + 1:
                new = [i for i, oid in enumerate(ids) if oid not in previous]
                if len(new) == 1 and [o for o in ids if o != ids[new[0]]] == previous:
                    assert new == [0], (previous, ids)
                    pushes += 1
            previous = ids
    assert multi >= 40 and pops >= 5 and pushes >= 2


@recorded
def test_recorded_stack_views_put_a_trigger_above_the_spell_it_came_from_and_the_last_entry_is_the_top() -> None:
    checked = 0
    for _, decisions in walk_records():
        for sd in decisions:
            stack = sd["observation"]["stack"]
            if len(stack) < 2:
                continue
            seats = view.Seats(sd["acting_seat"], "player-0", "player-1", {})
            gv = view.game_view(sd["observation"], seats, "g")
            ids = [s["id"] for s in gv["stack"]]
            assert ids[-1] == stack[0]["object_id"]  # the client's top is the engine's index 0
            for entry in stack:
                src = (entry.get("source") or {}).get("object_id")
                if src in ids:  # an ability on its source spell: it is above it (resolves first)
                    assert ids.index(entry["object_id"]) > ids.index(src)
                    checked += 1
    assert checked >= 5


# -- item 13: game over ---------------------------------------------------------------------------------------------------


def over(winner, classification="natural", reason="game_over") -> dict:
    return {"winner": winner, "classification": classification, "reason": reason}


def statuses(terminal: dict) -> tuple[dict, str | None]:
    gv = view.game_view(board(), SEATS, "g1", game_over=True, winner=None, terminal=terminal)
    return {p["id"]: p["status"] for p in gv["players"]}, gv["winnerId"]


def test_the_loser_reads_lost_the_winner_playing_and_the_winner_is_named() -> None:
    assert statuses(over(OPP)) == ({"player-0": "lost", "player-1": "playing"}, "player-1")
    assert statuses(over(ME)) == ({"player-0": "playing", "player-1": "lost"}, "player-0")


def test_a_concession_reads_conceded_and_a_lost_connection_or_timeout_reads_lost() -> None:
    assert statuses(over(OPP, "conceded", "conceded")) == ({"player-0": "conceded", "player-1": "playing"}, "player-1")
    assert statuses(over(OPP, "connection_lost", "connection_lost"))[0]["player-0"] == "lost"
    assert statuses(over(OPP, "forfeit", "timeout"))[0]["player-0"] == "lost"


def test_a_draw_or_a_halted_game_names_no_winner_and_nobody_lost() -> None:
    assert statuses(over(None, "halted", "engine_fault")) == ({"player-0": "playing", "player-1": "playing"}, None)


def test_a_game_in_progress_keeps_everyone_playing() -> None:
    gv = view.game_view(board(), SEATS, "g1")
    assert {p["status"] for p in gv["players"]} == {"playing"} and gv["winnerId"] is None


def test_the_host_sends_the_final_view_with_the_statuses() -> None:
    hub = Hub(opponent="Basilisk 2")
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Wildfire"}, "opponent_deck": {"name": "Rally"}})
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": lambda self, m: sent.append(m)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = SEATS
    hub.concede("conceded")
    bridge._push({**hub.state(), "observation": board()})
    last = [m for m in sent if m.get("state", {}).get("kind") == "state"][-1]["state"]["state"]["gameView"]
    assert last["gameOver"] and last["winnerId"] == "player-1"
    assert {p["id"]: p["status"] for p in last["players"]} == {"player-0": "conceded", "player-1": "playing"}


# -- item 19: auras and equipment ---------------------------------------------------------------------------------------


def attached_board() -> dict:
    host = creature("c1", "Writhing Chrysalis", ME)
    aura = creature("a1", "Nyxborn Hydra", ME, attached_to={"object": {
        "card_name": "Writhing Chrysalis", "controller_seat": ME, "object_id": "c1", "owner_seat": ME,
        "zone": "battlefield"}})
    observation = board()
    observation["players"][0]["battlefield"] = [host, aura]
    return observation


def test_an_aura_is_attached_to_its_host_in_both_directions() -> None:
    gv = view.game_view(attached_board(), SEATS, "g1")
    cards = {c["id"]: c for z in gv["zones"] if z["zone"] == "battlefield" for c in z["cards"]}
    assert cards["a1"]["attachedTo"] == "c1"
    assert cards["c1"]["attachmentIds"] == ["a1"] and "attachedTo" not in cards["c1"]


@recorded
def test_a_recorded_attachment_reads_as_attached() -> None:
    seen = 0
    for _, decisions in walk_records():
        for sd in decisions:
            observation = sd["observation"]
            attached = [(c["object_id"], c["permanent"]["attached_to"]["object"]["object_id"])
                        for p in observation["players"] for c in p["battlefield"]
                        if (c.get("permanent") or {}).get("attached_to")]
            if not attached:
                continue
            seats = view.Seats(sd["acting_seat"], "player-0", "player-1", {})
            gv = view.game_view(observation, seats, "g")
            cards = {c["id"]: c for z in gv["zones"] for c in z["cards"] if c.get("visibility") == "visible"}
            for aura, host in attached:
                assert cards[aura]["attachedTo"] == host and aura in cards[host]["attachmentIds"]
                seen += 1
    assert seen >= 1


# -- item 20: haste -------------------------------------------------------------------------------------------------------


def test_a_creature_with_haste_is_not_shown_summoning_sick() -> None:
    observation = board()
    observation["players"][0]["battlefield"] = [
        creature("h", "Goblin Heelcutter", ME, keywords=["haste"], summoning_sick=True),
        creature("s", "Writhing Chrysalis", ME, keywords=["reach"], summoning_sick=True),
        creature("o", "Elvish Mystic", ME, summoning_sick=False)]
    cards = {c["id"]: c for z in view.game_view(observation, SEATS, "g")["zones"]
             if z["zone"] == "battlefield" for c in z["cards"]}
    assert [cards[i]["summoningSick"] for i in ("h", "s", "o")] == [False, True, False]


@recorded
def test_recorded_hasty_creatures_are_never_summoning_sick_in_the_view() -> None:
    hasty = sick = 0
    for _, decisions in walk_records():
        for sd in decisions:
            seats = view.Seats(sd["acting_seat"], "player-0", "player-1", {})
            sick += sum(1 for p in sd["observation"]["players"] for c in p["battlefield"]
                        if "haste" in c["characteristics"]["keywords"] and c["permanent"]["summoning_sick"])
            gv = view.game_view(sd["observation"], seats, "g")
            for zone in gv["zones"]:
                for c in zone["cards"]:
                    if c.get("visibility") == "visible" and zone["zone"] == "battlefield" and "Haste" in c["keywords"]:
                        hasty += 1
                        assert c["summoningSick"] is False
    assert hasty >= 3 and sick >= 1  # the engine's flag does say sick for some of them


# -- item 23: stack objects -----------------------------------------------------------------------------------------------


def test_stack_objects_carry_their_card_and_an_ability_names_the_line_it_is() -> None:
    gv = view.game_view(board(ENGINE_STACK), SEATS, "g1")
    by_id = {s["id"]: s for s in gv["stack"]}
    elder, trigger, chrysalis = (by_id[e["object_id"]] for e in ENGINE_STACK)
    assert elder["sourceCard"]["identity"]["name"] == "Humbling Elder" and "Creature" in elder["sourceCard"]["types"]
    assert chrysalis["sourceCard"]["identity"]["name"] == "Writhing Chrysalis"
    # the trigger shows the Chrysalis (still on the stack) and highlights its cast trigger, not every line
    assert trigger["sourceCard"]["identity"]["name"] == "Writhing Chrysalis" and trigger["sourceId"] == CHRYSALIS["object_id"]
    assert trigger["text"].startswith("When you cast this spell, create two 0/1")
    assert "Triggered ability of" not in json.dumps(gv)


def test_an_ability_of_a_permanent_shows_the_permanent_untapped_with_its_own_line() -> None:
    shaman = creature("k1", "Krark-Clan Shaman", ME, tapped=True, summoning_sick=True)
    activated = ability("s1", "activated_ability", {**shaman, "zone": "battlefield"}, ME)
    observation = board([activated])
    observation["players"][0]["battlefield"] = [shaman]
    entry = view.game_view(observation, SEATS, "g1")["stack"][0]
    assert entry["sourceCard"]["identity"]["name"] == "Krark-Clan Shaman"
    assert entry["sourceCard"]["tapped"] is False and entry["sourceCard"]["summoningSick"] is False
    assert entry["sourceCard"]["zone"] == "stack"
    assert entry["text"].startswith("Sacrifice an artifact:")


def test_an_ability_whose_source_left_is_built_from_the_name_and_a_hidden_source_gets_no_card() -> None:
    gone = {"card_name": "Krark-Clan Shaman", "controller_seat": ME, "object_id": "gone", "owner_seat": ME,
            "zone": "graveyard"}
    entry = view.game_view(board([ability("s1", "triggered_ability", gone, ME)]), SEATS, "g")["stack"][0]
    assert entry["sourceCard"]["identity"]["name"] == "Krark-Clan Shaman"
    assert "Creature" in entry["sourceCard"]["types"] and entry["sourceCard"]["power"] == "1"
    hidden = {**gone, "card_name": None}
    nameless = {**ability("s2", "activated_ability", hidden, OPP), "card_name": None}
    assert "sourceCard" not in view.game_view(board([nameless]), SEATS, "g")["stack"][0]


def test_an_ability_with_two_candidate_lines_highlights_none() -> None:
    assert view.ability_line("When A.\nWhenever B.", "triggered_ability", "battlefield") == ""
    assert view.ability_line("When you cast this spell, C.\nWhenever B.", "triggered_ability", "battlefield") == "Whenever B."
    assert view.ability_line("Flying\n{T}: Add {G}.", "activated_ability", "battlefield") == "{T}: Add {G}."
    assert view.ability_line("Flying", "activated_ability", "battlefield") == ""


@recorded
def test_recorded_stack_objects_carry_a_card_without_hidden_names() -> None:
    cards = 0
    for _, decisions in walk_records():
        for sd in decisions:
            observation = sd["observation"]
            if not observation["stack"]:
                continue
            seats = view.Seats(sd["acting_seat"], "player-0", "player-1", {})
            gv = view.game_view(observation, seats, "g")
            known = names_in(observation)
            for s in gv["stack"]:
                if "sourceCard" in s:
                    cards += 1
                    assert s["sourceCard"]["identity"]["name"] in known
                assert "Triggered ability of" not in s["text"]
    assert cards >= 100


# -- hidden information ---------------------------------------------------------------------------------------------------


def names_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("card_name", "full_name") and isinstance(item, str):
                found.add(item)
            else:
                found |= names_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= names_in(item)
    return found


def visible_names(gv: dict) -> set[str]:
    names: set[str] = set()
    for zone in gv["zones"]:
        for c in zone["cards"]:
            if c.get("visibility") == "visible":
                names.add(c["identity"]["name"])
    for s in gv["stack"]:
        names.add(s["identity"]["name"])
        if "sourceCard" in s:
            names.add(s["sourceCard"]["identity"]["name"])
    names.discard("")
    return names


@recorded
def test_the_view_names_only_cards_the_seat_was_told_of_in_every_recorded_observation() -> None:
    """Every card name in the view comes from the viewer's own observation; and the opponent's hand shows exactly the
    cards the engine lists as known there, nothing else."""
    shown = 0
    for _, decisions in walk_records():
        for sd in decisions:
            observation = sd["observation"]
            seats = view.Seats(sd["acting_seat"], "player-0", "player-1", {})
            gv = view.game_view(observation, seats, "g")
            assert visible_names(gv) <= names_in(observation), sd["acting_seat"]
            opp_hand = next(z for z in gv["zones"] if z["zone"] == "hand" and z["ownerId"] == "player-1")
            known = sorted(k["card_name"] for k in observation["known"]
                           if k["zone"] == "hand" and k["owner_seat"] != sd["acting_seat"])
            shown_names = sorted(c["identity"]["name"] for c in opp_hand["cards"] if c.get("visibility") == "visible")
            assert shown_names == known[:opp_hand["count"]]
            assert opp_hand["count"] == next(p for p in observation["players"]
                                            if p["seat"] != sd["acting_seat"])["hand_count"]
            shown += len(shown_names)
    assert shown >= 10


def test_known_cards_of_the_opponents_hand_show_face_up_first_and_the_rest_stay_hidden() -> None:
    observation = board(known=[
        {"card_name": "Lightning Bolt", "how": "from_public_zone", "object_id": None, "owner_seat": OPP,
         "position_from_bottom": None, "position_from_top": None, "zone": "hand"},
        {"card_name": "Island", "how": "looked_at", "object_id": "x", "owner_seat": OPP, "position_from_bottom": None,
         "position_from_top": 0, "zone": "library"}])
    hand = next(z for z in view.game_view(observation, SEATS, "g")["zones"]
                if z["zone"] == "hand" and z["ownerId"] == "player-1")
    assert hand["count"] == 3 and len(hand["cards"]) == 3
    assert hand["cards"][0]["identity"]["name"] == "Lightning Bolt" and "Instant" in hand["cards"][0]["types"]
    assert all(c == {"visibility": "hidden", "id": c["id"]} for c in hand["cards"][1:])
    assert len({c["id"] for c in hand["cards"]}) == 3


# -- item 28: monarch and initiative -------------------------------------------------------------------------------------


def test_monarch_and_initiative_are_shown() -> None:
    observation = board()
    observation["players"][0]["designations"] = ["monarch"]
    observation["players"][1]["designations"] = ["initiative", "city_blessing"]
    gv = view.game_view(observation, SEATS, "g")
    assert gv["monarchId"] == "player-0" and gv["initiativeHolderId"] == "player-1"
    assert {p["id"]: p["hasCityBlessing"] for p in gv["players"]} == {"player-0": False, "player-1": True}
    plain = view.game_view(board(), SEATS, "g")
    assert plain["monarchId"] is None and plain["initiativeHolderId"] is None
    observation["players"][0]["designations"] = None  # a flag-off engine sends null
    assert view.game_view(observation, SEATS, "g")["monarchId"] is None


# -- item 29: the turn number ----------------------------------------------------------------------------------------------


def numbered(turn: int, active: str, starter: str | None) -> int:
    return view.turn_number({"turn": turn, "active_seat": active}, starter)


def test_the_turn_number_counts_every_players_turn_from_the_seat_that_started() -> None:
    sequence = [(1, ME), (1, OPP), (2, ME), (2, OPP), (3, ME)]
    assert [numbered(t, a, ME) for t, a in sequence] == [1, 2, 3, 4, 5]
    assert [numbered(t, a, None) for t, a in sequence] == [1, 2, 3, 4, 5]  # p0 starts unless told


@recorded
def test_when_the_first_decision_a_seat_sees_is_the_opponents_turn_the_number_is_still_right() -> None:
    """Games start with p0 (rules.starting_seat) and the engine's turn counter is the round. The first observation a
    seat sees can be p1's turn 1 (nothing was asked of it on p0's), which the old 'first seen' rule took for the
    starting seat and doubled the turn numbers of the whole game."""
    first_seen_p1 = 0
    for path, decisions in walk_records():
        reset = next(r["message"] for r in replay.read_record(path) if r["message"].get("request_type") == "reset")
        assert reset["rules"]["starting_seat"] == ME
        first = decisions[0]["observation"]
        if first["active_seat"] == OPP:
            first_seen_p1 += 1
            assert numbered(first["turn"], OPP, ME) == 2  # p0's turn 1 came first
            assert numbered(first["turn"], OPP, OPP) == 1  # what the old rule gave
        numbers = [numbered(sd["observation"]["turn"], sd["observation"]["active_seat"], ME) for sd in decisions]
        assert numbers == sorted(numbers)
        assert all(b - a <= 2 for a, b in zip(numbers, numbers[1:]))
    assert first_seen_p1 >= 1


def test_the_host_takes_the_starting_seat_from_the_games_rules() -> None:
    hub = Hub(opponent="Basilisk 2")
    hub.game_start({"game_id": "g-1", "seat": OPP, "own_deck": {"name": "Wildfire"}, "opponent_deck": {"name": "Rally"},
                    "rules": {"starting_seat": ME}})
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": lambda self, m: sent.append(m)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    observation = board()
    observation.update(turn=1, active_seat=OPP)  # the first thing the second player sees is its own turn 1
    bridge._push({**hub.state(), "observation": observation})
    gv = [m for m in sent if m.get("state", {}).get("kind") == "state"][-1]["state"]["state"]["gameView"]
    assert gv["turn"] == 2


# -- the cosmetic lines --------------------------------------------------------------------------------------------------------


def test_counters_use_the_clients_spelling() -> None:
    assert [view.counter_key(k) for k in ("p1p1", "m1m1", "lore", "stun", "loyalty", "charge")] == [
        "P1P1", "M1M1", "Lore", "Stun", "Loyalty", "Charge"]
    observation = board()
    observation["players"][0]["battlefield"] = [creature("c", "Saga", ME, counters={"lore": 2, "p1p1": 1, "stun": 0})]
    card = next(c for z in view.game_view(observation, SEATS, "g")["zones"] if z["zone"] == "battlefield"
                for c in z["cards"])
    assert card["counters"] == {"Lore": 2, "P1P1": 1}
