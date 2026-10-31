"""Hero charts: one SVG per benchmark and one per track, drawn from published records only.

A benchmark chart shows every rated row of the board's leaderboard (the site's
board run: the latest rated snapshot, else the latest rated run) as Elo with
its 95% interval; a bound is drawn as an arrow from its estimate. References
(panel members or ladder rungs) are squares, other entrants circles. The
builtin ``heuristic`` bot's rating is a dashed reference line, or the chart
says it is not on the board. The anchor sits at 1000.

Human games come from ``benchmarks/<id>/human/<session>/`` (a ledger and a
``SESSION.json``). They never enter the rating fit. On the chart each opponent
row carries the human's natural-game record against it, with timeout forfeits
and other endings counted beside it, not scored. From ``HUMAN_ESTIMATE_GAMES``
natural games on, a descriptive human row shows a one-parameter fit against
the bots' ratings held fixed, with a likelihood interval, or a one-sided bound
when every natural game is a win or every one a loss.

A track chart (``benchmarks/tracks.json``) applies the Hero method
(:mod:`spellbench.site.hero`) to the track's boards: a descriptive average of
Elo above random over the boards each bot entered, with its coverage.

Unrated runs appear only through :func:`preview_chart`, labelled as previews;
they never enter a track chart or the site.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..arena import store
from ..wire import strict_json_loads
from . import hero

TRACKS_FILE = "tracks.json"
TRACKS_SCHEMA = "spellbench-tracks/v1"
HUMAN_DIR = "human"
SESSION_FILE = "SESSION.json"
SESSION_SCHEMA = "spellbench-human-session/v1"
HUMAN_ESTIMATE_GAMES = 10
HEURISTIC = "heuristic"
ANCHOR_ELO = 1000.0
_LOG_TO_ELO = 400 / math.log(10)
_CHI2_95 = 3.841458820694124  # 1 degree of freedom

_WIDTH = 760
_LABEL_W = 230
_RIGHT_W = 150
_ROW_H = 26
_TOP = 86
_STYLE = """
.viz{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;--grid:#e6e5e0;
--entrant:#2a78d6;--reference:#eb6834;--human:#1baf7a}
@media (prefers-color-scheme:dark){.viz{--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e88;
--grid:#33332f;--entrant:#3987e5;--reference:#d95926;--human:#199e70}}
.bg{fill:var(--surface)} text{font-family:system-ui,-apple-system,Segoe UI,sans-serif;fill:var(--ink)}
.t{font-size:15px;font-weight:600} .s,.tick,.note{font-size:11px;fill:var(--ink2)} .lab{font-size:12px}
.grid{stroke:var(--grid);stroke-width:1} .ref{stroke:var(--muted);stroke-width:1.5;stroke-dasharray:5 4}
.anchor{stroke:var(--muted);stroke-width:1}
.ci{stroke-width:2;stroke-linecap:round} .entrant{fill:var(--entrant);stroke:var(--entrant)}
.reference{fill:var(--reference);stroke:var(--reference)} .human{fill:var(--human);stroke:var(--human)}
.ring{stroke:var(--surface);stroke-width:2} .chip{fill:none;stroke:var(--ink2);stroke-width:1.5}
"""


class ChartError(ValueError):
    """A tracks file or human session record is malformed."""


@dataclass(frozen=True)
class HumanRecord:
    """One human's games against one bot, over the sessions filed under a board."""

    human: str
    opponent: str
    wins: int
    draws: int
    losses: int
    other: dict[str, int]  # endings that are not natural results, by classification
    sessions: tuple[str, ...]


@dataclass(frozen=True)
class HumanSession:
    name: str
    human: str
    conditions: str
    rows: tuple[Mapping[str, Any], ...]


# ---------------- records ----------------

def load_tracks(benchmarks_dir: Path) -> list[dict[str, Any]]:
    """The tracks in ``benchmarks/tracks.json``, or none when the file is absent."""
    path = benchmarks_dir / TRACKS_FILE
    if not path.is_file():
        return []
    data = strict_json_loads(path.read_bytes())
    if not isinstance(data, dict) or data.get("schema") != TRACKS_SCHEMA or not isinstance(data.get("tracks"), list):
        raise ChartError(f"{path}: must be {{schema: {TRACKS_SCHEMA}, tracks: [...]}}")
    tracks = []
    for track in data["tracks"]:
        if (not isinstance(track, dict) or set(track) != {"id", "title", "benchmarks"}
                or not all(isinstance(track[key], str) and track[key] for key in ("id", "title"))
                or not isinstance(track["benchmarks"], list) or not track["benchmarks"]
                or any(not isinstance(item, str) for item in track["benchmarks"])):
            raise ChartError(f"{path}: every track needs id, title and a nonempty benchmarks list")
        tracks.append(track)
    if len({track["id"] for track in tracks}) != len(tracks):
        raise ChartError(f"{path}: track ids must be distinct")
    return tracks


def load_human_sessions(benchmark_dir: Path) -> list[HumanSession]:
    """Every human session filed under a board, oldest name first."""
    folder = benchmark_dir / HUMAN_DIR
    if not folder.is_dir():
        return []
    sessions = []
    for path in sorted(child for child in folder.iterdir() if child.is_dir()):
        info = strict_json_loads((path / SESSION_FILE).read_bytes())
        if not isinstance(info, dict) or info.get("schema") != SESSION_SCHEMA or not isinstance(info.get("human"), str) or not isinstance(
                info.get("conditions"), str):
            raise ChartError(f"{path / SESSION_FILE}: needs schema {SESSION_SCHEMA}, human and conditions")
        rows = tuple(store.read_jsonl(path / store.LEDGER_NAME))
        if any(info["human"] not in {seat["name"] for seat in row["seats"]} for row in rows):
            raise ChartError(f"{path}: every game must seat {info['human']!r}")
        sessions.append(HumanSession(path.name, info["human"], info["conditions"], rows))
    return sessions


def human_records(sessions: Sequence[HumanSession]) -> list[HumanRecord]:
    """Each human's record against each bot: natural wins, draws and losses, other endings counted apart."""
    tallies: dict[tuple[str, str], dict[str, Any]] = {}
    for session in sessions:
        for row in session.rows:
            seats = {seat["seat"]: seat["name"] for seat in row["seats"]}
            mine = next(seat for seat, name in seats.items() if name == session.human)
            opponent = next(name for seat, name in seats.items() if seat != mine)
            tally = tallies.setdefault((session.human, opponent),
                                       {"wins": 0, "draws": 0, "losses": 0, "other": {}, "sessions": set()})
            tally["sessions"].add(session.name)
            if row["classification"] != "natural":
                tally["other"][row["classification"]] = tally["other"].get(row["classification"], 0) + 1
            elif row["winner"] is None:
                tally["draws"] += 1
            elif row["winner"] == mine:
                tally["wins"] += 1
            else:
                tally["losses"] += 1
    return [HumanRecord(human, opponent, t["wins"], t["draws"], t["losses"], dict(sorted(t["other"].items())),
                        tuple(sorted(t["sessions"])))
            for (human, opponent), t in sorted(tallies.items())]


def human_estimate(games: Sequence[tuple[float, float]]) -> tuple[float | None, float | None, float | None, str | None]:
    """Fit one Elo against opponents whose Elo is held fixed: ``games`` are (opponent Elo, score 0, 0.5 or 1).

    Returns (estimate, lower, upper, bound). The interval is the likelihood
    ratio interval at 95%. With every score 1 (or 0) there is no finite
    estimate: the result is a lower (upper) bound alone.
    """
    def loglik(elo: float) -> float:
        total = 0.0
        for opponent, score in games:
            d = (elo - opponent) / _LOG_TO_ELO
            total += score * -math.log1p(math.exp(-d)) + (1 - score) * -math.log1p(math.exp(d))
        return total

    def solve(target: float, low: float, high: float, rising: bool) -> float:
        for _ in range(200):
            mid = (low + high) / 2
            if (loglik(mid) < target) == rising:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    total = sum(score for _, score in games)
    span = (min(o for o, _ in games) - 4000, max(o for o, _ in games) + 4000)
    if total == len(games):
        return None, solve(-_CHI2_95 / 2, *span, rising=True), None, "lower"
    if total == 0:
        return None, None, solve(-_CHI2_95 / 2, *span, rising=False), "upper"
    low, high = span
    for _ in range(200):  # the log-likelihood is concave: bisect its slope
        mid = (low + high) / 2
        if loglik(mid + 1e-6) > loglik(mid - 1e-6):
            low = mid
        else:
            high = mid
    best = (low + high) / 2
    target = loglik(best) - _CHI2_95 / 2
    return best, solve(target, span[0], best, rising=True), solve(target, best, span[1], rising=False), None


# ---------------- drawing ----------------

def _num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _scale(values: Sequence[float]) -> tuple[float, float, float]:
    low, high = min(values), max(values)
    step = 100.0 if high - low <= 900 else 200.0
    low = math.floor((low - 20) / step) * step
    high = math.ceil((high + 20) / step) * step
    return low, high, step


def _svg(title: str, subtitle: str, height: int, body: list[str]) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {_WIDTH} {height}" width="{_WIDTH}" '
        f'height="{height}" role="img" aria-label="{escape(title)}">',
        f"<style>{_STYLE}</style>",
        f'<rect class="bg" width="{_WIDTH}" height="{height}"/>',
        f'<text class="t" x="16" y="26">{escape(title)}</text>',
        f'<text class="s" x="16" y="44">{escape(subtitle)}</text>',
        *body, "</svg>", ""])


def _axis(low: float, high: float, step: float, x: Any, top: int, bottom: int, label: str) -> list[str]:
    out = []
    value = low
    while value <= high + 1e-9:
        px = x(value)
        out.append(f'<line class="grid" x1="{_num(px)}" y1="{top}" x2="{_num(px)}" y2="{bottom}"/>')
        out.append(f'<text class="tick" x="{_num(px)}" y="{bottom + 14}" text-anchor="middle">{_num(value)}</text>')
        value += step
    out.append(f'<text class="tick" x="{_num((x(low) + x(high)) / 2)}" y="{bottom + 30}" '
               f'text-anchor="middle">{escape(label)}</text>')
    return out


def _mark(kind: str, cx: float, cy: float) -> str:
    if kind == "reference":
        return f'<rect class="reference ring" x="{_num(cx - 5)}" y="{_num(cy - 5)}" width="10" height="10" rx="2"/>'
    if kind == "human":
        return (f'<path class="human ring" d="M{_num(cx)} {_num(cy - 6)} L{_num(cx + 6)} {_num(cy)} '
                f'L{_num(cx)} {_num(cy + 6)} L{_num(cx - 6)} {_num(cy)} Z"/>')
    return f'<circle class="{kind} ring" cx="{_num(cx)}" cy="{_num(cy)}" r="5"/>'


def _interval(kind: str, x: Any, y: float, lower: float | None, upper: float | None, value: float | None,
              bound: str | None, low: float, high: float) -> list[str]:
    out = []
    if bound == "lower":
        start = x(lower if value is None else value)
        out.append(f'<line class="ci {kind}" x1="{_num(start)}" y1="{_num(y)}" x2="{_num(x(high))}" y2="{_num(y)}"/>')
        out.append(f'<path class="{kind}" d="M{_num(x(high))} {_num(y)} l-7 -4 v8 Z"/>')
    elif bound == "upper":
        end = x(upper if value is None else value)
        out.append(f'<line class="ci {kind}" x1="{_num(x(low))}" y1="{_num(y)}" x2="{_num(end)}" y2="{_num(y)}"/>')
        out.append(f'<path class="{kind}" d="M{_num(x(low))} {_num(y)} l7 -4 v8 Z"/>')
    elif lower is not None and upper is not None:
        out.append(f'<line class="ci {kind}" x1="{_num(x(lower))}" y1="{_num(y)}" x2="{_num(x(upper))}" '
                   f'y2="{_num(y)}"/>')
    return out


def _legend(y: int, items: Sequence[tuple[str, str]]) -> list[str]:
    out, cx = [], 16.0
    for kind, label in items:
        if kind == "line":
            out.append(f'<line class="ref" x1="{_num(cx)}" y1="{y}" x2="{_num(cx + 18)}" y2="{y}"/>')
            cx += 24
        else:
            out.append(_mark(kind, cx + 5, y))
            cx += 16
        out.append(f'<text class="note" x="{_num(cx)}" y="{y + 4}">{escape(label)}</text>')
        cx += 7 * len(label) + 18
    return out


def _record_text(record: HumanRecord) -> str:
    text = f"{record.human} {record.wins}-{record.losses}" + (f"-{record.draws}" if record.draws else "")
    others = ", ".join(f"{count} {kind}" for kind, count in record.other.items())
    return text + (f" (+{others})" if others else "")


def benchmark_chart(benchmark_id: str, title: str, board: Mapping[str, Any], *, label: str,
                    references: Sequence[str] = (), sessions: Sequence[HumanSession] = (),
                    preview: bool = False) -> str:
    """One board: every rated row's Elo and 95% interval, the heuristic line and the human records."""
    rows = [row for row in board["rows"] if row["rated"]]
    elo = {row["name"]: row["elo_milli"] / 1000 for row in rows}
    records = [record for record in human_records(sessions) if record.opponent in elo]
    estimates = []
    for human in sorted({record.human for record in records}):
        games = []
        for session in sessions:
            for row in session.rows:
                if session.human != human or row["classification"] != "natural":
                    continue
                seats = {seat["seat"]: seat["name"] for seat in row["seats"]}
                mine = next(seat for seat, name in seats.items() if name == human)
                opponent = next(name for seat, name in seats.items() if seat != mine)
                if opponent in elo:
                    score = 0.5 if row["winner"] is None else float(row["winner"] == mine)
                    games.append((elo[opponent], score))
        if len(games) >= HUMAN_ESTIMATE_GAMES:
            estimates.append((human, len(games), *human_estimate(games)))
    ordered = sorted(rows, key=lambda row: (-row["elo_milli"], row["name"]))
    lines = len(ordered) + len(estimates)
    values = [ANCHOR_ELO]
    for row in ordered:
        values.append(row["elo_milli"] / 1000)
        if row["ci95_elo_milli"] is not None:
            values.extend(bound / 1000 for bound in row["ci95_elo_milli"])
    for _, _, value, lower, upper, _ in estimates:
        values.extend(v for v in (value, lower, upper) if v is not None)
    low, high, step = _scale(values)
    plot_left, plot_right = _LABEL_W, _WIDTH - _RIGHT_W

    def x(value: float) -> float:
        return plot_left + (min(max(value, low), high) - low) / (high - low) * (plot_right - plot_left)

    top, bottom = _TOP, _TOP + lines * _ROW_H
    body = _axis(low, high, step, x, top - 6, bottom, "Elo (random = 1000), 95% intervals")
    body.append(f'<line class="anchor" x1="{_num(x(ANCHOR_ELO))}" y1="{top - 6}" x2="{_num(x(ANCHOR_ELO))}" '
                f'y2="{bottom}"/>')
    heuristic = next((row for row in rows if row["name"] == HEURISTIC), None)
    if heuristic is not None:
        hx = x(heuristic["elo_milli"] / 1000)
        body.append(f'<line class="ref" x1="{_num(hx)}" y1="{top - 6}" x2="{_num(hx)}" y2="{bottom}"/>')
    by_opponent = {record.opponent: [r for r in records if r.opponent == record.opponent] for record in records}
    for index, row in enumerate(ordered):
        y = top + index * _ROW_H + _ROW_H / 2
        kind = "reference" if row["name"] in references else "entrant"
        value = row["elo_milli"] / 1000
        interval = row["ci95_elo_milli"]
        bound = hero.rating_bound(row) if row["name"] != board["anchor"]["name"] else None
        detail = (f"{_num(value)} [{_num(interval[0] / 1000)}, {_num(interval[1] / 1000)}]"
                  if interval is not None and bound is None else
                  (f"{'>' if bound == 'lower' else '<'} {_num(value)} (bound)" if bound else _num(value)))
        name = row["name"] + (" (reference)" if kind == "reference" else "")
        body.append(f'<g><title>{escape(row["name"])}: {escape(detail)}, {row["games"]} games</title>')
        body.append(f'<text class="lab" x="{plot_left - 10}" y="{_num(y + 4)}" text-anchor="end">'
                    f'{escape(name)}</text>')
        if interval is not None and bound is None:
            body.extend(_interval(kind, x, y, interval[0] / 1000, interval[1] / 1000, value, None, low, high))
        elif bound is not None:
            body.extend(_interval(kind, x, y, None, None, value, bound, low, high))
        body.append(_mark(kind, x(value), y))
        body.append(f'<text class="note" x="{plot_right + 10}" y="{_num(y + 4)}">{escape(detail)}</text>')
        body.append("</g>")
        for offset, record in enumerate(by_opponent.get(row["name"], ())):
            hx = x(value) + 14 + 12 * offset
            body.append(f'<g><title>{escape(_record_text(record))} against {escape(row["name"])}</title>'
                        f'{_mark("human", hx, y)}</g>')
            body.append(f'<text class="note" x="{_num(hx + 9)}" y="{_num(y - 8)}">'
                        f'{escape(_record_text(record))}</text>')
    for offset, (human, count, value, lower, upper, bound) in enumerate(estimates):
        y = top + (len(ordered) + offset) * _ROW_H + _ROW_H / 2
        body.append(f'<text class="lab" x="{plot_left - 10}" y="{_num(y + 4)}" text-anchor="end">'
                    f'{escape(human)} (human, descriptive)</text>')
        body.extend(_interval("human", x, y, lower, upper, value, bound, low, high))
        mark = value if value is not None else (lower if bound == "lower" else upper)
        body.append(_mark("human", x(mark), y))
        text = (f"{_num(value)} [{_num(lower)}, {_num(upper)}]" if bound is None else
                f"{'>' if bound == 'lower' else '<'} {_num(mark)} (bound)")
        body.append(f'<text class="note" x="{plot_right + 10}" y="{_num(y + 4)}">{escape(text)}, {count} games</text>')
    notes = []
    if heuristic is None:
        notes.append("heuristic is not on this board: no reference line")
    for session in sessions:
        notes.append(f"human session {session.name}: {session.conditions}")
    if estimates:
        notes.append("human estimate: natural games only, bot ratings held fixed; it does not cover their "
                     "uncertainty or when sessions stopped")
    if board.get("evaluation"):
        notes.append(board["evaluation"]["caveat"].split(":")[0])
    legend_y = bottom + 50
    legend = [("entrant", "entrant"), ("reference", "reference (panel or rung)")]
    if heuristic is not None:
        legend.append(("line", "heuristic"))
    if records:
        legend.append(("human", "human games (natural W-L)"))
    body.extend(_legend(legend_y, legend))
    for index, note in enumerate(notes):
        body.append(f'<text class="note" x="16" y="{legend_y + 22 + 15 * index}">{escape(note)}</text>')
    subtitle = f"{benchmark_id} · {label}" + (" · UNRATED PREVIEW, not a published rating" if preview else "")
    return _svg(title, subtitle, legend_y + 30 + 15 * len(notes), body)


def track_chart(track: Mapping[str, Any], boards: Sequence[tuple[str, Mapping[str, Any]]],
                sessions: Sequence[HumanSession] = ()) -> tuple[str, tuple[str, ...]]:
    """One track: the Hero method over its rated boards. Returns the SVG and the Hero warnings."""
    table = hero.hero_table(boards)
    included = table.benchmark_ids
    rows = [row for row in table.rows]
    values = [0.0]
    for row in rows:
        values.append(row.score)
        values.extend(v for v in (row.lower, row.upper) if v is not None)
        values.extend(chip.margin for chip in row.chips)
    low, high, step = _scale(values)
    plot_left, plot_right = _LABEL_W, _WIDTH - _RIGHT_W

    def x(value: float) -> float:
        return plot_left + (min(max(value, low), high) - low) / (high - low) * (plot_right - plot_left)

    top, bottom = _TOP, _TOP + max(1, len(rows)) * _ROW_H
    body = _axis(low, high, step, x, top - 6, bottom, "Elo above random, mean over the boards each bot entered")
    body.append(f'<line class="anchor" x1="{_num(x(0))}" y1="{top - 6}" x2="{_num(x(0))}" y2="{bottom}"/>')
    heuristic = next((row for row in rows if row.name == HEURISTIC), None)
    if heuristic is not None:
        body.append(f'<line class="ref" x1="{_num(x(heuristic.score))}" y1="{top - 6}" '
                    f'x2="{_num(x(heuristic.score))}" y2="{bottom}"/>')
    records = human_records(sessions)
    for index, row in enumerate(rows):
        y = top + index * _ROW_H + _ROW_H / 2
        coverage = f"{len(row.chips)}/{len(included)} boards"
        detail = (f"{'>' if row.bound == 'lower' else '<'} {_num(row.score)} (bound)" if row.bound else
                  f"{_num(row.score)}" + (f" [{_num(row.lower)}, {_num(row.upper)}]" if row.lower is not None else ""))
        if row.approximate and row.bound is None:
            detail += " approx."
        body.append(f'<g><title>{escape(row.name)}: {escape(detail)}, {coverage}: '
                    + escape(", ".join(f"{c.benchmark_id} {_num(c.margin)}" for c in row.chips)) + "</title>")
        body.append(f'<text class="lab" x="{plot_left - 10}" y="{_num(y + 4)}" text-anchor="end">'
                    f'{escape(row.name)}</text>')
        if not row.reference:
            body.extend(_interval("entrant", x, y, row.lower, row.upper, row.score, row.bound, low, high))
        for chip in row.chips:
            body.append(f'<line class="chip" x1="{_num(x(chip.margin))}" y1="{_num(y - 6)}" '
                        f'x2="{_num(x(chip.margin))}" y2="{_num(y + 6)}"/>')
        body.append(_mark("reference" if row.reference else "entrant", x(row.score), y))
        body.append(f'<text class="note" x="{plot_right + 10}" y="{_num(y + 4)}">{escape(detail)}, '
                    f'{coverage}</text>')
        body.append("</g>")
        for offset, record in enumerate(r for r in records if r.opponent == row.name):
            hx = x(row.score) + 14 + 12 * offset
            body.append(f'<g><title>{escape(_record_text(record))} against {escape(row.name)}</title>'
                        f'{_mark("human", hx, y)}</g>')
            body.append(f'<text class="note" x="{_num(hx + 9)}" y="{_num(y - 8)}">'
                        f'{escape(_record_text(record))}</text>')
    legend_y = bottom + 50
    legend = [("entrant", "mean over entered boards"), ("reference", "anchor")]
    if heuristic is not None:
        legend.append(("line", "heuristic"))
    if records:
        legend.append(("human", "human games (natural W-L)"))
    body.extend(_legend(legend_y, legend))
    notes = [
        "ticks: each board's own value; the mean covers only the boards a bot entered (coverage shown)",
        "descriptive, not a common strength rating: boards differ in conditions and in who entered them",
        "combined intervals are approximate (per-board standard errors, independence assumed)",
        *table.warnings,
    ]
    for index, note in enumerate(notes):
        body.append(f'<text class="note" x="16" y="{legend_y + 22 + 15 * index}">{escape(note)}</text>')
    subtitle = f"track {track['id']} · rated boards: {', '.join(included) or 'none yet'}"
    return _svg(track["title"], subtitle, legend_y + 30 + 15 * len(notes), body), table.warnings


def preview_chart(run_dir: Path, *, title: str | None = None) -> str:
    """An explicitly requested chart of one run or snapshot, labelled unrated when it is not rated."""
    from ..arena.config import TournamentConfig
    manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    board = store.read_json(run_dir / store.LEADERBOARD_JSON_NAME)
    config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
    benchmark_id = manifest["run"]["benchmark_id"]
    benchmark_dir = run_dir.parent.parent
    return benchmark_chart(benchmark_id, title or benchmark_id, board, label=f"{run_dir.parent.name}/{run_dir.name}",
                           references=config.opponent_panel, sessions=load_human_sessions(benchmark_dir),
                           preview=manifest["run"]["rated"] is not True)


def site_charts(benchmarks_dir: Path, boards: Mapping[str, tuple[str, str, Mapping[str, Any], Sequence[str]]]
                ) -> tuple[dict[str, bytes], list[str]]:
    """Charts for the site: ``boards`` maps a benchmark id to (title, run label, leaderboard, references).

    Returns ``charts/<id>.svg`` and ``charts/track-<id>.svg`` files and the warnings.
    """
    files: dict[str, bytes] = {}
    warnings: list[str] = []
    sessions = {bench_id: load_human_sessions(benchmarks_dir / bench_id) for bench_id in boards}
    for bench_id, (title, label, board, references) in sorted(boards.items()):
        files[f"charts/{bench_id}.svg"] = benchmark_chart(
            bench_id, title, board, label=label, references=references, sessions=sessions[bench_id]).encode("utf-8")
    for track in load_tracks(benchmarks_dir):
        unknown = [bench_id for bench_id in track["benchmarks"] if not (benchmarks_dir / bench_id).is_dir()]
        if unknown:
            raise ChartError(f"track {track['id']}: no benchmark {', '.join(unknown)}")
        rated = [(bench_id, boards[bench_id][2]) for bench_id in track["benchmarks"] if bench_id in boards]
        track_sessions = [s for bench_id in track["benchmarks"] if bench_id in boards for s in sessions[bench_id]]
        svg, track_warnings = track_chart(track, rated, track_sessions)
        files[f"charts/track-{track['id']}.svg"] = svg.encode("utf-8")
        warnings.extend(f"track {track['id']}: {warning}" for warning in track_warnings)
    return files, warnings


def write_session(source_run: Path, target: Path, *, human: str, conditions: str, note: str) -> None:
    """File a human session's ledger under a board: ``target`` is ``benchmarks/<id>/human/<session>``."""
    target.mkdir(parents=True, exist_ok=False)
    store.write_bytes_atomic(target / store.LEDGER_NAME, (source_run / store.LEDGER_NAME).read_bytes())
    store.write_bytes_atomic(target / SESSION_FILE, (json.dumps(
        {"schema": SESSION_SCHEMA, "human": human, "conditions": conditions, "note": note},
        ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
