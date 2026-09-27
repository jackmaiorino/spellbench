# mtg-kernel Phase 1 bots

`kernel_flat_bot.py` plays a Phase 1 V4 checkpoint (g115, A48, c12) on the
mtg-kernel engine. The engine must run with `--x-kernel-flat-v4`; the bot
forwards each decision's `x_kernel_flat_v4` tensor to the native scorer
`spellbench_scorer_v1` and answers with the mapped candidate id.

    python kernel_flat_bot.py --scorer spellbench_scorer_v1.exe \
        --config g115.scorer.json --name g115 --version 1.0.0

Selection is the training sampler with one draw per own decision from a
per-seat stream seeded by the game id and seat, so reruns are identical.
`--decision-log DIR` writes one JSONL file per game and seat for the
kernel's `spellbench_qualify_v1` replay check.
