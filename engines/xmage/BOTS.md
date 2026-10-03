# XMage bot coverage

Snapshot: 2026-10-03 UTC. This is the delivery inventory, not a leaderboard.
The intended outcome remains reproducible public ratings for every distinct
playable family. No new bot rating has been produced by this preparation slice.
The machine-readable status and alias relationships are in [coverage.json](coverage.json).

| Family | Available inputs | Wiring | Qualification, rating and publication |
|---|---|---|---|
| XMage MAD / CP7 | Pinned public source; ten UI skills | Kit H1/H2 plus explicitly named `mad7-s1` to `mad7-s10` fair variants | Targeted rename/shutdown repairs pass; new build and deadline replay unqualified; unrated |
| XMage MCTS | Pinned public source | Existing H3, labelled fixed-iteration sampled-world variant | Separate qualification pending; unrated |
| DraftZero Exp1 gen0, gen10, gen33 | All three public weights downloaded and hash verified | Isolated loading and repeated inference pass; gen33 also scores a real priority fixture | Full dialogs, combat, search and game qualification unfinished; unrated |
| MageZero v0.2 | Public model/vocab source and both engine bundles pinned | Isolated source loader prepared; tested with explicitly synthetic initialized weights | No public pretrained weights found; full fair adapter and qualification unfinished |
| Jack's XMage RL | Archived April snapshots plus current policy and mulligan files found in five profiles | One archived Elves snapshot passes isolated tensor/metadata inspection | Exact deck/encoder/source associations and complete fair adapter unfinished; unrated |

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
[the repair evidence](kit/evidence/native-repairs-20261003.md). Deadline replay,
new-build qualification and rated evaluation are still pending.

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
deck-association evidence. `.mz` handling and the full MageZero game adapter
remain work to finish when those inputs arrive.

Jack's archive contains 43 snapshot files in the five named profiles visible
in its current manifest: Pauper-Affinity, Pauper-Elves, Pauper-Rally,
Pauper-Wildfire and Pauper-Standard. The accompanying move note's older count
differs. Current policy and mulligan files remain on Haley. Profile names alone
do not establish exact deck hashes. Private source and weights stay outside
this public repository.

## Next delivery steps

Finish the game adapters, native qualification, and learned encoder/action
qualification. The tested Exp1 priority slice disables opponent-hand encoding,
reconstructs a world from permitted inputs and uses explicit compatibility
helpers. Its micro-decision history is empty at this slice; it does not run
DraftZero's original MCTS. Those changes must remain visible in any future
entry identity and description.

Use the FDN and Standard benchmarks with appropriate deck associations and
baseline anchors; add suitable Pauper support for Jack's deck-local entries.
Freeze the rated roster, schedules, seeds and clocks, collect complete
seat-swapped pairs, and retain outcome handling and uncertainty intervals.
Before substantial evaluation, refresh all three placements and reservations,
compare completed-work serial/parallel throughput, and use the supported arena
or kit qualification guard. The input fetcher and model probe are preparation
and small correctness paths; they do not launch evaluated games.

Jack and Haley still had healthy reserved cooling evaluation processes in the
2026-10-03 read-only inventory. No substantial evaluation, GPU run, new training
or paid compute was launched here. Existing review and publication paths remain
part of the outstanding delivery.
