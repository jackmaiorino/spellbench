# mtg-kernel Phase 1 bots

`kernel_flat_bot.py` plays a Phase 1 V4 checkpoint (g115, A48, c12) on the
mtg-kernel engine. The engine must run with `--x-kernel-flat-v4`; the bot
forwards each decision's `x_kernel_flat_v4` tensor to the native scorer
`spellbench_scorer_v1` and answers with the mapped candidate id.

    python kernel_flat_bot.py --scorer spellbench_scorer_v1 \
        --config g115.scorer.json --name g115 --version 1.0.0 \
        --expect-model-state 8139016ca561961714f25e22a9d6f7fc888548fc332e45b6bce402dfc43159f2

A bare `--scorer` name is looked up on `PATH` (with `PATHEXT` on Windows).
The bot exits before `hello`, so arena preflight stops the run, unless the
scorer reports the V4 feature digests, the training sampler and binary32
floats. `--expect-model-state` adds the model state hash to that check;
benchmark entries pass it, so a moved or swapped checkpoint cannot play
under the bot's name.

Selection is the training sampler with one draw per own decision from a
per-seat stream seeded by the game id and seat, so reruns are identical.
`--decision-log DIR` writes one JSONL file per game and seat for the
kernel's `spellbench_qualify_v1` replay check.

## Engine pins

`pauper-kernel-v2` and `pauper-ladder-v1` run the bridge, scorer and catalog
built from the mtg-kernel 92ec2393 line. `pauper-ladder-v2` runs them built
from mtg-kernel main at the commit named by its `--source-revision`, which
carries the same bridge (mtg-kernel PRs #462 and #476). The pin moved from
63a019dc9 to 89fb69a95 (mtg-kernel #505's merge) for the W1 search entrant;
the later bridge changes add only the `x_kernel_infoset_v1` extension, which
the board does not enable. Build at that commit with:

    cargo build --release --locked -p mtg-kernel --bin agent_bridge_v1 \
        --bin spellbench_scorer_v1 --bin spellbench_kernel_catalog
    target/release/spellbench_kernel_catalog > pauper-v2-catalog.json

Every engine change behind a board needs fresh audits on the pinned binary
before that board rates games: the history two-world audit, the
`check_engine_v2` and `check_private_preview_v2` checks here, the gorge-ar8
smoke, and the kernel's V4 visibility audit at the same commit
(`cargo test --release -p mtg-kernel --lib -- --ignored
spellbench_v4_visibility_audit --nocapture`). The board's `ENGINE-AUDITS.json`
records the commit, the binary hashes, each result and the reveal sites the
V4 audit printed.

## Native identity stays in the adapter

The native bridge's own `spellbench/v1` wire is for `kernel_engine_v2.py`
only; never connect a bot to it. Its `obj-<arena_id>-z<zcc>` ids and raw
`x_kernel_v5` observations carry native identity: the arena id follows the
initial library order and survives hidden zones, so a bot could re-identify
a card after an unseen shuffle, tell identical copies apart and date draws
(mtg-kernel `docs/contracts/AGENT_BRIDGE_V1.md`). The adapter mints
per-viewer ids instead and never forwards `x_kernel_v5`. `check_engine_v2`
fails if `obj-`, `arena_id` or `x_kernel_v5` appears in any bot-facing
message; `--extension x_kernel_flat_v4 --extension x_public_history_v1`
also exercises the extensions board bots can request.
