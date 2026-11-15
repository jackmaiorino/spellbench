# Spellbench leaderboard: pauper-bo1

- Games: 2304 played, 2304 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 3.833778 | 1666.0 | [1600.8, 1739.0] | 384 | 288 | 0 | 96 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.900084 | 1503.8 | [1450.5, 1563.7] | 640 | 379 | 0 | 261 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.898904 | 1503.6 | [1444.6, 1566.9] | 512 | 276 | 0 | 236 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.394785 | 1416.0 | [1363.0, 1473.9] | 768 | 396 | 0 | 372 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.800452 | 1312.8 | [1266.2, 1362.3] | 768 | 380 | 0 | 388 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.507533 | 1261.9 | [1213.9, 1312.6] | 640 | 301 | 0 | 339 | 0 |
| 7 | heuristic 2.0.0 | 1.034717 | 1179.7 | [1134.3, 1227.0] | 512 | 210 | 0 | 302 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 74 | 0 | 310 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 128 | 65 | 0 | 63 | 0.5078 | [0.4219, 0.5859] | 1.0000 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 102 | 0 | 26 | 0.7969 | [0.7266, 0.8672] | 0.0000 |
| oh2-r2s1-b512 | g115 | 128 | 78 | 0 | 50 | 0.6094 | [0.5156, 0.6953] | 0.0288 |
| oh2-r2s1-b512 | chains-a-c4-u1048576 | 128 | 31 | 0 | 97 | 0.2422 | [0.1719, 0.3125] | 0.0000 |
| oh2-r2s1-b512 | c12 | 128 | 103 | 0 | 25 | 0.8047 | [0.7422, 0.8672] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 41 | 0 | 87 | 0.3203 | [0.2422, 0.4062] | 0.0003 |
| heuristic | g115 | 128 | 28 | 0 | 100 | 0.2188 | [0.1484, 0.2969] | 0.0000 |
| heuristic | uniform | 128 | 90 | 0 | 38 | 0.7031 | [0.6250, 0.7812] | 0.0000 |
| heuristic | c12 | 128 | 51 | 0 | 77 | 0.3984 | [0.3125, 0.4844] | 0.0351 |
| oh2-r2s1-b512-argmax | gorge-ar8 | 128 | 99 | 0 | 29 | 0.7734 | [0.7031, 0.8438] | 0.0000 |
| oh2-r2s1-b512-argmax | g115 | 128 | 78 | 0 | 50 | 0.6094 | [0.5312, 0.6875] | 0.0161 |
| oh2-r2s1-b512-argmax | chains-a-c4-u1048576 | 128 | 36 | 0 | 92 | 0.2812 | [0.1953, 0.3672] | 0.0000 |
| gorge-ar8 | g115 | 128 | 45 | 0 | 83 | 0.3516 | [0.2578, 0.4375] | 0.0043 |
| gorge-ar8 | uniform | 128 | 118 | 0 | 10 | 0.9219 | [0.8672, 0.9688] | 0.0000 |
| gorge-ar8 | c12 | 128 | 75 | 0 | 53 | 0.5859 | [0.5078, 0.6641] | 0.0614 |
| g115 | chains-a-c4-u1048576 | 128 | 29 | 0 | 99 | 0.2266 | [0.1406, 0.3125] | 0.0000 |
| g115 | c12 | 128 | 84 | 0 | 44 | 0.6562 | [0.5703, 0.7422] | 0.0022 |
| uniform | c12 | 128 | 26 | 0 | 102 | 0.2031 | [0.1328, 0.2734] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.745945 | 1129.6 | 128 | 87 | 0 | 41 |
| heuristic 2.0.0 | 0.000000 | 1000.0 | 128 | 41 | 0 | 87 |

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 pauper-v2.0.0 | 0.948468 | 1164.8 | 384 | 288 | 0 | 96 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 512 | 277 | 0 | 235 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.007130 | 998.8 | 384 | 177 | 0 | 207 |
| g115 pauper-v2.0.0 | -0.444964 | 922.7 | 512 | 213 | 0 | 299 |
| c12 pauper-v2.0.0 | -1.221765 | 787.8 | 256 | 69 | 0 | 187 |

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 3.236693 | 1562.3 | [1422.4, 1739.0] | 48 | 32 | 0 | 16 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.904153 | 1504.5 | [1377.5, 1655.5] | 64 | 39 | 0 | 25 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.587277 | 1449.5 | [1329.4, 1602.1] | 80 | 45 | 0 | 35 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.235300 | 1388.3 | [1278.6, 1529.7] | 96 | 51 | 0 | 45 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.782297 | 1309.6 | [1209.5, 1438.6] | 96 | 51 | 0 | 45 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.481056 | 1257.3 | [1151.5, 1382.8] | 80 | 41 | 0 | 39 | 0 |
| 7 | heuristic 2.0.0 | 0.380500 | 1066.1 | [961.9, 1176.8] | 64 | 18 | 0 | 46 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 11 | 0 | 37 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 4.649104 | 1807.6 | [1667.1, 1993.1] | 48 | 34 | 0 | 14 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.856849 | 1670.0 | [1550.7, 1825.7] | 80 | 50 | 0 | 30 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.815003 | 1662.7 | [1544.2, 1821.6] | 96 | 65 | 0 | 31 | 0 |
| 4 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.788922 | 1658.2 | [1518.3, 1823.4] | 64 | 34 | 0 | 30 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.101834 | 1365.1 | [1274.0, 1484.4] | 96 | 44 | 0 | 52 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.697591 | 1294.9 | [1195.7, 1421.5] | 80 | 35 | 0 | 45 | 0 |
| 7 | heuristic 2.0.0 | 0.601729 | 1104.5 | [999.5, 1229.4] | 64 | 17 | 0 | 47 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 9 | 0 | 39 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 4.988254 | 1866.5 | [1705.1, 2106.9] | 48 | 44 | 0 | 4 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.411181 | 1592.6 | [1467.5, 1771.5] | 80 | 56 | 0 | 24 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.187178 | 1553.7 | [1414.2, 1745.0] | 64 | 38 | 0 | 26 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.616273 | 1280.8 | [1170.3, 1430.5] | 96 | 51 | 0 | 45 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.145785 | 1199.0 | [1084.1, 1338.9] | 80 | 39 | 0 | 41 | 0 |
| 6 | heuristic 2.0.0 | 0.997206 | 1173.2 | [1068.0, 1306.7] | 64 | 35 | 0 | 29 | 0 |
| 7 | g115 pauper-v2.0.0 | 0.451906 | 1078.5 | [952.7, 1222.2] | 96 | 15 | 0 | 81 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 10 | 0 | 38 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 4.314675 | 1749.5 | [1577.2, 2014.1] | 48 | 38 | 0 | 10 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.241648 | 1563.1 | [1407.4, 1756.8] | 64 | 37 | 0 | 27 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.141185 | 1545.7 | [1409.4, 1719.0] | 96 | 62 | 0 | 34 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 2.834614 | 1492.4 | [1355.6, 1670.7] | 80 | 43 | 0 | 37 | 0 |
| 5 | heuristic 2.0.0 | 1.797445 | 1312.2 | [1178.2, 1474.8] | 64 | 38 | 0 | 26 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.500147 | 1260.6 | [1138.6, 1409.9] | 80 | 36 | 0 | 44 | 0 |
| 7 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.880467 | 1153.0 | [1044.5, 1287.3] | 96 | 25 | 0 | 71 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 9 | 0 | 39 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 4.044399 | 1702.6 | [1559.4, 1914.1] | 48 | 38 | 0 | 10 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.944648 | 1511.5 | [1389.2, 1664.5] | 64 | 32 | 0 | 32 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.818407 | 1489.6 | [1364.8, 1643.3] | 80 | 43 | 0 | 37 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.656858 | 1461.5 | [1341.2, 1613.7] | 96 | 53 | 0 | 43 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.337718 | 1406.1 | [1297.6, 1544.3] | 96 | 58 | 0 | 38 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.282323 | 1222.8 | [1129.6, 1350.2] | 80 | 31 | 0 | 49 | 0 |
| 7 | heuristic 2.0.0 | 1.079390 | 1187.5 | [1090.9, 1303.8] | 64 | 25 | 0 | 39 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 8 | 0 | 40 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 4.044000 | 1702.5 | [1543.0, 1941.4] | 48 | 30 | 0 | 18 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 3.828710 | 1665.1 | [1520.7, 1881.7] | 80 | 48 | 0 | 32 | 0 |
| 3 | g115 pauper-v2.0.0 | 3.448356 | 1599.0 | [1456.5, 1801.2] | 96 | 52 | 0 | 44 | 0 |
| 4 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.404384 | 1591.4 | [1435.6, 1808.8] | 64 | 28 | 0 | 36 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 3.264629 | 1567.1 | [1436.8, 1770.8] | 96 | 58 | 0 | 38 | 0 |
| 6 | c12 pauper-v2.0.0 | 3.036379 | 1527.5 | [1389.8, 1730.4] | 80 | 46 | 0 | 34 | 0 |
| 7 | heuristic 2.0.0 | 1.961837 | 1340.8 | [1215.2, 1512.5] | 64 | 24 | 0 | 40 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 2 | 0 | 46 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 2.118947 | 1368.1 | [1227.6, 1540.8] | 48 | 32 | 0 | 16 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 1.819331 | 1316.0 | [1198.2, 1463.6] | 80 | 48 | 0 | 32 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 1.490971 | 1259.0 | [1116.2, 1413.4] | 64 | 31 | 0 | 33 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.261882 | 1219.2 | [1102.7, 1344.2] | 80 | 47 | 0 | 33 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.224157 | 1212.7 | [1094.9, 1349.6] | 96 | 53 | 0 | 43 | 0 |
| 6 | g115 pauper-v2.0.0 | 1.050984 | 1182.6 | [1060.6, 1321.0] | 96 | 40 | 0 | 56 | 0 |
| 7 | heuristic 2.0.0 | 0.384320 | 1066.8 | [959.9, 1183.8] | 64 | 24 | 0 | 40 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 13 | 0 | 35 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 4.527225 | 1786.5 | [1643.0, 2005.2] | 48 | 40 | 0 | 8 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.303464 | 1573.9 | [1441.0, 1755.1] | 64 | 37 | 0 | 27 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.968749 | 1515.7 | [1395.5, 1687.7] | 80 | 46 | 0 | 34 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.851652 | 1495.4 | [1387.9, 1644.2] | 96 | 58 | 0 | 38 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.376924 | 1239.2 | [1157.8, 1346.7] | 96 | 40 | 0 | 56 | 0 |
| 6 | heuristic 2.0.0 | 0.984890 | 1171.1 | [1068.0, 1309.3] | 64 | 29 | 0 | 35 | 0 |
| 7 | c12 pauper-v2.0.0 | 0.750595 | 1130.4 | [1027.7, 1261.0] | 80 | 26 | 0 | 54 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 48 | 12 | 0 | 36 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 512 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
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
