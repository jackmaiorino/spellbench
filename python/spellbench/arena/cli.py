"""The ``spellbench`` command line: run / validate / leaderboard / bot.

- ``spellbench run CONFIG.json`` — run a tournament and publish artifacts
  into the config's ``tournament_dir``.
- ``spellbench validate TOURNAMENT_DIR`` — verify every manifest digest and
  re-derive the leaderboard (every rating) from the match ledger, comparing
  bytes.
- ``spellbench leaderboard TOURNAMENT_DIR`` — print the leaderboard table.
- ``spellbench bot NAME [--seed N]`` — serve a builtin bot as an agent-role
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
from . import leaderboard as leaderboard_mod
from . import registry as registry_mod
from . import runner, store
from .bots import BUILTIN_VERSIONS, create_builtin_bot

_USAGE = (
    "usage:\n"
    "  spellbench run CONFIG.json\n"
    "  spellbench validate TOURNAMENT_DIR\n"
    "  spellbench leaderboard TOURNAMENT_DIR\n"
    "  spellbench bot NAME [--seed N]"
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


def _cmd_run(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print("usage: spellbench run CONFIG.json", file=sys.stderr)
        return 2
    config = _load_config(Path(argv[0]))
    summary = runner.run_tournament(config)
    print(f"tournament published: {summary.tournament_dir}")
    print(
        f"games: {summary.games_total} total, {summary.games_rated} natural, "
        f"{summary.games_truncated} truncated, {summary.games_halted} halted, "
        f"{summary.games_forfeit} forfeit"
    )
    print(f"leaderboard status: {summary.leaderboard_status}")
    return 0


def validate_tournament_dir(directory: Path) -> list[str]:
    """Re-verify a published tournament; returns a list of failures (empty = OK).

    Checks (fail closed): manifest presence and schema, the sha256/byte count
    of every data file, ledger row schemas, and a byte-exact recomputation of
    ``leaderboard.json`` and ``LEADERBOARD.md`` from the ledger, registry,
    and config.
    """
    failures: list[str] = []
    if not store.is_published(directory):
        return [f"{directory} has no manifest.json (not a published tournament)"]
    try:
        manifest = store.read_json(directory / store.MANIFEST_NAME, schema=store.TOURNAMENT_SCHEMA)
        store.require_keys(
            manifest,
            ["schema", "tournament", "engine", "games", "leaderboard_status", "files"],
            "manifest",
        )
    except (store.StoreError, ValidationError) as exc:
        return [f"manifest: {exc}"]
    failures.extend(store.verify_file_digests(directory, manifest))
    try:
        config = runner.TournamentConfig.from_json(
            store.read_json(directory / store.CONFIG_NAME, schema=store.CONFIG_SCHEMA)
        )
        entries = registry_mod.read_registry(directory / store.REGISTRY_NAME)
        rows = store.parse_ledger(store.read_jsonl(directory / store.LEDGER_NAME, schema=store.LEDGER_SCHEMA))
        document, markdown = leaderboard_mod.build_leaderboard(
            rows,
            entries,
            anchor_bot_id=config.anchor_bot_id(),
            base_seed=config.base_seed,
            bootstrap_replicates=config.bootstrap_replicates,
            format=config.format,
        )
        expected_json = store.canonical_bytes(document) + b"\n"
        actual_json = (directory / store.LEADERBOARD_JSON_NAME).read_bytes()
        if actual_json != expected_json:
            failures.append("leaderboard.json does not match a recomputation from matches.jsonl")
        actual_md = (directory / store.LEADERBOARD_MD_NAME).read_bytes()
        if actual_md != markdown.encode("utf-8"):
            failures.append("LEADERBOARD.md does not match a recomputation from matches.jsonl")
        if manifest["leaderboard_status"] != document["status"]:
            failures.append("manifest leaderboard_status does not match the recomputed leaderboard")
    except (store.StoreError, ValidationError, runner.TournamentError, ValueError) as exc:
        failures.append(f"recomputation failed: {exc}")
    return failures


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
        if command == "bot":
            return _cmd_bot(rest)
    except (runner.TournamentError, store.StoreError, ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
