"""Measure the actual native benchmark through its existing launch guard.

This prepares reusable throughput evidence without a rated commitment or run.
The Windows reservation launcher supplies containment and the storage/window
limits. Native kit jars and engine inputs must be pinned by that manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from spellbench.arena import runner
from spellbench.arena.throughput import Placement
from spellbench.bench import definition
from spellbench.bench.run import EVIDENCE_NAME, plan_for, run_files


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def qualify(benchmark_dir: Path, *, benchmark_sha256: str, out: Path,
            placement: str, environ: Mapping[str, str] | None = None) -> dict:
    benchmark_dir = benchmark_dir.resolve()
    benchmark_file = benchmark_dir / "benchmark.json"
    if sha(benchmark_file) != benchmark_sha256:
        raise ValueError("native benchmark definition differs")
    Placement.parse(placement)
    benchmark = definition.load_benchmark(benchmark_dir)
    environ = os.environ if environ is None else environ
    values = definition.placeholder_values(definition.placeholder_names(benchmark),
                                           definition.load_local_values(benchmark_dir.parent), environ)
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(str(out)))
    executed = runner.executed_config(config, lambda text: definition.substitute(text, values))
    files = run_files(executed)
    out.mkdir(parents=True, exist_ok=False)
    records = benchmark_dir / ".qualification-records"
    before = set(records.glob("qualification-*")) if records.exists() else set()
    allocation = plan_for(executed, placement=placement, evidence=benchmark_dir / EVIDENCE_NAME,
                          volumes={"run_dir": benchmark_dir}, files=files, environ=environ,
                          rules=benchmark.qualification_rules())
    trials = []
    for directory in sorted(set(records.glob("qualification-*")) - before):
        for ledger in sorted(directory.glob("trial-*.jsonl")):
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            if not rows or any(row["classification"] != "natural" for row in rows):
                raise ValueError("native qualification includes an empty or non-natural trial")
            trials.append({"path": str(ledger), "sha256": sha(ledger), "natural_games": len(rows)})
    report = {"schema": "spellbench-native-benchmark-qualification/v1", "benchmark": benchmark.id,
              "benchmark_sha256": benchmark_sha256, "allocation": allocation.to_json(),
              "trial_ledgers": trials, "reused": allocation.reused,
              "files": [file.to_json() for file in files], "rated_games": 0,
              "scope": "throughput and natural completion only; ratings and publication remain pending"}
    with (out / "QUALIFICATION.json").open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--benchmark-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--placement", required=True)
    args = parser.parse_args()
    report = qualify(args.benchmark, benchmark_sha256=args.benchmark_sha256, out=args.out,
                     placement=args.placement)
    print(json.dumps({"benchmark": report["benchmark"], "allocation": report["allocation"],
                      "trial_ledgers": report["trial_ledgers"], "rated_games": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
