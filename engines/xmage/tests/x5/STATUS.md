# X5 status (for the coordinator)

## 2026-10-02: work moves to main (branch `xmage-m1`)

- Main's reviewed build of `004913a` (lib `094733a7`) is the engine; its X5 (10,112 games, 0 violations, 1,011/1,011
  replays) is in `docs/llm-engine-verification-20261002.json`. The `d74803d5` run below is superseded history
  (`evidence/superseded-d74803d5/`).
- Ready, not run: `run-23-checks.sh` (leak tests and X4b goldens on `004913a`) and `../x5m/run_rated.sh`.
  Everything below this section is history from branch `xmage-x0-x1`.

## 18:50 EDT: standing by

- The writer on HaleysPC was a Codex cloud task building mtg-kernel FDN fixture tests into
  `C:/Users/haley/mtg-kernel-fdn-batch-b-target` and `mtg-kernel-fdn-target` (coordinator); not ours, untouched.
- Waiting for "X5 resume" naming the machine. On resume, `x5run.py run` with the same machine label skips the 3,544
  recorded games and plays the other 6,568, then the 1,011-game hash recheck and the summary. On Jack's PC, the
  rows from HaleysPC are copied over first so the plan's game split is unchanged, and the guard re-qualifies there.

## 18:40 EDT: HaleysPC run stopped at the reserve (3,544 of 10,112 games)

- **Stopped by me at 18:20** when C: free fell to 60.5 GiB, so the volume stays above the 60 GiB reserve. My run's
  own footprint never grew (1.55 GB of engine scratch, 8 MB of rows). C: kept falling after the stop with nothing of
  mine running: 62.06 GiB right after freeing my scratch, 61.05 at 18:24, 60.46 at 18:35. Something else on
  HaleysPC writes about 1 GiB per 10 minutes (I could not identify it; Windows Search and system writes lead the
  write counters). Resuming needs about 1.6 GB of engine scratch, which would cross the reserve, so I have not
  resumed.
- **Recorded so far (build `d74803d5`, all fixes, P's guard: 6 workers; `evidence/allocation-haleyspc.json`):**
  3,544 games (1,772 per pool), 66 games/min, all natural, **0 validator violations** over 2,030,290 decisions,
  0 halts, 0 truncations (`evidence/haleyspc-partial-summary.json`). Rows stay on HaleysPC in
  `~/x-spike/x5/final/run/`; `x5run.py run` resumes and skips them.
- Against Jack's PC's run (build `c81b025a`, before the warm-up and ability-order fixes): all 1,772 FDN games have
  identical digests on both machines and builds; 1,617 of 1,772 Standard games do. The 155 that changed are in
  decks with granted abilities or the AI-class path (UW 70, UG 38, RB 13, MonoB 9, BW 9, MonoW 8, RW 5, RG 3), as
  the two fixes intend.
- **Needed to finish:** about 2 GiB of headroom on HaleysPC's C: above the reserve (or the external writer stopped),
  or Jack's PC (about 35 min for the remaining 6,568 games at 200/min, plus the 1,011-game hash recheck). The hash
  recheck has not run.

## 18:20 EDT: disk note

- 3,025 of 10,112 games at 66 games/min, 0 violations, 0 halts; ETA for the run about 20:00 EDT.
- HaleysPC C: free fell from 69.5 GiB at launch to 62.9 GiB. My run's footprint is constant: 1.55 GB of engine
  scratch (6 card-database copies) and 8 MB of rows. Something else on the machine is writing; I could not pin it
  down quickly (no growth in `~/x-spike/x5`, Temp or the dated `C:\mtg-*` folders). A monitor stops my waiting at
  61 GiB; if C: nears 60 GiB I will stop the run (resumable: finished rows are kept) and report.

## 17:35 EDT: final run on HaleysPC in progress

- Reserve re-checked before start: C: 69.5 GiB free (guard's facts: 73.8 GB at qualification, 71.5 GB during the
  run with 6 engine copies). Build `d74803d5` (commit `71e32fc`), byte-identical to the verified ability-order
  build. All 32 decks `deck_ok`.
- P's guard on HaleysPC (ladder 1, 6, 12; 24 games per rung): busy-time rates 17.9, 49.0 and 46.8 games/min,
  outputs identical; verdict `substantial`, 6 workers. Running at 63 games/min, CPU 61 to 67 percent (16 logical
  on 8 cores), 0 violations and 0 halts in the first 350 games. ETA for the 10,112 games about 20:05 EDT, then the
  1,011-game hash recheck (about 16 min), so about 20:25.

## 13:00 EDT: ability-order fix verified on HaleysPC

- Implemented as decided (overlay, commit `4125a61`). A single ordering, `SeatPlayer.orderedAbilities`, now feeds
  every `ability_index`: activated abilities and trigger items. The object's own abilities (both faces, the token's,
  or the copied object's for a copy) keep XMage's order; granted ones follow, ordered by rule text, then the
  original ability id (which only orders identical text). The observation has no `ability_index`, so candidates
  and observation cannot disagree. XMage does not record which effect granted an ability, so the granting card's
  name could not be a key.
- Same pattern elsewhere: six more cards grant abilities from a `Set<Ability>` (Hazel's Brewmaster, Idris, Mirran
  Safehouse, Necrotic Ooze, Thranduil, Trazyn), none in the catalog; the fix covers them anyway. Mage core has none.
- Verified on HaleysPC at below-normal priority (`d74803d5`, commit `213d95a`): all 47 Standard16-UG
  `heuristic`-vs-`uniform` games of the earlier check plus 51 others (1 UG mirror, 20 RW and MonoW, 30 other cells,
  both pools), each under both hash modes with 3 and 2 workers: **98 of 98 equal across modes**, 0 violations, all
  natural. 16 UG digests changed from the previous build (their granted abilities now sort differently), and the
  other 50 games are unchanged (`evidence/ability-order-verify.json`).
- HaleysPC: builds and sources deleted again; `~/x-spike/x5` holds 2 MB of rows and summaries. Nothing of mine
  runs there. The full 1,011-game recheck waits for Jack's PC.

## 12:35 EDT: warm-up fix verified on HaleysPC

- Rebuilt on HaleysPC at below-normal priority (`lib_digest e8e5a42b`, commit `b5ce052`), stayed out of
  `x-spike/kit`. Small check only: 17 + 217 games, each under the default identity hash and `-XX:hashCode=3`,
  in different process layouts. 0 violations, all natural (`evidence/warmup-verify.json`).
- **Warm-up fix works.** All 10 divergent games of Standard16-RW and -MonoW now give one digest in both modes, equal
  to the main run. The check's 169 games outside Standard16-UG (46 RW, 44 MonoW, 80 other cells) are all equal
  across modes; 168 equal the main run, and the remaining one was a first-in-process game in the main run.
- **Second cause, open (Standard16-UG only):** 16 of 47 UG `heuristic`-vs-`uniform` games (and 5 of its 7
  divergent ones) still change with the hash mode. Traced in game 4187 to `ability_index` of abilities that
  Agatha's Soul Cauldron grants to Sentinel of the Nameless City: their order follows identity hash codes.
  Proposed mapper fix (visible ordering of granted abilities) in `README.md`; not implemented. UG plays 316 of the
  10,112 games.
- HaleysPC `~/x-spike/x5` pruned to 1.4 MB (rows, comparisons, leak summaries); builds and sources removed.
  Nothing of mine is running there. The full 1,011-game recheck waits for Jack's PC.

## 11:50 EDT: final

- **Jack's PC is clear.** No java, javac, maven or engine process of mine remains (checked); engine work
  directories removed; scratch `D:/e-scratch/xmage-x-spike` pruned to 0.8 GiB (cap 6 GiB). WSL distributions
  "Ubuntu" and "docker-desktop" are running, but I did not start them (none ran at 07:10 or 08:28; I never ran a
  WSL command other than listing), so I left them alone.
- **HaleysPC:** idle on my side since 10:05. Leftover scratch there: `~/x-spike/x5` (builds, about 1.2 GiB).
- **Final run** (Jack's PC, P's guard chose 12 workers): 10,112 games in 50 min (200.6 per minute), all natural,
  **0 validator violations** over 5,982,064 decisions, 0 halts, 0 truncations. Leak suite on the final build:
  counterspell 50, cantrip 50, randomized 200 pairs, all PASS. X4b goldens regenerated (5 of 5 PASS).
- **Open (needs HaleysPC or Jack's PC later):** every tenth game replayed under another identity-hash mode: 994 of
  1,011 equal, 17 differ. Traced: process history, not hashing. XMage's AI class `MagicAbility` mints ids in its
  static initializer, which first runs mid-game when engine autopay ranks objects. The fix (boot warm-up also
  initializes `mage/player/ai/`, `Warmup.java`) is committed but not built or verified: rebuild, replay the
  affected games (Standard16-UG, -RW, -MonoW, `heuristic` against `uniform`), rerun the hash check.
- Details, numbers and questions for P: `README.md`.
