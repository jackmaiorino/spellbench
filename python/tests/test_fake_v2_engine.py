"""The v2 fake engine: strict protocol handling, the scoring game, the hooks, the scenario runner."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.candidates import validate_candidate
from spellbench.digests import deck_id
from spellbench.errors import TransportError
from spellbench.host.tracking import GroupTracker
from spellbench.messages import EnvHelloOk
from spellbench.observation import validate_observation

import fake_v2_scenario_smoke

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"
BURN_ID = deck_id([{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}])
DOMAIN = {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]}
RULES = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
         "card_name_domain": DOMAIN, "extensions": [], "probe": False}


class Engine:
    def __init__(self, *args: str) -> None:
        self.peer = wire.SubprocessPeer([sys.executable, str(ENGINE), *args], timeout_s=30)
        self.count = 0

    def send(self, request_type: str, **fields) -> dict:
        self.count += 1
        message = {"request_type": request_type, "protocol": "spellbench/v2", "request_id": f"h-{self.count}", **fields}
        self.peer.write_line(wire.canonical_json_dumps(message))
        return wire.strict_json_loads(self.peer.read_line())

    def raw(self, line: bytes) -> dict:
        self.peer.write_line(line)
        return wire.strict_json_loads(self.peer.read_line())

    def reset(self, deck: str = "Burn", game_id: str = "g-0000000000000001", **changes) -> dict:
        fields = {"game_id": game_id, "format": "pauper-bo1",
                  "seats": [{"seat": seat, "deck": {"deck_id": BURN_ID, "catalog_id": deck}} for seat in ("p0", "p1")],
                  "rules": RULES, "game_secret": "11" * 32, "max_decisions": 10000, "max_steps": 100000}
        fields.update(changes)
        return self.send("reset", **fields)


@pytest.fixture
def engine():
    process = Engine()
    process.send("hello", protocol_minor=0)
    yield process
    process.peer.close()


def test_hello_is_a_valid_v2_hello_ok() -> None:
    process = Engine("--all-flags", "--rewind")
    hello = EnvHelloOk.from_json(process.send("hello", protocol_minor=0))
    process.peer.close()
    assert hello.profile.rewind and all(hello.profile.observation.values())
    assert {deck.catalog_id for deck in hello.catalog} >= {"Burn", "Echo", "Elves", "Faeries", "Loop", "P0Wins", "Stall", "Scenario:smoke"}
    assert hello.formats == ("pauper-bo1",) and hello.profile.extensions == ()                     # R2-13
    assert set(hello.profile.engine_defaults.values()) == {None}


def test_the_scoring_game_matches_the_v1_outcomes(engine: Engine) -> None:
    response, step = engine.reset(), 0
    while response["response_type"] == "decision":
        seat_decision = response["seat_decision"]
        validate_observation(seat_decision["observation"])
        for candidate in seat_decision["candidates"]:
            validate_candidate(candidate)
        pick = 1 if seat_decision["acting_seat"] == "p0" else 0          # p0 plays lands, p1 passes
        semantic = seat_decision["candidates"][pick]["semantic"]
        response = engine.send("step", game_id="g-0000000000000001", expected_step=step,
                               selection={"candidate_id": pick, "semantic_echo": semantic})
        step += 1
    assert (response["outcome"], response["reason"], response["step_count"]) == ("p0_win", "score", 4)


@pytest.mark.parametrize(
    ("request_fn", "code"),
    [
        (lambda e: e.send("step", game_id="g-1", expected_step=0, selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}}), "step_before_reset"),
        (lambda e: e.reset(format="modern"), "unsupported_format"),
        (lambda e: e.reset(deck="Nope"), "unsupported_deck"),
        (lambda e: e.reset(deck="Refuse"), "unsupported_deck"),
        (lambda e: e.reset(seats=[{"seat": s, "deck": {"deck_id": "sha256:" + "0" * 64, "catalog_id": "Burn"}} for s in ("p0", "p1")]), "deck_id_mismatch"),
        (lambda e: e.reset(rules={**RULES, "mulligan": "london"}), "unsupported_rule"),
        (lambda e: e.reset(rules={**RULES, "probe": True}), "unsupported_rule"),
        (lambda e: e.reset(x_extra=1), "malformed_request"),
        (lambda e: e.raw(b"[1,2]"), "malformed_request"),                                   # a non-object top level (R1-3)
        (lambda e: e.reset(rules={**RULES, "extensions": ["x_kernel_v5"]}), "unsupported_rule"),   # not declared in hello
        (lambda e: e.send("probe_resample", game_id="g-1", samples=1), "unsupported_request"),
        (lambda e: e.send("hello", protocol_minor=0, protocol="spellbench/v1"), "protocol_mismatch"),
        (lambda e: e.send("validate_deck", format="pauper-bo1", deck={"catalog_id": "Nope"}), "unsupported_deck"),
    ],
)
def test_error_codes(engine: Engine, request_fn, code: str) -> None:
    answer = request_fn(engine)
    assert (answer["response_type"], answer["error"]["code"]) == ("error", code)


def test_a_valid_deck_is_ok_and_a_non_object_line_carries_no_request_id(engine: Engine) -> None:
    assert engine.send("validate_deck", format="pauper-bo1", deck={"catalog_id": "Burn"})["response_type"] == "deck_ok"
    assert engine.raw(b"[1,2]")["request_id"] == ""


def test_step_checks_run_in_the_spec_9_4_order(engine: Engine) -> None:
    engine.reset()
    selection = {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert engine.send("step", game_id="g-9", expected_step=7, selection=selection)["error"]["code"] == "game_id_mismatch"


def test_a_request_that_fails_parsing_is_never_cached(engine: Engine) -> None:
    first = engine.reset()
    step = {"request_type": "step", "protocol": "spellbench/v2", "request_id": "h-60", "game_id": first["game_id"],
            "expected_step": 0, "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}}
    assert engine.raw(wire.canonical_json_dumps({**step, "x_extra": 1}))["error"]["code"] == "malformed_request"
    assert engine.raw(wire.canonical_json_dumps(step))["response_type"] == "decision"    # same id: served, not a reuse (R1-20)


def test_a_reused_game_id_is_malformed(engine: Engine) -> None:
    halted = engine.reset(deck="Halt")
    engine.send("step", game_id=halted["game_id"], expected_step=0, selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}})
    assert engine.reset()["error"]["code"] == "malformed_request"                          # the finished game's id
    assert engine.reset(game_id="g-0000000000000002")["response_type"] == "decision"       # a new reset after a terminal


def test_game_errors_and_retransmission(engine: Engine) -> None:
    first = engine.reset()
    assert engine.reset(game_id="g-0000000000000002")["error"]["code"] == "game_already_active"
    selection = {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert engine.send("step", game_id="g-9", expected_step=0, selection=selection)["error"]["code"] == "game_id_mismatch"
    assert engine.send("step", game_id=first["game_id"], expected_step=5, selection=selection)["error"]["code"] == "expected_step_mismatch"
    assert engine.send("step", game_id=first["game_id"], expected_step=0, selection={**selection, "candidate_id": 9})["error"]["code"] == "candidate_id_out_of_range"
    assert engine.send("step", game_id=first["game_id"], expected_step=0,
                       selection={"candidate_id": 1, "semantic_echo": {"kind": "pass"}})["error"]["code"] == "semantic_echo_mismatch"
    line = wire.canonical_json_dumps({"request_type": "step", "protocol": "spellbench/v2", "request_id": "h-50",
                                      "game_id": first["game_id"], "expected_step": 0, "selection": selection})
    engine.peer.write_line(line)
    answer = engine.peer.read_line()
    engine.peer.write_line(line)                       # the identical retransmission
    assert engine.peer.read_line() == answer
    engine.peer.write_line(line.replace(b'"expected_step":0', b'"expected_step":1'))
    assert wire.strict_json_loads(engine.peer.read_line())["error"]["code"] == "request_id_reuse_mismatch"
    engine.peer.write_line(b"{not json")
    error = wire.strict_json_loads(engine.peer.read_line())
    assert (error["request_id"], error["error"]["code"]) == ("", "malformed_json")


def test_probe_refused_with_the_probe_declared() -> None:
    process = Engine("--probe")
    process.send("hello", protocol_minor=0)
    process.reset()
    assert process.send("probe_resample", game_id="g-0000000000000001", samples=1)["error"]["code"] == "probe_refused"
    process.peer.close()


def test_hooks(engine: Engine) -> None:
    loop = Engine()
    loop.send("hello", protocol_minor=0)
    decision = loop.reset(deck="Loop")
    for step in range(20):
        assert [c["semantic"]["kind"] for c in decision["seat_decision"]["candidates"]] == ["pass"]
        decision = loop.send("step", game_id="g-0000000000000001", expected_step=step, selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}})
    loop.peer.close()
    halted = engine.reset(deck="Halt")
    selection = {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert engine.send("step", game_id=halted["game_id"], expected_step=0, selection=selection)["outcome"] == "halted"
    after = engine.send("step", game_id=halted["game_id"], expected_step=1, selection=selection)
    assert after["error"]["code"] == "game_already_terminal"                                  # R2-13


def _play(engine: Engine, deck: str, game_id: str, pick=lambda sd: 0) -> dict:
    response, step = engine.reset(deck=deck, game_id=game_id), 0
    while response["response_type"] == "decision":
        sd = response["seat_decision"]
        choice = pick(sd)
        response = engine.send("step", game_id=game_id, expected_step=step,
                               selection={"candidate_id": choice, "semantic_echo": sd["candidates"][choice]["semantic"]})
        step += 1
    return response


def test_the_ending_hooks(engine: Engine) -> None:
    assert _play(engine, "Truncate", "g-0000000000000011")["reason"] == "engine_cap"
    assert _play(engine, "P0Wins", "g-0000000000000012", pick=lambda sd: len(sd["candidates"]) - 1)["outcome"] == "p0_win"
    stall = _play(engine, "Stall", "g-0000000000000013")                                   # p0 passes: a natural draw
    assert (stall["outcome"], stall["reason"]) == ("draw", "stall_ended")
    echo = _play(engine, "Echo", "g-0000000000000014")
    assert echo["reason"] == "secret:" + hashlib.sha256(bytes.fromhex("11" * 32)).hexdigest()[:8]   # R3-16


def test_the_crash_hook_exits_at_the_first_step(engine: Engine) -> None:
    first = engine.reset(deck="Crash")
    engine.peer.write_line(wire.canonical_json_dumps({
        "request_type": "step", "protocol": "spellbench/v2", "request_id": "h-90", "game_id": first["game_id"],
        "expected_step": 0, "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}}))
    with pytest.raises(TransportError):
        engine.peer.read_line()


def test_the_smoke_scenario_numbers_counts_and_rewinds_like_the_host() -> None:
    process = Engine("--rewind")
    process.send("hello", protocol_minor=0)
    deck = {"deck_id": deck_id(fake_v2_scenario_smoke.SCENARIO.decklist), "catalog_id": "Scenario:smoke"}
    response = process.reset(seats=[{"seat": seat, "deck": deck} for seat in ("p0", "p1")])
    tracker, contexts, step = GroupTracker(), [], 0
    while response["response_type"] == "decision":
        sd = response["seat_decision"]
        validate_observation(sd["observation"])
        for candidate in sd["candidates"]:
            validate_candidate(candidate)
        tracker.check(sd)                                         # V3: seat steps, groups, the rewind (Task 10)
        contexts.append((sd["context"]["kind"], sd["context"]["purpose"], sd["context"]["rewind"]))
        kinds = [candidate["semantic"]["kind"] for candidate in sd["candidates"]]
        pick = kinds.index("cast_spell") if "cast_spell" in kinds else len(kinds) - 1   # take the action the rewind undoes
        tracker.answered(sd, chosen_kind=kinds[pick])
        response = process.send("step", game_id=response["game_id"], expected_step=step,
                                selection={"candidate_id": pick, "semantic_echo": sd["candidates"][pick]["semantic"]})
        step += 1
    process.peer.close()
    counts = (response["step_count"], response["decision_count"])
    assert counts == (tracker.answered_steps, tracker.completed_groups) == (7, 3)          # Decision 4 (R2-1)
    assert ("priority", None, True) in contexts and ("choice", "mana_payment", False) in contexts
