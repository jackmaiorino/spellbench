# Protocol v2 Reference Stack and Arena (Sub-project P) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen Spellbench Protocol v2.0 in the Python reference stack and the arena: strict engine and host roles, lenient bots, the live validator, secrets and digests, clocks and adjudication, v2 goldens, and v2 runs through leaderboard, validate, bench and site.

**Architecture:** v2 is built beside v1 in new modules with permanent names (`messages.py`, `candidates.py`, `observation.py`, `bot.py`, `builtins/`, `host/`). The arena then switches in place (Task 33), the remaining tests migrate, and v1 protocol code is deleted (Task 44). `spellbench.host` plays one game (routing, validation, digest, clocks, adjudication); `spellbench.arena` runs tournaments (secrets, schedule, ledger, ratings, manifest). Committed v1 runs stay readable through a frozen legacy verifier.

**Tech Stack:** Python 3.11+ standard library only at runtime; pytest; uv (>= 0.11.29); git (commitment check).

**Spec:** `spec/SPELLBENCH_PROTOCOL_V2.md` (branch `board-program`, commit `7e9e73f`, frozen). Intent: `E:/spellbench-archive/program-research/protocol-v2-review.md` and `protocol-v2-rereview.md`. Program: `docs/design/2026-09-27-everyone-on-the-board.md`. Binding for launches: `C:/Users/Jack/COMPUTE-POLICY.md` and `C:/Users/Jack/IdeaProjects/collab/ARTIFACT-LAW.md`.

## Global Constraints

- The spec is binding and frozen: never edit `spec/SPELLBENCH_PROTOCOL_V2.md`. Where this plan interprets it, the Decisions section says so, and code comments cite the section ("spec 11.4").
- Runtime code is standard library only: `dependencies = []` stays empty; pytest is the only test dependency.
- No em-dash (U+2014) anywhere: code, comments, HTML copy, docs, commit messages. Name projects, not people. No attribution lines in commit messages.
- Protocol string `"spellbench/v2"`, `protocol_minor` 0. Integers `|x| <= 2^53 - 1`, integer literals only, nesting at most 64 levels, lines at most 8 MiB, `\r\n` tolerated on read.
- Engines and the host fail closed (unknown fields are `malformed_request`, except `x_[a-z0-9_]+` keys in `seat_decision.extensions`). Agents, and the host reading agent responses, are lenient (spec 4.2, 10).
- Canonical JSON is RFC 8785 through `wire.canonical_json_dumps` (keys ordered by UTF-16 code units; `"`, `\` and control characters escaped, `\u00xx` in lowercase hex). Every digest and every forwarded `seat_decision` goes through it.
- Published artifacts are deterministic given the run secret: no timestamps, no absolute or machine paths, sorted iteration, `\n` line endings. Wall-clock values (clocks, throughput trials) never enter hashed data files; they live only in the manifest's `allocation` block or in unhashed files (`diagnostics.jsonl`, `throughput.jsonl`).
- Secrets: a run secret or game secret is never logged, printed, or written before its run ends, except the run secret file kept outside the repository (Task 41). `RunSecret.__repr__` redacts.
- Hashed JSON artifacts go through `store.canonical_bytes` / `store.write_json_atomic`.
- Every committed run stays checkable: `spellbench validate` passes on every run under `benchmarks/*/runs/`, v1 included, at every task.
- Tests run from the repo root: `uv run pytest python/tests -q` (baseline at `7e9e73f`: 595 passed, 3 skipped). Every task ends with the whole suite green; the module-level skips Task 33 adds are the only exception, and each is removed by the task that migrates its module.
- Reserved features stay out (the probe, fixed-deck benchmarks, `pay_mana`, `narrow_name`, `narrow_number`, native-id extensions without an audit, resource enforcement), except that the host rejects reserved kinds in decisions, never sends `probe_resample` or `rules.probe: true`, and refuses `pairing: "fixed_deck"` with a "reserved in protocol v2.0" error.
- Out of scope: the mtg-kernel bridge v2 (K2) and the gorge adapter (G), apart from the interfaces they consume (listed below).

## Review Focus

1. A subprocess bot that prints a log line on stdout before `hello_ok` (common with ML libraries): preflight stops with a config error naming the bot and quoting nothing it printed; mid-run it is a `malformed_response` forfeit; the host never hangs. (Tests: Task 17, Task 39.)
2. Ctrl+C, or any exception, during a committed run: the run directory still gets a manifest with `status: "aborted"`, the games finished so far, and the revealed run secret, and the command exits nonzero. (Test: Task 33; validated in Task 36.)
3. An engine catalog whose card names are not NFC (for example NFD text from a macOS file system): preflight stops with a config error naming the card and the deck, before any game. (Tests: Task 9, Task 25.)
4. A bot on Windows: stdin decoded with the locale code page and `\r\n` line endings, receiving raw UTF-8 names such as "Lim-Dûl's Vault": the minimal bot and the reference bot server read bytes, and the host accepts `\r\n`. (Test: Task 6.)
5. The run secret never lands in the repository tree, with or without `SPELLBENCH_SECRETS_DIR`; a committed run that died before writing its manifest is published with `bench reveal`; a second run on the same date gets `-2`. (Test: Task 41.)

## Decisions (made under the standing authorization; the controller should check them)

1. **v1 runs stay readable.** A frozen verifier (`arena/legacy_v1.py`) re-validates v1 runs byte for byte, and the site keeps showing the latest committed v1 run of `pauper-kernel` (the launch run, or sub-project C's re-launch if it lands first), labelled "protocol v1, before the fairness contract", on its page and in the Hero, until K2 reruns the benchmark on v2. Why: the rerun needs the kernel bridge v2 (out of scope); without this, CI's run validation and Pages fail and the board is empty for the whole K2 period; and every committed number stays checkable. Cost: one frozen module of moved code; no v1 protocol code survives.
2. **Build beside, then switch.** v2 lives in new modules with permanent names; the arena switches in place in Task 33; arena tests that still speak v1 are skipped at module level from Task 33 until their migration task (37, 39, 40, 41, 42). CI's `spellbench site` step on the integration branch is red from Task 33 until Task 42; the branch merges to `board-program` only after Task 44.
3. **What "rated" means.** A v2 run is rated only if it completed, the validator verdict is `pass`, its commitment was pushed before the first game with a third-party timestamp reference, and its allocation was measured by the throughput guard. Everything else publishes as unrated. The site's board run is the latest rated v2 run, or the latest v1 run.
4. **Rewind accounting** (spec 8, re-review n1): the rewound priority action's own group and every group completed after it are abandoned (not counted in `decision_count`); `group_id` is never reused. The host checks terminal `step_count` and `decision_count` exactly; a mismatch halts the game with reason `host_engine_fault:terminal_counts`.
5. **Caps** (spec 11.4): "reaches" means the seat's count equals the cap; the host adjudicates right after that choice, before sending the step. The stalling window is the last 250 answered decisions, that one included.
6. **Invalid runs stop at once** (spec 11.3 allows it): the ledger is the schedule prefix through the violating game, whatever the worker count.
7. **Goldens carry digests in a sidecar**, `goldens/protocol_v2/index.json` (with each transcript's engine arguments and replay roles), so every transcript row keeps exactly the spec's `{"dir", "message"}` shape; the two `malformed_json` transcripts hold the offending line as a JSON string.
8. **Benchmarks fix their information rules**: opponent decklist `visible`, mulligan `auto` (London when the engine supports it, else `none`, per spec 12.2), `host_assigned` with `p0`, probe off. Config `base_seed` becomes `stats_seed` (bootstrap only). Builtins become 2.0.0 (new bot ids).
9. **Commit flow**: `bench commit` writes `runs/<name>/COMMITMENT.json` and keeps the secret under `~/.spellbench/run-secrets/` (override `SPELLBENCH_SECRETS_DIR`, never inside the repository); `bench run --run NAME --proof REF` checks with git that the commitment is in a pushed commit; a committed run that fails before its manifest is published as `REVEAL.json`. Preflight resets use host-internal HMAC labels of the run secret (`spellbench/v2/preflight-game:`, `spellbench/v2/preflight-id:`), never a scheduled game's secret.
10. **Launch guards**: the throughput guard runs in `bench run` and `spellbench run`; a rated benchmark run also requires `SPELLBENCH_PIN_ROOT` and `SPELLBENCH_ARTIFACT_REGISTER` (engine files pinned by SHA-256 and registered). The library `run_tournament` requires an `Allocation`; an `unmeasured` one makes the run unrated. Guarded launch paths after P: `spellbench bench run`, `spellbench run`; the library path is covered by the rated rule.
11. **Sub-project C is input, not a conflict.** C (in flight on `c-kernel-bots`) adds `integrations/mtg_kernel/` (a v1 bot), edits `test_engine_conformance.py`, CI and `benchmarks/pauper-kernel/benchmark.json`, and commits a v1 run. P keeps C's `SPELLBENCH_ENGINE_ARGS` (Task 32), migrates whatever `benchmark.json` holds, C's bots included (Task 37), validates every v1 run (Task 4), and skips C's kernel-bot tests at module level when it deletes v1 (Task 44): that bot speaks v1 and is ported by K2.

## Interfaces for K2 and G (produced here, consumed there)

- `goldens/protocol_v2/test_vectors.json` (Task 2): every spec 16 vector, machine readable, for Rust and Go unit tests of object ids and stream seeds.
- `goldens/protocol_v2/*.transcript.jsonl` and `goldens/protocol_v2/index.json` (Task 34): the reference behavior, including one transcript per engine error code.
- `uv run spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...] [--games N] -- ENGINE ARGV...` and `spellbench.conformance.check_engine(argv: Sequence[str], *, format: str, decks: Sequence[str], games: int = 4) -> ConformanceReport` (Task 32); the opt-in pytest wrapper `python/tests/test_engine_conformance.py` reads `SPELLBENCH_ENGINE_BIN`, `SPELLBENCH_ENGINE_ARGS` and `SPELLBENCH_ENGINE_DECKS`.
- `spellbench.host.validator.LiveValidator` with `VALIDATOR_VERSION = "spellbench-live-validator/2.0"`; halt reasons `host_validator:V1` to `host_validator:V10` (Task 22).
- `spellbench.run_secret.object_id(game_secret: bytes, message: str) -> str`, `id_key(game_secret: bytes) -> bytes`, `stream_seed(game_secret: bytes, label: str) -> bytes` (Task 2), as test oracles for adapter id and RNG code.
- `benchmark.json` v2 fields an engine benchmark sets (Task 37): `engine.name`, `engine.command` (with `${NAME}` placeholders), `deck_pool`, `extensions`, `native_id_audits`, `time_control`, `limits`, `resources`, `workers`.
- Python bots: `spellbench.bot.serve(...)` with the lenient views `spellbench.bot.Decision`, `Candidate`, `GameStart`, `GameOver` (Task 6), and `spellbench.builtins.uniform.SplitMix64` (Task 11). K2 ports C's `integrations/mtg_kernel/kernel_flat_bot.py` from `spellbench.agent_server.serve` and `spellbench.arena.bots.uniform.SplitMix64` to these.
- Launch path for a published run: `spellbench bench commit`, then `spellbench bench run BENCH --run NAME --proof REF --placement TEXT`, with the local values `SPELLBENCH_PIN_ROOT` and `SPELLBENCH_ARTIFACT_REGISTER` (Tasks 41, 43). The kernel adapter is expected as `agent_bridge_v2` (Annex A naming) behind `${MTG_KERNEL_BRIDGE}`.

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `python/spellbench/wire.py` | 1, 44 | strict JSON (bound, depth 64), RFC 8785 canonical JSON, framing, subprocess peer |
| `python/spellbench/_schema.py` (new) | 1 | shared strict validators and the protocol's closed name sets |
| `python/spellbench/run_secret.py` (new) | 2 | run secret, commitment, game secrets, opaque game ids, agent seeds, object ids, stream seeds |
| `python/spellbench/digests.py` (new) | 2 | deck ids, card-name domains, the per-game digest chain |
| `python/spellbench/host/clock.py` (new) | 3 | Fischer clock, per-seat caps, stalling window |
| `python/spellbench/arena/legacy_v1.py` (new) | 4, 20 | frozen v1 run reader and verifier |
| `python/spellbench/arena/throughput.py` (new) | 5 | throughput qualification, allocation record, idle monitor |
| `python/spellbench/bench/pinning.py` (new) | 5 | engine file hashing, pinning, artifact registration |
| `python/spellbench/bot.py` (new) | 6 | lenient agent-role server and bot-side views |
| `examples/minimal_bot.py` (new) | 6 | the spec 10.6 minimal bot, stdlib only |
| `python/spellbench/candidates.py` (new) | 7 | the 30 v2.0 kinds, vocabularies, constraints |
| `python/spellbench/observation.py` (new) | 8 | observation schema (spec 6) and reference walkers |
| `python/spellbench/messages.py` (new) | 9 | engine-role messages and shared protocol types |
| `python/spellbench/host/violation.py`, `host/tracking.py` (new) | 10 | `ValidatorViolation`; V3 and V7 state |
| `python/spellbench/builtins/` (new) | 11 | `uniform`, `heuristic`, `first` 2.0.0 |
| `python/spellbench/arena/ledger.py` (new) | 12 | ledger rows v2 |
| `python/tests/fake_v2_world.py` (new) | 13 | the fake engine's board model |
| `python/spellbench/host/refs.py`, `hidden.py`, `declarations.py` (new) | 14, 15, 16 | V2 V4 V6; V5; V8 V9 |
| `python/spellbench/agent_messages.py`, `host/agent_process.py`, `host/seat.py`, `host/setup.py` (new) | 17 | agent-role messages (host side), agent client, seat driver protocol, the per-game `GameSetup` record |
| `python/spellbench/host/engine_process.py` (new) | 18 | engine client |
| `python/spellbench/arena/config.py` (new) | 19 | tournament config v2 |
| `python/spellbench/arena/leaderboard.py` | 20 | pair slots, attribution, v1 and v2 documents |
| `python/tests/fake_v2_engine.py` (new) | 21 | the v2 fake engine |
| `python/spellbench/host/validator.py` (new) | 22 | `LiveValidator` (V1 to V10) |
| `python/spellbench/host/game.py` (new) | 23, 29 | one game: routing, validation, digest, clocks, caps, adjudication |
| `python/spellbench/arena/drivers.py` (new) | 24 | builtin and subprocess seat drivers |
| `python/spellbench/arena/schedule.py` (new) | 25 | preflight, schedule, per-game setup |
| `python/tests/fake_v2_scenario_*.py`, `fake_v2_knowledge.py` (new) | 26, 27 | kinds, board and knowledge tours |
| `python/tests/hostile_v2_engine.py`, `bot_v2_hostile.py` (new) | 28 | hostile participants |
| `python/spellbench/arena/executor.py` (new) | 30 | serial and parallel execution, schedule-order prefix |
| `python/spellbench/arena/manifest.py` (new) | 31 | manifest v2, information rules, validator record, rated rule |
| `python/spellbench/conformance.py` (new) | 32 | engine conformance runner |
| `python/spellbench/arena/runner.py`, `store.py`, `cli.py` | 33 (and 32, 41, 43) | the v2 tournament, v2 schemas, CLI |
| `python/tools/generate_goldens_v2.py`, `goldens/protocol_v2/` (new) | 2, 34 | golden transcripts, index and vectors |
| `python/spellbench/arena/validate.py` | 4, 36, 41 | dispatch v1 or v2 validation; revealed runs |
| `python/spellbench/bench/definition.py`, `benchmarks/pauper-kernel/benchmark.json` | 37 | benchmark schema v2 |
| `python/spellbench/site/render.py`, `site/build.py` | 38, 42 | v2 and legacy runs on the site |
| `python/spellbench/bench/commit.py` (new), `bench/run.py` | 41, 43 | commit, run, reveal, rerun, launch guards |
| deletions, `README.md`, CI, version | 44 | v1 removal and docs |

## Execution Notes (controller)

- One integration branch `protocol-v2` off `board-program`; one git worktree and branch per task; merge each wave before starting the next. Files within a wave are disjoint.
- Files shared across waves (never within one): `arena/cli.py` (Tasks 32, 33, 41, 43), `arena/runner.py` (20, 33, 43), `arena/store.py` (20, 33), `arena/legacy_v1.py` (4, 20), `arena/validate.py` (4, 36, 41), `host/game.py` (23, 29), `bench/run.py` (41, 43), `python/tests/test_engine_conformance.py` (32). `python/tests/fake_v2_engine.py` is written by Task 21 only; Tasks 26 and 27 add scenario modules it discovers.
- Created once: `host/__init__.py` (Task 3), `builtins/__init__.py` (Task 11), `goldens/protocol_v2/` (Task 2), `python/tests/tour_helpers.py` (Task 22).
- Task 33 inserts `import pytest` and `pytest.skip("protocol v1 test, migrated in Task N", allow_module_level=True)` right after `from __future__ import annotations` (before every other import, so the module's v1 imports never run) in each arena test module it breaks. Tasks 37, 39, 40, 41, 42 remove their skip; Task 44 asserts none remain.
- Shared test fixtures from Task 33 on live in `python/tests/arena_helpers.py`: `TEST_RUN_SECRET = RunSecret(bytes(range(32)))` (the spec 16 vector secret), `TEST_PROOF`, `small_allocation(workers)`, `run(config, *, rated=False)`.
- Sub-project C: when it merges into `board-program`, rebase `protocol-v2` on it at the next wave boundary. The rebase touches `test_engine_conformance.py` (take P's Task 32 version once it exists, keeping `SPELLBENCH_ENGINE_ARGS`), CI (keep C's `pytest python/tests integrations -q`), and `benchmarks/pauper-kernel/` (keep C's run and its definition until Task 37 migrates it).
- Compute: the suite's tournaments are small correctness checks, which COMPUTE-POLICY allows. No benchmark run is launched in this sub-project; the first v2 `pauper-kernel` run belongs to K2 and goes through the guarded `bench run`.

| Wave | Tasks (effort in agent-days) | Needs |
|---|---|---|
| 1 | 1 (0.5), 2 (0.5), 3 (0.5), 4 (0.5), 5 (0.5), 6 (0.5) | nothing |
| 2 | 7 (0.5), 8 (0.75), 9 (0.5), 10 (0.5), 11 (0.5), 12 (0.5), 13 (0.5) | wave 1 |
| 3 | 14 (0.5), 15 (0.5), 16 (0.5), 17 (0.75), 18 (0.5), 19 (0.5), 20 (0.5), 21 (0.75) | wave 2 |
| 4 | 22 (0.5) | 14, 15, 16, 18, 21 |
| 5 | 23 (0.75), 24 (0.5), 25 (0.5), 26 (0.75), 27 (0.5), 28 (0.5) | 22 and wave 3 |
| 6 | 29 (0.75), 30 (0.5), 31 (0.5), 32 (0.5) | wave 5 |
| 7 | 33 (0.75), 34 (0.75) | wave 6 |
| 8 | 35 (0.5), 36 (0.5), 37 (0.5), 38 (0.5) | 33, 34 |
| 9 | 39 (0.5), 40 (0.75), 41 (0.75), 42 (0.5) | 36, 37, 38 |
| 10 | 43 (0.5), 44 (0.5) | 41; 39, 40, 42 |

Total: 44 tasks, 24.5 agent-days. Critical path: Tasks 1, 8, 15, 22, 23, 29, 33, 36, 41, 43 = 6.25 agent-days (Tasks 14, 16 and 21 are equally long alternatives to 15); with the wave barriers the elapsed time is 6.5 days, with up to eight implementers in wave 3. Each task's heading repeats its effort, wave and direct dependencies. Task 44 runs beside Task 43 (disjoint files); the controller reruns Task 44's final checks once both have merged.

---

## Wave 1

### Task 1: Strict wire and RFC 8785 canonical JSON

**Effort:** 0.5 agent-day. **Wave:** 1. **Depends on:** nothing.

**Files:**
- Modify: `python/spellbench/wire.py` (`MAX_JSON_INT`, `_parse_int`, `strict_json_loads`, `_assert_canonical_tree`, `canonical_json_dumps`; keep `candidates_sha256` until Task 44)
- Create: `python/spellbench/_schema.py`
- Modify: `python/tests/test_wire.py`
- Create: `python/tests/test_schema.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `wire.MAX_JSON_INT = (1 << 53) - 1`, `wire.MAX_NESTING = 64`
  - `wire.strict_json_loads(line: bytes | str) -> dict[str, Any]`: raises `MalformedJsonError` with "outside |x| <= 2^53 - 1", "nesting deeper than 64 levels", or "lone surrogate" in the message.
  - `wire.canonical_json_dumps(value: Any) -> bytes`: RFC 8785 (keys by UTF-16 code units); raises `ValidationError` for floats, non-string keys, out-of-range integers, unencodable strings.
  - `_schema` closed name sets (the single source of truth; `candidates` and `observation` re-export them): `PRIORITY_KINDS = ("pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability", "special_action")`, `CHOICE_KINDS` (the 24 kinds of spec 7.3 in table order), `V2_KINDS = frozenset(PRIORITY_KINDS + CHOICE_KINDS)`, `RESERVED_KINDS = frozenset({"pay_mana", "narrow_name", "narrow_number"})`, `REQUIRED_KINDS = frozenset({"pass", "play_land", "cast_spell", "declare_attack", "declare_block"})`, `OBSERVATION_FLAGS` (the 13 flags of spec 6.9 in table order)
  - `_schema`: `U32_MAX`, `I32_MIN`, `I32_MAX`, `SAFE_INT_MAX`, `SEATS = ("p0", "p1")`, `ZONES`, `REFERENCE_FIELDS = ("object_id", "card_name", "owner_seat", "controller_seat", "zone")`, `SNAKE_CASE_RE`, `EXTENSION_KEY_RE`; `fail(context: str, detail: str) -> NoReturn`, `as_object(value, context) -> dict`, `exact_keys(value: Mapping, expected: Iterable[str], context) -> None`, `safe_int`, `u32`, `i32` (each `(value, context) -> int`), `boolean(value, context) -> bool`, `text(value, context) -> str`, `nonempty(value, context) -> str`, `nullable(value, check: Callable[[Any, str], T], context) -> T | None`, `array(value, context, *, min_length: int = 0, max_length: int | None = None) -> list`, `seat(value, context) -> str`, `vocab(value, allowed: Collection[str], context) -> str`, `snake(value, context) -> str`, `card_name(value, context) -> str` (nonempty, NFC), `object_ref(value, context) -> dict`, `target_ref(value, context) -> dict`. All raise `errors.ValidationError("<context>: <detail>")`.

- [ ] **Step 1: Write the failing tests**

In `python/tests/test_wire.py`: in `test_strict_loads_rejects`, replace the `2^53 + 1` pair with `b'{"a":9007199254740992}'` and `b'{"a":-9007199254740992}'` (now outside the bound); in `test_strict_loads_accepts_safe_int_bounds`, replace the two `1 << 53` rows with `(b"9007199254740991", (1 << 53) - 1)` and `(b"-9007199254740991", -((1 << 53) - 1))`; in `test_canonical_dumps_rejects_non_canonical_values`, replace `9007199254740993` with `9007199254740992`. Replace `test_strict_loads_rejects_a_lone_surrogate_nested_past_the_recursion_limit` (depth now fails first) and append:

```python
@pytest.mark.parametrize(
    ("opening", "innermost", "closing"),
    [(b"[", rb'"\ud800"', b"]"), (b'{"k":', rb'{"\ud800":0}', b"}")],
    ids=["value", "key"],
)
def test_deep_json_fails_on_depth_before_any_string_check(opening: bytes, innermost: bytes, closing: bytes) -> None:
    depth = 1500
    with pytest.raises(MalformedJsonError, match="nesting deeper than 64 levels"):
        wire.strict_json_loads(b'{"a":' + opening * depth + innermost + closing * depth + b"}")


def test_a_lone_surrogate_within_the_depth_limit_is_rejected() -> None:
    with pytest.raises(MalformedJsonError, match="lone surrogate"):
        wire.strict_json_loads(b'{"a":' + b"[" * 10 + rb'"\ud800"' + b"]" * 10 + b"}")


def _nested_objects(levels: int) -> bytes:
    return b'{"a":' * levels + b"0" + b"}" * levels


def test_nesting_of_64_levels_is_accepted_and_65_rejected() -> None:
    assert wire.strict_json_loads(_nested_objects(64))
    with pytest.raises(MalformedJsonError, match="nesting deeper than 64 levels"):
        wire.strict_json_loads(_nested_objects(65))


def test_canonical_escapes_follow_rfc_8785() -> None:
    value = {"s": "\x00\x08\x0c\n\r\t\x1f\x7f\u2028\"\\"}
    assert wire.canonical_json_dumps(value) == b'{"s":"\\u0000\\b\\f\\n\\r\\t\\u001f\x7f\xe2\x80\xa8\\"\\\\"}'


def test_canonical_keys_sort_by_utf16_code_units() -> None:
    # U+1F600 is the surrogate pair D83D DE00, which sorts before U+FFFD in UTF-16
    # (RFC 8785 section 3.2.3), although its code point is larger.
    assert wire.canonical_json_dumps({"\ufffd": 1, "\U0001F600": 2}) == b'{"\xf0\x9f\x98\x80":2,"\xef\xbf\xbd":1}'
    assert wire.canonical_json_dumps({"b": 1, "a": {"d": 1, "c": 2}}) == b'{"a":{"c":2,"d":1},"b":1}'


def test_canonical_dumps_matches_the_spec_16_vector() -> None:
    value = {"b": "Chainer's Edict", "a": "Lim-D\u00fbl's Vault", "c": "tab\there"}
    assert hashlib.sha256(wire.canonical_json_dumps(value)).hexdigest() == (
        "041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377"
    )


def test_canonical_dumps_rejects_a_lone_surrogate_string() -> None:
    with pytest.raises(ValidationError, match="lone surrogate"):
        wire.canonical_json_dumps({"a": "x\ud800"})
```

Create `python/tests/test_schema.py`:

```python
"""Shared strict validators of the v2 modules."""

from __future__ import annotations

import pytest

from spellbench import _schema as s
from spellbench.errors import ValidationError

BOLT = {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0",
        "controller_seat": "p0", "zone": "hand"}


def test_object_ref_accepts_the_spec_example_and_a_hidden_name() -> None:
    assert s.object_ref(BOLT, "ref") == BOLT
    assert s.object_ref({**BOLT, "card_name": None}, "ref")["card_name"] is None


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"extra": 1}, "fields mismatch"),
        ({"zone": "deck"}, "zone"),
        ({"owner_seat": "p2"}, "p0 or p1"),
        ({"card_name": "Lim-Du\u0302l's Vault"}, "not in Unicode NFC"),
        ({"object_id": ""}, "nonempty"),
    ],
)
def test_object_ref_rejects(edit: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        s.object_ref({**BOLT, **edit}, "ref")


def test_target_ref_is_exactly_one_of_player_or_object() -> None:
    assert s.target_ref({"player": "p1"}, "t") == {"player": "p1"}
    assert s.target_ref({"object": BOLT}, "t") == {"object": BOLT}
    for bad in ({}, {"player": "p1", "object": BOLT}, {"player": None}):
        with pytest.raises(ValidationError):
            s.target_ref(bad, "t")


def test_integers_check_type_before_range() -> None:
    with pytest.raises(ValidationError, match="integer"):
        s.u32(True, "n")
    with pytest.raises(ValidationError):
        s.u32(1 << 32, "n")
    with pytest.raises(ValidationError):
        s.safe_int(1 << 53, "n")
    assert s.i32(-(1 << 31), "n") == -(1 << 31)


def test_vocab_rejects_unhashable_values_as_validation_errors() -> None:
    with pytest.raises(ValidationError):
        s.vocab([], frozenset({"red"}), "color")


def test_closed_name_sets() -> None:
    assert len(s.PRIORITY_KINDS) == 6 and len(s.CHOICE_KINDS) == 24 and len(s.V2_KINDS) == 30
    assert s.REQUIRED_KINDS <= s.V2_KINDS and not s.RESERVED_KINDS & s.V2_KINDS
    assert s.OBSERVATION_FLAGS[0] == "poison" and s.OBSERVATION_FLAGS[-1] == "known_cards" and len(s.OBSERVATION_FLAGS) == 13


def test_snake_case_and_card_names() -> None:
    assert s.snake("time_lord", "x") == "time_lord"
    with pytest.raises(ValidationError):
        s.snake("Time-Lord", "x")
    assert s.card_name("Lim-D\u00fbl's Vault", "x")
    with pytest.raises(ValidationError, match="NFC"):
        s.card_name("Lim-Du\u0302l's Vault", "x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_wire.py python/tests/test_schema.py -q`
Expected: FAIL: `ModuleNotFoundError: spellbench._schema`, 2^53 accepted, depth 65 accepted, the UTF-16 order test gets code point order.

- [ ] **Step 3: Implement**

In `wire.py`, set `MAX_JSON_INT = (1 << 53) - 1`, add `MAX_NESTING = 64`, change the `_parse_int` message to `f"JSON integer outside |x| <= 2^53 - 1: {quoted}"` (only the bound text changes), and replace the surrogate walk with one iterative walk:

```python
def _encodable(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MalformedJsonError("string contains a lone surrogate escape") from exc


def _check_tree(value: Any, *, check_strings: bool) -> None:
    """Nesting at most MAX_NESTING levels (the top-level object is level 1); strings encodable.

    Iterative: json accepts nesting deeper than the interpreter's recursion limit.
    """
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, (dict, list)):
            if depth > MAX_NESTING:
                raise MalformedJsonError(f"JSON nesting deeper than {MAX_NESTING} levels")
            children = item.values() if isinstance(item, dict) else item
            if check_strings and isinstance(item, dict):
                for key in item:
                    _encodable(key)
            pending.extend((child, depth + 1) for child in children)
        elif check_strings and isinstance(item, str):
            _encodable(item)
```

`strict_json_loads` calls `_check_tree(value, check_strings=bool(_SURROGATE_ESCAPE.search(line)))` after the top-level object check, and turns a `RecursionError` from `json.loads` into the same `"JSON nesting deeper than 64 levels"` message, so the depth error reads the same whichever layer finds it. For canonical output:

```python
def _assert_canonical_tree(value: Any) -> bool:
    """Validate a tree for canonical output; True when some key holds a non-BMP character."""
    astral = False
    pending: list[tuple[Any, str]] = [(value, "$")]
    while pending:
        item, context = pending.pop()
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if abs(item) > MAX_JSON_INT:
                raise ValidationError(f"{context} integer outside |x| <= 2^53 - 1: {item}")
        elif type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValidationError(f"{context} string contains a lone surrogate") from exc
        elif isinstance(item, list):
            pending.extend((child, f"{context}[{index}]") for index, child in enumerate(item))
        elif isinstance(item, dict):
            for key, child in item.items():
                if type(key) is not str:
                    raise ValidationError(f"{context} has a non-string key: {key!r}")
                pending.append((key, f"{context} key"))
                astral = astral or any(ord(char) > 0xFFFF for char in key)
                pending.append((child, f"{context}.{key}"))
        else:
            raise ValidationError(f"{context} is not canonical JSON: {type(item).__name__}")
    return astral


def _dumps_utf16(value: Any) -> str:
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _dumps_utf16(value[key]) for key in keys) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_dumps_utf16(child) for child in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def canonical_json_dumps(value: Any) -> bytes:
    """RFC 8785 (spec 4.3): keys by UTF-16 code units, compact, integers only, raw UTF-8.

    json's escaping already matches RFC 8785 (short escapes for \\b \\f \\n \\r \\t,
    lowercase \\u00xx for other control characters, nothing else escaped). Code
    point order equals UTF-16 order unless a key holds a non-BMP character.
    """
    if _assert_canonical_tree(value):
        return _dumps_utf16(value).encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
```

Create `python/spellbench/_schema.py` with the closed name sets (copied from the tables of spec 6.9, 7.2 and 7.3) and the helpers listed under Interfaces. Each helper checks the Python type first (`type(value) is int`, never `isinstance`, so `True` is not an integer; a list is never tested for membership). `object_ref` calls `exact_keys` with `REFERENCE_FIELDS`, then `nonempty(object_id)`, `nullable(card_name, card_name)`, `seat` twice, `vocab(zone, ZONES)`, and returns the input dict. `card_name` fails with `"<context>: card name {value!r} is not in Unicode NFC"` when `unicodedata.is_normalized("NFC", value)` is false. `target_ref` accepts exactly `{"player": seat}` or `{"object": object_ref}`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_wire.py python/tests/test_schema.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass (v1 code keeps working under the tighter bound).

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/wire.py python/spellbench/_schema.py python/tests/test_wire.py python/tests/test_schema.py
git commit -m "Wire: 2^53 - 1 bound, 64-level nesting, RFC 8785 key order; shared v2 validators"
```

### Task 2: Run secrets, deck and domain ids, and the game digest

**Effort:** 0.5 agent-day. **Wave:** 1. **Depends on:** nothing.

**Files:**
- Create: `python/spellbench/run_secret.py`
- Create: `python/spellbench/digests.py`
- Create: `goldens/protocol_v2/test_vectors.json`
- Create: `python/tests/test_run_secret.py`, `python/tests/test_digests.py`

**Interfaces:**
- Consumes: `wire.canonical_json_dumps` (exists; Task 1 refines it, and every vector here has ASCII keys).
- Produces:
  - `run_secret.RUN_SECRET_BYTES = 32`; `class RunSecret` (frozen, `value: bytes`, redacting `__repr__`): `generate() -> RunSecret`, `from_hex(text: str) -> RunSecret`, `hex() -> str`, `commitment() -> str`, `game_secret(index: int) -> bytes`, `game_id(index: int) -> str`, `agent_seed(index: int, seat: str) -> int`, `preflight_secret(index: int) -> bytes`, `preflight_game_id(index: int) -> str`
  - `run_secret.id_key(game_secret: bytes) -> bytes`, `object_id(game_secret: bytes, message: str) -> str`, `stream_seed(game_secret: bytes, label: str) -> bytes`
  - `digests.deck_rows(decklist: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]`, `deck_id(decklist) -> str`, `domain_id(names: Sequence[str]) -> str`, `card_name_domain(names: Iterable[str]) -> dict[str, Any]` (`{"domain_id", "names"}`, names sorted and unique)
  - `digests.GAME_DIGEST_DOMAIN = b"spellbench/v2/game-digest"`; `class GameDigest(reset_request: Mapping)` with `add_response(response: Mapping) -> None` (the answer to `reset`), `add_step(request: Mapping, response: Mapping | None) -> None`, `add_adjudication(*, classification: str, outcome: str, reason: str, winner: str | None) -> None`, `chain_hex() -> str`, `value() -> str` (`"sha256:" + hex`)
  - `goldens/protocol_v2/test_vectors.json`: one canonical JSON line, schema `"spellbench-test-vectors/v2"`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_run_secret.py`:

```python
"""Run secrets and derived values: the spec 16 test vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spellbench.run_secret import RunSecret, id_key, object_id, stream_seed

VECTOR = RunSecret(bytes(range(32)))
VECTORS_FILE = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2" / "test_vectors.json"


def test_run_secret_vectors() -> None:
    assert VECTOR.commitment() == "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd"
    assert VECTOR.game_secret(0).hex() == "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e"
    assert VECTOR.game_secret(1).hex() == "952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e"
    assert (VECTOR.game_id(0), VECTOR.game_id(1)) == ("g-f67d7fe78c792984", "g-bb341404cf686511")
    assert (VECTOR.agent_seed(0, "p0"), VECTOR.agent_seed(0, "p1")) == (8103969398531465, 1382627979884484)
    assert (VECTOR.agent_seed(1, "p0"), VECTOR.agent_seed(1, "p1")) == (4616060983342951, 7705961899067306)


def test_object_id_and_stream_vectors() -> None:
    game0 = VECTOR.game_secret(0)
    assert id_key(game0).hex() == "842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6"
    assert object_id(game0, "p0:card-17:z2") == "o-0a3647243d16bf78"
    assert object_id(game0, "p1:card-17:z2") == "o-e5e4b7ed2a0730e4"
    assert object_id(game0, "p0:card-17:z2:look:0") == "o-794a5cb152c9620f"
    assert object_id(game0, "p0:card-17:z2:look:1") == "o-e18a35822cc60e1c"
    assert stream_seed(game0, "spellbench/v2/rng:p1:library_shuffle:0")[:8].hex() == "8a28fd4db75719b1"


def test_the_two_games_of_a_pair_never_share_a_secret_and_preflight_is_separate() -> None:
    secrets = {VECTOR.game_secret(index) for index in range(200)}
    assert len(secrets) == 200
    assert VECTOR.preflight_secret(0) not in secrets
    assert VECTOR.preflight_game_id(0) not in {VECTOR.game_id(index) for index in range(200)}


def test_secrets_never_print() -> None:
    assert "000102" not in repr(VECTOR) and "000102" not in str(VECTOR)


@pytest.mark.parametrize("bad", ["00" * 31, "0g" * 32, "AB" * 32])
def test_from_hex_is_strict(bad: str) -> None:
    with pytest.raises(ValueError):
        RunSecret.from_hex(bad)


def test_generated_secrets_are_fresh() -> None:
    assert RunSecret.generate() != RunSecret.generate()


def test_the_vectors_file_matches_the_implementation() -> None:
    raw = VECTORS_FILE.read_bytes()
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    vectors = json.loads(raw)
    secret = RunSecret.from_hex(vectors["run_secret"])
    assert vectors["commitment"] == secret.commitment()
    for index, value in vectors["game_secret"].items():
        assert secret.game_secret(int(index)).hex() == value
    for index, value in vectors["game_id"].items():
        assert secret.game_id(int(index)) == value
    for key, value in vectors["agent_seed"].items():
        index, seat = key.split(":")
        assert secret.agent_seed(int(index), seat) == value
    game0 = secret.game_secret(0)
    assert id_key(game0).hex() == vectors["id_key_game_0"]
    for message, value in vectors["object_id_game_0"].items():
        assert object_id(game0, message) == value
    for label, value in vectors["stream_seed_game_0_first_8_bytes"].items():
        assert stream_seed(game0, label)[:8].hex() == value
```

Create `python/tests/test_digests.py`:

```python
"""Host-computed identifiers and the game digest chain (spec 4.3, 11.8)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.digests import GAME_DIGEST_DOMAIN, GameDigest, card_name_domain, deck_id, deck_rows, domain_id
from spellbench.errors import ValidationError

BURN = [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]
VECTORS = json.loads((Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2" / "test_vectors.json").read_bytes())


def test_deck_and_domain_vectors() -> None:
    assert deck_id(BURN) == "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2"
    assert deck_id(list(reversed(BURN))) == deck_id(BURN)  # rows are sorted by name first
    assert domain_id(["Lightning Bolt", "Mountain"]) == (
        "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697"
    )
    assert card_name_domain(["Mountain", "Lightning Bolt", "Mountain"]) == {
        "domain_id": domain_id(["Lightning Bolt", "Mountain"]),
        "names": ["Lightning Bolt", "Mountain"],
    }


@pytest.mark.parametrize(
    ("decklist", "message"),
    [
        ([], "nonempty"),
        ([{"name": "Mountain", "count": 0}], "count"),
        ([{"name": "Mountain", "count": 1}, {"name": "Mountain", "count": 2}], "twice"),
        ([{"name": "Lim-Du\u0302l's Vault", "count": 1}], "NFC"),
        ([{"name": "Mountain", "count": 1, "set": "M21"}], "exactly"),
    ],
)
def test_deck_rows_are_strict(decklist: list, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        deck_rows(decklist)


def test_first_chain_value_matches_the_spec_vector() -> None:
    reset = VECTORS["first_digest_chain_value"]["reset"]
    assert GameDigest({**reset, "request_id": "h-2"}).chain_hex() == VECTORS["first_digest_chain_value"]["d"]
    assert VECTORS["first_digest_chain_value"]["d"] == "a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3"


def _manual(reset: dict, *messages: dict) -> str:
    d = hashlib.sha256(GAME_DIGEST_DOMAIN + wire.canonical_json_dumps(reset)).digest()
    for message in messages:
        d = hashlib.sha256(d + wire.canonical_json_dumps(message)).digest()
    return "sha256:" + d.hex()


def test_chain_order_strips_request_ids_and_chains_a_retransmission_once() -> None:
    reset = {"request_type": "reset", "request_id": "h-2", "game_id": "g-1"}
    first = {"response_type": "decision", "request_id": "h-2", "step": 0}
    step = {"request_type": "step", "request_id": "h-3", "expected_step": 0}
    done = {"response_type": "terminal", "request_id": "h-3", "outcome": "draw"}
    digest = GameDigest(reset)
    digest.add_response(first)
    digest.add_step(step, done)
    digest.add_step(step, done)  # the identical retransmission and its cached response
    strip = lambda message: {key: value for key, value in message.items() if key != "request_id"}
    assert digest.value() == _manual(strip(reset), strip(first), strip(step), strip(done))


def test_an_adjudication_is_appended_once() -> None:
    reset = {"request_type": "reset", "request_id": "h-2"}
    digest = GameDigest(reset)
    digest.add_adjudication(classification="forfeit", outcome="p1_win", reason="forfeit:timeout", winner="p1")
    record = {"adjudication": {"classification": "forfeit", "outcome": "p1_win", "reason": "forfeit:timeout", "winner": "p1"}}
    assert digest.value() == _manual({"request_type": "reset"}, record)
    with pytest.raises(ValueError):
        digest.add_adjudication(classification="halted", outcome="halted", reason="x", winner=None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_run_secret.py python/tests/test_digests.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: spellbench.run_secret` (and the vectors file missing).

- [ ] **Step 3: Implement**

`python/spellbench/run_secret.py` (constructions verbatim from spec 11.6 and 5.3; `decimal(i)` is `str(i)` with a nonnegative `int`):

```python
"""Run secrets and everything derived from them (spec 11.6, 5.3, 16).

The module is not called ``secrets`` so it never shadows the standard library.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

RUN_SECRET_BYTES = 32
_LOW_53_BITS = (1 << 53) - 1


def _hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def _decimal(index: int) -> bytes:
    if type(index) is not int or index < 0:
        raise ValueError("a game index is a nonnegative integer")
    return str(index).encode("ascii")


@dataclass(frozen=True, repr=False)
class RunSecret:
    value: bytes

    def __post_init__(self) -> None:
        if type(self.value) is not bytes or len(self.value) != RUN_SECRET_BYTES:
            raise ValueError("a run secret is exactly 32 bytes")

    def __repr__(self) -> str:
        return "RunSecret(<redacted>)"

    __str__ = __repr__

    @classmethod
    def generate(cls) -> "RunSecret":
        return cls(secrets.token_bytes(RUN_SECRET_BYTES))

    @classmethod
    def from_hex(cls, text: str) -> "RunSecret":
        if type(text) is not str or len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("a run secret is 64 lowercase hex characters")
        return cls(bytes.fromhex(text))

    def hex(self) -> str:
        return self.value.hex()

    def commitment(self) -> str:
        return hashlib.sha256(self.value).hexdigest()

    def game_secret(self, index: int) -> bytes:
        return _hmac(self.value, b"spellbench/v2/game:" + _decimal(index))

    def game_id(self, index: int) -> str:
        return "g-" + _hmac(self.value, b"spellbench/v2/game-id:" + _decimal(index))[:8].hex()

    def agent_seed(self, index: int, seat: str) -> int:
        if seat not in ("p0", "p1"):
            raise ValueError("seat must be p0 or p1")
        digest = _hmac(self.value, b"spellbench/v2/agent-seed:" + _decimal(index) + b":" + seat.encode("ascii"))
        return int.from_bytes(digest[:8], "big") & _LOW_53_BITS

    # Host-internal (not in the spec): the preflight resets of spec 11.1 never use a scheduled game's secret.
    def preflight_secret(self, index: int) -> bytes:
        return _hmac(self.value, b"spellbench/v2/preflight-game:" + _decimal(index))

    def preflight_game_id(self, index: int) -> str:
        return "g-" + _hmac(self.value, b"spellbench/v2/preflight-id:" + _decimal(index))[:8].hex()


def id_key(game_secret: bytes) -> bytes:
    return _hmac(game_secret, b"spellbench/v2/object-id")


def object_id(game_secret: bytes, message: str) -> str:
    """The recommended object id of spec 5.3 for message ``"<viewer>:<internal key>[:look:<n>]"``."""
    return "o-" + _hmac(id_key(game_secret), message.encode("utf-8"))[:8].hex()


def stream_seed(game_secret: bytes, label: str) -> bytes:
    """The recommended stream seed of spec 11.6 for label ``"spellbench/v2/rng:<seat or shared>:<purpose>:<n>"``."""
    return _hmac(game_secret, label.encode("ascii"))
```

`python/spellbench/digests.py`: `deck_rows` requires a nonempty list of rows, each exactly `{name, count}`, name nonempty and NFC (`unicodedata.is_normalized`), count an integer in `[1, 2^32 - 1]`, names distinct ("appears twice"); returns `{"count", "name"}` rows sorted by name. `deck_id` and `domain_id` are `"sha256:" + sha256(canonical_json_dumps(...))`, `domain_id` over the sorted distinct NFC names. `GameDigest`:

```python
def _minus_request_id(message: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != "request_id"}


class GameDigest:
    """SHA-256 chain over one game's engine traffic (spec 11.8); agent traffic never enters it."""

    def __init__(self, reset_request: Mapping[str, Any]) -> None:
        self._d = hashlib.sha256(GAME_DIGEST_DOMAIN + canonical_json_dumps(_minus_request_id(reset_request))).digest()
        self._last_request: tuple[str, bytes] | None = None
        self._last_answered = False
        self._adjudicated = False

    def _chain(self, message: Mapping[str, Any]) -> None:
        self._d = hashlib.sha256(self._d + canonical_json_dumps(_minus_request_id(message))).digest()

    def add_response(self, response: Mapping[str, Any]) -> None:
        self._chain(response)

    def add_step(self, request: Mapping[str, Any], response: Mapping[str, Any] | None) -> None:
        key = (request["request_id"], canonical_json_dumps(request))
        if key == self._last_request:  # a retransmission and its cached response are chained once
            if not self._last_answered and response is not None:
                self._chain(response)
                self._last_answered = True
            return
        self._last_request, self._last_answered = key, response is not None
        self._chain(request)
        if response is not None:
            self._chain(response)

    def add_adjudication(self, *, classification: str, outcome: str, reason: str, winner: str | None) -> None:
        if self._adjudicated:
            raise ValueError("a game has at most one adjudication record")
        self._adjudicated = True
        self._chain({"adjudication": {"classification": classification, "outcome": outcome,
                                      "reason": reason, "winner": winner}})

    def chain_hex(self) -> str:
        return self._d.hex()

    def value(self) -> str:
        return "sha256:" + self._d.hex()
```

Write `goldens/protocol_v2/test_vectors.json` as one canonical line (`wire.canonical_json_line`) of:

```python
{
    "schema": "spellbench-test-vectors/v2",
    "run_secret": bytes(range(32)).hex(),
    "commitment": "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd",
    "game_secret": {"0": "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e",
                    "1": "952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e"},
    "game_id": {"0": "g-f67d7fe78c792984", "1": "g-bb341404cf686511"},
    "agent_seed": {"0:p0": 8103969398531465, "0:p1": 1382627979884484, "1:p0": 4616060983342951, "1:p1": 7705961899067306},
    "id_key_game_0": "842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6",
    "object_id_game_0": {"p0:card-17:z2": "o-0a3647243d16bf78", "p1:card-17:z2": "o-e5e4b7ed2a0730e4",
                         "p0:card-17:z2:look:0": "o-794a5cb152c9620f", "p0:card-17:z2:look:1": "o-e18a35822cc60e1c"},
    "stream_seed_game_0_first_8_bytes": {"spellbench/v2/rng:p1:library_shuffle:0": "8a28fd4db75719b1"},
    "deck_id": {"decklist": [{"count": 4, "name": "Lightning Bolt"}, {"count": 18, "name": "Mountain"}],
                "deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2"},
    "domain_id": {"names": ["Lightning Bolt", "Mountain"],
                  "domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697"},
    "canonical_sha256": {"value": {"a": "Lim-D\u00fbl's Vault", "b": "Chainer's Edict", "c": "tab\there"},
                         "sha256": "041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377"},
    "first_digest_chain_value": {
        "reset": {
            "request_type": "reset", "protocol": "spellbench/v2", "game_id": "g-f67d7fe78c792984", "format": "pauper-bo1",
            "seats": [
                {"seat": "p0", "deck": {"deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2",
                                        "catalog_id": "Burn"}},
                {"seat": "p1", "deck": {"deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2",
                                        "catalog_id": "Burn"}},
            ],
            "rules": {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
                      "starting_seat": "p0", "extensions": [], "probe": False,
                      "card_name_domain": {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697",
                                           "names": ["Lightning Bolt", "Mountain"]}},
            "game_secret": "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e",
            "max_decisions": 10000, "max_steps": 100000,
        },
        "d": "a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3",
    },
}
```

These are the spec 16 values, all recomputed while writing this plan; the reset is the spec 9.2 example without `request_id`. The tests recompute each one, so a typo fails.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_run_secret.py python/tests/test_digests.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/run_secret.py python/spellbench/digests.py goldens/protocol_v2/test_vectors.json python/tests/test_run_secret.py python/tests/test_digests.py
git commit -m "Run secrets, deck and domain ids, and the per-game digest chain"
```

### Task 3: Clocks, seat caps and the stalling window

**Effort:** 0.5 agent-day. **Wave:** 1. **Depends on:** nothing.

**Files:**
- Create: `python/spellbench/host/__init__.py` with exactly one line: `"""The protocol host for one game: routing, validation, clocks and adjudication (spec 11)."""`
- Create: `python/spellbench/host/clock.py`
- Create: `python/tests/test_host_clock.py`

**Interfaces:**
- Consumes: nothing.
- Produces (`spellbench.host.clock`):
  - `STALLING_WINDOW = 250`; `CAP_NAMES = ("max_seat_decisions_per_turn", "max_seat_decisions_per_game", "max_seat_steps_per_game")`
  - `class SeatClock(bank_ms: int, increment_ms: int, max_decision_ms: int)` with `remaining_ms: int`, `budget_ms() -> int`, `charge(elapsed_ms: int) -> bool`
  - `class SeatCaps(*, per_turn: int, groups_per_game: int, steps_per_game: int)` with `record(seat: str, *, turn: int, completed_group: bool) -> str | None` (the cap name reached, or None)
  - `is_real_choice(candidate_count: int, chosen_kind: str) -> bool`
  - `CapRuling(kind: str, loser_seat: str | None)` (`kind` is `"forfeit"` or `"draw"`); `class StallingWindow(size: int = STALLING_WINDOW)` with `record(seat: str, *, real_choice: bool) -> None`, `ruling(capped_seat: str) -> CapRuling`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_clock.py`:

```python
"""Fischer clock, per-seat caps and stalling adjudication (spec 11.4)."""

from __future__ import annotations

from spellbench.host.clock import CapRuling, SeatCaps, SeatClock, StallingWindow, is_real_choice


def test_the_clock_charges_then_adds_the_increment() -> None:
    clock = SeatClock(bank_ms=1000, increment_ms=200, max_decision_ms=600)
    assert clock.budget_ms() == 600
    assert clock.charge(500) and clock.remaining_ms == 700
    assert clock.charge(600) and clock.remaining_ms == 300   # exactly the cap is allowed
    assert clock.budget_ms() == 300                          # the bank is now the tighter limit
    assert not clock.charge(301)                             # over the remaining bank: a timeout
    assert not SeatClock(bank_ms=10_000, increment_ms=0, max_decision_ms=100).charge(101)


def test_each_cap_is_reached_at_equality() -> None:
    caps = SeatCaps(per_turn=3, groups_per_game=100, steps_per_game=100)
    assert [caps.record("p0", turn=1, completed_group=True) for _ in range(2)] == [None, None]
    assert caps.record("p0", turn=1, completed_group=True) == "max_seat_decisions_per_turn"
    fresh = SeatCaps(per_turn=3, groups_per_game=100, steps_per_game=100)
    assert fresh.record("p0", turn=1, completed_group=True) is None
    assert fresh.record("p0", turn=2, completed_group=True) is None   # a new turn resets the per-turn count
    assert fresh.record("p1", turn=2, completed_group=True) is None   # seats count separately


def test_game_caps_count_groups_and_steps_separately() -> None:
    caps = SeatCaps(per_turn=1000, groups_per_game=2, steps_per_game=5)
    assert caps.record("p1", turn=1, completed_group=False) is None
    assert caps.record("p1", turn=2, completed_group=True) is None
    assert caps.record("p1", turn=3, completed_group=True) == "max_seat_decisions_per_game"
    steps = SeatCaps(per_turn=1000, groups_per_game=1000, steps_per_game=2)
    steps.record("p0", turn=1, completed_group=False)
    assert steps.record("p0", turn=1, completed_group=False) == "max_seat_steps_per_game"


def test_real_choices_are_non_pass_selections_among_several() -> None:
    assert is_real_choice(2, "activate_ability")
    assert not is_real_choice(2, "pass")
    assert not is_real_choice(1, "cast_spell")


def test_stalling_rulings() -> None:
    window = StallingWindow()
    for _ in range(10):
        window.record("p0", real_choice=False)
        window.record("p1", real_choice=False)
    assert window.ruling("p0") == CapRuling(kind="draw", loser_seat=None)   # a mandatory loop
    window.record("p1", real_choice=True)
    assert window.ruling("p0") == CapRuling(kind="forfeit", loser_seat="p1")
    window.record("p0", real_choice=True)
    assert window.ruling("p0") == CapRuling(kind="forfeit", loser_seat="p0")  # a tie: the capped seat


def test_the_window_is_the_last_250_decisions_of_either_seat() -> None:
    window = StallingWindow()
    window.record("p1", real_choice=True)
    for _ in range(250):
        window.record("p0", real_choice=False)
    assert window.ruling("p0").kind == "draw"   # p1's real choice fell out of the window
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_clock.py -q`
Expected: FAIL with `ModuleNotFoundError: spellbench.host`.

- [ ] **Step 3: Implement `host/clock.py`**

```python
"""Per-seat clocks, caps and the stalling window (spec 11.4).

Times are integer milliseconds measured by the caller; nothing here reads a clock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

STALLING_WINDOW = 250
CAP_NAMES = ("max_seat_decisions_per_turn", "max_seat_decisions_per_game", "max_seat_steps_per_game")


@dataclass
class SeatClock:
    bank_ms: int
    increment_ms: int
    max_decision_ms: int
    remaining_ms: int = field(init=False)

    def __post_init__(self) -> None:
        self.remaining_ms = self.bank_ms

    def budget_ms(self) -> int:
        return min(self.max_decision_ms, self.remaining_ms)

    def charge(self, elapsed_ms: int) -> bool:
        """Subtract one decision's time, then add the increment; False when it was a timeout."""
        if elapsed_ms > self.max_decision_ms or elapsed_ms > self.remaining_ms:
            return False
        self.remaining_ms = self.remaining_ms - elapsed_ms + self.increment_ms
        return True


class SeatCaps:
    def __init__(self, *, per_turn: int, groups_per_game: int, steps_per_game: int) -> None:
        self._limits = dict(zip(CAP_NAMES, (per_turn, groups_per_game, steps_per_game)))
        self._turn: dict[str, int | None] = {"p0": None, "p1": None}
        self._counts = {seat: dict.fromkeys(CAP_NAMES, 0) for seat in ("p0", "p1")}

    def record(self, seat: str, *, turn: int, completed_group: bool) -> str | None:
        """Count one answered decision; the name of the cap it reaches (count equals cap), or None."""
        counts = self._counts[seat]
        if self._turn[seat] != turn:
            self._turn[seat] = turn
            counts["max_seat_decisions_per_turn"] = 0
        counts["max_seat_decisions_per_turn"] += 1
        counts["max_seat_steps_per_game"] += 1
        if completed_group:
            counts["max_seat_decisions_per_game"] += 1
        for name in CAP_NAMES:
            if counts[name] >= self._limits[name]:
                return name
        return None


def is_real_choice(candidate_count: int, chosen_kind: str) -> bool:
    return candidate_count >= 2 and chosen_kind != "pass"


@dataclass(frozen=True)
class CapRuling:
    kind: str
    loser_seat: str | None


class StallingWindow:
    def __init__(self, size: int = STALLING_WINDOW) -> None:
        self._entries: deque[tuple[str, bool]] = deque(maxlen=size)

    def record(self, seat: str, *, real_choice: bool) -> None:
        self._entries.append((seat, real_choice))

    def ruling(self, capped_seat: str) -> CapRuling:
        real = {"p0": 0, "p1": 0}
        for seat, choice in self._entries:
            real[seat] += choice
        if real["p0"] == real["p1"] == 0:
            return CapRuling(kind="draw", loser_seat=None)
        if real["p0"] == real["p1"]:
            return CapRuling(kind="forfeit", loser_seat=capped_seat)
        return CapRuling(kind="forfeit", loser_seat="p0" if real["p0"] > real["p1"] else "p1")
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_clock.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/__init__.py python/spellbench/host/clock.py python/tests/test_host_clock.py
git commit -m "Host: Fischer clock, seat caps and the stalling window"
```

### Task 4: The legacy v1 read path

**Effort:** 0.5 agent-day. **Wave:** 1. **Depends on:** nothing.

**Files:**
- Create: `python/spellbench/arena/legacy_v1.py`
- Modify: `python/spellbench/arena/validate.py` (the body moves into `legacy_v1`)
- Create: `python/tests/test_legacy_v1.py`

**Interfaces:**
- Consumes: `store` IO helpers (`read_json`, `read_jsonl`, `verify_file_digests`, `canonical_bytes`, `require_keys`, `is_published`, `MANIFEST_NAME`, `CONFIG_NAME`, `REGISTRY_NAME`, `LEDGER_NAME`, `LEADERBOARD_JSON_NAME`, `LEADERBOARD_MD_NAME`, `DATA_FILE_NAMES`), `registry.read_registry`, `leaderboard.build_leaderboard`. Nothing from `models`, `runner`, `arena.bots`, or the v1 clients: this module must survive their deletion.
- Produces:
  - `legacy_v1.LEGACY_ARENA_VERSION = "0.2.0"`, `TOURNAMENT_SCHEMA_V1 = "spellbench-tournament/v1"`, `LEDGER_SCHEMA_V1 = "spellbench-match-ledger/v1"`, `CONFIG_SCHEMA_V1 = "spellbench-tournament-config/v1"`, `LEADERBOARD_SCHEMA_V1 = "spellbench-leaderboard/v1"`
  - `validate_v1_run(directory: Path) -> list[str]` (exactly today's `validate_tournament_dir` behavior and messages)
  - `LegacyLedgerRow` (today's `store.LedgerRow` fields and checks, plus property `pair_slot -> int` returning `game_index`)
  - `@dataclass(frozen=True) class LegacyRun: name: str; config: dict[str, Any]; engine: dict[str, Any]; owners: dict[str, str]; board: dict[str, Any]; deck_labels: tuple[str, ...]; pairs_per_deck: int; format: str`
  - `read_v1_run(directory: Path) -> LegacyRun`
  - `validate.validate_tournament_dir(directory: Path) -> list[str]` now delegates to `legacy_v1.validate_v1_run` (Task 36 adds the v2 branch).

Background: this is a move, not a rewrite. Copy verbatim from commit `7e9e73f`, renamed with a `_v1` suffix where they would clash: from `models.py` the helpers `_fail`, `_keys`, `_int`, `_u32`, `_u64`, `_nonempty_str`, `_str`, `_seat`, `_optional_seat`, `_list` and the classes `Provenance`, `EngineIdentity`, `DeckRow`, `Deck`; from `arena/store.py` `LedgerSeat`, `Adjudication`, `LedgerRow` (as `LegacyLedgerRow`), `FORFEIT_CAUSES`, `parse_ledger`; from `arena/runner.py` `BotSpec` (without `registry_entry`), `_bot_spec_from_json`, `TournamentConfig.from_json` (as `LegacyConfig`, keeping only the fields `manifest_body` and the schedule read), `derive_game_seed`, `matchup_indexes`, `_schedule`, `schedule_mismatches`, `manifest_body`, `SEED_SCHEDULE_VERSION`; from `arena/bots/uniform.py` `SplitMix64` and its constants. The builtin version table is frozen as `_V1_BUILTIN_VERSIONS = {"first": "1.0.0", "heuristic": "1.0.0", "uniform": "1.0.0"}`; the v1 bootstrap limit checks keep reading `ratings.MAX_PAIR_COUNT` and `ratings.MAX_BOOTSTRAP_DRAWS`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_legacy_v1.py`:

```python
"""The committed protocol v1 run stays checkable after v1 code is gone."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from spellbench.arena import legacy_v1, store
from spellbench.arena.validate import validate_tournament_dir

REPO = Path(__file__).resolve().parents[2]
LAUNCH_RUN = REPO / "benchmarks" / "pauper-kernel" / "runs" / "2026-09-26"
# Every committed v1 run, including any that sub-project C commits before P merges.
V1_RUNS = sorted(path.parent for path in REPO.glob("benchmarks/*/runs/*/manifest.json")
                 if b'"schema":"spellbench-tournament/v1"' in path.read_bytes())


@pytest.mark.parametrize("run", V1_RUNS, ids=lambda path: f"{path.parents[1].name}/{path.name}")
def test_every_committed_v1_run_validates_through_the_legacy_path(run: Path) -> None:
    assert legacy_v1.validate_v1_run(run) == []
    assert validate_tournament_dir(run) == []


def test_a_tampered_v1_run_fails(tmp_path: Path) -> None:
    copy = tmp_path / "run"
    shutil.copytree(LAUNCH_RUN, copy)
    ledger = copy / "matches.jsonl"
    ledger.write_bytes(ledger.read_bytes().replace(b'"reason":"game_over"', b'"reason":"game over"', 1))
    failures = legacy_v1.validate_v1_run(copy)
    assert any("digest mismatch: matches.jsonl" in failure for failure in failures)


def test_read_v1_run_gives_the_site_what_it_shows() -> None:
    run = legacy_v1.read_v1_run(LAUNCH_RUN)
    assert run.name == "2026-09-26" and run.format == "pauper-bo1"
    assert run.deck_labels == ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
    assert run.pairs_per_deck == 4
    assert run.engine["name"] == "mtg-kernel" and run.board["status"] == "ok"
    assert run.owners == {"uniform": "spellbench", "heuristic": "spellbench", "first": "spellbench"}


def test_ledger_rows_expose_the_pair_slot() -> None:
    rows = legacy_v1.parse_ledger(store.read_jsonl(LAUNCH_RUN / "matches.jsonl", schema=legacy_v1.LEDGER_SCHEMA_V1))
    assert [row.pair_slot for row in rows[:2]] == [0, 1]


def test_the_legacy_module_imports_no_protocol_v1_code() -> None:
    tree = ast.parse(Path(legacy_v1.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not {"models", "runner", "bots", "engine_client", "agent_client", "agent_server"} & (imported | names)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_legacy_v1.py -q`
Expected: FAIL at collection: `cannot import name 'legacy_v1'`.

- [ ] **Step 3: Move the v1 verifier**

Create `legacy_v1.py` from the copies listed in Background. `validate_v1_run` is today's `validate_tournament_dir` body with `store.TOURNAMENT_SCHEMA`, `store.CONFIG_SCHEMA`, `store.LEDGER_SCHEMA` replaced by the `_V1` constants, `runner.TournamentConfig` by `LegacyConfig`, `store.parse_ledger` by the local `parse_ledger`, `runner.schedule_mismatches` and `runner.manifest_body` by the local copies, and `models.EngineIdentity` by the local copy. Keep the arena version gate exactly (it compares with `spellbench.__version__`, so its message is unchanged); a v1 run is recomputed only when its version equals `LEGACY_ARENA_VERSION`. `read_v1_run` reads a run that `validate_v1_run` accepted: `name=directory.name`, the recorded config JSON, `manifest["engine"]`, owners from the registry by name, `leaderboard.json`, deck labels (a catalog id, or `"decklist " + sha256(canonical deck)[:12]`, in pool order; a fixed pair reads `"<p0>"` or `"<p0> vs <p1>"`), `pairs_per_matchup // len(deck_pool)` (or `pairs_per_matchup` for a fixed pair), and the format.

Replace `validate.py` with:

```python
"""Re-verify a published tournament directory from its files alone."""

from __future__ import annotations

from pathlib import Path

from . import legacy_v1


def validate_tournament_dir(directory: Path) -> list[str]:
    """Re-verify a published tournament; returns the failures (empty means OK).

    Protocol v1 runs (schema spellbench-tournament/v1) go to the frozen legacy
    verifier; the v2 verifier arrives with the v2 arena.
    """
    return legacy_v1.validate_v1_run(directory)
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_legacy_v1.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass (every existing validate test now runs through the legacy path with unchanged messages).

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/legacy_v1.py python/spellbench/arena/validate.py python/tests/test_legacy_v1.py
git commit -m "Arena: frozen legacy verifier and reader for protocol v1 runs"
```

### Task 5: Launch guard cores: throughput and pinning

**Effort:** 0.5 agent-day. **Wave:** 1. **Depends on:** nothing.

**Files:**
- Create: `python/spellbench/arena/throughput.py`
- Create: `python/spellbench/bench/pinning.py`
- Create: `python/tests/test_throughput.py`, `python/tests/test_pinning.py`

**Interfaces:**
- Consumes: nothing.
- Produces (`spellbench.arena.throughput`):
  - `SMALL_RUN_SECONDS = 120`, `PROBE_GAMES = 2`, `QUALIFY_GAMES_PER_WORKER = 2`, `ALLOCATION_KINDS = ("small", "substantial", "unmeasured")`, `class ThroughputError(Exception)`
  - `@dataclass(frozen=True) class Trial: workers: int; games: int; seconds_milli: int; outputs_digest: str` with `to_json()`
  - `@dataclass(frozen=True) class Allocation: kind: str; workers: int; host: str; cpu_count: int; per_game_cores: int; probe: Trial | None = None; trials: tuple[Trial, ...] = (); projected_serial_seconds: int | None = None; placement: str | None = None; outputs_identical: bool | None = None` with property `measured -> bool`, `to_json() -> dict`, `from_json(value) -> Allocation` (strict keys), `unmeasured(workers: int, *, cpu_count: int | None = None, per_game_cores: int = 1, host: str | None = None) -> Allocation`
  - `resource_bound(cpu_count: int, per_game_cores: int) -> int`, `worker_ladder(cap: int) -> tuple[int, ...]`
  - `plan_allocation(*, games_total: int, cap: int, per_game_cores: int, play: Callable[[int, int], tuple[float, str]], placement: str | None, cpu_count: int | None = None, host: str | None = None) -> Allocation` where `play(workers, games)` plays the first `games` scheduled games with `workers` workers under a throwaway secret and returns `(wall seconds, outputs digest)`
  - `class IdleMonitor(slots: int, *, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic)` with `tick(*, running: int, queued: int) -> str | None`
- Produces (`spellbench.bench.pinning`):
  - `class PinningError(Exception)`; `@dataclass(frozen=True) class EngineFile: index: int; file_name: str; sha256: str; bytes: int; path: Path` (`path` excluded from comparison and `to_json()`)
  - `engine_files(command: Sequence[str]) -> tuple[EngineFile, ...]`, `pin_files(files: Sequence[EngineFile], pin_root: Path) -> tuple[Path, ...]`, `register_pins(register_script: Path, pinned: Sequence[Path], *, owner: str, purpose: str, doc: str, regen: str, python: str = sys.executable) -> None`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_throughput.py`:

```python
"""The useful-compute guard (COMPUTE-POLICY.md): probe, scaling comparison, selection."""

from __future__ import annotations

import pytest

from spellbench.arena.throughput import (
    Allocation, IdleMonitor, ThroughputError, plan_allocation, resource_bound, worker_ladder,
)


def _player(per_game_seconds: float, speedup: dict[int, float], digest: str = "sha256:" + "0" * 64):
    calls: list[tuple[int, int]] = []

    def play(workers: int, games: int) -> tuple[float, str]:
        calls.append((workers, games))
        return games * per_game_seconds / speedup.get(workers, 1.0), digest

    return play, calls


def test_a_fast_schedule_is_small_and_keeps_the_resource_bounded_workers() -> None:
    play, calls = _player(0.5, {})
    allocation = plan_allocation(games_total=96, cap=4, per_game_cores=1, play=play, placement=None, cpu_count=24, host="h")
    assert (allocation.kind, allocation.workers, allocation.projected_serial_seconds) == ("small", 4, 48)
    assert calls == [(1, 2)] and allocation.measured


def test_a_substantial_schedule_compares_worker_counts_on_identical_games() -> None:
    play, calls = _player(10.0, {2: 1.9, 4: 3.5, 8: 3.4})
    allocation = plan_allocation(games_total=192, cap=8, per_game_cores=3, play=play, placement="this PC; HaleysPC idle but slower",
                                 cpu_count=24, host="h")
    assert calls == [(1, 2), (1, 16), (2, 16), (4, 16), (8, 16)]   # probe, then the ladder on the same 16 games
    assert allocation.kind == "substantial" and allocation.workers == 4 and allocation.outputs_identical
    assert allocation.to_json()["placement"] == "this PC; HaleysPC idle but slower"


def test_a_substantial_run_needs_a_placement_note() -> None:
    play, _ = _player(10.0, {})
    with pytest.raises(ThroughputError, match="placement"):
        plan_allocation(games_total=192, cap=8, per_game_cores=3, play=play, placement=None, cpu_count=24, host="h")


def test_outputs_that_change_with_the_worker_count_are_refused() -> None:
    digests = iter(["sha256:" + "0" * 64, "sha256:" + "0" * 64, "sha256:" + "1" * 64])
    with pytest.raises(ThroughputError, match="changed the results"):
        plan_allocation(games_total=192, cap=2, per_game_cores=1, play=lambda w, g: (g * 10.0, next(digests)),
                        placement="x", cpu_count=24, host="h")


def test_resources_bound_the_ladder() -> None:
    assert resource_bound(24, 3) == 8 and resource_bound(2, 3) == 1
    assert worker_ladder(8) == (1, 2, 4, 8) and worker_ladder(6) == (1, 2, 4, 6) and worker_ladder(1) == (1,)


def test_an_unmeasured_allocation_round_trips_and_is_not_measured() -> None:
    allocation = Allocation.unmeasured(2, cpu_count=4, host="h")
    assert not allocation.measured and Allocation.from_json(allocation.to_json()) == allocation


def test_the_idle_monitor_warns_after_two_idle_windows() -> None:
    now = [0.0]
    monitor = IdleMonitor(4, window_s=60.0, clock=lambda: now[0])
    warnings = []
    for second in range(0, 181, 10):
        now[0] = float(second)
        warnings.append(monitor.tick(running=2, queued=5))
    assert [w for w in warnings if w] and "idle" in [w for w in warnings if w][0]
    busy = IdleMonitor(4, window_s=60.0, clock=lambda: now[0])
    assert all(busy.tick(running=4, queued=5) is None for _ in range(3))
```

Create `python/tests/test_pinning.py`:

```python
"""Engine files pinned by hash and registered (ARTIFACT-LAW.md clauses 4 and 9)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from spellbench.bench.pinning import PinningError, engine_files, pin_files, register_pins


def test_engine_files_hash_the_parts_that_name_files(tmp_path: Path) -> None:
    script = tmp_path / "engine.py"
    script.write_bytes(b"print('engine')\n")
    files = engine_files([sys.executable, str(script), "--flag"])
    assert [(file.index, file.file_name) for file in files] == [(0, Path(sys.executable).name), (1, "engine.py")]
    assert files[1].sha256 == hashlib.sha256(b"print('engine')\n").hexdigest()
    assert files[1].to_json() == {"index": 1, "file_name": "engine.py", "sha256": files[1].sha256, "bytes": 16}


def test_pinning_is_idempotent_and_detects_a_tampered_pin(tmp_path: Path) -> None:
    source = tmp_path / "bridge.exe"
    source.write_bytes(b"binary")
    (file,) = engine_files([str(source)])
    root = tmp_path / "pins"
    (pinned,) = pin_files([file], root)
    assert pinned == root / file.sha256 and (pinned / "bridge.exe").read_bytes() == b"binary"
    assert pin_files([file], root) == (pinned,)
    (pinned / "bridge.exe").write_bytes(b"tampered")
    with pytest.raises(PinningError, match="does not match"):
        pin_files([file], root)


def test_registration_calls_the_register_script(tmp_path: Path) -> None:
    log = tmp_path / "calls.json"
    script = tmp_path / "register.py"
    script.write_text(f"import json, sys\nopen({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n", encoding="utf-8")
    register_pins(script, [tmp_path / "pins" / "abc"], owner="spellbench", purpose="engine of run x", doc="manifest.json", regen="cargo build")
    (call,) = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert call[:3] == ["add", "--path", str(tmp_path / "pins" / "abc")]
    assert ["--retention", "keep-full"] == call[call.index("--retention"):call.index("--retention") + 2]


def test_a_failing_register_script_is_an_error(tmp_path: Path) -> None:
    script = tmp_path / "register.py"
    script.write_text("import sys\nsys.exit('catalog locked')\n", encoding="utf-8")
    with pytest.raises(PinningError, match="catalog locked"):
        register_pins(script, [tmp_path], owner="spellbench", purpose="p", doc="d", regen="r")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_throughput.py python/tests/test_pinning.py -q`
Expected: FAIL at collection (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`throughput.py` (module docstring: the probe, the small threshold, the scaling comparison on identical inputs, the placement note, and that trials are wall-clock evidence kept only in the manifest):

```python
def resource_bound(cpu_count: int, per_game_cores: int) -> int:
    """Games that fit at once when each needs ``per_game_cores`` declared cores (spec 11.4); at least 1."""
    return max(1, cpu_count // max(1, per_game_cores))


def worker_ladder(cap: int) -> tuple[int, ...]:
    ladder, workers = [], 1
    while workers < cap:
        ladder.append(workers)
        workers *= 2
    return tuple(ladder + [cap])


def plan_allocation(*, games_total, cap, per_game_cores, play, placement, cpu_count=None, host=None) -> Allocation:
    cpu = (os.cpu_count() or 1) if cpu_count is None else cpu_count
    name = (platform.node() or "unknown") if host is None else host
    bound = min(cap, resource_bound(cpu, per_game_cores))
    probe_games = min(PROBE_GAMES, games_total)
    seconds, digest = play(1, probe_games)
    probe = Trial(1, probe_games, round(seconds * 1000), digest)
    projected = math.ceil(seconds / probe_games * games_total)
    common = dict(host=name, cpu_count=cpu, per_game_cores=per_game_cores, probe=probe,
                  projected_serial_seconds=projected, placement=placement)
    if projected <= SMALL_RUN_SECONDS:
        return Allocation(kind="small", workers=bound, **common)
    if not placement:
        raise ThroughputError(
            f"a substantial run (projected {projected} s serial) needs a placement note: which machines "
            "(this PC, HaleysPC, RunPod) were considered and why this one (COMPUTE-POLICY.md)"
        )
    ladder = worker_ladder(bound)
    games = min(games_total, QUALIFY_GAMES_PER_WORKER * ladder[-1])
    trials = tuple(Trial(w, games, round(s * 1000), d) for w in ladder for s, d in [play(w, games)])
    if len({trial.outputs_digest for trial in trials}) != 1:
        raise ThroughputError("worker counts changed the results of identical games; refusing to parallelize")
    best = max(trials, key=lambda trial: (trial.games / max(trial.seconds_milli, 1), -trial.workers))
    return Allocation(kind="substantial", workers=best.workers, trials=trials, outputs_identical=True, **common)
```

`Allocation.to_json()` writes every field (`probe` and each trial through `Trial.to_json()`, `trials` as a list); `from_json` checks the exact key set and the kinds, and rebuilds the tuple. `IdleMonitor` keeps the start of the current window and whether any tick in it saw `running < slots and queued > 0`; when a tick crosses the window end it counts consecutive idle windows, and at two it resets and returns `"idle capacity: fewer than {slots} games ran while games were queued for two consecutive {window_s:.0f} s windows"`.

`pinning.py`: `engine_files` resolves part 0 with `shutil.which` when it is a bare name, keeps the parts that are existing regular files, and hashes them in 1 MiB chunks. `pin_files` writes each file to `<pin_root>/<sha256>/<file_name>` through a `.tmp` copy, re-hashes before `os.replace`, and on an existing pin re-hashes it and raises `PinningError(f"pinned file {path} does not match sha256 {sha256}")` on a mismatch. `register_pins` runs, for each pinned directory, `[python, str(register_script), "add", "--path", str(directory), "--lane", "spellbench", "--owner", owner, "--status", "live", "--retention", "keep-full", "--purpose", purpose, "--doc", doc, "--regen", regen]` with `capture_output=True`, and raises `PinningError` with the last 200 characters of stderr on a nonzero exit (the script is the collab `tools/artifact_register.py`, or anything with its CLI).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_throughput.py python/tests/test_pinning.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/throughput.py python/spellbench/bench/pinning.py python/tests/test_throughput.py python/tests/test_pinning.py
git commit -m "Launch guards: throughput qualification and engine pinning cores"
```

### Task 6: The bot server and the minimal bot

**Effort:** 0.5 agent-day. **Wave:** 1. **Depends on:** nothing.

**Files:**
- Create: `python/spellbench/bot.py`
- Create: `examples/minimal_bot.py`
- Create: `python/tests/test_bot_server.py`, `python/tests/test_minimal_bot.py`

**Interfaces:**
- Consumes: `wire.strict_json_loads`, `wire.canonical_json_line`, `wire.read_line`.
- Produces (`spellbench.bot`):
  - `PROTOCOL = "spellbench/v2"`
  - `@dataclass(frozen=True) class Candidate: candidate_id: int; semantic: dict[str, Any]; display_text: str | None`
  - `@dataclass(frozen=True) class Decision: game_id: str; candidates: tuple[Candidate, ...]; acting_seat: str | None; seat_step: int | None; observation: dict; context: dict; group: dict; extensions: dict; clock: dict; raw: dict` with `from_request(request: Mapping) -> Decision` (raises `ValueError` when the candidates are unusable)
  - `@dataclass(frozen=True) class GameStart: game_id: str; seat: str | None; format: str | None; own_deck: dict | None; opponent_deck: dict | None; rules: dict; engine: dict; engine_profile: dict; time_control: dict; limits: dict; resources: dict; agent_seed: int | None; raw: dict` with `from_request(request) -> GameStart`
  - `@dataclass(frozen=True) class GameOver: game_id: str; terminal: dict; raw: dict` with `from_request(request) -> GameOver`
  - `class BotSession(*, choose: Callable[[Decision], int], on_game_start: Callable[[GameStart], None] | None = None, on_game_over: Callable[[GameOver], None] | None = None, name: str, version: str, requires_observation: Sequence[str] = (), requires_extensions: Sequence[str] = (), extensions_accepted: Sequence[str] = ())` with `handle_line(line: bytes) -> bytes`
  - `serve(handler: Any = None, *, choose=None, on_game_start=None, on_game_over=None, name: str = "spellbench-bot", version: str = "0.0.0", requires_observation=(), requires_extensions=(), extensions_accepted=(), stdin=None, stdout=None) -> int`

Behavior (spec 4.1, 4.2, 10): ignore unknown fields everywhere; answer `hello` with `{"response_type": "hello_ok", "protocol", "request_id", "bot": {"name", "version"}, "requires": {"observation": [...], "extensions": [...]}, "extensions_accepted": [...]}`; `game_start` while a game is active is `game_already_active`, else `ack`; `choose` or `game_over` naming no active game is `unknown_game`; a `choose` whose `decision.candidates` is not a nonempty list of objects with integer `candidate_id` is `malformed_request`; a handler exception or a returned id that was not offered is `internal_error`; `choice` carries only `selection.candidate_id`; unparseable lines are `malformed_json` with `request_id` `""`; a missing or non-string `request_id` is `malformed_request` with `""`; a missing or non-string `protocol` is `malformed_request`; any other string is `protocol_mismatch`; an unknown `request_type` is `malformed_request`. After `game_over` the game is over even when `on_game_over` raises (that answer is `internal_error`). There is no retransmission cache and no `decision_pending` (the server answers each line before reading the next).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_bot_server.py`:

```python
"""The reference bot server: lenient reading, the minimal contract, the agent error codes."""

from __future__ import annotations

import io
import json

import pytest

from spellbench import wire
from spellbench.bot import BotSession, Decision, serve

PASS = {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}
LAND = {"candidate_id": 1, "semantic": {"kind": "play_land", "face": 0, "source": {}}, "display_text": "Play Mountain"}


def _request(kind: str, request_id: str, **fields) -> bytes:
    return wire.canonical_json_dumps({"request_type": kind, "protocol": "spellbench/v2", "request_id": request_id, **fields})


def _answer(session: BotSession, line: bytes) -> dict:
    out = session.handle_line(line)
    assert out.endswith(b"\n")
    return json.loads(out)


def _session(choose=lambda decision: decision.candidates[-1].candidate_id) -> BotSession:
    return BotSession(choose=choose, name="t", version="1", requires_observation=("keywords",))


def _started(session: BotSession) -> None:
    assert _answer(session, _request("game_start", "r-1", game_id="g-1", seat="p0", agent_seed=7))["response_type"] == "ack"


def test_hello_declares_the_bot_and_its_requirements() -> None:
    answer = _answer(_session(), _request("hello", "r-0", protocol_minor=0, x_future=1))
    assert answer == {"response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "r-0",
                      "bot": {"name": "t", "version": "1"},
                      "requires": {"observation": ["keywords"], "extensions": []}, "extensions_accepted": []}


def test_choose_reads_leniently_and_answers_only_the_candidate_id() -> None:
    session = _session()
    _started(session)
    decision = {"acting_seat": "p0", "candidates": [PASS, LAND], "x_unknown": {"a": 1}}
    answer = _answer(session, _request("choose", "r-2", game_id="g-1", decision=decision, clock={}, extra=[1]))
    assert answer == {"response_type": "choice", "protocol": "spellbench/v2", "request_id": "r-2",
                      "selection": {"candidate_id": 1}}


@pytest.mark.parametrize(
    ("line", "code", "request_id"),
    [
        (b"{not json", "malformed_json", ""),
        (b'{"request_type":"hello","protocol":"spellbench/v2"}', "malformed_request", ""),
        (b'{"request_type":"hello","request_id":"r-0"}', "malformed_request", "r-0"),
        (b'{"request_type":"hello","protocol":"spellbench/v1","request_id":"r-0"}', "protocol_mismatch", "r-0"),
        (b'{"request_type":"dance","protocol":"spellbench/v2","request_id":"r-0"}', "malformed_request", "r-0"),
    ],
)
def test_envelope_errors(line: bytes, code: str, request_id: str) -> None:
    answer = _answer(_session(), line)
    assert (answer["response_type"], answer["error"]["code"], answer["request_id"]) == ("error", code, request_id)


def test_game_state_errors() -> None:
    session = _session()
    assert _answer(session, _request("choose", "r-1", game_id="g-1", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"
    _started(session)
    assert _answer(session, _request("game_start", "r-2", game_id="g-2"))["error"]["code"] == "game_already_active"
    assert _answer(session, _request("choose", "r-3", game_id="g-9", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"
    assert _answer(session, _request("choose", "r-4", game_id="g-1", decision={"candidates": []}))["error"]["code"] == "malformed_request"
    assert _answer(session, _request("game_over", "r-5", game_id="g-1", terminal={}))["response_type"] == "ack"
    assert _answer(session, _request("choose", "r-6", game_id="g-1", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"


@pytest.mark.parametrize("choose", [lambda d: 5, lambda d: "0", lambda d: 1 / 0])
def test_a_bad_handler_answer_is_an_internal_error(choose) -> None:
    session = _session(choose)
    _started(session)
    answer = _answer(session, _request("choose", "r-2", game_id="g-1", decision={"candidates": [PASS]}))
    assert answer["error"]["code"] == "internal_error"


def test_serve_accepts_crlf_and_utf8_names() -> None:
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Lim-D\u00fbl's Vault \u014d"}]}
    lines = [_request("hello", "r-0"), _request("game_start", "r-1", game_id="g-1"),
             _request("choose", "r-2", game_id="g-1", decision=decision), _request("game_over", "r-3", game_id="g-1", terminal={})]
    stdout = io.BytesIO()
    assert serve(choose=lambda d: 0, stdin=io.BytesIO(b"".join(line + b"\r\n" for line in lines)), stdout=stdout) == 0
    kinds = [json.loads(line)["response_type"] for line in stdout.getvalue().splitlines()]
    assert kinds == ["hello_ok", "ack", "choice", "ack"]


def test_the_decision_view_exposes_what_bots_read() -> None:
    view = Decision.from_request({"game_id": "g-1", "decision": {"seat_step": 3, "candidates": [PASS, LAND]}, "clock": {"remaining_ms": 5}})
    assert [c.candidate_id for c in view.candidates] == [0, 1] and view.seat_step == 3 and view.clock == {"remaining_ms": 5}
```

Create `python/tests/test_minimal_bot.py`:

```python
"""The spec 10.6 minimal bot, as documented: stdlib only, about 15 lines, conforming."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from spellbench import wire

BOT = Path(__file__).resolve().parents[2] / "examples" / "minimal_bot.py"


def _request(kind: str, request_id: str, **fields) -> bytes:
    return wire.canonical_json_line({"request_type": kind, "protocol": "spellbench/v2", "request_id": request_id, **fields})


def test_the_minimal_bot_is_small_and_stdlib_only() -> None:
    source = BOT.read_text(encoding="utf-8")
    assert len([line for line in source.splitlines() if line.strip()]) <= 20
    imported = {alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= {"json", "sys"} and "from " not in source


def test_the_minimal_bot_plays_under_a_legacy_code_page() -> None:
    # U+014D encodes as c5 8d; 0x8d is undefined in cp1252, so a text-mode reader would crash.
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"},
                                "display_text": "Lim-D\u00fbl's Vault \u014d"}]}
    stdin = b"".join([_request("hello", "r-0", protocol_minor=0), _request("game_start", "r-1", game_id="g-1"),
                      _request("choose", "r-2", game_id="g-1", decision=decision, clock={}),
                      _request("game_over", "r-3", game_id="g-1", terminal={})])
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    result = subprocess.run([sys.executable, str(BOT)], input=stdin, capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    answers = [json.loads(line) for line in result.stdout.splitlines()]  # splitlines also drops a "\r"
    assert [a["response_type"] for a in answers] == ["hello_ok", "ack", "choice", "ack"]
    assert answers[2]["selection"] == {"candidate_id": 0} and answers[0]["bot"]["name"] == "minimal"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_bot_server.py python/tests/test_minimal_bot.py -q`
Expected: FAIL (`ModuleNotFoundError: spellbench.bot`; the example file is missing).

- [ ] **Step 3: Implement**

Create `examples/minimal_bot.py`:

```python
"""The minimal Spellbench v2 bot (spec 10.6): it always picks candidate 0."""
import json
import sys

for line in sys.stdin.buffer:  # bytes: never decoded with the locale's code page
    request = json.loads(line)
    reply = {"protocol": "spellbench/v2", "request_id": request["request_id"]}
    if request["request_type"] == "hello":
        reply.update(response_type="hello_ok", bot={"name": "minimal", "version": "1.0.0"})
    elif request["request_type"] == "choose":
        reply.update(response_type="choice", selection={"candidate_id": 0})
    else:
        reply.update(response_type="ack")
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
```

Create `python/spellbench/bot.py` to the behavior above. `BotSession.handle_line`:

```python
    def handle_line(self, line: bytes) -> bytes:
        try:
            value = wire.strict_json_loads(line)
        except MalformedJsonError as exc:
            return _error("", "malformed_json", str(exc))
        request_id = value.get("request_id")
        if type(request_id) is not str or not request_id:
            return _error("", "malformed_request", "request_id must be a nonempty string")
        protocol = value.get("protocol")
        if type(protocol) is not str:
            return _error(request_id, "malformed_request", "protocol must be a string")
        if protocol != PROTOCOL:
            return _error(request_id, "protocol_mismatch", f'protocol must be "{PROTOCOL}"')
        handler = {"hello": self._hello, "game_start": self._game_start,
                   "choose": self._choose, "game_over": self._game_over}.get(value.get("request_type"))
        if handler is None:
            return _error(request_id, "malformed_request", "unknown request_type")
        return handler(request_id, value)
```

`_error(request_id, code, message)` writes `{"response_type": "error", "protocol", "request_id", "error": {"code", "message"}}` with the message whitespace-collapsed and cut to 240 characters, as a canonical line. `serve` mirrors the v1 `agent_server.serve` loop (read with `wire.read_line`, answer `malformed_json` with `""` for a framing error, exit 0 at EOF); a `handler` object may provide `choose`, `on_game_start`, `on_game_over`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_bot_server.py python/tests/test_minimal_bot.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/bot.py examples/minimal_bot.py python/tests/test_bot_server.py python/tests/test_minimal_bot.py
git commit -m "Bot server: lenient agent role, and the documented minimal bot"
```

## Wave 2

### Task 7: Candidate semantics

**Effort:** 0.5 agent-day. **Wave:** 2. **Depends on:** Task 1.

**Files:**
- Create: `python/spellbench/candidates.py`
- Create: `python/tests/v2_sample_semantics.py` (test data other tasks import)
- Create: `python/tests/test_candidates.py`

**Interfaces:**
- Consumes: `_schema` helpers and name sets (Task 1).
- Produces (`spellbench.candidates`):
  - re-exported from `_schema`: `PRIORITY_KINDS` (6), `CHOICE_KINDS` (24), `V2_KINDS` (30), `RESERVED_KINDS`, `REQUIRED_KINDS`; and `MAX_CANDIDATES = 4096`
  - vocabularies (tuples, spec 7.4 and 6.10): `SELECT_PURPOSES`, `BOOLEAN_PURPOSES`, `NUMBER_PURPOSES`, `OPTION_PURPOSES`, `COLOR_PURPOSES`, `NAME_PURPOSES`, `ORDER_PURPOSES`, `ARRANGE_PURPOSES`, `ARRANGE_DESTINATIONS`, `DISTRIBUTE_PURPOSES`, `PILE_PURPOSES`, `CAST_METHODS`, `OPTIONAL_COSTS`, `COST_KINDS`, `SPECIAL_ACTIONS`, `REPLACEMENT_EVENTS`, `COLORS`, `MANA_SYMBOLS`
  - `validate_semantic(semantic: Any, context: str = "semantic") -> dict`, `validate_candidate(value: Any, context: str = "candidate") -> dict`, `family(kind: str) -> str` (`"priority"` or `"choice"`), `object_references(semantic: Mapping[str, Any]) -> list[tuple[str, dict]]` (every non-null object reference, depth first in sorted key order, with its path)
- Produces (`python/tests/v2_sample_semantics.py`): `R_BOLT`, `R_MOUNTAIN`, `R_SWIFTSPEAR`, `R_SPRITE`, `R_STACK` (object references), `SAMPLES: dict[str, dict]` (one valid semantic per v2.0 kind), and `seat_decision(semantics=None, *, observation=None, acting_seat="p0", kind="priority", source=None, purpose=None, rewind=False, extensions=None) -> dict` (a seat decision over Task 8's `SAMPLE_OBSERVATION`).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/v2_sample_semantics.py`:

```python
"""One valid semantic per v2.0 kind (spec 7.2, 7.3), for tests across tasks."""

from __future__ import annotations

R_BOLT = {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
R_MOUNTAIN = {"object_id": "o-2b8e4dafc6031912", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
R_SWIFTSPEAR = {"object_id": "o-4da06fc1e8253b34", "card_name": "Monastery Swiftspear", "owner_seat": "p0", "controller_seat": "p0", "zone": "battlefield"}
R_SPRITE = {"object_id": "o-6fc281e30a475d56", "card_name": "Spellstutter Sprite", "owner_seat": "p1", "controller_seat": "p1", "zone": "battlefield"}
R_STACK = {"object_id": "o-8c1d2e3f4a5b6c7d", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "stack"}

SAMPLES: dict[str, dict] = {
    "pass": {"kind": "pass"},
    "play_land": {"kind": "play_land", "source": R_MOUNTAIN, "face": 0},
    "cast_spell": {"kind": "cast_spell", "source": R_BOLT, "method": "normal"},
    "activate_mana_ability": {"kind": "activate_mana_ability", "source": R_SWIFTSPEAR, "ability_index": 0, "mana_choice": "R", "cost_target": None},
    "activate_ability": {"kind": "activate_ability", "source": R_SWIFTSPEAR, "ability_index": 0},
    "special_action": {"kind": "special_action", "source": R_BOLT, "action": "plot"},
    "choose_target": {"kind": "choose_target", "source": R_STACK, "slot": 0, "target": {"object": R_SPRITE}, "selected_count": 0, "minimum": 1, "maximum": 1},
    "finish_target_selection": {"kind": "finish_target_selection", "source": R_STACK, "slot": 0, "selected_count": 1},
    "choose_cost_target": {"kind": "choose_cost_target", "source": R_STACK, "cost_kind": "sacrifice", "candidate": R_SWIFTSPEAR, "selected_count": 0, "minimum": 1, "maximum": 1},
    "choose_cast_method": {"kind": "choose_cast_method", "source": R_BOLT, "method": "flashback"},
    "choose_spell_mode": {"kind": "choose_spell_mode", "source": R_STACK, "mode_index": 1, "mode_count": 3, "selected_count": 0, "minimum": 1, "maximum": 2},
    "choose_option": {"kind": "choose_option", "source": None, "purpose": "top_or_bottom", "option_index": 0, "option_count": 2, "option_label": "Top"},
    "choose_color": {"kind": "choose_color", "source": R_STACK, "purpose": "protection", "color": "red"},
    "choose_number": {"kind": "choose_number", "source": R_STACK, "purpose": "x_value", "value": 2, "minimum": 0, "maximum": 4},
    "choose_boolean": {"kind": "choose_boolean", "source": None, "purpose": "may_ability", "value": False},
    "choose_name": {"kind": "choose_name", "source": R_STACK, "purpose": "card_name", "value": "Lightning Bolt"},
    "select_object": {"kind": "select_object", "source": R_STACK, "purpose": "discard", "choice": {"object": R_MOUNTAIN}, "selected_count": 0, "minimum": 1, "maximum": 1},
    "finish_selection": {"kind": "finish_selection", "source": R_STACK, "purpose": "modes", "selected_count": 1},
    "optional_cost": {"kind": "optional_cost", "source": R_STACK, "cost": "kicker", "pay": True},
    "choose_cost_option": {"kind": "choose_cost_option", "source": R_STACK, "choice": "sacrifice_land"},
    "optional_cast": {"kind": "optional_cast", "card": R_BOLT, "method": "madness", "cast_it": False},
    "mulligan": {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 1, "keep": True},
    "order_pick": {"kind": "order_pick", "source": None, "purpose": "triggers", "position": 0, "count": 2,
                   "item": {"trigger": {"source": R_SWIFTSPEAR, "source_name": "Monastery Swiftspear", "ability_index": 0,
                                        "event_objects": [R_SPRITE], "instance": 0, "label": None}}},
    "arrange_card": {"kind": "arrange_card", "source": R_STACK, "purpose": "scry", "card": R_MOUNTAIN, "card_index": 0, "card_count": 2, "destination": "top"},
    "choose_replacement": {"kind": "choose_replacement", "affected": {"player": "p0"}, "event": "damage", "replacement_source": None, "replacement_index": 1, "replacement_count": 2},
    "choose_starting_player": {"kind": "choose_starting_player", "player": "p1"},
    "declare_attack": {"kind": "declare_attack", "attacker": R_SWIFTSPEAR, "defender": {"player": "p1"}},
    "declare_block": {"kind": "declare_block", "blocker": R_SPRITE, "attacker": None},
    "distribute": {"kind": "distribute", "source": R_STACK, "purpose": "damage", "recipient": {"object": R_SPRITE}, "amount": 1, "remaining": 3},
    "choose_pile": {"kind": "choose_pile", "source": None, "purpose": "effect", "pile_index": 1, "piles": [[R_BOLT], [R_MOUNTAIN, R_SWIFTSPEAR]]},
}


def seat_decision(semantics=None, *, observation=None, acting_seat="p0", kind="priority", source=None,
                  purpose=None, rewind=False, extensions=None) -> dict:
    """A seat decision over the spec 6.1 observation (Task 8's sample), for the validator tests of Tasks 14 to 16 and 22."""
    import copy

    from v2_sample_observation import SAMPLE_OBSERVATION  # imported late: Task 8 lands in the same wave

    semantics = [SAMPLES["pass"], SAMPLES["play_land"], SAMPLES["cast_spell"]] if semantics is None else semantics
    return {
        "acting_seat": acting_seat, "seat_step": 0, "group": {"group_id": 0, "substep_index": 0, "substep_count": 1},
        "context": {"kind": kind, "source": source, "purpose": purpose, "text": None, "rewind": rewind},
        "observation": copy.deepcopy(SAMPLE_OBSERVATION) if observation is None else observation,
        "candidates": [{"candidate_id": index, "semantic": copy.deepcopy(semantic), "display_text": None}
                       for index, semantic in enumerate(semantics)],
        "extensions": {} if extensions is None else extensions,
    }
```

Create `python/tests/test_candidates.py`:

```python
"""Candidate semantics: the 30 v2.0 kinds, their vocabularies and constraints (spec 7)."""

from __future__ import annotations

import copy

import pytest

from spellbench.candidates import (
    CHOICE_KINDS, PRIORITY_KINDS, RESERVED_KINDS, V2_KINDS, family, object_references, validate_candidate, validate_semantic,
)
from spellbench.errors import ValidationError

from v2_sample_semantics import R_SPRITE, R_SWIFTSPEAR, SAMPLES


def test_the_samples_cover_exactly_the_v2_kinds() -> None:
    assert set(SAMPLES) == V2_KINDS and len(V2_KINDS) == 30
    assert len(PRIORITY_KINDS) == 6 and len(CHOICE_KINDS) == 24


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_every_sample_validates_unchanged(kind: str) -> None:
    semantic = copy.deepcopy(SAMPLES[kind])
    assert validate_semantic(semantic) == SAMPLES[kind]
    assert family(kind) == ("priority" if kind in PRIORITY_KINDS else "choice")


@pytest.mark.parametrize("kind", sorted(RESERVED_KINDS))
def test_reserved_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        validate_semantic({"kind": kind})


def _edit(kind: str, **changes) -> dict:
    return {**copy.deepcopy(SAMPLES[kind]), **changes}


@pytest.mark.parametrize(
    "semantic",
    [
        {"kind": "choose_cast_mode"},                                     # a v1 kind
        _edit("play_land", extra=1),                                      # unknown field
        {k: v for k, v in SAMPLES["play_land"].items() if k != "face"},   # missing field
        _edit("choose_target", selected_count=1, maximum=1),              # selected_count < maximum
        _edit("choose_target", minimum=2, maximum=1),
        _edit("choose_spell_mode", maximum=4),                            # maximum <= mode_count
        _edit("choose_spell_mode", mode_index=3),
        _edit("choose_option", option_index=2),
        _edit("choose_number", value=5),
        _edit("order_pick", position=2),
        _edit("arrange_card", card_index=2),
        _edit("choose_replacement", replacement_count=1, replacement_index=0),
        _edit("distribute", amount=4),
        _edit("choose_pile", pile_index=2),
        _edit("choose_pile", piles=[[], [], []]),
        _edit("choose_color", color="purple"),
        _edit("cast_spell", method="sideways"),
        _edit("choose_cost_option", choice="Sacrifice Land"),
        _edit("select_object", purpose="discard_all"),
        _edit("mulligan", keep=1),
        _edit("choose_number", value=True),
        _edit("declare_attack", defender={"player": "p0", "object": R_SPRITE}),
        _edit("order_pick", item={"object": R_SPRITE, "trigger": {}}),
    ],
)
def test_invalid_semantics_are_malformed(semantic: dict) -> None:
    with pytest.raises(ValidationError):
        validate_semantic(semantic)


def test_nullable_fields() -> None:
    assert validate_semantic(_edit("cast_spell", method=None))["method"] is None
    assert validate_semantic(_edit("declare_attack", defender=None))["defender"] is None
    with pytest.raises(ValidationError):
        validate_semantic(_edit("choose_target", source=None))   # R, not R|null


def test_candidates_are_exactly_three_fields() -> None:
    candidate = {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}
    assert validate_candidate(candidate) == candidate
    with pytest.raises(ValidationError):
        validate_candidate({**candidate, "x_extra": 1})


def test_object_references_walk_every_reference() -> None:
    paths = [path for path, _ in object_references(SAMPLES["order_pick"])]
    assert paths == ["item.trigger.event_objects[0]", "item.trigger.source"]
    assert [ref for _, ref in object_references(SAMPLES["declare_block"])] == [R_SPRITE]
    assert len(object_references(SAMPLES["choose_pile"])) == 3
    assert object_references(SAMPLES["declare_attack"]) == [("attacker", R_SWIFTSPEAR)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_candidates.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.candidates`).

- [ ] **Step 3: Implement `candidates.py`**

Vocabularies verbatim from spec 7.4 (`COLORS = ("white", "blue", "black", "red", "green")`, `MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")`). The field table is the whole contract of spec 7.2 and 7.3:

```python
_FIELDS: dict[str, dict[str, Any]] = {
    "pass": {},
    "play_land": {"source": "R", "face": "u32"},
    "cast_spell": {"source": "R", "method": ("vocab?", CAST_METHODS)},
    "activate_mana_ability": {"source": "R", "ability_index": "u32", "mana_choice": ("vocab?", MANA_SYMBOLS), "cost_target": "T?"},
    "activate_ability": {"source": "R", "ability_index": "u32"},
    "special_action": {"source": "R", "action": ("vocab", SPECIAL_ACTIONS)},
    "choose_target": {"source": "R", "slot": "u32", "target": "T", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "finish_target_selection": {"source": "R", "slot": "u32", "selected_count": "u32"},
    "choose_cost_target": {"source": "R", "cost_kind": ("vocab", COST_KINDS), "candidate": "R", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "choose_cast_method": {"source": "R", "method": ("vocab", CAST_METHODS)},
    "choose_spell_mode": {"source": "R", "mode_index": "u32", "mode_count": "u32", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "choose_option": {"source": "R?", "purpose": ("vocab", OPTION_PURPOSES), "option_index": "u32", "option_count": "u32", "option_label": "str?"},
    "choose_color": {"source": "R?", "purpose": ("vocab", COLOR_PURPOSES), "color": ("vocab", COLORS)},
    "choose_number": {"source": "R?", "purpose": ("vocab", NUMBER_PURPOSES), "value": "i32", "minimum": "i32", "maximum": "i32"},
    "choose_boolean": {"source": "R?", "purpose": ("vocab", BOOLEAN_PURPOSES), "value": "bool"},
    "choose_name": {"source": "R?", "purpose": ("vocab", NAME_PURPOSES), "value": "str"},
    "select_object": {"source": "R?", "purpose": ("vocab", SELECT_PURPOSES), "choice": "T", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "finish_selection": {"source": "R?", "purpose": ("vocab", SELECT_PURPOSES), "selected_count": "u32"},
    "optional_cost": {"source": "R", "cost": ("vocab", OPTIONAL_COSTS), "pay": "bool"},
    "choose_cost_option": {"source": "R", "choice": "snake"},
    "optional_cast": {"card": "R", "method": ("vocab", CAST_METHODS), "cast_it": "bool"},
    "mulligan": {"hand_size": "u32", "mulligans_taken": "u32", "keep": "bool"},
    "order_pick": {"source": "R?", "purpose": ("vocab", ORDER_PURPOSES), "item": "item", "position": "u32", "count": "u32"},
    "arrange_card": {"source": "R?", "purpose": ("vocab", ARRANGE_PURPOSES), "card": "R", "card_index": "u32", "card_count": "u32", "destination": ("vocab", ARRANGE_DESTINATIONS)},
    "choose_replacement": {"affected": "T", "event": ("vocab", REPLACEMENT_EVENTS), "replacement_source": "R?", "replacement_index": "u32", "replacement_count": "u32"},
    "choose_starting_player": {"player": "seat"},
    "declare_attack": {"attacker": "R", "defender": "T?"},
    "declare_block": {"blocker": "R", "attacker": "R?"},
    "distribute": {"source": "R?", "purpose": ("vocab", DISTRIBUTE_PURPOSES), "recipient": "T", "amount": "u32", "remaining": "u32"},
    "choose_pile": {"source": "R?", "purpose": ("vocab", PILE_PURPOSES), "pile_index": "u32", "piles": "piles"},
}
```

Field kinds: `"R"` `_schema.object_ref`; `"R?"` nullable; `"T"` `_schema.target_ref`; `"T?"` nullable; `"u32"`, `"i32"`, `"bool"`, `"seat"`; `"str"` nonempty string; `"str?"` nullable string; `"snake"`; `("vocab", values)` and `("vocab?", values)`; `"item"` is exactly `{"object": R}` or `{"trigger": {"source": R|null, "source_name": NFC name|null, "ability_index": u32|null, "event_objects": [R], "instance": u32, "label": str|null}}`; `"piles"` is a list of exactly two lists of `R`. `validate_semantic` fails with `"reserved kind (not in v2.0)"` for `RESERVED_KINDS`, `"unknown kind"` otherwise, checks `exact_keys(["kind", *fields])`, each field, then the constraints of spec 7.3 (the list in the tests; `choose_pile.pile_index` is 0 or 1). `object_references` walks the semantic's keys in sorted order and yields `(path, ref)` for each non-null `R`, each `T` holding an `object`, each order-item object, trigger source and event object, and each pile member.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_candidates.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/candidates.py python/tests/v2_sample_semantics.py python/tests/test_candidates.py
git commit -m "Candidates: the 30 v2.0 kinds with vocabularies and constraints"
```

### Task 8: The observation schema

**Effort:** 0.75 agent-day. **Wave:** 2. **Depends on:** Task 1.

**Files:**
- Create: `python/spellbench/observation.py`
- Create: `python/tests/v2_sample_observation.py` (the spec 6.1 example as data)
- Create: `python/tests/test_observation.py`

**Interfaces:**
- Consumes: `_schema` (Task 1).
- Produces (`spellbench.observation`):
  - `PHASE_STEPS` (13 values incl. `pregame`), `SUPERTYPES`, `CARD_TYPES`, `COLOR_ORDER = ("white", "blue", "black", "red", "green")`, `STACK_KINDS`, `KNOWN_ZONES = ("hand", "library")`, `KNOWN_HOW`, `CHOSEN_KINDS`, `DAY_NIGHT = ("day", "night", "none")`, `ZONE_ARRAYS = ("hand", "battlefield", "graveyard", "exile", "command")`, and `OBSERVATION_FLAGS` re-exported from `_schema`
  - `validate_observation(value: Any, context: str = "observation") -> dict` (structure only: every field, type and vocabulary of spec 6; optional fields may be `null` or typed here, and Task 16 enforces the flags; `known` entries are type-checked here and shape-checked by Task 15)
  - `zone_records(observation) -> Iterator[tuple[str, str, dict]]` (path, owning seat, record)
  - `observation_objects(observation) -> list[tuple[str, dict]]` (path, reference) for every held object: zone-array records, stack entries, and `known` entries with a non-null `object_id` (reference `{object_id, card_name, owner_seat, controller_seat: owner_seat, zone}`)
  - `observation_references(observation) -> list[tuple[str, dict]]` (path, reference) for every non-null reference inside the observation that must equal a held object: `permanent.attached_to` and `permanent.attack_target` objects, `permanent.blocked_attackers`, stack `source` and object `targets`, pending-trigger `source`, `exiled_by`
- Produces (`python/tests/v2_sample_observation.py`): `SAMPLE_OBSERVATION` (spec 6.1 verbatim) and `ALL_FLAGS_ON`, `ALL_FLAGS_OFF` (dicts of the 13 flags).

Structural rules beyond types (all V1, spec 6.2 to 6.6): `players` is exactly `[p0, p1]` in that order; `mana_pool` has exactly `W U B R G C`; `phase_step == "pregame"` exactly when `turn == 0`, and `active_seat` is null only in `pregame`; each zone-array record's `zone` equals its array (a record claiming `library` is left for V5), a `battlefield` record's `controller_seat` and every other array record's `owner_seat` equal the player's seat; `permanent` is non-null exactly for `battlefield` records; `characteristics` is null only for a face-down record outside the battlefield; `colors` is a subset in `COLOR_ORDER` order; `power` and `toughness` are non-null only when `types` has `creature`; `attack_target` is non-null only while `attacking`; stack entries have zone `stack`, `characteristics` exactly when `stack_kind == "spell"`, and `targets` entries that are target references or `null`; subtypes, keywords, counter names, statuses and designations match `[a-z][a-z0-9_]*`; every card name is NFC.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/v2_sample_observation.py` holding `SAMPLE_OBSERVATION` as the spec 6.1 JSON copied verbatim into a Python dict (lowercase `null`, `true`, `false` become `None`, `True`, `False`), plus:

```python
from spellbench.observation import OBSERVATION_FLAGS

ALL_FLAGS_ON = dict.fromkeys(OBSERVATION_FLAGS, True)
ALL_FLAGS_OFF = dict.fromkeys(OBSERVATION_FLAGS, False)
```

Create `python/tests/test_observation.py`:

```python
"""The observation schema (spec 6)."""

from __future__ import annotations

import copy

import pytest

from spellbench.errors import ValidationError
from spellbench.observation import OBSERVATION_FLAGS, observation_objects, observation_references, validate_observation

from v2_sample_observation import SAMPLE_OBSERVATION


def _copy() -> dict:
    return copy.deepcopy(SAMPLE_OBSERVATION)


def test_the_spec_example_validates() -> None:
    assert validate_observation(_copy()) == SAMPLE_OBSERVATION
    assert len(OBSERVATION_FLAGS) == 13


def _mutations():
    def at(path_fn, value):
        def edit(observation):
            path_fn(observation, value)
            return observation
        return edit
    swift = lambda o: o["players"][0]["battlefield"][0]
    return {
        "unknown field": lambda o: {**o, "x_extra": 1},
        "missing field": lambda o: {k: v for k, v in o.items() if k != "known"},
        "players order": lambda o: {**o, "players": list(reversed(o["players"]))},
        "mana pool key": at(lambda o, v: o["players"][0]["mana_pool"].update(X=v), 0),
        "color order": at(lambda o, v: swift(o)["characteristics"].update(colors=v), ["red", "white"]),
        "permanent on a hand card": at(lambda o, v: o["players"][0]["hand"][0].update(permanent=v), swift(SAMPLE_OBSERVATION)["permanent"]),
        "face-up card without characteristics": at(lambda o, v: o["players"][0]["hand"][0].update(characteristics=v), None),
        "record zone differs from its array": at(lambda o, v: swift(o).update(zone=v), "graveyard"),
        "battlefield controller": at(lambda o, v: swift(o).update(controller_seat=v), "p1"),
        "pregame with a turn": at(lambda o, v: o.update(phase_step=v), "pregame"),
        "power on a noncreature": at(lambda o, v: o["players"][0]["hand"][0]["characteristics"].update(power=v), 3),
        "known how": at(lambda o, v: o["known"][0].update(how=v), "guessed"),
        "counter name": at(lambda o, v: swift(o)["permanent"].update(counters=v), {"+1/+1": 1}),
        "NFD card name": at(lambda o, v: o["players"][0]["hand"][0].update(card_name=v), "Lim-Du\u0302l's Vault"),
        "attack target while not attacking": at(lambda o, v: swift(o)["permanent"].update(attack_target=v), {"player": "p1"}),
        "life above i32": at(lambda o, v: o["players"][1].update(life=v), 1 << 31),
    }


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_invalid_observations_are_malformed(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_observation(_mutations()[name](_copy()))


def test_a_library_record_passes_the_schema_for_v5_to_report() -> None:
    observation = _copy()
    observation["players"][0]["hand"][0]["zone"] = "library"
    assert validate_observation(observation)


def test_walkers() -> None:
    observation = _copy()
    assert [path for path, _ in observation_objects(observation)] == [
        "players[0].hand[0]", "players[0].hand[1]", "players[0].battlefield[0]", "players[1].battlefield[0]",
    ]
    assert observation_references(observation) == []
    sprite = observation["players"][1]["battlefield"][0]
    swift = observation["players"][0]["battlefield"][0]
    swift["permanent"].update(attacking=True, attack_target={"player": "p1"})
    sprite["permanent"].update(blocking=True, blocked_attackers=[{k: swift[k] for k in ("object_id", "card_name", "owner_seat", "controller_seat", "zone")}])
    observation["known"].append({"owner_seat": "p1", "zone": "library", "card_name": "Island", "object_id": "o-794a5cb152c9620f",
                                 "position_from_top": 0, "position_from_bottom": None, "how": "looked_at"})
    validate_observation(observation)
    assert [path for path, _ in observation_references(observation)] == ["players[1].battlefield[0].permanent.blocked_attackers[0]"]
    held = dict(observation_objects(observation))
    assert held["known[2]"] == {"object_id": "o-794a5cb152c9620f", "card_name": "Island", "owner_seat": "p1",
                                "controller_seat": "p1", "zone": "library"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_observation.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.observation`).

- [ ] **Step 3: Implement `observation.py`**

Vocabularies verbatim from spec 6.2, 6.5, 6.7 and 6.10 (`SUPERTYPES = ("basic", "legendary", "ongoing", "snow", "world")`, the 15 `CARD_TYPES`, `STACK_KINDS = ("spell", "activated_ability", "triggered_ability")`, `KNOWN_HOW = ("revealed", "looked_at", "from_public_zone", "own_placement", "searching", "tracked")`, `CHOSEN_KINDS = ("color", "card_name", "creature_type", "card_type", "land_type", "number", "player", "mode", "other")`). Write one validator per object of spec 6 (`_player`, `_record`, `_characteristics`, `_permanent`, `_stack_entry`, `_pending_trigger`, `_known_entry`), each starting with `exact_keys` over the spec's field table and applying the structural rules listed above; build every error context from the path (`"observation.players[0].battlefield[0].permanent.counters"`), because validator halt messages quote it. `observation_objects` yields the zone records first (players in order, arrays in `ZONE_ARRAYS` order), then `stack[i]`, then `known[i]` entries with an id.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_observation.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/observation.py python/tests/v2_sample_observation.py python/tests/test_observation.py
git commit -m "Observation: the spec 6 board view schema and reference walkers"
```

### Task 9: Engine-role messages and shared protocol types

**Effort:** 0.5 agent-day. **Wave:** 2. **Depends on:** Tasks 1, 2.

**Files:**
- Create: `python/spellbench/messages.py`
- Create: `python/tests/test_messages.py`

**Interfaces:**
- Consumes: `_schema` helpers and the name sets `V2_KINDS`, `RESERVED_KINDS`, `REQUIRED_KINDS`, `OBSERVATION_FLAGS` (Task 1); `digests.deck_rows`, `digests.domain_id` (Task 2). Nothing from Tasks 7 or 8, which run in the same wave.
- Produces (`spellbench.messages`), frozen dataclasses with `to_json() -> dict` and strict `from_json(value, context=...)`:
  - `PROTOCOL = "spellbench/v2"`, `PROTOCOL_MINOR = 0`, `ENGINE_ERROR_CODES` (the 17 codes of spec 9.8), `MULLIGAN_RULES = ("london", "none")`, `STARTING_PLAYER_RULES = ("host_assigned", "toss_winner_chooses")`, `DECK_SOURCES = ("catalog", "decklist")`, `ENGINE_DEFAULT_KEYS = ("trigger_order", "replacement_order", "combat_damage_assignment", "mana_payment")`
  - `EngineIdentity(name, version, source_revision: str | None, rules_snapshot_id, card_pool_identity)` with `provenance() -> Provenance`; `Provenance(engine_name, engine_version, rules_snapshot_id, card_pool_identity)`
  - `DeckRow(name, count)`; `CatalogDeck(catalog_id, name, decklist: tuple[DeckRow, ...])`; `ExtensionDecl(name, native_ids: bool)`
  - `EngineProfile(rules_supported: dict[str, tuple[str, ...]], observation: dict[str, bool], decision_kinds: tuple[str, ...], engine_defaults: dict[str, str | None], rewind: bool, fairness: dict[str, bool], extensions: tuple[ExtensionDecl, ...])` (its `to_json()` is the `game_start.engine_profile` object)
  - `HelloRequest(request_id, protocol_minor)`; `EnvHelloOk(request_id, protocol_minor, engine: EngineIdentity, formats: tuple[str, ...], deck_sources: tuple[str, ...], catalog: tuple[CatalogDeck, ...], profile: EngineProfile)` (JSON flattens the profile fields into `hello_ok`)
  - `CardNameDomain(domain_id, names: tuple[str, ...])`; `Rules(opponent_decklist, mulligan, starting_player, starting_seat: str | None, card_name_domain: CardNameDomain, extensions: tuple[str, ...], probe: bool)`
  - `WireDeck(deck_id, catalog_id: str | None = None, decklist: tuple[DeckRow, ...] | None = None)`; `ResetRequest(request_id, game_id, format, seats: tuple[WireDeck, WireDeck], rules: Rules, game_secret: str, max_decisions: int, max_steps: int)`
  - `Decision(request_id, game_id, step: int, seat_decision: dict, provenance: Provenance)` (the binding; `seat_decision` is only checked to be an object here, Task 22 validates it) with property `acting_seat -> str | None`
  - `Selection(candidate_id, semantic_echo: dict)`; `StepRequest(request_id, game_id, expected_step, selection: Selection)`
  - `TerminalResult(outcome, classification, winner, reason, step_count, decision_count)`; `Terminal(request_id, game_id, result: TerminalResult, provenance: Provenance)`
  - `ValidateDeckRequest(request_id, format, catalog_id: str | None, decklist: tuple[DeckRow, ...] | None)`; `DeckOk(request_id)`; `ErrorResponse(request_id, code, message)` with `from_json(value, *, codes: frozenset[str], context="error")`
  - `TimeControl(startup_ms, game_start_ms, bank_ms, increment_ms, max_decision_ms, engine_step_ms)`, `Limits(max_decisions, max_steps, max_seat_decisions_per_turn, max_seat_decisions_per_game, max_seat_steps_per_game)` (construction fails unless each per-game seat cap is strictly below half its game cap, spec 11.1), `Resources(cpus, memory_mb, gpu: bool, engine_cpus)`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_messages.py`:

```python
"""Engine-role messages: the spec examples parse and round-trip exactly (spec 9)."""

from __future__ import annotations

import copy

import pytest

from spellbench.errors import ValidationError
from spellbench.messages import (
    ENGINE_ERROR_CODES, Decision, EnvHelloOk, ErrorResponse, Limits, ResetRequest, Rules, StepRequest, Terminal, TimeControl,
)

BURN_ID = "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2"
DOMAIN = {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]}
ENGINE = {"name": "mtg-kernel", "version": "0.0.5", "source_revision": None, "rules_snapshot_id": "opaque engine string",
          "card_pool_identity": "opaque engine string"}
PROVENANCE = {"engine_name": "mtg-kernel", "engine_version": "0.0.5", "rules_snapshot_id": "opaque engine string",
              "card_pool_identity": "opaque engine string"}
FLAGS = {"poison": False, "player_counters": False, "designations": True, "player_progress": False, "day_night": False,
         "passed_seats": True, "pending_triggers": True, "keywords": True, "full_name": False, "exiled_by": True,
         "stack_text": False, "permanent_details": True, "known_cards": True}
HELLO_OK = {  # spec 9.1, verbatim
    "response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "h-1", "protocol_minor": 0, "engine": ENGINE,
    "formats": ["pauper-bo1"], "deck_sources": ["catalog"],
    "catalog": [{"catalog_id": "Burn", "name": "Burn", "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]}],
    "rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]}, "observation": FLAGS,
    "decision_kinds": ["pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability", "special_action",
                       "choose_target", "finish_target_selection", "choose_cost_target", "choose_cast_method", "choose_spell_mode",
                       "choose_option", "choose_color", "choose_number", "choose_boolean", "select_object", "finish_selection",
                       "optional_cost", "choose_cost_option", "optional_cast", "order_pick", "arrange_card", "declare_attack", "declare_block"],
    "engine_defaults": {"trigger_order": None, "replacement_order": None, "combat_damage_assignment": "engine_order", "mana_payment": None},
    "rewind": False, "fairness": {"noninterference_probe": False}, "extensions": [{"name": "x_kernel_v5", "native_ids": True}],
}
RULES = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
         "card_name_domain": DOMAIN, "extensions": [], "probe": False}
RESET = {  # spec 9.2, verbatim
    "request_type": "reset", "protocol": "spellbench/v2", "request_id": "h-2", "game_id": "g-f67d7fe78c792984", "format": "pauper-bo1",
    "seats": [{"seat": "p0", "deck": {"deck_id": BURN_ID, "catalog_id": "Burn"}}, {"seat": "p1", "deck": {"deck_id": BURN_ID, "catalog_id": "Burn"}}],
    "rules": RULES, "game_secret": "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e",
    "max_decisions": 10000, "max_steps": 100000,
}
TERMINAL = {"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-9", "game_id": "g-f67d7fe78c792984",
            "outcome": "p0_win", "classification": "natural", "winner": "p0", "reason": "p1_life_zero",
            "step_count": 412, "decision_count": 388, "provenance": PROVENANCE}


@pytest.mark.parametrize(("model", "message"), [(EnvHelloOk, HELLO_OK), (ResetRequest, RESET), (Terminal, TERMINAL)])
def test_spec_examples_round_trip(model, message) -> None:
    assert model.from_json(copy.deepcopy(message)).to_json() == message


def test_the_decision_binding_keeps_the_seat_decision_raw() -> None:
    message = {"response_type": "decision", "protocol": "spellbench/v2", "request_id": "h-7", "game_id": "g-f67d7fe78c792984",
               "step": 14, "seat_decision": {"acting_seat": "p0", "anything": "validated later"}, "provenance": PROVENANCE}
    decision = Decision.from_json(copy.deepcopy(message))
    assert decision.acting_seat == "p0" and decision.to_json() == message


def test_step_request_always_carries_the_echo() -> None:
    step = {"request_type": "step", "protocol": "spellbench/v2", "request_id": "h-8", "game_id": "g-1", "expected_step": 14,
            "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}}
    assert StepRequest.from_json(step).to_json() == step
    with pytest.raises(ValidationError):
        StepRequest.from_json({**step, "selection": {"candidate_id": 0}})


def _hello(**changes) -> dict:
    value = copy.deepcopy(HELLO_OK)
    value.update(changes)
    return value


@pytest.mark.parametrize(
    "hello",
    [
        _hello(decision_kinds=["pass", "play_land", "cast_spell", "declare_attack"]),                 # a required kind missing
        _hello(decision_kinds=HELLO_OK["decision_kinds"] + ["pay_mana"]),                             # a reserved kind
        _hello(observation={**FLAGS, "x_flag": True}),
        _hello(engine_defaults={**HELLO_OK["engine_defaults"], "mana_payment": "engine_order"}),
        _hello(deck_sources=["catalog", "cloud"]),
        _hello(rules_supported={"mulligan": [], "starting_player": ["host_assigned"]}),
        _hello(catalog=[{"catalog_id": "Vault", "name": "Vault", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 4}]}]),
        _hello(extensions=[{"name": "kernel", "native_ids": True}]),
        _hello(x_unknown=1),
    ],
)
def test_invalid_hello_ok_is_malformed(hello: dict) -> None:
    with pytest.raises(ValidationError):
        EnvHelloOk.from_json(hello)


def test_an_nfd_catalog_name_is_named_in_the_error() -> None:
    hello = _hello(catalog=[{"catalog_id": "Vault", "name": "Vault", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 4}]}])
    with pytest.raises(ValidationError, match="Lim-Du\u0302l's Vault.*NFC"):
        EnvHelloOk.from_json(hello)


@pytest.mark.parametrize(
    "rules",
    [
        {**RULES, "starting_seat": None},                                     # host_assigned needs a seat
        {**RULES, "starting_player": "toss_winner_chooses"},                  # and toss_winner_chooses none
        {**RULES, "card_name_domain": {**DOMAIN, "names": ["Mountain"]}},     # domain_id must match the names
        {**RULES, "opponent_decklist": "secret"},
        {**RULES, "extensions": ["kernel"]},
    ],
)
def test_invalid_rules_are_malformed(rules: dict) -> None:
    with pytest.raises(ValidationError):
        Rules.from_json(rules)


def test_seat_caps_must_stay_below_half_the_game_caps() -> None:
    Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
           max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)
    with pytest.raises(ValidationError, match="half"):
        Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
               max_seat_decisions_per_game=5000, max_seat_steps_per_game=49999)


def test_errors_use_the_closed_code_table() -> None:
    assert len(ENGINE_ERROR_CODES) == 17
    error = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "", "error": {"code": "probe_refused", "message": "no"}}
    assert ErrorResponse.from_json(error, codes=ENGINE_ERROR_CODES).code == "probe_refused"
    with pytest.raises(ValidationError):
        ErrorResponse.from_json({**error, "error": {"code": "no_pending_decision", "message": "x"}}, codes=ENGINE_ERROR_CODES)


def test_a_terminal_never_carries_forfeit_or_a_truncated_winner() -> None:
    for changes in ({"classification": "forfeit"}, {"outcome": "truncated", "classification": "truncated"}):
        with pytest.raises(ValidationError):
            Terminal.from_json({**TERMINAL, **changes})


def test_time_control_round_trips() -> None:
    value = {"startup_ms": 300000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
             "max_decision_ms": 60000, "engine_step_ms": 120000}
    assert TimeControl.from_json(value).to_json() == value
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_messages.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.messages`).

- [ ] **Step 3: Implement `messages.py`**

Follow the v1 `models.py` pattern (frozen dataclasses, `to_json`, strict `from_json` with a context path) using `_schema` helpers. Rules per spec 9: `hello_ok.protocol_minor` is a safe integer (the engine client compares it with the request); `formats` and `deck_sources` nonempty, `deck_sources` a subset of `DECK_SOURCES` without repeats; `catalog` empty unless `deck_sources` has `catalog`, distinct `catalog_id`s, each `decklist` passed through `digests.deck_rows` (which names a non-NFC card; prefix the context with `catalog[i] (<catalog_id>)`); `rules_supported` exactly `mulligan` and `starting_player`, each a nonempty subset of its vocabulary; `observation` exactly the 13 flags as booleans; `decision_kinds` distinct members of `V2_KINDS` (a reserved kind fails as reserved) that include `REQUIRED_KINDS`; `engine_defaults` exactly the four keys, `mana_payment` in `(None, "engine_autopay")`, the others in `(None, "engine_order")`; `fairness` exactly `noninterference_probe`; `extensions` entries exactly `{name, native_ids}` with `EXTENSION_KEY_RE` names. `Rules.card_name_domain.domain_id` must equal `digests.domain_id(names)` and names are distinct NFC; `starting_seat` is a seat exactly when `starting_player == "host_assigned"`. `WireDeck` is exactly `{deck_id, catalog_id}` or `{deck_id, decklist}`, `deck_id` matching `sha256:[0-9a-f]{64}`. `ResetRequest.game_secret` is 64 lowercase hex; seats exactly `p0` then `p1`. `TerminalResult` follows spec 9.5 (natural pairs, `winner: null` for truncated and halted, no `forfeit`). Integer fields of `TimeControl`, `Limits`, `Resources` are at least 1 (`increment_ms` at least 0).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_messages.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/messages.py python/tests/test_messages.py
git commit -m "Messages: engine-role messages and shared v2 protocol types"
```

### Task 10: Group and identity tracking (V3, V7)

**Effort:** 0.5 agent-day. **Wave:** 2. **Depends on:** Task 3.

**Files:**
- Create: `python/spellbench/host/violation.py`
- Create: `python/spellbench/host/tracking.py`
- Create: `python/tests/test_host_tracking.py`

**Interfaces:**
- Consumes: `errors.ProtocolError`; `host/__init__.py` (Task 3).
- Produces:
  - `host.violation.RULES = ("V1", ..., "V10")`; `class ValidatorViolation(ProtocolError)` with `__init__(rule: str, detail: str)`, attributes `rule`, `detail`, picklable (`__reduce__`)
  - `host.tracking.GroupTracker()` with `check(seat_decision: Mapping) -> None` (raises V3), `answered(seat_decision: Mapping, *, chosen_kind: str) -> None`, `answered_by(seat: str) -> int` (that seat's answered decisions, its `seat_step_count`), attribute `answered_steps: int`, property `completed_groups: int`
  - `host.tracking.IdTracker()` with `check(seat: str, objects: Mapping[str, str]) -> None` (object id to zone; raises V7)

Semantics (spec 8, 9.3, 5.3; Decisions 4): per seat, `seat_step` starts at 0 and advances by 1 per answered decision; while a seat's group is partial, a decision for the other seat is a violation, and the seat's next decision must be the next substep (same `group_id` and `substep_count`) unless it is a rewind; a new group has the next `group_id` and substep 0; a rewind (`context.rewind`) is a priority decision of a seat that has made a non-pass priority action since its last priority decision, and it may abandon that seat's partial group (the rewind decision then has that group's id plus 1). When a rewind is answered, the groups completed since that seat's action (the action's own group included, and any group either seat completed after it) are subtracted from `completed_groups`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_tracking.py`:

```python
"""V3 (seat steps, groups, rewinds) and V7 (id freshness) state (spec 8, 5.3, 11.3)."""

from __future__ import annotations

import pickle

import pytest

from spellbench.host.tracking import GroupTracker, IdTracker
from spellbench.host.violation import ValidatorViolation


def sd(seat: str, step: int, group: int, index: int = 0, count: int = 1, *, kind: str = "priority", rewind: bool = False) -> dict:
    return {"acting_seat": seat, "seat_step": step, "group": {"group_id": group, "substep_index": index, "substep_count": count},
            "context": {"kind": kind, "source": None, "purpose": None, "text": None, "rewind": rewind}}


def play(tracker: GroupTracker, decision: dict, chosen: str = "pass") -> None:
    tracker.check(decision)
    tracker.answered(decision, chosen_kind=chosen)


def test_per_seat_counters_advance_independently() -> None:
    tracker = GroupTracker()
    for decision in (sd("p0", 0, 0), sd("p1", 0, 0), sd("p0", 1, 1), sd("p0", 2, 2), sd("p1", 1, 1)):
        play(tracker, decision)
    assert (tracker.answered_steps, tracker.completed_groups) == (5, 5)
    assert (tracker.answered_by("p0"), tracker.answered_by("p1")) == (3, 2)


@pytest.mark.parametrize(
    "decisions",
    [
        [sd("p0", 1, 0)],                                             # seat_step gap
        [sd("p0", 0, 1)],                                             # group_id skip
        [sd("p0", 0, 0, 0, 2), sd("p1", 0, 0)],                       # the other seat during a partial group
        [sd("p0", 0, 0, 0, 2), sd("p0", 1, 0, 1, 3)],                 # substep_count changed mid-group
        [sd("p0", 0, 0, 0, 2), sd("p0", 1, 1, 0, 1)],                 # a partial group abandoned without a rewind
        [sd("p0", 0, 0, rewind=True)],                                # a rewind with no action to undo
        [sd("p0", 0, 0), sd("p0", 1, 1, kind="choice", rewind=True)],  # a rewind that is not a priority decision
    ],
)
def test_v3_violations(decisions: list[dict]) -> None:
    tracker = GroupTracker()
    with pytest.raises(ValidatorViolation) as caught:
        for decision in decisions:
            play(tracker, decision, chosen="cast_spell")
    assert caught.value.rule == "V3"


def test_a_rewind_abandons_the_action_and_the_groups_after_it() -> None:
    tracker = GroupTracker()
    play(tracker, sd("p0", 0, 0), chosen="cast_spell")                   # the action (group 0)
    play(tracker, sd("p0", 1, 1, kind="choice"), chosen="choose_target")  # a completed target group (1)
    play(tracker, sd("p0", 2, 2, 0, 2, kind="choice"), chosen="choose_target")  # group 2 left partial
    rewound = sd("p0", 3, 3, rewind=True)                                 # re-posed priority: group 2 + 1
    play(tracker, rewound, chosen="pass")
    assert tracker.completed_groups == 1   # only the re-posed priority decision counts
    assert tracker.answered_steps == 4     # seat_step keeps counting answered decisions


def test_id_freshness() -> None:
    ids = IdTracker()
    ids.check("p0", {"o-1": "hand", "o-2": "battlefield"})
    ids.check("p1", {"o-1": "graveyard"})                 # per viewer: another seat's stream
    with pytest.raises(ValidatorViolation) as two_zones:
        ids.check("p0", {"o-1": "graveyard", "o-2": "battlefield"})
    assert two_zones.value.rule == "V7"
    ids = IdTracker()
    ids.check("p0", {"o-1": "hand"})
    ids.check("p0", {"o-3": "battlefield"})               # o-1 left
    with pytest.raises(ValidatorViolation, match="returned"):
        ids.check("p0", {"o-1": "hand"})


def test_violations_cross_process_boundaries() -> None:
    violation = pickle.loads(pickle.dumps(ValidatorViolation("V4", "stale reference")))
    assert (violation.rule, violation.detail, str(violation)) == ("V4", "stale reference", "V4: stale reference")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_tracking.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.tracking`).

- [ ] **Step 3: Implement**

`host/violation.py`:

```python
"""A live-validation violation (spec 11.3): the rule and a host-written detail."""

from __future__ import annotations

from ..errors import ProtocolError

RULES = tuple(f"V{number}" for number in range(1, 11))


class ValidatorViolation(ProtocolError):
    def __init__(self, rule: str, detail: str) -> None:
        if rule not in RULES:
            raise ValueError(f"unknown validator rule {rule!r}")
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail

    def __reduce__(self) -> tuple:
        return (type(self), (self.rule, self.detail))
```

`host/tracking.py`:

```python
class GroupTracker:
    def __init__(self) -> None:
        self._next_step = {"p0": 0, "p1": 0}
        self._next_group = {"p0": 0, "p1": 0}
        self._partial: dict[str, tuple[int, int, int] | None] = {"p0": None, "p1": None}
        self._since_action: dict[str, list[int] | None] = {"p0": None, "p1": None}
        self.answered_steps = 0
        self._completed = 0
        self._abandoned = 0

    @property
    def completed_groups(self) -> int:
        return self._completed - self._abandoned

    def answered_by(self, seat: str) -> int:
        return self._next_step[seat]

    def check(self, sd: Mapping[str, Any]) -> None:
        seat = sd["acting_seat"]
        other = "p1" if seat == "p0" else "p0"
        group, context = sd["group"], sd["context"]
        key = (group["group_id"], group["substep_index"], group["substep_count"])
        if sd["seat_step"] != self._next_step[seat]:
            raise ValidatorViolation("V3", f"{seat} seat_step {sd['seat_step']} is not {self._next_step[seat]}")
        if self._partial[other] is not None:
            raise ValidatorViolation("V3", f"a decision for {seat} while {other}'s group {self._partial[other][0]} is partial")
        if context["rewind"]:
            if context["kind"] != "priority":
                raise ValidatorViolation("V3", "a rewind re-poses a priority decision")
            if self._since_action[seat] is None:
                raise ValidatorViolation("V3", f"a rewind for {seat} without a priority action to undo")
        partial = self._partial[seat]
        if partial is not None and not context["rewind"]:
            if key != (partial[0], partial[1] + 1, partial[2]):
                raise ValidatorViolation("V3", f"{seat} group {partial[0]} must continue at substep {partial[1] + 1} of {partial[2]}")
            return
        expected = partial[0] + 1 if partial is not None else self._next_group[seat]
        if key[:2] != (expected, 0):
            raise ValidatorViolation("V3", f"{seat} must start group {expected} at substep 0, got {key[0]} at {key[1]}")

    def answered(self, sd: Mapping[str, Any], *, chosen_kind: str) -> None:
        seat, group, context = sd["acting_seat"], sd["group"], sd["context"]
        self._next_step[seat] += 1
        self.answered_steps += 1
        if context["rewind"]:
            self._abandoned += len(self._since_action[seat] or [])
            self._partial[seat] = None
        if group["substep_index"] + 1 == group["substep_count"]:
            self._partial[seat] = None
            self._next_group[seat] = group["group_id"] + 1
            self._completed += 1
            for open_list in self._since_action.values():
                if open_list is not None:
                    open_list.append(group["group_id"])
        else:
            self._partial[seat] = (group["group_id"], group["substep_index"], group["substep_count"])
        if context["kind"] == "priority":
            self._since_action[seat] = [group["group_id"]] if chosen_kind != "pass" else None
```

`IdTracker` keeps per seat the zone of every id seen, the ids of the previous observation, and the ids that departed:

```python
    def check(self, seat: str, objects: Mapping[str, str]) -> None:
        zones = self._zones[seat]
        for object_id, zone in objects.items():
            if object_id in self._departed[seat]:
                raise ValidatorViolation("V7", f"object id {object_id} returned to {seat}'s observation after leaving it")
            if zones.get(object_id, zone) != zone:
                raise ValidatorViolation("V7", f"object id {object_id} appeared in zones {zones[object_id]} and {zone}")
        self._departed[seat] |= self._present[seat] - objects.keys()
        self._present[seat] = set(objects)
        zones.update(objects)
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_tracking.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/violation.py python/spellbench/host/tracking.py python/tests/test_host_tracking.py
git commit -m "Host: V3 group and rewind tracking, V7 id freshness"
```

### Task 11: Builtin bots on v2

**Effort:** 0.5 agent-day. **Wave:** 2. **Depends on:** Task 6.

**Files:**
- Create: `python/spellbench/builtins/__init__.py`, `builtins/uniform.py`, `builtins/heuristic.py`, `builtins/first.py`
- Create: `python/tests/test_builtins.py`

**Interfaces:**
- Consumes: `spellbench.bot` (`Decision`, `GameStart`, `GameOver`, `serve`) (Task 6).
- Produces:
  - `builtins.BUILTIN_BOTS: dict[str, type]`, `builtins.BUILTIN_VERSIONS = {"first": "2.0.0", "heuristic": "2.0.0", "uniform": "2.0.0"}`, `builtins.create_builtin_bot(name: str, *, seed: int = 0) -> Any` (raises `ValueError` for unknown names)
  - each bot: `on_game_start(game: bot.GameStart) -> None`, `choose(decision: bot.Decision) -> int` (a `candidate_id`), `on_game_over(game_over: bot.GameOver) -> None`; each module has `main() -> int` serving itself (`python -m spellbench.builtins.<name>`; `uniform` takes `--seed N`)
  - `builtins.uniform.SplitMix64`, `MASK64`, `DERIVATION_VERSION = "spellbench-arena-uniform-v2"`, `stream_seed(agent_seed: int, seed: int) -> int`

Behavior: `uniform` seeds `SplitMix64((agent_seed ^ seed) & MASK64)` at `game_start` (spec 10.6: "seeded from agent_seed") and picks `candidates[next() % len(candidates)]`. `first` picks the first candidate. `heuristic` picks, in order: `mulligan` with `keep: true`; the first `play_land`; the first `cast_spell`; the first `activate_mana_ability` or `activate_ability`; the first `declare_attack` with a non-null `defender`; a `declare_block` with `attacker: null`; `choose_starting_player` naming its own seat; else the first candidate. Copy `SplitMix64` verbatim from `arena/bots/uniform.py` (with its attribution to mtg-kernel's `determinism.py`).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_builtins.py`:

```python
"""The builtin bots on v2: uniform seeded from agent_seed, first, heuristic."""

from __future__ import annotations

import subprocess
import sys

import pytest

from spellbench import wire
from spellbench.bot import Decision, GameStart
from spellbench.builtins import BUILTIN_VERSIONS, create_builtin_bot

# Bots read leniently, so short semantics are enough here (Task 7's samples land in the same wave).
SAMPLES = {
    "pass": {"kind": "pass"},
    "play_land": {"kind": "play_land", "face": 0},
    "cast_spell": {"kind": "cast_spell", "method": "normal"},
    "activate_ability": {"kind": "activate_ability", "ability_index": 0},
    "activate_mana_ability": {"kind": "activate_mana_ability", "ability_index": 0, "mana_choice": "R"},
    "mulligan": {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True},
    "declare_attack": {"kind": "declare_attack", "defender": {"player": "p1"}},
    "declare_block": {"kind": "declare_block", "attacker": None},
    "choose_option": {"kind": "choose_option", "option_index": 0, "option_count": 2},
    "choose_boolean": {"kind": "choose_boolean", "value": True},
}


def _decision(*kinds: str) -> Decision:
    candidates = [{"candidate_id": index, "semantic": SAMPLES[kind], "display_text": None} for index, kind in enumerate(kinds)]
    return Decision.from_request({"game_id": "g-1", "decision": {"candidates": candidates}})


def _start(bot, *, agent_seed: int, seat: str = "p0") -> None:
    bot.on_game_start(GameStart.from_request({"game_id": "g-1", "seat": seat, "agent_seed": agent_seed}))


def test_versions_are_2_0_0() -> None:
    assert BUILTIN_VERSIONS == {"first": "2.0.0", "heuristic": "2.0.0", "uniform": "2.0.0"}


def test_uniform_follows_the_agent_seed() -> None:
    decision = _decision(*sorted(SAMPLES)[:8])

    def picks(agent_seed: int, seed: int = 11) -> list[int]:
        bot = create_builtin_bot("uniform", seed=seed)
        _start(bot, agent_seed=agent_seed)
        return [bot.choose(decision) for _ in range(40)]

    assert picks(8103969398531465) == picks(8103969398531465)
    assert picks(8103969398531465) != picks(1382627979884484)
    assert picks(8103969398531465) != picks(8103969398531465, seed=12)
    assert set(picks(5)) <= set(range(8))


def test_uniform_needs_a_game() -> None:
    with pytest.raises(RuntimeError):
        create_builtin_bot("uniform").choose(_decision("pass"))


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        (("pass", "play_land", "cast_spell"), 1),
        (("pass", "cast_spell", "activate_ability"), 1),
        (("pass", "activate_mana_ability"), 1),
        (("mulligan",), 0),
        (("declare_block",), 0),
        (("pass", "choose_option"), 0),
    ],
)
def test_heuristic_priorities(kinds: tuple[str, ...], expected: int) -> None:
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1)
    assert bot.choose(_decision(*kinds)) == expected


def test_heuristic_attacks_and_does_not_block() -> None:
    attack = dict(SAMPLES["declare_attack"])
    candidates = [{"candidate_id": 0, "semantic": {**attack, "defender": None}, "display_text": None},
                  {"candidate_id": 1, "semantic": attack, "display_text": None}]
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1)
    assert bot.choose(Decision.from_request({"game_id": "g-1", "decision": {"candidates": candidates}})) == 1


def test_first_takes_the_first_candidate_and_serves_over_stdio() -> None:
    assert create_builtin_bot("first").choose(_decision("pass", "play_land")) == 0
    lines = b"".join(wire.canonical_json_line({"request_type": kind, "protocol": "spellbench/v2", "request_id": f"r-{i}", **extra})
                     for i, (kind, extra) in enumerate([("hello", {}), ("game_start", {"game_id": "g-1"}),
                                                        ("choose", {"game_id": "g-1", "decision": {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}}),
                                                        ("game_over", {"game_id": "g-1", "terminal": {}})]))
    result = subprocess.run([sys.executable, "-m", "spellbench.builtins.first"], input=lines, capture_output=True, timeout=30)
    assert result.returncode == 0 and b'"name":"first"' in result.stdout and b'"version":"2.0.0"' in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_builtins.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.builtins`).

- [ ] **Step 3: Implement the package**

`builtins/__init__.py` mirrors `arena/bots/__init__.py` with the v2 modules. `heuristic.HeuristicBot` stores `game.seat` at `on_game_start` and applies the order above over `decision.candidates` (returning `candidate_id`, never the index). `uniform.UniformBot`:

```python
def stream_seed(agent_seed: int, seed: int) -> int:
    return (agent_seed ^ seed) & MASK64


class UniformBot:
    name = BOT_NAME
    version = BOT_VERSION

    def __init__(self, seed: int = 0) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("uniform bot seed must be a nonnegative integer")
        self._seed = seed
        self._stream: SplitMix64 | None = None

    def on_game_start(self, game: GameStart) -> None:
        self._stream = SplitMix64(stream_seed(game.agent_seed or 0, self._seed))

    def choose(self, decision: Decision) -> int:
        if self._stream is None:
            raise RuntimeError("choose before game_start")
        return decision.candidates[self._stream.next() % len(decision.candidates)].candidate_id

    def on_game_over(self, game_over: GameOver) -> None:
        self._stream = None
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_builtins.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass (the v1 `arena/bots` package is untouched until Task 44).

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/builtins python/tests/test_builtins.py
git commit -m "Builtins: uniform, heuristic and first on protocol v2 (2.0.0)"
```

### Task 12: Ledger rows v2

**Effort:** 0.5 agent-day. **Wave:** 2. **Depends on:** Task 1.

**Files:**
- Create: `python/spellbench/arena/ledger.py`
- Create: `python/tests/test_ledger.py`

**Interfaces:**
- Consumes: `_schema` (Task 1).
- Produces (`spellbench.arena.ledger`):
  - `LEDGER_SCHEMA = "spellbench-match-ledger/v2"`, `FORFEIT_CAUSES = frozenset({"timeout", "stalling", "malformed_response", "invalid_selection", "agent_error", "transport_error"})`, `ENGINE_FAULTS = ("error", "timeout", "transport", "malformed", "terminal_counts")`
  - `LedgerSeat(seat, bot_id, name, version)`; `LedgerDeck(deck_id, name, catalog_id: str | None)`; `Adjudication(kind: str, detail: str, cause: str | None = None, loser_seat: str | None = None)` with kinds `forfeit`, `halt`, `mandatory_loop`; `LastSelection(seat, bot_id)`
  - `LedgerRow(game_index, game_id, matchup_index, pair_index, pair_slot, format, seats: tuple[LedgerSeat, LedgerSeat], decks: tuple[LedgerDeck, LedgerDeck], outcome, classification, winner, winner_bot_id, reason, adjudication: Adjudication | None, step_count, decision_count, decisions_checked, last_selection: LastSelection | None, game_digest: str, engine: dict)` with `rated -> bool`, `bot_id_at(seat) -> str`, `to_json()`, `from_json(value, context="ledger")`
  - `parse_ledger(rows: Iterable[dict]) -> tuple[LedgerRow, ...]`

Row rules (spec 9.5, 11.5, 11.8; Decisions 4 and 5): `pair_slot` is 0 or 1; `engine` is exactly the four provenance fields; `game_digest` matches `sha256:[0-9a-f]{64}`; `step_count <= decisions_checked <= step_count + 1`. By classification:
- `natural`: outcome and winner paired; adjudication null, or `mandatory_loop` with outcome `draw` and reason `mandatory_loop`.
- `forfeit`: outcome `p0_win` or `p1_win`, a `forfeit` adjudication whose `loser_seat` is the other seat, reason `forfeit:<cause>`.
- `truncated`: outcome `truncated`, winner null, no adjudication.
- `halted`: outcome `halted`, winner null; an adjudication is a `halt` whose reason starts `host_validator:V<n>` or `host_engine_fault:<fault>`; without one, the engine's own reason.
- `last_selection` may be non-null only for `truncated` and `halted` rows; `winner_bot_id` follows the winner's seat.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_ledger.py`:

```python
"""Ledger rows v2 (spec 11.5, 11.8)."""

from __future__ import annotations

import pytest

from spellbench.arena.ledger import LedgerRow, parse_ledger
from spellbench.errors import ValidationError

A, B = "a" * 64, "b" * 64
ENGINE = {"engine_name": "fake", "engine_version": "1", "rules_snapshot_id": "r", "card_pool_identity": "p"}
DECK = {"deck_id": "sha256:" + "0" * 64, "name": "Burn", "catalog_id": "Burn"}


def row(**changes) -> dict:
    value = {
        "schema": "spellbench-match-ledger/v2", "game_index": 0, "game_id": "g-f67d7fe78c792984", "matchup_index": 0,
        "pair_index": 0, "pair_slot": 0, "format": "pauper-bo1",
        "seats": [{"seat": "p0", "bot_id": A, "name": "a", "version": "1"}, {"seat": "p1", "bot_id": B, "name": "b", "version": "1"}],
        "decks": [DECK, DECK], "outcome": "p0_win", "classification": "natural", "winner": "p0", "winner_bot_id": A,
        "reason": "score", "adjudication": None, "step_count": 4, "decision_count": 4, "decisions_checked": 4,
        "last_selection": None, "game_digest": "sha256:" + "1" * 64, "engine": ENGINE,
    }
    value.update(changes)
    return value


VALID = {
    "natural": row(),
    "forfeit": row(outcome="p1_win", classification="forfeit", winner="p1", winner_bot_id=B, reason="forfeit:stalling",
                   adjudication={"kind": "forfeit", "cause": "stalling", "loser_seat": "p0", "detail": "cap reached"}, decisions_checked=5),
    "validator halt": row(outcome="halted", classification="halted", winner=None, winner_bot_id=None, reason="host_validator:V4",
                          adjudication={"kind": "halt", "detail": "stale reference"}, decisions_checked=5,
                          last_selection={"seat": "p1", "bot_id": B}),
    "engine halt": row(outcome="halted", classification="halted", winner=None, winner_bot_id=None, reason="engine_contract_failure:x"),
    "mandatory loop": row(outcome="draw", winner=None, winner_bot_id=None, reason="mandatory_loop",
                          adjudication={"kind": "mandatory_loop", "detail": "no real choice in the last 250 decisions"}),
    "truncated": row(outcome="truncated", classification="truncated", winner=None, winner_bot_id=None, reason="max_steps",
                     last_selection={"seat": "p0", "bot_id": A}),
}


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_rows_round_trip(name: str) -> None:
    (parsed,) = parse_ledger([VALID[name]])
    assert parsed.to_json() == VALID[name]
    assert parsed.rated == (name in ("natural", "forfeit", "mandatory loop"))


@pytest.mark.parametrize(
    "bad",
    [
        row(pair_slot=2),
        row(last_selection={"seat": "p0", "bot_id": A}),                               # only halted and truncated rows
        row(adjudication={"kind": "halt", "detail": "x"}),                            # natural rows never halt
        row(decisions_checked=6),
        row(game_digest="sha256:xyz"),
        row(**{**VALID["forfeit"], "adjudication": {**VALID["forfeit"]["adjudication"], "loser_seat": "p1"}}),
        row(**{**VALID["forfeit"], "reason": "forfeit:boredom",
               "adjudication": {**VALID["forfeit"]["adjudication"], "cause": "boredom"}}),
        row(**{**VALID["validator halt"], "reason": "host_validator:V11"}),
        row(**{**VALID["truncated"], "winner": "p0", "winner_bot_id": A}),
    ],
)
def test_invalid_rows_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        parse_ledger([bad])


def test_seat_lookups() -> None:
    (parsed,) = parse_ledger([row()])
    assert (parsed.bot_id_at("p0"), parsed.bot_id_at("p1"), parsed.pair_slot) == (A, B, 0)
    assert isinstance(parsed, LedgerRow)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_ledger.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.arena.ledger`).

- [ ] **Step 3: Implement `arena/ledger.py`**

Follow the v1 `store.LedgerRow` structure (frozen dataclass, checks in `__post_init__`, `to_json` with the seats sorted by seat, `from_json` with `store.require_keys` over the exact field list above plus `schema`), applying the row rules. `LedgerDeck.to_json()` is `{"deck_id", "name", "catalog_id"}`; `LastSelection.to_json()` is `{"seat", "bot_id"}` and its `bot_id` must equal that seat's bot. Import `store` only for `require_keys` (a function, no schema constants), so Task 33 can point `store.LEDGER_SCHEMA` here.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_ledger.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/ledger.py python/tests/test_ledger.py
git commit -m "Arena: ledger rows v2 with digests, attribution and host adjudications"
```

### Task 13: The fake engine's board model

**Effort:** 0.5 agent-day. **Wave:** 2. **Depends on:** Tasks 1, 2.

**Files:**
- Create: `python/tests/fake_v2_world.py`
- Create: `python/tests/test_fake_v2_world.py`

**Interfaces:**
- Consumes: `run_secret.object_id` (Task 2); `_schema.OBSERVATION_FLAGS` (Task 1).
- Produces (`python/tests/fake_v2_world.py`, imported by the fake engine and the scenario modules):
  - `CARDS: dict[str, dict[str, Any]]`: characteristics of the fixture cards (at least Mountain, Island, Lightning Bolt, Counterspell, Brainstorm, Preordain, Grizzly Bears, Monastery Swiftspear, Spellstutter Sprite, Chainer's Edict, Lim-Dûl's Vault, Barbarian Class, Relic of Progenitus, Pithing Needle, and one modal double-faced card with `full_name` "A // B" form)
  - `@dataclass class Obj` (internal id, name, owner, controller, zone, `zone_changes`, face-down, token, copy, permanent state: tapped, summoning_sick, damage, counters, `attached_to`, `attack_target`, `blocking`, phased_out, statuses, class_level, chosen, `exiled_by`, `face_down_visible_to`)
  - `@dataclass class StackItem(internal, kind, source, targets, divided=None, modes=None, x_value=None, text=None)`
  - `@dataclass(frozen=True) class Posed(seat: str, candidates: list[dict], substep: tuple[int, int] = (0, 1), kind: str | None = None, purpose: str | None = None, source: dict | None = None, rewind: bool = False, text: str | None = None, extensions: dict = {})` (one decision a scenario poses; the engine assigns candidate ids, `seat_step` and `group_id`)
  - `@dataclass(frozen=True) class Scenario(name: str, decklist: list[dict], engine_args: tuple[str, ...], script: Callable[[World], Generator[Posed, int, None]], outcome: tuple[str, str | None, str] = ("draw", None, "scenario_complete"))`
  - `class World(game_secret: bytes, *, flags: Mapping[str, bool])` with `add(name, *, owner, zone, controller=None, internal=None, **state) -> int`, `move(internal, zone, *, controller=None, library_position=0, face_down=False) -> None`, `object_id(viewer, internal) -> str`, `look(viewer, internal) -> str`, `end_looks(viewer) -> None`, `reference(viewer, internal) -> dict | None`, `target(viewer, target: dict | None) -> dict | None`, `observation(viewer) -> dict`; public state attributes (turn, phase_step, active_seat, priority_seat, life, poison, counters, mana_pool, lands_played, mulligans, designations, progress, day_night, passed_seats, libraries, stack, pending_triggers, known) that scenarios edit directly

Rules the model follows (spec 5.3, 6): ids come from `object_id(game_secret, f"{viewer}:card-{internal}:z{zone_changes}")` for visible objects and `f"{viewer}:card-{internal}:z{zone_changes}:look:{n}"` for looks into hidden zones, where `n` counts that viewer's looks during the stay and a look id stays fixed until `end_looks`; `move` bumps `zone_changes`, clears permanent state, and sets `face_down` to its argument (a face-down card leaving the battlefield is revealed, CR 708.9; `face_down=True` exiles a card face down); library order is index 0 at the top; face-down objects on the battlefield or the stack show face-down characteristics (a nameless colorless 2/2 creature) and `card_name: null` to every viewer but the controller, and face-down exiled cards show their name only to `face_down_visible_to`; references to objects outside the viewer's observation are `None`; each optional field of spec 6.9 is `null` when its flag is off; `known` entries carry `object_id` only for a card in the viewer's current looks and come out sorted by the spec 6.7 key.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_fake_v2_world.py`:

```python
"""The fake engine's board model keeps the spec's id and visibility rules."""

from __future__ import annotations

from spellbench.run_secret import RunSecret

from fake_v2_world import World

GAME0 = RunSecret(bytes(range(32))).game_secret(0)
FLAGS_OFF = dict.fromkeys(("poison", "player_counters", "designations", "player_progress", "day_night", "passed_seats",
                           "pending_triggers", "keywords", "full_name", "exiled_by", "stack_text", "permanent_details",
                           "known_cards"), False)


def test_ids_follow_the_spec_16_vectors() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    world.add("Island", owner="p0", zone="library", internal=17)
    world.move(17, "hand")
    world.move(17, "library")                       # two zone changes: "card-17:z2"
    assert world.look("p0", 17) == "o-794a5cb152c9620f"
    assert world.look("p0", 17) == "o-794a5cb152c9620f"   # stable within one effect
    world.end_looks("p0")
    assert world.look("p0", 17) == "o-e18a35822cc60e1c"   # fresh on the next look
    visible = World(GAME0, flags=FLAGS_OFF)                # the plain-id vector: a visible object at z2
    visible.add("Island", owner="p0", zone="hand", internal=17)
    visible.move(17, "graveyard")
    visible.move(17, "exile")
    assert (visible.object_id("p0", 17), visible.object_id("p1", 17)) == ("o-0a3647243d16bf78", "o-e5e4b7ed2a0730e4")


def test_a_zone_change_gives_a_fresh_id_per_viewer() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    bears = world.add("Grizzly Bears", owner="p1", zone="battlefield")
    before = {seat: world.object_id(seat, bears) for seat in ("p0", "p1")}
    world.move(bears, "graveyard")
    after = {seat: world.object_id(seat, bears) for seat in ("p0", "p1")}
    assert before["p0"] != before["p1"] and all(before[seat] != after[seat] for seat in ("p0", "p1"))


def test_hidden_information_stays_hidden() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    world.add("Counterspell", owner="p1", zone="hand")
    morph = world.add("Grizzly Bears", owner="p1", zone="battlefield", face_down=True)
    world.add("Mountain", owner="p0", zone="library")
    view = world.observation("p0")
    assert view["players"][1]["hand"] is None and view["players"][1]["hand_count"] == 1
    (record,) = view["players"][1]["battlefield"]
    assert record["card_name"] is None and record["characteristics"]["power"] == 2 and record["characteristics"]["colors"] == []
    assert world.observation("p1")["players"][1]["battlefield"][0]["card_name"] == "Grizzly Bears"
    assert all(entry["zone"] != "library" for player in view["players"] for zone in ("battlefield", "graveyard", "exile", "command")
               for entry in player[zone])
    world.move(morph, "graveyard")
    assert world.reference("p0", morph)["zone"] == "graveyard"


def test_optional_fields_follow_the_flags() -> None:
    off = World(GAME0, flags=FLAGS_OFF).observation("p0")
    assert off["day_night"] is None and off["passed_seats"] is None and off["pending_triggers"] is None
    assert off["players"][0]["poison"] is None and off["known"] == []
    on = World(GAME0, flags=dict.fromkeys(FLAGS_OFF, True)).observation("p0")
    assert on["day_night"] in ("day", "night", "none") and on["passed_seats"] == [] and on["players"][0]["poison"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_fake_v2_world.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: fake_v2_world`).

- [ ] **Step 3: Implement `fake_v2_world.py`**

Implement the model to the rules above; `observation(viewer)` returns every field of spec 6.2 to 6.6 in the spec's shapes (players `p0` then `p1`; zone arrays in insertion order, oldest first; `mana_pool` with the six symbols; `characteristics` from `CARDS` with `colors` in spec order; `permanent` for battlefield objects; stack entries with references resolved per viewer and targets that left becoming `None`). Keep the module independent of `spellbench` internals other than `run_secret.object_id`, so it doubles as a reference an adapter author can read.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_fake_v2_world.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/tests/fake_v2_world.py python/tests/test_fake_v2_world.py
git commit -m "Tests: the v2 fake engine's board model with per-viewer ids"
```

## Wave 3

Tasks 14 to 16 build their test seat decisions with `v2_sample_semantics.seat_decision` (Task 7), which wraps the spec 6.1 observation (Task 8) and defaults to the candidates `[pass, play_land, cast_spell]`.

### Task 14: Seat, reference and face-down checks (V2, V4, V6)

**Effort:** 0.5 agent-day. **Wave:** 3. **Depends on:** Tasks 7, 8, 10.

**Files:**
- Create: `python/spellbench/host/refs.py`
- Create: `python/tests/test_host_refs.py`

**Interfaces:**
- Consumes: `observation.observation_objects`, `observation.observation_references`, `observation.zone_records` (Task 8); `candidates.object_references` (Task 7); `host.violation.ValidatorViolation` (Task 10). Inputs are seat decisions that already passed V1.
- Produces (`spellbench.host.refs`): `check_seat(seat_decision: Mapping) -> None` (V2), `check_references(seat_decision: Mapping) -> None` (V4), `check_face_down(seat_decision: Mapping) -> None` (V6).

Rules (spec 5.1, 6.8, 11.3): V2, `observation.viewer == acting_seat`. V4, every id among the observation's held objects appears once; every non-null reference inside the observation, in any candidate's semantic, and `context.source` equals the held object with its id field for field; a non-null reference to an id that is not held fails ("absent objects become null"). V6, a face-down object on the battlefield or the stack whose controller is not the viewer has `card_name` null (and, for records, `full_name` null).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_refs.py`:

```python
"""V2, V4 and V6 (spec 5.1, 6.8, 11.3)."""

import pytest

from spellbench.host.refs import check_face_down, check_references, check_seat
from spellbench.host.violation import ValidatorViolation

from v2_sample_semantics import R_BOLT, R_STACK, R_SWIFTSPEAR, SAMPLES, seat_decision


def _rule(check, decision) -> str:
    with pytest.raises(ValidatorViolation) as caught:
        check(decision)
    return caught.value.rule


def test_a_consistent_decision_passes() -> None:
    decision = seat_decision()
    check_seat(decision)
    check_references(decision)
    check_face_down(decision)


def test_v2_the_viewer_is_the_acting_seat() -> None:
    assert _rule(check_seat, seat_decision(acting_seat="p1")) == "V2"


@pytest.mark.parametrize(
    "decision",
    [
        seat_decision([SAMPLES["pass"], {**SAMPLES["cast_spell"], "source": {**R_BOLT, "card_name": "Chain Lightning"}}]),
        seat_decision([SAMPLES["pass"], {**SAMPLES["cast_spell"], "source": {**R_BOLT, "zone": "graveyard"}}]),
        seat_decision([SAMPLES["pass"], {**SAMPLES["activate_ability"], "source": {**R_SWIFTSPEAR, "controller_seat": "p1"}}]),
        seat_decision([SAMPLES["choose_target"]], kind="choice"),          # its source is a stack entry that is not held
        seat_decision(source=R_STACK),                                      # context.source absent too
    ],
)
def test_v4_references_equal_the_held_object(decision: dict) -> None:
    assert _rule(check_references, decision) == "V4"


def test_v4_ids_are_unique_and_observation_links_are_checked() -> None:
    duplicate = seat_decision()
    duplicate["observation"]["players"][0]["hand"][1]["object_id"] = R_BOLT["object_id"]
    assert _rule(check_references, duplicate) == "V4"
    stale_block = seat_decision()
    sprite = stale_block["observation"]["players"][1]["battlefield"][0]
    swift = stale_block["observation"]["players"][0]["battlefield"][0]
    swift["permanent"].update(attacking=True, attack_target={"player": "p1"})
    sprite["permanent"].update(blocking=True, blocked_attackers=[{**R_SWIFTSPEAR, "card_name": "Goblin Guide"}])
    assert _rule(check_references, stale_block) == "V4"


def test_v6_face_down_names_are_hidden_from_other_seats() -> None:
    leak = seat_decision()
    leak["observation"]["players"][1]["battlefield"][0]["face_down"] = True   # p1's face-down Sprite, still named
    assert _rule(check_face_down, leak) == "V6"
    own = seat_decision()
    own["observation"]["players"][0]["battlefield"][0]["face_down"] = True    # the viewer's own: it may look (CR 708.5)
    check_face_down(own)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_refs.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.refs`).

- [ ] **Step 3: Implement `host/refs.py`**

```python
def check_seat(sd: Mapping[str, Any]) -> None:
    if sd["observation"]["viewer"] != sd["acting_seat"]:
        raise ValidatorViolation("V2", f"observation.viewer {sd['observation']['viewer']} is not acting_seat {sd['acting_seat']}")


def _held(observation: Mapping[str, Any]) -> dict[str, dict]:
    held: dict[str, dict] = {}
    for path, reference in observation_objects(observation):
        if reference["object_id"] in held:
            raise ValidatorViolation("V4", f"object id {reference['object_id']} appears twice in the observation ({path})")
        held[reference["object_id"]] = reference
    return held


def check_references(sd: Mapping[str, Any]) -> None:
    held = _held(sd["observation"])
    references = [(f"observation.{path}", ref) for path, ref in observation_references(sd["observation"])]
    for index, candidate in enumerate(sd["candidates"]):
        references += [(f"candidates[{index}].semantic.{path}", ref) for path, ref in object_references(candidate["semantic"])]
    if sd["context"]["source"] is not None:
        references.append(("context.source", sd["context"]["source"]))
    for path, ref in references:
        record = held.get(ref["object_id"])
        if record is None:
            raise ValidatorViolation("V4", f"{path} references {ref['object_id']}, which is not in the observation")
        if dict(ref) != record:
            raise ValidatorViolation("V4", f"{path} differs from the observation record of {ref['object_id']}")
```

`check_face_down` walks `zone_records` (battlefield arrays) and `observation["stack"]`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_refs.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/refs.py python/tests/test_host_refs.py
git commit -m "Host: V2 seat, V4 references, V6 face-down checks"
```

### Task 15: Hidden zones and knowledge (V5)

**Effort:** 0.5 agent-day. **Wave:** 3. **Depends on:** Tasks 7, 8, 10.

**Files:**
- Create: `python/spellbench/host/hidden.py`
- Create: `python/tests/test_host_hidden.py`

**Interfaces:**
- Consumes: `observation.zone_records` (Task 8), `candidates.object_references` (Task 7), `host.violation.ValidatorViolation` (Task 10).
- Produces (`spellbench.host.hidden`): `check_hidden_zones(seat_decision: Mapping) -> None` (V5), `known_sort_key(entry: Mapping) -> tuple`, `hidden_candidate_key(semantic: Mapping, viewer: str) -> tuple | None`.

Rules (spec 6.3, 6.7, 7.1, 11.3 V5): the other seat's `hand` is null; the viewer's `hand` has exactly `hand_count` records; no zone-array record has zone `library`; `known` entries: a `hand` entry names the other seat (never the viewer) and has both positions null; a `library` entry has exactly one non-null position, except `how: "searching"`, which has at most one; a seat's hand entries never outnumber its `hand_count`; `object_id` is non-null only with `how` in `looked_at`, `revealed`, `searching`; the list is sorted by `(owner_seat, zone, card_name, position_from_top, position_from_bottom, how, object_id)` with nulls first. Candidates that reference hidden-zone cards (zone `library`, or zone `hand` owned by the other seat) appear among themselves in `(card_name, object_id)` order; for a candidate with several such references, the key is the tuple of their `(card_name, object_id)` pairs in `object_references` order, with a null name sorting first.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_hidden.py`:

```python
"""V5: hidden zones, knowledge entries and hidden-card candidate order (spec 6.7, 7.1)."""

import pytest

from spellbench.host.hidden import check_hidden_zones, known_sort_key
from spellbench.host.violation import ValidatorViolation

from v2_sample_semantics import SAMPLES, seat_decision

LIB = lambda object_id, name: {"object_id": object_id, "card_name": name, "owner_seat": "p0", "controller_seat": "p0", "zone": "library"}


def _known(entry_overrides: dict) -> dict:
    return {"owner_seat": "p1", "zone": "hand", "card_name": "Counterspell", "object_id": None,
            "position_from_top": None, "position_from_bottom": None, "how": "revealed", **entry_overrides}


def _with(mutate) -> dict:
    decision = seat_decision()
    mutate(decision["observation"])
    return decision


def test_the_spec_example_passes() -> None:
    check_hidden_zones(seat_decision())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o["players"][1].update(hand=[]),                                 # the other seat's hand shown
        lambda o: o["players"][0].update(hand_count=3),                             # hand and hand_count disagree
        lambda o: o["players"][0]["hand"][1].update(zone="library"),                # a library object in a zone array
        lambda o: o.update(known=list(reversed(o["known"]))),                       # unsorted
        lambda o: o["known"].append(_known({"owner_seat": "p0"})),                  # the viewer's own hand listed
        lambda o: o["known"].append(_known({"position_from_top": 0})),              # a hand entry with a position
        lambda o: o["known"].insert(1, _known({"owner_seat": "p0", "zone": "library", "how": "looked_at", "card_name": "Mountain"})),
        lambda o: o["known"].extend([_known({})] * 3),                              # 4 entries for a hand of 3
        lambda o: o["known"].append(_known({"how": "from_public_zone", "object_id": "o-1"})),
    ],
)
def test_v5_violations(mutate) -> None:
    with pytest.raises(ValidatorViolation) as caught:
        check_hidden_zones(_with(mutate))
    assert caught.value.rule == "V5"


def test_a_search_entry_may_have_no_position() -> None:
    # Null positions sort first, so the search entry precedes the positioned Mountain.
    check_hidden_zones(_with(lambda o: o["known"].insert(0, _known(
        {"owner_seat": "p0", "zone": "library", "card_name": "Mountain", "how": "searching", "object_id": "o-9"}))))


def test_hidden_card_candidates_are_in_name_then_id_order() -> None:
    search = lambda ref: {**SAMPLES["select_object"], "purpose": "search", "choice": {"object": ref}, "minimum": 0}
    ordered = [search(LIB("o-b", "Island")), search(LIB("o-a", "Mountain")), SAMPLES["finish_selection"]]
    check_hidden_zones(seat_decision(ordered, kind="choice"))
    with pytest.raises(ValidatorViolation, match="order"):
        check_hidden_zones(seat_decision(list(reversed(ordered[:2])), kind="choice"))


def test_the_sort_key_puts_nulls_first() -> None:
    entries = [_known({"zone": "library", "how": "looked_at", "position_from_top": 0}),
               _known({"zone": "library", "how": "looked_at", "position_from_bottom": 0})]
    assert sorted(entries, key=known_sort_key) == [entries[1], entries[0]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_hidden.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.hidden`).

- [ ] **Step 3: Implement `host/hidden.py`**

```python
def _nullable(value: Any) -> tuple:
    return (0, "") if value is None else (1, value)


def known_sort_key(entry: Mapping[str, Any]) -> tuple:
    return (entry["owner_seat"], entry["zone"], entry["card_name"], _nullable(entry["position_from_top"]),
            _nullable(entry["position_from_bottom"]), entry["how"], _nullable(entry["object_id"]))


def hidden_candidate_key(semantic: Mapping[str, Any], viewer: str) -> tuple | None:
    pairs = tuple((_nullable(ref["card_name"]), ref["object_id"]) for _, ref in object_references(semantic)
                  if ref["zone"] == "library" or (ref["zone"] == "hand" and ref["owner_seat"] != viewer))
    return pairs or None
```

`check_hidden_zones` applies the rules in the order listed above, each failure a `ValidatorViolation("V5", ...)` naming the path; the order checks compare consecutive keys with `>` (equal keys are allowed: two identical entries are legal).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_hidden.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/hidden.py python/tests/test_host_hidden.py
git commit -m "Host: V5 hidden zones, knowledge entries and hidden-card order"
```

### Task 16: Declarations and context (V8, V9)

**Effort:** 0.5 agent-day. **Wave:** 3. **Depends on:** Tasks 7, 8, 9, 10.

**Files:**
- Create: `python/spellbench/host/declarations.py`
- Create: `python/tests/test_host_declarations.py`

**Interfaces:**
- Consumes: `messages.EngineProfile`, `messages.Rules` (Task 9); `candidates.family` (Task 7); `observation.zone_records` (Task 8); `host.violation.ValidatorViolation` (Task 10).
- Produces (`spellbench.host.declarations`): `check_declarations(seat_decision: Mapping, profile: EngineProfile, rules: Rules) -> None` (V8), `check_context(seat_decision: Mapping) -> None` (V9).

Rules. V8 (spec 6.9, 7.6, 8, 12.2, 14): every candidate kind is in `profile.decision_kinds`; no `mulligan` candidate while `rules.mulligan == "none"`; no `choose_starting_player` while `rules.starting_player == "host_assigned"`; `context.rewind` only when `profile.rewind`; every `extensions` key is in `rules.extensions`; for each optional field, a false flag means the field is null everywhere, and a true flag means it is non-null everywhere except the cases spec 6.9 lists (`full_name`, `exiled_by`, stack `text` may be null; `class_level` is non-null exactly when the permanent's subtypes include `class`). The field map: `poison`, `player_counters` (`counters`), `designations`, `player_progress` (`progress`) per player; `day_night`, `passed_seats`, `pending_triggers` on the observation; `keywords` in every non-null `characteristics` (records and stack entries); `full_name` and `exiled_by` on records; `stack_text` on stack entries; `permanent_details` on each permanent's `statuses`, `class_level`, `chosen`. V9 (spec 7.1): all candidates are of `context.kind`'s family, except a choice decision with `context.purpose == "mana_payment"`, whose candidates are `optional_cost` and `activate_mana_ability` only and include an `optional_cost` with `pay: false`; `activate_mana_ability` in a choice decision requires that purpose; `mana_payment` appears only on a choice decision.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_declarations.py`:

```python
"""V8 declarations and V9 context (spec 6.9, 7.1, 7.6)."""

import pytest

from spellbench.host.declarations import check_context, check_declarations
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import EngineProfile, Rules

from v2_sample_semantics import SAMPLES, seat_decision

FLAGS = {"poison": False, "player_counters": False, "designations": True, "player_progress": False, "day_night": False,
         "passed_seats": True, "pending_triggers": True, "keywords": True, "full_name": False, "exiled_by": True,
         "stack_text": False, "permanent_details": True, "known_cards": True}   # the spec 6.1 example's flags
PROFILE_JSON = {"rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]}, "observation": FLAGS,
                "decision_kinds": ["pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability", "optional_cost",
                                   "choose_target", "declare_attack", "declare_block", "mulligan", "choose_starting_player"],
                "engine_defaults": {"trigger_order": None, "replacement_order": None, "combat_damage_assignment": None, "mana_payment": None},
                "rewind": False, "fairness": {"noninterference_probe": False}, "extensions": [{"name": "x_kernel_v5", "native_ids": True}]}
RULES_JSON = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
              "card_name_domain": {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697",
                                   "names": ["Lightning Bolt", "Mountain"]}, "extensions": [], "probe": False}
PROFILE, RULES = EngineProfile.from_json(PROFILE_JSON), Rules.from_json(RULES_JSON)


def _v8(decision) -> None:
    check_declarations(decision, PROFILE, RULES)


def _swift(decision) -> dict:
    return decision["observation"]["players"][0]["battlefield"][0]


def test_the_spec_example_matches_its_declarations() -> None:
    _v8(seat_decision())


@pytest.mark.parametrize(
    "decision",
    [
        seat_decision([SAMPLES["pass"], SAMPLES["choose_name"]]),                         # an undeclared kind
        seat_decision([SAMPLES["mulligan"]], kind="choice"),                              # mulligan under rules.mulligan none
        seat_decision([SAMPLES["choose_starting_player"]], kind="choice"),                # host_assigned starting player
        seat_decision(rewind=True),                                                       # rewind not declared
        seat_decision(extensions={"x_kernel_v5": {}}),                                    # declared but not enabled
    ],
)
def test_v8_kinds_rules_and_extensions(decision: dict) -> None:
    with pytest.raises(ValidatorViolation) as caught:
        _v8(decision)
    assert caught.value.rule == "V8"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["observation"]["players"][0].update(poison=0),                            # flag off, value present
        lambda d: d["observation"].update(passed_seats=None),                                 # flag on, value missing
        lambda d: d["observation"]["players"][0]["hand"][0]["characteristics"].update(keywords=None),
        lambda d: _swift(d)["permanent"].update(class_level=2),                               # not a Class
        lambda d: (_swift(d)["characteristics"]["subtypes"].append("class"), _swift(d)["permanent"].update(class_level=None)),
        lambda d: _swift(d)["permanent"].update(statuses=None),
    ],
)
def test_v8_optional_fields_follow_the_flags(mutate) -> None:
    decision = seat_decision()
    mutate(decision)
    with pytest.raises(ValidatorViolation) as caught:
        _v8(decision)
    assert caught.value.rule == "V8"


def test_v8_allowed_nulls_with_the_flag_on() -> None:
    decision = seat_decision()
    assert _swift(decision)["exiled_by"] is None     # flag on: null is allowed for exiled_by
    _v8(decision)


MANA = [{**SAMPLES["optional_cost"], "cost": "unless_payment", "pay": True},
        {**SAMPLES["optional_cost"], "cost": "unless_payment", "pay": False},
        SAMPLES["activate_mana_ability"]]


def test_v9_context_matches_the_family_with_the_mana_payment_exception() -> None:
    check_context(seat_decision())
    check_context(seat_decision(MANA, kind="choice", purpose="mana_payment"))
    for decision in (
        seat_decision(kind="choice"),                                                   # priority kinds in a choice decision
        seat_decision([SAMPLES["pass"], SAMPLES["choose_target"]]),                    # mixed families
        seat_decision(MANA, kind="choice"),                                             # mana abilities without the purpose
        seat_decision(MANA[:1] + MANA[2:], kind="choice", purpose="mana_payment"),     # no pay: false
        seat_decision(MANA + [SAMPLES["choose_target"]], kind="choice", purpose="mana_payment"),
        seat_decision(purpose="mana_payment"),                                          # the purpose on a priority decision
    ):
        with pytest.raises(ValidatorViolation) as caught:
            check_context(decision)
        assert caught.value.rule == "V9"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_declarations.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.declarations`).

- [ ] **Step 3: Implement `host/declarations.py`**

Build a list of `(flag, path, value, may_be_null)` for every optional field (the map above; `may_be_null` is true for `full_name`, `exiled_by`, stack `text`, and for `class_level` on a permanent whose subtypes lack `class`) and apply: flag off and value not null, or flag on and value null without `may_be_null`, raise `ValidatorViolation("V8", f"{path} does not match the {flag} flag")`; with `permanent_details` on, a non-null `class_level` on a non-Class also fails. Then the kind, rule, rewind and extension checks. `check_context` follows the rule text above using `candidates.family`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_declarations.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/declarations.py python/tests/test_host_declarations.py
git commit -m "Host: V8 declarations and flags, V9 decision context"
```

### Task 17: Agent-role messages, the agent process and the seat driver protocol

**Effort:** 0.75 agent-day. **Wave:** 3. **Depends on:** Tasks 1, 9.

**Files:**
- Create: `python/spellbench/agent_messages.py`
- Create: `python/spellbench/host/seat.py`
- Create: `python/spellbench/host/setup.py`
- Create: `python/spellbench/host/agent_process.py`
- Create: `python/tests/test_host_agent_process.py`

**Interfaces:**
- Consumes: `messages` (`PROTOCOL`, `PROTOCOL_MINOR`, `Rules`, `EngineIdentity`, `EngineProfile`, `TimeControl`, `Limits`, `Resources`, `DeckRow`) (Task 9); `wire.SubprocessPeer`, `wire.strict_json_loads`, `wire.canonical_json_dumps`; `_client.Peer` protocol (existing).
- Produces (`spellbench.agent_messages`):
  - `AGENT_ERROR_CODES` (the 7 codes of spec 10.5)
  - `BotIdentity(name, version)`; `AgentHelloOk(request_id, bot, requires_observation: tuple[str, ...], requires_extensions: tuple[str, ...], extensions_accepted: tuple[str, ...])` with lenient `from_json(value, *, request_id: str)`
  - `Choice(request_id: str, candidate_id: int, echoes: dict[str, Any])` with lenient `from_json(value, *, request_id)` (`echoes` holds whichever of `seat_step`, `semantic_echo` were present, raw)
  - `read_ack(value, *, request_id) -> None`, `read_error(value, *, request_id) -> tuple[str, str] | None` (an error envelope's code and message; `request_id` may echo or be `""`)
  - `OwnDeck(deck_id, name, decklist: tuple[DeckRow, ...])`, `Clock(remaining_ms, max_decision_ms)`, `AgentTerminal(outcome, classification, winner, reason, seat_step_count)` (classification may be `forfeit`), each with `to_json()` and strict `from_json`
  - `game_start_payload(*, game_id: str, seat: str, format: str, own_deck: OwnDeck, opponent_deck: OwnDeck | None, rules: Rules, engine: EngineIdentity, engine_profile: EngineProfile, time_control: TimeControl, limits: Limits, resources: Resources, agent_seed: int) -> dict`, `choose_payload(*, game_id: str, seat_decision: Mapping, clock: Clock) -> dict`, `game_over_payload(*, game_id: str, terminal: AgentTerminal) -> dict`, `request(request_type: str, request_id: str, payload: Mapping) -> dict`
- Produces (`spellbench.host.seat`): `SEAT_FAILURE_CAUSES = ("timeout", "malformed_response", "invalid_selection", "agent_error", "transport_error")`; `class SeatFailure(Exception)` with `(cause: str, detail: str, diagnostic: str = "")`, picklable; `class SeatDriver(Protocol)` with `start(game_start: Mapping, *, timeout_s: float) -> None`, `choose(choose: Mapping, *, timeout_s: float) -> Choice`, `game_over(game_over: Mapping, *, timeout_s: float) -> None`, `close() -> None`
- Produces (`spellbench.host.setup`): `@dataclass(frozen=True) class GameSetup: game_index: int; game_id: str; game_secret_hex: str; format: str; wire_decks: tuple[WireDeck, WireDeck]; own_decks: tuple[OwnDeck, OwnDeck]; rules: Rules; time_control: TimeControl; limits: Limits; resources: Resources; agent_seeds: tuple[int, int]` (data only, defined here so Tasks 23 and 25 can share it in the same wave; `host.game` re-exports it)
- Produces (`spellbench.host.agent_process`): `class AgentProcess(argv: Sequence[str] | None = None, *, peer: Peer | None = None, startup_timeout_s: float | None = None)` with `hello() -> AgentHelloOk`, `game_start(payload, *, timeout_s) -> None`, `choose(payload, *, timeout_s) -> Choice`, `game_over(payload, *, timeout_s) -> None`, `close() -> None`, `stderr_text() -> str`. Request ids are `"r-<n>"`, `n` counting requests sent to this process from 0 (spec 4.1). Every failure raises `SeatFailure` with a deterministic `detail` that never quotes the peer: `PeerTimeoutError` is `timeout` ("no answer to {phase} within {ms} ms"), `TransportError` is `transport_error` ("the bot process failed during {phase}"), unparseable JSON, an oversized line, a missing required field, the wrong `response_type`, `protocol` or `request_id` are `malformed_response` ("the answer to {phase} was not a valid protocol message"), and an error envelope is `agent_error` ("{phase} was answered with an error (<code>)", the code only when it is in `AGENT_ERROR_CODES`). No retransmission (spec 4.1).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_agent_process.py`:

```python
"""Agent-role messages and the host's agent client (spec 10)."""

from __future__ import annotations

import sys
import time

import pytest

from spellbench import wire
from spellbench.agent_messages import AgentHelloOk, Choice, Clock, choose_payload
from spellbench.errors import PeerTimeoutError, TransportError, ValidationError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.seat import SeatFailure

from conftest import ScriptedPeer


def _answer(**message) -> bytes:
    return wire.canonical_json_dumps({"protocol": "spellbench/v2", **message})


HELLO = _answer(response_type="hello_ok", request_id="r-0", bot={"name": "b", "version": "1"}, x_note="ignored")


def test_hello_ok_is_read_leniently() -> None:
    hello = AgentHelloOk.from_json({"response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "r-0",
                                    "bot": {"name": "b", "version": "1"}, "requires": {"observation": ["keywords"]}, "x": 1},
                                   request_id="r-0")
    assert hello.requires_observation == ("keywords",) and hello.requires_extensions == ()
    for bad in ({"bot": {"name": "", "version": "1"}}, {"bot": None}, {"request_id": "r-9"}):
        with pytest.raises(ValidationError):
            AgentHelloOk.from_json({"response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "r-0",
                                    "bot": {"name": "b", "version": "1"}, **bad}, request_id="r-0")


def test_choice_needs_only_the_candidate_id_and_keeps_echoes_raw() -> None:
    base = {"response_type": "choice", "protocol": "spellbench/v2", "request_id": "r-2"}
    assert Choice.from_json({**base, "selection": {"candidate_id": 1, "x_why": "tempo"}}, request_id="r-2").echoes == {}
    echoed = Choice.from_json({**base, "selection": {"candidate_id": 1, "seat_step": "3"}}, request_id="r-2")
    assert echoed.echoes == {"seat_step": "3"}
    for selection in ({"candidate_id": "1"}, {"candidate_id": True}, {}):
        with pytest.raises(ValidationError):
            Choice.from_json({**base, "selection": selection}, request_id="r-2")


def test_request_ids_count_this_process_and_payloads_are_canonical() -> None:
    peer = ScriptedPeer([HELLO, _answer(response_type="ack", request_id="r-1"),
                         _answer(response_type="choice", request_id="r-2", selection={"candidate_id": 0})])
    agent = AgentProcess(peer=peer)
    agent.hello()
    agent.game_start({"game_id": "g-1", "seat": "p0"}, timeout_s=1)
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}], "acting_seat": "p0"}
    choice = agent.choose(choose_payload(game_id="g-1", seat_decision=decision, clock=Clock(remaining_ms=5, max_decision_ms=6)),
                          timeout_s=1)
    assert choice.candidate_id == 0
    assert [wire.strict_json_loads(line)["request_id"] for line in peer.sent] == ["r-0", "r-1", "r-2"]
    assert peer.sent[2] == wire.canonical_json_dumps(wire.strict_json_loads(peer.sent[2]))


@pytest.mark.parametrize(
    ("response", "cause"),
    [
        (PeerTimeoutError("slow"), "timeout"),
        (TransportError("gone"), "transport_error"),
        (b"Loading weights from /home/me/model.pt", "malformed_response"),
        (_answer(response_type="ack", request_id="r-1"), "malformed_response"),
        (_answer(response_type="choice", request_id="r-7", selection={"candidate_id": 0}), "malformed_response"),
        (_answer(response_type="error", request_id="r-1", error={"code": "internal_error", "message": "boom"}), "agent_error"),
    ],
)
def test_failures_map_to_forfeit_causes_without_quoting_the_peer(response, cause: str) -> None:
    agent = AgentProcess(peer=ScriptedPeer([HELLO, response]))
    agent.hello()
    with pytest.raises(SeatFailure) as caught:
        agent.choose({"game_id": "g-1", "decision": {}, "clock": {}}, timeout_s=1)
    assert caught.value.cause == cause
    assert "weights" not in caught.value.detail and "boom" not in caught.value.detail


def test_a_bot_that_logs_to_stdout_before_hello_is_malformed_and_never_hangs(tmp_path) -> None:
    script = tmp_path / "noisy.py"
    script.write_text("import sys, time\nprint('Loading model...', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    agent = AgentProcess([sys.executable, str(script)], startup_timeout_s=30)
    started = time.monotonic()
    with pytest.raises(SeatFailure) as caught:
        agent.hello()
    agent.close()
    assert caught.value.cause == "malformed_response" and "Loading" not in caught.value.detail
    assert time.monotonic() - started < 20
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_agent_process.py -q`
Expected: FAIL at collection (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`AgentProcess` wraps a `wire.SubprocessPeer` (or the injected peer): `_exchange(request_type, payload, timeout_s, phase)` stamps `request_id = f"r-{self._count}"` (incrementing), writes `wire.canonical_json_dumps(request(...))`, calls `peer.set_timeout(timeout_s)` when available, reads one line, parses it with `wire.strict_json_loads`, returns the dict with any error envelope already mapped to `SeatFailure("agent_error", ...)`; the exception mapping follows the Interfaces list, with `diagnostic` holding the exception text plus `stderr_text()`. The lenient readers accept any extra fields; a present-but-malformed `requires` or `extensions_accepted` is malformed (Review Focus 1 relies on failing fast rather than guessing). `host/setup.py` holds only the `GameSetup` dataclass from the Interfaces list (its imports: `WireDeck`, `Rules`, `TimeControl`, `Limits`, `Resources` from `messages`, `OwnDeck` from `agent_messages`).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_agent_process.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/agent_messages.py python/spellbench/host/seat.py python/spellbench/host/setup.py python/spellbench/host/agent_process.py python/tests/test_host_agent_process.py
git commit -m "Host: agent-role messages, the agent client and the seat driver protocol"
```

### Task 18: The engine process

**Effort:** 0.5 agent-day. **Wave:** 3. **Depends on:** Task 9.

**Files:**
- Create: `python/spellbench/host/engine_process.py`
- Create: `python/tests/test_host_engine_process.py`

**Interfaces:**
- Consumes: `messages` (Task 9); `wire`; `errors.EngineError`, `ProtocolError`, `PeerTimeoutError`, `TransportError`; `_client.Peer`.
- Produces (`spellbench.host.engine_process`): `class EngineProcess(argv: Sequence[str] | None = None, *, peer: Peer | None = None, timeout_s: float | None = None)` with
  - `hello(*, protocol_minor: int = PROTOCOL_MINOR) -> EnvHelloOk` (the answer's `protocol_minor` must not exceed the request's)
  - `next_request_id() -> str` (`"h-<n>"`, from 1)
  - `reset(request: ResetRequest) -> Decision | Terminal`
  - `step(*, candidate_id: int, semantic: Mapping[str, Any]) -> Decision | Terminal` (sends `semantic` as `semantic_echo`)
  - `validate_deck(*, format: str, catalog_id: str | None = None, decklist: Sequence[Mapping] | None = None) -> DeckOk`
  - `send_raw(message: Mapping[str, Any]) -> dict` and `send_line(payload: bytes) -> dict` (conformance probes: send anything, return the strict-parsed answer, no state change)
  - `retry_last() -> Any` (byte-identical retransmission, spec 4.1)
  - attributes `hello_result: EnvHelloOk | None`, `last_request: dict | None` (the last request sent), `last_response: dict | None` (its strict-parsed answer, including error envelopes and answers that failed a binding check; `None` when no parseable answer arrived); `set_timeout(seconds: float | None)`, `stderr_text() -> str`, `close()`
  - binding checks: every answer echoes `request_id`; decisions and terminals echo `game_id`; the first decision has `step` 0 and each later one the previous plus 1; a terminal's `step_count` equals the answered count. A failed check raises `ProtocolError`; an error envelope raises `EngineError(code, message)` (a code outside `ENGINE_ERROR_CODES` is a `ProtocolError`). Provenance drift and `decision_count` are the validator's and the game loop's (Tasks 22, 23).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_engine_process.py`:

```python
"""The host's engine client (spec 9)."""

from __future__ import annotations

import copy

import pytest

from spellbench import wire
from spellbench.errors import EngineError, ProtocolError
from spellbench.host.engine_process import EngineProcess
from spellbench.messages import ResetRequest

from conftest import ScriptedPeer
from test_messages import HELLO_OK, PROVENANCE, RESET, TERMINAL


def _decision(request_id: str, step: int) -> bytes:
    return wire.canonical_json_dumps({"response_type": "decision", "protocol": "spellbench/v2", "request_id": request_id,
                                      "game_id": RESET["game_id"], "step": step, "provenance": PROVENANCE,
                                      "seat_decision": {"acting_seat": "p0", "candidates": [
                                          {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}})


def _hello(peer: ScriptedPeer) -> EngineProcess:
    engine = EngineProcess(peer=peer)
    engine.hello()
    return engine


def _reset(engine: EngineProcess):
    return engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))


def test_a_game_binds_steps_and_echoes_the_semantic() -> None:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), _decision("h-2", 0),
                         wire.canonical_json_dumps({**TERMINAL, "request_id": "h-3", "step_count": 1, "decision_count": 1})])
    engine = _hello(peer)
    assert _reset(engine).step == 0
    terminal = engine.step(candidate_id=0, semantic={"kind": "pass"})
    assert terminal.result.step_count == 1
    step = wire.strict_json_loads(peer.sent[2])
    assert step["expected_step"] == 0 and step["selection"] == {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert engine.last_request == step and engine.last_response["response_type"] == "terminal"


@pytest.mark.parametrize(
    "answer",
    [
        _decision("h-9", 0),                                                        # request_id not echoed
        _decision("h-2", 3),                                                        # the first decision is step 0
        wire.canonical_json_dumps({**TERMINAL, "request_id": "h-2", "step_count": 5}),  # a reset terminal answers 0 steps
    ],
)
def test_binding_drift_is_a_protocol_error(answer: bytes) -> None:
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), answer]))
    with pytest.raises(ProtocolError):
        _reset(engine)


def test_an_error_envelope_is_an_engine_error() -> None:
    error = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-2",
             "error": {"code": "unsupported_deck", "message": "no such deck"}}
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), wire.canonical_json_dumps(error)]))
    with pytest.raises(EngineError) as caught:
        _reset(engine)
    assert caught.value.code == "unsupported_deck"


def test_a_higher_minor_than_requested_is_refused() -> None:
    with pytest.raises(ProtocolError, match="protocol_minor"):
        _hello(ScriptedPeer([wire.canonical_json_dumps({**HELLO_OK, "protocol_minor": 1})]))


def test_raw_probes_do_not_touch_the_game_state() -> None:
    mismatch = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "x",
                "error": {"code": "protocol_mismatch", "message": "v2 only"}}
    engine = _hello(ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), wire.canonical_json_dumps(mismatch)]))
    assert engine.send_raw({"request_type": "hello", "protocol": "spellbench/v1", "request_id": "x"})["error"]["code"] == "protocol_mismatch"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_engine_process.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.engine_process`).

- [ ] **Step 3: Implement `host/engine_process.py`**

Port the structure of v1 `engine_client.EngineProcess` and `_client.RoleClient` (single outstanding request, `_pending` and `_last` for `retry_last`, commit after validation), replacing the v1 models with `messages` and dropping group checks (per-seat groups are V3). Keep `self._answered` (0 after reset, plus 1 per step answered with a decision or terminal) for the binding checks, and set `last_request` / `last_response` on every exchange, including error answers, so the game loop can chain them.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_engine_process.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/engine_process.py python/tests/test_host_engine_process.py
git commit -m "Host: the v2 engine client with binding checks and raw probes"
```

### Task 19: Tournament config v2

**Effort:** 0.5 agent-day. **Wave:** 3. **Depends on:** Tasks 2, 9, 11.

**Files:**
- Create: `python/spellbench/arena/config.py`
- Create: `python/tests/test_arena_config.py`

**Interfaces:**
- Consumes: `messages.TimeControl`, `Limits`, `Resources`, `DeckRow` (Task 9); `digests.deck_rows` (Task 2); `builtins.BUILTIN_VERSIONS` (Task 11); `registry` (existing); `ratings.MAX_PAIR_COUNT`, `ratings.MAX_BOOTSTRAP_DRAWS` (existing).
- Produces (`spellbench.arena.config`):
  - `CONFIG_SCHEMA = "spellbench-tournament-config/v2"`, `MAX_WORKERS = 61`, `DEFAULT_TIME_CONTROL = TimeControl(300000, 60000, 600000, 2000, 60000, 120000)`, `DEFAULT_LIMITS = Limits(10000, 100000, 500, 4999, 49999)`, `DEFAULT_RESOURCES = Resources(cpus=1, memory_mb=4096, gpu=False, engine_cpus=1)`, `MULLIGAN_CHOICES = ("auto", "london", "none")`
  - `class TournamentError(Exception)`
  - `BotSpec` (v1 fields: name, version, type, seed, command, checkpoint, engine, owner, training_style_tags, registered_at) with `registry_entry(*, checkpoint_path: str | None = None) -> RegistryEntry` and `to_json()`
  - `DeckSpec(catalog_id: str | None = None, name: str | None = None, decklist: tuple[DeckRow, ...] | None = None)` (hashable; exactly `{"catalog_id"}` or `{"name", "decklist"}`) with `to_json()`, `from_json(value, context)`
  - `RulesSpec(opponent_decklist: str = "visible", mulligan: str = "auto", starting_player: str = "host_assigned", starting_seat: str | None = "p0")` with `to_json()`
  - `TournamentConfig(tournament_dir, format, decks: tuple[DeckSpec, DeckSpec] | None, deck_pool: tuple[DeckSpec, ...] | None, engine_command: tuple[str, ...], bots: tuple[BotSpec, ...], pairs_per_matchup, stats_seed, rules: RulesSpec, extensions: tuple[str, ...], native_id_audits: dict[str, str], time_control, limits, resources, bootstrap_replicates, rating_anchor, workers, include_self_play)` with `decks_for_pair(pair_index) -> tuple[DeckSpec, DeckSpec]`, `preflight_deck_pairs() -> tuple[tuple[DeckSpec, DeckSpec], ...]`, `deck_specs() -> tuple[DeckSpec, ...]` (distinct, first-use order), `per_game_cores() -> int` (`engine_cpus`, plus `2 * cpus` when any bot is a subprocess bot), `to_json()`, `from_json(value)`

Config JSON: required `schema`, `tournament_dir`, `format`, `engine` (`{"command": [...]}`, nothing else), `bots`, `pairs_per_matchup`, `stats_seed`, and exactly one of `decks` / `deck_pool`; optional `rules`, `extensions`, `native_id_audits` (keys must be enabled extensions; values nonempty audit references), `time_control`, `limits`, `resources` (each complete when given), `bootstrap_replicates`, `rating_anchor`, `workers`, `include_self_play`. A v1 field (`base_seed`, `max_decisions`, `max_steps`, `choose_timeout_ms`, `startup_timeout_ms`, `engine.timeout_ms`) is an error naming its v2 replacement. Builtin bots must carry `builtins.BUILTIN_VERSIONS`. There is no `probe` field (never set by hosts).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_config.py`:

```python
"""Tournament config v2."""

from __future__ import annotations

import pytest

from spellbench.arena.config import DEFAULT_LIMITS, DEFAULT_TIME_CONTROL, DeckSpec, TournamentConfig, TournamentError

BURN = [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]


def config(**changes) -> dict:
    value = {"schema": "spellbench-tournament-config/v2", "tournament_dir": "out/t", "format": "pauper-bo1",
             "decks": [{"catalog_id": "Burn"}, {"name": "My Burn", "decklist": BURN}],
             "engine": {"command": ["engine"]},
             "bots": [{"name": "uniform", "version": "2.0.0", "type": "builtin", "seed": 11},
                      {"name": "heuristic", "version": "2.0.0", "type": "builtin"}],
             "pairs_per_matchup": 2, "stats_seed": 7}
    value.update(changes)
    return value


def test_defaults_and_round_trip() -> None:
    parsed = TournamentConfig.from_json(config())
    assert parsed.time_control == DEFAULT_TIME_CONTROL and parsed.limits == DEFAULT_LIMITS
    assert parsed.rules.to_json() == {"opponent_decklist": "visible", "mulligan": "auto", "starting_player": "host_assigned", "starting_seat": "p0"}
    assert TournamentConfig.from_json(parsed.to_json()).to_json() == parsed.to_json()
    assert parsed.per_game_cores() == 1 and parsed.deck_specs()[1] == DeckSpec(name="My Burn", decklist=parsed.deck_specs()[1].decklist)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"base_seed": 1}, "stats_seed"),
        ({"engine": {"command": ["engine"], "timeout_ms": 5}}, "engine_step_ms"),
        ({"bots": [{"name": "uniform", "version": "1.0.0", "type": "builtin"}]}, "2.0.0"),
        ({"decks": [{"catalog_id": "Burn"}, {"decklist": BURN}]}, "name"),
        ({"decks": [{"catalog_id": "Burn"}, {"name": "x", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 1}]}]}, "NFC"),
        ({"rules": {"starting_player": "toss_winner_chooses"}}, "starting_seat"),
        ({"rules": {"mulligan": "vancouver"}}, "mulligan"),
        ({"native_id_audits": {"x_kernel_v5": "https://example.org/audit"}}, "extensions"),
        ({"limits": {**DEFAULT_LIMITS.to_json(), "max_seat_steps_per_game": 50000}}, "half"),
        ({"workers": 62}, "workers"),
        ({"probe": True}, "probe"),
    ],
)
def test_invalid_configs_name_the_field(changes: dict, message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        TournamentConfig.from_json(config(**changes))


def test_a_toss_rule_needs_no_seat_and_subprocess_bots_count_their_cores() -> None:
    toss = TournamentConfig.from_json(config(rules={"starting_player": "toss_winner_chooses", "starting_seat": None}))
    assert toss.rules.starting_seat is None
    sub = TournamentConfig.from_json(config(
        bots=[{"name": "uniform", "version": "2.0.0", "type": "builtin"},
              {"name": "mine", "version": "1", "type": "subprocess", "command": ["python", "bot.py"]}],
        resources={"cpus": 2, "memory_mb": 4096, "gpu": False, "engine_cpus": 1}))
    assert sub.per_game_cores() == 5


def test_a_pool_rotates_and_must_divide_the_pairs() -> None:
    pool = config(deck_pool=[{"catalog_id": "Burn"}, {"catalog_id": "Elves"}], pairs_per_matchup=4)
    del pool["decks"]
    parsed = TournamentConfig.from_json(pool)
    assert [parsed.decks_for_pair(index)[0].catalog_id for index in range(4)] == ["Burn", "Elves", "Burn", "Elves"]
    with pytest.raises(TournamentError, match="multiple"):
        TournamentConfig.from_json({**pool, "pairs_per_matchup": 3})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_config.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.arena.config`).

- [ ] **Step 3: Implement `arena/config.py`**

Port `BotSpec`, `_bot_spec_from_json` and `TournamentConfig.from_json` from v1 `runner.py` (keeping every v1 check and message: unique names, anchor, workers `[1, 61]`, self-play, pool multiple, bootstrap limits), with the v2 fields and rules above; `DeckSpec.from_json` runs decklists through `digests.deck_rows` and wraps a `ValidationError` as `TournamentError(f"{context}: {exc}")`; `TimeControl`, `Limits` and `Resources` come from `messages` (their construction errors become `TournamentError` naming the block).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_config.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/config.py python/tests/test_arena_config.py
git commit -m "Arena: tournament config v2 with rules, clocks, limits and resources"
```

### Task 20: Leaderboard v2 with attribution

**Effort:** 0.5 agent-day. **Wave:** 3. **Depends on:** Tasks 4, 12.

**Files:**
- Modify: `python/spellbench/arena/leaderboard.py`
- Modify: `python/spellbench/arena/legacy_v1.py` (its `build_leaderboard` call passes the v1 schema)
- Modify: `python/spellbench/arena/runner.py` (the v1 runner's call passes the v1 schema; the file is replaced in Task 33)
- Modify: `python/spellbench/arena/store.py` (v1 `LedgerRow` gains `pair_slot`; replaced in Task 33)
- Modify: `python/tests/test_arena_ratings.py`, `python/tests/test_arena_slices.py` (their calls pass the v1 schema)
- Create: `python/tests/test_leaderboard_v2.py`

**Interfaces:**
- Consumes: `arena.ledger.LedgerRow` (Task 12); `legacy_v1.LegacyLedgerRow` (Task 4).
- Produces:
  - `leaderboard.LEADERBOARD_SCHEMA_V1 = "spellbench-leaderboard/v1"`, `LEADERBOARD_SCHEMA_V2 = "spellbench-leaderboard/v2"`, `NOTES_V1` (today's `NOTES`, verbatim), `NOTES_V2`
  - `leaderboard.build_leaderboard(rows, entries, *, anchor_bot_id: str, base_seed: int, bootstrap_replicates: int, format: str, schema: str) -> tuple[dict, str]` (`schema` is required; `base_seed` keeps its name and receives a v2 config's `stats_seed`)
  - v2 documents add to each row (overall and deck slices): `games_played` (seat-games, rated or not), `halts_attributed`, `truncations_attributed` (games halted or truncated right after this bot's selection, from `last_selection`), `halt_rate` and `truncation_rate` (`{"num", "den"}`, or null with no games), `forfeits_by_cause` (`{cause: count}`); the markdown adds `## Halts and truncations after each bot's selection` before `## Notes`
  - `store.LedgerRow.pair_slot` property (returns `game_index`)

`NOTES_V2` is `NOTES_V1` with the CRN line replaced by `"the paired bootstrap resamples seat-swapped pairs within each matchup; the two games of a pair have independent game secrets"` and one line appended: `"halt and truncation rates count the games halted or truncated right after the bot's own selection, over every game it played"` (spec 11.5).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_leaderboard_v2.py`:

```python
"""Leaderboard v2: attribution rates, v2 notes; v1 documents stay byte for byte."""

from __future__ import annotations

from pathlib import Path

from spellbench.arena import leaderboard, legacy_v1, registry, store
from spellbench.arena.ledger import parse_ledger

from test_ledger import A, B, VALID, row

REPO = Path(__file__).resolve().parents[2]
ENTRIES = [registry.RegistryEntry(bot_id=A, name="a", version="1", engine="any"),
           registry.RegistryEntry(bot_id=B, name="b", version="1", engine="any")]


def _build(rows):
    return leaderboard.build_leaderboard(parse_ledger(rows), ENTRIES, anchor_bot_id=A, base_seed=7,
                                         bootstrap_replicates=1000, format="pauper-bo1", schema=leaderboard.LEADERBOARD_SCHEMA_V2)


def test_v2_rows_carry_attribution() -> None:
    rows = [row(), row(game_index=1, pair_slot=1, seats=[{"seat": "p0", "bot_id": B, "name": "b", "version": "1"},
                                                            {"seat": "p1", "bot_id": A, "name": "a", "version": "1"}],
                       winner_bot_id=B),
            {**VALID["validator halt"], "game_index": 2, "pair_index": 1},
            {**VALID["forfeit"], "game_index": 3, "pair_index": 1, "pair_slot": 1}]
    document, markdown = _build(rows)
    assert document["schema"] == "spellbench-leaderboard/v2" and document["notes"] == leaderboard.NOTES_V2
    by_name = {entry["name"]: entry for entry in document["rows"]}
    assert (by_name["b"]["halts_attributed"], by_name["a"]["halts_attributed"]) == (1, 0)
    assert by_name["b"]["halt_rate"] == {"num": 1, "den": 4} and by_name["a"]["games_played"] == 4
    assert by_name["a"]["forfeits_by_cause"] == {"stalling": 1}
    assert "## Halts and truncations after each bot's selection" in markdown


def test_v1_documents_are_unchanged() -> None:
    run = REPO / "benchmarks" / "pauper-kernel" / "runs" / "2026-09-26"
    rows = legacy_v1.parse_ledger(store.read_jsonl(run / "matches.jsonl", schema=legacy_v1.LEDGER_SCHEMA_V1))
    entries = registry.read_registry(run / "registry.json")
    anchor = next(entry.bot_id for entry in entries if entry.name == "uniform")
    document, markdown = leaderboard.build_leaderboard(rows, entries, anchor_bot_id=anchor, base_seed=20260926,
                                                       bootstrap_replicates=2000, format="pauper-bo1",
                                                       schema=leaderboard.LEADERBOARD_SCHEMA_V1)
    assert store.canonical_bytes(document) + b"\n" == (run / "leaderboard.json").read_bytes()
    assert markdown.encode("utf-8") == (run / "LEADERBOARD.md").read_bytes()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_leaderboard_v2.py -q`
Expected: FAIL (`LEADERBOARD_SCHEMA_V2` missing; `schema` is not a keyword).

- [ ] **Step 3: Implement**

In `leaderboard.py`: rename `NOTES` to `NOTES_V1`, add `NOTES_V2` and the schema constants, thread `schema` through `build_leaderboard`, `_build_document` and `_deck_slices` (every slice uses the same schema), read `row.pair_slot` in `_accumulate`, and make `_deck_label` return `deck["name"]` for a v2 deck entry (one with `deck_id`). Only when `schema == LEADERBOARD_SCHEMA_V2`: add the attribution fields (count every row, rated or not; a halted or truncated row with `last_selection` adds one to that bot) and the markdown section (columns `Bot`, `Games`, `Halts`, `Halt rate`, `Truncations`, `Truncation rate`, rates as `f"{num / den:.3f}"` or `-`). Add `pair_slot` to the v1 `store.LedgerRow`; pass `schema=leaderboard.LEADERBOARD_SCHEMA_V1` in the v1 `runner.run_tournament`, in `legacy_v1.validate_v1_run`, and in the helper builders of `test_arena_ratings.py` and `test_arena_slices.py`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_leaderboard_v2.py python/tests/test_legacy_v1.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/leaderboard.py python/spellbench/arena/legacy_v1.py python/spellbench/arena/runner.py python/spellbench/arena/store.py python/tests/test_arena_ratings.py python/tests/test_arena_slices.py python/tests/test_leaderboard_v2.py
git commit -m "Leaderboard: v2 documents with halt and truncation attribution"
```

### Task 21: The v2 fake engine

**Effort:** 0.75 agent-day. **Wave:** 3. **Depends on:** Tasks 2, 9, 13.

**Files:**
- Create: `python/tests/fake_v2_engine.py`
- Create: `python/tests/test_fake_v2_engine.py`

**Interfaces:**
- Consumes: `fake_v2_world` (Task 13); `messages` models for strict request parsing (Task 9); `digests.deck_id`, `digests.deck_rows` (Task 2); `wire`.
- Produces (`python/tests/fake_v2_engine.py`):
  - command line: `python fake_v2_engine.py [--flags NAMES | --all-flags] [--rewind] [--probe] [--london] [--toss] [--decklists] [--kinds NAMES] [--name NAME]` (flags and kinds are comma-separated; the defaults declare no optional flags, all 30 kinds, `rules_supported` `{"mulligan": ["none"], "starting_player": ["host_assigned"]}`, `deck_sources` `["catalog"]`, engine identity `fake-v2-engine` 0.2.0)
  - `serve(argv: Sequence[str], *, stdin=None, stdout=None, mutate: Callable[[int, dict], dict | bytes] | None = None) -> int` (`mutate(step, message)` may rewrite each outgoing decision or terminal, or return raw bytes to write instead of a message; it may also sleep or exit; Task 28's hostile engine uses it)
  - catalog decks: `Burn`, `Elves`, `Faeries` (the scoring game), the hooks `Crash`, `Halt`, `Truncate`, `Refuse`, `Rendezvous`, `Loop`, `Stall`, and `Scenario:<name>` for every `fake_v2_scenario_<name>.py` beside the engine (module attribute `SCENARIO: fake_v2_world.Scenario`), in sorted catalog-id order
  - `SCORING_DECKLIST = [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]` for the scoring decks and hooks

The scoring game (replaces `fake_arena_engine.py`, same outcomes): four decisions, the starting seat first, then alternating; each offers `[pass, play_land(face 0)]` for a Mountain in the seat's two-card hand; each `play_land` scores 1 and moves the Mountain to the battlefield (a fresh id). After the fourth answer: natural, the higher score wins, equal scores draw, reason `score`. Every game (the hooks and scenarios included) ends `truncated` (winner null, reason `max_steps` or `max_decisions`) once `max_steps` answers or `max_decisions` completed groups are reached, so `max_steps` below 4 truncates the scoring game. Turn number is the step plus 1, the acting seat is active and holds priority, phase `precombat_main`; `seat_step` and `group_id` count per seat. Hooks (by the p0 deck): `Crash` exits with code 3 at the first `step`; `Halt` answers the first `step` with a `halted` terminal, reason `engine_contract_failure:test_hook`; `Truncate` answers the first `step` with a `truncated` terminal, reason `engine_cap` (an engine-side cap, so truncation attribution can be tested although the host's seat caps always come first); `Refuse` answers `reset` with `unsupported_deck`; `Rendezvous` drops a marker named after the game in `$SPELLBENCH_RENDEZVOUS_DIR` at the first `step` and waits for `$SPELLBENCH_RENDEZVOUS_COUNT` markers (exit code 4 after 10 s; preflight resets never step, so they never wait); `Loop` poses single-candidate `[pass]` decisions to alternating seats forever, turn 1; `Stall` offers p0 `[pass, activate_ability(Relic of Progenitus)]` and p1 `[pass]` in alternation, turn 1, and ends in a natural draw (reason `stall_ended`) when p0 passes. A scenario deck runs its script (`Posed` decisions; the chosen `candidate_id` is sent into the generator); it needs its `engine_args` present on the engine's command line, else `reset` answers `unsupported_deck`.

Protocol behavior (spec 4.1, 9): strict parsing with the `messages` models (unknown fields `malformed_request`; unparseable lines `malformed_json` with `request_id` `""`); `protocol_mismatch`; a one-entry retransmission cache (the identical line returns the cached answer; a reused id with another payload is `request_id_reuse_mismatch`); a reused `game_id` is `malformed_request`; `reset` checks `format` (`unsupported_format`), deck sources and catalog ids (`unsupported_deck`), each `deck_id` against the list (`deck_id_mismatch`), rules against `rules_supported`, extensions and `probe` (`unsupported_rule`), and an active game (`game_already_active`); `step` checks in the spec 9.4 order; requests after a terminal are `game_already_terminal`; `validate_deck` answers `deck_ok` or `unsupported_deck` / `unsupported_format`; `probe_resample` is `unsupported_request`, or `probe_refused` with `--probe`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_fake_v2_engine.py`:

```python
"""The v2 fake engine: strict protocol handling, the scoring game, the hooks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.candidates import validate_candidate
from spellbench.digests import deck_id
from spellbench.messages import EnvHelloOk
from spellbench.observation import validate_observation

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"
BURN_ID = deck_id([{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}])
DOMAIN = {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]}
RULES = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
         "card_name_domain": DOMAIN, "extensions": [], "probe": False}


class Engine:
    def __init__(self, *args: str) -> None:
        self.peer = wire.SubprocessPeer([sys.executable, str(ENGINE), *args], timeout_s=30)
        self.count = 0

    def send(self, request_type: str, **fields) -> dict:
        self.count += 1
        message = {"request_type": request_type, "protocol": "spellbench/v2", "request_id": f"h-{self.count}", **fields}
        self.peer.write_line(wire.canonical_json_dumps(message))
        return wire.strict_json_loads(self.peer.read_line())

    def reset(self, deck: str = "Burn", game_id: str = "g-0000000000000001", **changes) -> dict:
        fields = {"game_id": game_id, "format": "pauper-bo1",
                  "seats": [{"seat": seat, "deck": {"deck_id": BURN_ID, "catalog_id": deck}} for seat in ("p0", "p1")],
                  "rules": RULES, "game_secret": "11" * 32, "max_decisions": 10000, "max_steps": 100000}
        fields.update(changes)
        return self.send("reset", **fields)


@pytest.fixture
def engine():
    process = Engine()
    process.send("hello", protocol_minor=0)
    yield process
    process.peer.close()


def test_hello_is_a_valid_v2_hello_ok() -> None:
    process = Engine("--all-flags", "--rewind")
    hello = EnvHelloOk.from_json(process.send("hello", protocol_minor=0))
    process.peer.close()
    assert hello.profile.rewind and all(hello.profile.observation.values())
    assert {deck.catalog_id for deck in hello.catalog} >= {"Burn", "Elves", "Faeries", "Loop", "Stall"}


def test_the_scoring_game_matches_the_v1_outcomes(engine: Engine) -> None:
    response, step = engine.reset(), 0
    while response["response_type"] == "decision":
        seat_decision = response["seat_decision"]
        validate_observation(seat_decision["observation"])
        for candidate in seat_decision["candidates"]:
            validate_candidate(candidate)
        pick = 1 if seat_decision["acting_seat"] == "p0" else 0          # p0 plays lands, p1 passes
        semantic = seat_decision["candidates"][pick]["semantic"]
        response = engine.send("step", game_id="g-0000000000000001", expected_step=step,
                               selection={"candidate_id": pick, "semantic_echo": semantic})
        step += 1
    assert (response["outcome"], response["reason"], response["step_count"]) == ("p0_win", "score", 4)


@pytest.mark.parametrize(
    ("request_fn", "code"),
    [
        (lambda e: e.send("step", game_id="g-1", expected_step=0, selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}}), "step_before_reset"),
        (lambda e: e.reset(format="modern"), "unsupported_format"),
        (lambda e: e.reset(deck="Nope"), "unsupported_deck"),
        (lambda e: e.reset(deck="Refuse"), "unsupported_deck"),
        (lambda e: e.reset(seats=[{"seat": s, "deck": {"deck_id": "sha256:" + "0" * 64, "catalog_id": "Burn"}} for s in ("p0", "p1")]), "deck_id_mismatch"),
        (lambda e: e.reset(rules={**RULES, "mulligan": "london"}), "unsupported_rule"),
        (lambda e: e.reset(rules={**RULES, "probe": True}), "unsupported_rule"),
        (lambda e: e.reset(x_extra=1), "malformed_request"),
        (lambda e: e.send("probe_resample", game_id="g-1", samples=1), "unsupported_request"),
        (lambda e: e.send("hello", protocol_minor=0, protocol="spellbench/v1"), "protocol_mismatch"),
    ],
)
def test_error_codes(engine: Engine, request_fn, code: str) -> None:
    answer = request_fn(engine)
    assert (answer["response_type"], answer["error"]["code"]) == ("error", code)


def test_game_errors_and_retransmission(engine: Engine) -> None:
    first = engine.reset()
    assert engine.reset(game_id="g-0000000000000002")["error"]["code"] == "game_already_active"
    selection = {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert engine.send("step", game_id="g-9", expected_step=0, selection=selection)["error"]["code"] == "game_id_mismatch"
    assert engine.send("step", game_id=first["game_id"], expected_step=5, selection=selection)["error"]["code"] == "expected_step_mismatch"
    assert engine.send("step", game_id=first["game_id"], expected_step=0, selection={**selection, "candidate_id": 9})["error"]["code"] == "candidate_id_out_of_range"
    assert engine.send("step", game_id=first["game_id"], expected_step=0,
                       selection={"candidate_id": 1, "semantic_echo": {"kind": "pass"}})["error"]["code"] == "semantic_echo_mismatch"
    line = wire.canonical_json_dumps({"request_type": "step", "protocol": "spellbench/v2", "request_id": "h-50",
                                      "game_id": first["game_id"], "expected_step": 0, "selection": selection})
    engine.peer.write_line(line)
    answer = engine.peer.read_line()
    engine.peer.write_line(line)                       # the identical retransmission
    assert engine.peer.read_line() == answer
    engine.peer.write_line(line.replace(b'"expected_step":0', b'"expected_step":1'))
    assert wire.strict_json_loads(engine.peer.read_line())["error"]["code"] == "request_id_reuse_mismatch"
    engine.peer.write_line(b"{not json")
    error = wire.strict_json_loads(engine.peer.read_line())
    assert (error["request_id"], error["error"]["code"]) == ("", "malformed_json")


def test_probe_refused_with_the_probe_declared() -> None:
    process = Engine("--probe")
    process.send("hello", protocol_minor=0)
    process.reset()
    assert process.send("probe_resample", game_id="g-0000000000000001", samples=1)["error"]["code"] == "probe_refused"
    process.peer.close()


def test_hooks(engine: Engine) -> None:
    loop = Engine()
    loop.send("hello", protocol_minor=0)
    decision = loop.reset(deck="Loop")
    for step in range(20):
        assert [c["semantic"]["kind"] for c in decision["seat_decision"]["candidates"]] == ["pass"]
        decision = loop.send("step", game_id="g-0000000000000001", expected_step=step, selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}})
    loop.peer.close()
    halted = engine.reset(deck="Halt")
    assert engine.send("step", game_id=halted["game_id"], expected_step=0,
                       selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}})["outcome"] == "halted"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_fake_v2_engine.py -q`
Expected: FAIL (the engine file does not exist; the subprocess exits at once).

- [ ] **Step 3: Implement `fake_v2_engine.py`**

Structure: `serve()` reads lines with `wire.read_line`, answers each with one canonical line, and keeps `(last_request_id, last_line, last_answer)` for retransmission and the set of used game ids. Build seat decisions from `World.observation(seat)` plus the posed candidates (the engine resolves scenario candidate references through `World.reference`), with `context.kind` from the candidates' family unless the `Posed` gives one. `decision` and `terminal` answers carry `provenance` from the engine identity. `mutate` is applied to each decision or terminal just before it is written (`step` is the binding step of a decision, or the answered count for a terminal); bytes it returns are written as the line, unchanged.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_fake_v2_engine.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/tests/fake_v2_engine.py python/tests/test_fake_v2_engine.py
git commit -m "Tests: the v2 fake engine with every engine error code and the scoring game"
```

## Wave 4

### Task 22: The live validator

**Effort:** 0.5 agent-day. **Wave:** 4. **Depends on:** Tasks 14, 15, 16, 18, 21.

**Files:**
- Create: `python/spellbench/host/validator.py`
- Create: `python/tests/test_host_validator.py`
- Create: `python/tests/tour_helpers.py` (plays a fake-engine scenario deck through the validator; Tasks 26 and 27 import it)

**Interfaces:**
- Consumes: `observation.validate_observation`, `observation.observation_objects`, `observation.CARD_TYPES` (Task 8); `candidates.validate_candidate`, `candidates.MAX_CANDIDATES` (Task 7); `messages.EnvHelloOk`, `Rules`, `Decision`, `Terminal` (Task 9); `host.refs` (Task 14), `host.hidden` (Task 15), `host.declarations` (Task 16), `host.tracking`, `host.violation` (Task 10); `host.engine_process` (Task 18); `_schema`; `wire.canonical_json_dumps`.
- Produces (`python/tests/tour_helpers.py`): `play_tour(module: ModuleType, *extra_args: str) -> list[dict]` (starts the fake engine with the scenario's `engine_args` plus `extra_args`, resets `Scenario:<name>` with rules fitted to the engine's `rules_supported`, answers candidate 0 each time, validates every decision and the terminal counts, returns the validated seat decisions).
- Produces (`spellbench.host.validator`):
  - `VALIDATOR_VERSION = "spellbench-live-validator/2.0"`, `BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")`
  - `validate_seat_decision_schema(seat_decision: Any, rules: Rules) -> dict` (V1 alone; any `ValidationError` becomes `ValidatorViolation("V1", ...)`)
  - `class LiveValidator(hello: EnvHelloOk, rules: Rules)` with `check(decision: Decision) -> dict` (the validated seat decision), `answered(seat_decision: Mapping, candidate_id: int) -> None`, `check_terminal(terminal: Terminal) -> None` (V10), properties `decisions_checked: int`, `answered_steps: int`, `completed_groups: int`, and `answered_by(seat: str) -> int`

V1 (spec 11.3): exactly the seven `seat_decision` fields (`acting_seat`, `seat_step`, `group`, `context`, `observation`, `candidates`, `extensions`); `group` `{group_id, substep_index, substep_count}` with `1 <= substep_count` and `substep_index < substep_count`; `context` exactly `{kind, source, purpose, text, rewind}` (`kind` priority or choice, `source` an object reference or null, `purpose` snake case or null, `text` string or null, `rewind` bool); the observation schema; 1 to 4096 candidates, each valid, `candidate_id` equal to its index, semantics pairwise distinct (compare canonical bytes), `pass` only at index 0; `extensions` an object with `x_[a-z0-9_]+` keys; `choose_name` values inside their domain (`card_name`: `rules.card_name_domain.names`; `creature_type`, `land_type`: snake case; `basic_land_type`: `BASIC_LAND_TYPES`; `card_type`: `CARD_TYPES`). `check` runs V1 to V10 in rule order, so the lowest-numbered broken rule is the one reported; V7 reads `{id: zone}` from `observation_objects`; V10 compares the decision's provenance with `hello.engine.provenance()`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_validator.py`:

```python
"""The live validator: V1 to V10 in rule order, with its counters (spec 11.3)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from spellbench.host.engine_process import EngineProcess
from spellbench.host.validator import LiveValidator
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import Decision, EnvHelloOk, Provenance, ResetRequest, Rules

from test_messages import HELLO_OK, PROVENANCE, RESET, RULES
from v2_sample_semantics import SAMPLES, seat_decision

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"


def _validator() -> LiveValidator:
    return LiveValidator(EnvHelloOk.from_json(copy.deepcopy(HELLO_OK)), Rules.from_json(RULES))


def _decision(sd: dict, *, step: int = 0, provenance: dict = PROVENANCE) -> Decision:
    return Decision(request_id=f"h-{step + 2}", game_id="g-1", step=step, seat_decision=sd, provenance=Provenance(**provenance))


def _rule(validator: LiveValidator, sd: dict, **kwargs) -> str:
    with pytest.raises(ValidatorViolation) as caught:
        validator.check(_decision(sd, **kwargs))
    return caught.value.rule


def test_a_fake_engine_game_passes_and_the_counts_match_its_terminal() -> None:
    engine = EngineProcess([sys.executable, str(ENGINE)], timeout_s=30)
    try:
        validator = LiveValidator(engine.hello(), Rules.from_json(RULES))
        response = engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))
        while isinstance(response, Decision):
            sd = validator.check(response)
            validator.answered(sd, 0)
            response = engine.step(candidate_id=0, semantic=sd["candidates"][0]["semantic"])
        validator.check_terminal(response)
    finally:
        engine.close()
    assert validator.decisions_checked == validator.answered_steps == response.result.step_count == 4
    assert validator.completed_groups == response.result.decision_count
    assert (validator.answered_by("p0"), validator.answered_by("p1")) == (2, 2)


@pytest.mark.parametrize(
    "sd",
    [
        seat_decision([SAMPLES["pass"], SAMPLES["pass"]]),                                       # duplicate semantics
        seat_decision([SAMPLES["play_land"], SAMPLES["pass"]]),                                  # pass not first
        {**seat_decision(), "x_extra": 1},                                                       # unknown field
        seat_decision(extensions={"kernel": {}}),                                                # not an x_ key
        seat_decision([{"kind": "pay_mana"}]),                                                    # a reserved kind
        seat_decision([{**SAMPLES["choose_name"], "source": None, "value": "Black Lotus"}], kind="choice"),  # outside the domain
    ],
)
def test_v1_schema(sd: dict) -> None:
    assert _rule(_validator(), sd) == "V1"


def test_v1_dense_ids_and_the_4096_cap() -> None:
    sparse = seat_decision()
    sparse["candidates"][1]["candidate_id"] = 5
    assert _rule(_validator(), sparse) == "V1"
    many = [{**SAMPLES["choose_number"], "source": None, "value": value, "minimum": 0, "maximum": 4096} for value in range(4097)]
    assert _rule(_validator(), seat_decision(many, kind="choice")) == "V1"


@pytest.mark.parametrize(
    ("mutate", "rule"),
    [
        (lambda sd: sd.update(acting_seat="p1"), "V2"),
        (lambda sd: sd.update(seat_step=3), "V3"),
        (lambda sd: sd["candidates"][2]["semantic"]["source"].update(card_name="Chain Lightning"), "V4"),
        (lambda sd: sd["observation"]["players"][1].update(hand=[]), "V5"),
        (lambda sd: sd["observation"]["players"][1]["battlefield"][0].update(face_down=True), "V6"),
        (lambda sd: sd["observation"]["players"][0].update(poison=0), "V8"),
        (lambda sd: sd["context"].update(kind="choice"), "V9"),
        (lambda sd: (sd.update(acting_seat="p1"), sd["candidates"][2]["semantic"]["source"].update(card_name="x")), "V2"),
    ],
)
def test_each_rule_is_reported_and_the_lowest_wins(mutate, rule: str) -> None:
    sd = seat_decision()
    mutate(sd)
    assert _rule(_validator(), sd) == rule


def test_v7_across_decisions_and_v10_provenance() -> None:
    validator = _validator()
    first = seat_decision()
    validator.check(_decision(first))
    validator.answered(first, 0)
    second = seat_decision([SAMPLES["pass"]])
    second.update(seat_step=1, group={"group_id": 1, "substep_index": 0, "substep_count": 1})
    player = second["observation"]["players"][0]
    bolt = player["hand"].pop(0)
    player["graveyard"].append({**bolt, "zone": "graveyard"})     # the same id in a new zone
    player["hand_count"] = 1
    assert _rule(validator, second, step=1) == "V7"
    assert _rule(_validator(), seat_decision(), provenance={**PROVENANCE, "engine_version": "9.9.9"}) == "V10"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_validator.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.validator`).

- [ ] **Step 3: Implement `host/validator.py`**

```python
class LiveValidator:
    def __init__(self, hello: EnvHelloOk, rules: Rules) -> None:
        self._profile = hello.profile
        self._rules = rules
        self._provenance = hello.engine.provenance()
        self._groups = GroupTracker()
        self._ids = IdTracker()
        self.decisions_checked = 0

    def check(self, decision: Decision) -> dict:
        self.decisions_checked += 1
        sd = validate_seat_decision_schema(decision.seat_decision, self._rules)        # V1
        check_seat(sd)                                                                 # V2
        self._groups.check(sd)                                                         # V3
        check_references(sd)                                                           # V4
        check_hidden_zones(sd)                                                         # V5
        check_face_down(sd)                                                            # V6
        self._ids.check(sd["acting_seat"], {ref["object_id"]: ref["zone"] for _, ref in observation_objects(sd["observation"])})  # V7
        check_declarations(sd, self._profile, self._rules)                             # V8
        check_context(sd)                                                              # V9
        self._check_provenance(decision.provenance)                                    # V10
        return sd

    def answered(self, sd: Mapping[str, Any], candidate_id: int) -> None:
        self._groups.answered(sd, chosen_kind=sd["candidates"][candidate_id]["semantic"]["kind"])

    def check_terminal(self, terminal: Terminal) -> None:
        self._check_provenance(terminal.provenance)

    def _check_provenance(self, provenance: Provenance) -> None:
        if provenance != self._provenance:
            raise ValidatorViolation("V10", "the engine identity drifted from its hello")
```

plus the `answered_steps`, `completed_groups` and `answered_by` pass-throughs to the `GroupTracker`, and `validate_seat_decision_schema` per the V1 list above.

Create `python/tests/tour_helpers.py` (no test of its own here; Tasks 26 and 27 exercise it once scenario decks exist):

```python
"""Play a fake-engine scenario deck through the live validator (tests only)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from spellbench.digests import card_name_domain, deck_id
from spellbench.host.engine_process import EngineProcess
from spellbench.host.validator import LiveValidator
from spellbench.messages import Decision, ResetRequest, Rules

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"


def play_tour(module: ModuleType, *extra_args: str) -> list[dict]:
    scenario = module.SCENARIO
    engine = EngineProcess([sys.executable, str(ENGINE), *scenario.engine_args, *extra_args], timeout_s=30)
    decisions: list[dict] = []
    try:
        hello = engine.hello()
        london = "london" in hello.profile.rules_supported["mulligan"]
        toss = "toss_winner_chooses" in hello.profile.rules_supported["starting_player"]
        rules = Rules.from_json({"opponent_decklist": "visible", "mulligan": "london" if london else "none",
                                 "starting_player": "toss_winner_chooses" if toss else "host_assigned",
                                 "starting_seat": None if toss else "p0",
                                 "card_name_domain": card_name_domain(row["name"] for row in scenario.decklist),
                                 "extensions": [], "probe": False})
        deck = {"deck_id": deck_id(scenario.decklist), "catalog_id": f"Scenario:{scenario.name}"}
        validator = LiveValidator(hello, rules)
        response = engine.reset(ResetRequest.from_json({
            "request_type": "reset", "protocol": "spellbench/v2", "request_id": engine.next_request_id(),
            "game_id": "g-00000000000000aa", "format": "pauper-bo1",
            "seats": [{"seat": "p0", "deck": deck}, {"seat": "p1", "deck": deck}], "rules": rules.to_json(),
            "game_secret": "22" * 32, "max_decisions": 10000, "max_steps": 100000}))
        while isinstance(response, Decision):
            sd = validator.check(response)
            decisions.append(sd)
            validator.answered(sd, 0)
            response = engine.step(candidate_id=0, semantic=sd["candidates"][0]["semantic"])
        validator.check_terminal(response)
        counts = (response.result.step_count, response.result.decision_count)
        assert counts == (validator.answered_steps, validator.completed_groups), counts
    finally:
        engine.close()
    return decisions
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_validator.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/validator.py python/tests/test_host_validator.py python/tests/tour_helpers.py
git commit -m "Host: the live validator, V1 to V10 in rule order"
```

## Wave 5

### Task 23: The game loop: routing, validation, digest and halts

**Effort:** 0.75 agent-day. **Wave:** 5. **Depends on:** Tasks 17, 18, 21, 22.

**Files:**
- Create: `python/spellbench/host/game.py`
- Create: `python/tests/test_host_game.py`

**Interfaces:**
- Consumes: `host.validator.LiveValidator` (Task 22); `host.engine_process.EngineProcess` (Task 18); `host.seat.SeatDriver`, `SeatFailure`, `host.setup.GameSetup` (Task 17); `agent_messages` payload builders, `OwnDeck`, `Clock`, `AgentTerminal`, `Choice` (Task 17); `digests.GameDigest` (Task 2); `messages` (Task 9); `errors`.
- Produces (`spellbench.host.game`):
  - `GameSetup`, re-exported from `host.setup` (Task 17)
  - `@dataclass(frozen=True) class GameResult: outcome: str; classification: str; winner: str | None; reason: str; adjudication: dict | None; step_count: int; decision_count: int; decisions_checked: int; last_selection_seat: str | None; game_digest: str; violation: dict | None; diagnostics: tuple[str, ...]` (`adjudication` in the ledger shape of Task 12; `violation` is `{"rule", "detail"}`)
  - `play_game(setup: GameSetup, *, engine: EngineProcess, seats: Mapping[str, SeatDriver], clock_ns: Callable[[], int] = time.monotonic_ns) -> GameResult` (the engine has answered `hello`; the caller closes the engine and the seats)

Flow (spec 11.2, 11.5, 11.8): build the `reset` request (`engine.next_request_id()`, caps from `setup.limits`) and start the digest from it; send `game_start` to p0 then p1 (`game_start_ms`); send `reset`; then for each decision: validate (a violation halts with `host_validator:<rule>`), send `choose` (the validated seat decision, a `Clock`), check the answer (`candidate_id` in range; `seat_step` and `semantic_echo` echoes, when present, equal by canonical bytes, else `invalid_selection`), record the answer with the validator, send `step` with the chosen candidate's semantic as the echo. Every engine answer and step request goes into the digest (`add_response` for the answer to `reset`, `add_step` for each step, the answer omitted when none parsed). An engine terminal is checked for V10 and for exact counts (`step_count == answered_steps`, `decision_count == completed_groups`, else `host_engine_fault:terminal_counts`). Engine failures halt with `host_engine_fault:<fault>`: `error` (an error envelope), `timeout` (`PeerTimeoutError`, bound by `engine_step_ms`), `transport` (other `TransportError`), `malformed` (any other `ProtocolError`). A `SeatFailure` forfeits that seat with its cause. Every host-recorded ending (forfeit, halt, draw) appends the adjudication record to the digest, and every ending sends `game_over` (with that seat's `seat_step_count`) to each seat that was sent `game_start`, ignoring failures. `last_selection_seat` is the seat of the last answered decision for halted and truncated games, else None. Part B (Task 29) adds the bank clock, caps and stalling through the three hooks `_budget_ms(seat)`, `_charge(seat, sd, elapsed_ms)` and `_after_answer(seat, sd, candidate_id)`; in this task they return `max_decision_ms`, None and None.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_game.py`:

```python
"""One game through the host: routing, canonical forwarding, the digest, halts and forfeits (spec 11)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_messages import Choice, OwnDeck
from spellbench.digests import GameDigest, deck_id
from spellbench.errors import PeerTimeoutError
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.host.seat import SeatFailure
from spellbench.messages import DeckRow, Limits, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret

from conftest import ScriptedPeer
from test_messages import HELLO_OK, PROVENANCE, RULES
from v2_sample_semantics import seat_decision

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"
SECRET = RunSecret(bytes(range(32)))
ROWS = (DeckRow("Lightning Bolt", 4), DeckRow("Mountain", 18))
BURN = WireDeck(deck_id=deck_id([row.to_json() for row in ROWS]), catalog_id="Burn")
OWN = OwnDeck(deck_id=BURN.deck_id, name="Burn", decklist=ROWS)


def setup(index: int = 0, **changes) -> GameSetup:
    values = dict(game_index=index, game_id=SECRET.game_id(index), game_secret_hex=SECRET.game_secret(index).hex(),
                  format="pauper-bo1", wire_decks=(BURN, BURN), own_decks=(OWN, OWN), rules=Rules.from_json(RULES),
                  time_control=TimeControl(300000, 60000, 600000, 2000, 60000, 120000),
                  limits=Limits(10000, 100000, 500, 4999, 49999), resources=Resources(1, 4096, False, 1),
                  agent_seeds=(SECRET.agent_seed(index, "p0"), SECRET.agent_seed(index, "p1")))
    values.update(changes)
    return GameSetup(**values)


def fail(exc: BaseException):
    raise exc


class Seat:
    """A scripted SeatDriver: pick(decision) returns a candidate_id or a Choice, or raises."""

    def __init__(self, pick=lambda decision: 0, *, start_error: SeatFailure | None = None) -> None:
        self.pick, self.start_error, self.received = pick, start_error, []

    def start(self, game_start, *, timeout_s):
        self.received.append(("game_start", game_start))
        if self.start_error is not None:
            raise self.start_error

    def choose(self, choose, *, timeout_s):
        self.received.append(("choose", choose))
        result = self.pick(choose["decision"])
        return result if isinstance(result, Choice) else Choice(request_id="r", candidate_id=result, echoes={})

    def game_over(self, game_over, *, timeout_s):
        self.received.append(("game_over", game_over))

    def close(self) -> None:
        pass


def lands(decision) -> int:
    kinds = [candidate["semantic"]["kind"] for candidate in decision["candidates"]]
    return kinds.index("play_land") if "play_land" in kinds else 0


def real_engine() -> EngineProcess:
    engine = EngineProcess([sys.executable, str(ENGINE)], timeout_s=30)
    engine.hello()
    return engine


def scripted(*answers) -> tuple[EngineProcess, ScriptedPeer]:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), *answers])
    engine = EngineProcess(peer=peer)
    engine.hello()
    return engine, peer


def decision_line(request_id: str, step: int, sd: dict) -> bytes:
    return wire.canonical_json_dumps({"response_type": "decision", "protocol": "spellbench/v2", "request_id": request_id,
                                      "game_id": SECRET.game_id(0), "step": step, "seat_decision": sd, "provenance": PROVENANCE})


FIRST = decision_line("h-2", 0, seat_decision())


def test_a_natural_game_routes_both_seats() -> None:
    engine, p0, p1 = real_engine(), Seat(lands), Seat()
    try:
        result = play_game(setup(), engine=engine, seats={"p0": p0, "p1": p1})
    finally:
        engine.close()
    assert (result.outcome, result.classification, result.reason) == ("p0_win", "natural", "score")
    assert (result.step_count, result.decision_count, result.decisions_checked) == (4, 4, 4)
    assert result.adjudication is None and result.violation is None and result.last_selection_seat is None
    assert [kind for kind, _ in p0.received] == ["game_start", "choose", "choose", "game_over"]
    start = p0.received[0][1]
    assert set(start) == {"game_id", "seat", "format", "own_deck", "opponent_deck", "rules", "engine", "engine_profile",
                          "time_control", "limits", "resources", "agent_seed"}
    assert start["agent_seed"] == SECRET.agent_seed(0, "p0") and start["opponent_deck"] == start["own_deck"]
    assert set(p0.received[1][1]) == {"game_id", "decision", "clock"}
    assert p0.received[-1][1]["terminal"] == {"outcome": "p0_win", "classification": "natural", "winner": "p0",
                                              "reason": "score", "seat_step_count": 2}


def test_the_digest_is_reproducible_and_depends_on_the_secret() -> None:
    digests = []
    for index in (0, 0, 1):
        engine = real_engine()
        try:
            digests.append(play_game(setup(index), engine=engine, seats={"p0": Seat(lands), "p1": Seat()}).game_digest)
        finally:
            engine.close()
    assert digests[0] == digests[1] != digests[2]


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (PeerTimeoutError("slow"), "host_engine_fault:timeout"),
        (b"{broken", "host_engine_fault:malformed"),
        (wire.canonical_json_dumps({"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-3",
                                    "error": {"code": "game_id_mismatch", "message": "x"}}), "host_engine_fault:error"),
        (wire.canonical_json_dumps({"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-3",
                                    "game_id": SECRET.game_id(0), "outcome": "draw", "classification": "natural", "winner": None,
                                    "reason": "x", "step_count": 1, "decision_count": 7, "provenance": PROVENANCE}),
         "host_engine_fault:terminal_counts"),
    ],
)
def test_engine_faults_halt_after_the_last_selection(answer, reason: str) -> None:
    engine, _ = scripted(FIRST, answer)
    p1 = Seat()
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": p1})
    assert (result.classification, result.outcome, result.reason, result.winner) == ("halted", "halted", reason, None)
    assert result.adjudication["kind"] == "halt" and result.last_selection_seat == "p0"
    assert p1.received[-1][0] == "game_over"


def test_a_validator_violation_halts_and_the_digest_records_it() -> None:
    engine, peer = scripted(decision_line("h-2", 0, seat_decision(acting_seat="p1")))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert (result.reason, result.violation["rule"], result.last_selection_seat) == ("host_validator:V2", "V2", None)
    digest = GameDigest(wire.strict_json_loads(peer.sent[1]))
    digest.add_response(wire.strict_json_loads(decision_line("h-2", 0, seat_decision(acting_seat="p1"))))
    digest.add_adjudication(classification="halted", outcome="halted", reason="host_validator:V2", winner=None)
    assert result.game_digest == digest.value()


def test_a_seat_that_cannot_start_forfeits_before_any_reset() -> None:
    engine, peer = scripted()
    failing = Seat(start_error=SeatFailure("timeout", "no answer to game_start within 60000 ms"))
    result = play_game(setup(), engine=engine, seats={"p0": failing, "p1": Seat()})
    assert (result.classification, result.winner, result.reason, result.step_count) == ("forfeit", "p1", "forfeit:timeout", 0)
    assert result.adjudication == {"kind": "forfeit", "cause": "timeout", "loser_seat": "p0",
                                   "detail": "no answer to game_start within 60000 ms"}
    assert len(peer.sent) == 1                                           # only hello: no reset was sent
    assert [kind for kind, _ in failing.received] == ["game_start", "game_over"]


@pytest.mark.parametrize(
    ("pick", "cause"),
    [
        (lambda d: fail(SeatFailure("agent_error", "choose was answered with an error (internal_error)")), "agent_error"),
        (lambda d: 7, "invalid_selection"),
        (lambda d: Choice(request_id="r", candidate_id=0, echoes={"seat_step": 5}), "invalid_selection"),
        (lambda d: Choice(request_id="r", candidate_id=0, echoes={"seat_step": False}), "invalid_selection"),
        (lambda d: Choice(request_id="r", candidate_id=0, echoes={"semantic_echo": {"kind": "cast_spell"}}), "invalid_selection"),
    ],
)
def test_a_bad_answer_forfeits_the_acting_seat(pick, cause: str) -> None:
    engine, _ = scripted(FIRST)
    result = play_game(setup(), engine=engine, seats={"p0": Seat(pick), "p1": Seat()})
    assert (result.classification, result.winner, result.reason) == ("forfeit", "p1", f"forfeit:{cause}")
    assert (result.step_count, result.decisions_checked) == (0, 1)


def test_matching_echoes_are_accepted() -> None:
    engine, _ = scripted(FIRST, PeerTimeoutError("stop here"))
    echo = Choice(request_id="r", candidate_id=0, echoes={"seat_step": 0, "semantic_echo": {"kind": "pass"}})
    result = play_game(setup(), engine=engine, seats={"p0": Seat(lambda d: echo), "p1": Seat()})
    assert result.reason == "host_engine_fault:timeout"                 # the answer was valid; the engine then stalled
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_game.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.host.game`).

- [ ] **Step 3: Implement `host/game.py`**

```python
class _Game:
    def __init__(self, setup: GameSetup, engine: EngineProcess, seats: Mapping[str, SeatDriver], clock_ns) -> None:
        if engine.hello_result is None:
            raise ProtocolError("play_game needs an engine that answered hello")
        self.setup, self.engine, self.seats, self.clock_ns = setup, engine, seats, clock_ns
        self.hello = engine.hello_result
        self.validator = LiveValidator(self.hello, setup.rules)
        self.reset = ResetRequest(request_id=engine.next_request_id(), game_id=setup.game_id, format=setup.format,
                                  seats=setup.wire_decks, rules=setup.rules, game_secret=setup.game_secret_hex,
                                  max_decisions=setup.limits.max_decisions, max_steps=setup.limits.max_steps)
        self.digest = GameDigest(self.reset.to_json())
        self.started: list[str] = []
        self.last_seat: str | None = None
        self.diagnostics: list[str] = []

    def play(self) -> GameResult:
        for seat in ("p0", "p1"):
            self.started.append(seat)
            try:
                self.seats[seat].start(self._game_start_payload(seat),
                                       timeout_s=self.setup.time_control.game_start_ms / 1000)
            except SeatFailure as failure:
                return self._forfeit(seat, failure)
        response = self._engine("reset", lambda: self.engine.reset(self.reset), step=False)
        while not isinstance(response, GameResult):
            if isinstance(response, Terminal):
                return self._terminal(response)
            try:
                sd = self.validator.check(response)
            except ValidatorViolation as violation:
                return self._halt(f"host_validator:{violation.rule}", violation.detail, violation=violation)
            seat = sd["acting_seat"]
            answer = self._ask(seat, sd)
            if isinstance(answer, GameResult):
                return answer
            self.validator.answered(sd, answer)
            self.last_seat = seat
            ruling = self._after_answer(seat, sd, answer)
            if ruling is not None:
                return ruling
            semantic = sd["candidates"][answer]["semantic"]
            response = self._engine(f"step {response.step}",
                                    lambda: self.engine.step(candidate_id=answer, semantic=semantic), step=True)
        return response
```

`_engine(phase, call, *, step)` sets `engine.set_timeout(engine_step_ms / 1000)`, runs the call, chains `engine.last_response` (reset) or `engine.last_request` plus `engine.last_response` (step) into the digest whether the call succeeded or failed, and maps `EngineError`, `PeerTimeoutError`, other `TransportError`, and other `ProtocolError` to `_halt("host_engine_fault:<fault>", detail)` with the deterministic details "the engine answered {phase} with error {code}", "the engine did not answer {phase} within {ms} ms", "the engine process failed at {phase}", "the engine's answer to {phase} was not a valid protocol message" (the exception text and `engine.stderr_text()` go to `diagnostics`). `_halt`, `_forfeit` and (in Task 29) `_draw` each call `digest.add_adjudication` once, send `game_over` to every started seat with an `AgentTerminal` carrying that seat's `validator.answered_by(seat)`, and build the `GameResult`. Echo comparisons use `wire.canonical_json_dumps` on both sides (so `False` never equals `0`).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_game.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/game.py python/tests/test_host_game.py
git commit -m "Host: the v2 game loop with validation, canonical forwarding and the digest"
```

### Task 24: Seat drivers

**Effort:** 0.5 agent-day. **Wave:** 5. **Depends on:** Tasks 6, 11, 17, 19.

**Files:**
- Create: `python/spellbench/arena/drivers.py`
- Create: `python/tests/test_arena_drivers.py`

**Interfaces:**
- Consumes: `host.seat.SeatDriver`, `SeatFailure`; `host.agent_process.AgentProcess`; `agent_messages.Choice` (Task 17); `builtins.create_builtin_bot` (Task 11); `bot.Decision`, `bot.GameStart`, `bot.GameOver` (Task 6); `arena.config.BotSpec` (Task 19); `wire`.
- Produces (`spellbench.arena.drivers`):
  - `class BuiltinDriver(spec: BotSpec, *, factory: Callable[[], Any] | None = None)` (a fresh bot per `start`: `create_builtin_bot(spec.name, seed=spec.seed)` unless `factory` is given)
  - `class SubprocessDriver(spec: BotSpec, *, startup_ms: int, agent_factory: Callable[[], AgentProcess] | None = None)` (a fresh process per game; `hello` within `startup_ms`; the bot must name itself `spec.name` and `spec.version`, else `SeatFailure("malformed_response", "hello named a different bot than its config entry")`)
  - `make_driver(spec: BotSpec, time_control: TimeControl) -> SeatDriver`

Both implement `SeatDriver`. The builtin driver hands its bot the payloads round-tripped through canonical JSON (so a bot sees exactly what a subprocess bot would, and cannot mutate the host's copy), runs each call on a thread bounded by `timeout_s` (`timeout` on expiry, `agent_error` when the bot raises, `malformed_response` when `choose` returns a non-integer), and returns `Choice(request_id="builtin", candidate_id=..., echoes={})`. `game_over` never raises.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_drivers.py`:

```python
"""Builtin and subprocess seat drivers."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import BuiltinDriver, SubprocessDriver
from spellbench.host.seat import SeatFailure

MINIMAL = Path(__file__).resolve().parents[2] / "examples" / "minimal_bot.py"
DECISION = {"acting_seat": "p0", "seat_step": 0, "candidates": [
    {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None},
    {"candidate_id": 1, "semantic": {"kind": "play_land", "face": 0}, "display_text": None}]}
CHOOSE = {"game_id": "g-1", "decision": DECISION, "clock": {"remaining_ms": 1000, "max_decision_ms": 1000}}
START = {"game_id": "g-1", "seat": "p0", "agent_seed": 42}


def builtin(name: str) -> BotSpec:
    return BotSpec(name=name, version="2.0.0", type="builtin")


def test_builtin_bots_play_and_cannot_mutate_the_host_copy() -> None:
    class Mutator:
        def on_game_start(self, game): pass
        def choose(self, decision):
            decision.raw["candidates"].clear()
            return 1
        def on_game_over(self, game_over): pass

    driver = BuiltinDriver(builtin("first"), factory=Mutator)
    driver.start(START, timeout_s=5)
    assert driver.choose(CHOOSE, timeout_s=5).candidate_id == 1
    assert len(CHOOSE["decision"]["candidates"]) == 2
    heuristic = BuiltinDriver(builtin("heuristic"))
    heuristic.start(START, timeout_s=5)
    assert heuristic.choose(CHOOSE, timeout_s=5).candidate_id == 1


@pytest.mark.parametrize(
    ("choose", "cause"),
    [(lambda decision: time.sleep(5), "timeout"), (lambda decision: 1 / 0, "agent_error"), (lambda decision: "1", "malformed_response")],
)
def test_builtin_failures(choose, cause: str) -> None:
    class Bot:
        def on_game_start(self, game): pass
        def on_game_over(self, game_over): pass

    Bot.choose = staticmethod(choose)
    driver = BuiltinDriver(builtin("first"), factory=Bot)
    driver.start(START, timeout_s=5)
    with pytest.raises(SeatFailure) as caught:
        driver.choose(CHOOSE, timeout_s=0.3)
    assert caught.value.cause == cause


def test_a_subprocess_bot_per_game() -> None:
    spec = BotSpec(name="minimal", version="1.0.0", type="subprocess", command=(sys.executable, str(MINIMAL)))
    driver = SubprocessDriver(spec, startup_ms=30_000)
    try:
        driver.start(START, timeout_s=30)
        assert driver.choose(CHOOSE, timeout_s=30).candidate_id == 0
        driver.game_over({"game_id": "g-1", "terminal": {}}, timeout_s=30)
    finally:
        driver.close()


def test_a_subprocess_bot_must_name_its_config_entry() -> None:
    spec = BotSpec(name="someone-else", version="1.0.0", type="subprocess", command=(sys.executable, str(MINIMAL)))
    driver = SubprocessDriver(spec, startup_ms=30_000)
    with pytest.raises(SeatFailure, match="different bot"):
        driver.start(START, timeout_s=30)
    driver.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_drivers.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.arena.drivers`).

- [ ] **Step 3: Implement `arena/drivers.py`**

Port the thread-and-queue pattern of v1 `runner._BuiltinDriver.choose` for every builtin call, with `bot.GameStart.from_request(json.loads(canonical_json_dumps(payload)))` and the same for `bot.Decision` and `bot.GameOver`. `SubprocessDriver.start` creates the `AgentProcess` (`agent_factory()` or `AgentProcess(list(spec.command), startup_timeout_s=startup_ms / 1000)`), calls `hello()`, checks the identity, then `game_start(payload, timeout_s=timeout_s)`; `SeatFailure` propagates unchanged, and `close()` is idempotent.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_drivers.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/drivers.py python/tests/test_arena_drivers.py
git commit -m "Arena: builtin and subprocess seat drivers for protocol v2"
```

### Task 25: Schedule and preflight

**Effort:** 0.5 agent-day. **Wave:** 5. **Depends on:** Tasks 17, 18, 19, 21.

**Files:**
- Create: `python/spellbench/arena/schedule.py`
- Create: `python/tests/test_arena_schedule_v2.py`

**Interfaces:**
- Consumes: `arena.config` (Task 19); `host.engine_process.EngineProcess` (Task 18); `host.agent_process.AgentProcess`, `agent_messages.OwnDeck`, `host.setup.GameSetup` (Task 17; not `host.game`, which Task 23 writes in this wave); `run_secret.RunSecret`, `digests` (Task 2); `messages` (Task 9).
- Produces (`spellbench.arena.schedule`):
  - `@dataclass(frozen=True) class ResolvedDeck: deck_id: str; name: str; catalog_id: str | None; decklist: tuple[DeckRow, ...]` with `wire() -> WireDeck`, `own() -> OwnDeck`, `ledger() -> LedgerDeck`
  - `@dataclass(frozen=True) class RunSetup: hello: EnvHelloOk; decks: dict[DeckSpec, ResolvedDeck]; rules: Rules; native_id_extensions: tuple[dict, ...]` with properties `engine -> EngineIdentity`, `profile -> EngineProfile`
  - `@dataclass(frozen=True) class GameContext: game_index: int; game_id: str; matchup_index: int; pair_index: int; pair_slot: int; seat_specs: tuple[tuple[str, BotSpec], tuple[str, BotSpec]]; decks: tuple[DeckSpec, DeckSpec]`
  - `class EnginePin` with `check(identity: EngineIdentity) -> None` (drift between engine processes is a `TournamentError`) and property `identity`
  - `preflight(config: TournamentConfig, run_secret: RunSecret, *, pin: EnginePin | None = None) -> RunSetup`
  - `schedule(config: TournamentConfig, run_secret: RunSecret) -> list[GameContext]`
  - `game_setup(config: TournamentConfig, setup: RunSetup, context: GameContext, run_secret: RunSecret) -> GameSetup`

Preflight (spec 11.1; a failure is a `TournamentError` naming the engine, deck or bot, raised before anything is written): start the engine with `startup_ms`, `hello` (an invalid `hello_ok`, such as a non-NFC catalog name, reports the parse error, which names the card and the deck); the format must be in `formats`; resolve every `DeckSpec` (a catalog id through `hello.catalog`, needing `catalog` in `deck_sources`; a decklist needing `decklist`), computing `deck_id` with `digests.deck_id`; resolve the rules (`mulligan: "auto"` becomes `london` when `rules_supported.mulligan` has it, else `none`; explicit values and the starting player must be supported), `card_name_domain` over every name of every resolved deck, `extensions` each declared by the engine, and each `native_ids: true` extension needing an entry in `native_id_audits` (recorded as `{"name", "audit"}`); reset each deck pairing once in its own engine process with `run_secret.preflight_secret(k)` and `preflight_game_id(k)`, pinning the identity; then start each subprocess bot once: `hello`, the identity, and its `requires` (observation flags the engine does not declare, or extensions the run does not enable, refuse the entry). The schedule is the v1 round robin (`combinations_with_replacement` order, self-play switch, pool rotation, seat swap by `pair_slot`) with `game_index` counting from 0 in schedule order and `game_id = run_secret.game_id(game_index)`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_schedule_v2.py`:

```python
"""Preflight, schedule and per-game setup (spec 11.1, 11.6, 12)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.schedule import game_setup, preflight, schedule
from spellbench.digests import deck_id
from spellbench.run_secret import RunSecret

from test_messages import HELLO_OK

TESTS = Path(__file__).resolve().parent
ENGINE = TESTS / "fake_v2_engine.py"
SECRET = RunSecret(bytes(range(32)))


def config(*, engine_args=(), bots=None, **changes) -> TournamentConfig:
    value = {"schema": "spellbench-tournament-config/v2", "tournament_dir": "unused", "format": "pauper-bo1",
             "deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}],
             "engine": {"command": [sys.executable, str(ENGINE), *engine_args]},
             "bots": bots or [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
                              {"name": "first", "version": "2.0.0", "type": "builtin"}],
             "pairs_per_matchup": 2, "stats_seed": 1, "include_self_play": False}
    value.update(changes)
    return TournamentConfig.from_json(value)


def test_preflight_resolves_decks_rules_and_the_domain() -> None:
    setup = preflight(config(), SECRET)
    burn = setup.decks[config().deck_pool[0]]
    assert burn.deck_id == deck_id([{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}])
    assert setup.rules.mulligan == "none" and setup.rules.starting_seat == "p0"
    assert setup.rules.card_name_domain.names == ("Lightning Bolt", "Mountain")
    assert preflight(config(engine_args=("--london",)), SECRET).rules.mulligan == "london"


def test_the_schedule_uses_opaque_ids_and_swaps_seats() -> None:
    games = schedule(config(), SECRET)
    assert [game.game_id for game in games] == [SECRET.game_id(index) for index in range(4)]
    assert [(game.pair_index, game.pair_slot) for game in games] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert games[0].seat_specs[0][1].name == games[1].seat_specs[1][1].name == "uniform"
    assert [game.decks[0].catalog_id for game in games] == ["Burn", "Burn", "Elves", "Elves"]


def test_game_setup_derives_everything_from_the_run_secret() -> None:
    cfg = config()
    setup = preflight(cfg, SECRET)
    one = game_setup(cfg, setup, schedule(cfg, SECRET)[1], SECRET)
    assert one.game_secret_hex == SECRET.game_secret(1).hex()
    assert one.agent_seeds == (SECRET.agent_seed(1, "p0"), SECRET.agent_seed(1, "p1"))
    assert one.own_decks[0].name == "Burn" and one.wire_decks[0].catalog_id == "Burn"


def _canned_engine(tmp_path: Path, hello: dict) -> list[str]:
    script = tmp_path / "canned_engine.py"
    script.write_text(
        "import json, sys\n"
        f"HELLO = {json.dumps(hello)!r}\n"
        "for line in sys.stdin.buffer:\n"
        "    request = json.loads(line)\n"
        "    answer = json.loads(HELLO)\n"
        "    answer['request_id'] = request['request_id']\n"
        "    sys.stdout.write(json.dumps(answer) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_an_nfd_catalog_stops_preflight_naming_the_card_and_deck(tmp_path: Path) -> None:
    hello = copy.deepcopy(HELLO_OK)
    hello["catalog"] = [{"catalog_id": "Vault", "name": "Vault", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 4}]}]
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)}, deck_pool=[{"catalog_id": "Vault"}])
    with pytest.raises(TournamentError, match=r"Vault.*Lim-Du\u0302l's Vault.*NFC"):
        preflight(cfg, SECRET)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Refuse"}]}, "unsupported_deck"),
        ({"deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Nope"}]}, "catalog"),
        ({"format": "modern"}, "format"),
        ({"rules": {"mulligan": "london"}}, "mulligan"),
        ({"extensions": ["x_kernel_v5"]}, "x_kernel_v5"),
    ],
)
def test_config_errors_stop_before_any_game(changes: dict, message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        preflight(config(**changes), SECRET)


def test_a_bot_whose_requirements_are_unmet_is_refused(tmp_path: Path) -> None:
    bot = tmp_path / "needs_poison.py"
    bot.write_text("import sys\nfrom spellbench.bot import serve\n"
                   "sys.exit(serve(choose=lambda d: 0, name='needy', version='1', requires_observation=('poison',)))\n", encoding="utf-8")
    bots = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
            {"name": "needy", "version": "1", "type": "subprocess", "command": [sys.executable, str(bot)]}]
    with pytest.raises(TournamentError, match="needy.*poison"):
        preflight(config(bots=bots), SECRET)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_schedule_v2.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.arena.schedule`).

- [ ] **Step 3: Implement `arena/schedule.py`**

Port `_EnginePin`, `_preflight_engine`, `_preflight` and `_schedule` from v1 `runner.py` into the public names above with the v2 steps. Wrap every engine or bot failure as `TournamentError(f"preflight: ...: {exc}")` so the underlying message (which names the card, deck, code or requirement) is kept. `game_setup` sets `opponent_deck` visibility through the rules; `own_decks[i]` is the resolved deck of seat `i`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_schedule_v2.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/schedule.py python/tests/test_arena_schedule_v2.py
git commit -m "Arena: v2 preflight, the opaque-id schedule and per-game setup"
```

### Task 26: Engine tours: every kind, group shape and board field

**Effort:** 0.75 agent-day. **Wave:** 5. **Depends on:** Tasks 13, 21, 22.

**Files:**
- Create: `python/tests/fake_v2_scenario_kinds.py`, `python/tests/fake_v2_scenario_board.py`
- Create: `python/tests/test_fake_v2_tours.py`

**Interfaces:**
- Consumes: `fake_v2_world.World`, `Posed`, `Scenario` (Task 13); the fake engine's scenario discovery (Task 21); `tour_helpers.play_tour` (Task 22).
- Produces: `SCENARIO` in each module (catalog ids `Scenario:kinds`, `Scenario:board`), used by the goldens (Task 34) and the conformance tests (Task 32).

`Scenario:kinds` (engine args `--london`, `--toss`, `--rewind`; rules `mulligan: london`, `starting_player: toss_winner_chooses`) scripts a game that poses, in order: `choose_starting_player`; `mulligan` twice (keep false, then keep true with `mulligans_taken: 1`) and the `mulligan_bottom` pick; priority with `play_land` (face 0, and face 1 of the modal double-faced land), `cast_spell` with `method: null` then `choose_cast_method`, `special_action`, `activate_mana_ability`, `activate_ability`; a fixed two-target spell (one group of two `choose_target`); a variable-target spell (`choose_target` then `finish_target_selection`, one group each); `choose_cost_target`; "choose two" modes (a group of two `choose_spell_mode`) and "one or more" ended by `finish_selection` with `purpose: "modes"`; `choose_option`, `choose_color`, `choose_number` (`x_value`), `choose_boolean`, `choose_name` (a name from the domain); a fixed discard (`select_object` group of two); a library search (`select_object` with `purpose: "search"`, `minimum: 0`, candidates in `(card_name, object_id)` order, the cards in `known` with `how: "searching"` and fresh ids) ended by `finish_selection`; `optional_cost` (kicker), `choose_cost_option`, `optional_cast` (madness); a resolution-time payment (`context.purpose: "mana_payment"`: `optional_cost` `unless_payment` with `pay: true` and `pay: false`, plus `activate_mana_ability`, re-posed after the activation); two triggers ordered by one `order_pick` (`purpose: "triggers"`, the last position implied); scry 2 (one group of three: two `arrange_card`, one `order_pick` `arrangement`); `choose_replacement`; attacks (a group of two `declare_attack`, one with `defender: null`), blocks (a group of `declare_block`, one blocker with an additional block); combat damage `distribute` (a group of two); a pile split (arrangement with `pile_0` and `pile_1`) and `choose_pile`; and a rewind (a `cast_spell`, a `choose_target`, then the priority decision re-posed with `context.rewind: true`). `Scenario:board` (no engine args; the World's flags follow the engine's) places at least one of everything spec 6 shows: poison, energy counters, the monarch, dungeon progress, day, passed seats, a pending trigger (and a hidden-source trigger that is omitted), keywords, a modal double-faced card's `full_name`, an `exiled_by` link, stack text, `goaded`, a Class at level 2, a chosen card name, an Aura (`attached_to`), a creature attacking a planeswalker, a blocker with `blocked_attackers`, a face-down creature of each seat, a token copy, a stack spell whose target left (a `null` target), divided damage, modes and X.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_fake_v2_tours.py`:

```python
"""The tours pass the live validator and cover every v2.0 kind, group shape and board field."""

from __future__ import annotations

from spellbench.candidates import V2_KINDS

import fake_v2_scenario_board
import fake_v2_scenario_kinds
from tour_helpers import play_tour


def test_the_kinds_tour_covers_every_kind_and_group_shape() -> None:
    decisions = play_tour(fake_v2_scenario_kinds)
    kinds = {c["semantic"]["kind"] for sd in decisions for c in sd["candidates"]}
    assert kinds == V2_KINDS
    multi = {(sd["candidates"][0]["semantic"]["kind"], sd["group"]["substep_count"]) for sd in decisions if sd["group"]["substep_count"] > 1}
    assert {"declare_attack", "declare_block", "choose_target", "select_object", "choose_spell_mode", "distribute", "arrange_card"} <= {kind for kind, _ in multi}
    assert ("arrange_card", 3) in multi                                  # scry 2: 2n - 1 decisions
    assert any(sd["context"]["rewind"] for sd in decisions)
    assert any(sd["context"]["purpose"] == "mana_payment" for sd in decisions)


def _optional_values(sd: dict) -> dict[str, list]:
    observation = sd["observation"]
    records = [r for player in observation["players"] for zone in ("hand", "battlefield", "graveyard", "exile", "command")
               for r in (player[zone] or [])]
    return {
        "poison": [p["poison"] for p in observation["players"]], "player_counters": [p["counters"] for p in observation["players"]],
        "designations": [p["designations"] for p in observation["players"]], "player_progress": [p["progress"] for p in observation["players"]],
        "day_night": [observation["day_night"]], "passed_seats": [observation["passed_seats"]], "pending_triggers": [observation["pending_triggers"]],
        "keywords": [r["characteristics"]["keywords"] for r in records if r["characteristics"]],
        "full_name": [r["full_name"] for r in records], "exiled_by": [r["exiled_by"] for r in records],
        "stack_text": [entry["text"] for entry in observation["stack"]],
        "permanent_details": [r["permanent"]["statuses"] for r in records if r["permanent"]],
    }


def test_the_board_tour_shows_every_optional_field_or_none() -> None:
    on = play_tour(fake_v2_scenario_board, "--all-flags")
    for flag in _optional_values(on[0]):
        assert any(value is not None and value != [] for sd in on for value in _optional_values(sd)[flag]), flag
    off = play_tour(fake_v2_scenario_board)
    for flag, values in _optional_values(off[-1]).items():
        assert all(value is None for value in values), flag
    assert any(r["face_down"] and r["card_name"] is None for sd in on for r in sd["observation"]["players"][1]["battlefield"])
    assert any(None in entry["targets"] for sd in on for entry in sd["observation"]["stack"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_fake_v2_tours.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: fake_v2_scenario_board`).

- [ ] **Step 3: Write the two scenario modules**

Each module builds a `Scenario` whose `script(world)` is a generator: it sets up objects with `world.add`, yields `Posed` decisions, and moves objects between yields so each observation matches what the next decision references (the engine resolves references per viewer; a scenario never writes an object id by hand). Keep every posed decision valid on its own: `pass` first whenever it is offered, distinct semantics, hidden-zone candidates sorted, the arrangement fixed at 2n - 1, a partial group never interleaved with the other seat. When the validator rejects a decision, fix the script, not the validator.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_fake_v2_tours.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/tests/fake_v2_scenario_kinds.py python/tests/fake_v2_scenario_board.py python/tests/test_fake_v2_tours.py
git commit -m "Tests: fake engine tours of every v2.0 kind, group shape and board field"
```

### Task 27: Knowledge tour: every update-table row

**Effort:** 0.5 agent-day. **Wave:** 5. **Depends on:** Tasks 13, 15, 21, 22.

**Files:**
- Create: `python/tests/fake_v2_knowledge.py`
- Create: `python/tests/fake_v2_scenario_knowledge.py`
- Create: `python/tests/test_fake_v2_knowledge.py`

**Interfaces:**
- Consumes: `fake_v2_world.World`, `Posed`, `Scenario` (Task 13); the engine's scenario discovery (Task 21); `host.hidden.known_sort_key` (Task 15); `tour_helpers.play_tour` (Task 22).
- Produces:
  - `fake_v2_knowledge.Knowledge(world: World, viewer: str)`: a reference implementation of the spec 6.7 update table, one method per row: `public_to_other_hand(name)`, `known_library_card_drawn(owner, end)`, `other_hand_revealed(names)`, `other_hand_to_public(name)`, `other_hand_to_hidden(count)`, `other_hand_randomized()`, `library_shuffled(owner)`, `looked_at(owner, cards: list[tuple[str, str, int]], how)` (`(name, end, position)`), `left_library_end(owner, end)`, `put_on_library_end(owner, end, name: str | None)`, `hidden_rearrangement(owner, end, depth)`, `ambiguous_insertion(owner, end, depth)`, `left_unknown_position(owner)`; `entries() -> list[dict]` (sorted by `known_sort_key`; it writes `world.known[viewer]`)
  - `SCENARIO` (`Scenario:knowledge`, engine args `--flags known_cards`): the rows fired in order 1 to 13, each followed by one decision whose `context.text` is `"row <n>"`
  - `EXPECTED: dict[int, list[dict]]`: viewer p0's `known` entries (without `object_id`) after each row

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_fake_v2_knowledge.py`:

```python
"""Knowledge (spec 6.7): every update-table row, through the validator."""

from __future__ import annotations

from spellbench.run_secret import RunSecret

import fake_v2_scenario_knowledge
from fake_v2_knowledge import Knowledge
from fake_v2_world import World
from tour_helpers import play_tour

FLAGS = {"known_cards": True}


def _entry(owner, zone, name, top=None, bottom=None, how="revealed") -> dict:
    return {"owner_seat": owner, "zone": zone, "card_name": name, "object_id": None,
            "position_from_top": top, "position_from_bottom": bottom, "how": how}


def fresh() -> Knowledge:
    return Knowledge(World(RunSecret(bytes(range(32))).game_secret(0), flags=FLAGS), "p0")


def test_hidden_departures_reduce_every_name() -> None:
    knowledge = fresh()
    knowledge.other_hand_revealed(["Counterspell", "Counterspell", "Island"])
    knowledge.other_hand_to_hidden(1)       # row 5: one card went back unseen, so each name's count c becomes max(0, c - 1)
    assert knowledge.entries() == [_entry("p1", "hand", "Counterspell")]


def test_library_ends_renumber() -> None:
    knowledge = fresh()
    knowledge.looked_at("p0", [("Mountain", "top", 0), ("Island", "top", 1)], "looked_at")     # row 8
    knowledge.left_library_end("p0", "top")                                                     # row 9: the top card drawn
    assert knowledge.entries() == [_entry("p0", "library", "Island", top=0, how="looked_at")]
    knowledge.put_on_library_end("p0", "top", None)                                            # row 10: an unknown card on top
    assert knowledge.entries() == [_entry("p0", "library", "Island", top=1, how="looked_at")]
    knowledge.hidden_rearrangement("p0", "top", 2)                                             # row 11: the other seat reorders two
    assert knowledge.entries() == []


def test_the_knowledge_tour_fires_every_row_and_passes_the_validator() -> None:
    decisions = play_tour(fake_v2_scenario_knowledge)
    marked = {int(sd["context"]["text"].split()[1]): sd for sd in decisions if (sd["context"]["text"] or "").startswith("row ")}
    assert sorted(marked) == list(range(1, 14))
    for row, expected in fake_v2_scenario_knowledge.EXPECTED.items():
        if marked[row]["acting_seat"] == "p0":
            seen = [{k: v for k, v in entry.items() if k != "object_id"} for entry in marked[row]["observation"]["known"]]
            assert seen == [{k: v for k, v in entry.items() if k != "object_id"} for entry in expected], row
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_fake_v2_knowledge.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: fake_v2_knowledge`).

- [ ] **Step 3: Implement**

`Knowledge` keeps entries as dicts and applies each row literally as spec 6.7 states it (the "remove every entry the insertion or removal makes ambiguous" rows remove all entries at or beyond the affected depth from that end, and every entry counted from the other end when the library size is unknown to the viewer). Keep one decision per row, posed to p0 wherever the row concerns p0's view, so `EXPECTED` pins what p0 sees; the scenario's decisions otherwise follow the Task 26 rules.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_fake_v2_knowledge.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/tests/fake_v2_knowledge.py python/tests/fake_v2_scenario_knowledge.py python/tests/test_fake_v2_knowledge.py
git commit -m "Tests: a reference knowledge model and a tour of every update-table row"
```

### Task 28: Hostile engine and hostile bots

**Effort:** 0.5 agent-day. **Wave:** 5. **Depends on:** Tasks 17, 18, 21, 22.

**Files:**
- Create: `python/tests/hostile_v2_engine.py`
- Create: `python/tests/bot_v2_hostile.py`
- Create: `python/tests/test_hostile_v2.py`

**Interfaces:**
- Consumes: `fake_v2_engine.serve` with `mutate` (Task 21); `host.engine_process`, `host.validator` (Tasks 18, 22); `host.agent_process`, `host.seat.SeatFailure` (Task 17); `wire`.
- Produces:
  - `python hostile_v2_engine.py MODE [fake engine args...]`: the scoring game with one fault injected at the second decision (step 1) or its terminal; `hostile_v2_engine.MODES: dict[str, str]` mapping each mode to the expected outcome, a rule (`"V1"` to `"V10"`) or a fault (`"malformed"`, `"error"`, `"timeout"`, `"transport"`, `"terminal_counts"`)
  - `python bot_v2_hostile.py MODE`: a bot that misbehaves in one way and is otherwise the minimal bot (as `hostile` 1.0.0); `bot_v2_hostile.MODES: dict[str, str]` mapping each mode to the `AgentProcess` outcome (a `SeatFailure` cause, or `"ok"`)

Engine modes (all at step 1 unless noted): `unknown-kind`, `reserved-kind`, `duplicate-semantics`, `pass-not-first`, `nfd-name` (V1); `viewer-mismatch` (V2); `seat-step-gap`, `group-skip` (V3); `stale-reference`, `absent-reference`, `duplicate-id` (V4); `opponent-hand`, `hand-count`, `library-record`, `known-unsorted` (V5, the last with `--flags known_cards`); `face-down-name` (V6); `id-two-zones` (V7, at step 2: p0's played Mountain keeps its hand id); `undeclared-kind` (V8, with `--kinds pass,play_land,cast_spell,declare_attack,declare_block` and a `choose_boolean` candidate), `flag-off-value`, `undeclared-extension` (V8); `family-mismatch` (V9); `provenance-drift` (V10); `garbage-json`, `wrong-request-id`, `deep-json` (an extension nested 70 levels) (malformed); `error-on-step` (error); `hang-on-step` (timeout; sleeps 60 s); `crash-on-step` (transport; exits 5); `bad-terminal-counts` (terminal_counts; `decision_count` plus 1).

Bot modes: `garbage`, `nested` (5000 levels), `deep65`, `flood` (16 MiB line), `bigint` (5000-digit id), `string-id`, `float-id`, `surrogate-error`, `stdout-noise` (prints `Loading model weights...` before `hello_ok`), `badname` (a lone surrogate in the name) are `malformed_response`; `error-response`, `decision-pending` are `agent_error`; `crash` is `transport_error`; `hang`, `slow-hello`, `slow-game-start` are `timeout`; `wrong-echo-step`, `wrong-echo-semantic`, `out-of-range`, `extra-fields`, `crlf`, `crash-on-game-over`, `requires-poison`, `wrong-name` (answers `hello` as `impostor`) are `ok` at this layer (the game loop, the drivers or preflight judge them). `crash` writes `Traceback ... pid=<its pid>` to stderr before exiting, so reruns prove no peer text reaches the ledger.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_hostile_v2.py`:

```python
"""Hostile participants trip exactly the rule or fault they target."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

from spellbench.errors import EngineError, PeerTimeoutError, ProtocolError, TransportError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.seat import SeatFailure
from spellbench.host.validator import LiveValidator
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import Decision, ResetRequest, Rules

import bot_v2_hostile
import hostile_v2_engine
from test_messages import RESET, RULES

TESTS = Path(__file__).resolve().parent
FAULTS = ((PeerTimeoutError, "timeout"), (TransportError, "transport"), (EngineError, "error"), (ProtocolError, "malformed"))


def outcome_of_engine(mode: str) -> str:
    engine = EngineProcess([sys.executable, str(TESTS / "hostile_v2_engine.py"), mode], timeout_s=3)
    try:
        validator = LiveValidator(engine.hello(), Rules.from_json(RULES))
        response = engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))
        while isinstance(response, Decision):
            sd = validator.check(response)
            pick = len(sd["candidates"]) - 1                  # play the land whenever one is offered
            validator.answered(sd, pick)
            response = engine.step(candidate_id=pick, semantic=sd["candidates"][pick]["semantic"])
        validator.check_terminal(response)
        if response.result.decision_count != validator.completed_groups:
            return "terminal_counts"
        return "clean"
    except ValidatorViolation as violation:
        return violation.rule
    except (PeerTimeoutError, TransportError, EngineError, ProtocolError) as exc:
        return next(name for kind, name in FAULTS if isinstance(exc, kind))
    finally:
        engine.close()


@pytest.mark.parametrize("mode", sorted(hostile_v2_engine.MODES))
def test_each_hostile_engine_mode_is_caught(mode: str) -> None:
    assert outcome_of_engine(mode) == hostile_v2_engine.MODES[mode]


def test_every_rule_has_a_hostile_engine() -> None:
    assert {f"V{number}" for number in range(1, 11)} <= set(hostile_v2_engine.MODES.values())


def outcome_of_bot(mode: str) -> str:
    agent = AgentProcess([sys.executable, str(TESTS / "bot_v2_hostile.py"), mode], startup_timeout_s=3)
    decision = {"acting_seat": "p0", "seat_step": 0,
                "candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}
    try:
        agent.hello()
        agent.game_start({"game_id": "g-1", "seat": "p0"}, timeout_s=3)
        agent.choose({"game_id": "g-1", "decision": decision, "clock": {}}, timeout_s=1)
        return "ok"
    except SeatFailure as failure:
        return failure.cause
    finally:
        agent.close()


@pytest.mark.parametrize("mode", sorted(bot_v2_hostile.MODES))
def test_each_hostile_bot_mode_maps_to_its_cause(mode: str) -> None:
    assert outcome_of_bot(mode) == bot_v2_hostile.MODES[mode]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_hostile_v2.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: bot_v2_hostile`).

- [ ] **Step 3: Implement the two fixtures**

`hostile_v2_engine.py` defines one `mutate(step, message)` per mode and calls `fake_v2_engine.serve(argv, mutate=MUTATIONS[mode])` with any fixed engine arguments the mode needs; every mutation edits a deep copy and leaves the message otherwise valid, so exactly one rule breaks. `bot_v2_hostile.py` follows the v1 `bot_hostile.py` shape with the v2 envelope; `MODES` is the table above.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_hostile_v2.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/tests/hostile_v2_engine.py python/tests/bot_v2_hostile.py python/tests/test_hostile_v2.py
git commit -m "Tests: hostile v2 engines and bots, one per rule and fault"
```

## Wave 6

### Task 29: The game loop: clocks, caps, stalling and forfeits

**Effort:** 0.75 agent-day. **Wave:** 6. **Depends on:** Tasks 3, 23, 24, 28.

**Files:**
- Modify: `python/spellbench/host/game.py` (the three hooks of Task 23, `_draw`)
- Create: `python/tests/test_host_game_adjudication.py`

**Interfaces:**
- Consumes: `host.clock.SeatClock`, `SeatCaps`, `StallingWindow`, `is_real_choice` (Task 3); Task 23's `_Game`; the drivers (Task 24); the hostile fixtures (Task 28).
- Produces: no new names. `play_game` now enforces spec 11.4: each seat starts with `SeatClock(bank_ms, increment_ms, max_decision_ms)`; `choose` carries `Clock(remaining_ms=<bank before this decision>, max_decision_ms)`; the seat's budget is `clock.budget_ms()`; after the answer, `clock.charge(elapsed_ms)` false is a `timeout` forfeit ("the answer to choose at seat step {n} exceeded the seat's clock"), even when an answer arrived; `SeatCaps` records every answered decision (`turn` from the observation, `completed_group` when the substep was the group's last) and `StallingWindow` records `is_real_choice(len(candidates), chosen kind)`; when a cap is reached, before the step is sent, the ruling is a `stalling` forfeit of `ruling.loser_seat` ("{seat} reached {cap} ({limit}); real choices in the last 250 decisions: p0 {a}, p1 {b}") or a `mandatory_loop` draw (outcome `draw`, classification `natural`, winner null, reason `mandatory_loop`, adjudication `{"kind": "mandatory_loop", "detail": ...}`, appended to the digest like every host ending).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_host_game_adjudication.py`:

```python
"""Clocks, caps, stalling, the mandatory-loop draw, and forfeits through real processes (spec 11.4, 11.5)."""

from __future__ import annotations

import sys
from pathlib import Path

from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.messages import Limits, TimeControl, WireDeck

from test_host_game import BURN, OWN, Seat, lands, setup

TESTS = Path(__file__).resolve().parent
TIGHT = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=20,
               max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)


def play(*, deck: str = "Burn", seats=None, engine: str = "fake_v2_engine.py", engine_args=(), clock_ns=None, **changes):
    wire = WireDeck(deck_id=BURN.deck_id, catalog_id=deck)
    process = EngineProcess([sys.executable, str(TESTS / engine), *engine_args], timeout_s=30)
    process.hello()
    seats = seats or {"p0": Seat(lands), "p1": Seat()}
    try:
        kwargs = {} if clock_ns is None else {"clock_ns": clock_ns}
        return play_game(setup(wire_decks=(wire, wire), **changes), engine=process, seats=seats, **kwargs)
    finally:
        process.close()
        for driver in seats.values():
            driver.close()


def hostile(mode: str) -> SubprocessDriver:
    spec = BotSpec(name="hostile", version="1.0.0", type="subprocess", command=(sys.executable, str(TESTS / "bot_v2_hostile.py"), mode))
    return SubprocessDriver(spec, startup_ms=30_000)


def test_a_loop_of_mandatory_actions_is_a_draw_at_the_cap() -> None:
    result = play(deck="Loop", limits=TIGHT)
    assert (result.outcome, result.classification, result.winner, result.reason) == ("draw", "natural", None, "mandatory_loop")
    assert result.adjudication["kind"] == "mandatory_loop" and result.step_count == 39   # p0's 20th answer is the 39th


def test_the_seat_with_more_real_choices_forfeits_for_stalling() -> None:
    last = lambda decision: len(decision["candidates"]) - 1
    result = play(deck="Stall", seats={"p0": Seat(last), "p1": Seat()}, limits=TIGHT)
    assert (result.classification, result.winner, result.reason) == ("forfeit", "p1", "forfeit:stalling")
    assert result.adjudication["loser_seat"] == "p0"
    ended = play(deck="Stall", seats={"p0": Seat(), "p1": Seat()}, limits=TIGHT)
    assert (ended.outcome, ended.reason) == ("draw", "stall_ended")


def test_the_bank_drains_and_a_late_answer_is_a_timeout() -> None:
    now = [0]

    def slow(decision):
        now[0] += 700_000_000          # 700 ms of fake wall time
        return 0

    p0 = Seat(slow)
    result = play(seats={"p0": p0, "p1": Seat()}, clock_ns=lambda: now[0],
                  time_control=TimeControl(startup_ms=1000, game_start_ms=1000, bank_ms=1000, increment_ms=0,
                                           max_decision_ms=800, engine_step_ms=30000))
    assert (result.classification, result.winner, result.reason) == ("forfeit", "p1", "forfeit:timeout")
    clocks = [payload["clock"] for kind, payload in p0.received if kind == "choose"]
    assert clocks == [{"remaining_ms": 1000, "max_decision_ms": 800}, {"remaining_ms": 300, "max_decision_ms": 800}]


def test_the_increment_refills_the_bank() -> None:
    now = [0]

    def slow(decision):
        now[0] += 700_000_000
        return lands(decision)

    result = play(seats={"p0": Seat(slow), "p1": Seat()}, clock_ns=lambda: now[0],
                  time_control=TimeControl(1000, 1000, 1000, 500, 800, 30000))
    assert result.reason == "score"                                  # 1000 - 700 + 500 = 800 left for the second answer


def test_real_processes_time_out_and_bad_answers_forfeit() -> None:
    fast = TimeControl(startup_ms=30000, game_start_ms=500, bank_ms=600000, increment_ms=0, max_decision_ms=300, engine_step_ms=30000)
    for mode, cause in (("hang", "timeout"), ("slow-game-start", "timeout"), ("out-of-range", "invalid_selection"),
                        ("wrong-echo-step", "invalid_selection"), ("garbage", "malformed_response"), ("crash", "transport_error")):
        result = play(seats={"p0": hostile(mode), "p1": Seat()}, time_control=fast)
        assert (result.reason, result.winner) == (f"forfeit:{cause}", "p1"), mode


def test_lenient_answers_and_game_over_failures_never_forfeit() -> None:
    for mode in ("extra-fields", "crlf", "crash-on-game-over"):
        result = play(seats={"p0": hostile(mode), "p1": Seat()})
        assert result.classification == "natural", mode


def test_a_slow_engine_halts_the_game() -> None:
    result = play(engine="hostile_v2_engine.py", engine_args=("hang-on-step",),
                  time_control=TimeControl(30000, 30000, 600000, 0, 60000, 500))
    assert (result.classification, result.reason) == ("halted", "host_engine_fault:timeout")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_host_game_adjudication.py -q -k "bank or increment or real_processes"`
Expected: FAIL: Task 23 budgets every decision with `max_decision_ms` and sends a constant bank, so the second 700 ms answer is accepted and the clock payloads read 1000 twice. (Skip the Loop and Stall tests at this step: without caps they run to the engine's `max_steps` truncation, 100000 answers.)

- [ ] **Step 3: Implement the hooks**

```python
    def _clocks_and_caps(self) -> None:          # called from __init__
        tc, limits = self.setup.time_control, self.setup.limits
        self.clocks = {seat: SeatClock(tc.bank_ms, tc.increment_ms, tc.max_decision_ms) for seat in ("p0", "p1")}
        self.caps = SeatCaps(per_turn=limits.max_seat_decisions_per_turn,
                             groups_per_game=limits.max_seat_decisions_per_game,
                             steps_per_game=limits.max_seat_steps_per_game)
        self.window = StallingWindow()

    def _budget_ms(self, seat: str) -> int:
        return self.clocks[seat].budget_ms()

    def _charge(self, seat: str, sd: Mapping[str, Any], elapsed_ms: int) -> GameResult | None:
        if self.clocks[seat].charge(elapsed_ms):
            return None
        return self._forfeit_for(seat, "timeout", f"the answer to choose at seat step {sd['seat_step']} exceeded the seat's clock")

    def _after_answer(self, seat: str, sd: Mapping[str, Any], candidate_id: int) -> GameResult | None:
        group = sd["group"]
        kind = sd["candidates"][candidate_id]["semantic"]["kind"]
        self.window.record(seat, real_choice=is_real_choice(len(sd["candidates"]), kind))
        cap = self.caps.record(seat, turn=sd["observation"]["turn"],
                               completed_group=group["substep_index"] + 1 == group["substep_count"])
        if cap is None:
            return None
        ruling = self.window.ruling(seat)
        if ruling.kind == "draw":
            return self._draw(f"{seat} reached {cap}; no real choice in the last {STALLING_WINDOW} decisions")
        return self._forfeit_for(ruling.loser_seat, "stalling", f"{seat} reached {cap}; the loser made more real choices in the last {STALLING_WINDOW} decisions")
```

The `choose` payload's `Clock.remaining_ms` reads `self.clocks[seat].remaining_ms` before the decision. Drivers receive `timeout_s=self._budget_ms(seat) / 1000` for `choose` and `game_start_ms / 1000` for `game_start`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_host_game_adjudication.py python/tests/test_host_game.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/host/game.py python/tests/test_host_game_adjudication.py
git commit -m "Host: Fischer clocks, seat caps, stalling forfeits and the mandatory-loop draw"
```

### Task 30: The parallel executor

**Effort:** 0.5 agent-day. **Wave:** 6. **Depends on:** Tasks 5, 12.

**Files:**
- Create: `python/spellbench/arena/executor.py`
- Create: `python/tests/test_arena_executor.py`

**Interfaces:**
- Consumes: `arena.ledger.LedgerRow` (Task 12); `arena.throughput.IdleMonitor` (Task 5).
- Produces (`spellbench.arena.executor`):
  - `@dataclass(frozen=True) class GameOutcome: row: LedgerRow; diagnostics: tuple[str, ...]; violation: dict | None; engine: dict` (`violation` is `{"game_index", "game_id", "rule", "detail"}` when the validator halted the game; `engine` is the identity the game's engine process reported)
  - `@dataclass(frozen=True) class ExecutionResult: outcomes: tuple[GameOutcome, ...]; stopped: str | None; error: BaseException | None; warnings: tuple[str, ...]` (`stopped` is None, `"violation"` or `"aborted"`; `outcomes` is always a contiguous schedule prefix)
  - `execute(contexts: Sequence[C], play_one: Callable[[C], GameOutcome], *, workers: int, stop_on_violation: bool = True, on_outcome: Callable[[GameOutcome], None] | None = None, monitor: IdleMonitor | None = None) -> ExecutionResult`

Semantics (Decision 6): `workers == 1` plays serially; more uses a spawn-context `ProcessPoolExecutor` and consumes futures in schedule order, calling `monitor.tick(running=..., queued=...)` before waiting on each future and again after every 5-second wait, its warnings collected in `warnings`. `on_outcome` sees each outcome in schedule order. The first outcome with a violation ends the prefix there (when `stop_on_violation`): queued games are cancelled, running ones finish, later results are dropped. Any exception, including `KeyboardInterrupt` in the parent or in `on_outcome`, and a worker's exception, returns `stopped="aborted"` with the prefix recorded so far and the exception in `error`; the pool is always shut down with `cancel_futures=True`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_executor.py`:

```python
"""Schedule-order execution: the same prefix whatever the worker count (Decision 6)."""

from __future__ import annotations

import pytest

from spellbench.arena.executor import GameOutcome, execute
from spellbench.arena.ledger import parse_ledger

from test_ledger import VALID, row


def play_one(index: int) -> GameOutcome:
    """Top-level so spawned workers can import it: game 3 breaks a validator rule, game 9 raises."""
    if index == 9:
        raise RuntimeError("the engine binary vanished")
    value = row(game_index=index) if index != 3 else {**VALID["validator halt"], "game_index": 3}
    violation = {"game_index": 3, "game_id": value["game_id"], "rule": "V4", "detail": "stale"} if index == 3 else None
    (parsed,) = parse_ledger([value])
    return GameOutcome(row=parsed, diagnostics=(), violation=violation, engine={"name": "fake"})


@pytest.mark.parametrize("workers", [1, 3])
def test_a_violation_ends_the_prefix_at_that_game(workers: int) -> None:
    result = execute(list(range(8)), play_one, workers=workers)
    assert result.stopped == "violation" and [o.row.game_index for o in result.outcomes] == [0, 1, 2, 3]


@pytest.mark.parametrize("workers", [1, 2])
def test_all_games_in_schedule_order(workers: int) -> None:
    seen = []
    result = execute([0, 1, 2, 4, 5], play_one, workers=workers, on_outcome=lambda outcome: seen.append(outcome.row.game_index))
    assert result.stopped is None and seen == [0, 1, 2, 4, 5]


@pytest.mark.parametrize("workers", [1, 2])
def test_an_error_aborts_with_the_prefix(workers: int) -> None:
    result = execute([0, 1, 9, 2], play_one, workers=workers)
    assert result.stopped == "aborted" and [o.row.game_index for o in result.outcomes] == [0, 1]
    assert "vanished" in str(result.error)


def test_an_interrupt_in_the_parent_aborts_and_keeps_what_was_recorded() -> None:
    def interrupt(outcome):
        if outcome.row.game_index == 1:
            raise KeyboardInterrupt

    result = execute([0, 1, 2], play_one, workers=1, on_outcome=interrupt)
    assert result.stopped == "aborted" and isinstance(result.error, KeyboardInterrupt)
    assert [o.row.game_index for o in result.outcomes] == [0, 1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_executor.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.arena.executor`).

- [ ] **Step 3: Implement `arena/executor.py`**

Port the pool handling of v1 `runner.run_tournament` (spawn context, schedule-order `future.result()`, shutdown with `cancel_futures`), adding the prefix, violation and abort rules above. Record the outcome before calling `on_outcome`, so an interrupt raised inside `on_outcome` keeps that game.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_executor.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/executor.py python/tests/test_arena_executor.py
git commit -m "Arena: schedule-order executor with violation stops and aborts"
```

### Task 31: Manifest v2 and information rules

**Effort:** 0.5 agent-day. **Wave:** 6. **Depends on:** Tasks 2, 5, 9, 12, 16, 19, 22.

**Files:**
- Create: `python/spellbench/arena/manifest.py`
- Create: `python/tests/test_arena_manifest.py`

**Interfaces:**
- Consumes: `arena.config.TournamentConfig` (Task 19); `arena.ledger.LedgerRow` (Task 12); `registry.RegistryEntry`; `messages.Rules`, `EngineProfile`, `EngineIdentity` (Task 9); `host.validator.VALIDATOR_VERSION` (Task 22); `run_secret.RunSecret` (Task 2); `arena.throughput.Allocation`, `bench.pinning.EngineFile` (Task 5); `spellbench.__version__`.
- Produces (`spellbench.arena.manifest`):
  - `TOURNAMENT_SCHEMA_V2 = "spellbench-tournament/v2"`, `COMMITMENT_SCHEMA = "spellbench-run-commitment/v1"`, `FAIRNESS_LABEL = "validator only"`, `RUN_STATUSES = ("complete", "invalid", "aborted")`, `MANIFEST_KEYS = ("schema", "protocol", "tournament", "engine", "engine_profile", "information_rules", "validator", "secrets", "run", "allocation", "engine_files", "games", "leaderboard_status", "files")`
  - `@dataclass(frozen=True) class CommitmentProof: commit: str; timestamp: str` (commit: 40 lowercase hex; timestamp: nonempty third-party reference) with `to_json()`, `from_json(value)`
  - `commitment_record(*, run_secret: RunSecret, benchmark_id: str | None, run_label: str | None) -> dict` (the `COMMITMENT.json` document: `{"schema", "protocol": "spellbench/v2", "benchmark_id", "run_label", "commitment"}`)
  - `information_rules(rules: Rules, profile: EngineProfile, native_id_extensions: Sequence[Mapping[str, str]]) -> dict` (spec 12.2's shape: `rules`, `engine_defaults`, `observation`, `native_id_extensions`, `fairness_label`)
  - `validator_record(rows: Sequence[LedgerRow], violations: Sequence[Mapping[str, Any]]) -> dict` (`{"version", "verdict", "decisions_checked", "violations"}`, verdict `pass` exactly when there are no violations)
  - `is_rated(*, status: str, verdict: str, commitment_proof: CommitmentProof | None, allocation: Allocation) -> bool` (Decision 3)
  - `run_status(*, scheduled: int, rows: int, stopped: str | None, violations: int) -> str`
  - `manifest_body(*, config, entries, anchor_bot_id, engine: EngineIdentity, profile: EngineProfile, protocol_minor: int, info_rules: dict, rows, violations, scheduled: int, leaderboard_status: str, status: str, benchmark_id: str | None, run_label: str | None, run_secret: RunSecret, commitment_proof: CommitmentProof | None, allocation: Allocation, engine_files: Sequence[EngineFile]) -> dict` (every key of `MANIFEST_KEYS` except `files`)

The sections: `protocol` `{"name": "spellbench/v2", "minor": protocol_minor}`; `tournament` (format, stats_seed, pairs_per_matchup, include_self_play, workers, time_control, limits, resources, bootstrap_replicates, `rating_anchor` `{name, bot_id}`, `arena_version`, `bots` as registry entries in config order); `engine` (identity JSON); `engine_profile` (`EngineProfile.to_json()`); `information_rules`; `validator`; `secrets` `{"commitment", "run_secret", "commitment_proof"}` (the secret revealed, spec 11.6); `run` `{"benchmark_id", "label", "status", "rated"}`; `allocation` (`Allocation.to_json()`); `engine_files` (`EngineFile.to_json()` list); `games` `{"scheduled", "total", "natural", "truncated", "halted", "forfeit"}`; `leaderboard_status`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_manifest.py`:

```python
"""Manifest v2: information rules, the validator verdict, the secrets, the rated rule (spec 11.3, 11.6, 12.2)."""

from __future__ import annotations

import hashlib

import pytest

from spellbench.arena.manifest import (
    CommitmentProof, commitment_record, information_rules, is_rated, run_status, validator_record,
)
from spellbench.arena.ledger import parse_ledger
from spellbench.arena.throughput import Allocation, Trial
from spellbench.messages import EngineProfile, Rules
from spellbench.run_secret import RunSecret

from test_host_declarations import PROFILE_JSON, RULES_JSON
from test_ledger import VALID, row

SMALL = Allocation(kind="small", workers=1, host="h", cpu_count=4, per_game_cores=1,
                   probe=Trial(1, 2, 10, "sha256:" + "0" * 64), projected_serial_seconds=1)
PROOF = CommitmentProof(commit="a" * 40, timestamp="https://github.com/o/r/issues/1#issuecomment-1")


def test_information_rules_have_the_spec_12_2_shape() -> None:
    record = information_rules(Rules.from_json(RULES_JSON), EngineProfile.from_json(PROFILE_JSON), [])
    assert set(record) == {"rules", "engine_defaults", "observation", "native_id_extensions", "fairness_label"}
    assert record["rules"] == RULES_JSON and record["fairness_label"] == "validator only"
    assert record["observation"] == PROFILE_JSON["observation"]


def test_the_validator_record() -> None:
    rows = parse_ledger([row(), {**VALID["validator halt"], "game_index": 1}])
    violation = {"game_index": 1, "game_id": rows[1].game_id, "rule": "V4", "detail": "stale reference"}
    assert validator_record(rows[:1], []) == {"version": "spellbench-live-validator/2.0", "verdict": "pass",
                                               "decisions_checked": 4, "violations": []}
    failed = validator_record(rows, [violation])
    assert failed["verdict"] == "fail" and failed["decisions_checked"] == 9 and failed["violations"] == [violation]


@pytest.mark.parametrize(
    ("status", "verdict", "proof", "allocation", "rated"),
    [
        ("complete", "pass", PROOF, SMALL, True),
        ("complete", "pass", None, SMALL, False),                                 # commitment not proven public
        ("complete", "pass", PROOF, Allocation.unmeasured(1, cpu_count=4, host="h"), False),
        ("invalid", "fail", PROOF, SMALL, False),
        ("aborted", "pass", PROOF, SMALL, False),
    ],
)
def test_the_rated_rule(status, verdict, proof, allocation, rated) -> None:
    assert is_rated(status=status, verdict=verdict, commitment_proof=proof, allocation=allocation) is rated


def test_run_status() -> None:
    assert run_status(scheduled=4, rows=4, stopped=None, violations=0) == "complete"
    assert run_status(scheduled=4, rows=2, stopped="violation", violations=1) == "invalid"
    assert run_status(scheduled=4, rows=2, stopped="aborted", violations=0) == "aborted"


def test_the_commitment_record_and_the_proof() -> None:
    secret = RunSecret(bytes(range(32)))
    record = commitment_record(run_secret=secret, benchmark_id="pauper-kernel", run_label="2026-10-01")
    assert record["commitment"] == hashlib.sha256(bytes(range(32))).hexdigest() and "run_secret" not in record
    assert CommitmentProof.from_json(PROOF.to_json()) == PROOF
    with pytest.raises(ValueError):
        CommitmentProof(commit="xyz", timestamp="t")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_manifest.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.arena.manifest`).

- [ ] **Step 3: Implement `arena/manifest.py`**

Pure functions over the inputs above; `manifest_body` assembles the sections in `MANIFEST_KEYS` order (canonical JSON sorts them anyway). `is_rated` is `status == "complete" and verdict == "pass" and commitment_proof is not None and allocation.measured`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_manifest.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/manifest.py python/tests/test_arena_manifest.py
git commit -m "Arena: manifest v2 with information rules, verdict, secrets and the rated rule"
```

### Task 32: The engine conformance runner

**Effort:** 0.5 agent-day. **Wave:** 6. **Depends on:** Tasks 18, 19, 21, 23, 24, 25, 28.

**Files:**
- Create: `python/spellbench/conformance.py`
- Modify: `python/spellbench/arena/cli.py` (the `conformance` subcommand)
- Modify: `python/tests/test_engine_conformance.py` (rewritten as the opt-in wrapper over `check_engine`)
- Create: `python/tests/test_conformance.py`

**Interfaces:**
- Consumes: `host.engine_process` (Task 18), `host.game.play_game` (Task 23; Task 29 lands in the same wave and changes no signature), `arena.config`, `arena.schedule` (`preflight`, `schedule`, `game_setup`), `arena.drivers.BuiltinDriver` (Tasks 19, 25, 24); `run_secret.RunSecret`; `messages`.
- Produces (`spellbench.conformance`), the interface K2 and G run against their adapters:
  - `@dataclass(frozen=True) class CheckResult: name: str; passed: bool; detail: str`
  - `@dataclass(frozen=True) class ConformanceReport: checks: tuple[CheckResult, ...]` with property `passed -> bool` and `render() -> str` (`"PASS <name>"` or `"FAIL <name>: <detail>"` per line)
  - `check_engine(argv: Sequence[str], *, format: str, decks: Sequence[str], games: int = 4) -> ConformanceReport`
  - `replay_engine_transcript(argv: Sequence[str], path: Path) -> list[str]` (sends every `host_to_engine` row of a golden transcript, compares each answer with its `engine_to_host` row as parsed JSON; returns the mismatches)
  - CLI: `spellbench conformance engine --format FORMAT --deck CATALOG_ID [--deck ...] [--games N] -- ARGV...` (exit 0 when every check passes, else 1)

Checks, each in a fresh engine process: `hello` (a strict `hello_ok`, the format offered, every deck in the catalog); `protocol_mismatch`; `malformed_json` (a non-JSON line answered with `request_id` `""`); `malformed_request` (an unknown field); `step_before_reset`; `unsupported_format`; `unsupported_deck` (catalog id `spellbench-conformance-no-such-deck`); `unsupported_request` for `probe_resample` (or `probe_refused` after a reset when the engine declares the probe); `game_already_active`; `game_id_mismatch`; `expected_step_mismatch`; `candidate_id_out_of_range`; `semantic_echo_mismatch`; `retransmission` (the identical request returns the identical parsed answer; a changed payload under the same id is `request_id_reuse_mismatch`); `game_already_terminal` (after a first-candidate game with `max_steps` 2000); and `games`: `games` full games (builtin `first` against `uniform`, seat-swapped, the decks in turn) through `play_game` with a fresh `RunSecret`, each required to end without a host halt or forfeit.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_conformance.py`:

```python
"""The conformance runner engine adapters are held to (the interface K2 and G consume)."""

from __future__ import annotations

import sys
from pathlib import Path

from spellbench.arena import cli
from spellbench.conformance import check_engine

TESTS = Path(__file__).resolve().parent
FAKE = [sys.executable, str(TESTS / "fake_v2_engine.py")]


def test_the_fake_engine_passes_every_check() -> None:
    report = check_engine(FAKE, format="pauper-bo1", decks=["Burn", "Elves"], games=2)
    assert report.passed, report.render()
    names = {check.name for check in report.checks}
    assert {"hello", "protocol_mismatch", "malformed_json", "retransmission", "game_already_terminal", "games"} <= names


def test_a_hostile_engine_fails_the_games_check_with_its_rule() -> None:
    report = check_engine([sys.executable, str(TESTS / "hostile_v2_engine.py"), "stale-reference"], format="pauper-bo1", decks=["Burn"], games=1)
    failed = {check.name: check.detail for check in report.checks if not check.passed}
    assert "games" in failed and "host_validator:V4" in failed["games"]


def test_the_cli(capsys) -> None:
    assert cli.main(["conformance", "engine", "--format", "pauper-bo1", "--deck", "Burn", "--games", "1", "--", *FAKE]) == 0
    assert "PASS games" in capsys.readouterr().out
```

Rewrite `python/tests/test_engine_conformance.py` (keeping `SPELLBENCH_ENGINE_ARGS`, which sub-project C added for engine flags):

```python
"""Opt-in conformance run against a real v2 engine.

Set SPELLBENCH_ENGINE_BIN to the engine executable; SPELLBENCH_ENGINE_ARGS (space-separated) is appended
to its command, and SPELLBENCH_ENGINE_DECKS (comma-separated, default Burn) lists the catalog decks.
"""

from __future__ import annotations

import os

import pytest

from spellbench.conformance import check_engine

ENGINE_BIN = os.environ.get("SPELLBENCH_ENGINE_BIN")
ENGINE_ARGS = os.environ.get("SPELLBENCH_ENGINE_ARGS", "").split()
DECKS = [deck for deck in os.environ.get("SPELLBENCH_ENGINE_DECKS", "Burn").split(",") if deck]

pytestmark = pytest.mark.skipif(not ENGINE_BIN, reason="SPELLBENCH_ENGINE_BIN is not set")


def test_the_engine_is_conformant() -> None:
    report = check_engine([ENGINE_BIN, *ENGINE_ARGS], format="pauper-bo1", decks=DECKS, games=4)
    assert report.passed, report.render()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_conformance.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.conformance`).

- [ ] **Step 3: Implement**

`check_engine` builds each probe with `EngineProcess.send_raw` / `send_line` and records a `CheckResult` per check (an exception inside a check is that check's failure, never the runner's). The `games` check builds a `TournamentConfig` from `argv`, the format, the decks as a pool and the two builtins, runs `preflight`, `schedule` and `game_setup` with a fresh `RunSecret`, plays the first `games` contexts through `play_game` with `BuiltinDriver`s, and fails with the game's `reason` when any game ends `halted` by the host (`host_validator:*` or `host_engine_fault:*`) or in a forfeit. `cli.py` gains `_cmd_conformance` dispatching `conformance engine` and printing `report.render()`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_conformance.py python/tests/test_engine_conformance.py -q`
Expected: PASS (3 passed, 1 skipped).
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/conformance.py python/spellbench/arena/cli.py python/tests/test_conformance.py python/tests/test_engine_conformance.py
git commit -m "Conformance: an engine checker for adapters, with a CLI"
```

## Wave 7

### Task 33: Switch the arena to v2

**Effort:** 0.75 agent-day. **Wave:** 7. **Depends on:** Tasks 5, 11, 12, 19, 20, 23, 24, 25, 28, 29, 30, 31.

**Files:**
- Rewrite: `python/spellbench/arena/runner.py`
- Modify: `python/spellbench/arena/store.py` (v2 schema constants; `COMMITMENT_NAME`; `prepare_tournament_dir(directory, *, allowed=())`; delete the v1 `LedgerSeat`, `Adjudication`, `LedgerRow`, `FORFEIT_CAUSES`, `parse_ledger`, which live on in `ledger.py` and `legacy_v1.py`)
- Modify: `python/spellbench/arena/cli.py` (`run` and `bot` on v2)
- Rewrite: `python/tests/arena_helpers.py`
- Modify: `examples/quickstart.json` (v2 config on `python/tests/fake_v2_engine.py`)
- Delete: `python/tests/fake_arena_engine.py`
- Rewrite: `python/tests/bot_one_land.py`, `python/tests/bot_slow_start.py` (same behavior on `spellbench.bot.serve`, version `1.0.0`, so wave 9's migrated tests find v2 bots)
- Modify (insert `import pytest` and `pytest.skip("protocol v1 test, migrated in Task N", allow_module_level=True)` right after `from __future__ import annotations`, before every other import): `test_arena_adjudication.py` (Task 39); `test_arena_e2e.py`, `test_arena_schedule.py`, `test_arena_slices.py`, `test_arena_parallel.py`, `test_arena_resolve.py`, `test_arena_commands.py`, `test_arena_ratings.py` (Task 40); `test_bench_definition.py` (Task 37); `test_bench_run.py` (Task 41); `test_site_build.py` (Task 42)
- Create: `python/tests/test_arena_tournament.py`

**Interfaces:**
- Consumes: `arena.config` (19), `arena.schedule` (25), `arena.drivers` (24), `arena.executor` (30), `arena.manifest` (31), `arena.ledger` (12), `arena.leaderboard` (20), `host.game` (23, 29), `host.engine_process` (18), `arena.throughput.Allocation`, `bench.pinning.EngineFile` (5), `run_secret` (2), `builtins`, `bot.serve` (11, 6).
- Produces (`spellbench.arena.runner`):
  - `TournamentError`, `TournamentConfig`, `BotSpec` (re-exported from `config`, so `bench` and `site` code fails on v1-shaped input with a `TournamentError` at run time, not an import error, until Tasks 41 and 42 port it)
  - `@dataclass(frozen=True) class TournamentSummary: tournament_dir: Path; games_total: int; games_rated: int; games_truncated: int; games_halted: int; games_forfeit: int; leaderboard_status: str; status: str; rated: bool; manifest: dict`
  - `executed_config(config: TournamentConfig, resolve: Callable[[str], str]) -> TournamentConfig`
  - `registry_entries(config: TournamentConfig, executed: TournamentConfig) -> list[RegistryEntry]`
  - `play_one(config: TournamentConfig, setup: RunSetup, context: GameContext, run_secret_hex: str, entries: dict[str, RegistryEntry]) -> GameOutcome` (top level and picklable: starts the engine with `startup_ms`, pins nothing itself but returns the identity, builds `make_driver` seats, calls `play_game`, closes everything, and builds the ledger row: seats and bot ids, `ResolvedDeck.ledger()` entries, the result fields, `last_selection` from `last_selection_seat`, the digest, `engine` provenance)
  - `play_games(config: TournamentConfig, setup: RunSetup, contexts: Sequence[GameContext], *, run_secret: RunSecret, entries: dict[str, RegistryEntry], workers: int, stop_on_violation: bool = True, on_outcome=None, monitor: IdleMonitor | None = None) -> ExecutionResult`
  - `run_tournament(config: TournamentConfig, *, run_secret: RunSecret, allocation: Allocation, commitment_proof: CommitmentProof | None = None, run_label: str | None = None, benchmark_id: str | None = None, engine_files: Sequence[EngineFile] = (), resolve: Callable[[str], str] | None = None, output_dir: str | Path | None = None, on_game: Callable[[LedgerRow], None] | None = None) -> TournamentSummary`
- Produces (`spellbench.arena.store`): `TOURNAMENT_SCHEMA = "spellbench-tournament/v2"`, `LEDGER_SCHEMA = "spellbench-match-ledger/v2"`, `CONFIG_SCHEMA = "spellbench-tournament-config/v2"`, `LEADERBOARD_SCHEMA = "spellbench-leaderboard/v2"`, `REGISTRY_SCHEMA` unchanged, `COMMITMENT_NAME = "COMMITMENT.json"` (literals, not imports, to avoid an import cycle; a test pins them to the owning modules' constants)
- Produces (`python/tests/arena_helpers.py`), used by every later arena test: `TESTS_DIR`, `FAKE_ENGINE`, `HOSTILE_ENGINE`, `BOT_HOSTILE`, `MINIMAL_BOT`, `TEST_RUN_SECRET`, `TEST_PROOF`, `small_allocation(workers: int = 1) -> Allocation`, `builtin(name, **extra)`, `subprocess_bot(name, command, **extra)`, `cli_bot(name, *args)`, `hostile_bot(mode)`, `make_config(directory, bots, *, engine=FAKE_ENGINE, engine_args=(), decks=("Burn", "Burn"), deck_pool=None, pairs=2, **extra) -> dict`, `run(config: dict, *, rated: bool = False, secret: RunSecret = TEST_RUN_SECRET, **kwargs) -> TournamentSummary`, `ledger_rows(directory)`, `leaderboard(directory)`, `manifest(directory)`, `row_by_name(document, name)`, `matchup_by_names(document, first, second)`

`run_tournament` order (spec 11.1, 11.6; Decisions 3 and 6): resolve the executed config and registry entries (checkpoints hashed); `preflight` (a config error writes nothing); `prepare_tournament_dir(directory, allowed=(COMMITMENT_NAME,))`; write `COMMITMENT.json` from `manifest.commitment_record` unless present, and refuse a present one whose commitment differs; write `config.json`, `registry.json`, an empty `matches.jsonl`; `schedule`; `play_games` with `allocation.workers`, appending each row (and diagnostics) as it arrives and then calling `on_game`; compute the status (`manifest.run_status`), the violations, the leaderboard (`schema=LEADERBOARD_SCHEMA_V2`, `base_seed=config.stats_seed`), and the manifest (`manifest_body` plus `files`: `COMMITMENT.json` first, then `DATA_FILE_NAMES`); publish; finally re-raise an aborting error (a `KeyboardInterrupt` included) after the manifest is written. `cli.py`: `run` loads a v2 config, uses `RunSecret.generate()` and `Allocation.unmeasured(config.workers)` (Task 43 adds the guard), and prints `status: <status> (rated|unrated)` after the games line; `bot NAME [--seed N]` serves `builtins.create_builtin_bot` through `bot.serve` with `BUILTIN_VERSIONS`.

- [ ] **Step 1: Write the failing tests**

Rewrite `python/tests/arena_helpers.py`:

```python
"""Shared helpers for the arena tests (protocol v2): config builders, fixtures and artifact readers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from spellbench.arena import runner
from spellbench.arena.config import TournamentConfig
from spellbench.arena.manifest import CommitmentProof
from spellbench.arena.throughput import Allocation, Trial
from spellbench.run_secret import RunSecret

TESTS_DIR = Path(__file__).resolve().parent
FAKE_ENGINE = TESTS_DIR / "fake_v2_engine.py"
HOSTILE_ENGINE = TESTS_DIR / "hostile_v2_engine.py"
BOT_HOSTILE = TESTS_DIR / "bot_v2_hostile.py"
MINIMAL_BOT = TESTS_DIR.parents[1] / "examples" / "minimal_bot.py"
TEST_RUN_SECRET = RunSecret(bytes(range(32)))
TEST_PROOF = CommitmentProof(commit="0" * 40, timestamp="test fixture")


def small_allocation(workers: int = 1) -> Allocation:
    """A measured "small" allocation for tests (named so pytest never collects it)."""
    return Allocation(kind="small", workers=workers, host="test-host", cpu_count=os.cpu_count() or 1, per_game_cores=1,
                      probe=Trial(workers=1, games=2, seconds_milli=10, outputs_digest="sha256:" + "0" * 64),
                      projected_serial_seconds=1)


def builtin(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "version": "2.0.0", "type": "builtin", **extra}


def subprocess_bot(name: str, command: list[str], **extra: Any) -> dict[str, Any]:
    return {"name": name, "version": "1.0.0", "type": "subprocess", "command": command, **extra}


def cli_bot(name: str, *args: str) -> list[str]:
    return [sys.executable, "-m", "spellbench.arena.cli", "bot", name, *args]


def hostile_bot(mode: str) -> dict[str, Any]:
    return subprocess_bot("hostile", [sys.executable, str(BOT_HOSTILE), mode])


def make_config(directory: Path, bots: list[dict[str, Any]], *, engine: Path = FAKE_ENGINE, engine_args: tuple[str, ...] = (),
                decks: tuple[str, str] = ("Burn", "Burn"), deck_pool: tuple[str, ...] | None = None, pairs: int = 2,
                **extra: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "schema": "spellbench-tournament-config/v2", "tournament_dir": str(directory), "format": "pauper-bo1",
        "decks": [{"catalog_id": decks[0]}, {"catalog_id": decks[1]}],
        "engine": {"command": [sys.executable, str(engine), *engine_args]},
        "bots": bots, "pairs_per_matchup": pairs, "stats_seed": 12345, "bootstrap_replicates": 1000,
    }
    if deck_pool is not None:
        del config["decks"]
        config["deck_pool"] = [{"catalog_id": deck} for deck in deck_pool]
    config.update(extra)
    return config


def run(config: dict[str, Any], *, rated: bool = False, secret: RunSecret = TEST_RUN_SECRET, **kwargs: Any) -> runner.TournamentSummary:
    parsed = TournamentConfig.from_json(config)
    return runner.run_tournament(parsed, run_secret=secret, allocation=small_allocation(parsed.workers),
                                 commitment_proof=TEST_PROOF if rated else None, **kwargs)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ledger_rows(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (directory / "matches.jsonl").read_text(encoding="utf-8").splitlines()]


def leaderboard(directory: Path) -> dict[str, Any]:
    return _json(directory / "leaderboard.json")


def manifest(directory: Path) -> dict[str, Any]:
    return _json(directory / "manifest.json")


def row_by_name(document: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in document["rows"] if row["name"] == name]
    assert len(matches) == 1, f"expected one leaderboard row for {name}"
    return matches[0]


def matchup_by_names(document: dict[str, Any], first: str, second: str) -> dict[str, Any]:
    matches = [m for m in document["matchups"] if {m["a_name"], m["b_name"]} == {first, second}]
    assert len(matches) == 1, f"expected one matchup for {first} vs {second}"
    return matches[0]
```

Create `python/tests/test_arena_tournament.py`:

```python
"""The v2 tournament: commitment first, opaque ids, the manifest, invalid and aborted runs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spellbench.arena import cli, config as config_module, leaderboard, ledger, manifest as manifest_module, runner, store

from arena_helpers import HOSTILE_ENGINE, TEST_RUN_SECRET, builtin, cli_bot, ledger_rows, make_config, manifest, run

BOTS = [builtin("uniform", seed=11), builtin("heuristic"), builtin("first")]
DATA = ("registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md", "COMMITMENT.json")


def test_store_schema_constants_match_their_owners() -> None:
    assert store.TOURNAMENT_SCHEMA == manifest_module.TOURNAMENT_SCHEMA_V2
    assert store.LEDGER_SCHEMA == ledger.LEDGER_SCHEMA and store.CONFIG_SCHEMA == config_module.CONFIG_SCHEMA
    assert store.LEADERBOARD_SCHEMA == leaderboard.LEADERBOARD_SCHEMA_V2


def test_a_complete_run_publishes_every_v2_record(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, BOTS, pairs=1, include_self_play=False))
    document = manifest(directory)
    assert set(document) == set(manifest_module.MANIFEST_KEYS)
    assert document["run"] == {"benchmark_id": None, "label": None, "status": "complete", "rated": False}
    assert document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert document["secrets"]["commitment"] == TEST_RUN_SECRET.commitment() and document["secrets"]["commitment_proof"] is None
    assert document["information_rules"]["fairness_label"] == "validator only"
    assert document["validator"]["verdict"] == "pass" and document["protocol"] == {"name": "spellbench/v2", "minor": 0}
    assert [entry["path"] for entry in document["files"]] == ["COMMITMENT.json", *store.DATA_FILE_NAMES]
    assert json.loads((directory / "COMMITMENT.json").read_text(encoding="utf-8"))["commitment"] == TEST_RUN_SECRET.commitment()
    rows = ledger_rows(directory)
    assert [row["game_id"] for row in rows] == [TEST_RUN_SECRET.game_id(index) for index in range(len(rows))]
    assert summary.status == "complete" and not summary.rated


def test_a_rated_run(tmp_path: Path) -> None:
    summary = run(make_config(tmp_path / "t", BOTS, pairs=1, include_self_play=False), rated=True)
    assert summary.rated and manifest(tmp_path / "t")["run"]["rated"] is True


def test_serial_and_parallel_runs_publish_the_same_data(tmp_path: Path) -> None:
    for name, workers in (("serial", 1), ("parallel", 3)):
        run(make_config(tmp_path / name, BOTS, pairs=2, workers=workers))
    for name in DATA:
        assert (tmp_path / "serial" / name).read_bytes() == (tmp_path / "parallel" / name).read_bytes(), name


def test_a_validator_violation_invalidates_the_run_at_that_game(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("first"), builtin("heuristic")], engine=HOSTILE_ENGINE,
                              engine_args=("stale-reference",), pairs=2))
    rows = ledger_rows(directory)
    assert summary.status == "invalid" and not summary.rated
    assert len(rows) == 1 and rows[0]["reason"] == "host_validator:V4"
    assert manifest(directory)["validator"]["verdict"] == "fail"


def test_an_interrupted_run_is_published_as_aborted_with_its_secret(tmp_path: Path) -> None:
    directory = tmp_path / "t"

    def interrupt(row) -> None:
        if row.game_index == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS, pairs=2), on_game=interrupt)
    document = manifest(directory)
    assert document["run"]["status"] == "aborted" and document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert len(ledger_rows(directory)) == 2


def test_a_config_error_writes_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match="unsupported_deck"):
        run(make_config(directory, BOTS, decks=("Refuse", "Refuse")))
    assert not directory.exists()


def test_the_cli_runs_a_config_and_serves_builtins(tmp_path: Path, capsys) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(make_config(tmp_path / "t", BOTS[:2], pairs=1)), encoding="utf-8")
    assert cli.main(["run", str(path)]) == 0
    assert "status: complete (unrated)" in capsys.readouterr().out
    hello = b'{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}\n'
    served = subprocess.run(cli_bot("uniform"), input=hello, capture_output=True, timeout=60)
    assert b'"name":"uniform"' in served.stdout and b'"version":"2.0.0"' in served.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_tournament.py -q`
Expected: FAIL (the v1 runner's `run_tournament` takes no `run_secret`; the store schemas are v1).

- [ ] **Step 3: Switch**

Rewrite `runner.py` to the Interfaces (module docstring: the v2 schedule, secrets and commitment, the executor's prefix rule, adjudication in `host.game`, no v1 seed schedule). Update `store.py` and `cli.py` as listed. Replace `examples/quickstart.json` with:

```json
{
  "schema": "spellbench-tournament-config/v2",
  "tournament_dir": "out/quickstart",
  "format": "pauper-bo1",
  "decks": [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
  "engine": {"command": ["python", "python/tests/fake_v2_engine.py"]},
  "bots": [
    {"name": "uniform", "version": "2.0.0", "type": "builtin", "seed": 11, "training_style_tags": ["baseline"]},
    {"name": "heuristic", "version": "2.0.0", "type": "builtin", "training_style_tags": ["heuristic"]},
    {"name": "first", "version": "2.0.0", "type": "builtin", "training_style_tags": ["baseline"]}
  ],
  "pairs_per_matchup": 8,
  "stats_seed": 12345,
  "workers": 4
}
```

Delete `fake_arena_engine.py` and add the module-level skips listed under Files. Port the two small bots: `bot_one_land.py` keeps its `OneLand` handler (reading `decision.candidates[i].semantic["kind"]` works unchanged on `bot.Decision`) and ends with `sys.exit(serve(OneLand(), name=BOT_NAME, version=BOT_VERSION))`; `bot_slow_start.py` sleeps `argv[1]` seconds, then serves `choose=lambda decision: decision.candidates[0].candidate_id` as `slow` 1.0.0.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_tournament.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass; the eleven skipped modules report as skipped.

- [ ] **Step 5: Commit**

```bash
git add -A python/spellbench/arena python/tests examples/quickstart.json
git commit -m "Arena: switch tournaments to protocol v2"
```

(`git add -A` on these paths stages the deleted `fake_arena_engine.py` too.)

### Task 34: Golden transcripts and the generator

**Effort:** 0.75 agent-day. **Wave:** 7. **Depends on:** Tasks 6, 17, 18, 21, 23, 24, 26, 27, 28, 29.

**Files:**
- Create: `python/tools/generate_goldens_v2.py`
- Create: `goldens/protocol_v2/*.transcript.jsonl`, `goldens/protocol_v2/index.json` (generated)
- Create: `python/tests/golden_helpers.py`
- Create: `python/tests/test_goldens_v2.py`

**Interfaces:**
- Consumes: `host.game.play_game` (clocks pinned by `clock_ns=lambda: 0`), `host.engine_process`, `host.agent_process` (Tasks 23, 29, 18, 17); `arena.drivers.SubprocessDriver` with `agent_factory` (Task 24); `bot.BotSession` (Task 6); the fake engine, its scenarios and the hostile engine (Tasks 21, 26 to 28); `run_secret` (the spec 16 vector secret, so game 0's id is `g-f67d7fe78c792984` as in the spec examples).
- Produces:
  - `goldens/protocol_v2/<name>.transcript.jsonl`: one canonical line per message, `{"dir": "host_to_engine" | "engine_to_host" | "host_to_agent" | "agent_to_host", "message": {...}}` (spec 16); for the two `malformed_json` transcripts, the offending line is a JSON string in `message`
  - `goldens/protocol_v2/index.json`: `{"schema": "spellbench-goldens/v2", "transcripts": {<file name>: {"engine": "fake_v2_engine.py" | "hostile_v2_engine.py" | null, "engine_args": [...], "game_digest": "sha256:..." | null, "roles": [...]}}}` (Decision 7), where `roles` lists the replays that apply: `"host"` (every game), `"engine"` (every transcript with engine rows), `"bot_server"` (every transcript whose agent answers came from the reference `BotSession`; not `game_forfeit_invalid_selection`, whose p0 is a hand-built bad bot, nor `agent_error_decision_pending`)
  - `python/tools/generate_goldens_v2.py` with `transcripts() -> dict[str, Golden]`, `render(rows) -> bytes`, `main(argv) -> int` (`--check` byte-compares without writing)
  - `python/tests/golden_helpers.py`: `GOLDENS_V2_DIR`, `load_transcript_v2(name: str) -> list[tuple[str, Any]]`, `golden_index() -> dict[str, dict]`, `class RecordingPeer(inner: Peer, rows: list, out_dir: str, in_dir: str)`, `class InProcessBot(session: BotSession)` (a `Peer` that answers through `handle_line`)

Transcripts. Games (all four directions, a digest each): `game_scoring` (Burn, p0 plays lands), `game_kinds_tour`, `game_board_tour` (`--all-flags`), `game_knowledge_tour`, `game_forfeit_invalid_selection` (p0's bot answers 9), `game_halt_host_validator_v4` (hostile `stale-reference`), `game_mandatory_loop` (Loop, per-turn cap 3), `game_stalling_forfeit` (Stall, p0 activates, per-turn cap 3); together they cover every message type, every v2.0 kind, every group shape (a full arrangement and a rewind included). Engine errors (engine rows only, digest null): `engine_error_<code>` for each of the 17 codes of spec 9.8 (`probe_refused` from `--probe`) and `engine_validate_deck` (`deck_ok` and `unsupported_deck`). Agent errors (agent rows only): `agent_error_<code>` for each of the 7 codes of spec 10.5, generated through `BotSession` except `decision_pending`, which the reference server cannot produce and whose agent row is written by hand.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/golden_helpers.py` (the `RecordingPeer` records the parsed message on each write and read, in order):

```python
"""Golden transcript helpers (protocol v2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spellbench import wire
from spellbench.bot import BotSession

GOLDENS_V2_DIR = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2"


def _parse(line: bytes) -> Any:
    try:
        return wire.strict_json_loads(line)
    except Exception:
        return line.decode("utf-8", errors="replace")      # a malformed_json probe is kept as text


def load_transcript_v2(name: str) -> list[tuple[str, Any]]:
    rows = [wire.strict_json_loads(line) for line in (GOLDENS_V2_DIR / name).read_bytes().splitlines()]
    return [(row["dir"], row["message"]) for row in rows]


def golden_index() -> dict[str, dict]:
    return json.loads((GOLDENS_V2_DIR / "index.json").read_bytes())["transcripts"]


class RecordingPeer:
    def __init__(self, inner, rows: list, out_dir: str, in_dir: str) -> None:
        self.inner, self.rows, self.out_dir, self.in_dir = inner, rows, out_dir, in_dir

    def write_line(self, payload: bytes) -> None:
        self.rows.append((self.out_dir, _parse(payload)))
        self.inner.write_line(payload)

    def read_line(self) -> bytes:
        line = self.inner.read_line()
        self.rows.append((self.in_dir, _parse(line)))
        return line

    def set_timeout(self, seconds) -> None:
        setter = getattr(self.inner, "set_timeout", None)
        if setter is not None:
            setter(seconds)

    def close(self) -> None:
        self.inner.close()


class InProcessBot:
    """A Peer served by a BotSession, so agent transcripts need no subprocess."""

    def __init__(self, session: BotSession) -> None:
        self.session, self.pending = session, []

    def write_line(self, payload: bytes) -> None:
        self.pending.append(self.session.handle_line(payload))

    def read_line(self) -> bytes:
        return wire.strip_line_terminator(self.pending.pop(0))

    def close(self) -> None:
        pass
```

Create `python/tests/test_goldens_v2.py`:

```python
"""The v2 goldens: current, canonical, valid, and complete (spec 16)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from spellbench import wire
from spellbench.agent_messages import AGENT_ERROR_CODES
from spellbench.candidates import V2_KINDS
from spellbench.messages import ENGINE_ERROR_CODES

from golden_helpers import GOLDENS_V2_DIR, golden_index, load_transcript_v2

TOOL = Path(__file__).resolve().parents[1] / "tools" / "generate_goldens_v2.py"


def test_the_generator_check_passes() -> None:
    result = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, timeout=600)
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()


def test_files_are_canonical_lines_and_indexed() -> None:
    names = sorted(path.name for path in GOLDENS_V2_DIR.glob("*.transcript.jsonl"))
    assert names == sorted(golden_index())
    for name in names:
        raw = (GOLDENS_V2_DIR / name).read_bytes()
        assert raw == b"".join(wire.canonical_json_line(wire.strict_json_loads(line)) for line in raw.splitlines())


def test_every_game_has_a_digest_and_the_goldens_cover_the_protocol() -> None:
    kinds, engine_codes, agent_codes = set(), set(), set()
    for name, entry in golden_index().items():
        rows = load_transcript_v2(name)
        if name.startswith("game_"):
            assert entry["game_digest"].startswith("sha256:"), name
        for direction, message in rows:
            if not isinstance(message, dict):
                continue
            if direction == "host_to_agent" and message.get("request_type") == "choose":
                kinds |= {c["semantic"]["kind"] for c in message["decision"]["candidates"]}
            if message.get("response_type") == "error":
                (engine_codes if direction == "engine_to_host" else agent_codes).add(message["error"]["code"])
    assert kinds == V2_KINDS
    assert engine_codes == ENGINE_ERROR_CODES and agent_codes == AGENT_ERROR_CODES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_goldens_v2.py -q`
Expected: FAIL (no generator, no goldens).

- [ ] **Step 3: Write the generator and generate**

Each game golden runs `play_game` with `EngineProcess(peer=RecordingPeer(wire.SubprocessPeer([python, fake_v2_engine.py or hostile_v2_engine.py, *args]), rows, "host_to_engine", "engine_to_host"))` and, per seat, `SubprocessDriver(spec, startup_ms=30000, agent_factory=lambda: AgentProcess(peer=RecordingPeer(InProcessBot(BotSession(choose=script, name=..., version=...)), rows, "host_to_agent", "agent_to_host")))`, with `clock_ns=lambda: 0` so every `clock` payload is deterministic, game index 0 of the spec 16 secret, and the game's rules fitted to the engine (as `tour_helpers.play_tour` does). Engine error goldens send crafted requests through a recording `EngineProcess` (`send_raw`, `send_line`); agent error goldens send crafted lines to a recording `InProcessBot`. `main` writes each golden with `render` and `index.json` as one canonical line; `--check` prints `OK`, `STALE` or `MISSING` per file and exits 1 on any difference. Keep the generator deterministic: sorted names, fixed arguments, no wall clock. Run it: `uv run python python/tools/generate_goldens_v2.py`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_goldens_v2.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/tools/generate_goldens_v2.py goldens/protocol_v2 python/tests/golden_helpers.py python/tests/test_goldens_v2.py
git commit -m "Goldens: protocol v2 transcripts with digests, and their generator"
```

## Wave 8

### Task 35: Golden replay in both roles

**Effort:** 0.5 agent-day. **Wave:** 8. **Depends on:** Tasks 32, 34.

**Files:**
- Create: `python/tests/test_golden_replay_v2.py`

**Interfaces:**
- Consumes: `golden_helpers` (Task 34); `host.game.play_game`, `GameSetup` (Tasks 23, 29); `host.engine_process`, `host.agent_process` (Tasks 18, 17); `arena.drivers.SubprocessDriver` (Task 24); `bot.BotSession` (Task 6); `conformance.replay_engine_transcript` (Task 32); `messages`, `agent_messages.OwnDeck`.
- Produces: tests only. Three replays (spec 16): the host reproduces every host row byte for byte and the recorded digest, from recorded engine and agent answers; the reference bot server reproduces every agent answer byte for byte; the fake engine reproduces every engine answer by value.

- [ ] **Step 1: Write the tests**

Create `python/tests/test_golden_replay_v2.py`:

```python
"""Replay the v2 goldens in both roles (spec 16)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.bot import BotSession
from spellbench.conformance import replay_engine_transcript
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.messages import Limits, ResetRequest, Resources, TimeControl

from conftest import ScriptedPeer
from golden_helpers import GOLDENS_V2_DIR, golden_index, load_transcript_v2

TESTS = Path(__file__).resolve().parent
INDEX = golden_index()


def exchanges_by_seat(rows) -> dict[str, list[tuple[dict, dict]]]:
    """(request, answer) per seat: hellos and game_overs go p0 then p1, game_start names its seat, choose its acting seat."""
    pairs: dict[str, list] = {"p0": [], "p1": []}
    hellos = overs = 0
    pending = None
    for direction, message in rows:
        if direction == "host_to_agent":
            kind = message["request_type"]
            if kind == "hello":
                seat, hellos = ("p0", "p1")[hellos], hellos + 1
            elif kind == "game_start":
                seat = message["seat"]
            elif kind == "choose":
                seat = message["decision"]["acting_seat"]
            else:
                seat, overs = ("p0", "p1")[overs], overs + 1
            pending = (seat, message)
        elif direction == "agent_to_host":
            seat, request = pending
            pairs[seat].append((request, message))
    return pairs


def setup_from(rows) -> GameSetup:
    reset = ResetRequest.from_json(next(m for d, m in rows if d == "host_to_engine" and m["request_type"] == "reset"))
    starts = {m["seat"]: m for d, m in rows if d == "host_to_agent" and m["request_type"] == "game_start"}
    first = starts["p0"]
    return GameSetup(game_index=0, game_id=reset.game_id, game_secret_hex=reset.game_secret, format=reset.format,
                     wire_decks=reset.seats, own_decks=(OwnDeck.from_json(starts["p0"]["own_deck"]), OwnDeck.from_json(starts["p1"]["own_deck"])),
                     rules=reset.rules, time_control=TimeControl.from_json(first["time_control"]),
                     limits=Limits.from_json(first["limits"]), resources=Resources.from_json(first["resources"]),
                     agent_seeds=(starts["p0"]["agent_seed"], starts["p1"]["agent_seed"]))


@pytest.mark.parametrize("name", sorted(n for n, entry in INDEX.items() if "host" in entry["roles"]))
def test_the_host_replays_every_game_byte_for_byte(name: str) -> None:
    rows = load_transcript_v2(name)
    engine_peer = ScriptedPeer([wire.canonical_json_dumps(m) for d, m in rows if d == "engine_to_host"])
    engine = EngineProcess(peer=engine_peer)
    engine.hello()
    pairs = exchanges_by_seat(rows)
    peers = {seat: ScriptedPeer([wire.canonical_json_dumps(answer) for _, answer in seat_pairs]) for seat, seat_pairs in pairs.items()}
    seats = {}
    for seat, seat_pairs in pairs.items():
        bot = next(answer["bot"] for request, answer in seat_pairs if request["request_type"] == "hello")
        spec = BotSpec(name=bot["name"], version=bot["version"], type="subprocess", command=("recorded",))
        seats[seat] = SubprocessDriver(spec, startup_ms=30_000, agent_factory=lambda seat=seat: AgentProcess(peer=peers[seat]))
    result = play_game(setup_from(rows), engine=engine, seats=seats, clock_ns=lambda: 0)
    assert engine_peer.sent == [wire.canonical_json_dumps(m) for d, m in rows if d == "host_to_engine"]
    for seat, seat_pairs in pairs.items():
        assert peers[seat].sent == [wire.canonical_json_dumps(request) for request, _ in seat_pairs], seat
    assert result.game_digest == INDEX[name]["game_digest"]


def _sessions(name: str, rows) -> list[list[tuple]]:
    if name.startswith("agent_error_"):
        requests = [m for d, m in rows if d == "host_to_agent"]
        answers = [m for d, m in rows if d == "agent_to_host"]
        return [list(zip(requests, answers))]
    return list(exchanges_by_seat(rows).values())


@pytest.mark.parametrize("name", sorted(n for n, entry in INDEX.items() if "bot_server" in entry["roles"]))
def test_the_bot_server_replays_every_answer_byte_for_byte(name: str) -> None:
    for pairs in _sessions(name, load_transcript_v2(name)):
        hello = next((a for r, a in pairs if isinstance(r, dict) and r.get("request_type") == "hello"), None) or {}
        picks = iter([a["selection"]["candidate_id"] if a["response_type"] == "choice" else 99
                      for r, a in pairs if isinstance(r, dict) and r.get("request_type") == "choose"])
        requires = hello.get("requires", {})
        session = BotSession(choose=lambda decision: next(picks), name=hello.get("bot", {}).get("name", "golden"),
                             version=hello.get("bot", {}).get("version", "1.0.0"),
                             requires_observation=tuple(requires.get("observation", ())),
                             requires_extensions=tuple(requires.get("extensions", ())),
                             extensions_accepted=tuple(hello.get("extensions_accepted", ())))
        for request, answer in pairs:
            line = request.encode("utf-8") if isinstance(request, str) else wire.canonical_json_dumps(request)
            assert session.handle_line(line) == wire.canonical_json_line(answer)


@pytest.mark.parametrize("name", sorted(n for n, entry in INDEX.items() if "engine" in entry["roles"]))
def test_the_fake_engine_replays_every_engine_answer(name: str) -> None:
    entry = INDEX[name]
    argv = [sys.executable, str(TESTS / entry["engine"]), *entry["engine_args"]]
    assert replay_engine_transcript(argv, GOLDENS_V2_DIR / name) == []
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest python/tests/test_golden_replay_v2.py -q`
Expected: PASS. A failure here is a real divergence between the goldens and the stack: fix the code (or, when the golden is wrong, the generator and a regenerated golden in the same commit, with the reason in the commit message); never edit a transcript by hand.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add python/tests/test_golden_replay_v2.py
git commit -m "Goldens: replay v2 transcripts as host, bot server and engine"
```

### Task 36: Validate v2 runs

**Effort:** 0.5 agent-day. **Wave:** 8. **Depends on:** Tasks 4, 31, 33.

**Files:**
- Modify: `python/spellbench/arena/validate.py`
- Create: `python/tests/test_validate_v2.py`

**Interfaces:**
- Consumes: `store` (Task 33 schemas and IO), `arena.config`, `arena.ledger`, `arena.schedule.schedule`, `arena.manifest` (`MANIFEST_KEYS`, `manifest_body`, `validator_record`, `is_rated`, `run_status`, `CommitmentProof`, `FAIRNESS_LABEL`), `arena.leaderboard` (v2), `arena.throughput.Allocation.from_json`, `registry`, `legacy_v1` (Task 4), `digests`, `run_secret.RunSecret`, `spellbench.__version__`.
- Produces (`spellbench.arena.validate`): `validate_tournament_dir(directory: Path) -> list[str]` (a v2 manifest goes to `validate_v2_run`, anything else to the legacy verifier) and `validate_v2_run(directory: Path) -> list[str]`.

The v2 checks, in order, each failure a line: manifest keys exactly `MANIFEST_KEYS`; `tournament.arena_version` equals `spellbench.__version__` (else the single v1-style message, and nothing more); `files` lists `COMMITMENT.json` then `store.DATA_FILE_NAMES`, digests match; config, registry and ledger parse (v2); `secrets`: the revealed `run_secret` hashes to `commitment`, `COMMITMENT.json` holds the same commitment, `commitment_proof` parses or is null; the ledger is a prefix of `schedule(config, run_secret)` (a complete run: all of it) with `game_index` from 0, `game_id == run_secret.game_id(game_index)`, matchup, pair, slot, seats (bot ids, names, versions) and decks as scheduled (a decklist deck's `deck_id` recomputed; games with one catalog id share one `deck_id`); `validator` equals `validator_record(rows, violations)`, each violation names a row whose reason is `host_validator:<rule>` and every such row is a violation; `run.status` equals the status the rows imply (complete, invalid when there is a violation, else aborted for a short ledger) and `run.rated` equals `is_rated(...)` with the recorded `Allocation`; `information_rules`: `fairness_label` is `validator only`, the domain id matches its names, `observation` and `engine_defaults` equal `engine_profile`'s, every native-id extension is enabled and audited; every row's `engine` equals the manifest engine's provenance; `leaderboard.json` and `LEADERBOARD.md` recompute byte for byte (`schema=LEADERBOARD_SCHEMA_V2`, `base_seed=config.stats_seed`); `manifest_body(...)` rebuilt from the files and the recorded engine, profile, information rules, secrets, allocation and engine files equals the manifest on every key but `files`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_validate_v2.py`:

```python
"""Validate v2 runs from their files alone, including invalid and aborted runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import spellbench
from spellbench.arena import store
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import HOSTILE_ENGINE, builtin, ledger_rows, make_config, manifest, run

BOTS = [builtin("uniform", seed=11), builtin("heuristic")]


def _run(tmp_path: Path, **kwargs) -> Path:
    directory = tmp_path / "t"
    run(make_config(directory, BOTS, pairs=2, include_self_play=False), **kwargs)
    return directory


def _rewrite(directory: Path, *, rows=None, edit=None) -> None:
    """Tamper with the run, then refresh the file digests so only the tampering can fail."""
    if rows is not None:
        (directory / "matches.jsonl").write_bytes(b"".join(store.canonical_bytes(row) + b"\n" for row in rows))
    document = manifest(directory)
    if edit is not None:
        edit(document)
    names = [entry["path"] for entry in document["files"]]
    document["files"] = [store.file_entry(directory / name, name) for name in names]
    store.write_json_atomic(directory / "manifest.json", document)


def _flip_first(rows: list[dict]) -> list[dict]:
    """Change game 0's result to another valid natural result."""
    first = rows[0]
    if first["outcome"] == "draw":
        flipped = {**first, "outcome": "p0_win", "winner": "p0", "winner_bot_id": first["seats"][0]["bot_id"]}
    else:
        flipped = {**first, "outcome": "draw", "winner": None, "winner_bot_id": None}
    return [flipped, *rows[1:]]


def test_complete_and_rated_runs_validate(tmp_path: Path) -> None:
    assert validate_tournament_dir(_run(tmp_path)) == []
    rated = tmp_path / "rated"
    run(make_config(rated, BOTS, pairs=2, include_self_play=False), rated=True)
    assert validate_tournament_dir(rated) == []


def test_an_invalid_run_validates_as_invalid(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("first"), builtin("heuristic")], engine=HOSTILE_ENGINE,
                    engine_args=("stale-reference",), pairs=2))
    assert validate_tournament_dir(directory) == []


def test_an_aborted_run_validates_as_aborted(tmp_path: Path) -> None:
    def stop(row) -> None:
        if row.game_index == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, on_game=stop)
    assert validate_tournament_dir(tmp_path / "t") == []


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        (lambda d: _rewrite(d, rows=_flip_first(ledger_rows(d))), "leaderboard.json"),
        (lambda d: _rewrite(d, rows=[{**r, "game_id": "g-0000000000000000"} if r["game_index"] == 0 else r for r in ledger_rows(d)]), "schedule"),
        (lambda d: _rewrite(d, edit=lambda m: m["secrets"].update(run_secret="11" * 32)), "commitment"),
        (lambda d: _rewrite(d, edit=lambda m: m["run"].update(rated=True)), "rated"),
        (lambda d: _rewrite(d, edit=lambda m: m["validator"].update(decisions_checked=1)), "validator"),
        (lambda d: _rewrite(d, edit=lambda m: m["information_rules"].update(fairness_label="validator and probe")), "fairness"),
        (lambda d: _rewrite(d, edit=lambda m: m["games"].update(natural=0)), "games"),
        (lambda d: (d / "LEADERBOARD.md").write_text("x", encoding="utf-8"), "digest mismatch: LEADERBOARD.md"),
    ],
)
def test_tampering_is_caught(tmp_path: Path, tamper, expected: str) -> None:
    directory = _run(tmp_path)
    tamper(directory)
    failures = validate_tournament_dir(directory)
    assert any(expected in failure for failure in failures), failures


def test_another_arena_version_gets_one_message(tmp_path: Path) -> None:
    directory = _run(tmp_path)
    _rewrite(directory, edit=lambda m: m["tournament"].update(arena_version="0.9.0"))
    assert validate_tournament_dir(directory) == [
        f"this run was made by spellbench arena 0.9.0; this is {spellbench.__version__}: rerun the benchmark, or validate with arena 0.9.0"
    ]


def test_an_unknown_schema_goes_to_the_legacy_path_and_fails_there(tmp_path: Path) -> None:
    directory = _run(tmp_path)
    _rewrite(directory, edit=lambda m: m.update(schema="spellbench-tournament/v9"))
    assert any("spellbench-tournament/v1" in failure for failure in validate_tournament_dir(directory))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_validate_v2.py -q`
Expected: FAIL: every v2 run is sent to the legacy verifier, which reports the schema.

- [ ] **Step 3: Implement**

Add `validate_v2_run` with the checks above (the order matters only for the version gate, which returns early); keep each failure message short and naming its check (the words the tests match: "schedule", "commitment", "rated", "validator", "fairness", "games", "leaderboard.json", "digest mismatch"). Dispatch in `validate_tournament_dir` on the manifest's `schema`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_validate_v2.py python/tests/test_legacy_v1.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/validate.py python/tests/test_validate_v2.py
git commit -m "Validate: v2 runs, including invalid and aborted ones"
```

### Task 37: Benchmark definition v2 and the pauper-kernel migration

**Effort:** 0.5 agent-day. **Wave:** 8. **Depends on:** Tasks 19, 33.

**Files:**
- Modify: `python/spellbench/bench/definition.py`
- Modify: `benchmarks/pauper-kernel/benchmark.json`
- Modify: `python/tests/test_bench_definition.py` (remove the skip; port to v2)

**Interfaces:**
- Consumes: `arena.config` (`DeckSpec`, `DEFAULT_*`, `TournamentConfig`) (Task 19), `messages.TimeControl`, `Limits`, `Resources`.
- Produces (`spellbench.bench.definition`):
  - `BENCHMARK_SCHEMA = "spellbench-benchmark/v2"`; `Benchmark` fields: `id`, `title`, `summary`, `format`, `engine_name`, `engine_command`, `deck_pool: tuple[DeckSpec, ...]`, `pairs_per_deck`, `stats_seed`, `extensions: tuple[str, ...]`, `native_id_audits: dict[str, str]`, `time_control`, `limits`, `resources`, `bootstrap_replicates`, `workers` (the most workers the throughput guard may choose), `bots`
  - `Benchmark.tournament_config(tournament_dir: str) -> dict` (a v2 config: the pool, `include_self_play: false`, `rating_anchor: "uniform"`, and the fixed rules `{"opponent_decklist": "visible", "mulligan": "auto", "starting_player": "host_assigned", "starting_seat": "p0"}`, Decision 8)
  - every other public name of the module unchanged (`parse_benchmark`, `load_benchmark`, `find_benchmarks`, `load_proposed`, placeholder helpers, run-name helpers)

Schema: required `schema`, `id`, `title`, `summary`, `format`, `engine` (`{name, command}`), `deck_pool` (catalog-id strings, or `{"name", "decklist"}` objects), `pairs_per_deck`, `stats_seed`, `bots`; optional `pairing` (only `"rotating_pool"`; `"fixed_deck"` fails with "fixed-deck benchmarks are reserved in protocol v2.0 (spec 15)"), `extensions`, `native_id_audits`, `time_control`, `limits`, `resources`, `bootstrap_replicates`, `workers`. A v1 schema or v1 field fails with a hint (`base_seed`: use `stats_seed`; `choose_timeout_ms`, `startup_timeout_ms`, `engine.timeout_ms`: use `time_control`).

`benchmarks/pauper-kernel/benchmark.json` becomes (the committed v1 run is untouched):

```json
{
  "schema": "spellbench-benchmark/v2",
  "id": "pauper-kernel",
  "title": "Pauper · mtg-kernel",
  "summary": "Eight Pauper decks on the mtg-kernel rules engine; every matchup plays each deck in both seats.",
  "format": "pauper-bo1",
  "engine": {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}"]},
  "deck_pool": ["Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries"],
  "pairs_per_deck": 4,
  "stats_seed": 20260926,
  "time_control": {"startup_ms": 120000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
                   "max_decision_ms": 30000, "engine_step_ms": 120000},
  "bootstrap_replicates": 2000,
  "workers": 8,
  "bots": [
    {
      "name": "uniform", "version": "2.0.0", "type": "builtin", "seed": 11, "owner": "spellbench",
      "training_style_tags": ["baseline"],
      "display": {"label": "random", "author": "Spellbench", "description": "Picks uniformly at random among the offered actions. The anchor: its Elo is fixed at 1000.", "url": null}
    },
    {
      "name": "heuristic", "version": "2.0.0", "type": "builtin", "owner": "spellbench",
      "training_style_tags": ["heuristic"],
      "display": {"label": "heuristic", "author": "Spellbench", "description": "Fixed priorities: play a land, cast a spell, activate an ability; attacks with everything and never blocks.", "url": null}
    },
    {
      "name": "first", "version": "2.0.0", "type": "builtin", "owner": "spellbench",
      "training_style_tags": ["baseline"],
      "display": {"label": "first", "author": "Spellbench", "description": "Always takes the first offered action.", "url": null}
    }
  ]
}
```

If sub-project C has merged by then, its kernel bots, its engine flag and its `workers` value carry over unchanged (they stay unrunnable until K2 ports the bridge and the bot; K2 also sets `extensions` and `native_id_audits`).

- [ ] **Step 1: Port the tests**

In `python/tests/test_bench_definition.py`: delete the skip; convert every fixture to v2 (`"schema": "spellbench-benchmark/v2"`, `stats_seed`, builtin versions `2.0.0`, `time_control` in place of the timeouts, no `engine.timeout_ms`) and keep every existing test's intent; then add:

```python
def test_fixed_deck_benchmarks_are_reserved(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="reserved in protocol v2.0"):
        definition.parse_benchmark(_value(pairing="fixed_deck"))


@pytest.mark.parametrize(("field", "hint"), [("base_seed", "stats_seed"), ("choose_timeout_ms", "time_control")])
def test_v1_fields_name_their_replacement(field: str, hint: str) -> None:
    with pytest.raises(BenchmarkError, match=hint):
        definition.parse_benchmark(_value(**{field: 1}))


def test_the_pool_may_hold_decklists_and_the_rules_are_fixed() -> None:
    value = _value(deck_pool=["Burn", {"name": "Mono Red", "decklist": [{"name": "Mountain", "count": 20}]}])
    config = definition.parse_benchmark(value).tournament_config("runs/x")
    assert config["deck_pool"][1] == {"name": "Mono Red", "decklist": [{"name": "Mountain", "count": 20}]}
    assert config["rules"] == {"opponent_decklist": "visible", "mulligan": "auto", "starting_player": "host_assigned", "starting_seat": "p0"}
    TournamentConfig.from_json(config)


def test_the_committed_pauper_kernel_definition_is_v2() -> None:
    benchmark = definition.load_benchmark(REPO / "benchmarks" / "pauper-kernel")
    assert benchmark.stats_seed == 20260926 and {bot.entry["version"] for bot in benchmark.bots if bot.entry["type"] == "builtin"} == {"2.0.0"}
    TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
```

(`_value(**changes)` is the module's fixture builder, now writing v2 definitions; add `REPO = Path(__file__).resolve().parents[2]` and `from spellbench.arena.config import TournamentConfig` at the top.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_bench_definition.py -q`
Expected: FAIL (the v1 schema is still required).

- [ ] **Step 3: Implement and migrate**

Update `definition.py` to the schema above (reuse `DeckSpec.from_json` for pool objects, wrapping errors as `BenchmarkError` with the field path), and rewrite `benchmarks/pauper-kernel/benchmark.json`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_bench_definition.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/bench/definition.py benchmarks/pauper-kernel/benchmark.json python/tests/test_bench_definition.py
git commit -m "Benchmarks: definition schema v2; pauper-kernel migrated"
```

### Task 38: Site render: protocol, fairness and attribution

**Effort:** 0.5 agent-day. **Wave:** 8. **Depends on:** nothing.

**Files:**
- Modify: `python/spellbench/site/render.py`
- Modify: `python/tests/test_site_render.py`

**Interfaces:**
- Consumes: view-model dicts only (the renderer stays pure).
- Produces: the view contract below, which Task 42 builds.

View-model additions to `BenchmarkPageView`:

```text
"protocol": {"name": str, "minor": int | None},       # {"name": "spellbench/v1", "minor": None} for a legacy run
"legacy": bool,
"fairness": {"label": str, "verdict": str, "decisions_checked": int, "violations": int} | None,   # None for a legacy run
"setup_rules": [{"term": str, "value": str}, ...],    # information rules and engine facts, in display order; [] for a legacy run
"attribution": [{"name": str, "label": str, "games": int, "halts": int, "truncations": int}, ...],  # [] for a legacy run
"newer_runs": [{"name": str, "status": str, "rated": bool}, ...],
# and in "run": "status": str, "rated": bool, "commitment": str | None, "run_secret": str | None
```

Markup contract: the meta line gains `protocol v2` (or `protocol v1`); after the run box, a `<section class="fairness">` reading "Fairness: validator only. The host checked every decision before a bot saw it ({N} decisions, verdict {verdict}). It cannot see hidden state, so an engine adapter that leaked through its text or extensions would go unnoticed." with a link to `repo_url + "/blob/main/spec/SPELLBENCH_PROTOCOL_V2.md#13-fairness-contract"`; for a legacy run, a `<p class="legacy">` instead: "Protocol v1: this run predates the fairness contract, and the two games of each pair shared one seed. It stays on the board until the benchmark reruns on protocol v2."; when `newer_runs` is not empty, a note "Newer runs not shown: <name> (<status>), ..."; the Setup list gains `Protocol` and every `setup_rules` row; when `attribution` is not empty, a table `<table class="attribution">` headed "Halts and truncations after each bot's move" with a row per bot (`label`, games, halts, truncations); the Re-check box adds "Commitment" and "Run secret (revealed after the run)" with the hex values when present. Method page, Games section: "Each benchmark is a round robin. Every matchup is played as pairs of games with the seats swapped, each pair using the next deck of the benchmark's pool in both seats; a bot never plays itself. Every game has its own secret, so the two games of a pair shuffle independently, and ratings still count them as a pair. The run publishes a commitment to its secret before the first game and reveals the secret afterwards, so anyone can recompute every game's randomness." A new Method section "Fairness": "Engines never show a bot the other player's hand or either library, beyond what the rules let it know. The host checks every decision before forwarding it and publishes the verdict with the run. Timing is not hidden: a bot can measure how long its opponent takes." Join page: the spec link points to `SPELLBENCH_PROTOCOL_V2.md`, and the steps add "The smallest bot is about 15 lines: examples/minimal_bot.py." (linked to `repo_url + "/blob/main/examples/minimal_bot.py"`).

- [ ] **Step 1: Write the failing tests**

Add to `python/tests/test_site_render.py` (building on its existing `BENCH` fixture, which the module updates with the new keys for a v2 run):

```python
V2_EXTRA = {
    "protocol": {"name": "spellbench/v2", "minor": 0}, "legacy": False,
    "fairness": {"label": "validator only", "verdict": "pass", "decisions_checked": 18123, "violations": 0},
    "setup_rules": [{"term": "Opponent decklist", "value": "visible"}, {"term": "Mulligan", "value": "none (the engine offers no mulligans)"}],
    "attribution": [{"name": "heuristic", "label": "heuristic", "games": 64, "halts": 1, "truncations": 0}],
    "newer_runs": [{"name": "2026-10-02", "status": "invalid", "rated": False}],
}


def _v2_page(**changes) -> str:
    view = copy.deepcopy(BENCH)
    view.update(copy.deepcopy(V2_EXTRA))
    view["run"].update(status="complete", rated=True, commitment="ab" * 32, run_secret="cd" * 32)
    view.update(changes)
    return render.render_benchmark(view)


def test_a_v2_page_shows_protocol_fairness_rules_and_attribution() -> None:
    page = _v2_page()
    assert "protocol v2" in page and 'class="fairness"' in page and "18123 decisions" in page
    assert "SPELLBENCH_PROTOCOL_V2.md#13-fairness-contract" in page
    assert "Mulligan" in page and 'class="attribution"' in page and "Newer runs not shown: 2026-10-02 (invalid)" in page
    assert "ab" * 32 in page and "cd" * 32 in page


def test_a_legacy_page_says_so_and_shows_no_fairness_box() -> None:
    page = _v2_page(protocol={"name": "spellbench/v1", "minor": None}, legacy=True, fairness=None, setup_rules=[], attribution=[])
    assert 'class="legacy"' in page and "predates the fairness contract" in page and 'class="fairness"' not in page


def test_setup_rule_values_are_escaped() -> None:
    assert "&lt;script&gt;" in _v2_page(setup_rules=[{"term": "x", "value": "<script>"}])


def test_method_and_join_describe_v2() -> None:
    method = render.render_method(INFO)
    assert "own secret" in method and "Fairness" in method
    join = render.render_join(INFO)
    assert "SPELLBENCH_PROTOCOL_V2.md" in join and "examples/minimal_bot.py" in join
```

Update any existing assertion on the old Games copy or the v1 spec link to the new text.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_site_render.py -q`
Expected: FAIL on the four new tests.

- [ ] **Step 3: Implement**

Extend `render_benchmark`, `_details`, `_run_box`, `render_method` (`_METHOD_SECTIONS`) and `render_join` to the contract; escape every new data string with `_e`; add CSS for `.fairness`, `.legacy` and `.attribution` using the existing tokens (no new colors).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_site_render.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Look at the pages**

Render the fixture views (v2 and legacy) to a scratch directory outside the repo and check them at desktop width and 375 px, light and dark. Record what you checked in the report.

- [ ] **Step 6: Commit**

```bash
git add python/spellbench/site/render.py python/tests/test_site_render.py
git commit -m "Site: protocol, fairness verdict, information rules and attribution on benchmark pages"
```

## Wave 9

### Task 39: Migrate the adjudication tests

**Effort:** 0.5 agent-day. **Wave:** 9. **Depends on:** Tasks 21, 28, 33, 36.

**Files:**
- Rewrite: `python/tests/test_arena_adjudication.py` (remove the skip)
- Delete: `python/tests/bot_invalid_choice.py`, `python/tests/bot_hang.py`, `python/tests/bot_hostile.py` (replaced by `bot_v2_hostile.py` modes)

**Interfaces:**
- Consumes: `arena_helpers` (Task 33), `bot_v2_hostile` modes (Task 28), the fake engine hooks (Task 21), `validate_tournament_dir` (Task 36).
- Produces: tests only. Every v1 test keeps a v2 counterpart: invalid selection, timeout, hostile answers, a bot that cannot introduce itself, engine crash, engine-reported halt, truncation, byte-identical adjudicated reruns, the hung bot behind a wrapper; the v1 "a truncated game may name a winner" test is retired (spec 9.5: a truncated terminal has `winner: null`) in favor of truncation attribution.

- [ ] **Step 1: Write the tests**

Rewrite `python/tests/test_arena_adjudication.py`:

```python
"""Host adjudication in tournaments: forfeits, halts, truncation, stalling, attribution (spec 11.4, 11.5)."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

from spellbench.arena import runner
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import BOT_HOSTILE, builtin, hostile_bot, ledger_rows, leaderboard, make_config, row_by_name, run, subprocess_bot

FAST = {"startup_ms": 30000, "game_start_ms": 30000, "bank_ms": 600000, "increment_ms": 0, "max_decision_ms": 500, "engine_step_ms": 30000}
TIGHT = {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 20,
         "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999}


def _duel(directory: Path, second: dict, **extra) -> runner.TournamentSummary:
    return run(make_config(directory, [builtin("heuristic"), second], pairs=1, include_self_play=False, **extra))


@pytest.mark.parametrize(
    ("mode", "cause"),
    [("out-of-range", "invalid_selection"), ("wrong-echo-semantic", "invalid_selection"), ("hang", "timeout"),
     ("garbage", "malformed_response"), ("nested", "malformed_response"), ("flood", "malformed_response"),
     ("bigint", "malformed_response"), ("surrogate-error", "malformed_response"), ("error-response", "agent_error"),
     ("crash", "transport_error")],
)
def test_a_bad_bot_forfeits_rated_losses_and_the_run_still_publishes(tmp_path: Path, mode: str, cause: str) -> None:
    directory = tmp_path / "t"
    summary = _duel(directory, hostile_bot(mode), time_control=FAST)
    assert (summary.status, summary.games_total, summary.games_forfeit, summary.games_rated) == ("complete", 2, 2, 2)
    assert {row["reason"] for row in ledger_rows(directory)} == {f"forfeit:{cause}"}
    offender = row_by_name(leaderboard(directory), "hostile")
    assert offender["forfeit_losses"] == 2 and offender["forfeits_by_cause"] == {cause: 2}
    assert validate_tournament_dir(directory) == []


@pytest.mark.parametrize(("mode", "reason"), [("stdout-noise", "hostile"), ("wrong-name", "hostile"), ("badname", "hello"),
                                              ("slow-hello", "hostile"), ("requires-poison", "poison")])
def test_a_bot_that_cannot_introduce_itself_stops_the_tournament_up_front(tmp_path: Path, mode: str, reason: str) -> None:
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match=reason) as caught:
        _duel(directory, hostile_bot(mode), time_control={**FAST, "startup_ms": 2000})
    assert "Loading" not in str(caught.value)            # nothing the bot printed is quoted
    assert not directory.exists()


@pytest.mark.parametrize(
    ("deck", "classification", "reason", "counter"),
    [("Crash", "halted", "host_engine_fault:transport", "halts_attributed"),
     ("Halt", "halted", "engine_contract_failure:test_hook", "halts_attributed"),
     ("Truncate", "truncated", "engine_cap", "truncations_attributed")],
)
def test_engine_endings_are_unrated_and_attributed(tmp_path: Path, deck, classification, reason, counter) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], decks=(deck, deck), pairs=1, include_self_play=False))
    rows = ledger_rows(directory)
    assert {(row["classification"], row["reason"]) for row in rows} == {(classification, reason)}
    assert all(row["last_selection"]["seat"] == "p0" for row in rows) and summary.games_rated == 0
    assert sum(entry[counter] for entry in leaderboard(directory)["rows"]) == 2


def test_stalling_and_mandatory_loops_are_adjudicated_at_the_caps(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    run(make_config(loop, [builtin("first"), builtin("heuristic")], decks=("Loop", "Loop"), pairs=1, include_self_play=False, limits=TIGHT))
    assert {row["reason"] for row in ledger_rows(loop)} == {"mandatory_loop"}
    stall = tmp_path / "stall"
    run(make_config(stall, [builtin("first"), builtin("heuristic")], decks=("Stall", "Stall"), pairs=1, include_self_play=False, limits=TIGHT))
    assert sorted(row["reason"] for row in ledger_rows(stall)) == ["forfeit:stalling", "stall_ended"]
    assert row_by_name(leaderboard(stall), "heuristic")["forfeits_by_cause"] == {"stalling": 1}


def test_adjudicated_rows_are_byte_identical_across_reruns(tmp_path: Path) -> None:
    for name in ("a", "b"):
        _duel(tmp_path / name, hostile_bot("crash"))     # the crashing bot prints its PID to stderr; none of it reaches the ledger
    assert (tmp_path / "a" / "matches.jsonl").read_bytes() == (tmp_path / "b" / "matches.jsonl").read_bytes()


def test_a_hung_bot_behind_a_wrapper_process_is_killed(tmp_path: Path) -> None:
    if os.name == "nt":
        wrapper = tmp_path / "wrap.bat"
        wrapper.write_text(f'@"{sys.executable}" "{BOT_HOSTILE}" hang\n', encoding="ascii")
        command = ["cmd", "/c", str(wrapper)]
    else:
        wrapper = tmp_path / "wrap.sh"
        wrapper.write_text(f'"{sys.executable}" "{BOT_HOSTILE}" hang\n', encoding="ascii")
        command = ["sh", str(wrapper)]
    directory = tmp_path / "t"
    outcome: list[BaseException | None] = []

    def play() -> None:
        try:
            _duel(directory, subprocess_bot("hostile", command), time_control=FAST)
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=play, daemon=True)
    worker.start()
    worker.join(timeout=60)
    assert outcome == [None], "the host is still blocked on the hung bot's pipes"
    assert {row["reason"] for row in ledger_rows(directory)} == {"forfeit:timeout"}
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest python/tests/test_arena_adjudication.py -q`
Expected: PASS (fix the stack, not the test, on a failure: these pin the spec 11.5 contract).

- [ ] **Step 3: Delete the v1 bot fixtures and run the whole suite**

Delete `bot_invalid_choice.py`, `bot_hang.py`, `bot_hostile.py`; confirm nothing imports them (`grep -rn "bot_hang\|bot_invalid_choice\|bot_hostile\b" python/tests` finds nothing but `bot_v2_hostile`).
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add -A python/tests/test_arena_adjudication.py python/tests/bot_invalid_choice.py python/tests/bot_hang.py python/tests/bot_hostile.py
git commit -m "Tests: adjudication on protocol v2 (forfeits, halts, truncation, stalling, attribution)"
```

### Task 40: Migrate the remaining arena tests

**Effort:** 0.75 agent-day. **Wave:** 9. **Depends on:** Tasks 21, 33, 36.

**Files:**
- Modify (remove the skip, port): `python/tests/test_arena_e2e.py`, `test_arena_schedule.py`, `test_arena_slices.py`, `test_arena_parallel.py`, `test_arena_resolve.py`, `test_arena_commands.py`, `test_arena_ratings.py`

**Interfaces:**
- Consumes: `arena_helpers` (Task 33), `arena.config`, `arena.ledger`, `arena.leaderboard` (v2), `arena.validate` (Task 36), the fake engine (Task 21).
- Produces: tests only. Every v1 test keeps a counterpart of the same name that pins the same behavior on v2; the only retirements are listed below.

Porting rules (apply to every test in the seven modules):

| v1 | v2 |
|---|---|
| `runner.TournamentConfig` | `spellbench.arena.config.TournamentConfig` |
| config `schema` `spellbench-tournament-config/v1`, `base_seed` | `spellbench-tournament-config/v2`, `stats_seed` |
| `choose_timeout_ms`, `startup_timeout_ms`, `engine.timeout_ms` | `time_control` (`max_decision_ms`, `startup_ms`, `engine_step_ms`); the other fields from `config.DEFAULT_TIME_CONTROL` |
| builtin `"version": "1.0.0"` | `"2.0.0"` |
| ledger `game_id` `m0001p0000g0` | `TEST_RUN_SECRET.game_id(i)`, `i` the schedule position (`game_index`) |
| ledger `game_index` (0 or 1) | `pair_slot` |
| ledger `game_seed` | gone: a schedule-tampering test edits `game_id` |
| ledger deck `{"catalog_id": X}` | `{"deck_id", "name", "catalog_id": X}` |
| `store.LedgerRow(...)` builders (`test_arena_ratings.py`, `test_arena_slices.py`) | `ledger.parse_ledger([...])` rows in Task 12's shape; every `build_leaderboard` call passes `schema=leaderboard.LEADERBOARD_SCHEMA_V2`; expected ratings, intervals and slice labels are unchanged (the math is) |
| v1 validate texts in `test_arena_e2e.py` | Task 36's texts (the arena-version message is unchanged) |
| `Rendezvous` waits at `reset` | at the first `step` |
| `spellbench bot` answers `spellbench/v1` | `spellbench/v2` with `2.0.0` |
| `test_the_package_version_is_the_project_version` | unchanged |

Retired: `test_validate_checks_the_ledger_against_the_schedule` edits `game_id` instead of `game_seed` (same name kept); nothing else is retired. New in `test_arena_e2e.py`:

```python
def test_the_two_games_of_a_pair_have_independent_secrets(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("uniform", seed=11), builtin("first")], pairs=1, include_self_play=False))
    first, second = ledger_rows(directory)
    assert (first["pair_index"], second["pair_index"]) == (0, 0) and first["game_digest"] != second["game_digest"]
    assert first["game_id"] != second["game_id"]
```

- [ ] **Step 1: Port the modules**

Apply the table module by module, keeping test names; run each module as you finish it: `uv run pytest python/tests/test_arena_e2e.py -q` and so on.
Expected: each module PASSES.

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest python/tests -q`
Expected: all pass; the only module-level skips left are `test_bench_run.py` (Task 41) and `test_site_build.py` (Task 42).

- [ ] **Step 3: Commit**

```bash
git add python/tests/test_arena_e2e.py python/tests/test_arena_schedule.py python/tests/test_arena_slices.py python/tests/test_arena_parallel.py python/tests/test_arena_resolve.py python/tests/test_arena_commands.py python/tests/test_arena_ratings.py
git commit -m "Tests: arena end to end, schedule, slices, parallel, resolve, commands and ratings on protocol v2"
```

### Task 41: Bench commit, run, reveal and rerun

**Effort:** 0.75 agent-day. **Wave:** 9. **Depends on:** Tasks 31, 33, 36, 37.

**Files:**
- Create: `python/spellbench/bench/commit.py`
- Rewrite: `python/spellbench/bench/run.py`
- Modify: `python/spellbench/arena/cli.py` (`bench commit`, `bench run`, `bench reveal`, `bench rerun`)
- Modify: `python/spellbench/arena/validate.py` (a revealed run: `REVEAL.json` without a manifest)
- Modify: `python/tests/test_bench_run.py` (remove the skip; port to v2)
- Create: `python/tests/test_bench_commit.py`

**Interfaces:**
- Consumes: `bench.definition` (Task 37), `arena.runner` (Task 33), `arena.manifest` (`commitment_record`, `CommitmentProof`) (Task 31), `arena.schedule`, `arena.executor`, `arena.throughput.Allocation`, `run_secret.RunSecret`, `arena.validate` (Task 36).
- Produces (`spellbench.bench.commit`):
  - `SECRETS_DIR_NAME = "SPELLBENCH_SECRETS_DIR"`, `REVEAL_NAME = "REVEAL.json"`, `REVEAL_SCHEMA = "spellbench-run-reveal/v1"`, `class CommitError(ValueError)`
  - `@dataclass(frozen=True) class CommittedRun: run_dir: Path; commitment: str; secret_path: Path`
  - `secrets_dir(environ: Mapping[str, str], local: Mapping[str, str]) -> Path` (the environment, then `benchmarks/local.json`, then `Path.home() / ".spellbench" / "run-secrets"`)
  - `commit_run(benchmark_dir: Path, *, date: str | None = None, environ: Mapping[str, str] | None = None) -> CommittedRun`
  - `load_run_secret(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> RunSecret`
  - `pushed_commit(run_dir: Path) -> str` (the commit that added `COMMITMENT.json`, contained in a remote-tracking branch)
  - `reveal_run(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str] | None = None) -> Path`
- Produces (`spellbench.bench.run`):
  - `@dataclass(frozen=True) class BenchmarkRun: run_dir: Path; summary: TournamentSummary; failures: tuple[str, ...]`
  - `run_benchmark(benchmark_dir: Path, *, run: str | None = None, proof: str | None = None, unrated: bool = False, date: str | None = None, placement: str | None = None, environ: Mapping[str, str] | None = None) -> BenchmarkRun`
  - `rerun_games(run_dir: Path, *, games: Sequence[int] | None = None, environ: Mapping[str, str] | None = None) -> list[str]`
- CLI: `spellbench bench commit BENCHMARK_DIR [--date YYYY-MM-DD]`; `spellbench bench run BENCHMARK_DIR (--run NAME --proof REF | --unrated [--date YYYY-MM-DD]) [--placement TEXT]`; `spellbench bench reveal BENCHMARK_DIR --run NAME`; `spellbench bench rerun RUN_DIR [--game N]...`

Flow (spec 11.1, 11.6; Decisions 3 and 9): `commit_run` picks the next run name, generates the secret, refuses a secrets directory inside the repository work tree (`git rev-parse --show-toplevel`), writes the hex secret to `<secrets dir>/<benchmark id>/<run>.hex`, then writes `runs/<run>/COMMITMENT.json` (`commitment_record`), and tells the operator to commit and push it and record a third-party timestamp (an issue comment, a signed release, or an OpenTimestamps proof). `run_benchmark` with `run` loads the secret (it must hash to the file's commitment), checks `pushed_commit`, and passes `CommitmentProof(commit, proof)`; with `unrated` it uses a fresh secret and no proof (the runner writes the commitment before the first game). The allocation is `Allocation.unmeasured(benchmark.workers)` until Task 43 adds the guard, so rated runs publish as unrated until then. When a committed run fails before the runner publishes a manifest, `run_benchmark` calls `reveal_run`, which writes `REVEAL.json` (`{"schema", "benchmark_id", "run_label", "commitment", "run_secret", "status": "aborted", "reason"}`), so every committed run is published (spec 11.6); `validate` accepts such a directory when the secret hashes to the commitment. `rerun_games` resolves placeholders like `run_benchmark`, rebuilds the schedule from the revealed secret, replays the chosen games (all by default) through `runner.play_games`, and reports every game whose outcome, reason or `game_digest` differs from the ledger.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_bench_commit.py`:

```python
"""Commitment first, secret outside the repository, reveal, rerun (spec 11.6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from spellbench.bench.commit import CommitError, commit_run, pushed_commit, reveal_run, secrets_dir
from spellbench.bench.run import rerun_games, run_benchmark

from test_bench_run import ENVIRON, _write_benchmark


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "--bare", "-q", str(remote))
    work.mkdir()
    git(work, "init", "-q")
    git(work, "config", "user.email", "bench@example.org")
    git(work, "config", "user.name", "bench")
    git(work, "remote", "add", "origin", str(remote))
    (work / "benchmarks").mkdir()
    _write_benchmark(work / "benchmarks")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "benchmark")
    git(work, "push", "-q", "origin", "HEAD:main")
    return work


def env(tmp_path: Path) -> dict[str, str]:
    return {**ENVIRON, "SPELLBENCH_SECRETS_DIR": str(tmp_path / "secrets")}


def test_a_committed_run_needs_a_pushed_commitment_then_runs_with_its_proof(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", environ=env(tmp_path))
    assert committed.run_dir == bench / "runs" / "2026-10-01"
    assert json.loads((committed.run_dir / "COMMITMENT.json").read_text(encoding="utf-8"))["commitment"] == committed.commitment
    assert repo not in committed.secret_path.parents
    with pytest.raises(CommitError, match="pushed"):
        pushed_commit(committed.run_dir)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "commitment")
    git(repo, "push", "-q", "origin", "HEAD:main")
    result = run_benchmark(bench, run="2026-10-01", proof="https://example.org/issues/1#c1", environ=env(tmp_path))
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.failures == () and manifest["secrets"]["commitment"] == committed.commitment
    assert manifest["secrets"]["commitment_proof"] == {"commit": git(repo, "rev-parse", "HEAD"), "timestamp": "https://example.org/issues/1#c1"}
    assert rerun_games(result.run_dir, games=[0, 1], environ=env(tmp_path)) == []


def test_the_secret_never_lands_in_the_repository(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", environ=ENVIRON)          # no SPELLBENCH_SECRETS_DIR: the home default
    assert (tmp_path / "home") in committed.secret_path.parents and repo not in committed.secret_path.parents
    assert git(repo, "status", "--porcelain", "--untracked-files=all").splitlines() == ["?? benchmarks/fake-pool/runs/2026-10-01/COMMITMENT.json"]
    with pytest.raises(CommitError, match="outside the repository"):
        commit_run(bench, date="2026-10-01", environ={**ENVIRON, "SPELLBENCH_SECRETS_DIR": str(repo / "secrets")})
    assert commit_run(bench, date="2026-10-01", environ=ENVIRON).run_dir.name == "2026-10-01-2"


def test_a_committed_run_that_died_is_revealed(repo: Path, tmp_path: Path) -> None:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", environ=env(tmp_path))
    reveal = reveal_run(committed.run_dir, benchmark_id="fake-pool", environ=env(tmp_path))
    record = json.loads(reveal.read_text(encoding="utf-8"))
    assert record["status"] == "aborted" and record["commitment"] == committed.commitment and len(record["run_secret"]) == 64
    from spellbench.arena.validate import validate_tournament_dir
    assert validate_tournament_dir(committed.run_dir) == []


def test_a_rerun_catches_a_changed_result(repo: Path, tmp_path: Path) -> None:
    result = run_benchmark(repo / "benchmarks" / "fake-pool", unrated=True, date="2026-10-01", environ=env(tmp_path))
    ledger = result.run_dir / "matches.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    rows[0]["game_digest"] = "sha256:" + "0" * 64
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert any("game 0" in mismatch for mismatch in rerun_games(result.run_dir, games=[0], environ=env(tmp_path)))
```

Port `python/tests/test_bench_run.py` (delete the skip): `_write_benchmark` and `_bot` write v2 definitions (`"schema": "spellbench-benchmark/v2"`, `stats_seed`, builtin `2.0.0`, the engine `["${PY}", "${FAKE_ENGINE}"]` with `FAKE_ENGINE` now `fake_v2_engine.py`); every `run_benchmark(bench, date=...)` call gains `unrated=True`; `PUBLISHED` gains `COMMITMENT.json`; the CLI tests call `bench run DIR --unrated --date ...`; add a usage test that `bench run DIR` with neither `--run` nor `--unrated` exits 2.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_bench_commit.py python/tests/test_bench_run.py -q`
Expected: FAIL at collection (`ModuleNotFoundError: spellbench.bench.commit`).

- [ ] **Step 3: Implement**

Write `commit.py` and `run.py` to the flow above; use `git` through `subprocess.run([...], capture_output=True, text=True)` with `-C <run_dir>`: `ls-files --error-unmatch COMMITMENT.json` (tracked), `diff --quiet HEAD -- COMMITMENT.json` (unchanged), `log -n 1 --format=%H --diff-filter=A -- COMMITMENT.json` (the adding commit), `branch -r --contains <sha>` (pushed). Every failure (untracked, modified since its commit, or on no remote-tracking branch) raises `CommitError` with a message that starts `the commitment is not in a pushed commit:` and names the missing step, for example `...: push it before the first game (spec 11.6)`. Write the secret file with `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)`. Add the four `bench` subcommands to `cli.py` (usage errors exit 2).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_bench_commit.py python/tests/test_bench_run.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/bench/commit.py python/spellbench/bench/run.py python/spellbench/arena/cli.py python/spellbench/arena/validate.py python/tests/test_bench_commit.py python/tests/test_bench_run.py
git commit -m "Bench: commit before the first game, run with a proof, reveal, rerun"
```

### Task 42: Site build on v2 and legacy runs

**Effort:** 0.5 agent-day. **Wave:** 9. **Depends on:** Tasks 4, 33, 36, 37, 38.

**Files:**
- Modify: `python/spellbench/site/build.py`
- Modify: `python/tests/test_site_build.py` (remove the skip; port to v2)

**Interfaces:**
- Consumes: `bench.definition` (Task 37), `arena.validate` (Task 36), `arena.legacy_v1.read_v1_run` (Task 4), `arena.config.TournamentConfig`, `render` view contract (Task 38), `hero`.
- Produces (`spellbench.site.build`): `build_site(benchmarks_dir: Path, out_dir: Path) -> list[str]` unchanged in signature; new helper `board_run_dir(benchmark_dir: Path) -> Path | None` (the latest published run that is a rated v2 run or a v1 run).

Rules (Decisions 1 and 3): each benchmark's page and Hero chip come from its board run; published runs newer than the board run are validated too, listed in `newer_runs`, and warned about ("<id>: runs/<name> is <status> and not rated; showing runs/<board>"); a run directory holding `REVEAL.json` and no manifest warns as "revealed after an abort" (detect it by that file name alone: Task 41 adds its validation in this same wave); a legacy board run is read with `legacy_v1.read_v1_run`, shows its bots by definition display where the name matches and by registry name otherwise, skips the drift check, and warns "<id>: the board run is protocol v1; rerun on protocol v2 to publish the current definition"; a v2 board run keeps the drift check (comparing v2 configs) and fills `protocol`, `fairness` (from `validator`), `setup_rules` (opponent decklist, mulligan with "(the engine offers no mulligans)" when the resolved rule is `none` because the engine lacks London, starting player, card-name domain size, each engine default, the optional observation fields the engine provides, enabled extensions), `attribution` (from the leaderboard rows), and the run's status, rated flag, commitment and revealed secret.

- [ ] **Step 1: Port and extend the tests**

In `python/tests/test_site_build.py`: delete the skip; import `FAKE_ENGINE`, `TEST_RUN_SECRET`, `TEST_PROOF`, `small_allocation` and `hostile_bot` from `arena_helpers` in place of the v1 names (`FAKE_ARENA_ENGINE`; `BOT_INVALID_CHOICE` becomes `hostile_bot("out-of-range")`), plus `RunSecret`, `TournamentConfig`, and `REPO = Path(__file__).resolve().parents[2]`; `_definition` writes v2 definitions; `_add_benchmark` publishes rated runs with `runner.run_tournament(TournamentConfig.from_json(config), run_secret=TEST_RUN_SECRET, allocation=small_allocation(), commitment_proof=TEST_PROOF, output_dir=directory / "runs" / name)`; every existing test keeps its name and intent. Add:

```python
def test_a_legacy_board_run_is_shown_with_its_label(tmp_path: Path) -> None:
    root = tmp_path / "benchmarks"
    bench = root / "pauper-kernel"
    shutil.copytree(REPO / "benchmarks" / "pauper-kernel", bench)
    warnings = build_site(root, tmp_path / "site")
    page = (tmp_path / "site" / "b" / "pauper-kernel" / "index.html").read_text(encoding="utf-8")
    assert 'class="legacy"' in page and "protocol v1" in page
    assert any("protocol v1" in warning for warning in warnings)
    assert "pauper-kernel" in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")


def test_a_newer_unrated_run_is_not_the_board_run(copy_tree: Path, tmp_path: Path) -> None:
    bench = copy_tree / "alpha"
    config = definition.load_benchmark(bench).tournament_config("runs/2026-09-27")
    runner.run_tournament(TournamentConfig.from_json(config), run_secret=RunSecret.generate(), allocation=small_allocation(),
                          output_dir=bench / "runs" / "2026-09-27")
    warnings = build_site(copy_tree, tmp_path / "site")
    page = (tmp_path / "site" / "b" / "alpha" / "index.html").read_text(encoding="utf-8")
    assert "Run 2026-09-26" in page and "Newer runs not shown: 2026-09-27 (complete)" in page
    assert any("2026-09-27" in warning and "not rated" in warning for warning in warnings)


def test_a_v2_page_shows_the_fairness_verdict_and_rules(tree: Path, tmp_path: Path) -> None:
    build_site(tree, tmp_path / "site")
    page = (tmp_path / "site" / "b" / "alpha" / "index.html").read_text(encoding="utf-8")
    assert 'class="fairness"' in page and "verdict pass" in page and "Opponent decklist" in page
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_site_build.py -q`
Expected: FAIL (the build still reads v1 configs and has no board-run rule).

- [ ] **Step 3: Implement**

Update `build.py` to the rules above; `_Run` gains `legacy: bool`, `manifest: dict | None`; `_read_run` branches on the manifest schema; the view builders fill the Task 38 keys.

- [ ] **Step 4: Run the tests, then the whole suite and the real site**

Run: `uv run pytest python/tests/test_site_build.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass, with no module-level skip left.
Run: `uv run spellbench site benchmarks "$TMPDIR/site-check"` (any scratch directory outside the repo)
Expected: `site built: ...`, with the warning that the pauper-kernel board run is protocol v1.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/site/build.py python/tests/test_site_build.py
git commit -m "Site: board runs from rated v2 or legacy v1 runs, with fairness and attribution"
```

## Wave 10

### Task 43: Launch guards in `bench run` and `spellbench run`

**Effort:** 0.5 agent-day. **Wave:** 10. **Depends on:** Tasks 5, 25, 33, 41.

**Files:**
- Modify: `python/spellbench/bench/run.py` (throughput guard, pinning, registration)
- Modify: `python/spellbench/arena/runner.py` (the idle monitor during execution)
- Modify: `python/spellbench/arena/cli.py` (`--placement` on `run`; allocation line in the output)
- Modify: `.gitignore` (`benchmarks/**/throughput.jsonl`)
- Create: `python/tests/test_bench_guards.py`

**Interfaces:**
- Consumes: `arena.throughput` (`plan_allocation`, `ThroughputError`, `IdleMonitor`, `SMALL_RUN_SECONDS`), `bench.pinning` (`engine_files`, `pin_files`, `register_pins`, `PinningError`) (Task 5); `arena.schedule` (`preflight`, `schedule`), `arena.runner` (`play_games`, `run_tournament`, `executed_config`, `registry_entries`) (Task 33); `bench.commit` (Task 41); `run_secret.RunSecret`.
- Produces:
  - `bench.run.qualification_play(config: TournamentConfig) -> Callable[[int, int], tuple[float, str]]` (a throwaway `RunSecret.generate()`, one preflight, the first `games` scheduled contexts played with `workers` workers through `play_games`; returns wall seconds and `"sha256:" +` the hex digest of the canonical rows)
  - `bench.run.plan_for(config: TournamentConfig, *, placement: str | None) -> Allocation` (`plan_allocation(games_total=len(schedule(config, secret)), cap=config.workers, per_game_cores=config.per_game_cores(), play=qualification_play(config), placement=placement)`)
  - `run_benchmark(...)` now uses `plan_for` for every run, and for a rated run (`run=...`) requires the local values `SPELLBENCH_PIN_ROOT` and `SPELLBENCH_ARTIFACT_REGISTER` (optional `SPELLBENCH_ARTIFACT_OWNER`, default `spellbench`), pins the executed engine command's files before the run (`engine_files` also go to the manifest for every run), and after publishing registers each pinned directory (purpose `engine of <id> run <name>`, doc the run's `manifest.json`, regen `build <engine name> <version> at <source_revision or "unknown">`)
  - `spellbench run CONFIG.json [--placement TEXT]` also plans with `plan_for`; both commands print `allocation: <kind> (<workers> workers)`
  - `runner.run_tournament` runs an `IdleMonitor(allocation.workers)` when `allocation.workers > 1`, appending each warning to `<run dir>/throughput.jsonl` (never in the manifest's files) and to stderr

A guard failure (a `ThroughputError`, missing pin values, a `PinningError`) stops the command before the first game; for a committed run it publishes `REVEAL.json` (Task 41), because the commitment is already public.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_bench_guards.py`:

```python
"""COMPUTE-POLICY and ARTIFACT-LAW guards on the launch paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spellbench.arena import cli, throughput
from spellbench.bench.commit import commit_run
from spellbench.bench.definition import BenchmarkError
from spellbench.bench.run import run_benchmark

from test_bench_commit import git, repo  # noqa: F401  (repo is a fixture this module reuses)
from test_bench_run import ENVIRON, _write_benchmark


def _register_script(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "register.log"
    script = tmp_path / "register.py"
    script.write_text(f"import json, sys\nopen({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n", encoding="utf-8")
    return script, log


def _committed(repo: Path, tmp_path: Path, environ: dict) -> str:
    bench = repo / "benchmarks" / "fake-pool"
    committed = commit_run(bench, date="2026-10-01", environ=environ)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "commitment")
    git(repo, "push", "-q", "origin", "HEAD:main")
    return committed.run_dir.name


def test_a_rated_run_is_measured_pinned_and_registered(repo: Path, tmp_path: Path) -> None:
    script, log = _register_script(tmp_path)
    environ = {**ENVIRON, "SPELLBENCH_SECRETS_DIR": str(tmp_path / "secrets"), "SPELLBENCH_PIN_ROOT": str(tmp_path / "pins"),
               "SPELLBENCH_ARTIFACT_REGISTER": str(script)}
    name = _committed(repo, tmp_path, environ)
    result = run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof="https://example.org/i/1", environ=environ)
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["allocation"]["kind"] == "small" and manifest["run"]["rated"] is True
    engine_file = next(entry for entry in manifest["engine_files"] if entry["file_name"] == "fake_v2_engine.py")
    assert (tmp_path / "pins" / engine_file["sha256"] / "fake_v2_engine.py").is_file()
    assert any(f"engine of fake-pool run {name}" in line for line in log.read_text(encoding="utf-8").splitlines())
    assert result.failures == ()


def test_a_rated_run_without_pin_values_stops_and_is_revealed(repo: Path, tmp_path: Path) -> None:
    environ = {**ENVIRON, "SPELLBENCH_SECRETS_DIR": str(tmp_path / "secrets")}
    name = _committed(repo, tmp_path, environ)
    with pytest.raises(BenchmarkError, match="SPELLBENCH_PIN_ROOT"):
        run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof="https://example.org/i/1", environ=environ)
    run_dir = repo / "benchmarks" / "fake-pool" / "runs" / name
    assert (run_dir / "REVEAL.json").is_file() and not (run_dir / "matches.jsonl").exists()


def test_a_substantial_run_needs_a_placement_and_compares_worker_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(throughput, "SMALL_RUN_SECONDS", 0)
    bench = _write_benchmark(tmp_path / "benchmarks")
    with pytest.raises(throughput.ThroughputError, match="placement"):
        run_benchmark(bench, unrated=True, date="2026-10-01", environ=ENVIRON)
    result = run_benchmark(bench, unrated=True, date="2026-10-02", placement="this PC only: 12 s projected", environ=ENVIRON)
    allocation = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))["allocation"]
    assert allocation["kind"] == "substantial" and allocation["outputs_identical"] is True
    assert [trial["workers"] for trial in allocation["trials"]][0] == 1 and allocation["placement"].startswith("this PC")


def test_spellbench_run_is_guarded_too(tmp_path: Path, capsys) -> None:
    from arena_helpers import builtin, make_config
    path = tmp_path / "config.json"
    path.write_text(json.dumps(make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=1)), encoding="utf-8")
    assert cli.main(["run", str(path)]) == 0
    assert "allocation: small (" in capsys.readouterr().out
    assert json.loads((tmp_path / "t" / "manifest.json").read_text(encoding="utf-8"))["allocation"]["kind"] == "small"


def test_idle_warnings_go_to_an_unhashed_file(tmp_path: Path, monkeypatch) -> None:
    from arena_helpers import builtin, make_config, run
    monkeypatch.setattr(throughput.IdleMonitor, "tick", lambda self, *, running, queued: "idle capacity: test")
    run(make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=2, workers=2))
    assert "idle capacity: test" in (tmp_path / "t" / "throughput.jsonl").read_text(encoding="utf-8")
    files = [entry["path"] for entry in json.loads((tmp_path / "t" / "manifest.json").read_text(encoding="utf-8"))["files"]]
    assert "throughput.jsonl" not in files
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_bench_guards.py -q`
Expected: FAIL (allocations are `unmeasured`; nothing is pinned; no placement check).

- [ ] **Step 3: Implement**

Wire `plan_for` into `run_benchmark` (after placeholder resolution and the commitment checks, before `run_tournament`) and into `cli._cmd_run`; the rated path checks the pin values first, then `engine_files(executed.engine_command)`, `pin_files`, the run, then `register_pins`. In `runner.run_tournament`, pass an `IdleMonitor` to `play_games` when `allocation.workers > 1` and write each returned warning as one JSON line `{"warning": text}` to `throughput.jsonl`. Add `benchmarks/**/throughput.jsonl` to `.gitignore`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest python/tests/test_bench_guards.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/bench/run.py python/spellbench/arena/runner.py python/spellbench/arena/cli.py .gitignore python/tests/test_bench_guards.py
git commit -m "Launch guards: throughput qualification, engine pinning and registration"
```

### Task 44: Remove protocol v1, update the docs, final checks

**Effort:** 0.5 agent-day. **Wave:** 10. **Depends on:** Tasks 39, 40, 41, 42 (and so every earlier task).

**Files:**
- Delete: `python/spellbench/models.py`, `engine_client.py`, `agent_client.py`, `agent_server.py`, `_client.py`, `python/spellbench/arena/bots/` (package), `python/tools/generate_protocol_goldens.py`, `goldens/protocol_v1/`, `python/tests/test_models.py`, `test_engine_client.py`, `test_agent_client.py`, `test_agent_server.py`, `test_golden_replay.py`, `test_end_to_end.py`, `fake_engine.py`
- Modify: `python/spellbench/wire.py` (delete `candidates_sha256`; gain the `Peer` protocol from `_client.py`), `python/spellbench/host/engine_process.py`, `python/spellbench/host/agent_process.py` (import `Peer` from `wire`), `python/spellbench/errors.py` (delete the v1 code sets), `python/spellbench/__init__.py` (v2 docstring and exports; `__version__ = "0.3.0"`), `pyproject.toml` (`version = "0.3.0"`), `uv.lock` (`uv lock`), `python/tests/conftest.py` (keep `ScriptedPeer`, `payload`, `scripted_peer`; drop v1 imports and helpers), `python/tests/test_wire.py` (drop the `candidates_sha256` tests)
- Modify: `.github/workflows/ci.yml` (the goldens step runs `generate_goldens_v2.py --check`), `README.md`, `examples/mtg-kernel.json`
- Modify, when sub-project C's `integrations/mtg_kernel/` exists on the branch: its test modules get `import pytest` and `pytest.skip("the kernel bot speaks protocol v1; K2 ports it to spellbench.bot", allow_module_level=True)` right after `from __future__ import annotations` (or first, without one), before every other import (the bot imports `spellbench.agent_server`, which this task deletes; K2 ports it to `spellbench.bot.serve` and `spellbench.builtins.uniform.SplitMix64`)
- Create: `python/tests/test_repository_hygiene.py`

**Interfaces:**
- Consumes: everything above.
- Produces: package `spellbench` 0.3.0 whose top level exports `messages`, `wire`, `bot`, the error classes, and lazily `EngineProcess` (`host.engine_process`), `AgentProcess` (`host.agent_process`) and `serve` (`bot.serve`).

- [ ] **Step 1: Write the failing hygiene test**

Create `python/tests/test_repository_hygiene.py`:

```python
"""Protocol v1 code is gone, no migration skip is left, and v2 text carries no em-dash."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import spellbench

REPO = Path(__file__).resolve().parents[2]
EM_DASH = "\u2014"


@pytest.mark.parametrize("module", ["spellbench.models", "spellbench.engine_client", "spellbench.agent_client",
                                    "spellbench.agent_server", "spellbench._client", "spellbench.arena.bots"])
def test_v1_modules_are_gone(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_no_migration_skip_is_left() -> None:
    offenders = [path.name for path in (REPO / "python" / "tests").glob("test_*.py")
                 if "protocol v1 test, migrated in Task" in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_the_version_and_the_exports() -> None:
    assert spellbench.__version__ == "0.3.0"
    assert spellbench.serve is spellbench.bot.serve and spellbench.EngineProcess.__module__ == "spellbench.host.engine_process"


def test_no_em_dash_in_v2_text() -> None:
    roots = [REPO / "python", REPO / "goldens" / "protocol_v2", REPO / "examples", REPO / "README.md",
             REPO / "benchmarks" / "pauper-kernel" / "benchmark.json"]
    files = [p for root in roots for p in ([root] if root.is_file() else root.rglob("*"))
             if p.is_file() and p.suffix in {".py", ".md", ".json", ".jsonl"} and "__pycache__" not in p.parts]
    assert [str(p.relative_to(REPO)) for p in files if EM_DASH in p.read_text(encoding="utf-8")] == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest python/tests/test_repository_hygiene.py -q`
Expected: FAIL (the v1 modules import; the version is 0.2.0).

- [ ] **Step 3: Remove v1 and update the package**

Make the deletions and modifications listed under Files. Then run `uv lock` and check that `uv.lock` changed only the `spellbench` version line.

- [ ] **Step 4: Update the docs and examples**

`examples/mtg-kernel.json`: the quickstart shape of Task 33 with `"engine": {"command": ["../mtg-kernel/target/release/agent_bridge_v2"]}`, `"pairs_per_matchup": 32`, `"workers": 8`.

`README.md`, keeping its length and plain style: the intro points to `spec/SPELLBENCH_PROTOCOL_V2.md` ("v1 is kept for reference; committed v1 runs still validate"); the Quickstart is unchanged apart from the output line `status: complete (unrated)`; "Real engines" becomes: "Any executable that serves the environment role works. Check it first: `uv run spellbench conformance engine --format pauper-bo1 --deck Burn -- path/to/engine`. The mtg-kernel adapter for protocol v2 is `agent_bridge_v2` (in progress)."; "Write a bot" shows

```python
from spellbench.bot import serve

def choose(decision):
    for candidate in decision.candidates:
        if candidate.semantic["kind"] == "play_land":
            return candidate.candidate_id
    return decision.candidates[0].candidate_id

raise SystemExit(serve(choose=choose, name="my-bot", version="0.1.0"))
```

and adds "No dependencies at all: `examples/minimal_bot.py` is a complete bot in 15 lines of standard-library Python."; "Ratings": "Matchups are seat-swapped game pairs. Each game has its own secret; the run publishes a commitment to its secret before the first game and reveals it afterwards, so every game can be recomputed."; "Benchmarks": the flow `spellbench bench commit`, commit and push the `COMMITMENT.json` and record a third-party timestamp, then `spellbench bench run benchmarks/<id> --run <name> --proof <link> [--placement "<machines considered>"]`; `--unrated` for a local try; the throughput guard (a small run keeps its workers; a substantial one measures worker counts on identical games and needs `--placement`); a rated run pins the engine's files under `SPELLBENCH_PIN_ROOT` and registers them with `SPELLBENCH_ARTIFACT_REGISTER` (both in `benchmarks/local.json`); `bench reveal` and `bench rerun`; "Trust" adds "The host validates every decision (fairness: validator only) and cannot see hidden state; see the spec's section 13."; "Status": "v2: 2-player best-of-one, stdio NDJSON, one decision at a time with authoritative legal candidates, a neutral board view, and live validation. `pauper-kernel`'s board run is protocol v1 until the v2 kernel adapter lands."

- [ ] **Step 5: Run the final checks**

Run: `uv run pytest python/tests -q`
Expected: all pass, no module-level skip left.
Run (when `integrations/` exists): `uv run pytest python/tests integrations -q`
Expected: all pass or skipped.
Run: `uv run python python/tools/generate_goldens_v2.py --check`
Expected: every golden `OK`.
Run: `uv run spellbench validate benchmarks/pauper-kernel/runs/2026-09-26`
Expected: `OK ...`.
Run: `uv run spellbench site benchmarks "<scratch dir>/site-check"`
Expected: `site built: ...`.
Run: `uv run spellbench run examples/quickstart.json` from a scratch copy of the repo, then `uv run spellbench validate out/quickstart`
Expected: a complete unrated run, then `OK out/quickstart: ...`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Protocol v1 removed; v2 docs, CI and version 0.3.0"
```

## Self-Review Notes

- Spec coverage: sections 2 and 4 (Tasks 1, 9, 17, 18), 5 (Tasks 2, 13, 14), 6 (Tasks 8, 13, 15, 16, 26, 27), 7 (Tasks 7, 16, 26), 8 (Tasks 10, 26), 9 (Tasks 9, 18, 21), 10 (Tasks 6, 11, 17), 11.1 (Task 25), 11.2 (Task 23), 11.3 (Tasks 10, 14 to 16, 22, 30, 31, 36), 11.4 (Tasks 3, 29), 11.5 (Tasks 12, 20, 29, 39), 11.6 (Tasks 2, 31, 33, 41), 11.7 (Task 24: a fresh bot per game; verified sandboxes are sub-project D), 11.8 (Tasks 2, 23), 12 (Tasks 19, 25, 31, 37), 13 (Tasks 22, 38), 14 (Tasks 16, 25), 15 (reserved: Task 37 refuses it), 16 (Tasks 2, 34, 35), plus the arena, site, guard and artifact-law requirements (Tasks 4, 5, 33, 36 to 44).
- Out of scope and named for K2 and G: the kernel bridge v2, the kernel bot port, extension audits, the gorge adapter.
