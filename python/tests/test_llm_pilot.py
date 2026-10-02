"""Live-pilot accounting stops on uncertain usage, model changes and fixed caps."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from spellbench.llm.prompt import Prompt
from spellbench.llm.provider import Completion, ProviderError

spec = importlib.util.spec_from_file_location("llm_pilot", Path(__file__).parents[1] / "tools/llm_plan_magic_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

PROMPT = Prompt(({"role": "user", "content": "choose"},), "a" * 64, 10)


class Provider:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def complete(self, prompt, *, timeout_s):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def budget(result, **changes):
    provider, log = Provider(result), io.StringIO()
    settings = {"model": "requested-model", "requests": 2, "tokens": 3000,
                "deadline": time.monotonic() + 10, **changes}
    return pilot.UsageBudget(provider, log=log, **settings), provider, log


def events(log):
    return [json.loads(line) for line in log.getvalue().splitlines()]


def test_attempt_is_journaled_and_actual_usage_limits_later_requests():
    state, provider, log = budget(Completion('{"candidate_id":0}', "requested-model", 1300, 15))
    state.complete(PROMPT, timeout_s=2)
    state.complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="pilot_budget_exhausted"):
        state.complete(PROMPT, timeout_s=2)
    assert state.calls == provider.calls == 2 and state.tokens == 2630 and state.unknown == 0
    assert [event["status"] for event in events(log)] == ["attempting", "completed", "attempting", "completed"]


def test_uncertain_request_poisoning_never_retries_or_understates_usage():
    state, provider, log = budget(ProviderError("interrupted_stream"))
    with pytest.raises(ProviderError, match="interrupted_stream"):
        state.complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="pilot_already_failed"):
        state.complete(PROMPT, timeout_s=2)
    assert state.calls == provider.calls == state.unknown == 1 and state.tokens == 0
    assert events(log)[-1]["unknown_usage"] and events(log)[-1]["error"] == "interrupted_stream"


@pytest.mark.parametrize("completion,code,known", [
    (Completion("{}", "substituted-model", 12, 5), "pilot_model_mismatch", 17),
    (Completion("{}", "requested-model", 3001, 5), "pilot_token_budget_exceeded", 3006),
    (Completion("{}", "requested-model", True, 5), "invalid_provider_usage", 0),
])
def test_failed_response_retains_available_usage_and_stops(completion, code, known):
    state, provider, log = budget(completion)
    with pytest.raises(ProviderError, match=code):
        state.complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="pilot_already_failed"):
        state.complete(PROMPT, timeout_s=2)
    assert provider.calls == 1 and state.tokens == known and state.unknown == int(known == 0)
    assert events(log)[-1]["error"] == code


@pytest.mark.parametrize("changes,code", [
    ({"tokens": 1033}, "pilot_budget_exhausted"),
    ({"deadline": time.monotonic() - 1}, "pilot_deadline_exhausted"),
])
def test_exhausted_budget_never_contacts_provider(changes, code):
    state, provider, log = budget(Completion("{}", "requested-model", 1, 1), **changes)
    with pytest.raises(ProviderError, match=code):
        state.complete(PROMPT, timeout_s=2)
    assert state.calls == provider.calls == 0 and not log.getvalue()


def test_shared_storage_cap_counts_utf8_before_writing():
    storage, first, second = pilot.StorageBudget(5), io.StringIO(), io.StringIO()
    storage.wrap(first).write("é")
    storage.wrap(second).write("abc")
    with pytest.raises(ProviderError, match="pilot_storage_budget_exhausted"):
        storage.wrap(first).write("x")
    assert storage.written == 5 and first.getvalue() == "é" and second.getvalue() == "abc"


def test_preflight_failure_survives_missing_docker_and_preserves_inputs(tmp_path, monkeypatch, capsys):
    command, engine = tmp_path / "command.json", tmp_path / "engine.json"
    command.write_text('["unlaunched-engine"]')
    engine.write_text('{"rules_snapshot_id":"pin","card_pool_identity":"pool"}')
    output = tmp_path / "receipt"
    monkeypatch.setattr(sys, "argv", ["pilot", "--model", "requested-model", "--image", "sha256:" + "a" * 64,
        "--engine-command", str(command), "--engine-manifest", str(engine), "--out", str(output)])
    monkeypatch.setattr(pilot.shutil, "disk_usage", lambda path: SimpleNamespace(free=120 * 2**30))

    def auth(*args, **kwargs):
        raise ProviderError("authorization_service_failed")

    original_run = pilot.subprocess.run

    def docker(argv, *args, **kwargs):
        if argv[0] == "docker":
            raise FileNotFoundError("docker")
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(pilot, "refresh_credentials", auth)
    monkeypatch.setattr(pilot.subprocess, "run", docker)
    assert pilot.main() == 2
    receipt = json.loads((output / "manifest.json").read_text())
    assert receipt["status"] == "failed" and receipt["error"] == "authorization_service_failed"
    assert not receipt["cleanup_verified"] and receipt["cleanup_error"] == "docker_unavailable"
    assert (output / "engine-command.json").read_bytes() == command.read_bytes()
    assert (output / "engine-manifest.json").read_bytes() == engine.read_bytes()
    assert json.loads(capsys.readouterr().out)["games"] == []
