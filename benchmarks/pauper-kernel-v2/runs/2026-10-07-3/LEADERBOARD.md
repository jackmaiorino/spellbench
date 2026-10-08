# Spellbench leaderboard: pauper-bo1

- Games: 960 played, 960 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 1.971514 | 1342.5 | [1281.5, 1423.4] | 384 | 272 | 0 | 112 | 0 |
| 2 | kit-mad-k 0.3.0+a49c05ddab71 | 1.566033 | 1272.0 | [1194.3, 1362.1] | 192 | 96 | 0 | 96 | 0 |
| 3 | c12 pauper-v2.0.0 | 1.491196 | 1259.0 | [1195.5, 1340.2] | 384 | 225 | 0 | 159 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 1.461012 | 1253.8 | [1178.6, 1338.5] | 192 | 91 | 0 | 101 | 0 |
| 5 | a48 pauper-v2.0.0 | 1.237906 | 1215.0 | [1155.6, 1289.3] | 384 | 199 | 0 | 185 | 0 |
| 6 | kit-mcts 0.3.0+068718d79078 | 0.352577 | 1061.2 | [976.1, 1157.7] | 192 | 44 | 0 | 148 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 192 | 33 | 0 | 159 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| uniform | a48 | 64 | 11 | 0 | 53 | 0.1719 | [0.0781, 0.2656] | 0.0000 |
| uniform | c12 | 64 | 15 | 0 | 49 | 0.2344 | [0.1250, 0.3438] | 0.0002 |
| uniform | g115 | 64 | 7 | 0 | 57 | 0.1094 | [0.0469, 0.1875] | 0.0000 |
| kit-mad-1 | a48 | 64 | 38 | 0 | 26 | 0.5938 | [0.4844, 0.7188] | 0.2101 |
| kit-mad-1 | c12 | 64 | 27 | 0 | 37 | 0.4219 | [0.2969, 0.5469] | 0.3323 |
| kit-mad-1 | g115 | 64 | 26 | 0 | 38 | 0.4062 | [0.2656, 0.5625] | 0.2863 |
| kit-mad-k | a48 | 64 | 37 | 0 | 27 | 0.5781 | [0.4531, 0.7031] | 0.3593 |
| kit-mad-k | c12 | 64 | 31 | 0 | 33 | 0.4844 | [0.3594, 0.6250] | 1.0000 |
| kit-mad-k | g115 | 64 | 28 | 0 | 36 | 0.4375 | [0.2969, 0.5781] | 0.5235 |
| a48 | c12 | 64 | 31 | 0 | 33 | 0.4844 | [0.3750, 0.5938] | 1.0000 |
| a48 | kit-mcts | 64 | 45 | 0 | 19 | 0.7031 | [0.5938, 0.8125] | 0.0044 |
| a48 | g115 | 64 | 17 | 0 | 47 | 0.2656 | [0.1719, 0.3750] | 0.0007 |
| c12 | kit-mcts | 64 | 51 | 0 | 13 | 0.7969 | [0.7031, 0.8906] | 0.0000 |
| c12 | g115 | 64 | 22 | 0 | 42 | 0.3438 | [0.2344, 0.4531] | 0.0213 |
| kit-mcts | g115 | 64 | 12 | 0 | 52 | 0.1875 | [0.0938, 0.2812] | 0.0000 |

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
| 1 | kit-mad-1 0.3.0+4e575c6a49fc | 2.994125 | 1520.1 | [1345.1, 1766.7] | 24 | 18 | 0 | 6 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.683401 | 1466.2 | [1318.0, 1683.4] | 48 | 35 | 0 | 13 | 0 |
| 3 | kit-mad-k 0.3.0+a49c05ddab71 | 2.629407 | 1456.8 | [1288.8, 1684.9] | 24 | 16 | 0 | 8 | 0 |
| 4 | a48 pauper-v2.0.0 | 1.640004 | 1284.9 | [1171.1, 1451.8] | 48 | 22 | 0 | 26 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.640004 | 1284.9 | [1155.0, 1469.4] | 48 | 22 | 0 | 26 | 0 |
| 6 | kit-mcts 0.3.0+068718d79078 | 0.775891 | 1134.8 | [955.5, 1338.0] | 24 | 5 | 0 | 19 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 2 | 0 | 22 | 0 |

### Burn

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.857596 | 1496.4 | [1371.3, 1648.7] | 48 | 40 | 0 | 8 | 0 |
| 2 | c12 pauper-v2.0.0 | 2.242752 | 1389.6 | [1272.1, 1526.8] | 48 | 33 | 0 | 15 | 0 |
| 3 | a48 pauper-v2.0.0 | 1.923145 | 1334.1 | [1199.4, 1478.1] | 48 | 29 | 0 | 19 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 1.706737 | 1296.5 | [1115.7, 1498.1] | 24 | 8 | 0 | 16 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.706737 | 1296.5 | [1133.5, 1474.1] | 24 | 8 | 0 | 16 | 0 |
| 6 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |
| 7 | kit-mcts 0.3.0+068718d79078 | 0.000000 | 1000.0 | [835.2, 1164.7] | 24 | 1 | 0 | 23 | 0 |

### CawGates

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kit-mad-k 0.3.0+a49c05ddab71 | 1.320900 | 1229.5 | [1083.7, 1414.9] | 24 | 19 | 0 | 5 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 0.774157 | 1134.5 | [973.8, 1308.0] | 24 | 16 | 0 | 8 | 0 |
| 3 | c12 pauper-v2.0.0 | 0.516984 | 1089.8 | [979.4, 1202.8] | 48 | 27 | 0 | 21 | 0 |
| 4 | a48 pauper-v2.0.0 | 0.108103 | 1018.8 | [899.9, 1146.2] | 48 | 21 | 0 | 27 | 0 |
| 5 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 11 | 0 | 13 | 0 |
| 6 | g115 pauper-v2.0.0 | -0.169729 | 970.5 | [855.6, 1084.4] | 48 | 17 | 0 | 31 | 0 |
| 7 | kit-mcts 0.3.0+068718d79078 | -0.309395 | 946.3 | [796.0, 1084.2] | 24 | 9 | 0 | 15 | 0 |

### Elves

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | c12 pauper-v2.0.0 | 2.509931 | 1436.0 | [1314.9, 1583.6] | 48 | 33 | 0 | 15 | 0 |
| 2 | g115 pauper-v2.0.0 | 2.509931 | 1436.0 | [1293.2, 1594.3] | 48 | 33 | 0 | 15 | 0 |
| 3 | kit-mad-k 0.3.0+a49c05ddab71 | 2.466996 | 1428.6 | [1256.1, 1631.1] | 24 | 13 | 0 | 11 | 0 |
| 4 | a48 pauper-v2.0.0 | 1.923714 | 1334.2 | [1219.6, 1461.9] | 48 | 25 | 0 | 23 | 0 |
| 5 | kit-mcts 0.3.0+068718d79078 | 1.693221 | 1294.1 | [1095.3, 1480.9] | 24 | 8 | 0 | 16 | 0 |
| 6 | kit-mad-1 0.3.0+4e575c6a49fc | 1.523419 | 1264.6 | [1103.8, 1423.7] | 24 | 7 | 0 | 17 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 1 | 0 | 23 | 0 |

### Faeries

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 1.552956 | 1269.8 | [1167.1, 1420.6] | 48 | 32 | 0 | 16 | 0 |
| 2 | a48 pauper-v2.0.0 | 1.344951 | 1233.6 | [1118.1, 1403.0] | 48 | 29 | 0 | 19 | 0 |
| 3 | c12 pauper-v2.0.0 | 1.209699 | 1210.1 | [1092.3, 1369.6] | 48 | 27 | 0 | 21 | 0 |
| 4 | kit-mad-1 0.3.0+4e575c6a49fc | 1.069177 | 1185.7 | [1060.1, 1347.7] | 24 | 10 | 0 | 14 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 1.069177 | 1185.7 | [1000.0, 1386.6] | 24 | 10 | 0 | 14 | 0 |
| 6 | kit-mcts 0.3.0+068718d79078 | 0.755297 | 1131.2 | [1000.0, 1290.7] | 24 | 8 | 0 | 16 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 4 | 0 | 20 | 0 |

### Rally

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 3.298275 | 1573.0 | [1508.4, 1661.6] | 48 | 37 | 0 | 11 | 0 |
| 2 | kit-mad-1 0.3.0+4e575c6a49fc | 3.021404 | 1524.9 | [1388.8, 1674.1] | 24 | 13 | 0 | 11 | 0 |
| 3 | a48 pauper-v2.0.0 | 2.657665 | 1461.7 | [1409.9, 1523.6] | 48 | 29 | 0 | 19 | 0 |
| 4 | c12 pauper-v2.0.0 | 2.657665 | 1461.7 | [1408.1, 1528.8] | 48 | 29 | 0 | 19 | 0 |
| 5 | kit-mad-k 0.3.0+a49c05ddab71 | 2.245615 | 1390.1 | [1256.2, 1529.1] | 24 | 8 | 0 | 16 | 0 |
| 6 | kit-mcts 0.3.0+068718d79078 | 1.481094 | 1257.3 | [1096.3, 1364.2] | 24 | 4 | 0 | 20 | 0 |
| 7 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 0 | 0 | 24 | 0 |

### Spy

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 0.752159 | 1130.7 | [1034.3, 1239.0] | 48 | 38 | 0 | 10 | 0 |
| 2 | c12 pauper-v2.0.0 | 0.425945 | 1074.0 | [980.0, 1171.9] | 48 | 34 | 0 | 14 | 0 |
| 3 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 11 | 0 | 13 | 0 |
| 4 | kit-mcts 0.3.0+068718d79078 | -0.510022 | 911.4 | [785.4, 1030.3] | 24 | 8 | 0 | 16 | 0 |
| 5 | a48 pauper-v2.0.0 | -0.723797 | 874.3 | [775.7, 957.2] | 48 | 18 | 0 | 30 | 0 |
| 6 | kit-mad-k 0.3.0+a49c05ddab71 | -0.887962 | 845.7 | [682.3, 970.3] | 24 | 6 | 0 | 18 | 0 |
| 7 | kit-mad-1 0.3.0+4e575c6a49fc | -1.098078 | 809.2 | [712.3, 902.0] | 24 | 5 | 0 | 19 | 0 |

### Wildfire

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | g115 pauper-v2.0.0 | 2.772845 | 1481.7 | [1332.6, 1705.1] | 48 | 40 | 0 | 8 | 0 |
| 2 | kit-mad-k 0.3.0+a49c05ddab71 | 2.457352 | 1426.9 | [1283.1, 1638.3] | 24 | 16 | 0 | 8 | 0 |
| 3 | kit-mad-1 0.3.0+4e575c6a49fc | 2.102092 | 1365.2 | [1216.4, 1582.4] | 24 | 14 | 0 | 10 | 0 |
| 4 | a48 pauper-v2.0.0 | 1.535196 | 1266.7 | [1163.6, 1421.3] | 48 | 26 | 0 | 22 | 0 |
| 5 | c12 pauper-v2.0.0 | 1.025508 | 1178.1 | [1055.3, 1342.6] | 48 | 20 | 0 | 28 | 0 |
| 6 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 24 | 3 | 0 | 21 | 0 |
| 7 | kit-mcts 0.3.0+068718d79078 | -0.700467 | 878.3 | [692.9, 1068.4] | 24 | 1 | 0 | 23 | 0 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| g115 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-k 0.3.0+a49c05ddab71 | 192 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 192 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
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
