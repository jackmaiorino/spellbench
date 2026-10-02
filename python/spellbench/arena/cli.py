"""The ``spellbench`` command line: run / validate / leaderboard / bench / site / bot / conformance.

- ``spellbench run CONFIG.json [--placement TEXT]``: run a tournament and
  publish artifacts into the config's ``tournament_dir``; the throughput
  guard plans the launch (a substantial run needs the placement).
- ``spellbench validate TOURNAMENT_DIR``: verify every manifest digest and
  re-derive the leaderboard (every rating) from the match ledger, comparing
  bytes.
- ``spellbench leaderboard TOURNAMENT_DIR``: print the leaderboard table.
- ``spellbench bench commit BENCHMARK_DIR --placement TEXT [--date YYYY-MM-DD]``:
  commit and push a run's commitment, keeping the secret outside the
  repository.
- ``spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated
  [--date YYYY-MM-DD] [--placement TEXT])``: play a committed run with its
  proof, or a fresh unrated run, then validate it.
- ``spellbench bench reveal BENCHMARK_DIR --run NAME``: publish a committed
  run that died before its manifest as REVEAL.json with its secret.
- ``spellbench bench rerun RUN_DIR [--game N]...``: replay games from the
  revealed secret and report differences from the ledger.
- ``spellbench site BENCHMARKS_DIR OUT_DIR``: validate every benchmark's
  latest run, then build the static site into OUT_DIR.
- ``spellbench bot NAME [--seed N]``: serve a builtin bot as an agent-role
  subprocess (so configs can reference builtins over stdio too).
- ``spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...] [--games N] -- ARGV...``:
  run the engine conformance checks against an engine command.

Exit codes: 0 success, 1 validation/run failure, 2 usage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from ..bot import serve as serve_bot
from ..builtins import BUILTIN_VERSIONS, create_builtin_bot
from ..errors import ValidationError
from ..run_secret import RunSecret
from ..wire import strict_json_loads
from . import runner, store
from .throughput import ThroughputError
from .validate import validate_tournament_dir

_USAGE = (
    "usage:\n"
    "  spellbench run CONFIG.json [--placement TEXT]\n"
    "  spellbench validate TOURNAMENT_DIR\n"
    "  spellbench leaderboard TOURNAMENT_DIR\n"
    "  spellbench bench commit BENCHMARK_DIR --placement TEXT [--date YYYY-MM-DD]\n"
    "  spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated [--date YYYY-MM-DD] [--placement TEXT])\n"
    "  spellbench bench reveal BENCHMARK_DIR --run NAME\n"
    "  spellbench bench rerun RUN_DIR [--game N]...\n"
    "  spellbench site BENCHMARKS_DIR OUT_DIR\n"
    "  spellbench bot NAME [--seed N]\n"
    "  spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...] [--games N] -- ARGV..."
)
_BENCH_USAGE = (
    "usage:\n"
    "  spellbench bench commit BENCHMARK_DIR --placement TEXT [--date YYYY-MM-DD]\n"
    "  spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated [--date YYYY-MM-DD] [--placement TEXT])\n"
    "  spellbench bench reveal BENCHMARK_DIR --run NAME\n"
    "  spellbench bench rerun RUN_DIR [--game N]..."
)
_BENCH_COMMIT_USAGE = "usage: spellbench bench commit BENCHMARK_DIR --placement TEXT [--date YYYY-MM-DD]"
_BENCH_RUN_USAGE = (
    "usage: spellbench bench run BENCHMARK_DIR "
    "(--run NAME --proof REF | --unrated [--date YYYY-MM-DD] [--placement TEXT])"
)
_BENCH_REVEAL_USAGE = "usage: spellbench bench reveal BENCHMARK_DIR --run NAME"
_BENCH_RERUN_USAGE = "usage: spellbench bench rerun RUN_DIR [--game N]..."
_CONFORMANCE_USAGE = "usage: spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...] [--games N] -- ARGV..."


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


def _print_allocation(summary: runner.TournamentSummary) -> None:
    """The allocation line of ``run`` and ``bench run``: the guard's kind and the workers it chose."""
    allocation = summary.manifest["allocation"]
    print(f"allocation: {allocation['kind']} ({allocation['workers']} workers)")


def _cmd_run(argv: Sequence[str]) -> int:
    # The launch guard lives in the bench layer: imported here so `spellbench bot`, spawned once
    # per seat per game, starts without the benchmark modules.
    from ..bench.pinning import engine_files
    from ..bench.run import EVIDENCE_NAME, plan_for, run_files

    parsed = _bench_options(list(argv), ("placement",), ())
    if parsed is None:
        print("usage: spellbench run CONFIG.json [--placement TEXT]", file=sys.stderr)
        return 2
    positionals, options, _ = parsed
    if len(positionals) != 1:
        print("usage: spellbench run CONFIG.json [--placement TEXT]", file=sys.stderr)
        return 2
    config = _load_config(Path(positionals[0]))
    run_dir = Path(config.tournament_dir)
    allocation = plan_for(
        config,
        placement=options.get("placement"),
        evidence=run_dir.parent / EVIDENCE_NAME,
        volumes={"run_dir": run_dir, "pin_root": run_dir},  # a plain run pins nothing
        files=run_files(config),
    )
    summary = runner.run_tournament(
        config,
        run_secret=RunSecret.generate(),
        allocation=allocation,
        engine_files=engine_files(config.engine_command),
    )
    print(f"tournament published: {summary.tournament_dir}")
    _print_games(summary)
    print(f"status: {summary.status} ({'rated' if summary.rated else 'unrated'})")
    _print_allocation(summary)
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


def _bench_options(
    rest: list[str], valued: tuple[str, ...], flags: tuple[str, ...]
) -> tuple[list[str], dict[str, str], list[str]] | None:
    """Split positionals, ``--name value`` options and ``--flag`` switches; None on malformed input."""
    positionals: list[str] = []
    options: dict[str, str] = {}
    switches: list[str] = []
    while rest:
        item = rest.pop(0)
        if not item.startswith("--"):
            positionals.append(item)
            continue
        name = item[2:]
        if name in flags:
            if name in switches:
                return None
            switches.append(name)
        elif name in valued:
            if name in options or not rest:
                return None
            options[name] = rest.pop(0)
        else:
            return None
    return positionals, options, switches


def _cmd_bench_commit(rest: list[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the benchmark modules.
    from ..bench.commit import commit_run

    parsed = _bench_options(rest, ("placement", "date"), ())
    if parsed is None:
        print(_BENCH_COMMIT_USAGE, file=sys.stderr)
        return 2
    positionals, options, _ = parsed
    if len(positionals) != 1 or "placement" not in options:
        print(_BENCH_COMMIT_USAGE, file=sys.stderr)
        return 2
    committed = commit_run(Path(positionals[0]), placement=options["placement"], date=options.get("date"))
    print(f"commitment pushed: {committed.commit} ({committed.run_dir})")
    print(
        "record a third-party timestamp for the commit (an issue comment, a signed release, or an "
        "OpenTimestamps proof) and pass it as --proof to bench run"
    )
    return 0


def _cmd_bench_run(rest: list[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the benchmark modules.
    from ..bench.run import run_benchmark

    parsed = _bench_options(rest, ("run", "proof", "date", "placement"), ("unrated",))
    if parsed is None:
        print(_BENCH_RUN_USAGE, file=sys.stderr)
        return 2
    positionals, options, switches = parsed
    unrated = "unrated" in switches
    run = options.get("run")
    if len(positionals) != 1 or (run is None) == (not unrated):
        print(_BENCH_RUN_USAGE, file=sys.stderr)
        return 2
    if run is not None and ("proof" not in options or "date" in options or "placement" in options):
        print(_BENCH_RUN_USAGE, file=sys.stderr)
        return 2
    if unrated and "proof" in options:
        print(_BENCH_RUN_USAGE, file=sys.stderr)
        return 2
    result = run_benchmark(
        Path(positionals[0]),
        run=run,
        proof=options.get("proof"),
        unrated=unrated,
        date=options.get("date"),
        placement=options.get("placement"),
    )
    print(f"benchmark run published: {result.run_dir}")
    _print_games(result.summary)
    _print_allocation(result.summary)
    if result.failures:
        for failure in result.failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("validate: OK")
    return 0


def _cmd_bench_reveal(rest: list[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the benchmark modules.
    from ..bench import definition
    from ..bench.commit import reveal_run

    parsed = _bench_options(rest, ("run",), ())
    if parsed is None:
        print(_BENCH_REVEAL_USAGE, file=sys.stderr)
        return 2
    positionals, options, _ = parsed
    if len(positionals) != 1 or "run" not in options:
        print(_BENCH_REVEAL_USAGE, file=sys.stderr)
        return 2
    benchmark_dir = Path(positionals[0]).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    run_dir = benchmark_dir / definition.RUNS_DIR / options["run"]
    # A manual reveal publishes a run that died outside a lock-holding invocation: the category is "error".
    path = reveal_run(run_dir, benchmark_id=benchmark.id, reason="error")
    print(f"run revealed: {path}")
    return 0


def _cmd_bench_rerun(rest: list[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the benchmark modules.
    from ..bench.run import rerun_games

    games: list[int] = []
    positionals: list[str] = []
    while rest:
        item = rest.pop(0)
        if item == "--game":
            if not rest:
                print(_BENCH_RERUN_USAGE, file=sys.stderr)
                return 2
            try:
                game = int(rest.pop(0))
            except ValueError:
                print("--game must be an integer", file=sys.stderr)
                return 2
            if game < 0:
                print("--game must be nonnegative", file=sys.stderr)
                return 2
            games.append(game)
        elif item.startswith("--"):
            print(_BENCH_RERUN_USAGE, file=sys.stderr)
            return 2
        else:
            positionals.append(item)
    if len(positionals) != 1:
        print(_BENCH_RERUN_USAGE, file=sys.stderr)
        return 2
    mismatches = rerun_games(Path(positionals[0]), games=games or None)
    if mismatches:
        for mismatch in mismatches:
            print(f"FAIL {mismatch}", file=sys.stderr)
        return 1
    print(f"rerun OK: {positionals[0]}")
    return 0


def _cmd_bench(argv: Sequence[str]) -> int:
    if not argv:
        print(_BENCH_USAGE, file=sys.stderr)
        return 2
    command, rest = argv[0], list(argv[1:])
    if command == "commit":
        return _cmd_bench_commit(rest)
    if command == "run":
        return _cmd_bench_run(rest)
    if command == "reveal":
        return _cmd_bench_reveal(rest)
    if command == "rerun":
        return _cmd_bench_rerun(rest)
    print(_BENCH_USAGE, file=sys.stderr)
    return 2


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
    return serve_bot(
        create_builtin_bot(name, seed=seed),
        name=name,
        version=BUILTIN_VERSIONS[name],
    )


def _cmd_conformance(argv: Sequence[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the conformance stack.
    from ..conformance import check_engine

    if not argv or argv[0] != "engine":
        print(_CONFORMANCE_USAGE, file=sys.stderr)
        return 2
    format_id = None
    decks: list[str] = []
    games = 4
    engine_argv: list[str] | None = None
    rest = list(argv[1:])
    while rest:
        argument = rest.pop(0)
        if argument == "--":
            engine_argv = rest
            break
        if not rest:
            print(_CONFORMANCE_USAGE, file=sys.stderr)
            return 2
        value = rest.pop(0)
        if argument == "--format" and format_id is None:
            format_id = value
        elif argument == "--deck":
            decks.append(value)
        elif argument == "--games":
            try:
                games = int(value)
            except ValueError:
                print("--games must be an integer", file=sys.stderr)
                return 2
            if games < 1:
                print("--games must be at least 1", file=sys.stderr)
                return 2
        else:
            print(_CONFORMANCE_USAGE, file=sys.stderr)
            return 2
    if engine_argv is None or not engine_argv or format_id is None or not decks:
        print(_CONFORMANCE_USAGE, file=sys.stderr)
        return 2
    report = check_engine(engine_argv, format=format_id, decks=decks, games=games)
    print(report.render())
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_USAGE, file=sys.stderr)
        return 2
    command, rest = args[0], args[1:]
    # The launch guards' errors (neither is a ValueError) are reported like the other input errors (R3-29).
    errors: tuple[type[Exception], ...] = (
        runner.TournamentError,
        store.StoreError,
        ValidationError,
        ValueError,
        ThroughputError,
    )
    if command in ("run", "bench"):
        # Imported on the launch paths only, so `spellbench bot` starts without the benchmark modules.
        from ..bench.pinning import PinningError

        errors = (*errors, PinningError)
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
        if command == "conformance":
            return _cmd_conformance(rest)
    except errors as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
