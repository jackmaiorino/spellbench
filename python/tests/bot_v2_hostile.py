"""Test fixture: an agent-role v2 bot that misbehaves in the mode named by argv[1].

Every mode is otherwise the minimal bot (spec 10.6), answering as ``hostile`` 1.0.0: ``hello_ok``
to ``hello``, ``ack`` to ``game_start`` and ``game_over``, candidate 0 to ``choose``. One mode
breaks one request (``choose`` unless named, so a run's preflight accepts the bot and the game
forfeits it, R3-32). ``MODES`` maps each mode to the outcome ``host.agent_process.AgentProcess``
records: a ``SeatFailure`` cause (spec 11.5), or ``"ok"`` when this layer accepts the answer and
the game loop, the drivers or preflight judge it instead. ``PHASES`` maps each mode to the request
it breaks, which a ``SeatFailure``'s detail names (``"every"`` for the two modes that shape every
answer instead).

- ``garbage``: answers ``choose`` with a line that is not JSON.
- ``nested``: answers ``choose`` with a short line nested 5000 levels.
- ``deep65``: answers ``choose`` with a line nested 65 levels, one past the wire cap (spec 2).
- ``flood``: answers ``choose`` with a 16 MiB line (twice the protocol cap).
- ``bigint``: answers ``choose`` with a ``candidate_id`` of 5000 digits (past 2^53 - 1, and past
  CPython's integer string-conversion limit).
- ``string-id``: answers ``choose`` with a string ``candidate_id``.
- ``float-id``: answers ``choose`` with a fractional ``candidate_id`` (strict JSON rejects it).
- ``surrogate-error``: answers ``choose`` with an error whose message holds a lone surrogate escape
  (cannot be encoded as UTF-8).
- ``stdout-noise``: prints ``Loading model weights...`` before its ``hello_ok``, as an ML library
  banner on stdout would.
- ``badname``: answers ``hello`` with a bot name holding a lone surrogate.
- ``error-response``: answers ``choose`` with an ``internal_error`` error envelope.
- ``decision-pending``: answers ``choose`` with a ``decision_pending`` error envelope.
- ``crash``: writes a traceback holding its pid to stderr, then exits on ``choose``, so reruns
  prove no peer text reaches the ledger.
- ``hang``: reads a ``choose`` and never answers it.
- ``slow-hello``, ``slow-game-start``: answer that request only after 60 s.
- ``deaf``: answers ``hello`` and ``game_start``, then never reads stdin again: a small ``choose``
  times out on the host's read, a large one on its bounded write (R2-5). It exits after
  ``DEAF_SECONDS``, so a host whose write is unbounded fails its test instead of hanging it.
- ``wrong-echo-step``, ``wrong-echo-semantic``: answer ``choose`` with a wrong echo, which this
  layer keeps raw for the game loop to judge.
- ``out-of-range``: answers ``choose`` with a ``candidate_id`` past the candidate list (R2-16).
- ``extra-fields``: every answer holds unknown fields (``EXTRA_FIELDS``), which lenient readers ignore (spec 10).
- ``crlf``: terminates every answer with a CRLF, which readers tolerate (spec 2).
- ``crash-on-game-over``: exits on ``game_over``.
- ``requires-poison``: answers ``hello`` requiring the ``poison`` observation flag.
- ``wrong-name``: answers ``hello`` as ``impostor``.

``MODES``, ``PHASES`` and ``EXTRA_FIELDS`` are module level and ``sys.argv`` is read only under
``if __name__ == "__main__":`` (R2-20), so a test can import the tables without the module serving stdin.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from spellbench import wire

BOT = {"name": "hostile", "version": "1.0.0"}
PROTOCOL = "spellbench/v2"

MODES: dict[str, str] = {
    "garbage": "malformed_response",
    "nested": "malformed_response",
    "deep65": "malformed_response",
    "flood": "malformed_response",
    "bigint": "malformed_response",
    "string-id": "malformed_response",
    "float-id": "malformed_response",
    "surrogate-error": "malformed_response",
    "stdout-noise": "malformed_response",
    "badname": "malformed_response",
    "error-response": "agent_error",
    "decision-pending": "agent_error",
    "crash": "transport_error",
    "hang": "timeout",
    "slow-hello": "timeout",
    "slow-game-start": "timeout",
    "deaf": "timeout",
    "wrong-echo-step": "ok",
    "wrong-echo-semantic": "ok",
    "out-of-range": "ok",
    "extra-fields": "ok",
    "crlf": "ok",
    "crash-on-game-over": "ok",
    "requires-poison": "ok",
    "wrong-name": "ok",
}

# The request each mode breaks (R3-32: choose unless named), as a SeatFailure's detail names it;
# "every" for extra-fields and crlf, which shape every answer instead.
PHASES: dict[str, str] = {
    "garbage": "choose",
    "nested": "choose",
    "deep65": "choose",
    "flood": "choose",
    "bigint": "choose",
    "string-id": "choose",
    "float-id": "choose",
    "surrogate-error": "choose",
    "stdout-noise": "hello",
    "badname": "hello",
    "error-response": "choose",
    "decision-pending": "choose",
    "crash": "choose",
    "hang": "choose",
    "slow-hello": "hello",
    "slow-game-start": "game_start",
    "deaf": "choose",
    "wrong-echo-step": "choose",
    "wrong-echo-semantic": "choose",
    "out-of-range": "choose",
    "extra-fields": "every",
    "crlf": "every",
    "crash-on-game-over": "game_over",
    "requires-poison": "hello",
    "wrong-name": "hello",
}

# The unknown fields extra-fields adds to every answer (spec 10: the host reads past them).
EXTRA_FIELDS: dict[str, Any] = {"x_note": "confidence soon", "debug": {"scores": [1, 2, 3]}}
# How long deaf sleeps after game_start before it exits: far past any budget the tests give its choose.
DEAF_SECONDS = 30

assert set(PHASES) == set(MODES)   # every mode names the request it breaks


def _send(payload: bytes, *, crlf: bool) -> None:
    sys.stdout.buffer.write(payload + (b"\r\n" if crlf else b"\n"))
    sys.stdout.buffer.flush()


def _crash() -> None:
    sys.stderr.write(f"Traceback (most recent call last):\nRuntimeError: pid={os.getpid()}\n")
    sys.stderr.flush()
    os._exit(7)


def _encode(message: dict[str, Any], mode: str) -> bytes:
    """An answer as canonical JSON, with ``EXTRA_FIELDS`` in every answer of ``extra-fields``."""
    return wire.canonical_json_dumps({**message, **EXTRA_FIELDS} if mode == "extra-fields" else message)


def _ack(request_id: str, mode: str) -> bytes:
    return _encode({"response_type": "ack", "protocol": PROTOCOL, "request_id": request_id}, mode)


def _hello_ok(request_id: str, mode: str) -> bytes:
    if mode == "badname":
        return (b'{"bot":{"name":"x\\ud800","version":"1.0.0"},"protocol":"spellbench/v2","request_id":"'
                + request_id.encode() + b'","response_type":"hello_ok"}')
    message: dict[str, Any] = {"response_type": "hello_ok", "protocol": PROTOCOL, "request_id": request_id,
                               "bot": dict(BOT)}
    if mode == "requires-poison":
        message["requires"] = {"observation": ["poison"]}
    if mode == "wrong-name":
        message["bot"] = {"name": "impostor", "version": "1.0.0"}
    return _encode(message, mode)


def _choice(request: dict, mode: str) -> bytes:
    request_id = request["request_id"]
    if mode == "garbage":
        return b"this is not json"
    if mode == "nested":
        return b'{"x":' + b"[" * 5000 + b"]" * 5000 + b"}"
    if mode == "deep65":
        # 63 nested lists under selection: the innermost sits at level 65, one past the wire cap.
        return (b'{"protocol":"spellbench/v2","request_id":"' + request_id.encode()
                + b'","response_type":"choice","selection":{"candidate_id":0,"x_deep":' + b"[" * 63 + b"]" * 63 + b"}}")
    if mode == "flood":
        return b"a" * (16 << 20)   # twice the protocol's 8 MiB line cap (spec 2)
    if mode == "bigint":
        return (b'{"protocol":"spellbench/v2","request_id":"' + request_id.encode()
                + b'","response_type":"choice","selection":{"candidate_id":' + b"1" * 5000 + b"}}")
    if mode == "float-id":
        return (b'{"protocol":"spellbench/v2","request_id":"' + request_id.encode()
                + b'","response_type":"choice","selection":{"candidate_id":0.0}}')
    if mode == "surrogate-error":
        return (b'{"error":{"code":"internal_error","message":"boom \\ud800"},'
                b'"protocol":"spellbench/v2","request_id":"' + request_id.encode() + b'","response_type":"error"}')
    if mode in ("error-response", "decision-pending"):
        code = "internal_error" if mode == "error-response" else "decision_pending"
        return wire.canonical_json_dumps({"response_type": "error", "protocol": PROTOCOL, "request_id": request_id,
                                          "error": {"code": code, "message": "boom"}})
    selection: dict[str, Any] = {"candidate_id": 0}
    if mode == "string-id":
        selection["candidate_id"] = "0"
    elif mode == "out-of-range":
        selection["candidate_id"] = 999
    elif mode == "wrong-echo-step":
        selection["seat_step"] = request["decision"]["seat_step"] + 1
    elif mode == "wrong-echo-semantic":
        selection["semantic_echo"] = {"kind": "play_land"}   # candidate 0 was pass
    message = {"response_type": "choice", "protocol": PROTOCOL, "request_id": request_id, "selection": selection}
    return _encode(message, mode)


def main(mode: str) -> int:
    crlf = mode == "crlf"
    while True:
        line = wire.read_line(sys.stdin.buffer)
        if line is None:
            return 0
        request = wire.strict_json_loads(line)
        request_id, kind = request["request_id"], request["request_type"]
        if kind == "hello":
            if mode == "stdout-noise":
                _send(b"Loading model weights...", crlf=False)   # a library banner, not a protocol line
            if mode == "slow-hello":
                time.sleep(60)
            _send(_hello_ok(request_id, mode), crlf=crlf)
        elif kind == "choose":
            if mode == "hang":
                time.sleep(60)   # the host times out and closes long before this answers
            elif mode == "crash":
                _crash()
            else:
                _send(_choice(request, mode), crlf=crlf)
        else:
            if kind == "game_start" and mode == "slow-game-start":
                time.sleep(60)
            if kind == "game_over" and mode == "crash-on-game-over":
                _crash()
            _send(_ack(request_id, mode), crlf=crlf)
            if kind == "game_start" and mode == "deaf":
                # Answered game_start, then never reads stdin again (R2-5). Bounded: if the host's write stops
                # timing out, this exit breaks its pipe and the test fails, rather than hanging on a live orphan.
                time.sleep(DEAF_SECONDS)
                os._exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        raise SystemExit(f"usage: bot_v2_hostile.py MODE; modes: {', '.join(sorted(MODES))}")
    sys.exit(main(sys.argv[1]))
