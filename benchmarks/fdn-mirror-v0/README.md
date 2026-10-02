# fdn-mirror-v0

Sixteen Foundations (FDN) draft decks on the XMage engine, played as mirrors: both seats play the same list, and
every matchup plays each deck in both seats. Builtin bots only: `uniform` (the rating anchor), `heuristic`, `first`.

- **Decks.** Drawn from DraftZero's 40 committed eval-split sample decks (`assets/sample/eval.txt`, DraftZero
  commit `bf5750cf`) with `random.Random("spellbench-fdn-mirror-v0").sample(sorted(eval), 16)`. Main decks only,
  names as Oracle names in NFC. They are catalog decks of the engine
  (`engines/xmage/overlay/src/main/resources/mage/player/spellbench/catalog.json`).
- **Attribution.** 17lands FDN Premier Draft public data (https://www.17lands.com/public_datasets), CC BY 4.0, via
  DraftZero (https://github.com/danieljbrooks/draft-zero, MIT). The benchmark page must credit 17lands and
  DraftZero.
- **Fairness.** Validator only: P's live validator checks every decision, and the engine declares no probe.
- **Schedule.** 3 matchups (no self-play) x 64 seat-swapped pairs (4 per deck) = 384 games per run.
- **Clock profile** (frozen): 120 s per decision, 3,600 s bank, 2 s increment, 300 s startup and game start,
  120 s engine step.
- **Open (design D9).** These 40 decks are the ones DraftZero's experiment 1 evaluated on. That is fine for rating
  builtins and XMage heuristics; `fdn-limited-v1` should draw from the full eval split and avoid them if DraftZero
  asks.

Runbook and cost: `engines/xmage/tests/x5m/README.md`.
