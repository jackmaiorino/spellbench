# XMage agent kit (A1)

Lets XMage bots play as protocol v2 agents (spec Section 10) from their seat's permitted inputs only: rebuild a world
from the observation, sample what is hidden, let the bot decide on the world, answer with a candidate. Design:
`E:/spellbench-archive/program-research/x-agent-kit-design.md` (revision 3 and its addendum); issue spellbench#28.
Slice results and the build-out after the A1 result review are in `evidence/README.md`.

## Layout

| Path | What |
|---|---|
| `core/src/spellbench/kit/core/` | kit-core, no XMage imports: the front process (`Front`, agent role over stdio), frozen entries (`Entries`), runner link (`RunnerLink`: one clock per decision, kill, confirmed exit, late-result discard, background restart), seeds (`Seeds`, Section 4.5), sampler (`Sampler`, Section 4), plans (`PlanBook`, Section 6.1), aggregation and fallback (`Aggregate`, Sections 5.5 and 6.5), observation comparison modulo ids (`ObsCompare`), and three XMage-free checks (`SliceCore`, `TerminationCheck`, `FrontCheck`) |
| `xmage/src/spellbench/kit/xmage/` | kit-xmage: the runner process (`Runner`), world builder (`WorldBuilder`, `World`, `KitDuel`, `KitRandom`), mechanics register (`Register`), deciders (`KitMad` for H1 and H2, `KitMcts` for H3, `Puppet` for the other seat), mapping back to v2 (`Mapping`, `Dialogs`, `Continuation`, `Resolver`), H3 knowledge (`KnowledgeWatcher`, `KitRedeal`), budgets (`KitContext`), diagnostics (`RoundTrip`) and the slice harness (`Slice`, `SliceProd`) |
| `xmage/resources/` | `register.json`, built by `register/scan.py`, shipped in the kit-xmage jar |
| `xmage/src/mage/player/ai/` | XMage's MAD and MCTS plugins vendored at the pin (MIT; see `../NOTICE`), changed only where marked `KIT`; `KitPayPlayer` (the engine's deterministic autopay planner, for every kit player), `KitBudgets`, `KitNodes` |
| `xmage/src/mage/player/spellbench/{observe,decide}/KitBridge.java` | the shared library: the only places kit code reaches package-private engine overlay code (vocabulary, `ability_index`, cast `method`); everything else used from the overlay is public API (`ObservationBuilder`, `Observation`, `Look`, `Seats`, `Exchange`) |
| `xmage/e7/` | E7 reference probe (compiled only by `scripts/upstream.sh`, never on an entry's classpath) |
| `diffs/` | the published kit diffs of the vendored MAD and MCTS sources against the pin |
| `register/` | `scan.py` and `build-register.sh`: the mechanics register and the pool's admission for kit entries |
| `qualify/` | change 8: `kitrun.py` (plan, qualify, guarded run, R-1 replay, summary) and `launch.sh`; prepared, not run |
| `scripts/` | `agent.sh` (one agent process: front plus runner), `upstream.sh` (diffs and the E7 reference build), `diagnose-unmapped.sh` (review change 5) |
| `tests/` | `play.py` (kit games through P's host and live validator), `kitlog.py` (evidence-log summaries, mapping failures), `e4.py` (horizon accounting), `costs.py` |
| `evidence/` | slice results |

## Build

Against the engine's exact jars (decision K2), Java 8 source level:

```bash
engines/xmage/scripts/build.sh --out ENGINE --xmage-repo XMAGE    # the engine, unchanged
engines/xmage/kit/build.sh --engine-build ENGINE --out KIT        # KIT/lib/kit-core.jar, kit-xmage.jar, KIT-MANIFEST.json
```

## Run one agent

```bash
kit/scripts/agent.sh --kit KIT --engine-build ENGINE --db DB [--work DIR] --entry h1|h2|h3 [--log FILE]
```

The front answers `hello` at once; at `game_start` it starts the runner (a child JVM with its own copy of the card
database, about 12 to 14 s to boot on the compute host) inside `game_start_ms`.

Entries (frozen in `Entries.java`, A1 result review change 6). The identity is the name plus a digest of the whole
configuration (`bot.version` = `0.3.0+DIGEST`); any override of a frozen value adds `-custom` to the name and changes
the digest.

| `--entry` | Name | Bot and dispatch | K | Budgets |
|---|---|---|---:|---|
| `h1` | `kit-mad-1` | ComputerPlayer7 search in the main phases and declare steps, its own pass elsewhere; MAD combat | 1 | 5000 nodes, 2000 options, 20 000 operations |
| `h2` | `kit-mad-k` | as h1, vote over K worlds | 4 | as h1, per world |
| `h3` | `kit-mcts` | MCTS at every priority decision and for combat (upstream dispatch); a rollout stopped by a cap or horizon is scored by the evaluator against the decision's score (design 5.6) | 1 | 30 iterations, rollout cap 1000, 20 000 operations, 2000 options, 128 combat engagements per expansion (the first in upstream's enumeration order: a labelled baseline biased toward that prefix; with eight available attackers the no-attack engagement is outside it) |

All entries: ComputerPlayer dialog heuristics (the same in both upstream bots); a world with a horizon-flagged stack
object, dropped pending triggers or an unsupported state is not searched and the front declines (wrapper); a chosen
action that does not use the stack and asks a dialog while it executes is unsupported (next ranked candidate,
wrapper). Overrides: `--nodes`, `--options`, `--operations`, `--iterations`, `--rollout`, `--worlds`, `--skill`.
Evidence options: `--log FILE` (one JSON line per decision with its tag `bot`, `wrapper` or `cap`), `--roundtrip 1`
(observation round-trip diagnostics, Section 7.2), `--dump DIR` (priority-anchor decisions as the runner receives
them), `--hang-at N` (E3 test hook), `--search-flagged 1` (E4 measurement: flagged worlds are searched up to the
horizon; a custom identity).

The frozen `mad7-s1` through `mad7-s10` entries expose the ten upstream UI skill settings through this same
CP7 wrapper, with names `xmage-mad7-fair-s1` through `xmage-mad7-fair-s10`. Each includes the skill, effective
depth, sampled-world information policy and changed synchronous search settings in its identity. `mad7-s7`
is the skill-7 fair variant. These entries retain the kit's 5,000-node, 2,000-option and 20,000-operation budgets.
Skills 1 to 4 share upstream's depth floor of 4; their fair policies need an equivalence check before counting
them as separate rated policies. Version 0.3.0 records the changed renamed-card reconstruction policy. The historical
0.2.0 identities and soak records remain archived; they are not qualification of this build. The supported plan
command accepts all skill entries and refuses duplicate policy aliases in one roster. Full qualification remains
pending. The targeted repairs and remaining deadline risk are in `evidence/native-repairs-20261003.md`.

Clock (change 2): each `choose` has one answer time, `min(max_decision_ms, remaining_ms)` minus `--overhead-ms`
(1500). Waiting for a booting runner, the search (runner deadline = time left minus `--grace-ms`, 5000), a failed
continuation's current-dialog search, diagnostics and a kill all share it; `--kill-reserve-ms` (300) is kept for
the kill and the fallback.

## Mechanics register

`register/build-register.sh` runs `register/scan.py`, a conservative static scan of the pinned XMage sources for the
pool's cards and the fixture cards, into `xmage/resources/spellbench/kit/xmage/register.json`. The world builder
enforces it (change 3): a stack trigger whose card may read event data, an activation that reads captured values or
paid costs, a spell with optional or alternative costs, and a stack object whose targets cannot all be placed are
flagged approximate with the search horizon; dropped pending triggers stop priority searches; emblems are rebuilt
from the register (one emblem class with a no-argument constructor per source); other command objects and tokens
that do not resolve by name are unsupported. `admission` lists the decks admitted for kit entries (a deck with a
restricted-mana card, an emblem that cannot be rebuilt or control of another player is excluded).

## Other engines (mtg-kernel)

The kit reads only its seat's protocol messages, so it can sit in a seat of another v2 engine whose cards XMage
implements. The pauper-kernel decks are XMage `.dek` lists; `register/pauper-kernel-decks.json` copies them from
mtg-kernel's `data/runtime_decks_v1.json` with their source hashes, and the register admits all eight decks
(112 cards, every one resolving at the XMage pin). What the kit handles for that engine:

- `cast_spell` with `method: null` (Section 7.4). The world's cast of that card, whatever its method, answers the
  candidate (`core/.../Offers.java`, the runner's root filter and the front's keys), and the action's plan answers the
  following `choose_cast_method` with the world's method.
- `seat_decision.extensions` are dropped on arrival: the kit reads none, and mtg-kernel's model inputs can reach
  several MiB per decision.
- A double-faced card on the battlefield enters the world on the face the observation names, the back face
  transformed, and the sampler counts a face's name against the list row its `full_name` names (CawGates' The
  Modern Age // Vector Glider; Slice case `DFC`).
- A priority stop whose only actions besides pass are mana activations answers pass without a search
  (`mana_only_pass`): the kernel offers priority mana at nearly every stop, and the kit's searches never root on a
  mana ability.

Still open for the kernel: `choose_cost_option`, `optional_cast` (madness) and `optional_cost` for `additional` and
`copy` costs have no world dialog yet and answer by the declining fallback; the kernel's observation omits
`pending_triggers` and offers a shorter keyword list, so continuation and characteristic checks fall back more often.
- A token that copies a decklist card enters as XMage's copy: an embalmed card (the kernel's `"<card> Embalmed
  Token"`, a white Zombie copy without mana cost) or a plain copy under the card's name. The token repository holds
  neither, and CawGates' embalmed Sacred Cat left 23% of its decisions unsearched (Slice case `EMBALM`).
- kit-mcts paces its searches by the bank (`clock.pace_moves` 20, `clock.pace_floor_ms` 12000): a decision gets at
  most an even share of the remaining bank plus the increment, and its search is interrupted at that clock. A fixed 30
  iterations on the kernel decks took 20 to 25 s per decision and spent the 600 s bank by about decision 50. The
  pacing is part of kit-mcts's configuration, so its identity changed; kit-mad-1 and kit-mad-k are unchanged.
- A land that asks a color as it enters (Sea Gate, Citadel Gate) is played. Such a land leaves no stack object, so
  its dialog used to make the play unsupported and the next ranked candidate answered (47 times in 7 CawGates games
  on the kernel). When every dialog of a non-stack action is a color choice, the world's color is the plan's
  (kit-mcts carries it as the payload's `colors`), and the color decision binds to the played land by name, since the
  land is a new object on the battlefield. A `choose_color` with no planned color (Prismatic Strands) is answered by
  ComputerPlayer's color choice on the offered colors. The policy text changed, so all three identities changed.

None of this is qualification. Thirty-two unrated smoke games on the kernel (2026-10-06, kit-mad-1 and kit-mcts
against a uniform seat) ended naturally with no halts or validator violations; they showed the two gaps above.

## Games through P's host

```bash
PYTHONPATH=P2/python python kit/tests/play.py --games 4 --out games.jsonl --kit-name kit-mad-1 --kit-version 0.2.0+DIGEST \
  --kit-cmd '["bash", "kit/scripts/agent.sh", "--kit", ...]' --opponent heuristic -- ENGINE_COMMAND...
```

## Slice checks

```bash
java -cp KIT/lib/kit-core.jar spellbench.kit.core.SliceCore
java -cp KIT/lib/kit-core.jar spellbench.kit.core.TerminationCheck WORKDIR
java -cp KIT/lib/kit-core.jar spellbench.kit.core.FrontCheck WORKDIR     # continuation plans and the clock
java -cp "KIT/lib/kit-xmage.jar;KIT/lib/kit-core.jar;KIT/lib/kit-upstream.jar;ENGINE/lib/*" -Dkit.e7.dir=DUMPS \
  spellbench.kit.xmage.Slice OUT.jsonl [S1 ... E7MAD DFC S2P S3P S4P S10P REG POOLAUDIT A3 MCTSPOWER UNMAPPED]
```

Run `Slice` in a directory holding its own `./db`. The `P` cases and `A3` answer the viewer seat through a real front
and runner child process; only the kit's first action is forced (`Front.forceForTest`). `UNMAPPED` reads
`-Dkit.unmapped.dir` (see `scripts/diagnose-unmapped.sh`).
