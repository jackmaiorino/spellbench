"""Commitment first and pushed, secret outside the repository, reveal, rerun (spec 11.6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench.commit import CommitError, commit_run, pushed_commit, reveal_run, secrets_dir
from spellbench.bench.run import rerun_games, run_benchmark

from test_bench_run import ENVIRON, _write_benchmark

# The merged Placement.parse form (COMPUTE-POLICY.md item 1): '<machine>=<disposition>: <reason>' per machine.
PLACEMENT = ("main-pc=used: selected, fastest measured; haleyspc=slower: idle, slower per game; "
             "runpod=not_authorized: no spending authority for a 1 h run")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "--bare", "-q", str(remote))
    work.mkdir()
    git(work, "init", "-q")
    git(work, "config", "user.email", "bench@example.org")
    git(work, "config", "user.name", "bench")
    git(work, "remote", "add", "origin", str(remote))
    (work / "benchmarks").mkdir()
    _write_benchmark(work / "benchmarks")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "benchmark")
    git(work, "push", "-q", "origin", "HEAD:main")
    return work


def env(tmp_path: Path) -> dict[str, str]:
    """The local values of a rated run: the secrets directory, and the pin root and register script Task 43 needs (R3-3)."""
    register = tmp_path / "register.py"
    register.write_text("import sys\n", encoding="utf-8")
    return {**ENVIRON, "SPELLBENCH_SECRETS_DIR": str(tmp_path / "secrets"), "SPELLBENCH_PIN_ROOT": str(tmp_path / "pins"),
            "SPELLBENCH_ARTIFACT_REGISTER": str(register)}


def test_a_committed_run_is_pushed_before_its_secret_exists_then_runs_with_its_proof(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ=env(tmp_path))
    assert committed.run_dir == bench / "runs" / "2026-10-01"
    assert json.loads((committed.run_dir / "COMMITMENT.json").read_text(encoding="utf-8"))["commitment"] == committed.commitment
    assert repo not in committed.secret_path.parents
    assert pushed_commit(committed.run_dir) == committed.commit == git(repo, "rev-parse", "HEAD")   # committed and pushed (R3-8)
    result = run_benchmark(bench, run="2026-10-01", proof="https://example.org/issues/1#c1", environ=env(tmp_path))
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.failures == () and manifest["secrets"]["commitment"] == committed.commitment
    assert manifest["secrets"]["commitment_proof"] == {"commit": committed.commit, "timestamp": "https://example.org/issues/1#c1"}
    assert rerun_games(result.run_dir, games=[0, 1], environ=env(tmp_path)) == []


def test_no_secret_is_kept_when_the_commitment_cannot_be_pushed(repo: Path, tmp_path: Path) -> None:
    git(repo, "remote", "remove", "origin")
    with pytest.raises(CommitError, match="not pushed"):
        commit_run(repo / "benchmarks" / "fake-pool", date="2026-10-01", placement=PLACEMENT, environ=env(tmp_path))
    assert not list((tmp_path / "secrets").rglob("*.hex"))                                      # R3-8


def test_a_commitment_changed_after_its_push_is_refused(repo: Path, tmp_path: Path) -> None:
    committed = commit_run(repo / "benchmarks" / "fake-pool", date="2026-10-01", placement=PLACEMENT, environ=env(tmp_path))
    path = committed.run_dir / "COMMITMENT.json"
    path.write_text(path.read_text(encoding="utf-8").replace(committed.commitment, "0" * 64), encoding="utf-8")
    git(repo, "commit", "-q", "-am", "swap the commitment")
    git(repo, "push", "-q", "origin", "HEAD")
    with pytest.raises(CommitError, match="changed after"):
        pushed_commit(committed.run_dir)                                                        # R3-8


def test_bench_commit_checks_the_local_values_before_publishing(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    head = git(repo, "rev-parse", "HEAD")
    for missing in ("SPELLBENCH_PIN_ROOT", "SPELLBENCH_ARTIFACT_REGISTER"):
        environ = {key: value for key, value in env(tmp_path).items() if key != missing}
        with pytest.raises(CommitError, match=missing):
            commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ=environ)
    with pytest.raises(CommitError, match="placement"):
        commit_run(bench, date="2026-10-01", placement="this PC only", environ=env(tmp_path))
    assert git(repo, "rev-parse", "HEAD") == head and not (bench / "runs").exists()            # nothing published (R3-14)


def test_the_secret_never_lands_in_the_repository(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    bench = repo / "benchmarks" / "fake-pool"
    home = {key: value for key, value in env(tmp_path).items() if key != "SPELLBENCH_SECRETS_DIR"}   # the home default
    committed = commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ=home)
    assert (tmp_path / "home") in committed.secret_path.parents and repo not in committed.secret_path.parents
    assert git(repo, "status", "--porcelain", "--untracked-files=all").splitlines() == []      # only the commitment, committed
    with pytest.raises(CommitError, match="outside the repository"):
        commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ={**home, "SPELLBENCH_SECRETS_DIR": str(repo / "secrets")})
    assert commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ=home).run_dir.name == "2026-10-01-2"


def test_a_committed_run_that_died_is_revealed(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ=env(tmp_path))
    reveal = reveal_run(committed.run_dir, benchmark_id="fake-pool", reason="error", environ=env(tmp_path))
    record = json.loads(reveal.read_text(encoding="utf-8"))
    assert record["status"] == "aborted" and record["commitment"] == committed.commitment and len(record["run_secret"]) == 64
    assert record["reason"] == "error"                                                          # a category, never exception text (R3-28)
    assert validate_tournament_dir(committed.run_dir) == []


def test_a_run_owned_by_another_invocation_is_never_revealed(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", placement=PLACEMENT, environ=env(tmp_path))
    (committed.secret_path.parent / "2026-10-01.lock").write_text("", encoding="utf-8")         # another bench run holds it
    with pytest.raises(CommitError, match="already"):
        run_benchmark(bench, run="2026-10-01", proof="https://example.org/i/1", environ=env(tmp_path))
    assert sorted(path.name for path in committed.run_dir.iterdir()) == ["COMMITMENT.json"]    # no REVEAL.json (R3-14)


def test_a_rerun_catches_a_changed_result(repo: Path, tmp_path: Path) -> None:
    result = run_benchmark(repo / "benchmarks" / "fake-pool", unrated=True, date="2026-10-01", environ=env(tmp_path))
    ledger = result.run_dir / "matches.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    rows[0]["game_digest"] = "sha256:" + "0" * 64
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert any("game 0" in mismatch for mismatch in rerun_games(result.run_dir, games=[0], environ=env(tmp_path)))
