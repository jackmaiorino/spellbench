"""The site build: validated runs in, static pages out."""

from __future__ import annotations

import copy
import dataclasses
import html
import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import pytest

from spellbench.arena import cli, runner, store
from spellbench.arena.config import TournamentConfig
from spellbench.arena.manifest import commitment_record
from spellbench.arena.validate import REVEAL_SCHEMA, WITHHELD_REASON
from spellbench.bench import definition
from spellbench.run_secret import RunSecret
from spellbench.site import build, render
from spellbench.site.build import SiteError, board_run_dir, build_site

from arena_helpers import (
    FAKE_ENGINE,
    TEST_ENGINE_FILES,
    TEST_PROOF,
    TEST_RUN_SECRET,
    TESTS_DIR,
    cli_bot,
    hostile_bot,
    small_allocation,
)

REPO = Path(__file__).resolve().parents[2]
BOT_ONE_LAND = TESTS_DIR / "bot_one_land.py"
RUN_FILES = ("manifest.json", "COMMITMENT.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json",
             "LEADERBOARD.md")
V1_RUN_FILES = ("manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md")
HOSTILE = '<script>alert("x")</script>'
GE, LE, NBSP = "≥", "≤", "\u00a0"  # a bound's sign, then a no-break space before its number
V1 = f"(protocol{NBSP}v1)"  # a protocol v1 run's label in the Hero and on the Models page (Decision 1, R3-20)


def _bot(name: str, label: str, tag: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name, "version": "2.0.0", "type": "builtin", "training_style_tags": [tag], **extra,
        "display": {"label": label, "author": "Spellbench", "description": f"{name} bot", "url": None},
    }


def _definition(bench_id: str, labels: dict[str, str] | None = None) -> dict[str, Any]:
    labels = labels or {}
    return {
        "schema": "spellbench-benchmark/v2",
        "id": bench_id,
        "title": f"Bench {bench_id}",
        "summary": "Three decks on the fake v2 engine.",
        "format": "pauper-bo1",
        "engine": {"name": "fake-v2-engine", "command": [sys.executable, str(FAKE_ENGINE)]},
        "deck_pool": ["Burn", "Elves", "Faeries"],
        "pairs_per_deck": 1,
        "stats_seed": 99,
        "bootstrap_replicates": 1000,
        "bots": [
            # this seed gives the fixture outcomes the bound tests need under TEST_RUN_SECRET (it mixes into the
            # uniform bot's stream): heuristic never draws, first draws overall and loses every Faeries game
            _bot("uniform", labels.get("uniform", "random"), "baseline", seed=100),
            _bot("heuristic", labels.get("heuristic", "heuristic"), "heuristic"),
            _bot("first", labels.get("first", "first"), "baseline"),
        ],
    }


def _write_definition(directory: Path, value: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "benchmark.json").write_text(json.dumps(value, indent=2), encoding="utf-8", newline="\n")


def _run(directory: Path, name: str, *, rated: bool = True, secret: RunSecret = TEST_RUN_SECRET,
         config_changes: dict[str, Any] | None = None, **kwargs: Any) -> Path:
    """Publish run ``name`` of the benchmark in ``directory`` from its definition; rated unless told otherwise.

    A rated run carries a commitment proof and pinned engine files (Decision 3, R3-7); an unrated one neither.
    ``config_changes`` edits the arena config first, a None value deleting its key.
    """
    config = definition.load_benchmark(directory).tournament_config(f"runs/{name}")
    for key, value in (config_changes or {}).items():
        if value is None:
            del config[key]
        else:
            config[key] = value
    runner.run_tournament(TournamentConfig.from_json(config), run_secret=secret,
                          allocation=small_allocation(config["workers"]),
                          commitment_proof=TEST_PROOF if rated else None,
                          engine_files=TEST_ENGINE_FILES if rated else (), output_dir=directory / "runs" / name,
                          **kwargs)
    return directory / "runs" / name


def _add_benchmark(root: Path, bench_id: str, *, runs: tuple[str, ...] = ("2026-09-26",), anchor: str | None = None,
                   labels: dict[str, str] | None = None) -> Path:
    directory = root / bench_id
    _write_definition(directory, _definition(bench_id, labels))
    for name in runs:
        _run(directory, name, config_changes=None if anchor is None else {"rating_anchor": anchor})
    return directory


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Benchmarks alpha and beta with one rated run each, plus proposed.json."""
    root = tmp_path_factory.mktemp("benchmarks")
    _add_benchmark(root, "alpha")
    _add_benchmark(root, "beta")
    proposed = {"schema": "spellbench-proposed-benchmarks/v1",
                "proposed": [{"title": "FDN Limited", "summary": "Foundations limited games.", "needs": "an engine"}]}
    (root / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def copy_tree(tree: Path, tmp_path: Path) -> Path:
    target = tmp_path / "benchmarks"
    shutil.copytree(tree, target)
    return target


def _build_with_views(root: Path, out: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], dict[str, list[Any]]]:
    """``build_site`` with every view the renderer receives captured, by render function name."""
    views: dict[str, list[Any]] = {}
    for name in ("render_home", "render_models", "render_benchmark"):
        def spy(view: Any, _render: Callable[[Any], str] = getattr(render, name), _name: str = name) -> str:
            views.setdefault(_name, []).append(copy.deepcopy(view))
            return _render(view)
        monkeypatch.setattr(render, name, spy)
    return build_site(root, out), views


def _manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


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
    for page in ("index.html", "models.html", "join.html", "method.html", "b/alpha/index.html", "b/beta/index.html"):
        assert (out / page).is_file(), page
    for name in RUN_FILES:
        assert (out / "b/alpha/run" / name).read_bytes() == (tree / "alpha/runs/2026-09-26" / name).read_bytes()
    assert sorted(path.name for path in (out / "b/alpha/run").iterdir()) == sorted(RUN_FILES)
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    assert re.findall(r'<a href="run/([^"]+)" download>', page) == list(RUN_FILES)  # the commitment after the manifest


def test_every_models_link_resolves_to_a_section(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    models = (out / "models.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="(model-[^"]+)"', models))
    assert ids
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for anchor in re.findall(r'href="(?:\.\./\.\./)?models\.html#(model-[^"]+)"', text):
            assert anchor in ids, f"{page.relative_to(out)} -> {anchor}"


def test_the_nav_on_every_page_includes_models(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        root = "../" * (len(page.relative_to(out).parents) - 1)
        current = ' aria-current="page"' if page.name == "models.html" else ""
        assert f'<li><a href="{root}models.html"{current}>Models</a></li>' in text, page.relative_to(out)


def test_every_benchmark_bot_has_a_models_section_with_its_display_text(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    models = (out / "models.html").read_text(encoding="utf-8")
    for bench_id in ("alpha", "beta"):
        document = json.loads((tree / bench_id / "benchmark.json").read_text(encoding="utf-8"))
        for bot in document["bots"]:
            text = _element(models, "section", "id", f"model-{bot['name']}")
            assert bot["display"]["label"] in text, bot["name"]
            assert bot["display"]["author"] in text and bot["display"]["description"] in text, bot["name"]
            assert "builtin reference bot" in text and f"version {bot['version']}" in text, bot["name"]


def test_the_models_page_shows_each_bots_rating_on_each_benchmark(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    models = (out / "models.html").read_text(encoding="utf-8")
    for bench_id in ("alpha", "beta"):
        board = json.loads((tree / bench_id / "runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8"))
        link = f'<a href="b/{bench_id}/index.html">{bench_id}</a>'  # a v2 run: no protocol v1 label
        for row in board["rows"]:
            section = _html(models, "section", "id", f"model-{row['name']}")
            if row["bot_id"] == board["anchor"]["bot_id"]:
                assert f"{link}: reference</li>" in section, row["name"]
                continue
            if row["elo_milli"] is None:
                assert f'{link}: <span class="muted">unrated</span></li>' in section, row["name"]
                continue
            margin, bound = (row["elo_milli"] - 1_000_000) / 1000, _bound(row, board)
            value = {"lower": GE + NBSP, "upper": LE + NBSP}.get(bound, "") + render.format_margin(margin)
            if bound is not None:
                assert f"{link}: {value}</li>" in section, row["name"]
            elif row["ci95_elo_milli"] is None:
                assert f"{link}: {value} (no interval)</li>" in section, row["name"]
            elif row["ci95_elo_milli"][0] == row["ci95_elo_milli"][1]:
                assert f"{link}: {value} (interval not estimable)</li>" in section, row["name"]
            else:
                low, high = (render.format_margin((end - 1_000_000) / 1000) for end in row["ci95_elo_milli"])
                assert f"{link}: {value} (95% interval {low} to {high})</li>" in section, row["name"]
    assert "(protocol" not in models


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
    _write_definition(copy_tree / "gamma", _definition("gamma"))
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert "gamma: no published run yet" in warnings
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "Bench gamma" in home and "No published run yet" in home
    assert not (out / "b/gamma").exists()


def test_an_unfinished_run_is_skipped_with_a_warning(copy_tree: Path, tmp_path: Path) -> None:
    unfinished = copy_tree / "alpha/runs/2026-09-27"
    unfinished.mkdir()
    (unfinished / "config.json").write_bytes(b"{}\n")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert "alpha: runs/2026-09-27 has no manifest.json (an unfinished run); showing runs/2026-09-26" in warnings
    assert "2026-09-26" in (out / "b/alpha/index.html").read_text(encoding="utf-8")


def test_revealed_and_pending_runs_are_listed_and_reveals_are_checked(copy_tree, tmp_path):
    bench, secret = copy_tree / "alpha", RunSecret(bytes(range(32)))
    for name in ("2026-09-27", "2026-09-28"):
        (bench / "runs" / name).mkdir()
        store.write_json_atomic(bench / "runs" / name / "COMMITMENT.json",
                                commitment_record(run_secret=secret, benchmark_id="alpha", run_label=name))
    reveal = {"schema": REVEAL_SCHEMA, "benchmark_id": "alpha", "run_label": "2026-09-28",
              "commitment": secret.commitment(), "run_secret": secret.hex(), "status": "aborted", "reason": "error"}
    store.write_json_atomic(bench / "runs/2026-09-28/REVEAL.json", reveal)
    build_site(copy_tree, tmp_path / "site")
    page = (tmp_path / "site/b/alpha/index.html").read_text(encoding="utf-8")
    assert "2026-09-27 (pending)" in page and "2026-09-28 (aborted)" in page
    store.write_json_atomic(bench / "runs/2026-09-28/REVEAL.json", {**reveal, "run_secret": "11" * 32})
    with pytest.raises(SiteError, match="2026-09-28"):
        build_site(copy_tree, tmp_path / "site-2")


def test_withheld_run_remains_visible_after_a_newer_board_run(copy_tree, tmp_path):
    bench, name, secret = copy_tree / "alpha", "2026-09-25", RunSecret(bytes(range(32)))
    folder = bench / "runs" / name
    folder.mkdir()
    store.write_json_atomic(folder / "COMMITMENT.json",
                            commitment_record(run_secret=secret, benchmark_id="alpha", run_label=name))
    store.write_json_atomic(folder / "REVEAL.json", {"schema": REVEAL_SCHEMA, "benchmark_id": "alpha",
                            "run_label": name, "commitment": secret.commitment(), "run_secret": None,
                            "status": "aborted", "reason": WITHHELD_REASON})
    build_site(copy_tree, tmp_path / "site")
    page = (tmp_path / "site/b/alpha/index.html").read_text(encoding="utf-8")
    assert "Withheld runs: 2026-09-25 (withheld)" in page and "no games can be verified" in page


def test_first_pending_commitment_is_visible_without_a_rating(copy_tree, tmp_path):
    bench, secret = copy_tree / "gamma", RunSecret(bytes(range(32)))
    _write_definition(bench, _definition("gamma"))
    folder = bench / "runs/2026-10-01"
    folder.mkdir(parents=True)
    store.write_json_atomic(folder / "COMMITMENT.json",
                            commitment_record(run_secret=secret, benchmark_id="gamma", run_label="2026-10-01"))
    build_site(copy_tree, tmp_path / "site")
    home = (tmp_path / "site/index.html").read_text(encoding="utf-8")
    assert "Other runs: 2026-10-01 (pending)" in home and "No published run yet" in home
    assert not (tmp_path / "site/b/gamma").exists()


def test_a_changed_definition_still_renders_the_run_and_warns(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha")
    changed["bots"] = changed["bots"][:2]  # "first" removed after the run
    _write_definition(copy_tree / "alpha", changed)
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert "alpha: benchmark.json changed since run 2026-09-26 (differs in bot names); rerun to publish the change" in warnings
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    assert "first" in _element(page[page.index('data-panel="overall"'):], "tr", "data-bot", "first")


def test_a_bot_removed_from_every_definition_keeps_a_models_section_from_the_runs_records(
    copy_tree: Path, tmp_path: Path
) -> None:
    # Its leaderboard rows and grid headers still link to models.html#model-first, so the section must exist.
    for bench_id in ("alpha", "beta"):
        changed = _definition(bench_id)
        changed["bots"] = changed["bots"][:2]
        _write_definition(copy_tree / bench_id, changed)
    out = tmp_path / "site"
    build_site(copy_tree, out)
    models = (out / "models.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="(model-[^"]+)"', models))
    section = _element(models, "section", "id", "model-first")
    assert "unspecified" in section and "builtin reference bot" in section  # registry identity, no display text
    assert "first bot" not in models  # the removed entry's description stays off the page
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for anchor in re.findall(r'href="(?:\.\./\.\./)?models\.html#(model-[^"]+)"', text):
            assert anchor in ids, f"{page.relative_to(out)} -> {anchor}"


def _overall_row(page: str, name: str) -> str:
    """The inner HTML of bot ``name``'s row in the Overall table."""
    return _html(page[page.index('data-panel="overall"'):], "tr", "data-bot", name)


def test_a_changed_bot_entry_warns_and_shows_the_rated_bot(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha", labels={"heuristic": "heuristic v2 (MCTS)"})
    changed["bots"][1]["seed"] = 7  # the arena entry changed after the run, as a new command or checkpoint would
    changed["bots"][1]["display"].update(description="Search with rollouts.", url="https://example.com/mcts")
    _write_definition(copy_tree / "alpha", changed)
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert (
        "alpha: benchmark.json changed since run 2026-09-26 (differs in bot 'heuristic'); rerun to publish the change"
        in warnings
    )
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    row = _overall_row(page, "heuristic")
    # the registry name and owner of the bot that was rated: no new label, description, or link
    assert '<span class="label"><a href="../../models.html#model-heuristic">heuristic</a></span>' in row
    assert "v2" not in row and "rollouts" not in row and "example.com" not in row
    assert "unspecified" in row  # the registry owner: the entry names none
    assert "heuristic 2.0.0" in re.sub(r"<[^>]+>", " ", row)
    unchanged = '<span class="label"><a href="../../models.html#model-uniform" title="uniform bot">random</a></span>'
    assert unchanged in _overall_row(page, "uniform")  # unchanged entry
    # the Hero row takes its label from alpha, the first benchmark listing the bot: the registry identity there too
    hero = _html((out / "index.html").read_text(encoding="utf-8"), "li", "data-bot", "heuristic")
    assert '<span class="name"><a href="models.html#model-heuristic">heuristic</a></span><span class="by">unspecified</span>' in hero
    assert "v2" not in hero
    # the Models section too: alpha's entry is stale, so the new display text stays off the page
    models = (out / "models.html").read_text(encoding="utf-8")
    section = _html(models, "section", "id", "model-heuristic")
    assert "<h2>heuristic</h2>" in section and "unspecified" in re.sub(r"<[^>]+>", " ", section)
    assert "rollouts" not in models and "example.com" not in models and "v2" not in models


def test_a_changed_setting_is_named_in_the_warning(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha")
    changed.update(stats_seed=100, pairs_per_deck=2)
    _write_definition(copy_tree / "alpha", changed)
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert (
        "alpha: benchmark.json changed since run 2026-09-26 (differs in pairs_per_matchup, stats_seed); "
        "rerun to publish the change" in warnings
    )
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    label = '<span class="label"><a href="../../models.html#model-heuristic" title="heuristic bot">heuristic</a></span>'
    assert label in _overall_row(page, "heuristic")


def test_a_relabel_is_live_and_every_row_shows_the_rated_name_and_version(copy_tree: Path, tmp_path: Path) -> None:
    # Display text is not recorded in runs, so a relabel cannot be detected; the rated identity stays visible.
    relabelled = _definition("alpha", labels={"heuristic": "heuristic v2 (MCTS)"})
    _write_definition(copy_tree / "alpha", relabelled)
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert not [warning for warning in warnings if "changed since run" in warning]
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    text = re.sub(r"<[^>]+>", " ", _overall_row(page, "heuristic"))
    assert "heuristic v2 (MCTS)" in text and "heuristic 2.0.0" in text
    for name in ("uniform", "first"):
        assert f"{name} 2.0.0" in re.sub(r"<[^>]+>", " ", _overall_row(page, name))


def test_the_hero_warns_when_one_name_covers_different_registry_bots(copy_tree: Path, tmp_path: Path) -> None:
    value = _definition("delta")
    value["bots"][1] = {  # "heuristic" served as a subprocess: another descriptor, so another bot id
        "name": "heuristic", "version": "2.0.0", "type": "subprocess", "command": cli_bot("heuristic"),
        "owner": "spellbench", "training_style_tags": ["heuristic"],
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


def _publish(root: Path, value: dict[str, Any], **kwargs: Any) -> Path:
    """Write benchmark ``value`` under ``root`` and publish its rated run 2026-09-26; returns the run directory."""
    directory = root / value["id"]
    _write_definition(directory, value)
    return _run(directory, "2026-09-26", **kwargs)


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
    bad = {**hostile_bot("out-of-range"),
           "display": {"label": "bad", "author": "Tests", "description": "Answers every choice out of range.", "url": None}}
    value["bots"] = [value["bots"][0], bad]
    run_dir = _publish(tmp_path / "benchmarks", value)
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert [row["forfeit_losses"] for row in board["rows"] if row["name"] == "hostile"] == [2]
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    _assert_overall_rows((tmp_path / "site/b/forfeits/index.html").read_text(encoding="utf-8"), board)


def test_a_fixed_pair_run_shows_its_one_pairing(tmp_path: Path) -> None:
    # A benchmark rotates its pool, but a run's config may fix one pairing; an inline deck is labelled by its name.
    value = _definition("fixed")
    value["engine"]["command"].append("--decklists")
    directory = tmp_path / "benchmarks/fixed"
    _write_definition(directory, value)
    decklist = {"name": "Mountains", "decklist": [{"name": "Mountain", "count": 60}]}
    config = {"decks": [decklist, {"catalog_id": "Burn"}], "pairs_per_matchup": 2}
    run_dir = _run(directory, "2026-09-26", config_changes={"deck_pool": None, **config})
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    page = (tmp_path / "site/b/fixed/index.html").read_text(encoding="utf-8")
    assert "<dt>Decks</dt><dd>Mountains vs Burn</dd>" in page
    assert "<dt>Schedule</dt><dd>2 seat-swapped pairs per deck in each matchup</dd>" in page
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert board["slices"]["deck"] == []  # one pairing: the page's deck label is the ledger's


def test_a_benchmark_whose_only_run_is_unfinished_shows_no_run(copy_tree: Path, tmp_path: Path) -> None:
    fresh = copy_tree / "gamma"
    (fresh / "runs/2026-09-26").mkdir(parents=True)
    (fresh / "runs/2026-09-26/config.json").write_bytes(b"{}\n")
    _write_definition(fresh, _definition("gamma"))
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert "gamma: runs/2026-09-26 has no manifest.json (an unfinished run); showing no run" in warnings
    assert "gamma: no published run yet" in warnings
    assert "No published run yet" in (out / "index.html").read_text(encoding="utf-8")
    assert not (out / "b/gamma").exists()


def test_pages_hold_no_local_paths(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    local = (str(tree), tree.as_posix(), str(out), out.as_posix(), sys.executable, str(FAKE_ENGINE))
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert not [path for path in local if path in text], page.name


def test_an_arena_level_definition_error_names_the_benchmark(copy_tree: Path, tmp_path: Path) -> None:
    broken = _definition("alpha")
    broken["bootstrap_replicates"] = 10  # benchmark.json allows it; the arena needs at least 1000
    _write_definition(copy_tree / "alpha", broken)
    out = tmp_path / "site"
    # the definition names its file, whose folder is the benchmark id; "." matches either path separator
    with pytest.raises(SiteError, match=r"alpha.benchmark\.json: benchmark: the arena refuses its config: "
                                        r"config\.bootstrap_replicates"):
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
            "owner": "spellbench", "training_style_tags": ["baseline"],
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
        assert f'<span class="chip">gamma {value}</span>' in item, row["name"]  # a v2 run: no protocol v1 label
        if bound is None:
            low, high = ((end - 1_000_000) / 1000 for end in row["ci95_elo_milli"])
            detail = f"95% interval {render.format_margin(low)} to {render.format_margin(high)}"
        else:
            detail = f"{'unbeaten' if bound == 'lower' else 'winless'} in gamma: the rating is limited by the prior"
        assert _aria_label(item) == f"{_in_words(margin, bound)}, {detail}", row["name"]
        assert ('class="arrow"' in item, 'class="whisker"' in item) == (bound is not None, bound is None), row["name"]


def test_the_models_page_orders_submitted_models_by_best_rating_then_the_builtins(
    checked: tuple[Path, dict[str, Any]]
) -> None:
    # one-land is the only submitted (subprocess) model; the builtins follow by best rating, ties by name.
    site, _ = checked
    models = (site / "models.html").read_text(encoding="utf-8")
    assert re.findall(r'<section id="model-([^"]+)"', models) == ["one-land", "heuristic", "uniform", "first"]
    one_land = _element(models, "section", "id", "model-one-land")
    assert "submitted model" in one_land and "baseline" in one_land and "version 1.0.0" in one_land
    uniform = _html(models, "section", "id", "model-uniform")
    assert "builtin reference bot" in uniform
    assert '<li><a href="b/gamma/index.html">gamma</a>: reference</li>' in uniform


# ---------------- board runs: rated protocol v2 runs, or protocol v1 runs (Decisions 1 and 3) ----------------


def test_board_run_dir_is_the_latest_rated_v2_run_or_v1_run(tmp_path: Path) -> None:
    # The choice reads each manifest's schema and run.rated alone; build_site validates what it chose.
    runs = tmp_path / "runs"

    def publish(name: str, manifest: dict[str, Any] | bytes) -> None:
        (runs / name).mkdir(parents=True)
        data = manifest if isinstance(manifest, bytes) else store.canonical_bytes(manifest) + b"\n"
        (runs / name / "manifest.json").write_bytes(data)

    def v2(rated: Any) -> dict[str, Any]:
        return {"schema": "spellbench-tournament/v2", "run": {"status": "complete", "rated": rated}}

    v1 = {"schema": "spellbench-tournament/v1"}
    publish("2026-09-01", v1)
    publish("2026-09-02", v2(True))
    publish("2026-09-02-2", v2(False))                                      # unrated: never on the board
    publish("2026-09-03", v2(1))                                            # rated is true, not a truthy value
    publish("2026-09-04", b"not json\n")                                    # unreadable
    publish("2026-09-05", {"schema": "spellbench-tournament/v9", "run": {"status": "complete", "rated": True}})
    for name, files in (("2026-09-06", ("COMMITMENT.json", "REVEAL.json")), ("2026-09-07", ("COMMITMENT.json",))):
        (runs / name).mkdir()
        for file in files:                                                  # no manifest: not a published run
            (runs / name / file).write_bytes(store.canonical_bytes(v2(True)) + b"\n")
    assert board_run_dir(tmp_path) == runs / "2026-09-02"
    shutil.rmtree(runs / "2026-09-02")
    assert board_run_dir(tmp_path) == runs / "2026-09-01"                  # no rated v2 run: the latest v1 run
    publish("2026-09-08", v1)
    assert board_run_dir(tmp_path) == runs / "2026-09-08"                  # the latest, whatever its protocol
    for name in ("2026-09-01", "2026-09-08"):
        shutil.rmtree(runs / name)
    assert board_run_dir(tmp_path) is None


def test_a_newer_unrated_run_is_not_the_board_run(copy_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bench = copy_tree / "alpha"
    _run(bench, "2026-09-27", rated=False, secret=RunSecret.generate())     # complete, but no proof: unrated
    warnings, views = _build_with_views(copy_tree, tmp_path / "site", monkeypatch)
    page = (tmp_path / "site" / "b" / "alpha" / "index.html").read_text(encoding="utf-8")
    assert "Run 2026-09-26" in page and "Newer runs not shown: 2026-09-27 (complete)" in page
    assert "alpha: runs/2026-09-27 is complete and not rated; showing runs/2026-09-26" in warnings
    assert (tmp_path / "site/b/alpha/run/manifest.json").read_bytes() == (bench / "runs/2026-09-26/manifest.json").read_bytes()
    alpha = next(view for view in views["render_benchmark"] if view["id"] == "alpha")
    assert alpha["newer_runs"] == [{"name": "2026-09-27", "status": "complete", "rated": False}]
    assert (alpha["run"]["status"], alpha["run"]["rated"]) == ("complete", True)


def test_runs_after_the_board_run_are_validated_listed_and_warned_about(copy_tree: Path, tmp_path: Path) -> None:
    bench = copy_tree / "alpha"
    _run(bench, "2026-09-25", rated=False)                                  # before the board run: not listed

    def stop(row: Any) -> None:
        raise RuntimeError("stopped after the first game")

    with pytest.raises(RuntimeError, match="stopped"):
        _run(bench, "2026-09-27", rated=False, on_game=stop)                # published as aborted
    assert _manifest(bench / "runs/2026-09-27")["run"]["status"] == "aborted"
    warnings = build_site(copy_tree, tmp_path / "site")
    page = (tmp_path / "site/b/alpha/index.html").read_text(encoding="utf-8")
    assert '<p class="note newer-runs">Newer runs not shown: 2026-09-27 (aborted)</p>' in page
    assert "alpha: runs/2026-09-27 is aborted and not rated; showing runs/2026-09-26" in warnings
    assert not [warning for warning in warnings if "2026-09-25" in warning] and "2026-09-25" not in page
    beta = (tmp_path / "site/b/beta/index.html").read_text(encoding="utf-8")
    assert '<p class="note newer-runs">' not in beta
    ledger = bench / "runs/2026-09-27/matches.jsonl"                       # a newer run is validated too
    ledger.write_bytes(ledger.read_bytes().replace(b'"reason":"score"', b'"reason":"SCORE"', 1))
    with pytest.raises(SiteError, match="alpha runs/2026-09-27: "):
        build_site(copy_tree, tmp_path / "site-2")
    assert not (tmp_path / "site-2").exists()


def test_a_benchmark_whose_runs_are_all_unrated_has_no_page(copy_tree: Path, tmp_path: Path) -> None:
    gamma = copy_tree / "gamma"
    _write_definition(gamma, _definition("gamma"))
    _run(gamma, "2026-09-26", rated=False)
    warnings = build_site(copy_tree, tmp_path / "site")
    assert "gamma: runs/2026-09-26 is complete and not rated; showing no run" in warnings
    assert not (tmp_path / "site/b/gamma").exists()
    hero = (tmp_path / "site/index.html").read_text(encoding="utf-8")
    assert "gamma" not in hero[hero.index('id="hero"'):hero.index('id="benchmarks"')]
    ledger = gamma / "runs/2026-09-26/matches.jsonl"                       # still validated: it is published
    ledger.write_bytes(ledger.read_bytes().replace(b'"reason":"score"', b'"reason":"SCORE"', 1))
    with pytest.raises(SiteError, match="gamma runs/2026-09-26: "):
        build_site(copy_tree, tmp_path / "site-2")


def test_a_run_revealed_after_an_abort_is_warned_about_by_its_file_name(copy_tree: Path, tmp_path: Path) -> None:
    # Task 41 validates REVEAL.json; until then the name alone says what the directory is, whatever it holds.
    runs = copy_tree / "alpha" / "runs"
    for name, files in (("2026-09-27", ("COMMITMENT.json",)), ("2026-09-28", ("COMMITMENT.json", "REVEAL.json")),
                        ("2026-09-29", ("REVEAL.json",))):
        (runs / name).mkdir()
        for file in files:
            (runs / name / file).write_bytes(b"not read before Task 41\n")
    warnings = build_site(copy_tree, tmp_path / "site")
    assert "alpha: runs/2026-09-27 has no manifest.json (an unfinished run); showing runs/2026-09-26" in warnings
    for name in ("2026-09-28", "2026-09-29"):
        assert (
            f"alpha: runs/{name} was revealed after an abort (REVEAL.json, no manifest.json); showing runs/2026-09-26"
            in warnings
        )
    assert len(warnings) == 3
    page = (tmp_path / "site/b/alpha/index.html").read_text(encoding="utf-8")
    assert "Run 2026-09-26" in page and '<p class="note newer-runs">' not in page


# ---------------- a protocol v2 board run ----------------


def test_a_v2_page_shows_the_fairness_verdict_and_rules(tree: Path, tmp_path: Path) -> None:
    build_site(tree, tmp_path / "site")
    page = (tmp_path / "site" / "b" / "alpha" / "index.html").read_text(encoding="utf-8")
    assert 'class="fairness"' in page and "verdict pass" in page and "Opponent decklist" in page
    assert "self-reported" not in page                                              # builtin bots only (R3-9)
    manifest = _manifest(tree / "alpha/runs/2026-09-26")
    checked = manifest["validator"]["decisions_checked"]
    assert checked > 0 and f"({checked} decisions, verdict pass)" in _html(page, "section", "class", "fairness")
    names = len(manifest["information_rules"]["rules"]["card_name_domain"]["names"])
    setup = re.findall(r"<dt>([^<]*)</dt><dd>([^<]*)</dd>", _html(page, "section", "class", "setup"))
    assert setup[:4] == [("Protocol", "spellbench/v2.0"), ("Format", "pauper-bo1"), ("Decks", "Burn, Elves, Faeries"),
                         ("Schedule", "1 seat-swapped pair per deck in each matchup")]
    assert setup[4:15] == [
        ("Opponent decklist", "visible"),
        ("Mulligan", "none (the engine offers no mulligans)"),                  # auto, and the engine has no London
        ("Starting player", "host_assigned (p0 takes the first turn)"),
        ("Card-name domain", f"{names} card names"),
        ("Trigger order", "offered to the bots"),                                # every engine default is null
        ("Replacement order", "offered to the bots"),
        ("Combat damage assignment", "offered to the bots"),
        ("Mana payment", "offered to the bots"),
        ("Optional observation fields", "none"),
        ("Extensions", "none"),
        ("Engine", "fake-v2-engine"),
    ]


def test_the_views_carry_every_protocol_key_of_a_v2_run(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The run's status and rated flag are required keys that the page does not show (Task 38 rulings).
    _, views = _build_with_views(tree, tmp_path / "site", monkeypatch)
    for view in views["render_benchmark"]:
        manifest = _manifest(tree / view["id"] / "runs/2026-09-26")
        assert (view["protocol"], view["legacy"], view["newer_runs"]) == ({"name": "spellbench/v2", "minor": 0}, False, [])
        assert view["fairness"] == {"label": "validator only", "verdict": "pass",
                                    "decisions_checked": manifest["validator"]["decisions_checked"], "violations": 0,
                                    "self_reported": False}
        run = view["run"]
        assert (run["status"], run["rated"]) == ("complete", True)
        assert (run["commitment"], run["run_secret"]) == (TEST_RUN_SECRET.commitment(), TEST_RUN_SECRET.hex())
        assert manifest["secrets"]["commitment"] == TEST_RUN_SECRET.commitment()
    [home] = views["render_home"]
    chips = [chip for row in home["hero"]["rows"] for chip in row["chips"]]
    assert chips and all(chip["legacy"] is False for chip in chips)
    [models] = views["render_models"]
    ratings = [row for model in models["models"] for row in model["benchmarks"]]
    assert ratings and all(row["legacy"] is False for row in ratings)


def test_the_recheck_box_shows_the_commitment_and_the_revealed_secret(tree: Path, tmp_path: Path) -> None:
    build_site(tree, tmp_path / "site")
    recheck = _html((tmp_path / "site/b/alpha/index.html").read_text(encoding="utf-8"), "section", "class", "recheck")
    manifest = _manifest(tree / "alpha/runs/2026-09-26")
    assert f'<p class="note">Commitment</p>\n<p><code class="hash">{manifest["secrets"]["commitment"]}</code></p>' in recheck
    assert (
        '<p class="note">Run secret (revealed after the run)</p>\n'
        f'<p><code class="hash">{manifest["secrets"]["run_secret"]}</code></p>'
    ) in recheck


def test_a_run_with_an_unsandboxed_subprocess_bot_is_self_reported(checked: tuple[Path, dict[str, Any]]) -> None:
    site, _ = checked                                                   # one-land runs unsandboxed (spec 11.7, R3-9)
    fairness = _html((site / "b/gamma/index.html").read_text(encoding="utf-8"), "section", "class", "fairness")
    assert "self-reported" in fairness and "without a verified sandbox" in fairness


def test_a_sandboxed_subprocess_bot_is_not_self_reported(tmp_path: Path) -> None:
    # self_reported comes from the manifest's isolation record: a subprocess bot in the sandbox is isolated.
    value = _definition("boxed")
    value["deck_pool"] = ["Burn"]
    value["bots"] = [value["bots"][0], {
        "name": "one-land", "version": "1.0.0", "type": "subprocess", "owner": "a-submitter",
        "command": ["${SPELLBENCH_SANDBOX}", str(BOT_ONE_LAND)],
        "display": {"label": "one land", "author": "Tests", "description": "Plays one land a game.", "url": None},
    }]
    run_dir = _publish(tmp_path / "benchmarks", value,
                       resolve=lambda part: sys.executable if part == "${SPELLBENCH_SANDBOX}" else part)
    assert _manifest(run_dir)["isolation"]["entries"][1] == {"name": "one-land", "isolation": "verified-sandbox"}
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    fairness = _html((tmp_path / "site/b/boxed/index.html").read_text(encoding="utf-8"), "section", "class", "fairness")
    assert "self-reported" not in fairness and "without a verified sandbox" not in fairness


# ---------------- a v2 run on an engine that names its decks, with halted games ----------------

_RENAMING_ENGINE = """\
import sys
sys.path.insert(0, {tests!r})
import fake_v2_engine

_catalog_deck = fake_v2_engine.CatalogDeck


class _Named:
    @staticmethod
    def from_json(value, *args):
        return _catalog_deck.from_json({{**value, "name": "The " + value["catalog_id"]}}, *args)


fake_v2_engine.CatalogDeck = _Named
sys.exit(fake_v2_engine.serve(sys.argv[1:]))
"""


@pytest.fixture(scope="module")
def odd(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The site of one benchmark, "odd", and its run: the engine publishes each catalog deck as "The <id>" and
    provides two optional observation fields, the Halt deck ends every game halted after the first move, and the
    run's config asks for no mulligan outright.

    A valid run has no truncated game: each seat's caps are below half of the game's (spec 11.4), so the
    attribution's truncation counts are checked with ``test_attribution_rows_copy_each_leaderboard_rows_counts``.
    """
    root = tmp_path_factory.mktemp("odd")
    engine = root / "renaming_engine.py"
    engine.write_text(_RENAMING_ENGINE.format(tests=str(TESTS_DIR)), encoding="utf-8", newline="\n")
    value = _definition("odd")
    value["engine"]["command"] = [sys.executable, str(engine), "--flags", "keywords,poison"]
    value["deck_pool"] = ["Burn", "Halt"]
    rules = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0"}
    run_dir = _publish(root / "benchmarks", value, config_changes={"rules": rules})
    build_site(root / "benchmarks", root / "site")
    return root / "site", run_dir


def test_deck_labels_are_the_ledger_deck_names(odd: tuple[Path, Path]) -> None:
    site, run_dir = odd                                                     # R3-25
    page = (site / "b/odd/index.html").read_text(encoding="utf-8")
    assert "<dt>Decks</dt><dd>The Burn, The Halt</dd>" in page
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert [deck_slice["label"] for deck_slice in board["slices"]["deck"]] == ["The Burn", "The Halt"]
    for label in ("The Burn", "The Halt"):
        assert f'data-deck="{label}"' in page
    home = (site / "index.html").read_text(encoding="utf-8")
    assert "2 decks" in _html(home, "article", "class", "card linked")


def test_the_setup_rules_are_the_ones_the_run_recorded(odd: tuple[Path, Path]) -> None:
    site, _ = odd
    setup = dict(re.findall(r"<dt>([^<]*)</dt><dd>([^<]*)</dd>", (site / "b/odd/index.html").read_text(encoding="utf-8")))
    assert setup["Mulligan"] == "none"                                      # asked for outright, not resolved from auto
    assert setup["Optional observation fields"] == "poison, keywords"      # the spec's order (6.9)


def test_the_attribution_table_matches_the_leaderboard(odd: tuple[Path, Path]) -> None:
    site, run_dir = odd
    page = (site / "b/odd/index.html").read_text(encoding="utf-8")
    table = _html(page, "table", "class", "attribution")
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    labels = {"uniform": "random", "heuristic": "heuristic", "first": "first"}
    rows = re.findall(r'<tr data-bot="([^"]+)"><td><span class="label"><a [^>]*>([^<]+)</a></span></td>'
                      r'<td class="num">(\d+)</td><td class="num">(\d+)</td><td class="num">(\d+)</td></tr>', table)
    assert rows == [
        (row["name"], labels[row["name"]], str(row["games_played"]), str(row["halts_attributed"]),
         str(row["truncations_attributed"]))
        for row in board["rows"]
    ]
    assert sum(row["halts_attributed"] for row in board["rows"]) == 2 * 3  # one Halt pair per matchup
    assert all(row["games_played"] > row["games"] for row in board["rows"])  # games played count halted games too


def test_attribution_rows_copy_each_leaderboard_rows_counts(odd: tuple[Path, Path]) -> None:
    # No valid run truncates a game (spec 11.4), so distinct counts are set on the leaderboard the view reads.
    _, run_dir = odd
    run = build._read_run(run_dir, ())
    board = copy.deepcopy(run.board)
    for index, row in enumerate(board["rows"]):
        row.update(games_played=100 + index, halts_attributed=10 + index, truncations_attributed=20 + index)
    display = {row["name"]: {"label": f"label of {row['name']}"} for row in board["rows"]}
    view = build._protocol_view(dataclasses.replace(run, board=board), display)
    assert view["attribution"] == [
        {"name": row["name"], "label": f"label of {row['name']}", "games": 100 + index, "halts": 10 + index,
         "truncations": 20 + index}
        for index, row in enumerate(board["rows"])
    ]


# ---------------- a protocol v1 board run (Decision 1) ----------------


def test_a_legacy_board_run_is_shown_with_its_label(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The committed v1 run of pauper-kernel beside the v2 tree. Validating the 960-game run takes about 20 s,
    # so this copies the definition with the 192-game run (the site step in CI builds the real tree).
    root = tmp_path / "benchmarks"
    shutil.copytree(tree, root)
    bench = root / "pauper-kernel"
    source = REPO / "benchmarks" / "pauper-kernel"
    shutil.copytree(source / "runs" / "2026-09-26", bench / "runs" / "2026-09-26")
    value = json.loads((source / "benchmark.json").read_text(encoding="utf-8"))
    value["bots"] = [bot for bot in value["bots"] if bot["name"] != "first"]  # a bot the definition no longer names
    _write_definition(bench, value)
    warnings, views = _build_with_views(root, tmp_path / "site", monkeypatch)
    page = (tmp_path / "site" / "b" / "pauper-kernel" / "index.html").read_text(encoding="utf-8")
    assert 'class="legacy"' in page and "protocol v1" in page
    assert "pauper-kernel: the board run is protocol v1; rerun on protocol v2 to publish the current definition" in warnings
    assert not [warning for warning in warnings if "pauper-kernel" in warning and "changed since run" in warning]
    home = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "pauper-kernel" in home and V1 in home                                   # the Hero chip is labelled too (R3-20)

    run_dir = bench / "runs" / "2026-09-26"
    board = json.loads((run_dir / "leaderboard.json").read_text(encoding="utf-8"))
    manifest = _manifest(run_dir)
    assert "Run 2026-09-26" in page and 'class="fairness"' not in page and 'class="attribution"' not in page
    assert '<p class="note">Commitment</p>' not in page
    setup = dict(re.findall(r"<dt>([^<]*)</dt><dd>([^<]*)</dd>", page))
    assert setup["Protocol"] == "spellbench/v1" and setup["Format"] == "pauper-bo1"
    assert setup["Decks"] == "Wildfire, Rally, Affinity, Elves, Spy, Burn, CawGates, Faeries"
    recorded = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    pairs = recorded["pairs_per_matchup"] // len(recorded["deck_pool"])
    assert pairs > 1 and setup["Schedule"] == f"{pairs} seat-swapped pairs per deck in each matchup"
    assert (setup["Engine"], setup["Engine version"]) == (manifest["engine"]["name"], manifest["engine"]["version"])
    assert "Opponent decklist" not in setup
    assert sorted(path.name for path in (tmp_path / "site/b/pauper-kernel/run").iterdir()) == sorted(V1_RUN_FILES)
    for name in V1_RUN_FILES:
        assert (tmp_path / "site/b/pauper-kernel/run" / name).read_bytes() == (run_dir / name).read_bytes()
    # bots by the definition's display text where the names match, by registry name and owner otherwise
    uniform = _overall_row(page, "uniform")
    assert '<a href="../../models.html#model-uniform" title="Picks uniformly' in uniform and ">random</a>" in uniform
    first = _overall_row(page, "first")
    assert '<span class="label"><a href="../../models.html#model-first">first</a></span>' in first  # no description
    assert '<span class="by">spellbench' in first and "Spellbench" not in first  # the registry owner, not the author
    assert "first 1.0.0" in re.sub(r"<[^>]+>", " ", first)                # the v1 bot that was rated
    models = (tmp_path / "site" / "models.html").read_text(encoding="utf-8")
    link = f'<a href="b/pauper-kernel/index.html">pauper-kernel</a> {V1}'
    assert f"<li>{link}: reference</li>" in _html(models, "section", "id", "model-uniform")
    heuristic = _html(models, "section", "id", "model-heuristic")
    assert f"<li>{link}: " in heuristic and '<li><a href="b/alpha/index.html">alpha</a>: ' in heuristic

    # each chip and rating row says whether its own benchmark's board run is protocol v1
    [home_view] = views["render_home"]
    chips = {(row["name"], chip["benchmark_id"]): chip["legacy"] for row in home_view["hero"]["rows"] for chip in row["chips"]}
    assert chips[("heuristic", "pauper-kernel")] is True and chips[("heuristic", "alpha")] is False
    assert {legacy for (name, bench_id), legacy in chips.items() if bench_id != "pauper-kernel"} == {False}
    assert {legacy for (name, bench_id), legacy in chips.items() if bench_id == "pauper-kernel"} == {True}
    hero_row = _html(home, "li", "data-bot", "heuristic")
    assert V1 in hero_row and hero_row.count(V1) == 1
    [models_view] = views["render_models"]
    ratings = {(model["name"], row["id"]): row["legacy"] for model in models_view["models"] for row in model["benchmarks"]}
    assert ratings == {key: key[1] == "pauper-kernel" for key in ratings} and len(ratings) > 6
    legacy = next(view for view in views["render_benchmark"] if view["id"] == "pauper-kernel")
    assert (legacy["protocol"], legacy["legacy"], legacy["fairness"]) == ({"name": "spellbench/v1", "minor": None}, True, None)
    assert (legacy["setup_rules"], legacy["attribution"], legacy["newer_runs"]) == ([], [], [])
    assert {key: legacy["run"][key] for key in ("status", "rated", "commitment", "run_secret")} == {
        "status": "complete", "rated": True, "commitment": None, "run_secret": None}
    assert len(legacy["overall"]) == len(board["rows"])


def test_a_newer_v2_run_is_listed_on_a_legacy_page(tmp_path: Path) -> None:
    # Until a v2 run is rated, the v1 run stays on the board and the v2 run is listed after it (Decision 1).
    root = tmp_path / "benchmarks"
    bench = root / "pauper-kernel"
    source = REPO / "benchmarks" / "pauper-kernel"
    shutil.copytree(source / "runs" / "2026-09-26", bench / "runs" / "2026-09-26")
    value = _definition("pauper-kernel")
    value["deck_pool"] = ["Burn"]
    _write_definition(bench, value)
    _run(bench, "2026-09-28", rated=False)
    warnings = build_site(root, tmp_path / "site")
    page = (tmp_path / "site/b/pauper-kernel/index.html").read_text(encoding="utf-8")
    assert "Run 2026-09-26" in page and 'class="legacy"' in page
    assert '<p class="note newer-runs">Newer runs not shown: 2026-09-28 (complete)</p>' in page
    assert "pauper-kernel: runs/2026-09-28 is complete and not rated; showing runs/2026-09-26" in warnings
