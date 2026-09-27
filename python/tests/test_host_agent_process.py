"""Agent-role messages and the host's agent client (spec 10)."""

from __future__ import annotations

import os
import pickle
import sys
import threading
import time

import pytest

from spellbench import wire
from spellbench.agent_messages import AGENT_ERROR_CODES, AgentHelloOk, Choice, Clock, OwnDeck, choose_payload
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


class DeafPeer(ScriptedPeer):
    """A peer whose writes block once the bot stops reading, like a full pipe."""

    def __init__(self, responses) -> None:
        super().__init__(responses)
        self.release = threading.Event()

    def write_line(self, data: bytes) -> None:
        if wire.strict_json_loads(data)["request_type"] == "choose":
            self.release.wait(30)
        super().write_line(data)


def test_a_write_to_a_bot_that_stopped_reading_times_out() -> None:
    peer = DeafPeer([HELLO])
    agent = AgentProcess(peer=peer)
    agent.hello()
    started = time.monotonic()
    with pytest.raises(SeatFailure) as caught:
        agent.choose({"game_id": "g-1", "decision": {}, "clock": {}}, timeout_s=0.5)
    assert caught.value.cause == "timeout" and time.monotonic() - started < 5      # the write is bounded too (R2-5)
    assert peer.closed                                                            # and the process is killed
    peer.release.set()


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


# R3-28 (controller ruling): GameSetup, and any other type holding a secret, sets repr=False
# on the secret field so it never reaches a log line or an error message.
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
