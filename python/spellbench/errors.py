"""Error types of the reference stack.

The closed error-code tables live with each role's messages: ``messages.ENGINE_ERROR_CODES`` (spec 9.8)
and ``agent_messages.AGENT_ERROR_CODES`` (spec 10.5).
"""

from __future__ import annotations


class SpellbenchError(Exception):
    """Base class for every error raised by the spellbench reference stack."""


class ProtocolError(SpellbenchError):
    """A received or locally constructed message violates the protocol."""


class MalformedJsonError(ProtocolError):
    """Wire-level strict-JSON failure; maps to the ``malformed_json`` code."""


class LineTooLongError(MalformedJsonError):
    """A line exceeded the 8 MiB cap (spec section 2)."""


class ValidationError(ProtocolError):
    """Schema/semantic validation failure; maps to ``malformed_request``."""


class TransportError(SpellbenchError):
    """The peer process or pipe failed (EOF, timeout, unexpected exit)."""


class PeerTimeoutError(TransportError):
    """The peer did not answer within the host's wall-clock budget."""


class RemoteError(SpellbenchError):
    """The peer returned a well-formed ``error`` response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    def __reduce__(self) -> tuple:
        # Rebuild from (code, message), so the error can cross processes.
        return (type(self), (self.code, self.message))


class EngineError(RemoteError):
    """An ``error`` response from an environment-role peer."""


class AgentError(RemoteError):
    """An ``error`` response from an agent-role peer."""
