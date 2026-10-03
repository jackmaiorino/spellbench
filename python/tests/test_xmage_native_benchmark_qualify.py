"""The native preparation must qualify the same inputs as the benchmark launch."""
import sys
from pathlib import Path

import pytest

from spellbench.arena import runner
from spellbench.arena.config import TournamentConfig
from spellbench.bench import definition
from spellbench.bench.run import EVIDENCE_NAME, plan_for, run_files
sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_native_benchmark_qualify import qualify, sha

from arena_helpers import roomy_machine
from test_bench_commit import PLACEMENT
from test_bench_run import ENVIRON, _write_benchmark


def test_native_preparation_evidence_is_reusable_by_the_actual_launch(tmp_path, monkeypatch):
    roomy_machine(monkeypatch)
    directory = _write_benchmark(tmp_path)
    out = tmp_path / "native-qualification"
    report = qualify(directory, benchmark_sha256=sha(directory / "benchmark.json"), out=out,
                     placement=PLACEMENT, environ=ENVIRON)
    assert report["trial_ledgers"] and report["rated_games"] == 0
    assert not (directory / "runs").exists()
    benchmark = definition.load_benchmark(directory)
    recorded = TournamentConfig.from_json(benchmark.tournament_config("runs/2026-10-03"))
    values = definition.placeholder_values(definition.placeholder_names(benchmark), {}, ENVIRON)
    executed = runner.executed_config(recorded, lambda text: definition.substitute(text, values))
    actual = plan_for(executed, placement=PLACEMENT, evidence=directory / EVIDENCE_NAME,
                      volumes={"run_dir": directory}, files=run_files(executed), environ=ENVIRON,
                      rules=benchmark.qualification_rules())
    assert actual.reused and actual.workload == report["allocation"]["workload"]
    repeated = qualify(directory, benchmark_sha256=sha(directory / "benchmark.json"),
                       out=tmp_path / "native-qualification-repeat", placement=PLACEMENT, environ=ENVIRON)
    assert repeated["reused"] and repeated["trial_ledgers"] == report["trial_ledgers"]
    # Cached throughput alone cannot certify natural native play after its
    # corresponding raw output rows are missing.
    Path(report["trial_ledgers"][0]["path"]).unlink()
    with pytest.raises(ValueError, match="missing matching retained"):
        qualify(directory, benchmark_sha256=sha(directory / "benchmark.json"),
                out=tmp_path / "native-qualification-missing", placement=PLACEMENT, environ=ENVIRON)


def test_changed_native_definition_is_refused_before_preparation(tmp_path):
    directory = _write_benchmark(tmp_path)
    out = tmp_path / "native-qualification"
    with pytest.raises(ValueError, match="definition differs"):
        qualify(directory, benchmark_sha256="0" * 64, out=out, placement=PLACEMENT, environ=ENVIRON)
    assert not out.exists() and not (directory / ".qualification-records").exists()
