"""The seat driver protocol and a seat's forfeit failure (spec 10, 11.5).

A ``SeatDriver`` is whatever plays one seat of one game: today a subprocess agent
(``agent_process.AgentProcess``), later perhaps an in-process bot. ``SeatFailure`` is the
one exception every driver raises when it cannot serve a request; its ``cause`` is one of
the forfeit causes of spec 11.5, and its ``diagnostic`` (the bot's stderr, an exception's
text) never appears in ``str()`` or in any message the host logs (R2-15, R3-32): only the
deterministic ``detail`` does.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from ..agent_messages import Choice

# Spec 11.5, in the order that section lists them.
SEAT_FAILURE_CAUSES = ("timeout", "malformed_response", "invalid_selection", "agent_error", "transport_error")


class SeatFailure(Exception):
    """A seat could not be served; ``cause`` is one of :data:`SEAT_FAILURE_CAUSES` (spec 11.5).

    Picklable: pickling an exception replays ``args`` into the constructor, and every
    constructor argument is positional here, so ``pickle.loads(pickle.dumps(failure))``
    reconstructs an equal ``cause``, ``detail`` and ``diagnostic``.
    """

    def __init__(self, cause: str, detail: str, diagnostic: str = "") -> None:
        super().__init__(cause, detail, diagnostic)
        self.cause = cause
        self.detail = detail
        self.diagnostic = diagnostic

    def __str__(self) -> str:
        return f"{self.cause}: {self.detail}"


class SeatDriver(Protocol):
    """One seat's live driver for the length of one game."""

    def start(self, game_start: Mapping[str, Any], *, timeout_s: float) -> None: ...

    def choose(self, choose: Mapping[str, Any], *, timeout_s: float) -> Choice: ...

    def game_over(self, game_over: Mapping[str, Any], *, timeout_s: float) -> None: ...

    def close(self) -> None: ...
