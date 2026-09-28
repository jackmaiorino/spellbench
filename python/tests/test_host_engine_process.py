"""The host's engine client (spec 9)."""

from __future__ import annotations

import copy
import sys
import threading
import time

import pytest

from spellbench import wire
from spellbench.errors import EngineError, PeerTimeoutError, ProtocolError
from spellbench.host.engine_process import EngineProcess, TerminalCountError, TerminalReasonError
from spellbench.messages import ResetRequest

from conftest import ScriptedPeer
from test_messages import HELLO_OK, PROVENANCE, RESET, TERMINAL


def _decision(request_id: str, step: int, *, game_id: str = RESET["game_id"]) -> bytes:
    return wire.canonical_json_dumps({"response_type": "decision", "protocol": "spellbench/v2", "request_id": request_id,
                                      "game_id": game_id, "step": step, "provenance": PROVENANCE,
                                      "seat_decision": {"acting_seat": "p0", "candidates": [
                                          {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}})


def _hello(peer: ScriptedPeer) -> EngineProcess:
    engine = EngineProcess(peer=peer)
    engine.hello()
    return engine


def _reset(engine: EngineProcess):
    return engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))


def test_a_game_binds_steps_and_echoes_the_semantic() -> None:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), _decision("h-2", 0),
                         wire.canonical_json_dumps({**TERMINAL, "request_id": "h-3", "step_count": 1, "decision_count": 1})])
    engine = _hello(peer)
    assert _reset(engine).step == 0
    terminal = engine.step(candidate_id=0, semantic={"kind": "pass"})
    assert terminal.result.step_count == 1
    step = wire.strict_json_loads(peer.sent[2])
    assert step["expected_step"] == 0 and step["selection"] == {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert engine.last_request == step and engine.last_response["response_type"] == "terminal"


@pytest.mark.parametrize(
    "answer",
    [
        _decision("h-9", 0),                                                        # request_id not echoed
        _decision("h-2", 3),                                                        # the first decision is step 0
        _decision("h-2", 0, game_id="g-not-the-requested-game"),                    # decision game_id mismatch
        wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "step_count": 5}),  # a reset terminal answers 0 steps
        wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "game_id": "g-not-the-requested-game",
                                   "step_count": 0, "decision_count": 0}),           # terminal game_id mismatch
    ],
)
def test_binding_drift_is_a_protocol_error(answer: bytes) -> None:
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), answer]))
    with pytest.raises(ProtocolError):
        _reset(engine)


def test_a_wrong_terminal_step_count_is_a_terminal_count_error() -> None:
    terminal = wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "step_count": 5})
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), terminal]))
    with pytest.raises(TerminalCountError) as caught:
        _reset(engine)
    assert caught.value.terminal.result.step_count == 5                    # R2-3


def test_the_v2_engine_error_codes_are_accepted() -> None:
    error = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-2",
             "error": {"code": "unsupported_rule", "message": "no such mulligan"}}     # not a v1 code (R2-17)
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), wire.canonical_json_dumps(error)]))
    with pytest.raises(EngineError) as caught:
        _reset(engine)
    assert caught.value.code == "unsupported_rule"


def test_an_error_envelope_is_an_engine_error() -> None:
    error = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-2",
             "error": {"code": "unsupported_deck", "message": "no such deck"}}
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), wire.canonical_json_dumps(error)]))
    with pytest.raises(EngineError) as caught:
        _reset(engine)
    assert caught.value.code == "unsupported_deck"


def test_a_higher_minor_than_requested_is_refused() -> None:
    with pytest.raises(ProtocolError, match="protocol_minor"):
        _hello(ScriptedPeer([wire.canonical_json_dumps({**HELLO_OK, "protocol_minor": 1})]))


def test_raw_probes_do_not_touch_the_game_state() -> None:
    mismatch = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "x",
                "error": {"code": "protocol_mismatch", "message": "v2 only"}}
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), wire.canonical_json_dumps(mismatch)]))
    last_request, last_response, counter = engine.last_request, engine.last_response, engine._request_counter
    assert engine.send_raw({"request_type": "hello", "protocol": "spellbench/v1", "request_id": "x"})["error"]["code"] == "protocol_mismatch"
    assert engine.last_request == last_request and engine.last_response == last_response  # untouched by the probe
    assert engine._request_counter == counter                                             # no request_id consumed


@pytest.mark.parametrize("reason", ["host_validator:V3", "host_engine_fault:terminal_counts", "forfeit:stalling"])
def test_an_engine_terminal_never_impersonates_the_host(reason: str) -> None:
    terminal = wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "reason": reason,
                                          "step_count": 0, "decision_count": 0})
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), terminal]))
    with pytest.raises(TerminalReasonError) as caught:
        _reset(engine)
    assert caught.value.terminal.result.reason == reason


@pytest.mark.parametrize("reason", ["Forfeit:timeout", "HOST_VALIDATOR:V4", " forfeit:x", "host_engine_fault :terminal_counts",
                                    "\uff46orfeit:timeout"])
def test_an_engine_terminal_never_imitates_a_host_reason(reason: str) -> None:
    terminal = wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "reason": reason,
                                          "step_count": 0, "decision_count": 0})
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), terminal]))
    with pytest.raises(TerminalReasonError):                                  # case, spacing and width aside (M13)
        _reset(engine)


# I3 (spec 9.3 to 9.5): an answer binds to its request by type and by echo, and a misrouted
# answer is a ProtocolError the game loop classifies, never a KeyError.

HELLO_LINE = wire.canonical_json_dumps(HELLO_OK)
_REQUEST_IDS = {"hello": "h-1", "reset": "h-2", "validate_deck": "h-2", "step": "h-3"}
_ROUTES = {"hello_ok": ("hello",), "decision": ("reset", "step"), "terminal": ("reset", "step"), "deck_ok": ("validate_deck",)}
MISROUTED = [(kind, request) for kind, routes in _ROUTES.items() for request in _REQUEST_IDS if request not in routes]


def _deck_ok(request_id: str) -> bytes:
    return wire.canonical_json_dumps({"response_type": "deck_ok", "protocol": "spellbench/v2", "request_id": request_id})


def _answer(kind: str, request_id: str) -> bytes:
    """A well-formed engine answer of ``kind`` that echoes ``request_id``."""
    if kind == "hello_ok":
        return wire.canonical_json_dumps({**HELLO_OK, "request_id": request_id})
    if kind == "decision":
        return _decision(request_id, 0)
    if kind == "terminal":
        return wire.canonical_json_dumps({**TERMINAL, "request_id": request_id, "step_count": 0, "decision_count": 0})
    return _deck_ok(request_id)


def _pose(request_type: str, answer: bytes):
    """The call that sends ``request_type`` to an engine whose peer answers it with ``answer``."""
    if request_type == "hello":
        return EngineProcess(peer=ScriptedPeer([answer])).hello
    engine = _hello(ScriptedPeer([HELLO_LINE, *([_decision("h-2", 0)] if request_type == "step" else []), answer]))
    if request_type == "reset":
        return lambda: _reset(engine)
    if request_type == "step":
        _reset(engine)
        return lambda: engine.step(candidate_id=0, semantic={"kind": "pass"})
    return lambda: engine.validate_deck(format="pauper-bo1", catalog_id="Burn")


@pytest.mark.parametrize(("kind", "request_type"), MISROUTED)
def test_an_answer_of_the_wrong_type_is_a_protocol_error(kind: str, request_type: str) -> None:
    call = _pose(request_type, _answer(kind, _REQUEST_IDS[request_type]))
    with pytest.raises(ProtocolError, match=f"^{kind} response to a non-"):
        call()


@pytest.mark.parametrize(
    ("request_type", "answer", "detail"),
    [
        ("hello", wire.canonical_json_dumps({**HELLO_OK, "request_id": "h-9"}), "hello_ok request_id mismatch"),
        ("reset", wire.canonical_json_dumps({**TERMINAL, "request_id": "h-9", "step_count": 0, "decision_count": 0}),
         "response request_id mismatch"),
        ("reset", wire.canonical_json_dumps({"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-9",
                                             "error": {"code": "unsupported_deck", "message": "no such deck"}}),
         "error response request_id mismatch"),
        ("validate_deck", _deck_ok("h-9"), "deck_ok request_id mismatch"),
    ],
    ids=["hello_ok", "terminal", "error", "deck_ok"],
)
def test_an_answer_echoing_another_request_is_a_protocol_error(request_type: str, answer: bytes, detail: str) -> None:
    with pytest.raises(ProtocolError, match=f"^{detail}$"):
        _pose(request_type, answer)()


def test_an_engine_namespaced_reason_is_accepted() -> None:
    terminal = wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "outcome": "halted",
                                          "classification": "halted", "winner": None,
                                          "reason": "engine_contract_failure:candidate_limit",
                                          "step_count": 0, "decision_count": 0})
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), terminal]))
    assert _reset(engine).result.reason == "engine_contract_failure:candidate_limit"


def test_a_second_decision_steps_from_the_first() -> None:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), _decision("h-2", 0), _decision("h-3", 1),
                         wire.canonical_json_dumps({**TERMINAL, "request_id": "h-4", "step_count": 2, "decision_count": 2})])
    engine = _hello(peer)
    assert _reset(engine).step == 0
    second = engine.step(candidate_id=0, semantic={"kind": "pass"})
    assert second.step == 1                                                  # the previous step (0) plus 1
    terminal = engine.step(candidate_id=0, semantic={"kind": "pass"})
    assert terminal.result.step_count == 2


def test_a_wrong_second_decision_step_is_a_protocol_error() -> None:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), _decision("h-2", 0), _decision("h-3", 5)])
    engine = _hello(peer)
    _reset(engine)
    with pytest.raises(ProtocolError, match="step drift"):
        engine.step(candidate_id=0, semantic={"kind": "pass"})


def test_retry_last_replays_the_cached_response() -> None:
    decision_line = _decision("h-2", 0)
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), decision_line, decision_line])
    engine = _hello(peer)
    first = _reset(engine)
    replay = engine.retry_last()
    assert replay == first
    assert peer.sent[1] == peer.sent[2]                                      # byte-identical retransmission (spec 4.1)


def test_retry_last_rejects_a_non_identical_replay() -> None:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), _decision("h-2", 0), _decision("h-2", 7)])
    engine = _hello(peer)
    _reset(engine)
    with pytest.raises(ProtocolError, match="different response"):
        engine.retry_last()


def test_validate_deck_sends_the_catalog_form_and_returns_deck_ok() -> None:
    deck_ok = wire.canonical_json_dumps({"response_type": "deck_ok", "protocol": "spellbench/v2", "request_id": "h-2"})
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), deck_ok])
    engine = _hello(peer)
    result = engine.validate_deck(format="pauper-bo1", catalog_id="Burn")
    assert result.request_id == "h-2"
    request = wire.strict_json_loads(peer.sent[1])
    assert request["format"] == "pauper-bo1" and request["deck"] == {"catalog_id": "Burn"}


def test_a_real_engine_that_never_reads_its_stdin_times_out_on_a_big_write() -> None:
    # A real child process, not a mock: it never touches stdin, so a payload bigger than
    # any OS pipe buffer (about 4 KiB on Windows, 64 KiB on Linux) blocks the write until
    # SubprocessPeer kills it (R2-5). send_raw needs no prior hello, so the first request is
    # the oversized one. engine_process.py adds no mapping of its own: a write timeout must
    # propagate exactly like a read timeout already does, as a bare PeerTimeoutError.
    engine = EngineProcess([sys.executable, "-c", "import time; time.sleep(60)"], timeout_s=2)
    huge_request = {"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1",
                     "protocol_minor": 0, "padding": "x" * (4 * 1024 * 1024)}
    before = {t.ident for t in threading.enumerate()}
    started = time.monotonic()
    with pytest.raises(PeerTimeoutError):
        engine.send_raw(huge_request)
    elapsed = time.monotonic() - started
    assert elapsed < 4                                                     # within twice the 2 s timeout
    peer = engine._peer
    assert isinstance(peer, wire.SubprocessPeer) and peer._proc.poll() is not None    # the child is dead
    time.sleep(0.2)                                                        # let a just-finished writer thread drop out
    assert {t.ident for t in threading.enumerate()} <= before              # no helper thread left alive
    engine.close()
