# Spellbench leaderboard: pauper-bo1

- Games: 2496 played, 2496 rated (forfeits rated as losses: 42; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.480993 | 1431.0 | [1350.1, 1521.2] | 192 | 139 | 0 | 53 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.194017 | 1381.1 | [1315.4, 1462.7] | 896 | 653 | 0 | 243 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.494263 | 1259.6 | [1181.2, 1348.6] | 192 | 97 | 0 | 95 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.472410 | 1255.8 | [1174.9, 1343.6] | 192 | 96 | 0 | 96 | 0 |
| 5 | kit-mad-1 0.3.0+4e575c6a49fc | 1.428715 | 1248.2 | [1166.6, 1338.4] | 192 | 94 | 0 | 98 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.253436 | 1217.7 | [1138.3, 1305.0] | 192 | 86 | 0 | 106 | 0 |
| 7 | kit-mad-k 0.3.0+a49c05ddab71 | 1.231398 | 1213.9 | [1134.5, 1305.8] | 192 | 85 | 0 | 107 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.215537 | 1211.2 | [1150.9, 1287.9] | 896 | 445 | 0 | 451 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.209316 | 1210.1 | [1131.5, 1301.7] | 192 | 84 | 0 | 108 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.165002 | 1202.4 | [1125.2, 1291.1] | 192 | 82 | 0 | 110 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.053119 | 1182.9 | [1101.7, 1271.8] | 192 | 77 | 0 | 115 | 0 |
| 12 | a48 pauper-v2.0.0 | 1.028908 | 1178.7 | [1114.4, 1254.0] | 896 | 403 | 0 | 493 | 0 |
| 13 | llm-gpt-6-luna 0.1.0 | 1.007818 | 1175.1 | [1091.8, 1265.2] | 192 | 75 | 0 | 117 | 42 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.190233 | 1033.0 | [943.7, 1128.6] | 192 | 43 | 0 | 149 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 37 | 0 | 155 | 0 |

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
| llm-gpt-6-luna | g115 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3594] | 0.0004 |
| llm-gpt-6-luna | c12 | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.6094] | 0.8238 |
| llm-gpt-6-luna | a48 | 64 | 29 | 0 | 35 | 0.4531 | [0.3438, 0.5625] | 0.5811 |
| oh2-r2s1-b512 | g115 | 64 | 34 | 0 | 30 | 0.5312 | [0.4062, 0.6562] | 0.8145 |
| oh2-r2s1-b512 | c12 | 64 | 53 | 0 | 11 | 0.8281 | [0.7500, 0.9062] | 0.0000 |
| oh2-r2s1-b512 | a48 | 64 | 52 | 0 | 12 | 0.8125 | [0.7344, 0.8906] | 0.0000 |
| g115 | kit-mad-1 | 64 | 43 | 0 | 21 | 0.6719 | [0.5469, 0.7969] | 0.0192 |
| g115 | uniform | 64 | 54 | 0 | 10 | 0.8438 | [0.7344, 0.9375] | 0.0000 |
| g115 | gorge-explore | 64 | 38 | 0 | 26 | 0.5938 | [0.4531, 0.7188] | 0.2379 |
| g115 | gorge-bot | 64 | 48 | 0 | 16 | 0.7500 | [0.6406, 0.8594] | 0.0009 |
| g115 | gorge-lethal-pressure | 64 | 46 | 0 | 18 | 0.7188 | [0.6094, 0.8281] | 0.0026 |
| g115 | c12 | 64 | 49 | 0 | 15 | 0.7656 | [0.6406, 0.8750] | 0.0005 |
| g115 | gorge-ar8 | 64 | 42 | 0 | 22 | 0.6562 | [0.5312, 0.7656] | 0.0309 |
| g115 | gorge-blocks | 64 | 49 | 0 | 15 | 0.7656 | [0.6562, 0.8594] | 0.0002 |
| g115 | a48 | 64 | 53 | 0 | 11 | 0.8281 | [0.7344, 0.9062] | 0.0000 |
| kit-mad-1 | c12 | 64 | 32 | 0 | 32 | 0.5000 | [0.3594, 0.6406] | 1.0000 |
| kit-mad-1 | a48 | 64 | 41 | 0 | 23 | 0.6406 | [0.5156, 0.7656] | 0.0636 |
| uniform | c12 | 64 | 9 | 0 | 55 | 0.1406 | [0.0625, 0.2188] | 0.0000 |
| uniform | a48 | 64 | 18 | 0 | 46 | 0.2812 | [0.1719, 0.4062] | 0.0043 |
| gorge-explore | c12 | 64 | 34 | 0 | 30 | 0.5312 | [0.4219, 0.6406] | 0.7905 |
| gorge-explore | a48 | 64 | 36 | 0 | 28 | 0.5625 | [0.4375, 0.6875] | 0.4807 |
| gorge-bot | c12 | 64 | 37 | 0 | 27 | 0.5781 | [0.4531, 0.7031] | 0.3323 |
| gorge-bot | a48 | 64 | 31 | 0 | 33 | 0.4844 | [0.3750, 0.5938] | 1.0000 |
| gorge-lethal-pressure | c12 | 64 | 29 | 0 | 35 | 0.4531 | [0.3438, 0.5781] | 0.6072 |
| gorge-lethal-pressure | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1671 |
| c12 | gorge-ar8 | 64 | 28 | 0 | 36 | 0.4375 | [0.3125, 0.5625] | 0.4545 |
| c12 | gorge-blocks | 64 | 27 | 0 | 37 | 0.4219 | [0.2969, 0.5469] | 0.3018 |
| c12 | a48 | 64 | 31 | 0 | 33 | 0.4844 | [0.3594, 0.6094] | 1.0000 |
| gorge-ar8 | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1435 |
| gorge-blocks | a48 | 64 | 30 | 0 | 34 | 0.4688 | [0.3594, 0.5781] | 0.7744 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: hosted-llm

skipped: fewer_than_two_bots

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
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 2.237387 | 1388.7 | [1216.2, 1623.2] | 24 | 17 | 0 | 7 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 2.237387 | 1388.7 | [1223.6, 1620.8] | 24 | 17 | 0 | 7 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.069799 | 1359.6 | [1231.3, 1556.6] | 112 | 84 | 0 | 28 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 1.894748 | 1329.2 | [1168.5, 1550.2] | 24 | 15 | 0 | 9 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.418693 | 1246.5 | [1062.9, 1462.8] | 24 | 12 | 0 | 12 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.135375 | 1197.2 | [1062.7, 1382.6] | 112 | 58 | 0 | 54 | 0 |
| 7 | llm-gpt-6-luna 0.1.0 | 1.105122 | 1192.0 | [1030.3, 1410.8] | 24 | 10 | 0 | 14 | 0 |
| 8 | a48 pauper-v2.0.0 | 1.067528 | 1185.4 | [1034.7, 1386.6] | 112 | 56 | 0 | 56 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.944397 | 1164.1 | [1000.0, 1378.0] | 24 | 9 | 0 | 15 | 0 |
| 10 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.778446 | 1135.2 | [956.2, 1369.7] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.778446 | 1135.2 | [903.4, 1391.6] | 24 | 8 | 0 | 16 | 0 |
| 12 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.604830 | 1105.1 | [900.9, 1354.5] | 24 | 7 | 0 | 17 | 0 |
| 13 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.220889 | 1038.4 | [848.4, 1260.5] | 24 | 5 | 0 | 19 | 0 |
| 14 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |
| 15 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.552755 | 904.0 | [702.6, 1119.0] | 24 | 2 | 0 | 22 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.514793 | 1610.6 | [1442.0, 1845.0] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.431017 | 1596.0 | [1477.0, 1738.3] | 112 | 95 | 0 | 17 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.776471 | 1482.3 | [1301.4, 1692.3] | 24 | 14 | 0 | 10 | 0 |
| 4 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.274463 | 1395.1 | [1234.2, 1579.0] | 24 | 11 | 0 | 13 | 0 |
| 5 | c12 pauper-v2.0.0 | 2.125345 | 1369.2 | [1250.2, 1495.2] | 112 | 62 | 0 | 50 | 0 |
| 6 | llm-gpt-6-luna 0.1.0 | 2.107372 | 1366.1 | [1210.2, 1550.2] | 24 | 10 | 0 | 14 | 2 |
| 7 | a48 pauper-v2.0.0 | 1.817118 | 1315.7 | [1182.4, 1440.1] | 112 | 53 | 0 | 59 | 0 |
| 8 | kit-mad-k 0.3.0+a49c05ddab71 | 1.763002 | 1306.3 | [1121.8, 1499.6] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.763002 | 1306.3 | [1137.7, 1492.3] | 24 | 8 | 0 | 16 | 0 |
| 10 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.763002 | 1306.3 | [1122.6, 1496.3] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.763002 | 1306.3 | [1172.4, 1461.0] | 24 | 8 | 0 | 16 | 0 |
| 12 | kit-mad-1 0.3.0+4e575c6a49fc | 1.581257 | 1274.7 | [1075.6, 1469.4] | 24 | 7 | 0 | 17 | 0 |
| 13 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.182412 | 1205.4 | [1084.1, 1342.6] | 24 | 5 | 0 | 19 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.954707 | 1165.8 | [1000.0, 1340.2] | 24 | 4 | 0 | 20 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.465821 | 1428.4 | [1286.3, 1578.8] | 24 | 23 | 0 | 1 | 0 |
| 2 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.125282 | 1195.5 | [1053.0, 1389.3] | 24 | 18 | 0 | 6 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.944582 | 1164.1 | [1052.6, 1285.4] | 24 | 17 | 0 | 7 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 0.612917 | 1106.5 | [972.8, 1282.9] | 24 | 15 | 0 | 9 | 0 |
| 5 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.612917 | 1106.5 | [1000.0, 1247.1] | 24 | 15 | 0 | 9 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.612917 | 1106.5 | [972.5, 1267.0] | 24 | 15 | 0 | 9 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.456374 | 1079.3 | [973.1, 1191.1] | 24 | 14 | 0 | 10 | 0 |
| 8 | c12 pauper-v2.0.0 | 0.373484 | 1064.9 | [988.7, 1142.5] | 112 | 55 | 0 | 57 | 0 |
| 9 | g115 pauper-v2.0.0 | 0.340758 | 1059.2 | [976.1, 1150.1] | 112 | 54 | 0 | 58 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 0.303198 | 1052.7 | [944.2, 1189.0] | 24 | 13 | 0 | 11 | 0 |
| 11 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 11 | 0 | 13 | 0 |
| 12 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [865.2, 1134.4] | 24 | 11 | 0 | 13 | 0 |
| 13 | a48 pauper-v2.0.0 | -0.263775 | 954.2 | [864.5, 1037.3] | 112 | 36 | 0 | 76 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.310118 | 946.1 | [775.9, 1106.9] | 24 | 9 | 0 | 15 | 0 |
| 15 | llm-gpt-6-luna 0.1.0 | -0.823812 | 856.9 | [717.6, 971.8] | 24 | 6 | 0 | 18 | 18 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 3.235709 | 1562.1 | [1386.7, 1850.2] | 24 | 20 | 0 | 4 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.654264 | 1461.1 | [1349.5, 1620.5] | 112 | 94 | 0 | 18 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.567530 | 1272.3 | [1156.7, 1425.1] | 24 | 11 | 0 | 13 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.459813 | 1253.6 | [1137.8, 1401.9] | 112 | 64 | 0 | 48 | 0 |
| 5 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.402286 | 1243.6 | [1095.3, 1433.9] | 24 | 10 | 0 | 14 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.402286 | 1243.6 | [1102.0, 1421.7] | 24 | 10 | 0 | 14 | 0 |
| 7 | a48 pauper-v2.0.0 | 1.121261 | 1194.8 | [1078.3, 1337.8] | 112 | 54 | 0 | 58 | 0 |
| 8 | llm-gpt-6-luna 0.1.0 | 1.061148 | 1184.3 | [1000.0, 1396.3] | 24 | 8 | 0 | 16 | 4 |
| 9 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.061148 | 1184.3 | [1000.0, 1366.9] | 24 | 8 | 0 | 16 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.061148 | 1184.3 | [1035.6, 1352.7] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.880800 | 1153.0 | [1000.0, 1329.3] | 24 | 7 | 0 | 17 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.689969 | 1119.9 | [915.7, 1309.5] | 24 | 6 | 0 | 18 | 0 |
| 13 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.689969 | 1119.9 | [961.0, 1280.0] | 24 | 6 | 0 | 18 | 0 |
| 14 | kit-mad-k 0.3.0+a49c05ddab71 | 0.000000 | 1000.0 | [822.4, 1202.2] | 24 | 3 | 0 | 21 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 1.918984 | 1333.4 | [1218.3, 1494.6] | 112 | 84 | 0 | 28 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.706077 | 1296.4 | [1173.7, 1459.9] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.531165 | 1266.0 | [1116.0, 1447.0] | 24 | 15 | 0 | 9 | 0 |
| 4 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.362070 | 1236.6 | [1058.6, 1456.7] | 24 | 14 | 0 | 10 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.362070 | 1236.6 | [1085.5, 1431.3] | 24 | 14 | 0 | 10 | 0 |
| 6 | oh2-r2s1-b512 pauper-v2.0.0 | 1.362070 | 1236.6 | [1090.0, 1405.6] | 24 | 14 | 0 | 10 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.362070 | 1236.6 | [1086.8, 1432.1] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.033670 | 1179.6 | [1029.4, 1354.3] | 24 | 12 | 0 | 12 | 0 |
| 9 | a48 pauper-v2.0.0 | 0.741942 | 1128.9 | [1021.5, 1263.3] | 112 | 49 | 0 | 63 | 0 |
| 10 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.707155 | 1122.8 | [964.0, 1305.2] | 24 | 10 | 0 | 14 | 0 |
| 11 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.540390 | 1093.9 | [935.6, 1267.9] | 24 | 9 | 0 | 15 | 0 |
| 12 | c12 pauper-v2.0.0 | 0.477770 | 1083.0 | [976.2, 1215.4] | 112 | 41 | 0 | 71 | 0 |
| 13 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.368689 | 1064.0 | [931.6, 1218.7] | 24 | 8 | 0 | 16 | 0 |
| 14 | llm-gpt-6-luna 0.1.0 | 0.000000 | 1000.0 | [827.6, 1185.4] | 24 | 6 | 0 | 18 | 3 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 6 | 0 | 18 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.087735 | 1362.7 | [1231.8, 1550.3] | 24 | 15 | 0 | 9 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.087735 | 1362.7 | [1221.8, 1573.4] | 24 | 15 | 0 | 9 | 0 |
| 3 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.932043 | 1335.6 | [1176.3, 1547.4] | 24 | 14 | 0 | 10 | 0 |
| 4 | g115 pauper-v2.0.0 | 1.928806 | 1335.1 | [1229.5, 1516.1] | 112 | 73 | 0 | 39 | 0 |
| 5 | llm-gpt-6-luna 0.1.0 | 1.779770 | 1309.2 | [1142.3, 1522.4] | 24 | 13 | 0 | 11 | 1 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.779770 | 1309.2 | [1152.9, 1505.7] | 24 | 13 | 0 | 11 | 0 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.629150 | 1283.0 | [1115.8, 1477.7] | 24 | 12 | 0 | 12 | 0 |
| 8 | a48 pauper-v2.0.0 | 1.626870 | 1282.6 | [1161.7, 1466.5] | 112 | 64 | 0 | 48 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.478530 | 1256.8 | [1115.8, 1452.4] | 24 | 11 | 0 | 13 | 0 |
| 10 | c12 pauper-v2.0.0 | 1.331825 | 1231.4 | [1114.3, 1415.2] | 112 | 55 | 0 | 57 | 0 |
| 11 | kit-mad-k 0.3.0+a49c05ddab71 | 1.009451 | 1175.4 | [1000.0, 1390.8] | 24 | 8 | 0 | 16 | 0 |
| 12 | kit-mad-1 0.3.0+4e575c6a49fc | 0.840464 | 1146.0 | [965.9, 1348.0] | 24 | 7 | 0 | 17 | 0 |
| 13 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.660468 | 1114.7 | [933.0, 1318.9] | 24 | 6 | 0 | 18 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.000000 | 1000.0 | [741.8, 1214.4] | 24 | 3 | 0 | 21 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.474725 | 1429.9 | [1255.8, 1664.3] | 24 | 20 | 0 | 4 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.031664 | 1352.9 | [1185.3, 1591.0] | 24 | 18 | 0 | 6 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.031664 | 1352.9 | [1159.7, 1599.7] | 24 | 18 | 0 | 6 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.646579 | 1286.0 | [1095.6, 1534.1] | 24 | 16 | 0 | 8 | 0 |
| 5 | g115 pauper-v2.0.0 | 1.569108 | 1272.6 | [1124.3, 1475.2] | 112 | 70 | 0 | 42 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.463098 | 1254.2 | [1109.2, 1463.9] | 112 | 67 | 0 | 45 | 0 |
| 7 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.287770 | 1223.7 | [1060.0, 1448.2] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.287770 | 1223.7 | [1061.1, 1439.9] | 24 | 14 | 0 | 10 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.112110 | 1193.2 | [1000.0, 1416.1] | 24 | 13 | 0 | 11 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 0.759175 | 1131.9 | [967.6, 1337.9] | 24 | 11 | 0 | 13 | 0 |
| 11 | llm-gpt-6-luna 0.1.0 | 0.759175 | 1131.9 | [931.3, 1370.9] | 24 | 11 | 0 | 13 | 4 |
| 12 | kit-mad-1 0.3.0+4e575c6a49fc | 0.201092 | 1034.9 | [857.7, 1259.7] | 24 | 8 | 0 | 16 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 7 | 0 | 17 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.212890 | 963.0 | [793.6, 1175.3] | 24 | 6 | 0 | 18 | 0 |
| 15 | a48 pauper-v2.0.0 | -0.339655 | 941.0 | [768.4, 1135.8] | 112 | 19 | 0 | 93 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.321255 | 1577.0 | [1466.0, 1758.9] | 112 | 99 | 0 | 13 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.915358 | 1506.5 | [1366.9, 1700.6] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 2.542170 | 1441.6 | [1266.1, 1663.2] | 24 | 14 | 0 | 10 | 0 |
| 4 | a48 pauper-v2.0.0 | 2.136858 | 1371.2 | [1262.5, 1546.8] | 112 | 72 | 0 | 40 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 2.004642 | 1348.2 | [1219.1, 1528.6] | 24 | 11 | 0 | 13 | 0 |
| 6 | llm-gpt-6-luna 0.1.0 | 2.004642 | 1348.2 | [1163.5, 1571.7] | 24 | 11 | 0 | 13 | 10 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.642033 | 1285.2 | [1153.3, 1478.8] | 24 | 9 | 0 | 15 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.454216 | 1252.6 | [1055.4, 1465.7] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.259032 | 1218.7 | [1047.5, 1424.5] | 24 | 7 | 0 | 17 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.259032 | 1218.7 | [1041.9, 1409.2] | 24 | 7 | 0 | 17 | 0 |
| 11 | c12 pauper-v2.0.0 | 1.106768 | 1192.3 | [1075.6, 1367.2] | 112 | 43 | 0 | 69 | 0 |
| 12 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.833078 | 1144.7 | [951.4, 1346.8] | 24 | 5 | 0 | 19 | 0 |
| 13 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.833078 | 1144.7 | [874.6, 1379.4] | 24 | 5 | 0 | 19 | 0 |
| 14 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.319885 | 1055.6 | [828.4, 1265.7] | 24 | 3 | 0 | 21 | 0 |
| 15 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 192 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
| llm-gpt-6-luna 0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
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
