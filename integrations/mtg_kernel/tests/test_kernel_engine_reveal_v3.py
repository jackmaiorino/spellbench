"""Actual neutral adapter path over supplied public native messages.

These fixtures exercise reset/step/projection/host validation, not native
visibility or complete-game engine qualification.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_engine_reveal_v3 import KernelRevealEngineV3, RevealNativePeerV3
from kernel_engine_v2 import FLAT, HISTORY
from spellbench import wire
from spellbench.digests import card_name_domain, deck_id
from spellbench.host.validator import LiveValidator
from spellbench.messages import Decision, EnvHelloOk, Rules, Terminal
from spellbench.reveal_meaning_v3 import SCHEMA, RevealProducerV3, RevealReducerV3
from test_kernel_observation_v2 import card, catalog, raw
from test_kernel_reveal_v3 import present, support


class PublicPeer:
    def __init__(self, *, malformed=False, hand_count=2, native_offset=0):
        self.calls, self.index = [], 0
        self.malformed, self.hand_count, self.native_offset = malformed, hand_count, native_offset
        producer = RevealProducerV3()
        self.operations = [producer.operation([present()])["operations"],
                           producer.operation([present()])["operations"]]
        self.operations.append(producer.operation([
            {"kind": "hand_arrival", "owner_seat": "p1", "card_name": None,
             "evidence": {"kind": "search_reveal"}},
            {**present(), "meaning": "moved", "arrival": producer.token(0)},
        ])["operations"])
        self.operations.append(producer.operation([
            {"kind": "hand_arrival", "owner_seat": "p1", "card_name": "Island",
             "evidence": {"kind": "public_transfer", "from_zone": "stack"}},
            {**present(), "meaning": "moved", "arrival": producer.token(0)},
        ])["operations"])
        self.operations.extend([[], []])  # each viewer next receives all four classes
        self.operations.append(producer.operation([
            {"kind": "hand_departure", "owner_seat": "p1", "card_name": None, "count": 1},
        ])["operations"])

    def request(self, request):
        self.calls.append(deepcopy(request))
        if request["request_type"] == "hello":
            return {"response_type": "hello_ok", "engine": {
                "name": "mtg-kernel", "version": "fixture", "source_revision": None,
                "rules_snapshot_id": "fixture", "card_pool_identity": "fixture"}}
        if request["request_type"] == "reset":
            self.index = 0
        else:
            assert request["request_type"] == "step"
            self.index += 1
        operations = self.operations[self.index]
        reveal = support(operations, operations)
        if self.malformed:
            reveal["viewers"][1]["transcript"]["operations"][0]["events"][0]["native_id"] = 999
        private = {"reveal_meaning_v3": reveal, "stack_instances": [],
                   "history": {"intentionally_invalid_private_slice": True}}
        if self.index == 6:
            return {"response_type": "terminal", "winner": None, "outcome": "draw", "reason": "game_over",
                    "extensions": {"x_kernel_v2_support": private}}
        value = raw()
        actor = f"p{self.index % 2}"
        value["acting_player"] = actor
        value["projection"].update(hand_counts=[self.hand_count] * 2, priority_player=actor)
        value["own_hand"] = [card(arena=self.native_offset + i, owner=actor)
                             for i in range(self.hand_count)]
        return {"response_type": "decision", "step": self.index,
                "group": {"substep_index": 0, "substep_count": 1},
                "candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}}],
                "extensions": {"x_kernel_v2_support": private,
                    "x_kernel_v5": {"observation_json": json.dumps(value)},
                    FLAT: {"row_candidate_ids": [0], "private_tensor": "never forwarded"}}}


def setup(first="p0", **peer_options):
    data = catalog()
    data["cards"]["Island"]["characteristics"]["keywords"] = []
    rows = [{"name": "Island", "count": 60}]
    data["catalog"] = [{"catalog_id": "Islands", "name": "Islands", "decklist": rows}]
    peer = PublicPeer(**peer_options)
    engine = KernelRevealEngineV3(peer, data)
    request = {"protocol": "spellbench/v2", "request_id": "reset", "request_type": "reset",
        "game_id": "public-reveal-fixture", "format": "pauper-bo1", "game_secret": "ab" * 32,
        "max_steps": 8, "max_decisions": 8,
        "rules": {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
                  "starting_seat": first, "card_name_domain": card_name_domain(["Island"]),
                  "extensions": [SCHEMA], "probe": False},
        "seats": [{"seat": seat, "deck": {"catalog_id": "Islands", "deck_id": deck_id(rows)}}
                  for seat in ("p0", "p1")]}
    return engine, peer, request


@pytest.mark.parametrize("first", ["p0", "p1"])
def test_four_classes_cross_actual_adapter_host_and_reducer_both_seats(first):
    engine, peer, request = setup(first)
    other, _, _ = setup(first, native_offset=10000)
    validator = LiveValidator(EnvHelloOk.from_json(engine.hello), Rules.from_json(request["rules"]),
                              max_steps=8, max_decisions=8)
    reducers = {seat: RevealReducerV3() for seat in ("p0", "p1")}
    for step in range(7):
        payload = wire.canonical_json_dumps(request)
        response = engine.handle(payload)
        assert response == other.handle(payload)
        calls = len(peer.calls)
        assert response == engine.handle(payload) and len(peer.calls) == calls
        current = wire.strict_json_loads(response)
        assert all(marker not in response.decode() for marker in ("arena_id", "native_id", "x_kernel_v5", HISTORY, FLAT))
        if step == 6:
            validator.check_terminal(Terminal.from_json(current))
            assert "extensions" not in current
            assert engine.hand_constraints(0) == [{"owner_seat": "p1" if first == "p0" else "p0",
                                                   "card_name": "Island", "minimum": 1}]
            break
        sd = validator.check(Decision.from_json(current))
        reducer = reducers[sd["acting_seat"]]
        reducer.absorb(sd["extensions"][SCHEMA])
        assert reducer.known_hand() == engine.hand_constraints(step % 2)
        if step >= 4:
            assert reducer.known_hand()[0]["minimum"] == 2
        validator.answered(sd, 0)
        request = {"protocol": "spellbench/v2", "request_id": f"step-{step}", "request_type": "step",
                   "game_id": current["game_id"], "expected_step": step,
                   "selection": {"candidate_id": 0, "semantic_echo": sd["candidates"][0]["semantic"]}}


def test_invalid_native_batch_halts_without_leaking_or_committing():
    engine, _, request = setup(malformed=True)
    result = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    assert result["response_type"] == "terminal" and result["classification"] == "halted"
    assert result["reason"] == "reveal_projection_failure"
    assert engine.hand_constraints(0) == engine.hand_constraints(1) == []


@pytest.mark.parametrize("broken", [None, [], "private malformed value"])
@pytest.mark.parametrize("field", ["extensions", "support", "response"])
def test_malformed_private_envelope_refuses_without_an_attribute_error(broken, field):
    engine, peer, request = setup()
    native_request = peer.request

    def malformed(value):
        result = native_request(value)
        if field == "response":
            return broken
        if field == "extensions":
            result["extensions"] = broken
        else:
            result["extensions"]["x_kernel_v2_support"] = broken
        return result

    peer.request = malformed
    answer = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    assert answer["response_type"] == "terminal" and answer["classification"] == "halted"
    assert answer["reason"] == "reveal_projection_failure"
    assert answer["game_id"] == request["game_id"]
    assert engine.hand_constraints(0) == engine.hand_constraints(1) == []


@pytest.mark.parametrize("io_failure", [False, True])
def test_failed_restart_terminal_belongs_to_new_reset_with_zero_counts(io_failure):
    engine, peer, request = setup()
    native_request = peer.request
    request["max_steps"] = 1
    first = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    sd = first["seat_decision"]
    cap = engine.step({"request_id": "cap", "game_id": engine.game, "expected_step": 0,
        "selection": {"candidate_id": 0, "semantic_echo": sd["candidates"][0]["semantic"]}})
    assert cap["classification"] == "truncated" and engine.current["response_type"] == "decision"

    def restart():
        if io_failure:
            raise OSError("private child diagnostic")
        peer.request = lambda value: {"response_type": "error"}

    peer.restart = restart
    request.update(request_id="new-reset", game_id="new-game")
    answer = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    assert answer["response_type"] == "terminal" and answer["classification"] == "halted"
    assert answer["game_id"] == "new-game" and answer["request_id"] == "new-reset"
    assert answer["step_count"] == answer["decision_count"] == 0
    assert answer["reason"] == "reveal_projection_failure"
    restarts = []

    def repaired_restart():
        restarts.append(True)
        peer.request = native_request

    peer.restart = repaired_restart
    request.update(request_id="recovered-reset", game_id="recovered-game")
    recovered = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    assert recovered["response_type"] == "decision" and recovered["game_id"] == "recovered-game"
    assert recovered["step"] == 0 and restarts == [True]


def test_public_hand_count_bound_refuses_before_draining():
    engine, _, request = setup(hand_count=0)
    result = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    assert result["response_type"] == "terminal" and result["classification"] == "halted"
    assert len(engine.reveal_history.pending[0]) == 1


@pytest.mark.parametrize("extensions", [[], [FLAT], [HISTORY], [SCHEMA, FLAT]])
def test_legacy_profiles_are_not_silently_enabled(extensions):
    engine, peer, request = setup()
    request["rules"]["extensions"] = extensions
    result = wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))
    assert result["error"]["code"] == "unsupported_rule"
    assert len(peer.calls) == 1 and engine.game is None


def test_native_restart_keeps_new_flag(monkeypatch):
    commands = []
    monkeypatch.setattr("kernel_engine_reveal_v3.subprocess.Popen",
                        lambda command, **kwargs: commands.append(command) or object())
    monkeypatch.setattr(RevealNativePeerV3, "close", lambda self: None)
    peer = RevealNativePeerV3("bridge")
    peer.restart()
    assert commands[0] == commands[1]
    assert commands[0][-1] == "--reveal-meaning-v3"


def test_buffered_neutral_substeps_do_not_redeliver_or_advance_native_history():
    from kernel_reveal_v3 import RevealHistoryV3
    from test_kernel_buffered_mill_v2 import MillPeer, engine_for
    peer = MillPeer(4)
    base = engine_for(peer)
    engine = KernelRevealEngineV3.__new__(KernelRevealEngineV3)
    engine.__dict__.update(base.__dict__)
    engine.rules = {"extensions": []}
    engine.max_steps = engine.max_groups = 20
    engine._reveal_game = engine.game
    engine.reveal_history = RevealHistoryV3()
    engine.current["extensions"]["x_kernel_v2_support"]["reveal_meaning_v3"] = support(
        [{"sequence": 0, "events": [present()]}])
    engine.absorb_history()
    first = engine.pose("first")
    assert len(first["seat_decision"]["extensions"][SCHEMA]["operations"]) == 1
    second = engine.step({"request_id": "next", "game_id": engine.game, "expected_step": 0,
        "selection": {"candidate_id": 0, "semantic_echo": first["seat_decision"]["candidates"][0]["semantic"]}})
    assert second["seat_decision"]["extensions"][SCHEMA]["operations"] == []
    assert peer.committed == peer.preview_prefixes == []
