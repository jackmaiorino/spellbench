"""Apply the original game-owned chooser to a validated priority feature frame.

Frames come from MaintainerPriorityBinding and the original rules' chooser hook.
This does not replace simulation callbacks or qualify a complete player.
"""
from __future__ import annotations

import copy
import math
import re
import time

from spellbench import wire
from xmage_maintainer_inference import validate_features, validate_scores
from xmage_maintainer_selection import GREEDY, PROFILES
from xmage_maintainer_sources import CALLBACK_SHA256, ENCODER_SHA256
from xmage_neural_decisions import decision_hash

SOURCE_KEYS = ("embedding_cache_sha256", "encoder_source_sha256", "candidate_source_sha256", "priority_rules_source_sha256")
VARIANT = ("original validated priority order and first 64 slots; exact permitted public binding; "
           "pass-only shortcut; original copied callbacks, activation and full games unfinished")


def validate_frame(decision, frame, sources):
    obs = decision.get("observation", {})
    if (not isinstance(obs, dict) or obs.get("viewer") != decision.get("acting_seat")
            or decision.get("context", {}).get("kind") != "priority"):
        raise ValueError("original priority requires the acting permitted viewer")
    if (not isinstance(frame, dict) or frame.get("schema") != "spellbench-maintainer-original-priority/v1"
            or frame.get("variant") != VARIANT or frame.get("decision_sha256") != decision_hash(decision)
            or frame.get("original_callback_sha256") != CALLBACK_SHA256 or frame.get("sources") != sources
            or frame.get("full_priority_player_qualified") is not False):
        raise ValueError("priority frame is not bound to the original rules and this decision")
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 4096:
        raise ValueError("original priority needs its offered choices")
    offered, semantics = {}, set()
    for candidate in candidates:
        if not isinstance(candidate, dict): raise ValueError("malformed priority candidate")
        cid, semantic = candidate.get("candidate_id"), candidate.get("semantic")
        if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in offered
                or not isinstance(semantic, dict) or wire.canonical_json_dumps(semantic) in semantics):
            raise ValueError("offered priority IDs or semantics are invalid or aliased")
        offered[cid] = semantic; semantics.add(wire.canonical_json_dumps(semantic))
    refs, count, flags = frame.get("candidate_refs"), frame.get("candidate_count"), frame.get("world_flags")
    if (type(count) is not int or not 1 <= count <= 64 or not isinstance(refs, list) or len(refs) != count
            or not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("unsupported:", "horizon:")) for f in flags)):
        raise ValueError("original priority prefix or world is invalid")
    bound, used = {}, set()
    for index, ref in enumerate(refs):
        if (not isinstance(ref, dict) or set(ref) != {"index", "candidate_id", "semantic"}
                or type(ref.get("index")) is not int or ref["index"] != index
                or type(ref.get("candidate_id")) is not int or ref["candidate_id"] not in offered
                or ref["candidate_id"] in used
                or wire.canonical_json_dumps(ref["semantic"]) != wire.canonical_json_dumps(offered[ref["candidate_id"]])):
            raise ValueError("original priority slot lost its exact offered binding")
        used.add(ref["candidate_id"]); bound[index] = ref["candidate_id"]
    if refs[0]["semantic"] != {"kind": "pass"}:
        raise ValueError("original priority PassAbility must occupy slot zero")
    features = frame.get("features")
    if count == 1:
        if features is not None: raise ValueError("pass-only priority must not invoke inference")
    else:
        validate_features(features)
        if (features.get("kind") != "candidates" or features.get("head") != "action"
                or features["candidate_mask"] != [True] * count + [False] * (64-count)
                or any(features["candidate_ids"][count:]) or any(any(row) for row in features["candidate_features"][count:])):
            raise ValueError("original priority features changed their action head, prefix or padding")
    return offered, bound, features


class PrioritySelection:
    """Reuse the same paired model, chooser and RNG as other original callbacks."""
    def __init__(self, model, selection, *, game_start, sources, profile=GREEDY):
        self.model, self.selection = model, selection
        self.start, self.sources = copy.deepcopy(game_start), copy.deepcopy(sources)
        self.profile = profile; self.failed = self.closed = False
        try:
            if (set(sources) != set(SOURCE_KEYS) or any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in sources.values())
                    or type(self.start.get("agent_seed")) is not int
                    or type(selection.seed) is not int
                    or profile not in PROFILES or selection.profile != profile or selection.seed != self.start.get("agent_seed")
                    or model.game_start_sha256 != decision_hash(self.start)
                    or model.encoding.get("state_encoder_sha256") != ENCODER_SHA256
                    or model.encoding.get("callback_sha256") != CALLBACK_SHA256
                    or model.encoding.get("card_embeddings_sha256") != sources["embedding_cache_sha256"]):
                raise ValueError("priority selection needs the same game, paired model and original chooser")
            selection.bind_game_start(self.start)
        except BaseException:
            self.failed = True; self.close(); raise

    def choose(self, decision, encoded, *, timeout_s):
        if self.closed or self.failed: raise ValueError("priority selection is closed or failed")
        try:
            if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("priority selection needs a positive finite remaining clock")
            deadline = time.monotonic() + timeout_s
            def remaining():
                value = deadline - time.monotonic()
                if value <= 0: raise TimeoutError("original priority exhausted its shared clock")
                return value
            decision, encoded = copy.deepcopy(decision), copy.deepcopy(encoded)
            if self.start.get("seat") != decision.get("acting_seat"):
                raise ValueError("priority decision belongs to another seat")
            if encoded.get("game_start_sha256") != decision_hash(self.start):
                raise ValueError("priority frame belongs to another game")
            if any(c.get("semantic", {}).get("kind") == "activate_mana_ability" for c in decision.get("candidates", [])):
                profile = self.start.get("engine_profile", {})
                kinds = profile.get("decision_kinds") if isinstance(profile, dict) else None
                if not isinstance(kinds, list) or "activate_mana_ability" not in kinds:
                    raise ValueError("priority mana requires the declared opt-in profile")
            offered, bound, features = validate_frame(decision, encoded, self.sources)
            scores = None; index = 0
            if features is not None:
                scores = self.model.score(features, timeout_s=remaining())
                scores = validate_scores(scores, features, self.model.encoding.get("mulligan_format"))
                indices = self.selection.choose(scores["probabilities"], features["candidate_mask"], count=len(bound),
                    picks=1, sequential=False, timeout_s=remaining())
                if (not isinstance(indices, list) or len(indices) != 1 or type(indices[0]) is not int or indices[0] not in bound):
                    raise ValueError("original priority chooser returned an unbound slot")
                index = indices[0]
            cid = bound[index]; remaining()
            return {"selection": {"candidate_id": cid, "semantic_echo": offered[cid]}, "scores": scores,
                    "decision_sha256": encoded["decision_sha256"], "profile": self.profile, "variant": VARIANT,
                    "world_flags": encoded["world_flags"], "full_priority_player_qualified": False}
        except BaseException:
            self.failed = True; self.close(); raise

    def close(self):
        if self.closed: return
        self.closed = True
        try: self.selection.close()
        finally: self.model.close()
