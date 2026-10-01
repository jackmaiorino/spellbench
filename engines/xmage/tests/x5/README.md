# X5 evidence: conformance on P's host

Task X5 (issue #23): both benchmark pools in the engine catalog, at least 10,000 live-validated games through P's
host, paired-world leak tests, and the fairness label. P's stack is protocol-v2 `4b588a1` throughout.

Status: see `STATUS.md` (the 10,112-game run was stopped at 2,216 games when Jack's PC was reclaimed; it reruns in
full on the final build once Jack's PC is released).

## Pools (catalog)

`overlay/src/main/resources/mage/player/spellbench/catalog.json`, written by `make_catalog.py`:

| Pool | Format | Decks | Source, license |
|---|---|---:|---|
| Standard 2022-25 | `standard-2022-25-bo1` | 16 (Standard-Mono{B,G,R,U,W}, Standard16-{RG,UB,GB,RB,BW,UG,GW,UR,RW,UW,5C}) | MageZero's fork `cb7e9c6f`, `Mage.Tests/decks/`, MIT |
| FDN | `fdn-limited-bo1` | 16 (`FDN_top_*`, staged for `fdn-mirror-v0`) | 17lands FDN Premier Draft data, CC BY 4.0, via DraftZero `bf5750cf` (MIT) |

- Names are Oracle names in NFC. The `.dck` files name 15 multi-face cards (transforming double-faced cards and
  adventures, for example Questing Druid) by their front face; the catalog uses the full name "A // B" (spec 4.4),
  so X2's Standard16-RG changed in one row. Attribution is in `../../NOTICE`.
- `validate_decks.py`: every deck as an inline decklist and by `catalog_id`, through `validate_deck`, plus the
  15 full names on their own: all `deck_ok`; hello's catalog equals the file (`evidence/validate-decks.json`).
  No deck is left out.
- Deck sizes: 60 (MonoU 62); FDN 40 (WUR 49, BGpW 41).

## Fairness label

`hello_ok.fairness` is `{"noninterference_probe": false}` (checked by `validate_decks.py`) and the engine refuses
`rules.probe`. Without the probe or an audit, the engine is **"fairness: validator only"** (spec 13 residual 2,
16): the live validator checks every decision, and the paired-world tests below are the audit substitute until
X5b. The engine README says so.

## Determinism finding (spec 11.8), fixed

P's guard refused the first qualification: one game of 48 (a Standard game with a plotted card) had a different
digest when its engine process had played other games first (`evidence/qualify-main-pc-refused-digest.log`). An
id trace (`-Dspellbench.trace.ids`) showed the cause: XMage's process-wide cache of parsed mana costs
(`ManaCostsImpl.costsCache`) mints object ids on a miss and none on a hit, and `PlotSpellAbility` parses a cost
mid-game. X4 had met the same cache through the mapper's own parsing.
`ManaCostCache` (overlay) snapshots the cache after the boot warm-up and restores it before each game is built, so
every game starts from a fresh process's state: a fresh process's games keep their digests, and no game depends
on its predecessors. After the fix the 48 qualification games had equal digests at 1, 12 and 24 workers, the game
replayed after 43 others matches its fresh-process digest, and HaleysPC (JDK 23.0.2) reproduces the digests of
Jack's PC (JDK 23.0.1) on every game compared.

## Compute allocation (COMPUTE-POLICY.md)

The launch guard is P's `arena.qualification.plan_allocation`: `x5run.py qualify` feeds it a `play(workers, games)`
that plays the sampled games of the real schedule (the first 48 of the interleaved order) through P's host.
`x5run.py` uses P's config, schedule, secrets, `game_setup`, `host.game.play_game` (live validator) and ledger
rows (`runner._outcome`); it differs from P's `runner.play_one` only in keeping one engine process per worker
(an engine start plus a 259 MB card-database copy per game would add 6 to 58 s per game). P's CLI `spellbench run`
has no guard yet (its allocation is "unmeasured"), so this module is the guarded path.

Scaling on Jack's PC (24 hardware threads, 128 GB), final build of 08:09, engines prewarmed per worker
(`evidence/allocation-main-pc.json`):

| Workers | Games | Wall s | Busy s (sum of game times) | Rate by busy time (games/min) |
|---:|---:|---:|---:|---:|
| 1 | 48 | 84.4 | 77.6 | 37.1 |
| 12 | 48 | 44.7 | 274.9 | **125.7** |
| 24 | 48 | 73.3 | 568.0 | 121.7 |

Guard verdict: `substantial`, 12 workers (the fastest rung by P's rule), outputs identical across rungs, projected
serial time 17,789 s. Wall times of the parallel rungs are dominated by 12 or 24 concurrent engine starts
(6 to 58 s each, mean 36 s); the run itself then made 206 to 215 games per minute at 12 workers with the CPU at
80 to 88 percent.

Placement (recorded in the allocation):

- **Jack's PC: used.** Released by the coordinator at 07:10 EDT; reclaimed at about 08:27 for the research lead's
  calibration, which stopped the run at 2,216 games (their rows and digests are kept). Off-limits until the
  coordinator's next "Jack's PC go".
- **HaleysPC: unavailable.** P's guard refused it before its first game: its only volume (C:) has 54.6 GiB free,
  below the 60 GiB reserve of ARTIFACT-LAW.md clause 1 (`evidence/qualify-haleyspc-refused-reserve.log`). It runs
  only small correctness checks here (leak tests, fix replays). Its throughput was therefore not measured; X4 saw
  40 to 56 games per minute there in 12 processes, a quarter of Jack's PC.
- **RunPod: slower.** At Jack's PC's measured 206 games per minute the whole schedule takes about 49 minutes. A
  CPU pod would first need a JDK 23 image, Maven Central downloads and the 2.5 to 4 minute build, plus the 18 s
  card-database scan and P's stack, before its first game, and would need a pod as fast as a 24-thread desktop
  just to tie. No spending authority covers it, and it cannot finish sooner than Jack's PC once released.

## Run 1 (interrupted): 2,216 games on Jack's PC

Build `d2563f73` (catalog with full names, cache fix), 12 workers, 08:15 to 08:27 EDT. Every game live-validated.
`evidence/run1-summary.json`, digests in `evidence/run1-digests.tsv`.

| Pool | Games | Natural | Halted | Truncated | Validator violations | Steps per game (mean, median, max) | s per game per worker |
|---|---:|---:|---:|---:|---:|---|---:|
| FDN | 1,109 | 1,069 | 40 (3.6%) | 0 | 0 | 538, 491, 1,441 | 3.0 |
| Standard | 1,107 | 1,085 | 22 (2.0%) | 0 | 0 | 563, 482, 4,314 | 4.0 |

Halt causes (spec 11.5 attribution: `last_selection` is the entry whose selection preceded the halt):

- FDN, all 40: `engine_contract_failure:dead_end:choose_target`, every one in deck `FDN_top_21511_WUR` and caused by
  Run Away Together ("choose two target creatures controlled by different players"). With every creature on one
  side, XMage still lets it be cast (it counts two legal creatures), the mapper offered a first target, and no
  second target was left. Preceded by `uniform` (35) and `heuristic` (5) selections: the spell is cast by the
  seat that acts last, so the attribution points at the casting entry, not at a fault of it.
- Standard, all 22: `engine_contract_failure:unsupported:multi_amount`, every one in deck `Standard16-RB`: Chandra,
  Hope's Beacon's +2 ("add two mana in any combination of colors") asks XMage's multi-amount question outside
  combat, which stage 1 did not map. Preceded by `uniform` (16), `first` (5) and `heuristic` (1).

Fixes (overlay only, commit `fa4d30c`; identity strings unchanged):

1. Fixed-count and minimum-count target selections offer only candidates after which the rest of the group can
   still be chosen (Section 7.1), tried on copies of the target with XMage's event-free `Target.add` (3,000 tries
   per question, then every candidate is kept and counted). When no complete set exists at the first target of a
   targeted choice, the choice fails, XMage rolls the cast back, and the seat's priority decision is re-posed with
   `rewind` (Section 8), as for any failed activation.
2. "Any combination of colors" (`MultiAmountType.MANA`) is one group of N `choose_color` decisions with purpose
   `mana`, colors in WUBRG order and never below the previous pick (one spelling per combination).

On the fixed build all 62 halted games end naturally (`evidence/fixcheck.jsonl`), and the first 60 games of the
schedule keep their run-1 digests.

## Paired-world leak tests (spec 13 F1, F3; design draft section 6)

`leak.py`. One game secret, two hidden worlds: world B runs the same game with
`-Dspellbench.test.worldSalt=SEAT:B`, a test hook in `rng.GameRandom` (a no-op unless set) that reseeds only that
seat's streams (library order, so its opening hand and draws, and its random cards). Shared streams and object ids
are untouched and both bots get the same seeds. The other seat (the observer) must then receive a byte-identical
`seat_decision` stream after canonicalization (canonical JSON, object ids renamed by first appearance, since a
different physical Island gets a different pseudorandom id) until the public state diverges. At the first
difference the pair is classified: `public` (public observation differs; ends the window), `own_hand`, `own_look`
(the observer's own library cards in `known`, after its own scry), or `UNEXPLAINED` (a leak; the test fails).
`leak.py --selftest` injects five leaks into a recorded pair (a `known` entry of the other hand, a reordered or a
dropped candidate, a revealing `display_text`, a context text): each must be classified `UNEXPLAINED`.

Results: pending (running on HaleysPC; see `STATUS.md`).

## Commands

```bash
python tests/x5/make_catalog.py --magezero D:/community/mage-magezero --fdn .../x5m/fdn-mirror-v0-catalog.json
PYTHONPATH=<p2>/python python tests/x5/validate_decks.py --expect-catalog -- scripts/engine.sh --build B --db DB
tests/x5/run-final.sh --machine main-pc --scratch S --xmage-repo X --m2 M2 --p2 P2 --cap 24 --placement TEXT
PYTHONPATH=<p2>/python python tests/x5/leak.py --position counterspell|cantrip|random --pairs N --out D -- ENGINE...
```

`plan.json` holds the master secret and the six workloads (pairs per matchup: 1,216 `uniform` mirror, 1,120
`heuristic` against `uniform`, 192 `first` against `uniform`, per pool; 10,112 games). This is a conformance run,
not a rated one, so its secret is published here.
