# XMage bot coverage

Snapshot: 2026-10-05 UTC. This inventory records source wiring, complete-player
admission, ratings and publication separately. Source PR121 and the Kiora repair
[PR133](https://github.com/jackmaiorino/spellbench/pull/133) are merged. PR133's
reviewed head passed all six hosted checks and its tree was verified on main.
These checks do not establish actual repaired-runtime or full-game admission.
The machine-readable status and aliases are in [coverage.json](coverage.json).

| Family | Inputs and source wiring | Remaining qualification and publication |
|---|---|---|
| XMage MAD / CP7 and MCTS | Pinned native sources and nine distinct fair variants wired; the frozen native runtime completed 30 natural matched throughput rows at 1/2/5 workers | No native rated games. Complete-player admission, the full 7040-game schedule, replay and publication remain unfinished |
| DraftZero Exp1 gen0, gen10, gen33 | Three public checkpoints pinned; original search/callbacks and released 96-visit/12-second profile wired. Kiora source repair merged | Released gen33 check forfeited at actor step97. Fresh repaired runtime, actual public projection/face-down fairness, callback, natural full game, replay and learned throughput remain unqualified; zero ratings |
| MageZero v0.2 | Original encoder/search and confined runtime wired | Compatible trained exports, exact decks, encoder/vocabulary revision and play settings unavailable. Historical ONNX candidates remain unqualified; zero ratings |
| The maintainer's XMage RL | Five policy/mulligan pairs strictly loaded; original callback wiring retained | Exact checkpoint-bound decks/configurations, native serving and complete-game coverage unresolved; zero ratings |

The FDN builtin baseline is complete: 384 natural/rated games over 16 decks,
64 complete seat-swapped pairs per matchup, zero forfeits/halts/truncations and
an exact-seed game0 replay. Three builtin entries are
[verified live](https://jackmaiorino.github.io/spellbench/b/fdn-mirror-v0/).
Those builtin ratings do not admit any requested native or learned family.

The maintainer's research priority suspends new game/build/qualification launches on both
PCs until explicit research handback. No automatic compute dispatch is queued.
Missing learned inputs remain unfinished entries. For MageZero, request trained
policy/value exports, their exact associated decks, matching encoder/vocabulary
revision and evaluation/search settings. The maintainer knows of no additional weights.

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
deadline-dependent profile is unchanged. The 600-second profile completed the
historical matched qualification described below. Rated play is pending.
Earlier 24-game serial rows and the later 48-game 1/4/8-worker comparison
remain historical evidence for their own frozen source and benchmark. Their
1.354x speedup and earlier run projection do not describe the newer runtime.

Generation45 completed 30 natural rows using the same ten game indices at
1/2/5 workers in 838.113/732.032/671.373 seconds. Five workers achieved
1.24836x serial with identical primary outputs and trial ledgers. This evidence
binds source `eb27befef38e789d5bb74e2e3a97b30c479df3ce`, engine manifest
`35aea0fd4a097f2d8733f6757a54cd560000407247303940a273ed52aeee26aa`,
kit manifest `5dcc7b1ce399f43bc7752c47615e2b51fd903a62d7472715b9abaac5d3b718e0`
and the unchanged native benchmark. The
[merged receipt](https://github.com/jackmaiorino/mtg-kernel-collab/blob/54e33c5182c2187ca8fca3c5672bbf6404eca157/ARTIFACTS/spellbench-xmage-native-current-runtime-20261005.json)
retains the terminal, cleanup, frozen inputs and verified recovery references.
It does not qualify every later checkout or all matchups and decks.

The [native benchmark](../../benchmarks/fdn-native-v1/benchmark.json) retains
nine distinct variants, two anchors, 16 FDN decks and the full 7040-game round
robin with 600-second decision and engine-step clocks. The sample projects
131.29 hours for that schedule; the full matchup/deck mix may differ. Its
7200-second qualification window cannot be reused as the formal-run window.
After explicit handback, refresh eligible placement and supported guards and
reuse only compatible frozen-runtime evidence. No native rated run is complete.

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

A public historical copy, `toastblademaster-arch/mtg-rl`, contains two UWTempo
ONNX exports under `ver1` and `ver2`. Their observed Git identities, lengths
and SHA-256s are pinned in [the candidate inventory](magezero-historical-exports.json).
Only opaque streaming hashes were computed; the graphs were not deserialized
or executed. Different exported bytes do not establish distinct trained bots.
The pinned exporter describes ONNX export as unsupported and permits an
uninitialized export after a checkpoint load fails. Training provenance, exact
decklists, matching Java encoder/search revisions and play settings remain
unknown. These candidates remain unfinished and are not qualified for the
current v0.2 adapter.

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

The maintainer's archive contains 43 snapshot files in the five named profiles visible
in its current manifest: Pauper-Affinity, Pauper-Elves, Pauper-Rally,
Pauper-Wildfire and Pauper-Standard. The accompanying move note's older count
differs. All ten current policy and mulligan files were copied opaquely from
The compute host and checked against the read-only 2026-10-03 size/hash inventory. Every
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

The maintainer's permitted priority feature pipe follows the received public action list.
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
[the priority fidelity comparison](models/evidence/2026-10-04-maintainer-priority-fidelity.md).

The maintainer's original frontend now connects London bottoming through the actual
player callback. It ranks the shrinking whole hand on each engine one-card
callback, retains each complete sequential draw and the original base-cache
signature, and moves each selected card to the bottom before the next ranking.
The complete sequence binds to Spellbench's upfront public group. Later substeps
bind unchanged observations and remaining menus without another session or model
call. All 150 affected Python checks and two identical normalized JVM runs pass
for 1/2/7-card hands. Card movement in these checks is a metadata fixture;
native movement, trained-weight bottoming and complete games remain unqualified.
The earlier component evidence remains in
[the London wiring evidence](models/evidence/2026-10-04-maintainer-london-wiring.md).

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
inference. `MaintainerReplayOpponent` is a non-playing reconstruction helper, with no
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

The maintainer's original attack and block loops now have a separate private staged port
and connect to the original frontend's game-owned session through `MaintainerCombatPlan`.
Root callbacks retain DONE-last full sequential selection, separate defender
choices, descending attacker-power block order and blocker removal. Subsequent
public declaration substeps reuse the resulting plan, checking its group and
public state without another model call. Unrecorded nested combat callbacks
refuse before additional inference. All 250 affected Python checks pass; two
normalized combat metadata JVM outputs match, with prior callbacks also passing.
The root binding now records the engine's complete creature slot schedule before
inference, including each extra block slot. The frontend verifies that schedule
on every substep. The maintainer's original policy assigns a blocker once and removes it
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
See [the combat delivery evidence](models/evidence/2026-10-04-maintainer-combat.md).

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
baseline anchors; add suitable Pauper support for the maintainer's deck-local entries.
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

The maintainer's original replay verifies permitted library positions against the
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

Divided-target choices now expose the complete unchanged inherited allocation as
target picks followed by a bound amount group. Stack observations retain the
wire's partially selected targets and partially assigned amounts. Historical
choices must match the original policy; hidden identities and changed public
state refuse. 120 metadata cases, two identical fresh JVM outputs, 22 existing
Java regressions and 222 affected Python checks pass against a complete runtime.
Multi-amount/combat distributions, native targeting/replacement events and full
trained-weight games remain unqualified. This adds no rated or published entry.
