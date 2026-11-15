"""Serve a built Manabrew web client (its ``dist`` folder, as built locally) on 127.0.0.1, pointed at the local relay.

The client reads ``/config.js`` before it connects; this server answers that path itself with the local relay, a
hub address that goes nowhere, and hosted play on. It answers the starter-deck list (``/preset_decks/``) with the
eight Pauper decks Basilisk 2 trained with (``decks.py``), and serves every other path from ``dist`` with the
cross-origin isolation headers the client's game worker needs. Unknown paths fall back to ``index.html`` (the
client routes in the browser).

The client draws mana and tap symbols from ``/scryfall-symbols/<name>.svg``, a path its own web server proxies to
Scryfall and that the build does not include. This server answers it from a folder of files that is filled on first
use from https://svgs.scryfall.io/card-symbols/ (``SymbolCache``): a file already in the folder is never fetched
again, requests to Scryfall go one at a time and spaced out, and the User-Agent names this program only.

``python -m spellbench.human.manabrew.serve_client <dist> [--port 5180] [--relay-port 9443] [--relay-key forge]
[--symbol-cache DIR]`` (the symbol folder defaults to ``<dist>/scryfall-symbols``).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from . import decks

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

SYMBOL_ROUTE = "/scryfall-symbols/"
SYMBOL_UPSTREAM = "https://svgs.scryfall.io/card-symbols/"
SYMBOL_FILE = re.compile(r"[A-Za-z0-9]{1,16}\.svg")  # W.svg, WU.svg, 2W.svg, BGP.svg, HALF.svg, INFINITY.svg
SYMBOL_AGENT = "spellbench-manabrew-client/1.0"
SYMBOL_GAP_S = 0.1  # Scryfall asks for 50 to 100 ms between requests
SYMBOL_RETRY_S = 60.0  # a symbol that failed to download is not asked for again for this long
SYMBOL_MAX_BYTES = 256 * 1024
SYMBOL_PREWARM = tuple(f"{code}.svg" for code in ("W", "U", "B", "R", "G", "C", "T", "Q", "X"))


def fetch_symbol(file: str) -> bytes | None:
    """One symbol file from Scryfall: its bytes, or None when Scryfall has no such symbol. Network trouble raises."""
    request = urllib.request.Request(SYMBOL_UPSTREAM + file,
                                     headers={"User-Agent": SYMBOL_AGENT, "Accept": "image/svg+xml"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read(SYMBOL_MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


class SymbolCache:
    """Mana and tap symbol files for the client, filled on first use from Scryfall and kept in ``folder``.

    ``get`` returns the file's bytes, or None for a name that is not a symbol file, a symbol Scryfall does not
    have, or a download that failed (not tried again for ``SYMBOL_RETRY_S``; after a network failure no symbol is
    tried). A file in the folder, or fetched earlier by this process, is served without any request. Downloads go
    one at a time, ``SYMBOL_GAP_S`` apart.
    """

    def __init__(self, folder: Path, fetch: Callable[[str], bytes | None] = fetch_symbol) -> None:
        self.folder = folder
        self.fetch = fetch
        self.memory: dict[str, bytes] = {}
        self.failed: dict[str, float] = {}
        self.offline_until = 0.0
        self.lock = threading.Lock()
        self.last = 0.0

    def prewarm(self, files: tuple[str, ...] = SYMBOL_PREWARM) -> None:
        """Fetch the symbols every game draws (the client's own warm-up set), so none waits on Scryfall in play."""
        for file in files:
            self.get(file)

    def get(self, file: str) -> bytes | None:
        if not SYMBOL_FILE.fullmatch(file):
            return None
        with self.lock:
            if file in self.memory:
                return self.memory[file]
            spot = self.folder / file
            try:
                self.memory[file] = spot.read_bytes()
                return self.memory[file]
            except OSError:
                pass
            if time.monotonic() < max(self.failed.get(file, 0.0), self.offline_until):
                return None
            wait = self.last + SYMBOL_GAP_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                body = self.fetch(file)
            except (OSError, ValueError):  # no network, a refused or timed out request
                body = None
                self.offline_until = time.monotonic() + SYMBOL_RETRY_S
            self.last = time.monotonic()
            if body is None or len(body) > SYMBOL_MAX_BYTES or b"<svg" not in body[:2048]:
                self.failed[file] = time.monotonic() + SYMBOL_RETRY_S
                return None
            self.memory[file] = body
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                partial = spot.with_name(spot.name + ".part")
                partial.write_bytes(body)
                os.replace(partial, spot)
            except OSError:
                pass  # a folder that cannot be written still serves this process's copy
            return body


def make_handler(dist: Path, config_js: bytes, symbols: SymbolCache | None = None):
    root = dist.resolve()
    presets = decks.by_preset_id()
    symbols = symbols if symbols is not None else SymbolCache(root / "scryfall-symbols")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - quiet
            return

        def _send(self, status: int, body: bytes, content_type: str, cache_control: str = "no-store") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cache-Control", cache_control)
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
            if path.startswith(SYMBOL_ROUTE):
                body = symbols.get(path[len(SYMBOL_ROUTE):])
                if body is None:
                    self._send(404, b"", "text/plain")
                else:
                    self._send(200, body, "image/svg+xml", "public, max-age=86400")
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
    parser.add_argument("--symbol-cache", type=Path,
                        help="folder for the mana symbols fetched from Scryfall (default: <dist>/scryfall-symbols)")
    args = parser.parse_args(argv)
    runtime = {"relay": {"host": "127.0.0.1", "port": args.relay_port, "password": args.relay_key},
               "hubApiUrl": "http://127.0.0.1:9", "hostedAiEnabled": True}
    config_js = f"window.__MANABREW_RUNTIME__ = {json.dumps(runtime)};\n".encode()
    symbols = SymbolCache(args.symbol_cache or args.dist.resolve() / "scryfall-symbols")
    threading.Thread(target=symbols.prewarm, daemon=True).start()  # the first game's symbols are there before it starts
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.dist, config_js, symbols))
    print(f"Manabrew client on http://127.0.0.1:{args.port}/ (relay ws://127.0.0.1:{args.relay_port})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
