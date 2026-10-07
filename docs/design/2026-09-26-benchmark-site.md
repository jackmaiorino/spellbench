# Benchmark site (sub-project A)

Status: approved 2026-09-26; implementation plan in `2026-09-26-benchmark-site-plan.md`.

## Goal

A clean public leaderboard the maintainer can post in the MTGRL Discord with the
message "integrate with this so you can get your model on the benchmark".
Viewers open a link and install nothing. Every number on the site traces
back to a committed match ledger that anyone can re-check with
`spellbench validate`.

This is the first of four sub-projects:

| # | Sub-project | Depends on |
|---|---|---|
| A | This spec: benchmark definitions, rotating-deck schedules, Hero metric, site generator, Pages deploy | nothing |
| B | Protocol v2 board view (what a bot can see), emitted by the mtg-kernel bridge | nothing |
| C | g115 on the board: the bridge emits its v7 features; a bot process scores them with the native checkpoint | Codex's features branch |
| D | Join kit: integration guide page, prebuilt bridge binaries, GitHub issue form for submissions | A and B |

Decisions already made: several benchmarks (one per format or goal) under
an overall Hero chart; the Hero metric is Elo above the random bot; each
benchmark rotates a deck pool with the same deck in both seats; hosting is
GitHub Pages from this repo, previewed privately until the repo goes public.

## 1. Benchmarks and results

A benchmark is a folder: `benchmarks/<id>/benchmark.json` plus
`benchmarks/<id>/runs/<YYYY-MM-DD>[-N]/`, where each run is an ordinary
published tournament directory (manifest, config, registry, ledger,
leaderboard).

`benchmark.json` (schema `spellbench-benchmark/v1`, strict: unknown fields
are errors) holds:

- `id`, `title`, `summary` (one sentence for the card), `format`;
- `engine`: `{name, command, timeout_ms}`;
- `deck_pool` (catalog ids) and `pairs_per_deck`;
- `base_seed`, `choose_timeout_ms`, `startup_timeout_ms`,
  `bootstrap_replicates`, `workers`;
- `bots`: arena bot entries (as in a tournament config) plus a `display`
  object per bot: `{label, author, description, url}` (`url` may be null).

Rules:

- The roster must include the builtin `uniform` bot; the benchmark anchors
  its ratings on it. Its display label is "random".
- Self-play is off: a bot is never scheduled against itself.
- Each run replays the whole round-robin. There is no incremental merging
  and no run history on the site: the site shows each benchmark's latest
  run (the latest date, then the highest `-N` suffix).
- Machine-specific paths never enter the repo. The engine command, bot
  commands, and bot checkpoint paths in `benchmark.json` may contain
  `${NAME}` placeholders, resolved at run time
  from environment variables or the git-ignored `benchmarks/local.json`
  (`{"NAME": "value"}`; the environment wins). An unresolved placeholder is
  an error before any process starts. The run's recorded `config.json`
  keeps the placeholders, and bot ids hash the unresolved command (a
  checkpoint still contributes the hash of its bytes), so a run's artifacts
  are the same on every machine and publish no local paths.
- `diagnostics.jsonl` (raw peer stderr) is git-ignored under `benchmarks/`.

Launch benchmark `pauper-kernel`: engine `${MTG_KERNEL_BRIDGE}` (the
mtg-kernel `agent_bridge_v1` binary), the 8 decks the bridge serves
(Wildfire, Rally, Affinity, Elves, Spy, Burn, CawGates, Faeries),
`pairs_per_deck` 4, bots `uniform`, `heuristic`, `first`, and g115 once
sub-project C lands.

## 2. Arena changes

- **Deck pool.** A tournament config may give `deck_pool` (a nonempty list
  of decks) instead of the fixed `decks` pair; giving both is an error.
  With a pool, pair `p` of every matchup plays `deck_pool[p % len(pool)]`
  in both seats, and `pairs_per_matchup` must be a multiple of the pool
  size, so every matchup plays every deck equally. Game seeds and seat
  swapping are unchanged. The benchmark runner sets
  `pairs_per_matchup = pairs_per_deck * len(deck_pool)`.
- **Preflight** resets the engine once per deck in the pool.
- **Self-play switch.** `include_self_play` (default `true`, so existing
  configs are unchanged) removes `(i, i)` matchups from the schedule when
  `false`. With it off, a config needs at least two bots.
- **Recorded versus executed commands.** `run_tournament` takes an optional
  command resolver: the recorded config, registry and bot ids use the
  commands as written; processes start with the resolved commands.
- **Deck slices.** `leaderboard.json` gains `slices.deck`: for each deck,
  the ratings recomputed from that deck's games alone, with the same
  anchor, the same prior, complete pairs only, and paired-bootstrap 95%
  intervals (stats seeds derived per deck from the base seed). The
  existing training-style `subratings` block is unchanged.

## 3. Hero metric

For bot `i` in benchmark `b`, `margin(i, b)` is its Elo minus the random
bot's Elo in `b` (random is the anchor, so this is its Elo display minus
1000), with the interval taken from `b`'s leaderboard. The Hero score is
the mean of `margin(i, b)` over the benchmarks `i` entered; bots match
across benchmarks by bot `name`.

- One benchmark entered: the Hero interval is that benchmark's interval.
- Several: per-benchmark standard errors come from interval half-widths
  divided by 1.96 and combine as `sqrt(sum(se^2)) / n`; the interval is the
  score plus or minus 1.96 of that, and the site labels it approximate.
- Rank by Hero score, then by bot name. The random bot is shown as the
  reference row at 0.
- A benchmark whose latest run is not anchored on `uniform` is left out of
  the Hero chart, with a warning from the build.
- The page states that the Hero score compares skill above random across
  formats, not head-to-head results.

## 4. Pages

Four page types, all static:

- **Home**: header and navigation; the Hero chart (horizontal bars with
  interval whiskers, a chip per benchmark with that margin); a "Put your
  model on the benchmark" call to action linking to Join; benchmark cards
  (title, engine, deck count, bots, games, run date), including dashed
  "Proposed" cards for FDN Limited and Standard 2022-25 ("needs an
  engine"), listed in a small `benchmarks/proposed.json`.
- **Benchmark page** (one per benchmark): engine identity; the leaderboard
  (rank, bot label with training-style tag, author, Elo, 95% interval bar,
  W-L, games, forfeits); tabs Overall, By deck (the deck slices), and By
  training style (the overall rows filtered by tag); a matchup grid (each
  bot's score against each other bot); a download link for the run's
  ledger and manifest and the `validate` result.
- **Join**: placeholder until sub-project D (what the protocol is, links to
  the spec and README).
- **Method**: plain-language rating method: seat-swapped pairs sharing a
  seed, forfeits rated as losses, halts and caps excluded, the virtual-draw
  prior, complete pairs, the Hero definition, and how to re-check a run.

Implementation: plain HTML with inline SVG charts and a few lines of
inline script for the tabs; no external libraries or fonts; colors as CSS
variables with light and dark themes; readable at phone width. Every
string from a benchmark file or ledger is HTML-escaped. Output is
deterministic: no build timestamps, sorted everything, so an unchanged
input rebuilds byte for byte.

## 5. Commands, deploy, tests

- `spellbench bench run benchmarks/<id> [--date YYYY-MM-DD]`: resolve
  placeholders, preflight, run, write `runs/<date>[-N]/`, validate.
- `spellbench site <benchmarks_dir> <out_dir>`: validate each benchmark's
  latest run (refusing to build if one fails), compute the Hero table,
  render the pages, and copy each run's ledger and manifest for download.
- `.github/workflows/pages.yml`: on push to `main`, sync with the pinned uv,
  run `spellbench site benchmarks site`, and deploy with the Pages actions
  (pinned by SHA like `ci.yml`). Pages on a free plan needs a public repo,
  so the workflow ships now and goes live when the repo is made public.
  Until then the preview is a private page link built from the same
  output.

Tests:

- Hero metric against hand-computed values (one and two benchmarks,
  interval combination, exclusion of an unanchored benchmark).
- Deck rotation: each deck exactly `pairs_per_deck` times per matchup,
  identical schedule across runs; `pairs_per_matchup` not a multiple of the
  pool size is rejected; `decks` with `deck_pool` is rejected.
- Self-play off: no `(i, i)` matchups; a one-bot config is rejected.
- Deck slices equal a direct recomputation from that deck's rows.
- Placeholders: unresolved names fail before any process starts; the
  recorded config and bot ids keep the placeholders.
- Site render from fixture tournaments: every internal link resolves, the
  numbers in the HTML match `leaderboard.json`, escaping holds for a hostile
  label, and two builds are byte-identical.
- The site build refuses a tampered run.

## Out of scope

Run history or seasons, incremental runs, a submission UI, bot process
reuse, the g115 bot (C), the board view (B), and the Join content (D).
