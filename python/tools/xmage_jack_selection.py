"""Private RPC to the exact original chooser, with one game-owned RNG.

The caller still needs the original callback's candidate list, feature
overwrites and application rules. Indices from this component are not
public Spellbench candidate IDs and must not be used as an agent fallback.
"""
from __future__ import annotations

import json
import math
import time

from spellbench import wire
from xmage_jack_sources import CALLBACK_SHA256
from xmage_neural_decisions import load_response

GREEDY = "jack-april-eval-greedy-fair-v1"
SAMPLED = "jack-april-no-training-sampled-fair-v1"
PROFILES = (GREEDY, SAMPLED)


def validate_request(probabilities, mask, count, picks, sequential):
    if (not isinstance(probabilities, list) or len(probabilities) != 64
            or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)
            or not isinstance(mask, list) or len(mask) != 64 or any(type(v) is not bool for v in mask)
            or type(count) is not int or not 1 <= count <= 64
            or type(picks) is not int or not 1 <= picks <= count
            or type(sequential) is not bool or not sequential and picks != 1
            or any(mask[count:]) or picks > sum(mask[:count])):
        raise ValueError("original Jack selection needs its fixed slots, legal mask and pick count")


class JackSelectionSession:
    def __init__(self, peer, *, profile: str, seed: int):
        self.peer = peer
        self.closed = self.failed = False
        self.sequence = 0
        self.profile, self.seed = profile, seed
        self.game_start_sha256 = None
        try:
            if profile not in PROFILES or type(seed) is not int or not 0 <= seed <= wire.MAX_JSON_INT:
                raise ValueError("original Jack chooser needs an explicit no-training profile and game seed")
            expected = {"ready": True, "selection": "jack-original-no-training", "profile": profile,
                        "seed": seed, "callback_source_sha256": CALLBACK_SHA256}
            if load_response(peer.read_line()) != expected:
                raise ValueError("Jack selection readiness differs from its original source and play profile")
        except BaseException:
            self.failed = True
            self.close()
            raise

    def choose(self, probabilities, mask, *, count: int, picks: int, sequential: bool, timeout_s: float) -> list[int]:
        if self.closed or self.failed:
            raise ValueError("Jack selection session is closed or has failed")
        try:
            if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("original Jack selection needs a positive finite remaining clock")
            deadline = time.monotonic() + timeout_s
            validate_request(probabilities, mask, count, picks, sequential)
            self.sequence += 1
            rid = str(self.sequence)

            def remaining():
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise TimeoutError("Jack selection exhausted its shared clock")
                return seconds

            self.peer.set_timeout(remaining())
            self.peer.write_line(json.dumps({"id": rid, "operation": "choose", "probabilities": probabilities,
                                            "mask": mask, "count": count, "picks": picks, "sequential": sequential},
                                           separators=(",", ":"), allow_nan=False).encode())
            self.peer.set_timeout(remaining())
            result = load_response(self.peer.read_line())
            if result.get("id") != rid or result.get("ok") is not True:
                raise ValueError("original Jack chooser refused or returned a stale request ID")
            indices = result.get("indices")
            if (not isinstance(indices, list) or len(indices) != picks
                    or any(type(i) is not int or not 0 <= i < count or not mask[i] for i in indices)
                    or len(set(indices)) != picks):
                raise ValueError("original Jack chooser returned illegal, repeated or incomplete picks")
            remaining()
            return indices
        except BaseException:
            self.failed = True
            self.close()
            raise

    def bind_game_start(self, game_start: dict):
        """All callbacks share this game's original RNG, with no cross-game reuse."""
        from xmage_neural_decisions import decision_hash
        try:
            digest = decision_hash(game_start)
            if (self.closed or self.failed or type(game_start.get("agent_seed")) is not int
                    or game_start["agent_seed"] != self.seed
                    or self.game_start_sha256 not in (None, digest)
                    or self.game_start_sha256 is None and self.sequence != 0):
                raise ValueError("original Jack chooser cannot be rebound to another game or RNG history")
            self.game_start_sha256 = digest
        except BaseException:
            self.failed = True
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.peer.close()
