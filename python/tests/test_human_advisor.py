"""The advisor of a human session: a second scorer reads the person's own decisions and the session shows its read.

The scorer here is the mtg-kernel test double (integrations/mtg_kernel/tests/fake_scorer.py): the same JSONL records,
no model. Sampled mode scores every row 0 (an even split); argmax mode scores the last row 1 and the others 0."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from spellbench.human import relay
from spellbench.human.advisor import Advisor, AdvisorError, scorer_argv, softmax
from spellbench.human.server import ADVISED_NOTE, Hub

from test_human_manabrew import bridge_in_game
from test_human_manabrew_london import ME, mulligan_decision, pending_of

FAKE = Path(__file__).resolve().parents[2] / "integrations" / "mtg_kernel" / "tests" / "fake_scorer.py"
CONTRACT = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
ENCODING = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"
CARD_DB = "064a7c989255ab3c"


def model_input(rows: list[int], **changes) -> dict:
    return {"schema": "mtg-kernel-spellbench-flat-v4/v1", "feature_contract_digest": CONTRACT,
            "feature_encoding_digest": ENCODING, "card_db_hash": CARD_DB, "acting_seat": ME, "step": 0,
            "row_candidate_ids": rows, "tensor": {"state": [1, 2, 3]}, **changes}


def advised(decision: dict, extension: dict | None, name: str = "x_kernel_flat_v7") -> dict:
    """The ``choose`` request of a decision as the relay forwards it in a session with an advisor."""
    extensions = {"x_public_history_v1": {"events": []}}
    if extension is not None:
        extensions[name] = extension
    return {"game_id": "g-1", "decision": {**decision, "extensions": extensions}}


@pytest.fixture
def advisor():
    made: list[Advisor] = []

    def make(mode: str = "ok", **kw) -> Advisor:
        made.append(Advisor([sys.executable, "-B", str(FAKE), "--mode", mode], name="bot-a", label="Bot A", **kw))
        return made[-1]

    yield make
    for one in made:
        one.close()


def ask(hub: Hub, request: dict) -> dict:
    """``pending_of`` for a whole ``choose`` request (the helper wraps a bare decision)."""
    import threading
    result: dict = {}
    thread = threading.Thread(target=lambda: result.update(answer=hub.choose(request)), daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None and thread.is_alive():
            hub.cond.wait(0.05)
    return {"thread": thread, "result": result}


def test_the_scorer_of_a_bot_command_is_its_program_arguments_and_config() -> None:
    command = ["python", "bot.py", "--scorer", "scorer.exe", "--scorer-arg", "--threads", "--scorer-arg", "1",
               "--config", "c.json", "--name", "bot-a", "--version", "1"]
    assert scorer_argv(command) == ["scorer.exe", "--threads", "1", "--config", "c.json"]
    with pytest.raises(ValueError):
        scorer_argv(["python", "uniform.py", "--seed", "1"])


def test_the_shares_are_the_softmax_of_the_scores() -> None:
    shares = softmax([0.0, 1.0, -1000.0])
    assert shares[1] == pytest.approx(math.e / (1 + math.e)) and shares[2] == 0.0
    assert sum(shares) == pytest.approx(1.0)


def test_a_read_gives_each_row_its_share_and_the_value(advisor) -> None:
    decision = mulligan_decision(7, 0)
    even = advisor("ok").read("g-1", decision, model_input([1, 0]))
    assert even == {"rows": [{"id": 1, "p": 0.5}, {"id": 0, "p": 0.5}], "value": 0.0, "win": 0.5}
    last = advisor("argmax").read("g-1", decision, model_input([1, 0]))
    assert [row["id"] for row in last["rows"]] == [1, 0]  # the model's row order
    assert last["rows"][1]["p"] == pytest.approx(math.e / (1 + math.e))


def test_a_decision_the_model_cannot_read_says_why_and_the_scorer_is_not_asked(advisor) -> None:
    one = advisor("die-after-1")  # would fail on a second request: none of these is one
    decision = mulligan_decision(7, 0)
    assert "no model input" in one.read("g-1", decision, None)["unavailable"]
    assert "another model input" in one.read("g-1", decision, model_input([0, 1], card_db_hash="other"))["unavailable"]
    assert "X choice" in one.read("g-1", decision, model_input([0, 1], numeric_choice_v4_fill=True))["unavailable"]
    assert "does not match" in one.read("g-1", decision, model_input([0, 5]))["unavailable"]
    assert "rows" in one.read("g-1", decision, model_input([0, 1]))


def test_a_scorer_that_never_becomes_ready_or_dies_is_an_advisor_error(advisor) -> None:
    with pytest.raises(AdvisorError):
        advisor("no-ready")
    with pytest.raises(AdvisorError):
        advisor("load-error")
    one = advisor("die-after-1")
    decision = mulligan_decision(7, 0)
    one.read("g-1", decision, model_input([0, 1]))
    with pytest.raises(AdvisorError):
        one.read("g-1", decision, model_input([0, 1]))


def test_the_person_sees_the_read_with_their_own_choice_texts_and_the_record_keeps_it(advisor, tmp_path) -> None:
    hub = Hub(log_dir=tmp_path, advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    assert hub.log[0]["text"] == ADVISED_NOTE.format(label="Bot A")
    started = ask(hub, advised(mulligan_decision(7, 0), model_input([0, 1])))
    advice = hub.advice
    texts = {c["id"]: c["text"] for c in hub.pending["candidates"]}
    assert advice["model"] == "Bot A" and advice["seq"] == hub.pending["seq"] and "chosen" not in advice
    assert [(row["ids"], row["text"]) for row in advice["rows"]] == [([1], texts[1]), ([0], texts[0])]  # likeliest first
    assert advice["rows"][0]["p"] == pytest.approx(math.e / (1 + math.e), abs=1e-4)
    assert advice["win"] == 0.5
    # the model input is the advisor's alone: nothing the person's side reads holds it
    assert "tensor" not in json.dumps(hub.state())
    hub.answer_with(hub.pending["seq"], 0)
    started["thread"].join(timeout=5)
    assert started["result"]["answer"] == 0 and hub.advice["chosen"] == 0
    hub.game_end({"game_id": "g-1", "terminal": {"winner": ME, "classification": "win", "reason": "win"}})
    records = [json.loads(line) for line in (tmp_path / f"g-1.{ME}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["advisor"] == {"name": "bot-a", "label": "Bot A", "model_state_sha256": "0" * 64,
                                     "selection": "argmax-first-v1"}
    assert records[1]["advisor"]["value"] == 0.0
    assert [cid for cid, _ in records[1]["advisor"]["probabilities"]] == [0, 1]  # the model's row order


def test_choices_the_person_reads_as_the_same_line_are_one_row_with_their_shares_added(advisor, tmp_path) -> None:
    hub = Hub(log_dir=tmp_path, advisor=advisor("ok"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    decision = mulligan_decision(7, 0)
    same = decision["candidates"][0]["semantic"]  # a third choice that reads exactly like the first
    decision["candidates"].append({"candidate_id": 2, "semantic": dict(same), "display_text": None})
    started = ask(hub, advised(decision, model_input([0, 1, 2])))
    texts = {c["id"]: c["text"] for c in hub.pending["candidates"]}
    assert texts[0] == texts[2] != texts[1]
    rows = hub.advice["rows"]
    assert [(row["ids"], row["text"]) for row in rows] == [([0, 2], texts[0]), ([1], texts[1])]
    assert rows[0]["p"] == pytest.approx(2 / 3, abs=1e-4) and rows[1]["p"] == pytest.approx(1 / 3, abs=1e-4)
    hub.answer_with(hub.pending["seq"], 2)
    started["thread"].join(timeout=5)
    hub.game_end({"game_id": "g-1", "terminal": {"winner": ME, "classification": "win", "reason": "win"}})
    records = [json.loads(line) for line in (tmp_path / f"g-1.{ME}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [cid for cid, _ in records[1]["advisor"]["probabilities"]] == [0, 1, 2]  # each candidate's own share


def test_a_session_without_an_advisor_has_no_read_and_the_same_record(tmp_path) -> None:
    hub = Hub(log_dir=tmp_path)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    started = pending_of(hub, mulligan_decision(7, 0))
    assert hub.advice is None and hub.state()["advisor"] is None
    hub.answer_with(started["pending"]["seq"], 1)
    started["thread"].join(timeout=5)
    hub.game_end({"game_id": "g-1", "terminal": {"winner": ME, "classification": "win", "reason": "win"}})
    records = [json.loads(line) for line in (tmp_path / f"g-1.{ME}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["advisor"] is None and "advisor" not in records[1]


def test_a_scorer_that_dies_mid_game_is_dropped_with_a_log_line_and_the_game_goes_on(advisor) -> None:
    hub = Hub(advisor=advisor("die-after-1"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    for step in range(3):
        started = ask(hub, advised(mulligan_decision(7, 0), model_input([0, 1])))
        if step == 0:
            assert "rows" in hub.advice
        else:
            assert "unavailable" in hub.advice
        hub.answer_with(hub.pending["seq"], 1)
        started["thread"].join(timeout=5)
        assert started["result"]["answer"] == 1
    assert hub.advisor is None and hub.advisor_identity is not None  # the games stay marked as advised
    assert sum("The advisor stopped" in line["text"] for line in hub.log) == 1


def advice_sent(bridge) -> list[dict]:
    return [m["state"]["entry"]["advisor"] for m in bridge.host.sent
            if m.get("state", {}).get("kind") == "log" and "advisor" in m["state"]["entry"]]


def test_the_client_gets_the_read_once_its_panels_are_up_and_again_with_the_answer(advisor) -> None:
    hub = Hub(opponent="Basilisk 2", advisor=advisor("ok"))
    bridge = bridge_in_game(hub)
    bridge.seats = None  # the first view creates the seats and holds the log (and the read) back
    bridge.dealt = {"human": "Wildfire", "bot": "Rally", "differs": False}
    started = ask(hub, advised(mulligan_decision(7, 0), model_input([0, 1])))
    bridge._push(hub.state())
    assert advice_sent(bridge) == []  # held like the log lines: the panel does not exist yet
    bridge._log_hold_until = 0.0
    bridge._push(hub.state())
    bridge._push(hub.state())
    sent = advice_sent(bridge)
    assert len(sent) == 1 and len(sent[0]["rows"]) == 2 and "chosen" not in sent[0]  # once per decision
    assert "scores" not in sent[0]  # the per-candidate shares are the record's
    entry = next(m["state"]["entry"] for m in bridge.host.sent if "advisor" in m["state"].get("entry", {}))
    assert entry["message"] == ""  # their client's own log code ignores a line without a message
    hub.answer_with(hub.pending["seq"], 1)
    started["thread"].join(timeout=5)
    bridge._push(hub.state())
    assert advice_sent(bridge)[-1]["chosen"] == 1 and len(advice_sent(bridge)) == 2


def test_the_relay_keeps_the_model_input_only_for_a_session_with_an_advisor() -> None:
    class Stub(relay.Relay):
        def __init__(self, advisor: bool) -> None:
            super().__init__("http://127.0.0.1:1", "t")
            self.advisor, self.posted = advisor, []

        def post(self, path: str, body: dict) -> dict:
            self.posted.append((path, body))
            return {"ok": True, "advisor": self.advisor, "candidate_id": 0}

    from spellbench.bot import Decision
    request = {"game_id": "g-1", "decision": {**mulligan_decision(7, 0), "extensions": {
        "x_kernel_flat_v7": model_input([0, 1]), "x_public_history_v1": {"events": []}}}}
    for advisor_on in (False, True):
        stub = Stub(advisor_on)
        stub.wait_ready()
        stub.choose(Decision.from_request(request))
        forwarded = stub.posted[-1][1]["request"]["decision"]["extensions"]
        assert ("x_kernel_flat_v7" in forwarded) is advisor_on and "x_public_history_v1" in forwarded
