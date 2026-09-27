"""The useful-compute guard (COMPUTE-POLICY.md): probe, scaling comparison, selection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena.throughput import (
    Allocation, IdleMonitor, ThroughputError, plan_allocation, resource_bound, worker_ladder, workload_id,
)
from spellbench.errors import ValidationError
from spellbench.wire import canonical_json_dumps


def _player(per_game_seconds: float, speedup: dict[int, float], digest: str = "sha256:" + "0" * 64):
    calls: list[tuple[int, int]] = []

    def play(workers: int, games: int) -> tuple[float, str]:
        calls.append((workers, games))
        return games * per_game_seconds / speedup.get(workers, 1.0), digest

    return play, calls


def test_a_fast_schedule_is_small_and_keeps_the_resource_bounded_workers() -> None:
    play, calls = _player(0.5, {})
    allocation = plan_allocation(games_total=96, cap=4, per_game_cores=1, play=play, placement=None, cpu_count=24, host="h")
    assert (allocation.kind, allocation.workers, allocation.projected_serial_seconds) == ("small", 4, 48)
    assert calls == [(1, 2)] and allocation.measured


def test_a_substantial_schedule_compares_worker_counts_on_identical_games() -> None:
    play, calls = _player(10.0, {2: 1.9, 4: 3.5, 8: 3.4})
    allocation = plan_allocation(games_total=192, cap=8, per_game_cores=3, play=play, placement="this PC; HaleysPC idle but slower",
                                 cpu_count=24, host="h")
    # The probe, then {1, bound // 2, bound} on the same 8 games: 16 games would cost more than a tenth of the serial time.
    assert calls == [(1, 2), (1, 8), (4, 8), (8, 8)]
    assert allocation.kind == "substantial" and allocation.workers == 4 and allocation.outputs_identical
    assert allocation.to_json()["placement"] == "this PC; HaleysPC idle but slower"


@pytest.mark.parametrize(
    ("games_total", "ladder"),
    [
        (2000, [(1, 16), (4, 16), (8, 16)]),  # two games per worker fit in a tenth of the serial time
        (192, [(1, 8), (4, 8), (8, 8)]),  # they do not: one game per worker
        (5, [(1, 5), (2, 5), (5, 5)]),  # never more workers than games
    ],
)
def test_the_ladder_is_bounded_by_its_budget_and_the_games(games_total: int, ladder: list[tuple[int, int]]) -> None:
    play, calls = _player(60.0, {})
    plan_allocation(games_total=games_total, cap=8, per_game_cores=1, play=play, placement="this PC only",
                    cpu_count=24, host="h")
    assert calls == [(1, 2), *ladder]


def test_the_qualification_wall_time_is_recorded() -> None:
    now = [0.0]

    def timed(play):
        def run(workers: int, games: int) -> tuple[float, str]:
            seconds, digest = play(workers, games)
            now[0] += seconds + 0.25  # process start-up outside the games
            return seconds, digest

        return run

    small = plan_allocation(games_total=96, cap=4, per_game_cores=1, play=timed(_player(0.5, {})[0]), placement=None,
                            cpu_count=24, host="h", clock=lambda: now[0])
    assert small.qualification_seconds_milli == 1_250
    substantial = plan_allocation(games_total=192, cap=8, per_game_cores=1, play=timed(_player(10.0, {4: 4.0, 8: 5.0})[0]),
                                  placement="this PC only", cpu_count=24, host="h", clock=lambda: now[0])
    # The probe's 20 s, then 80 s, 20 s and 16 s on the same 8 games, and 0.25 s around each.
    assert substantial.workers == 8 and substantial.to_json()["qualification_seconds_milli"] == 137_000


def test_a_substantial_run_needs_a_placement_note() -> None:
    play, _ = _player(10.0, {})
    with pytest.raises(ThroughputError, match="placement"):
        plan_allocation(games_total=192, cap=8, per_game_cores=3, play=play, placement=None, cpu_count=24, host="h")


def test_outputs_that_change_with_the_worker_count_are_refused() -> None:
    digests = iter(["sha256:" + "0" * 64, "sha256:" + "0" * 64, "sha256:" + "1" * 64])
    with pytest.raises(ThroughputError, match="changed the results"):
        plan_allocation(games_total=192, cap=2, per_game_cores=1, play=lambda w, g: (g * 10.0, next(digests)),
                        placement="x", cpu_count=24, host="h")


def test_an_empty_schedule_is_refused_before_anything_plays() -> None:
    play, calls = _player(1.0, {})
    with pytest.raises(ThroughputError, match="no games"):
        plan_allocation(games_total=0, cap=4, per_game_cores=1, play=play, placement=None, cpu_count=4, host="h")
    assert calls == []


def test_a_single_worker_bound_does_not_replay_the_probe() -> None:
    play, calls = _player(100.0, {})
    allocation = plan_allocation(games_total=10, cap=1, per_game_cores=1, play=play, placement="this PC only: cap 1",
                                 cpu_count=24, host="h")
    assert calls == [(1, 2)] and allocation.kind == "substantial" and allocation.trials == (allocation.probe,)


def test_resources_bound_the_ladder() -> None:
    assert resource_bound(24, 3) == 8 and resource_bound(2, 3) == 1
    assert worker_ladder(8) == (1, 4, 8) and worker_ladder(6) == (1, 3, 6) and worker_ladder(2) == (1, 2)
    assert worker_ladder(1) == (1,)


def test_an_unmeasured_allocation_round_trips_and_is_not_measured() -> None:
    allocation = Allocation.unmeasured(2, cpu_count=4, host="h")
    assert not allocation.measured and Allocation.from_json(allocation.to_json()) == allocation


def test_a_measured_allocation_round_trips_and_parsing_is_strict() -> None:
    play, _ = _player(10.0, {4: 3.5, 8: 3.4})
    allocation = plan_allocation(games_total=192, cap=8, per_game_cores=1, play=play, placement="this PC only",
                                 cpu_count=24, host="h", workload=workload_id({"config": {"format": "pauper-bo1"}}))
    value = allocation.to_json()
    assert canonical_json_dumps(value)  # integers only: the manifest's allocation block is canonical JSON
    assert Allocation.from_json(value) == allocation
    broken: list[dict[str, Any]] = [
        {**value, "note": "x"},
        {key: item for key, item in value.items() if key != "reused"},
        {**value, "kind": "large"},
        {**value, "workers": True},
        {**value, "trials": []},
        {**value, "outputs_identical": False},
        {**value, "placement": None},
        {**value, "probe": {**value["probe"], "outputs_digest": "0" * 64}},
    ]
    for item in broken:
        with pytest.raises(ValidationError):
            Allocation.from_json(item)


def test_the_workload_identity_is_canonical() -> None:
    assert workload_id({"a": 1, "b": [2, "x"]}) == workload_id({"b": [2, "x"], "a": 1})
    assert workload_id({"a": 1}).startswith("sha256:") and len(workload_id({"a": 1})) == len("sha256:") + 64
    with pytest.raises(ThroughputError):
        workload_id({"a": 0.5})


def _reuse_plan(evidence: Path) -> dict[str, Any]:
    return dict(games_total=192, cap=8, per_game_cores=3, cpu_count=24, host="h", evidence=evidence,
                workload=workload_id({"config": {"format": "pauper-bo1"}, "engine_files": ["a" * 64]}))


def test_a_compatible_prior_qualification_is_reused(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    first = plan_allocation(play=play, placement="this PC only", **_reuse_plan(evidence))
    assert not first.reused and len(calls) == 4 and len(evidence.read_text(encoding="utf-8").splitlines()) == 1
    again = plan_allocation(play=play, placement="this PC; HaleysPC busy", **_reuse_plan(evidence))
    assert len(calls) == 4 and again.reused and again.placement == "this PC; HaleysPC busy"
    assert replace(again, reused=False, placement="this PC only") == first
    assert again.measured and Allocation.from_json(again.to_json()) == again
    with pytest.raises(ThroughputError, match="placement"):  # a reused substantial allocation still needs this run's note
        plan_allocation(play=play, placement=None, **_reuse_plan(evidence))
    assert len(calls) == 4 and len(evidence.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    "change",
    [{"host": "other"}, {"cpu_count": 32}, {"per_game_cores": 2}, {"cap": 4},
     {"workload": workload_id({"config": {"format": "pauper-bo1"}, "engine_files": ["b" * 64]})}],
)
def test_a_changed_condition_qualifies_again(tmp_path: Path, change: dict[str, Any]) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    plan_allocation(play=play, placement="this PC only", **_reuse_plan(evidence))
    before = len(calls)
    allocation = plan_allocation(play=play, placement="this PC only", **{**_reuse_plan(evidence), **change})
    assert not allocation.reused and len(calls) > before


def test_unreadable_evidence_is_ignored_and_evidence_needs_a_workload(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    evidence.write_text('not json\n{"schema": "spellbench-throughput-evidence/v1", "allocation": {}}\n', encoding="utf-8")
    play, calls = _player(0.5, {})
    plan = dict(games_total=96, cap=4, per_game_cores=1, placement=None, cpu_count=24, host="h", evidence=evidence,
                workload=workload_id({"config": {"format": "pauper-bo1"}}))
    assert not plan_allocation(play=play, **plan).reused and plan_allocation(play=play, **plan).reused
    assert calls == [(1, 2)]
    with pytest.raises(ThroughputError, match="workload"):
        plan_allocation(play=play, **{**plan, "workload": None})


def test_the_idle_monitor_warns_after_two_idle_windows() -> None:
    now = [0.0]
    monitor = IdleMonitor(4, window_s=60.0, clock=lambda: now[0])
    warnings = []
    for second in range(0, 181, 10):
        now[0] = float(second)
        warnings.append(monitor.tick(running=2, queued=5))
    assert [w for w in warnings if w] and "idle" in [w for w in warnings if w][0]
    busy = IdleMonitor(4, window_s=60.0, clock=lambda: now[0])
    assert all(busy.tick(running=4, queued=5) is None for _ in range(3))


def test_only_sustained_idle_capacity_is_flagged() -> None:
    now = [0.0]
    monitor = IdleMonitor(4, window_s=60.0, clock=lambda: now[0])

    def flagged(start: int, stop: int, *, running, queued: int) -> list[int]:
        seconds = []
        for second in range(start, stop, 5):
            now[0] = float(second)
            if monitor.tick(running=running(second), queued=queued):
                seconds.append(second)
        return seconds

    # A game ends every 15 s and the next starts a moment later: a gap, never sustained.
    assert flagged(0, 600, running=lambda s: 3 if s % 15 == 0 else 4, queued=5) == []
    # The tail of the run: capacity is free but nothing is queued.
    assert flagged(600, 1200, running=lambda s: 1, queued=0) == []
    # One busy tick ends an idle stretch; two unbroken windows of idle capacity warn, and again two windows later.
    assert flagged(1200, 1300, running=lambda s: 4 if s == 1290 else 2, queued=5) == []
    assert flagged(1300, 1545, running=lambda s: 2, queued=5) == [1415, 1535]
