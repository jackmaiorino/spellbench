"""Owned original Jack combat loops, paired inference and shared game chooser."""
from __future__ import annotations

import copy
import math
import re
import time

from spellbench import wire
from xmage_jack_inference import validate_features, validate_scores
from xmage_jack_modes import ModeSession
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256, COMBAT_VARIANT
from xmage_neural_combat import CombatPlan, battlefield, combat_kind, select_candidate, target
from xmage_neural_decisions import decision_hash, load_response

SOURCE_KEYS = ("embedding_cache_sha256", "encoder_source_sha256", "candidate_source_sha256", "combat_rules_source_sha256")


def validate_round(decision, frame):
    family = combat_kind(decision)
    viewer, objects = battlefield(decision)
    kind, count = frame.get("type"), frame.get("candidate_count")
    sequential = kind != "DECLARE_ATTACK_TARGET"
    if (kind not in (("DECLARE_ATTACKS", "DECLARE_ATTACK_TARGET") if family == "attack" else ("DECLARE_BLOCKS",))
            or type(count) is not int or not 2 <= count <= 64
            or type(frame.get("sequential")) is not bool or frame["sequential"] != sequential
            or type(frame.get("picks")) is not int or frame["picks"] != (count if sequential else 1)
            or frame.get("decision_sha256") != decision_hash(decision)):
        raise ValueError("original combat round changed its head, count or selection shape")
    refs = frame.get("candidate_refs")
    if (not isinstance(refs, list) or len(refs) != count or any(not isinstance(r, dict) or set(r) != {"creature", "context"} for r in refs)
            or len({wire.canonical_json_dumps(r) for r in refs}) != count):
        raise ValueError("original combat candidates are incomplete or aliased")
    for i, ref in enumerate(refs):
        creature, context = ref["creature"], ref["context"]
        if sequential and (creature is None) != (i == count-1) or not sequential and creature is None:
            raise ValueError("original combat DONE must be last, with no target-round DONE")
        if creature is not None and (creature not in objects or objects[creature].get("controller_seat") != viewer):
            raise ValueError("original combat candidate is an unknown or opposing creature")
        if kind == "DECLARE_ATTACKS":
            if context is not None: raise ValueError("attack-selection candidate has a defender context")
        elif kind == "DECLARE_BLOCKS":
            opposing = target(context)
            oid = None if opposing is None else opposing.get("object_id")
            if (oid not in objects or objects[oid].get("controller_seat") == viewer
                    or objects[oid].get("permanent", {}).get("attacking") is not True
                    or context != refs[0]["context"]):
                raise ValueError("block round changed its opposing attacking creature")
        else:
            defender = target(context)
            if (creature != refs[0]["creature"] or defender is None or defender.get("player") == viewer
                    or "object_id" in defender and (defender["object_id"] not in objects
                                                   or objects[defender["object_id"]].get("controller_seat") == viewer)):
                raise ValueError("attack-target round changed its creature or permitted defender")
    if "features" in frame:
        features = frame["features"]
        validate_features(features)
        if (features.get("kind") != "candidates" or features.get("head") != ("block" if family == "block" else "attack")
                or features["candidate_mask"] != [True]*count+[False]*(64-count)
                or any(features["candidate_ids"][count:])
                or any(any(row) for row in features["candidate_features"][count:])):
            raise ValueError("combat features changed their original head, mask or padded slots")


def validate_result(decision, result, observed_rounds, request_hash):
    family = combat_kind(decision)
    viewer, objects = battlefield(decision)
    if (result.get("decision_sha256") != decision_hash(decision) or result.get("request_sha256") != request_hash
            or result.get("combat") != family or result.get("variant") != COMBAT_VARIANT
            or type(result.get("neural_calls")) is not int or result["neural_calls"] != len(observed_rounds)
            or wire.canonical_json_dumps(result.get("rounds")) != wire.canonical_json_dumps(observed_rounds)):
        raise ValueError("combat result differs from its request or observed original choices")
    flags, pairs = result.get("world_flags"), result.get("pairs")
    if (not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("unsupported:", "horizon:")) for f in flags)
            or not isinstance(pairs, list)):
        raise ValueError("combat result ran outside its supported world or lost its plan")
    selected, assigned = [], {}
    target_position = -1
    for index, round_ in enumerate(observed_rounds):
        validate_round(decision, round_)
        refs = round_["candidate_refs"]
        indices = round_["indices"]
        if (not isinstance(indices, list) or len(indices) != round_["picks"]
                or any(type(i) is not int or not 0 <= i < len(refs) for i in indices)
                or len(set(indices)) != len(indices)):
            raise ValueError("original combat receipt lost or aliased its sequential picks")
        used = []
        for i in indices:
            if refs[i]["creature"] is None: break
            used.append(refs[i])
        if family == "attack":
            if index == 0:
                if round_["type"] != "DECLARE_ATTACKS": raise ValueError("original attack needs its selection round first")
                selected = [ref["creature"] for ref in used]
            else:
                if round_["type"] != "DECLARE_ATTACK_TARGET" or refs[0]["creature"] not in selected:
                    raise ValueError("original defender choice precedes selection or changes its attacker")
                position = selected.index(refs[0]["creature"])
                if position <= target_position: raise ValueError("original defender choices changed attacker order")
                target_position = position
                assigned[used[0]["creature"]] = target(used[0]["context"])
        else:
            for ref in used:
                if ref["creature"] in assigned: raise ValueError("original blocker pool reused a declared blocker")
                assigned[ref["creature"]] = target(ref["context"])["object_id"]
    seen = set()
    for pair in pairs:
        name = "attacker" if family == "attack" else "blocker"
        if not isinstance(pair, dict) or set(pair) != {name, "defender" if family == "attack" else "attacker"}:
            raise ValueError("combat pair schema changed")
        oid = pair[name]
        if oid not in objects or objects[oid].get("controller_seat") != viewer or oid in seen:
            raise ValueError("combat pair uses an opposing, unknown or reused creature")
        seen.add(oid)
        if family == "attack":
            defender = target(pair["defender"])
            if (defender is None or defender.get("player") == viewer
                    or "object_id" in defender and (defender["object_id"] not in objects or objects[defender["object_id"]].get("controller_seat") == viewer)):
                raise ValueError("combat pair attacks an unknown or own defender")
            if oid not in selected or oid in assigned and assigned[oid] != defender:
                raise ValueError("combat attack differs from the original selected attacker or defender")
        else:
            attacker = objects.get(pair["attacker"])
            if attacker is None or attacker.get("controller_seat") == viewer or attacker.get("permanent", {}).get("attacking") is not True:
                raise ValueError("combat pair blocks an unknown or nonattacking creature")
            if assigned.get(oid) != pair["attacker"]:
                raise ValueError("combat block differs from the original selected blocker or attacker")


class JackCombatPlan(CombatPlan):
    """Bind a validated Jack plan to consecutive offered declaration substeps."""
    def __init__(self, decision, result, *, observed_rounds, request_hash):
        validate_result(decision, result, observed_rounds, request_hash)
        self._initialize(decision, result)


class CombatSession(ModeSession):
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "jack-permitted-combat"
    VARIANT = COMBAT_VARIANT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if (self.sources["encoder_source_sha256"] != ENCODER_SHA256
                or self.sources["candidate_source_sha256"] != CALLBACK_SHA256):
            self.failed = True; self.close()
            raise ValueError("combat sources differ from the paired original encoder")

    def plan(self, decision, *, world_seed, id_seed, timeout_s):
        if self.closed or self.failed: raise ValueError("combat session is closed or failed")
        try:
            if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("combat needs a positive finite shared clock")
            deadline = time.monotonic()+timeout_s
            def remaining():
                value = deadline-time.monotonic()
                if value <= 0: raise TimeoutError("combat exhausted its shared clock")
                return value
            decision = copy.deepcopy(decision)
            combat_kind(decision)
            viewer, _ = battlefield(decision)
            group = CombatPlan._group(decision)
            candidates = decision["candidates"]
            ids = [c.get("candidate_id") for c in candidates]
            if (viewer != self.start.get("seat") or decision.get("acting_seat") != viewer
                    or group["substep_index"] != 0
                    or decision.get("context", {}).get("rewind") is not False
                    or any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids) or len(set(ids)) != len(ids)
                    or any(not isinstance(s, str) or not re.fullmatch("[a-f0-9]{64}", s) for s in (world_seed, id_seed))):
                raise ValueError("combat needs this game's initial permitted declaration group and seeds")
            self.sequence += 1; rid = str(self.sequence)
            request = {"id":rid, "game_start":self.start, "decision":decision, "world_seed":world_seed, "id_seed":id_seed}
            self.peer.set_timeout(remaining()); self.peer.write_line(wire.canonical_json_dumps(request))
            rounds = []
            base_state = None
            while True:
                self.peer.set_timeout(remaining()); message = load_response(self.peer.read_line())
                if message.get("id") != rid: raise ValueError("combat returned a stale request ID")
                if message.get("event") == "result":
                    if message.get("ok") is not True: raise ValueError("original combat callback refused")
                    result = message.get("result")
                    if not isinstance(result, dict): raise ValueError("combat result is missing")
                    plan = JackCombatPlan(decision, result, observed_rounds=rounds, request_hash=decision_hash(request))
                    result = {**result, "checkpoint":self.model.checkpoint, "selection":select_candidate(decision, result)}
                    remaining()
                    return result, plan
                if message.get("event") != "choose" or type(message.get("call")) is not int or message["call"] != len(rounds)+1:
                    raise ValueError("combat lost or reordered original rounds")
                if len(rounds) >= 4096: raise ValueError("combat exceeds the declared round envelope")
                validate_round(decision, message)
                current_base = {key:message["features"][key] for key in ("sequence", "padding", "token_ids")}
                if base_state is not None and wire.canonical_json_dumps(current_base) != base_state:
                    raise ValueError("original combat changed its cached base state within a callback")
                base_state = wire.canonical_json_dumps(current_base)
                scores = self.model.score(message["features"], timeout_s=remaining())
                scores = validate_scores(scores, message["features"], self.model.encoding["mulligan_format"])
                indices = self.selection.choose(scores["probabilities"], message["features"]["candidate_mask"],
                        count=message["candidate_count"], picks=message["picks"], sequential=message["sequential"], timeout_s=remaining())
                receipt = {key:copy.deepcopy(value) for key,value in message.items() if key not in ("id", "event", "features")}
                receipt["indices"] = indices; rounds.append(receipt)
                self.peer.set_timeout(remaining())
                self.peer.write_line(wire.canonical_json_dumps({"id":rid, "call":message["call"], "ok":True, "indices":indices}))
        except BaseException:
            self.failed = True; self.close(); raise
