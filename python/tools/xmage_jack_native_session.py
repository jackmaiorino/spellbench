"""Own a borrowed original-player JVM and its existing confined inference pair.

The guarded launcher creates the peer. This component does not launch a JVM,
load weights, authorize native work or qualify a complete player.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time

from spellbench import wire
from xmage_jack_native_inference import JackNativeInferenceOwner, SCHEMA as INFERENCE_SCHEMA
from xmage_jack_sources import CALLBACK_SHA256
from xmage_neural_decisions import load_response

SCHEMA = "spellbench-jack-original-serving/v1"


def digest(value):
    return hashlib.sha256(wire.canonical_json_dumps(value)).hexdigest()


class JackNativeSession:
    """One game, serial decision requests, original inference stream and JVM owner."""
    def __init__(self, peer, owner, *, startup_s=90):
        self.peer, self.owner = peer, owner
        self.sequence = 0
        self.closed = self.failed = False
        self.cleanup = None
        try:
            if not isinstance(owner, JackNativeInferenceOwner) or owner.closed:
                raise ValueError("original serving requires an open game-owned inference pair")
            self.start = copy.deepcopy(owner.start)
            self.start_sha256 = digest(self.start)
            self.profile, self.seed = owner.profile, owner.seed
            if (type(self.start.get("agent_seed")) is not int or self.start["agent_seed"] != self.seed
                    or not 0 <= self.seed <= wire.MAX_JSON_INT):
                raise ValueError("original serving chooser seed differs from the declared game seed")
            self.ready = {"schema": SCHEMA, "ready": True, "callback_sha256": CALLBACK_SHA256,
                          "profile": self.profile, "seed": self.seed,
                          "game_start_sha256": self.start_sha256, "operations": ["decide"]}
            deadline = self._deadline(startup_s)
            self.peer.set_timeout(self._remaining(deadline))
            if wire.canonical_json_dumps(self._read()) != wire.canonical_json_dumps(self.ready):
                raise ValueError("original serving readiness differs from the owned game and callback")
            self._remaining(deadline)
        except BaseException as failure:
            self._fail(failure)
            raise

    @staticmethod
    def _deadline(seconds):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("original serving needs a positive finite remaining clock")
        return time.monotonic() + seconds

    @staticmethod
    def _remaining(deadline):
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("original serving exhausted its shared decision clock")
        return seconds

    def _read(self):
        row = self.peer.read_line()
        if not isinstance(row, bytes) or len(row) > wire.MAX_LINE_BYTES:
            raise ValueError("original serving response exceeds its private frame bound")
        return load_response(row)

    def _request(self, record):
        if not isinstance(record, dict) or set(record) != {"game_start", "decision", "world_seed", "id_seed"}:
            raise ValueError("original serving needs a bound decision and declared reconstruction seeds")
        record = copy.deepcopy(record)
        if digest(record["game_start"]) != self.start_sha256:
            raise ValueError("original serving request belongs to another game")
        for key in ("world_seed", "id_seed"):
            if not isinstance(record[key], str) or not re.fullmatch("[a-f0-9]{64}", record[key]):
                raise ValueError("original serving reconstruction seed differs from its declared shape")
        decision = record["decision"]
        if (not isinstance(decision, dict) or not isinstance(decision.get("observation"), dict)
                or self.start.get("seat") not in ("p0", "p1")
                or decision.get("acting_seat") != self.start["seat"]
                or decision["observation"].get("viewer") != self.start["seat"]):
            raise ValueError("original serving requires its acting permitted viewer")
        offered = decision.get("candidates")
        if not isinstance(offered, list) or not 1 <= len(offered) <= 4096:
            raise ValueError("original serving needs the offered choices")
        bound = {}
        for candidate in offered:
            if not isinstance(candidate, dict):
                raise ValueError("malformed original serving candidate")
            cid, semantic = candidate.get("candidate_id"), candidate.get("semantic")
            if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in bound
                    or not isinstance(semantic, dict)):
                raise ValueError("original serving choices are invalid or aliased")
            bound[cid] = semantic
        # Public inputs keep the integer-only wire contract, including nested semantics.
        wire.canonical_json_dumps(record)
        return record, bound

    def choose(self, record, *, timeout_s):
        if self.closed or self.failed:
            raise ValueError("original serving session is closed or failed")
        try:
            deadline = self._deadline(timeout_s)
            record, offered = self._request(record)
            self.sequence += 1
            if self.sequence > wire.MAX_JSON_INT:
                raise ValueError("original serving request sequence exhausted")
            rid = str(self.sequence)
            self.peer.set_timeout(self._remaining(deadline))
            request = {**record, "schema": SCHEMA, "id": rid, "operation": "decide",
                       "remaining_s": self._remaining(deadline)}
            payload = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(payload) > wire.MAX_LINE_BYTES:
                raise ValueError("original serving command exceeds its private frame bound")
            self.peer.write_line(payload)
            calls = 0
            while True:
                self.peer.set_timeout(self._remaining(deadline))
                message = self._read()
                self._remaining(deadline)
                if message.get("schema") == INFERENCE_SCHEMA:
                    seconds = message.get("remaining_s")
                    if (message.get("operation") == "close" or type(seconds) not in (int, float)
                            or not math.isfinite(seconds) or seconds <= 0):
                        raise ValueError("original callback closed or exhausted its inference session")
                    calls += 1
                    if calls > 4096:
                        raise ValueError("original serving exceeded its callback request envelope")
                    message["remaining_s"] = min(seconds, self._remaining(deadline))
                    self.owner.service(self.peer, message)
                    self._remaining(deadline)
                    continue
                if (set(message) != {"schema", "id", "operation", "event", "ok", "result"}
                        or message.get("schema") != SCHEMA or message.get("id") != rid
                        or message.get("operation") != "decide" or message.get("event") != "result"
                        or message.get("ok") is not True):
                    raise ValueError("original serving returned a stale or failed result")
                result = message.get("result")
                if (not isinstance(result, dict) or result.get("decision_sha256") != digest(record["decision"])
                        or result.get("game_start_sha256") != self.start_sha256
                        or result.get("profile") != self.profile or type(result.get("seed")) is not int
                        or result["seed"] != self.seed or type(result.get("inference_requests")) is not int
                        or result["inference_requests"] != calls or result.get("full_original_player_qualified") is not False):
                    raise ValueError("original serving result lost its game, decision or callback identity")
                selection, flags = result.get("selection"), result.get("world_flags")
                if (not isinstance(selection, dict) or set(selection) != {"candidate_id", "semantic_echo"}
                        or type(selection.get("candidate_id")) is not int or selection["candidate_id"] not in offered
                        or wire.canonical_json_dumps(selection["semantic_echo"])
                            != wire.canonical_json_dumps(offered[selection["candidate_id"]])
                        or not isinstance(flags, list) or any(not isinstance(flag, str)
                            or flag.startswith(("unsupported:", "horizon:")) for flag in flags)):
                    raise ValueError("original serving result is not an exact supported offered choice")
                self._remaining(deadline)
                return copy.deepcopy(result)
        except BaseException as failure:
            self._fail(failure)
            raise

    def _fail(self, failure):
        self.failed = True
        try:
            self.close()
        except BaseException as cleanup:
            if hasattr(failure, "add_note"):
                failure.add_note("Original serving cleanup also failed: " + str(cleanup))

    def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        for name, resource in (("jvm", self.peer), ("inference", self.owner)):
            try:
                resource.close()
                process = getattr(resource, "_proc", None) if name == "jvm" else None
                if process is not None and process.poll() is None:
                    raise RuntimeError("owned original JVM remains running after peer close")
            except BaseException as error:
                errors.append((name, error))
        self.cleanup = {"close_called": True, "jvm_close_succeeded": not any(n == "jvm" for n, _ in errors),
                        "inference_close_succeeded": not any(n == "inference" for n, _ in errors)}
        process = getattr(self.peer, "_proc", None)
        self.cleanup["jvm_process_absent"] = process.poll() is not None if process is not None else None
        if errors:
            failure = errors[0][1]
            for name, error in errors[1:]:
                if hasattr(failure, "add_note"):
                    failure.add_note(name + " cleanup also failed: " + str(error))
            raise failure
