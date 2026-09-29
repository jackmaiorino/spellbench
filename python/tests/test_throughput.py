"""The useful-compute guard (COMPUTE-POLICY.md): probe, scaling comparison, spot check, budget and monitoring."""

from __future__ import annotations

import heapq
import io
import json
import os
import platform
import random
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import qualification
from spellbench.arena.machine import cgroup_cpus, host_name
from spellbench.arena.throughput import (
    RESERVE_BYTES, SUBSTANTIAL_RUN_SECONDS, Allocation, Budget, CpuSampler, IdleMonitor, MachineFacts, Placement,
    PlayedGame, ThroughputError, check_reserve, free_bytes, machine_facts, nvidia_gpus, plan_allocation, resource_bound,
    sample_order, spot_check_game, total_memory, warning_sink, worker_ladder, workload_id,
)
from spellbench.errors import ValidationError
from spellbench.wire import canonical_json_dumps

DIGEST = "sha256:" + "0" * 64
OTHER = "sha256:" + "1" * 64
PLACEMENT = ("main-pc=used: fastest measured; haleyspc=slower: about half the speed per game; "
             "runpod=not_authorized: no spending authority for this run")
FIRST_16 = tuple(range(16))
MACHINE = MachineFacts(memory_bytes=2**36, gpus=(), free_bytes=(("pin_root", 2**42), ("run_dir", 2**42)))


def _player(per_game_seconds: float, speedup: dict[int, float], *, digest=lambda workers, index: DIGEST, row_bytes: int = 1000):
    """A fake qualification: with contention a game takes ``per_game_seconds * workers / speedup[workers]``,
    so ``workers`` games at a time finish ``speedup[workers]`` times faster than one."""
    calls: list[tuple[int, tuple[int, ...]]] = []

    def play(workers: int, indices: tuple[int, ...]) -> tuple[float, tuple[PlayedGame, ...]]:
        calls.append((workers, tuple(indices)))
        seconds = per_game_seconds * workers / speedup.get(workers, 1.0)
        games = tuple(PlayedGame(index, seconds, digest(workers, index), row_bytes) for index in indices)
        return len(indices) * per_game_seconds / speedup.get(workers, 1.0), games

    return play, calls


def _plan(play, **change: Any) -> Allocation:
    """plan_allocation for the pauper-kernel shape (192 games, cap 8, 24 cores), with placement and machine facts."""
    plan = {"games_total": 192, "cap": 8, "per_game_cores": 1, "play": play, "placement": PLACEMENT, "cpu_count": 24,
            "host": "h", "machine": MACHINE}
    return plan_allocation(**{**plan, **change})


def _counts(calls: list[tuple[int, tuple[int, ...]]]) -> list[tuple[int, int]]:
    return [(workers, len(indices)) for workers, indices in calls]


def _counting(play):
    """``play`` that advances a call counter after each call (for digests that change from call to call)."""
    call = [0]

    def run(workers: int, indices: tuple[int, ...]):
        result = play(workers, indices)
        call[0] += 1
        return result

    return run, call


def _ticks(monitor: IdleMonitor, now: list[float], seconds, *, running, queued: int = 5, completed=None) -> list[int]:
    """Tick at each second; returns the seconds whose tick warned."""
    flagged = []
    for second in seconds:
        now[0] = float(second)
        done = None if completed is None else completed(second)
        if monitor.tick(running=running(second) if callable(running) else running, queued=queued, completed=done):
            flagged.append(second)
    return flagged


def test_a_short_schedule_is_small_keeps_its_configured_workers_and_awaits_its_spot_check() -> None:
    play, calls = _player(0.5, {})
    allocation = _plan(play, games_total=96, cap=4, placement=None)
    assert (allocation.kind, allocation.workers, allocation.projected_serial_seconds) == ("small", 4, 48)
    assert calls == [(1, (0, 1))] and allocation.spot_check is None and not allocation.measured
    assert allocation.label == allocation.to_json()["label"] == "small run, not spot-checked"
    assert allocation.to_json()["rules"] == {"substantial_run_seconds": 600, "budget_percent": 12, "games_per_worker": 2,
                                         "probe_games": 2, "ladder_divisors": [2, 1], "spot_check_divisor": 2}
    assert allocation.rules.substantial_run_seconds == SUBSTANTIAL_RUN_SECONDS == 600


def test_a_small_run_is_ratable_once_its_spot_check_passes() -> None:
    play, _ = _player(0.5, {})
    allocation = _plan(play, games_total=96, cap=4, placement=None)
    game = spot_check_game(96)
    passed = allocation.with_spot_check(game, recorded_digest=DIGEST, replayed_digest=DIGEST)
    assert game == 48 and passed.measured and passed.label == "small run, spot-checked"
    assert passed.to_json()["spot_check"] == {"game_index": 48, "recorded_digest": DIGEST, "replayed_digest": DIGEST,
                                              "passed": True}
    assert Allocation.from_json(passed.to_json()) == passed
    failed = allocation.with_spot_check(game, recorded_digest=DIGEST, replayed_digest=OTHER)
    assert not failed.measured and failed.label == "small run, spot check failed"
    with pytest.raises(ThroughputError, match="game 48"):
        allocation.with_spot_check(game + 1, recorded_digest=DIGEST, replayed_digest=DIGEST)
    substantial = _plan(_player(10.0, {4: 3.5, 8: 3.4})[0])
    with pytest.raises(ThroughputError, match="small"):
        substantial.with_spot_check(96, recorded_digest=DIGEST, replayed_digest=DIGEST)
    value = passed.to_json()
    for broken in ({**value["spot_check"], "passed": False}, {**value["spot_check"], "game_index": 47}):
        with pytest.raises(ValidationError):
            Allocation.from_json({**value, "spot_check": broken})


def test_a_substantial_schedule_compares_worker_counts_on_identical_games() -> None:
    play, calls = _player(10.0, {2: 1.9, 4: 3.5, 8: 3.4})
    allocation = _plan(play, per_game_cores=3)
    # The probe plays two games per top-rung worker with one worker and is the ladder's first rung; 4 and 8 workers
    # then play the same 16 games (22 game-times at ideal scaling: within 12 percent of the 192-game schedule).
    assert calls == [(1, FIRST_16), (4, FIRST_16), (8, FIRST_16)]
    assert allocation.kind == "substantial" and allocation.workers == 4 and allocation.outputs_identical
    assert allocation.measured and allocation.label == "substantial run, measured" and allocation.trials[0] == allocation.probe
    assert allocation.spot_check is None and allocation.to_json()["placement"] == Placement.parse(PLACEMENT).to_json()


@pytest.mark.parametrize(
    ("games_total", "per_game", "kind", "counts"),
    [
        (2000, 200.0, "substantial", [(1, 16), (4, 16), (8, 16)]),
        (192, 200.0, "substantial", [(1, 16), (4, 16), (8, 16)]),
        (192, 3.125, "substantial", [(1, 16), (4, 16), (8, 16)]),  # 600 s projected: substantial at the threshold
        (192, 3.0, "small", [(1, 16)]),  # 576 s projected: under the threshold
        (183, 200.0, "small", [(1, 2)]),  # the comparison would cost 12.02 percent of the serial schedule
        (5, 200.0, "small", [(1, 2)]),  # fewer games than two per worker at the top rung
    ],
)
def test_a_schedule_short_in_time_or_games_is_small(games_total: int, per_game: float, kind: str, counts: list) -> None:
    play, calls = _player(per_game, {})
    allocation = _plan(play, games_total=games_total)
    assert allocation.kind == kind and _counts(calls) == counts


def test_the_substantial_threshold_is_recorded_and_patchable(monkeypatch) -> None:
    play, _ = _player(0.5, {})
    assert _plan(play, placement=None).kind == "small"  # 192 games of half a second
    monkeypatch.setattr(qualification, "SUBSTANTIAL_RUN_SECONDS", 0)  # what a test forcing the ladder patches
    forced = _plan(play)
    assert forced.kind == "substantial" and forced.to_json()["rules"]["substantial_run_seconds"] == 0
    monkeypatch.undo()
    assert Allocation.from_json(forced.to_json()) == forced  # checked against its own recorded threshold


@pytest.mark.parametrize(
    ("name", "value"),
    [("SUBSTANTIAL_RUN_SECONDS", 60), ("SUBSTANTIAL_RUN_SECONDS", 5000), ("QUALIFY_BUDGET_PERCENT", 11),
     ("QUALIFY_BUDGET_PERCENT", 13), ("QUALIFY_GAMES_PER_WORKER", 3), ("PROBE_GAMES", 4), ("LADDER_DIVISORS", (4, 2, 1)),
     ("SPOT_CHECK_DIVISOR", 3)],
)
def test_a_manifest_stays_valid_after_the_rules_change(monkeypatch, name: str, value: Any) -> None:
    play, _ = _player(10.0, {4: 3.5, 8: 3.4})
    substantial = _plan(play).to_json()
    small = _plan(play, games_total=183, placement=None)  # 12.02 percent: the comparison does not fit
    small = small.with_spot_check(spot_check_game(183), recorded_digest=DIGEST, replayed_digest=DIGEST).to_json()
    monkeypatch.setattr(qualification, name, value)  # the rules change after both manifests were written
    assert Allocation.from_json(substantial).label == "substantial run, measured"
    assert Allocation.from_json(small).label == "small run, spot-checked"
    assert qualification.current_rules().to_json() != substantial["rules"]


def test_a_small_run_spot_checks_the_game_its_own_rules_name(monkeypatch) -> None:
    play, _ = _player(0.5, {})
    monkeypatch.setattr(qualification, "SPOT_CHECK_DIVISOR", 3)
    planned = _plan(play, games_total=96, cap=4, placement=None)  # planned under a rule naming game 32
    monkeypatch.undo()  # the rules change again before the run ends and replays its game
    checked = planned.with_spot_check(32, recorded_digest=DIGEST, replayed_digest=DIGEST)
    assert checked.label == "small run, spot-checked" and Allocation.from_json(checked.to_json()) == checked
    with pytest.raises(ThroughputError, match="game 32"):
        planned.with_spot_check(spot_check_game(96), recorded_digest=DIGEST, replayed_digest=DIGEST)  # today's: 48


def test_reuse_never_crosses_a_rules_change(tmp_path: Path, monkeypatch) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence))
    monkeypatch.setattr(qualification, "QUALIFY_BUDGET_PERCENT", 13)  # the same probe, under other rules
    again = plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence))
    assert not again.reused and again.rules.budget_percent == 13 and _counts(calls) == [(1, 16), (4, 16), (8, 16)] * 2


def test_the_qualification_wall_time_is_recorded() -> None:
    now = [0.0]

    def timed(play):
        def run(workers: int, indices: tuple[int, ...]):
            seconds, games = play(workers, indices)
            now[0] += seconds + 0.25  # worker start-up outside the games
            return seconds, games

        return run

    small = _plan(timed(_player(0.5, {})[0]), games_total=96, cap=4, placement=None, clock=lambda: now[0])
    assert small.qualification_seconds_milli == 1_250
    substantial = _plan(timed(_player(10.0, {4: 4.0, 8: 5.0})[0]), clock=lambda: now[0])
    # 16 games at 1, 4 and 8 workers take 160 s, 40 s and 32 s, and 0.25 s around each call.
    assert substantial.workers == 8 and substantial.to_json()["qualification_seconds_milli"] == 232_750


def test_busy_time_ranking_finds_the_fastest_worker_count_where_batch_wall_time_does_not() -> None:
    """Plan review I2: lognormal game lengths (sigma 0.8), 4 workers 3.6 times and 8 workers 5.5 times faster than one,
    and 15 percent noise per game. The batch wall time of a rung is dominated by its slowest games; the summed game
    times of identical games are not."""
    slow = {1: 1.0, 4: 4 / 3.6, 8: 8 / 5.5}
    rng = random.Random(20260927)
    wrong_by_busy = wrong_by_wall = 0
    for _ in range(200):
        lengths = [60.0 * rng.lognormvariate(-0.32, 0.8) for _ in range(192)]
        walls: dict[int, float] = {}

        def play(workers: int, indices: tuple[int, ...]):
            durations = [lengths[index] * slow[workers] * rng.uniform(0.85, 1.15) for index in indices]
            free = [0.0] * workers
            for duration in durations:  # a pool hands the next game to the first free worker
                heapq.heappush(free, heapq.heappop(free) + duration)
            walls[workers] = max(free)
            return max(free), tuple(PlayedGame(index, duration, DIGEST, 100) for index, duration in zip(indices, durations))

        wrong_by_busy += _plan(play).workers != 8
        wrong_by_wall += min(walls, key=lambda workers: (round(walls[workers] * 1000), workers)) != 8
    assert wrong_by_busy == 0 and wrong_by_wall >= 40


def test_a_substantial_run_needs_a_placement_naming_every_machine() -> None:
    play, _ = _player(10.0, {})
    for placement in (None, "   "):
        with pytest.raises(ThroughputError, match="placement"):
            _plan(play, placement=placement)
    with pytest.raises(ThroughputError, match="main-pc, haleyspc and runpod"):
        _plan(play, placement="this PC only")


def test_the_placement_names_each_machine_once_with_a_disposition_and_a_reason() -> None:
    placement = Placement.parse(PLACEMENT)
    assert [(entry.machine, entry.disposition) for entry in placement.entries] == [
        ("main-pc", "used"), ("haleyspc", "slower"), ("runpod", "not_authorized")]
    assert Placement.parse(str(placement)) == placement == Placement.from_json(placement.to_json())
    assert placement.to_json()["runpod"] == {"disposition": "not_authorized", "reason": "no spending authority for this run"}
    for bad in (
        "main-pc=used: fastest; runpod=unavailable: no lease",  # a machine missing
        PLACEMENT + "; main-pc=used: again",  # a machine twice
        PLACEMENT.replace("=slower", "=busy"),  # not a disposition
        PLACEMENT.replace("fastest measured", " "),  # no reason
        PLACEMENT.replace("main-pc=used", "main-pc=slower"),  # no machine used
        PLACEMENT + "; laptop=unavailable: off",  # an unknown machine
    ):
        with pytest.raises(ThroughputError, match="main-pc, haleyspc and runpod"):
            Placement.parse(bad)


def test_outputs_that_change_with_the_worker_count_are_refused() -> None:
    play, calls = _player(10.0, {}, digest=lambda workers, index: DIGEST if workers == 1 else OTHER)
    with pytest.raises(ThroughputError, match="changed the results"):
        _plan(play, cap=2)
    assert _counts(calls) == [(1, 4), (2, 4), (1, 4)]  # the 1-worker trial was replayed and reproduced itself


def test_bots_that_read_the_clock_are_recorded_not_refused() -> None:
    def digest(workers: int, index: int) -> str:  # game 1's digest names the call that played it: a bot reading the clock
        return DIGEST if index != 1 else "sha256:" + format(call[0], "064x")

    play, calls = _player(10.0, {2: 1.8}, digest=digest)
    counting, call = _counting(play)
    allocation = _plan(counting, cap=2)
    assert _counts(calls) == [(1, 4), (2, 4), (1, 4)] and allocation.workers == 2 and allocation.measured
    assert allocation.outputs_identical is False and allocation.outputs_note.startswith("game 1 differed between worker counts")
    assert "clock" in allocation.outputs_note and Allocation.from_json(allocation.to_json()) == allocation


def test_a_clock_reading_game_cannot_hide_a_worker_count_change_in_another() -> None:
    """Re-review: game 1 reads the clock (differs on every call); game 5 changes only with more than one worker."""

    def digest(workers: int, index: int) -> str:
        if index == 1:
            return "sha256:" + format(call[0], "064x")
        return "sha256:" + "5" * 64 if index == 5 and workers > 1 else DIGEST

    play, calls = _player(10.0, {4: 3.5, 8: 3.4}, digest=digest)
    counting, call = _counting(play)
    with pytest.raises(ThroughputError, match=r"changed the results of identical games \(game 5\)"):
        _plan(counting)
    assert _counts(calls) == [(1, 16), (4, 16), (8, 16), (1, 16)]  # the replay changed game 1, never game 5


def test_an_empty_schedule_is_refused_before_anything_plays() -> None:
    play, calls = _player(1.0, {})
    with pytest.raises(ThroughputError, match="no games"):
        _plan(play, games_total=0, cap=4, cpu_count=4)
    assert calls == []


def test_a_single_worker_bound_does_not_replay_the_probe() -> None:
    play, calls = _player(100.0, {})
    allocation = _plan(play, games_total=20, cap=1)
    assert calls == [(1, (0, 1))] and allocation.kind == "substantial" and allocation.trials == (allocation.probe,)


def test_qualification_samples_games_across_matchups() -> None:
    assert sample_order([[0, 1, 2, 3], [4, 5], [6, 7, 8]]) == (0, 4, 6, 1, 5, 7, 2, 8, 3)
    matchups = [list(range(start, start + 8)) for start in range(0, 192, 8)]  # 24 matchups of 8 games each
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    _plan(play, sample=sample_order(matchups))
    assert [indices for _, indices in calls] == [tuple(range(0, 128, 8))] * 3  # the first game of 16 matchups
    for bad in ([0, 0, 1], list(range(191)), [*range(191), 500]):
        with pytest.raises(ThroughputError, match="sample"):
            _plan(play, sample=bad)


@pytest.mark.parametrize(
    "play",
    [
        lambda workers, indices: (float("nan"), tuple(PlayedGame(index, 1.0, DIGEST, 10) for index in indices)),
        lambda workers, indices: (-1.0, tuple(PlayedGame(index, 1.0, DIGEST, 10) for index in indices)),
        lambda workers, indices: (1.0, tuple(PlayedGame(index, 1.0, DIGEST, 10) for index in indices[1:])),
        lambda workers, indices: (1.0, tuple(PlayedGame(index + 1, 1.0, DIGEST, 10) for index in indices)),
        lambda workers, indices: (1.0, tuple(PlayedGame(index, 1.0, "0" * 64, 10) for index in indices)),
        lambda workers, indices: (1.0, tuple(PlayedGame(index, float("inf"), DIGEST, 10) for index in indices)),
        lambda workers, indices: (1.0, tuple(PlayedGame(index, 1.0, DIGEST, -1) for index in indices)),
        lambda workers, indices: (1.0, DIGEST),  # the first version's contract
    ],
)
def test_a_play_that_reports_unusable_results_is_refused(play) -> None:
    with pytest.raises(ThroughputError, match="playing 2 games with 1 worker"):
        _plan(play, games_total=96, cap=4, placement=None)


@pytest.mark.parametrize(
    "change", [{"cpu_count": 0}, {"host": ""}, {"workload": "sha256:abc"}, {"pinned_bytes": -1}, {"cap": 0},
               {"cap_bytes": -5}, {"per_game_cores": 1.5}],
)
def test_bad_launch_facts_are_refused_before_anything_plays(change: dict[str, Any]) -> None:
    play, calls = _player(0.5, {})
    with pytest.raises(ThroughputError):
        _plan(play, **{"games_total": 96, "cap": 4, "placement": None, **change})
    assert calls == []


def test_resources_bound_the_ladder() -> None:
    assert resource_bound(24, 3) == 8 and resource_bound(2, 3) == 1
    assert worker_ladder(8) == (1, 4, 8) and worker_ladder(6) == (1, 3, 6) and worker_ladder(2) == (1, 2)
    assert worker_ladder(1) == (1,)


def test_a_container_cpu_quota_bounds_the_core_count() -> None:
    assert cgroup_cpus("max 100000\n") is None and cgroup_cpus(None) is None
    assert cgroup_cpus("200000 100000\n") == 2 and cgroup_cpus("150000 100000") == 2
    assert cgroup_cpus("garbage") is None


def test_an_unmeasured_allocation_round_trips_and_is_not_measured() -> None:
    allocation = Allocation.unmeasured(2, cpu_count=4, host="h")
    assert not allocation.measured and Allocation.from_json(allocation.to_json()) == allocation
    assert allocation.label == "unmeasured" and allocation.qualified_rate is None


def test_the_host_is_an_alias_and_never_the_machine_name(monkeypatch) -> None:
    """R3-28: ``local`` unless ``SPELLBENCH_HOST_ALIAS`` names another alias; a host passed in wins."""
    monkeypatch.setattr(platform, "node", lambda: "machine-name")
    monkeypatch.delenv("SPELLBENCH_HOST_ALIAS", raising=False)
    play, _ = _player(0.5, {})
    assert host_name() == "local" and Allocation.unmeasured(1, cpu_count=4).host == "local"
    assert _plan(play, games_total=8, cap=2, placement=None, host=None).host == "local"
    monkeypatch.setenv("SPELLBENCH_HOST_ALIAS", " rig-2 ")
    assert host_name() == "rig-2" and _plan(play, games_total=8, cap=2, placement=None, host=None).host == "rig-2"
    assert host_name("given") == "given" and Allocation.unmeasured(1, cpu_count=4, host="given").host == "given"
    monkeypatch.setenv("SPELLBENCH_HOST_ALIAS", "  ")
    assert host_name() == "local"


def test_a_measured_allocation_round_trips_and_parsing_is_strict() -> None:
    play, _ = _player(10.0, {4: 3.5, 8: 3.4})
    allocation = _plan(play, workload=workload_id({"config": {"format": "pauper-bo1"}}), pinned_bytes=5000)
    value = allocation.to_json()
    assert canonical_json_dumps(value)  # integers only: the manifest's allocation block is canonical JSON
    assert Allocation.from_json(value) == allocation and allocation.qualified_rate == pytest.approx(0.35)
    broken: list[dict[str, Any]] = [
        {**value, "note": "x"},
        {key: item for key, item in value.items() if key != "reused"},
        {**value, "kind": "large"},
        {**value, "label": "small run, spot-checked"},
        {**value, "workers": True},
        {**value, "workers": 8},  # a slower rung than the busy-time choice
        {**value, "trials": []},
        {**value, "trials": [value["trials"][0], value["trials"][2], value["trials"][1]]},  # not the ladder's order
        {**value, "outputs_identical": False},  # identical digests recorded as different
        {**value, "placement": None},
        {**value, "games_total": 384},  # the projection belongs to another schedule
        {**value, "projected_serial_seconds": 100},
        {**value, "rules": {**value["rules"], "substantial_run_seconds": 2000}},  # under this threshold: small
        {**value, "rules": {**value["rules"], "budget_percent": 11}},  # under this budget the comparison does not fit
        {**value, "rules": {**value["rules"], "ladder_divisors": [4, 2, 1]}},  # the trials are not this ladder
        {**value, "rules": {**value["rules"], "ladder_divisors": [1, 2]}},  # divisors run from largest to 1
        {key: item for key, item in value.items() if key != "rules"} | {"rules": None},  # measured without rules
        {**value, "spot_check": {"game_index": 96, "recorded_digest": DIGEST, "replayed_digest": DIGEST, "passed": True}},
        {**value, "budget": {**value["budget"], "projected_bytes": 1}},
        {**value, "machine": {**value["machine"], "free_bytes": {"C:/runs": 1}}},  # roles, never paths
        {**value, "machine": {**value["machine"], "free_bytes": {"run_dir": 2**42}}},  # the pin volume is missing
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


def _reuse_plan(evidence: Path, **change: Any) -> dict[str, Any]:
    plan = {"games_total": 192, "cap": 8, "per_game_cores": 3, "cpu_count": 24, "host": "h", "evidence": evidence,
            "machine": MACHINE, "workload": workload_id({"config": {"format": "pauper-bo1"}, "engine_files": ["a" * 64]})}
    return {**plan, **change}


def test_a_compatible_prior_qualification_is_reused(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    first = plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence))
    assert not first.reused and len(calls) == 3 and len(evidence.read_text(encoding="utf-8").splitlines()) == 1
    other = PLACEMENT.replace("about half the speed per game", "busy with a training run")
    again = plan_allocation(play=play, placement=other, **_reuse_plan(evidence))
    assert len(calls) == 3 and again.reused and again.placement == Placement.parse(other)
    assert replace(again, reused=False, placement=first.placement) == first
    assert again.measured and Allocation.from_json(again.to_json()) == again
    with pytest.raises(ThroughputError, match="placement"):  # a reused substantial allocation still needs this run's note
        plan_allocation(play=play, placement=None, **_reuse_plan(evidence))
    assert len(calls) == 3 and len(evidence.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    "change",
    [{"host": "other"}, {"cpu_count": 32}, {"per_game_cores": 2}, {"cap": 4},
     {"workload": workload_id({"config": {"format": "pauper-bo1"}, "engine_files": ["b" * 64]})},
     {"games_total": 385},  # more than twice the qualified schedule
     {"machine": replace(MACHINE, memory_bytes=2**35)}],  # other hardware
)
def test_a_changed_condition_qualifies_again(tmp_path: Path, change: dict[str, Any]) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence))
    before = len(calls)
    allocation = plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence, **change))
    assert not allocation.reused and len(calls) > before


def test_a_small_rerun_never_covers_a_substantial_schedule(tmp_path: Path) -> None:
    """Plan review I1: a 10-game rerun of a config, then its 192-game run."""
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    rerun = plan_allocation(play=play, placement=None, **_reuse_plan(evidence, games_total=10, per_game_cores=1))
    assert (rerun.kind, rerun.projected_serial_seconds, _counts(calls)) == ("small", 100, [(1, 2)])
    with pytest.raises(ThroughputError, match="placement"):  # measured afresh: 1920 s serial is substantial
        plan_allocation(play=play, placement=None, **_reuse_plan(evidence, per_game_cores=1))
    full = plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence, per_game_cores=1))
    assert (full.kind, full.reused, full.projected_serial_seconds, full.games_total) == ("substantial", False, 1920, 192)


def test_reuse_needs_a_probe_of_the_same_size_and_games(tmp_path: Path) -> None:
    """Re-review: a 100-game rerun's 2-game probe (two fast builtin mirrors) must not classify the 192-game run."""
    evidence = tmp_path / "throughput-evidence.jsonl"
    calls = []

    def seconds(index: int) -> float:
        return 0.5 if index in (0, 1) else 30.0

    def play(workers: int, indices: tuple[int, ...]):
        calls.append(workers)
        return sum(seconds(index) for index in indices) / workers, tuple(PlayedGame(index, seconds(index), DIGEST, 100)
                                                                         for index in indices)

    plan = dict(cap=8, per_game_cores=1, cpu_count=24, host="h", play=play, machine=MACHINE, evidence=evidence,
                workload=workload_id({"config": "pauper-kernel"}))
    rerun = plan_allocation(games_total=100, placement=None, **plan)  # too few games for the comparison
    assert (rerun.kind, rerun.probe.games, rerun.projected_serial_seconds) == ("small", 2, 50)
    full = plan_allocation(games_total=192, placement=PLACEMENT, **plan)  # classified by its own 16-game probe
    assert (full.kind, full.reused, full.probe.games, full.projected_serial_seconds) == ("substantial", False, 16, 5052)
    reordered = plan_allocation(games_total=192, placement=PLACEMENT, sample=range(191, -1, -1), **plan)
    assert not reordered.reused  # a probe of other games is another measurement
    assert plan_allocation(games_total=192, placement=PLACEMENT, **plan).reused


def test_reuse_follows_the_schedule_within_a_factor_of_two(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(10.0, {4: 3.5, 8: 3.4})
    plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence, pinned_bytes=5000))
    larger = plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence, games_total=384, pinned_bytes=5000))
    assert larger.reused and len(calls) == 3 and (larger.games_total, larger.projected_serial_seconds) == (384, 3840)
    assert larger.budget == Budget(projected_bytes=384 * 1000 + 5000, pinned_bytes=5000, cap_bytes=2 * (384 * 1000 + 5000))


def test_reuse_never_crosses_the_size_class(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(2.5, {})
    small = plan_allocation(play=play, placement=None, **_reuse_plan(evidence))  # 480 s projected: small
    assert small.kind == "small" and _counts(calls) == [(1, 16)]
    longer = plan_allocation(play=play, placement=PLACEMENT, **_reuse_plan(evidence, games_total=250))  # 625 s
    assert longer.kind == "substantial" and not longer.reused
    assert _counts(calls) == [(1, 16), (1, 16), (4, 16), (8, 16)]


def test_reuse_never_carries_a_spot_check_forward(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    play, calls = _player(0.5, {})
    plan = _reuse_plan(evidence, games_total=96, cap=4, per_game_cores=1)
    checked = plan_allocation(play=play, placement=None, **plan).with_spot_check(
        spot_check_game(96), recorded_digest=DIGEST, replayed_digest=DIGEST)
    qualification.record_evidence(evidence, checked)  # as if a spot-checked allocation had been recorded
    again = plan_allocation(play=play, placement=None, **plan)
    assert again.reused and again.spot_check is None and not again.measured and len(calls) == 1


def test_unreadable_evidence_is_ignored_and_evidence_needs_a_workload(tmp_path: Path) -> None:
    evidence = tmp_path / "throughput-evidence.jsonl"
    evidence.write_text('not json\n{"schema": "spellbench-throughput-evidence/v1", "allocation": {}}\n', encoding="utf-8")
    play, calls = _player(0.5, {})
    plan = {"games_total": 96, "cap": 4, "placement": None, "evidence": evidence,
            "workload": workload_id({"config": {"format": "pauper-bo1"}})}
    assert not _plan(play, **plan).reused and _plan(play, **plan).reused
    assert calls == [(1, (0, 1))]
    with pytest.raises(ThroughputError, match="workload"):
        _plan(play, **{**plan, "workload": None})


def test_evidence_that_cannot_be_written_is_refused_before_anything_plays(tmp_path: Path) -> None:
    play, calls = _player(0.5, {})
    plan = {"games_total": 96, "cap": 4, "placement": None, "workload": workload_id({})}
    with pytest.raises(ThroughputError, match="evidence"):
        _plan(play, **plan, evidence=tmp_path)  # a directory where the file should be
    evidence = tmp_path / "throughput-evidence.jsonl"
    evidence.write_bytes(b"")
    os.chmod(evidence, stat.S_IREAD)  # readable, so only a write would fail: after the games, without the check
    try:
        if os.access(evidence, os.W_OK):
            pytest.skip("this user can write read-only files")
        with pytest.raises(ThroughputError, match="cannot write the throughput evidence"):
            _plan(play, **plan, evidence=evidence)
    finally:
        os.chmod(evidence, stat.S_IREAD | stat.S_IWRITE)
    assert calls == []


def test_the_budget_projects_row_and_pin_bytes_under_a_cap() -> None:
    play, _ = _player(0.5, {}, row_bytes=1000)
    allocation = _plan(play, games_total=96, cap=4, placement=None, pinned_bytes=5000)
    assert allocation.budget == Budget(projected_bytes=96 * 1000 + 5000, pinned_bytes=5000, cap_bytes=2 * (96 * 1000 + 5000))
    assert allocation.to_json()["budget"] == {"projected_bytes": 101_000, "pinned_bytes": 5000, "cap_bytes": 202_000}
    with pytest.raises(ThroughputError, match="cap"):
        _plan(play, games_total=96, cap=4, placement=None, pinned_bytes=5000, cap_bytes=100_000)


def test_a_target_volume_below_the_60_gib_reserve_is_refused() -> None:
    def machine(free: int) -> MachineFacts:
        return MachineFacts(memory_bytes=2**36, gpus=(), free_bytes=(("pin_root", 2**42), ("run_dir", free)))

    play, calls = _player(0.5, {}, row_bytes=1000)
    plan = {"games_total": 96, "cap": 4, "placement": None}
    with pytest.raises(ThroughputError, match="60 GiB"):
        _plan(play, **plan, machine=machine(RESERVE_BYTES - 1))
    assert calls == []  # refused before anything played
    with pytest.raises(ThroughputError, match="run_dir"):
        _plan(play, **plan, machine=machine(RESERVE_BYTES + 96_000 - 1))  # the projected rows would cross it
    allocation = _plan(play, **plan, machine=machine(RESERVE_BYTES + 96_000))
    assert allocation.to_json()["machine"] == {"memory_bytes": 2**36, "gpus": [],
                                               "free_bytes": {"pin_root": 2**42, "run_dir": RESERVE_BYTES + 96_000}}
    check_reserve(allocation.machine, allocation.budget.projected_bytes)


def test_the_reserve_check_always_runs_on_the_run_and_pin_volumes(tmp_path: Path, monkeypatch) -> None:
    play, calls = _player(0.5, {})
    plan = {"games_total": 96, "cap": 4, "placement": None}
    with pytest.raises(ThroughputError, match="run_dir and pin_root"):
        _plan(play, **plan, machine=None)  # no facts, and no volumes to measure
    with pytest.raises(ThroughputError, match="pin_root"):
        _plan(play, **plan, machine=MachineFacts(memory_bytes=None, gpus=(), free_bytes=(("run_dir", 2**42),)))
    measured: list[list[str]] = []

    def facts(volumes):
        measured.append(sorted(volumes))
        return MachineFacts(memory_bytes=None, gpus=(), free_bytes=(("pin_root", RESERVE_BYTES - 1), ("run_dir", 2**42)))

    monkeypatch.setattr(qualification, "machine_facts", facts)
    with pytest.raises(ThroughputError, match="pin_root has"):
        _plan(play, **plan, machine=None, volumes={"run_dir": tmp_path / "runs", "pin_root": tmp_path / "pins"})
    assert measured == [["pin_root", "run_dir"]] and calls == []


def test_machine_facts_record_memory_gpus_and_free_space_by_role(tmp_path: Path) -> None:
    facts = machine_facts({"run_dir": tmp_path / "runs" / "new", "pin_root": tmp_path}, memory=lambda: 2**36,
                          gpus=lambda: ["Test GPU"], disk_free=lambda path: 7 if path == tmp_path else 9)
    assert facts.to_json() == {"memory_bytes": 2**36, "gpus": ["Test GPU"], "free_bytes": {"pin_root": 7, "run_dir": 9}}
    assert MachineFacts.from_json(facts.to_json()) == facts
    with pytest.raises(ValidationError):
        machine_facts({str(tmp_path): tmp_path}, memory=lambda: None, gpus=lambda: [], disk_free=lambda path: 1)


def test_the_machine_probes_are_well_formed(tmp_path: Path) -> None:
    memory = total_memory()
    assert memory is None or memory > 0
    assert all(isinstance(name, str) and name for name in nvidia_gpus())
    assert free_bytes(tmp_path / "not" / "yet") > 0
    sampler = CpuSampler()
    sampler.sample()
    busy = sampler.sample()
    assert busy is None or 0.0 <= busy <= 1.0


def test_the_cpu_sampler_reports_the_busy_share_since_the_last_sample() -> None:
    counters = iter([(100, 1000), (150, 2000), (150, 2000), (1150, 3000)])
    sampler = CpuSampler(counters=lambda: next(counters))
    assert sampler.sample() is None  # nothing to compare with yet
    assert sampler.sample() == pytest.approx(0.95)  # 50 idle ticks of 1000
    assert sampler.sample() is None  # no time passed
    assert sampler.sample() == pytest.approx(0.0)  # idle throughout


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
    # A game ends every 15 s and the next starts a moment later: a gap, never sustained.
    assert _ticks(monitor, now, range(0, 600, 5), running=lambda s: 3 if s % 15 == 0 else 4) == []
    # The tail of the run: capacity is free but nothing is queued.
    assert _ticks(monitor, now, range(600, 1200, 5), running=1, queued=0) == []
    # One busy tick ends an idle stretch; two unbroken windows of idle capacity warn, and again two windows later.
    assert _ticks(monitor, now, range(1200, 1300, 5), running=lambda s: 4 if s == 1290 else 2) == []
    assert _ticks(monitor, now, range(1300, 1545, 5), running=2) == [1415, 1535]


def test_the_monitor_compares_finished_games_with_the_qualified_rate() -> None:
    now = [0.0]
    written: list[str] = []
    monitor = IdleMonitor(4, window_s=60.0, clock=lambda: now[0], qualified_rate=1.0, cpu=lambda: 0.25,
                          on_warning=written.append)
    # Every slot is busy, but only 6 games finish in each 60 s window against 60 expected.
    assert _ticks(monitor, now, range(0, 181, 10), running=4, completed=lambda s: s // 10) == [120]
    (warning,) = written
    assert warning.startswith("throughput below the qualified rate: 6 games finished in the last 60 s against 60.0 expected")
    assert warning.endswith("machine CPU 25% busy")


def test_the_rate_window_stretches_until_it_expects_enough_games() -> None:
    now = [0.0]
    monitor = IdleMonitor(8, window_s=60.0, clock=lambda: now[0], qualified_rate=8 / 400)
    # Eight 400 s games at a time finish together, so a 60 s window would mostly see none finish.
    assert _ticks(monitor, now, range(0, 2400, 5), running=8, queued=40, completed=lambda s: 8 * (s // 400)) == []
    # Then nothing finishes: after two 400 s windows it warns.
    assert _ticks(monitor, now, range(2400, 3300, 5), running=8, queued=40, completed=lambda s: 48) == [3200]


def test_warnings_are_written_and_flushed_as_they_happen(tmp_path: Path) -> None:
    path = tmp_path / "t" / "throughput.jsonl"
    stream = io.StringIO()
    now = [0.0]
    monitor = IdleMonitor(4, window_s=60.0, clock=lambda: now[0], on_warning=warning_sink(path, stream=stream))
    assert _ticks(monitor, now, range(0, 120, 10), running=1) == [] and not path.exists()
    assert _ticks(monitor, now, [120], running=1) == [120]
    (line,) = path.read_text(encoding="utf-8").splitlines()  # on disk as soon as the tick returned
    assert json.loads(line)["warning"].startswith("idle capacity") and stream.getvalue().startswith("idle capacity")
