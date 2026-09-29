"""Benchmark definitions: parsing, placeholders, and run-directory names."""

from __future__ import annotations

import pytest

pytest.skip("protocol v1 test, migrated in Task 37", allow_module_level=True)

import json
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import runner
from spellbench.bench import definition
from spellbench.bench.definition import BenchmarkError


def _value(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "spellbench-benchmark/v1",
        "id": "pauper-kernel",
        "title": "Pauper on mtg-kernel",
        "summary": "Eight Pauper decks.",
        "format": "pauper-bo1",
        "engine": {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}"], "timeout_ms": 120000},
        "deck_pool": ["Burn", "Elves"],
        "pairs_per_deck": 2,
        "base_seed": 7,
        "bots": [
            {
                "name": "uniform",
                "version": "1.0.0",
                "type": "builtin",
                "seed": 11,
                "display": {"label": "random", "author": "Spellbench", "description": "Uniform.", "url": None},
            },
            {
                "name": "mybot",
                "version": "2.0",
                "type": "subprocess",
                "command": ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"],
                "checkpoint": "${CKPT_DIR}/model.bin",
                "display": {
                    "label": "My Bot",
                    "author": "someone",
                    "description": "A test bot.",
                    "url": "https://example.com/bot",
                },
            },
        ],
    }
    value.update(changes)
    return value


def _write(directory: Path, value: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "benchmark.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    return directory


def test_a_valid_definition_parses_with_runner_defaults() -> None:
    benchmark = definition.parse_benchmark(_value())
    assert benchmark.id == "pauper-kernel"
    assert benchmark.engine_name == "mtg-kernel"
    assert benchmark.engine_command == ("${MTG_KERNEL_BRIDGE}",)
    assert benchmark.deck_pool == ("Burn", "Elves")
    assert benchmark.choose_timeout_ms == runner.DEFAULT_CHOOSE_TIMEOUT_MS
    assert benchmark.startup_timeout_ms == runner.DEFAULT_STARTUP_TIMEOUT_MS
    assert benchmark.bootstrap_replicates == runner.DEFAULT_BOOTSTRAP_REPLICATES
    assert benchmark.workers == runner.DEFAULT_WORKERS
    assert [bot.name for bot in benchmark.bots] == ["uniform", "mybot"]
    assert benchmark.bot("mybot").display.url == "https://example.com/bot"
    assert "display" not in benchmark.bot("mybot").entry
    assert benchmark.bot("nobody") is None


def test_unknown_top_level_fields_are_errors() -> None:
    with pytest.raises(BenchmarkError, match="colour"):
        definition.parse_benchmark(_value(colour="blue"))


def test_missing_fields_are_errors() -> None:
    value = _value()
    del value["deck_pool"]
    with pytest.raises(BenchmarkError, match="deck_pool"):
        definition.parse_benchmark(value)


def test_unknown_display_fields_are_errors() -> None:
    value = _value()
    value["bots"][0]["display"]["colour"] = "blue"
    with pytest.raises(BenchmarkError, match="colour"):
        definition.parse_benchmark(value)


def test_the_roster_must_include_the_builtin_uniform_bot() -> None:
    value = _value()
    value["bots"] = value["bots"][1:]
    with pytest.raises(BenchmarkError, match="uniform"):
        definition.parse_benchmark(value)


def test_bot_names_are_unique() -> None:
    value = _value()
    value["bots"][1]["name"] = "uniform"
    with pytest.raises(BenchmarkError, match="unique"):
        definition.parse_benchmark(value)


# Cf: zero-width space, right-to-left override, left-to-right isolate, soft hyphen. Cc: escape, newline.
@pytest.mark.parametrize("char", ["\u200b", "\u202e", "\u2066", "\u00ad", "\x1b", "\n"])
@pytest.mark.parametrize("field", ["label", "author", "description"])
def test_display_text_rejects_control_and_format_characters(field: str, char: str) -> None:
    value = _value()
    value["bots"][1]["display"][field] = f"My{char}Bot"
    with pytest.raises(BenchmarkError, match=rf"benchmark\.bots\[1\]\.display\.{field}: .*U\+{ord(char):04X}"):
        definition.parse_benchmark(value)


def test_display_text_may_hold_any_visible_characters() -> None:
    value = _value()
    label = "Überbot · 改 (MCTS) \U0001f916"
    value["bots"][1]["display"].update(label=label, author="José", description="Fast. Then slow.")
    assert definition.parse_benchmark(value).bot("mybot").display.label == label


# Each reads as "random" on a page: the same text, another case, extra spacing, fullwidth letters.
@pytest.mark.parametrize("label", ["random", "Random", " random  ", "random ", "ｒａｎｄｏｍ"])
def test_labels_are_unique_within_a_benchmark(label: str) -> None:
    value = _value()
    value["bots"][1]["display"]["label"] = label
    with pytest.raises(BenchmarkError, match=r"benchmark\.bots\[1\]\.display\.label: .*bots\[0\]"):
        definition.parse_benchmark(value)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x.org", "example.com", " https://x.org", "https://x.org/a b"])
def test_display_urls_must_be_plain_http_links(url: str) -> None:
    value = _value()
    value["bots"][1]["display"]["url"] = url
    with pytest.raises(BenchmarkError, match="url"):
        definition.parse_benchmark(value)


@pytest.mark.parametrize("bench_id", ["Pauper", "pauper kernel", "-x", "a/b", "", "a" * 65])
def test_ids_are_url_safe(bench_id: str) -> None:
    with pytest.raises(BenchmarkError, match="id"):
        definition.parse_benchmark(_value(id=bench_id))


@pytest.mark.parametrize("pool", [[], ["Burn", "Burn"], [""], "Burn", [1]])
def test_the_deck_pool_is_a_list_of_distinct_catalog_ids(pool: Any) -> None:
    with pytest.raises(BenchmarkError, match="deck_pool"):
        definition.parse_benchmark(_value(deck_pool=pool))


@pytest.mark.parametrize("field,bad", [("pairs_per_deck", True), ("pairs_per_deck", 0), ("base_seed", -1), ("workers", "8")])
def test_integers_are_checked(field: str, bad: Any) -> None:
    with pytest.raises(BenchmarkError, match=field):
        definition.parse_benchmark(_value(**{field: bad}))


def test_the_tournament_config_rotates_the_pool_without_self_play() -> None:
    config = definition.parse_benchmark(_value()).tournament_config("runs/2026-09-26")
    assert config["schema"] == "spellbench-tournament-config/v1"
    assert config["tournament_dir"] == "runs/2026-09-26"
    assert config["deck_pool"] == [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}]
    assert "decks" not in config
    assert config["pairs_per_matchup"] == 4
    assert config["rating_anchor"] == "uniform"
    assert config["include_self_play"] is False
    assert config["engine"] == {"command": ["${MTG_KERNEL_BRIDGE}"], "timeout_ms": 120000}
    assert config["bots"][1]["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]
    assert all("display" not in bot for bot in config["bots"])


def test_the_tournament_config_is_a_fresh_copy() -> None:
    benchmark = definition.parse_benchmark(_value())
    config = benchmark.tournament_config("runs/x")
    config["bots"][1]["command"].append("--oops")
    assert benchmark.tournament_config("runs/x")["bots"][1]["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]


def test_load_benchmark_requires_the_folder_name_to_match_the_id(tmp_path: Path) -> None:
    assert definition.load_benchmark(_write(tmp_path / "pauper-kernel", _value())).id == "pauper-kernel"
    with pytest.raises(BenchmarkError, match="id"):
        definition.load_benchmark(_write(tmp_path / "other", _value()))


def test_load_benchmark_rejects_non_strict_json(tmp_path: Path) -> None:
    directory = tmp_path / "pauper-kernel"
    directory.mkdir()
    (directory / "benchmark.json").write_text('{"schema": 1.5}', encoding="utf-8")
    with pytest.raises(BenchmarkError):
        definition.load_benchmark(directory)


def test_an_integer_literal_past_the_interpreter_digit_limit_is_not_strict_json(tmp_path: Path) -> None:
    # int() raises a bare ValueError past 4300 digits; the reader must still name the file.
    directory = tmp_path / "pauper-kernel"
    directory.mkdir()
    (directory / "benchmark.json").write_text('{"base_seed": ' + "7" * 5000 + "}", encoding="utf-8")
    with pytest.raises(BenchmarkError, match=r"benchmark\.json is not strict JSON"):
        definition.load_benchmark(directory)


def test_find_benchmarks_lists_folders_with_a_definition_in_order(tmp_path: Path) -> None:
    _write(tmp_path / "b", _value(id="b"))
    _write(tmp_path / "a", _value(id="a"))
    (tmp_path / "c").mkdir()
    (tmp_path / "local.json").write_text("{}", encoding="utf-8")
    assert definition.find_benchmarks(tmp_path) == [tmp_path / "a", tmp_path / "b"]


def test_placeholder_names_cover_engine_bot_commands_and_checkpoints() -> None:
    benchmark = definition.parse_benchmark(_value())
    assert definition.placeholder_names(benchmark) == ("CKPT_DIR", "MTG_KERNEL_BRIDGE", "PYTHON")


def test_the_environment_beats_local_values() -> None:
    values = definition.placeholder_values(
        ["PYTHON", "CKPT_DIR", "MTG_KERNEL_BRIDGE"],
        {"PYTHON": "py-local", "CKPT_DIR": "C:\\models"},
        {"PYTHON": "py-env", "MTG_KERNEL_BRIDGE": "bridge"},
    )
    assert values == {"PYTHON": "py-env", "CKPT_DIR": "C:\\models", "MTG_KERNEL_BRIDGE": "bridge"}


def test_every_unresolved_placeholder_is_named() -> None:
    with pytest.raises(BenchmarkError) as caught:
        definition.placeholder_values(["A", "B", "C"], {"A": "x"}, {"C": ""})
    assert "B" in str(caught.value) and "C" in str(caught.value) and "'A'" not in str(caught.value)


def test_substitute_replaces_embedded_placeholders_verbatim() -> None:
    assert definition.substitute("--model=${CKPT_DIR}/model.bin", {"CKPT_DIR": "C:\\models"}) == "--model=C:\\models/model.bin"
    assert definition.substitute("no placeholders", {}) == "no placeholders"
    with pytest.raises(BenchmarkError, match="MISSING"):
        definition.substitute("${MISSING}", {})


def test_local_values_are_strict(tmp_path: Path) -> None:
    assert definition.load_local_values(tmp_path) == {}
    (tmp_path / "local.json").write_text('{"MTG_KERNEL_BRIDGE": "C:/bridge.exe"}', encoding="utf-8")
    assert definition.load_local_values(tmp_path) == {"MTG_KERNEL_BRIDGE": "C:/bridge.exe"}
    for bad in ('{"A": 1}', '{"not a name": "x"}', "[]"):
        (tmp_path / "local.json").write_text(bad, encoding="utf-8")
        with pytest.raises(BenchmarkError):
            definition.load_local_values(tmp_path)


def _run(benchmark_dir: Path, name: str, *, published: bool = True) -> Path:
    directory = benchmark_dir / "runs" / name
    directory.mkdir(parents=True)
    if published:
        (directory / "manifest.json").write_text("{}\n", encoding="utf-8")
    return directory


def test_next_run_name_takes_the_first_free_suffix(tmp_path: Path) -> None:
    assert definition.next_run_name(tmp_path, "2026-09-26") == "2026-09-26"
    _run(tmp_path, "2026-09-26")
    assert definition.next_run_name(tmp_path, "2026-09-26") == "2026-09-26-2"
    _run(tmp_path, "2026-09-26-2", published=False)  # a crashed run still takes its name
    assert definition.next_run_name(tmp_path, "2026-09-26") == "2026-09-26-3"


@pytest.mark.parametrize("date", ["2026-13-01", "26-09-2026", "2026-09-26-2", "today", "2026-02-30"])
def test_run_dates_are_real_calendar_dates(tmp_path: Path, date: str) -> None:
    with pytest.raises(BenchmarkError, match="date"):
        definition.next_run_name(tmp_path, date)


def test_the_latest_run_is_the_latest_date_then_the_highest_suffix(tmp_path: Path) -> None:
    for name in ("2026-09-25-3", "2026-09-26", "2026-09-26-2", "2026-09-26-10"):
        _run(tmp_path, name)
    (tmp_path / "runs" / "notes").mkdir()
    assert definition.latest_run_dir(tmp_path) == tmp_path / "runs" / "2026-09-26-10"
    assert [run.name for run in definition.published_runs(tmp_path)] == [
        "2026-09-25-3", "2026-09-26", "2026-09-26-2", "2026-09-26-10",
    ]


def test_unpublished_runs_are_skipped_but_listed(tmp_path: Path) -> None:
    _run(tmp_path, "2026-09-26")
    _run(tmp_path, "2026-09-27", published=False)
    assert definition.latest_run_dir(tmp_path) == tmp_path / "runs" / "2026-09-26"
    assert definition.unpublished_runs(tmp_path) == [tmp_path / "runs" / "2026-09-27"]


def test_no_runs_means_no_latest_run(tmp_path: Path) -> None:
    assert definition.latest_run_dir(tmp_path) is None
    assert definition.published_runs(tmp_path) == []


def test_proposed_benchmarks(tmp_path: Path) -> None:
    assert definition.load_proposed(tmp_path) == ()
    proposed = {
        "schema": "spellbench-proposed-benchmarks/v1",
        "proposed": [{"title": "FDN Limited", "summary": "Foundations limited.", "needs": "an engine"}],
    }
    (tmp_path / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8")
    assert definition.load_proposed(tmp_path) == (
        definition.ProposedBenchmark(title="FDN Limited", summary="Foundations limited.", needs="an engine"),
    )
    proposed["proposed"][0]["colour"] = "blue"
    (tmp_path / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="colour"):
        definition.load_proposed(tmp_path)


@pytest.mark.parametrize("url", ["https://x.org/\x00", "https://x.org/\x7f"])
def test_display_urls_reject_control_characters(url: str) -> None:
    value = _value()
    value["bots"][1]["display"]["url"] = url
    with pytest.raises(BenchmarkError, match="url"):
        definition.parse_benchmark(value)


@pytest.mark.parametrize(
    "name,key", [("2026-09-26", ("2026-09-26", 1)), ("2026-09-26-2", ("2026-09-26", 2)), ("2026-09-26-10", ("2026-09-26", 10))]
)
def test_run_names_sort_by_date_then_suffix(name: str, key: tuple[str, int]) -> None:
    assert definition.RUN_NAME_PATTERN.fullmatch(name)
    assert definition.run_sort_key(name) == key


# "-1" would tie with the unsuffixed name; a fullwidth-digit date would sort after every real run.
@pytest.mark.parametrize("name", ["2026-09-26-1", "2026-09-26-02", "2026-09-26\n", "\uff12\uff10\uff12\uff16-09-26", "notes"])
def test_other_names_are_not_run_names(name: str) -> None:
    assert definition.RUN_NAME_PATTERN.fullmatch(name) is None
    with pytest.raises(BenchmarkError, match="run name"):
        definition.run_sort_key(name)


def test_local_values_reject_control_characters(tmp_path: Path) -> None:
    # Single backslashes: JSON reads \t, \b and \r as a tab, backspaces and a carriage return.
    (tmp_path / "local.json").write_text(r'{"MTG_KERNEL_BRIDGE": "C:\tools\bin\release\bridge.exe"}', encoding="utf-8")
    with pytest.raises(BenchmarkError, match="MTG_KERNEL_BRIDGE.*forward slashes"):
        definition.load_local_values(tmp_path)
    (tmp_path / "local.json").write_text(r'{"MTG_KERNEL_BRIDGE": "C:\\tools\\bin\\bridge.exe"}', encoding="utf-8")
    assert definition.load_local_values(tmp_path) == {"MTG_KERNEL_BRIDGE": "C:\\tools\\bin\\bridge.exe"}


def test_environment_values_reject_control_characters() -> None:
    # Git Bash keeps the carriage return of a value read from a CRLF file.
    with pytest.raises(BenchmarkError, match="MTG_KERNEL_BRIDGE"):
        definition.placeholder_values(["MTG_KERNEL_BRIDGE"], {}, {"MTG_KERNEL_BRIDGE": "C:/bridge.exe\r"})


@pytest.mark.parametrize("text", ["${MTG-KERNEL}", "${CKPT_DIR/m.bin"])
@pytest.mark.parametrize(
    "field,path",
    [
        ("engine.command[0]", ("engine", "command", 0)),
        ("bots[1].command[1]", ("bots", 1, "command", 1)),
        ("bots[1].checkpoint", ("bots", 1, "checkpoint")),
    ],
)
def test_malformed_placeholders_are_errors(text: str, field: str, path: tuple[Any, ...]) -> None:
    value = _value()
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = text
    with pytest.raises(BenchmarkError) as caught:
        definition.parse_benchmark(value)
    assert f"benchmark.{field}:" in str(caught.value)
