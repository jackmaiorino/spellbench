"""Full priority for a person on the Manabrew path (``python -m spellbench.human --full-priority``): the engine gives
the person's seat every priority window the rules have, so a stop the client sets in upkeep, draw, beginning of combat,
combat damage, end of combat or the end step is taken in that step; a window with only mana abilities goes to the client
(its AUTOPASS countdown or Full control answers it); a window with nothing but passing is still passed by the session;
the advisor shows no numbers at a window the bot's model never trained on; and each game's engine is told the person's
seat. Without the option nothing changes. Display and human flow only: the bot's seat sees none of this."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spellbench.human import session
from spellbench.human.server import (ENGINE_PRIORITY_STEPS, FULL_PRIORITY_STEPS, NEW_PRIORITY_STEPS, STEP_ORDER,
                                     UNTRAINED_READ, Hub, reachable_step)

from test_human_flow import at, pass_priority, until
from test_human_stops import BOLT, MANA, ME, MY_SPELL, OPP, PASS, SPELL_ON_STACK, decision, how

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations" / "mtg_kernel" / "london_human"))
sys.path.insert(1, str(Path(__file__).resolve().parents[2] / "integrations" / "mtg_kernel"))


def full_hub(*, client_autopass: bool = True, **kwargs) -> Hub:
    hub = Hub(real_action_stops=True, full_priority=True, client_autopass=client_autopass, **kwargs)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    return hub


# -- stops are taken where they are set ---------------------------------------------------------------------------


def test_every_step_but_untap_and_cleanup_has_a_window_with_full_priority() -> None:
    assert FULL_PRIORITY_STEPS == ("upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
                                   "declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end_step")
    assert NEW_PRIORITY_STEPS == {"upkeep", "draw", "beginning_of_combat", "combat_damage", "end_of_combat", "end_step"}
    assert set(ENGINE_PRIORITY_STEPS) | NEW_PRIORITY_STEPS == set(FULL_PRIORITY_STEPS)
    assert [reachable_step(step, FULL_PRIORITY_STEPS) for step in STEP_ORDER] == [
        "upkeep", *FULL_PRIORITY_STEPS, "end_step"]


def test_a_stop_at_the_opponents_end_step_is_taken_in_their_end_step() -> None:
    hub = full_hub()
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step"))
    assert hub.hold["seat"] == OPP and hub.hold["step"] == "end_step"
    assert not [line for line in hub.log if "gives no priority" in line["text"]]
    # my own later windows and the opponent's turn up to their end step are passed for me ...
    assert how(hub, at([PASS, BOLT], phase="postcombat_main")) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="end_step")) == "auto_pass"
    for step in ("upkeep", "draw", "precombat_main", "beginning_of_combat", "postcombat_main"):
        assert how(hub, at([PASS, BOLT], phase=step, active=OPP, turn=4)) == "auto_pass", step
    # ... and the end step itself is mine: a true end step, after the opponent's last main phase priority
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"
    assert hub.hold is None


@pytest.mark.parametrize("step", sorted(NEW_PRIORITY_STEPS))
@pytest.mark.parametrize("seat", [ME, OPP])
def test_a_stop_in_any_new_step_of_either_turn_is_taken_there(step: str, seat: str) -> None:
    hub = full_hub()
    other = OPP if seat == ME else ME
    # set in the other seat's second main phase: the stop is in the turn that follows
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", active=other, turn=3), until(seat, step, through=True))
    assert hub.hold["step"] == step
    assert how(hub, at([PASS, BOLT], phase="end_step", active=other, turn=3)) == "auto_pass"
    for earlier in STEP_ORDER[1:STEP_ORDER.index(step)]:
        assert how(hub, at([PASS, BOLT], phase=earlier, active=seat, turn=4)) == "auto_pass", earlier
    assert how(hub, at([PASS, BOLT], phase=step, active=seat, turn=4)) == "human"


def test_my_own_upkeep_stop_reaches_my_upkeep_through_the_opponents_whole_turn() -> None:
    hub = full_hub()
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", turn=3), until(ME, "upkeep", through=True))
    for step in FULL_PRIORITY_STEPS:
        assert how(hub, at([PASS, BOLT], phase=step, active=OPP, turn=4)) == "auto_pass", step
    assert how(hub, at([PASS, BOLT], phase="upkeep", active=ME, turn=5)) == "human"


def test_without_the_option_the_stop_is_still_moved_to_the_nearest_window() -> None:
    hub = Hub(real_action_stops=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    assert hub.full_priority is False and hub.client_autopass is False
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step"))
    assert hub.hold["step"] == "postcombat_main"
    assert [line for line in hub.log if "gives no priority" in line["text"]]


# -- windows with nothing to do, and windows with only mana -----------------------------------------------------------


@pytest.mark.parametrize("step", FULL_PRIORITY_STEPS)
@pytest.mark.parametrize("active", [ME, OPP])
def test_a_window_with_nothing_but_passing_is_passed_by_the_session_as_before(step: str, active: str) -> None:
    hub = full_hub()
    assert how(hub, decision([PASS], phase=step, active=active)) == "single"
    assert how(hub, decision([PASS], phase=step, active=active, stack=[SPELL_ON_STACK])) == "single"


def test_a_mana_only_window_goes_to_the_client_under_the_rules_of_a_real_window() -> None:
    hub = full_hub()
    # no hold: asked, like a window with a real action
    assert how(hub, at([PASS, MANA], phase="end_step", active=OPP, turn=4)) == "human"
    hub.pending = None
    # a hold that is still ahead and an empty stack: passed for the person, no round trip
    pass_priority(hub, at([PASS, BOLT], phase="precombat_main"), until(OPP, "end_step"))
    assert how(hub, at([PASS, MANA], phase="postcombat_main")) == "auto_pass"
    assert how(hub, at([PASS, MANA], phase="upkeep", active=OPP, turn=4)) == "auto_pass"
    # any stack is a stop, held or not
    assert how(hub, at([PASS, MANA], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK])) == "human"
    hub.pending = None
    # the hold's own step: reached, so asked
    assert how(hub, at([PASS, MANA], phase="end_step", active=OPP, turn=4)) == "human"


def test_a_mana_only_window_already_passed_at_is_not_asked_again() -> None:
    hub = full_hub()
    request = at([PASS, MANA], phase="upkeep", active=OPP, turn=4)
    pass_priority(hub, request)
    assert how(hub, request) == "auto_pass"
    assert how(hub, at([PASS, MANA], phase="draw", active=OPP, turn=4)) == "human"  # a new position is asked


def test_a_mana_only_window_gets_no_what_you_can_do_line() -> None:
    hub = full_hub()
    with hub.cond:
        hub._begin(at([PASS, MANA], phase="end_step", active=OPP, turn=4), {})
    assert hub.pending is not None
    assert not [line for line in hub.log if "You can:" in line["text"]]


def test_the_session_keeps_passing_mana_only_windows_when_asked_to() -> None:
    hub = full_hub(client_autopass=False)
    assert how(hub, at([PASS, MANA], phase="end_step", active=OPP, turn=4)) == "auto_pass"
    assert how(hub, at([PASS, MANA], phase="end_step", active=OPP, turn=4, stack=[MY_SPELL])) == "auto_pass"
    assert how(hub, at([PASS, BOLT], phase="end_step", active=OPP, turn=4)) == "human"


def test_the_play_page_never_sends_mana_only_windows() -> None:
    hub = Hub(real_action_stops=False, full_priority=True, client_autopass=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    assert hub.client_autopass is False
    assert how(hub, at([PASS, MANA], phase="end_step", active=OPP, turn=4)) == "auto_pass"


def test_every_game_says_what_the_bot_does_not_respond_to(tmp_path) -> None:
    import json

    from spellbench.human.server import FULL_PRIORITY_NOTE

    start = {"game_id": "g-9", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}}
    hub = Hub(real_action_stops=True, full_priority=True, client_autopass=True, log_dir=tmp_path)
    hub.game_start(start)
    assert [line["text"] for line in hub.log].count(FULL_PRIORITY_NOTE) == 1
    assert "does NOT respond" in FULL_PRIORITY_NOTE and "end step" in FULL_PRIORITY_NOTE
    hub._log_file.flush()
    header = json.loads((tmp_path / f"g-9.{ME}.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert header["full_priority"] is True
    plain = Hub(real_action_stops=True, log_dir=tmp_path / "plain")
    plain.game_start(start)
    assert FULL_PRIORITY_NOTE not in [line["text"] for line in plain.log]
    plain._log_file.flush()
    header = json.loads((tmp_path / "plain" / f"g-9.{ME}.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "full_priority" not in header


# -- the advisor ---------------------------------------------------------------------------------------------------------


class Reader:
    """An advisor stand-in: it records the decisions it is asked to read and never answers."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def identity(self) -> dict:
        return {"name": "reader", "label": "Reader", "model_state_sha256": None}


@pytest.mark.parametrize("step", sorted(NEW_PRIORITY_STEPS))
def test_the_advisor_shows_no_numbers_at_a_window_its_model_never_trained_on(step: str) -> None:
    hub = full_hub(advisor=Reader())
    hub._queue_read = lambda *args, **kwargs: pytest.fail("a new window was sent to the advisor")
    with hub.cond:
        hub._begin(at([PASS, BOLT], phase=step, active=OPP, turn=4), {})
    assert hub.advice["unavailable"] == UNTRAINED_READ and "reading" not in hub.advice


@pytest.mark.parametrize("step", ENGINE_PRIORITY_STEPS)
def test_the_advisor_still_reads_the_windows_the_bot_has_too(step: str) -> None:
    hub = full_hub(advisor=Reader())
    queued: list[tuple] = []
    hub._queue_read = lambda *args, **kwargs: queued.append(args)
    with hub.cond:
        hub._begin(at([PASS, BOLT], phase=step, active=OPP, turn=4), {})
    assert hub.advice.get("reading") is True and len(queued) == 1


# -- the engine is told the person's seat ------------------------------------------------------------------------------


BASE = {"tournament_dir": "x", "engine": {"name": "mtg-kernel", "command": ["python", "engine.py", "--bridge", "b"]},
        "deck_pool": [], "matchups": [["human", "bot"]], "pairs_per_matchup": 8}


@pytest.mark.parametrize("human_first,seat", [(True, "p0"), (False, "p1")])
def test_each_picked_game_names_the_persons_seat_to_its_engine(tmp_path, human_first: bool, seat: str) -> None:
    doc = session.picked_game_config(BASE, human_deck="Burn", bot_deck="Elves", human_first=human_first,
                                     run_dir=tmp_path, opponent="bot", full_priority=True)
    assert doc["engine"]["command"] == ["python", "engine.py", "--bridge", "b", "--engine-windows-seat", seat]
    assert doc["matchups"] == ([["human", "bot"]] if human_first else [["bot", "human"]])
    assert BASE["engine"]["command"] == ["python", "engine.py", "--bridge", "b"]  # the session's own config is not edited


def test_without_the_option_the_engine_command_is_unchanged(tmp_path) -> None:
    doc = session.picked_game_config(BASE, human_deck="Burn", bot_deck="Elves", human_first=True, run_dir=tmp_path,
                                     opponent="bot")
    assert doc["engine"] == BASE["engine"]


def test_the_option_needs_the_manabrew_client(capsys) -> None:
    for argv in (["--local", "x", "--out", "y", "--full-priority"],
                 ["--local", "x", "--out", "y", "--client", "manabrew", "--keep-mana-autopass"]):
        with pytest.raises(SystemExit):
            session.main(argv)
    assert "--full-priority" in capsys.readouterr().err


def test_the_bridge_seat_follows_the_starting_seat() -> None:
    from kernel_engine_london_human_v1 import native_window_seats

    # the bridge's p0 is whoever plays first
    assert native_window_seats("p0", "p0") == ["p0"] and native_window_seats("p1", "p1") == ["p0"]
    assert native_window_seats("p0", "p1") == ["p1"] and native_window_seats("p1", "p0") == ["p1"]


# -- the scripted client can cast in one step only (for the end-to-end games) -------------------------------------------


def test_the_scripted_client_takes_an_action_only_in_the_steps_it_is_told() -> None:
    from spellbench.human.manabrew.fake_client import answer

    prompt = {"input": {"type": "chooseAction", "actions": [
        {"id": "a1", "type": "cast", "label": "Cast Lightning Bolt"}, {"id": "a2", "type": "cast", "label": "Play Mountain"}]}}
    view = {"step": "endOfTurn", "activePlayerId": "player-1", "players": [], "stack": []}
    take = dict(take=("Lightning Bolt",), passive=True, me="player-0")
    assert answer(prompt, view=view, **take) == {"type": "act", "actionId": "a1"}
    assert answer(prompt, view=view, take_steps=("opponent:endOfTurn",), **take) == {"type": "act", "actionId": "a1"}
    assert answer(prompt, view=view, take_steps=("endOfTurn",), **take) == {"type": "act", "actionId": "a1"}
    for steps in (("self:endOfTurn",), ("upkeep", "opponent:main1")):
        assert answer(prompt, view=view, take_steps=steps, **take)["type"] == "pass"
    assert answer(prompt, view={**view, "step": "main2"}, take_steps=("opponent:endOfTurn",), **take)["type"] == "pass"
    # with lands_only the land is still played where the spell is not wanted, and nothing else is cast
    held = dict(take=("Lightning Bolt",), lands_only=True, me="player-0", take_steps=("opponent:endOfTurn",))
    assert answer(prompt, view={**view, "step": "main1", "activePlayerId": "player-0"}, **held) == {"type": "act", "actionId": "a2"}
    spell_only = {"input": {"type": "chooseAction", "actions": [{"id": "a1", "type": "cast", "label": "Cast Lightning Bolt"}]}}
    assert answer(spell_only, view={**view, "step": "main1", "activePlayerId": "player-0"}, **held)["type"] == "pass"
    assert answer(spell_only, view=view, **held) == {"type": "act", "actionId": "a1"}
