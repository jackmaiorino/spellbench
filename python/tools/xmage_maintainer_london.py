"""Original whole-hand London ranking, with a bound public bottoming plan."""
from __future__ import annotations

import copy
import math
import re
import time

from spellbench import wire
from xmage_maintainer_inference import validate_features, validate_scores
from xmage_maintainer_modes import ModeSession
from xmage_maintainer_sources import CALLBACK_SHA256, ENCODER_SHA256, LONDON_VARIANT
from xmage_neural_decisions import decision_hash, load_response

SOURCE_KEYS = ("embedding_cache_sha256", "encoder_source_sha256", "candidate_source_sha256", "london_rules_source_sha256")


def bound_view(start, decision):
    obs, group = decision.get("observation", {}), decision.get("group", {})
    seat = start.get("seat")
    if (seat not in ("p0", "p1") or decision.get("acting_seat") != seat or obs.get("viewer") != seat
            or obs.get("phase_step") != "pregame" or decision.get("context", {}).get("rewind") is not False
            or any(type(group.get(k)) is not int for k in ("group_id", "substep_index", "substep_count"))
            or not 0 <= group["group_id"] <= wire.MAX_JSON_INT
            or not 0 <= group["substep_index"] < group["substep_count"] <= 64
            or type(decision.get("seat_step")) is not int or not 0 <= decision["seat_step"] <= wire.MAX_JSON_INT):
        raise ValueError("London requires the acting viewer's pregame group")
    players = obs.get("players")
    own = [p for p in players if isinstance(p, dict) and p.get("seat") == seat] if isinstance(players, list) else []
    hand = own[0].get("hand") if len(own) == 1 else None
    if (not isinstance(hand, list) or not 1 <= len(hand) <= 64
            or type(own[0].get("hand_count")) is not int or own[0]["hand_count"] != len(hand)
            or group["substep_count"] > len(hand)
            or any(not isinstance(c, dict) or not isinstance(c.get("object_id"), str) or not c["object_id"]
                   or not isinstance(c.get("card_name"), str) or not c["card_name"]
                   or c.get("owner_seat") != seat or c.get("zone") != "hand" for c in hand)):
        raise ValueError("London requires the complete named own hand")
    objects = {c["object_id"]:c for c in hand}
    if len(objects) != len(hand): raise ValueError("London hand references are aliased")
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(hand)-group["substep_index"]:
        raise ValueError("London offered list has an incomplete remaining hand")
    offered, seen = {}, set()
    for candidate in candidates:
        cid, semantic = candidate.get("candidate_id"), candidate.get("semantic", {})
        item = semantic.get("item", {})
        ref = item.get("object")
        oid = ref.get("object_id") if isinstance(ref, dict) else None
        if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in offered or oid in seen
                or oid not in objects or set(item) != {"object"} or semantic.get("kind") != "order_pick"
                or semantic.get("purpose") != "mulligan_bottom" or "source" not in semantic or semantic["source"] is not None
                or type(semantic.get("position")) is not int or semantic["position"] != group["substep_index"]
                or type(semantic.get("count")) is not int or semantic["count"] != group["substep_count"]
                or wire.canonical_json_dumps(ref) != wire.canonical_json_dumps(objects[oid])):
            raise ValueError("London candidate is unbound, aliased or outside its original group")
        offered[cid] = semantic; seen.add(oid)
    return objects, offered


def validate_round(start, decision, frame, previous=()):
    objects, _ = bound_view(start, decision)
    remaining = set(objects)-set(previous)
    count = len(remaining)
    if (count < 2 or frame.get("type") != "LONDON_MULLIGAN"
            or type(frame.get("candidate_count")) is not int or frame["candidate_count"] != count
            or type(frame.get("picks")) is not int or frame["picks"] != count or frame.get("sequential") is not True
            or frame.get("decision_sha256") != decision_hash(decision)
            or not isinstance(frame.get("candidate_refs"), list) or len(frame["candidate_refs"]) != count
            or any(not isinstance(r, str) for r in frame["candidate_refs"])
            or len(set(frame["candidate_refs"])) != count or set(frame["candidate_refs"]) != remaining):
        raise ValueError("London ranking changed its whole-hand count, order bindings or draw shape")
    if "features" in frame:
        features = frame["features"]; validate_features(features)
        if (features.get("kind") != "candidates" or features.get("head") != "card_select"
                or features["candidate_mask"] != [True]*count+[False]*(64-count)
                or any(features["candidate_ids"][count:]) or any(any(r) for r in features["candidate_features"][count:])):
            raise ValueError("London features changed the original head or padding")


class LondonPlan:
    def __init__(self, start, decision, result, *, rounds, request_hash):
        objects, _ = bound_view(start, decision)
        if decision["group"]["substep_index"] != 0: raise ValueError("London plan requires the first bottom substep")
        if (result.get("decision_sha256") != decision_hash(decision) or result.get("request_sha256") != request_hash
                or result.get("variant") != LONDON_VARIANT or type(result.get("neural_calls")) is not int
                or result["neural_calls"] != len(rounds)
                or wire.canonical_json_dumps(result.get("rounds")) != wire.canonical_json_dumps(rounds)):
            raise ValueError("London result differs from its original ranking and request")
        flags = result.get("world_flags")
        if not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("unsupported:", "horizon:")) for f in flags):
            raise ValueError("London result used an unsupported world")
        k = decision["group"]["substep_count"]
        expected = []
        round_index = 0
        for position in range(k):
            remaining = set(objects)-set(expected)
            if len(remaining) == 1:
                expected.append(next(iter(remaining))); continue
            if round_index >= len(rounds): raise ValueError("London lost an original shrinking-hand callback")
            ranking = rounds[round_index]; round_index += 1
            validate_round(start, decision, ranking, expected)
            indices = ranking.get("indices")
            if (not isinstance(indices, list) or len(indices) != len(remaining)
                    or any(type(i) is not int or not 0 <= i < len(remaining) for i in indices)
                    or len(set(indices)) != len(remaining)):
                raise ValueError("London receipt lost full-hand sequential draws")
            expected.append(ranking["candidate_refs"][indices[-1]])
        if round_index != len(rounds): raise ValueError("London added a ranking after the original bottom loop completed")
        if result.get("bottomed") != expected: raise ValueError("London bottom targets differ from each original reranking's last card")
        self.start, self.initial = copy.deepcopy(start), copy.deepcopy(decision)
        self.bottomed, self.next_index = expected, 0

    @property
    def complete(self): return self.next_index == len(self.bottomed)

    def select(self, decision):
        objects, offered = bound_view(self.start, decision)
        original, _ = bound_view(self.start, self.initial)
        group, initial_group = decision["group"], self.initial["group"]
        if (self.complete or group["group_id"] != initial_group["group_id"]
                or group["substep_count"] != len(self.bottomed) or group["substep_index"] != self.next_index
                or decision["seat_step"] != self.initial["seat_step"]+self.next_index
                or wire.canonical_json_dumps(objects) != wire.canonical_json_dumps(original)
                or {s["item"]["object"]["object_id"] for s in offered.values()} != set(objects)-set(self.bottomed[:self.next_index])):
            raise ValueError("London public substeps changed the hand, group or already picked cards")
        selected = [(cid,s) for cid,s in offered.items() if s["item"]["object"]["object_id"] == self.bottomed[self.next_index]]
        if len(selected) != 1: raise ValueError("original London card is not offered")
        self.next_index += 1
        cid, semantic = selected[0]
        return {"candidate_id":cid, "semantic_echo":copy.deepcopy(semantic)}


class LondonSession(ModeSession):
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "maintainer-permitted-london"
    VARIANT = LONDON_VARIANT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.sources["encoder_source_sha256"] != ENCODER_SHA256 or self.sources["candidate_source_sha256"] != CALLBACK_SHA256:
            self.failed = True; self.close(); raise ValueError("London requires the original paired encoder")

    def plan(self, decision, *, world_seed, id_seed, timeout_s):
        if self.closed or self.failed: raise ValueError("London session is closed or failed")
        try:
            if type(timeout_s) not in (int,float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("London needs a positive finite shared clock")
            deadline = time.monotonic()+timeout_s
            def remaining():
                value = deadline-time.monotonic()
                if value <= 0: raise TimeoutError("London exhausted its shared clock")
                return value
            decision = copy.deepcopy(decision); bound_view(self.start, decision)
            if decision["group"]["substep_index"] != 0 or any(not isinstance(s,str) or not re.fullmatch("[a-f0-9]{64}",s) for s in (world_seed,id_seed)):
                raise ValueError("London needs its initial group and permitted seeds")
            self.sequence += 1; rid = str(self.sequence)
            request = {"id":rid,"game_start":self.start,"decision":decision,"world_seed":world_seed,"id_seed":id_seed}
            self.peer.set_timeout(remaining()); self.peer.write_line(wire.canonical_json_dumps(request)); rounds = []; bottomed = []
            while True:
                self.peer.set_timeout(remaining()); message = load_response(self.peer.read_line())
                if message.get("id") != rid: raise ValueError("London returned a stale request ID")
                if message.get("event") == "result":
                    if message.get("ok") is not True or not isinstance(message.get("result"),dict): raise ValueError("original London callback refused")
                    result = message["result"]
                    plan = LondonPlan(self.start,decision,result,rounds=rounds,request_hash=decision_hash(request))
                    remaining(); return {**result,"checkpoint":self.model.checkpoint}, plan
                if (message.get("event") != "choose" or type(message.get("call")) is not int
                        or message["call"] != len(rounds)+1 or len(rounds) >= decision["group"]["substep_count"]):
                    raise ValueError("London repeated or reordered its whole-hand ranking")
                validate_round(self.start,decision,message,bottomed)
                scores = validate_scores(self.model.score(message["features"],timeout_s=remaining()),message["features"],self.model.encoding["mulligan_format"])
                indices = self.selection.choose(scores["probabilities"],message["features"]["candidate_mask"],count=message["candidate_count"],picks=message["picks"],sequential=True,timeout_s=remaining())
                receipt = {k:copy.deepcopy(v) for k,v in message.items() if k not in ("id","event","features")};receipt["indices"] = indices;rounds.append(receipt)
                bottomed.append(message["candidate_refs"][indices[-1]])
                self.peer.set_timeout(remaining()); self.peer.write_line(wire.canonical_json_dumps({"id":rid,"call":message["call"],"ok":True,"indices":indices}))
        except BaseException:
            self.failed = True; self.close(); raise
