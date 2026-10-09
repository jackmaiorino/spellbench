"""Recorded replay keeps full public semantics, independently of a clock-reading policy."""
import copy
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_neural_game_check import CapturePeer, RecordedDriver


def traffic():
    return [{"event": "game_start", "payload": {"game_id": "game"}},
            {"event": "choose", "payload": {"game_id": "game", "clock": {"remaining_ms": 20, "max_decision_ms": 10},
                                               "decision": {"observation": {"hand": ["A"]}, "candidates": [0, 1]}}},
            {"event": "choice", "candidate_id": 1},
            {"event": "game_over", "payload": {"winner": "p0"}}]


def test_recorded_driver_matches_complete_public_semantics_and_consumes_all():
    rows = traffic(); driver = RecordedDriver(rows)
    driver.start(rows[0]["payload"], timeout_s=1)
    actual = copy.deepcopy(rows[1]["payload"]); actual["clock"]["remaining_ms"] = 100
    assert driver.choose(actual, timeout_s=1).candidate_id == 1
    driver.game_over(rows[3]["payload"], timeout_s=1)
    driver.finish()


@pytest.mark.parametrize("change", ["observation", "candidates", "max_clock", "game_id"])
def test_recorded_replay_refuses_changed_semantics(change):
    rows = traffic(); driver = RecordedDriver(rows)
    driver.start(rows[0]["payload"], timeout_s=1)
    actual = copy.deepcopy(rows[1]["payload"])
    if change == "observation": actual["decision"]["observation"] = {"hand": ["B"]}
    if change == "candidates": actual["decision"]["candidates"] = [0]
    if change == "max_clock": actual["clock"]["max_decision_ms"] = 11
    if change == "game_id": actual["game_id"] = "other"
    with pytest.raises(ValueError, match="public payload changed"):
        driver.choose(actual, timeout_s=1)


def test_recorded_replay_checks_swallowed_game_over_failure_and_unused_rows():
    rows = traffic(); driver = RecordedDriver(rows)
    driver.start(rows[0]["payload"], timeout_s=1)
    driver.choose(rows[1]["payload"], timeout_s=1)
    with pytest.raises(ValueError, match="public payload changed"):
        driver.game_over({"winner": "p1"}, timeout_s=1)
    with pytest.raises(ValueError, match="completely matched"):
        driver.finish()
    with pytest.raises(ValueError, match="completely matched"):
        RecordedDriver(rows).finish()


def test_complete_engine_capture_preserves_all_response_fields():
    class Peer:
        def write_line(self, line): self.written = line
        def read_line(self): return b'{"response_type":"terminal","hidden_state":{"secret":42}}'
    stream = io.BytesIO(); peer = Peer(); tap = CapturePeer(peer, stream)
    tap.write_line(b'{"request_type":"step","selection":{"candidate_id":1}}')
    assert tap.read_line() == peer.read_line()
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert rows[0]["dir"] == "host_to_engine" and rows[0]["message"]["selection"]["candidate_id"] == 1
    assert rows[1]["dir"] == "engine_to_host" and rows[1]["message"]["hidden_state"] == {"secret": 42}
