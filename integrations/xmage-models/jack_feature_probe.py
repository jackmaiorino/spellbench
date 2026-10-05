"""Repeat real Jack priority features in isolation without starting a player."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    if not Path("/.dockerenv").is_file():
        raise ValueError("real-feature checkpoint probes require the confined launcher")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe",))
    for name in ("checkpoint", "source", "mulligan", "embeddings", "fixture"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("checkpoint-sha256", "model-sha256", "mulligan-sha256", "mulligan-source-sha256",
                 "encoder-sha256", "callback-sha256", "embeddings-sha256", "fixture-sha256",
                 "staged-base-sha256", "staged-candidates-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--architecture", choices=("jack-rl-april",), required=True)
    parser.add_argument("--checkpoint-format", choices=("torch",), required=True)
    parser.add_argument("--mulligan-format", choices=("keep-logit", "keep-mull-q"), required=True)
    args = parser.parse_args()
    if sha(args.fixture) != args.fixture_sha256 or args.fixture.stat().st_size > 4 * 2**20:
        raise ValueError("real encoder fixture differs")
    fixture = json.loads(args.fixture.read_bytes())
    if (fixture.get("schema") != "spellbench-jack-priority-encoder-check/v1"
            or fixture.get("embedding_cache_sha256") != args.embeddings_sha256
            or fixture.get("encoder_source_sha256") != args.staged_base_sha256
            or fixture.get("candidate_source_sha256") != args.staged_candidates_sha256):
        raise ValueError("fixture is not bound to the staged encoder and this checkpoint's cache")
    sys.path.insert(0, "/app")
    from jack_runtime import JackRuntime
    runtime = JackRuntime(args.checkpoint, args.checkpoint_sha256, args.source, args.model_sha256,
                          args.mulligan, args.mulligan_sha256, args.mulligan_source_sha256,
                          args.encoder_sha256, args.callback_sha256, args.embeddings, args.embeddings_sha256,
                          args.mulligan_format)
    results = {}
    for view in ("active_view", "nonactive_view"):
        checked = fixture[view]
        if checked.get("different_hidden_samples", 0) < 1 or any(checked.get(flag) is not True for flag in
            ("hidden_sample_features_identical", "visible_life_change_detected", "own_hand_encoded",
             "own_card_ownership_correct", "other_hand_excluded", "offered_priority_choices_bound",
             "original_pass_encoded", "candidate_padding_masked")):
            raise ValueError("real encoder fixture lacks its fairness checks")
        encoded = checked["encoded"]
        refs = encoded["candidate_refs"]
        mask = encoded["candidate_mask"]
        if (encoded.get("schema") != "spellbench-jack-priority-features/v1" or encoded.get("head") != "action"
                or not isinstance(refs, list) or not 1 <= len(refs) <= 64
                or len(mask) != 64 or mask != [True] * len(refs) + [False] * (64 - len(refs))
                or [ref.get("index") for ref in refs] != list(range(len(refs)))
                or any(type(ref.get("candidate_id")) is not int or ref["candidate_id"] < 0 for ref in refs)
                or len({ref["candidate_id"] for ref in refs}) != len(refs)):
            raise ValueError("real priority candidate mapping differs")
        features = {key: encoded[key] for key in ("sequence", "padding", "token_ids", "candidate_features",
                                                  "candidate_ids", "candidate_mask")}
        features.update(kind="candidates", head="action")
        first = runtime.evaluate(features, runtime.encoding)
        if first != runtime.evaluate(features, runtime.encoding):
            raise ValueError("real-feature checkpoint inference does not repeat")
        probabilities = first["probabilities"]
        if (len(probabilities) != 64 or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)
                or abs(sum(probabilities) - 1) > 2e-5
                or any(probabilities[i] != 0 for i in range(len(refs), 64))):
            raise ValueError("real-feature probabilities include padding or invalid normalization")
        best = max(refs, key=lambda ref: (probabilities[ref["index"]], -ref["candidate_id"]))
        results[view] = {"scores": first, "probe_argmax_candidate_id": best["candidate_id"],
                         "decision_sha256": encoded["decision_sha256"], "offered_candidates": len(refs),
                         "padding_probability_zero": True, "repeated_identical": True,
                         "encoder_variant": encoded["variant"], "world_flags": encoded["world_flags"]}
    raw = json.dumps(results, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    print(json.dumps({"schema": "spellbench-jack-real-feature-probe/v1", **runtime.summary,
                      "fixture_sha256": args.fixture_sha256, "staged_base_sha256": args.staged_base_sha256,
                      "staged_candidates_sha256": args.staged_candidates_sha256, "results": results,
                      "output_sha256": hashlib.sha256(raw).hexdigest(), "full_game_qualified": False,
                      "scope": "actual priority features and paired checkpoint; no deck association, original selection-rule, full game or rating qualification"},
                     sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
