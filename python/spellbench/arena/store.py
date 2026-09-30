"""Canonical JSON tournament artifacts and atomic publish (spec section 4.3).

All arena artifacts are canonical JSON: UTF-8, keys sorted by code point,
compact separators, integers only (floats are rejected by
:func:`spellbench.wire.canonical_json_dumps`, so ratings are stored as
fixed-point integers and ratios as ``{"num": ..., "den": ...}`` pairs).

Schema identities (literals, not imports, so the owning modules can never
cycle back through this one; a test pins them to the owners' constants):

- ``spellbench-tournament/v2``: ``manifest.json``, the publish boundary.
- ``spellbench-match-ledger/v2``: ``matches.jsonl``, one row per game.
- ``spellbench-bot-registry/v1``: ``registry.json``.
- ``spellbench-leaderboard/v2``: ``leaderboard.json``.
- ``spellbench-tournament-config/v2``: ``config.json``, the normalized
  canonical copy of the run configuration.

Atomic publish: every data file is written (and fsynced) first;
``manifest.json``, which carries the sha256 and byte count of each data
file, is written last. A directory with a manifest is a complete,
verifiable tournament; a directory without one is partial.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from ..errors import ValidationError
from ..wire import canonical_json_dumps, strict_json_loads

TOURNAMENT_SCHEMA = "spellbench-tournament/v2"
LEDGER_SCHEMA = "spellbench-match-ledger/v2"
REGISTRY_SCHEMA = "spellbench-bot-registry/v1"
LEADERBOARD_SCHEMA = "spellbench-leaderboard/v2"
CONFIG_SCHEMA = "spellbench-tournament-config/v2"

MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "config.json"
REGISTRY_NAME = "registry.json"
LEDGER_NAME = "matches.jsonl"
LEADERBOARD_JSON_NAME = "leaderboard.json"
LEADERBOARD_MD_NAME = "LEADERBOARD.md"
# The run secret's commitment (and the run's benchmark and label), written before
# any game (spec 11.6, Decision 9); its document lives in ``manifest.py``.
COMMITMENT_NAME = "COMMITMENT.json"
# Raw failure text (peer stderr, OS errors) per adjudicated game. Deliberately
# outside the manifest: it is not deterministic and not part of the result.
DIAGNOSTICS_NAME = "diagnostics.jsonl"

# Data files in publish order; the manifest is always last.
DATA_FILE_NAMES = (
    CONFIG_NAME,
    REGISTRY_NAME,
    LEDGER_NAME,
    LEADERBOARD_JSON_NAME,
    LEADERBOARD_MD_NAME,
)


class StoreError(Exception):
    """A tournament artifact store operation failed."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON bytes (spec section 4.3); rejects floats and non-JSON types."""
    return canonical_json_dumps(value)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (same-directory tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_json_atomic(path: Path, value: Any) -> bytes:
    """Write one canonical JSON document; returns the bytes written."""
    data = canonical_bytes(value) + b"\n"
    write_bytes_atomic(path, data)
    return data


def append_ledger_row(path: Path, row: Any) -> None:
    """Append one canonical JSON line to the match ledger and flush."""
    line = canonical_bytes(row) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def append_diagnostics(path: Path, game_id: str, diagnostics: Iterable[str]) -> None:
    """Append one diagnostics record (ASCII-escaped JSON; never hashed)."""
    line = json.dumps({"game_id": game_id, "diagnostics": list(diagnostics)}, ensure_ascii=True)
    with open(path, "a", encoding="ascii", newline="\n") as handle:
        handle.write(line + "\n")


def file_entry(path: Path, name: str) -> dict[str, Any]:
    """The manifest entry for one data file: name, sha256, byte count."""
    data = path.read_bytes()
    return {"path": name, "sha256": sha256_hex(data), "bytes": len(data)}


def publish_manifest(directory: Path, manifest: dict[str, Any]) -> bytes:
    """Write ``manifest.json``, the publish boundary, always last.

    The caller must have written (and flushed) every data file listed in
    ``manifest["files"]`` before calling this.
    """
    if manifest.get("schema") != TOURNAMENT_SCHEMA:
        raise StoreError(f"manifest schema must be {TOURNAMENT_SCHEMA!r}")
    return write_json_atomic(directory / MANIFEST_NAME, manifest)


def read_json(path: Path, *, schema: str | None = None) -> dict[str, Any]:
    """Read one single-line canonical JSON document, fail closed."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    lines = raw.split(b"\n")
    if len(lines) > 2 or (len(lines) == 2 and lines[1] != b""):
        raise StoreError(f"{path} is not a single-line canonical JSON document")
    try:
        value = strict_json_loads(lines[0])
    except Exception as exc:
        raise StoreError(f"{path} is not strict JSON: {exc}") from exc
    if schema is not None and value.get("schema") != schema:
        raise StoreError(f"{path} schema must be {schema!r}, got {value.get('schema')!r}")
    return value


def read_jsonl(path: Path, *, schema: str | None = None) -> list[dict[str, Any]]:
    """Read an NDJSON artifact, validating the schema tag of every row."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.split(b"\n")):
        if line == b"":
            continue
        try:
            value = strict_json_loads(line)
        except Exception as exc:
            raise StoreError(f"{path} line {index + 1} is not strict JSON: {exc}") from exc
        if schema is not None and value.get("schema") != schema:
            raise StoreError(
                f"{path} line {index + 1} schema must be {schema!r}, got {value.get('schema')!r}"
            )
        rows.append(value)
    return rows


def prepare_tournament_dir(directory: Path, *, allowed: Iterable[str] = ()) -> None:
    """Fail closed unless ``directory`` is absent or holds only entries the caller named.

    The arena overwrites no run: a directory that holds anything outside ``allowed``
    (for v2, at most a ``COMMITMENT.json`` made for this run) is refused.
    """
    if directory.exists():
        if not directory.is_dir():
            raise StoreError(f"tournament dir path is not a directory: {directory}")
        admitted = set(allowed)
        unexpected = sorted(entry.name for entry in directory.iterdir() if entry.name not in admitted)
        if unexpected:
            raise StoreError(f"tournament dir is not empty (refusing to overwrite): {directory}")
    else:
        directory.mkdir(parents=True)


def is_published(directory: Path) -> bool:
    return (directory / MANIFEST_NAME).is_file()


def verify_file_digests(directory: Path, manifest: dict[str, Any]) -> list[str]:
    """Recompute every manifest file digest; returns a list of mismatches."""
    failures: list[str] = []
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["manifest.files is missing or not a list"]
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            failures.append(f"invalid manifest file entry: {entry!r}")
            continue
        name = entry["path"]
        if type(name) is not str or name in seen:
            failures.append(f"invalid or duplicate manifest path: {name!r}")
            continue
        seen.add(name)
        path = directory / name
        if not path.is_file():
            failures.append(f"missing file: {name}")
            continue
        actual = file_entry(path, name)
        if actual["sha256"] != entry["sha256"] or actual["bytes"] != entry["bytes"]:
            failures.append(f"digest mismatch: {name}")
    return failures


def require_keys(value: dict[str, Any], expected: Iterable[str], context: str) -> None:
    """Exact-key-set validation for arena artifact objects (fail closed)."""
    expected_set = set(expected)
    actual = set(value)
    if actual != expected_set:
        raise ValidationError(
            f"{context}: fields mismatch: missing={sorted(expected_set - actual)} "
            f"extra={sorted(actual - expected_set)}"
        )


