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

## Build-out after the A1 result review (Sol, PROCEED WITH CHANGES): changes 1 to 7 run

Review: `E:/spellbench-archive/program-research/reviews/a1-sol-opinion.md`. Run 2026-10-01 on HaleysPC at below-normal
priority, after merging `origin/xmage-x0-x1` (X-P4 core patch; engine rebuilt: `rules_snapshot_id`
`xmage-fd40ad5c...-xpat-6f8a902b...`, `lib_digest` `c81b025a...`). Records in `buildout/`: `finalA.jsonl` (71/71
PASS: S1 to S9, SENTINEL, E2, E7MCTS, E7MAD, S2P, S3P, S4P, S10P, REG, POOLAUDIT), `finalB.jsonl` (8/8 PASS: A3,
MCTSPOWER), `core-*.jsonl` (SliceCore 12/12, TerminationCheck PASS, FrontCheck 11/11), `unmapped/`, `games/`.
Change 8 (qualification, soak) waits for a coordinator go.

| Change | Code | Result |
|---|---|---|
| 1 production continuation | the continuation's picks are the plan of the whole logical dialog; later substeps, forced steps and the finish from that plan; anchors at every priority decision with the object on top (inputs only); earlier dialogs of the resolution replayed from this seat's own answers; arrangement plans from all looked-at cards | PASS. FrontCheck: picks preserved (one runner request for a three-substep group), forced substep advances the plan, finish at the plan's end, earlier dialog sent for the later one. Through a real front and runner: S2P (Hart search answered by one continuation, two lands), S3P (planned card discarded after the draw), S4P (mode by the current dialog, scry group by continuation, library top and bottom as planned), S10P (Cultivate: the second dialog continued after replaying the first) |
| 2 one clock per `choose` | `Front.Clock`, `RunnerLink.call(request, waitUntil, answerBy, grace)`, `Busy`, reaper | PASS (FrontCheck): `max_decision_ms` 4000 answered in 3417 ms (runner killed, exit confirmed); `remaining_ms` 4000 in 3405 ms; a decision during a 6 s reboot answered in 1200 ms (`runner_restarting`, no second kill), the replacement served the next one; slow continuation then dialog 2509 ms of 4000; slow diagnostics 3413 ms of 4000 |
| 3 register | `register/scan.py`, `register.json` (394 cards: 316 supported, 72 approximate, 6 unsupported; 27 of 32 pool decks admitted; excluded Standard-MonoR, Standard-MonoW, Standard16-5C, Standard16-BW, Standard16-RG), `WorldBuilder` enforcement, emblem rebuild | PASS. REG: trigger event data (Youthful Valkyrie), optional-cost state (Burst Lightning, kicker), a target that left (Shock after Stab) all flag the horizon and skip the priority search; Kaito's emblem rebuilt and projected as the engine shows it. POOLAUDIT: 394 cards create, 58 token classes resolve by name, 1 emblem class instantiates, 0 problems |
| 4 non-stack payload | declared unsupported: next ranked candidate, wrapper | PASS (REG): Thriving Bluff's color choice detected as a non-stack dialog. Games: 0 such choices |
| 5 mapping recoveries | chosen ability and failure reason in the runner's reply; `kitlog.py` per searched decision and mechanic | **Root cause found and fixed.** Replayed on the slice commit with dumps (`scripts/diagnose-unmapped.sh`; the heuristic game reproduced its two Kaito decisions; the uniform game diverged after step 315 under the new engine and gave five of its seven plus two new ones at 494 and 504). Every one was MAD searching **the active opponent's options**: the world set the player list's current player to the active seat, and MAD's root takes its player from there, so on the other seat's turn it chose the opponent's Kaito +1, the opponent's sampled Darkslick Shores, the opponent's sampled Cut Down. Fix: the current player is the priority holder. After it, all nine map to offered candidates (`unmapped/unmapped-fixed`). Games after the fix: 0 unmapped in 222 searched priority decisions |
| 6 entry identities | `Entries`: kit-mad-1, kit-mad-k (K = 4), kit-mcts (K = 1, 30 iterations, rollout cap 1000); identity = name + config digest; H3 on upstream dispatch (MCTS at every priority decision and for combat) | kit-mad-1 `0.2.0+71444ecbf4b3`, kit-mad-k `0.2.0+b0baca643a2a`, kit-mcts `0.2.0+b1166f62616a`. Smoke games below |
| 7 E4 accounting, A3 | `horizon_hits` per MAD root alternative; truncated expansions and expanded children for MCTS; `e4.py` share never above 1 | E4 re-measured (H1, 8 games, measurement mode, same schedule as the slice): 5 flagged anchors searched, 13 of 13 evaluated root alternatives met the horizon (share 1.0 each; 17 encounters, reported separately), so clause 1 still fires and the decline stands. A3 (final code): counterspell pair equal modulo ids (the hidden cards shift the engine's ids), cantrip pair identical; the same answer in each pair for kit-mad-1, kit-mad-k and kit-mcts. MCTSPOWER at cap 1000: 0 of 400 rollouts truncated in all eight runs |

Games after the fix, frozen identities, P's host and live validator, HaleysPC:

| Set | Games | Endings | Violations, forfeits, halts | Decisions checked | Kit wins | Searched priority decisions, unmapped | Wall s |
|---|---:|---|---|---:|---:|---|---:|
| E4 measurement, kit-mad-1 (search-flagged, custom identity), Standard16-RG and -UB | 8 | 8 natural | 0, 0, 0 | 2826 | 5 | 143, 0 | 278.6 |
| smoke kit-mad-1, Standard16-UB and -GB | 2 | 2 natural | 0, 0, 0 | 940 | 2 | 44, 0 | 120.5 |
| smoke kit-mad-k, Standard16-UB and -GB | 2 | 2 natural | 0, 0, 0 | 959 | 0 | 35, 0 | 202.3 |
| smoke kit-mcts (`0.2.0+b1166f62616a`, cap 1000), Standard16-UB | 1 | 1 natural | 0, 0, 0 | 542 | 1 | 43, 0 | 1014.7 |

kit-mcts in game: 43 MCTS priority decisions (median 17.9 s, p90 38.3 s, max 51.5 s), 8 MCTS combat decisions, 1290
completed iterations, 0 truncated rollouts and 0 truncated expansions at cap 1000 (E4 clause 2 not crossed). The
slice's deviations 1 (continuation first dialog only), 4 (non-stack payload), 5 and 6 (triggers, pending triggers,
command zone), 10 (H3 dispatch) and 13 (E4 outcome) are superseded by this section.

Continuation in games: 4 decisions answered on the continuation path; 16 continuation attempts fell back to the
current dialog on a projection mismatch
(approximate worlds; the fallback answers in the same clock).

E7 is **algorithm preservation with the wall timeout inactive**, on worlds from the corrected builder: the reference is
upstream `ComputerPlayer7` from the pristine sources with its wall-clock limit (skill x 3 s = 18 s) raised to 3,600 s
(`xmage/e7/E7Probe.java`), so both sides search to the node budget; it is not stock MAD at its default timeout. With
the limit active the loaded machine changed the reference's answer at one position. All 61 compared positions are
equal (17 skipped: cap or horizon active). The slice's E7 (72/72) used worlds from the builder with the player-cursor
fault, which both contestants shared, so it does not validate the reconstruction's current player.

MCTS pilot at cap 1000 (`finalB.jsonl`): upstream UCT (integer exploitation term) spreads the 400 iterations exactly
evenly over the root children (100 or 80 visits each); kit mode is identical across both pairs (Serra Angel; pass);
oracle mode picks Helpful Hunter in both cantrip worlds, so the hidden top card changes no decision. The C-MCTS
expectation for A3: no decision sensitivity at this budget; wins differ by world (cantrip 4 to 17 per child).
Cost: 0.23 to 0.48 s per iteration (95 to 190 s per 400-iteration world, machine shared).

**kit-mcts rollout cap: 300 rejected by the pre-registered threshold.** E4 clause 2 (`E4-threshold.md`, written
before measuring) is 50% truncated rollouts. In the powered pilot (MCTSPOWER, 400 iterations per world, cap 300,
first build-out run, `buildout/slice-a3-slice.jsonl`) the truncated share was 97 to 98% in the counterspell pair
(388, 392, 388 and 393 of 400 rollouts) and 100% in the cantrip pair (400 of 400 in all four runs); the slice's
H3COST measured 0% at caps 1000 and 5000 and 100% at 200 on the cantrip position. Coordinator decision
(2026-10-01): kit-mcts is re-frozen at rollout cap 1000 (new configuration digest); cap 300 is not kept under any
label. A4 measures the extra cost per decision before any rating. Rerun at cap 1000 in the final run: 0 of 400 rollouts truncated in all eight runs.

## Second result review (Sol, NOT READY: changes 2, 3, 4, 6 and 7 partial): items 1 to 5 and regressions

Review: `E:/spellbench-archive/program-research/reviews/a1b-sol-opinion.md`. Branch merged with `origin/xmage-x0-x1`
first (X5's `ability_index` order: own abilities, then granted ones by rule text; the kit maps through the engine's
own `SeatPlayer.abilityIndex` via `KitBridge`, so it agrees by construction; engine rebuilt, `lib_digest`
`d74803d5...`). Records in `buildout/second/`.

| Item | Fix | Test (HaleysPC, final build) |
|---|---|---|
| 1 latch an unconfirmed runner exit | `RunnerLink`: an unconfirmed kill latches the link; no replacement starts (start, `startAsync`) and requests are refused with `Busy("runner_exit_unconfirmed")` until the killed process is seen gone, which clears the latch and removes the locks | FrontCheck `latch.unconfirmed_exit_blocks_restart` (fallback in time, no restart while latched) and `latch.clears_after_confirmed_exit`: PASS |
| 2 skip enforcement and attribution | placeholders take `horizon:stack_object` (no search); a skipped combat world answers the declining candidate tagged `wrapper` | Slice `REG.placeholder_no_search`, FrontCheck `skip.combat_is_wrapper`: PASS |
| 3 H3 non-stack rejection | the vendored MCTS players count every dialog; at the root an action that leaves no stack object and asked a dialog is never a child (`mcts:non_stack_dialog_excluded`) | Slice `REG.h3_non_stack_excluded_before_selection` (Thriving Bluff excluded, a plain Mountain play kept): PASS |
| 4 complete identity | clock policy (grace, overhead, kill reserve) and diagnostics (round trip, hang hook) are in the configuration and its digest; any change gives `-custom`; `--name` and `--version` are refused | FrontCheck `identity.full_configuration`: PASS |
| 5 E4 over all MCTS work | every MCTS search counted once (priority and combat); iterations split into actual rollouts (`simulate`), terminal-node results (new counter) and empty expansions; clause 2 = truncated rollouts over actual rollouts, with denominators per kind and in total | `tests/e4.py` on the final kit-mcts game, below |
| opponent-turn regression | Slice OPPTURN: the opponent casts Serra Angel on its turn; the kit (kit-mad-1, through a real front and runner) searches its own options and casts Refute; seats swapped | `OPPTURN.p1` and `OPPTURN.p0`: PASS |
| nine positions | replayed and archived (`buildout/unmapped/positions/`, diagnosis on the final build in `unmapped-final.jsonl`): all nine choose offered candidates. Seven are the original positions; the uniform game diverged after step 315 on the X-P4 engine, so its last two originals (460, 462) could not be reproduced and the two unmapped positions of the replay (494, 504) stand in for them | UNMAPPED: PASS |

**A further discrepancy found and fixed.** The first final-build kit-mcts game had 1 unmapped choice in 37 searches:
MCTS chose Fountainport's `{3}, {T}, Pay 1 life` ability, which the engine did not offer. The game replayed with
dumps (same digest, `sha256:1ac71f9f...`), and Slice PLAYABLE showed 6 of 38 positions where XMage's playable list on
the world holds a Fountainport ability the engine does not offer (the engine offers only what its autopay can pay;
the land's own tap cost cannot also pay for it). Both bots now take root alternatives only among the decision's
offered candidates (`KitContext.rootFilter`, set by the runner for priority searches; MAD records the others as
`not_offered` root statistics). Slice OFFERED on those six positions: MAD and MCTS choose offered actions: PASS. E7
compares the search with the filter off.

**Two kit-mcts faults found by the smoke games and fixed.** (a) A runner error, `IndexOutOfBoundsException` in the
vendored `SelectBlockersNextAction`: upstream declares a block against `getAttackers().get(0)` of a combat group whose
attacker had left combat; reproduced from a dump (Slice OFFERED, position 214) and fixed (such groups are skipped;
`ComputerPlayerMCTS.selectBlockers` likewise). (b) `OutOfMemoryError` in MCTS blocking with 8 combatants: upstream
enumerates every block assignment, each a child game copy. A combat option budget (`combat_options`, 128
engagements per expansion, upstream order, `cap:combat_options` counted) is now part of kit-mcts, which therefore
has a new identity.

Final build results (`buildout/second/`): kit-core SliceCore 12/12, TerminationCheck PASS, FrontCheck 15/15;
Slice `finalA.jsonl` 76/76 (S1 to S9, SENTINEL, E2, E7MCTS, E7MAD 61/61, S2P, S3P, S4P, S10P, REG with the
placeholder, H3 non-stack and Thriving Bluff cases, POOLAUDIT, OPPTURN both seats, OFFERED 7 positions);
`finalB.jsonl` 8/8 (A3 for the three entries, MCTSPOWER at cap 1000: 0 of 400 rollouts truncated). Games (P's
host, live validator, Standard16-UB and -GB):

| Entry and identity | Games | Endings | Violations, forfeits, halts | Decisions checked | Kit wins | Searched priority, unmapped | Decision ms median, p90, max |
|---|---:|---|---|---:|---:|---|---|
| kit-mad-1 `0.2.0+da7301f729c0` | 2 | natural | 0, 0, 0 | 768 | 1 | 48, 0 | 154, 5852, 17003 |
| kit-mad-k `0.2.0+6f73bc90a85d` | 2 | natural | 0, 0, 0 | 801 | 1 | 51, 0 | 485, 14364, 70274 |
| kit-mcts `0.2.0+61e5852dd13f`, replay of the runner-error game | 1 | natural | 0, 0, 0 | 423 | 1 | 39, 0 | 16168, 40930, 43885 |
| kit-mcts, replay of the Fountainport game (out-of-memory blocks in the round before) | 1 | natural | 0, 0, 0 | 713 | 1 | 63, 0 | 12357, 19241, 31143 |

E4 over all MCTS work in these two games (`tests/e4.py`): 44 and 71 searches (5 and 8 combat); actual rollouts 1286
and 2128, terminal-node results 34 and 2, empty expansions 0; truncated rollouts 13 of 1286 (1.0%) and 1 of 2128
(0.05%): clause 2 not crossed; truncated expansions 0 of 3285 and 0 of 6901. kit-mad-k's decision maximum (70 s
in this run, 87 s in the previous) leaves 50 s and 33 s under the 120 s limit; it searches the opponent's turn
since the current-player fix.

Reproducibility observed on the way (not a qualification): the kit-mcts game replays matched their originals'
digests (`sha256:1ac71f9f...`, `sha256:750c34bc...`) before the later fixes changed the code.

## Third result review (Sol): READY FOR QUALIFICATION at `4580f8f`

Review: `E:/spellbench-archive/program-research/reviews/a1c-sol-opinion.md`. The 128-engagement combat cap is
accepted as a labelled baseline: it keeps a prefix of upstream's enumeration, so it is biased toward that prefix
(with eight available attackers the no-attack engagement is outside it); kit-mcts's description says so
(`qualify/kitrun.py`, `ENTRY_DESCRIPTIONS`; kit README), and cap firings are reported separately for attack and
block decisions (`tests/kitlog.py`, `combat_option_cap`). Change 8 is prepared in `qualify/` (README there) and not
run: it waits for a guarded machine and the coordinator's go. Prepared since: per-game kit logs (`--log-dir`,
checked in one FDN game on HaleysPC, not a qualification), `kitrun.py` (plan, P's `plan_allocation` qualification,
guarded run, R-1 replay, summary with the pass criteria), `launch.sh`.

## Change 8 plan (not started; waits for a coordinator go)

Entries: kit-mad-1 and kit-mad-k enter the first soak; kit-mcts waits for its own qualification with the provisional
profile 120 s per decision, a 3,600 s bank, 2 s increments and 300 s startup and game start (cap 1000 and 30
iterations kept; cap 300 stays rejected). Pass criteria, from the review's last section:

1. Qualified allocation: one worker against increasing worker counts on identical representative inputs; Jack's
   PC, HaleysPC and RunPod availability checked; completed-game throughput including database copies, JVM start,
   search, mapping, validation, output and recovery; the fastest eligible allocation recorded in the small manifest;
   the launcher refuses missing or incompatible qualification evidence before spawning the soak.
2. Preserved outputs and usable clocks: matched game digests across worker counts; decision tails, combat costs,
   bank consumption, cap firings, restarts and resources at the selected concurrency; the clock profile frozen before
   the soak, the same for every opponent.
3. The soak: 1,000 games per admitted entry against P's builtins on `fdn-mirror-v0`, then the declared cross-entry
   games, covering the pool and both seats, with the 20-game R-1 replay on the final build.
4. Passing results: zero `invalid_selection` and `malformed_response`; pool deficits and surpluses zero or
   explained; timeouts, halts and resource failures kept and accounted for; wrapper and cap rates by kind and
   mechanic; E4 over all MCTS work.
5. Rated admission: engine, entry configuration, clock profile and admitted pool equal to the qualification's;
   per-game isolation verified (no writable state survives into another game). The pool audit shows availability,
   not exact reconstruction.

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
