# X5 evidence: conformance on P's host

Task X5 (issue #23): both benchmark pools in the engine catalog, at least 10,000 live-validated games through P's
host, paired-world leak tests, and the fairness label. P's stack is protocol-v2 `4b588a1` throughout. Progress
notes for the coordinator are in `STATUS.md`.

## Summary

| Check | Result |
|---|---|
| Catalog | 32 decks (16 Standard 2022-25, 16 FDN), all `deck_ok` in `validate_deck`, none left out |
| Live-validated games, final build | 10,112 games, 0 validator violations (`evidence/final-summary.json`) |
| Halts and truncations, final build | 0 halted, 0 truncated, 0 forfeits: all 10,112 natural (run 1 on the earlier build: 62 halts from two causes, fixed) |
| Determinism | rungs of 1, 12 and 24 workers identical; every tenth game (1,011) replayed under another identity-hash mode: 994 equal, 17 differ. Two causes, both fixed and verified on HaleysPC: process history (boot warm-up) and the identity-hash order of abilities granted by Agatha's Soul Cauldron (ability ordering in the mapper) |
| Paired-world leak tests, final build (`evidence/leak/`) | counterspell 50 pairs, cantrip 50 pairs and 200 randomized pairs PASS, 0 unexplained divergences; comparator self-tests PASS |
| Fairness label | "fairness: validator only" (`hello_ok.fairness.noninterference_probe` false; README) |

Engine changes X5 made, all found by these runs:

1. `ManaCostCache` (overlay): game digests depended on the games an engine process had played before (XMage's
   process-wide parsed-mana-cost cache mints object ids on a miss only).
2. X-P4 `0004-hash-order` (core patch): tokens created by one event entered in identity-hash order, so games with
   Reckoner Bankbuster were not reproducible run to run. `rules_snapshot_id` is now
   `xmage-fd40ad5c...-xpat-6f8a902bb6681c2fe4ec79823cf05d5cc46042b2298a33f5ea73e0bbc61a2822`; `card_pool_identity`
   is unchanged.
3. Mapper (overlay): dependent targets (Run Away Together) rewind instead of halting `dead_end:choose_target`;
   "any combination of colors" mana is a `choose_color` group; other multi-amount questions outside combat (Glissa
   Sunslayer removing counters) are a `choose_number` group. These were the only halt causes in run 1.
4. Catalog names: multi-face cards under their full Oracle names (spec 4.4).

## Pools (catalog)

`overlay/src/main/resources/mage/player/spellbench/catalog.json`, written by `make_catalog.py`:

| Pool | Format | Decks | Source, license |
|---|---|---:|---|
| Standard 2022-25 | `standard-2022-25-bo1` | 16 (Standard-Mono{B,G,R,U,W}, Standard16-{RG,UB,GB,RB,BW,UG,GW,UR,RW,UW,5C}) | MageZero's fork `cb7e9c6f`, `Mage.Tests/decks/`, MIT |
| FDN | `fdn-limited-bo1` | 16 (`FDN_top_*`, staged for `fdn-mirror-v0`) | 17lands FDN Premier Draft data, CC BY 4.0, via DraftZero `bf5750cf` (MIT) |

- Names are Oracle names in NFC. The `.dck` files name 15 multi-face cards (transforming double-faced cards and
  adventures, for example Questing Druid) by their front face; the catalog uses the full name "A // B" (spec 4.4),
  so X2's Standard16-RG changed in one row. Attribution is in `../../NOTICE`.
- `validate_decks.py` sends every deck as an inline decklist and by `catalog_id` through `validate_deck`: all
  `deck_ok`, and hello's catalog equals the file (`evidence/validate-decks.json`). No deck is left out.
- Deck sizes: 60 (MonoU 62); FDN 40 (WUR 49, BGpW 41).

## Fairness label

`hello_ok.fairness` is `{"noninterference_probe": false}` (checked by `validate_decks.py`) and the engine refuses
`rules.probe`. Without the probe or an audit the engine is **"fairness: validator only"** (spec 13 residual 2, 16):
P's live validator checks every decision, and the paired-world tests below stand in for an audit until X5b. The
engine README states the label.

## Determinism findings (spec 11.8)

- **Process history.** P's guard refused the first qualification: one game in 48 (a Standard game with a plotted
  card) had a different digest when its engine process had played other games first
  (`evidence/qualify-main-pc-refused-digest.log`). An id trace (`-Dspellbench.trace.ids`) found XMage's
  process-wide `ManaCostsImpl.costsCache`, which mints object ids on a miss and none on a hit;
  `PlotSpellAbility` parses a cost mid-game. `ManaCostCache` snapshots the cache after the boot warm-up and
  restores it before each game is built, so every game starts from a fresh process's state. Afterwards the game
  replayed after 43 others matched its fresh-process digest.
- **Identity-hash order.** A Standard16-RB game gave 4 different digests in 6 runs of the same process setup, with
  identical object-id draws. Its streams first differed in the battlefield order of a Treasure and a Pilot token
  that Reckoner Bankbuster creates together: `CreateTokenEvent` keeps its tokens in a `HashMap` keyed by token
  objects, which have identity hash codes. X-P4 makes that map, and `TokenImpl`'s set of created tokens,
  insertion-ordered; the game then gave 1 digest in 6 runs. X4h's hash audit had not met it (no deck there creates
  two kinds of token at once). The final run replays every tenth game under `-XX:hashCode=3` with a hash warm-up
  to look for more such paths.
- **Machines.** HaleysPC (JDK 23.0.2) reproduced Jack's PC's (JDK 23.0.1) digests on every game compared, and the
  final build's jars are byte-identical on both machines (`lib_digest` `c81b025a...`).

## Compute allocation (COMPUTE-POLICY.md)

The launch guard is P's `arena.qualification.plan_allocation`. `x5run.py qualify` feeds it a `play(workers,
games)` that plays the first 48 games of the interleaved schedule through P's host. `x5run.py` uses P's config,
schedule, secrets, `game_setup`, `host.game.play_game` (with the live validator) and ledger rows
(`runner._outcome`). It differs from P's `runner.play_one` only in keeping one engine process per worker; a JVM
start plus a 259 MB card-database copy per game would add 6 to 58 s to every 2 to 4 s game. P's CLI `spellbench run`
has no guard yet (its allocation is "unmeasured"), so this module is the guarded path. `run-final.sh` runs build,
`validate_deck`, guard, run, hash check and summary in one go.

Scaling on Jack's PC (24 hardware threads, 128 GB), final build, engines started before timing
(`evidence/allocation-final.json`; run 1's build gave 37.1, 125.7 and 121.7):

| Workers | Games | Wall s | Busy s (sum of game times) | Rate by busy time (games/min) |
|---:|---:|---:|---:|---:|
| 1 | 48 | 83.2 | 76.3 | 37.8 |
| 12 | 48 | 47.3 | 297.2 | **116.3** |
| 24 | 48 | 79.5 | 648.9 | 106.5 |

Guard verdict: `substantial`, 12 workers (the fastest rung by P's rule), outputs identical across rungs, projected
serial time 17,521 s. The parallel rungs' wall times are dominated by 12 or 24 concurrent engine starts (6 to 58 s
each, mean 36 s). The run itself then made 200.6 games per minute at 12 workers with the CPU at 70 to 88
percent; per-game time triples from 1 to 12 workers (each game is a JVM plus a Python host with its validator), so
24 workers gain nothing.

Placement (recorded in the allocation):

- **Jack's PC: used.** Released 07:10 EDT; reclaimed about 08:27 for the research lead's calibration, which stopped
  run 1 at 2,216 games; released again 10:06 for the final run.
- **HaleysPC: unavailable.** P's guard refused it before its first game: its only volume (C:) has 54.6 GiB free,
  below the 60 GiB reserve of ARTIFACT-LAW.md clause 1 (`evidence/qualify-haleyspc-refused-reserve.log`); the
  coordinator kept the reserve (no exception). It ran only small correctness checks (leak tests, fix replays, a
  build) and was then reserved for another session's timing. X4 measured 40 to 56 games per minute there in 12
  processes, a quarter of Jack's PC.
- **RunPod: slower.** At Jack's PC's measured rate the whole schedule takes about 49 minutes. A CPU pod would first
  need a JDK 23 image, Maven Central downloads, the 2.5 to 4 minute build, the card-database scan and P's stack
  before its first game, and a pod as fast as a 24-thread desktop just to tie; no spending authority covers it.

Lever noted, not taken: P's preflight starts one engine per deck pairing in sequence (16 per pool, about 2 minutes
per invocation, CPU mostly idle); caching the preflight's `RunSetup` between the guard and the run would save one
of those.

## Run 1 (interrupted): 2,216 games

Build `d2563f73` (before the halt fixes and X-P4), 12 workers, 08:15 to 08:27 EDT, stopped when Jack's PC was
reclaimed. Every game live-validated. `evidence/run1-summary.json`, digests in `evidence/run1-digests.tsv`.

| Pool | Games | Natural | Halted | Truncated | Validator violations |
|---|---:|---:|---:|---:|---:|
| FDN | 1,109 | 1,069 | 40 (3.6%) | 0 | 0 |
| Standard | 1,107 | 1,085 | 22 (2.0%) | 0 | 0 |

Halt causes (spec 11.5 attribution: `last_selection` names the entry whose selection preceded the halt):

- FDN, all 40: `engine_contract_failure:dead_end:choose_target`, all in `FDN_top_21511_WUR`, caused by Run Away
  Together ("two target creatures controlled by different players"): with every creature on one side XMage still
  lets it be cast, the mapper offered a first target, and no second one was left. Preceded by `uniform` (35) and
  `heuristic` (5) selections, the entry that cast it.
- Standard, all 22: `engine_contract_failure:unsupported:multi_amount`: 21 in `Standard16-RB` (Chandra, Hope's
  Beacon's +2, "two mana in any combination of colors") and 1 in `Standard16-GB` (Glissa Sunslayer removing
  counters from Liliana of the Veil). Preceded by `uniform` (16), `first` (5) and `heuristic` (1).

All 62 end naturally on the fixed builds (`evidence/fixcheck.jsonl` and the Glissa replay).

## Final run: 10,112 games

Build `c81b025a` (commit `a4a9eda`: catalog with full names, `ManaCostCache`, X-P4, the three mapper fixes), Jack's
PC, 12 workers chosen by P's guard, 10:14 to 11:07 EDT: 10,112 games in 3,024 s, **200.6 games per minute**. Every
decision was checked by P's live validator: 5,982,064 decisions, **0 violations**. Summary
`evidence/final-summary.json`; every game's ending and digest in `evidence/final-games.tsv.gz`.

| Pool | Games | Natural | Halted | Truncated | Violations | Steps per game (mean, median, max) | Groups per game (mean) | s per game per worker (mean, max) |
|---|---:|---:|---:|---:|---:|---|---:|---|
| FDN | 5,056 | 5,056 | 0 | 0 | 0 | 592, 541, 1,907 | 570 | 3.1, 29 |
| Standard | 5,056 | 5,056 | 0 | 0 | 0 | 591, 501, 5,418 | 558 | 4.0, 107 |

Endings: FDN 4,877 by life (2,607 p0, 2,270 p1), 178 by an empty library, 1 draw (both lost); Standard 4,907 by
life, 127 by an empty library, 22 by poison. Halt and truncation rate 0 for every pool, matchup and entry, so the
Section 11.5 attribution table is empty.

| Workload (per pool) | Games | FDN result | Standard result |
|---|---:|---|---|
| `uniform` mirror | 2,432 | p0 won 1,173, p1 1,258, 1 draw | p0 1,206, p1 1,226 |
| `heuristic` against `uniform` | 2,240 | `heuristic` won 1,695 (75.7%) | `heuristic` won 1,520 (67.9%) |
| `first` against `uniform` | 384 | `first` won 6 | `first` won 36 |

Decision kinds posed (both pools): priority 5,297,957; declare_attack 220,062; choose_target 124,504;
select_object 77,866; declare_block 73,741; order_pick 36,575; choose_cost_target 36,527; mulligan 35,068;
distribute 17,295; arrange_card 17,285; optional_cost 15,118; choose_boolean 14,741; choose_spell_mode 8,307;
choose_number 3,712; choose_color 1,494; choose_option 851; choose_name 678; choose_cast_method 229;
choose_replacement 45; choose_pile 9. Notable counters: 68,000 rewinds (10,725 FDN, 57,251 Standard; 3,209 of
FDN's are Run Away Together cancelled at its first target; the rest are payments and costs that failed after
the action was chosen, as in X4), 4 `choose_number` groups for counters, and 21 tries in one game that
hit the completion budget (all candidates kept, no halt). Engine autopay inside payments still uses
`ComputerPlayer`'s logic for target and multi-amount questions 5,125 times (X4c listed these as never reached).

### Determinism of the final run

- P's guard: the 48 qualification games had equal outputs at 1, 12 and 24 workers.
- Hash perturbation (`evidence/hash-determinism.json`): every tenth game (1,011) again in fresh worker processes
  under `-XX:hashCode=3` and a hash warm-up: **994 equal, 17 differ**, all `heuristic` against `uniform` in
  Standard16-UG (7), Standard16-RW (6) and Standard-MonoW (4).
- Cause, found for game 2540 by an id trace: it is not the hash mode but process history. The replay alone gives
  the perturbed run's digest under either hash mode; replayed after the 50 games its worker had played before it,
  it gives the main run's digest. The traces first differ where engine autopay's object choice (`PayChoice`, which
  ranks with XMage's `ArtificialScoringSystem`) initializes the AI class `MagicAbility`, whose static initializer
  mints ids. X1's boot warm-up initializes only the framework jar's classes, so in each process the first game to
  reach that path drew those ids from its own stream.
- Fix: the boot warm-up also initializes every class under `mage/player/ai/` (`Warmup`), so no game draws those
  ids. Verified on HaleysPC (build `e8e5a42b`, commit `b5ce052`, below-normal priority; `evidence/warmup-verify.json`
  and `.tsv`), each set played under the default identity hash and under `-XX:hashCode=3` with a hash warm-up, in
  different process layouts:

  | Set | Games | Equal across hash modes | Equal to the main run |
  |---|---:|---:|---:|
  | the 17 divergent games: Standard16-RW, Standard-MonoW | 10 | 10 | 10 |
  | the 17 divergent games: Standard16-UG | 7 | 2 | 2 |
  | 200 more: `heuristic` against `uniform` in Standard16-RW, -MonoW, -UG | 46, 44, 47 | 46, 44, 31 | 46, 43, 31 |
  | 200 more: 80 games of the other cells | 80 | 80 | 80 |

  0 violations, all natural. Outside Standard16-UG the 169 games of the check are reproducible across hash modes
  and process layouts. 168 of them equal the main run; the other (a Standard-MonoW game) was, as expected, a
  game that reached the AI class first in its main-run process.
- **Second cause: Standard16-UG, fixed.** 16 of 47 UG games still changed with the identity-hash mode in one
  process layout. In game 4187 the streams first differ in a priority decision's `activate_ability.ability_index`
  (0 against 1) for Sentinel of the Nameless City, which carries the activated abilities Agatha's Soul Cauldron
  grants (those of the creature cards it exiled). The Cauldron's effect collects them with
  `Collectors.toSet()`, a hash set of abilities, and XMage lists granted abilities in the order effects add
  them. Six more Mage.Sets cards grant abilities from a `Set<Ability>` (Hazel's Brewmaster, Idris, Mirran
  Safehouse, Necrotic Ooze, Thranduil, Trazyn); none is in the catalog, and Mage core has no such set.
- Fix (overlay, commit `4125a61`): one ordering, `SeatPlayer.orderedAbilities`, now feeds every `ability_index`,
  for activated abilities (`activate_ability`) and triggered ones (`order_pick` trigger items) alike. Printed
  abilities come first in XMage's order: the card's, both faces', the token's, or, for a copy, the copied object's.
  Granted ones follow, ordered by rule text (code point order) and then the original ability's id. The id only
  orders abilities with identical text, so it tells the seat nothing. XMage does not record which effect granted
  an ability, so the granting card's name cannot be a key. The observation carries no `ability_index`, and every
  candidate takes it from that one ordering (Section 5.1). Verified on HaleysPC (`d74803d5`, commit `213d95a`;
  `evidence/ability-order-verify.json`, `.tsv`), each game under both hash modes in different process layouts:

  | Set | Games | Equal across hash modes | Equal to the previous build | Equal to the main run |
  |---|---:|---:|---:|---:|
  | Standard16-UG, `heuristic` against `uniform` (all 47 of the check) | 47 | 47 | 32 | 30 |
  | Standard16-UG, `uniform` mirror | 1 | 1 | 0 | 0 |
  | Standard16-RW, Standard-MonoW | 20 | 20 | 20 | 19 |
  | 30 games of other cells (both pools) | 30 | 30 | 30 | 30 |

  0 violations, all natural. The UG games whose digest changed are the ones whose granted abilities now sort
  differently; the MonoW game is the first-in-process game described above.
- So the run's outcomes and validator verdict stand. On the current build every game checked is reproducible
  across hash modes and process layouts. Main-run digests are stale for games that reach a granted-ability
  ordering or that first loaded an AI class in their process; the full 1,011-game recheck (Jack's PC) will
  measure how many.

## Paired-world leak tests (spec 13 F1, F3; design draft section 6)

`leak.py`. One game secret, two hidden worlds: world B runs the same game with
`-Dspellbench.test.worldSalt=SEAT:B`, a test hook in `rng.GameRandom` (a no-op unless set) that reseeds only that
seat's streams (its library order, so its opening hand and draws, and its random cards). Shared streams and object
ids are untouched and both bots get the same seeds. The other seat, the observer, must then receive a byte-identical
`seat_decision` stream after canonicalization (canonical JSON, object ids renamed by first appearance, since a
different physical Island gets a different pseudorandom id) until the public state diverges. At the first
difference the pair is classified:

| Class | Meaning |
|---|---|
| `public` | the public observation differs (everything but the observer's own hand and `known`): ends the window |
| `own_hand` | only the observer's own hand differs (possible only when the observer is the salted seat) |
| `own_look` | only `known` entries of the observer's own library differ (its own scry or draw look) |
| `own_effect_look` | only `known` entries of the other hand differ, shown while the observer's own spell resolves (Duress) |
| `UNEXPLAINED` | anything else: a leak, and the test fails |

`leak.py --selftest` injects five leaks into a recorded pair at the observer's first decision with a choice (a
`known` entry of the other hand, reversed candidates, a dropped candidate, a revealing `display_text`, a context
text): each must be classified `UNEXPLAINED`.

| Position | Design | Pairs kept (played) | Result |
|---|---|---:|---|
| counterspell | observer p0 `uniform` (Standard16-RG, on the play) against p1 (36 Island, 4 Counterspell; scripted: keeps, plays an Island whenever it can, never casts); salt p1; keep pairs whose p1 opening hand has a Counterspell in world A and none in world B | 50 (179) | p0's whole stream identical in all 50 games (11,178 decisions), 1,001 of them taken while p0's own spell was on the stack and p1 held Counterspell over two untapped Islands. PASS |
| cantrip | p0 (20 Island, 20 Opt; scripted: keeps, plays a land, casts Opt, scry to the top) against observer p1 (`uniform`, Standard-MonoU); salt p0; keep pairs whose p0 opening hands have the same names | 50 (248) | p1: identical until a public divergence in all 50 (median 62 decisions, turn 7), while p0 had already seen different library cards (median turn 2): p0's first divergence was `own_look` 40 times and `own_hand` 10 times. PASS |
| randomized | all 32 catalog decks as mirrors, `uniform` both seats, the salted seat alternating, observer the other seat | 200 (200) | 198 `public`, 2 `own_effect_look` (both Duress cast by the observer, checked by hand: 7 revealed hand cards), 0 unexplained; windows are short (median 11 decisions). PASS |
| self-test | five injected leaks per recorded pair (counterspell p0, randomized p1) | 2 | all five classified `UNEXPLAINED` in both. PASS |

Limits: a leak that only appears after the public state has diverged is out of each window; `own_effect_look`
accepts any difference in the other hand's `known` entries during the observer's own resolving spell; the
randomized windows are short (the salted seat's different hand soon changes its public plays).

Earlier pass on HaleysPC (build before X-P4 and the Glissa fix): counterspell 50 pairs, every one identical for
the whole game, with 1,001 p0 decisions taken while its own spell was on the stack and p1 held Counterspell over
two untapped Islands; cantrip 50 pairs, p1 identical until a public divergence (median 62 decisions, turn 7) while
p0 had already seen different library cards (median turn 2) in all 50; randomized 200 pairs flagged 2, both
Duress (`own_effect_look` did not exist yet).

## Questions for P

1. Decklists name multi-face cards "A // B" (spec 4.4). Should P's hello parser or `validate_deck` reject a
   front-face-only name for such a card? X2's catalog had one, and nothing caught it.
2. "Add N mana in any combination of colors" resolving outside a payment: posed as N `choose_color` (purpose
   `mana`) in non-decreasing WUBRG order. Is a `distribute` with purpose `mana` over colors intended instead?
   Its `recipient` must be a target reference, which a color is not.
3. A multi-amount question over labelled lines (counter kinds to remove) has no v2.0 kind that names the line:
   posed as a `choose_number` group in code point order of the lines. Should v2.1 add a label field?
4. Run Away Together-like targets: a spell whose targets cannot be completed is cancelled at its first target and
   the priority decision re-posed with `rewind`, although the seat never saw a target decision. Is that the
   intended use of rewind, or should the engine keep such a spell off the priority list (it would need XMage's
   target legality for complete sets)?
5. `spellbench run` has no launch guard yet; X5 used `plan_allocation` directly with an engine-per-worker
   executor. Should the arena executor offer engine reuse across games (an engine process plays games in
   sequence, restarted after a host halt) as a supported mode?
6. The X4b goldens embed `hello_ok` (catalog and identity strings), so any catalog change or core patch invalidates
   them; X5 regenerated them. Should goldens leave the catalog out of the comparison?

## Commands

```bash
python tests/x5/make_catalog.py --magezero D:/community/mage-magezero --fdn .../x5m/fdn-mirror-v0-catalog.json
PYTHONPATH=<p2>/python python tests/x5/validate_decks.py --expect-catalog -- scripts/engine.sh --build B --db DB
tests/x5/run-final.sh --machine main-pc --scratch S --xmage-repo X --m2 M2 --p2 P2 --cap 24 --placement TEXT
PYTHONPATH=<p2>/python python tests/x5/leak.py --position counterspell|cantrip|random --pairs N --workers W --out D -- ENGINE...
PYTHONPATH=<p2>/python python tests/x5/leak.py --selftest D/<position>-first-pair-streams.json SEAT
```

`plan.json` holds the master secret and the six workloads (pairs per matchup per pool: 1,216 `uniform` mirror,
1,120 `heuristic` against `uniform`, 192 `first` against `uniform`; 10,112 games). It is a conformance run, not a
rated one, so its secret is published here. Diagnostics: `seq.py` (games in one process, with engine stderr),
`lastdec.py` (the last decisions before an ending), `streams.py` (both seats' streams of one game).
