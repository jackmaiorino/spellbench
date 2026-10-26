# Spellbench leaderboard: pauper-bo1

- Games: 872 played, 872 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.832068 | 1492.0 | [1371.7, 1643.8] | 64 | 39 | 0 | 25 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.394446 | 1416.0 | [1327.7, 1521.0] | 744 | 524 | 0 | 220 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.896608 | 1329.5 | [1178.3, 1480.8] | 40 | 15 | 0 | 25 | 0 |
| 4 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.891817 | 1328.6 | [1185.7, 1473.1] | 64 | 24 | 0 | 40 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.825753 | 1317.2 | [1188.6, 1458.0] | 64 | 23 | 0 | 41 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.717119 | 1298.3 | [1214.9, 1401.8] | 128 | 76 | 0 | 52 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.619382 | 1281.3 | [1150.8, 1415.6] | 64 | 20 | 0 | 44 | 0 |
| 8 | kit-mad-k 0.3.0+a49c05ddab71 | 1.472764 | 1255.8 | [1128.5, 1387.1] | 64 | 18 | 0 | 46 | 0 |
| 9 | kit-mad-1 0.3.0+4e575c6a49fc | 1.395917 | 1242.5 | [1090.6, 1379.1] | 64 | 17 | 0 | 47 | 0 |
| 10 | a48 pauper-v2.0.0 | 1.369989 | 1238.0 | [1151.8, 1331.1] | 128 | 68 | 0 | 60 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.233313 | 1214.2 | [1070.3, 1354.8] | 64 | 15 | 0 | 49 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.197221 | 1034.3 | [804.8, 1203.9] | 64 | 6 | 0 | 58 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 27 | 0 | 165 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| uniform | g115 | 64 | 6 | 0 | 58 | 0.0938 | [0.0156, 0.1719] | 0.0000 |
| uniform | c12 | 64 | 9 | 0 | 55 | 0.1406 | [0.0625, 0.2344] | 0.0000 |
| uniform | a48 | 64 | 12 | 0 | 52 | 0.1875 | [0.0938, 0.2969] | 0.0000 |
| kit-mad-k | g115 | 64 | 18 | 0 | 46 | 0.2812 | [0.1875, 0.3750] | 0.0005 |
| kit-mcts-custom | g115 | 64 | 6 | 0 | 58 | 0.0938 | [0.0312, 0.1719] | 0.0000 |
| oh2-r2s1-b512 | g115 | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1671 |
| g115 | kit-mad-1 | 64 | 47 | 0 | 17 | 0.7344 | [0.6250, 0.8438] | 0.0015 |
| g115 | gorge-explore | 40 | 25 | 0 | 15 | 0.6250 | [0.4750, 0.7750] | 0.2266 |
| g115 | gorge-bot | 64 | 49 | 0 | 15 | 0.7656 | [0.6562, 0.8750] | 0.0002 |
| g115 | gorge-lethal-pressure | 64 | 40 | 0 | 24 | 0.6250 | [0.4688, 0.7656] | 0.1516 |
| g115 | c12 | 64 | 43 | 0 | 21 | 0.6719 | [0.5312, 0.7969] | 0.0347 |
| g115 | gorge-ar8 | 64 | 41 | 0 | 23 | 0.6406 | [0.5156, 0.7656] | 0.0636 |
| g115 | gorge-blocks | 64 | 44 | 0 | 20 | 0.6875 | [0.5625, 0.8125] | 0.0118 |
| g115 | a48 | 64 | 48 | 0 | 16 | 0.7500 | [0.6250, 0.8594] | 0.0009 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 64 | 39 | 0 | 25 |
| g115 pauper-v2.0.0 | -0.437622 | 924.0 | 192 | 116 | 0 | 76 |
| c12 pauper-v2.0.0 | -1.142330 | 801.6 | 64 | 21 | 0 | 43 |
| a48 pauper-v2.0.0 | -1.515826 | 736.7 | 64 | 16 | 0 | 48 |

### tag: search

skipped: no_rated_games

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 3.498613 | 1607.8 | [1372.5, 1902.5] | 8 | 4 | 0 | 4 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.498613 | 1607.8 | [1115.6, 2115.1] | 8 | 4 | 0 | 4 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.498613 | 1607.8 | [1519.0, 1768.8] | 94 | 76 | 0 | 18 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.046628 | 1529.3 | [1084.7, 1847.3] | 8 | 3 | 0 | 5 | 0 |
| 5 | c12 pauper-v2.0.0 | 2.607497 | 1453.0 | [1362.6, 1585.9] | 16 | 10 | 0 | 6 | 0 |
| 6 | kit-mad-1 0.3.0+4e575c6a49fc | 2.543101 | 1441.8 | [1115.6, 1652.1] | 8 | 2 | 0 | 6 | 0 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.199330 | 1382.1 | [1098.6, 1624.7] | 6 | 1 | 0 | 5 | 0 |
| 8 | kit-mcts-custom 0.3.0+25b213ad6a3c | 1.889175 | 1328.2 | [1052.0, 1573.6] | 8 | 1 | 0 | 7 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.889175 | 1328.2 | [1052.0, 1573.6] | 8 | 1 | 0 | 7 | 0 |
| 10 | a48 pauper-v2.0.0 | 0.891115 | 1154.8 | [1009.5, 1362.6] | 16 | 6 | 0 | 10 | 0 |
| 11 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.665399 | 1115.6 | [1026.8, 1276.6] | 8 | 0 | 0 | 8 | 0 |
| 12 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.665399 | 1115.6 | [1026.8, 1276.6] | 8 | 0 | 0 | 8 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.086939 | 1536.3 | [1379.8, 1822.2] | 8 | 5 | 0 | 3 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.634953 | 1457.7 | [1352.4, 1678.1] | 92 | 75 | 0 | 17 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.634953 | 1457.7 | [1352.4, 1678.1] | 4 | 2 | 0 | 2 | 0 |
| 4 | kit-mad-k 0.3.0+a49c05ddab71 | 1.679442 | 1291.7 | [957.6, 1553.6] | 8 | 2 | 0 | 6 | 0 |
| 5 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.679442 | 1291.7 | [965.6, 1544.4] | 8 | 2 | 0 | 6 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.650931 | 1286.8 | [1121.3, 1546.7] | 16 | 9 | 0 | 7 | 0 |
| 7 | kit-mad-1 0.3.0+4e575c6a49fc | 1.025515 | 1178.2 | [887.7, 1457.0] | 8 | 1 | 0 | 7 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.025515 | 1178.2 | [887.7, 1457.0] | 8 | 1 | 0 | 7 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.025515 | 1178.2 | [887.7, 1464.1] | 8 | 1 | 0 | 7 | 0 |
| 10 | a48 pauper-v2.0.0 | 0.984023 | 1170.9 | [1039.2, 1332.9] | 16 | 7 | 0 | 9 | 0 |
| 11 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.198260 | 965.6 | [860.3, 1185.9] | 8 | 0 | 0 | 8 | 0 |
| 13 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.198260 | 965.6 | [860.3, 1185.9] | 8 | 0 | 0 | 8 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.707658 | 1470.4 | [1303.5, 1629.3] | 8 | 8 | 0 | 0 | 0 |
| 2 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.707658 | 1470.4 | [1303.5, 1629.3] | 8 | 8 | 0 | 0 | 0 |
| 3 | c12 pauper-v2.0.0 | 1.547974 | 1268.9 | [1107.6, 1518.3] | 16 | 14 | 0 | 2 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 0.829956 | 1144.2 | [907.2, 1492.2] | 8 | 6 | 0 | 2 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.829956 | 1144.2 | [907.9, 1492.2] | 8 | 6 | 0 | 2 | 0 |
| 6 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.829956 | 1144.2 | [898.3, 1492.2] | 8 | 6 | 0 | 2 | 0 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.721742 | 1125.4 | [870.0, 1469.3] | 4 | 3 | 0 | 1 | 0 |
| 8 | a48 pauper-v2.0.0 | 0.160585 | 1027.9 | [859.8, 1199.5] | 16 | 9 | 0 | 7 | 0 |
| 9 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 9 | 0 | 15 | 0 |
| 10 | g115 pauper-v2.0.0 | -0.125555 | 978.2 | [811.3, 1137.1] | 92 | 29 | 0 | 63 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.125555 | 978.2 | [672.1, 1261.9] | 8 | 4 | 0 | 4 | 0 |
| 12 | kit-mad-k 0.3.0+a49c05ddab71 | -0.577541 | 899.7 | [638.2, 1092.6] | 8 | 3 | 0 | 5 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.577541 | 899.7 | [463.6, 1210.2] | 8 | 3 | 0 | 5 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.737714 | 1649.3 | [1356.0, 2144.3] | 8 | 5 | 0 | 3 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.285729 | 1570.8 | [1426.7, 1850.4] | 94 | 76 | 0 | 18 | 0 |
| 3 | kit-mad-k 0.3.0+a49c05ddab71 | 2.833744 | 1492.3 | [1299.9, 1768.8] | 8 | 3 | 0 | 5 | 0 |
| 4 | a48 pauper-v2.0.0 | 2.447274 | 1425.1 | [1285.4, 1657.9] | 16 | 10 | 0 | 6 | 0 |
| 5 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.330218 | 1404.8 | [1109.3, 1690.2] | 8 | 2 | 0 | 6 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.330218 | 1404.8 | [1100.9, 1690.2] | 8 | 2 | 0 | 6 | 0 |
| 7 | kit-mad-1 0.3.0+4e575c6a49fc | 1.676291 | 1291.2 | [979.3, 1602.8] | 8 | 1 | 0 | 7 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.676291 | 1291.2 | [979.3, 1602.8] | 8 | 1 | 0 | 7 | 0 |
| 9 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.676291 | 1291.2 | [979.3, 1602.8] | 8 | 1 | 0 | 7 | 0 |
| 10 | c12 pauper-v2.0.0 | 1.642865 | 1285.4 | [1121.3, 1546.7] | 16 | 8 | 0 | 8 | 0 |
| 11 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.720780 | 1125.2 | [981.1, 1404.8] | 6 | 0 | 0 | 6 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.452516 | 1078.6 | [934.5, 1358.2] | 8 | 0 | 0 | 8 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.145833 | 1546.5 | [1214.5, 2027.2] | 8 | 6 | 0 | 2 | 0 |
| 2 | a48 pauper-v2.0.0 | 2.324695 | 1403.8 | [1274.4, 1640.9] | 16 | 12 | 0 | 4 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.190322 | 1380.5 | [1258.2, 1584.9] | 92 | 61 | 0 | 31 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.190322 | 1380.5 | [1258.2, 1584.9] | 4 | 2 | 0 | 2 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.190322 | 1380.5 | [1107.9, 1697.6] | 8 | 4 | 0 | 4 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.738337 | 1302.0 | [879.0, 1655.4] | 8 | 3 | 0 | 5 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.738337 | 1302.0 | [888.3, 1647.8] | 8 | 3 | 0 | 5 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.391505 | 1241.7 | [1073.5, 1492.2] | 16 | 9 | 0 | 7 | 0 |
| 9 | kit-mad-k 0.3.0+a49c05ddab71 | 1.234810 | 1214.5 | [909.4, 1475.0] | 8 | 2 | 0 | 6 | 0 |
| 10 | kit-mcts-custom 0.3.0+25b213ad6a3c | 1.234810 | 1214.5 | [893.1, 1493.0] | 8 | 2 | 0 | 6 | 0 |
| 11 | kit-mad-1 0.3.0+4e575c6a49fc | 0.580884 | 1100.9 | [798.5, 1388.8] | 8 | 1 | 0 | 7 | 0 |
| 12 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.580884 | 1100.9 | [798.5, 1387.6] | 8 | 1 | 0 | 7 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.950598 | 1686.3 | [1519.0, 1934.7] | 8 | 5 | 0 | 3 | 0 |
| 2 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.950598 | 1686.3 | [1519.0, 1977.2] | 8 | 5 | 0 | 3 | 0 |
| 3 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.950598 | 1686.3 | [1519.0, 1957.7] | 8 | 5 | 0 | 3 | 0 |
| 4 | g115 pauper-v2.0.0 | 3.498613 | 1607.8 | [1492.2, 1768.8] | 94 | 59 | 0 | 35 | 0 |
| 5 | kit-mad-1 0.3.0+4e575c6a49fc | 3.498613 | 1607.8 | [1353.0, 1928.9] | 8 | 4 | 0 | 4 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.498613 | 1607.8 | [1256.2, 2053.3] | 6 | 3 | 0 | 3 | 0 |
| 7 | kit-mad-k 0.3.0+a49c05ddab71 | 3.046628 | 1529.3 | [1321.9, 1768.8] | 8 | 3 | 0 | 5 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.046628 | 1529.3 | [1326.2, 1768.8] | 8 | 3 | 0 | 5 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.046628 | 1529.3 | [1321.9, 1768.8] | 8 | 3 | 0 | 5 | 0 |
| 10 | c12 pauper-v2.0.0 | 2.607497 | 1453.0 | [1348.8, 1657.9] | 16 | 10 | 0 | 6 | 0 |
| 11 | a48 pauper-v2.0.0 | 2.607497 | 1453.0 | [1356.6, 1600.5] | 16 | 10 | 0 | 6 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.665399 | 1115.6 | [1000.0, 1276.6] | 8 | 0 | 0 | 8 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.084714 | 1362.2 | [1037.0, 1842.1] | 8 | 6 | 0 | 2 | 0 |
| 2 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.976500 | 1343.4 | [1103.9, 1727.7] | 4 | 3 | 0 | 1 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 1.129202 | 1196.2 | [1043.3, 1415.7] | 8 | 4 | 0 | 4 | 0 |
| 4 | g115 pauper-v2.0.0 | 1.129202 | 1196.2 | [1043.3, 1415.7] | 92 | 64 | 0 | 28 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.129202 | 1196.2 | [898.1, 1519.8] | 8 | 4 | 0 | 4 | 0 |
| 6 | c12 pauper-v2.0.0 | 0.805911 | 1140.0 | [914.6, 1412.4] | 16 | 9 | 0 | 7 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.677217 | 1117.6 | [876.1, 1368.3] | 8 | 3 | 0 | 5 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.173691 | 1030.2 | [704.0, 1315.9] | 8 | 2 | 0 | 6 | 0 |
| 9 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 9 | 0 | 15 | 0 |
| 10 | a48 pauper-v2.0.0 | -0.462452 | 919.7 | [763.1, 1047.6] | 16 | 4 | 0 | 12 | 0 |
| 11 | kit-mad-k 0.3.0+a49c05ddab71 | -1.704011 | 704.0 | [551.1, 923.6] | 8 | 0 | 0 | 8 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | -1.704011 | 704.0 | [551.1, 923.6] | 8 | 0 | 0 | 8 | 0 |
| 13 | kit-mad-1 0.3.0+4e575c6a49fc | -1.704011 | 704.0 | [551.1, 923.6] | 8 | 0 | 0 | 8 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.753739 | 1652.1 | [1553.6, 1768.8] | 94 | 84 | 0 | 10 | 0 |
| 2 | a48 pauper-v2.0.0 | 2.805543 | 1487.4 | [1384.4, 1600.5] | 16 | 10 | 0 | 6 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.798228 | 1486.1 | [1159.9, 1697.6] | 8 | 2 | 0 | 6 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 2.798228 | 1486.1 | [1159.9, 1697.6] | 8 | 2 | 0 | 6 | 0 |
| 5 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.454456 | 1426.4 | [1131.3, 1666.6] | 6 | 1 | 0 | 5 | 0 |
| 6 | kit-mad-k 0.3.0+a49c05ddab71 | 2.144301 | 1372.5 | [1084.7, 1616.6] | 8 | 1 | 0 | 7 | 0 |
| 7 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.144301 | 1372.5 | [1084.7, 1619.0] | 8 | 1 | 0 | 7 | 0 |
| 8 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.144301 | 1372.5 | [1084.7, 1619.0] | 8 | 1 | 0 | 7 | 0 |
| 9 | c12 pauper-v2.0.0 | 1.399731 | 1243.2 | [1079.6, 1384.4] | 16 | 7 | 0 | 9 | 0 |
| 10 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.920526 | 1159.9 | [1061.4, 1276.6] | 8 | 0 | 0 | 8 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.920526 | 1159.9 | [1061.4, 1276.6] | 8 | 0 | 0 | 8 | 0 |
| 12 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.920526 | 1159.9 | [1061.4, 1276.6] | 8 | 0 | 0 | 8 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 744 | 0 | 0.000 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 40 | 0 | 0.000 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 64 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 64 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| kit-mcts-custom 0.3.0+25b213ad6a3c | 64 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |

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
