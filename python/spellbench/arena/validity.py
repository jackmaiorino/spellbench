"""The validity unit of a board, computed from a run's schedule and ledger.

A board may name a validity unit in its definition (``benchmark.json`` field ``validity``, carried into the run's
``config.json``). A run of such a board is valid only when its games ended the way the unit requires. Every count
has a scheduled denominator, taken from ``schedule(config, run_secret)``, never from the ledger rows: a game that
was scheduled and not played counts against the run like a halted one.

The unit ``spellbench-validity/v1`` holds four thresholds, each in thousandths:

- ``block_natural_permille``: per block (one scheduled matchup of the run), the games that ended ``natural`` must
  be at least ``ceil(scheduled * permille / 1000)``. A forfeit, a halt and a truncation are not natural.
- ``block_complete_pairs_permille``: per block, the complete seat-swapped pairs (both games rated, the sample the
  rating fit and its bootstrap use) must be at least ``ceil(scheduled_pairs * permille / 1000)``. A halted game
  takes its pair partner out of the fit, so a block can meet the natural count and still rate too few games.
- ``rung_natural_permille``: per bot of the schedule (on a ladder, each rung and each entrant), the natural games
  over all its scheduled games in the run, with the same rounding.
- ``pairing_natural_permille``: per ordered deck pairing (the deck of seat ``p0``, then the deck of seat ``p1``),
  the natural games over every block of the run. The games a pairing may lose are
  ``max(1, scheduled - ceil(scheduled * permille / 1000))``: one game that is not natural never fails a pairing by
  itself (also at 1000), and a pairing that stops ending naturally fails the run even when every block passes.

:func:`evaluate_composition` applies the same unit to a rating composed from blocks of several runs: a snapshot is
published only when the composed sample passes too, and its manifest carries that record.

:func:`evaluate` returns the record a manifest publishes under ``validity``: the unit, the verdict, the three
tables, one line per failed threshold, and, for a failing run, the generated exclusion record. A run that fails is
still published in full; it is not rated (``manifest.is_rated``), its leaderboard withholds every rating, and
``bench compose`` and the site leave it out (:func:`run_exclusion`). ``bench prepare`` does not schedule its
matchups again under the same evaluation. Nothing here reads outcomes: who won never enters the verdict. A forfeit
is not natural, so a bot that forfeits more than the unit allows fails the run for both bots of the block.

Configs without the field get no record, so runs of earlier boards keep their bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from . import store
from .config import VALIDITY_UNIT_V1 as UNIT_V1
from .config import DeckSpec, TournamentConfig
from .manifest import VALIDITY_KEY as MANIFEST_KEY

if TYPE_CHECKING:  # annotations only: the schedule module starts engine and bot processes
    from .ledger import LedgerRow
    from .schedule import GameContext


def at_least(scheduled: int, permille: int) -> int:
    """``ceil(scheduled * permille / 1000)``, in integers."""
    return -(-scheduled * permille // 1000)


def pairing_minimum(scheduled: int, permille: int) -> int:
    """The natural games an ordered deck pairing needs: it may lose its rounded share, and always one game."""
    return scheduled - max(1, scheduled - at_least(scheduled, permille))


def _deck_label(deck: DeckSpec) -> str:
    return deck.catalog_id if deck.catalog_id is not None else str(deck.name)


@dataclass(frozen=True)
class _Game:
    """One scheduled game as the thresholds read it."""

    block: Any  # the key of its block
    pair: int  # its pair within the block
    names: tuple[str, str]  # the bots at p0 and p1
    decks: tuple[str, str]  # the deck labels at p0 and p1
    ref: Any  # how a pairing's ``not_natural`` list names the game
    row: Any  # its ledger row, or None when it was not played


def _scheduled(contexts: Sequence[GameContext], rows: Sequence[LedgerRow], *, block: Any, ref: Any) -> list[_Game]:
    """Each scheduled game of ``contexts`` with the ledger row of its ``game_index``; ``block`` and ``ref`` map a
    context to its block key and its reference. Rows outside ``contexts`` count for nothing."""
    played = {row.game_index: row for row in rows}
    return [_Game(block=block(context), pair=context.pair_index,
                  names=(context.seat_specs[0][1].name, context.seat_specs[1][1].name),
                  decks=(_deck_label(context.decks[0]), _deck_label(context.decks[1])),
                  ref=ref(context), row=played.get(context.game_index)) for context in contexts]


def _judge(config: TournamentConfig, games: Sequence[_Game], blocks: dict[Any, dict[str, Any]],
           labels: dict[Any, str]) -> dict[str, Any]:
    """The unit, the verdict, the three tables and the failed thresholds of ``games``. ``blocks`` holds each
    block's leading fields, in table order, and ``labels`` how a failure line names it."""
    unit = config.validity
    assert unit is not None
    pairs: dict[tuple[Any, int], list[bool]] = {}
    rungs: dict[str, dict[str, Any]] = {}
    pairings: dict[tuple[str, str], dict[str, Any]] = {}
    for game in games:
        natural = game.row is not None and game.row.classification == "natural"
        block = blocks[game.block]
        if "scheduled" not in block:
            # The two bots in the order of the block's first game (seat p0, then p1).
            block.update(bots=list(game.names), scheduled=0, played=0, natural=0, forfeit=0, halted=0, truncated=0,
                         missing=0)
        block["scheduled"] += 1
        if game.row is None:
            block["missing"] += 1
        else:
            block["played"] += 1
            block[game.row.classification] += 1
        pairs.setdefault((game.block, game.pair), []).append(game.row is not None and game.row.rated)
        for name in dict.fromkeys(game.names):  # a self-play game is one scheduled game of its bot
            rung = rungs.setdefault(name, {"name": name, "scheduled": 0, "natural": 0})
            rung["scheduled"] += 1
            rung["natural"] += natural
        pairing = pairings.setdefault(game.decks, {"decks": list(game.decks), "scheduled": 0, "natural": 0,
                                                   "not_natural": []})
        pairing["scheduled"] += 1
        if natural:
            pairing["natural"] += 1
        else:
            pairing["not_natural"].append(game.ref)

    failures: list[str] = []
    block_rows = []
    for key, block in blocks.items():
        scheduled_pairs = sum(1 for pair in pairs if pair[0] == key)
        complete = sum(1 for pair, rated in pairs.items() if pair[0] == key and len(rated) == 2 and all(rated))
        block["natural_min"] = at_least(block["scheduled"], unit.block_natural_permille)
        block["pairs_scheduled"] = scheduled_pairs
        block["complete_pairs"] = complete
        block["complete_pairs_min"] = at_least(scheduled_pairs, unit.block_complete_pairs_permille)
        label = f"{labels[key]} ({block['bots'][0]} vs {block['bots'][1]})"
        if block["natural"] < block["natural_min"]:
            failures.append(f"{label}: {block['natural']} of {block['scheduled']} scheduled games ended natural, "
                            f"needs {block['natural_min']}")
        if complete < block["complete_pairs_min"]:
            failures.append(f"{label}: {complete} of {scheduled_pairs} scheduled pairs are complete, "
                            f"needs {block['complete_pairs_min']}")
        block["pass"] = block["natural"] >= block["natural_min"] and complete >= block["complete_pairs_min"]
        block_rows.append(block)
    rung_rows = []
    for spec in config.bots:  # config order; a bot the schedule leaves out has no row
        rung = rungs.get(spec.name)
        if rung is None:
            continue
        rung["natural_min"] = at_least(rung["scheduled"], unit.rung_natural_permille)
        rung["pass"] = rung["natural"] >= rung["natural_min"]
        if not rung["pass"]:
            failures.append(f"bot {rung['name']}: {rung['natural']} of {rung['scheduled']} scheduled games ended "
                            f"natural, needs {rung['natural_min']}")
        rung_rows.append(rung)
    pairing_rows = []
    for pairing in pairings.values():  # the schedule's first-use order
        pairing["natural_min"] = pairing_minimum(pairing["scheduled"], unit.pairing_natural_permille)
        pairing["pass"] = pairing["natural"] >= pairing["natural_min"]
        if not pairing["pass"]:
            failures.append(f"deck pairing {pairing['decks'][0]} (p0) vs {pairing['decks'][1]} (p1): "
                            f"{pairing['natural']} of {pairing['scheduled']} scheduled games ended natural, "
                            f"needs {pairing['natural_min']}")
        pairing_rows.append(pairing)
    return {
        "unit": unit.to_json(),
        "verdict": "fail" if failures else "pass",
        "blocks": block_rows,
        "rungs": rung_rows,
        "pairings": pairing_rows,
        "failures": failures,
    }


def evaluate(
    config: TournamentConfig, contexts: Sequence[GameContext], rows: Sequence[LedgerRow], *, run_label: str | None
) -> dict[str, Any] | None:
    """The manifest's ``validity`` record for ``rows`` under ``config``'s unit, or None when it names none.

    ``contexts`` is ``schedule(config, run_secret)``: every denominator comes from it. A ledger row counts for the
    scheduled game with its ``game_index``; rows outside the schedule count for nothing (the validator reports
    them). ``run_label`` names the run in a failing run's exclusion record.
    """
    if config.validity is None:
        return None
    games = _scheduled(contexts, rows, block=lambda context: context.matchup_index,
                       ref=lambda context: context.game_index)
    indexes = sorted({game.block for game in games})
    record = _judge(config, games, {index: {"matchup_index": index} for index in indexes},
                    {index: f"block {index}" for index in indexes})
    record["exclusion"] = None
    if record["failures"]:
        record["exclusion"] = {"run": run_label, "reason": exclusion_reason(record["failures"])}
    return record


def evaluate_composition(
    config: TournamentConfig, parts: Sequence[tuple[str, Sequence[GameContext], Sequence[LedgerRow]]]
) -> dict[str, Any] | None:
    """The validity record of a rating composed from blocks of several runs, or None when ``config`` names no unit.

    Each part is one selected block: its run's label, that block's scheduled games (from the run's own schedule)
    and the run's ledger rows. Every run passed the unit by itself, but the thresholds hold for the sample a
    rating is fitted from: one lost game of the same deck pairing in each of several small runs passes each run
    and can still fail the pairing over the whole. A snapshot is published only when this record passes.
    """
    if config.validity is None:
        return None
    games: list[_Game] = []
    blocks: dict[Any, dict[str, Any]] = {}
    labels: dict[Any, str] = {}
    for label, contexts, rows in parts:
        for context in contexts:
            key = (label, context.matchup_index)
            blocks.setdefault(key, {"run": label, "matchup_index": context.matchup_index})
            labels.setdefault(key, f"run {label} block {context.matchup_index}")
        games += _scheduled(contexts, rows, block=lambda context, label=label: (label, context.matchup_index),
                            ref=lambda context, label=label: [label, context.game_index])
    return _judge(config, games, blocks, labels)


# The failed thresholds an exclusion reason spells out; the record's ``failures`` lists every one.
REASON_LINES = 8


def exclusion_reason(failures: Sequence[str]) -> str:
    """The generated reason of a failing run's exclusion record: the unit and the first failed thresholds."""
    shown = list(failures[:REASON_LINES])
    if len(failures) > REASON_LINES:
        shown.append(f"and {len(failures) - REASON_LINES} more")
    return f"failed the board's validity unit ({UNIT_V1}): " + "; ".join(shown)


def withheld_reason(record: dict[str, Any] | None) -> str | None:
    """Why a run's leaderboard withholds its ratings: the exclusion reason of a failing record, else None."""
    if record is None or record["verdict"] != "fail":
        return None
    return record["exclusion"]["reason"]


def verdict(record: Any) -> str | None:
    """A validity record's verdict, or None for a run without one."""
    return record.get("verdict") if isinstance(record, dict) else None


def run_exclusion(run_dir: Path) -> tuple[str, str] | None:
    """(run name, reason) when the published run in ``run_dir`` failed its board's validity unit, else None.

    Read from the run's own manifest, so the exclusion needs no hand-typed entry: a failing run is left out of
    preparation, snapshots and the board by its record alone. An unreadable manifest excludes nothing here; the
    validator reports it.
    """
    try:
        manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    except store.StoreError:
        return None
    record = manifest.get(MANIFEST_KEY) if isinstance(manifest, dict) else None
    if verdict(record) != "fail":
        return None
    exclusion = record.get("exclusion")
    reason = exclusion.get("reason") if isinstance(exclusion, dict) else None
    return run_dir.name, reason if type(reason) is str and reason else exclusion_reason(())
