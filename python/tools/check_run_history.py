#!/usr/bin/env python3
"""CI: no committed run disappears, no commitment stays unrevealed, no run strays from its commitment (spec 11.6).

Every committed run is published (spec 11.6; Decision 9, R3-8): with a manifest, or with ``REVEAL.json`` (revealed
after an abort, or withheld when its secret was lost). This check reads the work tree and the history of the
repository holding the current directory, from its top (``git rev-parse --show-toplevel``), and reports:

1. A deleted publication: every path under ``benchmarks/*/runs/`` or ``benchmarks/*/snapshots/`` deleted
   between ``--base`` and ``HEAD``
   (``git diff --no-renames --name-only --diff-filter=D BASE...HEAD -- benchmarks``). ``--no-renames``, so a run
   directory that was moved or renamed is reported under its old path, where git's rename detection would hide
   the move. A base of zeros (GitHub's ``before`` for a new branch), an empty base, or one git cannot resolve
   skips this part, with a note.
2. An unrevealed commitment: a run directory holding ``COMMITMENT.json`` and neither ``manifest.json`` nor
   ``REVEAL.json``, whose commitment was committed more than ``--max-age-days`` days ago (the committer date that
   ``git log -n 1 --diff-filter=A --format=%ct -- <path>`` gives). A commitment not committed yet is not stale.
3. A config its commitment did not fix: a run directory holding a manifest whose ``secrets.commitment_proof`` is
   not null played under a pushed commitment, which fixed the benchmark's definition (the Task 41 rulings). Its
   ``config.json`` must be, byte for byte, the config that ``benchmark.json`` at the commitment commit gives the
   run, built as ``bench run`` builds it (``bench/run.py``'s ``_config``) and written as the arena writes it.
4. An edited snapshot: an existing file under ``benchmarks/*/snapshots/`` modified between ``--base`` and
   ``HEAD``. A refit publishes a new dated snapshot; it cannot rewrite an earlier publication.

Prints one line per problem, naming the path, and exits 1; prints ``OK`` and exits 0 otherwise. Parts 1 and 2 use
the standard library and ``git`` alone; part 3 imports ``spellbench``, and only when some run carries a proof.

Usage (CI runs it with ``uv run --no-sync``)::

    python python/tools/check_run_history.py --base REF [--max-age-days N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

BENCHMARKS_DIR = "benchmarks"
RUNS_DIR = "runs"
BENCHMARK_FILE = "benchmark.json"
MANIFEST_NAME = "manifest.json"
COMMITMENT_NAME = "COMMITMENT.json"
REVEAL_NAME = "REVEAL.json"
CONFIG_NAME = "config.json"
DEFAULT_MAX_AGE_DAYS = 3
SECONDS_PER_DAY = 86_400
# The variables that point git at another repository (``git rev-parse --local-env-vars``), dropped as
# ``bench/commit.py`` drops them: every command here acts on the repository holding the current directory.
GIT_REPOSITORY_VARS = frozenset({
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
})
# A commitment proof's commit, as arena.manifest.CommitmentProof writes it: a full object name.
_COMMIT = re.compile(r"[0-9a-f]{40}")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """``git ARGS`` in ``root``, its output captured as bytes."""
    environment = {key: value for key, value in os.environ.items() if key not in GIT_REPOSITORY_VARS}
    return subprocess.run(["git", *args], cwd=root, capture_output=True, env=environment, stdin=subprocess.DEVNULL)


def _said(result: subprocess.CompletedProcess[bytes]) -> str:
    """What git said on stderr, as one line."""
    lines = [line.strip() for line in result.stderr.decode("utf-8", "replace").splitlines() if line.strip()]
    return "; ".join(lines) or f"git exited with status {result.returncode}"


def _relative(root: Path, path: Path) -> str:
    """``path`` relative to the repository's top, with ``/`` separators, as git names it."""
    return path.relative_to(root).as_posix()


def _run_dirs(root: Path, name: str) -> list[Path]:
    """The run directories under ``benchmarks/*/runs/`` holding a file named ``name``, sorted."""
    return sorted(path.parent for path in (root / BENCHMARKS_DIR).glob(f"*/{RUNS_DIR}/*/{name}") if path.is_file())


# ---------------------------------------------------------------------------
# 1. Deleted runs
# ---------------------------------------------------------------------------


def deleted_runs(root: Path, base: str) -> tuple[list[str], list[str]]:
    """The problems, one per path under ``benchmarks/*/runs/`` deleted between ``base`` and ``HEAD``, and the notes
    (this part skipped)."""
    if not base.strip("0"):
        return [], [f"note: the base {base or '(empty)'} names no commit (a new branch): the deleted-run check is "
                    "skipped"]
    if _git(root, "rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode != 0:
        return [], [f"note: git cannot resolve the base {base}: the deleted-run check is skipped"]
    result = _git(root, "diff", "-z", "--no-renames", "--name-only", "--diff-filter=D", f"{base}...HEAD", "--",
                  BENCHMARKS_DIR)
    if result.returncode != 0:
        return [f"deleted: cannot list the paths under {BENCHMARKS_DIR}/ deleted since {base}: {_said(result)}"], []
    paths = sorted(path.decode("utf-8", "surrogateescape") for path in result.stdout.split(b"\0") if path)
    return [
        f"deleted: {path} was deleted since {base}: a committed run stays published (spec 11.6)"
        for path in paths
        if _is_run_path(path)
    ], []


def _is_run_path(path: str) -> bool:
    """Whether a repository-relative path lies under a benchmark's runs or snapshots."""
    parts = PurePosixPath(path).parts
    return len(parts) > 3 and parts[0] == BENCHMARKS_DIR and parts[2] in (RUNS_DIR, "snapshots")


def modified_snapshots(root: Path, base: str) -> list[str]:
    """An existing snapshot stays immutable; refitting publishes a new dated snapshot."""
    if not base.strip("0") or _git(root, "rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode != 0:
        return []
    result = _git(root, "diff", "-z", "--no-renames", "--name-only", "--diff-filter=M", f"{base}...HEAD", "--",
                  BENCHMARKS_DIR)
    if result.returncode != 0:
        return [f"snapshot history: cannot list modified publications: {_said(result)}"]
    paths = [path.decode("utf-8", "surrogateescape") for path in result.stdout.split(b"\0") if path]
    return [f"modified: {path}: a published snapshot is immutable; compose a new dated snapshot"
            for path in sorted(paths) if _is_run_path(path) and PurePosixPath(path).parts[2] == "snapshots"]


# ---------------------------------------------------------------------------
# 2. Unrevealed commitments
# ---------------------------------------------------------------------------


def stale_commitments(root: Path, *, max_age_days: int, now: float) -> list[str]:
    """The problems, one per run directory whose only publication is a commitment committed more than
    ``max_age_days`` days before ``now``."""
    problems = []
    for run_dir in _run_dirs(root, COMMITMENT_NAME):
        if (run_dir / MANIFEST_NAME).exists() or (run_dir / REVEAL_NAME).exists():
            continue
        path = _relative(root, run_dir / COMMITMENT_NAME)
        result = _git(root, "log", "-n", "1", "--diff-filter=A", "--format=%ct", "--", path)
        if result.returncode != 0:
            problems.append(f"unrevealed: cannot tell when {path} was committed: {_said(result)}")
            continue
        added = result.stdout.decode("ascii", "replace").strip()
        if not added:
            continue  # not committed yet: nothing is public, so nothing is overdue
        age_days = (now - int(added)) / SECONDS_PER_DAY
        if age_days > max_age_days:
            problems.append(
                f"unrevealed: {path} was committed {int(age_days)} days ago and its run is neither published nor "
                "revealed (spec 11.6): publish its manifest, or run spellbench bench reveal (with --withheld when "
                "its secret is lost)"
            )
    return problems


# ---------------------------------------------------------------------------
# 3. Configs fixed by their commitments
# ---------------------------------------------------------------------------


def committed_configs(root: Path) -> list[str]:
    """The problems, one per run whose manifest carries a commitment proof and whose ``config.json`` is not the
    config its benchmark's definition at the commitment commit gives."""
    problems = []
    for run_dir in _run_dirs(root, MANIFEST_NAME):
        try:
            proof = _commitment_proof(run_dir / MANIFEST_NAME)
            problem = None if proof is None else _config_problem(root, run_dir, proof)
        except Exception as exc:  # noqa: BLE001 - whatever the files hold, the check reports a line, never a traceback
            problem = f"cannot be checked: {type(exc).__name__}: {exc}"
        if problem is not None:
            problems.append(f"config: {_relative(root, run_dir)}: {problem}")
    return problems


def _commitment_proof(path: Path) -> Any:
    """The manifest's ``secrets.commitment_proof``; None when it has none (a protocol v1 run, an unrated run)."""
    manifest = json.loads(path.read_bytes())
    secrets = manifest.get("secrets") if isinstance(manifest, dict) else None
    return secrets.get("commitment_proof") if isinstance(secrets, dict) else None


def _config_problem(root: Path, run_dir: Path, proof: Any) -> str | None:
    """Why ``run_dir``'s ``config.json`` is not the config its commitment commit fixed, or None."""
    commit = proof.get("commit") if isinstance(proof, dict) else None
    if type(commit) is not str or not _COMMIT.fullmatch(commit):
        return f"its commitment proof names no commit: {proof!r}"
    if _git(root, "rev-parse", "-q", "--verify", f"{commit}^{{commit}}").returncode != 0:
        return f"git cannot read its commitment commit {commit}"
    definition_path = _relative(root, run_dir.parent.parent / BENCHMARK_FILE)
    shown = _git(root, "show", f"{commit}:{definition_path}")
    if shown.returncode != 0:
        return f"{definition_path} is missing at its commitment commit {commit}"
    try:
        expected = expected_config(shown.stdout, run_dir.name)
    except Exception as exc:  # noqa: BLE001 - a definition that does not give a config is this run's problem
        return f"{definition_path} at its commitment commit {commit} gives no config: {exc}"
    try:
        recorded = (run_dir / CONFIG_NAME).read_bytes()
    except OSError as exc:
        return f"cannot read {CONFIG_NAME}: {exc.strerror or exc}"
    if recorded != expected:
        return (f"{CONFIG_NAME} is not the config {definition_path} gives at its commitment commit {commit}: the "
                "commitment fixed the benchmark's definition (spec 11.6)")
    return None


def expected_config(document: bytes, name: str) -> bytes:
    """The ``config.json`` bytes of run ``name`` under the definition ``document`` (the bytes of a
    ``benchmark.json``): the config ``bench run`` plays (``bench/run.py``'s ``_config``), as the arena writes it
    (``store.write_json_atomic``)."""
    # Imported here: parts 1 and 2 need nothing but the standard library and git.
    from spellbench.arena import store
    from spellbench.arena.config import TournamentConfig
    from spellbench.bench import definition
    from spellbench.wire import strict_json_loads

    benchmark = definition.parse_benchmark(strict_json_loads(document))
    config = TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))
    return store.canonical_bytes(config.to_json()) + b"\n"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def repository_root(directory: Path) -> Path | None:
    """The top of the git work tree holding ``directory``, or None."""
    result = _git(directory, "rev-parse", "--show-toplevel")
    top = result.stdout.decode("utf-8", "surrogateescape").strip()
    return Path(top) if result.returncode == 0 and top else None


def check(root: Path, *, base: str, max_age_days: int, now: float) -> tuple[list[str], list[str]]:
    """The problems of the three parts, in order, and the notes."""
    problems, notes = deleted_runs(root, base)
    problems += stale_commitments(root, max_age_days=max_age_days, now=now)
    problems += committed_configs(root)
    problems += modified_snapshots(root, base)
    return problems, notes


def _days(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")  # a path that is not valid UTF-8 still prints
    parser = argparse.ArgumentParser(description="The run-history check of CI (spec 11.6).")
    # nargs="?": a shell that drops an empty argument still passes an empty base, which skips part 1.
    parser.add_argument("--base", required=True, nargs="?", const="", metavar="REF",
                        help="the commit HEAD is compared with; zeros or nothing skip the deleted-run check")
    parser.add_argument("--max-age-days", type=_days, default=DEFAULT_MAX_AGE_DAYS, metavar="N",
                        help=f"the days a commitment may stay unrevealed (default {DEFAULT_MAX_AGE_DAYS})")
    args = parser.parse_args(argv)
    root = repository_root(Path.cwd())
    if root is None:
        print("error: run the check inside the repository's git work tree")
        return 1
    problems, notes = check(root, base=args.base.strip(), max_age_days=args.max_age_days, now=time.time())
    for line in notes + problems:
        print(line)
    if problems:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
