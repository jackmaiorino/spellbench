"""Ledger rows v2 (spec 11.5, 11.8)."""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import pathlib
import pickle
import re
import sys
import types

import pytest

from spellbench.arena import ledger
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
    assert ENGINE_FAULTS == ("error", "timeout", "transport", "malformed", "terminal_counts", "terminal_reason")


def test_a_terminal_reason_halt_is_a_ledger_row() -> None:
    """The game loop halts an engine terminal whose reason impersonates the host's (Task 23 fix round 1)."""
    halt = {**VALID["validator halt"], "reason": "host_engine_fault:terminal_reason",
            "adjudication": {"kind": "halt", "detail": "terminal reason starts with the host-only prefix 'forfeit:'"}}
    (parsed,) = parse_ledger([halt])
    assert parsed.to_json() == halt and not parsed.rated


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


# Fix round 1: each identifier in its format (deck_id, spec 4.3; game_id, spec 11.6; bot_id, the arena registry).
BOT_ID_FORM = "64 lowercase hex digits"
GAME_ID_FORM = "g- followed by 16 lowercase hex digits"
SHA256_ID_FORM = "sha256: followed by 64 lowercase hex digits"
SEAT_P0, SEAT_P1 = row()["seats"]
WRONG_FORMAT = {
    "a v1 game id": (row(game_id="m0001p0000g0"), "ledger[0].game_id", GAME_ID_FORM),
    "an uppercase game id": (row(game_id="g-F67D7FE78C792984"), "ledger[0].game_id", GAME_ID_FORM),
    "a short game id": (row(game_id="g-f67d7fe78c79298"), "ledger[0].game_id", GAME_ID_FORM),
    "a deck id without sha256:": (row(decks=[{**DECK, "deck_id": "0" * 64}, DECK]), "ledger[0].decks[0].deck_id", SHA256_ID_FORM),
    "a short deck id": (row(decks=[DECK, {**DECK, "deck_id": "sha256:" + "0" * 63}]), "ledger[0].decks[1].deck_id",
                        SHA256_ID_FORM),
    "an uppercase seat bot id": (row(seats=[{**SEAT_P0, "bot_id": A.upper()}, SEAT_P1]), "ledger[0].seats[0].bot_id",
                                 BOT_ID_FORM),
    "a short seat bot id": (row(seats=[SEAT_P0, {**SEAT_P1, "bot_id": B[:63]}]), "ledger[0].seats[1].bot_id", BOT_ID_FORM),
    "a short winner bot id": (row(winner_bot_id=A[:63]), "ledger[0].winner_bot_id", BOT_ID_FORM),
    "a short last selection bot id": ({**VALID["truncated"], "last_selection": {"seat": "p0", "bot_id": A[:63]}},
                                      "ledger[0].last_selection.bot_id", BOT_ID_FORM),
}


@pytest.mark.parametrize("name", sorted(WRONG_FORMAT))
def test_identifiers_have_their_formats(name: str) -> None:
    bad, path, form = WRONG_FORMAT[name]
    with pytest.raises(ValidationError, match=re.escape(f"{path}: must be {form}")):
        parse_ledger([bad])


@pytest.mark.parametrize("name", sorted(VALID))
def test_rows_survive_pickle_and_deepcopy(name: str) -> None:
    """The executor ships rows to and from spawned workers; the init-only context is no part of a row."""
    (parsed,) = parse_ledger([VALID[name]])
    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
        restored = pickle.loads(pickle.dumps(parsed, protocol))
        assert restored == parsed and restored.to_json() == VALID[name]
    assert copy.deepcopy(parsed) == parsed
    assert parsed == LedgerRow.from_json(VALID[name]) and "context" not in repr(parsed)   # parsed as ledger[0], then as ledger
    parsed.to_json()["engine"]["engine_name"] = "changed"
    assert parsed.engine == ENGINE                                                      # to_json hands out a copy


# Fix round 1: the mutation check, committed. Each entry breaks one rule of ledger.py (its text, then the broken
# text), and some rule test must then fail; the control runs the same harness on the unchanged file.
RULE_TESTS = (
    test_valid_rows_round_trip, test_invalid_rows_are_rejected, test_seat_lookups, test_every_host_ending_round_trips,
    test_each_rule_names_the_field_it_rejects, test_errors_name_the_row, test_rows_built_directly_are_checked,
    test_identifiers_have_their_formats,
)
LEDGER_SOURCE = pathlib.Path(ledger.__file__).read_text(encoding="utf-8")
MUTATIONS = {
    "seats in any order": ("if tuple(entry.seat for entry in self.seats) != _schema.SEATS:", "if False:"),
    "any adjudication keys (R1-14)": ("require_keys(value, _ADJUDICATION_KEYS[kind], context)",
                                      "require_keys(value, set(value), context)"),
    "a halt written with cause and loser": (
        'return {"kind": self.kind, "detail": self.detail}',
        'return {"kind": self.kind, "cause": self.cause, "loser_seat": self.loser_seat, "detail": self.detail}'),
    "a halt or mandatory loop with a cause": ("elif self.cause is not None or self.loser_seat is not None:", "elif False:"),
    "any forfeit cause": ('_schema.vocab(self.cause, FORFEIT_CAUSES, f"{context}.cause")',
                          '_schema.nonempty(self.cause, f"{context}.cause")'),
    "host halt reasons by prefix": ("if self.reason not in _HOST_HALT_REASONS:",
                                    'if not self.reason.startswith(("host_validator:V", "host_engine_fault:")):'),
    "any decisions_checked": ("if not self.step_count <= self.decisions_checked <= self.step_count + 1:", "if False:"),
    "a last selection on any row": ('if self.classification not in ("truncated", "halted"):', "if False:"),
    "a last selection naming any bot": ("if self.last_selection.bot_id != self.bot_id_at(self.last_selection.seat):",
                                        "if False:"),
    "a winner on truncated and halted rows": (
        '_schema.fail(f"{context}.winner", f"a {self.classification} row has winner null")', "pass"),
    "a truncated row adjudicated": ('_schema.fail(f"{context}.adjudication", "a truncated row has no adjudication")', "pass"),
    "a forfeit lost by its winner": ("if self.adjudication.loser_seat == self.winner:", "if False:"),
    "any forfeit reason": ('if self.reason != f"forfeit:{self.adjudication.cause}":', "if False:"),
    "a natural row halted or forfeited": ('if kind not in (None, "mandatory_loop"):',
                                          'if kind not in (None, "mandatory_loop", "halt", "forfeit"):'),
    "a mandatory loop with any result": (
        'if kind == "mandatory_loop" and (self.outcome, self.reason) != ("draw", "mandatory_loop"):', "if False:"),
    "any engine keys": (
        'require_keys(_schema.as_object(self.engine, f"{context}.engine"), _ENGINE_KEYS, f"{context}.engine")',
        '_schema.as_object(self.engine, f"{context}.engine")'),
    "empty engine values": ('_schema.nonempty(self.engine[key], f"{context}.engine.{key}")', "pass"),
    "any integer pair slot": ("if type(self.pair_slot) is not int or self.pair_slot not in (0, 1):",
                              "if type(self.pair_slot) is not int:"),
    "any winner_bot_id": ("if self.winner_bot_id != expected:", "if False:"),
    "any schema": ('if row["schema"] != LEDGER_SCHEMA:', "if False:"),
    "halted rows rated": ('return self.classification in ("natural", "forfeit")', 'return self.classification != "truncated"'),
    "from_json without its context": (
        'engine=dict(_schema.as_object(row["engine"], f"{context}.engine")),\n            context=context,',
        'engine=dict(_schema.as_object(row["engine"], f"{context}.engine")),'),
    "a deck id in any form": ('_formatted(self.deck_id, _SHA256_ID_RE, _SHA256_ID_FORM, f"{context}.deck_id")',
                              '_schema.nonempty(self.deck_id, f"{context}.deck_id")'),
    "a game id in any form": ('_formatted(self.game_id, _GAME_ID_RE, _GAME_ID_FORM, f"{context}.game_id")',
                              '_schema.nonempty(self.game_id, f"{context}.game_id")'),
    "a game digest in any form": ('_formatted(self.game_digest, _SHA256_ID_RE, _SHA256_ID_FORM, f"{context}.game_digest")',
                                  '_schema.text(self.game_digest, f"{context}.game_digest")'),
    "a seat bot id in any form": ('_bot_id(self.bot_id, f"{context}.bot_id")\n        _schema.nonempty(self.name',
                                  '_schema.nonempty(self.bot_id, f"{context}.bot_id")\n        _schema.nonempty(self.name'),
    "a last selection bot id in any form": ('_bot_id(self.bot_id, f"{context}.bot_id")\n\n',
                                            '_schema.nonempty(self.bot_id, f"{context}.bot_id")\n\n'),
    "a winner bot id in any form": ("_schema.nullable(self.winner_bot_id, _bot_id,",
                                    "_schema.nullable(self.winner_bot_id, _schema.nonempty,"),
    "uppercase sha256 ids": (r'_SHA256_ID_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")',
                             r'_SHA256_ID_RE = re.compile(r"\Asha256:[0-9a-fA-F]{64}\Z")'),
    "sha256 ids of any length": (r'_SHA256_ID_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")',
                                 r'_SHA256_ID_RE = re.compile(r"\Asha256:[0-9a-f]+\Z")'),
    "uppercase game ids": (r'_GAME_ID_RE = re.compile(r"\Ag-[0-9a-f]{16}\Z")', r'_GAME_ID_RE = re.compile(r"\Ag-[0-9a-fA-F]{16}\Z")'),
    "game ids of any length": (r'_GAME_ID_RE = re.compile(r"\Ag-[0-9a-f]{16}\Z")', r'_GAME_ID_RE = re.compile(r"\Ag-[0-9a-f]+\Z")'),
    "uppercase bot ids": (r'_BOT_ID_RE = re.compile(r"\A[0-9a-f]{64}\Z")', r'_BOT_ID_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")'),
    "bot ids of any length": (r'_BOT_ID_RE = re.compile(r"\A[0-9a-f]{64}\Z")', r'_BOT_ID_RE = re.compile(r"\A[0-9a-f]+\Z")'),
}


def _load(source: str) -> types.ModuleType:
    """Run ``source`` as a throwaway module of the arena package; the real ledger module is untouched."""
    spec = importlib.util.spec_from_loader("spellbench.arena._ledger_mutant", loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses reads the InitVar annotations through sys.modules
    try:
        exec(compile(source, "<ledger.py, mutated>", "exec"), module.__dict__)
    finally:
        del sys.modules[spec.name]
    return module


def _cases(test) -> list[dict]:
    """The keyword arguments of each case of a rule test (each parametrizes one name at most)."""
    marks = [mark for mark in getattr(test, "pytestmark", []) if mark.name == "parametrize"]
    return [{marks[0].args[0]: value} for value in marks[0].args[1]] if marks else [{}]


def _a_rule_test_fails(module: types.ModuleType) -> bool:
    """Run every case of RULE_TESTS with the module's parse_ledger, LedgerRow and Adjudication in place."""
    with pytest.MonkeyPatch.context() as patch:
        for name in ("parse_ledger", "LedgerRow", "Adjudication"):
            patch.setitem(globals(), name, getattr(module, name))
        for test in RULE_TESTS:
            for kwargs in _cases(test):
                try:
                    test(**kwargs)
                except (Exception, pytest.fail.Exception):
                    return True
    return False


def test_the_rule_tests_pass_on_an_unchanged_copy() -> None:
    """The control: the harness alone fails nothing, so a failure under a mutation is the mutation's."""
    assert not _a_rule_test_fails(_load(LEDGER_SOURCE))


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_each_mutation_fails_a_rule_test(name: str) -> None:
    old, new = MUTATIONS[name]
    assert LEDGER_SOURCE.count(old) == 1, f"update MUTATIONS: {name!r} no longer matches ledger.py exactly once"
    assert _a_rule_test_fails(_load(LEDGER_SOURCE.replace(old, new))), f"no rule test fails with: {name}"
