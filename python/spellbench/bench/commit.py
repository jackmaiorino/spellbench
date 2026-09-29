"""A rated run's commitment, pushed before its secret exists; the run's lock; its reveal (spec 11.6; Decision 9).

:func:`commit_run` (``spellbench bench commit``) publishes a run's commitment before its first game, in this
order (R3-8, R3-14):

1. It checks the local values the rated run will need, so a missing one never burns a published commitment:
   ``SPELLBENCH_PIN_ROOT`` set, ``SPELLBENCH_ARTIFACT_REGISTER`` naming an existing file (each from the
   environment, then ``benchmarks/local.json``), and a structured placement note (COMPUTE-POLICY.md item 1).
2. It picks the next run name (``<date>``, then ``<date>-2``, ...) and refuses a secrets directory inside the
   repository's work tree (Review Focus 5).
3. It generates the run secret in memory, writes ``runs/<run>/COMMITMENT.json``, commits that file alone and
   pushes it to ``origin``. When the push fails, the local commit is undone and the secret is dropped, so no
   usable secret ever exists without a public commitment.
4. Only then does it write the secret and the placement note under the secrets directory, outside the
   repository. The operator then records a third-party timestamp for the pushed commit: a commit date alone
   proves nothing (spec 11.6).

``spellbench bench run --run NAME --proof REF`` then owns the run through :func:`run_lock`, checks the secret
against the commitment (:func:`load_run_secret`) and the commitment against the remote (:func:`pushed_commit`),
and plays it. Spec 11.6 publishes every committed run: one that stops before its manifest is revealed with
:func:`reveal_run`, as ``REVEAL.json`` with a fixed reason category and never exception text (R3-28), either by
the invocation that holds its lock or by ``spellbench bench reveal``.

The secrets directory is ``SPELLBENCH_SECRETS_DIR`` (the environment, then ``benchmarks/local.json``), else
``~/.spellbench/run-secrets``. It holds ``<benchmark id>/<run>.hex`` (the secret), ``<run>.placement.txt`` and,
while an invocation owns the run, ``<run>.lock``. No run secret is printed or logged before it is revealed.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, NamedTuple

from ..arena import store
from ..arena.manifest import commitment_record
from ..arena.throughput import Placement, ThroughputError
from ..arena.validate import REVEAL_NAME, REVEAL_REASONS, REVEAL_SCHEMA
from ..run_secret import RunSecret
from . import definition

SECRETS_DIR_NAME = "SPELLBENCH_SECRETS_DIR"
PIN_ROOT_NAME = "SPELLBENCH_PIN_ROOT"
REGISTER_NAME = "SPELLBENCH_ARTIFACT_REGISTER"
REMOTE = "origin"
# Under Path.home() when SPELLBENCH_SECRETS_DIR is not set.
DEFAULT_SECRETS_DIR = (".spellbench", "run-secrets")
SECRET_SUFFIX = ".hex"
PLACEMENT_SUFFIX = ".placement.txt"
LOCK_SUFFIX = ".lock"
# The variables that point git at another repository (``git rev-parse --local-env-vars``). Every git command here
# acts on the repository that holds the run directory, never on one an enclosing git process chose.
GIT_REPOSITORY_VARS = frozenset({
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
})

_BENCHMARK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_NOT_PUSHED = "the commitment is not in a pushed commit"
_GIT_ERROR_LIMIT = 400


class CommitError(ValueError):
    """A commitment could not be published, checked or revealed, or its run is owned by another invocation."""


@dataclass(frozen=True)
class CommittedRun:
    """A commitment pushed by :func:`commit_run`: the run directory holding ``COMMITMENT.json``, the commitment,
    where the secret is kept, and ``commit``, the pushed commit that added ``COMMITMENT.json``."""

    run_dir: Path
    commitment: str
    secret_path: Path
    commit: str


class _RunFiles(NamedTuple):
    """A committed run's files in the secrets directory."""

    secret: Path
    placement: Path
    lock: Path


# ---------------------------------------------------------------------------
# Local values and the secrets directory
# ---------------------------------------------------------------------------


def _local_value(name: str, environ: Mapping[str, str], local: Mapping[str, str]) -> str | None:
    """The environment's value of ``name``, else ``benchmarks/local.json``'s; None when neither is set."""
    return environ.get(name) or local.get(name) or None


def secrets_dir(environ: Mapping[str, str], local: Mapping[str, str]) -> Path:
    """The folder that keeps run secrets: ``SPELLBENCH_SECRETS_DIR`` from ``environ``, then from ``local`` (the
    values of ``benchmarks/local.json``), else ``~/.spellbench/run-secrets`` (``Path.home()``, so ``USERPROFILE``
    on Windows); resolved to an absolute path. :func:`commit_run` refuses one inside the repository."""
    value = _local_value(SECRETS_DIR_NAME, environ, local)
    if value:
        return Path(value).expanduser().resolve()
    try:
        home = Path.home()
    except RuntimeError as exc:
        raise CommitError(f"no home directory to keep run secrets in: set {SECRETS_DIR_NAME}") from exc
    return home.joinpath(*DEFAULT_SECRETS_DIR).resolve()


def _checked_local_values(environ: Mapping[str, str], local: Mapping[str, str], placement: str) -> str:
    """Step 1 of :func:`commit_run`: the rated run's local values, checked before anything is published (a missing
    one found after the push would burn the commitment, R3-14); returns the placement note in its normal form."""
    where = "in the environment or in benchmarks/local.json"
    if not _local_value(PIN_ROOT_NAME, environ, local):
        raise CommitError(f"{PIN_ROOT_NAME} is not set: a rated run pins its engine and bot files under it; "
                          f"set it {where} before bench commit")
    register = _local_value(REGISTER_NAME, environ, local)
    if not register:
        raise CommitError(f"{REGISTER_NAME} is not set: a rated run registers its pinned files with that script; "
                          f"set it {where} before bench commit")
    if not Path(register).expanduser().is_file():
        raise CommitError(f"{REGISTER_NAME} names {register}, which is not a file; set it {where}")
    if type(placement) is not str:
        raise CommitError("the placement note must be text")
    try:
        return str(Placement.parse(placement))
    except ThroughputError as exc:
        raise CommitError(f"the placement note: {exc}") from None


def _checked_names(benchmark_id: str, run: str) -> None:
    """A benchmark id and a run name, never a path: both name files in the secrets directory."""
    if type(benchmark_id) is not str or not _BENCHMARK_ID.fullmatch(benchmark_id):
        raise CommitError(f"not a benchmark id: {benchmark_id!r}")
    if not definition.RUN_NAME_PATTERN.fullmatch(run):
        raise CommitError(f"not a run name (YYYY-MM-DD or YYYY-MM-DD-N with N >= 2): {run!r}")


def _run_files(folder: Path, run: str) -> _RunFiles:
    return _RunFiles(*(folder / f"{run}{suffix}" for suffix in (SECRET_SUFFIX, PLACEMENT_SUFFIX, LOCK_SUFFIX)))


def _files_of(run_dir: Path, benchmark_id: str, environ: Mapping[str, str] | None) -> _RunFiles:
    """The secrets-directory files of the run in ``run_dir`` (``benchmarks/<id>/runs/<run>``, whose
    ``benchmarks`` folder holds ``local.json``)."""
    run_dir = Path(run_dir).resolve()
    _checked_names(benchmark_id, run_dir.name)
    environ = os.environ if environ is None else environ
    local = definition.load_local_values(run_dir.parent.parent.parent)
    return _run_files(secrets_dir(environ, local) / benchmark_id, run_dir.name)


def _inside(path: Path, root: Path) -> bool:
    """Whether ``path`` is ``root`` or lies under it, also through symbolic links and case-insensitive names."""
    resolved, top = path.resolve(), root.resolve()
    if resolved == top or top in resolved.parents:
        return True
    for candidate in (resolved, *resolved.parents):
        with contextlib.suppress(OSError):
            if candidate.exists() and os.path.samefile(candidate, top):
                return True
    return False


def _write_new(path: Path, text: str) -> None:
    """Create ``path`` holding ``text`` (UTF-8, byte for byte), readable by its owner only. An existing file is never
    replaced (``O_EXCL`` raises ``FileExistsError``), and a failed write leaves no file."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``git -C directory ARGS`` with its output captured: the repository is the one holding ``directory``."""
    environment = {key: value for key, value in os.environ.items() if key not in GIT_REPOSITORY_VARS}
    try:
        return subprocess.run(
            ["git", "-C", str(directory), "-c", "color.ui=false", *args], capture_output=True, text=True,
            encoding="utf-8", errors="surrogateescape", env=environment, stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise CommitError(f"cannot run git: {exc.strerror or exc}") from exc


def _lines(text: str | None) -> list[str]:
    """The nonempty lines of a git output (a child's text output may end its lines with CR LF on Windows)."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _git_error(result: subprocess.CompletedProcess[str]) -> str:
    """What git said on stderr, as one line of ASCII."""
    text = "; ".join(_lines(result.stderr)) or f"git exited with status {result.returncode}"
    if len(text) > _GIT_ERROR_LIMIT:
        text = text[: _GIT_ERROR_LIMIT - 3] + "..."
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _git_lines(directory: Path, *args: str) -> list[str]:
    result = _git(directory, *args)
    if result.returncode != 0:
        raise CommitError(f"cannot check the commitment: git {args[0]} failed: {_git_error(result)}")
    return _lines(result.stdout)


def _work_tree(directory: Path) -> Path:
    """The top of the git work tree holding ``directory``."""
    result = _git(directory, "rev-parse", "--show-toplevel")
    top = _lines(result.stdout)[0] if result.returncode == 0 and _lines(result.stdout) else ""
    if not top:
        raise CommitError(f"{directory} is not in a git work tree: bench commit commits the commitment and pushes it "
                          f"to {REMOTE} (spec 11.6)")
    return Path(top)


# ---------------------------------------------------------------------------
# bench commit
# ---------------------------------------------------------------------------


def commit_run(
    benchmark_dir: Path, *, placement: str, date: str | None = None, environ: Mapping[str, str] | None = None
) -> CommittedRun:
    """Publish the commitment of the benchmark's next run, then keep its secret (the module docstring gives the
    order). ``date`` (YYYY-MM-DD) defaults to today, ``environ`` to ``os.environ``. Every failure is a
    ``CommitError`` naming what to fix; one raised before the push leaves nothing published and no secret."""
    environ = os.environ if environ is None else environ
    benchmark_dir = Path(benchmark_dir).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    local = definition.load_local_values(benchmark_dir.parent)
    # 1. The local values the rated run needs, before anything is published (R3-14).
    note = _checked_local_values(environ, local, placement)
    # 2. The run's name, and a secrets directory outside the repository (Review Focus 5).
    name = definition.next_run_name(benchmark_dir, datetime.date.today().isoformat() if date is None else date)
    top = _work_tree(benchmark_dir)
    folder = secrets_dir(environ, local)
    if _inside(folder, top):
        raise CommitError(f"the secrets directory {folder} is inside the repository work tree {top}: run secrets "
                          f"stay outside the repository; set {SECRETS_DIR_NAME} to a folder outside it")
    files = _run_files(folder / benchmark.id, name)
    for path in files:
        if path.exists():
            raise CommitError(f"{path} already exists, so {benchmark.id} run {name} was committed before; its run "
                              "directory must stay published (spec 11.6)")
    try:
        files.secret.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise CommitError(f"cannot create the secrets directory {files.secret.parent}: {exc.strerror or exc}") from exc
    # 3. The secret lives in memory only until its commitment is public (R3-8).
    secret = RunSecret.generate()
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    commit = _publish_commitment(run_dir, secret, benchmark_id=benchmark.id)
    # 4. Pushed: only now are the secret and the placement note kept (spec 11.6).
    _keep(files, secret=secret, note=note, run_dir=run_dir, benchmark_id=benchmark.id)
    return CommittedRun(run_dir=run_dir, commitment=secret.commitment(), secret_path=files.secret, commit=commit)


def _publish_commitment(run_dir: Path, secret: RunSecret, *, benchmark_id: str) -> str:
    """Write ``COMMITMENT.json``, commit that file alone and push it; returns the pushed commit. On a failure the
    commitment is taken back (:func:`_withdraw`) and ``CommitError`` raised: the caller never keeps the secret."""
    name = run_dir.name
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError:
        raise CommitError(f"{run_dir} appeared while committing; run bench commit again") from None
    try:
        store.write_json_atomic(run_dir / store.COMMITMENT_NAME,
                                commitment_record(run_secret=secret, benchmark_id=benchmark_id, run_label=name))
    except OSError as exc:
        _withdraw(run_dir, commit=None)
        raise CommitError(f"cannot write {run_dir / store.COMMITMENT_NAME}: {exc.strerror or exc}") from exc
    message = f"Spellbench: commitment for {benchmark_id} run {name}"
    for args in (("add", "--", store.COMMITMENT_NAME), ("commit", "-q", "-m", message, "--", store.COMMITMENT_NAME)):
        result = _git(run_dir, *args)
        if result.returncode != 0:
            _withdraw(run_dir, commit=None)
            raise CommitError(f"the commitment could not be committed: git {args[0]}: {_git_error(result)}; nothing "
                              "was published and no secret was kept")
    head = _git(run_dir, "rev-parse", "HEAD")
    commit = _lines(head.stdout)[0] if head.returncode == 0 and _lines(head.stdout) else ""
    if not commit:
        raise CommitError(f"the commitment was not pushed: its commit cannot be read ({_git_error(head)}); no "
                          "secret was kept, so undo that commit before you push")
    push = _git(run_dir, "push", "-q", REMOTE, "HEAD")
    if push.returncode != 0:
        if _withdraw(run_dir, commit=commit):
            raise CommitError(f"the commitment was not pushed: {_git_error(push)}; its local commit was undone and "
                              f"no secret was kept, so nothing was published: run bench commit again once {REMOTE} "
                              "accepts the push")
        raise CommitError(f"the commitment was not pushed: {_git_error(push)}; no secret was kept, so undo its local "
                          f"commit {commit} before you push")
    return commit


def _withdraw(run_dir: Path, *, commit: str | None) -> bool:
    """Take back an unpublished commitment: its local commit when HEAD is still ``commit`` (a soft reset, so the
    operator's index and files stay as they were), its index entry, its file and its empty folders. Returns False,
    leaving everything in place, when the commit cannot be undone."""
    if commit is not None:
        head = _git(run_dir, "rev-parse", "HEAD")
        if head.returncode != 0 or _lines(head.stdout)[:1] != [commit]:
            return False
        if _git(run_dir, "reset", "-q", "--soft", "HEAD~1").returncode != 0:
            return False
    _git(run_dir, "rm", "-q", "--cached", "--ignore-unmatch", "--", store.COMMITMENT_NAME)
    for path in (run_dir / store.COMMITMENT_NAME, run_dir / f"{store.COMMITMENT_NAME}.tmp"):
        with contextlib.suppress(OSError):
            path.unlink()
    for folder in (run_dir, run_dir.parent):  # the runs folder too, when this run was its only entry
        with contextlib.suppress(OSError):
            folder.rmdir()
    return True


def _keep(files: _RunFiles, *, secret: RunSecret, note: str, run_dir: Path, benchmark_id: str) -> None:
    """Keep the placement note, then the secret, each created exclusively. A commitment that is public but whose
    secret cannot be kept could never be revealed, so its secret is revealed at once instead: that run is never
    played (spec 11.6)."""
    try:
        _write_new(files.placement, note + "\n")
        _write_new(files.secret, secret.hex() + "\n")
    except OSError as exc:
        reveal = _write_reveal(run_dir, secret, benchmark_id=benchmark_id, reason="error")
        raise CommitError(f"the commitment is pushed but its secret could not be kept ({exc.strerror or exc}); the "
                          f"run cannot be played, so its secret was revealed in {reveal}: commit and push that file "
                          "(spec 11.6), then run bench commit again") from None


# ---------------------------------------------------------------------------
# bench run: the lock, the secret, the placement note, the pushed commit
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def run_lock(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> Iterator[Path]:
    """Own a committed run while the body runs: ``<secrets dir>/<benchmark id>/<run>.lock``, beside the secret,
    created with ``O_EXCL`` and removed on exit (R3-14). Only the owner may play or reveal the run, so a run that
    another invocation is playing is never revealed. A lock left by a killed process stays until the operator
    deletes it."""
    files = _files_of(run_dir, benchmark_id, environ)
    name = files.lock.name[: -len(LOCK_SUFFIX)]
    try:
        files.lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_new(files.lock, f"{os.getpid()}\n")
    except FileExistsError:
        raise CommitError(f"{benchmark_id} run {name} is already running or finished: another invocation holds "
                          f"{files.lock}; delete that file only when no bench run or bench reveal is working on "
                          "this run") from None
    except OSError as exc:
        raise CommitError(f"cannot take the lock {files.lock}: {exc.strerror or exc}") from exc
    try:
        yield files.lock
    finally:
        with contextlib.suppress(OSError):
            files.lock.unlink()


def _commitment_of(run_dir: Path) -> dict:
    path = run_dir / store.COMMITMENT_NAME
    try:
        return store.read_json(path)
    except store.StoreError as exc:
        raise CommitError(f"no readable commitment for this run: {exc}") from None


def load_run_secret(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> RunSecret:
    """The run secret :func:`commit_run` kept for the run in ``run_dir``; it must hash to the commitment in the
    run's ``COMMITMENT.json``, made for this benchmark and this run (spec 11.6)."""
    run_dir = Path(run_dir).resolve()
    path = _files_of(run_dir, benchmark_id, environ).secret
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        raise CommitError(f"no run secret for {benchmark_id} run {run_dir.name} at {path}: bench commit keeps it on "
                          "the machine that committed the run") from None
    try:
        secret = RunSecret.from_hex(text.strip())
    except ValueError:
        raise CommitError(f"{path} does not hold a run secret (64 lowercase hex characters)") from None
    record = _commitment_of(run_dir)
    expected = commitment_record(run_secret=secret, benchmark_id=benchmark_id, run_label=run_dir.name)
    commitment = run_dir / store.COMMITMENT_NAME
    if set(record) != set(expected) or any(record[key] != expected[key] for key in ("schema", "protocol")):
        raise CommitError(f"{commitment} is not a commitment record")
    if record["benchmark_id"] != benchmark_id or record["run_label"] != run_dir.name:
        raise CommitError(f"{commitment} was made for another run: its benchmark_id and run_label must be "
                          f"{benchmark_id!r} and {run_dir.name!r} (spec 11.6)")
    if record["commitment"] != expected["commitment"]:
        raise CommitError(f"the run secret in {path} does not hash to the commitment in {commitment} (spec 11.6)")
    return secret


def load_placement(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> str:
    """The placement note recorded by :func:`commit_run` for the run in ``run_dir``, in its normal form."""
    path = _files_of(run_dir, benchmark_id, environ).placement
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise CommitError(f"no placement note for {benchmark_id} run {Path(run_dir).resolve().name} at {path}: "
                          "bench commit records it beside the run secret") from None
    try:
        return str(Placement.parse(text.strip()))
    except ThroughputError as exc:
        raise CommitError(f"the placement note {path}: {exc}") from None


def pushed_commit(run_dir: Path) -> str:
    """The pushed commit that added the run's ``COMMITMENT.json`` (spec 11.6, R3-8).

    It fetches ``origin`` first (pruning deleted branches), so the check reads the remote's current state. The file
    must be tracked and unchanged from ``HEAD``, exactly one commit may touch it (the one that added it: a
    commitment changed, or removed and added again, after its first push proves nothing), and that commit must lie
    on a branch of ``origin``.
    """
    run_dir = Path(run_dir)
    name = store.COMMITMENT_NAME
    fetch = _git(run_dir, "fetch", "-q", "--prune", REMOTE)
    if fetch.returncode != 0:
        raise CommitError(f"cannot check the commitment against {REMOTE}: git fetch failed: {_git_error(fetch)}")
    if _git(run_dir, "ls-files", "--error-unmatch", "--", name).returncode != 0:
        raise CommitError(f"{_NOT_PUSHED}: {name} is not tracked; commit it and push it before the first game "
                          "(spec 11.6)")
    diff = _git(run_dir, "diff", "--quiet", "HEAD", "--", name)
    if diff.returncode == 1:
        raise CommitError(f"{_NOT_PUSHED}: {name} differs from HEAD; commit it and push it before the first game "
                          "(spec 11.6)")
    if diff.returncode != 0:
        raise CommitError(f"cannot check the commitment: git diff failed: {_git_error(diff)}")
    added = _git_lines(run_dir, "log", "--no-show-signature", "--format=%H", "--diff-filter=A", "--", name)
    touched = _git_lines(run_dir, "log", "--no-show-signature", "--format=%H", "--", name)
    if not added:
        raise CommitError(f"{_NOT_PUSHED}: no commit adds {name}; commit it and push it before the first game "
                          "(spec 11.6)")
    first = added[-1]  # the oldest: the commitment as first pushed
    if touched != [first]:
        raise CommitError(f"the commitment was changed after its first push ({first}); a changed commitment proves "
                          "nothing (spec 11.6)")
    if not _git_lines(run_dir, "branch", "-r", "--list", f"{REMOTE}/*", "--contains", first):
        raise CommitError(f"{_NOT_PUSHED}: commit {first} is on no branch of {REMOTE}; push it before the first "
                          "game (spec 11.6)")
    return first


# ---------------------------------------------------------------------------
# Reveal
# ---------------------------------------------------------------------------


def _write_reveal(run_dir: Path, secret: RunSecret, *, benchmark_id: str, reason: str) -> Path:
    path = run_dir / REVEAL_NAME
    store.write_json_atomic(path, {
        "schema": REVEAL_SCHEMA,
        "benchmark_id": benchmark_id,
        "run_label": run_dir.name,
        "commitment": secret.commitment(),
        "run_secret": secret.hex(),
        "status": "aborted",
        "reason": reason,
    })
    return path


def reveal_run(
    run_dir: Path, *, benchmark_id: str, reason: str, environ: Mapping[str, str] | None = None
) -> Path:
    """Publish the secret of a committed run that stopped before its manifest, as ``run_dir/REVEAL.json``; returns
    its path (spec 11.6: every committed run is published, aborted ones included).

    ``reason`` is a category from ``REVEAL_REASONS``, never exception text, which could carry local paths (R3-28).
    The caller owns the run (:func:`run_lock`). A run whose manifest exists already reveals its secret there.
    """
    if reason not in REVEAL_REASONS:
        raise CommitError(f"a reveal reason is one of {', '.join(REVEAL_REASONS)}, never free text (R3-28)")
    run_dir = Path(run_dir).resolve()
    if store.is_published(run_dir):
        raise CommitError(f"{run_dir} is published: its {store.MANIFEST_NAME} reveals the run secret")
    if (run_dir / REVEAL_NAME).exists():
        raise CommitError(f"{run_dir / REVEAL_NAME} exists: the run is revealed already")
    secret = load_run_secret(run_dir, benchmark_id=benchmark_id, environ=environ)
    return _write_reveal(run_dir, secret, benchmark_id=benchmark_id, reason=reason)
