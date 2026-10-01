# XMage agent kit (A1 vertical slice)

Lets XMage bots play as protocol v2 agents (spec Section 10) from their seat's permitted inputs only: rebuild a world
from the observation, sample what is hidden, let the bot decide on the world, answer with a candidate. Design:
`E:/spellbench-archive/program-research/x-agent-kit-design.md` (revision 3 and its addendum); issue spellbench#28.
This directory is the vertical slice of Section 9.1; results are in `evidence/README.md`.

## Layout

| Path | What |
|---|---|
| `core/src/spellbench/kit/core/` | kit-core, no XMage imports: the front process (`Front`, agent role over stdio), runner link (`RunnerLink`: deadlines, kill, confirmed exit, late-result discard, background restart), seeds (`Seeds`, Section 4.5), sampler (`Sampler`, Section 4), plans (`PlanBook`, Section 6.1), aggregation and fallback (`Aggregate`, Sections 5.5 and 6.5), observation comparison modulo ids (`ObsCompare`), and two XMage-free checks (`SliceCore`, `TerminationCheck`) |
| `xmage/src/spellbench/kit/xmage/` | kit-xmage: the runner process (`Runner`), world builder (`WorldBuilder`, `World`, `KitDuel`, `KitRandom`), deciders (`KitMad` for H1 and H2, `KitMcts` for H3, `Puppet` for the other seat), mapping back to v2 (`Mapping`, `Dialogs`, `Continuation`, `Resolver`), H3 knowledge (`KnowledgeWatcher`, `KitRedeal`), budgets (`KitContext`), diagnostics (`RoundTrip`) and the slice harness (`Slice`) |
| `xmage/src/mage/player/ai/` | XMage's MAD and MCTS plugins vendored at the pin (MIT; see `../NOTICE`), changed only where marked `KIT`; `KitPayPlayer` (the engine's deterministic autopay planner, for every kit player), `KitBudgets`, `KitNodes` |
| `xmage/src/mage/player/spellbench/{observe,decide}/KitBridge.java` | the shared library: the only places kit code reaches package-private engine overlay code (vocabulary, `ability_index`, cast `method`); everything else used from the overlay is public API (`ObservationBuilder`, `Observation`, `Look`, `Seats`, `Exchange`) |
| `xmage/e7/` | E7 reference probe (compiled only by `scripts/upstream.sh`, never on an entry's classpath) |
| `diffs/` | the published kit diffs of the vendored MAD and MCTS sources against the pin |
| `scripts/` | `agent.sh` (one agent process: front plus runner), `upstream.sh` (diffs and the E7 reference build) |
| `tests/` | `play.py` (kit games through P's host and live validator), `kitlog.py` (evidence-log summaries) |
| `evidence/` | slice results |

## Build

Against the engine's exact jars (decision K2), Java 8 source level:

```bash
engines/xmage/scripts/build.sh --out ENGINE --xmage-repo XMAGE    # the engine, unchanged
engines/xmage/kit/build.sh --engine-build ENGINE --out KIT        # KIT/lib/kit-core.jar, kit-xmage.jar, KIT-MANIFEST.json
```

## Run one agent

```bash
kit/scripts/agent.sh --kit KIT --engine-build ENGINE --db DB [--work DIR] --entry h1|h2|h3 [--worlds K] [--log FILE]
```

The front answers `hello` at once; at `game_start` it starts the runner (a child JVM with its own copy of the card
database, about 12 to 14 s to boot on HaleysPC) inside `game_start_ms`. Entries: `h1` (kit-wrapped MAD, one world),
`h2` (MAD, K-world vote, K = 4 by default), `h3` (kit-wrapped MCTS). Budgets: `--nodes`, `--options`,
`--operations`, `--iterations`, `--rollout`. Evidence options: `--log FILE` (one JSON line per decision with its tag
`bot`, `wrapper` or `cap`), `--roundtrip 1` (observation round-trip diagnostics, Section 7.2), `--dump DIR`
(priority-anchor decisions, for E7), `--hang-at N` (E3 test hook).

## Games through P's host

```bash
PYTHONPATH=P2/python python kit/tests/play.py --games 4 --out games.jsonl --kit-name kit-mad-k1-s6 \
  --kit-cmd '["bash", "kit/scripts/agent.sh", "--kit", ...]' --opponent heuristic -- ENGINE_COMMAND...
```

## Slice checks

```bash
java -cp KIT/lib/kit-core.jar spellbench.kit.core.SliceCore
java -cp KIT/lib/kit-core.jar spellbench.kit.core.TerminationCheck WORKDIR
java -cp "KIT/lib/kit-xmage.jar;KIT/lib/kit-core.jar;KIT/lib/kit-upstream.jar;ENGINE/lib/*" -Dkit.e7.dir=DUMPS \
  spellbench.kit.xmage.Slice OUT.jsonl [S1 S2 S3 S4 S5 S6 S7 S9 SENTINEL E2 E7MCTS E7MAD]   # in a directory with ./db
```
