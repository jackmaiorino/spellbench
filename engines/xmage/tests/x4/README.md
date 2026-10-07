# X4 stage 1 evidence: decision mapping

Task X4 stage 1 (issues #17 X4a, #21 X4e and the minimal part of #20): every XMage prompt the catalog decks reach
is posed as a protocol v2 decision, with groups, rewinds and engine autopay, so whole games play through P's host
and its live validator. Code: `overlay/.../spellbench/decide/` (the mapper), `server/GameSession.java` (the game
thread and the exchange).

## Command

On the compute host, engine built from branch `xmage-x0-x1` at `5e40ea8` with `scripts/build.sh` (identity strings
unchanged from X1: no core patch was added), P's stack at protocol-v2 `4b588a1`:

```bash
tests/x4/run-evidence.sh --build ~/x-spike/build --db ~/x-spike/db --p2 ~/x-spike/p2 --work ~/x-spike/x4/evidence
```

The script runs, in order, at below-normal priority (the machine was shared):

1. P's conformance runner: `spellbench conformance engine --format standard-2022-25-bo1 --deck Standard16-RG
   --deck Standard16-UB --games 20 -- scripts/engine.sh ...`.
2. `soak.py`: 200 games of the conformance games' configuration (builtin `first` against `uniform`, seat-swapped
   pairs, each catalog deck in turn, London mulligan), through `host.game.play_game` with the live validator, in
   12 engine processes that each play their games in sequence.
3. The same 200-game schedule again (same run secret) in 8 fresh processes, so every game runs after different
   games in its process; the 200 game digests (Section 11.8) are compared.
4. `soak.py --replay 0`: game 0 twice in one engine process and twice in a second process. A process refuses a
   reused `game_id` (Section 9.2), so a repetition in the same process runs under a fresh id and its digest is
   chained with the scheduled id put back.
5. `caps.py`: seven games cut by `max_decisions` or `max_steps`, every decision checked by P's `LiveValidator`
   and the terminal by `check_terminal` (the host's per-seat caps never let a host-run game reach an engine cap).
6. Coverage soaks: 100 games `uniform` against itself, 100 games `heuristic` against `uniform`, and 60 games of
   `uniform` on the X3 face-down decks (`tests/x3/decks`, sent as decklists).
7. The 100 `uniform` games again in 8 fresh processes; their digests are compared.

`agg.py` sums the per-game counters the engine writes (`SPELLBENCH_XMAGE_STATS`, engine side only).

## Results (2026-10-01)

All files are in `evidence/` (`BUILD-MANIFEST-computehost.json` is the build's manifest).

| Run | Games | Endings | Live-validator violations | Host halts | Decisions checked |
|---|---:|---|---:|---:|---:|
| Conformance (`conformance.txt`) | 20 checks + 20 games | all 21 lines `PASS` | 0 | 0 | |
| Soak, `first` vs `uniform` (`soak-summary.json`) | 200 | 200 natural (100 each seat) | 0 | 0 | 95,130 |
| Same schedule, 8 fresh processes (`rerun-summary.json`) | 200 | identical | 0 | 0 | 95,130 |
| `uniform` vs `uniform` (`uniform-summary.json`) | 100 | 100 natural | 0 | 0 | 62,879 |
| `heuristic` vs `uniform` (`heuristic-summary.json`) | 100 | 100 natural (heuristic won 69) | 0 | 0 | 42,748 |
| `uniform`, X3 face-down decks (`facedown-summary.json`) | 60 | 60 natural (9 by an empty library) | 0 | 0 | 44,835 |

No game in any run ended `halted` or `truncated`; the halted-game rate is 0 for every cause. In the
first-vs-uniform soak, `uniform` won all 200 games: `first` takes candidate 0, which is `pass` at every priority
decision, so it never plays a land.

Per game, first-vs-uniform soak (12 engine processes at below-normal priority on a machine shared with another
session's builds):

| | Mean | Median | Min | Max |
|---|---:|---:|---:|---:|
| Decisions (`step_count`, both seats) | 475.6 | 448 | 189 | 1,215 |
| Completed groups (`decision_count`) | 459.3 | 429 | | |
| Wall seconds per game | 8.05 | 6.99 | | 29.8 |

Throughput was 39.7 games per minute (302 s for 200 games); the rerun in 8 processes made 48.3. `uniform` against
itself averages 629 decisions and 13.0 s per game.

Determinism (Section 11.8):

- `determinism.json`: the 200 games of the soak and of its rerun have equal digests, 200 of 200. The rerun splits
  the schedule over 8 processes instead of 12, so each game runs after different games in its process.
- `uniform-determinism.json`: the same for the 100 `uniform` games, 100 of 100.
- `replay.json`: game 0 twice in one engine process and twice in a second process: four equal digests
  (`sha256:cb37f973...`), 329 decisions each.

Caps (`caps.json`): `caps verdict: PASS`. All seven games ended `truncated` at their cap (three at
`max_decisions`, four at `max_steps`), with `step_count` and `decision_count` equal to the validator's counts and
`check_terminal` accepting the truncation (V3).

## How XMage's prompts map (the corrected Annex C, as built)

| XMage callback | v2 decision | Notes |
|---|---|---|
| `priority` | `pass`, `play_land` (`face`), `cast_spell` (`method`), `activate_ability` (`ability_index`), `special_action` | `getPlayable` with duplicates kept, then filtered: mana abilities never (autopay); an action whose non-mana costs, targets, spree modes or tap-source mana cannot be met is not offered; a rejected one is re-posed away with `rewind` (below) |
| `chooseTarget` (targeted) | `choose_target`, `finish_target_selection` | `slot` is the requirement's index across the selected modes; fixed counts are one group, variable counts one group per decision |
| `choose` (not targeted), card choices | `select_object`/`finish_selection`, or `choose_cost_target` for a fixed-count cost | purpose from the cost class or `Outcome`; a library search has minimum 0 and always offers finish; every card the effect shows is a `known` entry |
| London bottom | `order_pick` `mulligan_bottom`, all k picks | `LondonAfterKeep` moves XMage's bottom step from each mulligan to the keep (CR 103.5, Section 7.5) |
| `putCardsOnTop/BottomOfLibrary` (any order) | `order_pick` `library_top`/`library_bottom` | n - 1 picks; XMage's loop is then answered from the picks |
| `scry`, `doSurveil` | `arrange_card` and `order_pick` `arrangement`, one group of 2n - 1 | looked-at cards are `known` with their positions |
| `chooseUse` | `optional_cost` (kicker, offspring, unless payment, ...), `choose_cast_method` (alternative cost), else `choose_boolean` | `pay: true` only when the seat's mana covers the cost (Section 7.1) |
| `choose(Choice)` | `choose_color`, `choose_name` (domain-restricted card names, normalized types), `choose_cast_method` (XMage's alternative-cost menu), else `choose_option` | mana color choices inside a payment are autopay's |
| `chooseMode` | `choose_spell_mode`, `finish_selection` `modes` | "choose N" is one fixed group; spree modes the seat cannot pay for are not offered |
| `announceX`, `getAmount` | `choose_number` | X bounded by the seat's available mana; more than 4096 values halts `candidate_limit` |
| `chooseTargetAmount` | `choose_target` decisions, then a `distribute` group | at least 1 per target (CR 601.2d) |
| `getMultiAmount` (combat damage) | `distribute` `combat_damage`, one per recipient | recipients matched to XMage's dialog; trample adds the defender as the last, forced recipient. Other multi-amount prompts halt `unsupported:multi_amount` |
| `chooseTriggeredAbility` | `order_pick` `triggers` | n - 1 picks, the last implied; `event_objects` empty |
| `chooseReplacementEffect` | `choose_replacement` | `affected` is the choosing seat, `event` `other` (the callback carries neither) |
| `choosePile` | `choose_pile` | |
| `selectAttackers`, `selectBlockers` | `declare_attack`, `declare_block` groups, one decision per creature | no completability oracle yet (stage 2) |
| `chooseMulligan` | `mulligan` | under `rules.mulligan: none` the engine keeps for both seats |
| `playMana` | engine autopay | XMage's computer-player planner, with producer ties in battlefield order (`AutoPayPlayer`) |
| `chooseAbilityForCast` | `choose_cast_method` | when more than one spell ability can be cast |

## What the games exercised (`evidence/counters-*.json`)

Totals over the first-vs-uniform soak (200 games), with the number of games each occurred in; the other runs'
files have the same counters.

| Counter | Total | Games | Meaning |
|---|---:|---:|---|
| `posed:priority` | 85,239 | 200 | priority decisions |
| `single_candidate` | 74,775 | 200 | decisions with one candidate (mostly pass-only priority) |
| `posed:declare_attack` | 3,682 | 200 | attack substeps (`first` never has creatures, so no blocks here; `uniform` vs `uniform` posed 839 block substeps and 229 `distribute` `combat_damage`) |
| `posed:select_object:discard` | 2,080 | 200 | cleanup discards (`first` never plays its cards) |
| `posed:choose_target:*` | 1,644 | 200 | targets, by the purpose the effect would have |
| `posed:mulligan`, `order_pick:mulligan_bottom` | 579, 183 | 200, 83 | London mulligan |
| `posed:order_pick:triggers` | 529 | 136 | trigger orders |
| `posed:choose_option` | 272 | 54 | Manifold Mouse's "double strike or trample" |
| `posed:optional_cost:*` | 296 | 104 | kicker (Burst Lightning), offspring (Pawpatch Recruit), unless payment |
| `posed:arrange_card:surveil`, `order_pick:arrangement` | 181, 62 | 64, 32 | Faerie Dreamthief and Kaito surveil |
| `posed:choose_spell_mode` | 83 | 61 | Gix's Command, Phantom Interference (spree) |
| `autopay` | 7,718 | 200 | mana payments the engine made itself |
| `action_not_offered:incompletable` | 2,269 | 86 | playable actions not offered: unpayable non-mana costs, no legal target, no affordable spree mode |
| `optional_cost_unpayable:*` | 269 | 97 | optional costs offered with `pay: false` only |
| `rewind` | 248 | 30 | priority decisions re-posed after a failed action (Section 8) |
| `autopay_failed` | 186 | 15 | of which autopay could not pay |

The face-down run adds `choose_cast_method` (59, XMage's alternative-cost menu), `choose_replacement` (19),
`distribute` `counters` (11, Quirion Beastcaller), `select_object` `search` (104), `block_redeclared` (20) and
`block_altered_by_engine` (8).

## Interpretations and gaps

Spec points this build interprets or does not yet meet:

- **Rewind (Section 8).** XMage reports a failed activation only after the fact (`activateAbility` false, its state
  rolled back). The seat's next priority decision is then posed with `context.rewind: true` and without the failed
  action; failed actions stay excluded until the seat passes or completes an action. The validator's rule decides
  which groups stop counting (the failed action's priority group and every group completed since, by either seat),
  and the engine counts the same way.
- **No dead ends (Section 7.1).** Stage 1 prefilters what is cheap to check and rewinds the rest: 1.2 rewinds per
  game in the first-vs-uniform soak, 2.9 with `uniform` on both seats, 5.2 with `heuristic` (which tries the first
  castable spell again at every priority decision). Remaining causes: autopay failing where XMage's playable list
  counted conditional mana (Rockface Village's red for a non-creature spell) or its greedy planner picked the wrong
  land, and Fountainport's costs.
- **Combat (Section 7.5).** One decision per possible attacker or blocker; no completability oracle (stage 2). When
  XMage rejects a declaration it asks again (a new group, counted `*_redeclared`); after three rejections the
  creatures that need not attack or block are offered only `null`. For a computer player XMage's own checks also
  remove an illegal attacker or blocker and add required blocks without asking (counted `*_altered_by_engine`).
  A creature that may block more than one attacker gets one decision, not one per additional block.
- **London mulligan (Section 7.5).** XMage asks for the bottom cards right after each mulligan, before the next
  keep decision. `decide.LondonAfterKeep` moves the step to the keep, as CR 103.5 and the spec order it. This is
  overlay code, so `rules_snapshot_id` (which hashes only core patches) did not change.
- **Engine autopay (Section 7.6; design D5, D6b).** XMage's computer-player planner, which also decides convoke,
  delve, improvise, Phyrexian payments and mana color choices. Its producer ranking sorted ties through a
  `HashMap` keyed by objects without a value `hashCode`; `decide.AutoPayPlayer` copies the planner with a
  `LinkedHashMap` (overlay, no core patch). `optional_cost` offers `pay: true` only when XMage's available-mana
  estimate covers the cost (that estimate includes conditional mana).
- **Determinism (Section 11.8).** The cross-process rerun first found one game in 200 whose digest depended on
  the games its process had played before: the mapper parsed a prompt's mana text with `ManaCostsImpl(String)`,
  which caches parsed costs process-wide and mints object ids only on a miss. The mapper now parses mana symbols
  itself. XMage card code that parses mana strings mid-game would show the same effect; none showed up in these
  runs. `-Dspellbench.trace.ids=PATH` (in `rng.GameRandom`) writes every game id draw with its callers, which is
  how the cause was found.
- **Purposes (Section 7.4).** From the calling XMage class (`decide.CallSite`) and the prompt's `Outcome`, else
  `other`. `choose_option` labels are XMage's option text.
- **Triggers (Section 7.3).** `order_pick` trigger items carry `event_objects: []` and `label: null`; `instance`
  numbers triggers with the same visible source and ability index.
- **Replacement choice.** `affected` is the choosing seat and `event` is `other`: XMage's callback names neither.
- **Knowledge (Section 6.7).** A card choice shows every card the effect looks at as `known` (all of the other
  seat's hand for Deep-Cavern Bat, not only its nonland cards); library cards in a search are `searching` with no
  position.
- **Cast methods.** `cast_spell.method` comes from the spell ability's class and type. XMage's alternative-cost menu
  ("Choose an alternative cost") is posed as `choose_cast_method`; when two entries map to one method it falls back
  to `choose_option`. Two playable abilities with the same semantic are merged (counted `duplicate_candidate`).
- **Declared kinds.** `activate_mana_ability` (never offered under autopay), `choose_cost_option` and
  `optional_cast` are not emitted and no longer declared; `choose_starting_player` was never declared.
- **Pass-only priority.** Posed (design D6a is a v2.1 question): about three in four decisions offer one candidate.
- **Still halting** (`engine_contract_failure:<cause>`): multi-amount prompts outside combat
  (`unsupported:multi_amount`), damage dialogs whose recipients cannot be matched
  (`unsupported:combat_damage_recipients`), a group that runs out of candidates (`dead_end:*`), a declaration
  rejected 20 times, and more than 4096 candidates. None occurred with the catalog decks.
- **Not seen** in any run's counters: scry, library orders, card naming (`card_name_domain`), colors, numbers,
  piles, non-combat multi-amount prompts and `chooseAbilityForCast`. They are mapped (or halt, as above), but no
  game here checked them. Special actions are offered at priority and not counted separately.
- Stage 2 (combat oracle, callback audit, goldens, hash order): see `tests/x4s2/README.md`.
