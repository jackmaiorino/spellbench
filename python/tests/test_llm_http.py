"""Actual loopback HTTP and stdio processes; no external or paid requests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from spellbench import wire
from spellbench.host.agent_process import AgentProcess
from spellbench.llm.prompt import render_prompt
from spellbench.llm.provider import ChatCompletionsProvider, ProviderConfig, ProviderError

from test_llm_agent import decision


def response(content='{"candidate_id":1}', **changes):
    return {"id": "test-response", "model": "test-snapshot", "system_fingerprint": "fp-test",
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 8}, **changes}


@pytest.fixture
def endpoint():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.received.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                                         "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            time.sleep(self.server.delay)
            self.send_response(self.server.status)
            if self.server.status == 302:
                self.send_header("Location", self.server.url + "/redirect-target")
            self.end_headers()
            try:
                self.wfile.write(self.server.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.received, server.status, server.delay = [], 200, 0
    server.body = json.dumps(response()).encode()
    server.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def provider(endpoint):
    return ChatCompletionsProvider(ProviderConfig(model="test-model", base_url=endpoint.url + "/v1", api_key="test-secret"))


def test_http_request_uses_verified_api_shape_and_does_not_expose_key_in_settings(endpoint):
    client = provider(endpoint)
    result = client.complete(render_prompt(decision()), timeout_s=2)
    received = endpoint.received[0]
    assert received["path"] == "/v1/chat/completions"
    assert received["authorization"] == "Bearer test-secret"
    assert received["body"]["response_format"]["json_schema"]["strict"] is True
    assert received["body"]["max_completion_tokens"] == 1024
    assert "temperature" not in received["body"]
    assert result.model == "test-snapshot" and result.prompt_tokens == 100
    assert "test-secret" not in repr(client.config)
    assert "test-secret" not in json.dumps(client.config.public_settings())


@pytest.mark.parametrize("bad_url", ["http://example.com/v1", "https://key@example.com/v1", "https://example.com/v1?key=x"])
def test_unsafe_endpoint_configuration_is_rejected(bad_url):
    with pytest.raises(ValueError):
        ProviderConfig(model="test", base_url=bad_url)


@pytest.mark.parametrize("status", [401, 429, 503])
def test_http_failure_is_one_attempt_and_does_not_quote_error_body(endpoint, status):
    endpoint.status, endpoint.body = status, b"provider error with test-secret"
    with pytest.raises(ProviderError, match=f"http_{status}") as error:
        provider(endpoint).complete(render_prompt(decision()), timeout_s=2)
    assert len(endpoint.received) == 1
    assert "test-secret" not in str(error.value)


def test_redirect_does_not_reissue_authorized_request(endpoint):
    endpoint.status = 302
    with pytest.raises(ProviderError, match="redirect_rejected"):
        provider(endpoint).complete(render_prompt(decision()), timeout_s=2)
    assert len(endpoint.received) == 1


@pytest.mark.parametrize("body,code", [
    (b"not json", "invalid_response_or_usage"),
    (json.dumps(response(usage={})).encode(), "invalid_response_or_usage"),
    (json.dumps(response(usage={"prompt_tokens": True, "completion_tokens": 8})).encode(), "invalid_response_or_usage"),
    (json.dumps(response(choices=[{"finish_reason": "stop", "message": {"refusal": "no"}}])).encode(), "refusal"),
    (json.dumps(response(choices=[{"finish_reason": "length", "message": {"content": "{"}}])).encode(), "incomplete_response"),
])
def test_unusable_response_stops_inference(endpoint, body, code):
    endpoint.body = body
    with pytest.raises(ProviderError, match=code):
        provider(endpoint).complete(render_prompt(decision()), timeout_s=2)


def test_whole_exchange_has_a_deadline(endpoint):
    endpoint.delay = 0.3
    started = time.monotonic()
    with pytest.raises(ProviderError, match="timeout"):
        provider(endpoint).complete(render_prompt(decision()), timeout_s=0.03)
    assert time.monotonic() - started < 0.25


def command(endpoint, logs):
    return [sys.executable, "-m", "spellbench.llm", "--model", "test-model", "--base-url", endpoint.url + "/v1",
            "--api-key-env", "TEST_LLM_KEY", "--log-dir", str(logs)]


def test_real_v2_host_drives_agent_subprocess_and_logs_only_protocol_on_stdout(endpoint, tmp_path):
    env = {**os.environ, "TEST_LLM_KEY": "test-secret"}
    with AgentProcess(command(endpoint, tmp_path), startup_timeout_s=5, env=env) as client:
        hello = client.hello()
        assert hello.bot.name == "llm-test-model"
        client.game_start({"game_id": "g", "seat": "p0", "own_deck": None}, timeout_s=2)
        result = client.choose(decision().raw, timeout_s=3)
        assert result.candidate_id == 1
        result = client.choose(decision(forced=True).raw, timeout_s=3)
        assert result.candidate_id == 0
        client.game_over({"game_id": "g", "terminal": {}}, timeout_s=2)
    assert len(endpoint.received) == 1
    paths = list(tmp_path.glob("*.jsonl"))
    assert len(paths) == 1
    text = paths[0].read_text(encoding="utf-8")
    assert "test-secret" not in text
    events = [json.loads(line) for line in text.splitlines()]
    assert [event["event"] for event in events] == ["configuration", "game_start", "decision", "decision", "game_over"]
    assert events[2]["returned_model"] == "test-snapshot" and events[2]["tokens"] == 108


def test_protocol_error_and_next_game_do_not_call_a_heuristic_or_retry(endpoint, tmp_path):
    endpoint.body = json.dumps(response('{"candidate_id":99}')).encode()
    requests = [
        {"request_type": "hello", "protocol_minor": 0},
        {"request_type": "game_start", "game_id": "g", "seat": "p0"},
        {"request_type": "choose", **decision().raw},
        {"request_type": "choose", **decision(forced=True).raw},
        {"request_type": "game_over", "game_id": "g", "terminal": {}},
    ]
    data = b"".join(wire.canonical_json_line({"protocol": "spellbench/v2", "request_id": f"r{i}", **request})
                    for i, request in enumerate(requests))
    result = subprocess.run(command(endpoint, tmp_path), input=data, capture_output=True,
                            env={**os.environ, "TEST_LLM_KEY": "test-secret"}, timeout=10)
    assert result.returncode == 0 and not result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [reply["response_type"] for reply in replies] == ["hello_ok", "ack", "error", "error", "ack"]
    assert len(endpoint.received) == 1


def test_cli_missing_key_fails_before_handshake_without_creating_logs(endpoint, tmp_path):
    env = dict(os.environ)
    env.pop("TEST_LLM_KEY", None)
    result = subprocess.run(command(endpoint, tmp_path), input=b"", capture_output=True, env=env, timeout=5)
    assert result.returncode == 2 and not result.stdout
    assert not list(tmp_path.glob("*.jsonl")) and not endpoint.received


def test_complete_fake_engine_game_routes_llm_and_replays_same_digest(endpoint, tmp_path, monkeypatch):
    from spellbench.arena.config import BotSpec
    from spellbench.arena.drivers import SubprocessDriver
    from spellbench.host.game import play_game
    from test_host_game import Seat, real_engine, setup

    monkeypatch.setenv("TEST_LLM_KEY", "test-secret")
    spec = BotSpec(name="llm-test-model", version="0.1.0", type="subprocess", command=tuple(command(endpoint, tmp_path)))
    results = []
    for _ in range(2):
        engine = real_engine()
        seat = SubprocessDriver(spec, startup_ms=5000)
        try:
            results.append(play_game(setup(), engine=engine, seats={"p0": seat, "p1": Seat()}))
        finally:
            seat.close()
            engine.close()
    assert all(result.classification == "natural" and result.outcome == "p0_win" for result in results)
    assert results[0].game_digest == results[1].game_digest
    assert all(result.decisions_checked == 4 for result in results)
    assert len(endpoint.received) == 4
    assert len(list(tmp_path.glob("*.jsonl"))) == 2
