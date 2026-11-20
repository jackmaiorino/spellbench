"""Full priority for a person on the Manabrew path (``python -m spellbench.human --full-priority``): the engine gives
the person's seat every priority window the rules have, so a stop the client sets in upkeep, draw, beginning of combat,
combat damage, end of combat or the end step is taken in that step; a window with only mana abilities goes to the client
(its AUTOPASS countdown or Full control answers it); a window with nothing but passing is still passed by the session;
the advisor shows no numbers at a priority window in those six steps or with the person's own object on top of the
stack (it still reads a second action in one combat priority round, which the bot's surface also lacks); and each
game's engine is told the person's seat. Without the option nothing changes. Display and human flow only: the bot's seat sees none of this."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spellbench.human import session
from spellbench.human.server import (ENGINE_PRIORITY_STEPS, FULL_PRIORITY_STEPS, NEW_PRIORITY_STEPS, OWN_STACK_READ,
                                     STEP_ORDER, UNTRAINED_READ, Hub, reachable_step)

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


def test_a_stop_whose_step_comes_up_with_nothing_to_do_is_used_up_there() -> None:
    """The step of a hold is reached even when the person can only pass in it: the hold ends there and the next
    window with something to do is asked, instead of the hold running on to the same step of a later turn."""
    hub = full_hub()
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", turn=3), until(ME, "upkeep", through=True))
    for step in FULL_PRIORITY_STEPS:
        assert how(hub, at([PASS], phase=step, active=OPP, turn=4)) == "single", step
    assert hub.hold is not None
    assert how(hub, at([PASS], phase="upkeep", active=ME, turn=5)) == "single"  # my upkeep: nothing but passing
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="draw", active=ME, turn=5)) == "human"
    # the same with only mana at the stop, passed by the session
    hub = full_hub(client_autopass=False)
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", turn=3), until(ME, "upkeep", through=True))
    assert how(hub, at([PASS, MANA], phase="upkeep", active=ME, turn=5)) == "auto_pass"
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="upkeep", active=OPP, turn=6)) == "human"


def test_a_stop_reached_after_turns_of_nothing_but_passing_is_still_reached_in_its_own_turn() -> None:
    hub = full_hub()
    pass_priority(hub, at([PASS, BOLT], phase="postcombat_main", active=OPP, turn=2), until(OPP, "upkeep"))
    assert how(hub, at([PASS], phase="end_step", active=OPP, turn=2)) == "single"  # behind the stop: their NEXT turn
    for step in FULL_PRIORITY_STEPS:
        assert how(hub, at([PASS], phase=step, active=ME, turn=3)) == "single", step
    assert hub.hold is not None
    assert how(hub, at([PASS], phase="upkeep", active=OPP, turn=4)) == "single"  # reached, nothing to do
    assert hub.hold is None
    assert how(hub, at([PASS, BOLT], phase="draw", active=OPP, turn=4)) == "human"


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


@pytest.mark.parametrize("opposing_below", [False, True])
def test_the_advisor_shows_no_numbers_while_the_persons_own_object_is_on_top_of_the_stack(opposing_below: bool) -> None:
    from spellbench.human import text

    stack = [MY_SPELL] if not opposing_below else (
        [MY_SPELL, SPELL_ON_STACK] if text.STACK_TOP_FIRST else [SPELL_ON_STACK, MY_SPELL])
    hub = full_hub(advisor=Reader())
    hub._queue_read = lambda *args, **kwargs: pytest.fail("an own-stack window was sent to the advisor")
    request = at([PASS, BOLT], phase="precombat_main", stack=stack)
    assert text.stack_top(request["observation"]["stack"])["controller_seat"] == ME
    with hub.cond:
        hub._begin(request, {})
    assert hub.advice["unavailable"] == OWN_STACK_READ


def test_the_advisor_reads_a_response_to_the_opponents_spell_and_everything_without_the_option() -> None:
    queued: list[tuple] = []
    hub = full_hub(advisor=Reader())
    hub._queue_read = lambda *args, **kwargs: queued.append(args)
    with hub.cond:
        hub._begin(at([PASS, BOLT], phase="precombat_main", active=OPP, turn=4, stack=[SPELL_ON_STACK]), {})
    assert hub.advice.get("reading") is True and len(queued) == 1
    plain = Hub(real_action_stops=True, advisor=Reader())  # no full priority: the surface has no such window to mark
    plain.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    plain._queue_read = lambda *args, **kwargs: queued.append(args)
    with plain.cond:
        plain._begin(at([PASS, BOLT], phase="precombat_main", stack=[MY_SPELL]), {})
    assert plain.advice.get("reading") is True and len(queued) == 2


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


# -- cards going to the person's own graveyard are ordered for them ------------------------------------------------------


def test_each_picked_game_asks_its_engine_to_settle_graveyard_order(tmp_path) -> None:
    doc = session.picked_game_config(BASE, human_deck="Spy", bot_deck="Spy", human_first=False, run_dir=tmp_path,
                                     opponent="bot", auto_graveyard_order=True)
    assert doc["engine"]["command"] == ["python", "engine.py", "--bridge", "b", "--auto-graveyard-order"]
    both = session.picked_game_config(BASE, human_deck="Spy", bot_deck="Spy", human_first=True, run_dir=tmp_path,
                                      opponent="bot", full_priority=True, auto_graveyard_order=True)
    assert both["engine"]["command"][-3:] == ["--engine-windows-seat", "p0", "--auto-graveyard-order"]


def test_the_graveyard_order_option_needs_the_manabrew_client_and_is_said_in_every_game(tmp_path, capsys) -> None:
    import json

    from spellbench.human.server import GRAVEYARD_ORDER_NOTE

    with pytest.raises(SystemExit):
        session.main(["--local", "x", "--out", "y", "--auto-graveyard-order"])
    assert "--auto-graveyard-order" in capsys.readouterr().err
    start = {"game_id": "g-7", "seat": ME, "own_deck": {"name": "Spy"}, "opponent_deck": {"name": "Spy"}}
    hub = Hub(real_action_stops=True, auto_graveyard_order=True, log_dir=tmp_path)
    hub.game_start(start)
    assert [line["text"] for line in hub.log].count(GRAVEYARD_ORDER_NOTE) == 1
    hub._log_file.flush()
    header = json.loads((tmp_path / f"g-7.{ME}.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert header["auto_graveyard_order"] is True and "full_priority" not in header
    plain = Hub(real_action_stops=True)
    plain.game_start(start)
    assert GRAVEYARD_ORDER_NOTE not in [line["text"] for line in plain.log]


def test_a_game_with_a_reader_says_both_players_order_and_why(tmp_path) -> None:
    from spellbench.human.server import GRAVEYARD_ORDER_NOTE

    start = {"game_id": "g-8", "seat": ME, "own_deck": {"name": "X"}, "opponent_deck": {"name": "Y"}}
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.set_graveyard_readers(["Gurmag Angler"])
    hub.game_start(start)
    texts = [line["text"] for line in hub.log]
    assert GRAVEYARD_ORDER_NOTE not in texts
    assert any("matters in this game (Gurmag Angler)" in line and "one step" in line for line in texts)


def test_the_session_finds_no_reader_in_any_pair_of_the_training_decks() -> None:
    from spellbench.human import graveyard_order
    from spellbench.human.manabrew import decks

    for a in decks.ALL_DECKS:
        for b in decks.ALL_DECKS:
            assert graveyard_order.readers(decks.card_names(a) + decks.card_names(b)) == [], (a, b)
    assert "Balustrade Spy" in decks.card_names("Spy")


def test_the_scripted_clients_own_stops_reach_its_pass() -> None:
    """``--self-stops`` used to be read and dropped: every pass aimed at the default stops."""
    from spellbench.human.manabrew.fake_client import answer

    prompt = {"input": {"type": "chooseAction", "actions": []}}
    players = [{"id": "player-0", "status": "playing"}, {"id": "player-1", "status": "playing"}]
    view = {"step": "endOfTurn", "activePlayerId": "player-1", "players": players, "stack": []}
    default = answer(prompt, view=view, me="player-0", pass_mode="stops")
    assert default["until"] == {"playerId": "player-0", "phase": "main1", "throughCombat": False}
    mine = answer(prompt, view=view, me="player-0", pass_mode="stops", self_stops=("upkeep", "main1"))
    assert mine["until"] == {"playerId": "player-0", "phase": "upkeep", "throughCombat": False}


# -- the order of the cards one look sends to the graveyard or the hand ------------------------------------------------


def look_card(name: str, object_id: str) -> dict:
    return {"object_id": object_id, "card_name": name, "zone": "library", "owner_seat": ME, "controller_seat": ME}


def arrange(card: dict, destinations: list[str], index: int, count: int, group: int = 7) -> dict:
    d = decision([])
    d["candidates"] = [{"candidate_id": i, "display_text": None, "semantic": {
        "kind": "arrange_card", "source": None, "purpose": "dig", "card": card, "card_index": index, "card_count": count,
        "destination": destination}} for i, destination in enumerate(destinations)]
    d["context"] = {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False}
    d["group"] = {"group_id": group, "substep_index": index, "substep_count": 2 * count - 1}
    return d


def order(cards: list[dict], position: int, count: int, group: int = 7, purpose: str = "arrangement") -> dict:
    d = decision([])
    d["candidates"] = [{"candidate_id": i, "display_text": None, "semantic": {
        "kind": "order_pick", "source": None, "purpose": purpose, "item": {"object": card}, "position": position,
        "count": count}} for i, card in enumerate(cards)]
    d["context"] = {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False}
    d["group"] = {"group_id": group, "substep_index": count + position, "substep_count": 2 * count - 1}
    return d


def answer_now(hub: Hub, request: dict, candidate_id: int | None = None) -> str:
    """Take a decision in as the session does; one the person would be asked is answered with ``candidate_id``."""
    with hub.cond:
        how, auto = hub._begin(request, {})
        if auto is None:
            assert candidate_id is not None, "the person was asked"
            hub.pending = None
            how, auto = "human", candidate_id
        hub._conclude(request, how, auto, None, 0.0)
    return how


WALL, WILDLING, STAMPEDE, SPY = (look_card("Wall of Roots", "o-w"), look_card("Sagu Wildling", "o-s"),
                                 look_card("Lead the Stampede", "o-l"), look_card("Balustrade Spy", "o-b"))


def winding_way(hub: Hub) -> list[str]:
    """Winding Way: three creatures to the hand, the rest to the graveyard, then the order of all four."""
    hows = [answer_now(hub, arrange(WALL, ["hand"], 0, 4)), answer_now(hub, arrange(WILDLING, ["hand"], 1, 4)),
            answer_now(hub, arrange(STAMPEDE, ["graveyard"], 2, 4)), answer_now(hub, arrange(SPY, ["hand"], 3, 4))]
    hows.append(answer_now(hub, order([STAMPEDE], 0, 4)))                    # the graveyard's one card
    hows.append(answer_now(hub, order([SPY, WILDLING, WALL], 1, 4), 0))      # the three for the hand
    hows.append(answer_now(hub, order([WILDLING, WALL], 2, 4), 0))
    return hows


def test_the_order_of_cards_one_look_sends_to_the_graveyard_or_hand_is_not_asked() -> None:
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    assert winding_way(hub) == ["single"] * 5 + ["auto_order", "auto_order"]
    assert hub.pending is None
    assert not [line for line in hub.log if "You choose" in line["text"]]  # the session's pick is not the person's


def test_without_the_option_the_same_look_asks_its_order() -> None:
    hub = Hub(real_action_stops=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    assert winding_way(hub) == ["single"] * 5 + ["human", "human"]


def test_the_order_of_cards_going_back_on_a_library_is_always_the_persons() -> None:
    """Lead the Stampede: the rest goes to the bottom in an order the person chooses. Also asked: an ordering whose
    cards have no recorded destination, one of another group, and any ordering that is not an arrangement's."""
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    answer_now(hub, arrange(WALL, ["hand", "bottom"], 0, 3), 1)
    answer_now(hub, arrange(WILDLING, ["hand", "bottom"], 1, 3), 1)
    answer_now(hub, arrange(SPY, ["hand", "bottom"], 2, 3), 0)
    assert answer_now(hub, order([WILDLING, WALL], 0, 3), 0) == "human"       # two for the bottom
    assert answer_now(hub, order([WILDLING, WALL], 0, 3, group=8), 0) == "human"  # another group: nothing recorded
    assert answer_now(hub, order([WILDLING, WALL], 0, 2, purpose="library_top"), 0) == "human"
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    assert answer_now(hub, order([SPY, WALL], 0, 4), 0) == "human"            # no destinations known at all
    mixed = Hub(real_action_stops=True, auto_graveyard_order=True)
    mixed.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    answer_now(mixed, arrange(WALL, ["graveyard", "bottom"], 0, 2), 0)
    answer_now(mixed, arrange(SPY, ["graveyard", "bottom"], 1, 2), 1)
    assert answer_now(mixed, order([SPY, WALL], 0, 2), 0) == "human"          # a card of it goes to the library


def test_in_a_game_with_a_reader_the_looks_graveyard_order_is_asked_and_the_hand_still_is_not() -> None:
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    hub.set_graveyard_readers(["Gurmag Angler"])
    answer_now(hub, arrange(WALL, ["hand", "graveyard"], 0, 4), 0)
    answer_now(hub, arrange(WILDLING, ["hand", "graveyard"], 1, 4), 0)
    answer_now(hub, arrange(STAMPEDE, ["hand", "graveyard"], 2, 4), 1)
    answer_now(hub, arrange(SPY, ["hand", "graveyard"], 3, 4), 1)
    assert answer_now(hub, order([SPY, STAMPEDE], 0, 4), 0) == "human"          # two for the graveyard: asked
    assert answer_now(hub, order([STAMPEDE], 1, 4)) == "single"
    assert answer_now(hub, order([WILDLING, WALL], 2, 4), 0) == "auto_order"    # the hand: never asked


# -- one step for a card ordering the person is asked ------------------------------------------------------------------


MILLED = [look_card("Lotleth Giant", "o-g"), look_card("Dread Return", "o-d"), look_card("Balustrade Spy", "o-b")]


def mill_order(cards: list[dict], position: int, count: int = 3, group: int = 9) -> dict:
    return order(cards, position, count, group=group, purpose="other")


def test_a_card_ordering_is_one_reorder_step_and_its_order_answers_every_substep() -> None:
    from spellbench.human.manabrew import prompts

    from test_human_flow import SEATS

    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    hub.set_graveyard_readers(["Gurmag Angler"])
    first = mill_order(MILLED, 0)
    with hub.cond:
        hub._begin(first, {})
    pending = hub.pending
    assert pending["screen"] == "order" and "put into the graveyard first" in pending["hint"]
    data, respond = prompts.build(pending, first["observation"], SEATS)
    assert data["type"] == "reorder" and [item["id"] for item in data["items"]] == ["o-g", "o-d", "o-b"]
    with pytest.raises(prompts.Rejected):
        respond({"type": "reorderDecision", "orderedIds": ["o-b", "o-g"]})               # not every card
    how, plan = respond({"type": "reorderDecision", "orderedIds": ["o-b", "o-g", "o-d"]})
    assert how == "plan" and plan == {"kind": "order", "cards": ["o-b", "o-g", "o-d"]}
    assert hub.plan_with(pending["seq"], plan) is None
    assert hub.answer == 2                                                                 # Balustrade Spy first
    hub.pending = None
    second = mill_order([MILLED[0], MILLED[1]], 1)
    with hub.cond:
        assert hub._automatic(second) == ("plan", 0)                                       # then Lotleth Giant


def test_a_library_order_is_one_step_with_its_own_meaning_and_nothing_changes_without_the_option() -> None:
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    answer_now(hub, arrange(WALL, ["hand", "bottom"], 0, 3), 1)
    answer_now(hub, arrange(WILDLING, ["hand", "bottom"], 1, 3), 1)
    answer_now(hub, arrange(SPY, ["hand", "bottom"], 2, 3), 0)
    request = order([WILDLING, WALL], 0, 3)
    with hub.cond:
        hub._begin(request, {})
    assert hub.pending["screen"] == "order" and "closest to the top of the library" in hub.pending["hint"]
    plain = Hub(real_action_stops=True)
    plain.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    with plain.cond:
        plain._begin(mill_order(MILLED, 0), {})
    assert plain.pending["screen"] == "generic"


def test_trigger_orders_and_put_backs_keep_their_own_screens() -> None:
    hub = Hub(real_action_stops=True, auto_graveyard_order=True)
    hub.game = {"game_id": "g-1", "seat": ME, "started": 0.0}
    triggers = order(MILLED, 0, 3, purpose="triggers")
    for c in triggers["candidates"]:
        c["semantic"]["item"] = {"trigger": {"source": None, "source_name": "x", "ability_index": 0,
                                             "event_objects": [], "instance": c["candidate_id"], "label": None}}
    with hub.cond:
        hub._begin(triggers, {})
    assert hub.pending["screen"] == "generic"


def test_the_scripted_client_keeps_the_offered_order_of_a_reorder_prompt() -> None:
    from spellbench.human.manabrew.fake_client import answer

    prompt = {"input": {"type": "reorder", "presentation": {"title": "Order"}, "items": [{"id": "o-b"}, {"id": "o-g"}]}}
    assert answer(prompt) == {"type": "reorderDecision", "orderedIds": ["o-b", "o-g"]}
