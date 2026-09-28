"""The host's client of one v2 engine process (spec 9).

Performs the ``hello`` handshake, drives ``reset``/``step``/``validate_deck``, and
checks the binding on every answer (spec 9.3 to 9.5): each answer echoes the
``request_id``; decisions and terminals echo the ``game_id``; the first decision has
``step`` 0 and each later one the previous plus 1; a terminal's ``step_count`` equals
the answered count. Provenance drift and ``decision_count`` are the validator's and
the game loop's (spec 11.3, 11.5), not checked here.

Idempotent retry (spec 4.1): a single outstanding request; ``retry_last`` retransmits
the last request byte-identically. ``send_raw`` and ``send_line`` are conformance
probes: they send anything, return the strict-parsed answer, and change no state.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Mapping, Sequence

from .. import wire
from .._client import Peer
from ..errors import EngineError, ProtocolError, ValidationError
from ..messages import (
    ENGINE_ERROR_CODES,
    PROTOCOL_MINOR,
    Decision,
    DeckOk,
    DeckRow,
    EnvHelloOk,
    ErrorResponse,
    HelloRequest,
    ResetRequest,
    Selection,
    StepRequest,
    Terminal,
    ValidateDeckRequest,
)

# Reason prefixes only the host records (spec 11.3, 11.5): an engine terminal
# carrying one impersonates the host.
_HOST_REASON_PREFIXES = ("host_validator:", "host_engine_fault:", "forfeit:")


class TerminalCountError(ProtocolError):
    """A terminal whose ``step_count`` differs from the answered count (R2-3).

    Carries the parsed terminal, so the game loop can halt the game as
    ``host_engine_fault:terminal_counts`` rather than ``malformed``.
    """

    def __init__(self, message: str, terminal: Terminal) -> None:
        super().__init__(message)
        self.terminal = terminal


class TerminalReasonError(ProtocolError):
    """A terminal whose ``reason`` starts with a host-only prefix: the engine impersonates the host.

    Carries the parsed terminal, so the game loop can halt the game as
    ``host_engine_fault:terminal_reason``.
    """

    def __init__(self, message: str, terminal: Terminal) -> None:
        super().__init__(message)
        self.terminal = terminal


class EngineProcess:
    """A client of one engine process (at most one active game per process)."""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        *,
        peer: Peer | None = None,
        timeout_s: float | None = None,
    ) -> None:
        if peer is None:
            if argv is None:
                raise ValueError("either argv or peer is required")
            peer = wire.SubprocessPeer(argv, timeout_s=timeout_s)
        self._peer = peer
        self._request_counter = 0
        self._pending: tuple[dict[str, Any], bytes] | None = None
        self._last: tuple[dict[str, Any], bytes, bytes, Any] | None = None
        self._closed = False
        self._hello: EnvHelloOk | None = None
        self._game_id: str | None = None
        self._expected_step: int | None = None
        # Answered decisions of the active game: 0 after reset, plus 1 per answer
        # holding a decision (spec 9.5: step_count counts the answered decisions).
        self._answered = 0
        self.last_request: dict[str, Any] | None = None
        self.last_response: dict[str, Any] | None = None

    @property
    def hello_result(self) -> EnvHelloOk | None:
        return self._hello

    def next_request_id(self) -> str:
        """The next request id, ``h-<n>`` from 1."""
        self._request_counter += 1
        return f"h-{self._request_counter}"

    def set_timeout(self, seconds: float | None) -> None:
        """Change the read budget of a spawned peer (injected peers are left alone)."""
        setter = getattr(self._peer, "set_timeout", None)
        if setter is not None:
            setter(seconds)

    def stderr_text(self) -> str:
        """The spawned peer's captured stderr, or "" for an injected peer."""
        reader = getattr(self._peer, "stderr_text", None)
        return reader() if reader is not None else ""

    def hello(self, *, protocol_minor: int = PROTOCOL_MINOR) -> EnvHelloOk:
        if self._hello is not None:
            raise ProtocolError("hello already completed for this process")
        request = HelloRequest(request_id=self.next_request_id(), protocol_minor=protocol_minor)
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, EnvHelloOk)
        return result

    def reset(self, request: ResetRequest) -> Decision | Terminal:
        if self._hello is None:
            raise ProtocolError("reset before hello")
        if self._game_id is not None:
            raise ProtocolError("a game is already active on this process")
        response, response_line = self._exchange(request.to_json())
        return self._validate_response(response, request.to_json(), response_line)

    def step(self, *, candidate_id: int, semantic: Mapping[str, Any]) -> Decision | Terminal:
        """Select a candidate of the active decision, echoing its ``semantic`` (spec 9.4)."""
        if self._game_id is None or self._expected_step is None:
            raise ProtocolError("step without an active decision")
        request = StepRequest(
            request_id=self.next_request_id(),
            game_id=self._game_id,
            expected_step=self._expected_step,
            selection=Selection(candidate_id=candidate_id, semantic_echo=dict(semantic)),
        )
        response, response_line = self._exchange(request.to_json())
        return self._validate_response(response, request.to_json(), response_line)

    def validate_deck(
        self,
        *,
        format: str,
        catalog_id: str | None = None,
        decklist: Sequence[Mapping[str, Any]] | None = None,
    ) -> DeckOk:
        if self._hello is None:
            raise ProtocolError("validate_deck before hello")
        rows = None if decklist is None else tuple(DeckRow(row["name"], row["count"]) for row in decklist)
        request = ValidateDeckRequest(
            request_id=self.next_request_id(), format=format, catalog_id=catalog_id, decklist=rows
        )
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, DeckOk)
        return result

    def send_raw(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """A conformance probe: send any message, return the strict-parsed answer, change no state."""
        return self.send_line(wire.canonical_json_dumps(message))

    def send_line(self, payload: bytes) -> dict[str, Any]:
        """A conformance probe: send any bytes, return the strict-parsed answer, change no state."""
        if self._closed:
            raise ProtocolError("client is closed")
        self._peer.write_line(payload)
        return wire.strict_json_loads(self._peer.read_line())

    def retry_last(self) -> Any:
        """Retransmit the last request byte-identically (spec 4.1)."""
        if self._closed:
            raise ProtocolError("client is closed")
        if self._pending is not None:
            request, line = self._pending
            self._peer.write_line(line)
            response_line = self._peer.read_line()
            response = wire.strict_json_loads(response_line)
            self.last_response = response
            return self._validate_response(response, request, response_line)
        if self._last is None:
            raise ProtocolError("no request to retry")
        request, line, response_line, result = self._last
        self._peer.write_line(line)
        replay_line = self._peer.read_line()
        if replay_line != response_line:
            raise ProtocolError("idempotent retry returned a different response")
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._peer.close()

    def __enter__(self) -> "EngineProcess":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # ------------------------------------------------------------------

    def _exchange(self, request: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        """Write one request line and read the strict-parsed response line."""
        if self._closed:
            raise ProtocolError("client is closed")
        if self._pending is not None:
            raise ProtocolError("a request exchange is incomplete; call retry_last()")
        line = wire.canonical_json_dumps(request)
        self._peer.write_line(line)
        self._pending = (request, line)
        self.last_request = request
        self.last_response = None
        try:
            response_line = self._peer.read_line()
        except BaseException:
            # The request may or may not have been applied; keep _pending so
            # retry_last() can retransmit the identical line.
            raise
        response = wire.strict_json_loads(response_line)
        self.last_response = response
        return response, response_line

    def _commit(self, request: dict[str, Any], response_line: bytes, result: Any) -> Any:
        line = wire.canonical_json_dumps(request)
        self._pending = None
        self._last = (request, line, response_line, result)
        return result

    def _validate_response(
        self,
        response: dict[str, Any],
        request: dict[str, Any],
        response_line: bytes,
    ) -> EnvHelloOk | Decision | Terminal | DeckOk:
        response_type = response.get("response_type")
        if response_type == "error":
            try:
                error = ErrorResponse.from_json(response, codes=ENGINE_ERROR_CODES)
            except ValidationError as exc:
                raise ProtocolError(f"invalid error response from engine: {exc}") from exc
            if error.request_id != request["request_id"]:
                raise ProtocolError("error response request_id mismatch")
            remote = EngineError(error.code, error.message)
            self._commit(request, response_line, remote)
            raise remote
        if response_type == "hello_ok":
            if request["request_type"] != "hello":
                raise ProtocolError("hello_ok response to a non-hello request")
            try:
                hello_ok = EnvHelloOk.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid hello_ok from engine: {exc}") from exc
            if hello_ok.request_id != request["request_id"]:
                raise ProtocolError("hello_ok request_id mismatch")
            if hello_ok.protocol_minor > request["protocol_minor"]:
                raise ProtocolError(
                    f"hello_ok protocol_minor {hello_ok.protocol_minor} exceeds "
                    f"the requested {request['protocol_minor']}"
                )
            self._hello = hello_ok
            return self._commit(request, response_line, hello_ok)
        if response_type == "decision":
            if request["request_type"] not in ("reset", "step"):
                raise ProtocolError("decision response to a non-reset/step request")
            try:
                decision = Decision.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid decision from engine: {exc}") from exc
            self._validate_decision(decision, request)
            return self._commit(request, response_line, decision)
        if response_type == "terminal":
            if request["request_type"] not in ("reset", "step"):
                raise ProtocolError("terminal response to a non-reset/step request")
            try:
                terminal = Terminal.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid terminal from engine: {exc}") from exc
            self._validate_terminal(terminal, request)
            return self._commit(request, response_line, terminal)
        if response_type == "deck_ok":
            if request["request_type"] != "validate_deck":
                raise ProtocolError("deck_ok response to a non-validate_deck request")
            try:
                deck_ok = DeckOk.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid deck_ok from engine: {exc}") from exc
            if deck_ok.request_id != request["request_id"]:
                raise ProtocolError("deck_ok request_id mismatch")
            return self._commit(request, response_line, deck_ok)
        raise ProtocolError(f"unsupported response_type from engine: {response_type!r}")

    def _validate_decision(self, decision: Decision, request: dict[str, Any]) -> None:
        if decision.request_id != request["request_id"]:
            raise ProtocolError("response request_id mismatch")
        if decision.game_id != request["game_id"]:
            raise ProtocolError("response game_id mismatch")
        # The first decision has step 0, each later one the previous plus 1 (spec 9.3).
        expected_step = 0 if request["request_type"] == "reset" else request["expected_step"] + 1
        if decision.step != expected_step:
            raise ProtocolError(f"decision step drift: expected {expected_step}, got {decision.step}")
        self._game_id = decision.game_id
        self._expected_step = decision.step
        self._answered += 1

    def _validate_terminal(self, terminal: Terminal, request: dict[str, Any]) -> None:
        if terminal.request_id != request["request_id"]:
            raise ProtocolError("response request_id mismatch")
        if terminal.game_id != request["game_id"]:
            raise ProtocolError("response game_id mismatch")
        # Compared without case, whitespace or compatibility forms: "Forfeit:timeout" and " forfeit:x" read as host reasons too.
        reason = "".join(unicodedata.normalize("NFKC", terminal.result.reason).casefold().split())
        for prefix in _HOST_REASON_PREFIXES:
            if reason.startswith(prefix):
                raise TerminalReasonError(
                    f"terminal reason starts with the host-only prefix {prefix!r}", terminal
                )
        if terminal.result.step_count != self._answered:
            raise TerminalCountError(
                f"terminal step_count {terminal.result.step_count} does not match "
                f"the answered count {self._answered}",
                terminal,
            )
        self._game_id = None
        self._expected_step = None
        self._answered = 0
