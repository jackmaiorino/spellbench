"""Ledger rows v2 (spec 11.5, 11.8)."""

from __future__ import annotations

import dataclasses
import re

import pytest

from spellbench.arena.ledger import ENGINE_FAULTS, FORFEIT_CAUSES, LEDGER_SCHEMA, Adjudication, LedgerRow, parse_ledger
from spellbench.errors import ValidationError

A, B = "a" * 64, "b" * 64
ENGINE = {"engine_name": "fake", "engine_version": "1", "rules_snapshot_id": "r", "card_pool_identity": "p"}
DECK = {"deck_id": "sha256:" + "0" * 64, "name": "Burn", "catalog_id": "Burn"}


def row(**changes) -> dict:
    value = {
        "schema": "spellbench-match-ledger/v2", "game_index": 0, "game_id": "g-f67d7fe78c792984", "matchup_index": 0,
        "pair_index": 0, "pair_slot": 0, "format": "pauper-bo1",
        "seats": [{"seat": "p0", "bot_id": A, "name": "a", "version": "1"}, {"seat": "p1", "bot_id": B, "name": "b", "version": "1"}],
        "decks": [DECK, DECK], "outcome": "p0_win", "classification": "natural", "winner": "p0", "winner_bot_id": A,
        "reason": "score", "adjudication": None, "step_count": 4, "decision_count": 4, "decisions_checked": 4,
        "last_selection": None, "game_digest": "sha256:" + "1" * 64, "engine": ENGINE,
    }
    value.update(changes)
    return value


VALID = {
    "natural": row(),
    "forfeit": row(outcome="p1_win", classification="forfeit", winner="p1", winner_bot_id=B, reason="forfeit:stalling",
                   adjudication={"kind": "forfeit", "cause": "stalling", "loser_seat": "p0", "detail": "cap reached"}, decisions_checked=5),
    "validator halt": row(outcome="halted", classification="halted", winner=None, winner_bot_id=None, reason="host_validator:V4",
                          adjudication={"kind": "halt", "detail": "stale reference"}, decisions_checked=5,
                          last_selection={"seat": "p1", "bot_id": B}),
    "engine halt": row(outcome="halted", classification="halted", winner=None, winner_bot_id=None, reason="engine_contract_failure:x"),
    "mandatory loop": row(outcome="draw", winner=None, winner_bot_id=None, reason="mandatory_loop",
                          adjudication={"kind": "mandatory_loop", "detail": "no real choice in the last 250 decisions"}),
    "truncated": row(outcome="truncated", classification="truncated", winner=None, winner_bot_id=None, reason="max_steps",
                     last_selection={"seat": "p0", "bot_id": A}),
}


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_rows_round_trip(name: str) -> None:
    (parsed,) = parse_ledger([VALID[name]])
    assert parsed.to_json() == VALID[name]
    assert parsed.rated == (name in ("natural", "forfeit", "mandatory loop"))


@pytest.mark.parametrize(
    "bad",
    [
        row(pair_slot=2),
        row(last_selection={"seat": "p0", "bot_id": A}),                               # only halted and truncated rows
        row(adjudication={"kind": "halt", "detail": "x"}),                            # natural rows never halt
        row(decisions_checked=6),
        row(game_digest="sha256:xyz"),
        row(**{**VALID["forfeit"], "adjudication": {**VALID["forfeit"]["adjudication"], "loser_seat": "p1"}}),
        row(**{**VALID["forfeit"], "reason": "forfeit:boredom",
               "adjudication": {**VALID["forfeit"]["adjudication"], "cause": "boredom"}}),
        row(**{**VALID["validator halt"], "reason": "host_validator:V11"}),
        row(**{**VALID["truncated"], "winner": "p0", "winner_bot_id": A}),
    ],
)
def test_invalid_rows_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        parse_ledger([bad])


def test_seat_lookups() -> None:
    (parsed,) = parse_ledger([row()])
    assert (parsed.bot_id_at("p0"), parsed.bot_id_at("p1"), parsed.pair_slot) == (A, B, 0)
    assert isinstance(parsed, LedgerRow)


def test_the_closed_sets() -> None:
    assert LEDGER_SCHEMA == "spellbench-match-ledger/v2"
    assert FORFEIT_CAUSES == frozenset(
        {"timeout", "stalling", "malformed_response", "invalid_selection", "agent_error", "transport_error"}
    )
    assert ENGINE_FAULTS == ("error", "timeout", "transport", "malformed", "terminal_counts")


def test_every_host_ending_round_trips() -> None:
    """Each forfeit cause, a p0 win by forfeit, each host halt reason, and a decklist deck (no catalog id)."""
    forfeit = VALID["forfeit"]
    rows = [{**forfeit, "reason": f"forfeit:{cause}", "adjudication": {**forfeit["adjudication"], "cause": cause}}
            for cause in sorted(FORFEIT_CAUSES)]
    rows.append({**forfeit, "outcome": "p0_win", "winner": "p0", "winner_bot_id": A,
                 "adjudication": {**forfeit["adjudication"], "loser_seat": "p1"}})
    rows += [{**VALID["validator halt"], "reason": f"host_validator:V{rule}"} for rule in range(1, 11)]
    rows += [{**VALID["validator halt"], "reason": f"host_engine_fault:{fault}"} for fault in ENGINE_FAULTS]
    rows.append(row(decks=[{**DECK, "catalog_id": None}, DECK]))
    rows = [{**value, "game_index": index} for index, value in enumerate(rows)]
    assert [parsed.to_json() for parsed in parse_ledger(rows)] == rows


def _without(value: dict, key: str) -> dict:
    return {name: item for name, item in value.items() if name != key}


SWAPPED = [{"seat": "p1", "bot_id": B, "name": "b", "version": "1"}, {"seat": "p0", "bot_id": A, "name": "a", "version": "1"}]

# Each rule of the brief once more, with the path its error must name (so no case passes by failing elsewhere).
MORE_INVALID = {
    "v1 schema": (row(schema="spellbench-match-ledger/v1"), "ledger[0].schema"),
    "an extra field": (row(x_note="hi"), "ledger[0]"),
    "a missing field": (_without(row(), "decisions_checked"), "ledger[0]"),
    "seats p1 first": (row(seats=SWAPPED), "ledger[0].seats"),
    "one deck": (row(decks=[DECK]), "ledger[0].decks"),
    "a deck without a name": (row(decks=[{**DECK, "name": ""}, DECK]), "ledger[0].decks[0].name"),
    "a bool pair slot": (row(pair_slot=True), "ledger[0].pair_slot"),
    "fewer checked than answered": (row(decisions_checked=3), "ledger[0].decisions_checked"),
    "an uppercase digest": (row(game_digest="sha256:" + "A" * 64), "ledger[0].game_digest"),
    "a fifth engine field": (row(engine={**ENGINE, "source_revision": None}), "ledger[0].engine"),
    "an empty engine field": (row(engine={**ENGINE, "engine_version": ""}), "ledger[0].engine.engine_version"),
    "the other seat's bot as winner": (row(winner_bot_id=B), "ledger[0].winner_bot_id"),
    "a natural row forfeited": (row(adjudication=VALID["forfeit"]["adjudication"]), "ledger[0].adjudication"),
    "a mandatory loop won": ({**VALID["mandatory loop"], "outcome": "p0_win", "winner": "p0", "winner_bot_id": A},
                             "ledger[0].adjudication"),
    "a mandatory loop with another reason": ({**VALID["mandatory loop"], "reason": "stall_ended"}, "ledger[0].adjudication"),
    "a forfeit without adjudication": ({**VALID["forfeit"], "adjudication": None}, "ledger[0].adjudication"),
    "a forfeit draw": ({**VALID["forfeit"], "outcome": "draw", "winner": None, "winner_bot_id": None}, "ledger[0].outcome"),
    "a forfeit reason of another cause": ({**VALID["forfeit"], "reason": "forfeit:timeout"}, "ledger[0].reason"),
    "a forfeit adjudication without loser_seat": (
        {**VALID["forfeit"], "adjudication": _without(VALID["forfeit"]["adjudication"], "loser_seat")}, "ledger[0].adjudication"),
    "a halt with cause and loser_seat": (
        {**VALID["validator halt"], "adjudication": {**VALID["forfeit"]["adjudication"], "kind": "halt"}}, "ledger[0].adjudication"),
    "a mandatory loop with loser_seat": (
        {**VALID["mandatory loop"], "adjudication": {**VALID["mandatory loop"]["adjudication"], "loser_seat": "p0"}},
        "ledger[0].adjudication"),
    "the v1 engine_halt kind": ({**VALID["validator halt"], "adjudication": {"kind": "engine_halt", "detail": "x"}},
                                "ledger[0].adjudication.kind"),
    "a halted row forfeited": ({**VALID["validator halt"], "adjudication": VALID["forfeit"]["adjudication"]},
                               "ledger[0].adjudication"),
    "an unknown engine fault": ({**VALID["validator halt"], "reason": "host_engine_fault:crash"}, "ledger[0].reason"),
    "a host halt with an engine reason": ({**VALID["validator halt"], "reason": "engine_contract_failure:x"}, "ledger[0].reason"),
    "a halted row with a winner": ({**VALID["engine halt"], "winner": "p0", "winner_bot_id": A}, "ledger[0].winner"),
    "a truncated row halted by the host": ({**VALID["truncated"], "adjudication": {"kind": "halt", "detail": "x"}},
                                           "ledger[0].adjudication"),
    "a truncated row with outcome halted": ({**VALID["truncated"], "outcome": "halted"}, "ledger[0].outcome"),
    "a last selection naming the other bot": ({**VALID["truncated"], "last_selection": {"seat": "p0", "bot_id": B}},
                                              "ledger[0].last_selection.bot_id"),
    "a last selection on a forfeit": ({**VALID["forfeit"], "last_selection": {"seat": "p0", "bot_id": A}},
                                      "ledger[0].last_selection"),
}


@pytest.mark.parametrize("name", sorted(MORE_INVALID))
def test_each_rule_names_the_field_it_rejects(name: str) -> None:
    bad, path = MORE_INVALID[name]
    with pytest.raises(ValidationError, match=re.escape(path + ":")):
        parse_ledger([bad])


def test_errors_name_the_row() -> None:
    with pytest.raises(ValidationError, match=re.escape("ledger[1].pair_slot:")):
        parse_ledger([row(), row(game_index=1, pair_slot=2)])


def test_rows_built_directly_are_checked() -> None:
    """The runner builds rows with the constructor, which applies the same rules."""
    (parsed,) = parse_ledger([row()])
    with pytest.raises(ValidationError, match=re.escape("ledger.pair_slot:")):
        dataclasses.replace(parsed, pair_slot=2)
    with pytest.raises(ValidationError, match=re.escape("ledger.seats:")):
        dataclasses.replace(parsed, seats=parsed.seats[::-1])
    for kind in ("halt", "mandatory_loop"):                                        # R1-14: never a cause or a loser
        with pytest.raises(ValidationError, match=re.escape("adjudication:")):
            Adjudication(kind=kind, detail="x", cause="timeout")
        with pytest.raises(ValidationError, match=re.escape("adjudication:")):
            Adjudication(kind=kind, detail="x", loser_seat="p0")
