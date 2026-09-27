"""The live validator: V1 to V10 in rule order, with its counters (spec 11.3)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from spellbench.host.engine_process import EngineProcess
from spellbench.host.validator import LiveValidator
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import Decision, EnvHelloOk, Provenance, ResetRequest, Rules, Terminal

from test_messages import HELLO_OK, PROVENANCE, RESET, RULES, TERMINAL
from v2_sample_semantics import SAMPLES, seat_decision

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"


def _validator() -> LiveValidator:
    return LiveValidator(EnvHelloOk.from_json(copy.deepcopy(HELLO_OK)), Rules.from_json(RULES))


def _decision(sd: dict, *, step: int = 0, provenance: dict = PROVENANCE) -> Decision:
    return Decision(request_id=f"h-{step + 2}", game_id="g-1", step=step, seat_decision=sd, provenance=Provenance(**provenance))


def _rule(validator: LiveValidator, sd: dict, **kwargs) -> str:
    with pytest.raises(ValidatorViolation) as caught:
        validator.check(_decision(sd, **kwargs))
    return caught.value.rule


def test_a_fake_engine_game_passes_and_the_counts_match_its_terminal() -> None:
    engine = EngineProcess([sys.executable, str(ENGINE)], timeout_s=30)
    try:
        validator = LiveValidator(engine.hello(), Rules.from_json(RULES))
        response = engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))
        while isinstance(response, Decision):
            sd = validator.check(response)
            validator.answered(sd, 0)
            response = engine.step(candidate_id=0, semantic=sd["candidates"][0]["semantic"])
        validator.check_terminal(response)
    finally:
        engine.close()
    assert validator.decisions_checked == validator.answered_steps == response.result.step_count == 4
    assert validator.completed_groups == response.result.decision_count
    assert (validator.answered_by("p0"), validator.answered_by("p1")) == (2, 2)


@pytest.mark.parametrize(
    "sd",
    [
        seat_decision([SAMPLES["pass"], SAMPLES["pass"]]),                                       # duplicate semantics
        seat_decision([SAMPLES["play_land"], SAMPLES["pass"]]),                                  # pass not first
        {**seat_decision(), "x_extra": 1},                                                       # unknown field
        seat_decision(extensions={"kernel": {}}),                                                # not an x_ key
        seat_decision([{"kind": "pay_mana"}]),                                                    # a reserved kind
        seat_decision([{**SAMPLES["choose_name"], "source": None, "value": "Black Lotus"}], kind="choice"),  # outside the domain
    ],
)
def test_v1_schema(sd: dict) -> None:
    assert _rule(_validator(), sd) == "V1"


def test_v1_dense_ids_and_the_4096_cap() -> None:
    sparse = seat_decision()
    sparse["candidates"][1]["candidate_id"] = 5
    assert _rule(_validator(), sparse) == "V1"
    many = [{**SAMPLES["choose_number"], "source": None, "value": value, "minimum": 0, "maximum": 4096} for value in range(4097)]
    assert _rule(_validator(), seat_decision(many, kind="choice")) == "V1"


@pytest.mark.parametrize(
    ("mutate", "rule"),
    [
        (lambda sd: sd.update(acting_seat="p1"), "V2"),
        (lambda sd: sd.update(seat_step=3), "V3"),
        (lambda sd: sd["candidates"][2]["semantic"]["source"].update(card_name="Chain Lightning"), "V4"),
        (lambda sd: sd["observation"]["players"][1].update(hand=[]), "V5"),
        (lambda sd: sd["observation"]["players"][1]["battlefield"][0].update(face_down=True), "V6"),
        (lambda sd: sd["observation"]["players"][0].update(poison=0), "V8"),
        (lambda sd: sd["context"].update(kind="choice"), "V9"),
        (lambda sd: (sd.update(acting_seat="p1"), sd["candidates"][2]["semantic"]["source"].update(card_name="x")), "V2"),
    ],
)
def test_each_rule_is_reported_and_the_lowest_wins(mutate, rule: str) -> None:
    sd = seat_decision()
    mutate(sd)
    assert _rule(_validator(), sd) == rule


def test_v7_across_decisions_and_v10_provenance() -> None:
    validator = _validator()
    first = seat_decision()
    validator.check(_decision(first))
    validator.answered(first, 0)
    second = seat_decision([SAMPLES["pass"]])
    second.update(seat_step=1, group={"group_id": 1, "substep_index": 0, "substep_count": 1})
    player = second["observation"]["players"][0]
    bolt = player["hand"].pop(0)
    player["graveyard"].append({**bolt, "zone": "graveyard"})     # the same id in a new zone
    player["hand_count"] = 1
    assert _rule(validator, second, step=1) == "V7"
    assert _rule(_validator(), seat_decision(), provenance={**PROVENANCE, "engine_version": "9.9.9"}) == "V10"


def test_v7_flags_an_id_that_returns_after_leaving_through_a_hidden_zone() -> None:
    """An id that leaves the observation (here as if drawn into a hidden zone) never comes back (spec 5.3).

    V4 alone cannot catch this: the third decision's own references all match its own
    observation record field for field. Only V7's cross-decision history (host.tracking.IdTracker)
    catches the reuse, so this checks that LiveValidator actually wires V7 across decisions.
    """
    validator = _validator()
    first = seat_decision([SAMPLES["pass"]])
    validator.check(_decision(first))
    validator.answered(first, 0)

    second = seat_decision([SAMPLES["pass"]])
    second.update(seat_step=1, group={"group_id": 1, "substep_index": 0, "substep_count": 1})
    player = second["observation"]["players"][0]
    player["hand"].pop(0)                                         # Lightning Bolt leaves to a hidden zone
    player["hand_count"] = 1
    validator.check(_decision(second, step=1))
    validator.answered(second, 0)

    third = seat_decision([SAMPLES["pass"]])                      # the unmodified sample: Lightning Bolt's id is back
    third.update(seat_step=2, group={"group_id": 2, "substep_index": 0, "substep_count": 1})
    assert _rule(validator, third, step=2) == "V7"


def test_v1_a_library_search_may_find_nothing() -> None:
    search = {**SAMPLES["select_object"], "purpose": "search", "minimum": 1}
    assert _rule(_validator(), seat_decision([search], kind="choice")) == "V1"            # spec 7.5, F3 (R2-7)


MULLIGAN = {**SAMPLES["mulligan"], "hand_size": 2, "mulligans_taken": 0}                  # the example viewer: 2 cards, 0 taken


@pytest.mark.parametrize(
    ("candidates", "rule"),
    [
        ([SAMPLES["choose_starting_player"]], "V1"),                                        # only one seat offered
        ([{**MULLIGAN, "keep": False}], "V1"),                                              # no keep: true
        ([{**MULLIGAN, "hand_size": 7}], "V1"),                                             # not the viewer's hand_count
        ([{**MULLIGAN, "mulligans_taken": 1}], "V1"),                                       # not the viewer's mulligans_taken
        ([{**SAMPLES["choose_starting_player"], "player": "p0"}, SAMPLES["choose_starting_player"]], "V8"),  # past V1
        ([MULLIGAN, {**MULLIGAN, "keep": False}], "V8"),                                    # past V1; the hello lacks the kind
    ],
)
def test_v1_starting_player_and_mulligan_shapes(candidates: list, rule: str) -> None:
    assert _rule(_validator(), seat_decision(candidates, kind="choice")) == rule            # R2-25


@pytest.mark.parametrize(
    ("semantics", "kind", "count"),
    [
        ([SAMPLES["arrange_card"]], "choice", 2),                  # scry 2 is 2 x 2 - 1 = 3 decisions
        ([SAMPLES["finish_selection"]], "choice", 2),              # a finish candidate ends a one-decision group
        ([SAMPLES["pass"], SAMPLES["play_land"]], "priority", 2),  # a priority decision is never decomposed
    ],
)
def test_v3_group_shapes(semantics: list, kind: str, count: int) -> None:
    sd = seat_decision(semantics, kind=kind)
    sd["group"]["substep_count"] = count
    assert _rule(_validator(), sd) == "V3"                                                   # R2-7


def test_a_check_that_breaks_on_bad_input_reports_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("spellbench.host.validator.check_hidden_zones", lambda sd: [][0])   # an IndexError, not a violation
    assert _rule(_validator(), seat_decision()) == "V1"                                     # R1-8


def test_only_a_halted_or_truncated_terminal_may_interrupt_a_group() -> None:
    validator = _validator()
    attack = seat_decision([SAMPLES["declare_attack"]], kind="choice")
    attack["group"]["substep_count"] = 2                                                      # the first of two attackers
    validator.check(_decision(attack))
    validator.answered(attack, 0)
    with pytest.raises(ValidatorViolation) as caught:
        validator.check_terminal(Terminal.from_json({**TERMINAL, "step_count": 1, "decision_count": 0}))
    assert caught.value.rule == "V3"                                                          # R1-12
    validator.check_terminal(Terminal.from_json({**TERMINAL, "outcome": "truncated", "classification": "truncated",
                                                 "winner": None, "reason": "max_steps", "step_count": 1,
                                                 "decision_count": 0}))                       # a cap may (Decision 13)
