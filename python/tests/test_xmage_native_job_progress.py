"""A transported qualification must not report old trial rows as new games."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_native_qualified_job import completed_since, progress_counts


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
