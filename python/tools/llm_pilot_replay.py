"""Replay one completed pilot game through its engine, without model requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from spellbench import wire
from spellbench.conformance import _engine_exchanges


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-command", type=Path, required=True, help="the preserved JSON argv")
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new SSD output directory")
    args = parser.parse_args()
    command = json.loads(args.engine_command.read_bytes())
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        parser.error("engine command must be a nonempty JSON argv")
    if args.transcript.stat().st_size > 128 * 2**20:
        parser.error("the one-game replay accepts at most a 128 MiB transcript")
    exchanges = _engine_exchanges(args.transcript)
    if (sum(isinstance(row[1], dict) and row[1].get("request_type") == "reset" for row in exchanges) != 1
            or not exchanges or not isinstance(exchanges[-1][3], dict)
            or exchanges[-1][3].get("response_type") != "terminal"):
        parser.error("one completed engine game is required")
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 60 * 2**30:
        parser.error("scratch volume must retain the standing 60 GiB reserve")
    output.mkdir(exist_ok=False)
    expected_path, actual_path = output / "expected.jsonl", output / "replayed.jsonl"
    with expected_path.open("xb") as stream:
        for row in exchanges:
            stream.write(wire.canonical_json_line(row[3]))
    receipt = {"kind": "one-game-engine-regeneration", "status": "running", "model_requests": 0,
               "transcript_sha256": digest(args.transcript), "engine_command_sha256": digest(args.engine_command),
               "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                  cwd=Path(__file__).resolve().parents[2], text=True).strip(),
               "output_format": "canonical JSON lines of complete engine responses, including hello and deck validation",
               "projected_bytes": args.transcript.stat().st_size * 2, "storage_cap_bytes": 256 * 2**20,
               "exchanges": len(exchanges), "matched": 0, "bit_identical": False}
    peer = None
    started = time.monotonic()
    try:
        peer = wire.SubprocessPeer(command, timeout_s=60)
        with actual_path.open("xb") as stream:
            for request_line, request, answer_line, expected in exchanges:
                peer.set_timeout(min(60, max(0.001, started + 300 - time.monotonic())))
                peer.write_line(request.encode() if isinstance(request, str) else wire.canonical_json_dumps(request))
                actual = wire.strict_json_loads(peer.read_line())
                line = wire.canonical_json_line(actual)
                stream.write(line)
                if line != wire.canonical_json_line(expected):
                    receipt.update(status="failed", mismatch_response_line=answer_line,
                                   mismatch_request_line=request_line)
                    break
                receipt["matched"] += 1
        receipt["status"] = "completed" if receipt["matched"] == len(exchanges) else "failed"
    except Exception as exc:
        receipt.update(status="failed", error_type=type(exc).__name__)
    finally:
        if peer is not None:
            peer.close()
            (output / "engine-stderr.txt").write_text(peer.stderr_text(), encoding="utf-8")
        receipt["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        receipt["expected_sha256"] = digest(expected_path)
        receipt["replayed_sha256"] = digest(actual_path) if actual_path.exists() else None
        receipt["bit_identical"] = receipt["expected_sha256"] == receipt["replayed_sha256"]
        if not receipt["bit_identical"]:
            receipt["status"] = "failed"
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
