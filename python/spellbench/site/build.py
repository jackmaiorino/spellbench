"""Build the static benchmark site from committed, validated runs.

``build_site(benchmarks_dir, out_dir)`` loads every ``<benchmarks_dir>/<id>/``
definition and finds each benchmark's board run (:func:`board_run_dir`): its
latest published run that is a rated protocol v2 run or a protocol v1 run
(Decisions 1 and 3). It re-validates the board run, every run published
after it, and every run revealed without a manifest with the checks of
``spellbench validate``, and refuses to build if any fails. It then computes
the Hero table, builds the view-model dicts that ``render`` turns into pages
(the contract in ``render``'s docstring), and writes ``index.html``,
``models.html``, ``join.html``, ``method.html``, ``b/<id>/index.html``, and
byte copies of the board run's published files under ``b/<id>/run/`` for
download.

- Every page and file is planned in memory before anything is written, so a
  refused build leaves ``out_dir`` as it was. The build replaces ``out_dir``
  only when it is absent, empty, or an earlier build (it holds
  ``SITE_MARKER``).
- A benchmark page and its Hero chips show the board run: bots, numbers,
  decks, format and engine come from the run's files. Titles and bot display
  text come from the current ``benchmark.json``. Display text itself is not
  recorded in runs, so every leaderboard row also shows the rated registry
  name and version.
- Runs published after the board run are unrated protocol v2 runs (aborted,
  invalid, or complete without everything Decision 3 asks): the page lists
  them with their status, and the build warns. Every committed run is
  published (spec 11.6), so the page lists two more kinds of run directory,
  unrated, when newer than the board run: a run revealed without a manifest
  (``REVEAL.json``, validated like a published run; status ``aborted``) and a
  pending commitment (``COMMITMENT.json`` alone, whose contents are left to
  its run's validation and to CI's run-history check; status ``pending``).
  A withheld run (a ``REVEAL.json`` without its secret, which was lost) is
  listed whatever its age, in a note of its own, since none of its games can
  be checked. Anything else without a manifest is an unfinished run: the
  build warns, and the page leaves it out.
- A protocol v2 board run carries its protocol, fairness verdict (with the
  isolation record's ``self_reported`` flag), information rules, the halts
  and truncations attributed to each bot, and its commitment and revealed
  secret. The build compares the arena config that ``benchmark.json`` gives
  now with the one the run recorded and warns on any difference; a bot whose
  arena entry changed (or that the definition no longer lists) shows its
  registry name and owner instead of display text.
- A protocol v1 board run is read with ``legacy_v1.read_v1_run`` and labelled
  protocol v1 on its page, in its Hero chips and on the Models page. Its
  config cannot be compared with a v2 definition, so there is no drift check:
  the build warns that the benchmark should rerun on protocol v2, and a bot
  shows its display text when the definition lists its name, its registry
  name and owner otherwise.
- Output is deterministic: benchmarks and tags in sorted order, no
  timestamps, no local paths in any page, Unix line endings on every OS.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .._schema import OBSERVATION_FLAGS
from ..arena import legacy_v1, registry, store
from ..arena.config import TournamentConfig
from ..arena.ledger import LedgerRow, parse_ledger
from ..arena.validate import validate_tournament_dir
from ..bench import definition
from ..messages import ENGINE_DEFAULT_KEYS, EngineIdentity
from . import hero, render

REPO_URL = "https://github.com/jackmaiorino/spellbench"
SITE_MARKER = ".spellbench-site"
# The published files of a board run, copied for download: a v2 run's manifest hashes its commitment too.
RUN_FILES = (store.MANIFEST_NAME, store.COMMITMENT_NAME, *store.DATA_FILE_NAMES)
LEGACY_RUN_FILES = (store.MANIFEST_NAME, *store.DATA_FILE_NAMES)

_SITE = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": REPO_URL}
_MARKER_TEXT = "spellbench site output; rebuilt by spellbench site\n"
_GAME_COUNTS = ("total", "rated", "forfeit", "truncated", "halted")
_ANCHOR_WITHOUT_PAIRS = "reference_id has no games"  # the fit's error when the anchor has no complete pair
_ANCHOR_ELO_MILLI = 1_000_000  # the anchor's fixed Elo in milli-Elo (hero.py)
_V1_PROTOCOL = "spellbench/v1"
# A committed run that failed before its manifest publishes this file (Decision 9); validate before listing it.
_REVEAL_NAME = "REVEAL.json"
# Each engine default (spec 7.6) by its Setup term; a null default means the bots are asked.
_ENGINE_DEFAULT_TERMS = {
    "trigger_order": "Trigger order",
    "replacement_order": "Replacement order",
    "combat_damage_assignment": "Combat damage assignment",
    "mana_payment": "Mana payment",
}
assert tuple(_ENGINE_DEFAULT_TERMS) == ENGINE_DEFAULT_KEYS


class SiteError(ValueError):
    """The site cannot be built; nothing was written."""


@dataclass(frozen=True)
class _Entry:
    """A bot's arena entry as its run recorded it, for a Models section the definition does not describe."""

    type: str
    engine: str
    tags: tuple[str, ...]
    version: str


@dataclass(frozen=True)
class _Listing:
    """A benchmark's run directories: the board run, the published runs after it, and the unpublished runs."""

    board: Path | None
    newer: tuple[Path, ...]
    unpublished: tuple[Path, ...]

    def checked(self) -> tuple[Path, ...]:
        """The board run, newer manifests and every revealed or withheld publication."""
        reveals = tuple(path for path in self.unpublished if (path / _REVEAL_NAME).is_file())
        return ((self.board,) if self.board is not None else ()) + self.newer + reveals


@dataclass(frozen=True)
class _Run:
    """A benchmark's board run, read after it passed validation."""

    name: str
    legacy: bool  # a protocol v1 run (Decision 1)
    files: dict[str, bytes]  # RUN_FILES (LEGACY_RUN_FILES for a v1 run) by name, copied for download
    format: str
    decks: tuple[str, ...]  # the pool in order, or the one fixed pairing ("<p0>" or "<p0> vs <p1>")
    pairs_per_deck: int
    entries: dict[str, _Entry]  # each configured bot's recorded entry by name, in config order
    engine: dict[str, Any]  # the engine identity from manifest.json
    owners: dict[str, str]  # registry owner by bot name
    board: dict[str, Any]  # leaderboard.json
    config: TournamentConfig | None  # the recorded v2 config, for the drift check; None for a v1 run
    manifest: dict[str, Any] | None  # the v2 manifest; None for a v1 run
    newer_runs: tuple[dict[str, Any], ...]  # the runs published after this one: name, status, rated
    withheld_runs: tuple[dict[str, Any], ...] = ()


def build_site(benchmarks_dir: Path, out_dir: Path) -> list[str]:
    """Validate every benchmark's board run and the runs after it, then write the site into ``out_dir``.

    Returns the warnings: unfinished runs, runs revealed after an abort, runs
    published after the board run (unrated), benchmarks without a published
    run, protocol v1 board runs, definitions changed since their v2 board
    run, benchmarks left out of the Hero chart, and Hero rows that average
    different registry bots under one name. Raises SiteError before anything
    is written when a definition is invalid, a board run or a run after it
    fails validation, or ``out_dir`` is not a site build (or is or contains
    ``benchmarks_dir``).
    """
    if not benchmarks_dir.is_dir():
        raise SiteError(f"no benchmarks directory at {benchmarks_dir}")
    target, source = out_dir.resolve(), benchmarks_dir.resolve()
    if target == source or target in source.parents:
        raise SiteError(f"refusing to overwrite {out_dir}: it is or contains the benchmarks directory")
    benchmarks, listings = _load_benchmarks(benchmarks_dir)
    proposed = _load_proposed(benchmarks_dir)
    failures = [
        f"{bench_id} runs/{run_dir.name}: {failure}"
        for bench_id, listing in listings.items()
        for run_dir in listing.checked()
        for failure in validate_tournament_dir(run_dir)
    ]
    if failures:
        raise SiteError(
            "refusing to build: every board run, and every run published after it, must pass validation\n"
            + "\n".join(f"  {failure}" for failure in failures)
        )
    newer = {bench_id: _other_runs(listing) for bench_id, listing in listings.items()}
    withheld = {bench_id: tuple(_newer_run(path) for path in listing.unpublished
                if (path / _REVEAL_NAME).is_file() and _newer_run(path)["status"] == "withheld")
                for bench_id, listing in listings.items()}
    runs = {
        bench_id: replace(_read_run(listing.board, newer[bench_id]), withheld_runs=withheld[bench_id])
        for bench_id, listing in listings.items()
        if listing.board is not None
    }
    warnings: list[str] = []
    stale: dict[str, frozenset[str]] = {}  # per benchmark: bots shown by registry identity
    for benchmark in benchmarks:
        run = runs.get(benchmark.id)
        warnings.extend(_listing_warnings(benchmark.id, listings[benchmark.id], newer[benchmark.id], run))
        if run is not None:
            board_warnings, stale[benchmark.id] = _board_run_check(benchmark, run)
            warnings.extend(board_warnings)
    table = hero.hero_table([(bench_id, run.board) for bench_id, run in runs.items()])
    warnings.extend(table.warnings)
    warnings.extend(_mixed_hero_bots(runs, table.benchmark_ids))

    info = {"site": _SITE}
    files = {
        SITE_MARKER: _MARKER_TEXT.encode("utf-8"),  # first: a partial write can still be replaced
        "index.html": render.render_home(_home_view(benchmarks, runs, stale, table, proposed,
            publications={name: newer[name] + withheld[name] for name in listings})).encode("utf-8"),
        "models.html": render.render_models(_models_view(benchmarks, runs, stale)).encode("utf-8"),
        "join.html": render.render_join(info).encode("utf-8"),
        "method.html": render.render_method(info).encode("utf-8"),
    }
    for benchmark in benchmarks:
        run = runs.get(benchmark.id)
        if run is None:
            continue
        page = render.render_benchmark(_benchmark_view(benchmark, run, stale[benchmark.id]))
        files[f"b/{benchmark.id}/index.html"] = page.encode("utf-8")
        for name, data in run.files.items():
            files[f"b/{benchmark.id}/run/{name}"] = data
    _write_site(out_dir, files)
    return warnings


def board_run_dir(benchmark_dir: Path) -> Path | None:
    """The run a benchmark's page and Hero chips show: its latest published run that is a rated protocol v2
    run or a protocol v1 run, or None (Decisions 1 and 3).

    An unrated v2 run never replaces the board run, so until a benchmark has a
    rated v2 run its latest v1 run stays on the board. The choice reads each
    manifest's ``schema`` and ``run.rated`` without validating the run:
    ``build_site`` then validates the board run and every run after it, so a
    manifest claiming what its files do not show refuses the build.
    """
    return _board_of(definition.published_runs(benchmark_dir))


def _board_of(published: Sequence[Path]) -> Path | None:
    """The latest of ``published`` (oldest first) that is a rated v2 run or a v1 run."""
    for run_dir in reversed(published):
        try:
            manifest = store.read_json(run_dir / store.MANIFEST_NAME)
        except store.StoreError:
            continue  # unreadable: never the board run; validation names it when it is newer than the board run
        if not isinstance(manifest, dict):
            continue
        schema, run = manifest.get("schema"), manifest.get("run")
        if schema == legacy_v1.TOURNAMENT_SCHEMA_V1:
            return run_dir
        if schema == store.TOURNAMENT_SCHEMA and isinstance(run, dict) and run.get("rated") is True:
            return run_dir
    return None


# ---------------- reading the benchmarks ----------------


def _load_benchmarks(benchmarks_dir: Path) -> tuple[list[definition.Benchmark], dict[str, _Listing]]:
    """Every definition in id order, and each benchmark's run directories (``_Listing``)."""
    benchmarks: list[definition.Benchmark] = []
    listings: dict[str, _Listing] = {}
    for folder in definition.find_benchmarks(benchmarks_dir):
        try:
            benchmark = definition.load_benchmark(folder)  # the arena accepts its config (Task 37)
        except definition.BenchmarkError as exc:
            raise SiteError(str(exc)) from exc
        benchmarks.append(benchmark)
        published = definition.published_runs(folder)
        board = _board_of(published)
        newer = published if board is None else published[published.index(board) + 1 :]
        listings[benchmark.id] = _Listing(board, tuple(newer), tuple(definition.unpublished_runs(folder)))
    return benchmarks, listings


def _listing_warnings(
    bench_id: str, listing: _Listing, newer_runs: Sequence[Mapping[str, Any]], run: _Run | None
) -> list[str]:
    """A warning for each run directory that is not the board run, and one when nothing is published.

    A directory without a manifest was revealed after an abort (it holds
    ``REVEAL.json``, by name alone) or is unfinished; a run published after
    the board run is unrated.
    """
    showing = "no run" if run is None else f"runs/{run.name}"
    warnings = []
    for run_dir in listing.unpublished:
        if (run_dir / _REVEAL_NAME).is_file():
            if _newer_run(run_dir)["status"] == "withheld":
                detail = f"was withheld after its secret was lost ({_REVEAL_NAME}); no games can be verified"
            else:
                detail = f"was revealed after an abort ({_REVEAL_NAME}, no {store.MANIFEST_NAME})"
        else:
            detail = f"has no {store.MANIFEST_NAME} (an unfinished run)"
        warnings.append(f"{bench_id}: runs/{run_dir.name} {detail}; showing {showing}")
    warnings += [
        f"{bench_id}: runs/{item['name']} is {item['status']} and not rated; showing {showing}" for item in newer_runs
    ]
    if listing.board is None and not listing.newer:
        warnings.append(f"{bench_id}: no published run yet")
    return warnings


def _board_run_check(benchmark: definition.Benchmark, run: _Run) -> tuple[list[str], frozenset[str]]:
    """What to warn about the board run, and its bots the pages show by registry name and owner.

    A v2 run gets the drift check (``_drift``). A v1 config cannot be compared
    with a v2 definition, so a v1 run's bots match the definition by name
    alone, and the warning asks for a rerun on protocol v2 (Decision 1).
    """
    if run.legacy:
        warning = (
            f"{benchmark.id}: the board run is protocol v1; rerun on protocol v2 to publish the current definition"
        )
        return [warning], frozenset(name for name in run.owners if benchmark.bot(name) is None)
    differences, stale = _drift(benchmark, run)
    if not differences:
        return [], stale
    warning = (
        f"{benchmark.id}: benchmark.json changed since run {run.name} (differs in {', '.join(differences)}); "
        "rerun to publish the change"
    )
    return [warning], stale


def _load_proposed(benchmarks_dir: Path) -> tuple[definition.ProposedBenchmark, ...]:
    try:
        return definition.load_proposed(benchmarks_dir)
    except definition.BenchmarkError as exc:
        raise SiteError(str(exc)) from exc


def _other_runs(listing: _Listing) -> tuple[dict[str, Any], ...]:
    """Newer unrated publications and pending commitments; lost secrets have their own note at every age."""
    records = [_newer_run(path) for path in listing.newer]
    for path in listing.unpublished:
        if not ((path / _REVEAL_NAME).is_file() or (path / store.COMMITMENT_NAME).is_file()):
            continue
        record = _newer_run(path)
        if record["status"] != "withheld" and (listing.board is None or
                definition.run_sort_key(path.name) > definition.run_sort_key(listing.board.name)):
            records.append(record)
    return tuple(sorted(records, key=lambda record: definition.run_sort_key(record["name"])))


def _newer_run(run_dir: Path) -> dict[str, Any]:
    """A non-board run's public status; revealed records passed validation first."""
    if not (run_dir / store.MANIFEST_NAME).is_file():
        if (run_dir / _REVEAL_NAME).is_file():
            record = store.read_json(run_dir / _REVEAL_NAME)
            status = "withheld" if record["run_secret"] is None else "aborted"
        else:
            status = "pending"
        return {"name": run_dir.name, "status": status, "rated": False}
    manifest = store.read_json(run_dir / store.MANIFEST_NAME, schema=store.TOURNAMENT_SCHEMA)
    return {"name": run_dir.name, "status": manifest["run"]["status"], "rated": manifest["run"]["rated"]}


def _read_run(run_dir: Path, newer_runs: tuple[dict[str, Any], ...]) -> _Run:
    """The files and documents of a board run that passed validation, v1 or v2 by its manifest's schema."""
    manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    if manifest["schema"] == legacy_v1.TOURNAMENT_SCHEMA_V1:
        return _read_legacy_run(run_dir, newer_runs)
    config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME, schema=store.CONFIG_SCHEMA))
    rows = parse_ledger(store.read_jsonl(run_dir / store.LEDGER_NAME, schema=store.LEDGER_SCHEMA))
    return _Run(
        name=run_dir.name,
        legacy=False,
        files={name: (run_dir / name).read_bytes() for name in RUN_FILES},
        format=config.format,
        decks=_deck_labels(config, rows),
        pairs_per_deck=config.pairs_per_matchup // (1 if config.deck_pool is None else len(config.deck_pool)),
        entries={spec.name: _entry(spec) for spec in config.bots},
        engine=EngineIdentity.from_json(manifest["engine"], "manifest.engine").to_json(),
        owners={entry.name: entry.owner for entry in registry.read_registry(run_dir / store.REGISTRY_NAME)},
        board=store.read_json(run_dir / store.LEADERBOARD_JSON_NAME, schema=store.LEADERBOARD_SCHEMA),
        config=config,
        manifest=manifest,
        newer_runs=newer_runs,
    )


def _read_legacy_run(run_dir: Path, newer_runs: tuple[dict[str, Any], ...]) -> _Run:
    """A protocol v1 board run, read with the frozen reader (Decision 1)."""
    legacy = legacy_v1.read_v1_run(run_dir)
    return _Run(
        name=legacy.name,
        legacy=True,
        files={name: (run_dir / name).read_bytes() for name in LEGACY_RUN_FILES},
        format=legacy.format,
        decks=legacy.deck_labels,
        pairs_per_deck=legacy.pairs_per_deck,
        entries={spec.name: _entry(spec) for spec in legacy_v1.LegacyConfig.from_json(legacy.config).bots},
        engine=dict(legacy.engine),
        owners=dict(legacy.owners),
        board=legacy.board,
        config=None,
        manifest=None,
        newer_runs=newer_runs,
    )


def _entry(spec: Any) -> _Entry:
    """A recorded bot entry: an arena ``BotSpec``, or ``legacy_v1``'s for a v1 run."""
    return _Entry(type=spec.type, engine=spec.engine, tags=tuple(spec.training_style_tags), version=spec.version)


def _deck_labels(config: TournamentConfig, rows: Sequence[LedgerRow]) -> tuple[str, ...]:
    """The run's decks by the ledger's deck names (R3-25): the pool in order, or its one fixed pairing ("<p0>" or
    "<p0> vs <p1>"), as the leaderboard's deck tables label them.

    A catalog deck's name is the one the engine publishes, which the ledger
    records; an inline deck's is its configured name, which the ledger repeats.
    """
    names = {deck.catalog_id: deck.name for row in rows for deck in row.decks if deck.catalog_id is not None}

    def label(spec: Any) -> str:
        return spec.name if spec.catalog_id is None else names.get(spec.catalog_id, spec.catalog_id)

    if config.deck_pool is not None:
        return tuple(label(deck) for deck in config.deck_pool)
    assert config.decks is not None
    first, second = config.decks
    return (label(first) if first == second else f"{label(first)} vs {label(second)}",)


def _drift(benchmark: definition.Benchmark, run: _Run) -> tuple[list[str], frozenset[str]]:
    """How the arena config ``benchmark.json`` gives now differs from the one v2 ``run`` recorded.

    Both sides are canonical ``TournamentConfig`` JSON for the run's
    directory. Returns what differs, for the warning ("bot names", then
    "bot '<name>'" for each changed entry or "bot order", then the other
    top-level fields), and the bots whose entry differs or that the
    definition no longer lists: their display text may describe another
    bot, so the site shows them by registry name and owner.
    """
    assert run.config is not None
    recorded = run.config.to_json()
    current = TournamentConfig.from_json(benchmark.tournament_config(f"runs/{run.name}")).to_json()
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
    *, publications: Mapping[str, Sequence[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """The view of ``index.html``: the Hero chart, a card per benchmark, the proposed cards."""
    return {
        "site": _SITE,
        "hero": {
            "rows": [_hero_row(row, benchmarks, runs, stale) for row in table.rows],
            "benchmark_count": len(table.benchmark_ids),
            "approximate": any(row.approximate for row in table.rows),
        },
        "benchmarks": [{**_card(benchmark, runs.get(benchmark.id)),
                        "other_runs": list((publications or {}).get(benchmark.id, ()))} for benchmark in benchmarks],
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
    (in ``stale``) shows its registry name and owner instead. Each chip says
    whether its benchmark's board run is protocol v1 (Decision 1, R3-20).
    """
    label, author, description = row.name, "", ""
    for benchmark in benchmarks:
        bot = benchmark.bot(row.name)
        if bot is None:
            continue
        if row.name in stale.get(benchmark.id, frozenset()):
            label, author = row.name, runs[benchmark.id].owners[row.name]
        else:
            label, author, description = bot.display.label, bot.display.author, bot.display.description
        break
    return {
        "name": row.name,
        "label": label,
        "author": author,
        "description": description,
        "score": row.score,
        "lower": row.lower,
        "upper": row.upper,
        "approximate": row.approximate,
        "reference": row.reference,
        "bound": row.bound,
        "chips": [
            {
                "benchmark_id": chip.benchmark_id,
                "margin": chip.margin,
                "bound": chip.bound,
                "legacy": runs[chip.benchmark_id].legacy,
            }
            for chip in row.chips
        ],
    }


def _models_view(
    benchmarks: Sequence[definition.Benchmark],
    runs: Mapping[str, _Run],
    stale: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    """The view of ``models.html``: one section per bot, linked from every bot name on the site.

    A bot's text comes from the first benchmark (id order) whose definition
    lists it. A bot whose arena entry changed since that benchmark's run (in
    ``stale``), or that no definition lists, shows its registry name and owner
    with the recorded entry's facts instead, as on the benchmark pages.
    Ratings come from each benchmark's board run leaderboard, each saying
    whether that run is protocol v1. Sections order submitted models by best
    rating first, the anchor and builtins after them, ties by name.
    """
    sections: dict[str, dict[str, Any]] = {}
    for benchmark in benchmarks:
        for bot in benchmark.bots:
            if bot.name in sections:
                continue
            if bot.name in stale.get(benchmark.id, frozenset()):
                sections[bot.name] = _recorded_section(bot.name, runs[benchmark.id])
            else:
                sections[bot.name] = _definition_section(bot)
    for benchmark in benchmarks:
        run = runs.get(benchmark.id)
        if run is None:
            continue
        for row in run.board["rows"]:
            if row["name"] not in sections:
                sections[row["name"]] = _recorded_section(row["name"], run)
    for benchmark in benchmarks:
        run = runs.get(benchmark.id)
        if run is None:
            continue
        anchor_id = run.board["anchor"]["bot_id"]
        for row in run.board["rows"]:
            sections[row["name"]]["benchmarks"].append(_model_rating(benchmark.id, row, anchor_id, run.legacy))
    return {"site": _SITE, "models": sorted(sections.values(), key=_model_order)}


def _definition_section(bot: definition.BenchmarkBot) -> dict[str, Any]:
    """A models section from the definition: the display text and the arena entry's facts."""
    display, entry = bot.display, bot.entry
    return {
        "name": bot.name,
        "label": display.label,
        "author": display.author,
        "description": display.description,
        "url": display.url,
        "kind": _model_kind(entry["type"]),
        "engine": entry.get("engine"),
        "tags": list(entry.get("training_style_tags", ())),
        "version": entry["version"],
        "benchmarks": [],
    }


def _recorded_section(name: str, run: _Run) -> dict[str, Any]:
    """A models section from a run's records, for a bot the definition no longer describes."""
    entry = run.entries[name]
    return {
        "name": name,
        "label": name,
        "author": run.owners[name],
        "description": "",
        "url": None,
        "kind": _model_kind(entry.type),
        "engine": None if entry.engine == "any" else entry.engine,
        "tags": list(entry.tags),
        "version": entry.version,
        "benchmarks": [],
    }


def _model_kind(bot_type: str) -> str:
    """The facts line's first item: builtins are the reference bots, everything else a submitted model."""
    return "builtin reference bot" if bot_type == "builtin" else "submitted model"


def _model_rating(bench_id: str, row: Mapping[str, Any], anchor_id: str, legacy: bool) -> dict[str, Any]:
    """One benchmark line of a models section: Elo above random and its interval, or "reference" for the anchor.

    ``legacy`` says the rating comes from a protocol v1 board run (Decision 1).
    """
    anchor = row["bot_id"] == anchor_id
    elo, interval = row["elo_milli"], row["ci95_elo_milli"]
    return {
        "id": bench_id,
        "href": f"b/{bench_id}/index.html",
        "reference": anchor,
        "margin": None if elo is None else (elo - _ANCHOR_ELO_MILLI) / 1000,
        "lower": None if interval is None else (interval[0] - _ANCHOR_ELO_MILLI) / 1000,
        "upper": None if interval is None else (interval[1] - _ANCHOR_ELO_MILLI) / 1000,
        "bound": None if anchor else hero.rating_bound(row),
        "legacy": legacy,
    }


def _model_order(section: Mapping[str, Any]) -> tuple[bool, float, str]:
    """Submitted models by best rating first, then the anchor and builtins; ties by name."""
    margins = [row["margin"] for row in section["benchmarks"] if row["margin"] is not None]
    best = max(margins, default=float("-inf"))
    return (section["kind"] == "builtin reference bot", -best, section["name"])


def _card(benchmark: definition.Benchmark, run: _Run | None) -> dict[str, Any]:
    """A benchmark card: the board run's counts when there is one, the definition's otherwise."""
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
            deck_count=len(run.decks),
            bot_count=len(run.entries),
            games=run.board["games"]["total"],
            run_name=run.name,
            href=f"b/{benchmark.id}/index.html",
        )
    return card


def _benchmark_view(benchmark: definition.Benchmark, run: _Run, stale: frozenset[str]) -> dict[str, Any]:
    """The view of ``b/<id>/index.html``: the board run's numbers with the definition's text.

    The bots in ``stale`` (a v2 run's bots whose arena entry changed since the
    run, see ``_drift``, or a v1 run's bots the definition does not name) are
    shown by registry name and owner. Every protocol key of the renderer's
    contract is set, for a v1 run too (``_protocol_view``).
    """
    board = run.board
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
        "format": run.format,
        "engine": run.engine,
        "decks": list(run.decks),
        "pairs_per_deck": run.pairs_per_deck,
        **_protocol_view(run, display),
        "run": {
            "name": run.name,
            "games": {key: board["games"][key] for key in _GAME_COUNTS},
            "manifest_sha256": store.sha256_hex(run.files[store.MANIFEST_NAME]),
            "files": [{"name": name, "href": f"run/{name}", "bytes": len(data)} for name, data in run.files.items()],
            # uv run: a fresh clone has no spellbench on PATH until uv installs the project
            "validate_command": f"uv run spellbench validate benchmarks/{benchmark.id}/runs/{run.name}",
            **_run_secrets(run),
        },
        "overall": overall,
        "deck_tables": [_deck_table(deck_slice, anchor_id, display) for deck_slice in board["slices"]["deck"]],
        "style_tables": [{"tag": tag, "rows": [row for row in overall if tag in row["tags"]]} for tag in tags],
        "grid": _grid(board["rows"], board["matchups"], display),
    }


def _protocol_view(run: _Run, display: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The page's protocol keys: a v2 run's protocol, fairness verdict, information rules and attribution, or a v1
    run's legacy values; and the runs published after it, for both."""
    newer_runs = [dict(item) for item in run.newer_runs]
    if run.legacy:
        return {
            "protocol": {"name": _V1_PROTOCOL, "minor": None},
            "legacy": True,
            "fairness": None,
            "setup_rules": [],
            "attribution": [],
            "newer_runs": newer_runs,
            "withheld_runs": [dict(item) for item in run.withheld_runs],
        }
    manifest, config = run.manifest, run.config
    assert manifest is not None and config is not None
    validator = manifest["validator"]
    return {
        "protocol": {"name": manifest["protocol"]["name"], "minor": manifest["protocol"]["minor"]},
        "legacy": False,
        "fairness": {
            "label": manifest["information_rules"]["fairness_label"],
            "verdict": validator["verdict"],
            "decisions_checked": validator["decisions_checked"],
            "violations": len(validator["violations"]),
            "self_reported": manifest["isolation"]["self_reported"],  # spec 11.7, R3-9
        },
        "setup_rules": _setup_rules(manifest["information_rules"], config),
        "attribution": [
            {
                "name": row["name"],
                "label": display[row["name"]]["label"],
                "games": row["games_played"],
                "halts": row["halts_attributed"],
                "truncations": row["truncations_attributed"],
            }
            for row in run.board["rows"]
        ],
        "newer_runs": newer_runs,
        "withheld_runs": [dict(item) for item in run.withheld_runs],
    }


def _run_secrets(run: _Run) -> dict[str, Any]:
    """The run box's status, rated flag, commitment and revealed secret (spec 11.6).

    A v1 run predates the commitment: it stays on the board as it was
    published, a complete run without a secret to show (Decision 1).
    """
    if run.legacy:
        return {"status": "complete", "rated": True, "commitment": None, "run_secret": None}
    assert run.manifest is not None
    state, secrets = run.manifest["run"], run.manifest["secrets"]
    return {
        "status": state["status"],
        "rated": state["rated"],
        "commitment": secrets["commitment"],
        "run_secret": secrets["run_secret"],
    }


def _setup_rules(info: Mapping[str, Any], config: TournamentConfig) -> list[dict[str, str]]:
    """The information rules and the engine facts that change play, as the manifest records them (spec 12.2).

    The mulligan says when ``auto`` resolved to ``none`` because the engine
    has no London mulligan; every engine default is shown (spec 7.6), a null
    one as offered to the bots; the observation fields are the optional ones
    the engine provides (spec 6.9), in the spec's order.
    """
    rules = info["rules"]
    mulligan = rules["mulligan"]
    if mulligan == "none" and config.rules.mulligan == "auto":
        mulligan = "none (the engine offers no mulligans)"
    starting = rules["starting_player"]
    if rules["starting_seat"] is not None:
        starting += f" ({rules['starting_seat']} takes the first turn)"
    names = len(rules["card_name_domain"]["names"])
    audits = {item["name"]: item["audit"] for item in info["native_id_extensions"]}
    extensions = [
        name + (f" (native ids, audit {audits[name]})" if name in audits else "") for name in rules["extensions"]
    ]
    provided = [flag for flag in OBSERVATION_FLAGS if info["observation"][flag]]
    return [
        {"term": "Opponent decklist", "value": rules["opponent_decklist"]},
        {"term": "Mulligan", "value": mulligan},
        {"term": "Starting player", "value": starting},
        {"term": "Card-name domain", "value": f"{names} card name{'' if names == 1 else 's'}"},
        *(
            {"term": term, "value": info["engine_defaults"][key] or "offered to the bots"}
            for key, term in _ENGINE_DEFAULT_TERMS.items()
        ),
        {"term": "Optional observation fields", "value": ", ".join(provided) or "none"},
        {"term": "Extensions", "value": ", ".join(extensions) or "none"},
    ]


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
        "descriptions": [display[row["name"]]["description"] for row in rows],
        "cells": cells,
    }


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
