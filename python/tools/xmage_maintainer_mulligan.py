"""Original evaluation mulligan inference on a bound, permitted pregame view.

This component owns its encoder pipe and paired inference session. It
preserves the original keep ties for both networks. Other game callbacks
and the complete maintainer agent remain unfinished.
"""
from __future__ import annotations

import copy
import math
import re
import time

from spellbench import wire
from xmage_maintainer_inference import validate_features, validate_scores
from xmage_maintainer_sources import MULLIGAN_JAVA_SHA256, MULLIGAN_VARIANT
from xmage_neural_decisions import decision_hash, load_response


def bound_view(start: dict, decision: dict) -> tuple[int, int, int]:
    obs = decision.get("observation", {})
    seat = start.get("seat")
    if (seat not in ("p0", "p1") or seat != decision.get("acting_seat") or seat != obs.get("viewer")
            or obs.get("phase_step") != "pregame"):
        raise ValueError("the maintainer's mulligan needs its own acting pregame viewer")
    players = obs.get("players")
    own = [p for p in players if isinstance(p, dict) and p.get("seat") == seat] if isinstance(players, list) else []
    if len(own) != 1:
        raise ValueError("mulligan needs one observed own player")
    player = own[0]
    count, hand, library = player.get("mulligans_taken"), player.get("hand"), player.get("library_count")
    if (type(count) is not int or not 0 <= count <= 7 or not isinstance(hand, list) or not 1 <= len(hand) <= 7
            or type(player.get("hand_count")) is not int or player["hand_count"] != len(hand)
            or type(library) is not int or not 0 <= library <= 60
            or any(not isinstance(c, dict) or not isinstance(c.get("card_name"), str) or not c["card_name"]
                   or c.get("owner_seat") != seat or c.get("zone") != "hand" for c in hand)):
        raise ValueError("mulligan features require the whole own named hand and observed counts")
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("mulligan inference requires both offered choices")
    ids, keeps = set(), set()
    for candidate in candidates:
        cid, semantic = candidate.get("candidate_id"), candidate.get("semantic", {})
        keep = semantic.get("keep")
        if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in ids
                or semantic.get("kind") != "mulligan" or type(keep) is not bool or keep in keeps
                or type(semantic.get("mulligans_taken")) is not int or semantic["mulligans_taken"] != count
                or type(semantic.get("hand_size")) is not int or semantic["hand_size"] != len(hand)):
            raise ValueError("mulligan candidates are unbound or aliased")
        ids.add(cid); keeps.add(keep)
    return count, len(hand), library


def validate_encoding(start: dict, decision: dict, encoded: dict, source: str) -> dict:
    count, hand, library = bound_view(start, decision)
    expected = {"schema":"spellbench-maintainer-mulligan-features/v1", "kind":"mulligan",
                "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
                "original_mulligan_encoder_sha256":MULLIGAN_JAVA_SHA256,
                "mulligan_encoder_source_sha256":source, "mulligans_taken":count,
                "hand_size":hand, "remaining_library_size":library, "variant":MULLIGAN_VARIANT}
    if wire.canonical_json_dumps({k:encoded.get(k) for k in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("mulligan encoding differs from its decision, original source or game")
    validate_features(encoded)
    values = encoded["values"]
    if (values[0] != count or type(values[1]) is not int or not 0 <= values[1] <= hand
            or type(values[2]) is not int or not 0 <= values[2] <= hand-values[1] or values[3] < 0
            or any(v == 0 for v in values[4:4+hand]) or any(values[4+hand:11])
            or any(v == 0 for v in values[11:11+library]) or any(values[11+library:])):
        raise ValueError("original mulligan counts or padded IDs differ from the observed own zones")
    flags = encoded.get("world_flags")
    if (not isinstance(flags, list) or any(not isinstance(f, str) for f in flags)
            or any(f.startswith(("unsupported:", "horizon:")) for f in flags)):
        raise ValueError("mulligan encoder returned unsupported reconstruction flags")
    return {"kind":"mulligan", "values":values}


class MulliganSession:
    def __init__(self, peer, model, *, game_start: dict, staged_source_sha256: str):
        self.peer, self.model = peer, model
        self.start = copy.deepcopy(game_start)
        self.source = staged_source_sha256
        self.sequence = 0
        self.closed = self.failed = False
        try:
            if not isinstance(self.source, str) or re.fullmatch("[a-f0-9]{64}", self.source) is None:
                raise ValueError("mulligan needs its staged source SHA-256")
            if model.encoding.get("mulligan_format") not in ("keep-logit", "keep-mull-q"):
                raise ValueError("mulligan needs the original declared network format")
            if getattr(model, "game_start_sha256", None) != decision_hash(self.start):
                raise ValueError("mulligan and paired network must belong to the exact same game start")
            ready = {"ready":True, "encoder":"maintainer-permitted-mulligan",
                     "original_mulligan_encoder_sha256":MULLIGAN_JAVA_SHA256,
                     "mulligan_encoder_source_sha256":self.source, "variant":MULLIGAN_VARIANT}
            if wire.canonical_json_dumps(load_response(peer.read_line())) != wire.canonical_json_dumps(ready):
                raise ValueError("mulligan encoder readiness differs from its original source")
        except BaseException:
            self.failed = True
            self.close()
            raise

    def choose(self, decision: dict, *, world_seed: str, id_seed: str, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("mulligan session is closed or failed")
        try:
            if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("mulligan needs a positive finite shared clock")
            deadline = time.monotonic()+timeout_s
            def remaining():
                seconds = deadline-time.monotonic()
                if seconds <= 0: raise TimeoutError("mulligan exhausted its shared clock")
                return seconds
            decision = copy.deepcopy(decision)
            bound_view(self.start, decision)
            for seed in (world_seed, id_seed):
                if not isinstance(seed, str) or re.fullmatch("[a-f0-9]{64}", seed) is None:
                    raise ValueError("mulligan seeds must be 32-byte hexadecimal strings")
            self.sequence += 1
            rid = str(self.sequence)
            self.peer.set_timeout(remaining())
            self.peer.write_line(wire.canonical_json_dumps({"id":rid, "game_start":self.start, "decision":decision,
                                                          "world_seed":world_seed, "id_seed":id_seed}))
            self.peer.set_timeout(remaining())
            result = load_response(self.peer.read_line())
            if result.get("id") != rid or result.get("ok") is not True or not isinstance(result.get("encoded"), dict):
                raise ValueError("mulligan encoder refused or returned a stale request")
            encoded = result["encoded"]
            features = validate_encoding(self.start, decision, encoded, self.source)
            scores = self.model.score(features, timeout_s=remaining())
            scores = validate_scores(scores, features, self.model.encoding["mulligan_format"])
            keep = scores["keep"] if self.model.encoding["mulligan_format"] == "keep-mull-q" else scores["keep_probability"] >= 0.5
            chosen = next(c for c in decision["candidates"] if c["semantic"]["keep"] == keep)
            remaining()
            return {"selection":{"candidate_id":chosen["candidate_id"], "semantic_echo":chosen["semantic"]},
                    "decision_sha256":encoded["decision_sha256"], "checkpoint":self.model.checkpoint,
                    "scores":scores, "variant":MULLIGAN_VARIANT, "world_flags":encoded["world_flags"]}
        except BaseException:
            self.failed = True
            self.close()
            raise

    def close(self):
        if self.closed: return
        self.closed = True
        try: self.peer.close()
        finally: self.model.close()
