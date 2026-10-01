"""Benchmark definitions: ``benchmarks/<id>/benchmark.json`` and its runs.

A benchmark is a folder. Its ``benchmark.json`` (schema
``spellbench-benchmark/v2``) names the engine, the deck pool that every
matchup rotates through, and the bot roster with how the site shows each
bot. Benchmarks fix their information rules (opponent decklist visible,
mulligan auto, host-assigned starting player with seat p0), so a
definition never states them. Each run is a published tournament directory
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
from typing import Any, Iterable, Iterator, Mapping

from .._schema import EXTENSION_KEY_RE
from ..arena import store
from ..arena.config import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_LIMITS,
    DEFAULT_RESOURCES,
    DEFAULT_TIME_CONTROL,
    DEFAULT_WORKERS,
    DeckSpec,
    RulesSpec,
    TournamentError,
)
from ..errors import MalformedJsonError, ValidationError
from ..messages import Limits, Resources, TimeControl
from ..wire import MAX_JSON_INT, strict_json_loads

BENCHMARK_SCHEMA = "spellbench-benchmark/v2"
BENCHMARK_SCHEMA_V1 = "spellbench-benchmark/v1"
PROPOSED_SCHEMA = "spellbench-proposed-benchmarks/v1"
ANCHOR_BOT = "uniform"
BENCHMARK_FILE = "benchmark.json"
PROPOSED_FILE = "proposed.json"
LOCAL_VALUES_FILE = "local.json"
RUNS_DIR = "runs"
PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Use with fullmatch: a date, then no suffix (a day's first run) or a suffix of 2 or more.
RUN_NAME_PATTERN = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?:-([2-9]|[1-9][0-9]+))?")

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
    "stats_seed",
    "bots",
)
_OPTIONAL_FIELDS = (
    "pairing",
    "extensions",
    "native_id_audits",
    "time_control",
    "limits",
    "resources",
    "bootstrap_replicates",
    "workers",
)
# v1 definition fields and the v2 field that replaces each.
_V1_FIELDS = {
    "base_seed": "stats_seed",
    "choose_timeout_ms": "time_control.max_decision_ms",
    "startup_timeout_ms": "time_control.startup_ms",
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
    deck_pool: tuple[DeckSpec, ...]
    pairs_per_deck: int
    stats_seed: int
    extensions: tuple[str, ...]
    native_id_audits: dict[str, str]
    time_control: TimeControl
    limits: Limits
    resources: Resources
    bootstrap_replicates: int
    workers: int  # the most workers the throughput guard may choose
    bots: tuple[BenchmarkBot, ...]

    def bot(self, name: str) -> BenchmarkBot | None:
        """The roster bot named ``name``, or None."""
        for bot in self.bots:
            if bot.name == name:
                return bot
        return None

    def tournament_config(self, tournament_dir: str) -> dict[str, Any]:
        """A fresh v2 arena config for one run: every matchup rotates the pool, no self-play."""
        return {
            "schema": store.CONFIG_SCHEMA,
            "tournament_dir": tournament_dir,
            "format": self.format,
            "deck_pool": [deck.to_json() for deck in self.deck_pool],
            "engine": {"command": list(self.engine_command)},
            "bots": [copy.deepcopy(bot.entry) for bot in self.bots],
            "pairs_per_matchup": self.pairs_per_deck * len(self.deck_pool),
            "stats_seed": self.stats_seed,
            # Benchmarks fix their information rules (spec 12.2, Decision 8).
            "rules": RulesSpec().to_json(),
            "extensions": list(self.extensions),
            "native_id_audits": dict(self.native_id_audits),
            "time_control": self.time_control.to_json(),
            "limits": self.limits.to_json(),
            "resources": self.resources.to_json(),
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


def _has_control_character(text: str) -> bool:
    return any(unicodedata.category(char) == "Cc" for char in text)


def _display_text(value: Any, context: str) -> str:
    """A nonempty string without control or format characters (Cc, Cf).

    Format characters include the zero-width and bidi controls, which can
    make one bot's text read like another's.
    """
    text = _string(value, context)
    for char in text:
        if unicodedata.category(char) in ("Cc", "Cf"):
            raise BenchmarkError(f"{context}: must not contain control or format characters, found U+{ord(char):04X}")
    return text


def _label_key(label: str) -> str:
    """A label as a reader compares it: compatibility forms and case folded, spacing collapsed."""
    return " ".join(unicodedata.normalize("NFKC", label).casefold().split())


def _is_link(value: Any) -> bool:
    """An ``https://`` or ``http://`` URL without whitespace or control characters."""
    return (
        type(value) is str
        and value.startswith(("https://", "http://"))
        and not any(char.isspace() for char in value)
        and not _has_control_character(value)
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
        label=_display_text(display["label"], f"{context}.label"),
        author=_display_text(display["author"], f"{context}.author"),
        description=_display_text(display["description"], f"{context}.description"),
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
    first_with_label: dict[str, int] = {}
    for index, bot in enumerate(bots):
        other = first_with_label.setdefault(_label_key(bot.display.label), index)
        if other != index:
            raise BenchmarkError(
                f"{context}[{index}].display.label: {bot.display.label!r} reads as the label of {context}[{other}]; "
                "labels must be unique, ignoring case, spacing and compatibility forms"
            )
    if not any(bot.name == ANCHOR_BOT and bot.entry.get("type") == "builtin" for bot in bots):
        raise BenchmarkError(f'{context}: the roster must include the builtin "{ANCHOR_BOT}" bot (the rating anchor)')
    return bots


def _deck_spec(value: Any, context: str) -> DeckSpec:
    if type(value) is str:
        return DeckSpec(catalog_id=_string(value, context))
    if isinstance(value, dict):
        try:
            return DeckSpec.from_json(value, context)
        except TournamentError as exc:
            raise BenchmarkError(f"{context}: {exc}") from exc
    raise BenchmarkError(f"{context}: a pool deck is a catalog-id string or a {{name, decklist}} object")


def _deck_pool(value: Any, context: str) -> tuple[DeckSpec, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkError(f"{context}: must be a nonempty list of decks")
    pool = tuple(_deck_spec(item, f"{context}[{index}]") for index, item in enumerate(value))
    if len(set(pool)) != len(pool):
        raise BenchmarkError(f"{context}: decks must be distinct")
    return pool


def _extensions(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(type(item) is not str or not EXTENSION_KEY_RE.fullmatch(item) for item in value):
        raise BenchmarkError(f"{context}: must be a list of extension names (x_[a-z0-9_]+)")
    extensions = tuple(value)
    if len(set(extensions)) != len(extensions):
        raise BenchmarkError(f"{context}: duplicate names")
    return extensions


def _native_id_audits(value: Any, extensions: tuple[str, ...], context: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{context}: must be an object of extension: audit reference")
    audits: dict[str, str] = {}
    for extension, reference in value.items():
        if extension not in extensions:
            raise BenchmarkError(f"{context}: {extension!r} is not one of the benchmark's extensions")
        audits[extension] = _string(reference, f"{context}[{extension!r}]")
    return audits


def _spec_block(block_type: Any, value: Any, context: str) -> Any:
    """A complete ``time_control``/``limits``/``resources`` block from ``messages``."""
    try:
        return block_type.from_json(value, context)
    except ValidationError as exc:
        raise BenchmarkError(f"{context}: {exc}") from exc


def parse_benchmark(value: Any) -> Benchmark:
    """Validate one parsed ``benchmark.json`` document."""
    context = "benchmark"
    document = _object(value, context)
    # Fixed-deck benchmarks (spec 15's shape) are reserved in protocol v2.0; they are
    # checked before any other schema check so such a definition gets this message
    # rather than a missing deck_pool (R3-19).
    if document.get("pairing") == "fixed_deck" or "entries" in document:
        raise BenchmarkError(f"{context}: fixed-deck benchmarks are reserved in protocol v2.0 (spec 15)")
    for field in sorted(_V1_FIELDS):
        if field in document:
            raise BenchmarkError(f"{context}.{field}: v1 field; the v2 replacement is {_V1_FIELDS[field]}")
    _check_fields(document, context, _REQUIRED_FIELDS, _OPTIONAL_FIELDS)
    if document["schema"] == BENCHMARK_SCHEMA_V1:
        raise BenchmarkError(
            f'{context}.schema: "{BENCHMARK_SCHEMA_V1}" is the v1 schema; the v2 replacement is '
            f'"{BENCHMARK_SCHEMA}" (base_seed is now stats_seed, the timeouts are now time_control)'
        )
    if document["schema"] != BENCHMARK_SCHEMA:
        raise BenchmarkError(f'{context}.schema: must be "{BENCHMARK_SCHEMA}"')
    bench_id = document["id"]
    if type(bench_id) is not str or not _ID_PATTERN.fullmatch(bench_id):
        raise BenchmarkError(
            f"{context}.id: must be 1 to 64 characters from a-z, 0-9 and '-', not starting with '-'; got {bench_id!r}"
        )
    pairing = document.get("pairing", "rotating_pool")
    if pairing != "rotating_pool":
        raise BenchmarkError(f'{context}.pairing: must be "rotating_pool", got {pairing!r}')
    engine = _object(document["engine"], f"{context}.engine")
    if "timeout_ms" in engine:
        raise BenchmarkError(f"{context}.engine.timeout_ms: v1 field; the v2 replacement is time_control.engine_step_ms")
    _check_fields(engine, f"{context}.engine", ("name", "command"))
    extensions = _extensions(document.get("extensions", []), f"{context}.extensions")
    benchmark = Benchmark(
        id=bench_id,
        title=_string(document["title"], f"{context}.title"),
        summary=_string(document["summary"], f"{context}.summary"),
        format=_string(document["format"], f"{context}.format"),
        engine_name=_string(engine["name"], f"{context}.engine.name"),
        engine_command=_strings(engine["command"], f"{context}.engine.command"),
        deck_pool=_deck_pool(document["deck_pool"], f"{context}.deck_pool"),
        pairs_per_deck=_integer(document["pairs_per_deck"], f"{context}.pairs_per_deck", minimum=1),
        stats_seed=_integer(document["stats_seed"], f"{context}.stats_seed", minimum=0),
        extensions=extensions,
        native_id_audits=_native_id_audits(document.get("native_id_audits", {}), extensions, f"{context}.native_id_audits"),
        time_control=_spec_block(TimeControl, document["time_control"], f"{context}.time_control")
        if "time_control" in document
        else DEFAULT_TIME_CONTROL,
        limits=_spec_block(Limits, document["limits"], f"{context}.limits") if "limits" in document else DEFAULT_LIMITS,
        resources=_spec_block(Resources, document["resources"], f"{context}.resources")
        if "resources" in document
        else DEFAULT_RESOURCES,
        bootstrap_replicates=_integer(
            document.get("bootstrap_replicates", DEFAULT_BOOTSTRAP_REPLICATES),
            f"{context}.bootstrap_replicates",
            minimum=1,
        ),
        workers=_integer(document.get("workers", DEFAULT_WORKERS), f"{context}.workers", minimum=1),
        bots=_parse_bots(document["bots"], f"{context}.bots"),
    )
    for field, text in _placeholder_fields(benchmark):
        if "${" in PLACEHOLDER_PATTERN.sub("", text):
            raise BenchmarkError(
                f"{context}.{field}: malformed placeholder in {text!r}; "
                "write ${NAME} with NAME of letters, digits and '_', not starting with a digit"
            )
    return benchmark


def _read_json(path: Path) -> dict[str, Any]:
    """The strict JSON object stored in ``path``."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BenchmarkError(f"cannot read {path}: {exc}") from exc
    try:
        return strict_json_loads(data)
    except MalformedJsonError as exc:
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


def _placeholder_fields(benchmark: Benchmark) -> Iterator[tuple[str, str]]:
    """(field, text) for each string that may hold placeholders: command parts and checkpoints."""
    for index, part in enumerate(benchmark.engine_command):
        yield f"engine.command[{index}]", part
    for bot_index, bot in enumerate(benchmark.bots):
        command = bot.entry.get("command")
        if isinstance(command, list):
            for index, part in enumerate(command):
                if isinstance(part, str):
                    yield f"bots[{bot_index}].command[{index}]", part
        checkpoint = bot.entry.get("checkpoint")
        if isinstance(checkpoint, str):
            yield f"bots[{bot_index}].checkpoint", checkpoint


def placeholder_names(benchmark: Benchmark) -> tuple[str, ...]:
    """The sorted unique placeholders in the engine command, bot commands and checkpoints."""
    return tuple(
        sorted({name for _, text in _placeholder_fields(benchmark) for name in PLACEHOLDER_PATTERN.findall(text)})
    )


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
        if _has_control_character(value):
            raise BenchmarkError(
                f"{path}: {name}: contains a control character; write paths with forward slashes "
                "or doubled backslashes (in JSON a single backslash starts an escape such as a tab)"
            )
    return values


def placeholder_values(
    names: Iterable[str], local: Mapping[str, str], environ: Mapping[str, str]
) -> dict[str, str]:
    """Resolve each name from the environment first, then local.json; no value may hold a control character."""
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
    garbled = [name for name, value in values.items() if _has_control_character(value)]
    if garbled:
        raise BenchmarkError(
            f"placeholder values {garbled} contain control characters (a stray tab, newline or carriage return?)"
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


def run_sort_key(name: str) -> tuple[str, int]:
    """(date, suffix) of a run name; the first run of a day has suffix 1."""
    match = RUN_NAME_PATTERN.fullmatch(name)
    if match is None:
        raise BenchmarkError(f"not a run name (YYYY-MM-DD or YYYY-MM-DD-N with N >= 2): {name!r}")
    return match.group(1), int(match.group(2) or 1)


def _runs(benchmark_dir: Path) -> list[Path]:
    """The children of ``runs/`` named like runs, oldest first."""
    runs_dir = benchmark_dir / RUNS_DIR
    if not runs_dir.is_dir():
        return []
    return sorted(
        (child for child in runs_dir.iterdir() if RUN_NAME_PATTERN.fullmatch(child.name)),
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
    match = RUN_NAME_PATTERN.fullmatch(date)
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
