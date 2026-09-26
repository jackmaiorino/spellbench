"""Spellbench protocol reference stack (spec/SPELLBENCH_PROTOCOL_V1.md)."""

from __future__ import annotations

from . import models, wire
from .errors import (
    AGENT_ERROR_CODES,
    ENGINE_ERROR_CODES,
    AgentError,
    EngineError,
    LineTooLongError,
    MalformedJsonError,
    ProtocolError,
    RemoteError,
    SpellbenchError,
    TransportError,
    ValidationError,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "models",
    "wire",
    "SpellbenchError",
    "ProtocolError",
    "MalformedJsonError",
    "LineTooLongError",
    "ValidationError",
    "TransportError",
    "RemoteError",
    "EngineError",
    "AgentError",
    "ENGINE_ERROR_CODES",
    "AGENT_ERROR_CODES",
    "EngineProcess",
    "AgentProcess",
    "serve",
]


def __getattr__(name: str):
    # Lazy so that importing spellbench.errors/wire/models stays lightweight.
    if name == "EngineProcess":
        from .engine_client import EngineProcess

        return EngineProcess
    if name == "AgentProcess":
        from .agent_client import AgentProcess

        return AgentProcess
    if name == "serve":
        from .agent_server import serve

        return serve
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
