"""Shared machinery for the host-side role clients (engine_client, agent_client).

Implements request-id generation, the single-outstanding-request exchange, and
the client side of the single-entry idempotent retry (spec section 4.1):
``retry_last`` retransmits the last request byte-identically. If the previous
exchange completed, the peer must answer with the byte-identical cached
response; if the previous exchange lost its response, the retransmission is
validated and committed as normal.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from . import wire
from .errors import ProtocolError


class Peer(Protocol):
    """Framed line transport used by the role clients.

    Payloads exclude the line terminator; the transport adds it on write and
    strips it on read.
    """

    def write_line(self, payload: bytes) -> None: ...

    def read_line(self) -> bytes: ...

    def close(self) -> None: ...


class RoleClient:
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
        self._used_request_ids: set[str] = set()
        self._pending: tuple[dict[str, Any], bytes] | None = None
        self._last: tuple[dict[str, Any], bytes, bytes, Any] | None = None
        self._closed = False

    def set_timeout(self, timeout_s: float | None) -> None:
        """Change the read budget of a spawned peer (injected peers are left alone)."""
        setter = getattr(self._peer, "set_timeout", None)
        if setter is not None:
            setter(timeout_s)

    def _next_request_id(self) -> str:
        while True:
            self._request_counter += 1
            candidate = f"h-{self._request_counter}"
            if candidate not in self._used_request_ids:
                return candidate

    def _claim_request_id(self, request_id: str) -> None:
        if request_id in self._used_request_ids:
            raise ProtocolError(f"request_id already used by this client: {request_id!r}")
        self._used_request_ids.add(request_id)

    def _exchange(self, request: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        """Write one request line and read the strict-parsed response line."""
        if self._closed:
            raise ProtocolError("client is closed")
        if self._pending is not None:
            raise ProtocolError("a request exchange is incomplete; call retry_last()")
        line = wire.canonical_json_dumps(request)
        self._peer.write_line(line)
        self._pending = (request, line)
        try:
            response_line = self._peer.read_line()
        except BaseException:
            # The request may or may not have been applied; keep _pending so
            # retry_last() can retransmit the identical line.
            raise
        response = wire.strict_json_loads(response_line)
        return response, response_line

    def _commit(self, request: dict[str, Any], response_line: bytes, result: Any) -> Any:
        line = wire.canonical_json_dumps(request)
        self._pending = None
        self._last = (request, line, response_line, result)
        return result

    def retry_last(self) -> Any:
        """Retransmit the last request byte-identically (spec section 4.1)."""
        if self._closed:
            raise ProtocolError("client is closed")
        if self._pending is not None:
            request, line = self._pending
            self._peer.write_line(line)
            response_line = self._peer.read_line()
            response = wire.strict_json_loads(response_line)
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

    def _validate_response(
        self,
        response: dict[str, Any],
        request: dict[str, Any],
        response_line: bytes,
    ) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._peer.close()

    def __enter__(self) -> "RoleClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
