# XMage bot coverage

Snapshot: 2026-10-04 UTC. This is the delivery inventory, not a leaderboard.
The intended outcome remains reproducible public ratings for every distinct
playable family. No new bot rating has been produced by this preparation slice.
The machine-readable status and alias relationships are in [coverage.json](coverage.json).
The prepared [native benchmark](../../benchmarks/fdn-native-v1/benchmark.json)
has nine distinct variants and two anchors, with a full round robin across the
sixteen FDN decks. Its 600-second decision and engine-step clocks apply to all
entries. It has no rated run. The historical `fdn-mirror-v0` definition is unchanged.

| Family | Available inputs | Wiring | Qualification, rating and publication |
|---|---|---|---|
| XMage MAD / CP7 | Pinned public source; ten UI skills | Kit H1/H2 plus explicitly named `mad7-s1` to `mad7-s10` fair variants | Native benchmark passes 48 natural complete-game throughput checks with identical 1/4/8-worker outputs; rated run pending |
| XMage MCTS | Pinned public source | Existing H3, labelled fixed-iteration sampled-world variant | Included in the same passing native benchmark qualification; unrated |
| DraftZero Exp1 gen0, gen10, gen33 | All three public weights downloaded and hash verified | All three complete a six-visit FDN game and same-seed replay; a distinct released final-evaluation fair profile is wired through priority, dialogs and combat | Published-profile full games, broader FDN coverage and benchmark qualification unfinished; unrated |
| MageZero v0.2 | Public model/vocab source and both engine bundles pinned | Original priority and dialog search pass native synthetic checks; typed combat, mixed bridge, public frontend and deck-bound confined runtime are wired | Compatible trained weights and author settings absent; native combat/mixed checks and full-game qualification pending; unrated |
| Jack's XMage RL | Archived April snapshots plus current policy and mulligan files verified in five profiles | All five current pairs pass strict loading and repeated inference on actual permitted Java priority features; paired inference, private original chooser, permitted mulligan features and original mode component are wired; Standard retains its legacy Q mulligan rule | Native chooser, mulligan and mode checks, custom mana filters, exact decks and complete callback adapter unfinished; unrated |

## Native policies and aliases

The engine source pin is `fd40ad5c29a92cef824cf12ba6d0e4daa25db975`.
`ComputerPlayer7` is the playing MAD policy. `ComputerPlayer6` supplies its
search and combat implementation and inherits the base player's pass-only
priority method. The base `ComputerPlayer` supplies shared dialog heuristics.
These supporting classes are not separate released playing policies.
`ComputerPlayerControllableProxy` uses CP7 during ordinary automatic play and
can forward control to a human. `ComputerDraftPlayer` drafts cards and concedes
ordinary games. Human control and draft selection are outside the match roster.

The upstream UI offers skills 1 to 10. CP7 uses depth `max(4, skill)` and a
wall-time allowance of `3 * skill` seconds. The kit runs synchronously with
5,000 nodes, 2,000 options and 20,000 operations, so its variants have distinct
names and configuration hashes. Skills 1 to 4 share depth 4, and their unused
wall-time field does not make four distinct kit policies. H1 uses skill 6;
`mad7-s6` represents the same search policy under its explicit fair-variant name.
H2 votes across four worlds. These relationships must be deduplicated in a
rated roster rather than counted as extra independently trained bots.

The upstream MCTS allowance is `2 * skill` seconds. H3 changes that to 30
iterations, with its published rollout, operation and combat-prefix caps.
Its entry identity and description must retain those changes.

The inherited kit recorded 2,176 natural-ending soak games with zero validator
violations. `kit/evidence/soak/findings.json` retains renamed-card reconstruction
failures, deadline-dependent replays and a temporary-directory leak. Version
0.3.0 has targeted passing rename and shutdown checks; see
[the repair evidence](kit/evidence/native-repairs-20261003.md). The historical
deadline-dependent profile is unchanged; the new 600-second profile passes
the matched complete-game qualification described below. Rated play is pending.
The new runtime completed 24 serial games, all natural and without validator
violations. A missing report module stopped that attempt before the parallel
comparison. The rows and restored report are retained, and a repaired runtime
checks report dependencies before preflight and checkpoints completed rung
timings. Those earlier rows remain functional evidence. A later completed
48-game 1/4/8-worker comparison passes natural outcome and output-identity
checks for the actual frozen benchmark. The guard selects eight workers.
Its matched batch speedup is 1.354x, with a planning projection near 23 hours
for the full round robin. This is throughput evidence; there is no rated run.

## Learned inputs and associations

[releases.json](releases.json) pins public source revisions, checkpoint lengths
and SHA-256s, the original feature-vocabulary code, and Exp1's 1,024-slot FDN+SPG
action vocabulary. Checkpoints remain opaque on the host and are loaded with
`weights_only=True` inside a container with no network, read-only inputs, CPU
and memory bounds, and no host credentials or Docker socket.

DraftZero's public release has generations 0, 10 and 33 at Hugging Face revision
`c0ac902361c041f986f429ad9d42e7b92494741f`. Exp1 uses a 2,000,000-bin feature
space. MageZero v0.2 uses 2,147,483,647 bins and 128-slot heads. The runtime
refuses to reinterpret one encoding as the other. Private training generations
and later experiment source are not additional public pretrained releases.

Both MageZero release ZIP directories were inspected without extraction:
v0.2 has 179 files and 41 deck files; v0.1 has 166 files and 29 deck files.
Neither contains `.mz`, `.pt`, `.pt.gz`, `.pth`, ONNX, safetensors or pickle
weights. Their deck lists do not establish which trained models exist.
The current catalogue has 16 Standard opponent decks, including the 62-card
`Standard-MonoU` list. Known training examples include UWTempo,
Standard-MonoU and Standard-MonoB. Every supplied model must retain its own
deck association; an arbitrary Standard deck cannot be substituted.

The useful author handoff is an exported `.mz` or `model.pt.gz`, the exact
deck list and version, source/encoder revision, vocabulary or ignore-list
metadata, and inference/search settings. For raw weights, record the author's
deck-association evidence. The isolated loader now streams the original `.mz`
layout, verifies its deck/version metadata, and refuses unexpected members.
Its export check uses synthetic initialized weights, not a pretrained policy.
The MageZero public frontend and confined runtime are wired; native combat and
full-game qualification remain unfinished. Author-supplied local
checkpoints have an explicit provenance route without invented download URLs;
see [the input instructions](../../integrations/xmage-models/README.md).

The original MageZero priority encoder now passes two real native executions:
468 features and three policy slots repeat identically. Sixteen sampled hidden
worlds per execution include different hidden cards while preserving encoded
features; changing visible own life changes the encoding. This is a priority
encoder check without trained weights, original search or complete games.

Jack's archive contains 43 snapshot files in the five named profiles visible
in its current manifest: Pauper-Affinity, Pauper-Elves, Pauper-Rally,
Pauper-Wildfire and Pauper-Standard. The accompanying move note's older count
differs. All ten current policy and mulligan files were copied opaquely from
Haley and checked against the read-only 2026-10-03 size/hash inventory. Every
current pair passes isolated strict loading and repeated finite inference
through all five candidate heads, the legacy actor and its paired mulligan
network. An archived Elves policy also passes the original candidate-head
contract. Standard requires the older two-Q mulligan source and decision rule;
the other four pairs use the April single-logit source. Both source revisions,
Java encoder/callback sources and offline embedding caches are pinned.
Synthetic probes do not establish cache coverage, encoder fairness or exact
deck association. Unassociated entries cannot launch `serve`. Private source
and weights stay outside this public repository.

The April base-state encoder now has a private staged fair port with an explicit
acting viewer, named permitted entity tokens and public-alias ordering for known
library cards. It replaces the original active-player perspective and whole-library
encoding. Build 039 compiles its Java bridge, read-only embedding lookup and
original priority candidate features. Real active and nonactive priority views
pass hand/ownership and offered-choice checks; eight different hidden samples
per view leave state and candidate features identical. All five current
checkpoint pairs now repeat isolated inference on those real features; Elves
uses its own cache fixture. Offered choices and masked padding pass. Exact
deck associations, original game selection, other callbacks and full games
remain unfinished. The receipts are in
[the neural evidence](models/evidence/2026-10-03-neural-inputs.md).
Preparation hashes four historical 60-card Pauper candidate decks with 15-card
sideboards. The global embedding cache covers their main decks; the Elves cache
also covers every sideboard name. The historical `Pauper-Standard` registry
selects that four-deck Pauper pool. These records do not yet bind any copied
checkpoint to its actual training deck version.

## Next delivery steps

Finish the game adapters, native qualification, and learned encoder/action
qualification. The tested Exp1 decision slices disable opponent-hand encoding,
reconstructs a world from permitted inputs and uses explicit compatibility
helpers. Their micro-decision history is empty; the direct-policy connector does not run
DraftZero's original MCTS. Those changes must remain visible in any future
entry identity and description.

The separate search bridge ports Exp1's original PUCT and dialog scripts.
Generation 33 repeats searches for priority, targets, binary choices,
numeric amounts, named colors and a visible library selection with an earlier recorded choice through the
confined checkpoint. Original Exp1's restriction on finishing a library search
before the target minimum remains explicit in the result. Its variant uses fresh
sampled-world trees, synchronous inference, all trained priors, minimum visits with original legal-future stopping
and no noise. Full transition history, remaining callbacks and game qualification are open.

Use the FDN and Standard benchmarks with appropriate deck associations and
baseline anchors; add suitable Pauper support for Jack's deck-local entries.
Freeze the rated roster, schedules, seeds and clocks, collect complete
seat-swapped pairs, and retain outcome handling and uncertainty intervals.
Before substantial evaluation, refresh all three placements and reservations,
compare completed-work serial/parallel throughput, and use the supported arena
or kit qualification guard. The input fetcher and model probe are preparation
and small correctness paths; they do not launch evaluated games.

The frozen native benchmark's guarded serial/parallel qualification passed
and its local reservation released. No rated XMage games, GPU run, new training
or paid compute were launched by this task. Existing review and publication paths remain
part of the outstanding delivery.
