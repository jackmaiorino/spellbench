# Spellbench leaderboard: pauper-bo1

- Games: 384 played, 379 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 5)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | oh2-r2s1-b512 pauper-v2.0.0 | - | - | - | 127 | 28 | 0 | 99 | 0 |
| - | heuristic 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | oh2-r2s1-b512-argmax pauper-v2.0.0 | - | - | - | 128 | 30 | 0 | 98 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 124 | 31 | 0 | 93 | 0 |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | chains-a-c4-u1048576 pauper-v2.0.0 | - | - | - | 379 | 290 | 0 | 89 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | chains-a-c4-u1048576 | 127 | 28 | 0 | 99 | 0.2222 | [0.1508, 0.3016] | 0.0000 |
| oh2-r2s1-b512-argmax | chains-a-c4-u1048576 | 128 | 30 | 0 | 98 | 0.2344 | [0.1641, 0.3047] | 0.0000 |
| g115 | chains-a-c4-u1048576 | 124 | 31 | 0 | 93 | 0.2541 | [0.1721, 0.3361] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 pauper-v2.0.0 | 1.240152 | 1215.4 | 379 | 290 | 0 | 89 |
| g115 pauper-v2.0.0 | 0.173801 | 1030.2 | 124 | 31 | 0 | 93 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 0.067823 | 1011.8 | 128 | 30 | 0 | 98 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 127 | 28 | 0 | 99 |

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
| oh2-r2s1-b512 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 0 | 0 | - | 0 | - |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| g115 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
| chains-a-c4-u1048576 pauper-v2.0.0 | 384 | 5 | 0.013 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 0 | 0 | - | 0 | - |

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
