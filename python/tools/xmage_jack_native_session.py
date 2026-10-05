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


def bound_decision(decision, seat):
    if (not isinstance(decision, dict) or not isinstance(decision.get("observation"), dict)
            or seat not in ("p0", "p1") or decision.get("acting_seat") != seat
            or decision["observation"].get("viewer") != seat):
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
    return bound


def bound_selection(selection, offered):
    if (not isinstance(selection, dict) or set(selection) != {"candidate_id", "semantic_echo"}
            or type(selection.get("candidate_id")) is not int or selection["candidate_id"] not in offered
            or wire.canonical_json_dumps(selection.get("semantic_echo"))
                != wire.canonical_json_dumps(offered[selection["candidate_id"]])):
        raise ValueError("original serving result is not an exact supported offered choice")


def priority_state(value, decision=None):
    if (not isinstance(value, dict) or set(value) != {"alternatives", "targets"}
            or not isinstance(value["alternatives"], list) or len(value["alternatives"]) > 4096):
        raise ValueError("original serving needs its recorded priority state")
    sources = set()
    for row in value["alternatives"]:
        if not isinstance(row, dict) or set(row) != {"source", "choices"}:
            raise ValueError("malformed original alternative-cost state")
        source, choices = row["source"], row["choices"]
        if (not isinstance(source, dict) or not isinstance(source.get("object_id"), str)
                or not source["object_id"] or source["object_id"] in sources
                or not isinstance(source.get("card_name"), str) or not source["card_name"]
                or not isinstance(choices, list) or not 1 <= len(choices) <= 4096
                or any(not isinstance(key, str) or not 1 <= len(key) <= 1024 for key in choices)
                or len(set(choices)) != len(choices)):
            raise ValueError("original alternative-cost state has invalid or aliased sources or keys")
        sources.add(source["object_id"])
    queue = value["targets"]
    if not isinstance(queue, list) or len(queue) > 4096:
        raise ValueError("original serving needs its bounded target queue")
    refs = {}
    fields = ("object_id", "card_name", "owner_seat", "controller_seat", "zone")
    if decision is not None:
        observation = decision["observation"]
        records = [card for player in observation.get("players", [])
                   for zone in ("hand", "battlefield", "graveyard", "exile", "command")
                   for card in player.get(zone, [])]
        records += observation.get("stack", [])
        for card in records:
            if isinstance(card.get("object_id"), str):
                refs[card["object_id"]] = {f: card.get(f) for f in fields}
        for card in observation.get("known", []):
            if isinstance(card.get("object_id"), str):
                refs[card["object_id"]] = {**{f: card.get(f) for f in fields}, "controller_seat": card.get("owner_seat")}
    for ref in queue:
        if (not isinstance(ref, dict) or set(ref) != set(fields)
                or not isinstance(ref.get("object_id"), str) or not ref["object_id"]
                or not isinstance(ref.get("card_name"), str) or not ref["card_name"]
                or wire.canonical_json_dumps(ref) != wire.canonical_json_dumps(refs.get(ref["object_id"]))):
            raise ValueError("original serving target queue has a foreign or hidden reference")
    # The JVM also compares every complete source against the actual permitted
    # observation and UUID binding before restoring the original rules.
    wire.canonical_json_dumps(value)


def bound_replay(record, seat):
    anchor, replay = record["anchor"], record["replay"]
    if (not isinstance(anchor, dict) or set(anchor) != {
            "decision", "selection", "priority_pass_after_activation", "original_priority_state"}
            or type(anchor["priority_pass_after_activation"]) is not bool
            or not isinstance(replay, dict) or set(replay) != {"priority_passes", "earlier"}
            or not isinstance(replay["priority_passes"], list) or not isinstance(replay["earlier"], list)
            or len(replay["earlier"]) > 4096):
        raise ValueError("original serving needs bounded recorded priority replay")
    root = anchor["decision"]
    offered = bound_decision(root, seat)
    bound_selection(anchor["selection"], offered)
    priority_state(anchor["original_priority_state"], root)
    action = anchor["selection"]["semantic_echo"].get("kind")
    if (root.get("context", {}).get("kind") != "priority"
            or action not in ("pass", "cast_spell", "activate_ability", "play_land", "activate_mana_ability")):
        raise ValueError("original serving replay has no selected priority action")
    if action == "pass":
        passed = root["observation"].get("passed_seats")
        other = "p1" if seat == "p0" else "p0"
        if (not isinstance(root["observation"].get("stack"), list) or not root["observation"]["stack"]
                or anchor["priority_pass_after_activation"] or not isinstance(passed, list)
                or any(p not in ("p0", "p1") for p in passed) or len(set(passed)) != len(passed)
                or seat in passed or replay["priority_passes"] != ([] if other in passed else [other])):
            raise ValueError("original resolution replay has no exact public stack/pass anchor")
    elif replay["priority_passes"]:
        raise ValueError("original activation replay has unrecorded priority passes")
    for entry in replay["earlier"]:
        if not isinstance(entry, dict) or set(entry) != {"decision", "selection"}:
            raise ValueError("malformed original serving replay prefix")
    previous = root
    entries = [*replay["earlier"], {"decision": record["decision"]}]
    for index, entry in enumerate(entries):
        current = entry["decision"]
        choices = bound_decision(current, seat)
        if (type(previous.get("seat_step")) is not int or type(current.get("seat_step")) is not int
                or not 0 <= previous["seat_step"] < current["seat_step"] <= wire.MAX_JSON_INT
                or current["seat_step"] != previous["seat_step"] + 1
                or current.get("context", {}).get("kind") not in (
                    ("choice", "priority") if index == len(entries) - 1 else ("choice",))
                or any(current["observation"].get(key) != root["observation"].get(key)
                       for key in ("turn", "phase_step"))):
            raise ValueError("original serving replay crossed an unrecorded step, turn or phase")
        if "selection" in entry:
            bound_selection(entry["selection"], choices)
        previous = current


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
            self.checkpoint = owner.session.checkpoint
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
        required = {"game_start", "decision", "world_seed", "id_seed"}
        if not isinstance(record, dict) or set(record) not in (required, required | {"anchor", "replay"}):
            raise ValueError("original serving needs a bound decision and declared reconstruction seeds")
        record = copy.deepcopy(record)
        if digest(record["game_start"]) != self.start_sha256:
            raise ValueError("original serving request belongs to another game")
        for key in ("world_seed", "id_seed"):
            if not isinstance(record[key], str) or not re.fullmatch("[a-f0-9]{64}", record[key]):
                raise ValueError("original serving reconstruction seed differs from its declared shape")
        bound = bound_decision(record["decision"], self.start["seat"])
        if "anchor" in record:
            bound_replay(record, self.start["seat"])
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
                bound_selection(selection, offered)
                if (not isinstance(flags, list) or any(not isinstance(flag, str)
                            or flag.startswith(("unsupported:", "horizon:")) for flag in flags)):
                    raise ValueError("original serving result is not an exact supported offered choice")
                if record["decision"].get("context", {}).get("kind") == "priority":
                    if type(result.get("priority_pass_after_activation")) is not bool:
                        raise ValueError("original serving lost its priority continuation")
                    priority_state(result.get("original_priority_state"), record["decision"])
                if "anchor" in record:
                    resolution = record["anchor"]["selection"]["semantic_echo"].get("kind") == "pass"
                    if ((result.get("original_resolution_path") is not True if resolution else result.get("original_activation_path") is not True)
                            or type(result.get("original_dialog_prefix_replayed")) is not int
                            or result["original_dialog_prefix_replayed"] != len(record["replay"]["earlier"])):
                        raise ValueError("original serving callback lost its actual activation or replay prefix")
                    if resolution and (result.get("original_activation_path") is not False
                                       or type(result.get("original_priority_passes_replayed")) is not int
                                       or result["original_priority_passes_replayed"] != len(record["replay"]["priority_passes"])):
                        raise ValueError("original serving resolution lost its recorded pass order")
                    if record["decision"].get("context", {}).get("kind") == "priority":
                        deferred = result.get("original_activation_pass_deferred")
                        if (result.get("original_priority_continuation") is not True or type(deferred) is not bool
                                or (deferred or record["anchor"]["priority_pass_after_activation"])
                                and (selection["semantic_echo"].get("kind") != "pass" or calls != 0)):
                            raise ValueError("original serving continuation lost its automatic pass or added inference")
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
