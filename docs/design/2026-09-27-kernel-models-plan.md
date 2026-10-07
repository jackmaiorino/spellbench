# Sub-project C: The maintainer's kernel models on Spellbench, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rate the maintainer's Phase 1 policies g115, A48 and c12 on the Spellbench `pauper-kernel` benchmark, each seeing exactly the model input its evaluation harness computes and making the harness's choice.

**Architecture:** The Spellbench bridge is ported onto Codex's g115 evaluation commit `cd41885e`. Behind an opt-in flag it runs a lockstep training-mode copy of every game (`FastActorSessionV1`, flat-action V3), checks it for exact equality after every step, and attaches the acting seat's V4 model input (computed by the kernel's own encoder) plus a row to candidate-id map to each decision as `x_kernel_flat_v4`. A stdlib Python bot in the Spellbench repo forwards that input to a native scorer (`spellbench_scorer_v1`, V4 mode with seeded sampling) and answers with the mapped candidate id. A replay verifier proves bot choices equal the harness's on the same positions before the benchmark is re-launched.

**Tech Stack:** Rust 2021 (mtg-kernel crate, serde, serde_json, sha2; no new dependencies), Python 3.11+ standard library (Spellbench), pytest for Spellbench tests, cargo test for kernel tests.

**Spec:** The "Spec" section below (no separate spec document). Background and evidence: `~\AppData\Local\Temp\claude\C--Users-user-IdeaProjects\157aeb44-0d40-4f26-8ee2-2b800f31ba9e\scratchpad\research-C-kernel-models.md`. Program: `~\IdeaProjects\spellbench\docs\design\2026-09-27-everyone-on-the-board.md` (sub-project 1).

---

## Spec

### What C delivers
1. mtg-kernel branch `spellbench/bridge-g115` (local only) containing: the Spellbench bridge ported onto `cd41885e`; the opt-in `--x-kernel-flat-v4` extension; the native scorer `spellbench_scorer_v1`; the replay verifier `spellbench_qualify_v1`.
2. Spellbench `integrations/mtg_kernel/`: a stdlib agent-role bot that plays any Phase 1 V4 checkpoint through the scorer.
3. Qualification evidence: every decision of a 96-game kernel-only tournament replayed against the evaluation harness with zero tensor, logit, choice and outcome mismatches, and a byte-identical rerun.
4. `benchmarks/pauper-kernel` with bots g115, a48, c12 (sampled policy, no search) and a re-launch run on the new engine identity (card registry `064a7c989255ab3c`), all six bots rated.

### Design
```
host -> agent_bridge_v1 --x-kernel-flat-v4
          RlEpisodeSessionV1 ............ protocol surface (raw policy-v5 list, x_kernel_v5), unchanged
          FastActorSessionV1, flat-action V3 ... lockstep copy, stepped with the same actions,
                                            game state compared for equality after every step
          V4 encoder + tensorizer on the copy -> extensions.x_kernel_flat_v4:
                                            {tensor bits, row_candidate_ids, feature digests, card db}
host -> kernel_flat_bot.py (choose) -> spellbench_scorer_v1 (one pinned checkpoint, CPU)
          answer = row_candidate_ids[selected_row]
```
- The lockstep copy is the session type and mode g115 was trained and evaluated on (`expanded_deck_training_v1.rs:1129`, `paired_bo1_harness_v1.rs:451-454`); the encoder calls are the ones `FrozenPlayPolicyV1::score_owned` makes. No second feature implementation exists anywhere in C.
- Flat-action V3 normalizes candidates (`rl_session/flat_action_v3.rs:217-343`): search targets reordered, effect sources relabeled to their historical record (same arena id), required-goad exclusions and infeasible menace blocks removed. The row map is built by semantic equality with an arena-id-only comparison of the effect source.
- Any engine-side failure to produce the input (lockstep reset, divergence, a selection the training list dropped, encoder or tensorizer error) ends the game as `halted`; never a bot forfeit.
- The bot samples like the evaluation harness: training sampler `f32-q8-expq63-hamilton-splitmix64-wide-v1`, one SplitMix64 draw per own decision from a seat stream seeded by `sha256(domain | game_id | seat)`.

### Non-goals
- No training, no search (the D3 search treatment needs engine-side simulation), no greedy variants.
- No V3-contract or Net8 (V2-contract) models; no registry transfers.
- No edits to Codex-owned kernel code: only new files, one-line `mod` registrations in `mtg-kernel/src/lib.rs`, and the cherry-picked bridge files.
- No fixes to the goad or menace kernel defects; no Terror support; no Protocol v2.
- No relocation or copying of checkpoints; scorer configs point at the original read-only files.
- Nothing pushed from mtg-kernel; no public release of results (the maintainer's call).

---

## Global Constraints

- mtg-kernel worktree: `~/IdeaProjects/mtg-kernel-spellbench-g115` on branch `spellbench/bridge-g115`, created by the controller from `cd41885e`; never create branches or worktrees yourself. (Called `$MTGK` below.)
- Spellbench work happens on branch `c-kernel-bots`, created by the controller from `board-program` (`b97b068`), in `~/IdeaProjects/spellbench` (called `$SB` below).
- All cargo commands: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115`, `-j 4`, at BelowNormal priority: start them from a PowerShell prompt after `(Get-Process -Id $PID).PriorityClass = 'BelowNormal'` (child processes inherit it). Commands below are written in Git Bash syntax; in PowerShell write `$env:VAR = 'value'; cmd` for `VAR=value cmd`. Never build into any other target directory.
- Codex-owned kernel code is read-only: do not edit `rl_session*.rs`, `flat_policy_*.rs`, `native_*.rs`, `sideboard_play_policy_v1.rs`, `expanded_deck_training_v1*`, `xmage_observed_inference_v1.rs` or any other pre-existing file, except the cherry-picked bridge files and one-line `mod` registrations in `mtg-kernel/src/lib.rs`.
- Checkpoints and descriptors are read-only and stay where they are; nothing of Codex's is pushed anywhere.
- Engine-side failure to produce `x_kernel_flat_v4` is a `halted` terminal with a reason starting `engine_contract_failure:flat_v4_`; never a forfeit.
- Without `--x-kernel-flat-v4` the bridge behaves exactly like the port: hello `extensions` is `["x_kernel_v5"]` and `data/agent_bridge_v1` goldens do not change.
- Every integer on the Spellbench wire satisfies `|x| <= 2^53`.
- Spellbench code stays standard-library Python; the bot imports only the standard library and `spellbench`.
- Feature identity: contract `c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b`, encoding `271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de`, card db `064a7c989255ab3c`.
- Model sources (read-only; state sha256 is what the scorer must report):
  - g115: checkpoint `D:/phase1-live/campaign-002/g/block115/run/iterations/000199/attempt-000000/update/checkpoint.json` sha256 `88c0b997708c2b5156b44f3940ad9d5d682f78ac24d346978bb3c9f34c59e8d1`; play_import `E:/mtg-kernel-learned-sideboarding-evidence/bo3-post480-preparation-001/phase1-training-qualification-001/campaign-001/block1/catalog/b-descriptor-windows.json` sha256 `6c2fcb3730e23df685836527f69ef3c2092c0bd121d7aedfc26e54072c60e808`; state `8139016ca561961714f25e22a9d6f7fc888548fc332e45b6bce402dfc43159f2`.
  - a48: checkpoint `D:/phase1-live/campaign-002/a/block48/run/iterations/000199/attempt-000000/update/checkpoint.json` sha256 `beb86b4116c6eaa8406f12eb391adde1a637e063375740ea0b9812251bcff4a4`; play_import `.../catalog/a-descriptor-windows.json` (same directory as above) sha256 `7b39fa26ef0ca72d7e3d660f32a266ef82692739b4d44f1870630fbd463d28f7`; state `774e936da26468358257774fe41ae94578265b331d2edb49d017c0835b08699a`.
  - c12: checkpoint `D:/phase1-live/campaign-002/c/block12/run/iterations/000199/attempt-000000/update/checkpoint.json` sha256 `993373f3e107e31f4be2ca0f368d2b1dd69b8088e59a81ea8257776c5bbc6abf`; play_import b-descriptor as for g115; state `5c14c025e3cc87fb2c3eea28e1dbd770d7d257344174296d6259020f720da9de`.
- Evidence lands outside the repositories in `E:/spellbench-archive/2026-09-27-c-kernel-models/`; scorer configs in `E:/spellbench-archive/kernel-bots/`.
- Spellbench results are measurement only: they are not inputs to Codex's D4 or the research director.
- Tasks 8 and 9 run evaluations: apply `~/COMPUTE-POLICY.md` (placement check across the primary desktop, the compute host and RunPod; scaling comparison; allocation recorded).
- Never use em-dashes in code, docs, commit messages or reports.

## Review Focus

- An opponent (a builtin) picks a candidate the training list dropped (required-goad exclusion, infeasible menace block): the game must end `halted` with `engine_contract_failure:flat_v4_lockstep:selection_not_in_training_list:<id>`, not desync or forfeit. Pinned by Task 6 `flat_v4_selection_outside_the_training_list_halts_the_game`.
- The benchmark engine command lacks `--x-kernel-flat-v4`: the bot must refuse with a message naming the flag, and the relaunch must stop before rated games. Pinned by Task 5 `test_missing_extension_is_an_internal_error` and the Task 9 smoke step (zero forfeits required).
- Model files moved, edited or mismatched to the config: the scorer must refuse to start and the bot must exit before `hello`, so arena preflight aborts the run instead of forfeiting games. Pinned by Task 4 `load_failure_emits_one_error_record_and_stops` and Task 5 `test_bot_exits_before_hello_when_the_scorer_never_becomes_ready`.
- Eight workers with two kernel seats per game run 16 scorer processes: choose latency must stay far below the 30 s timeout. Pinned by the Task 8 latency check (max `elapsed_us` under 5,000,000).
- A rerun with the same config must reproduce the ledger byte for byte (seat streams, lockstep, CPU forward). Pinned by the Task 8 double run and `cmp` of `matches.jsonl`.

---

## File structure

mtg-kernel (`$MTGK`, branch `spellbench/bridge-g115`):

| File | Task | Responsibility |
|---|---|---|
| bridge files from `0886e7b9..f175832c` | 1 | ported environment-role bridge, tests, goldens, contract doc |
| `mtg-kernel/src/agent_bridge_flat_v4.rs` | 2 | lockstep training-mode copy, equality check, row to candidate-id map |
| `mtg-kernel/src/agent_bridge_flat_v4_encode.rs` | 3 | V4 tensor for the copy's current decision, extension JSON, digests |
| `mtg-kernel/src/spellbench_scorer_v1.rs`, `mtg-kernel/src/bin/spellbench_scorer_v1.rs` | 4 | pinned-model JSONL scorer, V4 only, argmax or seeded sampling |
| `mtg-kernel/src/agent_bridge_v1.rs`, `mtg-kernel/src/bin/agent_bridge_v1.rs`, `mtg-kernel/tests/agent_bridge_v1.rs`, `docs/contracts/AGENT_BRIDGE_V1.md` | 6 | flag, wiring, halts, docs |
| `mtg-kernel/src/spellbench_qualify_v1.rs`, `mtg-kernel/src/bin/spellbench_qualify_v1.rs` | 7 | replay verifier: bot logs versus evaluation harness |
| `mtg-kernel/src/lib.rs` | 1, 2, 3, 4, 7 | one `mod` line each, at distinct anchors |

Spellbench (`$SB`, branch `c-kernel-bots`):

| File | Task | Responsibility |
|---|---|---|
| `integrations/mtg_kernel/kernel_flat_bot.py`, `README.md`, `tests/fake_scorer.py`, `tests/test_kernel_flat_bot.py` | 5 | agent-role bot, scorer test double, tests |
| `python/tests/test_engine_conformance.py`, `.github/workflows/ci.yml` | 5 | `SPELLBENCH_ENGINE_ARGS`; CI runs `integrations` tests |
| `benchmarks/pauper-kernel/benchmark.json`, `benchmarks/pauper-kernel/runs/<date>/`, `spec/SPELLBENCH_PROTOCOL_V1.md` (section 9 note) | 9 | kernel bots, flag, re-launch run |

Why the bot lives in Spellbench (`integrations/mtg_kernel/`), not in mtg-kernel: the bot needs only the Spellbench package and a scorer executable (no kernel Python); the mtg-kernel branch sits on unpushed Codex history and can never be published, while the benchmark definition that launches the bot, its tests and its provenance (`SPELLBENCH_SOURCE_REVISION`) all live in Spellbench; and `integrations/<engine>/` is the home the program needs next for gorge and XMage adapters.

## Dependencies and parallelism

| Task | Depends on | Can run in parallel with | Effort |
|---|---|---|---|
| 1 Port bridge | branch from controller | 5 | 0.5 d |
| 2 Lockstep | 1 | 3, 4, 5 (disjoint files; lib.rs anchors differ) | 0.5 d |
| 3 Payload encoder | 1 | 2, 4, 5 | 0.5 d |
| 4 Scorer | 1 | 2, 3, 5 | 0.5 d |
| 5 Python bot | none | 1, 2, 3, 4 | 0.5 d |
| 6 Wiring and halts | 2, 3 (Step 5 also needs Task 5 Step 5 in `$SB`) | 4, 5 | 0.75 d |
| 7 Verifier | 3, 4, 6 | 5 | 0.5 d |
| 8 Qualification run | 5, 7 | none | 0.5 d |
| 9 Benchmark and re-launch | 8, gate G1 | none | 0.5 d |

Total about 4.75 agent-days; critical path 1, 2 or 3, 6, 7, 8, 9 is about 3.25 days with the parallel lanes.

---

### Task 1: Port the Spellbench bridge onto cd41885e

**Files:**
- Cherry-pick: `.gitattributes`, `.github/workflows/ci.yml`, `data/agent_bridge_v1/*`, `docs/README.md`, `docs/contracts/AGENT_BRIDGE_V1.md`, `mtg-kernel/src/agent_bridge_v1.rs`, `mtg-kernel/src/bin/agent_bridge_v1.rs`, `mtg-kernel/src/lib.rs`, `mtg-kernel/tests/agent_bridge_v1.rs`, `python/tools/generate_agent_bridge_goldens.py`
- Modify: `mtg-kernel/src/agent_bridge_v1.rs` (`session_error_to_bridge_code_v1`, `session_error_code_name_v1`, the `ChooseOptionalCostWhich` arm of `neutral_semantic_v1`)
- Modify: `mtg-kernel/tests/agent_bridge_v1.rs` (two seed-pinned tests)
- Modify: `docs/contracts/AGENT_BRIDGE_V1.md` (optional-cost row)
- Regenerate: `data/agent_bridge_v1/*.transcript.jsonl`, `data/agent_bridge_v1/manifest.json`

**Interfaces:**
- Consumes: branch `spellbench/bridge-g115` at `cd41885e` (controller). Kernel APIs unchanged from main: `RlEpisodeSessionV1::{reset_with_decks_and_limits, current_response, step}`, `ActionSemanticV1` (byte-identical enum).
- Produces: `mtg_kernel::agent_bridge_v1::{SpellbenchBridgeServerV1, SpellbenchEngineIdentityV1}` with `SpellbenchBridgeServerV1::new() -> Self`, `with_engine_identity(SpellbenchEngineIdentityV1) -> Self`, `handle_line(&mut self, &str) -> String`; private `fn optional_cost_choice_str_v1(choice: OptionalCostChoice) -> &'static str`; bin `agent_bridge_v1`. Engine identity strings now end in `carddb-064a7c989255ab3c`.

- [ ] **Step 1: Cherry-pick the five bridge commits**

```bash
cd $MTGK
git log -1 --format=%H   # Expected: cd41885e...
git cherry-pick 0886e7b9 a441cd0b 60772d21 4b5eeef1 f175832c
```
Expected: five commits applied without conflicts (the hunk contexts in `lib.rs`, `.gitattributes`, `ci.yml` and `docs/README.md` exist unchanged on `cd41885e`).

- [ ] **Step 2: Compile to see the port failures**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_v1 --no-run -j 4`
Expected: FAIL with `error[E0004]: non-exhaustive patterns: RlSessionErrorCode::NonNaturalTerminal not covered` (twice) and `OptionalCostChoice::ReturnPermanent not covered`. The first build of the lib test target takes a long time.

- [ ] **Step 3: Write the failing unit test**

Append to the `#[cfg(test)] mod tests` block at the end of `mtg-kernel/src/agent_bridge_v1.rs`:

```rust
#[test]
fn port_maps_the_codex_lineage_enum_additions() {
    assert_eq!(
        session_error_code_name_v1(RlSessionErrorCode::NonNaturalTerminal),
        "non_natural_terminal"
    );
    let refused = RlSessionError {
        code: RlSessionErrorCode::NonNaturalTerminal,
        message: "non-natural".to_string(),
    };
    assert_eq!(session_error_to_bridge_code_v1(&refused), None);
    assert_eq!(optional_cost_choice_str_v1(OptionalCostChoice::ReturnPermanent), "return_permanent");
    assert_eq!(optional_cost_choice_str_v1(OptionalCostChoice::SacrificeLand), "sacrifice_land");
}
```

- [ ] **Step 4: Implement the arms**

In `session_error_to_bridge_code_v1` extend the `None` arm:
```rust
        | RlSessionErrorCode::EnvironmentRandomization
        | RlSessionErrorCode::NonNaturalTerminal => None,
```
In `session_error_code_name_v1` add:
```rust
        RlSessionErrorCode::NonNaturalTerminal => "non_natural_terminal",
```
Add next to `mana_choice_str_v1`:
```rust
/// Neutral `choose_optional_cost_which.choice` (spec Section 6 allows other
/// lowercase snake_case values beside the documented ones).
fn optional_cost_choice_str_v1(choice: OptionalCostChoice) -> &'static str {
    match choice {
        OptionalCostChoice::Decline => "decline",
        OptionalCostChoice::Discard => "discard",
        OptionalCostChoice::SacrificeLand => "sacrifice_land",
        OptionalCostChoice::ReturnPermanent => "return_permanent",
    }
}
```
and replace the inline match in the `ChooseOptionalCostWhich` arm with `"choice": optional_cost_choice_str_v1(*choice),`. In `docs/contracts/AGENT_BRIDGE_V1.md` section 6 change the row to `` `choice`: `"decline"`/`"discard"`/`"sacrifice_land"`/`"return_permanent"` ``.

- [ ] **Step 5: Run the module tests**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_v1 -j 4`
Expected: PASS, `test result: ok.` with 0 failed.

- [ ] **Step 6: Run the integration tests**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --test agent_bridge_v1 -j 4`
Expected: all pass except possibly `agent_bridge_names_the_session_error_when_a_validated_step_is_refused` and `agent_bridge_passes_a_kernel_halt_through_with_its_reason`. Both pin seeds reproduced on main's engine; this base has other rules (it includes the linked-exile fix `f72b32bc` behind the CawGates reproduction).

- [ ] **Step 7: Search for re-pin seeds**

Append to `mtg-kernel/tests/agent_bridge_v1.rs`:

```rust
/// Re-pinning helper after an engine change: prints every halted sweep game.
#[test]
#[ignore = "seed search helper; run with --ignored --nocapture"]
fn search_halted_sweep_games() {
    for deck in ["Elves", "CawGates", "Faeries", "Affinity", "Rally", "Wildfire", "Burn", "Spy"] {
        for seed in 1..=200_u64 {
            let (line, answered, choice) = drive_sweep_game(deck, seed, "g-search");
            let terminal = parse_line(&line);
            if terminal["outcome"] == "halted" {
                println!(
                    "HALT deck={deck} seed={seed} step={} kind={} step_count={} reason={}",
                    answered["step"], answered["candidates"][choice]["semantic"]["kind"],
                    terminal["step_count"], terminal["reason"]
                );
            }
        }
    }
}
```
Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --test agent_bridge_v1 search_halted_sweep_games -j 4 -- --ignored --nocapture`
Expected: `HALT ...` lines. Lines whose reason starts `engine_contract_failure:session_step_rejected_after_validation:` are session refusals; lines whose reason starts `fail_closed:` or `engine_halted:` are kernel halts.

- [ ] **Step 8: Re-pin the two tests**

In `agent_bridge_names_the_session_error_when_a_validated_step_is_refused`, replace the literals `"Elves"`, `11` (both calls), the asserted reason, `99` and `100` with the deck, seed, reason, step and step_count of the first session-refusal `HALT` line, and keep the `choose_attacker_inclusion` or `choose_blocker_inclusion` kind the line printed. In `agent_bridge_passes_a_kernel_halt_through_with_its_reason`, replace `"CawGates"`, `22`, the reason and `90` with the first kernel-halt line. If the search printed no kernel-halt line, delete that test and say in the commit message that its reproduction is fixed on this base by `f72b32bc`.

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --test agent_bridge_v1 -j 4`
Expected: PASS, 0 failed (1 ignored).

- [ ] **Step 9: Regenerate and check the goldens**

```bash
CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo build -p mtg-kernel --release --locked --bin agent_bridge_v1 -j 4
export MTG_KERNEL_AGENT_BRIDGE_V1_BIN=D:/cargo-target/mtg-kernel-spellbench-g115/release/agent_bridge_v1.exe
python python/tools/generate_agent_bridge_goldens.py --write --repo-root .
python python/tools/generate_agent_bridge_goldens.py --check --repo-root .
git diff --stat data/agent_bridge_v1
```
Expected: `AGENT_BRIDGE_GOLDENS: WROTE`, then `AGENT_BRIDGE_GOLDENS: PASS`; the diff shows `carddb-64c82a261e078f1a` replaced by `carddb-064a7c989255ab3c` and possibly different Burn mirror game content.

- [ ] **Step 10: Run the Spellbench reference client against the ported binary**

```bash
cd $SB
SPELLBENCH_ENGINE_BIN=D:/cargo-target/mtg-kernel-spellbench-g115/release/agent_bridge_v1.exe \
SPELLBENCH_ENGINE_DECKS=Wildfire,Rally,Affinity,Elves,Spy,Burn,CawGates,Faeries \
uv run --no-sync pytest python/tests/test_engine_conformance.py -q
```
Expected: `16 passed`.

- [ ] **Step 11: Commit**

```bash
cd $MTGK
git add mtg-kernel/src/agent_bridge_v1.rs mtg-kernel/tests/agent_bridge_v1.rs docs/contracts/AGENT_BRIDGE_V1.md data/agent_bridge_v1
git commit -m "agent bridge: port onto the Phase 1 evaluation runtime cd41885e"
```

---

### Task 2: Lockstep training-mode copy and equality check

**Files:**
- Create: `mtg-kernel/src/agent_bridge_flat_v4.rs`
- Modify: `mtg-kernel/src/lib.rs` (insert `pub(crate) mod agent_bridge_flat_v4;` on the line after `pub mod agent_bridge_v1;`)

**Interfaces:**
- Consumes (all pub on `cd41885e`): `FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(episode_id: u64, seed: u64, max_physical_decisions: u64, max_policy_steps: u64, deck_ids: SessionDeckIdsV1) -> Result<FastActorSessionV1, RlSessionError>` (`rl_session/flat_action_v3.rs:723`); `FastActorSessionV1::{current_response, step(episode_id, expected_step, selected_index: u32), diagnostic_current_action_semantics() -> Option<Vec<ActionSemanticV1>>, game_state() -> &GameState, policy_step_count, physical_decision_count}`; the same counters and `game_state` on `RlEpisodeSessionV1`.
- Produces (`crate::agent_bridge_flat_v4`):
  - `pub(crate) enum FlatV4LockstepErrorV1 { Reset(String), NoCurrentDecision, RowMap(&'static str), SelectionNotInTrainingList { candidate_id: u32 }, FastStep(String), Diverged(&'static str) }` with `pub(crate) fn halt_reason(&self) -> String` returning `engine_contract_failure:flat_v4_lockstep:<detail>`.
  - `pub(crate) fn semantics_equivalent_v1(raw: &ActionSemanticV1, row: &ActionSemanticV1) -> bool`
  - `pub(crate) fn map_rows_to_candidates_v1(raw: &[ActionSemanticV1], rows: &[ActionSemanticV1]) -> Result<Vec<u32>, FlatV4LockstepErrorV1>`
  - `pub(crate) struct FlatV4LockstepV1` with `reset(episode_id: u64, env_seed: u64, max_physical_decisions: u64, max_policy_steps: u64, deck_ids: SessionDeckIdsV1) -> Result<Self, FlatV4LockstepErrorV1>`, `fast_session(&self) -> &FastActorSessionV1`, `verify(&self, raw: &RlEpisodeSessionV1, raw_response: &RlSessionResponseV1) -> Result<(), FlatV4LockstepErrorV1>`, `row_candidate_ids(&self, raw_decision: &RlSessionDecisionV1) -> Result<Vec<u32>, FlatV4LockstepErrorV1>`, `mirror_step(&mut self, row_candidate_ids: &[u32], expected_step: u64, candidate_id: u32) -> Result<(), FlatV4LockstepErrorV1>`, and `#[cfg(test)] fast_session_mut_for_test(&mut self) -> &mut FastActorSessionV1`.

- [ ] **Step 1: Write the failing tests**

Create `mtg-kernel/src/agent_bridge_flat_v4.rs` with only the test module:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::rl::{PlayerSeatV1, TargetRefV1};
    use crate::rl_session::RlSessionResponseV1;
    use crate::state::{SplitMix64, Zone};

    const DECKS: [&str; 8] = ["Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries"];

    fn card(arena_id: u32, zone: Zone, zone_change_count: u32) -> CardStableRefV1 {
        CardStableRefV1 {
            arena_id,
            card_db_id: 7,
            owner: PlayerSeatV1::P0,
            controller: PlayerSeatV1::P0,
            zone,
            zone_change_count,
        }
    }

    fn effect_target(source: &CardStableRefV1, target_id: u32) -> ActionSemanticV1 {
        ActionSemanticV1::ChooseEffectTarget {
            actor: PlayerSeatV1::P0,
            source: source.clone(),
            target: TargetRefV1::Object { object: card(target_id, Zone::Battlefield, 1) },
            selected_count: 0,
            min_targets: 1,
            max_targets: 1,
        }
    }

    #[test]
    fn row_map_follows_reordering_filtering_and_effect_source_relabels() {
        let live = card(40, Zone::Stack, 3);
        let historical = card(40, Zone::Graveyard, 2);
        let raw = vec![
            effect_target(&live, 1),
            effect_target(&live, 2),
            ActionSemanticV1::Pass { actor: PlayerSeatV1::P0 },
        ];
        // Training mode relabels the source, reverses the targets, drops Pass.
        let rows = vec![effect_target(&historical, 2), effect_target(&historical, 1)];
        assert_eq!(map_rows_to_candidates_v1(&raw, &rows).unwrap(), vec![1, 0]);
    }

    #[test]
    fn row_map_rejects_unmatched_ambiguous_and_foreign_source_rows() {
        let live = card(40, Zone::Stack, 3);
        let other = card(41, Zone::Graveyard, 2);
        let raw = vec![effect_target(&live, 1), effect_target(&live, 1)];
        assert_eq!(
            map_rows_to_candidates_v1(&raw, &[effect_target(&live, 1)]),
            Err(FlatV4LockstepErrorV1::RowMap("ambiguous_row"))
        );
        assert_eq!(
            map_rows_to_candidates_v1(&raw[..1], &[effect_target(&other, 1)]),
            Err(FlatV4LockstepErrorV1::RowMap("unmatched_row"))
        );
        assert!(!semantics_equivalent_v1(&effect_target(&live, 1), &effect_target(&live, 2)));
    }

    #[test]
    fn lockstep_follows_the_raw_session_through_whole_games_on_every_catalog_deck() {
        for (index, deck) in DECKS.iter().enumerate() {
            for seed in [11_u64, 29, 47] {
                let episode_id = 0xB0B0_0000 + index as u64 * 1_000 + seed;
                let decks: SessionDeckIdsV1 = [deck.to_string(), deck.to_string()];
                let mut raw = RlEpisodeSessionV1::reset_with_decks_and_limits(
                    episode_id, seed, 2_000, 200_000, decks.clone(),
                )
                .unwrap();
                let mut lockstep =
                    FlatV4LockstepV1::reset(episode_id, seed, 2_000, 200_000, decks).unwrap();
                let mut rng = SplitMix64::seed(seed ^ 0x5EED);
                let mut steps = 0_u64;
                loop {
                    let response = raw.current_response();
                    lockstep.verify(&raw, &response).unwrap();
                    let RlSessionResponseV1::Decision(decision) = response else { break };
                    let rows = lockstep.row_candidate_ids(&decision).unwrap();
                    let pick = rows[(rng.next_u64() % rows.len() as u64) as usize];
                    let chosen = &decision.legal_actions[pick as usize];
                    raw.step(decision.episode_id, decision.step, pick, &chosen.stable_id).unwrap();
                    lockstep.mirror_step(&rows, decision.step, pick).unwrap();
                    steps += 1;
                }
                assert!(steps > 20, "{deck} seed {seed}: only {steps} steps");
            }
        }
    }

    #[test]
    fn mirror_step_refuses_a_selection_the_training_list_dropped() {
        let decks: SessionDeckIdsV1 = ["Burn".to_string(), "Burn".to_string()];
        let mut lockstep = FlatV4LockstepV1::reset(5, 5, 400, 4_000, decks).unwrap();
        let before = lockstep.fast_session().policy_step_count();
        assert_eq!(
            lockstep.mirror_step(&[1, 0], 0, 2),
            Err(FlatV4LockstepErrorV1::SelectionNotInTrainingList { candidate_id: 2 })
        );
        assert_eq!(lockstep.fast_session().policy_step_count(), before);
        assert_eq!(
            FlatV4LockstepErrorV1::SelectionNotInTrainingList { candidate_id: 2 }.halt_reason(),
            "engine_contract_failure:flat_v4_lockstep:selection_not_in_training_list:2"
        );
    }

    #[test]
    fn verify_detects_a_copy_of_a_different_game() {
        let decks: SessionDeckIdsV1 = ["Rally".to_string(), "Rally".to_string()];
        let raw = RlEpisodeSessionV1::reset_with_decks_and_limits(9, 11, 400, 4_000, decks.clone()).unwrap();
        let other = FlatV4LockstepV1::reset(9, 12, 400, 4_000, decks).unwrap();
        let error = other.verify(&raw, &raw.current_response()).unwrap_err();
        assert!(matches!(error, FlatV4LockstepErrorV1::Diverged(_)), "{error:?}");
    }
}
```
Add `pub(crate) mod agent_bridge_flat_v4;` to `mtg-kernel/src/lib.rs` on the line after `pub mod agent_bridge_v1;`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_flat_v4 -j 4`
Expected: FAIL to compile with `cannot find function map_rows_to_candidates_v1` and `cannot find type FlatV4LockstepV1`.

- [ ] **Step 3: Implement the module**

Insert above the test module:

```rust
//! Lockstep training-mode copy behind the bridge's `x_kernel_flat_v4`.
//!
//! The protocol surface stays on `RlEpisodeSessionV1`. This copy is a
//! `FastActorSessionV1` in flat-action V3 mode (the session type and mode the
//! Phase 1 lineage trained and was evaluated on), created with the same
//! catalog decks, seed and limits and stepped with the same executed actions.
//! `verify` compares game state for equality after every step. The copy only
//! encodes; it never drives the game.
//!
//! Flat-action V3 normalizes candidates (`rl_session/flat_action_v3.rs`
//! `normalize_candidates`): search targets reordered, effect sources replaced
//! by their historical record with the same arena id, required-goad
//! exclusions and infeasible menace blocks removed. `map_rows_to_candidates_v1`
//! maps each training row back to the raw candidate id.

use crate::rl::{ActionSemanticV1, CardStableRefV1};
use crate::rl_session::{
    FastActorResponseV1, FastActorSessionV1, RlEpisodeSessionV1, RlSessionDecisionV1,
    RlSessionResponseV1, SessionDeckIdsV1,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum FlatV4LockstepErrorV1 {
    Reset(String),
    NoCurrentDecision,
    RowMap(&'static str),
    SelectionNotInTrainingList { candidate_id: u32 },
    FastStep(String),
    Diverged(&'static str),
}

impl FlatV4LockstepErrorV1 {
    /// Halted reason: the engine could not produce the model input.
    pub(crate) fn halt_reason(&self) -> String {
        let detail = match self {
            Self::Reset(message) => format!("reset:{message}"),
            Self::NoCurrentDecision => "no_current_decision".to_string(),
            Self::RowMap(class) => format!("row_map:{class}"),
            Self::SelectionNotInTrainingList { candidate_id } => {
                format!("selection_not_in_training_list:{candidate_id}")
            }
            Self::FastStep(message) => format!("fast_step:{message}"),
            Self::Diverged(what) => format!("diverged:{what}"),
        };
        format!("engine_contract_failure:flat_v4_lockstep:{detail}")
    }
}

/// The six effect variants whose `source` flat-action V3 relabels (mirror of
/// `rl_session/flat_action_v3.rs` `effect_source_mut`, which is private).
fn effect_source_v1(semantic: &ActionSemanticV1) -> Option<&CardStableRefV1> {
    match semantic {
        ActionSemanticV1::ChooseEffectOption { source, .. }
        | ActionSemanticV1::ChooseEffectTarget { source, .. }
        | ActionSemanticV1::FinishEffectSelection { source, .. }
        | ActionSemanticV1::ChooseEffectColor { source, .. }
        | ActionSemanticV1::ChooseEffectNumber { source, .. }
        | ActionSemanticV1::ChooseEffectBoolean { source, .. } => Some(source),
        _ => None,
    }
}

fn with_effect_source_v1(semantic: &ActionSemanticV1, replacement: &CardStableRefV1) -> ActionSemanticV1 {
    let mut copy = semantic.clone();
    match &mut copy {
        ActionSemanticV1::ChooseEffectOption { source, .. }
        | ActionSemanticV1::ChooseEffectTarget { source, .. }
        | ActionSemanticV1::FinishEffectSelection { source, .. }
        | ActionSemanticV1::ChooseEffectColor { source, .. }
        | ActionSemanticV1::ChooseEffectNumber { source, .. }
        | ActionSemanticV1::ChooseEffectBoolean { source, .. } => *source = replacement.clone(),
        _ => {}
    }
    copy
}

/// Equal semantics, or equal after giving the raw effect source the row's
/// historical record when both name the same arena id.
pub(crate) fn semantics_equivalent_v1(raw: &ActionSemanticV1, row: &ActionSemanticV1) -> bool {
    if raw == row {
        return true;
    }
    match (effect_source_v1(raw), effect_source_v1(row)) {
        (Some(raw_source), Some(row_source)) if raw_source.arena_id == row_source.arena_id => {
            with_effect_source_v1(raw, row_source) == *row
        }
        _ => false,
    }
}

/// For each training row, the unique raw candidate id it executes.
pub(crate) fn map_rows_to_candidates_v1(
    raw: &[ActionSemanticV1],
    rows: &[ActionSemanticV1],
) -> Result<Vec<u32>, FlatV4LockstepErrorV1> {
    let mut used = vec![false; raw.len()];
    let mut map = Vec::with_capacity(rows.len());
    for row in rows {
        let mut matches = raw
            .iter()
            .enumerate()
            .filter(|(_, candidate)| semantics_equivalent_v1(candidate, row));
        let Some((index, _)) = matches.next() else {
            return Err(FlatV4LockstepErrorV1::RowMap("unmatched_row"));
        };
        if matches.next().is_some() {
            return Err(FlatV4LockstepErrorV1::RowMap("ambiguous_row"));
        }
        if std::mem::replace(&mut used[index], true) {
            return Err(FlatV4LockstepErrorV1::RowMap("duplicate_candidate"));
        }
        map.push(u32::try_from(index).map_err(|_| FlatV4LockstepErrorV1::RowMap("candidate_index"))?);
    }
    Ok(map)
}

pub(crate) struct FlatV4LockstepV1 {
    episode_id: u64,
    fast: FastActorSessionV1,
}

impl FlatV4LockstepV1 {
    pub(crate) fn reset(
        episode_id: u64,
        env_seed: u64,
        max_physical_decisions: u64,
        max_policy_steps: u64,
        deck_ids: SessionDeckIdsV1,
    ) -> Result<Self, FlatV4LockstepErrorV1> {
        let fast = FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(
            episode_id,
            env_seed,
            max_physical_decisions,
            max_policy_steps,
            deck_ids,
        )
        .map_err(|error| FlatV4LockstepErrorV1::Reset(error.message))?;
        Ok(Self { episode_id, fast })
    }

    pub(crate) fn fast_session(&self) -> &FastActorSessionV1 {
        &self.fast
    }

    #[cfg(test)]
    pub(crate) fn fast_session_mut_for_test(&mut self) -> &mut FastActorSessionV1 {
        &mut self.fast
    }

    /// Exact lockstep check: same response kind and decision header (or the
    /// identical terminal), same counters, equal game state.
    pub(crate) fn verify(
        &self,
        raw: &RlEpisodeSessionV1,
        raw_response: &RlSessionResponseV1,
    ) -> Result<(), FlatV4LockstepErrorV1> {
        match (raw_response, self.fast.current_response()) {
            (RlSessionResponseV1::Decision(raw_decision), FastActorResponseV1::Decision(fast_decision)) => {
                if raw_decision.step != fast_decision.step
                    || raw_decision.acting_player != fast_decision.acting_player
                    || raw_decision.physical_decision_id != fast_decision.physical_decision_id
                    || raw_decision.substep_index != fast_decision.substep_index
                    || raw_decision.substep_count != fast_decision.substep_count
                {
                    return Err(FlatV4LockstepErrorV1::Diverged("decision_header"));
                }
            }
            (RlSessionResponseV1::Terminal(raw_terminal), FastActorResponseV1::Terminal(fast_terminal)) => {
                if *raw_terminal != fast_terminal {
                    return Err(FlatV4LockstepErrorV1::Diverged("terminal"));
                }
            }
            _ => return Err(FlatV4LockstepErrorV1::Diverged("response_kind")),
        }
        if raw.policy_step_count() != self.fast.policy_step_count()
            || raw.physical_decision_count() != self.fast.physical_decision_count()
        {
            return Err(FlatV4LockstepErrorV1::Diverged("counters"));
        }
        if raw.game_state() != self.fast.game_state() {
            return Err(FlatV4LockstepErrorV1::Diverged("game_state"));
        }
        Ok(())
    }

    /// Row r of the V4 tensor is the copy's candidate r; returns its raw id.
    pub(crate) fn row_candidate_ids(
        &self,
        raw_decision: &RlSessionDecisionV1,
    ) -> Result<Vec<u32>, FlatV4LockstepErrorV1> {
        let rows = self
            .fast
            .diagnostic_current_action_semantics()
            .ok_or(FlatV4LockstepErrorV1::NoCurrentDecision)?;
        let raw: Vec<ActionSemanticV1> = raw_decision
            .legal_actions
            .iter()
            .map(|action| action.semantic.clone())
            .collect();
        map_rows_to_candidates_v1(&raw, &rows)
    }

    /// Steps the copy with the row executing `candidate_id`. Leaves the copy
    /// untouched when the training list does not contain the selection.
    pub(crate) fn mirror_step(
        &mut self,
        row_candidate_ids: &[u32],
        expected_step: u64,
        candidate_id: u32,
    ) -> Result<(), FlatV4LockstepErrorV1> {
        let row = row_candidate_ids
            .iter()
            .position(|id| *id == candidate_id)
            .ok_or(FlatV4LockstepErrorV1::SelectionNotInTrainingList { candidate_id })?;
        let row = u32::try_from(row).map_err(|_| FlatV4LockstepErrorV1::RowMap("row_index"))?;
        self.fast
            .step(self.episode_id, expected_step, row)
            .map_err(|error| FlatV4LockstepErrorV1::FastStep(error.message))?;
        Ok(())
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_flat_v4 -j 4`
Expected: PASS, `5 passed; 0 failed`. If the whole-game test fails with `Diverged("game_state")`, stop and report the deck, seed and step: that is a finding about the session types, not a test to loosen.

- [ ] **Step 5: Commit**

```bash
git add mtg-kernel/src/agent_bridge_flat_v4.rs mtg-kernel/src/lib.rs
git commit -m "agent bridge: lockstep training-mode copy with row map and equality check"
```

---

### Task 3: x_kernel_flat_v4 payload encoder with digests

**Files:**
- Create: `mtg-kernel/src/agent_bridge_flat_v4_encode.rs`
- Modify: `mtg-kernel/src/lib.rs` (insert `pub(crate) mod agent_bridge_flat_v4_encode;` on the line after `pub mod flat_policy_v4;`)

**Interfaces:**
- Consumes (pub(crate) on `cd41885e`): `FastActorSessionV1::encode_current_flat_scoring_decision_owned_v4(&self, FastActorDecisionV1, &mut FlatDecisionEncoderV4, &mut FlatScoringOwnedBuffersV2<'_>) -> Result<FlatDecisionV4, FlatDecisionErrorV2>` (`flat_policy_v4.rs:94`); `FlatScoringDecisionViewV2::new` (11 args, `flat_policy_v2.rs:921`); `FlatScoringDecisionViewV4::new`; `NativeFlatTensorizerV4::fill`; `NativeFlatDecisionTensorV4 { common: NativeFlatDecisionTensorV2 }`; `FEATURE_CONTRACT_DIGEST_V4`, `FEATURE_ENCODING_DIGEST_V4`; `KERNEL_CARDDB_HASH`; `xmage_observed_inference_v1::ObservedTensorBitsV1` (pub wire type, reused unmodified).
- Produces (`crate::agent_bridge_flat_v4_encode`):
  - `pub const SPELLBENCH_EXTENSION_KERNEL_FLAT_V4: &str = "x_kernel_flat_v4";`
  - `pub const FLAT_V4_EXTENSION_SCHEMA_V1: &str = "mtg-kernel-spellbench-flat-v4/v1";`
  - `pub(crate) enum FlatV4EncodeErrorV1 { NotADecision, Encode(String), Tensorize(String), RowCount { rows: usize, tensor_actions: usize } }` with `halt_reason(&self) -> String` returning `engine_contract_failure:flat_v4_encode:<detail>`.
  - `#[derive(Default)] pub(crate) struct FlatV4EncodeScratchV1`
  - `pub(crate) fn encode_flat_v4_tensor_v1(fast: &FastActorSessionV1, scratch: &mut FlatV4EncodeScratchV1) -> Result<NativeFlatDecisionTensorV4, FlatV4EncodeErrorV1>`
  - `pub(crate) fn tensor_bits_v1(tensor: &NativeFlatDecisionTensorV4) -> ObservedTensorBitsV1`
  - `pub(crate) fn flat_v4_extension_value_v1(tensor: &NativeFlatDecisionTensorV4, row_candidate_ids: &[u32], acting_seat: &str, step: u64) -> Result<serde_json::Value, FlatV4EncodeErrorV1>`
  - Wire shape: `{"schema","feature_contract_digest","feature_encoding_digest","card_db_hash","acting_seat","step","row_candidate_ids":[u32],"tensor":{13 arrays}}`, float arrays as IEEE-754 binary32 bit patterns.

- [ ] **Step 1: Write the failing tests**

Create `mtg-kernel/src/agent_bridge_flat_v4_encode.rs` with only:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::sideboard_play_policy_v1::FrozenPlayPolicyV1;
    use serde_json::json;

    const DECKS: [&str; 8] = ["Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries"];

    fn bits_value(tensor: &NativeFlatDecisionTensorV4) -> Value {
        serde_json::to_value(tensor_bits_v1(tensor)).unwrap()
    }

    #[test]
    fn extension_tensor_equals_the_harness_tensor_on_live_decisions() {
        let mut harness = FrozenPlayPolicyV1::training_fixture_v4();
        let mut scratch = FlatV4EncodeScratchV1::default();
        let mut checked = 0;
        for (index, deck) in DECKS.iter().enumerate() {
            let mut session = FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(
                900 + index as u64, 31 + index as u64, 400, 40_000,
                [deck.to_string(), deck.to_string()],
            )
            .unwrap();
            for turn in 0..120_u64 {
                let FastActorResponseV1::Decision(decision) = session.current_response() else { break };
                let ours = encode_flat_v4_tensor_v1(&session, &mut scratch).unwrap();
                harness.score_fast_session_v1(&session).unwrap();
                let theirs = harness.last_scored_training_tensor_v4().unwrap();
                assert_eq!(bits_value(&ours), bits_value(theirs), "{deck} decision {turn}");
                checked += 1;
                let row = (turn % u64::from(decision.legal_action_count)) as u32;
                session.step(decision.episode_id, decision.step, row).unwrap();
            }
        }
        assert!(checked >= 400, "only {checked} decisions checked");
    }

    fn max_integer(value: &Value) -> u64 {
        match value {
            Value::Number(number) => number.as_u64().unwrap_or(u64::MAX),
            Value::Array(items) => items.iter().map(max_integer).max().unwrap_or(0),
            Value::Object(map) => map.values().map(max_integer).max().unwrap_or(0),
            _ => 0,
        }
    }

    #[test]
    fn extension_value_carries_identity_row_map_and_safe_integers() {
        let session = FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(
            77, 5, 400, 40_000, ["Burn".to_string(), "Burn".to_string()],
        )
        .unwrap();
        let FastActorResponseV1::Decision(decision) = session.current_response() else { panic!("decision") };
        let tensor = encode_flat_v4_tensor_v1(&session, &mut FlatV4EncodeScratchV1::default()).unwrap();
        let rows: Vec<u32> = (0..decision.legal_action_count).rev().collect();
        let value = flat_v4_extension_value_v1(&tensor, &rows, "p0", decision.step).unwrap();
        assert_eq!(value["schema"], "mtg-kernel-spellbench-flat-v4/v1");
        assert_eq!(value["feature_contract_digest"], "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b");
        assert_eq!(value["feature_encoding_digest"], "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de");
        assert_eq!(value["card_db_hash"], "064a7c989255ab3c");
        assert_eq!(value["acting_seat"], "p0");
        assert_eq!(value["row_candidate_ids"], json!(rows));
        assert_eq!(value["tensor"].as_object().unwrap().len(), 13);
        assert!(max_integer(&value) <= 1_u64 << 53);
    }

    #[test]
    fn a_row_map_of_the_wrong_length_is_refused() {
        let session = FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(
            78, 6, 400, 40_000, ["Burn".to_string(), "Burn".to_string()],
        )
        .unwrap();
        let tensor = encode_flat_v4_tensor_v1(&session, &mut FlatV4EncodeScratchV1::default()).unwrap();
        let actions = tensor.common.action_features.len() / 195;
        let rows: Vec<u32> = (0..actions as u32 + 1).collect();
        assert_eq!(
            flat_v4_extension_value_v1(&tensor, &rows, "p0", 0),
            Err(FlatV4EncodeErrorV1::RowCount { rows: actions + 1, tensor_actions: actions })
        );
    }
}
```
Add `pub(crate) mod agent_bridge_flat_v4_encode;` to `mtg-kernel/src/lib.rs` on the line after `pub mod flat_policy_v4;`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_flat_v4_encode -j 4`
Expected: FAIL to compile with `cannot find function encode_flat_v4_tensor_v1`.

- [ ] **Step 3: Implement the module**

Insert above the test module:

```rust
//! `x_kernel_flat_v4`: the acting seat's V4 model input for the current
//! decision of a flat-action V3 `FastActorSessionV1`, built with the same
//! encoder and tensorizer calls as `FrozenPlayPolicyV1::score_owned`, plus
//! the row to candidate-id map and the feature identities.

use crate::card_def::KERNEL_CARDDB_HASH;
use crate::flat_policy_v2::{
    FlatCompletedDungeonV2, FlatContextPathElementV2, FlatEffectSubtypeChangeV2,
    FlatObjectAbilityUseV2, FlatObjectCoreV2, FlatObjectGoadV2, FlatObjectSubtypeV2,
    FlatRelationV2, FlatScorerActionCoreV2, FlatScorerActionRefV2, FlatScoringDecisionViewV2,
    FlatScoringOwnedBuffersV2,
};
use crate::flat_policy_v4::{FlatDecisionEncoderV4, FlatScoringDecisionViewV4};
use crate::native_flat_tensorizer_v4::{
    NativeFlatDecisionTensorV4, NativeFlatTensorizerV4, FEATURE_CONTRACT_DIGEST_V4,
    FEATURE_ENCODING_DIGEST_V4,
};
use crate::native_policy_value_net_v1::NativePolicyValueModelConfigV1;
use crate::rl_session::{FastActorResponseV1, FastActorSessionV1};
use crate::xmage_observed_inference_v1::ObservedTensorBitsV1;
use serde_json::{json, Value};

pub const SPELLBENCH_EXTENSION_KERNEL_FLAT_V4: &str = "x_kernel_flat_v4";
pub const FLAT_V4_EXTENSION_SCHEMA_V1: &str = "mtg-kernel-spellbench-flat-v4/v1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum FlatV4EncodeErrorV1 {
    NotADecision,
    Encode(String),
    Tensorize(String),
    RowCount { rows: usize, tensor_actions: usize },
}

impl FlatV4EncodeErrorV1 {
    pub(crate) fn halt_reason(&self) -> String {
        let detail = match self {
            Self::NotADecision => "not_a_decision".to_string(),
            Self::Encode(message) => format!("encode:{message}"),
            Self::Tensorize(message) => format!("tensorize:{message}"),
            Self::RowCount { rows, tensor_actions } => format!("row_count:{rows}:{tensor_actions}"),
        };
        format!("engine_contract_failure:flat_v4_encode:{detail}")
    }
}

/// Reused encoder cache and owned tables (the layout of the
/// `flat_policy_v4.rs` test helper `OwnedScoringV4`).
#[derive(Default)]
pub(crate) struct FlatV4EncodeScratchV1 {
    encoder: FlatDecisionEncoderV4,
    objects: Vec<FlatObjectCoreV2>,
    relations: Vec<FlatRelationV2>,
    object_subtypes: Vec<FlatObjectSubtypeV2>,
    ability_uses: Vec<FlatObjectAbilityUseV2>,
    goads: Vec<FlatObjectGoadV2>,
    completed_dungeons: Vec<FlatCompletedDungeonV2>,
    effect_subtype_changes: Vec<FlatEffectSubtypeChangeV2>,
    context_path_elements: Vec<FlatContextPathElementV2>,
    actions: Vec<FlatScorerActionCoreV2>,
    action_refs: Vec<FlatScorerActionRefV2>,
}

pub(crate) fn encode_flat_v4_tensor_v1(
    fast: &FastActorSessionV1,
    scratch: &mut FlatV4EncodeScratchV1,
) -> Result<NativeFlatDecisionTensorV4, FlatV4EncodeErrorV1> {
    let FastActorResponseV1::Decision(expected) = fast.current_response() else {
        return Err(FlatV4EncodeErrorV1::NotADecision);
    };
    let FlatV4EncodeScratchV1 {
        encoder, objects, relations, object_subtypes, ability_uses, goads,
        completed_dungeons, effect_subtype_changes, context_path_elements, actions, action_refs,
    } = scratch;
    let decision = fast
        .encode_current_flat_scoring_decision_owned_v4(
            expected,
            encoder,
            &mut FlatScoringOwnedBuffersV2 {
                objects, relations, object_subtypes, ability_uses, goads, completed_dungeons,
                effect_subtype_changes, context_path_elements, actions, action_refs,
            },
        )
        .map_err(|error| FlatV4EncodeErrorV1::Encode(format!("{error:?}")))?;
    let view = FlatScoringDecisionViewV4::new(
        FlatScoringDecisionViewV2::new(
            &decision.globals, objects, relations, object_subtypes, ability_uses, goads,
            completed_dungeons, effect_subtype_changes, context_path_elements, actions, action_refs,
        ),
        &decision.extensions,
    );
    let mut tensor = NativeFlatDecisionTensorV4::default();
    NativeFlatTensorizerV4::default()
        .fill(view, &mut tensor)
        .map_err(|error| FlatV4EncodeErrorV1::Tensorize(format!("{error:?}")))?;
    Ok(tensor)
}

fn bits(values: &[f32]) -> Vec<u32> {
    values.iter().map(|value| value.to_bits()).collect()
}

pub(crate) fn tensor_bits_v1(tensor: &NativeFlatDecisionTensorV4) -> ObservedTensorBitsV1 {
    let t = &tensor.common;
    ObservedTensorBitsV1 {
        state: bits(&t.state),
        object_features: bits(&t.object_features),
        object_card_ids: t.object_card_ids.clone(),
        object_groups: t.object_groups.clone(),
        object_node_ids: t.object_node_ids.clone(),
        edge_features: bits(&t.edge_features),
        edge_source_indices: t.edge_source_indices.clone(),
        edge_target_indices: t.edge_target_indices.clone(),
        action_features: bits(&t.action_features),
        action_ref_features: bits(&t.action_ref_features),
        action_ref_card_ids: t.action_ref_card_ids.clone(),
        action_ref_action_indices: t.action_ref_action_indices.clone(),
        action_ref_node_indices: t.action_ref_node_indices.clone(),
    }
}

pub(crate) fn flat_v4_extension_value_v1(
    tensor: &NativeFlatDecisionTensorV4,
    row_candidate_ids: &[u32],
    acting_seat: &str,
    step: u64,
) -> Result<Value, FlatV4EncodeErrorV1> {
    let action_dim = NativePolicyValueModelConfigV1::contract_v1().action_feature_dim;
    let features = tensor.common.action_features.len();
    let tensor_actions = features / action_dim;
    if tensor_actions * action_dim != features || tensor_actions != row_candidate_ids.len() {
        return Err(FlatV4EncodeErrorV1::RowCount { rows: row_candidate_ids.len(), tensor_actions });
    }
    Ok(json!({
        "schema": FLAT_V4_EXTENSION_SCHEMA_V1,
        "feature_contract_digest": FEATURE_CONTRACT_DIGEST_V4,
        "feature_encoding_digest": FEATURE_ENCODING_DIGEST_V4,
        "card_db_hash": format!("{KERNEL_CARDDB_HASH:016x}"),
        "acting_seat": acting_seat,
        "step": step,
        "row_candidate_ids": row_candidate_ids,
        "tensor": serde_json::to_value(tensor_bits_v1(tensor)).expect("tensor bits serialize"),
    }))
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_flat_v4_encode -j 4`
Expected: PASS, `3 passed; 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add mtg-kernel/src/agent_bridge_flat_v4_encode.rs mtg-kernel/src/lib.rs
git commit -m "agent bridge: x_kernel_flat_v4 payload from the evaluation encoder"
```

---

### Task 4: Scorer V4 mode with seeded sampling

**Files:**
- Create: `mtg-kernel/src/spellbench_scorer_v1.rs`
- Create: `mtg-kernel/src/bin/spellbench_scorer_v1.rs`
- Modify: `mtg-kernel/src/lib.rs` (insert `pub mod spellbench_scorer_v1;` on the line after `pub mod xmage_observed_inference_v1;`)
- Create (outside repos): `E:/spellbench-archive/kernel-bots/g115.scorer.json`, `a48.scorer.json`, `c12.scorer.json`

A new sibling of `xmage_observed_inference_v1` (which stays byte-identical, V3 only).

**Interfaces:**
- Consumes: `load_expanded_inference_v1(&ExpandedModelSourceV1) -> Result<(FrozenPlayPolicyV1, ExpandedInferenceIdentityV1), String>`; `FrozenPlayPolicyV1::{feature_identity_v1, score_training_tensor_v4}`; `FreshLineageGenerationV1::V4`; `WideCategoricalScratchV1::sample(&mut self, &[f32], u64) -> Result<usize, _>`; `WIDE_CATEGORICAL_SAMPLER_VERSION_V1`; `ObservedTensorBitsV1`.
- Produces (`mtg_kernel::spellbench_scorer_v1`):
  - Schemas: `SCORER_CONFIG_SCHEMA_V1 = "mtg-kernel-spellbench-scorer-config/v1"`, `SCORER_REQUEST_SCHEMA_V1 = "mtg-kernel-spellbench-scorer-request/v1"`, `SCORER_CHOICE_SCHEMA_V1 = "mtg-kernel-spellbench-scorer-choice/v1"`, `SCORER_READY_SCHEMA_V1 = "mtg-kernel-spellbench-scorer-ready/v1"`, `SCORER_ERROR_SCHEMA_V1 = "mtg-kernel-spellbench-scorer-error/v1"`; selections `SELECTION_SAMPLED_WIDE_V1 = "sampled-wide-v1"`, `SELECTION_ARGMAX_FIRST_V1 = "argmax-first-v1"`; `MAX_SCORER_REQUEST_BYTES_V1 = 8 * 1024 * 1024`.
  - `pub struct SpellbenchScorerConfigV1 { pub schema: String, pub source: ExpandedModelSourceV1, pub selection: String }` (serde, deny unknown fields).
  - `pub(crate) struct SpellbenchScorerV1` with `new(policy: FrozenPlayPolicyV1, model: Value, model_state_sha256: String, selection: &str) -> Result<Self, &'static str>`, `ready_record(&self) -> Value`, `score_line(&mut self, bytes: &[u8]) -> Result<Value, &'static str>`.
  - `pub fn run_spellbench_scorer_v1<R: BufRead, W: Write>(config: SpellbenchScorerConfigV1, reader: &mut R, writer: &mut W) -> Result<(), String>` and `pub fn run_spellbench_scorer_config_path_v1<R: BufRead, W: Write>(path: &Path, reader: &mut R, writer: &mut W) -> Result<(), String>`.
  - Bin: `spellbench_scorer_v1 --config PATH`.
  - JSONL: first line ready `{"schema": ready, "model": <ExpandedInferenceIdentityV1>, "model_state_sha256", "feature_contract_digest", "feature_encoding_digest", "card_db_hash", "selection", "sampler_identity", "float_encoding": "ieee754-binary32-u32-bits", "max_request_bytes", "game_state_owned": false}`. Request `{"schema","request_id","game_id","seat","step","feature_contract_digest","feature_encoding_digest","row_candidate_ids":[u32],"sample_seed":u64|null,"tensor":{13 arrays}}`. Choice `{"schema","request_id","request_sha256","model_state_sha256","selection","logits_bits":[u32],"value_bits":u32,"selected_row":u32,"selected_candidate_id":u32}`. Any rejected record emits `{"schema": error, "code", "service_continues": false}` and exits nonzero.

- [ ] **Step 1: Write the failing tests**

Create `mtg-kernel/src/spellbench_scorer_v1.rs` with only:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::rl_session::{FastActorResponseV1, FastActorSessionV1};
    use crate::state::SplitMix64;
    use std::io::Cursor;

    fn request_bits(tensor: &NativeFlatDecisionTensorV4) -> ObservedTensorBitsV1 {
        let b = |values: &[f32]| values.iter().map(|value| value.to_bits()).collect::<Vec<u32>>();
        let t = &tensor.common;
        ObservedTensorBitsV1 {
            state: b(&t.state), object_features: b(&t.object_features),
            object_card_ids: t.object_card_ids.clone(), object_groups: t.object_groups.clone(),
            object_node_ids: t.object_node_ids.clone(), edge_features: b(&t.edge_features),
            edge_source_indices: t.edge_source_indices.clone(), edge_target_indices: t.edge_target_indices.clone(),
            action_features: b(&t.action_features), action_ref_features: b(&t.action_ref_features),
            action_ref_card_ids: t.action_ref_card_ids.clone(),
            action_ref_action_indices: t.action_ref_action_indices.clone(),
            action_ref_node_indices: t.action_ref_node_indices.clone(),
        }
    }

    /// A live Rally decision with at least two candidates, the harness's
    /// logits on it, and a scorer request with a reversed row map.
    fn live_case(sample_seed: Option<u64>) -> (FastActorSessionV1, Vec<f32>, Vec<u32>, Vec<u8>) {
        let mut session = FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(
            4242, 17, 400, 40_000, ["Rally".to_string(), "Rally".to_string()],
        )
        .unwrap();
        loop {
            let FastActorResponseV1::Decision(decision) = session.current_response() else { panic!("game ended") };
            if decision.legal_action_count >= 2 { break }
            session.step(decision.episode_id, decision.step, 0).unwrap();
        }
        let mut harness = FrozenPlayPolicyV1::training_fixture_v4();
        let scores = harness.score_fast_session_v1(&session).unwrap();
        let tensor = harness.last_scored_training_tensor_v4().unwrap().clone();
        let rows: Vec<u32> = (0..scores.logits.len() as u32).rev().collect();
        let request = json!({
            "schema": SCORER_REQUEST_SCHEMA_V1, "request_id": "m0000p0000g0:5", "game_id": "m0000p0000g0",
            "seat": "p0", "step": 5,
            "feature_contract_digest": FEATURE_CONTRACT_DIGEST_V4,
            "feature_encoding_digest": FEATURE_ENCODING_DIGEST_V4,
            "row_candidate_ids": rows, "sample_seed": sample_seed,
            "tensor": serde_json::to_value(request_bits(&tensor)).unwrap(),
        });
        (session, scores.logits, rows, serde_json::to_vec(&request).unwrap())
    }

    fn scorer(selection: &str) -> SpellbenchScorerV1 {
        SpellbenchScorerV1::new(
            FrozenPlayPolicyV1::training_fixture_v4(), json!({"fixture": true}), "0".repeat(64), selection,
        )
        .unwrap()
    }

    #[test]
    fn argmax_scorer_reproduces_the_harness_logits_and_first_argmax() {
        let (_, logits, rows, bytes) = live_case(None);
        let choice = scorer(SELECTION_ARGMAX_FIRST_V1).score_line(&bytes).unwrap();
        let expected: Vec<u32> = logits.iter().map(|value| value.to_bits()).collect();
        assert_eq!(choice["logits_bits"], json!(expected));
        let row = first_argmax(&logits).unwrap();
        assert_eq!(choice["selected_row"], json!(row));
        assert_eq!(choice["selected_candidate_id"], json!(rows[row]));
        assert_eq!(choice["request_sha256"], format!("{:x}", Sha256::digest(&bytes)));
    }

    #[test]
    fn sampled_scorer_matches_the_harness_selection_for_the_same_seat_stream() {
        let seat_seed = 6_130_830_677_676_653_025_u64;
        let sample_seed = SplitMix64::seed(seat_seed).next_u64();
        let (session, _, rows, bytes) = live_case(Some(sample_seed));
        let choice = scorer(SELECTION_SAMPLED_WIDE_V1).score_line(&bytes).unwrap();
        let mut harness = FrozenPlayPolicyV1::training_fixture_v4();
        harness.reset_sampling_v1([seat_seed, seat_seed]);
        let harness_row = harness.select_fast_session_v1(&session).unwrap() as usize;
        assert_eq!(choice["selected_row"], json!(harness_row));
        assert_eq!(choice["selected_candidate_id"], json!(rows[harness_row]));
    }

    #[test]
    fn malformed_requests_fail_closed() {
        let (_, _, _, sampled) = live_case(Some(7));
        let (_, _, _, unseeded) = live_case(None);
        let edit = |bytes: &[u8], edit: &dyn Fn(&mut Value)| {
            let mut value: Value = serde_json::from_slice(bytes).unwrap();
            edit(&mut value);
            serde_json::to_vec(&value).unwrap()
        };
        let mut sampler = scorer(SELECTION_SAMPLED_WIDE_V1);
        assert_eq!(sampler.score_line(&edit(&sampled, &|v| v["feature_contract_digest"] = json!("0".repeat(64)))), Err("request_feature_contract"));
        assert_eq!(sampler.score_line(&edit(&sampled, &|v| v["row_candidate_ids"][1] = v["row_candidate_ids"][0].clone())), Err("row_candidate_ids"));
        assert_eq!(sampler.score_line(&edit(&sampled, &|v| { v["row_candidate_ids"].as_array_mut().unwrap().pop(); })), Err("row_count"));
        assert_eq!(sampler.score_line(&edit(&sampled, &|v| v["opponent_hand"] = json!([1]))), Err("request_json"));
        assert_eq!(sampler.score_line(&unseeded), Err("sample_seed"));
        assert_eq!(scorer(SELECTION_ARGMAX_FIRST_V1).score_line(&sampled), Err("sample_seed"));
    }

    #[test]
    fn serve_loop_answers_each_line_then_stops_at_the_first_rejection() {
        let (_, _, _, bytes) = live_case(Some(9));
        let mut input = bytes.clone();
        input.extend_from_slice(b"\r\n");
        input.extend_from_slice(&bytes);
        input.extend_from_slice(b"\nnot json\n");
        let mut output = Vec::new();
        let mut scorer = scorer(SELECTION_SAMPLED_WIDE_V1);
        let result = serve_scorer_v1(&mut scorer, &mut Cursor::new(input), &mut output);
        assert_eq!(result, Err("request_json".to_string()));
        let lines: Vec<Value> = output.split(|b| *b == b'\n').filter(|l| !l.is_empty()).map(|l| serde_json::from_slice(l).unwrap()).collect();
        assert_eq!(lines.len(), 3);
        assert_eq!(lines[0]["schema"], SCORER_CHOICE_SCHEMA_V1);
        assert_eq!(lines[1], lines[0]);
        assert_eq!(lines[2]["code"], "request_json");
    }

    #[test]
    fn load_failure_emits_one_error_record_and_stops() {
        let config: SpellbenchScorerConfigV1 = serde_json::from_value(json!({
            "schema": SCORER_CONFIG_SCHEMA_V1, "selection": SELECTION_SAMPLED_WIDE_V1,
            "source": {
                "play_import": {"path": "E:/does-not-exist/descriptor.json", "sha256": "0".repeat(64)},
                "feature_transfer": {
                    "expected_feature_contract_digest": FEATURE_CONTRACT_DIGEST_V4,
                    "expected_feature_encoding_digest": FEATURE_ENCODING_DIGEST_V4
                },
                "checkpoint": null
            }
        }))
        .unwrap();
        let mut output = Vec::new();
        let result = run_spellbench_scorer_v1(config, &mut Cursor::new(Vec::new()), &mut output);
        assert_eq!(result, Err("checkpoint_load".to_string()));
        let record: Value = serde_json::from_slice(output.split(|b| *b == b'\n').next().unwrap()).unwrap();
        assert_eq!(record, json!({"schema": SCORER_ERROR_SCHEMA_V1, "code": "checkpoint_load", "service_continues": false}));
    }

    #[test]
    fn ready_record_names_the_v4_identity_and_selection() {
        let ready = scorer(SELECTION_SAMPLED_WIDE_V1).ready_record();
        assert_eq!(ready["schema"], SCORER_READY_SCHEMA_V1);
        assert_eq!(ready["feature_contract_digest"], FEATURE_CONTRACT_DIGEST_V4);
        assert_eq!(ready["card_db_hash"], "064a7c989255ab3c");
        assert_eq!(ready["selection"], "sampled-wide-v1");
        assert_eq!(ready["sampler_identity"], "f32-q8-expq63-hamilton-splitmix64-wide-v1");
    }

    /// Needs SPELLBENCH_KERNEL_BOT_CONFIG_DIR=E:/spellbench-archive/kernel-bots.
    #[test]
    #[ignore = "loads the real Phase 1 checkpoints"]
    fn real_phase1_models_load_with_their_pinned_state() {
        let dir = std::path::PathBuf::from(std::env::var("SPELLBENCH_KERNEL_BOT_CONFIG_DIR").unwrap());
        for (name, state) in [
            ("g115", "8139016ca561961714f25e22a9d6f7fc888548fc332e45b6bce402dfc43159f2"),
            ("a48", "774e936da26468358257774fe41ae94578265b331d2edb49d017c0835b08699a"),
            ("c12", "5c14c025e3cc87fb2c3eea28e1dbd770d7d257344174296d6259020f720da9de"),
        ] {
            let mut output = Vec::new();
            run_spellbench_scorer_config_path_v1(&dir.join(format!("{name}.scorer.json")), &mut Cursor::new(Vec::new()), &mut output).unwrap();
            let ready: Value = serde_json::from_slice(output.split(|b| *b == b'\n').next().unwrap()).unwrap();
            assert_eq!(ready["model_state_sha256"], state, "{name}");
            if name == "g115" {
                assert_eq!(ready["model"]["model"]["weights_sha256"], "e2ca2f2b5dd750a59e24c71a4bac325ed7449d97b5892a79a80132e45d538333");
            }
        }
    }
}
```
Add `pub mod spellbench_scorer_v1;` to `mtg-kernel/src/lib.rs` on the line after `pub mod xmage_observed_inference_v1;`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib spellbench_scorer_v1 -j 4`
Expected: FAIL to compile with `cannot find struct SpellbenchScorerV1`.

- [ ] **Step 3: Implement the module**

Insert above the test module:

```rust
//! Stateless Spellbench scorer for fresh-lineage V4 policies (g115, A48,
//! c12). Loads one pinned model source, answers JSONL requests carrying the
//! `x_kernel_flat_v4` tensor, and returns the chosen row and candidate id.
//! Owns no game state. `xmage_observed_inference_v1` (V3 only) is unchanged.

use crate::card_def::KERNEL_CARDDB_HASH;
use crate::expanded_deck_training_v1::{load_expanded_inference_v1, ExpandedModelSourceV1};
use crate::fast_sampler::{WideCategoricalScratchV1, WIDE_CATEGORICAL_SAMPLER_VERSION_V1};
use crate::native_flat_tensorizer_v2::NativeFlatDecisionTensorV2;
use crate::native_flat_tensorizer_v4::{
    NativeFlatDecisionTensorV4, FEATURE_CONTRACT_DIGEST_V4, FEATURE_ENCODING_DIGEST_V4,
};
use crate::sideboard_play_policy_v1::{FreshLineageGenerationV1, FrozenPlayPolicyV1};
use crate::xmage_observed_inference_v1::ObservedTensorBitsV1;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::File;
use std::io::{BufRead, Read, Write};
use std::path::Path;

pub const SCORER_CONFIG_SCHEMA_V1: &str = "mtg-kernel-spellbench-scorer-config/v1";
pub const SCORER_REQUEST_SCHEMA_V1: &str = "mtg-kernel-spellbench-scorer-request/v1";
pub const SCORER_CHOICE_SCHEMA_V1: &str = "mtg-kernel-spellbench-scorer-choice/v1";
pub const SCORER_READY_SCHEMA_V1: &str = "mtg-kernel-spellbench-scorer-ready/v1";
pub const SCORER_ERROR_SCHEMA_V1: &str = "mtg-kernel-spellbench-scorer-error/v1";
pub const SELECTION_SAMPLED_WIDE_V1: &str = "sampled-wide-v1";
pub const SELECTION_ARGMAX_FIRST_V1: &str = "argmax-first-v1";
pub const MAX_SCORER_REQUEST_BYTES_V1: usize = 8 * 1024 * 1024;
const MAX_CONFIG_BYTES_V1: u64 = 1024 * 1024;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SpellbenchScorerConfigV1 {
    pub schema: String,
    pub source: ExpandedModelSourceV1,
    pub selection: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SpellbenchScorerRequestV1 {
    schema: String,
    request_id: String,
    game_id: String,
    seat: String,
    step: u64,
    feature_contract_digest: String,
    feature_encoding_digest: String,
    row_candidate_ids: Vec<u32>,
    #[serde(default)]
    sample_seed: Option<u64>,
    tensor: ObservedTensorBitsV1,
}

fn into_tensor_v4(bits: ObservedTensorBitsV1) -> NativeFlatDecisionTensorV4 {
    let floats = |values: Vec<u32>| values.into_iter().map(f32::from_bits).collect();
    NativeFlatDecisionTensorV4 {
        common: NativeFlatDecisionTensorV2 {
            state: floats(bits.state),
            object_features: floats(bits.object_features),
            object_card_ids: bits.object_card_ids,
            object_groups: bits.object_groups,
            object_node_ids: bits.object_node_ids,
            edge_features: floats(bits.edge_features),
            edge_source_indices: bits.edge_source_indices,
            edge_target_indices: bits.edge_target_indices,
            action_features: floats(bits.action_features),
            action_ref_features: floats(bits.action_ref_features),
            action_ref_card_ids: bits.action_ref_card_ids,
            action_ref_action_indices: bits.action_ref_action_indices,
            action_ref_node_indices: bits.action_ref_node_indices,
        },
    }
}

fn first_argmax(logits: &[f32]) -> Option<usize> {
    if logits.is_empty() || logits.iter().any(|value| !value.is_finite()) {
        return None;
    }
    let mut selected = 0;
    for index in 1..logits.len() {
        if logits[index] > logits[selected] {
            selected = index;
        }
    }
    Some(selected)
}

pub(crate) struct SpellbenchScorerV1 {
    policy: FrozenPlayPolicyV1,
    model: Value,
    model_state_sha256: String,
    selection: &'static str,
    sampler: WideCategoricalScratchV1,
}

impl SpellbenchScorerV1 {
    pub(crate) fn new(
        policy: FrozenPlayPolicyV1,
        model: Value,
        model_state_sha256: String,
        selection: &str,
    ) -> Result<Self, &'static str> {
        let selection = match selection {
            SELECTION_SAMPLED_WIDE_V1 => SELECTION_SAMPLED_WIDE_V1,
            SELECTION_ARGMAX_FIRST_V1 => SELECTION_ARGMAX_FIRST_V1,
            _ => return Err("selection"),
        };
        if policy.feature_identity_v1().generation != FreshLineageGenerationV1::V4 {
            return Err("model_generation_unsupported");
        }
        Ok(Self { policy, model, model_state_sha256, selection, sampler: WideCategoricalScratchV1::default() })
    }

    pub(crate) fn ready_record(&self) -> Value {
        json!({
            "schema": SCORER_READY_SCHEMA_V1,
            "model": self.model,
            "model_state_sha256": self.model_state_sha256,
            "feature_contract_digest": FEATURE_CONTRACT_DIGEST_V4,
            "feature_encoding_digest": FEATURE_ENCODING_DIGEST_V4,
            "card_db_hash": format!("{KERNEL_CARDDB_HASH:016x}"),
            "selection": self.selection,
            "sampler_identity": WIDE_CATEGORICAL_SAMPLER_VERSION_V1,
            "float_encoding": "ieee754-binary32-u32-bits",
            "max_request_bytes": MAX_SCORER_REQUEST_BYTES_V1,
            "game_state_owned": false,
        })
    }

    pub(crate) fn score_line(&mut self, bytes: &[u8]) -> Result<Value, &'static str> {
        let request: SpellbenchScorerRequestV1 = serde_json::from_slice(bytes).map_err(|_| "request_json")?;
        if request.schema != SCORER_REQUEST_SCHEMA_V1 {
            return Err("request_schema");
        }
        if request.feature_contract_digest != FEATURE_CONTRACT_DIGEST_V4
            || request.feature_encoding_digest != FEATURE_ENCODING_DIGEST_V4
        {
            return Err("request_feature_contract");
        }
        if request.request_id.is_empty() || request.game_id.is_empty() || !matches!(request.seat.as_str(), "p0" | "p1") {
            return Err("request_identity");
        }
        let rows = request.row_candidate_ids.len();
        if rows == 0 || request.row_candidate_ids.iter().collect::<BTreeSet<_>>().len() != rows {
            return Err("row_candidate_ids");
        }
        let seed = match (self.selection, request.sample_seed) {
            (SELECTION_SAMPLED_WIDE_V1, Some(seed)) => Some(seed),
            (SELECTION_ARGMAX_FIRST_V1, None) => None,
            _ => return Err("sample_seed"),
        };
        let output = self
            .policy
            .score_training_tensor_v4(&into_tensor_v4(request.tensor))
            .map_err(|_| "native_inference")?;
        if output.logits.len() != rows {
            return Err("row_count");
        }
        if !output.value.is_finite() || output.logits.iter().any(|value| !value.is_finite()) {
            return Err("invalid_model_output");
        }
        let selected = match seed {
            Some(seed) => self.sampler.sample(&output.logits, seed).map_err(|_| "sampler")?,
            None => first_argmax(&output.logits).ok_or("invalid_model_output")?,
        };
        Ok(json!({
            "schema": SCORER_CHOICE_SCHEMA_V1,
            "request_id": request.request_id,
            "request_sha256": format!("{:x}", Sha256::digest(bytes)),
            "model_state_sha256": self.model_state_sha256,
            "selection": self.selection,
            "logits_bits": output.logits.iter().map(|value| value.to_bits()).collect::<Vec<_>>(),
            "value_bits": output.value.to_bits(),
            "selected_row": selected,
            "selected_candidate_id": request.row_candidate_ids[selected],
        }))
    }
}

/// One bounded JSONL record; a trailing `\r` is dropped (xmage framing).
fn read_record<R: BufRead>(reader: &mut R, limit: usize) -> Result<Option<Vec<u8>>, &'static str> {
    let mut bytes = Vec::new();
    loop {
        let buffer = reader.fill_buf().map_err(|_| "input_io")?;
        if buffer.is_empty() {
            return Ok((!bytes.is_empty()).then_some(bytes));
        }
        let newline = buffer.iter().position(|byte| *byte == b'\n');
        let take = newline.unwrap_or(buffer.len());
        if bytes.len().checked_add(take).is_none_or(|size| size > limit) {
            return Err("request_too_large");
        }
        bytes.extend_from_slice(&buffer[..take]);
        reader.consume(take + usize::from(newline.is_some()));
        if newline.is_some() {
            if bytes.last() == Some(&b'\r') {
                bytes.pop();
            }
            return Ok(Some(bytes));
        }
    }
}

fn write_record<W: Write>(writer: &mut W, value: &Value) -> Result<(), String> {
    serde_json::to_writer(&mut *writer, value).map_err(|_| "output_json".to_string())?;
    writer.write_all(b"\n").map_err(|_| "output_io".to_string())?;
    writer.flush().map_err(|_| "output_io".to_string())
}

fn error_record(code: &str) -> Value {
    json!({"schema": SCORER_ERROR_SCHEMA_V1, "code": code, "service_continues": false})
}

pub(crate) fn serve_scorer_v1<R: BufRead, W: Write>(
    scorer: &mut SpellbenchScorerV1,
    reader: &mut R,
    writer: &mut W,
) -> Result<(), String> {
    loop {
        let result = match read_record(reader, MAX_SCORER_REQUEST_BYTES_V1) {
            Ok(None) => return Ok(()),
            Ok(Some(bytes)) => scorer.score_line(&bytes),
            Err(code) => Err(code),
        };
        match result {
            Ok(value) => write_record(writer, &value)?,
            Err(code) => {
                write_record(writer, &error_record(code))?;
                return Err(code.into());
            }
        }
    }
}

pub fn run_spellbench_scorer_v1<R: BufRead, W: Write>(
    config: SpellbenchScorerConfigV1,
    reader: &mut R,
    writer: &mut W,
) -> Result<(), String> {
    if config.schema != SCORER_CONFIG_SCHEMA_V1 {
        write_record(writer, &error_record("config_schema"))?;
        return Err("config_schema".into());
    }
    let (policy, identity) = match load_expanded_inference_v1(&config.source) {
        Ok(loaded) => loaded,
        Err(message) => {
            eprintln!("spellbench scorer: checkpoint load failed: {message}");
            write_record(writer, &error_record("checkpoint_load"))?;
            return Err("checkpoint_load".into());
        }
    };
    let model = serde_json::to_value(&identity).map_err(|_| "identity_json".to_string())?;
    let mut scorer = match SpellbenchScorerV1::new(policy, model, identity.state_sha256.clone(), &config.selection) {
        Ok(scorer) => scorer,
        Err(code) => {
            write_record(writer, &error_record(code))?;
            return Err(code.into());
        }
    };
    write_record(writer, &scorer.ready_record())?;
    serve_scorer_v1(&mut scorer, reader, writer)
}

pub fn run_spellbench_scorer_config_path_v1<R: BufRead, W: Write>(
    path: &Path,
    reader: &mut R,
    writer: &mut W,
) -> Result<(), String> {
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|_| "config_open".to_string())?
        .take(MAX_CONFIG_BYTES_V1 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "config_read".to_string())?;
    if bytes.len() as u64 > MAX_CONFIG_BYTES_V1 {
        return Err("config_too_large".into());
    }
    let config = serde_json::from_slice(&bytes).map_err(|_| "config_json".to_string())?;
    run_spellbench_scorer_v1(config, reader, writer)
}
```

Create `mtg-kernel/src/bin/spellbench_scorer_v1.rs`:

```rust
use mtg_kernel::spellbench_scorer_v1::run_spellbench_scorer_config_path_v1;
use std::path::PathBuf;

fn run() -> Result<(), String> {
    let mut arguments = std::env::args_os().skip(1);
    if arguments.next().as_deref() != Some(std::ffi::OsStr::new("--config")) {
        return Err("usage: spellbench_scorer_v1 --config PATH".into());
    }
    let config = PathBuf::from(arguments.next().ok_or("missing config path")?);
    if arguments.next().is_some() {
        return Err("unexpected argument".into());
    }
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    run_spellbench_scorer_config_path_v1(&config, &mut stdin.lock(), &mut stdout.lock())
}

fn main() {
    if let Err(code) = run() {
        eprintln!("spellbench scorer: {code}");
        std::process::exit(1);
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib spellbench_scorer_v1 -j 4`
Expected: PASS, `6 passed; 0 failed; 1 ignored`.

- [ ] **Step 5: Write the three scorer configs and run the real-model test**

Create `E:/spellbench-archive/kernel-bots/g115.scorer.json`:
```json
{
  "schema": "mtg-kernel-spellbench-scorer-config/v1",
  "selection": "sampled-wide-v1",
  "source": {
    "play_import": {"path": "E:/mtg-kernel-learned-sideboarding-evidence/bo3-post480-preparation-001/phase1-training-qualification-001/campaign-001/block1/catalog/b-descriptor-windows.json", "sha256": "6c2fcb3730e23df685836527f69ef3c2092c0bd121d7aedfc26e54072c60e808"},
    "feature_transfer": {"expected_feature_contract_digest": "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b", "expected_feature_encoding_digest": "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"},
    "checkpoint": {"path": "D:/phase1-live/campaign-002/g/block115/run/iterations/000199/attempt-000000/update/checkpoint.json", "sha256": "88c0b997708c2b5156b44f3940ad9d5d682f78ac24d346978bb3c9f34c59e8d1"}
  }
}
```
`a48.scorer.json`: same with play_import `.../catalog/a-descriptor-windows.json` sha256 `7b39fa26ef0ca72d7e3d660f32a266ef82692739b4d44f1870630fbd463d28f7` and checkpoint `D:/phase1-live/campaign-002/a/block48/run/iterations/000199/attempt-000000/update/checkpoint.json` sha256 `beb86b4116c6eaa8406f12eb391adde1a637e063375740ea0b9812251bcff4a4`. `c12.scorer.json`: the g115 play_import and checkpoint `D:/phase1-live/campaign-002/c/block12/run/iterations/000199/attempt-000000/update/checkpoint.json` sha256 `993373f3e107e31f4be2ca0f368d2b1dd69b8088e59a81ea8257776c5bbc6abf`.

Run: `SPELLBENCH_KERNEL_BOT_CONFIG_DIR=E:/spellbench-archive/kernel-bots CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib real_phase1_models_load_with_their_pinned_state -j 4 -- --ignored`
Expected: PASS, `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add mtg-kernel/src/spellbench_scorer_v1.rs mtg-kernel/src/bin/spellbench_scorer_v1.rs mtg-kernel/src/lib.rs
git commit -m "spellbench scorer: pinned V4 policy scoring with seeded training sampler"
```

---

### Task 5: Stdlib Python bot in Spellbench

**Files:**
- Create: `integrations/mtg_kernel/kernel_flat_bot.py`
- Create: `integrations/mtg_kernel/README.md`
- Create: `integrations/mtg_kernel/tests/fake_scorer.py`
- Create: `integrations/mtg_kernel/tests/test_kernel_flat_bot.py`
- Modify: `python/tests/test_engine_conformance.py` (engine arguments)
- Modify: `.github/workflows/ci.yml` (`Run tests` step)

**Interfaces:**
- Consumes: `spellbench.agent_server.serve(handler, bot_name=, bot_version=, extensions_accepted=)`; `spellbench.arena.bots.uniform.SplitMix64` (`.next() -> int`); the scorer JSONL of Task 4 (schemas and fields exactly as listed there); the extension wire of Task 3.
- Produces:
  - CLI `kernel_flat_bot.py --scorer PATH [--scorer-arg ARG]... --config PATH --name NAME --version VERSION [--seed N] [--decision-log DIR]`; the scorer runs as `[scorer, *scorer_args, "--config", config]`.
  - `seat_stream_seed(seed: int, game_id: str, seat: str) -> int`: `(seed ^ int.from_bytes(sha256(b"spellbench-kernel-flat-bot/v1" + b"\0" + game_id + b"\0" + seat)[:8], "big")) & (2**64 - 1)`.
  - Decision log (consumed by Task 7): `<DIR>/<game_id>.<seat>.jsonl`; first line `{"schema":"spellbench-kernel-bot-log/v1","kind":"header","game_id","seat","bot_name","bot_version","selection","stream_seed","model_state_sha256"}`; then one line per decision `{"kind":"decision","step","candidate_id","selected_row","sample_seed","logits_bits","value_bits","request_sha256","elapsed_us"}`.
  - `SPELLBENCH_ENGINE_ARGS` (space-separated) in the conformance test.

- [ ] **Step 1: Write the scorer test double**

Create `integrations/mtg_kernel/tests/fake_scorer.py`:

```python
"""Test double for mtg-kernel spellbench_scorer_v1: same JSONL records, no model.

Picks row sample_seed % len(row_candidate_ids). --mode: ok, no-ready,
wrong-digest, die-after-1.
"""

from __future__ import annotations

import hashlib
import json
import sys

CONTRACT = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
ENCODING = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"


def emit(value: dict) -> None:
    sys.stdout.buffer.write(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    mode = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "ok"
    if mode == "no-ready":
        return 0
    emit({
        "schema": "mtg-kernel-spellbench-scorer-ready/v1", "model": {"fake": True},
        "model_state_sha256": "0" * 64,
        "feature_contract_digest": "0" * 64 if mode == "wrong-digest" else CONTRACT,
        "feature_encoding_digest": ENCODING, "card_db_hash": "064a7c989255ab3c",
        "selection": "sampled-wide-v1", "sampler_identity": "f32-q8-expq63-hamilton-splitmix64-wide-v1",
        "float_encoding": "ieee754-binary32-u32-bits", "max_request_bytes": 8388608, "game_state_owned": False,
    })
    served = 0
    for raw in sys.stdin.buffer:
        line = raw.rstrip(b"\r\n")
        if mode == "die-after-1" and served == 1:
            return 3
        request = json.loads(line)
        rows = request["row_candidate_ids"]
        row = request["sample_seed"] % len(rows)
        emit({
            "schema": "mtg-kernel-spellbench-scorer-choice/v1", "request_id": request["request_id"],
            "request_sha256": hashlib.sha256(line).hexdigest(), "model_state_sha256": "0" * 64,
            "selection": "sampled-wide-v1", "logits_bits": [0] * len(rows), "value_bits": 0,
            "selected_row": row, "selected_candidate_id": rows[row],
        })
        served += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing tests**

Create `integrations/mtg_kernel/tests/test_kernel_flat_bot.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kernel_flat_bot as bot_module  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.agent_client import AgentProcess  # noqa: E402
from spellbench.errors import RemoteError, TransportError  # noqa: E402
from spellbench.models import Decision  # noqa: E402

HERE = Path(__file__).resolve().parent
BOT = HERE.parent / "kernel_flat_bot.py"
FAKE = HERE / "fake_scorer.py"
GAME_ID = "m0000p0000g0"
KERNEL_ENGINE = {
    "name": "mtg-kernel", "version": "0.0.4-spike", "source_revision": None,
    "rules_snapshot_id": "mtg-kernel-rules/0.0.4-spike/carddb-064a7c989255ab3c",
    "card_pool_identity": "mtg-kernel-pauper-pool-v1/carddb-064a7c989255ab3c",
}
OBJ = {"object_id": "obj-000001", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
BOLT = dict(OBJ, object_id="obj-000002", card_name="Lightning Bolt")


def bot_argv(tmp_path: Path, mode: str = "ok", log: Path | None = None) -> list[str]:
    argv = [
        sys.executable, str(BOT), "--scorer", sys.executable, "--scorer-arg", str(FAKE),
        "--scorer-arg=--mode", f"--scorer-arg={mode}", "--config", str(tmp_path / "unused.json"),
        "--name", "g115-test", "--version", "1.0.0",
    ]
    return argv + (["--decision-log", str(log)] if log is not None else [])


def make_decision(rows: list[int] | None, *, step: int = 0) -> Decision:
    candidates = [
        {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None},
        {"candidate_id": 1, "semantic": {"kind": "play_land", "source": OBJ}, "display_text": None},
        {"candidate_id": 2, "semantic": {"kind": "cast_spell", "source": BOLT}, "display_text": None},
    ]
    seats = [
        {"seat": seat, "life": 20, "hand_count": 7, "library_count": 53, "graveyard_count": 0, "battlefield_count": 0}
        for seat in ("p0", "p1")
    ]
    extensions = {}
    if rows is not None:
        extensions["x_kernel_flat_v4"] = {
            "schema": "mtg-kernel-spellbench-flat-v4/v1",
            "feature_contract_digest": bot_module.FEATURE_CONTRACT_DIGEST,
            "feature_encoding_digest": bot_module.FEATURE_ENCODING_DIGEST,
            "card_db_hash": "064a7c989255ab3c", "acting_seat": "p0", "step": step,
            "row_candidate_ids": rows, "tensor": {key: [] for key in sorted(bot_module.TENSOR_KEYS)},
        }
    return Decision.from_json({
        "response_type": "decision", "protocol": "spellbench/v1", "request_id": f"e-{step}",
        "game_id": GAME_ID, "step": step, "acting_seat": "p0",
        "group": {"group_id": step, "substep_index": 0, "substep_count": 1},
        "state_summary": {"turn": 1, "phase_step": "precombat_main", "active_seat": "p0",
                          "priority_seat": "p0", "seats": seats, "stack_count": 0},
        "candidates": candidates, "candidates_sha256": wire.candidates_sha256(candidates),
        "provenance": {"engine_name": "mtg-kernel", "engine_version": "0.0.4-spike",
                       "rules_snapshot_id": KERNEL_ENGINE["rules_snapshot_id"],
                       "card_pool_identity": KERNEL_ENGINE["card_pool_identity"]},
        "extensions": extensions,
    })


def start(agent: AgentProcess, engine: dict = KERNEL_ENGINE) -> None:
    agent.hello()
    agent.game_start(game_id=GAME_ID, seat="p0", format="pauper-bo1",
                     decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], engine=engine)


def test_seat_stream_seed_matches_the_pinned_vectors() -> None:
    assert bot_module.seat_stream_seed(0, GAME_ID, "p0") == 6130830677676653025
    assert bot_module.seat_stream_seed(0, GAME_ID, "p1") == 14732225731661844387
    rng = bot_module.SplitMix64(6130830677676653025)
    assert [rng.next(), rng.next()] == [14661015056425920609, 10495553203978975665]


def test_choose_maps_the_scorer_row_through_row_candidate_ids(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path, log=tmp_path / "log"), timeout_s=30) as agent:
        start(agent)
        selection = agent.choose(make_decision([1, 2, 0]))
    # First draw 14661015056425920609 % 3 == 0: row 0, which is candidate 1.
    assert selection.candidate_id == 1
    lines = (tmp_path / "log" / f"{GAME_ID}.p0.jsonl").read_text(encoding="utf-8").splitlines()
    header, entry = json.loads(lines[0]), json.loads(lines[1])
    assert header["schema"] == "spellbench-kernel-bot-log/v1"
    assert header["stream_seed"] == 6130830677676653025
    assert header["selection"] == "sampled-wide-v1"
    assert (entry["sample_seed"], entry["selected_row"], entry["candidate_id"]) == (14661015056425920609, 0, 1)


def test_missing_extension_is_an_internal_error(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        start(agent)
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision(None))
    assert caught.value.code == "internal_error"


def test_row_map_outside_the_candidates_is_refused(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        start(agent)
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision([0, 5]))
    assert caught.value.code == "internal_error"


def test_wrong_engine_card_registry_fails_game_start(tmp_path: Path) -> None:
    old = dict(KERNEL_ENGINE, rules_snapshot_id="mtg-kernel-rules/0.0.4-spike/carddb-64c82a261e078f1a",
               card_pool_identity="mtg-kernel-pauper-pool-v1/carddb-64c82a261e078f1a")
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        agent.hello()
        with pytest.raises(RemoteError) as caught:
            agent.game_start(game_id=GAME_ID, seat="p0", format="pauper-bo1",
                             decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], engine=old)
    assert caught.value.code == "internal_error"


@pytest.mark.parametrize("mode", ["no-ready", "wrong-digest"])
def test_bot_exits_before_hello_when_the_scorer_never_becomes_ready(tmp_path: Path, mode: str) -> None:
    with AgentProcess(bot_argv(tmp_path, mode=mode), timeout_s=30) as agent:
        with pytest.raises(TransportError):
            agent.hello()


def test_scorer_death_mid_game_is_an_internal_error(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path, mode="die-after-1"), timeout_s=30) as agent:
        start(agent)
        agent.choose(make_decision([1, 2, 0], step=0))
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision([1, 2, 0], step=1))
    assert caught.value.code == "internal_error"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd $SB && uv run --no-sync pytest integrations -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kernel_flat_bot'`.

- [ ] **Step 4: Write the bot**

Create `integrations/mtg_kernel/kernel_flat_bot.py`:

```python
"""Spellbench agent for mtg-kernel Phase 1 policies (g115, A48, c12).

The mtg-kernel bridge run with --x-kernel-flat-v4 attaches the acting seat's
model input to every decision as x_kernel_flat_v4: the actor-visible V4
tensor from the kernel's own encoder plus the map from model rows to
Spellbench candidate ids. This bot forwards the tensor to the native scorer
(mtg-kernel spellbench_scorer_v1), which loads one pinned checkpoint and
picks a row, and answers with the mapped candidate id. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from spellbench.agent_server import serve  # noqa: E402
from spellbench.arena.bots.uniform import SplitMix64  # noqa: E402
from spellbench.models import Decision, GameOverRequest, GameStartRequest  # noqa: E402

EXTENSION = "x_kernel_flat_v4"
EXTENSION_SCHEMA = "mtg-kernel-spellbench-flat-v4/v1"
REQUEST_SCHEMA = "mtg-kernel-spellbench-scorer-request/v1"
CHOICE_SCHEMA = "mtg-kernel-spellbench-scorer-choice/v1"
READY_SCHEMA = "mtg-kernel-spellbench-scorer-ready/v1"
LOG_SCHEMA = "spellbench-kernel-bot-log/v1"
FEATURE_CONTRACT_DIGEST = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
FEATURE_ENCODING_DIGEST = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"
SAMPLED = "sampled-wide-v1"
ARGMAX = "argmax-first-v1"
TENSOR_KEYS = frozenset({
    "state", "object_features", "object_card_ids", "object_groups", "object_node_ids",
    "edge_features", "edge_source_indices", "edge_target_indices", "action_features",
    "action_ref_features", "action_ref_card_ids", "action_ref_action_indices", "action_ref_node_indices",
})
MASK64 = (1 << 64) - 1
SEED_DOMAIN = b"spellbench-kernel-flat-bot/v1"


class BotError(Exception):
    """A condition the bot refuses to guess past (answered as internal_error)."""


def seat_stream_seed(seed: int, game_id: str, seat: str) -> int:
    digest = hashlib.sha256(SEED_DOMAIN + b"\0" + game_id.encode("utf-8") + b"\0" + seat.encode("ascii")).digest()
    return (seed ^ int.from_bytes(digest[:8], "big")) & MASK64


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ScorerProcess:
    """The native scorer child: one JSON object per line each way."""

    def __init__(self, argv: list[str]) -> None:
        self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.ready = self._read()
        if self.ready.get("schema") != READY_SCHEMA:
            raise BotError(f"scorer did not become ready: {self.ready!r}")

    def _read(self) -> dict[str, Any]:
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            raise BotError(f"scorer exited (code {self._proc.poll()})")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise BotError("scorer sent a non-object record")
        return value

    def score(self, request: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
        assert self._proc.stdin is not None
        line = _dumps(request).encode("utf-8")
        try:
            self._proc.stdin.write(line + b"\n")
            self._proc.stdin.flush()
        except OSError as exc:
            raise BotError(f"scorer input closed: {exc}") from exc
        return line, self._read()

    def close(self) -> None:
        if self._proc.stdin is not None and not self._proc.stdin.closed:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class KernelFlatBot:
    def __init__(self, scorer: ScorerProcess, *, seed: int, decision_log: Path | None, name: str, version: str) -> None:
        ready = scorer.ready
        if (ready.get("feature_contract_digest"), ready.get("feature_encoding_digest")) != (
            FEATURE_CONTRACT_DIGEST, FEATURE_ENCODING_DIGEST,
        ):
            raise BotError("scorer serves a different feature contract")
        if ready.get("selection") not in (SAMPLED, ARGMAX):
            raise BotError(f"unknown scorer selection {ready.get('selection')!r}")
        self._scorer = scorer
        self._seed = seed
        self._log_dir = decision_log
        self._identity = (name, version)
        self._card_db: str = ready["card_db_hash"]
        self._selection: str = ready["selection"]
        self._state: str = ready["model_state_sha256"]
        self._seat: str | None = None
        self._rng: SplitMix64 | None = None
        self._log = None

    def on_game_start(self, request: GameStartRequest) -> None:
        engine = request.engine
        if engine.name != "mtg-kernel" or not engine.card_pool_identity.endswith(f"carddb-{self._card_db}"):
            raise self._fail(f"engine {engine.name} {engine.card_pool_identity} lacks card registry {self._card_db}")
        self._seat = request.seat
        stream_seed = seat_stream_seed(self._seed, request.game_id, request.seat)
        self._rng = SplitMix64(stream_seed)
        if self._log_dir is not None:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            path = self._log_dir / f"{request.game_id}.{request.seat}.jsonl"
            self._log = open(path, "w", encoding="utf-8", newline="\n")
            self._write_log({
                "schema": LOG_SCHEMA, "kind": "header", "game_id": request.game_id, "seat": request.seat,
                "bot_name": self._identity[0], "bot_version": self._identity[1], "selection": self._selection,
                "stream_seed": stream_seed, "model_state_sha256": self._state,
            })

    def choose(self, decision: Decision) -> int:
        started = time.perf_counter_ns()
        extension = decision.extensions.get(EXTENSION)
        if not isinstance(extension, dict):
            raise self._fail("decision lacks x_kernel_flat_v4; run the bridge with --x-kernel-flat-v4")
        rows = self._validated_rows(decision, extension)
        assert self._rng is not None
        sample_seed = self._rng.next() if self._selection == SAMPLED else None
        request = {
            "schema": REQUEST_SCHEMA, "request_id": f"{decision.game_id}:{decision.step}",
            "game_id": decision.game_id, "seat": decision.acting_seat, "step": decision.step,
            "feature_contract_digest": FEATURE_CONTRACT_DIGEST, "feature_encoding_digest": FEATURE_ENCODING_DIGEST,
            "row_candidate_ids": rows, "sample_seed": sample_seed, "tensor": extension["tensor"],
        }
        line, choice = self._scorer.score(request)
        if choice.get("schema") != CHOICE_SCHEMA or choice.get("request_id") != request["request_id"]:
            raise self._fail(f"scorer answered {choice.get('schema')!r} code {choice.get('code')!r}")
        if choice.get("request_sha256") != hashlib.sha256(line).hexdigest():
            raise self._fail("scorer hashed a different request")
        row = choice.get("selected_row")
        if type(row) is not int or not 0 <= row < len(rows) or choice.get("selected_candidate_id") != rows[row]:
            raise self._fail("scorer choice does not match the row map")
        self._write_log({
            "kind": "decision", "step": decision.step, "candidate_id": rows[row], "selected_row": row,
            "sample_seed": sample_seed, "logits_bits": choice["logits_bits"], "value_bits": choice["value_bits"],
            "request_sha256": choice["request_sha256"], "elapsed_us": (time.perf_counter_ns() - started) // 1000,
        })
        return rows[row]

    def on_game_over(self, request: GameOverRequest) -> None:
        self._close_log()

    def close(self) -> None:
        self._close_log()
        self._scorer.close()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    def _validated_rows(self, decision: Decision, extension: dict[str, Any]) -> list[int]:
        if (
            extension.get("schema") != EXTENSION_SCHEMA
            or extension.get("feature_contract_digest") != FEATURE_CONTRACT_DIGEST
            or extension.get("feature_encoding_digest") != FEATURE_ENCODING_DIGEST
            or extension.get("card_db_hash") != self._card_db
        ):
            raise self._fail("x_kernel_flat_v4 identity does not match the model")
        if extension.get("acting_seat") != decision.acting_seat or decision.acting_seat != self._seat:
            raise self._fail("x_kernel_flat_v4 is not for this seat")
        if extension.get("step") != decision.step:
            raise self._fail("x_kernel_flat_v4 is not for this step")
        rows = extension.get("row_candidate_ids")
        if (
            not isinstance(rows, list) or not rows or len(set(rows)) != len(rows)
            or any(type(r) is not int or not 0 <= r < len(decision.candidates) for r in rows)
        ):
            raise self._fail("row_candidate_ids is not an injective map into the candidates")
        tensor = extension.get("tensor")
        if not isinstance(tensor, dict) or set(tensor) != TENSOR_KEYS:
            raise self._fail("tensor fields differ from the V4 wire")
        return rows

    def _write_log(self, record: dict[str, Any]) -> None:
        if self._log is not None:
            self._log.write(_dumps(record) + "\n")
            self._log.flush()

    @staticmethod
    def _fail(message: str) -> BotError:
        print(f"kernel_flat_bot: {message}", file=sys.stderr)
        return BotError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorer", required=True, help="spellbench_scorer_v1 executable")
    parser.add_argument("--scorer-arg", action="append", default=[], help="argument placed before --config")
    parser.add_argument("--config", required=True, help="scorer config JSON")
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--decision-log", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    try:
        scorer = ScorerProcess([args.scorer, *args.scorer_arg, "--config", args.config])
        bot = KernelFlatBot(scorer, seed=args.seed, decision_log=args.decision_log, name=args.name, version=args.version)
    except (BotError, OSError, ValueError) as exc:
        print(f"kernel_flat_bot: {exc}", file=sys.stderr)
        return 1
    try:
        return serve(bot, bot_name=args.name, bot_version=args.version, extensions_accepted=(EXTENSION,))
    finally:
        bot.close()


if __name__ == "__main__":
    sys.exit(main())
```

Create `integrations/mtg_kernel/README.md`:

```markdown
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
```

- [ ] **Step 5: Add engine arguments to the conformance test and CI**

In `python/tests/test_engine_conformance.py` add after `DECKS = ...`:
```python
ENGINE_ARGS = os.environ.get("SPELLBENCH_ENGINE_ARGS", "").split()
```
change `with EngineProcess([ENGINE_BIN], timeout_s=120) as engine:` to `with EngineProcess([ENGINE_BIN, *ENGINE_ARGS], timeout_s=120) as engine:`, and add to the module docstring: ``SPELLBENCH_ENGINE_ARGS`` (space-separated) is appended to the engine command.
In `.github/workflows/ci.yml` change `run: uv run --no-sync pytest python/tests -q` to `run: uv run --no-sync pytest python/tests integrations -q`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd $SB && uv run --no-sync pytest integrations -q && uv run --no-sync pytest python/tests -q`
Expected: `8 passed` for integrations; the existing suite unchanged (`595 passed, 3 skipped` at `b97b068`, plus any tests added since).

- [ ] **Step 7: Commit**

```bash
git add integrations python/tests/test_engine_conformance.py .github/workflows/ci.yml
git commit -m "Integrations: mtg-kernel Phase 1 bot over the native scorer"
```

---

### Task 6: Wire x_kernel_flat_v4 into the bridge, with halts for missing inputs

**Files:**
- Modify: `mtg-kernel/src/agent_bridge_v1.rs` (options, server and game structs, hello, `handle_reset`, `handle_step`, `session_response_to_wire`, `decision_response_value_v1`, new `flat_v4_extension_v1`, tests)
- Modify: `mtg-kernel/src/bin/agent_bridge_v1.rs` (flag)
- Modify: `mtg-kernel/tests/agent_bridge_v1.rs` (process test)
- Modify: `docs/contracts/AGENT_BRIDGE_V1.md` (sections 2, 5 and new section 11)

**Interfaces:**
- Consumes: Task 2 `FlatV4LockstepV1`, `FlatV4LockstepErrorV1`; Task 3 `encode_flat_v4_tensor_v1`, `flat_v4_extension_value_v1`, `FlatV4EncodeScratchV1`, `FlatV4EncodeErrorV1`, `SPELLBENCH_EXTENSION_KERNEL_FLAT_V4`; Task 5's `SPELLBENCH_ENGINE_ARGS` support in `$SB/python/tests/test_engine_conformance.py` (Step 5 only).
- Produces (`mtg_kernel::agent_bridge_v1`):
  - `#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)] pub struct SpellbenchBridgeOptionsV1 { pub x_kernel_flat_v4: bool }`
  - `pub const SPELLBENCH_FLAG_X_KERNEL_FLAT_V4: &str = "--x-kernel-flat-v4";`
  - `SpellbenchBridgeServerV1::with_options(identity: SpellbenchEngineIdentityV1, options: SpellbenchBridgeOptionsV1) -> Self`
  - `pub fn spellbench_episode_id_v1(game_id: &str) -> u64` (the FNV-1a mapping, for Task 7)
  - Bin: `agent_bridge_v1 [--x-kernel-flat-v4]`; any other argument exits 2 with usage.
  - Halted reasons: `engine_contract_failure:flat_v4_lockstep:<detail>` and `engine_contract_failure:flat_v4_encode:<detail>`.

- [ ] **Step 1: Write the failing tests**

Append to the `#[cfg(test)] mod tests` block of `mtg-kernel/src/agent_bridge_v1.rs`:

```rust
fn flat_v4_server() -> SpellbenchBridgeServerV1 {
    SpellbenchBridgeServerV1::with_options(
        SpellbenchEngineIdentityV1::with_source_revision(None),
        SpellbenchBridgeOptionsV1 { x_kernel_flat_v4: true },
    )
}

fn flat_v4_reset(game_id: &str, deck: &str, seed: u64) -> String {
    json!({"request_type": "reset", "protocol": "spellbench/v1", "request_id": format!("r-{game_id}"),
        "game_id": game_id, "format": "pauper-bo1",
        "seats": [{"seat": "p0", "deck": {"catalog_id": deck}}, {"seat": "p1", "deck": {"catalog_id": deck}}],
        "game_seed": seed, "max_decisions": 3000, "max_steps": 30000}).to_string()
}

fn flat_v4_step(decision: &Value, candidate_id: u64) -> String {
    json!({"request_type": "step", "protocol": "spellbench/v1", "request_id": format!("s-{}", decision["step"]),
        "game_id": decision["game_id"], "expected_step": decision["step"],
        "selection": {"candidate_id": candidate_id,
            "semantic_echo": decision["candidates"][candidate_id as usize]["semantic"]}}).to_string()
}

fn rows_of(decision: &Value) -> Vec<u64> {
    decision["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"]
        .as_array().unwrap().iter().map(|id| id.as_u64().unwrap()).collect()
}

#[test]
fn flat_v4_is_opt_in_and_listed_in_hello() {
    let hello = json!({"request_type": "hello", "protocol": "spellbench/v1", "request_id": "h-1"}).to_string();
    let off: Value = serde_json::from_str(
        &SpellbenchBridgeServerV1::with_engine_identity(SpellbenchEngineIdentityV1::with_source_revision(None))
            .handle_line(&hello),
    ).unwrap();
    assert_eq!(off["extensions"], json!(["x_kernel_v5"]));
    let on: Value = serde_json::from_str(&flat_v4_server().handle_line(&hello)).unwrap();
    assert_eq!(on["extensions"], json!(["x_kernel_v5", "x_kernel_flat_v4"]));
}

#[test]
fn flat_v4_whole_games_carry_the_extension_on_every_decision_of_every_deck() {
    for deck in ["Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries"] {
        for seed in [3_u64, 4] {
            let mut server = flat_v4_server();
            let mut line = server.handle_line(&flat_v4_reset(&format!("g-{deck}-{seed}"), deck, seed));
            let mut rng = crate::state::SplitMix64::seed(seed);
            let mut longest = line.len();
            loop {
                let response: Value = serde_json::from_str(&line).unwrap();
                if response["response_type"] != "decision" {
                    let reason = response["reason"].as_str().unwrap_or("");
                    assert!(!reason.contains("flat_v4"), "{deck} seed {seed}: {reason}");
                    break;
                }
                let extension = &response["extensions"]["x_kernel_flat_v4"];
                assert_eq!(extension["step"], response["step"]);
                assert_eq!(extension["acting_seat"], response["acting_seat"]);
                let rows = rows_of(&response);
                assert!(!rows.is_empty() && rows.len() <= response["candidates"].as_array().unwrap().len());
                let pick = rows[(rng.next_u64() % rows.len() as u64) as usize];
                line = server.handle_line(&flat_v4_step(&response, pick));
                longest = longest.max(line.len());
            }
            assert!(longest < 1024 * 1024, "{deck} seed {seed}: a {longest}-byte decision line");
        }
    }
}

#[test]
fn flat_v4_selection_outside_the_training_list_halts_the_game() {
    let mut server = flat_v4_server();
    let mut decision: Value = serde_json::from_str(&server.handle_line(&flat_v4_reset("g-filter", "Burn", 5))).unwrap();
    while rows_of(&decision).len() < 2 {
        let only = rows_of(&decision)[0];
        decision = serde_json::from_str(&server.handle_line(&flat_v4_step(&decision, only))).unwrap();
    }
    let dropped = rows_of(&decision)[0] as u32;
    server.game.as_mut().unwrap().flat_v4_rows.retain(|id| *id != dropped);
    let terminal: Value = serde_json::from_str(&server.handle_line(&flat_v4_step(&decision, u64::from(dropped)))).unwrap();
    assert_eq!(terminal["response_type"], "terminal");
    assert_eq!(terminal["classification"], "halted");
    assert_eq!(terminal["reason"], format!("engine_contract_failure:flat_v4_lockstep:selection_not_in_training_list:{dropped}"));
}

#[test]
fn flat_v4_lockstep_divergence_halts_the_game() {
    let mut server = flat_v4_server();
    let decision: Value = serde_json::from_str(&server.handle_line(&flat_v4_reset("g-diverge", "Burn", 6))).unwrap();
    {
        let fast = server.game.as_mut().unwrap().flat_v4.as_mut().unwrap().fast_session_mut_for_test();
        let crate::rl_session::FastActorResponseV1::Decision(expected) = fast.current_response() else { panic!("decision") };
        fast.step(expected.episode_id, expected.step, 0).unwrap();
    }
    let terminal: Value = serde_json::from_str(&server.handle_line(&flat_v4_step(&decision, rows_of(&decision)[0]))).unwrap();
    assert_eq!(terminal["classification"], "halted");
    assert!(terminal["reason"].as_str().unwrap().starts_with("engine_contract_failure:flat_v4_lockstep:"), "{terminal}");
}

#[test]
fn flat_v4_encode_failure_halts_instead_of_emitting_a_decision() {
    let mut server = flat_v4_server();
    let decision: Value = serde_json::from_str(&server.handle_line(&flat_v4_reset("g-encode", "Burn", 7))).unwrap();
    server.game.as_mut().unwrap().force_flat_v4_encode_error = true;
    let response: Value = serde_json::from_str(&server.handle_line(&flat_v4_step(&decision, rows_of(&decision)[0]))).unwrap();
    assert_eq!(response["classification"], "halted");
    assert_eq!(response["reason"], "engine_contract_failure:flat_v4_encode:encode:forced by test");
}
```

Append to `mtg-kernel/tests/agent_bridge_v1.rs`:

```rust
#[test]
fn agent_bridge_process_flag_enables_x_kernel_flat_v4() {
    use std::io::{BufRead, BufReader, Write};
    use std::process::{Command, Stdio};
    let mut child = Command::new(env!("CARGO_BIN_EXE_agent_bridge_v1"))
        .arg("--x-kernel-flat-v4")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    let mut stdin = child.stdin.take().unwrap();
    let mut stdout = BufReader::new(child.stdout.take().unwrap());
    let mut exchange = |line: String| -> Value {
        writeln!(stdin, "{line}").unwrap();
        let mut response = String::new();
        stdout.read_line(&mut response).unwrap();
        serde_json::from_str(&response).unwrap()
    };
    let hello = exchange(hello_line("h-1"));
    assert_eq!(hello["extensions"], json!(["x_kernel_v5", "x_kernel_flat_v4"]));
    let decision = exchange(burn_mirror_reset_line("r-1", "g-flag", 12345));
    assert_eq!(decision["extensions"]["x_kernel_flat_v4"]["schema"], "mtg-kernel-spellbench-flat-v4/v1");
    drop(stdin);
    assert!(child.wait().unwrap().success());
    let refused = Command::new(env!("CARGO_BIN_EXE_agent_bridge_v1")).arg("--bogus").output().unwrap();
    assert_eq!(refused.status.code(), Some(2));
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge_v1 -j 4`
Expected: FAIL to compile with `cannot find struct SpellbenchBridgeOptionsV1`.

- [ ] **Step 3: Implement the wiring**

In `mtg-kernel/src/agent_bridge_v1.rs` add imports and items:

```rust
use crate::agent_bridge_flat_v4::{FlatV4LockstepErrorV1, FlatV4LockstepV1};
use crate::agent_bridge_flat_v4_encode::{
    encode_flat_v4_tensor_v1, flat_v4_extension_value_v1, FlatV4EncodeErrorV1,
    FlatV4EncodeScratchV1, SPELLBENCH_EXTENSION_KERNEL_FLAT_V4,
};

/// Command-line flag enabling `x_kernel_flat_v4`.
pub const SPELLBENCH_FLAG_X_KERNEL_FLAT_V4: &str = "--x-kernel-flat-v4";

/// Opt-in behaviors of one bridge process.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SpellbenchBridgeOptionsV1 {
    /// Run the lockstep training-mode copy and attach `x_kernel_flat_v4`.
    pub x_kernel_flat_v4: bool,
}

/// The kernel episode id a Spellbench game id maps to (Section 2).
pub fn spellbench_episode_id_v1(game_id: &str) -> u64 {
    fnv1a64_utf8_v1(game_id)
}
```
Replace the game struct:
```rust
struct SpellbenchBridgeGameV1 {
    game_id: String,
    episode_id: u64,
    session: RlEpisodeSessionV1,
    terminal_sent: bool,
    flat_v4: Option<FlatV4LockstepV1>,
    /// Row map of the pending decision (row r executes candidate rows[r]).
    flat_v4_rows: Vec<u32>,
    flat_v4_scratch: FlatV4EncodeScratchV1,
    #[cfg(test)]
    force_flat_v4_encode_error: bool,
}
```
Add `options: SpellbenchBridgeOptionsV1` to `SpellbenchBridgeServerV1`; `new()` and `with_engine_identity()` set `SpellbenchBridgeOptionsV1::default()`; add:
```rust
    pub fn with_options(identity: SpellbenchEngineIdentityV1, options: SpellbenchBridgeOptionsV1) -> Self {
        SpellbenchBridgeServerV1 { identity, options, game: None, used_game_ids: HashSet::new(), last_exchange: None }
    }
```
In the hello arm of `dispatch_request` replace the extensions literal:
```rust
            SpellbenchRequestV1::Hello { request_id, .. } => {
                let mut extensions = vec![SPELLBENCH_EXTENSION_KERNEL_V5];
                if self.options.x_kernel_flat_v4 {
                    extensions.push(SPELLBENCH_EXTENSION_KERNEL_FLAT_V4);
                }
                json!({
                    "response_type": "hello_ok",
                    "protocol": SPELLBENCH_PROTOCOL_V1,
                    "request_id": request_id,
                    "engine": self.identity().hello_engine_value(),
                    "formats": [SPELLBENCH_FORMAT_PAUPER_BO1_V1],
                    "capabilities": {"decklists_as_data": false},
                    "extensions": extensions,
                })
            }
```
Add the extension helper (free function):
```rust
/// The `x_kernel_flat_v4` payload for `response` (None when the option is off
/// or the game ended); stores the decision's row map. An Err is the halted
/// reason: the engine could not produce the model input.
fn flat_v4_extension_v1(
    game: &mut SpellbenchBridgeGameV1,
    response: &RlSessionResponseV1,
) -> Result<Option<Value>, String> {
    let SpellbenchBridgeGameV1 { session, flat_v4, flat_v4_rows, flat_v4_scratch, .. } = game;
    let Some(lockstep) = flat_v4.as_ref() else { return Ok(None) };
    lockstep.verify(session, response).map_err(|error| error.halt_reason())?;
    let RlSessionResponseV1::Decision(decision) = response else { return Ok(None) };
    let rows = lockstep.row_candidate_ids(decision).map_err(|error| error.halt_reason())?;
    #[cfg(test)]
    if game.force_flat_v4_encode_error {
        return Err(FlatV4EncodeErrorV1::Encode("forced by test".to_string()).halt_reason());
    }
    let tensor = encode_flat_v4_tensor_v1(lockstep.fast_session(), flat_v4_scratch)
        .map_err(|error| error.halt_reason())?;
    let value = flat_v4_extension_value_v1(&tensor, &rows, seat_str_v1(decision.acting_player), decision.step)
        .map_err(|error| error.halt_reason())?;
    *flat_v4_rows = rows;
    Ok(Some(value))
}
```
(If the borrow checker rejects reading `game.force_flat_v4_encode_error` after the destructuring, add `force_flat_v4_encode_error` to the destructuring pattern under `#[cfg(test)]` and read the binding instead.)

Change `decision_response_value_v1` to take `flat_v4: Option<Value>` as a fifth argument and build extensions as:
```rust
    let mut extensions = json!({ SPELLBENCH_EXTENSION_KERNEL_V5: { /* unchanged */ } });
    if let Some(flat_v4) = flat_v4 {
        extensions[SPELLBENCH_EXTENSION_KERNEL_FLAT_V4] = flat_v4;
    }
```
Change `session_response_to_wire` to take `flat_v4: Option<Value>` as a fifth argument and pass it through for decisions.

In `handle_reset`, after `let episode_id = fnv1a64_utf8_v1(game_id);` create the lockstep first (clone `deck_ids` before the raw reset consumes it):
```rust
        let lockstep = if self.options.x_kernel_flat_v4 {
            Some(FlatV4LockstepV1::reset(episode_id, game_seed, max_decisions, max_steps, deck_ids.clone()))
        } else {
            None
        };
```
then, after the raw session is created, build the game, compute the extension and the response:
```rust
        let (lockstep, lockstep_failure) = match lockstep {
            Some(Ok(lockstep)) => (Some(lockstep), None),
            Some(Err(error)) => (None, Some(error.halt_reason())),
            None => (None, None),
        };
        let counts = (session.policy_step_count(), session.physical_decision_count());
        let response = session.current_response();
        let mut game = SpellbenchBridgeGameV1 {
            game_id: game_id.to_string(), episode_id, session, terminal_sent: false,
            flat_v4: lockstep, flat_v4_rows: Vec::new(), flat_v4_scratch: FlatV4EncodeScratchV1::default(),
            #[cfg(test)]
            force_flat_v4_encode_error: false,
        };
        let wire = match lockstep_failure.map(Err).unwrap_or_else(|| flat_v4_extension_v1(&mut game, &response)) {
            Ok(flat_v4) => self.session_response_to_wire(request_id, game_id, response, counts, flat_v4),
            Err(reason) => WireResponseV1::Terminal(self.halted_terminal_value(request_id, game_id, counts, &reason)),
        };
        game.terminal_sent = matches!(wire, WireResponseV1::Terminal(_));
        self.used_game_ids.insert(game_id.to_string());
        self.game = Some(game);
        match wire {
            WireResponseV1::Decision(value) | WireResponseV1::Terminal(value) => value,
        }
```
In `handle_step`, after the semantic-echo check and before `game.session.step(...)`:
```rust
        if game.flat_v4.is_some() && !game.flat_v4_rows.contains(&selection.candidate_id) {
            let reason = FlatV4LockstepErrorV1::SelectionNotInTrainingList { candidate_id: selection.candidate_id }.halt_reason();
            return self.fail_game_halted(request_id, answered_counts, &reason);
        }
```
and in the `Ok(response)` arm, before building the wire response:
```rust
            Ok(response) => {
                let counts = (game.session.policy_step_count(), game.session.physical_decision_count());
                let rows = std::mem::take(&mut game.flat_v4_rows);
                if let Some(lockstep) = game.flat_v4.as_mut() {
                    if let Err(error) = lockstep.mirror_step(&rows, expected_step, selection.candidate_id) {
                        return self.fail_game_halted(request_id, counts, &error.halt_reason());
                    }
                }
                let flat_v4 = match flat_v4_extension_v1(game, &response) {
                    Ok(flat_v4) => flat_v4,
                    Err(reason) => return self.fail_game_halted(request_id, counts, &reason),
                };
                let wire = self.session_response_to_wire(request_id, game_id, response, counts, flat_v4);
                // unchanged from here: mark terminal_sent, return the value
```
In `mtg-kernel/src/bin/agent_bridge_v1.rs` replace the argument check and server construction:
```rust
use mtg_kernel::agent_bridge_v1::{
    read_bridge_input_line_v1, BridgeInputLineV1, SpellbenchBridgeOptionsV1, SpellbenchBridgeServerV1,
    SpellbenchEngineIdentityV1, SPELLBENCH_FLAG_X_KERNEL_FLAT_V4,
};
...
    let mut options = SpellbenchBridgeOptionsV1::default();
    for argument in std::env::args_os().skip(1) {
        if argument.to_str() == Some(SPELLBENCH_FLAG_X_KERNEL_FLAT_V4) {
            options.x_kernel_flat_v4 = true;
        } else {
            eprintln!("usage: agent_bridge_v1 [{SPELLBENCH_FLAG_X_KERNEL_FLAT_V4}]");
            std::process::exit(2);
        }
    }
    let mut server = SpellbenchBridgeServerV1::with_options(SpellbenchEngineIdentityV1::current(), options);
```
In `docs/contracts/AGENT_BRIDGE_V1.md`: section 2 `extensions` row becomes `["x_kernel_v5"]`, or `["x_kernel_v5","x_kernel_flat_v4"]` with `--x-kernel-flat-v4`; section 5 adds one bullet pointing to section 11; add:

```markdown
## 11. x_kernel_flat_v4 (opt-in, `--x-kernel-flat-v4`)

For Phase 1 V4 policies (g115, A48, c12). The bridge runs a lockstep copy of
the game as `FastActorSessionV1` in flat-action V3 mode (the session type and
mode those policies trained and were evaluated on), created with the same
catalog decks, seed and limits, stepped with the same executed actions and
compared for equal game state, counters and decision header after every step.
Every decision carries, for the acting seat only:

`{"schema": "mtg-kernel-spellbench-flat-v4/v1", "feature_contract_digest",
"feature_encoding_digest", "card_db_hash", "acting_seat", "step",
"row_candidate_ids", "tensor"}`

`tensor` is the V4 model input from the kernel's own encoder and tensorizer
(13 arrays; floats as IEEE-754 binary32 bit patterns). Row r executes
candidate `row_candidate_ids[r]`; the training list can reorder search
targets, relabel effect sources and omit required-goad exclusions and
infeasible menace blocks, so it may cover fewer candidates than the decision.

Any failure to produce this input ends the game `halted` with reason
`engine_contract_failure:flat_v4_lockstep:<detail>` (reset, row_map,
selection_not_in_training_list, fast_step, diverged) or
`engine_contract_failure:flat_v4_encode:<detail>` (encode, tensorize,
row_count). Without the flag nothing here runs.
```

- [ ] **Step 4: Run all bridge tests and the goldens**

```bash
CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib agent_bridge -j 4
CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --test agent_bridge_v1 -j 4
CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo build -p mtg-kernel --release --locked --bin agent_bridge_v1 -j 4
MTG_KERNEL_AGENT_BRIDGE_V1_BIN=D:/cargo-target/mtg-kernel-spellbench-g115/release/agent_bridge_v1.exe python python/tools/generate_agent_bridge_goldens.py --check --repo-root .
```
Expected: all PASS (lib: the Task 1, 2, 3 tests plus the five new ones; integration: all plus the flag test); `AGENT_BRIDGE_GOLDENS: PASS` with no golden changes. If the whole-game test reports a `flat_v4` halt, stop and report the deck, seed and reason.

- [ ] **Step 5: Run the Spellbench reference client against the flagged bridge**

```bash
cd $SB
SPELLBENCH_ENGINE_BIN=D:/cargo-target/mtg-kernel-spellbench-g115/release/agent_bridge_v1.exe \
SPELLBENCH_ENGINE_ARGS=--x-kernel-flat-v4 \
SPELLBENCH_ENGINE_DECKS=Wildfire,Rally,Affinity,Elves,Spy,Burn,CawGates,Faeries \
uv run --no-sync pytest python/tests/test_engine_conformance.py -q
```
Expected: `16 passed` (halted games are conformant; the reference client validates every line including the `2^53` bound).

- [ ] **Step 6: Commit**

```bash
cd $MTGK
git add mtg-kernel/src/agent_bridge_v1.rs mtg-kernel/src/bin/agent_bridge_v1.rs mtg-kernel/tests/agent_bridge_v1.rs docs/contracts/AGENT_BRIDGE_V1.md
git commit -m "agent bridge: opt-in x_kernel_flat_v4 with halts for missing model input"
```

---

### Task 7: Qualification verifier

**Files:**
- Create: `mtg-kernel/src/spellbench_qualify_v1.rs`
- Create: `mtg-kernel/src/bin/spellbench_qualify_v1.rs`
- Modify: `mtg-kernel/src/lib.rs` (insert `pub mod spellbench_qualify_v1;` on the line after `pub mod spellbench_scorer_v1;`)

**Interfaces:**
- Consumes: Task 6 `SpellbenchBridgeServerV1::with_options`, `SpellbenchBridgeOptionsV1`, `spellbench_episode_id_v1`, `SpellbenchEngineIdentityV1::with_source_revision`; Task 3 `tensor_bits_v1`; Task 4 `SpellbenchScorerConfigV1`, `SpellbenchScorerV1` (tests), `SELECTION_SAMPLED_WIDE_V1`, `SELECTION_ARGMAX_FIRST_V1`; `load_expanded_inference_v1`; `FrozenPlayPolicyV1::{reset_sampling_v1, score_fast_session_v1, select_fast_session_v1, last_scored_training_tensor_v4}`; `FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3`; the Task 5 decision-log format; Spellbench `config.json` (`max_decisions`, `max_steps`) and `matches.jsonl` rows (`game_id`, `game_seed`, `decks[].catalog_id`, `seats[].name`, `classification`, `outcome`, `step_count`).
- Produces:
  - `pub struct SpellbenchQualificationArgsV1 { pub tournament_dir: PathBuf, pub decision_log_dir: PathBuf, pub bot_configs: BTreeMap<String, PathBuf> }`
  - `pub fn run_spellbench_qualification_v1(args: &SpellbenchQualificationArgsV1) -> Result<serde_json::Value, String>`: report `{"schema": "mtg-kernel-spellbench-qualification/v1", "games_replayed", "games_skipped", "decisions", "tensor_mismatches", "logit_mismatches", "choice_mismatches", "outcome_mismatches", "per_deck": {deck: {"games", "decisions"}}, "verdict": "PASS"|"FAIL"}`.
  - Bin: `spellbench_qualify_v1 --tournament-dir DIR --decision-log-dir DIR --bot NAME=CONFIG [--bot NAME=CONFIG]...`; prints the report; exit 0 iff `PASS`.

- [ ] **Step 1: Write the failing tests**

Create `mtg-kernel/src/spellbench_qualify_v1.rs` with only:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::spellbench_scorer_v1::SpellbenchScorerV1;
    use crate::state::SplitMix64;

    /// Plays one game through the in-process bridge with two in-process
    /// scorers exactly as the Python bot drives them, returning its ledger
    /// row and both seats' decision logs.
    fn play_logged_game(game_id: &str, deck: &str, seed: u64, limits: (u64, u64), stream_seeds: [u64; 2]) -> (LedgerGameV1, [BotLogV1; 2]) {
        let mut scorers = [0, 1].map(|_| {
            SpellbenchScorerV1::new(FrozenPlayPolicyV1::training_fixture_v4(), json!({"fixture": true}), "0".repeat(64), SELECTION_SAMPLED_WIDE_V1).unwrap()
        });
        let mut streams = stream_seeds.map(SplitMix64::seed);
        let mut logs = [0, 1].map(|seat| BotLogV1 {
            header: BotLogHeaderV1 { schema: BOT_LOG_SCHEMA_V1.into(), kind: "header".into(), game_id: game_id.into(),
                seat: ["p0", "p1"][seat].into(), bot_name: "fixture".into(), bot_version: "1.0.0".into(),
                selection: SELECTION_SAMPLED_WIDE_V1.into(), stream_seed: stream_seeds[seat], model_state_sha256: "0".repeat(64) },
            decisions: Vec::new(),
        });
        let mut server = replay_server();
        let mut response: Value = serde_json::from_str(&server.handle_line(&reset_line(game_id, [deck, deck], seed, limits, "q-0"))).unwrap();
        let mut index = 0;
        while response["response_type"] == "decision" {
            let seat = usize::from(response["acting_seat"] == "p1");
            let extension = &response["extensions"]["x_kernel_flat_v4"];
            let sample_seed = streams[seat].next_u64();
            let request = json!({"schema": "mtg-kernel-spellbench-scorer-request/v1", "request_id": format!("{game_id}:{}", response["step"]),
                "game_id": game_id, "seat": response["acting_seat"], "step": response["step"],
                "feature_contract_digest": extension["feature_contract_digest"], "feature_encoding_digest": extension["feature_encoding_digest"],
                "row_candidate_ids": extension["row_candidate_ids"], "sample_seed": sample_seed, "tensor": extension["tensor"]});
            let choice = scorers[seat].score_line(&serde_json::to_vec(&request).unwrap()).unwrap();
            let candidate_id = choice["selected_candidate_id"].as_u64().unwrap() as u32;
            logs[seat].decisions.push(BotLogDecisionV1 { kind: "decision".into(), step: response["step"].as_u64().unwrap(),
                candidate_id, selected_row: choice["selected_row"].as_u64().unwrap() as u32, sample_seed: Some(sample_seed),
                logits_bits: serde_json::from_value(choice["logits_bits"].clone()).unwrap(),
                value_bits: choice["value_bits"].as_u64().unwrap() as u32, request_sha256: choice["request_sha256"].as_str().unwrap().into(), elapsed_us: 0 });
            index += 1;
            response = serde_json::from_str(&server.handle_line(&step_line(&response, candidate_id, &format!("q-{index}")))).unwrap();
        }
        let game = LedgerGameV1 { game_id: game_id.into(), game_seed: seed, decks: [deck.into(), deck.into()],
            bot_names: ["fixture".into(), "fixture".into()], classification: response["classification"].as_str().unwrap().into(),
            outcome: response["outcome"].as_str().unwrap().into(), step_count: response["step_count"].as_u64().unwrap() };
        (game, logs)
    }

    fn harness_pair() -> [FrozenPlayPolicyV1; 2] {
        [FrozenPlayPolicyV1::training_fixture_v4(), FrozenPlayPolicyV1::training_fixture_v4()]
    }

    #[test]
    fn faithful_logs_replay_with_zero_mismatches() {
        for deck in ["Burn", "Spy"] {
            let (game, logs) = play_logged_game(&format!("q-{deck}"), deck, 21, (300, 3_000), [11, 12]);
            let mut counts = QualificationCountsV1::default();
            let [mut p0, mut p1] = harness_pair();
            replay_game_v1(&game, (300, 3_000), &logs, [&mut p0, &mut p1], &mut counts).unwrap();
            assert_eq!(counts.games_replayed, 1);
            assert!(counts.decisions > 20);
            assert_eq!((counts.tensor_mismatches, counts.logit_mismatches, counts.choice_mismatches, counts.outcome_mismatches), (0, 0, 0, 0), "{deck}");
        }
    }

    #[test]
    fn tampered_logits_and_choices_are_counted() {
        let (game, mut logs) = play_logged_game("q-tamper", "Burn", 22, (300, 3_000), [13, 14]);
        logs[0].decisions[0].logits_bits[0] ^= 1;
        let mut counts = QualificationCountsV1::default();
        let [mut p0, mut p1] = harness_pair();
        replay_game_v1(&game, (300, 3_000), &logs, [&mut p0, &mut p1], &mut counts).unwrap();
        assert_eq!(counts.logit_mismatches, 1);

        let (game, mut logs) = play_logged_game("q-tamper-2", "Burn", 23, (300, 3_000), [15, 16]);
        let first = logs[0].decisions.iter_mut().find(|decision| decision.logits_bits.len() >= 2).unwrap();
        first.candidate_id += 1; // the bot "chose" something the harness did not
        let mut counts = QualificationCountsV1::default();
        let [mut p0, mut p1] = harness_pair();
        replay_game_v1(&game, (300, 3_000), &logs, [&mut p0, &mut p1], &mut counts).unwrap();
        assert_eq!(counts.choice_mismatches, 1);
        assert_eq!(counts.games_replayed, 0, "a diverged replay is not counted as replayed");
    }
}
```
Add `pub mod spellbench_qualify_v1;` to `lib.rs` after `pub mod spellbench_scorer_v1;`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib spellbench_qualify_v1 -j 4`
Expected: FAIL to compile with `cannot find function replay_game_v1`.

- [ ] **Step 3: Implement the verifier**

Insert above the test module:

```rust
//! Qualification for Spellbench kernel bots: replays each logged game and
//! proves, decision by decision, that the bridge gave the bot the evaluation
//! harness's input (tensor), that the bot's scorer produced the harness's
//! logits, and that the bot chose the harness's row with the same seat stream.
//! The harness is `FrozenPlayPolicyV1` scoring its own flat-action V3
//! `FastActorSessionV1`, the evaluation path of the Phase 1 lineage.

use crate::agent_bridge_flat_v4_encode::tensor_bits_v1;
use crate::agent_bridge_v1::{
    spellbench_episode_id_v1, SpellbenchBridgeOptionsV1, SpellbenchBridgeServerV1, SpellbenchEngineIdentityV1,
};
use crate::expanded_deck_training_v1::load_expanded_inference_v1;
use crate::rl_session::FastActorSessionV1;
use crate::sideboard_play_policy_v1::FrozenPlayPolicyV1;
use crate::spellbench_scorer_v1::{SpellbenchScorerConfigV1, SELECTION_ARGMAX_FIRST_V1, SELECTION_SAMPLED_WIDE_V1};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

pub const QUALIFICATION_REPORT_SCHEMA_V1: &str = "mtg-kernel-spellbench-qualification/v1";
pub const BOT_LOG_SCHEMA_V1: &str = "spellbench-kernel-bot-log/v1";

// Every field is part of the checked wire even where the replay ignores it.
#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct BotLogHeaderV1 {
    schema: String, kind: String, game_id: String, seat: String, bot_name: String,
    bot_version: String, selection: String, stream_seed: u64, model_state_sha256: String,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct BotLogDecisionV1 {
    kind: String, step: u64, candidate_id: u32, selected_row: u32, sample_seed: Option<u64>,
    logits_bits: Vec<u32>, value_bits: u32, request_sha256: String, elapsed_us: u64,
}

pub(crate) struct BotLogV1 {
    header: BotLogHeaderV1,
    decisions: Vec<BotLogDecisionV1>,
}

pub(crate) struct LedgerGameV1 {
    game_id: String, game_seed: u64, decks: [String; 2], bot_names: [String; 2],
    classification: String, outcome: String, step_count: u64,
}

#[derive(Debug, Default)]
pub(crate) struct QualificationCountsV1 {
    games_replayed: u64, games_skipped: u64, decisions: u64, tensor_mismatches: u64,
    logit_mismatches: u64, choice_mismatches: u64, outcome_mismatches: u64,
    per_deck: BTreeMap<String, (u64, u64)>,
}

fn replay_server() -> SpellbenchBridgeServerV1 {
    SpellbenchBridgeServerV1::with_options(
        SpellbenchEngineIdentityV1::with_source_revision(None),
        SpellbenchBridgeOptionsV1 { x_kernel_flat_v4: true },
    )
}

fn reset_line(game_id: &str, decks: [&str; 2], seed: u64, limits: (u64, u64), request_id: &str) -> String {
    json!({"request_type": "reset", "protocol": "spellbench/v1", "request_id": request_id, "game_id": game_id,
        "format": "pauper-bo1",
        "seats": [{"seat": "p0", "deck": {"catalog_id": decks[0]}}, {"seat": "p1", "deck": {"catalog_id": decks[1]}}],
        "game_seed": seed, "max_decisions": limits.0, "max_steps": limits.1}).to_string()
}

fn step_line(decision: &Value, candidate_id: u32, request_id: &str) -> String {
    json!({"request_type": "step", "protocol": "spellbench/v1", "request_id": request_id,
        "game_id": decision["game_id"], "expected_step": decision["step"],
        "selection": {"candidate_id": candidate_id,
            "semantic_echo": decision["candidates"][candidate_id as usize]["semantic"]}}).to_string()
}

fn first_argmax(logits: &[f32]) -> usize {
    let mut selected = 0;
    for index in 1..logits.len() {
        if logits[index] > logits[selected] {
            selected = index;
        }
    }
    selected
}

/// Replays one game. Stops at the first choice mismatch (positions diverge).
pub(crate) fn replay_game_v1(
    game: &LedgerGameV1,
    limits: (u64, u64),
    logs: &[BotLogV1; 2],
    mut policies: [&mut FrozenPlayPolicyV1; 2],
    counts: &mut QualificationCountsV1,
) -> Result<(), String> {
    let episode_id = spellbench_episode_id_v1(&game.game_id);
    let mut server = replay_server();
    let decks = [game.decks[0].as_str(), game.decks[1].as_str()];
    let mut response: Value = serde_json::from_str(&server.handle_line(&reset_line(&game.game_id, decks, game.game_seed, limits, "q-0")))
        .map_err(|error| error.to_string())?;
    let mut harness = FastActorSessionV1::reset_with_decks_and_limits_flat_action_v3(
        episode_id, game.game_seed, limits.0, limits.1, game.decks.clone(),
    )
    .map_err(|error| error.message)?;
    let seeds = [logs[0].header.stream_seed, logs[1].header.stream_seed];
    for policy in policies.iter_mut() {
        policy.reset_sampling_v1(seeds);
    }
    let mut cursor = [0_usize; 2];
    let mut request_index = 0_u64;
    let mut decisions = 0_u64;
    while response["response_type"] == "decision" {
        let seat = usize::from(response["acting_seat"] == "p1");
        let step = response["step"].as_u64().ok_or("decision without step")?;
        let entry = logs[seat].decisions.get(cursor[seat]).ok_or_else(|| format!("{}: log shorter than game", game.game_id))?;
        cursor[seat] += 1;
        if entry.step != step {
            return Err(format!("{}: log step {} but decision step {step}", game.game_id, entry.step));
        }
        let extension = &response["extensions"]["x_kernel_flat_v4"];
        let rows: Vec<u32> = serde_json::from_value(extension["row_candidate_ids"].clone()).map_err(|error| error.to_string())?;
        let policy = &mut *policies[seat];
        let scores = policy.score_fast_session_v1(&harness)?;
        let harness_tensor = serde_json::to_value(tensor_bits_v1(policy.last_scored_training_tensor_v4()?)).map_err(|error| error.to_string())?;
        counts.decisions += 1;
        decisions += 1;
        if extension["tensor"] != harness_tensor {
            counts.tensor_mismatches += 1;
        }
        let harness_logits: Vec<u32> = scores.logits.iter().map(|value| value.to_bits()).collect();
        if entry.logits_bits != harness_logits {
            counts.logit_mismatches += 1;
        }
        let harness_row = match logs[seat].header.selection.as_str() {
            SELECTION_SAMPLED_WIDE_V1 => policy.select_fast_session_v1(&harness)? as usize,
            SELECTION_ARGMAX_FIRST_V1 => first_argmax(&scores.logits),
            other => return Err(format!("unknown selection {other}")),
        };
        if rows.get(harness_row) != Some(&entry.candidate_id) {
            counts.choice_mismatches += 1;
            return Ok(());
        }
        request_index += 1;
        let line = server.handle_line(&step_line(&response, entry.candidate_id, &format!("q-{request_index}")));
        response = serde_json::from_str(&line).map_err(|error| error.to_string())?;
        harness.step(episode_id, step, harness_row as u32).map_err(|error| error.message)?;
    }
    if response["classification"] != game.classification.as_str()
        || response["outcome"] != game.outcome.as_str()
        || response["step_count"] != game.step_count
    {
        counts.outcome_mismatches += 1;
    }
    counts.games_replayed += 1;
    let deck = counts.per_deck.entry(game.decks[0].clone()).or_default();
    deck.0 += 1;
    deck.1 += decisions;
    Ok(())
}

pub struct SpellbenchQualificationArgsV1 {
    pub tournament_dir: PathBuf,
    pub decision_log_dir: PathBuf,
    pub bot_configs: BTreeMap<String, PathBuf>,
}

fn read_json(path: &Path) -> Result<Value, String> {
    let bytes = std::fs::read(path).map_err(|error| format!("{}: {error}", path.display()))?;
    serde_json::from_slice(&bytes).map_err(|error| format!("{}: {error}", path.display()))
}

fn read_log(path: &Path) -> Result<Option<BotLogV1>, String> {
    let Ok(text) = std::fs::read_to_string(path) else { return Ok(None) };
    let mut lines = text.lines();
    let header: BotLogHeaderV1 = serde_json::from_str(lines.next().ok_or("empty log")?).map_err(|error| error.to_string())?;
    if header.schema != BOT_LOG_SCHEMA_V1 || header.kind != "header" {
        return Err(format!("{}: not a bot log", path.display()));
    }
    let decisions = lines.map(|line| serde_json::from_str(line).map_err(|error| error.to_string())).collect::<Result<Vec<BotLogDecisionV1>, String>>()?;
    Ok(Some(BotLogV1 { header, decisions }))
}

pub fn run_spellbench_qualification_v1(args: &SpellbenchQualificationArgsV1) -> Result<Value, String> {
    let config = read_json(&args.tournament_dir.join("config.json"))?;
    let limits = (
        config["max_decisions"].as_u64().ok_or("config.max_decisions")?,
        config["max_steps"].as_u64().ok_or("config.max_steps")?,
    );
    let ledger = std::fs::read_to_string(args.tournament_dir.join("matches.jsonl")).map_err(|error| error.to_string())?;
    let mut policies: HashMap<(String, usize), FrozenPlayPolicyV1> = HashMap::new();
    let mut counts = QualificationCountsV1::default();
    for line in ledger.lines() {
        let row: Value = serde_json::from_str(line).map_err(|error| error.to_string())?;
        let game = LedgerGameV1 {
            game_id: row["game_id"].as_str().ok_or("game_id")?.to_string(),
            game_seed: row["game_seed"].as_u64().ok_or("game_seed")?,
            decks: [0, 1].map(|seat| row["decks"][seat]["catalog_id"].as_str().unwrap_or_default().to_string()),
            bot_names: [0, 1].map(|seat| row["seats"][seat]["name"].as_str().unwrap_or_default().to_string()),
            classification: row["classification"].as_str().ok_or("classification")?.to_string(),
            outcome: row["outcome"].as_str().ok_or("outcome")?.to_string(),
            step_count: row["step_count"].as_u64().ok_or("step_count")?,
        };
        let paths = ["p0", "p1"].map(|seat| args.decision_log_dir.join(format!("{}.{seat}.jsonl", game.game_id)));
        let (Some(log0), Some(log1)) = (read_log(&paths[0])?, read_log(&paths[1])?) else {
            counts.games_skipped += 1;
            continue;
        };
        for (seat, log) in [&log0, &log1].into_iter().enumerate() {
            let key = (game.bot_names[seat].clone(), seat);
            if !policies.contains_key(&key) {
                let config_path = args.bot_configs.get(&key.0).ok_or_else(|| format!("no --bot config for {}", key.0))?;
                let config: SpellbenchScorerConfigV1 = serde_json::from_value(read_json(config_path)?).map_err(|error| error.to_string())?;
                let (policy, identity) = load_expanded_inference_v1(&config.source)?;
                if identity.state_sha256 != log.header.model_state_sha256 {
                    return Err(format!("{}: log model {} is not config model {}", key.0, log.header.model_state_sha256, identity.state_sha256));
                }
                policies.insert(key.clone(), policy);
            }
        }
        let mut p0 = policies.remove(&(game.bot_names[0].clone(), 0)).expect("loaded");
        let mut p1 = policies.remove(&(game.bot_names[1].clone(), 1)).expect("loaded");
        let result = replay_game_v1(&game, limits, &[log0, log1], [&mut p0, &mut p1], &mut counts);
        policies.insert((game.bot_names[0].clone(), 0), p0);
        policies.insert((game.bot_names[1].clone(), 1), p1);
        result?;
    }
    let clean = counts.tensor_mismatches + counts.logit_mismatches + counts.choice_mismatches + counts.outcome_mismatches == 0;
    Ok(json!({
        "schema": QUALIFICATION_REPORT_SCHEMA_V1,
        "games_replayed": counts.games_replayed, "games_skipped": counts.games_skipped, "decisions": counts.decisions,
        "tensor_mismatches": counts.tensor_mismatches, "logit_mismatches": counts.logit_mismatches,
        "choice_mismatches": counts.choice_mismatches, "outcome_mismatches": counts.outcome_mismatches,
        "per_deck": counts.per_deck.iter().map(|(deck, (games, decisions))| (deck.clone(), json!({"games": games, "decisions": decisions}))).collect::<serde_json::Map<_, _>>(),
        "verdict": if clean && counts.games_replayed > 0 { "PASS" } else { "FAIL" },
    }))
}
```

Create `mtg-kernel/src/bin/spellbench_qualify_v1.rs`:

```rust
use mtg_kernel::spellbench_qualify_v1::{run_spellbench_qualification_v1, SpellbenchQualificationArgsV1};
use std::collections::BTreeMap;
use std::path::PathBuf;

const USAGE: &str = "usage: spellbench_qualify_v1 --tournament-dir DIR --decision-log-dir DIR --bot NAME=CONFIG [--bot NAME=CONFIG]...";

fn main() {
    let mut arguments = std::env::args().skip(1);
    let (mut tournament_dir, mut decision_log_dir, mut bot_configs) = (None, None, BTreeMap::new());
    while let Some(flag) = arguments.next() {
        let value = arguments.next().unwrap_or_else(|| { eprintln!("{USAGE}"); std::process::exit(2) });
        match flag.as_str() {
            "--tournament-dir" => tournament_dir = Some(PathBuf::from(value)),
            "--decision-log-dir" => decision_log_dir = Some(PathBuf::from(value)),
            "--bot" => {
                let (name, path) = value.split_once('=').unwrap_or_else(|| { eprintln!("{USAGE}"); std::process::exit(2) });
                bot_configs.insert(name.to_string(), PathBuf::from(path));
            }
            _ => { eprintln!("{USAGE}"); std::process::exit(2) }
        }
    }
    let (Some(tournament_dir), Some(decision_log_dir)) = (tournament_dir, decision_log_dir) else {
        eprintln!("{USAGE}");
        std::process::exit(2)
    };
    match run_spellbench_qualification_v1(&SpellbenchQualificationArgsV1 { tournament_dir, decision_log_dir, bot_configs }) {
        Ok(report) => {
            println!("{report}");
            std::process::exit(if report["verdict"] == "PASS" { 0 } else { 1 });
        }
        Err(message) => {
            eprintln!("spellbench qualify: {message}");
            std::process::exit(1);
        }
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo test -p mtg-kernel --lib spellbench_qualify_v1 -j 4`
Expected: PASS, `2 passed; 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add mtg-kernel/src/spellbench_qualify_v1.rs mtg-kernel/src/bin/spellbench_qualify_v1.rs mtg-kernel/src/lib.rs
git commit -m "spellbench qualify: replay bot logs against the evaluation harness"
```

---

### Task 8: Qualification run and evidence

**Files:**
- Create (outside repos): `E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/qual-config.json`, `qual-config-rerun.json`, `run-1/`, `run-2/`, `logs/`, `qualification-report.json`, `latency.json`, `E:/spellbench-archive/2026-09-27-c-kernel-models/README.md`

**Interfaces:**
- Consumes: release binaries of Tasks 4, 6, 7; the Task 5 bot; the three scorer configs from Task 4.
- Produces: `qualification-report.json` with `"verdict":"PASS"` (input to gate G1 and Task 9), `latency.json`, byte-identical `matches.jsonl` across two runs.

- [ ] **Step 1: Build the release binaries and record their identity**

```bash
cd $MTGK
CARGO_TARGET_DIR=D:/cargo-target/mtg-kernel-spellbench-g115 cargo build -p mtg-kernel --release --locked --bin agent_bridge_v1 --bin spellbench_scorer_v1 --bin spellbench_qualify_v1 -j 4
git rev-parse HEAD
sha256sum D:/cargo-target/mtg-kernel-spellbench-g115/release/{agent_bridge_v1,spellbench_scorer_v1,spellbench_qualify_v1}.exe
```
Expected: three binaries; record the commit and the three sha256 values in the archive README.

- [ ] **Step 2: Write the qualification config**

`E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/qual-config.json` (96 games: 3 kernel bots, self-play on, 8 pairs per matchup, one per deck):
```json
{
  "schema": "spellbench-tournament-config/v1",
  "tournament_dir": "E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/run-1",
  "format": "pauper-bo1",
  "deck_pool": [{"catalog_id": "Wildfire"}, {"catalog_id": "Rally"}, {"catalog_id": "Affinity"}, {"catalog_id": "Elves"}, {"catalog_id": "Spy"}, {"catalog_id": "Burn"}, {"catalog_id": "CawGates"}, {"catalog_id": "Faeries"}],
  "engine": {"command": ["D:/cargo-target/mtg-kernel-spellbench-g115/release/agent_bridge_v1.exe", "--x-kernel-flat-v4"], "timeout_ms": 120000},
  "bots": [
    {"name": "g115", "version": "1.0.0", "type": "subprocess", "command": ["~/IdeaProjects/spellbench/.venv/Scripts/python.exe", "~/IdeaProjects/spellbench/integrations/mtg_kernel/kernel_flat_bot.py", "--scorer", "D:/cargo-target/mtg-kernel-spellbench-g115/release/spellbench_scorer_v1.exe", "--config", "E:/spellbench-archive/kernel-bots/g115.scorer.json", "--name", "g115", "--version", "1.0.0", "--decision-log", "E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/logs"]},
    {"name": "a48", "version": "1.0.0", "type": "subprocess", "command": ["~/IdeaProjects/spellbench/.venv/Scripts/python.exe", "~/IdeaProjects/spellbench/integrations/mtg_kernel/kernel_flat_bot.py", "--scorer", "D:/cargo-target/mtg-kernel-spellbench-g115/release/spellbench_scorer_v1.exe", "--config", "E:/spellbench-archive/kernel-bots/a48.scorer.json", "--name", "a48", "--version", "1.0.0", "--decision-log", "E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/logs"]},
    {"name": "c12", "version": "1.0.0", "type": "subprocess", "command": ["~/IdeaProjects/spellbench/.venv/Scripts/python.exe", "~/IdeaProjects/spellbench/integrations/mtg_kernel/kernel_flat_bot.py", "--scorer", "D:/cargo-target/mtg-kernel-spellbench-g115/release/spellbench_scorer_v1.exe", "--config", "E:/spellbench-archive/kernel-bots/c12.scorer.json", "--name", "c12", "--version", "1.0.0", "--decision-log", "E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/logs"]}
  ],
  "pairs_per_matchup": 8,
  "base_seed": 20260927,
  "workers": 8,
  "include_self_play": true
}
```
`qual-config-rerun.json`: identical except `"tournament_dir"` ends in `run-2` (the bot commands must stay identical so bot ids and ledger rows can match).

- [ ] **Step 3: Run the qualification tournament**

Run: `cd $SB && uv run --no-sync spellbench run E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/qual-config.json`
Expected: `games: 96 total, ... 0 forfeit`.

- [ ] **Step 4: Replay against the harness**

```bash
D:/cargo-target/mtg-kernel-spellbench-g115/release/spellbench_qualify_v1.exe \
  --tournament-dir E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/run-1 \
  --decision-log-dir E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/logs \
  --bot g115=E:/spellbench-archive/kernel-bots/g115.scorer.json \
  --bot a48=E:/spellbench-archive/kernel-bots/a48.scorer.json \
  --bot c12=E:/spellbench-archive/kernel-bots/c12.scorer.json \
  > E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/qualification-report.json
```
Expected: exit 0; report has `"verdict":"PASS"`, `"games_replayed":96`, `"games_skipped":0`, all four mismatch counts 0, and all 8 decks under `per_deck`. Any mismatch: stop, keep the evidence, report the first mismatching game and decision.

- [ ] **Step 5: Check choose latency**

```bash
python - <<'EOF'
import json, pathlib
logs = pathlib.Path("E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/logs")
values = sorted(json.loads(line)["elapsed_us"] for path in logs.glob("*.jsonl") for line in path.read_text().splitlines()[1:])
summary = {"decisions": len(values), "p50_us": values[len(values) // 2], "p99_us": values[int(len(values) * 0.99)], "max_us": values[-1]}
pathlib.Path(logs.parent / "latency.json").write_text(json.dumps(summary) + "\n")
print(summary)
assert summary["max_us"] < 5_000_000, summary
EOF
```
Expected: prints the summary; `max_us` under 5,000,000.

- [ ] **Step 6: Rerun and compare the ledgers**

```bash
cd $SB && uv run --no-sync spellbench run E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/qual-config-rerun.json
cmp E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/run-1/matches.jsonl E:/spellbench-archive/2026-09-27-c-kernel-models/qualification/run-2/matches.jsonl && echo IDENTICAL
```
Expected: `IDENTICAL`.

- [ ] **Step 7: Record the evidence**

Write `E:/spellbench-archive/2026-09-27-c-kernel-models/README.md` listing: branch and commit, binary sha256 values, scorer configs, the report, latency, the determinism result, the halt count and reasons from `run-1/matches.jsonl`, and the sentence "Measurement only; not an input to Codex D4 or the research director."

---

### Task 9: Benchmark entry and re-launch

**Files:**
- Modify: `benchmarks/pauper-kernel/benchmark.json`
- Modify (git-ignored): `benchmarks/local.json`
- Modify: `spec/SPELLBENCH_PROTOCOL_V1.md` (section 9, one sentence)
- Create: `benchmarks/pauper-kernel/runs/<date>/` (the run)
- Create (outside repos): `E:/spellbench-archive/2026-09-27-c-kernel-models/throughput/` (configs, runs, `throughput.json`)

**Interfaces:**
- Consumes: Task 8 PASS report; gate G1; release binaries from Task 8 Step 1.
- Produces: the re-launch run with six rated bots; leaderboard and site built from it.

What a re-launch needs, in order: (1) the Task 8 PASS report and gate G1; (2) release `agent_bridge_v1.exe` and `spellbench_scorer_v1.exe` from the branch head, commit recorded as `SPELLBENCH_SOURCE_REVISION`; (3) the three scorer configs; (4) `benchmarks/local.json` with the ten placeholder values; (5) the COMPUTE-POLICY placement check and scaling comparison, with the chosen `workers` written into `benchmark.json` and the evidence in `throughput/`; (6) a zero-forfeit smoke run; (7) the full run, validated; (8) the site build and a local commit. The previous run (`runs/2026-09-26`, card registry `64c82a261e078f1a`) stays as history; the site shows the new latest run.

- [ ] **Step 1: Gate G1**

Wait for the controller to confirm the focused Fable review of Tasks 6 to 8 is recorded with its disposition (IdeaProjects AGENTS.md), or that the controller waived it under the maintainer's standing authorization.

- [ ] **Step 2: COMPUTE-POLICY placement check**

```bash
powershell -NoProfile -Command "(Get-CimInstance Win32_Processor | Measure-Object NumberOfLogicalProcessors -Sum).Sum; [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB); Test-Connection the compute host -Count 1 -Quiet"
curl -s -A "Mozilla/5.0" -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/pods | head -c 400
```
Expected: The primary desktop 24 logical CPUs and 128 GB (as of 2026-09-26); the compute host reachability true or false; the RunPod pod list. Record them in `throughput/placement.json` with competing work observed (`tasklist` entries for `phase1_bo3_collect_v1.exe`, `cargo.exe`, `mtg_kernel*`) and existing reservations.

- [ ] **Step 3: Scaling comparison**

Write `throughput/scale-config-W.json` for W in 1, 4, 8, 12, 16: the Task 8 config with bots `uniform` (builtin, seed 11), g115 and a48 (no `--decision-log`), `include_self_play: false`, `pairs_per_matchup: 8`, `workers: W`, `tournament_dir` `throughput/run-W`. Run each:
```bash
cd $SB
for W in 1 4 8 12 16; do
  python -c "import subprocess, sys, time; t = time.perf_counter(); r = subprocess.run(['uv', 'run', '--no-sync', 'spellbench', 'run', sys.argv[1]]); print('W=$W', round(time.perf_counter() - t, 2), 's exit', r.returncode)" \
    E:/spellbench-archive/2026-09-27-c-kernel-models/throughput/scale-config-$W.json
done
```
Expected: 48 games per run, 0 forfeits; wall seconds per W. Write `throughput/throughput.json` with games per second per W, the chosen W (highest completed games per second; ties go to fewer workers), the projected full-run time for 960 games, and the placement decision: The compute host or RunPod only if the projected saving exceeds their setup (a Windows release build of this branch, about 100 MB of model assets, config rewrites) and, for RunPod, cost. State that `spellbench bench run` has no throughput guard (an unguarded launch path, COMPUTE-POLICY item 17).

- [ ] **Step 4: Add the bots and the flag to the benchmark**

In `benchmarks/pauper-kernel/benchmark.json` set `"engine": {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}", "--x-kernel-flat-v4"], "timeout_ms": 120000}`, set `"workers"` to the chosen W, and append to `"bots"`:
```json
    {
      "name": "g115", "version": "1.0.0", "type": "subprocess", "owner": "jackmaiorino", "engine": "mtg-kernel",
      "training_style_tags": ["reinforcement-learning"],
      "command": ["${PYTHON}", "${MTG_KERNEL_FLAT_BOT}", "--scorer", "${MTG_KERNEL_SCORER}", "--config", "${G115_SCORER_CONFIG}", "--name", "g115", "--version", "1.0.0"],
      "checkpoint": "${G115_CHECKPOINT}",
      "display": {"label": "g115", "author": "mipo", "description": "mtg-kernel policy network, Phase 1 lineage g block 115 (32,400 updates), sampled, no search. Trained on 7 of the 8 decks: never saw Spy or CawGates.", "url": null}
    },
    {
      "name": "a48", "version": "1.0.0", "type": "subprocess", "owner": "jackmaiorino", "engine": "mtg-kernel",
      "training_style_tags": ["reinforcement-learning"],
      "command": ["${PYTHON}", "${MTG_KERNEL_FLAT_BOT}", "--scorer", "${MTG_KERNEL_SCORER}", "--config", "${A48_SCORER_CONFIG}", "--name", "a48", "--version", "1.0.0"],
      "checkpoint": "${A48_CHECKPOINT}",
      "display": {"label": "a48", "author": "mipo", "description": "mtg-kernel policy network, Phase 1 lineage a block 48 (8,800 updates, independent initialization), sampled, no search. Trained on 7 of the 8 decks: never saw Spy or CawGates.", "url": null}
    },
    {
      "name": "c12", "version": "1.0.0", "type": "subprocess", "owner": "jackmaiorino", "engine": "mtg-kernel",
      "training_style_tags": ["reinforcement-learning"],
      "command": ["${PYTHON}", "${MTG_KERNEL_FLAT_BOT}", "--scorer", "${MTG_KERNEL_SCORER}", "--config", "${C12_SCORER_CONFIG}", "--name", "c12", "--version", "1.0.0"],
      "checkpoint": "${C12_CHECKPOINT}",
      "display": {"label": "c12", "author": "mipo", "description": "mtg-kernel policy network, Phase 1 lineage c block 12 (4,000 updates), sampled, no search. Trained on all 8 decks plus Terror.", "url": null}
    }
```
Set `benchmarks/local.json` (git-ignored) to:
```json
{
  "MTG_KERNEL_BRIDGE": "D:/cargo-target/mtg-kernel-spellbench-g115/release/agent_bridge_v1.exe",
  "MTG_KERNEL_SCORER": "D:/cargo-target/mtg-kernel-spellbench-g115/release/spellbench_scorer_v1.exe",
  "PYTHON": "~/IdeaProjects/spellbench/.venv/Scripts/python.exe",
  "MTG_KERNEL_FLAT_BOT": "~/IdeaProjects/spellbench/integrations/mtg_kernel/kernel_flat_bot.py",
  "G115_SCORER_CONFIG": "E:/spellbench-archive/kernel-bots/g115.scorer.json",
  "G115_CHECKPOINT": "D:/phase1-live/campaign-002/g/block115/run/iterations/000199/attempt-000000/update/checkpoint.json",
  "A48_SCORER_CONFIG": "E:/spellbench-archive/kernel-bots/a48.scorer.json",
  "A48_CHECKPOINT": "D:/phase1-live/campaign-002/a/block48/run/iterations/000199/attempt-000000/update/checkpoint.json",
  "C12_SCORER_CONFIG": "E:/spellbench-archive/kernel-bots/c12.scorer.json",
  "C12_CHECKPOINT": "D:/phase1-live/campaign-002/c/block12/run/iterations/000199/attempt-000000/update/checkpoint.json"
}
```
In `spec/SPELLBENCH_PROTOCOL_V1.md` section 9 append one sentence (documentation only): "Run with `--x-kernel-flat-v4`, the bridge also emits `x_kernel_flat_v4`, the acting seat's model input for mtg-kernel Phase 1 policies (see the bridge contract)."

Run: `cd $SB && uv run --no-sync python -c "from pathlib import Path; from spellbench.bench import definition; b = definition.load_benchmark(Path('benchmarks/pauper-kernel').resolve()); print([bot.entry['name'] for bot in b.bots], definition.placeholder_names(b))"`
Expected: `['uniform', 'heuristic', 'first', 'g115', 'a48', 'c12']` and the ten placeholder names of `local.json`.

- [ ] **Step 5: Smoke run (zero forfeits required)**

Write `throughput/smoke-config.json`: bots `uniform` and g115 exactly as in the benchmark (placeholders replaced by the local.json values), `"deck_pool": [{"catalog_id": "Burn"}]`, `pairs_per_matchup: 1`, `include_self_play: false`, `tournament_dir` `throughput/smoke`. Run `uv run --no-sync spellbench run E:/spellbench-archive/2026-09-27-c-kernel-models/throughput/smoke-config.json`.
Expected: `games: 2 total, ... 0 forfeit`. Any forfeit stops the task (misconfiguration).

- [ ] **Step 6: Re-launch the benchmark**

```bash
cd $SB
SPELLBENCH_SOURCE_REVISION=$(git -C $MTGK rev-parse HEAD) uv run --no-sync spellbench bench run benchmarks/pauper-kernel
```
Expected: `games: 960 total, N rated, ...` with `0 forfeit`; the command validates the run (no failures). Halted games are expected only with reasons from the goad and menace defects (`session_step_rejected_after_validation` or `flat_v4_lockstep:selection_not_in_training_list` when a builtin picks a dropped candidate) or kernel halts; any other `flat_v4` reason stops the task.

- [ ] **Step 7: Validate, build the site, commit**

```bash
uv run --no-sync spellbench site benchmarks E:/spellbench-archive/2026-09-27-c-kernel-models/site-check
git add benchmarks/pauper-kernel spec/SPELLBENCH_PROTOCOL_V1.md
git commit -m "pauper-kernel: add g115, a48, c12 and re-launch on the V4 engine (measurement only)"
```
Expected: the site builds; the commit contains the benchmark, the run directory and the spec sentence. Do not push (the maintainer's call).

---

## Self-review

- Spec coverage: port (Task 1), lockstep and equality (Task 2), extension with digests (Task 3), scorer V4 and seeded sampling (Task 4), bot and its location (Task 5), halts for missing inputs (Task 6), harness-equality qualification (Tasks 7 and 8), benchmark entry and re-launch with COMPUTE-POLICY (Task 9). Measurement-only and read-only constraints are global.
- Types: `row_candidate_ids` is `Vec<u32>` in Rust and a list of ints in Python everywhere; selection strings `sampled-wide-v1` and `argmax-first-v1` match across Tasks 4, 5 and 7; the log format of Task 5 is exactly what Task 7 deserializes (`deny_unknown_fields` on both records); halt reason prefixes match the Global Constraints.
- Placeholder scan: data-dependent values (Task 1 re-pin seeds, Task 9 worker count) come from named command outputs in the same task.

## Execution notes

Subagent-driven is recommended: tasks 2, 3, 4 and 5 run in parallel on disjoint files, every later task depends on exact names from earlier ones, and a shipped mistake would publish wrong ratings for the maintainer's models.
