# Spellbench leaderboard: pauper-bo1

- Games: 1152 played, 1140 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 12)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 192 | 80 | 0 | 112 | 0 |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | a48 pauper-v2.0.0 | - | - | - | 383 | 193 | 0 | 190 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 382 | 163 | 0 | 219 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 375 | 238 | 0 | 137 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 189 | 89 | 0 | 100 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 190 | 100 | 0 | 90 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 190 | 84 | 0 | 106 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 190 | 100 | 0 | 90 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 189 | 93 | 0 | 96 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| gorge-legacy | a48 | 64 | 34 | 0 | 30 | 0.5312 | [0.4062, 0.6406] | 0.7905 |
| gorge-legacy | c12 | 64 | 30 | 0 | 34 | 0.4688 | [0.3594, 0.5938] | 0.7905 |
| gorge-legacy | g115 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3594] | 0.0004 |
| a48 | gorge-explore | 64 | 33 | 0 | 31 | 0.5156 | [0.3906, 0.6406] | 1.0000 |
| a48 | gorge-bot | 64 | 27 | 0 | 37 | 0.4219 | [0.2969, 0.5469] | 0.3593 |
| a48 | gorge-lethal-pressure | 64 | 38 | 0 | 26 | 0.5938 | [0.4844, 0.6875] | 0.1460 |
| a48 | gorge-ar8 | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8036 |
| a48 | gorge-blocks | 63 | 35 | 0 | 28 | 0.5484 | [0.4194, 0.6774] | 0.6476 |
| c12 | gorge-explore | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8036 |
| c12 | gorge-bot | 63 | 26 | 0 | 37 | 0.4194 | [0.3065, 0.5484] | 0.3018 |
| c12 | gorge-lethal-pressure | 63 | 28 | 0 | 35 | 0.4355 | [0.2903, 0.5806] | 0.5034 |
| c12 | gorge-ar8 | 64 | 17 | 0 | 47 | 0.2656 | [0.1562, 0.3906] | 0.0026 |
| c12 | gorge-blocks | 64 | 28 | 0 | 36 | 0.4375 | [0.2969, 0.5781] | 0.5034 |
| g115 | gorge-explore | 61 | 37 | 0 | 24 | 0.6000 | [0.4667, 0.7333] | 0.2379 |
| g115 | gorge-bot | 63 | 37 | 0 | 26 | 0.5968 | [0.4677, 0.7258] | 0.2632 |
| g115 | gorge-lethal-pressure | 63 | 40 | 0 | 23 | 0.6290 | [0.5323, 0.7258] | 0.0386 |
| g115 | gorge-ar8 | 62 | 43 | 0 | 19 | 0.7000 | [0.6000, 0.8000] | 0.0018 |
| g115 | gorge-blocks | 62 | 33 | 0 | 29 | 0.5333 | [0.4167, 0.6500] | 0.7905 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

skipped: no_rated_games

## By deck

### Affinity

skipped: fit_failed (reference_id has no games)

### Burn

skipped: fit_failed (reference_id has no games)

### CawGates

skipped: fit_failed (reference_id has no games)

### Elves

skipped: fit_failed (reference_id has no games)

### Faeries

skipped: fit_failed (reference_id has no games)

### Rally

skipped: fit_failed (reference_id has no games)

### Spy

skipped: fit_failed (reference_id has no games)

### Wildfire

skipped: fit_failed (reference_id has no games)

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
| a48 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 384 | 4 | 0.010 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 2 | 0.010 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 2 | 0.010 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 2 | 0.010 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 1 | 0.005 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 1 | 0.005 | 0 | 0.000 |

## Notes

- natural results and forfeits are rated (a forfeit is a loss for the forfeiting bot); truncated and halted games are excluded
- games/W/D/L count seat-games: a mirror game is two seat-games for the same bot
- the Bradley-Terry fit excludes mirror matchups
- prior: each rated matchup adds one virtual drawn game to the fit and every bootstrap refit
- ratings, matchup scores, intervals, and sign tests use complete seat-swapped pairs; W/D/L counts every rated game
- the paired bootstrap resamples seat-swapped pairs within each matchup; the two games of a pair have independent game secrets
- subratings per training-style tag are a filtered recomputation over the same ledger
- Elo display = rating * 400 / ln(10) + 1000; the anchor displays at exactly 1000
- fixed-point integers: rating_log_units_e6 = rating * 1e6, elo_milli = Elo * 1e3
- deck slices (when games use more than one deck pairing): each pairing's ratings recomputed from its games alone, with the same anchor and prior and stats seeds derived per slice
- halt and truncation rates count the games halted or truncated right after the bot's own selection, over every game it played
