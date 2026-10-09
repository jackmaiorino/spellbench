# DraftZero FDN graph network: port plan

Goal: add the DraftZero FDN graph network as a fair entrant on
`benchmarks/fdn-draftzero-v1`. The board has no commitment yet, so adding an
entrant is a definition edit. Engineering integration does not establish rated
admission or strength.

## Inputs

Release: `danbrooks/draftzero-fdn-gnn` at `a8351e8b43572fe262a2ae93c5dac745ea3a2e7b`.
Weights are CC BY 4.0 and code is MIT. All 9 files listed in `SHA256SUMS` verify;
`SHA256SUMS` itself is 715 bytes. The job root is `D:/e-scratch/spellbench-draftzero-gnn-20261008/inputs`.

| File | sha256 (prefix) | Bytes |
|---|---|---|
| model.safetensors | d5ee8323 | 53,671,100 |
| vocab.json | 9b8ecf25 | 22,672 |
| config.json | 6b48d3de | 2,646 |
| goldens.jsonl.gz | 46d5949b | 542,894 |
| graph_net.py | 8e27fc75 | 17,659 |
| gnn_release.py | c4cfa966 | 6,832 |

The model is 13.4M parameters: width 256, 2 local passes, 2 global layers, 1,932 leaf rows and 22 edge labels.

### Source pins

| Part | Pin |
|---|---|
| Encoder | `WillWroble/mage@e4afc9c7` (branch graph-encoder). It is vendored at `danieljbrooks/draft-zero@2a461518:java/mzbridge/src/org/draftzero/mzbridge/graph`. |
| Engine | `danieljbrooks/mage@48e49184` (v0.2-generalist) |
| Search | `danieljbrooks/draft-zero@2a461518:java/mzbridge/src/mage/player/ai`: `BenchSearch`, `BenchPlayer`, `GraphNet`, `GraphMCTSPlayer`, plus `org/draftzero/mzbridge/GraphRecord` |
| Network | MageZero `NetGraph` (`WillWroble/MageZero@de225045`) |

These pins relate to ours as follows:

- The kit's staged MageZero v0.2 sources at `WillWroble/mage@cb7e9c6f` are a direct ancestor of both forks.
  - The encoder branch is 13 commits ahead.
  - The engine fork is 3 commits ahead. Those commits only add the set-wide action vocabulary (`ActionEncoder`), `ComputerPlayerMCTS2` width and docs.
- The engine fork's XMage base is `magefree/mage@09a423ae` (2025-10-26). Our XMage pin `fd40ad5c` is 3,261 upstream commits newer.
- The leaves are XMage strings (rules text, decision text). Version drift therefore shows up as vocab misses, not as errors. The card's coverage baseline is more than 99.99% of leaf occurrences at priority, attack and target decisions, and 99.34% at blocks. The port measures the same quantity on our engine.

## What the network reads

- **Graph.** `StateEncoder.processState(game, decisionPlayer, type, text, options, source)` builds typed nodes keyed by engine UUIDs.
  - The node types are ROOT, PLAYER (named `PlayerA`/`PlayerB` relative to the agent), ZONE, STACK_OBJECT, PERMANENT, CARD and ABILITY.
  - Every typed node has LEAF children. A leaf id is `indexFor(hash64(name))`, and some leaves carry a numeric value.
  - Edges run child to parent. Their labels are hashed (`NONE`, `name`, `static`, `TARGET@i`, `attachment`, `blocker`, `defender`, `exiled`, `OptionPile`, `DecisionSource`, ...).
  - Arrays are emitted in sorted-UUID order. The network does not depend on node order: it has no positional input.
- **Hidden information.** The opponent's hand is hidden (`perfectInfo = false`). Its `HandSize` is still encoded.
- **Decisions and heads:**
  - Priority (`graph_type` 0) uses the priority head, read at ABILITY nodes. Pass is the fixed node `UUID(0, "Pass".hashCode())`. Copies of one card form one option, scored as the log-sum-exp of their nodes.
  - Targets and blocks (3) use the target head, read at CARD, PERMANENT, STACK_OBJECT and PLAYER nodes. Stop Choosing is a CARD node.
  - An attack is asked per creature as a target choice: "no" is Stop Choosing and "yes" is the defending player. The text is `attack with: {this} ?:Choose a target:<TargetDefender name>` and the attacker is the DecisionSource.
  - A block is a target choice with the blocker as the DecisionSource.
  - Other yes/no questions (5) use `use[no, yes]`.
  - Mulligans, trigger order and damage assignment have no head. MageZero's player decides them in the author's games, and mulligans were off there.
- **Value.** `tanh(value_x)` is the acting player's expected result, with the temperature folded in.

## Search in the author's games

The author's games use `BenchSearch.searchTree` on one sampled world (PIMC K=1). The tree is fresh at every decision, with no reuse and synchronous evaluation:

- Selection is PUCT with c = 1, and unvisited children are valued 0.
- Own priors are a softmax of option logits at temperature 1.5, plus 0.1 added to every option that is not Pass or a mana ability. They are not renormalized.
- Opponent nodes use uniform priors.
- Leaves take the value head, discounted 0.99 per ply. There is a single-child shortcut, and the most-visited option is played.
- The budget counts simulations, with a cap of `4 x budget + 200` iterations.
- The author's opponent decks were guessed from 17lands.

Measured results:

| Simulations | Won vs MageZero heuristic (100 sims) | Time a decision (3090 server, 30 games) |
|---|---|---|
| 0 (policy) | 44.7% of 103 | ~0.2 s |
| 100 | 62.5% of 104 | ~7 s |
| 300 | 69.2% of 104 | ~20 s |
| 1,000 | 69.3% of 101 | 40-65 s |

The card gives about 20 ms for one network call on one laptop CPU thread (batch 1, median 226 nodes). The confined probe below measures our figure.

## Clock fit

The board clock is a 3,600 s bank, a 2 s increment and a 600 s decision cap.

- At 100 simulations, about 7 s a decision fits a game of about 200 searched decisions with room to spare.
- 300 simulations (about 20 s each) would exhaust the bank on long games.

The planned entrant is therefore 100 simulations, a fixed count with no wall-time cutoff, so moves are deterministic. A 300-simulation variant waits until measured per-game decision counts and times show it fits. A policy-only entrant (0 simulations) is cheap and can be added beside it.

## Port

What is reused:

- The kit's staging pipeline (`xmage_model_build.py`) and the `Exp1Compat` engine helpers.
  - `entityName` already returns `PlayerA`/`PlayerB` relative to the viewer, as the vendored encoder does.
  - Empty history, `isActivating`, sorted cards and `opponent` are also reused.
- The v0.2 `ActionEncoder.ActionType` and `FeatureMap`.
- The staged v0.2 search sources (`MCTSNode`, `MCTSPlayer`, `ComputerPlayerMCTS2`): `BenchSearch` steps the engine through them.
- The kit's `Sampler`/`WorldBuilder` worlds with the opponent's hand hidden, one world per decision (k = 0) as the existing neural agents do.
- The confined NDJSON inference loop: Java emits `infer` events, Python forwards them to the container, and the scores come back.
- The supervised arena launcher and identity binding.

What is new:

1. **Graph encoder (Java).** Stage `StateEncoder.java` and `FeatureGraph.java` from the pinned draft-zero copy into `spellbench.models.draftzero.gnn.encoder`. Apply declared rewrites in the same style as `xmage_encoder_sources.py`, and pin the source hashes in `releases.json`. `GraphEncoderMain` emits the graph-server layout: indices, values, edge child, edge parent and edge label.
2. **Option mapping (Java).** Port `GraphRecord` and `GraphNet.Policy`.
   - A priority candidate maps to its ability node, or the Pass node.
   - A target candidate maps to its target's UUID node, or Stop Choosing.
   - An attack maps to Stop Choosing or the defender.
   - Yes/no maps to the use head.
   - Candidates group by copy, with log-sum-exp within each group.
   - `GraphMCTSPlayer`'s attack and block loops record the attacker, the blocker and the decision source.
3. **Search (Java).** Port `BenchSearch.searchTree` with the settings above, bound in one explicit settings object, with the deterministic seed taken from the kit's seeds. Decisions with no head use the same fallback the author's games used: MageZero's player.
4. **Network runtime (container).** Add a `draftzero-gnn` architecture to the confined backend, built with `docker build --target gnn`. The default image keeps its instructions; only the new stage adds `safetensors==0.6.2`, pinned by wheel hash.
   - The backend loads the safetensors weights and the vocab.
   - The author's `graph_net.py` is used only inside the container, read-only and hash-checked.
   - A request carries one encoded state and returns per-node priority and target scores, use and value_x.
   - A request with no known leaves is refused.
5. **Checks:**
   - The reference loader reproduces all 300 goldens inside the container, measured with `gnn_reference_probe.py`.
   - The serving path reproduces the goldens to about 1e-5 with the same top option in all 300.
   - The Java encoder is repeatable on native states, and hidden-sample invariance holds for the opponent's hand.
   - Vocab coverage per decision type is measured on our engine and compared with `coverage.json`.
6. **Entrant.** Add `draftzero-fdn-gnn-100-fair` to `fdn-draftzero-v1`. Its identity binds the checkpoint hashes, build, image, settings and sources, as the Exp1 entrants do.

Risks:

- **String drift.** The encoder targets a fork about 11 months older than our XMage pin. Low coverage on some decision types, blocks especially, would weaken play without failing. The coverage receipt reports it.
- **Decision text.** The text leaf must reproduce the author's strings for priority (`priority`), targets, attacks and blocks.
- **Engine APIs.** The encoder uses engine APIs newer than v0.2's base (for example rooms, cloak and disguise). They should exist at `fd40ad5c`, and the build will confirm it.

## Status

Implemented on this branch (uncompiled until a host reservation frees):

- `releases.json` pins the release files, the draft-zero encoder and search sources and a `draftzero-gnn` backend.
- `xmage_draftzero_gnn_sources.py` stages StateEncoder, FeatureGraph, GraphRecord, GraphNet, GraphMCTSPlayer and
  BenchSearch with recorded edits (namespaces, Exp1Compat/GameAccess helpers, Java 8, the pipe instead of the HTTP
  graph server, tree method only). `xmage_model_build.py --draftzero-gnn-inputs` compiles them.
- `SearchPlayer.GRAPH` routes MageZero v0.2's priority, replayed callback and combat roots through `GnnSearch`
  (BenchPlayer's PIMC path on the permitted sampled world). `GnnBridgeMain` binds settings and the graph pipe per
  request; MageZero's own tree is unchanged when nothing is bound.
- Container: `gnn_runtime.py` serves per-node scores, use and value from the release's NetGraph; its `check` mode runs
  the 300 goldens through both the option and per-node paths. Host: `xmage_gnn_backend.py`, `xmage_gnn_model.py`,
  `xmage_gnn_search.py`, `xmage_gnn_runtime.py` (identity binds inputs, settings, build, image and sources). Leaf
  vocabulary coverage is audited at every session close.

Declared differences from the author's games: one permitted sampled world instead of a re-deal of the live game; CPU
float32 instead of bfloat16 on GPU; copies of one option report merged statistics on the played copy; a root with one
MageZero option is still searched; a source timeout is a failure rather than a fallback.

Next: golden and timing receipts, compile and bridge smoke (queued on the second host), a natural game and its
exact-seed replay, then the `fdn-draftzero-v1` entrant (100 simulations) with its evaluation inputs.

No rated runs and no commitments.
