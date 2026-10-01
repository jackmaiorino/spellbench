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
