"""Actual SSE transport, offline Responses fixtures, no ChatGPT usage."""

from __future__ import annotations

import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("truststore")

from spellbench.llm.chatgpt import ChatGptConfig, ChatGptProvider, read_completion, request_body
from spellbench.llm.prompt import render_prompt
from spellbench.llm.provider import ProviderError

from test_llm_agent import Provider, agent, decision, events
from test_llm_broker import session, choose_request, rpc, events as broker_events
from spellbench.llm.provider import Completion


def completed(**changes):
    return {"id": "response-test", "model": "snapshot-test", "status": "completed",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": '{"candidate_id":1}'}]}],
            "usage": {"input_tokens": 50, "output_tokens": 10}, **changes}


def sse(*events):
    return b"".join(b"event: unused\ndata: " + json.dumps(event).encode() + b"\n\n" for event in events)


def test_subscription_request_contains_only_explicit_prompt_and_structured_choice():
    config = ChatGptConfig("gpt-6-luna", "secret")
    body = request_body(config, render_prompt(decision()))
    assert body["model"] == "gpt-6-luna" and body["store"] is False and body["stream"] is True
    assert [item["role"] for item in body["input"]] == ["developer", "user"]
    assert body["text"]["format"]["strict"] is True
    assert not {"tools", "previous_response_id", "max_output_tokens", "temperature", "metadata"} & body.keys()
    assert "MUST-NOT-REACH-MODEL" not in json.dumps(body)
    assert "secret" not in repr(config) and "secret" not in json.dumps(config.public_settings())


def test_completed_event_is_authoritative_and_deltas_never_select_a_choice():
    stream = sse({"type": "response.output_text.delta", "delta": '{"candidate_id":999}'},
                 {"type": "response.completed", "response": completed()})
    result = read_completion(io.BytesIO(stream))
    assert result.content == '{"candidate_id":1}' and result.completion_tokens == 10


@pytest.mark.parametrize("stream,code", [
    (sse({"type": "response.output_text.delta", "delta": '{"candidate_id":1}'}), "interrupted_stream"),
    (sse({"type": "response.output_text.delta", "delta": '{"candidate_id":1}'},
         {"type": "response.failed", "error": {"message": "secret"}}), "inference_failed"),
    (sse({"type": "response.incomplete"}), "incomplete_response"),
    (sse({"type": "error", "message": "secret"}), "inference_failed"),
    (b'data: {"type":"error","type":"response.completed"}\n\n', "invalid_stream_event"),
    (b'data: nope\n\n', "invalid_stream_event"),
    (sse({"type": "response.completed", "response": completed(usage={})}), "invalid_response_or_usage"),
    (sse({"type": "response.completed", "response": completed(usage={"input_tokens": True, "output_tokens": 1})}), "invalid_response_or_usage"),
    (sse({"type": "response.completed", "response": completed(output=[{"type": "function_call"}])}), "unexpected_response_item"),
    (sse({"type": "response.completed", "response": completed(output=[{"type": "message", "role": "assistant", "status": "completed",
           "content": [{"type": "refusal", "refusal": "secret"}]}])}), "refusal"),
    (b":" + b"x" * 1_048_576, "response_too_large"),
], ids=["partial-eof", "late-failure", "incomplete", "error", "duplicate", "not-json", "missing-usage",
        "boolean-usage", "tool-call", "refusal", "oversize"])
def test_bad_or_incomplete_stream_never_returns_partial_choice(stream, code):
    with pytest.raises(ProviderError, match=code) as failure:
        read_completion(io.BytesIO(stream))
    assert "secret" not in str(failure.value)


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
            self.send_header("Content-Type", self.server.content_type)
            self.end_headers()
            try:
                self.wfile.write(self.server.body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.received, server.status, server.delay, server.content_type = [], 200, 0, "text/event-stream"
    server.body = sse({"type": "response.completed", "response": completed()})
    server.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def provider(endpoint, **options):
    client = ChatGptProvider(ChatGptConfig("gpt-6-luna", "secret", **options))
    # Only this test replaces the fixed endpoint. There is no CLI override.
    client._endpoint = endpoint.url + "/v1/responses"
    return client


def test_actual_stream_request_and_usage(endpoint):
    result = provider(endpoint).complete(render_prompt(decision()), timeout_s=2)
    assert result.model == "snapshot-test" and result.response_id == "response-test"
    request = endpoint.received[0]
    assert request["path"] == "/v1/responses" and request["authorization"] == "Bearer secret"
    assert request["body"]["input"][0]["role"] == "developer"


@pytest.mark.parametrize("status,code", [(401, "http_401"), (429, "http_429"), (503, "http_503"), (302, "redirect_rejected")])
def test_transport_fault_is_one_attempt_and_poison_survives_later_calls(endpoint, status, code):
    endpoint.status, endpoint.body = status, b"secret error body"
    client = provider(endpoint)
    with pytest.raises(ProviderError, match=code):
        client.complete(render_prompt(decision()), timeout_s=2)
    with pytest.raises(ProviderError, match="provider_already_failed"):
        client.complete(render_prompt(decision()), timeout_s=2)
    assert len(endpoint.received) == 1


def test_deadline_covers_entire_stream(endpoint):
    endpoint.delay = 0.3
    client = provider(endpoint)
    started = time.monotonic()
    with pytest.raises(ProviderError, match="timeout"):
        client.complete(render_prompt(decision()), timeout_s=0.03)
    assert time.monotonic() - started < 0.2
    with pytest.raises(ProviderError, match="provider_already_failed"):
        client.complete(render_prompt(decision()), timeout_s=2)
    assert len(endpoint.received) == 1


def test_content_type_must_be_stream(endpoint):
    endpoint.content_type = "application/json"
    with pytest.raises(ProviderError, match="invalid_stream_content_type"):
        provider(endpoint).complete(render_prompt(decision()), timeout_s=2)


def test_expiring_credentials_are_rejected_before_any_request(endpoint):
    with pytest.raises(ProviderError, match="credentials_expired"):
        provider(endpoint, expires_at=time.time() + 30).complete(render_prompt(decision()), timeout_s=2)
    assert not endpoint.received


def test_agent_output_overrun_records_actual_usage_and_forfeits():
    bot, fake, log = agent(Provider(Completion('{"candidate_id":1}', "test", 50, 33)))
    with pytest.raises(ProviderError, match="output_token_limit_exceeded"):
        bot.choose(decision())
    assert events(log)[-1]["tokens"] == 83 and events(log)[-1]["unknown_usage"] is False
    with pytest.raises(ProviderError, match="game_already_failed"):
        bot.choose(decision(forced=True))
    assert len(fake.calls) == 1


def test_broker_output_overrun_records_actual_usage_and_poison():
    broker, peer, fake, log = session(Provider(Completion('{"candidate_id":1}', "test", 50, 33)))
    peer.responses = [rpc()]
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert broker_events(log)[-1]["error"] == "output_token_limit_exceeded"
    assert broker_events(log)[-2]["unknown_usage"] is False and broker_events(log)[-2]["completion_tokens"] == 33
    assert broker.exchange(choose_request())["response_type"] == "error"
    assert len(fake.calls) == 1
