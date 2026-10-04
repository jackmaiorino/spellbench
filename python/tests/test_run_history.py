"""Public runs stay available and match the definition their commitment fixed."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spellbench.arena import store
from spellbench.arena.config import TournamentConfig
from spellbench.bench.definition import load_benchmark
from test_bench_run import _write_benchmark

TOOL = Path(__file__).parents[1] / "tools/check_run_history.py"


def git(repo, *args, date=None):
    environment = dict(os.environ)
    if date:
        environment.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(["git", *args], cwd=repo, env=environment, capture_output=True,
                          text=True, check=True).stdout.strip()


def check(repo, base):
    return subprocess.run([sys.executable, str(TOOL), "--base", base], cwd=repo,
                          capture_output=True, text=True)


@pytest.fixture
def history(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    bench = _write_benchmark(root / "benchmarks")
    run = bench / "runs/2026-10-01"
    run.mkdir(parents=True)
    store.write_json_atomic(run / "manifest.json", {})
    git(root, "init", "-q")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "published run")
    return root, bench, run, git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize("rename", [False, True])
def test_deleted_or_moved_run_is_reported(history, rename):
    root, bench, run, base = history
    assert check(root, base).returncode == 0
    if rename:
        git(root, "mv", str(run.relative_to(root)), str((run.parent / "2026-10-02").relative_to(root)))
    else:
        git(root, "rm", "-r", str(run.relative_to(root)))
    git(root, "commit", "-q", "-m", "remove old publication")
    result = check(root, base)
    assert result.returncode == 1 and "runs/2026-10-01/manifest.json" in result.stdout


@pytest.mark.parametrize("delete", [False, True])
def test_published_snapshots_are_immutable(history, delete):
    root, bench, _, _ = history
    path = bench / "snapshots" / "2026-10-02" / "manifest.json"
    path.parent.mkdir(parents=True)
    store.write_json_atomic(path, {"fixture": "snapshot"})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "publish snapshot")
    base = git(root, "rev-parse", "HEAD")
    if delete:
        git(root, "rm", str(path.relative_to(root)))
    else:
        store.write_json_atomic(path, {"fixture": "changed"})
        git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "alter snapshot")
    result = check(root, base)
    assert result.returncode == 1 and "snapshots/2026-10-02/manifest.json" in result.stdout


def test_old_pending_commitment_is_reported_until_revealed(history):
    root, bench, _, base = history
    pending = bench / "runs/2026-10-02"
    pending.mkdir()
    store.write_json_atomic(pending / "COMMITMENT.json", {})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "commitment", date="2026-01-01T00:00:00+00:00")
    result = check(root, base)
    assert result.returncode == 1 and "unrevealed" in result.stdout
    store.write_json_atomic(pending / "REVEAL.json", {})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "reveal")
    assert check(root, base).returncode == 0


def test_config_is_compared_with_the_commitment_definition(history):
    root, bench, run, base = history
    config = TournamentConfig.from_json(load_benchmark(bench).tournament_config("runs/2026-10-01")).to_json()
    store.write_json_atomic(run / "manifest.json", {"secrets": {"commitment_proof": {"commit": base}}})
    store.write_json_atomic(run / "config.json", config)
    changed = json.loads((bench / "benchmark.json").read_text())
    changed["stats_seed"] += 1
    store.write_json_atomic(bench / "benchmark.json", changed)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "later definition")
    assert check(root, base).returncode == 0
    store.write_json_atomic(run / "config.json", {**config, "stats_seed": config["stats_seed"] + 1})
    result = check(root, base)
    assert result.returncode == 1 and "config.json is not the config" in result.stdout
