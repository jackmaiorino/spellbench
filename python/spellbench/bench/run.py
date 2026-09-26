"""Run a benchmark: resolve placeholders, play the round robin, validate.

The run lands in ``<benchmark_dir>/runs/<date>[-N]/``. Its recorded config
keeps the definition's ``${NAME}`` placeholders; processes start with the
values from the environment or ``benchmarks/local.json`` (the environment
wins). An unresolved placeholder stops the run before any process starts.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..arena import runner
from ..arena.validate import validate_tournament_dir
from . import definition


@dataclass(frozen=True)
class BenchmarkRun:
    run_dir: Path
    summary: runner.TournamentSummary
    failures: tuple[str, ...]  # validate failures; empty means OK


def run_benchmark(
    benchmark_dir: Path, *, date: str | None = None, environ: Mapping[str, str] | None = None
) -> BenchmarkRun:
    """Play one run of the benchmark in ``benchmark_dir`` and validate it.

    ``date`` (YYYY-MM-DD) defaults to today; ``environ`` to ``os.environ``.
    """
    # Absolute, so "." has a folder name and the parent holds local.json.
    benchmark_dir = Path(benchmark_dir).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    values = definition.placeholder_values(
        definition.placeholder_names(benchmark),
        definition.load_local_values(benchmark_dir.parent),
        os.environ if environ is None else environ,
    )
    if date is None:
        date = datetime.date.today().isoformat()
    name = definition.next_run_name(benchmark_dir, date)
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    summary = runner.run_tournament(
        config, resolve=lambda text: definition.substitute(text, values), output_dir=run_dir
    )
    return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))
