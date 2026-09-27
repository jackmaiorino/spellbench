"""Run secrets and everything derived from them (spec 11.6, 5.3, 16).

The module is not called ``secrets`` so it never shadows the standard library.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

RUN_SECRET_BYTES = 32
_GAME_SECRET_BYTES = 32
_LOW_53_BITS = (1 << 53) - 1


def _hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def _decimal(index: int) -> bytes:
    if type(index) is not int or index < 0:
        raise ValueError("a game index is a nonnegative integer")
    return str(index).encode("ascii")


@dataclass(frozen=True, repr=False)
class RunSecret:
    value: bytes

    def __post_init__(self) -> None:
        if type(self.value) is not bytes or len(self.value) != RUN_SECRET_BYTES:
            raise ValueError("a run secret is exactly 32 bytes")

    def __repr__(self) -> str:
        return "RunSecret(<redacted>)"

    __str__ = __repr__

    @classmethod
    def generate(cls) -> "RunSecret":
        return cls(secrets.token_bytes(RUN_SECRET_BYTES))

    @classmethod
    def from_hex(cls, text: str) -> "RunSecret":
        if type(text) is not str or len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("a run secret is 64 lowercase hex characters")
        return cls(bytes.fromhex(text))

    def hex(self) -> str:
        return self.value.hex()

    def commitment(self) -> str:
        return hashlib.sha256(self.value).hexdigest()

    def game_secret(self, index: int) -> bytes:
        return _hmac(self.value, b"spellbench/v2/game:" + _decimal(index))

    def game_id(self, index: int) -> str:
        return "g-" + _hmac(self.value, b"spellbench/v2/game-id:" + _decimal(index))[:8].hex()

    def agent_seed(self, index: int, seat: str) -> int:
        if seat not in ("p0", "p1"):
            raise ValueError("seat must be p0 or p1")
        digest = _hmac(self.value, b"spellbench/v2/agent-seed:" + _decimal(index) + b":" + seat.encode("ascii"))
        return int.from_bytes(digest[:8], "big") & _LOW_53_BITS

    # Host-internal (not in the spec): the preflight resets of spec 11.1 never use a scheduled game's secret.
    def preflight_secret(self, index: int) -> bytes:
        return _hmac(self.value, b"spellbench/v2/preflight-game:" + _decimal(index))

    def preflight_game_id(self, index: int) -> str:
        return "g-" + _hmac(self.value, b"spellbench/v2/preflight-id:" + _decimal(index))[:8].hex()


def _game_secret(value: bytes) -> bytes:
    """Spec 5.3 and 11.6 key HMAC-SHA256 with the game secret's 32 raw bytes, never its 64-character hex text."""
    if type(value) is not bytes or len(value) != _GAME_SECRET_BYTES:
        raise ValueError("a game secret is exactly 32 raw bytes")
    return value


def id_key(game_secret: bytes) -> bytes:
    return _hmac(_game_secret(game_secret), b"spellbench/v2/object-id")


def object_id(game_secret: bytes, message: str) -> str:
    """The recommended object id of spec 5.3 for message ``"<viewer>:<internal key>[:look:<n>]"``."""
    return "o-" + _hmac(id_key(game_secret), message.encode("utf-8"))[:8].hex()


def stream_seed(game_secret: bytes, label: str) -> bytes:
    """The recommended stream seed of spec 11.6 for label ``"spellbench/v2/rng:<seat or shared>:<purpose>:<n>"``."""
    return _hmac(_game_secret(game_secret), label.encode("ascii"))
