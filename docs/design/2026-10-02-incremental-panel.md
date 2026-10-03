# Incremental reference-panel benchmarks

Adding an entrant must not replay unchanged LLM evaluations. A benchmark can declare a versioned `opponent_panel` of local reference bots. Each entrant plays every reference; references also play one another. Entrants need not play one another. The existing anchored Bradley-Terry fit and paired bootstrap operate on the observed comparisons.

`bench prepare` fingerprints declared bot inputs and sets `evaluation_targets` to entrants whose panel results are missing or incompatible. Its definition changes are reviewed and committed before the normal `bench commit` / guarded `bench run` workflow. No provider or bot process starts during preparation. An empty target list requires no launch.

`bench compose` publishes an immutable snapshot referencing the original validated run manifests and complete matchup blocks. It deterministically chooses the latest compatible complete run for each required matchup, preserves both seat slots and unrated endings, and never combines different engine, deck, rule, time-control, reference, or entrant identities. Rated snapshots use rated sources exclusively. Local previews explicitly allow unrated sources and never enter the public leaderboard. Original runs, commitments, secrets and game digests stay intact.

The site prefers the latest rated snapshot and validates all its sources and derived ratings. It labels reference-panel comparisons on benchmark, Hero and Models pages, identifies reused sources, and leaves unplayed head-to-head cells empty. The caveat explains indirect comparisons, matchup effects, dated model measurements, and ratings changing on refit without new games.

Verification covers adding a local entrant without starting the old LLM, changed inputs invalidating reuse, preserved game-pair identity across sources, deterministic recomposition, source tampering, compatibility and eligibility rejection, and site labels. Existing full round robins and committed historical artifacts remain supported. No live LLM calls or production benchmark runs are needed for engineering validation.
