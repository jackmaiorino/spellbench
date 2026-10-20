# Spellbench leaderboard: pauper-bo1

- Games: 192 played, 192 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts-custom 0.3.0+25b213ad6a3c | - | - | - | 192 | 34 | 0 | 158 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 64 | 59 | 0 | 5 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 64 | 48 | 0 | 16 | 0 |
| - | a48 pauper-v2.0.0 | - | - | - | 64 | 51 | 0 | 13 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| kit-mcts-custom | g115 | 64 | 5 | 0 | 59 | 0.0781 | [0.0156, 0.1406] | 0.0000 |
| kit-mcts-custom | c12 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3438] | 0.0001 |
| kit-mcts-custom | a48 | 64 | 13 | 0 | 51 | 0.2031 | [0.1250, 0.2812] | 0.0000 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: reinforcement-learning

skipped: no_rated_games

### tag: search

skipped: fewer_than_two_bots

## By deck

### Affinity

skipped: fit_failed (reference_id has no games)

### Burn

skipped: fit_failed (reference_id has no games)

### CawGates

skipped: fit_failed (reference_id has no games)

### Elves

skipped: fit_failed (reference_id has no games)

### Faeries

skipped: fit_failed (reference_id has no games)

### Rally

skipped: fit_failed (reference_id has no games)

### Spy

skipped: fit_failed (reference_id has no games)

### Wildfire

skipped: fit_failed (reference_id has no games)

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
| kit-mcts-custom 0.3.0+25b213ad6a3c | 192 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| c12 pauper-v2.0.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| a48 pauper-v2.0.0 | 64 | 0 | 0.000 | 0 | 0.000 |

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
