"""Prepare incremental evaluations and compose their reference-panel leaderboards.

Preparation only hashes local files and reads results. Actual games still use
the ordinary committed, guarded benchmark launcher.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from ..arena import runner, snapshot, store, validity
from ..arena.config import BotSpec, TournamentConfig
from ..arena.manifest import EngineFile
from .. import builtins
from . import definition, pinning

SNAPSHOTS_DIR = "snapshots"


def bot_files(spec: BotSpec) -> tuple[EngineFile, ...]:
    extra = (() if spec.checkpoint is None else (spec.checkpoint,)) + spec.evaluation_inputs
    if spec.type == "subprocess":
        command = spec.command
    else:
        folder = Path(builtins.__file__).parent
        # The factory imports every builtin's version table. Fingerprint that
        # bundle and the shared agent transport, not just its initializer.
        command = (sys.executable, str(folder / f"{spec.name}.py"))
        extra = extra + tuple(sorted(folder.glob("*.py"))) + tuple(
            folder.parent / name for name in ("__init__.py", "bot.py", "wire.py", "errors.py"))
    return pinning.engine_files(command, extra=extra)


def full_config(benchmark: definition.Benchmark) -> TournamentConfig:
    return TournamentConfig.from_json(replace(benchmark, evaluation_targets=None, evaluation_matchups=None).tournament_config("snapshot"))


def sources(directory: Path) -> list[snapshot.Source]:
    found = []
    excluded = definition.excluded_run_names(directory)
    for run_dir in definition.published_runs(directory):
        if run_dir.name in excluded:
            continue  # kept published, never measured: listed in benchmark.excluded_runs, or its own
            # manifest records a failed validity unit (definition.excluded_runs)
        manifest = store.read_json(run_dir / store.MANIFEST_NAME)
        if manifest.get("schema") != store.TOURNAMENT_SCHEMA:
            continue  # frozen legacy runs cannot be transported to a v2 reference panel
        config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
        if not config.opponent_panel or config.evaluation_engine_identity is None:
            continue
        if manifest["run"]["status"] != "complete":
            continue
        source = snapshot.read_source(run_dir)
        if source.manifest["run"]["benchmark_id"] != directory.name:
            raise snapshot.SnapshotError(f"source {run_dir.name} belongs to another benchmark")
        found.append(source)
    return found


def failed_attempts(directory: Path, desired: TournamentConfig) -> dict[tuple[str, str], str]:
    """Each matchup that a committed run scheduled under ``desired``'s evaluation conditions, with the same two
    players, and that failed the board's validity unit: the matchup (sorted names) and the earliest such run.

    Such a run stays published and excluded. Its matchups are not played again under the same evaluation, and
    no later run's block of such a matchup is ever selected, so a later attempt cannot stand in for a failed one;
    a new evaluation (another ``evaluation_version``, engine or bot) is a reviewed change of the definition.
    Unrated runs are never rated, so they bind nothing here. A board without a validity unit has none.
    """
    if desired.validity is None:
        return {}
    expected = snapshot.contract(desired)
    current = {bot.name: bot for bot in desired.bots}
    attempts: dict[tuple[str, str], str] = {}
    for run_dir in definition.published_runs(directory):
        try:
            manifest = store.read_json(run_dir / store.MANIFEST_NAME)
        except store.StoreError:
            continue
        secrets = manifest.get("secrets")
        if (validity.verdict(manifest.get(validity.MANIFEST_KEY)) != "fail" or not isinstance(secrets, dict)
                or secrets.get("commitment_proof") is None):
            continue
        config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
        try:
            if snapshot.contract(config) != expected:
                continue
        except snapshot.SnapshotError:
            continue
        for first, second in config.scheduled_pairs():  # the run's schedule, listed or the round robin
            if first.name != second.name and all(
                    spec.name in current and snapshot.bot_inputs(spec, config)
                    == snapshot.bot_inputs(current[spec.name], desired) for spec in (first, second)):
                attempts.setdefault(tuple(sorted((first.name, second.name))), run_dir.name)  # oldest first
    return attempts


def _replay_refusal(again: list[tuple[str, str]], failed: Mapping[tuple[str, str], str]) -> str:
    return ("a committed run of this evaluation failed the board's validity unit and stays excluded: "
            + ", ".join(f"{a} vs {b} (run {failed[(a, b)]})" for a, b in again)
            + "; a failed evaluation is not replayed or topped up. To rate again, change the evaluation "
            "(a new evaluation_version, engine or bot) and review that definition")


def refuse_replay(directory: Path, benchmark: definition.Benchmark) -> None:
    """Refuse a committed run of ``benchmark`` (as its definition schedules it) that would play a matchup again
    which a committed run of the same evaluation already played and failed (:func:`failed_attempts`).

    ``bench commit`` and a committed ``bench run`` call this, so the rule does not depend on ``bench prepare``
    having been run again after the failure."""
    if not benchmark.opponent_panel or benchmark.validity is None:
        return
    failed = failed_attempts(directory, full_config(benchmark))
    scheduled = TournamentConfig.from_json(benchmark.tournament_config("check")).scheduled_pairs()
    again = sorted({tuple(sorted((first.name, second.name))) for first, second in scheduled} & failed.keys())
    if again:
        raise definition.BenchmarkError(_replay_refusal(again, failed))


def prepare_benchmark(directory: Path, *, unrated: bool = False,
                      environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Fingerprint the current inputs and write the missing targets into benchmark.json.

    Review and commit this definition before bench commit. No bot, engine or
    inference process starts here, including already evaluated LLM entrants.
    """
    directory = directory.resolve()
    pending = [path.name for path in definition.unpublished_runs(directory)
               if (path / store.COMMITMENT_NAME).exists() and not (path / "REVEAL.json").exists()]
    if pending:
        raise definition.BenchmarkError("pending committed runs freeze the definition; finish or reveal before "
                                        "bench prepare: " + ", ".join(pending))
    benchmark = definition.load_benchmark(directory)
    if not benchmark.opponent_panel:
        raise definition.BenchmarkError("bench prepare requires opponent_panel and evaluation_version in benchmark.json")
    config = full_config(benchmark)
    values = definition.placeholder_values(definition.placeholder_names(replace(benchmark, evaluation_targets=None, evaluation_matchups=None)),
        definition.load_local_values(directory.parent), os.environ if environ is None else environ)
    # The whole definition, not the previous shard: a new entrant's command is checked before any commitment.
    definition.check_ladder_arguments(replace(benchmark, evaluation_targets=None, evaluation_matchups=None), values)
    executed = runner.executed_config(config, lambda text: definition.substitute(text, values))
    raw = definition._read_json(directory / definition.BENCHMARK_FILE)
    engine = pinning.engine_files(executed.engine_command, extra=executed.evaluation_engine_inputs)
    raw["evaluation_engine_identity"] = snapshot.files_identity(engine)
    by_name = {bot.name: bot for bot in executed.bots}
    for bot in raw["bots"]:
        spec = by_name[bot["name"]]
        bot["evaluation_identity"] = snapshot.files_identity(bot_files(spec))
    raw.pop("evaluation_targets", None)
    raw.pop("evaluation_matchups", None)  # a shard names blocks of the previous targets
    updated = definition.parse_benchmark(raw)
    desired = full_config(updated)
    found = sources(directory)
    dropped = snapshot.dropped_ladder_blocks(desired, found)
    if dropped:
        raise definition.BenchmarkError("the ladder would drop rated rung matchups it has played: " + ", ".join(
            f"{a} vs {b}" for a, b in dropped) + "; append rungs at the top, or start a new benchmark version")
    failed = failed_attempts(directory, desired)
    selected = snapshot.select_blocks(desired, found, rated_only=not unrated, barred=failed)
    missing = set(snapshot.required_matchups(desired)) - selected.keys()
    again = sorted(pair for pair in missing if pair in failed)
    if again and not unrated:
        raise definition.BenchmarkError(_replay_refusal(again, failed))
    panel = set(updated.opponent_panel)
    pending = {name for pair in missing for name in pair if name not in panel}
    if updated.ladder is not None:
        # A ladder replays only its missing blocks: a new rung or entrant never restarts the other rungs' matchups.
        pending.update(name for pair in missing for name in pair)
        if missing:
            raw["evaluation_matchups"] = [list(pair) for pair in sorted(missing)]
    elif any(set(pair) <= panel for pair in missing):
        pending.update(panel)
    raw["evaluation_targets"] = sorted(pending)
    definition.parse_benchmark(raw)
    # The definition, not a hidden runtime choice, fixes the next formal schedule.
    store.write_bytes_atomic(directory / definition.BENCHMARK_FILE,
                             (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return tuple(raw["evaluation_targets"])


def published_snapshots(directory: Path) -> list[Path]:
    folder = directory / SNAPSHOTS_DIR
    if not folder.exists():
        return []
    result = [path for path in folder.iterdir() if path.is_dir() and (path / store.MANIFEST_NAME).is_file()]
    for path in result:
        snapshot.checked_label(path.name)
    return sorted(result, key=lambda p: definition.run_sort_key(p.name))


def pending_entrants(config: TournamentConfig, selected: Mapping[tuple[str, str], snapshot.Source]) -> tuple[str, ...]:
    """Entrants outside the panel with no compatible block yet; partly played entrants still fail."""
    played = {name for pair in selected for name in pair}
    fixed = set(config.opponent_panel) | {config.rating_anchor}
    return tuple(bot.name for bot in config.bots if bot.name not in played and bot.name not in fixed)


def unprepared_entrants(config: TournamentConfig) -> tuple[str, ...]:
    """Entrants outside the panel not yet fingerprinted; no block can match them."""
    fixed = set(config.opponent_panel) | {config.rating_anchor}
    return tuple(bot.name for bot in config.bots if bot.evaluation_identity is None and bot.name not in fixed)


def compose_benchmark(directory: Path, *, unrated: bool = False, date: str | None = None) -> Path:
    """Publish a source-backed snapshot; no game or inference executes.

    Roster entries with no compatible block at all, including entries not yet
    fingerprinted, are listed as pending and left out of the fit, so one
    unplayed entrant does not hold back the board.
    """
    directory = directory.resolve()
    benchmark = definition.load_benchmark(directory)
    config = full_config(benchmark)
    found = sources(directory)
    unprepared = unprepared_entrants(config)
    config = snapshot.without_entrants(config, unprepared)
    # A matchup that a committed run played and failed is never taken from a later run of the same evaluation.
    failed = failed_attempts(directory, config)
    selected = snapshot.select_blocks(config, found, rated_only=not unrated, barred=failed)
    unplayed = pending_entrants(config, selected)
    if unplayed:
        config = snapshot.without_entrants(config, unplayed)
        selected = snapshot.select_blocks(config, found, rated_only=not unrated, barred=failed)
    pending = unprepared + unplayed
    barred = sorted(pair for pair in set(snapshot.required_matchups(config)) - selected.keys() if pair in failed)
    if barred:
        raise snapshot.SnapshotError(
            "no rating is composed for " + ", ".join(f"{a} vs {b} (run {failed[(a, b)]})" for a, b in barred)
            + ": that run failed the board's validity unit, and no other run of the same evaluation stands in "
            "for it")
    date = datetime.date.today().isoformat() if date is None else snapshot.checked_label(date)
    if len(date) != 10:
        raise definition.BenchmarkError("snapshot date must be YYYY-MM-DD")
    number = 1
    while True:
        label = date if number == 1 else f"{date}-{number}"
        target = directory / SNAPSHOTS_DIR / label
        if not target.exists():
            break
        number += 1
    return snapshot.write_snapshot(target, config, selected, benchmark_id=benchmark.id, rated_only=not unrated,
                                   pending=pending)
