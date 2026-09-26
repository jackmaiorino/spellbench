"""A conformant environment-role engine whose outcomes depend on the bots.

Each game is four decisions alternating p0, p1, p0, p1. Every decision
offers ``[pass, play_land]``; a seat scores one point per ``play_land``. The
higher score wins naturally and equal scores draw. So the builtin bots have
hand-derivable results: ``heuristic`` always plays the land (2 points),
``first`` always passes (0 points), and ``uniform`` is seeded per game.

Test hooks, selected by the p0 deck's ``catalog_id``:

- ``Crash``: the process exits abruptly on the first ``step`` request.
- ``Halt``: the first ``step`` answers a ``halted`` terminal.

``max_steps`` below four truncates the game at that step.
"""

from __future__ import annotations

import os
import sys

from spellbench import wire
from spellbench.errors import MalformedJsonError
from spellbench.models import (
    Candidate,
    Decision,
    EngineIdentity,
    EnvHelloOk,
    ErrorResponse,
    Group,
    SeatSummary,
    StateSummary,
    Terminal,
    TerminalResult,
)

ENGINE = EngineIdentity(
    name="fake-arena-engine",
    version="0.0.1",
    source_revision=None,
    rules_snapshot_id="rules-fake-arena",
    card_pool_identity="pool-fake-arena",
)
PROVENANCE = ENGINE.provenance()
DECISIONS_PER_GAME = 4


def _land(seat: str, step: int) -> dict:
    return {
        "object_id": f"obj-{seat}-{step}",
        "card_name": "Mountain",
        "owner_seat": seat,
        "controller_seat": seat,
        "zone": "hand",
    }


def _decision(request_id: str, game_id: str, step: int, scores: dict[str, int]) -> Decision:
    seat = "p0" if step % 2 == 0 else "p1"
    candidates = (
        Candidate(candidate_id=0, semantic={"kind": "pass"}, display_text="Pass"),
        Candidate(
            candidate_id=1,
            semantic={"kind": "play_land", "source": _land(seat, step)},
            display_text="Play Mountain",
        ),
    )
    return Decision(
        request_id=request_id,
        game_id=game_id,
        step=step,
        acting_seat=seat,
        group=Group(group_id=step, substep_index=0, substep_count=1),
        state_summary=StateSummary(
            turn=1 + step // 2,
            phase_step="precombat_main",
            active_seat=seat,
            priority_seat=seat,
            seats=tuple(
                SeatSummary(
                    seat=name,
                    life=20,
                    hand_count=7,
                    library_count=53,
                    graveyard_count=0,
                    battlefield_count=scores[name],
                )
                for name in ("p0", "p1")
            ),
            stack_count=0,
        ),
        candidates=candidates,
        candidates_sha256=wire.candidates_sha256([candidate.to_json() for candidate in candidates]),
        provenance=PROVENANCE,
        extensions={},
    )


def _terminal(request_id: str, game_id: str, result: TerminalResult) -> dict:
    return Terminal(request_id=request_id, game_id=game_id, result=result, provenance=PROVENANCE).to_json()


def main() -> int:
    out = sys.stdout.buffer
    game_id = ""
    hook = ""
    step = 0
    max_steps = DECISIONS_PER_GAME
    scores = {"p0": 0, "p1": 0}
    while True:
        line = wire.read_line(sys.stdin.buffer)
        if line is None:
            return 0
        try:
            request = wire.strict_json_loads(line)
        except MalformedJsonError as exc:
            message = ErrorResponse(request_id="", code="malformed_json", message=str(exc)).to_json()
        else:
            request_id = request.get("request_id", "")
            kind = request.get("request_type")
            if kind == "hello":
                message = EnvHelloOk(
                    request_id=request_id,
                    engine=ENGINE,
                    formats=("pauper-bo1",),
                    decklists_as_data=False,
                    extensions=(),
                ).to_json()
            elif kind == "reset":
                game_id = request["game_id"]
                hook = request["seats"][0]["deck"].get("catalog_id", "")
                max_steps = min(request["max_steps"], DECISIONS_PER_GAME)
                message = _decision(request_id, game_id, 0, scores).to_json()
            elif kind == "step":
                if hook == "Crash":
                    os._exit(3)
                if hook == "Halt":
                    result = TerminalResult(
                        outcome="halted",
                        classification="halted",
                        winner=None,
                        reason="engine_contract_failure",
                        step_count=step + 1,
                        decision_count=step + 1,
                    )
                    message = _terminal(request_id, game_id, result)
                else:
                    seat = "p0" if step % 2 == 0 else "p1"
                    scores[seat] += request["selection"]["candidate_id"]
                    step += 1
                    if step >= DECISIONS_PER_GAME:
                        if scores["p0"] == scores["p1"]:
                            outcome, winner = "draw", None
                        else:
                            winner = "p0" if scores["p0"] > scores["p1"] else "p1"
                            outcome = f"{winner}_win"
                        result = TerminalResult(
                            outcome=outcome,
                            classification="natural",
                            winner=winner,
                            reason="score",
                            step_count=step,
                            decision_count=step,
                        )
                        message = _terminal(request_id, game_id, result)
                    elif step >= max_steps:
                        result = TerminalResult(
                            outcome="truncated",
                            classification="truncated",
                            winner=None,
                            reason="max_steps",
                            step_count=step,
                            decision_count=step,
                        )
                        message = _terminal(request_id, game_id, result)
                    else:
                        message = _decision(request_id, game_id, step, scores).to_json()
            else:
                message = ErrorResponse(
                    request_id=request_id, code="malformed_request", message="unknown request_type"
                ).to_json()
        out.write(wire.canonical_json_line(message))
        out.flush()


if __name__ == "__main__":
    sys.exit(main())
