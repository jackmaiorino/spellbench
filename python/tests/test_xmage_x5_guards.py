"""X5 retained rows and exact replay coverage, using a real small v2 host ledger."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spellbench.arena.config import TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.arena.allocation import ThroughputError
from spellbench.wire import canonical_json_dumps

from arena_helpers import TEST_RUN_SECRET, builtin, make_config, run

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("x5_guards", ROOT / "engines/xmage/tests/x5/x5run.py")
x5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x5)


@pytest.fixture
def ledger(tmp_path):
    directory = tmp_path / "host"
    config = make_config(directory, [builtin("uniform"), builtin("first")], pairs=1, include_self_play=False)
    run(config)
    parsed = TournamentConfig.from_json(config)
    contexts = schedule(parsed, TEST_RUN_SECRET)
    sched = SimpleNamespace(games=[(0, i) for i in range(len(contexts))],
                            workloads=[{"label": "test", "config": parsed, "contexts": contexts}])
    rows = [{"gid": row["game_index"], "workload": "test", "row": row,
             "row_digest": "sha256:" + hashlib.sha256(canonical_json_dumps(row)).hexdigest()}
            for row in map(json.loads, (directory / "matches.jsonl").read_text().splitlines())]
    return sched, rows


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_retained_store_requires_same_build_and_plan_and_valid_rows(tmp_path, ledger):
    sched, rows = ledger
    path = tmp_path / "rows.jsonl"
    binding = {"plan_sha256": "plan", "engine_lib_digest": "build"}
    assert x5._resume_rows(path, binding, sched, [0, 1]) == set()
    write_rows(path, rows)
    assert x5._resume_rows(path, binding, sched, [0, 1]) == {0, 1}
    with pytest.raises(ThroughputError, match="another plan"):
        x5._resume_rows(path, {**binding, "engine_lib_digest": "old-build"}, sched, [0, 1])
    rows[0]["row_digest"] = "sha256:" + "0" * 64
    write_rows(path, rows)
    with pytest.raises(ThroughputError, match="digest"):
        x5._resume_rows(path, binding, sched, [0, 1])


def test_unbound_or_duplicate_legacy_rows_cannot_be_silently_skipped(tmp_path, ledger):
    sched, rows = ledger
    path = tmp_path / "rows.jsonl"
    write_rows(path, rows)
    with pytest.raises(ThroughputError, match="no build/plan binding"):
        x5._resume_rows(path, {}, sched, [0, 1])
    path.with_suffix(".manifest.json").write_text("{}")
    write_rows(path, [rows[0], rows[0]])
    with pytest.raises(ThroughputError, match="duplicate"):
        x5._resume_rows(path, {}, sched, [0, 1])


def test_only_unterminated_tail_is_quarantined_after_validating_prefix(tmp_path, ledger):
    sched, rows = ledger
    path = tmp_path / "rows.jsonl"
    x5._resume_rows(path, {}, sched, [0, 1])
    write_rows(path, rows[:1])
    prefix = path.read_bytes()
    fragment = b'{"gid": 1,'
    path.write_bytes(prefix + fragment)
    assert x5._resume_rows(path, {}, sched, [0, 1]) == {0}
    assert path.read_bytes() == prefix
    assert [p.read_bytes() for p in tmp_path.glob("rows.jsonl.partial-*")] == [fragment]
    assert json.loads(path.with_suffix(".recovery.jsonl").read_text())["retained_rows"] == 1
    path.write_bytes(prefix + b"malformed complete row\n")
    before = path.read_bytes()
    with pytest.raises(json.JSONDecodeError):
        x5._resume_rows(path, {}, sched, [0, 1])
    assert path.read_bytes() == before


@pytest.mark.parametrize("outputs_identical", [False, None])
def test_nondeterministic_qualification_cannot_publish_or_launch(tmp_path, ledger, monkeypatch, outputs_identical):
    sched, _ = ledger
    binding = {"workload": "test"}
    facts = SimpleNamespace(memory_bytes=2**35, gpus=())
    allocation = SimpleNamespace(kind="substantial", outputs_identical=outputs_identical,
                                 workload=x5.workload_id(binding), games_total=2, workers=2,
                                 host=x5.host_name(), cpu_count=x5.usable_cpus(), machine=facts,
                                 budget=SimpleNamespace(projected_bytes=1))
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    allocation_path = tmp_path / "allocation.json"
    allocation_path.write_text("{}")
    (tmp_path / "launch-binding.json").write_text(json.dumps(binding))
    monkeypatch.setattr(x5, "Schedule", lambda *a: sched)
    monkeypatch.setattr(x5, "_selected", lambda *a: [0, 1])
    monkeypatch.setattr(x5, "resolve_command", lambda a: tuple(a))
    monkeypatch.setattr(x5, "_launch_binding", lambda *a: (binding, (), {}))
    monkeypatch.setattr(x5, "machine_facts", lambda *a: facts)
    monkeypatch.setattr(x5, "check_reserve", lambda *a: None)
    monkeypatch.setattr(x5, "_setups", lambda *a: None)
    monkeypatch.setattr(x5, "plan_allocation", lambda **kw: allocation)
    monkeypatch.setattr(x5.Allocation, "from_json", lambda *a: allocation)
    monkeypatch.setattr(x5, "run_games", lambda *a, **kw: pytest.fail("unguarded worker spawn"))
    args = SimpleNamespace(plan=str(plan), out=str(tmp_path / "run"), allocation=str(allocation_path),
                           fraction=1, part="A", limit=0, gids_file=None, workers=2, machine="test",
                           build_digest="sha256:build", p2_commit="commit", cap=2, placement=None)
    with pytest.raises(ThroughputError, match="outputs differ"):
        x5.cmd_run(args, ["unused-engine"])
    binding.update(engine_lib_digest="build", host_source_revision="commit")
    with pytest.raises(ThroughputError, match="outputs differ"):
        x5.cmd_qualify(args, ["unused-engine"])
    assert not (Path(args.out) / "allocation.json").exists()


def test_nonempty_matching_replay_subset_fails_missing_coverage(tmp_path, ledger):
    _, rows = ledger
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_rows(a, rows)
    write_rows(b, rows[:1])
    # An explicit engineering subset still requires every chosen id.
    gids = tmp_path / "gids.txt"
    gids.write_text("0 1")
    args = SimpleNamespace(a=str(a), b=str(b), out=str(tmp_path / "comparison.json"),
                           plan=str(ROOT / "engines/xmage/tests/x5/plan.json"),
                           fraction=0.1, part="A", limit=0, gids_file=str(gids))
    assert x5.cmd_compare(args) == 1
    report = json.loads(Path(args.out).read_text())
    assert report["expected"] == 2 and report["shared"] == 1 and report["missing_in_b"] == [1]
    write_rows(b, rows)
    assert x5.cmd_compare(args) == 0


def test_frozen_replay_selection_requires_all_1011_games():
    plan = json.loads((ROOT / "engines/xmage/tests/x5/plan.json").read_text())
    selected = x5._selected(x5.Schedule(plan, ["selection-only"]),
                            SimpleNamespace(fraction=0.1, part="A", limit=0, gids_file=None))
    assert len(selected) == len(set(selected)) == 1011


def test_direct_run_requires_allocation_argument_before_any_spawn(monkeypatch):
    monkeypatch.setattr(x5, "run_games", lambda *args, **kwargs: pytest.fail("unguarded worker spawn"))
    with pytest.raises(SystemExit) as exc:
        x5.main(["run", "--plan", "plan", "--machine", "test", "--workers", "4", "--fraction", "1",
                 "--part", "A", "--build", "build", "--out", "out", "--", "unused-engine"])
    assert exc.value.code == 2


@pytest.mark.parametrize("missing_game", [False, True])
def test_summary_publishes_float_diagnostics_with_complete_verdict(tmp_path, ledger, missing_game):
    _, rows = ledger
    rows = [{**row, "machine": "test", "seconds": 1.25 + row["gid"],
             "violation": None, "host_halt": False, "diagnostics": []} for row in rows]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"games_total": len(rows)}), encoding="utf-8")
    ledger_path = tmp_path / "rows.jsonl"
    write_rows(ledger_path, rows[:1] if missing_game else rows)
    output = tmp_path / "summary.json"
    args = SimpleNamespace(plan=str(plan), rows=[str(ledger_path)], stats=[], out=str(output))
    expected = 1 if missing_game else 0
    assert x5.cmd_summarize(args) == expected
    report = json.loads(output.read_bytes())
    assert report["verdict"] == ("FAIL" if missing_game else "PASS")
    assert report["games_recorded"] == (1 if missing_game else 2)
    assert report["pools"]["test"]["rates"]["natural"] == 1.0
    assert report["pools"]["test"]["seconds_per_game"]["median"] == (1.25 if missing_game else 1.75)
    assert not output.with_name(output.name + ".tmp").exists()
