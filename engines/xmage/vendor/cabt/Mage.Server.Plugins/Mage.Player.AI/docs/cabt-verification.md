# CABT adapter verification

One command runs the whole adapter suite from the repo root:

```sh
scripts/run-cabt-adapter-tests.sh
```

CI can call that script, or the equivalent Maven/Python commands below.

## Test layers

### Java unit + callback-boundary integration tests

```sh
mvn -pl Mage.Server.Plugins/Mage.Player.AI test
```

The module's test tree (`src/test/java/mage/player/cabt/`) contains only the
CABT adapter tests. Two layers live there:

- **Unit**: prompt builders, selection appliers, validators, serializers,
  the card-data exporter, and the dataset writer, each against stub games
  (`StubGames`) carrying real engine containers (Battlefield, Combat,
  GameState, ManaPool, ...).
- **Callback-boundary integration** (`CabtBridgePlayer*Test`): the exact
  `Player` callback the engine invokes (chooseTarget, playMana,
  selectAttackers, chooseMulligan, ...) driven end to end through
  controller → validation → applier → trace, asserting on real engine state
  afterwards.
- **Full-engine smoke games** (`CabtRealGameSmokeTest`): a real `GameImpl`
  runs its own loop — turns, priority, the stack, mana payment, combat
  steps, state-based actions — with both players driven through the bridge
  by an in-process policy controller. No stubs: real cards
  (`mage.cards.basiclands.Forest`, `mage.cards.g.GrizzlyBears`), a real
  mulligan phase, a real starting-player choice. Asserts that priority
  prompts carry engine-enumerated playable options, that selecting
  PLAY_LAND/CAST_SPELL changes actual hand/battlefield/stack state through
  the real mana-payment loop, and that own-hand cards resolve to real names
  in serialized observations.

The smoke game also emits a reviewable **artifact bundle** under
`target/cabt-smoke-run/`: `manifest.json`, `decklists.json`,
`observations.jsonl` (every prompt as seen), `transitions.jsonl`
(before/selected/after per decision with object-id zone moves and tap
changes as the delta), `timeline.html` (human-readable), `final-state.json`,
and `invariants.json` — machine-checked cross-file claims, each carrying the
transition sequence numbers that prove it (the selected PLAY_LAND card id is
the id that moved HAND → BATTLEFIELD, the cast spell's id resolved
STACK → BATTLEFIELD, the paid mana source tapped, zone moves chain per
object, the final battlefield agrees with the moves, opponent hands never
leak). The test fails if any artifact is missing or the invariants disagree.

Two more full-engine layers run the same loop through the session and
protocol boundaries:

- **`CabtGameSessionTest`**: the pull-based session API (start → events →
  validated selections → game over) driving a real game to its turn limit,
  plus invalid-selection recovery and unknown-card fail-closed checks.
- **`CabtProtocolServerTest`**: raw request lines through
  `CabtProtocolServer.handleLine` — exactly what a Python client sends —
  including a full game played from serialized observations alone, the
  hidden-hand boundary asserted on every observation, structured errors for
  invalid selections that leave the pending decision answerable, and
  fail-closed unknown/malformed commands.

### Card identity resolution

`CardResolver` resolves requested card names to real XMage cards
**repository-first**: it queries `CardRepository` (which knows every imported
card's canonical name, including split / adventure / modal cards and names
with punctuation the class-name transform mangles), retrying once after
conservative punctuation/whitespace normalization
(`CardNameNormalizer`), and only falls back to the legacy
`CabtDeckFactory` class-name heuristic when the repository has no match (a
test JVM with no scanned database). Resolution **fails closed**: an unknown
name is reported unresolved with diagnostics (requested name, normalized
name, strategy, canonical name, printing, reason), never substituted.

- **`CardNameNormalizerTest`**, **`CardResolverTest`**: pure/fake-repository
  branch tests — repository-first precedence, normalize-then-retry, heuristic
  fallback, fail-closed unknowns. Run in milliseconds with no database.
- **`CardIdentityRepositoryTest`**: the real regression layer, run against
  XMage's scanned card database (`CardScanner.scan()`). Resolves a realistic
  decklist (`Forest`, `Lightning Bolt`, `Llanowar Elves`,
  `Boseiju, Who Endures`, split `Fire // Ice`), the split card from a single
  half (`Fire` → `Fire // Ice`), a curly-apostrophe name via normalization,
  and unknown-card fail-closed; drives the `resolve_card` / `validate_deck` /
  `repository_card_data` protocol commands (all without an active game) and a
  repository-resolved `game_start`; and regenerates the Python fixtures
  (`validate_deck_response.json`, `repository_card_data_response.json`). When
  the set classes aren't on the classpath the database stays empty and this
  class skips via a JUnit assumption, like the Python live tests skip without
  a built bridge.
- **`CardResolverProductionScanTest`**: proves a fresh `CabtProtocolServer`
  resolves a repository-only name (`Boseiju, Who Endures`) through
  `resolve_card` **without the test scanning first** — the resolver scans the
  card database itself on its first lookup. Asserts `EXACT` + a set code (not
  the heuristic fallback), so a regression that drops the production-path scan
  fails here.

The protocol distinguishes two card-data scopes: `all_card_data` is the
active game's deduped deck pool (needs a game); `repository_card_data`
resolves a requested list of names through the repository and needs no game
(it is a by-name lookup, not a whole-database dump).

### Python unit tests

```sh
cd python && python3 -m unittest discover -s tests
```

Tests `magic_cabt` (card-data parsing, JSONL dataset reading, and the
`resolve_card` / `validate_deck` / `repository_card_data` client helpers via a
fake transport in `test_card_identity.py`) against fixtures that are **real
Java output**: `MagicCardDataExporterTest`, `CabtDatasetWriterTest`, and
`CardIdentityRepositoryTest` regenerate them under
`Mage.Server.Plugins/Mage.Player.AI/target/cabt-fixtures/` on every Java
run, and the script copies them over `python/tests/fixtures/` before the
Python layer runs — so a Java-side format change fails the Python tests in
the same script run.

### End-to-end protocol smoke tests

`python/tests/test_protocol_live.py` launches the real Java
`CabtProtocolServer` as a subprocess and plays a full game from Python
(greedy agent over `observation.select.option` indices), asserting the
hidden-hand boundary on every observation and the structured-error path for
invalid selections. It needs `MAGIC_CABT_CLASSPATH`; the script computes and
exports it (also written to
`Mage.Server.Plugins/Mage.Player.AI/target/cabt-classpath.full.txt` for
manual runs) once `mage.player.cabt.CabtProtocolServer` appears in the
module's compiled classes, then runs `python/tests/test_protocol*.py`.
Without the variable these tests skip.

The runnable example on top of the same stack:

```sh
MAGIC_CABT_CLASSPATH="$(cat Mage.Server.Plugins/Mage.Player.AI/target/cabt-classpath.full.txt)" \
    python3 examples/run_selfplay.py --seed 42 --max-turns 15
```

drives two random legal agents through a real game and writes a replay
(observations + selections + result) to `target/cabt-selfplay/replay.jsonl`.

## When a test fails, look here

| Failure | Likely task area |
| --- | --- |
| `SelectionValidatorTest`, `InvalidSelectionException` in many tests | Selection plumbing (Tasks 1–2) |
| `CabtPriorityPromptBuilderTest`, `CabtPrioritySelectionApplierTest`, `CabtBridgePlayerPriorityTest` | Priority playable options (getPlayable enumeration / activateAbility dispatch) |
| `CabtRealGameSmokeTest` | Full-engine integration: any bridge surface misbehaving against the real game loop |
| `CabtGameSessionTest` | Session layer: game-thread handoff, event ordering, validation-before-dispatch, deck construction |
| `CabtProtocolServerTest`, `python test_protocol_live` | Protocol boundary: request/response shapes, error codes, observation serialization over the wire |
| `CabtRealGameSmokeTest.smokeRunBundleIsGeneratedAndInternallyConsistent`, `invariants.json` with `"passed": false` | Smoke-run bundle inconsistency: read the failing check's evidence in `target/cabt-smoke-run/invariants.json`, then the named sequence in `transitions.jsonl` / `timeline.html` |
| `CabtDecisionTraceRecorderTest` | Decision trace lifecycle/sequence/error recording |
| `CabtBridgePlayerOverrideAuditTest` | A SURFACED/FAIL_CLOSED Player callback is no longer overridden by the bridge, or the audit drifted from the real Player interface |
| `CabtBridgePlayerCopyAndSimulationTest` | copy()/rollback sharing or the simulation fail-closed guard |
| `MagicObservation*Test`, `MagicObjectViewFactoryTest` | Public state serialization / hidden-info boundary (Task 6) |
| `CabtTargetPromptBuilderTest`, `CabtBridgePlayerTargetPromptTest` | Target prompts (Task 7) |
| `CabtYesNoPromptTest`, `CabtChoicePromptTest`, `CabtPilePromptTest` | Generic choice prompts (Task 8) |
| `CabtModePromptBuilderTest`, `CabtBridgePlayerModePromptTest` | Mode selection (Task 9) |
| `CabtNumberPromptTest`, `CabtMultiAmountPromptTest` | Numeric/X/multi-amount prompts (Task 10) |
| `CabtTriggeredAbility*Test` | Trigger ordering (Task 11) |
| `CabtReplacementEffect*Test` | Replacement-effect choice (Task 12) |
| `CabtManaPromptBuilderTest`, `CabtBridgePlayerManaPromptTest` | Mana payment (Task 13) |
| `CabtAttackers*Test`, `CabtBlockers*Test` | Combat declarations (Tasks 14–15) |
| `CabtMulliganPromptTest`, `CabtBridgePlayerMulliganTest` | Mulligan (Task 16) |
| `MagicCardDataExporterTest`, `python test_card_data` | Static card data export (Task 21) |
| `CardNameNormalizerTest`, `CardResolverTest` | Card-name normalization / resolver branch logic (repository-first, heuristic fallback, fail-closed) |
| `CardIdentityRepositoryTest`, `CardResolverProductionScanTest`, `python test_card_identity` | Repository-backed resolution, production-path DB scan, `resolve_card`/`validate_deck`/`repository_card_data` commands, deck validation before `game_start` |
| `CabtDatasetWriterTest`, `python test_dataset` | Dataset writer/reader (Task 22) |
| `CabtPromptAuditTest.allSurfacedPromptsHaveTests` | A surfaced prompt lost its implementation or test class — fix the audit entry or restore the class (Task 23) |
| `CabtPromptAuditTest.failClosedPromptsThrow...` | A FAIL_CLOSED callback stopped throwing `CabtUnhandledDecisionException` — a decision may be silently AI-decided (Task 23) |
| `CabtDecisionSurfaceAuditTest` | Audit drift: entry names/statuses no longer match the engine or bridge (Tasks 3, 23) |
| Python `test_card_data` passes locally but fails after the script's fixture refresh | The Java output format changed; update the Python parser or the Java shape together (Tasks 21–22) |

A prompt failing **in a real game** (a `CabtUnhandledDecisionException` in a
game log) means the engine hit a surface the bridge fails closed on — check
`CabtDecisionSurfaceAudit` for the callback's entry; its adapterPlan says
what is needed to surface it.

## Adding a new prompt surface

1. Add the audit entry in `CabtDecisionSurfaceAudit` (real engine signature,
   implementation class, test class).
2. Implement the builder/applier and the `CabtBridgePlayer` override.
3. Add the unit + callback-boundary tests named by the entry.

`CabtPromptAuditTest` fails until all three exist — that is the coverage
gate working as intended.
