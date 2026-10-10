"""The site renderer: pure HTML from view-model dicts."""

from __future__ import annotations

import copy
import html
import re
from html.parser import HTMLParser
from typing import Any, Callable

import pytest

from spellbench.site import render

SITE = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": "https://github.com/jackmaiorino/spellbench"}
REPO = SITE["repo_url"]
GE, LE, NBSP = "≥", "≤", " "  # a bound's sign, then a no-break space before its number
SEP = " \u00b7 "
V1 = f"(protocol{NBSP}v1)"  # a v1 run's label in the Hero and on the Models page, kept on one line


def _leader(name: str, label: str, rank: int | None, elo: int | None, ci: list[int] | None, **extra: Any) -> dict[str, Any]:
    row = {
        "rank": rank, "name": name, "label": label, "author": "Spellbench", "url": None, "description": f"{label} bot",
        "tags": ["baseline"], "anchor": name == "uniform", "elo_milli": elo, "ci_elo_milli": ci,
        "wins": 10, "draws": 2, "losses": 4, "games": 16, "forfeits": 1, "bound": None, "version": "1.0.0",
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
            {"name": "heuristic", "label": "heuristic", "author": "Spellbench", "description": "heuristic bot",
             "score": 101.4, "lower": 52.0, "upper": 150.5, "approximate": False, "reference": False, "bound": None,
             "chips": [{"benchmark_id": "pauper-kernel", "margin": 101.4, "bound": None, "legacy": False}]},
            {"name": "uniform", "label": "random", "author": "Spellbench", "description": "random bot",
             "score": 0.0, "lower": 0.0, "upper": 0.0, "approximate": False, "reference": True, "bound": None,
             "chips": [{"benchmark_id": "pauper-kernel", "margin": 0.0, "bound": None, "legacy": False}]},
            {"name": "first", "label": "first", "author": "Spellbench", "description": "first bot",
             "score": -15.2, "lower": -50.0, "upper": 20.0, "approximate": False, "reference": False, "bound": None,
             "chips": [{"benchmark_id": "pauper-kernel", "margin": -15.2, "bound": None, "legacy": False}]},
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

# The benchmark page's protocol v2 keys, as Task 42's builder fills them for a v2 run; BENCH carries them.
V2_EXTRA: dict[str, Any] = {
    "protocol": {"name": "spellbench/v2", "minor": 0}, "legacy": False,
    "fairness": {"label": "validator only", "verdict": "pass", "decisions_checked": 18123, "violations": 0, "self_reported": False},
    "setup_rules": [{"term": "Opponent decklist", "value": "visible"}, {"term": "Mulligan", "value": "none (the engine offers no mulligans)"}],
    "attribution": [
        {"name": "heuristic", "label": "heuristic", "games": 64, "halts": 1, "truncations": 0},
        {"name": "uniform", "label": "random", "games": 64, "halts": 0, "truncations": 2},  # label differs from name
    ],
    "newer_runs": [{"name": "2026-10-02", "status": "invalid", "rated": False}],
}
V2_RUN_KEYS = ("status", "rated", "commitment", "run_secret")

BENCH: dict[str, Any] = {
    "site": SITE,
    "id": "pauper-kernel",
    "title": "Pauper \u00b7 mtg-kernel",
    "summary": "Eight Pauper decks.",
    "format": "pauper-bo1",
    "engine": {"name": "mtg-kernel", "version": "0.4.0", "source_revision": "abc123", "rules_snapshot_id": "rules-1", "card_pool_identity": "pool-1"},
    "decks": ["Burn", "Elves"],
    "pairs_per_deck": 4,
    **copy.deepcopy(V2_EXTRA),
    "run": {
        "name": "2026-09-26",
        "games": {"total": 192, "rated": 190, "forfeit": 1, "truncated": 1, "halted": 1},
        "manifest_sha256": "f" * 64,
        "files": [{"name": "matches.jsonl", "href": "run/matches.jsonl", "bytes": 12345},
                  {"name": "manifest.json", "href": "run/manifest.json", "bytes": 999}],
        "validate_command": "uv run spellbench validate benchmarks/pauper-kernel/runs/2026-09-26",
        "status": "complete", "rated": True, "commitment": "ab" * 32, "run_secret": "cd" * 32,
    },
    "overall": OVERALL,
    "deck_tables": [
        {"label": "Burn", "status": "ok", "reason": None, "fit_error": None, "rows": OVERALL},
        {"label": "Elves", "status": "fit_failed", "reason": "the random bot has no complete pair on this deck",
         "fit_error": "reference_id has no games", "rows": []},
    ],
    "style_tables": [{"tag": "baseline", "rows": OVERALL[1:]}, {"tag": "heuristic", "rows": OVERALL[:1]}],
    "grid": {
        "names": ["heuristic", "uniform", "first"],
        "labels": ["heuristic", "random", "first"],
        "descriptions": ["heuristic bot", "random bot", "first bot"],
        "cells": [
            [None, {"score": 0.6, "games": 64, "complete_pairs": 32}, {"score": 0.7, "games": 64, "complete_pairs": 32}],
            [{"score": 0.4, "games": 64, "complete_pairs": 32}, None, {"score": 0.55, "games": 57, "complete_pairs": 27}],
            [{"score": 0.3, "games": 64, "complete_pairs": 32}, {"score": 0.45, "games": 57, "complete_pairs": 27}, None],
        ],
    },
}

INFO = {"site": SITE}

MODELS: dict[str, Any] = {
    "site": SITE,
    "models": [
        {"name": "g115", "label": "g115", "author": "mipo", "description": "Phase 1 policy network, sampled, no search.",
         "url": "https://example.com/g115", "kind": "submitted model", "engine": "mtg-kernel",
         "tags": ["reinforcement-learning"], "version": "1.0.0",
         "benchmarks": [{"id": "pauper-kernel", "href": "b/pauper-kernel/index.html", "reference": False,
                         "margin": 388.0, "lower": 322.0, "upper": 464.0, "bound": None, "legacy": False}]},
        {"name": "heuristic", "label": "heuristic", "author": "Spellbench", "description": "Fixed priorities.",
         "url": None, "kind": "builtin reference bot", "engine": None, "tags": ["heuristic"], "version": "1.0.0",
         "benchmarks": [{"id": "pauper-kernel", "href": "b/pauper-kernel/index.html", "reference": False,
                         "margin": 101.0, "lower": 46.0, "upper": 156.0, "bound": None, "legacy": False}]},
        {"name": "uniform", "label": "random", "author": "Spellbench", "description": "Picks uniformly at random.",
         "url": None, "kind": "builtin reference bot", "engine": None, "tags": ["baseline"], "version": "1.0.0",
         "benchmarks": [{"id": "pauper-kernel", "href": "b/pauper-kernel/index.html", "reference": True,
                         "margin": 0.0, "lower": 0.0, "upper": 0.0, "bound": None, "legacy": False}]},
    ],
}


def _pages() -> dict[str, str]:
    return {
        "home": render.render_home(HOME),
        "benchmark": render.render_benchmark(BENCH),
        "models": render.render_models(MODELS),
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


def _v2_page(**changes: Any) -> str:
    """The page of BENCH, a protocol v2 run, with ``changes`` to its top-level keys."""
    view = copy.deepcopy(BENCH)
    view.update(copy.deepcopy(changes))
    return render.render_benchmark(view)


def _legacy_view(**changes: Any) -> dict[str, Any]:
    """BENCH as a protocol v1 run, with every v2 key set as Task 42's builder sets it for one."""
    view = copy.deepcopy(BENCH)
    view.update(
        protocol={"name": "spellbench/v1", "minor": None}, legacy=True, fairness=None, setup_rules=[], attribution=[],
        newer_runs=[],
    )
    view["run"].update(status="complete", rated=True, commitment=None, run_secret=None)
    view.update(copy.deepcopy(changes))
    return view


def _pre_v2_view() -> dict[str, Any]:
    """BENCH without any protocol key, as the site builder made it before protocol v2."""
    view = copy.deepcopy(BENCH)
    for key in V2_EXTRA:
        del view[key]
    for key in V2_RUN_KEYS:
        del view["run"][key]
    return view


def _without(view: dict[str, Any], key: str) -> dict[str, Any]:
    """A copy of ``view`` without one protocol v2 key: a top-level key, or ``run.<key>``."""
    view = copy.deepcopy(view)
    holder, name = (view["run"], key.removeprefix("run.")) if key.startswith("run.") else (view, key)
    del holder[name]
    return view


def _after_run_box(page: str) -> str:
    """The page from the end of the run box on."""
    box = re.search(r'<div class="run">\n.*?\n</div>\n', page, re.S)
    assert box, "no run box"
    return page[box.end():]


def _style(page: str) -> str:
    return page[page.index("<style>"):page.index("</style>")]


FAIRNESS_LINK = f'<a href="{REPO}/blob/main/spec/SPELLBENCH_PROTOCOL_V2.md#13-fairness-contract">validator only</a>'
HIDDEN_STATE = "It cannot see hidden state, so an engine adapter that leaked through its text or extensions would go unnoticed."
LEGACY_NOTE = (
    '<p class="legacy">Protocol v1: this run predates the fairness contract, and the two games of each pair shared one '
    "seed. It stays on the board until the benchmark reruns on protocol v2.</p>"
)


def test_a_v2_page_shows_protocol_fairness_rules_and_attribution() -> None:
    page = _v2_page()
    assert "protocol v2" in page and 'class="fairness"' in page and "18123 decisions" in page
    assert "SPELLBENCH_PROTOCOL_V2.md#13-fairness-contract" in page
    assert "Mulligan" in page and 'class="attribution"' in page and "Newer runs not shown: 2026-10-02 (invalid)" in page
    assert "ab" * 32 in page and "cd" * 32 in page


def test_the_fairness_section_reads_as_the_contract_right_after_the_run_box() -> None:
    assert _after_run_box(_v2_page()).startswith(
        f'<section class="fairness">\n<p>Fairness: {FAIRNESS_LINK}. The host checked every decision before a bot saw '
        f"it (18123 decisions, verdict pass). {HIDDEN_STATE}</p>\n</section>\n"
    )


def test_a_self_reported_run_says_so_next_to_the_fairness_label() -> None:
    fairness = {**V2_EXTRA["fairness"], "self_reported": True, "decisions_checked": 7, "verdict": "fail"}
    assert _html(_v2_page(fairness=fairness), "section", "class", "fairness") == (                         # R3-9
        f'\n<p>Fairness: {FAIRNESS_LINK} <span class="chip quiet">self-reported</span>. The host checked every '
        f"decision before a bot saw it (7 decisions, verdict fail). {HIDDEN_STATE} Its bots ran without a verified "
        "sandbox (spec 11.7), so the run cannot claim isolation.</p>\n"
    )
    assert "self-reported" not in _html(_v2_page(), "section", "class", "fairness")


def test_a_legacy_page_says_so_and_shows_no_fairness_box() -> None:
    page = render.render_benchmark(_legacy_view())
    assert _after_run_box(page).startswith(LEGACY_NOTE + "\n")
    assert 'class="fairness"' not in page and 'class="attribution' not in page
    assert f'<p class="meta">engine mtg-kernel 0.4.0{SEP}2 decks{SEP}same deck in both seats{SEP}protocol v1</p>' in page
    assert "<dl>\n<dt>Protocol</dt><dd>spellbench/v1</dd>\n<dt>Format</dt>" in page
    assert "Commitment" not in page and "Run secret" not in page


def test_the_meta_line_and_the_setup_list_name_the_protocol_and_its_rules() -> None:
    page = _v2_page()
    assert f'<p class="meta">engine mtg-kernel 0.4.0{SEP}2 decks{SEP}same deck in both seats{SEP}protocol v2</p>' in page
    assert "<dl>\n<dt>Protocol</dt><dd>spellbench/v2.0</dd>\n<dt>Format</dt>" in page  # its name and minor version
    assert (
        "<dt>Schedule</dt><dd>4 seat-swapped pairs per deck in each matchup</dd>\n"
        "<dt>Opponent decklist</dt><dd>visible</dd>\n"
        "<dt>Mulligan</dt><dd>none (the engine offers no mulligans)</dd>\n"
        "<dt>Engine</dt>"
    ) in page


def test_setup_rule_values_are_escaped() -> None:
    page = _v2_page(setup_rules=[{"term": "<b>x</b>", "value": "<script>"}])
    assert "<dt>&lt;b&gt;x&lt;/b&gt;</dt><dd>&lt;script&gt;</dd>" in page


def test_every_newer_run_is_listed_with_its_status_under_the_fairness_box() -> None:
    newer = [{"name": "2026-10-02", "status": "invalid", "rated": False}, {"name": "2026-10-03", "status": "complete", "rated": False}]
    note = '<p class="note newer-runs">Newer runs not shown: 2026-10-02 (invalid), 2026-10-03 (complete)</p>\n'
    fairness_box = r'<section class="fairness">\n<p>[^\n]*</p>\n</section>\n'
    assert re.match(fairness_box + re.escape(note), _after_run_box(_v2_page(newer_runs=newer)))
    assert _after_run_box(render.render_benchmark(_legacy_view(newer_runs=newer))).startswith(f"{LEGACY_NOTE}\n{note}")
    assert "Newer runs" not in _v2_page(newer_runs=[])
    # a gap above the note, so that it does not read as the caption of the box over it
    assert re.search(r"(?m)^\.newer-runs\s*\{[^}]*\bmargin-top:\s*16px", _style(_v2_page()))


def test_the_attribution_table_has_the_contract_caption_and_a_row_per_bot() -> None:
    assert _html(_v2_page(), "section", "class", "attribution-section") == "\n".join(
        [
            "",
            '<div class="table-wrap">',
            '<table class="attribution">',
            "<caption>Halts and truncations after each bot's move</caption>",
            '<thead><tr><th scope="col">Bot</th><th scope="col" class="num">Games</th>'
            '<th scope="col" class="num">Halts</th><th scope="col" class="num">Truncations</th></tr></thead>',
            "<tbody>",
            '<tr data-bot="heuristic"><td><span class="label"><a href="../../models.html#model-heuristic" '
            'title="heuristic bot">heuristic</a></span></td><td class="num">64</td><td class="num">1</td>'
            '<td class="num">0</td></tr>',
            '<tr data-bot="uniform"><td><span class="label"><a href="../../models.html#model-uniform" '
            'title="random bot">random</a></span></td><td class="num">64</td><td class="num">0</td>'
            '<td class="num">2</td></tr>',
            "</tbody>",
            "</table>",
            "</div>",
            "",
        ]
    )
    assert 'class="attribution' not in _v2_page(attribution=[])


def test_the_recheck_box_shows_the_commitment_and_the_revealed_secret_when_present() -> None:
    manifest = f'<p class="note">Manifest sha256</p>\n<p><code class="hash">{"f" * 64}</code></p>\n'
    commitment = f'<p class="note">Commitment</p>\n<p><code class="hash">{"ab" * 32}</code></p>\n'
    secret = f'<p class="note">Run secret (revealed after the run)</p>\n<p><code class="hash">{"cd" * 32}</code></p>\n'
    cases = {("ab" * 32, "cd" * 32): commitment + secret, ("ab" * 32, None): commitment, (None, "cd" * 32): secret, (None, None): ""}
    for (commitment_hex, secret_hex), shown in cases.items():
        view = copy.deepcopy(BENCH)
        view["run"].update(commitment=commitment_hex, run_secret=secret_hex)
        assert _html(render.render_benchmark(view), "section", "class", "recheck").endswith(manifest + shown)


def test_the_run_box_shows_no_status_or_rated_chip() -> None:
    # the page's run is the latest rated v2 run or the latest v1 run (Decision 3), so a chip would say nothing
    view = copy.deepcopy(BENCH)
    view["run"].update(status="aborted", rated=False)
    for page in (render.render_benchmark(view), render.render_benchmark(_legacy_view())):
        box = _html(page, "div", "class", "run")
        assert box.startswith(
            '\n<p><strong>Run 2026-09-26</strong> <span class="muted">192 games: 190 rated (1 forfeit), 1 truncated, '
            "1 halted</span></p>\n"
        )
        assert "chip" not in box and "aborted" not in box and "unrated" not in box


@pytest.mark.parametrize("base", ["v2", "legacy"])
@pytest.mark.parametrize("key", [*V2_EXTRA, *(f"run.{key}" for key in V2_RUN_KEYS)])
def test_a_view_with_only_some_protocol_v2_keys_is_refused(base: str, key: str) -> None:
    # all or nothing: a half-built view must not render a page that is part protocol v1 and part v2
    view = copy.deepcopy(BENCH) if base == "v2" else _legacy_view()
    with pytest.raises(KeyError, match=rf"keys: {re.escape(key)}\W*$"):
        render.render_benchmark(_without(view, key))


def test_a_view_without_any_protocol_key_is_refused() -> None:
    # the builder sets every key, a v1 run's too: no view renders as protocol v1 by default any more
    keys = ", ".join([*V2_EXTRA, *(f"run.{key}" for key in V2_RUN_KEYS)])
    with pytest.raises(KeyError, match=rf"keys: {re.escape(keys)}\W*$"):
        render.render_benchmark(_pre_v2_view())


@pytest.mark.parametrize(
    ("base", "changes"),
    [
        ("v2", {"legacy": True}),
        ("v2", {"fairness": None}),
        ("v2", {"protocol": {"name": "spellbench/v1", "minor": None}}),
        ("legacy", {"legacy": False}),
        ("legacy", {"fairness": V2_EXTRA["fairness"]}),
        ("legacy", {"protocol": {"name": "spellbench/v2", "minor": 0}}),
    ],
    ids=["v2-flagged-legacy", "v2-without-fairness", "v2-named-v1", "v1-flagged-v2", "v1-with-fairness", "v1-named-v2"],
)
def test_a_view_whose_legacy_flag_protocol_and_fairness_disagree_is_refused(base: str, changes: dict[str, Any]) -> None:
    view = copy.deepcopy(BENCH) if base == "v2" else _legacy_view()
    view.update(copy.deepcopy(changes))
    with pytest.raises(ValueError, match="disagree"):
        render.render_benchmark(view)


def test_method_and_join_describe_v2() -> None:
    method = render.render_method(INFO)
    assert (
        "<section>\n<h2>Games</h2>\n<p>A benchmark uses a round robin or a fixed panel of local reference opponents. Every scheduled matchup "
        "is played as pairs of games with "
        "the seats swapped, each pair using the next deck of the benchmark's pool in both seats; a bot never plays "
        "itself. Every game has its own secret, so the two games of a pair shuffle independently, and ratings still "
        "count them as a pair. The run publishes a commitment to its secret before the first game and reveals the "
        "secret afterwards, so anyone can recompute every game's randomness.</p>\n</section>"
    ) in method
    assert (                                                                                                 # R3-21
        "<section>\n<h2>Fairness</h2>\n<p>Engines must never show a bot the other player's hand or either library, "
        "beyond what the rules let it know. The host checks what it can see in every decision before forwarding it, "
        "and publishes the verdict with the run; it cannot see hidden state. What the protocol does not close "
        "(spec 13): timing, since a bot can measure how long its opponent takes; adapter faithfulness, since a leak "
        "through an engine's text or extensions goes unnoticed until an audit; rules errors in an engine; trust in "
        "the operator, who holds the run secret during the run; and self-reported runs, whose bots ran without a "
        "verified sandbox.</p>\n</section>"
    ) in method
    join = render.render_join(INFO)
    assert f'<li>Read the <a href="{REPO}/blob/main/spec/SPELLBENCH_PROTOCOL_V2.md">protocol spec</a>.</li>' in join
    assert (
        f'<li>The smallest bot is about 15 lines: <a href="{REPO}/blob/main/examples/minimal_bot.py">'
        "examples/minimal_bot.py</a>.</li>"
    ) in join


def test_a_legacy_hero_chip_is_labelled() -> None:
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0]["chips"] = [{"benchmark_id": "pauper-kernel", "margin": 101.4, "bound": None, "legacy": True}]
    row = _html(render.render_home(home), "li", "data-bot", "heuristic")
    assert f'<span class="chip">pauper-kernel +101 {V1}</span>' in row                                    # R3-20
    assert "(protocol" not in render.render_home(HOME)


def test_a_models_rating_from_a_v1_run_says_so_after_the_benchmark() -> None:
    models = copy.deepcopy(MODELS)
    for model in models["models"]:
        model["benchmarks"][0]["legacy"] = True
    models["models"][1]["benchmarks"][0].update(margin=864.0, lower=817.0, upper=920.0, bound="lower")
    page = render.render_models(models)
    link = f'<a href="b/pauper-kernel/index.html">pauper-kernel</a> {V1}'
    assert f"<li>{link}: +388 (95% interval +322 to +464)</li>" in _html(page, "section", "id", "model-g115")
    assert f"<li>{link}: {GE}{NBSP}+864</li>" in _html(page, "section", "id", "model-heuristic")
    assert f"<li>{link}: reference</li>" in _html(page, "section", "id", "model-uniform")
    assert "(protocol" not in render.render_models(MODELS)


def test_a_chip_or_rating_without_a_legacy_flag_is_refused() -> None:
    # the builder flags every chip and rating row: a missing flag no longer reads as protocol v1
    home = copy.deepcopy(HOME)
    del home["hero"]["rows"][2]["chips"][0]["legacy"]
    with pytest.raises(KeyError, match="legacy"):
        render.render_home(home)
    models = copy.deepcopy(MODELS)
    del models["models"][2]["benchmarks"][0]["legacy"]
    with pytest.raises(KeyError, match="legacy"):
        render.render_models(models)


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


def test_a_grid_cell_names_the_sample_behind_its_share() -> None:
    # The share is over complete pairs only: 57 rated games, but 27 complete pairs (54 games).
    page = _pages()["benchmark"]
    cell = re.search(r'<td data-row="uniform" data-col="first" title="([^"]*)"', page)
    assert cell and cell.group(1) == "random vs first: 55% of the points, over 27 complete pairs (54 games)"
    assert 'title="heuristic vs random: 60% of the points, over 32 complete pairs (64 games)"' in page


def test_every_deck_and_style_gets_a_panel() -> None:
    page = _pages()["benchmark"]
    assert 'data-deck="Burn"' in page and 'data-deck="Elves"' in page
    assert "Not rated: " in _element(page, "section", "data-deck", "Elves")
    assert 'data-tag="baseline"' in page and 'data-tag="heuristic"' in page


def test_an_unrated_deck_gives_a_reason_for_readers_and_keeps_the_fit_error_on_hover() -> None:
    page = _pages()["benchmark"]
    assert (
        '<p class="empty">Not rated: <span title="reference_id has no games">'
        "the random bot has no complete pair on this deck</span></p>"
    ) in _html(page, "section", "data-deck", "Elves")
    bench = copy.deepcopy(BENCH)
    bench["deck_tables"][1].update(status="no_rated_games", reason="no rated games", fit_error=None)
    assert '<p class="empty">Not rated: no rated games</p>' in render.render_benchmark(bench)


def test_the_hero_subtitle_names_the_whiskers() -> None:
    hero = _pages()["home"]
    hero = hero[hero.index('id="hero"'):hero.index("</section>")]
    assert "Whiskers show 95% intervals." in hero and "Bars show" not in hero


def test_the_method_page_says_which_matchups_get_the_virtual_draw() -> None:
    assert "every matchup with a complete pair gets one extra virtual draw" in _pages()["method"]


def test_links_between_pages() -> None:
    pages = _pages()
    assert 'href="b/pauper-kernel/index.html"' in pages["home"]
    assert 'href="join.html"' in pages["home"] and 'href="method.html"' in pages["home"]
    assert 'href="models.html"' in pages["home"]
    assert 'href="../../index.html"' in pages["benchmark"]
    assert 'href="run/matches.jsonl"' in pages["benchmark"]
    assert 'href="../../models.html"' in pages["benchmark"]
    assert 'href="b/pauper-kernel/index.html"' in pages["models"]


def test_the_nav_has_a_models_item_after_leaderboard() -> None:
    pages = _pages()
    for name, page in pages.items():
        root = "../../" if name == "benchmark" else ""
        current = ' aria-current="page"' if name == "models" else ""
        assert f'<li><a href="{root}models.html"{current}>Models</a></li>' in page, name
    models_nav = re.search(r"<nav.*?</nav>", pages["models"], re.S).group(0)
    assert (
        '<li><a href="index.html#hero">Leaderboard</a></li>'
        '<li><a href="models.html" aria-current="page">Models</a></li>'
        '<li><a href="index.html#benchmarks">Benchmarks</a></li>'
    ) in models_nav


def test_every_bot_name_links_to_its_models_section_with_the_description_on_hover() -> None:
    pages = _pages()
    hero = pages["home"][pages["home"].index('id="hero"'):pages["home"].index("</section>")]
    assert '<span class="name"><a href="models.html#model-heuristic" title="heuristic bot">heuristic</a></span>' in hero
    assert '<span class="name"><a href="models.html#model-uniform" title="random bot">random</a></span>' in hero
    page = pages["benchmark"]
    overall = page[page.index('data-panel="overall"'):]
    row = _html(overall, "tr", "data-bot", "first")
    assert '<span class="label"><a href="../../models.html#model-first" title="first bot">first</a></span>' in row
    grid = page[page.index('<table class="grid">'):]
    assert '<th scope="col"><a href="../../models.html#model-first" title="first bot">first</a></th>' in grid
    assert '<th scope="row"><a href="../../models.html#model-first" title="first bot">first</a></th>' in grid
    # the attribution table, the description taken from the overall row of the same name
    attribution = _html(page, "section", "class", "attribution-section")
    assert '<td><span class="label"><a href="../../models.html#model-uniform" title="random bot">random</a></span></td>' in attribution
    # a bot without an overall row still links, without a description
    ghost = [{"name": "ghost", "label": "ghost bot", "games": 2, "halts": 1, "truncations": 0}]
    attribution = _html(_v2_page(attribution=ghost), "section", "class", "attribution-section")
    assert '<td><span class="label"><a href="../../models.html#model-ghost">ghost bot</a></span></td>' in attribution


def test_render_models_shows_each_bots_identity_rating_and_anchor() -> None:
    page = _pages()["models"]
    for model in MODELS["models"]:
        text = _element(page, "section", "id", f"model-{model['name']}")
        for expected in (model["label"], model["author"], model["description"], model["kind"], f"version {model['version']}"):
            assert expected in text, (model["name"], expected)
    g115 = _html(page, "section", "id", "model-g115")
    assert "engine mtg-kernel" in _element(page, "section", "id", "model-g115")
    assert '<a href="https://example.com/g115">https://example.com/g115</a>' in g115
    assert (
        '<li><a href="b/pauper-kernel/index.html">pauper-kernel</a>: +388 (95% interval +322 to +464)</li>' in g115
    )
    uniform = _html(page, "section", "id", "model-uniform")
    assert '<li><a href="b/pauper-kernel/index.html">pauper-kernel</a>: reference</li>' in uniform


def test_a_models_section_heading_adds_the_bot_name_when_it_differs_from_the_label() -> None:
    page = _pages()["models"]
    assert "<h2>g115</h2>" in _html(page, "section", "id", "model-g115")  # label == name: the label alone
    uniform = _html(page, "section", "id", "model-uniform")
    assert "<h2>random <span" in uniform and "(uniform)</span></h2>" in uniform


def test_a_models_rating_marks_bounds_and_not_estimable_intervals_like_the_benchmark_pages() -> None:
    models = copy.deepcopy(MODELS)
    models["models"][0]["benchmarks"][0].update(margin=864.0, lower=817.0, upper=920.0, bound="lower")
    models["models"][1]["benchmarks"][0].update(margin=102.0, lower=102.0, upper=102.0)
    page = render.render_models(models)
    g115 = _html(page, "section", "id", "model-g115")
    assert f"pauper-kernel</a>: {GE}{NBSP}+864</li>" in g115 and "95% interval" not in g115
    heuristic = _html(page, "section", "id", "model-heuristic")
    assert "pauper-kernel</a>: +102 (interval not estimable)</li>" in heuristic


def test_the_models_page_says_so_without_bots_and_a_section_says_so_without_a_rated_benchmark() -> None:
    assert "No bots yet." in render.render_models({"site": SITE, "models": []})
    models = copy.deepcopy(MODELS)
    models["models"][0]["benchmarks"] = []
    assert "No rated benchmark yet." in _element(render.render_models(models), "section", "id", "model-g115")


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
    assert "example.com" not in page  # a bot's own url is linked from its Models page section, not here
    models = copy.deepcopy(MODELS)
    models["models"][0]["url"] = "javascript:alert(1)"
    models["models"][2]["url"] = "https://example.com/first"
    page = render.render_models(models)
    assert 'href="javascript:' not in page
    assert 'href="https://example.com/first"' in page


def test_the_method_page_explains_the_rating() -> None:
    method = _pages()["method"]
    for phrase in ("seat", "forfeit", "virtual draw", "anchor", "Hero score", "spellbench validate"):
        assert phrase in method


def test_the_method_page_gives_a_recheck_command_that_runs_from_a_fresh_clone() -> None:
    assert "<code>uv run spellbench validate benchmarks/&lt;id&gt;/runs/&lt;name&gt;</code>" in _pages()["method"]


def test_long_unbroken_text_breaks_instead_of_widening_the_page() -> None:
    token = "W" * 200
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0]["label"] = token
    home["benchmarks"][0]["title"] = token
    bench = copy.deepcopy(BENCH)
    bench["title"] = bench["summary"] = bench["engine"]["version"] = token
    bench["overall"][0]["label"] = token
    bench["grid"]["labels"][0] = token
    home_page, bench_page = render.render_home(home), render.render_benchmark(bench)
    assert token in _element(home_page, "li", "data-bot", "heuristic")
    assert f'<a href="b/pauper-kernel/index.html">{token}</a>' in home_page
    assert f"<h1>{token}</h1>" in bench_page and f'<p class="lead">{token}</p>' in bench_page
    assert f"engine mtg-kernel {token}" in bench_page
    assert token in _element(bench_page, "tr", "data-bot", "heuristic")
    grid = bench_page[bench_page.index('<table class="grid">'):]
    assert re.search(rf'<th scope="col"><a [^>]*>{token}</a></th>', grid)
    assert re.search(rf'<th scope="row"><a [^>]*>{token}</a></th>', grid)
    # the grid's screen-reader corner label sits inside the scrolling wrapper
    assert re.search(r'<div class="table-wrap">\s*<table class="grid">\s*<thead><tr><th scope="col"><span class="sr-only">', bench_page)
    for page in (home_page, bench_page):
        style = page[page.index("<style>"):page.index("</style>")]
        # every free-text block inherits overflow-wrap: anywhere from body ...
        assert re.search(r"(?m)^body\s*\{[^}]*\boverflow-wrap:\s*anywhere\b", style)
        # ... while tables keep their min-content widths and scroll inside .table-wrap
        assert re.search(r"\.table-wrap\s*\{[^}]*\boverflow-wrap:\s*normal\b", style)
        # ... which is the containing block of the absolutely positioned screen-reader text inside it, so
        # its overflow clips that text too (else a wide grid pushed it, and the page, past the viewport)
        assert re.search(r"\.table-wrap\s*\{[^}]*\bposition:\s*relative\b", style)


def test_the_setup_list_caps_its_term_column_so_a_long_term_wraps() -> None:
    # Setup terms come from data (setup_rules). A max-content term column let one long term squeeze every value
    # to a sliver on a phone, or widen the page when unbroken; fit-content(40%) caps it, and terms and values
    # break like other free text (body's overflow-wrap: anywhere).
    token = "W" * 200
    page = _v2_page(setup_rules=[{"term": token, "value": token}])
    assert f"<dt>{token}</dt><dd>{token}</dd>" in page
    style = _style(page)
    assert re.search(r"(?m)^\.details dl\s*\{[^}]*\bgrid-template-columns:\s*fit-content\(40%\) minmax\(0, 1fr\);", style)
    assert re.search(r"(?m)^body\s*\{[^}]*\boverflow-wrap:\s*anywhere\b", style)
    assert not re.search(r"\.details (dl|dt|dd)\b[^{]*\{[^}]*(white-space:\s*nowrap|overflow-wrap:\s*normal)", style)


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
        chips=[{"benchmark_id": "pauper-kernel", "margin": 864.0, "bound": "lower", "legacy": False}],
    )
    page = render.render_home(home)
    row = _html(page, "li", "data-bot", "heuristic")
    assert f'<span class="value">{GE}{NBSP}+864</span>' in row
    assert f"pauper-kernel {GE}{NBSP}+864" in row
    assert 'class="arrow"' in row and 'class="whisker"' not in row
    assert _aria(row) == "at least 864 Elo above random, unbeaten in pauper-kernel: the rating is limited by the prior"
    hero = page[page.index('id="hero"'):page.index('id="benchmarks"')]
    assert (
        f"A score marked {GE} or {LE} is only a bound: the bot won every game, or lost every game, "
        "in a benchmark it entered."
    ) in hero
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
        chips=[{"benchmark_id": "pauper-kernel", "margin": score, "bound": bound, "legacy": False}],
    )
    label = _aria(_html(render.render_home(home), "li", "data-bot", "first"))
    assert label.startswith(phrase + ",")


def test_every_leaderboard_row_shows_the_rated_name_and_version() -> None:
    bench = copy.deepcopy(BENCH)
    bench["overall"][0].update(label="heuristic v2 (MCTS)", version="2.3.1")
    page = render.render_benchmark(bench)
    overall = page[page.index('data-panel="overall"'):]
    row = _html(overall, "tr", "data-bot", "heuristic")
    # muted text after the label: the registry name and version the ratings belong to
    assert re.search(r'<span class="by">[^<]*<span class="ident"[^>]*>heuristic 2\.3\.1</span></span>', row)
    assert "heuristic v2 (MCTS)" in _element(overall, "tr", "data-bot", "heuristic")
    for name in ("uniform", "first"):
        assert f"{name} 1.0.0" in _element(overall, "tr", "data-bot", name)
    style = page[page.index('data-panel="style"'):]
    assert "uniform 1.0.0" in _element(style, "tr", "data-bot", "uniform")  # style tables reuse the rows


def test_the_method_page_explains_bounds() -> None:
    # "won (or lost) every rated game": a draw gives each side half a point, so a record with one is finite
    method = _pages()["method"]
    assert "<h2>Bots that won or lost every game</h2>" in method
    assert (
        "A bot that won (or lost) every rated game has no finite best-fit rating. The virtual draw keeps it "
        "finite, so the site shows it as a bound, at least or at most, and that bound grows with the number of games played."
    ) in method
    assert "never lost" not in method


# ---------------- escaping: payloads in every string field of all four views ----------------

MARKUP_PAYLOADS = (
    "<img src=x onerror=alert(1)>",
    '"><svg onload=alert(1)>',
    "'><script>alert(1)</script>",
    "</title><script>alert(1)</script>",
    "</style><script>alert(1)</script>",
    '" onmouseover="alert(1)',
    "&lt;b&gt;already escaped&lt;/b&gt; &amp;",
    "\u202e\u200b</textarea><b>bidi</b>\u2066",  # bidi and zero-width characters around markup (render level only)
)
# Fields whose values choose the markup's shape: kept in the second pass so that bounded rows, rated
# deck tables, and links render with payloads in their text.
SHAPE_KEYS = frozenset({"bound", "status", "url", "repo_url"})


def _inject(value: Any, payload: str, keep: frozenset[str] = frozenset()) -> Any:
    """``value`` with every string replaced by ``payload``, except under the dict keys in ``keep``."""
    if isinstance(value, dict):
        return {key: item if key in keep else _inject(item, payload, keep) for key, item in value.items()}
    if isinstance(value, list):
        return [_inject(item, payload, keep) for item in value]
    return payload if isinstance(value, str) else value


def _fuzz_views() -> list[tuple[str, Callable[[Any], str], dict[str, Any]]]:
    """Each page's renderer with a view that takes every branch that shows data."""
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0].update(bound="lower", chips=[{"benchmark_id": "pauper-kernel", "margin": 101.4, "bound": "lower", "legacy": True}])
    home["hero"]["rows"][2]["approximate"] = home["hero"]["approximate"] = True
    bench = copy.deepcopy(BENCH)
    bench["overall"][0].update(bound="lower", wins=16, draws=0, losses=0)
    bench["overall"][2].update(url="https://example.com/first", ci_elo_milli=[985_000, 985_000])  # not estimable
    bench["overall"].append(_leader("ghost", "ghost", None, None, None, wins=0, draws=0, losses=0, games=0))
    models = copy.deepcopy(MODELS)
    models["models"][0]["benchmarks"][0].update(margin=864.0, lower=817.0, upper=920.0, bound="lower", legacy=True)
    models["models"][1]["benchmarks"][0].update(margin=102.0, lower=102.0, upper=102.0)  # interval not estimable
    models["models"][1]["benchmarks"].append(
        {"id": "new-one", "href": "b/new-one/index.html", "reference": False,
         "margin": None, "lower": None, "upper": None, "bound": None, "legacy": True}  # entered but unrated
    )
    models["models"].append(
        {"name": "ghost", "label": "ghost", "author": "Tests", "description": "", "url": None,
         "kind": "submitted model", "engine": None, "tags": [], "version": "1.0.0", "benchmarks": []}
    )
    return [
        ("home", render.render_home, home),
        ("benchmark", render.render_benchmark, bench),
        ("models", render.render_models, models),
        ("join", render.render_join, copy.deepcopy(INFO)),
        ("method", render.render_method, copy.deepcopy(INFO)),
    ]


class _Structure(HTMLParser):
    """The tags and attribute names of a page, in order, and its link targets."""

    def __init__(self, page: str) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, ...]] = []
        self.links: list[str] = []
        self.feed(page)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events.append((tag, *(name for name, _ in attrs)))
        self.links += [value for name, value in attrs if name in ("href", "src") and value is not None]

    def handle_endtag(self, tag: str) -> None:
        self.events.append(("/" + tag,))


@pytest.mark.parametrize("keep", [frozenset(), SHAPE_KEYS], ids=["every-string", "every-string-but-shape-keys"])
@pytest.mark.parametrize("payload", MARKUP_PAYLOADS)
def test_payloads_in_every_string_field_stay_text(payload: str, keep: frozenset[str]) -> None:
    for name, render_page, view in _fuzz_views():
        benign = _Structure(render_page(_inject(view, "text", keep)))
        page = render_page(_inject(view, payload, keep))
        # a payload that opened or closed a tag (a </title> or </style> breakout included) or added an
        # attribute would change the page's tag structure
        assert _Structure(page).events == benign.events, name
        assert payload not in page, name  # every payload holds a character that escaping rewrites
        assert page.count("<script>") == (1 if name == "benchmark" else 0), name  # only the tab script


def test_a_script_url_in_a_data_field_never_becomes_a_link() -> None:
    # hrefs keep their build-made relative paths; every other string, url and repo_url included, is the payload
    for name, render_page, view in _fuzz_views():
        links = _Structure(render_page(_inject(view, "javascript:alert(1)", frozenset({"href"})))).links
        assert links and not [link for link in links if link.strip().lower().startswith("javascript:")], name


# ---------------- axes, tiles, panel grid, card groups ----------------


def test_ticks_are_round_values_inside_the_scale() -> None:
    assert render._ticks((-560.0, 500.0)) == [-400, -200, 0, 200, 400]
    assert render._ticks((970.0, 1420.0)) == [1000, 1100, 1200, 1300, 1400]
    assert render._ticks((-1.0, 1.0)) == [-1, 0, 1]  # never a step below one Elo


def test_the_hero_has_an_elo_axis_and_gridlines_and_hover_text() -> None:
    home = _pages()["home"]
    axis = _html(home, "li", "class", "axis")
    assert '<span class="axis-title">Elo above random</span>' in axis and 'aria-hidden="true"' in home
    assert re.search(r'<text x="[0-9.]+%" y="12" text-anchor="middle">0</text>', axis)
    row = _html(home, "li", "data-bot", "heuristic")
    assert 'class="gridline"' in row
    assert "<title>heuristic: 101 Elo above random, 95% interval +52 to +150</title>" in row


def test_a_leaderboard_has_an_elo_axis_an_anchor_line_and_hover_text() -> None:
    page = _pages()["benchmark"]
    overall = page[page.index('data-panel="overall"'):]
    head = overall[overall.index("<thead>"):overall.index("</thead>")]
    assert '<svg class="ticks"' in head and ">1000</text>" in head
    row = _html(overall, "tr", "data-bot", "heuristic")
    assert '<line class="zero"' in row  # the random bot's 1000
    assert "<title>heuristic: Elo 1101, 95% interval 1052 to 1150</title>" in row


def test_the_benchmark_page_opens_with_tiles_then_the_leaderboards_then_the_run() -> None:
    page = _pages()["benchmark"]
    tiles = _html(page, "dl", "class", "tiles")
    text = re.sub(r"<[^>]+>", " ", tiles)
    assert "Rated games" in text and "190" in text and "of 192 played" in text
    assert "Bots" in text and "2 decks" in text
    assert "Matchups measured" in text and "3" in text and "of 3 possible" in text
    assert "Top rated" in text and 'href="../../models.html#model-heuristic"' in tiles and "1101 Elo" in text
    order = [page.index(marker) for marker in ('class="tiles"', 'class="leaderboards"', 'class="matchups"',
                                              '<section class="about">', 'class="details"')]
    assert order == sorted(order)


def test_the_top_rated_tile_skips_the_anchor_and_marks_a_bound() -> None:
    bench = copy.deepcopy(BENCH)
    bench["overall"] = [bench["overall"][1], {**bench["overall"][0], "bound": "lower"}, bench["overall"][2]]
    text = re.sub(r"<[^>]+>", " ", _html(render.render_benchmark(bench), "dl", "class", "tiles"))
    assert "heuristic" in text and f"{GE}{NBSP}1101 Elo" in text


def _panel_bench() -> dict[str, Any]:
    """BENCH as a reference-panel board: heuristic is the panel, and uniform never met first."""
    bench = copy.deepcopy(BENCH)
    bench["grid"]["cells"][1][2] = bench["grid"]["cells"][2][1] = None
    bench["evaluation"] = {"opponents": ["heuristic"], "sources": ["2026-09-26"], "caveat": "Panel caveat."}
    return bench


def test_a_reference_panel_grid_shows_only_the_panels_columns() -> None:
    page = render.render_benchmark(_panel_bench())
    grid = page[page.index('<table class="grid panel">'):]
    assert grid.count('data-col="heuristic"') == 3 and 'data-col="uniform"' not in grid
    assert "Entrants play the reference panel, not one another" in page
    assert '<td data-row="heuristic" data-col="heuristic" class="self"></td>' in grid


def test_a_panel_grid_falls_back_to_every_column_when_a_matchup_skips_the_panel() -> None:
    bench = _panel_bench()
    bench["grid"]["cells"][1][2] = {"score": 0.5, "games": 2, "complete_pairs": 1}
    page = render.render_benchmark(bench)
    assert '<table class="grid">' in page and page.count('data-col="uniform"') == 3
    bench["evaluation"]["opponents"] = ["nobody"]
    assert '<table class="grid">' in render.render_benchmark(bench)


def test_the_grid_has_a_legend_and_tells_unplayed_cells_from_the_diagonal() -> None:
    page = render.render_benchmark(_panel_bench())
    assert '<div class="legend" aria-hidden="true">' in page and "not measured" in page
    full = _pages()["benchmark"]
    assert '<td data-row="first" data-col="first" class="self"></td>' in full
    bench = copy.deepcopy(BENCH)
    bench["grid"]["cells"][1][2] = None
    assert '<td data-row="uniform" data-col="first" class="none"></td>' in render.render_benchmark(bench)


def test_home_groups_live_waiting_and_proposed_benchmarks() -> None:
    home = _pages()["home"]
    groups = re.findall(r'<h3 class="group">([^<]+)</h3>', home)
    assert groups == ["Live boards", "Awaiting a published run", "Proposed"]
    live = home[home.index("Live boards"):home.index("Awaiting a published run")]
    assert 'href="b/pauper-kernel/index.html"' in live and "New benchmark" not in live
    empty = copy.deepcopy(HOME)
    empty["benchmarks"], empty["proposed"] = [], []
    assert '<p class="empty">No benchmarks yet.</p>' in render.render_home(empty)


def test_a_live_card_lists_its_leaders() -> None:
    home = copy.deepcopy(HOME)
    home["benchmarks"][0]["leaders"] = [
        {"label": "heuristic", "elo_milli": 1_101_499, "bound": None},
        {"label": "first", "elo_milli": 1_050_000, "bound": "lower"},
    ]
    page = render.render_home(home)
    mini = _html(page, "ol", "class", "leaders-mini")
    assert '<li><span class="label">heuristic</span> <span class="num">1101</span></li>' in mini
    assert f'<span class="num">{GE}{NBSP}1050</span>' in mini
    assert 'class="leaders-mini"' not in _pages()["home"]  # no leaders, no list


def test_the_models_page_opens_with_a_jump_list() -> None:
    page = _pages()["models"]
    jump = _html(page, "nav", "class", "jump")
    assert [name for name in re.findall(r'href="#model-([^"]+)"', jump)] == ["g115", "heuristic", "uniform"]
    assert ">random</a>" in jump
    assert 'class="jump"' not in render.render_models({**MODELS, "models": []})
