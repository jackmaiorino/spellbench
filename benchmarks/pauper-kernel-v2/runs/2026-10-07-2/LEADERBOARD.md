# Spellbench leaderboard: pauper-bo1

- Games: 1 played, 1 rated (forfeits rated as losses: 0; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: no_rated_games
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | uniform 2.0.0 | - | - | - | 1 | 0 | 0 | 1 | 0 |
| - | kit-mad-1 0.3.0+4e575c6a49fc | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mad-k 0.3.0+a49c05ddab71 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | a48 pauper-v2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | kit-mcts 0.3.0+068718d79078 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | g115 pauper-v2.0.0 | - | - | - | 1 | 1 | 0 | 0 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| uniform | g115 | 1 | 0 | 0 | 1 | - | - | - |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: heuristic

skipped: no_rated_games

### tag: reinforcement-learning

skipped: no_rated_games

### tag: search

skipped: no_rated_games

## Halts and truncations after each bot's selection

| Bot | Games | Halts | Halt rate | Truncations | Truncation rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| uniform 2.0.0 | 1 | 0 | 0.000 | 0 | 0.000 |
| kit-mad-1 0.3.0+4e575c6a49fc | 0 | 0 | - | 0 | - |
| kit-mad-k 0.3.0+a49c05ddab71 | 0 | 0 | - | 0 | - |
| a48 pauper-v2.0.0 | 0 | 0 | - | 0 | - |
| c12 pauper-v2.0.0 | 0 | 0 | - | 0 | - |
| kit-mcts 0.3.0+068718d79078 | 0 | 0 | - | 0 | - |
| g115 pauper-v2.0.0 | 1 | 0 | 0.000 | 0 | 0.000 |

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
