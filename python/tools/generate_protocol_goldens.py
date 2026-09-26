#!/usr/bin/env python3
"""Author the spellbench/v1 golden transcripts (spec section 11).

Writes ``goldens/protocol_v1/*.transcript.jsonl`` deterministically from the
reference models. ``--check`` byte-verifies the on-disk files against a fresh
in-memory render without rewriting anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

from spellbench import wire
from spellbench.models import (
    Ack,
    AgentHelloOk,
    BotIdentity,
    Candidate,
    Choice,
    ChooseRequest,
    Decision,
    Deck,
    EngineIdentity,
    EnvHelloOk,
    ErrorResponse,
    GameOverRequest,
    GameStartRequest,
    Group,
    HelloRequest,
    ResetRequest,
    SeatDeck,
    SeatSummary,
    Selection,
    StateSummary,
    StepRequest,
    Terminal,
    TerminalResult,
)

ENGINE = EngineIdentity(
    name="example-engine",
    version="1.0.0",
    source_revision=None,
    rules_snapshot_id="rules-2025-09-26",
    card_pool_identity="pool-example-1",
)
PROVENANCE = ENGINE.provenance()

BOT = BotIdentity(name="uniform", version="1.0.0")

GAME_ID = "g-0001"
FORMAT = "pauper-bo1"
DECK = Deck(catalog_id="Burn")
SEATS = (SeatDeck(seat="p0", deck=DECK), SeatDeck(seat="p1", deck=DECK))

PASS = Candidate(candidate_id=0, semantic={"kind": "pass"}, display_text="Pass priority")

TERMINAL_RESULT = TerminalResult(
    outcome="p0_win",
    classification="natural",
    winner="p0",
    reason="p1_life_zero",
    step_count=2,
    decision_count=2,
)


def _pass_decision(request_id: str, *, step: int, acting_seat: str, group_id: int) -> Decision:
    candidates = (PASS,)
    return Decision(
        request_id=request_id,
        game_id=GAME_ID,
        step=step,
        acting_seat=acting_seat,
        group=Group(group_id=group_id, substep_index=0, substep_count=1),
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


DECISION_0 = _pass_decision("h-2", step=0, acting_seat="p0", group_id=0)
DECISION_1 = _pass_decision("h-3", step=1, acting_seat="p1", group_id=1)

HELLO_OK = EnvHelloOk(
    request_id="h-1",
    engine=ENGINE,
    formats=(FORMAT,),
    decklists_as_data=True,
    extensions=("x_example_obsv1",),
)

RESET = ResetRequest(
    request_id="h-2",
    game_id=GAME_ID,
    format=FORMAT,
    seats=SEATS,
    game_seed=12345,
    max_decisions=10000,
    max_steps=100000,
)

PASS_SELECTION = Selection(candidate_id=0, semantic_echo={"kind": "pass"})

Entry = tuple[str, dict]


def _env_prefix() -> list[Entry]:
    return [
        ("host_to_engine", HelloRequest(request_id="h-1").to_json()),
        ("engine_to_host", HELLO_OK.to_json()),
        ("host_to_engine", RESET.to_json()),
        ("engine_to_host", DECISION_0.to_json()),
    ]


def _error(code: str, request_id: str, message: str) -> dict:
    return ErrorResponse(request_id=request_id, code=code, message=message).to_json()


def transcripts() -> dict[str, list[Entry]]:
    env_happy = [
        *_env_prefix(),
        ("host_to_engine", StepRequest(request_id="h-3", game_id=GAME_ID, expected_step=0, selection=PASS_SELECTION).to_json()),
        ("engine_to_host", DECISION_1.to_json()),
        ("host_to_engine", StepRequest(request_id="h-4", game_id=GAME_ID, expected_step=1, selection=PASS_SELECTION).to_json()),
        ("engine_to_host", Terminal(request_id="h-4", game_id=GAME_ID, result=TERMINAL_RESULT, provenance=PROVENANCE).to_json()),
    ]

    agent_happy = [
        ("host_to_agent", HelloRequest(request_id="h-1").to_json()),
        ("agent_to_host", AgentHelloOk(request_id="h-1", bot=BOT, extensions_accepted=()).to_json()),
        (
            "host_to_agent",
            GameStartRequest(
                request_id="h-2",
                game_id=GAME_ID,
                seat="p0",
                format=FORMAT,
                decks=(DECK, DECK),
                engine=ENGINE,
            ).to_json(),
        ),
        ("agent_to_host", Ack(request_id="h-2").to_json()),
        ("host_to_agent", ChooseRequest(request_id="h-3", game_id=GAME_ID, decision=DECISION_0).to_json()),
        ("agent_to_host", Choice(request_id="h-3", selection=PASS_SELECTION).to_json()),
        ("host_to_agent", GameOverRequest(request_id="h-4", game_id=GAME_ID, terminal=TERMINAL_RESULT).to_json()),
        ("agent_to_host", Ack(request_id="h-4").to_json()),
    ]

    protocol_mismatch = [
        (
            "host_to_engine",
            {"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1"},
        ),
        ("engine_to_host", _error("protocol_mismatch", "h-1", 'protocol must be "spellbench/v1"')),
    ]

    reuse = [
        ("host_to_engine", HelloRequest(request_id="h-1").to_json()),
        ("engine_to_host", HELLO_OK.to_json()),
        (
            "host_to_engine",
            ResetRequest(
                request_id="h-1",
                game_id=GAME_ID,
                format=FORMAT,
                seats=SEATS,
                game_seed=12345,
                max_decisions=10000,
                max_steps=100000,
            ).to_json(),
        ),
        ("engine_to_host", _error("request_id_reuse_mismatch", "h-1", "request_id reused with a different payload")),
    ]

    expected_step = [
        *_env_prefix(),
        (
            "host_to_engine",
            StepRequest(request_id="h-3", game_id=GAME_ID, expected_step=7, selection=PASS_SELECTION).to_json(),
        ),
        ("engine_to_host", _error("expected_step_mismatch", "h-3", "expected_step 7 does not match decision step 0")),
    ]

    out_of_range = [
        *_env_prefix(),
        (
            "host_to_engine",
            StepRequest(
                request_id="h-3",
                game_id=GAME_ID,
                expected_step=0,
                selection=Selection(candidate_id=5, semantic_echo={"kind": "pass"}),
            ).to_json(),
        ),
        ("engine_to_host", _error("candidate_id_out_of_range", "h-3", "candidate_id 5 outside the candidate list of 1")),
    ]

    echo_mismatch = [
        *_env_prefix(),
        (
            "host_to_engine",
            StepRequest(
                request_id="h-3",
                game_id=GAME_ID,
                expected_step=0,
                selection=Selection(
                    candidate_id=0,
                    semantic_echo={"kind": "choose_optional_cost_use", "use_cost": True},
                ),
            ).to_json(),
        ),
        ("engine_to_host", _error("semantic_echo_mismatch", "h-3", "semantic_echo does not equal the candidate semantic")),
    ]

    return {
        "env_happy_path.transcript.jsonl": env_happy,
        "agent_happy_path.transcript.jsonl": agent_happy,
        "env_error_protocol_mismatch.transcript.jsonl": protocol_mismatch,
        "env_error_request_id_reuse_mismatch.transcript.jsonl": reuse,
        "env_error_expected_step_mismatch.transcript.jsonl": expected_step,
        "env_error_candidate_id_out_of_range.transcript.jsonl": out_of_range,
        "env_error_semantic_echo_mismatch.transcript.jsonl": echo_mismatch,
    }


def render(entries: list[Entry]) -> bytes:
    return b"".join(
        wire.canonical_json_line({"dir": direction, "message": message}) for direction, message in entries
    )


def main(argv: list[str]) -> int:
    check = "--check" in argv
    goldens_dir = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v1"
    built = {name: render(entries) for name, entries in transcripts().items()}
    failures = 0
    for name in sorted(built):
        path = goldens_dir / name
        content = built[name]
        if check:
            if not path.is_file():
                print(f"MISSING {name}")
                failures += 1
            elif path.read_bytes() != content:
                print(f"STALE   {name}")
                failures += 1
            else:
                print(f"OK      {name}")
        else:
            goldens_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"WROTE   {name} ({len(content)} bytes)")
    if check and failures:
        print(f"{failures} golden(s) out of date; run without --check to rewrite", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
