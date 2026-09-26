from __future__ import annotations

import pytest

from spellbench.agent_client import AgentProcess
from spellbench.errors import AgentError, ProtocolError, TransportError
from spellbench.models import (
    AgentHelloOk,
    BotIdentity,
    Choice,
    ErrorResponse,
    Selection,
    TerminalResult,
)

from conftest import TEST_ENGINE, ScriptedPeer, make_decision, payload

BOT = BotIdentity(name="uniform", version="1.0.0")

TERMINAL = TerminalResult(
    outcome="p1_win",
    classification="natural",
    winner="p1",
    reason="p0_life_zero",
    step_count=2,
    decision_count=2,
)


def agent_hello_ok(request_id: str = "h-1") -> bytes:
    return payload(AgentHelloOk(request_id=request_id, bot=BOT, extensions_accepted=()).to_json())


def ack(request_id: str) -> bytes:
    return payload({"response_type": "ack", "protocol": "spellbench/v1", "request_id": request_id})


def choice(request_id: str, selection: Selection) -> bytes:
    return payload(Choice(request_id=request_id, selection=selection).to_json())


def game_start_kwargs() -> dict:
    return dict(
        game_id="g-0001",
        seat="p0",
        format="pauper-bo1",
        decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
        engine=TEST_ENGINE,
    )


def test_happy_path() -> None:
    decision = make_decision("h-2", step=0)
    peer = ScriptedPeer(
        [
            agent_hello_ok(),
            ack("h-2"),
            choice("h-3", Selection(candidate_id=0, semantic_echo={"kind": "pass"})),
            ack("h-4"),
        ]
    )
    with AgentProcess(peer=peer) as agent:
        hello = agent.hello()
        assert hello.bot == BOT
        agent.game_start(**game_start_kwargs())
        selection = agent.choose(decision)
        assert selection.candidate_id == 0
        assert selection.semantic_echo == {"kind": "pass"}
        agent.game_over(TERMINAL)
    assert peer.closed
    # The embedded decision is forwarded verbatim (canonical bytes).
    choose_line = peer.sent[2]
    assert b'"decision":{' in choose_line
    assert decision.to_json() == make_decision("h-2", step=0).to_json()


def test_choose_echo_mismatch_detected() -> None:
    decision = make_decision("h-2", step=0)
    peer = ScriptedPeer(
        [
            agent_hello_ok(),
            ack("h-2"),
            choice(
                "h-3",
                Selection(candidate_id=0, semantic_echo={"kind": "choose_optional_cost_use", "use_cost": True}),
            ),
        ]
    )
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        agent.game_start(**game_start_kwargs())
        with pytest.raises(ProtocolError, match="semantic_echo does not match"):
            agent.choose(decision)


def test_choose_out_of_range_detected() -> None:
    decision = make_decision("h-2", step=0)
    peer = ScriptedPeer(
        [
            agent_hello_ok(),
            ack("h-2"),
            choice("h-3", Selection(candidate_id=9, semantic_echo={"kind": "pass"})),
        ]
    )
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        agent.game_start(**game_start_kwargs())
        with pytest.raises(ProtocolError, match="outside the offered candidate list"):
            agent.choose(decision)


def test_choose_without_game_rejected_locally() -> None:
    peer = ScriptedPeer([agent_hello_ok()])
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        with pytest.raises(ProtocolError, match="without an active game"):
            agent.choose(make_decision("h-2", step=0))


def test_choose_game_id_mismatch_rejected_locally() -> None:
    peer = ScriptedPeer([agent_hello_ok(), ack("h-2")])
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        agent.game_start(**game_start_kwargs())
        with pytest.raises(ProtocolError, match="does not match the active game"):
            agent.choose(make_decision("h-2", step=0, game_id="g-other"))


def test_agent_error_code_surfaced() -> None:
    peer = ScriptedPeer(
        [
            agent_hello_ok(),
            payload(ErrorResponse(request_id="h-2", code="unknown_game", message="no such game").to_json()),
        ]
    )
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        with pytest.raises(AgentError) as excinfo:
            agent.game_start(**game_start_kwargs())
        assert excinfo.value.code == "unknown_game"


def test_ack_echo_mismatch_detected() -> None:
    peer = ScriptedPeer([agent_hello_ok(), ack("h-999")])
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        with pytest.raises(ProtocolError, match="request_id mismatch"):
            agent.game_start(**game_start_kwargs())


def test_unexpected_response_type_detected() -> None:
    peer = ScriptedPeer(
        [agent_hello_ok(), choice("h-2", Selection(candidate_id=0, semantic_echo={"kind": "pass"}))]
    )
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        with pytest.raises(ProtocolError, match="unexpected response_type"):
            agent.game_start(**game_start_kwargs())


def test_game_over_clears_game_and_allows_new_one() -> None:
    peer = ScriptedPeer([agent_hello_ok(), ack("h-2"), ack("h-3"), ack("h-4"), ack("h-5")])
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        agent.game_start(**game_start_kwargs())
        agent.game_over(TERMINAL)
        agent.game_start(**game_start_kwargs())
        agent.game_over(TERMINAL)


def test_idempotent_retry_on_choose() -> None:
    decision = make_decision("h-2", step=0)
    selection = Selection(candidate_id=0, semantic_echo={"kind": "pass"})
    peer = ScriptedPeer(
        [
            agent_hello_ok(),
            ack("h-2"),
            TransportError("lost"),
            choice("h-3", selection),
            choice("h-3", selection),
        ]
    )
    with AgentProcess(peer=peer) as agent:
        agent.hello()
        agent.game_start(**game_start_kwargs())
        with pytest.raises(TransportError):
            agent.choose(decision)
        retried = agent.retry_last()
        assert retried == selection
        again = agent.retry_last()
        assert again == selection
        assert peer.sent[2] == peer.sent[3] == peer.sent[4]
