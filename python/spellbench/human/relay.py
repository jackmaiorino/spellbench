"""The human seat's agent process: relays each request to the local play server (``spellbench.human.server``).

The arena starts this file as an ordinary subprocess bot, one process per game. It answers on stdin and stdout
through ``spellbench.bot.serve`` and forwards ``game_start``, ``choose`` and ``game_over`` to the server named by
``HUMAN_SEAT_URL`` with the token in ``HUMAN_SEAT_TOKEN`` (the arena strips ``SPELLBENCH_*`` variables from bot
environments, so these names stay outside that prefix). ``hello`` waits until the human asks for the next game,
which keeps the pause between games off the game clock: ``startup_ms`` bounds it, ``bank_ms`` does not.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spellbench.bot import Decision, GameOver, GameStart, serve  # noqa: E402

NAME = "human"
VERSION = "1.0.0"
URL_ENV = "HUMAN_SEAT_URL"
TOKEN_ENV = "HUMAN_SEAT_TOKEN"
# The model's input tensor is large and means nothing to a person; everything else is forwarded unchanged.
DROPPED_EXTENSIONS = ("x_kernel_flat_v4",)


class Relay:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._token = token

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self._url + path, data=data, method="POST",
            headers={"Content-Type": "application/json", "X-Human-Token": self._token})
        last: Exception | None = None
        for attempt in range(5):  # the server may be restarting a thread; it never loses a pending decision
            try:
                with urllib.request.urlopen(request, timeout=None) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError:
                raise
            except OSError as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"play server unreachable: {last}")

    def wait_ready(self) -> None:
        self.post("/relay/hello", {})

    def on_game_start(self, game: GameStart) -> None:
        self.post("/relay/game_start", {"request": game.raw})

    def choose(self, decision: Decision) -> int:
        request = dict(decision.raw)
        seat_decision = dict(request.get("decision") or {})
        extensions = dict(seat_decision.get("extensions") or {})
        for name in DROPPED_EXTENSIONS:
            extensions.pop(name, None)
        seat_decision["extensions"] = extensions
        request["decision"] = seat_decision
        answer = self.post("/relay/choose", {"request": request})
        return int(answer["candidate_id"])

    def on_game_over(self, game_over: GameOver) -> None:
        self.post("/relay/game_over", {"request": game_over.raw})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=NAME)
    parser.add_argument("--version", default=VERSION)
    args = parser.parse_args(argv)
    url, token = os.environ.get(URL_ENV), os.environ.get(TOKEN_ENV)
    if not url or not token:
        print(f"relay: {URL_ENV} and {TOKEN_ENV} must name the play server", file=sys.stderr)
        return 2
    relay = Relay(url, token)
    relay.wait_ready()
    return serve(relay, name=args.name, version=args.version, extensions_accepted=["x_public_history_v1"])


if __name__ == "__main__":
    sys.exit(main())
