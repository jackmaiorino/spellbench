"""Test fixture: an agent-role bot that never answers ``choose``.

It completes ``hello`` and ``game_start`` normally, then sleeps on the first
``choose`` (argv[1] seconds, default 3600) so the host's wall-clock budget
expires and the host must adjudicate a timeout forfeit and kill the process.
"""

from __future__ import annotations

import sys
import time

from spellbench import wire

BOT = {"name": "bad-hang", "version": "1.0.0"}


def main() -> int:
    out = sys.stdout.buffer
    while True:
        line = wire.read_line(sys.stdin.buffer)
        if line is None:
            return 0
        request = wire.strict_json_loads(line)
        request_id = request.get("request_id", "")
        request_type = request.get("request_type")
        if request_type == "choose":
            time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 3600)
        if request_type == "hello":
            message = {
                "response_type": "hello_ok",
                "protocol": "spellbench/v1",
                "request_id": request_id,
                "bot": BOT,
                "extensions_accepted": [],
            }
        else:
            message = {"response_type": "ack", "protocol": "spellbench/v1", "request_id": request_id}
        out.write(wire.canonical_json_line(message))
        out.flush()


if __name__ == "__main__":
    sys.exit(main())
