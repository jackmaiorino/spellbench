"""The rated wrapper delegates commitment/throughput checks and refuses false completion."""
import hashlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_native_benchmark_rated as rated


def fixture(tmp_path, monkeypatch):
    benchmark = tmp_path / "fdn-mirror-v0"
    benchmark.mkdir()
    original = Path(__file__).parents[2] / "benchmarks/fdn-mirror-v0/benchmark.json"
    shutil.copyfile(original, benchmark / "benchmark.json")
    output = benchmark / "runs/2026-10-05"
    output.mkdir(parents=True)
    (output / "manifest.json").write_bytes(b"published manifest\n")
    (output / "matches.jsonl").write_bytes(b"published primary ledger\n")
    calls = []
    monkeypatch.setattr(rated, "require_guard", lambda path, work_id: calls.append((path, work_id)))
    summary = SimpleNamespace(status="complete", rated=True, games_total=384,
                              games_rated=382, games_halted=0, games_truncated=2, games_forfeit=1)
    result = SimpleNamespace(run_dir=output, summary=summary, failures=())
    def run(directory, **arguments):
        calls.append((directory, arguments))
        return result
    monkeypatch.setattr(rated, "run_benchmark", run)
    arguments = {"benchmark_sha256": rated.sha(benchmark / "benchmark.json"), "run": "2026-10-05",
                 "proof": "GitHub public commitment timestamp", "out": output,
                 "host_guard": tmp_path / "host_reservation_v1.py", "host_work_id": "owned-rated-job"}
    return benchmark, arguments, result, calls


def test_calls_committed_runner_after_guard_and_reports_actual_counts(tmp_path, monkeypatch):
    benchmark, arguments, result, calls = fixture(tmp_path, monkeypatch)
    report = rated.play(benchmark, **arguments)
    assert calls == [(arguments["host_guard"], arguments["host_work_id"]),
                     (benchmark, {"run": "2026-10-05", "proof": arguments["proof"]})]
    assert report["scheduled_games"] == report["completed_games"] == 384
    assert report["rated_games"] == 382 and report["truncated_games"] == 2 and report["forfeit_games"] == 1
    assert report["ledger_sha256"] == hashlib.sha256(b"published primary ledger\n").hexdigest()


@pytest.mark.parametrize("changes", [
    {"benchmark_sha256": "0" * 64}, {"out": Path("other-run")},
    {"run": "../other"}, {"proof": ""},
])
def test_wrong_frozen_identity_refuses_before_host_or_runner(tmp_path, monkeypatch, changes):
    benchmark, arguments, _, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        rated.play(benchmark, **{**arguments, **changes})
    assert calls == []


@pytest.mark.parametrize("changes", [
    {"status": "aborted"}, {"rated": False}, {"games_total": 383},
])
def test_partial_or_unrated_result_is_not_reported_as_completion(tmp_path, monkeypatch, changes):
    benchmark, arguments, result, _ = fixture(tmp_path, monkeypatch)
    for name, value in changes.items():
        setattr(result.summary, name, value)
    with pytest.raises(ValueError, match="did not complete"):
        rated.play(benchmark, **arguments)


def test_actual_validator_failure_prevents_success_receipt(tmp_path, monkeypatch):
    benchmark, arguments, result, _ = fixture(tmp_path, monkeypatch)
    result.failures = ("matches.jsonl has an invalid decision count",)
    with pytest.raises(ValueError, match="validation failed"):
        rated.play(benchmark, **arguments)


def test_missing_guard_never_calls_committed_runner(tmp_path, monkeypatch):
    benchmark, arguments, _, calls = fixture(tmp_path, monkeypatch)
    def refuse(*args):
        raise ValueError("outside owned job")
    monkeypatch.setattr(rated, "require_guard", refuse)
    with pytest.raises(ValueError, match="outside owned job"):
        rated.play(benchmark, **arguments)
    assert calls == []


def test_production_entrypoint_rejects_test_reservation_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MTG_HOST_RESERVATION_TEST_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="production Windows containment"):
        rated.require_guard(tmp_path / "host_reservation_v1.py", "test-job")


@pytest.mark.parametrize("failure", [None, "no-token", "foreign-work", "outside-job", "test-root", "released"])
def test_requires_this_contained_process_and_active_production_claim(tmp_path, monkeypatch, failure):
    path = tmp_path / "host_reservation_v1.py"
    path.write_bytes(b"pinned trusted helper fixture\n")
    monkeypatch.setattr(rated, "HOST_GUARD_SHA256", rated.sha(path))
    environment = {"TOKEN": "owned"}
    state = {"state": "held", "token_fate": "holds", "test_root": False,
             "record": {"lane": "spellbench-xmage-native", "work_id": "owned-job"}}
    members = [1234]
    if failure == "no-token":
        environment.clear()
    elif failure == "foreign-work":
        state["record"]["work_id"] = "another-job"
    elif failure == "outside-job":
        members.clear()
    elif failure == "test-root":
        state["test_root"] = True
    elif failure == "released":
        state["token_fate"] = "released"
    helper = SimpleNamespace(CANONICAL_ROOT="C:/mtg-node/host-lock", SCHEMA="mtg-host-reservation/v1",
                             TOKEN_ENV="TOKEN", status=lambda token: state, job_members=lambda job: members)
    loader = SimpleNamespace(exec_module=lambda module: None)
    monkeypatch.setattr(rated, "importlib", SimpleNamespace(util=SimpleNamespace(
        spec_from_file_location=lambda *args: SimpleNamespace(loader=loader), module_from_spec=lambda spec: helper)))
    monkeypatch.setattr(rated, "os", SimpleNamespace(name="nt", environ=environment, getpid=lambda: 1234))
    if failure is None:
        rated.require_guard(path, "owned-job")
    else:
        with pytest.raises(ValueError, match="outside its declared owned native job"):
            rated.require_guard(path, "owned-job")
