"""Benchmark definitions: ``benchmarks/<id>/benchmark.json`` and its runs.

A benchmark is a folder. Its ``benchmark.json`` (schema
``spellbench-benchmark/v1``) names the engine, the deck pool that every
matchup rotates through, and the bot roster with how the site shows each
bot. Each run is a published tournament directory
``runs/<YYYY-MM-DD>[-N]/``: the first run of a day has no suffix, later
ones ``-2``, ``-3``, and so on. The site shows the latest published run.

Machine-specific paths stay out of the repo: engine command parts, bot
command parts and checkpoint strings may hold ``${NAME}`` placeholders,
resolved at run time from the environment or the git-ignored
``benchmarks/local.json`` (the environment wins).

Every input is strict: unknown fields are errors, and each error names the
offending field.
"""

from __future__ import annotations

import copy
import datetime
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..arena import runner, store
from ..errors import MalformedJsonError
from ..wire import MAX_JSON_INT, strict_json_loads

BENCHMARK_SCHEMA = "spellbench-benchmark/v1"
PROPOSED_SCHEMA = "spellbench-proposed-benchmarks/v1"
ANCHOR_BOT = "uniform"
BENCHMARK_FILE = "benchmark.json"
PROPOSED_FILE = "proposed.json"
LOCAL_VALUES_FILE = "local.json"
RUNS_DIR = "runs"
PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
RUN_NAME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-([1-9][0-9]*))?$")

_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REQUIRED_FIELDS = (
    "schema",
    "id",
    "title",
    "summary",
    "format",
    "engine",
    "deck_pool",
    "pairs_per_deck",
    "base_seed",
    "bots",
)
# The optional integer fields and their defaults (the runner's).
_OPTIONAL_DEFAULTS = {
    "choose_timeout_ms": runner.DEFAULT_CHOOSE_TIMEOUT_MS,
    "startup_timeout_ms": runner.DEFAULT_STARTUP_TIMEOUT_MS,
    "bootstrap_replicates": runner.DEFAULT_BOOTSTRAP_REPLICATES,
    "workers": runner.DEFAULT_WORKERS,
}


class BenchmarkError(ValueError):
    """A benchmark definition, a local value, or a run name is invalid."""


@dataclass(frozen=True)
class BotDisplay:
    label: str
    author: str
    description: str
    url: str | None


@dataclass(frozen=True)
class BenchmarkBot:
    name: str
    entry: dict[str, Any]  # the arena bot entry as written, without "display"
    display: BotDisplay


@dataclass(frozen=True)
class Benchmark:
    id: str
    title: str
    summary: str
    format: str
    engine_name: str
    engine_command: tuple[str, ...]
    engine_timeout_ms: int
    deck_pool: tuple[str, ...]
    pairs_per_deck: int
    base_seed: int
    choose_timeout_ms: int
    startup_timeout_ms: int
    bootstrap_replicates: int
    workers: int
    bots: tuple[BenchmarkBot, ...]

    def bot(self, name: str) -> BenchmarkBot | None:
        """The roster bot named ``name``, or None."""
        for bot in self.bots:
            if bot.name == name:
                return bot
        return None

    def tournament_config(self, tournament_dir: str) -> dict[str, Any]:
        """A fresh arena config for one run: every matchup rotates the pool, no self-play."""
        return {
            "schema": store.CONFIG_SCHEMA,
            "tournament_dir": tournament_dir,
            "format": self.format,
            "deck_pool": [{"catalog_id": deck} for deck in self.deck_pool],
            "engine": {"command": list(self.engine_command), "timeout_ms": self.engine_timeout_ms},
            "bots": [copy.deepcopy(bot.entry) for bot in self.bots],
            "pairs_per_matchup": self.pairs_per_deck * len(self.deck_pool),
            "base_seed": self.base_seed,
            "choose_timeout_ms": self.choose_timeout_ms,
            "startup_timeout_ms": self.startup_timeout_ms,
            "bootstrap_replicates": self.bootstrap_replicates,
            "workers": self.workers,
            "rating_anchor": ANCHOR_BOT,
            "include_self_play": False,
        }


@dataclass(frozen=True)
class ProposedBenchmark:
    title: str
    summary: str
    needs: str


# ---------------------------------------------------------------------------
# Field checks
# ---------------------------------------------------------------------------


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{context}: must be an object")
    return value


def _check_fields(value: dict[str, Any], context: str, required: Iterable[str], optional: Iterable[str] = ()) -> None:
    missing = set(required) - set(value)
    extra = set(value) - set(required) - set(optional)
    if missing or extra:
        raise BenchmarkError(f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def _string(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise BenchmarkError(f"{context}: must be a nonempty string")
    return value


def _strings(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(type(item) is not str or not item for item in value):
        raise BenchmarkError(f"{context}: must be a nonempty list of nonempty strings")
    return tuple(value)


def _integer(value: Any, context: str, *, minimum: int) -> int:
    # type() rather than isinstance(): a boolean is not an integer here.
    if type(value) is not int or not minimum <= value <= MAX_JSON_INT:
        raise BenchmarkError(f"{context}: must be an integer in [{minimum}, 2^53]")
    return value


def _is_link(value: Any) -> bool:
    """An ``https://`` or ``http://`` URL without whitespace or control characters."""
    return (
        type(value) is str
        and value.startswith(("https://", "http://"))
        and not any(char.isspace() or unicodedata.category(char) == "Cc" for char in value)
    )


# ---------------------------------------------------------------------------
# benchmark.json
# ---------------------------------------------------------------------------


def _parse_display(value: Any, context: str) -> BotDisplay:
    display = _object(value, context)
    _check_fields(display, context, ("label", "author", "description", "url"))
    url = display["url"]
    if url is not None and not _is_link(url):
        raise BenchmarkError(
            f"{context}.url: must be null or an https:// or http:// URL without whitespace or control characters"
        )
    return BotDisplay(
        label=_string(display["label"], f"{context}.label"),
        author=_string(display["author"], f"{context}.author"),
        description=_string(display["description"], f"{context}.description"),
        url=url,
    )


def _parse_bot(value: Any, context: str) -> BenchmarkBot:
    raw = _object(value, context)
    return BenchmarkBot(
        name=_string(raw.get("name"), f"{context}.name"),
        # The arena validates the other fields when the tournament config is parsed.
        entry={key: copy.deepcopy(item) for key, item in raw.items() if key != "display"},
        display=_parse_display(raw.get("display"), f"{context}.display"),
    )


def _parse_bots(value: Any, context: str) -> tuple[BenchmarkBot, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkError(f"{context}: must be a nonempty list")
    bots = tuple(_parse_bot(item, f"{context}[{index}]") for index, item in enumerate(value))
    names = [bot.name for bot in bots]
    if len(set(names)) != len(names):
        raise BenchmarkError(f"{context}: names must be unique, got {names}")
    if not any(bot.name == ANCHOR_BOT and bot.entry.get("type") == "builtin" for bot in bots):
        raise BenchmarkError(f'{context}: the roster must include the builtin "{ANCHOR_BOT}" bot (the rating anchor)')
    return bots


def parse_benchmark(value: Any) -> Benchmark:
    """Validate one parsed ``benchmark.json`` document."""
    context = "benchmark"
    document = _object(value, context)
    _check_fields(document, context, _REQUIRED_FIELDS, _OPTIONAL_DEFAULTS)
    if document["schema"] != BENCHMARK_SCHEMA:
        raise BenchmarkError(f'{context}.schema: must be "{BENCHMARK_SCHEMA}"')
    bench_id = document["id"]
    if type(bench_id) is not str or not _ID_PATTERN.fullmatch(bench_id):
        raise BenchmarkError(
            f"{context}.id: must be 1 to 64 characters from a-z, 0-9 and '-', not starting with '-'; got {bench_id!r}"
        )
    engine = _object(document["engine"], f"{context}.engine")
    _check_fields(engine, f"{context}.engine", ("name", "command"), ("timeout_ms",))
    deck_pool = _strings(document["deck_pool"], f"{context}.deck_pool")
    if len(set(deck_pool)) != len(deck_pool):
        raise BenchmarkError(f"{context}.deck_pool: catalog ids must be distinct, got {list(deck_pool)}")
    optional = {
        field: _integer(document.get(field, default), f"{context}.{field}", minimum=1)
        for field, default in _OPTIONAL_DEFAULTS.items()
    }
    return Benchmark(
        id=bench_id,
        title=_string(document["title"], f"{context}.title"),
        summary=_string(document["summary"], f"{context}.summary"),
        format=_string(document["format"], f"{context}.format"),
        engine_name=_string(engine["name"], f"{context}.engine.name"),
        engine_command=_strings(engine["command"], f"{context}.engine.command"),
        engine_timeout_ms=_integer(
            engine.get("timeout_ms", runner.DEFAULT_ENGINE_TIMEOUT_MS), f"{context}.engine.timeout_ms", minimum=1
        ),
        deck_pool=deck_pool,
        pairs_per_deck=_integer(document["pairs_per_deck"], f"{context}.pairs_per_deck", minimum=1),
        base_seed=_integer(document["base_seed"], f"{context}.base_seed", minimum=0),
        bots=_parse_bots(document["bots"], f"{context}.bots"),
        **optional,
    )


def _read_json(path: Path) -> dict[str, Any]:
    """The strict JSON object stored in ``path``."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BenchmarkError(f"cannot read {path}: {exc}") from exc
    # ValueError: an integer literal past Python's digit limit escapes strict_json_loads.
    try:
        return strict_json_loads(data)
    except (MalformedJsonError, ValueError) as exc:
        raise BenchmarkError(f"{path} is not strict JSON: {exc}") from exc


def load_benchmark(directory: Path) -> Benchmark:
    """Read ``directory/benchmark.json``; the benchmark id must be the folder name."""
    path = directory / BENCHMARK_FILE
    document = _read_json(path)
    try:
        benchmark = parse_benchmark(document)
    except BenchmarkError as exc:
        raise BenchmarkError(f"{path}: {exc}") from exc
    if benchmark.id != directory.name:
        raise BenchmarkError(f"{directory}: id {benchmark.id!r} does not match the folder name {directory.name!r}")
    return benchmark


def find_benchmarks(benchmarks_dir: Path) -> list[Path]:
    """The folders of ``benchmarks_dir`` that hold a ``benchmark.json``, sorted."""
    if not benchmarks_dir.is_dir():
        return []
    return sorted(child for child in benchmarks_dir.iterdir() if (child / BENCHMARK_FILE).is_file())


# ---------------------------------------------------------------------------
# proposed.json
# ---------------------------------------------------------------------------


def _parse_proposed(value: Any, context: str) -> ProposedBenchmark:
    item = _object(value, context)
    _check_fields(item, context, ("title", "summary", "needs"))
    return ProposedBenchmark(
        title=_string(item["title"], f"{context}.title"),
        summary=_string(item["summary"], f"{context}.summary"),
        needs=_string(item["needs"], f"{context}.needs"),
    )


def load_proposed(benchmarks_dir: Path) -> tuple[ProposedBenchmark, ...]:
    """The benchmarks listed in ``proposed.json``, in file order; () without the file."""
    path = benchmarks_dir / PROPOSED_FILE
    if not path.exists():
        return ()
    document = _read_json(path)
    _check_fields(document, str(path), ("schema", "proposed"))
    if document["schema"] != PROPOSED_SCHEMA:
        raise BenchmarkError(f'{path}: schema: must be "{PROPOSED_SCHEMA}"')
    items = document["proposed"]
    if not isinstance(items, list):
        raise BenchmarkError(f"{path}: proposed: must be a list")
    return tuple(_parse_proposed(item, f"{path}: proposed[{index}]") for index, item in enumerate(items))


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


def placeholder_names(benchmark: Benchmark) -> tuple[str, ...]:
    """The sorted unique placeholders in the engine command, bot commands and checkpoints."""
    texts = list(benchmark.engine_command)
    for bot in benchmark.bots:
        command = bot.entry.get("command")
        if isinstance(command, list):
            texts.extend(part for part in command if isinstance(part, str))
        checkpoint = bot.entry.get("checkpoint")
        if isinstance(checkpoint, str):
            texts.append(checkpoint)
    return tuple(sorted({name for text in texts for name in PLACEHOLDER_PATTERN.findall(text)}))


def load_local_values(benchmarks_dir: Path) -> dict[str, str]:
    """Placeholder values from ``local.json`` in ``benchmarks_dir``; {} without the file."""
    path = benchmarks_dir / LOCAL_VALUES_FILE
    if not path.exists():
        return {}
    values = _read_json(path)
    for name, value in values.items():
        if not _NAME_PATTERN.fullmatch(name):
            raise BenchmarkError(
                f"{path}: {name!r} is not a placeholder name (letters, digits and '_', not starting with a digit)"
            )
        if type(value) is not str:
            raise BenchmarkError(f"{path}: {name}: must be a string")
    return values


def placeholder_values(
    names: Iterable[str], local: Mapping[str, str], environ: Mapping[str, str]
) -> dict[str, str]:
    """Resolve each name from the environment first, then local.json."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in sorted(set(names)):
        value = environ.get(name) or local.get(name)
        if value:
            values[name] = value
        else:
            missing.append(name)
    if missing:
        raise BenchmarkError(
            f"unresolved placeholders {missing}: set them in the environment or in benchmarks/{LOCAL_VALUES_FILE}"
        )
    return values


def substitute(text: str, values: Mapping[str, str]) -> str:
    """``text`` with each ``${NAME}`` replaced by ``values[NAME]`` verbatim."""

    def value_of(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise BenchmarkError(f"no value for placeholder ${{{name}}}")
        return values[name]

    return PLACEHOLDER_PATTERN.sub(value_of, text)


# ---------------------------------------------------------------------------
# Run directories
# ---------------------------------------------------------------------------


def _run_name_match(name: str) -> re.Match[str] | None:
    """Match a run name, so that each name has its own sort key.

    ASCII only (``\\d`` also matches other scripts' digits), the whole name
    (``$`` alone accepts a trailing newline), and no ``-1`` suffix (it would
    tie with the unsuffixed name).
    """
    match = RUN_NAME_PATTERN.fullmatch(name) if name.isascii() else None
    if match is None or match.group(2) == "1":
        return None
    return match


def run_sort_key(name: str) -> tuple[str, int]:
    """(date, suffix) of a run name; the first run of a day has suffix 1."""
    match = _run_name_match(name)
    if match is None:
        raise BenchmarkError(f"not a run name (YYYY-MM-DD or YYYY-MM-DD-N with N >= 2): {name!r}")
    return match.group(1), int(match.group(2) or 1)


def _runs(benchmark_dir: Path) -> list[Path]:
    """The children of ``runs/`` named like runs, oldest first."""
    runs_dir = benchmark_dir / RUNS_DIR
    if not runs_dir.is_dir():
        return []
    return sorted(
        (child for child in runs_dir.iterdir() if _run_name_match(child.name)),
        key=lambda child: run_sort_key(child.name),
    )


def published_runs(benchmark_dir: Path) -> list[Path]:
    """The runs with a ``manifest.json``, oldest first."""
    return [run for run in _runs(benchmark_dir) if store.is_published(run)]


def unpublished_runs(benchmark_dir: Path) -> list[Path]:
    """The runs without a ``manifest.json`` (unfinished or crashed), oldest first."""
    return [run for run in _runs(benchmark_dir) if not store.is_published(run)]


def latest_run_dir(benchmark_dir: Path) -> Path | None:
    """The latest published run (the latest date, then the highest suffix), or None."""
    runs = published_runs(benchmark_dir)
    return runs[-1] if runs else None


def next_run_name(benchmark_dir: Path, date: str) -> str:
    """The first free name of ``date``, ``date-2``, ``date-3``, ... under ``runs/``.

    A name is taken by anything already there, published or not.
    """
    match = _run_name_match(date)
    if match is None or match.group(2) is not None:
        raise BenchmarkError(f"run date must be YYYY-MM-DD, got {date!r}")
    try:
        datetime.date.fromisoformat(date)
    except ValueError as exc:
        raise BenchmarkError(f"run date {date!r} is not a calendar date: {exc}") from exc
    runs_dir = benchmark_dir / RUNS_DIR
    name, suffix = date, 1
    while (runs_dir / name).exists():
        suffix += 1
        name = f"{date}-{suffix}"
    return name
