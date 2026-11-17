"""The person's pass controls on the Manabrew path: the pass-until the client sends (GO TO, END TURN, NEXT TURN, the
phase-stop dialog) is held by the session as the engine's own agent holds it, windows are passed for the person only while
it is ahead (and the stack is empty, and no combat is under way unless the hold goes through combat), any action of theirs
clears it, a stack is always a stop, "end turn" on a stack stops at anything new, a position they already passed at is not
asked again, and every stack change is drawn. Display and human flow only: the engine and the bot never see any of this."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from spellbench.human.manabrew import fake_client, prompts, view
from spellbench.human.manabrew.host import Bridge
from spellbench.human.server import STEP_ORDER, Conceded, Hub, active_combat, position_key, real_actions

from test_human_manabrew import directive
from test_human_stops import (BOLT, LAND, MANA, MY_SPELL, NINJA, OPP, PASS, ME, SPELL_ON_STACK, decision, new_hub,
                              recorded, recorded_games, ref, waiting_priority)

THROUGH = True
SEATS = view.Seats(ME, "player-0", "player-1", {"player-0": "human", "player-1": "Basilisk 2"})
PLAYER = {ME: "player-0", OPP: "player-1"}
CLIENT_STEP = {ours: client for client, ours in prompts.STEP_OF.items() if client != "combatFirstStrikeDamage"}


def at(candidates: list[dict], *, phase: str = "precombat_main", active: str = ME, turn: int = 3, stack: list | None = None,
       attacking: bool = False) -> dict:
    d = decision(candidates, phase=phase, active=active, stack=stack)
    d["observation"]["turn"] = turn
    if attacking:
        attacker = {"object_id": "o-a", "card_name": "Goblin", "controller_seat": active, "owner_seat": active,
                    "zone": "battlefield", "permanent": {"attacking": True, "tapped": True}}
        d["observation"]["players"][0 if active == ME else 1]["battlefield"] = [attacker]
    return d


def attack_step(index: int, count: int, *, can_decline: bool = True, turn: int = 3, creature: str = "o-c0") -> dict:
    attacker = ref(creature, "Elf")
    options = [{"candidate_id": 0, "semantic": {"kind": "declare_attack", "attacker": attacker, "defender": None}}] if can_decline else []
    options.append({"candidate_id": 1, "semantic": {"kind": "declare_attack", "attacker": attacker, "defender": {"player": OPP}}})
    d = at([], phase="declare_attackers", turn=turn)
    d["candidates"] = options
    d["context"] = {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False}
    d["group"] = {"group_id": 11, "substep_index": index, "substep_count": count}
    return d


def until(player: str, step: str, *, through: bool = False) -> dict:
    """The client's PassUntil for a seat and one of our step names."""
    return {"playerId": PLAYER[player], "phase": CLIENT_STEP[step], "throughCombat": through}


def pass_priority(hub: Hub, request: dict, target: dict | None = None, *, exhaust: bool = False) -> None:
    """The person is asked at ``request`` and passes with the client's ``until`` (a ``until`` dict above) and exhaustStack."""
    thread = waiting_priority(hub, request)
    seq = hub.pending["seq"]
    data, answer = prompts.build(hub.pending, request["observation"], SEATS)
    output = {"type": "pass", "exhaustStack": exhaust, **({"until": target} if target else {})}
    how, value = answer(output)
    if how == "answer":
        assert hub.answer_with(seq, value) is None
    else:
        assert how == "pass" and hub.pass_with(seq, value["until"], exhaust_stack=value["exhaust_stack"]) is None
    thread.join(5)
    assert thread.result == [0]


def how(hub: Hub, request: dict) -> str:
    with hub.cond:
        answered, chosen = hub._begin(request, {})
        hub.pending = None  # (a decision left pending is not answered: only how it would be is wanted)
    return answered if chosen is not None else "human"


# -- the client's pass-until reaches the hub ---------------------------------------------------------------------------


def pending_priority(candidates: list[dict]) -> dict:
    return {"seq": 5, "prompt": "Your priority", "context": {"kind": "priority"}, "group": {}, "screen": "generic",
            "candidates": [{"id": i, "kind": s["kind"], "text": s["kind"], "semantic": s} for i, s in enumerate(candidates)]}


def test_every_pass_button_sends_its_target_and_the_host_keeps_it() -> None:
    data, answer = prompts.build(pending_priority([PASS, BOLT]), {}, SEATS)
    go_to_attackers = {"playerId": "player-0", "phase": "combatDeclareAttackers", "throughCombat": False}
    assert answer({"type": "pass", "until": go_to_attackers, "exhaustStack": False}) == (
        "pass", {"until": {"seat": ME, "step": "declare_attackers", "through_combat": False}, "exhaust_stack": False})
    end_turn = {"playerId": "player-1", "phase": "endOfTurn", "throughCombat": True}
    assert answer({"type": "pass", "until": end_turn, "exhaustStack": False}) == (
        "pass", {"until": {"seat": OPP, "step": "end_step", "through_combat": True}, "exhaust_stack": False})
    assert answer({"type": "pass", "exhaustStack": True}) == ("pass", {"until": None, "exhaust_stack": True})
    assert answer({"type": "pass", "exhaustStack": False}) == ("answer", 0)  # a single pass names nothing
    for step in ("upkeep", "draw", "main1", "combatBegin", "combatDeclareAttackers", "combatDeclareBlockers",
                 "combatFirstStrikeDamage", "combatDamage", "combatEnd", "main2", "endOfTurn", "cleanup"):
        assert prompts.hold_target({"playerId": "player-1", "phase": step, "throughCombat": False}, SEATS)["step"] in STEP_ORDER
    # a target the session cannot read is a plain pass: it asks at more windows, never at fewer
    assert prompts.hold_target({"playerId": "player-9", "phase": "main1"}, SEATS) is None
    assert prompts.hold_target({"playerId": "player-0", "phase": "nonsense"}, SEATS) is None
    assert prompts.hold_target("main1", SEATS) is None


def test_the_hosts_pass_with_a_target_reaches_the_hub_as_a_hold() -> None:
    hub = new_hub(real=True)
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": staticmethod(sent.append)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = SEATS
    request = at([PASS, BOLT], phase="precombat_main")
    thread = waiting_priority(hub, request)
    bridge._push(hub.state())
    bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": hub.pending["seq"], "action": {
        "type": "chooseAction", "output": {"type": "pass", "until": until(OPP, "end_step", through=True),
                                           "exhaustStack": False}}})
    thread.join(5)
    assert thread.result == [0]
    # the engine has no window in the end step: the hold is aimed at the nearest one (the second main phase)
    assert hub.hold["seat"] == OPP and hub.hold["step"] == "postcombat_main" and hub.hold["through_combat"] is True
    assert not [m for m in sent if m.get("state", {}).get("kind") == "error"]


# -- (a) the hold --------------------------------------------------------------------------------------------------------


def test_end_turn_passes_the_rest_of_my_turn_and_the_opponents_but_stops_for_a_spell_or_a_combat() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step", through=True))
    assert how(hub, at([PASS, BOLT], phase="postcombat_main")) == "auto_pass"                 # my own main 2
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, NINJA], phase="declare_blockers", active=OPP, turn=4)) == "auto_pass"
    # through combat: even with attackers declared the windows are passed
    assert how(hub, at([PASS, NINJA], phase="declare_blockers", active=OPP, turn=4, attacking=True)) == "auto_pass"
    # a spell on the stack is a stop, whoever's it is
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[MY_SPELL])) == "human"
    # the opponent's end step is never a window here: my next turn finds the hold gone
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=ME, turn=5)) == "human"
    assert hub.hold is None


def test_go_to_attackers_stops_at_the_attackers_step_and_then_the_hold_is_gone() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT]), until(ME, "declare_attackers"))
    assert hub.hold is not None
    assert how(hub, at([PASS, BOLT], phase="beginning_of_combat")) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="declare_attackers")) == "human"
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="declare_blockers")) == "human"  # no hold: every window with an action


def test_a_plain_pass_runs_to_the_next_stop_but_not_through_a_combat_that_is_under_way() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="declare_attackers", attacking=True), until(ME, "postcombat_main"))
    assert how(hub, at([PASS, NINJA], phase="declare_blockers", attacking=True)) == "human"   # active combat
    assert how(hub, at([PASS, NINJA], phase="combat_damage", attacking=True)) == "human"
    assert how(hub, at([PASS, NINJA], phase="end_of_combat")) == "auto_pass"                  # no attackers any more
    assert how(hub, at([PASS, BOLT], phase="postcombat_main")) == "human"                     # the stop
    assert hub.hold is None


def test_active_combat_is_attackers_declared_in_a_combat_step() -> None:
    assert active_combat(at([PASS, BOLT], phase="declare_blockers", attacking=True)["observation"])
    assert not active_combat(at([PASS, BOLT], phase="precombat_main", attacking=True)["observation"])
    assert not active_combat(at([PASS, BOLT], phase="declare_blockers")["observation"])


@pytest.mark.parametrize("act", ["cast", "land"])
def test_any_action_of_the_persons_clears_the_hold(act: str) -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT, LAND]), until(OPP, "end_step", through=True))
    assert hub.hold is not None
    assert how(hub, at([PASS, BOLT, LAND], phase="postcombat_main")) == "auto_pass"
    thread = waiting_priority(hub, at([PASS, BOLT, LAND], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK]))
    assert hub.answer_with(hub.pending["seq"], 1 if act == "cast" else 2) is None  # a spell, or a land
    thread.join(5)
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="declare_blockers", active=OPP, turn=4)) == "human"


def test_a_pass_replaces_the_hold_and_a_pass_with_no_target_clears_it() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT]), until(OPP, "end_step", through=True))
    pass_priority(hub, at([PASS, BOLT, LAND], phase="declare_attackers", stack=[MY_SPELL]))  # no target: no hold
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="postcombat_main")) == "human"


def test_a_target_of_my_own_turn_that_is_already_behind_waits_for_my_next_turn() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main"), until(ME, "precombat_main"))  # main 1 again, a turn on
    assert how(hub, at([PASS, BOLT], phase="end_of_combat", turn=3)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=ME, turn=5)) == "human"


def test_the_opponents_turn_target_skips_to_a_later_step_of_that_turn() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main"), until(OPP, "declare_blockers"))
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="declare_attackers", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="declare_blockers", active=OPP, turn=4)) == "human"
    assert hub.hold is None


def test_a_target_in_the_turn_it_was_set_in_is_gone_with_that_turn() -> None:
    """The recorded Wildfire mirror found this: Space at the opponent's main 2 aims at its end step, which the engine
    never offers a window in; the hold must not carry into my turn."""
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4), until(OPP, "end_step"))
    assert hub.hold is not None
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=ME, turn=5)) == "human"
    assert hub.hold is None


def test_a_target_in_a_turn_that_had_no_window_is_lost() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", active=ME, turn=3), until(OPP, "precombat_main"))
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=ME, turn=5)) == "human"  # no window of turn 4 came
    assert hub.hold is None


@pytest.mark.parametrize("through", [False, True])
def test_a_stop_at_the_opponents_end_step_is_taken_in_their_second_main_phase(through: bool) -> None:
    """The owner's report: Space (or END TURN) aims at the opponent's end step, where he wanted to cast Brainstorm. The
    engine has no priority there, so the session used to pass him through every window up to it and he never held
    priority again until his own turn. Now the stop is the last window the turn has."""
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step", through=through))
    assert hub.hold["step"] == "postcombat_main"
    assert how(hub, at([PASS, BOLT], phase="postcombat_main")) == "auto_pass"                   # my own main 2
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "auto_pass"  # still ahead
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"     # the stop
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=ME, turn=5)) == "human"


def test_the_moved_stop_still_passes_a_window_with_nothing_to_do() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step", through=True))
    assert how(hub, at([PASS, MANA], phase="postcombat_main", active=OPP, turn=4)) == "auto_pass"


def test_a_stop_before_the_first_window_or_between_windows_is_taken_at_the_next_one() -> None:
    from spellbench.human.server import reachable_step

    assert [reachable_step(s) for s in STEP_ORDER] == [
        "precombat_main", "precombat_main", "precombat_main", "precombat_main", "declare_attackers", "declare_attackers",
        "declare_blockers", "postcombat_main", "postcombat_main", "postcombat_main", "postcombat_main", "postcombat_main"]
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main"), until(OPP, "upkeep"))
    assert hub.hold["step"] == "precombat_main"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "human"  # their first window
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4), until(OPP, "end_of_combat"))
    assert how(hub, at([PASS, BOLT], phase="declare_attackers", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"


def test_a_stop_that_cannot_be_taken_this_turn_is_not_carried_into_the_next_and_the_log_says_why() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4), until(OPP, "end_step"))
    assert any("no later priority this turn" in line["text"] and "opponent's end step" in line["text"] for line in hub.log)
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=ME, turn=5)) == "human"
    assert hub.hold is None


def test_the_log_says_once_per_turn_where_the_stop_is_taken() -> None:
    hub = new_hub(real=True)
    for _ in range(2):
        pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step"))
        hub.hold = None
        hub.passed_at = None  # (the same position is not asked twice; this is the person passing again)
    lines = [line["text"] for line in hub.log if "gives no priority" in line["text"]]
    assert lines == ["The engine gives no priority in the opponent's end step, so your stop there is taken in the "
                     "opponent's second main phase, the nearest priority there is."]
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main", turn=5), until(OPP, "end_step"))
    assert len([line for line in hub.log if "gives no priority" in line["text"]]) == 2  # a new turn says it again


def test_the_play_page_never_holds() -> None:
    hub = new_hub(real=False)
    thread = waiting_priority(hub, at([PASS, BOLT], phase="precombat_main"))
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    assert hub.hold is None


# -- (b) the attackers declaration ----------------------------------------------------------------------------------------


def test_a_hold_that_is_ahead_answers_the_attack_with_no_attackers() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT]), until(OPP, "end_step", through=True))
    first, second = attack_step(0, 2, creature="o-c0"), attack_step(1, 2, creature="o-c1")
    assert how(hub, first) == "auto_pass"
    assert hub._automatic(first)[1] == 0  # the "no attack" candidate
    assert hub._automatic(second) == ("auto_pass", 0)
    assert hub.pending is None


def test_without_a_hold_or_when_it_is_reached_the_person_is_asked_to_attack() -> None:
    hub = new_hub(real=True)
    assert how(hub, attack_step(0, 2)) == "human"
    pass_priority(hub, at([PASS, BOLT]), until(ME, "declare_attackers"))
    assert how(hub, attack_step(0, 2)) == "human"  # the stop he asked for
    assert hub.hold is None


def test_a_forced_attack_is_asked_even_under_a_hold() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT]), until(OPP, "end_step", through=True))
    # a creature that must attack (its only candidate is an attack) makes the declaration the person's to answer
    assert how(hub, attack_step(0, 2, can_decline=False)) == "single"
    assert how(hub, attack_step(1, 2)) == "human"
    # two ways to attack and none to stay home: asked too
    hub.forced_attack_group = None
    forced = attack_step(0, 2, can_decline=False, turn=5)
    forced["observation"]["active_seat"] = ME
    forced["candidates"].append({"candidate_id": 2, "semantic": {**forced["candidates"][0]["semantic"], "defender": {"player": ME}}})
    pass_priority(hub, at([PASS, BOLT], turn=5), until(OPP, "end_step", through=True))
    assert how(hub, forced) == "human"


def test_the_play_page_still_asks_for_attackers() -> None:
    hub = new_hub(real=False)
    assert how(hub, attack_step(0, 2)) == "human"


def test_the_decision_log_says_who_answered(tmp_path: Path) -> None:
    hub = Hub(log_dir=tmp_path, real_action_stops=True)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    pass_priority(hub, at([PASS, BOLT]), until(OPP, "end_step", through=True))
    assert hub.choose({"decision": attack_step(0, 1)}) == 0
    assert hub.choose({"decision": at([PASS, BOLT], phase="postcombat_main")}) == 0
    thread = waiting_priority(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK]))
    hub.answer_with(hub.pending["seq"], 1)
    thread.join(5)
    rows = [json.loads(line) for line in (tmp_path / "g-1.p0.jsonl").read_text().splitlines()]
    assert [(r["how"], r["phase_step"]) for r in rows if r["kind"] == "decision"] == [
        ("human", "precombat_main"), ("auto_pass", "declare_attackers"), ("auto_pass", "postcombat_main"),
        ("human", "precombat_main")]


# -- (c) a stack is always a stop ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stack", [[SPELL_ON_STACK], [MY_SPELL], [MY_SPELL, SPELL_ON_STACK], [SPELL_ON_STACK, MY_SPELL]])
@pytest.mark.parametrize("target", [None, until(OPP, "end_step", through=True), until(ME, "postcombat_main")])
@pytest.mark.parametrize("phase", ["precombat_main", "declare_attackers", "declare_blockers", "postcombat_main"])
def test_any_stack_is_a_stop_under_any_hold_when_there_is_something_to_do(phase: str, target, stack: list) -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main", turn=2), target)
    assert how(hub, at([PASS, BOLT], phase=phase, stack=stack)) == "human"
    assert how(hub, at([PASS, NINJA], phase=phase, active=OPP, turn=4, stack=stack)) == "human"
    assert how(hub, at([PASS, MANA], phase=phase, stack=stack)) == "auto_pass"  # nothing but pass and mana: passed


# -- (d) end turn on a stack -------------------------------------------------------------------------------------------------


def test_exhaust_stack_passes_the_stack_it_was_pressed_on_and_stops_at_anything_new() -> None:
    hub = new_hub(real=True)
    base = at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])
    pass_priority(hub, base, exhaust=True)
    assert hub.exhaust_stack
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "auto_pass"
    # the opponent adds a spell on top: a new object, so the person is asked
    added = {**ref("o-new", "Lava Dart", OPP, "stack"), "stack_kind": "spell", "targets": []}
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK, added])) == "human"
    assert not hub.exhaust_stack


def test_exhaust_stack_stops_when_the_object_was_replaced_by_a_new_one() -> None:
    """The reviewer's case: the token on the stack resolved and the opponent's Lava Dart took its place."""
    hub = new_hub(real=True)
    token = {**ref("o-tok", "Blood Token", OPP, "stack"), "stack_kind": "activated_ability", "targets": []}
    dart = {**ref("o-dart", "Lava Dart", OPP, "stack"), "stack_kind": "spell", "targets": []}
    pass_priority(hub, at([PASS, BOLT], active=OPP, turn=4, stack=[token]), exhaust=True)
    assert how(hub, at([PASS, BOLT], active=OPP, turn=4, stack=[dart])) == "human"


def test_exhaust_stack_with_nothing_to_do_at_the_new_object_ends_the_pass_through() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], active=OPP, turn=4, stack=[SPELL_ON_STACK]), exhaust=True)
    added = {**ref("o-new", "Lava Dart", OPP, "stack"), "stack_kind": "spell", "targets": []}
    assert how(hub, at([PASS, MANA], active=OPP, turn=4, stack=[SPELL_ON_STACK, added])) == "auto_pass"
    assert not hub.exhaust_stack
    assert how(hub, at([PASS, BOLT, LAND], active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"  # no longer passing through


def test_exhaust_stack_ends_with_the_stack() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, BOLT], active=OPP, turn=4, stack=[SPELL_ON_STACK]), exhaust=True)
    thread = waiting_priority(hub, at([PASS, BOLT], active=OPP, turn=4))
    assert not hub.exhaust_stack
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    assert how(hub, at([PASS, BOLT, LAND], active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"


def test_pass_turn_with_a_stack_is_the_same_exhaust() -> None:
    hub = new_hub(real=True)
    thread = waiting_priority(hub, at([PASS, BOLT], active=OPP, turn=4, stack=[SPELL_ON_STACK]))
    assert hub.pass_turn(hub.pending["seq"], exhaust_stack=True) is None
    thread.join(5)
    assert hub.exhaust_stack and hub.exhaust_ids == {"o-s"}


# -- (e) a position already passed at ------------------------------------------------------------------------------------------


def test_a_position_the_person_passed_at_is_not_asked_again_but_any_change_is() -> None:
    hub = new_hub(real=True)
    here = at([PASS, MANA, NINJA], phase="declare_blockers", active=OPP, turn=4, attacking=True)
    pass_priority(hub, here)
    assert how(hub, at([PASS, MANA, NINJA], phase="declare_blockers", active=OPP, turn=4, attacking=True)) == "auto_pass"
    # a new legal action, a new stack object, a new combat state, a changed board: all asked
    assert how(hub, at([PASS, MANA, NINJA, BOLT], phase="declare_blockers", active=OPP, turn=4, attacking=True)) == "human"
    assert how(hub, at([PASS, MANA, NINJA], phase="declare_blockers", active=OPP, turn=4, attacking=True,
                       stack=[SPELL_ON_STACK])) == "human"
    assert how(hub, at([PASS, MANA, NINJA], phase="declare_blockers", active=OPP, turn=4)) == "human"
    moved = at([PASS, MANA, NINJA], phase="declare_blockers", active=OPP, turn=4, attacking=True)
    moved["observation"]["players"][0]["life"] = 17
    assert how(hub, moved) == "human"
    pooled = at([PASS, MANA, NINJA], phase="declare_blockers", active=OPP, turn=4, attacking=True)
    pooled["observation"]["players"][0]["mana_pool"] = {"U": 1}
    assert how(hub, pooled) == "human"


def test_a_position_is_remembered_within_its_step_only() -> None:
    hub = new_hub(real=True)
    pass_priority(hub, at([PASS, NINJA], phase="declare_blockers", active=OPP, turn=4))
    assert how(hub, at([PASS, NINJA], phase="declare_blockers", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, NINJA], phase="postcombat_main", active=OPP, turn=4)) == "human"   # another step
    assert how(hub, at([PASS, NINJA], phase="declare_blockers", active=ME, turn=5)) == "human"   # another turn


def test_a_position_the_person_acted_at_is_asked_again() -> None:
    hub = new_hub(real=True)
    thread = waiting_priority(hub, at([PASS, BOLT, LAND]))
    hub.answer_with(hub.pending["seq"], 2)  # played a land: not a pass
    thread.join(5)
    assert how(hub, at([PASS, BOLT, LAND])) == "human"


def test_the_position_key_ignores_what_changes_without_a_game_event() -> None:
    a, b = at([PASS, BOLT]), at([PASS, BOLT])
    b["observation"]["passed_seats"] = ["p1"]
    b["observation"]["priority_seat"] = OPP
    assert position_key(a) == position_key(b)
    b["observation"]["players"][1]["life"] = 3
    assert position_key(a) != position_key(b)


# -- (f) every stack change is drawn --------------------------------------------------------------------------------------------


def opponents_stack(*names: str) -> list[dict]:
    return [{**ref(f"o-{n}", n, OPP, "stack"), "stack_kind": "spell", "targets": []} for n in names]


def test_rapid_passes_with_different_stacks_are_all_drawn_in_order() -> None:
    hub = new_hub(real=True)
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    bridge.FRAME_GAP_S = 0
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": staticmethod(sent.append)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    stacks = [opponents_stack("Shock"), opponents_stack("Shock", "Counterspell"), [], opponents_stack("Fireblast")]
    for stack in stacks:  # the session passes each at once: nothing for the person to do but pass and tap mana
        assert hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=4, stack=stack)}) == 0
    bridge._push(hub.wait_state(-1, timeout=0.1, frames_from=0))
    views = [m["state"]["state"]["gameView"] for m in sent if m.get("state", {}).get("kind") == "state"]
    assert [[entry["identity"]["name"] for entry in gv["stack"]] for gv in views] == [
        ["Shock"], ["Counterspell", "Shock"], [], ["Fireblast"]]
    assert bridge.sent_frames == hub.frames_total == 4
    # nothing is drawn twice, and later states carry on from there
    sent.clear()
    bridge._push(hub.wait_state(-1, timeout=0.1, frames_from=bridge.sent_frames))
    assert not [m for m in sent if m.get("state", {}).get("kind") == "state"]


def paced_bridge(hub: Hub, gap: float = 0.0) -> tuple[Bridge, list[dict]]:
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    bridge.FRAME_GAP_S = gap
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": staticmethod(sent.append)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    return bridge, sent


def drawn_stacks(sent: list[dict]) -> list[list[str]]:
    views = [m["state"]["state"]["gameView"] for m in sent if m.get("state", {}).get("kind") == "state"]
    return [[entry["identity"]["name"] for entry in gv["stack"]] for gv in views]


def pump_once(bridge: Bridge) -> None:
    """What the pump does with the hub's newest state, with the bridge's own cursor."""
    bridge._push(bridge.hub.wait_state(-1, timeout=0.1, frames_from=bridge.sent_frames, frames_game=bridge.sent_frames_game,
                                       positions_from=bridge.sent_positions if bridge.pace > 0 else None))


def test_the_stack_changes_of_a_second_game_are_drawn_from_its_first() -> None:
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    for stack in (opponents_stack("Shock"), [], opponents_stack("Fireblast"), []):
        hub.choose({"decision": at([PASS, MANA], active=OPP, turn=4, stack=stack)})
    pump_once(bridge)
    assert bridge.sent_frames == hub.frames_total == 4  # the cursor of game 1 is above anything game 2 has yet
    hub.game_end({"game_id": "g-1", "terminal": {"winner": ME}})
    pump_once(bridge)  # the end of game 1: the table is between games
    assert bridge.order is None
    sent.clear()
    bridge.order, bridge.game_id = ["human", "Basilisk 2"], "g-2"
    hub.game_start({"game_id": "g-2", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    for stack in (opponents_stack("Lava Dart"), opponents_stack("Lava Dart", "Counterspell"), []):
        hub.choose({"decision": at([PASS, MANA], active=OPP, turn=2, stack=stack)})
    assert hub.frames_total == 3
    pump_once(bridge)  # the first state the pump sees of game 2 already has three positions
    assert drawn_stacks(sent) == [["Lava Dart"], ["Counterspell", "Lava Dart"], []]
    assert bridge.sent_frames == 3 and bridge.sent_frames_game == "g-2"


def test_a_frame_cursor_above_the_hubs_total_starts_over() -> None:
    hub = new_hub(real=True)
    for stack in (opponents_stack("Shock"), []):
        hub.choose({"decision": at([PASS, MANA], active=OPP, turn=4, stack=stack)})
    assert len(hub.wait_state(-1, timeout=0.1, frames_from=7)["frames"]) == 2  # a count from another game
    assert len(hub.wait_state(-1, timeout=0.1, frames_from=2)["frames"]) == 0
    assert len(hub.wait_state(-1, timeout=0.1, frames_from=1, frames_game="g-1")["frames"]) == 1
    assert len(hub.wait_state(-1, timeout=0.1, frames_from=1, frames_game="g-0")["frames"]) == 2  # another game's count


def test_the_pacing_of_drawn_positions_holds_no_lock_so_the_persons_answer_is_handled_at_once() -> None:
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub, gap=0.4)  # four positions: 1.2 s of pacing
    for stack in (opponents_stack("Shock"), [], opponents_stack("Fireblast"), []):
        hub.choose({"decision": at([PASS, MANA], active=OPP, turn=4, stack=stack)})
    def ask() -> None:
        try:
            hub.choose({"decision": at([PASS, BOLT], active=OPP, turn=4, stack=opponents_stack("Fireblast"))})
        except Conceded:  # the arena's side of a concession
            pass

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    pusher = threading.Thread(target=bridge._pump_once, args=(-1,), daemon=True)  # the pump's own step
    pusher.start()
    deadline = time.monotonic() + 3
    while not drawn_stacks(sent) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert drawn_stacks(sent) and pusher.is_alive()  # pacing: the first position is out, the rest wait
    started = time.monotonic()
    bridge._on_host(None, {"type": "StateUpdate", "from_player": "human",
                           "state": {"kind": "response", "promptId": 99, "action": {}}})  # a relay handler
    handled = time.monotonic() - started
    assert handled < 0.25 and pusher.is_alive()
    assert any(m.get("state", {}).get("kind") == "error" for m in sent)  # it was answered, not queued behind the pacing
    started = time.monotonic()
    bridge._on_host(None, {"type": "StateUpdate", "from_player": "human", "state": directive("concede")})
    assert time.monotonic() - started < 0.25 and pusher.is_alive()
    assert hub.game_over["reason"] == "conceded"  # the person's answer took effect during the pacing
    thread.join(5)
    pusher.join(5)
    assert not pusher.is_alive()
    assert not any(m.get("state", {}).get("kind") == "prompt" and m["state"]["prompt"]["input"]["type"] == "chooseAction"
                   for m in sent)  # the decision it was about is gone: it is not sent after the fact


# -- display pacing: what the session passed through is drawn slowly enough to follow -----------------------------------------


def creature_on(observation: dict, seat: str, oid: str, name: str, **permanent) -> None:
    players = {p["seat"]: p for p in observation["players"]}
    players[seat].setdefault("battlefield", []).append(
        {**ref(oid, name, seat), "characteristics": {"types": ["creature"], "keywords": [], "power": 2, "toughness": 2},
         "permanent": {"tapped": False, "attacking": False, "blocking": False, "counters": {}, "damage": 0, **permanent}})


def test_what_changed_sets_how_long_a_position_stays() -> None:
    from spellbench.human.manabrew.host import pace_kind
    base = at([PASS, MANA], phase="precombat_main", active=OPP, turn=4)["observation"]
    same = json.loads(json.dumps(base))
    assert pace_kind(None, base, ME) is None and pace_kind(base, same, ME) is None
    assert pace_kind(base, at([PASS], phase="precombat_main", active=ME, turn=5)["observation"], ME) == "turn"
    assert pace_kind(base, at([PASS], phase="postcombat_main", active=OPP, turn=4)["observation"], ME) == "step"
    cast = at([PASS], active=OPP, turn=4, stack=opponents_stack("Shock"))["observation"]
    assert pace_kind(base, cast, ME) == "action" and pace_kind(cast, base, ME) == "action"  # cast, then resolved
    mine = at([PASS], active=OPP, turn=4, stack=[{**ref("o-x", "Bolt", ME, "stack"), "stack_kind": "spell"}])["observation"]
    assert pace_kind(base, mine, ME) == "own"
    hurt = json.loads(json.dumps(base))
    hurt["players"][0]["life"] -= 3
    assert pace_kind(base, hurt, ME) == "action"
    before = at([PASS], phase="declare_attackers", active=OPP, turn=4)["observation"]
    after = json.loads(json.dumps(before))
    creature_on(before, OPP, "o-g", "Goblin")
    creature_on(after, OPP, "o-g", "Goblin", attacking=True, tapped=True)
    assert pace_kind(before, after, ME) == "combat"  # the opponent's attackers
    assert pace_kind(before, after, OPP) == "own"


def opponent_turn(hub: Hub) -> None:
    """An opponent's turn the session passes through for the person: a new turn, a spell cast and resolved, a step."""
    hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=ME, turn=3)})
    hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=4)})
    hub.say("Opp casts Shock")
    hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=4, stack=opponents_stack("Shock"))})
    hub.say("Shock resolves")
    hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=4)})
    hub.choose({"decision": at([PASS, MANA], phase="postcombat_main", active=OPP, turn=4)})


def test_paced_positions_wait_by_what_changed_and_the_log_comes_with_each(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats = 1.0, SEATS
    waits: list[float] = []
    monkeypatch.setattr(host.time, "sleep", waits.append)  # no real waiting: the waits asked for are kept
    opponent_turn(hub)
    pump_once(bridge)
    assert drawn_stacks(sent) == [[], [], ["Shock"], [], []]  # every position, the stack ones and the others
    # dwell of each drawn position before the next one: the new turn, the spell, its resolution (the last one is the
    # current position, which the prompt of a decision would follow at once)
    assert waits == pytest.approx([0.9, 0.75, 0.75], abs=0.01)
    kinds = [m["state"]["kind"] for m in sent if m.get("state", {}).get("kind") in ("state", "log")]
    messages = [m["state"]["entry"]["message"] for m in sent if m.get("state", {}).get("kind") == "log"]
    assert messages.index("Opp casts Shock") < messages.index("Shock resolves")
    # the line about the spell is sent with the position that shows it, not after everything
    shock_line = next(i for i, m in enumerate(sent) if m.get("state", {}).get("entry", {}).get("message") == "Opp casts Shock")
    shock_view = next(i for i, m in enumerate(sent) if m.get("state", {}).get("kind") == "state"
                      and m["state"]["state"]["gameView"]["stack"])
    assert shock_line < shock_view and kinds.count("state") == 5


def alternating_turns_and_own_spells(hub: Hub, count: int) -> None:
    """``count`` positions the session passes through at once: a new turn, then my own spell on the stack, and again."""
    for n in range(count):
        turn = 4 + n // 2
        stack = [] if n % 2 == 0 else [{**MY_SPELL, "object_id": f"o-m{n}"}]
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn, stack=stack)})


def test_a_long_burst_of_mixed_changes_is_drawn_in_full_within_one_budget(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats = 1.0, SEATS
    waits: list[float] = []
    monkeypatch.setattr(host.time, "sleep", waits.append)
    alternating_turns_and_own_spells(hub, 30)  # 0.9 s and 0.2 s dwells, clamped to the 0.12 s floor when scaled
    pump_once(bridge)
    assert hub.positions_total == 30 and bridge.sent_positions == 30
    assert len(drawn_stacks(sent)) == 30  # every position is drawn, none dropped
    assert 0 < sum(waits) <= bridge.PACE_CAP_S + 1e-9  # the clamped dwells share one budget
    sent.clear(), waits.clear()
    pump_once(bridge)
    assert drawn_stacks(sent) == [] and waits == []  # nothing is drawn twice


def test_with_pacing_off_the_stack_positions_are_kept_and_drawn_as_before(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    expected, last = [], ()
    for n in range(50):  # stack changes with step changes between them, which never push a stack change out
        stack = opponents_stack(f"Shock{n}") if n % 2 == 0 else []
        for phase in ("precombat_main", "postcombat_main"):
            request = at([PASS, MANA], phase=phase, active=OPP, turn=4, stack=stack)
            hub.choose({"decision": request})
            ids = tuple(entry["object_id"] for entry in stack)
            if ids != last:
                expected.append(request["observation"])
                last = ids
    assert hub.frames == expected[-40:] and hub.frames_total == len(expected)
    bridge, sent = paced_bridge(hub, gap=0.2)
    monkeypatch.setattr(host.time, "sleep", lambda s: None)
    pump_once(bridge)
    assert len(drawn_stacks(sent)) == 8 + 1  # the newest eight stack positions, then the current one


def test_a_low_bank_draws_without_waiting(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats = 1.0, SEATS
    waits: list[float] = []
    monkeypatch.setattr(host.time, "sleep", waits.append)
    low = {"remaining_ms": 90_000, "max_decision_ms": 1_800_000}  # a minute and a half left
    for turn in range(4, 8):
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn), "clock": low})
    pump_once(bridge)
    assert len(drawn_stacks(sent)) == 4 and waits == []  # all drawn, nothing waited: the drawing never runs a bank out
    plenty = {"remaining_ms": 1_000_000, "max_decision_ms": 1_800_000}
    for turn in range(8, 10):
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn), "clock": plenty})
    pump_once(bridge)
    assert waits  # with time in the bank the positions are paced again


def test_a_valid_answer_during_a_paced_wait_is_taken_before_the_wait_ends(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats = 1.0, SEATS
    opponent_turn(hub)
    spell = opponents_stack("Fireblast")
    thread = waiting_priority(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4, stack=spell))
    monkeypatch.setattr(host.time, "sleep", lambda seconds: None)
    pump_once(bridge)  # the burst, then the prompt of the open decision
    prompt = next(m["state"]["prompt"] for m in sent if m.get("state", {}).get("kind") == "prompt")
    # The burst is drawn again while that prompt is open; its first wait blocks until the test lets it go.
    in_wait, release = threading.Event(), threading.Event()

    def blocking(seconds: float) -> None:
        in_wait.set()
        release.wait(10)

    monkeypatch.setattr(host.time, "sleep", blocking)
    state = hub.wait_state(-1, timeout=0.1, frames_from=bridge.sent_frames, frames_game=bridge.sent_frames_game,
                           positions_from=0)
    pusher = threading.Thread(target=bridge._push, args=(state,), daemon=True)
    pusher.start()
    try:
        assert in_wait.wait(5)  # the drawing is in a paced wait now
        begun = time.monotonic()
        bridge._on_host(None, {"type": "StateUpdate", "from_player": "human", "state": {
            "kind": "response", "promptId": prompt["promptId"], "action": {"type": "pass", "exhaustStack": False}}})
        thread.join(5)
        assert thread.result == [0] and time.monotonic() - begun < 0.5  # accepted while the wait still runs
        assert pusher.is_alive() and not release.is_set()
        assert bridge._dwell == 0.0  # and what follows from it is not held back
    finally:
        release.set()
        pusher.join(10)


def test_unsent_positions_are_kept_and_a_gap_is_said_never_silent(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    import spellbench.human.server as server
    hub = new_hub(real=True)
    hub.wait_state(-1, timeout=0.01, positions_from=0)  # a host draws the positions
    for turn in range(4, 454):  # 450 positions before the host takes any
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn)})
    state = hub.wait_state(-1, timeout=0.01, positions_from=0)
    assert len(state["positions"]) == 450 and "positions_gap" not in state
    hub.wait_state(-1, timeout=0.01, positions_from=450)
    assert hub.positions == []  # taken ones go
    monkeypatch.setattr(server, "POSITION_UNSENT_LIMIT", 10)
    for turn in range(500, 520):
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn)})
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats, bridge.sent_positions = 1.0, SEATS, 450
    monkeypatch.setattr(host.time, "sleep", lambda seconds: None)
    pump_once(bridge)
    assert len(drawn_stacks(sent)) == 10 and bridge.sent_positions == 470
    assert any("10 board positions were not drawn" in line["text"] for line in hub.log)  # said, in the log


def test_the_bank_floor_counts_only_the_persons_own_running_clock(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats = 1.0, SEATS
    waits: list[float] = []
    monkeypatch.setattr(host.time, "sleep", waits.append)
    clock = {"remaining_ms": 122_000, "max_decision_ms": 1_800_000}
    for turn in range(4, 8):
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn), "clock": clock})
    hub.clock["at"] -= 3_000  # the opponent thought for three seconds since: not the person's time
    pump_once(bridge)
    assert waits  # 122 s in the bank and nothing of the person's open: paced


def test_no_paced_wait_takes_an_open_decisions_bank_under_the_floor(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub)
    bridge.pace, bridge.seats = 1.0, SEATS
    waits: list[float] = []
    monkeypatch.setattr(host.time, "sleep", waits.append)
    clock = {"remaining_ms": 120_500, "max_decision_ms": 1_800_000}  # half a second above the floor
    for turn, stack in ((4, []), (4, opponents_stack("Shock")), (5, []), (6, opponents_stack("Bolt"))):
        hub.choose({"decision": at([PASS, MANA], phase="precombat_main", active=OPP, turn=turn, stack=stack),
                    "clock": clock})
    result: list[int] = []
    asked = threading.Thread(target=lambda: result.append(hub.choose({"decision": at(
        [PASS, BOLT], phase="precombat_main", active=OPP, turn=6, stack=opponents_stack("Bolt", "Shock")),
        "clock": clock})), daemon=True)
    asked.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    pump_once(bridge)
    assert sum(waits) <= 0.5 + 1e-6  # never past the floor, though the burst would want about 3 s
    hub.answer_with(hub.pending["seq"], 0)
    asked.join(5)


def test_pacing_off_draws_only_the_stack_changes_as_before(monkeypatch) -> None:
    import spellbench.human.manabrew.host as host
    hub = new_hub(real=True)
    bridge, sent = paced_bridge(hub, gap=0.2)
    waits: list[float] = []
    monkeypatch.setattr(host.time, "sleep", waits.append)
    opponent_turn(hub)
    pump_once(bridge)
    assert drawn_stacks(sent) == [["Shock"], [], []]  # the spell, its resolution, then the current position
    assert waits == [0.2]


def test_the_page_state_does_not_carry_the_frames() -> None:
    hub = new_hub(real=True)
    hub.choose({"decision": at([PASS, MANA], active=OPP, turn=4, stack=opponents_stack("Shock"))})
    assert "frames" not in hub.state() and "frames" not in hub.wait_state(-1, timeout=0.1)
    assert len(hub.wait_state(-1, timeout=0.1, frames_from=0)["frames"]) == 1


# -- the scripted client sends the real payloads ---------------------------------------------------------------------------------


def game_view(step: str, active: str = "player-0", stack: list | None = None) -> dict:
    return {"step": step, "activePlayerId": active, "stack": stack or [],
            "players": [{"id": "player-0", "status": "playing"}, {"id": "player-1", "status": "playing"}]}


def test_the_stand_in_sends_what_the_clients_buttons_send() -> None:
    me = "player-0"
    # Space at main 1 of my turn: to the next stop of mine (the attackers step)
    assert fake_client.pass_output(game_view("main1"), me, "stops") == {
        "type": "pass", "exhaustStack": False,
        "until": {"playerId": "player-0", "phase": "combatDeclareAttackers", "throughCombat": False}}
    # at attackers: main 2; at main 2: the opponent's end step
    assert fake_client.pass_output(game_view("combatDeclareAttackers"), me, "stops")["until"]["phase"] == "main2"
    assert fake_client.pass_output(game_view("main2"), me, "stops")["until"] == {
        "playerId": "player-1", "phase": "endOfTurn", "throughCombat": False}
    # on the opponent's turn: its end step, then my next turn's main 1
    assert fake_client.pass_output(game_view("main1", "player-1"), me, "stops")["until"]["phase"] == "endOfTurn"
    assert fake_client.pass_output(game_view("endOfTurn", "player-1"), me, "stops")["until"] == {
        "playerId": "player-0", "phase": "main1", "throughCombat": False}
    # END TURN: the first stop of the next player's turn, through combat
    assert fake_client.pass_output(game_view("main1"), me, "end-turn")["until"] == {
        "playerId": "player-1", "phase": "endOfTurn", "throughCombat": True}
    assert fake_client.pass_output(game_view("main1", "player-1"), me, "end-turn")["until"] == {
        "playerId": "player-0", "phase": "main1", "throughCombat": True}
    assert fake_client.end_turn_stop(game_view("main1"), me, (), ()) == {"playerId": "player-1", "phase": "upkeep"}
    # on a stack: no target; END TURN asks to pass the whole stack
    stack = [{"id": "x"}]
    assert fake_client.pass_output(game_view("main1", stack=stack), me, "stops") == {"type": "pass", "exhaustStack": False}
    assert fake_client.pass_output(game_view("main1", stack=stack), me, "end-turn") == {"type": "pass", "exhaustStack": True}
    assert fake_client.pass_output(game_view("main1"), me, "plain") == {"type": "pass", "exhaustStack": False}


def test_the_stand_ins_buttons_drive_the_session_the_way_the_client_does() -> None:
    hub = new_hub(real=True)
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    bridge.host = type("Relay", (), {"send": staticmethod(lambda m: None)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = SEATS
    for n, (mode, expected) in enumerate((("stops", ("declare_attackers", False)), ("end-turn", ("postcombat_main", True)))):
        hub.hold = None
        thread = waiting_priority(hub, at([PASS, BOLT], phase="precombat_main", turn=3 + n))
        bridge._push(hub.state())
        envelope = bridge.prompt
        prompt = {"promptId": hub.pending["seq"], "input": {"type": "chooseAction", "actions": []}}
        output = fake_client.answer(prompt, view=game_view("main1"), me="player-0", pass_mode=mode)
        bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": hub.pending["seq"],
                                      "action": {"type": "chooseAction", "output": output}})
        thread.join(5)
        assert envelope is not None and thread.result == [0]
        assert (hub.hold["step"], hub.hold["through_combat"]) == expected
        bridge.prompt = None


# -- the owner's recorded games ----------------------------------------------------------------------------------------------------


def client_view(observation: dict, pid: dict) -> dict:
    """The gameView fields the client's pass controls read, from an observation."""
    return {"step": view.STEPS.get(observation.get("phase_step"), "main1"), "activePlayerId": pid[observation["active_seat"]],
            "stack": observation.get("stack") or [],
            "players": [{"id": pid[ME], "status": "playing"}, {"id": pid[OPP], "status": "playing"}]}


def replay_through(game: dict) -> dict:
    """One recorded human game's decisions through the session's rule. The person answers as recorded, except that a
    recorded pass (or a window the old session passed for them) is the client's Space: a pass with the next stop as its
    target, or none on a stack. Returns the priority windows asked, per turn, and the recorded answers the rule would
    have taken out of the person's hands (decisions it answered itself where they had acted)."""
    hub = Hub(real_action_stops=True)
    hub.game_start({"game_id": game["game_id"], "seat": game["seat"], "own_deck": {"name": game["deck"]},
                    "opponent_deck": {"name": "?"}})
    hub.narrator = None  # the log is not what is measured
    me = game["seat"]
    other = OPP if me == ME else ME
    pid = {me: "player-0", other: "player-1"}
    seats = view.Seats(me, "player-0", "player-1", {})
    asked, hidden, per_turn, before = 0, [], {}, 0
    hub.cond.acquire()  # the session's own thread holds the lock around a decision
    for line, sd in zip(game["log"], game["engine"]):
        priority = (sd.get("context") or {}).get("kind") == "priority"
        if priority and len(sd["candidates"]) > 1 and real_actions(sd["candidates"]):
            before += 1  # the previous rule asked at every one of these
        how_, chosen = hub._begin(sd, {})
        if chosen is not None:
            if chosen != line["candidate_id"] and line["how"] in ("human", "plan"):
                hidden.append((sd["observation"]["turn"], sd["observation"]["phase_step"], line["semantic"]["kind"]))
            hub._conclude(sd, how_, chosen, None, 0.0)
            continue
        if priority:
            asked += 1
            key = (sd["observation"]["turn"], sd["observation"]["active_seat"])
            per_turn[key] = per_turn.get(key, 0) + 1
        seq = hub.pending["seq"]
        acted = line["how"] != "auto_pass" and line["semantic"]["kind"] != "pass"
        if priority and not acted:
            out = fake_client.pass_output(client_view(sd["observation"], pid), "player-0", "stops")
            error = hub.pass_with(seq, prompts.hold_target(out.get("until"), seats), exhaust_stack=out["exhaustStack"])
        else:
            error = hub.answer_with(seq, line["candidate_id"])
        assert error is None
        chosen, how_, _ = hub._take_answer()
        hub._conclude(sd, how_, chosen, None, 0.0)
    hub.cond.release()
    return {"asked": asked, "before": before, "hidden": hidden, "per_turn": per_turn}


@recorded
def test_the_rule_never_takes_a_recorded_action_out_of_the_persons_hands() -> None:
    games = recorded_games()
    assert len(games) == 4
    for game in games:
        result = replay_through(game)
        assert result["hidden"] == [], game["game_id"]
        assert result["asked"] <= result["before"]
