# Spellbench leaderboard: pauper-bo1

- Games: 2112 played, 2112 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.228791 | 1387.2 | [1317.6, 1474.8] | 768 | 561 | 0 | 207 | 0 |
| 2 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.640135 | 1284.9 | [1198.8, 1381.5] | 192 | 98 | 0 | 94 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.597000 | 1277.4 | [1196.6, 1369.3] | 192 | 96 | 0 | 96 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.510731 | 1262.4 | [1180.9, 1351.4] | 192 | 92 | 0 | 100 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.489139 | 1258.7 | [1176.5, 1351.1] | 192 | 91 | 0 | 101 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.397261 | 1242.7 | [1176.8, 1322.3] | 768 | 407 | 0 | 361 | 0 |
| 7 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.359043 | 1236.1 | [1149.6, 1329.3] | 192 | 85 | 0 | 107 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.337228 | 1232.3 | [1148.4, 1326.1] | 192 | 84 | 0 | 108 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.337228 | 1232.3 | [1150.3, 1324.1] | 192 | 84 | 0 | 108 | 0 |
| 10 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.293442 | 1224.7 | [1148.2, 1311.2] | 192 | 82 | 0 | 110 | 0 |
| 11 | a48 pauper-v2.0.0 | 1.178492 | 1204.7 | [1138.3, 1285.3] | 768 | 364 | 0 | 404 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 0.070586 | 1012.3 | [915.3, 1105.5] | 192 | 35 | 0 | 157 | 0 |
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
| g115 | kit-mcts | 64 | 59 | 0 | 5 | 0.9219 | [0.8438, 0.9844] | 0.0000 |
| g115 | kit-mad-1 | 64 | 44 | 0 | 20 | 0.6875 | [0.5781, 0.7969] | 0.0075 |
| g115 | gorge-explore | 64 | 46 | 0 | 18 | 0.7188 | [0.6094, 0.8125] | 0.0013 |
| g115 | gorge-bot | 64 | 47 | 0 | 17 | 0.7344 | [0.6094, 0.8438] | 0.0015 |
| g115 | gorge-lethal-pressure | 64 | 43 | 0 | 21 | 0.6719 | [0.5156, 0.7969] | 0.0433 |
| g115 | c12 | 64 | 44 | 0 | 20 | 0.6875 | [0.5625, 0.8125] | 0.0169 |
| g115 | gorge-ar8 | 64 | 51 | 0 | 13 | 0.7969 | [0.6875, 0.8906] | 0.0001 |
| g115 | gorge-blocks | 64 | 39 | 0 | 25 | 0.6094 | [0.4688, 0.7344] | 0.1671 |
| g115 | a48 | 64 | 41 | 0 | 23 | 0.6406 | [0.5000, 0.7812] | 0.0784 |
| kit-mcts | c12 | 64 | 14 | 0 | 50 | 0.2188 | [0.1250, 0.3281] | 0.0001 |
| kit-mcts | a48 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3594] | 0.0004 |
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
| 1 | kit-mad-1 0.3.0+4e575c6a49fc | 3.363058 | 1584.2 | [1442.6, 1753.7] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.996772 | 1520.6 | [1381.7, 1680.5] | 96 | 73 | 0 | 23 | 0 |
| 3 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.834181 | 1492.3 | [1318.3, 1696.3] | 24 | 15 | 0 | 9 | 0 |
| 4 | kit-mad-k 0.3.0+a49c05ddab71 | 2.672495 | 1464.3 | [1299.1, 1676.3] | 24 | 14 | 0 | 10 | 0 |
| 5 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.358058 | 1409.6 | [1259.5, 1587.5] | 24 | 12 | 0 | 12 | 0 |
| 6 | c12 pauper-v2.0.0 | 2.168536 | 1376.7 | [1255.2, 1509.7] | 96 | 54 | 0 | 42 | 0 |
| 7 | a48 pauper-v2.0.0 | 1.922401 | 1334.0 | [1215.8, 1459.9] | 96 | 48 | 0 | 48 | 0 |
| 8 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.717216 | 1298.3 | [1096.7, 1486.4] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.543366 | 1268.1 | [1118.0, 1432.0] | 24 | 7 | 0 | 17 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.358681 | 1236.0 | [1052.4, 1420.6] | 24 | 6 | 0 | 18 | 0 |
| 11 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.358681 | 1236.0 | [1095.1, 1394.0] | 24 | 6 | 0 | 18 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 0.384169 | 1066.7 | [880.5, 1259.5] | 24 | 2 | 0 | 22 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.598226 | 1451.4 | [1306.3, 1674.5] | 96 | 86 | 0 | 10 | 0 |
| 2 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.844132 | 1320.4 | [1126.4, 1572.9] | 24 | 14 | 0 | 10 | 0 |
| 3 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.332161 | 1231.4 | [1031.1, 1487.0] | 24 | 11 | 0 | 13 | 0 |
| 4 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.162419 | 1201.9 | [1000.0, 1433.8] | 24 | 10 | 0 | 14 | 0 |
| 5 | a48 pauper-v2.0.0 | 1.048890 | 1182.2 | [1032.3, 1386.6] | 96 | 53 | 0 | 43 | 0 |
| 6 | kit-mad-k 0.3.0+a49c05ddab71 | 0.990275 | 1172.0 | [965.2, 1410.5] | 24 | 9 | 0 | 15 | 0 |
| 7 | c12 pauper-v2.0.0 | 0.932488 | 1162.0 | [992.4, 1368.3] | 96 | 50 | 0 | 46 | 0 |
| 8 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.813701 | 1141.4 | [968.9, 1363.0] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.630225 | 1109.5 | [904.9, 1340.3] | 24 | 7 | 0 | 17 | 0 |
| 10 | kit-mad-1 0.3.0+4e575c6a49fc | 0.228700 | 1039.7 | [838.9, 1263.3] | 24 | 5 | 0 | 19 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [753.5, 1263.8] | 24 | 4 | 0 | 20 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | -0.259357 | 954.9 | [661.8, 1219.8] | 24 | 3 | 0 | 21 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 0.691902 | 1120.2 | [970.4, 1276.1] | 24 | 18 | 0 | 6 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 0.505284 | 1087.8 | [939.3, 1267.5] | 24 | 17 | 0 | 7 | 0 |
| 3 | c12 pauper-v2.0.0 | 0.315233 | 1054.8 | [944.2, 1183.0] | 96 | 60 | 0 | 36 | 0 |
| 4 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.162112 | 1028.2 | [885.5, 1174.2] | 24 | 15 | 0 | 9 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 14 | 0 | 10 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [833.7, 1169.5] | 24 | 14 | 0 | 10 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [832.7, 1181.5] | 24 | 14 | 0 | 10 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.158608 | 972.4 | [833.5, 1112.4] | 24 | 13 | 0 | 11 | 0 |
| 9 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.315470 | 945.2 | [799.9, 1113.8] | 24 | 12 | 0 | 12 | 0 |
| 10 | a48 pauper-v2.0.0 | -0.415793 | 927.8 | [821.8, 1035.0] | 96 | 40 | 0 | 56 | 0 |
| 11 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | -0.472230 | 918.0 | [771.0, 1057.5] | 24 | 11 | 0 | 13 | 0 |
| 12 | g115 pauper-v2.0.0 | -0.837357 | 854.5 | [738.0, 958.2] | 96 | 29 | 0 | 67 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | -1.133744 | 803.0 | [644.7, 943.6] | 24 | 7 | 0 | 17 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.573601 | 1447.1 | [1370.9, 1581.4] | 96 | 84 | 0 | 12 | 0 |
| 2 | c12 pauper-v2.0.0 | 1.817268 | 1315.7 | [1245.2, 1443.1] | 96 | 69 | 0 | 27 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.600428 | 1278.0 | [1168.8, 1421.3] | 24 | 11 | 0 | 13 | 0 |
| 4 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.432867 | 1248.9 | [1143.3, 1388.3] | 24 | 10 | 0 | 14 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.085339 | 1188.5 | [1040.9, 1354.3] | 24 | 8 | 0 | 16 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.085339 | 1188.5 | [1077.1, 1342.7] | 24 | 8 | 0 | 16 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.900993 | 1156.5 | [955.6, 1317.3] | 24 | 7 | 0 | 17 | 0 |
| 8 | a48 pauper-v2.0.0 | 0.898392 | 1156.1 | [1085.2, 1285.6] | 96 | 46 | 0 | 50 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.705690 | 1122.6 | [945.9, 1300.8] | 24 | 6 | 0 | 18 | 0 |
| 10 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.495176 | 1086.0 | [1000.0, 1212.4] | 24 | 5 | 0 | 19 | 0 |
| 11 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.495176 | 1086.0 | [900.0, 1244.4] | 24 | 5 | 0 | 19 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | -0.311681 | 945.9 | [733.0, 1122.4] | 24 | 2 | 0 | 22 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.843469 | 1494.0 | [1390.6, 1663.8] | 96 | 69 | 0 | 27 | 0 |
| 2 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.688523 | 1467.0 | [1330.0, 1654.8] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-k 0.3.0+a49c05ddab71 | 2.515296 | 1437.0 | [1297.0, 1633.4] | 24 | 15 | 0 | 9 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.515296 | 1437.0 | [1320.8, 1620.9] | 24 | 15 | 0 | 9 | 0 |
| 5 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.515296 | 1437.0 | [1317.6, 1623.8] | 24 | 15 | 0 | 9 | 0 |
| 6 | kit-mad-1 0.3.0+4e575c6a49fc | 2.183837 | 1379.4 | [1202.2, 1601.0] | 24 | 13 | 0 | 11 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.021878 | 1351.2 | [1214.3, 1535.2] | 24 | 12 | 0 | 12 | 0 |
| 8 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.021878 | 1351.2 | [1236.7, 1519.9] | 24 | 12 | 0 | 12 | 0 |
| 9 | a48 pauper-v2.0.0 | 1.839770 | 1319.6 | [1218.2, 1478.5] | 96 | 43 | 0 | 53 | 0 |
| 10 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.697223 | 1294.8 | [1151.1, 1477.0] | 24 | 10 | 0 | 14 | 0 |
| 11 | kit-mcts 0.3.0+068718d79078 | 1.697223 | 1294.8 | [1106.9, 1511.2] | 24 | 10 | 0 | 14 | 0 |
| 12 | c12 pauper-v2.0.0 | 1.406476 | 1244.3 | [1137.3, 1420.8] | 96 | 32 | 0 | 64 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 4.061965 | 1705.6 | [1652.0, 1778.3] | 96 | 76 | 0 | 20 | 0 |
| 2 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.718567 | 1646.0 | [1555.3, 1757.1] | 24 | 16 | 0 | 8 | 0 |
| 3 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.718567 | 1646.0 | [1552.2, 1756.8] | 24 | 16 | 0 | 8 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.718567 | 1646.0 | [1525.6, 1795.6] | 24 | 16 | 0 | 8 | 0 |
| 5 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.537194 | 1614.5 | [1520.4, 1734.9] | 24 | 15 | 0 | 9 | 0 |
| 6 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.021626 | 1524.9 | [1437.2, 1635.4] | 24 | 12 | 0 | 12 | 0 |
| 7 | a48 pauper-v2.0.0 | 2.722818 | 1473.0 | [1430.9, 1526.7] | 96 | 45 | 0 | 51 | 0 |
| 8 | kit-mad-k 0.3.0+a49c05ddab71 | 2.684400 | 1466.3 | [1369.2, 1569.4] | 24 | 10 | 0 | 14 | 0 |
| 9 | kit-mad-1 0.3.0+4e575c6a49fc | 2.684400 | 1466.3 | [1339.4, 1596.9] | 24 | 10 | 0 | 14 | 0 |
| 10 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.512708 | 1436.5 | [1263.9, 1585.0] | 24 | 9 | 0 | 15 | 0 |
| 11 | c12 pauper-v2.0.0 | 2.337025 | 1406.0 | [1370.2, 1443.9] | 96 | 36 | 0 | 60 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 1.261705 | 1219.2 | [1097.2, 1338.8] | 24 | 3 | 0 | 21 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.173729 | 1377.6 | [1225.2, 1587.6] | 24 | 19 | 0 | 5 | 0 |
| 2 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.771673 | 1307.8 | [1151.5, 1500.6] | 24 | 17 | 0 | 7 | 0 |
| 3 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.587871 | 1275.8 | [1119.4, 1485.4] | 24 | 16 | 0 | 8 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.587871 | 1275.8 | [1125.3, 1462.5] | 24 | 16 | 0 | 8 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.456836 | 1253.1 | [1130.1, 1411.2] | 96 | 62 | 0 | 34 | 0 |
| 6 | g115 pauper-v2.0.0 | 1.374105 | 1238.7 | [1113.3, 1412.0] | 96 | 60 | 0 | 36 | 0 |
| 7 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.898504 | 1156.1 | [971.1, 1346.4] | 24 | 12 | 0 | 12 | 0 |
| 8 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.898504 | 1156.1 | [969.5, 1349.2] | 24 | 12 | 0 | 12 | 0 |
| 9 | kit-mad-1 0.3.0+4e575c6a49fc | 0.376679 | 1065.4 | [900.8, 1252.5] | 24 | 9 | 0 | 15 | 0 |
| 10 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 7 | 0 | 17 | 0 |
| 11 | kit-mad-k 0.3.0+a49c05ddab71 | 0.000000 | 1000.0 | [800.2, 1193.5] | 24 | 7 | 0 | 17 | 0 |
| 12 | a48 pauper-v2.0.0 | -0.214965 | 962.7 | [823.9, 1115.8] | 96 | 22 | 0 | 74 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | -0.424172 | 926.3 | [730.8, 1120.9] | 24 | 5 | 0 | 19 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.975614 | 1516.9 | [1403.9, 1689.4] | 96 | 84 | 0 | 12 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 2.265008 | 1393.5 | [1240.3, 1584.4] | 24 | 13 | 0 | 11 | 0 |
| 3 | a48 pauper-v2.0.0 | 2.120052 | 1368.3 | [1262.1, 1532.8] | 96 | 67 | 0 | 29 | 0 |
| 4 | kit-mad-k 0.3.0+a49c05ddab71 | 1.759157 | 1305.6 | [1130.9, 1511.0] | 24 | 10 | 0 | 14 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.759157 | 1305.6 | [1179.7, 1476.4] | 24 | 10 | 0 | 14 | 0 |
| 6 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.585995 | 1275.5 | [1144.9, 1444.7] | 24 | 9 | 0 | 15 | 0 |
| 7 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.221147 | 1212.1 | [1000.0, 1429.6] | 24 | 7 | 0 | 17 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.190408 | 1206.8 | [1093.0, 1380.9] | 96 | 44 | 0 | 52 | 0 |
| 9 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.023967 | 1177.9 | [1000.0, 1370.8] | 24 | 6 | 0 | 18 | 0 |
| 10 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.811666 | 1141.0 | [953.7, 1328.6] | 24 | 5 | 0 | 19 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.578020 | 1100.4 | [876.1, 1309.5] | 24 | 4 | 0 | 20 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 0.313190 | 1054.4 | [875.0, 1241.9] | 24 | 3 | 0 | 21 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

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
| kit-mcts 0.3.0+068718d79078 | 192 | 0 | 0.000 | 0 | 0.000 |
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
