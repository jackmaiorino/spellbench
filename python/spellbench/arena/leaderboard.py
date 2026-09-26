"""Leaderboard artifacts: ``leaderboard.json`` + ``LEADERBOARD.md`` per format.

Inputs are the parsed match ledger, the bot registry, and the run parameters
(anchor, base seed, bootstrap replicate count). The build is a pure,
deterministic function of those inputs, so ``validate`` can recompute it
byte-identically from a tournament directory.

Conventions (declared in the artifact's ``notes``):

- ``natural`` rows (spec section 7.5) and ``forfeit`` rows are rated; a
  forfeit is a loss for the seat that forfeited. Truncated and halted rows
  are recorded in the ledger and excluded.
- Games/W/D/L count seat-games: a non-mirror game is one seat-game per bot;
  a mirror game is two seat-games for the same bot (one per seat), so a
  decisive mirror adds one win AND one loss.
- The Bradley-Terry fit excludes mirror matchups: a bot cannot inform its
  own rating. Mirror matchups carry no score CI or sign test either.
- Prior: every rated matchup gets ``VIRTUAL_DRAWS_PER_MATCHUP`` virtual
  drawn games in the fit (and in every bootstrap refit). Without it an
  unbeaten or winless record has no finite maximum-likelihood rating and a
  single lopsided bot would blank the whole leaderboard. W/D/L columns and
  matchup counts report real games only.
- The paired bootstrap resamples seat-swapped pairs (the CRN unit) within
  each matchup; the sign test runs over per-pair half-point totals.
- Subratings per training-style tag are a filtered recomputation over the
  same ledger: only rated games where BOTH seats carry the tag.

Statistics seeds (``spellbench-arena-stats-seed-v1``) derive from the
tournament base seed via one SplitMix64 draw (SplitMix64 as ported in
``ratings.py`` from mtg-kernel ``evaluation_stats.py``), masked into the
protocol integer range (|x| <= 2^53)::

    rating_bootstrap_seed = SM64(base_seed ^ 0x5350_5f42_4f54_5354) & (2**53 - 1)
    matchup_stat_seed(k)  = SM64(base_seed ^ 0x5350_5f4d_4154_4348 ^ k * 0x9e3779b97f4a7c15) & (2**53 - 1)

where ``k`` is the matchup's ordinal in sorted ``(a_bot_id, b_bot_id)`` order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from . import ratings, registry, store

_MASK64 = 0xFFFF_FFFF_FFFF_FFFF
_GOLDEN_RATIO_64 = 0x9E37_79B9_7F4A_7C15  # SplitMix64 increment (see ratings.py)
_RATING_BOOTSTRAP_DOMAIN = 0x5350_5F42_4F54_5354
_MATCHUP_STAT_DOMAIN = 0x5350_5F4D_4154_4348
_STATS_SEED_VERSION = "spellbench-arena-stats-seed-v1"
_BT_ALGORITHM = (
    "anchored Bradley-Terry MM (draws count half; anchor fixed at 0.0 log units); "
    "ported from mtg-kernel scripts/experiments/population_v2_cycle4_v1/bt_rating_v1.py"
)
VIRTUAL_DRAWS_PER_MATCHUP = 1

NOTES = [
    "natural results and forfeits are rated (a forfeit is a loss for the forfeiting bot); truncated and halted games are excluded",
    "games/W/D/L count seat-games: a mirror game is two seat-games for the same bot",
    "the Bradley-Terry fit excludes mirror matchups",
    "prior: each rated matchup adds one virtual drawn game to the fit and every bootstrap refit",
    "the paired bootstrap resamples seat-swapped pairs (the CRN unit) within each matchup",
    "subratings per training-style tag are a filtered recomputation over the same ledger",
    "Elo display = rating * 400 / ln(10) + 1000; the anchor displays at exactly 1000",
    "fixed-point integers: rating_log_units_e6 = rating * 1e6, elo_milli = Elo * 1e3",
]


_MAX_JSON_INT = (1 << 53) - 1  # artifact integers stay inside the protocol range


def rating_bootstrap_seed(base_seed: int) -> int:
    return ratings.splitmix64_next((base_seed ^ _RATING_BOOTSTRAP_DOMAIN) & _MASK64) & _MAX_JSON_INT


def matchup_stat_seed(base_seed: int, matchup_ordinal: int) -> int:
    mixed = (base_seed ^ _MATCHUP_STAT_DOMAIN ^ (matchup_ordinal * _GOLDEN_RATIO_64)) & _MASK64
    return ratings.splitmix64_next(mixed) & _MAX_JSON_INT


@dataclass
class _Wdl:
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0


@dataclass
class _Matchup:
    a_id: str
    b_id: str
    games: int = 0
    a_wins: int = 0
    draws: int = 0
    b_wins: int = 0
    # pair_index -> {game_index: row}; rated rows only
    pairs: dict[int, dict[int, store.LedgerRow]] = field(default_factory=dict)

    @property
    def mirror(self) -> bool:
        return self.a_id == self.b_id

    def complete_pair_totals(self) -> tuple[int, ...]:
        """Per-pair half-point totals for `a`, over pairs with both games rated.

        A mirror pair is a wash by construction (the bot holds both seats and
        earns one of the two half-points of every game), so its total is
        always 2 of the pair's 4 half-points.
        """
        totals: list[int] = []
        for pair_index in sorted(self.pairs):
            games = self.pairs[pair_index]
            if set(games) != {0, 1}:
                continue
            if self.mirror:
                totals.append(2)
                continue
            total = 0
            for game_index in (0, 1):
                row = games[game_index]
                if row.winner_bot_id is None:
                    total += 1  # draw: one half-point per game per side
                elif row.winner_bot_id == self.a_id:
                    total += 2
            totals.append(total)
        return tuple(totals)

    def incomplete_pairs(self) -> int:
        return sum(1 for games in self.pairs.values() if set(games) != {0, 1})


def _accumulate(
    rows: Sequence[store.LedgerRow],
) -> tuple[dict[str, _Wdl], dict[str, int], dict[tuple[str, str], _Matchup]]:
    """Per-bot seat-game W/D/L, per-bot forfeit losses, and the matchup panel."""
    wdl: dict[str, _Wdl] = {}
    forfeit_losses: dict[str, int] = {}
    matchups: dict[tuple[str, str], _Matchup] = {}
    for row in rows:
        p0_id = row.bot_id_at("p0")
        p1_id = row.bot_id_at("p1")
        if row.classification == "forfeit":
            assert row.adjudication is not None and row.adjudication.loser_seat is not None
            loser = row.bot_id_at(row.adjudication.loser_seat)
            forfeit_losses[loser] = forfeit_losses.get(loser, 0) + 1
        if not row.rated:
            continue
        mirror = p0_id == p1_id
        for bot_id in {p0_id, p1_id}:
            wdl.setdefault(bot_id, _Wdl())
        if mirror:
            wdl[p0_id].games += 2
            if row.winner_bot_id is None:
                wdl[p0_id].draws += 2
            else:
                wdl[p0_id].wins += 1
                wdl[p0_id].losses += 1
        else:
            wdl[p0_id].games += 1
            wdl[p1_id].games += 1
            if row.winner_bot_id is None:
                wdl[p0_id].draws += 1
                wdl[p1_id].draws += 1
            else:
                loser_id = p1_id if row.winner_bot_id == p0_id else p0_id
                wdl[row.winner_bot_id].wins += 1
                wdl[loser_id].losses += 1
        a_id, b_id = (p0_id, p1_id) if p0_id <= p1_id else (p1_id, p0_id)
        matchup = matchups.setdefault((a_id, b_id), _Matchup(a_id=a_id, b_id=b_id))
        matchup.games += 1
        if mirror:
            if row.winner_bot_id is None:
                matchup.draws += 1
            else:
                matchup.a_wins += 1
                matchup.b_wins += 1
        elif row.winner_bot_id is None:
            matchup.draws += 1
        elif row.winner_bot_id == a_id:
            matchup.a_wins += 1
        else:
            matchup.b_wins += 1
        matchup.pairs.setdefault(row.pair_index, {})[row.game_index] = row
    return wdl, forfeit_losses, matchups


def _rational(num: int, den: int) -> dict[str, int]:
    return {"num": num, "den": den}


def _prior_pair_records(matchups: Sequence[_Matchup]) -> list[ratings.PairRecord]:
    """Fit inputs for the rated (non-mirror) matchups, prior draws included."""
    return [
        ratings.PairRecord(
            a_id=matchup.a_id,
            b_id=matchup.b_id,
            a_wins=matchup.a_wins,
            b_wins=matchup.b_wins,
            draws=matchup.draws + VIRTUAL_DRAWS_PER_MATCHUP,
        )
        for matchup in matchups
        if not matchup.mirror and matchup.games > 0
    ]


def _fit_or_none(
    pair_records: list[ratings.PairRecord], anchor_bot_id: str
) -> tuple[ratings.BtFit | None, str | None]:
    try:
        return ratings.fit_bt_ratings(pair_records, anchor_bot_id), None
    except ratings.BtRatingError as exc:
        return None, str(exc)


def build_leaderboard(
    rows: Sequence[store.LedgerRow],
    entries: Sequence[registry.RegistryEntry],
    *,
    anchor_bot_id: str,
    base_seed: int,
    bootstrap_replicates: int,
    format: str,
) -> tuple[dict[str, Any], str]:
    """Build the leaderboard JSON document and the markdown rendering."""
    by_id = {entry.bot_id: entry for entry in entries}
    if anchor_bot_id not in by_id:
        raise ValueError(f"anchor bot_id is not in the registry: {anchor_bot_id!r}")
    counts = {"total": len(rows), "rated": 0, "truncated": 0, "halted": 0, "forfeit": 0}
    for row in rows:
        if row.rated:
            counts["rated"] += 1
        if row.classification != "natural":
            counts[row.classification] += 1

    wdl, forfeit_losses, matchups = _accumulate(rows)
    ordered_matchups = [matchups[key] for key in sorted(matchups)]

    # ---------------- matchup panel (paired stats) ----------------
    matchup_entries: list[dict[str, Any]] = []
    matchup_pairs_for_bootstrap: list[ratings.MatchupPairs] = []
    for ordinal, matchup in enumerate(ordered_matchups):
        totals = matchup.complete_pair_totals()
        if matchup.mirror:
            a_half, a_half_den = 1, 2  # a mirror seat-game is always a wash
        else:
            a_half, a_half_den = 2 * matchup.a_wins + matchup.draws, 2 * matchup.games
        entry: dict[str, Any] = {
            "a_bot_id": matchup.a_id,
            "b_bot_id": matchup.b_id,
            "a_name": by_id[matchup.a_id].name if matchup.a_id in by_id else matchup.a_id,
            "b_name": by_id[matchup.b_id].name if matchup.b_id in by_id else matchup.b_id,
            "games": matchup.games,
            "a_wins": matchup.a_wins,
            "draws": matchup.draws,
            "b_wins": matchup.b_wins,
            "complete_pairs": len(totals),
            "incomplete_pairs": matchup.incomplete_pairs(),
            "a_score": _rational(a_half, a_half_den) if matchup.games else _rational(0, 1),
            "a_score_ci95": None,
            "sign_test": None,
        }
        if totals and not matchup.mirror:
            seed = matchup_stat_seed(base_seed, ordinal)
            summary = ratings.bootstrap_pair_half_points(totals, seed, bootstrap_replicates)
            entry["a_score_ci95"] = {
                "lower": _rational(summary.lower_sum, summary.denominator),
                "upper": _rational(summary.upper_sum, summary.denominator),
                "seed": summary.bootstrap_seed,
                "replicates": summary.bootstrap_replicates,
            }
            sign = ratings.exact_two_sided_sign_test(totals)
            entry["sign_test"] = {
                "wins": sign.wins,
                "losses": sign.losses,
                "ties": sign.ties,
                "p_value": _rational(sign.p_value_numerator, sign.p_value_denominator),
            }
            matchup_pairs_for_bootstrap.append(
                ratings.MatchupPairs(a_id=matchup.a_id, b_id=matchup.b_id, pair_totals=totals)
            )
        matchup_entries.append(entry)

    # ---------------- anchored BT fit over the whole panel ----------------
    pair_records = _prior_pair_records(ordered_matchups)
    if not pair_records:
        status, fit, fit_error = "no_rated_games", None, None
    else:
        fit, fit_error = _fit_or_none(pair_records, anchor_bot_id)
        status = "ok" if fit is not None else "fit_failed"

    # ---------------- paired bootstrap over refits ----------------
    bootstrap_doc: dict[str, Any]
    intervals: dict[str, tuple[float, float]] = {}
    if fit is None:
        bootstrap_doc = {"status": "not_applicable", "replicates": bootstrap_replicates, "failed_replicates": 0, "seed": None}
    elif not matchup_pairs_for_bootstrap:
        bootstrap_doc = {"status": "no_complete_pairs", "replicates": bootstrap_replicates, "failed_replicates": 0, "seed": None}
    else:
        seed = rating_bootstrap_seed(base_seed)
        try:
            boot = ratings.paired_rating_bootstrap(
                matchup_pairs_for_bootstrap,
                anchor_bot_id,
                bootstrap_seed=seed,
                bootstrap_replicates=bootstrap_replicates,
                virtual_draws=VIRTUAL_DRAWS_PER_MATCHUP,
            )
        except ratings.BtRatingError:
            bootstrap_doc = {"status": "bootstrap_failed", "replicates": bootstrap_replicates, "failed_replicates": bootstrap_replicates, "seed": seed}
        else:
            intervals = {bot_id: (lo, hi) for bot_id, lo, hi in boot.intervals}
            bootstrap_doc = {
                "status": "ok",
                "replicates": boot.replicates,
                "failed_replicates": boot.failed_replicates,
                "seed": seed,
            }

    # ---------------- leaderboard rows ----------------
    ratings_map: dict[str, float] = {}
    if fit is not None:
        ratings_map = dict(fit.ratings_log_units)
    table_rows: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: item.bot_id):
        bot_wdl = wdl.get(entry.bot_id, _Wdl())
        rating = ratings_map.get(entry.bot_id)
        ci = intervals.get(entry.bot_id)
        table_rows.append(
            {
                "rank": None,  # assigned after sorting
                "bot_id": entry.bot_id,
                "name": entry.name,
                "version": entry.version,
                "training_style_tags": list(entry.training_style_tags),
                "rated": rating is not None,
                "rating_log_units_e6": None if rating is None else ratings.rating_e6(rating),
                "elo_milli": None if rating is None else ratings.elo_milli(rating),
                "ci95_log_units_e6": (
                    None if ci is None else [ratings.rating_e6(ci[0]), ratings.rating_e6(ci[1])]
                ),
                "ci95_elo_milli": (
                    None if ci is None else [ratings.elo_milli(ci[0]), ratings.elo_milli(ci[1])]
                ),
                "games": bot_wdl.games,
                "wins": bot_wdl.wins,
                "draws": bot_wdl.draws,
                "losses": bot_wdl.losses,
                "forfeit_losses": forfeit_losses.get(entry.bot_id, 0),
            }
        )
    rated_rows = sorted(
        (row for row in table_rows if row["rated"]),
        key=lambda row: (-row["rating_log_units_e6"], row["bot_id"]),
    )
    for rank, row in enumerate(rated_rows, start=1):
        row["rank"] = rank
    unrated_rows = sorted((row for row in table_rows if not row["rated"]), key=lambda row: row["bot_id"])
    table_rows = rated_rows + unrated_rows

    # ---------------- subratings per training-style tag ----------------
    tags = sorted({tag for entry in entries for tag in entry.training_style_tags})
    subratings: list[dict[str, Any]] = []
    for tag in tags:
        subratings.append(_build_subrating(tag, rows, entries, anchor_bot_id))

    anchor = by_id[anchor_bot_id]
    document: dict[str, Any] = {
        "schema": store.LEADERBOARD_SCHEMA,
        "format": format,
        "status": status,
        "fit_error": fit_error,
        "anchor": {"bot_id": anchor.bot_id, "name": anchor.name, "version": anchor.version},
        "games": counts,
        "bt": {
            "algorithm": _BT_ALGORITHM,
            "anchor_bot_id": anchor_bot_id,
            "virtual_draws_per_matchup": VIRTUAL_DRAWS_PER_MATCHUP,
            "iterations": None if fit is None else fit.iterations,
            "rating_bootstrap": bootstrap_doc,
            "stats_seed_version": _STATS_SEED_VERSION,
        },
        "rows": table_rows,
        "matchups": matchup_entries,
        "subratings": subratings,
        "notes": NOTES,
    }
    return document, render_markdown(document)


def _build_subrating(
    tag: str,
    rows: Sequence[store.LedgerRow],
    entries: Sequence[registry.RegistryEntry],
    anchor_bot_id: str,
) -> dict[str, Any]:
    """One training-style subrating: a filtered recomputation over the ledger."""
    participants = {entry.bot_id for entry in entries if tag in entry.training_style_tags}
    name_of = {entry.bot_id: entry.name for entry in entries}
    version_of = {entry.bot_id: entry.version for entry in entries}
    doc: dict[str, Any] = {
        "tag": tag,
        "status": "skipped",
        "reason": None,
        "anchor_bot_id": None,
        "rows": [],
    }
    if len(participants) < 2:
        doc["reason"] = "fewer_than_two_bots"
        return doc
    slice_rows = [
        row
        for row in rows
        if row.rated and row.bot_id_at("p0") in participants and row.bot_id_at("p1") in participants
    ]
    if not slice_rows:
        doc["reason"] = "no_rated_games"
        return doc
    slice_wdl, _, slice_matchups = _accumulate(slice_rows)
    pair_records = _prior_pair_records([slice_matchups[key] for key in sorted(slice_matchups)])
    if not pair_records:
        doc["reason"] = "no_rated_games"
        return doc
    slice_ids = sorted({record.a_id for record in pair_records} | {record.b_id for record in pair_records})
    slice_anchor = anchor_bot_id if anchor_bot_id in slice_ids else slice_ids[0]
    fit, fit_error = _fit_or_none(pair_records, slice_anchor)
    if fit is None:
        doc["reason"] = f"fit_failed: {fit_error}"
        return doc
    slice_ratings = dict(fit.ratings_log_units)
    sub_rows = []
    for bot_id in slice_ids:
        bot_wdl = slice_wdl.get(bot_id, _Wdl())
        sub_rows.append(
            {
                "bot_id": bot_id,
                "name": name_of.get(bot_id, bot_id),
                "version": version_of.get(bot_id, ""),
                "rating_log_units_e6": ratings.rating_e6(slice_ratings[bot_id]),
                "elo_milli": ratings.elo_milli(slice_ratings[bot_id]),
                "games": bot_wdl.games,
                "wins": bot_wdl.wins,
                "draws": bot_wdl.draws,
                "losses": bot_wdl.losses,
            }
        )
    sub_rows.sort(key=lambda row: (-row["rating_log_units_e6"], row["bot_id"]))
    doc.update(
        {
            "status": "ok",
            "anchor_bot_id": slice_anchor,
            "rows": sub_rows,
        }
    )
    return doc


# ---------------------------------------------------------------------------
# Markdown rendering (deterministic; derived from the JSON document)
# ---------------------------------------------------------------------------


def _fmt_e6(value: int | None) -> str:
    return "-" if value is None else f"{value / 1_000_000:.6f}"


def _fmt_milli(value: int | None) -> str:
    return "-" if value is None else f"{value / 1000:.1f}"


def _fmt_ci(ci: list[int] | None) -> str:
    if ci is None:
        return "-"
    return f"[{_fmt_milli(ci[0])}, {_fmt_milli(ci[1])}]"


def _fmt_rational(value: dict[str, int] | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value['num'] / value['den']:.{digits}f}"


def render_markdown(document: dict[str, Any]) -> str:
    anchor = document["anchor"]
    counts = document["games"]
    boot = document["bt"]["rating_bootstrap"]
    lines = [
        f"# Spellbench leaderboard: {document['format']}",
        "",
        f"- Games: {counts['total']} played, {counts['rated']} rated "
        f"(forfeits rated as losses: {counts['forfeit']}; unrated: truncated {counts['truncated']}, "
        f"halted {counts['halted']})",
        f"- Anchor: {anchor['name']} {anchor['version']}, fixed at 0.000000 log units (Elo display 1000.0)",
        f"- Status: {document['status']}"
        + (f" ({document['fit_error']})" if document["fit_error"] else ""),
        f"- Rating: anchored Bradley-Terry MM, draws count half, "
        f"{document['bt']['virtual_draws_per_matchup']} virtual draw(s) per matchup; "
        f"CI95: paired bootstrap over seat-swapped pairs "
        f"({boot['replicates']} replicates, {boot['failed_replicates']} failed, status {boot['status']})",
        "",
        "| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |",
        "| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in document["rows"]:
        rank = "-" if row["rank"] is None else str(row["rank"])
        lines.append(
            f"| {rank} | {row['name']} {row['version']} | {_fmt_e6(row['rating_log_units_e6'])} "
            f"| {_fmt_milli(row['elo_milli'])} | {_fmt_ci(row['ci95_elo_milli'])} "
            f"| {row['games']} | {row['wins']} | {row['draws']} | {row['losses']} "
            f"| {row['forfeit_losses']} |"
        )
    lines += [
        "",
        "## Matchups (W/D/L from bot A's perspective, rated games)",
        "",
        "| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for matchup in document["matchups"]:
        ci = matchup["a_score_ci95"]
        ci_text = "-"
        if ci is not None:
            ci_text = f"[{_fmt_rational(ci['lower'])}, {_fmt_rational(ci['upper'])}]"
        sign = matchup["sign_test"]
        p_text = "-" if sign is None else _fmt_rational(sign["p_value"])
        lines.append(
            f"| {matchup['a_name']} | {matchup['b_name']} | {matchup['games']} "
            f"| {matchup['a_wins']} | {matchup['draws']} | {matchup['b_wins']} "
            f"| {_fmt_rational(matchup['a_score'])} | {ci_text} | {p_text} |"
        )
    if document["subratings"]:
        lines += ["", "## Subratings by training-style tag", ""]
        for sub in document["subratings"]:
            lines.append(f"### tag: {sub['tag']}")
            lines.append("")
            if sub["status"] != "ok":
                lines.append(f"skipped: {sub['reason']}")
                lines.append("")
                continue
            lines += [
                "| Bot | Rating | Elo | Games | W | D | L |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
            for row in sub["rows"]:
                lines.append(
                    f"| {row['name']} {row['version']} | {_fmt_e6(row['rating_log_units_e6'])} "
                    f"| {_fmt_milli(row['elo_milli'])} | {row['games']} | {row['wins']} "
                    f"| {row['draws']} | {row['losses']} |"
                )
            lines.append("")
    lines += ["## Notes", ""]
    lines += [f"- {note}" for note in document["notes"]]
    lines.append("")
    return "\n".join(lines)
