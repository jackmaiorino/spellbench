"""Test fixture: an agent-role bot that misbehaves in the mode named by argv[1].

- ``nested``: answers ``choose`` with a short but deeply nested JSON line.
- ``surrogate``: answers ``choose`` with an error whose message holds a lone
  surrogate escape (cannot be encoded as UTF-8).
- ``badname``: answers ``hello`` with a bot name holding a lone surrogate.
- ``garbage``: answers ``choose`` with a line that is not JSON.
- ``crash``: writes a stderr burst holding its PID, then exits on ``choose``.
- ``flood``: answers ``choose`` with a 16 MiB line (twice the protocol cap).
- ``bigint``: answers ``choose`` with a choice whose ``candidate_id`` has
  5000 digits (past CPython's 4300-digit integer conversion limit).

Every other request is answered correctly, as bot ``hostile`` 1.0.0.
"""

from __future__ import annotations

import os
import sys

from spellbench import wire

MODE = sys.argv[1]


def send(payload: bytes) -> None:
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    while True:
        line = wire.read_line(sys.stdin.buffer)
        if line is None:
            return 0
        request = wire.strict_json_loads(line)
        request_id = request["request_id"]
        kind = request["request_type"]
        if kind == "hello":
            if MODE == "badname":
                send(
                    b'{"bot":{"name":"x\\ud800","version":"1.0.0"},"extensions_accepted":[],'
                    b'"protocol":"spellbench/v1","request_id":"' + request_id.encode() + b'",'
                    b'"response_type":"hello_ok"}'
                )
                continue
            send(
                wire.canonical_json_dumps(
                    {
                        "bot": {"name": "hostile", "version": "1.0.0"},
                        "extensions_accepted": [],
                        "protocol": "spellbench/v1",
                        "request_id": request_id,
                        "response_type": "hello_ok",
                    }
                )
            )
        elif kind in ("game_start", "game_over"):
            send(
                wire.canonical_json_dumps(
                    {"protocol": "spellbench/v1", "request_id": request_id, "response_type": "ack"}
                )
            )
        elif MODE == "nested":
            send(b'{"x":' + b"[" * 5000 + b"]" * 5000 + b"}")
        elif MODE == "surrogate":
            send(
                b'{"error":{"code":"internal_error","message":"boom \\ud800"},'
                b'"protocol":"spellbench/v1","request_id":"' + request_id.encode() + b'",'
                b'"response_type":"error"}'
            )
        elif MODE == "garbage":
            send(b"this is not json")
        elif MODE == "crash":
            sys.stderr.write(f"Traceback (most recent call last):\nRuntimeError: pid={os.getpid()}\n")
            sys.stderr.flush()
            os._exit(7)
        elif MODE == "flood":
            sys.stdout.buffer.write(b"a" * (16 << 20) + b"\n")
            sys.stdout.buffer.flush()
        elif MODE == "bigint":
            send(
                b'{"protocol":"spellbench/v1","request_id":"' + request_id.encode() + b'",'
                b'"response_type":"choice","selection":{"candidate_id":' + b"1" * 5000 + b","
                b'"semantic_echo":{"kind":"pass"}}}'
            )
        else:
            raise SystemExit(f"unknown mode {MODE}")


if __name__ == "__main__":
    sys.exit(main())
