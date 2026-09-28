"""Test double for mtg-kernel spellbench_scorer_v1: same JSONL records, no model.

Sampled selection picks row sample_seed % len(row_candidate_ids); argmax
selection picks the last row, the only maximum of its logits. Like the real
scorer, it answers a request with other fields, or a sample_seed that does
not fit the selection, with an error record and exits.

--mode: ok, argmax; ready records the bot must refuse (no-ready, load-error,
wrong-digest, wrong-encoding, wrong-sampler, wrong-float-encoding,
unknown-selection); answers it must refuse (error-record, wrong-schema,
wrong-request-id, wrong-hash, row-past-end, row-negative, row-bool,
wrong-candidate); die-after-1.
"""

from __future__ import annotations

import hashlib
import json
import sys

CONTRACT = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
ENCODING = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"
ARGMAX = "argmax-first-v1"
REQUEST_KEYS = {
    "schema", "request_id", "game_id", "seat", "step", "feature_contract_digest", "feature_encoding_digest",
    "row_candidate_ids", "sample_seed", "tensor",
}
ONE_F32_BITS = 0x3F800000
READY_CHANGES = {
    "argmax": {"selection": ARGMAX},
    "unknown-selection": {"selection": "greedy-v1"},
    "wrong-digest": {"feature_contract_digest": "0" * 64},
    "wrong-encoding": {"feature_encoding_digest": "0" * 64},
    "wrong-sampler": {"sampler_identity": "f32-q8-expq63-hamilton-splitmix64-wide-v2"},
    "wrong-float-encoding": {"float_encoding": "ieee754-binary16-u16-bits"},
}
# Each changes one field of a correct answer.
WRONG_ANSWERS = {
    "wrong-schema": lambda choice, rows: {"schema": "mtg-kernel-spellbench-scorer-choice/v2"},
    "wrong-request-id": lambda choice, rows: {"request_id": choice["request_id"] + "-other"},
    "wrong-hash": lambda choice, rows: {"request_sha256": hashlib.sha256(b"another request").hexdigest()},
    "row-past-end": lambda choice, rows: {"selected_row": len(rows), "selected_candidate_id": rows[0]},
    "row-negative": lambda choice, rows: {"selected_row": -1, "selected_candidate_id": rows[-1]},
    "row-bool": lambda choice, rows: {"selected_row": True, "selected_candidate_id": rows[1]},
    "wrong-candidate": lambda choice, rows: {"selected_candidate_id": choice["selected_candidate_id"] + 1},
}


def emit(value: dict) -> None:
    sys.stdout.buffer.write(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def refuse(code: str) -> int:
    emit({"schema": "mtg-kernel-spellbench-scorer-error/v1", "code": code, "service_continues": False})
    return 1


def main() -> int:
    mode = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "ok"
    if mode == "no-ready":
        return 0
    if mode == "load-error":
        return refuse("checkpoint_load")
    ready = {
        "schema": "mtg-kernel-spellbench-scorer-ready/v1", "model": {"fake": True},
        "model_state_sha256": "0" * 64, "feature_contract_digest": CONTRACT,
        "feature_encoding_digest": ENCODING, "card_db_hash": "064a7c989255ab3c",
        "selection": "sampled-wide-v1", "sampler_identity": "f32-q8-expq63-hamilton-splitmix64-wide-v1",
        "float_encoding": "ieee754-binary32-u32-bits", "max_request_bytes": 8388608, "game_state_owned": False,
    }
    ready.update(READY_CHANGES.get(mode, {}))
    emit(ready)
    selection = ready["selection"]
    served = 0
    for raw in sys.stdin.buffer:
        line = raw.rstrip(b"\r\n")
        if mode == "die-after-1" and served == 1:
            return 3
        request = json.loads(line)
        if set(request) != REQUEST_KEYS:
            return refuse("request_json")
        if (request["sample_seed"] is None) != (selection == ARGMAX):
            return refuse("sample_seed")
        if mode == "error-record":
            return refuse("native_inference")
        rows = request["row_candidate_ids"]
        if selection == ARGMAX:
            row, logits = len(rows) - 1, [0] * (len(rows) - 1) + [ONE_F32_BITS]
        else:
            row, logits = request["sample_seed"] % len(rows), [0] * len(rows)
        choice = {
            "schema": "mtg-kernel-spellbench-scorer-choice/v1", "request_id": request["request_id"],
            "request_sha256": hashlib.sha256(line).hexdigest(), "model_state_sha256": "0" * 64,
            "selection": selection, "logits_bits": logits, "value_bits": 0,
            "selected_row": row, "selected_candidate_id": rows[row],
        }
        if mode in WRONG_ANSWERS:
            choice.update(WRONG_ANSWERS[mode](choice, rows))
        emit(choice)
        served += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
