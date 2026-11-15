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
63a019dc9 to 89fb69a95 (mtg-kernel #505's merge), then to 4fccd3ebc, the
frozen W1 engine, then to d11d986d9: 4fccd3ebc plus the three commits of
mtg-kernel #614 (PR #705 into `release/ladder-v2-4fccd3ebc`), which keep a
paid ninjutsu source pristine in hand so the opponent infoset export no
longer halts on it (mtg-kernel #612). Only `agent_bridge_v1` and
`spellbench_qualify_v1` are rebuilt for that pin; the scorer (b7deed4d) and the
catalog are the pinned ones. Since 4fccd3ebc the board enables `x_kernel_infoset_v1`
for the W1 search entrant, so its engine is `kernel_engine_infoset_v2.py`,
named by its own placeholder `${MTG_KERNEL_V2_INFOSET_ENGINE}` (the other
boards keep `${MTG_KERNEL_V2_ENGINE}` for `kernel_engine_v2.py`). The
adapter imports `kernel_engine_v2.py` and `kernel_g6_digest.py`, so both
are in `evaluation_engine_inputs` and their bytes join the evaluation
engine identity. Build at the pinned commit with the W1 soak profile (for d11d986d9 leave out
`--bin spellbench_scorer_v1`):

    CARGO_PROFILE_RELEASE_LTO=false CARGO_PROFILE_RELEASE_CODEGEN_UNITS=64 \
    CARGO_PROFILE_RELEASE_INCREMENTAL=false \
    CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER=rust-lld \
    cargo build --release --locked -p mtg-kernel --bin agent_bridge_v1 \
        --bin spellbench_scorer_v1 --bin spellbench_qualify_v1

The catalog stays the 89fb69a95 one (sha256 `af8e1b91...`, byte-identical to
`pauper-v2-omen-92ec2393.json`).

The board runs the python engine inputs by sha256 from a spellbench
checkout at 0c486ed. Main's `kernel_history_v2.py` and
`kernel_observation_v2.py` differ from those bytes (spellbench d4dcb42), so
resolve the engine placeholders to a 0c486ed checkout, not to main. The
adapter pytest and goldens run on main's bytes; the other audits run on the
pinned ones (`engine_bytes` in `ENGINE-AUDITS.json`). The engine and builtin bot identities also depend on the launch environment: drive
`bench commit` and `bench run` with the pinned `python.exe` and with
`MTG_KERNEL_V2_BRIDGE`, `MTG_KERNEL_PUBLIC_CATALOG` and `MTG_KERNEL_V2_SOURCE`
removed from the launch process environment (including any user-level value it inherits), and check the printed engine
identity from `bench prepare` in a clean checkout before committing.

`pauper-ladder-v3` keeps that bridge, scorer, catalog and interpreter and
runs the adapter bytes of main at bb20077 (`kernel_history_v2.py` b41e376a
and `kernel_observation_v2.py` 3bfc00de from spellbench d4dcb42; the other
files are unchanged since 0c486ed), so resolve its engine placeholders to an
export of that commit. Its engine command is the plain adapter
`kernel_engine_v2.py` (placeholder `MTG_KERNEL_V2_ENGINE`), without
`x_kernel_infoset_v1`: on this bridge the information-set exporter halts
when a token sits in a hand (I1, mtg-kernel#713), which off-mirror Faeries
games reach. A bot that needs the export joins later through a per-block
opt-in under a new evaluation version, with the exporter fixed first.
Evaluation 3.0.0 does not offer per-block extensions and does not forbid
them: the extensions are a field of the definition and of the snapshot
contract, and a later evaluation version defines the opt-in.
Its rule for a committed definition: `spellbench
bench prepare benchmarks/pauper-ladder-v3 --check`, run from a clean
checkout of the default branch with the pinned `python.exe` and with every
placeholder resolved from `benchmarks/local.json`, must print OK before
`bench commit`. The check prepares the definition again and compares the
bytes, so the engine identity, every bot identity and the schedule are the
committed ones. It refuses any placeholder of the definition that is also
set in the process environment (`MTG_KERNEL_V2_BRIDGE` and
`MTG_KERNEL_PUBLIC_CATALOG` are the usual ones; also remove
`MTG_KERNEL_V2_SOURCE`, which earlier definitions read), because a set
variable wins over the local values. The builtin bot identities hash the
interpreter and the checkout's own builtin bot sources, so the check
reports them as different under another interpreter or a changed checkout.
The search entrant is listed in `deferred_entrants`, so the prepared file
needs no hand edit. CI has no pinned binaries: with them, set
`SPELLBENCH_PINNED_LOCAL` to the local values file and
`SPELLBENCH_PINNED_PYTHON` to the pinned interpreter, and
`pytest python/tests/test_ladder_v3.py -k pinned` makes the same check as
a test.

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
a card after an unseen shuffle, tell identical copies apart and, while draws
follow the original order, infer when a card was drawn (mtg-kernel
`docs/contracts/AGENT_BRIDGE_V1.md`). The adapter mints
per-viewer ids instead and never forwards `x_kernel_v5`. `check_engine_v2`
fails if `obj-`, `arena_id` or `x_kernel_v5` appears in any bot-facing
message; `--extension x_kernel_flat_v4 --extension x_public_history_v1`
also exercises the extensions board bots can request.
