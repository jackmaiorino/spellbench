"""The hosted entry point reaches the reference arena without live inference."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.arena.config import TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.bench.definition import load_benchmark
from spellbench.llm import hosted
from spellbench.llm.broker import BrokerSession, serve_broker
from spellbench.llm.provider import ProviderError
from spellbench.llm.run_budget import RunBudget
from spellbench.run_secret import RunSecret


class Peer:
    def __init__(self, image, command):
        self.image, self.command, self.closed = image, command, False
        self.name = "fake-child"
        self.raw = None

    def set_timeout(self, value):
        pass

    def write_line(self, raw):
        self.raw = wire.strict_json_loads(raw)

    def read_line(self):
        return wire.canonical_json_line({"protocol": "spellbench/v2", "request_id": self.raw["request_id"],
                                         "response_type": "ack"})

    def close(self):
        self.closed = True


def test_hello_needs_no_profile_or_model_call_and_removes_child(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=60)
    input_stream = io.BytesIO(wire.canonical_json_line(
        {"protocol": "spellbench/v2", "request_type": "hello", "request_id": "h-1"}))
    output_stream = io.BytesIO()
    children = []

    def child(image, command):
        result = Peer(image, command)
        children.append(result)
        return result

    monkeypatch.setattr(hosted, "DockerPeer", child)
    monkeypatch.setattr(hosted, "load_credentials", lambda *args: pytest.fail("hello read credentials"))
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": input_stream})())
    monkeypatch.setattr(sys, "stdout", type("Output", (), {"buffer": output_stream})())
    monkeypatch.setattr(sys, "argv", ["hosted", "--model", "luna", "--image", "sha256:" + "a" * 64,
                                    "--run-budget", str(path), "--log-dir", str(tmp_path / "logs"),
                                    "--max-run-requests", "8", "--max-run-tokens", "8000",
                                    "--max-run-wall-seconds", "60"])
    assert hosted.main() == 0
    assert wire.strict_json_loads(output_stream.getvalue())["request_id"] == "h-1"
    assert children[0].closed
    assert "--broker-stdio" in children[0].command
    assert "--credentials" not in children[0].command and str(path) not in children[0].command
    assert RunBudget(path, model="luna").summary()["requests"] == 0


def test_log_cap_is_checked_before_writing():
    stream = io.StringIO()
    log = hosted.BoundedLog(stream, limit=4)
    log.write("é")
    with pytest.raises(OSError):
        log.write("abc")
    assert stream.getvalue() == "é"


def test_explicit_profile_renewal_is_before_game_start_and_makes_no_inference(monkeypatch):
    calls = []
    monkeypatch.setattr(hosted, "refresh_credentials", lambda path: calls.append("refresh") or
                        {"access_token": "host-only-token", "expires_at": 9999999999})
    monkeypatch.setattr(hosted, "ChatGptProvider", lambda config: calls.append("configure") or object())
    plan = hosted.PlanProvider("luna", Path("host.credentials"), "low")
    plan.renew_before_game()
    assert calls == ["refresh", "configure"]
    assert plan.provider is not None


def test_stdio_renews_before_forwarding_game_start_and_closes_on_failure():
    message = {"protocol": "spellbench/v2", "request_type": "game_start", "request_id": "h-2", "game_id": "g"}
    source = io.BytesIO(wire.canonical_json_line(message))
    peer = Peer("image", [])
    session = BrokerSession(peer, None, settings={}, max_completion_tokens=1024, log=io.StringIO())

    def renew():
        assert peer.raw is None
        raise ProviderError("browser_sign_in_required")

    with pytest.raises(ProviderError, match="browser_sign_in_required"):
        serve_broker(session, stdin=source, stdout=io.BytesIO(), before_game_start=renew)
    assert peer.closed


def test_definition_has_complete_seat_swapped_schedule_and_fixed_settings():
    root = Path(__file__).parents[2]
    benchmark = load_benchmark(root / "benchmarks/standard-mirror-xmage")
    config = TournamentConfig.from_json(benchmark.tournament_config("out/test"))
    contexts = schedule(config, RunSecret.from_hex("a" * 64))
    assert len(contexts) == 48
    luna = next(bot for bot in config.bots if bot.name == "llm-gpt-6-luna")
    assert luna.owner == "jackmaiorino" and luna.type == "subprocess"
    luna_games = [game for game in contexts if any(bot.name == luna.name for _, bot in game.seat_specs)]
    assert len(luna_games) == 32
    for first, second in zip(contexts[::2], contexts[1::2]):
        assert [bot.name for _, bot in first.seat_specs] == [bot.name for _, bot in second.seat_specs][::-1]
        assert first.decks == second.decks
    assert "gpt-6-luna" in luna.command and "${SPELLBENCH_LLM_RUN_BUDGET}" in luna.command
    assert config.workers == 4 and config.stats_seed == 20261001
