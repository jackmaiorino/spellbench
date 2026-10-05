"""Bind pinned neural policy scores to offered, permitted game decisions.

This is a decision adapter, not a complete agent or the original MCTS player.
Exp1 accepts priority, target and binary heads; MageZero v0.2 accepts priority
only. Unsupported callbacks
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

from spellbench import digests, wire
from xmage_checkpoint_backend import cleanup_container, pinned_command
from xmage_release_assets import prepare_root

ENCODING = {"hash_algorithm": "xmage_feature_hash", "hash_version": 1, "feature_hash_bins": 2000000}
SCHEMAS = {"spellbench-draftzero-priority-features/v1", "spellbench-draftzero-decision-features/v1"}
MAGEZERO_ENCODING = {**ENCODING, "feature_hash_bins": 2147483647}


def profile(architecture: str) -> tuple[dict, set[str], int, str]:
    if architecture == "draftzero-exp1":
        return ENCODING, SCHEMAS, 1024, "Exp1"
    if architecture == "magezero-v02":
        return MAGEZERO_ENCODING, {"spellbench-magezero-priority-features/v1"}, 128, "MageZero v0.2"
    raise ValueError("unsupported neural decision architecture")


def decision_hash(decision: dict) -> str:
    return hashlib.sha256(wire.canonical_json_dumps(decision)).hexdigest()


def validate_mapping(decision: dict, encoded: dict, architecture="draftzero-exp1") -> tuple[str, list[dict]]:
    encoding, schemas, policy_width, label = profile(architecture)
    if (encoded.get("schema") not in schemas or encoded.get("encoding") != encoding
            or encoded.get("decision_sha256") != decision_hash(decision)):
        raise ValueError("encoded features are not bound to this offered decision and " + label + " encoding")
    head = encoded.get("head")
    if head not in ("priority", "target", "binary"):
        raise ValueError("this callback has no implemented trained policy head")
    if architecture == "magezero-v02" and (head != "priority" or decision.get("context", {}).get("kind") != "priority"):
        raise ValueError("MageZero currently implements the priority encoder slice only")
    candidates = decision.get("candidates")
    slots = encoded.get("policy_slots")
    if (not isinstance(candidates, list) or not candidates or not isinstance(slots, list)
            or len(slots) != len(candidates)):
        raise ValueError("policy mapping must cover every offered candidate exactly once")
    ids = [c.get("candidate_id") for c in candidates]
    if any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("offered candidate ids must be unique nonnegative protocol integers")
    mapped = [s.get("candidate_id") for s in slots]
    width = 2 if head == "binary" else policy_width
    if (any(type(cid) is not int for cid in mapped) or len(set(mapped)) != len(mapped) or set(mapped) != set(ids)
            or any(type(s.get("policy_slot")) is not int or not 0 <= s["policy_slot"] < width for s in slots)):
        raise ValueError("policy slots contain a missing, aliased or out-of-range candidate")
    features = encoded.get("features")
    if (not isinstance(features, list) or not 1 <= len(features) <= 16384
            or any(type(f) is not int or not 0 <= f < encoding["feature_hash_bins"] for f in features)):
        raise ValueError("encoded features exceed " + label + "'s finite integer vocabulary envelope")
    return head, slots


def validate_scores(scores: dict, architecture="draftzero-exp1") -> None:
    policy_width = profile(architecture)[2]
    for name, width in (("priority", policy_width), ("opponent_priority", policy_width), ("target", policy_width), ("binary", 2)):
        values = scores.get(name)
        if (not isinstance(values, list) or len(values) != width
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in values)):
            raise ValueError("inference returned a nonfinite or wrong-width policy head")
    value = scores.get("value")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("inference returned an invalid state value")


def select_candidate(decision: dict, encoded: dict, scores: dict, architecture="draftzero-exp1") -> dict:
    head, slots = validate_mapping(decision, encoded, architecture)
    validate_scores(scores, architecture)
    value = scores["value"]
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


def close_resources(*resources, failure=None):
    """Attempt every owned close, retaining an active failure as the primary error."""
    errors = []
    for resource in resources:
        if resource is not None:
            try:
                resource.close()
            except BaseException as error:
                errors.append(error)
    if failure is not None:
        for error in errors:
            notes = tuple(getattr(error, "__notes__", []))
            failure.add_note("Neural cleanup failed: " + str(error))
            for note in notes:
                failure.add_note(note)
    elif errors:
        for error in errors[1:]:
            errors[0].add_note("Neural cleanup also failed: " + str(error))
        raise errors[0]


class InferenceSession:
    """One owned confined checkpoint process, with a shared request deadline."""
    def __init__(self, manifest: dict, root: Path, checkpoint: str, image: str, *, startup_s: float = 90,
                 peer_factory=wire.SubprocessPeer, on_owned=None, architecture="draftzero-exp1", game_start=None):
        self.architecture = architecture
        self.encoding, _, width, label = profile(architecture)
        config = manifest.get("inference_backends", {}).get(architecture, {})
        if checkpoint not in config.get("checkpoints", []):
            raise ValueError("this decision adapter requires a pinned " + label + " checkpoint")
        assets = {a["id"]: a for a in manifest["assets"]}
        if architecture == "magezero-v02":
            deck = game_start.get("own_deck") if isinstance(game_start, dict) else None
            if not isinstance(deck, dict) or not isinstance(deck.get("decklist"), list):
                raise ValueError("MageZero decision needs its actual own decklist")
            if digests.deck_id(deck["decklist"]) != assets[checkpoint].get("deck_id"):
                raise ValueError("MageZero checkpoint deck association differs from the actual own decklist")
        self.container = "spellbench-xmage-" + uuid.uuid4().hex
        self.argv = pinned_command(manifest, root, checkpoint, image, "serve", self.container)
        self.checkpoint = checkpoint
        self.peer = None
        self.closed = False
        self.failed = False
        self.cleanup = None
        self.sequence = 0
        expected = {"architecture": architecture, "encoding": self.encoding, "policy_width": width,
                    "checkpoint_sha256": assets[checkpoint]["sha256"],
                    "model_source_sha256": assets[config["model"]]["sha256"],
                    "vocab_source_sha256": assets[config["feature_vocab_code"]]["sha256"],
                    "action_vocab_sha256": assets[config["action_vocab"]]["sha256"] if architecture == "draftzero-exp1" else None}
        try:
            if on_owned is not None:
                # The supervising job can recover this owned container after a
                # process kill, including during a slow startup handshake.
                on_owned(self.container)
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
        validate_mapping(decision, encoded, self.architecture)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("neural decision needs a positive finite remaining clock")
        deadline = time.monotonic() + timeout_s
        try:
            scores = self.score(encoded["features"], timeout_s=max(0, deadline-time.monotonic()))
            result = {"checkpoint": self.checkpoint, **select_candidate(decision, encoded, scores, self.architecture)}
            if time.monotonic() > deadline:
                raise TimeoutError("neural decision exhausted its selection-validation clock")
            return result
        except BaseException as failure:
            self.failed = True
            close_resources(self, failure=failure)
            raise

    def score(self, features: list[int], *, timeout_s: float) -> dict:
        """Raw heads and value for the audited, permitted-world search process."""
        if self.closed or self.failed:
            raise ValueError("inference session is closed or has failed")
        if (not isinstance(features, list) or not 1 <= len(features) <= 16384
                or any(type(f) is not int or not 0 <= f < self.encoding["feature_hash_bins"] for f in features)):
            raise ValueError("encoded features exceed the checkpoint's finite integer vocabulary envelope")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("neural decision needs a positive finite remaining clock")
        deadline = time.monotonic() + timeout_s
        self.sequence += 1
        rid = str(self.sequence)
        payload = json.dumps({"id": rid, "features": features, "encoding": self.encoding},
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
            validate_scores(scores, self.architecture)
            if time.monotonic() > deadline:
                raise TimeoutError("neural decision exhausted its shared inference/validation clock")
            return {k: scores[k] for k in ("priority", "opponent_priority", "target", "binary", "value")}
        except BaseException as failure:
            self.failed = True
            close_resources(self, failure=failure)
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
    parser.add_argument("--architecture", choices=("draftzero-exp1", "magezero-v02"), default="draftzero-exp1")
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
                  "architecture": args.architecture,
                  "scope": "one offered decision; full agent, search and ratings unfinished"}
        if args.architecture == "magezero-v02":
            result["schema"] = "spellbench-magezero-neural-decision/v1"
        try:
            raw = args.manifest.read_bytes()
            record_raw, encoded_raw = args.record.read_bytes(), args.encoded.read_bytes()
            record, encoded = wire.strict_json_loads(record_raw), wire.strict_json_loads(encoded_raw)
            result.update(manifest_sha256=hashlib.sha256(raw).hexdigest(),
                          record_sha256=hashlib.sha256(record_raw).hexdigest(),
                          encoded_sha256=hashlib.sha256(encoded_raw).hexdigest())
            validate_mapping(record["decision"], encoded, args.architecture)
            session = InferenceSession(json.loads(raw), args.root, args.checkpoint, args.image,
                                       architecture=args.architecture, game_start=record.get("game_start"))
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
