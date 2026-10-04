# Spellbench leaderboard: standard-2022-25-bo1

- Games: 43 played, 43 rated (forfeits rated as losses: 2; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | llm-gpt-6-luna 0.1.0 | 2.164438 | 1376.0 | [1240.8, 1590.7] | 27 | 23 | 0 | 4 | 2 |
| 2 | heuristic 2.0.0 | 0.805853 | 1140.0 | [1031.8, 1277.2] | 27 | 14 | 0 | 13 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 32 | 6 | 0 | 26 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| heuristic | uniform | 16 | 11 | 0 | 5 | 0.6875 | [0.5625, 0.8750] | 0.2500 |
| heuristic | llm-gpt-6-luna | 11 | 3 | 0 | 8 | 0.2000 | [0.0000, 0.4000] | 0.2500 |
| uniform | llm-gpt-6-luna | 16 | 1 | 0 | 15 | 0.0625 | [0.0000, 0.1875] | 0.0156 |

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
| 1 | llm-gpt-6-luna 0.1.0 | 2.510763 | 1436.2 | [1319.3, 1616.1] | 14 | 13 | 0 | 1 | 0 |
| 2 | heuristic 2.0.0 | 1.055208 | 1183.3 | [1040.6, 1418.9] | 14 | 7 | 0 | 7 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 2 | 0 | 14 | 0 |

### Standard16-UB

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | llm-gpt-6-luna 0.1.0 | 1.501724 | 1260.9 | [1101.4, 1492.2] | 13 | 10 | 0 | 3 | 2 |
| 2 | heuristic 2.0.0 | 0.517713 | 1089.9 | [983.4, 1239.9] | 13 | 7 | 0 | 6 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 4 | 0 | 12 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| llm-gpt-6-luna 0.1.0 | 27 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 27 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 32 | 0 | 0.000 | 0 | 0.000 |

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
