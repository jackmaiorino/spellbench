# X4 stage 2 evidence: arrangements, callbacks, combat, hash order

Task X4 stage 2 (issues #18 X4b, #19 X4c, #20 X4d, #22 X4h). Stage 1 is `tests/x4/README.md` (mapping table,
counters, interpretations); this file adds to it. Code: `overlay/.../decide/CombatOracle.java` (X4d),
`CallbackAudit.java` and `PayChoice.java` (X4c, X4h), and changes in `SeatPlayer.java`, `Exchange.java`,
`observe/ObservationBuilder.java` and `observe/ViewerIds.java`. No core patch was added: `rules_snapshot_id` and
`card_pool_identity` are unchanged from X1 and stage 1 (`xmage-fd40ad5c...-xpat-8c2578be...`).

## Commands

All on HaleysPC at below-normal priority, P's stack at protocol-v2 `4b588a1`, the card database template
`~/x-spike/db`:

```bash
tests/x4s2/run-evidence.sh --build B --db DB --p2 P2 --work W --section audit     # X4c
tests/x4s2/run-evidence.sh --build B --db DB --p2 P2 --work W --section goldens   # X4b (GOLDENS_GENERATE=1 regenerates)
tests/x4s2/run-evidence.sh --build B --db DB --p2 P2 --work W --section combat    # X4d
tests/x4s2/run-evidence.sh --build B --db DB --p2 P2 --work W --section hash      # X4h
tests/x4s2/run-evidence.sh --build B --db DB --p2 P2 --work W --section regress   # conformance and 200-game soak
```

Builds: `goldens`, `hash` and `regress` ran on the full `scripts/build.sh` build of `d62e6e6` (`~/haley-build.sh`,
lib digest `7fdf9e26...`). `audit` and `combat` ran on a development build of the same overlay sources (`e7de309`:
the stage 1 jars with the overlay recompiled by `javac --release 8`); the overlay did not change after `e7de309`.
Results are in `evidence/`.

| Run | Games | Endings | Validator violations | Host halts | Decisions checked |
|---|---:|---|---:|---:|---:|
| Combat decks, `uniform` (`combat-summary.json`) | 1,000 | all natural | 0 | 0 | 619,168 |
| X3 face-down decks, `uniform` (`facedown-summary.json`) | 600 | all natural | 0 | 0 | 428,792 |
| Combat decks, `heuristic` against `uniform` (`heuristic-summary.json`) | 400 | all natural | 0 | 0 | 166,465 |
| Hash order: as is, `-XX:hashCode=3`, `-XX:hashCode=4` (`base`, `seq`, `addr`) | 3 x 100 | all natural | 0 | 0 | 3 x 64,791 |
| X4c fixtures (`fixtures.jsonl`) | 2 | natural | 0 | 0 | |
| X4b goldens, generated and checked (`goldens/index.json`) | 5 | natural | 0 | 0 | |
| Conformance runner (`conformance.txt`) | 20 checks + 20 games | all 21 lines `PASS` | 0 | 0 | |
| Soak, `first` against `uniform` (`soak-summary.json`) | 200 | all natural (`uniform` won 200) | 0 | 0 | 95,366 |

## X4b: arrangement goldens (#18)

`goldens/` holds five XMage transcripts in the Section 16 format (one canonical `{dir, message}` line per message,
all four directions) with their game digests in `goldens/index.json`, built by `goldens.py generate`:

| Golden | Card | Block posed | Placed (position 0 first) | Then drawn | Game, digest |
|---|---|---|---|---|---|
| `xmage_scry` | Preordain | 2 `arrange_card` (both `top`) + 1 `order_pick` | Shivan Dragon, Air Elemental | Shivan Dragon, Air Elemental | 0, `437709fc...` |
| `xmage_surveil` | Curate | 2 `arrange_card` (`graveyard`, `top`) + 1 `order_pick` | Curate | Curate | 0, `34627148...` |
| `xmage_library_top` | Ponder | `order_pick` `library_top`, count 3, 2 posed | Shivan Dragon, Island, Air Elemental | Shivan Dragon, Island | 0, `b332a59d...` |
| `xmage_library_bottom` | Impulse | `order_pick` `library_bottom`, count 3, 2 posed | Island, Impulse, Hill Giant | Island, Impulse, Hill Giant | 3, `7cac8b09...` |
| `xmage_london_bottom` | two mulligans | `order_pick` `mulligan_bottom`, count 2, both posed | Hill Giant, Air Elemental | the last two draws: Hill Giant, Air Elemental | 0, `91ae2d03...` |

Each is a whole game of the Section 16 vector run secret through P's host with its live validator, both seats one
scripted bot in process (keep or mulligan twice, land, first castable spell, never attack, decline yes/no, card 0 of an
arrangement to the second destination where the golden says so, order picks last candidate first, so every placed
order is the reverse of the order XMage looked the cards up). The decks are 10 to 12 named cards, so the games end
by an empty library in 83 to 194 steps; the cards beside the one under test are distinct and uncastable, so a later
draw names the card it took. A golden is kept only when its block has the Section 7.5 shape and the seat's later
draws come off the library in the placed order: that is the check that XMage's "last one chosen is topmost" loops
are inverted correctly (position 0 closest to the top). Game 3 was used for `library_bottom` because games 0 to 2
put two cards of one name in the block.

`goldens.py check` replays each golden two ways: P's `conformance.replay_engine_transcript` (a fresh engine given the
recorded host requests must give the recorded answers, by value), and the whole game again through the host with
the same bots, whose rows must equal the golden byte for byte and whose digest must equal the indexed one. Verdict
on the final build: PASS, 5 of 5 (`evidence/goldens-check.txt`).

Interpretation: a surveil or scry card the seat sends elsewhere is placed in the destination order of Section 7.5
(`top, bottom, graveyard`), so in `xmage_surveil` the single order pick places Curate on top and the graveyard card
is the implied last position.

## X4c: no AI fallback (#19)

`decide/CallbackAudit` (`evidence/callback-audit.txt`, verdict PASS) lists the 322 methods a seat's player runs and
where each implementation comes from. It fails when a method resolves to XMage's `ComputerPlayer` without a
classification, or when a decision callback of `Player` is implemented outside the overlay.

| Where the implementation is | Count | Meaning |
|---|---:|---|
| `SeatPlayer` | 29 | posed as v2 decisions; a few causes halt (`unsupported:multi_amount` and the others of stage 1) |
| `AutoPayPlayer` | 2 | engine autopay (`mana_payment: engine_autopay`, Section 7.6) |
| `ComputerPlayer` | 16 | none decides anything in a game: draft and tournament hooks, bookkeeping, `isHuman` (false), `getAvailableManaProducers` (an autopay query) |
| `PlayerImpl` and `Player` defaults | the rest | XMage's rules code; its choices go through the posed callbacks |

Changes this audit led to:

- `chooseLandOrSpellAbility` was a silent default: `PlayerImpl` answers a free "play that card" with the card's spell
  ability and never asks. `SeatPlayer` now poses it when the card can be played more than one way, as
  `choose_option` with labels `play_land` and `cast:<method>` (v2.0 has no land-or-spell kind; question for P).
- Inside a payment (`isInPayManaMode`), the object choices autopay makes (convoke, delve, exile-from-graveyard costs)
  went to `ComputerPlayer.makeChoice`, whose ranking ends in a tie-break by object UUID. They now go to
  `decide/PayChoice`, the same ranking with a visible tie-break (X4h). Counted `autopay_default:*`: 624 in the 600
  face-down games, 0 elsewhere. `chooseTargetAmount`, `chooseUse`, `getAmount` and `getMultiAmount` inside a payment
  still use `ComputerPlayer`'s logic (deterministic, no id order), counted, and never reached in these runs.

Fixtures (`fixtures.py`, `evidence/fixtures.jsonl`, through P's host, validator on):

- Chandra, Flameshaper (FDN) against Grizzly Bears: the -4 reached `chooseTargetAmount`, posed as 19 `choose_target`
  decisions and 19 `distribute` (`damage`) decisions in game 0; no violation.
- Bloodbraid Elf cascading into Bonecrusher Giant: `chooseUse` (posed `choose_boolean`) then `chooseAbilityForCast`
  with the creature and its adventure, posed as `choose_cast_method` 8 times in game 0.
- Quirion Beastcaller (Standard-MonoG): `distribute` `counters` 61 times in 41 of the 600 face-down games.

## X4d: combat completability oracle (#20)

`decide/CombatOracle` replaces the stage 1 interim (three rejections, then only "no attack"). A declaration is posed
one decision per slot: per attacker, and per block of a blocker (a creature that can block additional attackers now
gets one decision per block, Section 7.5). A candidate is offered only when some choice for the later slots
completes the declaration into one XMage accepts unchanged: each complete declaration is tried on a fresh
`createSimulationForAI` copy, declared through XMage's own combat code, then put through the checks XMage's own
declare loops run (`checkAttackRestrictions`; `checkBlockRestrictions`, `checkBlockRequirementsAfter`,
`checkBlockRestrictionsAfter`). For a computer player those checks repair a bad declaration (they remove attackers
or blockers, or add required blocks) instead of rejecting it, so the oracle counts a declaration legal only when the
checks pass and leave it unchanged. Attack requirements (CR 508.1d) are maximized: a declaration must obey as many
of XMage's `creaturesForcedToAttack` as any legal declaration does. The copy is callback-free (a seat callback in a
simulation throws, and the declaration counts as illegal), and the collections XMage's `Combat` copy constructor
shares with the live game are detached first. XMage's own pre-declarations (forced attackers, forced blocks) are
removed and declared by the seat under the oracle.

Combat decks (`decks/`, written for this task): `X4d-Menace-R` (menace, attacks each combat, can't attack or block
alone, blocks each combat, blocks an additional creature), `X4d-Lure-G` (all creatures able to block it do so, must
be blocked if able, can't be blocked by more than one), `X4d-Raptor-RW` (attacks or blocks each combat if able,
menace, flying, extra blocks).

Over 2,000 games (1,000 `uniform` on the combat decks, 600 `uniform` on the X3 face-down decks, 400 `heuristic`
against `uniform` on the combat decks):

| Counter | Combat | Face-down | Heuristic |
|---|---:|---:|---:|
| `posed:declare_attack` decisions | 38,587 | 20,245 | 8,501 |
| `posed:declare_block` decisions | 20,754 | 9,531 | 4,987 |
| declarations rejected by XMage (`attack_rejected`, `block_rejected`) | 0 | 0 | 0 |
| declarations changed by XMage (`*_altered_by_engine`, `*_not_as_declared`) | 0 | 0 | 0 |
| dead ends (`dead_end:*` halts), oracle budget hits, oracle callbacks or errors | 0 | 0 | 0 |
| decisions where the oracle removed a choice (attack / block) | 5,609 / 9,747 | 0 / 546 | 1,294 / 2,723 |
| complete declarations tried (`combat_oracle_leaf`) | 152,579 | 55,819 | 36,421 |
| XMage pre-declarations taken over (attack / block) | 2,295 / 1,560 | 0 / 0 | 539 / 356 |

Throughput was 55.6 games per minute for the combat decks in 12 processes (stage 1: `uniform` on the catalog decks
took 13.0 s per game, about 55 per minute in 12 processes), so the oracle costs little.

Gaps: a cost to attack or block (Propaganda, Ghostly Prison) asks the seat inside XMage's declaration event; the
oracle's copy cannot ask, so such an attack or block is never offered (none of these decks has one). The oracle stops
a question after 3,000 complete declarations (never reached).

## X4h: hash order (#22)

Audit of what reaches candidate order and engine defaults (Section 7.1 deterministic order):

| Path | Source collection | Order now |
|---|---|---|
| any sorted decision | `Exchange.build` | rank, observation position, minor key, then (new) the canonical semantic, so XMage's collection order never breaks a tie |
| targets and selections | `Target.possibleTargets` (a `HashSet`) | observation position; hidden-zone cards (card_name, object_id) |
| attack defenders | `Combat.defenders` (a `HashSet`) | (new) players by seat, then battlefield order |
| `choose(Choice)` options | `ChoiceImpl` (linked), but card code may install a `HashSet` or `HashMap` | (new) code point order when the collection is a plain hash one (`choice_hash_order_sorted`: 1,335 in the face-down games) |
| card names | the card database set | (new) code point order of the wire value |
| exile records (observation positions) | `Exile.exileZones` (a `HashMap` by zone UUID) | (new) arrival, cards arriving together by (name, a per-viewer keyed hash) |
| autopay object choices | `PossibleTargetsComparator` ends in `BY_ID` (UUID) | (new) `PayChoice`: same ranking, visible tie-break |
| modes, triggers, replacements, cast methods, playable list, mana planner, special actions | XMage `LinkedHashMap`s or lists | insertion order (checked in XMage's source) |

Test: the same 100-game schedule (one run secret; `uniform` on the two catalog decks and the three combat decks)
three times in fresh processes: as is (HotSpot's default per-thread identity hash), with
`-XX:+UnlockExperimentalVMOptions -XX:hashCode=3` (a global sequence) and `-Dspellbench.hashWarmup=7919`, and with
`-XX:hashCode=4` (object address) and `-Dspellbench.hashWarmup=104729`. The warm-up (`Exchange.hashWarmup`, a test hook
that is a no-op unless set) draws that many identity hashes on the protocol thread and on each game thread, shifting
every identity hash the thread assigns later. The options reached the engine JVMs (`Picked up JAVA_TOOL_OPTIONS` and
`hashCode = 4 {environment}` checked). Result (`evidence/hash-determinism.json`): 100 of 100 game digests equal
across the three runs, and the engine counters equal too.

## Regression

On the final build: P's conformance runner (`conformance engine`, Standard16-RG and Standard16-UB, 20 games) passes
all 21 lines, and the 200-game first-vs-uniform soak of stage 1, live-validated, ends 200 natural games with 0
violations and 0 halts (95,366 decisions checked; stage 1: 95,130). Its counters show the oracle at work there too
(3,811 attack decisions, 5,252 declarations tried, no rejection) and `choice_hash_order_sorted` 256 times (an option set some catalog card builds as a
plain `HashSet`; the card was not identified).

## Questions for P

1. A free "play that card" whose card can be played as a land or cast (`chooseLandOrSpellAbility`) has no v2.0 kind;
   it is posed as `choose_option` (`play_land`, `cast:<method>`). Should v2.1 add one?
2. Section 7.5 says a creature that can block additional attackers gets one decision per additional block. This
   build poses one decision per possible block (up to the creature's limit or the number of attackers it can block),
   and after a `null` only `null` is offered (so a declaration has one spelling). Is a forced single-candidate
   decision acceptable there, or should the group shrink?
3. An attack or block with a cost (Propaganda) cannot be checked by the oracle without asking the seat inside the
   declaration; this build does not offer it. Is "never offered" acceptable for v2.0, or should the cost be posed
   as `optional_cost` after the group?
4. Goldens: these five are whole games of tiny decks (1 to 2.6 MB each). Would P prefer them shortened with a seat
   cap (a stalling forfeit ending), or kept as natural endings?
