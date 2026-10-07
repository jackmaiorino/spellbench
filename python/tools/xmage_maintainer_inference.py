"""Owned, deck-bound inference for the maintainer's original paired April networks.

This is the private inference component. It does not choose public game
actions or qualify the remaining game callbacks. Checkpoints execute only
through the existing confined launcher, under the caller's guarded job.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
import uuid
from pathlib import Path

from spellbench import digests, wire
from xmage_checkpoint_backend import cleanup_container, pinned_command
from xmage_maintainer_sources import CALLBACK_SHA256, ENCODER_SHA256
from xmage_neural_decisions import load_response

HEADS = ("action", "target", "card_select", "attack", "block")
MULLIGAN_PARAMETERS = {"vocab_size": 65536, "embed_dim": 32, "max_hand": 7,
                       "max_deck": 60, "num_explicit": 3}


def encoding(manifest: dict, checkpoint: str) -> tuple[dict, dict]:
    config = manifest.get("inference_backends", {}).get("maintainer-rl-april", {})
    if checkpoint not in config.get("checkpoints", []):
        raise ValueError("the maintainer's inference needs its declared April checkpoint")
    assets = {a["id"]: a for a in manifest.get("assets", [])}
    if len(assets) != len(manifest.get("assets", [])):
        raise ValueError("the maintainer's input identities must be unique")
    policy = assets[checkpoint]
    mulligan = assets[policy["mulligan_checkpoint"]]
    mulligan_source = assets[policy.get("mulligan_source", config.get("mulligan_source"))]
    cache = assets[policy.get("embedding_cache", config.get("embedding_cache"))]
    if (assets[config["state_encoder"]]["sha256"] != ENCODER_SHA256
            or assets[config["callback_source"]]["sha256"] != CALLBACK_SHA256):
        raise ValueError("the maintainer's inference requires the pinned original April game sources")
    policy_format = policy.get("mulligan_format", "keep-logit")
    if policy_format not in ("keep-logit", "keep-mull-q"):
        raise ValueError("unsupported original maintainer mulligan format")
    identity = {"state_encoder_sha256": ENCODER_SHA256, "callback_sha256": CALLBACK_SHA256,
                "card_embeddings_sha256": cache["sha256"],
                "mulligan_source_sha256": mulligan_source["sha256"], "mulligan_format": policy_format,
                "input_dim": 128, "candidate_dim": 48, "token_vocab": 65536,
                "action_vocab": 65536, "mulligan_dim": 71}
    expected = {"ready": True, "architecture": "maintainer-rl-april", "encoding": identity,
                "checkpoint_sha256": policy["sha256"],
                "model_source_sha256": assets[config["model"]]["sha256"],
                "mulligan_sha256": mulligan["sha256"], "mulligan_source_sha256": mulligan_source["sha256"],
                "mulligan_parameters": MULLIGAN_PARAMETERS, "candidate_heads": list(HEADS),
                "device": "cpu", "weights_only": True, "strict_load": True, "finite_weights": True,
                "model_class": "MTGTransformerModel", "mulligan_class": "MulliganNet"}
    return identity, expected


def _numbers(values, count, *, integer=False, boolean=False):
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("the maintainer's feature vector has the wrong width")
    for value in values:
        if boolean:
            if type(value) is not bool:
                raise ValueError("the maintainer's masks must contain booleans")
        elif integer:
            if type(value) is not int or not 0 <= value < 65536:
                raise ValueError("the maintainer IDs exceed their original vocabulary")
        elif type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
            raise ValueError("the maintainer's features must be finite bounded numbers")


def validate_features(features: dict) -> None:
    if not isinstance(features, dict):
        raise ValueError("the maintainer's inference needs an encoded feature object")
    kind = features.get("kind")
    if kind == "mulligan":
        values = features.get("values")
        _numbers(values, 71)
        _numbers(values[4:], 67, integer=True)
        if not any(values[4:11]):
            raise ValueError("encoded maintainer mulligan hand contains only padding")
        return
    if kind != "candidates" or features.get("head") not in HEADS:
        raise ValueError("the maintainer's callback needs an original candidate head")
    for name, rows, width in (("sequence", 256, 128), ("candidate_features", 64, 48)):
        matrix = features.get(name)
        if not isinstance(matrix, list) or len(matrix) != rows:
            raise ValueError("the maintainer's encoded matrix has the wrong row count")
        for row in matrix:
            _numbers(row, width)
    _numbers(features.get("padding"), 256, boolean=True)
    _numbers(features.get("token_ids"), 256, integer=True)
    _numbers(features.get("candidate_ids"), 64, integer=True)
    _numbers(features.get("candidate_mask"), 64, boolean=True)
    if all(features["padding"]) or not any(features["candidate_mask"]):
        raise ValueError("the maintainer's state or choices contain only padding")
    for index, valid in enumerate(features["candidate_mask"]):
        if valid and features["candidate_ids"][index] == 0:
            raise ValueError("legal maintainer candidates require their original nonzero IDs")


def validate_scores(scores: dict, features: dict, policy_format: str) -> dict:
    if features["kind"] == "mulligan":
        if policy_format == "keep-mull-q":
            _numbers([scores.get("q_keep"), scores.get("q_mulligan")], 2)
            if type(scores.get("keep")) is not bool or scores["keep"] != (scores["q_keep"] >= scores["q_mulligan"]):
                raise ValueError("the maintainer Q mulligan receipt changed its original tie rule")
            return {key: scores[key] for key in ("q_keep", "q_mulligan", "keep")}
        logit, probability = scores.get("keep_logit"), scores.get("keep_probability")
        _numbers([logit, probability], 2)
        expected = 1 / (1 + math.exp(-logit)) if logit >= 0 else math.exp(logit) / (1 + math.exp(logit))
        if not 0 <= probability <= 1 or abs(probability - expected) > 2e-7:
            raise ValueError("the maintainer's keep probability differs from its original sigmoid logit")
        return {"keep_logit": logit, "keep_probability": probability}
    probabilities = scores.get("probabilities")
    _numbers(probabilities, 64)
    _numbers([scores.get("value")], 1)
    if (any(not 0 <= value <= 1 for value in probabilities)
            or abs(sum(probabilities) - 1) > 1e-5
            or any(value != 0 for value, valid in zip(probabilities, features["candidate_mask"]) if not valid)):
        raise ValueError("the maintainer's network returned an invalid masked candidate distribution")
    return {"probabilities": probabilities, "value": scores["value"]}


class MaintainerInferenceSession:
    """Pin both networks, the original encoders and the actual own deck."""
    def __init__(self, manifest: dict, root: Path, checkpoint: str, image: str, *, game_start: dict,
                 startup_s: float = 90, peer_factory=wire.SubprocessPeer, on_owned=None):
        self.peer = None
        self.closed = self.failed = False
        self.cleanup = None
        self.container = None
        self.sequence = 0
        self.checkpoint = checkpoint
        self.encoding, expected = encoding(manifest, checkpoint)
        policy = next(a for a in manifest["assets"] if a["id"] == checkpoint)
        deck = game_start.get("own_deck") if isinstance(game_start, dict) else None
        if (not isinstance(deck, dict) or not isinstance(deck.get("decklist"), list)
                or digests.deck_id(deck["decklist"]) != policy.get("deck_id")):
            raise ValueError("the maintainer's checkpoint association differs from the actual own deck")
        self.game_start_sha256 = hashlib.sha256(wire.canonical_json_dumps(game_start)).hexdigest()
        self.container = "spellbench-xmage-" + uuid.uuid4().hex
        self.argv = pinned_command(manifest, root, checkpoint, image, "serve", self.container)
        try:
            if on_owned is not None:
                on_owned(self.container)
            self.peer = peer_factory(self.argv, timeout_s=startup_s)
            self.ready = load_response(self.peer.read_line())
            if wire.canonical_json_dumps({key: self.ready.get(key) for key in expected}) != wire.canonical_json_dumps(expected):
                raise ValueError("the maintainer's readiness differs from its paired networks and original encoding")
        except BaseException as exc:
            self.failed = True
            cleanup_error = None
            try:
                self.close()
            except Exception as failure:
                cleanup_error = str(failure)
            failure = RuntimeError("the maintainer's inference startup failed: " + str(exc))
            failure.cleanup, failure.cleanup_error = self.cleanup, cleanup_error
            raise failure from exc

    def score(self, features: dict, *, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("the maintainer's inference session is closed or has failed")
        try:
            if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("the maintainer's inference needs a positive finite remaining clock")
            deadline = time.monotonic() + timeout_s
            def remaining():
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise TimeoutError("the maintainer's inference exhausted its shared clock")
                return seconds
            features = copy.deepcopy(features)
            validate_features(features)
            self.sequence += 1
            rid = str(self.sequence)
            self.peer.set_timeout(remaining())
            self.peer.write_line(json.dumps({"id": rid, "encoding": self.encoding, "features": features},
                                            allow_nan=False, separators=(",", ":")).encode())
            self.peer.set_timeout(remaining())
            scores = load_response(self.peer.read_line())
            if scores.get("id") != rid:
                raise ValueError("the maintainer's inference returned a stale request ID")
            result = validate_scores(scores, features, self.encoding["mulligan_format"])
            if time.monotonic() >= deadline:
                raise TimeoutError("the maintainer's inference exhausted its shared validation clock")
            return result
        except BaseException:
            self.failed = True
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.peer is not None:
                self.peer.close()
        finally:
            if self.container is not None:
                self.cleanup = cleanup_container(self.container)
                if self.cleanup.get("confirmed_absent") is not True:
                    raise RuntimeError("the maintainer owned checkpoint container cleanup is unconfirmed")
