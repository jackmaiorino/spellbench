"""A rated run's commitment, pushed before its secret exists; the run's lock; its reveal (spec 11.6; Decision 9).

:func:`commit_run` (``spellbench bench commit``) publishes a run's commitment before its first game, in this
order (R3-8, R3-14):

1. It checks the local values the rated run will need, so a missing one never burns a published commitment:
   ``SPELLBENCH_PIN_ROOT`` set, ``SPELLBENCH_ARTIFACT_REGISTER`` naming an existing file (each from the
   environment, then ``benchmarks/local.json``), and a structured placement note (COMPUTE-POLICY.md item 1).
2. It picks the next run name (``<date>``, then ``<date>-2``, ...) and refuses a secrets directory given as a
   relative path, or lying inside any git work tree or repository (Review Focus 5).
3. It fetches ``origin`` and refuses unless tracked files are unchanged, ``HEAD`` is the tip of ``origin``'s
   default branch, and the benchmark folder holds no untracked file: the commitment commit then sits directly on
   that branch, publishes nothing else, and fixes the benchmark as committed.
4. It generates the run secret in memory, writes ``runs/<run>/COMMITMENT.json``, commits that file alone and pushes
   that one commit to the default branch. Ctrl+C is held from before the commit until the secret is kept. Any
   failure before the push is confirmed withdraws the commitment (its local commit, index entry and file; the
   operator's own work stays) and drops the secret, so no usable secret exists without a public commitment. A
   push reported as failed is checked against ``origin``: a commitment that reached it is public, so its secret is
   kept.
5. Only then does it keep the secret and the placement note under the secrets directory, outside the repository.
   The operator then records a third-party timestamp for the pushed commit: a commit date alone proves nothing
   (spec 11.6).

``spellbench bench run --run NAME --proof REF`` then owns the run through :func:`run_lock`, refuses a run already
started (:func:`mark_started`: a commitment is played once), checks the secret against the commitment
(:func:`load_run_secret`), the commitment against ``origin``'s default branch (:func:`pushed_commit`) and the
benchmark against the commitment commit (:func:`check_definition`), and plays it. Spec 11.6 publishes every
committed run: one that stops before its manifest is revealed with :func:`reveal_run`, as ``REVEAL.json`` with a
fixed reason category and never exception text (R3-28), either by the invocation that holds its lock or by
``spellbench bench reveal``; the files of the unfinished attempt move beside the secret first. A run whose secret
was lost after its push is published as withheld (:func:`withhold_run`).

The secrets directory is ``SPELLBENCH_SECRETS_DIR`` (the environment, then ``benchmarks/local.json``; an absolute
path), else ``~/.spellbench/run-secrets``. It holds ``<benchmark id>/<run>.hex`` (the secret),
``<run>.placement.txt``, ``<run>.started`` once the run began, ``<run>.attempt/`` (the unpublished files of a run
revealed without its manifest) and, while an invocation owns the run, ``<run>.lock``. No run secret is printed or
logged before it is revealed.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, NamedTuple

from ..arena import runner, store
from ..arena.manifest import commitment_record
from ..arena.throughput import Placement, ThroughputError
from ..arena.validate import REVEAL_NAME, REVEAL_REASONS, REVEAL_SCHEMA, WITHHELD_REASON
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
# Written when the run's tournament begins: a commitment is played once (spec 11.6).
STARTED_SUFFIX = ".started"
# A folder: the unpublished files of an attempt revealed without its manifest.
ATTEMPT_SUFFIX = ".attempt"
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
    started: Path
    attempt: Path


# ---------------------------------------------------------------------------
# Local values and the secrets directory
# ---------------------------------------------------------------------------


def _local_value(name: str, environ: Mapping[str, str], local: Mapping[str, str]) -> str | None:
    """The environment's value of ``name``, else ``benchmarks/local.json``'s; None when neither is set."""
    return environ.get(name) or local.get(name) or None


def secrets_dir(environ: Mapping[str, str], local: Mapping[str, str]) -> Path:
    """The folder that keeps run secrets: ``SPELLBENCH_SECRETS_DIR`` from ``environ``, then from ``local`` (the
    values of ``benchmarks/local.json``), else ``~/.spellbench/run-secrets`` (``Path.home()``, so ``USERPROFILE``
    on Windows); resolved. A relative value is refused: it would name another folder from each working directory.
    Every use also refuses one inside a git work tree (:func:`_secrets_folder`, Review Focus 5)."""
    value = _local_value(SECRETS_DIR_NAME, environ, local)
    if value:
        folder = Path(value).expanduser()
        if not folder.is_absolute():
            raise CommitError(f"{SECRETS_DIR_NAME} must be an absolute path, not {value!r}: a relative one names "
                              "another folder from each working directory (Review Focus 5)")
        return folder.resolve()
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
    suffixes = (SECRET_SUFFIX, PLACEMENT_SUFFIX, LOCK_SUFFIX, STARTED_SUFFIX, ATTEMPT_SUFFIX)
    return _RunFiles(*(folder / f"{run}{suffix}" for suffix in suffixes))


def _files_of(run_dir: Path, benchmark_id: str, environ: Mapping[str, str] | None) -> _RunFiles:
    """The secrets-directory files of the run in ``run_dir`` (``benchmarks/<id>/runs/<run>``, whose
    ``benchmarks`` folder holds ``local.json``); the secrets directory is checked at every use (Review Focus 5)."""
    run_dir = Path(run_dir).resolve()
    _checked_names(benchmark_id, run_dir.name)
    environ = os.environ if environ is None else environ
    benchmark_dir = run_dir.parent.parent
    local = definition.load_local_values(benchmark_dir.parent)
    return _run_files(_secrets_folder(environ, local, benchmark_dir) / benchmark_id, run_dir.name)


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


def _nearest_existing(path: Path) -> Path:
    """``path``, or its nearest parent that exists as a folder."""
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return path


def _enclosing_repository(folder: Path) -> Path | None:
    """The git work tree, or the git folder (a ``.git`` folder, a bare repository), holding ``folder``; None when
    git finds no repository there."""
    near = _nearest_existing(folder)
    top = _git(near, "rev-parse", "--show-toplevel")
    if top.returncode == 0 and _lines(top.stdout):
        return Path(_lines(top.stdout)[0])
    inside = _git(near, "rev-parse", "--is-inside-git-dir")
    if inside.returncode == 0 and _lines(inside.stdout)[:1] == ["true"]:
        return near
    return None


def _secrets_folder(environ: Mapping[str, str], local: Mapping[str, str], benchmark_dir: Path) -> Path:
    """:func:`secrets_dir`, refused when it lies inside a git work tree or repository (Review Focus 5): the one
    holding the benchmark, that repository's git folder and main work tree (``git rev-parse --git-common-dir``; a
    linked worktree's main checkout counts), or any other one git finds from the folder itself."""
    folder = secrets_dir(environ, local)
    top = _work_tree(benchmark_dir)
    roots = [top]
    common = _git(benchmark_dir, "rev-parse", "--git-common-dir")
    if common.returncode == 0 and _lines(common.stdout):
        git_dir = (benchmark_dir / _lines(common.stdout)[0]).resolve()  # relative to the directory, or absolute
        roots += [git_dir, *([git_dir.parent] if git_dir.name == ".git" else [])]
    enclosing = next((root for root in roots if _inside(folder, root)), None) or _enclosing_repository(folder)
    if enclosing is not None:
        raise CommitError(f"the secrets directory {folder} is inside the git repository or work tree {enclosing}: "
                          f"run secrets stay outside the repository and every git work tree; set {SECRETS_DIR_NAME} "
                          "to an absolute path outside them")
    return folder


def _head(directory: Path) -> str | None:
    """The commit ``HEAD`` names, or None."""
    result = _git(directory, "rev-parse", "-q", "--verify", "HEAD^{commit}")
    return _lines(result.stdout)[0] if result.returncode == 0 and _lines(result.stdout) else None


def _tracking_ref(branch: str) -> str:
    return f"refs/remotes/{REMOTE}/{branch}"


def _default_branch(directory: Path) -> str:
    """``origin``'s default branch, the one a commitment goes to (spec 11.6): after a fetch, the branch
    ``refs/remotes/origin/HEAD`` names (a clone records it), else the one ``origin`` itself names
    (``git ls-remote --symref origin HEAD``)."""
    prefix = _tracking_ref("")
    recorded = _git(directory, "symbolic-ref", "-q", f"{prefix}HEAD")
    name = _lines(recorded.stdout)[0] if recorded.returncode == 0 and _lines(recorded.stdout) else ""
    if name.startswith(prefix) and len(name) > len(prefix):
        if _git(directory, "rev-parse", "-q", "--verify", f"{name}^{{commit}}").returncode == 0:
            return name[len(prefix):]
    listed = _git(directory, "ls-remote", "--symref", REMOTE, "HEAD")
    if listed.returncode != 0:
        raise CommitError(f"cannot tell the default branch of {REMOTE}: git ls-remote failed: {_git_error(listed)}")
    for line in _lines(listed.stdout):
        target, _, ref = line.partition("\t")
        if ref.strip() == "HEAD" and target.startswith("ref: refs/heads/") and len(target) > len("ref: refs/heads/"):
            return target[len("ref: refs/heads/"):].strip()
    raise CommitError(f"cannot tell the default branch of {REMOTE}: its HEAD names no branch; set it there, or record "
                      f"it here with: git remote set-head {REMOTE} <branch>")


def _remote_tip(directory: Path, branch: str) -> str:
    """The fetched tip of ``origin/<branch>``."""
    result = _git(directory, "rev-parse", "-q", "--verify", f"{_tracking_ref(branch)}^{{commit}}")
    if result.returncode != 0 or not _lines(result.stdout):
        raise CommitError(f"{REMOTE}/{branch}, the default branch of {REMOTE}, was not fetched; run git fetch {REMOTE}")
    return _lines(result.stdout)[0]


def _fetch(directory: Path) -> subprocess.CompletedProcess[str]:
    """Fetch ``origin``, pruning deleted branches, so every check reads its current state."""
    return _git(directory, "fetch", "-q", "--prune", REMOTE)


def _on_branch(directory: Path, commit: str, branch: str) -> bool | None:
    """Whether the fetched ``origin/<branch>`` holds ``commit``; None when git cannot tell."""
    result = _git(directory, "merge-base", "--is-ancestor", commit, _tracking_ref(branch))
    return {0: True, 1: False}.get(result.returncode)


def _on_remote(directory: Path, commit: str, branch: str) -> bool | None:
    """After a push reported as failed or cut off: whether ``origin/<branch>`` holds ``commit`` now, fetched
    afresh; None when the fetch fails, so nobody can tell."""
    if _fetch(directory).returncode != 0:
        return None
    return _on_branch(directory, commit, branch)


def definition_changes(benchmark_dir: Path, commit: str) -> str | None:
    """The first file of the benchmark folder, its runs aside, that differs between ``commit`` and ``HEAD``, or
    between ``commit`` and the work tree, or sits untracked in the work tree (a repository-relative path); None
    when the benchmark is the one ``commit`` holds."""
    scope = ("--", ".", f":(exclude){definition.RUNS_DIR}")
    for args in (("diff", "--name-only", "--no-renames", commit, "HEAD", *scope),
                 ("diff", "--name-only", "--no-renames", commit, *scope),
                 ("ls-files", "--full-name", "--others", "--exclude-standard", *scope)):
        changed = _git_lines(benchmark_dir, *args)
        if changed:
            return changed[0]
    return None


def check_definition(benchmark_dir: Path, commit: str) -> None:
    """The benchmark as the commitment fixed it (spec 11.6): every file of ``benchmark_dir`` but its runs is the
    same at ``commit`` (the pushed commit that added ``COMMITMENT.json``), at ``HEAD`` and in the work tree, with no
    untracked file beside them. Otherwise a kept secret could play the benchmark's variants privately and choose
    the one to publish."""
    changed = definition_changes(Path(benchmark_dir), commit)
    if changed is not None:
        raise CommitError(f"{changed} changed after the commitment: the commitment fixed the benchmark's definition "
                          f"at commit {commit} (spec 11.6); restore that file, or delete it if git does not track it, "
                          "before bench run: a changed definition needs a new commitment")


# ---------------------------------------------------------------------------
# bench commit
# ---------------------------------------------------------------------------


def commit_run(
    benchmark_dir: Path, *, placement: str, date: str | None = None, environ: Mapping[str, str] | None = None
) -> CommittedRun:
    """Publish the commitment of the benchmark's next run, then keep its secret (the module docstring gives the
    order). ``date`` (YYYY-MM-DD) defaults to today, ``environ`` to ``os.environ``. Every failure is a
    ``CommitError`` naming what to fix; one raised before the push is confirmed leaves nothing published and no
    secret."""
    environ = os.environ if environ is None else environ
    benchmark_dir = Path(benchmark_dir).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    local = definition.load_local_values(benchmark_dir.parent)
    # 1. The local values the rated run needs, before anything is published (R3-14).
    note = _checked_local_values(environ, local, placement)
    # 2. The run's name, and a secrets directory outside every work tree (Review Focus 5).
    name = definition.next_run_name(benchmark_dir, datetime.date.today().isoformat() if date is None else date)
    files = _run_files(_secrets_folder(environ, local, benchmark_dir) / benchmark.id, name)
    for path in files:
        if os.path.lexists(path):
            raise CommitError(f"{path} already exists, so {benchmark.id} run {name} was committed before; its run "
                              "directory must stay published (spec 11.6)")
    # 3. A clean repository on origin's default branch: the commitment commit publishes nothing else.
    branch, base = _ready_to_publish(benchmark_dir)
    try:
        files.secret.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise CommitError(f"cannot create the secrets directory {files.secret.parent}: {exc.strerror or exc}") from exc
    # 4 and 5. The secret lives in memory only until its commitment is public (R3-8); Ctrl+C is held until the
    # secret is kept, so neither an orphan commit nor a public commitment without its secret is left (R3-31).
    secret = RunSecret.generate()
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    with runner.deferred_interrupts():
        commit = _publish(run_dir, secret, files, note, benchmark_id=benchmark.id, base=base, branch=branch)
    return CommittedRun(run_dir=run_dir, commitment=secret.commitment(), secret_path=files.secret, commit=commit)


def _ready_to_publish(benchmark_dir: Path) -> tuple[str, str]:
    """Step 3 of :func:`commit_run`: ``origin``'s default branch and ``HEAD``, once ``origin`` is fetched, tracked
    files are unchanged, ``HEAD`` is that branch's tip and the benchmark folder holds no untracked file."""
    fetch = _fetch(benchmark_dir)
    if fetch.returncode != 0:
        raise CommitError(f"cannot publish the commitment: git fetch {REMOTE} failed: {_git_error(fetch)}; nothing "
                          "was published")
    branch = _default_branch(benchmark_dir)
    tip = _remote_tip(benchmark_dir, branch)
    status = _git(benchmark_dir, "status", "--porcelain", "-z", "--untracked-files=no")
    if status.returncode != 0:
        raise CommitError(f"cannot publish the commitment: git status failed: {_git_error(status)}")
    changed = [entry[3:] for entry in (status.stdout or "").split("\0") if len(entry) > 3]
    if changed:
        raise CommitError(f"tracked files are changed ({changed[0]}): commit, stash or restore them before bench "
                          "commit, so the commitment commit publishes COMMITMENT.json alone and fixes the benchmark "
                          "as committed (spec 11.6)")
    base = _head(benchmark_dir)
    if base != tip:
        raise CommitError(f"HEAD ({base or 'no commit'}) is not {REMOTE}/{branch} ({tip}), the tip of the default "
                          f"branch of {REMOTE}: the commitment commit goes directly on it and its push publishes "
                          "nothing else; pull, or push or set aside your local commits, before bench commit")
    untracked = definition_changes(benchmark_dir, base)
    if untracked is not None:
        raise CommitError(f"{untracked} is not committed: the commitment fixes the benchmark as committed "
                          "(spec 11.6); commit or delete it before bench commit")
    return branch, base


def _publish(
    run_dir: Path, secret: RunSecret, files: _RunFiles, note: str, *, benchmark_id: str, base: str, branch: str
) -> str:
    """Steps 4 and 5 of :func:`commit_run`, the caller holding Ctrl+C: write ``COMMITMENT.json``, commit it alone
    on ``base``, push that commit to ``origin/<branch>``, then keep the secret; returns the commit.

    Until the push is confirmed, any exception (a ``KeyboardInterrupt`` or ``SystemExit`` included) withdraws the
    commitment and drops the secret, unless ``origin`` holds the commitment anyway: it is then public, so its secret
    is kept and the exception raised again. A push reported as failed is checked the same way (spec 11.6).
    """
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError:
        raise CommitError(f"{run_dir} appeared while committing; run bench commit again") from None
    except OSError as exc:
        raise CommitError(f"cannot create {run_dir}: {exc.strerror or exc}") from exc
    commit: str | None = None
    pushing = False  # from the push on, origin may hold the commitment
    try:
        try:
            store.write_json_atomic(run_dir / store.COMMITMENT_NAME, commitment_record(
                run_secret=secret, benchmark_id=benchmark_id, run_label=run_dir.name))
        except OSError as exc:
            raise CommitError(f"cannot write {run_dir / store.COMMITMENT_NAME}: {exc.strerror or exc}") from exc
        commit = _commit(run_dir, benchmark_id=benchmark_id, base=base)
        pushing = True
        push = _git(run_dir, "push", "-q", REMOTE, f"{commit}:refs/heads/{branch}")
        reached = True if push.returncode == 0 else _on_remote(run_dir, commit, branch)
        pushing = False
    except BaseException as exc:
        public = withdrawn = False
        if pushing and commit is not None:
            with contextlib.suppress(Exception):
                public = _on_remote(run_dir, commit, branch) is True
        if public:
            _keep(files, secret=secret, note=note, run_dir=run_dir, benchmark_id=benchmark_id)  # (spec 11.6)
            raise
        with contextlib.suppress(Exception):
            withdrawn = _withdraw(run_dir, base=base)
        if not withdrawn:
            exc.add_note(f"the local commitment commit could not be undone: run git reset --soft {base} before you "
                         "push, since no secret was kept")
        raise
    if reached:
        _keep(files, secret=secret, note=note, run_dir=run_dir, benchmark_id=benchmark_id)
        return commit
    undone = _withdraw(run_dir, base=base)
    where = (f"{REMOTE}/{branch} does not hold it" if reached is False else
             f"whether {REMOTE} received it cannot be checked, since git fetch failed (if {REMOTE}/{branch} holds "
             f"commit {commit}, its secret is lost: publish that run with spellbench bench reveal BENCHMARK_DIR --run "
             f"{run_dir.name} --withheld)")
    undo = ("its local commit was undone" if undone else
            f"undo its local commit {commit} (git reset --soft {base}) before you push")
    raise CommitError(f"the commitment was not pushed: {_git_error(push)}; {where}; {undo} and no secret was kept, "
                      f"so run bench commit again once {REMOTE} accepts the push")


def _commit(run_dir: Path, *, benchmark_id: str, base: str) -> str:
    """Commit ``COMMITMENT.json`` alone on ``base``; returns the commit."""
    message = f"Spellbench: commitment for {benchmark_id} run {run_dir.name}"
    for args in (("add", "--", store.COMMITMENT_NAME), ("commit", "-q", "-m", message, "--", store.COMMITMENT_NAME)):
        result = _git(run_dir, *args)
        if result.returncode != 0:
            raise CommitError(f"the commitment could not be committed: git {args[0]}: {_git_error(result)}; nothing "
                              "was published and no secret was kept")
    commit = _commitment_commit(run_dir.parent.parent, run_dir.name, base)
    if commit is None:
        raise CommitError("the commitment could not be committed: HEAD is not a commit adding COMMITMENT.json alone "
                          f"on {base}; nothing was published and no secret was kept")
    return commit


def _commitment_commit(benchmark_dir: Path, name: str, base: str) -> str | None:
    """``HEAD`` when it is run ``name``'s commitment commit: one parent, ``base``, and one change, that run's
    ``COMMITMENT.json`` (git paths, relative to the benchmark folder); else None."""
    head = _git(benchmark_dir, "log", "-1", "--no-show-signature", "--format=%H %P", "HEAD")
    parts = _lines(head.stdout)[0].split() if head.returncode == 0 and _lines(head.stdout) else []
    if len(parts) != 2 or parts[1] != base:
        return None
    listing = ("diff-tree", "-r", "--no-commit-id", "--name-only", "--no-renames")
    every = _git(benchmark_dir, *listing, parts[0])
    here = _git(benchmark_dir, *listing, "--relative", parts[0])
    if every.returncode != 0 or here.returncode != 0 or len(_lines(every.stdout)) != 1:
        return None
    return parts[0] if _lines(here.stdout) == [f"{definition.RUNS_DIR}/{name}/{store.COMMITMENT_NAME}"] else None


def _withdraw(run_dir: Path, *, base: str) -> bool:
    """Take back an unpublished commitment: its commit when ``HEAD`` is that commit on ``base`` (a soft reset), its
    index entry, its file and its empty folders; the operator's own files stay. Returns False, leaving everything
    in place, when ``HEAD`` is another commit or cannot be moved back."""
    benchmark_dir, name = run_dir.parent.parent, run_dir.name
    head = _head(benchmark_dir)
    if head is None:
        return False
    if head != base:
        if _commitment_commit(benchmark_dir, name, base) != head:
            return False
        if _git(benchmark_dir, "reset", "-q", "--soft", base).returncode != 0:
            return False
    _git(benchmark_dir, "rm", "-q", "--cached", "--ignore-unmatch", "--",
         f"{definition.RUNS_DIR}/{name}/{store.COMMITMENT_NAME}")
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


def _commitment_of(run_dir: Path, benchmark_id: str) -> dict:
    """The run's ``COMMITMENT.json``: a commitment record made for this benchmark and this run (spec 11.6)."""
    path = run_dir / store.COMMITMENT_NAME
    try:
        record = store.read_json(path)
    except store.StoreError as exc:
        raise CommitError(f"no readable commitment for this run: {exc}") from None
    shape = commitment_record(run_secret=RunSecret(bytes(32)), benchmark_id=benchmark_id, run_label=run_dir.name)
    if set(record) != set(shape) or any(record[key] != shape[key] for key in ("schema", "protocol")):
        raise CommitError(f"{path} is not a commitment record")
    if record["benchmark_id"] != benchmark_id or record["run_label"] != run_dir.name:
        raise CommitError(f"{path} was made for another run: its benchmark_id and run_label must be "
                          f"{benchmark_id!r} and {run_dir.name!r} (spec 11.6)")
    if type(record["commitment"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", record["commitment"]):
        raise CommitError(f"{path} holds no commitment (64 lowercase hex characters)")
    return record


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
    if _commitment_of(run_dir, benchmark_id)["commitment"] != secret.commitment():
        raise CommitError(f"the run secret in {path} does not hash to the commitment in "
                          f"{run_dir / store.COMMITMENT_NAME} (spec 11.6)")
    return secret


def _played(benchmark_id: str, name: str, marker: Path) -> CommitError:
    return CommitError(f"{benchmark_id} run {name} was already played under its commitment ({marker} exists): a "
                       "commitment is played once (spec 11.6), so that run must be published (its manifest and "
                       "files) or revealed with spellbench bench reveal")


def check_not_started(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> None:
    """Refuse a committed run whose tournament began before (:func:`mark_started`): a commitment is played once
    (spec 11.6), so deleting a finished run's unpublished outputs never lets it play again."""
    files = _files_of(run_dir, benchmark_id, environ)
    if os.path.lexists(files.started):
        raise _played(benchmark_id, Path(run_dir).resolve().name, files.started)


def mark_started(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> Path:
    """Record beside the secret that the run's tournament begins, after the pre-run checks and before the first
    game: ``<run>.started``, created exclusively and never removed, so a run already started is refused
    (spec 11.6)."""
    files = _files_of(run_dir, benchmark_id, environ)
    try:
        _write_new(files.started, "")
    except FileExistsError:
        raise _played(benchmark_id, Path(run_dir).resolve().name, files.started) from None
    except OSError as exc:
        raise CommitError(f"cannot record that the run starts in {files.started}: {exc.strerror or exc}") from exc
    return files.started


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
    on ``origin``'s default branch, where :func:`commit_run` pushes it: a side branch can be deleted.
    """
    run_dir = Path(run_dir)
    name = store.COMMITMENT_NAME
    fetch = _fetch(run_dir)
    if fetch.returncode != 0:
        raise CommitError(f"cannot check the commitment against {REMOTE}: git fetch failed: {_git_error(fetch)}")
    branch = _default_branch(run_dir)
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
    _remote_tip(run_dir, branch)
    on_branch = _on_branch(run_dir, first, branch)
    if on_branch is None:
        raise CommitError(f"cannot check the commitment: git merge-base cannot tell whether {REMOTE}/{branch} holds "
                          f"commit {first}")
    if not on_branch:
        raise CommitError(f"{_NOT_PUSHED}: commit {first} is not on {REMOTE}/{branch}, the default branch of "
                          f"{REMOTE}; push it there before the first game (spec 11.6)")
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


def _unpublished(run_dir: Path) -> None:
    """A committed run published neither by its manifest nor by a reveal."""
    if store.is_published(run_dir):
        raise CommitError(f"{run_dir} is published: its {store.MANIFEST_NAME} reveals the run secret")
    if os.path.lexists(run_dir / REVEAL_NAME):
        raise CommitError(f"{run_dir / REVEAL_NAME} exists: the run is revealed already")


def attempt_dir(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> Path:
    """Where :func:`reveal_run` and :func:`withhold_run` move the unpublished files of the run's unfinished attempt:
    ``<secrets dir>/<benchmark id>/<run>.attempt``, outside the repository."""
    return _files_of(run_dir, benchmark_id, environ).attempt


def _set_aside(run_dir: Path, attempt: Path) -> list[str]:
    """Move every entry of ``run_dir`` but ``COMMITMENT.json`` (the unpublished files of an attempt that stopped
    before its manifest) into ``attempt``, so the published folder holds exactly ``COMMITMENT.json`` and
    ``REVEAL.json`` (spec 11.6); returns the names moved. An entry already set aside is never replaced."""
    try:
        names = sorted(entry.name for entry in run_dir.iterdir() if entry.name != store.COMMITMENT_NAME)
        if names:
            attempt.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in names:
            target = attempt / name
            if os.path.lexists(target):
                raise CommitError(f"cannot move {run_dir / name} aside: {target} exists already; move one of them "
                                  "elsewhere first")
            shutil.move(str(run_dir / name), str(target))
    except OSError as exc:
        raise CommitError(f"cannot move the unpublished files of {run_dir} to {attempt}: "
                          f"{exc.strerror or exc}") from exc
    return names


def reveal_run(
    run_dir: Path, *, benchmark_id: str, reason: str, environ: Mapping[str, str] | None = None
) -> Path:
    """Publish the secret of a committed run that stopped before its manifest, as ``run_dir/REVEAL.json``; returns
    its path (spec 11.6: every committed run is published, aborted ones included).

    ``reason`` is a category from ``REVEAL_REASONS``, never exception text, which could carry local paths (R3-28).
    The caller owns the run (:func:`run_lock`). A run whose manifest exists already reveals its secret there. The
    unfinished attempt's files move first to :func:`attempt_dir`, outside the repository, so the published folder
    holds exactly ``COMMITMENT.json`` and ``REVEAL.json``.
    """
    if reason not in REVEAL_REASONS:
        raise CommitError(f"a reveal reason is one of {', '.join(REVEAL_REASONS)}, never free text (R3-28)")
    run_dir = Path(run_dir).resolve()
    _unpublished(run_dir)
    secret = load_run_secret(run_dir, benchmark_id=benchmark_id, environ=environ)
    _set_aside(run_dir, attempt_dir(run_dir, benchmark_id=benchmark_id, environ=environ))
    return _write_reveal(run_dir, secret, benchmark_id=benchmark_id, reason=reason)


def withhold_run(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> Path:
    """Publish a committed run whose secret was lost after its commitment was pushed, as a withheld run:
    ``REVEAL.json`` with ``"run_secret": null`` and ``WITHHELD_REASON`` (spec 11.6 publishes every committed run;
    the site shows it as withheld). Refused while the secret file exists: that run is revealed instead. The
    caller owns the run (:func:`run_lock`); the attempt's files move aside as in :func:`reveal_run`."""
    run_dir = Path(run_dir).resolve()
    _unpublished(run_dir)
    files = _files_of(run_dir, benchmark_id, environ)
    if os.path.lexists(files.secret):
        raise CommitError(f"the run secret of {benchmark_id} run {run_dir.name} exists ({files.secret}): reveal the "
                          "run instead (bench reveal without --withheld); a withheld run is only for a secret lost "
                          "after its push (spec 11.6)")
    record = _commitment_of(run_dir, benchmark_id)
    _set_aside(run_dir, files.attempt)
    path = run_dir / REVEAL_NAME
    store.write_json_atomic(path, {
        "schema": REVEAL_SCHEMA,
        "benchmark_id": benchmark_id,
        "run_label": run_dir.name,
        "commitment": record["commitment"],
        "run_secret": None,
        "status": "aborted",
        "reason": WITHHELD_REASON,
    })
    return path
