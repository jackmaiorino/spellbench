# Spellbench leaderboard: standard-2022-25-bo1

- Games: 17 played, 17 rated (forfeits rated as losses: 1; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.021651 | 1177.5 | [1041.1, 1405.7] | 16 | 12 | 0 | 4 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 17 | 5 | 0 | 12 | 0 |
| - | llm-gpt-6-luna 0.1.0 | - | - | - | 1 | 0 | 0 | 1 | 1 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| heuristic | uniform | 16 | 12 | 0 | 4 | 0.7500 | [0.5625, 0.9375] | 0.1250 |
| llm-gpt-6-luna | uniform | 1 | 0 | 0 | 1 | - | - | - |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: fewer_than_two_bots

### tag: hosted-llm

skipped: fewer_than_two_bots

## By deck

### Standard16-RG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.955511 | 1166.0 | [1000.0, 1492.2] | 8 | 6 | 0 | 2 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 9 | 3 | 0 | 6 | 0 |
| - | llm-gpt-6-luna 0.1.0 | - | - | - | 1 | 0 | 0 | 1 | 1 |

### Standard16-UB

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.955511 | 1166.0 | [1000.0, 1492.2] | 8 | 6 | 0 | 2 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 8 | 2 | 0 | 6 | 0 |
| - | llm-gpt-6-luna 0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| heuristic 2.0.0 | 16 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 17 | 0 | 0.000 | 0 | 0.000 |
| llm-gpt-6-luna 0.1.0 | 1 | 0 | 0.000 | 0 | 0.000 |

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
