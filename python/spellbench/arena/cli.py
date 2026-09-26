"""The ``spellbench`` command line: run / validate / leaderboard / bench / site / bot.

- ``spellbench run CONFIG.json``: run a tournament and publish artifacts
  into the config's ``tournament_dir``.
- ``spellbench validate TOURNAMENT_DIR``: verify every manifest digest and
  re-derive the leaderboard (every rating) from the match ledger, comparing
  bytes.
- ``spellbench leaderboard TOURNAMENT_DIR``: print the leaderboard table.
- ``spellbench bench run BENCHMARK_DIR [--date YYYY-MM-DD]``: run a
  benchmark into ``BENCHMARK_DIR/runs/<date>[-N]/`` (the date defaults to
  today), then validate the run.
- ``spellbench site BENCHMARKS_DIR OUT_DIR``: validate every benchmark's
  latest run, then build the static site into OUT_DIR.
- ``spellbench bot NAME [--seed N]``: serve a builtin bot as an agent-role
  subprocess (so configs can reference builtins over stdio too).

Exit codes: 0 success, 1 validation/run failure, 2 usage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from .. import agent_server
from ..errors import ValidationError
from ..wire import strict_json_loads
from . import runner, store
from .bots import BUILTIN_VERSIONS, create_builtin_bot
from .validate import validate_tournament_dir

_USAGE = (
    "usage:\n"
    "  spellbench run CONFIG.json\n"
    "  spellbench validate TOURNAMENT_DIR\n"
    "  spellbench leaderboard TOURNAMENT_DIR\n"
    "  spellbench bench run BENCHMARK_DIR [--date YYYY-MM-DD]\n"
    "  spellbench site BENCHMARKS_DIR OUT_DIR\n"
    "  spellbench bot NAME [--seed N]"
)
_BENCH_USAGE = "usage: spellbench bench run BENCHMARK_DIR [--date YYYY-MM-DD]"


def _load_config(path: Path) -> runner.TournamentConfig:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise runner.TournamentError(f"cannot read config {path}: {exc}") from exc
    try:
        value = strict_json_loads(raw)
    except Exception as exc:
        raise runner.TournamentError(f"config is not strict canonical JSON: {exc}") from exc
    return runner.TournamentConfig.from_json(value)


def _print_games(summary: runner.TournamentSummary) -> None:
    """The games and leaderboard-status lines of ``run`` and ``bench run``."""
    print(
        f"games: {summary.games_total} total, {summary.games_rated} rated, "
        f"{summary.games_truncated} truncated, {summary.games_halted} halted, "
        f"{summary.games_forfeit} forfeit"
    )
    print(f"leaderboard status: {summary.leaderboard_status}")


def _cmd_run(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print("usage: spellbench run CONFIG.json", file=sys.stderr)
        return 2
    config = _load_config(Path(argv[0]))
    summary = runner.run_tournament(config)
    print(f"tournament published: {summary.tournament_dir}")
    _print_games(summary)
    return 0


def _cmd_validate(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print("usage: spellbench validate TOURNAMENT_DIR", file=sys.stderr)
        return 2
    failures = validate_tournament_dir(Path(argv[0]))
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"OK {argv[0]}: digests verified, ratings re-derived from the ledger")
    return 0


def _cmd_leaderboard(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print("usage: spellbench leaderboard TOURNAMENT_DIR", file=sys.stderr)
        return 2
    path = Path(argv[0]) / store.LEADERBOARD_MD_NAME
    if not path.is_file():
        print(f"no leaderboard at {path} (run a tournament first)", file=sys.stderr)
        return 1
    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


def _cmd_bench(argv: Sequence[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the benchmark modules.
    from ..bench.run import run_benchmark

    if len(argv) < 2 or argv[0] != "run":
        print(_BENCH_USAGE, file=sys.stderr)
        return 2
    date = None
    rest = list(argv[2:])
    if rest:
        if len(rest) != 2 or rest[0] != "--date":
            print(_BENCH_USAGE, file=sys.stderr)
            return 2
        date = rest[1]
    result = run_benchmark(Path(argv[1]), date=date)
    print(f"benchmark run published: {result.run_dir}")
    _print_games(result.summary)
    if result.failures:
        for failure in result.failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("validate: OK")
    return 0


def _cmd_site(argv: Sequence[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the site modules.
    from ..site.build import build_site

    if len(argv) != 2:
        print("usage: spellbench site BENCHMARKS_DIR OUT_DIR", file=sys.stderr)
        return 2
    out_dir = Path(argv[1])
    for warning in build_site(Path(argv[0]), out_dir):
        print(f"warning: {warning}", file=sys.stderr)
    print(f"site built: {out_dir}")
    return 0


def _cmd_bot(argv: Sequence[str]) -> int:
    if not argv or argv[0] not in BUILTIN_VERSIONS:
        print(
            f"usage: spellbench bot NAME [--seed N] (builtins: {', '.join(sorted(BUILTIN_VERSIONS))})",
            file=sys.stderr,
        )
        return 2
    name = argv[0]
    seed = 0
    rest = list(argv[1:])
    if rest:
        if len(rest) != 2 or rest[0] != "--seed":
            print("usage: spellbench bot NAME [--seed N]", file=sys.stderr)
            return 2
        try:
            seed = int(rest[1])
        except ValueError:
            print("--seed must be an integer", file=sys.stderr)
            return 2
        if seed < 0:
            print("--seed must be nonnegative", file=sys.stderr)
            return 2
    return agent_server.serve(
        create_builtin_bot(name, seed=seed),
        bot_name=name,
        bot_version=BUILTIN_VERSIONS[name],
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_USAGE, file=sys.stderr)
        return 2
    command, rest = args[0], args[1:]
    try:
        if command == "run":
            return _cmd_run(rest)
        if command == "validate":
            return _cmd_validate(rest)
        if command == "leaderboard":
            return _cmd_leaderboard(rest)
        if command == "bench":
            return _cmd_bench(rest)
        if command == "site":
            return _cmd_site(rest)
        if command == "bot":
            return _cmd_bot(rest)
    except (runner.TournamentError, store.StoreError, ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
