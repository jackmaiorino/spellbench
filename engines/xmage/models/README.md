# DraftZero neural adapters

This is the tested connection from permitted XMage observations to Exp1's
feature hash and legal priority, target and binary policy slots. It is not a
complete agent. The neural connector selects directly from these trained
heads; its declared variant does not run the original MCTS search.

The source staging tool verifies the pinned public Java encoder files before
making explicit compatibility edits for the reviewed base engine. The staged
source hashes and every rewrite are recorded. Card sorting, entity names and
permanent ordering use the public fork's rules. Optional debug pairs use a
small local value type instead of JavaFX. Micro-decision history is empty and
the activation-in-progress flag is false at these slices. Soulbond
pairs and unsupported reconstructed worlds are refused.

Build with the pinned JDK 23.0.1 and reviewed engine inputs:

```powershell
uv run python python/tools/xmage_model_build.py --inputs D:/e-scratch/JOB --engine ENGINE_BUILD --out D:/e-scratch/JOB/BUILD
```

Run `spellbench.kit.xmage.ModelEncoderCheck` with `BUILD/model`, `BUILD/core`,
`BUILD/kit` and the engine jars on the classpath, in a working directory
holding its own pinned `db`. Set `-Dmz.actionVocab` to the verified `FDN_SPG.tsv`.
The real fixture reaches precombat priority with Stab, checks identical feature
and action outputs across varied sampled hidden worlds, and confirms that a
visible life change alters the features. Generation 33 then scores those real
features inside the no-network backend and produces repeat-identical scores
for offered candidates.

`ModelEncoderMain DECISION.json WORLD_SEED ID_SEED` also accepts a saved kit
decision record. Seeds are 32-byte lowercase hex strings. `--stdio` keeps the
same audited encoder warm on a private NDJSON pipe. Each request supplies `id`,
`game_start`, `decision`, `world_seed` and `id_seed`. Replies retain that ID
and either the encoded snapshot or a refusal. A malformed seed is refused
without poisoning the following valid request.

The encoder receives no live
engine game, opponent hand or actual library order. Opponent-hand encoding is
disabled. Reconstruction and watcher approximations remain explicit in the
output. Targets use the original entity-name vocabulary, including the stop
slot. True/false callbacks use slots 1/0. Every slot retains the offered
candidate ID and the encoding binds to the canonical decision SHA-256.
Unsupported callback families and reconstructed worlds are refused. A Kaito
emblem and an incomplete optional-kicker stack were correctly refused before
inference.

`ModelCallbackCheck OUTPUT_DIRECTORY` reaches two real engine dialogs: Stab
targeting two creatures and Campus Guide's optional library search. It writes
the permitted records and encodings, checks their original policy slots,
varies sampled hidden hands/libraries, and checks sensitivity to visible life.
Both fixtures pass and their output is identical across the retained builds.
The persistent pipe reproduces those snapshots. The original priority fixture
also retains its exact output SHA-256.

The isolated client maps real scores only to the bound offered candidates:

```powershell
uv run python python/tools/xmage_neural_decisions.py --root D:/e-scratch/JOB --checkpoint draftzero-exp1-gen33 --image sha256:OBSERVED_IMAGE_ID --record D:/e-scratch/JOB/target-record.json --encoded D:/e-scratch/JOB/target-encoded.json --report D:/e-scratch/JOB/target-result.json
```

Use the immutable image and hash-verified inputs described in
[the backend instructions](../../../integrations/xmage-models/README.md).
All three public checkpoints have selected offered candidates repeatedly on
both real callbacks. The client validates all policy widths and finite values,
the checkpoint/source readiness hashes, and the request ID. Writes, reads and
validation share one deadline. A failed exchange closes the owned container
and prevents subsequent use. There is no native or random-policy fallback.
Direct inference takes the largest offered raw logit and resolves ties by the
lowest candidate ID. That choice rule and the encoder approximations must
remain part of any future entry identity.

The original Exp1 search has a separate bridge for priority, target and binary
roots, including a visible library search after an earlier recorded choice. Build it with
`--search-inputs` pointing to the verified search sources and dependency from
the release manifest. `xmage_search_sources.py` relocates the pinned classes
and records every compatibility edit and source hash in `STAGE.json`.
It keeps the original PUCT, priors, discounted backpropagation, virtual loss,
dialog scripts and visit-based final choice. Its source classes share no names
with the native bots. The base fork's core helpers are ported separately.

`spellbench.kit.xmage.ModelSearchMain` is a warm private NDJSON process.
`xmage_neural_search.SearchSession` supplies real checkpoint heads and value
through the confined `InferenceSession`. Requests contain only permitted
records and independently sampled world seeds. Responses bind to the canonical
decision hash, cover every offered root action, complete the requested visits
and choose a supported visit winner. Stale responses, incomplete roots,
unsupported worlds, inference failures and exhausted clocks close both
owned processes. The neural float RPC is private; public v2 frames keep their
integer-only contract. There is no heuristic or random replacement on failure.

For a callback root, the request includes `anchor` with the latest relevant
offered priority `decision` and bound `selection`, and `replay` with public
`priority_passes` and earlier own `decision`/`selection` pairs. Replay validates
each received observation and selection before reaching the requested callback.
Only visible own-library facts condition the sampled world. The original
micro-decision history and activation flag reach the encoder through the real
callback. Unrecorded callbacks terminate replay even when XMage would catch an
ordinary exception. The result records how many earlier choices and passes it
replayed and confirms an identical received observation.

The declared play variant uses a fresh tree per received root, synchronous
inference, a fixed visit count, all four trained policy heads, no root noise
and opponent-hand encoding disabled. Prior temperature is 1.5, the exploration
bonus 0.1, PUCT constant 1 and backpropagation discount 0.99. Reconstruction
approximations remain in the result. The reviewed engine also lacks the fork's
combat retry shortcut, which remains part of the unfinished combat qualification.
These settings identify a fair port rather than exact full-player equivalence.

Generation 33 completed two identical six-visit real priority searches through
this bridge: root visits 1/2/3 for pass/Stab/land, seven neural calls, and the
offered land selected. The root feature set equals the independently encoded
priority features. The original priority output hash is unchanged and both
process exits are confirmed. This is a small correctness check.

Generation 33 also repeats six-visit searches on Stab's targets, Campus Guide's
optional trigger and its library selection after a recorded yes. Each performs
seven neural evaluations. The library root represents nine offered candidates:
eight search branches and an explicitly excluded fail-to-find choice. Original
Exp1 requires the target minimum before finishing; the bridge preserves and
labels that restriction. Initial branches pruned by the original search remain
in the result with zero visits and null value. Altered visible life is refused,
and owned process exits are confirmed.

Full history across draws and other transitions, the remaining decision families, complete-game tests
and rating qualification remain to be implemented. No playing-strength claim
follows from these checks. Evidence is
indexed in [the input and adapter receipt summary](evidence/2026-10-03-neural-inputs.md).

Numeric and named callbacks are under extension. Their original trees use the
trained value network with uniform priors; the checkpoint has no numeric or
named policy head. Numeric branches retain Exp1's 65-option safety limit and
use the legal range offered by the engine. The replay applies that bound to
the current source and player in the simulated prefix, and records the change
as an approximation. Named options bind original keys and labels to offered
semantics. The original creature-type shortcut and forced choices still need
their own bridge. Remaining callback families continue to fail closed.

Builds 034 and 035 compile with the pinned JDK. Real Fireball and Shifting Sky
fixtures save six numeric values and five colors. The first color fixture,
Thriving Grove, reaches an unsupported replacement-order callback; its failed
receipt is retained. Generation 33 repeats the existing target, binary and
library searches on build 035, but refuses the unbounded original numeric
callback before named search. The offered-range adaptation and refreshed
named replay anchor await their next real check. These families are unqualified.

Jack's private April encoder and callback source are staged by
`xmage_jack_sources.py`, with both original file hashes required. The base
encoder uses the acting viewer, named permitted entity references and known
library cards in public alias order. Text embeddings come from a pinned
read-only cache. The candidate extraction preserves the original priority
action IDs, 48 features and 64-slot padding, using the acting player in the
reconstructed world. Extraction failures refuse the decision; more than 64
offered choices are refused without truncation. Other callback paths are not
exposed by this bridge.

`xmage_model_build.py --jack-inputs PRIVATE_ROOT --jack-manifest INPUTS.json`
adds these private sources to the reviewed build. `JackEncoderMain` takes a
record or `--stdio`, the embedding path and hash, both staged source hashes,
and a seed record or `--request-seeds`. It returns original priority features
and the corresponding offered candidate IDs. `JackEncoderCheck` prepares two
real active and nonactive priority views, checks their hand/ownership and
candidate binding, and compares features across different hidden samples.
The new Java build and fixtures have not run yet. Paired model inference on
these actual features, other callbacks, exact checkpoint deck associations,
complete games and rating qualification remain unfinished.
