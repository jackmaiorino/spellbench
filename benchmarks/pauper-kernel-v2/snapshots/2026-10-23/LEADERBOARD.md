# Spellbench leaderboard: pauper-bo1

- Games: 2496 played, 2496 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh1-r2s1-b128 pauper-v2.0.0 | 2.644990 | 1459.5 | [1373.6, 1553.2] | 192 | 141 | 0 | 51 | 0 |
| 2 | r2-b20 pauper-v2.0.0 | 2.512459 | 1436.5 | [1357.7, 1532.9] | 192 | 136 | 0 | 56 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.233543 | 1388.0 | [1320.9, 1472.0] | 896 | 615 | 0 | 281 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.639438 | 1284.8 | [1200.9, 1380.1] | 192 | 98 | 0 | 94 | 0 |
| 5 | kit-mad-1 0.3.0+4e575c6a49fc | 1.596308 | 1277.3 | [1193.8, 1371.8] | 192 | 96 | 0 | 96 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.510052 | 1262.3 | [1182.4, 1351.1] | 192 | 92 | 0 | 100 | 0 |
| 7 | kit-mad-k 0.3.0+a49c05ddab71 | 1.488464 | 1258.6 | [1176.6, 1349.3] | 192 | 91 | 0 | 101 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.365214 | 1237.2 | [1169.7, 1317.7] | 896 | 430 | 0 | 466 | 0 |
| 9 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.358399 | 1236.0 | [1148.8, 1328.4] | 192 | 85 | 0 | 107 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.336589 | 1232.2 | [1145.1, 1326.7] | 192 | 84 | 0 | 108 | 0 |
| 11 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.336589 | 1232.2 | [1151.4, 1325.1] | 192 | 84 | 0 | 108 | 0 |
| 12 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.292816 | 1224.6 | [1142.7, 1310.5] | 192 | 82 | 0 | 110 | 0 |
| 13 | a48 pauper-v2.0.0 | 1.204946 | 1209.3 | [1140.9, 1285.2] | 896 | 395 | 0 | 501 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.035650 | 1006.2 | [918.3, 1098.9] | 192 | 34 | 0 | 158 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 33 | 0 | 159 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| gorge-legacy | g115 | 64 | 18 | 0 | 46 | 0.2812 | [0.1562, 0.4219] | 0.0066 |
| gorge-legacy | c12 | 64 | 36 | 0 | 28 | 0.5625 | [0.4375, 0.6875] | 0.4807 |
| gorge-legacy | a48 | 64 | 31 | 0 | 33 | 0.4844 | [0.3750, 0.6094] | 1.0000 |
| uniform | g115 | 64 | 10 | 0 | 54 | 0.1562 | [0.0625, 0.2812] | 0.0000 |
| uniform | c12 | 64 | 11 | 0 | 53 | 0.1719 | [0.0781, 0.2812] | 0.0000 |
| uniform | a48 | 64 | 12 | 0 | 52 | 0.1875 | [0.0938, 0.2812] | 0.0000 |
| kit-mad-k | g115 | 64 | 17 | 0 | 47 | 0.2656 | [0.1562, 0.3906] | 0.0026 |
| kit-mad-k | c12 | 64 | 32 | 0 | 32 | 0.5000 | [0.3750, 0.6250] | 1.0000 |
| kit-mad-k | a48 | 64 | 42 | 0 | 22 | 0.6562 | [0.5156, 0.7812] | 0.0414 |
| kit-mcts-custom | g115 | 64 | 5 | 0 | 59 | 0.0781 | [0.0156, 0.1562] | 0.0000 |
| kit-mcts-custom | c12 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3438] | 0.0001 |
| kit-mcts-custom | a48 | 64 | 13 | 0 | 51 | 0.2031 | [0.1250, 0.2969] | 0.0000 |
| g115 | oh1-r2s1-b128 | 64 | 27 | 0 | 37 | 0.4219 | [0.2812, 0.5469] | 0.3593 |
| g115 | kit-mad-1 | 64 | 44 | 0 | 20 | 0.6875 | [0.5781, 0.7969] | 0.0075 |
| g115 | gorge-explore | 64 | 46 | 0 | 18 | 0.7188 | [0.6094, 0.8281] | 0.0013 |
| g115 | gorge-bot | 64 | 47 | 0 | 17 | 0.7344 | [0.6094, 0.8438] | 0.0015 |
| g115 | gorge-lethal-pressure | 64 | 43 | 0 | 21 | 0.6719 | [0.5312, 0.8125] | 0.0433 |
| g115 | c12 | 64 | 44 | 0 | 20 | 0.6875 | [0.5625, 0.8125] | 0.0169 |
| g115 | gorge-ar8 | 64 | 51 | 0 | 13 | 0.7969 | [0.6875, 0.8906] | 0.0001 |
| g115 | gorge-blocks | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1671 |
| g115 | a48 | 64 | 41 | 0 | 23 | 0.6406 | [0.5156, 0.7812] | 0.0784 |
| g115 | r2-b20 | 64 | 27 | 0 | 37 | 0.4219 | [0.3125, 0.5312] | 0.2668 |
| oh1-r2s1-b128 | c12 | 64 | 50 | 0 | 14 | 0.7812 | [0.6875, 0.8750] | 0.0000 |
| oh1-r2s1-b128 | a48 | 64 | 54 | 0 | 10 | 0.8438 | [0.7500, 0.9219] | 0.0000 |
| kit-mad-1 | c12 | 64 | 36 | 0 | 28 | 0.5625 | [0.4375, 0.6875] | 0.4807 |
| kit-mad-1 | a48 | 64 | 40 | 0 | 24 | 0.6250 | [0.4844, 0.7656] | 0.1338 |
| gorge-explore | c12 | 64 | 36 | 0 | 28 | 0.5625 | [0.4531, 0.6719] | 0.4240 |
| gorge-explore | a48 | 64 | 38 | 0 | 26 | 0.5938 | [0.4688, 0.7188] | 0.2101 |
| gorge-bot | c12 | 64 | 26 | 0 | 38 | 0.4062 | [0.3125, 0.5156] | 0.1460 |
| gorge-bot | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.5156, 0.7188] | 0.0923 |
| gorge-lethal-pressure | c12 | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8145 |
| gorge-lethal-pressure | a48 | 64 | 33 | 0 | 31 | 0.5156 | [0.3906, 0.6406] | 1.0000 |
| c12 | gorge-ar8 | 64 | 32 | 0 | 32 | 0.5000 | [0.3750, 0.6250] | 1.0000 |
| c12 | gorge-blocks | 64 | 28 | 0 | 36 | 0.4375 | [0.3281, 0.5469] | 0.4240 |
| c12 | a48 | 64 | 36 | 0 | 28 | 0.5625 | [0.4375, 0.6875] | 0.4807 |
| c12 | r2-b20 | 64 | 11 | 0 | 53 | 0.1719 | [0.0781, 0.2656] | 0.0000 |
| gorge-ar8 | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1671 |
| gorge-blocks | a48 | 64 | 37 | 0 | 27 | 0.5781 | [0.4375, 0.7031] | 0.3593 |
| a48 | r2-b20 | 64 | 18 | 0 | 46 | 0.2812 | [0.1719, 0.3906] | 0.0013 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh1-r2s1-b128 pauper-v2.0.0 | 0.495577 | 1086.1 | 192 | 141 | 0 | 51 |
| r2-b20 pauper-v2.0.0 | 0.364819 | 1063.4 | 192 | 136 | 0 | 56 |
| g115 pauper-v2.0.0 | 0.000000 | 1000.0 | 256 | 139 | 0 | 117 |
| c12 pauper-v2.0.0 | -0.787693 | 863.2 | 256 | 81 | 0 | 175 |
| a48 pauper-v2.0.0 | -0.816632 | 858.1 | 256 | 79 | 0 | 177 |

### tag: search

skipped: no_rated_games

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-1 0.3.0+4e575c6a49fc | 3.345768 | 1581.2 | [1443.6, 1750.3] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.950266 | 1512.5 | [1381.4, 1658.6] | 112 | 81 | 0 | 31 | 0 |
| 3 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.820169 | 1489.9 | [1324.6, 1695.2] | 24 | 15 | 0 | 9 | 0 |
| 4 | r2-b20 pauper-v2.0.0 | 2.820169 | 1489.9 | [1338.5, 1679.8] | 24 | 15 | 0 | 9 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 2.659568 | 1462.0 | [1290.5, 1658.0] | 24 | 14 | 0 | 10 | 0 |
| 6 | oh1-r2s1-b128 pauper-v2.0.0 | 2.659568 | 1462.0 | [1286.7, 1667.8] | 24 | 14 | 0 | 10 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.347276 | 1407.8 | [1258.3, 1592.5] | 24 | 12 | 0 | 12 | 0 |
| 8 | c12 pauper-v2.0.0 | 2.121773 | 1368.6 | [1252.2, 1498.4] | 112 | 58 | 0 | 54 | 0 |
| 9 | a48 pauper-v2.0.0 | 1.982474 | 1344.4 | [1231.2, 1466.7] | 112 | 54 | 0 | 58 | 0 |
| 10 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.710575 | 1297.2 | [1115.6, 1488.6] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.537724 | 1267.1 | [1116.4, 1429.1] | 24 | 7 | 0 | 17 | 0 |
| 12 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.354020 | 1235.2 | [1066.5, 1401.2] | 24 | 6 | 0 | 18 | 0 |
| 13 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.354020 | 1235.2 | [1095.8, 1393.8] | 24 | 6 | 0 | 18 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.683344 | 1118.7 | [933.3, 1298.6] | 24 | 3 | 0 | 21 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh1-r2s1-b128 pauper-v2.0.0 | 2.583208 | 1448.7 | [1258.1, 1692.9] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.553549 | 1443.6 | [1290.1, 1659.9] | 112 | 94 | 0 | 18 | 0 |
| 3 | r2-b20 pauper-v2.0.0 | 2.381537 | 1413.7 | [1210.1, 1680.4] | 24 | 17 | 0 | 7 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.834217 | 1318.6 | [1128.7, 1572.2] | 24 | 14 | 0 | 10 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.326298 | 1230.4 | [1031.4, 1486.8] | 24 | 11 | 0 | 13 | 0 |
| 6 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.157685 | 1201.1 | [1000.0, 1435.5] | 24 | 10 | 0 | 14 | 0 |
| 7 | a48 pauper-v2.0.0 | 1.070113 | 1185.9 | [1033.1, 1388.0] | 112 | 57 | 0 | 55 | 0 |
| 8 | kit-mad-k 0.3.0+a49c05ddab71 | 0.986563 | 1171.4 | [966.5, 1406.0] | 24 | 9 | 0 | 15 | 0 |
| 9 | c12 pauper-v2.0.0 | 0.926964 | 1161.0 | [986.8, 1374.2] | 112 | 53 | 0 | 59 | 0 |
| 10 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.810908 | 1140.9 | [967.9, 1365.7] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.628256 | 1109.1 | [923.5, 1341.4] | 24 | 7 | 0 | 17 | 0 |
| 12 | kit-mad-1 0.3.0+4e575c6a49fc | 0.228119 | 1039.6 | [842.9, 1273.5] | 24 | 5 | 0 | 19 | 0 |
| 13 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [753.7, 1242.3] | 24 | 4 | 0 | 20 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |
| 15 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.955191 | 834.1 | [623.6, 1067.8] | 24 | 1 | 0 | 23 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | r2-b20 pauper-v2.0.0 | 2.611012 | 1453.6 | [1361.3, 1566.9] | 24 | 24 | 0 | 0 | 0 |
| 2 | oh1-r2s1-b128 pauper-v2.0.0 | 2.052566 | 1356.6 | [1204.4, 1537.2] | 24 | 23 | 0 | 1 | 0 |
| 3 | kit-mad-k 0.3.0+a49c05ddab71 | 0.687398 | 1119.4 | [971.2, 1281.1] | 24 | 18 | 0 | 6 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 0.501950 | 1087.2 | [940.9, 1260.2] | 24 | 17 | 0 | 7 | 0 |
| 5 | c12 pauper-v2.0.0 | 0.267799 | 1046.5 | [933.1, 1171.0] | 112 | 59 | 0 | 53 | 0 |
| 6 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.161033 | 1028.0 | [887.9, 1170.5] | 24 | 15 | 0 | 9 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [833.5, 1172.0] | 24 | 14 | 0 | 10 | 0 |
| 9 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [833.3, 1169.1] | 24 | 14 | 0 | 10 | 0 |
| 10 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.157565 | 972.6 | [832.9, 1111.5] | 24 | 13 | 0 | 11 | 0 |
| 11 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.313423 | 945.6 | [803.4, 1110.6] | 24 | 12 | 0 | 12 | 0 |
| 12 | a48 pauper-v2.0.0 | -0.381699 | 933.7 | [825.6, 1047.1] | 112 | 40 | 0 | 72 | 0 |
| 13 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.469220 | 918.5 | [776.6, 1056.0] | 24 | 11 | 0 | 13 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.626603 | 891.1 | [741.0, 1053.1] | 24 | 10 | 0 | 14 | 0 |
| 15 | g115 pauper-v2.0.0 | -0.821203 | 857.3 | [747.2, 962.3] | 112 | 28 | 0 | 84 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | r2-b20 pauper-v2.0.0 | 2.863781 | 1497.5 | [1388.7, 1640.7] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.682297 | 1466.0 | [1389.3, 1598.0] | 112 | 93 | 0 | 19 | 0 |
| 3 | oh1-r2s1-b128 pauper-v2.0.0 | 2.480276 | 1430.9 | [1331.1, 1575.9] | 24 | 16 | 0 | 8 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.812022 | 1314.8 | [1246.0, 1437.9] | 112 | 72 | 0 | 40 | 0 |
| 5 | kit-mad-1 0.3.0+4e575c6a49fc | 1.620544 | 1281.5 | [1173.0, 1429.6] | 24 | 11 | 0 | 13 | 0 |
| 6 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.450156 | 1251.9 | [1145.9, 1382.7] | 24 | 10 | 0 | 14 | 0 |
| 7 | kit-mad-k 0.3.0+a49c05ddab71 | 1.097206 | 1190.6 | [1041.3, 1346.2] | 24 | 8 | 0 | 16 | 0 |
| 8 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.097206 | 1190.6 | [1075.7, 1342.7] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.910281 | 1158.1 | [1000.0, 1332.7] | 24 | 7 | 0 | 17 | 0 |
| 10 | a48 pauper-v2.0.0 | 0.868435 | 1150.9 | [1080.4, 1277.1] | 112 | 45 | 0 | 67 | 0 |
| 11 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.712497 | 1123.8 | [945.1, 1296.9] | 24 | 6 | 0 | 18 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.499606 | 1086.8 | [900.5, 1248.2] | 24 | 5 | 0 | 19 | 0 |
| 13 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.499606 | 1086.8 | [1000.0, 1211.9] | 24 | 5 | 0 | 19 | 0 |
| 14 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.499606 | 1086.8 | [900.8, 1251.0] | 24 | 5 | 0 | 19 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.928432 | 1508.7 | [1404.2, 1680.8] | 112 | 80 | 0 | 32 | 0 |
| 2 | oh1-r2s1-b128 pauper-v2.0.0 | 2.721041 | 1472.7 | [1299.4, 1673.5] | 24 | 16 | 0 | 8 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.721041 | 1472.7 | [1335.6, 1647.9] | 24 | 16 | 0 | 8 | 0 |
| 4 | r2-b20 pauper-v2.0.0 | 2.721041 | 1472.7 | [1375.5, 1639.5] | 24 | 16 | 0 | 8 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 2.545244 | 1442.2 | [1299.4, 1639.6] | 24 | 15 | 0 | 9 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.545244 | 1442.2 | [1323.0, 1615.1] | 24 | 15 | 0 | 9 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.545244 | 1442.2 | [1315.5, 1628.3] | 24 | 15 | 0 | 9 | 0 |
| 8 | kit-mad-1 0.3.0+4e575c6a49fc | 2.208689 | 1383.7 | [1193.2, 1611.5] | 24 | 13 | 0 | 11 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.044224 | 1355.1 | [1216.6, 1536.5] | 24 | 12 | 0 | 12 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.044224 | 1355.1 | [1242.0, 1525.8] | 24 | 12 | 0 | 12 | 0 |
| 11 | a48 pauper-v2.0.0 | 1.879908 | 1326.6 | [1226.7, 1488.5] | 112 | 49 | 0 | 63 | 0 |
| 12 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.714676 | 1297.9 | [1143.1, 1475.3] | 24 | 10 | 0 | 14 | 0 |
| 13 | c12 pauper-v2.0.0 | 1.350898 | 1234.7 | [1126.1, 1406.2] | 112 | 34 | 0 | 78 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 1.191700 | 1207.0 | [1074.6, 1393.8] | 24 | 7 | 0 | 17 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.885681 | 1675.0 | [1631.0, 1738.5] | 112 | 83 | 0 | 29 | 0 |
| 2 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.666135 | 1636.9 | [1550.0, 1743.7] | 24 | 16 | 0 | 8 | 0 |
| 3 | oh1-r2s1-b128 pauper-v2.0.0 | 3.666135 | 1636.9 | [1519.9, 1784.4] | 24 | 16 | 0 | 8 | 0 |
| 4 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.666135 | 1636.9 | [1544.4, 1745.9] | 24 | 16 | 0 | 8 | 0 |
| 5 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.666135 | 1636.9 | [1521.9, 1778.6] | 24 | 16 | 0 | 8 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.490291 | 1606.3 | [1512.2, 1714.0] | 24 | 15 | 0 | 9 | 0 |
| 7 | r2-b20 pauper-v2.0.0 | 3.320195 | 1576.8 | [1513.7, 1667.2] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.989595 | 1519.3 | [1432.5, 1617.4] | 24 | 12 | 0 | 12 | 0 |
| 9 | a48 pauper-v2.0.0 | 2.777127 | 1482.4 | [1443.0, 1529.7] | 112 | 52 | 0 | 60 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 2.660646 | 1462.2 | [1366.6, 1557.4] | 24 | 10 | 0 | 14 | 0 |
| 11 | kit-mad-1 0.3.0+4e575c6a49fc | 2.660646 | 1462.2 | [1338.2, 1588.7] | 24 | 10 | 0 | 14 | 0 |
| 12 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.492587 | 1433.0 | [1263.6, 1582.6] | 24 | 9 | 0 | 15 | 0 |
| 13 | c12 pauper-v2.0.0 | 2.338637 | 1406.3 | [1374.8, 1438.7] | 112 | 40 | 0 | 72 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 1.257114 | 1218.4 | [1097.4, 1267.2] | 24 | 3 | 0 | 21 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.134337 | 1370.8 | [1222.4, 1570.4] | 24 | 19 | 0 | 5 | 0 |
| 2 | oh1-r2s1-b128 pauper-v2.0.0 | 1.928077 | 1334.9 | [1178.5, 1534.7] | 24 | 18 | 0 | 6 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.736399 | 1301.6 | [1146.6, 1484.3] | 24 | 17 | 0 | 7 | 0 |
| 4 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.554979 | 1270.1 | [1091.5, 1468.3] | 24 | 16 | 0 | 8 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.554979 | 1270.1 | [1122.1, 1447.7] | 24 | 16 | 0 | 8 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.388914 | 1241.3 | [1118.4, 1395.4] | 112 | 68 | 0 | 44 | 0 |
| 7 | r2-b20 pauper-v2.0.0 | 1.380655 | 1239.8 | [1031.8, 1480.4] | 24 | 15 | 0 | 9 | 0 |
| 8 | g115 pauper-v2.0.0 | 1.319099 | 1229.2 | [1106.4, 1388.7] | 112 | 66 | 0 | 46 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.877672 | 1152.5 | [1000.0, 1337.0] | 24 | 12 | 0 | 12 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.877672 | 1152.5 | [970.0, 1352.9] | 24 | 12 | 0 | 12 | 0 |
| 11 | kit-mad-1 0.3.0+4e575c6a49fc | 0.367689 | 1063.9 | [903.7, 1246.6] | 24 | 9 | 0 | 15 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 7 | 0 | 17 | 0 |
| 13 | kit-mad-k 0.3.0+a49c05ddab71 | 0.000000 | 1000.0 | [797.1, 1177.7] | 24 | 7 | 0 | 17 | 0 |
| 14 | a48 pauper-v2.0.0 | -0.135788 | 976.4 | [835.3, 1123.1] | 112 | 26 | 0 | 86 | 0 |
| 15 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.651711 | 886.8 | [711.4, 1057.1] | 24 | 4 | 0 | 20 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh1-r2s1-b128 pauper-v2.0.0 | 3.599366 | 1625.3 | [1464.7, 1880.5] | 24 | 20 | 0 | 4 | 0 |
| 2 | r2-b20 pauper-v2.0.0 | 2.962493 | 1514.6 | [1384.2, 1701.5] | 24 | 17 | 0 | 7 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.926165 | 1508.3 | [1403.0, 1688.0] | 112 | 90 | 0 | 22 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 2.260721 | 1392.7 | [1243.3, 1586.0] | 24 | 13 | 0 | 11 | 0 |
| 5 | a48 pauper-v2.0.0 | 2.158240 | 1374.9 | [1275.7, 1547.3] | 112 | 72 | 0 | 40 | 0 |
| 6 | kit-mad-k 0.3.0+a49c05ddab71 | 1.757235 | 1305.3 | [1125.1, 1505.9] | 24 | 10 | 0 | 14 | 0 |
| 7 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.757235 | 1305.3 | [1186.8, 1476.2] | 24 | 10 | 0 | 14 | 0 |
| 8 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.584646 | 1275.3 | [1150.1, 1455.4] | 24 | 9 | 0 | 15 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.220628 | 1212.0 | [1000.0, 1420.5] | 24 | 7 | 0 | 17 | 0 |
| 10 | c12 pauper-v2.0.0 | 1.183353 | 1205.6 | [1093.5, 1375.7] | 112 | 46 | 0 | 66 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.023714 | 1177.8 | [1000.0, 1369.8] | 24 | 6 | 0 | 18 | 0 |
| 12 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.811590 | 1141.0 | [952.2, 1341.4] | 24 | 5 | 0 | 19 | 0 |
| 13 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.578039 | 1100.4 | [875.6, 1312.7] | 24 | 4 | 0 | 20 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |
| 15 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.396290 | 931.2 | [772.6, 1103.0] | 24 | 1 | 0 | 23 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh1-r2s1-b128 pauper-v2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| r2-b20 pauper-v2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 192 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
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
- Reference-panel rating: entrants are compared through shared local opponents. Unplayed head-to-head matchups are not measured; matchup-specific strengths can differ from the ranking. Compatible earlier evaluations are reused, so this is a dated model measurement. Elo and its interval can change when the combined results are refitted without replaying earlier games.
- Pending, no panel results yet: llm-gpt-6-luna
