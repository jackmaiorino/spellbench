# Spellbench leaderboard: pauper-bo1

- Games: 1920 played, 1914 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 6)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 2.560747 | 1444.8 | [1396.8, 1498.6] | 508 | 337 | 0 | 171 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.524049 | 1438.5 | [1386.5, 1494.2] | 382 | 236 | 0 | 146 | 0 |
| 3 | g115 pauper-v2.0.0 | 1.976486 | 1343.4 | [1297.6, 1393.7] | 636 | 352 | 0 | 284 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.586435 | 1275.6 | [1236.9, 1320.5] | 767 | 394 | 0 | 373 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.328207 | 1230.7 | [1190.4, 1276.5] | 640 | 315 | 0 | 325 | 0 |
| 6 | heuristic 2.0.0 | 0.639037 | 1111.0 | [1071.4, 1153.6] | 511 | 188 | 0 | 323 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 92 | 0 | 292 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| heuristic | c12 | 128 | 46 | 0 | 82 | 0.3594 | [0.2734, 0.4375] | 0.0021 |
| heuristic | g115 | 127 | 27 | 0 | 100 | 0.2143 | [0.1508, 0.2778] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 37 | 0 | 91 | 0.2891 | [0.2188, 0.3594] | 0.0000 |
| heuristic | uniform | 128 | 78 | 0 | 50 | 0.6094 | [0.5391, 0.6797] | 0.0066 |
| oh2-r2s1-b512 | c12 | 128 | 104 | 0 | 24 | 0.8125 | [0.7500, 0.8750] | 0.0000 |
| oh2-r2s1-b512 | g115 | 126 | 72 | 0 | 54 | 0.5645 | [0.4758, 0.6452] | 0.2005 |
| oh2-r2s1-b512 | gorge-ar8 | 127 | 97 | 0 | 30 | 0.7698 | [0.6984, 0.8413] | 0.0000 |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 127 | 64 | 0 | 63 | 0.5079 | [0.4365, 0.5794] | 1.0000 |
| c12 | g115 | 128 | 52 | 0 | 76 | 0.4062 | [0.3281, 0.4844] | 0.0428 |
| c12 | gorge-ar8 | 128 | 56 | 0 | 72 | 0.4375 | [0.3594, 0.5156] | 0.1849 |
| c12 | uniform | 128 | 101 | 0 | 27 | 0.7891 | [0.7188, 0.8516] | 0.0000 |
| g115 | gorge-ar8 | 128 | 76 | 0 | 52 | 0.5938 | [0.5234, 0.6641] | 0.0227 |
| g115 | oh2-r2s1-b512-argmax | 127 | 46 | 0 | 81 | 0.3651 | [0.2937, 0.4365] | 0.0009 |
| gorge-ar8 | uniform | 128 | 113 | 0 | 15 | 0.8828 | [0.8281, 0.9375] | 0.0000 |
| gorge-ar8 | oh2-r2s1-b512-argmax | 128 | 36 | 0 | 92 | 0.2812 | [0.2109, 0.3594] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.891998 | 1155.0 | 128 | 91 | 0 | 37 |
| heuristic 2.0.0 | 0.000000 | 1000.0 | 128 | 37 | 0 | 91 |

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 381 | 240 | 0 | 141 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.002958 | 999.5 | 254 | 144 | 0 | 110 |
| g115 pauper-v2.0.0 | -0.521145 | 909.5 | 381 | 176 | 0 | 205 |
| c12 pauper-v2.0.0 | -1.128988 | 803.9 | 256 | 76 | 0 | 180 |

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 1.841821 | 1320.0 | [1320.0, 1320.0] | 8 | 6 | 0 | 2 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.440641 | 1250.3 | [1250.3, 1250.3] | 12 | 8 | 0 | 4 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 1.414202 | 1245.7 | [1245.7, 1245.7] | 6 | 3 | 0 | 3 | 0 |
| 4 | g115 pauper-v2.0.0 | 0.958838 | 1166.6 | [1166.6, 1166.6] | 10 | 4 | 0 | 6 | 0 |
| 5 | heuristic 2.0.0 | 0.782641 | 1136.0 | [1136.0, 1136.0] | 8 | 4 | 0 | 4 | 0 |
| 6 | c12 pauper-v2.0.0 | 0.716627 | 1124.5 | [1124.5, 1124.5] | 10 | 4 | 0 | 6 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 1 | 0 | 5 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.260156 | 1392.6 | [1392.6, 1392.6] | 6 | 5 | 0 | 1 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 1.569868 | 1272.7 | [1272.7, 1272.7] | 8 | 5 | 0 | 3 | 0 |
| 3 | g115 pauper-v2.0.0 | 1.483676 | 1257.7 | [1257.7, 1257.7] | 10 | 7 | 0 | 3 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.772576 | 1134.2 | [1134.2, 1134.2] | 12 | 6 | 0 | 6 | 0 |
| 5 | c12 pauper-v2.0.0 | 0.254354 | 1044.2 | [1044.2, 1044.2] | 10 | 4 | 0 | 6 | 0 |
| 6 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 3 | 0 | 3 | 0 |
| 7 | heuristic 2.0.0 | -1.084400 | 811.6 | [811.6, 811.6] | 8 | 0 | 0 | 8 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 1.316777 | 1228.7 | [1228.7, 1228.7] | 8 | 7 | 0 | 1 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 0.778640 | 1135.3 | [1135.3, 1135.3] | 6 | 4 | 0 | 2 | 0 |
| 3 | c12 pauper-v2.0.0 | 0.362314 | 1062.9 | [1062.9, 1062.9] | 10 | 6 | 0 | 4 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.011702 | 1002.0 | [1002.0, 1002.0] | 12 | 5 | 0 | 7 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 3 | 0 | 3 | 0 |
| 6 | heuristic 2.0.0 | -0.374418 | 935.0 | [935.0, 935.0] | 8 | 3 | 0 | 5 | 0 |
| 7 | g115 pauper-v2.0.0 | -0.497863 | 913.5 | [913.5, 913.5] | 10 | 2 | 0 | 8 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.065398 | 1532.5 | [1532.5, 1532.5] | 6 | 5 | 0 | 1 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.598492 | 1451.4 | [1451.4, 1451.4] | 10 | 7 | 0 | 3 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.170695 | 1377.1 | [1377.1, 1377.1] | 8 | 4 | 0 | 4 | 0 |
| 4 | heuristic 2.0.0 | 1.829323 | 1317.8 | [1317.8, 1317.8] | 8 | 5 | 0 | 3 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.640188 | 1284.9 | [1284.9, 1284.9] | 10 | 5 | 0 | 5 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.391041 | 1241.6 | [1241.6, 1241.6] | 12 | 4 | 0 | 8 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 0 | 0 | 6 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.449244 | 1599.2 | [1599.2, 1599.2] | 6 | 5 | 0 | 1 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 2.700626 | 1469.1 | [1469.1, 1469.1] | 12 | 9 | 0 | 3 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.522382 | 1438.2 | [1438.2, 1438.2] | 10 | 6 | 0 | 4 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 2.233288 | 1388.0 | [1388.0, 1388.0] | 8 | 3 | 0 | 5 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.724400 | 1299.6 | [1299.6, 1299.6] | 10 | 5 | 0 | 5 | 0 |
| 6 | heuristic 2.0.0 | 0.916075 | 1159.1 | [1159.1, 1159.1] | 8 | 2 | 0 | 6 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 0 | 0 | 6 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.204644 | 1383.0 | [1383.0, 1383.0] | 6 | 5 | 0 | 1 | 0 |
| 2 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.476947 | 1256.6 | [1256.6, 1256.6] | 12 | 8 | 0 | 4 | 0 |
| 3 | g115 pauper-v2.0.0 | 1.225894 | 1213.0 | [1213.0, 1213.0] | 10 | 5 | 0 | 5 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 1.021531 | 1177.5 | [1177.5, 1177.5] | 8 | 3 | 0 | 5 | 0 |
| 5 | heuristic 2.0.0 | 0.840287 | 1146.0 | [1146.0, 1146.0] | 8 | 4 | 0 | 4 | 0 |
| 6 | c12 pauper-v2.0.0 | 0.636801 | 1110.6 | [1110.6, 1110.6] | 10 | 4 | 0 | 6 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 1 | 0 | 5 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512 pauper-v2.0.0 | 1.839539 | 1319.6 | [1319.6, 1319.6] | 8 | 6 | 0 | 2 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 1.589160 | 1276.1 | [1276.1, 1276.1] | 6 | 4 | 0 | 2 | 0 |
| 3 | c12 pauper-v2.0.0 | 1.397569 | 1242.8 | [1242.8, 1242.8] | 10 | 7 | 0 | 3 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0.803647 | 1139.6 | [1139.6, 1139.6] | 12 | 5 | 0 | 7 | 0 |
| 5 | heuristic 2.0.0 | 0.726855 | 1126.3 | [1126.3, 1126.3] | 8 | 4 | 0 | 4 | 0 |
| 6 | g115 pauper-v2.0.0 | 0.699906 | 1121.6 | [1121.6, 1121.6] | 10 | 3 | 0 | 7 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 1 | 0 | 5 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 3.097871 | 1538.2 | [1538.2, 1538.2] | 6 | 5 | 0 | 1 | 0 |
| 2 | oh2-r2s1-b512 pauper-v2.0.0 | 2.448404 | 1425.3 | [1425.3, 1425.3] | 8 | 5 | 0 | 3 | 0 |
| 3 | g115 pauper-v2.0.0 | 2.111560 | 1366.8 | [1366.8, 1366.8] | 10 | 6 | 0 | 4 | 0 |
| 4 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.823924 | 1316.8 | [1316.8, 1316.8] | 12 | 7 | 0 | 5 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.319896 | 1229.3 | [1229.3, 1229.3] | 10 | 5 | 0 | 5 | 0 |
| 6 | heuristic 2.0.0 | 0.065888 | 1011.4 | [1011.4, 1011.4] | 8 | 1 | 0 | 7 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 6 | 1 | 0 | 5 | 0 |


## Deck grid

### Deck vs deck: all games

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 18 (60) | 37 (60) | 33 (60) | 72 (60) | 45 (60) | 48 (60) | 33 (60) |
| Rally | 82 (60) | - | 70 (60) | 67 (60) | 88 (60) | 83 (60) | 77 (60) | 78 (55) |
| Affinity | 63 (60) | 30 (60) | - | 55 (60) | 82 (60) | 60 (60) | 67 (60) | 62 (60) |
| Elves | 67 (60) | 33 (60) | 45 (60) | - | 80 (60) | 57 (60) | 80 (60) | 58 (60) |
| Spy | 28 (60) | 12 (60) | 18 (60) | 20 (60) | - | 27 (60) | 38 (60) | 12 (60) |
| Burn | 55 (60) | 17 (60) | 40 (60) | 43 (60) | 73 (60) | - | 52 (60) | 50 (60) |
| CawGates | 52 (60) | 23 (60) | 33 (60) | 20 (60) | 62 (60) | 48 (60) | - | 33 (59) |
| Faeries | 67 (60) | 22 (55) | 38 (60) | 42 (60) | 88 (60) | 50 (60) | 67 (59) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1695.6 | [1666.6, 1728.7] |
| Elves | 1566.0 | [1539.8, 1595.1] |
| Affinity | 1564.4 | [1537.5, 1592.4] |
| Faeries | 1523.4 | [1498.9, 1548.2] |
| Burn | 1481.4 | [1455.1, 1507.1] |
| Wildfire | 1440.5 | [1412.7, 1466.6] |
| CawGates | 1425.7 | [1398.0, 1451.7] |
| Spy | 1303.0 | [1269.5, 1332.9] |

Transitivity: observed scores differ from the deck ratings' predictions by 4.7 points RMS.

### Deck vs deck: strong pilots (top half of the table)

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 12 (24) | 33 (24) | 42 (24) | 75 (24) | 33 (24) | 58 (24) | 29 (24) |
| Rally | 88 (24) | - | 83 (24) | 67 (24) | 92 (24) | 79 (24) | 92 (24) | 88 (20) |
| Affinity | 67 (24) | 17 (24) | - | 50 (24) | 71 (24) | 54 (24) | 62 (24) | 75 (24) |
| Elves | 58 (24) | 33 (24) | 50 (24) | - | 88 (24) | 42 (24) | 75 (24) | 75 (24) |
| Spy | 25 (24) | 8 (24) | 29 (24) | 12 (24) | - | 33 (24) | 42 (24) | 17 (24) |
| Burn | 67 (24) | 21 (24) | 46 (24) | 58 (24) | 67 (24) | - | 67 (24) | 67 (24) |
| CawGates | 42 (24) | 8 (24) | 38 (24) | 25 (24) | 58 (24) | 33 (24) | - | 27 (23) |
| Faeries | 71 (24) | 12 (20) | 25 (24) | 25 (24) | 83 (24) | 33 (24) | 73 (23) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1745.3 | [1700.7, 1802.8] |
| Elves | 1564.2 | [1523.1, 1609.9] |
| Affinity | 1540.5 | [1496.8, 1589.3] |
| Burn | 1536.6 | [1500.6, 1580.0] |
| Faeries | 1473.3 | [1432.6, 1513.6] |
| Wildfire | 1435.8 | [1394.3, 1474.9] |
| CawGates | 1386.5 | [1340.5, 1426.7] |
| Spy | 1317.7 | [1268.6, 1360.4] |

Transitivity: observed scores differ from the deck ratings' predictions by 7.9 points RMS.

### Robustness: score by own deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 | 52 | 81 | 77 | 73 | 50 | 80 | 67 | 52 |
| oh2-r2s1-b512-argmax | 56 | 88 | 60 | 69 | 38 | 69 | 58 | 57 |
| g115 | 59 | 83 | 70 | 74 | 15 | 72 | 12 | 58 |
| gorge-ar8 | 46 | 84 | 60 | 47 | 25 | 43 | 46 | 60 |
| c12 | 40 | 69 | 58 | 60 | 32 | 35 | 42 | 58 |
| heuristic | 20 | 67 | 45 | 52 | 14 | 16 | 36 | 45 |
| uniform | 12 | 40 | 29 | 35 | 4 | 15 | 23 | 33 |

### Robustness: score by opponent's deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 | 78 | 35 | 61 | 53 | 91 | 62 | 83 | 67 |
| oh2-r2s1-b512-argmax | 79 | 26 | 50 | 52 | 85 | 58 | 77 | 65 |
| g115 | 62 | 27 | 50 | 52 | 72 | 59 | 65 | 55 |
| gorge-ar8 | 53 | 32 | 50 | 41 | 67 | 54 | 59 | 55 |
| c12 | 59 | 29 | 36 | 41 | 81 | 50 | 59 | 39 |
| heuristic | 36 | 17 | 23 | 31 | 73 | 38 | 48 | 27 |
| uniform | 40 | 4 | 8 | 10 | 50 | 44 | 23 | 12 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 512 | 3 | 0.006 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 384 | 1 | 0.003 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 768 | 1 | 0.001 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 512 | 1 | 0.002 | 0 | 0.000 |
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
- off-mirror games only; the unit is the seat-swapped pair, which gives each bot both decks
- scores are the earlier deck's, over complete pairs; W/D/L counts every rated game
- strong pilots: games where both bots rank in the top half of the overall table
- deck ratings: anchored Bradley-Terry over decks, one virtual draw per pairing, centered so the average deck is Elo 1500
- predicted scores come from the deck ratings; residual_rms_e6 measures how far the matrix is from transitive
- robustness: rated games by own deck and by opponent deck, self-play excluded, mirrors included
