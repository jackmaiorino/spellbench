"""Bind one original bottom sequence to unchanged public group substeps."""
import copy

import pytest

from test_xmage_jack_native_agent import ready, priority
from test_xmage_jack_london import fixture
from test_xmage_neural_agent import view
import xmage_jack_native_agent as agent


def prepared(count=3):
    bot, session = ready([1])
    _, received, *_ = fixture(count)
    received["seat_step"] = 0
    received["observation"]["players"][0]["mulligans_taken"] = received["group"]["substep_count"]
    original = session.choose

    def choose(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        if agent.family(record["decision"]) != "london":
            return result
        selected = result["selection"]["semantic_echo"]["item"]["object"]["object_id"]
        refs = [c["semantic"]["item"]["object"]["object_id"] for c in received["candidates"]]
        result.update(original_london_path=True, london_plan={"group_id": 88,
            "count": received["group"]["substep_count"], "bottomed": [selected] + [r for r in reversed(refs) if r != selected][:received["group"]["substep_count"]-1]})
        return result

    session.choose = choose
    return bot, session, received


def later(received, picked):
    current = copy.deepcopy(received)
    current["seat_step"] += 1
    current["group"]["substep_index"] = 1
    current["candidates"] = [c for c in reversed(current["candidates"]) if c["candidate_id"] != picked]
    for c in current["candidates"]:
        c["candidate_id"] += 100
        c["semantic"]["position"] = 1
    return current


def test_original_full_sequence_rebinds_reordered_candidates_without_another_session_call():
    bot, session, received = prepared()
    assert bot.choose(view(received)) == 21
    assert agent.family(received) == "london" and len(session.requests) == 1
    next_ = later(received, 21)
    assert bot.choose(view(next_)) == 122
    assert bot.london is None and len(session.requests) == 1 and bot.history.anchor is None
    # London completes without creating an activation prefix or changing its model session.
    session.indices = iter([0])
    bot.choose(view(priority(2)))
    assert len(session.requests) == 2 and "anchor" not in session.requests[-1][0]
    bot.close()


@pytest.mark.parametrize("fault", ["group", "count", "observation", "remaining", "position", "interrupted"])
def test_changed_bottom_substep_refuses_before_another_model_call(fault):
    bot, session, received = prepared()
    bot.choose(view(received))
    next_ = later(received, 21)
    if fault == "group": next_["group"]["group_id"] += 1
    if fault == "count": next_["group"]["substep_count"] = 3
    if fault == "observation": next_["observation"]["players"][0]["life"] = 19
    if fault == "remaining": next_["candidates"][0]["semantic"]["item"]["object"] = received["candidates"][1]["semantic"]["item"]["object"]
    if fault == "position": next_["candidates"][0]["semantic"]["position"] = 0
    if fault == "interrupted": next_ = priority(1)
    with pytest.raises(ValueError): bot.choose(view(next_))
    assert session.closed and len(session.requests) == 1


@pytest.mark.parametrize("fault", ["repeat", "hidden", "short", "foreign-group", "first", "false-path"])
def test_bad_original_plan_closes_the_owned_session(fault):
    bot, session, received = prepared()
    original = session.choose
    def bad(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        plan = result["london_plan"]
        if fault == "repeat": plan["bottomed"][1] = plan["bottomed"][0]
        if fault == "hidden": plan["bottomed"][1] = "unknown-hidden"
        if fault == "short": plan["bottomed"].pop()
        if fault == "foreign-group": plan["group_id"] = 99
        if fault == "first": plan["bottomed"].reverse()
        if fault == "false-path": result["original_london_path"] = False
        return result
    session.choose = bad
    with pytest.raises(ValueError): bot.choose(view(received))
    assert session.closed and len(session.requests) == 1


@pytest.mark.parametrize("fault", ["initial-position", "counter", "hidden-menu", "missing-menu"])
def test_invalid_first_group_refuses_before_session_use(fault):
    bot, session, received = prepared()
    if fault == "initial-position":
        received = later(received, 21)
        received["seat_step"] = 0
    if fault == "counter": received["observation"]["players"][0]["mulligans_taken"] = 1
    if fault == "hidden-menu": received["candidates"][0]["semantic"]["item"]["object"]["card_name"] = "unknown"
    if fault == "missing-menu": received["candidates"].pop()
    with pytest.raises(ValueError): bot.choose(view(received))
    assert session.closed and not session.requests
