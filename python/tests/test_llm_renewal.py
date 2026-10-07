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
                assert timeout == 40
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


def test_real_renewal_child_uses_relocated_budget_without_authorization(tmp_path):
    from spellbench.llm.login import save_credentials
    from test_llm_login import record
    from test_llm_budget_transfer import transfer
    from test_llm_run_budget import budget as make_budget, failed_run_recovery, Provider, PROMPT
    from spellbench.llm.run_budget import BudgetedProvider
    parent = make_budget(tmp_path)
    with pytest.raises(ProviderError):
        BudgetedProvider(Provider(ProviderError("inference_failed")), parent).complete(PROMPT, timeout_s=30)
    source, _, _ = failed_run_recovery(parent, tmp_path / "successor.sqlite3", tmp_path, no_cutoff=True)
    relocated = transfer(tmp_path, source)
    profile = tmp_path / "profile.credentials"
    # A fresh synthetic profile returns before HTTP. This exercises the real
    # host subprocess and map/hash propagation, with no account or model use.
    save_credentials(profile, record())
    before = relocated.summary()
    renewal.renew_profile(profile, relocated)
    assert relocated.summary() == before
    assert relocated.summary()["requests"] == 1
