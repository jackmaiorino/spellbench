# DraftZero Exp1 current-source build

PR #141's Brineborn correction is preserved alongside merged PR #186. It changes only the model copy of the exactly audited register row. The native register and other event-data refusal rules remain intact.

The Exp1 build uses JDK 23.0.1 and reviewed engine manifest `3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93`. Its public encoder/search inputs are the original pinned release. BUILD.json SHA256 is `e10b9f088940bc91f51ff0a4cf1d96dac796d92a67bcde257dd5832000c45f20`. The runtime verifier accepts the current release manifest, all 310 class hashes, both resource hashes and the original Commons Math dependency. The additional class is `core/spellbench/kit/core/Offers.class`, already integrated on main.

| Check | Observed result |
|---|---|
| Model build through guarded spare core slots, BelowNormal | exit 0 |
| Actual public three-object Brineborn stack reconstruction/resolution | PASS: exactly one source counter; Essence Scatter target retained |
| Model build, runtime, X5 guards, qualification and rated launcher tests | 64 passed |
| GNN source/search and model build tests | 29 passed, 1 skipped |

The engine overlay and three Exp1 commands bind the observed BUILD.json. Runtime identities were recomputed using current frontend hashes and the original 96-visit/12-second published fair profile. All three checkpoint hashes, the inference image, sixteen decks, clocks, six entrants, 1,920 games and 960 seat-swapped pairs are preserved. The GNN entry is byte-equivalent as a parsed object to merged main's entry, retaining its separate model build and earlier natural-game/replay evidence.

Build custody: `D:/e-scratch/spellbench-learned-backlog-20261009/exp1-build-001`, with a hash-verified cold copy under `E:/spellbench-learned-backlog-20261009/exp1-build-001`. These are build receipts, not game or throughput qualification. No game, rating, paid allocation or GPU job ran in this refresh. Fresh natural games and exact replays for gen0/gen10/gen33, learned-workload serial/parallel qualification, the public commitment, rated block and live publication remain required under issue #36.
