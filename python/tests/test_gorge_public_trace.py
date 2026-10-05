"""The diagnostic preparer refuses changed pins, budgets and private inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gorge_public_trace", REPO / "python/tools/gorge_public_trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)
SOURCE = (REPO / "engines/gorge/native-overlay/public_redeal.go.txt").read_text(encoding="utf-8")


def projection():
    return {
        "names": ["actor", "opponent"], "decks": [["Forest"], ["Mountain"]],
        "starting_life": 20, "mulligans": 1,
        "history": {"ActorBoundaries": True, "Actor": 0,
                    "Frames": [{"Decision": {"Player": 0}}, {"Decision": {"Player": 0}}],
                    "Answers": {"0": {}}},
        "options": {"Attempts": 64, "Worlds": 8, "MaxSubmits": 5000,
                    "Redeal": {"SpellbenchPublic": True, "Engine": None, "Observer": None}},
        "public_reconstruction": {"Attempts": 1, "Submits": 5000, "Nodes": 4858, "BudgetExhausted": 1},
    }


def prepare(value, source=SOURCE):
    data = json.dumps(value).encode()
    return trace.prepare(data, hashlib.sha256(data).hexdigest(), source, "/workspace/gorge")


def test_changed_projection_pin_is_refused():
    data = json.dumps(projection()).encode()
    with pytest.raises(ValueError, match="SHA-256"):
        trace.prepare(data, "00" * 32, SOURCE, "/workspace/gorge")


@pytest.mark.parametrize("field,value", [("Attempts", 65), ("Worlds", 9), ("MaxSubmits", 5001)])
def test_a_correct_hash_does_not_admit_changed_sampler_budgets(field, value):
    fixture = projection()
    fixture["options"][field] = value
    with pytest.raises(ValueError, match="sampler budgets"):
        prepare(fixture)


@pytest.mark.parametrize("field", ["Engine", "Observer"])
def test_live_engine_and_observer_blobs_are_refused(field):
    fixture = projection()
    fixture["options"]["Redeal"][field] = {}
    with pytest.raises(ValueError, match="live engine or observer"):
        prepare(fixture)


def test_another_players_private_decision_is_refused():
    fixture = projection()
    fixture["history"]["Frames"][1]["Decision"]["Player"] = 1
    with pytest.raises(ValueError, match="private decision"):
        prepare(fixture)


def test_an_incomplete_actor_history_is_refused():
    fixture = projection()
    fixture["history"]["Answers"] = {}
    with pytest.raises(ValueError, match="previous actor answer"):
        prepare(fixture)


def test_changed_production_source_context_is_refused():
    with pytest.raises(ValueError, match="patch context changed"):
        prepare(projection(), SOURCE.replace("work.Attempts++", "work.Attempts += 1"))


def test_replay_capsule_pins_its_input_and_keeps_qualification_incomplete():
    capsule = prepare(projection())
    assert capsule["frames"] == 2
    assert capsule["projection_sha256"] in capsule["test_source"]
    assert capsule["expected_work"] == projection()["public_reconstruction"]
    assert "captured_work_identical" in capsule["test_source"]
    assert capsule["native_qualification_complete"] is False and capsule["rated_games"] == 0
    assert hashlib.sha256(capsule["logging_source"].encode()).hexdigest() == capsule["logging_source_sha256"]


def test_shuffle_logging_wraps_every_hypothetical_planner_without_new_sampling():
    source = trace.instrument(SOURCE, "/workspace/gorge", trace_shuffle_failures=True)
    assert "hypothetical_shuffle_proposal" in source
    assert "return order,err" in source
    assert "diagnosticPlanner(proposal)" in source and "diagnosticPlanner(&pp)" in source
    assert "spellbenchBasicSearchPlanner(proposal, basicSearches)" not in source
    assert "spellbenchBasicSearchPlanner(&pp, basicSearches)" not in source
    assert "plannerFrames[p]=frame" in source
    assert "rand.NewPCG(seed[0], seed[1])" in source
    assert "proposalLimit = min(opts.MaxSubmits" in source
    assert "BestShuffle" not in trace.instrument(SOURCE, "/workspace/gorge")


def test_shuffle_logging_rejects_changed_clone_planner_context():
    changed = SOURCE.replace("spellbenchBasicSearchPlanner(&pp, basicSearches)", "anotherPlanner(&pp)")
    with pytest.raises(ValueError, match="patch context changed"):
        trace.instrument(changed, "/workspace/gorge", trace_shuffle_failures=True)
