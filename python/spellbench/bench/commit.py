"""bench commit: a pushed commitment before the first game, the secret kept outside the repository.

Flow (spec 11.1, 11.6; Decision 9; R3-8, R3-14): :func:`commit_run` first
checks the local values the rated run will need, so a missing value never
burns a published commitment. It then generates the run secret in memory,
writes ``runs/<run>/COMMITMENT.json``, commits only that file and pushes the
commit. Only after the push succeeded does the secret exist on disk, under the
secrets directory (the environment's ``SPELLBENCH_SECRETS_DIR``, then
``benchmarks/local.json``, then ``~/.spellbench/run-secrets``; never inside
the repository work tree), with the placement note beside it — so no usable
secret ever exists without a public commitment, which spec 11.6 then forces
the run to reveal.

``git`` runs through ``subprocess`` with ``-C <run dir>``; the pushed state is
always checked after a fetch, never from stale local refs. ``REVEAL_NAME`` and
``REVEAL_SCHEMA`` come from ``arena.validate``: arena code never imports this
layer (R3-4).
"""

from __future__ import annotations

import datetime
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..arena import store
from ..arena.manifest import commitment_record
from ..arena.throughput import Placement, ThroughputError
from ..arena.validate import REVEAL_NAME, REVEAL_REASONS, REVEAL_SCHEMA
from ..run_secret import RunSecret
from . import definition

SECRETS_DIR_NAME = "SPELLBENCH_SECRETS_DIR"
PIN_ROOT_NAME = "SPELLBENCH_PIN_ROOT"
ARTIFACT_REGISTER_NAME = "SPELLBENCH_ARTIFACT_REGISTER"
REMOTE = "origin"


class CommitError(ValueError):
    """The commitment flow failed; nothing usable exists without a public commitment (spec 11.6)."""


@dataclass(frozen=True)
class CommittedRun:
    run_dir: Path
    commitment: str
    secret_path: Path
    commit: str  # the pushed commit that added COMMITMENT.json


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One git invocation in ``cwd``; the caller checks the return code."""
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _git_checked(cwd: Path, *args: str) -> str:
    """One git invocation that must succeed; its stdout, stripped."""
    result = _git(cwd, *args)
    if result.returncode != 0:
        raise CommitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _write_exclusive(path: Path, text: str) -> None:
    """Write ``text`` to a fresh file, mode 0o600, refusing to overwrite (the secret, its note, the lock)."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, text.encode("utf-8"))
    finally:
        os.close(descriptor)


def secrets_dir(environ: Mapping[str, str], local: Mapping[str, str]) -> Path:
    """The run-secrets directory: the environment, then ``benchmarks/local.json``, then the home default."""
    value = environ.get(SECRETS_DIR_NAME) or local.get(SECRETS_DIR_NAME)
    if value:
        return Path(value)
    return Path.home() / ".spellbench" / "run-secrets"


def _secrets_dir_for(run_dir: Path, environ: Mapping[str, str] | None) -> Path:
    env = os.environ if environ is None else environ
    return secrets_dir(env, definition.load_local_values(run_dir.parents[2]))


def commit_run(
    benchmark_dir: Path, *, placement: str, date: str | None = None, environ: Mapping[str, str] | None = None
) -> CommittedRun:
    """Commit and push a run's commitment, then keep its secret outside the repository.

    ``date`` (YYYY-MM-DD) defaults to today; ``environ`` to ``os.environ``.
    Every check that can fail runs before anything is published: a failure is
    a :class:`CommitError` naming the value, and nothing is committed (R3-14).
    """
    benchmark_dir = Path(benchmark_dir).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    env = os.environ if environ is None else environ
    local = definition.load_local_values(benchmark_dir.parent)
    # The local values the rated run will need, checked before anything is
    # published: a missing value found after the push would burn the commitment.
    if not (env.get(PIN_ROOT_NAME) or local.get(PIN_ROOT_NAME)):
        raise CommitError(f"{PIN_ROOT_NAME} is not set (the environment or benchmarks/{definition.LOCAL_VALUES_FILE})")
    register = env.get(ARTIFACT_REGISTER_NAME) or local.get(ARTIFACT_REGISTER_NAME)
    if not register or not Path(register).is_file():
        raise CommitError(
            f"{ARTIFACT_REGISTER_NAME} must name an existing file (the environment or "
            f"benchmarks/{definition.LOCAL_VALUES_FILE})"
        )
    try:
        Placement.parse(placement)
    except ThroughputError as exc:
        raise CommitError(f"the placement note does not parse: {exc}") from exc
    if date is None:
        date = datetime.date.today().isoformat()
    name = definition.next_run_name(benchmark_dir, date)
    secrets = secrets_dir(env, local)
    toplevel = Path(_git_checked(benchmark_dir, "rev-parse", "--show-toplevel")).resolve()
    resolved = secrets.resolve()
    if resolved == toplevel or toplevel in resolved.parents:
        raise CommitError(f"the secrets directory {SECRETS_DIR_NAME}={secrets} must be outside the repository {toplevel}")
    secret = RunSecret.generate()
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    record = commitment_record(run_secret=secret, benchmark_id=benchmark.id, run_label=name)
    store.write_json_atomic(run_dir / store.COMMITMENT_NAME, record)
    _git_checked(run_dir, "add", "--", store.COMMITMENT_NAME)
    _git_checked(run_dir, "commit", "-q", "-m", f"Spellbench: commitment for {benchmark.id} run {name}", "--",
                 store.COMMITMENT_NAME)
    pushed = _git(run_dir, "push", "-q", REMOTE, "HEAD")
    if pushed.returncode != 0:
        # The secret is dropped: no usable secret ever exists without a public
        # commitment (spec 11.6 then forces its reveal).
        raise CommitError(f"the commitment was not pushed: {pushed.stderr.strip()}")
    commit = _git_checked(run_dir, "rev-parse", "HEAD")
    secret_dir = secrets / benchmark.id
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_path = secret_dir / f"{name}.hex"
    _write_exclusive(secret_path, secret.hex() + "\n")
    _write_exclusive(secret_dir / f"{name}.placement.txt", placement + "\n")
    return CommittedRun(run_dir=run_dir, commitment=secret.commitment(), secret_path=secret_path, commit=commit)


def load_run_secret(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> RunSecret:
    """The secret ``bench commit`` kept for this run, under the secrets directory."""
    path = _secrets_dir_for(run_dir, environ) / benchmark_id / f"{run_dir.name}.hex"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CommitError(f"cannot read the run secret of {benchmark_id} run {run_dir.name}: {exc}") from exc
    try:
        return RunSecret.from_hex(text.strip())
    except ValueError as exc:
        raise CommitError(f"the run secret of {benchmark_id} run {run_dir.name}: {exc}") from exc


def load_placement(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> str:
    """The placement note recorded beside the secret at ``bench commit``."""
    path = _secrets_dir_for(run_dir, environ) / benchmark_id / f"{run_dir.name}.placement.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CommitError(f"cannot read the placement note of {benchmark_id} run {run_dir.name}: {exc}") from exc


def pushed_commit(run_dir: Path) -> str:
    """The pushed commit that added this run's ``COMMITMENT.json``, still its last change (spec 11.6, R3-8).

    Fetches ``REMOTE`` first, so the check reads the remote's current state,
    not stale local refs. An untracked or locally modified file, or an adding
    commit on no remote-tracking branch, is a :class:`CommitError` naming the
    missing step; a last change that differs from the adding commit proves
    nothing and is refused on its own words.
    """
    prefix = "the commitment is not in a pushed commit:"
    fetched = _git(run_dir, "fetch", "-q", REMOTE)
    if fetched.returncode != 0:
        raise CommitError(f"{prefix} cannot fetch {REMOTE}: {fetched.stderr.strip()}")
    if _git(run_dir, "ls-files", "--error-unmatch", store.COMMITMENT_NAME).returncode != 0:
        raise CommitError(f"{prefix} commit it before the first game (spec 11.6)")
    if _git(run_dir, "diff", "--quiet", "HEAD", "--", store.COMMITMENT_NAME).returncode != 0:
        raise CommitError(f"{prefix} commit the local change before the first game (spec 11.6)")
    added = _git_checked(run_dir, "log", "-n", "1", "--format=%H", "--diff-filter=A", "--", store.COMMITMENT_NAME)
    if not added:
        raise CommitError(f"{prefix} commit it before the first game (spec 11.6)")
    last = _git_checked(run_dir, "log", "-n", "1", "--format=%H", "--", store.COMMITMENT_NAME)
    if last != added:
        raise CommitError(
            f"the commitment was changed after its first push ({last}); a changed commitment proves nothing (spec 11.6)"
        )
    if not _git_checked(run_dir, "branch", "-r", "--contains", added):
        raise CommitError(f"{prefix} push it before the first game (spec 11.6)")
    return added


def reveal_run(run_dir: Path, *, benchmark_id: str, reason: str, environ: Mapping[str, str] | None = None) -> Path:
    """Publish a committed run that died before its manifest: ``REVEAL.json`` with the secret (spec 11.6).

    ``reason`` is one of ``REVEAL_REASONS`` — a fixed category, never exception
    text, which could carry local paths (R3-28). Returns the reveal's path.
    """
    if reason not in REVEAL_REASONS:
        raise CommitError(f"the reveal reason must be one of {REVEAL_REASONS}, got {reason!r}")
    if store.is_published(run_dir):
        raise CommitError(f"{run_dir} is already published (it has a manifest)")
    secret = load_run_secret(run_dir, benchmark_id=benchmark_id, environ=environ)
    try:
        record = store.read_json(run_dir / store.COMMITMENT_NAME)
    except store.StoreError as exc:
        raise CommitError(f"cannot read the run's {store.COMMITMENT_NAME}: {exc}") from exc
    if secret.commitment() != record.get("commitment"):
        raise CommitError(f"the run secret does not hash to the commitment in {store.COMMITMENT_NAME}")
    reveal = {
        "schema": REVEAL_SCHEMA,
        "benchmark_id": benchmark_id,
        "run_label": run_dir.name,
        "commitment": record["commitment"],
        "run_secret": secret.hex(),
        "status": "aborted",
        "reason": reason,
    }
    path = run_dir / REVEAL_NAME
    store.write_json_atomic(path, reveal)
    return path
