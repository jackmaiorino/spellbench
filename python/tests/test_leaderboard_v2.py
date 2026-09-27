"""Leaderboard v2: attribution rates, v2 notes; v1 documents stay byte for byte."""

from __future__ import annotations

from pathlib import Path

from spellbench.arena import leaderboard, legacy_v1, registry, store
from spellbench.arena.ledger import parse_ledger

from test_ledger import A, B, VALID, row

REPO = Path(__file__).resolve().parents[2]
ENTRIES = [registry.RegistryEntry(bot_id=A, name="a", version="1", engine="any"),
           registry.RegistryEntry(bot_id=B, name="b", version="1", engine="any")]


def _build(rows):
    return leaderboard.build_leaderboard(parse_ledger(rows), ENTRIES, anchor_bot_id=A, base_seed=7,
                                         bootstrap_replicates=1000, format="pauper-bo1", schema=leaderboard.LEADERBOARD_SCHEMA_V2)


def test_v2_rows_carry_attribution() -> None:
    rows = [row(), row(game_index=1, pair_slot=1, seats=[{"seat": "p0", "bot_id": B, "name": "b", "version": "1"},
                                                            {"seat": "p1", "bot_id": A, "name": "a", "version": "1"}],
                       winner_bot_id=B),
            {**VALID["validator halt"], "game_index": 2, "pair_index": 1},
            {**VALID["forfeit"], "game_index": 3, "pair_index": 1, "pair_slot": 1}]
    document, markdown = _build(rows)
    assert document["schema"] == "spellbench-leaderboard/v2" and document["notes"] == leaderboard.NOTES_V2
    by_name = {entry["name"]: entry for entry in document["rows"]}
    assert (by_name["b"]["halts_attributed"], by_name["a"]["halts_attributed"]) == (1, 0)
    assert by_name["b"]["halt_rate"] == {"num": 1, "den": 4} and by_name["a"]["games_played"] == 4
    assert by_name["a"]["forfeits_by_cause"] == {"stalling": 1}
    assert "## Halts and truncations after each bot's selection" in markdown


def test_v2_deck_slices_are_labelled_by_deck_name() -> None:
    elves = {"deck_id": "sha256:" + "2" * 64, "name": "Elves", "catalog_id": "Elves"}
    swapped = [{"seat": "p0", "bot_id": B, "name": "b", "version": "1"}, {"seat": "p1", "bot_id": A, "name": "a", "version": "1"}]
    rows = [row(), row(game_index=1, pair_slot=1, seats=swapped, winner_bot_id=B),
            row(game_index=2, pair_index=1, decks=[elves, elves]),
            row(game_index=3, pair_index=1, pair_slot=1, seats=swapped, winner_bot_id=B, decks=[elves, elves])]
    document, _ = _build(rows)                    # LedgerDeck rows, normalized once (R2-8)
    assert [deck_slice["label"] for deck_slice in document["slices"]["deck"]] == ["Burn", "Elves"]


def test_v1_documents_are_unchanged() -> None:
    run = REPO / "benchmarks" / "pauper-kernel" / "runs" / "2026-09-26"
    rows = legacy_v1.parse_ledger(store.read_jsonl(run / "matches.jsonl", schema=legacy_v1.LEDGER_SCHEMA_V1))
    entries = registry.read_registry(run / "registry.json")
    anchor = next(entry.bot_id for entry in entries if entry.name == "uniform")
    document, markdown = leaderboard.build_leaderboard(rows, entries, anchor_bot_id=anchor, base_seed=20260926,
                                                       bootstrap_replicates=2000, format="pauper-bo1",
                                                       schema=leaderboard.LEADERBOARD_SCHEMA_V1)
    assert store.canonical_bytes(document) + b"\n" == (run / "leaderboard.json").read_bytes()
    assert markdown.encode("utf-8") == (run / "LEADERBOARD.md").read_bytes()
