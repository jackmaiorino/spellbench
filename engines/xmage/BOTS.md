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
| MageZero v0.2 | Public model/vocab source and both engine bundles pinned | Original priority and dialog search pass native synthetic checks; typed combat, mixed bridge, public frontend and deck-bound confined runtime are wired | Native synthetic combat/mixed checks pass; compatible trained weights and author settings absent; full-game qualification pending; unrated |
| Jack's XMage RL | Archived April snapshots plus current policy and mulligan files verified in five profiles | All five current pairs pass strict loading and repeated inference on actual permitted Java priority features; paired inference, private original chooser, mulligan, mode, original binary/X, named-source spell targets, general cost/object targets and original provided-card components are wired; provided-card selection retains name groups, representative features and the card_select head with a separately labelled seeded physical-copy stream; a distinct inherited card pipe retains the original April sorting helpers, UUID ties, target.add and empty planning queues without neural or copy RNG; optional automatic mana replay adds original producer filters, tap reservations, nested payment context and engine choices; modes retain original cost flags and legality; Standard retains its legacy Q mulligan rule | Native source checks including target/card ordering, STOP, prefix and chooser/copy application, modes with costs and automatic mana payment, other callbacks, exact decks and complete game adapter unfinished; unrated |

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
The MageZero public frontend and confined runtime are wired. Native synthetic
attack, block and mixed-bridge checks now repeat identically and bind the actual
wire declarations. They used no pretrained weights. Full-game qualification
remains unfinished. Author-supplied local
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

Jack's permitted priority feature pipe follows the received public action list.
The original priority player separately constructs, deduplicates and validates
its options, includes individual mana abilities, and dispatches by phase with
different action/pass behavior. The production bridge now enters those original
policy steps and retains their activation state. Binary, X, spell-mode, named Choice
and general target and provided-card picks replay that saved activation through the original player.
Targets retain sequential mutation, same-name direct returns, STOP and 64-slot
limits; recorded prefixes add no policy draw. Metadata checks pass for visible
spell, cost and object wire forms with the acting viewer's actual named source.
Provided-card replay retains original name groups, representative features, physical
copy selection and the card_select head. Inherited picks enter the original sorting,
queued-target and target.add paths without neural draws. Recorded card prefixes
add neither model nor physical-copy draws; sequential groups and STOP checks pass.
All 93 affected Python checks and two identical normalized card metadata JVM runs
pass. Original combat now connects through the whole-group path described below.
Native priority/resolution qualification remains open. The guarded
runtime is connected; the full player remains unqualified. Existing paired-network
feature checks retain their tested scope; see
[the priority fidelity comparison](models/evidence/2026-10-04-jack-priority-fidelity.md).

Jack's original frontend now connects London bottoming through the actual
player callback. It ranks the shrinking whole hand on each engine one-card
callback, retains each complete sequential draw and the original base-cache
signature, and moves each selected card to the bottom before the next ranking.
The complete sequence binds to Spellbench's upfront public group. Later substeps
bind unchanged observations and remaining menus without another session or model
call. All 150 affected Python checks and two identical normalized JVM runs pass
for 1/2/7-card hands. Card movement in these checks is a metadata fixture;
native movement, trained-weight bottoming and complete games remain unqualified.
The earlier component evidence remains in
[the London wiring evidence](models/evidence/2026-10-04-jack-london-wiring.md).

Original priority state now carries the complete inherited target queue through
root receipts, the public frontend, private serving and activation replay.
Entries retain their order and duplicates as complete named visible references.
Restoration replaces the inherited queue before activation, with no model or
chooser draw. Missing, changed or hidden entries refuse. All 276 affected Python
checks and two fresh metadata JVM outputs pass, including actual inherited card
queue consumption. Immediate activation continuation is now connected as described
below; unrecorded resolution transitions and complete games remain unqualified.

Immediate next-priority requests reconstruct the saved activation world, replay
the complete recorded callback prefix without policy or copy draws, and finish
the actual original activation body. Passes from that body and the original phase
dispatch become the exact offered public pass; otherwise the original policy
dispatch chooses the next action on the completed world. Changed observations,
unrecorded callbacks and turn or phase transitions refuse. All 293 affected Python
checks pass, and two normalized metadata JVM outputs match across 0/1/2 callback
prefixes, stack and phase passes, cleanup, fresh dispatch and failure closure.
The metadata activation fixture does not qualify native ability legality,
native resolution execution, nested combat callbacks or complete games.

Saved passes on a visible nonempty stack now resume the reconstructed game toward
the original resolving callback or next priority dispatch. Public passed-seat
facts determine the one permitted opponent pass. Recorded callback prefixes replay
without policy or physical-copy draws. An extra or reordered priority, opponent
choice, unrecorded phase transition or incomplete resume refuses before further
inference. `JackReplayOpponent` is a non-playing reconstruction helper, with no
leaderboard entry. All 329 affected Python checks pass, and two normalized JVM
outputs match for resolving X, binary prefixes, opponent passes and fresh priority.
These fixtures script resume and stack contents; the native event loop and stack
legality still require qualification. Library-position transport, nested combat
callbacks, other phase transitions and complete games remain unfinished.

End-step passes also connect to fixed cleanup discard groups from the active
player's named hand. The bridge requires the same turn, an empty stack, both
players passed, no priority seat, a source-free discard context and an exact
consecutive group prefix. The actual `TargetDiscard`, cleanup phase, own hand and
range must match before the original target chooser runs. Earlier picks mutate
the actual target without extra draws. This uses the original `target` head and
same-name direct returns. All 365 affected Python checks pass; two metadata JVM
outputs match across one to three discards and every prefix. Native cleanup remains
unqualified under the research resource hold.

Callback reconstruction now conditions a separate sampling observation on named
own-library search, look and reveal facts. The root observation and admitted root
aliases retain their earlier visibility. A card's first shown position constrains
sampling; subsequent positions are replayed by the engine. Conflicting identities,
positions, capacity or permitted deck composition refuse before inference. New
positional facts after a library-size change still require position transport.
All 366 affected Python checks pass. Two fresh metadata JVM checks cover the real
sampler, hidden-read traps, root feature exclusion, actual current-look admission,
and original forced/neural target choices with current permitted features. Native
reconstruction, shuffle/movement histories and complete games remain unqualified.

Jack's original attack and block loops now have a separate private staged port
and connect to the original frontend's game-owned session through `JackCombatPlan`.
Root callbacks retain DONE-last full sequential selection, separate defender
choices, descending attacker-power block order and blocker removal. Subsequent
public declaration substeps reuse the resulting plan, checking its group and
public state without another model call. Unrecorded nested combat callbacks
refuse before additional inference. All 250 affected Python checks pass; two
normalized combat metadata JVM outputs match, with prior callbacks also passing.
The root binding now records the engine's complete creature slot schedule before
inference, including each extra block slot. The frontend verifies that schedule
on every substep. Jack's original policy assigns a blocker once and removes it
from its pool, so any remaining slots decline without changing the assignment
or making another model call. All 265 affected Python checks and two fresh JVM
outputs pass for limited/unlimited block capacity, unchanged draw counts,
held/rendered block observations and rejection of unexpected slots.
Fixtures supply metadata legality and declarations. Native legality and
multi-block games, nested callbacks, actual trained weights and complete games
remain unqualified.

The earlier separate combat component retains its private staged port
and paired-policy transport. It retains DONE-last sequential selection, the
separate defender round, descending-power attacker order, blocker filtering and
removal, and one cached base state per callback. The game-owned original chooser
finishes its full sequential draw even when DONE appears earlier. A plan binds
the original declarations to consecutive offered wire substeps. Nested combat
callbacks refuse until qualified. Source staging preserves all fifteen earlier
private bodies byte for byte; native combat and complete games remain unfinished.
See [the combat delivery evidence](models/evidence/2026-10-04-jack-combat.md).

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

Jack's original replay verifies permitted library positions against the
reconstructed owner's UUID order before projection, alias admission and scoring.
Stale positions and wrong-library references refuse without fetching hidden names.
Two repeat metadata JVMs and fourteen Java replay regressions pass. Native library
reconstruction and position transport remain unqualified.

Empty-stack forward phase resumes retain the original pass/state/seeds and verify
the actual reached observation before the next priority scores. Serving and
frontend require the phase receipt. 267 affected Python checks, two repeat metadata
JVMs and fifteen Java regressions pass. Native phase transitions, turn changes,
repeated phases and intervening combat callbacks remain unqualified.

Ordinary amount prompts use the unchanged inherited chooser through source/range
binding. Earlier amounts restore and validate the reconstructed engine RNG; no
neural X or physical-copy calls are added. 284 Python checks, two repeat JVMs with
288 parent-oracle cases and sixteen Java regressions pass. Native amount prompts,
the wire candidate-limit envelope and complete trained-weight games remain open.

Inherited pile/replacement replay now preserves the original left-pile/first-effect
policies, exact physical piles and actual replacement iterator order. Implicit
replacement menus remain implicit; historical policy disagreement refuses.
310 affected Python checks, two matching metadata JVM outputs with 96 parent-oracle
cases and seventeen Java regressions pass. Native qualification and full games
remain open; no ratings or public entries have been added.

Trigger ordering now preserves the inherited first-ability chooser across the
complete wire group before XMage applies its first trigger. Physical callbacks
check the remaining order; the final singleton can bypass the chooser as it does
in the pinned engine, including across consecutive groups. Actual unsorted ability
slots, repeated instances and current or recorded public source identities bind
the menu; unknown or hidden sources refuse. Two matching metadata JVM outputs
cover 180 parent-oracle cases, all eighteen Java regressions pass, and 300 affected
Python checks pass. Native trigger execution remains unqualified.

Empty-stack forward phase resumes now reach original dialogs as well as priority.
Recorded callback prefixes preserve the saved root and reconstruction seeds;
each actual observation is compared before the current policy scores. Turn/active
seat changes, reversed or overshooting phases, unrecorded priorities and opponent
choices refuse. 259 affected Python checks, 48 matching metadata JVM cases and
nineteen Java regressions pass. Native phase execution, automatic draws and full
trained-weight games remain unqualified.

Top and bottom library ordering now runs the unchanged inherited movement loop
and exposes its final physical block as a complete wire ordering group. Top
placement reverses the physical selection order; bottom placement preserves it.
Recorded prefixes must match that original order and consume no policy or copy
draws. 204 affected Python checks, 60 matching metadata JVM cases and twenty Java
regressions pass. These fixtures script card movement; native replacements,
zone changes, scry/surveil arrangements and complete games remain unqualified.
