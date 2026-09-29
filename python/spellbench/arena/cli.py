"""The ``spellbench`` command line: run / validate / leaderboard / bench / site / bot.

- ``spellbench run CONFIG.json``: run a protocol v2 tournament under a
  fresh run secret and publish its artifacts into the config's
  ``tournament_dir``, then print its status and whether it is rated. No
  launch guard measures it yet, so it publishes as unrated (Decision 3).
- ``spellbench validate TOURNAMENT_DIR``: verify every manifest digest and
  re-derive the leaderboard (every rating) from the match ledger, comparing
  bytes.
- ``spellbench leaderboard TOURNAMENT_DIR``: print the leaderboard table.
- ``spellbench bench commit BENCHMARK_DIR --placement TEXT [--date
  YYYY-MM-DD]``: check the rated run's local values, then commit and push
  the next run's ``COMMITMENT.json`` and only then keep its secret, outside
  the repository (spec 11.6, Decision 9); record a third-party timestamp
  for that commit next.
- ``spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated
  [--date YYYY-MM-DD] [--placement TEXT])``: play the committed run NAME
  under its pushed commitment, with REF the commitment's third-party
  timestamp, or an unrated run under a fresh secret, into
  ``BENCHMARK_DIR/runs/<name>/``, then validate it.
- ``spellbench bench reveal BENCHMARK_DIR --run NAME [--reason REASON |
  --withheld]``: publish the secret of a committed run that stopped before
  its manifest (killed, or never started) as ``REVEAL.json``, with a reason
  from ``REVEAL_REASONS`` (default ``interrupted``), after moving the
  attempt's unpublished files beside the secret, then validate it. With
  ``--withheld``, publish a run whose secret was lost after its push as
  withheld (spec 11.6).
- ``spellbench bench rerun RUN_DIR [--game N]...``: replay a published
  run's games (all by default) from its revealed secret and report each one
  whose ledger row differs from the ledger's.
- ``spellbench site BENCHMARKS_DIR OUT_DIR``: validate every benchmark's
  latest run, then build the static site into OUT_DIR.
- ``spellbench bot NAME [--seed N]``: serve a builtin bot (protocol v2) as an
  agent-role subprocess (so configs can reference builtins over stdio too).
- ``spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...]
  [--games N] [--timeout-s SECONDS] -- ENGINE ARGV...``: hold an engine to the
  conformance checks (``spellbench.conformance``), one line per check; exit 0
  only when every check passes.

Exit codes: 0 success, 1 validation/run failure, 2 usage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

from .. import bot
from ..builtins import BUILTIN_VERSIONS, create_builtin_bot
from ..errors import ValidationError
from ..run_secret import RunSecret
from ..wire import strict_json_loads
from . import runner, store
from .throughput import Allocation
from .validate import REVEAL_REASONS, validate_tournament_dir

_USAGE = (
    "usage:\n"
    "  spellbench run CONFIG.json\n"
    "  spellbench validate TOURNAMENT_DIR\n"
    "  spellbench leaderboard TOURNAMENT_DIR\n"
    "  spellbench bench commit BENCHMARK_DIR --placement TEXT [--date YYYY-MM-DD]\n"
    "  spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated [--date YYYY-MM-DD]"
    " [--placement TEXT])\n"
    f"  spellbench bench reveal BENCHMARK_DIR --run NAME [--reason {'|'.join(REVEAL_REASONS)} | --withheld]\n"
    "  spellbench bench rerun RUN_DIR [--game N]...\n"
    "  spellbench site BENCHMARKS_DIR OUT_DIR\n"
    "  spellbench bot NAME [--seed N]\n"
    "  spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck CATALOG_ID ...] [--games N]"
    " [--timeout-s SECONDS] -- ENGINE [ARG ...]"
)
_BENCH_USAGE = (
    "usage:\n"
    "  spellbench bench commit BENCHMARK_DIR --placement TEXT [--date YYYY-MM-DD]\n"
    "  spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated [--date YYYY-MM-DD]"
    " [--placement TEXT])\n"
    f"  spellbench bench reveal BENCHMARK_DIR --run NAME [--reason {'|'.join(REVEAL_REASONS)} | --withheld]\n"
    "  spellbench bench rerun RUN_DIR [--game N]..."
)
_CONFORMANCE_USAGE = (
    "usage: spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck CATALOG_ID ...] [--games N]"
    " [--timeout-s SECONDS] -- ENGINE [ARG ...]"
)


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
    # A fresh secret per run (spec 11.6); no guard measures the run yet, so it is unrated (Decision 3). The
    # allocation records the cores each game declares, which cap the workers the runner starts (spec 11.4).
    allocation = Allocation.unmeasured(config.workers, per_game_cores=config.per_game_cores())
    summary = runner.run_tournament(config, run_secret=RunSecret.generate(), allocation=allocation)
    print(f"tournament published: {summary.tournament_dir}")
    _print_games(summary)
    print(f"status: {summary.status} ({'rated' if summary.rated else 'unrated'})")
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
    args: Sequence[str], *, values: Sequence[str] = (), flags: Sequence[str] = (), repeated: Sequence[str] = ()
) -> dict[str, Any] | None:
    """The options of a ``bench`` command, or None for a usage error: each of ``values`` takes one value and may
    appear once, each of ``repeated`` takes one value each time (a list), each of ``flags`` stands alone."""
    options: dict[str, Any] = {name: [] for name in repeated}
    index = 0
    while index < len(args):
        name = args[index]
        if name in flags and name not in options:
            options[name] = True
            index += 1
        elif name in repeated and index + 1 < len(args):
            options[name].append(args[index + 1])
            index += 2
        elif name in values and name not in options and index + 1 < len(args):
            options[name] = args[index + 1]
            index += 2
        else:
            return None
    return options


def _report_failures(failures: Sequence[str]) -> int:
    """Each validate failure on stderr and exit 1, or ``validate: OK`` and exit 0."""
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print("validate: OK")
    return 0


def _bench_commit(directory: Path, args: Sequence[str]) -> int | None:
    from ..bench.commit import commit_run

    options = _bench_options(args, values=("--placement", "--date"))
    if options is None or "--placement" not in options:
        return None
    # commit_run holds Ctrl+C until the secret is kept; this hold lasts until the operator has read what was
    # published, and a Ctrl+C held meanwhile then stops the command (spec 11.6, R3-31).
    with runner.deferred_interrupts():
        committed = commit_run(directory, placement=options["--placement"], date=options.get("--date"))
        print(f"commitment pushed, so it is public: {committed.run_dir / store.COMMITMENT_NAME} in commit "
              f"{committed.commit}")
        print(f"commitment: {committed.commitment}")
        print(f"run secret kept outside the repository: {committed.secret_path}")
        print(f"next: record a third-party timestamp for commit {committed.commit} (an issue comment, a signed "
              f"release, or an OpenTimestamps proof), then run: spellbench bench run {directory} --run "
              f"{committed.run_dir.name} --proof <the timestamp's link>")
    return 0


def _bench_run(directory: Path, args: Sequence[str]) -> int | None:
    from ..bench.run import run_benchmark

    options = _bench_options(args, values=("--run", "--proof", "--date", "--placement"), flags=("--unrated",))
    if options is None:
        return None
    committed = {"--run", "--proof"} <= set(options) and not {"--unrated", "--date", "--placement"} & set(options)
    unrated = "--unrated" in options and not {"--run", "--proof"} & set(options)
    if not (committed or unrated):
        return None
    result = run_benchmark(directory, run=options.get("--run"), proof=options.get("--proof"), unrated=unrated,
                           date=options.get("--date"), placement=options.get("--placement"))
    print(f"benchmark run published: {result.run_dir}")
    _print_games(result.summary)
    return _report_failures(result.failures)


def _bench_reveal(directory: Path, args: Sequence[str]) -> int | None:
    from ..bench import definition
    from ..bench.commit import attempt_dir, reveal_run, run_lock, withhold_run

    options = _bench_options(args, values=("--run", "--reason"), flags=("--withheld",))
    if options is None or "--run" not in options or {"--reason", "--withheld"} <= set(options):
        return None
    reason = options.get("--reason", "interrupted")
    if reason not in REVEAL_REASONS:
        return None
    name = options["--run"]
    definition.run_sort_key(name)  # a run name, never a path
    directory = directory.resolve()
    benchmark = definition.load_benchmark(directory)
    run_dir = directory / definition.RUNS_DIR / name
    # Only the invocation that owns the run reveals it, so a run another invocation is playing never is (R3-14).
    with run_lock(run_dir, benchmark_id=benchmark.id):
        attempt = attempt_dir(run_dir, benchmark_id=benchmark.id)
        before = set(attempt.iterdir()) if attempt.is_dir() else set()
        if "--withheld" in options:
            path = withhold_run(run_dir, benchmark_id=benchmark.id)
        else:
            path = reveal_run(run_dir, benchmark_id=benchmark.id, reason=reason)
        moved = sorted(entry.name for entry in (set(attempt.iterdir()) if attempt.is_dir() else set()) - before)
    if "--withheld" in options:
        print(f"WARNING: {benchmark.id} run {name} is published as withheld: its secret is lost, so nobody can check "
              "its commitment, and the site shows the run as withheld (spec 11.6)", file=sys.stderr)
        print(f"run withheld: {path}")
    else:
        print(f"run revealed: {path}")
    if moved:
        print(f"the unpublished files of the attempt ({', '.join(moved)}) moved outside the repository, to {attempt}")
    print("next: commit and push it; spec 11.6 publishes every committed run")
    return _report_failures(validate_tournament_dir(run_dir))


def _bench_rerun(directory: Path, args: Sequence[str]) -> int | None:
    from ..bench.run import rerun_games

    options = _bench_options(args, repeated=("--game",))
    if options is None or not all(value.isascii() and value.isdigit() for value in options["--game"]):
        return None
    mismatches = rerun_games(directory, games=[int(value) for value in options["--game"]] or None)
    for mismatch in mismatches:
        print(f"FAIL {mismatch}", file=sys.stderr)
    if mismatches:
        return 1
    print(f"OK {directory}: every replayed game matches its ledger row, field by field")
    return 0


def _cmd_bench(argv: Sequence[str]) -> int:
    # Imported inside each command so `spellbench bot`, spawned once per seat per game, starts without the
    # benchmark modules (and arena modules never import bench at module level, R3-4).
    commands = {"commit": _bench_commit, "run": _bench_run, "reveal": _bench_reveal, "rerun": _bench_rerun}
    if len(argv) < 2 or argv[0] not in commands or argv[1].startswith("--"):
        print(_BENCH_USAGE, file=sys.stderr)
        return 2
    code = commands[argv[0]](Path(argv[1]), argv[2:])
    if code is None:
        print(_BENCH_USAGE, file=sys.stderr)
        return 2
    return code


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
    return bot.serve(create_builtin_bot(name, seed=seed), name=name, version=BUILTIN_VERSIONS[name])


def _conformance_options(argv: Sequence[str]) -> tuple[list[str], dict[str, Any]] | None:
    """The engine command and the ``check_engine`` keywords of ``conformance engine``, or None for a usage error.

    Everything after the first ``--`` is the engine command, so it may hold ``--`` and option names itself. Only
    the syntax is checked here: ``check_engine`` refuses values out of range (``games`` below 1, say).
    """
    args = list(argv)
    if not args or args[0] != "engine" or "--" not in args:
        return None
    split = args.index("--")
    options, engine = args[1:split], args[split + 1 :]
    if not engine or len(options) % 2:
        return None
    keywords: dict[str, Any] = {"decks": []}
    for flag, value in zip(options[::2], options[1::2]):
        if flag == "--deck":
            keywords["decks"].append(value)
        elif flag == "--format" and "format" not in keywords:
            keywords["format"] = value
        elif flag == "--games" and "games" not in keywords:
            if not value.isascii() or not value.isdigit():
                return None
            keywords["games"] = int(value)
        elif flag == "--timeout-s" and "timeout_s" not in keywords:
            try:
                keywords["timeout_s"] = float(value)
            except ValueError:
                return None
        else:
            return None
    if "format" not in keywords or not keywords["decks"]:
        return None
    return engine, keywords


def _cmd_conformance(argv: Sequence[str]) -> int:
    # Imported here so `spellbench bot`, spawned once per seat per game, starts without the conformance runner.
    from .. import conformance

    parsed = _conformance_options(argv)
    if parsed is None:
        print(_CONFORMANCE_USAGE, file=sys.stderr)
        return 2
    engine, keywords = parsed
    try:
        report = conformance.check_engine(engine, **keywords)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(_CONFORMANCE_USAGE, file=sys.stderr)
        return 2
    # An engine's error messages reach the details: escape what stdout cannot encode (a Windows pipe is cp1252).
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(report.render().encode(encoding, "backslashreplace").decode(encoding))
    return 0 if report.passed else 1


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
        if command == "conformance":
            return _cmd_conformance(rest)
    except (runner.TournamentError, store.StoreError, ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
