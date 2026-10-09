"""Operator evidence must survive until exact, supervised cold collection succeeds."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


def test_ready_publication_exposes_only_complete_fsynced_receipt(recording, monkeypatch):
    record, terminal, config = recording
    real_fsync, real_link = engine_records.os.fsync, engine_records.os.link
    observed = []
    def fsync(fd):
        assert not (record.directory / "READY.json").exists()
        real_fsync(fd)
    def link(source, target):
        if Path(target).name == "READY.json":
            payload = json.loads(Path(source).read_bytes())
            assert payload["row_sha256"] == digest((record.directory / "ROW.json").read_bytes())
            observed.append(payload)
        real_link(source, target)
    monkeypatch.setattr(engine_records.os, "fsync", fsync)
    monkeypatch.setattr(engine_records.os, "link", link)
    record.seal(terminal)
    assert observed and json.loads((record.directory / "READY.json").read_bytes()) == observed[0]


def test_transport_admission_precedes_any_scp(recording, monkeypatch, collector):
    record, _, config = recording
    config["transport"] = {"ssh_target": "host", "command_timeout_seconds": 1,
                           "copy_timeout_seconds": 1, "poll_seconds": 1}
    monkeypatch.setattr(collector, "powershell", lambda *args: json.dumps([record.directory.name]))
    def refuse(*args):
        raise ValueError("pre-transfer reserve")
    monkeypatch.setattr(collector, "check_storage", refuse)
    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: pytest.fail("SCP before admission"))
    with pytest.raises(ValueError, match="pre-transfer reserve"):
        collector.collect_remote(config, duration=1, stop=record.directory / "STOP")


def test_pipeline_identity_binds_transport_and_changed_source(recording, monkeypatch):
    _, _, config = recording
    from spellbench.arena.throughput import workload_id
    config["transport"] = {"compression": "gzip", "ssh_target": "host"}
    before = workload_id(engine_records.identity(config))
    config["transport"]["ssh_target"] = "different-host"
    assert workload_id(engine_records.identity(config)) != before
    config["source_sha256"] = engine_records.identity(config)["source_sha256"]
    engine_records.assert_current(config)
    original = engine_records.sha
    monkeypatch.setattr(engine_records, "sha", lambda path: "0"*64 if Path(path).name == "executor.py" else original(path))
    with pytest.raises(ValueError, match="source pins"):
        engine_records.assert_current(config)


def test_explicit_disabled_recording_does_not_read_global_environment(monkeypatch):
    from spellbench.arena import runner
    monkeypatch.setattr(engine_records, "settings", lambda *args: pytest.fail("global recording config was read"))
    seen = {}
    monkeypatch.setattr(runner, "execute", lambda *args, **kwargs: seen.update(kwargs))
    runner.play_games(None, None, [], run_secret=SimpleNamespace(hex=lambda: "00"*32),
                      entries={}, workers=2, recording=None)
    assert seen["submission_window"] is None


@pytest.mark.parametrize("recording_data", [None, {"enabled": True}])
def test_small_spot_check_uses_same_recording_and_supervised_collection(recording, recording_data, monkeypatch):
    from spellbench.arena import runner
    _, terminal, _ = recording
    events = []
    guard = lambda: None
    def play(*args, **kwargs):
        assert kwargs["recording"] is recording_data and kwargs["guard"] is guard
        kwargs["on_outcome"](SimpleNamespace(row=terminal, record_directory="same-route"))
        return SimpleNamespace(error=None, outcomes=[SimpleNamespace(row=terminal)])
    monkeypatch.setattr(runner, "play_games", play)
    monkeypatch.setattr(engine_records, "collect", lambda directory, row, **kwargs:
                        events.append((directory, row, kwargs["guard"])))
    class Allocation:
        def with_spot_check(self, *args, **kwargs):
            assert events == [("same-route", terminal, guard)]
            return "spot-proof"
    result = runner._spot_checked(Allocation(), 0, config=None, setup=None, context=None,
                                  row=terminal, run_secret=None, entries={}, recording=recording_data, guard=guard)
    assert result == ("spot-proof", None)


def test_production_runner_records_actual_parallel_engine_games_and_collects_in_order(tmp_path, collector):
    from spellbench.arena import runner
    from spellbench.arena.schedule import schedule, preflight
    from spellbench.arena.config import TournamentConfig
    from spellbench.conformance import replay_engine_transcript
    from arena_helpers import make_config, builtin, TEST_RUN_SECRET
    config = TournamentConfig.from_json(make_config(tmp_path / "run", [builtin("uniform"), builtin("heuristic")],
                                                   pairs=1, include_self_play=False))
    data = {"schema": "spellbench-engine-recording/v1", "root": str(tmp_path / "hot"),
            "cold_source": str(tmp_path / "cold"), "recovery": str(tmp_path / "recovery"),
            "per_game_cap_bytes": 2**20, "collection_timeout_seconds": 1,
            "transport": {"compression": "gzip"}}
    setup = preflight(config, TEST_RUN_SECRET)
    contexts = schedule(config, TEST_RUN_SECRET)
    entries = {entry.name: entry for entry in runner.registry_entries(config, config)}
    rows = []
    def collected(outcome):
        directory = Path(outcome.record_directory)
        ack = collector.preserve(directory, data)
        engine_records.put(directory / "COLLECTED.json", ack)
        engine_records.collect(directory, outcome.row)
        rows.append(outcome.row)
    result = runner.play_games(config, setup, contexts, run_secret=TEST_RUN_SECRET,
                               entries=entries, workers=2, timed=True, recording=data, on_outcome=collected)
    assert result.error is None and len(rows) == len(contexts) == 2
    assert [row.game_index for row in rows] == [0, 1]
    for outcome in result.outcomes:
        directory = Path(outcome.record_directory)
        assert not (directory / "engine.jsonl").exists()
        cold = Path(data["cold_source"]) / directory.name
        assert (cold / "ROW.json").read_bytes() == wire.canonical_json_dumps(outcome.row.to_json())
        transcript = tmp_path / f"replay-{outcome.row.game_index}.jsonl"
        transcript.write_bytes(gzip.decompress((cold / "engine.jsonl.gz").read_bytes()))
        assert replay_engine_transcript(config.engine_command, transcript) == []

from spellbench import wire
from spellbench.arena import engine_records, executor
from spellbench.arena.ledger import parse_ledger
from test_arena_executor import play_one
from test_ledger import row as ledger_row


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def recording(tmp_path):
    terminal, = parse_ledger([ledger_row(game_index=0)])
    config = {"schema": "spellbench-engine-recording/v1", "root": str(tmp_path / "hot"),
              "cold_source": str(tmp_path / "cold"), "recovery": str(tmp_path / "recovery"),
              "per_game_cap_bytes": 4096, "collection_timeout_seconds": 1}
    record = engine_records.EngineRecord(config, SimpleNamespace(game_index=terminal.game_index,
                                                               game_id=terminal.game_id))
    yield record, terminal, config
    record.close()


def acknowledge(directory):
    """Act as the external collector: copy and verify both destinations first."""
    ready_path = directory / "READY.json"
    ready = json.loads(ready_path.read_bytes())
    destinations = {}
    for key, root in (("cold_path", ready["cold_source"]), ("recovery_path", ready["recovery"])):
        target = Path(root) / directory.name
        target.mkdir(parents=True)
        for name in ("engine.jsonl", "ROW.json", "READY.json"):
            shutil.copyfile(directory / name, target / name)
            assert (target / name).read_bytes() == (directory / name).read_bytes()
        destinations[key] = str(target / "engine.jsonl")
    ack = {"schema": "spellbench-engine-record-collected/v1", "ready_sha256": digest(ready_path.read_bytes()),
           "transcript_sha256": ready["transcript_sha256"], "transcript_bytes": ready["transcript_bytes"],
           "row_sha256": ready["row_sha256"], "row_bytes": ready["row_bytes"],
           **destinations, "cold_verified": True, "recovery_verified": True}
    (directory / "COLLECTED.json").write_text(json.dumps(ack), encoding="utf-8")
    return ack


def sealed(recording):
    record, terminal, config = recording
    record.write("host_to_engine", b'{"op":"step","selection":{"candidate_id":17}}')
    record.write("engine_to_host", b'{"op":"terminal","winner":"A"}')
    return Path(record.seal(terminal)), terminal, config


def test_peer_preserves_complete_exchanges_and_enforces_byte_cap_before_forwarding(recording):
    record, terminal, config = recording
    request = b'{ "op":"step", "selection":{"candidate_id":17,"semantic_echo":{"text":"all fields"}} }'
    response = wire.canonical_json_dumps({"op": "decision", "observation": {"hand": ["snowman \u2603"]},
                                          "candidates": [{"id": 18, "kind": "cast", "nested": {"value": 9}}]})

    class Peer:
        def __init__(self): self.sent = []
        def write_line(self, payload): self.sent.append(payload)
        def read_line(self): return response

    peer = Peer()
    wrapped = engine_records.RecordPeer(peer, record)
    expected = b"".join(wire.canonical_json_dumps({"dir": direction, "message": wire.strict_json_loads(payload)}) + b"\n"
                        for direction, payload in (("host_to_engine", request), ("engine_to_host", response)))
    config["per_game_cap_bytes"] = len(expected)
    wrapped.write_line(request)
    assert wrapped.read_line() == response
    with pytest.raises(ValueError, match="byte cap"):
        wrapped.write_line(request)
    record.close()
    assert record.path.read_bytes() == expected
    assert peer.sent == [request]
    assert not (record.directory / "READY.json").exists()


def test_success_releases_only_acknowledged_hot_transcript_and_keeps_all_receipts(recording):
    directory, terminal, _ = sealed(recording)
    sentinel = directory / "failure-history.json"
    sentinel.write_bytes(b"prior attempts remain")
    before = {name: (directory / name).read_bytes() for name in ("engine.jsonl", "ROW.json", "READY.json")}
    ack = acknowledge(directory)
    guards = []
    engine_records.collect(directory, terminal, guard=lambda: guards.append("checked"))
    assert guards
    assert not (directory / "engine.jsonl").exists()
    assert sentinel.read_bytes() == b"prior attempts remain"
    assert (directory / "ROW.json").read_bytes() == wire.canonical_json_dumps(terminal.to_json())
    assert (directory / "ROW.json").read_bytes() == before["ROW.json"]
    assert (directory / "READY.json").read_bytes() == before["READY.json"]
    assert json.loads((directory / "COLLECTED.json").read_bytes()) == ack
    release = json.loads((directory / "HOT-RELEASE.json").read_bytes())
    assert release["schema"] == "spellbench-engine-record-hot-release/v1"
    for key in ("ready_sha256", "row_sha256", "row_bytes", "transcript_sha256", "transcript_bytes",
                "cold_path", "recovery_path", "cold_verified", "recovery_verified"):
        assert release[key] == ack[key]
    for key in ("cold_path", "recovery_path"):
        assert Path(ack[key]).read_bytes() == before["engine.jsonl"]


@pytest.mark.parametrize("field,value", [
    ("ready_sha256", "0" * 64), ("row_sha256", "0" * 64), ("row_bytes", 0),
    ("transcript_sha256", "0" * 64), ("transcript_bytes", 0),
    ("cold_path", "unrelated-cold-file"), ("recovery_path", "unrelated-recovery-file"),
    ("cold_verified", False), ("recovery_verified", False),
])
def test_mismatched_ack_preserves_hot_trace_and_receipts(recording, field, value):
    directory, terminal, _ = sealed(recording)
    original = (directory / "engine.jsonl").read_bytes()
    ack = acknowledge(directory)
    ack[field] = value
    (directory / "COLLECTED.json").write_text(json.dumps(ack), encoding="utf-8")
    with pytest.raises(ValueError, match="acknowledgement differs"):
        engine_records.collect(directory, terminal)
    assert (directory / "engine.jsonl").read_bytes() == original
    assert (directory / "READY.json").exists()
    assert (directory / "ROW.json").exists()
    assert not (directory / "HOT-RELEASE.json").exists()


@pytest.mark.parametrize("changed", ["READY.json", "ROW.json", "engine.jsonl", "callback"])
def test_changed_ready_terminal_or_transcript_cannot_reuse_ack(recording, changed):
    directory, terminal, _ = sealed(recording)
    acknowledge(directory)
    if changed == "READY.json":
        ready = json.loads((directory / changed).read_bytes())
        ready["operator_only"] = False
        (directory / changed).write_text(json.dumps(ready), encoding="utf-8")
    elif changed == "ROW.json":
        (directory / changed).write_bytes(b"{}")
    elif changed == "engine.jsonl":
        with (directory / changed).open("ab") as stream:
            stream.write(b"{}\n")
    else:
        terminal, = parse_ledger([ledger_row(game_index=1)])
    with pytest.raises(ValueError):
        engine_records.collect(directory, terminal)
    assert (directory / "engine.jsonl").exists()
    assert not (directory / "HOT-RELEASE.json").exists()


def test_missing_ack_times_out_under_guard_and_retains_attempt(recording, monkeypatch):
    directory, terminal, _ = sealed(recording)
    times = iter((0.0, 2.0))
    monkeypatch.setattr(engine_records.time, "monotonic", lambda: next(times))
    guards = []
    with pytest.raises(TimeoutError, match="acknowledgement expired"):
        engine_records.collect(directory, terminal, guard=lambda: guards.append("checked"))
    assert guards == ["checked"]
    assert (directory / "engine.jsonl").exists()
    assert not (directory / "HOT-RELEASE.json").exists()


@pytest.mark.parametrize("has_ack", [False, True])
def test_supervisor_refusal_preserves_trace_even_with_ready_ack(recording, has_ack):
    directory, terminal, _ = sealed(recording)
    if has_ack:
        acknowledge(directory)

    def guard():
        raise RuntimeError("supervisor STOP")

    with pytest.raises(RuntimeError, match="supervisor STOP"):
        engine_records.collect(directory, terminal, guard=guard)
    assert (directory / "engine.jsonl").exists()
    assert not (directory / "HOT-RELEASE.json").exists()


@pytest.mark.parametrize("remaining", ["engine-db", "seat-A-db", "seat-B-db", "no-container-cleanup", "live-container", "wrong-container", "absent-container"])
def test_seal_rejects_remaining_database_or_unconfirmed_container(recording, remaining):
    record, terminal, _ = recording
    if remaining == "engine-db":
        target = record.directory / "engine-work" / "private" / "db"
    elif remaining.endswith("-db"):
        seat = remaining.split("-")[1]
        target = record.directory / f"agent-work-{seat}" / "private" / "db"
    else:
        target = record.directory / "agent-work-A"
    target.mkdir(parents=True)
    if remaining.endswith("db"):
        (target / "cards.h2.mv.db").write_bytes(b"working database")
    else:
        (target / "owned.owned.json").write_text(json.dumps({"container": "owned"}), encoding="utf-8")
        if remaining == "live-container":
            (target / "owned.cleanup.json").write_text(json.dumps({"container": "owned", "confirmed_absent": False}), encoding="utf-8")
        elif remaining == "wrong-container":
            (target / "owned.cleanup.json").write_text(json.dumps({"container": "different", "confirmed_absent": True}), encoding="utf-8")
        elif remaining == "absent-container":
            (target / "owned.owned.json").write_text('{}', encoding="utf-8")
            (target / "owned.cleanup.json").write_text(json.dumps({"confirmed_absent": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="cleanup"):
        record.seal(terminal)
    assert record.path.exists()
    assert not (record.directory / "READY.json").exists()


@pytest.mark.parametrize("ack_state", ["bad", "missing"])
def test_uncollected_trace_stops_bounded_executor_before_replenishment(recording, monkeypatch, ack_state):
    directory, terminal, _ = sealed(recording)
    if ack_state == "bad":
        ack = acknowledge(directory)
        ack["recovery_verified"] = False
        (directory / "COLLECTED.json").write_text(json.dumps(ack), encoding="utf-8")
    else:
        times = iter((0.0, 2.0))
        monkeypatch.setattr(engine_records.time, "monotonic", lambda: next(times))
    submitted = []

    class ObservedPool(ThreadPoolExecutor):
        def submit(self, function, context):
            submitted.append(context)
            return super().submit(function, context)

    monkeypatch.setattr(executor, "ProcessPoolExecutor", lambda *, max_workers, mp_context: ObservedPool(max_workers))
    # Process termination is covered by executor tests; these workers are threads.
    monkeypatch.setattr(executor, "_terminate_workers", lambda pool: None)
    result = executor.execute([0, 1, 2, 4], play_one, workers=2, submission_window=2,
                              on_outcome=lambda outcome: engine_records.collect(directory, terminal))
    assert result.stopped == "aborted"
    assert isinstance(result.error, ValueError if ack_state == "bad" else TimeoutError)
    assert submitted == [0, 1]
    assert [outcome.row.game_index for outcome in result.outcomes] == [0]
    assert (directory / "engine.jsonl").exists()


@pytest.fixture
def collector():
    path = Path(engine_records.__file__).resolve().parents[2] / "tools/xmage_engine_record_collect.py"
    spec = importlib.util.spec_from_file_location("engine_record_collector_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compressed_custody_preserves_complete_bytes_in_both_stores_before_release(recording, collector):
    record, _, config = recording
    config["transport"] = {"compression": "gzip"}
    directory, terminal, _ = sealed(recording)
    original = (directory / "engine.jsonl").read_bytes()
    ack = collector.preserve(directory, config)
    assert (directory / "engine.jsonl").read_bytes() == original
    assert not (directory / "COLLECTED.json").exists()
    for key in ("cold_path", "recovery_path"):
        compressed = Path(ack[key]).read_bytes()
        assert Path(ack[key]).name == "engine.jsonl.gz"
        assert digest(compressed) == ack["compressed_sha256"]
        assert len(compressed) == ack["compressed_bytes"]
        assert gzip.decompress(compressed) == original
        assert json.loads(Path(ack[key]).with_name("COLLECTED.json").read_bytes()) == ack
    (directory / "COLLECTED.json").write_text(json.dumps(ack), encoding="utf-8")
    engine_records.collect(directory, terminal)
    assert not (directory / "engine.jsonl").exists()
    assert (directory / "HOT-RELEASE.json").exists()


@pytest.mark.parametrize("destination", ["cold_source", "recovery"])
def test_conflicting_compressed_custody_copy_never_acknowledges_or_releases(recording, collector, destination):
    record, _, config = recording
    config["transport"] = {"compression": "gzip"}
    directory, _, _ = sealed(recording)
    target = Path(config[destination]) / directory.name
    target.mkdir(parents=True)
    (target / "engine.jsonl.gz").write_bytes(b"different evidence")
    with pytest.raises(ValueError, match="custody copy differs"):
        collector.preserve(directory, config)
    assert (directory / "engine.jsonl").exists()
    assert not (directory / "COLLECTED.json").exists()
    assert not (directory / "HOT-RELEASE.json").exists()
