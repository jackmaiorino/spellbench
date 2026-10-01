"""X4 caps check: games cut by ``max_decisions`` and ``max_steps`` end ``truncated`` the way the live validator
accepts (spec 9.2, 11.3 V3), with the engine's counts equal to the validator's.

The host's per-seat caps stay below half of each game cap (spec 11.4), so host-run games never reach an engine cap;
this script drives the engine directly: seeded random answers, every decision checked by P's ``LiveValidator``,
then ``check_terminal``.

    PYTHONPATH=<p2>/python python caps.py -- <engine argv...>
"""

from __future__ import annotations

import json
import random
import sys

from spellbench import digests
from spellbench.host.engine_process import EngineProcess
from spellbench.host.validator import LiveValidator
from spellbench.messages import CardNameDomain, Decision, ResetRequest, Rules, Terminal, WireDeck
from spellbench.run_secret import RunSecret

CASES = [  # (max_decisions, max_steps, answer seed)
    (60, 5000, 1), (250, 5000, 2), (5000, 61, 3), (5000, 333, 4), (5000, 207, 5), (5000, 150, 6), (90, 5000, 7),
]


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:]
    secret = RunSecret.from_hex("00" * 31 + "07")
    results = []
    engine = EngineProcess(argv, timeout_s=300)
    try:
        hello = engine.hello()
        deck = next(d for d in hello.catalog if d.catalog_id == "Standard16-RG")
        rows = digests.deck_rows([r.to_json() for r in deck.decklist])
        wire = WireDeck(digests.deck_id(rows), catalog_id=deck.catalog_id)
        domain = CardNameDomain.from_json(digests.card_name_domain(r["name"] for r in rows))
        rules = Rules(opponent_decklist="visible", mulligan="london", starting_player="host_assigned",
                      starting_seat="p0", card_name_domain=domain, extensions=(), probe=False)
        for game, (max_decisions, max_steps, seed) in enumerate(CASES):
            request = ResetRequest(request_id=f"caps-{game}", game_id=secret.game_id(game), format="standard-2022-25-bo1",
                                   seats=(wire, wire), rules=rules, game_secret=secret.game_secret(game).hex(),
                                   max_decisions=max_decisions, max_steps=max_steps)
            validator = LiveValidator(hello, rules, max_decisions=max_decisions, max_steps=max_steps)
            rng = random.Random(seed)
            response = engine.reset(request)
            while isinstance(response, Decision):
                sd = validator.check(response)            # raises ValidatorViolation on any broken rule
                choice = rng.randrange(len(sd["candidates"]))
                validator.answered(sd, choice)
                response = engine.step(candidate_id=choice, semantic=sd["candidates"][choice]["semantic"])
            assert isinstance(response, Terminal)
            validator.check_terminal(response)            # V3 truncation rules, V10
            result = response.result
            counts_match = (result.step_count == validator.answered_steps
                            and result.decision_count == validator.completed_groups)
            results.append({"max_decisions": max_decisions, "max_steps": max_steps,
                            "classification": result.classification, "reason": result.reason,
                            "step_count": result.step_count, "decision_count": result.decision_count,
                            "counts_match": counts_match})
    finally:
        engine.close()
    print(json.dumps(results, indent=1))
    # every game either reaches its cap (truncated, spec 9.2) or ends naturally below it
    ok = all(r["counts_match"] and (r["classification"] == "truncated" or (
        r["classification"] == "natural" and r["step_count"] < r["max_steps"]
        and r["decision_count"] < r["max_decisions"])) for r in results)
    print("caps verdict:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
