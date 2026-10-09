"""Guarded, throughput-qualified replay of a complete published benchmark's operator engine records.

The final proof covers every ledger row and every engine response with recorded
selections. It calls no policies and leaves the normal fresh-policy replay intact.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from spellbench import wire
from spellbench.arena import engine_records, recorded_replay, runner, store
from spellbench.arena.config import TournamentConfig
from spellbench.arena.executor import execute
from spellbench.arena.job_storage import JobStorageGuard
from spellbench.arena.ledger import LedgerRow
from spellbench.arena.schedule import schedule
from spellbench.arena.throughput import PlayedGame, current_rules, plan_allocation, workload_id
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench import definition, pinning
from spellbench.run_secret import RunSecret
from xmage_native_benchmark_rated import require_guard


@dataclass(frozen=True)
class ReplayOutcome:
    row: LedgerRow
    proof: dict
    seconds: float
    scratch: str
    violation: None = None


def one(item, *, secret, recording, command, files, root, cap_bytes, timeout_s):
    started = time.perf_counter()
    pinning.verify_files(files)
    scratch = Path(root) / (f"game-{item[0].game_index}-" + uuid.uuid4().hex)
    proof = recorded_replay.replay_record(item[1], item[0], secret, recording, command, scratch,
                                         cap_bytes=cap_bytes, timeout_s=timeout_s)
    pinning.verify_files(files)
    return ReplayOutcome(item[0], proof, time.perf_counter() - started, str(scratch))


def load_inputs(plan):
    directory = engine_records.plain_path(Path(plan["run_dir"]).resolve())
    for name, expected in plan["run_files_sha256"].items():
        if name not in store.DATA_FILE_NAMES + (store.MANIFEST_NAME, store.COMMITMENT_NAME):
            raise ValueError("recorded replay plan names a noncanonical run file")
        recorded_replay._checked(directory / name, expected)
    if set(plan["run_files_sha256"]) != set(store.DATA_FILE_NAMES + (store.MANIFEST_NAME, store.COMMITMENT_NAME)):
        raise ValueError("recorded replay plan must bind every canonical published run file")
    failures = validate_tournament_dir(directory)
    if failures:
        raise ValueError("published run is invalid: " + "; ".join(failures))
    manifest = store.read_json(directory / store.MANIFEST_NAME)
    config = TournamentConfig.from_json(store.read_json(directory / store.CONFIG_NAME))
    secret = RunSecret.from_hex(manifest["secrets"]["run_secret"])
    contexts = schedule(config, secret)
    rows = [LedgerRow.from_json(value) for value in store.read_jsonl(directory / store.LEDGER_NAME)]
    if (len(rows) != len(contexts) or len(rows) != plan["scheduled_games"]
            or [row.game_index for row in rows] != list(range(len(contexts)))):
        raise ValueError("recorded replay requires the entire declared schedule in ledger order")
    records = plan["records"]
    if len(records) != len(rows) or [item["game_index"] for item in records] != list(range(len(rows))):
        raise ValueError("recorded replay requires one hash-bound durable record for every ledger row")
    executed = runner.executed_config(config, lambda part: definition.substitute(part, plan["values"]))
    executed = replace(executed, engine_command=pinning.resolve_command(executed.engine_command))
    files = pinning.engine_files(executed.engine_command, extra=executed.evaluation_engine_inputs)
    if [file.to_json() for file in files] != manifest["engine_files"]:
        raise ValueError("recorded replay does not use the published engine files")
    for item in records:
        engine_records.plain_path(Path(item["directory"]).resolve())
    return rows, records, secret, executed, files


def replay(plan, out: Path, *, guard):
    if plan.get("schema") != "spellbench-recorded-benchmark-replay-plan/v1":
        raise ValueError("unknown recorded benchmark replay plan")
    if type(plan.get("max_workers")) is not int or plan["max_workers"] < 1:
        raise ValueError("recorded replay requires a positive declared worker bound")
    out = engine_records.plain_path(out.resolve())
    out.mkdir(parents=True, exist_ok=False)
    rows, records, secret, config, files = load_inputs(plan)
    storage = JobStorageGuard(plan["job_storage_budget"], environ=os.environ, paths=(out,))
    def check():
        guard()
        storage.check()
        pinning.verify_files(files)
    check()
    task = partial(one, secret=secret, recording=plan["recording_identity"], command=config.engine_command,
                   files=files, root=str(out / "scratch"), cap_bytes=plan["per_game_cap_bytes"],
                   timeout_s=max(config.time_control.startup_ms, config.time_control.engine_step_ms) / 1000)
    trial_number = 0
    def play(workers, positions):
        nonlocal trial_number
        trial_number += 1
        selected = [(rows[index], records[index]) for index in positions]
        played = []
        started = time.perf_counter()
        with (out / f"proofs-{trial_number}.jsonl").open("xb") as stream:
            def collect(outcome):
                stream.write(wire.canonical_json_dumps(outcome.proof) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
                check()
                played.append(PlayedGame(outcome.row.game_index, outcome.seconds, runner.row_digest(outcome.row),
                                         len(wire.canonical_json_dumps(outcome.proof)) + 1))
                # The immutable original remains in durable custody; this duplicate
                # is released only after its complete proof was fsynced.
                (Path(outcome.scratch) / "engine.jsonl").unlink()
            result = execute(selected, task, workers=workers, on_outcome=collect,
                             guard=check, submission_window=workers)
        if result.error:
            raise result.error
        if result.stopped is not None or len(played) != len(selected):
            raise ValueError("recorded replay stopped before the complete requested prefix")
        check()
        return time.perf_counter() - started, tuple(played)
    sample = list(plan["qualification_sample"])
    if (len(set(sample)) != len(sample) or any(type(index) is not int or not 0 <= index < len(rows) for index in sample)):
        raise ValueError("recorded replay sample must name distinct scheduled indices")
    order = sample + [index for index in range(len(rows)) if index not in sample]
    allocation = plan_allocation(games_total=len(rows), cap=plan["max_workers"], per_game_cores=1,
                                 play=play, placement=plan["placement"], sample=order,
                                 workload=workload_id({"plan": plan, "helper": engine_records.sha(__file__),
                                                       "recorded_replay": engine_records.sha(recorded_replay.__file__)}),
                                 volumes={"run_dir": out, "pin_root": out},
                                 rules=replace(current_rules(), worker_selection="wall"),
                                 cap_bytes=plan["job_storage_budget"]["cap_bytes"])
    if allocation.kind == "substantial" and allocation.outputs_identical is not True:
        raise ValueError("recorded engine replay must reproduce exact rows at every worker count")
    engine_records.put(out / "ALLOCATION.json", allocation.to_json())
    if plan.get("qualification_only") is True:
        return {"qualification_only": True, "allocation": allocation.to_json(), "model_requests": 0}
    elapsed, completed = play(allocation.workers, tuple(range(len(rows))))
    if len(completed) != len(rows):
        raise ValueError("recorded replay did not cover every published row")
    for name, expected in plan["run_files_sha256"].items():
        recorded_replay._checked(Path(plan["run_dir"]) / name, expected)
    check()
    result = {"schema": "spellbench-recorded-benchmark-replay/v1", "scheduled_games": len(rows),
              "engine_replay_identical": True, "policy_repeat_identical": None, "model_requests": 0,
              "ledger_sha256": plan["run_files_sha256"][store.LEDGER_NAME],
              "proof_file": f"proofs-{trial_number}.jsonl", "wall_seconds": elapsed,
              "allocation": allocation.to_json()}
    engine_records.put(out / "REPLAY.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host-guard", type=Path, required=True)
    parser.add_argument("--host-work-id", required=True)
    args = parser.parse_args()
    plan = json.loads(recorded_replay._checked(args.plan, args.plan_sha256))
    guard = partial(require_guard, args.host_guard, args.host_work_id)
    guard()
    print(json.dumps(replay(plan, args.out, guard=guard)))


if __name__ == "__main__":
    main()
