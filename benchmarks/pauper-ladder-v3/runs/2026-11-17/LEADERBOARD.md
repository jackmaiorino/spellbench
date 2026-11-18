# Spellbench leaderboard: pauper-bo1

- Games: 384 played, 384 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | oh2-r2s1-b512 pauper-v2.0.0 | - | - | - | 128 | 74 | 0 | 54 | 0 |
| - | heuristic 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | oh2-r2s1-b512-argmax pauper-v2.0.0 | - | - | - | 128 | 69 | 0 | 59 | 0 |
| - | gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 128 | 60 | 0 | 68 | 0 |
| - | oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | - | - | - | 384 | 181 | 0 | 203 | 0 |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| oh2-r2s1-b512 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 74 | 0 | 54 | 0.5781 | [0.5000, 0.6484] | 0.0755 |
| oh2-r2s1-b512-argmax | oh2-r2s1-b512-s4a-16k-k4 | 128 | 69 | 0 | 59 | 0.5391 | [0.4609, 0.6250] | 0.4583 |
| g115 | oh2-r2s1-b512-s4a-16k-k4 | 128 | 60 | 0 | 68 | 0.4688 | [0.3906, 0.5469] | 0.5716 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

| Bot | Rating | Elo | Games | W | D | L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 0.000000 | 1000.0 | 128 | 74 | 0 | 54 |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | -0.157248 | 972.7 | 128 | 69 | 0 | 59 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | -0.312598 | 945.7 | 384 | 181 | 0 | 203 |
| g115 pauper-v2.0.0 | -0.436789 | 924.1 | 128 | 60 | 0 | 68 |

### tag: search

skipped: fewer_than_two_bots


## Deck grid

### Deck vs deck: all games

Row deck's score in percent over complete pairs (games in parentheses).

| Deck | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wildfire | - | 0 (12) | 50 (12) | 8 (12) | 75 (12) | 50 (12) | 50 (12) | 58 (12) |
| Rally | 100 (12) | - | 67 (12) | 67 (12) | 58 (12) | 75 (12) | 83 (12) | 83 (12) |
| Affinity | 50 (12) | 33 (12) | - | 42 (12) | 50 (12) | 50 (12) | 67 (12) | 42 (12) |
| Elves | 92 (12) | 33 (12) | 58 (12) | - | 92 (12) | 83 (12) | 92 (12) | 92 (12) |
| Spy | 25 (12) | 42 (12) | 50 (12) | 8 (12) | - | 25 (12) | 25 (12) | 33 (12) |
| Burn | 50 (12) | 25 (12) | 50 (12) | 17 (12) | 75 (12) | - | 50 (12) | 50 (12) |
| CawGates | 50 (12) | 17 (12) | 33 (12) | 8 (12) | 75 (12) | 50 (12) | - | 58 (12) |
| Faeries | 42 (12) | 17 (12) | 58 (12) | 8 (12) | 67 (12) | 50 (12) | 42 (12) | - |

| Deck | Elo | CI95 (Elo) |
| --- | ---: | --- |
| Elves | 1677.5 | [1624.4, 1735.2] |
| Rally | 1668.5 | [1609.5, 1744.9] |
| Affinity | 1482.9 | [1421.2, 1542.3] |
| Burn | 1468.4 | [1405.1, 1528.2] |
| Wildfire | 1446.5 | [1392.7, 1498.1] |
| CawGates | 1446.5 | [1385.2, 1505.1] |
| Faeries | 1439.1 | [1373.9, 1497.4] |
| Spy | 1370.6 | [1308.7, 1423.8] |

Transitivity: observed scores differ from the deck ratings' predictions by 11.6 points RMS.

### Deck vs deck: strong pilots (top half of the table)

- Status: skipped (fewer than four rated bots)

### Robustness: score by own deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 | 50 | 81 | 56 | 81 | 25 | 69 | 56 | 44 |
| oh2-r2s1-b512-argmax | 50 | 94 | 38 | 81 | 19 | 56 | 50 | 44 |
| g115 | 44 | 75 | 56 | 81 | 12 | 56 | 12 | 38 |
| oh2-r2s1-b512-s4a-16k-k4 | 38 | 62 | 46 | 67 | 46 | 31 | 46 | 42 |

### Robustness: score by opponent's deck

| Bot | Wildfire | Rally | Affinity | Elves | Spy | Burn | CawGates | Faeries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 | 69 | 44 | 56 | 31 | 50 | 75 | 69 | 69 |
| oh2-r2s1-b512-argmax | 75 | 38 | 44 | 38 | 62 | 69 | 50 | 56 |
| g115 | 44 | 31 | 62 | 31 | 50 | 62 | 44 | 50 |
| oh2-r2s1-b512-s4a-16k-k4 | 52 | 17 | 50 | 19 | 81 | 40 | 60 | 58 |

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| oh2-r2s1-b512 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| heuristic 2.0.0 | 0 | 0 | - | 0 | - |
| oh2-r2s1-b512-argmax pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| gorge-ar8 gorge-26257e0eda17/adapter-0.2.0/neutral-0.1.0 | 0 | 0 | - | 0 | - |
| g115 pauper-v2.0.0 | 128 | 0 | 0.000 | 0 | 0.000 |
| oh2-r2s1-b512-s4a-16k-k4 pauper-v2.0.0 | 384 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
| c12 pauper-v2.0.0 | 0 | 0 | - | 0 | - |

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
