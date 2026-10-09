# DraftZero FDN graph network: goldens, timing and build

Release `danbrooks/draftzero-fdn-gnn@a8351e8b`. Every file matched the release's SHA256SUMS. Each check ran on the
second host (Ryzen 7 3700X), under that host's reservation and its supervisor, inside the network-less `gnn` image
(`--network none`, read-only, one CPU, 3 GB). The image used was `sha256:4c480570…`. Docker builds are not reproducible,
so the board pins the image actually used on its run host.

| Check | Result |
|---|---|
| Author's loader (`gnn_release.check`), 300 goldens | max option-logit diff 8.6e-6, value_x 1.3e-6, use 3.3e-7; same top option 300/300 |
| Serving path (`gnn_runtime.py check`), option logits | max diff 7.6e-6, value 8.9e-7, use 2.7e-7; same top option 300/300 |
| Serving path, per-node scores rebuilt into option logits | identical to the option path (max diff 0.0) |
| Repeated call | identical |
| One network call, batch 1, one CPU thread | median 24 ms, p90 33 ms, max 56 ms (median 226 nodes a state) |
| Golden leaf occurrences in the vocabulary | 99.91% |

The goldens contain 160 priority states and 140 target states (attacks, targets and blocks). None is a yes/no decision.

The model build has the encoder, MageZero v0.2, MageZero search and graph network stages, and `--current-overlay`.
Its BUILD.json is `6e0563fd…`, with 301 classes. It compiled on JDK 23.0.1 against engine manifest `3b54f3f6…`.
`GnnBridgeMain` started and printed its readiness line.

Receipt hashes (kept in the job root):

- `reference-probe.json` `54a3f5eb899d280612090de50e238c2e114f4e17e667e90b567b3b48abdcb83b`
- `serving-check.json` `87137cde8f1750bc07e2a5c0f2df9d3067c0e136fcae0c7ff8378e91a13f3300`
- `BUILD.json` `6e0563fd7d98645c8702c964e5fd4b5d6e8ee3cf4a8b6e562001368448a55d21`

## Natural games through the board's engine command

Both games are unrated and run at 100 simulations against the builtin heuristic bot, on the board's clock. The engine
command is the board's own: the verified entry, the pinned card database `fcdba7e7`, and overlay build `149de0fd`. The
GNN ran on its model build `76b29b89` with bot version `draftzero-gnn-pimc-v1-dd5a3721b40f75b6be1a3d93`. Each game was
played twice with the same seeds (`xmage_neural_game_check.py`), and each replay was identical.

| GNN deck vs heuristic deck | Result | Decisions | Searched | Fallbacks | Leaf coverage | Primary store |
|---|---|---|---|---|---|---|
| FDN_top_02581_UR vs FDN_top_02581_UR | GNN won (life) | 304 | 36 | 2 trigger orders | 99.95% | `65bf1ebf` |
| FDN_top_13950_BR vs FDN_top_04752_WG | heuristic won (life) | 447 | 159 | 13 horizon worlds, 1 unreproduced callback | 99.57% | `93fd2861` |

A searched root took a median of 101 network calls, and a searched decision took a few seconds. That fits the
3,600 s bank with a wide margin. The earlier attempts' failures are each fixed on this branch:

- characteristic gaps in callback replay;
- the combat search root;
- step names and helper emblems in the encoder;
- unsearched worlds;
- replay through attack declarations;
- unsearched decision families;
- fungible tapped permanents;
- visible draws;
- unreproduced callbacks.

Check receipts: UR `11fba535659f553abc452e6afb25a4b017e3beb9a659d958618c0281c311157b`, BR/WG
`241e6934ecaeb1fe81af442cb370116f9574576d3b5b4b9ed397a23e29beaed3`.

The golden checks cover the network, the weights and the option mapping. The native games and their leaf audit cover the
Java encoder on this engine. Neither establishes strength or rated admission.
