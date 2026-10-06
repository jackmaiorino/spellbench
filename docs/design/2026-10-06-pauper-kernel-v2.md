# Pauper-kernel v2: one Pauper board for kernel models, XMage and gorge bots

Status: route decided. On 2026-10-06 Jack chose the single board with world-model
agents (C1 to C3) over separate per-engine Pauper boards. The remaining changes are
proposals for review. Owner: the Spellbench lead (Claude),
per Jack's 2026-10-06 assignment. This proposal changes no frozen gate,
commitment, running qualification or existing benchmark definition. Everything
below applies to a new evaluation version of `pauper-kernel-v2`; the v1
`pauper-kernel` board and its two published runs stay frozen as history.

## Goal

Jack, 2026-10-06: get all XMage heuristic bots and all gorge bots up against the
pauper-kernel benchmark, with a v2 of its protocol. Success is the gorge and
XMage families rated on the same eight-deck Pauper board as g115, a48 and c12,
on one engine, with ratings that are directly comparable.

## Where things stand

| Board | Engine and wire | Roster | Status |
|---|---|---|---|
| `pauper-kernel` | mtg-kernel, Spellbench wire v1 | uniform, heuristic, first, g115, a48, c12 | Rated 2026-09-26 and 09-27. Not audited for hidden information; its halts come from builtin bots taking goad and menace choices the engine offers but the rules forbid |
| `pauper-kernel-v2` | mtg-kernel, wire v2, neutral choices | panel g115, a48, c12; uniform calibration; GPT-6 Luna | No formal games. `known_cards: false`, no public history. Luna (#74) waits on PR #130, which waits on mtg-kernel #147 |
| `pauper-gorge` (PR #64) | gorge engine, wire v2 | 12 gorge strategies, uniform, heuristic | Five decks (Wildfire, Rally, Spy, Burn, CawGates), 3,640 scheduled games, 0 rated. Native107 failed at game 49 with 2 reconstruction budget exhaustions; native129 stopped at game 51 (Wildfire, search-redeal) after 11 |
| `fdn-native-v1` | XMage engine, wire v2 | nine fair MAD and MCTS variants, uniform, heuristic | FDN Limited only, 7,040 scheduled games, 0 native rated games. All eight Pauper decks come from XMage's own `decks/Pauper/` files; the kit's card scan at pin fd40ad5c finds all 112 cards (93 supported, 19 approximate, 0 unsupported) |

Sources: the benchmark definitions under `benchmarks/`, PR #64's description and
`docs/gorge-search-bridge-20261002.md` on its branch, `engines/xmage/BOTS.md`,
`docs/pauper-luna-panel-20261003.md`, issue #40.

## The problem

Gorge and XMage bots are engine-bound. The gorge agents read gorge's native view
(`x_gorge_view_v1`) and gorge's public event deltas (`x_gorge_search_v1`); the
XMage bots run inside the XMage process. Neither can sit in an mtg-kernel seat
today. Running them on their own engines yields separate boards whose numbers
are not comparable: the rules implementations, card coverage and decision
surfaces differ, and no game ever crosses between them.

To be "against the pauper-kernel benchmark" they have to play mtg-kernel games
through the neutral v2 wire. The searching bots already do the hard part: gorge
search-redeal and the XMage fair variants rebuild hypothetical worlds in their
own engine from a seat's information only. v2 of the Pauper board makes that
pattern a first-class, declared kind of entrant, and gives it the inputs it
needs.

## Changes

### C1. One board, panel schedule

`pauper-kernel-v2` stays the single Pauper board: mtg-kernel engine, the eight
decks, mirror matches, four seat-swapped pairs per deck. It keeps the reference
panel workflow (`docs/reference-panels.md`): every new entrant plays the panel
(uniform calibration, g115, a48, c12), and the panel plays itself once.

| Item | Games |
|---|---:|
| Panel and calibration (6 matchups × 64) | 384 |
| One new entrant (4 opponents × 8 decks × 4 pairs × 2) | 256 |
| 12 gorge strategies | 3,072 |
| 9 XMage fair variants (after deduplicating aliases per `BOTS.md`) | 2,304 |
| GPT-6 Luna (unchanged plan, no uniform matchup) | 192 |
| **Total** | **5,952** |

A full round robin of the same 26 entrants would be 325 matchups × 64 = 20,800
games. Entrants do not meet each other; their ratings link through the panel,
and the page says so.

### C2. World-model agents

A world-model agent is a bot that embeds a second rules engine and rebuilds
hypothetical worlds from its own seat's messages. It declares:

```json
"engine": "any",
"world_model": {"engine": "gorge", "source": "26257e0eda1779d739a07e835c6500b9c4dabc62",
                "card_coverage": "sha256:…", "fallback": "native-sampler-only/v1"},
"resources": {"cpus": 1, "memory_mb": 2048}
```

- Its only inputs are its seat's `game_start`, `choose` and `game_over`
  messages, as for any agent (Section 11.7). It never reads the mtg-kernel
  process, a game secret, or another seat's messages.
- `world_model` is part of the entrant identity and is fingerprinted by
  `bench prepare`. Changing the source pin, coverage or fallback is a new
  evaluation of that entrant only.
- `resources` is per entrant (issue #40, question 15). The host schedules on
  declared cores and memory, so a 2 GB XMage agent and a 1 GB gorge agent can
  share a machine with the kernel scorers.
- An unanswerable decision is the agent's forfeit (`agent_error`), never an
  engine halt.

Non-search engine-bound bots (gorge `bot`, `lethal-pressure`, XMage's base
dialog heuristics) enter the same way: the world model translates the neutral
observation into a native view and asks the native policy. Their hidden-zone
inputs come from the world model's own sampling, never from the real game.

### C3. Public history and a complete knowledge tracker

Wire v2.0 carries no public event history (Section 14), and `pauper-kernel-v2`
declares `known_cards: false`. Reconstruction cannot be faithful without both:
gorge's redeal needs the ordered public events (draws, reveals, shuffles,
library exits, London bottoms) to constrain hidden zones.

- Add `x_public_history_v1`: engine-neutral, actor-visible event deltas since
  the seat's previous decision, with per-viewer ids and no counters, generalized
  from `x_gorge_search_v1`. The mtg-kernel adapter emits it; the gorge and XMage
  world models consume it. It obeys F2 and F4 in full and needs the Section 14
  audit for the eight-deck pool before rated use.
- Replace `known_cards: false` with a complete v2 knowledge tracker in the
  mtg-kernel adapter (Section 6.7 update table), checked against the extension
  so the two can never disagree.
- Once a second engine emits the same extension, propose it as a v2.1 core
  field.

### C4. Card coverage

Mirror matches mean an entrant needs only the decks it plays, but every card of
each such deck in its world model.

- Preflight checks each entrant's declared coverage against every pool deck and
  schedules it only on covered decks.
- Only entrants covering all eight decks appear on the main Elo table. A partial
  entrant is published as a labelled slice ("rated on 5 of 8 decks") with its
  covered-deck results against the panel on those same decks.
- Today gorge's pool omits Affinity, Elves and Faeries; the reason is to be
  confirmed with the gorge thread, and porting any missing cards is the path to
  the main table.
- XMage already covers all eight decks: the eight pauper-kernel decks are
  XMage `.dek` files (mtg-kernel `data/runtime_decks_v1.json`, from XMage's
  `decks/Pauper/`), and the kit's card scan (`engines/xmage/kit/register/scan.py`
  at pin fd40ad5c) admits all 112 cards: 93 supported, 19 approximate, 0
  unsupported. The four Pauper profiles in `engines/xmage/coverage.json` are RL
  training profiles, not card coverage. The 19 approximate cards are disclosed
  on the entrant's page. XMage's remaining gaps are candidate-shape mismatches
  in the kit, which the XMage thread is fixing separately.

### C5. Search budget exhaustion is an agent outcome

Gorge's redeal qualification requires zero reconstruction exhaustion and zero
refused roots. A single exhaustion fails the whole attempt, so qualification
becomes a lottery as the game count grows: with a per-game exhaustion
probability p, a clean 640-game audit has probability (1 − p)^640, which is
about 4% at p = 0.5%. Native107 and native129 both failed this way, at games 49
and 51.

For this board:

- Budgets are counted in work (attempts, worlds, submits, nodes), never in
  seconds, so replays stay exact (Section 11.4).
- On exhaustion the agent plays its declared deterministic fallback (for gorge,
  the native sampler's worlds or the native default bot) and answers normally.
- The agent reports every exhaustion and fallback in its game-over receipt; the
  ledger records the counts per entrant, deck and decision kind, and the page
  publishes the rate.
- Qualification bounds the rate rather than forbidding it: over a fixed,
  pre-declared sample, the upper 95% bound on fallback decisions per search
  decision stays below 1%, matching the existing under-1% adapter mapping
  fallback gate.

This is a rule for new evaluations on this board. It does not loosen PR #64's
frozen `pauper-gorge` gates.

### C6. Halts and pairs

- The no-dead-end rule (Annex A) applies to mtg-kernel's v2 adapter: no candidate
  may lead to an unfinishable group (the declined goaded attacker and the lone
  blocker on a menace attacker behind the v1 halts).
- A halted or truncated game removes its whole seat-swapped pair from ratings,
  so pair totals never mix one-sided evidence.
- A run whose engine halts exceed 1% of scheduled games is published as
  invalid, not rated. Halt attribution (`last_selection`) and quarantine stay as
  in Section 11.5.

### C7. One clock, measured

All entrants share one time control, sized from qualification of the slowest
admitted agent. The proposal starts from gorge's current profile
(`max_decision_ms` 60,000, `bank_ms` 600,000) and raises it only on measured
need. Per-entrant clock profiles (issue #40, question 11) stay out of this
board, because a rating should not depend on a privately chosen clock.

### C8. Versioning

Enabling `x_public_history_v1` and the knowledge tracker changes the
information rules, so the board moves to `evaluation_version`
`pauper-neutral-v2.1.0`. The panel's 384 local reference games replay; they use
no paid calls. Luna has no formal games yet, so its 192 games should run under
the new version rather than the old one, which would otherwise need a rerun.

## Questions from issue #40 this board needs answered

- D6a (questions 8 and 23): may the engine answer pass-only priority itself?
  It cuts most of the world-model agents' calls.
- Question 14: an agent `requires.engine`. A world-model agent instead declares
  `engine: "any"` plus `world_model`; this supersedes the request for this board.
- Question 15: per-agent resources, adopted in C2.

## Work order

1. mtg-kernel adapter: complete knowledge tracker and `x_public_history_v1`,
   with the Section 14 audit for the eight decks.
2. gorge world-model agent: point the existing public collector at
   `x_public_history_v1`, translate the neutral observation into a gorge view,
   declare coverage and fallback. Start with the five covered decks.
3. XMage world-model agent: the same for the MAD and MCTS fair variants,
   on all eight decks.
4. Card coverage ports for gorge's missing decks.
5. Qualification under C5, then commitment and rated panel runs per family.

Each step is its own PR. Steps 2 and 3 run in parallel once step 1 lands.
