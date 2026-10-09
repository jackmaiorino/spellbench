"""A transported qualification must not report old trial rows as new games."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import pytest
from types import SimpleNamespace

import xmage_native_qualified_job as job
from xmage_native_qualified_job import completed_since, execution_kind, progress_counts, sha


def owned_receipt(root, digit):
    name = "spellbench-xmage-" + digit * 32
    path = root / (name + ".owned.json")
    path.write_text(json.dumps({"schema": "spellbench-owned-model-container/v1", "container": name,
                               "creator_pid": 42, "work_directory": str(root / "agent-private")}))
    return name, path


def test_abort_cleanup_removes_only_new_recorded_containers(tmp_path):
    root = tmp_path / "agent-work"
    root.mkdir()
    old_name, old = owned_receipt(root, "a")
    baseline = job.container_records((root,))
    new_name, new = owned_receipt(root, "b")
    calls = []
    def docker(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="")
    result = job.cleanup_containers((root,), baseline, environ={}, run=docker)
    assert calls == [["docker", "rm", "--force", new_name]]
    assert result[0]["confirmed_absent"] is True
    assert result[0]["receipt_sha256"] == sha(new)
    assert old.exists() and new.exists()  # Audit receipts survive cleanup.
    assert old_name not in calls[0]


@pytest.mark.parametrize("change", ["name", "directory", "schema"])
def test_cleanup_rejects_foreign_or_malformed_receipt(tmp_path, change):
    _, path = owned_receipt(tmp_path, "a")
    data = json.loads(path.read_bytes())
    data[{"name": "container", "directory": "work_directory", "schema": "schema"}[change]] = (
        str(tmp_path.parent / "foreign") if change == "directory" else "foreign")
    path.write_text(json.dumps(data))
    result = job.cleanup_containers((tmp_path,), {}, environ={}, run=lambda *a, **k: pytest.fail("foreign Docker call"))
    assert result[0]["confirmed_absent"] is False
    assert "invalid owned" in result[0]["error"]


def test_cleanup_preserves_docker_failure_and_refuses_changed_history(tmp_path):
    _, path = owned_receipt(tmp_path, "a")
    result = job.cleanup_containers((tmp_path,), {}, environ={}, run=lambda *a, **k:
        SimpleNamespace(returncode=1, stderr="daemon unavailable"))
    assert result[0]["confirmed_absent"] is False
    baseline = job.container_records((tmp_path,))
    path.write_text(path.read_text() + " ")
    result = job.cleanup_containers((tmp_path,), baseline, environ={}, run=lambda *a, **k: pytest.fail("changed-history call"))
    assert result[0]["confirmed_absent"] is False
    assert "older owned container receipt changed" in result[0]["error"]


def test_container_work_roots_cannot_select_foreign_tree(tmp_path):
    record = {"hot_root": str(tmp_path / "owned"), "container_work_roots": [str(tmp_path / "foreign")]}
    with pytest.raises(ValueError, match="outside the owned hot root"):
        job.container_roots(record)


def test_cleanup_uses_workload_daemon_and_continues_after_bad_receipts(tmp_path, monkeypatch):
    _, old = owned_receipt(tmp_path, "a")
    baseline = job.container_records((tmp_path,))
    old.write_text(old.read_text() + " ")
    _, malformed = owned_receipt(tmp_path, "b")
    malformed.write_text("invalid json")
    good_name, good = owned_receipt(tmp_path, "c")
    monkeypatch.setenv("DOCKER_HOST", "controller-daemon")
    workload = {"DOCKER_HOST": "workload-daemon", "DOCKER_CONFIG": "workload-config", "PATH": "workload-bin"}
    calls = []
    def docker(command, **kwargs):
        assert kwargs["env"] == workload
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="")
    result = job.cleanup_containers((tmp_path,), baseline, environ=workload, run=docker)
    assert calls == [["docker", "rm", "--force", good_name]]
    assert sum(row["confirmed_absent"] is False for row in result) == 2
    assert [row for row in result if row["confirmed_absent"]][0]["receipt"] == str(good)


def test_benchmark_progress_excludes_retained_trials(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    retained = tmp_path / ".qualification-records/qualification-old/trial-1-workers-1.jsonl"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"{}\n" * 16)
    prepared = {"qualification_kind": "benchmark", "benchmark": {"path": str(benchmark)}}
    baseline = progress_counts(prepared, tmp_path / "out")
    assert completed_since(prepared, tmp_path / "out", baseline) == 0
    current = retained.parent.parent / "qualification-current/trial-1-workers-1.jsonl"
    current.parent.mkdir()
    current.write_bytes(b"{}\n" * 3)
    assert completed_since(prepared, tmp_path / "out", baseline) == 3
    with current.open("ab") as stream:
        stream.write(b"{}\n")
    assert completed_since(prepared, tmp_path / "out", baseline) == 4
    assert retained.read_bytes() == b"{}\n" * 16


def test_soak_progress_counts_only_new_rows(tmp_path):
    ledger = tmp_path / "completed-games.jsonl"
    ledger.write_bytes(b"{}\n" * 2)
    baseline = progress_counts({}, tmp_path)
    with ledger.open("ab") as stream:
        stream.write(b"{}\n")
    assert completed_since({}, tmp_path, baseline) == 1
    ledger.write_bytes(b"{}\n")
    assert completed_since({}, tmp_path, baseline) == 0


def test_no_ledgers_yet_reports_zero(tmp_path):
    assert progress_counts({}, tmp_path) == {}
    assert completed_since({}, tmp_path, {}) == 0


def test_rated_progress_uses_match_ledger_without_counting_qualification(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    retained = tmp_path / ".qualification-records/qualification-old/trial-1-workers-1.jsonl"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"{}\n" * 10)
    output = tmp_path / "runs/2026-10-05"
    output.mkdir(parents=True)
    prepared = {"execution_kind": "rated_benchmark", "qualification_kind": "benchmark",
                "benchmark": {"path": str(benchmark)}}
    baseline = progress_counts(prepared, output)
    assert baseline == {}
    ledger = output / "matches.jsonl"
    ledger.write_bytes(b"{}\n" * 3)
    assert completed_since(prepared, output, baseline) == 3


def test_rated_execution_requires_owned_entrypoint_and_honest_scope(tmp_path):
    entry = tmp_path / "xmage_native_benchmark_rated.py"
    entry.write_text("# pinned rated entrypoint\n", encoding="utf-8")
    record = {"execution_kind": "rated_benchmark", "qualification_only": False,
              "hot_root": str(tmp_path), "launcher_python": {"path": "python"}}
    prepared = {"execution_kind": "rated_benchmark", "qualification_kind": "benchmark",
                "execution_entrypoint": {"path": str(entry), "sha256": sha(entry)},
                "command": ["python", str(entry), "--out", "run"]}
    assert execution_kind(record, prepared) == "rated_benchmark"
    with pytest.raises(ValueError, match="qualification-only"):
        execution_kind({**record, "qualification_only": True}, prepared)
    with pytest.raises(ValueError, match="kinds differ"):
        execution_kind(record, {**prepared, "execution_kind": "qualification"})
    with pytest.raises(ValueError, match="does not launch"):
        execution_kind(record, {**prepared, "command": ["python", "other.py"]})
    with pytest.raises(ValueError, match="base Python"):
        execution_kind(record, {**prepared, "command": ["other-python", str(entry)]})
    entry.write_text("# mutated rated entrypoint\n", encoding="utf-8")
    with pytest.raises(ValueError, match="entrypoint differs"):
        execution_kind(record, prepared)


def test_existing_qualification_manifests_keep_their_execution_kind():
    assert execution_kind({}, {}) == "qualification"
    with pytest.raises(ValueError, match="unknown"):
        execution_kind({"execution_kind": "raw"}, {})
    with pytest.raises(ValueError, match="qualification-only scope"):
        execution_kind({"qualification_only": False}, {})


def test_storage_refuses_projected_cap_or_reserve_before_dispatch(tmp_path, monkeypatch):
    hot, cold = tmp_path / "hot", tmp_path / "cold"
    hot.mkdir(); cold.mkdir()
    (hot / "input").write_bytes(b"12345")
    (cold / "input").write_bytes(b"12345")
    record = {"hot_root": str(hot), "cold_root": str(cold), "projected_peak_physical_bytes": 16,
              "storage_cap_bytes": 15, "reserve_bytes": 100}
    with pytest.raises(RuntimeError, match="aggregate storage cap"):
        job.storage(record)
    record["storage_cap_bytes"] = 20
    monkeypatch.setattr(job.shutil, "disk_usage", lambda path: SimpleNamespace(free=105))
    with pytest.raises(RuntimeError, match="declared reserve"):
        job.storage(record)
    monkeypatch.setattr(job.shutil, "disk_usage", lambda path: SimpleNamespace(free=106))
    assert job.storage(record) == 10


def test_storage_scan_tolerates_worker_file_removed_after_listing(tmp_path, monkeypatch):
    transient = tmp_path / "cards.h2.trace.db"
    transient.write_bytes(b"temporary database trace")
    (tmp_path / "retained").write_bytes(b"12345")
    walk = job.os.walk

    def racing_walk(*args, **kwargs):
        for directory, dirs, files in walk(*args, **kwargs):
            if transient.name in files:
                transient.unlink()
            yield directory, dirs, files

    monkeypatch.setattr(job.os, "walk", racing_walk)
    assert job.tree_bytes(tmp_path) == 5
    assert not transient.exists()


def test_storage_scan_keeps_unreadable_file_failures(tmp_path, monkeypatch):
    blocked = tmp_path / "unreadable"
    blocked.write_bytes(b"cannot silently omit storage")
    stat = Path.stat

    def unreadable_stat(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("storage metadata unavailable")
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", unreadable_stat)
    with pytest.raises(PermissionError, match="storage metadata unavailable"):
        job.tree_bytes(tmp_path)


def test_busy_check_without_cores_counts_every_name_match():
    table = [(10, 1, "java.exe"), (11, 1, "mtg_kernel_tests.exe"), (12, 1, "python.exe")]
    assert job.busy_processes(table, None, affinity=lambda pid: {16}) == [(10, "java.exe"), (11, "mtg_kernel_tests.exe")]


def test_busy_check_with_cores_ignores_only_processes_pinned_elsewhere():
    table = [(10, 1, "java.exe"), (11, 1, "mtg_kernel_tests.exe"), (12, 1, "native_x.exe"), (13, 1, "bo3_y.exe")]
    affinity = {10: set(range(16, 24)), 11: {15, 16}, 12: None, 13: set(range(24))}.get
    cores = job.parse_cores("0-15")
    # pinned entirely to 16-23: ignored; overlapping, unreadable or unpinned: still busy
    assert job.busy_processes(table, cores, affinity=affinity) == [
        (11, "mtg_kernel_tests.exe"), (12, "native_x.exe"), (13, "bo3_y.exe")]


def test_declared_cores_wrap_the_child_in_timed():
    prepared = {"command": ["py", "rated.py", "--out", "o"]}
    assert job.run_command({}, prepared) == ["py", "rated.py", "--out", "o"]
    record = {"cores": "0-15", "host_slots": {"path": "C:/pins/host_slots_v1.py"}}
    assert job.run_command(record, prepared) == [sys.executable, "C:/pins/host_slots_v1.py", "timed", "--cores", "0-15",
                                                 "--", "py", "rated.py", "--out", "o"]
    assert job.declared_cores({}) is None
    assert job.parse_cores("3-1,8") == [3, 2, 1, 8]
    with pytest.raises(ValueError):
        job.parse_cores("0-x")
