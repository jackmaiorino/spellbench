# DraftZero neural adapters

This is the tested connection from permitted XMage observations to Exp1's
feature hash and legal priority, target and binary policy slots. It is not a
complete agent. The neural connector selects directly from these trained
heads; its declared variant does not run the original MCTS search.

The original-search components also have a public v2 frontend in
`python/tools/xmage_neural_agent.py` and a verified launcher in
`python/tools/xmage_neural_runtime.py`. Complete-game qualification remains
pending. The frontend uses one mixed Java pipe and one confined checkpoint
per game, retains the original complete combat plan across its declaration
group, and supplies saved own actions and earlier callbacks to Java replay.
History contains only previously visible names and confirmed own loyalty
costs. Seeds follow the kit's HMAC construction, using only `agent_seed` and
`seat_step`. Opaque request and game IDs do not seed play.

The default minimum visit count is 1000. A six-visit diagnostic is a separate
identity. The fair port uses the shared host clock with the previously
declared 600-second search envelope; original Exp1's default is 4 seconds.
The emitted identity records this change, no root noise, fresh trees,
disabled opponent-hand encoding, checkpoint hash, model build, immutable
container image and Python adapter source hashes. The pregame keep choice
preserves a newly constructed original player's `allowMulligans=false`
default. Human-player takeover configurations that enable mulligans are
unfinished. Unsupported callbacks, missing anchors, changed combat groups,
rewinds and expired clocks close the session without a substitute policy.

The launcher requires SHA-256 pins for Java, the reviewed model build and
the immutable card database. It verifies every class, classpath resource,
engine jar, original-search dependency and action vocabulary before serving.
It accepts the native relative path separators in both Windows and Linux
build manifests and refuses compile-only builds. `--print-identity` performs
these read-only checks without starting Java, Docker or a game. Required
arguments are shown by `python python/tools/xmage_neural_runtime.py --help`.
The supplied `--work` root keeps an ownership file before each Docker launch,
so the supervising job can recover its container after a process kill.
Cleanup reports confirm absence before deleting that process's private DB.

Use `python/tools/xmage_neural_game_check.py` under a supervising guarded job
for one unrated full game and its identical-seed replay. Its pinned JSON plan
declares the engine and agent commands, identity, FDN decks, seed and clocks.
It retains public traffic, diagnostics and primary outcome hashes. A
non-natural ending is a failed correctness check. This diagnostic cannot
create a rated tournament or publish a leaderboard. Its storage manifest
must count both engine and agent working databases. Formal evaluation still
requires frozen benchmark review and compatible throughput qualification.

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
decision hash, cover every offered root action, account for the actual visits
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
inference, a minimum visit count with original legal-future stopping, all four trained policy heads, no root noise
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
callback before named search. Later real checks validate the offered-range
adaptation and refreshed named replay anchor. Complete-game qualification
remains unfinished.

Build 036 repeats target, binary and library search, then returns 41 numeric
root visits for a requested minimum of six. Original Exp1 keeps searching
until a legal future exists and resets some branch statistics during
`bestChild`; the bridge's exact-count assumption refused the result. The next
bridge records the original minimum stopping rule, captures cleared branch
visits before selection and checks that retained plus cleared work equals
root visits. The capture leaves original expansion, masking and selection
unchanged. Build 041 repeats the target, binary, library and numeric roots.
The numeric root records 41 actual visits, 42 neural evaluations and 33 cleared
branch visits, with X=4 selected. The named root then refuses an unsupported
Shifting Sky stack anchor. All owned Java and model processes exit. These
checks and the earlier annotation build failure are retained in the cold
accounting snapshot.

Shifting Sky's register entry is now generated from 24 pinned upstream source
files. The scanner reads card types from the constructor, so a LAND predicate
inside an enchantment's effect does not classify it as a land. Unrecognized
constructors retain the conservative fallback. Its repeated source scan
supports stack replay without optional costs. The actual named search now
repeats Blue across the five-color root with six visits and seven real neural
evaluations; changed public state is refused and owned process cleanup passes.
Model build manifests now hash and verify copied resources, including
this register. Existing frozen native jars and qualification inputs are unchanged.

The confined `jack_feature_probe.py` helper runs all five real checkpoint
pairs on the Java priority fixtures without enabling unassociated game serving.
Active and nonactive views repeat with finite normalized scores, legal offered
IDs and masked padding. Elves uses its own embedding-cache fixture. This is
diagnostic feature inference; exact decks, the original full policy selection
and other callbacks remain unfinished. See
[the retained checks](evidence/2026-10-03-neural-inputs.md).

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
Build 039 compiles with JDK 23.0.1. Both real active and nonactive priority
fixtures pass their hand, ownership, legal candidate binding, original pass
and padding checks. Eight different hidden samples per fixture leave base
and candidate features identical, while a visible life change alters them.
The guarded check completed in 20.5 seconds with all owned children stopped;
tested classes and receipts are retained. Paired inference on these features
passes in the later confined checks described above. Other callbacks and
exact checkpoint deck associations,
complete games and rating qualification remain unfinished.

`ModelCombatMain` runs Exp1's original per-creature binary attacker choices
and target blocker choices, with the same trained priors, minimum visit rule
and recorded selection masking as the other search roots. Its initial
reconstructed combat anchor resumes before declarations; resuming a paused
PRE anchor would skip those callbacks. Every root must have the expected
callback family and player. The anchor adjustment and unported fork
illegal-block retry shortcut are explicit approximation flags.

`xmage_neural_combat.CombatSession` shares one clock across private Java RPC,
confined model inference and result validation. `CombatPlan` retains the
original assignment through the engine's declaration group. It binds each
choice to an offered candidate, accepts declarations held pending until the
group completes, and refuses skipped substeps, rewinds, repeated creatures or
unrelated public changes. Failed sessions close both owned processes.

Build 047 and the actual generation-33 checkpoint repeat both attack and
block plans. Each plan has two roots, six visits per root and 14 neural calls.
The reviewed engine accepts all two attacker and two blocker substeps, and
the retained Python plan selects the same offered choices. These are combat
correctness checks. Full transition history, remaining callbacks, the fork's
illegal-block retry behavior, complete-game serving and rating qualification
remain unfinished. Receipts and failed attempts are indexed in
[the evidence summary](evidence/2026-10-03-neural-inputs.md).
`ModelBridgeMain` joins the existing search and combat entry points on one
warm private Java pipe. `xmage_neural_bridge.BridgeSession` owns that pipe and
one confined checkpoint session. Priority, saved-anchor dialog and combat
requests share an increasing request sequence, failure state and cleanup.
Each request retains one clock across Java RPC, neural scoring and validation.
Results identify their requested operation and cannot replace the pinned
checkpoint identity. An error terminates the Java loop and closes both owned
processes on the Python side. The original search algorithms and settings
remain in their existing entry points.

The reviewed-build CI now also compiles the public model encoder, original
search, combat and mixed bridge classes with JDK 23.0.1. It fetches only pinned
Java sources and the pinned Commons Math dependency. Its ephemeral input
directory has a 32 MiB cap and 1 GiB free-space reserve. `--compile-only`
requires the pinned upstream engine revisions and hashes the actual jars,
then records a distinct compilation manifest with `reviewed_runtime: false`.
The default model build still requires the reviewed 004913a engine manifest;
local input caps and runtime qualification remain unchanged.

Mixed request, clock and ownership checks pass alongside the existing search
and combat checks. Build 048 and generation 33 complete eight interleaved
priority and combat requests through one JVM and checkpoint session, with
84 real neural evaluations. Repeated results are identical, combat results
equal their earlier isolated receipts, and all four real wire declarations
bind identically. Owned cleanup and reservation release are confirmed.
Pregame decisions, complete transition history, remaining callbacks and
complete-game qualification remain unfinished.

`--magezero-inputs` adds the five pinned MageZero v0.2 encoder sources to a
separate `spellbench.models.magezero.v02.encoder` package. They retain their
original feature hash range of 2,147,483,647 and 128-slot action hash, including
reserved pass and mana actions. A negative original hash is refused rather
than repaired. The same declared base-engine compatibility edits provide
sorted cards and public entity names; priority slices use empty dialog history.
The staging receipt records every edit and staged source hash. Exp1's encoder
and action vocabulary remain in their existing package.

`MageZeroEncoderMain` accepts a saved permitted priority decision or `--stdio`.
It reconstructs a sampled world, disables opponent-hand encoding and binds
every offered candidate to its original MageZero action slot. Other callbacks
are refused. `MageZeroEncoderCheck` supplies a real priority fixture, varied
hidden samples and a visible-life control for a later guarded runtime check.
The fixture has not yet run. CI also compiles this optional public path without
fetching weights or qualifying play.

`xmage_neural_decisions.py --architecture magezero-v02` connects these saved
features to the existing confined raw/`.mz` backend when actual weights arrive.
It checks the exact encoding, 128-slot heads, checkpoint and source identities,
decision hash and complete offered-choice mapping. It recomputes the supplied
own decklist's Spellbench digest and requires the checkpoint's recorded deck
association before launch. Argmax masks unoffered actions and uses a stable
tie rule. This is an explicitly distinct direct-policy priority slice; original
MageZero search and complete-game serving are unfinished. No actual pretrained
MageZero weights have been found or qualified.

Spell-mode callbacks now enter Exp1's original `chooseMode`, which constructs
a numeric action list with stop at ordinal zero and available modes in source
order. The replay binds those ordinals to the engine's public mode indices,
source, selected count and mode bounds. Recorded choices append the original
numeric history before later callbacks. No separate trained mode head or new
priority rule is introduced.

The original mode stop can be unoffered when the engine requires a mode.
Search retains that original branch. It can leave the public candidate list
only with captured original pruning or selection masking and complete spent
visit accounting. An unoffered branch with a legal future or an unoffered
chosen result is refused. The Python result validator checks that accounting
alongside all offered children. Replaying a forced numeric prefix now also
preserves the original rule that a one-option amount does not append history.
`ModelSearchCallbackCheck OUTPUT mode` prepares a real Abrade modal callback
with both creature and artifact modes available. Runtime replay, actual
checkpoint inference on this callback and full-game qualification are pending.
