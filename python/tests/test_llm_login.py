"""Native OAuth consent, verified identities, and protected app-owned records."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("truststore")
from cryptography.hazmat.primitives.asymmetric import rsa

from spellbench.llm import login
from spellbench.llm.provider import ProviderError
from spellbench.host.agent_process import AgentProcess
from test_llm_agent import decision


@pytest.fixture(scope="module")
def signing():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", alg="RS256", use="sig")
    return key, {"keys": [jwk]}


def token(signing, **changes):
    claims = {"iss": login.ISSUER, "aud": "oaiapp_test", "sub": "account-test", "iat": int(time.time()),
              "exp": int(time.time()) + 3600, "nonce": "nonce-test", **changes}
    return jwt.encode(claims, signing[0], algorithm="RS256", headers={"kid": "test-key"})


def record(**changes):
    return {"schema": "spellbench-chatgpt/v1", "issuer": login.ISSUER, "client_id": "oaiapp_test", "subject": "account-test",
            "access_token": "secret-access", "refresh_token": "secret-refresh", "id_token": "secret-id",
            "ext_agent_host_id": "urn:uuid:00000000-0000-0000-0000-000000000001",
            "scopes": ["chatgpt.tokens.use.direct"], "expires_at": time.time() + 3600, **changes}


def test_protected_record_roundtrip_and_expiry(tmp_path):
    path = tmp_path / "profile.credentials"
    value = record()
    login.save_credentials(path, value)
    assert login.load_credentials(path) == value
    if os.name == "nt":
        assert b"secret-access" not in path.read_bytes() and path.read_bytes().startswith(login.DPAPI_PREFIX)
    else:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    login.save_credentials(path, record(expires_at=time.time() - 30))
    with pytest.raises(ValueError, match="expired"):
        login.load_credentials(path)
    assert login.load_credentials(path, require_fresh=False)["subject"] == "account-test"


def test_unprotected_or_world_readable_credentials_are_rejected(tmp_path):
    path = tmp_path / "profile.credentials"
    if os.name == "nt":
        path.write_text(json.dumps(record()))
    else:
        login.save_credentials(path, record())
        os.chmod(path, 0o644)
    with pytest.raises(ValueError):
        login.load_credentials(path)


@pytest.mark.parametrize("changes", [{"issuer": "untrusted"}, {"scopes": []}, {"expires_at": float("inf")},
                                     {"expires_at": True}, {"client_id": None}, {"scopes": "chatgpt.tokens.use.direct"}])
def test_malformed_or_ungranted_record_is_rejected(tmp_path, changes):
    path = tmp_path / "profile.credentials"
    login.save_credentials(path, record(**changes))
    with pytest.raises(ValueError):
        login.load_credentials(path)


def test_authorization_uses_public_registration_host_pkce_and_separate_state(tmp_path):
    host = login.host_id(tmp_path / "host")
    assert login.host_id(tmp_path / "host") == host
    attempt = login.Attempt("http://127.0.0.1:54321/auth/callback", host)
    url = urllib.parse.urlsplit(attempt.authorization_url())
    values = dict(urllib.parse.parse_qsl(url.query))
    assert url.scheme == "https" and url.hostname == "auth.openai.com"
    assert values["client_id"] == "dynamic_agent_client" and values["agent_name_hint"] == "Spellbench"
    assert values["resource"] == "https://api.openai.com/v1" and values["ext_agent_host_id"] == host
    expected = base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
    assert values["code_challenge"] == expected and values["code_challenge_method"] == "S256"
    assert attempt.state != attempt.nonce and len(attempt.verifier) >= 43
    assert attempt.state not in repr(attempt) and "client_secret" not in values


@pytest.mark.parametrize("changes", [{"state": "wrong"}, {"client_id": "dynamic_agent_client"}, {"code": ""},
                                     {"client_id": ""}, {"state": ""}])
def test_bad_callback_is_rejected(changes):
    attempt = login.Attempt("http://127.0.0.1:1455/auth/callback", "host")
    values = {"state": attempt.state, "code": "test-code", "client_id": "oaiapp_test", **changes}
    with pytest.raises(ValueError):
        attempt.callback(urllib.parse.urlencode(values))


def test_denial_validates_state_and_duplicate_fields_are_rejected():
    attempt = login.Attempt("http://127.0.0.1:1455/auth/callback", "host")
    with pytest.raises(ValueError):
        attempt.callback("state=wrong&error=access_denied")
    with pytest.raises(ValueError):
        attempt.callback(urllib.parse.urlencode({"state": "é", "error": "access_denied"}))
    with pytest.raises(ProviderError, match="authorization_denied"):
        attempt.callback(urllib.parse.urlencode({"state": attempt.state, "error": "access_denied"}))
    with pytest.raises(ValueError):
        attempt.callback(urllib.parse.urlencode({"state": attempt.state}) + "&code=one&code=two&client_id=oaiapp_test")


def test_returning_callback_cannot_replace_client_registration():
    attempt = login.Attempt("http://127.0.0.1:1455/auth/callback", "host", "oaiapp_test")
    assert "agent_name_hint" not in attempt.authorization_url()
    assert attempt.callback(urllib.parse.urlencode({"state": attempt.state, "code": "test-code"})) == ("test-code", "oaiapp_test")
    with pytest.raises(ValueError):
        attempt.callback(urllib.parse.urlencode({"state": attempt.state, "code": "test-code", "client_id": "oaiapp_other"}))


def test_signature_and_all_identity_claims_are_validated(signing):
    assert login.verify_identity(token(signing), "oaiapp_test", "nonce-test", signing[1])["sub"] == "account-test"


@pytest.mark.parametrize("changes", [{"iss": "other"}, {"aud": "other"}, {"nonce": "other"}, {"nonce": None},
                                     {"sub": ""}, {"exp": int(time.time()) - 60}, {"iat": int(time.time()) + 3600}])
def test_untrusted_identity_cannot_be_saved(signing, changes):
    with pytest.raises(ProviderError, match="invalid_identity_token"):
        login.verify_identity(token(signing, **changes), "oaiapp_test", "nonce-test", signing[1])


def test_invalid_signature_and_algorithm_are_rejected(signing):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"nonce": "nonce-test"}, other, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(ProviderError, match="invalid_identity_token"):
        login.verify_identity(forged, "oaiapp_test", "nonce-test", signing[1])
    forged = jwt.encode({"nonce": "nonce-test"}, "x" * 32, algorithm="HS256", headers={"kid": "test-key"})
    with pytest.raises(ProviderError, match="invalid_identity_token"):
        login.verify_identity(forged, "oaiapp_test", "nonce-test", signing[1])


def test_end_to_end_loopback_consent_exchange_and_protected_store(tmp_path, monkeypatch, signing):
    captured, requests, replies, threads = {}, [], [], []

    def browser(url):
        captured.update(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)))
        callback = captured["redirect_uri"] + "?" + urllib.parse.urlencode({
            "state": captured["state"], "code": "test-code", "client_id": "oaiapp_test"})
        def send_callback():
            with urllib.request.urlopen(callback, timeout=3) as stream:
                replies.append(stream.status)
        thread = threading.Thread(target=send_callback)
        thread.start()
        threads.append(thread)
        return True

    def endpoint(url, form=None):
        requests.append((url, form))
        if url == login.JWKS_URL:
            return signing[1]
        return {"id_token": token(signing, nonce=captured["nonce"]), "access_token": "secret-access",
                "refresh_token": "secret-refresh", "token_type": "Bearer", "expires_in": 3600, "scope": login.SCOPES}

    monkeypatch.setattr(login.webbrowser, "open", browser)
    monkeypatch.setattr(login, "_json_request", endpoint)
    path = tmp_path / "profile.credentials"
    login.sign_in(path, timeout_s=5)
    for thread in threads:
        thread.join(timeout=3)
    assert replies == [200]
    saved = login.load_credentials(path)
    assert saved["subject"] == "account-test" and saved["client_id"] == "oaiapp_test"
    assert requests[0][1]["client_id"] == "oaiapp_test" and requests[0][1]["code"] == "test-code"
    assert requests[0][1]["redirect_uri"] == captured["redirect_uri"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(requests[0][1]["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == captured["code_challenge"] and "client_secret" not in requests[0][1]


@pytest.mark.parametrize("case,code", [("scope", "plan_usage_not_granted"), ("account", "account_mismatch")])
def test_exchange_cannot_enable_ungranted_usage_or_switch_existing_account(monkeypatch, signing, case, code):
    attempt = login.Attempt("http://127.0.0.1:1455/auth/callback", "host", "oaiapp_test", nonce="nonce-test")
    def endpoint(url, form=None):
        if url == login.JWKS_URL:
            return signing[1]
        return {"id_token": token(signing, sub="different" if case == "account" else "account-test"),
                "access_token": "secret", "token_type": "Bearer", "expires_in": 3600,
                "scope": "openid" if case == "scope" else login.SCOPES}
    monkeypatch.setattr(login, "_json_request", endpoint)
    with pytest.raises(ProviderError, match=code):
        login.exchange(attempt, "code", "oaiapp_test", record())


def plan_command(credentials, logs, *options):
    return [sys.executable, "-m", "spellbench.llm", "--provider", "chatgpt-plan", "--model", "gpt-6-luna",
            "--credentials", str(credentials), "--log-dir", str(logs), *options]


def test_plan_cli_real_stdio_handshake_forced_choice_and_secret_free_logs(tmp_path):
    path, logs = tmp_path / "profile.credentials", tmp_path / "logs"
    login.save_credentials(path, record())
    # The plan route works without an API key and sends no request for a forced
    # choice. This exercises the real CLI and DPAPI decryption in a subprocess.
    env = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
    with AgentProcess(plan_command(path, logs), startup_timeout_s=5, env=env) as client:
        assert client.hello().bot.name == "llm-gpt-6-luna"
        client.game_start({"game_id": "g", "seat": "p0"}, timeout_s=2)
        assert client.choose(decision(forced=True).raw, timeout_s=2).candidate_id == 0
        client.game_over({"game_id": "g", "terminal": {}}, timeout_s=2)
    text = next(logs.glob("*.jsonl")).read_text()
    assert "secret-access" not in text and "secret-refresh" not in text
    events = [json.loads(line) for line in text.splitlines()]
    assert events[0]["provider"]["transport"] == "chatgpt-plan"
    assert events[-2]["calls"] == 0


@pytest.mark.parametrize("options", [("--base-url", "http://127.0.0.1:1"), ("--temperature", "0"),
                                    ("--response-format", "json_object"), ("--broker-stdio",), ("--allow-no-api-key",)])
def test_plan_cli_rejects_unsupported_options_before_credential_read_or_handshake(tmp_path, options):
    logs = tmp_path / "logs"
    result = subprocess.run(plan_command(tmp_path / "missing.credentials", logs, *options), input=b"", capture_output=True, timeout=5)
    assert result.returncode == 2 and b"unsupported provider options" in result.stderr and not result.stdout
    assert not logs.exists()


def test_expired_plan_credentials_fail_before_handshake_and_logs(tmp_path):
    path, logs = tmp_path / "profile.credentials", tmp_path / "logs"
    login.save_credentials(path, record(expires_at=time.time() - 60))
    result = subprocess.run(plan_command(path, logs), input=b"", capture_output=True, timeout=5)
    assert result.returncode == 2 and not result.stdout and not logs.exists()
    assert b"secret" not in result.stderr
