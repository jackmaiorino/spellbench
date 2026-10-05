"""Original combat plans stay bound to one public declaration group."""
import copy
import pytest
from test_xmage_jack_native_agent import ready, priority
from test_xmage_neural_combat import fixture, later_decision
from test_xmage_neural_agent import view
import xmage_jack_native_agent as agent


def prepared(family):
    bot, session = ready([1])
    record, plan = fixture(family)
    d = record["decision"]
    d["seat_step"] = 0
    d["context"]["kind"] = "choice"
    if family == "block":
        d["acting_seat"] = d["observation"]["viewer"] = "p0"
        for player in d["observation"]["players"]:
            player["seat"] = "p0" if player["seat"] == "p1" else "p1"
            for obj in player["battlefield"]:
                obj["controller_seat"] = "p0" if obj["controller_seat"] == "p1" else "p1"
    original = session.choose
    def choose(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        if agent.family(record["decision"]) in ("attack", "block"):
            result.update(original_combat_path=True, combat=family, pairs=copy.deepcopy(plan["pairs"]))
        return result
    session.choose = choose
    return bot, session, d


@pytest.mark.parametrize("family", ["attack", "block"])
def test_actual_plan_is_rebound_without_another_session_call(family):
    bot, session, d = prepared(family)
    assert bot.choose(view(d)) == 7
    later = later_decision({"decision": d}, family)
    assert bot.choose(view(later)) == 19
    assert bot.combat is None and len(session.requests) == 1 and bot.history.anchor is None
    session.indices = iter([0])
    bot.choose(view(priority(2)))
    assert len(session.requests) == 2
    bot.close()


@pytest.mark.parametrize("family", ["attack", "block"])
@pytest.mark.parametrize("fault", ["group", "observation", "skip", "interrupted", "repeat"])
def test_changed_group_closes_without_more_model_work(family, fault):
    bot, session, d = prepared(family)
    bot.choose(view(d))
    later = later_decision({"decision": d}, family)
    if fault == "group": later["group"]["group_id"] += 1
    if fault == "observation": later["observation"]["players"][0]["life"] = 19
    if fault == "skip": later["seat_step"] += 1
    if fault == "interrupted": later = priority(1)
    if fault == "repeat":
        for candidate in later["candidates"]:
            candidate["semantic"]["attacker" if family == "attack" else "blocker"]["object_id"] = "own-1"
    with pytest.raises(ValueError): bot.choose(view(later))
    assert session.closed and len(session.requests) == 1


@pytest.mark.parametrize("fault", ["duplicate", "opposing", "hidden", "path", "family", "first"])
def test_bad_plan_refuses_instead_of_substituting_a_declaration(fault):
    bot, session, d = prepared("attack")
    original = session.choose
    def bad(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        if fault == "duplicate": result["pairs"].append(copy.deepcopy(result["pairs"][0]))
        if fault == "opposing": result["pairs"][0]["attacker"] = "other-1"
        if fault == "hidden": result["pairs"][0]["defender"] = {"object_id": "hidden"}
        if fault == "path": result["original_combat_path"] = False
        if fault == "family": result["combat"] = "block"
        if fault == "first": result["pairs"] = []
        return result
    session.choose = bad
    with pytest.raises(ValueError): bot.choose(view(d))
    assert session.closed and len(session.requests) == 1
