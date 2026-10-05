# Adding entrants without replaying existing LLM evaluations

Declare a fixed panel in a protocol v2 `benchmark.json`:

```json
"opponent_panel": ["uniform", "heuristic", "local-model"],
"evaluation_version": "my-panel-v1"
```

These names must already occur in `bots`. Use local reference agents with varied strengths and playing styles, and freeze the panel's versions, checkpoints and settings. The roster must include `uniform` as its rating anchor. It may be a reference or a separate calibration entrant that plays the references without adding uniform matchups for other entrants. A panel consisting only of weak bots can saturate and distinguish strong entrants poorly. Entrants play every reference, and references play one another. Entrants do not need to meet other entrants.

Before the first panel evaluation, and after adding or updating an entrant:

```text
uv run spellbench bench prepare benchmarks/my-benchmark
```

Preparation hashes the engine, builtin implementations and shared transport, subprocess programs, checkpoint files, and file arguments. It writes their fingerprints and the missing `evaluation_targets` to the definition. It starts no engine, bot or inference process. Review and commit the definition, then use the existing `bench commit` and guarded `bench run --run NAME --proof REF` workflow. The run roster contains the references, selected targets and rating anchor; its schedule includes only missing matchup blocks. Unchanged LLM entrants are not started, including in preflight and throughput qualification. An empty target list needs no run or commitment.

A successful CLI panel run composes its snapshot automatically. Refit saved results explicitly with:

```text
uv run spellbench bench compose benchmarks/my-benchmark
uv run spellbench validate benchmarks/my-benchmark/snapshots/2026-10-02
uv run spellbench site benchmarks site
```

Composing and publishing play zero games. Snapshots keep references to complete source matchup blocks, including halts and truncations. Both seat slots stay together; duplicate blocks cannot be counted twice. Selection uses the latest compatible completed source for each required matchup, independent of its outcomes. Snapshots do not overwrite the original runs or secrets.

Changing an entrant's version, seed, command or declared input bytes requires only that entrant's new evaluation. Changing the engine, deck pool, information rules, clocks, caps, resources, evaluation version or frozen reference inputs invalidates the affected panel. Advance `evaluation_version` for changes in arena behavior or other game-affecting inputs outside the declared files.

For configuration or dependencies not given as standalone file arguments, declare files to fingerprint and pin:

```json
"evaluation_inputs": ["${LLM_POLICY_JSON}", "${PROMPT_TEMPLATE}"]
```

This is an optional field on a bot. Use it for a hosted LLM's provider configuration, model snapshot identifier, prompt, inference settings, context policy and relevant adapter dependencies. Use the benchmark's optional `evaluation_engine_inputs` for external engine data or configuration. Keep credentials outside these game-policy inputs. A provider alias can change remotely without a local file change; use a fixed model snapshot where available and publish the evaluation date. Cached results describe that evaluated version, not a newly sampled live service.

Only complete, validated, fingerprinted protocol v2 runs with matching conditions can contribute. Older unversioned evaluations remain published as historical measurements; they cannot automatically be promoted into the new panel. Establish the panel once, then reuse it for future additions. Preparation refuses to change a definition with an unresolved committed run.

For offline development, `bench prepare --unrated`, `bench run --unrated` and `bench compose --unrated` permit previews. They remain unrated and never replace a rated snapshot on the public board. A rated snapshot requires rated source runs throughout; composition does not qualify an unrated source.

The benchmark page, Hero chips and Models page label reference-panel ratings. The page lists the source evaluation dates and explains that comparisons through shared opponents do not measure unplayed head-to-head matchups, that matchup-specific strengths can differ, and that Elo and uncertainty can move when the combined evidence is refitted without replaying earlier games. Selected direct matches can still be evaluated in a separate round-robin benchmark.
