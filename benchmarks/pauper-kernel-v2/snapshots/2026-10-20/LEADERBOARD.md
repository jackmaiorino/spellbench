# Spellbench leaderboard: pauper-bo1

- Games: 2112 played, 2112 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.226631 | 1386.8 | [1315.8, 1473.5] | 768 | 561 | 0 | 207 | 0 |
| 2 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.639165 | 1284.8 | [1197.2, 1376.5] | 192 | 98 | 0 | 94 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.596056 | 1277.3 | [1196.1, 1371.1] | 192 | 96 | 0 | 96 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.509840 | 1262.3 | [1178.3, 1347.4] | 192 | 92 | 0 | 100 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.488262 | 1258.5 | [1176.5, 1352.1] | 192 | 91 | 0 | 101 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.384432 | 1240.5 | [1175.8, 1322.8] | 768 | 405 | 0 | 363 | 0 |
| 7 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.358248 | 1236.0 | [1149.7, 1329.5] | 192 | 85 | 0 | 107 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.336447 | 1232.2 | [1145.8, 1327.2] | 192 | 84 | 0 | 108 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.336447 | 1232.2 | [1149.7, 1322.0] | 192 | 84 | 0 | 108 | 0 |
| 10 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.292689 | 1224.6 | [1146.9, 1314.2] | 192 | 82 | 0 | 110 | 0 |
| 11 | a48 pauper-v2.0.0 | 1.190963 | 1206.9 | [1139.4, 1288.0] | 768 | 367 | 0 | 401 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.035652 | 1006.2 | [919.4, 1101.2] | 192 | 34 | 0 | 158 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 33 | 0 | 159 | 0 |

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
| g115 | kit-mad-1 | 64 | 44 | 0 | 20 | 0.6875 | [0.5781, 0.7969] | 0.0075 |
| g115 | gorge-explore | 64 | 46 | 0 | 18 | 0.7188 | [0.6094, 0.8281] | 0.0013 |
| g115 | gorge-bot | 64 | 47 | 0 | 17 | 0.7344 | [0.6094, 0.8438] | 0.0015 |
| g115 | gorge-lethal-pressure | 64 | 43 | 0 | 21 | 0.6719 | [0.5312, 0.7969] | 0.0433 |
| g115 | c12 | 64 | 44 | 0 | 20 | 0.6875 | [0.5469, 0.8125] | 0.0169 |
| g115 | gorge-ar8 | 64 | 51 | 0 | 13 | 0.7969 | [0.6875, 0.9062] | 0.0001 |
| g115 | gorge-blocks | 64 | 39 | 0 | 25 | 0.6094 | [0.4844, 0.7344] | 0.1671 |
| g115 | a48 | 64 | 41 | 0 | 23 | 0.6406 | [0.5000, 0.7656] | 0.0784 |
| kit-mad-1 | c12 | 64 | 36 | 0 | 28 | 0.5625 | [0.4375, 0.6875] | 0.4807 |
| kit-mad-1 | a48 | 64 | 40 | 0 | 24 | 0.6250 | [0.4844, 0.7656] | 0.1338 |
| gorge-explore | c12 | 64 | 36 | 0 | 28 | 0.5625 | [0.4531, 0.6719] | 0.4240 |
| gorge-explore | a48 | 64 | 38 | 0 | 26 | 0.5938 | [0.4844, 0.7031] | 0.2101 |
| gorge-bot | c12 | 64 | 26 | 0 | 38 | 0.4062 | [0.3125, 0.5156] | 0.1460 |
| gorge-bot | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.5000, 0.7188] | 0.0923 |
| gorge-lethal-pressure | c12 | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8145 |
| gorge-lethal-pressure | a48 | 64 | 33 | 0 | 31 | 0.5156 | [0.3906, 0.6406] | 1.0000 |
| c12 | gorge-ar8 | 64 | 32 | 0 | 32 | 0.5000 | [0.3750, 0.6250] | 1.0000 |
| c12 | gorge-blocks | 64 | 28 | 0 | 36 | 0.4375 | [0.3281, 0.5625] | 0.4240 |
| c12 | a48 | 64 | 36 | 0 | 28 | 0.5625 | [0.4219, 0.6875] | 0.4807 |
| gorge-ar8 | a48 | 64 | 39 | 0 | 25 | 0.6094 | [0.4688, 0.7500] | 0.1671 |
| gorge-blocks | a48 | 64 | 37 | 0 | 27 | 0.5781 | [0.4375, 0.7031] | 0.3593 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 85 | 0 | 43 |
| c12 pauper-v2.0.0 | -0.617444 | 892.7 | 128 | 56 | 0 | 72 |
| a48 pauper-v2.0.0 | -0.723785 | 874.3 | 128 | 51 | 0 | 77 |

### tag: search

skipped: no_rated_games

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-1 0.3.0+4e575c6a49fc | 3.363999 | 1584.4 | [1442.2, 1757.2] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.006432 | 1522.3 | [1385.8, 1680.3] | 96 | 73 | 0 | 23 | 0 |
| 3 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.834614 | 1492.4 | [1316.4, 1704.8] | 24 | 15 | 0 | 9 | 0 |
| 4 | kit-mad-k 0.3.0+a49c05ddab71 | 2.672791 | 1464.3 | [1299.1, 1673.6] | 24 | 14 | 0 | 10 | 0 |
| 5 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.358129 | 1409.6 | [1255.8, 1590.0] | 24 | 12 | 0 | 12 | 0 |
| 6 | c12 pauper-v2.0.0 | 2.142946 | 1372.3 | [1250.8, 1501.9] | 96 | 53 | 0 | 43 | 0 |
| 7 | a48 pauper-v2.0.0 | 1.939986 | 1337.0 | [1221.0, 1461.8] | 96 | 48 | 0 | 48 | 0 |
| 8 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.717043 | 1298.3 | [1096.3, 1482.1] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.543175 | 1268.1 | [1118.0, 1433.1] | 24 | 7 | 0 | 17 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.358485 | 1236.0 | [1052.8, 1420.2] | 24 | 6 | 0 | 18 | 0 |
| 11 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.358485 | 1236.0 | [1094.9, 1395.3] | 24 | 6 | 0 | 18 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.685041 | 1119.0 | [933.2, 1299.4] | 24 | 3 | 0 | 21 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.578807 | 1448.0 | [1303.5, 1672.3] | 96 | 86 | 0 | 10 | 0 |
| 2 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.839636 | 1319.6 | [1126.1, 1563.8] | 24 | 14 | 0 | 10 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.329470 | 1231.0 | [1032.0, 1496.0] | 24 | 11 | 0 | 13 | 0 |
| 4 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.160236 | 1201.6 | [1000.0, 1435.8] | 24 | 10 | 0 | 14 | 0 |
| 5 | a48 pauper-v2.0.0 | 1.053415 | 1183.0 | [1033.2, 1388.3] | 96 | 54 | 0 | 42 | 0 |
| 6 | kit-mad-k 0.3.0+a49c05ddab71 | 0.988555 | 1171.7 | [964.9, 1407.3] | 24 | 9 | 0 | 15 | 0 |
| 7 | c12 pauper-v2.0.0 | 0.934433 | 1162.3 | [991.2, 1370.3] | 96 | 51 | 0 | 45 | 0 |
| 8 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.812400 | 1141.1 | [967.8, 1370.8] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.629303 | 1109.3 | [903.0, 1338.4] | 24 | 7 | 0 | 17 | 0 |
| 10 | kit-mad-1 0.3.0+4e575c6a49fc | 0.228424 | 1039.7 | [841.2, 1271.6] | 24 | 5 | 0 | 19 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [750.2, 1263.0] | 24 | 4 | 0 | 20 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.955891 | 833.9 | [622.9, 1068.1] | 24 | 1 | 0 | 23 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 0.687966 | 1119.5 | [970.8, 1272.7] | 24 | 18 | 0 | 6 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 0.502382 | 1087.3 | [936.4, 1257.9] | 24 | 17 | 0 | 7 | 0 |
| 3 | c12 pauper-v2.0.0 | 0.270837 | 1047.0 | [933.0, 1165.8] | 96 | 58 | 0 | 38 | 0 |
| 4 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.161181 | 1028.0 | [886.7, 1173.8] | 24 | 15 | 0 | 9 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 14 | 0 | 10 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [848.3, 1173.6] | 24 | 14 | 0 | 10 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [836.9, 1174.4] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.157718 | 972.6 | [833.7, 1111.2] | 24 | 13 | 0 | 11 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.313732 | 945.5 | [799.9, 1110.9] | 24 | 12 | 0 | 12 | 0 |
| 10 | a48 pauper-v2.0.0 | -0.376203 | 934.6 | [827.0, 1039.9] | 96 | 40 | 0 | 56 | 0 |
| 11 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.469690 | 918.4 | [769.4, 1056.5] | 24 | 11 | 0 | 13 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.627237 | 891.0 | [742.2, 1027.5] | 24 | 10 | 0 | 14 | 0 |
| 13 | g115 pauper-v2.0.0 | -0.830987 | 855.6 | [742.9, 963.0] | 96 | 28 | 0 | 68 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.538507 | 1441.0 | [1360.7, 1575.4] | 96 | 83 | 0 | 13 | 0 |
| 2 | c12 pauper-v2.0.0 | 1.809005 | 1314.3 | [1244.4, 1439.5] | 96 | 68 | 0 | 28 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.592304 | 1276.6 | [1167.8, 1419.5] | 24 | 11 | 0 | 13 | 0 |
| 4 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.425789 | 1247.7 | [1143.8, 1384.6] | 24 | 10 | 0 | 14 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.080347 | 1187.7 | [1040.5, 1351.7] | 24 | 8 | 0 | 16 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.080347 | 1187.7 | [1076.0, 1343.6] | 24 | 8 | 0 | 16 | 0 |
| 7 | a48 pauper-v2.0.0 | 0.914699 | 1158.9 | [1086.5, 1286.7] | 96 | 45 | 0 | 51 | 0 |
| 8 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.897033 | 1155.8 | [1000.0, 1318.6] | 24 | 7 | 0 | 17 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.702749 | 1122.1 | [931.8, 1303.7] | 24 | 6 | 0 | 18 | 0 |
| 10 | kit-mcts-custom 0.3.0+25b213ad6a3c | 0.493239 | 1085.7 | [930.5, 1241.1] | 24 | 5 | 0 | 19 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.493239 | 1085.7 | [1000.0, 1210.4] | 24 | 5 | 0 | 19 | 0 |
| 12 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.493239 | 1085.7 | [901.2, 1246.2] | 24 | 5 | 0 | 19 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.911791 | 1505.8 | [1401.9, 1671.3] | 96 | 71 | 0 | 25 | 0 |
| 2 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.705594 | 1470.0 | [1334.0, 1662.0] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-k 0.3.0+a49c05ddab71 | 2.530488 | 1439.6 | [1295.7, 1637.1] | 24 | 15 | 0 | 9 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.530488 | 1439.6 | [1324.3, 1618.5] | 24 | 15 | 0 | 9 | 0 |
| 5 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.530488 | 1439.6 | [1319.6, 1621.8] | 24 | 15 | 0 | 9 | 0 |
| 6 | kit-mad-1 0.3.0+4e575c6a49fc | 2.195549 | 1381.4 | [1184.6, 1615.9] | 24 | 13 | 0 | 11 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.032003 | 1353.0 | [1214.7, 1542.3] | 24 | 12 | 0 | 12 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.032003 | 1353.0 | [1239.7, 1519.8] | 24 | 12 | 0 | 12 | 0 |
| 9 | a48 pauper-v2.0.0 | 1.807354 | 1314.0 | [1216.9, 1474.9] | 96 | 43 | 0 | 53 | 0 |
| 10 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.704500 | 1296.1 | [1152.1, 1474.8] | 24 | 10 | 0 | 14 | 0 |
| 11 | c12 pauper-v2.0.0 | 1.409222 | 1244.8 | [1137.5, 1419.6] | 96 | 33 | 0 | 63 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 1.185035 | 1205.9 | [1074.4, 1376.8] | 24 | 7 | 0 | 17 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 4.071907 | 1707.4 | [1655.7, 1780.7] | 96 | 76 | 0 | 20 | 0 |
| 2 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.729516 | 1647.9 | [1556.3, 1760.2] | 24 | 16 | 0 | 8 | 0 |
| 3 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.729516 | 1647.9 | [1550.6, 1757.5] | 24 | 16 | 0 | 8 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.729516 | 1647.9 | [1530.8, 1803.5] | 24 | 16 | 0 | 8 | 0 |
| 5 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.547803 | 1616.3 | [1521.8, 1736.1] | 24 | 15 | 0 | 9 | 0 |
| 6 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.030852 | 1526.5 | [1436.7, 1629.2] | 24 | 12 | 0 | 12 | 0 |
| 7 | a48 pauper-v2.0.0 | 2.773037 | 1481.7 | [1439.3, 1537.3] | 96 | 46 | 0 | 50 | 0 |
| 8 | kit-mad-k 0.3.0+a49c05ddab71 | 2.692429 | 1467.7 | [1370.8, 1571.2] | 24 | 10 | 0 | 14 | 0 |
| 9 | kit-mad-1 0.3.0+4e575c6a49fc | 2.692429 | 1467.7 | [1339.1, 1598.4] | 24 | 10 | 0 | 14 | 0 |
| 10 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.520067 | 1437.8 | [1265.9, 1592.3] | 24 | 9 | 0 | 15 | 0 |
| 11 | c12 pauper-v2.0.0 | 2.300172 | 1399.6 | [1365.6, 1434.5] | 96 | 35 | 0 | 61 | 0 |
| 12 | kit-mcts-custom 0.3.0+25b213ad6a3c | 1.264331 | 1219.6 | [1097.8, 1270.1] | 24 | 3 | 0 | 21 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.163201 | 1375.8 | [1224.6, 1579.6] | 24 | 19 | 0 | 5 | 0 |
| 2 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.762212 | 1306.1 | [1151.6, 1505.7] | 24 | 17 | 0 | 7 | 0 |
| 3 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.579033 | 1274.3 | [1095.5, 1471.4] | 24 | 16 | 0 | 8 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.579033 | 1274.3 | [1125.1, 1456.4] | 24 | 16 | 0 | 8 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.440869 | 1250.3 | [1125.6, 1407.5] | 96 | 62 | 0 | 34 | 0 |
| 6 | g115 pauper-v2.0.0 | 1.357823 | 1235.9 | [1109.1, 1402.6] | 96 | 60 | 0 | 36 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.892868 | 1155.1 | [1000.0, 1339.6] | 24 | 12 | 0 | 12 | 0 |
| 8 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.892868 | 1155.1 | [969.9, 1353.9] | 24 | 12 | 0 | 12 | 0 |
| 9 | kit-mad-1 0.3.0+4e575c6a49fc | 0.374238 | 1065.0 | [908.6, 1237.3] | 24 | 9 | 0 | 15 | 0 |
| 10 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 7 | 0 | 17 | 0 |
| 11 | kit-mad-k 0.3.0+a49c05ddab71 | 0.000000 | 1000.0 | [799.3, 1191.6] | 24 | 7 | 0 | 17 | 0 |
| 12 | a48 pauper-v2.0.0 | -0.194367 | 966.2 | [830.2, 1120.4] | 96 | 23 | 0 | 73 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.662048 | 885.0 | [701.3, 1075.9] | 24 | 4 | 0 | 20 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.956989 | 1513.7 | [1402.1, 1689.3] | 96 | 84 | 0 | 12 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 2.264138 | 1393.3 | [1243.6, 1589.6] | 24 | 13 | 0 | 11 | 0 |
| 3 | a48 pauper-v2.0.0 | 2.137823 | 1371.4 | [1268.2, 1534.0] | 96 | 68 | 0 | 28 | 0 |
| 4 | kit-mad-k 0.3.0+a49c05ddab71 | 1.759058 | 1305.6 | [1133.2, 1510.8] | 24 | 10 | 0 | 14 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.759058 | 1305.6 | [1179.2, 1477.7] | 24 | 10 | 0 | 14 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.586054 | 1275.5 | [1145.7, 1451.9] | 24 | 9 | 0 | 15 | 0 |
| 7 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.221382 | 1212.2 | [1000.0, 1428.5] | 24 | 7 | 0 | 17 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.185822 | 1206.0 | [1092.6, 1380.3] | 96 | 45 | 0 | 51 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.024223 | 1177.9 | [1000.0, 1353.3] | 24 | 6 | 0 | 18 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.811906 | 1141.0 | [953.9, 1339.4] | 24 | 5 | 0 | 19 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.578209 | 1100.4 | [876.9, 1308.4] | 24 | 4 | 0 | 20 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |
| 13 | kit-mcts-custom 0.3.0+25b213ad6a3c | -0.396322 | 931.2 | [736.3, 1122.8] | 24 | 1 | 0 | 23 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 192 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
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
