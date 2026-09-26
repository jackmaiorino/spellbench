"""Bot registry: identities, canonical descriptors, and the registry artifact.

A registry entry is ``{bot_id, name, version, engine, training_style_tags,
owner, registered_at}``. ``bot_id`` is the lowercase hex SHA-256 of the
canonical JSON (spec section 4.3) of a canonical descriptor:

- builtin bots: ``{"name": ..., "type": "builtin", "version": ...}``
- subprocess bots: ``{"command": [...], "name": ..., "type": "subprocess",
  "version": ...}``, plus a ``"weights_sha256"`` field when the bot was
  registered with a checkpoint path (the hash covers the checkpoint bytes).

``registered_at`` is integer epoch seconds. The arena never reads the wall
clock for artifacts (reruns of an identical config must be byte-identical),
so it defaults to 0 unless the config supplies a value.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..errors import ValidationError
from ..wire import MAX_JSON_INT
from . import store


def _nonempty_str(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise ValidationError(f"{context}: must be a nonempty string")
    return value


def _uint(value: Any, context: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_JSON_INT:
        raise ValidationError(f"{context}: must be an integer in [0, 2^53]")
    return value


def _tags(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValidationError(f"{context}: must be a list of strings")
    out: list[str] = []
    for index, item in enumerate(value):
        out.append(_nonempty_str(item, f"{context}[{index}]"))
    if len(set(out)) != len(out):
        raise ValidationError(f"{context}: duplicate tags")
    return tuple(sorted(out))


@dataclass(frozen=True)
class RegistryEntry:
    bot_id: str
    name: str
    version: str
    engine: str
    training_style_tags: tuple[str, ...] = ()
    owner: str = "unspecified"
    registered_at: int = 0

    def __post_init__(self) -> None:
        _nonempty_str(self.bot_id, "registry_entry.bot_id")
        if len(self.bot_id) != 64 or any(c not in "0123456789abcdef" for c in self.bot_id):
            raise ValidationError("registry_entry.bot_id: must be 64 lowercase hex chars")
        _nonempty_str(self.name, "registry_entry.name")
        _nonempty_str(self.version, "registry_entry.version")
        _nonempty_str(self.engine, "registry_entry.engine")
        _nonempty_str(self.owner, "registry_entry.owner")
        _uint(self.registered_at, "registry_entry.registered_at")
        object.__setattr__(self, "training_style_tags", _tags(list(self.training_style_tags), "registry_entry.training_style_tags"))

    def to_json(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "name": self.name,
            "version": self.version,
            "engine": self.engine,
            "training_style_tags": list(self.training_style_tags),
            "owner": self.owner,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "registry_entry") -> "RegistryEntry":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        store.require_keys(
            value,
            ["bot_id", "name", "version", "engine", "training_style_tags", "owner", "registered_at"],
            context,
        )
        return cls(
            bot_id=value["bot_id"],
            name=value["name"],
            version=value["version"],
            engine=value["engine"],
            training_style_tags=tuple(value["training_style_tags"]),
            owner=value["owner"],
            registered_at=value["registered_at"],
        )


def bot_id_from_descriptor(descriptor: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the identity descriptor."""
    return hashlib.sha256(store.canonical_bytes(descriptor)).hexdigest()


def builtin_descriptor(name: str, version: str) -> dict[str, Any]:
    return {"name": _nonempty_str(name, "bot.name"), "type": "builtin", "version": _nonempty_str(version, "bot.version")}


def subprocess_descriptor(
    name: str,
    version: str,
    command: Sequence[str],
    *,
    weights_sha256: str | None = None,
) -> dict[str, Any]:
    if not command or any(type(part) is not str or not part for part in command):
        raise ValidationError("bot.command: must be a nonempty list of nonempty strings")
    descriptor: dict[str, Any] = {
        "command": list(command),
        "name": _nonempty_str(name, "bot.name"),
        "type": "subprocess",
        "version": _nonempty_str(version, "bot.version"),
    }
    if weights_sha256 is not None:
        if len(weights_sha256) != 64 or any(c not in "0123456789abcdef" for c in weights_sha256):
            raise ValidationError("weights_sha256: must be 64 lowercase hex chars")
        descriptor["weights_sha256"] = weights_sha256
    return descriptor


def checkpoint_sha256(path: Path) -> str:
    """Hash a checkpoint file's bytes; fails closed if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValidationError(f"checkpoint is not readable: {path}: {exc}") from exc


def build_entry(
    *,
    name: str,
    version: str,
    engine: str = "any",
    training_style_tags: Iterable[str] = (),
    owner: str = "unspecified",
    registered_at: int = 0,
    descriptor: dict[str, Any],
) -> RegistryEntry:
    return RegistryEntry(
        bot_id=bot_id_from_descriptor(descriptor),
        name=name,
        version=version,
        engine=engine,
        training_style_tags=tuple(training_style_tags),
        owner=owner,
        registered_at=registered_at,
    )


def write_registry(path: Path, entries: Sequence[RegistryEntry]) -> bytes:
    ids = [entry.bot_id for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValidationError("registry contains duplicate bot_id values")
    document = {
        "schema": store.REGISTRY_SCHEMA,
        "bots": [entry.to_json() for entry in sorted(entries, key=lambda entry: entry.bot_id)],
    }
    return store.write_json_atomic(path, document)


def read_registry(path: Path) -> tuple[RegistryEntry, ...]:
    document = store.read_json(path, schema=store.REGISTRY_SCHEMA)
    store.require_keys(document, ["schema", "bots"], "registry")
    bots = document["bots"]
    if not isinstance(bots, list):
        raise ValidationError("registry.bots: must be a list")
    entries = tuple(RegistryEntry.from_json(item, f"registry.bots[{index}]") for index, item in enumerate(bots))
    ids = [entry.bot_id for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValidationError("registry contains duplicate bot_id values")
    return entries
