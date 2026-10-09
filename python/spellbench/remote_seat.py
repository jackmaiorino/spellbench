"""Remote seats: one seat played by a bot on its author's own machine (spec 11.7).

Two halves, joined by one TLS connection per game:

- ``relay`` runs on the host as the seat's agent process. The host starts it
  like any subprocess bot, a fresh process per game, and it copies the seat's
  NDJSON lines unchanged between its stdin/stdout and the author's endpoint.
  It dials out, pins the endpoint's certificate by SHA-256 and sends the
  seat's token before any protocol line. It never sees the run secret or the
  other seat: its only input is what the host already sends this seat.
- ``serve`` runs on the author's machine. It accepts a relay, checks the
  token, starts a fresh bot process for that connection and copies lines both
  ways until either side closes.

The engine, the secrets and the live validator stay on the host. Timing is
the host's: network latency is charged to the seat's clock, and a dropped
connection is a forfeit. Nothing of the author's runs on the host, but none
of the isolation of a verified sandbox applies either, so a run with a
remote seat is self-reported.

The module uses only the standard library and no other spellbench module, so
an author can run ``serve`` from this single file.

Usage::

    python -m spellbench.remote_seat token > seat.token
    python -m spellbench.remote_seat fingerprint cert.pem
    python -m spellbench.remote_seat serve --listen 0.0.0.0:7443 --cert cert.pem --key key.pem \\
        --token-file seat.token -- python my_bot.py
    python -m spellbench.remote_seat relay --endpoint bots.example.org:7443 --server-sha256 HEX \\
        --token-file seat.token
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO, Callable, Sequence

PROTOCOL = "spellbench-remote-seat/1"
# The protocol's line limit (spellbench.wire.MAX_LINE_BYTES, spec 2); a longer line ends the connection.
MAX_LINE_BYTES = 8 * 1024 * 1024
# The handshake lines are small; a longer one is refused without reading on.
MAX_HANDSHAKE_BYTES = 4096
MIN_TOKEN_CHARS = 32
DEFAULT_CONNECT_TIMEOUT_S = 30.0
DEFAULT_HANDSHAKE_TIMEOUT_S = 30.0
# How long ``serve`` lets a bot exit on its own after its connection closes, before killing it.
BOT_EXIT_GRACE_S = 5.0

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONNECT = 3
EXIT_REFUSED = 4


class RemoteSeatError(Exception):
    """A relay that cannot start: no connection, a certificate mismatch or a refused token."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


def read_token(path: str | Path) -> str:
    """The token in ``path``, stripped. Too short a token is refused, since it is the endpoint's only lock."""
    token = Path(path).read_text(encoding="utf-8").strip()
    if len(token) < MIN_TOKEN_CHARS or any(ch.isspace() for ch in token):
        raise ValueError(f"{path}: the token must be one word of at least {MIN_TOKEN_CHARS} characters")
    return token


def normalize_sha256(text: str) -> str:
    """A SHA-256 fingerprint as 64 lowercase hex digits; colons, as ``openssl x509 -fingerprint`` prints, are dropped."""
    value = text.strip().lower().removeprefix("sha256:").replace(":", "")
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"not a SHA-256 fingerprint: {text!r}")
    return value


def certificate_sha256(pem_path: str | Path) -> str:
    """The SHA-256 of the DER form of the first certificate in ``pem_path``."""
    der = ssl.PEM_cert_to_DER_cert(Path(pem_path).read_text(encoding="ascii"))
    return hashlib.sha256(der).hexdigest()


def parse_endpoint(text: str, *, any_port: bool = False) -> tuple[str, int]:
    """``HOST:PORT`` or ``[IPV6]:PORT`` as ``(host, port)``; ``any_port`` also accepts port 0 (listen on any)."""
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit() or not (0 if any_port else 1) <= int(port) < 65536:
        raise ValueError(f"not HOST:PORT: {text!r}")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, int(port)


def _handshake_line(**fields: object) -> bytes:
    return json.dumps({"remote_seat": PROTOCOL, **fields}, separators=(",", ":")).encode("utf-8") + b"\n"


def _read_handshake(stream: TlsStream) -> dict[str, object] | None:
    """One handshake object of this protocol, or ``None`` for EOF, an oversized line or anything else."""
    line = stream.readline(MAX_HANDSHAKE_BYTES + 1)
    if not line.endswith(b"\n") or len(line) > MAX_HANDSHAKE_BYTES:
        return None
    try:
        value = json.loads(line)
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("remote_seat") != PROTOCOL:
        return None
    return value


def _copy_lines(read: Callable[[int], bytes], write: Callable[[bytes], None]) -> None:
    """Copy whole lines until EOF, a partial last line or a line over the limit; then return."""
    while True:
        line = read(MAX_LINE_BYTES + 1)
        if not line or not line.endswith(b"\n") or len(line) > MAX_LINE_BYTES:
            return
        write(line)


def _pump(first: Callable[[], None], second: Callable[[], None]) -> None:
    """Run both copies on daemon threads; return as soon as either one ends."""
    done = threading.Event()

    def run(copy: Callable[[], None]) -> None:
        try:
            copy()
        except (OSError, ValueError, ssl.SSLError):
            pass
        finally:
            done.set()

    for copy in (first, second):
        threading.Thread(target=run, args=(copy,), daemon=True).start()
    done.wait()


def _close_quietly(*closers: Callable[[], None]) -> None:
    for close in closers:
        try:
            close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# TLS that one reader thread and one writer thread can share
# ---------------------------------------------------------------------------


class TlsStream:
    """A TLS connection over a plain socket, run through memory BIOs.

    Each game copies lines both ways at once, a reader thread and a writer thread on one connection. OpenSSL
    forbids using one SSL object from two threads at a time, so every call into it holds ``_ssl_lock``. Only
    the plain socket's blocking ``recv`` and ``sendall``, which are safe to run concurrently, happen outside that
    lock. ``_send_lock`` keeps the ciphertext of one ``sendall`` together on the wire.
    """

    def __init__(self, sock: socket.socket, context: ssl.SSLContext, *, server_side: bool,
                 server_hostname: str | None = None) -> None:
        self._sock = sock
        self._incoming, self._outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self._ssl = context.wrap_bio(self._incoming, self._outgoing, server_side=server_side,
                                     server_hostname=server_hostname)
        self._ssl_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._buffer = bytearray()
        self._eof = False

    def handshake(self) -> None:
        while True:
            try:
                with self._ssl_lock:
                    self._ssl.do_handshake()
                self._flush()
                return
            except ssl.SSLWantReadError:
                self._flush()
                if not self._feed():
                    raise ConnectionError("the peer closed during the TLS handshake") from None

    def peer_certificate(self) -> bytes:
        with self._ssl_lock:
            return self._ssl.getpeercert(binary_form=True) or b""

    def settimeout(self, timeout_s: float | None) -> None:
        self._sock.settimeout(timeout_s)

    def sendall(self, data: bytes) -> None:
        with self._send_lock:
            with self._ssl_lock:
                self._ssl.write(data)
                ciphertext = self._outgoing.read()
            self._sock.sendall(ciphertext)

    def readline(self, limit: int) -> bytes:
        """Up to ``limit`` bytes through the next newline, as ``io`` readers do; ``b""`` at EOF."""
        while True:
            newline = self._buffer.find(b"\n", 0, limit)
            if newline >= 0 or len(self._buffer) >= limit or self._eof:
                size = newline + 1 if newline >= 0 else min(limit, len(self._buffer))
                line = bytes(self._buffer[:size])
                del self._buffer[:size]
                return line
            chunk = self._read_some()
            if chunk:
                self._buffer += chunk
            else:
                self._eof = True

    def close(self) -> None:
        _close_quietly(lambda: self._sock.shutdown(socket.SHUT_RDWR), self._sock.close)

    def _flush(self) -> None:
        with self._send_lock:
            with self._ssl_lock:
                ciphertext = self._outgoing.read()
            if ciphertext:
                self._sock.sendall(ciphertext)

    def _feed(self) -> bool:
        """Move one ``recv`` of ciphertext into the SSL object; ``False`` once the socket is at EOF."""
        data = self._sock.recv(65536)
        with self._ssl_lock:
            if data:
                self._incoming.write(data)
            else:
                self._incoming.write_eof()
        return bool(data)

    def _read_some(self) -> bytes:
        """Some plaintext, or ``b""`` once the peer has closed, cleanly or not."""
        while True:
            try:
                with self._ssl_lock:
                    data = self._ssl.read(65536)
                    pending = self._outgoing.pending
            except ssl.SSLWantReadError:
                self._feed()  # at EOF, the next read raises the EOF it now sees
                continue
            except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
                return b""
            if pending:
                self._flush()  # TLS 1.3 post-handshake replies, such as a key update
            return data


# ---------------------------------------------------------------------------
# Host side: the relay
# ---------------------------------------------------------------------------


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def connect(endpoint: str, server_sha256: str, token: str, *,
            timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S) -> TlsStream:
    """Dial ``endpoint``, pin its certificate and present ``token``; return the accepted connection.

    The certificate is checked before the token is sent, so a wrong endpoint never learns it. The pin replaces
    chain and hostname validation, so a self-signed certificate is fine. The connection has no timeout once
    accepted: the host's clock bounds every exchange. Lines the bot wrote right after the handshake (a banner
    before ``hello_ok``) stay buffered in the returned stream.
    """
    host, port = parse_endpoint(endpoint)
    pinned = normalize_sha256(server_sha256)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # replaced by the pin below
    try:
        raw = socket.create_connection((host, port), timeout=timeout_s)
    except OSError as exc:
        raise RemoteSeatError(f"cannot reach {endpoint}: {exc}", EXIT_CONNECT) from exc
    stream = TlsStream(raw, context, server_side=False, server_hostname=None if _is_ip(host) else host)
    try:
        stream.handshake()
    except (OSError, ssl.SSLError) as exc:
        stream.close()
        raise RemoteSeatError(f"TLS handshake with {endpoint} failed: {exc}", EXIT_CONNECT) from exc
    if not hmac.compare_digest(hashlib.sha256(stream.peer_certificate()).hexdigest(), pinned):
        stream.close()
        raise RemoteSeatError(f"{endpoint} presented a certificate that does not match the pinned SHA-256",
                              EXIT_REFUSED)
    try:
        stream.sendall(_handshake_line(token=token))
        reply = _read_handshake(stream)
    except (OSError, ssl.SSLError) as exc:
        stream.close()
        raise RemoteSeatError(f"{endpoint} closed during the handshake: {exc}", EXIT_CONNECT) from exc
    if reply is None or reply.get("ok") is not True:
        reason = reply.get("error") if reply is not None else None
        stream.close()
        raise RemoteSeatError(f"{endpoint} refused the seat ({reason if isinstance(reason, str) else 'no reason'})",
                              EXIT_REFUSED)
    stream.settimeout(None)
    return stream


def relay(endpoint: str, server_sha256: str, token: str, *, stdin: BinaryIO, stdout: BinaryIO,
          timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S) -> int:
    """Connect, then copy lines between ``stdin``/``stdout`` and the endpoint until either side closes."""
    stream = connect(endpoint, server_sha256, token, timeout_s=timeout_s)

    def emit(line: bytes) -> None:
        stdout.write(line)
        stdout.flush()

    try:
        _pump(lambda: _copy_lines(stdin.readline, stream.sendall), lambda: _copy_lines(stream.readline, emit))
    finally:
        stream.close()
    return EXIT_OK


# ---------------------------------------------------------------------------
# Author side: the server
# ---------------------------------------------------------------------------


class SeatServer:
    """Accepts relays on ``listen`` and plays each connection with a fresh ``command`` process."""

    def __init__(self, listen: str, *, cert: str | Path, key: str | Path, token: str, command: Sequence[str],
                 max_games: int = 4, handshake_timeout_s: float = DEFAULT_HANDSHAKE_TIMEOUT_S,
                 log: Callable[[str], None] | None = None) -> None:
        if not command:
            raise ValueError("serve needs the bot's command after --")
        if max_games < 1:
            raise ValueError("--max-games must be at least 1")
        host, port = parse_endpoint(listen, any_port=True)
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.load_cert_chain(str(cert), str(key))
        self._token = token.encode("utf-8")
        self._command = list(command)
        self._slots = threading.BoundedSemaphore(max_games)
        self._handshake_timeout_s = handshake_timeout_s
        self._log = log or (lambda message: print(message, file=sys.stderr, flush=True))
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self._socket = socket.create_server((host, port), family=family)
        self._closed = threading.Event()

    @property
    def port(self) -> int:
        return self._socket.getsockname()[1]

    def serve_forever(self) -> None:
        while not self._closed.is_set():
            try:
                raw, address = self._socket.accept()
            except OSError:
                if self._closed.is_set():
                    return
                raise
            threading.Thread(target=self._handle, args=(raw, address), daemon=True).start()

    def close(self) -> None:
        """Stop accepting. Games already started play on. Shutting the socket down first wakes a blocked accept
        on Linux, where closing it alone would leave the port listening."""
        self._closed.set()
        _close_quietly(lambda: self._socket.shutdown(socket.SHUT_RDWR), self._socket.close)

    def _handle(self, raw: socket.socket, address: object) -> None:
        peer = f"{address}"
        raw.settimeout(self._handshake_timeout_s)  # bounds the TLS handshake and the token line
        stream = TlsStream(raw, self._context, server_side=True)
        try:
            stream.handshake()
            hello = _read_handshake(stream)
            token = hello.get("token") if hello is not None else None
            if not isinstance(token, str) or not hmac.compare_digest(token.encode("utf-8"), self._token):
                self._log(f"{peer}: refused (unauthorized)")
                stream.sendall(_handshake_line(ok=False, error="unauthorized"))
                return
            if not self._slots.acquire(blocking=False):
                self._log(f"{peer}: refused (busy)")
                stream.sendall(_handshake_line(ok=False, error="busy"))
                return
            try:
                self._play(stream, peer)
            finally:
                self._slots.release()
        except (OSError, ssl.SSLError) as exc:
            self._log(f"{peer}: connection failed: {exc}")
        finally:
            stream.close()

    def _play(self, stream: TlsStream, peer: str) -> None:
        try:
            bot = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        except OSError as exc:
            self._log(f"{peer}: cannot start the bot: {exc}")
            stream.sendall(_handshake_line(ok=False, error="bot did not start"))
            return
        assert bot.stdin is not None and bot.stdout is not None
        stream.sendall(_handshake_line(ok=True))
        stream.settimeout(None)
        self._log(f"{peer}: game started (bot pid {bot.pid})")
        bot_in, bot_out = bot.stdin, bot.stdout

        def to_bot(line: bytes) -> None:
            bot_in.write(line)
            bot_in.flush()

        try:
            _pump(lambda: _copy_lines(stream.readline, to_bot), lambda: _copy_lines(bot_out.readline, stream.sendall))
        finally:
            _close_quietly(bot_in.close)
            try:
                bot.wait(timeout=BOT_EXIT_GRACE_S)
            except subprocess.TimeoutExpired:
                bot.kill()
                bot.wait()
            _close_quietly(bot_out.close)
            self._log(f"{peer}: game ended (bot exit {bot.returncode})")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m spellbench.remote_seat", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="action", required=True)

    commands.add_parser("token", help="print a fresh random token for one seat")

    fingerprint = commands.add_parser("fingerprint", help="print a PEM certificate's SHA-256 pin")
    fingerprint.add_argument("cert")

    serve = commands.add_parser("serve", help="author side: serve a bot to relays")
    serve.add_argument("--listen", required=True, help="HOST:PORT to listen on")
    serve.add_argument("--cert", required=True, help="PEM certificate (self-signed is fine)")
    serve.add_argument("--key", required=True, help="PEM private key")
    serve.add_argument("--token-file", required=True)
    serve.add_argument("--max-games", type=int, default=4, help="games served at once; more are refused as busy")
    serve.add_argument("command", nargs=argparse.REMAINDER, help="-- then the bot's command")

    relay_parser = commands.add_parser("relay", help="host side: play this seat through an author's endpoint")
    relay_parser.add_argument("--endpoint", required=True, help="the author's HOST:PORT")
    relay_parser.add_argument("--server-sha256", required=True, help="the endpoint certificate's SHA-256 pin")
    relay_parser.add_argument("--token-file", required=True)
    relay_parser.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT_S)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "token":
            print(secrets.token_hex(32))
            return EXIT_OK
        if args.action == "fingerprint":
            print(certificate_sha256(args.cert))
            return EXIT_OK
        token = read_token(args.token_file)
        if args.action == "serve":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            server = SeatServer(args.listen, cert=args.cert, key=args.key, token=token, command=command,
                                max_games=args.max_games)
            print(f"serving on port {server.port}", file=sys.stderr, flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.close()
            return EXIT_OK
        return relay(args.endpoint, args.server_sha256, token, stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                     timeout_s=args.connect_timeout)
    except RemoteSeatError as exc:
        print(f"remote seat: {exc}", file=sys.stderr, flush=True)
        return exc.exit_code
    except (OSError, ValueError, ssl.SSLError) as exc:
        print(f"remote seat: {exc}", file=sys.stderr, flush=True)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
