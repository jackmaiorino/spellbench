"""Engine files pinned by hash and registered (ARTIFACT-LAW.md clauses 4 and 9).

A rated run records the SHA-256 of every file its engine command names
(:func:`engine_files`), copies each one to ``<pin_root>/<sha256>/<file name>``
before the first game (:func:`pin_files`), and registers every pinned
directory in the artifact catalog through the collab
``tools/artifact_register.py``, or any script with its command line
(:func:`register_pins`).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

CHUNK_BYTES = 1 << 20


class PinningError(Exception):
    """An engine file could not be hashed, pinned or registered."""


@dataclass(frozen=True)
class EngineFile:
    """One part of the engine command that names a regular file.

    ``path`` locates the file on this machine; it is not part of the
    identity (comparison) or of the published record (:meth:`to_json`).
    """

    index: int
    file_name: str
    sha256: str
    bytes: int
    path: Path = field(compare=False)

    def to_json(self) -> dict[str, Any]:
        return {"index": self.index, "file_name": self.file_name, "sha256": self.sha256, "bytes": self.bytes}


def _sha256_file(path: Path) -> tuple[str, int]:
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


def engine_files(command: Sequence[str]) -> tuple[EngineFile, ...]:
    """The command parts that are existing regular files, hashed; a bare part 0 is looked up on the PATH."""
    files = []
    for index, part in enumerate(command):
        text = part
        if index == 0 and part and Path(part).name == part:
            text = shutil.which(part) or part
        path = Path(text)
        if not path.is_file():
            continue
        sha256, size = _sha256_file(path)
        files.append(EngineFile(index=index, file_name=path.name, sha256=sha256, bytes=size, path=path.absolute()))
    return tuple(files)


def pin_files(files: Sequence[EngineFile], pin_root: Path) -> tuple[Path, ...]:
    """Copy each file to ``<pin_root>/<sha256>/<file_name>``; returns each file's pin directory.

    An existing pin is re-hashed and kept (pinning is idempotent); a pin
    whose bytes no longer match its hash is an error, and so is a source
    file that changed after :func:`engine_files` hashed it.
    """
    directories = []
    for file in files:
        directory = Path(pin_root) / file.sha256
        target = directory / file.file_name
        if target.exists():
            if _sha256_file(target)[0] != file.sha256:
                raise PinningError(f"pinned file {target} does not match sha256 {file.sha256}")
        else:
            _copy_verified(file, target)
        directories.append(directory)
    return tuple(directories)


def _copy_verified(file: EngineFile, target: Path) -> None:
    """Copy through a same-directory ``.tmp`` file, re-hashed before it replaces the target."""
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file.path, tmp)
        if _sha256_file(tmp)[0] != file.sha256:
            raise PinningError(f"engine file {file.path} changed after it was hashed (sha256 {file.sha256}); not pinned")
        os.replace(tmp, target)
    except OSError as exc:
        raise PinningError(f"cannot pin {file.path} in {target.parent}: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def register_pins(
    register_script: Path,
    pinned: Sequence[Path],
    *,
    owner: str,
    purpose: str,
    doc: str,
    regen: str,
    python: str = sys.executable,
) -> None:
    """Register each pinned directory in the artifact catalog (lane ``spellbench``, kept in full)."""
    for directory in pinned:
        command = [
            python, str(register_script), "add", "--path", str(directory), "--lane", "spellbench", "--owner", owner,
            "--status", "live", "--retention", "keep-full", "--purpose", purpose, "--doc", doc, "--regen", regen,
        ]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, check=False)
        except OSError as exc:
            raise PinningError(f"cannot run the artifact register {register_script}: {exc}") from exc
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise PinningError(
                f"registering {directory} with {register_script} failed (exit {result.returncode}): {stderr[-200:]}"
            )
