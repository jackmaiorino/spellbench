"""Broker capabilities and a real isolated-environment stdio child.

These tests exercise the pipe transport. They do not claim OS confinement;
the isolation wrapper remains the owner of container launch and teardown.
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

from spellbench import wire
from spellbench.llm.agent import AgentConfig
from spellbench.llm.broker import BrokerLimits, BrokerSession, RPC, StdioProvider, serve_broker
from spellbench.llm.prompt import render_prompt
from spellbench.llm.provider import ChatCompletionsProvider, Completion, ProviderConfig, ProviderError

from test_llm_agent import Provider, decision
from test_llm_http import endpoint  # shared loopback fixture, no external request


def host(kind, request_id="r", **fields):
    return {"request_type": kind, "request_id": request_id, "protocol": "spellbench/v2", **fields}


def ack(request_id="r"):
    return {"response_type": "ack", "protocol": "spellbench/v2", "request_id": request_id}


def rpc(**changes):
    return {"broker": RPC, "request_id": "i-0", "messages": list(render_prompt(decision()).messages),
            "timeout_ms": 1000, **changes}


class Peer:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = []
        self.closed = False

    def set_timeout(self, value):
        self.timeout = value

    def write_line(self, value):
        self.sent.append(wire.strict_json_loads(value))

    def read_line(self):
        return wire.canonical_json_line(self.responses.pop(0))

    def close(self):
        self.closed = True


def session(provider=None, config=AgentConfig(), limits=BrokerLimits()):
    peer, log = Peer([ack()]), io.StringIO()
    provider = provider or Provider()
    broker = BrokerSession(peer, provider, settings={"model": "fixed-host-model"},
                           max_completion_tokens=32, log=log, config=config, limits=limits)
    assert broker.exchange(host("game_start", game_id="g", seat="p0"))["response_type"] == "ack"
    return broker, peer, provider, log


def choose_request(request_id="r", forced=False):
    return host("choose", request_id, **decision(forced=forced).raw)


def choice(request_id="r"):
    return {"response_type": "choice", "protocol": "spellbench/v2", "request_id": request_id,
            "selection": {"candidate_id": 1}}


def events(log):
    return [json.loads(line) for line in log.getvalue().splitlines()]


def test_broker_forwards_one_inference_and_retains_host_owned_settings():
    broker, peer, provider, log = session()
    peer.responses = [rpc(), choice()]
    assert broker.exchange(choose_request()) == choice()
    assert len(provider.calls) == 1
    assert peer.sent[-1]["completion"]["model"] == "snapshot-model"
    assert events(log)[0]["provider"] == {"model": "fixed-host-model"}
    assert events(log)[-1]["tokens"] == 60


@pytest.mark.parametrize("extra", [{"base_url": "http://attacker"}, {"model": "other"}, {"api_key": "x"},
                                  {"max_completion_tokens": 999999}])
def test_child_cannot_choose_endpoint_model_key_or_generation_budget(extra):
    broker, peer, provider, log = session()
    peer.responses = [rpc(**extra)]
    answer = broker.exchange(choose_request())
    assert answer["response_type"] == "error" and not provider.calls
    assert events(log)[-1]["error"] == "invalid_inference_request"


@pytest.mark.parametrize("messages", [[], [{"role": {}, "content": "x"}],
                                       [{"role": "tool", "content": "x"}],
                                       [{"role": "user", "content": "x", "tool_calls": []}]])
def test_invalid_or_tool_messages_cannot_reach_provider(messages):
    broker, peer, provider, log = session()
    peer.responses = [rpc(messages=messages)]
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert not provider.calls


def test_one_call_per_decision_even_when_child_requests_more():
    broker, peer, provider, log = session()
    peer.responses = [rpc(), rpc(request_id="i-1")]
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert len(provider.calls) == 1
    assert events(log)[-1]["error"] == "inference_not_allowed"


@pytest.mark.parametrize("kind", ["hello", "game_over"])
def test_inference_cannot_run_outside_a_choose_request(kind):
    broker, peer, provider, log = session()
    peer.responses = [rpc()]
    assert broker.exchange(host(kind, game_id="g"))["response_type"] == "error"
    assert not provider.calls


def test_forced_decision_has_no_inference_capability():
    broker, peer, provider, log = session()
    peer.responses = [rpc()]
    assert broker.exchange(choose_request(forced=True))["response_type"] == "error"
    assert not provider.calls


def test_budget_is_reserved_by_host_before_inference():
    broker, peer, provider, log = session(config=AgentConfig(max_tokens_per_game=10))
    peer.responses = [rpc()]
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert not provider.calls
    assert events(log)[-1]["error"] == "token_budget_exhausted"


def test_connection_call_budget_survives_a_new_game():
    broker, peer, provider, log = session(limits=BrokerLimits(max_calls_total=1))
    peer.responses = [rpc(), choice(), ack("end"), ack("start"), rpc()]
    assert broker.exchange(choose_request())["response_type"] == "choice"
    assert broker.exchange(host("game_over", "end", game_id="g"))["response_type"] == "ack"
    assert broker.exchange(host("game_start", "start", game_id="g", seat="p0"))["response_type"] == "ack"
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert len(provider.calls) == 1
    assert events(log)[-1]["error"] == "call_budget_exhausted"


def test_unknown_usage_poison_cannot_be_cleared_by_game_start():
    broker, peer, provider, log = session(Provider(ProviderError("http_429")))
    peer.responses = [rpc()]
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert events(log)[-2]["unknown_usage"] is True
    assert broker.exchange(host("game_start", game_id="new"))["response_type"] == "error"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("result", [RuntimeError("secret-provider-detail"),
                                   Completion('{"candidate_id":1}', "test", True, 10)])
def test_unexpected_provider_fault_poison_is_logged_without_private_details(result):
    broker, peer, provider, log = session(Provider(result))
    peer.responses = [rpc()]
    answer = broker.exchange(choose_request())
    assert answer["response_type"] == "error"
    assert events(log)[-2]["unknown_usage"] is True
    assert "secret-provider-detail" not in json.dumps(answer) + log.getvalue()


def test_provider_illegal_candidate_is_not_sent_to_child():
    broker, peer, provider, log = session(Provider(Completion('{"candidate_id":999}', "test", 50, 10)))
    peer.responses = [rpc()]
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert "completion" not in peer.sent[-1]
    assert events(log)[-2]["unknown_usage"] is False


def test_stdio_provider_has_no_network_or_environment_dependency(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("child attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    reply = {"broker": RPC, "request_id": "i-0", "completion": {
        "content": '{"candidate_id":1}', "model": "host-model", "prompt_tokens": 10, "completion_tokens": 8}}
    output = io.BytesIO()
    provider = StdioProvider(stdin=io.BytesIO(wire.canonical_json_line(reply)), stdout=output)
    assert provider.complete(render_prompt(decision()), timeout_s=1).model == "host-model"
    sent = wire.strict_json_loads(output.getvalue())
    assert set(sent) == {"broker", "request_id", "messages", "timeout_ms"}


def test_stdio_provider_rejects_a_response_from_another_request():
    reply = {"broker": RPC, "request_id": "wrong"}
    provider = StdioProvider(stdin=io.BytesIO(wire.canonical_json_line(reply)), stdout=io.BytesIO())
    with pytest.raises(ProviderError, match="broker_response_mismatch"):
        provider.complete(render_prompt(decision()), timeout_s=1)


def test_real_stdio_child_uses_host_http_without_a_provider_key(endpoint, tmp_path):
    child_env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
    assert "OPENAI_API_KEY" not in child_env
    peer = wire.SubprocessPeer([sys.executable, "-m", "spellbench.llm", "--broker-stdio", "--model", "test-model",
                                "--log-dir", str(tmp_path)], env=child_env)
    settings = ProviderConfig(model="test-model", base_url=endpoint.url + "/v1", api_key="host-only-secret")
    log = io.StringIO()
    broker = BrokerSession(peer, ChatCompletionsProvider(settings), settings=settings.public_settings(),
                           max_completion_tokens=1024, log=log)
    try:
        assert broker.exchange(host("hello", "h", protocol_minor=0))["response_type"] == "hello_ok"
        assert broker.exchange(host("game_start", "s", game_id="g", seat="p0"))["response_type"] == "ack"
        assert broker.exchange(choose_request("c"))["selection"]["candidate_id"] == 1
        forced = broker.exchange(choose_request("f", forced=True))
        assert forced["selection"]["candidate_id"] == 0
        assert broker.exchange(host("game_over", "o", game_id="g", terminal={}))["response_type"] == "ack"
    finally:
        peer.close()
    assert len(endpoint.received) == 1
    assert endpoint.received[0]["authorization"] == "Bearer host-only-secret"
    assert "host-only-secret" not in log.getvalue()
    for path in tmp_path.glob("*.jsonl"):
        assert "host-only-secret" not in path.read_text(encoding="utf-8")


def test_serve_closes_transport_and_does_not_forward_internal_rpc_to_host():
    broker, peer, provider, log = session()
    peer.responses = [rpc(), choice()]
    output = io.BytesIO()
    assert serve_broker(broker, stdin=io.BytesIO(wire.canonical_json_line(choose_request())), stdout=output) == 0
    assert wire.strict_json_loads(output.getvalue()) == choice()
    assert peer.closed
