# DraftZero serving repair runtime

This binds the issue #36 serving repairs (temporary-effect replay, complete scry/surveil arrangements and the Uncharted Voyage hidden destination) into the benchmark definition.

One combined model build now serves all four learned entries. It was built with JDK 23.0.1 against reviewed engine manifest `3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93` at source `2645eeec5bec6bb5e1e26c1ca78c4bdd5cfd4dab`. BUILD.json SHA256 is `21b95147fe5a50a2d65ef3e94dc85c1782344d96ee7a9aa9b44a315be5b274f0` (382 classes, 2 resources). The runtime verifier accepts it for both the Exp1 and GNN architectures.

| Check | Observed result |
|---|---|
| Combined build, public-effects and arrangement native checks | exit 0; Immolator effects restored, Voyage/Lightshell Duo/Opt/Preordain plans repeated and replayed without inference |
| Witnessed effects that do not explain the board (expired effects; an extra unwitnessed pump) | world built without them and flagged `approximate:unexplained_characteristics`, as before this PR, instead of a seat failure |
| Hosted XMage reviewed build at `abe73ee` | passed, including both new native checks |
| Saved diagnostic Uncharted Voyage callback (game 1792, seat step 77) | full callback observation comparison passed and reached the original inference boundary; zero model calls |

The definition change is limited to the build hash, the four recomputed entry versions, the build's class list and the two new helper sources. Reversing those fields recovers the previous definition exactly. Checkpoints, inference image, 96 visits/12 seconds, GNN 100 simulations, clocks, sixteen decks, six entrants and the 1,920-game / 960-pair schedule are unchanged.

Build custody: `E:/spellbench-issue36-delivery-20261025/combined-model-build-002` (cold) and `D:/e-scratch/spellbench-issue36-delivery-20261025/combined-model-build-002` (SSD). The native checks used the benchmark's pinned card database (`fcdba7e7…`); the earlier regression copy no longer exists. These are build and fixture checks, not serving, throughput or ratings.
