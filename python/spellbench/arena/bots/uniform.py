"""Seeded uniform-choice builtin bot, with a SplitMix64 port.

``SplitMix64`` is a line-for-line port of the reference implementation in
mtg-kernel ``python/mtg_kernel_rl/determinism.py`` (class ``SplitMix64``),
reused with Jack's attribution.

Derivation (``spellbench-arena-uniform-v1``): the bot is constructed with an
integer ``seed``. On ``game_start`` the per-game stream is seeded with
``SplitMix64(seed ^ int.from_bytes(sha256(game_id.encode("utf-8"))[:8], "big"))``.
Each ``choose`` draws ``stream.next() % len(candidates)`` — the same modulo
reduction the mtg-kernel uniform policy uses
(``determinism.derive_uniform_index``). The game_id mix keeps the two games
of a seat-swapped pair decorrelated while an identical config replays
byte-identically.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ... import models

MASK64 = 0xFFFF_FFFF_FFFF_FFFF
GOLDEN_RATIO_64 = 0x9E37_79B9_7F4A_7C15

BOT_NAME = "uniform"
BOT_VERSION = "1.0.0"
DERIVATION_VERSION = "spellbench-arena-uniform-v1"


class SplitMix64:
    """Ported from mtg-kernel python/mtg_kernel_rl/determinism.py (SplitMix64)."""

    def __init__(self, seed: int) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + GOLDEN_RATIO_64) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58_476D_1CE4_E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D0_49BB_1331_11EB) & MASK64
        return (z ^ (z >> 31)) & MASK64


def game_stream_seed(seed: int, game_id: str) -> int:
    digest = hashlib.sha256(game_id.encode("utf-8")).digest()
    return (seed ^ int.from_bytes(digest[:8], "big")) & MASK64


class UniformBot:
    """Picks a uniformly random candidate from each decision's legal list.

    Implements the builtin-agent call sequence: ``on_game_start`` /
    ``choose(decision) -> candidate_id`` / ``on_game_over`` (the same handler
    shape as :func:`spellbench.agent_server.serve`).
    """

    name = BOT_NAME
    version = BOT_VERSION

    def __init__(self, seed: int = 0) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("uniform bot seed must be a nonnegative integer")
        self._seed = seed
        self._stream: SplitMix64 | None = None

    def on_game_start(self, request: models.GameStartRequest) -> None:
        self._stream = SplitMix64(game_stream_seed(self._seed, request.game_id))

    def choose(self, decision: models.Decision) -> int:
        if self._stream is None:
            raise RuntimeError("choose before game_start")
        return self._stream.next() % len(decision.candidates)

    def on_game_over(self, request: models.GameOverRequest) -> None:
        self._stream = None


def main() -> int:
    """Serve the uniform bot as an agent-role subprocess."""
    import sys

    from ... import agent_server

    seed = 0
    argv = sys.argv[1:]
    if len(argv) == 2 and argv[0] == "--seed":
        seed = int(argv[1])
    elif argv:
        print("usage: python -m spellbench.arena.bots.uniform [--seed N]", file=sys.stderr)
        return 2
    return agent_server.serve(UniformBot(seed), bot_name=BOT_NAME, bot_version=BOT_VERSION)


if __name__ == "__main__":
    import sys

    sys.exit(main())
