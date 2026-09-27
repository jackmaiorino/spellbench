# Spellbench leaderboard: pauper-bo1

- Games: 192 played, 181 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 11)
- Anchor: uniform 1.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 0.820570 | 1142.5 | [1067.7, 1227.2] | 124 | 96 | 0 | 28 | 0 |
| 2 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 117 | 60 | 0 | 57 | 0 |
| 3 | first 1.0.0 | -0.888073 | 845.7 | [758.1, 930.5] | 121 | 25 | 0 | 96 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| first | heuristic | 64 | 12 | 0 | 52 | 0.1875 | [0.1094, 0.2812] | 0.0000 |
| first | uniform | 57 | 13 | 0 | 44 | 0.2407 | [0.1111, 0.3704] | 0.0026 |
| heuristic | uniform | 60 | 44 | 0 | 16 | 0.7414 | [0.6207, 0.8621] | 0.0013 |

## Subratings by training-style tag

### tag: baseline

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform 1.0.0 | 0.000000 | 1000.0 | 57 | 44 | 0 | 13 |
| first 1.0.0 | -1.123004 | 804.9 | 57 | 13 | 0 | 44 |

### tag: heuristic

skipped: fewer_than_two_bots

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 1.609438 | 1279.6 | [1176.9, 1460.0] | 16 | 14 | 0 | 2 | 0 |
| 2 | first 1.0.0 | 0.000000 | 1000.0 | [852.0, 1087.6] | 16 | 5 | 0 | 11 | 0 |
| 3 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 5 | 0 | 11 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | first 1.0.0 | 0.297936 | 1051.8 | [837.3, 1264.5] | 16 | 9 | 0 | 7 | 0 |
| 2 | heuristic 1.0.0 | 0.148968 | 1025.9 | [837.3, 1203.6] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 7 | 0 | 9 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 1.184329 | 1205.7 | [1205.7, 1205.7] | 12 | 11 | 0 | 1 | 0 |
| 2 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 11 | 8 | 0 | 3 | 0 |
| 3 | first 1.0.0 | -2.192750 | 619.1 | [619.1, 619.1] | 15 | 0 | 0 | 15 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 1.609438 | 1279.6 | [1078.5, 1492.2] | 16 | 15 | 0 | 1 | 0 |
| 2 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 10 | 3 | 0 | 7 | 0 |
| 3 | first 1.0.0 | -1.223775 | 787.4 | [586.3, 1000.0] | 10 | 0 | 0 | 10 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 2.206773 | 1383.4 | [1383.4, 1383.4] | 16 | 16 | 0 | 0 | 0 |
| 2 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 8 | 0 | 8 | 0 |
| 3 | first 1.0.0 | -2.206773 | 616.6 | [616.6, 616.6] | 16 | 0 | 0 | 16 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 0.571016 | 1099.2 | [967.7, 1266.2] | 16 | 13 | 0 | 3 | 0 |
| 2 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 10 | 0 | 6 | 0 |
| 3 | first 1.0.0 | -1.825458 | 682.9 | [540.0, 801.1] | 16 | 1 | 0 | 15 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 11 | 0 | 5 | 0 |
| 2 | heuristic 1.0.0 | -0.468206 | 918.7 | [775.7, 1026.8] | 16 | 8 | 0 | 8 | 0 |
| 3 | first 1.0.0 | -0.936412 | 837.3 | [650.1, 948.2] | 16 | 5 | 0 | 11 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 1.0.0 | 0.468206 | 1081.3 | [947.4, 1250.9] | 16 | 11 | 0 | 5 | 0 |
| 2 | uniform 1.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 8 | 0 | 8 | 0 |
| 3 | first 1.0.0 | -0.468206 | 918.7 | [688.1, 1113.4] | 16 | 5 | 0 | 11 | 0 |

## Notes

- natural results and forfeits are rated (a forfeit is a loss for the forfeiting bot); truncated and halted games are excluded
- games/W/D/L count seat-games: a mirror game is two seat-games for the same bot
- the Bradley-Terry fit excludes mirror matchups
- prior: each rated matchup adds one virtual drawn game to the fit and every bootstrap refit
- ratings, matchup scores, intervals, and sign tests use complete seat-swapped pairs; W/D/L counts every rated game
- the paired bootstrap resamples seat-swapped pairs (the CRN unit) within each matchup
- subratings per training-style tag are a filtered recomputation over the same ledger
- Elo display = rating * 400 / ln(10) + 1000; the anchor displays at exactly 1000
- fixed-point integers: rating_log_units_e6 = rating * 1e6, elo_milli = Elo * 1e3
- deck slices (when games use more than one deck pairing): each pairing's ratings recomputed from its games alone, with the same anchor and prior and stats seeds derived per slice
