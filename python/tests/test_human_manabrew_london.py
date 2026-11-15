"""The London opening through the Manabrew adapter: the mulligan and put-back prompts, the bottom plan, the pregame
view and log lines, and a scripted client's whole opening against the real relay-less host objects."""

from __future__ import annotations

import threading

import pytest

from spellbench.human import text
from spellbench.human.manabrew import prompts, view
from spellbench.human.server import Hub

ME, OPP = "p0", "p1"
SEATS = view.Seats(ME, "player-1", "player-0", {"player-1": "human", "player-0": "Basilisk 2"})
HAND = ["Mountain", "Lightning Bolt", "Chain Lightning", "Mountain", "Fireblast", "Mountain", "Burst Lightning"]


def ref(object_id: str, name: str, seat: str = ME, zone: str = "hand") -> dict:
    return {"object_id": object_id, "card_name": name, "owner_seat": seat, "controller_seat": seat, "zone": zone}


def card(i: int, name: str) -> dict:
    return {**ref(f"c{i}", name), "full_name": name, "token": False, "copy": False, "face_down": False,
            "characteristics": {"colors": [], "keywords": [], "mana_value": 1, "power": None, "toughness": None,
                                "subtypes": [], "supertypes": [], "types": ["land" if name == "Mountain" else "instant"]}}


def observation(size: int = 7, *, taken=(0, 0), pregame: bool = True) -> dict:
    return {"viewer": ME, "turn": 0 if pregame else 1, "phase_step": "pregame" if pregame else "untap",
            "active_seat": None if pregame else ME, "priority_seat": None if pregame else ME, "stack": [], "known": [],
            "passed_seats": [], "day_night": None, "pending_triggers": None,
            "players": [
                {"seat": ME, "life": 20, "mulligans_taken": taken[0], "hand_count": size, "library_count": 60 - size,
                 "hand": [card(i, HAND[i % len(HAND)]) for i in range(size)], "battlefield": [], "graveyard": [],
                 "exile": [], "mana_pool": {}, "lands_played_this_turn": 0},
                {"seat": OPP, "life": 20, "mulligans_taken": taken[1], "hand_count": 7 - taken[1],
                 "library_count": 53 + taken[1], "hand": None, "battlefield": [], "graveyard": [], "exile": [],
                 "mana_pool": {}, "lands_played_this_turn": 0}]}


def mulligan_decision(size: int = 7, taken: int = 0, *, opp_taken: int = 0, group_id: int = 0) -> dict:
    semantics = [{"kind": "mulligan", "hand_size": size, "mulligans_taken": taken, "keep": False},
                 {"kind": "mulligan", "hand_size": size, "mulligans_taken": taken, "keep": True}]
    return {"acting_seat": ME, "seat_step": 0, "group": {"group_id": group_id, "substep_index": 0, "substep_count": 1},
            "context": {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False},
            "observation": observation(size, taken=(taken, opp_taken)),
            "candidates": [{"candidate_id": i, "semantic": s, "display_text": None} for i, s in enumerate(semantics)],
            "extensions": {}}


def bottom_decision(position: int, count: int, *, hand: list[int], group_id: int = 1) -> dict:
    """The seat's ``position``-th mulligan_bottom substep of ``count``; ``hand`` are the card indexes still in hand."""
    obs = observation(len(hand), taken=(count, 0))
    obs["players"][0]["hand"] = [card(i, HAND[i % len(HAND)]) for i in hand]
    semantics = [{"kind": "order_pick", "source": None, "purpose": "mulligan_bottom",
                  "item": {"object": ref(f"c{i}", HAND[i % len(HAND)])}, "position": position, "count": count}
                 for i in hand]
    return {"acting_seat": ME, "seat_step": position, "group": {"group_id": group_id, "substep_index": position,
                                                                 "substep_count": count},
            "context": {"kind": "choice", "source": None, "purpose": "mulligan_bottom", "text": None, "rewind": False},
            "observation": obs,
            "candidates": [{"candidate_id": i, "semantic": s, "display_text": None} for i, s in enumerate(semantics)],
            "extensions": {}}


@pytest.fixture
def hub() -> Hub:
    hub = Hub()
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    return hub


def pending_of(hub: Hub, decision: dict) -> dict:
    """Runs ``hub.choose`` in a thread to the point where the person is asked, and returns the pending decision."""
    result: dict = {}

    def run() -> None:
        result["answer"] = hub.choose({"decision": decision})

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None and thread.is_alive():
            hub.cond.wait(0.05)
        pending = hub.pending
    return {"pending": pending, "thread": thread, "result": result}


def test_a_keep_or_mulligan_is_manabrews_mulligan_prompt(hub: Hub) -> None:
    started = pending_of(hub, mulligan_decision(7, 0))
    pending = started["pending"]
    assert pending["screen"] == "generic" and pending["prompt"] == "Keep or mulligan?"
    data, answer = prompts.build(pending, hub.observation, SEATS)
    assert data == {"type": "mulligan", "handCardIds": [f"c{i}" for i in range(7)], "mulliganCount": 0}
    assert answer({"type": "mulliganDecision", "keep": True}) == ("answer", 1)
    assert answer({"type": "mulliganDecision", "keep": False}) == ("answer", 0)
    with pytest.raises(ValueError):
        answer({"type": "mulliganDecision"})
    assert hub.answer_with(pending["seq"], 1) is None
    started["thread"].join(timeout=5)
    assert started["result"]["answer"] == 1


def test_the_mulligan_count_and_hand_follow_the_decision(hub: Hub) -> None:
    started = pending_of(hub, mulligan_decision(6, 1))
    data, _ = prompts.build(started["pending"], hub.observation, SEATS)
    assert data["mulliganCount"] == 1 and len(data["handCardIds"]) == 6
    hub.answer_with(started["pending"]["seq"], 1)
    started["thread"].join(timeout=5)


def test_a_mulligan_bottom_group_is_one_put_back_prompt_and_replays_the_picks_in_click_order(hub: Hub) -> None:
    hand = list(range(7))
    started = pending_of(hub, bottom_decision(0, 2, hand=hand))
    pending = started["pending"]
    assert pending["screen"] == "bottom"
    data, answer = prompts.build(pending, hub.observation, SEATS)
    assert data["type"] == "mulliganPutBack" and data["count"] == 2
    assert data["handCardIds"] == [f"c{i}" for i in hand] and [c["id"] for c in data["cards"]] == data["handCardIds"]
    assert [c["identity"]["name"] for c in data["cards"]] == [HAND[i % len(HAND)] for i in hand]
    # Wrong counts and foreign ids are refused before they reach the engine.
    for bad in (["c1"], ["c1", "c1"], ["c1", "zzz"], ["c1", "c2", "c3"]):
        with pytest.raises(ValueError):
            answer({"type": "mulliganPutBackDecision", "cardIds": bad})
    how, plan = answer({"type": "mulliganPutBackDecision", "cardIds": ["c5", "c2"]})
    assert how == "plan" and plan == {"kind": "bottom", "cards": ["c5", "c2"]}
    assert hub.plan_with(pending["seq"], plan) is None
    started["thread"].join(timeout=5)
    assert started["result"]["answer"] == 5  # candidate of c5: the first click is bottomed first
    # The second substep is answered from the plan with no prompt: position 1 names c2.
    rest = [i for i in hand if i != 5]
    assert hub.choose({"decision": bottom_decision(1, 2, hand=rest)}) == rest.index(2)
    assert hub.pending is None


def test_a_put_back_that_is_not_the_visible_hand_falls_back_to_a_selection(hub: Hub) -> None:
    decision = bottom_decision(0, 1, hand=list(range(7)))
    decision["observation"]["players"][0]["hand"].pop()  # the offered cards are not the whole visible hand
    started = pending_of(hub, decision)
    data, answer = prompts.build(started["pending"], hub.observation, SEATS)
    assert data["type"] == "chooseFromSelection" and len(data["options"]) == 7
    assert data["options"][0]["label"].startswith("Bottom ")
    assert answer({"chosenIndices": [3]}) == ("answer", 3)
    hub.answer_with(started["pending"]["seq"], 3)
    started["thread"].join(timeout=5)


def test_the_pregame_view_shows_the_own_hand_and_only_a_count_of_the_other(hub: Hub) -> None:
    gv = view.game_view(observation(7, taken=(0, 2)), SEATS, "g1")
    zones = {(z["zone"], z["ownerId"]): z for z in gv["zones"]}
    assert [c["identity"]["name"] for c in zones[("hand", "player-1")]["cards"]] == HAND
    assert zones[("hand", "player-0")]["count"] == 5
    assert all(c == {"visibility": "hidden", "id": c["id"]} for c in zones[("hand", "player-0")]["cards"])
    assert gv["turn"] == 0 and gv["step"] == "upkeep"
    # No active or priority seat in pregame: the view names the person's seat, never the string "None".
    assert gv["activePlayerId"] == "player-1" and gv["priorityPlayerId"] == "player-1"


def test_the_log_counts_the_mulligans_of_both_seats_and_the_keeps(hub: Hub) -> None:
    hub._absorb(mulligan_decision(7, 0), {})
    hub._absorb(mulligan_decision(6, 1, opp_taken=2), {})
    lines = [(entry["side"], entry["text"]) for entry in hub.log]
    assert any(side == "opp" and "Opponent takes a mulligan" in line and "2 taken" in line for side, line in lines)
    assert any(side == "you" and "You take a mulligan" in line and "1 taken" in line for side, line in lines)
    game = mulligan_decision(6, 1, opp_taken=2)
    game["observation"].update(turn=1, phase_step="untap", active_seat=ME, priority_seat=ME)
    hub._absorb(game, {})
    final = [line for _, line in [(e["side"], e["text"]) for e in hub.log]]
    assert "Opponent keeps 5 cards" in final and "You keep 6 cards" in final
    # Nothing in the log names a card of the other seat.
    assert not any("Opponent" in line and any(name in line for name in HAND) for line in final)


def test_the_candidate_texts_name_the_bottom_and_the_choice() -> None:
    bottom = bottom_decision(0, 2, hand=[0, 1, 2])["candidates"][1]["semantic"]
    assert text.candidate(bottom, ME) == "Bottom Lightning Bolt"
    assert text.candidate({"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True}, ME) == "Keep"
    assert "Mulligan" in text.candidate({"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": False}, ME)
    prompt = text.prompt(bottom_decision(0, 2, hand=[0, 1, 2]), ME)
    assert prompt.startswith("Put a card on the bottom of your library") and "1 of 2" in prompt


def test_conceding_at_the_keep_or_mulligan_prompt_ends_the_game_and_refuses_the_open_decision(hub: Hub) -> None:
    from spellbench.human.server import Conceded
    errors: list[BaseException] = []

    def run() -> None:
        try:
            hub.choose({"decision": mulligan_decision(7, 0)})
        except BaseException as exc:  # noqa: BLE001 - the thread reports what the engine side would see
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    assert hub.concede("conceded") is True
    thread.join(timeout=5)
    assert errors and isinstance(errors[0], Conceded)
    assert hub.game_over["reason"] == "conceded" and hub.results[-1]["result"] == "loss"
    assert hub.concede("conceded") is False  # a second concession changes nothing


def test_a_lost_connection_at_the_put_back_prompt_ends_the_game_the_same_way(hub: Hub) -> None:
    from spellbench.human.server import Conceded
    errors: list[BaseException] = []

    def run() -> None:
        try:
            hub.choose({"decision": bottom_decision(0, 1, hand=list(range(7)))})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    assert hub.concede("connection_lost") is True
    thread.join(timeout=5)
    assert errors and isinstance(errors[0], Conceded)
    assert hub.game_over["reason"] == "connection_lost"
