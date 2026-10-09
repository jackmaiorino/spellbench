"""Measure the actual native benchmark through its existing launch guard.

This prepares reusable throughput evidence without a rated commitment or run.
The Windows reservation launcher supplies containment and the storage/window
limits. Native kit jars and engine inputs must be pinned by that manifest.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
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


def clock_repeat_receipt(allocation, trials: list[dict]) -> dict:
    """Bind the generic guard's clock disposition to its retained full serial replay."""
    if allocation.outputs_identical is not False or not allocation.outputs_note:
        raise ValueError("clock-sensitive qualification lacks the generic guard's variability disposition")
    paths = [Path(row["path"]) for row in trials]
    if len({path.parent for path in paths}) != 1:
        raise ValueError("clock-sensitive trials lack one coherent retained measurement")
    def rows(path):
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        by_index = {row["game_index"]: row for row in values}
        if len(by_index) != len(values) or any(row["classification"] != "natural" for row in values):
            raise ValueError("clock-sensitive serial replay is incomplete or non-natural")
        return by_index
    first_path = next(path for path in paths if path.name.endswith("-workers-1.jsonl"))
    first = rows(first_path)
    changed = set()
    for path in paths:
        compared = rows(path)
        if set(compared) != set(first):
            raise ValueError("clock-sensitive trials played different game indices")
        changed.update(index for index in first if compared[index] != first[index])
    if not changed:
        raise ValueError("clock-sensitive disposition has no differing measured outputs")
    for path in sorted(first_path.parent.glob("trial-*-workers-1.jsonl"), reverse=True):
        if path in paths:
            continue
        repeated = rows(path)
        if set(repeated) == set(first) and all(repeated[index] != first[index] for index in changed):
            return {"path": str(path), "sha256": sha(path), "natural_games": len(repeated),
                    "cross_worker_changed_indices": sorted(changed),
                    "disposition": "every changed game also changed on a complete serial policy replay"}
    raise ValueError("clock-sensitive qualification lacks the generic guard's complete varying serial replay")


def qualify(benchmark_dir: Path, *, benchmark_sha256: str, out: Path,
            placement: str, environ: Mapping[str, str] | None = None,
            diagnostic_sample: tuple[int, ...] = (), diagnostic_games_per_worker: int | None = None,
            clock_sensitive: bool = False) -> dict:
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
    rules = benchmark.qualification_rules()
    sample = benchmark.qualification_sample
    diagnostic = bool(diagnostic_sample)
    if diagnostic != (diagnostic_games_per_worker is not None):
        raise ValueError("diagnostic sampling requires both indices and games per worker")
    if diagnostic:
        if not 1 <= diagnostic_games_per_worker <= 8 or len(diagnostic_sample) > 64:
            raise ValueError("native diagnostic sampling exceeds its bounded envelope")
        rules = replace(rules, games_per_worker=diagnostic_games_per_worker)
        sample = diagnostic_sample
    out.mkdir(parents=True, exist_ok=False)
    records = benchmark_dir / ".qualification-records"
    evidence = benchmark_dir / ("diagnostic-" + EVIDENCE_NAME if diagnostic else EVIDENCE_NAME)
    allocation = plan_for(executed, placement=placement, evidence=evidence,
                          volumes={"run_dir": benchmark_dir}, files=files, environ=environ,
                          rules=rules, sample=sample)
    if allocation.kind == "substantial" and allocation.outputs_identical is not True and not clock_sensitive:
        raise ValueError("native qualification outputs differ across worker counts")
    trials = trial_ledgers(records, allocation)
    clock_repeat = (clock_repeat_receipt(allocation, trials) if allocation.kind == "substantial"
                    and allocation.outputs_identical is not True else None)
    report = {"schema": "spellbench-native-benchmark-qualification/v1", "benchmark": benchmark.id,
              "benchmark_sha256": benchmark_sha256, "allocation": allocation.to_json(),
              "trial_ledgers": trials, "reused": allocation.reused,
              "files": [file.to_json() for file in files], "rated_games": 0,
              "diagnostic_only": diagnostic, "preferred_sample": list(sample),
              "clock_sensitive_opt_in": clock_sensitive, "clock_sensitive_serial_replay": clock_repeat,
              "scope": ("placement diagnostic only; separate evidence cannot qualify the frozen rated launch"
                        if diagnostic else "throughput and natural completion only; ratings and publication remain pending")}
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
    parser.add_argument("--clock-sensitive", action="store_true",
                        help="Accept only generic-guard-certified full serial policy variability; engine replay remains separate")
    parser.add_argument("--diagnostic-index", type=int, action="append", default=[],
                        help="Prefer this scheduled game in a separate placement diagnostic")
    parser.add_argument("--diagnostic-games-per-worker", type=int,
                        help="Bounded diagnostic sample size per top-rung worker (1 to 8)")
    args = parser.parse_args()
    report = qualify(args.benchmark, benchmark_sha256=args.benchmark_sha256, out=args.out,
                     placement=args.placement, diagnostic_sample=tuple(args.diagnostic_index),
                          diagnostic_games_per_worker=args.diagnostic_games_per_worker,
                          clock_sensitive=args.clock_sensitive)
    print(json.dumps({"benchmark": report["benchmark"], "allocation": report["allocation"],
                      "trial_ledgers": report["trial_ledgers"], "rated_games": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
