"""Serve a built Manabrew web client (its ``dist`` folder, as built locally) on 127.0.0.1, pointed at the local relay.

The client reads ``/config.js`` before it connects; this server answers that path itself with the local relay, a
hub address that goes nowhere, and hosted play on. It answers the starter-deck list (``/preset_decks/``) with the
eight Pauper decks Basilisk 2 trained with (``decks.py``), and serves every other path from ``dist`` with the
cross-origin isolation headers the client's game worker needs. Unknown paths fall back to ``index.html`` (the
client routes in the browser).

``python -m spellbench.human.manabrew.serve_client <dist> [--port 5180] [--relay-port 9443] [--relay-key forge]``
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import decks

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


def make_handler(dist: Path, config_js: bytes):
    root = dist.resolve()
    presets = decks.by_preset_id()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - quiet
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path == "/config.js":
                self._send(200, config_js, "text/javascript")
                return
            if path == "/preset_decks/index.json":  # the table offers exactly the training decks
                self._send(200, json.dumps(decks.preset_index()).encode(), "application/json")
                return
            if path.startswith("/preset_decks/"):
                catalog = presets.get(Path(path).stem)
                if catalog is None:
                    self._send(404, b"", "text/plain")
                else:
                    self._send(200, json.dumps(decks.preset(catalog)).encode(), "application/json")
                return
            target = (root / path.lstrip("/")).resolve()
            if root not in target.parents and target != root or not target.is_file():
                if "." in Path(path).name:  # a missing file (the status banner): nothing to serve
                    self._send(404, b"", "text/plain")
                    return
                target = root / "index.html"  # a client route
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), content_type)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--port", type=int, default=5180)
    parser.add_argument("--relay-port", type=int, default=9443)
    parser.add_argument("--relay-key", default="forge")
    args = parser.parse_args(argv)
    runtime = {"relay": {"host": "127.0.0.1", "port": args.relay_port, "password": args.relay_key},
               "hubApiUrl": "http://127.0.0.1:9", "hostedAiEnabled": True}
    config_js = f"window.__MANABREW_RUNTIME__ = {json.dumps(runtime)};\n".encode()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.dist, config_js))
    print(f"Manabrew client on http://127.0.0.1:{args.port}/ (relay ws://127.0.0.1:{args.relay_port})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
