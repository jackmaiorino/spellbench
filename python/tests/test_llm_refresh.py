"""App-owned grant renewal, identity retention and rotating-token serialization."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

jwt = pytest.importorskip("jwt")

from spellbench.llm import login
from spellbench.llm.provider import ProviderError
from test_llm_login import record, signing, token


def expired(path, signing):
    profile = record(id_token=token(signing), expires_at=time.time() - 60)
    login.save_credentials(path, profile)
    return profile


def response(signing, **changes):
    return {"access_token": "replacement-access", "refresh_token": "replacement-refresh", "token_type": "Bearer",
            "id_token": token(signing), "scope": "openid chatgpt.tokens.use.direct", "expires_in": 3600, **changes}


def endpoint(monkeypatch, signing, value):
    calls = []

    def request(url, form=None):
        calls.append((url, form))
        if url == login.JWKS_URL:
            return signing[1]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(login, "_json_request", request)
    return calls


def test_rotating_tokens_are_saved_together_with_verified_identity(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    previous = expired(path, signing)
    calls = endpoint(monkeypatch, signing, response(signing))
    renewed = login.refresh_credentials(path)
    assert login.load_credentials(path) == renewed
    assert renewed["subject"] == previous["subject"] and renewed["client_id"] == previous["client_id"]
    assert renewed["ext_agent_host_id"] == previous["ext_agent_host_id"]
    assert renewed["access_token"] == "replacement-access" and renewed["refresh_token"] == "replacement-refresh"
    assert renewed["expires_at"] > time.time() + 3500
    assert calls[0] == (login.TOKEN_URL, {"grant_type": "refresh_token", "client_id": "oaiapp_test",
                                         "refresh_token": "secret-refresh", "resource": login.BASE_URL})
    assert len(calls) == 2  # token grant and JWKS, no model request


def test_fresh_credentials_make_no_auth_or_model_requests(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    previous = record(id_token=token(signing))
    login.save_credentials(path, previous)
    calls = endpoint(monkeypatch, signing, None)
    assert login.refresh_credentials(path) == previous
    assert not calls


def test_refresh_can_omit_id_token_scopes_and_rotated_refresh_token(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    previous = expired(path, signing)
    value = {"access_token": "replacement-access", "token_type": "bearer", "expires_in": 3600}
    calls = endpoint(monkeypatch, signing, value)
    renewed = login.refresh_credentials(path)
    assert renewed["id_token"] == previous["id_token"] and renewed["scopes"] == previous["scopes"]
    assert renewed["refresh_token"] == previous["refresh_token"]
    assert len(calls) == 1


def test_refresh_id_token_may_omit_original_authorization_nonce(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    claims = jwt.decode(token(signing), options={"verify_signature": False})
    claims.pop("nonce")
    replacement = jwt.encode(claims, signing[0], algorithm="RS256", headers={"kid": "test-key"})
    endpoint(monkeypatch, signing, response(signing, id_token=replacement))
    assert login.refresh_credentials(path)["id_token"] == replacement


@pytest.mark.parametrize("change", ["subject", "audience", "nonce", "client", "scope", "expiry", "empty_refresh", "type"])
def test_bad_refresh_preserves_selected_profile(tmp_path, signing, monkeypatch, change):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    before = path.read_bytes()
    changes = {
        "subject": {"id_token": token(signing, sub="another-account")},
        "audience": {"id_token": token(signing, aud="oaiapp_other")},
        "nonce": {"id_token": token(signing, nonce="another-authorization")},
        "client": {"client_id": "oaiapp_other"}, "scope": {"scope": "openid"},
        "expiry": {"expires_in": True}, "empty_refresh": {"refresh_token": ""}, "type": {"token_type": "Basic"},
    }
    endpoint(monkeypatch, signing, response(signing, **changes[change]))
    with pytest.raises(ProviderError):
        login.refresh_credentials(path)
    assert path.read_bytes() == before


def test_uncertain_refresh_is_not_retried_and_does_not_overwrite_profile(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    before = path.read_bytes()
    calls = endpoint(monkeypatch, signing, ProviderError("authorization_service_failed"))
    with pytest.raises(ProviderError, match="authorization_service_failed"):
        login.refresh_credentials(path)
    assert len(calls) == 1 and path.read_bytes() == before


def test_rotating_session_lock_excludes_an_actual_second_process(tmp_path):
    path = tmp_path / "profile.credentials"
    code = '''
import sys
from pathlib import Path
from spellbench.llm.login import credential_lock
from spellbench.llm.provider import ProviderError
try:
    with credential_lock(Path(sys.argv[1])):
        print('acquired')
except ProviderError as error:
    print(error.code)
'''
    with login.credential_lock(path):
        result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0 and result.stdout.strip() == "credential_session_busy"
    result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == "acquired"


def test_four_waiting_workers_reload_the_winners_profile_without_auth(tmp_path, signing):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    code = '''
import sys
from pathlib import Path
from spellbench.llm import login
def unexpected_request(*args, **kwargs):
    raise AssertionError('waiter sent authorization')
login._json_request = unexpected_request
print('ready', flush=True)
profile = login.refresh_credentials(Path(sys.argv[1]), lock_timeout_s=10, minimum_valid_seconds=1800)
print(profile['access_token'], flush=True)
'''
    children = []
    try:
        with login.credential_lock(path):
            for _ in range(4):
                children.append(subprocess.Popen([sys.executable, "-u", "-c", code, str(path)],
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            for child in children:
                assert child.stdout.readline().strip() == "ready"
            # Simulate the winner's atomic persistence while all peers wait.
            login.save_credentials(path, record(id_token=token(signing), access_token="winner-access"))
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            assert stdout.strip() == "winner-access"
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_wait_timeout_does_not_request_auth_or_change_profile(tmp_path, signing):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    before = path.read_bytes()
    code = '''
import sys, time
from pathlib import Path
from spellbench.llm.login import refresh_credentials
from spellbench.llm.provider import ProviderError
start = time.monotonic()
try:
    refresh_credentials(Path(sys.argv[1]), lock_timeout_s=0.1)
except ProviderError as error:
    print(error.code)
    assert time.monotonic() - start < 2
'''
    with login.credential_lock(path):
        result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == "credential_session_busy"
    assert path.read_bytes() == before


def test_game_horizon_renews_a_profile_with_three_minutes_left(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    login.save_credentials(path, record(id_token=token(signing), expires_at=time.time() + 180))
    calls = endpoint(monkeypatch, signing, response(signing))
    assert login.refresh_credentials(path, minimum_valid_seconds=1800)["access_token"] == "replacement-access"
    assert len(calls) == 2


def test_short_grant_preserves_rotated_token_but_refuses_play(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    endpoint(monkeypatch, signing, response(signing, expires_in=900))
    with pytest.raises(ProviderError, match="credential_validity_too_short"):
        login.refresh_credentials(path, minimum_valid_seconds=1800)
    assert login.load_credentials(path)["refresh_token"] == "replacement-refresh"


def test_failure_is_recorded_while_holding_lock_and_waiters_refuse_auth(tmp_path, signing, monkeypatch):
    path = tmp_path / "profile.credentials"
    expired(path, signing)
    calls = endpoint(monkeypatch, signing, ProviderError("authorization_service_failed"))
    failed = []

    def mark_failed():
        with pytest.raises(ProviderError, match="credential_session_busy"):
            with login.credential_lock(path):
                pytest.fail("failure released lock too early")
        failed.append(True)

    with pytest.raises(ProviderError, match="authorization_service_failed"):
        login.refresh_credentials(path, on_failure=mark_failed)

    def guard():
        assert failed
        raise ProviderError("run_budget_already_failed")

    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        login.refresh_credentials(path, before_refresh=guard)
    assert len(calls) == 1
