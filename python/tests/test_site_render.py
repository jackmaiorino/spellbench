"""The site renderer: pure HTML from view-model dicts."""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from spellbench.site import render

SITE = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": "https://github.com/jackmaiorino/spellbench"}


def _leader(name: str, label: str, rank: int | None, elo: int | None, ci: list[int] | None, **extra: Any) -> dict[str, Any]:
    row = {
        "rank": rank, "name": name, "label": label, "author": "Spellbench", "url": None, "description": f"{label} bot",
        "tags": ["baseline"], "anchor": name == "uniform", "elo_milli": elo, "ci_elo_milli": ci,
        "wins": 10, "draws": 2, "losses": 4, "games": 16, "forfeits": 1,
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
             "approximate": False, "reference": False, "chips": [{"benchmark_id": "pauper-kernel", "margin": 101.4}]},
            {"name": "uniform", "label": "random", "author": "Spellbench", "score": 0.0, "lower": 0.0, "upper": 0.0,
             "approximate": False, "reference": True, "chips": [{"benchmark_id": "pauper-kernel", "margin": 0.0}]},
            {"name": "first", "label": "first", "author": "Spellbench", "score": -15.2, "lower": -50.0, "upper": 20.0,
             "approximate": False, "reference": False, "chips": [{"benchmark_id": "pauper-kernel", "margin": -15.2}]},
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


def _element(page: str, tag: str, attribute: str, value: str) -> str:
    match = re.search(rf'<{tag}\b[^>]*\b{attribute}="{re.escape(value)}"[^>]*>(.*?)</{tag}>', page, re.S)
    assert match, f"no <{tag} {attribute}={value!r}>"
    return re.sub(r"<[^>]+>", " ", match.group(1))


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
