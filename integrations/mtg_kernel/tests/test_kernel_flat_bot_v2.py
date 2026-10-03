"""Protocol migration preserves the native scorer wire and sampled row choice."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_flat_bot as integration
from spellbench.bot import BotSession, Decision, GameStart
from spellbench.builtins.uniform import SplitMix64


class RecordedScorer:
    ready = {
        "feature_contract_digest": integration.FEATURE_CONTRACT_DIGEST,
        "feature_encoding_digest": integration.FEATURE_ENCODING_DIGEST,
        "sampler_identity": integration.SAMPLER_IDENTITY,
        "float_encoding": integration.FLOAT_ENCODING,
        "selection": integration.SAMPLED,
        "card_db_hash": "064a7c989255ab3c",
        "model_state_sha256": "0" * 64,
    }

    def __init__(self):
        self.requests = []

    def score(self, request):
        self.requests.append(copy.deepcopy(request))
        wire = integration._dumps(request).encode()
        row = request["sample_seed"] % len(request["row_candidate_ids"])
        return wire, {
            "schema": integration.CHOICE_SCHEMA, "request_id": request["request_id"],
            "request_sha256": hashlib.sha256(wire).hexdigest(), "selected_row": row,
            "selected_candidate_id": request["row_candidate_ids"][row],
            "logits_bits": [0, 0], "value_bits": 0,
        }

    def close(self):
        pass


def start_payload():
    return {"game_id": "g-test", "seat": "p0", "engine": {
        "name": "mtg-kernel", "card_pool_identity": "mtg-kernel-pauper-pool-v1/carddb-064a7c989255ab3c",
    }}


def decision(seat_step=0, **changes):
    tensor = {key: [] for key in integration.TENSOR_KEYS}
    tensor["state"] = [0, 1065353216, 2147483648]
    extension = {
        "schema": integration.EXTENSION_SCHEMA,
        "feature_contract_digest": integration.FEATURE_CONTRACT_DIGEST,
        "feature_encoding_digest": integration.FEATURE_ENCODING_DIGEST,
        "card_db_hash": "064a7c989255ab3c", "acting_seat": "p0", "step": seat_step,
        "row_candidate_ids": [2, 0], "tensor": tensor,
        **changes,
    }
    return Decision.from_request({"game_id": "g-test", "decision": {
        "acting_seat": "p0", "seat_step": seat_step,
        "candidates": [{"candidate_id": n} for n in range(3)],
        "extensions": {integration.EXTENSION: extension},
    }})


def make_bot(scorer):
    return integration.KernelFlatBot(scorer, seed=11, decision_log=None,
                                    name="g115", version="2.0.0", expect_model_state="0" * 64)


def test_v2_preserves_tensor_row_map_and_legacy_sample_stream():
    scorer = RecordedScorer()
    bot = make_bot(scorer)
    bot.on_game_start(GameStart.from_request(start_payload()))
    # The established v1 stream definition, independent of the v2 envelope.
    digest = hashlib.sha256(b"spellbench-kernel-flat-bot/v1\0g-test\0p0").digest()
    rng = SplitMix64(11 ^ int.from_bytes(digest[:8], "big"))
    for step in (0, 1, 2):
        incoming = decision(step)
        expected_seed = rng.next()
        assert bot.choose(incoming) == [2, 0][expected_seed % 2]
        request = scorer.requests[-1]
        assert request["sample_seed"] == expected_seed
        assert request["tensor"] == incoming.extensions[integration.EXTENSION]["tensor"]
        assert request["row_candidate_ids"] == [2, 0]
        assert request["step"] == step
    bot.close()


@pytest.mark.parametrize("changes", [
    {"card_db_hash": "other"}, {"feature_contract_digest": "0" * 64},
    {"feature_encoding_digest": "0" * 64}, {"acting_seat": "p1"}, {"step": 9},
    {"row_candidate_ids": [0, 0]}, {"row_candidate_ids": [True, 1]},
    {"row_candidate_ids": [0, 4]}, {"row_candidate_ids": []}, {"tensor": {}},
])
def test_mismatched_input_never_reaches_scorer(changes):
    scorer = RecordedScorer()
    bot = make_bot(scorer)
    bot.on_game_start(GameStart.from_request(start_payload()))
    with pytest.raises(integration.BotError):
        bot.choose(decision(**changes))
    assert scorer.requests == []


def test_v2_wire_requires_native_extension_and_returns_legal_candidate():
    scorer = RecordedScorer()
    bot = make_bot(scorer)
    session = BotSession(choose=bot.choose, on_game_start=bot.on_game_start,
                         name="g115", version="2.0.0",
                         requires_extensions=(integration.EXTENSION,),
                         extensions_accepted=(integration.EXTENSION,))
    def send(kind, payload):
        return json.loads(session.handle_line(json.dumps({
            "protocol": "spellbench/v2", "request_type": kind, "request_id": kind, **payload,
        }).encode()))
    hello = send("hello", {})
    assert hello["requires"]["extensions"] == [integration.EXTENSION]
    assert send("game_start", start_payload())["response_type"] == "ack"
    reply = send("choose", decision().raw)
    assert reply["response_type"] == "choice"
    assert reply["selection"]["candidate_id"] in (0, 2)


def test_real_scorer_transport_keeps_binary32_bits(tmp_path):
    fake = Path(__file__).with_name("fake_scorer.py")
    scorer = integration.ScorerProcess([sys.executable, str(fake), "--config", str(tmp_path / "unused")])
    bot = make_bot(scorer)
    try:
        bot.on_game_start(GameStart.from_request(start_payload()))
        assert bot.choose(decision()) in (0, 2)
    finally:
        bot.close()
