"""The person's "pass until the opponent's end step" (the local pass control's P and shift+P): a hold of the same kind
as the client's pass-until, aimed at the opponent's end step and not running through the opponent's combat. While it is
ahead every priority window of the person's is passed for them, on their turn and the opponent's; it stops at the
opponent's end step, the first time they are asked anything (an opponent object on the stack, an attack, a choice), at
any action of theirs or when they turn it off; with every-turn it is armed again at each opponent turn. Person-side
only: the engine and the bot see the passes, at the windows the engine offered."""

from __future__ import annotations

import pytest

from spellbench.human.manabrew.host import PASS_MODE_FIELD, Bridge, pass_mode_directive
from spellbench.human.server import Hub

from test_human_flow import SEATS, at, attack_step, how, until
from test_human_manabrew import directive
from test_human_stops import BOLT, MANA, ME, MY_SPELL, NINJA, OPP, PASS, SPELL_ON_STACK, ref, waiting_priority


def control(on: bool, every_turn: bool) -> dict:
    """The envelope the client's control sends (through the relay, as the person's directive)."""
    return {"kind": "directive", "fromPlayer": "player-0", "directive": pass_mode_directive(on, every_turn)}


def full_hub(**kwargs) -> Hub:
    """The session the person plays: real-action stops, full priority, the client's countdown on mana-only windows."""
    hub = Hub(real_action_stops=True, full_priority=True, client_autopass=True, **kwargs)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    return hub


def press(hub: Hub, request: dict, *, every_turn: bool = False, armed: bool = True) -> None:
    """The person is asked at ``request`` and presses the control: the directive, then the client's own pass of that
    priority (the host passes nothing by itself)."""
    thread = waiting_priority(hub, request)
    assert hub.pass_to_opponent_end(True, every_turn) is None
    assert hub.answer is None  # the directive alone answers nothing
    assert hub.answer_with(hub.pending["seq"], 0) is None  # the client's pass (candidate 0 is the pass)
    thread.join(5)
    assert thread.result == [0]
    if armed:
        assert hub.pass_mode["on"] and hub.hold["mode"] and hub.hold["seat"] == OPP
    else:
        assert hub.pass_mode["on"] is False and hub.hold is None


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


OPP_TRIGGER = {**ref("o-t", "Guttersnipe", OPP, "stack"), "stack_kind": "triggered_ability", "targets": []}


@pytest.mark.parametrize("stack", [[SPELL_ON_STACK], [OPP_TRIGGER], [MY_SPELL, SPELL_ON_STACK]])
def test_an_opponents_object_on_the_stack_stops_it_even_where_he_can_only_pass(stack: list) -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="postcombat_main", turn=3))
    assert how(hub, at([PASS], phase="precombat_main", active=OPP, turn=4, stack=stack)) == "single"  # only a pass
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "stack" and hub.hold is None
    # so the next window where he can act is his, not passed for him
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"


def test_a_mana_only_window_on_the_opponents_stack_stops_it_too() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="postcombat_main", turn=3))
    assert how(hub, at([PASS, MANA], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"
    assert hub.pass_mode["ended"] == "stack"  # the client's countdown has it: he is told it stopped


def test_the_opponents_attack_stops_it_even_where_he_can_only_pass() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert how(hub, at([PASS], phase="declare_attackers", active=OPP, turn=4, attacking=True)) == "single"
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "attack"
    assert how(hub, at([PASS, BOLT], phase="declare_blockers", active=OPP, turn=4, attacking=True)) == "human"


def test_his_own_spell_alone_on_the_stack_does_not_stop_it_where_he_can_only_pass() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert how(hub, at([PASS], phase="precombat_main", turn=3, stack=[MY_SPELL])) == "single"
    assert hub.pass_mode["on"]


# -- pressed where the opponent has already acted: only that window is passed, nothing is armed ---------------------------


@pytest.mark.parametrize("where,ended", [
    ({"phase": "precombat_main", "stack": [SPELL_ON_STACK]}, "stack"),
    ({"phase": "precombat_main", "stack": [OPP_TRIGGER]}, "stack"),
    ({"phase": "declare_attackers", "attacking": True}, "attack"),
])
def test_pressed_at_an_opponents_spell_or_attack_it_passes_that_window_only_and_does_not_arm(where: dict,
                                                                                            ended: str) -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], active=OPP, turn=4, **where), armed=False)
    assert hub.pass_mode["ended"] == ended
    # the next clear windows of that turn are his: nothing was armed to pass them
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"
    assert any("Only this priority is passed" in line["text"] for line in hub.log)


def test_pressed_with_every_turn_at_an_opponents_spell_it_waits_for_their_next_turn() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK]), every_turn=True,
          armed=False)
    assert hub.pass_mode["every_turn"]
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=4)) == "human"  # not this turn
    assert how(hub, at([PASS, BOLT], phase="precombat_main", turn=5)) == "human"
    assert how(hub, at([PASS, BOLT], phase="upkeep", active=OPP, turn=6)) == "auto_pass"
    assert hub.pass_mode["on"]


def test_every_turn_does_not_arm_in_an_opponent_turn_whose_first_window_has_their_object() -> None:
    hub = full_hub()
    press(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4), every_turn=True)
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"  # reached
    assert how(hub, at([PASS, BOLT], phase="precombat_main", turn=5)) == "human"
    assert how(hub, at([PASS], phase="upkeep", active=OPP, turn=6, stack=[OPP_TRIGGER])) == "single"
    assert hub.pass_mode["on"] is False and hub.pass_mode["ended"] == "stack" and hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=6)) == "human"  # not later this turn
    assert how(hub, at([PASS, BOLT], phase="precombat_main", active=OPP, turn=8)) == "auto_pass"  # the next one


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


def test_an_older_host_or_a_lost_directive_leaves_a_plain_pass() -> None:
    """The control passes the open priority with the client's own pass: without the directive (a host that ignores
    it, or a send that failed) that is an ordinary pass of one window, and nothing waits on the host."""
    hub = full_hub()
    thread = waiting_priority(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    assert hub.answer_with(hub.pending["seq"], 0) is None
    thread.join(5)
    assert thread.result == [0] and hub.hold is None and hub.pass_mode["on"] is False
    assert how(hub, at([PASS, BOLT], phase="postcombat_main", turn=3)) == "human"


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
    assert hub.answer is None
    # the control's own pass, then the client's countdown on that window, Space aimed at his next phase stop, an
    # exhaust pass and a pass with no target: none retargets or clears the mode
    assert hub.answer_with(seq, 0) is None and hub.answer == 0
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
    bridge._on_response("human", control(True, False))
    hold = dict(hub.hold)
    assert hub.answer is None  # the host passes nothing by itself: the client's pass follows
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


def state_entries(sent: list[dict]) -> list[dict]:
    """The mode's own entries (no message: the client's own log ignores them)."""
    return [m["state"]["entry"]["passMode"] for m in sent if m.get("state", {}).get("kind") == "log"
            and "passMode" in m["state"]["entry"] and m["state"]["entry"]["message"] == ""]


def test_the_host_advertises_the_control_on_the_first_log_line_of_each_batch() -> None:
    """The control appears only once a host has said it has it: the first log line of each batch carries the state,
    from the game's first lines on (and again after a return, when the whole log comes again). The line is unchanged."""
    hub = full_hub()
    bridge, sent = bridge_for(hub)
    with hub.cond:
        hub._begin(at([PASS, BOLT], phase="precombat_main", turn=3), {})
    bridge._push(hub.state())
    logs = [m["state"]["entry"] for m in sent if m.get("state", {}).get("kind") == "log"]
    assert logs and logs[0]["message"] and logs[0]["passMode"]["on"] is False  # a real line, unchanged
    assert [e for e in logs if "passMode" in e] == [logs[0]]
    assert state_entries(sent) == []


def test_the_state_is_published_to_the_client_once_per_change() -> None:
    hub = full_hub()
    bridge, sent = bridge_for(hub)
    thread = waiting_priority(hub, at([PASS, BOLT], phase="precombat_main", turn=3))
    bridge._push(hub.state())
    bridge._on_response("human", control(True, True))
    bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": hub.pending["seq"],
                                  "action": {"type": "chooseAction", "output": {"type": "pass", "exhaustStack": False}}})
    thread.join(5)
    assert thread.result == [0]
    bridge._push(hub.state())
    bridge._push(hub.state())  # nothing changed: not sent again
    shown = state_entries(sent)
    assert shown[-1]["on"] is True and shown[-1]["everyTurn"] is True and shown[-1]["step"] == "end_step"
    assert [m["on"] for m in shown] == [True]  # an untouched mode gets no entry of its own
    bridge._on_response("human", control(False, False))
    bridge._push(hub.state())
    assert state_entries(sent)[-1] == {**state_entries(sent)[-1], "on": False, "everyTurn": False, "ended": "cancelled"}
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
    bridge._on_response("human", control(True, False))
    bridge._push(hub.state())
    count = len(state_entries(sent))
    bridge.rejoins += 1
    bridge._push(hub.state())
    assert len(state_entries(sent)) == count + 1


def test_the_request_rides_on_a_directive_type_the_relay_forwards() -> None:
    """The relay forwards only directives that parse as the protocol's own DirectiveInput (an unknown type is refused
    as an unauthorized envelope); extra fields pass through. The carrier is a restoreVote for a vote that never exists."""
    sent = pass_mode_directive(True, True)
    assert sent["type"] == "restoreVote" and isinstance(sent["voteId"], int) and 0 <= sent["voteId"] <= 2**32 - 1
    assert sent["accept"] is False and sent[PASS_MODE_FIELD] == {"on": True, "everyTurn": True}


def test_other_directives_are_still_ignored() -> None:
    hub = full_hub()
    bridge, _ = bridge_for(hub)
    bridge._on_response("human", directive("requestRepeat", iterations=2))
    bridge._on_response("human", directive("restoreVote", voteId=3, accept=True))  # a real vote: not the control
    assert hub.pass_mode["on"] is False and hub.game_over is None
