"""Bind the ported Exp1 search to offered decisions and isolated neural scores.

The caller starts the reviewed Java build in its own working directory and
supplies an InferenceSession with a pinned checkpoint and confined container.
This bridge currently supports priority roots. It is not a rated agent.
"""
from __future__ import annotations

import math
import json
import time

from spellbench import wire
from xmage_neural_decisions import decision_hash, load_response

READY = {"ready": True, "search": "draftzero-exp1-original-priority"}


def validate_result(decision: dict, result: dict, visits: int, calls: int) -> None:
    if (result.get("decision_sha256") != decision_hash(decision)
            or type(result.get("root_visits")) is not int or result["root_visits"] != visits
            or type(result.get("neural_calls")) is not int or result["neural_calls"] != calls):
        raise ValueError("search result is stale or did not complete the requested work")
    candidates = decision["candidates"]
    chosen = result.get("selection", {})
    offered = next((c for c in candidates if type(chosen.get("candidate_id")) is int
                    and c["candidate_id"] == chosen["candidate_id"]), None)
    if offered is None or offered["semantic"] != chosen.get("semantic_echo"):
        raise ValueError("search selected an unoffered or changed candidate")
    children = result.get("children")
    if not isinstance(children, list) or len(children) != len(candidates):
        raise ValueError("search root does not cover all offered actions")
    expected = {wire.canonical_json_dumps(c["semantic"]) for c in candidates}
    keys = [wire.canonical_json_dumps(c.get("semantic")) for c in children]
    if len(set(keys)) != len(keys) or set(keys) != expected:
        raise ValueError("search root has a missing, aliased or unoffered action")
    for child in children:
        if (type(child.get("visits")) is not int or not 0 <= child["visits"] <= visits
                or type(child.get("value")) not in (int, float) or not math.isfinite(child["value"])):
            raise ValueError("search root statistics are invalid")
    selected_branch = next(c for c in children if c["semantic"] == offered["semantic"])
    if (sum(c["visits"] for c in children) != visits or selected_branch["visits"] <= 0
            or selected_branch["visits"] != max(c["visits"] for c in children)):
        raise ValueError("search visit statistics do not support its chosen action")
    flags = result.get("world_flags")
    if (not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("horizon:", "unsupported:")) for f in flags)):
        raise ValueError("search ran outside its supported world envelope")


class SearchSession:
    """One private search pipe and checkpoint process, poisoned on any failure."""
    def __init__(self, peer, model):
        self.peer, self.model = peer, model
        self.closed = self.failed = False
        self.sequence = 0
        try:
            if load_response(peer.read_line()) != READY:
                raise ValueError("search readiness differs from the supported original Exp1 bridge")
        except BaseException:
            self.failed = True
            self.close()
            raise

    def choose(self, record: dict, *, visits: int, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("search session is closed or has failed")
        if type(visits) is not int or not 2 <= visits <= 1000:
            raise ValueError("original search visit budget must be 2..1000")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("original search needs a positive finite remaining clock")
        decision = record.get("decision", {})
        if decision.get("context", {}).get("kind") != "priority":
            raise ValueError("this original search bridge supports priority roots only")
        candidates = decision.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("search root needs offered candidates")
        ids = [c.get("candidate_id") for c in candidates]
        if any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids) or len(set(ids)) != len(ids):
            raise ValueError("search candidate ids are invalid or aliased")
        keys = [wire.canonical_json_dumps(c.get("semantic")) for c in candidates]
        if any(not isinstance(c.get("semantic"), dict) for c in candidates) or len(set(keys)) != len(keys):
            raise ValueError("search candidate semantics are invalid or aliased")
        self.sequence += 1
        rid = str(self.sequence)
        deadline = time.monotonic() + timeout_s
        # Do not allow an input record to override the session id or work budget.
        request = {k: record[k] for k in ("game_start", "decision", "world_seed", "id_seed")}
        request.update(id=rid, visits=visits)
        calls = 0
        try:
            self.peer.set_timeout(max(0, deadline - time.monotonic()))
            self.peer.write_line(wire.canonical_json_dumps(request))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("search exhausted its shared decision clock")
                self.peer.set_timeout(remaining)
                message = load_response(self.peer.read_line())
                if message.get("id") != rid:
                    raise ValueError("search returned a stale request id")
                if message.get("event") == "result":
                    if message.get("ok") is not True or not isinstance(message.get("result"), dict):
                        raise ValueError("original search refused: " + str(message.get("error")))
                    validate_result(decision, message["result"], visits, calls)
                    if time.monotonic() > deadline:
                        raise TimeoutError("search exhausted its result-validation clock")
                    return {"checkpoint": self.model.checkpoint, **message["result"]}
                if message.get("event") != "infer" or type(message.get("call")) is not int or message["call"] != calls + 1:
                    raise ValueError("search returned a stale or invalid neural call")
                calls += 1
                scores = self.model.score(message.get("features"), timeout_s=max(0, deadline-time.monotonic()))
                self.peer.set_timeout(max(0, deadline-time.monotonic()))
                # This private inference RPC carries floats. Public v2 frames
                # keep their integer-only canonical JSON contract.
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
