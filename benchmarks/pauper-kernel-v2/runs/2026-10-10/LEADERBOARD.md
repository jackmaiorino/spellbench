# Spellbench leaderboard: pauper-bo1

- Games: 352 played, 352 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.087515 | 1362.6 | [1292.6, 1451.5] | 224 | 170 | 0 | 54 | 0 |
| 2 | a48 pauper-v2.0.0 | 1.444843 | 1251.0 | [1175.0, 1343.5] | 128 | 74 | 0 | 54 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 1.181806 | 1205.3 | [986.1, 1389.0] | 32 | 9 | 0 | 23 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.043757 | 1181.3 | [1112.8, 1263.4] | 128 | 64 | 0 | 64 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 35 | 0 | 157 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| uniform | g115 | 64 | 8 | 0 | 56 | 0.1250 | [0.0469, 0.2188] | 0.0000 |
| uniform | c12 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3594] | 0.0001 |
| uniform | a48 | 64 | 11 | 0 | 53 | 0.1719 | [0.0781, 0.2812] | 0.0000 |
| g115 | kit-mad-1 | 32 | 23 | 0 | 9 | 0.7188 | [0.5000, 0.9062] | 0.0923 |
| g115 | c12 | 64 | 48 | 0 | 16 | 0.7500 | [0.6250, 0.8594] | 0.0009 |
| g115 | a48 | 64 | 43 | 0 | 21 | 0.6719 | [0.5625, 0.7656] | 0.0074 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 91 | 0 | 37 |
| a48 pauper-v2.0.0 | -0.704708 | 877.6 | 64 | 21 | 0 | 43 |
| c12 pauper-v2.0.0 | -1.078203 | 812.7 | 64 | 16 | 0 | 48 |

### tag: search

skipped: no_rated_games

## By deck

### Affinity

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-1 0.3.0+4e575c6a49fc | 4.051171 | 1703.8 | [1457.7, 2079.3] | 4 | 3 | 0 | 1 | 0 |
| 2 | g115 pauper-v2.0.0 | 3.203873 | 1556.6 | [1426.7, 1768.8] | 28 | 23 | 0 | 5 | 0 |
| 3 | a48 pauper-v2.0.0 | 1.998326 | 1347.1 | [1249.2, 1490.0] | 16 | 9 | 0 | 7 | 0 |
| 4 | c12 pauper-v2.0.0 | 1.205547 | 1209.4 | [1054.0, 1438.1] | 16 | 7 | 0 | 9 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.285729 | 1570.8 | [1428.8, 1768.8] | 28 | 25 | 0 | 3 | 0 |
| 2 | a48 pauper-v2.0.0 | 2.447274 | 1425.1 | [1304.3, 1600.5] | 16 | 10 | 0 | 6 | 0 |
| 3 | c12 pauper-v2.0.0 | 1.642865 | 1285.4 | [1112.7, 1487.4] | 16 | 8 | 0 | 8 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 1.088505 | 1189.1 | [1047.1, 1387.1] | 4 | 0 | 0 | 4 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | c12 pauper-v2.0.0 | 0.569214 | 1098.9 | [1000.0, 1248.7] | 16 | 12 | 0 | 4 | 0 |
| 2 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 13 | 0 | 11 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | -0.006835 | 998.8 | [775.2, 1302.7] | 4 | 3 | 0 | 1 | 0 |
| 4 | a48 pauper-v2.0.0 | -0.193641 | 966.4 | [831.6, 1078.5] | 16 | 9 | 0 | 7 | 0 |
| 5 | g115 pauper-v2.0.0 | -0.854133 | 851.6 | [717.7, 957.9] | 28 | 7 | 0 | 21 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.123776 | 1542.7 | [1401.6, 1768.8] | 28 | 25 | 0 | 3 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 2.276478 | 1395.5 | [1076.0, 1703.2] | 4 | 1 | 0 | 3 | 0 |
| 3 | c12 pauper-v2.0.0 | 1.561888 | 1271.3 | [1102.7, 1487.4] | 16 | 8 | 0 | 8 | 0 |
| 4 | a48 pauper-v2.0.0 | 1.561888 | 1271.3 | [1115.5, 1487.4] | 16 | 8 | 0 | 8 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 1.991745 | 1346.0 | [1203.0, 1553.6] | 28 | 21 | 0 | 7 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 1.991745 | 1346.0 | [876.4, 1900.7] | 4 | 2 | 0 | 2 | 0 |
| 3 | a48 pauper-v2.0.0 | 1.862532 | 1323.6 | [1210.6, 1492.2] | 16 | 11 | 0 | 5 | 0 |
| 4 | c12 pauper-v2.0.0 | 0.129213 | 1022.4 | [819.4, 1209.5] | 16 | 5 | 0 | 11 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 5 | 0 | 19 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.186502 | 1553.6 | [1492.2, 1678.1] | 28 | 22 | 0 | 6 | 0 |
| 2 | a48 pauper-v2.0.0 | 3.131562 | 1544.0 | [1492.2, 1655.1] | 16 | 12 | 0 | 4 | 0 |
| 3 | c12 pauper-v2.0.0 | 2.374143 | 1412.4 | [1339.0, 1492.2] | 16 | 10 | 0 | 6 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 0.989277 | 1171.9 | [1110.5, 1296.4] | 4 | 0 | 0 | 4 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 0.941339 | 1163.5 | [1042.1, 1314.9] | 28 | 21 | 0 | 7 | 0 |
| 2 | c12 pauper-v2.0.0 | 0.470670 | 1081.8 | [973.8, 1220.3] | 16 | 8 | 0 | 8 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 9 | 0 | 15 | 0 |
| 4 | a48 pauper-v2.0.0 | -0.006316 | 998.9 | [812.4, 1161.3] | 16 | 6 | 0 | 10 | 0 |
| 5 | kit-mad-1 0.3.0+4e575c6a49fc | -1.255886 | 781.8 | [660.4, 933.2] | 4 | 0 | 0 | 4 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.995943 | 1520.4 | [1385.0, 1725.3] | 28 | 26 | 0 | 2 | 0 |
| 2 | a48 pauper-v2.0.0 | 1.869143 | 1324.7 | [1154.8, 1535.8] | 16 | 9 | 0 | 7 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 0.798719 | 1138.8 | [1003.3, 1343.6] | 4 | 0 | 0 | 4 | 0 |
| 4 | c12 pauper-v2.0.0 | 0.759524 | 1131.9 | [996.3, 1339.0] | 16 | 6 | 0 | 10 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |
| - | gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 224 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 32 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| gorge-legacy gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| kit-mad-k 0.3.0+a49c05ddab71 | 0 | 0 | - | 0 | - |
| kit-mcts 0.3.0+068718d79078 | 0 | 0 | - | 0 | - |
| gorge-explore gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| gorge-bot gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| gorge-lethal-pressure gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| gorge-blocks gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |

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
