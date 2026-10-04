# Isolated XMage model backend

This backend prepares real neural inputs for the XMage game adapter. It does
not speak Spellbench's agent protocol or claim full-game qualification.
See [the coverage inventory](../../engines/xmage/BOTS.md) for unfinished work.

Fetch all public inputs as opaque, hash-verified files into an owned job root:

```powershell
uv run python python/tools/xmage_release_assets.py fetch --root D:/e-scratch/JOB --report D:/e-scratch/JOB/INPUTS.json
uv run python python/tools/xmage_release_assets.py archives --root D:/e-scratch/JOB --report D:/e-scratch/JOB/ARCHIVES.json
docker build --tag spellbench-xmage-models:local integrations/xmage-models
docker image inspect spellbench-xmage-models:local --format '{{.Id}}'
```

Use that observed immutable image ID, not the tag:

```powershell
uv run python python/tools/xmage_checkpoint_backend.py probe --root D:/e-scratch/JOB --checkpoint draftzero-exp1-gen33 --image sha256:IMAGE_ID --report D:/e-scratch/JOB/GEN33.json
```

Repeat the probe for gen0 and gen10. All three genuine public checkpoints have
passed loading, finite-output and repeated-inference checks. Receipts record
the input manifest hash, actual image, four read-only mounts, launch arguments,
package versions, encoding, head width, output hash and any failure. Failures
are retained. No checkpoint or upstream Python source is imported on the host.

`serve` uses the same confinement and pins. It emits a readiness line, then
accepts NDJSON requests with `id`, `features` and `encoding`. Each response
for MageZero/DraftZero contains four raw policy heads and a scalar value. Features are mapped through
the checkpoint's saved dense vocabulary with the original deduplication and
unknown-feature handling. An input with no known features is refused. Legal
candidate mapping now covers the priority, target and binary heads in
[the neural adapters](../../engines/xmage/models/README.md). The separate
original-search bridge consumes all four heads and value through this confined
process for priority, saved-anchor targets, binary dialogs and a visible library
search after a recorded earlier choice. Remaining history, callbacks and full games still need the
complete game adapter.

All three public checkpoints have completed a six-visit FDN UR game against
heuristic and its exact-seed replay, naturally and without validator violations.
Both primary stores and the decision/choice streams excluding clocks match.
That single-game diagnostic exercises priority, targets, attacks and blocks;
Broader callbacks, decks and released search settings remain
unqualified. See [the retained evidence](../../engines/xmage/models/evidence/2026-10-03-neural-inputs.md).

The public launcher also wires `--play-profile published-exp1-final-eval-fair-v1`
with the released 96-visit, 12-second final-evaluation settings. It accepts the
original source-time stopping rule below 96 visits and enables only the binary
prior. This distinct identity records the disabled opponent-hand encoder,
fresh-tree synchronous port and CPU float32 inference change. Native full-game
and throughput qualification for this profile are pending. Its pinned source
derivation and runtime instructions are in [the model adapter documentation](../../engines/xmage/models/README.md).

MageZero v0.2 source is wired as a separate architecture. A supplied weight
needs a pinned manifest entry, a deck ID and deck-association evidence before
it can launch. The loader requires the recorded wide hash range and strict
128-slot model shape. Its source contract passed using synthetic initialized
weights only. No actual pretrained MageZero checkpoint has been qualified;
complete game play remains unfinished.

The v0.2 Java encoder is now separately staged with
`xmage_model_build.py --magezero-inputs INPUT_ROOT`. Its original feature and
128-slot action hashes are preserved alongside Exp1's separate namespace.
`spellbench.kit.xmage.MageZeroEncoderMain` encodes permitted priority records;
remaining callback families are refused. The saved feature result can be
passed to `xmage_neural_decisions.py --architecture magezero-v02` with the same
record and an author-supplied pinned checkpoint. That decision path recomputes
the actual own decklist digest and checks it against the model's association
before starting confined inference. Two actual native encoder checks repeat
identically, preserve hidden-sample invariance and detect visible life changes.
Actual-weight qualification and original search remain unfinished.

The inspected v0.1 and v0.2 public engine bundles contain no pretrained
weights. Author delivery needs the trained `.mz` export or raw weights, the
exact associated decklists, the engine and encoder source revision, and the
search configuration. The v0.2 release changes the feature hashing and is
incompatible with v0.1 models. Keep those versions separate. An author export
can enter the existing hash-pinned isolated loading path as soon as those
inputs arrive; an exact deck association is still required before serving.

Jack reported no known additional checkpoint locations on October 3. A
concise author request is:

> Could you share MageZero's publicly distributable pretrained models,
> preferably the original `.mz` exports, with each model's exact decklist?
> Please include the compatible engine and encoder revisions, feature and
> action vocabularies or ignore metadata, and the inference/search settings
> used to play. We are wiring these into Spellbench and need those details to
> preserve the actual policy and its deck association.

For an author-supplied `.mz` export, stage the opaque file in an owned input
root and add its asset to an external copy of `releases.json`, then add that
asset ID to `inference_backends.magezero-v02.checkpoints`. Record these fields:

```json
{
  "id": "magezero-author-deck-version",
  "filename": "author-export.mz",
  "kind": "checkpoint",
  "transport": "local-file",
  "provenance": "Author and source of the supplied export",
  "bytes": 123,
  "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256",
  "checkpoint_format": "magezero-mz",
  "deck_id": "sha256:REPLACE_WITH_SPELLBENCH_CANONICAL_DECKLIST_DIGEST",
  "deck_association_evidence": "Author confirmation associating this model with the pinned deck",
  "export_metadata": {"deck": "EXACT_EXPORT_DECK_NAME", "version": 1}
}
```

Compute `deck_id` with `spellbench.digests.deck_id` over the exact associated
`[{"name": "CARD", "count": N}, ...]` rows. It hashes normalized canonical deck
rows, so a raw deck file hash is not interchangeable with this identifier.

Replace all placeholders with observed values. Pass the external manifest with
`--manifest` when probing or serving. The bundle must contain exactly
`metadata.json` and `model.pt.gz`; its deck name and integer version must match
the manifest. Members are streamed inside the container without extraction,
and weights still use `torch.load(weights_only=True)`. The metadata's deck name
alone does not establish association with an exact deck list. Extra, duplicate,
linked, encrypted or oversized metadata entries are refused.

`MageZeroSearchMain` and `xmage_magezero_search.SearchSession` connect the
original 128-slot priority tree and replayed target, binary, numeric, named
and spell-mode roots to that confined backend. Dialog roots require a saved
own priority anchor and explicit public replay history. The original callback
must match the whole received observation before inference. Pass an explicit
settings object containing every original search parameter and head flag.
`ORIGINAL_DEFAULT_SETTINGS` records the source's four-second timeout,
1000-visit budget and four disabled policy priors. The authors' actual play
configuration is still required with their weights. The deterministic bridge
requires no noise and zero selection temperature; other configurations are
refused.

`diagnostic_settings(visits)` explicitly selects a separate all-head,
minimum-visit profile. Requests and results bind the exact settings, decision,
architecture and original root visit accounting. The source time-based profile
may finish below its visit budget; the diagnostic profile must complete its
minimum visits. The original library fail-to-find restriction and unoffered
mode work remain visible in the result and visit accounting. MageZero v0.2
prepends a numeric stop option only when the mode minimum is already met;
mandatory mode roots preserve its zero-based mode ordinals. Exp1 retains its
original unconditional stop option. The typed mixed bridge now includes original
per-creature combat decisions. Native combat and mixed-operation checks, actual
pretrained native checks, full games and useful-throughput qualification remain
unfinished.

The optional private `activation_callback: true` requires `priority_callback:
true` and stages `OriginalActivationPlayer`. Its actual April activation body
refreshes ability objects, reserves tap sources and tap targets, clears payment
state, retains failed-activation forced passes and passes successful stack
actions. Original mana availability/producer filtering, nested payment context
and cast/play-ability bookmark recovery are retained in the player. The missing
fast-getter override annotation is adapted to the pinned engine's API while
preserving that method body. Training/debug file logging is excluded.

`dispatchOriginalPriority` connects persistent owner-matched `PriorityRules`
and the caller's original chooser to those activation/pass callbacks. Copies
retain the current ability and reset payment reservations as the original
copy constructor does. Strategic callbacks, original parent mana payment and
parent producer lookup are abstract requirements, so this class cannot run a
substitute strategic player. It does not assert the full copied-callback marker.
The caller still owns the permitted reconstructed world, persistent rules,
all original callbacks and shared inference/RNG. Isolated metadata checks cover
the actual dispatch, fresh activation, tap reservations/producer exclusion,
copy resets, failure cleanup, nested payment context and bookmark recovery.
Native callbacks, full player integration and games remain unqualified.
The pinned engine's `ComputerPlayer` supplies engine primitives here. The
private April ComputerPlayer6/7 inheritance and its skill-10 behavior still
require complete parent-policy integration before this can be qualified as
the original player; the declared parent skill is retained as metadata.

`python/tools/xmage_magezero_runtime.py` serves the public frontend with that
mixed bridge. Supply the external copy containing author weights as `--manifest`
and the unchanged repository manifest as `--public-manifest`. The latter is the
manifest used to compile and verify the MageZero model build. Additional weights
must retain every public source and encoder pin; legacy ONNX exports are refused.
Every original parameter must be present in the `--settings` JSON file. Those
settings, the exact deck digest, checkpoint, build, image and frontend sources
determine the bot version. `--print-identity` checks pinned inputs without starting
a model or a JVM. Run serving only through the guarded arena launcher and include
the frontend's private database copy in the job's storage manifest:

```powershell
python python/tools/xmage_magezero_runtime.py `
  --manifest AUTHOR_RELEASES.json --public-manifest engines/xmage/releases.json `
  --settings AUTHOR_SETTINGS.json --root OWNED_INPUT_ROOT --checkpoint MODEL_ASSET_ID `
  --image sha256:PINNED_IMAGE_SHA256 `
  --java PINNED_JAVA --java-sha256 JAVA_SHA256 --engine REVIEWED_ENGINE_ROOT `
  --model-build MAGEZERO_BUILD_ROOT --model-build-sha256 BUILD_MANIFEST_SHA256 `
  --db-file PINNED_CARDS_DB --db-sha256 DB_SHA256 --work OWNED_WORK_ROOT
```

The runtime needs a build containing `MageZeroSearchBridgeMain` and both search
and combat entrypoints. At game start, the actual own decklist must match the
checkpoint association before confined inference starts. The public lifecycle
retains only replayable visible history and closes each per-game session. Local
tests cover both stopping profiles, declaration-plan reuse, cleanup replay,
startup failure and resource cleanup. These tests use synthetic weights or model
peers and establish wiring; actual author weights and full-game qualification
are still required.

Raw `.pt.gz` and `.pt` inputs use `checkpoint_format` values `torch-gzip` and
`torch`. They require the same exact deck hash and association evidence but no
`export_metadata`. Public download assets still require an HTTPS source.
Local checkpoint, source-code and feature-data assets require recorded
provenance and an already staged, hash-matching file. The preparation tool
never downloads or deserializes a local input.

Jack's five current policy/mulligan pairs also passed strict loading and
repeated finite inference. Their weights, historical private sources and
embedding caches stay outside this public repository. Standard's mulligan
network has two Q outputs and uses the original `Q_keep >= Q_mulligan` rule.
The other four pairs use the April single keep-logit architecture. The first
Standard probe correctly refused the mismatched April source; that failed
receipt remains part of the evidence.

For these pairs an external manifest's `inference_backends.jack-rl-april`
configuration supplies `model`, `mulligan_source`, `state_encoder`,
`callback_source` and `checkpoints` asset IDs. Each policy checkpoint supplies
`mulligan_checkpoint`, `embedding_cache` and `checkpoint_format: "torch"`.
A legacy policy can override `mulligan_source` and set
`mulligan_format: "keep-mull-q"`; the default is `"keep-logit"`. All seven
inputs have individual hashes and read-only mounts. The saved configuration
and tensor shapes construct the original networks, then strict loading checks
every parameter. There is no partial load or randomly initialized fallback.

Jack probes use synthetic features without playing Magic and do not require
a deck association. `serve` requires the policy's exact `deck_id` hash and
`deck_association_evidence`. Each request's encoding identity includes the
state encoder, callback source, embedding cache and mulligan source/format.
Candidate requests contain `sequence`, `padding`, `token_ids`, `head`,
`candidate_features`, `candidate_ids` and `candidate_mask` and use one of the
original `action`, `target`, `card_select`, `attack` or `block` heads.
`legacy_actor` uses the original 15-action head; `mulligan` uses its original
explicit features, hand IDs and deck IDs. Shapes, finite feature bounds,
vocabulary ranges and boolean masks are checked before inference. These
checks do not qualify the Java feature encoder, cache coverage or exact deck
association. The complete fair game adapter and ratings remain unfinished.

The private April base encoder now has a staged fair port. The original picks
the active player, uses that perspective for ownership features, and reads
the selected player's whole library. The port requires an explicit acting
viewer and a map of named, permitted object references. Anonymous entities
and sampled hidden library cards cannot produce identity features. Known
library tokens use public object-alias order. These changes are part of the
variant's identity and need actual game qualification.

`xmage_model_build.py --jack-inputs PRIVATE_ROOT --jack-manifest PRIVATE_MANIFEST`
adds the private staged encoder to the reviewed model build. Both arguments
are required; the source must match the recorded April hash. Private generated
source remains in that owned build root. `JackEncoderMain` accepts recorded
priority decisions or a private NDJSON pipe, and returns base-state features
bound to the decision hash. It checks the staged method and pinned embedding
cache before reporting readiness. The original priority candidate features
are implemented, bound to offered choices and compiled against the reviewed
engine. `JackEncoderCheck` passes real active and nonactive priority fixtures
for hand perspective, ownership, hidden-sample invariance, candidate padding
and a visible life change. Other callback families remain unfinished.

`pinned_jack_feature_probe_command` runs the confined `jack_feature_probe.py`
helper on a fixed hash-pinned Java fixture. All five real policy/mulligan pairs
repeat finite normalized priority inference with masked padding; Elves uses
its own embedding-cache fixture. This diagnostic probe preserves the refusal
to serve checkpoints without deck associations. It does not qualify original
full-policy selection or complete games. Source and output hashes are retained
in [the evidence](../../engines/xmage/models/evidence/2026-10-03-neural-inputs.md).

Embedding lookup uses one explicit hash-pinned cache with 32 finite numbers
per card. It performs no network lookup or file writes and refuses missing
names. Preparation verified 114 global and 174 Elves-cache entries. The global
cache covers the main decks of all four historical Pauper candidates; it lacks
some sideboard names. The Elves cache covers all four candidates including
sideboards. Those coverage checks do not establish which cache or exact deck
belongs to a copied checkpoint. The historical `Pauper-Standard` registry
selects a four-deck Pauper pool. Its current checkpoint association is pending.

The optional `card_set_callback: true` private staging flag adds a ninth
source body for the original `chooseTarget(Outcome, Cards, TargetCard, Ability,
Game)` callback. It requires `target_callback` and the existing mode, dialog
and payment prefix rules. `JackCardSetEncoderMain` takes the eight general-target
arguments followed by the staged card-set rules SHA-256. The owned
`xmage_jack_card_sets.CardSetSession` retains the original provided-card filter,
library/hand name groups, first available representatives, `card_select` head,
STOP gates, first 64 groups and minimum completion. All physical copies are
bound to offered public actions.

The original callback chooses a physical copy with a fresh unseeded Java RNG.
This explicitly declared fair variant uses a separate game-owned Python
MT19937 stream, seeded from SHA-256 of
`spellbench-jack-card-copy-mt19937/v1\0` followed by canonical `game_start`
bytes. A singleton copy consumes no copy RNG; a single original group consumes
no neural inference or chooser RNG. The original Java neural chooser stream
is unchanged, and recorded prefix choices consume neither stream. The
inherited `choose(Cards)` callback remains separate from this neural callback.
Private native execution, other callbacks, incompatible public/original ranges,
exact deck associations and complete games remain unqualified.

The optional `parent_card_callback: true` flag adds six private bodies for the
separate inherited `choose(Cards)` callback. It requires the original neural
card and prefix rules and all eight pinned April parent sources, including the
ComputerPlayer6/7 inheritance. The original base loop, selector, comparator
and permanent scoring are retained. This path assumes empty planning queues,
preserves score/name ordering and UUID ties, and applies the original
`target.add`. It does not substitute the current pinned engine's parent policy.

`JackParentCardEncoderMain` takes the nine card-set arguments followed by hashes
for the parent rules, selector, comparator, permanent scorer, scoring helper and
original ability scoring table.
`xmage_jack_parent_cards.ParentCardSession` binds the determined choice to the
complete offered public card set without model, chooser or physical-copy RNG.
Recorded parent prefix choices must match the original policy. An original
implicit completion maps only to an offered legal STOP. The parent pipe accepts
earlier neural card choices but refuses a neural card root. Native execution,
queued planning behavior, other callbacks, exact decks and full games remain
unqualified.

The optional `combat_callback: true` flag adds the original April `CombatRules`
body independently of the target-prefix flags. `JackCombatMain` takes the
embedding path and hash, original state and candidate hashes, and staged combat
rules hash. Its private pipe requests paired inference and the shared original
chooser for each original combat round. Attacks retain the first 63 creatures
and final DONE, followed by separate defender choices. Blocks retain the
original attacker power ordering, legality filters and blocker removal. Both
use one cached permitted base state per callback. The full sequential chooser
draw is retained even after DONE, preserving the game's original RNG stream.

`xmage_jack_combat.CombatSession` owns this pipe, paired model and chooser with
one shared clock. Its returned `JackCombatPlan` binds the actual declarations
to consecutive public group substeps and refuses changed or rewound public
state. Nested interactive or mana-payment combat callbacks refuse. This is
wiring and source staging; native execution, exact decks and complete games
remain unqualified.

The optional `london_callback: true` stages `LondonRules` independently. The
engine's London loop calls the original policy with a one-card target on each
iteration. `JackLondonMain` ranks the shrinking whole hand for every card,
uses the original `card_select` head and complete sequential chooser draw,
applies the last ranked card to the target, and moves it to the library before
the next callback. The original default-enabled base-cache signature is
extracted from the private source. A singleton bypasses inference and RNG.

`xmage_jack_london.LondonSession` shares the paired model, original chooser and
clock. Its `LondonPlan` binds these repeated picks to consecutive public
bottoming substeps and rejects changed hand references or reused picks. Moved
hand aliases are excluded from newly built known-library features. Original
model-error fallback becomes refusal. Native execution, actual paired-weight
bottoming, exact decks and complete games remain unqualified.

The container is limited to one CPU, 3 GiB RAM, 64 processes and a 64 MiB
ephemeral temporary filesystem. It has no network, a read-only root filesystem,
no privileges and no host socket. Probe timeout cleanup removes only the
launcher's uniquely named container. Large evaluated workloads must still
pass the existing useful-throughput guard.
### Jack's original priority rules

The private Jack input manifest can opt into `priority_callback: true`. The
source stager then emits `PriorityRules.java` and records both the original
callback identity and the staged rule hash. Altered private source and
nonboolean flags refuse staging. The private source remains outside public Git.

This component preserves the April default settings: base-state, playable and
alternative-cost caches enabled, a 256-entry alternative-cost cache, activation
fast path enabled, simulation validation enabled, and no-clone lookup disabled.
It calls the original two-argument playable API. That engine API may already
collapse equal-text abilities before Jack's source-specific mana deduplication;
the separate offered-mana feature lookup does not change this policy behavior.

The extracted rules retain activation tests, validated alternative-cost keys,
the first-64 selection bound, pass-only selection without a chooser call, and
the original turn-step dispatch. Simulation copies must implement the staged
`PriorityRules.OriginalCallbacks` contract with the pinned callback source
identity. Missing copied callbacks refuse instead of using a substitute bot.
The caller still owns the permitted reconstructed world, the game-owned neural
chooser and application of actual original callbacks.

`engines/xmage/tests/priority-rules/JackPriorityRulesCheck.java` runs the actual
staged rules on isolated metadata fixtures. It checks option order and
deduplication, fast-path rejection, cache reuse and state changes, the 64-slot
bound, twelve turn steps, alternative-cost enumeration and actual validated
choice application, and refusal of unported simulation callbacks. It starts no
native game, card database or network. These checks do not qualify complete
priority play, native hidden-world invariance, paired weights or full games.

The private manifest can additionally enable `parent_mana_callback: true` with
`activation_callback: true`. It requires the three pinned April parent sources
and `parent_choice_source`, the pinned April `ChoiceImpl.java`. The stager emits
abstract `OriginalParentManaPlayer`, retaining the inherited payment algorithm,
producer scores, conditional and as-though tests, phyrexian recursion guard,
special mana action, unpaid-color hint and ComputerPlayer6's queued answers.
The old choice-answer helper is extracted from that same commit because the
pinned engine lacks its method. Queued answers copy; unpaid hints and the
phyrexian guard reset, as in the original constructors.

The engine's producer primitive feeds the existing original activation filters
and tap reservations. Payment calls the player's actual activation callback.
Original parent color order, map iteration, nested payment mode behavior and
random fallback are retained. Strategic callbacks and creature-type selection
remain required; this abstract component does not implement the full copied
callback marker. `JackParentManaCheck.java` executes these bodies with metadata
engine hooks, alongside the existing activation checks. No native game, card
database or model is started. Native replay, ordering/RNG qualification and
complete persistent player integration remain unfinished.

`parent_dialog_callback: true` requires both the original parent mana and parent
card-scoring options. It emits abstract `OriginalParentDialogsPlayer`, preserving
the inherited target scorer and damage/amount allocation, creature-type scan,
queued card targets and copy behavior, and mode/use/X fallbacks. The inherited
trigger, pile, replacement, constrained multi-amount and cast-ability callbacks
also retain their original bodies. The RL target-amount and Target/Map overrides
only add diagnostics to parent delegation; this stage executes that delegation
without training/debug output.

Each new path that reads a game requires its owned player and the runtime's
`requireOriginalPermittedWorld` implementation. In particular, the creature-type
library scan must run on a sampled permitted world, whose ordering can differ
from the real hidden library. The gate remains abstract until the persistent
runtime supplies its world/copy admission. Original ordering and fallback RNG
remain unchanged. `JackParentDialogCheck.java` checks actual parent bodies with
metadata engine hooks; neural overrides and the complete copied-callback marker
remain unavailable. Native fairness, RNG/replay and full-game checks are still
required before qualification or rating.

`JackPriorityBinding` takes the actual validated list from the original rules'
chooser hook and its cached permitted base state. It preserves the first 64
slots in their original order, requires a unique exact offered semantic for
each selected slot, and rejects unnamed sources, unmatched Oracle indices,
undeclared priority mana and unsupported worlds. Additional public choices
remain outside the original prefix. Public IDs and offering order do not
determine neural slot order. The frame binds the complete decision and game
start, the source identities, original action IDs, float features and masks.
Pass-only frames bypass feature encoding.

`xmage_jack_priority.PrioritySelection` reuses the paired model and the same
game-owned original Java chooser under one clock. It maps the selected original
slot to its offered public ID, preserves the pass-only inference/RNG shortcut,
and closes both components on refusal. Isolated Java and Python checks cover
these bindings; a local optional check serializes the actual staged private
candidate codec and cached state. This component does not execute simulation
callbacks, reconstruct a persistent original player, activate abilities or
qualify complete games. Those integrations and native replay checks remain
unfinished.
