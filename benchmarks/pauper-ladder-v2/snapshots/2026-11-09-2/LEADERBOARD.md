# Spellbench leaderboard: pauper-bo1

- Games: 2304 played, 2298 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 6)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.967943 | 1515.6 | [1461.8, 1576.5] | 638 | 417 | 0 | 221 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.854543 | 1495.9 | [1437.7, 1562.0] | 507 | 297 | 0 | 210 | 0 |
| 3 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.726754 | 1473.7 | [1411.2, 1543.8] | 383 | 187 | 0 | 196 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.515346 | 1437.0 | [1384.3, 1497.9] | 764 | 441 | 0 | 323 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.720649 | 1298.9 | [1251.1, 1351.0] | 640 | 329 | 0 | 311 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.715698 | 1298.0 | [1249.7, 1349.7] | 768 | 359 | 0 | 409 | 0 |
| 7 | heuristic 2.0.0 | 0.939222 | 1163.2 | [1117.9, 1215.0] | 512 | 194 | 0 | 318 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 74 | 0 | 310 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 127 | 65 | 0 | 62 | 0.5079 | [0.4127, 0.5952] | 1.0000 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 106 | 0 | 22 | 0.8281 | [0.7656, 0.8828] | 0.0000 |
| oh2-r2s1-b512 | g115 | 127 | 75 | 0 | 52 | 0.5873 | [0.5000, 0.6825] | 0.0989 |
| oh2-r2s1-b512 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 69 | 0 | 59 | 0.5391 | [0.4453, 0.6328] | 0.5114 |
| oh2-r2s1-b512 | c12 | 128 | 102 | 0 | 26 | 0.7969 | [0.7266, 0.8594] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 46 | 0 | 82 | 0.3594 | [0.2656, 0.4531] | 0.0051 |
| heuristic | g115 | 128 | 18 | 0 | 110 | 0.1406 | [0.0859, 0.2031] | 0.0000 |
| heuristic | uniform | 128 | 88 | 0 | 40 | 0.6875 | [0.6094, 0.7734] | 0.0001 |
| heuristic | c12 | 128 | 42 | 0 | 86 | 0.3281 | [0.2344, 0.4141] | 0.0009 |
| oh2-r2s1-b512-argmax | gorge-ar8 | 128 | 96 | 0 | 32 | 0.7500 | [0.6641, 0.8203] | 0.0000 |
| oh2-r2s1-b512-argmax | g115 | 125 | 71 | 0 | 54 | 0.5656 | [0.4836, 0.6557] | 0.2153 |
| oh2-r2s1-b512-argmax | oh2-r2s1-b512-s4a-16k-k4 | 127 | 68 | 0 | 59 | 0.5397 | [0.4444, 0.6349] | 0.5224 |
| gorge-ar8 | g115 | 128 | 48 | 0 | 80 | 0.3750 | [0.2891, 0.4609] | 0.0139 |
| gorge-ar8 | uniform | 128 | 111 | 0 | 17 | 0.8672 | [0.8047, 0.9219] | 0.0000 |
| gorge-ar8 | c12 | 128 | 64 | 0 | 64 | 0.5000 | [0.4062, 0.5859] | 1.0000 |
| g115 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 59 | 0 | 69 | 0.4609 | [0.3594, 0.5547] | 0.5327 |
| g115 | c12 | 128 | 86 | 0 | 42 | 0.6719 | [0.5859, 0.7656] | 0.0013 |
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
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 510 | 311 | 0 | 199 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.062259 | 989.2 | 379 | 201 | 0 | 178 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | -0.199301 | 965.4 | 383 | 187 | 0 | 196 |
| g115 pauper-v2.0.0 | -0.378087 | 934.3 | 508 | 251 | 0 | 257 |
| c12 pauper-v2.0.0 | -1.205004 | 790.7 | 256 | 68 | 0 | 188 |

### tag: search

skipped: fewer_than_two_bots

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.965893 | 1515.2 | [1404.5, 1672.3] | 96 | 66 | 0 | 30 | 0 |
| 2 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.828836 | 1491.4 | [1361.7, 1667.2] | 48 | 26 | 0 | 22 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.623870 | 1455.8 | [1328.5, 1621.3] | 64 | 35 | 0 | 29 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 2.420059 | 1420.4 | [1304.6, 1575.0] | 80 | 39 | 0 | 41 | 0 |
| 5 | c12 pauper-v2.0.0 | 2.406287 | 1418.0 | [1314.2, 1570.8] | 80 | 53 | 0 | 27 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.463290 | 1254.2 | [1149.7, 1399.2] | 96 | 37 | 0 | 59 | 0 |
| 7 | heuristic 2.0.0 | 1.212037 | 1210.6 | [1100.5, 1354.5] | 64 | 25 | 0 | 39 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 7 | 0 | 41 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.536046 | 1614.3 | [1494.6, 1770.2] | 80 | 56 | 0 | 24 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.357794 | 1583.3 | [1468.0, 1731.3] | 96 | 68 | 0 | 28 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.288592 | 1571.3 | [1431.2, 1741.6] | 64 | 37 | 0 | 27 | 0 |
| 4 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.995737 | 1520.4 | [1360.5, 1690.2] | 48 | 19 | 0 | 29 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.900633 | 1330.2 | [1244.0, 1442.8] | 96 | 45 | 0 | 51 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.666660 | 1289.5 | [1188.3, 1410.3] | 80 | 38 | 0 | 42 | 0 |
| 7 | heuristic 2.0.0 | 0.215278 | 1037.4 | [926.9, 1143.0] | 64 | 14 | 0 | 50 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.882039 | 1674.4 | [1515.5, 1905.0] | 64 | 51 | 0 | 13 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.610065 | 1627.1 | [1489.4, 1817.9] | 80 | 62 | 0 | 18 | 0 |
| 3 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 3.185082 | 1553.3 | [1388.7, 1762.4] | 48 | 27 | 0 | 21 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.582887 | 1275.0 | [1161.0, 1429.4] | 96 | 50 | 0 | 46 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.325711 | 1230.3 | [1122.4, 1377.0] | 80 | 44 | 0 | 36 | 0 |
| 6 | heuristic 2.0.0 | 0.596969 | 1103.7 | [981.4, 1252.0] | 64 | 29 | 0 | 35 | 0 |
| 7 | g115 pauper-v2.0.0 | 0.268541 | 1046.7 | [923.9, 1201.4] | 96 | 14 | 0 | 82 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.890961 | 1502.2 | [1362.3, 1677.2] | 64 | 43 | 0 | 21 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.858492 | 1496.6 | [1373.8, 1645.6] | 80 | 56 | 0 | 24 | 0 |
| 3 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.445693 | 1424.9 | [1259.5, 1618.9] | 48 | 21 | 0 | 27 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.306260 | 1400.6 | [1264.6, 1558.6] | 96 | 56 | 0 | 40 | 0 |
| 5 | heuristic 2.0.0 | 1.302557 | 1226.3 | [1106.3, 1365.4] | 64 | 35 | 0 | 29 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.280719 | 1222.5 | [1115.9, 1343.5] | 80 | 37 | 0 | 43 | 0 |
| 7 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.827702 | 1143.8 | [1040.6, 1252.2] | 96 | 29 | 0 | 67 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 3.574769 | 1621.0 | [1476.6, 1822.2] | 47 | 36 | 0 | 11 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.629451 | 1456.8 | [1331.9, 1631.8] | 78 | 42 | 0 | 36 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.610556 | 1453.5 | [1331.8, 1631.2] | 92 | 50 | 0 | 42 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.423961 | 1421.1 | [1308.8, 1588.8] | 96 | 60 | 0 | 36 | 0 |
| 5 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.209316 | 1383.8 | [1236.1, 1577.8] | 59 | 21 | 0 | 38 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.824080 | 1316.9 | [1191.0, 1489.6] | 80 | 38 | 0 | 42 | 0 |
| 7 | heuristic 2.0.0 | 1.643096 | 1285.4 | [1176.5, 1431.1] | 64 | 30 | 0 | 34 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 5 | 0 | 43 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 3.716730 | 1645.7 | [1500.8, 1856.7] | 48 | 27 | 0 | 21 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.544926 | 1615.8 | [1491.1, 1810.9] | 96 | 63 | 0 | 33 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 3.502175 | 1608.4 | [1483.6, 1812.8] | 80 | 47 | 0 | 33 | 0 |
| 4 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.393171 | 1589.5 | [1457.0, 1789.0] | 64 | 32 | 0 | 32 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.794810 | 1485.5 | [1357.2, 1676.9] | 96 | 55 | 0 | 41 | 0 |
| 6 | c12 pauper-v2.0.0 | 2.243242 | 1389.7 | [1264.7, 1580.8] | 80 | 39 | 0 | 41 | 0 |
| 7 | heuristic 2.0.0 | 1.215022 | 1211.1 | [1089.9, 1379.0] | 64 | 20 | 0 | 44 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 5 | 0 | 43 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.109995 | 1366.5 | [1242.4, 1515.2] | 80 | 49 | 0 | 31 | 0 |
| 2 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 1.940494 | 1337.1 | [1181.9, 1515.8] | 48 | 24 | 0 | 24 | 0 |
| 3 | g115 pauper-v2.0.0 | 1.862710 | 1323.6 | [1212.5, 1457.7] | 96 | 56 | 0 | 40 | 0 |
| 4 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 1.849080 | 1321.2 | [1180.4, 1474.9] | 64 | 33 | 0 | 31 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.473242 | 1255.9 | [1143.4, 1390.3] | 80 | 46 | 0 | 34 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.230349 | 1213.7 | [1114.3, 1329.1] | 96 | 46 | 0 | 50 | 0 |
| 7 | heuristic 2.0.0 | 0.482987 | 1083.9 | [1002.3, 1182.1] | 64 | 22 | 0 | 42 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 12 | 0 | 36 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 4.069721 | 1707.0 | [1551.8, 1929.2] | 80 | 66 | 0 | 14 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.714463 | 1645.3 | [1483.0, 1871.5] | 64 | 45 | 0 | 19 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.292919 | 1572.0 | [1434.8, 1776.0] | 96 | 68 | 0 | 28 | 0 |
| 4 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.049416 | 1356.0 | [1157.7, 1581.5] | 48 | 7 | 0 | 41 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.427027 | 1247.9 | [1114.2, 1432.5] | 96 | 37 | 0 | 59 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.317166 | 1228.8 | [1114.9, 1386.0] | 80 | 34 | 0 | 46 | 0 |
| 7 | heuristic 2.0.0 | 0.450402 | 1078.2 | [941.5, 1229.6] | 64 | 19 | 0 | 45 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 12 | 0 | 36 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 512 | 3 | 0.006 | 0 | 0.000 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 384 | 1 | 0.003 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 768 | 2 | 0.003 | 0 | 0.000 |
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
- Ladder rating: the references (rungs) play the rungs nearest them in rating and each entrant plays the rungs named for it, so ratings connect through overlapping matchups. Unplayed head-to-head matchups are not measured; matchup-specific strengths can differ from the ranking. Compatible earlier evaluations are reused, so this is a dated model measurement. Elo and its interval can change when the combined results are refitted without replaying earlier games.
