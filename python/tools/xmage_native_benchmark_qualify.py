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
import re
from pathlib import Path
from typing import Mapping

from spellbench.arena import runner, store
from spellbench.arena.throughput import Placement
from spellbench.bench import definition
from spellbench.bench.run import EVIDENCE_NAME, plan_for, run_files


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def trial_ledgers(records: Path, allocation) -> list[dict]:
    # Reused generic evidence may contain forfeits or halts. Bind retained rows
    # to this allocation's exact measured digests before certifying natural play.
    expected = {(trial.workers, trial.indices, trial.outputs_digest): trial
                for trial in (allocation.probe, *allocation.trials) if trial is not None}
    found = {}
    for ledger in sorted(records.glob("qualification-*/trial-*.jsonl")):
        match = re.fullmatch(r"trial-\d+-workers-(\d+)\.jsonl", ledger.name)
        if match is None:
            continue
        try:
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        except json.JSONDecodeError:
            continue  # An interrupted trial cannot certify the measured one.
        by_index = {row["game_index"]: row for row in rows}
        if len(by_index) != len(rows):
            continue
        for key, trial in expected.items():
            if int(match.group(1)) != trial.workers or set(by_index) != set(trial.indices):
                continue
            ordered = [by_index[index] for index in trial.indices]
            digests = ["sha256:" + hashlib.sha256(store.canonical_bytes(row)).hexdigest() for row in ordered]
            combined = "sha256:" + hashlib.sha256("".join(digest + "\n" for digest in digests).encode("ascii")).hexdigest()
            if combined != trial.outputs_digest:
                continue
            if any(row["classification"] != "natural" for row in ordered):
                raise ValueError("native qualification includes a non-natural trial")
            found[key] = {"path": str(ledger), "sha256": sha(ledger), "natural_games": len(rows)}
    if set(found) != set(expected) or not found:
        raise ValueError("native qualification is missing matching retained trial ledgers")
    return list(found.values())


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
    allocation = plan_for(executed, placement=placement, evidence=benchmark_dir / EVIDENCE_NAME,
                          volumes={"run_dir": benchmark_dir}, files=files, environ=environ,
                          rules=benchmark.qualification_rules())
    trials = trial_ledgers(records, allocation)
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
