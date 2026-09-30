"""The v2 goldens: current, canonical, valid, and complete (spec 16)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from spellbench import wire
from spellbench.agent_messages import AGENT_ERROR_CODES
from spellbench.candidates import V2_KINDS
from spellbench.messages import ENGINE_ERROR_CODES

from golden_helpers import GOLDENS_V2_DIR, golden_index, load_transcript_v2

TOOL = Path(__file__).resolve().parents[1] / "tools" / "generate_goldens_v2.py"
ENGINE_REQUESTS = {"hello", "reset", "step", "validate_deck", "probe_resample"}
ENGINE_RESPONSES = {"hello_ok", "decision", "terminal", "deck_ok", "error"}
AGENT_REQUESTS = {"hello", "game_start", "choose", "game_over"}
AGENT_RESPONSES = {"hello_ok", "ack", "choice", "error"}
RESERVED_RESPONSES = {"probe_result"}               # spec 9.7: reserved, so no v2.0 engine produces it


def test_the_generator_check_passes() -> None:
    result = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, timeout=600)
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()


def test_files_are_canonical_lines_and_indexed() -> None:
    names = sorted(path.name for path in GOLDENS_V2_DIR.glob("*.transcript.jsonl"))
    assert names == sorted(golden_index())
    for name in names:
        raw = (GOLDENS_V2_DIR / name).read_bytes()
        assert raw == b"".join(wire.canonical_json_line(wire.strict_json_loads(line)) for line in raw.splitlines())


def test_every_game_has_a_digest_and_the_goldens_cover_the_protocol() -> None:
    kinds, engine_codes, agent_codes = set(), set(), set()
    for name, entry in golden_index().items():
        rows = load_transcript_v2(name)
        if name.startswith("game_"):
            assert entry["game_digest"].startswith("sha256:"), name
        for direction, message in rows:
            if not isinstance(message, dict):
                continue
            if direction == "host_to_agent" and message.get("request_type") == "choose":
                kinds |= {c["semantic"]["kind"] for c in message["decision"]["candidates"]}
            if message.get("response_type") == "error":
                (engine_codes if direction == "engine_to_host" else agent_codes).add(message["error"]["code"])
    assert kinds == V2_KINDS
    assert engine_codes == ENGINE_ERROR_CODES and agent_codes == AGENT_ERROR_CODES


def test_the_goldens_cover_every_message_type() -> None:
    seen: dict[str, set[str]] = {direction: set() for direction in ("host_to_engine", "engine_to_host", "host_to_agent", "agent_to_host")}
    for name in golden_index():
        for direction, message in load_transcript_v2(name):
            if isinstance(message, dict):
                seen[direction].add(message.get("request_type") or message.get("response_type"))
    assert ENGINE_REQUESTS <= seen["host_to_engine"] and ENGINE_RESPONSES <= seen["engine_to_host"]
    assert AGENT_REQUESTS <= seen["host_to_agent"] and AGENT_RESPONSES <= seen["agent_to_host"]
    assert not RESERVED_RESPONSES & seen["engine_to_host"]                          # spec 16 (R3-26)
    assert json.loads((GOLDENS_V2_DIR / "index.json").read_bytes())["notes"]        # the Decision 4 reading (R2-23)
