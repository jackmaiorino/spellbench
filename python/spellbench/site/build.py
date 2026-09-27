"""Build the static benchmark site from committed, validated runs.

``build_site(benchmarks_dir, out_dir)`` loads every ``<benchmarks_dir>/<id>/``
definition, re-validates each benchmark's latest published run with the
checks of ``spellbench validate``, and refuses to build if any run fails. It
then computes the Hero table, builds the view-model dicts that ``render``
turns into pages (the contract in ``docs/design/2026-09-26-benchmark-site-plan.md``),
and writes ``index.html``, ``join.html``, ``method.html``,
``b/<id>/index.html``, and byte copies of each run's files under
``b/<id>/run/`` for download.

- Every page and file is planned in memory before anything is written, so a
  refused build leaves ``out_dir`` as it was. The build replaces ``out_dir``
  only when it is absent, empty, or an earlier build (it holds
  ``SITE_MARKER``).
- A benchmark page shows its run: bots, numbers, decks, format and engine
  come from the run's files. Titles and bot display text come from the
  current ``benchmark.json``. The build compares the arena config that
  ``benchmark.json`` gives now with the one the run recorded and warns on
  any difference; a bot whose arena entry changed (or that the definition
  no longer lists) shows its registry name and owner instead of display
  text. Display text itself is not recorded in runs, so every leaderboard
  row also shows the rated registry name and version.
- Output is deterministic: benchmarks and tags in sorted order, no
  timestamps, no local paths in any page, Unix line endings on every OS.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import models
from ..arena import registry, runner, store
from ..arena.validate import validate_tournament_dir
from ..bench import definition
from . import hero, render

REPO_URL = "https://github.com/jackmaiorino/spellbench"
SITE_MARKER = ".spellbench-site"
RUN_FILES = (store.MANIFEST_NAME, *store.DATA_FILE_NAMES)

_SITE = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": REPO_URL}
_MARKER_TEXT = "spellbench site output; rebuilt by spellbench site\n"
_GAME_COUNTS = ("total", "rated", "forfeit", "truncated", "halted")
_ANCHOR_WITHOUT_PAIRS = "reference_id has no games"  # the fit's error when the anchor has no complete pair


class SiteError(ValueError):
    """The site cannot be built; nothing was written."""


@dataclass(frozen=True)
class _Run:
    """A benchmark's latest published run, read after it passed validation."""

    name: str
    files: dict[str, bytes]  # RUN_FILES by name, copied for download
    config: runner.TournamentConfig
    engine: dict[str, Any]  # the engine identity from manifest.json
    owners: dict[str, str]  # registry owner by bot name
    board: dict[str, Any]  # leaderboard.json


def build_site(benchmarks_dir: Path, out_dir: Path) -> list[str]:
    """Validate every benchmark's latest run, then write the site into ``out_dir``.

    Returns the warnings: unfinished runs, benchmarks without a published
    run, definitions changed since their run, benchmarks left out of the
    Hero chart, and Hero rows that average different registry bots under
    one name. Raises SiteError before anything is written when a
    definition is invalid, a latest run fails validation, or ``out_dir`` is
    not a site build (or is or contains ``benchmarks_dir``).
    """
    if not benchmarks_dir.is_dir():
        raise SiteError(f"no benchmarks directory at {benchmarks_dir}")
    target, source = out_dir.resolve(), benchmarks_dir.resolve()
    if target == source or target in source.parents:
        raise SiteError(f"refusing to overwrite {out_dir}: it is or contains the benchmarks directory")
    warnings: list[str] = []
    benchmarks, latest = _load_benchmarks(benchmarks_dir, warnings)
    proposed = _load_proposed(benchmarks_dir)
    failures = [
        f"{bench_id} runs/{run_dir.name}: {failure}"
        for bench_id, run_dir in latest.items()
        for failure in validate_tournament_dir(run_dir)
    ]
    if failures:
        raise SiteError(
            "refusing to build: every latest run must pass validation\n"
            + "\n".join(f"  {failure}" for failure in failures)
        )
    runs = {bench_id: _read_run(run_dir) for bench_id, run_dir in latest.items()}
    stale: dict[str, frozenset[str]] = {}  # per benchmark: bots shown by registry identity
    for benchmark in benchmarks:
        run = runs.get(benchmark.id)
        if run is None:
            continue
        differences, stale[benchmark.id] = _drift(benchmark, run)
        if differences:
            warnings.append(
                f"{benchmark.id}: benchmark.json changed since run {run.name} (differs in {', '.join(differences)}); "
                "rerun to publish the change"
            )
    table = hero.hero_table([(bench_id, run.board) for bench_id, run in runs.items()])
    warnings.extend(table.warnings)
    warnings.extend(_mixed_hero_bots(runs, table.benchmark_ids))

    info = {"site": _SITE}
    files = {
        SITE_MARKER: _MARKER_TEXT.encode("utf-8"),  # first: a partial write can still be replaced
        "index.html": render.render_home(_home_view(benchmarks, runs, stale, table, proposed)).encode("utf-8"),
        "join.html": render.render_join(info).encode("utf-8"),
        "method.html": render.render_method(info).encode("utf-8"),
    }
    for benchmark in benchmarks:
        run = runs.get(benchmark.id)
        if run is None:
            continue
        page = render.render_benchmark(_benchmark_view(benchmark, run, stale[benchmark.id]))
        files[f"b/{benchmark.id}/index.html"] = page.encode("utf-8")
        for name in RUN_FILES:
            files[f"b/{benchmark.id}/run/{name}"] = run.files[name]
    _write_site(out_dir, files)
    return warnings


# ---------------- reading the benchmarks ----------------


def _load_benchmarks(
    benchmarks_dir: Path, warnings: list[str]
) -> tuple[list[definition.Benchmark], dict[str, Path]]:
    """Every definition in id order, and the latest published run of each benchmark that has one."""
    benchmarks: list[definition.Benchmark] = []
    latest: dict[str, Path] = {}
    for folder in definition.find_benchmarks(benchmarks_dir):
        try:
            benchmark = definition.load_benchmark(folder)
        except definition.BenchmarkError as exc:
            raise SiteError(str(exc)) from exc
        try:
            runner.TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
        except runner.TournamentError as exc:
            raise SiteError(f"{benchmark.id}: {exc}") from exc
        benchmarks.append(benchmark)
        run_dir = definition.latest_run_dir(folder)
        showing = "no run" if run_dir is None else f"runs/{run_dir.name}"
        for unfinished in definition.unpublished_runs(folder):
            warnings.append(
                f"{benchmark.id}: runs/{unfinished.name} has no manifest.json (an unfinished run); showing {showing}"
            )
        if run_dir is None:
            warnings.append(f"{benchmark.id}: no published run yet")
        else:
            latest[benchmark.id] = run_dir
    return benchmarks, latest


def _load_proposed(benchmarks_dir: Path) -> tuple[definition.ProposedBenchmark, ...]:
    try:
        return definition.load_proposed(benchmarks_dir)
    except definition.BenchmarkError as exc:
        raise SiteError(str(exc)) from exc


def _read_run(run_dir: Path) -> _Run:
    """The files and documents of a run that passed validation."""
    manifest = store.read_json(run_dir / store.MANIFEST_NAME, schema=store.TOURNAMENT_SCHEMA)
    config = store.read_json(run_dir / store.CONFIG_NAME, schema=store.CONFIG_SCHEMA)
    entries = registry.read_registry(run_dir / store.REGISTRY_NAME)
    return _Run(
        name=run_dir.name,
        files={name: (run_dir / name).read_bytes() for name in RUN_FILES},
        config=runner.TournamentConfig.from_json(config),
        engine=models.EngineIdentity.from_json(manifest["engine"], "manifest.engine").to_json(),
        owners={entry.name: entry.owner for entry in entries},
        board=store.read_json(run_dir / store.LEADERBOARD_JSON_NAME, schema=store.LEADERBOARD_SCHEMA),
    )


def _drift(benchmark: definition.Benchmark, run: _Run) -> tuple[list[str], frozenset[str]]:
    """How the arena config ``benchmark.json`` gives now differs from the one ``run`` recorded.

    Both sides are canonical ``TournamentConfig`` JSON for the run's
    directory. Returns what differs, for the warning ("bot names", then
    "bot '<name>'" for each changed entry or "bot order", then the other
    top-level fields), and the bots whose entry differs or that the
    definition no longer lists: their display text may describe another
    bot, so the site shows them by registry name and owner.
    """
    recorded = run.config.to_json()
    current = runner.TournamentConfig.from_json(benchmark.tournament_config(f"runs/{run.name}")).to_json()
    if _same(recorded, current):
        return [], frozenset()
    was = {bot["name"]: bot for bot in recorded["bots"]}
    now = {bot["name"]: bot for bot in current["bots"]}
    stale = frozenset(name for name, entry in was.items() if name not in now or not _same(entry, now[name]))
    differences = ["bot names"] if was.keys() != now.keys() else []
    differences += [f"bot {name!r}" for name in sorted(stale) if name in now]
    if not differences and not _same(recorded["bots"], current["bots"]):
        differences.append("bot order")
    differences += sorted(
        field
        for field in recorded.keys() | current.keys()
        if field != "bots" and not _same(recorded.get(field), current.get(field))
    )
    return differences, stale


def _same(first: Any, second: Any) -> bool:
    """Whether two JSON values are the same canonical JSON (so ``1`` and ``true`` differ)."""
    return store.canonical_bytes(first) == store.canonical_bytes(second)


def _mixed_hero_bots(runs: Mapping[str, _Run], benchmark_ids: Sequence[str]) -> list[str]:
    """A warning for each Hero row that averages different registry bots (bot ids) under one name."""
    by_name: dict[str, dict[str, list[str]]] = {}  # name -> bot id -> benchmarks
    for bench_id in benchmark_ids:
        board = runs[bench_id].board
        for row in board["rows"]:
            if row["rated"] and row["bot_id"] != board["anchor"]["bot_id"]:
                by_name.setdefault(row["name"], {}).setdefault(row["bot_id"], []).append(bench_id)
    return [
        f"Hero chart: {name!r} averages different registry bots (different bot ids) across benchmarks "
        + ", ".join(sorted(bench_id for bench_ids in by_id.values() for bench_id in bench_ids))
        for name, by_id in sorted(by_name.items())
        if len(by_id) > 1
    ]


# ---------------- view models ----------------


def _home_view(
    benchmarks: Sequence[definition.Benchmark],
    runs: Mapping[str, _Run],
    stale: Mapping[str, frozenset[str]],
    table: hero.HeroTable,
    proposed: Sequence[definition.ProposedBenchmark],
) -> dict[str, Any]:
    """The view of ``index.html``: the Hero chart, a card per benchmark, the proposed cards."""
    return {
        "site": _SITE,
        "hero": {
            "rows": [_hero_row(row, benchmarks, runs, stale) for row in table.rows],
            "benchmark_count": len(table.benchmark_ids),
            "approximate": any(row.approximate for row in table.rows),
        },
        "benchmarks": [_card(benchmark, runs.get(benchmark.id)) for benchmark in benchmarks],
        "proposed": [{"title": item.title, "summary": item.summary, "needs": item.needs} for item in proposed],
    }


def _hero_row(
    row: hero.HeroRow,
    benchmarks: Sequence[definition.Benchmark],
    runs: Mapping[str, _Run],
    stale: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    """A Hero row, labelled by the first benchmark (id order) whose definition lists the bot.

    As on that benchmark's page, a bot whose arena entry changed since its run
    (in ``stale``) shows its registry name and owner instead.
    """
    label, author = row.name, ""
    for benchmark in benchmarks:
        bot = benchmark.bot(row.name)
        if bot is None:
            continue
        if row.name in stale.get(benchmark.id, frozenset()):
            label, author = row.name, runs[benchmark.id].owners[row.name]
        else:
            label, author = bot.display.label, bot.display.author
        break
    return {
        "name": row.name,
        "label": label,
        "author": author,
        "score": row.score,
        "lower": row.lower,
        "upper": row.upper,
        "approximate": row.approximate,
        "reference": row.reference,
        "bound": row.bound,
        "chips": [{"benchmark_id": chip.benchmark_id, "margin": chip.margin, "bound": chip.bound} for chip in row.chips],
    }


def _card(benchmark: definition.Benchmark, run: _Run | None) -> dict[str, Any]:
    """A benchmark card: the run's counts when there is a run, the definition's otherwise."""
    card = {
        "id": benchmark.id,
        "title": benchmark.title,
        "summary": benchmark.summary,
        "engine_name": benchmark.engine_name,
    }
    if run is None:
        card.update(
            deck_count=len(benchmark.deck_pool), bot_count=len(benchmark.bots), games=None, run_name=None, href=None
        )
    else:
        card.update(
            deck_count=len(_deck_labels(run.config)),
            bot_count=len(run.config.bots),
            games=run.board["games"]["total"],
            run_name=run.name,
            href=f"b/{benchmark.id}/index.html",
        )
    return card


def _benchmark_view(benchmark: definition.Benchmark, run: _Run, stale: frozenset[str]) -> dict[str, Any]:
    """The view of ``b/<id>/index.html``: the run's numbers with the definition's text.

    The bots in ``stale`` (their arena entry changed since the run, see
    ``_drift``) are shown by registry name and owner.
    """
    board, config = run.board, run.config
    display = {
        name: _display_of(None if name in stale else benchmark.bot(name), name, owner)
        for name, owner in run.owners.items()
    }
    anchor_id = board["anchor"]["bot_id"]
    overall = _leader_rows(board["rows"], anchor_id, display)
    tags = sorted({tag for row in overall for tag in row["tags"]})
    return {
        "site": _SITE,
        "id": benchmark.id,
        "title": benchmark.title,
        "summary": benchmark.summary,
        "format": config.format,
        "engine": run.engine,
        "decks": _deck_labels(config),
        "pairs_per_deck": config.pairs_per_matchup // (1 if config.deck_pool is None else len(config.deck_pool)),
        "run": {
            "name": run.name,
            "games": {key: board["games"][key] for key in _GAME_COUNTS},
            "manifest_sha256": store.sha256_hex(run.files[store.MANIFEST_NAME]),
            "files": [{"name": name, "href": f"run/{name}", "bytes": len(run.files[name])} for name in RUN_FILES],
            # uv run: a fresh clone has no spellbench on PATH until uv installs the project
            "validate_command": f"uv run spellbench validate benchmarks/{benchmark.id}/runs/{run.name}",
        },
        "overall": overall,
        "deck_tables": [_deck_table(deck_slice, anchor_id, display) for deck_slice in board["slices"]["deck"]],
        "style_tables": [{"tag": tag, "rows": [row for row in overall if tag in row["tags"]]} for tag in tags],
        "grid": _grid(board["rows"], board["matchups"], display),
    }


def _display_of(bot: definition.BenchmarkBot | None, name: str, owner: str) -> dict[str, Any]:
    """How the site shows bot ``name``: ``bot``'s display, else the registry name and owner."""
    if bot is None:
        return {"label": name, "author": owner, "description": "", "url": None}
    display = bot.display
    return {"label": display.label, "author": display.author, "description": display.description, "url": display.url}


def _leader_rows(
    rows: Sequence[Mapping[str, Any]], anchor_id: str, display: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Leaderboard rows (overall or one deck's), in leaderboard order.

    ``version`` is the rated bot's registry version. ``bound`` marks a rating
    that is only a bound (``hero.rating_bound``); the anchor's rating is
    fixed, so it never is.
    """
    views = []
    for row in rows:
        anchor = row["bot_id"] == anchor_id
        views.append(
            {
                "rank": row["rank"],
                "name": row["name"],
                "version": row["version"],
                **display[row["name"]],  # label, author, description, url
                "tags": list(row["training_style_tags"]),
                "anchor": anchor,
                "elo_milli": row["elo_milli"],
                "ci_elo_milli": row["ci95_elo_milli"],
                "bound": None if anchor else hero.rating_bound(row),
                "wins": row["wins"],
                "draws": row["draws"],
                "losses": row["losses"],
                "games": row["games"],
                "forfeits": row["forfeit_losses"],
            }
        )
    return views


def _deck_table(
    deck_slice: Mapping[str, Any], anchor_id: str, display: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """One deck's table from ``slices.deck``, with a reason for readers when it is not rated.

    The fit's own error text stays in ``fit_error``; the page shows it on hover.
    """
    status, fit_error = deck_slice["status"], deck_slice["fit_error"]
    if status == "ok":
        reason = None
    elif status == "no_rated_games":
        reason = "no rated games"
    elif fit_error == _ANCHOR_WITHOUT_PAIRS:
        reason = "the random bot has no complete pair on this deck"
    else:
        reason = "the ratings could not be fitted"
    return {
        "label": deck_slice["label"],
        "status": status,
        "reason": reason,
        "fit_error": fit_error,
        "rows": _leader_rows(deck_slice["rows"], anchor_id, display),
    }


def _grid(
    rows: Sequence[Mapping[str, Any]], matchups: Sequence[Mapping[str, Any]], display: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Each overall bot's share of the points against each other, over complete pairs.

    A matchup stores bot ``a``'s share as ``a_score``; bot ``b``'s is its
    complement. A cell carries the matchup's rated ``games`` and the
    ``complete_pairs`` the share is computed over. The diagonal, a pair of
    bots without a matchup, and a matchup without complete pairs
    (``a_score`` null) have no cell.
    """
    by_bots = {frozenset((matchup["a_bot_id"], matchup["b_bot_id"])): matchup for matchup in matchups}
    cells: list[list[dict[str, Any] | None]] = []
    for i, row in enumerate(rows):
        line: list[dict[str, Any] | None] = []
        for j, other in enumerate(rows):
            matchup = by_bots.get(frozenset((row["bot_id"], other["bot_id"]))) if i != j else None
            if matchup is None or matchup["a_score"] is None:
                line.append(None)
                continue
            num, den = matchup["a_score"]["num"], matchup["a_score"]["den"]
            share = num / den if matchup["a_bot_id"] == row["bot_id"] else (den - num) / den
            line.append({"score": share, "games": matchup["games"], "complete_pairs": matchup["complete_pairs"]})
        cells.append(line)
    return {
        "names": [row["name"] for row in rows],
        "labels": [display[row["name"]]["label"] for row in rows],
        "cells": cells,
    }


def _deck_labels(config: runner.TournamentConfig) -> list[str]:
    """The run's decks: the pool in order, or its one fixed pairing ("<p0>" or "<p0> vs <p1>")."""
    if config.deck_pool is not None:
        return [_deck_label(deck) for deck in config.deck_pool]
    assert config.decks is not None
    first, second = config.decks
    return [_deck_label(first) if first == second else f"{_deck_label(first)} vs {_deck_label(second)}"]


def _deck_label(deck: models.Deck) -> str:
    """A deck's catalog id; a decklist gets the leaderboard's label for it."""
    if deck.catalog_id is not None:
        return deck.catalog_id
    return "decklist " + store.sha256_hex(store.canonical_bytes(deck.to_json()))[:12]


# ---------------- writing ----------------


def _write_site(out_dir: Path, files: Mapping[str, bytes]) -> None:
    """Replace ``out_dir`` with ``files``, unless it is something other than a site build."""
    if out_dir.exists():
        if not out_dir.is_dir() or (any(out_dir.iterdir()) and not (out_dir / SITE_MARKER).is_file()):
            raise SiteError(f"refusing to overwrite {out_dir}: it is not a spellbench site build")
        shutil.rmtree(out_dir)
    for name, data in files.items():
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
