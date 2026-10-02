"""Verify declared launch files without depending on the benchmark or arena runner."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from .arena.manifest import EngineFile

CHUNK_BYTES = 1 << 20


class PinningError(Exception):
    """A declared launch file could not be resolved, pinned or verified."""


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise PinningError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest(), size


def verify_files(files: Sequence[EngineFile]) -> None:
    """Refuse changed original inputs before launching and before rated publication."""
    for file in files:
        if file.path is None or not file.path.is_file() or sha256_file(file.path)[0] != file.sha256:
            raise PinningError(f"{file.path} changed since it was hashed (sha256 {file.sha256}); refusing to launch it")
