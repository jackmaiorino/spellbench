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
database, about 12 to 14 s to boot on HaleysPC) inside `game_start_ms`.

Entries (frozen in `Entries.java`, A1 result review change 6). The identity is the name plus a digest of the whole
configuration (`bot.version` = `0.2.0+DIGEST`); any override of a frozen value adds `-custom` to the name and changes
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
  spellbench.kit.xmage.Slice OUT.jsonl [S1 ... E7MAD S2P S3P S4P S10P REG POOLAUDIT A3 MCTSPOWER UNMAPPED]
```

Run `Slice` in a directory holding its own `./db`. The `P` cases and `A3` answer the viewer seat through a real front
and runner child process; only the kit's first action is forced (`Front.forceForTest`). `UNMAPPED` reads
`-Dkit.unmapped.dir` (see `scripts/diagnose-unmapped.sh`).
