"""The Manabrew prompts: the attack and block declarations, target progress, source cards, option labels and error codes.
Display and human flow only: the engine and the bot never see any of this."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spellbench.human import replay, text
from spellbench.human.manabrew import prompts, view
from spellbench.human.manabrew.host import Bridge
from spellbench.human.server import Hub

from test_human_stops import ME, OPP, decision, new_hub, ref, waiting_priority

SEATS = view.Seats(ME, "player-0", "player-1", {"player-0": "human", "player-1": "Basilisk 2"})
RECORDS = sorted(Path(os.environ.get(
    "SPELLBENCH_HUMAN_RECORDS", "E:/artifacts/chains-20261107-human-interim/engine-records/cold")).glob("game-*/engine.jsonl.gz"))
recorded = pytest.mark.skipif(not RECORDS, reason="the recorded human games are not on this machine")


def creature(oid: str, name: str, seat: str = ME, *, keywords=(), tapped=False, attacking=False, sick=False,
             types=("creature",), subtypes=()) -> dict:
    return {"object_id": oid, "card_name": name, "owner_seat": seat, "controller_seat": seat, "zone": "battlefield",
            "characteristics": {"types": list(types), "subtypes": list(subtypes), "keywords": list(keywords),
                                "power": 2, "toughness": 2, "colors": [], "mana_value": 2, "supertypes": []},
            "permanent": {"tapped": tapped, "attacking": attacking, "summoning_sick": sick, "counters": {}, "damage": 0,
                          "blocking": False, "blocked_attackers": [], "attached_to": None}}


def with_board(request: dict, mine: list[dict], theirs: list[dict]) -> dict:
    players = request["observation"]["players"]
    players[0]["battlefield"], players[1]["battlefield"] = mine, theirs
    return request


def pending_of(request: dict) -> dict:
    return new_hub(real=True)._view(request)


def attack_request(first: str, count: int, mine: list[dict], *, can_decline: bool = True) -> dict:
    attacker = ref(first, "Elf")
    options = [{"candidate_id": 0, "semantic": {"kind": "declare_attack", "attacker": attacker, "defender": None}}] \
        if can_decline else []
    options.append({"candidate_id": 1, "semantic": {"kind": "declare_attack", "attacker": attacker,
                                                    "defender": {"player": OPP}}})
    d = with_board(decision([], phase="declare_attackers"), mine, [])
    d["candidates"] = options
    d["context"] = {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False}
    d["group"] = {"group_id": 11, "substep_index": 0, "substep_count": count}
    return d


# -- item 4: the attackers --------------------------------------------------------------------------------------------


def test_a_defender_is_not_offered_as_an_attacker() -> None:
    mine = [creature("wall", "Wall", keywords=["defender"]), creature("elf-a", "Elf"), creature("elf-b", "Elf")]
    request = attack_request("elf-a", 2, mine)
    data, answer = prompts.build(pending_of(request), request["observation"], SEATS)
    assert data["type"] == "chooseAttackers"
    assert [a["attackerId"] for a in data["attackers"]] == ["elf-a", "elf-b"]
    assert answer({"assignments": [{"attackerId": "elf-b", "targetId": "player-1"}]}) == (
        "plan", {"kind": "attack", "attackers": ["elf-b"]})


def test_a_count_that_does_not_match_asks_creature_by_creature() -> None:
    # the engine asks about two creatures but three could attack by our reading (some effect we cannot see)
    mine = [creature("elf-a", "Elf"), creature("elf-b", "Elf"), creature("elf-c", "Elf")]
    request = attack_request("elf-a", 2, mine)
    data, _ = prompts.build(pending_of(request), request["observation"], SEATS)
    assert data["type"] == "chooseFromSelection"
    assert [o["label"] for o in data["options"]] == ["Elf: no attack", "Elf attacks opponent"]
    # and the creature asked about is not among the ones we would list
    request = attack_request("elf-z", 2, [creature("elf-a", "Elf"), creature("elf-b", "Elf")])
    assert prompts.build(pending_of(request), request["observation"], SEATS)[0]["type"] == "chooseFromSelection"


def test_summoning_sick_and_tapped_creatures_are_left_out_and_haste_is_not_sick() -> None:
    mine = [creature("elf-a", "Elf"), creature("tired", "Elf", tapped=True), creature("new", "Elf", sick=True),
            creature("fast", "Goblin", sick=True, keywords=["haste"])]
    request = attack_request("elf-a", 2, mine)
    data, _ = prompts.build(pending_of(request), request["observation"], SEATS)
    assert [a["attackerId"] for a in data["attackers"]] == ["elf-a", "fast"]


def test_a_forced_attack_is_marked_must_attack() -> None:
    mine = [creature("elf-a", "Elf"), creature("elf-b", "Elf")]
    forced = attack_request("elf-a", 2, mine, can_decline=False)
    data, _ = prompts.build(pending_of(forced), forced["observation"], SEATS)
    assert {a["attackerId"]: a["mustAttack"] for a in data["attackers"]} == {"elf-a": True, "elf-b": False}
    free = attack_request("elf-a", 2, mine)
    data, _ = prompts.build(pending_of(free), free["observation"], SEATS)
    assert not any(a["mustAttack"] for a in data["attackers"])


# -- item 18: the blockers ----------------------------------------------------------------------------------------------


def block_request(attackers: list[dict], blockers: list[dict], offered: dict[str, list[str]]) -> dict:
    """A block declaration at its first substep: the first blocker's candidates (no block, and each attacker offered)."""
    blocker = blockers[0]
    options = [{"candidate_id": 0, "semantic": {"kind": "declare_block", "attacker": None,
                                                "blocker": ref(blocker["object_id"], blocker["card_name"])}}]
    for i, attacker in enumerate(offered[blocker["object_id"]], start=1):
        options.append({"candidate_id": i, "semantic": {"kind": "declare_block", "attacker": ref(attacker, "Attacker", OPP),
                                                       "blocker": ref(blocker["object_id"], blocker["card_name"])}})
    d = with_board(decision([], phase="declare_blockers", active=OPP), blockers, attackers)
    d["candidates"] = options
    d["context"] = {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False}
    d["group"] = {"group_id": 12, "substep_index": 0, "substep_count": len(blockers)}
    return d


def test_flying_attackers_can_only_be_blocked_by_flying_or_reach() -> None:
    attackers = [creature("fly", "Faerie", OPP, keywords=["flying"], attacking=True),
                 creature("walk", "Goblin", OPP, attacking=True)]
    blockers = [creature("g1", "Elf"), creature("f1", "Bird", keywords=["flying"]), creature("r1", "Spider", keywords=["reach"]),
                creature("tapped", "Elf", tapped=True)]
    request = block_request(attackers, blockers, {"g1": ["walk"]})
    data, answer = prompts.build(pending_of(request), request["observation"], SEATS)
    valid = {a["attackerId"]: a["validBlockerIds"] for a in data["attackers"]}
    assert valid == {"fly": ["f1", "r1"], "walk": ["g1", "f1", "r1"]}
    assert data["availableBlockerIds"] == ["g1", "f1", "r1"]
    assert answer({"assignments": [{"blockerId": "r1", "attackerId": "fly"}]}) == (
        "plan", {"kind": "block", "blocks": {"g1": None, "f1": None, "r1": "fly"}})


def test_menace_asks_for_two_and_unblockable_attackers_have_no_blockers() -> None:
    attackers = [creature("men", "Goblin", OPP, keywords=["menace"], attacking=True),
                 creature("sneak", "Rogue", OPP, keywords=["cant_be_blocked"], attacking=True),
                 creature("isle", "Merfolk", OPP, keywords=["islandwalk"], attacking=True)]
    blockers = [creature("g1", "Elf"), creature("g2", "Elf"), creature("i1", "Island", types=("land",), subtypes=["island"])]
    request = block_request(attackers, blockers[:2] + blockers[2:], {"g1": ["men"]})
    data, _ = prompts.build(pending_of(request), request["observation"], SEATS)
    by = {a["attackerId"]: a for a in data["attackers"]}
    assert by["men"]["minBlockers"] == 2 and by["men"]["validBlockerIds"] == ["g1", "g2"]
    assert by["sneak"]["validBlockerIds"] == [] and by["isle"]["validBlockerIds"] == []  # we control an Island
    assert by["men"]["mustBeBlocked"] is False


def bridge_with(hub: Hub) -> tuple[Bridge, list[dict]]:
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": staticmethod(sent.append)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = SEATS
    return bridge, sent


def respond(bridge: Bridge, prompt_id: int, kind: str, output: dict) -> None:
    bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": prompt_id,
                                  "action": {"type": kind, "output": output}})


def envelopes(sent: list[dict], kind: str) -> list[dict]:
    return [m["state"] for m in sent if m.get("state", {}).get("kind") == kind]


def test_a_refused_block_asks_again_under_a_new_prompt_id_with_the_reason() -> None:
    hub = new_hub(real=True)
    bridge, sent = bridge_with(hub)
    attackers = [creature("a1", "Goblin", OPP, attacking=True), creature("a2", "Ogre", OPP, attacking=True)]
    blockers = [creature("g1", "Elf"), creature("g2", "Elf")]
    request = block_request(attackers, blockers, {"g1": ["a1"], "g2": ["a1"]})  # the engine offers a1 only (an effect we do not read)
    thread = waiting_first = waiting_priority(hub, request)
    bridge._push(hub.state())
    first = envelopes(sent, "prompt")[-1]["prompt"]
    seq = first["promptId"]
    assert first["input"]["type"] == "chooseBlockers" and "error" not in first["input"]
    respond(bridge, seq, "chooseBlockers", {"type": "declareBlockers", "assignments": [{"blockerId": "g1", "attackerId": "a2"}]})
    again = envelopes(sent, "prompt")[-1]["prompt"]
    assert again["input"]["type"] == "chooseBlockers" and "not allowed" in again["input"]["error"]
    assert again["promptId"] != seq and again["promptId"] >= 2_000_000
    assert not envelopes(sent, "error")  # the new prompt is the answer, not an "Action rejected" toast
    assert hub.pending["seq"] == seq  # the decision itself is unchanged
    respond(bridge, seq, "chooseBlockers", {"type": "declareBlockers", "assignments": []})  # the old id is stale
    assert envelopes(sent, "error")[-1]["error"]["code"] == "stalePrompt"
    respond(bridge, again["promptId"], "chooseBlockers", {"type": "declareBlockers", "assignments": [{"blockerId": "g1", "attackerId": "a1"}]})
    waiting_first.join(5)
    assert waiting_first.result == [1]  # g1 blocks a1: the candidate that names it


def test_a_second_refusal_falls_back_to_the_one_by_one_choice() -> None:
    hub = new_hub(real=True)
    bridge, sent = bridge_with(hub)
    attackers = [creature("a1", "Goblin", OPP, attacking=True), creature("a2", "Ogre", OPP, attacking=True)]
    blockers = [creature("g1", "Elf")]
    request = block_request(attackers, blockers, {"g1": ["a1"]})
    waiting_priority(hub, request)
    bridge._push(hub.state())
    seq = envelopes(sent, "prompt")[-1]["prompt"]["promptId"]
    bad = {"type": "declareBlockers", "assignments": [{"blockerId": "g1", "attackerId": "a2"}]}
    respond(bridge, seq, "chooseBlockers", bad)
    again = envelopes(sent, "prompt")[-1]["prompt"]["promptId"]
    respond(bridge, again, "chooseBlockers", bad)
    assert envelopes(sent, "error")[-1]["error"]["code"] == "unknownActionId"
    bridge._push(hub.state())
    assert envelopes(sent, "prompt")[-1]["prompt"]["input"]["type"] == "chooseFromSelection"


# -- item 17: targets -------------------------------------------------------------------------------------------------------


def target_pending(source: str, targets: list[dict], *, minimum=1, maximum=1, selected=0, finish=False) -> dict:
    src = ref("o-src", source, OPP, "stack")
    cands = [{"kind": "choose_target", "source": src, "slot": 0, "target": t, "selected_count": selected,
              "minimum": minimum, "maximum": maximum} for t in targets]
    if finish:
        cands.append({"kind": "finish_target_selection", "source": src, "slot": 0, "selected_count": selected})
    return {"seq": 7, "prompt": "Choose a target", "context": {"kind": "choice", "source": src, "rewind": False},
            "group": {}, "screen": "generic",
            "candidates": [{"id": i, "kind": s["kind"], "text": s["kind"], "semantic": s} for i, s in enumerate(cands)]}


MY_ELF = {"object": ref("elf", "Elf", ME)}
THEIR_GOBLIN = {"object": ref("gob", "Goblin", OPP)}


def test_a_bolt_at_either_player_is_hostile_and_a_friendly_effect_is_not() -> None:
    seats = SEATS
    bolt = target_pending("Lightning Bolt", [{"player": ME}, {"player": OPP}, MY_ELF, THEIR_GOBLIN])
    data, _ = prompts.build(bolt, {}, seats)
    assert data["hostile"] is True and data["intent"] == "hostile"
    only_theirs = target_pending("Cast Down", [THEIR_GOBLIN])
    assert prompts.build(only_theirs, {}, seats)[0]["hostile"] is True
    only_mine = target_pending("Map Token", [MY_ELF])
    data, _ = prompts.build(only_mine, {}, seats)
    assert data["hostile"] is False and data["intent"] == "friendly"
    mixed_friendly = target_pending("Toxin Analysis", [MY_ELF, THEIR_GOBLIN])
    assert prompts.build(mixed_friendly, {}, seats)[0]["hostile"] is False  # "gains deathtouch and lifelink"


def test_target_progress_and_bounds_come_from_the_engine() -> None:
    graveyard = [{"object": {**ref(f"c{i}", "Chrysalis", OPP, "graveyard")}} for i in range(3)]
    first = target_pending("Blood Fountain", graveyard, minimum=0, maximum=2, selected=0, finish=True)
    data, answer = prompts.build(first, {}, SEATS)
    assert (data["minTargets"], data["maxTargets"], data["chosenTargets"]) == (0, 2, 0)
    assert answer({"chosen": []}) == ("answer", 3)  # Skip is the engine's "finish"
    second = target_pending("Blood Fountain", graveyard[1:], minimum=0, maximum=2, selected=1, finish=True)
    data, _ = prompts.build(second, {}, SEATS)
    assert (data["minTargets"], data["maxTargets"], data["chosenTargets"]) == (0, 2, 1)  # the client shows Done
    single = target_pending("Lightning Bolt", [{"player": OPP}])
    data, answer = prompts.build(single, {}, SEATS)
    assert (data["minTargets"], data["maxTargets"], data["chosenTargets"]) == (1, 1, 0)
    with pytest.raises(prompts.Rejected) as caught:
        answer({"chosen": []})
    assert caught.value.code == "invalidShape"


def test_a_target_prompt_cannot_be_cancelled_because_the_engine_cannot_rewind() -> None:
    pending = target_pending("Lightning Bolt", [{"player": OPP}, {"player": ME}])
    data, answer = prompts.build(pending, {}, SEATS)
    assert data["cancellable"] is False and pending["context"]["rewind"] is False
    with pytest.raises(prompts.Rejected) as caught:
        answer({"type": "cancel"})
    assert caught.value.code == "cancelNotAllowed"
    with pytest.raises(prompts.Rejected) as caught:
        answer({"chosen": [{"kind": "player", "id": "player-9"}]})
    assert caught.value.code == "unknownActionId"


def test_protocol_error_codes_reach_the_client() -> None:
    hub = new_hub(real=True)
    bridge, sent = bridge_with(hub)
    request = decision([{"kind": "pass"}, {"kind": "cast_spell", "source": ref("o-b", "Lightning Bolt", zone="hand"),
                                              "method": "normal"}])
    waiting_priority(hub, request)
    bridge._push(hub.state())
    seq = envelopes(sent, "prompt")[-1]["prompt"]["promptId"]
    respond(bridge, seq, "chooseAction", {"type": "act", "actionId": "9"})
    assert envelopes(sent, "error")[-1]["error"]["code"] == "unknownActionId"
    respond(bridge, seq, "chooseBoardTargets", {"type": "boardTargets", "chosen": []})
    assert envelopes(sent, "error")[-1]["error"]["code"] == "wrongPromptType"
    respond(bridge, seq, "chooseAction", {"type": "dance"})
    assert envelopes(sent, "error")[-1]["error"]["code"] == "invalidShape"
    respond(bridge, seq, "chooseAction", {"type": "act", "actionId": "1"})
    assert hub.answer == 1  # an answer the prompt offered is taken


# -- item 10: the source card ------------------------------------------------------------------------------------------------


def stack_entry(oid: str, name: str, kind: str = "spell", **fields) -> dict:
    return {**ref(oid, name, ME, "stack"), "stack_kind": kind, "targets": [], "characteristics": {
        "types": ["instant"], "subtypes": [], "supertypes": [], "colors": ["red"], "keywords": [], "mana_value": 1,
        "power": None, "toughness": None}, **fields}


def test_the_source_of_a_choice_is_the_object_on_the_stack() -> None:
    bridge, _ = bridge_with(new_hub(real=True))
    observation = decision([])["observation"]
    observation["stack"] = [stack_entry("o-bolt", "Lightning Bolt")]
    prompt: dict = {}
    bridge._source_of(prompt, ref("o-bolt", "Lightning Bolt", ME, "stack"), observation)
    assert prompt["sourceCard"]["id"] == "o-bolt" and prompt["sourceCard"]["identity"]["name"] == "Lightning Bolt"
    assert "sourceAbilityText" not in prompt


def test_the_source_of_an_ability_is_its_card_and_the_line_it_runs() -> None:
    bridge, _ = bridge_with(new_hub(real=True))
    observation = decision([])["observation"]
    # a trigger whose source field is null (the card has left the board): the card is built from the entry's own name
    trigger = stack_entry("o-trig", "Ninja of the Deep Hours", "triggered_ability", source=None)
    observation["stack"] = [trigger]
    prompt: dict = {}
    bridge._source_of(prompt, ref("o-trig", "Ninja of the Deep Hours", ME, "stack"), observation)
    assert prompt["sourceCard"]["identity"]["name"] == "Ninja of the Deep Hours"
    assert prompt["sourceAbilityText"].startswith("Whenever this creature deals combat damage to a player")
    # a card on the battlefield is found as before
    observation["players"][0]["battlefield"] = [creature("elf", "Elf")]
    prompt = {}
    bridge._source_of(prompt, ref("elf", "Elf", ME), observation)
    assert prompt["sourceCard"]["id"] == "elf"
    prompt = {}
    bridge._source_of(prompt, ref("nowhere", "Nothing", ME, "stack"), observation)
    assert prompt == {}


@recorded
def test_every_recorded_choice_names_a_source_card_that_is_the_stack_object() -> None:
    named = built = 0
    for path in RECORDS:
        for d in replay.decisions(replay.read_record(path)):
            source = (d.get("context") or {}).get("source")
            if not (isinstance(source, dict) and source.get("object_id")):
                continue
            named += 1
            seats = view.Seats(d["acting_seat"], "player-0", "player-1", {})
            bridge, _ = bridge_with(new_hub(real=True))
            bridge.seats = seats
            prompt: dict = {}
            bridge._source_of(prompt, source, d["observation"])
            entry = next(e for e in d["observation"]["stack"] if e["object_id"] == source["object_id"])
            # a spell is its own card; an ability shows the card it came from (the entry itself when that is not told)
            expected = entry["object_id"] if entry["stack_kind"] == "spell" else (
                (entry.get("source") or {}).get("object_id") or entry["object_id"])
            assert prompt["sourceCard"]["id"] == expected
            assert prompt["sourceCard"]["identity"]["name"] == source["card_name"]
            built += 1
    assert named >= 80 and built == named  # before: view.find_card skipped the stack, so none was sent


@recorded
def test_every_recorded_attack_and_block_declaration_is_what_the_engine_asks() -> None:
    attacks = blocks = 0
    for path in RECORDS:
        groups: dict = {}
        for d in replay.decisions(replay.read_record(path)):
            hub = new_hub(real=True)
            hub.game = {"seat": d["acting_seat"]}
            seats = view.Seats(d["acting_seat"], "player-0", "player-1", {})
            pending = hub._view(d)
            kinds = {c["kind"] for c in pending["candidates"]}
            if kinds == {"declare_attack"} and pending["screen"] == "attack":
                data, _ = prompts.build(pending, d["observation"], seats)
                assert data["type"] == "chooseAttackers"
                assert len(data["attackers"]) == (pending["group"].get("substep_count") or 1)
                attacks += 1
            if kinds == {"declare_block"}:
                groups.setdefault((pending["group"].get("group_id"), d["observation"].get("turn")), []).append((d, pending, seats))
        for items in groups.values():
            d0, pending0, seats0 = items[0]
            offered: dict = {}
            for _, pending, _ in items:
                for c in pending["candidates"]:
                    s = c["semantic"]
                    if s.get("attacker"):
                        offered.setdefault(s["blocker"]["object_id"], set()).add(s["attacker"]["object_id"])
            data, _ = prompts.build(pending0, d0["observation"], seats0)
            derived: dict = {}
            for e in data["attackers"]:
                for b in e["validBlockerIds"]:
                    derived.setdefault(b, set()).add(e["attackerId"])
            asked = {p["candidates"][0]["semantic"]["blocker"]["object_id"] for _, p, _ in items}
            assert {b: derived.get(b, set()) for b in asked} == {b: offered.get(b, set()) for b in asked}
            blocks += 1
    assert attacks >= 20 and blocks >= 5


# -- items 16 and 25: the labels ----------------------------------------------------------------------------------------------


def order_pending(count: int, position: int, purpose: str = "triggers") -> dict:
    item = {"trigger": {"source": None, "source_name": "Monastery Swiftspear", "label": None}}
    semantic = {"kind": "order_pick", "source": None, "purpose": purpose, "item": item, "position": position, "count": count}
    return {"seq": 3, "prompt": "", "context": {"kind": "choice"}, "group": {"substep_index": position, "substep_count": count - 1},
            "candidates": [{"candidate_decision": None, "candidate_id": 0, "semantic": semantic}]}


def test_trigger_order_is_labelled_by_when_the_trigger_resolves() -> None:
    # position 0 is put on the stack first (mtg-kernel Action::OrderTriggers), so it resolves last
    assert text.candidate(order_pending(2, 0)["candidates"][0]["semantic"], ME) == "Monastery Swiftspear: resolves last"
    assert text.candidate(order_pending(3, 0)["candidates"][0]["semantic"], ME) == "Monastery Swiftspear: resolves last"
    assert text.candidate(order_pending(3, 1)["candidates"][0]["semantic"], ME) == "Monastery Swiftspear: resolves second"
    assert text.candidate(order_pending(3, 2)["candidates"][0]["semantic"], ME) == "Monastery Swiftspear: resolves first"
    assert text.prompt(order_pending(3, 1), ME) == "Order your triggers: choose the one that resolves second (2 of 2)"
    # an ordering of cards (a scry's put-back) keeps its position wording
    other = order_pending(2, 0, "arrangement")["candidates"][0]["semantic"]
    other["item"] = {"object": ref("c1", "Island", ME, "library")}
    assert text.candidate(other, ME) == "Island at position 1 of 2"


def effect_decision(source: str, count: int) -> dict:
    src = ref("o-src", source, ME, "stack")
    return {"context": {"kind": "choice", "source": src, "purpose": "effect_option"}, "observation": {},
            "candidates": [{"candidate_id": i, "semantic": {"kind": "choose_option", "source": src, "purpose": "effect_option",
                                                            "option_index": i, "option_count": count, "option_label": None}}
                           for i in range(count)]}


def test_known_effect_options_are_named() -> None:
    line, labels = text.effect_options(effect_decision("Winding Way", 2), ME)
    assert labels == {0: "Creature", 1: "Land"} and line.startswith("Winding Way: choose a card type")
    assert text.effect_options(effect_decision("Ninja of the Deep Hours", 2), ME)[1] == {0: "Do not draw", 1: "Draw a card"}
    # an option count the table does not know, and a card it does not list, keep the position wording
    assert text.effect_options(effect_decision("Winding Way", 3), ME)[1][2] == "Winding Way: effect 3 of 3"
    assert text.effect_options(effect_decision("Mystery", 2), ME)[1][0] == "Mystery: effect 1 of 2"


def test_optional_costs_say_what_they_pay() -> None:
    def optional(source: str, cost: str, pay: bool) -> str:
        return text.candidate({"kind": "optional_cost", "source": ref("o", source, ME, "stack"), "cost": cost, "pay": pay}, ME)
    assert optional("Nihil Spellbomb", "other", True) == "Pay {B}"
    assert optional("Nihil Spellbomb", "other", False) == "Do not pay {B}"
    assert optional("Highway Robbery", "additional", True) == "Pay the additional cost (discard a card or sacrifice a land)"
    assert optional("Goblin Bushwhacker", "kicker", True) == "Pay the kicker cost ({R})"
    assert optional("Chain Lightning", "copy", True) == "Pay {R}{R} to copy the spell"
    assert optional("Force Spike", "unless_payment", True) == "Pay {1}"
    assert optional("Unknown Card", "other", True) == "Pay the other cost of Unknown Card"
    assert text.candidate({"kind": "choose_cost_option", "choice": "sacrifice_land"}, ME) == "Sacrifice a land"
    assert text.candidate({"kind": "choose_cost_option", "choice": "discard"}, ME) == "Discard a card"


def test_activate_candidates_carry_the_rules_line_and_mana_sources_their_cost() -> None:
    def activation(name: str, zone: str, index: int = 0) -> dict:
        return {"kind": "activate_ability", "source": ref("o", name, ME, zone), "ability_index": index}
    assert text.ability_rules(activation("Krark-Clan Shaman", "battlefield")) == (
        "Sacrifice an artifact: This creature deals 1 damage to each creature without flying.")
    # a card with a mana ability and a trigger besides its one activated ability
    assert text.ability_rules(activation("Lembas", "battlefield")).startswith("{2}, {T}, Sacrifice this artifact")
    assert text.ability_rules(activation("Twisted Landscape", "battlefield")).startswith("{T}, Sacrifice this land: Search")
    assert text.ability_rules(activation("Twisted Landscape", "hand", 1)).startswith("Cycling {B}{R}{G}")
    assert text.ability_rules(activation("Ninja of the Deep Hours", "hand", 1)).startswith("Ninjutsu {1}{U}")
    assert text.ability_rules(activation("Unknown Card", "battlefield")) == ""
    pending = {"seq": 1, "prompt": "", "context": {"kind": "priority"}, "group": {}, "screen": "generic", "candidates": [
        {"id": 0, "kind": "pass", "text": "Pass", "semantic": {"kind": "pass"}},
        {"id": 1, "kind": "activate_ability", "text": "Activate Lembas (yours)", "semantic": activation("Lembas", "battlefield")}]}
    action = prompts.build(pending, {}, SEATS)[0]["actions"][0]
    assert action["description"].startswith("{2}, {T}, Sacrifice this artifact: You gain 3 life.")
    # two creatures sacrificed to the same mana source read differently
    def paid(creature_name: str) -> str:
        return text.candidate({"kind": "activate_mana_ability", "source": ref("o-s", "Saruli Caretaker"), "ability_index": 0,
                               "mana_choice": "G", "cost_target": {"object": ref(creature_name, creature_name)}}, ME)
    assert paid("Elf") != paid("Goblin") and "Elf" in paid("Elf")
