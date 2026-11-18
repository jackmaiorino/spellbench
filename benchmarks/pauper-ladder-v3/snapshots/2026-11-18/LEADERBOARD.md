# Spellbench leaderboard: pauper-bo1

- Games: 2688 played, 2688 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: ok
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status ok)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | chains-a-c4-u1048576 pauper-v2.0.0 | 3.166685 | 1550.1 | [1494.1, 1609.9] | 384 | 260 | 0 | 124 | 0 |
| 2 | oh2-r2s1-b512-argmax pauper-v2.0.0 | 2.615861 | 1454.4 | [1403.6, 1507.0] | 640 | 360 | 0 | 280 | 0 |
| 3 | oh2-r2s1-b512 pauper-v2.0.0 | 2.563350 | 1445.3 | [1397.7, 1498.7] | 768 | 448 | 0 | 320 | 0 |
| 4 | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 2.307486 | 1400.9 | [1345.8, 1462.4] | 384 | 181 | 0 | 203 | 0 |
| 5 | g115 pauper-v2.0.0 | 2.087253 | 1362.6 | [1314.3, 1412.2] | 896 | 446 | 0 | 450 | 0 |
| 6 | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 1.643288 | 1285.5 | [1244.8, 1330.2] | 768 | 386 | 0 | 382 | 0 |
| 7 | c12 pauper-v2.0.0 | 1.409751 | 1244.9 | [1200.0, 1292.8] | 640 | 312 | 0 | 328 | 0 |
| 8 | heuristic 2.0.0 | 0.938302 | 1163.0 | [1120.9, 1209.5] | 512 | 214 | 0 | 298 | 0 |
| 9 | uniform 2.0.0 | 0.000000 | 1000.0 | [1000.0, 1000.0] | 384 | 81 | 0 | 303 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-argmax | 128 | 65 | 0 | 63 | 0.5078 | [0.4297, 0.5859] | 1.0000 |
| oh2-r2s1-b512 | gorge-ar8 | 128 | 86 | 0 | 42 | 0.6719 | [0.5938, 0.7500] | 0.0001 |
| oh2-r2s1-b512 | g115 | 128 | 77 | 0 | 51 | 0.6016 | [0.5234, 0.6797] | 0.0241 |
| oh2-r2s1-b512 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 74 | 0 | 54 | 0.5781 | [0.5078, 0.6562] | 0.0755 |
| oh2-r2s1-b512 | chains-a-c4-u1048576 | 128 | 44 | 0 | 84 | 0.3438 | [0.2656, 0.4141] | 0.0003 |
| oh2-r2s1-b512 | c12 | 128 | 102 | 0 | 26 | 0.7969 | [0.7266, 0.8594] | 0.0000 |
| heuristic | gorge-ar8 | 128 | 37 | 0 | 91 | 0.2891 | [0.2344, 0.3516] | 0.0000 |
| heuristic | g115 | 128 | 38 | 0 | 90 | 0.2969 | [0.2266, 0.3672] | 0.0000 |
| heuristic | uniform | 128 | 91 | 0 | 37 | 0.7109 | [0.6406, 0.7812] | 0.0000 |
| heuristic | c12 | 128 | 48 | 0 | 80 | 0.3750 | [0.3047, 0.4375] | 0.0009 |
| oh2-r2s1-b512-argmax | gorge-ar8 | 128 | 103 | 0 | 25 | 0.8047 | [0.7422, 0.8594] | 0.0000 |
| oh2-r2s1-b512-argmax | g115 | 128 | 79 | 0 | 49 | 0.6172 | [0.5469, 0.6875] | 0.0041 |
| oh2-r2s1-b512-argmax | oh2-r2s1-b512-s4a-16k-k4 | 128 | 69 | 0 | 59 | 0.5391 | [0.4531, 0.6250] | 0.4583 |
| oh2-r2s1-b512-argmax | chains-a-c4-u1048576 | 128 | 46 | 0 | 82 | 0.3594 | [0.2891, 0.4375] | 0.0009 |
| gorge-ar8 | g115 | 128 | 48 | 0 | 80 | 0.3750 | [0.2969, 0.4531] | 0.0090 |
| gorge-ar8 | uniform | 128 | 112 | 0 | 16 | 0.8750 | [0.8203, 0.9297] | 0.0000 |
| gorge-ar8 | c12 | 128 | 68 | 0 | 60 | 0.5312 | [0.4531, 0.6094] | 0.5572 |
| g115 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 60 | 0 | 68 | 0.4688 | [0.3906, 0.5547] | 0.5716 |
| g115 | chains-a-c4-u1048576 | 128 | 34 | 0 | 94 | 0.2656 | [0.1953, 0.3359] | 0.0000 |
| g115 | c12 | 128 | 82 | 0 | 46 | 0.6406 | [0.5781, 0.7031] | 0.0003 |
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
| chains-a-c4-u1048576 pauper-v2.0.0 | 0.569350 | 1098.9 | 384 | 260 | 0 | 124 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 640 | 362 | 0 | 278 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.043571 | 992.4 | 512 | 257 | 0 | 255 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | -0.287813 | 950.0 | 384 | 181 | 0 | 203 |
| g115 pauper-v2.0.0 | -0.476159 | 917.3 | 640 | 276 | 0 | 364 |
| c12 pauper-v2.0.0 | -1.180304 | 795.0 | 256 | 72 | 0 | 184 |

### tag: search

skipped: fewer_than_two_bots


## Deck grid

### Deck vs deck: all games

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 11 (84) | 37 (84) | 32 (84) | 69 (84) | 39 (84) | 45 (84) | 39 (84) |
| Rally | 89 (84) | - | 75 (84) | 71 (84) | 87 (84) | 76 (84) | 86 (84) | 89 (84) |
| Affinity | 63 (84) | 25 (84) | - | 40 (84) | 71 (84) | 54 (84) | 67 (84) | 46 (84) |
| Elves | 68 (84) | 29 (84) | 60 (84) | - | 83 (84) | 56 (84) | 77 (84) | 65 (84) |
| Spy | 31 (84) | 13 (84) | 29 (84) | 17 (84) | - | 31 (84) | 30 (84) | 21 (84) |
| Burn | 61 (84) | 24 (84) | 46 (84) | 44 (84) | 69 (84) | - | 52 (84) | 45 (84) |
| CawGates | 55 (84) | 14 (84) | 33 (84) | 23 (84) | 70 (84) | 48 (84) | - | 37 (84) |
| Faeries | 61 (84) | 11 (84) | 54 (84) | 35 (84) | 79 (84) | 55 (84) | 63 (84) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1735.7 | [1707.6, 1767.3] |
| Elves | 1582.5 | [1560.3, 1605.8] |
| Affinity | 1513.6 | [1489.5, 1538.8] |
| Faeries | 1503.5 | [1480.2, 1528.0] |
| Burn | 1490.1 | [1465.1, 1515.4] |
| CawGates | 1431.2 | [1406.3, 1454.1] |
| Wildfire | 1424.3 | [1401.4, 1446.8] |
| Spy | 1319.1 | [1291.5, 1344.3] |

Transitivity: observed scores differ from the deck ratings' predictions by 4.2 points RMS.

### Deck vs deck: strong pilots (top half of the table)

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 8 (36) | 47 (36) | 28 (36) | 69 (36) | 36 (36) | 42 (36) | 47 (36) |
| Rally | 92 (36) | - | 78 (36) | 69 (36) | 81 (36) | 78 (36) | 89 (36) | 92 (36) |
| Affinity | 53 (36) | 22 (36) | - | 42 (36) | 64 (36) | 47 (36) | 72 (36) | 47 (36) |
| Elves | 72 (36) | 31 (36) | 58 (36) | - | 86 (36) | 53 (36) | 86 (36) | 78 (36) |
| Spy | 31 (36) | 19 (36) | 36 (36) | 14 (36) | - | 28 (36) | 28 (36) | 31 (36) |
| Burn | 64 (36) | 22 (36) | 53 (36) | 47 (36) | 72 (36) | - | 53 (36) | 56 (36) |
| CawGates | 58 (36) | 11 (36) | 28 (36) | 14 (36) | 72 (36) | 47 (36) | - | 53 (36) |
| Faeries | 53 (36) | 8 (36) | 53 (36) | 22 (36) | 69 (36) | 44 (36) | 47 (36) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1736.3 | [1695.9, 1781.6] |
| Elves | 1606.2 | [1571.3, 1643.9] |
| Burn | 1512.6 | [1472.5, 1552.4] |
| Affinity | 1494.5 | [1457.6, 1529.4] |
| Faeries | 1448.0 | [1410.3, 1485.2] |
| CawGates | 1434.9 | [1397.7, 1471.1] |
| Wildfire | 1429.6 | [1394.3, 1464.5] |
| Spy | 1337.9 | [1295.4, 1374.7] |

Transitivity: observed scores differ from the deck ratings' predictions by 6.8 points RMS.

### Robustness: score by own deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 | 54 | 90 | 73 | 77 | 46 | 73 | 67 | 62 |
| oh2-r2s1-b512-argmax | 50 | 86 | 46 | 65 | 34 | 64 | 52 | 52 |
| oh2-r2s1-b512 | 51 | 84 | 55 | 68 | 38 | 62 | 61 | 47 |
| oh2-r2s1-b512-s4a-16k-k4 | 38 | 62 | 46 | 67 | 46 | 31 | 46 | 42 |
| g115 | 46 | 81 | 59 | 68 | 20 | 63 | 13 | 48 |
| gorge-ar8 | 41 | 85 | 54 | 56 | 24 | 38 | 47 | 57 |
| c12 | 39 | 84 | 55 | 54 | 22 | 51 | 34 | 51 |
| heuristic | 22 | 64 | 52 | 56 | 20 | 20 | 42 | 58 |
| uniform | 6 | 42 | 17 | 31 | 6 | 15 | 17 | 35 |

### Robustness: score by opponent's deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 | 75 | 38 | 67 | 54 | 88 | 69 | 75 | 77 |
| oh2-r2s1-b512-argmax | 74 | 22 | 54 | 41 | 78 | 59 | 62 | 60 |
| oh2-r2s1-b512 | 69 | 24 | 54 | 47 | 78 | 59 | 72 | 64 |
| oh2-r2s1-b512-s4a-16k-k4 | 52 | 17 | 50 | 19 | 81 | 40 | 60 | 58 |
| g115 | 58 | 20 | 50 | 46 | 67 | 50 | 57 | 50 |
| gorge-ar8 | 61 | 28 | 49 | 42 | 71 | 46 | 58 | 47 |
| c12 | 59 | 28 | 42 | 38 | 75 | 51 | 61 | 36 |
| heuristic | 48 | 12 | 42 | 34 | 70 | 44 | 48 | 34 |
| uniform | 27 | 4 | 15 | 10 | 42 | 38 | 23 | 10 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| chains-a-c4-u1048576 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 640 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512 pauper-v2.0.0 | 768 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 896 | 0 | 0.000 | 0 | 0.000 |
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
- Evaluation versions by block: pauper-ladder-v3.1.0 (extensions: x_kernel_flat_v4, x_public_history_v1, x_kernel_infoset_v1) for the 3 blocks of oh2-r2s1-b512-s4a-16k-k4; pauper-ladder-v3.0.0 (extensions: x_kernel_flat_v4, x_public_history_v1) for the other 18 blocks.
- off-mirror games only; the unit is the seat-swapped pair, which gives each bot both decks
- scores are the earlier deck's, over complete pairs; W/D/L counts every rated game
- strong pilots: games where both bots rank in the top half of the overall table
- deck ratings: anchored Bradley-Terry over decks, one virtual draw per pairing, centered so the average deck is Elo 1500
- predicted scores come from the deck ratings; residual_rms_e6 measures how far the matrix is from transitive
- robustness: rated games by own deck and by opponent deck, self-play excluded, mirrors included
