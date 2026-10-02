"""Deck slices: per-deck ratings recomputed from each deck's games alone."""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from spellbench.arena import leaderboard, registry, store
from spellbench.arena.ledger import parse_ledger

from arena_helpers import TEST_RUN_SECRET

ENGINE = {"engine_name": "fake", "engine_version": "1", "rules_snapshot_id": "r", "card_pool_identity": "p"}
ALPHA, BETA, GAMMA = (
    registry.build_entry(name=name, version="2.0.0", descriptor=registry.builtin_descriptor(name, "2.0.0"))
    for name in ("alpha", "beta", "gamma")
)
ENTRIES = [ALPHA, BETA, GAMMA]
BASE_SEED = 7


def _catalog_deck(name: str) -> dict[str, Any]:
    return {"deck_id": "sha256:" + hashlib.sha256(name.encode()).hexdigest(), "name": name, "catalog_id": name}


def _row(matchup: int, pair: int, game: int, a, b, decks: tuple[dict, dict], result: str) -> dict[str, Any]:
    """Game ``game`` of pair ``pair`` of matchup (a, b), as a ledger-v2 JSON row.

    Slot 0 seats a at p0, slot 1 seats b at p0. ``result`` is "a" or "b"
    (that bot wins), "draw", or "halted".
    """
    game_index = pair * 2 + game
    p0, p1 = (a, b) if game == 0 else (b, a)
    seats = [
        {"seat": seat, "bot_id": entry.bot_id, "name": entry.name, "version": entry.version}
        for seat, entry in (("p0", p0), ("p1", p1))
    ]
    if result == "halted":
        outcome, classification, winner = "halted", "halted", None
    elif result == "draw":
        outcome, classification, winner = "draw", "natural", None
    else:
        winner_entry = a if result == "a" else b
        winner = "p0" if winner_entry is p0 else "p1"
        outcome, classification = f"{winner}_win", "natural"
    return {
        "schema": "spellbench-match-ledger/v2",
        "game_index": game_index,
        "game_id": TEST_RUN_SECRET.game_id(game_index),
        "matchup_index": matchup,
        "pair_index": pair,
        "pair_slot": game,
        "format": "pauper-bo1",
        "seats": seats,
        "decks": list(decks),
        "outcome": outcome,
        "classification": classification,
        "winner": winner,
        "winner_bot_id": None if winner is None else (p0 if winner == "p0" else p1).bot_id,
        "reason": "test",
        "adjudication": None,
        "step_count": 1,
        "decision_count": 1,
        "decisions_checked": 1,
        "last_selection": None,
        "game_digest": "sha256:" + "1" * 64,
        "engine": ENGINE,
    }


def _pairs(matchup: int, a, b, schedule: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """One matchup; ``schedule[p]`` is (deck, game 0 result, game 1 result) of pair p."""
    rows = []
    for pair, (deck, first, second) in enumerate(schedule):
        decks = (_catalog_deck(deck), _catalog_deck(deck))
        rows.append(_row(matchup, pair, 0, a, b, decks, first))
        rows.append(_row(matchup, pair, 1, a, b, decks, second))
    return rows


# A two-deck pool alternating by pair: alpha is strongest on Burn, beta on Elves.
ROWS = (
    _pairs(0, ALPHA, BETA, [("Burn", "a", "a"), ("Elves", "b", "b"), ("Burn", "a", "draw"), ("Elves", "b", "a")])
    + _pairs(1, ALPHA, GAMMA, [("Burn", "a", "a"), ("Elves", "draw", "draw"), ("Burn", "a", "b"), ("Elves", "b", "b")])
    + _pairs(2, BETA, GAMMA, [("Burn", "b", "a"), ("Elves", "a", "a"), ("Burn", "draw", "a"), ("Elves", "a", "draw")])
)


def _build(rows, base_seed: int = BASE_SEED, entries=ENTRIES):
    return leaderboard.build_leaderboard(
        parse_ledger(rows), entries, anchor_bot_id=ALPHA.bot_id, base_seed=base_seed, bootstrap_replicates=1000,
        format="pauper-bo1", schema=leaderboard.LEADERBOARD_SCHEMA_V2,
    )


def test_one_slice_per_deck_in_sorted_order() -> None:
    document, _ = _build(ROWS)
    slices = document["slices"]["deck"]
    assert [deck_slice["label"] for deck_slice in slices] == ["Burn", "Elves"]
    assert slices[0]["decks"] == [_catalog_deck("Burn"), _catalog_deck("Burn")]


def test_a_slice_equals_a_recomputation_from_that_decks_rows() -> None:
    document, _ = _build(ROWS)
    for ordinal, deck_slice in enumerate(document["slices"]["deck"]):
        deck = deck_slice["decks"][0]["catalog_id"]
        deck_rows = [row for row in ROWS if row["decks"][0]["catalog_id"] == deck]
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
    burn_only = [row for row in ROWS if row["decks"][0]["catalog_id"] == "Burn"]
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
    faeries, affinity = _catalog_deck("Faeries"), _catalog_deck("Affinity")
    burn = _catalog_deck("Burn")
    rows = [
        _row(0, 0, 0, ALPHA, BETA, (faeries, affinity), "a"),
        _row(0, 0, 1, ALPHA, BETA, (faeries, affinity), "b"),
        _row(0, 1, 0, ALPHA, BETA, (burn, burn), "a"),
        _row(0, 1, 1, ALPHA, BETA, (burn, burn), "a"),
    ]
    document, _ = _build(rows)
    assert [s["label"] for s in document["slices"]["deck"]] == ["Burn", "Faeries vs Affinity"]


def test_a_decklist_deck_is_labeled_by_its_name() -> None:
    # A v2 ledger deck carries the deck's name, and the slice label uses it (Task 20).
    brew = {"deck_id": "sha256:" + hashlib.sha256(b"My Brew").hexdigest(), "name": "My Brew", "catalog_id": None}
    burn = _catalog_deck("Burn")
    rows = [
        _row(0, 0, 0, ALPHA, BETA, (burn, burn), "a"),
        _row(0, 0, 1, ALPHA, BETA, (burn, burn), "b"),
        _row(0, 1, 0, ALPHA, BETA, (brew, brew), "a"),
        _row(0, 1, 1, ALPHA, BETA, (brew, brew), "a"),
    ]
    document, _ = _build(rows)
    labels = [s["label"] for s in document["slices"]["deck"]]
    assert labels == ["Burn", "My Brew"]


def test_the_markdown_lists_each_deck() -> None:
    _, markdown = _build(ROWS)
    assert "## By deck" in markdown
    assert markdown.index("### Burn") < markdown.index("### Elves") < markdown.index("## Notes")


def test_the_by_deck_heading_follows_exactly_one_blank_line() -> None:
    # The matchup table ends without a blank line; the subratings block
    # (rendered when any bot has a tag) ends with one.
    tagged = [dataclasses.replace(entry, training_style_tags=("rl",)) for entry in ENTRIES]
    for entries in (ENTRIES, tagged):
        _, markdown = _build(ROWS, entries=entries)
        assert "\n\n## By deck\n" in markdown and "\n\n\n" not in markdown


def test_deck_slice_seeds_stay_in_the_protocol_range() -> None:
    seeds = {leaderboard.deck_slice_seed(2**53, ordinal) for ordinal in range(8)}
    assert len(seeds) == 8 and all(0 <= seed < 2**53 for seed in seeds)
