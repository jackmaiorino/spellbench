"""The ``uniform`` builtin bot: a uniformly random candidate, seeded from ``agent_seed`` (spec 10.6).

It is the rating anchor ("random"), so its picks are a pure function of each
game's ``agent_seed`` and the bot's configured ``seed``.

``SplitMix64`` is a line-for-line port of the reference implementation in
mtg-kernel ``python/mtg_kernel_rl/determinism.py`` (class ``SplitMix64``).

Derivation (``spellbench-arena-uniform-v2``): the bot is constructed with a
nonnegative integer ``seed``. On ``game_start`` the game's stream is seeded
with ``SplitMix64((agent_seed ^ seed) & MASK64)``, a missing ``agent_seed``
reading as 0. Each ``choose`` draws ``stream.next() % len(candidates)``, the
same modulo reduction the mtg-kernel uniform policy uses
(``determinism.derive_uniform_index``), and answers that candidate's
``candidate_id``. The host derives ``agent_seed`` from the run secret, the
game index and the seat (spec 11.6), so the two seats and the two games of a
seat-swapped pair draw independent streams, and the revealed run secret
replays every pick.
"""

from __future__ import annotations

import sys

from ..bot import Decision, GameOver, GameStart, serve

MASK64 = 0xFFFF_FFFF_FFFF_FFFF
GOLDEN_RATIO_64 = 0x9E37_79B9_7F4A_7C15

BOT_NAME = "uniform"
BOT_VERSION = "2.0.0"
DERIVATION_VERSION = "spellbench-arena-uniform-v2"

_USAGE = "usage: python -m spellbench.builtins.uniform [--seed N] (N a nonnegative integer)"


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


def stream_seed(agent_seed: int, seed: int) -> int:
    return (agent_seed ^ seed) & MASK64


class UniformBot:
    """Answers a uniformly random offered candidate (the derivation above)."""

    name = BOT_NAME
    version = BOT_VERSION

    def __init__(self, seed: int = 0) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("uniform bot seed must be a nonnegative integer")
        self._seed = seed
        self._stream: SplitMix64 | None = None

    def on_game_start(self, game: GameStart) -> None:
        self._stream = SplitMix64(stream_seed(game.agent_seed or 0, self._seed))

    def choose(self, decision: Decision) -> int:
        if self._stream is None:
            raise RuntimeError("choose before game_start")
        return decision.candidates[self._stream.next() % len(decision.candidates)].candidate_id

    def on_game_over(self, game_over: GameOver) -> None:
        self._stream = None


def main() -> int:
    """Serve the uniform bot over stdin and stdout; exit code 2 for a bad argument."""
    argv = sys.argv[1:]
    try:
        if argv and (len(argv) != 2 or argv[0] != "--seed"):
            raise ValueError("unknown arguments")
        bot = UniformBot(int(argv[1]) if argv else 0)
    except ValueError:  # an unknown argument, or a seed that is not a nonnegative integer
        print(_USAGE, file=sys.stderr)
        return 2
    return serve(bot, name=BOT_NAME, version=BOT_VERSION)


if __name__ == "__main__":
    sys.exit(main())
