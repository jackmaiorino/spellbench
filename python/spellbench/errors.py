"""Error types and the closed protocol error-code sets (spec sections 7.6, 10.5)."""

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


ENGINE_ERROR_CODES = frozenset(
    {
        "malformed_json",
        "malformed_request",
        "protocol_mismatch",
        "request_id_reuse_mismatch",
        "step_before_reset",
        "game_already_active",
        "game_id_mismatch",
        "expected_step_mismatch",
        "candidate_id_out_of_range",
        "semantic_echo_mismatch",
        "unsupported_format",
        "unsupported_deck",
        "game_already_terminal",
    }
)

AGENT_ERROR_CODES = frozenset(
    {
        "malformed_json",
        "malformed_request",
        "protocol_mismatch",
        "request_id_reuse_mismatch",
        "unknown_game",
        "no_pending_decision",
        "decision_pending",
        "game_already_active",
        "internal_error",
    }
)
