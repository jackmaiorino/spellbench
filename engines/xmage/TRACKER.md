# Sub-project X tracker: XMage bots on the Spellbench board

**Final goal.** XMage's own heuristic bots, and RL bots built on XMage (MageZero, DraftZero), rated on Spellbench benchmarks under protocol v2's fairness contract.

**How the bots get there.** Every XMage bot (the rule-based `ComputerPlayer`, the MAD minimax AI, XMage's MCTS, MageZero's network-guided MCTS) is a Java `Player` that reads a live `Game`. A v2 agent sees only its own observation, so none of them can be a thin shim. The shared answer is an **XMage agent kit** (track A):

1. Rebuild an XMage position from the v2 observation.
2. Sample the hidden cards (determinization).
3. Let any XMage `Player` decide on the sampled world.
4. Map its action back to a v2 candidate.

Heuristic bots are the kit's first customers. MageZero and DraftZero use the same kit (brief path B, DraftZero's own experiment-3 plan). This is decision Q2 below.

Design: `E:/spellbench-archive/program-research/x-design-draft.md` (gate addendum 2026-09-30). Research: `x-xmage-brief.md` beside it.

GitHub: parent issue #13 (child issues #14 to #36; the RL track is #36). Status values: `done`, `ready` (no open dependency), `blocked` (names its blocker), `later`.

## Milestones

| Milestone | Meaning | Issues |
|---|---|---|
| M1 | XMage engine conforms to v2.0. First XMage benchmark (`fdn-mirror-v0`: FDN mirrors, visible lists) rated with Spellbench's builtins | X2 to X5, X5m |
| M2 | XMage heuristic bots rated on `fdn-mirror-v0` | A0 to A4, H1 to H4 |
| M3 | Real benchmarks `fdn-limited-v1` and `standard-2022-25` published | X6, P-v2.1 |
| M4 | MageZero and DraftZero rated | R0 to R5, D-sandbox |

## Engine track (X)

| ID | Issue | Status | Depends | Est. (agent-days) | Done when |
|---|---|---|---|---:|---|
| X0 | Pin and build | done (2026-09-30) | | | two clean builds identical per platform; pins and identity strings in README |
| X1 | Determinism and secrets (X-P1 to X-P3, router, per-viewer ids, boot warm-up) | done (2026-09-30) | | | `x1-determinism.sh` PASS on Windows and Linux; stock diverges |
| X1f (#14) | X1 follow-ups: prune WSL `~/x-spike`; strip Maven 3.6 ANSI from the build manifest | ready (after the research lead's quiet window, about 03:35 EDT 10-01) | | 0.1 | done and rebuilt once |
| X2 (#15) | v2 server skeleton: strict I-JSON reader, envelope, retransmission cache, `hello`/`reset`/`step`/`terminal`/`error`, caps, `validate_deck`, stdout isolation, terminal reasons from player state; `reset` drives the X1 router and per-viewer ids | done (2026-10-01): wire contract only | X1 | 2 | P's conformance runner passes 11 of 20 checks; the 9 that need a posed decision move to X3/X4 (`tests/x2/`) |
| X3 (#16) | Observation (Section 6) on `CardView` visibility, normalization tables (Section 6.10), conservative flags (`known_cards` false), per-viewer ids with look counters | done (2026-10-01): 360 games, 539,524 observations, 0 failures (`tests/x3/`) | X2 | 4 to 5 | P's host validator accepts observations over random games; paired-world check on hand and library |
| X4a (#17) | Decision mapping, base: priority kinds, targets, choices, modes, numbers, booleans, mulligan, triggers, replacements, piles | blocked: X3 | X3 | 3 | every kind the engine emits round-trips through P's validator |
| X4b (#18) | Arrangement overrides: scry, surveil, library order (top inverted), London bottom as `2n - 1` and `order_pick` | blocked: X4a | X4a | 1.5 | goldens for each arrangement |
| X4c (#19) | Silent and fail-closed paths: `chooseAbilityForCast` to `choose_cast_method`/`optional_cast`, `chooseTargetAmount` to targets then `distribute`, combat damage per recipient | blocked: X4a | X4a | 1.5 | Chandra, Flameshaper and Quirion Beastcaller playable; no `ComputerPlayer` fallback reached (audit) |
| X4d (#20) | Combat as per-creature groups with a completability oracle on a callback-free copy | blocked: X4a | X4a | 2 | no dead end over 10,000 random games |
| X4e (#21) | Rewind on rejected activations; `engine_autopay` | blocked: X4a | X4a | 1 | rewind golden; no payment loop in the soak |
| X4h (#22) | Hash-order audit of candidate paths (no `HashSet` or UUID order reaches candidate order) | blocked: X4a | X4a | 0.5 | audit note plus a test that shuffles hash seeds |
| X5 (#23) | Conformance on P's host: envelope goldens, XMage goldens with digests, live validator over at least 10,000 random games on both pools, paired-world leak tests | blocked: X4 | X4, P host (exists) | 3 to 4 | zero violations; label "fairness: validator only" |
| X5m (#24) | `fdn-mirror-v0` benchmark (v2.0 as written: frozen pool of 16 FDN decks from DraftZero's eval split as mirrors, visible lists, CC BY 4.0 attribution) and a first rated run with `uniform`, `first`, `heuristic` | blocked: X5 | X5, compute policy | 1 | ledger published; halt and truncation rates shown |
| X5b (#25) | Optional `probe_resample` | later | X5, P enabling the probe | 2 to 3 | "validator and probe" label |
| X6 (#26) | Manifests `fdn-limited-v1` (rotating pairs, hidden lists) and `standard-2022-25` (fixed-deck, 16 house decks, legality list) | blocked: P-v2.1 | X5, P-v2.1 | 1 to 2 | both validate against P's v2.1 schema |

## Agent kit track (A): XMage bots as fair v2 agents

| ID | Issue | Status | Depends | Est. | Done when |
|---|---|---|---|---:|---|
| A0 (#27) | Design the kit: v2 observation to XMage position (reuse DraftZero's MIT StateSpec rebuilder and mzbridge), determinization sampler consistent with `known` entries and the decklist rule in force, whole-action planning at a group's first substep, candidate mapping. Independent design review (fresh Sol session) before A1 | done (2026-10-01): revision 3 approved with changes by Sol (round 3); eight changes bound to the A1 slice | | 2 | design doc reviewed, dispositions recorded |
| A1 (#28) | Position rebuild and sampler (Java agent process speaking the v2 agent role) | blocked: A0, X3 | A0, X3 (observation shape) | 4 | rebuilt worlds match the engine's public state over 1,000 sampled decisions |
| A2 (#29) | Action to candidate mapping across group substeps | blocked: A1, X4 | A1, X4 | 3 | every decision answered with a valid candidate in a 1,000-game soak |
| A3 (#30) | Paired-world fairness tests for the kit (DraftZero's counterspell and cantrip positions) | blocked: A2 | A2 | 1.5 | identical answers across hidden worlds where they must be |
| A4 (#31) | Throughput: determinizations per decision vs clock profile; compute-policy qualification (serial vs parallel, Jack's PC, HaleysPC, RunPod) | blocked: A2 | A2 | 1 | time-control profile proposal for P |

## Heuristic bot track (H)

| ID | Issue | Status | Depends | Est. | Done when |
|---|---|---|---|---:|---|
| H1 (#32) | `xmage-rule`: XMage's rule-based `ComputerPlayer` through the kit (one world per decision; it is fair on a sampled world) | blocked: A2 | A2 | 1 | entry runs a full benchmark game set without violations |
| H2 (#33) | `xmage-mad`: the MAD minimax AI on K sampled worlds (fixes its own-draw leak by construction) | blocked: A2 | A2 | 1.5 | as H1, plus a K setting fixed per entry |
| H3 (#34) | `xmage-mcts`: XMage's MCTS on sampled worlds | blocked: A2 | A2 | 1.5 | as H1 |
| H4 (#35) | Rated runs of H1 to H3 on `fdn-mirror-v0`, later on M3's benchmarks | blocked: X5m, H1 | X5m, H1 to H3 | 1 | ratings on the site |

## RL bot track (R)

| ID | Issue | Status | Depends | Est. | Done when |
|---|---|---|---|---:|---|
| R0 | Outreach drafts for CABT, DraftZero and MageZero (brief 5.5, draft section 8), for Jack to send | drafted (2026-10-01): `x-outreach-drafts.md`, awaiting Jack | | 0.5 | drafts in `E:/spellbench-archive/program-research/`; Jack sends |
| R1 | Checkpoint handling: convert gzipped `torch.save` pickles to safetensors plus vocabulary JSON, inside the no-network container only | blocked: D-sandbox | D-sandbox, R0 answers | 1 | weights-only files with hashes |
| R2 | MageZero entry: their fork's `StateEncoder` and MCTS on the kit's sampled worlds, hidden-info key fixed, one entry per (deck, model) | blocked: A2, R1 | A2, R1, D-sandbox | 4 to 6 | entries pass A3's paired-world tests |
| R3 | DraftZero entry (ideally owned by DraftZero, their experiment 3): StateSpec rebuild plus K-determinized `coach` | blocked: A2, R1 | A2, R1, D-sandbox, R0 | 4 to 8 | as R2 |
| R4 | Policy-only fallback (`x_mz_features_v1` extension, Section 14 audit) if path B is too slow for time controls | later | X4, R1 | 4 to 6 | audited extension listed by a benchmark |
| R5 | Rated runs of MageZero (`standard-2022-25`) and DraftZero (`fdn-limited-v1`) | blocked: X6, R2, R3 | X6, R2, R3 | 1 | ratings on the site, labelled with fairness and sandbox status |

## External dependencies (other owners)

| ID | Owner | Need | Status 2026-09-30 |
|---|---|---|---|
| P-host | P (protocol-v2 branches) | host, live validator, builtins, goldens | exists on `protocol-v2` (P task 37) |
| P-v2.1 | P | deltas S1 to S10 of the design draft (rotating pairs, hidden lists, fixed-deck section 15, legality lists, time-control profiles, D6a to D6c rulings, Annex C corrections) | not started; requests and rulings filed with P as #40 (2026-10-01) |
| D-sandbox | D (join kit) | network-less Docker runner for JVM, GPU and pickle agents; stdio relay | not started |

## Decisions (Jack, 2026-09-30: "I'll take your recs for those")

- **Q1, push: yes.** The branch moves into the main spellbench repository (public; backed up by git_sync) and gets a PR into `board-program`. Work continues in a worktree of the main repository; the local clone `D:/spellbench-x/spellbench` is retired.
- **Q2, heuristic bots: agent kit only.** No engine-side "house pilots" that read the real game.
- **Q3, GitHub issues: yes, mirrored.** Issues for tracks X, A and H. The RL track gets one generic issue that names no RL project until R0's outreach has gone out. This file stays the detailed source; issues link here.

## Log

- 2026-10-01: X2 done on HaleysPC (Jack's PC reserved for the research lead's timing run until about 03:35 EDT). Engine declares `deck_sources: [catalog, decklist]` (P's conformance runner takes catalog decks only). Found and fixed: the repo `.gitignore` had silently dropped `patches/build/` (now `patches/build-only/`).
- 2026-10-01: A0 design drafted. Finding: at the pin, XMage's rule-based `ComputerPlayer` passes every priority and never attacks, so the H roster becomes MAD on 1 world (H1), MAD voting over K worlds (H2), MCTS (H3); pending the Sol review.
- 2026-10-01: X3 done (Opus agent, built on HaleysPC): P's validator V1, V2, V4 to V9 plus six invariants over 360 random games, zero failures; mutation test catches 8 of 8 injected faults. Six spec questions for P recorded in `tests/x3/README.md`.
- 2026-10-01: engine finding from the A0 work: `ComputerPlayer.playMana` orders mana producers with identity-hash ties (`MageObjectImpl`, `CardImpl`, `PermanentImpl` have no `hashCode`), and `engine_autopay` runs it, so X4e must rerun the X1 digest checks under autopay; a fix would be patch X-P4 (owned by X4h). X1's games used CABT's step-wise mana prompts and never exercised this path.
- 2026-10-01: A0 revisions 2 and 3 written; Sol round 2: BLOCK narrowed to 6 items; round 3: APPROVE WITH CHANGES (eight changes bound to the A1 vertical slice). A1 starts with the vertical slice, revised estimate 26 to 36 agent-days for tracks A and H before learned bots. Roster: kit-wrapped MAD on one world (H1), MAD K-world vote (H2), MCTS (H3); P's builtin heuristic is the cheap non-search baseline.
- 2026-10-01: A0 review (GPT-6.1 Sol, xhigh): BLOCK with 12 required changes (MCTS rollouts re-deal hidden cards; whole-resolution replay repeats effects; MAD is not deterministic; plan identities break across zone changes; percentage rebuild bars hide rare decisive errors). Revision 2 in progress; A1 waits for approval. Log: `E:/spellbench-archive/program-research/reviews/REVIEWS.md`.
- 2026-10-01: R0 outreach drafts written for Jack (`E:/spellbench-archive/program-research/x-outreach-drafts.md`).
- 2026-09-30: issues #13 to #36 opened; branch pushed, PR into `board-program`.
- 2026-09-30: X0 and X1 done (README evidence). Tracker created. Critical path to M2: X2, X3, X4, X5, X5m, plus A0 to A2 in parallel once X3 fixes the observation shape.
