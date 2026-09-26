"""Static HTML for the benchmark site, rendered from plain view-model dicts.

The renderer is pure: each ``render_*`` function reads only its view and
returns the page text, so an unchanged view renders byte for byte. The view
shapes and the markup hooks the build relies on (``data-bot``,
``data-panel``, ``data-deck``, ``data-tag``, ``data-row`` then ``data-col``,
``id="hero"``, ``id="benchmarks"``) are the Task 6 and Task 8 contract in
``docs/design/2026-09-26-benchmark-site-plan.md``.

- Every data string goes through ``html.escape(value, quote=True)``,
  attribute values included. A bot ``url`` becomes a link only when it
  starts with ``http://`` or ``https://``; otherwise the label is plain text.
- Links are relative and explicit, never a bare directory. Benchmark pages
  sit two directories down (``b/<id>/index.html``), so their cross-page
  links start with ``../../``.
- Pages load nothing external: one inline stylesheet with light and dark
  color tokens, inline SVG charts, and on benchmark pages a few lines of tab
  script. Without script every tab panel shows under its own heading.
- SVG x positions are percentages of the chart width with one decimal, so
  marks keep their shape at any width and the output stays stable.
"""

from __future__ import annotations

import html
from typing import Any, Iterable, Mapping, Sequence

_SEP = " \N{MIDDLE DOT} "
_ARROW = "\N{RIGHTWARDS ARROW}"
_CHECK = "\N{CHECK MARK}"
_MINUS = "\N{MINUS SIGN}"
_ANCHOR_ELO_MILLI = 1_000_000  # the random bot's fixed Elo, 1000
_TINT_MAX = 55  # percent of the accent (or warning) color in a 100% (or 0%) grid cell

_NAV = (
    ("Leaderboard", "index.html#hero"),
    ("Benchmarks", "index.html#benchmarks"),
    ("Join", "join.html"),
    ("Method", "method.html"),
)

_HERO_SUBTITLE = (
    "Each bot's Elo minus the random bot's, averaged over the benchmarks it entered. "
    "Bars show 95% intervals. "
    "The score compares skill above random across formats, not head-to-head results."
)

_JOIN_INTRO = (
    "Spellbench is a small protocol. The arena sends your bot one decision at a time as a line of JSON "
    "listing the legal choices, and your bot answers with the one it picks. Any language works: your bot "
    "is its own process reading standard input and writing standard output."
)

_METHOD_SECTIONS = (
    (
        "Games",
        "Each benchmark is a round robin. Every matchup is played as pairs of games that share one random "
        "seed with the seats swapped, so both bots face the same shuffles. Each pair uses the next deck of "
        "the benchmark's pool in both seats, and a bot never plays itself.",
    ),
    (
        "What counts",
        "Wins, losses, and draws count. A bot that times out, crashes, or answers with an illegal choice "
        "forfeits that game, and a forfeit counts as a loss. Games the engine halts or stops at its step "
        "limit are recorded and left out.",
    ),
    (
        "Ratings",
        "Ratings come from a Bradley-Terry fit over complete seat-swapped pairs. A draw counts as half a "
        "win, and every matchup gets one extra virtual draw so a perfect record still has a finite rating. "
        "The random bot is the anchor: its Elo is fixed at 1000. The 95% intervals come from a bootstrap "
        "that resamples whole pairs within each matchup.",
    ),
    (
        "By deck",
        "Each deck's table is the same fit run on that deck's games alone, still anchored on the random bot.",
    ),
    (
        "Hero score",
        "A bot's Hero score is its Elo above the random bot, averaged over the benchmarks it entered. With "
        "one benchmark, its interval is that benchmark's interval. With several, the per-benchmark errors "
        "are combined as if independent, so the interval is approximate. The Hero score compares skill "
        "above random across formats; it is not a head-to-head result.",
    ),
)

_TAB_SCRIPT = """<script>
document.querySelectorAll("[data-tabs]").forEach(function (root) {
  var tabs = root.querySelectorAll('[role="tab"]');
  var panels = root.querySelectorAll('[role="tabpanel"]');
  root.querySelector('[role="tablist"]').hidden = false;
  function show(index) {
    tabs.forEach(function (tab, i) { tab.setAttribute("aria-selected", String(i === index)); });
    panels.forEach(function (panel, i) { panel.hidden = i !== index; });
  }
  tabs.forEach(function (tab, i) { tab.addEventListener("click", function () { show(i); }); });
  show(0);
});
</script>"""

_STYLE = """:root {
  --bg: #ffffff;
  --surface: #f6f7f9;
  --text: #1d2026;
  --muted: #5d6470;
  --border: #d9dde3;
  --accent: #2a78d6;
  --accent-soft: #e3eefb;
  --warn: #eb6834;
  --good: #1f8a4c;
  /* text in the accent and good hues, nudged toward the text color for contrast */
  --accent-ink: color-mix(in srgb, var(--accent) 80%, var(--text));
  --good-ink: color-mix(in srgb, var(--good) 80%, var(--text));
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #111418;
    --surface: #1a1e24;
    --text: #e7eaee;
    --muted: #9aa3ad;
    --border: #2c323a;
    --accent: #5b9df0;
    --accent-soft: #1d2a3b;
    --warn: #f08a5d;
    --good: #4cc27f;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #111418;
  --surface: #1a1e24;
  --text: #e7eaee;
  --muted: #9aa3ad;
  --border: #2c323a;
  --accent: #5b9df0;
  --accent-soft: #1d2a3b;
  --warn: #f08a5d;
  --good: #4cc27f;
  color-scheme: dark;
}
*, *::before, *::after { box-sizing: border-box; }
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 16px;
  line-height: 1.55;
}
a { color: var(--accent-ink); text-underline-offset: 0.2em; }
a:hover { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
h1, h2, h3 { margin: 0; font-weight: 600; line-height: 1.25; text-wrap: balance; }
h1 { font-size: clamp(26px, 3vw + 16px, 34px); letter-spacing: -0.015em; }
h2 { font-size: 21px; letter-spacing: -0.01em; }
h3 { font-size: 16px; }
p { margin: 0; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size: 0.875em; }
code { padding: 0.1em 0.35em; border-radius: 4px; background: var(--surface); overflow-wrap: anywhere; }
pre { margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); white-space: pre-wrap; overflow-wrap: anywhere; }
pre code { padding: 0; background: none; font-size: inherit; }
.sr-only, .tabs:not([hidden]) ~ .panel .panel-title {
  position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.wrap { max-width: 960px; margin: 0 auto; padding-left: 16px; padding-right: 16px; }
.site-header { border-bottom: 1px solid var(--border); }
.site-header .wrap { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 24px; padding-top: 16px; padding-bottom: 16px; }
.brand a { margin-right: 10px; color: var(--text); font-size: 20px; font-weight: 700; letter-spacing: -0.02em; text-decoration: none; }
.brand span { display: inline-block; color: var(--muted); font-size: 14px; }
.site-header ul { display: flex; flex-wrap: wrap; gap: 4px 20px; margin: 0; padding: 0; list-style: none; }
.site-header nav a { color: var(--muted); font-size: 15px; text-decoration: none; }
.site-header nav a:hover, .site-header nav a[aria-current="page"] { color: var(--text); }
main { padding-top: 40px; padding-bottom: 64px; }
.site-footer { border-top: 1px solid var(--border); color: var(--muted); font-size: 14px; }
.site-footer .wrap { padding-top: 20px; padding-bottom: 40px; }
.site-footer p + p { margin-top: 4px; }
.site-footer a { color: inherit; }
.site-footer a:hover { color: var(--text); }
.lead { max-width: 46rem; margin-top: 10px; color: var(--muted); font-size: 17px; }
.lead + .meta { margin-top: 8px; }
.meta, .note, .muted { color: var(--muted); }
.meta, .note { font-size: 14px; }
.empty { padding: 16px 0; color: var(--muted); }
.chip {
  display: inline-block; padding: 0 8px; border-radius: 999px;
  background: var(--accent-soft); color: var(--accent-ink);
  font-size: 12.5px; font-weight: 500; line-height: 20px; font-variant-numeric: tabular-nums;
  white-space: nowrap; vertical-align: 1px;
}
.chip.quiet { background: none; box-shadow: inset 0 0 0 1px var(--border); color: var(--muted); }
.chips .chip { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
ol.hero { margin: 24px 0 0; padding: 0; list-style: none; border-top: 1px solid var(--border); }
ol.hero > li {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "who value" "bar bar" "chips chips";
  align-items: center; gap: 6px 16px; padding: 12px 0; border-bottom: 1px solid var(--border);
}
.who { grid-area: who; min-width: 0; overflow-wrap: anywhere; }
.name, .label { font-weight: 600; }
.by { display: block; color: var(--muted); font-size: 13px; font-weight: 400; }
.value { grid-area: value; font-size: 17px; font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.reference .value { color: var(--muted); }
.chips { grid-area: chips; display: flex; flex-wrap: wrap; gap: 4px; }
#hero .note { margin-top: 12px; }
svg { display: block; overflow: visible; }
svg.bar { grid-area: bar; width: 100%; height: 24px; }
svg.ci { width: 100%; min-width: 96px; height: 16px; }
.zero { stroke: var(--muted); stroke-dasharray: 3 3; }
.whisker { stroke: var(--text); stroke-width: 1.5; }
.track { stroke: var(--border); }
.up { color: var(--accent); }
.down { color: var(--warn); }
.flat { color: var(--muted); }
@media (min-width: 720px) {
  ol.hero > li { grid-template-columns: 11rem minmax(0, 1fr) 3.5rem 11rem; grid-template-areas: "who bar value chips"; gap: 16px; }
}
.cta { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px 24px; margin-top: 40px; padding: 20px 24px; border-radius: 12px; background: var(--surface); }
.cta h2 { font-size: 18px; }
.cta p { margin-top: 4px; color: var(--muted); }
.button { display: inline-block; padding: 8px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--text); font-weight: 500; text-decoration: none; white-space: nowrap; }
.button:hover { border-color: var(--accent); color: var(--accent-ink); }
#benchmarks { margin-top: 56px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); gap: 12px; margin-top: 16px; }
.card { position: relative; padding: 16px 18px; border: 1px solid var(--border); border-radius: 12px; overflow-wrap: anywhere; }
.card.linked:hover { border-color: var(--accent); }
.card.proposed { border-style: dashed; }
.card h3 a { color: var(--text); text-decoration: none; }
.card h3 a::after { content: ""; position: absolute; inset: 0; border-radius: 12px; }
.card h3 a:focus-visible { outline: none; }
.card h3 a:focus-visible::after { outline: 2px solid var(--accent); outline-offset: 2px; }
.card p { margin-top: 6px; font-size: 15px; }
.card .meta, .card .status { font-size: 14px; }
.status { color: var(--muted); }
.status.live { color: var(--text); }
.status.live::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 8px; border-radius: 50%; background: var(--good); vertical-align: 1px; }
.run { margin-top: 24px; padding: 14px 18px; border-radius: 12px; background: var(--surface); }
.files { display: flex; flex-wrap: wrap; gap: 4px 20px; margin: 6px 0 0; padding: 0; list-style: none; font-size: 14px; }
.validated { color: var(--good-ink); font-weight: 600; }
.leaderboards { margin-top: 40px; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; }
.tabs button { padding: 6px 12px; border: 0; border-radius: 8px; background: none; color: var(--muted); font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; }
.tabs button:hover { color: var(--text); }
.tabs button[aria-selected="true"] { background: var(--accent-soft); color: var(--accent-ink); }
.tabs[hidden] ~ .panel + .panel { margin-top: 48px; }
.panel-title { margin-bottom: 8px; }
.panel .note { margin-bottom: 12px; }
.panel h3 { margin-bottom: 8px; }
.panel .empty { padding: 0; }
.panel section + section { margin-top: 32px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 15px; }
th, td { padding: 10px 12px; text-align: left; vertical-align: middle; }
thead th { padding-top: 6px; padding-bottom: 6px; border-bottom: 1px solid var(--border); color: var(--muted); font-size: 13px; font-weight: 500; white-space: nowrap; }
table.leaders tbody tr { border-bottom: 1px solid var(--border); }
.num { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.rank { color: var(--muted); }
.elo { font-weight: 600; }
.ci-cell { width: 34%; }
.matchups { margin-top: 56px; }
.matchups .note { margin: 4px 0 16px; }
table.grid { width: auto; border-collapse: separate; border-spacing: 3px; }
table.grid th { padding: 4px 8px; color: var(--muted); font-size: 13px; font-weight: 500; }
table.grid thead th { border: 0; text-align: center; vertical-align: bottom; white-space: normal; }
table.grid tbody th { color: var(--text); text-align: right; }
table.grid td { width: 4.5rem; padding: 10px 8px; border-radius: 6px; text-align: center; font-variant-numeric: tabular-nums; }
table.grid td.none { background: var(--surface); }
@media (max-width: 599px) {
  th, td { padding: 8px 6px; }
  table { font-size: 14px; }
}
.details { display: grid; gap: 32px 40px; margin-top: 56px; }
.details dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 8px 20px; margin: 14px 0 0; font-size: 15px; }
.details dt { color: var(--muted); }
.details dd { margin: 0; overflow-wrap: anywhere; }
.recheck { padding: 18px 20px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.recheck p, .recheck pre { margin-top: 10px; }
.recheck code { background: var(--bg); }
.hash { word-break: break-all; }
@media (min-width: 760px) {
  .details { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
}
.prose { max-width: 44rem; }
.prose h2 { margin-top: 32px; font-size: 19px; }
.prose p, .prose ol { margin-top: 10px; }
.prose ol { padding-left: 1.4em; }
.prose li + li { margin-top: 6px; }
"""


def format_elo(elo_milli: int) -> str:
    """Elo display from fixed-point milli-Elo: ``1_101_499`` gives ``"1101"``."""
    return f"{elo_milli / 1000:.0f}"


def format_margin(value: float) -> str:
    """Signed whole Elo: ``"+101"``, ``"0"`` when it rounds to zero, and negatives with U+2212 (not a hyphen)."""
    rounded = round(value)
    if rounded > 0:
        return f"+{rounded}"
    if rounded < 0:
        return f"{_MINUS}{-rounded}"
    return "0"


def format_share(score: float) -> str:
    """A share of the points as a whole percentage: ``0.6`` gives ``"60%"``."""
    return f"{score * 100:.0f}%"


def render_home(view: Mapping[str, Any]) -> str:
    """``index.html``: the Hero chart, the call to action, and the benchmark cards."""
    site = view["site"]
    cards = [_benchmark_card(card) for card in view["benchmarks"]]
    cards += [_proposed_card(card) for card in view["proposed"]]
    listing = ['<div class="cards">', *cards, "</div>"] if cards else ['<p class="empty">No benchmarks yet.</p>']
    main = [
        _hero(view["hero"]),
        '<section class="cta">',
        "<div>",
        "<h2>Put your model on the benchmark</h2>",
        "<p>Speak the Spellbench protocol, send us your bot, get rated.</p>",
        "</div>",
        f'<a class="button" href="join.html">How to join {_ARROW}</a>',
        "</section>",
        '<section id="benchmarks">',
        "<h2>Benchmarks</h2>",
        *listing,
        "</section>",
    ]
    return _page(
        site,
        title=f"{site['title']}{_SEP}{site['tagline']}",
        description=(
            f"{site['title']}, a {site['tagline']}: Elo above the random bot, "
            "re-derived from committed match ledgers."
        ),
        main="\n".join(main),
    )


def render_benchmark(view: Mapping[str, Any]) -> str:
    """``b/<id>/index.html``: one benchmark's latest run, its leaderboards, and its matchups."""
    site, engine = view["site"], view["engine"]
    meta = _SEP.join(
        [
            f"engine {_e(engine['name'])} {_e(engine['version'])}",
            _count(len(view["decks"]), "deck"),
            "same deck in both seats",
        ]
    )
    main = [
        f"<h1>{_e(view['title'])}</h1>",
        f'<p class="lead">{_e(view["summary"])}</p>',
        f'<p class="meta">{meta}</p>',
        _run_box(view["run"]),
        _leaderboards(view),
        _grid(view["grid"]),
        _details(view),
    ]
    return _page(
        site,
        title=f"{view['title']}{_SEP}{site['title']}",
        description=view["summary"],
        main="\n".join(main),
        depth=2,
        script=True,
    )


def render_join(view: Mapping[str, Any]) -> str:
    """``join.html``: how to put a bot on the benchmark (a placeholder until the join kit)."""
    site = view["site"]
    repo = site["repo_url"]
    spec = _link(repo + "/blob/main/spec/SPELLBENCH_PROTOCOL_V1.md", "protocol spec")
    readme = _link(repo + "#write-a-bot", '"Write a bot" section')
    issues = _link(repo + "/issues", "open an issue on the repository")
    main = [
        '<div class="prose">',
        "<h1>Put your model on the benchmark</h1>",
        f"<p>{_JOIN_INTRO}</p>",
        "<h2>Get started</h2>",
        "<ol>",
        f"<li>Read the {spec}.</li>",
        f"<li>Start from the README's {readme}.</li>",
        "<li>Play your bot against the builtin bots with <code>spellbench run</code>.</li>",
        "</ol>",
        f"<p>A submission guide and form are on the way. Until then, {issues}.</p>",
        "</div>",
    ]
    return _page(
        site,
        title=f"Join{_SEP}{site['title']}",
        description="Speak the Spellbench protocol, send us your bot, get rated.",
        main="\n".join(main),
        current="Join",
    )


def render_method(view: Mapping[str, Any]) -> str:
    """``method.html``: how ratings work, in plain language."""
    site = view["site"]
    clone = _link(site["repo_url"], "Clone the repository")
    sections = [f"<section>\n<h2>{heading}</h2>\n<p>{text}</p>\n</section>" for heading, text in _METHOD_SECTIONS]
    sections.append(
        "<section>\n<h2>Check it yourself</h2>\n"
        f"<p>Every number on this site is re-derived from a committed match ledger. {clone} and run "
        "<code>spellbench validate benchmarks/&lt;id&gt;/runs/&lt;date&gt;</code>: it checks every file's "
        "hash and recomputes every rating from the ledger.</p>\n</section>"
    )
    main = ['<div class="prose">', "<h1>How ratings work</h1>", *sections, "</div>"]
    return _page(
        site,
        title=f"How ratings work{_SEP}{site['title']}",
        description="How Spellbench rates bots: seat-swapped pairs, an anchored Bradley-Terry fit, and ledgers anyone can re-check.",
        main="\n".join(main),
        current="Method",
    )


# ---------------- page shell and small helpers ----------------


def _page(
    site: Mapping[str, Any],
    *,
    title: str,
    description: str,
    main: str,
    depth: int = 0,
    current: str | None = None,
    script: bool = False,
) -> str:
    """A complete document: head with the inline style, header, ``main``, footer.

    ``depth`` counts the directories between the page and the site root; every
    cross-page link gets that many ``../``. ``current`` names the nav entry to
    mark as the current page, and ``script`` adds the tab script.
    """
    root = "../" * depth
    nav = []
    for name, href in _NAV:
        mark = ' aria-current="page"' if name == current else ""
        nav.append(f'<li><a href="{root}{href}"{mark}>{name}</a></li>')
    repo = site["repo_url"]
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        f'<meta name="description" content="{_e(description)}">',
        f"<title>{_e(title)}</title>",
        f"<style>\n{_STYLE}</style>",
        "</head>",
        "<body>",
        '<header class="site-header">',
        '<div class="wrap">',
        f'<p class="brand"><a href="{root}index.html">{_e(site["title"])}</a> <span>{_e(site["tagline"])}</span></p>',
        '<nav aria-label="Site">',
        f"<ul>{''.join(nav)}</ul>",
        "</nav>",
        "</div>",
        "</header>",
        '<main class="wrap">',
        main,
        "</main>",
        '<footer class="site-footer">',
        '<div class="wrap">',
        "<p>Every rating is re-derived from a committed match ledger with <code>spellbench validate</code>.</p>",
        f"<p>Source and ledgers: {_link(repo, repo.split('://', 1)[-1])}</p>",
        "</div>",
        "</footer>",
    ]
    if script:
        parts.append(_TAB_SCRIPT)
    parts += ["</body>", "</html>"]
    return "\n".join(parts) + "\n"


def _e(value: object) -> str:
    """Escape a data value for HTML text or a double-quoted attribute."""
    return html.escape(str(value), quote=True)


def _link(url: str | None, text: str) -> str:
    """``text`` linked to ``url`` when it is an http(s) URL; otherwise plain text."""
    if url is not None and url.startswith(("http://", "https://")):
        return f'<a href="{_e(url)}">{_e(text)}</a>'
    return _e(text)


def _count(number: int, noun: str) -> str:
    """``"1 deck"``, ``"8 decks"``."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _note(text: str) -> str:
    return f'<p class="note">{text}</p>'


def _file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _scale(values: Iterable[float]) -> tuple[float, float]:
    """A shared axis over ``values``: their range padded 8% on each side, never a zero span."""
    points = list(values)
    if not points:
        return -1.0, 1.0
    low, high = min(points), max(points)
    pad = (high - low) * 0.08 if high > low else 1.0
    return low - pad, high + pad


def _position(value: float, scale: tuple[float, float]) -> float:
    """Where ``value`` falls on ``scale``, in percent of the chart width, rounded to one decimal."""
    low, high = scale
    return round((value - low) / (high - low) * 100, 1)


# ---------------- home page ----------------


def _hero(hero: Mapping[str, Any]) -> str:
    """The Hero chart: one row per bot, bars on a scale shared by every row."""
    rows = hero["rows"]
    parts = [
        '<section id="hero">',
        "<h1>Elo above the random bot</h1>",
        f'<p class="lead">{_HERO_SUBTITLE}</p>',
    ]
    if rows:
        values = [0.0]
        for row in rows:
            values.append(row["score"])
            values.extend(bound for bound in (row["lower"], row["upper"]) if bound is not None)
        scale = _scale(values)
        parts.append('<ol class="hero">')
        parts.extend(_hero_row(row, scale) for row in rows)
        parts.append("</ol>")
        note = f"{_count(hero['benchmark_count'], 'benchmark')} in the chart."
        if hero["approximate"]:
            note += " Intervals that combine several benchmarks are approximate."
        parts.append(_note(note))
    else:
        parts.append('<p class="empty">No rated benchmark yet.</p>')
    parts.append("</section>")
    return "\n".join(parts)


def _hero_row(row: Mapping[str, Any], scale: tuple[float, float]) -> str:
    who = f'<span class="name">{_e(row["label"])}</span>'
    if row["reference"]:
        who += ' <span class="chip quiet">reference</span>'
    if row["author"]:
        who += f'<span class="by">{_e(row["author"])}</span>'
    chips = " ".join(
        f'<span class="chip">{_e(chip["benchmark_id"])} {format_margin(chip["margin"])}</span>' for chip in row["chips"]
    )
    kind = ' class="reference"' if row["reference"] else ""
    return "\n".join(
        [
            f'<li data-bot="{_e(row["name"])}"{kind}>',
            f'<div class="who">{who}</div>',
            _hero_bar(row, scale),
            f'<span class="value">{format_margin(row["score"])}</span>',
            f'<span class="chips">{chips}</span>',
            "</li>",
        ]
    )


def _hero_bar(row: Mapping[str, Any], scale: tuple[float, float]) -> str:
    """A bar from 0 to the score over a dashed zero line, with a whisker across the interval."""
    zero = _position(0.0, scale)
    marks = [f'<line class="zero" x1="{zero:.1f}%" y1="0" x2="{zero:.1f}%" y2="24"/>']
    if row["reference"]:
        marks.append(f'<circle class="flat" cx="{zero:.1f}%" cy="12" r="4" fill="currentColor"/>')
        label = "0, the reference"
    else:
        score, lower, upper = row["score"], row["lower"], row["upper"]
        end = _position(score, scale)
        tone = "up" if score >= 0 else "down"
        marks.append(
            f'<rect class="{tone}" x="{min(zero, end):.1f}%" y="6" width="{abs(end - zero):.1f}%" height="12" '
            'rx="2" fill="currentColor"/>'
        )
        label = f"{format_margin(score)} Elo above random"
        if lower is not None and upper is not None:
            low, high = _position(lower, scale), _position(upper, scale)
            marks.append(
                f'<g class="whisker"><line x1="{low:.1f}%" y1="12" x2="{high:.1f}%" y2="12"/>'
                f'<line x1="{low:.1f}%" y1="8" x2="{low:.1f}%" y2="16"/>'
                f'<line x1="{high:.1f}%" y1="8" x2="{high:.1f}%" y2="16"/></g>'
            )
            interval = "approximate 95% interval" if row["approximate"] else "95% interval"
            label += f", {interval} {format_margin(lower)} to {format_margin(upper)}"
        else:
            label += ", no interval"
    return f'<svg class="bar" width="100%" height="24" role="img" aria-label="{_e(label)}">{"".join(marks)}</svg>'


def _benchmark_card(card: Mapping[str, Any]) -> str:
    title = _e(card["title"])
    linked = card["href"] is not None
    heading = f'<a href="{_e(card["href"])}">{title}</a>' if linked else title
    facts = [_e(card["engine_name"]), _count(card["deck_count"], "deck"), _count(card["bot_count"], "bot")]
    if card["games"] is not None:
        facts.append(_count(card["games"], "game"))
    if card["run_name"] is not None:
        status = f'<p class="status live">Latest run {_e(card["run_name"])}</p>'
    else:
        status = '<p class="status">No published run yet</p>'
    return "\n".join(
        [
            f'<article class="{"card linked" if linked else "card"}">',
            f"<h3>{heading}</h3>",
            f'<p>{_e(card["summary"])}</p>',
            f'<p class="meta">{_SEP.join(facts)}</p>',
            status,
            "</article>",
        ]
    )


def _proposed_card(card: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            '<article class="card proposed">',
            f"<h3>{_e(card['title'])}</h3>",
            f"<p>{_e(card['summary'])}</p>",
            f'<p class="status">Proposed{_SEP}needs {_e(card["needs"])}</p>',
            "</article>",
        ]
    )


# ---------------- benchmark page ----------------


def _run_box(run: Mapping[str, Any]) -> str:
    """The run's name and game counts, its files for download, and the validation mark."""
    games = run["games"]
    rated = f"{games['rated']} rated"
    if games["forfeit"]:
        rated += f" ({_count(games['forfeit'], 'forfeit')})"
    counts = ", ".join([rated] + [f"{games[key]} {key}" for key in ("truncated", "halted") if games[key]])
    files = [
        f'<li><a href="{_e(item["href"])}" download>{_e(item["name"])}</a> '
        f'<span class="muted">{_file_size(item["bytes"])}</span></li>'
        for item in run["files"]
    ]
    return "\n".join(
        [
            '<div class="run">',
            f'<p><strong>Run {_e(run["name"])}</strong> <span class="muted">{_count(games["total"], "game")}: {counts}</span></p>',
            '<ul class="files">',
            *files,
            f'<li class="validated">validated {_CHECK}</li>',
            "</ul>",
            "</div>",
        ]
    )


def _leaderboards(view: Mapping[str, Any]) -> str:
    """The Overall, By deck, and By training style panels behind one tab bar.

    Style tables are overall rows filtered by tag, so they reuse the overall
    table's scale and each bot keeps its position across those tabs. Each deck
    table is its own fit and gets its own scale.
    """
    overall_scale = _elo_scale(view["overall"])
    overall = [
        '<section data-panel="overall">',
        '<h2 class="panel-title">Overall</h2>',
        _note("The random bot is the anchor, fixed at 1000. Lines show 95% intervals."),
        _leader_table(view["overall"], overall_scale),
        "</section>",
    ]
    by_deck = ['<h2 class="panel-title">By deck</h2>']
    if view["deck_tables"]:
        pairs = _count(view["pairs_per_deck"], "seat-swapped pair")
        by_deck.append(_note(f"Each deck is rated on its own games ({pairs} per matchup), still anchored on the random bot."))
        by_deck += [_deck_section(table) for table in view["deck_tables"]]
    else:
        by_deck.append(_note("This benchmark uses one deck pairing; see Overall."))
    by_style = ['<h2 class="panel-title">By training style</h2>']
    if view["style_tables"]:
        by_style.append(_note("The overall ratings and ranks, filtered by training-style tag."))
        by_style += [_style_section(table, overall_scale) for table in view["style_tables"]]
    else:
        by_style.append(_note("No training-style tags yet."))
    panels = (("overall", "Overall", overall), ("deck", "By deck", by_deck), ("style", "By training style", by_style))
    parts = ['<div class="leaderboards" data-tabs>', '<div class="tabs" role="tablist" aria-label="Leaderboards" hidden>']
    for index, (key, name, _) in enumerate(panels):
        selected = "true" if index == 0 else "false"
        parts.append(
            f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" '
            f'aria-selected="{selected}">{name}</button>'
        )
    parts.append("</div>")
    for key, _, content in panels:
        parts.append(f'<div class="panel" role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}">')
        parts.extend(content)
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _deck_section(table: Mapping[str, Any]) -> str:
    if table["status"] == "ok":
        content = _leader_table(table["rows"], _elo_scale(table["rows"]))
    else:
        content = f'<p class="empty">Not rated: {_e(table["reason"] or table["status"])}</p>'
    label = _e(table["label"])
    return f'<section data-panel="deck" data-deck="{label}">\n<h3>{label}</h3>\n{content}\n</section>'


def _style_section(table: Mapping[str, Any], scale: tuple[float, float]) -> str:
    tag = _e(table["tag"])
    return f'<section data-panel="style" data-tag="{tag}">\n<h3>{tag}</h3>\n{_leader_table(table["rows"], scale)}\n</section>'


def _elo_scale(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    """The axis for a leaderboard's interval bars: every rated row's Elo and interval bounds."""
    values: list[float] = []
    for row in rows:
        if row["elo_milli"] is not None:
            values.append(row["elo_milli"] / 1000)
            if row["ci_elo_milli"] is not None:
                values.extend(bound / 1000 for bound in row["ci_elo_milli"])
    return _scale(values)


def _leader_table(rows: Sequence[Mapping[str, Any]], scale: tuple[float, float]) -> str:
    """One leaderboard; every row's interval bar is drawn on ``scale``."""
    head = (
        '<thead><tr><th scope="col" class="num" aria-label="Rank">#</th><th scope="col">Bot</th>'
        '<th scope="col" class="num">Elo</th><th scope="col" class="ci-cell">95% interval</th>'
        '<th scope="col" class="num">W-D-L</th><th scope="col" class="num">Games</th>'
        '<th scope="col" class="num">Forfeits</th></tr></thead>'
    )
    return "\n".join(
        [
            '<div class="table-wrap">',
            '<table class="leaders">',
            head,
            "<tbody>",
            *(_leader_row(row, scale) for row in rows),
            "</tbody>",
            "</table>",
            "</div>",
        ]
    )


def _leader_row(row: Mapping[str, Any], scale: tuple[float, float]) -> str:
    rank = "-" if row["rank"] is None else str(row["rank"])
    hint = f' title="{_e(row["description"])}"' if row["description"] else ""
    bot = f'<span class="label"{hint}>{_link(row["url"], row["label"])}</span>'
    marks = ['<span class="chip quiet">anchor</span>'] if row["anchor"] else []
    marks += [f'<span class="chip">{_e(tag)}</span>' for tag in row["tags"]]
    if marks:
        bot += " " + " ".join(marks)
    if row["author"]:
        bot += f'<span class="by">{_e(row["author"])}</span>'
    elo = '<span class="muted">unrated</span>' if row["elo_milli"] is None else format_elo(row["elo_milli"])
    return "\n".join(
        [
            f'<tr data-bot="{_e(row["name"])}">',
            f'<td class="num rank">{rank}</td>',
            f'<td class="bot">{bot}</td>',
            f'<td class="num elo">{elo}</td>',
            f'<td class="ci-cell">{_interval_bar(row, scale)}</td>',
            f'<td class="num">{row["wins"]}-{row["draws"]}-{row["losses"]}</td>',
            f'<td class="num">{row["games"]}</td>',
            f'<td class="num">{row["forfeits"]}</td>',
            "</tr>",
        ]
    )


def _interval_bar(row: Mapping[str, Any], scale: tuple[float, float]) -> str:
    """A dot at the Elo and a line across its 95% interval; empty for an unrated row."""
    elo_milli, interval = row["elo_milli"], row["ci_elo_milli"]
    if elo_milli is None:
        return ""
    if row["anchor"] or elo_milli == _ANCHOR_ELO_MILLI:
        tone = "flat"
    else:
        tone = "up" if elo_milli > _ANCHOR_ELO_MILLI else "down"
    marks = ['<line class="track" x1="0" y1="8" x2="100%" y2="8"/>', f'<g class="{tone}">']
    if interval is not None:
        low, high = _position(interval[0] / 1000, scale), _position(interval[1] / 1000, scale)
        if high > low:
            marks.append(
                f'<line x1="{low:.1f}%" y1="8" x2="{high:.1f}%" y2="8" '
                'stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
            )
    marks.append(f'<circle cx="{_position(elo_milli / 1000, scale):.1f}%" cy="8" r="4" fill="currentColor"/></g>')
    if row["anchor"]:
        label = f"Elo {format_elo(elo_milli)}, the anchor"
    elif interval is None:
        label = f"Elo {format_elo(elo_milli)}, no interval"
    else:
        label = f"Elo {format_elo(elo_milli)}, 95% interval {format_elo(interval[0])} to {format_elo(interval[1])}"
    return f'<svg class="ci" width="100%" height="16" role="img" aria-label="{_e(label)}">{"".join(marks)}</svg>'


def _grid(grid: Mapping[str, Any]) -> str:
    """The matchup grid: each row bot's share of the points against each column bot."""
    names, labels = grid["names"], grid["labels"]
    head = "".join(f'<th scope="col">{_e(label)}</th>' for label in labels)
    body = []
    for name, label, cells in zip(names, labels, grid["cells"], strict=True):
        tds = "".join(_grid_cell(name, other, cell) for other, cell in zip(names, cells, strict=True))
        body.append(f'<tr><th scope="row">{_e(label)}</th>{tds}</tr>')
    return "\n".join(
        [
            '<section class="matchups">',
            "<h2>Matchups</h2>",
            _note("Each cell is the row bot's share of the points against the column bot."),
            '<div class="table-wrap">',
            '<table class="grid">',
            f'<thead><tr><th scope="col"><span class="sr-only">Bot</span></th>{head}</tr></thead>',
            "<tbody>",
            *body,
            "</tbody>",
            "</table>",
            "</div>",
            "</section>",
        ]
    )


def _grid_cell(row_name: str, col_name: str, cell: Mapping[str, Any] | None) -> str:
    """One matchup cell, tinted by how far its share is from even, with the game count as its title."""
    position = f'data-row="{_e(row_name)}" data-col="{_e(col_name)}"'
    if cell is None:
        return f'<td {position} class="none"></td>'
    percent = round(cell["score"] * 100)
    strength = abs(percent - 50) * _TINT_MAX // 50
    tint = ""
    if strength:
        tone = "accent" if percent > 50 else "warn"
        tint = f' style="background: color-mix(in srgb, var(--{tone}) {strength}%, transparent)"'
    return f'<td {position} title="{_count(cell["games"], "game")}"{tint}>{format_share(cell["score"])}</td>'


def _details(view: Mapping[str, Any]) -> str:
    """The run's setup with the engine identity, and how to re-check the run."""
    engine, run = view["engine"], view["run"]
    revision = engine["source_revision"]
    facts = (
        ("Format", _e(view["format"])),
        ("Decks", ", ".join(_e(deck) for deck in view["decks"])),
        ("Schedule", f"{_count(view['pairs_per_deck'], 'seat-swapped pair')} per deck in each matchup"),
        ("Engine", _e(engine["name"])),
        ("Engine version", _e(engine["version"])),
        ("Source revision", f"<code>{_e(revision)}</code>" if revision else '<span class="muted">not recorded</span>'),
        ("Rules snapshot", f"<code>{_e(engine['rules_snapshot_id'])}</code>"),
        ("Card pool", f"<code>{_e(engine['card_pool_identity'])}</code>"),
    )
    clone = _link(view["site"]["repo_url"], "Clone the repository")
    return "\n".join(
        [
            '<div class="details">',
            '<section class="setup">',
            "<h2>Setup</h2>",
            "<dl>",
            *(f"<dt>{term}</dt><dd>{value}</dd>" for term, value in facts),
            "</dl>",
            "</section>",
            '<section class="recheck">',
            "<h2>Re-check this run</h2>",
            f"<p>{clone}, then run:</p>",
            f"<pre><code>{_e(run['validate_command'])}</code></pre>",
            _note("It checks every file's hash and recomputes every rating from the ledger."),
            _note("Manifest sha256"),
            f'<p><code class="hash">{_e(run["manifest_sha256"])}</code></p>',
            "</section>",
            "</div>",
        ]
    )
