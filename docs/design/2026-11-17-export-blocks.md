# Export blocks: a second set of evaluation conditions for some blocks of a ladder

2026-11-17. Implemented in `arena/config.py`, `arena/snapshot.py`, `bench/definition.py`, `bench/panel.py`; tests in `python/tests/test_export_blocks.py`.

## Problem

`pauper-ladder-v3` plays without the information-set export, because no rated bot there reads it and its exporter used to halt (mtg-kernel#713). The search entrant needs the export. Turning it on for the whole board would be a new evaluation: every published block would have to be played again.

## Rule

A ladder definition may name `export_blocks`: a list of bots and, for the blocks of those bots only, another engine command, extension list, engine inputs and engine identity, with their own `evaluation_version`. Every other block keeps the board's own conditions and version.

```json
"export_blocks": {
  "evaluation_version": "pauper-ladder-v3.1.0",
  "bots": ["oh2-r2s1-b512-s4a-16k-k4"],
  "engine": {"command": ["..."]},
  "extensions": ["x_kernel_flat_v4", "x_public_history_v1", "x_kernel_infoset_v1"],
  "evaluation_engine_inputs": ["..."],
  "evaluation_engine_identity": "written by bench prepare"
}
```

- A block is of the export form when one of its two bots is listed, of the base form otherwise. Decks, pairing, clock, limits, validity unit and anchor are shared.
- A run is one form. `Benchmark.tournament_config` writes a schedule of export blocks with the export conditions at the top level of the run's config, and a schedule of other blocks with the board's own. Neither config carries `export_blocks`, so a run of either form is an ordinary run and its contract is compared as before. A base-form run therefore records the board's own version.
- `TournamentConfig.as_form` gives one form of a board's whole config: that form's blocks under that form's conditions. The whole config itself is refused by `schedule` and `preflight`, so nothing plays an export block under the base conditions or a base block under the export conditions.
- A schedule that mixes the forms is refused by `bench prepare` and wherever the definition is loaded, which is before `bench commit` makes a commitment. Defer the entrants of one form, run the other, prepare again.
- A source run supplies the block of a matchup only when the run's contract equals the contract of that matchup's form (`snapshot.form_contracts`). A base-form run never supplies an export block, and the reverse.
- The base form's contract does not change when a board gains export blocks. Its published blocks stay selected without a replay, and a base block that failed the validity unit stays barred. A failed export-form run bars its own blocks the same way.

## Snapshots

A snapshot without an export-form block is written as before, to the byte (schema `spellbench-snapshot/v1`).

A snapshot that holds blocks of both forms has schema `spellbench-snapshot/v2`. Its top level is the base form's contract and engine facts, key for key as in v1. One added object, `export_blocks`, carries the export form's `contract`, `engine`, `engine_profile`, `information_rules`, `engine_files` and the `matchups` played under it. The protocol and the deck domain must agree across the forms. `leaderboard.json` gains `evaluation.export_blocks` and a note that says which blocks were played under which version; the board page prints it.

Validation is unchanged in kind: the whole snapshot is recomputed from its source runs and compared byte for byte.

## What a reader should know

The ratings of a two-form snapshot are one fit over blocks of both forms. That is sound only if the export form changes nothing for the bots that do not read the export; the board's receipt holds that evidence (published games replayed under the export conditions, compared row by row).
