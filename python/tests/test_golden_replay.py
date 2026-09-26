"""Replay the golden transcripts byte-exactly in both roles (spec section 11)."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_client import AgentProcess
from spellbench.agent_server import serve
from spellbench.engine_client import EngineProcess
from spellbench.errors import AGENT_ERROR_CODES, ENGINE_ERROR_CODES, EngineError, ValidationError
from spellbench.models import (
    Ack,
    AgentHelloOk,
    Choice,
    ChooseRequest,
    Decision,
    EnvHelloOk,
    ErrorResponse,
    GameOverRequest,
    GameStartRequest,
    HelloRequest,
    ResetRequest,
    Selection,
    StepRequest,
    Terminal,
)

from conftest import GOLDENS_DIR, ScriptedPeer, load_transcript, payload

ENV_HAPPY = "env_happy_path.transcript.jsonl"
AGENT_HAPPY = "agent_happy_path.transcript.jsonl"
ERROR_GOLDENS = {
    "env_error_protocol_mismatch.transcript.jsonl": "protocol_mismatch",
    "env_error_expected_step_mismatch.transcript.jsonl": "expected_step_mismatch",
    "env_error_candidate_id_out_of_range.transcript.jsonl": "candidate_id_out_of_range",
    "env_error_semantic_echo_mismatch.transcript.jsonl": "semantic_echo_mismatch",
    "env_error_request_id_reuse_mismatch.transcript.jsonl": "request_id_reuse_mismatch",
}
ALL_GOLDENS = [ENV_HAPPY, AGENT_HAPPY, *ERROR_GOLDENS]

REQUEST_MODELS = {
    "hello": HelloRequest,
    "reset": ResetRequest,
    "step": StepRequest,
    "game_start": GameStartRequest,
    "choose": ChooseRequest,
    "game_over": GameOverRequest,
}


def validate_response(message: dict, direction: str) -> None:
    response_type = message["response_type"]
    if response_type == "hello_ok":
        if "engine" in message:
            EnvHelloOk.from_json(message)
        else:
            AgentHelloOk.from_json(message)
    elif response_type == "decision":
        Decision.from_json(message)
    elif response_type == "terminal":
        Terminal.from_json(message)
    elif response_type == "ack":
        Ack.from_json(message)
    elif response_type == "choice":
        Choice.from_json(message)
    elif response_type == "error":
        codes = ENGINE_ERROR_CODES if direction == "engine_to_host" else AGENT_ERROR_CODES
        ErrorResponse.from_json(message, codes=codes)
    else:  # pragma: no cover - guards the goldens themselves
        raise AssertionError(f"unexpected response_type in golden: {response_type}")


@pytest.mark.parametrize("name", ALL_GOLDENS)
def test_every_golden_message_validates(name: str) -> None:
    for _raw, direction, message in load_transcript(name):
        if direction in ("host_to_engine", "host_to_agent"):
            request_type = message.get("request_type")
            if name == "env_error_protocol_mismatch.transcript.jsonl":
                # The pinned violation: the request itself must fail validation.
                with pytest.raises(ValidationError):
                    REQUEST_MODELS[request_type].from_json(message)
            else:
                REQUEST_MODELS[request_type].from_json(message)
        else:
            validate_response(message, direction)


def test_generator_check_mode_passes() -> None:
    tool = Path(__file__).resolve().parents[1] / "tools" / "generate_protocol_goldens.py"
    result = subprocess.run([sys.executable, str(tool), "--check"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_golden_files_are_canonical_lines() -> None:
    for name in ALL_GOLDENS:
        raw = (GOLDENS_DIR / name).read_bytes()
        assert raw == b"".join(wire.canonical_json_line(wire.strict_json_loads(line)) + b"" for line in raw.splitlines())


def test_env_happy_path_byte_exact_client_replay() -> None:
    rows = load_transcript(ENV_HAPPY)
    requests = [message for _, direction, message in rows if direction == "host_to_engine"]
    responses = [payload(message) for _, direction, message in rows if direction == "engine_to_host"]
    peer = ScriptedPeer(responses)
    with EngineProcess(peer=peer) as engine:
        hello = engine.hello()
        assert hello.engine.name == "example-engine"
        first = engine.reset(ResetRequest.from_json(requests[1]))
        assert isinstance(first, Decision)
        assert first.step == 0
        second = engine.step(0)
        assert isinstance(second, Decision)
        assert second.step == 1
        done = engine.step(0)
        assert isinstance(done, Terminal)
        assert done.result.outcome == "p0_win"
        assert done.result.step_count == 2 and done.result.decision_count == 2
    assert peer.sent == [payload(message) for message in requests]


def test_agent_happy_path_byte_exact_client_replay() -> None:
    rows = load_transcript(AGENT_HAPPY)
    requests = [message for _, direction, message in rows if direction == "host_to_agent"]
    responses = [payload(message) for _, direction, message in rows if direction == "agent_to_host"]
    peer = ScriptedPeer(responses)
    with AgentProcess(peer=peer) as agent:
        hello = agent.hello()
        assert hello.bot.name == "uniform"
        agent.game_start(GameStartRequest.from_json(requests[1]))
        choose = ChooseRequest.from_json(requests[2])
        selection = agent.choose(choose.decision)
        assert selection == Selection(candidate_id=0, semantic_echo={"kind": "pass"})
        agent.game_over(GameOverRequest.from_json(requests[3]).terminal)
    assert peer.sent == [payload(message) for message in requests]


def test_agent_happy_path_byte_exact_server_replay() -> None:
    rows = load_transcript(AGENT_HAPPY)
    inbound = b"".join(
        wire.canonical_json_line(message) for _, direction, message in rows if direction == "host_to_agent"
    )
    expected = b"".join(
        wire.canonical_json_line(message) for _, direction, message in rows if direction == "agent_to_host"
    )
    stdout = io.BytesIO()
    code = serve(
        choose=lambda decision: 0,
        bot_name="uniform",
        bot_version="1.0.0",
        stdin=io.BytesIO(inbound),
        stdout=stdout,
    )
    assert code == 0
    assert stdout.getvalue() == expected


def test_choose_embeds_the_env_decision_verbatim() -> None:
    env_decision = [m for _, d, m in load_transcript(ENV_HAPPY) if d == "engine_to_host" and m["response_type"] == "decision"][0]
    choose = [m for _, d, m in load_transcript(AGENT_HAPPY) if d == "host_to_agent" and m["request_type"] == "choose"][0]
    assert choose["decision"] == env_decision


@pytest.mark.parametrize(
    "name,code",
    [(name, code) for name, code in ERROR_GOLDENS.items() if name != "env_error_request_id_reuse_mismatch.transcript.jsonl"],
)
def test_env_error_goldens_replay_through_client(name: str, code: str) -> None:
    rows = load_transcript(name)
    requests = [message for _, direction, message in rows if direction == "host_to_engine"]
    responses = [payload(message) for _, direction, message in rows if direction == "engine_to_host"]
    peer = ScriptedPeer(responses)
    with EngineProcess(peer=peer) as engine:
        with pytest.raises(EngineError) as excinfo:
            if code == "protocol_mismatch":
                engine.hello()
            else:
                engine.hello()
                engine.reset(ResetRequest.from_json(requests[1]))
                engine.step(0)
        assert excinfo.value.code == code


def test_request_id_reuse_mismatch_golden_validates() -> None:
    rows = load_transcript("env_error_request_id_reuse_mismatch.transcript.jsonl")
    error = rows[-1][2]
    parsed = ErrorResponse.from_json(error, codes=ENGINE_ERROR_CODES)
    assert parsed.code == "request_id_reuse_mismatch"
    request_ids = [m["request_id"] for _, d, m in rows if d == "host_to_engine"]
    assert request_ids == ["h-1", "h-1"]  # the pinned violation: same id, different payload
    assert rows[0][2] != rows[2][2]
