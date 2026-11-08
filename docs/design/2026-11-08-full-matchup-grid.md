# Full matchup grid: all 36 deck pairings (design)

Status: proposal, 2026-11-08. Prompted by inkling_6 on the MTGRL Discord: expand the
Pauper boards from deck mirrors to every pairing in the 8-deck pool, and rate the decks.

## Today

Every board plays mirrors only. `TournamentConfig` gives pair `p` the deck
`deck_pool[p % len(deck_pool)]` in both seats, and the ladder run 2026-11-01 confirms
it: 1920 of 1920 games are mirrors. Per bot matchup the ladder plays 8 decks x 8
seat-swapped pairs = 128 games. Bot ratings are clean, but the board says nothing
about deck strength or about how a bot copes with an opponent on another deck.

## Schedule: deck-swapped blocks

A new pool mode, `"deck_schedule": "all-pairs"` (default `"mirror"`, so existing
boards and committed runs are unchanged). For bots A and B, each unordered deck
pairing gets one block:

- mirror X/X: 2 games (A:X vs B:X, both seat orders), as today;
- off-mirror X/Y: 4 games (A:X vs B:Y and A:Y vs B:X, each in both seat orders).

One cycle is 8 x 2 + 28 x 4 = **128 games per bot matchup, the ladder's current
budget**. Because every block gives each bot both decks and both seats, deck and
seat effects cancel exactly from the bot comparison (duplicate-bridge style), so
bot ratings stay unbiased with the existing Bradley-Terry fit and no model change.
Precision should be close to today's; lopsided deck matchups carry a little less
information per game, which the first run will measure. pauper-kernel-v2 plays 64
games per matchup and needs a full cycle (2x) to cover the grid.

## Ratings

One model covers all games:

    logit P(A on X beats B on Y) = (r_A - r_B) + M[X,Y] + seat

- `r`: bot ratings, the headline, fitted as today (the block design makes them
  orthogonal to `M`).
- `M`: an antisymmetric 8x8 matchup matrix (`M[X,Y] = -M[Y,X]`, mirrors 0). This is
  the "full 8x8": each cell shown as deck X's win rate against Y with a bootstrap
  CI, net of pilot skill.
- Deck Elo: the best transitive summary `M[X,Y] ~ d_X - d_Y`, on the usual Elo scale
  (mean deck 1500). Real matchups are not transitive (rock, paper, scissors), so the
  site shows the residual alongside, and the matrix stays the primary view.
- Robustness per bot: score by own deck (8 rows) and by opponent deck (8 columns),
  each pooled over opponents. Full per-bot 8x8 cells would hold about 2 games per
  opponent each, too few to show as numbers.

Deck strength depends on pilot skill (games involving the random bot measure decks
under random play). The matrix is reported twice: all games, and games between the
top half of the board.

## Precision (ladder, one cycle)

15 matchups x 4 games = 60 games per off-mirror cell pooled over all bots: CI95 about
+/-12 pp. Two cycles give about +/-9 pp. Today's per-pairing deck slices would
become 36 thin slices; they are replaced by 8 per-deck slices plus the matrix.

## Implementation

1. Config: `deck_schedule` on benchmark and tournament configs; `preflight_deck_pairs`
   returns all 36 pairings in all-pairs mode.
2. Schedule: block order within a matchup is deterministic (mirrors first, then
   off-mirror pairings in `combinations` order); `game_id` and seeds unchanged in kind.
3. Bootstrap: resample whole blocks (2 or 4 games) instead of seat pairs, so every
   replicate stays deck-balanced.
4. Leaderboard: `matchup_matrix`, `deck_ratings` and per-bot robustness sections;
   arena version bump (validate re-derives committed runs).
5. Site: an 8x8 heatmap with CIs and a per-bot robustness strip.
6. A new board `pauper-ladder-v3` (or a v2 rerun) in all-pairs mode; mirror boards stay
   as published.

Cost: one cycle on the ladder roster equals the 2026-11-01 run (about 12.5 core-seconds
per game, 1920 games). Compute placement follows COMPUTE-POLICY as usual.

## Feasibility and a caveat

- The engine already plays mixed decks: the v2 engine wrapper passes one catalog deck
  per seat, and the kernel session accepts mixed deck ids (its own tests run Burn vs
  Rally). Preflight will reset all 36 pairings before any game.
- The mtg-kernel training stack accepts only mirror pairings ("one exact mirror
  pairing; mixed decks are rejected"), so Archon 1-3 and Basilisk 1 never saw an
  off-mirror game. Their off-mirror play is out of distribution, which is exactly the
  robustness inkling_6 asks about; expect the board to move.
