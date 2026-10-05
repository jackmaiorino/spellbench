"""A transported qualification must not report old trial rows as new games."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import pytest
from types import SimpleNamespace

import xmage_native_qualified_job as job
from xmage_native_qualified_job import completed_since, execution_kind, progress_counts, sha


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
