"""Deck slices: per-deck ratings recomputed from each deck's games alone."""

from __future__ import annotations

import dataclasses
import hashlib

from spellbench import models
from spellbench.arena import leaderboard, registry, store

PROVENANCE = models.Provenance("fake", "0", "rules", "pool")
ALPHA, BETA, GAMMA = (
    registry.build_entry(name=name, version="1.0.0", descriptor=registry.builtin_descriptor(name, "1.0.0"))
    for name in ("alpha", "beta", "gamma")
)
ENTRIES = [ALPHA, BETA, GAMMA]
BASE_SEED = 7


def _row(matchup: int, pair: int, game: int, a, b, decks: tuple[str, str], result: str) -> store.LedgerRow:
    """Game ``game`` of pair ``pair`` of matchup (a, b).

    Game 0 seats a at p0, game 1 seats b at p0. ``result`` is "a" or "b"
    (that bot wins), "draw", or "halted".
    """
    p0, p1 = (a, b) if game == 0 else (b, a)
    seats = tuple(
        store.LedgerSeat(seat=seat, bot_id=entry.bot_id, name=entry.name, version=entry.version)
        for seat, entry in (("p0", p0), ("p1", p1))
    )
    if result == "halted":
        outcome, classification, winner = "halted", "halted", None
    elif result == "draw":
        outcome, classification, winner = "draw", "natural", None
    else:
        winner_entry = a if result == "a" else b
        winner = "p0" if winner_entry is p0 else "p1"
        outcome, classification = f"{winner}_win", "natural"
    return store.LedgerRow(
        game_id=f"m{matchup:04d}p{pair:04d}g{game}",
        matchup_index=matchup,
        pair_index=pair,
        game_index=game,
        format="pauper-bo1",
        game_seed=1,
        seats=seats,
        decks=({"catalog_id": decks[0]}, {"catalog_id": decks[1]}),
        outcome=outcome,
        classification=classification,
        winner=winner,
        winner_bot_id=None if winner is None else (p0 if winner == "p0" else p1).bot_id,
        reason="test",
        adjudication=None,
        step_count=1,
        decision_count=1,
        engine=PROVENANCE,
    )


def _pairs(matchup: int, a, b, schedule: list[tuple[str, str, str]]) -> list[store.LedgerRow]:
    """One matchup; ``schedule[p]`` is (deck, game 0 result, game 1 result) of pair p."""
    rows = []
    for pair, (deck, first, second) in enumerate(schedule):
        rows.append(_row(matchup, pair, 0, a, b, (deck, deck), first))
        rows.append(_row(matchup, pair, 1, a, b, (deck, deck), second))
    return rows


# A two-deck pool alternating by pair: alpha is strongest on Burn, beta on Elves.
ROWS = (
    _pairs(0, ALPHA, BETA, [("Burn", "a", "a"), ("Elves", "b", "b"), ("Burn", "a", "draw"), ("Elves", "b", "a")])
    + _pairs(1, ALPHA, GAMMA, [("Burn", "a", "a"), ("Elves", "draw", "draw"), ("Burn", "a", "b"), ("Elves", "b", "b")])
    + _pairs(2, BETA, GAMMA, [("Burn", "b", "a"), ("Elves", "a", "a"), ("Burn", "draw", "a"), ("Elves", "a", "draw")])
)


def _build(rows, base_seed: int = BASE_SEED):
    return leaderboard.build_leaderboard(
        rows, ENTRIES, anchor_bot_id=ALPHA.bot_id, base_seed=base_seed, bootstrap_replicates=1000, format="pauper-bo1"
    )


def test_one_slice_per_deck_in_sorted_order() -> None:
    document, _ = _build(ROWS)
    slices = document["slices"]["deck"]
    assert [deck_slice["label"] for deck_slice in slices] == ["Burn", "Elves"]
    assert slices[0]["decks"] == [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}]


def test_a_slice_equals_a_recomputation_from_that_decks_rows() -> None:
    document, _ = _build(ROWS)
    for ordinal, deck_slice in enumerate(document["slices"]["deck"]):
        deck = deck_slice["decks"][0]["catalog_id"]
        deck_rows = [row for row in ROWS if row.decks[0]["catalog_id"] == deck]
        direct, _ = _build(deck_rows, base_seed=leaderboard.deck_slice_seed(BASE_SEED, ordinal))
        assert deck_slice["status"] == direct["status"] == "ok"
        assert deck_slice["fit_error"] is None
        assert deck_slice["rows"] == direct["rows"]
        assert deck_slice["games"] == direct["games"]
        assert deck_slice["rating_bootstrap"] == direct["bt"]["rating_bootstrap"]
        assert direct["slices"]["deck"] == []


def test_a_document_with_slices_rebuilds_as_identical_canonical_json() -> None:
    # validate recomputes leaderboard.json and LEADERBOARD.md byte for byte.
    first, first_markdown = _build(ROWS)
    second, second_markdown = _build(ROWS)
    assert store.canonical_bytes(first) == store.canonical_bytes(second)
    assert first_markdown == second_markdown


def test_slices_keep_the_overall_anchor() -> None:
    document, _ = _build(ROWS)
    for deck_slice in document["slices"]["deck"]:
        anchor = next(row for row in deck_slice["rows"] if row["bot_id"] == ALPHA.bot_id)
        assert anchor["elo_milli"] == 1_000_000


def test_decks_split_the_ratings() -> None:
    document, _ = _build(ROWS)
    by_deck = {s["label"]: {row["name"]: row for row in s["rows"]} for s in document["slices"]["deck"]}
    assert by_deck["Burn"]["beta"]["elo_milli"] < 1_000_000 < by_deck["Elves"]["beta"]["elo_milli"]


def test_a_single_pairing_ledger_has_no_slices() -> None:
    burn_only = [row for row in ROWS if row.decks[0]["catalog_id"] == "Burn"]
    document, markdown = _build(burn_only)
    assert document["slices"] == {"deck": []}
    assert "## By deck" not in markdown


def test_a_slice_without_a_rated_anchor_is_reported_not_raised() -> None:
    # Both Elves games between alpha and beta halted, so the anchor (alpha)
    # has no complete pair on Elves and that slice cannot be anchored.
    rows = _pairs(0, ALPHA, BETA, [("Burn", "a", "a"), ("Elves", "halted", "halted")]) + _pairs(
        1, BETA, GAMMA, [("Burn", "a", "b"), ("Elves", "a", "draw")]
    )
    document, markdown = _build(rows)
    assert document["status"] == "ok"
    elves = next(s for s in document["slices"]["deck"] if s["label"] == "Elves")
    assert elves["status"] == "fit_failed" and elves["fit_error"]
    assert elves["games"]["halted"] == 2
    assert not any(row["rated"] for row in elves["rows"])
    assert "skipped: fit_failed" in markdown


def test_mixed_seat_decks_get_a_versus_label() -> None:
    rows = [
        _row(0, 0, 0, ALPHA, BETA, ("Faeries", "Affinity"), "a"),
        _row(0, 0, 1, ALPHA, BETA, ("Faeries", "Affinity"), "b"),
        _row(0, 1, 0, ALPHA, BETA, ("Burn", "Burn"), "a"),
        _row(0, 1, 1, ALPHA, BETA, ("Burn", "Burn"), "a"),
    ]
    document, _ = _build(rows)
    assert [s["label"] for s in document["slices"]["deck"]] == ["Burn", "Faeries vs Affinity"]


def test_a_decklist_deck_is_labeled_by_its_digest() -> None:
    decklist = {"decklist": [{"name": "Mountain", "count": 20}, {"name": "Lightning Bolt", "count": 4}]}
    canonical = b'{"decklist":[{"count":20,"name":"Mountain"},{"count":4,"name":"Lightning Bolt"}]}'
    rows = [
        _row(0, 0, 0, ALPHA, BETA, ("Burn", "Burn"), "a"),
        _row(0, 0, 1, ALPHA, BETA, ("Burn", "Burn"), "b"),
        *(
            dataclasses.replace(_row(0, 1, game, ALPHA, BETA, ("Burn", "Burn"), "a"), decks=(decklist, decklist))
            for game in (0, 1)
        ),
    ]
    document, _ = _build(rows)
    labels = [s["label"] for s in document["slices"]["deck"]]
    assert labels == ["Burn", "decklist " + hashlib.sha256(canonical).hexdigest()[:12]]


def test_the_markdown_lists_each_deck() -> None:
    _, markdown = _build(ROWS)
    assert "## By deck" in markdown
    assert markdown.index("### Burn") < markdown.index("### Elves") < markdown.index("## Notes")


def test_the_by_deck_heading_follows_exactly_one_blank_line() -> None:
    # The matchup table ends without a blank line; the subratings block
    # (rendered when any bot has a tag) ends with one.
    tagged = [dataclasses.replace(entry, training_style_tags=("rl",)) for entry in ENTRIES]
    for entries in (ENTRIES, tagged):
        _, markdown = leaderboard.build_leaderboard(
            ROWS, entries, anchor_bot_id=ALPHA.bot_id, base_seed=BASE_SEED, bootstrap_replicates=1000, format="pauper-bo1"
        )
        assert "\n\n## By deck\n" in markdown and "\n\n\n" not in markdown


def test_deck_slice_seeds_stay_in_the_protocol_range() -> None:
    seeds = {leaderboard.deck_slice_seed(2**53, ordinal) for ordinal in range(8)}
    assert len(seeds) == 8 and all(0 <= seed < 2**53 for seed in seeds)
