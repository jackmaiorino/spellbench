"""The host's client of one agent process (spec 10).

Performs the ``hello`` handshake and drives ``game_start``/``choose``/``game_over``. Every
failure, on either the write or the read side, is mapped to a :class:`~spellbench.host.seat.SeatFailure`
whose ``cause`` is one of the forfeit causes of spec 11.5; nothing the peer said or wrote
(its stderr, a raw line, an error's message) ever reaches the failure's ``detail`` (R2-15).

Writes are bounded by the same budget as reads (R2-5): a pipe to a bot that stopped reading
blocks the writer once its OS buffer fills (about 4 KiB on Windows, 64 KiB on Linux), and a
``choose`` request carries the whole board, so it is exactly the request most likely to fill
one. ``_write`` therefore writes on a daemon helper thread and waits at most ``timeout_s``;
on expiry it closes the peer (killing a subprocess bot) and raises a timeout failure, exactly
as a read timeout would.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping, Sequence, TypeVar

from .. import wire
from .._client import Peer
from ..agent_messages import AGENT_ERROR_CODES, AgentHelloOk, Choice, read_ack, read_error, request
from ..errors import MalformedJsonError, PeerTimeoutError, TransportError, ValidationError
from ..messages import PROTOCOL_MINOR
from .seat import SeatFailure

_T = TypeVar("_T")


def _ms(seconds: float | None) -> int | None:
    return None if seconds is None else round(seconds * 1000)


class AgentProcess:
    """A client of one agent-role process: the hello handshake, then any number of games in turn."""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        *,
        peer: Peer | None = None,
        startup_timeout_s: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if peer is None:
            if argv is None:
                raise ValueError("either argv or peer is required")
            peer = wire.SubprocessPeer(argv, timeout_s=startup_timeout_s, env=env)
        self._peer = peer
        self._startup_timeout_s = startup_timeout_s
        self._count = 0

    def stderr_text(self) -> str:
        """The spawned peer's captured stderr, or "" for an injected peer."""
        reader = getattr(self._peer, "stderr_text", None)
        return reader() if reader is not None else ""

    def hello(self) -> AgentHelloOk:
        request_id, response = self._exchange(
            "hello", {"protocol_minor": PROTOCOL_MINOR}, timeout_s=self._startup_timeout_s, phase="hello"
        )
        return self._read(response, phase="hello", reader=lambda value: AgentHelloOk.from_json(value, request_id=request_id))

    def game_start(self, payload: Mapping[str, Any], *, timeout_s: float) -> None:
        request_id, response = self._exchange("game_start", payload, timeout_s=timeout_s, phase="game_start")
        self._read(response, phase="game_start", reader=lambda value: read_ack(value, request_id=request_id))

    def choose(self, payload: Mapping[str, Any], *, timeout_s: float) -> Choice:
        request_id, response = self._exchange("choose", payload, timeout_s=timeout_s, phase="choose")
        return self._read(response, phase="choose", reader=lambda value: Choice.from_json(value, request_id=request_id))

    def game_over(self, payload: Mapping[str, Any], *, timeout_s: float) -> None:
        request_id, response = self._exchange("game_over", payload, timeout_s=timeout_s, phase="game_over")
        self._read(response, phase="game_over", reader=lambda value: read_ack(value, request_id=request_id))

    def close(self) -> None:
        self._peer.close()

    def __enter__(self) -> "AgentProcess":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # ------------------------------------------------------------------

    def _write(self, line: bytes, *, timeout_s: float | None, phase: str) -> None:
        """Write ``line`` on a helper thread, bounded by ``timeout_s`` (R2-5)."""
        outcome: list[BaseException | None] = [None]

        def target() -> None:
            try:
                self._peer.write_line(line)
            except BaseException as exc:  # noqa: BLE001 - handed back to the caller to map
                outcome[0] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout_s)
        if thread.is_alive():
            # The bot never read this request: close (kill a subprocess) rather than leak it.
            self._peer.close()
            raise SeatFailure("timeout", f"the bot did not read {phase} within {_ms(timeout_s)} ms", diagnostic=self.stderr_text())
        exc = outcome[0]
        if exc is None:
            return
        if isinstance(exc, PeerTimeoutError):
            raise SeatFailure(
                "timeout", f"no answer to {phase} within {_ms(timeout_s)} ms", diagnostic=f"{exc}\n{self.stderr_text()}"
            ) from exc
        if isinstance(exc, TransportError):
            raise SeatFailure(
                "transport_error", f"the bot process failed during {phase}", diagnostic=f"{exc}\n{self.stderr_text()}"
            ) from exc
        raise exc

    def _exchange(
        self, request_type: str, payload: Mapping[str, Any], *, timeout_s: float | None, phase: str
    ) -> tuple[str, dict[str, Any]]:
        """Send one request and return ``(request_id, response)``; an error envelope raises directly."""
        request_id = f"r-{self._count}"
        self._count += 1
        line = wire.canonical_json_dumps(request(request_type, request_id, payload))
        self._write(line, timeout_s=timeout_s, phase=phase)
        setter = getattr(self._peer, "set_timeout", None)
        if setter is not None:
            setter(timeout_s)
        try:
            raw = self._peer.read_line()
            response = wire.strict_json_loads(raw)
        except PeerTimeoutError as exc:
            raise SeatFailure(
                "timeout", f"no answer to {phase} within {_ms(timeout_s)} ms", diagnostic=f"{exc}\n{self.stderr_text()}"
            ) from exc
        except TransportError as exc:
            raise SeatFailure(
                "transport_error", f"the bot process failed during {phase}", diagnostic=f"{exc}\n{self.stderr_text()}"
            ) from exc
        except MalformedJsonError as exc:
            raise SeatFailure(
                "malformed_response",
                f"the answer to {phase} was not a valid protocol message",
                diagnostic=f"{exc}\n{self.stderr_text()}",
            ) from exc
        try:
            error = read_error(response, request_id=request_id)
        except ValidationError as exc:
            raise SeatFailure(
                "malformed_response",
                f"the answer to {phase} was not a valid protocol message",
                diagnostic=f"{exc}\n{self.stderr_text()}",
            ) from exc
        if error is not None:
            code, message = error
            quoted = f" ({code})" if code in AGENT_ERROR_CODES else ""
            raise SeatFailure(
                "agent_error", f"{phase} was answered with an error{quoted}", diagnostic=f"{message}\n{self.stderr_text()}"
            )
        return request_id, response

    def _read(self, response: dict[str, Any], *, phase: str, reader: Callable[[dict[str, Any]], _T]) -> _T:
        """Apply ``reader`` to ``response``, mapping a binding or field failure to ``malformed_response``."""
        try:
            return reader(response)
        except ValidationError as exc:
            raise SeatFailure(
                "malformed_response",
                f"the answer to {phase} was not a valid protocol message",
                diagnostic=f"{exc}\n{self.stderr_text()}",
            ) from exc
