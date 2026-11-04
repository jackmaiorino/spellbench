"""check_engine_v2 rejects any bot-facing message that carries native identity."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import check_engine_v2
from check_engine_v2 import assert_no_native_identity
from spellbench import wire
from test_kernel_observation_v2 import adapter, project, raw


def test_projected_observation_passes():
    assert_no_native_identity(wire.canonical_json_dumps(project(adapter(), raw())))


@pytest.mark.parametrize("leak, marker", [
    ({"object_id": "obj-000067-z0001"}, "obj-"),
    ({"stable": {"arena_id": 67}}, "arena_id"),
    ({"extensions": {"x_kernel_v5": {"observation_json": "{}"}}}, "x_kernel_v5"),
])
def test_each_marker_trips(leak, marker):
    message = wire.canonical_json_dumps({"seat_decision": {"observation": project(adapter(), raw()), **leak}})
    with pytest.raises(AssertionError, match=marker):
        assert_no_native_identity(message)
    with pytest.raises(AssertionError, match=marker):
        assert_no_native_identity(message.decode())


def test_raw_bridge_observation_trips():
    with pytest.raises(AssertionError, match="arena_id"):
        assert_no_native_identity(wire.canonical_json_dumps(raw()))


class LeakyPeer:
    closed = 0

    def __init__(self, executable):
        pass

    def close(self):
        LeakyPeer.closed += 1


class LeakyEngine:
    """Answers every request with a message that forwards the raw extension."""

    def __init__(self, peer, catalog):
        pass

    def handle(self, payload):
        return wire.canonical_json_line({"protocol": "spellbench/v2", "response_type": "hello_ok",
                                         "extensions": {"x_kernel_v5": {"observation_json": "{}"}}})


def test_check_fails_on_a_leaking_engine(monkeypatch):
    monkeypatch.setattr(check_engine_v2, "NativePeer", LeakyPeer)
    monkeypatch.setattr(check_engine_v2, "KernelEngine", LeakyEngine)
    LeakyPeer.closed = 0
    with pytest.raises(AssertionError, match="native identity: x_kernel_v5"):
        check_engine_v2.check("bridge", {"catalog": []}, "Burn", "p0", [])
    assert LeakyPeer.closed == 2
