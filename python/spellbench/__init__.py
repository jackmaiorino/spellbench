"""Spellbench protocol v2 reference stack (spec/SPELLBENCH_PROTOCOL_V2.md).

``messages`` holds the environment-role messages, ``wire`` the strict NDJSON framing and canonical JSON, and
``bot`` the reference agent-role server (``serve``). ``host`` plays one game (``EngineProcess`` and
``AgentProcess`` are its role clients) and ``arena`` runs tournaments. Committed protocol v1 runs stay checkable
through the frozen verifier ``arena.legacy_v1``; no other protocol v1 code is left.
"""

from __future__ import annotations

from . import bot, messages, wire
from .errors import (
    AgentError,
    EngineError,
    LineTooLongError,
    MalformedJsonError,
    PeerTimeoutError,
    ProtocolError,
    RemoteError,
    SpellbenchError,
    TransportError,
    ValidationError,
)

__version__ = "0.3.0"

__all__ = [
    "__version__",
    "messages",
    "wire",
    "bot",
    "SpellbenchError",
    "ProtocolError",
    "MalformedJsonError",
    "LineTooLongError",
    "ValidationError",
    "TransportError",
    "PeerTimeoutError",
    "RemoteError",
    "EngineError",
    "AgentError",
    "EngineProcess",
    "AgentProcess",
    "serve",
]


def __getattr__(name: str):
    # Lazy, so that importing spellbench stays light: a bot process needs neither host client.
    if name == "EngineProcess":
        from .host.engine_process import EngineProcess

        return EngineProcess
    if name == "AgentProcess":
        from .host.agent_process import AgentProcess

        return AgentProcess
    if name == "serve":
        from .bot import serve

        return serve
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
