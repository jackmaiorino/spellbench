# Spellbench leaderboard: pauper-bo1

- Games: 2112 played, 2100 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 12)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 1.998356 | 1347.2 | [1285.4, 1425.0] | 759 | 510 | 0 | 249 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.663234 | 1288.9 | [1212.4, 1375.1] | 190 | 100 | 0 | 90 | 0 |
| 3 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.648729 | 1286.4 | [1206.1, 1373.6] | 190 | 100 | 0 | 90 | 0 |
| 4 | kit-mad-k 0.3.0+a49c05ddab71 | 1.565167 | 1271.9 | [1191.5, 1359.9] | 192 | 96 | 0 | 96 | 0 |
| 5 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.536510 | 1266.9 | [1188.2, 1361.5] | 189 | 93 | 0 | 96 | 0 |
| 6 | kit-mad-1 0.3.0+4e575c6a49fc | 1.460138 | 1253.7 | [1176.5, 1342.8] | 192 | 91 | 0 | 101 | 0 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.448857 | 1251.7 | [1173.3, 1341.1] | 189 | 89 | 0 | 100 | 0 |
| 8 | a48 pauper-v2.0.0 | 1.358767 | 1236.0 | [1175.4, 1310.0] | 767 | 392 | 0 | 375 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.347980 | 1234.2 | [1157.1, 1318.8] | 190 | 84 | 0 | 106 | 0 |
| 10 | c12 pauper-v2.0.0 | 1.343392 | 1233.4 | [1172.9, 1308.9] | 766 | 388 | 0 | 378 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.226467 | 1213.1 | [1133.1, 1299.9] | 192 | 80 | 0 | 112 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 0.352279 | 1061.2 | [979.1, 1149.0] | 192 | 44 | 0 | 148 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 33 | 0 | 159 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| gorge-legacy | a48 | 64 | 34 | 0 | 30 | 0.5312 | [0.4062, 0.6406] | 0.7905 |
| gorge-legacy | c12 | 64 | 30 | 0 | 34 | 0.4688 | [0.3594, 0.5938] | 0.7905 |
| gorge-legacy | g115 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3594] | 0.0004 |
| uniform | a48 | 64 | 11 | 0 | 53 | 0.1719 | [0.0938, 0.2656] | 0.0000 |
| uniform | c12 | 64 | 15 | 0 | 49 | 0.2344 | [0.1406, 0.3438] | 0.0002 |
| uniform | g115 | 64 | 7 | 0 | 57 | 0.1094 | [0.0469, 0.1875] | 0.0000 |
| kit-mad-1 | a48 | 64 | 38 | 0 | 26 | 0.5938 | [0.4688, 0.7031] | 0.2101 |
| kit-mad-1 | c12 | 64 | 27 | 0 | 37 | 0.4219 | [0.2969, 0.5469] | 0.3323 |
| kit-mad-1 | g115 | 64 | 26 | 0 | 38 | 0.4062 | [0.2656, 0.5469] | 0.2863 |
| kit-mad-k | a48 | 64 | 37 | 0 | 27 | 0.5781 | [0.4531, 0.7188] | 0.3593 |
| kit-mad-k | c12 | 64 | 31 | 0 | 33 | 0.4844 | [0.3438, 0.6094] | 1.0000 |
| kit-mad-k | g115 | 64 | 28 | 0 | 36 | 0.4375 | [0.2969, 0.5781] | 0.5235 |
| a48 | c12 | 64 | 31 | 0 | 33 | 0.4844 | [0.3750, 0.5938] | 1.0000 |
| a48 | kit-mcts | 64 | 45 | 0 | 19 | 0.7031 | [0.5938, 0.8125] | 0.0044 |
| a48 | g115 | 64 | 17 | 0 | 47 | 0.2656 | [0.1562, 0.3750] | 0.0007 |
| a48 | gorge-explore | 64 | 33 | 0 | 31 | 0.5156 | [0.3906, 0.6406] | 1.0000 |
| a48 | gorge-bot | 64 | 27 | 0 | 37 | 0.4219 | [0.2969, 0.5625] | 0.3593 |
| a48 | gorge-lethal-pressure | 64 | 38 | 0 | 26 | 0.5938 | [0.4844, 0.6875] | 0.1460 |
| a48 | gorge-ar8 | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8036 |
| a48 | gorge-blocks | 63 | 35 | 0 | 28 | 0.5484 | [0.4032, 0.6774] | 0.6476 |
| c12 | kit-mcts | 64 | 51 | 0 | 13 | 0.7969 | [0.7031, 0.8906] | 0.0000 |
| c12 | g115 | 64 | 22 | 0 | 42 | 0.3438 | [0.2344, 0.4531] | 0.0213 |
| c12 | gorge-explore | 64 | 30 | 0 | 34 | 0.4688 | [0.3438, 0.5938] | 0.8036 |
| c12 | gorge-bot | 63 | 26 | 0 | 37 | 0.4194 | [0.3065, 0.5484] | 0.3018 |
| c12 | gorge-lethal-pressure | 63 | 28 | 0 | 35 | 0.4355 | [0.3065, 0.5806] | 0.5034 |
| c12 | gorge-ar8 | 64 | 17 | 0 | 47 | 0.2656 | [0.1562, 0.3906] | 0.0026 |
| c12 | gorge-blocks | 64 | 28 | 0 | 36 | 0.4375 | [0.2969, 0.5781] | 0.5034 |
| kit-mcts | g115 | 64 | 12 | 0 | 52 | 0.1875 | [0.0938, 0.2812] | 0.0000 |
| g115 | gorge-explore | 61 | 37 | 0 | 24 | 0.6000 | [0.4667, 0.7333] | 0.2379 |
| g115 | gorge-bot | 63 | 37 | 0 | 26 | 0.5968 | [0.4516, 0.7419] | 0.2632 |
| g115 | gorge-lethal-pressure | 63 | 40 | 0 | 23 | 0.6290 | [0.5323, 0.7258] | 0.0386 |
| g115 | gorge-ar8 | 62 | 43 | 0 | 19 | 0.7000 | [0.6000, 0.8000] | 0.0018 |
| g115 | gorge-blocks | 62 | 33 | 0 | 29 | 0.5333 | [0.4167, 0.6500] | 0.7905 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 0.887666 | 1154.2 | 128 | 89 | 0 | 39 |
| c12 pauper-v2.0.0 | 0.151270 | 1026.3 | 128 | 55 | 0 | 73 |
| a48 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 48 | 0 | 80 |

### tag: search

skipped: no_rated_games

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-1 0.3.0+4e575c6a49fc | 2.945799 | 1511.7 | [1323.3, 1755.1] | 24 | 18 | 0 | 6 | 0 |
| 2 | kit-mad-k 0.3.0+a49c05ddab71 | 2.589102 | 1449.8 | [1279.7, 1672.1] | 24 | 16 | 0 | 8 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.496994 | 1433.8 | [1301.2, 1627.3] | 96 | 68 | 0 | 28 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.955020 | 1339.6 | [1153.3, 1559.5] | 24 | 12 | 0 | 12 | 0 |
| 5 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.801045 | 1312.9 | [1133.7, 1543.6] | 24 | 11 | 0 | 13 | 0 |
| 6 | a48 pauper-v2.0.0 | 1.783742 | 1309.9 | [1185.2, 1482.0] | 96 | 50 | 0 | 46 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.645519 | 1285.9 | [1095.2, 1523.9] | 24 | 10 | 0 | 14 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.592887 | 1276.7 | [1141.3, 1452.2] | 96 | 45 | 0 | 51 | 0 |
| 9 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.486679 | 1258.3 | [1129.2, 1445.9] | 24 | 9 | 0 | 15 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.486679 | 1258.3 | [1098.0, 1457.8] | 24 | 9 | 0 | 15 | 0 |
| 11 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.486679 | 1258.3 | [1072.9, 1475.1] | 24 | 9 | 0 | 15 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 0.769721 | 1133.7 | [948.2, 1332.6] | 24 | 5 | 0 | 19 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.836795 | 1492.8 | [1371.1, 1623.2] | 96 | 76 | 0 | 20 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.177180 | 1378.2 | [1229.8, 1531.6] | 24 | 11 | 0 | 13 | 0 |
| 3 | a48 pauper-v2.0.0 | 2.158489 | 1375.0 | [1245.1, 1504.2] | 96 | 60 | 0 | 36 | 0 |
| 4 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.022384 | 1351.3 | [1198.5, 1523.9] | 24 | 10 | 0 | 14 | 0 |
| 5 | c12 pauper-v2.0.0 | 2.003182 | 1348.0 | [1231.6, 1465.6] | 96 | 56 | 0 | 40 | 0 |
| 6 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.864256 | 1323.9 | [1177.2, 1480.1] | 24 | 9 | 0 | 15 | 0 |
| 7 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.864256 | 1323.9 | [1163.1, 1496.6] | 24 | 9 | 0 | 15 | 0 |
| 8 | kit-mad-1 0.3.0+4e575c6a49fc | 1.700784 | 1295.5 | [1096.5, 1496.0] | 24 | 8 | 0 | 16 | 0 |
| 9 | kit-mad-k 0.3.0+a49c05ddab71 | 1.700784 | 1295.5 | [1132.9, 1472.6] | 24 | 8 | 0 | 16 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.700784 | 1295.5 | [1166.9, 1446.3] | 24 | 8 | 0 | 16 | 0 |
| 11 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.529531 | 1265.7 | [1072.0, 1448.4] | 24 | 7 | 0 | 17 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | 0.000000 | 1000.0 | [836.3, 1163.7] | 24 | 1 | 0 | 23 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 1.320353 | 1229.4 | [1084.7, 1410.7] | 24 | 19 | 0 | 5 | 0 |
| 2 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.124501 | 1195.3 | [1055.2, 1360.6] | 24 | 18 | 0 | 6 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 0.774267 | 1134.5 | [1000.0, 1310.0] | 24 | 16 | 0 | 8 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.456020 | 1079.2 | [918.6, 1249.4] | 24 | 14 | 0 | 10 | 0 |
| 5 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.456020 | 1079.2 | [920.8, 1246.7] | 24 | 14 | 0 | 10 | 0 |
| 6 | a48 pauper-v2.0.0 | 0.371070 | 1064.5 | [960.6, 1179.1] | 96 | 48 | 0 | 48 | 0 |
| 7 | c12 pauper-v2.0.0 | 0.335150 | 1058.2 | [953.9, 1158.3] | 96 | 47 | 0 | 49 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.302959 | 1052.6 | [894.8, 1217.1] | 24 | 13 | 0 | 11 | 0 |
| 9 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.151503 | 1026.3 | [883.6, 1188.3] | 24 | 12 | 0 | 12 | 0 |
| 10 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.151503 | 1026.3 | [864.2, 1191.5] | 24 | 12 | 0 | 12 | 0 |
| 11 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 11 | 0 | 13 | 0 |
| 12 | g115 pauper-v2.0.0 | -0.255860 | 955.6 | [844.1, 1066.9] | 96 | 31 | 0 | 65 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | -0.309868 | 946.2 | [798.1, 1083.3] | 24 | 9 | 0 | 15 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.771949 | 1481.5 | [1347.8, 1626.5] | 96 | 73 | 0 | 23 | 0 |
| 2 | kit-mad-k 0.3.0+a49c05ddab71 | 2.481094 | 1431.0 | [1257.2, 1621.5] | 24 | 13 | 0 | 11 | 0 |
| 3 | c12 pauper-v2.0.0 | 2.278062 | 1395.7 | [1274.0, 1524.4] | 96 | 61 | 0 | 35 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.175556 | 1377.9 | [1203.8, 1554.4] | 24 | 11 | 0 | 13 | 0 |
| 5 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.021174 | 1351.1 | [1203.8, 1510.0] | 24 | 10 | 0 | 14 | 0 |
| 6 | a48 pauper-v2.0.0 | 1.937138 | 1336.5 | [1219.3, 1453.5] | 96 | 52 | 0 | 44 | 0 |
| 7 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.863402 | 1323.7 | [1150.4, 1500.0] | 24 | 9 | 0 | 15 | 0 |
| 8 | kit-mcts 0.3.0+068718d79078 | 1.700229 | 1295.4 | [1095.5, 1479.1] | 24 | 8 | 0 | 16 | 0 |
| 9 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.529217 | 1265.7 | [1116.8, 1421.4] | 24 | 7 | 0 | 17 | 0 |
| 10 | kit-mad-1 0.3.0+4e575c6a49fc | 1.529217 | 1265.7 | [1096.1, 1424.2] | 24 | 7 | 0 | 17 | 0 |
| 11 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.347228 | 1234.0 | [1072.7, 1396.5] | 24 | 6 | 0 | 18 | 0 |
| 12 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.347228 | 1234.0 | [1051.7, 1418.9] | 24 | 6 | 0 | 18 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.601142 | 1451.9 | [1312.0, 1649.1] | 24 | 19 | 0 | 5 | 0 |
| 2 | g115 pauper-v2.0.0 | 1.748444 | 1303.7 | [1197.4, 1452.9] | 96 | 59 | 0 | 37 | 0 |
| 3 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.724297 | 1299.5 | [1148.2, 1484.5] | 24 | 14 | 0 | 10 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.724297 | 1299.5 | [1170.8, 1467.2] | 24 | 14 | 0 | 10 | 0 |
| 5 | a48 pauper-v2.0.0 | 1.634783 | 1284.0 | [1177.1, 1442.8] | 96 | 56 | 0 | 40 | 0 |
| 6 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.568490 | 1272.5 | [1170.5, 1418.3] | 24 | 13 | 0 | 11 | 0 |
| 7 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.414209 | 1245.7 | [1116.8, 1412.9] | 24 | 12 | 0 | 12 | 0 |
| 8 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.103627 | 1191.7 | [1032.2, 1383.5] | 24 | 10 | 0 | 14 | 0 |
| 9 | kit-mad-1 0.3.0+4e575c6a49fc | 1.103627 | 1191.7 | [1062.0, 1360.5] | 24 | 10 | 0 | 14 | 0 |
| 10 | kit-mad-k 0.3.0+a49c05ddab71 | 1.103627 | 1191.7 | [1000.0, 1395.4] | 24 | 10 | 0 | 14 | 0 |
| 11 | c12 pauper-v2.0.0 | 0.848768 | 1147.4 | [1041.3, 1301.2] | 96 | 35 | 0 | 61 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 0.778663 | 1135.3 | [1000.0, 1300.0] | 24 | 8 | 0 | 16 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.754751 | 1652.3 | [1613.9, 1741.4] | 21 | 15 | 0 | 6 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.754751 | 1652.3 | [1614.0, 1742.3] | 22 | 16 | 0 | 6 | 0 |
| 3 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.623959 | 1629.5 | [1501.7, 1800.2] | 22 | 16 | 0 | 6 | 0 |
| 4 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.623959 | 1629.5 | [1554.0, 1721.0] | 22 | 14 | 0 | 8 | 0 |
| 5 | g115 pauper-v2.0.0 | 3.452047 | 1599.7 | [1552.5, 1662.8] | 87 | 59 | 0 | 28 | 0 |
| 6 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.416207 | 1593.5 | [1521.0, 1683.8] | 21 | 13 | 0 | 8 | 0 |
| 7 | kit-mad-1 0.3.0+4e575c6a49fc | 3.047132 | 1529.3 | [1393.1, 1681.3] | 24 | 13 | 0 | 11 | 0 |
| 8 | a48 pauper-v2.0.0 | 2.651776 | 1460.7 | [1423.7, 1503.5] | 95 | 43 | 0 | 52 | 0 |
| 9 | c12 pauper-v2.0.0 | 2.585474 | 1449.1 | [1413.6, 1489.8] | 94 | 41 | 0 | 53 | 0 |
| 10 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.583185 | 1448.7 | [1331.6, 1549.6] | 24 | 10 | 0 | 14 | 0 |
| 11 | kit-mad-k 0.3.0+a49c05ddab71 | 2.260046 | 1392.6 | [1215.6, 1527.7] | 24 | 8 | 0 | 16 | 0 |
| 12 | kit-mcts 0.3.0+068718d79078 | 1.487761 | 1258.5 | [1096.5, 1363.8] | 24 | 4 | 0 | 20 | 0 |
| 13 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.829296 | 1144.1 | [1000.0, 1289.7] | 24 | 16 | 0 | 8 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.829296 | 1144.1 | [1029.4, 1267.4] | 24 | 16 | 0 | 8 | 0 |
| 3 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.657539 | 1114.2 | [1000.0, 1234.4] | 24 | 15 | 0 | 9 | 0 |
| 4 | c12 pauper-v2.0.0 | 0.616847 | 1107.2 | [1022.6, 1194.3] | 96 | 62 | 0 | 34 | 0 |
| 5 | g115 pauper-v2.0.0 | 0.577494 | 1100.3 | [1014.7, 1188.4] | 96 | 61 | 0 | 35 | 0 |
| 6 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.326561 | 1056.7 | [935.2, 1184.9] | 24 | 13 | 0 | 11 | 0 |
| 7 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.326561 | 1056.7 | [943.0, 1175.7] | 24 | 13 | 0 | 11 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 11 | 0 | 13 | 0 |
| 9 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.000000 | 1000.0 | [857.2, 1143.8] | 24 | 11 | 0 | 13 | 0 |
| 10 | kit-mcts 0.3.0+068718d79078 | -0.511057 | 911.2 | [783.4, 1030.1] | 24 | 8 | 0 | 16 | 0 |
| 11 | a48 pauper-v2.0.0 | -0.748632 | 869.9 | [782.8, 946.4] | 96 | 27 | 0 | 69 | 0 |
| 12 | kit-mad-k 0.3.0+a49c05ddab71 | -0.890207 | 845.4 | [692.7, 970.4] | 24 | 6 | 0 | 18 | 0 |
| 13 | kit-mad-1 0.3.0+4e575c6a49fc | -1.101059 | 808.7 | [713.2, 904.8] | 24 | 5 | 0 | 19 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.875428 | 1499.5 | [1371.2, 1695.9] | 96 | 83 | 0 | 13 | 0 |
| 2 | kit-mad-k 0.3.0+a49c05ddab71 | 2.499736 | 1434.2 | [1284.6, 1631.3] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 2.137063 | 1371.2 | [1218.6, 1591.4] | 24 | 14 | 0 | 10 | 0 |
| 4 | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.962647 | 1340.9 | [1202.1, 1529.6] | 24 | 13 | 0 | 11 | 0 |
| 5 | a48 pauper-v2.0.0 | 1.583653 | 1275.1 | [1163.9, 1431.2] | 96 | 56 | 0 | 40 | 0 |
| 6 | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.271579 | 1220.9 | [1066.6, 1420.7] | 24 | 9 | 0 | 15 | 0 |
| 7 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.271579 | 1220.9 | [1066.5, 1419.7] | 24 | 9 | 0 | 15 | 0 |
| 8 | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.091817 | 1189.7 | [1000.0, 1405.2] | 24 | 8 | 0 | 16 | 0 |
| 9 | c12 pauper-v2.0.0 | 0.962692 | 1167.2 | [1048.8, 1314.7] | 96 | 41 | 0 | 55 | 0 |
| 10 | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.904929 | 1157.2 | [954.5, 1376.4] | 24 | 7 | 0 | 17 | 0 |
| 11 | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.263394 | 1045.8 | [829.2, 1263.7] | 24 | 4 | 0 | 20 | 0 |
| 12 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |
| 13 | kit-mcts 0.3.0+068718d79078 | -0.705534 | 877.4 | [693.2, 1068.9] | 24 | 1 | 0 | 23 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 768 | 4 | 0.005 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 1 | 0.005 | 0 | 0.000 |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 2 | 0.010 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 1 | 0.005 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 2 | 0.010 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 2 | 0.010 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
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
