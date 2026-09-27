"""Builtin bots on protocol v2: ``uniform``, ``heuristic``, ``first``, each version 2.0.0.

Each module also serves its bot over stdin and stdout:
``python -m spellbench.builtins.<name>`` (``uniform`` takes ``--seed N``; the
others take no arguments).

The package imports its bot modules on first use, never at import. Otherwise
``-m`` would run a module the package had already imported: runpy warns about
that, and under an error-level warnings filter the bot exits before answering
``hello``. ``BUILTIN_BOTS`` and ``BUILTIN_VERSIONS`` are built on first access
(PEP 562) and then kept as ordinary module attributes.
"""

from __future__ import annotations

from typing import Any

BUILTIN_BOTS: dict[str, type]  # bound on first access, by _tables()
BUILTIN_VERSIONS: dict[str, str]  # bound on first access, by _tables()


def create_builtin_bot(name: str, *, seed: int = 0) -> Any:
    """Instantiate a builtin bot; fails closed on unknown names. Only ``uniform`` reads ``seed``."""
    bots, _ = _tables()
    if name not in bots:
        raise ValueError(f"unknown builtin bot: {name!r} (known: {sorted(bots)})")
    from . import uniform

    if name == uniform.BOT_NAME:
        return uniform.UniformBot(seed)
    return bots[name]()


def __getattr__(name: str) -> Any:
    if name == "BUILTIN_BOTS":
        return _tables()[0]
    if name == "BUILTIN_VERSIONS":
        return _tables()[1]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _tables() -> tuple[dict[str, type], dict[str, str]]:
    """Import the bot modules and bind both tables once; ``setdefault`` keeps racing threads on one copy."""
    namespace = globals()
    if "BUILTIN_VERSIONS" not in namespace:
        from . import first, heuristic, uniform

        modules = ((first, first.FirstBot), (heuristic, heuristic.HeuristicBot), (uniform, uniform.UniformBot))
        namespace.setdefault("BUILTIN_BOTS", {module.BOT_NAME: bot for module, bot in modules})
        namespace.setdefault("BUILTIN_VERSIONS", {module.BOT_NAME: module.BOT_VERSION for module, _ in modules})
    return namespace["BUILTIN_BOTS"], namespace["BUILTIN_VERSIONS"]
