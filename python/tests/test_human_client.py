"""The human seat: the play server's automatic answers and combat plans, and a whole game through the relay."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from spellbench.human import relay
from spellbench.human.server import Hub, make_server
from spellbench.human import text

from arena_helpers import builtin, ledger_rows, make_config, roomy_machine, run, subprocess_bot

ME, OPP = "p0", "p1"


def ref(object_id: str, name: str, seat: str = ME, zone: str = "battlefield") -> dict:
    return {"object_id": object_id, "card_name": name, "owner_seat": seat, "controller_seat": seat, "zone": zone}


def observation(*, phase: str = "precombat_main", active: str = ME, stack: list | None = None) -> dict:
    return {"viewer": ME, "turn": 3, "phase_step": phase, "active_seat": active, "priority_seat": ME,
            "players": [{"seat": ME, "life": 20, "battlefield": []}, {"seat": OPP, "life": 20, "battlefield": []}],
            "stack": stack or [], "known": []}


def decision(candidates: list[dict], *, kind: str = "priority", group: dict | None = None, **obs) -> dict:
    return {"acting_seat": ME, "seat_step": 0, "group": group or {"group_id": 0, "substep_index": 0, "substep_count": 1},
            "context": {"kind": kind, "source": None, "purpose": None, "text": None, "rewind": False},
            "observation": observation(**obs),
            "candidates": [{"candidate_id": i, "semantic": s, "display_text": None} for i, s in enumerate(candidates)],
            "extensions": {}}


PASS = {"kind": "pass"}
BOLT = {"kind": "cast_spell", "source": ref("o-b", "Lightning Bolt", zone="hand"), "method": "normal"}


@pytest.fixture
def hub() -> Hub:
    hub = Hub()
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    return hub


def answer_in_background(hub: Hub, pick) -> threading.Thread:
    """Answers the next pending decision with ``pick(pending)`` once it appears."""
    def worker() -> None:
        with hub.cond:
            while hub.pending is None:
                hub.cond.wait()
            pending = hub.pending
        pick(pending)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def test_lone_candidates_and_bare_passes_are_answered_without_the_page(hub: Hub) -> None:
    assert hub.choose({"decision": decision([BOLT], kind="choice")}) == 0
    assert hub.choose({"decision": decision([PASS, {"kind": "activate_mana_ability", "source": ref("o-m", "Mountain"),
                                                    "ability_index": 0, "mana_choice": "R", "cost_target": None}])}) == 0
    assert hub.pending is None


def test_priority_passes_outside_stops_and_waits_at_own_main(hub: Hub) -> None:
    assert hub.choose({"decision": decision([PASS, BOLT], phase="upkeep")}) == 0  # no stop at upkeep
    assert hub.choose({"decision": decision([PASS, BOLT], phase="precombat_main", active=OPP)}) == 0
    thread = answer_in_background(hub, lambda p: hub.answer_with(p["seq"], 1))
    assert hub.choose({"decision": decision([PASS, BOLT], phase="precombat_main")}) == 1
    thread.join()


def test_opponent_spells_stop_even_while_passing_to_end_of_turn(hub: Hub) -> None:
    hub.observation = observation(phase="precombat_main", active=OPP)
    assert hub.control("pass_turn", {}) is None
    spell = {**ref("o-s", "Counterspell", OPP, "stack"), "stack_kind": "spell", "targets": []}
    assert hub.choose({"decision": decision([PASS, BOLT], phase="end_step", active=OPP)}) == 0
    thread = answer_in_background(hub, lambda p: hub.answer_with(p["seq"], 0))
    hub.choose({"decision": decision([PASS, BOLT], phase="end_step", active=OPP, stack=[spell])})
    thread.join()
    assert hub.control("skip_turn", {}) is None
    assert hub.choose({"decision": decision([PASS, BOLT], phase="end_step", active=OPP, stack=[spell])}) == 0


def test_attack_plan_answers_every_substep(hub: Hub) -> None:
    def substep(index: int, attacker: dict) -> dict:
        return decision([{"kind": "declare_attack", "attacker": attacker, "defender": None},
                         {"kind": "declare_attack", "attacker": attacker, "defender": {"player": OPP}}],
                        kind="choice", group={"group_id": 4, "substep_index": index, "substep_count": 2},
                        phase="declare_attackers")
    goblin, bear = ref("o-g", "Goblin"), ref("o-r", "Bear")
    thread = answer_in_background(hub, lambda p: hub.plan_with(p["seq"], {"kind": "attack", "attackers": ["o-r"]}))
    assert hub.choose({"decision": substep(0, goblin)}) == 0  # not in the plan: no attack
    thread.join()
    assert hub.choose({"decision": substep(1, bear)}) == 1  # answered from the plan, no page round trip
    assert hub.plan is not None and hub.pending is None


def test_block_plan_assigns_blockers_and_declines_extra_blocks(hub: Hub) -> None:
    attacker = ref("o-a", "Ogre", OPP)
    wall = ref("o-w", "Wall")

    def substep(index: int, blocker: dict) -> dict:
        return decision([{"kind": "declare_block", "blocker": blocker, "attacker": None},
                         {"kind": "declare_block", "blocker": blocker, "attacker": attacker}],
                        kind="choice", group={"group_id": 7, "substep_index": index, "substep_count": 2},
                        phase="declare_blockers", active=OPP)
    thread = answer_in_background(hub, lambda p: hub.plan_with(p["seq"], {"kind": "block", "blocks": {"o-w": "o-a"}}))
    assert hub.choose({"decision": substep(0, wall)}) == 1
    thread.join()
    assert hub.choose({"decision": substep(1, wall)}) == 0  # a second block for the same creature is declined


def test_costed_mana_sources_are_labelled_and_explained(hub: Hub) -> None:
    swamp, spawn = ref("o-s", "Swamp"), ref("o-e", "Eldrazi Spawn Token")
    request = decision([PASS, {"kind": "activate_mana_ability", "source": swamp, "ability_index": 0, "mana_choice": "B",
                               "cost_target": None},
                        {"kind": "activate_mana_ability", "source": spawn, "ability_index": 0, "mana_choice": "C",
                         "cost_target": None}, BOLT])
    request["observation"]["players"][0]["battlefield"] = [
        {**swamp, "characteristics": {"types": ["land"]}}, {**spawn, "characteristics": {"types": ["creature"]}}]
    view = hub._view(request)
    assert [c["text"] for c in view["candidates"][1:3]] == ["Tap Swamp for mana (B)",
                                                             "Activate Eldrazi Spawn Token for mana (C)"]
    assert "appears once you activate it" in view["hint"]
    request["candidates"] = request["candidates"][:2]
    assert hub._view(request)["hint"] is None  # only lands: autopay covers them


def test_history_lines_name_cards_for_both_sides() -> None:
    events = [{"kind": "turn_began", "turn": 2, "active_seat": OPP},
              {"kind": "draw", "seat": OPP, "card": None},
              {"kind": "zone_move", "card": {"object_id": None, "card_name": "Kor Skyfisher", "owner_seat": OPP},
               "owner_seat": OPP, "from": {"zone": "hand"}, "to": {"zone": "stack"}}]
    lines = list(text.history(events, ME))
    assert lines == [("game", "Turn 2: opponent turn"), ("opp", "Opp draws a card"), ("opp", "Opp casts Kor Skyfisher")]


def test_a_game_plays_through_the_relay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roomy_machine(monkeypatch)
    hub = Hub(log_dir=tmp_path / "logs")
    server = make_server(hub)
    host, port = server.server_address[:2]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv(relay.URL_ENV, f"http://{host}:{port}")
    monkeypatch.setenv(relay.TOKEN_ENV, server.token)
    stop = threading.Event()

    def player() -> None:  # a person who presses "next" and takes the first offered candidate
        seen = set()
        while not stop.is_set():
            with hub.cond:
                hub.cond.wait(0.05)
                pending, waiting = hub.pending, hub.hello_waiting
            if waiting:
                hub.control("next", {})
            if pending is not None and pending["seq"] not in seen:
                seen.add(pending["seq"])
                if pending["screen"] in ("attack", "block"):
                    hub.plan_with(pending["seq"], {"kind": pending["screen"],
                                                   "attackers": [], "blocks": {}})
                else:
                    hub.answer_with(pending["seq"], pending["candidates"][-1]["id"])
    threading.Thread(target=player, daemon=True).start()
    human = subprocess_bot("human", [sys.executable, str(Path(relay.__file__).resolve())])
    human["version"] = relay.VERSION
    config = make_config(tmp_path / "run", [human, builtin("uniform", seed=3)], pairs=1, include_self_play=False)
    try:
        summary = run(config)
    finally:
        stop.set()
        server.shutdown()
    assert summary.status == "complete"
    rows = ledger_rows(tmp_path / "run")
    assert len(rows) == 2 and all(row["classification"] != "forfeit" for row in rows)
    logs = sorted((tmp_path / "logs").glob("*.jsonl"))
    assert len(logs) == 2
    records = [json.loads(line) for line in logs[0].read_text().splitlines()]
    assert records[0]["kind"] == "header" and records[-1]["kind"] == "game_over"
    assert any(r["kind"] == "decision" for r in records)
    assert len(hub.results) == 2


def test_the_page_needs_the_token(tmp_path: Path) -> None:
    server = make_server(Hub())
    host, port = server.server_address[:2]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://{host}:{port}/")
        with urllib.request.urlopen(f"http://{host}:{port}/?t={server.token}") as response:
            assert b"Spellbench Play" in response.read()
    finally:
        server.shutdown()
