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
| E4 horizon | threshold written before measuring (`E4-threshold.md`). S1 to S9 and the DraftZero positions: 0 flagged stack objects, MAD horizon 0; MCTS truncation 0% at rollout caps 1000 and 5000, 100% at 200. Game set (`e4-horizon-games.json`): 13 anchors held a flagged object, all above clause 1's 25%, cause `stack_ability_identity` (a source with several triggered abilities, for example Emberheart Challenger) and one `stack_source_ambiguous`: **these kinds now go without search** (the kit declines, tagged wrapper), implemented after the measurement. H3 in game at cap 300: 32.6% truncated (clause 2 not crossed) | outcome is a register change, see Deviations |
| E5 determinism (R-1) | PASS: one schedule (4 games, H1 against heuristic) twice, concurrently, separate processes and work directories: 4/4 game digests equal, 694/694 kit answers equal; earlier code gave the same four digests | `r1/`, `r1-pre-e4/`; same machine only (Jack's PC was off limits); `game_id` not varied (the kit's seeds read only `agent_seed`) |
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

## Game set (H1 entry, through P's host and live validator)

Final code (`games/`), seat-swapped pairs over Standard16-RG and Standard16-UB, run secrets in each `summary.json`:

GAMESET_TABLE

## Numbers the design left to the slice

| Number | Value | Basis |
|---|---|---|
| MAD node budget | 5000 (upstream default; error threshold budget + 100) | E7 equality; fired in 3 of 324 game anchors |
| Option-generation budget | 2000 options per playable | fired only in the runaway position |
| Operation cap | 20 000 callbacks per MAD root alternative or MCTS iteration | never fired outside E2 |
| MCTS iterations | 20 to 30 per world per decision in the slice | 0.09 to 0.2 s per iteration unloaded (0.5 to 1.2 s under load); the upstream UCT term spreads 30 iterations almost evenly over the root children |
| MCTS rollout cap | 1000 priority callbacks | 0% truncated at 1000 and 5000, 100% at 200 |
| Safety deadline | `min(max_decision_ms, remaining_ms)` - grace - 1500 ms | E3 |
| Grace period | 5000 ms | E3: kill to confirmed exit 0 ms |
| Runner restart | 12 to 14 s boot (framework warm-up, card database), off the decision clock | E3 |
| E4 thresholds | 25% horizon share (MAD), 50% truncated rollouts (MCTS), 10% dropped pending triggers | `E4-threshold.md` |

## Measured costs (E8; replaces Section 8.1 and 9.2 guesses)

Runtime, HaleysPC: COSTS_TABLE

Integration (this agent's wall clock, 2026-10-01, about 04:40 to 07:45 EDT, including a 30 minute machine hold): the
whole slice took about 3 agent-hours against the provisional 7 to 10 agent-days. Per case, from first code to a
passing check: skeleton (front, runner, world builder, sampler, MAD diff, plans) 50 min to the first H1 game; S1 10
min; S2 15 min (departed-source rebuild); S3 10 min; S4 15 min (looked-at cards in the continuation); S5 10 min; S6
10 min (the own-history rule had to be rewritten); S7 and the MCTS diff 25 min; S8 5 min; S9, sentinel and E2 15
min; E3 30 min (two real faults: an H2 lock left by a killed runner, and a self-join in the restart path); E5 5 min;
E7 20 min. The provisional estimates of 9.2 are agent-days of a slower process; on this evidence the remaining items
(A1 build-out, A2, H3, A3) are dominated by register coverage (cards and mechanics), not by architecture.

## Diagnostics (Section 7.2, never gates)

Observation round trip (the world projected through the engine's own `ObservationBuilder`, compared modulo ids):
ROUNDTRIP. World flags over the H1 anchors: FLAGS.

## Deviations from the design

1. Continuation answers only the first dialog of a resolution; a later dialog of the same resolution takes the
   current-dialog path (earlier answers are recorded but not replayed).
2. Chains are replanned at every priority decision (Section 6.1 allows it); ComputerPlayer7's `actionCache` does not
   carry across decisions, since each world has a fresh decider.
3. ComputerPlayer7 passes without searching outside the main phases and the declare steps; the front answers those
   pass decisions itself, without a world (the bot's own answer; saves about 40% of anchors).
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
