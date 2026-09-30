"""Shared test doubles: an in-process peer that answers from a script."""

from __future__ import annotations

import collections
from typing import Any, Deque

import pytest

from spellbench import wire
from spellbench.errors import TransportError


def payload(message: dict[str, Any]) -> bytes:
    """Canonical line payload (no newline), as ScriptedPeer responses carry."""
    return wire.canonical_json_dumps(message)


class ScriptedPeer:
    """In-process fake peer: queued response payloads (or exceptions)."""

    def __init__(self, responses: list[bytes | BaseException] | None = None) -> None:
        self.responses: Deque[bytes | BaseException] = collections.deque(responses or [])
        self.sent: list[bytes] = []
        self.closed = False

    def write_line(self, data: bytes) -> None:
        if self.closed:
            raise TransportError("peer is closed")
        self.sent.append(data)

    def read_line(self) -> bytes:
        if not self.responses:
            raise TransportError("script exhausted")
        item = self.responses.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def scripted_peer() -> ScriptedPeer:
    return ScriptedPeer()
