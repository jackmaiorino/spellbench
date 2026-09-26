from __future__ import annotations

import pytest

from spellbench.engine_client import EngineProcess
from spellbench.errors import EngineError, ProtocolError, TransportError
from spellbench.models import (
    Decision,
    EnvHelloOk,
    ErrorResponse,
    Group,
    Selection,
    Terminal,
    TerminalResult,
)

from conftest import TEST_ENGINE, TEST_PROVENANCE, ScriptedPeer, make_decision, payload


def hello_ok(request_id: str = "h-1") -> bytes:
    return payload(
        EnvHelloOk(
            request_id=request_id,
            engine=TEST_ENGINE,
            formats=("pauper-bo1",),
            decklists_as_data=True,
            extensions=(),
        ).to_json()
    )


def reset_kwargs() -> dict:
    return dict(
        game_id="g-0001",
        format="pauper-bo1",
        decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
        game_seed=12345,
        max_decisions=10000,
        max_steps=100000,
    )


def terminal(
    request_id: str,
    *,
    step_count: int = 2,
    decision_count: int = 2,
    game_id: str = "g-0001",
    halted: bool = False,
) -> bytes:
    return payload(
        Terminal(
            request_id=request_id,
            game_id=game_id,
            result=TerminalResult(
                outcome="halted" if halted else "p0_win",
                classification="halted" if halted else "natural",
                winner=None if halted else "p0",
                reason="engine_contract_failure" if halted else "p1_life_zero",
                step_count=step_count,
                decision_count=decision_count,
            ),
            provenance=TEST_PROVENANCE,
        ).to_json()
    )


def test_happy_path_two_decisions_then_terminal() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(make_decision("h-2", step=0).to_json()),
            payload(make_decision("h-3", step=1, acting_seat="p1").to_json()),
            terminal("h-4"),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        hello = engine.hello()
        assert hello.engine == TEST_ENGINE
        first = engine.reset(**reset_kwargs())
        assert isinstance(first, Decision)
        assert first.step == 0 and first.acting_seat == "p0"
        second = engine.step(0)
        assert isinstance(second, Decision)
        assert second.step == 1 and second.acting_seat == "p1"
        done = engine.step(0)
        assert isinstance(done, Terminal)
        assert done.result.outcome == "p0_win"
        assert done.result.step_count == 2
    assert peer.sent[0] == b'{"protocol":"spellbench/v1","request_id":"h-1","request_type":"hello"}'
    assert b'"request_id":"h-4"' in peer.sent[3]
    assert b'"expected_step":1' in peer.sent[3]
    assert peer.closed


def test_reset_before_hello_rejected_locally() -> None:
    with EngineProcess(peer=ScriptedPeer()) as engine:
        with pytest.raises(ProtocolError, match="before hello"):
            engine.reset(**reset_kwargs())


def test_step_without_decision_rejected_locally() -> None:
    peer = ScriptedPeer([hello_ok()])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(ProtocolError, match="without an active decision"):
            engine.step(0)


def test_double_hello_rejected_locally() -> None:
    peer = ScriptedPeer([hello_ok()])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(ProtocolError, match="already completed"):
            engine.hello()


def test_reset_twice_rejected_locally() -> None:
    peer = ScriptedPeer([hello_ok(), payload(make_decision("h-2", step=0).to_json())])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="already active"):
            engine.reset(**reset_kwargs())


def test_provenance_drift_detected() -> None:
    drifted = TEST_PROVENANCE.__class__(
        engine_name="test-engine",
        engine_version="0.1.0",
        rules_snapshot_id="rules-OTHER",
        card_pool_identity="pool-test",
    )
    peer = ScriptedPeer([hello_ok(), payload(make_decision("h-2", step=0, provenance=drifted).to_json())])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(ProtocolError, match="provenance drifted"):
            engine.reset(**reset_kwargs())


def test_step_sequence_drift_detected() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(make_decision("h-2", step=0).to_json()),
            payload(make_decision("h-3", step=5, acting_seat="p1").to_json()),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="step drift"):
            engine.step(0)


def test_group_id_must_advance_by_one() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(make_decision("h-2", step=0, group=Group(group_id=0, substep_index=0, substep_count=1)).to_json()),
            payload(
                make_decision("h-3", step=1, group=Group(group_id=2, substep_index=0, substep_count=1)).to_json()
            ),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="advance by exactly 1"):
            engine.step(0)


def test_multi_substep_group_contiguity() -> None:
    group = lambda i: Group(group_id=7, substep_index=i, substep_count=3)  # noqa: E731
    # reset starts a fresh game: the first group must be group 0.
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(
                make_decision("h-2", step=0, group=Group(group_id=0, substep_index=0, substep_count=3)).to_json()
            ),
            payload(make_decision("h-3", step=1, group=Group(group_id=0, substep_index=1, substep_count=3)).to_json()),
            payload(make_decision("h-4", step=2, group=Group(group_id=0, substep_index=2, substep_count=3)).to_json()),
            payload(make_decision("h-5", step=3, group=Group(group_id=1, substep_index=0, substep_count=1)).to_json()),
            terminal("h-6", step_count=4, decision_count=2),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        d0 = engine.reset(**reset_kwargs())
        assert isinstance(d0, Decision) and d0.group.substep_count == 3
        for _ in range(3):
            d = engine.step(0)
            assert isinstance(d, Decision)
        done = engine.step(0)
        assert isinstance(done, Terminal)
        assert done.result.decision_count == 2
    assert group(0).substep_count == 3


def test_group_substep_gap_detected() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(
                make_decision("h-2", step=0, group=Group(group_id=0, substep_index=0, substep_count=2)).to_json()
            ),
            payload(make_decision("h-3", step=1, group=Group(group_id=1, substep_index=0, substep_count=1)).to_json()),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="not contiguous and stable"):
            engine.step(0)


def test_terminal_interrupting_partial_group_detected() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(
                make_decision("h-2", step=0, group=Group(group_id=0, substep_index=0, substep_count=2)).to_json()
            ),
            terminal("h-3", step_count=1, decision_count=1),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="partial group"):
            engine.step(0)


def test_a_halted_terminal_may_end_a_partial_group() -> None:
    # Spec 8: an engine that cannot complete a group fails the whole game as
    # halted; the unfinished group is not a completed physical decision.
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(
                make_decision("h-2", step=0, group=Group(group_id=0, substep_index=0, substep_count=2)).to_json()
            ),
            terminal("h-3", step_count=1, decision_count=0, halted=True),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        done = engine.step(0)
        assert isinstance(done, Terminal)
        assert done.result.classification == "halted"


def test_terminal_decision_count_mismatch_detected() -> None:
    peer = ScriptedPeer(
        [hello_ok(), payload(make_decision("h-2", step=0).to_json()), terminal("h-3", step_count=1, decision_count=7)]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="decision_count mismatch"):
            engine.step(0)


def test_degenerate_terminal_from_reset() -> None:
    peer = ScriptedPeer([hello_ok(), terminal("h-2", step_count=0, decision_count=0)])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        done = engine.reset(**reset_kwargs())
        assert isinstance(done, Terminal)
        assert done.result.step_count == 0


def test_error_response_surfaces_code() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(
                ErrorResponse(
                    request_id="h-2", code="unsupported_format", message="no such format"
                ).to_json()
            ),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(EngineError) as excinfo:
            engine.reset(**reset_kwargs())
        assert excinfo.value.code == "unsupported_format"


def test_error_response_unknown_code_is_protocol_error() -> None:
    bad = {"response_type": "error", "protocol": "spellbench/v1", "request_id": "h-2", "error": {"code": "mystery", "message": "m"}}
    peer = ScriptedPeer([hello_ok(), payload(bad)])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(ProtocolError, match="invalid error response"):
            engine.reset(**reset_kwargs())


def test_response_request_id_mismatch_detected() -> None:
    peer = ScriptedPeer([hello_ok("h-zzz")])
    with EngineProcess(peer=peer) as engine:
        with pytest.raises(ProtocolError, match="request_id mismatch"):
            engine.hello()


def test_step_selection_validated_locally() -> None:
    peer = ScriptedPeer([hello_ok(), payload(make_decision("h-2", step=0).to_json())])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        with pytest.raises(ProtocolError, match="outside the current candidate list"):
            engine.step(3)
        with pytest.raises(ProtocolError, match="semantic_echo does not match"):
            engine.step(Selection(candidate_id=0, semantic_echo={"kind": "choose_optional_cost_use", "use_cost": True}))


def test_idempotent_retry_completed_exchange() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(make_decision("h-2", step=0).to_json()),
            payload(make_decision("h-3", step=1, acting_seat="p1").to_json()),
            payload(make_decision("h-3", step=1, acting_seat="p1").to_json()),  # replayed response
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        first = engine.step(0)
        replayed = engine.retry_last()
        assert replayed == first
        assert peer.sent[2] == peer.sent[3]  # byte-identical retransmission


def test_idempotent_retry_mismatched_response_detected() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(make_decision("h-2", step=0).to_json()),
            payload(make_decision("h-3", step=1, acting_seat="p1").to_json()),
            payload(make_decision("h-3", step=1, acting_seat="p0").to_json()),  # wrong replay
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**reset_kwargs())
        engine.step(0)
        with pytest.raises(ProtocolError, match="different response"):
            engine.retry_last()


def test_idempotent_retry_after_lost_response() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            TransportError("response lost in flight"),
            payload(make_decision("h-2", step=0).to_json()),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(TransportError):
            engine.reset(**reset_kwargs())
        decision = engine.retry_last()
        assert isinstance(decision, Decision)
        assert decision.step == 0
        assert peer.sent[1] == peer.sent[2]  # byte-identical retransmission


def test_retry_without_history_rejected() -> None:
    with EngineProcess(peer=ScriptedPeer()) as engine:
        with pytest.raises(ProtocolError, match="no request to retry"):
            engine.retry_last()


def test_duplicate_request_id_rejected_locally() -> None:
    peer = ScriptedPeer([hello_ok()])
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        from spellbench.models import ResetRequest, SeatDeck, Deck

        dupe = ResetRequest(
            request_id="h-1",
            game_id="g-2",
            format="pauper-bo1",
            seats=(SeatDeck(seat="p0", deck=Deck(catalog_id="Burn")), SeatDeck(seat="p1", deck=Deck(catalog_id="Burn"))),
            game_seed=1,
            max_decisions=1,
            max_steps=1,
        )
        with pytest.raises(ProtocolError, match="already used"):
            engine.reset(dupe)


def test_error_retry_reraises_remote_error() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(ErrorResponse(request_id="h-2", code="unsupported_format", message="nope").to_json()),
            payload(ErrorResponse(request_id="h-2", code="unsupported_format", message="nope").to_json()),
        ]
    )
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        with pytest.raises(EngineError):
            engine.reset(**reset_kwargs())
        with pytest.raises(EngineError, match="unsupported_format"):
            engine.retry_last()


def test_new_game_after_terminal() -> None:
    peer = ScriptedPeer(
        [
            hello_ok(),
            payload(make_decision("h-2", step=0).to_json()),
            terminal("h-3", step_count=1, decision_count=1),
            payload(make_decision("h-4", step=0, game_id="g-0002").to_json()),
            terminal("h-5", step_count=1, decision_count=1, game_id="g-0002"),
        ]
    )
    kwargs = reset_kwargs()
    with EngineProcess(peer=peer) as engine:
        engine.hello()
        engine.reset(**kwargs)
        done = engine.step(0)
        assert isinstance(done, Terminal)
        second = engine.reset(**{**kwargs, "game_id": "g-0002"})
        assert isinstance(second, Decision) and second.game_id == "g-0002"
        done2 = engine.step(0)
        assert isinstance(done2, Terminal)
