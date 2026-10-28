"""Transparent engine wrapper that keeps a local wire transcript for misplay review.

usage: engine_tap.py --out DIR -- ENGINE_COMMAND...

Bytes pass through unchanged in both directions. Each process writes
DIR/tap-<uuid>.jsonl with one {"dir", "message"} record per wire line, the
same shape as the operator engine recording (arena/engine_records.py), so the
review converter reads either. The model-input payloads of x_kernel_flat_v4
(tensors and completion proposals) are dropped from the copy because review
needs only the row map. Transcripts carry the game secret and hidden zones:
keep them on the local machine.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

HEAVY = ("tensor", "proposals", "proposals_zlib")


def slim(line: bytes) -> object:
    try:
        message = json.loads(line)
    except ValueError:
        return {"unparsed": line.decode("utf-8", "replace")}
    extensions = message.get("extensions") if isinstance(message, dict) else None
    flat = extensions.get("x_kernel_flat_v4") if isinstance(extensions, dict) else None
    if isinstance(flat, dict):
        extensions["x_kernel_flat_v4"] = {k: v for k, v in flat.items() if k not in HEAVY}
    return message


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[0] != "--out" or argv[2] != "--":
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    log = (out / f"tap-{uuid.uuid4().hex}.jsonl").open("w", encoding="utf-8", newline="\n")
    lock = threading.Lock()
    child = subprocess.Popen(argv[3:], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def record(direction: str, line: bytes) -> None:
        text = json.dumps({"dir": direction, "message": slim(line)}, separators=(",", ":"))
        with lock:
            log.write(text + "\n")
            log.flush()

    def pump_in() -> None:
        assert child.stdin is not None
        try:
            for line in sys.stdin.buffer:
                record("host_to_engine", line)
                child.stdin.write(line)
                child.stdin.flush()
        except OSError:
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    threading.Thread(target=pump_in, daemon=True).start()
    assert child.stdout is not None
    for line in child.stdout:
        record("engine_to_host", line)
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
    code = child.wait()
    log.close()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
