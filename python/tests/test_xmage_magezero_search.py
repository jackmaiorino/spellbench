"""Original MageZero settings, stopping rules and architecture stay bound."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_magezero_search as search
from spellbench import wire
from xmage_neural_decisions import decision_hash
from test_xmage_neural_search import fixture as original_fixture


def fixture(settings=None):
    record, result = original_fixture()
    record["game_start"]["seat"] = "p0"
    record["decision"].update(acting_seat="p0", observation={"viewer": "p0"})
    record["decision"]["context"]["rewind"] = False
    settings = copy.deepcopy(settings or search.diagnostic_settings(2))
    result.update(decision_sha256=decision_hash(record["decision"]), settings=copy.deepcopy(settings),
                  policy_width=128, search_budget=search.budget(settings))
    return record, result, settings


class Peer:
    def __init__(self, messages):
        self.messages = iter([search.READY, *messages])
        self.writes, self.closed = [], False
    def read_line(self):
        return json.dumps(next(self.messages)).encode()
    def write_line(self, value):
        self.writes.append(json.loads(value))
    def set_timeout(self, value):
        assert value > 0
    def close(self):
        self.closed = True


class Model:
    architecture, checkpoint = "magezero-v02", "author-supplied-pinned-model"
    def __init__(self):
        self.closed, self.calls = False, []
    def score(self, features, *, timeout_s):
        self.calls.append(features)
        return {"priority": [0.0]*128, "opponent_priority": [0.0]*128,
                "target": [0.0]*128, "binary": [0.0, 0.0], "value": 0.2}
    def close(self):
        self.closed = True


def test_original_time_stopping_can_return_below_visit_budget_without_changing_head_flags():
    record, result, settings = fixture(search.ORIGINAL_DEFAULT_SETTINGS)
    assert result["root_visits"] < settings["searchBudget"]
    request = search.search_request(record, settings)
    wire.canonical_json_dumps(request)
    assert all(request["settings"][flag] for flag in ("noPolicyPriority", "noPolicyOpponent", "noPolicyTarget", "noPolicyUse"))
    assert search.search_result(record, result, settings, 1) is result
    with pytest.raises(ValueError, match="explicit settings"):
        search.search_result(record, result, search.diagnostic_settings(1000), 1)


def test_real_private_exchange_preserves_full_integer_feature_range_and_128_slot_heads():
    record, result, settings = fixture()
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "features": [2000001, 2147483646]},
                 {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    selected = session.choose(record, settings=settings, timeout_s=3)
    assert selected["checkpoint"] == model.checkpoint and selected["selection"]["candidate_id"] == 3
    assert model.calls == [[2000001, 2147483646]]
    assert peer.writes[0]["settings"] == settings and "visits" not in peer.writes[0]
    assert len(peer.writes[1]["scores"]["priority"]) == 128
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("fault", ["missing", "extra", "float", "nonfinite", "bool-budget", "noise",
                                  "temperature", "wrong-profile", "diagnostic-head", "diagnostic-prior", "zero-timeout"])
def test_explicit_settings_refuse_implicit_defaults_or_silent_profile_changes(fault):
    settings = search.diagnostic_settings(6)
    if fault == "missing": settings.pop("noPolicyTarget")
    elif fault == "extra": settings["fallback"] = True
    elif fault == "float": settings["searchTimeout"] = 4.0
    elif fault == "nonfinite": settings["priorTemp"] = "NaN"
    elif fault == "bool-budget": settings["searchBudget"] = True
    elif fault == "noise": settings["noNoise"] = False
    elif fault == "temperature": settings["selectionTemperature"] = "1"
    elif fault == "wrong-profile": settings["profile"] = "guess-original-settings"
    elif fault == "diagnostic-head": settings["noPolicyTarget"] = True
    elif fault == "diagnostic-prior": settings["priorBonus"] = "2"
    elif fault == "zero-timeout": settings["searchTimeout"] = "0"
    with pytest.raises(ValueError):
        search.validate_settings(settings)


@pytest.mark.parametrize("fault", ["callback", "wrong-viewer", "wrong-seat", "rewind", "stale-result",
                                  "wrong-width", "partial", "wrong-profile", "integer-flag", "no-neural-call"])
def test_unbound_decisions_results_or_work_close_both_owned_sessions(fault):
    record, result, settings = fixture()
    if fault == "callback": record["decision"]["context"]["kind"] = "choice"
    elif fault == "wrong-viewer": record["decision"]["observation"]["viewer"] = "p1"
    elif fault == "wrong-seat": record["game_start"]["seat"] = "p1"
    elif fault == "rewind": record["decision"]["context"]["rewind"] = True
    elif fault == "stale-result": result["decision_sha256"] = "c"*64
    elif fault == "wrong-width": result["policy_width"] = 1024
    elif fault == "partial": result["root_visits"] = 1
    elif fault == "wrong-profile": result["settings"]["noPolicyTarget"] = True
    elif fault == "integer-flag": result["settings"]["noNoise"] = 1
    elif fault == "no-neural-call": result["neural_calls"] = 0
    messages = [] if fault == "no-neural-call" else [{"id": "1", "event": "infer", "call": 1, "features": [1]}]
    peer = Peer([*messages, {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    with pytest.raises(ValueError):
        session.choose(record, settings=settings, timeout_s=3)
    assert session.failed and peer.closed and model.closed


def test_exp1_checkpoint_is_refused_before_any_search_request():
    peer, model = Peer([]), Model()
    model.architecture = "draftzero-exp1"
    with pytest.raises(ValueError, match="128-slot checkpoint"):
        search.SearchSession(peer, model)
    assert peer.closed and model.closed and peer.writes == []


def callback_fixture(family, *, source_settings=False):
    record, result, settings = fixture(search.ORIGINAL_DEFAULT_SETTINGS if source_settings else None)
    anchor = {"decision": copy.deepcopy(record["decision"]), "selection": copy.deepcopy(result["selection"])}
    source = {"object_id": "permitted-callback-source"}
    semantics = {
        "target": [{"kind": "choose_target", "target": {"object_id": name}, "source": source}
                   for name in ("visible-creature-a", "visible-creature-b")],
        "binary": [{"kind": "choose_boolean", "value": value, "source": source} for value in (False, True)],
        "numeric": [{"kind": "choose_number", "minimum": 1, "maximum": 2, "value": value, "source": source}
                    for value in (1, 2)],
        "named": [{"kind": "choose_color", "color": color} for color in ("red", "blue")],
        "mode": [{"kind": "choose_spell_mode", "mode_index": index, "mode_count": 2, "source": source}
                 for index in (0, 1)],
    }[family]
    decision = record["decision"]
    decision["context"] = {"kind": "choice", "rewind": False}
    for candidate, semantic in zip(decision["candidates"], semantics):
        candidate["semantic"] = semantic
    record.update(anchor=anchor, replay={"priority_passes": ["p1", "p0"], "earlier": []})
    result.update(decision_sha256=decision_hash(decision),
                  selection={"candidate_id": 3, "semantic_echo": copy.deepcopy(semantics[1])},
                  children=[{"semantic": copy.deepcopy(c["semantic"]), "visits": 2 if c["candidate_id"] == 3 else 0,
                             "value": 0.2} for c in decision["candidates"]],
                  replay={"earlier": 0, "priority_passes": 2, "observation_identical": True})
    return record, result, settings


@pytest.mark.parametrize("family", ["target", "binary", "numeric", "named", "mode"])
def test_private_callback_exchange_binds_the_public_anchor_and_explicit_source_settings(family):
    record, result, settings = callback_fixture(family, source_settings=True)
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "features": [2147483646]},
                 {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    chosen = session.choose(record, settings=settings, timeout_s=3)
    assert chosen["selection"]["semantic_echo"] == record["decision"]["candidates"][1]["semantic"]
    assert peer.writes[0]["anchor"] == record["anchor"] and peer.writes[0]["replay"] == record["replay"]
    assert peer.writes[0]["settings"] == settings and result["root_visits"] < settings["searchBudget"]
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("fault", ["missing-anchor", "missing-history", "incomplete-prefix", "missing-passes",
                                  "false-observation", "integer-confirmation"])
def test_callback_failure_poisoning_refuses_missing_or_unconfirmed_public_replay(fault):
    record, result, settings = callback_fixture("target")
    if fault == "missing-anchor": record.pop("anchor")
    elif fault == "missing-history": record.pop("replay")
    elif fault == "incomplete-prefix": record["replay"]["earlier"].append(copy.deepcopy(record["anchor"]))
    elif fault == "missing-passes": result["replay"]["priority_passes"] = 0
    elif fault == "false-observation": result["replay"]["observation_identical"] = False
    elif fault == "integer-confirmation": result["replay"]["observation_identical"] = 1
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "features": [1]},
                 {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    with pytest.raises(ValueError, match="anchor|replay"):
        session.choose(record, settings=settings, timeout_s=3)
    assert session.failed and peer.closed and model.closed
    if fault in ("missing-anchor", "missing-history"):
        assert model.calls == [] and peer.writes == []


def test_library_fail_to_find_preserves_the_original_magezero_restriction_and_work_accounting():
    record, result, settings = callback_fixture("target")
    decision = record["decision"]
    decision["context"]["purpose"] = "search"
    decision["candidates"][0]["semantic"] = {"kind": "finish_selection", "purpose": "search"}
    result["children"][0] = {
        "semantic": decision["candidates"][0]["semantic"], "visits": 0, "value": None,
        "excluded": True, "pruned": False,
        "reason": "original MageZero library target expansion requires its minimum before finishing",
    }
    result.update(decision_sha256=decision_hash(decision), policy_restrictions=["library_fail_to_find_before_minimum"])
    assert search.search_result(record, result, settings, 1) is result
    result["children"][0]["reason"] = "original Exp1 library target expansion requires its minimum before finishing"
    with pytest.raises(ValueError, match="original policy restriction"):
        search.search_result(record, result, settings, 1)
