"""A minimal conformant environment-role engine used by the end-to-end tests.

Plays a scripted two-decision game of pass/priority and then reports a natural
p0 win. Supports the single-entry idempotent retry of spec section 4.1.
"""

from __future__ import annotations

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
    name="fake-engine",
    version="0.0.1",
    source_revision=None,
    rules_snapshot_id="rules-fake",
    card_pool_identity="pool-fake",
)
PROVENANCE = ENGINE.provenance()


def pass_decision(request_id: str, game_id: str, step: int, acting_seat: str) -> Decision:
    candidates = (Candidate(candidate_id=0, semantic={"kind": "pass"}, display_text="Pass priority"),)
    return Decision(
        request_id=request_id,
        game_id=game_id,
        step=step,
        acting_seat=acting_seat,
        group=Group(group_id=step, substep_index=0, substep_count=1),
        state_summary=StateSummary(
            turn=1,
            phase_step="precombat_main",
            active_seat="p0",
            priority_seat=acting_seat,
            seats=(
                SeatSummary(
                    seat="p0", life=20, hand_count=7, library_count=53, graveyard_count=0, battlefield_count=0
                ),
                SeatSummary(
                    seat="p1", life=20, hand_count=7, library_count=53, graveyard_count=0, battlefield_count=0
                ),
            ),
            stack_count=0,
        ),
        candidates=candidates,
        candidates_sha256=wire.candidates_sha256([candidate.to_json() for candidate in candidates]),
        provenance=PROVENANCE,
        extensions={},
    )


def main() -> int:
    out = sys.stdout.buffer
    game_id: str | None = None
    step = -1
    last: tuple[bytes, bytes] | None = None

    while True:
        line = wire.read_line(sys.stdin.buffer)
        if line is None:
            return 0
        if last is not None and last[0] == line:
            out.write(last[1])
            out.flush()
            continue
        try:
            request = wire.strict_json_loads(line)
        except MalformedJsonError as exc:
            message = ErrorResponse(request_id="", code="malformed_json", message=str(exc)).to_json()
            last = None
        else:
            request_id = request.get("request_id")
            request_id = request_id if type(request_id) is str else ""
            if request.get("protocol") != "spellbench/v1":
                message = ErrorResponse(
                    request_id=request_id, code="protocol_mismatch", message='protocol must be "spellbench/v1"'
                ).to_json()
            elif request.get("request_type") == "hello":
                message = EnvHelloOk(
                    request_id=request_id,
                    engine=ENGINE,
                    formats=("pauper-bo1",),
                    decklists_as_data=True,
                    extensions=(),
                ).to_json()
            elif request.get("request_type") == "reset":
                game_id = request["game_id"]
                step = 0
                message = pass_decision(request_id, game_id, 0, "p0").to_json()
            elif request.get("request_type") == "step":
                assert game_id is not None
                if request["expected_step"] != step:
                    message = ErrorResponse(
                        request_id=request_id,
                        code="expected_step_mismatch",
                        message="expected_step does not match the pending decision",
                    ).to_json()
                elif step == 0:
                    step = 1
                    message = pass_decision(request_id, game_id, 1, "p1").to_json()
                else:
                    message = Terminal(
                        request_id=request_id,
                        game_id=game_id,
                        result=TerminalResult(
                            outcome="p0_win",
                            classification="natural",
                            winner="p0",
                            reason="p1_life_zero",
                            step_count=2,
                            decision_count=2,
                        ),
                        provenance=PROVENANCE,
                    ).to_json()
            else:
                message = ErrorResponse(
                    request_id=request_id, code="malformed_request", message="unknown request_type"
                ).to_json()
            response_line = wire.canonical_json_line(message)
            last = (line, response_line)
            out.write(response_line)
            out.flush()
            continue
        response_line = wire.canonical_json_line(message)
        out.write(response_line)
        out.flush()


if __name__ == "__main__":
    sys.exit(main())
