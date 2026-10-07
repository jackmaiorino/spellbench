"""Original combat plans stay bound to one public declaration group."""
import copy
import pytest
from test_xmage_maintainer_native_agent import ready, priority
from test_xmage_neural_combat import fixture, later_decision
from test_xmage_neural_agent import view
import xmage_maintainer_native_agent as agent


def prepared(family, slots=None):
    bot, session = ready([1])
    record, plan = fixture(family)
    d = record["decision"]
    d["seat_step"] = 0
    d["context"]["kind"] = "choice"
    slots = ["own-1", "own-2"] if slots is None else slots
    d["group"]["substep_count"] = len(slots)
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
            result.update(original_combat_path=True, combat=family, pairs=copy.deepcopy(plan["pairs"]),
                          combat_slots=copy.deepcopy(slots))
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


def block_slot(d, index, oid, *, rendered=False):
    later = copy.deepcopy(d)
    later["seat_step"] = index
    later["group"]["substep_index"] = index
    for candidate in later["candidates"]:
        candidate["semantic"]["blocker"]["object_id"] = oid
    if rendered:
        obj = later["observation"]["players"][0]["battlefield"][0]
        obj["permanent"].update(blocking=True, blocked_attackers=[{"object_id": "other-1"}])
    return later


@pytest.mark.parametrize("rendered", [False, True])
@pytest.mark.parametrize("assigned", [False, True])
def test_additional_block_slots_decline_without_changing_original_assignment(rendered, assigned):
    bot, session, d = prepared("block", ["own-1", "own-1", "own-1", "own-2"])
    if not assigned:
        session.indices = iter([0])
        original = session.choose
        def decline(record, *, timeout_s):
            result = original(record, timeout_s=timeout_s)
            result["pairs"] = []
            return result
        session.choose = decline
    assert bot.choose(view(d)) == (7 if assigned else 19)
    for index in (1, 2):
        later = block_slot(d, index, "own-1", rendered=rendered and assigned)
        assert bot.choose(view(later)) == 19
        assert bot.combat.picks["own-1"] == ("other-1" if assigned else None)
    last = block_slot(d, 3, "own-2", rendered=rendered and assigned)
    assert bot.choose(view(last)) == 19
    assert bot.combat is None and len(session.requests) == 1 and bot.history.anchor is None
    bot.close()


@pytest.mark.parametrize("fault", ["missing", "length", "hidden", "opposing", "noncontiguous", "plan-creature"])
def test_slot_schedule_must_bind_every_plan_creature_and_engine_substep(fault):
    slots = ["own-1", "own-1", "own-2"]
    bot, session, d = prepared("block", slots)
    original = session.choose
    def bad(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        if fault == "missing": result.pop("combat_slots")
        if fault == "length": result["combat_slots"].pop()
        if fault == "hidden": result["combat_slots"][1] = "hidden"
        if fault == "opposing": result["combat_slots"][1] = "other-1"
        if fault == "noncontiguous": result["combat_slots"] = ["own-1", "own-2", "own-1"]
        if fault == "plan-creature": result["combat_slots"] = ["own-2"] * 3
        return result
    session.choose = bad
    with pytest.raises(ValueError): bot.choose(view(d))
    assert session.closed and len(session.requests) == 1


def test_attacker_cannot_gain_an_extra_slot():
    bot, session, d = prepared("attack", ["own-1", "own-1"])
    with pytest.raises(ValueError, match="slot schedule revisits"): bot.choose(view(d))
    assert session.closed and len(session.requests) == 1


@pytest.mark.parametrize("fault", ["no-decline", "aliased-decline", "changed-creature", "changed-block"])
def test_extra_block_slots_refuse_unoffered_or_changed_declarations(fault):
    bot, session, d = prepared("block", ["own-1", "own-1", "own-2"])
    bot.choose(view(d))
    later = block_slot(d, 1, "own-1", rendered=True)
    if fault == "no-decline": later["candidates"] = later["candidates"][1:]
    if fault == "aliased-decline":
        duplicate = copy.deepcopy(later["candidates"][0]); duplicate["candidate_id"] += 100
        later["candidates"].append(duplicate)
    if fault == "changed-creature":
        for candidate in later["candidates"]: candidate["semantic"]["blocker"]["object_id"] = "own-2"
    if fault == "changed-block": later["observation"]["players"][0]["battlefield"][0]["permanent"]["blocked_attackers"] = []
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
