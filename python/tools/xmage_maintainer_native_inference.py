"""Serve original JVM callbacks through one existing confined, deck-bound pair."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import time

from spellbench import wire
from xmage_maintainer_inference import MaintainerInferenceSession
from xmage_maintainer_sources import CALLBACK_SHA256

SCHEMA = "spellbench-maintainer-native-inference/v1"
PROFILES = ("maintainer-april-eval-greedy-fair-v1", "maintainer-april-no-training-sampled-fair-v1")


class MaintainerNativeInferenceOwner:
    """One pair and physical-copy stream for the game and its admitted JVM copies."""
    def __init__(self, manifest, root, checkpoint, image, *, game_start, profile, seed,
                 session_factory=MaintainerInferenceSession, **session_options):
        if profile not in PROFILES or type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("native maintainer inference needs a declared profile and Java game seed")
        self.start = copy.deepcopy(game_start)
        self.start_sha256 = hashlib.sha256(wire.canonical_json_dumps(self.start)).hexdigest()
        copy_seed = hashlib.sha256(b"spellbench-maintainer-card-copy-mt19937/v1\0" + wire.canonical_json_dumps(self.start)).digest()
        self.copy_rng = random.Random(int.from_bytes(copy_seed, "big"))
        self.profile, self.seed = profile, seed
        self.sequence = self.copy_draws = 0
        self.closed = False
        self.session = session_factory(manifest, root, checkpoint, image, game_start=self.start, **session_options)

    def handle(self, message: dict) -> dict:
        if self.closed:
            raise ValueError("native maintainer inference owner is closed")
        try:
            if (not isinstance(message, dict) or message.get("schema") != SCHEMA
                    or message.get("callback_sha256") != CALLBACK_SHA256
                    or message.get("profile") != self.profile or type(message.get("seed")) is not int
                    or message["seed"] != self.seed or message.get("game_start_sha256") != self.start_sha256
                    or type(message.get("id")) is not int or message["id"] != self.sequence + 1
                    or message["id"] >= 2**63):
                raise ValueError("native maintainer request identity, profile, game or sequence differs")
            self.sequence += 1
            operation = message.get("operation")
            if operation == "close":
                self.close()
                return {"id": self.sequence, "closed": True}
            seconds = message.get("remaining_s")
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("native maintainer callback needs its positive remaining clock")
            if operation == "physical_copy":
                count = message.get("count")
                if type(count) is not int or not 1 <= count <= 64:
                    raise ValueError("native maintainer physical-copy count exceeds the original group envelope")
                index = 0
                if count > 1:
                    index = self.copy_rng.randrange(count)
                    self.copy_draws += 1
                return {"id": self.sequence, "index": index}
            features = message.get("features")
            if operation not in ("score", "mulligan") or not isinstance(features, dict):
                raise ValueError("unsupported native maintainer inference operation")
            if features.get("kind") != ("candidates" if operation == "score" else "mulligan"):
                raise ValueError("native maintainer callback changed its original feature kind")
            if operation == "score":
                metadata = message.get("selection")
                if not isinstance(metadata, dict) or any(type(metadata.get(k)) is not int for k in (
                        "pick_index", "minimum", "maximum", "count")):
                    raise ValueError("native maintainer callback needs original selection metadata")
                count = metadata["count"]
                mask = features.get("candidate_mask")
                if (not 1 <= count <= 64 or metadata["pick_index"] < 0
                        or not 0 <= metadata["minimum"] <= metadata["maximum"]
                        or not isinstance(mask, list) or len(mask) != 64 or any(mask[count:])):
                    raise ValueError("native maintainer callback selection metadata escaped its prefix")
            scores = self.session.score(features, timeout_s=seconds)
            if operation == "score":
                return {"id": self.sequence, **scores}
            fmt = self.session.encoding["mulligan_format"]
            if fmt == "keep-mull-q":
                first, second = scores["q_keep"], scores["q_mulligan"]
            elif fmt == "keep-logit":
                first, second = scores["keep_logit"], scores["keep_probability"]
            else:
                raise ValueError("unsupported paired native mulligan format")
            return {"id": self.sequence, "format": fmt, "first": first, "second": second}
        except BaseException as failure:
            try:
                self.close()
            except BaseException as cleanup:
                if hasattr(failure, "add_note"):
                    failure.add_note("Native the maintainer's cleanup also failed: " + str(cleanup))
            raise

    def service(self, peer, message):
        """Answer a received private JVM request; caller owns the guarded JVM peer."""
        started = time.monotonic()
        response = self.handle(message)
        if message["operation"] != "close":
            try:
                remaining = message["remaining_s"] - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("native maintainer callback exhausted its response-write clock")
                peer.set_timeout(remaining)
                peer.write_line(json.dumps(response,allow_nan=False,separators=(",", ":")).encode("utf-8"))
            except BaseException as failure:
                try:
                    self.close()
                except BaseException as cleanup:
                    if hasattr(failure, "add_note"):
                        failure.add_note("Native the maintainer's cleanup also failed: " + str(cleanup))
                raise
        return response

    def close(self):
        if not self.closed:
            self.closed = True
            self.session.close()
