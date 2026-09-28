"""Play a fake-engine scenario deck through the live validator (tests only)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from spellbench.digests import card_name_domain, deck_id
from spellbench.host.engine_process import EngineProcess
from spellbench.host.validator import LiveValidator
from spellbench.messages import Decision, ResetRequest, Rules

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"


def play_tour(module: ModuleType, *extra_args: str) -> list[dict]:
    """Candidate 0 unless the scenario module defines pick(sd) (R2-2): candidate 0 of a priority decision is pass."""
    scenario = module.SCENARIO
    pick = getattr(module, "pick", lambda sd: 0)
    engine = EngineProcess([sys.executable, str(ENGINE), *scenario.engine_args, *extra_args], timeout_s=30)
    decisions: list[dict] = []
    try:
        hello = engine.hello()
        london = "london" in hello.profile.rules_supported["mulligan"]
        toss = "toss_winner_chooses" in hello.profile.rules_supported["starting_player"]
        rules = Rules.from_json({"opponent_decklist": "visible", "mulligan": "london" if london else "none",
                                 "starting_player": "toss_winner_chooses" if toss else "host_assigned",
                                 "starting_seat": None if toss else "p0",
                                 "card_name_domain": card_name_domain(row["name"] for row in scenario.decklist),
                                 "extensions": [], "probe": False})
        deck = {"deck_id": deck_id(scenario.decklist), "catalog_id": f"Scenario:{scenario.name}"}
        reset = ResetRequest.from_json({
            "request_type": "reset", "protocol": "spellbench/v2", "request_id": engine.next_request_id(),
            "game_id": "g-00000000000000aa", "format": "pauper-bo1",
            "seats": [{"seat": "p0", "deck": deck}, {"seat": "p1", "deck": deck}], "rules": rules.to_json(),
            "game_secret": "22" * 32, "max_decisions": 10000, "max_steps": 100000})
        validator = LiveValidator(hello, rules, max_decisions=reset.max_decisions, max_steps=reset.max_steps)
        response = engine.reset(reset)
        while isinstance(response, Decision):
            sd = validator.check(response)
            decisions.append(sd)
            choice = pick(sd)
            validator.answered(sd, choice)
            response = engine.step(candidate_id=choice, semantic=sd["candidates"][choice]["semantic"])
        validator.check_terminal(response)
        counts = (response.result.step_count, response.result.decision_count)
        assert counts == (validator.answered_steps, validator.completed_groups), counts
    finally:
        engine.close()
    return decisions
