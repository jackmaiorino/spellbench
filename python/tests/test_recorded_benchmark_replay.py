"""A complete fake tournament must bind durable engine traffic to every published row."""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
import threading
import time
from dataclasses import replace

import pytest

from arena_helpers import builtin, make_config, TEST_RUN_SECRET, roomy_machine
from spellbench import wire
from spellbench.arena import engine_records, recorded_replay, runner, store
from spellbench.arena.config import TournamentConfig
from spellbench.arena.ledger import LedgerRow
from spellbench.arena.throughput import Allocation
from spellbench.bench import pinning


def tool(name):
    path = Path(__file__).parents[1] / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def complete(tmp_path):
    collector = tool("xmage_engine_record_collect")
    data = {"schema": "spellbench-engine-recording/v1", "root": str(tmp_path / "hot"),
            "cold_source": str(tmp_path / "cold"), "recovery": str(tmp_path / "recovery"),
            "per_game_cap_bytes": 2**20, "collection_timeout_seconds": 5,
            "transport": {"compression": "gzip"}}
    config = TournamentConfig.from_json(make_config(tmp_path / "run", [builtin("uniform"), builtin("heuristic")],
                                                   pairs=1, include_self_play=False))
    files = pinning.engine_files(config.engine_command)
    stop = threading.Event()
    failures = []
    def collect():
        seen = set()
        while not stop.wait(.01):
            for ready in Path(data["root"]).glob("*/READY.json"):
                if ready in seen:
                    continue
                try:
                    ack = collector.preserve(ready.parent, data)
                    engine_records.put(ready.parent / "COLLECTED.json", ack)
                    seen.add(ready)
                except BaseException as exc:
                    failures.append(exc)
                    return
    thread = threading.Thread(target=collect)
    thread.start()
    try:
        summary = runner.run_tournament(config, run_secret=TEST_RUN_SECRET,
                                        allocation=Allocation.unmeasured(1), engine_files=files, recording=data)
        assert summary.status == "complete"
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive() and not failures
    rows = [LedgerRow.from_json(row) for row in store.read_jsonl(tmp_path / "run" / store.LEDGER_NAME)]
    records = []
    for row in rows:
        directory, = [path for path in Path(data["cold_source"]).iterdir()
                      if json.loads((path / "ROW.json").read_bytes())["game_index"] == row.game_index]
        records.append({"game_index": row.game_index, "directory": str(directory),
                        "ready_sha256": engine_records.sha(directory / "READY.json"),
                        "row_sha256": engine_records.sha(directory / "ROW.json"),
                        "collected_sha256": engine_records.sha(directory / "COLLECTED.json")})
    plan = {"schema": "spellbench-recorded-benchmark-replay-plan/v1", "run_dir": str(tmp_path / "run"),
            "run_files_sha256": {name: engine_records.sha(tmp_path / "run" / name)
                                 for name in store.DATA_FILE_NAMES + (store.MANIFEST_NAME, store.COMMITMENT_NAME)},
            "records": records, "recording_identity": engine_records.identity(data), "values": {},
            "scheduled_games": len(rows), "max_workers": 2, "qualification_sample": [0, 1],
            "per_game_cap_bytes": 2**20, "job_storage_budget": {"projected_bytes": 2**22, "cap_bytes": 2**24},
            "placement": None}
    return plan, rows, config, tmp_path


def test_complete_published_tournament_replays_full_responses_without_policies(complete, monkeypatch):
    plan, rows, _, root = complete
    replay = tool("xmage_recorded_benchmark_replay")
    monkeypatch.setenv("SPELLBENCH_JOB_ROOT", str(root))
    roomy_machine(monkeypatch)
    monkeypatch.setattr(replay.JobStorageGuard, "check", lambda self: 0)
    guarded = []
    result = replay.replay(plan, root / "proof", guard=lambda: guarded.append(True))
    assert result["engine_replay_identical"] is True and result["policy_repeat_identical"] is None
    assert result["model_requests"] == 0 and result["scheduled_games"] == len(rows) == 2
    assert guarded and not list((root / "proof").glob("scratch/*/engine.jsonl"))
    proofs = list(store.read_jsonl(root / "proof" / result["proof_file"]))
    assert [proof["row_sha256"] for proof in proofs] == [record["row_sha256"] for record in plan["records"]]


@pytest.mark.parametrize("field", ["records", "run_files_sha256"])
def test_missing_schedule_record_or_changed_published_input_is_refused(complete, field):
    plan, _, _, root = complete
    replay = tool("xmage_recorded_benchmark_replay")
    if field == "records":
        plan[field].pop()
    else:
        (root / "run" / store.LEDGER_NAME).write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="every ledger row|input changed"):
        replay.load_inputs(plan)


def rewrite(record, filename, value):
    path = Path(record["directory"]) / filename
    path.write_bytes(wire.canonical_json_dumps(value))
    record[{"READY.json": "ready_sha256", "ROW.json": "row_sha256", "COLLECTED.json": "collected_sha256"}[filename]] = engine_records.sha(path)


@pytest.mark.parametrize("mutation", ["row", "ack", "compressed", "cap", "guard"])
def test_bad_custody_retains_durable_record_and_prevents_replay(complete, mutation):
    plan, rows, _, root = complete
    record = plan["records"][0]
    directory = Path(record["directory"])
    guard = None
    cap = 2**20
    if mutation == "row":
        row = json.loads((directory / "ROW.json").read_bytes())
        row["reason"] = "substituted"
        rewrite(record, "ROW.json", row)
    elif mutation == "ack":
        ack = json.loads((directory / "COLLECTED.json").read_bytes())
        ack["row_sha256"] = "0" * 64
        rewrite(record, "COLLECTED.json", ack)
    elif mutation == "compressed":
        with (directory / "engine.jsonl.gz").open("ab") as stream:
            stream.write(b"changed")
    elif mutation == "cap":
        cap = 1
    else:
        def guard():
            raise RuntimeError("STOP")
    with pytest.raises((ValueError, RuntimeError)):
        recorded_replay.materialize(record, rows[0], plan["recording_identity"], root / "scratch",
                                    cap_bytes=cap, guard=guard)
    assert (directory / "engine.jsonl.gz").is_file()


@pytest.mark.parametrize("mutation", ["secret", "answer", "terminal", "deck"])
def test_complete_trace_is_bound_to_revealed_game_and_ledger_digest(complete, mutation):
    plan, rows, _, root = complete
    directory = Path(plan["records"][0]["directory"])
    trace = [wire.strict_json_loads(line) for line in gzip.decompress((directory / "engine.jsonl.gz").read_bytes()).splitlines()]
    if mutation == "secret":
        trace[2]["message"]["game_secret"] = "0" * 64
    elif mutation == "answer":
        trace[3]["message"]["extra"] = "changed complete response"
    elif mutation == "terminal":
        trace[-1]["message"]["reason"] = "changed"
    else:
        trace[2]["message"]["seats"][0]["deck"]["deck_id"] = "sha256:" + "0" * 64
    path = root / "changed.jsonl"
    path.write_bytes(b"".join(wire.canonical_json_dumps(item) + b"\n" for item in trace))
    with pytest.raises(ValueError, match="recorded"):
        recorded_replay.check_exchanges(path, rows[0], TEST_RUN_SECRET)


def test_failed_complete_response_replay_retains_hot_attempt(complete, monkeypatch):
    plan, rows, config, root = complete
    monkeypatch.setattr(recorded_replay, "replay_engine_transcript", lambda *args, **kwargs: ["response differs"])
    with pytest.raises(ValueError, match="complete engine response"):
        recorded_replay.replay_record(plan["records"][0], rows[0], TEST_RUN_SECRET, plan["recording_identity"],
                                     config.engine_command, root / "failed", cap_bytes=2**20, timeout_s=1)
    assert (root / "failed" / "engine.jsonl").is_file()


def test_launch_uses_same_resolved_executable_as_published_file_pin(complete, monkeypatch):
    plan, _, config, _ = complete
    replay = tool("xmage_recorded_benchmark_replay")
    original = runner.executed_config
    monkeypatch.setattr(runner, "executed_config", lambda *args:
                        replace(original(*args), engine_command=("bare-python", *config.engine_command[1:])))
    resolve = pinning.resolve_command
    resolved = []
    def fixed(command):
        if command[0] == "bare-python":
            command = (config.engine_command[0], *command[1:])
        result = resolve(command)
        resolved.append(result)
        return result
    monkeypatch.setattr(pinning, "resolve_command", fixed)
    _, _, _, executed, files = replay.load_inputs(plan)
    assert resolved and executed.engine_command == resolved[0]
    assert str(files[0].path) == executed.engine_command[0]


def test_refusal_after_pool_shutdown_does_not_publish_qualification(complete, monkeypatch):
    plan, _, _, root = complete
    replay = tool("xmage_recorded_benchmark_replay")
    monkeypatch.setenv("SPELLBENCH_JOB_ROOT", str(root))
    roomy_machine(monkeypatch)
    monkeypatch.setattr(replay.JobStorageGuard, "check", lambda self: 0)
    real_execute = replay.execute
    stopped = []
    def execute(*args, **kwargs):
        result = real_execute(*args, **kwargs)
        stopped.append(True)
        return result
    def guard():
        if stopped:
            raise RuntimeError("STOP during pool shutdown")
    monkeypatch.setattr(replay, "execute", execute)
    with pytest.raises(RuntimeError, match="pool shutdown"):
        replay.replay(plan, root / "refused", guard=guard)
    assert not (root / "refused" / "ALLOCATION.json").exists()
    assert not (root / "refused" / "REPLAY.json").exists()
