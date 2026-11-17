"""The advisor of a human session: a second scorer reads the person's own decisions and the session shows its read.

The scorer here is the mtg-kernel test double (integrations/mtg_kernel/tests/fake_scorer.py): the same JSONL records,
no model. Sampled mode scores every row 0 (an even split); argmax mode scores the last row 1 and the others 0."""

from __future__ import annotations

import json
import math
import sys
import threading
import time
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
    """``pending_of`` for a whole ``choose`` request (the helper wraps a bare decision), once its read is back (reads
    run in the advisor's own thread)."""
    import threading
    result: dict = {}
    thread = threading.Thread(target=lambda: result.update(answer=hub.choose(request)), daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None and thread.is_alive():
            hub.cond.wait(0.05)
    assert hub.wait_reads(10)
    return {"thread": thread, "result": result}


def choose(hub: Hub, request: dict) -> int:
    """A decision the session answers without the person (a later creature of a planned declaration): the answer, once
    the reads it queued are back."""
    answer = hub.choose(request)
    assert hub.wait_reads(10)
    return answer


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


# -- attack and block declarations: one question per creature, named, and the declaration's reads together ---------------

OPP = "p1"


def creature(oid: str, name: str, seat: str = ME) -> dict:
    return {"object_id": oid, "card_name": name, "owner_seat": seat, "controller_seat": seat, "zone": "battlefield"}


def combat_substep(kind: str, index: int, count: int, subject: dict, aims: list, *, turn: int = 5, active: str = ME,
                   group_id: int = 9, phase: str | None = None) -> dict:
    """One substep of an attack (``declare_attack``) or block (``declare_block``) declaration as the engine poses it."""
    role, other = ("attacker", "defender") if kind == "declare_attack" else ("blocker", "attacker")
    phase = phase or ("declare_attackers" if kind == "declare_attack" else "declare_blockers")
    return {"acting_seat": ME, "seat_step": 10 + index,
            "group": {"group_id": group_id, "substep_index": index, "substep_count": count},
            "context": {"kind": "choice", "source": None, "purpose": None, "text": None, "rewind": False},
            "observation": {"viewer": ME, "turn": turn, "phase_step": phase, "active_seat": active, "priority_seat": ME,
                            "players": [{"seat": ME, "life": 20, "battlefield": []},
                                        {"seat": OPP, "life": 20, "battlefield": []}], "stack": [], "known": []},
            "candidates": [{"candidate_id": i, "semantic": {"kind": kind, role: subject, other: aim}, "display_text": None}
                           for i, aim in enumerate(aims)]}


def priority(*, phase: str, turn: int = 5, active: str = ME) -> dict:
    bolt = {"object_id": "o-b", "card_name": "Lightning Bolt", "owner_seat": ME, "controller_seat": ME, "zone": "hand"}
    request = combat_substep("declare_attack", 0, 1, creature("x", "x"), [None], turn=turn, active=active, phase=phase)
    request["context"]["kind"] = "priority"
    request["candidates"] = [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None},
                             {"candidate_id": 1, "semantic": {"kind": "cast_spell", "source": bolt, "method": "normal"},
                              "display_text": None}]
    return request


MULLDRIFTER, MISCREANT, SEER = creature("o-m", "Mulldrifter"), creature("o-f", "Faerie Miscreant"), creature("o-s", "Faerie Seer")
FOE = {"player": OPP}


def attack_with_plan(hub: Hub, attackers: list[str]) -> list[int]:
    """The person declares a three-creature attack on one screen (the plan answers substeps 2 and 3)."""
    started = ask(hub, advised(combat_substep("declare_attack", 0, 3, MULLDRIFTER, [None, FOE]), model_input([0, 1])))
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": attackers}) is None
    started["thread"].join(timeout=5)
    answers = [started["result"]["answer"]]
    for index, subject in ((1, MISCREANT), (2, SEER)):
        answers.append(choose(hub, advised(combat_substep("declare_attack", index, 3, subject, [None, FOE]),
                                          model_input([0, 1]))))
    return answers


def test_an_attack_read_names_its_creature_and_question_and_plain_choices(advisor) -> None:
    hub = Hub(advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    started = ask(hub, advised(combat_substep("declare_attack", 0, 3, MULLDRIFTER, [None, FOE]), model_input([0, 1])))
    question = hub.advice["question"]
    assert question["title"] == "Attack with Mulldrifter?" and (question["index"], question["count"]) == (0, 3)
    assert question["subject_id"] == "o-m" and question["screen"] == "attack"
    assert [(row["short"], row["p"]) for row in hub.advice["rows"]] == [("attack", pytest.approx(0.7311, abs=1e-4)),
                                                                         ("hold back", pytest.approx(0.2689, abs=1e-4))]
    assert "declaration" not in hub.advice  # nothing of this declaration is answered yet
    hub.answer_with(hub.pending["seq"], 1)
    started["thread"].join(timeout=5)


def test_the_reads_of_every_creature_of_a_one_screen_attack_are_listed_with_the_persons_answers(advisor, tmp_path) -> None:
    hub = Hub(log_dir=tmp_path, advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    assert attack_with_plan(hub, ["o-m", "o-s"]) == [1, 0, 1]
    declaration = hub.advice["declaration"]
    assert declaration["kind"] == "attack" and declaration["count"] == 3
    items = declaration["items"]
    assert [(i["index"], i["subject"], i["chosen"], i["how"]) for i in items] == [
        (0, "Mulldrifter", "attack", "plan"), (1, "Faerie Miscreant", "hold back", "plan"), (2, "Faerie Seer", "attack", "plan")]
    assert all(i["p_attack"] == pytest.approx(0.7311, abs=1e-4) for i in items)
    assert items[1]["p_chosen"] == pytest.approx(0.2689, abs=1e-4)
    assert hub.advice["chosen"] == 1 and not any(i.get("reading") for i in items)  # the first read, with two more
    # The records are as before: the advisor's shares only for the decision the person was shown.
    hub.game_end({"game_id": "g-1", "terminal": {"winner": ME, "classification": "win", "reason": "win"}})
    records = [json.loads(line) for line in (tmp_path / f"g-1.{ME}.jsonl").read_text(encoding="utf-8").splitlines()]
    decisions = [r for r in records if r.get("kind") == "decision"]
    assert ["advisor" in r for r in decisions] == [True, False, False]
    assert [r["how"] for r in decisions] == ["plan", "plan", "plan"]
    assert "tensor" not in json.dumps(hub.state())


def test_the_declaration_stays_with_the_reads_of_that_combat_and_ends_after_it(advisor) -> None:
    hub = Hub(advisor=advisor("ok"), real_action_stops=True)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    attack_with_plan(hub, ["o-m"])
    started = ask(hub, advised(priority(phase="declare_blockers"), model_input([0, 1])))
    assert len(hub.advice["declaration"]["items"]) == 3  # a read later in the same combat shows the attack too
    hub.answer_with(hub.pending["seq"], 0)
    started["thread"].join(timeout=5)
    started = ask(hub, advised(priority(phase="postcombat_main"), model_input([0, 1])))
    assert "declaration" not in hub.advice and hub.declaration is None  # combat is over
    hub.answer_with(hub.pending["seq"], 0)
    started["thread"].join(timeout=5)


def test_a_block_read_names_the_blocker_and_the_attacker(advisor) -> None:
    hub = Hub(advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    guardian, ogre = creature("o-g", "Guardian of the Guildpact", OPP), creature("o-o", "Ogre", OPP)
    skyfisher = creature("o-k", "Kor Skyfisher")
    started = ask(hub, advised(combat_substep("declare_block", 0, 2, skyfisher, [None, guardian], active=OPP),
                               model_input([0, 1])))
    assert hub.advice["question"]["title"] == "Block Guardian of the Guildpact with Kor Skyfisher?"
    assert [row["short"] for row in hub.advice["rows"]] == ["block Guardian of the Guildpact", "no block"]
    assert hub.plan_with(hub.pending["seq"], {"kind": "block", "blocks": {"o-k": None, "o-w": "o-o"}}) is None
    started["thread"].join(timeout=5)
    wall = creature("o-w", "Wall of Roots")
    request = advised(combat_substep("declare_block", 1, 2, wall, [None, guardian, ogre], active=OPP),
                      model_input([0, 1, 2]))
    assert choose(hub, request) == 2
    items = hub.advice["declaration"]["items"]
    assert [(i["subject"], i["chosen"]) for i in items] == [("Kor Skyfisher", "no block"), ("Wall of Roots", "block Ogre")]
    assert items[1]["rows"][0] == {"text": "block Ogre", "target": "object:o-o", "p": pytest.approx(0.5761, abs=1e-4)}  # e / (2 + e)
    assert "p_attack" not in items[1]


def test_a_creature_with_one_legal_choice_is_listed_without_a_read(advisor) -> None:
    hub = Hub(advisor=advisor("die-after-1"))  # a second read would stop the advisor: none is asked for
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    started = ask(hub, advised(combat_substep("declare_attack", 0, 2, MULLDRIFTER, [None, FOE]), model_input([0, 1])))
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": []}) is None
    started["thread"].join(timeout=5)
    assert choose(hub, advised(combat_substep("declare_attack", 1, 2, SEER, [FOE]), model_input([0]))) == 0
    items = hub.advice["declaration"]["items"]
    assert items[1] == {"index": 1, "subject": "Faerie Seer", "subject_id": "o-s", "chosen": "attack",
                        "chosen_target": "player:p1", "how": "single", "only": True}
    assert hub.advisor is not None


def test_the_client_is_told_the_read_is_one_creature_of_its_combined_screen_and_gets_the_later_reads(advisor) -> None:
    from test_human_manabrew import card
    hub = Hub(opponent="Basilisk 2", advisor=advisor("argmax"))
    bridge = bridge_in_game(hub)
    bridge.dealt = {"human": "Faeries", "bot": "Burn", "differs": False}
    bridge._log_hold_until = 0.0
    request = advised(combat_substep("declare_attack", 0, 2, MULLDRIFTER, [None, FOE]), model_input([0, 1]))
    request["decision"]["observation"]["players"][0]["battlefield"] = [card("o-m", "Mulldrifter", ME, "battlefield"),
                                                                       card("o-s", "Faerie Seer", ME, "battlefield")]
    started = ask(hub, request)
    bridge._push(hub.state())
    first = advice_sent(bridge)[-1]
    assert first["question"]["combined"] is True and first["question"]["title"] == "Attack with Mulldrifter?"
    assert "choices" not in first["question"]  # the hub's own lookup, not the panel's
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": ["o-s"]}) is None
    started["thread"].join(timeout=5)
    choose(hub, advised(combat_substep("declare_attack", 1, 2, SEER, [None, FOE]), model_input([0, 1])))
    bridge._push(hub.state())
    last = advice_sent(bridge)[-1]
    assert [(i["subject"], i["chosen"]) for i in last["declaration"]["items"]] == [("Mulldrifter", "hold back"),
                                                                                    ("Faerie Seer", "attack")]
    assert last["question"]["combined"] is True and last["chosen"] == 0


def ogre(oid: str, *, damage: int = 0) -> dict:
    return {**creature(oid, "Ogre", OPP), "characteristics": {"types": ["creature"], "power": 3, "toughness": 3},
            "permanent": {"tapped": False, "attacking": True, "blocking": False, "counters": {}, "damage": damage}}


def test_two_attackers_of_one_name_stay_two_choices_with_their_own_shares(advisor) -> None:
    hub = Hub(advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    hurt, fresh = ogre("o-a1", damage=1), ogre("o-a2")
    request = advised(combat_substep("declare_block", 0, 1, creature("o-k", "Kor Skyfisher"), [None, hurt, fresh],
                                     active=OPP), model_input([0, 1, 2]))
    request["decision"]["observation"]["players"][1]["battlefield"] = [hurt, fresh]
    started = ask(hub, request)
    rows = hub.advice["rows"]
    assert [(row["short"], row["target"]) for row in rows] == [
        ("block Ogre (3/3)", "object:o-a2"), ("no block", "none"), ("block Ogre (3/3, 1 damage)", "object:o-a1")]
    assert rows[0]["p"] == pytest.approx(0.5761, abs=1e-4) and rows[2]["p"] == pytest.approx(0.2119, abs=1e-4)
    assert hub.plan_with(hub.pending["seq"], {"kind": "block", "blocks": {"o-k": "o-a1"}}) is None
    started["thread"].join(timeout=5)
    assert started["result"]["answer"] == 1
    item = hub.advice["declaration"]["items"][0]
    assert item["chosen"] == "block Ogre (3/3, 1 damage)" and item["chosen_target"] == "object:o-a1"
    assert item["p_chosen"] == pytest.approx(0.2119, abs=1e-4)  # its own share, not the two Ogres' together
    assert len(item["rows"]) == 3


def test_attackers_of_one_name_in_the_same_state_are_numbered() -> None:
    from spellbench.human.server import combat_question
    a, b = ogre("o-a1"), ogre("o-a2")
    request = combat_substep("declare_block", 0, 1, creature("o-k", "Kor Skyfisher"), [None, a, b], active=OPP)
    request["observation"]["players"][1]["battlefield"] = [a, b]
    question = combat_question(request, ME)
    assert question["choices"] == {0: "no block", 1: "block Ogre #1", 2: "block Ogre #2"}
    assert question["targets"] == {0: "none", 1: "object:o-a1", 2: "object:o-a2"}


class StalledAdvisor:
    """An advisor whose scorer stops answering after its first read (``release`` lets it go on)."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.reads = 0

    def identity(self) -> dict:
        return {"name": "stalled", "label": "Stalled", "model_state_sha256": None, "selection": "argmax-first-v1"}

    def read(self, game_id, decision, extension) -> dict:
        self.reads += 1
        if self.reads > 1:
            self.release.wait(20)
        rows = [{"id": c["candidate_id"], "p": 1 / len(decision["candidates"])} for c in decision["candidates"]]
        return {"rows": rows, "value": 0.0, "win": 0.5}

    def close(self) -> None:
        self.release.set()


def test_a_stalled_advisor_never_holds_back_an_answer_or_the_persons_concession() -> None:
    stalled = StalledAdvisor()
    hub = Hub(advisor=stalled)  # type: ignore[arg-type]
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    started = ask(hub, advised(combat_substep("declare_attack", 0, 3, MULLDRIFTER, [None, FOE]), model_input([0, 1])))
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": ["o-m", "o-f", "o-s"]}) is None
    started["thread"].join(timeout=5)
    begun = time.monotonic()
    for index, subject in ((1, MISCREANT), (2, SEER)):  # the scorer is stuck on the first of these
        assert hub.choose(advised(combat_substep("declare_attack", index, 3, subject, [None, FOE]),
                                  model_input([0, 1]))) == 1
    assert time.monotonic() - begun < 1.0  # the planned answers went back at once
    items = hub.advice["declaration"]["items"]
    assert [i.get("reading", False) for i in items] == [False, True, True]  # the panel says they are being read
    begun = time.monotonic()
    assert hub.concede("conceded")  # the lock is free: the person's concession is not held up by the read
    assert time.monotonic() - begun < 1.0
    stalled.release.set()
    assert hub.wait_reads(10)
    from spellbench.human.server import DROPPED_READ
    assert [i.get("unavailable") for i in hub.declaration["items"][1:]] == [DROPPED_READ] * 2  # nothing late lands


def test_a_read_that_lands_after_the_answer_was_accepted_is_not_recorded_as_shown(advisor, tmp_path) -> None:
    hub = Hub(log_dir=tmp_path, advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    captured: list = []
    hub._queue_read = lambda *job: captured.append(job[3])  # type: ignore[method-assign]  # held, not read
    started = ask(hub, advised(mulligan_decision(7, 0), model_input([0, 1])))
    assert hub.advice["reading"]
    with hub.cond:  # the answer is accepted, and the read lands before choose() takes the answer
        assert hub.answer_with(hub.pending["seq"], 1) is None
        captured[0]({"rows": [{"id": 1, "p": 0.7}, {"id": 0, "p": 0.3}], "value": 0.2, "win": 0.6})
    started["thread"].join(timeout=5)
    assert hub.advice["rows"] and hub.advice["late"]  # the panel still shows it, after the answer
    hub.game_end({"game_id": "g-1", "terminal": {"winner": ME, "classification": "win", "reason": "win"}})
    records = [json.loads(line) for line in (tmp_path / f"g-1.{ME}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[1]["advisor"] == {"unavailable": "not read before the answer"}


def test_reads_of_a_game_that_is_over_never_reach_the_scorer_and_the_reader_stops_at_the_end() -> None:
    stalled = StalledAdvisor()
    hub = Hub(advisor=stalled)  # type: ignore[arg-type]
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    started = ask(hub, advised(combat_substep("declare_attack", 0, 4, MULLDRIFTER, [None, FOE]), model_input([0, 1])))
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": []}) is None
    started["thread"].join(timeout=5)
    for index, subject in ((1, MISCREANT), (2, SEER), (3, creature("o-x", "Spellstutter Sprite"))):
        hub.choose(advised(combat_substep("declare_attack", index, 4, subject, [None, FOE]), model_input([0, 1])))
    deadline = time.monotonic() + 5
    while stalled.reads < 2 and time.monotonic() < deadline:  # the scorer is stuck on the second read
        time.sleep(0.01)
    assert hub.concede("conceded")
    stalled.release.set()
    assert hub.wait_reads(10)
    assert stalled.reads == 2  # the two reads queued behind it were dropped, never sent to the scorer
    hub.close_advisor()
    assert hub._reader is not None and not hub._reader.is_alive() and hub.advisor is None


DEAF_SCORER = '''import json, sys, time
print(json.dumps({"schema": "mtg-kernel-spellbench-scorer-ready/v1", "float_encoding": "ieee754-binary32-u32-bits",
                  "selection": "argmax-first-v1", "model_state_sha256": "0" * 64, "feature_contract_digest": %r,
                  "feature_encoding_digest": %r, "card_db_hash": %r}), flush=True)
time.sleep(600)  # never reads its input
''' % (CONTRACT, ENCODING, CARD_DB)


def test_the_session_end_closes_a_scorer_that_stopped_reading_in_bounded_time(tmp_path) -> None:
    script = tmp_path / "deaf_scorer.py"
    script.write_text(DEAF_SCORER, encoding="utf-8")
    deaf = Advisor([sys.executable, "-B", str(script)], name="deaf", label="Deaf")
    hub = Hub(advisor=deaf)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    big = model_input([0, 1], tensor={"state": [0] * 400_000})  # far more than a pipe holds
    asked = threading.Thread(target=lambda: hub.choose(advised(mulligan_decision(7, 0), big)), daemon=True)
    asked.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    time.sleep(1.0)  # the advisor's thread is now stuck writing to the full pipe
    closer = threading.Thread(target=hub.close_advisor, daemon=True)
    begun = time.monotonic()
    closer.start()
    closer.join(15)
    assert not closer.is_alive() and time.monotonic() - begun < 10
    assert deaf._proc.poll() is not None and hub._reader is not None and not hub._reader.is_alive()
    hub.answer_with(hub.pending["seq"], 0)
    asked.join(5)


class GatedAdvisor(StalledAdvisor):
    """Every read waits until ``release`` is set."""

    def read(self, game_id, decision, extension) -> dict:
        self.reads += 1
        self.release.wait(20)
        rows = [{"id": c["candidate_id"], "p": 1 / len(decision["candidates"])} for c in decision["candidates"]]
        return {"rows": rows, "value": 0.0, "win": 0.5}


def open_and_answer(hub: Hub, request: dict, candidate_id: int) -> None:
    """A decision the person is asked and answers (its read may still be on its way)."""
    result: list = []
    thread = threading.Thread(target=lambda: result.append(hub.choose(request)), daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    assert hub.answer_with(hub.pending["seq"], candidate_id) is None
    thread.join(5)


def test_a_combat_read_queued_behind_others_is_made_while_its_list_is_shown() -> None:
    gated = GatedAdvisor()
    hub = Hub(advisor=gated, real_action_stops=True)  # type: ignore[arg-type]
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    open_and_answer(hub, advised(priority(phase="precombat_main"), model_input([0, 1])), 0)  # the reader is held here
    result: list = []
    first = threading.Thread(target=lambda: result.append(hub.choose(advised(
        combat_substep("declare_attack", 0, 2, MULLDRIFTER, [None, FOE]), model_input([0, 1])))), daemon=True)
    first.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": ["o-m", "o-s"]}) is None
    first.join(5)
    hub.choose(advised(combat_substep("declare_attack", 1, 2, SEER, [None, FOE]), model_input([0, 1])))
    # a later decision of the same combat moves the read on: the attack's list is still shown
    open_and_answer(hub, advised(priority(phase="declare_attackers"), model_input([0, 1])), 0)
    gated.release.set()
    assert hub.wait_reads(10)
    items = hub.advice["declaration"]["items"]
    assert [("rows" in i, i.get("reading", False)) for i in items] == [(True, False), (True, False)]


def test_the_read_queue_stays_short_and_drops_what_is_no_longer_wanted() -> None:
    from spellbench.human.server import DROPPED_READ, READ_BACKLOG
    from test_human_stops import MANA
    gated = GatedAdvisor()
    hub = Hub(advisor=gated, real_action_stops=True)  # type: ignore[arg-type]
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    open_and_answer(hub, advised(priority(phase="precombat_main"), model_input([0, 1])), 0)  # the reader is held here
    count = READ_BACKLOG + 10
    first = threading.Thread(target=lambda: hub.choose(advised(
        combat_substep("declare_attack", 0, count, MULLDRIFTER, [None, FOE]), model_input([0, 1]))), daemon=True)
    first.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)
    assert hub.plan_with(hub.pending["seq"], {"kind": "attack", "attackers": []}) is None
    first.join(5)
    for index in range(1, count):
        hub.choose(advised(combat_substep("declare_attack", index, count, creature(f"o-{index}", f"Bear {index}"),
                                          [None, FOE]), model_input([0, 1])))
    assert hub._jobs.qsize() <= READ_BACKLOG  # never more waiting than that, and nothing blocked
    items = hub.advice["declaration"]["items"]
    assert sum(i.get("unavailable") == DROPPED_READ for i in items) == count - READ_BACKLOG
    passed = priority(phase="postcombat_main")
    passed["candidates"][1] = {"candidate_id": 1, "semantic": MANA, "display_text": None}
    hub.choose({"decision": passed})  # combat is over: its reads are no longer wanted
    open_and_answer(hub, advised(priority(phase="postcombat_main"), model_input([0, 1])), 0)
    assert hub._jobs.qsize() == 1  # the new read only: the combat's were pruned when it was queued
    gated.release.set()
    assert hub.wait_reads(10)


def test_the_declaration_ends_with_its_combat_even_when_every_later_window_is_passed_for_the_person(advisor) -> None:
    from test_human_stops import MANA
    hub = Hub(advisor=advisor("ok"), real_action_stops=True)
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    attack_with_plan(hub, ["o-m"])
    assert "declaration" in hub.advice
    rev = hub.advice.get("rev", 0)
    passed = priority(phase="declare_blockers")
    passed["candidates"][1] = {"candidate_id": 1, "semantic": MANA, "display_text": None}
    assert hub.choose({"decision": passed}) == 0  # answered for the person: still that combat, the list stays
    assert "declaration" in hub.advice
    passed = priority(phase="postcombat_main")
    passed["candidates"][1] = {"candidate_id": 1, "semantic": MANA, "display_text": None}
    assert hub.choose({"decision": passed}) == 0  # passed for the person too, after combat: the list is gone
    assert hub.declaration is None and "declaration" not in hub.advice and hub.advice["rev"] > rev


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
