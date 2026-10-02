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

from ..arena import runner, snapshot, store
from ..arena.config import BotSpec, TournamentConfig
from ..arena.manifest import EngineFile
from .. import builtins
from . import definition, pinning

SNAPSHOTS_DIR = "snapshots"


def bot_files(spec: BotSpec) -> tuple[EngineFile, ...]:
    extra = (() if spec.checkpoint is None else (spec.checkpoint,)) + spec.evaluation_inputs
    command = spec.command if spec.type == "subprocess" else (sys.executable, str(Path(builtins.__file__)))
    return pinning.engine_files(command, extra=extra)


def full_config(benchmark: definition.Benchmark) -> TournamentConfig:
    return TournamentConfig.from_json(replace(benchmark, evaluation_targets=None).tournament_config("snapshot"))


def sources(directory: Path) -> list[snapshot.Source]:
    found = []
    for run_dir in definition.published_runs(directory):
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
    values = definition.placeholder_values(definition.placeholder_names(replace(benchmark, evaluation_targets=None)),
        definition.load_local_values(directory.parent), os.environ if environ is None else environ)
    executed = runner.executed_config(config, lambda text: definition.substitute(text, values))
    raw = definition._read_json(directory / definition.BENCHMARK_FILE)
    engine = pinning.engine_files(executed.engine_command, extra=executed.evaluation_engine_inputs)
    raw["evaluation_engine_identity"] = snapshot.files_identity(engine)
    by_name = {bot.name: bot for bot in executed.bots}
    for bot in raw["bots"]:
        spec = by_name[bot["name"]]
        bot["evaluation_identity"] = snapshot.files_identity(bot_files(spec))
    raw.pop("evaluation_targets", None)
    updated = definition.parse_benchmark(raw)
    desired = full_config(updated)
    selected = snapshot.select_blocks(desired, sources(directory), rated_only=not unrated)
    missing = set(snapshot.required_matchups(desired)) - selected.keys()
    panel = set(updated.opponent_panel)
    pending = {name for pair in missing for name in pair if name not in panel}
    if any(set(pair) <= panel for pair in missing):
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


def compose_benchmark(directory: Path, *, unrated: bool = False, date: str | None = None) -> Path:
    """Publish a source-backed snapshot; no game or inference executes."""
    directory = directory.resolve()
    benchmark = definition.load_benchmark(directory)
    config = full_config(benchmark)
    selected = snapshot.select_blocks(config, sources(directory), rated_only=not unrated)
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
    return snapshot.write_snapshot(target, config, selected, benchmark_id=benchmark.id, rated_only=not unrated)
