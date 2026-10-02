"""Hard host authorization deadline and shared failure ordering, without live authorization."""

import subprocess

import pytest

from spellbench.llm import renewal
from spellbench.llm.provider import ProviderError
from spellbench.llm.run_budget import RunBudget


def test_slow_authorization_is_stopped_after_shared_failure(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=120)
    budget = RunBudget(path, model="luna")
    events = []

    class Child:
        killed = False

        def wait(self, timeout):
            if not self.killed:
                assert timeout == 50
                raise subprocess.TimeoutExpired("authorization", timeout)
            return -9

        def poll(self):
            return -9 if self.killed else None

        def kill(self):
            assert budget.summary()["policy"]["terminal_error"] == "profile_renewal_failed"
            self.killed = True
            events.append("killed")

    monkeypatch.setattr(renewal.subprocess, "Popen", lambda *args, **kwargs: Child())
    with pytest.raises(ProviderError, match="profile_renewal_failed"):
        renewal.renew_profile(tmp_path / "never-read.credentials", budget)
    assert events == ["killed"]
    assert budget.summary()["requests"] == 0


def test_failed_budget_is_checked_before_auth_in_the_profile_lock(tmp_path, monkeypatch):
    path = tmp_path / "budget.sqlite3"
    RunBudget.create(path, model="luna", requests=8, tokens=8000, wall_seconds=120)
    budget = RunBudget(path, model="luna")
    budget.fail("profile_renewal_failed")

    def refresh(path, **kwargs):
        assert kwargs["minimum_valid_seconds"] == 1800 and kwargs["lock_timeout_s"] == 35
        kwargs["before_refresh"]()
        pytest.fail("a failed run proceeded to authorization")

    monkeypatch.setattr(renewal, "refresh_credentials", refresh)
    monkeypatch.setattr(renewal.sys, "argv", ["renewal", "--credentials", "never-read.credentials",
                                             "--run-budget", str(path), "--model", "luna"])
    assert renewal.main() == 2
    assert budget.summary()["requests"] == 0
