"""One owned Java pipe and confined checkpoint, with a single request clock."""
from __future__ import annotations

import json
import math
import time

from spellbench import wire
from xmage_neural_decisions import load_response


class NeuralSession:
    def __init__(self, peer, model, *, ready: dict):
        self.peer, self.model = peer, model
        self.sequence = 0
        self.closed = self.failed = False
        try:
            if load_response(peer.read_line()) != ready:
                raise ValueError("neural readiness differs from the supported original Exp1 bridge")
        except BaseException:
            self.failed = True
            self.close()
            raise

    def exchange(self, request: dict, *, timeout_s: float, validate) -> dict:
        if self.closed or self.failed:
            raise ValueError("neural session is closed or has failed")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("original neural search needs a positive finite remaining clock")
        self.sequence += 1
        rid = str(self.sequence)
        deadline = time.monotonic() + timeout_s
        calls = 0

        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError("neural search exhausted its shared decision clock")
            return value

        try:
            self.peer.set_timeout(remaining())
            self.peer.write_line(wire.canonical_json_dumps({**request, "id": rid}))
            while True:
                self.peer.set_timeout(remaining())
                message = load_response(self.peer.read_line())
                if message.get("id") != rid:
                    raise ValueError("neural search returned a stale request id")
                if message.get("event") == "result":
                    if "operation" in request and message.get("operation") != request["operation"]:
                        raise ValueError("neural result differs from its requested operation")
                    if message.get("ok") is not True or not isinstance(message.get("result"), dict):
                        raise ValueError("original neural search refused: " + str(message.get("error")))
                    result = validate(message["result"], calls)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("neural search exhausted its validation clock")
                    return {**result, "checkpoint": self.model.checkpoint}
                if (message.get("event") != "infer" or type(message.get("call")) is not int
                        or message["call"] != calls + 1):
                    raise ValueError("neural search returned a stale or invalid neural call")
                calls += 1
                scores = self.model.score(message.get("features"), timeout_s=remaining())
                self.peer.set_timeout(remaining())
                # Float-valued heads stay on this private pipe. Public v2
                # frames retain their integer-only canonical JSON contract.
                self.peer.write_line(json.dumps({"id": rid, "call": calls, "ok": True, "scores": scores},
                                                separators=(",", ":"), allow_nan=False).encode())
        except BaseException:
            self.failed = True
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.peer.close()
        finally:
            self.model.close()
