# Spellbench leaderboard: pauper-bo1

- Games: 384 played, 384 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 128 | 54 | 0 | 74 | 0 |
| - | oh1-r2s1-b128 pauper-v2.0.0 | - | - | - | 192 | 141 | 0 | 51 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 128 | 25 | 0 | 103 | 0 |
| - | a48 pauper-v2.0.0 | - | - | - | 128 | 28 | 0 | 100 | 0 |
| - | r2-b20 pauper-v2.0.0 | - | - | - | 192 | 136 | 0 | 56 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| g115 | oh1-r2s1-b128 | 64 | 27 | 0 | 37 | 0.4219 | [0.2969, 0.5469] | 0.3593 |
| g115 | r2-b20 | 64 | 27 | 0 | 37 | 0.4219 | [0.3125, 0.5312] | 0.2668 |
| oh1-r2s1-b128 | c12 | 64 | 50 | 0 | 14 | 0.7812 | [0.6875, 0.8750] | 0.0000 |
| oh1-r2s1-b128 | a48 | 64 | 54 | 0 | 10 | 0.8438 | [0.7500, 0.9219] | 0.0000 |
| c12 | r2-b20 | 64 | 11 | 0 | 53 | 0.1719 | [0.0938, 0.2656] | 0.0000 |
| a48 | r2-b20 | 64 | 18 | 0 | 46 | 0.2812 | [0.1875, 0.3906] | 0.0013 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh1-r2s1-b128 pauper-v2.0.0 | 0.377148 | 1065.5 | 192 | 141 | 0 | 51 |
| r2-b20 pauper-v2.0.0 | 0.243845 | 1042.4 | 192 | 136 | 0 | 56 |
| g115 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 54 | 0 | 74 |
| a48 pauper-v2.0.0 | -0.938558 | 837.0 | 128 | 28 | 0 | 100 |
| c12 pauper-v2.0.0 | -1.077130 | 812.9 | 128 | 25 | 0 | 103 |

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
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
| g115 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| oh1-r2s1-b128 pauper-v2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| r2-b20 pauper-v2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |

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
