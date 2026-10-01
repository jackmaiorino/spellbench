# A1 vertical slice: evidence (2026-10-01, HaleysPC)

Design A0 revision 3 with its addendum (`E:/spellbench-archive/program-research/x-agent-kit-design.md`, Section
9.1); issue spellbench#28. Everything ran on HaleysPC at below-normal priority, JDK 23.0.2, engine built from this
branch with `engines/xmage/scripts/build.sh` (unchanged identity: `rules_snapshot_id`
`xmage-fd40ad5c...-xpat-8c2578bef...`, `lib_digest` `6a942b3f...`), P's stack at protocol-v2 `4b588a1`. Kit build
manifest: `KIT-MANIFEST.json`.

## Verdict

Every slice case S1 to S9, every exit criterion E1 to E8 and every addendum change has a result below. The kit-wrapped
MAD entry (H1) played the slice's game set through P's host against the XMage engine with zero validator violations,
zero forfeits and zero halts. Two items are partial (marked): continuation beyond the first dialog of a resolution,
and the executed payload of non-stack actions. One pre-registered threshold fired (E4 clause 1) and its outcome is
implemented.

## Build-out after the A1 result review (Sol, PROCEED WITH CHANGES; in progress)

Review: `E:/spellbench-archive/program-research/reviews/a1-sol-opinion.md`. Code for changes 1 to 7 is on branch
`xmage-agent-kit`; its checks need HaleysPC (builds, Java and games are on hold for the X5 benchmark), so every
row below is **pending a run** unless it says otherwise. Change 8 (qualification, soak) waits for a coordinator go.

| Change | Code | Verification (pending unless noted) |
|---|---|---|
| 1 production continuation | `Front`: the continuation's picks are the plan of the logical dialog (no second request at substep 0); later substeps, forced single-candidate steps and the finish come from that plan; anchors are saved at every priority decision with the object on top (inputs only); the resolution's earlier dialogs (this seat's own answers after the anchor) go to the runner. `Continuation`: replays them (selections, yes/no, numbers, modes; arrangements are planned but not replayed), counts repeated XMage calls on one target as one dialog, plans arrangements in the front's format, declines a flagged source | `FrontCheck` (fake runner): picks preserved across substeps, forced step advances the plan, finish at the plan's end, earlier dialog sent for the later one. `Slice` S2P, S3P, S4P, S10P (Cultivate: second dialog after replay) through a real front and runner |
| 2 one clock per `choose` | `Front.Clock`, `RunnerLink.call(request, waitUntil, answerBy, grace)`: restart waiting, the runner's deadline, continuation, the current dialog after it, diagnostics and the kill share one answer time; a booting replacement is never killed (`Busy`); an unconfirmed exit is confirmed by a reaper before the next start | `FrontCheck`: `max_decision_ms` binds, `remaining_ms` binds, a decision during a 6 s reboot answered in time without a kill, slow continuation then dialog, slow diagnostics |
| 3 register | `register/scan.py` + `register.json` (394 cards: 316 supported, 72 approximate, 6 unsupported; **27 of 32 pool decks admitted**, excluded: Standard-MonoR, Standard-MonoW, Standard16-5C, Standard16-BW, Standard16-RG, all for restricted-mana lands or Gwenna); `WorldBuilder`: trigger event data, captured activation values, optional-cost state and incomplete stack targets take the horizon; dropped pending triggers stop priority searches; emblems rebuilt; unsupported states not searched (`Runner.skipReason`) | `Slice` REG (four state conditions and the emblem rebuild), POOLAUDIT (every token class resolves by name, every emblem instantiates). The static scan ran locally (Python only) |
| 4 non-stack payload | declared unsupported: an executed action that leaves no stack object and asked a dialog is reported (`non_stack_dialogs`) and the front answers the next ranked candidate (wrapper); the register lists such cards (`non_stack_choices`) | `Slice` REG (Thriving Bluff's color choice detected) |
| 5 mapping recoveries | runner reports the chosen ability (class, type, source, zone, rule, index) and the failure reason; `kitlog.py` reports failures per searched decision and per mechanic. Restated: the nine are **9 of 310 searched priority decisions (2.9%)**, not 9 of 2,460 answers; two named a Kaito activation the engine did not offer, seven had no semantic at all | `scripts/diagnose-unmapped.sh`: replays the two games on the slice commit with dumps that carry the decision's own history, then `Slice` UNMAPPED on the nine |
| 6 entry identities | `Entries`: kit-mad-1, kit-mad-k (K = 4), kit-mcts (K = 1, 30 iterations, rollout cap 1000, truncation scoring; see the cap decision below); identity = name + config digest; H3 restored to upstream dispatch (MCTS at every priority decision with more than one candidate, MCTS combat with a budget boundary in combat expansion) | `Slice` A3 runs all three entries; game set after the go |
| 7 E4 accounting, A3 | MAD root alternatives carry `horizon_hits`; the front logs evaluated and affected alternatives; MCTS counts truncated expansions and expanded children; `e4.py` reports the affected share (never above 1), encounters, declines, truncated rollouts and expansions separately. The slice's E4 "shares" of 2.0 were encounters over root stats and are withdrawn | E4 re-measured with `--search-flagged 1` on the E4 game schedule; `Slice` A3 (identical permitted inputs across the counterspell and cantrip pairs, same answer, for kit-mad-1, kit-mad-k, kit-mcts) and MCTSPOWER (400 iterations: every root child at least 40 visits, kit vs oracle) |
| 8 qualification and soak | not started (after a coordinator go) | |

**kit-mcts rollout cap: 300 rejected by the pre-registered threshold.** E4 clause 2 (`E4-threshold.md`, written
before measuring) is 50% truncated rollouts. In the powered pilot (MCTSPOWER, 400 iterations per world, cap 300,
first build-out run, `buildout/slice-a3-slice.jsonl`) the truncated share was 97 to 98% in the counterspell pair
(388, 392, 388 and 393 of 400 rollouts) and 100% in the cantrip pair (400 of 400 in all four runs); the slice's
H3COST measured 0% at caps 1000 and 5000 and 100% at 200 on the cantrip position. Coordinator decision
(2026-10-01): kit-mcts is re-frozen at rollout cap 1000 (new configuration digest); cap 300 is not kept under any
label. A4 measures the extra cost per decision before any rating. The pilot is rerun at cap 1000 in the final run.

## Cases (Section 9.1)

| Case | Result | Evidence |
|---|---|---|
| S1 Stab, targets preselected by MAD | PASS 7/7: MAD chose Stab on Grizzly Bears; executed payload read from the spell on the stack; plan answered the engine's `choose_target`; live-source rebinding bound; cast and resolution transitions equal modulo ids; hand-written assertions (target, Bears died) | `slice-xmage.jsonl` S1.* |
| S2 Burnished Hart | PASS 9/9: candidate mapped back to the world's ability; stack entry with `source: null` bound by name lineage; `searching` entries present and addressable; continuation at the search matched the engine's observation; resolution transition equal; Hart in graveyard, two lands tapped; knowledge cleared by the shuffle | S2.* |
| S3 Strix Lookout draw then discard | PASS 5/5: saved-anchor continuation with the drawn card pinned on top; world hand +1 and library -1 at the dialog (no effect repeated); resolution transition equal | S3.* |
| S4 Charming Prince, scry 2 | PASS 8/8, both variants: mode chosen by the current dialog (ComputerPlayer.chooseMode, mode 0); continuation matched the `arrange_card` decision; 2n-1 = 3 decisions; both-on-top has a two-candidate order pick, the top/bottom split poses a single-candidate order pick; library order as planned | S4.* |
| S5 cast whose payment fails | PASS 2/2: the engine offers Burst Lightning off Rockface Village, autopay fails, the engine re-poses priority with `rewind: true` without it; the front's plan, anchors and recorded answers since the action are rolled back. Tested at the front level (the rewind's observation transition is the engine's own) | S5.* |
| S6 first strike (Inspiring Paladin vs Youthful Valkyrie) | PASS 6/6: two worlds vote the same combat key; both damage steps identified by the front's own-history rule; world step equals the engine's XMage step; both transitions equal; Valkyrie died in the first-strike step | S6.* |
| S7 H3 branch-local knowledge | PASS 8/8: (a) a drawn known top card stays in hand, no library pin left, parent copy keeps its pin; (b) an opponent's known card that left the hand is never re-dealt back; (c) shuffle clears positions; (d) 50 re-deals conserve sizes and multisets with pins honored; addendum 1 (reveal without a GameEvent, duplicate names, independent siblings, looks); (e) hook counter: 61 re-deals for 60 simulates, 60 completed iterations, kit and oracle modes | S7.* |
| S8 keys and aggregation | PASS 6/6 (kit-core): old keys collide on `mana_choice` and on trigger `instance`, full-semantic keys do not; A 45+45, B 55, C 55 gives A with the plan from world 0; ties by exact sums; MCTS visit aggregation | `slice-core.jsonl` |
| S9 H2 where worlds disagree | PASS 2/2: four worlds, two distinct choices (Cathar Commando 1, Helpful Hunter 3); every root option has a RootStat with bound type (`exact`, `at_most`) or a reason; vote and plan from world 1 | S9.* |

## Exit criteria

| | Result | Notes |
|---|---|---|
| E1 exact transitions | PASS: 9 observation transitions in S1 to S6 equal modulo ids, plus hand-written assertions | S5 is a front-level rollback test (no kit world executes the failed cast) |
| E2 budgets | PASS: values below; none fires on S1 to S9 except the H3 rollout cap at the debugging cap of 400 in S7 (see E4); the runaway position (Arc Lightning over 30 creatures, plus Shock) fires the option budget, the operation cap, the node budget, the MCTS iteration count and the rollout cap, each answered in under 3 s; `KitBudgetExceeded` thrown 16, caught at the kit's boundary 16 (none swallowed) | the stop is an `Error`, so XMage's `catch (Exception)` blocks cannot swallow it |
| E3 termination | PASS: link check (`e3-termination.jsonl`): stale reply discarded, hung request answered in 3.0 s for a 2 s deadline plus 1 s grace, exit confirmed (kill to exit 0 ms), fresh runner served the next request. In game (`e3-game/`): a priority search that ignores interruption at seat step 48, `max_decision_ms` 20 000: fallback answered in 18.5 s tagged `cap`, runner killed and exit confirmed, the stale H2 lock removed, a replacement booted in the background (12 s), the game ended naturally, zero violations | anchors are kept in the front as inputs (decision and world seed), so a restart loses none |
| E4 horizon | threshold written before measuring (`E4-threshold.md`). S1 to S9 and the DraftZero positions: 0 flagged stack objects, MAD horizon 0; MCTS truncation 0% at rollout caps 1000 and 5000, 100% at 200. Game set (`e4-horizon-games.json`): 13 anchors held a flagged object, all above clause 1's 25%, cause `stack_ability_identity` (a source with several triggered abilities, for example Emberheart Challenger) and one `stack_source_ambiguous`: **these kinds now go without search** (the kit declines, tagged wrapper), implemented after the measurement; in the final set 17 such decisions were declined and none searched (`e4-horizon-final-games.json`). H3 in game at cap 300: 32.6% truncated (clause 2 not crossed) | outcome is a register change, see Deviations |
| E5 determinism (R-1) | PASS: one schedule (4 games, H1 against heuristic) twice, concurrently, separate processes and work directories: 4/4 game digests equal and 657/657 kit answers equal on the final code; the pre-E4 code also gave 4/4 (694 answers, `r1-pre-e4/`) | `r1/`, `r1-pre-e4/`; same machine only (Jack's PC was off limits); `game_id` not varied (the kit's seeds read only `agent_seed`) |
| E6 MCTS knowledge | PASS: S7 (a) to (e); C-MCTS pilot measured (below) and its A3 expectation written | |
| E7 behaviour preservation | PASS: MAD 72/72 positions (dumped from H1 games) same choice as upstream `ComputerPlayer7` from the pristine sources with the same X-P4 build; 10 skipped because a cap or horizon was active; MCTS: with no knowledge the re-deal keeps upstream's semantics (decider hand untouched, sizes and multisets conserved, every unseen name reaches the opponent's hand over 200 re-deals) | `kit-upstream.jar` from `scripts/upstream.sh`; never on an entry's classpath |
| E8 costs | measured (below) | |

## Addendum changes

| # | Result |
|---|---|
| 1 | PASS (S7 addendum checks): reveals, looks and scry choices notify the branch's `KnowledgeWatcher` from the vendored simulated players; duplicate names are counts; sibling copies independent |
| 2 | PASS (E2): the option budget covers modes, cost targets and X (estimate before enumeration, truncation after) in MAD option generation and MCTS expansion; thrown equals caught |
| 3 | PASS (E3): one timely response under both limits (the runner deadline is `min(max_decision_ms, remaining_ms)` minus grace and overhead; a background restart spends no decision's clock), confirmed exit, late results discarded, anchors rebuilt from inputs |
| 4 | PASS (SENTINEL): a flagged sentinel that costs 10 life when resolved, under MAD and MCTS: resolved 0 times; MAD stops at `addActions` (caller level, 2 stops), MCTS in expansion (11) and rollouts (28) |
| 5 | PARTIAL: executed payloads from the spell or the `StackAbility`'s underlying ability (paid-cost targets included); logical-dialog completion (fixed groups, maximum reached, finish) and forced steps fixed (SliceCore). Non-stack actions: the live dialog answers are recorded, the transient executed copy is not captured |
| 6 | PASS: S4 split variant poses the forced single-candidate pick; S8 old keys collide; E7 scoped to caps and horizons inactive |
| 7 | PASS (SliceCore): disjoint allocation with an unknown face-down battlefield card (U = 18, public 2, physical 20, multiset exact) |
| 8 | Recorded: the StateSpec adapter (R3, not in this slice) maps a returned label only when it names exactly one candidate key, until a complete public-equivalence rule is validated |

## Sensitivity pilots and the A3 expectations they fix (Section 7.3)

DraftZero's two positions rebuilt with FDN cards (`DZ.*` notes in `slice-xmage.jsonl`), each decided on a kit-sampled
world and on the oracle world:

| Position | MAD kit | MAD oracle | MCTS kit / oracle (30 iterations, cap 2000) |
|---|---|---|---|
| counterspell R (Refute in hand) | Serra Angel (2875 vs pass 415) | Serra Angel (2875) | Serra Angel / Serra Angel; every root child 7 to 8 visits, all won |
| counterspell N (Island) | Serra Angel (2875) | Serra Angel (2875) | same |
| cantrip E (Llanowar Elves on top) | Helpful Hunter (3192) | Helpful Hunter (2148) | Helpful Hunter / Helpful Hunter; 6 visits per child |
| cantrip L (Plains on top) | Helpful Hunter (3192) | Helpful Hunter (3192) | same |

- C-MAD: the oracle world reproduces the own-draw dependence (Helpful Hunter's root score moves from 3192 to 2148
  with the hidden top card); the kit's worlds give the same scores in E and L. No expectation for the counterspell
  pair: MAD never models the response, and neither mode changes. Expectation fixed for A3: kit mode identical
  across each pair; oracle mode may differ in the cantrip pair.
- C-MCTS: at the slice budget upstream UCT (with its integer exploitation term) spreads the iterations evenly over
  the root children, so neither mode shows sensitivity. Expectation fixed for A3: none until the iteration budget
  gives every root child at least 40 visits; then the C-MCTS row is re-measured before A3 runs.

## Game set (H1 entry, through P's host and live validator)

Final code (`games/`), seat-swapped pairs over Standard16-RG and Standard16-UB, run secrets in each `summary.json`:

| Set | Games | Endings | Validator violations | Forfeits, halts | Decisions checked | Kit wins | Kit answers: bot / wrapper / cap | Mean game wall s |
|---|---:|---|---:|---|---:|---:|---|---:|
| H1 vs heuristic | 8 | 8 natural | 0 | 0, 0 | 2822 | 6 | 1408 / 24 / 0 | 33.27 |
| H1 vs uniform (round trip on) | 4 | 4 natural | 0 | 0, 0 | 2003 | 3 | 1005 / 23 / 0 | 57.67 |
| H2 (K = 4) vs heuristic | 2 | 2 natural | 0 | 0, 0 | 667 | 2 | 338 / 18 / 0 | 32.05 |
| H3 (K = 1, 20 iterations, rollout cap 300) vs heuristic | 1 | 1 natural | 0 | 0, 0 | 566 | 1 | 281 / 4 / 0 | 273.53 |

Total: 15 games, 6058 decisions checked by P's live validator, 0 violations. Wrapper answers by path are in each `kitlog-summary.json` (`wrapper_paths`): kinds the current dialog does not synthesize yet (`choose_option`, trigger `order_pick`, non-combat `distribute`), the E4 decline, and a few MAD choices with no offered candidate (`priority_unmapped`).

## Numbers the design left to the slice

| Number | Value | Basis |
|---|---|---|
| MAD node budget | 5000 (upstream default; error threshold budget + 100) | E7 equality; fired in 4 of about 377 game anchors |
| Option-generation budget | 2000 options per playable | fired only in the runaway position |
| Operation cap | 20 000 callbacks per MAD root alternative or MCTS iteration | never fired outside E2 |
| MCTS iterations | 20 to 30 per world per decision in the slice | 0.09 to 0.2 s per iteration unloaded (0.5 to 1.2 s under load); the upstream UCT term spreads 30 iterations almost evenly over the root children |
| MCTS rollout cap | 1000 priority callbacks | 0% truncated at 1000 and 5000, 100% at 200 |
| Safety deadline | `min(max_decision_ms, remaining_ms)` - grace - 1500 ms | E3 |
| Grace period | 5000 ms | E3: kill to confirmed exit 0 ms |
| Runner restart | 12 to 14 s boot (framework warm-up, card database), off the decision clock | E3 |
| E4 thresholds | 25% horizon share (MAD), 50% truncated rollouts (MCTS), 10% dropped pending triggers | `E4-threshold.md` |

## Measured costs (E8; replaces Section 8.1 and 9.2 guesses)

Runtime, HaleysPC, final game set (`costs.json`):

| Set | Kit decisions per seat per game | Answered without a world | Anchors per game | World build ms (median, p90, max) | Search ms per anchor, world 0 (median, p90, max) | Kit s per seat per game | Node cap fired |
|---|---:|---:|---:|---|---|---:|---:|
| H1 vs heuristic | 179.0 | 0.786 | 21.2 | 8.0, 21, 724 | 90.0, 1096, 19017 | 14.9 | 1 |
| H1 vs uniform (round trip on) | 257.0 | 0.758 | 36.8 | 4, 11, 156 | 106, 1837, 12612 | 35.9 | 3 |
| H2 (K = 4) vs heuristic | 178.0 | 0.758 | 14.0 | 6.0, 46, 145 | 106.5, 861, 1128 | 12.6 | 0 |
| H3 (K = 1, 20 iterations, rollout cap 300) vs heuristic | 285.0 | 0.807 | 33.0 | 5, 13, 110 | 8727, 10585, 10932 | 255.1 | 0 |

Design guesses replaced: world build 3 to 7 ms (M1) is 5 to 9 ms median here; MAD 0.2 to 2 s per world is a median of about 0.1 s with a long tail (p90 1 to 2 s; worst 19 s in the final set, 79 s in an earlier set run while the machine was loaded, both at the 5000-node budget); 10 to 160 s per seat per game at K = 1 is 15 to 36 s. Runner boot 12 to 14 s per agent process (`game_start`), a replacement 12 s after a kill. H3: 0.09 to 0.2 s per completed MCTS iteration unloaded, so 20 iterations cost about 9 s per decision in game and K = 4 with 300 iterations would cost minutes per decision.

Integration (this agent's wall clock, 2026-10-01, about 04:40 to 08:10 EDT, including a 20 minute machine hold): the
whole slice took about 3.5 agent-hours against the provisional 7 to 10 agent-days. Per case, from first code to a
passing check: skeleton (front, runner, world builder, sampler, MAD diff, plans) 50 min to the first H1 game; S1 10
min; S2 15 min (departed-source rebuild); S3 10 min; S4 15 min (looked-at cards in the continuation); S5 10 min; S6
10 min (the own-history rule had to be rewritten); S7 and the MCTS diff 25 min; S8 5 min; S9, sentinel and E2 15
min; E3 30 min (two real faults: an H2 lock left by a killed runner, and a self-join in the restart path); E5 5 min;
E7 20 min; final runs and evidence 40 min. On this evidence the remaining items (A1 build-out, A2, H3, A3) are
dominated by register coverage (cards, mechanics, dialog kinds) and machine time for games, not by architecture: a
plausible re-estimate is hours per item, with A3's game volume and H3's search cost the largest terms.

## Diagnostics (Section 7.2, never gates)

Observation round trip (the world projected through the engine's own `ObservationBuilder`, compared modulo ids):
91 of 347 decisions in the uniform set round-trip exactly (26%); by kind activate_ability 7/43, arrange_card 2/2, cast_spell 45/161, choose_boolean 0/2, choose_cost_target 0/1, choose_spell_mode 2/2, choose_target 3/7, declare_attack 4/53, declare_block 2/16, distribute 1/4, mulligan 4/4, order_pick 0/6, play_land 21/40, select_object 0/6. The differences are characteristics (`/players/battlefield/characteristics/keywords` 381, `/players/battlefield/characteristics/power` 337, `/players/battlefield/characteristics/toughness` 256, `/players/battlefield/characteristics/types` 235, `/players/battlefield/characteristics/colors` 161, `/players/battlefield/characteristics/subtypes` 103): until-end-of-turn effects, Kaito's turn-dependent creature form, and Role tokens the world does not rebuild, which the worlds flag `approximate:unexplained_characteristics`, plus graveyard labels shifted by them. World flags over all anchors of the final game set: `approximate:watchers_reset` 387, `approximate:unexplained_characteristics` 226, `unsupported:command_zone` 134, `approximate:activation_usage_other_seat` 40, `own_history:loyalty_used` 25, `horizon:stack_object` 17, `approximate:stack_ability_identity` 16, `unsupported:token` 16, `approximate:token_characteristics` 14, `lineage:stack_source` 4, `approximate:stack_source_ambiguous` 2, `approximate:stack_placeholder` 1, `approximate:blocked_status_from_observation` 1 (of about 377 anchors).

## Deviations from the design

1. Continuation answers only the first dialog of a resolution; a later dialog of the same resolution takes the
   current-dialog path (earlier answers are recorded but not replayed).
2. Chains are replanned at every priority decision (Section 6.1 allows it); ComputerPlayer7's `actionCache` does not
   carry across decisions, since each world has a fresh decider.
3. ComputerPlayer7 passes without searching outside the main phases and the declare steps; the front answers those
   pass decisions itself, without a world (the bot's own answer; a fifth to a quarter of the multi-candidate
   decisions).
4. Non-stack actions: live dialog answers recorded; the transient executed copy is not captured (addendum 5).
5. Triggered abilities on the stack are rebuilt when their source has exactly one triggered ability; whether the
   resolution reads an event object is not checked (register row "triggered abilities" stays approximate in A1).
6. Pending triggers are dropped (flagged `approximate:pending_triggers_dropped`), watchers are reset (every world
   carries `approximate:watchers_reset`), command-zone objects are not rebuilt (`unsupported:command_zone`).
7. Hidden opponent lists use names uniform over the domain (the DomainPrior of 4.2 is A1 build-out); the slice used
   visible lists only.
8. `KitBudgetExceeded` is an `Error`, not an unchecked exception, so XMage cannot swallow it.
9. X-P4 candidate applied on the bot path only: every kit player pays through `KitPayPlayer`, a copy of the engine's
   overlay `AutoPayPlayer` (no engine patch).
10. H3 uses MCTS at priority only; its combat and dialogs use the MAD decider's `ComputerPlayer` heuristics.
11. A killed runner is replaced in the background, and the H2 lock file its database copy keeps is removed after the
    confirmed exit (both found necessary by E3).
12. Fixture positions are built in the X engine's own game with XMage's test-harness cheat (no X5 harness yet).
13. E4 clause 1 fired: decisions on worlds holding a stack object of kind `stack_ability_identity` or
    `stack_source_ambiguous` are answered without search (declining candidate, wrapper).
14. Own history implemented for the first-strike damage step and for the kit's own loyalty activations; other
    activation limits and watcher history are not.
15. The front's `requires.observation` is `passed_seats` and `keywords`.
