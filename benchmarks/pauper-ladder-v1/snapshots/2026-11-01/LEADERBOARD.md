# Spellbench leaderboard: pauper-bo1

- Games: 1920 played, 1920 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.981539 | 1517.9 | [1459.6, 1581.8] | 384 | 257 | 0 | 127 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.924822 | 1508.1 | [1454.0, 1567.2] | 512 | 356 | 0 | 156 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.228912 | 1387.2 | [1338.6, 1438.1] | 640 | 361 | 0 | 279 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.531857 | 1266.1 | [1219.9, 1314.8] | 768 | 351 | 0 | 417 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.401526 | 1243.5 | [1200.7, 1287.6] | 640 | 306 | 0 | 334 | 0 |
| 6 | heuristic 2.0.0 | 0.833061 | 1144.7 | [1102.3, 1188.6] | 512 | 203 | 0 | 309 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 86 | 0 | 298 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| heuristic | c12 | 128 | 49 | 0 | 79 | 0.3828 | [0.2891, 0.4766] | 0.0237 |
| heuristic | g115 | 128 | 21 | 0 | 107 | 0.1641 | [0.1094, 0.2266] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 49 | 0 | 79 | 0.3828 | [0.3047, 0.4688] | 0.0107 |
| heuristic | uniform | 128 | 84 | 0 | 44 | 0.6562 | [0.5859, 0.7266] | 0.0002 |
| oh2-r2s1-b512 | c12 | 128 | 112 | 0 | 16 | 0.8750 | [0.8125, 0.9297] | 0.0000 |
| oh2-r2s1-b512 | g115 | 128 | 83 | 0 | 45 | 0.6484 | [0.5625, 0.7344] | 0.0034 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 99 | 0 | 29 | 0.7734 | [0.7031, 0.8516] | 0.0000 |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 128 | 62 | 0 | 66 | 0.4844 | [0.3906, 0.5781] | 0.8714 |
| c12 | g115 | 128 | 42 | 0 | 86 | 0.3281 | [0.2422, 0.4219] | 0.0013 |
| c12 | gorge-ar8 | 128 | 59 | 0 | 69 | 0.4609 | [0.3594, 0.5547] | 0.5224 |
| c12 | uniform | 128 | 110 | 0 | 18 | 0.8594 | [0.8047, 0.9141] | 0.0000 |
| g115 | gorge-ar8 | 128 | 87 | 0 | 41 | 0.6797 | [0.5938, 0.7656] | 0.0003 |
| g115 | oh2-r2s1-b512-argmax | 128 | 36 | 0 | 92 | 0.2812 | [0.2109, 0.3594] | 0.0000 |
| gorge-ar8 | uniform | 128 | 104 | 0 | 24 | 0.8125 | [0.7500, 0.8750] | 0.0000 |
| gorge-ar8 | oh2-r2s1-b512-argmax | 128 | 29 | 0 | 99 | 0.2266 | [0.1641, 0.2969] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.473784 | 1082.3 | 128 | 79 | 0 | 49 |
| heuristic 2.0.0 | 0.000000 | 1000.0 | 128 | 49 | 0 | 79 |

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 0.096029 | 1016.7 | 256 | 158 | 0 | 98 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 384 | 257 | 0 | 127 |
| g115 pauper-v2.0.0 | -0.792417 | 862.3 | 384 | 167 | 0 | 217 |
| c12 pauper-v2.0.0 | -1.654621 | 712.6 | 256 | 58 | 0 | 198 |

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.913101 | 1506.1 | [1374.6, 1677.8] | 48 | 32 | 0 | 16 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.561074 | 1444.9 | [1322.9, 1605.1] | 64 | 39 | 0 | 25 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.450550 | 1425.7 | [1311.3, 1579.6] | 80 | 50 | 0 | 30 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.705579 | 1296.3 | [1194.7, 1430.6] | 96 | 47 | 0 | 49 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.355289 | 1235.4 | [1139.6, 1359.4] | 80 | 36 | 0 | 44 | 0 |
| 6 | heuristic 2.0.0 | 1.051683 | 1182.7 | [1078.9, 1313.7] | 64 | 27 | 0 | 37 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 9 | 0 | 39 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.967959 | 1689.3 | [1538.0, 1898.3] | 48 | 36 | 0 | 12 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.526539 | 1612.6 | [1476.2, 1801.3] | 64 | 44 | 0 | 20 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.031279 | 1526.6 | [1412.2, 1672.4] | 80 | 51 | 0 | 29 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.986316 | 1345.1 | [1231.3, 1489.0] | 96 | 46 | 0 | 50 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.628776 | 1282.9 | [1171.6, 1407.8] | 80 | 38 | 0 | 42 | 0 |
| 6 | heuristic 2.0.0 | 0.198049 | 1034.4 | [955.6, 1123.1] | 64 | 14 | 0 | 50 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.389024 | 1588.7 | [1459.7, 1766.7] | 64 | 60 | 0 | 4 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.114706 | 1367.4 | [1240.5, 1525.7] | 48 | 32 | 0 | 16 | 0 |
| 3 | c12 pauper-v2.0.0 | 0.603438 | 1104.8 | [1016.3, 1202.8] | 80 | 42 | 0 | 38 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.322530 | 1056.0 | [969.1, 1143.2] | 96 | 38 | 0 | 58 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 21 | 0 | 27 | 0 |
| 6 | g115 pauper-v2.0.0 | -0.026833 | 995.3 | [888.3, 1095.5] | 80 | 22 | 0 | 58 | 0 |
| 7 | heuristic 2.0.0 | -0.200317 | 965.2 | [871.2, 1055.0] | 64 | 25 | 0 | 39 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.503673 | 1434.9 | [1298.9, 1601.6] | 48 | 31 | 0 | 17 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.485956 | 1431.9 | [1294.1, 1597.8] | 64 | 42 | 0 | 22 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.191863 | 1380.8 | [1264.1, 1518.4] | 80 | 47 | 0 | 33 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.675661 | 1291.1 | [1177.8, 1434.5] | 80 | 44 | 0 | 36 | 0 |
| 5 | heuristic 2.0.0 | 1.553318 | 1269.8 | [1166.5, 1410.1] | 64 | 37 | 0 | 27 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.917985 | 1159.5 | [1055.2, 1281.4] | 96 | 30 | 0 | 66 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 9 | 0 | 39 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.672456 | 1638.0 | [1493.9, 1830.7] | 48 | 37 | 0 | 11 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.752257 | 1478.1 | [1362.9, 1635.8] | 80 | 48 | 0 | 32 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.658511 | 1461.8 | [1338.1, 1621.7] | 64 | 34 | 0 | 30 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.184095 | 1379.4 | [1274.2, 1522.4] | 96 | 50 | 0 | 46 | 0 |
| 5 | heuristic 2.0.0 | 1.660427 | 1288.4 | [1181.9, 1437.6] | 64 | 32 | 0 | 32 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.514425 | 1263.1 | [1157.1, 1404.0] | 80 | 33 | 0 | 47 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 6 | 0 | 42 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.251849 | 1564.9 | [1439.0, 1738.4] | 64 | 42 | 0 | 22 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.163633 | 1549.6 | [1396.2, 1740.9] | 48 | 27 | 0 | 21 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.969371 | 1515.8 | [1378.9, 1690.5] | 80 | 51 | 0 | 29 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.544168 | 1442.0 | [1329.3, 1594.7] | 96 | 57 | 0 | 39 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.693245 | 1294.1 | [1174.3, 1455.5] | 80 | 35 | 0 | 45 | 0 |
| 6 | heuristic 2.0.0 | 0.985352 | 1171.2 | [1039.6, 1327.2] | 64 | 21 | 0 | 43 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 7 | 0 | 41 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.251287 | 1391.1 | [1261.4, 1549.4] | 64 | 43 | 0 | 21 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.093035 | 1363.6 | [1237.4, 1524.2] | 48 | 29 | 0 | 19 | 0 |
| 3 | g115 pauper-v2.0.0 | 1.461548 | 1253.9 | [1126.5, 1408.1] | 80 | 39 | 0 | 41 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.376870 | 1239.2 | [1130.9, 1381.9] | 80 | 45 | 0 | 35 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.335715 | 1232.0 | [1109.1, 1381.1] | 96 | 49 | 0 | 47 | 0 |
| 6 | heuristic 2.0.0 | 0.470956 | 1081.8 | [975.2, 1213.1] | 64 | 23 | 0 | 41 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 12 | 0 | 36 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 4.144794 | 1720.0 | [1588.6, 1903.7] | 64 | 52 | 0 | 12 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.881975 | 1674.4 | [1525.8, 1866.5] | 48 | 33 | 0 | 15 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.191915 | 1554.5 | [1441.3, 1711.1] | 80 | 53 | 0 | 27 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.314165 | 1228.3 | [1132.4, 1344.6] | 96 | 34 | 0 | 62 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.298269 | 1225.5 | [1128.4, 1347.9] | 80 | 33 | 0 | 47 | 0 |
| 6 | heuristic 2.0.0 | 0.804579 | 1139.8 | [1051.8, 1246.9] | 64 | 24 | 0 | 40 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512 pauper-v2.0.0 | 512 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 512 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |

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
- Ladder rating: the references (rungs) play the rungs nearest them in rating and each entrant plays the rungs named for it, so ratings connect through overlapping matchups. Unplayed head-to-head matchups are not measured; matchup-specific strengths can differ from the ranking. Compatible earlier evaluations are reused, so this is a dated model measurement. Elo and its interval can change when the combined results are refitted without replaying earlier games.
