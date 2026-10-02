"""Real HTTPS checks of native chain, hostname and expiry validation."""

from __future__ import annotations

import datetime as dt
import ssl
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("truststore")
pytest.importorskip("cryptography")
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from spellbench.llm import login
from spellbench.llm.chatgpt import ChatGptConfig, ChatGptProvider
from spellbench.llm.prompt import render_prompt
from spellbench.llm.provider import ProviderError
from spellbench.llm.tls import native_opener

from test_llm_agent import decision
from test_llm_chatgpt import sse, completed


@pytest.fixture
def https_server(tmp_path):
    servers = []
    def create(*, expired=False):
        now = dt.datetime.now(dt.timezone.utc)
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Spellbench offline test CA")])
        root = (x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name).public_key(root_key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
                .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), True)
                .sign(root_key, hashes.SHA256()))
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        leaf = (x509.CertificateBuilder().subject_name(leaf_name).issuer_name(root_name).public_key(leaf_key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(hours=2))
                .not_valid_after(now + dt.timedelta(hours=-1 if expired else 1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
                .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
                .sign(root_key, hashes.SHA256()))
        root_path, leaf_path, key_path = (tmp_path / name for name in ("root.pem", "leaf.pem", "key.pem"))
        root_path.write_bytes(root.public_bytes(serialization.Encoding.PEM))
        leaf_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except (ConnectionError, ssl.SSLError):
                    # Native validation can abort after the TLS handshake but
                    # before sending HTTP. These disconnects are expected.
                    pass

            def do_POST(self):
                self.server.requests.append(self.headers.get("Authorization"))
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(sse({"type": "response.completed", "response": completed()}))

            def do_GET(self):
                self.server.requests.append("GET")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"keys":[]}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(leaf_path, key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        servers.append((server, thread))
        return server, root_path
    yield create
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def trust_test_ca(opener, root_path):
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPSHandler):
            handler._context.load_verify_locations(cafile=root_path)
            assert handler._context.check_hostname is True and handler._context.verify_mode == ssl.CERT_REQUIRED


def test_valid_chain_and_hostname_permit_the_request_without_global_ssl_changes(https_server):
    original_context = ssl.SSLContext
    server, root_path = https_server()
    provider = ChatGptProvider(ChatGptConfig("test", "test-secret"))
    trust_test_ca(provider._opener, root_path)
    provider._endpoint = f"https://localhost:{server.server_port}/responses"
    assert provider.complete(render_prompt(decision()), timeout_s=3).content == '{"candidate_id":1}'
    assert server.requests == ["Bearer test-secret"] and ssl.SSLContext is original_context


@pytest.mark.parametrize("case", ["untrusted", "wrong-hostname", "expired"])
def test_invalid_tls_prevents_inference_and_oauth_http_requests(https_server, monkeypatch, case):
    server, root_path = https_server(expired=case == "expired")
    provider = ChatGptProvider(ChatGptConfig("test", "test-secret"))
    opener = native_opener()
    if case != "untrusted":
        trust_test_ca(provider._opener, root_path)
        trust_test_ca(opener, root_path)
    host = "127.0.0.1" if case == "wrong-hostname" else "localhost"
    target = f"https://{host}:{server.server_port}/responses"
    provider._endpoint = target
    with pytest.raises(ProviderError, match="transport_error"):
        provider.complete(render_prompt(decision()), timeout_s=3)
    monkeypatch.setattr(login, "native_opener", lambda: opener)
    with pytest.raises(ProviderError, match="authorization_service_failed"):
        login._json_request(target, {"code": "secret-code"})
    assert server.requests == []
