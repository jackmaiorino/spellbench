# Spellbench leaderboard: pauper-bo1

- Games: 384 played, 384 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | oh2-r2s1-b512 pauper-v2.0.0 | - | - | - | 128 | 35 | 0 | 93 | 0 |
| - | heuristic 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | oh2-r2s1-b512-argmax pauper-v2.0.0 | - | - | - | 128 | 28 | 0 | 100 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 128 | 29 | 0 | 99 | 0 |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | fmw120b-q3c-u0165248 pauper-v2.0.0 | - | - | - | 384 | 292 | 0 | 92 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | fmw120b-q3c-u0165248 | 128 | 35 | 0 | 93 | 0.2734 | [0.2031, 0.3438] | 0.0000 |
| oh2-r2s1-b512-argmax | fmw120b-q3c-u0165248 | 128 | 28 | 0 | 100 | 0.2188 | [0.1484, 0.2969] | 0.0000 |
| g115 | fmw120b-q3c-u0165248 | 128 | 29 | 0 | 99 | 0.2266 | [0.1562, 0.3047] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fmw120b-q3c-u0165248 pauper-v2.0.0 | 0.968429 | 1168.2 | 384 | 292 | 0 | 92 |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 35 | 0 | 93 |
| g115 pauper-v2.0.0 | -0.247339 | 957.0 | 128 | 29 | 0 | 99 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.291825 | 949.3 | 128 | 28 | 0 | 100 |


## Deck grid

### Deck vs deck: all games

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 25 (12) | 67 (12) | 25 (12) | 50 (12) | 25 (12) | 50 (12) | 17 (12) |
| Rally | 75 (12) | - | 75 (12) | 58 (12) | 58 (12) | 83 (12) | 75 (12) | 75 (12) |
| Affinity | 33 (12) | 25 (12) | - | 42 (12) | 58 (12) | 67 (12) | 67 (12) | 33 (12) |
| Elves | 75 (12) | 42 (12) | 58 (12) | - | 83 (12) | 58 (12) | 50 (12) | 67 (12) |
| Spy | 50 (12) | 42 (12) | 42 (12) | 17 (12) | - | 25 (12) | 42 (12) | 25 (12) |
| Burn | 75 (12) | 17 (12) | 33 (12) | 42 (12) | 75 (12) | - | 50 (12) | 33 (12) |
| CawGates | 50 (12) | 25 (12) | 33 (12) | 50 (12) | 58 (12) | 50 (12) | - | 42 (12) |
| Faeries | 83 (12) | 25 (12) | 67 (12) | 33 (12) | 75 (12) | 67 (12) | 58 (12) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Rally | 1630.2 | [1577.1, 1691.8] |
| Elves | 1570.1 | [1520.3, 1626.0] |
| Faeries | 1548.6 | [1505.3, 1598.5] |
| Affinity | 1478.7 | [1434.7, 1520.9] |
| Burn | 1478.7 | [1433.1, 1521.0] |
| CawGates | 1464.7 | [1420.9, 1506.5] |
| Wildfire | 1421.9 | [1379.1, 1458.4] |
| Spy | 1407.3 | [1365.1, 1443.6] |

Transitivity: observed scores differ from the deck ratings' predictions by 11.1 points RMS.

### Deck vs deck: strong pilots (top half of the table)

- Status: skipped (fewer than four rated bots)

### Robustness: score by own deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 | 19 | 50 | 31 | 38 | 6 | 19 | 19 | 38 |
| oh2-r2s1-b512-argmax | 0 | 38 | 12 | 38 | 12 | 19 | 19 | 38 |
| g115 | 6 | 56 | 25 | 25 | 6 | 31 | 0 | 31 |
| fmw120b-q3c-u0165248 | 69 | 90 | 71 | 88 | 65 | 71 | 77 | 79 |

### Robustness: score by opponent's deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 | 56 | 12 | 38 | 19 | 19 | 38 | 31 | 6 |
| oh2-r2s1-b512-argmax | 12 | 6 | 19 | 12 | 44 | 25 | 19 | 38 |
| g115 | 25 | 12 | 31 | 6 | 44 | 25 | 19 | 19 |
| fmw120b-q3c-u0165248 | 92 | 52 | 77 | 67 | 92 | 77 | 88 | 65 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 0 | 0 | - | 0 | - |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| g115 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
| c12 pauper-v2.0.0 | 0 | 0 | - | 0 | - |
| fmw120b-q3c-u0165248 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |

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
- off-mirror games only; the unit is the seat-swapped pair, which gives each bot both decks
- scores are the earlier deck's, over complete pairs; W/D/L counts every rated game
- strong pilots: games where both bots rank in the top half of the overall table
- deck ratings: anchored Bradley-Terry over decks, one virtual draw per pairing, centered so the average deck is Elo 1500
- predicted scores come from the deck ratings; residual_rms_e6 measures how far the matrix is from transitive
- robustness: rated games by own deck and by opponent deck, self-play excluded, mirrors included
