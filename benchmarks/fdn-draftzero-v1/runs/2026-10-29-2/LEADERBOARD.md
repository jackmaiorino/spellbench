# Spellbench leaderboard: fdn-limited-bo1

- Games: 384 played, 384 rated (forfeits rated as losses: 20; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 1.858169 | 1322.8 | [1257.6, 1402.2] | 256 | 200 | 0 | 56 | 20 |
| 2 | heuristic 2.0.0 | 1.043723 | 1181.3 | [1125.7, 1249.8] | 256 | 134 | 0 | 122 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 256 | 50 | 0 | 206 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| draftzero-fdn-gnn-100-fair | heuristic | 128 | 91 | 0 | 37 | 0.7109 | [0.6250, 0.7969] | 0.0000 |
| draftzero-fdn-gnn-100-fair | uniform | 128 | 109 | 0 | 19 | 0.8516 | [0.7812, 0.9062] | 0.0000 |
| heuristic | uniform | 128 | 97 | 0 | 31 | 0.7578 | [0.6797, 0.8438] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: fair-variant

skipped: fewer_than_two_bots

### tag: heuristic

skipped: fewer_than_two_bots

### tag: imitation

skipped: fewer_than_two_bots

### tag: learned

skipped: fewer_than_two_bots

### tag: pretrained

skipped: fewer_than_two_bots

### tag: search

skipped: fewer_than_two_bots

## By deck

### FDN_top_02581_UR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 2.014322 | 1349.9 | [1264.5, 1532.4] | 16 | 13 | 0 | 3 | 0 |
| 2 | heuristic 2.0.0 | 1.291341 | 1224.3 | [1087.6, 1460.0] | 16 | 9 | 0 | 7 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 2 | 0 | 14 | 0 |

### FDN_top_02810_UR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 1.305698 | 1226.8 | [1078.5, 1492.2] | 16 | 12 | 0 | 4 | 4 |
| 2 | heuristic 2.0.0 | 0.652849 | 1113.4 | [971.3, 1302.4] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 4 | 0 | 12 | 0 |

### FDN_top_04752_WG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 1.740532 | 1302.4 | [1105.3, 1766.7] | 16 | 13 | 0 | 3 | 0 |
| 2 | heuristic 2.0.0 | 0.870266 | 1151.2 | [1052.6, 1383.4] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 3 | 0 | 13 | 0 |

### FDN_top_05840_UGpR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 0.000000 | 1000.0 | [892.8, 1105.3] | 16 | 8 | 0 | 8 | 1 |
| 2 | heuristic 2.0.0 | 0.000000 | 1000.0 | [834.0, 1166.0] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 8 | 0 | 8 | 0 |

### FDN_top_13096_WU

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 3.064829 | 1532.4 | [1378.0, 1766.7] | 16 | 15 | 0 | 1 | 0 |
| 2 | heuristic 2.0.0 | 1.532415 | 1266.2 | [1099.2, 1431.9] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 1 | 0 | 15 | 0 |

### FDN_top_13950_BR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 2.833213 | 1492.2 | [1406.7, 1648.7] | 16 | 16 | 0 | 0 | 0 |
| 2 | heuristic 2.0.0 | 0.000000 | 1000.0 | [758.0, 1242.0] | 16 | 4 | 0 | 12 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 4 | 0 | 12 | 0 |

### FDN_top_15834_WBpU

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 2.396474 | 1416.3 | [1232.3, 1648.7] | 16 | 13 | 0 | 3 | 0 |
| 2 | heuristic 2.0.0 | 1.825458 | 1317.1 | [1198.9, 1460.0] | 16 | 10 | 0 | 6 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 1 | 0 | 15 | 0 |

### FDN_top_16798_UB

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 2.175844 | 1378.0 | [1232.3, 1579.9] | 16 | 12 | 0 | 4 | 0 |
| 2 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 1.989768 | 1345.7 | [1166.0, 1579.9] | 16 | 11 | 0 | 5 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 1 | 0 | 15 | 0 |

### FDN_top_17463_BG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 0.771181 | 1134.0 | [973.2, 1349.9] | 16 | 10 | 0 | 6 | 0 |
| 2 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 0.617093 | 1107.2 | [967.7, 1302.4] | 16 | 9 | 0 | 7 | 5 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 5 | 0 | 11 | 0 |

### FDN_top_20196_GpUR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 2.290141 | 1397.8 | [1264.5, 1648.7] | 16 | 14 | 0 | 2 | 1 |
| 2 | heuristic 2.0.0 | 1.145071 | 1198.9 | [1061.0, 1431.9] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 2 | 0 | 14 | 0 |

### FDN_top_20626_WG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | heuristic 2.0.0 | 2.014322 | 1349.9 | [1203.6, 1579.9] | 16 | 13 | 0 | 3 | 0 |
| 2 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 1.291341 | 1224.3 | [971.3, 1492.2] | 16 | 9 | 0 | 7 | 2 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 2 | 0 | 14 | 0 |

### FDN_top_21511_WUR

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 3.338128 | 1579.9 | [1492.2, 1766.7] | 16 | 16 | 0 | 0 | 0 |
| 2 | heuristic 2.0.0 | 0.851839 | 1148.0 | [1000.0, 1383.4] | 16 | 6 | 0 | 10 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 2 | 0 | 14 | 0 |

### FDN_top_23736_U

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 3.055450 | 1530.8 | [1431.9, 1766.7] | 16 | 16 | 0 | 0 | 0 |
| 2 | heuristic 2.0.0 | 0.407709 | 1070.8 | [852.0, 1383.4] | 16 | 5 | 0 | 11 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 3 | 0 | 13 | 0 |

### FDN_top_24789_BGpW

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 0.297936 | 1051.8 | [921.5, 1203.6] | 16 | 9 | 0 | 7 | 4 |
| 2 | heuristic 2.0.0 | 0.148968 | 1025.9 | [860.8, 1226.8] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 7 | 0 | 9 | 0 |

### FDN_top_26941_WB

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 1.609438 | 1279.6 | [1113.4, 1530.8] | 16 | 14 | 0 | 2 | 1 |
| 2 | heuristic 2.0.0 | 0.000000 | 1000.0 | [801.1, 1198.9] | 16 | 5 | 0 | 11 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 5 | 0 | 11 | 0 |

### FDN_top_28740_RG

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 2.833213 | 1492.2 | [1406.7, 1648.7] | 16 | 12 | 0 | 4 | 2 |
| 2 | heuristic 2.0.0 | 2.833213 | 1492.2 | [1406.7, 1648.7] | 16 | 12 | 0 | 4 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 16 | 0 | 0 | 16 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| draftzero-fdn-gnn-100-fair draftzero-gnn-pimc-v1-f95b3129ac9e49d99d8a4e90 | 256 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 256 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 256 | 0 | 0.000 | 0 | 0.000 |

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
