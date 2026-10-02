"""An interrupted game needs verified host evidence before prefix regeneration."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from spellbench import wire

spec = importlib.util.spec_from_file_location(
    "timeout_replay", Path(__file__).parents[1] / "tools/llm_pilot_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def inputs(tmp_path, monkeypatch, *, receipt=True, changed_hash=False):
    command = tmp_path / "command.json"
    command.write_text('["unused-engine"]')
    transcript = tmp_path / "trace.jsonl"
    transcript.write_bytes(b"retained engine prefix")
    exchanges = [(1, {"request_type": "hello"}, 2, {"response_type": "hello_ok"}),
                 (3, {"request_type": "reset"}, 4, {"response_type": "decision"})]
    monkeypatch.setattr(replay, "_engine_exchanges", lambda path: exchanges)
    argv = ["replay", "--engine-command", str(command), "--transcript", str(transcript),
            "--out", str(tmp_path / "output")]
    if receipt:
        host = tmp_path / "host.json"
        host.write_text(json.dumps({"passed": True, "model_requests": 0, "classification": "forfeit",
                                    "timeout_binding": {"error": "timeout", "unknown_usage": True},
                                    "transcript_sha256": "0" * 64 if changed_hash else replay.digest(transcript),
                                    "exchanges": 2}))
        argv += ["--timeout-host-receipt", str(host)]
    monkeypatch.setattr(sys, "argv", argv)
    return exchanges


@pytest.mark.parametrize("receipt,changed_hash", [(False, False), (True, True)])
def test_unverified_prefix_refuses_before_engine_launch(tmp_path, monkeypatch, receipt, changed_hash):
    inputs(tmp_path, monkeypatch, receipt=receipt, changed_hash=changed_hash)
    monkeypatch.setattr(replay.wire, "SubprocessPeer", lambda *a, **k: pytest.fail("engine launched"))
    with pytest.raises(SystemExit) as exc:
        replay.main()
    assert exc.value.code == 2
    assert not (tmp_path / "output").exists()


def test_verified_prefix_is_labelled_and_bound_without_claiming_engine_terminal(tmp_path, monkeypatch):
    exchanges = inputs(tmp_path, monkeypatch)
    answers = iter(row[3] for row in exchanges)

    class Peer:
        def __init__(self, *a, **k):
            pass
        def set_timeout(self, seconds):
            pass
        def write_line(self, line):
            pass
        def read_line(self):
            return wire.canonical_json_line(next(answers))
        def close(self):
            pass
        def stderr_text(self):
            return ""

    monkeypatch.setattr(replay.wire, "SubprocessPeer", Peer)
    monkeypatch.setattr(replay.subprocess, "check_output", lambda *a, **k: "source\n")
    monkeypatch.setattr(replay.shutil, "disk_usage", lambda path: type("Space", (), {"free": 100 * 2**30})())
    assert replay.main() == 0
    result = json.loads((tmp_path / "output/receipt.json").read_text())
    assert result["kind"] == "timeout-forfeit-engine-prefix-regeneration"
    assert result["engine_terminal_observed"] is False
    assert result["host_receipt_sha256"] == replay.digest(tmp_path / "host.json")
    assert result["matched"] == 2 and result["bit_identical"] and result["model_requests"] == 0
