"""Returned contract halts keep their error text in stderr, outside the protocol."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_engine_v2 import KernelEngine, ProjectionError
from kernel_observation_v2 import KernelProjection
from test_kernel_observation_v2 import catalog


@pytest.mark.parametrize("phase", ["step", "projection"])
def test_contract_error_is_diagnostic_only(phase, capsys):
    engine = KernelEngine.__new__(KernelEngine)
    engine.game = "game"
    engine.provenance = {}
    engine.answered = engine.completed = 0
    engine.max_steps = engine.max_groups = 100
    engine.current = {"response_type": "decision"}
    engine.seat_steps = {"p0": 0}
    engine.group_ids = {"p0": 0}
    engine.buffer = None
    engine.native_candidates = [0]
    engine.pending = {"seat_decision": {"candidates": [{"semantic": {}}], "acting_seat": "p0",
                      "group": {"substep_index": 0, "substep_count": 1}}}

    def fail(*args):
        raise ProjectionError("controlled private diagnostic")

    engine.native_step = engine.pose = fail
    if phase == "step":
        answer = engine.step({"request_id": "id", "game_id": "game", "expected_step": 0,
                              "selection": {"candidate_id": 0, "semantic_echo": {}}})
    else:
        answer = engine.respond("id")
    assert answer["reason"] == "engine_contract_failure:ProjectionError"
    assert "controlled private diagnostic" not in str(answer)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ProjectionError: controlled private diagnostic" in captured.err


@pytest.mark.parametrize("failure, suffix", [
    ("invalid pending trigger announcement", ": invalid pending trigger announcement"),
    ("invalid pending trigger announcement\nprivate-card=SECRET", ""),
    ({"private-card": "SECRET"}, ""),
    (["SECRET"], ""),
    (True, ""),
])
def test_native_projection_classification_stays_out_of_primary_halt(failure, suffix, capsys):
    engine = KernelEngine.__new__(KernelEngine)
    engine.game = "game"
    engine.provenance = {}
    engine.answered = engine.completed = 0
    engine.max_steps = engine.max_groups = 100
    engine.current = {"response_type": "decision"}
    projection = KernelProjection(catalog(), b"s" * 32)

    def pose(_request_id):
        # The native failure is rejected before any private raw state is read.
        return projection.project({}, {"projection_error": failure})

    engine.pose = pose
    answer = engine.respond("id")
    assert answer["reason"] == "engine_contract_failure:ProjectionError"
    assert "native private" not in str(answer)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "kernel_engine_v2: ProjectionError: native private projection validation failed" + suffix + "\n"
    assert "SECRET" not in captured.err
