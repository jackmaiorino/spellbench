"""Priority stops on the Manabrew path: the person gets every priority at which they have a legal action besides
passing and mana abilities, in any step of either turn and on any stack; a priority with nothing else to do is passed
for them. The rule reads the engine's own candidate list. Display and human flow only: the engine and the bot never
see any of this."""

from __future__ import annotations

import glob
import gzip
import json
import os
import threading
from collections import Counter
from pathlib import Path

import pytest

from spellbench.human import text
from spellbench.human.manabrew import prompts, view
from spellbench.human.manabrew.host import Bridge
from spellbench.human.server import DEFAULT_STOPS, PHASE_STEPS, Hub, real_actions

ME, OPP = "p0", "p1"
PASS = {"kind": "pass"}
MANA = {"kind": "activate_mana_ability", "source": {"object_id": "o-i", "card_name": "Island", "zone": "battlefield"},
        "ability_index": 0, "mana_choice": "U", "cost_target": None}


def ref(object_id: str, name: str, seat: str = ME, zone: str = "battlefield") -> dict:
    return {"object_id": object_id, "card_name": name, "owner_seat": seat, "controller_seat": seat, "zone": zone}


BOLT = {"kind": "cast_spell", "source": ref("o-b", "Lightning Bolt", zone="hand"), "method": "normal"}
NINJA = {"kind": "activate_ability", "source": ref("o-n", "Ninja of the Deep Hours", zone="hand"), "ability_index": 1}
LAND = {"kind": "play_land", "source": ref("o-l", "Island", zone="hand")}
SPELL_ON_STACK = {**ref("o-s", "Counterspell", OPP, "stack"), "stack_kind": "spell", "targets": []}
MY_SPELL = {**ref("o-m", "Lightning Bolt", ME, "stack"), "stack_kind": "spell", "targets": []}


def decision(candidates: list[dict], *, phase: str = "precombat_main", active: str = ME, stack: list | None = None) -> dict:
    return {"acting_seat": ME, "seat_step": 0, "group": {"group_id": 0, "substep_index": 0, "substep_count": 1},
            "context": {"kind": "priority", "source": None, "purpose": None, "text": None, "rewind": False},
            "observation": {"viewer": ME, "turn": 3, "phase_step": phase, "active_seat": active, "priority_seat": ME,
                            "players": [{"seat": ME, "life": 20, "battlefield": []},
                                        {"seat": OPP, "life": 20, "battlefield": []}],
                            "stack": stack or [], "known": []},
            "candidates": [{"candidate_id": i, "semantic": s, "display_text": None} for i, s in enumerate(candidates)],
            "extensions": {}}


def new_hub(*, real: bool) -> Hub:
    hub = Hub(real_action_stops=real)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    return hub


def how(hub: Hub, request: dict) -> str:
    """How the decision would be answered without the person: ``auto_pass`` or ``human`` (they are asked)."""
    hub._absorb(request, {})
    return hub._automatic(request)[0]


# -- the rule ----------------------------------------------------------------------------------------------------------


def test_real_actions_are_everything_but_passing_and_mana() -> None:
    candidates = decision([PASS, MANA, BOLT, NINJA, LAND])["candidates"]
    assert [c["semantic"]["kind"] for c in real_actions(candidates)] == ["cast_spell", "activate_ability", "play_land"]
    assert real_actions(decision([PASS, MANA])["candidates"]) == []
    assert real_actions(None) == []


@pytest.mark.parametrize("active", [ME, OPP])
@pytest.mark.parametrize("step", PHASE_STEPS)
def test_a_real_action_is_offered_in_every_step_of_either_turn(step: str, active: str) -> None:
    hub = new_hub(real=True)
    assert how(hub, decision([PASS, MANA, NINJA], phase=step, active=active)) == "human"
    assert how(hub, decision([PASS, MANA, BOLT], phase=step, active=active)) == "human"


@pytest.mark.parametrize("active", [ME, OPP])
@pytest.mark.parametrize("step", PHASE_STEPS)
def test_a_turn_with_no_real_options_asks_nothing(step: str, active: str) -> None:
    hub = new_hub(real=True)
    assert how(hub, decision([PASS], phase=step, active=active)) == "single"  # the lone pass: never asked
    assert how(hub, decision([PASS, MANA, MANA], phase=step, active=active)) == "auto_pass"
    assert how(hub, decision([PASS, MANA], phase=step, active=active, stack=[SPELL_ON_STACK])) == "auto_pass"


def test_any_stack_offers_a_real_action_and_otherwise_passes() -> None:
    hub = new_hub(real=True)
    for stack in ([SPELL_ON_STACK], [MY_SPELL], [MY_SPELL, SPELL_ON_STACK]):
        assert how(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=stack)) == "human"
        assert how(hub, decision([PASS, MANA], phase="end_step", active=OPP, stack=stack)) == "auto_pass"


def test_the_play_page_keeps_its_own_stops() -> None:
    """Without the option (the play page) only the S panel's stops ask: nothing changes there."""
    hub = new_hub(real=False)
    for step in PHASE_STEPS:
        for active in (ME, OPP):
            stops = DEFAULT_STOPS[f"{'own' if active == ME else 'opp'}_{step}"]
            assert how(hub, decision([PASS, NINJA], phase=step, active=active)) == ("human" if stops else "auto_pass")
    assert how(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=[SPELL_ON_STACK])) == "human"
    assert how(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=[MY_SPELL])) == "auto_pass"


def test_single_candidates_and_plans_are_unchanged() -> None:
    hub = new_hub(real=True)
    assert hub._automatic(decision([BOLT]))[0] == "single"  # the only candidate (no pass): nothing to choose


# -- passing to the end of the turn --------------------------------------------------------------------------------------


def waiting_priority(hub: Hub, request: dict) -> threading.Thread:
    """Starts ``hub.choose`` on a priority decision in a thread; returns it once the decision is pending."""
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(hub.choose({"decision": request})), daemon=True)
    thread.result = result  # type: ignore[attr-defined]
    thread.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    return thread


def test_pass_turn_passes_the_rest_of_the_turn_but_not_an_opponents_spell() -> None:
    hub = new_hub(real=True)
    first = decision([PASS, BOLT], phase="precombat_main", active=OPP)
    thread = waiting_priority(hub, first)
    assert hub.pass_turn(hub.pending["seq"]) is None
    thread.join(5)
    assert thread.result == [0] and hub.skip is not None
    assert how(hub, decision([PASS, BOLT], phase="declare_attackers", active=OPP)) == "auto_pass"
    assert how(hub, decision([PASS, NINJA], phase="end_step", active=OPP)) == "auto_pass"
    assert how(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=[SPELL_ON_STACK])) == "human"
    assert how(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=[MY_SPELL])) == "auto_pass"
    # the next turn asks again
    later = decision([PASS, NINJA], phase="declare_blockers", active=ME)
    later["observation"]["turn"] = 4
    assert how(hub, later) == "human" and hub.skip is None


def test_pass_turn_is_refused_for_a_decision_that_is_not_open() -> None:
    hub = new_hub(real=True)
    assert hub.pass_turn(7) == "stale decision"


def test_end_turn_on_a_stack_passes_until_the_stack_is_empty() -> None:
    hub = new_hub(real=True)
    first = decision([PASS, BOLT], phase="end_step", active=OPP, stack=[SPELL_ON_STACK])
    thread = waiting_priority(hub, first)
    assert hub.pass_turn(hub.pending["seq"], exhaust_stack=True) is None
    thread.join(5)
    assert thread.result == [0]
    deeper = decision([PASS, BOLT], phase="end_step", active=OPP, stack=[SPELL_ON_STACK, SPELL_ON_STACK])
    assert hub.choose({"decision": deeper}) == 0  # passed without asking: they asked to pass the whole stack
    empty = decision([PASS, BOLT], phase="end_step", active=OPP)
    thread = waiting_priority(hub, empty)  # the stack is empty: asked again, and a new stack is asked about too
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    assert hub.exhaust_stack is False
    another = {**SPELL_ON_STACK, "object_id": "o-s2"}  # a new object (the same one at the same position is not asked twice)
    thread = waiting_priority(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=[another]))
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)


def test_the_decision_log_tells_how_each_priority_was_answered(tmp_path: Path) -> None:
    hub = Hub(log_dir=tmp_path, real_action_stops=True)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    assert hub.choose({"decision": decision([PASS, MANA], phase="upkeep")}) == 0
    thread = waiting_priority(hub, decision([PASS, NINJA], phase="declare_blockers"))
    hub.answer_with(hub.pending["seq"], 1)
    thread.join(5)
    lines = [json.loads(line) for line in (tmp_path / "g-1.p0.jsonl").read_text().splitlines()]
    assert [(r["how"], r["phase_step"]) for r in lines if r["kind"] == "decision"] == [
        ("auto_pass", "upkeep"), ("human", "declare_blockers")]


# -- what the Manabrew client sends ---------------------------------------------------------------------------------------


def pending_priority(candidates: list[dict], *, phase: str = "declare_blockers", active: str = ME) -> dict:
    hub = new_hub(real=True)
    return {"seq": 5, "prompt": text.prompt(decision(candidates, phase=phase, active=active), ME),
            "context": {"kind": "priority"}, "group": {}, "screen": "generic",
            "candidates": [{"id": i, "kind": s["kind"], "text": text.candidate(s, ME), "semantic": s}
                           for i, s in enumerate(candidates)]}


def test_the_clients_pass_buttons_map_to_the_right_answers() -> None:
    pending = pending_priority([PASS, MANA, NINJA])
    seats = view.Seats(ME, "player-1", "player-0", {"player-1": "human", "player-0": "Basilisk 2"})
    data, answer = prompts.build(pending, {}, seats)
    assert data["type"] == "chooseAction"
    assert [a["id"] for a in data["actions"]] == ["1", "2"]  # the mana ability and the ninjutsu activation
    ninja = data["actions"][1]
    assert ninja["type"] == "activateAbility" and ninja["cardId"] == "o-n" and not ninja["isManaAbility"]
    assert ninja["description"] == "Activate Ninja of the Deep Hours (ability 2) (from your hand)"
    assert answer({"type": "pass", "exhaustStack": False}) == ("answer", 0)  # the pass button and Space
    until = {"playerId": "player-1", "phase": "main2", "throughCombat": False}
    assert answer({"type": "pass", "until": until, "exhaustStack": False}) == (
        "pass", {"until": {"seat": ME, "step": "postcombat_main", "through_combat": False}, "exhaust_stack": False})
    assert answer({"type": "pass", "until": {**until, "throughCombat": True}, "exhaustStack": False}) == (
        "pass", {"until": {"seat": ME, "step": "postcombat_main", "through_combat": True}, "exhaust_stack": False})
    assert answer({"type": "pass", "exhaustStack": True}) == ("pass", {"until": None, "exhaust_stack": True})  # on a stack
    assert answer({"type": "act", "actionId": "2"}) == ("answer", 2)


def test_the_hosts_end_turn_reaches_the_hub_and_a_plain_pass_does_not() -> None:
    end_turn = {"playerId": "player-1", "phase": "endOfTurn", "throughCombat": True}
    hub = new_hub(real=True)
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    sent: list[dict] = []
    bridge.host = type("Relay", (), {"send": staticmethod(sent.append)})()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = view.Seats(ME, "player-0", "player-1", {"player-0": "human", "player-1": "Basilisk 2"})
    for n, (pass_output, expect_skip) in enumerate((({"type": "pass", "exhaustStack": False}, False),
                                                    ({"type": "pass", "until": end_turn, "exhaustStack": False}, True))):
        request = decision([PASS, NINJA], phase="declare_blockers")
        request["observation"]["turn"] = 3 + n  # (a position the person already passed at is not asked again)
        thread = waiting_priority(hub, request)
        bridge._push(hub.state())  # the prompt reaches the client
        assert any(m.get("state", {}).get("kind") == "prompt" for m in sent)
        sent.clear()
        bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": hub.pending["seq"],
                                      "action": {"type": "chooseAction", "output": pass_output}})
        thread.join(5)
        assert thread.result == [0] and (hub.hold is not None) is expect_skip
        hub.hold = None
        bridge.prompt = None
    assert not [m for m in sent if m.get("state", {}).get("kind") == "error"]


# -- why the person has priority ------------------------------------------------------------------------------------------


def test_the_prompt_says_whose_turn_and_which_step_outside_the_main_phase() -> None:
    assert text.prompt(decision([PASS, BOLT], phase="declare_blockers", active=ME), ME) == (
        "Your priority in your declare blockers step")
    assert text.prompt(decision([PASS, BOLT], phase="declare_attackers", active=OPP), ME) == (
        "Your priority in the opponent's declare attackers step")
    assert text.prompt(decision([PASS, BOLT], phase="end_step", active=OPP), ME) == (
        "Your priority in the opponent's end step")
    assert text.prompt(decision([PASS, BOLT], phase="precombat_main", active=ME), ME) == "Your priority (Main 1)"
    assert text.prompt(decision([PASS, BOLT], phase="precombat_main", active=OPP), ME) == (
        "Your priority in the opponent's first main phase")


def test_the_log_says_why_the_person_has_priority_and_what_they_can_do() -> None:
    hub = new_hub(real=True)
    thread = waiting_priority(hub, decision([PASS, MANA, NINJA, BOLT], phase="declare_blockers"))
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    thread = waiting_priority(hub, decision([PASS, BOLT], phase="end_step", active=OPP, stack=[SPELL_ON_STACK]))
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    thread = waiting_priority(hub, decision([PASS, BOLT], phase="precombat_main", active=ME))
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    notes = [line["text"] for line in hub.log if line["text"].startswith("Your priority")]
    assert notes == [
        "Your priority in your declare blockers step. You can: Activate Ninja of the Deep Hours (ability 2); Cast Lightning Bolt",
        "Your priority in the opponent's end step, Opp: Counterspell on the stack. You can: Cast Lightning Bolt"]


def test_the_play_page_log_gets_no_such_note() -> None:
    hub = new_hub(real=False)
    thread = waiting_priority(hub, decision([PASS, BOLT], phase="precombat_main", active=OPP, stack=[SPELL_ON_STACK]))
    hub.answer_with(hub.pending["seq"], 0)
    thread.join(5)
    assert not [line for line in hub.log if line["text"].startswith("Your priority")]


# -- the owner's recorded games -------------------------------------------------------------------------------------------

ROOT = Path(os.environ.get("SPELLBENCH_HUMAN_SESSION", "E:/artifacts/chains-20261107-human-interim"))
LOGS = sorted(glob.glob(str(ROOT / "decision-logs" / "*.jsonl")))
recorded = pytest.mark.skipif(not LOGS or not (ROOT / "engine-records").exists(),
                              reason="the recorded human sessions are not on this machine")


def _record(game_id: str) -> list[dict]:
    for base in ("cold", "hot"):
        for path in glob.glob(str(ROOT / "engine-records" / base / f"game-*-{game_id}-*" / "engine.jsonl*")):
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as stream:
                return [json.loads(line) for line in stream if line.strip()]
    return []


def recorded_games() -> list[dict]:
    """Every recorded game with a human decision log: the log's decisions joined, in order, to the engine's decisions
    for the human seat (the log has one line per decision it answered)."""
    games = []
    for path in LOGS:
        lines = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        header = lines[0]
        decisions = [line for line in lines if line["kind"] == "decision"]
        if header.get("bot_name") != "Human" or not decisions:
            continue
        engine = [row["message"]["seat_decision"] for row in _record(header["game_id"])
                  if row.get("dir") == "engine_to_host" and (row["message"] or {}).get("response_type") == "decision"
                  and row["message"]["seat_decision"]["acting_seat"] == header["seat"]]
        if len(engine) < len(decisions):
            continue
        games.append({"game_id": header["game_id"], "seat": header["seat"], "deck": header["own_deck"]["name"],
                      "log": decisions, "engine": engine[:len(decisions)]})
    return games


def hidden_windows(game: dict) -> list[dict]:
    """The decisions the session passed for the person (``auto_pass``) at which the new rule would have asked."""
    found = []
    for line, sd in zip(game["log"], game["engine"]):
        assert line["candidate_id"] in {c["candidate_id"] for c in sd["candidates"]}  # the join is right
        assert line["candidate_count"] == len(sd["candidates"])
        if line["how"] == "auto_pass" and real_actions(sd["candidates"]):
            found.append(sd)
    return found


@recorded
def test_how_many_priorities_the_owner_was_never_shown() -> None:
    games = recorded_games()
    assert len(games) == 4
    hidden = {g["game_id"]: len(hidden_windows(g)) for g in games}
    assert hidden == {"g-8ccb0b21be945053": 19, "g-8de385e522ad962f": 16, "g-ab1f899e3d57531a": 1,
                      "g-e04f733c60027f02": 46}
    assert sum(hidden.values()) == 82
    passes = sum(1 for g in games for line in g["log"] if line["how"] == "auto_pass")
    assert passes == 142  # the other 60 had nothing but a pass or mana: still passed for the person


@recorded
def test_the_missed_ninjutsu_windows_of_the_faeries_game() -> None:
    game = next(g for g in recorded_games() if g["deck"] == "Faeries")
    windows = [(sd["observation"]["turn"], sd["observation"]["phase_step"], sd["observation"]["active_seat"],
                sorted(text.candidate(c["semantic"], ME) for c in real_actions(sd["candidates"])))
               for sd in hidden_windows(game) if any(c["semantic"]["kind"] == "activate_ability"
                                                    for c in sd["candidates"])]
    assert windows == [
        (7, "declare_blockers", ME, ["Activate Moon-Circuit Hacker"]),
        (8, "declare_blockers", ME, ["Activate Moon-Circuit Hacker"]),
        (9, "declare_blockers", ME, ["Activate Moon-Circuit Hacker", "Activate Ninja of the Deep Hours"])]
    # the abilities are activated from hand, and each was passed with "auto_pass" because the step was no stop
    for sd in hidden_windows(game):
        for c in real_actions(sd["candidates"]):
            if c["semantic"]["kind"] == "activate_ability":
                assert c["semantic"]["source"]["zone"] == "hand"


@recorded
def test_the_new_rule_replayed_over_the_recorded_games_asks_exactly_where_it_was_passed() -> None:
    """Re-run every recorded priority through a Hub with the new rule: the asked ones stay asked, and the passed ones
    are asked exactly when they had a real action (a skip the person asked for aside)."""
    for game in recorded_games():
        hub = Hub(real_action_stops=True)
        hub.game_start({"game_id": game["game_id"], "seat": game["seat"], "own_deck": {"name": game["deck"]},
                        "opponent_deck": {"name": "?"}})
        counts: Counter = Counter()
        for line, sd in zip(game["log"], game["engine"]):
            if (sd.get("context") or {}).get("kind") != "priority" or len(sd["candidates"]) == 1:
                continue
            hub.skip = None
            now = hub._automatic(sd)[0]
            counts[(line["how"], now)] += 1
        assert ("human", "auto_pass") not in counts  # nothing the person was asked is passed now
        assert counts[("auto_pass", "human")] == len(hidden_windows(game))
