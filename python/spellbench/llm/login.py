"""Explicit, app-owned Sign in with ChatGPT for the local Spellbench host.

Credentials are separate from Codex. There is no automatic refresh or inference
here: an expired credential requires another browser sign-in between runs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .chatgpt import BASE_URL, _unique
from .provider import ProviderError
from .tls import native_opener

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
JWKS_URL = ISSUER + "/.well-known/jwks.json"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DYNAMIC_CLIENT = "dynamic_agent_client"
MAX_CREDENTIAL_BYTES = 262_144
DPAPI_PREFIX = b"spellbench-dpapi-v1\n"


def default_credentials_path() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "Spellbench" / "chatgpt.credentials"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "spellbench" / "chatgpt.credentials"


def _dpapi(raw: bytes, *, decrypt: bool = False) -> bytes:
    """Encrypt for the current Windows user; never fall back to plaintext."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    operation = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN. No machine-wide protection flag.
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("credential protection failed")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def save_credentials(path: Path, record: dict[str, Any]) -> None:
    raw = json.dumps(record, separators=(",", ":"), ensure_ascii=True).encode()
    if os.name == "nt":
        raw = DPAPI_PREFIX + _dpapi(raw)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".chatgpt-", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_credentials(path: Path, *, require_fresh: bool = True) -> dict[str, Any]:
    info = path.stat()
    if info.st_size > MAX_CREDENTIAL_BYTES or path.is_symlink():
        raise ValueError("invalid credential file")
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("credentials require owner-only permissions")
    raw = path.read_bytes()
    if os.name == "nt":
        if not raw.startswith(DPAPI_PREFIX):
            raise ValueError("Windows credentials must be DPAPI protected")
        raw = _dpapi(raw[len(DPAPI_PREFIX):], decrypt=True)
    record = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(record, dict) or record.get("schema") != "spellbench-chatgpt/v1":
        raise ValueError("invalid credential file")
    for name in ("client_id", "subject", "access_token", "ext_agent_host_id"):
        if not isinstance(record.get(name), str) or not record[name]:
            raise ValueError("invalid credentials")
    scopes = record.get("scopes")
    if (record.get("issuer") != ISSUER or not isinstance(scopes, list)
            or any(not isinstance(scope, str) for scope in scopes) or "chatgpt.tokens.use.direct" not in scopes):
        raise ValueError("ChatGPT plan usage not granted")
    if type(record.get("expires_at")) not in {int, float} or not math.isfinite(record["expires_at"]):
        raise ValueError("invalid credential expiry")
    if require_fresh and record["expires_at"] <= time.time() + 60:
        raise ValueError("credentials expired; sign in between runs")
    return record


def host_id(path: Path) -> str:
    """Stable per app host, shared by its separate account profiles."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="ascii") as stream:
            stream.write("urn:uuid:" + str(uuid.uuid4()))
    except FileExistsError:
        pass
    value = path.read_text(encoding="ascii").strip()
    if not value.startswith("urn:uuid:"):
        raise ValueError("invalid host ID")
    uuid.UUID(value[9:])
    return value


@dataclass(frozen=True)
class Attempt:
    redirect_uri: str
    host: str
    client_id: str = DYNAMIC_CLIENT
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64), repr=False)

    def authorization_url(self) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        params = {"client_id": self.client_id, "ext_agent_host_id": self.host, "response_type": "code",
                  "redirect_uri": self.redirect_uri, "scope": SCOPES, "resource": BASE_URL,
                  "state": self.state, "nonce": self.nonce, "code_challenge_method": "S256", "code_challenge": challenge}
        if self.client_id == DYNAMIC_CLIENT:
            params["agent_name_hint"] = "Spellbench"
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    def callback(self, query: str) -> tuple[str, str]:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=16)
        values = _unique(pairs)
        state = values.get("state", "")
        if not state.isascii() or not hmac.compare_digest(state, self.state):
            raise ValueError("invalid callback state")
        if "error" in values:
            raise ProviderError("authorization_denied")
        client = values.get("client_id", self.client_id)
        if (not client.startswith("oaiapp_") or
                (self.client_id != DYNAMIC_CLIENT and client != self.client_id) or not values.get("code")):
            raise ValueError("invalid registration callback")
        return values["code"], client


def _json_request(url: str, form: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, None if form is None else urllib.parse.urlencode(form).encode(),
                                     {} if form is None else {"Content-Type": "application/x-www-form-urlencoded"})
    opener = native_opener()
    try:
        with opener.open(request, timeout=15) as stream:
            raw = stream.read(MAX_CREDENTIAL_BYTES + 1)
        if len(raw) > MAX_CREDENTIAL_BYTES:
            raise ValueError
        result = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ProviderError("authorization_service_failed") from None
    except (ValueError, OSError, ProviderError):
        # Never expose authorization codes, tokens, response bodies or URLs.
        raise ProviderError("authorization_service_failed") from None


def verify_identity(token: str, client_id: str, nonce: str, jwks: dict[str, Any]) -> dict[str, Any]:
    try:
        import jwt
    except ImportError:
        raise ValueError("install the chatgpt optional dependency") from None
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError
        keys = [item for item in jwks["keys"] if item.get("kid") == header["kid"]]
        if len(keys) != 1 or keys[0].get("kty") != "RSA":
            raise ValueError
        key = jwt.PyJWK.from_dict(keys[0], algorithm="RS256")
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id, issuer=ISSUER,
                            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]}, leeway=5)
        if not isinstance(claims["sub"], str) or not claims["sub"] or not hmac.compare_digest(claims["nonce"], nonce):
            raise ValueError
        return claims
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
        raise ProviderError("invalid_identity_token") from None


def exchange(attempt: Attempt, code: str, client_id: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    value = _json_request(TOKEN_URL, {"grant_type": "authorization_code", "client_id": client_id, "code": code,
                                    "code_verifier": attempt.verifier, "redirect_uri": attempt.redirect_uri, "resource": BASE_URL})
    try:
        claims = verify_identity(value["id_token"], client_id, attempt.nonce, _json_request(JWKS_URL))
        if previous is not None and (claims["sub"] != previous["subject"] or client_id != previous["client_id"]):
            raise ProviderError("account_mismatch")
        scopes = value["scope"].split()
        if "chatgpt.tokens.use.direct" not in scopes:
            raise ProviderError("plan_usage_not_granted")
        if (value["token_type"].lower() != "bearer" or not isinstance(value["access_token"], str)
                or not value["access_token"] or type(value["expires_in"]) is not int or value["expires_in"] <= 60):
            raise ValueError
        return {"schema": "spellbench-chatgpt/v1", "issuer": ISSUER, "client_id": client_id, "subject": claims["sub"],
                "ext_agent_host_id": attempt.host, "access_token": value["access_token"], "id_token": value["id_token"],
                "refresh_token": value.get("refresh_token"), "scopes": scopes, "expires_at": time.time() + value["expires_in"]}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProviderError("invalid_token_response") from None


def sign_in(path: Path, *, port: int = 0, timeout_s: float = 300) -> None:
    try:
        import jwt  # noqa: F401; fail before opening consent if the extra is missing
    except ImportError:
        raise ValueError("install the chatgpt optional dependency") from None
    native_opener()  # Validate the optional TLS dependency before browser consent.
    # One profile belongs to one verified identity/client. Selecting a different
    # account requires a different path, rather than replacing its registration.
    previous = load_credentials(path, require_fresh=False) if path.exists() else None
    selected_host = host_id(path.parent / "chatgpt.host-id")

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(2)

        def do_GET(self) -> None:
            url = urllib.parse.urlsplit(self.path)
            if url.path != "/auth/callback" or self.headers.get("Host") != f"127.0.0.1:{server.server_port}":
                self.send_error(400)
                return
            try:
                server.result = attempt.callback(url.query)
            except ValueError:
                self.send_error(400)
                return
            except ProviderError as exc:
                server.result = exc
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Return to Spellbench to check sign-in. You may close this tab.")

        def log_message(self, *args: Any) -> None:
            pass

    with HTTPServer(("127.0.0.1", port), Handler) as server:
        server.timeout, server.result = 1, None
        attempt = Attempt(f"http://127.0.0.1:{server.server_port}/auth/callback", selected_host,
                          DYNAMIC_CLIENT if previous is None else previous["client_id"])
        print("Opening ChatGPT sign-in for Spellbench. Review the ChatGPT plan usage permission in your browser.", flush=True)
        if not webbrowser.open(attempt.authorization_url()):
            raise ProviderError("browser_open_failed")
        deadline = time.monotonic() + timeout_s
        while server.result is None and time.monotonic() < deadline:
            server.handle_request()
        if server.result is None:
            raise ProviderError("authorization_timeout")
        if isinstance(server.result, ProviderError):
            raise server.result
        code, client_id = server.result
    save_credentials(path, exchange(attempt, code, client_id, previous))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign in with ChatGPT for Spellbench; does not run inference")
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    try:
        sign_in(args.credentials or default_credentials_path(), port=args.port)
        print("Spellbench sign-in complete. Credentials saved outside game logs; no model requests were made.")
        return 0
    except (OSError, ValueError, ProviderError) as exc:
        code = exc.code if isinstance(exc, ProviderError) else "local_configuration_failed"
        print("Spellbench sign-in failed: " + code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
