# Spellbench leaderboard: pauper-bo1

- Games: 192 played, 192 rated (forfeits rated as losses: 42; unrated: truncated 0, halted 0)
- Anchor: uniform 2.0.0, fixed at 0.000000 log units (Elo display 1000.0)
- Status: fit_failed (reference_id has no games)
- Rating: anchored Bradley-Terry MM, draws count half, 1 virtual draw(s) per matchup; CI95: paired bootstrap over seat-swapped pairs (2000 replicates, 0 failed, status not_applicable)

| Rank | Bot | Rating | Elo | CI95 (Elo) | Games | W | D | L | Forfeit L |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| - | llm-gpt-6-luna 0.1.0 | - | - | - | 192 | 75 | 0 | 117 | 42 |
| - | g115 pauper-v2.0.0 | - | - | - | 64 | 48 | 0 | 16 | 0 |
| - | uniform 2.0.0 | - | - | - | 0 | 0 | 0 | 0 | 0 |
| - | c12 pauper-v2.0.0 | - | - | - | 64 | 34 | 0 | 30 | 0 |
| - | a48 pauper-v2.0.0 | - | - | - | 64 | 35 | 0 | 29 | 0 |

## Matchups (W/D/L from bot A's perspective, rated games)

| Bot A | Bot B | Games | A wins | Draws | B wins | A score | A score CI95 | Sign test p |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| llm-gpt-6-luna | g115 | 64 | 16 | 0 | 48 | 0.2500 | [0.1562, 0.3594] | 0.0004 |
| llm-gpt-6-luna | c12 | 64 | 30 | 0 | 34 | 0.4688 | [0.3281, 0.6094] | 0.8238 |
| llm-gpt-6-luna | a48 | 64 | 29 | 0 | 35 | 0.4531 | [0.3438, 0.5625] | 0.5811 |

## Subratings by training-style tag

### tag: baseline

skipped: fewer_than_two_bots

### tag: hosted-llm

skipped: fewer_than_two_bots

### tag: reinforcement-learning

skipped: no_rated_games

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
| llm-gpt-6-luna 0.1.0 | 192 | 0 | 0.000 | 0 | 0.000 |
| g115 pauper-v2.0.0 | 64 | 0 | 0.000 | 0 | 0.000 |
| uniform 2.0.0 | 0 | 0 | - | 0 | - |
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
