# Spellbench leaderboard: pauper-bo1

- Games: 3072 played, 3072 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | fmw120b-q3c-u0165248 pauper-v2.0.0 | 3.565903 | 1619.5 | [1561.1, 1681.0] | 384 | 292 | 0 | 92 | 0 |
| 2 | chains-a-c4-u1048576 pauper-v2.0.0 | 3.152469 | 1547.6 | [1491.6, 1608.0] | 384 | 260 | 0 | 124 | 0 |
| 3 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.569376 | 1446.3 | [1396.1, 1499.8] | 768 | 388 | 0 | 380 | 0 |
| 4 | oh2-r2s1-b512 pauper-v2.0.0 | 2.557843 | 1444.3 | [1397.3, 1493.6] | 896 | 483 | 0 | 413 | 0 |
| 5 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.295067 | 1398.7 | [1343.1, 1458.3] | 384 | 181 | 0 | 203 | 0 |
| 6 | g115 pauper-v2.0.0 | 2.101675 | 1365.1 | [1318.0, 1413.7] | 1024 | 475 | 0 | 549 | 0 |
| 7 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.638322 | 1284.6 | [1243.3, 1329.7] | 768 | 386 | 0 | 382 | 0 |
| 8 | c12 pauper-v2.0.0 | 1.411193 | 1245.1 | [1201.6, 1290.5] | 640 | 312 | 0 | 328 | 0 |
| 9 | heuristic 2.0.0 | 0.940520 | 1163.4 | [1120.1, 1206.0] | 512 | 214 | 0 | 298 | 0 |
| 10 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 81 | 0 | 303 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 128 | 65 | 0 | 63 | 0.5078 | [0.4297, 0.5859] | 1.0000 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 86 | 0 | 42 | 0.6719 | [0.5938, 0.7500] | 0.0001 |
| oh2-r2s1-b512 | g115 | 128 | 77 | 0 | 51 | 0.6016 | [0.5234, 0.6797] | 0.0241 |
| oh2-r2s1-b512 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 74 | 0 | 54 | 0.5781 | [0.5078, 0.6562] | 0.0755 |
| oh2-r2s1-b512 | chains-a-c4-u1048576 | 128 | 44 | 0 | 84 | 0.3438 | [0.2656, 0.4141] | 0.0003 |
| oh2-r2s1-b512 | c12 | 128 | 102 | 0 | 26 | 0.7969 | [0.7266, 0.8594] | 0.0000 |
| oh2-r2s1-b512 | fmw120b-q3c-u0165248 | 128 | 35 | 0 | 93 | 0.2734 | [0.2109, 0.3438] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 37 | 0 | 91 | 0.2891 | [0.2266, 0.3516] | 0.0000 |
| heuristic | g115 | 128 | 38 | 0 | 90 | 0.2969 | [0.2266, 0.3672] | 0.0000 |
| heuristic | uniform | 128 | 91 | 0 | 37 | 0.7109 | [0.6406, 0.7812] | 0.0000 |
| heuristic | c12 | 128 | 48 | 0 | 80 | 0.3750 | [0.3125, 0.4375] | 0.0009 |
| oh2-r2s1-b512-argmax | gorge-ar8 | 128 | 103 | 0 | 25 | 0.8047 | [0.7422, 0.8672] | 0.0000 |
| oh2-r2s1-b512-argmax | g115 | 128 | 79 | 0 | 49 | 0.6172 | [0.5469, 0.6875] | 0.0041 |
| oh2-r2s1-b512-argmax | oh2-r2s1-b512-s4a-16k-k4 | 128 | 69 | 0 | 59 | 0.5391 | [0.4531, 0.6172] | 0.4583 |
| oh2-r2s1-b512-argmax | chains-a-c4-u1048576 | 128 | 46 | 0 | 82 | 0.3594 | [0.2891, 0.4297] | 0.0009 |
| oh2-r2s1-b512-argmax | fmw120b-q3c-u0165248 | 128 | 28 | 0 | 100 | 0.2188 | [0.1484, 0.2891] | 0.0000 |
| gorge-ar8 | g115 | 128 | 48 | 0 | 80 | 0.3750 | [0.2891, 0.4609] | 0.0090 |
| gorge-ar8 | uniform | 128 | 112 | 0 | 16 | 0.8750 | [0.8203, 0.9297] | 0.0000 |
| gorge-ar8 | c12 | 128 | 68 | 0 | 60 | 0.5312 | [0.4531, 0.6172] | 0.5572 |
| g115 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 60 | 0 | 68 | 0.4688 | [0.3828, 0.5547] | 0.5716 |
| g115 | chains-a-c4-u1048576 | 128 | 34 | 0 | 94 | 0.2656 | [0.1953, 0.3438] | 0.0000 |
| g115 | c12 | 128 | 82 | 0 | 46 | 0.6406 | [0.5781, 0.7031] | 0.0003 |
| g115 | fmw120b-q3c-u0165248 | 128 | 29 | 0 | 99 | 0.2266 | [0.1562, 0.2969] | 0.0000 |
| uniform | c12 | 128 | 28 | 0 | 100 | 0.2188 | [0.1484, 0.2891] | 0.0000 |

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
| fmw120b-q3c-u0165248 pauper-v2.0.0 | 0.977723 | 1169.8 | 384 | 292 | 0 | 92 |
| chains-a-c4-u1048576 pauper-v2.0.0 | 0.564911 | 1098.1 | 384 | 260 | 0 | 124 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 768 | 397 | 0 | 371 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.077773 | 986.5 | 640 | 285 | 0 | 355 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | -0.290798 | 949.5 | 384 | 181 | 0 | 203 |
| g115 pauper-v2.0.0 | -0.451042 | 921.6 | 768 | 305 | 0 | 463 |
| c12 pauper-v2.0.0 | -1.166477 | 797.4 | 256 | 72 | 0 | 184 |

### tag: search

skipped: fewer_than_two_bots


## Deck grid

### Deck vs deck: all games

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 12 (96) | 41 (96) | 31 (96) | 67 (96) | 38 (96) | 46 (96) | 36 (96) |
| Rally | 88 (96) | - | 75 (96) | 70 (96) | 83 (96) | 77 (96) | 84 (96) | 88 (96) |
| Affinity | 59 (96) | 25 (96) | - | 41 (96) | 70 (96) | 55 (96) | 67 (96) | 45 (96) |
| Elves | 69 (96) | 30 (96) | 59 (96) | - | 83 (96) | 56 (96) | 74 (96) | 66 (96) |
| Spy | 33 (96) | 17 (96) | 30 (96) | 17 (96) | - | 30 (96) | 31 (96) | 22 (96) |
| Burn | 62 (96) | 23 (96) | 45 (96) | 44 (96) | 70 (96) | - | 52 (96) | 44 (96) |
| CawGates | 54 (96) | 16 (96) | 33 (96) | 26 (96) | 69 (96) | 48 (96) | - | 38 (96) |
| Faeries | 64 (96) | 12 (96) | 55 (96) | 34 (96) | 78 (96) | 56 (96) | 62 (96) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1722.2 | [1696.5, 1750.9] |
| Elves | 1581.7 | [1559.9, 1604.8] |
| Faeries | 1509.9 | [1487.2, 1531.8] |
| Affinity | 1508.9 | [1486.2, 1531.6] |
| Burn | 1488.4 | [1465.1, 1509.0] |
| CawGates | 1435.3 | [1414.0, 1457.4] |
| Wildfire | 1423.3 | [1401.4, 1444.7] |
| Spy | 1330.2 | [1305.6, 1352.4] |

Transitivity: observed scores differ from the deck ratings' predictions by 4.2 points RMS.

### Deck vs deck: strong pilots (top half of the table)

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 14 (28) | 46 (28) | 21 (28) | 68 (28) | 32 (28) | 32 (28) | 32 (28) |
| Rally | 86 (28) | - | 82 (28) | 68 (28) | 71 (28) | 79 (28) | 79 (28) | 82 (28) |
| Affinity | 54 (28) | 18 (28) | - | 46 (28) | 43 (28) | 64 (28) | 68 (28) | 43 (28) |
| Elves | 79 (28) | 32 (28) | 54 (28) | - | 86 (28) | 54 (28) | 71 (28) | 89 (28) |
| Spy | 32 (28) | 29 (28) | 57 (28) | 14 (28) | - | 25 (28) | 21 (28) | 32 (28) |
| Burn | 68 (28) | 21 (28) | 36 (28) | 46 (28) | 75 (28) | - | 46 (28) | 46 (28) |
| CawGates | 68 (28) | 21 (28) | 32 (28) | 29 (28) | 79 (28) | 54 (28) | - | 61 (28) |
| Faeries | 68 (28) | 18 (28) | 57 (28) | 11 (28) | 68 (28) | 54 (28) | 39 (28) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1690.9 | [1649.2, 1739.4] |
| Elves | 1604.3 | [1566.7, 1644.8] |
| CawGates | 1492.0 | [1455.9, 1527.8] |
| Burn | 1488.8 | [1445.9, 1530.4] |
| Affinity | 1485.6 | [1450.8, 1521.8] |
| Faeries | 1466.2 | [1425.7, 1505.0] |
| Wildfire | 1403.5 | [1363.7, 1440.9] |
| Spy | 1368.8 | [1328.4, 1406.3] |

Transitivity: observed scores differ from the deck ratings' predictions by 10.4 points RMS.

### Robustness: score by own deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fmw120b-q3c-u0165248 | 69 | 90 | 71 | 88 | 65 | 71 | 77 | 79 |
| chains-a-c4-u1048576 | 54 | 90 | 73 | 77 | 46 | 73 | 67 | 62 |
| oh2-r2s1-b512-argmax | 42 | 78 | 41 | 60 | 30 | 56 | 47 | 50 |
| oh2-r2s1-b512 | 46 | 79 | 52 | 63 | 33 | 56 | 55 | 46 |
| oh2-r2s1-b512-s4a-16k-k4 | 38 | 62 | 46 | 67 | 46 | 31 | 46 | 42 |
| g115 | 41 | 78 | 55 | 62 | 18 | 59 | 12 | 46 |
| gorge-ar8 | 41 | 85 | 54 | 56 | 24 | 38 | 47 | 57 |
| c12 | 39 | 84 | 55 | 54 | 22 | 51 | 34 | 51 |
| heuristic | 22 | 64 | 52 | 56 | 20 | 20 | 42 | 58 |
| uniform | 6 | 42 | 17 | 31 | 6 | 15 | 17 | 35 |

### Robustness: score by opponent's deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fmw120b-q3c-u0165248 | 92 | 52 | 77 | 67 | 92 | 77 | 88 | 65 |
| chains-a-c4-u1048576 | 75 | 38 | 67 | 54 | 88 | 69 | 75 | 77 |
| oh2-r2s1-b512-argmax | 64 | 20 | 48 | 36 | 72 | 53 | 55 | 56 |
| oh2-r2s1-b512 | 67 | 22 | 52 | 43 | 70 | 56 | 66 | 55 |
| oh2-r2s1-b512-s4a-16k-k4 | 52 | 17 | 50 | 19 | 81 | 40 | 60 | 58 |
| g115 | 54 | 19 | 48 | 41 | 64 | 47 | 52 | 46 |
| gorge-ar8 | 61 | 28 | 49 | 42 | 71 | 46 | 58 | 47 |
| c12 | 59 | 28 | 42 | 38 | 75 | 51 | 61 | 36 |
| heuristic | 48 | 12 | 42 | 34 | 70 | 44 | 48 | 34 |
| uniform | 27 | 4 | 15 | 10 | 42 | 38 | 23 | 10 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| fmw120b-q3c-u0165248 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| chains-a-c4-u1048576 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 1024 | 0 | 0.000 | 0 | 0.000 |
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
- Evaluation versions by block: pauper-ladder-v3.1.0 (extensions: x_kernel_flat_v4, x_public_history_v1, x_kernel_infoset_v1) for the 3 blocks of oh2-r2s1-b512-s4a-16k-k4; pauper-ladder-v3.0.0 (extensions: x_kernel_flat_v4, x_public_history_v1) for the other 21 blocks.
- off-mirror games only; the unit is the seat-swapped pair, which gives each bot both decks
- scores are the earlier deck's, over complete pairs; W/D/L counts every rated game
- strong pilots: games where both bots rank in the top half of the overall table
- deck ratings: anchored Bradley-Terry over decks, one virtual draw per pairing, centered so the average deck is Elo 1500
- predicted scores come from the deck ratings; residual_rms_e6 measures how far the matrix is from transitive
- robustness: rated games by own deck and by opponent deck, self-play excluded, mirrors included
