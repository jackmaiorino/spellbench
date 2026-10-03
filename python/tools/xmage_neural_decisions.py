"""Bind real DraftZero policy scores to offered, permitted game decisions.

This is a decision adapter, not a complete agent or the original MCTS player.
It accepts only the priority, target and binary heads. Unsupported callbacks
and failed inference are refused without a native or random-policy fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import uuid
from pathlib import Path

from spellbench import wire
from xmage_checkpoint_backend import cleanup_container, pinned_command
from xmage_release_assets import prepare_root

ENCODING = {"hash_algorithm": "xmage_feature_hash", "hash_version": 1, "feature_hash_bins": 2000000}
SCHEMAS = {"spellbench-draftzero-priority-features/v1", "spellbench-draftzero-decision-features/v1"}


def decision_hash(decision: dict) -> str:
    return hashlib.sha256(wire.canonical_json_dumps(decision)).hexdigest()


def validate_mapping(decision: dict, encoded: dict) -> tuple[str, list[dict]]:
    if (encoded.get("schema") not in SCHEMAS or encoded.get("encoding") != ENCODING
            or encoded.get("decision_sha256") != decision_hash(decision)):
        raise ValueError("encoded features are not bound to this offered decision and Exp1 encoding")
    head = encoded.get("head")
    if head not in ("priority", "target", "binary"):
        raise ValueError("this callback has no implemented trained policy head")
    candidates = decision.get("candidates")
    slots = encoded.get("policy_slots")
    if (not isinstance(candidates, list) or not candidates or not isinstance(slots, list)
            or len(slots) != len(candidates)):
        raise ValueError("policy mapping must cover every offered candidate exactly once")
    ids = [c.get("candidate_id") for c in candidates]
    if any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("offered candidate ids must be unique nonnegative protocol integers")
    mapped = [s.get("candidate_id") for s in slots]
    width = 2 if head == "binary" else 1024
    if (any(type(cid) is not int for cid in mapped) or len(set(mapped)) != len(mapped) or set(mapped) != set(ids)
            or any(type(s.get("policy_slot")) is not int or not 0 <= s["policy_slot"] < width for s in slots)):
        raise ValueError("policy slots contain a missing, aliased or out-of-range candidate")
    features = encoded.get("features")
    if (not isinstance(features, list) or not 1 <= len(features) <= 16384
            or any(type(f) is not int or not 0 <= f < ENCODING["feature_hash_bins"] for f in features)):
        raise ValueError("encoded features exceed Exp1's finite integer vocabulary envelope")
    return head, slots


def select_candidate(decision: dict, encoded: dict, scores: dict) -> dict:
    head, slots = validate_mapping(decision, encoded)
    for name, width in (("priority", 1024), ("opponent_priority", 1024), ("target", 1024), ("binary", 2)):
        values = scores.get(name)
        if (not isinstance(values, list) or len(values) != width
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in values)):
            raise ValueError("inference returned a nonfinite or wrong-width policy head")
    value = scores.get("value")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("inference returned an invalid state value")
    # The original server returns raw logits. Direct-policy inference takes
    # their argmax on offered candidates only. Collisions tie by candidate id.
    chosen = max(slots, key=lambda s: (scores[head][s["policy_slot"]], -s["candidate_id"]))
    candidate = next(c for c in decision["candidates"] if c["candidate_id"] == chosen["candidate_id"])
    return {"selection": {"candidate_id": candidate["candidate_id"], "semantic_echo": candidate["semantic"]},
            "head": head, "decision_sha256": encoded["decision_sha256"],
            "candidate_scores": [{**s, "logit": scores[head][s["policy_slot"]]} for s in slots],
            "state_value": value, "variant": "direct trained-policy argmax; no original MCTS search",
            "encoder_variant": encoded.get("variant"), "world_flags": encoded.get("world_flags", [])}


def load_response(payload: bytes) -> dict:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("inference response repeats a JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("inference response contains a nonfinite number")
    result = json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(result, dict):
        raise ValueError("inference response must be a JSON object")
    return result


class InferenceSession:
    """One owned confined checkpoint process, with a shared request deadline."""
    def __init__(self, manifest: dict, root: Path, checkpoint: str, image: str, *, startup_s: float = 90,
                 peer_factory=wire.SubprocessPeer):
        config = manifest.get("inference_backends", {}).get("draftzero-exp1", {})
        if checkpoint not in config.get("checkpoints", []):
            raise ValueError("this decision adapter requires a pinned DraftZero Exp1 checkpoint")
        self.container = "spellbench-xmage-" + uuid.uuid4().hex
        self.argv = pinned_command(manifest, root, checkpoint, image, "serve", self.container)
        self.checkpoint = checkpoint
        self.peer = None
        self.closed = False
        self.failed = False
        self.cleanup = None
        self.sequence = 0
        assets = {a["id"]: a for a in manifest["assets"]}
        expected = {"architecture": "draftzero-exp1", "encoding": ENCODING, "policy_width": 1024,
                    "checkpoint_sha256": assets[checkpoint]["sha256"],
                    "model_source_sha256": assets[config["model"]]["sha256"],
                    "vocab_source_sha256": assets[config["feature_vocab_code"]]["sha256"],
                    "action_vocab_sha256": assets[config["action_vocab"]]["sha256"]}
        try:
            self.peer = peer_factory(self.argv, timeout_s=startup_s)
            self.ready = load_response(self.peer.read_line())
            if self.ready.get("ready") is not True or any(self.ready.get(k) != v for k, v in expected.items()):
                raise ValueError("inference readiness does not match the pinned checkpoint and encoder inputs")
        except BaseException as exc:
            self.failed = True
            cleanup_error = None
            try:
                self.close()
            except Exception as failure:
                cleanup_error = str(failure)
            failure = RuntimeError("checkpoint inference startup failed: " + str(exc))
            failure.cleanup = self.cleanup
            failure.cleanup_error = cleanup_error
            raise failure from exc

    def choose(self, decision: dict, encoded: dict, *, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("inference session is closed or has failed")
        validate_mapping(decision, encoded)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("neural decision needs a positive finite remaining clock")
        deadline = time.monotonic() + timeout_s
        self.sequence += 1
        rid = str(self.sequence)
        payload = json.dumps({"id": rid, "features": encoded["features"], "encoding": encoded["encoding"]},
                             separators=(",", ":"), allow_nan=False).encode()
        try:
            self.peer.set_timeout(max(0, deadline - time.monotonic()))
            self.peer.write_line(payload)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("neural decision exhausted its shared write/read clock")
            self.peer.set_timeout(remaining)
            scores = load_response(self.peer.read_line())
            if scores.get("id") != rid:
                raise ValueError("inference returned a stale or mismatched request id")
            result = {"checkpoint": self.checkpoint, **select_candidate(decision, encoded, scores)}
            if time.monotonic() > deadline:
                raise TimeoutError("neural decision exhausted its shared inference/validation clock")
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
            self.cleanup = cleanup_container(self.container)
        if not self.cleanup["confirmed_absent"]:
            raise RuntimeError("owned inference container cleanup could not be confirmed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("engines/xmage/releases.json"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--encoded", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = prepare_root(args.report.parent) / args.report.name
    with report.open("x", encoding="utf-8") as stream:
        session = None
        result = {"schema": "spellbench-draftzero-neural-decision/v1", "exit_code": 2,
                  "checkpoint": args.checkpoint, "container_image": args.image,
                  "scope": "one offered decision; full agent, search and ratings unfinished"}
        try:
            raw = args.manifest.read_bytes()
            record_raw, encoded_raw = args.record.read_bytes(), args.encoded.read_bytes()
            record, encoded = wire.strict_json_loads(record_raw), wire.strict_json_loads(encoded_raw)
            result.update(manifest_sha256=hashlib.sha256(raw).hexdigest(),
                          record_sha256=hashlib.sha256(record_raw).hexdigest(),
                          encoded_sha256=hashlib.sha256(encoded_raw).hexdigest())
            validate_mapping(record["decision"], encoded)
            session = InferenceSession(json.loads(raw), args.root, args.checkpoint, args.image)
            result["readiness"] = session.ready
            first = session.choose(record["decision"], encoded, timeout_s=30)
            second = session.choose(record["decision"], encoded, timeout_s=30)
            if first != second:
                raise ValueError("repeated neural decision differs")
            result.update(exit_code=0, decision=first, repeated_inference_identical=True)
        except Exception as exc:
            result.update(exit_code=2, error=str(exc), error_type=type(exc).__name__)
            if hasattr(exc, "cleanup"):
                result["cleanup"] = exc.cleanup
                result["cleanup_error"] = exc.cleanup_error
        finally:
            if session:
                try:
                    session.close()
                except Exception as exc:
                    result.update(exit_code=2, cleanup_error=str(exc))
                result["cleanup"] = session.cleanup
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"exit_code": result["exit_code"], "report": str(report)}))
        return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
