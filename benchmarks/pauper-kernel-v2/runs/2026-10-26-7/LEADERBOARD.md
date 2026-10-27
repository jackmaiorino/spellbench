# Spellbench leaderboard: pauper-bo1

- Games: 2304 played, 2304 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.484296 | 1431.6 | [1352.8, 1522.5] | 192 | 139 | 0 | 53 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.203298 | 1382.8 | [1315.7, 1460.9] | 832 | 605 | 0 | 227 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.496095 | 1259.9 | [1176.1, 1346.3] | 192 | 97 | 0 | 95 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.474208 | 1256.1 | [1176.9, 1343.2] | 192 | 96 | 0 | 96 | 0 |
| 5 | kit-mad-1 0.3.0+4e575c6a49fc | 1.430445 | 1248.5 | [1167.4, 1334.8] | 192 | 94 | 0 | 98 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.254903 | 1218.0 | [1137.8, 1306.6] | 192 | 86 | 0 | 106 | 0 |
| 7 | kit-mad-k 0.3.0+a49c05ddab71 | 1.232832 | 1214.2 | [1133.3, 1300.4] | 192 | 85 | 0 | 107 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.223471 | 1212.5 | [1152.0, 1283.3] | 832 | 411 | 0 | 421 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.210718 | 1210.3 | [1130.0, 1299.4] | 192 | 84 | 0 | 108 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.166340 | 1202.6 | [1123.6, 1292.3] | 192 | 82 | 0 | 110 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.054297 | 1183.2 | [1102.5, 1268.3] | 192 | 77 | 0 | 115 | 0 |
| 12 | a48 pauper-v2.0.0 | 1.017438 | 1176.7 | [1114.2, 1249.7] | 832 | 368 | 0 | 464 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.190398 | 1033.1 | [942.8, 1125.6] | 192 | 43 | 0 | 149 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 37 | 0 | 155 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| gorge-legacy | g115 | 64 | 18 | 0 | 46 | 0.2812 | [0.1562, 0.4062] | 0.0043 |
| gorge-legacy | c12 | 64 | 29 | 0 | 35 | 0.4531 | [0.3281, 0.5781] | 0.6291 |
| gorge-legacy | a48 | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8145 |
| kit-mad-k | g115 | 64 | 15 | 0 | 49 | 0.2344 | [0.1250, 0.3594] | 0.0005 |
| kit-mad-k | c12 | 64 | 29 | 0 | 35 | 0.4531 | [0.3281, 0.5938] | 0.6476 |
| kit-mad-k | a48 | 64 | 41 | 0 | 23 | 0.6406 | [0.5156, 0.7500] | 0.0490 |
| kit-mcts-custom | g115 | 64 | 6 | 0 | 58 | 0.0938 | [0.0312, 0.1875] | 0.0000 |
| kit-mcts-custom | c12 | 64 | 14 | 0 | 50 | 0.2188 | [0.1094, 0.3594] | 0.0005 |
| kit-mcts-custom | a48 | 64 | 23 | 0 | 41 | 0.3594 | [0.2344, 0.4844] | 0.0784 |
| oh2-r2s1-b512 | g115 | 64 | 34 | 0 | 30 | 0.5312 | [0.4062, 0.6562] | 0.8145 |
| oh2-r2s1-b512 | c12 | 64 | 53 | 0 | 11 | 0.8281 | [0.7500, 0.9062] | 0.0000 |
| oh2-r2s1-b512 | a48 | 64 | 52 | 0 | 12 | 0.8125 | [0.7344, 0.8906] | 0.0000 |
| g115 | kit-mad-1 | 64 | 43 | 0 | 21 | 0.6719 | [0.5469, 0.7812] | 0.0192 |
| g115 | uniform | 64 | 54 | 0 | 10 | 0.8438 | [0.7344, 0.9375] | 0.0000 |
| g115 | gorge-explore | 64 | 38 | 0 | 26 | 0.5938 | [0.4531, 0.7188] | 0.2379 |
| g115 | gorge-bot | 64 | 48 | 0 | 16 | 0.7500 | [0.6250, 0.8594] | 0.0009 |
| g115 | gorge-lethal-pressure | 64 | 46 | 0 | 18 | 0.7188 | [0.5938, 0.8281] | 0.0026 |
| g115 | c12 | 64 | 49 | 0 | 15 | 0.7656 | [0.6406, 0.8750] | 0.0005 |
| g115 | gorge-ar8 | 64 | 42 | 0 | 22 | 0.6562 | [0.5469, 0.7656] | 0.0309 |
| g115 | gorge-blocks | 64 | 49 | 0 | 15 | 0.7656 | [0.6562, 0.8750] | 0.0002 |
| g115 | a48 | 64 | 53 | 0 | 11 | 0.8281 | [0.7188, 0.9219] | 0.0000 |
| kit-mad-1 | c12 | 64 | 32 | 0 | 32 | 0.5000 | [0.3594, 0.6406] | 1.0000 |
| kit-mad-1 | a48 | 64 | 41 | 0 | 23 | 0.6406 | [0.5156, 0.7656] | 0.0636 |
| uniform | c12 | 64 | 9 | 0 | 55 | 0.1406 | [0.0625, 0.2188] | 0.0000 |
| uniform | a48 | 64 | 18 | 0 | 46 | 0.2812 | [0.1719, 0.4062] | 0.0043 |
| gorge-explore | c12 | 64 | 34 | 0 | 30 | 0.5312 | [0.4219, 0.6406] | 0.7905 |
| gorge-explore | a48 | 64 | 36 | 0 | 28 | 0.5625 | [0.4375, 0.6875] | 0.4807 |
| gorge-bot | c12 | 64 | 37 | 0 | 27 | 0.5781 | [0.4531, 0.7031] | 0.3323 |
| gorge-bot | a48 | 64 | 31 | 0 | 33 | 0.4844 | [0.3750, 0.6094] | 1.0000 |
| gorge-lethal-pressure | c12 | 64 | 29 | 0 | 35 | 0.4531 | [0.3438, 0.5781] | 0.6072 |
| gorge-lethal-pressure | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1671 |
| c12 | gorge-ar8 | 64 | 28 | 0 | 36 | 0.4375 | [0.3125, 0.5625] | 0.4545 |
| c12 | gorge-blocks | 64 | 27 | 0 | 37 | 0.4219 | [0.3125, 0.5312] | 0.3018 |
| c12 | a48 | 64 | 31 | 0 | 33 | 0.4844 | [0.3594, 0.6094] | 1.0000 |
| gorge-ar8 | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7188] | 0.1435 |
| gorge-blocks | a48 | 64 | 30 | 0 | 34 | 0.4688 | [0.3594, 0.5781] | 0.7744 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 192 | 139 | 0 | 53 |
| g115 pauper-v2.0.0 | -0.132238 | 977.0 | 192 | 132 | 0 | 60 |
| c12 pauper-v2.0.0 | -1.468546 | 744.9 | 192 | 57 | 0 | 135 |
| a48 pauper-v2.0.0 | -1.487420 | 741.6 | 192 | 56 | 0 | 136 |

### tag: search

skipped: no_rated_games

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 2.237664 | 1388.7 | [1223.8, 1625.6] | 24 | 17 | 0 | 7 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 2.237664 | 1388.7 | [1223.2, 1614.0] | 24 | 17 | 0 | 7 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.070687 | 1359.7 | [1232.5, 1561.7] | 104 | 78 | 0 | 26 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 1.894979 | 1329.2 | [1167.0, 1546.1] | 24 | 15 | 0 | 9 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.418857 | 1246.5 | [1087.2, 1471.2] | 24 | 12 | 0 | 12 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.137994 | 1197.7 | [1068.2, 1381.1] | 104 | 54 | 0 | 50 | 0 |
| 7 | a48 pauper-v2.0.0 | 1.064536 | 1184.9 | [1038.0, 1378.9] | 104 | 52 | 0 | 52 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.944496 | 1164.1 | [1000.0, 1365.5] | 24 | 9 | 0 | 15 | 0 |
| 9 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.778524 | 1135.2 | [962.0, 1364.1] | 24 | 8 | 0 | 16 | 0 |
| 10 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.778524 | 1135.2 | [905.0, 1392.7] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.604889 | 1105.1 | [903.7, 1328.8] | 24 | 7 | 0 | 17 | 0 |
| 12 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.220908 | 1038.4 | [859.7, 1265.9] | 24 | 5 | 0 | 19 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.552792 | 904.0 | [701.6, 1119.5] | 24 | 2 | 0 | 22 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.503414 | 1608.6 | [1427.7, 1842.2] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.403136 | 1591.2 | [1472.2, 1735.4] | 104 | 88 | 0 | 16 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.768760 | 1481.0 | [1301.8, 1698.0] | 24 | 14 | 0 | 10 | 0 |
| 4 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.269143 | 1394.2 | [1239.0, 1576.4] | 24 | 11 | 0 | 13 | 0 |
| 5 | c12 pauper-v2.0.0 | 2.122685 | 1368.7 | [1251.7, 1494.9] | 104 | 58 | 0 | 46 | 0 |
| 6 | a48 pauper-v2.0.0 | 1.826391 | 1317.3 | [1184.4, 1441.3] | 104 | 50 | 0 | 54 | 0 |
| 7 | kit-mad-k 0.3.0+a49c05ddab71 | 1.759679 | 1305.7 | [1137.3, 1492.7] | 24 | 8 | 0 | 16 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.759679 | 1305.7 | [1139.5, 1471.7] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.759679 | 1305.7 | [1120.6, 1494.5] | 24 | 8 | 0 | 16 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.759679 | 1305.7 | [1170.4, 1460.9] | 24 | 8 | 0 | 16 | 0 |
| 11 | kit-mad-1 0.3.0+4e575c6a49fc | 1.578515 | 1274.2 | [1085.2, 1470.5] | 24 | 7 | 0 | 17 | 0 |
| 12 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.180715 | 1205.1 | [1084.6, 1340.7] | 24 | 5 | 0 | 19 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.953480 | 1165.6 | [1000.0, 1340.4] | 24 | 4 | 0 | 20 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.471509 | 1429.3 | [1306.7, 1580.9] | 24 | 23 | 0 | 1 | 0 |
| 2 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.128768 | 1196.1 | [1053.3, 1390.8] | 24 | 18 | 0 | 6 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.947598 | 1164.6 | [1053.6, 1286.0] | 24 | 17 | 0 | 7 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 0.614965 | 1106.8 | [947.1, 1271.1] | 24 | 15 | 0 | 9 | 0 |
| 5 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.614965 | 1106.8 | [973.8, 1249.3] | 24 | 15 | 0 | 9 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.614965 | 1106.8 | [972.5, 1269.8] | 24 | 15 | 0 | 9 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.457923 | 1079.5 | [972.9, 1190.8] | 24 | 14 | 0 | 10 | 0 |
| 8 | c12 pauper-v2.0.0 | 0.423810 | 1073.6 | [996.5, 1152.4] | 104 | 50 | 0 | 54 | 0 |
| 9 | g115 pauper-v2.0.0 | 0.320055 | 1055.6 | [972.4, 1140.8] | 104 | 47 | 0 | 57 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 0.304239 | 1052.9 | [919.8, 1169.7] | 24 | 13 | 0 | 11 | 0 |
| 11 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 11 | 0 | 13 | 0 |
| 12 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [875.5, 1134.8] | 24 | 11 | 0 | 13 | 0 |
| 13 | a48 pauper-v2.0.0 | -0.292554 | 949.2 | [856.6, 1031.4] | 104 | 30 | 0 | 74 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.311192 | 945.9 | [770.4, 1106.6] | 24 | 9 | 0 | 15 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.273061 | 1568.6 | [1381.9, 1855.7] | 24 | 20 | 0 | 4 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.726169 | 1473.6 | [1356.7, 1652.5] | 104 | 88 | 0 | 16 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.583435 | 1275.1 | [1158.6, 1437.0] | 24 | 11 | 0 | 13 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.504175 | 1261.3 | [1142.4, 1433.1] | 104 | 60 | 0 | 44 | 0 |
| 5 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.415981 | 1246.0 | [1097.5, 1439.4] | 24 | 10 | 0 | 14 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.415981 | 1246.0 | [1102.3, 1431.0] | 24 | 10 | 0 | 14 | 0 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.070612 | 1186.0 | [1000.0, 1389.7] | 24 | 8 | 0 | 16 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.070612 | 1186.0 | [1034.9, 1372.2] | 24 | 8 | 0 | 16 | 0 |
| 9 | a48 pauper-v2.0.0 | 1.062932 | 1184.7 | [1067.1, 1336.1] | 104 | 48 | 0 | 56 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.888246 | 1154.3 | [1000.0, 1340.9] | 24 | 7 | 0 | 17 | 0 |
| 11 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.695461 | 1120.8 | [922.9, 1323.0] | 24 | 6 | 0 | 18 | 0 |
| 12 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.695461 | 1120.8 | [963.4, 1306.4] | 24 | 6 | 0 | 18 | 0 |
| 13 | kit-mad-k 0.3.0+a49c05ddab71 | 0.000000 | 1000.0 | [822.7, 1179.4] | 24 | 3 | 0 | 21 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 1.940943 | 1337.2 | [1215.6, 1502.4] | 104 | 77 | 0 | 27 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.716580 | 1298.2 | [1171.8, 1460.3] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.540739 | 1267.7 | [1114.7, 1443.9] | 24 | 15 | 0 | 9 | 0 |
| 4 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.370680 | 1238.1 | [1058.1, 1461.7] | 24 | 14 | 0 | 10 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.370680 | 1238.1 | [1083.6, 1434.3] | 24 | 14 | 0 | 10 | 0 |
| 6 | oh2-r2s1-b512 pauper-v2.0.0 | 1.370680 | 1238.1 | [1089.8, 1409.2] | 24 | 14 | 0 | 10 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.370680 | 1238.1 | [1086.0, 1428.5] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.040254 | 1180.7 | [1000.0, 1359.7] | 24 | 12 | 0 | 12 | 0 |
| 9 | a48 pauper-v2.0.0 | 0.803298 | 1139.5 | [1025.1, 1285.5] | 104 | 45 | 0 | 59 | 0 |
| 10 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.711613 | 1123.6 | [939.1, 1312.6] | 24 | 10 | 0 | 14 | 0 |
| 11 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.543754 | 1094.5 | [930.3, 1280.5] | 24 | 9 | 0 | 15 | 0 |
| 12 | c12 pauper-v2.0.0 | 0.411851 | 1071.5 | [954.9, 1211.4] | 104 | 34 | 0 | 70 | 0 |
| 13 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.370944 | 1064.4 | [915.8, 1219.4] | 24 | 8 | 0 | 16 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 6 | 0 | 18 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.085896 | 1362.4 | [1248.4, 1537.0] | 24 | 15 | 0 | 9 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.085896 | 1362.4 | [1227.1, 1565.4] | 24 | 15 | 0 | 9 | 0 |
| 3 | g115 pauper-v2.0.0 | 1.939877 | 1337.0 | [1234.7, 1486.3] | 104 | 69 | 0 | 35 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.930299 | 1335.3 | [1175.2, 1536.8] | 24 | 14 | 0 | 10 | 0 |
| 5 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.778131 | 1308.9 | [1151.3, 1504.4] | 24 | 13 | 0 | 11 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.627627 | 1282.7 | [1123.3, 1476.8] | 24 | 12 | 0 | 12 | 0 |
| 7 | a48 pauper-v2.0.0 | 1.577865 | 1274.1 | [1164.9, 1423.6] | 104 | 59 | 0 | 45 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.477135 | 1256.6 | [1121.6, 1427.0] | 24 | 11 | 0 | 13 | 0 |
| 9 | c12 pauper-v2.0.0 | 1.366163 | 1237.3 | [1124.1, 1382.7] | 104 | 53 | 0 | 51 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 1.008502 | 1175.2 | [1000.0, 1379.4] | 24 | 8 | 0 | 16 | 0 |
| 11 | kit-mad-1 0.3.0+4e575c6a49fc | 0.839684 | 1145.9 | [965.7, 1326.6] | 24 | 7 | 0 | 17 | 0 |
| 12 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.659869 | 1114.6 | [956.6, 1293.7] | 24 | 6 | 0 | 18 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.000000 | 1000.0 | [743.0, 1229.0] | 24 | 3 | 0 | 21 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.481020 | 1431.0 | [1260.0, 1671.3] | 24 | 20 | 0 | 4 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.037564 | 1354.0 | [1169.9, 1607.6] | 24 | 18 | 0 | 6 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.037564 | 1354.0 | [1162.9, 1612.5] | 24 | 18 | 0 | 6 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.651926 | 1287.0 | [1094.9, 1536.9] | 24 | 16 | 0 | 8 | 0 |
| 5 | g115 pauper-v2.0.0 | 1.563047 | 1271.5 | [1125.0, 1487.5] | 104 | 64 | 0 | 40 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.487020 | 1258.3 | [1109.2, 1472.4] | 104 | 62 | 0 | 42 | 0 |
| 7 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.292362 | 1224.5 | [1059.8, 1459.5] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.292362 | 1224.5 | [1061.9, 1445.7] | 24 | 14 | 0 | 10 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.116236 | 1193.9 | [1000.0, 1430.0] | 24 | 13 | 0 | 11 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 0.762172 | 1132.4 | [967.9, 1343.0] | 24 | 11 | 0 | 13 | 0 |
| 11 | kit-mad-1 0.3.0+4e575c6a49fc | 0.201915 | 1035.1 | [852.5, 1267.9] | 24 | 8 | 0 | 16 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 7 | 0 | 17 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.213739 | 962.9 | [781.4, 1185.4] | 24 | 6 | 0 | 18 | 0 |
| 14 | a48 pauper-v2.0.0 | -0.351021 | 939.0 | [757.2, 1151.8] | 104 | 17 | 0 | 87 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.459398 | 1601.0 | [1486.2, 1783.5] | 104 | 94 | 0 | 10 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.966664 | 1515.4 | [1383.2, 1711.5] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 2.583196 | 1448.7 | [1275.8, 1671.9] | 24 | 14 | 0 | 10 | 0 |
| 4 | a48 pauper-v2.0.0 | 2.130915 | 1370.2 | [1264.0, 1541.5] | 104 | 67 | 0 | 37 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 2.031821 | 1353.0 | [1224.7, 1540.7] | 24 | 11 | 0 | 13 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.661326 | 1288.6 | [1157.5, 1480.9] | 24 | 9 | 0 | 15 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.469988 | 1255.4 | [1056.6, 1472.7] | 24 | 8 | 0 | 16 | 0 |
| 8 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.271557 | 1220.9 | [1048.5, 1427.3] | 24 | 7 | 0 | 17 | 0 |
| 9 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.271557 | 1220.9 | [1042.2, 1423.5] | 24 | 7 | 0 | 17 | 0 |
| 10 | c12 pauper-v2.0.0 | 1.086537 | 1188.8 | [1072.0, 1361.4] | 104 | 40 | 0 | 64 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.839891 | 1145.9 | [945.3, 1351.3] | 24 | 5 | 0 | 19 | 0 |
| 12 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.839891 | 1145.9 | [875.9, 1371.7] | 24 | 5 | 0 | 19 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.321942 | 1055.9 | [825.6, 1267.2] | 24 | 3 | 0 | 21 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 832 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 192 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 832 | 0 | 0.000 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 832 | 0 | 0.000 | 0 | 0.000 |
| kit-mcts-custom 0.3.0+25b213ad6a3c | 192 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |

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
