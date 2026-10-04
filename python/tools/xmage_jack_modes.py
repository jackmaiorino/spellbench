"""Original spell-mode features, paired inference and the owned Java chooser.

The encoder reaches the actual callback by permitted replay. Single modes
and exhausted modes bypass inference and preserve the original RNG history.
Other callbacks and complete game qualification remain unfinished.
"""
from __future__ import annotations

import copy
import math
import re
import struct
import time

from spellbench import observation, wire
from xmage_jack_inference import validate_features, validate_scores
from xmage_jack_selection import GREEDY, PROFILES
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256, MODE_VARIANT, MODE_MANA_VARIANT
from xmage_neural_decisions import decision_hash, load_response

SOURCE_KEYS = ("encoder_source_sha256", "candidate_source_sha256", "mode_rules_source_sha256", "embedding_cache_sha256")
MANA_SOURCE_KEYS = SOURCE_KEYS + ("dialog_rules_source_sha256",)


def bound_view(start: dict, decision: dict) -> dict[int, dict]:
    obs, context = decision.get("observation", {}), decision.get("context", {})
    seat, source = start.get("seat"), context.get("source")
    if (seat not in ("p0", "p1") or seat != decision.get("acting_seat") or seat != obs.get("viewer")
            or context.get("kind") != "choice" or not isinstance(source, dict)
            or source.get("controller_seat") != seat or not source.get("card_name")):
        raise ValueError("Jack modes need the acting viewer's named callback source")
    try:
        refs = [ref for _, ref in observation.observation_objects(obs) if ref["object_id"] == source.get("object_id")]
    except (KeyError, TypeError) as exc:
        raise ValueError("mode source observation is incomplete") from exc
    if not refs or any(wire.canonical_json_dumps(ref) != wire.canonical_json_dumps(source) for ref in refs):
        raise ValueError("mode source differs from its visible reference")
    offered, modes, finish, metadata = {}, set(), False, None
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 4097:
        raise ValueError("Jack mode needs its offered action list")
    for candidate in candidates:
        cid, semantic = candidate.get("candidate_id"), candidate.get("semantic", {})
        if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in offered
                or wire.canonical_json_dumps(semantic.get("source")) != wire.canonical_json_dumps(source)):
            raise ValueError("mode actions are aliased or belong to another source")
        count = semantic.get("selected_count")
        if type(count) is not int or count < 0:
            raise ValueError("mode action needs its actual selected count")
        if semantic.get("kind") == "choose_spell_mode":
            index, total, minimum, maximum = (semantic.get(k) for k in ("mode_index", "mode_count", "minimum", "maximum"))
            if (any(type(v) is not int for v in (index, total, minimum, maximum))
                    or not 0 <= index < total <= 4096 or index in modes or not 0 <= minimum <= maximum <= total):
                raise ValueError("mode index or range is invalid")
            current = (total, count, minimum, maximum)
            if metadata is not None and metadata != current:
                raise ValueError("mode actions disagree on their actual count and range")
            metadata = current; modes.add(index)
        elif semantic.get("kind") == "finish_selection" and semantic.get("purpose") == "modes" and not finish:
            finish = True
        else:
            raise ValueError("mode decision mixes unrelated or repeated actions")
        offered[cid] = semantic
    if metadata is not None and any(s["selected_count"] != metadata[1] for s in offered.values()):
        raise ValueError("mode finish has a different selected count")
    return offered


def validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    return _validate_encoding(start, decision, encoded, sources, request_hash, original_mana=False)


def validate_mana_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    return _validate_encoding(start, decision, encoded, sources, request_hash, original_mana=True)


def _validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str, *, original_mana: bool):
    keys = MANA_SOURCE_KEYS if original_mana else SOURCE_KEYS
    if (not isinstance(sources, dict) or set(sources) != set(keys)
            or any(not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value) for value in sources.values())):
        raise ValueError("mode frame needs every original staged source pin")
    offered = bound_view(start, decision)
    expected = {"schema":"spellbench-jack-mode-features/v1", "decision_sha256":decision_hash(decision),
                "game_start_sha256":decision_hash(start), "request_sha256":request_hash,
                "original_callback_sha256":CALLBACK_SHA256,
                "variant":MODE_MANA_VARIANT if original_mana else MODE_VARIANT, **sources}
    if wire.canonical_json_dumps({k:encoded.get(k) for k in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("mode frame differs from its original sources, game, decision or replay request")
    available, count, order = (encoded.get(k) for k in ("available_count", "candidate_count", "original_mode_indices"))
    if (type(available) is not int or not 0 <= available <= 4096 or type(count) is not int or count != min(64, available)
            or not isinstance(order, list) or len(order) != count
            or any(type(i) is not int or not 0 <= i < 4096 for i in order) or len(set(order)) != count):
        raise ValueError("mode frame changed the original order or 64-slot cap")
    costs = encoded.get("original_mode_cost_flags") if original_mana else [False]*count
    if not isinstance(costs, list) or len(costs) != count or any(type(value) is not bool for value in costs):
        raise ValueError("mode frame changed its original cost-presence flags")
    flags = encoded.get("world_flags")
    if (not isinstance(flags, list) or any(not isinstance(f, str) for f in flags)
            or any(f.startswith(("unsupported:", "horizon:")) for f in flags)):
        raise ValueError("mode frame has unsupported reconstruction flags")
    if available <= 1:
        cid = encoded.get("forced_candidate_id")
        semantic = offered.get(cid) if type(cid) is int else None
        reason = "single_available_mode" if available else "no_available_modes"
        if (encoded.get("kind") != "jack-mode-forced" or encoded.get("reason") != reason or semantic is None
                or available and (semantic.get("kind") != "choose_spell_mode" or semantic["mode_index"] != order[0])
                or not available and semantic.get("kind") != "finish_selection"):
            raise ValueError("forced mode differs from the original callback's direct return")
        return None, {0:cid}
    validate_features(encoded)
    if encoded["head"] != "action" or any(encoded["candidate_mask"][count:]):
        raise ValueError("mode features changed the original policy head or mask tail")
    for i in range(64):
        row, ident = encoded["candidate_features"][i], encoded["candidate_ids"][i]
        ordinal = struct.unpack("!f", struct.pack("!f", i / count))[0] if i < count else 0
        if (row[0] != ordinal or i < count and (ident == 0 or row[13] != int(costs[i]))
                or i >= count and (ident != 0 or any(row))):
            raise ValueError("mode ordinal feature or original padding differs")
    refs = encoded.get("candidate_refs")
    if not isinstance(refs, list): raise ValueError("mode needs offered action bindings")
    bound, used = {}, set()
    for ref in refs:
        i, cid, mode = (ref.get(k) for k in ("index", "candidate_id", "mode_index"))
        semantic = offered.get(cid) if type(cid) is int else None
        if (type(i) is not int or not 0 <= i < count or i in bound or cid in used
                or not encoded["candidate_mask"][i] or type(mode) is not int or mode != order[i]
                or semantic is None or semantic.get("kind") != "choose_spell_mode" or semantic["mode_index"] != mode):
            raise ValueError("original mode slot is unbound, repeated or not offered")
        bound[i] = cid; used.add(cid)
    if set(bound) != {i for i, legal in enumerate(encoded["candidate_mask"]) if legal}:
        raise ValueError("original legal mode slots have incomplete offered bindings")
    features = {k:encoded[k] for k in ("kind", "head", "sequence", "padding", "token_ids", "candidate_features",
                                      "candidate_ids", "candidate_mask")}
    return features, bound


class ModeSession:
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "jack-permitted-mode"
    VARIANT = MODE_VARIANT
    bound_view = staticmethod(bound_view)
    validate_encoding = staticmethod(validate_encoding)

    def __init__(self, peer, model, selection, *, game_start: dict, sources: dict, profile: str = GREEDY):
        self.peer, self.model, self.selection = peer, model, selection
        self.start, self.sources = copy.deepcopy(game_start), copy.deepcopy(sources)
        self.profile, self.sequence = profile, 0
        self.closed = self.failed = False
        try:
            if (set(sources) != set(self.SOURCE_KEYS) or any(not isinstance(s, str) or not re.fullmatch("[a-f0-9]{64}", s)
                    for s in sources.values()) or profile not in PROFILES or selection.profile != profile
                    or type(self.start.get("agent_seed")) is not int or selection.seed != self.start["agent_seed"]
                    or model.game_start_sha256 != decision_hash(self.start)
                    or model.encoding.get("state_encoder_sha256") != ENCODER_SHA256
                    or model.encoding.get("callback_sha256") != CALLBACK_SHA256
                    or model.encoding.get("card_embeddings_sha256") != sources["embedding_cache_sha256"]):
                raise ValueError("mode component needs the same game, original paired model and chooser profile")
            selection.bind_game_start(self.start)
            ready = load_response(peer.read_line())
            expected = {"ready":True, "encoder":self.ENCODER, "original_callback_sha256":CALLBACK_SHA256,
                        "variant":self.VARIANT, **sources}
            if (wire.canonical_json_dumps({k:ready.get(k) for k in expected}) != wire.canonical_json_dumps(expected)
                    or type(ready.get("embedding_count")) is not int or ready["embedding_count"] <= 0):
                raise ValueError("mode encoder readiness differs from its original staged sources")
        except BaseException:
            self.failed = True; self.close(); raise

    def choose(self, decision: dict, *, anchor: dict, replay: dict, world_seed: str, id_seed: str, timeout_s: float) -> dict:
        if self.closed or self.failed: raise ValueError("mode session is closed or failed")
        try:
            if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("mode needs a positive finite shared clock")
            deadline = time.monotonic() + timeout_s
            def remaining():
                value = deadline-time.monotonic()
                if value <= 0: raise TimeoutError("mode exhausted its shared clock")
                return value
            decision = copy.deepcopy(decision)
            offered = self.bound_view(self.start, decision)
            if not isinstance(anchor, dict) or not isinstance(replay, dict):
                raise ValueError("mode requires an explicit priority anchor and recorded callback prefix")
            if any(not isinstance(s, str) or not re.fullmatch("[a-f0-9]{64}", s) for s in (world_seed, id_seed)):
                raise ValueError("mode seeds must be 32-byte hexadecimal strings")
            self.sequence += 1; rid = str(self.sequence)
            request = copy.deepcopy({"id":rid, "game_start":self.start, "decision":decision, "anchor":anchor,
                                     "replay":replay, "world_seed":world_seed, "id_seed":id_seed})
            self.peer.set_timeout(remaining()); self.peer.write_line(wire.canonical_json_dumps(request))
            self.peer.set_timeout(remaining()); result = load_response(self.peer.read_line())
            if result.get("id") != rid or result.get("ok") is not True or not isinstance(result.get("encoded"), dict):
                raise ValueError("mode encoder refused or returned a stale request")
            encoded = result["encoded"]
            features, bound = self.validate_encoding(self.start, decision, encoded, self.sources, decision_hash(request))
            scores = None
            if features is None: cid = bound[0]
            else:
                scores = self.model.score(features, timeout_s=remaining())
                scores = validate_scores(scores, features, self.model.encoding.get("mulligan_format"))
                indices = self.selection.choose(scores["probabilities"], features["candidate_mask"],
                    count=encoded["candidate_count"], picks=1, sequential=False, timeout_s=remaining())
                if len(indices) != 1 or type(indices[0]) is not int or indices[0] not in bound:
                    raise ValueError("original mode chooser returned an unbound slot")
                cid = bound[indices[0]]
            remaining()
            return {"selection":{"candidate_id":cid, "semantic_echo":offered[cid]}, "scores":scores,
                    "decision_sha256":encoded["decision_sha256"], "checkpoint":self.model.checkpoint,
                    "profile":self.profile, "variant":self.VARIANT, "world_flags":encoded["world_flags"]}
        except BaseException:
            self.failed = True; self.close(); raise

    def close(self):
        if self.closed: return
        self.closed = True
        try: self.peer.close()
        finally:
            try: self.selection.close()
            finally: self.model.close()


class ManaModeSession(ModeSession):
    """Mode legality uses the original filtered mana rules on the permitted game."""
    SOURCE_KEYS = MANA_SOURCE_KEYS
    ENCODER = "jack-permitted-mode-mana"
    VARIANT = MODE_MANA_VARIANT
    validate_encoding = staticmethod(validate_mana_encoding)
