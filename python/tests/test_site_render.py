"""The site renderer: pure HTML from view-model dicts."""

from __future__ import annotations

import copy
import html
import re
from typing import Any

import pytest

from spellbench.site import render

SITE = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": "https://github.com/jackmaiorino/spellbench"}
GE, LE, NBSP = "≥", "≤", " "  # a bound's sign, then a no-break space before its number


def _leader(name: str, label: str, rank: int | None, elo: int | None, ci: list[int] | None, **extra: Any) -> dict[str, Any]:
    row = {
        "rank": rank, "name": name, "label": label, "author": "Spellbench", "url": None, "description": f"{label} bot",
        "tags": ["baseline"], "anchor": name == "uniform", "elo_milli": elo, "ci_elo_milli": ci,
        "wins": 10, "draws": 2, "losses": 4, "games": 16, "forfeits": 1, "bound": None,
    }
    row.update(extra)
    return row


OVERALL = [
    _leader("heuristic", "heuristic", 1, 1_101_499, [1_052_000, 1_150_500], tags=["heuristic"]),
    _leader("uniform", "random", 2, 1_000_000, [1_000_000, 1_000_000]),
    _leader("first", "first", 3, 985_000, [950_000, 1_020_000]),
]

HOME: dict[str, Any] = {
    "site": SITE,
    "hero": {
        "rows": [
            {"name": "heuristic", "label": "heuristic", "author": "Spellbench", "score": 101.4, "lower": 52.0, "upper": 150.5,
             "approximate": False, "reference": False, "bound": None,
             "chips": [{"benchmark_id": "pauper-kernel", "margin": 101.4, "bound": None}]},
            {"name": "uniform", "label": "random", "author": "Spellbench", "score": 0.0, "lower": 0.0, "upper": 0.0,
             "approximate": False, "reference": True, "bound": None,
             "chips": [{"benchmark_id": "pauper-kernel", "margin": 0.0, "bound": None}]},
            {"name": "first", "label": "first", "author": "Spellbench", "score": -15.2, "lower": -50.0, "upper": 20.0,
             "approximate": False, "reference": False, "bound": None,
             "chips": [{"benchmark_id": "pauper-kernel", "margin": -15.2, "bound": None}]},
        ],
        "benchmark_count": 1,
        "approximate": False,
    },
    "benchmarks": [
        {"id": "pauper-kernel", "title": "Pauper \u00b7 mtg-kernel", "summary": "Eight Pauper decks.", "engine_name": "mtg-kernel",
         "deck_count": 8, "bot_count": 3, "games": 192, "run_name": "2026-09-26", "href": "b/pauper-kernel/index.html"},
        {"id": "new-one", "title": "New benchmark", "summary": "Not run yet.", "engine_name": "gorge",
         "deck_count": 2, "bot_count": 2, "games": None, "run_name": None, "href": None},
    ],
    "proposed": [{"title": "FDN Limited", "summary": "Foundations limited games.", "needs": "an engine"}],
}

BENCH: dict[str, Any] = {
    "site": SITE,
    "id": "pauper-kernel",
    "title": "Pauper \u00b7 mtg-kernel",
    "summary": "Eight Pauper decks.",
    "format": "pauper-bo1",
    "engine": {"name": "mtg-kernel", "version": "0.4.0", "source_revision": "abc123", "rules_snapshot_id": "rules-1", "card_pool_identity": "pool-1"},
    "decks": ["Burn", "Elves"],
    "pairs_per_deck": 4,
    "run": {
        "name": "2026-09-26",
        "games": {"total": 192, "rated": 190, "forfeit": 1, "truncated": 1, "halted": 1},
        "manifest_sha256": "f" * 64,
        "files": [{"name": "matches.jsonl", "href": "run/matches.jsonl", "bytes": 12345},
                  {"name": "manifest.json", "href": "run/manifest.json", "bytes": 999}],
        "validate_command": "spellbench validate benchmarks/pauper-kernel/runs/2026-09-26",
    },
    "overall": OVERALL,
    "deck_tables": [
        {"label": "Burn", "status": "ok", "reason": None, "rows": OVERALL},
        {"label": "Elves", "status": "fit_failed", "reason": "reference id is absent", "rows": []},
    ],
    "style_tables": [{"tag": "baseline", "rows": OVERALL[1:]}, {"tag": "heuristic", "rows": OVERALL[:1]}],
    "grid": {
        "names": ["heuristic", "uniform", "first"],
        "labels": ["heuristic", "random", "first"],
        "cells": [
            [None, {"score": 0.6, "games": 64}, {"score": 0.7, "games": 64}],
            [{"score": 0.4, "games": 64}, None, {"score": 0.55, "games": 64}],
            [{"score": 0.3, "games": 64}, {"score": 0.45, "games": 64}, None],
        ],
    },
}

INFO = {"site": SITE}


def _pages() -> dict[str, str]:
    return {
        "home": render.render_home(HOME),
        "benchmark": render.render_benchmark(BENCH),
        "join": render.render_join(INFO),
        "method": render.render_method(INFO),
    }


def _html(page: str, tag: str, attribute: str, value: str) -> str:
    """The inner HTML of the first ``<tag attribute="value">`` in ``page``."""
    match = re.search(rf'<{tag}\b[^>]*\b{attribute}="{re.escape(value)}"[^>]*>(.*?)</{tag}>', page, re.S)
    assert match, f"no <{tag} {attribute}={value!r}>"
    return match.group(1)


def _element(page: str, tag: str, attribute: str, value: str) -> str:
    """The text of the first ``<tag attribute="value">``, each tag replaced by a space."""
    return re.sub(r"<[^>]+>", " ", _html(page, tag, attribute, value))


def _aria(fragment: str) -> str:
    """The first aria-label in ``fragment``, unescaped."""
    match = re.search(r'aria-label="([^"]*)"', fragment)
    assert match, "no aria-label"
    return html.unescape(match.group(1))


def test_format_helpers() -> None:
    assert render.format_elo(1_101_499) == "1101"
    assert render.format_elo(985_000) == "985"
    assert render.format_margin(101.4) == "+101"
    assert render.format_margin(-15.2) == "\u221215"
    assert render.format_margin(0.2) == "0" and render.format_margin(-0.4) == "0"
    assert render.format_share(0.6) == "60%" and render.format_share(0.333) == "33%"


def test_pages_are_complete_documents() -> None:
    for name, page in _pages().items():
        assert page.startswith("<!doctype html>"), name
        assert page.endswith("</html>\n"), name
        assert '<meta name="viewport"' in page and "<title>" in page, name
        assert "\r" not in page and "\u2014" not in page, name


def test_rendering_is_deterministic() -> None:
    assert _pages() == _pages()


def test_no_external_resources() -> None:
    for name, page in _pages().items():
        assert not re.search(r'\bsrc="(?:https?:)?//', page), name
        assert "<link" not in page and "@import" not in page, name


def test_hero_rows_show_label_and_margin() -> None:
    home = _pages()["home"]
    assert "+101" in _element(home, "li", "data-bot", "heuristic")
    assert "\u221215" in _element(home, "li", "data-bot", "first")
    reference = _element(home, "li", "data-bot", "uniform")
    assert "random" in reference and "0" in reference


def test_leaderboard_rows_show_the_formatted_numbers() -> None:
    page = _pages()["benchmark"]
    overall = page[page.index('data-panel="overall"'):]
    for row in OVERALL:
        text = _element(overall, "tr", "data-bot", row["name"])
        assert render.format_elo(row["elo_milli"]) in text
        assert f'{row["wins"]}-{row["draws"]}-{row["losses"]}' in text


def test_the_grid_shows_shares() -> None:
    page = _pages()["benchmark"]
    cell = re.search(r'<td\b[^>]*data-row="heuristic"[^>]*data-col="uniform"[^>]*>(.*?)</td>', page, re.S)
    assert cell and "60%" in cell.group(1)
    assert page.count('data-col="first"') == 3  # one cell per row, the diagonal included


def test_every_deck_and_style_gets_a_panel() -> None:
    page = _pages()["benchmark"]
    assert 'data-deck="Burn"' in page and 'data-deck="Elves"' in page
    assert "Not rated: reference id is absent" in page
    assert 'data-tag="baseline"' in page and 'data-tag="heuristic"' in page


def test_links_between_pages() -> None:
    pages = _pages()
    assert 'href="b/pauper-kernel/index.html"' in pages["home"]
    assert 'href="join.html"' in pages["home"] and 'href="method.html"' in pages["home"]
    assert 'href="../../index.html"' in pages["benchmark"]
    assert 'href="run/matches.jsonl"' in pages["benchmark"]


def test_a_benchmark_without_a_run_has_an_unlinked_card() -> None:
    home = _pages()["home"]
    assert "New benchmark" in home and "No published run yet" in home
    assert "b/new-one/" not in home


def test_proposed_cards() -> None:
    home = _pages()["home"]
    assert "FDN Limited" in home and "Proposed" in home and "an engine" in home


def test_an_empty_hero_says_so() -> None:
    view = copy.deepcopy(HOME)
    view["hero"] = {"rows": [], "benchmark_count": 0, "approximate": False}
    assert "No rated benchmark yet." in render.render_home(view)


def test_approximate_intervals_are_labelled() -> None:
    view = copy.deepcopy(HOME)
    view["hero"]["approximate"] = True
    assert "approximate" in render.render_home(view)


@pytest.mark.parametrize("hostile", ['<script>alert("x")</script>', '" onmouseover="alert(1)'])
def test_hostile_text_is_escaped(hostile: str) -> None:
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0]["label"] = hostile
    home["benchmarks"][0]["title"] = hostile
    bench = copy.deepcopy(BENCH)
    bench["overall"][0]["label"] = hostile
    bench["overall"][0]["author"] = hostile
    bench["grid"]["labels"][0] = hostile
    for page in (render.render_home(home), render.render_benchmark(bench)):
        assert "<script>alert" not in page
        assert 'onmouseover="alert' not in page


def test_only_http_urls_become_links() -> None:
    bench = copy.deepcopy(BENCH)
    bench["overall"][0]["url"] = "javascript:alert(1)"
    bench["overall"][2]["url"] = "https://example.com/first"
    page = render.render_benchmark(bench)
    assert 'href="javascript:' not in page
    assert 'href="https://example.com/first"' in page


def test_the_method_page_explains_the_rating() -> None:
    method = _pages()["method"]
    for phrase in ("seat", "forfeit", "virtual draw", "anchor", "Hero score", "spellbench validate"):
        assert phrase in method


def test_long_unbroken_text_breaks_instead_of_widening_the_page() -> None:
    token = "W" * 200
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0]["label"] = token
    home["benchmarks"][0]["title"] = token
    bench = copy.deepcopy(BENCH)
    bench["title"] = bench["summary"] = bench["engine"]["version"] = token
    bench["overall"][0]["label"] = token
    home_page, bench_page = render.render_home(home), render.render_benchmark(bench)
    assert token in _element(home_page, "li", "data-bot", "heuristic")
    assert f'<a href="b/pauper-kernel/index.html">{token}</a>' in home_page
    assert f"<h1>{token}</h1>" in bench_page and f'<p class="lead">{token}</p>' in bench_page
    assert f"engine mtg-kernel {token}" in bench_page
    assert token in _element(bench_page, "tr", "data-bot", "heuristic")
    for page in (home_page, bench_page):
        style = page[page.index("<style>"):page.index("</style>")]
        # every free-text block inherits overflow-wrap: anywhere from body ...
        assert re.search(r"(?m)^body\s*\{[^}]*\boverflow-wrap:\s*anywhere\b", style)
        # ... while tables keep their min-content widths and scroll inside .table-wrap
        assert re.search(r"\.table-wrap\s*\{[^}]*\boverflow-wrap:\s*normal\b", style)


def test_a_bounded_leaderboard_row_reads_as_a_bound_with_an_arrow() -> None:
    # A bot that won every game (+864 [+817, +920] in the reviewer's simulation) and one that lost every game.
    bench = copy.deepcopy(BENCH)
    bench["overall"][0].update(elo_milli=1_864_000, ci_elo_milli=[1_817_000, 1_920_000], wins=16, draws=0, losses=0, bound="lower")
    bench["overall"][2].update(elo_milli=616_644, ci_elo_milli=[616_644, 616_644], wins=0, draws=0, losses=16, bound="upper")
    page = render.render_benchmark(bench)
    overall = page[page.index('data-panel="overall"'):]
    top, bottom = _html(overall, "tr", "data-bot", "heuristic"), _html(overall, "tr", "data-bot", "first")
    assert f"{GE}{NBSP}1864" in top and "unbeaten" in _element(overall, "tr", "data-bot", "heuristic")
    assert f"{LE}{NBSP}617" in bottom and "winless" in _element(overall, "tr", "data-bot", "first")
    for row in (top, bottom):
        assert 'class="arrow"' in row and 'stroke-width="3"' not in row  # an arrow, not the interval line
    assert _aria(top) == "at least 1864 Elo, unbeaten: the rating is limited by the prior"
    assert _aria(bottom) == "at most 617 Elo, winless: the rating is limited by the prior"
    # the arrow runs from the estimate to the edge on the side the rating is open
    assert re.search(r'<g class="arrow"><line x1="[0-9.]+%" y1="8" x2="100\.0%"', top)
    assert re.search(r'<g class="arrow"><line x1="[0-9.]+%" y1="8" x2="0\.0%"', bottom)


def test_a_zero_width_interval_that_is_not_a_bound_is_not_estimable() -> None:
    # CawGates heuristic in the trial run: 11-0-1 with the loss in an incomplete pair, so every
    # complete pair went the same way and the bootstrap interval collapsed onto the estimate.
    bench = copy.deepcopy(BENCH)
    bench["overall"][0].update(elo_milli=1_205_739, ci_elo_milli=[1_205_739, 1_205_739], wins=11, draws=0, losses=1)
    page = render.render_benchmark(bench)
    overall = page[page.index('data-panel="overall"'):]
    row = _html(overall, "tr", "data-bot", "heuristic")
    assert "interval not estimable" in row and "<circle" not in row
    assert "1206" in _element(overall, "tr", "data-bot", "heuristic")  # the estimate still shows
    assert "<circle" in _html(overall, "tr", "data-bot", "uniform")  # the anchor keeps its dot


def test_a_bounded_hero_row_reads_as_a_bound_with_an_arrow() -> None:
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0].update(
        score=864.0, lower=817.0, upper=920.0, bound="lower",
        chips=[{"benchmark_id": "pauper-kernel", "margin": 864.0, "bound": "lower"}],
    )
    page = render.render_home(home)
    row = _html(page, "li", "data-bot", "heuristic")
    assert f'<span class="value">{GE}{NBSP}+864</span>' in row
    assert f"pauper-kernel {GE}{NBSP}+864" in row
    assert 'class="arrow"' in row and 'class="whisker"' not in row
    assert _aria(row) == "at least 864 Elo above random, unbeaten in pauper-kernel: the rating is limited by the prior"
    hero = page[page.index('id="hero"'):page.index('id="benchmarks"')]
    assert f"A score marked {GE} or {LE} is only a bound" in hero
    assert "is only a bound" not in render.render_home(HOME)  # the note appears only with a bound


def test_a_hero_row_with_a_zero_width_interval_is_not_estimable() -> None:
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0].update(lower=101.4, upper=101.4)
    row = _html(render.render_home(home), "li", "data-bot", "heuristic")
    assert 'class="whisker"' not in row
    assert _aria(row) == "101 Elo above random, interval not estimable"


@pytest.mark.parametrize(
    ("score", "bound", "phrase"),
    [
        (-154.2, None, "154 Elo below random"),
        (101.4, None, "101 Elo above random"),
        (0.3, None, "level with random"),
        (-154.2, "upper", "at least 154 Elo below random"),   # at most -154: at least 154 below
        (-154.2, "lower", "at most 154 Elo below random"),
        (101.4, "upper", "at most 101 Elo above random"),
    ],
)
def test_the_hero_states_each_margin_in_words(score: float, bound: str | None, phrase: str) -> None:
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][2].update(
        score=score, lower=score - 30, upper=score + 30, bound=bound,
        chips=[{"benchmark_id": "pauper-kernel", "margin": score, "bound": bound}],
    )
    label = _aria(_html(render.render_home(home), "li", "data-bot", "first"))
    assert label.startswith(phrase + ",")


def test_the_method_page_explains_bounds() -> None:
    method = _pages()["method"]
    assert (
        "A bot that never lost (or never won) a rated game has no finite best-fit rating. The virtual draw keeps it "
        "finite, so the site shows it as a bound, at least or at most, and that bound grows with the number of games played."
    ) in method
