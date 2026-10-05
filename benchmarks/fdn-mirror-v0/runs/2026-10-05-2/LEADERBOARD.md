# Spellbench leaderboard: fdn-limited-bo1

- Games: 384 played, 384 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.224066 | 1212.6 | [1154.8, 1281.3] | 256 | 227 | 0 | 29 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 256 | 155 | 0 | 101 | 0 |
| 3 | first 2.0.0 | -4.003788 | 304.5 | [105.7, 433.9] | 256 | 2 | 0 | 254 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| first | heuristic | 128 | 1 | 0 | 127 | 0.0078 | [0.0000, 0.0234] | 0.0000 |
| first | uniform | 128 | 1 | 0 | 127 | 0.0078 | [0.0000, 0.0234] | 0.0000 |
| heuristic | uniform | 128 | 100 | 0 | 28 | 0.7812 | [0.7109, 0.8438] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform 2.0.0 | 0.000000 | 1000.0 | 128 | 127 | 0 | 1 |
| first 2.0.0 | -4.442651 | 228.2 | 128 | 1 | 0 | 127 |

### tag: heuristic

skipped: fewer_than_two_bots

## By deck

### FDN_top_02581_UR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.851839 | 1148.0 | [1000.0, 1383.4] | 16 | 14 | 0 | 2 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 10 | 0 | 6 | 0 |
| 3 | first 2.0.0 | -2.486289 | 568.1 | [507.8, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_02810_UR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 2.206773 | 1383.4 | [1383.4, 1383.4] | 16 | 16 | 0 | 0 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 8 | 0 | 8 | 0 |
| 3 | first 2.0.0 | -2.206773 | 616.6 | [616.6, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_04752_WG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.407709 | 1070.8 | [1000.0, 1242.0] | 16 | 13 | 0 | 3 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 11 | 0 | 5 | 0 |
| 3 | first 2.0.0 | -2.647741 | 540.0 | [507.8, 593.3] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_05840_UGpR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 12 | 0 | 4 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 12 | 0 | 4 | 0 |
| 3 | first 2.0.0 | -2.833213 | 507.8 | [507.8, 507.8] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_13096_WU

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.000304 | 1173.8 | [1032.3, 1406.7] | 16 | 14 | 0 | 2 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | first 2.0.0 | -1.674911 | 709.0 | [540.0, 874.4] | 16 | 1 | 0 | 15 | 0 |

### FDN_top_13950_BR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.407709 | 1070.8 | [852.0, 1383.4] | 16 | 13 | 0 | 3 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 11 | 0 | 5 | 0 |
| 3 | first 2.0.0 | -2.647741 | 540.0 | [420.1, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_15834_WBpU

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.407709 | 1070.8 | [1000.0, 1242.0] | 16 | 13 | 0 | 3 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 11 | 0 | 5 | 0 |
| 3 | first 2.0.0 | -2.647741 | 540.0 | [507.8, 593.3] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_16798_UB

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.407709 | 1070.8 | [1000.0, 1242.0] | 16 | 13 | 0 | 3 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 11 | 0 | 5 | 0 |
| 3 | first 2.0.0 | -2.647741 | 540.0 | [507.8, 593.3] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_17463_BG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.393247 | 1242.0 | [1070.8, 1383.4] | 16 | 15 | 0 | 1 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | first 2.0.0 | -2.341062 | 593.3 | [540.0, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_20196_GpUR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.393247 | 1242.0 | [1070.8, 1383.4] | 16 | 15 | 0 | 1 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | first 2.0.0 | -2.341062 | 593.3 | [540.0, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_20626_WG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.393247 | 1242.0 | [1070.8, 1383.4] | 16 | 15 | 0 | 1 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | first 2.0.0 | -2.341062 | 593.3 | [540.0, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_21511_WUR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.000304 | 1173.8 | [1032.3, 1383.4] | 16 | 14 | 0 | 2 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | first 2.0.0 | -1.674911 | 709.0 | [568.1, 823.1] | 16 | 1 | 0 | 15 | 0 |

### FDN_top_23736_U

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 1.393247 | 1242.0 | [1070.8, 1383.4] | 16 | 15 | 0 | 1 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | first 2.0.0 | -2.341062 | 593.3 | [540.0, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_24789_BGpW

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.407709 | 1070.8 | [1000.0, 1242.0] | 16 | 13 | 0 | 3 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 11 | 0 | 5 | 0 |
| 3 | first 2.0.0 | -2.647741 | 540.0 | [507.8, 593.3] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_26941_WB

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 2.206773 | 1383.4 | [1383.4, 1383.4] | 16 | 16 | 0 | 0 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 8 | 0 | 8 | 0 |
| 3 | first 2.0.0 | -2.206773 | 616.6 | [616.6, 616.6] | 16 | 0 | 0 | 16 | 0 |

### FDN_top_28740_RG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 2.206773 | 1383.4 | [1383.4, 1383.4] | 16 | 16 | 0 | 0 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 8 | 0 | 8 | 0 |
| 3 | first 2.0.0 | -2.206773 | 616.6 | [616.6, 616.6] | 16 | 0 | 0 | 16 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| heuristic 2.0.0 | 256 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 256 | 0 | 0.000 | 0 | 0.000 |
| first 2.0.0 | 256 | 0 | 0.000 | 0 | 0.000 |

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
