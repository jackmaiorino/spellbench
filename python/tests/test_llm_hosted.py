"""The hosted entry point reaches the reference arena without live inference."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spellbench import wire
from spellbench.arena.config import BotSpec, TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.bench.definition import load_benchmark
from spellbench.llm import hosted
from spellbench.llm.broker import BrokerSession, RPC, serve_broker
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import BudgetedProvider, RunBudget, check_hosted_budgets
from test_llm_run_budget import PROMPT, Provider
from spellbench.run_secret import RunSecret
from spellbench.errors import TransportError
from test_llm_agent import decision


@pytest.mark.parametrize("result", ["forced", "legal", "illegal", "timeout"])
def test_trusted_real_child_preserves_choices_accounting_and_cleanup(tmp_path, monkeypatch, result):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=80000, wall_seconds=60,
                     allow_timeout_forfeits=True)
    provider = Provider(ProviderError("timeout") if result == "timeout" else
                        Completion('{"candidate_id":' + ("999" if result == "illegal" else "1") + '}',
                                   "luna", 100, 20))
    monkeypatch.setattr(hosted, "PlanProvider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(hosted, "DockerPeer", lambda *args: pytest.fail("trusted mode launched Docker"))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("RUNPOD_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("SPELLBENCH_PRIVATE", "must-not-reach-child")
    children, environments = [], []
    original = wire.SubprocessPeer
    def child(command, **kwargs):
        environments.append(kwargs["env"])
        peer = original(command, **kwargs)
        children.append(peer)
        return peer
    monkeypatch.setattr(wire, "SubprocessPeer", child)
    incoming = io.BytesIO(b"".join(wire.canonical_json_line(message) for message in [
        {"protocol": "spellbench/v2", "request_type": "hello", "request_id": "h-1"},
        {"protocol": "spellbench/v2", "request_type": "game_start", "request_id": "g-1",
         "game_id": "g", "seat": "p0", "agent_seed": 1,
         "own_deck": {"decklist": [{"count": 4, "name": "Lightning Bolt"}]}},
        {"protocol": "spellbench/v2", "request_type": "choose", "request_id": "c-1",
         **decision(forced=result == "forced").raw},
    ]))
    output = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": incoming})())
    monkeypatch.setattr(sys, "stdout", type("Output", (), {"buffer": output})())
    monkeypatch.setattr(sys, "argv", ["hosted", "--model", "luna", "--trusted-agent-process",
                                    "--run-budget", str(path), "--log-dir", str(tmp_path / "logs"),
                                    "--max-run-requests", "8", "--max-run-tokens", "80000",
                                    "--max-run-wall-seconds", "60", "--allow-timeout-forfeits"])
    assert hosted.main() == (1 if result in {"illegal", "timeout"} else 0)
    responses = [wire.strict_json_loads(line) for line in output.getvalue().splitlines()]
    assert responses[0]["response_type"] == "hello_ok"
    assert responses[-1]["response_type"] == ("error" if result in {"illegal", "timeout"} else "choice")
    assert provider.calls == (0 if result == "forced" else 1)
    assert children[0]._proc.poll() is not None
    assert not any(key in environments[0] for key in ("OPENAI_API_KEY", "RUNPOD_API_KEY", "SPELLBENCH_PRIVATE"))
    summary = RunBudget(path, model="luna").summary()
    assert summary["requests"] == provider.calls
    assert summary["pending"] == 0
    assert summary["policy"]["terminal_error"] == ("hosted_broker_failed" if result == "illegal" else None)
    assert summary["unknown_usage"] == (1 if result == "timeout" else 0)
    events = [json.loads(line) for line in next((tmp_path / "logs").glob("broker-*.jsonl")).read_text().splitlines()]
    assert events[0]["provider"]["transport"] == "trusted-chatgpt-plan"
    assert events[0]["provider"]["image_id"] is None


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


@pytest.mark.parametrize("allow_timeout_forfeits", [False, True])
def test_hello_needs_no_profile_or_model_call_and_removes_child(tmp_path, monkeypatch, allow_timeout_forfeits):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=60,
                     allow_timeout_forfeits=allow_timeout_forfeits)
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
                                    "--max-run-wall-seconds", "60"] +
                        (["--allow-timeout-forfeits"] if allow_timeout_forfeits else []))
    assert hosted.main() == 0
    assert wire.strict_json_loads(output_stream.getvalue())["request_id"] == "h-1"
    assert children[0].closed
    assert "--broker-stdio" in children[0].command
    assert "--credentials" not in children[0].command and str(path) not in children[0].command
    assert "--allow-timeout-forfeits" not in children[0].command
    assert RunBudget(path, model="luna").summary()["requests"] == 0


def test_log_cap_is_checked_before_writing():
    stream = io.StringIO()
    log = hosted.BoundedLog(stream, limit=4)
    log.write("é")
    with pytest.raises(OSError):
        log.write("abc")
    assert stream.getvalue() == "é"


def test_explicit_profile_renewal_is_before_game_start_and_makes_no_inference(tmp_path, monkeypatch):
    calls = []
    def renew(path, budget):
        calls.append("refresh")

    monkeypatch.setattr(hosted, "renew_profile", renew)
    monkeypatch.setattr(hosted, "load_credentials", lambda path:
                        {"access_token": "host-only-token", "expires_at": 9999999999})
    monkeypatch.setattr(hosted, "ChatGptProvider", lambda config: calls.append("configure") or object())
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=60)
    budget = RunBudget(path, model="luna")
    plan = hosted.PlanProvider("luna", Path("host.credentials"), "low", budget=budget)
    plan.renew_before_game()
    assert calls == ["refresh", "configure"]
    assert plan.provider is not None
    assert budget.summary()["policy"]["terminal_error"] is None
    assert budget.summary()["requests"] == 0


@pytest.mark.parametrize("failure", [ProviderError("browser_sign_in_required"),
                                     RuntimeError("private renewal details")])
def test_hosted_renewal_failure_stops_all_workers_and_the_next_phase(tmp_path, monkeypatch, failure):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=4096, tokens=10_000_000, wall_seconds=7200)
    source = io.BytesIO(wire.canonical_json_line(
        {"protocol": "spellbench/v2", "request_type": "game_start", "request_id": "g-1", "game_id": "g"}))
    children = []

    def child(image, command):
        result = Peer(image, command)
        children.append(result)
        return result

    def renew(path, budget):
        assert children[0].raw is None
        raise failure

    monkeypatch.setattr(hosted, "DockerPeer", child)
    monkeypatch.setattr(hosted, "renew_profile", renew)
    monkeypatch.setattr(hosted, "ChatGptProvider", lambda *args: pytest.fail("renewal failure sent inference"))
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": source})())
    monkeypatch.setattr(sys, "stdout", type("Output", (), {"buffer": io.BytesIO()})())
    monkeypatch.setattr(sys, "argv", ["hosted", "--model", "luna", "--image", "sha256:" + "a" * 64,
                                    "--run-budget", str(path), "--log-dir", str(tmp_path / "logs"),
                                    "--renew-profile-before-game"])
    assert hosted.main() == 2
    assert children[0].closed and children[0].raw is None
    budget = RunBudget(path, model="luna")
    summary = budget.summary()
    assert summary["policy"]["terminal_error"] == "profile_renewal_failed"
    assert summary["requests"] == summary["unknown_usage"] == 0
    assert summary["reported_input_tokens"] == summary["reported_output_tokens"] == 0
    assert "private renewal details" not in json.dumps(summary)
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        budget.reserve(PROMPT, output_tokens=1024)
    bot = BotSpec("luna", "0.1", "subprocess", command=("python", "llm_hosted_bot.py", "--model", "luna",
                                                         "--run-budget=" + str(path)))
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        check_hosted_budgets(SimpleNamespace(bots=(bot,)), allow_pending=True)


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
    assert "gpt-6-luna" in luna.command and "--run-budget=${SPELLBENCH_LLM_RUN_BUDGET}" in luna.command
    assert config.workers == 4 and config.stats_seed == 20261001


@pytest.mark.parametrize("policy_flag,command_flag", [(True, False), (False, True)])
def test_hosted_refuses_timeout_policy_mismatch_before_creating_child(tmp_path, monkeypatch, policy_flag, command_flag):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=60,
                     allow_timeout_forfeits=policy_flag)
    monkeypatch.setattr(hosted, "DockerPeer", lambda *args: pytest.fail("mismatched policy created child"))
    monkeypatch.setattr(hosted, "load_credentials", lambda *args: pytest.fail("mismatched policy read credentials"))
    monkeypatch.setattr(sys, "argv", ["hosted", "--model", "luna", "--image", "sha256:" + "a" * 64,
                                    "--run-budget", str(path), "--log-dir", str(tmp_path / "logs"),
                                    "--max-run-requests", "8", "--max-run-tokens", "8000",
                                    "--max-run-wall-seconds", "60"] +
                        (["--allow-timeout-forfeits"] if command_flag else []))
    assert hosted.main() == 2
    assert RunBudget(path, model="luna").summary()["requests"] == 0


def test_launcher_accepts_only_bound_timeout_policy_and_keeps_failed_usage(tmp_path):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=4096, tokens=10_000_000, wall_seconds=7200,
                     allow_timeout_forfeits=True)
    state = RunBudget(path, model="luna")
    provider = Provider(ProviderError("timeout"))
    with pytest.raises(ProviderError, match="timeout"):
        BudgetedProvider(provider, state).complete(PROMPT, timeout_s=2)
    command = ("python", "llm_hosted_bot.py", "--model", "luna", "--run-budget=" + str(path))
    def config(extra=()):
        return SimpleNamespace(bots=(BotSpec("luna", "0.1", "subprocess", command=command + extra),))
    with pytest.raises(ProviderError, match="run_budget_limits_mismatch"):
        check_hosted_budgets(config())
    check_hosted_budgets(config(("--allow-timeout-forfeits",)))
    for extra in [("--allow-timeout-forfeits", "--allow-timeout-forfeits"),
                  ("--allow-timeout-forfeits=true",), ("--allow-timeout-forfeits=false",)]:
        with pytest.raises(ProviderError, match="run_budget_ambiguous_command"):
            check_hosted_budgets(config(extra))
    other = Provider(Completion("{}", "luna", 100, 20))
    BudgetedProvider(other, state).complete(PROMPT, timeout_s=2)
    assert provider.calls == other.calls == 1
    assert state.summary()["unknown_usage"] == 1 and state.summary()["accounted_tokens"] == 1154


def test_plan_provider_cannot_renew_or_infer_again_after_timeout(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=60, allow_timeout_forfeits=True)
    state = RunBudget(path, model="luna")
    provider = Provider(ProviderError("timeout"))
    monkeypatch.setattr(hosted, "load_credentials", lambda path:
                        {"access_token": "host-only-token", "expires_at": 9999999999})
    monkeypatch.setattr(hosted, "ChatGptProvider", lambda config: provider)
    monkeypatch.setattr(hosted, "renew_profile", lambda *args: pytest.fail("failed game renewed its provider"))
    plan = hosted.PlanProvider("luna", Path("host.credentials"), "low", budget=state)
    with pytest.raises(ProviderError, match="timeout"):
        BudgetedProvider(plan, state).complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="provider_already_failed"):
        plan.complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="provider_already_failed"):
        plan.renew_before_game()
    state.check()
    assert provider.calls == 1 and state.summary()["requests"] == 1


@pytest.mark.parametrize("failure", ["candidate", "timeout", "old_timeout_then_transport", "timeout_log_cap", "docker"])
def test_hosted_failure_marks_budget_terminal_except_its_own_settled_timeout(tmp_path, monkeypatch, failure):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=60, allow_timeout_forfeits=True)
    state = RunBudget(path, model="luna")
    if failure == "old_timeout_then_transport":
        with pytest.raises(ProviderError, match="timeout"):
            BudgetedProvider(Provider(ProviderError("timeout")), state).complete(PROMPT, timeout_s=2)
    result = (ProviderError("timeout") if failure in {"timeout", "timeout_log_cap"}
              else Completion('{"candidate_id":999}', "luna", 100, 20))
    provider = Provider(result)
    children = []

    class InferencePeer(Peer):
        def read_line(self):
            if self.raw.get("request_type") == "choose":
                if failure == "old_timeout_then_transport":
                    raise TransportError("private child detail")
                return wire.canonical_json_line({"broker": RPC, "request_id": "i-1",
                                                 "messages": list(PROMPT.messages), "timeout_ms": 1000})
            return super().read_line()

    def child(image, command):
        if failure == "docker":
            raise TransportError("private Docker detail")
        value = InferencePeer(image, command)
        children.append(value)
        return value

    if failure == "timeout_log_cap":
        class FailingLog(hosted.BoundedLog):
            def write(self, value):
                if json.loads(value)["event"] == "inference":
                    raise OSError("log cap exhausted")
                return super().write(value)
        monkeypatch.setattr(hosted, "BoundedLog", FailingLog)
    monkeypatch.setattr(hosted, "DockerPeer", child)
    monkeypatch.setattr(hosted, "PlanProvider", lambda *args, **kwargs: provider)
    incoming = io.BytesIO(
        wire.canonical_json_line({"protocol": "spellbench/v2", "request_type": "game_start", "request_id": "g-1", "game_id": "g"})
        + wire.canonical_json_line({"protocol": "spellbench/v2", "request_type": "choose", "request_id": "c-1", **decision().raw}))
    output = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": incoming})())
    monkeypatch.setattr(sys, "stdout", type("Output", (), {"buffer": output})())
    monkeypatch.setattr(sys, "argv", ["hosted", "--model", "luna", "--image", "sha256:" + "a" * 64,
                                    "--run-budget", str(path), "--log-dir", str(tmp_path / "logs"),
                                    "--max-run-requests", "8", "--max-run-tokens", "8000",
                                    "--max-run-wall-seconds", "60", "--allow-timeout-forfeits"])
    assert hosted.main() == (2 if failure in {"timeout_log_cap", "docker"} else 1)
    assert all(value.closed for value in children)
    summary = state.summary()
    if failure == "timeout":
        assert summary["policy"]["terminal_error"] is None
        state.check()
    else:
        assert summary["policy"]["terminal_error"] == "hosted_broker_failed"
        with pytest.raises(ProviderError, match="run_budget_already_failed"):
            state.check()
    assert summary["requests"] == (0 if failure == "docker" else 1)
    assert summary["completed"] == int(failure == "candidate")
    assert summary["unknown_usage"] == int(failure in {"timeout", "old_timeout_then_transport", "timeout_log_cap"})
    assert provider.calls == int(failure in {"candidate", "timeout", "timeout_log_cap"})
