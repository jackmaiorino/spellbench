# DraftZero neural adapters

Jack's original general target component uses `JackTargetEncoderMain` and
`xmage_jack_targets.TargetSession`. Set `target_callback: true` in the private
input manifest with the mode, dialog, filtered-mana and automatic payment flags.
The pipe takes the embedding file and seven source hashes: embedding, state,
candidate, target rules, mode rules, dialog rules and payment rules. Private
source and paired weights stay outside public Git.

The actual original loop preserves legal target order, earlier picks, STOP
availability, direct single/same-name choices, the `target` head, original
candidate IDs/features and the first 64 slots. Forced choices bypass both
inference and chooser RNG. A model error refuses. Each frame binds named
permitted objects or players, source, slot, selected count, range and the full
replay request. Earlier mode, binary and X choices use their original rules;
automatic payment shares the original private bridge. The paired network,
original chooser and one shared clock are owned by the session.

This path supports the acting player's named-source `choose_target` and
`finish_target_selection` spell callbacks. Native execution, costs, provided
card sets, divided targets, opponent-sourced choices, complete games and deck
qualification remain unfinished. The extracted loop retains its original
minimum and Crew/Saddle completion rules for future callback qualification.

Jack's original yes/no and X component uses `JackDialogEncoderMain` and
`xmage_jack_dialogs.DialogSession`. Set `dialog_callback: true` in the private
input manifest to stage `DialogRules.java` from the pinned April callback.
The component requires the reviewed replay build, original offline embedding
cache and staged source pins. It reaches the actual callback, checks its
visible source and observation, and binds the full replay request.

The private rules retain all three original binary mana feasibility gates,
the original filtered mana availability, conditional mana checks and X cap
at 20. Ordinary binary choices use YES then NO and their distinct original
token IDs. X choices retain the original affordable integer range and mana
budget features. Both use the action head, paired policy and one game-owned
original Java chooser. Forced feasibility and single-X returns bypass the
model and chooser. The shared clock and resource cleanup are inherited from
the tested mode component. Other number callbacks, native automatic mana
qualification and complete games remain
unfinished. This component has no trained-checkpoint or full-game claim.

Jack's original spell-mode component uses `JackModeEncoderMain` and
`xmage_jack_modes.ModeSession`. An explicit `mode_callback: true` in the private
input manifest stages the original legality rule as `ModeRules.java`. The
callback encoder requires the reviewed search/replay source build through
`--search-inputs`, the pinned offline embedding file, and the staged state,
candidate and mode-rule source hashes.

The bridge replays a saved permitted priority and its recorded prefix,
verifies the current observation, and resolves named entities against that
current visible projection. It preserves original available-mode order,
the first 64 slots, the original legality mask, action IDs, 48 features and
the float32 ordinal overwrite in feature 0. It builds the base state before
checking costs and targets, as the original callback does. A sole available
mode or exhausted mode list returns directly without inference or RNG use.
The remaining mode frame uses the paired policy and game-owned Java chooser.
The full request, game, decision, sources, offered slots and shared clock are
bound; failures close all three owned resources.

For modes with costs, set `mode_mana_callback: true` together with
`mode_callback: true` and `dialog_callback: true`. Pass the staged dialog-rule
source hash as the sixth `JackModeEncoderMain` argument and use
`xmage_jack_modes.ManaModeSession`. The replay player then uses the original
filtered mana availability for the acting viewer, including copied games
used by cost checks. The original mode legality rule and cost-presence
feature 13 are retained. Frames bind the extra mana-rule source and the
Boolean cost flags for all original candidate slots, including masked modes.
The pipe advertises `jack-permitted-mode-mana`; the five-argument pipe retains
its original restricted mode variant.

The opt-in automatic payment path adds `mana_payment_callback: true` to the
private manifest, with the original filtered mana path already enabled. It
stages `ManaPaymentRules.java` from the same pinned callback. Producer
filtering and stable ordering, activation source/tap-target reservations,
nested unpaid-mana context, color preference and tap-target rules retain
their original source. Actual and copied players hold separate reservations.
The ordinary engine delegation preserves its ordered pending mana costs and
does not call the Exp1 policy. This path pins the original default
`RL_ENGINE_CHOICES=1` and empty parent planning queues used by the RL path.

Pass the staged payment-rule hash as argument seven to `JackModeEncoderMain`
or argument six to `JackDialogEncoderMain`, and use `PaymentModeSession` or
`PaymentDialogSession`. Readiness and every frame carry the additional source
pin and a distinct payment variant. Older consumers refuse these variants.
The paired policy, original chooser, clock and cleanup remain owned by the
same game session. Earlier pipe argument counts retain their previous
variants. The public CI check compares ordinary engine color delegation for
all six mana colors with ordered pending payments. Private rules and real
payment/reservation lifecycle still require guarded native qualification;
these source components do not qualify a complete entrant.

Invalid or unsupported callbacks refuse in place of the
original heuristic fallback. Local transport checks do not execute private
Java or checkpoints; native callback and hidden-world replay checks, other
callbacks, exact deck associations and complete games remain unfinished.

Jack's private paired inference now also has an original mulligan feature
component. A `mulligan_encoder` asset in the external Jack manifest stages
the hash-pinned private `MulliganModel.java` into `MulliganEncoder.java`.
The Java source is identical at the declared April and legacy Q network
revisions. The port retains the original 71 features, hand card IDs, land and
creature counts, average nonland mana value, and remaining-library composition.
It orders the library by known card name to remove hidden order. This is a
declared fair variant; pooled floating-point outputs still need native replay.

`JackMulliganEncoderMain` reads owned pregame records through a private pipe.
`xmage_jack_mulligan.MulliganSession` binds each encoded decision and observed
counts to the exact game start already verified by the paired model. Both
networks keep ties: the April network keeps at probability 0.5 or greater,
and the legacy Q network keeps when Q_keep is at least Q_mull. Evaluation
disables the original training exploration, keep floor and hard overrides.
The shared clock includes encoding, inference and validation. Changed source,
stale responses, malformed padding and unoffered choices close both resources.
`JackMulliganEncoderCheck` prepares actual pregame and hidden-world checks for
the guarded native job. These checks have not executed. Other callbacks, deck
associations, original duplicate-prompt handling and complete games remain
unfinished; this component is not a full agent or a rated entrant.

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

`--play-profile published-exp1-final-eval-fair-v1` selects the separately
identified released final-evaluation play settings: 96 visits, 12 seconds,
backpropagation discount 0.99, prior temperature 1.5, bonus 0.1, and only the
binary prior. `--visits` may be omitted or set to 96 for this profile. The
original time-or-visits loop can stop below 96 visits after it has a legal
future. Priority, saved-anchor dialogs and every per-creature combat root
retain that stopping rule; the public frontend reuses the resulting combat
plan across the declaration group. Changed settings, architecture and work
receipts close the session. Older builds without `PlaySettings.class` cannot
serve this identity.

The pinned [source derivation](../draftzero-published-play.json) distinguishes
the recorded 0.7 training-label discount from the runner's 0.99 play-time
backpropagation discount. Noise is disabled; the recorded epsilon 0.15 and
selection temperature 2 are retained, with maximum-visit selection as in the
original no-noise tree. Automatic mana tapping, duplicate states and the
released no-mulligan rule are retained. All three public checkpoints use one
common final-evaluation profile rather than their separate training-time
profiles. The released runner enabled opponent-hand encoding; this entry
disables it and is explicitly a fair variant. The existing fresh-tree,
synchronous transport and confined CPU float32 changes also remain declared.
Full-game replay, clock sensitivity, broader FDN coverage and completed-work
throughput must be qualified for this profile before rated play. Earlier
six-visit diagnostic games do not qualify its published time control.

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

The private paired inference component `xmage_jack_inference.py` verifies the
actual own deck against the checkpoint association before starting its owned
container. Readiness binds both weight hashes, both network sources, the
original Java sources, the selected embedding cache and the fixed network
shapes. It supports all five candidate heads and both original mulligan
formats. Stale responses, wrong shapes, invalid masked probabilities and an
exhausted shared clock close the session. Container removal must be confirmed.
This component consumes encoded features; it does not choose public actions.

The stage also writes private `PolicySelector.java`, extracting the original
float32 normalization, first-index greedy choice and sequential sampling
without replacement. The private `JackSelectionMain` pipe and
`xmage_jack_selection.py` preserve these original indices and an explicitly
selected no-training profile. The original evaluation path uses greedy play.
An optional sampled profile uses one Java RNG per game with its declared
protocol seed. Source identities and changed fairness behavior are recorded
in [jack-play-profiles.json](../jack-play-profiles.json).

Generic candidate helpers expose the original head mapping, IDs, features
and combat candidate type in the private stage. The game bridge still exposes
priority features only. Original candidate filtering and order, per-callback
feature adjustments, mulligan encoding and application rules remain to be
wired. The new chooser has not yet executed in a guarded native check. These
components are not a complete playing agent or rated entry.

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
are refused. `MageZeroEncoderCheck` passes two actual native executions with
468 identical features and three policy slots. Sixteen draws per execution
include different hidden cards while preserving encoded features; a visible
own-life change alters the encoding. This checks the original priority encoder
without pretrained weights or complete games. CI also compiles this optional
public path.

`xmage_neural_decisions.py --architecture magezero-v02` connects these saved
features to the existing confined raw/`.mz` backend when actual weights arrive.
It checks the exact encoding, 128-slot heads, checkpoint and source identities,
decision hash and complete offered-choice mapping. It recomputes the supplied
own decklist's Spellbench digest and requires the checkpoint's recorded deck
association before launch. Argmax masks unoffered actions and uses a stable
tie rule. This is an explicitly distinct direct-policy priority slice;
trained-checkpoint qualification and complete-game serving are unfinished. No actual pretrained
MageZero weights have been found or qualified.

`--magezero-search-inputs` additionally stages MageZero's actual original
v0.2 tree from 17 independently pinned public source blobs. It requires the
separate original MageZero encoder input. The shared audited core compatibility
recipe reads those MageZero bytes; it preserves the original 128-slot visit
labels and places the tree and its private transport in
`spellbench.models.magezero.v02.search`. Exp1 keeps its separate implementation
and 1024-slot heads. Missing or mismatched source revisions are refused.

The transport requires finite 128-slot priority, opponent and target heads,
the original two binary outputs, and features below 2,147,483,647. An inference
failure reaches the caller without a heuristic fallback. These staged classes
require explicit source search settings, including every policy-head flag and
the original time stopping rule. The pinned default disables all policy priors;
the learned author configuration is therefore needed with the weights. A
separate diagnostic method enables all heads and enforces minimum visits.
These settings remain distinct in any future adapter identity. Native priority
and public callback replay now pass with synthetic scores; trained weights
and full-game serving remain unfinished. Two real source staging
executions produce identical hashes and preserve `new int[128]` and `%128`.

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
with both creature and artifact modes available. The guarded gen33 check
passes three unrelated or absent source refusals before neural inference,
then repeats the actual six-visit mode search identically with seven neural
calls each. Its unoffered stop is pruned with complete visit accounting.

`ModelSearchCallbackCheck OUTPUT mode-wire SAVED_MODE_RESULT_JSON` applies
that real learned mode through XMage, requires the next target callback, and
retains the original earlier-mode history in the target record. The guarded
check repeats this subsequent target search identically with seven neural
calls each and reproduces the current observation exactly. Broader callback
and full-game qualification remain unfinished.

MageZero's typed replay also covers targets, library targets, binary choices,
amounts, named choices and spell modes. Native paired checks use six visits
and seven synthetic calls per root. Mode selection applies through XMage and
reaches its following target, whose replay reproduces the observation exactly.
MageZero prepends the original numeric stop only when a mode may be stopped;
Exp1 always prepends it. The mode binding preserves both rules. The separate
Exp1 control repeats identically, and four changed-source or changed-observation
requests refuse before inference. These checks use no trained MageZero weights.

`MageZeroSearchCombatMain` and `xmage_magezero_combat` connect the separately
pinned original per-creature attack and block loops to the 128-slot transport.
Each real callback gets a fresh tree with every explicitly supplied original
setting. Work receipts preserve pruned and masked visits and echo the stopping
rule per root. The source time-or-visits profile may stop below its visit budget;
the separately named diagnostic profile requires minimum visits. A retained
plan binds each later declaration substep to the same original assignment.

`MageZeroSearchBridgeMain` and `xmage_magezero_bridge` share one model, serial
request sequence and owned private pipe across priority, replayed dialogs and
combat. A failed operation closes the session. The reconstructed combat anchor
resumes before declarations, as in the existing Exp1 compatibility port. Native
combat and mixed-operation validation, complete games, trained weights and
ratings remain unfinished; passing transport tests does not qualify an entrant.

`xmage_magezero_agent` now exposes that mixed bridge through Spellbench's public
game lifecycle. It shares the public replay history and decision clock, binds
MageZero's conditional mode rule and explicit settings, and retains its typed
combat plan across declaration substeps. The original constructor keeps
mulligans. Each new game creates a separate model session using only its seat
and exact own deck; terminal and failure paths close it.

`xmage_magezero_runtime.py` launches this frontend with one private JVM and the
existing confined inference backend. Its external weights manifest can add
deck-bound checkpoints while preserving every public source, encoder and backend
pin. The compiled build remains bound to the canonical public manifest, requires
both MageZero stages and the mixed entrypoints, and is verified before launch.
The public bot version binds the exact deck, checkpoint, search settings, build,
image and frontend source hashes. Startup failures clean up owned resources;
uncertain container cleanup retains the work directory. No trained MageZero
checkpoint or complete game has been qualified by these frontend tests.


`JackGeneralTargetEncoderMain` and `xmage_jack_general_targets.GeneralTargetSession`
extend the original general target loop to `choose_cost_target`, `select_object`
and `finish_selection`, alongside spell targets. They preserve source, visible
references, selected count, range and the original wire echo. Only callback
fields are normalized; public observations stay intact. Generic `TargetCard`
callbacks use the same original `target` head, ordering, direct returns and STOP
rules. Earlier mode, binary, X, payment and target choices retain their original
rules. The eight private stage bodies are unchanged. Source pins, the complete
request, normalized mapping and distinct variant remain bound before inference.
Use the existing target staging flag and the same seven source arguments.

Provided-card selection has separate original filtering, name deduplication and
copy selection and remains unfinished. Divided targets, opponent sources,
incompatible public/original ranges, private native execution, exact decks,
complete games, ratings and publication remain unqualified. Public normalization
checks and transport tests do not qualify the full agent.

## Original Jack activation replay

`xmage_jack_native_runtime.py` connects the public frontend to the original
priority, mulligan and activation player in one game-owned session. It requires
the complete private player build, including `JackModeEncoder`, and the existing
reservation and containment guards. The active research hold prevents native
startup. Arena run/bench run still owns substantial-work throughput and storage
qualification.

Binary, X and spell-mode callbacks retain the saved priority state, reconstruction
seeds and exact earlier selections. The current spell-mode callback runs the
original chooser, legality mask and 64-slot prefix once. An earlier mode uses its
recorded selection and original feasibility checks without a second policy draw.
Empty and singleton callbacks retain their original direct returns. Candidate
IDs and source references bind to actual modes on the permitted world.

Metadata verification compiled the private generated callback and public replay
with JDK 23.0.1 targeting Java 8. Two JVM runs were identical for 0, 1, 2 and 70
available modes, earlier mode prefixes, binary/X regression, copy ownership and
hidden-card read denials. All 56 affected Python checks passed. The first fixture
retained XMage's default selected mode; its failure is preserved before the
fixture clears that default. The working-space projection also failed after two
compile attempts. Both attempts and synthetic files were losslessly packed and
verified in D/E copies, restoring the 335 MiB native reserve.

Evidence is retained under `E:/spellbench-xmage-all-20261002/jack-mode-replay-001`.
Native resolution passes and priority continuation, remaining callback families, refreshed full
build/native preparations, trained-weight complete games and deck associations
remain unfinished. These metadata results do not qualify or rate a bot.

Named Choice replay now enters the original inherited `choose(Outcome, Choice,
Game)` body. Its keys retain their original policy order; visible labels, sorted
wire indices and candidate IDs bind separately. Duplicate option labels remain
distinct by visible slot. Colors, creature/type names and cast methods retain
their typed semantics. Forced choices bypass inference through the original
body; earlier choices apply the actual key or value without a second policy draw.
Alternative-cost choices already fixed by the saved priority state can apply
implicitly before a different public callback. Automatic mana-color choices
retain their original unposed engine delegation.

Only an owned root replay pause bypasses the inherited error cleanup. Foreign
pauses still close the receiving game-owned session. JDK23 target8 compilation,
two identical named-callback metadata JVM runs and 72 affected Python checks
pass. The original priority/choice, binary/X and spell-mode metadata checks also
pass with the new hook. Invalid labels, slots, counts, sources and IDs refuse
before inference. Evidence is under
`E:/spellbench-xmage-all-20261002/jack-named-replay-001`. Native runtime, large
card-name domains, remaining callbacks and complete trained-weight games remain
unqualified. Original private bodies and weights remain outside public Git.

General target replay now binds each pick inside the actual original target
loop, including visible spell, cost and object-selection actions. Recorded
targets apply to the loop without another model draw; the current pick retains
the original order, same-name direct return, STOP gates and 64-slot limit.
Binding requires the acting viewer's actual named source and the complete
permitted menu. Invalid sources, counts, ranges, slots, IDs, hidden references,
forced prefixes and prefixes outside the first 64 slots refuse before inference.
London uses its separate pregame group path described below. Provided-card activation replay is described below.

Two metadata JVM runs are byte-identical for 1/2/70 targets, target/cost/object
wire forms, earlier target mutation and forced/STOP returns. The unchanged
named-choice, binary/X/mode and original priority/choice checks also pass, along
with 81 affected Python checks. Production components compiled with JDK23.0.1
target8; subsequent fixture repairs reuse those exact production classes.
Failed fixture sources/logs remain retained. Evidence is under
`E:/spellbench-xmage-all-20261002/jack-target-replay-001`. This does not qualify
native callbacks or complete trained-weight games.

Provided-card replay now enters both the actual neural group loop and inherited
original `makeChoice` body. Neural picks retain first-64 group order, original
representative features and `card_select` scores, then select a physical copy
through the owned copy stream. Recorded picks mutate the original groups without
another model or copy draw. Inherited picks retain good/bad sorting, UUID ties,
queued targets, `target.add` and implicit completion without neural draws.
Bindings require the acting viewer's actual named Ability source and the complete
permitted menu. Invalid sources, ranges, IDs and recorded picks refuse before
inference. Full private builds require both card encoder classes.

All 93 affected Python checks pass. Two fresh metadata JVM runs have identical
normalized numeric results for 1/2/70 cards, grouped physical copies, sequential
picks, neural STOP, inherited sorting/queue/completion and recorded prefixes.
Target, named-choice, binary/X/mode and original priority/choice regressions pass.
JDK23.0.1 target8 compiled the production classes; the later multi-pick fixture
compile reuses those classes. The first fixture's incorrect following-X head
expectation and its failed log remain retained. Evidence is under
`E:/spellbench-xmage-all-20261002/jack-card-replay-001`. Metadata checks use synthetic
scores. Native callbacks, actual pretrained inference, general source contexts,
native priority/resolution execution and complete games remain unqualified.

`JackLondonPlan` now connects the original player's pregame bottoming callback
to the production root dispatcher and game-owned model/chooser session. Each
one-card callback ranks the entire remaining hand with the original `card_select`
head, complete sequential draw and cache signature. It applies the original last
ranked card and moves it to the library bottom before reranking. The single-card
shortcut bypasses policy and chooser draws. Bindings require the first public
bottom group, its observed mulligan count and the complete named own hand.

Spellbench collects all public bottom picks before moving cards in the engine.
The frontend therefore binds the generated sequence to subsequent public substeps
with unchanged observation, group, step and remaining-menu checks. These substeps
do not make another session or model call. The ordinary session, clock and
failure cleanup remain shared; an interrupted or changed group refuses. Full
private runtime builds require `JackLondonPlan`; reduced encoder builds exclude it.

All 150 affected Python checks pass. Two normalized metadata JVM outputs match
for 1/2/7-card hands, complete shrinking-hand ranks, singleton shortcuts, bottom
order, first wire selection and malformed-menu refusal. Card, target, named,
binary/X/mode and original root regressions pass. JDK23.0.1 target8 compiled the
production classes. The checked-exception compile repair, pregame fixture repairs
and Python fixture failure remain retained. Evidence is under
`E:/spellbench-xmage-all-20261002/jack-london-plan-001`. Fixtures use synthetic
scores and metadata card movement; native movement, actual checkpoints and full
games remain unqualified under the research resource hold.

`JackCombatPlan` now connects root attack and block groups to the actual original
player callbacks and existing game-owned model/chooser stream. It binds the first
public creature and targets to the named current battlefield before inference,
then collects the original declarations. The original loops retain DONE-last
full sequential draws, separate defender choices, cached base state, descending
attacker-power block order and removal of declared blockers. An unoffered result
refuses instead of substituting a declaration. Nested root combat callbacks
refuse before additional inference; supported simulation admission remains owned.

The frontend retains that whole combat plan across declaration substeps through
the existing public state/group checks, without another session or model call.
Full runtime builds require `JackCombatPlan`; reduced encoder builds exclude it.
All 250 affected Python checks pass. Two normalized combat metadata JVM outputs
match for attacks, multiple defenders, blocks, DONE, original draw counts,
first wire binding and nested failure closure. Hidden-card reads are denied in
the fixture. London, card, target, named, binary/X/mode and original root checks
also pass. JDK23.0.1 target8 compiled the generated original callback/CombatRules
and public components. Fixture API and player-reference failures remain retained
under `E:/spellbench-xmage-all-20261002/jack-combat-plan-001`.

The root binding also mirrors the engine's full declaration slot schedule before
inference: active creature order, group block eligibility and limited/unlimited
maximum block counts. It records the public aliases for every slot and checks
the first creature and total count. Later substeps bind that exact schedule.
The original policy still assigns a blocker once and removes it from its pool;
its extra engine slots decline without changing that assignment or drawing from
the model. Unexpected repeats, changed slots and unoffered declines refuse.
All 265 affected Python checks and two fresh JVM outputs pass, including
additional/unlimited block capacity, unchanged original draw counts and both
held and rendered observations. The shared DraftZero combat binder is unchanged.
Evidence is under `E:/spellbench-xmage-all-20261002/jack-combat-slots-001`.

Combat legality and declarations in these fixtures are explicit metadata
overrides, with synthetic policy scores. Native declaration legality and
multi-block games, nested callback replay, actual pretrained inference and
complete games remain unqualified under the research resource hold.

`JackPriorityState` now captures and restores the original inherited target
queue alongside alternative-cost state. Capture reads the admitted original
player's actual queue and exports independent complete visible references.
Restoration verifies every reference against the saved root observation and
world alias bindings, then replaces the actual queue before activation. Ordered
duplicates are preserved; no model or physical-copy draw is added. Python serving
and the public frontend bind the same complete queue to the activation anchor.
Old receipts that omit the queue refuse.

All 276 affected Python checks and two fresh metadata JVM outputs pass for
0/1/2/64 entries, duplicate/order preservation, replacement, independent copies,
hidden-reference denial and pre-activation refusal. Actual inherited card queue
consumption and prior callback/combat/London regressions pass. The initial fixture
checked-exception compile failure is retained under
`E:/spellbench-xmage-all-20261002/jack-priority-queue-001`.
Immediate activation-to-priority continuation now reconstructs the saved anchor
world and restores its queue and alternative costs. The actual original activation
body consumes every recorded callback, with no model or physical-copy draws.
Its automatic pass is deferred until the completed world matches the public
priority observation, then bound to the exact offered pass. A recorded phase
pass follows the same path; otherwise the original next-priority dispatch runs
on that completed world. The frontend preserves anchor sampling seeds and requires
complete continuation receipts. Changed observations, unrecorded callbacks,
unoffered passes and unrecorded turn or phase transitions refuse and close the
owned session before further inference.

All 293 affected Python checks pass. Two normalized fresh metadata JVM outputs
match for 0/1/2 callback prefixes, stack and phase passes, original activation
cleanup, zero replay draws and fresh original dispatch. Prior callback, queue,
combat and London regressions pass. Evidence, including both initial fixture
failures, is retained under
`E:/spellbench-xmage-all-20261002/jack-priority-continuation-001`.
The activation fixture overrides legality and stack use, so native ability
legality, native priority-pass/stack-resolution execution, nested combat callbacks,
refreshed full builds, trained weights and complete games remain unqualified
under the research hold.

Saved public passes on a visible nonempty stack now connect to actual game resume
and the original resolving callback or next priority dispatch. The frontend retains
the pass anchor and sampling seeds. Serving validates exact public passed-seat
facts and the resulting opponent-pass order before entering the JVM. The admitted
original player applies its saved pass; `JackReplayOpponent`, a non-playing helper,
permits only recorded opponent priority passes while replay is bound. Opponent
menus, targets, triggered-ability choices and other unrecorded decisions refuse.
The bridge consumes recorded callback prefixes without another model/copy draw
and preserves the owned pause when it reaches the requested callback. A next
priority dispatch uses the original policy on the resumed world. Both frontend
and private serving require actual resolution and consumed-pass receipts.

All 329 affected Python checks pass, including 27 new resolution/required-build
checks and nine existing priority-source checks newly included in this scope.
Two fresh normalized metadata JVM outputs match across callback/priority endpoints,
recorded binary prefixes and opponent-already-passed cases. Saved/public pass bodies,
resolving X, next original priority, owned pause and pre-inference refusals pass;
previous callback, bootstrap, queue, combat and London regressions remain passing.
Evidence retains the initial runtime-fixture failure under
`E:/spellbench-xmage-all-20261002/jack-resolution-replay-001`.
The fixture scripts resume and stack contents, so this does not qualify the native
event loop or stack legality. Other phase transitions, library-position transport,
nested combat replay, refreshed full builds, trained weights and
complete games remain unfinished under the research hold.

End-step pass replay now admits the engine's fixed cleanup discard group. The
public root must be the same active player's end step with an empty stack. Each
current and recorded prefix menu must show cleanup in the same turn, both seats
passed, no priority seat and source-free discard choices from the complete named
own-hand references. Counts, group identity, consecutive steps and prefix indices
must agree. The JVM additionally binds the actual `TargetDiscard`, cleanup phase,
active player, actual hand and target range before entering the chooser. Other
source-free general targets remain unsupported.

The original sequential general-target loop retains its `target` head, same-name
direct returns, first-64 cap and target mutations. Prefix picks add no policy or
physical-copy draws; frontend and serving require the actual cleanup-path receipt.
All 365 affected Python checks pass, including 36 new cleanup checks. Two fresh
metadata JVM outputs match for one, two and three discards, every prefix, both
opponent-pass states and same-name direct choices. Changed phase, hand, source,
group or actual target range refuses before inference. Previous resolution and
callback regressions pass. Evidence is retained under
`E:/spellbench-xmage-all-20261002/jack-cleanup-replay-001`, including initial fixture
failures. Resume and target legality are scripted metadata; native cleanup and
complete trained-weight games remain unqualified.

Original callback reconstruction now supplies the full replay record to
`JackPermittedWorlds.buildReplay`. `JackReplayKnowledge` conditions a separate
sampling observation on permitted named own-library facts from earlier and current
callbacks. Root visibility remains unchanged: new IDs can bind reconstructed
objects without entering the root's named alias map, knowledge watcher or feature
tokens. Initial admission filters for permitted aliases before fetching a card.
Current aliases become available through the actual own look or public reveal.

First visibility determines a newly shown card's reconstruction constraint;
later positions for that identity are handled by actual replay. A root-visible
card moved into the library retains its existing physical binding. Conflicting
names, positions, capacities and own-deck composition refuse before bootstrap or
inference. New positional facts first shown after a library-size change refuse
until root-position transport is implemented. Opponent-library facts from later
callbacks do not condition the root. Shared DraftZero sampling/replay is unchanged.

All 366 affected Python checks pass, including a new missing-helper runtime check.
Two fresh metadata JVM outputs match. Tests use the real sampler across eight seeds
for search/look/reveal and top/bottom constraints, check first-visibility precedence,
and exercise original forced and neural `target` choices. Hidden-read traps and
feature token checks prove future cards are excluded at the root; current original
request tokens match the original encoder after the actual own look. Invalid pools
refuse before native bootstrap. Prior registry, cleanup, resolution, activation,
queue, combat, London and callback checks pass. Initial fixture failures and a
post-check storage-reserve failure are retained under
`E:/spellbench-xmage-all-20261002/jack-library-replay-001`; archive-verified duplicate
recovery restored the reserve without changing tested sources. Native reconstruction,
position transport, shuffle/movement history and trained-weight games remain open.

Before projecting a replay decision or admitting its named aliases,
`JackReplayKnowledge.verifyPositions` checks each permitted library fact against
the reconstructed owner's actual UUID order. A card must belong to that library;
any supplied top or bottom index must match. An unpositioned fact is accepted only
for a search. The check never fetches a hidden card name. This prevents a stale or
forged position from validating itself when the projection copies the supplied
look. Two fresh metadata JVM outputs match, including either player's permitted
library, one-sided positions, a real rearrangement and refusal before original
activation or scoring. All fourteen existing Java replay checks pass. Initial
fixture failures are retained under
`E:/spellbench-xmage-all-20261002/jack-library-position-001`. This guard does not
implement position transport or qualify native library reconstruction.

Empty-stack priority passes can now resume to a later priority phase in the same
turn with the same active player. The frontend retains the selected pass, complete
original priority state, exact public opponent-pass sequence and reconstruction
seeds. `JackDialogReplay` applies the original pass and resumes the reconstructed
engine. Its actual projected observation must match the requested decision before
the next original priority dispatch scores anything. Both serving and frontend
require the phase-advance receipt; unrecorded intervening choices or priority calls
refuse. Turn changes, repeated/backward phase sequences and nested combat callbacks
remain unsupported by this path.

All 267 affected Python checks pass, including 34 new transport/refusal checks.
Two fresh metadata JVM outputs match across upkeep/draw, main/beginning-of-combat,
end-of-combat/main and main/end-step transitions with both public pass orders.
They compare real projections and reject a reached phase that differs before
scoring. All fifteen existing Java replay checks pass. Resume itself is scripted
metadata, so native automatic actions, draws, phase legality and event-loop
qualification remain open. Evidence lives under
`E:/spellbench-xmage-all-20261002/jack-phase-advance-001`.

Ordinary `choose_number` amount prompts now bind the inherited `getAmount` callback
through the original replay and frontend. They use the unchanged parent chooser,
including its random draw, lower/upper clamps, fixed-value shortcut and cap of
`max(min, 10)` when the actual maximum is `Integer.MAX_VALUE`. They make no neural
X-head or physical-copy calls. The wire menu must bind the actual source and bounds
and contain every value in the effective inherited range, within the 4096-action
envelope. Native prompt generation retains its own candidate-limit guard.

An earlier amount is re-executed and checked against its recorded answer to restore
the reconstructed engine RNG before the next amount. This differs from replaying
neural choices, whose persistent model/RNG session must not draw again. A historical
amount disagreement refuses before the new choice; malformed source/range/value
records refuse before any amount draw. All 284 affected Python checks pass, including
three new frontend checks. Two fresh metadata JVM outputs match for 288 cases across
eight seeds, signed/fixed/high/capped bounds, visible sources and both prefix modes.
Answers and engine RNG consumption match a separate player running the unchanged
inherited parent body. All sixteen existing Java replay checks pass. Initial oracle
fixture compile failures, the superseded current-only oracle check and storage
refusals remain retained under
`E:/spellbench-xmage-all-20261002/jack-amount-replay-001`. Verified compression of
inactive duplicates retained both evidence copies and the native reserve. Actual
native amount prompts, larger-range wire behavior and complete games remain open.

Pile and replacement prompts now enter the unchanged inherited parent methods:
left pile and first replacement, respectively. Binding checks both complete piles
in physical-card order against permitted references, and all replacement indices
and sources against the actual map iterator order. Equal card names or effect
labels do not merge choices. Null/single replacement menus remain implicit.
Earlier answers are checked against the original fixed policy; disagreement closes
the session before the current choice. Full runtime builds require
`JackInheritedChoices`; reduced builds exclude it.

310 affected Python checks pass, including five new frontend checks. Two fresh
metadata JVMs match across 96 parent-oracle cases, and all seventeen existing Java
checks pass. No neural or physical-copy draws occur in these inherited choices.
Evidence: `E:/spellbench-xmage-all-20261002/jack-inherited-replay-001`.
Nested combat, native callback qualification and complete games
remain unfinished under the research resource hold.

The full CI runtime fixture initially omitted the newly required helper class.
Its complete-build fixture now includes it, and a missing-helper case verifies
startup refusal. All 34 runtime checks pass locally in addition to the 310 affected
checks above. Production sources and the seventeen Java results are unchanged.

Trigger ordering enters the unchanged inherited first-ability chooser through the
original callback player. XMage's wire presents every ordering pick before applying
the group. Replay checks and consumes all recorded picks virtually before the
first physical return, then verifies each remaining engine list without posing
another wire choice. The pinned engine applies its final singleton directly;
the replay queue retires at that point so a later trigger group starts normally.
Explicit singleton and empty callbacks still execute the unchanged parent body.

Binding preserves actual unsorted abilities, SeatPlayer's ability indices, repeated
instance counts and complete group positions. Current permitted sources bind their
references; recorded public sources whose zone counter changed bind the matching
null-source form. Unknown sources and movement into unobserved hidden zones refuse
before source lookup. These checks do not qualify native last-known-information
behavior. Earlier answers must match the original policy. No neural, physical-copy
or engine RNG draws occur in trigger ordering. Full runtime builds require
`JackTriggerOrder`; reduced builds exclude it.

300 affected Python checks pass, including five frontend cases and one additional
runtime missing-helper case. Two fresh metadata JVM outputs match across 180
parent-oracle cases, including engine-skipped final singletons and consecutive
ordering groups. The previous helper fails that regression; the repaired helper
passes, alongside all eighteen existing Java checks. Evidence:
`E:/spellbench-xmage-all-20261002/jack-trigger-replay-001`. Fixtures use metadata
worlds. Native event-loop execution, nested combat, library-position transport,
turn changes/repeated phases and complete trained-weight games remain open.

An empty-stack pass that advances the phase can now resume at an original dialog
before priority returns to the viewer. Recorded callbacks remain in the same root
and use the original reconstruction seeds. Their phases must follow the declared
forward interval with unchanged turn and active seat. Replay consumes their
answers without additional policy/copy draws and compares every actual observation
before dispatching the current original callback or priority policy. An unrecorded
viewer priority or opponent decision still refuses. The serving and frontend
require the original phase-resume receipt for both endpoint types.

259 affected Python checks pass, including 29 new frontend/serving cases. Two fresh
metadata JVM outputs match across 48 callback/priority transition cases, and all
nineteen existing Java regressions pass. Turn/active-seat changes, reversed or
overshooting prefixes, actual phase mismatch, missing passes and unrecorded choices
close the session before scoring. Evidence:
`E:/spellbench-xmage-all-20261002/jack-phase-callbacks-001`. Resume is scripted in
these metadata fixtures. Native phase transitions, turn changes, repeated phases,
automatic draws, nested combat and complete games remain unqualified.

Top and bottom library ordering now wraps the actual inherited `PlayerImpl`
movement loop. The original provided-card selector chooses and moves each card;
replay reads only the resulting owner's UUID block to expose the wire order.
Top placement reverses the physical selection order, while bottom placement
preserves it. The complete public card set, source, destination, group and
positions must bind before movement. Each historical pick must match the original
final order. Later group observations may drop known facts for selected cards,
but cannot introduce or change facts or omit facts for remaining cards. Each
reconstruction executes the original loop once with restored engine RNG and
adds no policy or physical-copy draws. Other nested callbacks still refuse.
Full runtime builds require `JackLibraryOrder`; reduced builds exclude it.

204 affected Python checks pass, including ten new frontend/runtime cases. Two
fresh metadata JVM outputs match across 60 parent-oracle cases covering top and
bottom placement, repeated card names, optional sources and all choice prefixes.
All twenty prior Java regressions pass. Malformed menus and historical policy
disagreement close the session before scoring. Evidence:
`E:/spellbench-xmage-all-20261002/jack-library-order-001`. Fixtures retain the
pinned original ordering loop and inherited selector but script physical card
placement. Native zone changes, replacement events, source/knowledge lifecycle,
scry/surveil arrangements and complete trained-weight games remain unqualified.
