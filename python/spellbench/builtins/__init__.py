"""Builtin bots on protocol v2: ``uniform``, ``heuristic``, ``first``, each version 2.0.0.

Each module also serves its bot over stdin and stdout:
``python -m spellbench.builtins.<name>`` (``uniform`` takes ``--seed N``).
"""

from __future__ import annotations

from typing import Any

from . import first, heuristic, uniform

BUILTIN_BOTS = {
    first.BOT_NAME: first.FirstBot,
    heuristic.BOT_NAME: heuristic.HeuristicBot,
    uniform.BOT_NAME: uniform.UniformBot,
}

BUILTIN_VERSIONS = {
    first.BOT_NAME: first.BOT_VERSION,
    heuristic.BOT_NAME: heuristic.BOT_VERSION,
    uniform.BOT_NAME: uniform.BOT_VERSION,
}


def create_builtin_bot(name: str, *, seed: int = 0) -> Any:
    """Instantiate a builtin bot; fails closed on unknown names. Only ``uniform`` reads ``seed``."""
    if name not in BUILTIN_BOTS:
        raise ValueError(f"unknown builtin bot: {name!r} (known: {sorted(BUILTIN_BOTS)})")
    if name == uniform.BOT_NAME:
        return uniform.UniformBot(seed)
    return BUILTIN_BOTS[name]()
