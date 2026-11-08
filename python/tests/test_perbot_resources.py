"""Per-bot resources (spec 11.4): effective blocks, per-game cores, budgeted scheduling and compatibility."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from spellbench.arena import executor, qualification
from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.executor import execute
from spellbench.arena.schedule import game_setup, preflight, schedule
from spellbench.arena.snapshot import bot_inputs, contract
from spellbench.arena.throughput import PlayedGame, plan_allocation
from spellbench.messages import Resources

from test_arena_executor import play_one
from test_arena_schedule_v2 import SECRET, config as schedule_config
from test_throughput import DIGEST, MACHINE, PLACEMENT

BOARD = {"cpus": 1, "memory_mb": 4096, "gpu": False, "engine_cpus": 1}
SEARCH = {"cpus": 4, "memory_mb": 8192, "gpu": False, "engine_cpus": 1}


def sub(name: str, resources: dict | None = None) -> dict:
    bot = {"name": name, "version": "1", "type": "subprocess", "command": ["python", f"{name}.py"]}
    if resources is not None:
        bot["resources"] = resources
    return bot


def ladder(**changes) -> dict:
    """A roster like the rated ladder's: a builtin anchor, two 1-cpu policy rungs and a 4-cpu search entrant."""
    value = {"schema": "spellbench-tournament-config/v2", "tournament_dir": "out/t", "format": "pauper-bo1",
             "decks": [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}], "engine": {"command": ["engine"]},
             "bots": [{"name": "uniform", "version": "2.0.0", "type": "builtin"}, sub("c12"), sub("g115"),
                      sub("search", SEARCH)],
             "pairs_per_matchup": 1, "stats_seed": 7, "include_self_play": False, "resources": BOARD,
             "core_accounting": "sequential"}
    value.update(changes)
    return value


# -- parse and validation ------------------------------------------------------------------------------------------


def test_a_bot_block_round_trips_and_an_absent_one_stays_unwritten() -> None:
    parsed = TournamentConfig.from_json(ladder())
    written = parsed.to_json()
    assert written["bots"][3]["resources"] == SEARCH and "resources" not in written["bots"][1]
    assert TournamentConfig.from_json(written) == parsed
    assert parsed.bots[3].resources == Resources(**SEARCH) and parsed.bots[1].resources is None
    plain = TournamentConfig.from_json(ladder(bots=[{"name": "uniform", "version": "2.0.0", "type": "builtin"},
                                                    sub("c12")]))
    assert not plain.per_bot_resources and all("resources" not in bot for bot in plain.to_json()["bots"])


@pytest.mark.parametrize("bot, message", [
    ({"name": "uniform", "version": "2.0.0", "type": "builtin", "resources": BOARD}, "builtin bots play inside"),
    (sub("x", {"cpus": 4}), "resources"),
    (sub("x", {**SEARCH, "cpus": 0}), "cpus"),
    (sub("x", {**SEARCH, "threads": 2}), "resources"),
    (sub("x", {**SEARCH, "engine_cpus": 2}), "engine_cpus must equal the board's"),
])
def test_invalid_bot_blocks_name_the_field(bot: dict, message: str) -> None:
    roster = [{"name": "uniform", "version": "2.0.0", "type": "builtin"}, sub("c12")]
    if bot["name"] != "uniform":
        roster.append(bot)
    else:
        roster[0] = bot
    with pytest.raises(TournamentError, match=message):
        TournamentConfig.from_json(ladder(bots=roster))


# -- effective resources and per-game cores ------------------------------------------------------------------------


def test_effective_resources_inherit_the_board_block() -> None:
    parsed = TournamentConfig.from_json(ladder())
    uniform, c12, g115, search = parsed.bots
    assert parsed.bot_resources(c12) == parsed.resources == Resources(**BOARD)
    assert parsed.bot_resources(search) == Resources(**SEARCH)
    assert parsed.bot_resources(uniform) == parsed.resources


def test_sequential_games_reserve_the_largest_seat_and_concurrent_games_add_them_up() -> None:
    parsed = TournamentConfig.from_json(ladder())
    uniform, c12, g115, search = parsed.bots
    assert parsed.game_cores(c12, g115) == 1 and parsed.game_cores(c12, search) == 4
    assert parsed.game_cores(uniform, search) == 4 and parsed.game_cores(uniform, c12) == 1
    assert parsed.per_game_cores() == 1  # the cheapest scheduled game: the unit a worker stands for
    concurrent = TournamentConfig.from_json(ladder(core_accounting="concurrent"))
    uniform, c12, g115, search = concurrent.bots
    assert concurrent.game_cores(c12, search) == 1 + 1 + 4 and concurrent.game_cores(uniform, search) == 1 + 4
    assert concurrent.game_cores(c12, g115) == 3 and concurrent.per_game_cores() == 2  # uniform vs a 1-cpu rung


def test_the_unit_is_the_cheapest_game_the_schedule_plays() -> None:
    only_search = TournamentConfig.from_json(ladder(matchups=[["search", "c12"], ["search", "uniform"]]))
    assert only_search.per_game_cores() == 4
    assert [len(pair) for pair in only_search.scheduled_pairs()] == [2, 2]


@pytest.mark.parametrize("accounting, resources, cores", [
    ("concurrent", BOARD, 3), ("sequential", BOARD, 1), ("sequential", {**BOARD, "cpus": 4}, 4),
    ("concurrent", {**BOARD, "cpus": 2, "engine_cpus": 3}, 7),
])
def test_without_bot_blocks_every_game_reserves_the_board_formula(accounting, resources, cores) -> None:
    roster = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
              {"name": "heuristic", "version": "2.0.0", "type": "builtin"}, sub("c12")]
    parsed = TournamentConfig.from_json(ladder(bots=roster, resources=resources, core_accounting=accounting))
    assert parsed.per_game_cores() == cores
    assert {parsed.game_cores(a, b) for a, b in parsed.scheduled_pairs()} == {cores}  # builtin pairs too, as before


# -- the seats' game_start resources -------------------------------------------------------------------------------


def test_each_seat_receives_its_own_block_in_game_start() -> None:
    builtins = schedule_config()
    setup = preflight(builtins, SECRET)  # the fake engine only; the per-bot config below shares its decks
    mixed = schedule_config(bots=[{"name": "uniform", "version": "2.0.0", "type": "builtin"}, sub("search", SEARCH)],
                            resources=BOARD)
    games = [game_setup(mixed, setup, game, SECRET) for game in schedule(mixed, SECRET)]
    assert games[0].seat_resources == (Resources(**BOARD), Resources(**SEARCH))
    assert games[1].seat_resources == (Resources(**SEARCH), Resources(**BOARD))  # the seats swap
    assert [games[1].resources_for(index) for index in (0, 1)] == [Resources(**SEARCH), Resources(**BOARD)]
    plain = game_setup(builtins, setup, schedule(builtins, SECRET)[0], SECRET)
    assert plain.seat_resources is None and plain.resources_for(1) == plain.resources == builtins.resources


# -- budgeted scheduling -------------------------------------------------------------------------------------------


class _State:
    lock = threading.Lock()
    costs: dict[int, int] = {}
    used = 0
    peak = 0
    starts: list[tuple[int, int]] = []  # (game, cores in use once it started)
    submitted: list[int] = []


def tracked(index: int):
    with _State.lock:
        _State.used += _State.costs[index]
        _State.peak = max(_State.peak, _State.used)
        _State.starts.append((index, _State.used))
    time.sleep(0.2)
    with _State.lock:
        _State.used -= _State.costs[index]
    return play_one(index)


class _ThreadPool(ThreadPoolExecutor):
    """The executor's pool, in threads, so the test can see which games overlap."""

    _processes: dict = {}

    def __init__(self, max_workers: int, mp_context=None) -> None:
        super().__init__(max_workers=max_workers)

    def submit(self, function, context):
        _State.submitted.append(context)
        return super().submit(function, context)


@pytest.fixture
def threads(monkeypatch):
    monkeypatch.setattr(executor, "ProcessPoolExecutor", _ThreadPool)
    _State.used, _State.peak, _State.starts, _State.submitted = 0, 0, [], []
    return _State


def test_a_four_core_game_shares_an_eight_core_budget_with_one_core_games(threads) -> None:
    contexts = [0, 1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13]
    costs = [1, 1, 4, 4, 4, 1, 1, 1, 4, 1, 1, 1]
    threads.costs = dict(zip(contexts, costs))
    seen = []
    result = execute(contexts, tracked, workers=8, costs=costs, budget=8,
                     on_outcome=lambda outcome: seen.append(outcome.row.game_index))
    assert result.stopped is None and seen == contexts
    assert result == execute(contexts, play_one, workers=1)  # the same outcomes as serial play
    assert threads.peak <= 8 and threads.peak >= 5  # games overlapped, never past the budget
    assert threads.submitted == contexts  # games start in schedule order


def test_a_game_larger_than_the_budget_runs_alone(threads) -> None:
    contexts, costs = [0, 1, 2, 4], [1, 10, 1, 1]
    threads.costs = dict(zip(contexts, costs))
    result = execute(contexts, tracked, workers=4, costs=costs, budget=4)
    assert result.stopped is None and dict(threads.starts)[1] == 10


def test_budgeted_violations_and_errors_keep_the_prefix(threads) -> None:
    threads.costs = {index: 2 for index in range(12)}
    stopped = execute([0, 1, 3, 4], tracked, workers=4, costs=[1, 2, 2, 1], budget=4)
    assert stopped.stopped == "violation" and [o.row.game_index for o in stopped.outcomes] == [0, 1, 3]
    failed = execute([0, 1, 9, 2], tracked, workers=4, costs=[1, 2, 2, 1], budget=4, submission_window=2)
    assert failed.stopped == "aborted" and [o.row.game_index for o in failed.outcomes] == [0, 1]


def test_the_monitor_sees_the_budget_share_in_use(threads) -> None:
    threads.costs = {0: 4, 1: 4, 2: 1}
    seen = []

    class Monitor:
        def tick(self, *, running: int, queued: int, completed: int) -> None:
            seen.append((running, queued))

    execute([0, 1, 2], tracked, workers=8, costs=[4, 4, 1], budget=8, monitor=Monitor())
    assert seen[0] == (8, 1)  # two 4-core games fill all eight workers' cores; the 1-core game waits


def test_a_real_pool_plays_mixed_costs_like_serial_play() -> None:
    contexts = [0, 1, 2, 4, 5]
    assert execute(contexts, play_one, workers=4, costs=[4, 1, 1, 4, 1], budget=4) == execute(contexts, play_one, workers=1)


@pytest.mark.parametrize("costs, budget", [([1, 1], None), (None, 4), ([1], 4), ([1, 0], 4), ([1, 1], 0)])
def test_invalid_costs_are_refused(costs, budget) -> None:
    with pytest.raises(ValueError, match="costs"):
        execute([0, 1], play_one, workers=2, costs=costs, budget=budget)


# -- qualification -------------------------------------------------------------------------------------------------


def _play(seconds: float):
    def play(workers, indices):
        return seconds * len(indices), tuple(PlayedGame(index, seconds, DIGEST, 100) for index in indices)
    return play


def test_qualification_weighs_each_game_by_the_workers_it_holds() -> None:
    plan = {"games_total": 4, "cap": 4, "per_game_cores": 1, "placement": PLACEMENT, "cpu_count": 8, "host": "h",
            "machine": MACHINE}
    plain = plan_allocation(play=_play(2.0), **plan)
    same = plan_allocation(play=_play(2.0), game_cores=[1, 1, 1, 1], **plan)
    assert plain == same and plain.probe.busy_milli == 2000 * plain.probe.games
    weighted = plan_allocation(play=_play(2.0), game_cores=[1, 4, 1, 4], **plan)
    # The serial probe holds one worker whatever the game's cores (a larger game runs alone): unweighted.
    assert weighted.probe == plain.probe and weighted.projected_serial_seconds == plain.projected_serial_seconds


def test_a_rung_counts_a_large_game_as_several_workers_games() -> None:
    trial, _ = qualification._trial(_play(1.0), 4, (0, 1, 2), shares=(qualification.Fraction(1),
                                    qualification.Fraction(4), qualification.Fraction(8)))
    assert trial.busy_milli == 1000 + 4000 + 4000  # capped at the rung's four workers


@pytest.mark.parametrize("cores", [[1, 1, 1], [1, 0, 1, 1], [1, True, 1, 1], "1111"])
def test_game_cores_must_cover_the_schedule(cores) -> None:
    with pytest.raises(qualification.ThroughputError, match="game_cores"):
        plan_allocation(games_total=4, cap=4, per_game_cores=1, play=_play(1.0), placement=None, cpu_count=8,
                        host="h", machine=MACHINE, game_cores=cores)


# -- compatibility -------------------------------------------------------------------------------------------------


def _panel(**changes) -> TournamentConfig:
    identity = "0" * 64
    value = ladder(opponent_panel=["c12", "g115", "search"], evaluation_version="v1",
                   evaluation_engine_identity=identity, **changes)
    value["bots"] = [{**bot, "evaluation_identity": identity} for bot in value["bots"]]
    return TournamentConfig.from_json(value)


def test_blocks_compare_effective_resources() -> None:
    current = _panel()
    by_name = {bot.name: bot for bot in current.bots}
    assert "resources" not in bot_inputs(by_name["c12"], current)
    assert bot_inputs(by_name["search"], current)["resources"] == SEARCH
    # Declaring the board block is playing under it: compatible with a block that inherited it.
    declared = _panel(bots=[*ladder()["bots"][:1], sub("c12", BOARD), *ladder()["bots"][2:]])
    assert bot_inputs(declared.bots[1], declared) == bot_inputs(by_name["c12"], current)
    # The same entrant under the board block (before it declared four cores) is a different player.
    before = _panel(bots=[*ladder()["bots"][:3], sub("search")])
    assert bot_inputs(before.bots[3], before) != bot_inputs(by_name["search"], current)
    assert contract(before)["references"]["search"] != contract(current)["references"]["search"]
    assert contract(before)["references"]["c12"] == contract(current)["references"]["c12"]


def test_contracts_without_bot_blocks_keep_their_shape() -> None:
    plain = _panel(bots=[*ladder()["bots"][:3], sub("search")])
    references = contract(plain)["references"]
    assert all("resources" not in entry for entry in references.values())
    assert contract(plain)["resources"] == BOARD


def _manifest_tournament(config: TournamentConfig) -> dict:
    from spellbench.arena.ledger import parse_ledger
    from spellbench.arena.manifest import information_rules, manifest_body
    from spellbench.messages import EngineIdentity, EngineProfile, Rules
    from spellbench.run_secret import RunSecret
    from test_arena_manifest import PINNED, PROFILE_JSON, PROOF, RULES_JSON, SMALL
    from test_ledger import row

    entries = tuple(bot.registry_entry() for bot in config.bots)
    profile = EngineProfile.from_json(PROFILE_JSON)
    body = manifest_body(config=config, entries=entries, anchor_bot_id=entries[0].bot_id,
                         engine=EngineIdentity("engine", "1", None, "r", "p"), profile=profile, protocol_minor=0,
                         info_rules=information_rules(Rules.from_json(RULES_JSON), profile, []),
                         rows=parse_ledger([row()]), violations=[], scheduled=1, leaderboard_status="ok",
                         status="complete", benchmark_id="b", run_label="2026-10-01",
                         run_secret=RunSecret(bytes(range(32))), commitment_proof=PROOF, allocation=SMALL,
                         engine_files=PINNED)
    return body["tournament"]


def test_the_manifest_lists_effective_resources_only_with_bot_blocks() -> None:
    parsed = TournamentConfig.from_json(ladder())
    listed = _manifest_tournament(parsed)["bot_resources"]
    assert listed == {"uniform": BOARD, "c12": BOARD, "g115": BOARD, "search": SEARCH}
    plain = TournamentConfig.from_json(ladder(bots=[*ladder()["bots"][:3], sub("search")]))
    tournament = _manifest_tournament(plain)
    assert "bot_resources" not in tournament and tournament["resources"] == BOARD


# -- benchmark definitions -----------------------------------------------------------------------------------------


def test_a_definition_bot_carries_its_block_into_the_run_config() -> None:
    from spellbench.bench import definition
    from test_bench_definition import _value

    value = _value(core_accounting="sequential")
    value["bots"][1]["resources"] = SEARCH
    benchmark = definition.parse_benchmark(value)
    run = TournamentConfig.from_json(benchmark.tournament_config("benchmarks/x/runs/2026-11-08"))
    assert run.bot_resources(run.bots[1]) == Resources(**SEARCH) and run.per_game_cores() == 4
    value["bots"][1]["resources"] = {**SEARCH, "engine_cpus": 3}
    with pytest.raises(definition.BenchmarkError, match="engine_cpus"):
        definition.parse_benchmark(value)
