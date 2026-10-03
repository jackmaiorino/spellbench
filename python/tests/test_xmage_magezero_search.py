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
