"""Commitment first and pushed, secret outside the repository, reveal, rerun (spec 11.6).

Every test that commits or pushes does so in a throwaway repository under ``tmp_path`` whose ``origin`` is a local
bare repository; the autouse ``git_guard`` checks each git command's resolved top level before it runs.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spellbench.arena import cli, runner, store
from spellbench.arena.manifest import commitment_record
from spellbench.arena.validate import REVEAL_KEYS, REVEAL_SCHEMA, check_reveal, validate_tournament_dir
from spellbench.bench import commit as bench_commit
from spellbench.bench.commit import (
    GIT_REPOSITORY_VARS,
    CommitError,
    commit_run,
    load_placement,
    pushed_commit,
    reveal_run,
    secrets_dir,
)
from spellbench.bench.run import rerun_games, run_benchmark
from spellbench.run_secret import RunSecret

from test_bench_run import ENVIRON, _write_benchmark

PLACEMENT = ("main-pc=used: fastest measured; haleyspc=slower: about half the speed per game; "
             "runpod=not_authorized: not needed for a 1 h run")
PROOF = "https://example.org/issues/1#c1"
RUN = "2026-10-01"


def git(cwd: Path, *args: str) -> str:
    """git in ``cwd``, with no variable pointing it at another repository."""
    environment = {key: value for key, value in os.environ.items() if key not in GIT_REPOSITORY_VARS}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=environment).stdout.strip()


@pytest.fixture(autouse=True)
def git_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """No test here can reach the real repository or its remote: every git command, the code's and the tests' own,
    must act on a repository under ``tmp_path`` (its resolved top level, or outside a work tree its directory, is
    checked before it runs). Records, at each push, the run secret files that existed then."""
    for name in GIT_REPOSITORY_VARS:
        monkeypatch.delenv(name, raising=False)
    real_run, root, pushes = subprocess.run, tmp_path.resolve(), []

    def guarded(args: Any, *rest: Any, **kwargs: Any) -> Any:
        if isinstance(args, (list, tuple)) and args and args[0] == "git":
            directory = Path(args[2]) if len(args) > 2 and args[1] == "-C" else Path(kwargs.get("cwd") or os.getcwd())
            top = real_run(["git", "-C", str(directory), "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True)
            where = Path(top.stdout.strip()) if top.returncode == 0 and top.stdout.strip() else directory
            assert where.resolve() == root or root in where.resolve().parents, f"git {args[1:]} outside {root}"
            if "push" in args:
                pushes.append(sorted(path.name for path in root.rglob(f"*{bench_commit.SECRET_SUFFIX}")))
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)
    return SimpleNamespace(pushes=pushes)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "--bare", "-q", str(remote))
    work.mkdir()
    git(work, "init", "-q")
    assert Path(git(work, "rev-parse", "--show-toplevel")).resolve() == work.resolve()  # a throwaway repository
    git(work, "config", "user.email", "bench@example.org")
    git(work, "config", "user.name", "bench")
    git(work, "config", "commit.gpgsign", "false")  # the machine's signing setup plays no part
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


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _drop_the_pushed_branch(repo: Path, tmp_path: Path) -> None:
    """Delete, on the remote only, the branch the commitment was pushed to: the local remote-tracking branch goes stale."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(tmp_path / "remote.git", "update-ref", "-d", f"refs/heads/{branch}")


def test_a_committed_run_is_pushed_before_its_secret_exists_then_runs_with_its_proof(
    repo: Path, tmp_path: Path, git_guard: SimpleNamespace
) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    assert committed.run_dir == bench / "runs" / RUN
    assert json.loads((committed.run_dir / "COMMITMENT.json").read_text(encoding="utf-8"))["commitment"] == committed.commitment
    assert repo not in committed.secret_path.parents
    assert pushed_commit(committed.run_dir) == committed.commit == git(repo, "rev-parse", "HEAD")   # committed and pushed (R3-8)
    assert git_guard.pushes[-1] == [] and committed.secret_path.is_file()      # no secret existed when it was pushed
    secret = RunSecret.from_hex(committed.secret_path.read_text(encoding="ascii").strip())
    assert secret.commitment() == committed.commitment
    assert load_placement(committed.run_dir, benchmark_id="fake-pool", environ=env(tmp_path)) == PLACEMENT
    assert git(repo, "log", "-1", "--format=%s") == f"Spellbench: commitment for fake-pool run {RUN}"
    result = run_benchmark(bench, run=RUN, proof=PROOF, environ=env(tmp_path))
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.failures == () and manifest["secrets"]["commitment"] == committed.commitment
    assert manifest["secrets"]["commitment_proof"] == {"commit": committed.commit, "timestamp": PROOF}
    assert manifest["secrets"]["run_secret"] == secret.hex() and manifest["run"]["label"] == RUN
    assert not committed.secret_path.with_name(f"{RUN}.lock").exists()        # released at the end
    assert rerun_games(result.run_dir, games=[0, 1], environ=env(tmp_path)) == []
    with pytest.raises(CommitError, match="published"):                        # its manifest reveals the secret
        reveal_run(result.run_dir, benchmark_id="fake-pool", reason="error", environ=env(tmp_path))
    with pytest.raises(CommitError, match="already running or finished"):
        run_benchmark(bench, run=RUN, proof=PROOF, environ=env(tmp_path))


def test_the_commitment_commit_holds_the_commitment_alone(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    (repo / "notes.txt").write_text("staged\n", encoding="utf-8")
    git(repo, "add", "notes.txt")
    (bench / "benchmark.json").write_bytes((bench / "benchmark.json").read_bytes() + b"\n")
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    assert git(repo, "show", "--name-only", "--format=", committed.commit).splitlines() == [
        f"benchmarks/fake-pool/runs/{RUN}/COMMITMENT.json"
    ]
    assert git(repo, "diff", "--cached", "--name-only") == "notes.txt"           # the operator's work stays theirs
    assert git(repo, "diff", "--name-only") == "benchmarks/fake-pool/benchmark.json"


def test_no_secret_is_kept_when_the_commitment_cannot_be_pushed(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    (repo / "notes.txt").write_text("staged\n", encoding="utf-8")
    git(repo, "add", "notes.txt")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "remote", "remove", "origin")
    with pytest.raises(CommitError, match="not pushed"):
        commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    assert not list((tmp_path / "secrets").rglob("*.hex"))                                      # R3-8
    assert not list((tmp_path / "secrets").rglob("*.placement.txt"))
    assert git(repo, "rev-parse", "HEAD") == head and not (bench / "runs").exists()            # its local commit undone
    assert git(repo, "diff", "--cached", "--name-only") == "notes.txt"


def test_a_commitment_changed_after_its_push_is_refused(repo: Path, tmp_path: Path) -> None:
    committed = commit_run(repo / "benchmarks" / "fake-pool", date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    path = committed.run_dir / "COMMITMENT.json"
    path.write_bytes(path.read_bytes().replace(committed.commitment.encode("ascii"), b"0" * 64))
    git(repo, "commit", "-q", "-am", "swap the commitment")
    git(repo, "push", "-q", "origin", "HEAD")
    with pytest.raises(CommitError, match="changed after"):
        pushed_commit(committed.run_dir)                                                        # R3-8


def _write_commitment(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(run_dir / "COMMITMENT.json",
                            commitment_record(run_secret=RunSecret.generate(), benchmark_id="fake-pool", run_label=RUN))


@pytest.mark.parametrize("case", ["untracked", "staged", "modified", "unpushed", "remote branch deleted",
                                  "removed and added again"])
def test_pushed_commit_names_what_is_missing(repo: Path, tmp_path: Path, case: str) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    run_dir = bench / "runs" / RUN
    expected = "the commitment is not in a pushed commit"
    if case in ("untracked", "staged", "unpushed"):
        _write_commitment(run_dir)
        if case != "untracked":
            git(repo, "add", "-A")
        if case == "unpushed":
            git(repo, "commit", "-q", "-m", "a commitment never pushed")
    else:
        commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
        if case == "modified":
            (run_dir / "COMMITMENT.json").write_bytes(b"{}\n")
        elif case == "remote branch deleted":
            _drop_the_pushed_branch(repo, tmp_path)     # fetched with --prune, the stale branch no longer counts
        else:
            git(repo, "rm", "-q", "-r", f"benchmarks/fake-pool/runs/{RUN}")
            git(repo, "commit", "-q", "-m", "drop the commitment")
            _write_commitment(run_dir)                  # another commitment under the same name
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "commit again")
            git(repo, "push", "-q", "origin", "HEAD")
            expected = "changed after its first push"
    with pytest.raises(CommitError, match=expected):
        pushed_commit(run_dir)


def test_bench_commit_checks_the_local_values_before_publishing(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    head = git(repo, "rev-parse", "HEAD")
    for missing in ("SPELLBENCH_PIN_ROOT", "SPELLBENCH_ARTIFACT_REGISTER"):
        environ = {key: value for key, value in env(tmp_path).items() if key != missing}
        with pytest.raises(CommitError, match=missing):
            commit_run(bench, date=RUN, placement=PLACEMENT, environ=environ)
    with pytest.raises(CommitError, match="SPELLBENCH_ARTIFACT_REGISTER"):
        commit_run(bench, date=RUN, placement=PLACEMENT,
                   environ={**env(tmp_path), "SPELLBENCH_ARTIFACT_REGISTER": str(tmp_path / "no-such-script.py")})
    with pytest.raises(CommitError, match="placement"):
        commit_run(bench, date=RUN, placement="this PC only", environ=env(tmp_path))
    assert git(repo, "rev-parse", "HEAD") == head and not (bench / "runs").exists()            # nothing published (R3-14)
    assert not (tmp_path / "secrets").exists()


def test_local_json_supplies_the_local_values(repo: Path, tmp_path: Path) -> None:
    names = ("SPELLBENCH_SECRETS_DIR", "SPELLBENCH_PIN_ROOT", "SPELLBENCH_ARTIFACT_REGISTER")
    values = env(tmp_path)
    (repo / "benchmarks" / "local.json").write_text(json.dumps({name: values[name] for name in names}), encoding="utf-8")
    committed = commit_run(repo / "benchmarks" / "fake-pool", date=RUN, placement=PLACEMENT, environ=ENVIRON)
    assert (tmp_path / "secrets") in committed.secret_path.parents


def test_the_secrets_directory_comes_from_the_environment_then_local_json_then_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    name, first, second = "SPELLBENCH_SECRETS_DIR", tmp_path / "first", tmp_path / "second"
    assert secrets_dir({name: str(first)}, {name: str(second)}) == first
    assert secrets_dir({name: ""}, {name: str(second)}) == second
    assert secrets_dir({}, {}) == tmp_path / "home" / ".spellbench" / "run-secrets"


def test_the_secret_never_lands_in_the_repository(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    bench = repo / "benchmarks" / "fake-pool"
    home = {key: value for key, value in env(tmp_path).items() if key != "SPELLBENCH_SECRETS_DIR"}   # the home default
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=home)
    assert (tmp_path / "home") in committed.secret_path.parents and repo not in committed.secret_path.parents
    assert git(repo, "status", "--porcelain", "--untracked-files=all").splitlines() == []      # only the commitment, committed
    inside = [repo / "secrets", repo, bench / "runs"]
    link = tmp_path / "link-to-repo"
    try:
        link.symlink_to(repo, target_is_directory=True)
        inside.append(link / "secrets")                                                         # the repository, by another path
    except (OSError, NotImplementedError):
        pass                                                                                    # no symbolic links here (Windows)
    for folder in inside:
        with pytest.raises(CommitError, match="outside the repository"):
            commit_run(bench, date=RUN, placement=PLACEMENT, environ={**home, "SPELLBENCH_SECRETS_DIR": str(folder)})
    assert commit_run(bench, date=RUN, placement=PLACEMENT, environ=home).run_dir.name == "2026-10-01-2"


def test_a_committed_run_that_died_is_revealed(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    reveal = reveal_run(committed.run_dir, benchmark_id="fake-pool", reason="error", environ=env(tmp_path))
    record = json.loads(reveal.read_text(encoding="utf-8"))
    assert record["status"] == "aborted" and record["commitment"] == committed.commitment and len(record["run_secret"]) == 64
    assert record["reason"] == "error"                                                          # a category, never exception text (R3-28)
    assert validate_tournament_dir(committed.run_dir) == []
    with pytest.raises(CommitError, match="revealed already"):
        reveal_run(committed.run_dir, benchmark_id="fake-pool", reason="error", environ=env(tmp_path))
    with pytest.raises(CommitError, match="one of"):
        reveal_run(committed.run_dir, benchmark_id="fake-pool", reason="OSError: disk full", environ=env(tmp_path))


def test_a_run_owned_by_another_invocation_is_never_revealed(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    (committed.secret_path.parent / "2026-10-01.lock").write_text("", encoding="utf-8")         # another bench run holds it
    with pytest.raises(CommitError, match="already"):
        run_benchmark(bench, run=RUN, proof="https://example.org/i/1", environ=env(tmp_path))
    assert sorted(path.name for path in committed.run_dir.iterdir()) == ["COMMITMENT.json"]    # no REVEAL.json (R3-14)
    assert (committed.secret_path.parent / "2026-10-01.lock").exists()                         # and its lock stays


@pytest.mark.parametrize("case,message", [
    ("another secret", "does not hash"),
    ("no secret", "no run secret"),
    ("no placement note", "no placement note"),
    ("not pushed", "not in a pushed commit"),
    ("more than the commitment", "already running or finished"),
    ("never committed", "has no COMMITMENT.json"),
])
def test_a_committed_run_that_cannot_start_is_neither_played_nor_revealed(
    repo: Path, tmp_path: Path, case: str, message: str
) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    run = RUN
    if case == "another secret":
        committed.secret_path.write_bytes(RunSecret.generate().hex().encode("ascii") + b"\n")
    elif case == "no secret":
        committed.secret_path.unlink()
    elif case == "no placement note":
        committed.secret_path.with_name(f"{RUN}.placement.txt").unlink()
    elif case == "not pushed":
        _drop_the_pushed_branch(repo, tmp_path)
    elif case == "more than the commitment":
        (committed.run_dir / "config.json").write_bytes(b"{}\n")
    else:
        run = "2026-10-09"
    before = _names(committed.run_dir)
    with pytest.raises(CommitError, match=message):
        run_benchmark(bench, run=run, proof=PROOF, environ=env(tmp_path))
    assert _names(committed.run_dir) == before and "REVEAL.json" not in before                # nothing played or revealed
    assert not list(committed.secret_path.parent.glob("*.lock"))                               # the lock is released


def test_the_run_holds_its_lock_while_it_plays_and_a_ctrl_c_reveals_it(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    lock = committed.secret_path.with_name(f"{RUN}.lock")
    seen = []

    def interrupted(config: Any, **kwargs: Any) -> None:
        seen.append(lock.is_file())
        with pytest.raises(CommitError, match="already running"):                               # a second invocation
            run_benchmark(bench, run=RUN, proof=PROOF, environ=env(tmp_path))
        raise KeyboardInterrupt  # before the runner's committed phase: no manifest

    monkeypatch.setattr(runner, "run_tournament", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_benchmark(bench, run=RUN, proof=PROOF, environ=env(tmp_path))
    assert seen == [True] and not lock.exists()
    assert json.loads((committed.run_dir / "REVEAL.json").read_text(encoding="utf-8"))["reason"] == "interrupted"
    assert validate_tournament_dir(committed.run_dir) == []


def _raises(error: BaseException, *, game: bool = False) -> Any:
    """A stand-in for ``runner.run_tournament`` that stops before any manifest, after one recorded game if ``game``."""
    def run_tournament(config: Any, *, output_dir: Path, **kwargs: Any) -> None:
        if game:
            (Path(output_dir) / "matches.jsonl").write_bytes(b'{"game_index":0}\n')
        raise error
    return run_tournament


@pytest.mark.parametrize("case,reason", [("preflight", "preflight"), ("error", "error"), ("after a game", "error")])
def test_a_committed_run_that_fails_before_its_manifest_is_revealed_with_a_category(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, reason: str
) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    environ, error = env(tmp_path), f"the engine failed at {tmp_path / 'private'}"
    if case == "preflight":  # the real preflight: the engine cannot start (spec 11.1)
        environ["FAKE_ENGINE"] = str(tmp_path / "private" / "no-such-engine.py")
        expected: type[BaseException] = runner.TournamentError
    elif case == "error":
        monkeypatch.setattr(runner, "run_tournament", _raises(RuntimeError(error)))
        expected = RuntimeError
    else:
        monkeypatch.setattr(runner, "run_tournament", _raises(runner.TournamentError(error), game=True))
        expected = runner.TournamentError
    with pytest.raises(expected):
        run_benchmark(bench, run=RUN, proof=PROOF, environ=environ)
    data = (committed.run_dir / "REVEAL.json").read_bytes()
    record = json.loads(data)
    assert sorted(record) == sorted(REVEAL_KEYS) and record["reason"] == reason                 # a category (R3-28)
    assert b"private" not in data and str(tmp_path).encode() not in data                       # never exception text
    assert not committed.secret_path.with_name(f"{RUN}.lock").exists()
    assert check_reveal(committed.run_dir) == ([] if case != "after a game" else
                                               ["unexpected file in the run directory: matches.jsonl"])


def test_a_pushed_commitment_whose_secret_cannot_be_kept_is_revealed_at_once(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_new = bench_commit._write_new

    def failing(path: Path, text: str) -> None:
        if path.suffix == bench_commit.SECRET_SUFFIX:
            raise PermissionError(13, "Permission denied", str(path))
        write_new(path, text)

    monkeypatch.setattr(bench_commit, "_write_new", failing)
    bench = repo / "benchmarks" / "fake-pool"
    with pytest.raises(CommitError, match="revealed"):
        commit_run(bench, date=RUN, placement=PLACEMENT, environ=env(tmp_path))
    run_dir = bench / "runs" / RUN
    assert git(repo, "branch", "-r", "--contains", "HEAD")                                     # the commitment is public
    assert not list((tmp_path / "secrets").rglob("*.hex")) and validate_tournament_dir(run_dir) == []
    assert json.loads((run_dir / "REVEAL.json").read_text(encoding="utf-8"))["reason"] == "error"


def _revealed(directory: Path, **changes: Any) -> Path:
    """A revealed run's directory, its ``REVEAL.json`` with ``changes``."""
    secret = RunSecret(bytes(range(32)))
    directory.mkdir(parents=True)
    store.write_json_atomic(directory / "COMMITMENT.json",
                            commitment_record(run_secret=secret, benchmark_id="fake-pool", run_label=RUN))
    record = {"schema": REVEAL_SCHEMA, "benchmark_id": "fake-pool", "run_label": RUN, "commitment": secret.commitment(),
              "run_secret": secret.hex(), "status": "aborted", "reason": "error", **changes}
    store.write_json_atomic(directory / "REVEAL.json", record)
    return directory


@pytest.mark.parametrize("changes,failure", [
    ({"run_secret": "11" * 32}, "does not hash to its commitment"),
    ({"run_secret": "11" * 32, "commitment": RunSecret(bytes([17]) * 32).commitment()}, "not the SHA-256"),
    ({"benchmark_id": "other"}, "made for another run"),
    ({"run_label": "2026-10-02"}, "made for another run"),
    ({"reason": "OSError: /home/someone/secrets"}, "reason must be one of"),
    ({"reason": None}, "reason must be one of"),
    ({"status": "complete"}, "status must be"),
    ({"schema": "spellbench-run-reveal/v0"}, "schema must be"),
    ({"detail": "Traceback"}, "fields mismatch"),
    ({"run_secret": "not hex"}, "run_secret is not"),
    ({"commitment": "abc"}, "commitment is not 64"),
    ({"benchmark_id": None}, "benchmark_id must be"),
])
def test_check_reveal_holds_a_reveal_to_its_commitment(tmp_path: Path, changes: dict[str, Any], failure: str) -> None:
    assert validate_tournament_dir(_revealed(tmp_path / "good")) == []
    failures = validate_tournament_dir(_revealed(tmp_path / "bad", **changes))
    assert any(failure in line for line in failures), failures


def test_check_reveal_checks_the_published_files(tmp_path: Path) -> None:
    missing = _revealed(tmp_path / "missing")
    (missing / "COMMITMENT.json").unlink()
    extra = _revealed(tmp_path / "extra")
    (extra / "matches.jsonl").write_bytes(b"")
    loose = _revealed(tmp_path / "loose")
    (loose / "REVEAL.json").write_bytes(json.dumps(json.loads((loose / "REVEAL.json").read_bytes()), indent=1).encode())
    crlf = _revealed(tmp_path / "crlf")
    (crlf / "REVEAL.json").write_bytes((crlf / "REVEAL.json").read_bytes().replace(b"\n", b"\r\n"))
    local = _revealed(tmp_path / "local")
    (local / "diagnostics.jsonl").write_bytes(b"{}\n")
    assert "missing file: COMMITMENT.json" in check_reveal(missing)
    assert "unexpected file in the run directory: matches.jsonl" in check_reveal(extra)
    assert "REVEAL.json is not canonical JSON (spec 4.3)" in check_reveal(loose)
    assert any("CR LF" in line for line in check_reveal(crlf))
    assert check_reveal(local) == []                                                           # local, unhashed files
    published = _revealed(tmp_path / "published")
    (published / "manifest.json").write_bytes(b"{}\n")                                         # a manifest: not a reveal
    assert validate_tournament_dir(published) != []


def test_a_rerun_catches_a_changed_result(repo: Path, tmp_path: Path) -> None:
    result = run_benchmark(repo / "benchmarks" / "fake-pool", unrated=True, date=RUN, environ=env(tmp_path))
    ledger = result.run_dir / "matches.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    rows[0]["game_digest"] = "sha256:" + "0" * 64
    rows[1]["outcome"] = "p1_win" if rows[1]["outcome"] == "p0_win" else "p0_win"
    rows[2]["reason"] = "a changed reason"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    mismatches = rerun_games(result.run_dir, games=[0, 1, 2, 3], environ=env(tmp_path))
    assert [line.split(" ")[:2] for line in mismatches] == [["game", "0"], ["game", "1"], ["game", "2"]]
    assert "game_digest" in mismatches[0] and "outcome" in mismatches[1] and "reason" in mismatches[2]
    with pytest.raises(ValueError, match="not a game of the ledger"):
        rerun_games(result.run_dir, games=[len(rows)], environ=env(tmp_path))


def test_the_cli_commits_runs_reveals_and_reruns(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in env(tmp_path).items():
        monkeypatch.setenv(name, value)
    bench = repo / "benchmarks" / "fake-pool"
    assert cli.main(["bench", "commit", str(bench), "--placement", PLACEMENT, "--date", RUN]) == 0
    out, err = capsys.readouterr()
    secret = (tmp_path / "secrets" / "fake-pool" / f"{RUN}.hex").read_text(encoding="ascii").strip()
    assert f"commit {git(repo, 'rev-parse', 'HEAD')}" in out and "third-party timestamp" in out
    assert secret not in out + err                                                             # never printed before its reveal
    assert cli.main(["bench", "run", str(bench), "--run", RUN, "--proof", PROOF]) == 0
    assert "validate: OK" in capsys.readouterr().out
    assert cli.main(["bench", "rerun", str(bench / "runs" / RUN), "--game", "0", "--game", "3"]) == 0
    assert "every replayed game matches" in capsys.readouterr().out
    assert cli.main(["bench", "commit", str(bench), "--placement", PLACEMENT, "--date", RUN]) == 0
    second = "2026-10-01-2"
    lock = tmp_path / "secrets" / "fake-pool" / f"{second}.lock"
    lock.write_text("", encoding="utf-8")                                                       # a bench run owns it
    assert cli.main(["bench", "reveal", str(bench), "--run", second]) == 1
    assert "already running" in capsys.readouterr().err and not (bench / "runs" / second / "REVEAL.json").exists()
    lock.unlink()                                                                               # the operator found no live run
    assert cli.main(["bench", "reveal", str(bench), "--run", second]) == 0
    assert "validate: OK" in capsys.readouterr().out
    assert json.loads((bench / "runs" / second / "REVEAL.json").read_text(encoding="utf-8"))["reason"] == "interrupted"
    assert cli.main(["bench", "reveal", str(bench), "--run", second]) == 1                     # revealed once
    assert "error:" in capsys.readouterr().err
