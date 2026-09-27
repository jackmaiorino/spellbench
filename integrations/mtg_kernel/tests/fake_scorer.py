"""Test double for mtg-kernel spellbench_scorer_v1: same JSONL records, no model.

Picks row sample_seed % len(row_candidate_ids). --mode: ok, no-ready,
wrong-digest, die-after-1.
"""

from __future__ import annotations

import hashlib
import json
import sys

CONTRACT = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
ENCODING = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"


def emit(value: dict) -> None:
    sys.stdout.buffer.write(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    mode = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "ok"
    if mode == "no-ready":
        return 0
    emit({
        "schema": "mtg-kernel-spellbench-scorer-ready/v1", "model": {"fake": True},
        "model_state_sha256": "0" * 64,
        "feature_contract_digest": "0" * 64 if mode == "wrong-digest" else CONTRACT,
        "feature_encoding_digest": ENCODING, "card_db_hash": "064a7c989255ab3c",
        "selection": "sampled-wide-v1", "sampler_identity": "f32-q8-expq63-hamilton-splitmix64-wide-v1",
        "float_encoding": "ieee754-binary32-u32-bits", "max_request_bytes": 8388608, "game_state_owned": False,
    })
    served = 0
    for raw in sys.stdin.buffer:
        line = raw.rstrip(b"\r\n")
        if mode == "die-after-1" and served == 1:
            return 3
        request = json.loads(line)
        rows = request["row_candidate_ids"]
        row = request["sample_seed"] % len(rows)
        emit({
            "schema": "mtg-kernel-spellbench-scorer-choice/v1", "request_id": request["request_id"],
            "request_sha256": hashlib.sha256(line).hexdigest(), "model_state_sha256": "0" * 64,
            "selection": "sampled-wide-v1", "logits_bits": [0] * len(rows), "value_bits": 0,
            "selected_row": row, "selected_candidate_id": rows[row],
        })
        served += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
