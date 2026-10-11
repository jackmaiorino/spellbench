"""Original arrangement plans preserve target order across fixed wire partitions."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_arrangement as arrangement
from xmage_neural_decisions import decision_hash
from xmage_neural_agent import NeuralAgent
from test_xmage_neural_agent import Session, game, decision, view, CHECKPOINT
from spellbench.bot import GameStart


def fixture(purpose="surveil", moved=("b",), top_order=("a",), count=2):
    names = ["a", "b", "c"][:count]
    known = [{"object_id": c, "card_name": "Island", "owner_seat": "p0", "zone": "library",
              "how": "looked_at", "position_from_top": i} for i, c in enumerate(names)]
    source = {"object_id": "source", "card_name": "Lightshell Duo", "owner_seat": "p0", "controller_seat": "p0", "zone": "stack"}
    refs = {c: {"object_id": c, "card_name": "Island", "owner_seat": "p0", "controller_seat": "p0", "zone": "library"} for c in names}
    away = "graveyard" if purpose == "surveil" else "bottom"
    d = decision(*[{"kind": "arrange_card", "purpose": purpose, "card": refs[names[0]],
                   "card_index": 0, "card_count": count, "destination": dest, "source": source} for dest in ("top", away)], step=1)
    d["context"].update(purpose=purpose, source=source)
    d["observation"].update(known=known)
    d["group"] = {"group_id": 8, "substep_count": 2 * count - 1, "substep_index": 0}
    dest = {c: away if c in moved else "top" for c in names}
    script = [{"stage": "partition", "possible": names, "minimum": 0, "maximum": count,
               "choices": list(moved) + ([None] if len(moved) < count else [])}]
    for stage, members, selected in (("bottom_order", list(moved) if purpose == "scry" else [], list(moved) if purpose == "scry" else []),
                                      ("top_order", [c for c in names if c not in moved], list(reversed(top_order)))):
        remaining = set(members)
        for pick in selected[:-1]:
            script.append({"stage": stage, "possible": sorted(remaining), "minimum": 1, "maximum": 1, "choices": [pick]})
            remaining.remove(pick)
    roots = []
    budget = {"kind": "minimum_root_visits_until_legal_future", "requested": 2}
    for frame in script:
        remaining, selected = set(frame["possible"]), 0
        for pick in frame["choices"]:
            options = remaining | ({None} if selected >= frame["minimum"] else set())
            if len(options) > 1:
                roots.append({"index": len(roots), "type": "CHOOSE_TARGET", "stage": frame["stage"], "selected": pick,
                              "requested_minimum": 2, "root_visits": 2, "neural_calls": 1, "search_budget": budget,
                              "children": [{"action": c, "visits": 2 if c == pick else 0, "value": 0.0}
                                           for c in sorted(options, key=str)]})
            if pick is not None:
                remaining.remove(pick)
                selected += 1
    value = {"decision_sha256": decision_hash(d), "arrangement": purpose, "cards": names, "destinations": dest,
             "order": list(top_order) + list(moved), "target_script": script, "roots": roots, "neural_calls": len(roots),
             "world_flags": [], "search_budget": budget, "replay": {"earlier": 0, "priority_passes": 1, "observation_identical": True}}
    return d, value, refs


def later(first, value, refs, step):
    d = copy.deepcopy(first)
    n = len(value["cards"])
    d["seat_step"] = first["seat_step"] + step
    d["group"]["substep_index"] = step
    if step < n:
        for candidate in d["candidates"]:
            candidate["semantic"].update(card=refs[value["cards"][step]], card_index=step)
    else:
        position = step - n
        wanted = value["order"][position]
        destination = value["destinations"][wanted]
        d["context"]["purpose"] = "arrangement"
        d["candidates"] = [{"candidate_id": 10 + i, "semantic": {"kind": "order_pick", "purpose": "arrangement",
                            "item": {"object": refs[c]}, "position": position, "count": n,
                            "source": first["context"]["source"]}}
                           for i, c in enumerate(value["order"][position:]) if value["destinations"][c] == destination]
    return d


@pytest.mark.parametrize("purpose,count,moved,top", [
    ("surveil", 1, (), ("a",)), ("surveil", 1, ("a",), ()),
    ("surveil", 2, ("b",), ("a",)), ("surveil", 2, ("b", "a"), ()),
    ("surveil", 2, (), ("a", "b")), ("scry", 3, ("b", "c"), ("a",)),
    ("scry", 3, (), ("c", "a", "b")), ("scry", 3, ("c", "b", "a"), ())])
def test_original_target_sequence_maps_to_complete_partition_and_placement_group(purpose, count, moved, top):
    d, value, refs = fixture(purpose, moved, top, count)
    plan = arrangement.ArrangementPlan(d, value, visits=2)
    for step in range(2 * count - 1):
        chosen = plan.select(later(d, value, refs, step))["semantic_echo"]
        if step < count:
            assert chosen["destination"] == value["destinations"][value["cards"][step]]
        else:
            assert chosen["item"]["object"]["object_id"] == value["order"][step-count]
    assert plan.complete
    assert plan.history()["target_script"] == value["target_script"]


@pytest.mark.parametrize("fault", ["hidden", "position", "work", "omitted-branch", "root-selection", "script-selection", "order", "partial"])
def test_changed_visibility_original_history_and_work_fail_closed(fault):
    d, value, _ = fixture()
    if fault == "hidden": d["observation"]["known"][0]["owner_seat"] = "p1"
    elif fault == "position": d["observation"]["known"][0]["position_from_top"] = 1
    elif fault == "work": value["neural_calls"] += 1
    elif fault == "omitted-branch": value["roots"][0]["children"].pop()
    elif fault == "root-selection": value["roots"][0]["selected"] = "a"
    elif fault == "script-selection": value["target_script"][0]["choices"][0] = "a"
    elif fault == "order": value["order"].reverse()
    else: value["target_script"][0]["choices"].pop()
    with pytest.raises(ValueError): arrangement.ArrangementPlan(d, value, visits=2)


@pytest.mark.parametrize("fault", ["group", "skip", "source", "observation", "missing-option", "rewind"])
def test_retained_group_rejects_changed_or_skipped_wire_decisions(fault):
    d, value, refs = fixture()
    plan = arrangement.ArrangementPlan(d, value, visits=2)
    plan.select(d)
    next_d = later(d, value, refs, 1)
    if fault == "group": next_d["group"]["group_id"] += 1
    elif fault == "skip": next_d["seat_step"] += 1
    elif fault == "source": next_d["context"]["source"]["object_id"] = "changed"
    elif fault == "observation": next_d["observation"]["turn"] += 1
    elif fault == "missing-option": next_d["candidates"].pop()
    else: next_d["context"]["rewind"] = True
    with pytest.raises(ValueError): plan.select(next_d)
    assert plan.failed


def test_frontend_searches_once_and_retains_original_history_for_later_callback_replay():
    d, value, refs = fixture()
    class ArrangingSession(Session):
        def arrange(self, record, *, visits, timeout_s):
            self.requests.append((copy.deepcopy(record), visits, timeout_s))
            current = copy.deepcopy(value)
            current.update(decision_sha256=decision_hash(record["decision"]), checkpoint=CHECKPOINT)
            return current
    session = ArrangingSession([0])
    bot = NeuralAgent(lambda: session, checkpoint=CHECKPOINT, visits=2, arrangement_factory=arrangement.ArrangementPlan)
    bot.on_game_start(GameStart.from_request(game()))
    anchor = decision({"kind": "pass"}, stack=[{"object_id": "source", "stack_kind": "spell"}])
    bot.choose(view(anchor))
    for step in range(3):
        bot.choose(view(later(d, value, refs, step)))
    assert len(session.requests) == 1
    assert len(bot.history.earlier) == 3
    assert bot.history.earlier[0]["decision"]["x_arrangement_plan"]["target_script"] == value["target_script"]
    assert all("x_arrangement_plan" not in entry["decision"] for entry in bot.history.earlier[1:])
    bot.close()
