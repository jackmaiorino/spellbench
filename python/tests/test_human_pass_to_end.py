"""The person's "pass until the opponent's end step" (the local pass control's P and shift+P): a hold of the same kind
as the client's pass-until, aimed at the opponent's end step and not running through the opponent's combat. While it is
ahead every priority window of the person's is passed for them, on their turn and the opponent's; it stops at the
opponent's end step, the first time they are asked anything (an opponent object on the stack, an attack, a choice), at
any action of theirs or when they turn it off; with every-turn it is armed again at each opponent turn. Person-side
only: the engine and the bot see the passes, at the windows the engine offered."""

from __future__ import annotations

import pytest

from spellbench.human.manabrew.host import PASS_MODE_DIRECTIVE, Bridge
from spellbench.human.server import Hub

from test_human_flow import SEATS, at, attack_step, how, until
from test_human_manabrew import directive
from test_human_stops import BOLT, MANA, ME, MY_SPELL, NINJA, OPP, PASS, SPELL_ON_STACK, waiting_priority


def full_hub(**kwargs) -> Hub:
    """The session the person plays: real-action stops, full priority, the client's countdown on mana-only windows."""
    hub = Hub(real_action_stops=True, full_priority=True, client_autopass=True, **kwargs)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    return hub


def press(hub: Hub, request: dict, *, every_turn: bool = False) -> None:
    """The person is asked at ``request`` and turns the mode on: that priority is passed for them."""
    thread = waiting_priority(hub, request)
    assert hub.pass_to_opponent_end(True, every_turn) is None
    thread.join(5)
    assert thread.result == [0]
    assert hub.pass_mode["on"] and hub.hold["mode"] and hub.hold["seat"] == OPP


def choice(active: str, turn: int, phase: str = "precombat_main") -> dict:
    """A decision that is not a priority (a discard, a target): always the person's."""
    d = at([], phase=phase, active=active, turn=turn)
    d["context"] = {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False}
    d["candidates"] = [{"candidate_id": i, "semantic": {"kind": "choose_target", "target": {"object_id": f"o-{i}"}},
                        "display_text": None} for i in range(2)]
    return d


def test_on_from_my_turn_passes_my_windows_declines_my_attack_and_stops_at_the_opponents_end_step() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert hub.hold["step"] == "end_step" and hub.hold["through_combat"] is False
    assert how(hub, at([PASS, BOLT], phase="beginning_of_combat", turn=3)) == "auto_pass"
    with hub.cond:
        assert hub._begin(attack_step(0, 1, turn=3), {}) == ("auto_pass", 0)  # no attackers
    assert how(hub, at([PASS, BOLT, NINJA], phase="postcombat_main", turn=3)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="end_step", turn=3)) == "auto_pass"
    for step in ("upkeep", "draw", "precombat_main", "beginning_of_combat", "postcombat_main"):
        assert how(hub, at([PASS, BOLT], phase=step, active=OPP, turn=4)) == "auto_pass", step
    assert how(hub, at([PASS, MANA], phase="postcombat_main", active=OPP, turn=4)) == "auto_pass"  # no countdown either
    assert hub.pass_mode["on"]
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"  # the end step: his priority
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "reached" and hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="precombat_main", turn=5)) == "human"  # his next turn is his own


def test_on_from_the_opponents_turn_stops_at_this_turns_end_step() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4))
    assert hub.hold["turn"] == (4, OPP)
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"
    assert hub.pass_mode["ended"] == "reached"


def test_without_full_priority_it_stops_at_the_nearest_window_before_the_end_step() -> None:
    hub = Hub(real_action_stops=True)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert hub.hold["step"] == "postcombat_main" and hub.pass_mode_view()["step"] == "postcombat_main"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"
    assert hub.pass_mode["ended"] == "reached"


def test_an_opponents_spell_on_the_stack_stops_it_and_turns_it_off() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="postcombat_main", turn=3))
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "stack" and hub.hold is None
    # off now: the rest of the turn is the person's as usual
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"


def test_a_spell_he_cannot_answer_does_not_stop_it_but_a_mana_window_on_the_stack_does() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="postcombat_main", turn=3))
    assert how(hub, at([PASS], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "single"
    assert hub.pass_mode["on"]  # nothing he could do: not asked, the mode goes on
    assert how(hub, at([PASS, MANA], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"
    assert hub.pass_mode["ended"] == "stack"  # the client's countdown has it: he is told it stopped


def test_the_opponents_attack_stops_it_but_his_own_forced_combat_does_not() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert how(hub, at([PASS, BOLT], phase="declare_attackers", turn=3, attacking=True)) == "auto_pass"
    assert hub.pass_mode["on"]
    assert how(hub, at([PASS, BOLT], phase="beginning_of_combat", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="declare_attackers", active=OPP, turn=4, attacking=True)) == "human"
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "attack"


@pytest.mark.parametrize("active,turn", [(ME, 3), (OPP, 4)])
def test_a_real_decision_is_still_asked_and_ends_it(active: str, turn: int) -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert how(hub, choice(active, turn, "postcombat_main")) == "human"
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "decision"


def test_cancel_clears_it() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3), every_turn=True)
    assert hub.pass_to_opponent_end(False) is None
    assert hub.hold is None and hub.pass_mode["on"] is False and hub.pass_mode["every_turn"] is False
    assert hub.pass_mode["ended"] == "cancelled"
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", turn=3)) == "human"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4)) == "human"  # no re-arm


def test_any_action_of_his_ends_it() -> None:
    hub = full_hub()
    with hub.cond:
        hub._begin(choice(ME, 3), {})
    assert hub.pass_to_opponent_end(True) is None  # turned on during a choice: the choice is not answered
    assert hub.answer is None and hub.pass_mode["on"]
    assert hub.answer_with(hub.pending["seq"], 1) is None
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "your_action" and hub.hold is None


def test_every_turn_rearms_at_each_opponent_turn_and_never_on_his_own() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4), every_turn=True)
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"
    assert hub.pass_mode["ended"] == "reached" and hub.pass_mode["every_turn"]
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4, stack=[MY_SPELL])) == "human"  # same turn
    assert hub.pass_mode["on"] is False
    for step in ("upkeep", "precombat_main", "postcombat_main", "end_step"):  # his own turn stays normal
        assert how(hub, at([PASS, BOLT], phase=step, turn=5)) == "human", step
    assert hub.pass_mode["on"] is False
    assert how(hub, at([PASS, BOLT], phase="upkeep", active=OPP, turn=6)) == "auto_pass"  # armed again
    assert hub.pass_mode["on"] and hub.pass_mode["every_turn"]
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=6, stack=[SPELL_ON_STACK])) == "human"
    assert hub.pass_mode["ended"] == "stack"
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=6)) == "human"  # not again this turn
    assert how(hub, at([PASS, BOLT], phase="precombat_main", turn=7)) == "human"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=8)) == "auto_pass"
    assert hub.pass_mode["on"]


def test_every_turn_pressed_on_his_turn_passes_now_like_p_and_rearms_after() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3), every_turn=True)
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", turn=3)) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", turn=5)) == "human"
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=6)) == "auto_pass"


def test_a_new_game_starts_with_it_off() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3), every_turn=True)
    hub.game_start({"game_id": "g-2", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    assert hub.hold is None and hub.pass_mode_view()["on"] is False and hub.pass_mode_view()["every_turn"] is False


def test_with_no_game_it_is_refused() -> None:
    assert Hub(real_action_stops=True).pass_to_opponent_end(True) == "no game in progress"


# -- (gap 3) a pass the client sends while the mode is on neither retargets nor clears it --------------------------------


def test_a_client_pass_until_or_plain_pass_while_it_is_on_keeps_the_modes_hold() -> None:
    hub = full_hub()
    with hub.cond:
        hub._begin(at([PASS, MANA, BOLT], phase="precombat_main", turn=3), {})
    seq = hub.pending["seq"]
    assert hub.pass_to_opponent_end(True) is None
    hold = dict(hub.hold)
    assert hub.answer == 0
    # the client's countdown on that window, then Space aimed at his next phase stop, then a pass with no target:
    # all for the window the mode already passed
    assert hub.pass_with(seq, {"seat": ME, "step": "postcombat_main", "through_combat": False}) is None
    assert hub.pass_with(seq, None, exhaust_stack=True) is None
    assert hub.answer_with(seq, 0) is None
    assert hub.hold == hold and hub.pass_mode["on"] and hub.answer == 0 and not hub.exhaust_stack


def test_a_pass_the_client_sends_for_the_open_prompt_after_the_directive_is_taken_quietly() -> None:
    hub = full_hub()
    bridge, sent = bridge_for(hub)
    request = at([PASS, BOLT], phase="precombat_main", turn=3)
    with hub.cond:
        hub._begin(request, {})
    bridge._push(hub.state())
    seq = hub.pending["seq"]
    bridge._on_response("human", directive(PASS_MODE_DIRECTIVE, on=True, everyTurn=False))
    hold = dict(hub.hold)
    bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": seq, "action": {
        "type": "chooseAction", "output": {"type": "pass", "until": until(ME, "postcombat_main"), "exhaustStack": False}}})
    assert hub.hold == hold and hub.answer == 0
    assert not [m for m in sent if m.get("state", {}).get("kind") == "error"]


# -- the client is told ----------------------------------------------------------------------------------------------------


def bridge_for(hub: Hub) -> tuple[Bridge, list[dict]]:
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": staticmethod(sent.append)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = SEATS
    return bridge, sent


def pass_modes(sent: list[dict]) -> list[dict]:
    return [m["state"]["entry"]["passMode"] for m in sent
            if m.get("state", {}).get("kind") == "log" and "passMode" in m["state"]["entry"]]


def test_the_state_is_published_to_the_client_once_per_change() -> None:
    hub = full_hub()
    bridge, sent = bridge_for(hub)
    thread = waiting_priority(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    bridge._push(hub.state())
    bridge._on_response("human", directive(PASS_MODE_DIRECTIVE, on=True, everyTurn=True))
    thread.join(5)
    assert thread.result == [0]
    bridge._push(hub.state())
    bridge._push(hub.state())  # nothing changed: not sent again
    shown = pass_modes(sent)
    assert shown[-1]["on"] is True and shown[-1]["everyTurn"] is True and shown[-1]["step"] == "end_step"
    assert [m["on"] for m in shown] == [True]  # an untouched mode is never sent
    entry = next(m["state"]["entry"] for m in sent if "passMode" in m.get("state", {}).get("entry", {}))
    assert entry["message"] == ""  # the client's own log ignores it
    bridge._on_response("human", directive(PASS_MODE_DIRECTIVE, on=False, everyTurn=False))
    bridge._push(hub.state())
    assert pass_modes(sent)[-1] == {**pass_modes(sent)[-1], "on": False, "everyTurn": False, "ended": "cancelled"}
    # the log says it too
    texts = [m["state"]["entry"]["message"] for m in sent if m.get("state", {}).get("kind") == "log"]
    assert any("Passing for you until the opponent's end step" in t for t in texts)
    assert any("turned off" in t for t in texts)
    assert not [m for m in sent if m.get("state", {}).get("kind") == "error"]


def test_a_returning_client_is_told_again() -> None:
    hub = full_hub()
    bridge, sent = bridge_for(hub)
    with hub.cond:
        hub._begin(at([PASS, BOLT], phase="precombat_main", turn=3), {})
    bridge._push(hub.state())
    bridge._on_response("human", directive(PASS_MODE_DIRECTIVE, on=True, everyTurn=False))
    bridge._push(hub.state())
    count = len(pass_modes(sent))
    bridge.rejoins += 1
    bridge._push(hub.state())
    assert len(pass_modes(sent)) == count + 1


def test_other_directives_are_still_ignored_and_concede_still_works() -> None:
    hub = full_hub()
    bridge, _ = bridge_for(hub)
    bridge._on_response("human", directive("requestRepeat", iterations=2))
    assert hub.pass_mode["on"] is False and hub.game_over is None
