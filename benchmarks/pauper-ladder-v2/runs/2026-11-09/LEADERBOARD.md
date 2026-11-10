# Spellbench leaderboard: pauper-bo1

- Games: 384 played, 383 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 1)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | oh2-r2s1-b512 pauper-v2.0.0 | - | - | - | 128 | 69 | 0 | 59 | 0 |
| - | heuristic 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | oh2-r2s1-b512-argmax pauper-v2.0.0 | - | - | - | 127 | 68 | 0 | 59 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 128 | 59 | 0 | 69 | 0 |
| - | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | - | - | - | 383 | 187 | 0 | 196 | 0 |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 69 | 0 | 59 | 0.5391 | [0.4453, 0.6250] | 0.5114 |
| oh2-r2s1-b512-argmax | oh2-r2s1-b512-s4a-16k-k4 | 127 | 68 | 0 | 59 | 0.5397 | [0.4444, 0.6429] | 0.5224 |
| g115 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 59 | 0 | 69 | 0.4609 | [0.3594, 0.5547] | 0.5327 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 0.002457 | 1000.4 | 127 | 68 | 0 | 59 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 69 | 0 | 59 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | -0.155350 | 973.0 | 383 | 187 | 0 | 196 |
| g115 pauper-v2.0.0 | -0.310701 | 946.0 | 128 | 59 | 0 | 69 |

### tag: search

skipped: fewer_than_two_bots

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
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 384 | 1 | 0.003 | 0 | 0.000 |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
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
