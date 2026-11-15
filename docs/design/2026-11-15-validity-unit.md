# The validity unit, enforced by code (2026-11-15)

## Why

Until now a rated ladder run was judged by hand from a post-run table: every 128-game block needs at least 125
natural endings and every rung at least 97%. A failing run was excluded by typing an `excluded_runs` entry. Three
holes:

1. The fit and its bootstrap use complete seat-swapped pairs only, so a halted game also removes its partner. A
   block with 125 natural games can rate 122.
2. Failures concentrate. A deck pairing that halts every time costs each block one pair, so every block and every
   rung passes while the board silently lacks that pairing.
3. Counting from ledger rows lets a game that was never played pass.

## The unit

`validity` in `benchmark.json` (carried into each run's `config.json`):

```json
{"unit": "spellbench-validity/v1", "block_natural_permille": 970, "block_complete_pairs_permille": 970,
 "rung_natural_permille": 970, "pairing_natural_permille": 900}
```

Every denominator is the scheduled count from `schedule(config, run_secret)`. A forfeit, a halt, a truncation and
a game that was not played all count against "natural".

| Rule | Per | Minimum | 128-game block, 18-block run |
|---|---|---|---|
| natural games | block | `ceil(scheduled * 970 / 1000)` | 125 of 128 |
| complete pairs (both games rated) | block | `ceil(pairs * 970 / 1000)` | 63 of 64 (126 games in the fit) |
| natural games | bot, over its blocks | `ceil(scheduled * 970 / 1000)` | 373 of 384 for three blocks |
| natural games | ordered deck pairing, over the run | `scheduled - max(1, scheduled - ceil(scheduled * 900 / 1000))` | 33 of 36 |

The pairing rule always allows one game, so a single halt cannot fail a small run (an entrant-only run schedules
six games per pairing and needs five).

## Arithmetic from the published ledgers

Reproduced by `python/tests/test_arena_validity.py` (the unit is applied to the ledgers there only to read what it
would say; the published runs name no unit and are unchanged).

| Run | Not natural | Worst block (natural, complete pairs) | Worst ordered pairing | Under this unit |
|---|---|---|---|---|
| pauper-ladder-v2 2026-11-08 | 5 of 1,920 | 125, 61 (122 games rated) | Faeries mirror 235 of 240 | fail: pairs |
| pauper-ladder-v2 2026-11-09 | 1 of 384 | 127, 63 | Faeries mirror 47 of 48 | pass |
| pauper-ladder-v2 2026-11-14 (excluded by hand) | 5 of 384 | 124, 61 | Faeries mirror 43 of 48 (89.6%) | fail: natural, pairs, one rung, pairing |
| pauper-grid-v1 2026-11-08 | 6 of 1,920 | 126, 62 | Faeries then Rally 27 of 30 (90.0%) | fail: pairs |

- Block natural: 97% of 128 is 124.16, so 125. This is the number the hand rule already used.
- Block pairs: the same 97% on the sample the rating uses. 97% of 64 pairs is 62.08, so 63: at most one broken
  pair, 126 of 128 games in the fit. 62 pairs would be 124 games, 96.9%, under the unit's own share. The published
  block at 125 natural and 61 pairs is the case this rule exists for.
- Pairing: 90%. The worst pairing of a run that was published as valid kept 27 of 30 (90.0%); the pairing of the
  run that was excluded kept 43 of 48 (89.6%). 90% is the round threshold between them. In the worst case (every
  lost game in a different pair) it keeps 15 of a pairing's 18 pairs.
- A pairing that never ends naturally (0 of 36) passes every block (126 natural, 63 pairs) and every rung, and
  fails this rule.

Every one of the 17 games above came from two faults that are fixed: 11 paid ninjutsu activations
(`paid_ninjutsu_repair` in `benchmarks/pauper-ladder-v2/ENGINE-AUDITS.json`) and 6 projection errors (reason
`engine_contract_failure:ProjectionError` in the grid ledger, issue 288). On the repaired engine the unrated board
pass recorded in that file ended 1,920 of 1,920 games naturally, a halt rate under 0.16% at 95% confidence.
The price of the pair rule is a false failure when two unrelated halts land in different pairs of one block: for a
per-game halt rate p that is about 8,064 p squared per block, so under 1% per 18-block run at p = 0.02%, about 15% at
p = 0.1%. A run that fails for that reason is still an honest record; the unrated pass before a commitment shows
the rate first.

The thresholds are fixed in a board's definition before its first game and are part of every run's config and of
the snapshot contract: they are chosen here once, from runs that are already published, and are not re-derived
from a later run. Forfeits count against "natural" as ruled, so a bot that forfeits more than the unit allows
fails the run for both bots of that block; its games are a record, not a low rating.

## Runs of different sizes, and composed ratings

The pairing rule is judged per run on that run's scheduled games, and always allows one game, so it is weak on a
small run: a single block schedules two games per ordered pairing (one may be lost), an entrant-only run of three
blocks six (five needed). A rating is fitted from blocks of several runs, so `bench compose` applies the whole unit
again to the blocks it selects, with their scheduled denominators, and publishes the snapshot only if that
composed sample passes; the snapshot's manifest carries the composed record. Three one-block runs that each lose
one game of the same pairing pass one by one and fail together (3 of 6, 5 needed).

## What a failing run publishes

- `manifest.json` gains `validity`: the unit, the verdict, per-block, per-bot and per-pairing tables, one line per
  failed threshold, and the generated exclusion record (`run`, `reason`). The validator recomputes all of it.
- `run.rated` is false: a rated run must pass its board's unit.
- The run's own `leaderboard.json` and `LEADERBOARD.md` have status `withheld`: games, W/D/L and matchup records
  (observed scores and their intervals), no rating, rating interval, rank, subrating, deck slice or deck grid.
- `bench compose` and the site leave the run out by its own record; `excluded_runs` needs no entry. A snapshot
  can never cite it, rated or unrated.
- `bench prepare` refuses to schedule a matchup again that a committed run played under the same evaluation
  conditions and failed. Rating again needs a changed evaluation (a new `evaluation_version`, engine or bot),
  which is a reviewed change of the definition, so a later attempt cannot quietly stand in for a failed one.
- The secret is revealed and every file stays published, as for any run.

## What does not change

A config without `validity` has no record and no new behaviour: the manifest key, the config field and the
snapshot contract field are written only when a board names a unit. Every published run and snapshot validates
and recomputes byte for byte as before.
