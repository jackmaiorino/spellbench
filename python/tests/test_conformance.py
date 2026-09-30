"""The conformance runner engine adapters are held to (the interface K2 and G consume)."""

from __future__ import annotations

import sys
from pathlib import Path

from spellbench import wire
from spellbench.arena import cli
from spellbench.conformance import check_engine, replay_engine_transcript
from spellbench.host.engine_process import EngineProcess

TESTS = Path(__file__).resolve().parent
FAKE = [sys.executable, str(TESTS / "fake_v2_engine.py")]


def test_the_fake_engine_passes_every_check() -> None:
    report = check_engine(FAKE, format="pauper-bo1", decks=["Burn", "Elves"], games=2)
    assert report.passed, report.render()
    names = {check.name for check in report.checks}
    assert {"hello", "protocol_mismatch", "malformed_json", "malformed_request_non_object", "unsupported_rule",
            "game_id_reuse", "never_cached", "step_check_order", "retransmission", "game_already_terminal", "games"} <= names


def test_replay_sends_a_string_row_as_its_raw_line(tmp_path: Path) -> None:
    engine = EngineProcess(FAKE, timeout_s=30)
    try:
        hello = {"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1", "protocol_minor": 0}
        hello_ok, error = engine.send_raw(hello), engine.send_line(b"{not json")
    finally:
        engine.close()
    assert error["error"]["code"] == "malformed_json"
    rows = [("host_to_engine", hello), ("engine_to_host", hello_ok), ("host_to_engine", "{not json"), ("engine_to_host", error)]
    path = tmp_path / "raw.transcript.jsonl"
    path.write_bytes(b"".join(wire.canonical_json_line({"dir": direction, "message": message}) for direction, message in rows))
    assert replay_engine_transcript(FAKE, path) == []     # sent as the JSON string '"{not json"' it would be malformed_request (R3-11)


def test_a_hostile_engine_fails_the_games_check_with_its_rule() -> None:
    report = check_engine([sys.executable, str(TESTS / "hostile_v2_engine.py"), "stale-reference"], format="pauper-bo1", decks=["Burn"], games=1)
    failed = {check.name: check.detail for check in report.checks if not check.passed}
    assert "games" in failed and "host_validator:V4" in failed["games"]


def test_the_cli(capsys) -> None:
    assert cli.main(["conformance", "engine", "--format", "pauper-bo1", "--deck", "Burn", "--games", "1", "--", *FAKE]) == 0
    assert "PASS games" in capsys.readouterr().out
