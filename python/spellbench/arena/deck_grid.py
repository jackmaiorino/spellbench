"""The deck grid: deck-vs-deck scores, deck ratings and per-bot robustness.

A leaderboard gains ``deck_grid`` when its ledger holds an off-mirror game
(two different decks), which happens on ``all_pairs`` boards. Mirror-only
ledgers, every board committed before the grid, get no section, so their
artifacts keep their bytes.

The unit is the seat-swapped pair, as for bot ratings. A pair with decks
(X on p0, Y on p1) gives each bot X once and Y once, so pilot skill cancels
from the deck comparison; the reversed pair (Y, X) puts the other deck on the
play, so a full grid also cancels the play/draw edge. Self-play pairs count:
one bot on both sides is a clean deck measurement.

- ``matrix``: for every unordered deck pairing, the earlier deck's games and
  W/D/L over every rated off-mirror game, and its score over complete pairs
  with a percentile bootstrap CI (the matchup-panel recipe). Reported for
  all games and for games between the top half of the overall table
  ("strong pilots"), since deck strength depends on who pilots.
- ``deck_ratings``: an anchored Bradley-Terry fit over the decks (one
  virtual draw per pairing, as for bots), shifted so the average deck is 0
  log units and displays at Elo 1500; the CI comes from a paired bootstrap
  whose every refit is centered the same way. Real matchups need not be
  transitive, so each cell also carries the fit's predicted score and the
  section reports the RMS gap between observed and predicted scores.
- ``robustness``: per bot (self-play excluded), rated-game W/D/L by its own
  deck and by its opponent's deck, mirrors included. Every opponent plays
  every pairing equally, so the rows of one bot compare fairly.

Seeds derive from the stats seed like the leaderboard's (SplitMix64 over a
domain constant), with a cell ordinal that runs across both reports.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from . import ratings, store

GRID_SCHEMA = "spellbench-deck-grid/v1"
VIRTUAL_DRAWS_PER_PAIRING = 1
DECK_ELO_CENTER_MILLI = 1_500_000  # the average deck displays at Elo 1500

_MASK64 = 0xFFFF_FFFF_FFFF_FFFF
_MAX_JSON_INT = (1 << 53) - 1
_GOLDEN_RATIO_64 = 0x9E37_79B9_7F4A_7C15
_CELL_DOMAIN = 0x5350_5F47_5249_445F  # "SP_GRID_"
_DECK_RATING_DOMAIN = 0x5350_5F44_4543_4B52  # "SP_DECKR"
_REPORT_STRIDE = 1 << 16  # cell ordinals of the second report start here

NOTES = [
    "off-mirror games only; the unit is the seat-swapped pair, which gives each bot both decks",
    "scores are the earlier deck's, over complete pairs; W/D/L counts every rated game",
    "strong pilots: games where both bots rank in the top half of the overall table",
    "deck ratings: anchored Bradley-Terry over decks, one virtual draw per pairing, centered so the average deck is Elo 1500",
    "predicted scores come from the deck ratings; residual_rms_e6 measures how far the matrix is from transitive",
    "robustness: rated games by own deck and by opponent deck, self-play excluded, mirrors included",
]


def deck_label(deck: dict[str, Any]) -> str:
    """A deck's display label: its v2 name, a catalog id, or a decklist digest."""
    if "deck_id" in deck:
        return deck["name"]
    if "catalog_id" in deck:
        return deck["catalog_id"]
    return "decklist " + store.sha256_hex(store.canonical_bytes(deck))[:12]


def row_decks(row: Any) -> list[dict[str, Any]]:
    """A row's (p0, p1) decks as JSON objects (v2 rows carry LedgerDeck dataclasses)."""
    return [deck.to_json() if hasattr(deck, "to_json") else deck for deck in row.decks]


def has_off_mirror(rows: Sequence[Any]) -> bool:
    """True when some game paired two different decks."""
    return any(store.canonical_bytes(decks[0]) != store.canonical_bytes(decks[1])
               for decks in (row_decks(row) for row in rows))


def _seed(base_seed: int, domain: int, ordinal: int) -> int:
    mixed = (base_seed ^ domain ^ (ordinal * _GOLDEN_RATIO_64)) & _MASK64
    return ratings.splitmix64_next(mixed) & _MAX_JSON_INT


def _winner_seat(row: Any) -> str | None:
    if row.winner is not None:
        return row.winner
    if row.winner_bot_id is None:
        return None
    return "p0" if row.bot_id_at("p0") == row.winner_bot_id else "p1"


def _rational(num: int, den: int) -> dict[str, int]:
    return {"num": num, "den": den}


def _wdl() -> dict[str, int]:
    return {"games": 0, "wins": 0, "draws": 0, "losses": 0}


def _add(record: dict[str, int], half_points: int) -> None:
    record["games"] += 1
    record[{2: "wins", 1: "draws", 0: "losses"}[half_points]] += 1


def _half_points(row: Any, seat: str) -> int:
    winner = _winner_seat(row)
    return 1 if winner is None else (2 if winner == seat else 0)


def build_deck_grid(
    rows: Sequence[Any],
    table_rows: Sequence[dict[str, Any]],
    *,
    base_seed: int,
    bootstrap_replicates: int,
) -> dict[str, Any] | None:
    """The ``deck_grid`` section for ``rows``, or None for a mirror-only ledger.

    ``table_rows`` are the overall leaderboard rows, ranked; they pick the strong pilots.
    """
    if not has_off_mirror(rows):
        return None
    ordered = sorted(rows, key=lambda row: row.game_index)
    keys: dict[bytes, str] = {}
    for row in ordered:
        for deck in row_decks(row):
            keys.setdefault(store.canonical_bytes(deck), deck_label(deck))
    labels = list(keys.values())
    document: dict[str, Any] = {"schema": GRID_SCHEMA, "decks": labels, "status": "ok", "reason": None}
    if len(set(labels)) != len(labels):
        document.update(status="skipped", reason="two different decks share a label")
        return document
    index = {key: position for position, key in enumerate(keys)}
    rated = [row for row in ordered if row.rated]

    ranked = [row for row in table_rows if row["rated"]]
    strong_count = (len(ranked) + 1) // 2
    strong = {row["bot_id"] for row in ranked[:strong_count]}
    reports = []
    for ordinal, (name, members) in enumerate((("all", None), ("strong_pilots", strong))):
        if members is not None and len(ranked) < 4:
            reports.append({"pilots": name, "status": "skipped", "reason": "fewer than four rated bots",
                            "bot_ids": [], "cells": [], "deck_ratings": None})
            continue
        subset = rated if members is None else [
            row for row in rated if row.bot_id_at("p0") in members and row.bot_id_at("p1") in members]
        reports.append(_report(name, subset, index, labels, base_seed, bootstrap_replicates,
                               ordinal * _REPORT_STRIDE, sorted(members) if members is not None else []))
    document["reports"] = reports
    document["robustness"] = _robustness(rated, index, labels, table_rows)
    document["notes"] = NOTES
    return document


def _report(
    name: str,
    rows: Sequence[Any],
    index: dict[bytes, int],
    labels: list[str],
    base_seed: int,
    bootstrap_replicates: int,
    seed_offset: int,
    bot_ids: list[str],
) -> dict[str, Any]:
    """One matrix with its deck ratings, over ``rows`` (rated games)."""
    records: dict[tuple[int, int], dict[str, int]] = {}
    pairs: dict[tuple[str, str, int], dict[int, Any]] = {}
    for row in rows:
        p0, p1 = (index[store.canonical_bytes(deck)] for deck in row_decks(row))
        if p0 == p1:
            continue
        first, second = min(p0, p1), max(p0, p1)
        seat = "p0" if p0 == first else "p1"
        _add(records.setdefault((first, second), _wdl()), _half_points(row, seat))
        bots = tuple(sorted((row.bot_id_at("p0"), row.bot_id_at("p1"))))
        pairs.setdefault((bots[0], bots[1], row.pair_index), {})[row.pair_slot] = row
    totals: dict[tuple[int, int], list[int]] = {}
    complete: dict[tuple[int, int], list[int]] = {}  # (first wins, second wins, draws) over complete pairs
    for key in sorted(pairs):
        games = pairs[key]
        if set(games) != {0, 1}:
            continue
        decks = [tuple(index[store.canonical_bytes(deck)] for deck in row_decks(games[slot])) for slot in (0, 1)]
        if decks[0] != decks[1]:
            continue  # both games of a pair share the seat decks by construction
        p0, p1 = decks[0]
        first = min(p0, p1)
        seat = "p0" if p0 == first else "p1"
        points = [_half_points(games[slot], seat) for slot in (0, 1)]
        totals.setdefault((first, max(p0, p1)), []).append(sum(points))
        record = complete.setdefault((first, max(p0, p1)), [0, 0, 0])
        for value in points:
            record[{2: 0, 0: 1, 1: 2}[value]] += 1
    cells = []
    for ordinal, cell in enumerate(sorted(records)):
        cell_totals = tuple(totals.get(cell, ()))
        entry: dict[str, Any] = {
            "deck": labels[cell[0]],
            "opponent": labels[cell[1]],
            **records[cell],
            "complete_pairs": len(cell_totals),
            "score": None,
            "score_ci95": None,
            "predicted_score_e6": None,
        }
        if cell_totals:
            entry["score"] = _rational(sum(cell_totals), 4 * len(cell_totals))
            summary = ratings.bootstrap_pair_half_points(
                cell_totals, _seed(base_seed, _CELL_DOMAIN, seed_offset + ordinal), bootstrap_replicates)
            entry["score_ci95"] = {
                "lower": _rational(summary.lower_sum, summary.denominator),
                "upper": _rational(summary.upper_sum, summary.denominator),
                "seed": summary.bootstrap_seed,
                "replicates": summary.bootstrap_replicates,
            }
        cells.append(entry)
    deck_ratings = _deck_ratings(totals, complete, labels, cells, base_seed, bootstrap_replicates, seed_offset)
    return {"pilots": name, "status": "ok" if cells else "no_rated_games", "reason": None,
            "bot_ids": bot_ids, "cells": cells, "deck_ratings": deck_ratings}


def _deck_ratings(
    totals: dict[tuple[int, int], list[int]],
    complete: dict[tuple[int, int], list[int]],
    labels: list[str],
    cells: list[dict[str, Any]],
    base_seed: int,
    bootstrap_replicates: int,
    seed_offset: int,
) -> dict[str, Any]:
    """Centered Bradley-Terry deck ratings over complete pairs, with predicted cell scores."""
    doc: dict[str, Any] = {"status": "ok", "fit_error": None, "virtual_draws_per_pairing": VIRTUAL_DRAWS_PER_PAIRING,
                           "bootstrap": None, "residual_rms_e6": None, "rows": []}
    if not totals:
        doc["status"] = "no_complete_pairs"
        return doc
    records = [ratings.PairRecord(labels[first], labels[second], wins, losses, draws + VIRTUAL_DRAWS_PER_PAIRING)
               for (first, second), (wins, losses, draws) in sorted(complete.items())]
    reference = labels[min(first for first, _ in totals)]
    try:
        fit = ratings.fit_bt_ratings(records, reference)
    except ratings.BtRatingError as exc:
        doc.update(status="fit_failed", fit_error=str(exc))
        return doc
    fitted = dict(fit.ratings_log_units)
    mean = math.fsum(fitted.values()) / len(fitted)
    centered = {deck: rating - mean for deck, rating in fitted.items()}
    intervals: dict[str, tuple[float, float]] = {}
    seed = _seed(base_seed, _DECK_RATING_DOMAIN, seed_offset)
    try:
        boot = ratings.paired_rating_bootstrap(
            [ratings.MatchupPairs(labels[first], labels[second], tuple(pair_totals))
             for (first, second), pair_totals in sorted(totals.items())],
            reference, bootstrap_seed=seed, bootstrap_replicates=bootstrap_replicates,
            virtual_draws=VIRTUAL_DRAWS_PER_PAIRING, center=True)
    except ratings.BtRatingError:
        doc["bootstrap"] = {"status": "bootstrap_failed", "replicates": bootstrap_replicates, "seed": seed,
                            "failed_replicates": bootstrap_replicates}
    else:
        intervals = {deck: (low, high) for deck, low, high in boot.intervals}
        doc["bootstrap"] = {"status": "ok", "replicates": boot.replicates, "seed": seed,
                            "failed_replicates": boot.failed_replicates}
    gaps = []
    for entry in cells:
        if entry["deck"] not in centered or entry["opponent"] not in centered:
            continue
        predicted = 1.0 / (1.0 + math.exp(centered[entry["opponent"]] - centered[entry["deck"]]))
        entry["predicted_score_e6"] = round(predicted * 1_000_000)
        if entry["score"] is not None:
            gaps.append(entry["score"]["num"] / entry["score"]["den"] - predicted)
    if gaps:
        doc["residual_rms_e6"] = round(math.sqrt(math.fsum(gap * gap for gap in gaps) / len(gaps)) * 1_000_000)
    rows = []
    for deck in labels:
        if deck not in centered:
            continue
        ci = intervals.get(deck)
        rows.append({
            "deck": deck,
            "rating_log_units_e6": ratings.rating_e6(centered[deck]),
            "elo_milli": _deck_elo_milli(centered[deck]),
            "ci95_elo_milli": None if ci is None else [_deck_elo_milli(ci[0]), _deck_elo_milli(ci[1])],
        })
    rows.sort(key=lambda row: (-row["rating_log_units_e6"], labels.index(row["deck"])))
    doc["rows"] = rows
    return doc


def _deck_elo_milli(rating: float) -> int:
    return ratings.elo_milli(rating) - ratings.elo_milli(0.0) + DECK_ELO_CENTER_MILLI


def _robustness(
    rows: Sequence[Any], index: dict[bytes, int], labels: list[str], table_rows: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per bot (self-play excluded): W/D/L by own deck and by opponent deck, in deck order."""
    by_bot: dict[str, tuple[list[dict[str, int]], list[dict[str, int]]]] = {}
    for row in rows:
        p0_id, p1_id = row.bot_id_at("p0"), row.bot_id_at("p1")
        if p0_id == p1_id:
            continue
        decks = [index[store.canonical_bytes(deck)] for deck in row_decks(row)]
        for seat, bot_id, own, opponent in (("p0", p0_id, decks[0], decks[1]), ("p1", p1_id, decks[1], decks[0])):
            own_rows, opponent_rows = by_bot.setdefault(
                bot_id, ([_wdl() for _ in labels], [_wdl() for _ in labels]))
            half_points = _half_points(row, seat)
            _add(own_rows[own], half_points)
            _add(opponent_rows[opponent], half_points)
    result = []
    for table_row in table_rows:  # overall table order: ranked bots first
        if table_row["bot_id"] not in by_bot:
            continue
        own_rows, opponent_rows = by_bot[table_row["bot_id"]]
        result.append({
            "bot_id": table_row["bot_id"],
            "name": table_row["name"],
            "by_own_deck": [{"deck": label, **record} for label, record in zip(labels, own_rows)],
            "by_opponent_deck": [{"deck": label, **record} for label, record in zip(labels, opponent_rows)],
        })
    return result


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _percent(num: int, den: int) -> str:
    return "" if den == 0 else f"{100 * num / den:.0f}"


def _milli(value: int) -> str:
    return f"{value / 1000:.1f}"


def render_markdown(grid: dict[str, Any]) -> list[str]:
    """The grid's markdown lines (a ``## Deck grid`` section)."""
    lines = ["", "## Deck grid", ""]
    if grid["status"] != "ok":
        return lines + [f"- Status: {grid['status']} ({grid['reason']})"]
    labels = grid["decks"]
    for report in grid["reports"]:
        title = "all games" if report["pilots"] == "all" else "strong pilots (top half of the table)"
        lines += [f"### Deck vs deck: {title}", ""]
        if report["status"] != "ok":
            lines += [f"- Status: {report['status']}" + (f" ({report['reason']})" if report["reason"] else ""), ""]
            continue
        lines.append("Row deck's score in percent over complete pairs (games in parentheses).")
        lines.append("")
        scores: dict[tuple[str, str], tuple[str, int]] = {}
        for cell in report["cells"]:
            score = cell["score"]
            if score is None:
                continue
            scores[(cell["deck"], cell["opponent"])] = (_percent(score["num"], score["den"]), cell["games"])
            scores[(cell["opponent"], cell["deck"])] = (_percent(score["den"] - score["num"], score["den"]),
                                                       cell["games"])
        lines.append("| Deck | " + " | ".join(labels) + " |")
        lines.append("| --- |" + " ---: |" * len(labels))
        for deck in labels:
            cells = []
            for opponent in labels:
                if deck == opponent:
                    cells.append("-")
                elif (deck, opponent) in scores:
                    value, games = scores[(deck, opponent)]
                    cells.append(f"{value} ({games})")
                else:
                    cells.append("")
            lines.append(f"| {deck} | " + " | ".join(cells) + " |")
        ratings_doc = report["deck_ratings"]
        lines.append("")
        if ratings_doc["status"] != "ok":
            lines += [f"Deck ratings: {ratings_doc['status']}" + (
                f" ({ratings_doc['fit_error']})" if ratings_doc["fit_error"] else ""), ""]
            continue
        rms = ratings_doc["residual_rms_e6"]
        lines += ["| Deck | Elo | CI95 (Elo) |", "| --- | ---: | --- |"]
        for row in ratings_doc["rows"]:
            ci = row["ci95_elo_milli"]
            lines.append(f"| {row['deck']} | {_milli(row['elo_milli'])} | "
                         + ("" if ci is None else f"[{_milli(ci[0])}, {_milli(ci[1])}]") + " |")
        lines.append("")
        if rms is not None:
            lines += [f"Transitivity: observed scores differ from the deck ratings' predictions by "
                      f"{rms / 10_000:.1f} points RMS.", ""]
    if grid["robustness"]:
        for field, title in (("by_own_deck", "own deck"), ("by_opponent_deck", "opponent's deck")):
            lines += [f"### Robustness: score by {title}", ""]
            lines.append("| Bot | " + " | ".join(labels) + " |")
            lines.append("| --- |" + " ---: |" * len(labels))
            for bot in grid["robustness"]:
                values = [_percent(2 * record["wins"] + record["draws"], 2 * record["games"]) for record in bot[field]]
                lines.append(f"| {bot['name']} | " + " | ".join(values) + " |")
            lines.append("")
    return lines
