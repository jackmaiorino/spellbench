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
before starting confined inference. Runtime encoder checks and actual-weight
qualification remain pending; these changes do not qualify original search.

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

The container is limited to one CPU, 3 GiB RAM, 64 processes and a 64 MiB
ephemeral temporary filesystem. It has no network, a read-only root filesystem,
no privileges and no host socket. Probe timeout cleanup removes only the
launcher's uniquely named container. Large evaluated workloads must still
pass the existing useful-throughput guard.
