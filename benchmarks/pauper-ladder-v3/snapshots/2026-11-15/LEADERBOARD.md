# Spellbench leaderboard: pauper-bo1

- Games: 2304 played, 2304 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 3.178503 | 1552.2 | [1495.7, 1615.5] | 384 | 260 | 0 | 124 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.658248 | 1461.8 | [1408.1, 1518.6] | 512 | 291 | 0 | 221 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.561287 | 1444.9 | [1397.3, 1501.7] | 640 | 374 | 0 | 266 | 0 |
| 4 | g115 pauper-v2.0.0 | 2.078081 | 1361.0 | [1314.5, 1411.4] | 768 | 386 | 0 | 382 | 0 |
| 5 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.647337 | 1286.2 | [1244.8, 1332.8] | 768 | 386 | 0 | 382 | 0 |
| 6 | c12 pauper-v2.0.0 | 1.408069 | 1244.6 | [1204.7, 1295.1] | 640 | 312 | 0 | 328 | 0 |
| 7 | heuristic 2.0.0 | 0.936900 | 1162.8 | [1122.5, 1207.3] | 512 | 214 | 0 | 298 | 0 |
| 8 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 81 | 0 | 303 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 128 | 65 | 0 | 63 | 0.5078 | [0.4297, 0.5859] | 1.0000 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 86 | 0 | 42 | 0.6719 | [0.5938, 0.7500] | 0.0001 |
| oh2-r2s1-b512 | g115 | 128 | 77 | 0 | 51 | 0.6016 | [0.5234, 0.6797] | 0.0241 |
| oh2-r2s1-b512 | chains-a-c4-u1048576 | 128 | 44 | 0 | 84 | 0.3438 | [0.2656, 0.4141] | 0.0003 |
| oh2-r2s1-b512 | c12 | 128 | 102 | 0 | 26 | 0.7969 | [0.7344, 0.8594] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 37 | 0 | 91 | 0.2891 | [0.2266, 0.3438] | 0.0000 |
| heuristic | g115 | 128 | 38 | 0 | 90 | 0.2969 | [0.2266, 0.3672] | 0.0000 |
| heuristic | uniform | 128 | 91 | 0 | 37 | 0.7109 | [0.6406, 0.7812] | 0.0000 |
| heuristic | c12 | 128 | 48 | 0 | 80 | 0.3750 | [0.3047, 0.4375] | 0.0009 |
| oh2-r2s1-b512-argmax | gorge-ar8 | 128 | 103 | 0 | 25 | 0.8047 | [0.7422, 0.8672] | 0.0000 |
| oh2-r2s1-b512-argmax | g115 | 128 | 79 | 0 | 49 | 0.6172 | [0.5469, 0.6875] | 0.0041 |
| oh2-r2s1-b512-argmax | chains-a-c4-u1048576 | 128 | 46 | 0 | 82 | 0.3594 | [0.2812, 0.4375] | 0.0009 |
| gorge-ar8 | g115 | 128 | 48 | 0 | 80 | 0.3750 | [0.2891, 0.4609] | 0.0090 |
| gorge-ar8 | uniform | 128 | 112 | 0 | 16 | 0.8750 | [0.8203, 0.9297] | 0.0000 |
| gorge-ar8 | c12 | 128 | 68 | 0 | 60 | 0.5312 | [0.4531, 0.6016] | 0.5572 |
| g115 | chains-a-c4-u1048576 | 128 | 34 | 0 | 94 | 0.2656 | [0.1953, 0.3359] | 0.0000 |
| g115 | c12 | 128 | 82 | 0 | 46 | 0.6406 | [0.5781, 0.7109] | 0.0003 |
| uniform | c12 | 128 | 28 | 0 | 100 | 0.2188 | [0.1484, 0.2969] | 0.0000 |

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
| chains-a-c4-u1048576 pauper-v2.0.0 | 0.577063 | 1100.2 | 384 | 260 | 0 | 124 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 512 | 288 | 0 | 224 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.013577 | 997.6 | 384 | 188 | 0 | 196 |
| g115 pauper-v2.0.0 | -0.485753 | 915.6 | 512 | 216 | 0 | 296 |
| c12 pauper-v2.0.0 | -1.185603 | 794.0 | 256 | 72 | 0 | 184 |


## Deck grid

### Deck vs deck: all games

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 12 (72) | 35 (72) | 36 (72) | 68 (72) | 38 (72) | 44 (72) | 36 (72) |
| Rally | 88 (72) | - | 76 (72) | 72 (72) | 92 (72) | 76 (72) | 86 (72) | 90 (72) |
| Affinity | 65 (72) | 24 (72) | - | 40 (72) | 75 (72) | 54 (72) | 67 (72) | 47 (72) |
| Elves | 64 (72) | 28 (72) | 60 (72) | - | 82 (72) | 51 (72) | 75 (72) | 61 (72) |
| Spy | 32 (72) | 8 (72) | 25 (72) | 18 (72) | - | 32 (72) | 31 (72) | 19 (72) |
| Burn | 62 (72) | 24 (72) | 46 (72) | 49 (72) | 68 (72) | - | 53 (72) | 44 (72) |
| CawGates | 56 (72) | 14 (72) | 33 (72) | 25 (72) | 69 (72) | 47 (72) | - | 33 (72) |
| Faeries | 64 (72) | 10 (72) | 53 (72) | 39 (72) | 81 (72) | 56 (72) | 67 (72) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1745.2 | [1716.3, 1778.4] |
| Elves | 1565.5 | [1541.4, 1592.4] |
| Affinity | 1518.8 | [1493.4, 1545.1] |
| Faeries | 1514.9 | [1490.5, 1539.8] |
| Burn | 1493.9 | [1467.6, 1519.6] |
| CawGates | 1429.1 | [1403.3, 1452.4] |
| Wildfire | 1421.0 | [1396.1, 1444.8] |
| Spy | 1311.6 | [1282.5, 1336.9] |

Transitivity: observed scores differ from the deck ratings' predictions by 4.4 points RMS.

### Deck vs deck: strong pilots (top half of the table)

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 12 (24) | 46 (24) | 38 (24) | 67 (24) | 29 (24) | 38 (24) | 42 (24) |
| Rally | 88 (24) | - | 83 (24) | 71 (24) | 92 (24) | 79 (24) | 92 (24) | 96 (24) |
| Affinity | 54 (24) | 17 (24) | - | 42 (24) | 71 (24) | 46 (24) | 75 (24) | 50 (24) |
| Elves | 62 (24) | 29 (24) | 58 (24) | - | 83 (24) | 38 (24) | 83 (24) | 71 (24) |
| Spy | 33 (24) | 8 (24) | 29 (24) | 17 (24) | - | 29 (24) | 29 (24) | 29 (24) |
| Burn | 71 (24) | 21 (24) | 54 (24) | 62 (24) | 71 (24) | - | 54 (24) | 58 (24) |
| CawGates | 62 (24) | 8 (24) | 25 (24) | 17 (24) | 71 (24) | 46 (24) | - | 50 (24) |
| Faeries | 58 (24) | 4 (24) | 50 (24) | 29 (24) | 71 (24) | 42 (24) | 50 (24) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1764.5 | [1718.3, 1823.3] |
| Elves | 1566.5 | [1528.9, 1608.0] |
| Burn | 1534.9 | [1492.4, 1583.6] |
| Affinity | 1500.1 | [1453.0, 1544.9] |
| Faeries | 1453.9 | [1411.0, 1497.9] |
| CawGates | 1430.6 | [1386.8, 1472.5] |
| Wildfire | 1422.7 | [1377.7, 1463.0] |
| Spy | 1326.6 | [1272.9, 1370.4] |

Transitivity: observed scores differ from the deck ratings' predictions by 7.2 points RMS.

### Robustness: score by own deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 | 54 | 90 | 73 | 77 | 46 | 73 | 67 | 62 |
| oh2-r2s1-b512-argmax | 50 | 84 | 48 | 61 | 38 | 66 | 53 | 55 |
| oh2-r2s1-b512 | 51 | 85 | 55 | 65 | 40 | 61 | 62 | 48 |
| g115 | 46 | 82 | 59 | 66 | 21 | 65 | 14 | 50 |
| gorge-ar8 | 41 | 85 | 54 | 56 | 24 | 38 | 47 | 57 |
| c12 | 39 | 84 | 55 | 54 | 22 | 51 | 34 | 51 |
| heuristic | 22 | 64 | 52 | 56 | 20 | 20 | 42 | 58 |
| uniform | 6 | 42 | 17 | 31 | 6 | 15 | 17 | 35 |

### Robustness: score by opponent's deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 | 75 | 38 | 67 | 54 | 88 | 69 | 75 | 77 |
| oh2-r2s1-b512-argmax | 73 | 19 | 56 | 42 | 81 | 56 | 66 | 61 |
| oh2-r2s1-b512 | 69 | 20 | 54 | 50 | 84 | 56 | 72 | 62 |
| g115 | 60 | 18 | 48 | 49 | 70 | 48 | 59 | 50 |
| gorge-ar8 | 61 | 28 | 49 | 42 | 71 | 46 | 58 | 47 |
| c12 | 59 | 28 | 42 | 38 | 75 | 51 | 61 | 36 |
| heuristic | 48 | 12 | 42 | 34 | 70 | 44 | 48 | 34 |
| uniform | 27 | 4 | 15 | 10 | 42 | 38 | 23 | 10 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 512 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512 pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
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
- no per-deck ratings are published on this board: each matchup plays too few pairs of one deck pairing to rate a deck's games on their own; scores by deck are in the deck grid
- halt and truncation rates count the games halted or truncated right after the bot's own selection, over every game it played
- Ladder rating: the references (rungs) play the rungs nearest them in rating and each entrant plays the rungs named for it, so ratings connect through overlapping matchups. Unplayed head-to-head matchups are not measured; matchup-specific strengths can differ from the ranking. Compatible earlier evaluations are reused, so this is a dated model measurement. Elo and its interval can change when the combined results are refitted without replaying earlier games.
- Pending, no panel results yet: oh2-r2s1-b512-s4a-16k-k4
- off-mirror games only; the unit is the seat-swapped pair, which gives each bot both decks
- scores are the earlier deck's, over complete pairs; W/D/L counts every rated game
- strong pilots: games where both bots rank in the top half of the overall table
- deck ratings: anchored Bradley-Terry over decks, one virtual draw per pairing, centered so the average deck is Elo 1500
- predicted scores come from the deck ratings; residual_rms_e6 measures how far the matrix is from transitive
- robustness: rated games by own deck and by opponent deck, self-play excluded, mirrors included
