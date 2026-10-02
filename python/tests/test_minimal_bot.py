"""The spec 10.6 minimal bot, as documented: stdlib only, about 15 lines, conforming."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from spellbench import wire

BOT = Path(__file__).resolve().parents[2] / "examples" / "minimal_bot.py"


def _request(kind: str, request_id: str, **fields) -> bytes:
    return wire.canonical_json_line({"request_type": kind, "protocol": "spellbench/v2", "request_id": request_id, **fields})


def test_the_minimal_bot_is_small_and_stdlib_only() -> None:
    source = BOT.read_text(encoding="utf-8")
    assert len([line for line in source.splitlines() if line.strip()]) <= 20
    imported = {alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= {"json", "sys"} and "from " not in source


def test_the_minimal_bot_plays_under_a_legacy_code_page() -> None:
    # U+014D encodes as c5 8d; 0x8d is undefined in cp1252, so a text-mode reader would crash.
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"},
                                "display_text": "Lim-D\u00fbl's Vault \u014d"}]}
    stdin = b"".join([_request("hello", "r-0", protocol_minor=0), _request("game_start", "r-1", game_id="g-1"),
                      _request("choose", "r-2", game_id="g-1", decision=decision, clock={}),
                      _request("game_over", "r-3", game_id="g-1", terminal={})])
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    result = subprocess.run([sys.executable, str(BOT)], input=stdin, capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    answers = [json.loads(line) for line in result.stdout.splitlines()]  # splitlines also drops a "\r"
    assert [a["response_type"] for a in answers] == ["hello_ok", "ack", "choice", "ack"]
    assert answers[2]["selection"] == {"candidate_id": 0} and answers[0]["bot"]["name"] == "minimal"
