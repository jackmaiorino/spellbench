# Spellbench leaderboard: pauper-bo1

- Games: 1920 played, 1915 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 5)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.989507 | 1519.3 | [1460.0, 1582.3] | 510 | 348 | 0 | 162 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.848127 | 1494.8 | [1432.8, 1563.2] | 380 | 229 | 0 | 151 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.505586 | 1435.3 | [1381.1, 1492.7] | 636 | 382 | 0 | 254 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.722145 | 1299.2 | [1249.3, 1354.6] | 640 | 329 | 0 | 311 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.716160 | 1298.1 | [1253.7, 1354.1] | 768 | 359 | 0 | 409 | 0 |
| 6 | heuristic 2.0.0 | 0.937974 | 1162.9 | [1114.2, 1213.6] | 512 | 194 | 0 | 318 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 74 | 0 | 310 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 127 | 65 | 0 | 62 | 0.5079 | [0.4127, 0.5952] | 1.0000 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 106 | 0 | 22 | 0.8281 | [0.7656, 0.8828] | 0.0000 |
| oh2-r2s1-b512 | g115 | 127 | 75 | 0 | 52 | 0.5873 | [0.5000, 0.6825] | 0.0989 |
| oh2-r2s1-b512 | c12 | 128 | 102 | 0 | 26 | 0.7969 | [0.7344, 0.8594] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 46 | 0 | 82 | 0.3594 | [0.2734, 0.4453] | 0.0051 |
| heuristic | g115 | 128 | 18 | 0 | 110 | 0.1406 | [0.0859, 0.2031] | 0.0000 |
| heuristic | uniform | 128 | 88 | 0 | 40 | 0.6875 | [0.6016, 0.7656] | 0.0001 |
| heuristic | c12 | 128 | 42 | 0 | 86 | 0.3281 | [0.2422, 0.4141] | 0.0009 |
| oh2-r2s1-b512-argmax | gorge-ar8 | 128 | 96 | 0 | 32 | 0.7500 | [0.6641, 0.8281] | 0.0000 |
| oh2-r2s1-b512-argmax | g115 | 125 | 71 | 0 | 54 | 0.5656 | [0.4754, 0.6475] | 0.2153 |
| gorge-ar8 | g115 | 128 | 48 | 0 | 80 | 0.3750 | [0.2891, 0.4609] | 0.0139 |
| gorge-ar8 | uniform | 128 | 111 | 0 | 17 | 0.8672 | [0.8047, 0.9219] | 0.0000 |
| gorge-ar8 | c12 | 128 | 64 | 0 | 64 | 0.5000 | [0.4062, 0.5859] | 1.0000 |
| g115 | c12 | 128 | 86 | 0 | 42 | 0.6719 | [0.5781, 0.7578] | 0.0013 |
| uniform | c12 | 128 | 17 | 0 | 111 | 0.1328 | [0.0781, 0.1953] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.573346 | 1099.6 | 128 | 82 | 0 | 46 |
| heuristic 2.0.0 | 0.000000 | 1000.0 | 128 | 46 | 0 | 82 |

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 382 | 242 | 0 | 140 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.081779 | 985.8 | 252 | 133 | 0 | 119 |
| g115 pauper-v2.0.0 | -0.396383 | 931.1 | 380 | 192 | 0 | 188 |
| c12 pauper-v2.0.0 | -1.214977 | 788.9 | 256 | 68 | 0 | 188 |

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.904810 | 1504.6 | [1386.4, 1660.1] | 80 | 56 | 0 | 24 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.641925 | 1458.9 | [1323.6, 1637.8] | 48 | 28 | 0 | 20 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.493160 | 1433.1 | [1312.8, 1593.3] | 64 | 34 | 0 | 30 | 0 |
| 4 | c12 pauper-v2.0.0 | 2.410551 | 1418.8 | [1315.5, 1575.5] | 80 | 53 | 0 | 27 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.469868 | 1255.3 | [1148.0, 1406.9] | 96 | 37 | 0 | 59 | 0 |
| 6 | heuristic 2.0.0 | 1.204556 | 1209.3 | [1093.0, 1351.9] | 64 | 25 | 0 | 39 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 7 | 0 | 41 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.440446 | 1597.7 | [1473.2, 1760.7] | 64 | 44 | 0 | 20 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.393371 | 1589.5 | [1470.2, 1744.7] | 80 | 59 | 0 | 21 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.378147 | 1586.8 | [1442.8, 1777.3] | 48 | 29 | 0 | 19 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.905277 | 1331.0 | [1242.6, 1458.9] | 96 | 45 | 0 | 51 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.659734 | 1288.3 | [1185.7, 1416.5] | 80 | 38 | 0 | 42 | 0 |
| 6 | heuristic 2.0.0 | 0.216910 | 1037.7 | [924.8, 1149.6] | 64 | 14 | 0 | 50 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.694434 | 1641.8 | [1468.0, 1890.4] | 48 | 39 | 0 | 9 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.608471 | 1626.9 | [1487.8, 1828.7] | 64 | 53 | 0 | 11 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.571300 | 1273.0 | [1166.3, 1425.0] | 96 | 50 | 0 | 46 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.328832 | 1230.8 | [1119.1, 1374.0] | 80 | 44 | 0 | 36 | 0 |
| 5 | heuristic 2.0.0 | 0.601894 | 1104.6 | [972.9, 1252.5] | 64 | 29 | 0 | 35 | 0 |
| 6 | g115 pauper-v2.0.0 | 0.293169 | 1050.9 | [928.7, 1191.5] | 80 | 14 | 0 | 66 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.992649 | 1519.9 | [1399.8, 1685.6] | 64 | 48 | 0 | 16 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.912652 | 1506.0 | [1371.5, 1691.8] | 48 | 33 | 0 | 15 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.247466 | 1390.4 | [1267.1, 1558.4] | 80 | 47 | 0 | 33 | 0 |
| 4 | heuristic 2.0.0 | 1.291657 | 1224.4 | [1111.2, 1369.2] | 64 | 35 | 0 | 29 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.285776 | 1223.4 | [1119.9, 1356.5] | 80 | 37 | 0 | 43 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.832328 | 1144.6 | [1043.7, 1264.6] | 96 | 29 | 0 | 67 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.653335 | 1460.9 | [1340.0, 1628.9] | 76 | 47 | 0 | 29 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.619819 | 1455.1 | [1333.7, 1619.9] | 62 | 38 | 0 | 24 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.404959 | 1417.8 | [1304.7, 1577.0] | 96 | 60 | 0 | 36 | 0 |
| 4 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.068225 | 1359.3 | [1210.5, 1548.9] | 44 | 17 | 0 | 27 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.828366 | 1317.6 | [1204.1, 1484.7] | 80 | 38 | 0 | 42 | 0 |
| 6 | heuristic 2.0.0 | 1.649884 | 1286.6 | [1179.0, 1432.1] | 64 | 30 | 0 | 34 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 5 | 0 | 43 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.575347 | 1621.1 | [1483.4, 1825.3] | 64 | 41 | 0 | 23 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.477051 | 1604.0 | [1472.2, 1807.6] | 80 | 54 | 0 | 26 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.450574 | 1599.4 | [1458.8, 1810.2] | 48 | 26 | 0 | 22 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.807630 | 1487.7 | [1355.4, 1679.6] | 96 | 55 | 0 | 41 | 0 |
| 5 | c12 pauper-v2.0.0 | 2.246329 | 1390.2 | [1257.4, 1571.2] | 80 | 39 | 0 | 41 | 0 |
| 6 | heuristic 2.0.0 | 1.209593 | 1210.1 | [1092.1, 1379.4] | 64 | 20 | 0 | 44 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 5 | 0 | 43 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.088659 | 1362.8 | [1238.3, 1500.1] | 64 | 40 | 0 | 24 | 0 |
| 2 | g115 pauper-v2.0.0 | 1.885491 | 1327.5 | [1218.2, 1458.9] | 80 | 49 | 0 | 31 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 1.816720 | 1315.6 | [1180.4, 1467.4] | 48 | 25 | 0 | 23 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.473390 | 1256.0 | [1138.2, 1385.0] | 80 | 46 | 0 | 34 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.225790 | 1212.9 | [1114.2, 1328.5] | 96 | 46 | 0 | 50 | 0 |
| 6 | heuristic 2.0.0 | 0.486279 | 1084.5 | [1001.0, 1179.2] | 64 | 22 | 0 | 42 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 12 | 0 | 36 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.955087 | 1687.1 | [1530.2, 1909.8] | 64 | 50 | 0 | 14 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.763032 | 1653.7 | [1489.5, 1866.7] | 48 | 32 | 0 | 16 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.329693 | 1578.4 | [1433.9, 1770.3] | 80 | 56 | 0 | 24 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.427414 | 1248.0 | [1109.1, 1427.9] | 96 | 37 | 0 | 59 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.314100 | 1228.3 | [1115.6, 1387.3] | 80 | 34 | 0 | 46 | 0 |
| 6 | heuristic 2.0.0 | 0.452300 | 1078.6 | [937.4, 1232.6] | 64 | 19 | 0 | 45 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 12 | 0 | 36 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 512 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 384 | 3 | 0.008 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 640 | 2 | 0.003 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 768 | 0 | 0.000 | 0 | 0.000 |
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
