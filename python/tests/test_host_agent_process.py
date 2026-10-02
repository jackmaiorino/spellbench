"""Agent-role messages and the host's agent client (spec 10)."""

from __future__ import annotations

import os
import pickle
import sys
import threading
import time

import pytest

from spellbench import wire
from spellbench.agent_messages import (
    AGENT_ERROR_CODES,
    AgentHelloOk,
    AgentTerminal,
    BotIdentity,
    Choice,
    Clock,
    OwnDeck,
    choose_payload,
    game_over_payload,
    game_start_payload,
)
from spellbench.errors import PeerTimeoutError, TransportError, ValidationError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.setup import GameSetup
from spellbench.host.seat import SeatFailure
from spellbench.messages import Limits, Resources, Rules, TimeControl, WireDeck

from conftest import ScriptedPeer


def _answer(**message) -> bytes:
    return wire.canonical_json_dumps({"protocol": "spellbench/v2", **message})


HELLO = _answer(response_type="hello_ok", request_id="r-0", bot={"name": "b", "version": "1"}, x_note="ignored")


def test_hello_ok_is_read_leniently() -> None:
    hello = AgentHelloOk.from_json({"response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "r-0",
                                    "bot": {"name": "b", "version": "1"}, "requires": {"observation": ["keywords"]}, "x": 1},
                                   request_id="r-0")
    assert hello.requires_observation == ("keywords",) and hello.requires_extensions == ()
    for bad in ({"bot": {"name": "", "version": "1"}}, {"bot": None}, {"request_id": "r-9"}):
        with pytest.raises(ValidationError):
            AgentHelloOk.from_json({"response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "r-0",
                                    "bot": {"name": "b", "version": "1"}, **bad}, request_id="r-0")


def test_choice_needs_only_the_candidate_id_and_keeps_echoes_raw() -> None:
    base = {"response_type": "choice", "protocol": "spellbench/v2", "request_id": "r-2"}
    assert Choice.from_json({**base, "selection": {"candidate_id": 1, "x_why": "tempo"}}, request_id="r-2").echoes == {}
    echoed = Choice.from_json({**base, "selection": {"candidate_id": 1, "seat_step": "3"}}, request_id="r-2")
    assert echoed.echoes == {"seat_step": "3"}
    for candidate_id in (-1, 1 << 40):              # any integer: the game loop judges the range (R2-16)
        assert Choice.from_json({**base, "selection": {"candidate_id": candidate_id}}, request_id="r-2").candidate_id == candidate_id
    for selection in ({"candidate_id": "1"}, {"candidate_id": True}, {}):
        with pytest.raises(ValidationError):
            Choice.from_json({**base, "selection": selection}, request_id="r-2")


def test_a_seat_failure_prints_its_cause_and_detail_only() -> None:
    failure = SeatFailure("timeout", "no answer to choose within 300 ms", diagnostic="Traceback: the bot's stderr")
    assert str(failure) == "timeout: no answer to choose within 300 ms"          # never the diagnostic (R2-15)
    assert pickle.loads(pickle.dumps(failure)).diagnostic == failure.diagnostic


def test_a_seat_failure_reprs_without_its_diagnostic_too() -> None:
    failure = SeatFailure("timeout", "no answer to choose within 300 ms", diagnostic="Traceback: the bot's stderr")
    assert "stderr" not in repr(failure)                                        # never the diagnostic, as with str()
    assert repr(failure) == "SeatFailure('timeout', 'no answer to choose within 300 ms')"


def test_the_agent_error_codes_are_a_closed_frozenset() -> None:
    assert isinstance(AGENT_ERROR_CODES, frozenset) and AGENT_ERROR_CODES == {
        "malformed_json", "malformed_request", "protocol_mismatch", "unknown_game", "game_already_active",
        "decision_pending", "internal_error"}


def test_request_ids_count_this_process_and_payloads_are_canonical() -> None:
    peer = ScriptedPeer([HELLO, _answer(response_type="ack", request_id="r-1"),
                         _answer(response_type="choice", request_id="r-2", selection={"candidate_id": 0})])
    agent = AgentProcess(peer=peer)
    agent.hello()
    agent.game_start({"game_id": "g-1", "seat": "p0"}, timeout_s=1)
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}], "acting_seat": "p0"}
    choice = agent.choose(choose_payload(game_id="g-1", seat_decision=decision, clock=Clock(remaining_ms=5, max_decision_ms=6)),
                          timeout_s=1)
    assert choice.candidate_id == 0
    assert [wire.strict_json_loads(line)["request_id"] for line in peer.sent] == ["r-0", "r-1", "r-2"]
    assert peer.sent[2] == wire.canonical_json_dumps(wire.strict_json_loads(peer.sent[2]))


@pytest.mark.parametrize(
    ("response", "cause"),
    [
        (PeerTimeoutError("slow"), "timeout"),
        (TransportError("gone"), "transport_error"),
        (b"Loading weights from /home/me/model.pt", "malformed_response"),
        (_answer(response_type="ack", request_id="r-1"), "malformed_response"),
        (_answer(response_type="choice", request_id="r-7", selection={"candidate_id": 0}), "malformed_response"),
        (_answer(response_type="error", request_id="r-1", error={"code": "internal_error", "message": "boom"}), "agent_error"),
    ],
)
def test_failures_map_to_forfeit_causes_without_quoting_the_peer(response, cause: str) -> None:
    agent = AgentProcess(peer=ScriptedPeer([HELLO, response]))
    agent.hello()
    with pytest.raises(SeatFailure) as caught:
        agent.choose({"game_id": "g-1", "decision": {}, "clock": {}}, timeout_s=1)
    assert caught.value.cause == cause
    assert "weights" not in caught.value.detail and "boom" not in caught.value.detail


def test_a_bot_that_logs_to_stdout_before_hello_is_malformed_and_never_hangs(tmp_path) -> None:
    script = tmp_path / "noisy.py"
    script.write_text("import sys, time\nprint('Loading model...', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    agent = AgentProcess([sys.executable, str(script)], startup_timeout_s=30)
    started = time.monotonic()
    with pytest.raises(SeatFailure) as caught:
        agent.hello()
    agent.close()
    assert caught.value.cause == "malformed_response" and "Loading" not in caught.value.detail
    assert time.monotonic() - started < 20


def test_a_real_bot_that_never_reads_its_stdin_times_out_on_a_big_write() -> None:
    # A real child process, not a mock: it never touches stdin, so a payload bigger than
    # any OS pipe buffer (about 4 KiB on Windows, 64 KiB on Linux) blocks the write until
    # SubprocessPeer kills it (R2-5). choose_payload's seat_decision is padded well past that.
    agent = AgentProcess([sys.executable, "-c", "import time; time.sleep(60)"], startup_timeout_s=30)
    huge = choose_payload(
        game_id="g-1", seat_decision={"padding": "x" * (4 * 1024 * 1024)}, clock=Clock(remaining_ms=1, max_decision_ms=1)
    )
    before = {t.ident for t in threading.enumerate()}
    started = time.monotonic()
    with pytest.raises(SeatFailure) as caught:
        agent.choose(huge, timeout_s=2)
    elapsed = time.monotonic() - started
    assert caught.value.cause == "timeout"
    assert elapsed < 4                                                     # within twice the 2 s timeout
    peer = agent._peer
    assert isinstance(peer, wire.SubprocessPeer) and peer._proc.poll() is not None    # the child is dead
    time.sleep(0.2)                                                        # let a just-finished writer thread drop out
    assert {t.ident for t in threading.enumerate()} <= before              # no helper thread left alive
    agent.close()


def test_the_bot_process_runs_with_the_environment_it_is_given(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SPELLBENCH_SECRETS_DIR", str(tmp_path / "secrets"))
    script = tmp_path / "env_bot.py"
    script.write_text(
        "import json, os, sys\n"
        "request = json.loads(sys.stdin.buffer.readline())\n"
        "name = 'leaky' if 'SPELLBENCH_SECRETS_DIR' in os.environ else 'clean'\n"
        "reply = {'response_type': 'hello_ok', 'protocol': 'spellbench/v2', 'request_id': request['request_id'],\n"
        "         'bot': {'name': name, 'version': '1'}}\n"
        "sys.stdout.write(json.dumps(reply) + '\\n')\n"
        "sys.stdout.flush()\n", encoding="utf-8")
    names = []
    for env in (None, {key: value for key, value in os.environ.items() if not key.startswith("SPELLBENCH_")}):
        agent = AgentProcess([sys.executable, str(script)], startup_timeout_s=30, env=env)
        try:
            names.append(agent.hello().bot.name)
        finally:
            agent.close()
    assert names == ["leaky", "clean"]                                            # R3-9


# Shared example values (spec 9.1/9.2 style, matching test_messages.py's own constants).
_DOMAIN = {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697",
           "names": ["Lightning Bolt", "Mountain"]}
_BURN_ID = "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2"
_RULES = Rules.from_json({"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
                          "starting_seat": "p0", "card_name_domain": _DOMAIN, "extensions": [], "probe": False})
_WIRE_DECK = WireDeck(deck_id=_BURN_ID, catalog_id="Burn")
_OWN_DECK = OwnDeck.from_json({"deck_id": _BURN_ID, "name": "Burn",
                               "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]})
_TIME_CONTROL = TimeControl(startup_ms=1, game_start_ms=1, bank_ms=1, increment_ms=0, max_decision_ms=1, engine_step_ms=1)
_LIMITS = Limits(max_decisions=10, max_steps=10, max_seat_decisions_per_turn=1,
                  max_seat_decisions_per_game=1, max_seat_steps_per_game=1)
_RESOURCES = Resources(cpus=1, memory_mb=1, gpu=False, engine_cpus=1)


def test_bot_identity_holds_name_and_version() -> None:
    identity = BotIdentity("uniform", "2.0.0")
    assert (identity.name, identity.version) == ("uniform", "2.0.0")


def test_own_deck_strict_round_trip_and_rejects_a_bad_deck_id() -> None:
    raw = {"deck_id": _BURN_ID, "name": "Burn",
           "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]}
    assert OwnDeck.from_json(raw).to_json() == raw
    with pytest.raises(ValidationError):
        OwnDeck.from_json({**raw, "deck_id": "not-a-sha256-digest"})


def test_agent_terminal_allows_forfeit_and_checks_the_winner_pairing() -> None:
    natural = AgentTerminal.from_json({"outcome": "p0_win", "classification": "natural", "winner": "p0",
                                       "reason": "p1_life_zero", "seat_step_count": 4})
    assert natural.to_json()["winner"] == "p0"
    forfeit = AgentTerminal.from_json({"outcome": "p1_win", "classification": "forfeit", "winner": "p1",
                                       "reason": "forfeit:timeout", "seat_step_count": 2})
    assert forfeit.classification == "forfeit"
    with pytest.raises(ValidationError):        # spec 11.5: winner must match the outcome's winning seat
        AgentTerminal.from_json({"outcome": "p1_win", "classification": "forfeit", "winner": "p0",
                                 "reason": "forfeit:timeout", "seat_step_count": 2})


class _Stub:
    """A minimal stand-in for a message object: only the ``to_json()`` the payload builders call."""

    def __init__(self, value) -> None:
        self._value = value

    def to_json(self):
        return self._value


def test_game_start_payload_matches_spec_shape() -> None:
    payload = game_start_payload(
        game_id="g-1", seat="p0", format="pauper-bo1",
        own_deck=_Stub({"deck_id": _BURN_ID, "name": "Burn", "decklist": []}), opponent_deck=None,
        rules=_Stub({"r": 1}), engine=_Stub({"e": 1}), engine_profile=_Stub({"p": 1}),
        time_control=_Stub({"t": 1}), limits=_Stub({"l": 1}), resources=_Stub({"res": 1}), agent_seed=42,
    )
    assert set(payload) == {"game_id", "seat", "format", "own_deck", "opponent_deck", "rules", "engine",
                            "engine_profile", "time_control", "limits", "resources", "agent_seed"}
    assert payload["game_id"] == "g-1" and payload["opponent_deck"] is None and payload["agent_seed"] == 42
    assert payload["own_deck"] == {"deck_id": _BURN_ID, "name": "Burn", "decklist": []}


def test_game_over_payload_matches_spec_shape() -> None:
    terminal = AgentTerminal.from_json({"outcome": "p0_win", "classification": "natural", "winner": "p0",
                                        "reason": "p1_life_zero", "seat_step_count": 4})
    assert game_over_payload(game_id="g-1", terminal=terminal) == {"game_id": "g-1", "terminal": terminal.to_json()}


def test_game_setup_never_reprs_its_secret() -> None:
    secret = "ab" * 32
    setup = GameSetup(
        game_index=0,
        game_id="g-1",
        game_secret_hex=secret,
        format="pauper-bo1",
        wire_decks=(_WIRE_DECK, _WIRE_DECK),
        own_decks=(_OWN_DECK, _OWN_DECK),
        rules=_RULES,
        time_control=_TIME_CONTROL,
        limits=_LIMITS,
        resources=_RESOURCES,
        agent_seeds=(1, 2),
    )
    assert secret not in repr(setup) and "game_secret_hex" not in repr(setup)
