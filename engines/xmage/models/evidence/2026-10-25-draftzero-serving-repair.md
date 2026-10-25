# DraftZero serving repair runtime

This binds the issue #36 serving repairs (temporary-effect replay, complete scry/surveil arrangements and the Uncharted Voyage hidden destination) into the benchmark definition.

One combined model build now serves all four learned entries. It was built with JDK 23.0.1 against reviewed engine manifest `3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93` at source `abe73ee133c3e258937e7fe66f5425b8e62c3710`. BUILD.json SHA256 is `9e3770226b58bfb634233049bfa070ae448429b7313e0679b70f194aacc9d22b` (382 classes, 2 resources). The runtime verifier accepts it for both the Exp1 and GNN architectures.

| Check | Observed result |
|---|---|
| Combined build, public-effects and arrangement native checks | exit 0; Immolator effects restored, Voyage/Lightshell Duo/Opt/Preordain plans repeated and replayed without inference |
| Hosted XMage reviewed build at `abe73ee` | passed, including both new native checks |
| Saved diagnostic Uncharted Voyage callback (game 1792, seat step 77) | full callback observation comparison passed and reached the original inference boundary; zero model calls |

The definition change is limited to the build hash, the four recomputed entry versions, the build's class list and the two new helper sources. Reversing those fields recovers the previous definition exactly. Checkpoints, inference image, 96 visits/12 seconds, GNN 100 simulations, clocks, sixteen decks, six entrants and the 1,920-game / 960-pair schedule are unchanged.

Build custody: `E:/spellbench-issue36-serving-20261010/combined-model-build-001` (cold) and `D:/e-scratch/spellbench-issue36-serving-20261010/combined-model-build-001` (SSD). These are build and fixture checks, not serving, throughput or ratings.
