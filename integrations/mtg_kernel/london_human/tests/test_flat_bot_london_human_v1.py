"""The human-play London bot: V7 identity, its own pregame answers, and the keep-seven TEST mode."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "python"))

import kernel_flat_bot_london_human_v1 as bot_module  # noqa: E402
from spellbench.bot import Decision, GameStart  # noqa: E402

V7_CONTRACT = "1f894f0dcaaeb4e5ac0233e3f39d866c0dddca494f1afc8152107bded0551a4d"
V7_ENCODING = "4c592d136a74240f40b12c638203ab1758ed3cd63748ab7cd2788a60a78850a3"
V4_CONTRACT = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
DB = "064a7c989255ab3c"
TENSOR = {key: [0] for key in bot_module.TENSOR_KEYS}
GAME = "london-g1"


class FakeScorer:
    """Stands in for the native scorer: answers the highest-numbered row, and counts its requests."""

    def __init__(self, *, contract: str = V7_CONTRACT, encoding: str = V7_ENCODING) -> None:
        self.ready = {"schema": bot_module.READY_SCHEMA, "feature_contract_digest": contract,
                      "feature_encoding_digest": encoding, "sampler_identity": bot_module.SAMPLER_IDENTITY,
                      "float_encoding": bot_module.FLOAT_ENCODING, "selection": bot_module.ARGMAX, "card_db_hash": DB,
                      "model_state_sha256": "e" * 64}
        self.requests: list[dict] = []

    def score(self, request: dict):
        self.requests.append(request)
        line = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        row = len(request["row_candidate_ids"]) - 1
        return line, {"schema": bot_module.CHOICE_SCHEMA, "request_id": request["request_id"],
                      "request_sha256": hashlib.sha256(line).hexdigest(), "selected_row": row,
                      "selected_candidate_id": request["row_candidate_ids"][row], "logits_bits": [0], "value_bits": 0}

    def close(self) -> None:
        pass


def make_bot(scorer: FakeScorer | None = None, *, keep_seven: bool = False) -> tuple[bot_module.KernelFlatBot, FakeScorer]:
    scorer = scorer or FakeScorer()
    bot = bot_module.KernelFlatBot(scorer, seed=3, decision_log=None, name="london-test", version="v",
                                   test_keep_seven=keep_seven)
    bot.on_game_start(GameStart.from_request({
        "game_id": GAME, "seat": "p0", "engine": {"name": "mtg-kernel",
                                                  "card_pool_identity": f"mtg-kernel-pauper-pool-v1/carddb-{DB}"}}))
    return bot, scorer


def decision(semantics: list[dict], *, step: int = 0, flat_key: str = "x_kernel_flat_v7") -> Decision:
    extension = {"schema": bot_module.EXTENSION_SCHEMA, "feature_contract_digest": V7_CONTRACT,
                 "feature_encoding_digest": V7_ENCODING, "card_db_hash": DB, "acting_seat": "p0", "step": step,
                 "row_candidate_ids": list(range(len(semantics))), "tensor": TENSOR}
    return Decision.from_request({"game_id": GAME, "decision": {
        "acting_seat": "p0", "seat_step": step, "observation": {}, "context": {}, "group": {},
        "candidates": [{"candidate_id": i, "semantic": s, "display_text": None} for i, s in enumerate(semantics)],
        "extensions": {flat_key: extension}}})


KEEP = {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True}
MULLIGAN = {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": False}
PASS = {"kind": "pass"}
LAND = {"kind": "play_land", "source": {"object_id": "x"}, "face": 0}


def test_the_bot_serves_the_v7_identity_and_refuses_a_v4_scorer() -> None:
    assert (bot_module.FEATURE_CONTRACT_DIGEST, bot_module.FEATURE_ENCODING_DIGEST) == (V7_CONTRACT, V7_ENCODING)
    assert bot_module.EXTENSION == "x_kernel_flat_v7"
    with pytest.raises(bot_module.BotError):
        bot_module.KernelFlatBot(FakeScorer(contract=V4_CONTRACT), seed=0, decision_log=None, name="n", version="v")


def test_a_learned_bot_answers_a_mulligan_decision_from_its_model_alone() -> None:
    bot, scorer = make_bot()
    chosen = bot.choose(decision([MULLIGAN, KEEP]))
    assert chosen == 1  # the fake scorer's choice, nothing of the bot's own
    [request] = scorer.requests
    assert (request["feature_contract_digest"], request["feature_encoding_digest"]) == (V7_CONTRACT, V7_ENCODING)
    assert request["tensor"] == TENSOR and request["row_candidate_ids"] == [0, 1]
    # A decision that carries only the V4 payload is refused: no silent fallback.
    with pytest.raises(bot_module.BotError):
        bot.choose(decision([MULLIGAN, KEEP], step=1, flat_key="x_kernel_flat_v4"))


def test_keep_seven_test_mode_keeps_without_scoring_a_mulligan_decision_only() -> None:
    bot, scorer = make_bot(keep_seven=True)
    assert bot.choose(decision([MULLIGAN, KEEP])) == 1
    assert scorer.requests == []
    # Everything else is the model's: an in-game decision is scored as usual.
    bot.choose(decision([PASS, LAND], step=1))
    assert len(scorer.requests) == 1
    # A decision that mixes kinds is never mistaken for the mulligan decision.
    bot.choose(decision([MULLIGAN, LAND], step=2))
    assert len(scorer.requests) == 2


def test_the_keep_seven_flag_exists_only_as_a_named_test_option(capsys) -> None:
    with pytest.raises(SystemExit):
        bot_module.main(["--help"])
    assert "--test-keep-seven" in capsys.readouterr().out
