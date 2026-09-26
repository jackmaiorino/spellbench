"""Test fixture: an agent-role bot that answers choose with an invalid selection.

Speaks well-formed NDJSON and a valid envelope, but deliberately returns
``candidate_id`` 42 (outside every offered candidate list), which the host
must adjudicate as a forfeit (invalid selection). Not used by the protocol
conformance suite.
"""

from __future__ import annotations

import sys

from spellbench import wire

BOT = {"name": "bad-invalid", "version": "1.0.0"}


def main() -> int:
    out = sys.stdout.buffer
    while True:
        line = wire.read_line(sys.stdin.buffer)
        if line is None:
            return 0
        request = wire.strict_json_loads(line)
        request_id = request.get("request_id", "")
        request_type = request.get("request_type")
        if request_type == "hello":
            message = {
                "response_type": "hello_ok",
                "protocol": "spellbench/v1",
                "request_id": request_id,
                "bot": BOT,
                "extensions_accepted": [],
            }
        elif request_type in ("game_start", "game_over"):
            message = {"response_type": "ack", "protocol": "spellbench/v1", "request_id": request_id}
        elif request_type == "choose":
            message = {
                "response_type": "choice",
                "protocol": "spellbench/v1",
                "request_id": request_id,
                "selection": {"candidate_id": 42, "semantic_echo": {"kind": "pass"}},
            }
        else:
            message = {
                "response_type": "error",
                "protocol": "spellbench/v1",
                "request_id": request_id,
                "error": {"code": "malformed_request", "message": "unknown request_type"},
            }
        out.write(wire.canonical_json_line(message))
        out.flush()


if __name__ == "__main__":
    sys.exit(main())
