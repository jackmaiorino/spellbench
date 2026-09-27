"""Engine and bot files pinned by hash, verified at launch, and registered (ARTIFACT-LAW.md clauses 4 and 9).

A launch resolves each command once (:func:`resolve_command`: a bare program
name through the PATH; an unexpanded placeholder or a missing program is
refused), hashes the files it names plus declared files such as a bot's
checkpoint (:func:`engine_files`), copies each to
``<pin_root>/<sha256>/<file name>`` and registers each pin directory in the
artifact catalog right after pinning it (:func:`pin_and_register`), through
the collab ``tools/artifact_register.py`` or any script with its command
line. The launcher starts the resolved command, or with
:func:`pinned_command` the pinned copies of self-contained binaries, and
re-hashes what it starts (:func:`verify_files`, :func:`verify_pins`) before
each process and after the last game, so the recorded hashes are the bytes
that ran. Plan the allocation (``arena.throughput.plan_allocation``, with the
pinned bytes) before pinning: it keeps the 60 GiB reserve on the pin root.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

CHUNK_BYTES = 1 << 20
REGISTER_TIMEOUT_S = 60.0
CITED_BY = "cited by: "
_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


class PinningError(Exception):
    """An engine or bot file could not be resolved, hashed, pinned, verified or registered."""


@dataclass(frozen=True)
class EngineFile:
    """One file a command runs with: part ``index`` of the command, or, from ``len(command)`` on, a declared
    file outside the command line (such as a checkpoint).

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


def resolve_command(command: Sequence[str]) -> tuple[str, ...]:
    """``command`` with its program as an absolute path, resolved once: hash and launch this same tuple.

    A bare program name is looked up on the PATH (``shutil.which``), since
    the operating system's own search order can find a different file. An
    empty command, an unexpanded ``${NAME}`` placeholder, or a program that
    is not a regular file is refused, so nothing launches or pins silently
    unrecorded.
    """
    parts = tuple(command)
    if not parts:
        raise PinningError("the command is empty: there is nothing to launch or pin")
    for index, part in enumerate(parts):
        if type(part) is not str:
            raise PinningError(f"command part {index} is not a string: {part!r}")
        placeholder = _PLACEHOLDER.search(part)
        if placeholder:
            raise PinningError(f"command part {index} holds the unexpanded placeholder {placeholder.group(0)}")
    program = parts[0]
    if Path(program).name == program:
        found = shutil.which(program)
        if found is None:
            raise PinningError(f"the program {program!r} is not on the PATH")
        program = found
    path = Path(program).absolute()
    if not path.is_file():
        raise PinningError(f"the program {parts[0]!r} is not a regular file")
    return (str(path), *parts[1:])


def _engine_file(index: int, path: Path) -> EngineFile:
    sha256, size = _sha256_file(path)
    return EngineFile(index=index, file_name=path.name, sha256=sha256, bytes=size, path=path.absolute())


def engine_files(command: Sequence[str], *, extra: Sequence[str | Path] = ()) -> tuple[EngineFile, ...]:
    """The files an engine or subprocess bot runs with, hashed in 1 MiB chunks.

    The program (resolved once, see :func:`resolve_command`), each later
    command part that is an existing regular file, and each declared file in
    ``extra`` (a checkpoint, a data file the program reads without naming it
    in its arguments), which must exist; declared files take the indices
    after the command's parts.
    """
    resolved = resolve_command(command)
    files = [_engine_file(index, Path(part)) for index, part in enumerate(resolved) if index == 0 or Path(part).is_file()]
    for offset, item in enumerate(extra):
        path = Path(item)
        if not path.is_file():
            raise PinningError(f"the declared file {item} is not a regular file")
        files.append(_engine_file(len(resolved) + offset, path))
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
    """Copy through a same-directory ``.tmp`` file, re-hashed before it replaces the target.

    A failed copy leaves no temporary file, and no pin directory when this
    call created it.
    """
    created = not target.parent.exists()
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
        if created:
            with contextlib.suppress(OSError):
                target.parent.rmdir()  # only when empty: a finished pin stays


def pinned_command(command: Sequence[str], files: Sequence[EngineFile], pin_root: Path) -> tuple[str, ...]:
    """``command`` with each part named in ``files`` replaced by its pinned copy.

    Pass only files that run correctly from a copy, such as a self-contained
    binary (the kernel bridge). An interpreter needs the files installed
    beside it and a script may import its neighbours, so those launch from
    :func:`resolve_command`'s paths, checked with :func:`verify_files`.
    """
    parts = list(command)
    for file in files:
        if file.index < len(parts):
            parts[file.index] = str(Path(pin_root) / file.sha256 / file.file_name)
    return tuple(parts)


def verify_files(files: Sequence[EngineFile]) -> None:
    """Re-hash each file where it was hashed; refuse when any differs. Call before each launch and after the last game."""
    for file in files:
        if not file.path.is_file() or _sha256_file(file.path)[0] != file.sha256:
            raise PinningError(f"{file.path} changed since it was hashed (sha256 {file.sha256}); refusing to launch it")


def verify_pins(files: Sequence[EngineFile], pin_root: Path) -> None:
    """Re-hash each pinned copy; refuse when any is missing or differs (for launches from :func:`pinned_command`)."""
    for file in files:
        target = Path(pin_root) / file.sha256 / file.file_name
        if not target.is_file() or _sha256_file(target)[0] != file.sha256:
            raise PinningError(f"pinned file {target} does not match sha256 {file.sha256}")


def _register(register_script: Path, verb: str, path: Path, arguments: Sequence[str], *, python: str,
              timeout_s: float) -> str:
    """Run ``<register_script> <verb> <arguments>`` once for ``path``; returns its standard output."""
    command = [python, str(register_script), verb, *arguments]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise PinningError(f"the artifact register {register_script} did not finish within {timeout_s:g} s") from exc
    except OSError as exc:
        raise PinningError(f"cannot run the artifact register {register_script}: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise PinningError(
            f"the artifact register {register_script} could not {verb} {path} (exit {result.returncode}): {stderr[-200:]}"
        )
    return result.stdout.decode("utf-8", errors="replace")


def _add_arguments(path: Path, *, owner: str, status: str, purpose: str, doc: str, regen: str) -> list[str]:
    return ["--path", str(path), "--lane", "spellbench", "--owner", owner, "--status", status,
            "--retention", "keep-full", "--purpose", purpose, "--doc", doc, "--regen", regen]


def _cite(note: Any, cited_by: str) -> str:
    """``note`` with ``cited_by`` added to its ``cited by:`` list (unchanged when it is already there)."""
    note = note if isinstance(note, str) else ""
    _, found, runs = note.partition(CITED_BY)
    if found:
        return note if cited_by in runs.split("; ") else f"{note}; {cited_by}"
    return f"{note}; {CITED_BY}{cited_by}" if note else CITED_BY + cited_by


def register_pins(
    register_script: Path,
    pinned: Sequence[Path],
    *,
    owner: str,
    purpose: str,
    doc: str,
    regen: str,
    cited_by: str | None = None,
    status: str = "live",
    python: str = sys.executable,
    timeout_s: float = REGISTER_TIMEOUT_S,
) -> None:
    """Register each pinned directory once in the artifact catalog (lane ``spellbench``, kept in full).

    Without ``cited_by`` each directory is added with the given fields. With
    it, the catalog row is looked up first (``show``): a new pin is added
    with the note ``cited by: <cited_by>``, and a pin other runs share is
    updated with ``status`` and this run appended to its note, keeping its
    first purpose and doc (the catalog keeps only the newest row). Each call
    of the script is bounded by ``timeout_s``.
    """
    for directory in dict.fromkeys(Path(item) for item in pinned):
        added = _add_arguments(directory, owner=owner, status=status, purpose=purpose, doc=doc, regen=regen)
        if cited_by is None:
            _register(register_script, "add", directory, added, python=python, timeout_s=timeout_s)
            continue
        shown = _register(register_script, "show", directory, ["--id", str(directory)], python=python, timeout_s=timeout_s)
        try:
            row = json.loads(shown)
        except ValueError:
            row = None  # "not found"
        if isinstance(row, dict):
            note = _cite(row.get("note"), cited_by)
            _register(register_script, "update", directory, ["--id", str(directory), "--status", status, "--note", note],
                      python=python, timeout_s=timeout_s)
        else:
            _register(register_script, "add", directory, [*added, "--note", CITED_BY + cited_by], python=python,
                      timeout_s=timeout_s)


def register_tree(
    register_script: Path,
    path: Path,
    *,
    owner: str,
    status: str,
    purpose: str,
    doc: str,
    regen: str,
    python: str = sys.executable,
    timeout_s: float = REGISTER_TIMEOUT_S,
) -> None:
    """Register one artifact tree, such as a published run directory (ARTIFACT-LAW.md clause 9)."""
    _register(register_script, "add", Path(path),
              _add_arguments(Path(path), owner=owner, status=status, purpose=purpose, doc=doc, regen=regen),
              python=python, timeout_s=timeout_s)


def pin_and_register(
    files: Sequence[EngineFile],
    pin_root: Path,
    register_script: Path,
    *,
    owner: str,
    purpose: str,
    doc: str,
    regen: str,
    cited_by: str,
    python: str = sys.executable,
    timeout_s: float = REGISTER_TIMEOUT_S,
) -> tuple[Path, ...]:
    """Pin each file and register its directory (status live) before pinning the next, so a crash leaves at
    most one pin uncatalogued; returns each file's pin directory."""
    directories: list[Path] = []
    for file in files:
        (directory,) = pin_files([file], pin_root)
        if directory not in directories:
            register_pins(register_script, [directory], owner=owner, purpose=purpose, doc=doc, regen=regen,
                          cited_by=cited_by, status="live", python=python, timeout_s=timeout_s)
        directories.append(directory)
    return tuple(directories)
