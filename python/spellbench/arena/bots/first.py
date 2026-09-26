"""Trivial conformance bot: always picks candidate 0.

Exists so protocol conformance tests have a minimal, fully deterministic
agent; mirrors ``spellbench.agent_server.main`` but as a named builtin with
the arena's standard module entry point.
"""

from __future__ import annotations

from ... import models

BOT_NAME = "first"
BOT_VERSION = "1.0.0"


class FirstBot:
    """Implements the builtin-agent call sequence (see bots/uniform.py)."""

    name = BOT_NAME
    version = BOT_VERSION

    def on_game_start(self, request: models.GameStartRequest) -> None:
        return None

    def choose(self, decision: models.Decision) -> int:
        return 0

    def on_game_over(self, request: models.GameOverRequest) -> None:
        return None


def main() -> int:
    """Serve the first-candidate bot as an agent-role subprocess."""
    from ... import agent_server

    return agent_server.serve(FirstBot(), bot_name=BOT_NAME, bot_version=BOT_VERSION)


if __name__ == "__main__":
    import sys

    sys.exit(main())
