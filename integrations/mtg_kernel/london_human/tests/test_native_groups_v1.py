"""The bot's grouped decisions answered natively at the London human engine (``--native-seat``).

With the option the bot's block declaration, card arrangement, selection order and trigger order are never posed to
the protocol as one grouped decision with completion proposals: each of the engine's own questions in it goes to the
bot's model (its own scorer) with the engine's own model input, and the row the scorer samples is the bot's answer, as
the trainer's session answers every native question. The person's seat keeps its grouped decisions and proposals.
The bridge-backed tests need MTG_KERNEL_LONDON_HUMAN_BRIDGE and MTG_KERNEL_PUBLIC_CATALOG; they use a stand-in
scorer (a seeded pick), since what is proven here is which questions reach the model and with what input. That the
bot's native questions equal the trainer's own session is proven at the wrapper level with the real scorer by
tools/native_groups_proof_v1.py and the mtg-kernel replay test.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

BRIDGE = os.environ.get("MTG_KERNEL_LONDON_HUMAN_BRIDGE")
CATALOG = os.environ.get("MTG_KERNEL_PUBLIC_CATALOG")
needs_bridge = pytest.mark.skipif(not (BRIDGE and CATALOG and Path(BRIDGE).exists()),
                                  reason="needs the London bridge and the public catalog")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[3] / "python"))

import kernel_flat_bot_london_human_v1 as flat_bot  # noqa: E402
from kernel_engine_london_human_v1 import (FLAT, PROPOSALS, KernelEngine, NativePeer,  # noqa: E402
                                           check_native_scorer)
from test_bot_windows_v1 import Recorder, pick, reset_value, send  # noqa: E402

PERSON, BOT = "p0", "p1"
GROUPED = {"declare_block", "arrange_card", "order_pick"}  # what a grouped decision poses (with proposals)


class SeededScorer:
    """A stand-in for the bot's scorer: the ready record the bot checks, and a pick of the sample seed modulo the
    rows, answered in the scorer's choice schema. It records every request."""

    def __init__(self) -> None:
        self.ready = {"schema": flat_bot.READY_SCHEMA, "feature_contract_digest": flat_bot.FEATURE_CONTRACT_DIGEST,
                      "feature_encoding_digest": flat_bot.FEATURE_ENCODING_DIGEST,
                      "sampler_identity": flat_bot.SAMPLER_IDENTITY, "float_encoding": flat_bot.FLOAT_ENCODING,
                      "selection": flat_bot.SAMPLED, "model_state_sha256": "0" * 64, "card_db_hash": "x"}
        self.requests: list[dict] = []

    def score(self, request: dict) -> tuple[bytes, dict]:
        self.requests.append(request)
        line = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        rows = request["row_candidate_ids"]
        row = request["sample_seed"] % len(rows)
        return line, {"schema": flat_bot.CHOICE_SCHEMA, "request_id": request["request_id"],
                      "request_sha256": hashlib.sha256(line).hexdigest(), "selected_row": row,
                      "selected_candidate_id": rows[row], "logits_bits": [0] * len(rows), "value_bits": 0}


def test_the_native_seat_is_the_bots_and_needs_its_scorer() -> None:
    with pytest.raises(ValueError):
        KernelEngine(Recorder(), {"catalog": []}, native_seat=BOT)  # no scorer
    with pytest.raises(ValueError):
        KernelEngine(Recorder(), {"catalog": []}, engine_windows_seat=BOT, native_seat=BOT,
                     native_scorer=SeededScorer())
    with pytest.raises(ValueError):
        KernelEngine(Recorder(), {"catalog": []}, line_seat=BOT, native_seat=BOT, native_scorer=SeededScorer())


def test_a_scorer_the_bot_would_refuse_is_refused() -> None:
    check_native_scorer(SeededScorer())
    for key, value in (("sampler_identity", "other"), ("feature_contract_digest", "0"), ("selection", "x"),
                       ("float_encoding", "f64")):
        scorer = SeededScorer()
        scorer.ready[key] = value
        with pytest.raises(ValueError):
            check_native_scorer(scorer)
    with pytest.raises(ValueError):
        check_native_scorer(SeededScorer(), expect_model_state="1" * 64)


class World:
    def __init__(self, seed: int, *, native: bool, first: str, person: str, bot: str, log: Path | None) -> None:
        catalog = json.loads(Path(CATALOG).read_bytes())
        self.peer = NativePeer(BRIDGE)
        self.scorer = SeededScorer() if native else None
        self.engine = KernelEngine(self.peer, catalog, engine_windows_seat=PERSON, auto_graveyard_order=True,
                                   action_windows_seat=BOT, native_seat=BOT if native else None,
                                   native_scorer=self.scorer, native_seed=seed, native_log=log)
        self.serial = 0
        self.current = self.send(reset_value(catalog, seed, first=first, person=person, bot=bot))

    def send(self, value: dict) -> dict:
        self.serial += 1
        return send(self.engine, value, self.serial)

    def answer(self, candidate: int) -> None:
        sd = self.current["seat_decision"]
        self.current = self.send({"request_type": "step", "game_id": self.current["game_id"],
                                  "expected_step": self.current["step"],
                                  "selection": {"candidate_id": candidate,
                                                "semantic_echo": sd["candidates"][candidate]["semantic"]}})


def play(seed: int, *, native: bool, first: str, person: str, bot: str, log: Path | None = None) -> dict:
    """One game to its end: the grouped decisions posed to each seat, and the stand-in scorer's requests."""
    world = World(seed, native=native, first=first, person=person, bot=bot, log=log)
    rng = random.Random(seed)
    posed = {PERSON: Counter(), BOT: Counter()}
    proposals = {PERSON: 0, BOT: 0}
    try:
        for _ in range(40_000):
            if world.current["response_type"] != "decision":
                assert world.current["classification"] == "natural", world.current
                break
            sd = world.current["seat_decision"]
            kinds = {c["semantic"]["kind"] for c in sd["candidates"]}
            if kinds & GROUPED and not any(c["semantic"].get("purpose") == "mulligan_bottom"
                                           for c in sd["candidates"]):
                posed[sd["acting_seat"]][kinds.pop()] += 1
            if (sd["extensions"].get(FLAT) or {}).get("schema") == PROPOSALS:
                proposals[sd["acting_seat"]] += 1
            world.answer(pick(sd, rng))
        else:
            pytest.fail(f"seed {seed}: the game did not end")
    finally:
        world.peer.close()
    return {"posed": posed, "proposals": proposals, "requests": world.scorer.requests if world.scorer else []}


@needs_bridge
@pytest.mark.parametrize("first", ["p0", "p1"])
def test_the_bots_groups_reach_its_model_one_native_question_at_a_time(first: str, tmp_path: Path) -> None:
    log = tmp_path / "native.jsonl"
    groups: Counter = Counter()
    for seed, (person, bot) in enumerate([("Faeries", "Faeries"), ("Burn", "Faeries"), ("Spy", "CawGates"),
                                          ("Faeries", "Affinity")], start=1):
        plain = play(seed, native=False, first=first, person=person, bot=bot)
        native = play(seed, native=True, first=first, person=person, bot=bot, log=log)
        # The bot is never posed a grouped decision and never gets completion proposals; the person keeps them. (The
        # two games are not the same game: with the option the bot also takes the trainer's own single-option choices.)
        assert not native["posed"][BOT] and native["proposals"][BOT] == 0, native
        for request in native["requests"]:
            # The engine's own model input, rows in the engine's own order, a seed of the bot's native stream.
            assert request["schema"] == flat_bot.REQUEST_SCHEMA and "tensor" in request
            assert request["seat"] == BOT and type(request["sample_seed"]) is int
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    for record in records:
        if record["kind"] == "question":
            groups[record["group"]] += 1
    assert groups["block"] > 0, dict(groups)
    assert sum(1 for r in records if r["kind"] == "header") == 4
    print(f"native questions by group ({first} first): {dict(groups)}")


@pytest.mark.skipif(not (CATALOG and Path(CATALOG).exists()), reason="needs the public catalog")
@pytest.mark.parametrize("first,bridge_seat", [("p0", "p1"), ("p1", "p0")])
def test_the_reset_names_the_bots_bridge_seat_for_trainer_choices_only_with_the_option(first: str,
                                                                                      bridge_seat: str) -> None:
    catalog = json.loads(Path(CATALOG).read_bytes())
    sent = {}
    for native in (False, True):
        peer = Recorder()
        engine = KernelEngine(peer, catalog, engine_windows_seat=PERSON, action_windows_seat=BOT,
                              native_seat=BOT if native else None, native_scorer=SeededScorer() if native else None)
        answer = send(engine, reset_value(catalog, 1, first=first, person="Faeries", bot="Burn"))
        sent[native] = [r for r in peer.requests if r["request_type"] == "reset"][0]
        if native:  # a bridge without the field refuses it, and the session says what it needs
            assert "trainer_choice_seats" in answer["error"]["message"]
    assert "trainer_choice_seats" not in sent[False]
    assert sent[True].pop("trainer_choice_seats") == [bridge_seat]
    assert sent[True] == sent[False]


@needs_bridge
def test_a_log_that_cannot_be_written_never_stops_the_game(tmp_path: Path, capsys) -> None:
    result = play(2, native=True, first="p0", person="Faeries", bot="Faeries", log=tmp_path)  # a folder: not writable
    assert result["requests"]  # the bot's native questions were asked and the game ended naturally (play checks it)
    assert "is not written from here on" in capsys.readouterr().err
