"""Shared test doubles: an in-process peer that answers from a script."""

from __future__ import annotations

import collections
import hashlib
import os
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep this CI shard's tests when SPELLBENCH_TEST_SHARD is "index/count".

    CI splits the Windows run across parallel jobs. Each test goes to a shard by
    a hash of its node id, and every test in one xdist_group goes by the group
    name instead, so --dist loadgroup still sees each group whole. The hook sees
    every collected item, integrations included, as long as python/tests is
    among the collected paths.
    """
    shard = os.environ.get("SPELLBENCH_TEST_SHARD")
    if not shard:
        return
    index, count = (int(part) for part in shard.split("/"))
    if not 1 <= index <= count:
        raise pytest.UsageError(f"SPELLBENCH_TEST_SHARD must be index/count with 1 <= index <= count, got {shard!r}")
    keep, drop = [], []
    for item in items:
        group = item.get_closest_marker("xdist_group")
        key = f"group:{group.args[0]}" if group and group.args else item.nodeid
        digest = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        (keep if digest % count == index - 1 else drop).append(item)
    items[:] = keep
    config.hook.pytest_deselected(items=drop)
