"""The site build: validated runs in, static pages out."""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from spellbench.arena import cli, runner, store
from spellbench.bench import definition
from spellbench.site import build, render
from spellbench.site.build import SiteError, build_site

from arena_helpers import BOT_INVALID_CHOICE, FAKE_ARENA_ENGINE, TESTS_DIR, cli_bot

BOT_ONE_LAND = TESTS_DIR / "bot_one_land.py"
RUN_FILES = ("manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md")
HOSTILE = '<script>alert("x")</script>'
GE, LE, NBSP = "≥", "≤", " "  # a bound's sign, then a no-break space before its number


def _bot(name: str, label: str, tag: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name, "version": "1.0.0", "type": "builtin", "training_style_tags": [tag], **extra,
        "display": {"label": label, "author": "Spellbench", "description": f"{name} bot", "url": None},
    }


def _definition(bench_id: str, labels: dict[str, str] | None = None) -> dict[str, Any]:
    labels = labels or {}
    return {
        "schema": "spellbench-benchmark/v1",
        "id": bench_id,
        "title": f"Bench {bench_id}",
        "summary": "Three decks on the fake arena engine.",
        "format": "pauper-bo1",
        "engine": {"name": "fake-arena-engine", "command": [sys.executable, str(FAKE_ARENA_ENGINE)], "timeout_ms": 30000},
        "deck_pool": ["Burn", "Elves", "Faeries"],
        "pairs_per_deck": 1,
        "base_seed": 99,
        "bootstrap_replicates": 1000,
        "bots": [
            _bot("uniform", labels.get("uniform", "random"), "baseline", seed=11),
            _bot("heuristic", labels.get("heuristic", "heuristic"), "heuristic"),
            _bot("first", labels.get("first", "first"), "baseline"),
        ],
    }


def _add_benchmark(root: Path, bench_id: str, *, runs: tuple[str, ...] = ("2026-09-26",), anchor: str | None = None,
                   labels: dict[str, str] | None = None) -> Path:
    directory = root / bench_id
    directory.mkdir(parents=True)
    (directory / "benchmark.json").write_text(json.dumps(_definition(bench_id, labels), indent=2), encoding="utf-8")
    benchmark = definition.load_benchmark(directory)
    for name in runs:
        config = benchmark.tournament_config(f"runs/{name}")
        if anchor is not None:
            config["rating_anchor"] = anchor
        runner.run_tournament(runner.TournamentConfig.from_json(config), output_dir=directory / "runs" / name)
    return directory


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Benchmarks alpha and beta with one run each, plus proposed.json."""
    root = tmp_path_factory.mktemp("benchmarks")
    _add_benchmark(root, "alpha")
    _add_benchmark(root, "beta")
    proposed = {"schema": "spellbench-proposed-benchmarks/v1",
                "proposed": [{"title": "FDN Limited", "summary": "Foundations limited games.", "needs": "an engine"}]}
    (root / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8")
    return root


@pytest.fixture
def copy_tree(tree: Path, tmp_path: Path) -> Path:
    target = tmp_path / "benchmarks"
    shutil.copytree(tree, target)
    return target


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.links.append(value)


def _files(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file()}


def _html(page: str, tag: str, attribute: str, value: str) -> str:
    """The inner HTML of the first ``<tag attribute="value">`` in ``page``."""
    match = re.search(rf'<{tag}\b[^>]*\b{attribute}="{re.escape(value)}"[^>]*>(.*?)</{tag}>', page, re.S)
    assert match, f"no <{tag} {attribute}={value!r}>"
    return match.group(1)


def _element(page: str, tag: str, attribute: str, value: str) -> str:
    """The text of the first ``<tag attribute="value">``, each tag replaced by a space."""
    return re.sub(r"<[^>]+>", " ", _html(page, tag, attribute, value))


def _bound(row: dict[str, Any], board: dict[str, Any]) -> str | None:
    """The site's bound for a leaderboard row, derived here from the rule rather than the build.

    Only a record of wins alone (or losses alone) is a bound: a draw gives each side half a point,
    so a record with a draw has a finite best-fit rating.
    """
    if row["bot_id"] == board["anchor"]["bot_id"] or not row["rated"] or row["draws"]:
        return None
    if row["wins"] and not row["losses"]:
        return "lower"
    if row["losses"] and not row["wins"]:
        return "upper"
    return None


def test_the_site_has_every_page_and_run_file(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    for page in ("index.html", "join.html", "method.html", "b/alpha/index.html", "b/beta/index.html"):
        assert (out / page).is_file(), page
    for name in RUN_FILES:
        assert (out / "b/alpha/run" / name).read_bytes() == (tree / "alpha/runs/2026-09-26" / name).read_bytes()


def test_every_internal_link_resolves(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    for page in out.rglob("*.html"):
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        for link in parser.links:
            parts = urlsplit(link)
            if parts.scheme or link.startswith("#"):
                continue
            assert (page.parent / parts.path).resolve().is_file(), f"{page.relative_to(out)} -> {link}"


def test_benchmark_numbers_match_the_leaderboard(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    overall = page[page.index('data-panel="overall"'):]
    board = json.loads((tree / "alpha/runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8"))
    for row in board["rows"]:
        text = _element(overall, "tr", "data-bot", row["name"])
        assert render.format_elo(row["elo_milli"]) in text
        assert f'{row["wins"]}-{row["draws"]}-{row["losses"]}' in text
    for deck in ("Burn", "Elves", "Faeries"):
        assert f'data-deck="{deck}"' in page


def test_the_hero_chart_uses_the_random_anchor(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "random" in _element(home, "li", "data-bot", "uniform")
    boards = [json.loads((tree / b / "runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8")) for b in ("alpha", "beta")]
    margins = [(next(r for r in board["rows"] if r["name"] == "heuristic")["elo_milli"] - 1_000_000) / 1000 for board in boards]
    assert render.format_margin(sum(margins) / 2) in _element(home, "li", "data-bot", "heuristic")


def test_two_builds_are_byte_identical_with_unix_newlines(tree: Path, tmp_path: Path) -> None:
    build_site(tree, tmp_path / "one")
    build_site(tree, tmp_path / "two")
    one, two = _files(tmp_path / "one"), _files(tmp_path / "two")
    assert one == two
    assert all(b"\r\n" not in data for name, data in one.items() if name.endswith(".html"))


def test_a_rebuild_replaces_the_previous_output(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    (out / "stale.html").write_text("old", encoding="utf-8")
    build_site(tree, out)
    assert not (out / "stale.html").exists()


def test_the_build_refuses_a_directory_it_did_not_make(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    out.mkdir()
    (out / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SiteError, match="refusing"):
        build_site(tree, out)
    assert (out / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_tampered_run_is_refused_and_nothing_is_written(copy_tree: Path, tmp_path: Path) -> None:
    ledger = copy_tree / "beta/runs/2026-09-26/matches.jsonl"
    data = ledger.read_bytes()
    ledger.write_bytes(data.replace(b'"reason":"score"', b'"reason":"SCORE"', 1))
    out = tmp_path / "site"
    with pytest.raises(SiteError, match="beta"):
        build_site(copy_tree, out)
    assert not out.exists()


def test_a_benchmark_without_a_run_gets_a_card_and_a_warning(copy_tree: Path, tmp_path: Path) -> None:
    fresh = copy_tree / "gamma"
    fresh.mkdir()
    (fresh / "benchmark.json").write_text(json.dumps(_definition("gamma"), indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("gamma" in warning and "no published run" in warning for warning in warnings)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "Bench gamma" in home and "No published run yet" in home
    assert not (out / "b/gamma").exists()


def test_an_unfinished_run_is_skipped_with_a_warning(copy_tree: Path, tmp_path: Path) -> None:
    unfinished = copy_tree / "alpha/runs/2026-09-27"
    unfinished.mkdir()
    (unfinished / "config.json").write_text("{}", encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("2026-09-27" in warning for warning in warnings)
    assert "2026-09-26" in (out / "b/alpha/index.html").read_text(encoding="utf-8")


def test_a_changed_definition_still_renders_the_run_and_warns(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha")
    changed["bots"] = changed["bots"][:2]  # "first" removed after the run
    (copy_tree / "alpha/benchmark.json").write_text(json.dumps(changed, indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert "alpha: benchmark.json changed since run 2026-09-26 (differs in bot names); rerun to publish the change" in warnings
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    assert "first" in _element(page[page.index('data-panel="overall"'):], "tr", "data-bot", "first")


def _overall_row(page: str, name: str) -> str:
    """The inner HTML of bot ``name``'s row in the Overall table."""
    return _html(page[page.index('data-panel="overall"'):], "tr", "data-bot", name)


def test_a_changed_bot_entry_warns_and_shows_the_rated_bot(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha", labels={"heuristic": "heuristic v2 (MCTS)"})
    changed["bots"][1]["seed"] = 7  # the arena entry changed after the run, as a new command or checkpoint would
    changed["bots"][1]["display"].update(description="Search with rollouts.", url="https://example.com/mcts")
    (copy_tree / "alpha/benchmark.json").write_text(json.dumps(changed, indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert (
        "alpha: benchmark.json changed since run 2026-09-26 (differs in bot 'heuristic'); rerun to publish the change"
        in warnings
    )
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    row = _overall_row(page, "heuristic")
    # the registry name and owner of the bot that was rated: no new label, description, or link
    assert '<span class="label">heuristic</span>' in row
    assert "v2" not in row and "rollouts" not in row and "example.com" not in row
    assert "unspecified" in row  # the registry owner: the entry names none
    assert "heuristic 1.0.0" in re.sub(r"<[^>]+>", " ", row)
    assert '<span class="label" title="uniform bot">random</span>' in _overall_row(page, "uniform")  # unchanged entry
    # the Hero row takes its label from alpha, the first benchmark listing the bot: the registry identity there too
    hero = _html((out / "index.html").read_text(encoding="utf-8"), "li", "data-bot", "heuristic")
    assert '<span class="name">heuristic</span><span class="by">unspecified</span>' in hero and "v2" not in hero


def test_a_changed_setting_is_named_in_the_warning(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha")
    changed.update(base_seed=100, pairs_per_deck=2)
    (copy_tree / "alpha/benchmark.json").write_text(json.dumps(changed, indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert (
        "alpha: benchmark.json changed since run 2026-09-26 (differs in base_seed, pairs_per_matchup); "
        "rerun to publish the change" in warnings
    )
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    assert '<span class="label" title="heuristic bot">heuristic</span>' in _overall_row(page, "heuristic")


def test_a_relabel_is_live_and_every_row_shows_the_rated_name_and_version(copy_tree: Path, tmp_path: Path) -> None:
    # Display text is not recorded in runs, so a relabel cannot be detected; the rated identity stays visible.
    relabelled = _definition("alpha", labels={"heuristic": "heuristic v2 (MCTS)"})
    (copy_tree / "alpha/benchmark.json").write_text(json.dumps(relabelled, indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert not [warning for warning in warnings if "changed since run" in warning]
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    text = re.sub(r"<[^>]+>", " ", _overall_row(page, "heuristic"))
    assert "heuristic v2 (MCTS)" in text and "heuristic 1.0.0" in text
    for name in ("uniform", "first"):
        assert f"{name} 1.0.0" in re.sub(r"<[^>]+>", " ", _overall_row(page, name))


def test_the_hero_warns_when_one_name_covers_different_registry_bots(copy_tree: Path, tmp_path: Path) -> None:
    value = _definition("delta")
    value["bots"][1] = {  # "heuristic" served as a subprocess: another descriptor, so another bot id
        "name": "heuristic", "version": "1.0.0", "type": "subprocess", "command": cli_bot("heuristic"),
        "training_style_tags": ["heuristic"],
        "display": {"label": "heuristic", "author": "Spellbench", "description": "heuristic bot", "url": None},
    }
    _publish(copy_tree, value)
    warnings = build_site(copy_tree, tmp_path / "site")
    assert (
        "Hero chart: 'heuristic' averages different registry bots (different bot ids) across benchmarks alpha, beta, delta"
        in warnings
    )
    assert not [warning for warning in warnings if "'first'" in warning]  # the same builtin everywhere


def test_hostile_labels_are_escaped(tmp_path: Path) -> None:
    root = tmp_path / "benchmarks"
    _add_benchmark(root, "alpha", labels={"heuristic": HOSTILE})
    out = tmp_path / "site"
    build_site(root, out)
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert "<script>alert" not in text, page.name
    assert "&lt;script&gt;" in (out / "b/alpha/index.html").read_text(encoding="utf-8")


def test_an_unanchored_run_is_left_out_of_the_hero_chart(copy_tree: Path, tmp_path: Path) -> None:
    _add_benchmark(copy_tree, "delta", anchor="heuristic")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("delta" in warning and "heuristic" in warning for warning in warnings)
    hero = (out / "index.html").read_text(encoding="utf-8")
    hero = hero[hero.index('id="hero"'):hero.index('id="benchmarks"')]
    assert "delta" not in hero and "alpha" in hero


def test_the_cli_builds_the_site(tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "site"
    assert cli.main(["site", str(tree), str(out)]) == 0
    assert "site built" in capsys.readouterr().out
    assert cli.main(["site", str(tree)]) == 2


def _publish(root: Path, value: dict[str, Any]) -> Path:
    """Write benchmark ``value`` under ``root`` and publish its run 2026-09-26; returns the run directory."""
    directory = root / value["id"]
    directory.mkdir(parents=True)
    (directory / "benchmark.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    config = definition.load_benchmark(directory).tournament_config("runs/2026-09-26")
    runner.run_tournament(runner.TournamentConfig.from_json(config), output_dir=directory / "runs/2026-09-26")
    return directory / "runs/2026-09-26"


def _assert_overall_rows(page: str, board: dict[str, Any]) -> None:
    """Each overall row shows the anchor mark, interval or bound, games and forfeits of its ``board`` row."""
    overall = page[page.index('data-panel="overall"'):]
    for row in board["rows"]:
        cells = re.search(rf'<tr data-bot="{row["name"]}">(.*?)</tr>', overall, re.S).group(1)
        is_anchor = row["bot_id"] == board["anchor"]["bot_id"]
        assert ("anchor" in _element(overall, "tr", "data-bot", row["name"]).split()) == is_anchor, row["name"]
        elo, bound = render.format_elo(row["elo_milli"]), _bound(row, board)
        if bound == "lower":
            assert f"at least {elo} Elo, unbeaten: the rating is limited by the prior" in cells, row["name"]
        elif bound == "upper":
            assert f"at most {elo} Elo, winless: the rating is limited by the prior" in cells, row["name"]
        elif not is_anchor:
            low, high = (render.format_elo(bound) for bound in row["ci95_elo_milli"])
            assert f"95% interval {low} to {high}" in cells, row["name"]
        assert f'<td class="num">{row["games"]}</td>\n<td class="num">{row["forfeit_losses"]}</td>' in cells


def test_every_leaderboard_number_reaches_the_benchmark_page(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    board = json.loads((tree / "alpha/runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8"))
    _assert_overall_rows(page, board)
    names = {row["bot_id"]: row["name"] for row in board["rows"]}
    for matchup in board["matchups"]:
        a, b = names[matchup["a_bot_id"]], names[matchup["b_bot_id"]]
        share = matchup["a_score"]["num"] / matchup["a_score"]["den"]
        pairs = matchup["complete_pairs"]
        sample = f"over {pairs} complete pair{'s' if pairs != 1 else ''} ({2 * pairs} games)"
        for row, col, expected in ((a, b, share), (b, a, 1 - share)):
            cell = re.search(rf'<td data-row="{row}" data-col="{col}" title="([^"]*)"[^>]*>([^<]*)</td>', page)
            assert cell and cell.groups() == (sample, render.format_share(expected)), (row, col)
    for deck_slice in board["slices"]["deck"]:
        section = page[page.index(f'data-deck="{deck_slice["label"]}"'):]
        for row in deck_slice["rows"]:
            text = _element(section, "tr", "data-bot", row["name"])
            assert render.format_elo(row["elo_milli"]) in text
            assert f'{row["wins"]}-{row["draws"]}-{row["losses"]}' in text


def test_the_recheck_command_runs_from_a_fresh_clone(tree: Path, tmp_path: Path) -> None:
    # A fresh clone has no spellbench on PATH; uv run installs the project and runs it.
    out = tmp_path / "site"
    build_site(tree, out)
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    assert "<pre><code>uv run spellbench validate benchmarks/alpha/runs/2026-09-26</code></pre>" in page


def test_a_bot_that_won_every_game_is_shown_as_a_bound(tree: Path, tmp_path: Path) -> None:
    # On the fake engine heuristic scores two points a game and first none: heuristic never loses, first never wins.
    out = tmp_path / "site"
    build_site(tree, out)
    boards = {b: json.loads((tree / b / "runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8")) for b in ("alpha", "beta")}
    rows = {row["name"]: row for row in boards["alpha"]["rows"]}
    assert rows["heuristic"]["wins"] > 0 == rows["heuristic"]["draws"] == rows["heuristic"]["losses"]
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    top = _html(page[page.index('data-panel="overall"'):], "tr", "data-bot", "heuristic")
    high = render.format_elo(rows["heuristic"]["elo_milli"])
    assert f"{GE}{NBSP}{high}" in top and ">unbeaten<" in top and 'class="arrow"' in top
    assert f'aria-label="at least {high} Elo, unbeaten: the rating is limited by the prior"' in top
    # first lost every game on Faeries: an upper bound in that deck's table
    faeries = next(deck for deck in boards["alpha"]["slices"]["deck"] if deck["label"] == "Faeries")
    first = next(row for row in faeries["rows"] if row["name"] == "first")
    assert first["losses"] > 0 == first["wins"] == first["draws"]
    bottom = _html(_section(page, 'data-deck="Faeries"'), "tr", "data-bot", "first")
    assert f"{LE}{NBSP}{render.format_elo(first['elo_milli'])}" in bottom and ">winless<" in bottom
    assert 'class="arrow"' in bottom
    # the Hero row averages two lower bounds: a lower bound, drawn with an arrow
    hero = _html((out / "index.html").read_text(encoding="utf-8"), "li", "data-bot", "heuristic")
    margins = {
        b: (next(row for row in board["rows"] if row["name"] == "heuristic")["elo_milli"] - 1_000_000) / 1000
        for b, board in boards.items()
    }
    assert f'<span class="value">{GE}{NBSP}{render.format_margin(sum(margins.values()) / 2)}</span>' in hero
    assert 'class="arrow"' in hero and 'class="whisker"' not in hero
    for bench, margin in margins.items():
        assert f"{bench} {GE}{NBSP}{render.format_margin(margin)}" in hero


def test_a_bot_with_a_draw_is_not_a_bound(tree: Path, tmp_path: Path) -> None:
    # Overall, first never won but drew against uniform: its rating is finite, so it shows its interval.
    out = tmp_path / "site"
    build_site(tree, out)
    board = json.loads((tree / "alpha/runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8"))
    first = next(row for row in board["rows"] if row["name"] == "first")
    assert first["wins"] == 0 < first["draws"] and first["losses"] > 0
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    row = _html(page[page.index('data-panel="overall"'):], "tr", "data-bot", "first")
    elo = render.format_elo(first["elo_milli"])
    low, high = (render.format_elo(end) for end in first["ci95_elo_milli"])
    assert f'<td class="num elo">{elo}</td>' in row and "winless" not in row and 'class="arrow"' not in row
    assert f'aria-label="Elo {elo}, 95% interval {low} to {high}"' in row
    hero = _html((out / "index.html").read_text(encoding="utf-8"), "li", "data-bot", "first")
    assert LE not in hero and 'class="arrow"' not in hero and 'class="whisker"' in hero


def test_an_unrated_deck_is_reported_and_the_site_still_builds(tmp_path: Path) -> None:
    value = _definition("halting")
    value["deck_pool"] = ["Burn", "Halt"]  # the fake engine halts every game on the Halt deck
    run_dir = _publish(tmp_path / "benchmarks", value)
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert [deck_slice["status"] for deck_slice in board["slices"]["deck"]] == ["ok", "no_rated_games"]
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    page = (tmp_path / "site/b/halting/index.html").read_text(encoding="utf-8")
    assert "Not rated: no rated games" in _element(page, "section", "data-deck", "Halt")
    games = board["games"]
    assert f'{games["total"]} games: {games["rated"]} rated, {games["halted"]} halted' in page


@pytest.mark.parametrize(
    ("status", "fit_error", "reason"),
    [
        ("ok", None, None),
        ("no_rated_games", None, "no rated games"),
        ("fit_failed", "reference_id has no games", "the random bot has no complete pair on this deck"),
        ("fit_failed", "comparison graph is disconnected", "the ratings could not be fitted"),
    ],
)
def test_a_deck_table_explains_why_it_is_not_rated(status: str, fit_error: str | None, reason: str | None) -> None:
    # The fake engine cannot leave the anchor without a complete pair on one deck, so the slice is built here.
    deck_slice = {"label": "Elves", "status": status, "fit_error": fit_error, "rows": []}
    table = build._deck_table(deck_slice, "a" * 64, {})
    assert (table["status"], table["reason"], table["fit_error"]) == (status, reason, fit_error)


def test_forfeits_reach_the_benchmark_page(tmp_path: Path) -> None:
    value = _definition("forfeits")
    value["deck_pool"] = ["Burn"]
    bad = {"name": "bad-invalid", "version": "1.0.0", "type": "subprocess", "command": [sys.executable, str(BOT_INVALID_CHOICE)],
           "display": {"label": "bad", "author": "Tests", "description": "Answers every choice out of range.", "url": None}}
    value["bots"] = [value["bots"][0], bad]
    run_dir = _publish(tmp_path / "benchmarks", value)
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert [row["forfeit_losses"] for row in board["rows"] if row["name"] == "bad-invalid"] == [2]
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    _assert_overall_rows((tmp_path / "site/b/forfeits/index.html").read_text(encoding="utf-8"), board)


def test_a_fixed_pair_run_shows_its_one_pairing(tmp_path: Path) -> None:
    decklist = {"decklist": [{"name": "Mountain", "count": 60}]}
    directory = tmp_path / "benchmarks/fixed"
    directory.mkdir(parents=True)
    (directory / "benchmark.json").write_text(json.dumps(_definition("fixed"), indent=2), encoding="utf-8")
    config = definition.load_benchmark(directory).tournament_config("runs/2026-09-26")
    del config["deck_pool"]
    config.update(decks=[decklist, {"catalog_id": "Burn"}], pairs_per_matchup=2)
    runner.run_tournament(runner.TournamentConfig.from_json(config), output_dir=directory / "runs/2026-09-26")
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    page = (tmp_path / "site/b/fixed/index.html").read_text(encoding="utf-8")
    label = "decklist " + store.sha256_hex(store.canonical_bytes(decklist))[:12]  # as the leaderboard labels it
    assert f"<dt>Decks</dt><dd>{label} vs Burn</dd>" in page
    assert "<dt>Schedule</dt><dd>2 seat-swapped pairs per deck in each matchup</dd>" in page


def test_a_benchmark_whose_only_run_is_unfinished_shows_no_run(copy_tree: Path, tmp_path: Path) -> None:
    fresh = copy_tree / "gamma"
    (fresh / "runs/2026-09-26").mkdir(parents=True)
    (fresh / "runs/2026-09-26/config.json").write_text("{}", encoding="utf-8")
    (fresh / "benchmark.json").write_text(json.dumps(_definition("gamma"), indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert "gamma: runs/2026-09-26 has no manifest.json (an unfinished run); showing no run" in warnings
    assert "gamma: no published run yet" in warnings
    assert "No published run yet" in (out / "index.html").read_text(encoding="utf-8")
    assert not (out / "b/gamma").exists()


def test_pages_hold_no_local_paths(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    local = (str(tree), tree.as_posix(), str(out), out.as_posix(), sys.executable, str(FAKE_ARENA_ENGINE))
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert not [path for path in local if path in text], page.name


def test_an_arena_level_definition_error_names_the_benchmark(copy_tree: Path, tmp_path: Path) -> None:
    broken = _definition("alpha")
    broken["bootstrap_replicates"] = 10  # benchmark.json allows it; the arena needs at least 1000
    (copy_tree / "alpha/benchmark.json").write_text(json.dumps(broken, indent=2), encoding="utf-8")
    out = tmp_path / "site"
    with pytest.raises(SiteError, match="^alpha: config.bootstrap_replicates"):
        build_site(copy_tree, out)
    assert not out.exists()


def test_a_missing_benchmarks_directory_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "site"
    with pytest.raises(SiteError, match="no benchmarks directory"):
        build_site(tmp_path / "missing", out)
    assert not out.exists()


def test_the_build_never_replaces_the_benchmarks_it_reads(copy_tree: Path) -> None:
    for directory in (copy_tree, copy_tree.parent):
        (directory / ".spellbench-site").write_text("planted\n", encoding="utf-8")  # as if a build had run there
    before = _files(copy_tree.parent)
    for out in (copy_tree, copy_tree.parent):
        with pytest.raises(SiteError, match="refusing"):
            build_site(copy_tree, out)
        assert _files(copy_tree.parent) == before


# ---------------- every number on the site, checked against leaderboard.json ----------------


@pytest.fixture(scope="module")
def checked(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """A site built from one benchmark, "gamma", holding every kind of leaderboard row, and its leaderboard.json.

    On the fake engine heuristic wins every game (a lower bound), first never
    wins (an upper bound where it also never drew, else an interval), and
    one-land beats first and loses to heuristic: an ordinary interval overall
    and, with one pair per deck, a zero-width one ("interval not estimable")
    in every deck table. uniform is the anchor.
    """
    root = tmp_path_factory.mktemp("checked")
    value = _definition("gamma")
    value["workers"] = 4  # the ledger is the same for any worker count
    value["bots"].append(
        {
            "name": "one-land", "version": "1.0.0", "type": "subprocess", "command": [sys.executable, str(BOT_ONE_LAND)],
            "training_style_tags": ["baseline"],
            "display": {"label": "one land", "author": "Tests", "description": "Plays one land a game.", "url": None},
        }
    )
    run_dir = _publish(root / "benchmarks", value)
    build_site(root / "benchmarks", root / "site")
    return root / "site", json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))


def _section(page: str, marker: str) -> str:
    """The HTML from ``marker`` to the end of its section."""
    start = page.index(marker)
    return page[start:page.index("</section>", start)]


def _aria_label(fragment: str) -> str:
    match = re.search(r'aria-label="([^"]*)"', fragment)
    assert match, fragment
    return html.unescape(match.group(1))


def _check_table(section: str, rows: list[dict[str, Any]], board: dict[str, Any]) -> set[str]:
    """Check one rendered leaderboard against its leaderboard.json ``rows``; returns the kinds of rows seen."""
    assert re.findall(r'<tr data-bot="([^"]*)">', section) == [row["name"] for row in rows]
    kinds: set[str] = set()
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", _html(section, "tr", "data-bot", row["name"]), re.S)
        rank, bot, elo_cell, ci_cell, wdl, games, forfeits = cells
        assert rank == ("-" if row["rank"] is None else str(row["rank"])), row["name"]
        assert f'>{row["name"]} {row["version"]}</span>' in bot, row["name"]  # the rated identity
        assert wdl == f'{row["wins"]}-{row["draws"]}-{row["losses"]}', row["name"]
        assert (games, forfeits) == (str(row["games"]), str(row["forfeit_losses"])), row["name"]
        if row["elo_milli"] is None:
            assert (elo_cell, ci_cell) == ('<span class="muted">unrated</span>', ""), row["name"]
            kinds.add("unrated")
            continue
        elo, interval, bound = render.format_elo(row["elo_milli"]), row["ci95_elo_milli"], _bound(row, board)
        assert elo_cell.split("<", 1)[0] == {"lower": GE + NBSP, "upper": LE + NBSP}.get(bound, "") + elo, row["name"]
        assert (">unbeaten<" in elo_cell, ">winless<" in elo_cell) == (bound == "lower", bound == "upper"), row["name"]
        if row["bot_id"] == board["anchor"]["bot_id"]:
            kind, label = "anchor", f"Elo {elo}, the anchor"
        elif bound == "lower":
            kind, label = "lower", f"at least {elo} Elo, unbeaten: the rating is limited by the prior"
        elif bound == "upper":
            kind, label = "upper", f"at most {elo} Elo, winless: the rating is limited by the prior"
        elif interval is None:
            kind, label = "no interval", f"Elo {elo}, no interval"
        elif interval[0] == interval[1]:
            kind, label = "not estimable", None
        else:
            low, high = (render.format_elo(end) for end in interval)
            kind, label = "interval", f"Elo {elo}, 95% interval {low} to {high}"
        if label is None:
            assert ci_cell == '<span class="ci-text">interval not estimable</span>', row["name"]
        else:
            assert _aria_label(ci_cell) == label, row["name"]
        assert ('class="arrow"' in ci_cell) == (bound is not None), row["name"]
        kinds.add(kind)
    return kinds


def _in_words(margin: float, bound: str | None) -> str:
    """A Hero margin as the aria text words it."""
    rounded = round(margin)
    if rounded > 0:
        text = f"{rounded} Elo above random"
    elif rounded < 0:
        text = f"{-rounded} Elo below random"
    else:
        text = "level with random"
    if bound is None:
        return text
    return ("at least " if (bound == "lower") == (rounded >= 0) else "at most ") + text


def test_every_number_on_the_site_matches_the_leaderboard(checked: tuple[Path, dict[str, Any]]) -> None:
    site, board = checked
    page = (site / "b/gamma/index.html").read_text(encoding="utf-8")
    games = board["games"]
    assert f'{games["total"]} games: {games["rated"]} rated' in page

    # the overall, training-style, and deck tables
    kinds = _check_table(_section(page, 'data-panel="overall"'), board["rows"], board)
    for tag in sorted({tag for row in board["rows"] for tag in row["training_style_tags"]}):
        tagged = [row for row in board["rows"] if tag in row["training_style_tags"]]
        _check_table(_section(page, f'data-tag="{tag}"'), tagged, board)
    for deck_slice in board["slices"]["deck"]:
        section = _section(page, f'data-deck="{deck_slice["label"]}"')
        assert deck_slice["status"] == "ok"
        kinds |= _check_table(section, deck_slice["rows"], board)
    assert kinds == {"anchor", "lower", "upper", "interval", "not estimable"}  # every kind of row, from real data

    # the matchup grid: every ordered pair of bots, the diagonal included
    names = [row["name"] for row in board["rows"]]
    matchups = {frozenset((matchup["a_name"], matchup["b_name"])): matchup for matchup in board["matchups"]}
    for row_name in names:
        for col_name in names:
            cell = re.search(rf'<td data-row="{row_name}" data-col="{col_name}"([^>]*)>([^<]*)</td>', page)
            assert cell, (row_name, col_name)
            matchup = matchups.get(frozenset((row_name, col_name))) if row_name != col_name else None
            if matchup is None or matchup["a_score"] is None:
                assert cell.groups() == (' class="none"', ""), (row_name, col_name)
                continue
            num, den = matchup["a_score"]["num"], matchup["a_score"]["den"]
            share = num / den if matchup["a_name"] == row_name else (den - num) / den
            pairs = matchup["complete_pairs"]
            assert cell.group(1).startswith(f' title="over {pairs} complete pairs ({2 * pairs} games)"'), (row_name, col_name)
            assert cell.group(2) == render.format_share(share), (row_name, col_name)

    # the Hero chart: one benchmark, so each row is that benchmark's overall row
    home = (site / "index.html").read_text(encoding="utf-8")
    assert f'{games["total"]} games' in home[home.index('id="benchmarks"'):]
    for row in board["rows"]:
        item = _html(home, "li", "data-bot", row["name"])
        if row["bot_id"] == board["anchor"]["bot_id"]:
            assert '<span class="value">0</span>' in item and _aria_label(item) == "0, the reference"
            continue
        margin, bound = (row["elo_milli"] - 1_000_000) / 1000, _bound(row, board)
        value = {"lower": GE + NBSP, "upper": LE + NBSP}.get(bound, "") + render.format_margin(margin)
        assert f'<span class="value">{value}</span>' in item, row["name"]
        assert f'<span class="chip">gamma {value}</span>' in item, row["name"]
        if bound is None:
            low, high = ((end - 1_000_000) / 1000 for end in row["ci95_elo_milli"])
            detail = f"95% interval {render.format_margin(low)} to {render.format_margin(high)}"
        else:
            detail = f"{'unbeaten' if bound == 'lower' else 'winless'} in gamma: the rating is limited by the prior"
        assert _aria_label(item) == f"{_in_words(margin, bound)}, {detail}", row["name"]
        assert ('class="arrow"' in item, 'class="whisker"' in item) == (bound is not None, bound is None), row["name"]
