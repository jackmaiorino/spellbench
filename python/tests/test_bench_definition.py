"""Benchmark definitions: parsing, placeholders, and run-directory names."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import runner
from spellbench.arena.config import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_LIMITS,
    DEFAULT_RESOURCES,
    DEFAULT_TIME_CONTROL,
    DEFAULT_WORKERS,
    MAX_WORKERS,
    DeckSpec,
    TournamentConfig,
)
from spellbench.bench import definition
from spellbench.bench.definition import BenchmarkError
from spellbench.messages import DeckRow, Limits, Resources, TimeControl

REPO = Path(__file__).resolve().parents[2]
PAUPER_KERNEL = REPO / "benchmarks" / "pauper-kernel"
# Decision 8: every benchmark plays these information rules (spec 12.2).
BENCHMARK_RULES = {"opponent_decklist": "visible", "mulligan": "auto", "starting_player": "host_assigned", "starting_seat": "p0"}
CLOCKS = {"startup_ms": 120000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
          "max_decision_ms": 30000, "engine_step_ms": 120000}
KERNEL_PLACEHOLDERS = (
    "A48_CHECKPOINT", "A48_SCORER_CONFIG", "C12_CHECKPOINT", "C12_SCORER_CONFIG", "G115_CHECKPOINT",
    "G115_SCORER_CONFIG", "MTG_KERNEL_BRIDGE", "MTG_KERNEL_FLAT_BOT", "MTG_KERNEL_SCORER", "PYTHON",
)
MONO_RED = {"name": "Mono Red", "decklist": [{"name": "Mountain", "count": 20}]}


def _value(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "spellbench-benchmark/v2",
        "id": "pauper-kernel",
        "title": "Pauper on mtg-kernel",
        "summary": "Eight Pauper decks.",
        "format": "pauper-bo1",
        "engine": {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}"]},
        "deck_pool": ["Burn", "Elves"],
        "pairs_per_deck": 2,
        "stats_seed": 7,
        "time_control": dict(CLOCKS),
        "bots": [
            {
                "name": "uniform",
                "version": "2.0.0",
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


def _refused(value: Any) -> str:
    """The message ``parse_benchmark`` refuses ``value`` with."""
    with pytest.raises(BenchmarkError) as caught:
        definition.parse_benchmark(value)
    return str(caught.value)


def test_a_valid_definition_parses_with_arena_defaults() -> None:
    value = _value()
    del value["time_control"]
    benchmark = definition.parse_benchmark(value)
    assert definition.BENCHMARK_SCHEMA == "spellbench-benchmark/v2"
    assert benchmark.id == "pauper-kernel"
    assert benchmark.engine_name == "mtg-kernel"
    assert benchmark.engine_command == ("${MTG_KERNEL_BRIDGE}",)
    assert benchmark.deck_pool == (DeckSpec(catalog_id="Burn"), DeckSpec(catalog_id="Elves"))
    assert benchmark.pairs_per_deck == 2 and benchmark.stats_seed == 7
    assert benchmark.time_control == DEFAULT_TIME_CONTROL
    assert benchmark.limits == DEFAULT_LIMITS
    assert benchmark.resources == DEFAULT_RESOURCES
    assert benchmark.bootstrap_replicates == DEFAULT_BOOTSTRAP_REPLICATES
    assert benchmark.workers == DEFAULT_WORKERS
    assert benchmark.extensions == () and benchmark.native_id_audits == {}
    assert [bot.name for bot in benchmark.bots] == ["uniform", "mybot"]
    assert benchmark.bot("mybot").display.url == "https://example.com/bot"
    assert "display" not in benchmark.bot("mybot").entry
    assert benchmark.bot("nobody") is None


def test_every_optional_field_is_read() -> None:
    limits = {"max_decisions": 2000, "max_steps": 20000, "max_seat_decisions_per_turn": 100,
              "max_seat_decisions_per_game": 999, "max_seat_steps_per_game": 9999}
    resources = {"cpus": 2, "memory_mb": 8192, "gpu": True, "engine_cpus": 3}
    benchmark = definition.parse_benchmark(_value(
        pairing="rotating_pool", extensions=["x_kernel_v5", "x_gorge_view_v1"],
        native_id_audits={"x_kernel_v5": "audits/x_kernel_v5.md"},
        limits=limits, resources=resources, bootstrap_replicates=3000, workers=12,
    ))
    assert benchmark.time_control == TimeControl(**CLOCKS)
    assert benchmark.limits == Limits(**limits) and benchmark.resources == Resources(**resources)
    assert benchmark.extensions == ("x_kernel_v5", "x_gorge_view_v1")
    assert benchmark.native_id_audits == {"x_kernel_v5": "audits/x_kernel_v5.md"}
    assert (benchmark.bootstrap_replicates, benchmark.workers) == (3000, 12)
    config = benchmark.tournament_config("runs/x")
    assert config["time_control"] == CLOCKS and config["limits"] == limits and config["resources"] == resources
    assert config["extensions"] == ["x_kernel_v5", "x_gorge_view_v1"]
    assert config["native_id_audits"] == {"x_kernel_v5": "audits/x_kernel_v5.md"}
    assert (config["bootstrap_replicates"], config["workers"]) == (3000, 12)
    TournamentConfig.from_json(config)


def test_a_definition_is_an_object() -> None:
    assert _refused([_value()]) == "benchmark: must be an object"


def test_unknown_top_level_fields_are_errors() -> None:
    assert "extra=['colour']" in _refused(_value(colour="blue"))
    assert "extra=['rules']" in _refused(_value(rules=BENCHMARK_RULES))  # benchmarks fix their rules (Decision 8)


@pytest.mark.parametrize(
    "field", ["schema", "id", "title", "summary", "format", "engine", "deck_pool", "pairs_per_deck", "stats_seed", "bots"]
)
def test_missing_fields_are_errors(field: str) -> None:
    value = _value()
    del value[field]
    assert f"missing=['{field}']" in _refused(value)


def test_the_engine_holds_a_name_and_a_command() -> None:
    assert _refused(_value(engine=["${MTG_KERNEL_BRIDGE}"])) == "benchmark.engine: must be an object"
    assert "benchmark.engine: " in _refused(_value(engine={"command": ["bridge"]}))
    assert "missing=['name']" in _refused(_value(engine={"command": ["bridge"]}))
    assert "extra=['flags']" in _refused(_value(engine={"name": "e", "command": ["bridge"], "flags": []}))
    assert _refused(_value(engine={"name": "", "command": ["bridge"]})).startswith("benchmark.engine.name: ")
    for command in ([], "bridge", [""], ["bridge", 1]):
        assert _refused(_value(engine={"name": "e", "command": command})).startswith("benchmark.engine.command: ")


def test_unknown_display_fields_are_errors() -> None:
    value = _value()
    value["bots"][0]["display"]["colour"] = "blue"
    with pytest.raises(BenchmarkError, match="colour"):
        definition.parse_benchmark(value)


def test_the_roster_must_include_the_builtin_uniform_bot() -> None:
    value = _value()
    value["bots"][0]["name"] = "heuristic"
    with pytest.raises(BenchmarkError, match="uniform"):
        definition.parse_benchmark(value)
    value = _value()
    value["bots"][0]["name"] = "first"
    value["bots"][1]["name"] = "uniform"  # a subprocess bot named uniform is not the anchor
    with pytest.raises(BenchmarkError, match="uniform"):
        definition.parse_benchmark(value)


def test_a_roster_needs_two_bots() -> None:
    # Bots never play themselves, so a lone bot has no games.
    value = _value()
    value["bots"] = value["bots"][:1]
    message = _refused(value)
    assert message.startswith("benchmark.bots: ") and "two" in message
    assert _refused(_value(bots=[])) == "benchmark.bots: must be a nonempty list"
    assert _refused(_value(bots={"uniform": {}})) == "benchmark.bots: must be a nonempty list"


def test_bot_names_are_unique() -> None:
    value = _value()
    value["bots"][1]["name"] = "uniform"
    with pytest.raises(BenchmarkError, match="unique"):
        definition.parse_benchmark(value)


def test_the_roster_is_checked_as_arena_entries() -> None:
    # The arena would refuse these when it reads the config; the definition refuses them first.
    value = _value()
    value["bots"][0]["version"] = "1.0.0"  # a protocol v1 builtin
    message = _refused(value)
    assert "bots[0]" in message and "2.0.0" in message
    value = _value()
    value["bots"][1]["colour"] = "blue"
    message = _refused(value)
    assert "bots[1]" in message and "colour" in message
    value = _value()
    del value["bots"][1]["command"]
    assert "bots[1].command" in _refused(value)


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
    value["bots"][1]["display"].update(label=label, author="José", description="Fast. Then slow.")
    assert definition.parse_benchmark(value).bot("mybot").display.label == label


# Each reads as "random" on a page: the same text, another case, extra spacing, fullwidth letters.
@pytest.mark.parametrize("label", ["random", "Random", " random  ", "random ", "ｒａｎｄｏｍ"])
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


@pytest.mark.parametrize("pool", [[], ["Burn", "Burn"], [""], "Burn", [1], [None], [["Burn"]], {"Burn": 1}])
def test_the_deck_pool_is_a_list_of_distinct_decks(pool: Any) -> None:
    with pytest.raises(BenchmarkError, match=r"benchmark\.deck_pool"):
        definition.parse_benchmark(_value(deck_pool=pool))


@pytest.mark.parametrize(
    ("deck", "detail"),
    [
        ({"catalog_id": "Elves"}, "catalog id string"),  # a catalog deck has one spelling: its id
        ({"name": "Mono Red"}, "catalog id string"),
        ({**MONO_RED, "sideboard": []}, "catalog id string"),
        ({**MONO_RED, "decklist": []}, "decklist"),
        ({**MONO_RED, "decklist": [{"name": "Mountain", "count": 0}]}, "count"),
        ({**MONO_RED, "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 1}]}, "NFC"),
        ({**MONO_RED, "name": ""}, "name"),
        ({**MONO_RED, "name": "Mono\u202eRed"}, "U+202E"),
        ({**MONO_RED, "name": "Burn"}, "distinct"),  # reads as the catalog deck Burn on a page
    ],
)
def test_pool_decklists_are_checked(deck: dict[str, Any], detail: str) -> None:
    message = _refused(_value(deck_pool=["Burn", deck]))
    assert message.startswith("benchmark.deck_pool[1]") and detail in message


def test_the_pool_may_hold_decklists_and_the_rules_are_fixed() -> None:
    value = _value(deck_pool=["Burn", {"name": "Mono Red", "decklist": [{"name": "Mountain", "count": 20}]}])
    benchmark = definition.parse_benchmark(value)
    assert benchmark.deck_pool[1] == DeckSpec(name="Mono Red", decklist=(DeckRow("Mountain", 20),))
    config = benchmark.tournament_config("runs/x")
    assert config["deck_pool"][1] == {"name": "Mono Red", "decklist": [{"name": "Mountain", "count": 20}]}
    assert config["rules"] == {"opponent_decklist": "visible", "mulligan": "auto", "starting_player": "host_assigned", "starting_seat": "p0"}
    TournamentConfig.from_json(config)


def test_fixed_deck_benchmarks_are_reserved() -> None:
    with pytest.raises(BenchmarkError, match=r"benchmark\.pairing: .*reserved in protocol v2\.0"):
        definition.parse_benchmark(_value(pairing="fixed_deck"))
    assert _refused(_value(pairing="fixed_deck")) == "benchmark.pairing: fixed-deck benchmarks are reserved in protocol v2.0 (spec 15)"


def test_a_spec_15_shaped_definition_gets_the_reserved_message() -> None:
    value = {key: item for key, item in _value().items() if key != "deck_pool"}
    value.update(pairing="fixed_deck", entries=[{"entry": "burn-random", "bot": "uniform",
                                                 "deck": {"name": "Burn", "catalog_id": "Burn"}, "display": {"label": "random"}}])
    with pytest.raises(BenchmarkError, match="reserved in protocol v2.0"):
        definition.parse_benchmark(value)                                   # not "missing deck_pool" (R3-19)
    del value["pairing"]
    with pytest.raises(BenchmarkError, match=r"benchmark\.entries: .*reserved in protocol v2\.0"):
        definition.parse_benchmark(value)                                   # entries alone are the fixed-deck shape
    value["pairing"] = "rotating_pool"
    with pytest.raises(BenchmarkError, match=r"benchmark\.entries: .*reserved in protocol v2\.0"):
        definition.parse_benchmark(value)


def test_the_reserved_check_comes_before_every_other_check() -> None:
    # A definition broken everywhere else still gets the reserved message (R3-19).
    for value in ({"pairing": "fixed_deck"}, {"entries": []}, {"schema": "spellbench-benchmark/v1", "entries": [], "base_seed": 1}):
        assert "reserved in protocol v2.0 (spec 15)" in _refused(value)


@pytest.mark.parametrize("pairing", ["swiss", "Rotating_pool", "", 1, None, ["rotating_pool"]])
def test_the_only_pairing_is_the_rotating_pool(pairing: Any) -> None:
    assert _refused(_value(pairing=pairing)).startswith('benchmark.pairing: must be "rotating_pool"')
    assert definition.parse_benchmark(_value(pairing="rotating_pool")) == definition.parse_benchmark(_value())


@pytest.mark.parametrize(
    ("field", "hint"),
    [
        ("base_seed", "stats_seed"),
        ("choose_timeout_ms", "time_control.max_decision_ms"),
        ("startup_timeout_ms", "time_control.startup_ms"),
    ],
)
def test_v1_fields_name_their_replacement(field: str, hint: str) -> None:
    with pytest.raises(BenchmarkError, match=rf"benchmark\.{field}: .*{hint}"):
        definition.parse_benchmark(_value(**{field: 1}))


def test_the_v1_engine_timeout_names_its_replacement() -> None:
    engine = {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}"], "timeout_ms": 120000}
    with pytest.raises(BenchmarkError, match=r"benchmark\.engine\.timeout_ms: .*time_control\.engine_step_ms"):
        definition.parse_benchmark(_value(engine=engine))


def test_a_v1_definition_is_refused_with_a_migration_hint() -> None:
    value = _value(schema="spellbench-benchmark/v1", base_seed=7, choose_timeout_ms=30000)
    del value["stats_seed"], value["time_control"]
    message = _refused(value)
    assert message.startswith("benchmark.schema: ") and "spellbench-benchmark/v2" in message and "stats_seed" in message
    for schema in ("spellbench-benchmark/v3", "spellbench-tournament-config/v2", 2):
        assert _refused(_value(schema=schema)).startswith('benchmark.schema: must be "spellbench-benchmark/v2"')


@pytest.mark.parametrize(
    ("block", "value", "field"),
    [
        ("time_control", [], "benchmark.time_control"),
        ("time_control", {key: item for key, item in CLOCKS.items() if key != "bank_ms"}, "benchmark.time_control"),
        ("time_control", {**CLOCKS, "bank_ms": 0}, "benchmark.time_control.bank_ms"),
        ("time_control", {**CLOCKS, "increment_ms": -1}, "benchmark.time_control.increment_ms"),
        ("time_control", {**CLOCKS, "timeout_ms": 5}, "benchmark.time_control"),
        ("limits", {**DEFAULT_LIMITS.to_json(), "max_seat_decisions_per_game": 5000}, "benchmark.limits.max_seat_decisions_per_game"),
        ("limits", {**DEFAULT_LIMITS.to_json(), "max_steps": 1.5}, "benchmark.limits.max_steps"),
        ("limits", {"max_decisions": 10000}, "benchmark.limits"),
        ("resources", {**DEFAULT_RESOURCES.to_json(), "gpu": "no"}, "benchmark.resources.gpu"),
        ("resources", {**DEFAULT_RESOURCES.to_json(), "cpus": 0}, "benchmark.resources.cpus"),
    ],
)
def test_clocks_caps_and_resources_are_complete_checked_blocks(block: str, value: Any, field: str) -> None:
    # Spec 11.4: each block is declared whole; a seat cap stays strictly below half of its game cap (spec 11.1).
    assert _refused(_value(**{block: value})).startswith(f"{field}: ")


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"extensions": "x_kernel_v5"}, "benchmark.extensions"),
        ({"extensions": ["kernel_v5"]}, "benchmark.extensions"),
        ({"extensions": ["x_Kernel"]}, "benchmark.extensions"),
        ({"extensions": ["x_kernel_v5\n"]}, "benchmark.extensions"),
        ({"extensions": [1]}, "benchmark.extensions"),
        ({"extensions": ["x_a", "x_a"]}, "benchmark.extensions"),
        ({"native_id_audits": ["x_a"]}, "benchmark.native_id_audits"),
        ({"native_id_audits": {"x_a": "audit"}}, "benchmark.native_id_audits"),  # not an enabled extension
        ({"extensions": ["x_a"], "native_id_audits": {"x_a": ""}}, "benchmark.native_id_audits.x_a"),
        ({"extensions": ["x_a"], "native_id_audits": {"x_a": None}}, "benchmark.native_id_audits.x_a"),
    ],
)
def test_extensions_and_native_id_audits_are_checked(changes: dict[str, Any], field: str) -> None:
    # Spec 14: extension names match x_[a-z0-9_]+, and a native-id audit names an enabled extension.
    assert _refused(_value(**changes)).startswith(f"{field}: ")


@pytest.mark.parametrize(
    "field,bad",
    [
        ("pairs_per_deck", True), ("pairs_per_deck", 0), ("pairs_per_deck", "2"),
        ("stats_seed", -1), ("stats_seed", True), ("stats_seed", 2**53), ("stats_seed", 1.0),
        ("workers", "8"), ("workers", 0), ("workers", MAX_WORKERS + 1),
        ("bootstrap_replicates", True), ("bootstrap_replicates", 0),
    ],
)
def test_integers_are_checked(field: str, bad: Any) -> None:
    assert _refused(_value(**{field: bad})).startswith(f"benchmark.{field}: ")


def test_the_edges_of_the_integer_ranges_are_accepted() -> None:
    assert definition.parse_benchmark(_value(stats_seed=0)).stats_seed == 0
    assert definition.parse_benchmark(_value(stats_seed=2**53 - 1)).stats_seed == 2**53 - 1
    assert definition.parse_benchmark(_value(workers=MAX_WORKERS)).workers == MAX_WORKERS
    assert definition.parse_benchmark(_value(pairs_per_deck=1)).pairs_per_deck == 1


def test_the_arena_limits_are_checked_when_the_definition_is_read() -> None:
    # The arena's bootstrap range and its draw limit refuse these; the definition refuses them already.
    assert "bootstrap_replicates" in _refused(_value(bootstrap_replicates=500))
    assert "bootstrap" in _refused(_value(pairs_per_deck=30000))


def test_the_tournament_config_rotates_the_pool_without_self_play() -> None:
    config = definition.parse_benchmark(_value()).tournament_config("runs/2026-09-26")
    assert config["schema"] == "spellbench-tournament-config/v2"
    assert config["tournament_dir"] == "runs/2026-09-26"
    assert config["format"] == "pauper-bo1"
    assert config["deck_pool"] == [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}]
    assert "decks" not in config
    assert config["pairs_per_matchup"] == 4
    assert config["stats_seed"] == 7
    assert config["rating_anchor"] == "uniform"
    assert config["include_self_play"] is False
    assert config["rules"] == BENCHMARK_RULES
    assert config["engine"] == {"command": ["${MTG_KERNEL_BRIDGE}"]}
    assert config["time_control"] == CLOCKS
    assert config["limits"] == DEFAULT_LIMITS.to_json() and config["resources"] == DEFAULT_RESOURCES.to_json()
    assert config["extensions"] == [] and config["native_id_audits"] == {}
    assert config["bootstrap_replicates"] == DEFAULT_BOOTSTRAP_REPLICATES and config["workers"] == DEFAULT_WORKERS
    assert config["bots"][1]["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]
    assert all("display" not in bot for bot in config["bots"])
    # Every field is written out, so the arena reads the benchmark's values and never its own defaults.
    parsed = TournamentConfig.from_json(config).to_json()
    assert {key: item for key, item in parsed.items() if key != "bots"} == {key: item for key, item in config.items() if key != "bots"}


def test_the_tournament_config_is_a_fresh_copy() -> None:
    benchmark = definition.parse_benchmark(_value(extensions=["x_a"], native_id_audits={"x_a": "audit"}))
    config = benchmark.tournament_config("runs/x")
    config["bots"][1]["command"].append("--oops")
    config["engine"]["command"].append("--oops")
    config["native_id_audits"]["x_b"] = "oops"
    config["extensions"].append("x_b")
    config["rules"]["mulligan"] = "none"
    config["time_control"]["bank_ms"] = 1
    again = benchmark.tournament_config("runs/x")
    assert again["bots"][1]["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]
    assert again["engine"]["command"] == ["${MTG_KERNEL_BRIDGE}"]
    assert again["native_id_audits"] == {"x_a": "audit"} and benchmark.native_id_audits == {"x_a": "audit"}
    assert again["extensions"] == ["x_a"]
    assert again["rules"] == BENCHMARK_RULES and again["time_control"] == CLOCKS


def test_the_definition_does_not_share_its_document() -> None:
    value = _value(extensions=["x_a"], native_id_audits={"x_a": "audit"})
    benchmark = definition.parse_benchmark(value)
    value["bots"][1]["command"].append("--oops")
    value["native_id_audits"]["x_b"] = "oops"
    assert benchmark.bot("mybot").entry["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]
    assert benchmark.native_id_audits == {"x_a": "audit"}


def test_load_benchmark_requires_the_folder_name_to_match_the_id(tmp_path: Path) -> None:
    assert definition.load_benchmark(_write(tmp_path / "pauper-kernel", _value())).id == "pauper-kernel"
    with pytest.raises(BenchmarkError, match="id"):
        definition.load_benchmark(_write(tmp_path / "other", _value()))


def test_load_benchmark_names_the_file_and_the_field(tmp_path: Path) -> None:
    directory = _write(tmp_path / "pauper-kernel", _value(base_seed=7))
    with pytest.raises(BenchmarkError, match=r"benchmark\.json: benchmark\.base_seed: "):
        definition.load_benchmark(directory)


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
    (directory / "benchmark.json").write_text('{"stats_seed": ' + "7" * 5000 + "}", encoding="utf-8")
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


def test_an_empty_environment_value_falls_back_to_the_local_value() -> None:
    assert definition.placeholder_values(["PYTHON"], {"PYTHON": "py-local"}, {"PYTHON": ""}) == {"PYTHON": "py-local"}


def test_every_unresolved_placeholder_is_named() -> None:
    with pytest.raises(BenchmarkError) as caught:
        definition.placeholder_values(["A", "B", "C"], {"A": "x"}, {"C": ""})
    assert "B" in str(caught.value) and "C" in str(caught.value) and "'A'" not in str(caught.value)


def test_substitute_replaces_embedded_placeholders_verbatim() -> None:
    assert definition.substitute("--model=${CKPT_DIR}/model.bin", {"CKPT_DIR": "C:\\models"}) == "--model=C:\\models/model.bin"
    assert definition.substitute("${A}${B}", {"A": "${B}", "B": "b"}) == "${B}b"  # a value is never read again
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


@pytest.mark.parametrize("text", ["${MTG-KERNEL}", "${CKPT_DIR/m.bin", "${}", "${9LIVES}"])
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


# ---------------------------------------------------------------------------
# The committed pauper-kernel definition (Decisions 8 and 11)
# ---------------------------------------------------------------------------


def test_the_committed_pauper_kernel_definition_is_v2() -> None:
    benchmark = definition.load_benchmark(REPO / "benchmarks" / "pauper-kernel")
    assert benchmark.stats_seed == 20260926 and {bot.entry["version"] for bot in benchmark.bots if bot.entry["type"] == "builtin"} == {"2.0.0"}
    TournamentConfig.from_json(benchmark.tournament_config("runs/check"))


def test_the_migration_carries_every_v1_value_to_its_v2_field() -> None:
    # The latest committed v1 run recorded the v1 definition's arena config; the run itself stays v1.
    recorded = json.loads((PAUPER_KERNEL / "runs" / "2026-09-27" / "config.json").read_text(encoding="utf-8"))
    assert recorded["schema"] == "spellbench-tournament-config/v1"
    benchmark = definition.load_benchmark(PAUPER_KERNEL)
    config = TournamentConfig.from_json(benchmark.tournament_config(recorded["tournament_dir"])).to_json()
    assert config["stats_seed"] == recorded["base_seed"]
    assert config["time_control"] == {**CLOCKS, "startup_ms": recorded["startup_timeout_ms"],
                                      "max_decision_ms": recorded["choose_timeout_ms"], "engine_step_ms": recorded["engine"]["timeout_ms"]}
    assert config["engine"] == {"command": recorded["engine"]["command"]}  # the engine flag carries over
    assert config["limits"] == DEFAULT_LIMITS.to_json()
    assert (config["limits"]["max_decisions"], config["limits"]["max_steps"]) == (recorded["max_decisions"], recorded["max_steps"])
    for field in ("tournament_dir", "format", "deck_pool", "pairs_per_matchup", "bootstrap_replicates", "workers",
                  "rating_anchor", "include_self_play"):
        assert config[field] == recorded[field], field
    # Every bot entry carries over, the kernel bots included; only the builtins move to 2.0.0.
    assert config["bots"] == [{**bot, "version": "2.0.0"} if bot["type"] == "builtin" else bot for bot in recorded["bots"]]
    assert config["rules"] == BENCHMARK_RULES
    assert config["extensions"] == [] and config["native_id_audits"] == {}  # K2 sets them with the v2 bridge
    assert config["resources"] == DEFAULT_RESOURCES.to_json()


def test_the_committed_definition_keeps_the_kernel_bots_and_their_display() -> None:
    benchmark = definition.load_benchmark(PAUPER_KERNEL)
    assert [bot.name for bot in benchmark.bots] == ["uniform", "heuristic", "first", "g115", "a48", "c12"]
    assert benchmark.engine_command == ("${MTG_KERNEL_BRIDGE}", "--x-kernel-flat-v4")
    assert benchmark.deck_pool == tuple(
        DeckSpec(catalog_id=name) for name in ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
    )
    assert benchmark.bot("uniform").display.label == "random"
    for name in ("g115", "a48", "c12"):
        bot = benchmark.bot(name)
        assert (bot.entry["type"], bot.entry["version"], bot.entry["engine"]) == ("subprocess", "1.0.0", "mtg-kernel"), name
        assert bot.entry["checkpoint"] == f"${{{name.upper()}_CHECKPOINT}}" and bot.display.label == name


def test_the_committed_placeholders_resolve_from_the_environment_or_local_json(tmp_path: Path) -> None:
    # README: ${NAME} resolves from the environment, else from the git-ignored benchmarks/local.json.
    benchmark = definition.load_benchmark(PAUPER_KERNEL)
    assert definition.placeholder_names(benchmark) == KERNEL_PLACEHOLDERS
    (tmp_path / "local.json").write_text(
        json.dumps({name: f"C:/local/{name.lower()}" for name in KERNEL_PLACEHOLDERS}), encoding="utf-8"
    )
    local = definition.load_local_values(tmp_path)
    values = definition.placeholder_values(definition.placeholder_names(benchmark), local, {"PYTHON": "/usr/bin/python3"})
    assert values["PYTHON"] == "/usr/bin/python3" and values["MTG_KERNEL_BRIDGE"] == "C:/local/mtg_kernel_bridge"
    config = TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
    executed = runner.executed_config(config, lambda text: definition.substitute(text, values))
    assert executed.engine_command == ("C:/local/mtg_kernel_bridge", "--x-kernel-flat-v4")
    g115 = next(spec for spec in executed.bots if spec.name == "g115")
    assert g115.command[:5] == ("/usr/bin/python3", "C:/local/mtg_kernel_flat_bot", "--scorer", "C:/local/mtg_kernel_scorer", "--config")
    assert g115.checkpoint == "C:/local/g115_checkpoint"
    parts = [*executed.engine_command, *(part for spec in executed.bots for part in spec.command)]
    parts += [spec.checkpoint for spec in executed.bots if spec.checkpoint is not None]
    assert not any("${" in part for part in parts)  # the names cover every placeholder the arena resolves
    del local["G115_CHECKPOINT"]
    with pytest.raises(BenchmarkError, match="G115_CHECKPOINT"):
        definition.placeholder_values(definition.placeholder_names(benchmark), local, {})
