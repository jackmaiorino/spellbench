# gorge Spellbench v2 Adapter (Sub-project G) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the gorge rules engine a Spellbench Protocol v2 engine (environment role over stdio) and wrap gorge's default and lethal-pressure bots as v2 agents, so gorge bots and every other v2 bot can be rated on a five-deck `pauper-gorge` benchmark.

**Architecture:**
- A separate Go module, `engines/gorge` in the Spellbench repository, imports gorge unmodified at a pinned commit.
- The engine runs through `rules.NewHypotheticalPlanned`. Its library-shuffle planner draws from per-seat ChaCha8 streams keyed by the v2 `game_secret`, and its chance prefix forces the host-assigned starting seat, so the adapter follows Section 11.6 with no gorge change.
- Each gorge decision becomes a transaction of v2 decisions. Clone lookahead folds native follow-ups, a Clone+Submit oracle proves every candidate completable, and the real engine only advances when the transaction commits.
- The observation projects `view.Project` (seat visibility) plus engine state, with HMAC per-viewer ids tracked per zone incarnation through a shadow `events.Apply`.
- `x_gorge_view_v1` carries gorge's own view and decision re-keyed to non-native ids for a Go agent around `seat.Bot`.

**Tech Stack:** Go 1.27.1 (module `go 1.25.8`), gorge `26257e0e` (Apache-2.0), Forge corpus `95f04e8a` (GPL-3.0, fetched, never shipped), stdlib only (`crypto/hmac`, `crypto/sha256`, `math/rand/v2` ChaCha8, `encoding/json`).

**Spec:**
- `~\IdeaProjects\spellbench\spec\SPELLBENCH_PROTOCOL_V2.md`, branch `board-program`, commit `7e9e73f`. Annex B describes gorge informatively. Where this plan departs from Annex B, it says why.
- Background: `~\AppData\Local\Temp\claude\C--Users-user-IdeaProjects\157aeb44-0d40-4f26-8ee2-2b800f31ba9e\scratchpad\gorge-adapter-brief.md`.
- Evidence probes: `D:\community\gorge-scratch\probe\cmd\{census5,sourceprobe,plannerprobe,catalogprobe}`, logs in `D:\community\gorge-scratch\logs\`.

## Global Constraints

- **Protocol authority:** `spellbench/v2`, `protocol_minor` 0, frozen at spec commit `7e9e73f`. The environment role is strict (Section 4.2); anything the spec does not license is rejected with its pinned error code, and unrepresentable states end the game `halted` with reason `engine_contract_failure:<cause>`.
- **Where the adapter lives:** a separate Go module at `~\IdeaProjects\spellbench\engines\gorge`, module path `github.com/jackmaiorino/spellbench/engines/gorge`, license MIT (the Spellbench repository license). It requires `github.com/adams-shaun/gorge v0.0.0-20260927030508-26257e0eda17`, resolved locally through a git-ignored `go.work` replace to `D:/community/gorge` (commit `26257e0eda1779d739a07e835c6500b9c4dabc62`). Why not a fork branch of gorge:
  - (a) No engine change is needed. `rules.NewHypotheticalPlanned` (planner per player and ordinal) plus a forced toss gives the Section 11.6 streams, proven by `D:\community\gorge-scratch\probe\cmd\plannerprobe` on 20 live games with zero unplanned draws.
  - (b) The adapter implements the Spellbench spec, so it belongs next to the spec, its goldens and sub-project P's conformance harness.
  - (c) gorge churns daily (6,204 commits, head committed the day of the pin). A pinned import isolates us; the pin moves by a deliberate task.
  - (d) gorge's in-tree process rules (test budgets, dependency order, time-import whitelist, closing approximations register) never apply to our code.
  - (e) The packages are self-contained, so they can later move under `gorge/cmd/` if gorge's maintainer wants to own them.
  - Cost: `internal/policynet` cannot be imported from outside gorge, so the PolicyNet bot needs an exported loader upstream. It is out of scope here.
- **gorge's tree is read-only.** No tracked gorge file is modified and nothing is committed there. gorge's per-package test budgets (`TEST_HISTORY.md` `budget_s`) and dependency-order rules (`internal/archtest`) apply to anything placed inside gorge's tree. This plan places nothing there; the rules bind any later upstream PR.
- **Forge scripts are never shipped.** They are GPL-3.0 and are never vendored, embedded, committed or published. The corpus lives only in `D:\community\gorge\.cards` (gitignored), fetched by `forgec fetch -ref 95f04e8a04c8925fa97cb226fc3341cabcc90a53`. Binaries load it at run time through `-corpus` or `GORGE_CARDS`.
- **Toolchain and caches:** Go 1.27.1 at `D:\tools\go1.27.1\go\bin`, `GOTOOLCHAIN=local`, `CGO_ENABLED=0`, `GOCACHE=D:/community/go-cache/build`, `GOMODCACHE=D:/community/go-cache/mod`. Every command in this plan runs in Git Bash from `~/IdeaProjects/spellbench/engines/gorge` after `source scripts/env.sh`. Builds use no network.
- **Randomness (Section 11.6):**
  - Library shuffle n of seat s uses `rand.New(rand.NewChaCha8(HMAC-SHA256(game_secret, "spellbench/v2/rng:<s>:library_shuffle:<n>")))`, Fisher-Yates over the planner's input.
  - The toss is not random: the chance prefix `{Bound: 2, Value: starting_seat}` forces it.
  - `rules.Config.Seed` is the first 8 bytes of HMAC(game_secret, `"spellbench/v2/rng:shared:gorge_seed:0"`).
  - Any engine draw the planner did not supply halts the game with `engine_contract_failure:unplanned_randomness`.
- **Declared engine profile (hello_ok):**
  - `formats ["pauper-bo1"]`, `deck_sources ["catalog"]`;
  - `rules_supported {"mulligan":["london","none"],"starting_player":["host_assigned"]}`;
  - observation flags true only for `pending_triggers` and `keywords`;
  - `engine_defaults` `{"trigger_order":null,"replacement_order":null,"combat_damage_assignment":"engine_order","mana_payment":null}`: gorge assigns combat damage itself in engine order, and the engine answers gorge's division ask with that rule (Task 16), so `distribute` is never posed;
  - `rewind false`, `fairness {"noninterference_probe":false}`;
  - `extensions [{"name":"x_gorge_view_v1","native_ids":false}]`;
  - `decision_kinds`: the 24 kinds `pass, play_land, cast_spell, activate_mana_ability, activate_ability, special_action, choose_target, finish_target_selection, choose_cost_target, choose_spell_mode, choose_color, choose_number, choose_boolean, choose_name, select_object, finish_selection, optional_cost, optional_cast, mulligan, order_pick, arrange_card, choose_replacement, declare_attack, declare_block`.
- **No text channel.** Every `display_text`, `context.text`, stack `text` and pending-trigger `label` is `null`, so F2's text rule holds by construction.
- **Card names:**
  - Oracle names in NFC, with multi-face cards named `"A // B"` in decklists: `Sagu Wildling // Roost Seek`, `The Modern Age // Vector Glider`.
  - Accented Oracle spellings: `Troll of Khazad-dûm`, `Lórien Revealed`.
  - Deck ids are pinned per deck in Task 7.
- **Fairness (F1 to F4):**
  - Every value sent to a seat is a function of that seat's information state.
  - `x_gorge_view_v1` uses per-seat non-native integer ids derived from v2 ids, so `native_ids` is false.
  - The payload carries no global counters (gorge `Decision.Seq` is replaced), no digests (payment actions dropped), and no hidden order (hidden-zone options sorted by `(card_name, object_id)`).
- **Repository and commits:**
  - Commits go only to the Spellbench repository, on integration branch `gorge-adapter` (created from `board-program`).
  - Parallel tasks use separate worktrees `~\IdeaProjects\spellbench-wt\g<N>` on branches `gorge-adapter-g<N>`, merged into `gorge-adapter` in wave order.
  - Nothing is pushed or published without the maintainer.
- **House rules:** no em-dashes anywhere (code, comments, docs, commits); concise docs; name projects, not people.
- **Compute policy.** Before the rated run (Task 30), apply `~/COMPUTE-POLICY.md`:
  - measure serial and parallel completed games per second on the primary desktop;
  - check compute host and RunPod availability;
  - record the choice in the run manifest;
  - launch only through P's supported host launcher.

## Review Focus

1. **Name normalization.** Decks named with ASCII-folded or NFD names (`Troll of Khazad-dum`, `Lo\u0301rien Revealed`), or a host whose `deck_id` rows use `"A // B"` names, must give `unsupported_deck` or matching ids, never a crash or silent substitution. Pinned in Task 7 (`TestDeckIDsMatchHostComputation`, `TestAsciiFoldedNameIsNotSubstituted`).
2. **Echo equality.** A `step` whose `semantic_echo` has the candidate's fields in another key order, or with nested object references re-serialized, must be accepted; an echo with one extra or one changed field must be `semantic_echo_mismatch`. Pinned in Task 22 (`TestEchoComparesParsedFieldsNotBytes`).
3. **Caps.** A cap that would land inside a fixed group (attack declarations, arrangements) must end the game `truncated` before the group starts, with `decision_count` excluding it. The engine must never interrupt a partial group, which Section 8 forbids for truncation. Pinned in Task 22 (`TestCapNeverSplitsAGroup`).
4. **Retransmission.** A retransmitted `step` after the engine has already answered it returns the cached bytes without advancing, and so does an identical retransmission of an older request of the same game. The same `request_id` with different bytes, including an older id, returns `request_id_reuse_mismatch`. Pinned in Task 23 (`TestRetransmissionIsIdempotentAndReuseFails`).
5. **Canonicalized payloads.** The Go agent must reconstruct gorge types from the host's canonical re-serialization: sorted keys, integers re-printed, extension object reordered. Pinned in Task 26 (`TestAgentDecodesCanonicalizedPayload`).

---

## File Structure

All paths are relative to `~\IdeaProjects\spellbench\engines\gorge` unless absolute.

| Path | Responsibility |
|---|---|
| `go.mod`, `.gitignore`, `NOTICE`, `README.md` | module, pin, license notices, engine notes |
| `scripts/env.sh`, `scripts/setup-dev.sh` | toolchain env; writes `go.work` replace to the local gorge clone |
| `internal/gorgepin/` | pinned gorge commit, compiler fingerprint, corpus lock check, registry open |
| `internal/testcorpus/` | shared test registry (fails when `GORGE_CARDS` is unset) |
| `internal/wire/` | strict JSON check, NDJSON framing, RFC 8785 canonical JSON, deck and domain ids, game digest |
| `internal/secrets/` | Section 11.6 and 5.3 HMAC constructions, streams |
| `internal/protocol/` | v2 message, observation and candidate types, kind field table, request decoding, error codes |
| `internal/catalog/` | the five catalog decks (Oracle names), resolution, preflight, deck ids |
| `internal/gamecfg/` | engine construction, secret-derived shuffles, forced toss, randomness invariant, clone probes |
| `internal/identity/` | zone-incarnation tracker (shadow `events.Apply`), per-viewer ids, looks |
| `internal/observe/` | v2 observation from `view.Project` plus engine state, vocab normalization |
| `internal/mapping/` | transactions: framework, source resolution, oracle, priority, mana, combat, targets, costs, selections, modes, ordering, arrangement, simple choices, payments |
| `internal/session/` | one game: loop, counters, groups, caps, terminals, halts, internal answers; the qualification audit (resample self-check, leak scan, semantic consistency, realized commits) |
| `internal/server/` | environment-role request handling, retransmission cache |
| `internal/xview/` | `x_gorge_view_v1` payload builder, per-seat id tables, hidden-option renumbering |
| `internal/validate/` | Go subset of the live validator (V2 to V9 plus V1 field checks) |
| `internal/minihost/` | in-process v2 host for tests and qualification, Go uniform and first agents |
| `internal/agent/` | agent-role server wrapping gorge bots |
| `cmd/spellbench-gorge-env/` | environment-role binary |
| `cmd/spellbench-gorge-agent/` | agent-role binary (`-policy bot` or `lethal-pressure`) |
| `cmd/gorgequal/` | qualification runner and report |
| `testdata/goldens/*.transcript.jsonl` | engine-specific environment-role goldens |
| `../../benchmarks/pauper-gorge/benchmark.json` | the five-deck benchmark definition |

## Waves, dependencies and effort

Each row is one task of about half a day unless noted. Tasks in one wave run in parallel in separate worktrees and touch disjoint files, except where a row says "then": those tasks run one after another, each merged before the next starts.

| Wave | Tasks (effort, depends on) |
|---|---|
| 0 | T1 scaffold and pin (0.5) |
| 1 | T2 strict JSON and framing (0.5, T1); T3 canonical JSON and digests (0.5, T1); T4 secrets (0.5, T1); T5 v2 types (0.5, T1) |
| 2 | T6 envelope and requests (0.5, T2 T5), T7 catalog (0.5, T1 T3) and T9 validator subset (0.5, T5) in parallel; then T8 game construction (0.5, T4 T7) once T7 is merged |
| 3 | T10 identity (0.5, T4 T8), then T11 observation I (0.5, T5 T10), then T12 observation II (0.5, T11) |
| 4 | T13 mapping framework (0.5, T12), then T14 priority (0.5, T13), then T15 mana abilities (0.5, T14) |
| 5 | T16 combat (0.75, T13 T14); T17 targets and costs (0.5, T13 T14); T18 selections and modes (0.5, T13 T14); T19a ordering (0.5, T13 T14); T19b arrangement (0.75, T13 T14); T20 simple choices (0.5, T13 T14); T21 resolution payments (0.5, T13 T15) |
| 6 | T22 session (0.5, T6 T8 T12 T14 to T21); T24 x_gorge_view_v1 (0.75, T14 to T21) |
| 7 | T23 environment server and binary (0.5, T6 T22 T24) |
| 8 | T25 mini-host and test agents (0.75, T3 T4 T9 T23); T28a qualification audits (0.75, T22 T23 T24) |
| 9 | T26 Go agent (1.0, T23 T24 T25); T27 goldens (0.5, T25) |
| 10 | T28b qualification runner and runs (0.75, T25 T26 T28a) |
| 11 | T29 benchmark and engine notes (0.5, T7 T28b) |
| 12 | T30 integration with sub-project P and rated run (0.75, T29, P deliverables P1 to P4) |

- **Wave 5 dependency on T14:** the wave-5 tests build their games with Task 14's test helpers (`envFor`, `untilPending`, `answerAll`).
- **Effort:** about 18.25 agent-days in total, 17.5 before P's deliverables land.
- **Critical path:** T1, T3, T7, T8, T10, T11, T12, T13, T14, T15, T21, T24, T23, T25, T26, T28b, T29 = 9.75 days of work. T30 (0.75) follows once P lands, about 10.5 days elapsed with enough parallel agents. With three agents, expect 11 to 12 working days.
- **Slack:** T2, T4, T5, T6, T9, T16 to T20 (T19a and T19b included), T22, T27 and T28a.

## What this plan needs from sub-project P

| P deliverable | Used by | Interim without it |
|---|---|---|
| P1 v2 reference host with the live validator (V1 to V10), canonical forwarding, secrets and commitment, clocks, forfeits, digest | T30 rated run, validator verdict | Go mini-host plus validator subset (T9, T25), run in T28b |
| P2 `spellbench-benchmark/v2` schema and loader (rotating pool, rules, time_control, limits, resources, per-game extension enablement) | T29 final validation, T30 | T29 writes the file against the spec fields and a Go shape test |
| P3 v2 builtin bots (uniform anchor, heuristic, first) | T30 ratings | Go `uniform` and `first` test agents (T25) |
| P4 v2 engine conformance harness and `goldens/protocol_v2` envelope and error goldens, replayable by any engine with engine identity masked | T30 conformance | engine-specific Go goldens and error-table tests (T23, T27) |
| P5 host policy: enable `x_gorge_view_v1` only in games where an entry `requires` it (payload about 14 KB per decision) | T30 throughput | enable it in every game (correct, slower) |

## Decisions for the controller

1. **Adapter location.** Recommended: `engines/gorge` inside the Spellbench repository, MIT, pinned import. The alternative is a standalone Apache-2.0 repository, easier to hand to gorge's maintainer.
2. **Unless-cost payment (Chain Lightning copy, Spell Pierce).** gorge asks pay/decline before its mana window, so v2's "`pay: false` is always offered" cannot hold after floating mana inside that window. Recommended: offer `optional_cost` pay:true only when the floating pool already covers the cost, with no activation candidates (7.1 says "may"), and document it. Alternatives: declare `mana_payment: "engine_autopay"` (changes the whole mana model), or ask upstream for a window-first unless flow.
3. **Hybrid pip allocation** (Burning-Tree Emissary's `{R/G}` paid from a pool holding both). v2.0 has no kind for allocating floating mana (`pay_mana` is reserved). Recommended: the engine answers with gorge's first offered option and documents it; alternative: pose `choose_color` with purpose `mana`.
4. **Mulligan rule for `pauper-gorge`.** Section 12.2 says `london` wherever supported, which makes the cross-engine comparison with `pauper-kernel` (`none`) not like for like. Recommended: `london`, per the spec.
5. **Publishing.** Pushing `gorge-adapter`, publishing the benchmark, and offering the adapter to gorge's maintainer are the maintainer's to send.
6. **What "gorge-bot" means on the leaderboard.** Through the adapter the bot sees per-seat ids and name-sorted hidden options (F1), so its games are not byte-identical to native gorge games. Recommended: rate it as `gorge-bot` with that note, and qualify it by intent parity (Task 28b: the adapter commits exactly the move the bot chose). The alternative, native-identical play, would need native ids and engine-ordered hidden options, which F1 rules out.

---

### Task 1: Module scaffold, gorge pin and corpus access

**Files:**
- Create: `go.mod`, `.gitignore`, `NOTICE`
- Create: `scripts/env.sh`, `scripts/setup-dev.sh`
- Create: `internal/gorgepin/pin.go`, `internal/gorgepin/pin_test.go`
- Create: `internal/testcorpus/corpus.go`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `gorgepin.GorgeCommit`, `gorgepin.CompilerFingerprint`, `gorgepin.ForgeRef`, `gorgepin.CorpusDigest` (string constants);
  - `func gorgepin.OpenRegistry(dir string) (*cards.Registry, error)`;
  - `func testcorpus.Dir(t testing.TB) string`;
  - `func testcorpus.Registry(t testing.TB) *cards.Registry`.

- [ ] **Step 1: Create the integration branch and the module files**

```bash
cd /c~/IdeaProjects/spellbench && git switch board-program && git switch -c gorge-adapter
mkdir -p engines/gorge/scripts engines/gorge/internal/gorgepin engines/gorge/internal/testcorpus
```

`engines/gorge/go.mod`:

```
module github.com/jackmaiorino/spellbench/engines/gorge

go 1.25.8

require github.com/adams-shaun/gorge v0.0.0-20260927030508-26257e0eda17
```

`engines/gorge/.gitignore`:

```
go.work
go.work.sum
bin/
```

`engines/gorge/scripts/env.sh`:

```sh
# Source from engines/gorge: toolchain, caches on D:, local gorge and corpus.
export PATH=/d/tools/go1.27.1/go/bin:$PATH
export GOTOOLCHAIN=local CGO_ENABLED=0
export GOCACHE=D:/community/go-cache/build GOMODCACHE=D:/community/go-cache/mod
export GORGE_SRC=${GORGE_SRC:-D:/community/gorge}
export GORGE_CARDS=${GORGE_CARDS:-$GORGE_SRC/.cards}
```

`engines/gorge/scripts/setup-dev.sh`:

```sh
#!/bin/sh
# Writes the git-ignored go.work that resolves gorge to the local pinned clone.
set -eu
want=26257e0eda1779d739a07e835c6500b9c4dabc62
got=$(git -C "$GORGE_SRC" rev-parse HEAD)
[ "$got" = "$want" ] || { echo "gorge at $got, pinned $want" >&2; exit 1; }
cat > go.work <<EOF
go 1.25.8

use .

replace github.com/adams-shaun/gorge => $GORGE_SRC
EOF
echo "go.work -> $GORGE_SRC ($got)"
```

`engines/gorge/NOTICE`:

```
This module imports gorge (https://github.com/adams-shaun/gorge), Apache License 2.0,
at commit 26257e0eda1779d739a07e835c6500b9c4dabc62. Binaries built from this module
include gorge; redistribute them with gorge's LICENSE.

Card behaviour is compiled at run time from Card-Forge/forge card scripts (GPL-3.0),
fetched into a local corpus directory. No Forge script, and no IR compiled from one,
is part of this module or of any binary built from it.
```

- [ ] **Step 2: Write the failing test**

`internal/gorgepin/pin_test.go`:

```go
package gorgepin_test

import (
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

func TestLinkedGorgeIsThePinnedCompiler(t *testing.T) {
	if cards.CompilerFingerprint != gorgepin.CompilerFingerprint {
		t.Fatalf("linked gorge compiler %s, pinned %s", cards.CompilerFingerprint, gorgepin.CompilerFingerprint)
	}
}

func TestOpenRegistryChecksTheCorpusLock(t *testing.T) {
	reg, err := gorgepin.OpenRegistry(testcorpus.Dir(t))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := reg.Lookup("Lightning Bolt"); !ok {
		t.Fatal("Lightning Bolt is not in the pinned corpus")
	}
	if _, err := gorgepin.OpenRegistry(t.TempDir()); err == nil {
		t.Fatal("a directory without cards.lock was accepted")
	}
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd engines/gorge && source scripts/env.sh && sh scripts/setup-dev.sh && go test ./internal/gorgepin/`
Expected: FAIL with `no non-test Go files` or `undefined: gorgepin.OpenRegistry`.

- [ ] **Step 4: Write minimal implementation**

`internal/gorgepin/pin.go`:

```go
// Package gorgepin pins the gorge build and the Forge corpus this adapter was
// qualified against. A different build or corpus is a different engine identity.
package gorgepin

import (
	"fmt"

	"github.com/adams-shaun/gorge/cards"
	// rules registers its non-API primitives with effects.Supported; without
	// this import coverage checks undercount (see gorge cmd/forgec).
	_ "github.com/adams-shaun/gorge/rules"
)

const (
	GorgeCommit         = "26257e0eda1779d739a07e835c6500b9c4dabc62"
	CompilerFingerprint = "4e081d8104fbe09256edb9fa696ce6f7"
	ForgeRef            = "95f04e8a04c8925fa97cb226fc3341cabcc90a53"
	CorpusDigest        = "377204728a927366bab4cc40bf89a64544bd5bf464d66d261e58e1a71b69bf5f"
)

// OpenRegistry opens dir's compiled corpus after checking that the linked gorge
// compiler and the fetched corpus are the pinned ones.
func OpenRegistry(dir string) (*cards.Registry, error) {
	if cards.CompilerFingerprint != CompilerFingerprint {
		return nil, fmt.Errorf("gorge compiler %s is not the pinned %s", cards.CompilerFingerprint, CompilerFingerprint)
	}
	lock, err := cards.ReadLock(dir)
	if err != nil {
		return nil, fmt.Errorf("corpus lock in %s: %w", dir, err)
	}
	if lock.Commit != ForgeRef || lock.Digest != CorpusDigest {
		return nil, fmt.Errorf("corpus %s/%s is not the pinned %s/%s", lock.Commit, lock.Digest, ForgeRef, CorpusDigest)
	}
	return cards.OpenCorpus(dir)
}
```

`internal/testcorpus/corpus.go`:

```go
// Package testcorpus shares one pinned registry across a test binary. Tests
// fail, never skip, when the corpus is missing: a skipped engine test is a
// silent coverage hole.
package testcorpus

import (
	"os"
	"sync"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
)

var (
	once sync.Once
	reg  *cards.Registry
	err  error
)

func Dir(t testing.TB) string {
	t.Helper()
	d := os.Getenv("GORGE_CARDS")
	if d == "" {
		t.Fatal("GORGE_CARDS is not set: source scripts/env.sh")
	}
	return d
}

func Registry(t testing.TB) *cards.Registry {
	t.Helper()
	dir := Dir(t)
	once.Do(func() { reg, err = gorgepin.OpenRegistry(dir) })
	if err != nil {
		t.Fatal(err)
	}
	return reg
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `go test ./internal/gorgepin/ -v`
Expected: `--- PASS: TestLinkedGorgeIsThePinnedCompiler`, `--- PASS: TestOpenRegistryChecksTheCorpusLock`, `ok  	github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin`.

- [ ] **Step 6: Commit**

```bash
git add engines/gorge && git commit -m "gorge adapter: module scaffold, gorge pin and corpus check"
```

---

### Task 2: Strict JSON and NDJSON framing

**Files:**
- Create: `internal/wire/strict.go`, `internal/wire/frame.go`
- Test: `internal/wire/strict_test.go`, `internal/wire/frame_test.go`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `const wire.MaxLineBytes = 8 << 20`, `wire.MaxDepth = 64`, `wire.MaxInt int64 = 1<<53 - 1`;
  - `type wire.StrictError struct{ Code, Msg string }`, with codes `wire.CodeMalformedJSON = "malformed_json"` and `wire.CodeNotObject = "malformed_request"`;
  - `func wire.CheckStrict(b []byte) error` (top level must be an object);
  - `func wire.CheckStrictAny(b []byte) error` (any top-level value);
  - `var wire.ErrLineTooLong`;
  - `type wire.Reader` with `func wire.NewReader(io.Reader) *Reader` and `func (*Reader) ReadLine() ([]byte, error)`;
  - `func wire.WriteLine(w io.Writer, v any) error`.

- [ ] **Step 1: Write the failing tests**

`internal/wire/strict_test.go`:

```go
package wire_test

import (
	"errors"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func nest(n int) string { return strings.Repeat(`{"a":`, n) + `1` + strings.Repeat(`}`, n) }

func TestCheckStrictRejectsWhatSection2Forbids(t *testing.T) {
	bad := map[string]string{
		`{"a":1,"a":2}`:            "duplicate key",
		`{"a":1.0}`:                "fraction",
		`{"a":1e3}`:                "exponent",
		`{"a":9007199254740992}`:   "above 2^53-1",
		`{"a":-9007199254740992}`:  "below -(2^53-1)",
		`{"a":"\ud800"}`:           "unpaired high surrogate",
		`{"a":"\udc00"}`:           "unpaired low surrogate",
		`{"a":01}`:                 "leading zero",
		nest(65):                   "65 levels",
		"{\"a\":\"\xff\"}":         "invalid UTF-8",
		`{"a":1} x`:                "trailing data",
	}
	for in, why := range bad {
		if err := wire.CheckStrict([]byte(in)); err == nil {
			t.Errorf("%s accepted (%s)", in, why)
		}
	}
	good := []string{
		`{"a":9007199254740991,"b":-9007199254740991,"c":"\ud83d\ude00","d":[{"e":null,"f":true}]}`,
		nest(64),
		" {\"a\":\"Lim-D\u00fbl's Vault\"}\r",
	}
	for _, in := range good {
		if err := wire.CheckStrict([]byte(in)); err != nil {
			t.Errorf("%s rejected: %v", in, err)
		}
	}
}

func TestCheckStrictClassifiesTopLevel(t *testing.T) {
	var se *wire.StrictError
	if err := wire.CheckStrict([]byte(`[1]`)); !errors.As(err, &se) || se.Code != wire.CodeNotObject {
		t.Fatalf("array top level: %v", err)
	}
	if err := wire.CheckStrict([]byte(`{"a":`)); !errors.As(err, &se) || se.Code != wire.CodeMalformedJSON {
		t.Fatalf("truncated object: %v", err)
	}
	if err := wire.CheckStrictAny([]byte(`[{"count":4,"name":"Lightning Bolt"}]`)); err != nil {
		t.Fatalf("CheckStrictAny rejected an array: %v", err)
	}
}
```

`internal/wire/frame_test.go`:

```go
package wire_test

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func TestReaderAcceptsEightMiBAndResyncsAfterALongerLine(t *testing.T) {
	exact := `{"p":"` + strings.Repeat("x", wire.MaxLineBytes-8) + `"}`
	over := exact + " "
	in := exact + "\n" + over + "\r\n" + `{"ok":1}` + "\r\n"
	r := wire.NewReader(strings.NewReader(in))
	if line, err := r.ReadLine(); err != nil || len(line) != wire.MaxLineBytes {
		t.Fatalf("8 MiB line: len %d err %v", len(line), err)
	}
	if _, err := r.ReadLine(); !errors.Is(err, wire.ErrLineTooLong) {
		t.Fatalf("longer line: %v", err)
	}
	if line, err := r.ReadLine(); err != nil || string(line) != `{"ok":1}` {
		t.Fatalf("resync: %q %v", line, err)
	}
	if _, err := r.ReadLine(); err != io.EOF {
		t.Fatalf("end: %v", err)
	}
}

func TestWriteLineIsOneCompactLine(t *testing.T) {
	var b bytes.Buffer
	if err := wire.WriteLine(&b, map[string]any{"a": "<&>", "b": 1}); err != nil {
		t.Fatal(err)
	}
	if b.String() != "{\"a\":\"<&>\",\"b\":1}\n" {
		t.Fatalf("got %q", b.String())
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/wire/`
Expected: FAIL with `undefined: wire.CheckStrict` (and the other missing names).

- [ ] **Step 3: Write minimal implementation**

`internal/wire/strict.go`:

```go
// Package wire holds the transport rules of Spellbench v2 Section 2 and the
// canonical JSON of Section 4.3.
package wire

import (
	"fmt"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const (
	MaxDepth          = 64
	MaxInt            = int64(1)<<53 - 1
	CodeMalformedJSON = "malformed_json"
	CodeNotObject     = "malformed_request"
)

// StrictError carries the v2 error code a receiver answers with.
type StrictError struct{ Code, Msg string }

func (e *StrictError) Error() string { return e.Code + ": " + e.Msg }

func bad(format string, a ...any) error {
	return &StrictError{Code: CodeMalformedJSON, Msg: fmt.Sprintf(format, a...)}
}

// CheckStrict validates one request line: strict JSON whose top level is an object.
func CheckStrict(b []byte) error {
	if err := CheckStrictAny(b); err != nil {
		return err
	}
	p := &parser{b: b}
	p.ws()
	if p.b[p.i] != '{' {
		return &StrictError{Code: CodeNotObject, Msg: "top-level value is not an object"}
	}
	return nil
}

// CheckStrictAny validates strict JSON with any top-level value.
func CheckStrictAny(b []byte) error {
	if !utf8.Valid(b) {
		return bad("invalid UTF-8")
	}
	p := &parser{b: b}
	if err := p.value(0); err != nil {
		return err
	}
	p.ws()
	if p.i != len(p.b) {
		return bad("trailing data at byte %d", p.i)
	}
	return nil
}

type parser struct {
	b []byte
	i int
}

func (p *parser) ws() {
	for p.i < len(p.b) && strings.IndexByte(" \t\n\r", p.b[p.i]) >= 0 {
		p.i++
	}
}

func (p *parser) lit(s string) bool {
	if strings.HasPrefix(string(p.b[p.i:min(len(p.b), p.i+len(s))]), s) {
		p.i += len(s)
		return true
	}
	return false
}

func (p *parser) value(depth int) error {
	p.ws()
	if p.i >= len(p.b) {
		return bad("unexpected end of input")
	}
	switch c := p.b[p.i]; {
	case c == '{':
		return p.object(depth + 1)
	case c == '[':
		return p.array(depth + 1)
	case c == '"':
		_, err := p.str()
		return err
	case c == '-' || (c >= '0' && c <= '9'):
		return p.number()
	case p.lit("true"), p.lit("false"), p.lit("null"):
		return nil
	default:
		return bad("unexpected byte %q at %d", c, p.i)
	}
}

func (p *parser) object(depth int) error {
	if depth > MaxDepth {
		return bad("nesting deeper than %d levels", MaxDepth)
	}
	p.i++
	seen := map[string]bool{}
	p.ws()
	if p.i < len(p.b) && p.b[p.i] == '}' {
		p.i++
		return nil
	}
	for {
		p.ws()
		if p.i >= len(p.b) || p.b[p.i] != '"' {
			return bad("expected a key at %d", p.i)
		}
		k, err := p.str()
		if err != nil {
			return err
		}
		if seen[k] {
			return bad("duplicate key %q", k)
		}
		seen[k] = true
		p.ws()
		if p.i >= len(p.b) || p.b[p.i] != ':' {
			return bad("expected ':' at %d", p.i)
		}
		p.i++
		if err := p.value(depth); err != nil {
			return err
		}
		p.ws()
		if p.i >= len(p.b) {
			return bad("unterminated object")
		}
		switch p.b[p.i] {
		case ',':
			p.i++
		case '}':
			p.i++
			return nil
		default:
			return bad("expected ',' or '}' at %d", p.i)
		}
	}
}

func (p *parser) array(depth int) error {
	if depth > MaxDepth {
		return bad("nesting deeper than %d levels", MaxDepth)
	}
	p.i++
	p.ws()
	if p.i < len(p.b) && p.b[p.i] == ']' {
		p.i++
		return nil
	}
	for {
		if err := p.value(depth); err != nil {
			return err
		}
		p.ws()
		if p.i >= len(p.b) {
			return bad("unterminated array")
		}
		switch p.b[p.i] {
		case ',':
			p.i++
		case ']':
			p.i++
			return nil
		default:
			return bad("expected ',' or ']' at %d", p.i)
		}
	}
}

func (p *parser) hex4() (rune, error) {
	if p.i+4 > len(p.b) {
		return 0, bad("short \\u escape")
	}
	v, err := strconv.ParseUint(string(p.b[p.i:p.i+4]), 16, 32)
	if err != nil {
		return 0, bad("bad \\u escape")
	}
	p.i += 4
	return rune(v), nil
}

// str parses a string and returns its decoded value (for duplicate-key checks).
func (p *parser) str() (string, error) {
	p.i++
	var sb strings.Builder
	for p.i < len(p.b) {
		c := p.b[p.i]
		switch {
		case c == '"':
			p.i++
			return sb.String(), nil
		case c < 0x20:
			return "", bad("control character in string")
		case c == '\\':
			if p.i+1 >= len(p.b) {
				return "", bad("unterminated escape")
			}
			e := p.b[p.i+1]
			p.i += 2
			switch e {
			case '"', '\\', '/':
				sb.WriteByte(e)
			case 'b':
				sb.WriteByte('\b')
			case 'f':
				sb.WriteByte('\f')
			case 'n':
				sb.WriteByte('\n')
			case 'r':
				sb.WriteByte('\r')
			case 't':
				sb.WriteByte('\t')
			case 'u':
				r, err := p.hex4()
				if err != nil {
					return "", err
				}
				if utf16.IsSurrogate(r) {
					if r >= 0xDC00 || p.i+2 > len(p.b) || p.b[p.i] != '\\' || p.b[p.i+1] != 'u' {
						return "", bad("unpaired surrogate escape")
					}
					p.i += 2
					r2, err := p.hex4()
					if err != nil {
						return "", err
					}
					if r2 < 0xDC00 || r2 > 0xDFFF {
						return "", bad("unpaired surrogate escape")
					}
					r = utf16.DecodeRune(r, r2)
				}
				sb.WriteRune(r)
			default:
				return "", bad("bad escape \\%c", e)
			}
		default:
			sb.WriteByte(c)
			p.i++
		}
	}
	return "", bad("unterminated string")
}

func (p *parser) number() error {
	start := p.i
	if p.b[p.i] == '-' {
		p.i++
	}
	if p.i >= len(p.b) || p.b[p.i] < '0' || p.b[p.i] > '9' {
		return bad("bad number at %d", start)
	}
	if p.b[p.i] == '0' && p.i+1 < len(p.b) && p.b[p.i+1] >= '0' && p.b[p.i+1] <= '9' {
		return bad("leading zero at %d", start)
	}
	for p.i < len(p.b) && p.b[p.i] >= '0' && p.b[p.i] <= '9' {
		p.i++
	}
	if p.i < len(p.b) && strings.IndexByte(".eE", p.b[p.i]) >= 0 {
		return bad("number with a fraction or an exponent at %d", start)
	}
	n, err := strconv.ParseInt(string(p.b[start:p.i]), 10, 64)
	if err != nil || n > MaxInt || n < -MaxInt {
		return bad("integer outside |x| <= 2^53-1 at %d", start)
	}
	return nil
}
```

`internal/wire/frame.go`:

```go
package wire

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
)

// MaxLineBytes is Section 2's line bound, excluding the terminator.
const MaxLineBytes = 8 << 20

var ErrLineTooLong = errors.New("line exceeds 8 MiB")

type Reader struct{ r *bufio.Reader }

func NewReader(r io.Reader) *Reader { return &Reader{r: bufio.NewReaderSize(r, 64<<10)} }

// ReadLine returns the next line without "\n" or "\r\n". A longer line is
// drained through its newline and reported as ErrLineTooLong, so framing
// resynchronizes on the next line.
func (r *Reader) ReadLine() ([]byte, error) {
	var line []byte
	tooLong := false
	for {
		chunk, err := r.r.ReadSlice('\n')
		if !tooLong {
			line = append(line, chunk...)
			if len(bytes.TrimRight(line, "\r\n")) > MaxLineBytes {
				tooLong, line = true, nil
			}
		}
		switch {
		case errors.Is(err, bufio.ErrBufferFull):
			continue
		case errors.Is(err, io.EOF):
			if tooLong {
				return nil, ErrLineTooLong
			}
			if len(line) == 0 {
				return nil, io.EOF
			}
			return nil, io.ErrUnexpectedEOF
		case err != nil:
			return nil, err
		}
		if tooLong {
			return nil, ErrLineTooLong
		}
		line = bytes.TrimSuffix(line, []byte("\n"))
		return bytes.TrimSuffix(line, []byte("\r")), nil
	}
}

// WriteLine writes v as one compact JSON line (HTML escaping off).
func WriteLine(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	return enc.Encode(v)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/wire/ -v`
Expected: `--- PASS` for all four tests; `ok  	github.com/jackmaiorino/spellbench/engines/gorge/internal/wire`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/wire && git commit -m "gorge adapter: strict JSON check and NDJSON framing"
```

---

### Task 3: Canonical JSON, deck and domain ids, game digest

**Files:**
- Create: `internal/wire/canonical.go`, `internal/wire/digest.go`
- Test: `internal/wire/canonical_test.go`

**Interfaces:**
- Consumes: `wire.CheckStrictAny` (Task 2). If Task 2 is not merged yet, this task's worktree cherry-picks it first.
- Produces:
  - `func wire.CanonicalBytes(raw []byte) ([]byte, error)`, `func wire.Canonical(v any) ([]byte, error)`;
  - `type wire.DeckRow struct{ Name string; Count int }` (JSON `name`, `count`), `func wire.DeckID(rows []DeckRow) (string, error)`, `func wire.DomainID(names []string) (string, error)` (Steps 1 to 5 return the id alone; the wire follow-up of Step 6 makes both refuse a repeated name);
  - `func wire.WithoutRequestID(msg []byte) ([]byte, error)` (strict after Step 6: it runs `CheckStrict` first);
  - `type wire.GameDigest` with `func wire.NewGameDigest(resetMinusID []byte) (*GameDigest, error)`, `func (*GameDigest) Chain(msgMinusID []byte) error` and `func (*GameDigest) String() string`.

- [ ] **Step 1: Write the failing test (spec Section 16 vectors)**

`internal/wire/canonical_test.go`:

```go
package wire_test

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func TestCanonicalMatchesSpecVector(t *testing.T) {
	in := []byte("{\"b\":\"Chainer's Edict\",\"a\":\"Lim-D\\u00fbl's Vault\",\"c\":\"tab\\there\"}")
	out, err := wire.CanonicalBytes(in)
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != "{\"a\":\"Lim-D\u00fbl's Vault\",\"b\":\"Chainer's Edict\",\"c\":\"tab\\there\"}" {
		t.Fatalf("canonical %s", out)
	}
	sum := sha256.Sum256(out)
	if got := hex.EncodeToString(sum[:]); got != "041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377" {
		t.Fatalf("sha256 %s", got)
	}
}

func TestDeckAndDomainIDVectors(t *testing.T) {
	id := wire.DeckID([]wire.DeckRow{{Name: "Mountain", Count: 18}, {Name: "Lightning Bolt", Count: 4}})
	if id != "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2" {
		t.Fatalf("deck_id %s", id)
	}
	dom := wire.DomainID([]string{"Mountain", "Lightning Bolt"})
	if dom != "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697" {
		t.Fatalf("domain_id %s", dom)
	}
}

const specReset = `{"request_type":"reset","protocol":"spellbench/v2","request_id":"h-2","game_id":"g-f67d7fe78c792984","format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":"sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2","catalog_id":"Burn"}},{"seat":"p1","deck":{"deck_id":"sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2","catalog_id":"Burn"}}],"rules":{"opponent_decklist":"visible","mulligan":"none","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":"sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697","names":["Lightning Bolt","Mountain"]},"extensions":[],"probe":false},"game_secret":"7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e","max_decisions":10000,"max_steps":100000}`

func TestGameDigestFirstLinkVector(t *testing.T) {
	msg, err := wire.WithoutRequestID([]byte(specReset))
	if err != nil {
		t.Fatal(err)
	}
	d, err := wire.NewGameDigest(msg)
	if err != nil {
		t.Fatal(err)
	}
	if got := d.String(); got != "sha256:a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3" {
		t.Fatalf("first chain value %s", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/wire/ -run 'Canonical|DeckAndDomain|GameDigest'`
Expected: FAIL with `undefined: wire.CanonicalBytes`.

- [ ] **Step 3: Write minimal implementation**

`internal/wire/canonical.go`:

```go
package wire

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"unicode/utf16"
)

// CanonicalBytes re-serializes strict JSON per RFC 8785 for integer-only data.
func CanonicalBytes(raw []byte) ([]byte, error) {
	if err := CheckStrictAny(raw); err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	if err := writeCanon(&buf, v); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// Canonical marshals v (HTML escaping off) and canonicalizes the result.
func Canonical(v any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return CanonicalBytes(bytes.TrimSuffix(b.Bytes(), []byte("\n")))
}

func utf16Less(a, b string) bool {
	x, y := utf16.Encode([]rune(a)), utf16.Encode([]rune(b))
	for i := 0; i < len(x) && i < len(y); i++ {
		if x[i] != y[i] {
			return x[i] < y[i]
		}
	}
	return len(x) < len(y)
}

func writeCanon(buf *bytes.Buffer, v any) error {
	switch t := v.(type) {
	case nil:
		buf.WriteString("null")
	case bool:
		buf.WriteString(strconv.FormatBool(t))
	case json.Number:
		n, err := strconv.ParseInt(string(t), 10, 64)
		if err != nil {
			return fmt.Errorf("non-integer number %s", t)
		}
		buf.WriteString(strconv.FormatInt(n, 10))
	case string:
		writeString(buf, t)
	case []any:
		buf.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeCanon(buf, e); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Slice(keys, func(i, j int) bool { return utf16Less(keys[i], keys[j]) })
		buf.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			writeString(buf, k)
			buf.WriteByte(':')
			if err := writeCanon(buf, t[k]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		return fmt.Errorf("unexpected JSON value %T", v)
	}
	return nil
}

func writeString(buf *bytes.Buffer, s string) {
	buf.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			buf.WriteString(`\"`)
		case '\\':
			buf.WriteString(`\\`)
		case '\b':
			buf.WriteString(`\b`)
		case '\f':
			buf.WriteString(`\f`)
		case '\n':
			buf.WriteString(`\n`)
		case '\r':
			buf.WriteString(`\r`)
		case '\t':
			buf.WriteString(`\t`)
		default:
			if r < 0x20 {
				fmt.Fprintf(buf, `\u%04x`, r)
			} else {
				buf.WriteRune(r)
			}
		}
	}
	buf.WriteByte('"')
}

// DeckRow is one decklist row.
type DeckRow struct {
	Name  string `json:"name"`
	Count int    `json:"count"`
}

func sha(b []byte) string {
	s := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(s[:])
}

// DeckID is Section 4.3's deck_id: rows sorted by name in code point order
// (UTF-8 byte order equals code point order), canonical, SHA-256.
func DeckID(rows []DeckRow) string {
	s := append([]DeckRow(nil), rows...)
	sort.Slice(s, func(i, j int) bool { return s[i].Name < s[j].Name })
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, r := range s {
		if i > 0 {
			buf.WriteByte(',')
		}
		buf.WriteString(`{"count":` + strconv.Itoa(r.Count) + `,"name":`)
		writeString(&buf, r.Name)
		buf.WriteByte('}')
	}
	buf.WriteByte(']')
	return sha(buf.Bytes())
}

// DomainID is card_name_domain.domain_id: the names sorted, canonical, SHA-256.
func DomainID(names []string) string {
	s := append([]string(nil), names...)
	sort.Strings(s)
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, n := range s {
		if i > 0 {
			buf.WriteByte(',')
		}
		writeString(&buf, n)
	}
	buf.WriteByte(']')
	return sha(buf.Bytes())
}
```

`internal/wire/digest.go`:

```go
package wire

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

// WithoutRequestID removes the top-level request_id before digesting (Section 11.8).
func WithoutRequestID(msg []byte) ([]byte, error) {
	dec := json.NewDecoder(bytes.NewReader(msg))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		return nil, err
	}
	delete(m, "request_id")
	return Canonical(m)
}

// GameDigest is the Section 11.8 chain.
type GameDigest struct{ d [32]byte }

func NewGameDigest(resetMinusID []byte) (*GameDigest, error) {
	c, err := CanonicalBytes(resetMinusID)
	if err != nil {
		return nil, err
	}
	h := sha256.New()
	h.Write([]byte("spellbench/v2/game-digest"))
	h.Write(c)
	g := &GameDigest{}
	copy(g.d[:], h.Sum(nil))
	return g, nil
}

func (g *GameDigest) Chain(msgMinusID []byte) error {
	c, err := CanonicalBytes(msgMinusID)
	if err != nil {
		return err
	}
	h := sha256.New()
	h.Write(g.d[:])
	h.Write(c)
	copy(g.d[:], h.Sum(nil))
	return nil
}

func (g *GameDigest) String() string { return "sha256:" + hex.EncodeToString(g.d[:]) }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/wire/ -v`
Expected: all wire tests PASS, including `TestCanonicalMatchesSpecVector`, `TestDeckAndDomainIDVectors`, `TestGameDigestFirstLinkVector`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/wire && git commit -m "gorge adapter: RFC 8785 canonical JSON, deck and domain ids, game digest"
```

- [ ] **Step 6: Wire follow-up (strict digest input, repeated names refused)**

Applied in the wire follow-up, a task outside this plan's numbering that runs after Tasks 2 and 3 are merged (G1-7 needs Task 2's `CheckStrict`).
- `WithoutRequestID` runs `CheckStrict` first, so a duplicate key or trailing data is an error instead of being dropped before the digest (Sections 2 and 11.8).
- `DeckID` and `DomainID` refuse a repeated name with an error, as P's reference host does: Section 4.3 computes both over distinct names. Tasks 7, 23 and 25 take the error.

Replace or add these declarations in `internal/wire/canonical_test.go`:

```go
func TestDeckAndDomainIDVectors(t *testing.T) {
	id, err := wire.DeckID([]wire.DeckRow{{Name: "Mountain", Count: 18}, {Name: "Lightning Bolt", Count: 4}})
	if err != nil || id != "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2" {
		t.Fatalf("deck_id %s %v", id, err)
	}
	dom, err := wire.DomainID([]string{"Mountain", "Lightning Bolt"})
	if err != nil || dom != "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697" {
		t.Fatalf("domain_id %s %v", dom, err)
	}
}

// The wire follow-up: repeated names are refused (P's reference host does the
// same), and a message with a duplicate key or trailing data is never digested.
func TestRepeatedNamesAreRefused(t *testing.T) {
	rows := []wire.DeckRow{{Name: "Mountain", Count: 9}, {Name: "Lightning Bolt", Count: 4}, {Name: "Mountain", Count: 9}}
	if id, err := wire.DeckID(rows); err == nil {
		t.Fatalf("deck_id merged a repeated name: %s", id)
	}
	if id, err := wire.DomainID([]string{"Mountain", "Lightning Bolt", "Mountain"}); err == nil {
		t.Fatalf("domain_id merged a repeated name: %s", id)
	}
}

func TestWithoutRequestIDIsStrict(t *testing.T) {
	for _, in := range []string{`{"request_id":"a","b":1,"b":2}`, `{"request_id":"a"} {}`, `[1]`, `{"a":1.5}`} {
		if out, err := wire.WithoutRequestID([]byte(in)); err == nil {
			t.Errorf("%s accepted as %s", in, out)
		}
	}
}
```

Run: `go test ./internal/wire/ -run 'DeckAndDomain|Repeated|WithoutRequestID'`
Expected: FAIL to compile: `assignment mismatch: 2 variables but wire.DeckID returns 1 value`.

Replace or add these declarations in `internal/wire/canonical.go`:

```go
// DeckID is Section 4.3's deck_id: one row per distinct name, sorted by name
// in code point order (UTF-8 byte order equals code point order), canonical,
// SHA-256. A repeated name is refused, never merged.
func DeckID(rows []DeckRow) (string, error) {
	s := append([]DeckRow(nil), rows...)
	sort.Slice(s, func(i, j int) bool { return s[i].Name < s[j].Name })
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, r := range s {
		if i > 0 {
			if s[i-1].Name == r.Name {
				return "", fmt.Errorf("card name %q appears twice", r.Name)
			}
			buf.WriteByte(',')
		}
		buf.WriteString(`{"count":` + strconv.Itoa(r.Count) + `,"name":`)
		writeString(&buf, r.Name)
		buf.WriteByte('}')
	}
	buf.WriteByte(']')
	return sha(buf.Bytes()), nil
}

// DomainID is card_name_domain.domain_id: the distinct names sorted,
// canonical, SHA-256. A repeated name is refused, never merged.
func DomainID(names []string) (string, error) {
	s := append([]string(nil), names...)
	sort.Strings(s)
	var buf bytes.Buffer
	buf.WriteByte('[')
	for i, n := range s {
		if i > 0 {
			if s[i-1] == n {
				return "", fmt.Errorf("card name %q appears twice", n)
			}
			buf.WriteByte(',')
		}
		writeString(&buf, n)
	}
	buf.WriteByte(']')
	return sha(buf.Bytes()), nil
}
```

Replace or add these declarations in `internal/wire/digest.go`:

```go
// WithoutRequestID removes the top-level request_id before digesting (Section
// 11.8). The message must be strict JSON (Section 2): a duplicate key or
// trailing data is an error, never silently dropped.
func WithoutRequestID(msg []byte) ([]byte, error) {
	if err := CheckStrict(msg); err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(msg))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		return nil, err
	}
	delete(m, "request_id")
	return Canonical(m)
}
```

Run: `go test ./internal/wire/ -v`
Expected: every wire test PASS, including `TestRepeatedNamesAreRefused` and `TestWithoutRequestIDIsStrict`.

```bash
git add engines/gorge/internal/wire && git commit -m "gorge adapter: strict WithoutRequestID; deck and domain ids refuse repeated names"
```

---

### Task 4: Secrets and identifier constructions

**Files:**
- Create: `internal/secrets/secrets.go`
- Test: `internal/secrets/secrets_test.go`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - host-side: `func secrets.Commitment(run []byte) string`, `func secrets.GameSecret(run []byte, i uint64) []byte`, `func secrets.GameID(run []byte, i uint64) string`, `func secrets.AgentSeed(run []byte, i uint64, seat string) uint64`;
  - engine-side: `type secrets.Game` with `func secrets.ParseGame(hex64 string) (*Game, error)` and `func secrets.NewGame(secret []byte) *Game`;
  - on `*Game`: `ObjectID(msg string) string`, `IDKeyHex() string`, `StreamSeed(owner, purpose string, n uint64) [32]byte`, `Stream(owner, purpose string, n uint64) *rand.Rand`.

- [ ] **Step 1: Write the failing test**

`internal/secrets/secrets_test.go`:

```go
package secrets_test

import (
	"encoding/hex"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

func runSecret() []byte {
	b := make([]byte, 32)
	for i := range b {
		b[i] = byte(i)
	}
	return b
}

func TestHostVectors(t *testing.T) {
	run := runSecret()
	check := func(name, got, want string) {
		t.Helper()
		if got != want {
			t.Errorf("%s = %s, want %s", name, got, want)
		}
	}
	check("commitment", secrets.Commitment(run), "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd")
	check("game_secret(0)", hex.EncodeToString(secrets.GameSecret(run, 0)), "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e")
	check("game_secret(1)", hex.EncodeToString(secrets.GameSecret(run, 1)), "952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e")
	check("game_id(0)", secrets.GameID(run, 0), "g-f67d7fe78c792984")
	check("game_id(1)", secrets.GameID(run, 1), "g-bb341404cf686511")
	seeds := map[[2]any]uint64{{uint64(0), "p0"}: 8103969398531465, {uint64(0), "p1"}: 1382627979884484,
		{uint64(1), "p0"}: 4616060983342951, {uint64(1), "p1"}: 7705961899067306}
	for k, want := range seeds {
		if got := secrets.AgentSeed(run, k[0].(uint64), k[1].(string)); got != want {
			t.Errorf("agent_seed%v = %d, want %d", k, got, want)
		}
	}
}

func TestEngineVectors(t *testing.T) {
	g, err := secrets.ParseGame("7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e")
	if err != nil {
		t.Fatal(err)
	}
	if g.IDKeyHex() != "842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6" {
		t.Fatalf("id_key %s", g.IDKeyHex())
	}
	for msg, want := range map[string]string{
		"p0:card-17:z2":        "o-0a3647243d16bf78",
		"p1:card-17:z2":        "o-e5e4b7ed2a0730e4",
		"p0:card-17:z2:look:0": "o-794a5cb152c9620f",
		"p0:card-17:z2:look:1": "o-e18a35822cc60e1c",
	} {
		if got := g.ObjectID(msg); got != want {
			t.Errorf("object id %q = %s, want %s", msg, got, want)
		}
	}
	seed := g.StreamSeed("p1", "library_shuffle", 0)
	if hex.EncodeToString(seed[:8]) != "8a28fd4db75719b1" {
		t.Fatalf("stream seed %x", seed[:8])
	}
	if _, err := secrets.ParseGame("7648831B4AE4148770E13149D5EBBE1C4991168413D4B38E49292CFC5538980E"); err == nil {
		t.Fatal("uppercase secret accepted")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/secrets/`
Expected: FAIL with `undefined: secrets.Commitment`.

- [ ] **Step 3: Write minimal implementation**

`internal/secrets/secrets.go`:

```go
// Package secrets implements the HMAC constructions of Spellbench v2
// Sections 5.3 and 11.6. Nothing computed from a game secret reaches an agent.
package secrets

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math/rand/v2"
	"regexp"
	"strconv"
)

func mac(key []byte, msg string) []byte {
	h := hmac.New(sha256.New, key)
	h.Write([]byte(msg))
	return h.Sum(nil)
}

func dec(i uint64) string { return strconv.FormatUint(i, 10) }

func Commitment(run []byte) string {
	s := sha256.Sum256(run)
	return hex.EncodeToString(s[:])
}

func GameSecret(run []byte, i uint64) []byte { return mac(run, "spellbench/v2/game:"+dec(i)) }

func GameID(run []byte, i uint64) string {
	return "g-" + hex.EncodeToString(mac(run, "spellbench/v2/game-id:"+dec(i))[:8])
}

func AgentSeed(run []byte, i uint64, seat string) uint64 {
	b := mac(run, "spellbench/v2/agent-seed:"+dec(i)+":"+seat)
	return binary.BigEndian.Uint64(b[:8]) & (1<<53 - 1)
}

// Game holds one game's secret and derived id key. Engine-internal only.
type Game struct {
	secret []byte
	idKey  []byte
}

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

func ParseGame(s string) (*Game, error) {
	if !hex64.MatchString(s) {
		return nil, fmt.Errorf("game_secret is not 64 lowercase hex characters")
	}
	b, _ := hex.DecodeString(s)
	return NewGame(b), nil
}

func NewGame(secret []byte) *Game {
	return &Game{secret: append([]byte(nil), secret...), idKey: mac(secret, "spellbench/v2/object-id")}
}

func (g *Game) IDKeyHex() string { return hex.EncodeToString(g.idKey) }

// ObjectID is Section 5.3's recommended construction over message M.
func (g *Game) ObjectID(msg string) string { return "o-" + hex.EncodeToString(mac(g.idKey, msg)[:8]) }

// StreamSeed is Section 11.6's recommended stream seed; owner is "p0", "p1" or "shared".
func (g *Game) StreamSeed(owner, purpose string, n uint64) [32]byte {
	var s [32]byte
	copy(s[:], mac(g.secret, fmt.Sprintf("spellbench/v2/rng:%s:%s:%d", owner, purpose, n)))
	return s
}

// Stream is a ChaCha8 generator (256-bit key) for one randomized event.
func (g *Game) Stream(owner, purpose string, n uint64) *rand.Rand {
	return rand.New(rand.NewChaCha8(g.StreamSeed(owner, purpose, n)))
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/secrets/ -v`
Expected: `--- PASS: TestHostVectors`, `--- PASS: TestEngineVectors`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/secrets && git commit -m "gorge adapter: v2 secret, id and stream constructions with spec vectors"
```

---

### Task 5: v2 semantics, observation and decision types

**Files:**
- Create: `internal/protocol/refs.go`, `internal/protocol/kinds.go`, `internal/protocol/observation.go`, `internal/protocol/messages.go`
- Test: `internal/protocol/kinds_test.go`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `const protocol.Name = "spellbench/v2"`;
  - `type ObjectRef`, `type TargetRef` (with `PlayerTarget(seat string) TargetRef` and `ObjectTarget(ObjectRef) TargetRef`);
  - `type Semantic struct{ Kind string; Fields map[string]any }` with `MarshalJSON`, `func (*Semantic) UnmarshalJSON([]byte) error` and `func (Semantic) Check() error`. A decoded semantic's `Fields` hold `string`, `bool`, `nil`, `json.Number`, and `json.RawMessage` for nested objects and arrays; constructors store Go values. `Check` types every field of all 30 kinds (references, target references, order items, u32, i32, vocabularies, seats; Section 11.3 V1), reads numbers through one helper (Go integer types or `json.Number`), enforces the Section 7.3 constraints and `choose_name`'s card-type domain, and never panics;
  - `var KindFields map[string][]string` (the 30 kinds, derived from the typed `kindTable`) and `var PriorityKinds map[string]bool`;
  - the constructors listed in Step 3;
  - `type Candidate`, `type Group`, `type Context`, `type SeatDecision` (its `Extensions` is `type ExtensionMap map[string]json.RawMessage`, whose `MarshalJSON` writes nil as `{}`, Section 9.3; plain map values assign to it), `type Observation`, `type PlayerObs` (with `Progress *Progress`), `type ObjectRecord`, `type Characteristics`, `type Permanent`, `type StackEntry`, `type PendingTrigger`, `type Known`, `type ManaPool`, `type OrderItem`, `type TriggerItem` (a `TargetRef` decodes strictly: exactly one of a seat or a reference);
  - `type Provenance`, `type Engine`, `type HelloOK` (`ProtocolMinor uint32`), `type DecisionResponse`, `type TerminalResponse`, `type ErrorResponse`, `type ErrorBody`, `type DeckOK`.

G1-2 and G1-8, applied during implementation, with its review fix round: the semantic decoder and number-safe `Check` (a host decodes the engine's JSON before validating it, Tasks 9 and 25), typed fields for all 30 kinds, `Check`'s remaining constraints (`choose_option`, `choose_pile`, the `mana_choice` vocabulary, a null `cast_spell` method), and `extensions` as an object (`ExtensionMap`).

- [ ] **Step 1: Write the failing test**

`internal/protocol/kinds_test.go`:

```go
package protocol_test

import (
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestThirtyKinds(t *testing.T) {
	if len(protocol.KindFields) != 30 {
		t.Fatalf("%d kinds, spec Section 7 lists 30", len(protocol.KindFields))
	}
	if len(protocol.PriorityKinds) != 6 {
		t.Fatalf("%d priority kinds, want 6", len(protocol.PriorityKinds))
	}
}

func keys(t *testing.T, s protocol.Semantic) []string {
	b, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	json.Unmarshal(b, &m)
	var ks []string
	for k := range m {
		if k != "kind" {
			ks = append(ks, k)
		}
	}
	sort.Strings(ks)
	return ks
}

// everyConstructor returns one semantic from each constructor.
func everyConstructor() []protocol.Semantic {
	name := "Lightning Bolt"
	r := protocol.ObjectRef{ObjectID: "o-0a3647243d16bf78", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "hand"}
	tgt := protocol.PlayerTarget("p1")
	return []protocol.Semantic{
		protocol.Pass(), protocol.PlayLand(r, 0), protocol.CastSpell(r, "normal"),
		protocol.ActivateManaAbility(r, 0, nil, nil), protocol.ActivateAbility(r, 1), protocol.SpecialAction(r, "plot"),
		protocol.ChooseTarget(r, 0, tgt, 0, 1, 1), protocol.FinishTargetSelection(r, 0, 1),
		protocol.ChooseCostTarget(r, "sacrifice", r, 0, 1, 1), protocol.ChooseSpellMode(r, 0, 2, 0, 1, 1),
		protocol.ChooseColor(nil, "effect", "red"), protocol.ChooseNumber(&r, "x_value", 2, 0, 4),
		protocol.ChooseBoolean(nil, "optional_trigger", true), protocol.ChooseName(&r, "card_type", "creature"),
		protocol.SelectObject(nil, "discard", protocol.ObjectTarget(r), 0, 1, 1), protocol.FinishSelection(nil, "search", 0),
		protocol.OptionalCost(r, "kicker", true), protocol.OptionalCast(r, "madness", false), protocol.Mulligan(7, 0, true),
		protocol.OrderPick(nil, "mulligan_bottom", protocol.ObjectItem(r), 0, 1),
		protocol.ArrangeCard(&r, "scry", r, 0, 2, "top"),
		protocol.ChooseReplacement(tgt, "damage", nil, 0, 2), protocol.DeclareAttack(r, &tgt), protocol.DeclareBlock(r, nil),
		protocol.Distribute(&r, "combat_damage", protocol.ObjectTarget(r), 1, 3),
	}
}

func TestConstructorsEmitExactlyTheSpecFields(t *testing.T) {
	for _, s := range everyConstructor() {
		want := append([]string(nil), protocol.KindFields[s.Kind]...)
		sort.Strings(want)
		got := keys(t, s)
		if len(got) != len(want) {
			t.Errorf("%s fields %v, want %v", s.Kind, got, want)
			continue
		}
		for i := range got {
			if got[i] != want[i] {
				t.Errorf("%s fields %v, want %v", s.Kind, got, want)
			}
		}
		if err := s.Check(); err != nil {
			t.Errorf("%s: %v", s.Kind, err)
		}
	}
}

func TestCheckEnforcesFieldConstraints(t *testing.T) {
	name := "x"
	r := protocol.ObjectRef{ObjectID: "o-1", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "stack"}
	for _, s := range []protocol.Semantic{
		protocol.ChooseTarget(r, 0, protocol.PlayerTarget("p0"), 1, 1, 1),            // selected_count < maximum
		protocol.ChooseSpellMode(r, 2, 2, 0, 1, 1),                                   // mode_index < mode_count
		protocol.ChooseNumber(nil, "amount", 5, 0, 4),                                // minimum <= value <= maximum
		protocol.ChooseReplacement(protocol.PlayerTarget("p0"), "damage", nil, 0, 1), // 2 <= count
		protocol.Distribute(nil, "damage", protocol.PlayerTarget("p1"), 4, 3),        // amount <= remaining
		protocol.ChooseColor(nil, "effect", "colorless"),                             // vocabulary
	} {
		if err := s.Check(); err == nil {
			t.Errorf("%s %v accepted", s.Kind, s.Fields)
		}
	}
}

func TestTargetRefAndNullableFields(t *testing.T) {
	b, _ := json.Marshal(protocol.DeclareBlock(protocol.ObjectRef{ObjectID: "o-1", OwnerSeat: "p1", ControllerSeat: "p1", Zone: "battlefield"}, nil))
	// Map keys are sorted by encoding/json; struct fields keep declaration order.
	want := `{"attacker":null,"blocker":{"object_id":"o-1","card_name":null,"owner_seat":"p1","controller_seat":"p1","zone":"battlefield"},"kind":"declare_block"}`
	if string(b) != want {
		t.Fatalf("got %s", b)
	}
	b, _ = json.Marshal(protocol.PlayerTarget("p0"))
	if string(b) != `{"player":"p0"}` {
		t.Fatalf("player target %s", b)
	}
}

// checked runs Check and reports a panic as a test failure, so one bad case
// cannot abort the others.
func checked(t *testing.T, s protocol.Semantic) (err error) {
	t.Helper()
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("%s: Check panicked: %v", s.Kind, p)
			err = errors.New("panic")
		}
	}()
	return s.Check()
}

func decoded(t *testing.T, text string) protocol.Semantic {
	t.Helper()
	var s protocol.Semantic
	if err := json.Unmarshal([]byte(text), &s); err != nil {
		t.Fatalf("%s: %v", text, err)
	}
	return s
}

// A host decodes the engine's JSON; the decoded semantic must pass Check and
// re-marshal to the same bytes.
func TestDecodedSemanticsRoundTrip(t *testing.T) {
	for _, s := range everyConstructor() {
		b, err := json.Marshal(s)
		if err != nil {
			t.Fatal(err)
		}
		var d protocol.Semantic
		if err := json.Unmarshal(b, &d); err != nil {
			t.Errorf("%s: %v", s.Kind, err)
			continue
		}
		if err := checked(t, d); err != nil {
			t.Errorf("decoded %s: %v", s.Kind, err)
		}
		if again, _ := json.Marshal(d); string(again) != string(b) {
			t.Errorf("%s round trip\n got %s\nwant %s", s.Kind, again, b)
		}
	}
}

// Task 25's host decodes whole decision responses into these types.
func TestDecodedDecisionKeepsItsCandidates(t *testing.T) {
	sd := protocol.SeatDecision{ActingSeat: "p0", Context: protocol.Context{Kind: "choice"}}
	for i, s := range everyConstructor() {
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: s})
	}
	b, err := json.Marshal(protocol.DecisionResponse{ResponseType: "decision", Protocol: protocol.Name, SeatDecision: sd})
	if err != nil {
		t.Fatal(err)
	}
	var back protocol.DecisionResponse
	if err := json.Unmarshal(b, &back); err != nil {
		t.Fatal(err)
	}
	for _, c := range back.SeatDecision.Candidates {
		if err := checked(t, c.Semantic); err != nil {
			t.Errorf("candidate %d: %v", c.CandidateID, err)
		}
	}
	if again, _ := json.Marshal(back); string(again) != string(b) {
		t.Errorf("decision round trip\n got %s\nwant %s", again, b)
	}
}

func TestSemanticDecodeNeedsAKindedObject(t *testing.T) {
	for _, text := range []string{`null`, `[]`, `"pass"`, `7`, `{}`, `{"kind":null}`, `{"kind":7}`} {
		var s protocol.Semantic
		if err := json.Unmarshal([]byte(text), &s); err == nil {
			t.Errorf("%s decoded as %+v", text, s)
		}
	}
	var c protocol.Candidate
	if err := json.Unmarshal([]byte(`{"candidate_id":0,"semantic":null,"display_text":null}`), &c); err == nil {
		t.Errorf("null semantic decoded as %+v", c.Semantic)
	}
}

func TestCheckReadsNumbersExactly(t *testing.T) {
	d := decoded(t, `{"kind":"choose_number","source":null,"purpose":"x_value","value":-2,"minimum":-3,"maximum":4}`)
	if d.Fields["value"] != json.Number("-2") {
		t.Fatalf("value decoded as %T %v, want json.Number", d.Fields["value"], d.Fields["value"])
	}
	if err := checked(t, d); err != nil {
		t.Fatalf("decoded choose_number: %v", err)
	}
	if err := checked(t, decoded(t, `{"kind":"choose_number","source":null,"purpose":"x_value","value":5,"minimum":0,"maximum":4}`)); err == nil {
		t.Error("decoded choose_number outside its range accepted")
	}
	// Generically decoded fields (float64): an error, not a panic.
	generic := protocol.Semantic{Kind: "choose_number", Fields: map[string]any{"source": nil, "purpose": "x_value",
		"value": float64(1), "minimum": float64(0), "maximum": float64(2)}}
	if err := checked(t, generic); err == nil {
		t.Error("float64 numbers accepted")
	}
	// Any Go integer type is read.
	s := protocol.OrderPick(nil, "triggers", protocol.ObjectItem(ref), 0, 2)
	s.Fields["position"], s.Fields["count"] = int(1), uint64(2)
	if err := checked(t, s); err != nil {
		t.Errorf("Go integer types: %v", err)
	}
	// Anything else is refused, as are values outside the field's u32 or i32 range.
	for name, mutate := range map[string]func(protocol.Semantic){
		"fraction":            func(s protocol.Semantic) { s.Fields["position"] = json.Number("0.5") },
		"exponent":            func(s protocol.Semantic) { s.Fields["position"] = json.Number("0e0") },
		"string":              func(s protocol.Semantic) { s.Fields["position"] = "0" },
		"null":                func(s protocol.Semantic) { s.Fields["position"] = nil },
		"negative u32":        func(s protocol.Semantic) { s.Fields["position"] = json.Number("-1") },
		"u32 overflow":        func(s protocol.Semantic) { s.Fields["count"] = uint64(math.MaxUint32 + 1) },
		"uint64 beyond int64": func(s protocol.Semantic) { s.Fields["count"] = uint64(math.MaxUint64) },
	} {
		s := protocol.OrderPick(nil, "triggers", protocol.ObjectItem(ref), 0, 2)
		mutate(s)
		if err := checked(t, s); err == nil {
			t.Errorf("order_pick with %s %v accepted", name, s.Fields)
		}
	}
	i32 := protocol.ChooseNumber(nil, "amount", 1, 0, 4)
	i32.Fields["maximum"] = json.Number("2147483648")
	if err := checked(t, i32); err == nil {
		t.Error("choose_number maximum beyond i32 accepted")
	}
}

// specTypes is this test's own transcription of the field types in Sections
// 7.2 and 7.3: R and T are object and target references, word is a
// vocabulary value, snake an open snake_case word, piles two arrays of R.
var specTypes = map[string][][2]string{
	"pass":                    {},
	"play_land":               {{"source", "R"}, {"face", "u32"}},
	"cast_spell":              {{"source", "R"}, {"method", "word|null"}},
	"activate_mana_ability":   {{"source", "R"}, {"ability_index", "u32"}, {"mana_choice", "word|null"}, {"cost_target", "T|null"}},
	"activate_ability":        {{"source", "R"}, {"ability_index", "u32"}},
	"special_action":          {{"source", "R"}, {"action", "word"}},
	"choose_target":           {{"source", "R"}, {"slot", "u32"}, {"target", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_target_selection": {{"source", "R"}, {"slot", "u32"}, {"selected_count", "u32"}},
	"choose_cost_target":      {{"source", "R"}, {"cost_kind", "word"}, {"candidate", "R"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_cast_method":      {{"source", "R"}, {"method", "word"}},
	"choose_spell_mode":       {{"source", "R"}, {"mode_index", "u32"}, {"mode_count", "u32"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_option":           {{"source", "R|null"}, {"purpose", "word"}, {"option_index", "u32"}, {"option_count", "u32"}, {"option_label", "string|null"}},
	"choose_color":            {{"source", "R|null"}, {"purpose", "word"}, {"color", "word"}},
	"choose_number":           {{"source", "R|null"}, {"purpose", "word"}, {"value", "i32"}, {"minimum", "i32"}, {"maximum", "i32"}},
	"choose_boolean":          {{"source", "R|null"}, {"purpose", "word"}, {"value", "bool"}},
	"choose_name":             {{"source", "R|null"}, {"purpose", "word"}, {"value", "string"}},
	"select_object":           {{"source", "R|null"}, {"purpose", "word"}, {"choice", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_selection":        {{"source", "R|null"}, {"purpose", "word"}, {"selected_count", "u32"}},
	"optional_cost":           {{"source", "R"}, {"cost", "word"}, {"pay", "bool"}},
	"choose_cost_option":      {{"source", "R"}, {"choice", "snake"}},
	"optional_cast":           {{"card", "R"}, {"method", "word"}, {"cast_it", "bool"}},
	"mulligan":                {{"hand_size", "u32"}, {"mulligans_taken", "u32"}, {"keep", "bool"}},
	"order_pick":              {{"source", "R|null"}, {"purpose", "word"}, {"item", "item"}, {"position", "u32"}, {"count", "u32"}},
	"arrange_card":            {{"source", "R|null"}, {"purpose", "word"}, {"card", "R"}, {"card_index", "u32"}, {"card_count", "u32"}, {"destination", "word"}},
	"choose_replacement":      {{"affected", "T"}, {"event", "word"}, {"replacement_source", "R|null"}, {"replacement_index", "u32"}, {"replacement_count", "u32"}},
	"choose_starting_player":  {{"player", "seat"}},
	"declare_attack":          {{"attacker", "R"}, {"defender", "T|null"}},
	"declare_block":           {{"blocker", "R"}, {"attacker", "R|null"}},
	"distribute":              {{"source", "R|null"}, {"purpose", "word"}, {"recipient", "T"}, {"amount", "u32"}, {"remaining", "u32"}},
	"choose_pile":             {{"source", "R|null"}, {"purpose", "word"}, {"pile_index", "u32"}, {"piles", "piles"}},
}

func TestKindFieldsMatchTheSpecTable(t *testing.T) {
	if len(protocol.KindFields) != len(specTypes) {
		t.Fatalf("%d kinds, spec table %d", len(protocol.KindFields), len(specTypes))
	}
	for kind, slots := range specTypes {
		got := protocol.KindFields[kind]
		if len(got) != len(slots) {
			t.Errorf("%s fields %v, spec %v", kind, got, slots)
			continue
		}
		for i, sl := range slots {
			if got[i] != sl[0] {
				t.Errorf("%s fields %v, spec %v", kind, got, slots)
			}
		}
	}
}

// baselines returns one valid semantic of every kind.
func baselines() map[string]protocol.Semantic {
	out := map[string]protocol.Semantic{}
	for _, s := range everyConstructor() {
		out[s.Kind] = s
	}
	for _, s := range []protocol.Semantic{
		{Kind: "choose_cast_method", Fields: map[string]any{"source": ref, "method": "flashback"}},
		{Kind: "choose_option", Fields: map[string]any{"source": nil, "purpose": "effect_option",
			"option_index": uint32(0), "option_count": uint32(2), "option_label": nil}},
		{Kind: "choose_cost_option", Fields: map[string]any{"source": ref, "choice": "sacrifice_land"}},
		{Kind: "choose_starting_player", Fields: map[string]any{"player": "p1"}},
		{Kind: "choose_pile", Fields: map[string]any{"source": nil, "purpose": "effect", "pile_index": uint32(1),
			"piles": [][]protocol.ObjectRef{{}, {ref}}}},
	} {
		out[s.Kind] = s
	}
	return out
}

// with returns a copy of s with field k set to v.
func with(s protocol.Semantic, k string, v any) protocol.Semantic {
	f := make(map[string]any, len(s.Fields))
	for key, val := range s.Fields {
		f[key] = val
	}
	f[k] = v
	return protocol.Semantic{Kind: s.Kind, Fields: f}
}

// mk builds a semantic from field pairs.
func mk(kind string, kv ...any) protocol.Semantic {
	f := map[string]any{}
	for i := 0; i < len(kv); i += 2 {
		f[kv[i].(string)] = kv[i+1]
	}
	return protocol.Semantic{Kind: kind, Fields: f}
}

// both runs Check on s as built and on s decoded from its JSON, as a host
// reads it.
func both(t *testing.T, s protocol.Semantic) (built, wire error) {
	t.Helper()
	built = checked(t, s)
	b, err := json.Marshal(s)
	if err != nil {
		return built, err
	}
	var d protocol.Semantic
	if err := json.Unmarshal(b, &d); err != nil {
		return built, err
	}
	return built, checked(t, d)
}

var (
	island = "Island"
	ref    = protocol.ObjectRef{ObjectID: "o-2", CardName: &island, OwnerSeat: "p1", ControllerSeat: "p1", Zone: "battlefield"}
)

// refMap is ref as decoded JSON, edited.
func refMap(edit func(map[string]any)) map[string]any {
	m := map[string]any{"object_id": "o-2", "card_name": "Island", "owner_seat": "p1", "controller_seat": "p1", "zone": "battlefield"}
	if edit != nil {
		edit(m)
	}
	return m
}

// trigger is an order_pick trigger item's body as decoded JSON, edited.
func trigger(edit func(map[string]any)) map[string]any {
	m := map[string]any{"source": refMap(nil), "source_name": "Island", "ability_index": 0,
		"event_objects": []any{refMap(nil)}, "instance": 1, "label": nil}
	if edit != nil {
		edit(m)
	}
	return m
}

type value struct {
	name string
	v    any
}

// wrongValues returns values that a field of the given spec type must refuse.
func wrongValues(typ string) []value {
	base, nullable := strings.CutSuffix(typ, "|null")
	var out []value
	if !nullable {
		out = append(out, value{"null", nil})
	}
	badRef := func(name string, edit func(map[string]any)) value { return value{name, refMap(edit)} }
	switch base {
	case "u32":
		out = append(out, value{"-1", -1}, value{"2^32", uint64(1) << 32}, value{"1.5", json.Number("1.5")},
			value{"1e0", json.Number("1e0")}, value{`"0"`, "0"}, value{"true", true}, value{"{}", map[string]any{}})
	case "i32":
		out = append(out, value{"2^31", int64(math.MaxInt32) + 1}, value{"-2^31-1", int64(math.MinInt32) - 1},
			value{"0.5", json.Number("0.5")}, value{`"0"`, "0"}, value{"false", false})
	case "bool":
		out = append(out, value{`"yes"`, "yes"}, value{`"true"`, "true"}, value{"1", 1}, value{"{}", map[string]any{}})
	case "string":
		out = append(out, value{"5", 5}, value{"true", true}, value{"{}", map[string]any{}}, value{"[]", []any{}})
	case "word":
		out = append(out, value{`"bogus"`, "bogus"}, value{`""`, ""}, value{"5", 5}, value{"true", true})
	case "snake":
		out = append(out, value{`"Not Snake"`, "Not Snake"}, value{`"1st"`, "1st"}, value{`"a-b"`, "a-b"},
			value{`""`, ""}, value{"5", 5})
	case "seat":
		out = append(out, value{`"p7"`, "p7"}, value{`"P0"`, "P0"}, value{`""`, ""}, value{"0", 0})
	case "R":
		out = append(out, value{"7", 7}, value{`"o-2"`, "o-2"}, value{"[]", []any{}}, value{"{}", map[string]any{}},
			value{"zero ObjectRef", protocol.ObjectRef{}}, value{"player target", protocol.PlayerTarget("p0")},
			badRef("ref without zone", func(m map[string]any) { delete(m, "zone") }),
			badRef("ref with an extra key", func(m map[string]any) { m["x"] = 1 }),
			badRef("owner_seat p7", func(m map[string]any) { m["owner_seat"] = "p7" }),
			badRef("controller_seat null", func(m map[string]any) { m["controller_seat"] = nil }),
			badRef("zone deck", func(m map[string]any) { m["zone"] = "deck" }),
			badRef("object_id 5", func(m map[string]any) { m["object_id"] = 5 }),
			badRef("object_id null", func(m map[string]any) { m["object_id"] = nil }),
			badRef("card_name 5", func(m map[string]any) { m["card_name"] = 5 }))
	case "T":
		out = append(out, value{"zero TargetRef", protocol.TargetRef{}}, value{`{"object":null}`, map[string]any{"object": nil}},
			value{"{}", map[string]any{}}, value{`{"player":"p7"}`, map[string]any{"player": "p7"}},
			value{"player and object", map[string]any{"player": "p0", "object": refMap(nil)}},
			value{`{"target":"p0"}`, map[string]any{"target": "p0"}},
			value{"object with a bad ref", map[string]any{"object": refMap(func(m map[string]any) { m["zone"] = "deck" })}},
			value{"bare ref", ref}, value{`"p0"`, "p0"}, value{"5", 5})
	case "item":
		badTrigger := func(name string, edit func(map[string]any)) value {
			return value{name, map[string]any{"trigger": trigger(edit)}}
		}
		out = append(out, value{"zero OrderItem", protocol.OrderItem{}}, value{`{"trigger":null}`, map[string]any{"trigger": nil}},
			value{`{"object":null}`, map[string]any{"object": nil}}, value{"[]", []any{}}, value{"{}", map[string]any{}},
			value{"object and trigger", map[string]any{"object": refMap(nil), "trigger": trigger(nil)}},
			value{`{"card":R}`, map[string]any{"card": refMap(nil)}}, value{"bare ref", refMap(nil)},
			badTrigger("trigger without instance", func(m map[string]any) { delete(m, "instance") }),
			badTrigger("trigger with an extra key", func(m map[string]any) { m["x"] = 1 }),
			badTrigger("trigger instance -1", func(m map[string]any) { m["instance"] = -1 }),
			badTrigger(`trigger ability_index "x"`, func(m map[string]any) { m["ability_index"] = "x" }),
			badTrigger("trigger source 5", func(m map[string]any) { m["source"] = 5 }),
			badTrigger("trigger source_name 5", func(m map[string]any) { m["source_name"] = 5 }),
			badTrigger("trigger label 5", func(m map[string]any) { m["label"] = 5 }),
			badTrigger("trigger event_objects null", func(m map[string]any) { m["event_objects"] = nil }),
			badTrigger("trigger event_objects [5]", func(m map[string]any) { m["event_objects"] = []any{5} }))
	case "piles":
		out = append(out, value{`[[1,2],["x"]]`, []any{[]any{1, 2}, []any{"x"}}},
			value{"refs, not arrays", []any{refMap(nil), refMap(nil)}},
			value{"a null pile", []any{[]any{refMap(nil)}, nil}},
			value{"a bad ref in a pile", []any{[]any{refMap(func(m map[string]any) { m["zone"] = "deck" })}, []any{}}},
			value{`"piles"`, "piles"}, value{"{}", map[string]any{}})
	}
	return out
}

// validValues returns values other than the baseline's that a field of the
// given spec type must accept. Numbers are covered by the constraint tests.
func validValues(typ string) []value {
	base, nullable := strings.CutSuffix(typ, "|null")
	var out []value
	if nullable {
		out = append(out, value{"null", nil})
		switch base {
		case "R":
			out = append(out, value{"nil *ObjectRef", (*protocol.ObjectRef)(nil)})
		case "T":
			out = append(out, value{"nil *TargetRef", (*protocol.TargetRef)(nil)})
		case "string", "word":
			out = append(out, value{"nil *string", (*string)(nil)})
		}
	}
	tgt := protocol.ObjectTarget(ref)
	switch base {
	case "R":
		out = append(out, value{"ObjectRef", ref}, value{"*ObjectRef", &ref},
			value{"null card_name", refMap(func(m map[string]any) { m["card_name"] = nil })},
			value{"zone exile", refMap(func(m map[string]any) { m["zone"] = "exile" })})
	case "T":
		out = append(out, value{"player p0", protocol.PlayerTarget("p0")}, value{"object", tgt}, value{"*TargetRef", &tgt},
			value{`{"player":"p1"}`, map[string]any{"player": "p1"}})
	case "item":
		out = append(out, value{"object item", protocol.ObjectItem(ref)},
			value{"empty trigger", protocol.OrderItem{Trigger: &protocol.TriggerItem{EventObjects: []protocol.ObjectRef{}}}},
			value{"trigger", map[string]any{"trigger": trigger(nil)}},
			value{"trigger with nulls", map[string]any{"trigger": trigger(func(m map[string]any) {
				m["source"], m["source_name"], m["ability_index"], m["event_objects"] = nil, nil, nil, []any{}
			})}})
	case "piles":
		out = append(out, value{"Go piles", [][]protocol.ObjectRef{{ref}, {}}},
			value{"decoded piles", []any{[]any{}, []any{refMap(nil), refMap(nil)}}})
	case "seat":
		out = append(out, value{"p0", "p0"}, value{"p1", "p1"})
	case "snake":
		out = append(out, value{"decline", "decline"}, value{"a1_b", "a1_b"})
	case "bool":
		out = append(out, value{"true", true}, value{"false", false})
	}
	return out
}

// Every field slot of every kind refuses values of the wrong type, built or
// decoded.
func TestEverySlotRejectsAWrongValue(t *testing.T) {
	base := baselines()
	for kind, slots := range specTypes {
		for _, sl := range slots {
			for _, w := range wrongValues(sl[1]) {
				if built, wire := both(t, with(base[kind], sl[0], w.v)); built == nil || wire == nil {
					t.Errorf("%s.%s = %s accepted (built: %v, decoded: %v)", kind, sl[0], w.name, built, wire)
				}
			}
		}
	}
}

func TestEverySlotAcceptsItsValidForms(t *testing.T) {
	base := baselines()
	if len(base) != len(specTypes) {
		t.Fatalf("%d baselines for %d kinds", len(base), len(specTypes))
	}
	for kind, slots := range specTypes {
		if built, wire := both(t, base[kind]); built != nil || wire != nil {
			t.Errorf("baseline %s rejected (built: %v, decoded: %v)", kind, built, wire)
		}
		for _, sl := range slots {
			vals := validValues(sl[1])
			if w, ok := base[kind].Fields[sl[0]].(string); ok {
				vals = append(vals, value{"*string", &w})
			}
			for _, v := range vals {
				if built, wire := both(t, with(base[kind], sl[0], v.v)); built != nil || wire != nil {
					t.Errorf("%s.%s = %s rejected (built: %v, decoded: %v)", kind, sl[0], v.name, built, wire)
				}
			}
		}
	}
}

// A zero TargetRef or OrderItem marshals as {"object":null} or
// {"trigger":null}; one with both members set marshals as its first member.
// Check refuses all three in every target and item slot.
func TestZeroAndDoubleReferencesFailCheck(t *testing.T) {
	base := baselines()
	p0 := "p0"
	for kind, slots := range specTypes {
		for _, sl := range slots {
			var bad []value
			switch strings.TrimSuffix(sl[1], "|null") {
			case "T":
				bad = []value{{"zero TargetRef", protocol.TargetRef{}}, {"&zero TargetRef", &protocol.TargetRef{}},
					{"TargetRef with both members", protocol.TargetRef{Player: &p0, Object: &ref}}}
			case "item":
				bad = []value{{"zero OrderItem", protocol.OrderItem{}}, {"&zero OrderItem", &protocol.OrderItem{}},
					{"OrderItem with both members", protocol.OrderItem{Object: &ref, Trigger: &protocol.TriggerItem{EventObjects: []protocol.ObjectRef{}}}}}
			}
			for _, b := range bad {
				if err := checked(t, with(base[kind], sl[0], b.v)); err == nil {
					t.Errorf("%s.%s = %s accepted", kind, sl[0], b.name)
				}
			}
		}
	}
	for _, text := range []string{
		`{"kind":"choose_target","source":{"object_id":"o-1","card_name":"x","owner_seat":"p0","controller_seat":"p0","zone":"stack"},"slot":0,"target":{"object":null},"selected_count":0,"minimum":1,"maximum":1}`,
		`{"kind":"order_pick","source":null,"purpose":"triggers","item":{"trigger":null},"position":0,"count":1}`,
	} {
		if err := checked(t, decoded(t, text)); err == nil {
			t.Errorf("%s accepted", text)
		}
	}
}

// Each clause of Section 7.3's field constraints, the choose_name card-type
// domain, and the field set, violated alone and met at its boundary.
func TestCheckEnforcesEachConstraintClause(t *testing.T) {
	R := refMap(nil)
	target := func(sel, lo, hi int) protocol.Semantic {
		return mk("choose_target", "source", R, "slot", 0, "target", map[string]any{"player": "p1"}, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	costTarget := func(sel, lo, hi int) protocol.Semantic {
		return mk("choose_cost_target", "source", R, "cost_kind", "sacrifice", "candidate", R, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	selectObject := func(sel, lo, hi int) protocol.Semantic {
		return mk("select_object", "source", nil, "purpose", "discard", "choice", map[string]any{"object": R}, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	mode := func(idx, count, sel, lo, hi int) protocol.Semantic {
		return mk("choose_spell_mode", "source", R, "mode_index", idx, "mode_count", count, "selected_count", sel, "minimum", lo, "maximum", hi)
	}
	option := func(idx, count int) protocol.Semantic {
		return mk("choose_option", "source", nil, "purpose", "vote", "option_index", idx, "option_count", count, "option_label", "yes")
	}
	number := func(v, lo, hi int64) protocol.Semantic {
		return mk("choose_number", "source", nil, "purpose", "amount", "value", v, "minimum", lo, "maximum", hi)
	}
	pick := func(pos, count int) protocol.Semantic {
		return mk("order_pick", "source", nil, "purpose", "triggers", "item", map[string]any{"object": R}, "position", pos, "count", count)
	}
	arrange := func(idx, count int) protocol.Semantic {
		return mk("arrange_card", "source", nil, "purpose", "scry", "card", R, "card_index", idx, "card_count", count, "destination", "bottom")
	}
	replacement := func(idx, count int) protocol.Semantic {
		return mk("choose_replacement", "affected", map[string]any{"player": "p0"}, "event", "damage", "replacement_source", nil,
			"replacement_index", idx, "replacement_count", count)
	}
	distribute := func(amount, remaining int) protocol.Semantic {
		return mk("distribute", "source", nil, "purpose", "damage", "recipient", map[string]any{"player": "p1"}, "amount", amount, "remaining", remaining)
	}
	pile := func(idx int, piles ...any) protocol.Semantic {
		return mk("choose_pile", "source", nil, "purpose", "effect", "pile_index", idx, "piles", piles)
	}
	name := func(purpose, v string) protocol.Semantic {
		return mk("choose_name", "source", nil, "purpose", purpose, "value", v)
	}
	color := func(kv ...any) protocol.Semantic {
		return mk("choose_color", append([]any{"source", nil, "purpose", "effect"}, kv...)...)
	}
	for name, s := range map[string]protocol.Semantic{
		"choose_target minimum > maximum":              target(0, 2, 1),
		"choose_target selected_count = maximum":       target(1, 1, 1),
		"choose_cost_target minimum > maximum":         costTarget(0, 2, 1),
		"choose_cost_target selected_count = maximum":  costTarget(1, 1, 1),
		"select_object minimum > maximum":              selectObject(0, 2, 1),
		"select_object selected_count = maximum":       selectObject(1, 1, 1),
		"choose_spell_mode mode_index = mode_count":    mode(2, 2, 0, 1, 1),
		"choose_spell_mode minimum > maximum":          mode(0, 3, 0, 2, 1),
		"choose_spell_mode maximum > mode_count":       mode(0, 2, 0, 1, 3),
		"choose_spell_mode selected_count = maximum":   mode(0, 2, 1, 1, 1),
		"choose_option option_index = option_count":    option(2, 2),
		"choose_number value < minimum":                number(-1, 0, 4),
		"choose_number value > maximum":                number(5, 0, 4),
		"order_pick position = count":                  pick(2, 2),
		"arrange_card card_index = card_count":         arrange(2, 2),
		"choose_replacement replacement_count = 1":     replacement(0, 1),
		"choose_replacement index = count":             replacement(2, 2),
		"distribute amount > remaining":                distribute(4, 3),
		"choose_pile pile_index 2":                     pile(2, []any{}, []any{R}),
		"choose_pile with one pile":                    pile(0, []any{R}),
		"choose_pile with three piles":                 pile(0, []any{}, []any{}, []any{R}),
		"choose_pile with no piles":                    pile(0),
		"choose_name card_type bogus":                  name("card_type", "bogus"),
		"choose_name card_type Creature":               name("card_type", "Creature"),
		"pass with an extra field":                     mk("pass", "x", 1),
		"choose_color with an extra field":             color("color", "red", "extra", 1),
		"choose_color without color":                   color(),
		"choose_color with colour instead of color":    color("colour", "red"),
		"choose_color with sauce instead of source":    mk("choose_color", "sauce", nil, "purpose", "effect", "color", "red"),
		"reserved kind pay_mana":                       mk("pay_mana"),
		"reserved kind narrow_number":                  mk("narrow_number", "source", nil, "purpose", "other", "minimum", 0, "maximum", 1),
		"kind missing":                                 mk(""),
		"choose_number minimum beyond i32":             number(0, math.MinInt32-1, 4),
		"play_land face beyond u32":                    mk("play_land", "source", R, "face", uint64(math.MaxUint32)+1),
		"order_pick position -1":                       pick(-1, 2),
		"choose_starting_player player null":           mk("choose_starting_player", "player", nil),
		"choose_cost_option choice with a capital":     mk("choose_cost_option", "source", R, "choice", "Decline"),
		"cast_spell method bogus":                      mk("cast_spell", "source", R, "method", "bogus"),
		"activate_mana_ability mana_choice lower case": mk("activate_mana_ability", "source", R, "ability_index", 0, "mana_choice", "w", "cost_target", nil),
	} {
		if built, wire := both(t, s); built == nil || wire == nil {
			t.Errorf("%s accepted (built: %v, decoded: %v)", name, built, wire)
		}
	}
	for name, s := range map[string]protocol.Semantic{
		"choose_target minimum = maximum":                   target(0, 1, 1),
		"choose_target selected_count = maximum - 1":        target(1, 0, 2),
		"choose_cost_target minimum = maximum":              costTarget(0, 1, 1),
		"choose_cost_target selected_count = maximum - 1":   costTarget(1, 0, 2),
		"select_object minimum = maximum":                   selectObject(0, 1, 1),
		"select_object selected_count = maximum - 1":        selectObject(1, 0, 2),
		"choose_spell_mode at every boundary":               mode(1, 2, 1, 2, 2),
		"choose_option option_index = option_count - 1":     option(1, 2),
		"choose_number value = minimum":                     number(-3, -3, 4),
		"choose_number value = maximum":                     number(4, -3, 4),
		"choose_number over the whole i32 range":            number(math.MinInt32, math.MinInt32, math.MaxInt32),
		"choose_number value = i32 maximum":                 number(math.MaxInt32, 0, math.MaxInt32),
		"order_pick position = count - 1":                   pick(1, 2),
		"arrange_card card_index = card_count - 1":          arrange(1, 2),
		"choose_replacement replacement_count = 2":          replacement(0, 2),
		"choose_replacement index = count - 1":              replacement(1, 2),
		"distribute amount = remaining":                     distribute(3, 3),
		"choose_pile pile_index 0":                          pile(0, []any{}, []any{R}),
		"choose_pile pile_index 1":                          pile(1, []any{R}, []any{}),
		"choose_name card_type creature":                    name("card_type", "creature"),
		"choose_name card_type kindred":                     name("card_type", "kindred"),
		"choose_name creature_type goblin":                  name("creature_type", "goblin"),
		"choose_name card_name Lightning Bolt":              name("card_name", "Lightning Bolt"),
		"choose_color":                                      color("color", "red"),
		"pass":                                              mk("pass"),
		"play_land face = u32 maximum":                      mk("play_land", "source", R, "face", uint64(math.MaxUint32)),
		"mulligan counts as Go int, uint64 and json.Number": mk("mulligan", "hand_size", 7, "mulligans_taken", uint64(1), "keep", true),
		"finish_selection selected_count as json.Number":    mk("finish_selection", "source", nil, "purpose", "modes", "selected_count", json.Number("3")),
	} {
		if built, wire := both(t, s); built != nil || wire != nil {
			t.Errorf("%s rejected (built: %v, decoded: %v)", name, built, wire)
		}
	}
}

// TargetRef decoding (observation targets: attached_to, attack_target, stack
// targets) accepts exactly {"player": seat} or {"object": ref}.
func TestTargetRefDecodingIsStrict(t *testing.T) {
	obj := `{"object_id":"o-1","card_name":null,"owner_seat":"p0","controller_seat":"p0","zone":"battlefield"}`
	for _, text := range []string{`null`, `{}`, `[]`, `"p0"`, `{"object":null}`, `{"player":null}`, `{"player":"p7"}`,
		`{"player":"p0","x":1}`, `{"player":"p0","object":` + obj + `}`, `{"target":"p0"}`} {
		var tr protocol.TargetRef
		if err := json.Unmarshal([]byte(text), &tr); err == nil {
			t.Errorf("%s decoded as %+v", text, tr)
		}
	}
	for _, text := range []string{`{"player":"p1"}`, `{"object":` + obj + `}`} {
		var tr protocol.TargetRef
		if err := json.Unmarshal([]byte(text), &tr); err != nil {
			t.Errorf("%s: %v", text, err)
		} else if b, _ := json.Marshal(tr); string(b) != text {
			t.Errorf("%s re-marshals as %s", text, b)
		}
	}
	var p protocol.Permanent
	if err := json.Unmarshal([]byte(`{"attached_to":{"object":null}}`), &p); err == nil {
		t.Error(`attached_to {"object":null} decoded`)
	}
	if err := json.Unmarshal([]byte(`{"attached_to":null,"attack_target":{"player":"p1"}}`), &p); err != nil || p.AttachedTo != nil {
		t.Errorf("valid permanent targets: %v %+v", err, p)
	}
}

// Section 6.3's progress object and Section 4.2's u32 protocol_minor.
func TestProgressAndProtocolMinorTypes(t *testing.T) {
	text := `{"dungeon":"Tomb of Annihilation","dungeon_room":null,"ring_tempted":2,"speed":null}`
	var p protocol.PlayerObs
	if err := json.Unmarshal([]byte(`{"progress":`+text+`}`), &p); err != nil {
		t.Fatal(err)
	}
	if b, _ := json.Marshal(p.Progress); string(b) != text {
		t.Errorf("progress re-marshals as %s", b)
	}
	var h protocol.HelloOK
	if err := json.Unmarshal([]byte(`{"protocol_minor":4294967296}`), &h); err == nil {
		t.Error("protocol_minor 2^32 decoded")
	}
}

// Section 9.3: extensions is an object, {} when the engine emits none.
func TestExtensionsMarshalAsAnObject(t *testing.T) {
	b, err := json.Marshal(protocol.DecisionResponse{})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"extensions":{}`) {
		t.Errorf("nil extensions marshal as %s", b)
	}
	sd := protocol.SeatDecision{Extensions: map[string]json.RawMessage{"x_gorge_view_v1": json.RawMessage(`{"a":1}`)}}
	if b, _ = json.Marshal(sd); !strings.Contains(string(b), `"extensions":{"x_gorge_view_v1":{"a":1}}`) {
		t.Errorf("extensions marshal as %s", b)
	}
	// The guarantee sits on the small map, not on the whole decision.
	if b, _ = json.Marshal(protocol.ExtensionMap(nil)); string(b) != `{}` {
		t.Errorf("nil ExtensionMap marshals as %s", b)
	}
	// A host decoding an engine's null still sees it (Task 9's check).
	var back protocol.SeatDecision
	if err := json.Unmarshal([]byte(`{"extensions":null}`), &back); err != nil || back.Extensions != nil {
		t.Errorf("decoded null extensions: %v %v", err, back.Extensions)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/protocol/`
Expected: FAIL with `undefined: protocol.KindFields`.

- [ ] **Step 3: Write minimal implementation**

`internal/protocol/refs.go`:

```go
// Package protocol holds the Spellbench v2 wire types this engine emits and reads.
package protocol

import (
	"encoding/json"
	"fmt"
)

const Name = "spellbench/v2"

type ObjectRef struct {
	ObjectID       string  `json:"object_id"`
	CardName       *string `json:"card_name"`
	OwnerSeat      string  `json:"owner_seat"`
	ControllerSeat string  `json:"controller_seat"`
	Zone           string  `json:"zone"`
}

// TargetRef is exactly one of {"player": seat} or {"object": ref}.
type TargetRef struct {
	Player *string
	Object *ObjectRef
}

func PlayerTarget(seat string) TargetRef { return TargetRef{Player: &seat} }
func ObjectTarget(r ObjectRef) TargetRef { return TargetRef{Object: &r} }

func (t TargetRef) MarshalJSON() ([]byte, error) {
	if t.Player != nil {
		return json.Marshal(map[string]string{"player": *t.Player})
	}
	return json.Marshal(map[string]*ObjectRef{"object": t.Object})
}

// UnmarshalJSON accepts exactly {"player": seat} or {"object": ref}.
func (t *TargetRef) UnmarshalJSON(b []byte) error {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(b, &m); err != nil {
		return err
	}
	p, o := m["player"], m["object"]
	var seat string
	var r ObjectRef
	switch {
	case len(m) == 1 && p != nil:
		if json.Unmarshal(p, &seat) != nil || (seat != "p0" && seat != "p1") {
			return fmt.Errorf("target reference: player %s is not a seat", p)
		}
		t.Player, t.Object = &seat, nil
	case len(m) == 1 && o != nil && string(o) != "null":
		if err := json.Unmarshal(o, &r); err != nil {
			return err
		}
		t.Player, t.Object = nil, &r
	default:
		return fmt.Errorf(`target reference %s is not {"player": seat} or {"object": ref}`, b)
	}
	return nil
}

// oneMember reports whether exactly one member is set, as the wire form needs.
func (t TargetRef) oneMember() bool { return (t.Player == nil) != (t.Object == nil) }

// OrderItem is order_pick.item: {"object": R} or {"trigger": {...}}.
type OrderItem struct {
	Object  *ObjectRef
	Trigger *TriggerItem
}

type TriggerItem struct {
	Source       *ObjectRef  `json:"source"`
	SourceName   *string     `json:"source_name"`
	AbilityIndex *uint32     `json:"ability_index"`
	EventObjects []ObjectRef `json:"event_objects"`
	Instance     uint32      `json:"instance"`
	Label        *string     `json:"label"`
}

func ObjectItem(r ObjectRef) OrderItem { return OrderItem{Object: &r} }

func (o OrderItem) oneMember() bool { return (o.Object == nil) != (o.Trigger == nil) }

func (o OrderItem) MarshalJSON() ([]byte, error) {
	if o.Object != nil {
		return json.Marshal(map[string]*ObjectRef{"object": o.Object})
	}
	return json.Marshal(map[string]*TriggerItem{"trigger": o.Trigger})
}
```

`internal/protocol/kinds.go`:

```go
package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"regexp"
	"slices"
	"strings"
)

type slot struct{ name, typ string }

// kindTable is Sections 7.2 and 7.3: each kind's fields in order, all required
// and no others, with the type Check enforces:
//   - R and T: an object reference (Section 5.1) and a target reference (5.2);
//   - item: order_pick.item, {"object": R} or {"trigger": {...}};
//   - [X]: an array of X;
//   - u32 and i32 (Section 4.4), bool, string, and seat (p0 or p1);
//   - snake: an open lowercase snake_case word (Section 4.4);
//   - any other name: a string from Vocab[name].
//
// A "|null" suffix also allows null.
var kindTable = map[string][]slot{
	"pass":                    {},
	"play_land":               {{"source", "R"}, {"face", "u32"}},
	"cast_spell":              {{"source", "R"}, {"method", "method|null"}},
	"activate_mana_ability":   {{"source", "R"}, {"ability_index", "u32"}, {"mana_choice", "mana_symbol|null"}, {"cost_target", "T|null"}},
	"activate_ability":        {{"source", "R"}, {"ability_index", "u32"}},
	"special_action":          {{"source", "R"}, {"action", "special_action.action"}},
	"choose_target":           {{"source", "R"}, {"slot", "u32"}, {"target", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_target_selection": {{"source", "R"}, {"slot", "u32"}, {"selected_count", "u32"}},
	"choose_cost_target":      {{"source", "R"}, {"cost_kind", "choose_cost_target.cost_kind"}, {"candidate", "R"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_cast_method":      {{"source", "R"}, {"method", "method"}},
	"choose_spell_mode":       {{"source", "R"}, {"mode_index", "u32"}, {"mode_count", "u32"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"choose_option":           {{"source", "R|null"}, {"purpose", "choose_option.purpose"}, {"option_index", "u32"}, {"option_count", "u32"}, {"option_label", "string|null"}},
	"choose_color":            {{"source", "R|null"}, {"purpose", "choose_color.purpose"}, {"color", "color"}},
	"choose_number":           {{"source", "R|null"}, {"purpose", "choose_number.purpose"}, {"value", "i32"}, {"minimum", "i32"}, {"maximum", "i32"}},
	"choose_boolean":          {{"source", "R|null"}, {"purpose", "choose_boolean.purpose"}, {"value", "bool"}},
	"choose_name":             {{"source", "R|null"}, {"purpose", "choose_name.purpose"}, {"value", "string"}},
	"select_object":           {{"source", "R|null"}, {"purpose", "select_object.purpose"}, {"choice", "T"}, {"selected_count", "u32"}, {"minimum", "u32"}, {"maximum", "u32"}},
	"finish_selection":        {{"source", "R|null"}, {"purpose", "finish_selection.purpose"}, {"selected_count", "u32"}},
	"optional_cost":           {{"source", "R"}, {"cost", "optional_cost.cost"}, {"pay", "bool"}},
	"choose_cost_option":      {{"source", "R"}, {"choice", "snake"}},
	"optional_cast":           {{"card", "R"}, {"method", "method"}, {"cast_it", "bool"}},
	"mulligan":                {{"hand_size", "u32"}, {"mulligans_taken", "u32"}, {"keep", "bool"}},
	"order_pick":              {{"source", "R|null"}, {"purpose", "order_pick.purpose"}, {"item", "item"}, {"position", "u32"}, {"count", "u32"}},
	"arrange_card":            {{"source", "R|null"}, {"purpose", "arrange_card.purpose"}, {"card", "R"}, {"card_index", "u32"}, {"card_count", "u32"}, {"destination", "arrange_card.destination"}},
	"choose_replacement":      {{"affected", "T"}, {"event", "choose_replacement.event"}, {"replacement_source", "R|null"}, {"replacement_index", "u32"}, {"replacement_count", "u32"}},
	"choose_starting_player":  {{"player", "seat"}},
	"declare_attack":          {{"attacker", "R"}, {"defender", "T|null"}},
	"declare_block":           {{"blocker", "R"}, {"attacker", "R|null"}},
	"distribute":              {{"source", "R|null"}, {"purpose", "distribute.purpose"}, {"recipient", "T"}, {"amount", "u32"}, {"remaining", "u32"}},
	"choose_pile":             {{"source", "R|null"}, {"purpose", "choose_pile.purpose"}, {"pile_index", "u32"}, {"piles", "[[R]]"}},
}

// The nested objects, typed the same way.
var (
	refShape     = []slot{{"object_id", "string"}, {"card_name", "string|null"}, {"owner_seat", "seat"}, {"controller_seat", "seat"}, {"zone", "zone"}}
	triggerShape = []slot{{"source", "R|null"}, {"source_name", "string|null"}, {"ability_index", "u32|null"}, {"event_objects", "[R]"}, {"instance", "u32"}, {"label", "string|null"}}
	targetForms  = map[string]string{"player": "seat", "object": "R"}
	itemForms    = map[string]string{"object": "R", "trigger": "trigger"}
	snakeCase    = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)
)

// KindFields is Section 7.2 and 7.3: each kind's fields, all required, no others.
var KindFields = func() map[string][]string {
	m := make(map[string][]string, len(kindTable))
	for kind, slots := range kindTable {
		m[kind] = make([]string, len(slots))
		for i, s := range slots {
			m[kind][i] = s.name
		}
	}
	return m
}()

var PriorityKinds = map[string]bool{"pass": true, "play_land": true, "cast_spell": true,
	"activate_mana_ability": true, "activate_ability": true, "special_action": true}

// Vocab is Sections 5.1, 6.10 and 7.4, keyed "<kind>.<field>" or a shared name.
var Vocab = map[string][]string{
	"zone":                         {"library", "hand", "battlefield", "graveyard", "stack", "exile", "command"},
	"select_object.purpose":        {"discard", "sacrifice", "exile", "destroy", "return_to_hand", "search", "reveal", "put_onto_battlefield", "put_into_hand", "put_into_graveyard", "legend_rule", "tap", "untap", "delve", "convoke", "attach", "keep", "vote", "modes", "other"},
	"finish_selection.purpose":     {"discard", "sacrifice", "exile", "destroy", "return_to_hand", "search", "reveal", "put_onto_battlefield", "put_into_hand", "put_into_graveyard", "legend_rule", "tap", "untap", "delve", "convoke", "attach", "keep", "vote", "modes", "other"},
	"choose_boolean.purpose":       {"may_ability", "optional_trigger", "may_cast", "change_copy_targets", "optional_replacement", "reveal", "other"},
	"choose_number.purpose":        {"x_value", "amount", "life_payment", "cost_repetitions", "vote", "other"},
	"choose_option.purpose":        {"effect_option", "top_or_bottom", "odd_or_even", "vote", "other"},
	"choose_color.purpose":         {"mana", "protection", "effect", "other"},
	"choose_name.purpose":          {"card_name", "creature_type", "card_type", "land_type", "basic_land_type", "other"},
	"order_pick.purpose":           {"triggers", "library_top", "library_bottom", "mulligan_bottom", "arrangement", "other"},
	"arrange_card.purpose":         {"scry", "surveil", "dig", "look_at_top", "pile_split", "other"},
	"arrange_card.destination":     {"top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1"},
	"distribute.purpose":           {"damage", "combat_damage", "counters", "mana", "life", "other"},
	"choose_pile.purpose":          {"effect", "other"},
	"method":                       {"normal", "alternative", "flashback", "escape", "evoke", "overload", "adventure", "disturb", "foretell", "plot", "mdfc_back", "split_left", "split_right", "fuse", "prototype", "morph", "disguise", "madness", "miracle", "cascade", "discover", "rebound", "suspend", "free", "other"},
	"optional_cost.cost":           {"kicker", "buyback", "entwine", "conspire", "casualty", "bargain", "gift", "offspring", "copy", "unless_payment", "additional", "other"},
	"choose_cost_target.cost_kind": {"sacrifice", "discard", "exile", "tap", "untap", "return_to_hand", "reveal", "remove_counter", "other"},
	"special_action.action":        {"turn_face_up", "plot", "foretell", "suspend", "unlock_door", "other"},
	"choose_replacement.event":     {"zone_change", "damage", "draw", "enter_battlefield", "counters", "life", "other"},
	"color":                        {"white", "blue", "black", "red", "green"},
	"mana_symbol":                  {"W", "U", "B", "R", "G", "C"},
	"card_type":                    {"artifact", "battle", "conspiracy", "creature", "dungeon", "enchantment", "instant", "kindred", "land", "phenomenon", "plane", "planeswalker", "scheme", "sorcery", "vanguard"},
}

// Semantic is a candidate's tagged object: Kind plus that kind's fields.
// Constructors store Go values (ObjectRef, TargetRef, OrderItem, their
// pointers for nullable fields, uint32, int32, string, *string, bool).
// UnmarshalJSON, the host's side, stores strings, bools, null (nil) and numbers
// (json.Number), and keeps objects and arrays as json.RawMessage: a generic map
// would re-sort the keys of nested references, so Marshal could not reproduce
// the engine's bytes.
type Semantic struct {
	Kind   string
	Fields map[string]any
}

func (s Semantic) MarshalJSON() ([]byte, error) {
	m := make(map[string]any, len(s.Fields)+1)
	for k, v := range s.Fields {
		m[k] = v
	}
	m["kind"] = s.Kind
	return json.Marshal(m)
}

// UnmarshalJSON accepts an object whose kind is a string; Check judges the
// other fields.
func (s *Semantic) UnmarshalJSON(b []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return fmt.Errorf("semantic: %w", err)
	}
	k, ok := raw["kind"]
	if !ok || k[0] != '"' {
		return errors.New("semantic: not an object with a string kind")
	}
	var kind string
	if err := json.Unmarshal(k, &kind); err != nil {
		return fmt.Errorf("semantic kind: %w", err)
	}
	delete(raw, "kind")
	fields := make(map[string]any, len(raw))
	for name, v := range raw {
		switch v[0] {
		case '{', '[':
			fields[name] = v
		case '"':
			var str string
			if err := json.Unmarshal(v, &str); err != nil {
				return fmt.Errorf("semantic field %s: %w", name, err)
			}
			fields[name] = str
		case 't', 'f':
			fields[name] = v[0] == 't'
		case 'n':
			fields[name] = nil
		default:
			fields[name] = json.Number(v) // the literal, as UseNumber keeps it
		}
	}
	s.Kind, s.Fields = kind, fields
	return nil
}

func sem(kind string, kv ...any) Semantic {
	f := make(map[string]any, len(kv)/2)
	for i := 0; i < len(kv); i += 2 {
		f[kv[i].(string)] = kv[i+1]
	}
	return Semantic{Kind: kind, Fields: f}
}

func Pass() Semantic { return sem("pass") }
func PlayLand(src ObjectRef, face uint32) Semantic {
	return sem("play_land", "source", src, "face", face)
}
func CastSpell(src ObjectRef, method string) Semantic {
	return sem("cast_spell", "source", src, "method", method)
}
func ActivateManaAbility(src ObjectRef, idx uint32, mana *string, cost *TargetRef) Semantic {
	return sem("activate_mana_ability", "source", src, "ability_index", idx, "mana_choice", mana, "cost_target", cost)
}
func ActivateAbility(src ObjectRef, idx uint32) Semantic {
	return sem("activate_ability", "source", src, "ability_index", idx)
}
func SpecialAction(src ObjectRef, action string) Semantic {
	return sem("special_action", "source", src, "action", action)
}
func ChooseTarget(src ObjectRef, slot uint32, t TargetRef, sel, lo, hi uint32) Semantic {
	return sem("choose_target", "source", src, "slot", slot, "target", t, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func FinishTargetSelection(src ObjectRef, slot, sel uint32) Semantic {
	return sem("finish_target_selection", "source", src, "slot", slot, "selected_count", sel)
}
func ChooseCostTarget(src ObjectRef, costKind string, cand ObjectRef, sel, lo, hi uint32) Semantic {
	return sem("choose_cost_target", "source", src, "cost_kind", costKind, "candidate", cand, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func ChooseSpellMode(src ObjectRef, idx, count, sel, lo, hi uint32) Semantic {
	return sem("choose_spell_mode", "source", src, "mode_index", idx, "mode_count", count, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func ChooseColor(src *ObjectRef, purpose, color string) Semantic {
	return sem("choose_color", "source", src, "purpose", purpose, "color", color)
}
func ChooseNumber(src *ObjectRef, purpose string, v, lo, hi int32) Semantic {
	return sem("choose_number", "source", src, "purpose", purpose, "value", v, "minimum", lo, "maximum", hi)
}
func ChooseBoolean(src *ObjectRef, purpose string, v bool) Semantic {
	return sem("choose_boolean", "source", src, "purpose", purpose, "value", v)
}
func ChooseName(src *ObjectRef, purpose, v string) Semantic {
	return sem("choose_name", "source", src, "purpose", purpose, "value", v)
}
func SelectObject(src *ObjectRef, purpose string, choice TargetRef, sel, lo, hi uint32) Semantic {
	return sem("select_object", "source", src, "purpose", purpose, "choice", choice, "selected_count", sel, "minimum", lo, "maximum", hi)
}
func FinishSelection(src *ObjectRef, purpose string, sel uint32) Semantic {
	return sem("finish_selection", "source", src, "purpose", purpose, "selected_count", sel)
}
func OptionalCost(src ObjectRef, cost string, pay bool) Semantic {
	return sem("optional_cost", "source", src, "cost", cost, "pay", pay)
}
func OptionalCast(card ObjectRef, method string, castIt bool) Semantic {
	return sem("optional_cast", "card", card, "method", method, "cast_it", castIt)
}
func Mulligan(handSize, taken uint32, keep bool) Semantic {
	return sem("mulligan", "hand_size", handSize, "mulligans_taken", taken, "keep", keep)
}
func OrderPick(src *ObjectRef, purpose string, item OrderItem, pos, count uint32) Semantic {
	return sem("order_pick", "source", src, "purpose", purpose, "item", item, "position", pos, "count", count)
}
func ArrangeCard(src *ObjectRef, purpose string, card ObjectRef, idx, count uint32, dest string) Semantic {
	return sem("arrange_card", "source", src, "purpose", purpose, "card", card, "card_index", idx, "card_count", count, "destination", dest)
}
func ChooseReplacement(affected TargetRef, event string, replSrc *ObjectRef, idx, count uint32) Semantic {
	return sem("choose_replacement", "affected", affected, "event", event, "replacement_source", replSrc, "replacement_index", idx, "replacement_count", count)
}
func DeclareAttack(attacker ObjectRef, defender *TargetRef) Semantic {
	return sem("declare_attack", "attacker", attacker, "defender", defender)
}
func DeclareBlock(blocker ObjectRef, attacker *ObjectRef) Semantic {
	return sem("declare_block", "blocker", blocker, "attacker", attacker)
}
func Distribute(src *ObjectRef, purpose string, recipient TargetRef, amount, remaining uint32) Semantic {
	return sem("distribute", "source", src, "purpose", purpose, "recipient", recipient, "amount", amount, "remaining", remaining)
}

func inVocab(list, v string) bool { return slices.Contains(Vocab[list], v) }

// show renders a field value for an error message as its JSON.
func show(v any) string {
	if b, err := json.Marshal(v); err == nil {
		return string(b)
	}
	return fmt.Sprint(v)
}

// integer is how Check reads every number: a Go integer type (constructors) or
// a json.Number (UnmarshalJSON). Anything else is an error, including a float64
// from a decoder without UseNumber and a literal with a fraction or exponent.
func integer(v any) (int64, error) {
	if n, ok := v.(json.Number); ok {
		i, err := n.Int64()
		if err != nil {
			return 0, fmt.Errorf("%s is not an integer", n)
		}
		return i, nil
	}
	switch rv := reflect.ValueOf(v); rv.Kind() {
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return rv.Int(), nil
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		if n := rv.Uint(); n <= math.MaxInt64 {
			return int64(n), nil
		}
		return 0, fmt.Errorf("%d is out of range", rv.Uint())
	}
	return 0, fmt.Errorf("%s (%T) is not an integer", show(v), v)
}

// isNull reports whether v marshals as JSON null.
func isNull(v any) bool {
	if v == nil {
		return true
	}
	switch rv := reflect.ValueOf(v); rv.Kind() {
	case reflect.Pointer, reflect.Map, reflect.Slice, reflect.Interface:
		return rv.IsNil()
	}
	return false
}

// text reads a string field: a string, or a *string as constructors store
// nullable ones.
func text(v any) (string, error) {
	switch x := v.(type) {
	case string:
		return x, nil
	case *string:
		if x != nil {
			return *x, nil
		}
	}
	return "", fmt.Errorf("%s (%T) is not a string", show(v), v)
}

// asDecoded returns a reference, target, item or array as UnmarshalJSON-style
// values (maps, slices, strings, bools, nil and json.Number), so a built value
// is judged exactly as its JSON would be. A TargetRef or OrderItem must set
// exactly one member, since MarshalJSON would hide the other.
func asDecoded(v any) (any, error) {
	switch v.(type) {
	case map[string]any, []any:
		return v, nil
	}
	if isNull(v) {
		return nil, nil
	}
	if r, ok := v.(interface{ oneMember() bool }); ok && !r.oneMember() {
		return nil, fmt.Errorf("%T must set exactly one member", v)
	}
	b, ok := v.(json.RawMessage)
	if !ok {
		var err error
		if b, err = json.Marshal(v); err != nil {
			return nil, err
		}
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var g any
	if err := d.Decode(&g); err != nil {
		return nil, err
	}
	return g, nil
}

// checkValue checks v against a kindTable type.
func checkValue(typ string, v any) error {
	base, nullable := strings.CutSuffix(typ, "|null")
	elem, isArray := strings.CutPrefix(base, "[")
	if isArray || base == "R" || base == "T" || base == "item" || base == "trigger" {
		var err error
		if v, err = asDecoded(v); err != nil {
			return err
		}
	}
	if isNull(v) {
		if nullable {
			return nil
		}
		return errors.New("is null")
	}
	switch {
	case isArray:
		a, ok := v.([]any)
		if !ok {
			return fmt.Errorf("%s is not an array", show(v))
		}
		for i, e := range a {
			if err := checkValue(strings.TrimSuffix(elem, "]"), e); err != nil {
				return fmt.Errorf("[%d]: %w", i, err)
			}
		}
		return nil
	case base == "R":
		return checkObject(v, refShape)
	case base == "trigger":
		return checkObject(v, triggerShape)
	case base == "T":
		return checkOneOf(v, targetForms)
	case base == "item":
		return checkOneOf(v, itemForms)
	case base == "u32":
		return inRange(v, 0, math.MaxUint32, base)
	case base == "i32":
		return inRange(v, math.MinInt32, math.MaxInt32, base)
	case base == "bool":
		if _, ok := v.(bool); !ok {
			return fmt.Errorf("%s is not a bool", show(v))
		}
		return nil
	}
	w, err := text(v)
	switch {
	case err != nil:
		return err
	case base == "string":
	case base == "seat":
		if w != "p0" && w != "p1" {
			return fmt.Errorf("%q is not a seat", w)
		}
	case base == "snake":
		if !snakeCase.MatchString(w) {
			return fmt.Errorf("%q is not a snake_case word", w)
		}
	case Vocab[base] == nil:
		return fmt.Errorf("unknown type %q", typ)
	case !inVocab(base, w):
		return fmt.Errorf("%q not in vocabulary %s", w, base)
	}
	return nil
}

func inRange(v any, lo, hi int64, typ string) error {
	n, err := integer(v)
	if err == nil && (n < lo || n > hi) {
		err = fmt.Errorf("%d is not a %s", n, typ)
	}
	return err
}

// checkObject checks that v is an object with exactly shape's fields.
func checkObject(v any, shape []slot) error {
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Errorf("%s is not an object", show(v))
	}
	if len(m) != len(shape) {
		return fmt.Errorf("%s has %d fields, want %d", show(v), len(m), len(shape))
	}
	for _, sl := range shape {
		fv, ok := m[sl.name]
		if !ok {
			return fmt.Errorf("%s lacks %s", show(v), sl.name)
		}
		if err := checkValue(sl.typ, fv); err != nil {
			return fmt.Errorf("%s: %w", sl.name, err)
		}
	}
	return nil
}

// checkOneOf checks that v is an object with exactly one of forms' members.
func checkOneOf(v any, forms map[string]string) error {
	m, ok := v.(map[string]any)
	if !ok || len(m) != 1 {
		return fmt.Errorf("%s is not an object with one member", show(v))
	}
	for k, fv := range m {
		typ, ok := forms[k]
		if !ok {
			return fmt.Errorf("unknown member %q", k)
		}
		if err := checkValue(typ, fv); err != nil {
			return fmt.Errorf("%s: %w", k, err)
		}
	}
	return nil
}

// Check enforces Sections 7.2 and 7.3 for constructed and decoded semantics
// alike: a known kind, exactly its fields, each field's kindTable type, the
// field constraints, and the static choose_name domain. A malformed value is
// an error, never a panic.
func (s Semantic) Check() error {
	slots, ok := kindTable[s.Kind]
	if !ok {
		return fmt.Errorf("unknown kind %q", s.Kind)
	}
	if len(slots) != len(s.Fields) {
		return fmt.Errorf("%s has %d fields, want %d", s.Kind, len(s.Fields), len(slots))
	}
	for _, sl := range slots {
		v, ok := s.Fields[sl.name]
		if !ok {
			return fmt.Errorf("%s lacks %s", s.Kind, sl.name)
		}
		if err := checkValue(sl.typ, v); err != nil {
			return fmt.Errorf("%s.%s: %w", s.Kind, sl.name, err)
		}
	}
	return s.checkConstraints()
}

// num and str read fields Check has already typed.
func (s Semantic) num(k string) int64  { n, _ := integer(s.Fields[k]); return n }
func (s Semantic) str(k string) string { w, _ := text(s.Fields[k]); return w }

// checkConstraints is Section 7.3's field constraints, plus the card_type
// domain of choose_name (Section 7.5 names the card types of Section 6.10).
func (s Semantic) checkConstraints() error {
	n := s.num
	switch s.Kind {
	case "choose_target", "choose_cost_target", "select_object":
		if sel, lo, hi := n("selected_count"), n("minimum"), n("maximum"); !(lo <= hi && sel < hi) {
			return fmt.Errorf("%s selected_count %d, minimum %d, maximum %d", s.Kind, sel, lo, hi)
		}
	case "choose_spell_mode":
		idx, count, sel, lo, hi := n("mode_index"), n("mode_count"), n("selected_count"), n("minimum"), n("maximum")
		if !(idx < count && lo <= hi && hi <= count && sel < hi) {
			return fmt.Errorf("choose_spell_mode mode_index %d, mode_count %d, selected_count %d, minimum %d, maximum %d", idx, count, sel, lo, hi)
		}
	case "choose_option":
		if idx, count := n("option_index"), n("option_count"); !(idx < count) {
			return fmt.Errorf("choose_option option_index %d, option_count %d", idx, count)
		}
	case "choose_number":
		if v, lo, hi := n("value"), n("minimum"), n("maximum"); !(lo <= v && v <= hi) {
			return fmt.Errorf("choose_number %d outside [%d,%d]", v, lo, hi)
		}
	case "order_pick":
		if pos, count := n("position"), n("count"); !(pos < count) {
			return fmt.Errorf("order_pick position %d, count %d", pos, count)
		}
	case "arrange_card":
		if idx, count := n("card_index"), n("card_count"); !(idx < count) {
			return fmt.Errorf("arrange_card card_index %d, card_count %d", idx, count)
		}
	case "choose_replacement":
		if idx, count := n("replacement_index"), n("replacement_count"); !(2 <= count && idx < count) {
			return fmt.Errorf("choose_replacement replacement_index %d, replacement_count %d", idx, count)
		}
	case "distribute":
		if amount, remaining := n("amount"), n("remaining"); !(amount <= remaining) {
			return fmt.Errorf("distribute amount %d, remaining %d", amount, remaining)
		}
	case "choose_pile":
		piles, _ := asDecoded(s.Fields["piles"])
		if a, _ := piles.([]any); !(n("pile_index") <= 1 && len(a) == 2) {
			return fmt.Errorf("choose_pile pile_index %d with %d piles", n("pile_index"), len(a))
		}
	case "choose_name":
		if s.str("purpose") == "card_type" && !inVocab("card_type", s.str("value")) {
			return fmt.Errorf("choose_name card_type %q is not a card type", s.str("value"))
		}
	}
	return nil
}
```

`internal/protocol/observation.go`:

```go
package protocol

type ManaPool struct {
	W uint32 `json:"W"`
	U uint32 `json:"U"`
	B uint32 `json:"B"`
	R uint32 `json:"R"`
	G uint32 `json:"G"`
	C uint32 `json:"C"`
}

type Characteristics struct {
	Supertypes []string `json:"supertypes"`
	Types      []string `json:"types"`
	Subtypes   []string `json:"subtypes"`
	Colors     []string `json:"colors"`
	ManaValue  uint32   `json:"mana_value"`
	Power      *int32   `json:"power"`
	Toughness  *int32   `json:"toughness"`
	Keywords   []string `json:"keywords"`
}

type Permanent struct {
	Tapped           bool                `json:"tapped"`
	SummoningSick    bool                `json:"summoning_sick"`
	Damage           uint32              `json:"damage"`
	Counters         map[string]uint32   `json:"counters"`
	AttachedTo       *TargetRef          `json:"attached_to"`
	Attacking        bool                `json:"attacking"`
	AttackTarget     *TargetRef          `json:"attack_target"`
	Blocking         bool                `json:"blocking"`
	BlockedAttackers []ObjectRef         `json:"blocked_attackers"`
	PhasedOut        bool                `json:"phased_out"`
	Statuses         []string            `json:"statuses"`
	ClassLevel       *uint32             `json:"class_level"`
	Chosen           []map[string]string `json:"chosen"`
}

type ObjectRecord struct {
	ObjectRef
	FullName        *string          `json:"full_name"`
	FaceDown        bool             `json:"face_down"`
	Token           bool             `json:"token"`
	Copy            bool             `json:"copy"`
	Characteristics *Characteristics `json:"characteristics"`
	Permanent       *Permanent       `json:"permanent"`
	ExiledBy        *ObjectRef       `json:"exiled_by"`
}

type PlayerObs struct {
	Seat                string            `json:"seat"`
	Life                int32             `json:"life"`
	Poison              *uint32           `json:"poison"`
	Counters            map[string]uint32 `json:"counters"`
	ManaPool            ManaPool          `json:"mana_pool"`
	LandsPlayedThisTurn uint32            `json:"lands_played_this_turn"`
	MulligansTaken      uint32            `json:"mulligans_taken"`
	Designations        []string          `json:"designations"`
	Progress            *Progress         `json:"progress"`
	HandCount           uint32            `json:"hand_count"`
	LibraryCount        uint32            `json:"library_count"`
	Hand                []ObjectRecord    `json:"hand"`
	Battlefield         []ObjectRecord    `json:"battlefield"`
	Graveyard           []ObjectRecord    `json:"graveyard"`
	Exile               []ObjectRecord    `json:"exile"`
	Command             []ObjectRecord    `json:"command"`
}

// Progress is Section 6.3's player progress. This engine leaves it null
// (player_progress is false).
type Progress struct {
	Dungeon     *string `json:"dungeon"`
	DungeonRoom *string `json:"dungeon_room"`
	RingTempted uint32  `json:"ring_tempted"`
	Speed       *uint32 `json:"speed"`
}

type StackEntry struct {
	ObjectRef
	StackKind       string           `json:"stack_kind"`
	Source          *ObjectRef       `json:"source"`
	FaceDown        bool             `json:"face_down"`
	Copy            bool             `json:"copy"`
	Characteristics *Characteristics `json:"characteristics"`
	Targets         []*TargetRef     `json:"targets"`
	Divided         []uint32         `json:"divided"`
	Modes           []uint32         `json:"modes"`
	XValue          *uint32          `json:"x_value"`
	Text            *string          `json:"text"`
}

type PendingTrigger struct {
	Source         *ObjectRef `json:"source"`
	SourceName     *string    `json:"source_name"`
	ControllerSeat string     `json:"controller_seat"`
	Label          *string    `json:"label"`
	Optional       bool       `json:"optional"`
}

type Known struct {
	OwnerSeat          string  `json:"owner_seat"`
	Zone               string  `json:"zone"`
	CardName           string  `json:"card_name"`
	ObjectID           *string `json:"object_id"`
	PositionFromTop    *uint32 `json:"position_from_top"`
	PositionFromBottom *uint32 `json:"position_from_bottom"`
	How                string  `json:"how"`
}

type Observation struct {
	Viewer          string           `json:"viewer"`
	Turn            uint32           `json:"turn"`
	PhaseStep       string           `json:"phase_step"`
	ActiveSeat      *string          `json:"active_seat"`
	PrioritySeat    *string          `json:"priority_seat"`
	PassedSeats     []string         `json:"passed_seats"`
	DayNight        *string          `json:"day_night"`
	Players         [2]PlayerObs     `json:"players"`
	Stack           []StackEntry     `json:"stack"`
	PendingTriggers []PendingTrigger `json:"pending_triggers"`
	Known           []Known          `json:"known"`
}
```

`internal/protocol/messages.go`:

```go
package protocol

import "encoding/json"

type Candidate struct {
	CandidateID uint32   `json:"candidate_id"`
	Semantic    Semantic `json:"semantic"`
	DisplayText *string  `json:"display_text"`
}

type Group struct {
	GroupID      uint64 `json:"group_id"`
	SubstepIndex uint32 `json:"substep_index"`
	SubstepCount uint32 `json:"substep_count"`
}

type Context struct {
	Kind    string     `json:"kind"`
	Source  *ObjectRef `json:"source"`
	Purpose *string    `json:"purpose"`
	Text    *string    `json:"text"`
	Rewind  bool       `json:"rewind"`
}

type SeatDecision struct {
	ActingSeat  string       `json:"acting_seat"`
	SeatStep    uint64       `json:"seat_step"`
	Group       Group        `json:"group"`
	Context     Context      `json:"context"`
	Observation Observation  `json:"observation"`
	Candidates  []Candidate  `json:"candidates"`
	Extensions  ExtensionMap `json:"extensions"`
}

// ExtensionMap is seat_decision.extensions (Section 14). It marshals as an
// object, {} when nil, never null (Section 9.3). Plain map literals assign to it.
type ExtensionMap map[string]json.RawMessage

func (e ExtensionMap) MarshalJSON() ([]byte, error) {
	if e == nil {
		return []byte("{}"), nil
	}
	return json.Marshal(map[string]json.RawMessage(e))
}

type Engine struct {
	Name             string  `json:"name"`
	Version          string  `json:"version"`
	SourceRevision   *string `json:"source_revision"`
	RulesSnapshotID  string  `json:"rules_snapshot_id"`
	CardPoolIdentity string  `json:"card_pool_identity"`
}

type Provenance struct {
	EngineName       string `json:"engine_name"`
	EngineVersion    string `json:"engine_version"`
	RulesSnapshotID  string `json:"rules_snapshot_id"`
	CardPoolIdentity string `json:"card_pool_identity"`
}

type CatalogDeck struct {
	CatalogID string    `json:"catalog_id"`
	Name      string    `json:"name"`
	Decklist  []DeckRow `json:"decklist"`
}

type DeckRow struct {
	Name  string `json:"name"`
	Count int    `json:"count"`
}

type Extension struct {
	Name      string `json:"name"`
	NativeIDs bool   `json:"native_ids"`
}

type HelloOK struct {
	ResponseType   string              `json:"response_type"`
	Protocol       string              `json:"protocol"`
	RequestID      string              `json:"request_id"`
	ProtocolMinor  uint32              `json:"protocol_minor"`
	Engine         Engine              `json:"engine"`
	Formats        []string            `json:"formats"`
	DeckSources    []string            `json:"deck_sources"`
	Catalog        []CatalogDeck       `json:"catalog"`
	RulesSupported map[string][]string `json:"rules_supported"`
	Observation    map[string]bool     `json:"observation"`
	DecisionKinds  []string            `json:"decision_kinds"`
	EngineDefaults map[string]*string  `json:"engine_defaults"`
	Rewind         bool                `json:"rewind"`
	Fairness       map[string]bool     `json:"fairness"`
	Extensions     []Extension         `json:"extensions"`
}

type DecisionResponse struct {
	ResponseType string       `json:"response_type"`
	Protocol     string       `json:"protocol"`
	RequestID    string       `json:"request_id"`
	GameID       string       `json:"game_id"`
	Step         uint64       `json:"step"`
	SeatDecision SeatDecision `json:"seat_decision"`
	Provenance   Provenance   `json:"provenance"`
}

type TerminalResponse struct {
	ResponseType   string     `json:"response_type"`
	Protocol       string     `json:"protocol"`
	RequestID      string     `json:"request_id"`
	GameID         string     `json:"game_id"`
	Outcome        string     `json:"outcome"`
	Classification string     `json:"classification"`
	Winner         *string    `json:"winner"`
	Reason         string     `json:"reason"`
	StepCount      uint64     `json:"step_count"`
	DecisionCount  uint64     `json:"decision_count"`
	Provenance     Provenance `json:"provenance"`
}

type ErrorBody struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type ErrorResponse struct {
	ResponseType string    `json:"response_type"`
	Protocol     string    `json:"protocol"`
	RequestID    string    `json:"request_id"`
	Error        ErrorBody `json:"error"`
}

type DeckOK struct {
	ResponseType string `json:"response_type"`
	Protocol     string `json:"protocol"`
	RequestID    string `json:"request_id"`
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/protocol/ -v`
Expected: all sixteen tests PASS, from `TestThirtyKinds` to `TestExtensionsMarshalAsAnObject`, including `TestDecodedSemanticsRoundTrip`, `TestCheckReadsNumbersExactly`, `TestEverySlotRejectsAWrongValue` and `TestCheckEnforcesEachConstraintClause`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/protocol && git commit -m "gorge adapter: v2 candidate kinds, observation and message types"
```

---

### Task 6: Request decoding and the closed error table

**Files:**
- Create: `internal/protocol/errors.go`, `internal/protocol/requests.go`
- Test: `internal/protocol/requests_test.go`

**Interfaces:**
- Consumes: `wire.CheckStrict` (Task 2), the protocol types (Task 5).
- Produces:
  - error code constants `protocol.CodeMalformedJSON` through `protocol.CodeGameAlreadyTerminal` (the 17 codes of Section 9.8);
  - `type protocol.Error struct{ Code, Message string }`;
  - `type protocol.Request struct{ Type, ID string; Line []byte; Hello *HelloReq; Reset *ResetReq; Step *StepReq; ValidateDeck *ValidateDeckReq; Probe *ProbeReq }`;
  - `func protocol.Decode(line []byte) (Request, *Error)`;
  - `type ResetReq struct{ GameID, Format string; Decks [2]DeckSpec; Rules Rules; GameSecret string; MaxDecisions, MaxSteps uint64 }`;
  - `type DeckSpec struct{ DeckID, CatalogID string; Decklist []DeckRow; IsDecklist bool }`;
  - `type Rules struct{ OpponentDecklist, Mulligan, StartingPlayer string; StartingSeat *string; DomainID string; Names []string; Extensions []string; Probe bool }`;
  - `type StepReq struct{ GameID string; ExpectedStep uint64; CandidateID uint64; Echo json.RawMessage }`.

Strict reading (G1-4): `json.Unmarshal` of JSON `null` into a string, bool or slice is a silent no-op, so every field goes through a getter that checks the raw value. A string starts with `"`, a bool is `true` or `false`, an array starts with `[` and holds only strings; a `null` `protocol` is `malformed_request`. Decklist rows are exactly `{name, count}` with a nonempty name, a count in [1, 2^32-1] and distinct names, for `reset` and `validate_deck`. `protocol_minor` and `samples` are u32 (Section 4.2).

- [ ] **Step 1: Write the failing test**

`internal/protocol/requests_test.go`:

```go
package protocol_test

import (
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

const goodReset = `{"request_type":"reset","protocol":"spellbench/v2","request_id":"h-2","game_id":"g-1","format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":"sha256:aa","catalog_id":"Burn"}},{"seat":"p1","deck":{"deck_id":"sha256:bb","catalog_id":"Spy"}}],"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":"sha256:cc","names":["Lightning Bolt"]},"extensions":["x_gorge_view_v1"],"probe":false},"game_secret":"7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e","max_decisions":10000,"max_steps":100000}`

func TestDecodeReset(t *testing.T) {
	req, perr := protocol.Decode([]byte(goodReset))
	if perr != nil {
		t.Fatal(perr)
	}
	r := req.Reset
	if req.ID != "h-2" || r.GameID != "g-1" || r.Decks[1].CatalogID != "Spy" || r.Rules.Mulligan != "london" ||
		*r.Rules.StartingSeat != "p0" || r.MaxSteps != 100000 || len(r.Rules.Extensions) != 1 {
		t.Fatalf("decoded %+v", req.Reset)
	}
	req, perr = protocol.Decode([]byte(withDecklist(`[{"name":"Mountain","count":40},{"count":20,"name":"Lightning Bolt"}]`)))
	if perr != nil || !req.Reset.Decks[0].IsDecklist || len(req.Reset.Decks[0].Decklist) != 2 || req.Reset.Decks[0].Decklist[1].Count != 20 {
		t.Fatalf("decklist deck: %+v %v", req.Reset, perr)
	}
}

// withDecklist gives seat p0 a decklist deck instead of its catalog deck.
func withDecklist(rows string) string {
	return strings.Replace(goodReset, `"catalog_id":"Burn"}`, `"decklist":`+rows+`}`, 1)
}

func validateDeck(rows string) string {
	return `{"request_type":"validate_deck","protocol":"spellbench/v2","request_id":"v","format":"pauper-bo1","deck":{"decklist":` + rows + `}}`
}

func TestDecodeErrorsUseTheClosedTable(t *testing.T) {
	cases := []struct{ line, code, id string }{
		{`{"request_type":"hello"`, protocol.CodeMalformedJSON, ""},
		{`[1]`, protocol.CodeMalformedRequest, ""},
		{`{"request_type":"hello","protocol":"spellbench/v2","request_id":5,"protocol_minor":0}`, protocol.CodeMalformedRequest, ""},
		{`{"request_type":"hello","protocol":"spellbench/v1","request_id":"a","protocol_minor":0}`, protocol.CodeProtocolMismatch, "a"},
		{`{"request_type":"hello","request_id":"a","protocol_minor":0}`, protocol.CodeMalformedRequest, "a"},
		{`{"request_type":"hello","protocol":"spellbench/v2","request_id":"a","protocol_minor":0,"x_extra":1}`, protocol.CodeMalformedRequest, "a"},
		{`{"request_type":"quit","protocol":"spellbench/v2","request_id":"a"}`, protocol.CodeMalformedRequest, "a"},
		{strings.Replace(goodReset, `"p1","deck"`, `"p0","deck"`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"catalog_id":"Burn"}`, `"catalog_id":"Burn","decklist":[]}`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"mulligan":"london"`, `"mulligan":"paris"`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `7648831b`, `7648831B`, 1), protocol.CodeMalformedRequest, "h-2"},
		{`{"request_type":"step","protocol":"spellbench/v2","request_id":"s","game_id":"g","expected_step":0,"selection":{"candidate_id":0}}`, protocol.CodeMalformedRequest, "s"},
		// JSON null is never a string, bool or array (G1-4), and protocol_minor is u32.
		{`{"request_type":"hello","protocol":null,"request_id":"a","protocol_minor":0}`, protocol.CodeMalformedRequest, "a"},
		{`{"request_type":null,"protocol":"spellbench/v2","request_id":"a","protocol_minor":0}`, protocol.CodeMalformedRequest, "a"},
		{`{"request_type":"hello","protocol":"spellbench/v2","request_id":"a","protocol_minor":4294967296}`, protocol.CodeMalformedRequest, "a"},
		{strings.Replace(goodReset, `"game_id":"g-1"`, `"game_id":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"format":"pauper-bo1"`, `"format":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"deck_id":"sha256:aa"`, `"deck_id":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"catalog_id":"Burn"`, `"catalog_id":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"opponent_decklist":"visible"`, `"opponent_decklist":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"domain_id":"sha256:cc"`, `"domain_id":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"names":["Lightning Bolt"]`, `"names":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"names":["Lightning Bolt"]`, `"names":["Lightning Bolt",null]`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"extensions":["x_gorge_view_v1"]`, `"extensions":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"probe":false`, `"probe":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{strings.Replace(goodReset, `"game_secret":"7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e"`, `"game_secret":null`, 1), protocol.CodeMalformedRequest, "h-2"},
		{`{"request_type":"step","protocol":"spellbench/v2","request_id":"s","game_id":null,"expected_step":0,"selection":{"candidate_id":0,"semantic_echo":{"kind":"pass"}}}`, protocol.CodeMalformedRequest, "s"},
		// Decklist rows are exactly {name, count}: count in [1, 2^32-1], names distinct and nonempty.
		{withDecklist(`[{"name":"Mountain","count":60,"x_note":1}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"Name":"Mountain","count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":0}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain"}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":4294967296}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"","count":60}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`[{"name":"Mountain","count":30},{"name":"Mountain","count":30}]`), protocol.CodeMalformedRequest, "h-2"},
		{withDecklist(`null`), protocol.CodeMalformedRequest, "h-2"},
		{validateDeck(`[{"name":"Mountain","count":30},{"name":"Mountain","count":30}]`), protocol.CodeMalformedRequest, "v"},
		{validateDeck(`[{"name":null,"count":60}]`), protocol.CodeMalformedRequest, "v"},
	}
	for _, c := range cases {
		req, perr := protocol.Decode([]byte(c.line))
		if perr == nil || perr.Code != c.code || req.ID != c.id {
			t.Errorf("%s: got %+v id %q, want %s id %q", c.line, perr, req.ID, c.code, c.id)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/protocol/ -run Decode`
Expected: FAIL with `undefined: protocol.Decode`.

- [ ] **Step 3: Write minimal implementation**

`internal/protocol/errors.go`:

```go
package protocol

const (
	CodeMalformedJSON          = "malformed_json"
	CodeMalformedRequest       = "malformed_request"
	CodeProtocolMismatch       = "protocol_mismatch"
	CodeRequestIDReuseMismatch = "request_id_reuse_mismatch"
	CodeStepBeforeReset        = "step_before_reset"
	CodeGameAlreadyActive      = "game_already_active"
	CodeGameIDMismatch         = "game_id_mismatch"
	CodeExpectedStepMismatch   = "expected_step_mismatch"
	CodeCandidateIDOutOfRange  = "candidate_id_out_of_range"
	CodeSemanticEchoMismatch   = "semantic_echo_mismatch"
	CodeUnsupportedFormat      = "unsupported_format"
	CodeUnsupportedDeck        = "unsupported_deck"
	CodeDeckIDMismatch         = "deck_id_mismatch"
	CodeUnsupportedRule        = "unsupported_rule"
	CodeUnsupportedRequest     = "unsupported_request"
	CodeProbeRefused           = "probe_refused"
	CodeGameAlreadyTerminal    = "game_already_terminal"
)

type Error struct{ Code, Message string }

func (e *Error) Error() string { return e.Code + ": " + e.Message }

func Errf(code, msg string) *Error { return &Error{Code: code, Message: msg} }
```

`internal/protocol/requests.go`:

```go
package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"slices"
	"strconv"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type HelloReq struct{ ProtocolMinor uint64 }

type DeckSpec struct {
	DeckID     string
	CatalogID  string
	Decklist   []DeckRow
	IsDecklist bool
}

type Rules struct {
	OpponentDecklist, Mulligan, StartingPlayer string
	StartingSeat                               *string
	DomainID                                   string
	Names                                      []string
	Extensions                                 []string
	Probe                                      bool
}

type ResetReq struct {
	GameID, Format         string
	Decks                  [2]DeckSpec
	Rules                  Rules
	GameSecret             string
	MaxDecisions, MaxSteps uint64
}

type StepReq struct {
	GameID       string
	ExpectedStep uint64
	CandidateID  uint64
	Echo         json.RawMessage
}

type ValidateDeckReq struct {
	Format string
	Deck   DeckSpec
}

type ProbeReq struct {
	GameID  string
	Samples uint64
}

type Request struct {
	Type, ID     string
	Line         []byte
	Hello        *HelloReq
	Reset        *ResetReq
	Step         *StepReq
	ValidateDeck *ValidateDeckReq
	Probe        *ProbeReq
}

type obj map[string]json.RawMessage

var errShape = errors.New("shape")

func exact(o obj, fields ...string) error {
	if len(o) != len(fields) {
		return fmt.Errorf("want fields %v", fields)
	}
	for _, f := range fields {
		if _, ok := o[f]; !ok {
			return fmt.Errorf("missing %s", f)
		}
	}
	return nil
}

// getStr reads a string field. JSON null or any other type is an error:
// json.Unmarshal of null into a string is a silent no-op.
func getStr(o obj, k string) (string, error) {
	raw := o[k]
	var s string
	if len(raw) == 0 || raw[0] != '"' || json.Unmarshal(raw, &s) != nil {
		return "", fmt.Errorf("%s is not a string", k)
	}
	return s, nil
}

// getBool reads a field that is exactly true or false.
func getBool(o obj, k string) (bool, error) {
	switch string(o[k]) {
	case "true":
		return true, nil
	case "false":
		return false, nil
	}
	return false, fmt.Errorf("%s is not a boolean", k)
}

// getStrings reads an array of strings; null and non-string elements are errors.
func getStrings(o obj, k string) ([]string, error) {
	raw := o[k]
	var elems []json.RawMessage
	if len(raw) == 0 || raw[0] != '[' || json.Unmarshal(raw, &elems) != nil {
		return nil, fmt.Errorf("%s is not an array of strings", k)
	}
	out := make([]string, 0, len(elems))
	for i, e := range elems {
		var s string
		if len(e) == 0 || e[0] != '"' || json.Unmarshal(e, &s) != nil {
			return nil, fmt.Errorf("%s[%d] is not a string", k, i)
		}
		out = append(out, s)
	}
	return out, nil
}

// getU64 accepts only an integer literal (json.Number would also take "5").
func getU64(o obj, k string) (uint64, error) {
	raw := o[k]
	if len(raw) == 0 || raw[0] < '0' || raw[0] > '9' {
		return 0, fmt.Errorf("%s is not a non-negative integer", k)
	}
	v, err := strconv.ParseUint(string(raw), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%s is not a non-negative integer", k)
	}
	return v, nil
}

// getU32 is getU64 bounded to u32 (Section 4.4).
func getU32(o obj, k string) (uint64, error) {
	v, err := getU64(o, k)
	if err != nil || v > math.MaxUint32 {
		return 0, fmt.Errorf("%s is not a u32", k)
	}
	return v, nil
}

func getObj(raw json.RawMessage) (obj, error) {
	var o obj
	if err := json.Unmarshal(raw, &o); err != nil || o == nil {
		return nil, fmt.Errorf("not an object")
	}
	return o, nil
}

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Decode parses one request line strictly. On error, Request.ID holds the
// request_id when it could be read, else "".
func Decode(line []byte) (Request, *Error) {
	req := Request{Line: line}
	if err := wire.CheckStrict(line); err != nil {
		var se *wire.StrictError
		if errors.As(err, &se) && se.Code == wire.CodeNotObject {
			return req, Errf(CodeMalformedRequest, se.Msg)
		}
		return req, Errf(CodeMalformedJSON, err.Error())
	}
	var o obj
	_ = json.Unmarshal(line, &o)
	if id, err := getStr(o, "request_id"); err == nil && id != "" {
		req.ID = id
	} else {
		return req, Errf(CodeMalformedRequest, "request_id is not a nonempty string")
	}
	ps, err := getStr(o, "protocol")
	if err != nil {
		return req, Errf(CodeMalformedRequest, "protocol is missing or not a string")
	}
	if ps != Name {
		return req, Errf(CodeProtocolMismatch, "protocol "+ps)
	}
	rt, err := getStr(o, "request_type")
	if err != nil {
		return req, Errf(CodeMalformedRequest, err.Error())
	}
	req.Type = rt
	var derr error
	switch rt {
	case "hello":
		derr = decodeHello(o, &req)
	case "reset":
		derr = decodeReset(o, &req)
	case "step":
		derr = decodeStep(o, &req)
	case "validate_deck":
		derr = decodeValidateDeck(o, &req)
	case "probe_resample":
		derr = decodeProbe(o, &req)
	default:
		derr = fmt.Errorf("unknown request_type %q", rt)
	}
	if derr != nil {
		return req, Errf(CodeMalformedRequest, derr.Error())
	}
	return req, nil
}

func decodeHello(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "protocol_minor"); err != nil {
		return err
	}
	m, err := getU32(o, "protocol_minor")
	req.Hello = &HelloReq{ProtocolMinor: m}
	return err
}

// decodeDecklist reads rows that are exactly {name, count}: a nonempty name,
// a count in [1, 2^32-1], and each name once.
func decodeDecklist(raw json.RawMessage) ([]DeckRow, error) {
	var elems []json.RawMessage
	if len(raw) == 0 || raw[0] != '[' || json.Unmarshal(raw, &elems) != nil {
		return nil, errors.New("decklist is not an array")
	}
	seen := map[string]bool{}
	rows := make([]DeckRow, 0, len(elems))
	for i, e := range elems {
		row, err := getObj(e)
		if err != nil || exact(row, "name", "count") != nil {
			return nil, fmt.Errorf("decklist[%d] is not exactly {name, count}", i)
		}
		name, err := getStr(row, "name")
		if err != nil || name == "" {
			return nil, fmt.Errorf("decklist[%d].name is not a nonempty string", i)
		}
		n, err := getU32(row, "count")
		if err != nil || n == 0 {
			return nil, fmt.Errorf("decklist[%d].count is not in [1, 2^32-1]", i)
		}
		if seen[name] {
			return nil, fmt.Errorf("decklist names %q twice", name)
		}
		seen[name] = true
		rows = append(rows, DeckRow{Name: name, Count: int(n)})
	}
	return rows, nil
}

func decodeDeck(raw json.RawMessage) (DeckSpec, error) {
	d, err := getObj(raw)
	if err != nil {
		return DeckSpec{}, err
	}
	var s DeckSpec
	if s.DeckID, err = getStr(d, "deck_id"); err != nil {
		return s, err
	}
	switch {
	case exact(d, "deck_id", "catalog_id") == nil:
		s.CatalogID, err = getStr(d, "catalog_id")
	case exact(d, "deck_id", "decklist") == nil:
		s.IsDecklist = true
		s.Decklist, err = decodeDecklist(d["decklist"])
	default:
		err = errors.New("deck must be {deck_id, catalog_id} or {deck_id, decklist}")
	}
	return s, err
}

func oneOf(v string, vals ...string) error {
	if !slices.Contains(vals, v) {
		return fmt.Errorf("%q not in %v", v, vals)
	}
	return nil
}

func decodeRules(raw json.RawMessage) (Rules, error) {
	var r Rules
	o, err := getObj(raw)
	if err != nil {
		return r, err
	}
	if err := exact(o, "opponent_decklist", "mulligan", "starting_player", "starting_seat", "card_name_domain", "extensions", "probe"); err != nil {
		return r, err
	}
	if r.OpponentDecklist, err = getStr(o, "opponent_decklist"); err != nil || oneOf(r.OpponentDecklist, "visible", "hidden") != nil {
		return r, errors.New("opponent_decklist")
	}
	if r.Mulligan, err = getStr(o, "mulligan"); err != nil || oneOf(r.Mulligan, "london", "none") != nil {
		return r, errors.New("mulligan")
	}
	if r.StartingPlayer, err = getStr(o, "starting_player"); err != nil || oneOf(r.StartingPlayer, "host_assigned", "toss_winner_chooses") != nil {
		return r, errors.New("starting_player")
	}
	if err := json.Unmarshal(o["starting_seat"], &r.StartingSeat); err != nil ||
		(r.StartingSeat != nil && oneOf(*r.StartingSeat, "p0", "p1") != nil) ||
		(r.StartingPlayer == "host_assigned") != (r.StartingSeat != nil) {
		return r, errors.New("starting_seat")
	}
	dom, err := getObj(o["card_name_domain"])
	if err != nil || exact(dom, "domain_id", "names") != nil {
		return r, errors.New("card_name_domain")
	}
	if r.DomainID, err = getStr(dom, "domain_id"); err != nil {
		return r, err
	}
	if r.Names, err = getStrings(dom, "names"); err != nil {
		return r, err
	}
	if r.Extensions, err = getStrings(o, "extensions"); err != nil {
		return r, err
	}
	if r.Probe, err = getBool(o, "probe"); err != nil {
		return r, err
	}
	return r, nil
}

func decodeReset(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "game_id", "format", "seats", "rules", "game_secret", "max_decisions", "max_steps"); err != nil {
		return err
	}
	r := &ResetReq{}
	var err error
	if r.GameID, err = getStr(o, "game_id"); err != nil || r.GameID == "" {
		return errors.New("game_id")
	}
	if r.Format, err = getStr(o, "format"); err != nil {
		return err
	}
	var seats []json.RawMessage
	if json.Unmarshal(o["seats"], &seats) != nil || len(seats) != 2 {
		return errors.New("seats must list p0 then p1")
	}
	for i, raw := range seats {
		s, err := getObj(raw)
		if err != nil || exact(s, "seat", "deck") != nil {
			return errors.New("seat entry shape")
		}
		if name, _ := getStr(s, "seat"); name != fmt.Sprintf("p%d", i) {
			return errors.New("seats must list p0 then p1")
		}
		if r.Decks[i], err = decodeDeck(s["deck"]); err != nil {
			return err
		}
	}
	if r.Rules, err = decodeRules(o["rules"]); err != nil {
		return err
	}
	if r.GameSecret, err = getStr(o, "game_secret"); err != nil || !hex64.MatchString(r.GameSecret) {
		return errors.New("game_secret must be 64 lowercase hex characters")
	}
	if r.MaxDecisions, err = getU64(o, "max_decisions"); err != nil {
		return err
	}
	if r.MaxSteps, err = getU64(o, "max_steps"); err != nil {
		return err
	}
	req.Reset = r
	return nil
}

func decodeStep(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "game_id", "expected_step", "selection"); err != nil {
		return err
	}
	s := &StepReq{}
	var err error
	if s.GameID, err = getStr(o, "game_id"); err != nil {
		return err
	}
	if s.ExpectedStep, err = getU64(o, "expected_step"); err != nil {
		return err
	}
	sel, err := getObj(o["selection"])
	if err != nil || exact(sel, "candidate_id", "semantic_echo") != nil {
		return errors.New("selection must be {candidate_id, semantic_echo}")
	}
	if s.CandidateID, err = getU64(sel, "candidate_id"); err != nil {
		return err
	}
	if _, err := getObj(sel["semantic_echo"]); err != nil {
		return errors.New("semantic_echo is not an object")
	}
	s.Echo = sel["semantic_echo"]
	req.Step = s
	return nil
}

func decodeValidateDeck(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "format", "deck"); err != nil {
		return err
	}
	v := &ValidateDeckReq{}
	var err error
	if v.Format, err = getStr(o, "format"); err != nil {
		return err
	}
	d, err := getObj(o["deck"])
	if err != nil {
		return err
	}
	switch {
	case exact(d, "catalog_id") == nil:
		v.Deck.CatalogID, err = getStr(d, "catalog_id")
	case exact(d, "decklist") == nil:
		v.Deck.IsDecklist = true
		v.Deck.Decklist, err = decodeDecklist(d["decklist"])
	default:
		err = errors.New("deck must be {catalog_id} or {decklist}")
	}
	req.ValidateDeck = v
	return err
}

func decodeProbe(o obj, req *Request) error {
	if err := exact(o, "request_type", "protocol", "request_id", "game_id", "samples"); err != nil {
		return err
	}
	p := &ProbeReq{}
	var err error
	if p.GameID, err = getStr(o, "game_id"); err != nil {
		return err
	}
	p.Samples, err = getU32(o, "samples")
	req.Probe = p
	return err
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/protocol/ -v`
Expected: all protocol tests PASS, including `TestDecodeReset` and `TestDecodeErrorsUseTheClosedTable`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/protocol && git commit -m "gorge adapter: strict v2 request decoding and error codes"
```

---

### Task 7: Deck catalog with Oracle names

**Files:**
- Create: `internal/catalog/catalog.go`
- Test: `internal/catalog/catalog_test.go`

**Interfaces:**
- Consumes: `wire.DeckRow`, `wire.DeckID` and `wire.DomainID` with their error results (Task 3 and its wire follow-up; whichever of this task and the follow-up merges second adapts these call sites), `testcorpus.Registry` (Task 1).
- Produces:
  - `type catalog.Deck struct{ CatalogID, Name string; Rows []wire.DeckRow }` with `func (Deck) DeckID() string`;
  - `func catalog.Decks() []Deck` (five decks, benchmark order Wildfire, Rally, Spy, Burn, CawGates);
  - `func catalog.ByID(id string) (Deck, bool)`;
  - `func catalog.Resolve(reg *cards.Registry, d Deck) ([]*cards.Card, error)` (row order, expanded by count);
  - `func catalog.Preflight(reg *cards.Registry) error`: every primitive the cards' scripts name is implemented. It checks primitives, not decisions: that every decision these cards raise maps to a declared kind (Section 9.2) is shown by the census and by Task 28b's games;
  - `func catalog.PoolNames() []string` (sorted distinct names).

G1-9, applied during implementation: the deck rows use keyed literals (`go vet` flags unkeyed ones), `catalog` imports `rules` for its registrations as `gorgepin` does, and the preflight comment names what proves decision-kind coverage. The merged task also added tests for near-miss names, catalog order and lookup contracts, and preflight refusals. The `DeckID` and `DomainID` call sites below take the error results of Task 3's Step 6, applied in the wire follow-up.

- [ ] **Step 1: Write the failing test**

`internal/catalog/catalog_test.go`:

```go
package catalog_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

// Deck ids recomputed independently (Python json.dumps sort_keys, ensure_ascii=False)
// from the mtg-kernel catalog lists with Oracle names; see the plan's evidence.
var wantIDs = map[string]string{
	"Wildfire": "sha256:32d59bef473236ee5861fa4b01932c11fff7ebc7a4fc4b7f189be99d9672e313",
	"Rally":    "sha256:b1b414074a7081c963838b0b82d91b85ce0c46b324feab0a1f542aaabeca73ea",
	"Spy":      "sha256:82b3117c82044353f15f1dc1f32a45614e379f17e6be5b8df267c5e29b59dbb8",
	"Burn":     "sha256:20e44003dba8100a83d84878c55f6736f1cb033ec76596a740cdbeb558b580c9",
	"CawGates": "sha256:84aa6f5edec314009ac290881520c308d581a5e04393f75ddb046c6354c46654",
}

func TestDeckIDsMatchHostComputation(t *testing.T) {
	for _, d := range catalog.Decks() {
		n := 0
		for _, r := range d.Rows {
			n += r.Count
		}
		if n != 60 {
			t.Errorf("%s has %d cards", d.CatalogID, n)
		}
		if d.DeckID() != wantIDs[d.CatalogID] {
			t.Errorf("%s deck_id %s, want %s", d.CatalogID, d.DeckID(), wantIDs[d.CatalogID])
		}
	}
	if got, err := wire.DomainID(catalog.PoolNames()); err != nil || got != "sha256:ab186e0272634f91dad9dd7b5765f33b69b3dc91bdfb1f6e43879be6ea49ba5b" {
		t.Errorf("pool domain_id %s %v", got, err)
	}
}

func TestEveryCatalogCardResolvesAndIsFullyPlayable(t *testing.T) {
	reg := testcorpus.Registry(t)
	if err := catalog.Preflight(reg); err != nil {
		t.Fatal(err)
	}
	spy, _ := catalog.ByID("Spy")
	cs, err := catalog.Resolve(reg, spy)
	if err != nil || len(cs) != 60 {
		t.Fatalf("Spy resolves to %d cards: %v", len(cs), err)
	}
}

func TestAsciiFoldedNameIsNotSubstituted(t *testing.T) {
	reg := testcorpus.Registry(t)
	bad := catalog.Deck{CatalogID: "X", Rows: []wire.DeckRow{{Name: "Troll of Khazad-dum", Count: 60}}}
	if _, err := catalog.Resolve(reg, bad); err == nil || !strings.Contains(err.Error(), "Troll of Khazad-dum") {
		t.Fatalf("ASCII-folded name resolved: %v", err)
	}
	nfd := catalog.Deck{CatalogID: "Y", Rows: []wire.DeckRow{{Name: "Lo\u0301rien Revealed", Count: 60}}}
	if _, err := catalog.Resolve(reg, nfd); err == nil {
		t.Fatal("NFD-decomposed name resolved")
	}
}

// gorge's Lookup finds each of these (case and punctuation folded, one face of
// a multi-face card, an alias), so each reaches the exact-name check.
func TestNearMissNamesGorgeFindsAreNotSubstituted(t *testing.T) {
	reg := testcorpus.Registry(t)
	for _, name := range []string{"lightning bolt", "KrarkClan Shaman", "Sagu Wildling", "Vector Glider", "Skittering Kitten"} {
		if _, ok := reg.Lookup(name); !ok {
			t.Fatalf("gorge no longer finds %q", name)
		}
		d := catalog.Deck{CatalogID: "Z", Rows: []wire.DeckRow{{Name: name, Count: 60}}}
		if _, err := catalog.Resolve(reg, d); err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("%q resolved: %v", name, err)
		}
	}
}

// Decks keeps benchmark order and distinct row names, ByID finds exactly the
// named deck, Resolve keeps row order expanded by count (the library order the
// shuffle starts from), and PoolNames is sorted and distinct.
func TestCatalogOrderAndLookupContracts(t *testing.T) {
	reg := testcorpus.Registry(t)
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.CatalogID)
		if got, ok := catalog.ByID(d.CatalogID); !ok || got.CatalogID != d.CatalogID {
			t.Errorf("ByID(%s) gave %q, %v", d.CatalogID, got.CatalogID, ok)
		}
		cs, err := catalog.Resolve(reg, d)
		if err != nil {
			t.Fatal(err)
		}
		seen, i := map[string]bool{}, 0
		for _, r := range d.Rows {
			if seen[r.Name] {
				t.Errorf("%s repeats %s", d.CatalogID, r.Name)
			}
			seen[r.Name] = true
			want, _ := reg.Lookup(r.Name)
			for n := 0; n < r.Count; n++ {
				if i >= len(cs) || cs[i] != want {
					t.Fatalf("%s card %d is not %s", d.CatalogID, i, r.Name)
				}
				i++
			}
		}
		if i != len(cs) {
			t.Errorf("%s resolves to %d cards, rows hold %d", d.CatalogID, len(cs), i)
		}
	}
	if got := strings.Join(ids, " "); got != "Wildfire Rally Spy Burn CawGates" {
		t.Errorf("decks in order %s", got)
	}
	if _, ok := catalog.ByID("Pauper"); ok {
		t.Error("an unknown catalog id was found")
	}
	names := catalog.PoolNames()
	for i := 1; i < len(names); i++ {
		if names[i-1] >= names[i] {
			t.Errorf("pool names %q, %q are not sorted and distinct", names[i-1], names[i])
		}
	}
}

// Preflight fails on a missing catalog card, and on a card that resolves but
// needs a primitive gorge does not implement.
func TestPreflightRefusesMissingAndUnplayableCards(t *testing.T) {
	if err := catalog.Preflight(cards.NewRegistry()); err == nil {
		t.Fatal("an empty registry passed")
	}
	// One synthetic card (authored here, not a Forge file), named for the
	// first row Preflight checks, with a keyword gorge does not implement.
	dir := t.TempDir()
	folder := cards.CorpusDir(dir)
	if err := os.MkdirAll(folder, 0o755); err != nil {
		t.Fatal(err)
	}
	first := catalog.Decks()[0].Rows[0].Name
	script := []byte("Name:" + first + "\nTypes:Land\nK:Spellbench Probe Keyword\nOracle:\n")
	if err := os.WriteFile(filepath.Join(folder, "first.txt"), script, 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := cards.OpenCorpus(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := catalog.Preflight(reg); err == nil || !strings.Contains(err.Error(), "kw:Spellbench Probe Keyword") {
		t.Fatalf("an unplayable card passed: %v", err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/catalog/`
Expected: FAIL with `undefined: catalog.Decks`.

- [ ] **Step 3: Write minimal implementation**

`internal/catalog/catalog.go`:

```go
// Package catalog holds the engine's catalog decks: the five Spellbench Pauper
// lists gorge plays fully, with Oracle names in NFC ("A // B" for multi-face).
package catalog

import (
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/effects"
	// rules registers its non-API primitives with effects.Supported; without
	// this import coverage checks undercount (see gorge cmd/forgec).
	_ "github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

// Deck is one catalog deck: its catalog_id, display name and decklist rows.
type Deck struct {
	CatalogID, Name string
	Rows            []wire.DeckRow
}

// DeckID is the deck's Section 4.3 deck_id. Catalog rows name each card once,
// so wire.DeckID (which refuses a repeated name) cannot fail here;
// TestDeckIDsMatchHostComputation pins every id.
func (d Deck) DeckID() string {
	id, err := wire.DeckID(d.Rows)
	if err != nil {
		panic("catalog deck " + d.CatalogID + ": " + err.Error())
	}
	return id
}

var decks = []Deck{
	{CatalogID: "Wildfire", Name: "Wildfire", Rows: []wire.DeckRow{
		{Name: "Twisted Landscape", Count: 4}, {Name: "Fanatical Offering", Count: 4}, {Name: "Ichor Wellspring", Count: 3}, {Name: "Blood Fountain", Count: 1},
		{Name: "Drossforge Bridge", Count: 4}, {Name: "Slagwoods Bridge", Count: 4}, {Name: "Writhing Chrysalis", Count: 4}, {Name: "Nyxborn Hydra", Count: 1},
		{Name: "Vault of Whispers", Count: 1}, {Name: "Cleansing Wildfire", Count: 4}, {Name: "Lembas", Count: 3}, {Name: "Makeshift Munitions", Count: 1},
		{Name: "Cast Down", Count: 4}, {Name: "Nihil Spellbomb", Count: 4}, {Name: "Swamp", Count: 3}, {Name: "Mountain", Count: 2}, {Name: "Forest", Count: 2},
		{Name: "Refurbished Familiar", Count: 4}, {Name: "Krark-Clan Shaman", Count: 3}, {Name: "Eviscerator's Insight", Count: 1}, {Name: "Toxin Analysis", Count: 2},
		{Name: "Pulse of Murasa", Count: 1},
	}},
	{CatalogID: "Rally", Name: "Rally", Rows: []wire.DeckRow{
		{Name: "Clockwork Percussionist", Count: 4}, {Name: "Voldaren Epicure", Count: 4}, {Name: "Goblin Bushwhacker", Count: 4},
		{Name: "Goblin Tomb Raider", Count: 4}, {Name: "Burning-Tree Emissary", Count: 4}, {Name: "Galvanic Blast", Count: 4},
		{Name: "Experimental Synthesizer", Count: 3}, {Name: "Lightning Bolt", Count: 4}, {Name: "Reckless Impulse", Count: 4},
		{Name: "Rally at the Hornburg", Count: 4}, {Name: "Great Furnace", Count: 4}, {Name: "Mountain", Count: 14}, {Name: "Chain Lightning", Count: 2},
		{Name: "End the Festivities", Count: 1},
	}},
	{CatalogID: "Spy", Name: "Spy", Rows: []wire.DeckRow{
		{Name: "Mesmeric Fiend", Count: 2}, {Name: "Overgrown Battlement", Count: 4}, {Name: "Saruli Caretaker", Count: 4}, {Name: "Gatecreeper Vine", Count: 3},
		{Name: "Sagu Wildling // Roost Seek", Count: 4}, {Name: "Generous Ent", Count: 4}, {Name: "Lead the Stampede", Count: 4}, {Name: "Winding Way", Count: 4},
		{Name: "Land Grant", Count: 4}, {Name: "Balustrade Spy", Count: 4}, {Name: "Lotleth Giant", Count: 2}, {Name: "Dread Return", Count: 2}, {Name: "Swamp", Count: 1},
		{Name: "Forest", Count: 3}, {Name: "Wall of Roots", Count: 3}, {Name: "Masked Vandal", Count: 3}, {Name: "Quirion Ranger", Count: 2},
		{Name: "Troll of Khazad-dûm", Count: 1}, {Name: "Lotus Petal", Count: 2}, {Name: "Tinder Wall", Count: 2}, {Name: "Elves of Deep Shadow", Count: 2},
	}},
	{CatalogID: "Burn", Name: "Burn", Rows: []wire.DeckRow{
		{Name: "Sneaky Snacker", Count: 4}, {Name: "Faithless Looting", Count: 2}, {Name: "Highway Robbery", Count: 4}, {Name: "Masked Meower", Count: 4},
		{Name: "Lightning Bolt", Count: 4}, {Name: "Mountain", Count: 18}, {Name: "Grab the Prize", Count: 4}, {Name: "Fireblast", Count: 4}, {Name: "Guttersnipe", Count: 4},
		{Name: "Fiery Temper", Count: 4}, {Name: "Voldaren Epicure", Count: 4}, {Name: "Lava Dart", Count: 4},
	}},
	{CatalogID: "CawGates", Name: "CawGates", Rows: []wire.DeckRow{
		{Name: "Island", Count: 4}, {Name: "Citadel Gate", Count: 4}, {Name: "Counterspell", Count: 4}, {Name: "Heap Gate", Count: 2}, {Name: "Idyllic Beachfront", Count: 1},
		{Name: "Brainstorm", Count: 3}, {Name: "Journey to Nowhere", Count: 4}, {Name: "Lórien Revealed", Count: 3}, {Name: "Outlaw Medic", Count: 2},
		{Name: "Basilisk Gate", Count: 4}, {Name: "Sacred Cat", Count: 4}, {Name: "Sea Gate", Count: 4}, {Name: "Azorius Guildgate", Count: 2},
		{Name: "The Modern Age // Vector Glider", Count: 4}, {Name: "Thraben Charm", Count: 2}, {Name: "Prismatic Strands", Count: 4},
		{Name: "Squadron Hawk", Count: 4}, {Name: "Spell Pierce", Count: 2}, {Name: "Preordain", Count: 2}, {Name: "Guardian of the Guildpact", Count: 1},
	}},
}

// Decks returns the catalog in benchmark order. The slice and its rows are
// shared: callers must not modify them.
func Decks() []Deck { return decks }

// ByID returns the catalog deck whose catalog_id is id.
func ByID(id string) (Deck, bool) {
	for _, d := range decks {
		if d.CatalogID == id {
			return d, true
		}
	}
	return Deck{}, false
}

// lookup resolves an Oracle name exactly. gorge's Lookup folds case and
// whitespace, drops punctuation and combining marks, reads only the front face
// of "A // B", and also finds a card by one face or an alias, so the card it
// finds must carry exactly this name: its faces joined with " // ".
func lookup(reg *cards.Registry, name string) (*cards.Card, error) {
	if !utf8.ValidString(name) {
		return nil, fmt.Errorf("card %q is not UTF-8", name)
	}
	c, ok := reg.Lookup(name)
	if !ok {
		return nil, fmt.Errorf("card %q is not in the corpus", name)
	}
	var faces []string
	for _, f := range c.Faces {
		faces = append(faces, f.Name)
	}
	full := faces[0]
	if len(faces) > 1 {
		full = strings.Join(faces, " // ")
	}
	if full != name {
		return nil, fmt.Errorf("card %q is %q in the corpus", name, full)
	}
	return c, nil
}

// Resolve returns d's cards in row order, each row repeated count times. A
// name that is not exactly a corpus card's Oracle name is an error, never a
// substitution.
func Resolve(reg *cards.Registry, d Deck) ([]*cards.Card, error) {
	var out []*cards.Card
	for _, r := range d.Rows {
		c, err := lookup(reg, r.Name)
		if err != nil {
			return nil, fmt.Errorf("deck %s: %w", d.CatalogID, err)
		}
		for i := 0; i < r.Count; i++ {
			out = append(out, c)
		}
	}
	return out, nil
}

// Preflight proves every catalog card resolves and is fully playable
// (every primitive its script names is implemented). It does not prove that
// the engine can offer every decision these cards raise (Section 9.2 makes
// such a deck unsupported_deck): the plan's decision-shape census (census5)
// and the Task 28 qualification prove decision-kind coverage.
func Preflight(reg *cards.Registry) error {
	sup := effects.Supported()
	for _, d := range decks {
		for _, r := range d.Rows {
			c, err := lookup(reg, r.Name)
			if err != nil {
				return fmt.Errorf("deck %s: %w", d.CatalogID, err)
			}
			if miss := reg.Unsupported(c, sup); len(miss) > 0 {
				return fmt.Errorf("deck %s: %s needs %v", d.CatalogID, r.Name, miss)
			}
		}
	}
	return nil
}

// PoolNames returns every catalog card name once, sorted in code point order.
func PoolNames() []string {
	set := map[string]bool{}
	for _, d := range decks {
		for _, r := range d.Rows {
			set[r.Name] = true
		}
	}
	var out []string
	for n := range set {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/catalog/ -v`
Expected: `--- PASS: TestDeckIDsMatchHostComputation`, `--- PASS: TestEveryCatalogCardResolvesAndIsFullyPlayable`, `--- PASS: TestAsciiFoldedNameIsNotSubstituted`, `--- PASS: TestNearMissNamesGorgeFindsAreNotSubstituted`, `--- PASS: TestCatalogOrderAndLookupContracts`, `--- PASS: TestPreflightRefusesMissingAndUnplayableCards`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/catalog && git commit -m "gorge adapter: five-deck catalog with Oracle names and pinned deck ids"
```

---

### Task 8: Game construction and secret-derived randomness

**Files:**
- Create: `internal/gamecfg/game.go`
- Test: `internal/gamecfg/game_test.go`

**Interfaces:**
- Consumes: `secrets.Game`, its `Stream` and `StreamSeed` methods (Task 4); `catalog.Resolve` (Task 7); `testcorpus.Registry` (Task 1).
- Produces:
  - `type gamecfg.Rules struct{ Mulligan string; StartingSeat state.PlayerID }`;
  - `type gamecfg.Game struct{ E *rules.Engine; Secret *secrets.Game }`;
  - `func gamecfg.New(reg *cards.Registry, sec *secrets.Game, decks [2][]*cards.Card, r Rules) (*Game, error)`;
  - `func (*Game) Submit(in decision.Intent) error` (checks the randomness invariant);
  - `func (*Game) CheckRandomness() error`;
  - `func (*Game) Probe(ins ...decision.Intent) (*rules.Engine, error)` (clone plus submits; the real engine is untouched);
  - `var gamecfg.ErrUnplannedRandomness`.

G1-10, applied during implementation, with its review fix round: tests recompute both opening libraries and a mulligan's shuffle (the seat's next ordinal) from the secret streams without the planner, and check the gorge seed; a probe test covers a shuffling probe and shows the real engine untouched; `New`'s errors are checked. `Probe`'s comment says a probe outcome may never shape a decision through hidden-zone contents (Section 13 F3).

- [ ] **Step 1: Write the failing test**

`internal/gamecfg/game_test.go`:

```go
package gamecfg_test

import (
	"context"
	"encoding/binary"
	"errors"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

func deck(t *testing.T, reg *cards.Registry, id string) []*cards.Card {
	d, _ := catalog.ByID(id)
	cs, err := catalog.Resolve(reg, d)
	if err != nil {
		t.Fatal(err)
	}
	return cs
}

func secret(b byte) *secrets.Game {
	s := make([]byte, 32)
	s[0] = b
	return secrets.NewGame(s)
}

func playOut(t *testing.T, g *gamecfg.Game) string {
	bots := [2]seat.Seat{seat.NewBot(1), seat.NewBot(2)}
	for n := 0; !g.E.G.Over && g.E.Pending() != nil && n < 50000; n++ {
		d := g.E.Pending()
		in, _ := bots[d.Player].Decide(context.Background(), view.Project(g.E.G, g.E, d.Player, d), *d)
		if err := g.Submit(in); err != nil {
			t.Fatalf("intent %d: %v", n, err)
		}
	}
	return g.E.L.Head()
}

func TestStartingSeatIsForcedAndGamesAreDeterministic(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	for _, start := range []state.PlayerID{0, 1} {
		a, err := gamecfg.New(reg, secret(7), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london", StartingSeat: start})
		if err != nil {
			t.Fatal(err)
		}
		if a.E.G.StartingPlayer != start {
			t.Fatalf("starting player %d, want %d", a.E.G.StartingPlayer, start)
		}
		b, _ := gamecfg.New(reg, secret(7), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london", StartingSeat: start})
		if playOut(t, a) != playOut(t, b) {
			t.Fatal("same secret and answers gave different chain heads")
		}
	}
}

func TestSeatOneLibraryIsIndependentOfSeatZero(t *testing.T) {
	reg := testcorpus.Registry(t)
	spy, burn := deck(t, reg, "Spy"), deck(t, reg, "Burn")
	a, _ := gamecfg.New(reg, secret(9), [2][]*cards.Card{spy, burn}, gamecfg.Rules{Mulligan: "none"})
	b, _ := gamecfg.New(reg, secret(9), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "none"})
	names := func(g *gamecfg.Game) (out []string) {
		for _, z := range []state.Zone{state.ZHand, state.ZLibrary} {
			for _, id := range g.E.G.Zone(z, 1) {
				out = append(out, g.E.G.Obj(id).Card.Faces[0].Name)
			}
		}
		return out
	}
	na, nb := names(a), names(b)
	for i := range na {
		if na[i] != nb[i] {
			t.Fatalf("seat 1 card %d differs (%s vs %s) when only seat 0's deck changed", i, na[i], nb[i])
		}
	}
}

func TestUnplannedRandomnessIsDetected(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	g, _ := gamecfg.New(reg, secret(3), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "none"})
	g.E.Rand(6) // an engine draw no planner supplied, as a Rand-using card would make
	if err := g.CheckRandomness(); !errors.Is(err, gamecfg.ErrUnplannedRandomness) {
		t.Fatalf("got %v", err)
	}
}

// fisherYates recomputes a Section 11.6 library shuffle from the spec alone:
// Fisher-Yates over in, driven by the stream of
// "spellbench/v2/rng:<owner>:library_shuffle:<n>".
func fisherYates(sec *secrets.Game, owner string, n uint64, in []state.ObjID) []state.ObjID {
	out := slices.Clone(in)
	r := sec.Stream(owner, "library_shuffle", n)
	for i := len(out) - 1; i > 0; i-- {
		j := r.IntN(i + 1)
		out[i], out[j] = out[j], out[i]
	}
	return out
}

// dealt is p's hand then library. A draw moves the library's top (index 0)
// to the end of the hand, so right after a shuffle and a fresh seven this is
// the shuffled order.
func dealt(g *gamecfg.Game, p state.PlayerID) []state.ObjID {
	return append(slices.Clone(g.E.G.Zone(state.ZHand, p)), g.E.G.Zone(state.ZLibrary, p)...)
}

// intent answers p's pending decision with its option of this kind.
func intent(t *testing.T, g *gamecfg.Game, p state.PlayerID, kind string) decision.Intent {
	t.Helper()
	d := g.E.Pending()
	if d == nil || d.Player != p {
		t.Fatalf("no pending decision for p%d", p)
	}
	for i, o := range d.Options {
		if o.Kind == kind {
			return decision.Intent{Seq: d.Seq, Player: p, Choices: []int{i}}
		}
	}
	t.Fatalf("p%d has no %q option", p, kind)
	return decision.Intent{}
}

// Both opening libraries, recomputed from the secret without the planner:
// gorge numbers objects from 1, seat by seat in deck order, and shuffles each
// library from that order. A swapped seat, ordinal or purpose fails here, and
// so does a gorge seed not taken from the shared stream.
func TestOpeningLibrariesFollowTheSecretStreams(t *testing.T) {
	reg := testcorpus.Registry(t)
	decks := [2][]*cards.Card{deck(t, reg, "Spy"), deck(t, reg, "Burn")}
	sec := secret(5)
	g, err := gamecfg.New(reg, sec, decks, gamecfg.Rules{Mulligan: "none"})
	if err != nil {
		t.Fatal(err)
	}
	next := state.ObjID(1)
	for p, owner := range []string{"p0", "p1"} {
		in := make([]state.ObjID, len(decks[p]))
		for i, c := range decks[p] {
			if o := g.E.G.Obj(next); o == nil || o.Card != c {
				t.Fatalf("object %d is not %s's deck card %d", next, owner, i)
			}
			in[i] = next
			next++
		}
		if got, want := dealt(g, state.PlayerID(p)), fisherYates(sec, owner, 0, in); !slices.Equal(got, want) {
			t.Fatalf("%s opening order\n got %v\nwant %v", owner, got, want)
		}
	}
	seed := sec.StreamSeed("shared", "gorge_seed", 0)
	if want := binary.BigEndian.Uint64(seed[:8]); g.E.L.Seed != want {
		t.Fatalf("gorge seed %d, want %d", g.E.L.Seed, want)
	}
}

// A London mulligan is the seat's second shuffle: ordinal 1 of its own
// stream, over its library with the hand moved to the end. gorge redraws when
// the declaration pass ends, so p1 answers first.
func TestMulliganShuffleUsesTheSeatsNextOrdinal(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	sec := secret(5)
	g, err := gamecfg.New(reg, sec, [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london"})
	if err != nil {
		t.Fatal(err)
	}
	in := append(slices.Clone(g.E.G.Zone(state.ZLibrary, 0)), g.E.G.Zone(state.ZHand, 0)...)
	if err := g.Submit(intent(t, g, 0, "mulligan")); err != nil {
		t.Fatal(err)
	}
	if err := g.Submit(intent(t, g, 1, "keep")); err != nil {
		t.Fatal(err)
	}
	if d := g.E.Pending(); d == nil || d.Kind != decision.KMulligan || d.Player != 0 {
		t.Fatal("p0 is not deciding on its redrawn hand")
	}
	if got, want := dealt(g, 0), fisherYates(sec, "p0", 1, in); !slices.Equal(got, want) {
		t.Fatalf("p0 order after the mulligan\n got %v\nwant %v", got, want)
	}
}

// Submit checks the invariant after every intent.
func TestSubmitReportsUnplannedRandomness(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	g, err := gamecfg.New(reg, secret(3), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london"})
	if err != nil {
		t.Fatal(err) // New ends with CheckRandomness, so the invariant holds here
	}
	in := intent(t, g, 0, "keep")
	g.E.Rand(6)
	if err := g.Submit(in); !errors.Is(err, gamecfg.ErrUnplannedRandomness) {
		t.Fatalf("got %v", err)
	}
}

// Probe answers on a clone, and an option the engine did not offer is an
// error. Probing p0's mulligan and p1's keep ends the pass, so the clone
// shuffles p0's redraw, yet the real engine's draws, planned count, head,
// pending decision and library stay put, and real submits still pass. A
// clone shuffles from its own generator, not the planner, so only a
// draw-free probe ends where the real submit arrives.
func TestProbeLeavesTheRealEngineUntouched(t *testing.T) {
	reg := testcorpus.Registry(t)
	burn := deck(t, reg, "Burn")
	build := func() *gamecfg.Game {
		g, err := gamecfg.New(reg, secret(3), [2][]*cards.Card{burn, burn}, gamecfg.Rules{Mulligan: "london"})
		if err != nil {
			t.Fatal(err)
		}
		return g
	}
	g, twin := build(), build()
	mull := intent(t, g, 0, "mulligan")
	if err := twin.Submit(mull); err != nil { // p1's keep is read off a twin game
		t.Fatal(err)
	}
	keep := intent(t, twin, 1, "keep")
	head, draws, lib := g.E.L.Head(), g.E.RNGDraws(), slices.Clone(g.E.G.Zone(state.ZLibrary, 0))
	if _, err := g.Probe(decision.Intent{Seq: mull.Seq, Player: 0, Choices: []int{2}}); err == nil {
		t.Fatal("probe accepted an option the engine did not offer")
	}
	c, err := g.Probe(mull, keep)
	if err != nil {
		t.Fatal(err)
	}
	if c.RNGDraws() == draws {
		t.Fatal("the probe drew nothing, so it cannot test the real engine's draws")
	}
	if got := g.E.RNGDraws(); got != draws {
		t.Errorf("real engine has %d draws after probing, want %d", got, draws)
	}
	if err := g.CheckRandomness(); err != nil {
		t.Errorf("probing moved the planned count: %v", err)
	}
	if g.E.L.Head() != head || g.E.Pending().Seq != mull.Seq || !slices.Equal(g.E.G.Zone(state.ZLibrary, 0), lib) {
		t.Error("probing moved the real engine's head, pending decision or library")
	}
	one, err := g.Probe(mull)
	if err != nil {
		t.Fatal(err)
	}
	if err := g.Submit(mull); err != nil {
		t.Fatal(err)
	}
	if one.L.Head() != g.E.L.Head() {
		t.Error("a draw-free probe did not end where the real submit arrives")
	}
	if err := g.Submit(keep); err != nil {
		t.Fatal(err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/gamecfg/`
Expected: FAIL with `undefined: gamecfg.New`.

- [ ] **Step 3: Write minimal implementation**

`internal/gamecfg/game.go`:

```go
// Package gamecfg builds a gorge engine whose every random draw comes from
// Section 11.6 streams: rules.NewHypotheticalPlanned asks a planner for each
// library shuffle (per player and ordinal), and the chance prefix forces the
// toss to the host-assigned starting seat. The hypothetical constructor is
// used deliberately as the live engine; see the plan's Global Constraints.
package gamecfg

import (
	"encoding/binary"
	"errors"
	"fmt"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

var ErrUnplannedRandomness = errors.New("engine_contract_failure:unplanned_randomness")

type Rules struct {
	Mulligan     string // "london" or "none"
	StartingSeat state.PlayerID
}

type Game struct {
	E       *rules.Engine
	Secret  *secrets.Game
	planned uint64 // draws the planner forced, plus the toss
}

// New returns the game at its first decision, even alongside a CheckRandomness error.
func New(reg *cards.Registry, sec *secrets.Game, decks [2][]*cards.Card, r Rules) (*Game, error) {
	g := &Game{Secret: sec, planned: 1}
	seed := sec.StreamSeed("shared", "gorge_seed", 0)
	cfg := rules.Config{
		Seed:         binary.BigEndian.Uint64(seed[:8]),
		Names:        []string{"p0", "p1"},
		Decks:        [][]*cards.Card{decks[0], decks[1]},
		Tokens:       reg.Tokens,
		NameUniverse: reg.Cards,
	}
	if r.Mulligan == "london" {
		cfg.Mulligans = 7
	}
	e, err := rules.NewHypotheticalPlanned(cfg, []rules.ChanceDraw{{Bound: 2, Value: int(r.StartingSeat)}}, g.plan)
	if err != nil {
		return nil, err
	}
	g.E = e
	if err := e.AdvanceHypothetical(); err != nil {
		return nil, err
	}
	return g, g.CheckRandomness()
}

// plan draws the shuffle of ctx.Player's library from that seat's own stream.
func (g *Game) plan(ctx rules.ShuffleContext) ([]state.ObjID, error) {
	r := g.Secret.Stream(fmt.Sprintf("p%d", ctx.Player), "library_shuffle", uint64(ctx.Ordinal))
	out := make([]state.ObjID, len(ctx.Library))
	for i, c := range ctx.Library {
		out[i] = c.ID
	}
	for i := len(out) - 1; i > 0; i-- {
		j := r.IntN(i + 1)
		out[i], out[j] = out[j], out[i]
	}
	if len(out) > 1 {
		g.planned += uint64(len(out) - 1)
	}
	return out, nil
}

// CheckRandomness fails when the engine drew a value no planner supplied.
func (g *Game) CheckRandomness() error {
	if got := g.E.RNGDraws(); got != g.planned {
		return fmt.Errorf("%w: %d draws, %d planned", ErrUnplannedRandomness, got, g.planned)
	}
	return nil
}

func (g *Game) Submit(in decision.Intent) error {
	if err := g.E.SubmitHypothetical(in); err != nil {
		return err
	}
	return g.CheckRandomness()
}

// Probe submits ins to a clone. Clones have no planner, so a probe's own
// shuffles draw from the clone's generator; probes judge legality only.
// A clone still holds the real hidden zones and the secret-seeded generator,
// so no probe outcome may set a decision's shape through hidden-zone
// contents (Section 13 F3); Task 28's resample check is the net.
func (g *Game) Probe(ins ...decision.Intent) (*rules.Engine, error) {
	c := g.E.Clone()
	for _, in := range ins {
		if err := c.SubmitHypothetical(in); err != nil {
			return nil, err
		}
	}
	return c, nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/gamecfg/ -v`
Expected: all seven tests PASS: `TestStartingSeatIsForcedAndGamesAreDeterministic`, `TestSeatOneLibraryIsIndependentOfSeatZero`, `TestUnplannedRandomnessIsDetected`, `TestOpeningLibrariesFollowTheSecretStreams`, `TestMulliganShuffleUsesTheSeatsNextOrdinal`, `TestSubmitReportsUnplannedRandomness`, `TestProbeLeavesTheRealEngineUntouched`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/gamecfg && git commit -m "gorge adapter: secret-derived per-seat shuffles, forced toss, randomness invariant"
```

---

### Task 9: Validator subset (Go)

**Files:**
- Create: `internal/validate/validate.go`
- Test: `internal/validate/validate_test.go`

**Interfaces:**
- Consumes: protocol types and `protocol.Semantic.Check` (Task 5).
- Produces:
  - `type validate.Profile struct{ Kinds map[string]bool; Flags map[string]bool; Extensions map[string]bool }`;
  - `type validate.Stream struct` (per-seat state: seat_step, groups, id zones, departed ids) with `func validate.NewStream(p Profile) *Stream`;
  - `func (*Stream) Check(sd protocol.SeatDecision) error`, which returns a `*validate.Violation{Rule, Msg string}` naming V1 to V9;
  - `func (*Stream) InGroup() bool`: whether the seat's last decision left a group partial, for the mini-host's cross-seat check (Task 25).

Checks beyond the base subset (G1-11): V1 a non-null `extensions` object; V4 every reference the observation holds (`context.source`, `attached_to`, `attack_target`, `blocked_attackers`, `exiled_by`, stack sources and targets, pending-trigger sources) and ids unique within the observation; V5 `known` shape, count and order (Section 6.7) and hidden-zone candidates in `(card_name, object_id)` order; V8 every optional field null exactly as its flag says (Section 6.9); V9 `activate_mana_ability` in a choice decision only beside `optional_cost` candidates with purpose `mana_payment`. Cross-seat group exclusivity needs both streams, so the mini-host checks it (Task 25). Decoded semantics hold nested references as raw JSON (Task 5), which `walkRefs` reads.

- [ ] **Step 1: Write the failing test**

`internal/validate/validate_test.go`:

```go
package validate_test

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

func profile() validate.Profile {
	return validate.Profile{Kinds: map[string]bool{"pass": true, "play_land": true, "declare_attack": true},
		Flags: map[string]bool{"pending_triggers": true, "keywords": true}}
}

func str(s string) *string { return &s }

func base(seatStep uint64, group uint64) protocol.SeatDecision {
	obs := protocol.Observation{Viewer: "p0", PhaseStep: "precombat_main", Stack: []protocol.StackEntry{},
		PendingTriggers: []protocol.PendingTrigger{}, Known: []protocol.Known{}}
	for i := range obs.Players {
		obs.Players[i] = protocol.PlayerObs{Seat: []string{"p0", "p1"}[i], Battlefield: []protocol.ObjectRecord{},
			Graveyard: []protocol.ObjectRecord{}, Exile: []protocol.ObjectRecord{}, Command: []protocol.ObjectRecord{}}
	}
	obs.Players[0].Hand = []protocol.ObjectRecord{}
	return protocol.SeatDecision{ActingSeat: "p0", SeatStep: seatStep, Group: protocol.Group{GroupID: group, SubstepCount: 1},
		Context: protocol.Context{Kind: "priority"}, Observation: obs,
		Candidates: []protocol.Candidate{{Semantic: protocol.Pass()}}, Extensions: map[string]json.RawMessage{}}
}

func rule(err error) string {
	var v *validate.Violation
	if errors.As(err, &v) {
		return v.Rule
	}
	return ""
}

func TestValidSequencePasses(t *testing.T) {
	s := validate.NewStream(profile())
	for i := uint64(0); i < 3; i++ {
		if err := s.Check(base(i, i)); err != nil {
			t.Fatalf("decision %d: %v", i, err)
		}
	}
}

func TestViolationsNameTheirRule(t *testing.T) {
	cases := map[string]func(*protocol.SeatDecision){
		"V2": func(sd *protocol.SeatDecision) { sd.Observation.Viewer = "p1" },
		"V3": func(sd *protocol.SeatDecision) { sd.SeatStep = 5 },
		"V5": func(sd *protocol.SeatDecision) { sd.Observation.Players[1].Hand = []protocol.ObjectRecord{} },
		"V8": func(sd *protocol.SeatDecision) { sd.Observation.DayNight = str("day") },
		"V9": func(sd *protocol.SeatDecision) { sd.Context.Kind = "choice" },
		"V1": func(sd *protocol.SeatDecision) {
			sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: 1, Semantic: protocol.Pass()})
		},
	}
	for want, mutate := range cases {
		s := validate.NewStream(profile())
		sd := base(0, 0)
		mutate(&sd)
		if got := rule(s.Check(sd)); got != want {
			t.Errorf("mutation for %s reported %q", want, got)
		}
	}
}

func TestIDFreshnessAcrossTheSeatStream(t *testing.T) {
	s := validate.NewStream(profile())
	name := "Mountain"
	rec := protocol.ObjectRecord{ObjectRef: protocol.ObjectRef{ObjectID: "o-1", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "hand"}}
	sd := base(0, 0)
	sd.Observation.Players[0].Hand = []protocol.ObjectRecord{rec}
	sd.Observation.Players[0].HandCount = 1
	if err := s.Check(sd); err != nil {
		t.Fatal(err)
	}
	rec.Zone = "battlefield" // same id, new zone: forbidden (V7)
	sd = base(1, 1)
	sd.Observation.Players[0].Battlefield = []protocol.ObjectRecord{rec}
	if got := rule(s.Check(sd)); got != "V7" {
		t.Fatalf("reused id across zones reported %q", got)
	}
}

// A host validates the engine's JSON after decoding it (Task 25). A decision
// with non-pass candidates must survive the round trip (G1-2).
func TestJSONDecodedDecisionValidates(t *testing.T) {
	hand := protocol.ObjectRef{ObjectID: "o-1", CardName: str("Mountain"), OwnerSeat: "p0", ControllerSeat: "p0", Zone: "hand"}
	sd := base(0, 0)
	sd.Observation.Players[0].Hand = []protocol.ObjectRecord{{ObjectRef: hand, Characteristics: &protocol.Characteristics{
		Supertypes: []string{"basic"}, Types: []string{"land"}, Subtypes: []string{"mountain"}, Colors: []string{}, Keywords: []string{}}}}
	sd.Observation.Players[0].HandCount = 1
	sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: 1, Semantic: protocol.PlayLand(hand, 0)})
	b, err := json.Marshal(protocol.DecisionResponse{ResponseType: "decision", Protocol: protocol.Name, SeatDecision: sd})
	if err != nil {
		t.Fatal(err)
	}
	var back protocol.DecisionResponse
	if err := json.Unmarshal(b, &back); err != nil {
		t.Fatal(err)
	}
	if err := validate.NewStream(profile()).Check(back.SeatDecision); err != nil {
		t.Fatalf("decoded decision: %v", err)
	}
}

func allKinds() validate.Profile {
	p := profile()
	p.Kinds = map[string]bool{}
	for k := range protocol.KindFields {
		p.Kinds[k] = true
	}
	return p
}

// populated has one permanent and one stack ability, so every reference
// field has a record to point at.
func populated() protocol.SeatDecision {
	sd := base(0, 0)
	perm := protocol.ObjectRef{ObjectID: "o-b", CardName: str("Mountain"), OwnerSeat: "p0", ControllerSeat: "p0", Zone: "battlefield"}
	sd.Observation.Players[0].Battlefield = []protocol.ObjectRecord{{ObjectRef: perm,
		Characteristics: &protocol.Characteristics{Supertypes: []string{}, Types: []string{"land"}, Subtypes: []string{}, Colors: []string{}, Keywords: []string{}},
		Permanent:       &protocol.Permanent{Counters: map[string]uint32{}, BlockedAttackers: []protocol.ObjectRef{}}}}
	ability := protocol.ObjectRef{ObjectID: "o-s", CardName: str("Mountain"), OwnerSeat: "p0", ControllerSeat: "p0", Zone: "stack"}
	sd.Observation.Stack = []protocol.StackEntry{{ObjectRef: ability, StackKind: "activated_ability", Source: &perm, Targets: []*protocol.TargetRef{}}}
	return sd
}

// searchFor sets up a library search whose candidates reference two looked-at
// cards, in the given name order.
func searchFor(sd *protocol.SeatDecision, first, second string) {
	ids := map[string]string{"Forest": "o-f", "Swamp": "o-w"}
	sd.Observation.Known = []protocol.Known{
		{OwnerSeat: "p0", Zone: "library", CardName: "Forest", ObjectID: str("o-f"), How: "searching"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Swamp", ObjectID: str("o-w"), How: "searching"},
	}
	sd.Context = protocol.Context{Kind: "choice"}
	sd.Candidates = nil
	for i, n := range []string{first, second} {
		r := protocol.ObjectRef{ObjectID: ids[n], CardName: str(n), OwnerSeat: "p0", ControllerSeat: "p0", Zone: "library"}
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i),
			Semantic: protocol.SelectObject(nil, "search", protocol.ObjectTarget(r), 0, 0, 1)})
	}
}

// G1-11: the structural rules beyond the base subset, one mutation each.
func TestStructuralRulesNameTheirRule(t *testing.T) {
	stranger := protocol.ObjectRef{ObjectID: "o-x", CardName: str("Swamp"), OwnerSeat: "p1", ControllerSeat: "p1", Zone: "battlefield"}
	zero, one := uint32(0), uint32(1)
	cases := []struct {
		rule, what string
		mutate     func(*protocol.SeatDecision)
	}{
		{"V1", "extensions null", func(sd *protocol.SeatDecision) { sd.Extensions = nil }},
		{"V4", "context.source", func(sd *protocol.SeatDecision) { sd.Context.Source = &stranger }},
		{"V4", "attached_to", func(sd *protocol.SeatDecision) {
			t := protocol.ObjectTarget(stranger)
			sd.Observation.Players[0].Battlefield[0].Permanent.AttachedTo = &t
		}},
		{"V4", "blocked_attackers", func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Battlefield[0].Permanent.BlockedAttackers = []protocol.ObjectRef{stranger}
		}},
		{"V4", "stack source", func(sd *protocol.SeatDecision) { sd.Observation.Stack[0].Source = &stranger }},
		{"V4", "stack target", func(sd *protocol.SeatDecision) {
			t := protocol.ObjectTarget(stranger)
			sd.Observation.Stack[0].Targets = []*protocol.TargetRef{&t}
		}},
		{"V4", "pending-trigger source", func(sd *protocol.SeatDecision) {
			sd.Observation.PendingTriggers = []protocol.PendingTrigger{{Source: &stranger, ControllerSeat: "p1"}}
		}},
		{"V4", "duplicate id", func(sd *protocol.SeatDecision) {
			rec := sd.Observation.Players[0].Battlefield[0]
			sd.Observation.Players[0].Battlefield = append(sd.Observation.Players[0].Battlefield, rec)
		}},
		{"V5", "own hand in known", func(sd *protocol.SeatDecision) {
			sd.Observation.Known = []protocol.Known{{OwnerSeat: "p0", Zone: "hand", CardName: "Mountain", How: "revealed"}}
		}},
		{"V5", "two library positions", func(sd *protocol.SeatDecision) {
			sd.Observation.Known = []protocol.Known{{OwnerSeat: "p0", Zone: "library", CardName: "Mountain",
				PositionFromTop: &zero, PositionFromBottom: &zero, How: "looked_at"}}
		}},
		{"V5", "known order", func(sd *protocol.SeatDecision) {
			sd.Observation.Known = []protocol.Known{
				{OwnerSeat: "p0", Zone: "library", CardName: "Mountain", PositionFromTop: &one, How: "looked_at"},
				{OwnerSeat: "p0", Zone: "library", CardName: "Mountain", PositionFromTop: &zero, How: "looked_at"}}
		}},
		{"V5", "more hand entries than cards", func(sd *protocol.SeatDecision) {
			sd.Observation.Known = []protocol.Known{{OwnerSeat: "p1", Zone: "hand", CardName: "Mountain", How: "revealed"}}
		}},
		{"V5", "hidden-zone candidate order", func(sd *protocol.SeatDecision) { searchFor(sd, "Swamp", "Forest") }},
		{"V8", "keywords null with its flag", func(sd *protocol.SeatDecision) {
			sd.Observation.Players[0].Battlefield[0].Characteristics.Keywords = nil
		}},
		{"V8", "poison without its flag", func(sd *protocol.SeatDecision) { sd.Observation.Players[0].Poison = &one }},
		{"V9", "mana ability without optional_cost", func(sd *protocol.SeatDecision) {
			sd.Context = protocol.Context{Kind: "choice", Purpose: str("mana_payment")}
			sd.Candidates = []protocol.Candidate{{Semantic: protocol.ActivateManaAbility(sd.Observation.Players[0].Battlefield[0].ObjectRef, 0, nil, nil)}}
		}},
	}
	if err := validate.NewStream(allKinds()).Check(populated()); err != nil {
		t.Fatalf("clean decision: %v", err)
	}
	sorted := populated()
	searchFor(&sorted, "Forest", "Swamp")
	if err := validate.NewStream(allKinds()).Check(sorted); err != nil {
		t.Fatalf("sorted search: %v", err)
	}
	for _, c := range cases {
		sd := populated()
		c.mutate(&sd)
		if got := rule(validate.NewStream(allKinds()).Check(sd)); got != c.rule {
			t.Errorf("%s reported %q, want %s", c.what, got, c.rule)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/validate/`
Expected: FAIL with `undefined: validate.NewStream`.

- [ ] **Step 3: Write minimal implementation**

`internal/validate/validate.go`:

```go
// Package validate is a Go subset of the Section 11.3 live validator, used by
// this adapter's tests and qualification until sub-project P's validator runs.
package validate

import (
	"encoding/json"
	"fmt"
	"regexp"
	"slices"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

type Violation struct{ Rule, Msg string }

func (v *Violation) Error() string { return v.Rule + ": " + v.Msg }

func vio(rule, format string, a ...any) error { return &Violation{Rule: rule, Msg: fmt.Sprintf(format, a...)} }

type Profile struct {
	Kinds      map[string]bool
	Flags      map[string]bool
	Extensions map[string]bool
}

type Stream struct {
	p            Profile
	nextSeatStep uint64
	group        *protocol.Group // open group, nil when none
	nextGroup    uint64
	zoneOf       map[string]string // object id -> the one zone it appeared in
	live         map[string]bool   // ids in the previous decision
	departed     map[string]bool   // ids that left the stream
}

func NewStream(p Profile) *Stream {
	return &Stream{p: p, zoneOf: map[string]string{}, live: map[string]bool{}, departed: map[string]bool{}}
}

// InGroup reports whether this seat's last decision left a group partial. The
// mini-host checks it across its two streams: while one seat's group is
// partial, the engine poses nothing to the other seat (Section 8, V3).
func (s *Stream) InGroup() bool { return s.group != nil }

var extKey = regexp.MustCompile(`^x_[a-z0-9_]+$`)

// EqualRef compares references by value (CardName is a pointer).
func EqualRef(a, b protocol.ObjectRef) bool {
	return a.ObjectID == b.ObjectID && a.OwnerSeat == b.OwnerSeat && a.ControllerSeat == b.ControllerSeat &&
		a.Zone == b.Zone && (a.CardName == nil) == (b.CardName == nil) && (a.CardName == nil || *a.CardName == *b.CardName)
}

// records collects every object record of the observation by id (zone
// arrays, stack entries, and known entries that carry an id). An id may
// appear only once.
func records(o protocol.Observation) (map[string]protocol.ObjectRef, error) {
	out := map[string]protocol.ObjectRef{}
	add := func(r protocol.ObjectRef) error {
		if _, ok := out[r.ObjectID]; ok {
			return vio("V4", "id %s appears twice in the observation", r.ObjectID)
		}
		out[r.ObjectID] = r
		return nil
	}
	for _, p := range o.Players {
		for _, zone := range [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command} {
			for _, rec := range zone {
				if rec.Zone == "library" {
					return nil, vio("V5", "zone array holds library object %s", rec.ObjectID)
				}
				if err := add(rec.ObjectRef); err != nil {
					return nil, err
				}
			}
		}
	}
	for _, s := range o.Stack {
		if err := add(s.ObjectRef); err != nil {
			return nil, err
		}
	}
	for _, k := range o.Known {
		if k.ObjectID != nil {
			name := k.CardName
			if err := add(protocol.ObjectRef{ObjectID: *k.ObjectID, CardName: &name, OwnerSeat: k.OwnerSeat, ControllerSeat: k.OwnerSeat, Zone: k.Zone}); err != nil {
				return nil, err
			}
		}
	}
	return out, nil
}

// walkRefs visits every object reference inside a candidate semantic.
func walkRefs(v any, visit func(protocol.ObjectRef) error) error {
	b, _ := json.Marshal(v)
	var generic any
	json.Unmarshal(b, &generic)
	var walk func(any) error
	walk = func(x any) error {
		switch t := x.(type) {
		case map[string]any:
			if id, ok := t["object_id"].(string); ok {
				var r protocol.ObjectRef
				rb, _ := json.Marshal(t)
				json.Unmarshal(rb, &r)
				r.ObjectID = id
				return visit(r)
			}
			for _, e := range t {
				if err := walk(e); err != nil {
					return err
				}
			}
		case []any:
			for _, e := range t {
				if err := walk(e); err != nil {
					return err
				}
			}
		}
		return nil
	}
	return walk(generic)
}

// observationRefs visits every non-null object reference the observation
// holds outside its records: attachments, attack targets, blocked attackers,
// exiled_by, stack sources and targets, pending-trigger sources (V4).
func observationRefs(o protocol.Observation, visit func(where string, r protocol.ObjectRef) error) error {
	target := func(where string, t *protocol.TargetRef) error {
		if t != nil && t.Object != nil {
			return visit(where, *t.Object)
		}
		return nil
	}
	for _, p := range o.Players {
		for _, zone := range [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command} {
			for _, rec := range zone {
				if rec.ExiledBy != nil {
					if err := visit("exiled_by of "+rec.ObjectID, *rec.ExiledBy); err != nil {
						return err
					}
				}
				pm := rec.Permanent
				if pm == nil {
					continue
				}
				if err := target("attached_to of "+rec.ObjectID, pm.AttachedTo); err != nil {
					return err
				}
				if err := target("attack_target of "+rec.ObjectID, pm.AttackTarget); err != nil {
					return err
				}
				for _, a := range pm.BlockedAttackers {
					if err := visit("blocked_attackers of "+rec.ObjectID, a); err != nil {
						return err
					}
				}
			}
		}
	}
	for _, st := range o.Stack {
		if st.Source != nil {
			if err := visit("source of "+st.ObjectID, *st.Source); err != nil {
				return err
			}
		}
		for _, t := range st.Targets {
			if err := target("target of "+st.ObjectID, t); err != nil {
				return err
			}
		}
	}
	for i, pt := range o.PendingTriggers {
		if pt.Source != nil {
			if err := visit(fmt.Sprintf("pending trigger %d", i), *pt.Source); err != nil {
				return err
			}
		}
	}
	return nil
}

var knownHow = []string{"revealed", "looked_at", "from_public_zone", "own_placement", "searching", "tracked"}

func cmpU(a, b *uint32) int {
	switch {
	case a == nil && b == nil:
		return 0
	case a == nil:
		return -1
	case b == nil:
		return 1
	case *a < *b:
		return -1
	case *a > *b:
		return 1
	}
	return 0
}

func cmpS(a, b *string) int {
	switch {
	case a == nil && b == nil:
		return 0
	case a == nil:
		return -1
	case b == nil:
		return 1
	case *a < *b:
		return -1
	case *a > *b:
		return 1
	}
	return 0
}

// knownOrder is Section 6.7's order: owner_seat, zone, card_name,
// position_from_top, position_from_bottom, how, object_id (nulls first).
func knownOrder(a, b protocol.Known) int {
	for _, c := range [][2]string{{a.OwnerSeat, b.OwnerSeat}, {a.Zone, b.Zone}, {a.CardName, b.CardName}} {
		if c[0] != c[1] {
			if c[0] < c[1] {
				return -1
			}
			return 1
		}
	}
	if c := cmpU(a.PositionFromTop, b.PositionFromTop); c != 0 {
		return c
	}
	if c := cmpU(a.PositionFromBottom, b.PositionFromBottom); c != 0 {
		return c
	}
	if a.How != b.How {
		if a.How < b.How {
			return -1
		}
		return 1
	}
	return cmpS(a.ObjectID, b.ObjectID)
}

// checkKnown is V5's knowledge rules (Section 6.7): shape, count and order.
func checkKnown(o protocol.Observation) error {
	hand := map[string]uint32{}
	for i, k := range o.Known {
		switch {
		case k.Zone != "hand" && k.Zone != "library":
			return vio("V5", "known %d has zone %q", i, k.Zone)
		case !slices.Contains(knownHow, k.How):
			return vio("V5", "known %d has how %q", i, k.How)
		case k.CardName == "":
			return vio("V5", "known %d has no card name", i)
		case k.Zone == "hand" && k.OwnerSeat == o.Viewer:
			return vio("V5", "known %d lists the viewer's own hand", i)
		case k.Zone == "hand" && (k.PositionFromTop != nil || k.PositionFromBottom != nil):
			return vio("V5", "known hand entry %d has a position", i)
		case k.Zone == "library" && k.How != "searching" && (k.PositionFromTop == nil) == (k.PositionFromBottom == nil):
			return vio("V5", "known library entry %d needs exactly one position", i)
		case k.Zone == "library" && k.PositionFromTop != nil && k.PositionFromBottom != nil:
			return vio("V5", "known library entry %d has two positions", i)
		}
		if k.Zone == "hand" {
			hand[k.OwnerSeat]++
		}
		if i > 0 && knownOrder(o.Known[i-1], k) > 0 {
			return vio("V5", "known entries %d and %d are out of order", i-1, i)
		}
	}
	for _, p := range o.Players {
		if hand[p.Seat] > p.HandCount {
			return vio("V5", "%d known hand entries for %s, hand_count %d", hand[p.Seat], p.Seat, p.HandCount)
		}
	}
	return nil
}

// hiddenKey returns the smallest (card_name, object_id) key among the
// hidden-zone cards a candidate references, if any: library cards, and cards
// in the other seat's hand.
func hiddenKey(viewer string, sem protocol.Semantic) (string, bool) {
	key, found := "", false
	walkRefs(sem, func(r protocol.ObjectRef) error {
		if r.Zone == "library" || (r.Zone == "hand" && r.OwnerSeat != viewer) {
			name := ""
			if r.CardName != nil {
				name = *r.CardName
			}
			if k := name + "\x00" + r.ObjectID; !found || k < key {
				key, found = k, true
			}
		}
		return nil
	})
	return key, found
}

// checkFlags is V8's optional-field rule (Section 6.9): a field whose flag is
// false is null; with the flag true it is null only where Section 6.9 allows
// (full_name, exiled_by, stack text, class_level).
func (s *Stream) checkFlags(o protocol.Observation) error {
	on := s.p.Flags
	field := func(flag string, isNull bool, what string) error {
		if on[flag] == isNull {
			if isNull {
				return vio("V8", "%s is null with %s true", what, flag)
			}
			return vio("V8", "%s is set with %s false", what, flag)
		}
		return nil
	}
	nullable := func(flag string, isNull bool, what string) error {
		if !on[flag] && !isNull {
			return vio("V8", "%s is set with %s false", what, flag)
		}
		return nil
	}
	chars := func(c *protocol.Characteristics, what string) error {
		if c == nil {
			return nil
		}
		return field("keywords", c.Keywords == nil, "keywords of "+what)
	}
	checks := []error{
		field("day_night", o.DayNight == nil, "day_night"),
		field("passed_seats", o.PassedSeats == nil, "passed_seats"),
		field("pending_triggers", o.PendingTriggers == nil, "pending_triggers"),
	}
	for _, p := range o.Players {
		checks = append(checks,
			field("poison", p.Poison == nil, "poison of "+p.Seat),
			field("player_counters", p.Counters == nil, "counters of "+p.Seat),
			field("designations", p.Designations == nil, "designations of "+p.Seat),
			field("player_progress", p.Progress == nil, "progress of "+p.Seat))
		for _, zone := range [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command} {
			for _, rec := range zone {
				checks = append(checks, chars(rec.Characteristics, rec.ObjectID),
					nullable("full_name", rec.FullName == nil, "full_name of "+rec.ObjectID),
					nullable("exiled_by", rec.ExiledBy == nil, "exiled_by of "+rec.ObjectID))
				if pm := rec.Permanent; pm != nil {
					checks = append(checks,
						field("permanent_details", pm.Statuses == nil, "statuses of "+rec.ObjectID),
						field("permanent_details", pm.Chosen == nil, "chosen of "+rec.ObjectID),
						nullable("permanent_details", pm.ClassLevel == nil, "class_level of "+rec.ObjectID))
				}
			}
		}
	}
	for _, st := range o.Stack {
		checks = append(checks, chars(st.Characteristics, st.ObjectID), nullable("stack_text", st.Text == nil, "text of "+st.ObjectID))
	}
	for _, err := range checks {
		if err != nil {
			return err
		}
	}
	return nil
}

func (s *Stream) Check(sd protocol.SeatDecision) error {
	o := sd.Observation
	// V2
	if o.Viewer != sd.ActingSeat {
		return vio("V2", "viewer %s, acting seat %s", o.Viewer, sd.ActingSeat)
	}
	// V3
	if sd.SeatStep != s.nextSeatStep {
		return vio("V3", "seat_step %d, want %d", sd.SeatStep, s.nextSeatStep)
	}
	g := sd.Group
	if s.group != nil {
		if g.GroupID != s.group.GroupID || g.SubstepIndex != s.group.SubstepIndex+1 || g.SubstepCount != s.group.SubstepCount {
			return vio("V3", "partial group %d not continued", s.group.GroupID)
		}
	} else if g.GroupID != s.nextGroup || g.SubstepIndex != 0 || g.SubstepCount == 0 {
		return vio("V3", "group %d/%d, want new group %d", g.GroupID, g.SubstepIndex, s.nextGroup)
	}
	// V1 candidates and the extensions object
	if sd.Extensions == nil {
		return vio("V1", "extensions is null, not an object")
	}
	if len(sd.Candidates) == 0 || len(sd.Candidates) > 4096 {
		return vio("V1", "%d candidates", len(sd.Candidates))
	}
	seen := map[string]bool{}
	priority, costs := 0, 0
	for i, c := range sd.Candidates {
		if c.CandidateID != uint32(i) {
			return vio("V1", "candidate %d has id %d", i, c.CandidateID)
		}
		if err := c.Semantic.Check(); err != nil {
			return vio("V1", "candidate %d: %v", i, err)
		}
		b, _ := json.Marshal(c.Semantic)
		if seen[string(b)] {
			return vio("V1", "candidate %d repeats a semantic", i)
		}
		seen[string(b)] = true
		if c.Semantic.Kind == "pass" && i != 0 {
			return vio("V1", "pass at %d", i)
		}
		if !s.p.Kinds[c.Semantic.Kind] {
			return vio("V8", "kind %s not declared", c.Semantic.Kind)
		}
		if protocol.PriorityKinds[c.Semantic.Kind] {
			priority++
		}
		if c.Semantic.Kind == "optional_cost" {
			costs++
		}
	}
	// V9
	switch {
	case sd.Context.Kind == "priority" && priority != len(sd.Candidates):
		return vio("V9", "priority context with choice candidates")
	case sd.Context.Kind == "choice" && priority > 0:
		for _, c := range sd.Candidates {
			if k := c.Semantic.Kind; k != "activate_mana_ability" && k != "optional_cost" {
				return vio("V9", "choice context with activate_mana_ability and %s", k)
			}
		}
		if sd.Context.Purpose == nil || *sd.Context.Purpose != "mana_payment" || costs == 0 {
			return vio("V9", "activate_mana_ability in a choice decision without mana_payment and optional_cost candidates")
		}
	case sd.Context.Kind != "priority" && sd.Context.Kind != "choice":
		return vio("V9", "context kind %q", sd.Context.Kind)
	}
	// V5
	other := 1
	if sd.ActingSeat == "p1" {
		other = 0
	}
	if o.Players[other].Hand != nil {
		return vio("V5", "the other seat's hand is not null")
	}
	me := o.Players[1-other]
	if me.Hand == nil || uint32(len(me.Hand)) != me.HandCount {
		return vio("V5", "viewer hand has %d records, hand_count %d", len(me.Hand), me.HandCount)
	}
	if err := checkKnown(o); err != nil {
		return err
	}
	prev := ""
	for i, c := range sd.Candidates {
		if key, ok := hiddenKey(sd.ActingSeat, c.Semantic); ok {
			if key < prev {
				return vio("V5", "hidden-zone candidate %d is out of (card_name, object_id) order", i)
			}
			prev = key
		}
	}
	// V8 optional fields and extensions
	if err := s.checkFlags(o); err != nil {
		return err
	}
	for k := range sd.Extensions {
		if !extKey.MatchString(k) || !s.p.Extensions[k] {
			return vio("V8", "extension %s not enabled", k)
		}
	}
	// V6
	for _, st := range o.Stack {
		if st.FaceDown && st.ControllerSeat != sd.ActingSeat && st.CardName != nil {
			return vio("V6", "face-down stack object %s shows a name", st.ObjectID)
		}
	}
	for _, p := range o.Players {
		for _, rec := range p.Battlefield {
			if rec.FaceDown && rec.ControllerSeat != sd.ActingSeat && (rec.CardName != nil || rec.FullName != nil) {
				return vio("V6", "face-down permanent %s shows a name", rec.ObjectID)
			}
		}
	}
	// V4 and V7
	recs, err := records(o)
	if err != nil {
		return err
	}
	for id, r := range recs {
		if z, ok := s.zoneOf[id]; ok && z != r.Zone {
			return vio("V7", "id %s appears in %s and %s", id, z, r.Zone)
		}
		if s.departed[id] {
			return vio("V7", "id %s returned after leaving", id)
		}
	}
	matches := func(where string, r protocol.ObjectRef) error {
		if rec, ok := recs[r.ObjectID]; !ok || !EqualRef(rec, r) {
			return vio("V4", "%s references %s, not equal to its observation record", where, r.ObjectID)
		}
		return nil
	}
	if sd.Context.Source != nil {
		if err := matches("context.source", *sd.Context.Source); err != nil {
			return err
		}
	}
	if err := observationRefs(o, matches); err != nil {
		return err
	}
	for i, c := range sd.Candidates {
		if err := walkRefs(c.Semantic, func(r protocol.ObjectRef) error {
			return matches(fmt.Sprintf("candidate %d", i), r)
		}); err != nil {
			return err
		}
	}
	for id := range s.live {
		if _, still := recs[id]; !still {
			s.departed[id] = true
		}
	}
	s.live = map[string]bool{}
	for id, r := range recs {
		s.live[id] = true
		s.zoneOf[id] = r.Zone
	}
	// advance counters
	s.nextSeatStep++
	if g.SubstepIndex+1 == g.SubstepCount {
		s.group, s.nextGroup = nil, g.GroupID+1
	} else {
		cp := g
		s.group = &cp
	}
	return nil
}
```

Note for the implementer: V7's "returned after leaving" treats a hidden-zone look id that leaves `known` as departed, which Section 5.3 requires, since looks get fresh ids.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/validate/ -v`
Expected: `--- PASS: TestValidSequencePasses`, `--- PASS: TestViolationsNameTheirRule`, `--- PASS: TestIDFreshnessAcrossTheSeatStream`, `--- PASS: TestJSONDecodedDecisionValidates`, `--- PASS: TestStructuralRulesNameTheirRule`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/validate && git commit -m "gorge adapter: Go validator subset V1 to V9"
```

---

### Task 10: Object identity: incarnations, per-viewer ids, looks

**Files:**
- Create: `internal/identity/tracker.go`
- Create: `internal/testgame/testgame.go` (test helper shared by later tasks)
- Test: `internal/identity/tracker_test.go`

**Interfaces:**
- Consumes: `secrets.Game`, `gamecfg.Game` (Tasks 4, 8).
- Produces:
  - `type identity.Tracker` with `func identity.New(e *rules.Engine, sec *secrets.Game) *Tracker`;
  - `func (*Tracker) Sync(e *rules.Engine) error`, `func (*Tracker) Key(id state.ObjID) string`;
  - `func (*Tracker) VisibleID(viewer state.PlayerID, id state.ObjID) (string, error)`;
  - look handling: `func (*Tracker) OpenLook(viewer state.PlayerID)` (an open look is closed first, so its looks count), `func (*Tracker) LookID(viewer state.PlayerID, id state.ObjID) (string, error)`, `func (*Tracker) CloseLook(viewer state.PlayerID)`;
  - the keys references were taken at, for Task 12's null rules: `func (*Tracker) SourceKey(id state.ObjID) (string, bool)` (a stack ability's source when it was put on the stack), `func (*Tracker) TargetKey(id state.ObjID, i int) (string, bool)` (target i when chosen), `func (*Tracker) AttackKey(attacker state.ObjID) (string, bool)` (a battle or planeswalker when attacked), and `func (*Tracker) Blocking(id state.ObjID) bool` (declared as a blocker this combat and still the same object);
  - `var identity.ErrIDCollision`, `var identity.ErrShadowDiverged`;
  - `testgame.New(t, reg, deck0, deck1 string, secretByte byte, mulligan string) *gamecfg.Game`;
  - `testgame.RunUntil(t, g, bots [2]seat.Seat, pred func(*rules.Engine) bool, maxIntents int) bool`;
  - `testgame.Bots(seed uint64) [2]seat.Seat`.

Design note: gorge keeps one `ObjID` across zone changes. Section 5.3 needs a fresh id on every zone change, including round trips inside one engine step: a London mulligan moves hand to library to hand inside one `Submit`. gorge defers every redraw until each seat has declared (`rules/mulligan.go`: `handleMulligan` only counts, `resolveMulliganRedraws` runs after the pass), so a mulliganing seat's hand moves in the `Submit` of the last declaration, not its own; the session tasks must not expect an immediate redraw either. The tracker therefore replays each new engine event through `events.Apply` on a shadow `state.Game` and counts every zone change exactly. A shadow that disagrees with the engine is a hard error (`halted`).

References that must turn null when their object changes zones (G1-3) need more than a live `ObjID`, because gorge keeps one `ObjID` across zones and `state.Target` carries no incarnation. The tracker records, as it folds events, the key each reference was taken at:
- an activated ability's source: its key at the start of the Sync batch, before the cost events (a cycled card is discarded before its ability is pushed);
- a triggered ability's source: its key when the trigger is put on the stack;
- a target: its key when chosen;
- a battle or planeswalker attack target: its key when declared;
- a declared blocker: its key when declared, until combat ends or it is removed from combat (G1-15, CR 509.1h).

- [ ] **Step 1: Write the failing test**

`internal/testgame/testgame.go`:

```go
// Package testgame drives real gorge games for tests.
package testgame

import (
	"context"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

func New(t testing.TB, reg *cards.Registry, deck0, deck1 string, secretByte byte, mulligan string) *gamecfg.Game {
	t.Helper()
	var decks [2][]*cards.Card
	for i, id := range []string{deck0, deck1} {
		d, ok := catalog.ByID(id)
		if !ok {
			t.Fatalf("no catalog deck %s", id)
		}
		cs, err := catalog.Resolve(reg, d)
		if err != nil {
			t.Fatal(err)
		}
		decks[i] = cs
	}
	s := make([]byte, 32)
	s[0] = secretByte
	g, err := gamecfg.New(reg, secrets.NewGame(s), decks, gamecfg.Rules{Mulligan: mulligan, StartingSeat: state.PlayerID(0)})
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func Bots(seed uint64) [2]seat.Seat { return [2]seat.Seat{seat.NewBot(seed), seat.NewBot(seed + 1)} }

// RunUntil answers decisions with bots until pred holds (true) or the game ends (false).
func RunUntil(t testing.TB, g *gamecfg.Game, bots [2]seat.Seat, pred func(*rules.Engine) bool, maxIntents int) bool {
	t.Helper()
	for n := 0; n < maxIntents; n++ {
		if pred(g.E) {
			return true
		}
		d := g.E.Pending()
		if g.E.G.Over || d == nil {
			return false
		}
		in, _ := bots[d.Player].Decide(context.Background(), view.Project(g.E.G, g.E, d.Player, d), *d)
		if err := g.Submit(in); err != nil {
			t.Fatal(err)
		}
	}
	return false
}
```

`internal/identity/tracker_test.go`:

```go
package identity_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestIDsAreFreshPerZoneAndPerViewer(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 1, "none")
	tr := identity.New(g.E, g.Secret)
	hand := g.E.G.Zone(state.ZHand, 0)
	card := hand[0]
	inHand, _ := tr.VisibleID(0, card)
	other, _ := tr.VisibleID(1, card)
	if inHand == other {
		t.Fatal("the same object has the same id for both viewers")
	}
	moved := testgame.RunUntil(t, g, testgame.Bots(5), func(e *rules.Engine) bool {
		o := e.G.Obj(card)
		return o.Zone != state.ZHand
	}, 5000)
	if !moved {
		t.Fatal("card never left hand in this seed: pick another seed")
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	after, _ := tr.VisibleID(0, card)
	if after == inHand {
		t.Fatalf("id %s survived a zone change", after)
	}
}

// gorge defers every London redraw until each seat has declared
// (rules/mulligan.go: handleMulligan counts, resolveMulliganRedraws runs after
// the pass), so the mulliganing seat's hand moves only once the other seat
// has answered.
func TestMulliganRoundTripGivesFreshIDs(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Spy", "Spy", 2, "london")
	tr := identity.New(g.E, g.Secret)
	d := g.E.Pending()
	if d.Kind != decision.KMulligan {
		t.Fatalf("first decision %s, want mulligan", d.Kind)
	}
	seat := d.Player
	before := map[string]bool{}
	for _, id := range g.E.G.Zone(state.ZHand, seat) {
		oid, _ := tr.VisibleID(seat, id)
		before[oid] = true
	}
	answer := func(d *decision.Decision, kind string) {
		for _, o := range d.Options {
			if o.Kind == kind {
				if err := g.Submit(decision.Intent{Seq: d.Seq, Player: d.Player, Choices: []int{o.Index}}); err != nil {
					t.Fatal(err)
				}
				return
			}
		}
		t.Fatalf("no %s option in %+v", kind, d.Options)
	}
	answer(d, "mulligan")
	for d = g.E.Pending(); d != nil && d.Player != seat; d = g.E.Pending() {
		answer(d, "keep")
	}
	if d == nil || d.Kind != decision.KMulligan {
		t.Fatalf("after the redraw the seat is asked %+v, want its next mulligan ask", d)
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	hand := g.E.G.Zone(state.ZHand, seat)
	if len(hand) != 7 {
		t.Fatalf("redrawn hand has %d cards", len(hand))
	}
	for _, id := range hand {
		oid, _ := tr.VisibleID(seat, id)
		if before[oid] {
			t.Fatalf("id %s is reused in the redrawn hand", oid)
		}
	}
}

func TestLooksAreStableWithinAndFreshAcross(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 3, "none")
	tr := identity.New(g.E, g.Secret)
	top := g.E.G.Zone(state.ZLibrary, 0)[0]
	tr.OpenLook(0)
	a, _ := tr.LookID(0, top)
	b, _ := tr.LookID(0, top)
	tr.CloseLook(0)
	tr.OpenLook(0)
	c, _ := tr.LookID(0, top)
	tr.OpenLook(0) // a second open without a close still starts a fresh look
	d, _ := tr.LookID(0, top)
	tr.CloseLook(0)
	if a != b || a == c || d == c || d == a {
		t.Fatalf("look ids %s %s %s %s", a, b, c, d)
	}
}

func TestShadowNeverDivergesOverWholeGames(t *testing.T) {
	reg := testcorpus.Registry(t)
	for i, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		g := testgame.New(t, reg, deck, deck, byte(10+i), "london")
		tr := identity.New(g.E, g.Secret)
		testgame.RunUntil(t, g, testgame.Bots(uint64(i)), func(e *rules.Engine) bool {
			if err := tr.Sync(e); err != nil {
				t.Fatalf("%s: %v", deck, err)
			}
			return false
		}, 20000)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/identity/`
Expected: FAIL with `undefined: identity.New`.

- [ ] **Step 3: Write minimal implementation**

`internal/identity/tracker.go`:

```go
// Package identity issues Section 5.3 object ids: per viewer, fresh on every
// zone change and on every look into a hidden zone, from the game secret.
package identity

import (
	"errors"
	"fmt"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

var (
	ErrIDCollision    = errors.New("engine_contract_failure:id_collision")
	ErrShadowDiverged = errors.New("engine_contract_failure:identity_shadow_diverged")
)

type lookKey struct {
	viewer state.PlayerID
	key    string
}

// chosen is one stack target as it was when chosen: the object and its key.
type chosen struct {
	obj state.ObjID
	key string
}

type Tracker struct {
	sec     *secrets.Game
	shadow  *state.Game
	applied int
	moves   map[state.ObjID]uint32
	looks   map[lookKey]uint32
	open    [2]map[string]uint32
	seen    [2]map[string]string
	zbuf    []state.Zone
	// References that must turn null when their object changes zones (G1-3):
	// the key each was taken at. gorge keeps one ObjID across zone changes, so
	// a live ObjID alone cannot tell a stale reference from a current one.
	sourceKeys map[state.ObjID]string   // stack ability -> its source's key when put on the stack
	targetKeys map[state.ObjID][]chosen // stack object -> its targets' keys when chosen
	attackKeys map[state.ObjID]string   // attacker -> the attacked battle's or planeswalker's key
	blockKeys  map[state.ObjID]string   // blocker declared this combat -> its key when declared
	before     map[state.ObjID]uint32   // move counts at the start of this Sync batch, for objects that moved in it
}

func New(e *rules.Engine, sec *secrets.Game) *Tracker {
	return &Tracker{sec: sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: map[state.ObjID]uint32{}, looks: map[lookKey]uint32{},
		seen:       [2]map[string]string{{}, {}},
		sourceKeys: map[state.ObjID]string{}, targetKeys: map[state.ObjID][]chosen{},
		attackKeys: map[state.ObjID]string{}, blockKeys: map[state.ObjID]string{}, before: map[state.ObjID]uint32{}}
}

func keyOf(id state.ObjID, moves uint32) string { return fmt.Sprintf("%d:z%d", id, moves) }

// Sync folds the events appended since the last call into the shadow game,
// counting every zone change per object, then checks the shadow against the engine.
func (t *Tracker) Sync(e *rules.Engine) error {
	clear(t.before)
	for ; t.applied < len(e.L.Events); t.applied++ {
		ev := e.L.Events[t.applied]
		n := len(t.shadow.Objs)
		t.zbuf = t.zbuf[:0]
		for i := range t.shadow.Objs {
			t.zbuf = append(t.zbuf, t.shadow.Objs[i].Zone)
		}
		events.Apply(t.shadow, ev)
		for i := range t.zbuf {
			if t.shadow.Objs[i].Zone != t.zbuf[i] {
				id := t.shadow.Objs[i].ID
				if _, ok := t.before[id]; !ok {
					t.before[id] = t.moves[id]
				}
				t.moves[id]++
			}
		}
		t.record(ev, n)
	}
	if len(t.shadow.Objs) != len(e.G.Objs) {
		return fmt.Errorf("%w: %d shadow objects, %d engine objects", ErrShadowDiverged, len(t.shadow.Objs), len(e.G.Objs))
	}
	for i := range e.G.Objs {
		if e.G.Objs[i].Zone != t.shadow.Objs[i].Zone {
			return fmt.Errorf("%w: object %d", ErrShadowDiverged, e.G.Objs[i].ID)
		}
	}
	return nil
}

// record notes, after event ev (which may have minted the objects from index
// n on), the keys that stack references and attack targets were taken at.
//   - An ability's source: for an activated ability, its key at the start of
//     this Sync batch, before the cost events (a cycled card is discarded
//     before its ability is pushed); for a triggered ability, its key when
//     the trigger is put on the stack.
//   - A target: its key when chosen.
//   - A battle or planeswalker attack target: its key when declared.
//   - A declared blocker: its key when declared, until combat ends or it is
//     removed from combat.
func (t *Tracker) record(ev events.Event, n int) {
	g := t.shadow
	for i := n; i < len(g.Objs); i++ {
		o := &g.Objs[i]
		if o.Ability == nil || o.Zone != state.ZStack || o.Source == 0 {
			continue
		}
		mc := t.moves[o.Source]
		if b, ok := t.before[o.Source]; ok && o.StackKind == state.StackKindActivated {
			mc = b
		}
		t.sourceKeys[o.ID] = keyOf(o.Source, mc)
	}
	for _, id := range g.Stack {
		o := g.Obj(id)
		if o == nil {
			continue
		}
		have := t.targetKeys[id]
		if len(have) > len(o.Targets) {
			have = have[:len(o.Targets)]
		}
		for j, tg := range o.Targets {
			obj := tg.Obj
			if tg.IsPlayer {
				obj = 0
			}
			if j < len(have) && have[j].obj == obj {
				continue
			}
			c := chosen{obj: obj}
			if obj != 0 {
				c.key = t.Key(obj)
			}
			if j < len(have) {
				have[j] = c
			} else {
				have = append(have, c)
			}
		}
		t.targetKeys[id] = have
	}
	if ev.Kind == events.DeclareAttackers && ev.Obj != 0 {
		for _, id := range ev.IDs {
			t.attackKeys[id] = t.Key(ev.Obj)
		}
	}
	if ev.Kind == events.DeclareBlockers {
		for _, pr := range ev.Pairs {
			if pr[1] != 0 {
				t.blockKeys[pr[1]] = t.Key(pr[1])
			}
		}
	}
	if ev.Kind == events.EndCombatReset {
		if ev.Obj == 0 {
			clear(t.attackKeys)
			clear(t.blockKeys)
		} else {
			delete(t.blockKeys, ev.Obj)
		}
	}
}

// Key is the internal key of Section 5.3: stable for one stay in one zone.
func (t *Tracker) Key(id state.ObjID) string { return keyOf(id, t.moves[id]) }

// SourceKey is the key the source of stack ability id had when the ability
// was put on the stack. ok is false for an ability the tracker never saw
// pushed (one already on the stack when the tracker was created).
func (t *Tracker) SourceKey(id state.ObjID) (key string, ok bool) {
	key, ok = t.sourceKeys[id]
	return key, ok
}

// TargetKey is the key target i of stack object id had when it was chosen.
func (t *Tracker) TargetKey(id state.ObjID, i int) (key string, ok bool) {
	ks := t.targetKeys[id]
	if i >= len(ks) || ks[i].obj == 0 {
		return "", false
	}
	return ks[i].key, true
}

// AttackKey is the key of the battle or planeswalker attacker was declared
// against, while that combat lasts.
func (t *Tracker) AttackKey(attacker state.ObjID) (key string, ok bool) {
	key, ok = t.attackKeys[attacker]
	return key, ok
}

// Blocking reports whether id was declared as a blocker this combat and has
// neither changed zones nor been removed from combat since: CR 509.1h keeps it
// a blocking creature after its attacker leaves.
func (t *Tracker) Blocking(id state.ObjID) bool {
	key, ok := t.blockKeys[id]
	return ok && key == t.Key(id)
}

func (t *Tracker) mint(viewer state.PlayerID, msg string) (string, error) {
	oid := t.sec.ObjectID(msg)
	if prev, ok := t.seen[viewer][oid]; ok && prev != msg {
		return "", ErrIDCollision
	}
	t.seen[viewer][oid] = msg
	return oid, nil
}

func (t *Tracker) VisibleID(viewer state.PlayerID, id state.ObjID) (string, error) {
	return t.mint(viewer, fmt.Sprintf("p%d:%s", viewer, t.Key(id)))
}

// OpenLook starts one effect's look for viewer; CloseLook ends it. Opening a
// look while one is open closes that one first, so its looks still count and
// its ids are never reused.
func (t *Tracker) OpenLook(viewer state.PlayerID) {
	if t.open[viewer] != nil {
		t.CloseLook(viewer)
	}
	t.open[viewer] = map[string]uint32{}
}

func (t *Tracker) CloseLook(viewer state.PlayerID) {
	for key := range t.open[viewer] {
		t.looks[lookKey{viewer, key}]++
	}
	t.open[viewer] = nil
}

func (t *Tracker) LookID(viewer state.PlayerID, id state.ObjID) (string, error) {
	m := t.open[viewer]
	if m == nil {
		return "", errors.New("engine_contract_failure:look_not_open")
	}
	key := t.Key(id)
	n, ok := m[key]
	if !ok {
		n = t.looks[lookKey{viewer, key}]
		m[key] = n
	}
	return t.mint(viewer, fmt.Sprintf("p%d:%s:look:%d", viewer, key, n))
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/identity/ -v`
Expected: all four tests PASS. If `TestShadowNeverDivergesOverWholeGames` fails, some gorge state change bypasses `events.Apply`. Stop and report the event kind and object instead of weakening the check: the fallback (zone plus `Object.Incarnation` diff) misses hidden round trips and would need the controller's approval.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/identity engines/gorge/internal/testgame && git commit -m "gorge adapter: per-viewer object ids with exact zone incarnations and looks"
```

---

### Task 11: Observation I: players, zones, records, characteristics

**Files:**
- Create: `internal/observe/project.go`, `internal/observe/vocab.go`
- Test: `internal/observe/project_test.go`, `internal/observe/vocab_test.go`, `internal/observe/manavalue_test.go`

**Interfaces:**
- Consumes: `identity.Tracker` (Task 10), protocol types (Task 5), `testgame` (Task 10).
- Produces:
  - `var observe.Flags map[string]bool` (the 13 flags, true only for `pending_triggers` and `keywords`);
  - `type observe.Projector struct{ E *rules.Engine; IDs *identity.Tracker; Mulls [2]uint32 }` and `type observe.State struct{ PriorityHolder *state.PlayerID; Known []protocol.Known }`;
  - `func (*Projector) Observation(viewer state.PlayerID, st State) (protocol.Observation, error)`;
  - `func (*Projector) Ref(viewer state.PlayerID, id state.ObjID) (*protocol.ObjectRef, error)` (nil when absent or hidden);
  - `func (*Projector) Record(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRecord, error)`;
  - `func (*Projector) LookRef(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRef, error)` (a hidden-zone object shown by the open look; an object `Visible` accepts is refused, so no object gets two ids);
  - vocab helpers: `observe.Seat(p) string`, `observe.PhaseStep(g) string`, `observe.Visible(viewer, o) bool`, `observe.MayLook(viewer, o) bool`, `observe.Normalize(s) string`, `observe.Counter(kind) string`, `observe.Keywords([]string) []string`, `observe.Colors(letters string) []string`.

Characteristics (G1-5, G1-14): a transforming double-faced card takes its mana value from its front face on either face (CR 712.8e: Vector Glider is 2), a spell on the stack counts its announced X (CR 202.3e), and an ability is not named after a face-down source the viewer may not look at. Changeling is a known gap: the subtypes show gorge's derived types (Masked Vandal reads `shapeshifter`), recorded in the engine notes.

- [ ] **Step 1: Write the failing tests**

`internal/observe/vocab_test.go`:

```go
package observe_test

import (
	"reflect"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
)

func TestVocabularyNormalization(t *testing.T) {
	for in, want := range map[string]string{"Time Lord": "time_lord", "Urza's": "urzas", "First Strike": "first_strike", "Human": "human"} {
		if got := observe.Normalize(in); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
	for in, want := range map[string]string{"P1P1": "p1p1", "M0M1": "m0m1", "CHARGE": "charge", "Lore": "lore"} {
		if got := observe.Counter(in); got != want {
			t.Errorf("Counter(%q) = %q, want %q", in, got, want)
		}
	}
	if got := observe.Colors("RWG"); !reflect.DeepEqual(got, []string{"white", "red", "green"}) {
		t.Errorf("Colors = %v", got)
	}
	got := observe.Keywords([]string{"Flying", "Flashback:1 R", "Forestwalk", "Protection from red", "CARDNAME can't block.", "Flying"})
	if !reflect.DeepEqual(got, []string{"flying", "flashback", "landwalk", "protection"}) {
		t.Errorf("Keywords = %v", got)
	}
}
```

`internal/observe/project_test.go`:

```go
package observe_test

import (
	"encoding/json"
	"strconv"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestObservationHidesTheOtherHandAndLibraries(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "CawGates", 4, "none")
	p := &observe.Projector{E: g.E, IDs: identity.New(g.E, g.Secret)}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	if obs.Players[1].Hand != nil || len(obs.Players[0].Hand) != 7 || obs.Players[1].HandCount != 7 {
		t.Fatalf("hands: %d own, other %v", len(obs.Players[0].Hand), obs.Players[1].Hand)
	}
	if obs.Players[0].LibraryCount != 53 || obs.PhaseStep == "" || obs.Known == nil || obs.PendingTriggers == nil {
		t.Fatalf("observation %+v", obs)
	}
	b, _ := json.Marshal(obs)
	if strings.Contains(string(b), `"zone":"library"`) {
		t.Fatal("a zone array holds a library object")
	}
	// No card of p1's hand or library may be named anywhere, unless the same
	// name is in a zone p0 sees. (Burn and CawGates share no card.)
	seen := map[string]bool{}
	for _, pl := range obs.Players {
		for _, zone := range [][]protocol.ObjectRecord{pl.Hand, pl.Battlefield, pl.Graveyard, pl.Exile, pl.Command} {
			for _, rec := range zone {
				if rec.CardName != nil {
					seen[*rec.CardName] = true
				}
			}
		}
	}
	hidden := 0
	for _, z := range []state.Zone{state.ZHand, state.ZLibrary} {
		for _, id := range g.E.G.Zone(z, 1) {
			name := g.E.G.Obj(id).Face().Name
			if seen[name] {
				continue
			}
			hidden++
			if strings.Contains(string(b), strconv.Quote(name)) {
				t.Fatalf("hidden card %s is named in p0's observation", name)
			}
		}
	}
	if hidden != 60 {
		t.Fatalf("scanned %d hidden cards, want p1's 60", hidden)
	}
}

func TestCharacteristicsOfBasicLandAndBolt(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 5, "none")
	p := &observe.Projector{E: g.E, IDs: identity.New(g.E, g.Secret)}
	for _, id := range g.E.G.Zone(state.ZHand, 0) {
		rec, err := p.Record(0, id)
		if err != nil {
			t.Fatal(err)
		}
		c := rec.Characteristics
		switch *rec.CardName {
		case "Mountain":
			if c.Supertypes[0] != "basic" || c.Types[0] != "land" || c.Subtypes[0] != "mountain" || c.ManaValue != 0 || c.Power != nil {
				t.Errorf("Mountain %+v", c)
			}
		case "Lightning Bolt":
			if c.Types[0] != "instant" || c.Colors[0] != "red" || c.ManaValue != 1 {
				t.Errorf("Lightning Bolt %+v", c)
			}
		}
		if rec.Permanent != nil || rec.Token || rec.Copy {
			t.Errorf("%s in hand has permanent fields", *rec.CardName)
		}
	}
}
```

`internal/observe/manavalue_test.go` (internal: `manaValue` is unexported):

```go
package observe

import (
	"testing"

	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
)

// Vector Glider, the back face of The Modern Age, has the front face's mana
// value (CR 712.8e); X counts only on the stack (CR 202.3e).
func TestManaValueOfBackFacesAndX(t *testing.T) {
	reg := testcorpus.Registry(t)
	age, ok1 := reg.Lookup("The Modern Age")
	hydra, ok2 := reg.Lookup("Nyxborn Hydra")
	if !ok1 || !ok2 {
		t.Fatal("corpus lacks The Modern Age or Nyxborn Hydra")
	}
	for _, c := range []struct {
		what string
		o    state.Object
		want uint32
	}{
		{"The Modern Age", state.Object{Card: age, Zone: state.ZBattlefield}, 2},
		{"Vector Glider", state.Object{Card: age, FaceIdx: 1, Zone: state.ZBattlefield}, 2},
		{"Nyxborn Hydra in hand", state.Object{Card: hydra, Zone: state.ZHand, X: 3}, 1},
		{"Nyxborn Hydra on the stack with X 3", state.Object{Card: hydra, Zone: state.ZStack, X: 3}, 4},
	} {
		if got := manaValue(&c.o); got != c.want {
			t.Errorf("%s: mana value %d, want %d", c.what, got, c.want)
		}
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/observe/`
Expected: FAIL with `undefined: observe.Normalize`.

- [ ] **Step 3: Write minimal implementation**

`internal/observe/vocab.go`:

```go
package observe

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/state"
)

var Flags = map[string]bool{"poison": false, "player_counters": false, "designations": false, "player_progress": false,
	"day_night": false, "passed_seats": false, "pending_triggers": true, "keywords": true, "full_name": false,
	"exiled_by": false, "stack_text": false, "permanent_details": false, "known_cards": false}

func Seat(p state.PlayerID) string { return fmt.Sprintf("p%d", p) }

var steps = [...]string{"untap", "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
	"declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end_step", "cleanup"}

func PhaseStep(g *state.Game) string {
	if g.Turn == 0 {
		return "pregame"
	}
	return steps[g.Step]
}

// Normalize is Section 6.10: lowercase, apostrophes removed, spaces and hyphens to "_".
func Normalize(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	s = strings.NewReplacer("'", "", "’", "", " ", "_", "-", "_").Replace(s)
	return s
}

var ptCounter = regexp.MustCompile(`^[PM]\d+[PM]\d+$`)

func Counter(kind string) string {
	if u := strings.ToUpper(kind); ptCounter.MatchString(u) {
		return strings.ToLower(u)
	}
	return Normalize(kind)
}

func Colors(letters string) []string {
	out := []string{}
	for _, c := range []struct {
		l    byte
		name string
	}{{'W', "white"}, {'U', "blue"}, {'B', "black"}, {'R', "red"}, {'G', "green"}} {
		if strings.IndexByte(letters, c.l) >= 0 {
			out = append(out, c.name)
		}
	}
	return out
}

// cr702 lists CR 702 keyword names (normalized, no parameters).
var cr702 = map[string]bool{}

func init() {
	for _, k := range strings.Fields(`deathtouch defender double_strike enchant equip first_strike flash flying haste
		hexproof indestructible intimidate landwalk lifelink protection reach shroud trample vigilance ward banding
		rampage cumulative_upkeep flanking phasing buyback shadow cycling echo horsemanship fading kicker flashback
		madness fear morph amplify provoke storm affinity entwine modular sunburst bushido soulshift splice offering
		ninjutsu epic convoke dredge transmute bloodthirst haunt replicate forecast graft recover ripple split_second
		suspend vanishing absorb aura_swap delve fortify frenzy gravestorm poisonous transfigure champion changeling
		evoke hideaway prowl reinforce conspire persist wither retrace devour exalted unearth cascade annihilator
		level_up rebound umbra_armor infect battle_cry living_weapon undying miracle soulbond overload scavenge unleash
		cipher evolve extort fuse bestow tribute dethrone hidden_agenda outlast prowess dash exploit menace renown
		awaken devoid ingest myriad surge skulk emerge escalate melee crew fabricate partner undaunted improvise
		aftermath embalm eternalize afflict ascend assist jump_start mentor afterlife riot spectacle escape companion
		mutate encore boast foretell demonstrate daybound nightbound disturb decayed cleave training compleated
		reconfigure blitz casualty enlist read_ahead ravenous squad prototype living_metal for_mirrodin toxic backup
		bargain craft disguise plot saddle spree gift offspring impending job_select harmonize mobilize station warp`) {
		cr702[k] = true
	}
}

// Keywords maps gorge's derived keyword lines to CR 702 names, deduplicated in order.
func Keywords(lines []string) []string {
	out := []string{}
	seen := map[string]bool{}
	for _, l := range lines {
		k := Normalize(cards.KeywordHead(l))
		switch {
		case strings.HasSuffix(k, "walk") && k != "":
			k = "landwalk"
		case strings.HasSuffix(k, "cycling"):
			k = "cycling"
		case strings.HasPrefix(k, "protection"):
			k = "protection"
		}
		if cr702[k] && !seen[k] {
			seen[k] = true
			out = append(out, k)
		}
	}
	return out
}
```

`internal/observe/project.go`:

```go
// Package observe builds the Section 6 observation for one seat from gorge's
// seat projection (view.Project, visibility "seat") completed from engine state.
package observe

import (
	"fmt"
	"slices"
	"strings"

	"github.com/adams-shaun/gorge/botpolicy"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

type Projector struct {
	E     *rules.Engine
	IDs   *identity.Tracker
	Mulls [2]uint32
}

type State struct {
	PriorityHolder *state.PlayerID
	Known          []protocol.Known
}

var superTypes = map[string]bool{"basic": true, "legendary": true, "ongoing": true, "snow": true, "world": true}

func Visible(viewer state.PlayerID, o *state.Object) bool {
	switch o.Zone {
	case state.ZBattlefield, state.ZGraveyard, state.ZExile, state.ZStack, state.ZCommand:
		return true
	case state.ZHand:
		return o.Owner == viewer
	}
	return false
}

func MayLook(viewer state.PlayerID, o *state.Object) bool {
	looker := o.Controller
	if o.HasMayLook {
		looker = o.MayLookPlayer
	}
	return viewer == looker
}

func controller(o *state.Object) state.PlayerID {
	if o.Zone == state.ZBattlefield || o.Zone == state.ZStack {
		return o.Controller
	}
	return o.Owner
}

func (p *Projector) name(viewer state.PlayerID, o *state.Object) *string {
	if o.FaceDown && !MayLook(viewer, o) {
		return nil
	}
	var n string
	if o.Ability != nil {
		// An ability is named after its source, unless that source is face
		// down and the viewer may not look at it.
		if src := p.E.G.Obj(o.Source); src != nil && src.Face() != nil && (!src.FaceDown || MayLook(viewer, src)) {
			n = src.Face().Name
		}
	} else if n = p.E.Derived(o.ID).Name; n == "" && o.Face() != nil {
		n = o.Face().Name
	}
	if n == "" {
		return nil
	}
	return &n
}

func (p *Projector) Ref(viewer state.PlayerID, id state.ObjID) (*protocol.ObjectRef, error) {
	o := p.E.G.Obj(id)
	if o == nil || !Visible(viewer, o) {
		return nil, nil
	}
	oid, err := p.IDs.VisibleID(viewer, id)
	if err != nil {
		return nil, err
	}
	return &protocol.ObjectRef{ObjectID: oid, CardName: p.name(viewer, o), OwnerSeat: Seat(o.Owner),
		ControllerSeat: Seat(controller(o)), Zone: o.Zone.String()}, nil
}

// LookRef references a hidden-zone object the open look shows to viewer. An
// object the viewer can see already has its visible id; a look id would give
// it two.
func (p *Projector) LookRef(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRef, error) {
	o := p.E.G.Obj(id)
	if o == nil || Visible(viewer, o) {
		return protocol.ObjectRef{}, fmt.Errorf("engine_contract_failure:look_ref_not_hidden %d", id)
	}
	oid, err := p.IDs.LookID(viewer, id)
	if err != nil {
		return protocol.ObjectRef{}, err
	}
	name := o.Face().Name
	return protocol.ObjectRef{ObjectID: oid, CardName: &name, OwnerSeat: Seat(o.Owner),
		ControllerSeat: Seat(o.Owner), Zone: o.Zone.String()}, nil
}

func (p *Projector) Characteristics(viewer state.PlayerID, o *state.Object) *protocol.Characteristics {
	if o.FaceDown && !MayLook(viewer, o) {
		if o.Zone != state.ZBattlefield && o.Zone != state.ZStack {
			return nil
		}
		two := int32(2)
		return &protocol.Characteristics{Supertypes: []string{}, Types: []string{"creature"}, Subtypes: []string{},
			Colors: []string{}, Power: &two, Toughness: &two, Keywords: []string{}}
	}
	d := p.E.Derived(o.ID)
	c := &protocol.Characteristics{Supertypes: []string{}, Types: []string{}, Subtypes: []string{},
		Colors: Colors(d.Colors), Keywords: Keywords(d.Keywords)}
	for _, t := range d.Types {
		n := Normalize(t)
		switch {
		case superTypes[n]:
			c.Supertypes = append(c.Supertypes, n)
		case slices.Contains(protocol.Vocab["card_type"], n):
			c.Types = append(c.Types, n)
		default:
			c.Subtypes = append(c.Subtypes, n)
		}
	}
	c.ManaValue = manaValue(o)
	if slices.Contains(c.Types, "creature") {
		pw, tg := d.Power, d.Toughness
		c.Power, c.Toughness = &pw, &tg
	}
	return c
}

// manaValue is CR 202.3's mana value: a transforming double-faced card uses
// its front face's cost on either face (CR 712.8e: Vector Glider is 2), and X
// counts as its announced value only while the spell is on the stack (CR
// 202.3e).
func manaValue(o *state.Object) uint32 {
	f := o.Face()
	if f == nil {
		return 0
	}
	cost := f.ManaCost
	if o.Card != nil && o.Card.AlternateMode == "DoubleFaced" && len(o.Card.Faces) > 0 {
		cost = o.Card.Faces[0].ManaCost
	}
	mv := max(0, botpolicy.CmcOf(cost))
	if o.Zone == state.ZStack && o.Ability == nil {
		mv += int32(strings.Count(cost, "X")) * max(0, o.X)
	}
	return uint32(mv)
}

// builder carries per-observation caches (the inverted block map of Task 12).
type builder struct {
	p        *Projector
	viewer   state.PlayerID
	blocking map[state.ObjID][]state.ObjID
}

func (p *Projector) Record(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRecord, error) {
	return (&builder{p: p, viewer: viewer}).record(id)
}

func (b *builder) record(id state.ObjID) (protocol.ObjectRecord, error) {
	o := b.p.E.G.Obj(id)
	ref, err := b.p.Ref(b.viewer, id)
	if err != nil {
		return protocol.ObjectRecord{}, err
	}
	if ref == nil {
		return protocol.ObjectRecord{}, fmt.Errorf("object %d is not visible to %s", id, Seat(b.viewer))
	}
	rec := protocol.ObjectRecord{ObjectRef: *ref, FaceDown: o.FaceDown, Token: o.IsToken, Copy: o.IsCopy,
		Characteristics: b.p.Characteristics(b.viewer, o)}
	if o.Zone == state.ZBattlefield {
		rec.Permanent, err = b.permanent(o)
	}
	return rec, err
}

func (b *builder) records(cvs []view.CardView) ([]protocol.ObjectRecord, error) {
	out := make([]protocol.ObjectRecord, 0, len(cvs))
	for _, cv := range cvs {
		r, err := b.record(cv.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

func u32(v int32) uint32 { return uint32(max(0, v)) }

func (p *Projector) Observation(viewer state.PlayerID, st State) (protocol.Observation, error) {
	g := p.E.G
	v := view.Project(g, p.E, viewer, nil)
	b := &builder{p: p, viewer: viewer}
	obs := protocol.Observation{Viewer: Seat(viewer), Turn: uint32(max(0, g.Turn)), PhaseStep: PhaseStep(g),
		Stack: []protocol.StackEntry{}, PendingTriggers: []protocol.PendingTrigger{}, Known: st.Known}
	if obs.Known == nil {
		obs.Known = []protocol.Known{}
	}
	if v.Active != view.NoSeat {
		s := Seat(v.Active)
		obs.ActiveSeat = &s
	}
	if st.PriorityHolder != nil {
		s := Seat(*st.PriorityHolder)
		obs.PrioritySeat = &s
	}
	for i, pv := range v.Players {
		pl := g.Players[pv.ID]
		po := protocol.PlayerObs{Seat: Seat(pv.ID), Life: pv.Life,
			ManaPool: protocol.ManaPool{W: u32(pl.Pool[state.MW]), U: u32(pl.Pool[state.MU]), B: u32(pl.Pool[state.MB]),
				R: u32(pl.Pool[state.MR]), G: u32(pl.Pool[state.MG]), C: u32(pl.Pool[state.MC])},
			LandsPlayedThisTurn: u32(pl.LandsPlayed), MulligansTaken: p.Mulls[pv.ID],
			HandCount: uint32(pv.HandSize), LibraryCount: uint32(pv.LibrarySize)}
		var err error
		if pv.ID == viewer {
			if po.Hand, err = b.records(pv.Hand); err != nil {
				return obs, err
			}
		}
		for _, z := range []struct {
			dst *[]protocol.ObjectRecord
			src []view.CardView
		}{{&po.Battlefield, pv.Battlefield}, {&po.Graveyard, pv.Graveyard}, {&po.Exile, pv.Exile}, {&po.Command, pv.Command}} {
			if *z.dst, err = b.records(z.src); err != nil {
				return obs, err
			}
		}
		obs.Players[i] = po
	}
	return obs, b.stackAndPending(&obs, v)
}
```

Also in this task, add to `project.go` the two stubs that Task 12 replaces: `func (b *builder) permanent(o *state.Object) (*protocol.Permanent, error)` returning tapped, summoning sick, damage and counters only, and `func (b *builder) stackAndPending(obs *protocol.Observation, v view.View) error { return nil }`. Task 12 deletes them from `project.go` and owns both bodies.

```go
func (b *builder) permanent(o *state.Object) (*protocol.Permanent, error) {
	pm := &protocol.Permanent{Tapped: o.Tapped, SummoningSick: o.SummonSick, Damage: u32(o.Damage),
		Counters: map[string]uint32{}, BlockedAttackers: []protocol.ObjectRef{}}
	for _, c := range o.Counters {
		if c.N > 0 {
			pm.Counters[Counter(c.Kind)] += uint32(c.N)
		}
	}
	return pm, nil
}

func (b *builder) stackAndPending(obs *protocol.Observation, v view.View) error { return nil }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/observe/ -v`
Expected: `--- PASS: TestVocabularyNormalization`, `--- PASS: TestObservationHidesTheOtherHandAndLibraries`, `--- PASS: TestCharacteristicsOfBasicLandAndBolt`, `--- PASS: TestManaValueOfBackFacesAndX`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/observe && git commit -m "gorge adapter: v2 observation players, zones, records and characteristics"
```

---

### Task 12: Observation II: combat fields, stack, pending triggers, known

**Files:**
- Create: `internal/observe/combat_stack.go` (replaces the two stubs of Task 11), `internal/observe/known.go`
- Test: `internal/observe/combat_stack_test.go`

**Interfaces:**
- Consumes: Task 11's `builder`, `Projector`, `Ref`, `Characteristics`; Task 10's `SourceKey`, `TargetKey`, `AttackKey`, `Blocking`.
- Produces:
  - full `(*builder).permanent`: attached_to, attacking, attack_target (null once the attacked permanent changed zones), blocking (declared this combat, or still blocking: it stays true after the attacker leaves, CR 509.1h) and blocked_attackers inverted from `BlockedBy`, zero tombstones skipped;
  - `(*builder).stackAndPending`: stack entries and pending triggers, with triggers whose source is hidden from the viewer omitted (Section 6.6). A stack source or target that changed zones since it was recorded is null (Sections 5.1 and 6.5); `stack_kind` comes from `Object.StackKind`; a stack object without a reference or with an unmapped kind is an `engine_contract_failure` error, never a truncated stack (Section 9.5);
  - `func observe.SortKnown(ks []protocol.Known)`;
  - `func observe.KnownEntry(ref protocol.ObjectRef, how string, fromTop *uint32) protocol.Known`.

- [ ] **Step 1: Write the failing test**

`internal/observe/combat_stack_test.go`:

```go
package observe_test

import (
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestBlockingIsInvertedFromBlockedBy(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Wildfire", "Wildfire", 6, "none")
	found := testgame.RunUntil(t, g, testgame.Bots(21), func(e *rules.Engine) bool {
		for i := range e.G.Objs {
			// a live blocker: gorge leaves zero tombstones for removed ones
			if e.G.Objs[i].IsAttacking && slices.ContainsFunc(e.G.Objs[i].BlockedBy, func(b state.ObjID) bool { return b != 0 }) {
				return true
			}
		}
		return false
	}, 30000)
	if !found {
		t.Fatal("no blocked attacker in this seed")
	}
	tr := identity.New(g.E, g.Secret)
	p := &observe.Projector{E: g.E, IDs: tr}
	obs, err := p.Observation(g.E.Pending().Player, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	var attackers, blockers int
	for _, pl := range obs.Players {
		for _, rec := range pl.Battlefield {
			pm := rec.Permanent
			if pm.Attacking {
				attackers++
				if pm.AttackTarget == nil {
					t.Errorf("%s attacks nothing", rec.ObjectID)
				}
			}
			if pm.Blocking {
				blockers++
				if len(pm.BlockedAttackers) == 0 {
					t.Errorf("%s blocks no attacker", rec.ObjectID)
				}
			}
		}
	}
	if attackers == 0 || blockers == 0 {
		t.Fatalf("attackers %d blockers %d", attackers, blockers)
	}
}

func TestStackEntryForASpell(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Burn", "Burn", 7, "none")
	if !testgame.RunUntil(t, g, testgame.Bots(3), func(e *rules.Engine) bool { return len(e.G.Stack) > 0 }, 20000) {
		t.Fatal("nothing was cast")
	}
	p := &observe.Projector{E: g.E, IDs: identity.New(g.E, g.Secret)}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	top := obs.Stack[len(obs.Stack)-1]
	if top.Zone != "stack" || top.StackKind == "" || top.Targets == nil {
		t.Fatalf("stack entry %+v", top)
	}
	if top.StackKind == "spell" && top.Characteristics == nil {
		t.Fatal("spell without characteristics")
	}
	if top.StackKind != "spell" && top.Characteristics != nil {
		t.Fatal("ability with characteristics")
	}
	_ = state.ZStack
}

func TestSortKnownOrder(t *testing.T) {
	zero, one := uint32(0), uint32(1)
	id := "o-2"
	ks := []protocol.Known{
		{OwnerSeat: "p1", Zone: "hand", CardName: "Counterspell", How: "revealed"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Island", PositionFromTop: &one, How: "looked_at"},
		{OwnerSeat: "p0", Zone: "library", CardName: "Island", PositionFromTop: &zero, How: "looked_at", ObjectID: &id},
		{OwnerSeat: "p0", Zone: "library", CardName: "Brainstorm", PositionFromTop: &one, How: "looked_at"},
	}
	observe.SortKnown(ks)
	got := []string{ks[0].CardName, ks[1].CardName, ks[2].CardName, ks[3].OwnerSeat}
	want := []string{"Brainstorm", "Island", "Island", "p1"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("order %v", got)
		}
	}
	if *ks[1].PositionFromTop != 0 {
		t.Fatal("position_from_top must break the tie")
	}
}

// tracked plays bot games from their start, syncing a tracker after every
// intent as the session does, until pred holds. It tries each deck with
// several seeds and fails, never skips, when no game gets there.
func tracked(t *testing.T, decks []string, pred func(*rules.Engine, *identity.Tracker) bool) (*gamecfg.Game, *identity.Tracker) {
	reg := testcorpus.Registry(t)
	for _, deck := range decks {
		for s := byte(1); s <= 20; s++ {
			g := testgame.New(t, reg, deck, deck, s, "none")
			tr := identity.New(g.E, g.Secret)
			if testgame.RunUntil(t, g, testgame.Bots(uint64(s)), func(e *rules.Engine) bool {
				if err := tr.Sync(e); err != nil {
					t.Fatal(err)
				}
				return pred(e, tr)
			}, 30000) {
				return g, tr
			}
		}
	}
	t.Fatalf("no %v game reached the wanted state", decks)
	return nil, nil
}

// entry returns the viewer's stack entry for stack object id.
func entry(t *testing.T, g *gamecfg.Game, tr *identity.Tracker, id state.ObjID) protocol.StackEntry {
	p := &observe.Projector{E: g.E, IDs: tr}
	obs, err := p.Observation(0, observe.State{})
	if err != nil {
		t.Fatal(err)
	}
	for i, sid := range g.E.G.Stack {
		if sid == id {
			return obs.Stack[i]
		}
	}
	t.Fatalf("stack object %d not in the observation", id)
	return protocol.StackEntry{}
}

// A cycled card is discarded before its ability is put on the stack, so the
// ability's source has left: Section 6.5 makes it null.
func TestCycledSourceIsNull(t *testing.T) {
	var ability state.ObjID
	g, tr := tracked(t, []string{"Spy", "CawGates", "Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			if src := e.G.Obj(o.Source); o.Ability != nil && o.StackKind == state.StackKindActivated && src != nil && src.Zone == state.ZGraveyard {
				ability = id
				return true
			}
		}
		return false
	})
	if se := entry(t, g, tr, ability); se.Source != nil || se.StackKind != "activated_ability" {
		t.Fatalf("ability %+v: source %+v, want null", se.ObjectRef, se.Source)
	}
}

// A target that changed zones after it was chosen (a land sacrificed in
// response to Cleansing Wildfire) is a null target, even though the card is
// visible in its new zone.
func TestTargetThatLeftIsNull(t *testing.T) {
	var spell state.ObjID
	var slot int
	g, tr := tracked(t, []string{"Wildfire", "Rally", "Burn"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			for i, tg := range e.G.Obj(id).Targets {
				if key, ok := tr.TargetKey(id, i); ok && !tg.IsPlayer && e.G.Obj(tg.Obj) != nil && key != tr.Key(tg.Obj) {
					spell, slot = id, i
					return true
				}
			}
		}
		return false
	})
	if se := entry(t, g, tr, spell); se.Targets[slot] != nil {
		t.Fatalf("target %d of %+v is %+v, want null", slot, se.ObjectRef, se.Targets[slot].Object)
	}
}

// Writhing Chrysalis's cast trigger resolves above the spell it came from:
// that source is still on the stack and stays referenced.
func TestCastTriggerKeepsItsStackSource(t *testing.T) {
	var trigger state.ObjID
	g, tr := tracked(t, []string{"Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for _, id := range e.G.Stack {
			o := e.G.Obj(id)
			if src := e.G.Obj(o.Source); o.Ability != nil && src != nil && src.Zone == state.ZStack && src.Face().Name == "Writhing Chrysalis" {
				trigger = id
				return true
			}
		}
		return false
	})
	se := entry(t, g, tr, trigger)
	if se.StackKind != "triggered_ability" || se.Source == nil || se.Source.Zone != "stack" || *se.Source.CardName != "Writhing Chrysalis" {
		t.Fatalf("cast trigger %+v with source %+v", se.ObjectRef, se.Source)
	}
}

// CR 509.1h: a blocker whose attacker left combat is still a blocking
// creature, with no blocked attackers left to list.
func TestBlockerStaysBlockingAfterItsAttackerLeaves(t *testing.T) {
	var blocker state.ObjID
	g, tr := tracked(t, []string{"CawGates", "Rally", "Wildfire"}, func(e *rules.Engine, tr *identity.Tracker) bool {
		for i := range e.G.Objs {
			b := &e.G.Objs[i]
			if b.Zone != state.ZBattlefield || !tr.Blocking(b.ID) {
				continue
			}
			alone := true
			for j := range e.G.Objs {
				if a := &e.G.Objs[j]; a.IsAttacking && slices.Contains(a.BlockedBy, b.ID) {
					alone = false
				}
			}
			if alone {
				blocker = b.ID
				return true
			}
		}
		return false
	})
	rec, err := (&observe.Projector{E: g.E, IDs: tr}).Record(0, blocker)
	if err != nil {
		t.Fatal(err)
	}
	if !rec.Permanent.Blocking || len(rec.Permanent.BlockedAttackers) != 0 {
		t.Fatalf("blocker %s: blocking %v, attackers %v", rec.ObjectID, rec.Permanent.Blocking, rec.Permanent.BlockedAttackers)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/observe/ -run 'Blocking|StackEntry|SortKnown|Cycled|TargetThatLeft|CastTrigger|BlockerStays'`
Expected: FAIL to compile: `undefined: observe.SortKnown`.

- [ ] **Step 3: Write minimal implementation**

Delete the two stubs from `project.go` and create `internal/observe/combat_stack.go`:

```go
package observe

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// blockMap inverts the attackers' BlockedBy lists: blocker -> attackers it
// blocks. gorge keeps zero tombstones for removed blockers; they are skipped.
func (b *builder) blockMap() map[state.ObjID][]state.ObjID {
	if b.blocking == nil {
		b.blocking = map[state.ObjID][]state.ObjID{}
		g := b.p.E.G
		for i := range g.Objs {
			a := &g.Objs[i]
			if a.Zone == state.ZBattlefield && a.IsAttacking {
				for _, blk := range a.BlockedBy {
					if blk != 0 {
						b.blocking[blk] = append(b.blocking[blk], a.ID)
					}
				}
			}
		}
	}
	return b.blocking
}

// sameRef references id, or nil once id has changed zones since key was
// taken (Sections 5.1, 6.4 and 6.5: a reference to an object that left is
// null). known is false for a reference the tracker never recorded, which
// follows the current object.
func (b *builder) sameRef(id state.ObjID, key string, known bool) (*protocol.ObjectRef, error) {
	if known && key != b.p.IDs.Key(id) {
		return nil, nil
	}
	return b.p.Ref(b.viewer, id)
}

func (b *builder) permanent(o *state.Object) (*protocol.Permanent, error) {
	pm := &protocol.Permanent{Tapped: o.Tapped, SummoningSick: o.SummonSick, Damage: u32(o.Damage),
		Counters: map[string]uint32{}, BlockedAttackers: []protocol.ObjectRef{}}
	for _, c := range o.Counters {
		if c.N > 0 {
			pm.Counters[Counter(c.Kind)] += uint32(c.N)
		}
	}
	if o.AttachedTo != 0 {
		r, err := b.p.Ref(b.viewer, o.AttachedTo)
		if err != nil {
			return nil, err
		}
		if r != nil {
			t := protocol.ObjectTarget(*r)
			pm.AttachedTo = &t
		}
	}
	if o.IsAttacking {
		pm.Attacking = true
		if o.AttackingBattle != 0 {
			key, known := b.p.IDs.AttackKey(o.ID)
			r, err := b.sameRef(o.AttackingBattle, key, known)
			if err != nil {
				return nil, err
			}
			if r != nil {
				t := protocol.ObjectTarget(*r)
				pm.AttackTarget = &t
			}
		} else {
			t := protocol.PlayerTarget(Seat(o.Attacking))
			pm.AttackTarget = &t
		}
	}
	attackers := b.blockMap()[o.ID]
	pm.Blocking = len(attackers) > 0 || b.p.IDs.Blocking(o.ID)
	for _, a := range attackers {
		r, err := b.p.Ref(b.viewer, a)
		if err != nil {
			return nil, err
		}
		if r != nil {
			pm.BlockedAttackers = append(pm.BlockedAttackers, *r)
		}
	}
	return pm, nil
}

var stackKinds = map[state.StackObjKind]string{state.StackKindSpell: "spell",
	state.StackKindActivated: "activated_ability", state.StackKindTriggered: "triggered_ability"}

func (b *builder) stackAndPending(obs *protocol.Observation, v view.View) error {
	g := b.p.E.G
	for _, sv := range v.Stack {
		o := g.Obj(sv.ID)
		ref, err := b.p.Ref(b.viewer, sv.ID)
		if err != nil {
			return err
		}
		kind, ok := stackKinds[o.StackKind]
		if ref == nil || !ok || (o.Ability != nil) == (o.StackKind == state.StackKindSpell) {
			// Never a partial stack (Section 9.5): the game halts instead.
			return fmt.Errorf("engine_contract_failure:stack_entry %d", sv.ID)
		}
		se := protocol.StackEntry{ObjectRef: *ref, StackKind: kind, FaceDown: o.FaceDown, Copy: o.IsCopy,
			Targets: []*protocol.TargetRef{}}
		if o.Ability != nil {
			if src := g.Obj(o.Source); src != nil && src.Incarnation == o.SourceIncarnation {
				key, known := b.p.IDs.SourceKey(o.ID)
				if se.Source, err = b.sameRef(o.Source, key, known); err != nil {
					return err
				}
			}
		} else {
			se.Characteristics = b.p.Characteristics(b.viewer, o)
		}
		for i, t := range o.Targets {
			if t.IsPlayer {
				pt := protocol.PlayerTarget(Seat(t.Player))
				se.Targets = append(se.Targets, &pt)
				continue
			}
			key, known := b.p.IDs.TargetKey(o.ID, i)
			r, err := b.sameRef(t.Obj, key, known)
			if err != nil {
				return err
			}
			if r == nil {
				se.Targets = append(se.Targets, nil)
			} else {
				ot := protocol.ObjectTarget(*r)
				se.Targets = append(se.Targets, &ot)
			}
		}
		se.Modes, se.XValue = modesAndX(o)
		obs.Stack = append(obs.Stack, se)
	}
	for _, pt := range b.p.E.PendingTriggers() {
		src := g.Obj(pt.Source)
		if src != nil && !Visible(b.viewer, src) {
			continue // Section 6.6: a trigger from a hidden, unrevealed source is omitted
		}
		entry := protocol.PendingTrigger{ControllerSeat: Seat(pt.Controller), Optional: pt.Optional}
		if src != nil {
			var err error
			if entry.Source, err = b.p.Ref(b.viewer, pt.Source); err != nil {
				return err
			}
			entry.SourceName = b.p.name(b.viewer, src)
		}
		obs.PendingTriggers = append(obs.PendingTriggers, entry)
	}
	return nil
}

func modesAndX(o *state.Object) ([]uint32, *uint32) {
	f := o.Face()
	sa := o.Ability
	if sa == nil && f != nil {
		sa = f.SpellAbility()
	}
	var modes []uint32
	if sa != nil && sa.Params["Choices"] != "" {
		modes = []uint32{}
		choices := strings.Split(sa.Params["Choices"], ",")
		for _, m := range o.ChosenModes {
			for i, c := range choices {
				if strings.TrimSpace(c) == m {
					modes = append(modes, uint32(i))
				}
			}
		}
	}
	var x *uint32
	if f != nil && o.Ability == nil && strings.Contains(f.ManaCost, "X") {
		v := u32(o.X)
		x = &v
	}
	return modes, x
}
```

`internal/observe/known.go`:

```go
package observe

import (
	"sort"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func KnownEntry(ref protocol.ObjectRef, how string, fromTop *uint32) protocol.Known {
	id := ref.ObjectID
	return protocol.Known{OwnerSeat: ref.OwnerSeat, Zone: ref.Zone, CardName: *ref.CardName, ObjectID: &id,
		PositionFromTop: fromTop, How: how}
}

func lessU(a, b *uint32) (bool, bool) {
	switch {
	case a == nil && b == nil:
		return false, false
	case a == nil:
		return true, true
	case b == nil:
		return false, true
	case *a != *b:
		return *a < *b, true
	}
	return false, false
}

func lessS(a, b *string) (bool, bool) {
	switch {
	case a == nil && b == nil:
		return false, false
	case a == nil:
		return true, true
	case b == nil:
		return false, true
	case *a != *b:
		return *a < *b, true
	}
	return false, false
}

// SortKnown is Section 6.7's order: owner_seat, zone, card_name,
// position_from_top, position_from_bottom, how, object_id (nulls first).
func SortKnown(ks []protocol.Known) {
	sort.SliceStable(ks, func(i, j int) bool {
		a, b := ks[i], ks[j]
		if a.OwnerSeat != b.OwnerSeat {
			return a.OwnerSeat < b.OwnerSeat
		}
		if a.Zone != b.Zone {
			return a.Zone < b.Zone
		}
		if a.CardName != b.CardName {
			return a.CardName < b.CardName
		}
		if l, ok := lessU(a.PositionFromTop, b.PositionFromTop); ok {
			return l
		}
		if l, ok := lessU(a.PositionFromBottom, b.PositionFromBottom); ok {
			return l
		}
		if a.How != b.How {
			return a.How < b.How
		}
		l, _ := lessS(a.ObjectID, b.ObjectID)
		return l
	})
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/observe/ -v`
Expected: all eleven observe tests PASS, including `TestCycledSourceIsNull`, `TestTargetThatLeftIsNull`, `TestCastTriggerKeepsItsStackSource` and `TestBlockerStaysBlockingAfterItsAttackerLeaves`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/observe && git commit -m "gorge adapter: observation combat fields, stack, pending triggers, known order"
```

---

### Task 13: Mapping framework: transactions, sources, oracle, candidate rules

**Files:**
- Create: `internal/mapping/tx.go`, `internal/mapping/route.go`, `internal/mapping/source.go`, `internal/mapping/oracle.go`, `internal/mapping/finalize.go`, `internal/mapping/pick.go`, `internal/mapping/single.go`
- Test: `internal/mapping/framework_test.go`

**Interfaces:**
- Consumes: `gamecfg.Game`, `observe.Projector`, `identity.Tracker`, protocol types.
- Produces (every later mapping task builds on these names):
  - `type mapping.Env struct{ G *gamecfg.Game; Obs *observe.Projector; IDs *identity.Tracker; Action *ActionContext; Domain map[string]bool; Slots map[string]uint32; Looking [2]bool }` with `func (*Env) OpenLook(seat state.PlayerID)` and `func (*Env) CloseLooks()`;
  - `type mapping.ActionContext struct{ Seat state.PlayerID; Obj state.ObjID; Since state.ObjID }` (`Since`: the engine's next object id when the action began, set by the session);
  - `type mapping.NativeOp struct{ Op string; Option int; Followup []int; List string; Position int; Unit state.ObjID; Covers []int }` (JSON tags `op`, `option`, `followup`, `list`, `position`, `unit`, `covers`);
  - `type mapping.Cand struct{ Sem protocol.Semantic; Op NativeOp; Hidden bool; SortName, SortID string }`;
  - `type mapping.Pose struct{ Seat state.PlayerID; Context protocol.Context; GroupStart bool; SubstepIndex, SubstepCount uint32; Candidates []Cand; Known []protocol.Known; Look bool; Native *decision.Decision; Followups map[string]*decision.Decision }`;
  - `type mapping.Transaction interface{ Pose() (*Pose, error); Answer(i int) (commit []decision.Intent, done bool, err error) }`;
  - `func mapping.Begin(env *Env, d *decision.Decision) (Transaction, error)`, `func mapping.Register(route string, f Builder)`, `type mapping.Builder func(*Env, *decision.Decision) (Transaction, error)`, `func mapping.Route(d *decision.Decision) string`;
  - `func mapping.ResolveSource(env *Env, d *decision.Decision) (*protocol.ObjectRef, error)` and `func mapping.MustSource(env *Env, d *decision.Decision) (protocol.ObjectRef, error)`;
  - `func mapping.Accepts(env *Env, ins ...decision.Intent) bool`, `func mapping.Intent(d *decision.Decision, choices ...int) decision.Intent`;
  - `func mapping.Finalize(p *Pose) error` (pass first, hidden-zone candidate order, distinct semantics, 4096 cap);
  - `type mapping.PickSpec` and `func mapping.NewPick(env *Env, s PickSpec) Transaction` (the generic one-pick-per-decision subset transaction used by Tasks 17, 18 and 19a), plus the unexported helper `allOptions(d)`;
  - `func mapping.SingleChoice(env *Env, d *decision.Decision, ctx protocol.Context, sem func(decision.Option) (protocol.Semantic, bool, error)) (Transaction, error)`, with the unexported `singleTx` (an `after` hook field) and `choice(src, purpose)`, used by Tasks 20 and 21;
  - errors `mapping.ErrDeadEnd`, `mapping.ErrUnmapped`, `mapping.ErrCandidateLimit`, `mapping.ErrDuplicate`, `mapping.ErrUnresolvableSource`;
  - engine-internal answers, a registry like the routes: `type mapping.InternalFunc func(*Env, *decision.Decision) (decision.Intent, error)`, `func mapping.RegisterInternal(route string, f InternalFunc)` (Task 16 registers `choose/division`, Task 21 `choose/pay_pip`) and `func mapping.Internal(env *Env, d *decision.Decision) (decision.Intent, bool, error)`, which the session calls before posing;
  - hook `var mapping.ExpandActivate func(env *Env, d *decision.Decision, o decision.Option, src protocol.ObjectRef) ([]Cand, map[string]*decision.Decision, error)` with a simple default (one candidate, no folding) that Task 15 replaces.

Routing is a registry, so wave-5 tasks add files with `init()` registrations and never edit a shared switch.

`Route(d)` returns:
- `priority`, `attackers`, `blockers`, `target`, `trigger_order`;
- `modes/unless` (any option with `Mode` `unless_pay` or `unless_decline`), `modes/discard`, `modes/mode`;
- `mulligan/keep`, `mulligan/bottom`;
- `trigger_optional/madness` (ResumeKind `madness`), `trigger_optional/optional`;
- `replacement/madness`, `replacement/order`;
- `arrange/<first option kind>`;
- for `KChoose`, `choose/<class>` with class:
  - `cost`: `sacrifice`, `tapcost`, `returncost`, `exile_cost`, `exile`, or `discard` with a nonzero `Source`;
  - `cleanup_discard`: `discard` with `Source` 0;
  - `search`, `hand_move`, `dig`, `untap`, `keep`, `x`, `number`, `color`, `type`, `name`, `division`;
  - `yesno`: `yes`/`no`;
  - `explore`: `graveyard`/`top`;
  - `mana_window`: `activate` and `done`;
  - `trigger_cost`: `trigger_cost_pay` or `trigger_cost_decline`;
  - `pay_pip`: `pay_` prefix;
  - `mana`;
- anything else: `unmapped:<kind>/<sorted option kinds>`.

- [ ] **Step 1: Write the failing test**

`internal/mapping/framework_test.go`:

```go
package mapping_test

import (
	"errors"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func str(s string) *string { return &s }

func ref(id, name string) protocol.ObjectRef {
	return protocol.ObjectRef{ObjectID: id, CardName: str(name), OwnerSeat: "p0", ControllerSeat: "p0", Zone: "library"}
}

func TestFinalizePutsPassFirstAndOrdersHiddenCandidates(t *testing.T) {
	p := &mapping.Pose{Context: protocol.Context{Kind: "choice"}, Candidates: []mapping.Cand{
		{Sem: protocol.SelectObject(nil, "search", protocol.ObjectTarget(ref("o-b", "Swamp")), 0, 0, 1), Hidden: true, SortName: "Swamp", SortID: "o-b"},
		{Sem: protocol.FinishSelection(nil, "search", 0)},
		{Sem: protocol.SelectObject(nil, "search", protocol.ObjectTarget(ref("o-a", "Forest")), 0, 0, 1), Hidden: true, SortName: "Forest", SortID: "o-a"},
	}}
	if err := mapping.Finalize(p); err != nil {
		t.Fatal(err)
	}
	if p.Candidates[0].SortName != "Forest" || p.Candidates[2].SortName != "Swamp" || p.Candidates[1].Sem.Kind != "finish_selection" {
		t.Fatalf("order %v %v %v", p.Candidates[0].SortName, p.Candidates[1].Sem.Kind, p.Candidates[2].SortName)
	}
	q := &mapping.Pose{Context: protocol.Context{Kind: "priority"}, Candidates: []mapping.Cand{
		{Sem: protocol.PlayLand(ref("o-1", "Mountain"), 0)}, {Sem: protocol.Pass()}}}
	mapping.Finalize(q)
	if q.Candidates[0].Sem.Kind != "pass" {
		t.Fatal("pass is not candidate 0")
	}
	dup := &mapping.Pose{Context: protocol.Context{Kind: "priority"}, Candidates: []mapping.Cand{{Sem: protocol.Pass()}, {Sem: protocol.Pass()}}}
	if err := mapping.Finalize(dup); !errors.Is(err, mapping.ErrDuplicate) {
		t.Fatalf("duplicates: %v", err)
	}
}

func TestRouteNamesEveryPoolShape(t *testing.T) {
	cases := map[string]*decision.Decision{
		"choose/cost":            {Kind: decision.KChoose, Source: 9, Options: []decision.Option{{Kind: "sacrifice"}}},
		"choose/cleanup_discard": {Kind: decision.KChoose, Options: []decision.Option{{Kind: "discard"}}},
		"choose/mana_window":     {Kind: decision.KChoose, Options: []decision.Option{{Kind: "activate"}, {Kind: "done"}}},
		"choose/pay_pip":         {Kind: decision.KChoose, Options: []decision.Option{{Kind: "pay_R"}, {Kind: "pay_G"}}},
		"modes/unless":           {Kind: decision.KModes, Options: []decision.Option{{Kind: "mode", Mode: decision.ModeUnlessPay}}},
		"mulligan/bottom":        {Kind: decision.KMulligan, Options: []decision.Option{{Kind: "bottom"}}},
		"unmapped:choose/vote":   {Kind: decision.KChoose, Options: []decision.Option{{Kind: "vote"}}},
	}
	for want, d := range cases {
		if got := mapping.Route(d); got != want {
			t.Errorf("Route = %q, want %q", got, want)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/`
Expected: FAIL with `undefined: mapping.Finalize`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/tx.go`:

```go
// Package mapping turns one gorge decision into a transaction of v2
// decisions. The real engine advances only through the intents a
// transaction returns from Answer; clones answer every "what if".
package mapping

import (
	"errors"
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var (
	ErrDeadEnd            = errors.New("engine_contract_failure:dead_end")
	ErrUnmapped           = errors.New("engine_contract_failure:unmapped_decision")
	ErrCandidateLimit     = errors.New("engine_contract_failure:candidate_limit")
	ErrDuplicate          = errors.New("engine_contract_failure:duplicate_candidates")
	ErrUnresolvableSource = errors.New("engine_contract_failure:unresolvable_source")
)

// ActionContext is the acting seat's priority action in progress: the object
// it acts from, and Since, the engine's next object id when the action began
// (stack objects with a smaller id were on the stack before it).
type ActionContext struct {
	Seat  state.PlayerID
	Obj   state.ObjID
	Since state.ObjID
}

type Env struct {
	G       *gamecfg.Game
	Obs     *observe.Projector
	IDs     *identity.Tracker
	Action  *ActionContext
	Domain  map[string]bool
	Slots   map[string]uint32 // target slot counter per action (key: v2 id of the source)
	Looking [2]bool
}

// OpenLook starts the look a transaction needs before it mints look ids.
// The look lasts until the transaction completes (Section 5.3: ids are
// stable within one effect's decisions); the session calls CloseLooks.
func (e *Env) OpenLook(seat state.PlayerID) {
	if !e.Looking[seat] {
		e.IDs.OpenLook(seat)
		e.Looking[seat] = true
	}
}

func (e *Env) CloseLooks() {
	for s := range e.Looking {
		if e.Looking[s] {
			e.IDs.CloseLook(state.PlayerID(s))
			e.Looking[s] = false
		}
	}
}

// NativeOp is what a candidate means natively; x_gorge_view_v1 carries it
// (ids rekeyed) so a native agent can map its answer onto candidates.
// Op: "choose" (native option, plus folded follow-ups keyed "<option>" and
// "<option>/<follow-up option>"), "finish", "none" (a declaration unit
// declines), "cast" (a cast_spell standing for several native variants,
// listed in Covers), "list" (Option at Position of the native list named by
// List: "choices", "rest" or "followup:<key>"), "dest" (an arrangement
// partition, Task 19b).
type NativeOp struct {
	Op       string      `json:"op"`
	Option   int         `json:"option"`
	Followup []int       `json:"followup,omitempty"`
	List     string      `json:"list,omitempty"`
	Position int         `json:"position,omitempty"`
	Unit     state.ObjID `json:"unit,omitempty"`
	Covers   []int       `json:"covers,omitempty"`
}

type Cand struct {
	Sem              protocol.Semantic
	Op               NativeOp
	Hidden           bool
	SortName, SortID string
}

type Pose struct {
	Seat                       state.PlayerID
	Context                    protocol.Context
	GroupStart                 bool
	SubstepIndex, SubstepCount uint32
	Candidates                 []Cand
	Known                      []protocol.Known
	Look                       bool
	Native                     *decision.Decision
	Followups                  map[string]*decision.Decision
}

type Transaction interface {
	Pose() (*Pose, error)
	Answer(i int) (commit []decision.Intent, done bool, err error)
}

type Builder func(*Env, *decision.Decision) (Transaction, error)

var builders = map[string]Builder{}

func Register(route string, f Builder) { builders[route] = f }

func Begin(env *Env, d *decision.Decision) (Transaction, error) {
	r := Route(d)
	if f, ok := builders[r]; ok {
		return f(env, d)
	}
	return nil, fmt.Errorf("%w:%s", ErrUnmapped, r)
}

// InternalFunc answers a decision the engine makes itself, under a declared
// rule, without posing it (Section 7.6 and controller decision 3).
type InternalFunc func(*Env, *decision.Decision) (decision.Intent, error)

var internals = map[string]InternalFunc{}

// RegisterInternal makes route an engine-internal answer (Tasks 16 and 21).
func RegisterInternal(route string, f InternalFunc) { internals[route] = f }

// Internal answers d when its route is engine-internal; ok is false otherwise.
func Internal(env *Env, d *decision.Decision) (in decision.Intent, ok bool, err error) {
	f, ok := internals[Route(d)]
	if !ok {
		return decision.Intent{}, false, nil
	}
	in, err = f(env, d)
	return in, true, err
}

func Intent(d *decision.Decision, choices ...int) decision.Intent {
	return decision.Intent{Seq: d.Seq, Player: d.Player, Choices: choices}
}

func purpose(s string) *string { return &s }
```

`internal/mapping/route.go`:

```go
package mapping

import (
	"sort"
	"strings"

	"github.com/adams-shaun/gorge/decision"
)

func optKinds(d *decision.Decision) (set map[string]bool, sorted string) {
	set = map[string]bool{}
	var ks []string
	for _, o := range d.Options {
		if !set[o.Kind] {
			set[o.Kind] = true
			ks = append(ks, o.Kind)
		}
	}
	sort.Strings(ks)
	return set, strings.Join(ks, ",")
}

func Route(d *decision.Decision) string {
	k, sorted := optKinds(d)
	switch d.Kind {
	case decision.KPriority:
		return "priority"
	case decision.KAttackers:
		return "attackers"
	case decision.KBlockers:
		return "blockers"
	case decision.KTarget:
		return "target"
	case decision.KTriggerOrder:
		return "trigger_order"
	case decision.KModes:
		for _, o := range d.Options {
			if o.Mode == decision.ModeUnlessPay || o.Mode == decision.ModeUnlessDecline {
				return "modes/unless"
			}
		}
		if k["discard"] {
			return "modes/discard"
		}
		return "modes/mode"
	case decision.KMulligan:
		if k["bottom"] {
			return "mulligan/bottom"
		}
		return "mulligan/keep"
	case decision.KTriggerOptional:
		if d.ResumeKind == "madness" {
			return "trigger_optional/madness"
		}
		return "trigger_optional/optional"
	case decision.KReplacement:
		if k["madness_exile"] || k["madness_graveyard"] {
			return "replacement/madness"
		}
		if k["replacement"] {
			return "replacement/order"
		}
	case decision.KArrange:
		if len(d.Options) > 0 {
			return "arrange/" + d.Options[0].Kind
		}
	case decision.KChoose:
		switch {
		case k["activate"] || (k["done"] && len(k) == 1):
			return "choose/mana_window"
		case k["trigger_cost_pay"] || k["trigger_cost_decline"]:
			return "choose/trigger_cost"
		case k["sacrifice"] || k["tapcost"] || k["returncost"] || k["exile_cost"] || k["exile"] || (k["discard"] && d.Source != 0):
			return "choose/cost"
		case k["discard"]:
			return "choose/cleanup_discard"
		case k["yes"] || k["no"]:
			return "choose/yesno"
		case k["graveyard"] && k["top"]:
			return "choose/explore"
		}
		for _, o := range d.Options {
			if strings.HasPrefix(o.Kind, "pay_") {
				return "choose/pay_pip"
			}
		}
		if len(k) == 1 {
			for _, c := range []string{"search", "hand_move", "dig", "untap", "keep", "x", "number", "color", "type", "name", "division", "mana"} {
				if k[c] {
					return "choose/" + c
				}
			}
		}
	}
	return "unmapped:" + string(d.Kind) + "/" + sorted
}
```

`internal/mapping/source.go`:

```go
package mapping

import (
	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// ResolveSource finds a choice decision's v2 source (Section 7.3), in order:
//  1. the stack entry of the ability whose source is Decision.Source (topmost),
//     or Decision.Source itself when it is on the stack. While the acting seat
//     is still announcing its own action from Decision.Source, abilities put
//     on the stack before that action began are skipped: they are an earlier
//     activation of the same permanent, not this one;
//  2. the current visible incarnation of Decision.Source;
//  3. the object of the acting seat's last priority action (gorge chooses an
//     activated ability's targets and costs before pushing it: sourceprobe);
//  4. nil.
func ResolveSource(env *Env, d *decision.Decision) (*protocol.ObjectRef, error) {
	g := env.G.E.G
	if d.Source != 0 {
		a := env.Action
		announcing := a != nil && a.Seat == d.Player && a.Obj == d.Source
		for i := len(g.Stack) - 1; i >= 0; i-- {
			id := g.Stack[i]
			if announcing && id < a.Since {
				continue
			}
			if so := g.Obj(id); so != nil && so.Ability != nil && so.Source == d.Source {
				return env.Obs.Ref(d.Player, id)
			}
		}
		if r, err := env.Obs.Ref(d.Player, d.Source); r != nil || err != nil {
			return r, err
		}
	}
	if a := env.Action; a != nil && a.Seat == d.Player {
		return env.Obs.Ref(d.Player, a.Obj)
	}
	return nil, nil
}

// MustSource is ResolveSource for kinds whose source is typed R (never null).
func MustSource(env *Env, d *decision.Decision) (protocol.ObjectRef, error) {
	r, err := ResolveSource(env, d)
	if err != nil {
		return protocol.ObjectRef{}, err
	}
	if r == nil {
		return protocol.ObjectRef{}, ErrUnresolvableSource
	}
	return *r, nil
}
```

`internal/mapping/oracle.go`:

```go
package mapping

import "github.com/adams-shaun/gorge/decision"

// Accepts reports whether the engine accepts the intent sequence, judged on a
// clone (Decision.Validate first, as the cheap filter).
func Accepts(env *Env, ins ...decision.Intent) bool {
	if len(ins) > 0 {
		if d := env.G.E.Pending(); d != nil && d.Validate(ins[0]) != nil {
			return false
		}
	}
	_, err := env.G.Probe(ins...)
	return err == nil
}
```

`internal/mapping/finalize.go`:

```go
package mapping

import (
	"encoding/json"
	"fmt"
	"sort"
)

// Finalize applies Section 7.1: candidates referencing hidden-zone cards are
// ordered among themselves by (card_name, object_id); pass is candidate 0;
// semantics are pairwise distinct; at most 4096 candidates.
func Finalize(p *Pose) error {
	var slots []int
	var hidden []Cand
	for i, c := range p.Candidates {
		if c.Hidden {
			slots = append(slots, i)
			hidden = append(hidden, c)
		}
	}
	sort.SliceStable(hidden, func(i, j int) bool {
		if hidden[i].SortName != hidden[j].SortName {
			return hidden[i].SortName < hidden[j].SortName
		}
		return hidden[i].SortID < hidden[j].SortID
	})
	for k, i := range slots {
		p.Candidates[i] = hidden[k]
	}
	for i, c := range p.Candidates {
		if c.Sem.Kind == "pass" && i != 0 {
			p.Candidates = append([]Cand{c}, append(p.Candidates[:i:i], p.Candidates[i+1:]...)...)
			break
		}
	}
	if len(p.Candidates) == 0 {
		return ErrDeadEnd
	}
	if len(p.Candidates) > 4096 {
		return ErrCandidateLimit
	}
	seen := map[string]bool{}
	for _, c := range p.Candidates {
		b, err := json.Marshal(c.Sem)
		if err != nil {
			return err
		}
		if seen[string(b)] {
			return fmt.Errorf("%w: %s", ErrDuplicate, b)
		}
		seen[string(b)] = true
	}
	return nil
}
```

`internal/mapping/pick.go` (the generic subset transaction):

```go
package mapping

import (
	"encoding/json"
	"slices"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// PickSpec describes a Min..Max pick over native options, posed one pick per
// decision: a fixed group when Min == Max, else one group per decision with a
// finish candidate once Min is met (Section 7.5).
type PickSpec struct {
	D       *decision.Decision
	Options []int // native option indices, presentation order
	Sem     func(opt int, selected uint32) (Cand, error)
	Finish  func(selected uint32) protocol.Semantic // required when Min < Max
	Context protocol.Context
	Known   []protocol.Known
	Look    bool
}

type pickTx struct {
	env    *Env
	s      PickSpec
	chosen []int
	pose   *Pose
	memo   map[string]bool
}

func NewPick(env *Env, s PickSpec) Transaction { return &pickTx{env: env, s: s, memo: map[string]bool{}} }

// allOptions lists every native option index in offered order.
func allOptions(d *decision.Decision) []int {
	out := make([]int, len(d.Options))
	for i := range out {
		out[i] = i
	}
	return out
}

func (t *pickTx) fixed() bool { return t.s.D.Min == t.s.D.Max }

func key(xs []int) string { b, _ := json.Marshal(xs); return string(b) }

func (t *pickTx) accepts(choices []int) bool {
	k := key(choices)
	if v, ok := t.memo[k]; ok {
		return v
	}
	v := Accepts(t.env, Intent(t.s.D, choices...))
	t.memo[k] = v
	return v
}

// completable: some answer extending prefix is accepted (depth-first, bounded).
func (t *pickTx) completable(prefix []int, budget *int) bool {
	d := t.s.D
	if len(prefix) >= d.Min && t.accepts(prefix) {
		return true
	}
	if len(prefix) >= d.Max || *budget <= 0 {
		return false
	}
	for _, o := range t.s.Options {
		if !d.Repeatable && slices.Contains(prefix, o) {
			continue
		}
		*budget--
		if t.completable(append(slices.Clone(prefix), o), budget) {
			return true
		}
	}
	return false
}

func (t *pickTx) Pose() (*Pose, error) {
	d := t.s.D
	p := &Pose{Seat: d.Player, Context: t.s.Context, Known: t.s.Known, Look: t.s.Look, Native: d}
	if t.fixed() {
		p.GroupStart, p.SubstepIndex, p.SubstepCount = len(t.chosen) == 0, uint32(len(t.chosen)), uint32(d.Max)
	} else {
		p.GroupStart, p.SubstepCount = true, 1
	}
	for _, o := range t.s.Options {
		if !d.Repeatable && slices.Contains(t.chosen, o) {
			continue
		}
		budget := 64
		if !t.completable(append(slices.Clone(t.chosen), o), &budget) {
			continue
		}
		c, err := t.s.Sem(o, uint32(len(t.chosen)))
		if err != nil {
			return nil, err
		}
		c.Op = NativeOp{Op: "choose", Option: o}
		p.Candidates = append(p.Candidates, c)
	}
	if !t.fixed() && len(t.chosen) >= d.Min && t.accepts(t.chosen) {
		p.Candidates = append(p.Candidates, Cand{Sem: t.s.Finish(uint32(len(t.chosen))), Op: NativeOp{Op: "finish", Option: -1}})
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *pickTx) Answer(i int) ([]decision.Intent, bool, error) {
	op := t.pose.Candidates[i].Op
	if op.Op == "finish" {
		return []decision.Intent{Intent(t.s.D, t.chosen...)}, true, nil
	}
	t.chosen = append(t.chosen, op.Option)
	if len(t.chosen) == t.s.D.Max {
		return []decision.Intent{Intent(t.s.D, t.chosen...)}, true, nil
	}
	return nil, false, nil
}
```

`internal/mapping/single.go` (a one-decision transaction shared by Tasks 20 and 21):

```go
package mapping

import (
	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

type singleTx struct {
	pose  *Pose
	d     *decision.Decision
	after func(opt int) // optional hook run on the chosen native option
}

func (s *singleTx) Pose() (*Pose, error) { return s.pose, nil }

func (s *singleTx) Answer(i int) ([]decision.Intent, bool, error) {
	op := s.pose.Candidates[i].Op
	if s.after != nil {
		s.after(op.Option)
	}
	return []decision.Intent{Intent(s.d, op.Option)}, true, nil
}

// SingleChoice maps each native option to at most one candidate (ok false drops it).
func SingleChoice(env *Env, d *decision.Decision, ctx protocol.Context, sem func(o decision.Option) (protocol.Semantic, bool, error)) (Transaction, error) {
	p := &Pose{Seat: d.Player, Context: ctx, GroupStart: true, SubstepCount: 1, Native: d}
	for _, o := range d.Options {
		s, ok, err := sem(o)
		if err != nil {
			return nil, err
		}
		if ok {
			p.Candidates = append(p.Candidates, Cand{Sem: s, Op: NativeOp{Op: "choose", Option: o.Index}})
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	return &singleTx{pose: p, d: d}, nil
}

func choice(src *protocol.ObjectRef, p string) protocol.Context {
	var pp *string
	if p != "" {
		pp = &p
	}
	return protocol.Context{Kind: "choice", Source: src, Purpose: pp}
}
```

Default `ExpandActivate` in `tx.go`:

```go
// ExpandActivate turns one native "activate" option into candidates. Task 15
// replaces it with the lookahead version that folds colour and cost follow-ups.
var ExpandActivate = func(env *Env, d *decision.Decision, o decision.Option, src protocol.ObjectRef) ([]Cand, map[string]*decision.Decision, error) {
	return []Cand{{Sem: protocol.ActivateManaAbility(src, 0, nil, nil), Op: NativeOp{Op: "choose", Option: o.Index}}}, nil, nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -v`
Expected: `--- PASS: TestFinalizePutsPassFirstAndOrdersHiddenCandidates`, `--- PASS: TestRouteNamesEveryPoolShape`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: mapping framework, routing, sources, oracle, candidate rules"
```

---

### Task 14: Priority decisions

**Files:**
- Create: `internal/mapping/priority.go`
- Test: `internal/mapping/priority_test.go`
- Create: `internal/mapping/envtest_test.go` (test helper: builds an `Env` for a `testgame` game)

**Interfaces:**
- Consumes: framework (Task 13), `ExpandActivate`.
- Produces:
  - registered route `priority`;
  - `func mapping.CastMethod(o decision.Option, alternateMode string) (method string, optional string, special string, ok bool)` (`alternateMode` is the card's `AlternateMode`), with the mode tables below;
  - `func mapping.NonManaAbilityIndex(o *state.Object, abilityIdx int) uint32`.

Mode tables:
- method:
  - `"" mayplay mayflash` → `normal`; `flashback` → `flashback`; `plot_cast` → `plot`;
  - `bestowed surged blitzed emerged mutated` → `alternative`, as is any option with `AltCostIndex > 0`;
  - `escape` → `escape`; `madness` → `madness`; `miracle` → `miracle`; `foretell_cast` → `foretell`; `adventure_alt` → `adventure` for an Adventure card and `other` for an Omen face (Roost Seek), which v2's vocabulary has no word for; `split_alt` → `split_right`; `fuse` → `fuse`; `suspend_cast` → `suspend`; `modal_spell` → `mdfc_back`.
- optional cost: `kicked` → `kicker`, `buyback` → `buyback`, `entwined` → `entwine`, `conspired` → `conspire`, `casualty` → `casualty`, `offspring` → `offspring`.
- special action: cast `Mode` `plot` → `special_action` `plot`; priority kinds `turn_face_up` → `turn_face_up`, `unlock` → `unlock_door`.
- `concede` is never offered. Any other mode or kind fails closed as unmapped; the engine notes list those modes (Task 29).
- One cast candidate stands for one object, method and alternative cost: two alternative costs of one card key on `AltCostIndex`, so neither overwrites the other (their equal semantics then fail closed as duplicates).
- Optional-cost modes: gorge offers the plain and the optional-cost variants as two options for one object. The adapter offers one `cast_spell`; if the agent picks it, a follow-up `optional_cost` decision in its own group picks the native option. The follow-up's `source` is the card itself (still in hand), because gorge has not started casting.

- [ ] **Step 1: Write the failing test**

`internal/mapping/envtest_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func envFor(t *testing.T, g *gamecfg.Game) *mapping.Env {
	tr := identity.New(g.E, g.Secret)
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	return &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Slots: map[string]uint32{}}
}

// untilPending plays bots (no mulligans) until a pending decision satisfies pred.
func untilPending(t *testing.T, deck string, secret byte, pred func(*decision.Decision, *rules.Engine) bool) *gamecfg.Game {
	return untilPendingRules(t, deck, secret, "none", pred)
}

// untilPendingRules is untilPending with the mulligan rule ("london" or "none").
func untilPendingRules(t *testing.T, deck string, secret byte, mulligan string, pred func(*decision.Decision, *rules.Engine) bool) *gamecfg.Game {
	reg := testcorpus.Registry(t)
	for s := secret; s < secret+20; s++ {
		g := testgame.New(t, reg, deck, deck, s, mulligan)
		if testgame.RunUntil(t, g, testgame.Bots(uint64(s)), func(e *rules.Engine) bool {
			d := e.Pending()
			return d != nil && pred(d, e)
		}, 30000) {
			return g
		}
	}
	t.Fatalf("no %s game reached the wanted decision", deck)
	return nil
}

// answerAll drives a transaction to completion picking candidate pick(pose).
func answerAll(t *testing.T, tx mapping.Transaction, pick func(*mapping.Pose) int) []decision.Intent {
	var commits []decision.Intent
	for {
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		c, done, err := tx.Answer(pick(p))
		if err != nil {
			t.Fatal(err)
		}
		commits = append(commits, c...)
		if done {
			return commits
		}
	}
}
```

`internal/mapping/priority_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func hasOption(d *decision.Decision, kind, mode string) bool {
	for _, o := range d.Options {
		if o.Kind == kind && o.Mode == mode {
			return true
		}
	}
	return false
}

func TestPriorityPassFirstAndNoConcede(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && hasOption(d, "cast", "")
	})
	env := envFor(t, g)
	tx, err := mapping.Begin(env, g.E.Pending())
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.Candidates[0].Sem.Kind != "pass" || p.Context.Kind != "priority" {
		t.Fatalf("first candidate %s context %s", p.Candidates[0].Sem.Kind, p.Context.Kind)
	}
	for _, c := range p.Candidates {
		if c.Sem.Kind == "cast_spell" && c.Sem.Fields["method"] != "normal" && c.Sem.Fields["method"] != "flashback" {
			t.Errorf("unexpected method %v", c.Sem.Fields["method"])
		}
	}
}

func TestKickerBecomesAFollowUpOptionalCost(t *testing.T) {
	g := untilPending(t, "Rally", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KPriority && hasOption(d, "cast", "kicked")
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	cast := -1
	for i, c := range p.Candidates {
		if c.Sem.Kind == "cast_spell" && *c.Sem.Fields["source"].(protocol.ObjectRef).CardName == "Goblin Bushwhacker" {
			cast = i
		}
	}
	if cast < 0 {
		t.Fatal("no cast_spell for Goblin Bushwhacker")
	}
	commit, done, err := tx.Answer(cast)
	if err != nil || done || commit != nil {
		t.Fatalf("after cast: commit %v done %v err %v", commit, done, err)
	}
	f, _ := tx.Pose()
	if !f.GroupStart || f.Context.Kind != "choice" || f.Candidates[0].Sem.Kind != "optional_cost" || f.Candidates[0].Sem.Fields["cost"] != "kicker" {
		t.Fatalf("follow-up %+v", f.Candidates)
	}
	for i, c := range f.Candidates {
		if c.Sem.Fields["pay"] == true {
			commit, done, _ = tx.Answer(i)
		}
	}
	if !done || len(commit) != 1 || d.Options[commit[0].Choices[0]].Mode != "kicked" {
		t.Fatalf("kicked commit %v", commit)
	}
}

func TestCastMethodTable(t *testing.T) {
	for _, c := range []struct {
		opt                      decision.Option
		altMode                  string
		method, optional, action string
	}{
		{decision.Option{Kind: "cast"}, "", "normal", "", ""},
		{decision.Option{Kind: "cast", Mode: "kicked"}, "", "normal", "kicker", ""},
		{decision.Option{Kind: "cast", AltCostIndex: 1}, "", "alternative", "", ""},
		{decision.Option{Kind: "cast", Mode: "adventure_alt"}, "Adventure", "adventure", "", ""},
		{decision.Option{Kind: "cast", Mode: "adventure_alt"}, "Omen", "other", "", ""}, // Roost Seek
		{decision.Option{Kind: "cast", Mode: "plot"}, "", "", "", "plot"},
	} {
		m, o, a, ok := mapping.CastMethod(c.opt, c.altMode)
		if !ok || m != c.method || o != c.optional || a != c.action {
			t.Errorf("%+v %s: %q %q %q %v", c.opt, c.altMode, m, o, a, ok)
		}
	}
	if _, _, _, ok := mapping.CastMethod(decision.Option{Kind: "cast", Mode: "multikicked"}, ""); ok {
		t.Error("multikicker is mapped; it must fail closed")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'Priority|Kicker|CastMethod'`
Expected: FAIL to compile: `undefined: mapping.CastMethod`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/priority.go`:

```go
package mapping

import (
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var castMethods = map[string]string{"": "normal", "mayplay": "normal", "mayflash": "normal", "flashback": "flashback",
	"plot_cast": "plot", "bestowed": "alternative", "surged": "alternative", "blitzed": "alternative",
	"emerged": "alternative", "mutated": "alternative", "escape": "escape", "madness": "madness", "miracle": "miracle",
	"foretell_cast": "foretell", "adventure_alt": "adventure", "split_alt": "split_right", "fuse": "fuse",
	"suspend_cast": "suspend", "modal_spell": "mdfc_back"}

var optionalCostModes = map[string]string{"kicked": "kicker", "buyback": "buyback", "entwined": "entwine",
	"conspired": "conspire", "casualty": "casualty", "offspring": "offspring"}

// CastMethod classifies a "cast" option of a card whose AlternateMode is
// alternateMode: a method, or an optional cost over the normal method, or a
// special action. gorge's adventure_alt also casts an Omen face (Roost Seek),
// which v2's method vocabulary names only as "other". Every mode outside the
// tables fails closed (the engine notes list them).
func CastMethod(o decision.Option, alternateMode string) (method, optional, special string, ok bool) {
	if o.Mode == "plot" {
		return "", "", "plot", true
	}
	if c, ok := optionalCostModes[o.Mode]; ok {
		return "normal", c, "", true
	}
	if o.AltCostIndex > 0 {
		return "alternative", "", "", true
	}
	if o.Mode == "adventure_alt" && alternateMode != "Adventure" {
		return "other", "", "", true
	}
	m, ok := castMethods[o.Mode]
	return m, "", "", ok
}

func NonManaAbilityIndex(o *state.Object, abilityIdx int) uint32 {
	f := o.Face()
	n := uint32(0)
	for i, a := range f.Abilities {
		if i == abilityIdx {
			return n
		}
		if a.Kind == "AB" && a.API != "Mana" {
			n++
		}
	}
	return n
}

type castGroup struct {
	plain    int            // native index of the plain variant, -1 when absent
	optional map[string]int // cost -> native index
	cost     string
	method   string
	src      protocol.ObjectRef
}

type priorityTx struct {
	env       *Env
	d         *decision.Decision
	pose      *Pose
	groups    map[int]*castGroup // candidate index -> cast group needing a follow-up
	followup  *castGroup
	folds     map[string]*decision.Decision
	follPose  *Pose
}

func init() { Register("priority", newPriority) }

func newPriority(env *Env, d *decision.Decision) (Transaction, error) {
	return &priorityTx{env: env, d: d, groups: map[int]*castGroup{}}, nil
}

func (t *priorityTx) ref(id state.ObjID) (protocol.ObjectRef, error) {
	r, err := t.env.Obs.Ref(t.d.Player, id)
	if err != nil {
		return protocol.ObjectRef{}, err
	}
	if r == nil {
		return protocol.ObjectRef{}, fmt.Errorf("%w: priority option on hidden object %d", ErrUnmapped, id)
	}
	return *r, nil
}

func (t *priorityTx) Pose() (*Pose, error) {
	if t.followup != nil {
		return t.follPose, nil
	}
	d := t.d
	p := &Pose{Seat: d.Player, Context: protocol.Context{Kind: "priority"}, GroupStart: true, SubstepCount: 1, Native: d}
	casts := map[string]*castGroup{} // key: object and method
	for _, o := range d.Options {
		switch o.Kind {
		case "concede":
		case "pass":
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.Pass(), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "play_land":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			face := uint32(0)
			if o.Mode == "modal_land" {
				face = 1
			}
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.PlayLand(src, face), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "ability":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			idx := NonManaAbilityIndex(t.env.G.E.G.Obj(o.Obj), o.Ability)
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.ActivateAbility(src, idx), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "turn_face_up", "unlock":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			action := map[string]string{"turn_face_up": "turn_face_up", "unlock": "unlock_door"}[o.Kind]
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.SpecialAction(src, action), Op: NativeOp{Op: "choose", Option: o.Index}})
		case "activate":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			cs, folds, err := ExpandActivate(t.env, d, o, src)
			if err != nil {
				return nil, err
			}
			p.Candidates = append(p.Candidates, cs...)
			for k, v := range folds {
				if p.Followups == nil {
					p.Followups = map[string]*decision.Decision{}
				}
				p.Followups[k] = v
			}
		case "cast":
			src, err := t.ref(o.Obj)
			if err != nil {
				return nil, err
			}
			obj := t.env.G.E.G.Obj(o.Obj)
			method, optional, special, ok := CastMethod(o, obj.Card.AlternateMode)
			if !ok {
				return nil, fmt.Errorf("%w:cast_mode/%s", ErrUnmapped, o.Mode)
			}
			if special != "" {
				p.Candidates = append(p.Candidates, Cand{Sem: protocol.SpecialAction(src, special), Op: NativeOp{Op: "choose", Option: o.Index}})
				continue
			}
			// One candidate per object, method and alternative cost: two
			// alternative costs of one card stay two variants (their equal
			// semantics then fail closed as duplicates), never one overwriting
			// the other.
			key := fmt.Sprint(o.Obj, "/", method, "/", o.AltCostIndex)
			cg := casts[key]
			if cg == nil {
				cg = &castGroup{plain: -1, optional: map[string]int{}, src: src, method: method}
				casts[key] = cg
				p.Candidates = append(p.Candidates, Cand{Sem: protocol.CastSpell(src, method), Op: NativeOp{Op: "cast", Option: -1}})
				t.groups[len(p.Candidates)-1] = cg
			}
			if optional == "" {
				cg.plain = o.Index
			} else {
				cg.optional[optional] = o.Index
				cg.cost = optional
			}
		default:
			return nil, fmt.Errorf("%w:priority/%s", ErrUnmapped, o.Kind)
		}
	}
	// A cast group without optional variants is a plain choice; one with an
	// optional-cost variant stands for every native variant it covers.
	for i, cg := range t.groups {
		switch {
		case len(cg.optional) == 0:
			p.Candidates[i].Op = NativeOp{Op: "choose", Option: cg.plain}
		case len(cg.optional) > 1:
			return nil, fmt.Errorf("%w:several optional costs on one cast", ErrUnmapped)
		default:
			for _, opt := range cg.optional {
				p.Candidates[i].Op.Covers = append(p.Candidates[i].Op.Covers, opt)
			}
			if cg.plain >= 0 {
				p.Candidates[i].Op.Covers = append(p.Candidates[i].Op.Covers, cg.plain)
			}
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *priorityTx) Answer(i int) ([]decision.Intent, bool, error) {
	if t.followup != nil {
		op := t.follPose.Candidates[i].Op
		return []decision.Intent{Intent(t.d, op.Option)}, true, nil
	}
	c := t.pose.Candidates[i]
	if c.Op.Op == "cast" {
		var cg *castGroup
		src, method := c.Sem.Fields["source"].(protocol.ObjectRef), c.Sem.Fields["method"].(string)
		for _, g := range t.groups {
			if g.src.ObjectID == src.ObjectID && g.method == method {
				cg = g
			}
		}
		t.followup = cg
		f := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Source: &cg.src}, GroupStart: true, SubstepCount: 1, Native: t.d}
		for _, opt := range cg.optional {
			f.Candidates = append(f.Candidates, Cand{Sem: protocol.OptionalCost(cg.src, cg.cost, true), Op: NativeOp{Op: "choose", Option: opt}})
		}
		if cg.plain >= 0 {
			f.Candidates = append(f.Candidates, Cand{Sem: protocol.OptionalCost(cg.src, cg.cost, false), Op: NativeOp{Op: "choose", Option: cg.plain}})
		}
		if err := Finalize(f); err != nil {
			return nil, false, err
		}
		t.follPose = f
		return nil, false, nil
	}
	ins := []decision.Intent{Intent(t.d, c.Op.Option)}
	for _, f := range c.Op.Followup {
		ins = append(ins, decision.Intent{Choices: []int{f}}) // Seq and Player are filled by the session at commit
	}
	return ins, true, nil
}
```

The session fills each follow-up intent's `Seq` and `Player` from the engine's pending decision at commit time, after checking that the pending decision is the one the lookahead saw; otherwise the game halts `followup_mismatch` (Task 22).

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'Priority|Kicker|CastMethod' -v`
Expected: `--- PASS: TestPriorityPassFirstAndNoConcede`, `--- PASS: TestKickerBecomesAFollowUpOptionalCost`, `--- PASS: TestCastMethodTable`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: priority decisions, cast methods, kicker follow-up"
```

---

### Task 15: Mana abilities: lookahead expansion

**Files:**
- Create: `internal/mapping/mana.go`
- Test: `internal/mapping/mana_test.go`

**Interfaces:**
- Consumes: framework (Task 13), `gamecfg.Game.Probe`, Task 14's test helpers (`envFor`, `untilPending`).
- Produces:
  - replaces `mapping.ExpandActivate` (in `init()`);
  - `func mapping.ManaSymbol(o decision.Option) (string, bool)` (from `Option.ManaSymbol`, else a label ending `Add X`);
  - registered route `choose/mana`, which reaches the session only if a fold was missed; it fails closed.

Rules:
- The lookahead submits the activation on a clone.
- If the clone's next pending decision belongs to the same seat and is a mana follow-up, it is folded: colour options (`mana`) become `mana_choice`; single-object cost picks (`tapcost`, `sacrifice`, `discard`, `exile_cost`, `returncost`) become `cost_target`, recursing once for a colour after a cost.
- A source with several available mana abilities (Heap Gate: {T}: Add {C}; {1}, {T}: add one mana of any color) asks gorge's stage-1 "choose a mana ability" first. Its options are `mana` options that name their ability in `Option.Ability`, with a single pip (`Add C`) or none (`Pay 1: Add any color`). An option without a pip is probed and its stage-2 colour ask folded too: one candidate per colour, `Followup: [stage-1 option, colour]` (G2-1).
- `ability_index` is the stage-1 option's `Ability`: gorge numbers the source's available mana abilities, which is their Oracle order whenever all are available, and only then does it ask stage 1 (G2-11). A source that asks no stage 1 activates its only available ability, index 0: a single-ability source, or Heap Gate while its {1} ability is unpayable. The cost-then-colour fold is reached only by single-ability sources, so it keeps index 0.
- A plain source (basic land) is one candidate with `mana_choice: null`.
- `Followups` records each folded native follow-up decision, keyed `"<option>"` or `"<option>/<first follow-up option>"` (a cost pick or a stage-1 option), for `x_gorge_view_v1` and the session's follow-up check.

- [ ] **Step 1: Write the failing test**

`internal/mapping/mana_test.go`:

```go
package mapping_test

import (
	"fmt"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func untappedBridge(d *decision.Decision, e *rules.Engine) bool {
	if d.Kind != decision.KPriority {
		return false
	}
	for _, o := range d.Options {
		if o.Kind == "activate" && e.G.Obj(o.Obj).Face().Name == "Drossforge Bridge" {
			return true
		}
	}
	return false
}

func TestDualLandExpandsIntoOneCandidatePerColour(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, untappedBridge)
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	colours := map[string]int{}
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		src := c.Sem.Fields["source"].(protocol.ObjectRef)
		if *src.CardName == "Drossforge Bridge" {
			if mc, _ := c.Sem.Fields["mana_choice"].(*string); mc != nil {
				colours[*mc] = i
			}
		}
	}
	if len(colours) < 2 {
		t.Fatalf("bridge colours %v", colours)
	}
	commit, done, err := tx.Answer(colours["R"])
	if err != nil || !done || len(commit) != 2 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
	c, err := g.Probe(commit[0])
	if err != nil {
		t.Fatal(err)
	}
	f := c.Pending()
	commit[1].Seq, commit[1].Player = f.Seq, f.Player
	if err := c.SubmitHypothetical(commit[1]); err != nil {
		t.Fatal(err)
	}
	if c.G.Players[g.E.Pending().Player].Pool[state.MR] < 1 {
		t.Fatal("choosing R did not add red mana")
	}
}

// Heap Gate has two mana abilities ({T}: Add {C}; {1}, {T}: add one mana of
// any color). With mana floating, both are available, so activating it asks
// gorge's stage-1 "choose a mana ability", and the second ability then asks
// its colour: both asks fold into one decision, and each candidate names its
// ability by index (G2-1, G2-11).
func TestHeapGateFoldsItsTwoAbilitiesAndTheColourAsk(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KPriority {
			return false
		}
		for _, o := range d.Options {
			if o.Kind == "activate" && o.Cost != "" && e.G.Obj(o.Obj).Face().Name == "Heap Gate" {
				return true // the {1} ability is payable from the pool
			}
		}
		return false
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]int{} // "<ability_index>/<mana_choice>" -> candidate
	gate := ""
	for i, c := range p.Candidates {
		if c.Sem.Kind != "activate_mana_ability" {
			continue
		}
		src := c.Sem.Fields["source"].(protocol.ObjectRef)
		if *src.CardName != "Heap Gate" || (gate != "" && src.ObjectID != gate) {
			continue
		}
		gate = src.ObjectID
		mc, _ := c.Sem.Fields["mana_choice"].(*string)
		if mc == nil {
			t.Fatalf("Heap Gate candidate without a mana choice: %+v", c.Sem)
		}
		got[fmt.Sprint(c.Sem.Fields["ability_index"], "/", *mc)] = i
	}
	for _, want := range []string{"0/C", "1/W", "1/U", "1/B", "1/R", "1/G"} {
		if _, ok := got[want]; !ok {
			t.Fatalf("Heap Gate candidates %v lack %s", got, want)
		}
	}
	if len(got) != 6 {
		t.Fatalf("Heap Gate candidates %v, want 6", got)
	}
	commit, done, err := tx.Answer(got["1/G"])
	if err != nil || !done || len(commit) != 3 {
		t.Fatalf("commit %v done %v err %v", commit, done, err)
	}
	c, err := g.Probe(commit[0])
	if err != nil {
		t.Fatal(err)
	}
	for _, in := range commit[1:] {
		f := c.Pending()
		in.Seq, in.Player = f.Seq, f.Player
		if err := c.SubmitHypothetical(in); err != nil {
			t.Fatal(err)
		}
	}
	before, after := g.E.G.Players[d.Player].Pool, c.G.Players[d.Player].Pool
	if after[state.MG] != before[state.MG]+1 {
		t.Fatalf("green mana %d, want %d", after[state.MG], before[state.MG]+1)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'DualLand|HeapGate'`
Expected: FAIL with `bridge colours map[]` (the Task 13 default does not fold colours).

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/mana.go`:

```go
package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	ExpandActivate = expandActivate
	Register("choose/mana", func(*Env, *decision.Decision) (Transaction, error) {
		return nil, fmt.Errorf("%w:unfolded_mana_colour", ErrUnmapped)
	})
}

func ManaSymbol(o decision.Option) (string, bool) {
	if o.ManaSymbol != "" {
		return o.ManaSymbol, true
	}
	l := strings.TrimSpace(o.Label)
	if i := strings.LastIndex(l, "Add "); i >= 0 && len(l) == i+5 && strings.ContainsAny(l[i+4:], "WUBRGC") {
		return l[i+4:], true
	}
	return "", false
}

var costKinds = map[string]bool{"tapcost": true, "sacrifice": true, "discard": true, "exile_cost": true, "returncost": true}

func sameSeatChoose(c *rules.Engine, seat state.PlayerID) *decision.Decision {
	n := c.Pending()
	if n == nil || c.G.Over || n.Player != seat || n.Kind != decision.KChoose || len(n.Options) == 0 {
		return nil
	}
	return n
}

func expandActivate(env *Env, d *decision.Decision, o decision.Option, src protocol.ObjectRef) ([]Cand, map[string]*decision.Decision, error) {
	c, err := env.G.Probe(Intent(d, o.Index))
	if err != nil {
		return nil, nil, nil // the engine refuses this activation now: not offered
	}
	folds := map[string]*decision.Decision{}
	plain := []Cand{{Sem: protocol.ActivateManaAbility(src, 0, nil, nil), Op: NativeOp{Op: "choose", Option: o.Index}}}
	next := sameSeatChoose(c, d.Player)
	if next == nil {
		return plain, nil, nil
	}
	key := fmt.Sprint(o.Index)
	switch k := next.Options[0].Kind; {
	case k == "mana":
		// A colour ask, or gorge's stage-1 "choose a mana ability" ask for a
		// source with several available mana abilities (Heap Gate). Each
		// option carries its ability in Option.Ability (0 for a colour ask
		// of a single-ability source), and either a single pip or, for an
		// ability whose colour is asked next, none: that stage-2 colour ask
		// is folded as the follow-up "<option>/<stage-1 option>".
		folds[key] = next
		var out []Cand
		for _, co := range next.Options {
			idx := uint32(co.Ability)
			if sym, ok := ManaSymbol(co); ok {
				out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, idx, &sym, nil),
					Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index}}})
				continue
			}
			c2, err := env.G.Probe(Intent(d, o.Index), Intent(next, co.Index))
			if err != nil {
				continue // the engine refuses this ability now: not offered
			}
			n2 := sameSeatChoose(c2, d.Player)
			if n2 == nil || n2.Options[0].Kind != "mana" {
				return nil, nil, fmt.Errorf("%w:mana_ability/%q", ErrUnmapped, co.Label)
			}
			folds[fmt.Sprint(key, "/", co.Index)] = n2
			for _, col := range n2.Options {
				sym, ok := ManaSymbol(col)
				if !ok {
					return nil, nil, fmt.Errorf("%w:mana_option/%q", ErrUnmapped, col.Label)
				}
				out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, idx, &sym, nil),
					Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index, col.Index}}})
			}
		}
		return out, folds, nil
	case costKinds[k] && next.Min == 1 && next.Max == 1:
		folds[key] = next
		var out []Cand
		for _, co := range next.Options {
			target, err := env.Obs.Ref(d.Player, co.Obj)
			if err != nil || target == nil {
				return nil, nil, fmt.Errorf("%w:cost_target_hidden", ErrUnmapped)
			}
			ct := protocol.ObjectTarget(*target)
			c2, err := env.G.Probe(Intent(d, o.Index), Intent(next, co.Index))
			if err != nil {
				continue
			}
			if n2 := sameSeatChoose(c2, d.Player); n2 != nil && n2.Options[0].Kind == "mana" {
				folds[fmt.Sprint(key, "/", co.Index)] = n2
				for _, col := range n2.Options {
					sym, _ := ManaSymbol(col)
					out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, 0, &sym, &ct),
						Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index, col.Index}}})
				}
				continue
			}
			out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, 0, nil, &ct),
				Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index}}})
		}
		return out, folds, nil
	}
	return plain, nil, nil // any other follow-up (a trigger order, say) is posed on its own
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -v`
Expected: all mapping tests so far PASS, including `TestDualLandExpandsIntoOneCandidatePerColour` and `TestHeapGateFoldsItsTwoAbilitiesAndTheColourAsk`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: mana abilities folded with stage-1, colour and cost lookahead"
```

---

### Task 16: Combat: declare_attack, declare_block, engine-order damage

**Files:**
- Create: `internal/mapping/combat.go`
- Test: `internal/mapping/combat_test.go`

**Interfaces:**
- Consumes: framework (Task 13): `Accepts`, `Finalize`, `Intent`, `Register`.
- Produces:
  - registered routes `attackers`, `blockers`;
  - the internal answer `choose/division` (`RegisterInternal`): under hello_ok's `combat_damage_assignment: "engine_order"` the engine answers gorge's division ask itself;
  - `func mapping.Compositions(power int32, n int) [][]int32`, which reproduces gorge's `divisionOptions` enumeration order;
  - `func mapping.EngineOrderSplit(power int32, lethal []int32) []int32`, Section 7.6's engine-order split.

Rules (Section 7.5 Combat):
- One fixed group with one decision per creature that appears in the native options, in first-appearance order.
- A blocker whose group cap exceeds 1 gets one decision per additional block.
- Candidates: each legal defender (attack) or attacker (block), plus `null`.
- A candidate is offered only if some full declaration extending the current prefix is accepted by the engine: prefix alone, then the prefix repaired by `decision.FitRequired` (only if the repair keeps the prefix and adds options only for units not yet decided: FitRequired may prepend an option for the unit whose `null` candidate is being tested, which would re-decide it), then a bounded depth-first search.
- Combat damage (Section 7.6): gorge assigns trample damage, and divisions too large to ask, itself: lethal damage to each blocker in its blocker order, the rest to the last blocker or to the defender with trample. The engine declares that rule as `engine_order` and answers gorge's division ask for a non-trample attacker with the same split, so no `distribute` is posed. gorge measures lethal as the blocker's toughness (1 when the attacker has deathtouch), without subtracting damage already marked; the engine notes record it.

- [ ] **Step 1: Write the failing test**

`internal/mapping/combat_test.go`:

```go
package mapping_test

import (
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestAttackGroupHasOneDecisionPerCreature(t *testing.T) {
	g := untilPending(t, "Rally", 1, func(d *decision.Decision, e *rules.Engine) bool {
		seen := map[any]bool{}
		for _, o := range d.Options {
			seen[o.Obj] = true
		}
		return d.Kind == decision.KAttackers && len(seen) >= 2
	})
	env := envFor(t, g)
	d := g.E.Pending()
	creatures := map[any]bool{}
	for _, o := range d.Options {
		creatures[o.Obj] = true
	}
	tx, _ := mapping.Begin(env, d)
	substeps := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		if p.SubstepCount != uint32(len(creatures)) || p.SubstepIndex != uint32(substeps) {
			t.Fatalf("substep %d/%d, want %d/%d", p.SubstepIndex, p.SubstepCount, substeps, len(creatures))
		}
		substeps++
		for i, c := range p.Candidates {
			if c.Sem.Kind != "declare_attack" {
				t.Fatalf("candidate kind %s", c.Sem.Kind)
			}
			if def, _ := c.Sem.Fields["defender"].(*protocol.TargetRef); def != nil {
				return i // attack with everything the engine allows
			}
		}
		return 0
	})
	if substeps != len(creatures) || len(commit) != 1 {
		t.Fatalf("substeps %d commit %v", substeps, commit)
	}
	if !mapping.Accepts(env, commit[0]) {
		t.Fatal("the assembled declaration is rejected")
	}
}

func TestCompositionsMatchGorgeOrder(t *testing.T) {
	got := mapping.Compositions(2, 2)
	want := [][]int32{{0, 2}, {1, 1}, {2, 0}}
	if len(got) != len(want) {
		t.Fatalf("%v", got)
	}
	for i := range want {
		if got[i][0] != want[i][0] || got[i][1] != want[i][1] {
			t.Fatalf("%v", got)
		}
	}
}

// Section 7.6's engine_order split, which the engine applies to gorge's
// division ask instead of posing distribute (combat_damage_assignment is
// declared "engine_order"): lethal to each blocker in order, the rest to the
// last blocker.
func TestEngineOrderSplit(t *testing.T) {
	for _, c := range []struct {
		power  int32
		lethal []int32
		want   []int32
	}{
		{5, []int32{2, 2, 2}, []int32{2, 2, 1}},
		{7, []int32{2, 2}, []int32{2, 5}},
		{1, []int32{2, 2}, []int32{1, 0}},
		{3, []int32{1, 1, 1}, []int32{1, 1, 1}},
	} {
		if got := mapping.EngineOrderSplit(c.power, c.lethal); !slices.Equal(got, c.want) {
			t.Errorf("EngineOrderSplit(%d, %v) = %v, want %v", c.power, c.lethal, got, c.want)
		}
	}
	d := &decision.Decision{Kind: decision.KChoose, Options: []decision.Option{{Kind: "division"}}}
	if mapping.Route(d) != "choose/division" {
		t.Fatalf("route %s", mapping.Route(d))
	}
	if _, ok, _ := mapping.Internal(nil, &decision.Decision{Kind: decision.KAttackers}); ok {
		t.Fatal("an attack declaration is answered internally")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'AttackGroup|Compositions|EngineOrder'`
Expected: FAIL to compile: `undefined: mapping.Compositions` and `undefined: mapping.EngineOrderSplit`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/combat.go`:

```go
package mapping

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	Register("attackers", func(env *Env, d *decision.Decision) (Transaction, error) { return newDeclare(env, d, true) })
	Register("blockers", func(env *Env, d *decision.Decision) (Transaction, error) { return newDeclare(env, d, false) })
	RegisterInternal("choose/division", engineOrderDivision)
}

type declareTx struct {
	env    *Env
	d      *decision.Decision
	attack bool
	units  []state.ObjID // one entry per decision (a blocker repeats per extra block)
	chosen []int
	i      int
	pose   *Pose
	memo   map[string]bool
}

func newDeclare(env *Env, d *decision.Decision, attack bool) (Transaction, error) {
	t := &declareTx{env: env, d: d, attack: attack, memo: map[string]bool{}}
	seen := map[state.ObjID]bool{}
	for _, o := range d.Options {
		if seen[o.Obj] {
			continue
		}
		seen[o.Obj] = true
		n := 1
		if !attack && o.Group != "" {
			n = d.GroupCapFor(o.Group)
		}
		for k := 0; k < n; k++ {
			t.units = append(t.units, o.Obj)
		}
	}
	return t, nil
}

func (t *declareTx) accepts(ch []int) bool {
	b, _ := json.Marshal(ch)
	if v, ok := t.memo[string(b)]; ok {
		return v
	}
	v := Accepts(t.env, Intent(t.d, ch...))
	t.memo[string(b)] = v
	return v
}

// completable: a full declaration extending prefix, deciding only units from `from` on.
func (t *declareTx) completable(prefix []int, from int, budget *int) bool {
	if t.accepts(prefix) {
		return true
	}
	if fr := t.d.FitRequired(prefix); t.laterUnitsOnly(prefix, fr, from) && t.accepts(fr) {
		return true
	}
	for u := from; u < len(t.units) && *budget > 0; u++ {
		for _, o := range t.d.Options {
			if o.Obj != t.units[u] || slices.Contains(prefix, o.Index) {
				continue
			}
			*budget--
			if t.completable(append(slices.Clone(prefix), o.Index), u+1, budget) {
				return true
			}
		}
	}
	return false
}

// laterUnitsOnly reports whether the repair fr keeps prefix and adds options
// only for units at index from or later. FitRequired may add an option for a
// unit already decided (the current unit, when its null candidate is being
// tested): that completion would re-decide it, so it proves nothing.
func (t *declareTx) laterUnitsOnly(prefix, fr []int, from int) bool {
	if len(fr) < len(prefix) || !slices.Equal(fr[:len(prefix)], prefix) {
		return false
	}
	for _, o := range fr[len(prefix):] {
		if !slices.Contains(t.units[from:], t.d.Options[o].Obj) {
			return false
		}
	}
	return true
}

func (t *declareTx) ref(id state.ObjID) (protocol.ObjectRef, error) {
	r, err := t.env.Obs.Ref(t.d.Player, id)
	if err != nil || r == nil {
		return protocol.ObjectRef{}, fmt.Errorf("%w: combat object %d not visible", ErrUnmapped, id)
	}
	return *r, nil
}

func (t *declareTx) Pose() (*Pose, error) {
	unit := t.units[t.i]
	u, err := t.ref(unit)
	if err != nil {
		return nil, err
	}
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice"}, GroupStart: t.i == 0,
		SubstepIndex: uint32(t.i), SubstepCount: uint32(len(t.units)), Native: t.d}
	for _, o := range t.d.Options {
		if o.Obj != unit || slices.Contains(t.chosen, o.Index) {
			continue
		}
		budget := 32
		if !t.completable(append(slices.Clone(t.chosen), o.Index), t.i+1, &budget) {
			continue
		}
		var sem protocol.Semantic
		if t.attack {
			def := protocol.PlayerTarget(observe.Seat(o.Player))
			if o.Battle != 0 {
				b, err := t.ref(o.Battle)
				if err != nil {
					return nil, err
				}
				def = protocol.ObjectTarget(b)
			}
			sem = protocol.DeclareAttack(u, &def)
		} else {
			a, err := t.ref(o.Attacker)
			if err != nil {
				return nil, err
			}
			sem = protocol.DeclareBlock(u, &a)
		}
		p.Candidates = append(p.Candidates, Cand{Sem: sem, Op: NativeOp{Op: "choose", Option: o.Index, Unit: unit}})
	}
	budget := 32
	if t.completable(slices.Clone(t.chosen), t.i+1, &budget) {
		none := protocol.DeclareBlock(u, nil)
		if t.attack {
			none = protocol.DeclareAttack(u, nil)
		}
		p.Candidates = append(p.Candidates, Cand{Sem: none, Op: NativeOp{Op: "none", Option: -1, Unit: unit}})
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *declareTx) Answer(i int) ([]decision.Intent, bool, error) {
	if op := t.pose.Candidates[i].Op; op.Op == "choose" {
		t.chosen = append(t.chosen, op.Option)
	}
	t.i++
	if t.i == len(t.units) {
		return []decision.Intent{Intent(t.d, t.chosen...)}, true, nil
	}
	return nil, false, nil
}

// Compositions reproduces gorge rules.divisionOptions: every nonnegative split
// of power over n recipients, first recipient's amount ascending outermost.
func Compositions(power int32, n int) [][]int32 {
	var out [][]int32
	cur := make([]int32, 0, n)
	var rec func(rem int32, idx int)
	rec = func(rem int32, idx int) {
		if idx == n-1 {
			out = append(out, append(append([]int32(nil), cur...), rem))
			return
		}
		for v := int32(0); v <= rem; v++ {
			cur = append(cur, v)
			rec(rem-v, idx+1)
			cur = cur[:len(cur)-1]
		}
	}
	rec(power, 0)
	return out
}

// EngineOrderSplit is Section 7.6's engine_order combat damage assignment
// over blockers in gorge's order: lethal damage to each blocker, the rest to
// the last one. lethal[i] is blocker i's lethal amount.
func EngineOrderSplit(power int32, lethal []int32) []int32 {
	out := make([]int32, len(lethal))
	remaining := power
	for i, need := range lethal {
		give := remaining
		if i < len(lethal)-1 && give > need {
			give = max(0, need)
		}
		out[i] = give
		remaining -= give
	}
	return out
}

// engineOrderDivision answers gorge's combat damage division ask itself,
// under hello_ok's combat_damage_assignment "engine_order": gorge's blocker
// order, and gorge's measure of lethal (the blocker's toughness, 1 when the
// attacker has deathtouch). gorge assigns trample damage and divisions too
// large to ask with the same rule (rules/combat.go), so every combat follows
// one declared rule and no distribute decision is ever posed.
func engineOrderDivision(env *Env, d *decision.Decision) (decision.Intent, error) {
	e := env.G.E
	a := e.G.Obj(d.Source)
	if a == nil || len(d.Options) == 0 {
		return decision.Intent{}, fmt.Errorf("%w:division_without_attacker", ErrUnmapped)
	}
	power := int32(d.Options[len(d.Options)-1].Amount)
	var live []state.ObjID
	for _, b := range a.BlockedBy {
		if o := e.G.Obj(b); o != nil && o.Zone == state.ZBattlefield {
			live = append(live, b)
		}
	}
	splits := Compositions(power, len(live))
	if len(live) < 2 || len(splits) != len(d.Options) {
		return decision.Intent{}, fmt.Errorf("%w:division_layout", ErrUnmapped)
	}
	for i, o := range d.Options {
		if int32(o.Amount) != splits[i][0] || len(strings.Split(o.Label, ",")) != len(live) {
			return decision.Intent{}, fmt.Errorf("%w:division_layout", ErrUnmapped)
		}
	}
	lethal := make([]int32, len(live))
	for i, b := range live {
		lethal[i] = e.Toughness(b)
		if e.HasKeyword(a.ID, "Deathtouch") {
			lethal[i] = 1
		}
	}
	want := EngineOrderSplit(power, lethal)
	for k, split := range splits {
		if slices.Equal(split, want) {
			return Intent(d, k), nil
		}
	}
	return decision.Intent{}, fmt.Errorf("%w:division_split", ErrUnmapped)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'AttackGroup|Compositions|EngineOrder' -v`
Expected: `--- PASS: TestAttackGroupHasOneDecisionPerCreature`, `--- PASS: TestCompositionsMatchGorgeOrder`, `--- PASS: TestEngineOrderSplit`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: attack and block declarations with witnesses, engine-order combat damage"
```

---

### Task 17: Targets and costs

**Files:**
- Create: `internal/mapping/targets.go`
- Test: `internal/mapping/targets_test.go`

**Interfaces:**
- Consumes: `NewPick`, `PickSpec`, `MustSource` (Task 13).
- Produces:
  - registered routes `target` and `choose/cost`;
  - `func mapping.TargetOf(env *Env, d *decision.Decision, o decision.Option) (protocol.TargetRef, error)`;
  - `var mapping.CostKinds map[string]string` (`sacrifice` to `sacrifice`, `discard` to `discard`, `tapcost` to `tap`, `returncost` to `return_to_hand`, `exile_cost` and `exile` to `exile`).

Rules:
- A target requirement's `slot` counts the target decisions already completed for the same source in this action; `Env.Slots` is keyed by the source's v2 id and reset by the session at each priority decision.
- Fixed-count targets and costs (`Min == Max`) are one fixed group.
- Variable targets offer `finish_target_selection`; a variable cost selection becomes `select_object` plus `finish_selection`, because `choose_cost_target` has no finish kind. Purpose is `delve` for an exile from a graveyard, else the cost kind's purpose.

- [ ] **Step 1: Write the failing test**

`internal/mapping/targets_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestBoltTargetsAreSlotZeroWithStackSource(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KTarget && e.G.Obj(d.Source) != nil && e.G.Obj(d.Source).Face().Name == "Lightning Bolt"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range p.Candidates {
		f := c.Sem.Fields
		if c.Sem.Kind != "choose_target" || f["slot"] != uint32(0) || f["minimum"] != uint32(1) || f["maximum"] != uint32(1) {
			t.Fatalf("candidate %+v", c.Sem)
		}
		if src := f["source"].(protocol.ObjectRef); src.Zone != "stack" {
			t.Fatalf("source zone %s", src.Zone)
		}
	}
}

func TestFireblastSacrificeIsAFixedCostGroup(t *testing.T) {
	g := untilPending(t, "Burn", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "sacrifice" && d.Min == 2 && d.Max == 2
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	var sizes []uint32
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		sizes = append(sizes, p.SubstepCount)
		if p.Candidates[0].Sem.Kind != "choose_cost_target" || p.Candidates[0].Sem.Fields["cost_kind"] != "sacrifice" {
			t.Fatalf("candidate %+v", p.Candidates[0].Sem)
		}
		return 0
	})
	if len(sizes) != 2 || sizes[0] != 2 || len(commit) != 1 || len(commit[0].Choices) != 2 {
		t.Fatalf("sizes %v commit %v", sizes, commit)
	}
}
```

`targets_test.go` also imports `github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol`.

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'BoltTargets|FireblastSacrifice'`
Expected: FAIL with `unmapped_decision:target`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/targets.go`:

```go
package mapping

import (
	"fmt"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var CostKinds = map[string]string{"sacrifice": "sacrifice", "discard": "discard", "tapcost": "tap",
	"returncost": "return_to_hand", "exile_cost": "exile", "exile": "exile"}

var costPurposes = map[string]string{"sacrifice": "sacrifice", "discard": "discard", "tap": "tap",
	"return_to_hand": "return_to_hand", "exile": "exile"}

func init() {
	Register("target", newTargets)
	Register("choose/cost", newCost)
}

func TargetOf(env *Env, d *decision.Decision, o decision.Option) (protocol.TargetRef, error) {
	if o.Kind == "player" {
		return protocol.PlayerTarget(observe.Seat(o.Player)), nil
	}
	r, err := env.Obs.Ref(d.Player, o.Obj)
	if err != nil || r == nil {
		return protocol.TargetRef{}, fmt.Errorf("%w: target %d not visible", ErrUnmapped, o.Obj)
	}
	return protocol.ObjectTarget(*r), nil
}

// slotTx wraps a target pick to count the slot when it completes.
type slotTx struct {
	Transaction
	env *Env
	key string
}

func (s *slotTx) Answer(i int) ([]decision.Intent, bool, error) {
	c, done, err := s.Transaction.Answer(i)
	if done {
		s.env.Slots[s.key]++
	}
	return c, done, err
}

func newTargets(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	slot := env.Slots[src.ObjectID]
	lo, hi := uint32(d.Min), uint32(d.Max)
	spec := PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: &src},
		Sem: func(opt int, sel uint32) (Cand, error) {
			tg, err := TargetOf(env, d, d.Options[opt])
			return Cand{Sem: protocol.ChooseTarget(src, slot, tg, sel, lo, hi)}, err
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishTargetSelection(src, slot, sel) }}
	return &slotTx{Transaction: NewPick(env, spec), env: env, key: src.ObjectID}, nil
}

func newCost(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	kind, ok := CostKinds[d.Options[0].Kind]
	if !ok {
		return nil, fmt.Errorf("%w:cost/%s", ErrUnmapped, d.Options[0].Kind)
	}
	lo, hi := uint32(d.Min), uint32(d.Max)
	ref := func(opt int) (protocol.ObjectRef, error) {
		r, err := env.Obs.Ref(d.Player, d.Options[opt].Obj)
		if err != nil || r == nil {
			return protocol.ObjectRef{}, fmt.Errorf("%w: cost object not visible", ErrUnmapped)
		}
		return *r, nil
	}
	spec := PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: &src}}
	if d.Min == d.Max {
		spec.Sem = func(opt int, sel uint32) (Cand, error) {
			r, err := ref(opt)
			return Cand{Sem: protocol.ChooseCostTarget(src, kind, r, sel, lo, hi)}, err
		}
		return NewPick(env, spec), nil
	}
	purp := costPurposes[kind]
	if kind == "exile" && env.G.E.G.Obj(d.Options[0].Obj).Zone == state.ZGraveyard {
		purp = "delve"
	}
	spec.Context.Purpose = &purp
	spec.Sem = func(opt int, sel uint32) (Cand, error) {
		r, err := ref(opt)
		return Cand{Sem: protocol.SelectObject(&src, purp, protocol.ObjectTarget(r), sel, lo, hi)}, err
	}
	spec.Finish = func(sel uint32) protocol.Semantic { return protocol.FinishSelection(&src, purp, sel) }
	return NewPick(env, spec), nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'BoltTargets|FireblastSacrifice' -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: targets with slots, fixed and variable costs"
```

---

### Task 18: Selections and modes

**Files:**
- Create: `internal/mapping/select.go`
- Test: `internal/mapping/select_test.go`

**Interfaces:**
- Consumes: `NewPick`, `ResolveSource`, `MustSource`, `Env.OpenLook`, `observe.KnownEntry`, `Projector.LookRef`.
- Produces registered routes:
  - `choose/cleanup_discard`, `modes/discard` (`select_object` `discard`);
  - `choose/search` (`select_object` `search`, hidden-zone candidates, `known` entries how `searching`);
  - `choose/hand_move`:
    - destination exile from the other seat's hand: `select_object` `exile`, `known` how `revealed`;
    - any library destination: delegated to the route `hand_move/library` registered by Task 19a;
  - `choose/untap` (`untap`), `choose/keep` (`legend_rule`);
  - `modes/mode` (`choose_spell_mode`, `finish_selection` `modes` when variable). gorge offers only the eligible modes, so `mode_index` is the offered mode's printed index and `mode_count` the printed count (G2-10), the numbering the stack entry's `modes` use (Task 12);
- Produces `func mapping.PrintedModes(d *decision.Decision) ([]uint32, uint32, error)`: each offered option's printed mode index (from `ResumeModes` within `ResumeSA`'s `Choices`) and the printed count; dense when the decision has no `ResumeModes`. Task 28a's consistency audit reads it.

- [ ] **Step 1: Write the failing test**

`internal/mapping/select_test.go`:

```go
package mapping_test

import (
	"slices"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestSearchCandidatesAreSortedAndKnown(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 1 && d.Options[0].Kind == "search"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	var prev string
	finish := false
	for _, c := range p.Candidates {
		switch c.Sem.Kind {
		case "finish_selection":
			finish = true
		case "select_object":
			if c.Sem.Fields["purpose"] != "search" {
				t.Fatalf("purpose %v", c.Sem.Fields["purpose"])
			}
			key := c.SortName + "\x00" + c.SortID
			if key < prev {
				t.Fatalf("hidden candidates out of (name, id) order")
			}
			prev = key
		}
	}
	if !finish || len(p.Known) == 0 || p.Known[0].How != "searching" || p.Known[0].PositionFromTop != nil {
		t.Fatalf("finish %v known %+v", finish, p.Known)
	}
}

// gorge offers only Thraben Charm's eligible modes; each candidate still
// names the printed mode and the printed count of three (G2-10).
func TestModalSpellNamesPrintedModes(t *testing.T) {
	printed := func(e *rules.Engine, d *decision.Decision) []string {
		var out []string
		for _, c := range strings.Split(e.G.Obj(d.Source).Face().SpellAbility().Params["Choices"], ",") {
			out = append(out, strings.TrimSpace(c))
		}
		return out
	}
	g := untilPending(t, "CawGates", 17, func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KModes || e.G.Obj(d.Source) == nil || e.G.Obj(d.Source).Face().Name != "Thraben Charm" {
			return false
		}
		return len(d.ResumeModes) > 0 && d.ResumeModes[0] != printed(e, d)[0] // the first printed mode was filtered out
	})
	env := envFor(t, g)
	d := g.E.Pending()
	names := printed(g.E, d)
	tx, _ := mapping.Begin(env, d)
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range p.Candidates {
		if c.Sem.Kind != "choose_spell_mode" {
			continue
		}
		want := uint32(slices.Index(names, d.ResumeModes[c.Op.Option]))
		if c.Sem.Fields["mode_index"] != want || c.Sem.Fields["mode_count"] != uint32(3) {
			t.Fatalf("option %d: %+v, want mode_index %d of 3", c.Op.Option, c.Sem.Fields, want)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'SearchCandidates|ModalSpell'`
Expected: FAIL with `unmapped_decision:choose/search`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/select.go`:

```go
package mapping

import (
	"fmt"
	"slices"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var handDestPurpose = map[string]string{"Hand": "put_into_hand", "Battlefield": "put_onto_battlefield",
	"Graveyard": "put_into_graveyard"}

func init() {
	Register("choose/cleanup_discard", visibleSelect("discard", false))
	Register("modes/discard", visibleSelect("discard", true))
	Register("choose/untap", visibleSelect("untap", true))
	Register("choose/keep", visibleSelect("legend_rule", true))
	Register("choose/search", newSearch)
	Register("choose/hand_move", newHandMove)
	Register("modes/mode", newModes)
}

func visibleSelect(purp string, withSource bool) Builder {
	return func(env *Env, d *decision.Decision) (Transaction, error) {
		var src *protocol.ObjectRef
		if withSource {
			var err error
			if src, err = ResolveSource(env, d); err != nil {
				return nil, err
			}
		}
		lo, hi := uint32(d.Min), uint32(d.Max)
		return NewPick(env, PickSpec{D: d, Options: allOptions(d),
			Context: protocol.Context{Kind: "choice", Source: src, Purpose: &purp},
			Sem: func(opt int, sel uint32) (Cand, error) {
				r, err := env.Obs.Ref(d.Player, d.Options[opt].Obj)
				if err != nil || r == nil {
					return Cand{}, fmt.Errorf("%w: %s object not visible", ErrUnmapped, purp)
				}
				return Cand{Sem: protocol.SelectObject(src, purp, protocol.ObjectTarget(*r), sel, lo, hi)}, nil
			},
			Finish: func(sel uint32) protocol.Semantic { return protocol.FinishSelection(src, purp, sel) }}), nil
	}
}

// hiddenSelect presents options whose objects sit in a zone hidden from the
// chooser (a library, or the other seat's hand) under look ids.
func hiddenSelect(env *Env, d *decision.Decision, purp, how string) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	env.OpenLook(d.Player)
	refs := map[int]protocol.ObjectRef{}
	var known []protocol.Known
	for i, o := range d.Options {
		r, err := env.Obs.LookRef(d.Player, o.Obj)
		if err != nil {
			return nil, err
		}
		refs[i] = r
		known = append(known, observe.KnownEntry(r, how, nil))
	}
	observe.SortKnown(known)
	lo, hi := uint32(d.Min), uint32(d.Max)
	return NewPick(env, PickSpec{D: d, Options: allOptions(d), Known: known, Look: true,
		Context: protocol.Context{Kind: "choice", Source: src, Purpose: &purp},
		Sem: func(opt int, sel uint32) (Cand, error) {
			r := refs[opt]
			return Cand{Sem: protocol.SelectObject(src, purp, protocol.ObjectTarget(r), sel, lo, hi),
				Hidden: true, SortName: *r.CardName, SortID: r.ObjectID}, nil
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishSelection(src, purp, sel) }}), nil
}

func newSearch(env *Env, d *decision.Decision) (Transaction, error) {
	return hiddenSelect(env, d, "search", "searching")
}

func newHandMove(env *Env, d *decision.Decision) (Transaction, error) {
	dest := ""
	if d.ResumeSA != nil {
		dest = d.ResumeSA.Params["Destination"]
	}
	owner := env.G.E.G.Obj(d.Options[0].Obj).Owner
	switch {
	case dest == "Library":
		if f, ok := builders["hand_move/library"]; ok {
			return f(env, d)
		}
	case dest == "Exile" && owner != d.Player:
		return hiddenSelect(env, d, "exile", "revealed")
	case owner == d.Player && handDestPurpose[dest] != "":
		return visibleSelect(handDestPurpose[dest], true)(env, d)
	}
	return nil, fmt.Errorf("%w:hand_move/%s", ErrUnmapped, dest)
}

// newModes poses one choose_spell_mode per pick. gorge offers only the
// eligible modes (Thraben Charm without a creature to target starts at its
// second mode), so a candidate names the printed mode and count (Section
// 7.3), the numbering the stack entry's modes use (Task 12).
func newModes(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	index, n, err := PrintedModes(d)
	if err != nil {
		return nil, err
	}
	lo, hi := uint32(d.Min), uint32(d.Max)
	purp := "modes"
	return NewPick(env, PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: &src},
		Sem: func(opt int, sel uint32) (Cand, error) {
			return Cand{Sem: protocol.ChooseSpellMode(src, index[opt], n, sel, lo, hi)}, nil
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishSelection(&src, purp, sel) }}), nil
}

// PrintedModes maps each offered mode option to its index among the modal
// ability's printed modes (ResumeSA's Choices, in Oracle order), and returns
// the printed mode count. gorge names each offered mode in ResumeModes; a
// decision without them offers every printed mode, densely.
func PrintedModes(d *decision.Decision) ([]uint32, uint32, error) {
	index := make([]uint32, len(d.Options))
	for i := range index {
		index[i] = uint32(i)
	}
	if len(d.ResumeModes) == 0 || d.ResumeSA == nil {
		return index, uint32(len(d.Options)), nil
	}
	var printed []string
	for _, c := range strings.Split(d.ResumeSA.Params["Choices"], ",") {
		printed = append(printed, strings.TrimSpace(c))
	}
	if len(d.ResumeModes) != len(d.Options) {
		return nil, 0, fmt.Errorf("%w:modes_layout", ErrUnmapped)
	}
	for i, name := range d.ResumeModes {
		k := slices.Index(printed, strings.TrimSpace(name))
		if k < 0 {
			return nil, 0, fmt.Errorf("%w:modes_layout", ErrUnmapped)
		}
		index[i] = uint32(k)
	}
	return index, uint32(len(printed)), nil
}
```

An own-hand move to a destination outside `handDestPurpose` fails closed as unmapped.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'SearchCandidates|ModalSpell' -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: selections (discard, search, revealed hand, untap, legend) and modes"
```

---

### Task 19a: Ordering

**Files:**
- Create: `internal/mapping/order.go`
- Test: `internal/mapping/order_test.go`

**Interfaces:**
- Consumes: framework (Task 13): `NewPick`, `PickSpec`, `ResolveSource`, `Finalize`; Task 14's test helpers.
- Native ops (read by Task 26's agent): ordering candidates are `list` (List `choices`; Option the item's option in the native decision; Position its place in the order).
- Produces registered routes:
  - `trigger_order`: `order_pick` `triggers`, n-1 decisions, last implied;
  - `mulligan/bottom`: `order_pick` `mulligan_bottom`, all k posed;
  - `hand_move/library`: `select_object` picks (a fixed group, or a `finish_selection` once the minimum is met when the ask is variable), then `order_pick` `library_top`.

A trigger item's `instance` numbers the triggers whose visible fields are equal: two triggers whose sources are not visible both read source and name `null`, and numbering them per native object would give them equal semantics (G2-23).

Pinned direction, verified in gorge's code (`rules/arrange.go`, `rules/mulligan.go` `handleBottoming`, `effects/zone.go` `libraryOrderPlacement`): in every native answer, list index 0 is the card closest to the library's top. It matches v2 position order, so native lists are built in v2 placement order.

- [ ] **Step 1: Write the failing tests**

`internal/mapping/order_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestTriggerOrderImpliesTheLastPosition(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KTriggerOrder
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	n := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		n++
		if p.Candidates[0].Sem.Fields["purpose"] != "triggers" {
			t.Fatal("purpose")
		}
		return 0
	})
	if n != len(d.Options)-1 || len(commit[0].Choices) != len(d.Options) {
		t.Fatalf("posed %d for %d triggers, commit %v", n, len(d.Options), commit)
	}
}

func TestMulliganBottomPosesAllPicks(t *testing.T) {
	g := untilPendingRules(t, "Burn", 1, "london", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KMulligan && d.Max > 0 && d.Options[0].Kind == "bottom"
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	n := 0
	answerAll(t, tx, func(p *mapping.Pose) int { n++; return 0 })
	if n != d.Max {
		t.Fatalf("posed %d of %d bottom picks", n, d.Max)
	}
}
```

The mulligan-bottom test uses `untilPendingRules` (Task 14's helper) with `"london"`, since the bottoming ask exists only after a mulligan.

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/mapping/ -run 'TriggerOrder|MulliganBottom'`
Expected: FAIL with `unmapped_decision:trigger_order`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/order.go`:

```go
package mapping

import (
	"encoding/json"
	"fmt"
	"slices"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	Register("trigger_order", newTriggerOrder)
	Register("mulligan/bottom", newMulliganBottom)
	Register("hand_move/library", newHandToLibrary)
}

// orderTx places `count` native options one position per decision.
type orderTx struct {
	env      *Env
	d        *decision.Decision
	purpose  string
	items    map[int]protocol.OrderItem
	pool     []int // candidate native options
	count    int
	implied  bool // the last position is implied (items offered == items placed)
	placed   []int
	pose     *Pose
	prefix   []decision.Intent // intents committed before the ordered one (hand_move select)
	build    func(order []int) decision.Intent
	size     uint32
}

func (t *orderTx) Pose() (*Pose, error) {
	pos := len(t.placed)
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Purpose: &t.purpose}, Native: t.d,
		GroupStart: pos == 0, SubstepIndex: uint32(pos), SubstepCount: t.size}
	for _, o := range t.pool {
		if slices.Contains(t.placed, o) {
			continue
		}
		p.Candidates = append(p.Candidates, Cand{Sem: protocol.OrderPick(nil, t.purpose, t.items[o], uint32(pos), uint32(t.count)),
			Op: NativeOp{Op: "list", Option: o, List: "choices", Position: pos}})
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *orderTx) Answer(i int) ([]decision.Intent, bool, error) {
	t.placed = append(t.placed, t.pose.Candidates[i].Op.Option)
	if t.implied && len(t.placed) == t.count-1 {
		for _, o := range t.pool {
			if !slices.Contains(t.placed, o) {
				t.placed = append(t.placed, o)
			}
		}
	}
	if len(t.placed) < t.count {
		return nil, false, nil
	}
	return append(t.prefix, t.build(t.placed)), true, nil
}

func newTriggerOrder(env *Env, d *decision.Decision) (Transaction, error) {
	t := &orderTx{env: env, d: d, purpose: "triggers", items: map[int]protocol.OrderItem{}, count: len(d.Options), implied: true,
		size: uint32(len(d.Options) - 1)}
	instances := map[string]uint32{}
	for _, o := range d.Options {
		src, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil {
			return nil, err
		}
		var name *string
		if src != nil {
			name = src.CardName
		}
		// instance numbers the triggers whose visible fields are equal (two
		// triggers of hidden sources both read source and name null), so
		// the key is those fields, never the native object.
		item := protocol.TriggerItem{Source: src, SourceName: name, EventObjects: []protocol.ObjectRef{}}
		b, _ := json.Marshal(item)
		item.Instance = instances[string(b)]
		instances[string(b)]++
		t.items[o.Index] = protocol.OrderItem{Trigger: &item}
		t.pool = append(t.pool, o.Index)
	}
	t.build = func(order []int) decision.Intent { return Intent(d, order...) }
	return t, nil
}

func newMulliganBottom(env *Env, d *decision.Decision) (Transaction, error) {
	t := &orderTx{env: env, d: d, purpose: "mulligan_bottom", items: map[int]protocol.OrderItem{}, count: d.Max, size: uint32(d.Max)}
	for _, o := range d.Options {
		r, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil || r == nil {
			return nil, fmt.Errorf("%w: mulligan card not visible", ErrUnmapped)
		}
		t.items[o.Index] = protocol.ObjectItem(*r)
		t.pool = append(t.pool, o.Index)
	}
	t.build = func(order []int) decision.Intent { return Intent(d, order...) }
	return t, nil
}

// handToLibrary: Brainstorm. A fixed select_object group picks the cards, then
// an order_pick library_top group places them (last position implied).
type handToLibrary struct {
	sel   Transaction
	order *orderTx
	d     *decision.Decision
	env   *Env
}

func newHandToLibrary(env *Env, d *decision.Decision) (Transaction, error) {
	h := &handToLibrary{d: d, env: env}
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	purp := "other"
	lo, hi := uint32(d.Min), uint32(d.Max)
	// Selecting runs on a private decision copy so the pick does not commit.
	h.sel = NewPick(env, PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: src, Purpose: &purp},
		Sem: func(opt int, sel uint32) (Cand, error) {
			r, err := env.Obs.Ref(d.Player, d.Options[opt].Obj)
			if err != nil || r == nil {
				return Cand{}, fmt.Errorf("%w: hand card not visible", ErrUnmapped)
			}
			return Cand{Sem: protocol.SelectObject(src, purp, protocol.ObjectTarget(*r), sel, lo, hi)}, nil
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishSelection(src, purp, sel) }})
	return h, nil
}

func (h *handToLibrary) Pose() (*Pose, error) {
	if h.order != nil {
		return h.order.Pose()
	}
	return h.sel.Pose()
}

func (h *handToLibrary) Answer(i int) ([]decision.Intent, bool, error) {
	if h.order != nil {
		return h.order.Answer(i)
	}
	commit, done, err := h.sel.Answer(i)
	if err != nil || !done {
		return nil, false, err
	}
	chosen := commit[0].Choices
	if len(chosen) < 2 {
		return commit, true, nil
	}
	o := &orderTx{env: h.env, d: h.d, purpose: "library_top", items: map[int]protocol.OrderItem{}, count: len(chosen),
		implied: true, size: uint32(len(chosen) - 1), pool: chosen}
	for _, c := range chosen {
		r, _ := h.env.Obs.Ref(h.d.Player, h.d.Options[c].Obj)
		o.items[c] = protocol.ObjectItem(*r)
	}
	o.build = func(order []int) decision.Intent { return Intent(h.d, order...) }
	h.order = o
	return nil, false, nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/mapping/ -run 'TriggerOrder|MulliganBottom' -v`
Expected: `--- PASS: TestTriggerOrderImpliesTheLastPosition`, `--- PASS: TestMulliganBottomPosesAllPicks`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: order picks (triggers, mulligan bottom, Brainstorm)"
```

---

### Task 19b: Arrangement

**Files:**
- Create: `internal/mapping/arrange.go`
- Test: `internal/mapping/arrange_test.go`

**Interfaces:**
- Consumes: framework, `Env.OpenLook`, `LookRef`, `KnownEntry`, `SortKnown`, `gamecfg.Game.Probe`; Task 14's test helpers.
- Native ops (read by Task 26's agent): partition candidates are `dest` (Option is the card's native option or -1, List the destination, Position the card index; `top` and `hand` are inside the native Choices). Ordering candidates are `list` (List `choices`, `rest` or `followup:dig_bottom`; Option the card's option in that decision; Position its place in the destination). Explore's partition candidates are `choose` with the destination option's index.
- Produces registered routes:
  - `arrange/bottom`, `arrange/graveyard`, `arrange/exile`, `arrange/hand`: the Section 7.5 arrangement, `2n-1` decisions;
  - `choose/dig`: dig and gorge's follow-up `dig_bottom` as one arrangement with purpose `dig`;
  - `arrange/dig_bottom`: a dig_bottom ask with no take ask before it, one arrangement with forced `bottom` partitions;
  - `choose/explore`: one-card arrangement, destinations `top` or `graveyard`.

Pinned direction, verified in gorge's code (`rules/arrange.go`, `rules/mulligan.go` `handleBottoming`, `effects/zone.go` `libraryOrderPlacement`): in every native answer, list index 0 is the card closest to the library's top. It matches v2 position order, so native lists are built in v2 placement order.

- [ ] **Step 1: Write the failing tests**

`internal/mapping/arrange_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestScryIsTwoNMinusOneAndLandsCardsWhereChosen(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KArrange && d.Restable && len(d.Options) == 2 // Preordain's scry 2
	})
	env := envFor(t, g)
	d := g.E.Pending()
	lib := g.E.G.Zone(state.ZLibrary, d.Player)
	top0, top1 := lib[0], lib[1]
	tx, _ := mapping.Begin(env, d)
	decisions := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		decisions++
		if p.SubstepCount != 3 {
			t.Fatalf("group size %d, want 3", p.SubstepCount)
		}
		if p.Candidates[0].Sem.Kind == "arrange_card" {
			for i, c := range p.Candidates { // send card 0 to the bottom, keep card 1 on top
				if (decisions == 1) == (c.Sem.Fields["destination"] == "bottom") {
					return i
				}
			}
		}
		return 0
	})
	if decisions != 3 {
		t.Fatalf("%d decisions", decisions)
	}
	c, err := g.Probe(commit...)
	if err != nil {
		t.Fatal(err)
	}
	// Preordain draws after its scry, so the card kept on top is now the last
	// card added to the hand, and the other is the library's bottom card.
	hand, newLib := c.G.Zone(state.ZHand, d.Player), c.G.Zone(state.ZLibrary, d.Player)
	if hand[len(hand)-1] != top1 || newLib[len(newLib)-1] != top0 {
		t.Fatalf("drawn %d, library bottom %d, want %d and %d", hand[len(hand)-1], newLib[len(newLib)-1], top1, top0)
	}
}

func TestDigMergesDigAndDigBottomIntoOneArrangement(t *testing.T) {
	g := untilPending(t, "Spy", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "dig"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	var count uint32
	followOps := 0
	commit := answerAll(t, tx, func(p *mapping.Pose) int {
		count = p.SubstepCount
		for i, c := range p.Candidates {
			if c.Sem.Kind == "arrange_card" && c.Sem.Fields["destination"] == "bottom" {
				return i // every card to the bottom, so gorge asks dig_bottom for the order
			}
			if c.Op.Op == "list" && c.Op.List == "followup:dig_bottom" && p.Followups["dig_bottom"] != nil {
				followOps++
			}
		}
		return 0
	})
	if count != 2*5-1 {
		t.Fatalf("Lead the Stampede arrangement size %d, want 9", count)
	}
	if followOps == 0 || len(commit) != 2 {
		t.Fatalf("bottom order not carried by the dig_bottom follow-up: %d ops, commit %v", followOps, commit)
	}
	if _, err := g.Probe(commit...); err != nil {
		t.Fatalf("dig commit rejected: %v", err)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/mapping/ -run 'Scry|Dig'`
Expected: FAIL with `unmapped_decision:arrange/bottom`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/arrange.go`:

```go
package mapping

import (
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var destOrder = []string{"top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1"}

func init() {
	for _, k := range []string{"bottom", "graveyard", "exile", "hand"} {
		Register("arrange/"+k, newScryLike)
	}
	Register("arrange/dig_bottom", newDigBottom)
	Register("choose/dig", newDig)
	Register("choose/explore", newExplore)
}

// arrangeTx is Section 7.5's arrangement: n arrange_card decisions (top card
// first), then n-1 order_pick decisions placing destination by destination.
//
// Native ops, which the Go agent reads through x_gorge_view_v1:
//   - a partition candidate is "dest": Option is the card's native option
//     index (-1 when it has none), List the destination, Position the card
//     index. "top" and "hand" are the destinations inside the native
//     Choices; every other destination is outside them.
//   - an ordering candidate is "list": List names the native answer list
//     ("choices", "rest" or "followup:<key>"), Option is the card's option
//     index in that decision, Position its place within the destination.
type arrangeTx struct {
	env      *Env
	d        *decision.Decision
	purpose  string
	src      *protocol.ObjectRef
	cards    []state.ObjID
	refs     []protocol.ObjectRef
	byID     map[string]int // look id -> card index
	native   []int          // the card's native option index, -1 for none
	dests    [][]string
	legal    func(i int, dst string, chosen []string) bool
	restOnly map[string]bool                  // destinations whose native order is fixed by the engine
	destOp   func(i int, dst string) NativeOp // optional override of the partition op
	listFor  func(i int, dst string) (list string, option int)
	prepare  func() error // optional, runs once before the first ordering pick
	prepared bool
	follow   map[string]*decision.Decision
	chosen   []string
	placed   []int
	known    []protocol.Known
	commit   func() ([]decision.Intent, error)
	pose     *Pose
}

func (t *arrangeTx) n() int { return len(t.cards) }

func cardName(r protocol.ObjectRef) string {
	if r.CardName == nil {
		return ""
	}
	return *r.CardName
}

// look opens the seat's look and mints the look ids and known entries, with
// each card's live distance from the top of the library.
func (t *arrangeTx) look(how string) error {
	t.env.OpenLook(t.d.Player)
	lib := t.env.G.E.G.Zone(state.ZLibrary, t.d.Player)
	t.byID = map[string]int{}
	for i, id := range t.cards {
		r, err := t.env.Obs.LookRef(t.d.Player, id)
		if err != nil {
			return err
		}
		at := slices.Index(lib, id)
		if at < 0 {
			return fmt.Errorf("%w: looked-at card %d is not in the library", ErrUnmapped, id)
		}
		t.refs = append(t.refs, r)
		t.byID[r.ObjectID] = i
		p := uint32(at)
		t.known = append(t.known, observe.KnownEntry(r, how, &p))
	}
	observe.SortKnown(t.known)
	return nil
}

func (t *arrangeTx) nativeOf(cards []int) []int {
	out := make([]int, 0, len(cards))
	for _, i := range cards {
		out = append(out, t.native[i])
	}
	return out
}

func (t *arrangeTx) currentDest() (string, []int) {
	for _, dst := range destOrder {
		var unplaced []int
		for i, c := range t.chosen {
			if c == dst && !slices.Contains(t.placed, i) {
				unplaced = append(unplaced, i)
			}
		}
		if len(unplaced) > 0 {
			return dst, unplaced
		}
	}
	return "", nil
}

// orderedFor lists the card indices sent to dst, in placement order.
func (t *arrangeTx) orderedFor(dst string) []int {
	var out []int
	for _, i := range t.placed {
		if t.chosen[i] == dst {
			out = append(out, i)
		}
	}
	return out
}

func (t *arrangeTx) Pose() (*Pose, error) {
	if t.n() == 0 {
		return nil, ErrDeadEnd
	}
	step := len(t.chosen) + len(t.placed)
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Source: t.src, Purpose: &t.purpose},
		GroupStart: step == 0, SubstepIndex: uint32(step), SubstepCount: uint32(2*t.n() - 1), Known: t.known, Look: true, Native: t.d}
	if len(t.chosen) < t.n() {
		i := len(t.chosen)
		for _, dst := range t.dests[i] {
			if !t.legal(i, dst, t.chosen) {
				continue
			}
			op := NativeOp{Op: "dest", Option: t.native[i], List: dst, Position: i}
			if t.destOp != nil {
				op = t.destOp(i, dst)
			}
			p.Candidates = append(p.Candidates, Cand{Sem: protocol.ArrangeCard(t.src, t.purpose, t.refs[i], uint32(i), uint32(t.n()), dst), Op: op})
		}
	} else {
		if t.prepare != nil && !t.prepared {
			if err := t.prepare(); err != nil {
				return nil, err
			}
			t.prepared = true
		}
		dst, unplaced := t.currentDest()
		if t.restOnly[dst] {
			unplaced = unplaced[:1] // the engine fixes this order: offered order, one candidate per pick
		}
		pos := len(t.orderedFor(dst))
		for _, i := range unplaced {
			list, idx := t.listFor(i, dst)
			// The items are library cards: Finalize orders them by (card_name, object_id).
			p.Candidates = append(p.Candidates, Cand{
				Sem:    protocol.OrderPick(t.src, "arrangement", protocol.ObjectItem(t.refs[i]), uint32(len(t.placed)), uint32(t.n())),
				Op:     NativeOp{Op: "list", Option: idx, List: list, Position: pos},
				Hidden: true, SortName: cardName(t.refs[i]), SortID: t.refs[i].ObjectID})
		}
		p.Followups = t.follow
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *arrangeTx) Answer(k int) ([]decision.Intent, bool, error) {
	c := t.pose.Candidates[k]
	if len(t.chosen) < t.n() {
		t.chosen = append(t.chosen, c.Sem.Fields["destination"].(string))
		if t.n() == 1 {
			t.placed = []int{0}
		}
	} else {
		t.placed = append(t.placed, t.byID[c.Sem.Fields["item"].(protocol.OrderItem).Object.ObjectID])
		if len(t.placed) == t.n()-1 { // only the final pick of the arrangement is implied
			_, last := t.currentDest()
			t.placed = append(t.placed, last...)
		}
	}
	if len(t.placed) < t.n() {
		return nil, false, nil
	}
	ins, err := t.commit()
	return ins, true, err
}

// newScryLike: gorge KArrange (Scry and Surveil). Options are the top N in
// library order; pile A (Choices) stays on top in answer order, pile B goes to
// the options' Kind destination, in Rest order when Restable.
func newScryLike(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	other := d.Options[0].Kind
	purp := map[string]string{"bottom": "scry", "graveyard": "surveil"}[other]
	switch {
	case d.Min == len(d.Options) && d.Max == len(d.Options):
		purp = "look_at_top" // a full rearrange (Ponder): pile B is always empty
	case purp == "":
		purp = "other"
	}
	t := &arrangeTx{env: env, d: d, purpose: purp, src: src, restOnly: map[string]bool{}}
	for _, o := range d.Options {
		t.cards = append(t.cards, o.Obj)
		t.native = append(t.native, o.Index)
		t.dests = append(t.dests, []string{"top", other})
	}
	if !d.Restable {
		t.restOnly[other] = true
	}
	if err := t.look("looked_at"); err != nil {
		return nil, err
	}
	t.legal = func(i int, dst string, chosen []string) bool {
		top := 0
		for _, c := range chosen {
			if c == "top" {
				top++
			}
		}
		rest := t.n() - i - 1
		if dst == "top" {
			return top+1 <= d.Max && top+1+rest >= d.Min
		}
		return top <= d.Max && top+rest >= d.Min
	}
	t.listFor = func(i int, dst string) (string, int) {
		if dst == "top" {
			return "choices", t.native[i]
		}
		return "rest", t.native[i]
	}
	t.commit = func() ([]decision.Intent, error) {
		in := Intent(d, t.nativeOf(t.orderedFor("top"))...)
		if d.Restable {
			in.Rest = t.nativeOf(t.orderedFor(other))
		}
		return []decision.Intent{in}, nil
	}
	return t, nil
}

// digBottom returns the dig_bottom ask pending on c for seat, if any.
func digBottom(c *rules.Engine, seat state.PlayerID) *decision.Decision {
	n := c.Pending()
	if n == nil || c.G.Over || n.Player != seat || n.Kind != decision.KArrange || len(n.Options) == 0 || n.Options[0].Kind != "dig_bottom" {
		return nil
	}
	return n
}

// newDig: gorge asks "dig" (which eligible cards go to the hand) and then,
// when two or more cards remain, "dig_bottom" (their order on the bottom).
// v2 sees one arrangement over the whole DigNum window. The dig_bottom ask is
// found by lookahead once the partition is known and carried as the
// follow-up "dig_bottom".
func newDig(env *Env, d *decision.Decision) (Transaction, error) {
	sa := d.ResumeSA
	if sa == nil {
		return nil, fmt.Errorf("%w:dig_shape", ErrUnmapped)
	}
	param := func(k string) string { return strings.TrimSpace(sa.Params[k]) }
	dest, dest2, pos2 := param("DestinationZone"), param("DestinationZone2"), param("LibraryPosition2")
	if dest == "" {
		dest = "Hand" // gorge's defaults (effects/cardflow.go)
	}
	if dest2 == "" {
		dest2, pos2 = "Library", "-1"
	}
	if !strings.EqualFold(dest, "Hand") || !strings.EqualFold(dest2, "Library") || pos2 != "-1" || d.MaxSum > 0 ||
		strings.EqualFold(param("SkipReorder"), "True") || strings.EqualFold(param("FromBottom"), "True") {
		return nil, fmt.Errorf("%w:dig_shape", ErrUnmapped)
	}
	n, err := strconv.Atoi(param("DigNum"))
	if err != nil || n <= 0 {
		return nil, fmt.Errorf("%w:dig_num", ErrUnmapped)
	}
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	lib := env.G.E.G.Zone(state.ZLibrary, d.Player)
	window := slices.Clone(lib[:min(n, len(lib))])
	eligible := map[state.ObjID]int{}
	for _, o := range d.Options {
		if o.Player != d.Player || !slices.Contains(window, o.Obj) {
			return nil, fmt.Errorf("%w:dig_option_outside_window", ErrUnmapped)
		}
		eligible[o.Obj] = o.Index
	}
	how := "looked_at"
	if strings.EqualFold(param("Reveal"), "True") {
		how = "revealed"
	}
	t := &arrangeTx{env: env, d: d, purpose: "dig", src: src, cards: window, restOnly: map[string]bool{}}
	for _, id := range window {
		if idx, ok := eligible[id]; ok {
			t.native = append(t.native, idx)
			t.dests = append(t.dests, []string{"hand", "bottom"})
		} else {
			t.native = append(t.native, -1)
			t.dests = append(t.dests, []string{"bottom"})
		}
	}
	if err := t.look(how); err != nil {
		return nil, err
	}
	eligibleAfter := func(i int) int {
		k := 0
		for _, idx := range t.native[i+1:] {
			if idx >= 0 {
				k++
			}
		}
		return k
	}
	t.legal = func(i int, dst string, chosen []string) bool {
		hand := 0
		for _, c := range chosen {
			if c == "hand" {
				hand++
			}
		}
		if dst == "hand" {
			return hand+1 <= d.Max
		}
		return hand+eligibleAfter(i) >= d.Min
	}
	sentTo := func(dst string) (cards []int) {
		for i, c := range t.chosen {
			if c == dst {
				cards = append(cards, i)
			}
		}
		return cards
	}
	followIdx := map[state.ObjID]int{}
	t.prepare = func() error {
		if len(sentTo("bottom")) < 2 {
			return nil // gorge moves a lone remainder without asking
		}
		c, err := env.G.Probe(Intent(d, t.nativeOf(sentTo("hand"))...))
		if err != nil {
			return err
		}
		nb := digBottom(c, d.Player)
		if nb == nil {
			return fmt.Errorf("%w:dig_bottom_missing", ErrUnmapped)
		}
		t.follow = map[string]*decision.Decision{"dig_bottom": nb}
		for _, o := range nb.Options {
			followIdx[o.Obj] = o.Index
		}
		return nil
	}
	t.listFor = func(i int, dst string) (string, int) {
		if dst == "hand" {
			return "choices", t.native[i]
		}
		return "followup:dig_bottom", followIdx[t.cards[i]]
	}
	t.commit = func() ([]decision.Intent, error) {
		dig := Intent(d, t.nativeOf(t.orderedFor("hand"))...)
		bottom := t.orderedFor("bottom")
		if len(bottom) < 2 {
			return []decision.Intent{dig}, nil
		}
		c, err := env.G.Probe(dig)
		if err != nil {
			return nil, err
		}
		nb := digBottom(c, d.Player)
		if nb == nil {
			return nil, fmt.Errorf("%w:dig_bottom_missing", ErrUnmapped)
		}
		at := map[state.ObjID]int{}
		for _, o := range nb.Options {
			at[o.Obj] = o.Index
		}
		order := make([]int, 0, len(bottom))
		for _, i := range bottom {
			idx, ok := at[t.cards[i]]
			if !ok {
				return nil, fmt.Errorf("%w:dig_bottom_card_missing", ErrUnmapped)
			}
			order = append(order, idx)
		}
		return []decision.Intent{dig, {Seq: nb.Seq, Player: nb.Player, Choices: order}}, nil
	}
	return t, nil
}

// newDigBottom: a dig_bottom ask with no take ask before it (gorge took the
// eligible cards silently, or none were eligible). Every offered card goes to
// the bottom, so each partition pick is forced and only the order is chosen.
func newDigBottom(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	t := &arrangeTx{env: env, d: d, purpose: "dig", src: src, restOnly: map[string]bool{}}
	for _, o := range d.Options {
		t.cards = append(t.cards, o.Obj)
		t.native = append(t.native, o.Index)
		t.dests = append(t.dests, []string{"bottom"})
	}
	if err := t.look("looked_at"); err != nil {
		return nil, err
	}
	t.legal = func(int, string, []string) bool { return true }
	t.destOp = func(i int, dst string) NativeOp { return NativeOp{Op: "dest", Option: -1, List: dst, Position: i} }
	t.listFor = func(i int, _ string) (string, int) { return "choices", t.native[i] }
	t.commit = func() ([]decision.Intent, error) {
		return []decision.Intent{Intent(d, t.nativeOf(t.orderedFor("bottom"))...)}, nil
	}
	return t, nil
}

// newExplore: "Put the revealed card back on top or into your graveyard?"
func newExplore(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := ResolveSource(env, d)
	if err != nil {
		return nil, err
	}
	lib := env.G.E.G.Zone(state.ZLibrary, d.Player)
	if len(lib) == 0 {
		return nil, fmt.Errorf("%w:explore_empty_library", ErrUnmapped)
	}
	kindIdx := map[string]int{}
	var dests []string
	for _, o := range d.Options {
		kindIdx[o.Kind] = o.Index
	}
	for _, dst := range []string{"top", "graveyard"} {
		if _, ok := kindIdx[dst]; ok {
			dests = append(dests, dst)
		}
	}
	t := &arrangeTx{env: env, d: d, purpose: "other", src: src, cards: slices.Clone(lib[:1]), native: []int{-1},
		dests: [][]string{dests}, restOnly: map[string]bool{}}
	if err := t.look("revealed"); err != nil {
		return nil, err
	}
	t.legal = func(int, string, []string) bool { return true }
	t.destOp = func(_ int, dst string) NativeOp { return NativeOp{Op: "choose", Option: kindIdx[dst]} }
	t.commit = func() ([]decision.Intent, error) {
		return []decision.Intent{Intent(d, kindIdx[t.chosen[0]])}, nil
	}
	return t, nil
}
```

In `commit`, native lists are in v2 placement order: `top` in Choices order, the pile-B destination in Rest order, and dig's bottom block in dig_bottom answer order. Each puts index 0 closest to the top, which `TestScryIsTwoNMinusOneAndLandsCardsWhereChosen` checks against real library order.

Three details are easy to get wrong:
- Ordering candidates reference library cards, so they are `Hidden` and Finalize orders them by `(card_name, object_id)` (Section 7.1). `Answer` therefore finds the card by its look id, never by candidate index.
- gorge's Dig parameters have defaults (`DestinationZone` Hand, `DestinationZone2` Library with `LibraryPosition2` -1, `effects/cardflow.go:1307-1342`). Lead the Stampede sets neither, so the shape check applies the defaults before comparing.
- gorge asks dig_bottom on its own when the take was silent (at most ChangeNum eligible cards, `effects/cardflow.go:1752`). `arrange/dig_bottom` covers that case with forced `bottom` partitions.

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/mapping/ -run 'Scry|Dig' -v`
Expected: `--- PASS: TestScryIsTwoNMinusOneAndLandsCardsWhereChosen`, `--- PASS: TestDigMergesDigAndDigBottomIntoOneArrangement`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: fixed-size arrangements (scry, dig, explore)"
```

---

### Task 20: Simple choices

**Files:**
- Create: `internal/mapping/simple.go`
- Test: `internal/mapping/simple_test.go`

**Interfaces:**
- Consumes: framework.
- Produces registered routes:
  - `mulligan/keep` (`mulligan`, which updates `Env.Obs.Mulls`);
  - `trigger_optional/optional` (`choose_boolean` `optional_trigger`), `trigger_optional/madness` (`optional_cast` `madness`, whose `card` is the exiled card itself: `ResolveSource` would answer the madness trigger's stack entry);
  - `choose/yesno` (`choose_boolean`: ResumeKind `search_confirm` to `may_ability`, `search_mayshuffle` to `other`, `copy_optional` and `repeat_optional` to `may_ability`, else `other`);
  - `replacement/madness` (`choose_boolean` `optional_replacement`, true means exile), `replacement/order` (`choose_replacement`);
  - `choose/color` (`choose_color` `effect`), `choose/x` (`choose_number` `x_value`), `choose/number` (`choose_number` `amount`);
  - `choose/type` (`choose_name` `card_type`), `choose/name` (`choose_name` `card_name`, filtered to `Env.Domain`).
- Uses `SingleChoice`, `singleTx` and `choice` from Task 13's `single.go`.

- [ ] **Step 1: Write the failing test**

`internal/mapping/simple_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestSimpleChoiceKinds(t *testing.T) {
	cases := []struct {
		deck, want string
		pred       func(*decision.Decision, *rules.Engine) bool
	}{
		{"Burn", "optional_cast", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KTriggerOptional && d.ResumeKind == "madness"
		}},
		{"Wildfire", "choose_boolean", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KTriggerOptional && d.ResumeKind == "optional"
		}},
		{"CawGates", "choose_color", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "color"
		}},
		{"Spy", "choose_name", func(d *decision.Decision, e *rules.Engine) bool {
			return d.Kind == decision.KChoose && len(d.Options) > 0 && d.Options[0].Kind == "type"
		}},
	}
	for _, c := range cases {
		g := untilPending(t, c.deck, 1, c.pred)
		env := envFor(t, g)
		tx, err := mapping.Begin(env, g.E.Pending())
		if err != nil {
			t.Fatalf("%s: %v", c.want, err)
		}
		p, err := tx.Pose()
		if err != nil || p.Candidates[0].Sem.Kind != c.want {
			t.Fatalf("%s: got %+v %v", c.want, p, err)
		}
		if err := p.Candidates[0].Sem.Check(); err != nil {
			t.Fatalf("%s: %v", c.want, err)
		}
		if c.want == "optional_cast" { // the card in exile, not the madness trigger on the stack
			if card := p.Candidates[0].Sem.Fields["card"].(protocol.ObjectRef); card.Zone != "exile" {
				t.Fatalf("madness card is in %s", card.Zone)
			}
		}
	}
}

func TestMulliganKeepCountsMulligans(t *testing.T) {
	g := untilPendingRules(t, "Burn", 1, "london", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KMulligan && d.Options[0].Kind != "bottom"
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	for i, c := range p.Candidates {
		if c.Sem.Fields["keep"] == false {
			tx.Answer(i)
		}
	}
	if env.Obs.Mulls[d.Player] != 1 {
		t.Fatalf("mulligans taken %d", env.Obs.Mulls[d.Player])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'SimpleChoiceKinds|MulliganKeep'`
Expected: FAIL with `unmapped_decision:trigger_optional/madness`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/simple.go`:

```go
package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var colors = map[string]string{"white": "white", "blue": "blue", "black": "black", "red": "red", "green": "green"}

var boolPurpose = map[string]string{"search_confirm": "may_ability", "copy_optional": "may_ability",
	"repeat_optional": "may_ability", "search_mayshuffle": "other"}

func init() {
	Register("mulligan/keep", func(env *Env, d *decision.Decision) (Transaction, error) {
		hand := uint32(len(env.G.E.G.Zone(state.ZHand, d.Player)))
		taken := env.Obs.Mulls[d.Player]
		tx, err := SingleChoice(env, d, choice(nil, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.Mulligan(hand, taken, o.Kind == "keep"), true, nil
		})
		if err != nil {
			return nil, err
		}
		st := tx.(*singleTx)
		st.after = func(opt int) {
			if d.Options[opt].Kind == "mulligan" {
				env.Obs.Mulls[d.Player]++
			}
		}
		return st, nil
	})
	Register("trigger_optional/optional", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "optional_trigger"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseBoolean(src, "optional_trigger", o.Kind == "yes"), true, nil
		})
	})
	Register("trigger_optional/madness", func(env *Env, d *decision.Decision) (Transaction, error) {
		// optional_cast.card is the exiled card itself. ResolveSource would
		// answer the madness trigger's stack entry, whose source it is.
		r, err := env.Obs.Ref(d.Player, d.Source)
		if err != nil {
			return nil, err
		}
		if r == nil {
			return nil, ErrUnresolvableSource
		}
		card := *r
		return SingleChoice(env, d, choice(&card, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.OptionalCast(card, "madness", o.Kind == "yes"), true, nil
		})
	})
	Register("choose/yesno", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		p := boolPurpose[d.ResumeKind]
		if p == "" {
			p = "other"
		}
		return SingleChoice(env, d, choice(src, p), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseBoolean(src, p, o.Kind == "yes"), true, nil
		})
	})
	Register("replacement/madness", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "optional_replacement"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseBoolean(src, "optional_replacement", o.Kind == "madness_exile"), true, nil
		})
	})
	Register("replacement/order", func(env *Env, d *decision.Decision) (Transaction, error) {
		affected := protocol.PlayerTarget(observe.Seat(d.Player))
		if d.Source != 0 {
			if r, err := env.Obs.Ref(d.Player, d.Source); err != nil {
				return nil, err
			} else if r != nil {
				affected = protocol.ObjectTarget(*r)
			}
		}
		event := "other"
		switch {
		case strings.Contains(d.Prompt, "modify damage"):
			event = "damage"
		case strings.Contains(d.Prompt, "counter"):
			event = "counters"
		case strings.Contains(d.Prompt, "enters with"):
			event = "enter_battlefield"
		}
		n := uint32(len(d.Options))
		return SingleChoice(env, d, choice(nil, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
			rs, err := env.Obs.Ref(d.Player, o.Obj)
			return protocol.ChooseReplacement(affected, event, rs, uint32(o.Index), n), err == nil, err
		})
	})
	Register("choose/color", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "effect"), func(o decision.Option) (protocol.Semantic, bool, error) {
			c, ok := colors[strings.ToLower(strings.TrimSpace(o.Label))]
			if !ok {
				return protocol.Semantic{}, false, fmt.Errorf("%w:color/%q", ErrUnmapped, o.Label)
			}
			return protocol.ChooseColor(src, "effect", c), true, nil
		})
	})
	number := func(purp string) Builder {
		return func(env *Env, d *decision.Decision) (Transaction, error) {
			src, err := ResolveSource(env, d)
			if err != nil {
				return nil, err
			}
			lo, hi := int32(d.Options[0].Amount), int32(d.Options[0].Amount)
			for _, o := range d.Options {
				lo, hi = min(lo, int32(o.Amount)), max(hi, int32(o.Amount))
			}
			return SingleChoice(env, d, choice(src, purp), func(o decision.Option) (protocol.Semantic, bool, error) {
				return protocol.ChooseNumber(src, purp, int32(o.Amount), lo, hi), true, nil
			})
		}
	}
	Register("choose/x", number("x_value"))
	Register("choose/number", number("amount"))
	Register("choose/type", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "card_type"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseName(src, "card_type", observe.Normalize(o.Label)), true, nil
		})
	})
	Register("choose/name", func(env *Env, d *decision.Decision) (Transaction, error) {
		src, err := ResolveSource(env, d)
		if err != nil {
			return nil, err
		}
		return SingleChoice(env, d, choice(src, "card_name"), func(o decision.Option) (protocol.Semantic, bool, error) {
			return protocol.ChooseName(src, "card_name", o.Label), env.Domain[o.Label], nil
		})
	})
}
```

For `choose/x`, gorge's `Option.Amount` omits zero (JSON omitempty), and the Go value is 0 for "X = 0", which is correct in-process.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'SimpleChoiceKinds|MulliganKeep' -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: mulligan, booleans, madness, replacement order, colour, numbers, names"
```

---

### Task 21: Resolution-time payments and engine-internal answers

**Files:**
- Create: `internal/mapping/payment.go`
- Test: `internal/mapping/payment_test.go`

**Interfaces:**
- Consumes: framework, `ExpandActivate` (Task 15).
- Produces:
  - registered routes `modes/unless`, `choose/mana_window`, `choose/trigger_cost`;
  - the internal answer `choose/pay_pip` (`RegisterInternal`, Task 13's registry). v2.0 has no kind for allocating floating mana to a hybrid pip, since `pay_mana` is reserved, so `choose/pay_pip` is answered with gorge's first offered option. This is the engine's payment procedure, not a player decision, and is recorded in the engine notes (Task 29) and as controller decision 3.

Rules:
- **Unless costs** (gorge `KModes` pay/decline, ResumeKind `unless_pay`) become `optional_cost`.
  - `cost` is `unless_payment` when `ResumeSA.API` is `Counter`, `copy` when the API names a copy, else `other`.
  - `pay: true` is offered only when a clone shows paying opens no `unless_mana` window, meaning the floating pool already covers the cost (controller decision 2). No activation candidates.
- **Trigger costs** (window first): gorge's `choose/mana_window` (activate options plus done) becomes one decision with `context.purpose` `mana_payment`:
  - `optional_cost pay:false`, whose op answers done and then decline (the pay/decline ask is the follow-up keyed by done's option index);
  - one `activate_mana_ability` per window activation, folded like Task 15;
  - `optional_cost pay:true`, only when a clone shows that done leads to a pay/decline ask offering pay.
  - Each activation commits and the session re-poses the next window as a new decision.
  - A window whose done does not lead to a trigger-cost ask fails closed: a cast payment window (gorge poses one when a cost grows after announcement; absent in bot play, reachable by other agents) or `unless_mana`. The engine notes list it as a halt cause (G2-28).
- **Trigger costs without a window** (`choose/trigger_cost`) become `optional_cost` pay:true/false as offered.

- [ ] **Step 1: Write the failing test**

`internal/mapping/payment_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
)

func TestSpellbombWindowIsOneManaPaymentDecision(t *testing.T) {
	g := untilPending(t, "Wildfire", 1, func(d *decision.Decision, e *rules.Engine) bool {
		k := map[string]bool{}
		for _, o := range d.Options {
			k[o.Kind] = true
		}
		return d.Kind == decision.KChoose && k["activate"] && k["done"]
	})
	env := envFor(t, g)
	tx, err := mapping.Begin(env, g.E.Pending())
	if err != nil {
		t.Fatal(err)
	}
	p, err := tx.Pose()
	if err != nil {
		t.Fatal(err)
	}
	if p.Context.Purpose == nil || *p.Context.Purpose != "mana_payment" {
		t.Fatalf("purpose %v", p.Context.Purpose)
	}
	kinds := map[string]int{}
	decline := -1
	for i, c := range p.Candidates {
		kinds[c.Sem.Kind]++
		if c.Sem.Kind == "optional_cost" && c.Sem.Fields["pay"] == false {
			decline = i
		}
	}
	if kinds["activate_mana_ability"] == 0 || decline < 0 {
		t.Fatalf("kinds %v decline %d", kinds, decline)
	}
	commit, done, err := tx.Answer(decline)
	if err != nil || !done || len(commit) != 2 {
		t.Fatalf("decline commits done then decline: %v %v %v", commit, done, err)
	}
}

func TestUnlessPayIsOfferedOnlyWhenThePoolCovers(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KModes && d.ResumeKind == "unless_pay"
	})
	env := envFor(t, g)
	d := g.E.Pending()
	tx, _ := mapping.Begin(env, d)
	p, _ := tx.Pose()
	for _, c := range p.Candidates {
		if c.Sem.Kind != "optional_cost" {
			t.Fatalf("kind %s", c.Sem.Kind)
		}
		if c.Sem.Fields["pay"] == true {
			commit := []decision.Intent{mapping.Intent(d, c.Op.Option)}
			cl, err := g.Probe(commit...)
			if err != nil {
				t.Fatal(err)
			}
			if n := cl.Pending(); n != nil && n.ResumeKind == "unless_mana" && n.Player == d.Player {
				t.Fatal("pay:true offered but paying opens a mana window")
			}
		}
	}
}

func TestHybridPipIsAnsweredInternally(t *testing.T) {
	d := &decision.Decision{Kind: decision.KChoose, Min: 1, Max: 1, Options: []decision.Option{{Index: 0, Kind: "pay_R"}, {Index: 1, Kind: "pay_G"}}}
	in, ok, err := mapping.Internal(nil, d)
	if !ok || err != nil || len(in.Choices) != 1 || in.Choices[0] != 0 {
		t.Fatalf("internal answer %v %v %v", in, ok, err)
	}
	if _, ok, _ := mapping.Internal(nil, &decision.Decision{Kind: decision.KPriority}); ok {
		t.Fatal("priority answered internally")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'Spellbomb|UnlessPay|HybridPip'`
Expected: FAIL with `engine_contract_failure:unmapped_decision:choose/mana_window`.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/payment.go`:

```go
package mapping

import (
	"fmt"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func init() {
	Register("modes/unless", newUnless)
	Register("choose/mana_window", newManaWindow)
	Register("choose/trigger_cost", newTriggerCost)
	RegisterInternal("choose/pay_pip", payPip)
}

// payPip allocates floating mana to a hybrid pip with gorge's first offered
// option: v2.0 has no kind for it (pay_mana is reserved), so this is the
// engine's payment procedure, recorded in the engine notes (controller
// decision 3).
func payPip(_ *Env, d *decision.Decision) (decision.Intent, error) {
	return Intent(d, d.Options[0].Index), nil
}

func unlessCost(d *decision.Decision) string {
	if d.ResumeSA == nil {
		return "other"
	}
	switch api := d.ResumeSA.API; {
	case api == "Counter":
		return "unless_payment"
	case strings.Contains(api, "Copy"):
		return "copy"
	}
	return "other"
}

func opensManaWindow(env *Env, d *decision.Decision, opt int) bool {
	c, err := env.G.Probe(Intent(d, opt))
	if err != nil {
		return true
	}
	n := c.Pending()
	return n != nil && n.Player == d.Player && n.ResumeKind == "unless_mana"
}

func newUnless(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	cost := unlessCost(d)
	return SingleChoice(env, d, choice(&src, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
		pay := o.Mode == decision.ModeUnlessPay
		if pay && opensManaWindow(env, d, o.Index) {
			return protocol.Semantic{}, false, nil
		}
		return protocol.OptionalCost(src, cost, pay), true, nil
	})
}

func newTriggerCost(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	return SingleChoice(env, d, choice(&src, ""), func(o decision.Option) (protocol.Semantic, bool, error) {
		return protocol.OptionalCost(src, "other", o.Kind == "trigger_cost_pay"), true, nil
	})
}

type windowTx struct {
	d    *decision.Decision
	pose *Pose
}

func (w *windowTx) Pose() (*Pose, error) { return w.pose, nil }

func (w *windowTx) Answer(i int) ([]decision.Intent, bool, error) {
	op := w.pose.Candidates[i].Op
	ins := []decision.Intent{Intent(w.d, op.Option)}
	for _, f := range op.Followup {
		ins = append(ins, decision.Intent{Choices: []int{f}})
	}
	return ins, true, nil
}

func newManaWindow(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	done := -1
	for _, o := range d.Options {
		if o.Kind == "done" {
			done = o.Index
		}
	}
	c, err := env.G.Probe(Intent(d, done))
	if err != nil {
		return nil, err
	}
	ask := c.Pending()
	if ask == nil || ask.Player != d.Player || Route(ask) != "choose/trigger_cost" {
		// A cast payment window (a cost that grew after announcement) or an
		// unless_mana window: not mapped in v2.0, a listed halt cause.
		return nil, fmt.Errorf("%w:mana_window_not_a_trigger_cost", ErrUnmapped)
	}
	purp := "mana_payment"
	// The done ask is keyed by done's option index, like every folded
	// follow-up, so the agent finds it from the op alone.
	p := &Pose{Seat: d.Player, Context: protocol.Context{Kind: "choice", Source: &src, Purpose: &purp},
		GroupStart: true, SubstepCount: 1, Native: d, Followups: map[string]*decision.Decision{fmt.Sprint(done): ask}}
	for _, ao := range ask.Options {
		pay := ao.Kind == "trigger_cost_pay"
		p.Candidates = append(p.Candidates, Cand{Sem: protocol.OptionalCost(src, "other", pay),
			Op: NativeOp{Op: "choose", Option: done, Followup: []int{ao.Index}}})
	}
	for _, o := range d.Options {
		if o.Kind != "activate" {
			continue
		}
		s, err := env.Obs.Ref(d.Player, o.Obj)
		if err != nil || s == nil {
			return nil, fmt.Errorf("%w: mana source not visible", ErrUnmapped)
		}
		cs, folds, err := ExpandActivate(env, d, o, *s)
		if err != nil {
			return nil, err
		}
		p.Candidates = append(p.Candidates, cs...)
		for k, v := range folds {
			p.Followups[k] = v
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	return &windowTx{d: d, pose: p}, nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -v`
Expected: every mapping test PASS, including `TestSpellbombWindowIsOneManaPaymentDecision`, `TestUnlessPayIsOfferedOnlyWhenThePoolCovers` and `TestHybridPipIsAnsweredInternally`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: unless and trigger-cost payments, internal hybrid pip allocation"
```

---

### Task 22: Session: game loop, counters, caps, terminals, halts

**Files:**
- Create: `internal/session/session.go`, `internal/session/terminal.go`
- Test: `internal/session/session_test.go`

**Interfaces:**
- Consumes: `gamecfg`, `identity`, `observe`, `mapping` (Begin, `Internal(env, d)`, error values), `protocol`.
- Produces:
  - `type session.Extender interface{ Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error) }`;
  - `type session.Config struct{ Reg *cards.Registry; Provenance protocol.Provenance; Ext Extender }`;
  - `type session.Game` with `func session.Start(cfg Config, gameID string, req *protocol.ResetReq, sec *secrets.Game, decks [2][]*cards.Card) (*Game, error)`;
  - `func (*Game) Pending() (*protocol.DecisionResponse, *protocol.TerminalResponse)`;
  - `func (*Game) Step(req *protocol.StepReq) *protocol.Error` (checks `game_already_terminal`, `expected_step_mismatch`, `candidate_id_out_of_range`, `semantic_echo_mismatch` in spec order);
  - `func session.EchoEqual(echo json.RawMessage, s protocol.Semantic) bool`;
  - `func (*Game) EngineHead() string` (parity tests).

Rules:
- `step` counts every answered decision; `seat_step` and `group_id` are per seat.
- A group completes when its last substep is answered; `decision_count` counts completed groups.
- Caps are checked only when a group would start. A group starts only if `decision_count < max_decisions` and `step + substep_count <= max_steps`, so truncation never splits a group (Section 8).
- Halts are `halted` with reason `engine_contract_failure:<cause>`, the cause a fixed token, never engine text. Engine panics, including `*rules.LivelockError`, are recovered.
- `priority_seat` is the acting seat for priority decisions and for choices inside that seat's own priority action; else null.
- A priority answer records the action (`mapping.ActionContext`, with `Since` the engine's next object id), which source resolution reads while the seat announces it (Task 13).
- Decisions the engine answers itself (`mapping.Internal`: combat damage in engine order, hybrid pips) are submitted without posing.
- A folded follow-up intent (Seq 0) is submitted only when the pending decision is the one the lookahead saw: the same kind and player, and options equal in kind, object, mana symbol and ability. Its pose keys name it (`followKeys`). Anything else halts `followup_mismatch` (G2-16).

- [ ] **Step 1: Write the failing test**

`internal/session/session_test.go`:

```go
package session_test

import (
	"bytes"
	"encoding/json"
	"maps"
	"slices"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
)

func start(t *testing.T, deck string, maxSteps uint64) *session.Game {
	reg := testcorpus.Registry(t)
	d, _ := catalog.ByID(deck)
	cs, err := catalog.Resolve(reg, d)
	if err != nil {
		t.Fatal(err)
	}
	seat := "p0"
	req := &protocol.ResetReq{GameID: "g-t", Format: "pauper-bo1", MaxDecisions: 100000, MaxSteps: maxSteps,
		Rules: protocol.Rules{Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &seat, Names: catalog.PoolNames()}}
	s := make([]byte, 32)
	g, err := session.Start(session.Config{Reg: reg}, "g-t", req, secrets.NewGame(s), [2][]*cards.Card{cs, cs})
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func echo(t *testing.T, s protocol.Semantic) json.RawMessage {
	b, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func profile() validate.Profile {
	kinds := map[string]bool{}
	for k := range protocol.KindFields {
		kinds[k] = true
	}
	return validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}}
}

func TestFirstCandidateGameEndsWithConsistentCounts(t *testing.T) {
	g := start(t, "Burn", 4000)
	streams := [2]*validate.Stream{validate.NewStream(profile()), validate.NewStream(profile())}
	steps := uint64(0)
	for {
		dec, term := g.Pending()
		if term != nil {
			if term.StepCount != steps || term.DecisionCount > steps || term.Reason == "" {
				t.Fatalf("terminal %+v after %d steps", term, steps)
			}
			if term.Classification == "halted" {
				t.Fatalf("halted: %s", term.Reason)
			}
			return
		}
		sd := dec.SeatDecision
		seat := 0
		if sd.ActingSeat == "p1" {
			seat = 1
		}
		if err := streams[seat].Check(sd); err != nil {
			t.Fatalf("step %d: %v", steps, err)
		}
		if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: 0, Echo: echo(t, sd.Candidates[0].Semantic)}); perr != nil {
			t.Fatalf("step %d: %v", steps, perr)
		}
		steps++
	}
}

// reversedJSON writes a decoded JSON value with every object's keys in
// reverse sorted order, a layout no encoder produces on its own.
func reversedJSON(v any) []byte {
	var b bytes.Buffer
	switch x := v.(type) {
	case map[string]any:
		keys := slices.Sorted(maps.Keys(x))
		slices.Reverse(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			kb, _ := json.Marshal(k)
			b.Write(kb)
			b.WriteByte(':')
			b.Write(reversedJSON(x[k]))
		}
		b.WriteByte('}')
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			b.Write(reversedJSON(e))
		}
		b.WriteByte(']')
	default:
		eb, _ := json.Marshal(x)
		b.Write(eb)
	}
	return b.Bytes()
}

func decoded(t *testing.T, raw []byte) map[string]any {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var m map[string]any
	if err := d.Decode(&m); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestEchoComparesParsedFieldsNotBytes(t *testing.T) {
	g := start(t, "Burn", 4000)
	// Pass until a candidate carries a nested object reference (a play_land
	// or cast_spell source).
	var dec *protocol.DecisionResponse
	id := -1
	for n := 0; id < 0; n++ {
		d, term := g.Pending()
		if term != nil || n > 200 {
			t.Fatal("no candidate with a nested object reference")
		}
		for i, c := range d.SeatDecision.Candidates {
			if _, ok := c.Semantic.Fields["source"].(protocol.ObjectRef); ok {
				dec, id = d, i
				break
			}
		}
		if id < 0 {
			if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: d.Step, CandidateID: 0, Echo: echo(t, d.SeatDecision.Candidates[0].Semantic)}); perr != nil {
				t.Fatal(perr)
			}
		}
	}
	c := dec.SeatDecision.Candidates[id].Semantic
	raw := echo(t, c)
	reordered := reversedJSON(decoded(t, raw))
	if bytes.Equal(reordered, raw) {
		t.Fatal("the reversed layout equals the engine's bytes")
	}
	if !session.EchoEqual(reordered, c) {
		t.Fatalf("echo with reversed keys at every level rejected: %s", reordered)
	}
	extra := decoded(t, raw)
	extra["x_extra"] = 1
	changed := decoded(t, raw)
	changed["source"].(map[string]any)["zone"] = "graveyard"
	for what, m := range map[string]map[string]any{"an extra field": extra, "a changed nested field": changed} {
		b := reversedJSON(m)
		if session.EchoEqual(b, c) {
			t.Fatalf("echo with %s accepted", what)
		}
		if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(id), Echo: b}); perr == nil || perr.Code != protocol.CodeSemanticEchoMismatch {
			t.Fatalf("echo with %s: got %v", what, perr)
		}
	}
	if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(id), Echo: reordered}); perr != nil {
		t.Fatalf("reordered echo refused by Step: %v", perr)
	}
}

// last answers every decision with its last candidate: it takes mulligans
// until the rule forces a keep, then bottoms several cards, an order_pick
// group of two or more substeps (Section 8).
func last(sd protocol.SeatDecision) int { return len(sd.Candidates) - 1 }

func TestCapNeverSplitsAGroup(t *testing.T) {
	g := start(t, "Rally", 4000)
	var groupStep uint64
	for found := false; !found; {
		dec, term := g.Pending()
		if term != nil {
			t.Fatal("the game ended before a multi-substep group")
		}
		sd := dec.SeatDecision
		if sd.Group.SubstepIndex == 0 && sd.Group.SubstepCount >= 2 {
			groupStep, found = dec.Step, true
			break
		}
		k := last(sd)
		if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(k), Echo: echo(t, sd.Candidates[k].Semantic)}); perr != nil {
			t.Fatal(perr)
		}
	}
	h := start(t, "Rally", groupStep+1) // room for one more decision, not for the group
	for {
		dec, term := h.Pending()
		if term != nil {
			if term.Outcome != "truncated" || term.StepCount != groupStep {
				t.Fatalf("terminal %+v, want truncated at %d", term, groupStep)
			}
			return
		}
		k := last(dec.SeatDecision)
		if perr := h.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(k), Echo: echo(t, dec.SeatDecision.Candidates[k].Semantic)}); perr != nil {
			t.Fatal(perr)
		}
	}
}

func TestTerminalGameRejectsSteps(t *testing.T) {
	g := start(t, "Burn", 0)
	if _, term := g.Pending(); term == nil || term.Outcome != "truncated" {
		t.Fatalf("max_steps 0 must truncate at reset, got %+v", term)
	}
	if perr := g.Step(&protocol.StepReq{GameID: "g-t"}); perr == nil || perr.Code != protocol.CodeGameAlreadyTerminal {
		t.Fatalf("got %v", perr)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/session/`
Expected: FAIL with `undefined: session.Start`.

- [ ] **Step 3: Write minimal implementation**

`internal/session/session.go`:

```go
// Package session runs one v2 game over a gorge engine.
package session

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"strconv"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
)

type Extender interface {
	Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error)
}

type Config struct {
	Reg        *cards.Registry
	Provenance protocol.Provenance
	Ext        Extender
}

type Game struct {
	ID                     string
	cfg                    Config
	g                      *gamecfg.Game
	env                    *mapping.Env
	tx                     mapping.Transaction
	native                 *decision.Decision
	pose                   *mapping.Pose
	resp                   *protocol.DecisionResponse
	term                   *protocol.TerminalResponse
	step, decisions        uint64
	seatStep, groupID      [2]uint64
	nativeCount            [2]uint64
	maxSteps, maxDecisions uint64
}

func Start(cfg Config, gameID string, req *protocol.ResetReq, sec *secrets.Game, decks [2][]*cards.Card) (*Game, error) {
	start := state.PlayerID(0)
	if req.Rules.StartingSeat != nil && *req.Rules.StartingSeat == "p1" {
		start = 1
	}
	g, err := gamecfg.New(cfg.Reg, sec, decks, gamecfg.Rules{Mulligan: req.Rules.Mulligan, StartingSeat: start})
	if err != nil {
		return nil, err
	}
	tr := identity.New(g.E, sec)
	dom := map[string]bool{}
	for _, n := range req.Rules.Names {
		dom[n] = true
	}
	s := &Game{ID: gameID, cfg: cfg, g: g, maxSteps: req.MaxSteps, maxDecisions: req.MaxDecisions,
		env: &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Domain: dom, Slots: map[string]uint32{}}}
	s.advance()
	return s, nil
}

func (s *Game) Pending() (*protocol.DecisionResponse, *protocol.TerminalResponse) {
	if s.term != nil {
		return nil, s.term
	}
	return s.resp, nil
}

func (s *Game) EngineHead() string { return s.g.E.L.Head() }

func (s *Game) recoverPanic() {
	if r := recover(); r != nil {
		fmt.Fprintf(os.Stderr, "gorge engine panic: %v\n", r)
		if _, ok := r.(*rules.LivelockError); ok {
			s.halt("livelock")
		} else {
			s.halt("panic")
		}
	}
}

func (s *Game) advance() {
	defer s.recoverPanic()
	for s.term == nil {
		if s.tx == nil {
			e := s.g.E
			if e.G.Over {
				s.natural()
				return
			}
			d := e.Pending()
			if d == nil {
				s.halt("no_pending_decision")
				return
			}
			if in, ok, err := mapping.Internal(s.env, d); ok || err != nil {
				if err == nil {
					err = s.submit(in, nil)
				}
				if err != nil {
					s.halt(cause(err, "submit_rejected"))
					return
				}
				continue
			}
			if d.Kind == decision.KPriority {
				s.env.Action, s.env.Slots = nil, map[string]uint32{}
			}
			tx, err := mapping.Begin(s.env, d)
			if err != nil {
				s.halt(cause(err, "unmapped_decision"))
				return
			}
			s.tx, s.native = tx, d
			s.nativeCount[d.Player]++
		}
		p, err := s.tx.Pose()
		if err != nil {
			s.halt(cause(err, "dead_end"))
			return
		}
		if p.GroupStart {
			if s.decisions >= s.maxDecisions {
				s.truncate("max_decisions")
				return
			}
			if s.step+uint64(p.SubstepCount) > s.maxSteps {
				s.truncate("max_steps")
				return
			}
		}
		if err := s.present(p); err != nil {
			s.halt(cause(err, "projection"))
		}
		return
	}
}

func (s *Game) present(p *mapping.Pose) error {
	var holder *state.PlayerID
	if p.Context.Kind == "priority" || (s.env.Action != nil && s.env.Action.Seat == p.Seat) {
		h := p.Seat
		holder = &h
	}
	known := append([]protocol.Known(nil), p.Known...)
	observe.SortKnown(known)
	obs, err := s.env.Obs.Observation(p.Seat, observe.State{PriorityHolder: holder, Known: known})
	if err != nil {
		return err
	}
	sd := protocol.SeatDecision{ActingSeat: observe.Seat(p.Seat), SeatStep: s.seatStep[p.Seat],
		Group:   protocol.Group{GroupID: s.groupID[p.Seat], SubstepIndex: p.SubstepIndex, SubstepCount: p.SubstepCount},
		Context: p.Context, Observation: obs, Extensions: map[string]json.RawMessage{}}
	for i, c := range p.Candidates {
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: c.Sem})
	}
	if s.cfg.Ext != nil {
		ext, err := s.cfg.Ext.Extend(s.env, p, s.nativeCount[p.Seat])
		if err != nil {
			return err
		}
		sd.Extensions = ext
	}
	s.pose = p
	s.resp = &protocol.DecisionResponse{ResponseType: "decision", Protocol: protocol.Name, GameID: s.ID, Step: s.step,
		SeatDecision: sd, Provenance: s.cfg.Provenance}
	return nil
}

func EchoEqual(echo json.RawMessage, sem protocol.Semantic) bool {
	decode := func(b []byte) (any, bool) {
		d := json.NewDecoder(bytes.NewReader(b))
		d.UseNumber()
		var v any
		return v, d.Decode(&v) == nil
	}
	a, ok := decode(echo)
	raw, _ := json.Marshal(sem)
	b, _ := decode(raw)
	return ok && reflect.DeepEqual(a, b)
}

func (s *Game) Step(req *protocol.StepReq) *protocol.Error {
	switch {
	case s.term != nil:
		return protocol.Errf(protocol.CodeGameAlreadyTerminal, "the game has ended")
	case req.ExpectedStep != s.step:
		return protocol.Errf(protocol.CodeExpectedStepMismatch, fmt.Sprintf("pending step is %d", s.step))
	case req.CandidateID >= uint64(len(s.pose.Candidates)):
		return protocol.Errf(protocol.CodeCandidateIDOutOfRange, "no such candidate")
	case !EchoEqual(req.Echo, s.pose.Candidates[req.CandidateID].Sem):
		return protocol.Errf(protocol.CodeSemanticEchoMismatch, "semantic_echo differs from the candidate")
	}
	s.answer(int(req.CandidateID))
	return nil
}

func (s *Game) actionObject(op mapping.NativeOp) state.ObjID {
	idx := op.Option
	if op.Op == "cast" && len(op.Covers) > 0 {
		idx = op.Covers[0]
	}
	if idx >= 0 && idx < len(s.native.Options) {
		return s.native.Options[idx].Obj
	}
	return 0
}

func (s *Game) answer(i int) {
	defer s.recoverPanic()
	p := s.pose
	seat := p.Seat
	op := p.Candidates[i].Op
	if p.Context.Kind == "priority" {
		if obj := s.actionObject(op); obj != 0 {
			s.env.Action = &mapping.ActionContext{Seat: seat, Obj: obj, Since: s.g.E.G.NextID}
		}
	}
	commit, done, err := s.tx.Answer(i)
	s.step++
	s.seatStep[seat]++
	if p.SubstepIndex+1 == p.SubstepCount {
		s.groupID[seat]++
		s.decisions++
	}
	if err != nil {
		s.halt(cause(err, "dead_end"))
		return
	}
	keys := followKeys(op)
	for k, in := range commit {
		var want *decision.Decision
		if k > 0 && in.Seq == 0 && k-1 < len(keys) {
			want = p.Followups[keys[k-1]]
		}
		if err := s.submit(in, want); err != nil {
			s.halt(cause(err, "submit_rejected"))
			return
		}
	}
	if done {
		s.tx = nil
		s.env.CloseLooks()
	}
	s.advance()
}

var errFollowup = errors.New("engine_contract_failure:followup_mismatch")

// followKeys names the pose follow-ups a candidate's folded intents answer,
// in commit order: "<option>", then "<option>/<first follow-up option>"
// (Tasks 15 and 21 key them so).
func followKeys(op mapping.NativeOp) []string {
	keys := make([]string, 0, len(op.Followup))
	key := strconv.Itoa(op.Option)
	for _, f := range op.Followup {
		keys = append(keys, key)
		key += "/" + strconv.Itoa(f)
	}
	return keys
}

// sameAsk reports whether the pending decision is the one the lookahead saw:
// the same kind, player and options (kind, object, mana symbol, ability).
func sameAsk(d, want *decision.Decision) bool {
	if d.Kind != want.Kind || d.Player != want.Player || len(d.Options) != len(want.Options) {
		return false
	}
	for i, o := range d.Options {
		w := want.Options[i]
		if o.Kind != w.Kind || o.Obj != w.Obj || o.ManaSymbol != w.ManaSymbol || o.Ability != w.Ability {
			return false
		}
	}
	return true
}

// submit sends one intent. A folded follow-up (Seq 0) is filled from the
// pending decision only after that decision is shown to be the lookahead's
// (want); otherwise the game halts followup_mismatch.
func (s *Game) submit(in decision.Intent, want *decision.Decision) error {
	d := s.g.E.Pending()
	if d == nil {
		return errFollowup
	}
	if in.Seq == 0 {
		if want == nil || !sameAsk(d, want) {
			return errFollowup
		}
		in.Seq, in.Player = d.Seq, d.Player
	}
	if in.Seq != d.Seq || in.Player != d.Player {
		return errFollowup
	}
	if err := s.g.Submit(in); err != nil {
		fmt.Fprintf(os.Stderr, "gorge rejected intent %+v: %v\n", in, err)
		return err
	}
	return s.env.IDs.Sync(s.g.E)
}
```

`internal/session/terminal.go`:

```go
package session

import (
	"errors"
	"fmt"
	"os"

	"github.com/adams-shaun/gorge/events"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

var causes = []struct {
	err  error
	name string
}{
	{mapping.ErrUnmapped, "unmapped_decision"}, {mapping.ErrDeadEnd, "dead_end"},
	{mapping.ErrCandidateLimit, "candidate_limit"}, {mapping.ErrDuplicate, "duplicate_candidates"},
	{mapping.ErrUnresolvableSource, "unresolvable_source"}, {gamecfg.ErrUnplannedRandomness, "unplanned_randomness"},
	{identity.ErrIDCollision, "id_collision"}, {identity.ErrShadowDiverged, "identity_shadow_diverged"},
	{errFollowup, "followup_mismatch"},
}

func cause(err error, fallback string) string {
	fmt.Fprintf(os.Stderr, "gorge adapter: %v\n", err) // detail stays on stderr, never in reason
	for _, c := range causes {
		if errors.Is(err, c.err) {
			return c.name
		}
	}
	return fallback
}

func (s *Game) terminal(outcome, class, reason string, winner *string) {
	s.term = &protocol.TerminalResponse{ResponseType: "terminal", Protocol: protocol.Name, GameID: s.ID,
		Outcome: outcome, Classification: class, Winner: winner, Reason: reason,
		StepCount: s.step, DecisionCount: s.decisions, Provenance: s.cfg.Provenance}
	s.tx, s.resp = nil, nil
}

func (s *Game) halt(c string) { s.terminal("halted", "halted", "engine_contract_failure:"+c, nil) }

func (s *Game) truncate(cap string) { s.terminal("truncated", "truncated", cap, nil) }

func (s *Game) natural() {
	e := s.g.E
	if e.G.Draw {
		s.terminal("draw", "natural", "draw", nil)
		return
	}
	w := observe.Seat(e.G.Winner)
	s.terminal(w+"_win", "natural", lossReason(e.L.Events, 1-e.G.Winner), &w)
}

func lossReason(evs []events.Event, loser state.PlayerID) string {
	seat := observe.Seat(loser)
	for i := len(evs) - 1; i >= 0; i-- {
		if ev := evs[i]; ev.Kind == events.PlayerLost && ev.Player == loser {
			switch ev.Text {
			case "life total is 0 or less":
				return seat + "_life_zero"
			case "drew from an empty library":
				return seat + "_decked"
			case "ten or more poison counters":
				return seat + "_poison"
			}
			break
		}
	}
	return seat + "_lost"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/session/ -v`
Expected: all four tests PASS, including `TestFirstCandidateGameEndsWithConsistentCounts` with zero validator violations and no `halted` terminal.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/session && git commit -m "gorge adapter: v2 game session with per-seat counters, group-safe caps and fail-closed halts"
```

---

### Task 23: Environment server and binary

**Files:**
- Create: `internal/server/server.go`, `internal/server/identity.go`
- Create: `cmd/spellbench-gorge-env/main.go`
- Test: `internal/server/server_test.go`

**Interfaces:**
- Consumes: `protocol.Decode`, `session`, `catalog`, `secrets`, `xview.New` (Task 24), `observe.Flags`, `gorgepin`.
- Produces:
  - `type server.Server` with `func server.New(reg *cards.Registry, sourceRevision *string) *Server` and `func (*Server) Handle(line []byte) []byte` (one response line without the newline);
  - `func server.Serve(r io.Reader, w io.Writer, s *Server) error`;
  - `var server.DecisionKinds []string` (the 24 kinds; `distribute` is not one, since combat damage follows the declared `engine_order` default);
  - the `spellbench-gorge-env` binary (`-corpus`, `-source-revision`).

Retransmission (Section 4.1, G2-21): the engine caches every response since the last accepted reset, with its request's SHA-256, by request id.
- An identical retransmission of any cached request, the latest or an older one of the same game, returns its cached bytes without side effects.
- A cached id with different bytes returns `request_id_reuse_mismatch`.
- Each accepted reset clears the cache, so it holds one game's traffic at most. An id from an earlier game is no longer recognized; a host never reuses one, since ids are unique per process. This is recorded in the engine notes.

Parse failures are never cached.

Validation order:
- **Reset:** `game_already_active`, reused `game_id` (`malformed_request`), `unsupported_format`, per-seat deck checks (`unsupported_deck`, then `deck_id_mismatch`), rule checks (`unsupported_rule`, and `malformed_request` when `domain_id` does not hash its names or a name repeats).
- **Step:** `step_before_reset`, `game_id_mismatch`, then the session's order.

- [ ] **Step 1: Write the failing test**

`internal/server/server_test.go`:

```go
package server_test

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func resp(t *testing.T, b []byte) map[string]any {
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("%s: %v", b, err)
	}
	return m
}

func code(t *testing.T, b []byte) string {
	m := resp(t, b)
	if m["response_type"] != "error" {
		return ""
	}
	return m["error"].(map[string]any)["code"].(string)
}

func reset(id, gameID, deck, mutate string) []byte {
	d, _ := catalog.ByID(deck)
	names, _ := json.Marshal(catalog.PoolNames())
	dom, _ := wire.DomainID(catalog.PoolNames())
	line := fmt.Sprintf(`{"request_type":"reset","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":%q,"catalog_id":%q}},{"seat":"p1","deck":{"deck_id":%q,"catalog_id":%q}}],"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":%q,"names":%s},"extensions":["x_gorge_view_v1"],"probe":false},"game_secret":"%s","max_decisions":10000,"max_steps":100000}`,
		id, gameID, d.DeckID(), deck, d.DeckID(), deck, dom, names, strings.Repeat("ab", 32))
	if mutate != "" {
		parts := strings.SplitN(mutate, "=>", 2)
		line = strings.Replace(line, parts[0], parts[1], 1)
	}
	return []byte(line)
}

func TestHelloDeclaresTheProfile(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	m := resp(t, s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":3}`)))
	if m["protocol_minor"].(float64) != 0 || len(m["decision_kinds"].([]any)) != 24 || len(m["catalog"].([]any)) != 5 ||
		len(m["observation"].(map[string]any)) != 13 || m["rewind"] != false ||
		m["engine_defaults"].(map[string]any)["combat_damage_assignment"] != "engine_order" {
		t.Fatalf("hello_ok %v", m)
	}
	if slices.Contains(server.DecisionKinds, "distribute") {
		t.Fatal("distribute declared, but combat damage follows engine_order")
	}
}

func TestResetErrors(t *testing.T) {
	cases := map[string]string{
		`"format":"pauper-bo1"=>"format":"modern-bo1"`:                          "unsupported_format",
		`"catalog_id":"Burn"}}]=>"catalog_id":"Terror"}}]`:                      "unsupported_deck",
		`"starting_player":"host_assigned","starting_seat":"p0"=>"starting_player":"toss_winner_chooses","starting_seat":null`: "unsupported_rule",
		`"extensions":["x_gorge_view_v1"]=>"extensions":["x_other"]`:            "unsupported_rule",
		`"probe":false=>"probe":true`:                                           "unsupported_rule",
		`"deck_id":"sha256:=>"deck_id":"sha256:0`:                               "deck_id_mismatch",
	}
	for mutate, want := range cases {
		s := server.New(testcorpus.Registry(t), nil)
		if got := code(t, s.Handle(reset("r-1", "g-1", "Burn", mutate))); got != want {
			t.Errorf("%s: got %q, want %q", mutate, got, want)
		}
	}
	s := server.New(testcorpus.Registry(t), nil)
	if got := code(t, s.Handle(reset("r-1", "g-1", "Burn", ""))); got != "" {
		t.Fatalf("valid reset: %s", got)
	}
	if got := code(t, s.Handle(reset("r-2", "g-2", "Burn", ""))); got != "game_already_active" {
		t.Fatalf("second reset: %s", got)
	}
}

func TestStepErrorOrder(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	step := func(id, game string, exp, cand int, echo string) string {
		return code(t, s.Handle([]byte(fmt.Sprintf(`{"request_type":"step","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"expected_step":%d,"selection":{"candidate_id":%d,"semantic_echo":%s}}`, id, game, exp, cand, echo))))
	}
	if got := step("s-0", "g-1", 0, 0, `{"kind":"pass"}`); got != "step_before_reset" {
		t.Fatalf("got %s", got)
	}
	first := resp(t, s.Handle(reset("r-1", "g-1", "Burn", "")))
	cands := first["seat_decision"].(map[string]any)["candidates"].([]any)
	sem, _ := json.Marshal(cands[0].(map[string]any)["semantic"])
	if got := step("s-1", "g-9", 0, 0, string(sem)); got != "game_id_mismatch" {
		t.Fatalf("got %s", got)
	}
	if got := step("s-2", "g-1", 5, 0, string(sem)); got != "expected_step_mismatch" {
		t.Fatalf("got %s", got)
	}
	if got := step("s-3", "g-1", 0, 4095, string(sem)); got != "candidate_id_out_of_range" {
		t.Fatalf("got %s", got)
	}
	if got := step("s-4", "g-1", 0, 0, `{"kind":"nonsense"}`); got != "semantic_echo_mismatch" {
		t.Fatalf("got %s", got)
	}
}

func TestRetransmissionIsIdempotentAndReuseFails(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	line := reset("r-1", "g-1", "Burn", "")
	a := s.Handle(line)
	b := s.Handle(line)
	if string(a) != string(b) {
		t.Fatal("retransmitted reset returned different bytes")
	}
	if got := code(t, s.Handle(reset("r-1", "g-1", "Spy", ""))); got != "request_id_reuse_mismatch" {
		t.Fatalf("reuse with different bytes: %s", got)
	}
	hello := `{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-9","protocol_minor":0}`
	h := s.Handle([]byte(hello))
	// Section 4.1: an identical retransmission of an older request of this
	// game returns its cached response, without side effects.
	if got := s.Handle(line); string(got) != string(a) {
		t.Fatalf("older identical retransmission: %s", got)
	}
	if got := s.Handle([]byte(hello)); string(got) != string(h) {
		t.Fatal("retransmitted hello returned different bytes")
	}
	if got := code(t, s.Handle([]byte(strings.Replace(hello, `"protocol_minor":0`, `"protocol_minor":1`, 1)))); got != "request_id_reuse_mismatch" {
		t.Fatalf("older id with different bytes: %s", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/server/`
Expected: FAIL with `undefined: server.New`.

- [ ] **Step 3: Write minimal implementation**

`internal/server/identity.go`:

```go
package server

import (
	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

const AdapterVersion = "0.1.0"

// DecisionKinds are the 24 kinds the engine emits. distribute is not one:
// combat damage follows the declared engine_order default (Section 7.6).
var DecisionKinds = []string{"pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability",
	"special_action", "choose_target", "finish_target_selection", "choose_cost_target", "choose_spell_mode",
	"choose_color", "choose_number", "choose_boolean", "choose_name", "select_object", "finish_selection",
	"optional_cost", "optional_cast", "mulligan", "order_pick", "arrange_card", "choose_replacement",
	"declare_attack", "declare_block"}

func engineIdentity(sourceRevision *string) protocol.Engine {
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.DeckID())
	}
	catalogID, err := wire.DomainID(ids) // five distinct deck ids: never refused
	if err != nil {
		panic("catalog deck ids repeat: " + err.Error())
	}
	return protocol.Engine{Name: "gorge", Version: "gorge-" + gorgepin.GorgeCommit[:12] + "/spellbench-adapter-" + AdapterVersion,
		SourceRevision:   sourceRevision,
		RulesSnapshotID:  "gorge/" + gorgepin.GorgeCommit[:12] + "/ir-" + cards.CompilerFingerprint,
		CardPoolIdentity: "forge-" + gorgepin.ForgeRef[:12] + "/corpus-" + gorgepin.CorpusDigest[:16] + "/catalog-" + catalogID[7:23]}
}

func provenance(e protocol.Engine) protocol.Provenance {
	return protocol.Provenance{EngineName: e.Name, EngineVersion: e.Version, RulesSnapshotID: e.RulesSnapshotID, CardPoolIdentity: e.CardPoolIdentity}
}

// engineOrder is the declared combat damage default (Section 7.6): gorge
// assigns combat damage in engine order (Task 16).
var engineOrder = "engine_order"

func helloOK(id string, e protocol.Engine, flags map[string]bool) protocol.HelloOK {
	var cat []protocol.CatalogDeck
	for _, d := range catalog.Decks() {
		cd := protocol.CatalogDeck{CatalogID: d.CatalogID, Name: d.Name}
		for _, r := range d.Rows {
			cd.Decklist = append(cd.Decklist, protocol.DeckRow{Name: r.Name, Count: r.Count})
		}
		cat = append(cat, cd)
	}
	return protocol.HelloOK{ResponseType: "hello_ok", Protocol: protocol.Name, RequestID: id, ProtocolMinor: 0, Engine: e,
		Formats: []string{"pauper-bo1"}, DeckSources: []string{"catalog"}, Catalog: cat,
		RulesSupported: map[string][]string{"mulligan": {"london", "none"}, "starting_player": {"host_assigned"}},
		Observation:    flags, DecisionKinds: DecisionKinds,
		EngineDefaults: map[string]*string{"trigger_order": nil, "replacement_order": nil, "combat_damage_assignment": &engineOrder, "mana_payment": nil},
		Rewind:         false, Fairness: map[string]bool{"noninterference_probe": false},
		Extensions:     []protocol.Extension{{Name: "x_gorge_view_v1", NativeIDs: false}}}
}
```

`internal/server/server.go`:

```go
// Package server implements the Spellbench v2 environment role for gorge.
package server

import (
	"crypto/sha256"
	"errors"
	"io"
	"slices"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// cached is one answered request: the SHA-256 of its line and the response.
type cached struct {
	sum  [32]byte
	resp []byte
}

type Server struct {
	reg     *cards.Registry
	engine  protocol.Engine
	game    *session.Game
	gameIDs map[string]bool
	// cache holds every response since the last accepted reset, by request
	// id (Section 4.1): an identical retransmission of any of them returns
	// its bytes, a changed payload is request_id_reuse_mismatch. Clearing it
	// at each accepted reset bounds it by one game's traffic.
	cache map[string]cached
}

func New(reg *cards.Registry, sourceRevision *string) *Server {
	return &Server{reg: reg, engine: engineIdentity(sourceRevision), gameIDs: map[string]bool{}, cache: map[string]cached{}}
}

func marshal(v any) []byte {
	b, _ := wire.Canonical(v) // any valid layout is allowed; canonical keeps goldens stable
	return b
}

func errResp(id string, e *protocol.Error) []byte {
	return marshal(protocol.ErrorResponse{ResponseType: "error", Protocol: protocol.Name, RequestID: id,
		Error: protocol.ErrorBody{Code: e.Code, Message: e.Message}})
}

func (s *Server) Handle(line []byte) []byte {
	req, perr := protocol.Decode(line)
	if perr != nil {
		return errResp(req.ID, perr)
	}
	sum := sha256.Sum256(line)
	if c, ok := s.cache[req.ID]; ok {
		if c.sum == sum {
			return c.resp
		}
		return errResp(req.ID, protocol.Errf(protocol.CodeRequestIDReuseMismatch, "request_id reused with a different payload"))
	}
	prev := s.game
	out := s.dispatch(req)
	if s.game != prev { // an accepted reset starts a new game
		clear(s.cache)
	}
	s.cache[req.ID] = cached{sum: sum, resp: out}
	return out
}

func (s *Server) dispatch(req protocol.Request) []byte {
	switch req.Type {
	case "hello":
		return marshal(helloOK(req.ID, s.engine, observe.Flags))
	case "reset":
		return s.reset(req)
	case "step":
		return s.stepReq(req)
	case "validate_deck":
		v := req.ValidateDeck
		if v.Format != "pauper-bo1" {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedFormat, v.Format))
		}
		if _, ok := catalog.ByID(v.Deck.CatalogID); v.Deck.IsDecklist || !ok {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "only the engine catalog decks are playable"))
		}
		return marshal(protocol.DeckOK{ResponseType: "deck_ok", Protocol: protocol.Name, RequestID: req.ID})
	default: // probe_resample: this engine has no probe (Section 9.7)
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRequest, req.Type+" is not implemented"))
	}
}

func (s *Server) respond(id string, g *session.Game) []byte {
	dec, term := g.Pending()
	if term != nil {
		t := *term
		t.RequestID = id
		return marshal(t)
	}
	d := *dec
	d.RequestID = id
	return marshal(d)
}

func (s *Server) reset(req protocol.Request) []byte {
	r := req.Reset
	switch {
	case s.game != nil && !terminal(s.game):
		return errResp(req.ID, protocol.Errf(protocol.CodeGameAlreadyActive, "a game is active"))
	case s.gameIDs[r.GameID]:
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "game_id reused"))
	case r.Format != "pauper-bo1":
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedFormat, r.Format))
	}
	var decks [2][]*cards.Card
	for i, spec := range r.Decks {
		d, ok := catalog.ByID(spec.CatalogID)
		if spec.IsDecklist || !ok {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "only the engine catalog decks are playable"))
		}
		if spec.DeckID != d.DeckID() {
			return errResp(req.ID, protocol.Errf(protocol.CodeDeckIDMismatch, "deck_id does not match "+d.CatalogID))
		}
		cs, err := catalog.Resolve(s.reg, d)
		if err != nil {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, err.Error()))
		}
		decks[i] = cs
	}
	switch {
	case r.Rules.StartingPlayer != "host_assigned":
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "starting_player"))
	case r.Rules.Probe:
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "probe"))
	}
	if dom, err := wire.DomainID(r.Rules.Names); err != nil || dom != r.Rules.DomainID {
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "card_name_domain.domain_id does not hash its distinct names"))
	}
	for _, x := range r.Rules.Extensions {
		if x != "x_gorge_view_v1" {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "extension "+x))
		}
	}
	sec, err := secrets.ParseGame(r.GameSecret)
	if err != nil {
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, err.Error()))
	}
	cfg := session.Config{Reg: s.reg, Provenance: provenance(s.engine)}
	if slices.Contains(r.Rules.Extensions, "x_gorge_view_v1") {
		cfg.Ext = xview.New()
	}
	g, err := session.Start(cfg, r.GameID, r, sec, decks)
	if err != nil {
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "engine could not start: "+err.Error()))
	}
	s.game = g
	s.gameIDs[r.GameID] = true
	return s.respond(req.ID, g)
}

func terminal(g *session.Game) bool { _, t := g.Pending(); return t != nil }

func (s *Server) stepReq(req protocol.Request) []byte {
	switch {
	case s.game == nil:
		return errResp(req.ID, protocol.Errf(protocol.CodeStepBeforeReset, "no game"))
	case req.Step.GameID != s.game.ID:
		return errResp(req.ID, protocol.Errf(protocol.CodeGameIDMismatch, "another game is active"))
	}
	if perr := s.game.Step(req.Step); perr != nil {
		return errResp(req.ID, perr)
	}
	return s.respond(req.ID, s.game)
}

// Serve runs the stdio loop until stdin closes.
func Serve(r io.Reader, w io.Writer, s *Server) error {
	in := wire.NewReader(r)
	for {
		line, err := in.ReadLine()
		switch {
		case errors.Is(err, io.EOF):
			return nil
		case errors.Is(err, wire.ErrLineTooLong):
			if _, err := w.Write(append(errResp("", protocol.Errf(protocol.CodeMalformedJSON, "line exceeds 8 MiB")), '\n')); err != nil {
				return err
			}
			continue
		case err != nil:
			return err
		}
		if _, err := w.Write(append(s.Handle(line), '\n')); err != nil {
			return err
		}
	}
}
```

`cmd/spellbench-gorge-env/main.go`:

```go
// Command spellbench-gorge-env serves the Spellbench v2 environment role over stdio.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
)

func main() {
	corpus := flag.String("corpus", os.Getenv("GORGE_CARDS"), "compiled Forge corpus directory (never shipped)")
	rev := flag.String("source-revision", "", "adapter source revision reported in hello_ok")
	flag.Parse()
	reg, err := gorgepin.OpenRegistry(*corpus)
	if err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-env:", err)
		os.Exit(2)
	}
	if err := catalog.Preflight(reg); err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-env:", err)
		os.Exit(2)
	}
	var sr *string
	if *rev != "" {
		sr = rev
	}
	out := bufio.NewWriter(os.Stdout)
	w := &flushWriter{out}
	if err := server.Serve(os.Stdin, w, server.New(reg, sr)); err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-env:", err)
		os.Exit(1)
	}
}

type flushWriter struct{ w *bufio.Writer }

func (f *flushWriter) Write(p []byte) (int, error) {
	n, err := f.w.Write(p)
	if err == nil {
		err = f.w.Flush()
	}
	return n, err
}
```

- [ ] **Step 4: Run tests and a stdio smoke**

Run: `go test ./internal/server/ -v`
Expected: all four tests PASS.

Run: `go build -o bin/ ./cmd/spellbench-gorge-env && echo '{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}' | bin/spellbench-gorge-env | head -c 120` (Git Bash finds the `.exe` on Windows)
Expected: a line starting `{"catalog":[{"catalog_id":"Wildfire"` (canonical key order), with `"response_type":"hello_ok"` later in the same line.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/server engines/gorge/cmd/spellbench-gorge-env && git commit -m "gorge adapter: v2 environment server and stdio binary"
```

---

### Task 24: x_gorge_view_v1 payload and audit

**Files:**
- Create: `internal/xview/xview.go`, `internal/xview/rekey.go`
- Test: `internal/xview/xview_test.go`, `internal/xview/key_test.go`

**Interfaces:**
- Consumes: `mapping.Env`, `mapping.Pose`, `mapping.NativeOp`, `view.Project`, `view.RoundOf`, `identity.Tracker`, `observe.Visible`.
- Produces:
  - `type xview.Payload struct{ Version int; NativeIndex uint64; View view.View; Decision decision.Decision; Facts Facts; Followups map[string]decision.Decision; Ops []mapping.NativeOp }` (JSON keys `version`, `native_index`, `view`, `decision`, `policy_facts`, `followups`, `ops`);
  - `type xview.Facts`, `type xview.OptionFacts` and `type xview.ProducesFacts` (a card view's `ManaProduction.Indeterminate` and `Reflected`, which are json `"-"` and read by gorge's bot when it taps mana: G2-27);
  - `type xview.Follow struct{ Key string; Perm []int }`: the Extender keeps, per seat, its last payload's renumbering of the native decision and of each folded follow-up (by native key), for Task 28a's audit only;
  - `type xview.Extender`, implementing `session.Extender`, with `func xview.New() *Extender` (per game: per-seat id tables);
  - `func (*Extender) Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error)`.

Audit rules (Section 14 with `native_ids: false`):
- **Ids:** every gorge object id in the payload is replaced by a per-seat integer. The integer is assigned in the order v2 ids first appear in that seat's stream, which the seat can compute itself, so it carries nothing hidden and is fresh wherever the v2 id is.
- **No global counters:** `Decision.Seq` is replaced by `native_index`, the seat's own count of native decisions.
- **No digests:** payment actions and fallbacks are dropped.
- **No hidden order:** options referencing hidden-zone cards are reordered by `(card_name, v2 id)` and renumbered, in the native decision and in every follow-up. Follow-up keys and every op are translated with the matching permutation.
- **Pending triggers** whose source is hidden, absent or 0 are dropped, as in the observation.
- **Only seen objects get ids** (G2-2): an object the seat sees, or a hidden card this pose's own look shows (its native and follow-up options). Every other reference (a stack ability's source shuffled into a library, as Lembas's is; an absent object; 0) becomes 0, the payload's analogue of v2's `null`.
- **No native ids in names** (G2-3): gorge writes object ids into option groups (`"blocker:65"`, `"payment:12"`). Each decision's groups are relabelled `g0`, `g1`, ... in first-appearance order, equal groups kept equal, and `GroupLimits` keys follow.
- **Deterministic numbering** (G2-20): follow-ups are visited in sorted key order, so integers are assigned the same way on every rerun.

- [ ] **Step 1: Write the failing test**

`internal/xview/xview_test.go`:

```go
package xview_test

import (
	"encoding/json"
	"regexp"
	"slices"
	"strconv"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// payloadAt plays bot games (seeds 1 to 20) until pred holds, then builds
// the pose's payload.
func payloadAt(t *testing.T, deck string, pred func(*decision.Decision, *rules.Engine) bool) (xview.Payload, *mapping.Pose) {
	pl, p, _ := payloadAndGame(t, deck, pred)
	return pl, p
}

func payloadAndGame(t *testing.T, deck string, pred func(*decision.Decision, *rules.Engine) bool) (xview.Payload, *mapping.Pose, *rules.Engine) {
	reg := testcorpus.Registry(t)
	for seed := byte(1); seed <= 20; seed++ {
		g := testgame.New(t, reg, deck, deck, seed, "none")
		tr := identity.New(g.E, g.Secret)
		if !testgame.RunUntil(t, g, testgame.Bots(uint64(seed)), func(e *rules.Engine) bool {
			if err := tr.Sync(e); err != nil {
				t.Fatal(err)
			}
			d := e.Pending()
			return d != nil && pred(d, e)
		}, 30000) {
			continue
		}
		env := &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}, Slots: map[string]uint32{}}
		tx, err := mapping.Begin(env, g.E.Pending())
		if err != nil {
			t.Fatal(err)
		}
		p, err := tx.Pose()
		if err != nil {
			t.Fatal(err)
		}
		ext, err := xview.New().Extend(env, p, 7)
		if err != nil {
			t.Fatal(err)
		}
		raw := ext["x_gorge_view_v1"]
		if err := wire.CheckStrictAny(raw); err != nil {
			t.Fatalf("payload is not strict JSON: %v", err)
		}
		var pl xview.Payload
		if err := json.Unmarshal(raw, &pl); err != nil {
			t.Fatal(err)
		}
		return pl, p, g.E
	}
	t.Fatalf("no %s game reached the decision", deck)
	return xview.Payload{}, nil, nil
}

func TestPayloadHasNoGlobalCountersOrDigests(t *testing.T) {
	pl, p := payloadAt(t, "Burn", func(d *decision.Decision, e *rules.Engine) bool { return d.Kind == decision.KPriority })
	if pl.Decision.Seq != 7 || pl.NativeIndex != 7 || len(pl.Decision.PaymentActions) != 0 {
		t.Fatalf("seq %d native %d payments %d", pl.Decision.Seq, pl.NativeIndex, len(pl.Decision.PaymentActions))
	}
	if len(pl.Ops) != len(p.Candidates) {
		t.Fatalf("%d ops for %d candidates", len(pl.Ops), len(p.Candidates))
	}
}

func TestSearchOptionsAreSortedAndIDsAreSmall(t *testing.T) {
	pl, _ := payloadAt(t, "Wildfire", func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KChoose && len(d.Options) > 1 && d.Options[0].Kind == "search"
	})
	for i := 1; i < len(pl.Decision.Options); i++ {
		if pl.Decision.Options[i-1].Label > pl.Decision.Options[i].Label {
			t.Fatalf("search options not in name order: %q before %q", pl.Decision.Options[i-1].Label, pl.Decision.Options[i].Label)
		}
		if pl.Decision.Options[i].Index != i {
			t.Fatalf("option %d has index %d", i, pl.Decision.Options[i].Index)
		}
	}
	for _, pv := range pl.View.Players {
		for _, cv := range pv.Battlefield {
			if cv.ID == 0 || cv.ID > 500 {
				t.Fatalf("rekeyed id %d is not a small per-seat integer", cv.ID)
			}
		}
	}
}

// Lembas's gain-life ability stays on the stack after its dies trigger
// shuffles Lembas into the library: the ability's source is hidden, so the
// payload names it 0 instead of failing the game (G2-2).
func TestHiddenStackSourceIsZero(t *testing.T) {
	var ability state.ObjID
	pl, _, e := payloadAndGame(t, "Wildfire", func(d *decision.Decision, e *rules.Engine) bool {
		for _, id := range e.G.Stack {
			if o := e.G.Obj(id); o.Ability != nil && e.G.Obj(o.Source) != nil && e.G.Obj(o.Source).Zone == state.ZLibrary {
				ability = id
				return true
			}
		}
		return false
	})
	i := slices.Index(e.G.Stack, ability)
	if i < 0 || i >= len(pl.View.Stack) || pl.View.Stack[i].Source != 0 {
		t.Fatalf("stack %+v, want entry %d with source 0", pl.View.Stack, i)
	}
}

var kindAndID = regexp.MustCompile(`[a-z_]+:[0-9]+`)

// Block options carry gorge groups named after native ids ("blocker:65"):
// the payload relabels them g0, g1, ... and no string carries a native id
// (G2-3).
func TestGroupsCarryNoNativeIDs(t *testing.T) {
	pl, p, _ := payloadAndGame(t, "Rally", func(d *decision.Decision, e *rules.Engine) bool {
		if d.Kind != decision.KBlockers {
			return false
		}
		for _, o := range d.Options {
			if o.Group != "" {
				return true
			}
		}
		return false
	})
	groups := regexp.MustCompile(`^g[0-9]+$`)
	native, got := p.Native.Options, pl.Decision.Options // blockers are visible: options keep their order
	for i := range native {
		if (native[i].Group == "") != (got[i].Group == "") || (got[i].Group != "" && !groups.MatchString(got[i].Group)) {
			t.Fatalf("option %d group %q became %q", i, native[i].Group, got[i].Group)
		}
		for j := range native {
			if (native[i].Group == native[j].Group) != (got[i].Group == got[j].Group) {
				t.Fatalf("options %d and %d changed group equality", i, j)
			}
		}
	}
	for k := range pl.Decision.GroupLimits {
		if !groups.MatchString(k) {
			t.Fatalf("group limit key %q", k)
		}
	}
	raw, _ := json.Marshal(pl)
	var walk func(any)
	walk = func(v any) {
		switch x := v.(type) {
		case string:
			if kindAndID.MatchString(x) {
				t.Errorf("payload string %q names a native id", x)
			}
		case []any:
			for _, e := range x {
				walk(e)
			}
		case map[string]any:
			for k, e := range x {
				walk(k)
				walk(e)
			}
		}
	}
	var generic any
	json.Unmarshal(raw, &generic)
	walk(generic)
	for _, pv := range pl.View.Players {
		for _, cv := range pv.Battlefield {
			if cv.Token != "#"+strconv.FormatUint(uint64(cv.ID), 10) {
				t.Errorf("card %d token %q", cv.ID, cv.Token)
			}
		}
	}
}
```

`internal/xview/key_test.go` (internal: `followKey`, `rekey` and `dropSourceless` are unexported):

```go
package xview

import (
	"testing"

	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
)

func TestFollowKeysFollowTheRenumbering(t *testing.T) {
	perm := []int{2, 0, 1}
	fperm := map[string][]int{"1": {1, 0}}
	for in, want := range map[string]string{"1": "0", "1/0": "0/1", "dig_bottom": "dig_bottom", "7": "7"} {
		if got := followKey(in, perm, fperm); got != want {
			t.Errorf("followKey(%q) = %q, want %q", in, got, want)
		}
	}
}

// A reference to a hidden card that no look shows, or to object 0 (a Rally
// pending trigger had one), becomes 0 without failing, and a pending trigger
// left without a source is dropped (G2-2).
func TestHiddenAndZeroReferencesBecomeZero(t *testing.T) {
	g := testgame.New(t, testcorpus.Registry(t), "Rally", "Rally", 1, "none")
	tr := identity.New(g.E, g.Secret)
	env := &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: g.E, IDs: tr}}
	hand, lib := g.E.G.Zone(state.ZHand, 0)[0], g.E.G.Zone(state.ZLibrary, 0)[0]
	r, errp := New().rekey(env, 0, map[state.ObjID]bool{})
	v := view.View{Pending: []view.PendingView{{Source: 0}, {Source: lib}, {Source: hand}},
		Stack: []view.StackView{{ID: hand, Source: lib}}}
	r.view(&v)
	dropSourceless(&v)
	if *errp != nil {
		t.Fatal(*errp)
	}
	if len(v.Pending) != 1 || v.Pending[0].Source == 0 || v.Stack[0].Source != 0 || v.Stack[0].ID == 0 {
		t.Fatalf("pending %+v, stack %+v", v.Pending, v.Stack)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/xview/`
Expected: FAIL with `undefined: xview.New`.

- [ ] **Step 3: Write minimal implementation**

`internal/xview/rekey.go`:

```go
package xview

import (
	"strconv"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
)

type rekeyer func(state.ObjID) state.ObjID

func (r rekeyer) card(cv *view.CardView) {
	cv.ID = r(cv.ID)
	cv.Token = "#" + strconv.FormatUint(uint64(cv.ID), 10)
	if cv.AttachedTo != 0 {
		cv.AttachedTo = r(cv.AttachedTo)
	}
	for i := range cv.BlockedBy {
		cv.BlockedBy[i] = r(cv.BlockedBy[i])
	}
}

func (r rekeyer) cards(cvs []view.CardView) {
	for i := range cvs {
		r.card(&cvs[i])
	}
}

func (r rekeyer) view(v *view.View) {
	for pi := range v.Players {
		p := &v.Players[pi]
		for _, z := range [][]view.CardView{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command, p.Commanders, p.PlanarDeck} {
			r.cards(z)
		}
		if p.LibraryTop != nil {
			r.card(p.LibraryTop)
		}
		for i := range p.PotentialActions {
			if p.PotentialActions[i].Obj != 0 {
				p.PotentialActions[i].Obj = r(p.PotentialActions[i].Obj)
			}
		}
		if p.CmdDamage != nil {
			m := map[state.ObjID]int32{}
			for id, v := range p.CmdDamage {
				m[r(id)] = v
			}
			p.CmdDamage = m
		}
	}
	for i := range v.Stack {
		s := &v.Stack[i]
		s.ID = r(s.ID)
		if s.Source != 0 {
			s.Source = r(s.Source)
		}
		for j := range s.Targets {
			if s.Targets[j].Obj != 0 {
				s.Targets[j].Obj = r(s.Targets[j].Obj)
			}
		}
		if s.Card != nil {
			r.card(s.Card)
		}
	}
	for i := range v.Pending {
		v.Pending[i].Source = r(v.Pending[i].Source)
	}
	v.Decision = nil // carried separately in Payload.Decision
}

func (r rekeyer) decision(d *decision.Decision, seq uint64) {
	d.Seq = seq
	d.PaymentActions, d.PaymentFallback = nil, nil
	if d.Source != 0 {
		d.Source = r(d.Source)
	}
	for i := range d.Options {
		o := &d.Options[i]
		for _, p := range []*state.ObjID{&o.Obj, &o.Attacker, &o.Battle} {
			if *p != 0 {
				*p = r(*p)
			}
		}
	}
}
```

`internal/xview/xview.go`:

```go
// Package xview builds x_gorge_view_v1: gorge's own seat view and native
// decision for gorge-native bots, re-keyed to per-seat non-native ids.
package xview

import (
	"encoding/json"
	"maps"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
)

type OptionFacts struct {
	Attach     bool            `json:"attach"`
	Grant      *decision.Grant `json:"grant"`
	Controller uint8           `json:"controller"`
	SetProps   []string        `json:"set_props"`
	BlockMust  bool            `json:"block_must"`
	AttackMust bool            `json:"attack_must"`
}

// ProducesFacts restores a card view's server-side mana production flags
// (cards.ManaProduction's Indeterminate and Reflected are json "-"), which
// gorge's bot reads when it taps mana.
type ProducesFacts struct {
	Card          state.ObjID `json:"card"`
	Indeterminate bool        `json:"indeterminate"`
	Reflected     bool        `json:"reflected"`
}

type Facts struct {
	Options                   []OptionFacts   `json:"options"`
	Produces                  []ProducesFacts `json:"produces"`
	EffectOptional            bool          `json:"effect_optional"`
	CopyOfCopy                bool          `json:"copy_of_copy"`
	AffordableTargets         int           `json:"affordable_targets"`
	TargetsWithSameController bool          `json:"targets_with_same_controller"`
	SetPropMode               string        `json:"set_prop_mode"`
	ResumeKind                string        `json:"resume_kind"`
	ResumeAPI                 string        `json:"resume_api"`
	ResumeUnlessCost          string        `json:"resume_unless_cost"`
}

type Payload struct {
	Version     int                          `json:"version"`
	NativeIndex uint64                       `json:"native_index"`
	View        view.View                    `json:"view"`
	Decision    decision.Decision            `json:"decision"`
	Facts       Facts                        `json:"policy_facts"`
	Followups   map[string]decision.Decision `json:"followups"`
	Ops         []mapping.NativeOp           `json:"ops"`
}

type table struct {
	ints map[string]uint32
	next uint32
}

// Follow is one folded follow-up of a seat's last payload: its payload key
// and its native -> payload option renumbering.
type Follow struct {
	Key  string
	Perm []int
}

type Extender struct {
	tables     [2]*table
	last       [2][]int             // the seat's last native -> payload renumbering (audit only, Task 28a)
	lastFollow [2]map[string]Follow // the same for its follow-ups, by native key (audit only, Task 28a)
}

func New() *Extender {
	return &Extender{tables: [2]*table{{ints: map[string]uint32{}}, {ints: map[string]uint32{}}}}
}

// rekey maps gorge object ids to the seat's small integers. Only objects the
// seat sees, or the hidden cards this pose's own look shows (its native and
// follow-up options), get one. Every other reference (a card in a hidden zone,
// an absent object, 0) becomes 0, the payload's analogue of v2's null
// (Sections 5.1 and 5.3).
func (x *Extender) rekey(env *mapping.Env, seat state.PlayerID, shown map[state.ObjID]bool) (rekeyer, *error) {
	var firstErr error
	t := x.tables[seat]
	return func(id state.ObjID) state.ObjID {
		o := env.G.E.G.Obj(id)
		var v2 string
		var err error
		switch {
		case o == nil:
			return 0
		case observe.Visible(seat, o) || o.Zone == state.ZCeased:
			v2, err = env.IDs.VisibleID(seat, id)
		case shown[id]:
			v2, err = env.IDs.LookID(seat, id)
		default:
			return 0
		}
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			return 0
		}
		n, ok := t.ints[v2]
		if !ok {
			t.next++
			n, t.ints[v2] = t.next, t.next
		}
		return state.ObjID(n)
	}, &firstErr
}

// shownBy lists the objects the pose's native decision and folded follow-ups
// offer: the only hidden-zone cards the payload may name.
func shownBy(p *mapping.Pose) map[state.ObjID]bool {
	shown := map[state.ObjID]bool{}
	for _, d := range append([]*decision.Decision{p.Native}, slices.Collect(maps.Values(p.Followups))...) {
		for _, o := range d.Options {
			shown[o.Obj] = true
		}
	}
	return shown
}

// relabelGroups replaces each option's Group with an opaque label in
// first-appearance order (g0, g1, ...), keeping equal groups equal, and
// renames GroupLimits keys the same way. gorge writes native object ids into
// group names ("blocker:65", "payment:12").
func relabelGroups(d *decision.Decision) {
	labels := map[string]string{}
	label := func(g string) string {
		if g == "" {
			return ""
		}
		l, ok := labels[g]
		if !ok {
			l = "g" + strconv.Itoa(len(labels))
			labels[g] = l
		}
		return l
	}
	for i := range d.Options {
		d.Options[i].Group = label(d.Options[i].Group)
	}
	if d.GroupLimits != nil {
		m := make(map[string]int, len(d.GroupLimits))
		for _, g := range slices.Sorted(maps.Keys(d.GroupLimits)) {
			m[label(g)] = d.GroupLimits[g]
		}
		d.GroupLimits = m
	}
}

// dropSourceless drops the pending triggers whose source rekeyed to 0: a
// hidden, absent or zero source, as the observation omits them (Section 6.6).
func dropSourceless(v *view.View) {
	kept := v.Pending[:0]
	for _, pv := range v.Pending {
		if pv.Source != 0 {
			kept = append(kept, pv)
		}
	}
	v.Pending = kept
}

// produces collects the mana production flags of every card in the view.
func produces(v *view.View) []ProducesFacts {
	var out []ProducesFacts
	add := func(cvs []view.CardView) {
		for _, cv := range cvs {
			if pr := cv.Produces; pr != nil && (pr.Indeterminate || pr.Reflected) {
				out = append(out, ProducesFacts{Card: cv.ID, Indeterminate: pr.Indeterminate, Reflected: pr.Reflected})
			}
		}
	}
	for _, p := range v.Players {
		for _, z := range [][]view.CardView{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command, p.Commanders} {
			add(z)
		}
	}
	return out
}

func facts(d *decision.Decision) Facts {
	f := Facts{EffectOptional: d.EffectOptional, CopyOfCopy: d.CopyOfCopy, AffordableTargets: d.AffordableTargets,
		TargetsWithSameController: d.TargetsWithSameController, SetPropMode: string(d.SetPropMode), ResumeKind: d.ResumeKind}
	if d.ResumeSA != nil {
		f.ResumeAPI, f.ResumeUnlessCost = d.ResumeSA.API, d.ResumeSA.Params["UnlessCost"]
	}
	for _, o := range d.Options {
		f.Options = append(f.Options, OptionFacts{Attach: o.Attach, Grant: o.Grant, Controller: uint8(o.Controller),
			SetProps: o.SetProps, BlockMust: o.BlockMust, AttackMust: o.AttackMust})
	}
	return f
}

// sortHidden reorders the options of d that reference hidden-zone cards by
// (card name, look id), renumbers every option, and returns old -> new
// (perm) and new -> old (order).
func sortHidden(env *mapping.Env, seat state.PlayerID, d *decision.Decision) (perm, order []int) {
	g := env.G.E.G
	perm, order = make([]int, len(d.Options)), make([]int, len(d.Options))
	var hid []int
	for i, o := range d.Options {
		order[i], perm[i] = i, i
		if obj := g.Obj(o.Obj); obj != nil && !observe.Visible(seat, obj) {
			hid = append(hid, i)
		}
	}
	key := func(i int) string {
		id, _ := env.IDs.LookID(seat, d.Options[i].Obj)
		return g.Obj(d.Options[i].Obj).Face().Name + "\x00" + id
	}
	sorted := append([]int(nil), hid...)
	sort.SliceStable(sorted, func(a, b int) bool { return key(sorted[a]) < key(sorted[b]) })
	for k, slot := range hid {
		order[slot] = sorted[k]
	}
	opts := make([]decision.Option, len(d.Options))
	for newIdx, old := range order {
		opts[newIdx] = d.Options[old]
		opts[newIdx].Index = newIdx
		perm[old] = newIdx
	}
	d.Options = opts
	return perm, order
}

func at(perm []int, i int) int {
	if i >= 0 && i < len(perm) {
		return perm[i]
	}
	return i
}

// followKey translates a follow-up key. "<option>" and "<option>/<follow-up
// option>" name native indices, which sortHidden renumbers; named keys
// ("dig_bottom") stay.
func followKey(k string, perm []int, fperm map[string][]int) string {
	a, b, two := strings.Cut(k, "/")
	i, err := strconv.Atoi(a)
	if err != nil {
		return k
	}
	out := strconv.Itoa(at(perm, i))
	if two {
		j, err := strconv.Atoi(b)
		if err != nil {
			return k
		}
		out += "/" + strconv.Itoa(at(fperm[a], j))
	}
	return out
}

func (x *Extender) Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error) {
	e := env.G.E
	seat := p.Seat
	r, errp := x.rekey(env, seat, shownBy(p))
	v := view.Project(e.G, e, seat, nil)
	v.Round = view.RoundOf(e.G, e.L.Events)
	r.view(&v)
	dropSourceless(&v)
	d := p.Native.CloneValue()
	pl := Payload{Version: 1, NativeIndex: nativeIndex, Facts: facts(&d), Followups: map[string]decision.Decision{}}
	pl.Facts.Produces = produces(&v)
	perm, order := sortHidden(env, seat, &d)
	x.last[seat] = perm
	if f := pl.Facts.Options; len(f) == len(order) {
		nf := make([]OptionFacts, len(f))
		for newIdx, old := range order {
			nf[newIdx] = f[old]
		}
		pl.Facts.Options = nf
	}
	r.decision(&d, nativeIndex)
	relabelGroups(&d)
	pl.Decision = d
	// Follow-ups are sorted the same way; their keys and every op that points
	// into them are translated with their own permutations. Keys are visited
	// in sorted order, so ids are numbered the same way on every rerun.
	fperm := map[string][]int{}
	follows := map[string]Follow{}
	for _, k := range slices.Sorted(maps.Keys(p.Followups)) {
		c := p.Followups[k].CloneValue()
		fperm[k], _ = sortHidden(env, seat, &c)
		r.decision(&c, nativeIndex)
		relabelGroups(&c)
		key := followKey(k, perm, fperm)
		pl.Followups[key] = c
		follows[k] = Follow{Key: key, Perm: fperm[k]}
	}
	x.lastFollow[seat] = follows
	for _, c := range p.Candidates {
		op := c.Op
		// The pose may be posed again (a retransmission): never rewrite its slices.
		op.Covers = append([]int(nil), op.Covers...)
		op.Followup = append([]int(nil), op.Followup...)
		if key, ok := strings.CutPrefix(op.List, "followup:"); ok {
			op.Option = at(fperm[key], op.Option)
		} else {
			op.Option = at(perm, op.Option)
		}
		if len(op.Followup) > 0 {
			k0 := strconv.Itoa(c.Op.Option)
			op.Followup[0] = at(fperm[k0], c.Op.Followup[0])
			if len(op.Followup) > 1 {
				op.Followup[1] = at(fperm[k0+"/"+strconv.Itoa(c.Op.Followup[0])], c.Op.Followup[1])
			}
		}
		for i, cv := range op.Covers {
			op.Covers[i] = at(perm, cv)
		}
		if op.Unit != 0 {
			op.Unit = r(op.Unit)
		}
		pl.Ops = append(pl.Ops, op)
	}
	pl.View = v
	if *errp != nil {
		return nil, *errp
	}
	raw, err := json.Marshal(pl)
	if err != nil {
		return nil, err
	}
	return map[string]json.RawMessage{"x_gorge_view_v1": raw}, nil
}
```

Order of operations matters. Every permutation is computed from native indices before any key or op is rewritten, and `Unit` is re-keyed like every other id. `Covers` and `Followup` are copied before rewriting, because a retransmitted decision re-extends the same pose. A `list` op whose List starts with `followup:` indexes that follow-up, so it takes the follow-up's permutation, not the native decision's.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/xview/ -v`
Expected: `--- PASS: TestPayloadHasNoGlobalCountersOrDigests`, `--- PASS: TestSearchOptionsAreSortedAndIDsAreSmall`, `--- PASS: TestHiddenStackSourceIsZero`, `--- PASS: TestGroupsCarryNoNativeIDs`, `--- PASS: TestFollowKeysFollowTheRenumbering`, `--- PASS: TestHiddenAndZeroReferencesBecomeZero`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/xview && git commit -m "gorge adapter: x_gorge_view_v1 with per-seat ids, sorted hidden options, policy facts"
```

---

### Task 25: Mini-host and Go test agents

**Files:**
- Create: `internal/minihost/host.go`, `internal/minihost/agents.go`
- Test: `internal/minihost/host_test.go`

**Interfaces:**
- Consumes: `server.Server`, `validate` (`Stream.Check` and `Stream.InGroup`, Task 9), `wire` (canonical, digest, `DomainID` with its error), `secrets` (host side), `catalog`, `protocol` (the `Semantic` decoder of Task 5: the host decodes the engine's JSON into `protocol.SeatDecision` before validating).
- Produces:
  - `type minihost.Link interface{ Round(req []byte) ([]byte, error) }`;
  - `type minihost.Host struct{ RunSecret []byte; Engine Link; Profile validate.Profile; MaxSteps, MaxDecisions uint64; KeepDecisions bool }`;
  - `func (*Host) Play(i uint64, deck catalog.Deck, mulligan string, extensions []string, agents [2]Link) (Result, error)`;
  - `type minihost.Result struct{ Terminal protocol.TerminalResponse; Digest string; Steps int; SeatDecisions [2][][]byte }` (the canonical `seat_decision` bytes, kept only with `KeepDecisions`: at 10 to 35 KB each with the extension, keeping every game's would exhaust memory in long qualification runs, G2-22);
  - `type minihost.EngineLink struct{ S *server.Server }`;
  - `type minihost.Uniform struct` and `type minihost.First struct` (in-process agents seeded from `game_start.agent_seed`).

The mini-host implements Sections 11.2 (canonical forwarding), 11.3 (validator subset), 11.6 (secrets, agent seeds, opaque ids) and 11.8 (digest). It has no clocks, adjudication or stalling; P's host owns those. It also checks V3 across its two streams: no decision for one seat while the other seat's group is partial (G1-11).

- [ ] **Step 1: Write the failing test**

`internal/minihost/host_test.go`:

```go
package minihost_test

import (
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

func host(t *testing.T) *minihost.Host {
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	run := make([]byte, 32)
	return &minihost.Host{RunSecret: run, Engine: &minihost.EngineLink{S: server.New(testcorpus.Registry(t), nil)},
		Profile: validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{"x_gorge_view_v1": true}},
		MaxSteps: 20000, MaxDecisions: 9999}
}

func TestUniformGamesOnEveryDeckValidateAndReplay(t *testing.T) {
	for i, d := range catalog.Decks() {
		agents := [2]minihost.Link{&minihost.Uniform{}, &minihost.Uniform{}}
		a, err := host(t).Play(uint64(i), d, "london", []string{"x_gorge_view_v1"}, agents)
		if err != nil {
			t.Fatalf("%s: %v", d.CatalogID, err)
		}
		if a.Terminal.Classification == "halted" {
			t.Fatalf("%s halted: %s", d.CatalogID, a.Terminal.Reason)
		}
		b, _ := host(t).Play(uint64(i), d, "london", []string{"x_gorge_view_v1"}, [2]minihost.Link{&minihost.Uniform{}, &minihost.Uniform{}})
		if a.Digest != b.Digest {
			t.Fatalf("%s: rerun digest %s != %s", d.CatalogID, b.Digest, a.Digest)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/minihost/`
Expected: FAIL with `undefined: minihost.Host`.

- [ ] **Step 3: Write minimal implementation**

`internal/minihost/agents.go`:

```go
package minihost

import (
	"encoding/json"
	"fmt"
	"math/rand/v2"
)

type Link interface{ Round(req []byte) ([]byte, error) }

type agentReq struct {
	RequestType string          `json:"request_type"`
	RequestID   string          `json:"request_id"`
	AgentSeed   uint64          `json:"agent_seed"`
	Decision    json.RawMessage `json:"decision"`
}

func reply(id, typ string, extra string) []byte {
	return []byte(fmt.Sprintf(`{"response_type":%q,"protocol":"spellbench/v2","request_id":%q%s}`, typ, id, extra))
}

// Uniform picks uniformly with a PCG seeded from agent_seed.
type Uniform struct{ r *rand.Rand }

func (u *Uniform) Round(req []byte) ([]byte, error) {
	var q agentReq
	if err := json.Unmarshal(req, &q); err != nil {
		return nil, err
	}
	switch q.RequestType {
	case "hello":
		return reply(q.RequestID, "hello_ok", `,"bot":{"name":"uniform-go","version":"1"}`), nil
	case "game_start":
		u.r = rand.New(rand.NewPCG(q.AgentSeed, 1))
		return reply(q.RequestID, "ack", ""), nil
	case "choose":
		var d struct{ Candidates []json.RawMessage }
		json.Unmarshal(q.Decision, &d)
		return reply(q.RequestID, "choice", fmt.Sprintf(`,"selection":{"candidate_id":%d}`, u.r.IntN(len(d.Candidates)))), nil
	}
	return reply(q.RequestID, "ack", ""), nil
}

// First always picks candidate 0.
type First struct{}

func (First) Round(req []byte) ([]byte, error) {
	var q agentReq
	if err := json.Unmarshal(req, &q); err != nil {
		return nil, err
	}
	switch q.RequestType {
	case "hello":
		return reply(q.RequestID, "hello_ok", `,"bot":{"name":"first-go","version":"1"}`), nil
	case "choose":
		return reply(q.RequestID, "choice", `,"selection":{"candidate_id":0}`), nil
	}
	return reply(q.RequestID, "ack", ""), nil
}
```

`internal/minihost/host.go`:

```go
// Package minihost is an in-process Spellbench v2 host for this adapter's
// tests and qualification: canonical forwarding, the validator subset,
// secrets and the game digest. Not a replacement for the reference host.
package minihost

import (
	"encoding/hex"
	"encoding/json"
	"fmt"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type EngineLink struct{ S *server.Server }

func (e *EngineLink) Round(req []byte) ([]byte, error) { return e.S.Handle(req), nil }

type Host struct {
	RunSecret              []byte
	Engine                 Link
	Profile                validate.Profile
	MaxSteps, MaxDecisions uint64
	// KeepDecisions keeps every forwarded seat decision in the Result. They
	// run 10 to 35 KB each with the extension, so only tests that read them
	// turn it on.
	KeepDecisions bool
	n             int
}

type Result struct {
	Terminal      protocol.TerminalResponse
	Digest        string
	Steps         int
	SeatDecisions [2][][]byte // only with Host.KeepDecisions
}

func (h *Host) id() string { h.n++; return fmt.Sprintf("h-%d", h.n) }

func (h *Host) Play(i uint64, deck catalog.Deck, mulligan string, extensions []string, agents [2]Link) (Result, error) {
	var res Result
	gameID := secrets.GameID(h.RunSecret, i)
	names := catalog.PoolNames()
	domain, err := wire.DomainID(names)
	if err != nil {
		return res, err
	}
	seat0 := "p0"
	reset := map[string]any{"request_type": "reset", "protocol": protocol.Name, "request_id": h.id(), "game_id": gameID,
		"format": "pauper-bo1",
		"seats": []any{map[string]any{"seat": "p0", "deck": map[string]any{"deck_id": deck.DeckID(), "catalog_id": deck.CatalogID}},
			map[string]any{"seat": "p1", "deck": map[string]any{"deck_id": deck.DeckID(), "catalog_id": deck.CatalogID}}},
		"rules": map[string]any{"opponent_decklist": "visible", "mulligan": mulligan, "starting_player": "host_assigned",
			"starting_seat": seat0, "card_name_domain": map[string]any{"domain_id": domain, "names": names},
			"extensions": extensions, "probe": false},
		"game_secret": hex.EncodeToString(secrets.GameSecret(h.RunSecret, i)), "max_decisions": h.MaxDecisions, "max_steps": h.MaxSteps}
	resetBytes, _ := wire.Canonical(reset)
	noID, _ := wire.WithoutRequestID(resetBytes)
	dig, err := wire.NewGameDigest(noID)
	if err != nil {
		return res, err
	}
	for s, a := range agents {
		seat := fmt.Sprintf("p%d", s)
		// A minimal game_start: only the fields this adapter's agents read.
		// P's host sends the full message; Task 30 runs the agent under it.
		start, _ := wire.Canonical(map[string]any{"request_type": "game_start", "protocol": protocol.Name, "request_id": "r-0",
			"game_id": gameID, "seat": seat, "agent_seed": secrets.AgentSeed(h.RunSecret, i, seat)})
		if _, err := a.Round(start); err != nil {
			return res, err
		}
	}
	// The game's profile enables its extensions before any stream exists;
	// the host's own profile is never mutated.
	prof := h.Profile
	prof.Extensions = map[string]bool{}
	for k, v := range h.Profile.Extensions {
		prof.Extensions[k] = v
	}
	for _, x := range extensions {
		prof.Extensions[x] = true
	}
	streams := [2]*validate.Stream{validate.NewStream(prof), validate.NewStream(prof)}
	out, _ := h.Engine.Round(resetBytes)
	agentReq := [2]int{1, 1}
	for {
		chain, _ := wire.WithoutRequestID(out)
		if err := dig.Chain(chain); err != nil {
			return res, err
		}
		var head struct {
			ResponseType string                `json:"response_type"`
			Step         uint64                `json:"step"`
			SeatDecision protocol.SeatDecision `json:"seat_decision"`
			Error        *protocol.ErrorBody   `json:"error"`
		}
		if err := json.Unmarshal(out, &head); err != nil {
			return res, err
		}
		switch head.ResponseType {
		case "terminal":
			json.Unmarshal(out, &res.Terminal)
			res.Digest = dig.String()
			return res, nil
		case "error":
			return res, fmt.Errorf("engine error %s: %s", head.Error.Code, head.Error.Message)
		}
		sd := head.SeatDecision
		seat := 0
		if sd.ActingSeat == "p1" {
			seat = 1
		}
		// V3 across the two streams: while one seat's group is partial, the
		// engine poses nothing to the other seat (Section 8).
		if streams[1-seat].InGroup() {
			return res, fmt.Errorf("validator: V3: decision for %s while the other seat's group is partial", sd.ActingSeat)
		}
		if err := streams[seat].Check(sd); err != nil {
			return res, fmt.Errorf("validator: %w", err)
		}
		// Forward the host's canonical re-serialization (Section 11.2).
		var raw struct {
			SeatDecision json.RawMessage `json:"seat_decision"`
		}
		json.Unmarshal(out, &raw)
		canon, err := wire.CanonicalBytes(raw.SeatDecision)
		if err != nil {
			return res, err
		}
		if h.KeepDecisions {
			res.SeatDecisions[seat] = append(res.SeatDecisions[seat], canon)
		}
		choose := fmt.Sprintf(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"r-%d","game_id":%q,"decision":%s,"clock":{"remaining_ms":600000,"max_decision_ms":60000}}`,
			agentReq[seat], gameID, canon)
		agentReq[seat]++
		ans, err := agents[seat].Round([]byte(choose))
		if err != nil {
			return res, err
		}
		var choice struct {
			Selection struct {
				CandidateID int `json:"candidate_id"`
			} `json:"selection"`
		}
		if err := json.Unmarshal(ans, &choice); err != nil || choice.Selection.CandidateID < 0 || choice.Selection.CandidateID >= len(sd.Candidates) {
			return res, fmt.Errorf("invalid selection %s", ans)
		}
		echo, _ := json.Marshal(sd.Candidates[choice.Selection.CandidateID].Semantic)
		step := []byte(fmt.Sprintf(`{"request_type":"step","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"expected_step":%d,"selection":{"candidate_id":%d,"semantic_echo":%s}}`,
			h.id(), gameID, head.Step, choice.Selection.CandidateID, echo))
		sc, _ := wire.WithoutRequestID(step)
		if err := dig.Chain(sc); err != nil {
			return res, err
		}
		res.Steps++
		out, _ = h.Engine.Round(step)
	}
}
```

Note: the engine's decision responses are canonical already (`server.marshal`), but the host re-canonicalizes regardless, as Section 11.2 requires.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/minihost/ -v -timeout 20m`
Expected: `--- PASS: TestUniformGamesOnEveryDeckValidateAndReplay`. Five decks, two runs each, no `halted`, identical digests.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/minihost && git commit -m "gorge adapter: in-process v2 mini-host with validator, canonical forwarding and digests"
```

---

### Task 26: Go agent wrapping gorge's bots

**Files:**
- Create: `internal/agent/agent.go`, `internal/agent/pick.go`
- Create: `cmd/spellbench-gorge-agent/main.go`
- Test: `internal/agent/agent_test.go`, `internal/agent/pick_test.go`

**Interfaces:**
- Consumes: `xview.Payload` and `xview.ProducesFacts`, `mapping.NativeOp`, `seat.NewBot`, `seat.NewLethalPressureBot`, `wire.NewReader`; the test drives games through `server` (Task 23) and `minihost` (Task 25).
- Produces:
  - `type agent.Server` with `func agent.New(policy string) (*Server, error)` (`bot` or `lethal-pressure`), `func (*Server) Handle(line []byte) []byte` and `func (*Server) Round(req []byte) ([]byte, error)` (a `minihost.Link`);
  - `func agent.Serve(r io.Reader, w io.Writer, s *Server) error`: the stdio loop; an over-long line is answered `malformed_json` and the next line is read;
  - `func agent.Rebuild(p xview.Payload) (view.View, decision.Decision)` (applies the policy facts, including the card views' mana production flags);
  - `func agent.Pick(p xview.Payload, sems []map[string]any, st *Plan, ask func(decision.Decision) decision.Intent) (int, string)` (candidate semantics are read as generic JSON; the string is `""` for a match, `"forced"` or `"fallback"`);
  - `type agent.Plan` and `func agent.NewPlan(native uint64, in decision.Intent) *Plan`;
  - `type agent.Record struct{ Intent decision.Intent; Followups map[string]decision.Intent; Forced, Fallbacks int; Reason string }`, `func (*Server) Records() map[uint64]*Record` (the current game's native decisions, with the bot's follow-up answers keyed as the payload keys them, for Task 28b's parity audit), `func (*Server) Fallbacks() int` and `func (*Server) Forced() int`;
  - the `spellbench-gorge-agent` binary (`-policy`).

Behaviour:
- `hello_ok` names the bot `gorge-bot` or `gorge-lethal-pressure`, version `gorge-26257e0eda17/adapter-0.1.0`, and `requires.extensions: ["x_gorge_view_v1"]`.
- At `game_start` the bot is seeded from `agent_seed` (gorge's own PCG, as `seat.NewBot(seed)`).
- At each new `native_index` the bot answers the native decision once. Folded follow-ups are asked lazily with the same view.
- The intent then drives every substep:
  - `choose` matches the next option of the intent in the bot's answer order (membership for declaration units, which carry `Unit`), plus follow-ups;
  - `none` matches a unit with no intended option;
  - `cast` matches when the intended option is in `Covers`;
  - `dest` matches when the card's option is inside the intended Choices exactly when the destination is `top` or `hand`;
  - `list` matches the named list (`Choices`, `Rest`, or a follow-up's answer) at `Position`;
  - `finish` matches when every intended pick is done.
- When nothing matches a decision with a single candidate, it is answered as forced (G2-7): gorge's bot takes every offered unless payment, but when paying needs a mana window the engine leaves only `pay: false` (controller decision 2). A forced answer is counted apart from fallbacks, recorded with a reason on the native decision's `Record`, and skipped by parity.
- When nothing matches among several candidates, the agent falls back to `pay: false`, then `finish`, then candidate 0, and records the fallback and its reason.
- A panic inside the bot answers an empty intent, so the substep falls back (counted); any other failure answers `internal_error`, and a `choose` before `game_start` answers `malformed_request` (G2-26, Section 10.5).

- [ ] **Step 1: Write the failing test**

`internal/agent/agent_test.go`:

```go
package agent_test

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func TestAgentDecodesCanonicalizedPayload(t *testing.T) {
	a, _ := agent.New("bot")
	var hello map[string]any
	json.Unmarshal(a.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}`)), &hello)
	if hello["bot"].(map[string]any)["name"] != "gorge-bot" {
		t.Fatalf("hello %v", hello)
	}
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	h := &minihost.Host{RunSecret: make([]byte, 32), Engine: &minihost.EngineLink{S: server.New(testcorpus.Registry(t), nil)},
		Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
		MaxSteps: 3000, MaxDecisions: 2999, KeepDecisions: true}
	burn, _ := catalog.ByID("Burn")
	b0, _ := agent.New("bot")
	b1, _ := agent.New("lethal-pressure")
	res, err := h.Play(3, burn, "london", []string{"x_gorge_view_v1"}, [2]minihost.Link{b0, b1})
	if err != nil {
		t.Fatal(err) // the host forwards canonical bytes: sorted keys, re-printed integers
	}
	if res.Terminal.Classification == "halted" {
		t.Fatalf("halted: %s", res.Terminal.Reason)
	}
	if b0.Fallbacks()+b1.Fallbacks() > res.Steps/50 {
		t.Fatalf("%d fallbacks in %d steps", b0.Fallbacks()+b1.Fallbacks(), res.Steps)
	}
	canon, _ := wire.CanonicalBytes(res.SeatDecisions[0][0])
	if !strings.Contains(string(canon), `"x_gorge_view_v1"`) {
		t.Fatal("extension missing from the forwarded decision")
	}
}

// A choose before game_start is refused, not a crash, and an over-long line
// is answered malformed_json while the agent keeps serving (G2-26).
func TestAgentAnswersErrorsAndKeepsReading(t *testing.T) {
	a, _ := agent.New("bot")
	var m map[string]any
	json.Unmarshal(a.Handle([]byte(`{"request_type":"choose","protocol":"spellbench/v2","request_id":"r-1","game_id":"g","decision":{"candidates":[]}}`)), &m)
	if m["response_type"] != "error" || m["error"].(map[string]any)["code"] != "malformed_request" {
		t.Fatalf("choose before game_start: %v", m)
	}
	in := strings.Repeat("x", wire.MaxLineBytes+1) + "\n" + `{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}` + "\n"
	var w bytes.Buffer
	if err := agent.Serve(strings.NewReader(in), &w, a); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(w.String()), "\n")
	if len(lines) != 2 || !strings.Contains(lines[0], `"malformed_json"`) || !strings.Contains(lines[1], `"hello_ok"`) {
		t.Fatalf("answers %q", lines)
	}
}
```

`internal/agent/pick_test.go`:

```go
package agent_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

func TestPickFollowsAScryAnswer(t *testing.T) {
	pl := agent.NewPlan(1, decision.Intent{Choices: []int{2}, Rest: []int{0, 1}})
	none := func(decision.Decision) decision.Intent { return decision.Intent{} }
	sems := []map[string]any{{"kind": "arrange_card"}, {"kind": "arrange_card"}}
	part := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "dest", Option: 0, List: "top", Position: 0},
		{Op: "dest", Option: 0, List: "bottom", Position: 0},
	}}
	if i, miss := agent.Pick(part, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("card 0 went to candidate %d (%q), want the bottom", i, miss)
	}
	order := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "list", Option: 1, List: "rest", Position: 0},
		{Op: "list", Option: 0, List: "rest", Position: 0},
	}}
	if i, miss := agent.Pick(order, sems, pl, none); i != 1 || miss != "" {
		t.Fatalf("first bottom card is candidate %d (%q), want option 0", i, miss)
	}
	// Nothing matches a single candidate: it is forced, never a fallback (G2-7).
	lone := xview.Payload{Ops: []mapping.NativeOp{{Op: "list", Option: 1, List: "choices", Position: 0}}}
	if i, miss := agent.Pick(lone, sems[:1], pl, none); i != 0 || miss != "forced" {
		t.Fatalf("lone unmatched candidate %d (%q), want 0 forced", i, miss)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/agent/`
Expected: FAIL with `undefined: agent.New`.

- [ ] **Step 3: Write minimal implementation**

`internal/agent/agent.go`:

```go
// Package agent serves gorge's bots in the Spellbench v2 agent role, reading
// only the forwarded seat decision and its x_gorge_view_v1 extension.
package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// Record is how the agent played one native decision, for Task 28b's parity
// audit: the bot's plan (its intent, and its answers to the folded follow-ups
// it was asked, keyed as the payload keys them) and the substeps no op
// matched: Forced when the decision had a single candidate, Fallbacks
// otherwise, with the first reason.
type Record struct {
	Intent    decision.Intent
	Followups map[string]decision.Intent
	Forced    int
	Fallbacks int
	Reason    string
}

type Server struct {
	policy    string
	bot       seat.Seat
	plan      *Plan
	fallbacks int
	forced    int
	records   map[uint64]*Record // the current game's native decisions (parity audit)
}

func New(policy string) (*Server, error) {
	if policy != "bot" && policy != "lethal-pressure" {
		return nil, fmt.Errorf("unknown policy %q", policy)
	}
	return &Server{policy: policy, records: map[uint64]*Record{}}, nil
}

// Fallbacks counts substeps answered by the fallback rule; Forced counts
// single-candidate substeps no op matched (the unless-cost restriction of
// controller decision 2, say). Both are per process, across games.
func (s *Server) Fallbacks() int { return s.fallbacks }

func (s *Server) Forced() int { return s.forced }

// Records exposes the current game's native decisions to Task 28b's audit.
func (s *Server) Records() map[uint64]*Record { return s.records }

func (s *Server) Round(req []byte) ([]byte, error) { return s.Handle(req), nil }

type candidate struct {
	CandidateID uint32         `json:"candidate_id"`
	Semantic    map[string]any `json:"semantic"` // read generically: the agent needs only kinds and a few fields
}

type request struct {
	RequestType string `json:"request_type"`
	RequestID   string `json:"request_id"`
	AgentSeed   uint64 `json:"agent_seed"`
	Decision    struct {
		Candidates []candidate                `json:"candidates"`
		Extensions map[string]json.RawMessage `json:"extensions"`
	} `json:"decision"`
}

func out(v map[string]any) []byte { b, _ := json.Marshal(v); return b }

func errorLine(id, code, msg string) []byte {
	return out(map[string]any{"response_type": "error", "protocol": protocol.Name, "request_id": id,
		"error": map[string]string{"code": code, "message": msg}})
}

// Handle answers one request line. A failure inside the agent answers
// internal_error (Section 10.5) instead of ending the process.
func (s *Server) Handle(line []byte) (resp []byte) {
	var q request
	dec := json.NewDecoder(bytes.NewReader(line))
	dec.UseNumber() // amounts compare as integers, never as floats
	if err := dec.Decode(&q); err != nil {
		return errorLine("", "malformed_json", err.Error())
	}
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintln(os.Stderr, "gorge agent: internal error:", r)
			resp = errorLine(q.RequestID, "internal_error", "the agent failed")
		}
	}()
	base := map[string]any{"protocol": protocol.Name, "request_id": q.RequestID}
	switch q.RequestType {
	case "hello":
		name := map[string]string{"bot": "gorge-bot", "lethal-pressure": "gorge-lethal-pressure"}[s.policy]
		base["response_type"] = "hello_ok"
		base["bot"] = map[string]string{"name": name, "version": "gorge-26257e0eda17/adapter-0.1.0"}
		base["requires"] = map[string][]string{"observation": {}, "extensions": {"x_gorge_view_v1"}}
		base["extensions_accepted"] = []string{"x_gorge_view_v1"}
	case "game_start":
		if s.policy == "lethal-pressure" {
			s.bot = seat.NewLethalPressureBot(q.AgentSeed)
		} else {
			s.bot = seat.NewBot(q.AgentSeed)
		}
		s.plan = nil
		s.records = map[uint64]*Record{}
		base["response_type"] = "ack"
	case "choose":
		if s.bot == nil {
			return errorLine(q.RequestID, "malformed_request", "choose before game_start")
		}
		base["response_type"] = "choice"
		base["selection"] = map[string]uint32{"candidate_id": s.choose(q)}
	default:
		base["response_type"] = "ack"
	}
	return out(base)
}

// Serve answers request lines until the input ends. An over-long line is
// answered malformed_json and the next line is read (Section 2).
func Serve(r io.Reader, w io.Writer, s *Server) error {
	in := wire.NewReader(r)
	for {
		line, err := in.ReadLine()
		var resp []byte
		switch {
		case errors.Is(err, io.EOF):
			return nil
		case errors.Is(err, wire.ErrLineTooLong):
			resp = errorLine("", "malformed_json", "line exceeds 8 MiB")
		case err != nil:
			return err
		default:
			resp = s.Handle(line)
		}
		if _, err := w.Write(append(resp, '\n')); err != nil {
			return err
		}
	}
}

// decide asks the bot. A panic answers an empty intent, so no op matches and
// the substep falls back, counted.
func (s *Server) decide(v view.View, d decision.Decision) (in decision.Intent) {
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintln(os.Stderr, "gorge agent: bot panic:", r)
			in = decision.Intent{}
		}
	}()
	in, _ = s.bot.Decide(context.Background(), v, d)
	return in
}

func (s *Server) choose(q request) uint32 {
	cands := q.Decision.Candidates
	raw, ok := q.Decision.Extensions["x_gorge_view_v1"]
	if !ok || len(cands) == 0 {
		s.fallbacks++
		return 0
	}
	var p xview.Payload
	if err := json.Unmarshal(raw, &p); err != nil || len(p.Ops) != len(cands) {
		fmt.Fprintln(os.Stderr, "gorge agent: payload unusable:", err)
		s.fallbacks++
		return cands[0].CandidateID
	}
	v, d := Rebuild(p)
	ask := func(nd decision.Decision) decision.Intent {
		vv := v // a follow-up is asked with the same view, showing that decision
		vv.Decision = &nd
		return s.decide(vv, nd)
	}
	if s.plan == nil || s.plan.native != p.NativeIndex {
		s.plan = NewPlan(p.NativeIndex, ask(d))
		s.records[p.NativeIndex] = &Record{Intent: s.plan.intent, Followups: s.plan.follow}
	}
	sems := make([]map[string]any, len(cands))
	for i, c := range cands {
		sems[i] = c.Semantic
	}
	i, miss := Pick(p, sems, s.plan, ask)
	if miss != "" {
		r := s.records[p.NativeIndex]
		if miss == "forced" {
			s.forced++
			r.Forced++
		} else {
			s.fallbacks++
			r.Fallbacks++
		}
		if r.Reason == "" {
			r.Reason = fmt.Sprintf("%s: no %v candidate of %d matches the plan", miss, sems[0]["kind"], len(sems))
		}
		fmt.Fprintln(os.Stderr, "gorge agent: native", p.NativeIndex, r.Reason)
	}
	return cands[i].CandidateID
}

// Rebuild returns the bot's inputs, restoring the server-side policy facts.
func Rebuild(p xview.Payload) (view.View, decision.Decision) {
	v, d := p.View, p.Decision
	f := p.Facts
	d.EffectOptional, d.CopyOfCopy, d.AffordableTargets = f.EffectOptional, f.CopyOfCopy, f.AffordableTargets
	d.TargetsWithSameController, d.SetPropMode, d.ResumeKind = f.TargetsWithSameController, decision.SetPropMode(f.SetPropMode), f.ResumeKind
	if f.ResumeAPI != "" {
		d.ResumeSA = &cards.SA{API: f.ResumeAPI, Params: map[string]string{"UnlessCost": f.ResumeUnlessCost}}
	}
	for i := range d.Options {
		if i < len(f.Options) {
			o := f.Options[i]
			d.Options[i].Attach, d.Options[i].Grant, d.Options[i].Controller = o.Attach, o.Grant, state.PlayerID(o.Controller)
			d.Options[i].SetProps, d.Options[i].BlockMust, d.Options[i].AttackMust = o.SetProps, o.BlockMust, o.AttackMust
		}
	}
	flags := map[state.ObjID]xview.ProducesFacts{}
	for _, pf := range f.Produces {
		flags[pf.Card] = pf
	}
	for pi := range v.Players {
		pv := &v.Players[pi]
		for _, zone := range [][]view.CardView{pv.Hand, pv.Battlefield, pv.Graveyard, pv.Exile, pv.Command, pv.Commanders} {
			for i := range zone {
				if pf, ok := flags[zone[i].ID]; ok && zone[i].Produces != nil {
					pr := *zone[i].Produces
					pr.Indeterminate, pr.Reflected = pf.Indeterminate, pf.Reflected
					zone[i].Produces = &pr
				}
			}
		}
	}
	v.Decision = &d
	return v, d
}
```

`internal/agent/pick.go`:

```go
package agent

import (
	"fmt"
	"slices"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// Plan is the bot's answer to one native decision, spent substep by substep.
type Plan struct {
	native uint64
	intent decision.Intent
	follow map[string]decision.Intent
	used   []int
}

// NewPlan starts the plan for native decision `native` from the bot's intent.
func NewPlan(native uint64, in decision.Intent) *Plan {
	return &Plan{native: native, intent: in, follow: map[string]decision.Intent{}}
}

// followup asks the bot a folded follow-up once, with the same view.
func (pl *Plan) followup(p xview.Payload, key string, ask func(decision.Decision) decision.Intent) []int {
	in, ok := pl.follow[key]
	if !ok {
		fd, ok := p.Followups[key]
		if !ok {
			return nil
		}
		in = ask(fd)
		pl.follow[key] = in
	}
	return in.Choices
}

// complement lists the options outside chosen, in offered order.
func complement(chosen []int, n int) []int {
	var out []int
	for i := 0; i < n; i++ {
		if !slices.Contains(chosen, i) {
			out = append(out, i)
		}
	}
	return out
}

func unitChosen(p xview.Payload, in decision.Intent, unit int) bool {
	for _, c := range in.Choices {
		if c < len(p.Decision.Options) && int(p.Decision.Options[c].Obj) == unit {
			return true
		}
	}
	return false
}

// match reports whether a candidate's native op agrees with the plan.
func (pl *Plan) match(p xview.Payload, op mapping.NativeOp, ask func(decision.Decision) decision.Intent) bool {
	in := pl.intent
	switch op.Op {
	case "choose":
		var ok bool
		if op.Unit != 0 {
			// Declaration units are posed in the adapter's unit order: membership.
			ok = slices.Contains(in.Choices, op.Option) && !slices.Contains(pl.used, op.Option)
		} else {
			// Everything else follows the bot's answer order, which native asks
			// read (target slots, cards put on the library in order).
			ok = len(pl.used) < len(in.Choices) && in.Choices[len(pl.used)] == op.Option
		}
		if ok && len(op.Followup) > 0 {
			got := pl.followup(p, fmt.Sprint(op.Option), ask)
			ok = len(got) > 0 && got[0] == op.Followup[0]
			if ok && len(op.Followup) > 1 {
				got2 := pl.followup(p, fmt.Sprint(op.Option, "/", op.Followup[0]), ask)
				ok = len(got2) > 0 && got2[0] == op.Followup[1]
			}
		}
		return ok
	case "none":
		return !unitChosen(p, in, int(op.Unit))
	case "cast":
		for _, c := range op.Covers {
			if slices.Contains(in.Choices, c) {
				return true
			}
		}
	case "dest":
		inside := op.Option >= 0 && slices.Contains(in.Choices, op.Option)
		return inside == (op.List == "top" || op.List == "hand")
	case "list":
		list := in.Choices
		if op.List == "rest" {
			list = in.Rest
			if len(list) == 0 { // no pile-B order given: gorge's default, the offered order
				list = complement(in.Choices, len(p.Decision.Options))
			}
		} else if key, ok := strings.CutPrefix(op.List, "followup:"); ok {
			list = pl.followup(p, key, ask)
		}
		return op.Position < len(list) && list[op.Position] == op.Option
	case "finish":
		return len(pl.used) >= len(in.Choices)
	}
	return false
}

// Pick returns the candidate matching the plan, with miss "". When no op
// matches, a single candidate is answered as "forced" (an engine-fixed order,
// or pay:false left alone by the unless-cost restriction of controller
// decision 2); otherwise the agent falls back to pay:false, then finish, then
// candidate 0, as "fallback".
func Pick(p xview.Payload, sems []map[string]any, pl *Plan, ask func(decision.Decision) decision.Intent) (int, string) {
	for i, op := range p.Ops {
		if pl.match(p, op, ask) {
			if op.Op == "choose" {
				pl.used = append(pl.used, op.Option)
			}
			return i, ""
		}
	}
	if len(sems) == 1 {
		return 0, "forced"
	}
	for i, s := range sems {
		if s["kind"] == "optional_cost" && s["pay"] == false {
			return i, "fallback"
		}
	}
	for i, s := range sems {
		if s["kind"] == "finish_selection" || s["kind"] == "finish_target_selection" {
			return i, "fallback"
		}
	}
	return 0, "fallback"
}
```

Why `choose` is sequential: the adapter commits a multi-pick answer in pick order, and gorge reads that order for target slots and for cards put on the library. Matching the bot's order therefore reproduces its native intent exactly. Arrangements use `dest` for the partition and `list` for the order, so a scry answer with Choices [2] and Rest [0, 1] sends card 2 to the top and orders the bottom as 0 then 1.

`cmd/spellbench-gorge-agent/main.go`:

```go
// Command spellbench-gorge-agent serves gorge's default or lethal-pressure bot
// in the Spellbench v2 agent role over stdio.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
)

func main() {
	policy := flag.String("policy", "bot", "bot or lethal-pressure")
	flag.Parse()
	s, err := agent.New(*policy)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := agent.Serve(os.Stdin, &flushWriter{bufio.NewWriter(os.Stdout)}, s); err != nil {
		fmt.Fprintln(os.Stderr, "spellbench-gorge-agent:", err)
		os.Exit(1)
	}
}

type flushWriter struct{ w *bufio.Writer }

func (f *flushWriter) Write(p []byte) (int, error) {
	n, err := f.w.Write(p)
	if err == nil {
		err = f.w.Flush()
	}
	return n, err
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/agent/ -v -timeout 20m`
Expected: `--- PASS: TestPickFollowsAScryAnswer`, `--- PASS: TestAgentAnswersErrorsAndKeepsReading` and `--- PASS: TestAgentDecodesCanonicalizedPayload` (no `halted`, fallbacks at most 2% of steps).

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/agent engines/gorge/cmd/spellbench-gorge-agent && git commit -m "gorge adapter: Go agent serving gorge's default and lethal-pressure bots"
```

---

### Task 27: Environment-role golden transcripts

**Files:**
- Create: `internal/server/golden_test.go`
- Create: `testdata/goldens/*.transcript.jsonl`, `testdata/goldens/digests.json` (generated)

**Interfaces:**
- Consumes: `server`, `minihost`, `catalog`, `validate`, `observe`.
- Produces:
  - goldens in the spec's transcript format, `{"dir": "host_to_engine" | "engine_to_host" | "host_to_agent" | "agent_to_host", "message": {...}}` per line. A request line that is not JSON at all (the `malformed_json` scenario) is stored as the string `raw`, since `message` must be an object;
  - `TestGoldensReplayByteExact`, which replays the `host_to_engine` lines into a fresh server, compares every `engine_to_host` line byte for byte, and recomputes each game scenario's Section 11.8 digest against `digests.json`;
  - `-update` regenerates the files.

Scenarios:
- `hello`;
- `reset_first_decision_<deck>` for the five decks;
- `uniform_game_burn` (Uniform agents, `max_steps` 300, full transcript with agent traffic);
- one file per error code: `malformed_json`, `malformed_request`, `protocol_mismatch`, `request_id_reuse_mismatch`, `step_before_reset`, `game_already_active`, `game_id_mismatch`, `expected_step_mismatch`, `candidate_id_out_of_range`, `semantic_echo_mismatch`, `unsupported_format`, `unsupported_deck`, `deck_id_mismatch`, `unsupported_rule`, `unsupported_request`, `game_already_terminal`;
- `arrangement`, `attack_declaration`, `order_pick` and `mana_payment`: the first seeded Uniform game (seeds 0 to 19, every deck) whose decisions reach that shape, replayed with `max_steps` ending right after that group, since a cap never splits a group. An arrangement or order block must have at least three substeps, so a scry 1 or a one-card bottom block never stands in for a full group, and the order block is one outside an arrangement, so the two goldens differ.

Every scenario resets without `x_gorge_view_v1`: its payload carries gorge cost strings compiled from Forge scripts, which this module never ships.

27 transcripts in all, plus `digests.json` with the game scenarios' digests.

`probe_refused` is not reachable, because this engine answers `unsupported_request` for every probe; the list records that.

- [ ] **Step 1: Write the failing test**

`internal/server/golden_test.go`:

```go
package server_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

var update = flag.Bool("update", false, "regenerate goldens")

// record is one transcript line. A request that is not JSON at all
// (malformed_json) is kept as the string raw, since message must be an object.
type record struct {
	Dir     string          `json:"dir"`
	Message json.RawMessage `json:"message,omitempty"`
	Raw     string          `json:"raw,omitempty"`
}

func TestGoldensReplayByteExact(t *testing.T) {
	dir := filepath.Join("..", "..", "testdata", "goldens")
	if *update {
		if err := writeGoldens(t, dir); err != nil {
			t.Fatal(err)
		}
	}
	files, _ := filepath.Glob(filepath.Join(dir, "*.transcript.jsonl"))
	if len(files) < 27 {
		t.Fatalf("%d golden files, want at least 27", len(files))
	}
	var digests map[string]string
	if b, err := os.ReadFile(filepath.Join(dir, "digests.json")); err != nil || json.Unmarshal(b, &digests) != nil || len(digests) != 5 {
		t.Fatalf("digests.json: %v, %d entries, want 5", err, len(digests))
	}
	for _, f := range files {
		s := server.New(testcorpus.Registry(t), nil)
		fh, err := os.Open(f)
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(fh)
		sc.Buffer(make([]byte, 1<<20), 9<<20)
		var last []byte
		var dig *wire.GameDigest // Section 11.8 over the engine lines, from the reset on
		for sc.Scan() {
			var r record
			if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
				t.Fatalf("%s: %v", f, err)
			}
			switch {
			case r.Dir == "host_to_engine" && r.Raw != "":
				last = s.Handle([]byte(r.Raw))
			case r.Dir == "host_to_engine":
				last = s.Handle(r.Message)
			case r.Dir == "engine_to_host" && string(last) != string(r.Message):
				t.Fatalf("%s: engine response differs:\n got %s\nwant %s", filepath.Base(f), last, r.Message)
			}
			if (r.Dir == "host_to_engine" || r.Dir == "engine_to_host") && r.Raw == "" {
				msg, err := wire.WithoutRequestID(r.Message)
				switch {
				case err != nil:
					t.Fatalf("%s: %v", f, err)
				case dig == nil:
					dig, err = wire.NewGameDigest(msg)
				default:
					err = dig.Chain(msg)
				}
				if err != nil {
					t.Fatalf("%s: %v", f, err)
				}
			}
		}
		fh.Close()
		name := strings.TrimSuffix(filepath.Base(f), ".transcript.jsonl")
		if want, ok := digests[name]; ok && (dig == nil || dig.String() != want) {
			t.Fatalf("%s: replayed digest %v, digests.json has %s", name, dig, want)
		}
	}
}

func writeTranscript(path string, recs []record) error {
	var b bytes.Buffer
	enc := json.NewEncoder(&b) // one compact line per record, no HTML escaping
	enc.SetEscapeHTML(false)
	for _, r := range recs {
		if err := enc.Encode(r); err != nil {
			return err
		}
	}
	return os.WriteFile(path, b.Bytes(), 0o644)
}

// recorder wraps a link and appends both directions of every exchange.
type recorder struct {
	inner    minihost.Link
	to, from string
	recs     *[]record
}

func (r *recorder) Round(req []byte) ([]byte, error) {
	out, err := r.inner.Round(req)
	*r.recs = append(*r.recs, record{Dir: r.to, Message: req}, record{Dir: r.from, Message: out})
	return out, err
}

func playRecorded(reg *cards.Registry, i uint64, deck catalog.Deck, maxSteps uint64) ([]record, minihost.Result, error) {
	var recs []record
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	h := &minihost.Host{RunSecret: make([]byte, 32),
		Engine:   &recorder{inner: &minihost.EngineLink{S: server.New(reg, nil)}, to: "host_to_engine", from: "engine_to_host", recs: &recs},
		Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
		MaxSteps: maxSteps, MaxDecisions: maxSteps}
	agents := [2]minihost.Link{
		&recorder{inner: &minihost.Uniform{}, to: "host_to_agent", from: "agent_to_host", recs: &recs},
		&recorder{inner: &minihost.Uniform{}, to: "host_to_agent", from: "agent_to_host", recs: &recs}}
	res, err := h.Play(i, deck, "london", []string{}, agents)
	return recs, res, err
}

// firstGroup finds the first engine decision containing needle, and not
// exclude when it is set, whose group has at least minSize substeps, and
// returns the step that group started at and its size.
func firstGroup(recs []record, needle, exclude string, minSize uint64) (start, size uint64, ok bool) {
	for _, r := range recs {
		msg := string(r.Message)
		if r.Dir != "engine_to_host" || !strings.Contains(msg, needle) || (exclude != "" && strings.Contains(msg, exclude)) {
			continue
		}
		var d struct {
			Step         uint64 `json:"step"`
			SeatDecision struct {
				Group struct {
					SubstepIndex uint64 `json:"substep_index"`
					SubstepCount uint64 `json:"substep_count"`
				} `json:"group"`
			} `json:"seat_decision"`
		}
		if json.Unmarshal(r.Message, &d) == nil && d.SeatDecision.Group.SubstepCount >= minSize {
			return d.Step - d.SeatDecision.Group.SubstepIndex, d.SeatDecision.Group.SubstepCount, true
		}
	}
	return 0, 0, false
}

func writeGoldens(t *testing.T, dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	reg := testcorpus.Registry(t)
	hello := []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}`)
	step := func(game string, exp, cand int, echo string) []byte {
		return []byte(fmt.Sprintf(`{"request_type":"step","protocol":"spellbench/v2","request_id":"s-1","game_id":%q,"expected_step":%d,"selection":{"candidate_id":%d,"semantic_echo":%s}}`, game, exp, cand, echo))
	}
	// Goldens are generated without x_gorge_view_v1: its payload carries gorge
	// cost strings compiled from Forge scripts, which this module never ships.
	noExt := `"extensions":["x_gorge_view_v1"]=>"extensions":[]`
	burn := reset("r-1", "g-1", "Burn", noExt)
	pass := `{"kind":"pass"}`
	scenarios := []struct {
		name  string
		lines [][]byte
	}{
		{"hello", [][]byte{hello}},
		{"malformed_json", [][]byte{[]byte(`{"request_type":`)}},
		{"malformed_request", [][]byte{[]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1"}`)}},
		{"protocol_mismatch", [][]byte{[]byte(`{"request_type":"hello","protocol":"spellbench/v1","request_id":"h-1","protocol_minor":0}`)}},
		{"request_id_reuse_mismatch", [][]byte{hello, []byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":1}`)}},
		{"step_before_reset", [][]byte{step("g-1", 0, 0, pass)}},
		{"game_already_active", [][]byte{burn, reset("r-2", "g-2", "Burn", noExt)}},
		{"game_id_mismatch", [][]byte{burn, step("g-9", 0, 0, pass)}},
		{"expected_step_mismatch", [][]byte{burn, step("g-1", 5, 0, pass)}},
		{"candidate_id_out_of_range", [][]byte{burn, step("g-1", 0, 4095, pass)}},
		{"semantic_echo_mismatch", [][]byte{burn, step("g-1", 0, 0, `{"kind":"nonsense"}`)}},
		{"unsupported_format", [][]byte{reset("r-1", "g-1", "Burn", `"format":"pauper-bo1"=>"format":"modern-bo1"`)}},
		{"unsupported_deck", [][]byte{reset("r-1", "g-1", "Burn", `"catalog_id":"Burn"}}]=>"catalog_id":"Terror"}}]`)}},
		{"deck_id_mismatch", [][]byte{reset("r-1", "g-1", "Burn", `"deck_id":"sha256:=>"deck_id":"sha256:0`)}},
		{"unsupported_rule", [][]byte{reset("r-1", "g-1", "Burn", `"probe":false=>"probe":true`)}},
		{"unsupported_request", [][]byte{[]byte(`{"request_type":"probe_resample","protocol":"spellbench/v2","request_id":"p-1","game_id":"g-1","samples":4}`)}},
		{"game_already_terminal", [][]byte{reset("r-1", "g-1", "Burn", `"max_steps":100000=>"max_steps":0`), step("g-1", 0, 0, pass)}},
	}
	for _, d := range catalog.Decks() {
		scenarios = append(scenarios, struct {
			name  string
			lines [][]byte
		}{"reset_first_decision_" + strings.ToLower(d.CatalogID), [][]byte{reset("r-1", "g-1", d.CatalogID, noExt)}})
	}
	for _, sc := range scenarios {
		s := server.New(reg, nil)
		var recs []record
		for _, l := range sc.lines {
			in := record{Dir: "host_to_engine", Message: l}
			if !json.Valid(l) {
				in = record{Dir: "host_to_engine", Raw: string(l)}
			}
			recs = append(recs, in, record{Dir: "engine_to_host", Message: s.Handle(l)})
		}
		if err := writeTranscript(filepath.Join(dir, sc.name+".transcript.jsonl"), recs); err != nil {
			return err
		}
	}
	// Game scenarios: whole host, engine and agent exchanges of seeded Uniform games.
	digests := map[string]string{}
	burnDeck, _ := catalog.ByID("Burn")
	recs, res, err := playRecorded(reg, 0, burnDeck, 300)
	if err != nil {
		return err
	}
	if err := writeTranscript(filepath.Join(dir, "uniform_game_burn.transcript.jsonl"), recs); err != nil {
		return err
	}
	digests["uniform_game_burn"] = res.Digest
	// Group shapes: the first seeded game that reaches each, cut by max_steps
	// right after that group (a cap never splits a group).
	// Arrangements and order blocks need three substeps or more, so a scry 1
	// or a one-card bottom block never stands in for a full group; an order
	// block is one outside an arrangement, so the two goldens differ.
	targets := []struct {
		name, needle, exclude string
		minSize               uint64
	}{
		{"arrangement", `"kind":"arrange_card"`, "", 3},
		{"attack_declaration", `"kind":"declare_attack"`, "", 1},
		{"order_pick", `"kind":"order_pick"`, `"purpose":"arrangement"`, 3},
		{"mana_payment", `"purpose":"mana_payment"`, "", 1},
	}
	for _, tg := range targets {
		found := false
		for i := uint64(0); i < 20 && !found; i++ {
			for _, d := range catalog.Decks() {
				full, _, err := playRecorded(reg, i, d, 3000)
				if err != nil {
					return err
				}
				start, size, ok := firstGroup(full, tg.needle, tg.exclude, tg.minSize)
				if !ok {
					continue
				}
				cut, res, err := playRecorded(reg, i, d, start+size)
				if err != nil {
					return err
				}
				if err := writeTranscript(filepath.Join(dir, tg.name+".transcript.jsonl"), cut); err != nil {
					return err
				}
				digests[tg.name] = res.Digest
				found = true
				break
			}
		}
		if !found {
			return fmt.Errorf("no seeded Uniform game reached %s", tg.name)
		}
	}
	b, _ := json.MarshalIndent(digests, "", "  ")
	return os.WriteFile(filepath.Join(dir, "digests.json"), append(b, '\n'), 0o644)
}
```

The transcripts are written with HTML escaping off, so each stored engine line is byte for byte what the server sent. The group-shape search plays up to 400 games once, at `-update` time only.

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/server/ -run Goldens`
Expected: FAIL with `0 golden files, want at least 27`.

- [ ] **Step 3: Generate the goldens**

Run: `go test ./internal/server/ -run Goldens -update`
Expected: PASS; `ls testdata/goldens | wc -l` prints 28 (27 transcripts and `digests.json`).

- [ ] **Step 4: Run test to verify it passes on replay**

Run: `go test ./internal/server/ -run Goldens -count=1 -v`
Expected: `--- PASS: TestGoldensReplayByteExact`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/server/golden_test.go engines/gorge/testdata/goldens && git commit -m "gorge adapter: environment-role golden transcripts replayed byte-exact"
```

---

### Task 28a: Qualification audits: resample self-check, leak scan, semantic consistency, realized commits

**Files:**
- Create: `internal/session/resample.go`, `internal/session/audit.go`, `internal/identity/clone.go`, `internal/xview/clone.go`, `internal/server/audit.go`
- Modify: `internal/session/session.go` (the declarations `Config`, `Game`, `advance`, `present`, `answer`), `internal/server/server.go` (the declarations `Server`, `reset`)
- Test: `internal/session/resample_test.go`, `internal/session/audit_test.go`

**Interfaces:**
- Consumes: `session.Game` (Task 22), `server.Server` (Task 23), `xview.Extender` and `xview.Follow` (Task 24), `identity.Tracker` (Task 10), `mapping.PrintedModes` (Task 18), `mapping.ManaSymbol` (Task 15).
- Produces:
  - `func (*session.Game) ResampleCheck(r *rand.Rand) error`;
  - `func (*identity.Tracker) CloneFor(e *rules.Engine) *Tracker`, `func (*xview.Extender) Clone() *Extender`, `func (*xview.Extender) Perm(seat state.PlayerID) []int`, `func (*xview.Extender) FollowOf(seat state.PlayerID, nativeKey string) (Follow, bool)`;
  - the audit: `session.Config.Audit`, `func session.LeakHits(sd []byte, hidden map[string]bool) int`, `type session.Realized struct{ Seat state.PlayerID; Native uint64; Kind decision.Kind; Intent decision.Intent; Followups map[string]decision.Intent }`, `func (*Game) Leaks() int`, `func (*Game) Inconsistent() int`, `func (*Game) Realized() []Realized`;
  - `func (*server.Server) SetAudit(on bool)`, `Leaks() int`, `Inconsistent() int`, `Realized() []session.Realized`, `ResampleCheck(r *rand.Rand) error`.

Audits (Task 28b's runner turns them on and reports them):
1. **Resample self-check.** It stands in for the reserved Section 9.7 probe and does not change the fairness label. It runs only at a transaction's first pose, the only one built from the current engine state: the session sets `fresh` when `advance` begins a transaction and clears it in `answer`. A later pose (a follow-up group such as the kicker `optional_cost`, the next pick of a variable selection, a later substep) carries answers a clone never saw, so its substep index proves nothing (G2-8). The check:
   - clones the engine, the identity tracker and the extension's id tables;
   - permutes every library except the positions the pose's `known` entries give and the cards the native decision offers;
   - swaps each unpinned card of the other seat's hand with a random card of that seat's library, unless the seat is looking at that whole library (a search);
   - rebuilds the whole `seat_decision`, including `x_gorge_view_v1`, and requires canonical byte equality.
2. **Leak scan:** every string in a seat decision (the extension included; `choose_name` candidates skipped, their domain is public) is checked against the names of cards the seat cannot see. Those are the cards in the other seat's hand, in libraries or face down, minus every name the seat can see anywhere and every name the decision itself carries in public records: zone records, stack entries of either kind (an ability names its source even after the source went into a library, as Lembas's does), pending-trigger names and `known` (G2-9). A hit is investigated, never whitelisted without the controller.
3. **Semantic consistency:** each answered candidate must describe the native option its op commits: the object it names (by v2 id when the seat sees it, else by name, zone and owner), a mana candidate's `ability_index` and `mana_choice`, a mode's `mode_index`, a number's `value`, an attack's defender and a block's attacker. It catches wrong numbering (G2-10, G2-11, G2-19) that parity alone cannot see (G2-14).
4. **Realized commits:** for every completed native decision the session records its commits in the numbering the seat's agent saw: the native decision's intent renumbered by `Perm`, and each later intent under the payload key of the follow-up it answered, renumbered by that follow-up's permutation. A folded intent (Seq 0) answers the follow-up its op's key chain names; an intent carrying its own Seq (dig's bottom order) answers the pose follow-up with that Seq (G2-14).

- [ ] **Step 1: Write the failing tests**

`internal/session/resample_test.go`:

```go
package session_test

import (
	"math/rand/v2"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func TestResamplingHiddenStateNeverChangesTheSeatDecision(t *testing.T) {
	for _, deck := range []string{"Wildfire", "Rally", "Spy", "Burn", "CawGates"} {
		g := start(t, deck, 2000)
		r := rand.New(rand.NewPCG(1, 2))
		for n := 0; n < 400; n++ {
			dec, term := g.Pending()
			if term != nil {
				if term.Classification == "halted" {
					t.Fatalf("%s halted: %s", deck, term.Reason)
				}
				break
			}
			if n%7 == 0 {
				if err := g.ResampleCheck(r); err != nil {
					t.Fatalf("%s step %d: %v", deck, dec.Step, err)
				}
			}
			k := r.IntN(len(dec.SeatDecision.Candidates))
			if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: uint64(k),
				Echo: echo(t, dec.SeatDecision.Candidates[k].Semantic)}); perr != nil {
				t.Fatal(perr)
			}
		}
	}
}
```

`internal/session/audit_test.go`:

```go
package session_test

import (
	"testing"

	"github.com/adams-shaun/gorge/cards"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/secrets"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

func TestLeakScanCountsAPlantedName(t *testing.T) {
	hidden := map[string]bool{"Lightning Bolt": true}
	clean := []byte(`{"observation":{"players":[{"hand":[{"card_name":"Mountain"}]}]},` +
		`"candidates":[{"semantic":{"kind":"choose_name","purpose":"card_name","value":"Lightning Bolt"}}],` +
		`"extensions":{"x_gorge_view_v1":{"view":{"label":"Lightning Bolt deals 3"}}}}`)
	if n := session.LeakHits(clean, hidden); n != 0 {
		t.Fatalf("clean decision scored %d", n)
	}
	planted := []byte(`{"observation":{"players":[{"hand":[{"card_name":"Mountain"}]}]},` +
		`"extensions":{"x_gorge_view_v1":{"view":{"players":[{"hand":[{"name":"Lightning Bolt"}]}]}}}}`)
	if n := session.LeakHits(planted, hidden); n != 1 {
		t.Fatalf("planted leak scored %d, want 1", n)
	}
}

func TestAuditedGameHasNoLeaksAndRecordsIntents(t *testing.T) {
	reg := testcorpus.Registry(t)
	d, _ := catalog.ByID("CawGates")
	cs, err := catalog.Resolve(reg, d)
	if err != nil {
		t.Fatal(err)
	}
	seat := "p0"
	req := &protocol.ResetReq{GameID: "g-a", Format: "pauper-bo1", MaxDecisions: 100000, MaxSteps: 3000,
		Rules: protocol.Rules{Mulligan: "london", StartingPlayer: "host_assigned", StartingSeat: &seat, Names: catalog.PoolNames()}}
	g, err := session.Start(session.Config{Reg: reg, Ext: xview.New(), Audit: true}, "g-a", req,
		secrets.NewGame(make([]byte, 32)), [2][]*cards.Card{cs, cs})
	if err != nil {
		t.Fatal(err)
	}
	for {
		dec, term := g.Pending()
		if term != nil {
			if term.Classification == "halted" {
				t.Fatalf("halted: %s", term.Reason)
			}
			break
		}
		c := dec.SeatDecision.Candidates[len(dec.SeatDecision.Candidates)-1] // the last candidate acts more than pass does
		if perr := g.Step(&protocol.StepReq{GameID: "g-a", ExpectedStep: dec.Step, CandidateID: uint64(c.CandidateID),
			Echo: echo(t, c.Semantic)}); perr != nil {
			t.Fatal(perr)
		}
	}
	if g.Leaks() != 0 || g.Inconsistent() != 0 {
		t.Fatalf("%d leak-scan hits, %d inconsistent candidates", g.Leaks(), g.Inconsistent())
	}
	if len(g.Realized()) == 0 {
		t.Fatal("no realized intents recorded")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/session/ -run 'Resampling|Leak|Audited'`
Expected: FAIL with `g.ResampleCheck undefined` and `undefined: session.LeakHits`.

- [ ] **Step 3: Write minimal implementation**

`internal/identity/clone.go`:

```go
package identity

import (
	"maps"

	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
)

// CloneFor copies the tracker for a clone of the game (the resample
// self-check): the same move and look counters, open looks, minted ids and
// recorded reference keys, with the shadow re-pointed at e. The copy only
// mints; it never syncs.
func (t *Tracker) CloneFor(e *rules.Engine) *Tracker {
	c := &Tracker{sec: t.sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: maps.Clone(t.moves), looks: maps.Clone(t.looks),
		sourceKeys: maps.Clone(t.sourceKeys), targetKeys: map[state.ObjID][]chosen{},
		attackKeys: maps.Clone(t.attackKeys), blockKeys: maps.Clone(t.blockKeys), before: map[state.ObjID]uint32{}}
	for id, ks := range t.targetKeys {
		c.targetKeys[id] = append([]chosen(nil), ks...)
	}
	for v := range t.open {
		c.open[v] = maps.Clone(t.open[v]) // a nil map (no open look) stays nil
		c.seen[v] = maps.Clone(t.seen[v])
	}
	return c
}
```

`internal/xview/clone.go`:

```go
package xview

import (
	"maps"
	"slices"

	"github.com/adams-shaun/gorge/state"
)

// Clone copies the per-seat id tables, so a rebuilt payload numbers ids
// exactly as the real one did.
func (x *Extender) Clone() *Extender {
	c := &Extender{}
	for s, t := range x.tables {
		c.tables[s] = &table{ints: maps.Clone(t.ints), next: t.next}
		c.last[s] = slices.Clone(x.last[s])
		c.lastFollow[s] = maps.Clone(x.lastFollow[s])
	}
	return c
}

// Perm is the native -> payload option renumbering of the seat's last
// payload. The audit reads it; no agent ever receives it.
func (x *Extender) Perm(seat state.PlayerID) []int { return x.last[seat] }

// FollowOf is the payload key and renumbering of the folded follow-up the
// seat's last payload keyed nativeKey natively (audit only).
func (x *Extender) FollowOf(seat state.PlayerID, nativeKey string) (Follow, bool) {
	f, ok := x.lastFollow[seat][nativeKey]
	return f, ok
}
```

`internal/session/resample.go`:

```go
package session

import (
	"bytes"
	"errors"
	"fmt"
	"maps"
	"math/rand/v2"

	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gamecfg"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

var ErrResample = errors.New("noninterference self-check failed")

// ResampleCheck rebuilds the pending seat decision from a clone whose hidden
// state was redrawn and requires byte equality with the real one.
func (s *Game) ResampleCheck(r *rand.Rand) error {
	// Only a transaction's first pose was built from this very state; every
	// later one (a follow-up group, the next pick of a variable selection, the
	// substeps of a group) carries answers the clone never saw.
	if s.resp == nil || s.native == nil || s.pose == nil || !s.fresh {
		return nil
	}
	seat := s.pose.Seat
	other := 1 - seat
	c := s.g.E.Clone()
	pinned := map[state.ObjID]bool{} // cards whose place the seat knows
	for _, o := range s.native.Options {
		pinned[o.Obj] = true
	}
	var wholeLook [2]bool
	for _, k := range s.pose.Known {
		if k.Zone != "library" {
			continue
		}
		p := state.PlayerID(0)
		if k.OwnerSeat == "p1" {
			p = 1
		}
		lib := c.G.Zone(state.ZLibrary, p)
		switch {
		case k.PositionFromTop == nil:
			wholeLook[p] = true
		case int(*k.PositionFromTop) < len(lib):
			pinned[lib[*k.PositionFromTop]] = true
		}
	}
	for p := state.PlayerID(0); p < 2; p++ {
		lib := append([]state.ObjID(nil), c.G.Zone(state.ZLibrary, p)...)
		var free []int
		for i, id := range lib {
			if !pinned[id] {
				free = append(free, i)
			}
		}
		for i := len(free) - 1; i > 0; i-- {
			j := r.IntN(i + 1)
			lib[free[i]], lib[free[j]] = lib[free[j]], lib[free[i]]
		}
		c.G.SetZone(state.ZLibrary, p, lib)
	}
	if !wholeLook[other] {
		hand := append([]state.ObjID(nil), c.G.Zone(state.ZHand, other)...)
		lib := append([]state.ObjID(nil), c.G.Zone(state.ZLibrary, other)...)
		for i := range hand {
			if len(lib) == 0 || pinned[hand[i]] {
				continue
			}
			j := r.IntN(len(lib))
			if pinned[lib[j]] {
				continue
			}
			hand[i], lib[j] = lib[j], hand[i]
			c.G.Obj(hand[i]).Zone, c.G.Obj(lib[j]).Zone = state.ZHand, state.ZLibrary
		}
		c.G.SetZone(state.ZHand, other, hand)
		c.G.SetZone(state.ZLibrary, other, lib)
	}
	g := &gamecfg.Game{E: c, Secret: s.g.Secret}
	tr := s.env.IDs.CloneFor(c)
	env := &mapping.Env{G: g, IDs: tr, Obs: &observe.Projector{E: c, IDs: tr, Mulls: s.env.Obs.Mulls},
		Action: s.env.Action, Domain: s.env.Domain, Slots: maps.Clone(s.env.Slots), Looking: s.env.Looking}
	twin := &Game{ID: s.ID, cfg: s.cfg, g: g, env: env, step: s.step, decisions: s.decisions,
		seatStep: s.seatStep, groupID: s.groupID, nativeCount: s.nativeCount, maxSteps: s.maxSteps, maxDecisions: s.maxDecisions}
	if x, ok := s.cfg.Ext.(*xview.Extender); ok {
		twin.cfg.Ext = x.Clone()
	}
	twin.cfg.Audit = false
	d := c.Pending()
	tx, err := mapping.Begin(env, d)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrResample, err)
	}
	twin.tx, twin.native = tx, d
	p, err := tx.Pose()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrResample, err)
	}
	if err := twin.present(p); err != nil {
		return fmt.Errorf("%w: %v", ErrResample, err)
	}
	a, _ := wire.Canonical(s.resp.SeatDecision)
	b, _ := wire.Canonical(twin.resp.SeatDecision)
	if !bytes.Equal(a, b) {
		return fmt.Errorf("%w at step %d", ErrResample, s.step)
	}
	return nil
}
```

The real pose already opened any look and numbered its ids, so the copied tracker, `Looking` flags and id tables make the twin mint the same ids. The twin never submits, so its shadow never syncs.

`internal/session/audit.go`:

```go
package session

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

// Realized is a completed native decision as the engine committed it, in
// the numbering the seat's x_gorge_view_v1 showed: the native decision's
// intent, and each folded follow-up's under its payload key (Task 28b's
// parity audit compares both with the agent's plan).
type Realized struct {
	Seat      state.PlayerID
	Native    uint64
	Kind      decision.Kind
	Intent    decision.Intent
	Followups map[string]decision.Intent
}

func (s *Game) Leaks() int { return s.leaks }

func (s *Game) Realized() []Realized { return s.realized }

// Inconsistent counts answered candidates whose semantic disagrees with the
// native option their op commits.
func (s *Game) Inconsistent() int { return s.inconsistent }

// LeakHits counts string values in a seat decision that name a card hidden
// from the seat. choose_name candidates are skipped: their domain is public.
func LeakHits(sd []byte, hidden map[string]bool) int {
	var v any
	if err := json.Unmarshal(sd, &v); err != nil {
		return 1 // an unreadable decision is never clean
	}
	hits := 0
	var walk func(any)
	walk = func(x any) {
		switch t := x.(type) {
		case string:
			if hidden[t] {
				hits++
			}
		case []any:
			for _, e := range t {
				walk(e)
			}
		case map[string]any:
			if t["kind"] == "choose_name" {
				return
			}
			for _, e := range t {
				walk(e)
			}
		}
	}
	walk(v)
	return hits
}

// hiddenNames lists the names of cards the seat cannot see (the other seat's
// hand, libraries, face-down cards), minus every name the seat can see: any
// visible card, and every name the decision's own observation carries in
// public records (zone records, stack entries of either kind, pending
// triggers) or in known. A stack ability names its source even after the
// source went into a library (Lembas), and that name is public.
func (s *Game) hiddenNames(seat state.PlayerID, obs protocol.Observation) map[string]bool {
	g := s.g.E.G
	hidden, seen := map[string]bool{}, map[string]bool{}
	for i := range g.Objs {
		o := &g.Objs[i]
		if o.Ability != nil || o.Face() == nil {
			continue
		}
		name := o.Face().Name
		switch {
		case observe.Visible(seat, o) && (!o.FaceDown || observe.MayLook(seat, o)):
			seen[name] = true
		case o.Zone == state.ZLibrary || o.Zone == state.ZHand || o.FaceDown:
			hidden[name] = true
		}
	}
	see := func(n *string) {
		if n != nil {
			seen[*n] = true
		}
	}
	for _, p := range obs.Players {
		for _, zone := range [][]protocol.ObjectRecord{p.Hand, p.Battlefield, p.Graveyard, p.Exile, p.Command} {
			for _, rec := range zone {
				see(rec.CardName)
			}
		}
	}
	for _, st := range obs.Stack {
		see(st.CardName)
	}
	for _, pt := range obs.PendingTriggers {
		see(pt.SourceName)
	}
	for _, k := range obs.Known {
		seen[k.CardName] = true
	}
	for n := range seen {
		delete(hidden, n)
	}
	return hidden
}

// realize records a completed native decision's commits in the numbering
// the seat's agent saw: commit[0] in the native decision's payload order,
// and each later intent under the payload key of the follow-up it answered,
// in that follow-up's order. A folded intent (Seq 0) answers the follow-up
// its op's key chain names; one carrying its own Seq (dig's bottom order)
// answers the pose follow-up with that Seq.
func (s *Game) realize(seat state.PlayerID, p *mapping.Pose, op mapping.NativeOp, commit []decision.Intent) {
	x, _ := s.cfg.Ext.(*xview.Extender)
	renum := func(perm []int, in decision.Intent) decision.Intent {
		m := func(xs []int) []int {
			out := make([]int, len(xs))
			for i, v := range xs {
				out[i] = v
				if v >= 0 && v < len(perm) {
					out[i] = perm[v]
				}
			}
			return out
		}
		return decision.Intent{Choices: m(in.Choices), Rest: m(in.Rest)}
	}
	var perm []int
	if x != nil {
		perm = x.Perm(seat)
	}
	r := Realized{Seat: seat, Native: s.nativeCount[seat], Kind: s.native.Kind, Intent: renum(perm, commit[0]),
		Followups: map[string]decision.Intent{}}
	keys := followKeys(op)
	for k, in := range commit[1:] {
		native := ""
		if in.Seq == 0 && k < len(keys) {
			native = keys[k]
		} else {
			for key, fd := range p.Followups {
				if fd.Seq == in.Seq {
					native = key
				}
			}
		}
		if x == nil {
			continue
		}
		if f, ok := x.FollowOf(seat, native); ok {
			r.Followups[f.Key] = renum(f.Perm, in)
		}
	}
	s.realized = append(s.realized, r)
}

// objectField names, per kind, the semantic field that references the
// object of the native option a choose, cast or list op commits.
var objectField = map[string]string{"play_land": "source", "cast_spell": "source", "activate_ability": "source",
	"activate_mana_ability": "source", "special_action": "source", "choose_target": "target",
	"choose_cost_target": "candidate", "select_object": "choice", "declare_attack": "attacker",
	"declare_block": "blocker", "order_pick": "item", "optional_cast": "card", "choose_replacement": "replacement_source"}

// checkConsistent is the semantic-consistency audit: an answered candidate
// must describe the native option its op commits.
func (s *Game) checkConsistent(p *mapping.Pose, c mapping.Cand) {
	if why := s.consistent(p, c); why != "" {
		s.inconsistent++
		fmt.Fprintf(os.Stderr, "gorge audit: %s candidate disagrees with its native option: %s\n", c.Sem.Kind, why)
	}
}

// consistent returns what differs, or "": the object the semantic names is
// the option's object (by v2 id when the seat sees it, else by name, zone
// and owner); a mana candidate's ability_index and mana_choice are its folded
// options'; a mode's mode_index is the option's printed mode; a number's
// value is the option's amount; an attack's defender and a block's attacker
// are the option's.
func (s *Game) consistent(p *mapping.Pose, c mapping.Cand) string {
	op, d, idx := c.Op, p.Native, c.Op.Option
	switch op.Op {
	case "cast":
		if len(op.Covers) == 0 {
			return "a cast op covers no option"
		}
		idx = op.Covers[0]
	case "choose":
	case "list":
		if key, ok := strings.CutPrefix(op.List, "followup:"); ok {
			d = p.Followups[key]
		}
	case "dest":
		if idx < 0 {
			return "" // a looked-at card with no native option
		}
	default:
		return "" // none, finish: no native option
	}
	if d == nil || idx < 0 || idx >= len(d.Options) {
		return fmt.Sprintf("option %d is not offered", idx)
	}
	o := d.Options[idx]
	var sem map[string]any
	b, _ := json.Marshal(c.Sem)
	json.Unmarshal(b, &sem)
	if f := objectField[c.Sem.Kind]; f != "" {
		if why := s.sameObject(p.Seat, sem[f], o.Obj, o.Player, o.Kind == "player"); why != "" {
			return why
		}
	}
	switch c.Sem.Kind {
	case "arrange_card":
		if op.Op == "dest" {
			return s.sameObject(p.Seat, sem["card"], o.Obj, 0, false)
		}
	case "declare_attack":
		if o.Battle != 0 {
			return s.sameObject(p.Seat, sem["defender"], o.Battle, 0, false)
		}
		return s.sameObject(p.Seat, sem["defender"], 0, o.Player, true)
	case "declare_block":
		return s.sameObject(p.Seat, sem["attacker"], o.Attacker, 0, false)
	case "choose_spell_mode":
		index, _, err := mapping.PrintedModes(d)
		if err != nil || fmt.Sprint(sem["mode_index"]) != fmt.Sprint(index[idx]) {
			return fmt.Sprintf("mode_index %v for option %d", sem["mode_index"], idx)
		}
	case "choose_number":
		if fmt.Sprint(sem["value"]) != strconv.Itoa(o.Amount) {
			return fmt.Sprintf("value %v, option amount %d", sem["value"], o.Amount)
		}
	case "activate_mana_ability":
		keys := followKeys(op)
		if len(keys) == 0 {
			return ""
		}
		first, last := p.Followups[keys[0]], p.Followups[keys[len(keys)-1]]
		if first == nil || last == nil {
			return "a folded follow-up is missing"
		}
		f0, fl := first.Options[op.Followup[0]], last.Options[op.Followup[len(op.Followup)-1]]
		if f0.Kind == "mana" && fmt.Sprint(sem["ability_index"]) != strconv.Itoa(f0.Ability) {
			return fmt.Sprintf("ability_index %v, folded ability %d", sem["ability_index"], f0.Ability)
		}
		if sym, ok := mapping.ManaSymbol(fl); ok && sem["mana_choice"] != sym {
			return fmt.Sprintf("mana_choice %v, folded %s", sem["mana_choice"], sym)
		}
	}
	return ""
}

// sameObject reports why ref (an object reference, a target reference or an
// order item, as generic JSON) does not name the native object obj, or the
// seat player when isPlayer.
func (s *Game) sameObject(seat state.PlayerID, ref any, obj state.ObjID, player state.PlayerID, isPlayer bool) string {
	m, _ := ref.(map[string]any)
	if inner, ok := m["object"].(map[string]any); ok {
		m = inner
	}
	if pl, ok := m["player"].(string); ok || isPlayer {
		if !isPlayer || pl != observe.Seat(player) {
			return fmt.Sprintf("player %v, option %s", m["player"], observe.Seat(player))
		}
		return ""
	}
	o := s.g.E.G.Obj(obj)
	switch {
	case obj == 0 || m["trigger"] != nil:
		return "" // no native object to compare, or a trigger item
	case o == nil:
		return fmt.Sprintf("option object %d is gone", obj)
	case m == nil:
		if observe.Visible(seat, o) {
			return fmt.Sprintf("a null reference to visible object %d", obj)
		}
		return ""
	case observe.Visible(seat, o):
		want, err := s.env.IDs.VisibleID(seat, obj)
		if err != nil || m["object_id"] != want {
			return fmt.Sprintf("names %v, the option is %s", m["object_id"], want)
		}
	case m["card_name"] != o.Face().Name || m["zone"] != o.Zone.String() || m["owner_seat"] != observe.Seat(o.Owner):
		// a hidden card shown by a look: compare what its look id stands for
		return fmt.Sprintf("names %v in %v, the option is %s in %s", m["card_name"], m["zone"], o.Face().Name, o.Zone)
	}
	return ""
}
```

Then change the session: `Config` gains `Audit`; `Game` gains `leaks`, `inconsistent`, `realized` and `fresh`; `advance` sets `fresh` when it begins a transaction; `present` runs the leak scan once the extensions are attached; `answer` clears `fresh`, runs the consistency check before the transaction's `Answer`, and records the realized commits when the transaction completes, before the next decision is posed (which would overwrite the extension's permutations).

Replace or add these declarations in `internal/session/session.go`:

```go
type Config struct {
	Reg        *cards.Registry
	Provenance protocol.Provenance
	Ext        Extender
	Audit      bool // qualification only: leak scan and realized intents
}

type Game struct {
	ID                     string
	cfg                    Config
	g                      *gamecfg.Game
	env                    *mapping.Env
	tx                     mapping.Transaction
	native                 *decision.Decision
	pose                   *mapping.Pose
	resp                   *protocol.DecisionResponse
	term                   *protocol.TerminalResponse
	step, decisions        uint64
	seatStep, groupID      [2]uint64
	nativeCount            [2]uint64
	maxSteps, maxDecisions uint64
	leaks, inconsistent    int
	realized               []Realized
	fresh                  bool // the pending pose is its transaction's first
}

func (s *Game) advance() {
	defer s.recoverPanic()
	for s.term == nil {
		if s.tx == nil {
			e := s.g.E
			if e.G.Over {
				s.natural()
				return
			}
			d := e.Pending()
			if d == nil {
				s.halt("no_pending_decision")
				return
			}
			if in, ok, err := mapping.Internal(s.env, d); ok || err != nil {
				if err == nil {
					err = s.submit(in, nil)
				}
				if err != nil {
					s.halt(cause(err, "submit_rejected"))
					return
				}
				continue
			}
			if d.Kind == decision.KPriority {
				s.env.Action, s.env.Slots = nil, map[string]uint32{}
			}
			tx, err := mapping.Begin(s.env, d)
			if err != nil {
				s.halt(cause(err, "unmapped_decision"))
				return
			}
			s.tx, s.native = tx, d
			s.nativeCount[d.Player]++
			s.fresh = true
		}
		p, err := s.tx.Pose()
		if err != nil {
			s.halt(cause(err, "dead_end"))
			return
		}
		if p.GroupStart {
			if s.decisions >= s.maxDecisions {
				s.truncate("max_decisions")
				return
			}
			if s.step+uint64(p.SubstepCount) > s.maxSteps {
				s.truncate("max_steps")
				return
			}
		}
		if err := s.present(p); err != nil {
			s.halt(cause(err, "projection"))
		}
		return
	}
}

func (s *Game) present(p *mapping.Pose) error {
	var holder *state.PlayerID
	if p.Context.Kind == "priority" || (s.env.Action != nil && s.env.Action.Seat == p.Seat) {
		h := p.Seat
		holder = &h
	}
	known := append([]protocol.Known(nil), p.Known...)
	observe.SortKnown(known)
	obs, err := s.env.Obs.Observation(p.Seat, observe.State{PriorityHolder: holder, Known: known})
	if err != nil {
		return err
	}
	sd := protocol.SeatDecision{ActingSeat: observe.Seat(p.Seat), SeatStep: s.seatStep[p.Seat],
		Group:   protocol.Group{GroupID: s.groupID[p.Seat], SubstepIndex: p.SubstepIndex, SubstepCount: p.SubstepCount},
		Context: p.Context, Observation: obs, Extensions: map[string]json.RawMessage{}}
	for i, c := range p.Candidates {
		sd.Candidates = append(sd.Candidates, protocol.Candidate{CandidateID: uint32(i), Semantic: c.Sem})
	}
	if s.cfg.Ext != nil {
		ext, err := s.cfg.Ext.Extend(s.env, p, s.nativeCount[p.Seat])
		if err != nil {
			return err
		}
		sd.Extensions = ext
	}
	if s.cfg.Audit {
		b, err := json.Marshal(sd)
		if err != nil {
			return err
		}
		s.leaks += LeakHits(b, s.hiddenNames(p.Seat, obs))
	}
	s.pose = p
	s.resp = &protocol.DecisionResponse{ResponseType: "decision", Protocol: protocol.Name, GameID: s.ID, Step: s.step,
		SeatDecision: sd, Provenance: s.cfg.Provenance}
	return nil
}

func (s *Game) answer(i int) {
	defer s.recoverPanic()
	p := s.pose
	seat := p.Seat
	op := p.Candidates[i].Op
	s.fresh = false
	if s.cfg.Audit {
		s.checkConsistent(p, p.Candidates[i])
	}
	if p.Context.Kind == "priority" {
		if obj := s.actionObject(op); obj != 0 {
			s.env.Action = &mapping.ActionContext{Seat: seat, Obj: obj, Since: s.g.E.G.NextID}
		}
	}
	commit, done, err := s.tx.Answer(i)
	s.step++
	s.seatStep[seat]++
	if p.SubstepIndex+1 == p.SubstepCount {
		s.groupID[seat]++
		s.decisions++
	}
	if err != nil {
		s.halt(cause(err, "dead_end"))
		return
	}
	keys := followKeys(op)
	for k, in := range commit {
		var want *decision.Decision
		if k > 0 && in.Seq == 0 && k-1 < len(keys) {
			want = p.Followups[keys[k-1]]
		}
		if err := s.submit(in, want); err != nil {
			s.halt(cause(err, "submit_rejected"))
			return
		}
	}
	if done {
		if s.cfg.Audit && len(commit) > 0 {
			s.realize(seat, p, op, commit) // commit[0] always answers the transaction's own native decision
		}
		s.tx = nil
		s.env.CloseLooks()
	}
	s.advance()
}
```

Give the server the audit switch: `Server` gains `audit`, and `reset` passes it on.

Replace or add these declarations in `internal/server/server.go`:

```go
type Server struct {
	reg     *cards.Registry
	engine  protocol.Engine
	game    *session.Game
	gameIDs map[string]bool
	// cache holds every response since the last accepted reset, by request
	// id (Section 4.1): an identical retransmission of any of them returns
	// its bytes, a changed payload is request_id_reuse_mismatch. Clearing it
	// at each accepted reset bounds it by one game's traffic.
	cache map[string]cached
	audit bool
}

func (s *Server) reset(req protocol.Request) []byte {
	r := req.Reset
	switch {
	case s.game != nil && !terminal(s.game):
		return errResp(req.ID, protocol.Errf(protocol.CodeGameAlreadyActive, "a game is active"))
	case s.gameIDs[r.GameID]:
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "game_id reused"))
	case r.Format != "pauper-bo1":
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedFormat, r.Format))
	}
	var decks [2][]*cards.Card
	for i, spec := range r.Decks {
		d, ok := catalog.ByID(spec.CatalogID)
		if spec.IsDecklist || !ok {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "only the engine catalog decks are playable"))
		}
		if spec.DeckID != d.DeckID() {
			return errResp(req.ID, protocol.Errf(protocol.CodeDeckIDMismatch, "deck_id does not match "+d.CatalogID))
		}
		cs, err := catalog.Resolve(s.reg, d)
		if err != nil {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, err.Error()))
		}
		decks[i] = cs
	}
	switch {
	case r.Rules.StartingPlayer != "host_assigned":
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "starting_player"))
	case r.Rules.Probe:
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "probe"))
	}
	if dom, err := wire.DomainID(r.Rules.Names); err != nil || dom != r.Rules.DomainID {
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "card_name_domain.domain_id does not hash its distinct names"))
	}
	for _, x := range r.Rules.Extensions {
		if x != "x_gorge_view_v1" {
			return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedRule, "extension "+x))
		}
	}
	sec, err := secrets.ParseGame(r.GameSecret)
	if err != nil {
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, err.Error()))
	}
	cfg := session.Config{Reg: s.reg, Provenance: provenance(s.engine), Audit: s.audit}
	if slices.Contains(r.Rules.Extensions, "x_gorge_view_v1") {
		cfg.Ext = xview.New()
	}
	g, err := session.Start(cfg, r.GameID, r, sec, decks)
	if err != nil {
		return errResp(req.ID, protocol.Errf(protocol.CodeUnsupportedDeck, "engine could not start: "+err.Error()))
	}
	s.game = g
	s.gameIDs[r.GameID] = true
	return s.respond(req.ID, g)
}
```

`internal/server/audit.go`:

```go
package server

import (
	"math/rand/v2"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
)

// SetAudit turns the qualification audit on for games reset afterwards.
func (s *Server) SetAudit(on bool) { s.audit = on }

// Leaks, Inconsistent, Realized and ResampleCheck report on the current game.
func (s *Server) Leaks() int {
	if s.game == nil {
		return 0
	}
	return s.game.Leaks()
}

func (s *Server) Inconsistent() int {
	if s.game == nil {
		return 0
	}
	return s.game.Inconsistent()
}

func (s *Server) Realized() []session.Realized {
	if s.game == nil {
		return nil
	}
	return s.game.Realized()
}

func (s *Server) ResampleCheck(r *rand.Rand) error {
	if s.game == nil {
		return nil
	}
	return s.game.ResampleCheck(r)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./internal/session/ -run 'Resampling|Leak|Audited' -v -timeout 30m`
Expected: `--- PASS: TestResamplingHiddenStateNeverChangesTheSeatDecision`, `--- PASS: TestLeakScanCountsAPlantedName`, `--- PASS: TestAuditedGameHasNoLeaksAndRecordsIntents`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/session engines/gorge/internal/identity engines/gorge/internal/xview engines/gorge/internal/server && git commit -m "gorge adapter: qualification audits (resample self-check, leak scan, consistency, realized commits)"
```

---

### Task 28b: Qualification runner and runs: determinism, fairness, leaks, parity, throughput

**Files:**
- Create: `cmd/gorgequal/main.go`
- Test: `cmd/gorgequal/main_test.go`

**Interfaces:**
- Consumes: `minihost` (Task 25), `agent` (`Records`, `Forced`, `Fallbacks`, Task 26), the server's audit (Task 28a), `validate`, `catalog`.
- Produces:
  - the `gorgequal` command: `-games N`, `-resample K` (a check before every K-th step, 0 for none), `-workers W`, `-audit` (default true), `-out report.json`;
  - a report with per deck and pairing rows (halts, truncations, validator violations, rerun digest mismatches, resample checks and failures, leak-scan hits, inconsistent candidates, parity comparisons and mismatches, fallbacks, forced answers), per-deck gates with reasons, games per second, and Go memory (`runtime.MemStats.Sys`).

Checks:
1. **Determinism:** every game is played twice from the same run secret, once audited and once plain. The digests must match, which also shows the audit does not disturb the game.
2. **Validator:** the mini-host's validator subset checks every forwarded decision (Task 25).
3. **Resample self-check, leak scan and semantic consistency** (Task 28a): zero failures, hits and inconsistent candidates.
4. **Bot parity:** gorge's bot must play through the adapter exactly the moves it chose. Every realized native decision of an agent seat must equal the agent's `Record`: the top-level intent (attacker and blocker choices as sets, pile-B order only when the bot gave one) and every folded follow-up answer, such as a mana colour, a cost target, a trigger cost's pay or decline, or dig's bottom order (G2-14). Native decisions the agent answered forced or by fallback are not compared (G2-7). Native-versus-adapter game identity is not expected: per-seat ids and sorted hidden options change the bot's inputs by design (engine notes, Task 29).
5. **Forced and fallback gate:** per deck, the native decisions the gorge agents answered with a forced or fallback substep stay under 1% of all their native decisions, and the report lists the reasons (G2-14). Forced answers are reported per deck, apart from fallbacks.
6. **Throughput:** plain games per second, serially and with W workers, for Task 30's compute qualification.

- [ ] **Step 1: Write the failing test**

`cmd/gorgequal/main_test.go`:

```go
package main

import "testing"

func TestSmallQualificationIsClean(t *testing.T) {
	rep, err := qualify(options{games: 1, resample: 3, workers: 1, audit: true})
	if err != nil {
		t.Fatal(err)
	}
	if !rep.Clean() {
		t.Fatalf("qualification not clean: %+v %+v", rep.Totals, rep.Gates)
	}
	if rep.Totals.ResampleChecks == 0 || rep.Totals.ParityCompared == 0 {
		t.Fatalf("checks did not run: %+v", rep.Totals)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./cmd/gorgequal/`
Expected: FAIL with `undefined: qualify`.

- [ ] **Step 3: Write minimal implementation**

`cmd/gorgequal/main.go`:

```go
// Command gorgequal runs the adapter's qualification: games per deck and
// pairing through the mini-host, with determinism, validator, resample,
// leak, semantic-consistency, parity and throughput checks.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"maps"
	"math/rand/v2"
	"os"
	"runtime"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/adams-shaun/gorge/decision"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/agent"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/gorgepin"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/minihost"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/server"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/validate"
)

type options struct {
	games, resample, workers int
	audit                    bool
}

type Totals struct {
	Games, Halts, Truncations, Violations, DigestMismatch int
	ResampleChecks, ResampleFailures, LeakHits, Inconsistent int
	ParityCompared, ParityMismatch, Fallbacks, Forced        int
	GamesPerSecond                                           float64
	GoMemoryMB                                               uint64
}

// DeckGate counts, per deck, the native decisions the gorge agents answered
// and those with a forced or fallback substep, with their reasons. Parity
// never compares those decisions, so the gate bounds them instead.
type DeckGate struct {
	AgentNatives, ForcedNatives, FallbackNatives int
	Reasons                                      map[string]int
}

// Pass: forced plus fallback native decisions stay under 1% of the deck's
// agent native decisions.
func (g DeckGate) Pass() bool {
	return 100*(g.ForcedNatives+g.FallbackNatives) < g.AgentNatives || g.AgentNatives == 0
}

type Report struct {
	Totals Totals              `json:"totals"`
	Gates  map[string]DeckGate `json:"gates"`
	Rows   []map[string]any    `json:"rows"`
}

func (r Report) Clean() bool {
	t := r.Totals
	for _, g := range r.Gates {
		if !g.Pass() {
			return false
		}
	}
	return t.Games > 0 && t.Halts == 0 && t.Violations == 0 && t.DigestMismatch == 0 &&
		t.ResampleFailures == 0 && t.LeakHits == 0 && t.Inconsistent == 0 && t.ParityMismatch == 0
}

var pairings = []string{"uniform/uniform", "bot/uniform", "bot/lethal-pressure"}

// auditLink runs a resample check before every k-th step it forwards.
type auditLink struct {
	srv            *server.Server
	r              *rand.Rand
	every, n       int
	checks, failed int
}

func (a *auditLink) Round(req []byte) ([]byte, error) {
	if a.every > 0 && bytes.Contains(req, []byte(`"request_type":"step"`)) {
		if a.n++; a.n%a.every == 0 {
			a.checks++
			if err := a.srv.ResampleCheck(a.r); err != nil {
				fmt.Fprintln(os.Stderr, "gorgequal:", err)
				a.failed++
			}
		}
	}
	return a.srv.Handle(req), nil
}

func link(name string) minihost.Link {
	if name == "uniform" {
		return &minihost.Uniform{}
	}
	a, err := agent.New(name)
	if err != nil {
		panic(err)
	}
	return a
}

func sameIntent(k decision.Kind, got, want decision.Intent) bool {
	g, w := slices.Clone(got.Choices), slices.Clone(want.Choices)
	if k == decision.KAttackers || k == decision.KBlockers {
		slices.Sort(g)
		slices.Sort(w)
	}
	return slices.Equal(g, w) && (len(want.Rest) == 0 || slices.Equal(got.Rest, want.Rest))
}

// parity compares each realized native decision of an agent seat with the
// agent's record of it: the top-level intent and every folded follow-up
// answer. Decisions the agent answered forced or by fallback are skipped;
// the deck gate bounds them.
func parity(realized []session.Realized, seats [2]minihost.Link) (compared, mismatched int) {
	for _, r := range realized {
		a, ok := seats[r.Seat].(*agent.Server)
		if !ok {
			continue
		}
		rec := a.Records()[r.Native]
		if rec != nil && (rec.Forced > 0 || rec.Fallbacks > 0) {
			continue
		}
		compared++
		same := rec != nil && sameIntent(r.Kind, r.Intent, rec.Intent)
		for key, got := range r.Followups {
			if !same {
				break
			}
			want, ok := rec.Followups[key]
			same = ok && slices.Equal(got.Choices, want.Choices)
		}
		if !same {
			mismatched++
			fmt.Fprintf(os.Stderr, "gorgequal: parity seat %d native %d %s: realized %v %v, planned %+v\n",
				r.Seat, r.Native, r.Kind, r.Intent, r.Followups, rec)
		}
	}
	return compared, mismatched
}

type job struct {
	i       uint64
	deck    catalog.Deck
	pairing string
}

func qualify(o options) (Report, error) {
	reg, err := gorgepin.OpenRegistry(os.Getenv("GORGE_CARDS"))
	if err != nil {
		return Report{}, err
	}
	kinds := map[string]bool{}
	for _, k := range server.DecisionKinds {
		kinds[k] = true
	}
	var jobs []job
	for _, d := range catalog.Decks() {
		for _, p := range pairings {
			for g := 0; g < o.games; g++ {
				jobs = append(jobs, job{uint64(len(jobs)), d, p})
			}
		}
	}
	play := func(j job, audit bool) (minihost.Result, *auditLink, [2]minihost.Link, error) {
		srv := server.New(reg, nil)
		srv.SetAudit(audit)
		al := &auditLink{srv: srv, r: rand.New(rand.NewPCG(j.i, 7))}
		if audit {
			al.every = o.resample
		}
		names := strings.Split(j.pairing, "/")
		seats := [2]minihost.Link{link(names[0]), link(names[1])}
		h := &minihost.Host{RunSecret: []byte("gorge-qualification-run-secret!!"), Engine: al,
			Profile:  validate.Profile{Kinds: kinds, Flags: observe.Flags, Extensions: map[string]bool{}},
			MaxSteps: 100000, MaxDecisions: 49999}
		res, err := h.Play(j.i, j.deck, "london", []string{"x_gorge_view_v1"}, seats)
		return res, al, seats, err
	}
	rep := Report{Gates: map[string]DeckGate{}}
	var mu sync.Mutex
	start := time.Now()
	work := make(chan job)
	var wg sync.WaitGroup
	for w := 0; w < max(1, o.workers); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range work {
				a, al, seats, errA := play(j, o.audit)
				b, _, _, errB := play(j, false)
				fb, forced := 0, 0
				gate := DeckGate{Reasons: map[string]int{}}
				for _, l := range seats {
					ag, ok := l.(*agent.Server)
					if !ok {
						continue
					}
					fb += ag.Fallbacks()
					forced += ag.Forced()
					for _, rec := range ag.Records() {
						gate.AgentNatives++
						switch {
						case rec.Fallbacks > 0:
							gate.FallbackNatives++
						case rec.Forced > 0:
							gate.ForcedNatives++
						}
						if rec.Reason != "" {
							gate.Reasons[rec.Reason]++
						}
					}
				}
				compared, mismatched := parity(al.srv.Realized(), seats)
				leaks, inconsistent := al.srv.Leaks(), al.srv.Inconsistent()
				row := map[string]any{"deck": j.deck.CatalogID, "pairing": j.pairing, "game": j.i, "steps": a.Steps,
					"outcome": a.Terminal.Outcome, "digest": a.Digest, "leaks": leaks, "inconsistent": inconsistent,
					"parity_mismatch": mismatched, "fallbacks": fb, "forced": forced}
				mu.Lock()
				t := &rep.Totals
				t.Games++
				switch {
				case errA != nil:
					t.Violations++
					row["error"] = errA.Error()
				case a.Terminal.Classification == "halted":
					t.Halts++
					row["halt"] = a.Terminal.Reason
				case a.Terminal.Classification == "truncated":
					t.Truncations++
				}
				if errA == nil && (errB != nil || a.Digest != b.Digest) {
					t.DigestMismatch++
				}
				t.ResampleChecks += al.checks
				t.ResampleFailures += al.failed
				t.LeakHits += leaks
				t.Inconsistent += inconsistent
				t.ParityCompared += compared
				t.ParityMismatch += mismatched
				t.Fallbacks += fb
				t.Forced += forced
				dg := rep.Gates[j.deck.CatalogID]
				if dg.Reasons == nil {
					dg.Reasons = map[string]int{}
				}
				dg.AgentNatives += gate.AgentNatives
				dg.ForcedNatives += gate.ForcedNatives
				dg.FallbackNatives += gate.FallbackNatives
				for k, v := range gate.Reasons {
					dg.Reasons[k] += v
				}
				rep.Gates[j.deck.CatalogID] = dg
				rep.Rows = append(rep.Rows, row)
				mu.Unlock()
			}
		}()
	}
	for _, j := range jobs {
		work <- j
	}
	close(work)
	wg.Wait()
	rep.Totals.GamesPerSecond = float64(2*rep.Totals.Games) / time.Since(start).Seconds()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	rep.Totals.GoMemoryMB = ms.Sys >> 20
	return rep, nil
}

func main() {
	var o options
	flag.IntVar(&o.games, "games", 4, "games per deck and pairing")
	flag.IntVar(&o.resample, "resample", 7, "run the resample self-check before every K-th step (0: never)")
	flag.IntVar(&o.workers, "workers", max(1, runtime.NumCPU()/2), "concurrent games")
	flag.BoolVar(&o.audit, "audit", true, "leak scan, consistency, parity and resample checks on the first run of each game")
	outPath := flag.String("out", "gorgequal-report.json", "report path")
	flag.Parse()
	rep, err := qualify(o)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	b, _ := json.MarshalIndent(rep, "", " ")
	if err := os.WriteFile(*outPath, b, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	t := rep.Totals
	fmt.Printf("games %d halts %d truncated %d violations %d digest_mismatch %d resample_failed %d/%d leak_hits %d inconsistent %d parity_mismatch %d/%d fallbacks %d forced %d games/s %.2f clean=%v\n",
		t.Games, t.Halts, t.Truncations, t.Violations, t.DigestMismatch, t.ResampleFailures, t.ResampleChecks,
		t.LeakHits, t.Inconsistent, t.ParityMismatch, t.ParityCompared, t.Fallbacks, t.Forced, t.GamesPerSecond, rep.Clean())
	for _, d := range slices.Sorted(maps.Keys(rep.Gates)) {
		g := rep.Gates[d]
		fmt.Printf("gate %s: %d agent native decisions, %d forced, %d fallback, pass=%v\n", d, g.AgentNatives, g.ForcedNatives, g.FallbackNatives, g.Pass())
	}
	if !rep.Clean() {
		os.Exit(1)
	}
}
```

- [ ] **Step 4: Run the test and the qualification runs**

Run: `go test ./cmd/gorgequal/ -v -timeout 60m`
Expected: `--- PASS: TestSmallQualificationIsClean`.

Run: `go run ./cmd/gorgequal -games 8 -workers 8 -out ../../out/gorgequal-audit.json`
Expected: `clean=true` over 120 games (5 decks x 3 pairings x 8), with `halts 0`, `violations 0`, `digest_mismatch 0`, `resample_failed 0/`, `leak_hits 0`, `inconsistent 0` and `parity_mismatch 0/`, and `pass=true` on every deck's `gate` line.

Run: `go run ./cmd/gorgequal -games 8 -workers 1 -audit=false -resample 0 -out ../../out/gorgequal-serial.json && go run ./cmd/gorgequal -games 8 -workers 8 -audit=false -resample 0 -out ../../out/gorgequal-w8.json`
Expected: both `clean=true`. Record both games/s figures for Task 30's compute qualification.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/cmd/gorgequal && git commit -m "gorge adapter: qualification runner with bot parity, forced and fallback gate, and throughput"
```

---

### Task 29: Benchmark definition and engine notes

**Files:**
- Create: `~\IdeaProjects\spellbench\benchmarks\pauper-gorge\benchmark.json`
- Create: `engines/gorge/README.md`
- Test: `internal/server/benchmark_test.go`

**Interfaces:**
- Consumes: `catalog`, `server.DecisionKinds`, `observe.Flags`.
- Produces:
  - the benchmark file, written against the Section 11.4 and 12.2 fields with schema `spellbench-benchmark/v2`; P2's loader is the final authority and Task 30 reconciles any schema difference;
  - engine notes stating the declared profile and every deviation.

- [ ] **Step 1: Write the failing test**

`internal/server/benchmark_test.go`:

```go
package server_test

import (
	"encoding/json"
	"os"
	"slices"
	"testing"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/catalog"
)

func TestBenchmarkMatchesTheEngineProfile(t *testing.T) {
	raw, err := os.ReadFile("../../../../benchmarks/pauper-gorge/benchmark.json")
	if err != nil {
		t.Fatal(err)
	}
	var b struct {
		Schema, ID, Format string
		DeckPool           []string `json:"deck_pool"`
		Rules              struct {
			Mulligan       string   `json:"mulligan"`
			StartingPlayer string   `json:"starting_player"`
			Extensions     []string `json:"extensions"`
		} `json:"rules"`
		Limits map[string]int `json:"limits"`
	}
	if err := json.Unmarshal(raw, &b); err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.CatalogID)
	}
	if !slices.Equal(b.DeckPool, ids) || b.Format != "pauper-bo1" || b.Rules.Mulligan != "london" || b.Rules.StartingPlayer != "host_assigned" {
		t.Fatalf("benchmark %+v", b)
	}
	if 2*b.Limits["max_seat_decisions_per_game"] >= b.Limits["max_decisions"] ||
		2*b.Limits["max_seat_steps_per_game"] >= b.Limits["max_steps"] {
		t.Fatal("per-seat caps must be strictly below half of the game caps (Section 11.4)")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/server/ -run Benchmark`
Expected: FAIL with `open ../../../../benchmarks/pauper-gorge/benchmark.json:` followed by the system's file-not-found message.

- [ ] **Step 3: Write the files**

`benchmarks/pauper-gorge/benchmark.json`:

```json
{
  "schema": "spellbench-benchmark/v2",
  "id": "pauper-gorge",
  "title": "Pauper · gorge",
  "summary": "Five Pauper decks on the gorge rules engine; every matchup plays each deck in both seats.",
  "format": "pauper-bo1",
  "pairing": "rotating_pool",
  "engine": {"name": "gorge", "command": ["${GORGE_SPELLBENCH_ENV}", "-corpus", "${GORGE_CARDS}"], "timeout_ms": 120000},
  "deck_pool": ["Wildfire", "Rally", "Spy", "Burn", "CawGates"],
  "pairs_per_deck": 4,
  "rules": {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned", "starting_seat": "p0",
            "extensions": ["x_gorge_view_v1"], "probe": false},
  "time_control": {"startup_ms": 120000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
                   "max_decision_ms": 60000, "engine_step_ms": 120000},
  "limits": {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 500,
             "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999},
  "resources": {"cpus": 1, "memory_mb": 1024, "gpu": false, "engine_cpus": 1},
  "bots": [
    {"name": "uniform", "version": "2.0.0", "type": "builtin", "owner": "spellbench", "training_style_tags": ["baseline"],
     "display": {"label": "random", "author": "Spellbench", "description": "Picks uniformly at random among the offered actions. The anchor: its Elo is fixed at 1000.", "url": null}},
    {"name": "heuristic", "version": "2.0.0", "type": "builtin", "owner": "spellbench", "training_style_tags": ["heuristic"],
     "display": {"label": "heuristic", "author": "Spellbench", "description": "Fixed priorities over the offered actions.", "url": null}},
    {"name": "gorge-bot", "version": "gorge-26257e0eda17/adapter-0.1.0", "type": "subprocess", "engine": "gorge",
     "command": ["${GORGE_SPELLBENCH_AGENT}", "-policy", "bot"], "owner": "gorge", "training_style_tags": ["heuristic"],
     "display": {"label": "gorge bot", "author": "gorge", "description": "gorge's default heuristic bot, reading gorge's own seat view.", "url": "https://github.com/adams-shaun/gorge"}},
    {"name": "gorge-lethal-pressure", "version": "gorge-26257e0eda17/adapter-0.1.0", "type": "subprocess", "engine": "gorge",
     "command": ["${GORGE_SPELLBENCH_AGENT}", "-policy", "lethal-pressure"], "owner": "gorge", "training_style_tags": ["heuristic"],
     "display": {"label": "gorge lethal-pressure", "author": "gorge", "description": "gorge's lethal-pressure bot variant.", "url": "https://github.com/adams-shaun/gorge"}}
  ]
}
```

`engines/gorge/README.md` covers, briefly:
1. Build: `source scripts/env.sh && sh scripts/setup-dev.sh && go build -o bin/ ./cmd/...`; the corpus is fetched with gorge's `forgec fetch` and is never shipped.
2. CI (G1-6, G2-31): the module has no `go.sum` and builds only through the git-ignored `go.work`, and `scripts/env.sh` holds this machine's D: paths. A CI job clones gorge at the pin, exports `GORGE_SRC` and `GORGE_CARDS`, runs `forgec fetch -ref 95f04e8a04c8925fa97cb226fc3341cabcc90a53` into `GORGE_CARDS`, runs `sh scripts/setup-dev.sh`, then the one test command `go test -timeout 60m ./...` (the mini-host, agent and qualification packages run past `go test`'s 10-minute default). Tests fail, never skip, when `GORGE_CARDS` is unset.
3. The declared `hello_ok` profile (the Global Constraints line).
4. Engine procedures and limits:
   - Combat damage assignment is declared `engine_order` (Section 7.6): gorge's blocker order, lethal damage to each blocker, the rest to the last blocker or to the defender with trample; no `distribute` is posed. gorge measures lethal as the blocker's toughness (1 against deathtouch), without subtracting damage already marked. The other engine defaults are null.
   - Hybrid-pip allocation from floating mana is engine-internal (gorge's first option).
   - Unless costs can be paid only from floating mana (no activation during the unless ask).
   - `known_cards` is false and there is no text channel.
   - Only `host_assigned` starting players.
   - Retransmission: the engine caches every response since the last accepted reset, so an identical older request of the same game gets its cached response; a request id from an earlier game is not recognized.
   - Phased-out permanents are omitted (gorge's view treats them as absent).
   - `ability_index`: a non-mana ability counts the face's non-mana abilities in Oracle order. A mana ability takes gorge's stage-1 numbering of the source's available mana abilities, which is Oracle order when all are available; a source with one available ability reads 0.
   - Changeling is a known gap: subtypes show gorge's derived types (Masked Vandal reads `shapeshifter`), not every creature type.
   - Cast modes that fail closed as `unmapped_decision`: `optionalcost`, `multikicked`, `replicated`, `squadded`, `warped`, `warp_recast`, `mayhem`, `harmonize`, `retrace`, `jumpstart`, `aftermath`, `adventure_recast`, `room_alt`, `defeat_cast`, and the special actions `foretell` and `suspend`. An Omen face (Roost Seek) is cast with method `other`, which the vocabulary offers for it.
   - A mana payment window that does not lead to a trigger-cost ask halts the game `engine_contract_failure:unmapped_decision`: a cast payment window (gorge poses one when a cost grows after announcement) or an `unless_mana` window. Bot play never reaches one; another agent can.
   - Where gorge fixes a pile-B order (an arrange ask that is not Restable), each order pick offers one card. A dig_bottom ask with no take ask before it is an arrangement whose partitions are all `bottom`.
5. `x_gorge_view_v1`: payload fields, id re-keying and the audit (Task 24), `native_ids: false`. Hidden, absent and zero references are 0, option groups are relabelled, and the policy facts restore the server-side fields gorge's bot reads, including the card views' mana production flags. The wrapped bots see per-seat ids and name-sorted hidden options, so their games are not byte-identical to native gorge games; parity means the adapter commits exactly the intent, follow-up answers included, the bot chose (Task 28b).
6. How to run the qualification (Tasks 28a and 28b) and the goldens (Task 27).

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/server/ -run Benchmark -v`
Expected: `--- PASS: TestBenchmarkMatchesTheEngineProfile`.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/pauper-gorge engines/gorge/README.md engines/gorge/internal/server/benchmark_test.go && git commit -m "pauper-gorge benchmark definition and gorge engine notes"
```

---

### Task 30: Integration with sub-project P and the rated run

**Files:**
- Modify: `benchmarks/pauper-gorge/benchmark.json` (to P2's final schema)
- Modify: `benchmarks/local.json` (git-ignored: `GORGE_SPELLBENCH_ENV`, `GORGE_SPELLBENCH_AGENT`, `GORGE_CARDS`)
- Create: the run folder P's launcher writes under `benchmarks/pauper-gorge/runs/`

**Interfaces:**
- Consumes: P1 (reference host and live validator), P2 (benchmark loader), P3 (v2 builtin bots), P4 (conformance harness and `goldens/protocol_v2`), P5 (per-game extension enablement, optional).
- Produces: a validator-clean `pauper-gorge` run with gorge's bots rated, and the run manifest recording the compute choice.

- [ ] **Step 1: Point the benchmark at the built binaries**

Run: `go build -o bin/ ./cmd/spellbench-gorge-env ./cmd/spellbench-gorge-agent`, then set in `benchmarks/local.json`: `"GORGE_SPELLBENCH_ENV": "~/IdeaProjects/spellbench/engines/gorge/bin/spellbench-gorge-env.exe"`, `"GORGE_SPELLBENCH_AGENT": ".../spellbench-gorge-agent.exe"`, `"GORGE_CARDS": "D:/community/gorge/.cards"`.
Expected: P2's loader validates `benchmarks/pauper-gorge/benchmark.json` with no error. If P2's schema differs from the draft fields, edit the file to P2's schema and rerun `TestBenchmarkMatchesTheEngineProfile`.

- [ ] **Step 2: Run P's engine conformance harness against the binary**

Run: P4's documented command with the engine command set to `bin/spellbench-gorge-env.exe -corpus D:/community/gorge/.cards`.
Expected: every envelope and error scenario passes with engine identity masked. Any failure is fixed in the owning task's package with a new test, then this step is rerun.

- [ ] **Step 3: Smoke tournament with the live validator**

Run: P1's tournament launcher on `pauper-gorge`, 1 pair per deck, all four bots.
Expected: validator verdict `pass`, zero `halted` games, gorge agents with zero `malformed_response` or `invalid_selection` forfeits.

- [ ] **Step 4: Compute qualification before the rated run** (`~/COMPUTE-POLICY.md`)

Each item fills a field of the run manifest's compute record.
- Placements (`placements`): for the primary desktop, the compute host and RunPod, record availability, competing work, cores, memory, storage and connectivity, and any current reservation to preserve.
- Throughput on identical inputs (`throughput`): the same seeded pairs through P's launcher at `workers` 1, 4, 8 and 16 on the primary desktop, and the same pairs with the same binaries (hashes checked) on the compute host. Record completed games per second and projected completion time per machine and worker count. Task 28b's in-process figures are ceilings only.
- RunPod projection (`runpod_projection`): cost and turnaround, counting startup, the transfer of the binaries, a `forgec fetch` of the corpus there (it is never shipped), games per second, recovery and release, against the two PCs and within existing spending authority.
- Guarded launch path (`guarded_launcher`): run P's launcher once without throughput evidence and record its refusal, then name the launch command that carries the guard. A launch that bypasses it is not a qualified run.
- Choice (`choice`): the fastest qualified allocation, and why.
Expected: every field is recorded, the refusal is shown, and the chosen allocation is the fastest qualified one.

- [ ] **Step 5: Artifact law before launch** (`~/IdeaProjects/collab/ARTIFACT-LAW.md`)

Each item fills a field of the run manifest's artifact record.
- Budget (`budget_bytes`, `cap_bytes`, clause 1): the run's projected bytes and a cap; the launcher refuses dispatch past the cap or below a 60 GiB reserve on the target volume, and the actual bytes are reconciled after the run.
- Scratch (`scratch_root`, clause 2): hot I/O under one SSD scratch root, `D:/e-scratch/pauper-gorge-<run>/`, with a manifest naming its sources and hashes; sealed outputs move to E: once verified, and the scratch deletion is logged.
- Pinned binaries (`pinned_binaries`, clause 4): copy `spellbench-gorge-env` and `spellbench-gorge-agent` into `E:/pinned-binaries/<sha256>/` and record both hashes, with gorge's commit and the corpus digest.
- Registry (`catalog_entry`, clause 9): register the run's artifact tree in `ARTIFACTS/catalog.jsonl` through `tools/artifact_register.py`.
Expected: the manifest carries every field, both binaries resolve by hash under `E:/pinned-binaries`, and the catalog lists the run.

- [ ] **Step 6: Commitment before the first game** (Section 11.6)

Run: P's `bench commit` for the rated run, under the standing authorization. It writes the commitment (SHA-256 of the run secret, with the benchmark id and the run label), pushes it to the benchmark's public repository and obtains a third-party timestamp.
Expected: the pushed commit and the timestamp both exist before Step 7 starts. A run whose commitment is not provably public before its first game is never rated, so the launch waits for both.

- [ ] **Step 7: Rated run and publication gate**

Run: P1's launcher with the recorded allocation and the pushed, timestamped commitment. During the run, sample CPU, memory and I/O each minute: two consecutive 60-second windows of idle eligible capacity while games are queued require diagnosis and a qualified correction, recorded in the manifest (compute policy item 6).
Expected: a completed run with validator verdict `pass`, `fairness_label` `validator only`, `native_id_extensions` empty, and gorge-bot and gorge-lethal-pressure rated. Publishing the run and pushing branches wait for the maintainer.

- [ ] **Step 8: Closure prune manifest** (artifact law clause 3)

Write the run's PRUNE manifest (paths, bytes, hashes, regeneration recipe): keep the manifests, receipts, reports, ledger and every failed or void attempt's records; prune uncited bulk; never prune a hash-cited file. Mark the catalog entry closed.
Expected: the PRUNE manifest lists every pruned path, and the catalog entry points to it.

- [ ] **Step 9: Commit**

```bash
git add benchmarks/pauper-gorge && git commit -m "pauper-gorge: first validator-clean run"
```

---

## Self-review

Spec coverage, by section:

| Spec section | Task |
|---|---|
| 2 transport | T2, T23 |
| 4.1 retransmission | T23 |
| 4.3 canonical JSON | T3, T25 |
| 5.3 ids | T4, T10 |
| 6 observation | T11, T12 |
| 6.7 known (`known_cards` false) | T18, T19a, T19b |
| 6.8 hidden | T11, T24, T28a |
| 7.1 rules | T13 |
| 7.2 to 7.5 kinds | T14 to T21 |
| 7.6 defaults (combat damage `engine_order` declared; mulligan and starting player by rules) | T8, T16, T23 |
| 8 groups and caps | T13, T22 |
| 9.1 to 9.8 messages and errors | T5, T6, T22, T23 |
| 11.3 validator | T9, T25, T30 |
| 11.4 limits | T29 |
| 11.6 secrets and streams | T4, T8 |
| 11.8 digest | T3, T25 |
| 12 decks and domain | T7, T23 |
| 13 fairness | T24, T28a, T28b |
| 14 extensions | T24 |
| 16 goldens and vectors | T3, T4, T27, T30 |

- **Gaps accepted:** `probe_resample` answers `unsupported_request`, as the spec allows for an engine without the probe. `choose_pile` and `choose_cost_option` are not declared; the pool needs neither. `distribute` is not declared: combat damage follows the declared engine order (T16).
- **Placeholder scan:** every step carries its code. Task 30 depends on P's commands, which it names by deliverable because P has not published them yet.
- **Type consistency:** `NativeOp` (T13) is used unchanged by T14 to T21, T24 and T26; its ops `choose`, `finish`, `none`, `cast`, `list` and `dest` are matched one for one by `agent.Pick`, and follow-up keys (`"<option>"`, `"<option>/<follow-up option>"`, `dig_bottom`) are renumbered by `xview.followKey`, checked by the session before each folded intent (T22) and translated for the audit (`xview.Follow`, T28a). `Transaction.Answer` returns `([]decision.Intent, bool, error)` everywhere, and `Env.OpenLook` and `Env.CloseLooks` are used by T18, T19a, T19b and T22.
- **Review Focus:** each line has its test in T7, T22, T23 and T26.

## Revision notes

Pre-execution review G1 (Tasks 1 to 12) and G2 (Tasks 13 to 30), applied with the controller's rulings. Tasks 3, 5, 7 and 8 show what was built ("applied during implementation"), and Task 3's Step 6 what the wire follow-up applies.

- G1-1: T10 `TestMulliganRoundTripGivesFreshIDs` answers the other seat's keep before comparing; the design note records gorge's deferred redraw.
- G1-2: T5 `Semantic.UnmarshalJSON` and number-safe `Check` (applied during implementation); T9 `TestJSONDecodedDecisionValidates`.
- G1-3: T10 records source, target and attack keys (`SourceKey`, `TargetKey`, `AttackKey`); T12 nulls stale references; tests for a cycled source, a target that left, and Writhing Chrysalis's cast trigger.
- G1-4: T6 strict string, bool and array getters, exact decklist rows, u32 `protocol_minor`; null and row cases in `TestDecodeErrorsUseTheClosedTable`.
- G1-5: T11 `manaValue` takes a transforming card's front-face cost; `TestManaValueOfBackFacesAndX`.
- G1-6: T29 README CI note (clone at the pin, `forgec fetch`, `setup-dev.sh`, one `go test -timeout 60m ./...`).
- G1-7: T3 Step 6, `WithoutRequestID` runs `CheckStrict` first (applied in the wire follow-up).
- G1-8: T5 `Check` constraints and `ExtensionMap` (applied during implementation).
- G1-9: T7 keyed literals, `rules` import, preflight coverage note (applied during implementation).
- G1-10: T8 stream-recomputation tests and the `Probe` F3 comment (applied during implementation).
- G1-11: T9 V1 extensions, V4 all references, V5 `known` and hidden order, V8 flags, V9 companions, `Stream.InGroup`; T25 cross-seat V3 check.
- G1-12: T10 skip replaced by `t.Fatal`, `OpenLook` closes an open look first; T11 `LookRef` refuses visible objects.
- G1-13: T11 hidden-card scan over p1's hand and library names.
- G1-14: T11 X on the stack and face-down ability names, changeling noted as a gap; T12 `stack_kind` from `Object.StackKind`; T29 notes.
- G1-15: T10 `Blocking` (declared blockers per combat); T12 `blocking` reads it, tombstones skipped; `TestBlockerStaysBlockingAfterItsAttackerLeaves`.
- G1-16: T12 halts on a stack object without a reference or with an unmapped kind.
- G1-17: T12 Step 2 expects a compile failure; T11 names `project.go` for the stubs.
- G2-1: T15 folds gorge's stage-1 mana ability ask and its stage-2 colour ask; Heap Gate test.
- G2-2: T24 rekeys only seen or shown objects, others 0; pending triggers without a source dropped; Lembas and zero-source tests.
- G2-3: T24 `relabelGroups` (`g0`, `g1`, ...) for groups and `GroupLimits`; `TestGroupsCarryNoNativeIDs`.
- G2-4: T5's decoder (via G1-2, applied during implementation) is what T25 consumes; nested values stay raw JSON per the Task 5 ruling, not a per-kind Go type table.
- G2-5: waves and dependencies: T13, then T14, then T15; wave 5 on T14's helpers; T26 after T23 and T25; T28b last; critical path recomputed.
- G2-6: T19b scry test checks the drawn card and the library bottom.
- G2-7: T26 `Pick` returns "forced" for an unmatched single candidate, counted apart; T28b parity skips it and reports it per deck.
- G2-8: T28a resample check runs only on a transaction's first pose (`fresh`); T22 `advance` and `answer` set and clear it.
- G2-9: T28a `hiddenNames` subtracts every name the decision's public records carry.
- G2-10: T18 `PrintedModes`; `mode_index` and `mode_count` are printed; filtered Thraben Charm test.
- G2-11: T15 `ability_index` from the stage-1 option's `Ability`; T29 notes corrected.
- G2-12: T16 `laterUnitsOnly` limits the FitRequired shortcut to undecided units.
- G2-13: `combat_damage_assignment: "engine_order"` (Global Constraints, T23); T16 answers the division ask internally (`EngineOrderSplit`, `RegisterInternal`); `distribute` dropped from the 24 kinds, with Pose splits and the `amount` op.
- G2-14: T28a realized commits with follow-up answers and the semantic-consistency audit; T26 `Record`; T28b full parity and the 1% forced and fallback gate.
- G2-15: T22 cap test drives a multi-substep group and fails if absent; echo test with reversed nested keys and a changed field; T28a resample test fails on `halted`.
- G2-16: T22 `submit` checks each folded follow-up against the lookahead (`followKeys`, `sameAsk`), else `followup_mismatch`.
- G2-17: T30 Steps 4, 5, 7 and 8: placements, throughput on both PCs, RunPod projection, guarded launcher, utilization watch, byte budget, scratch root, pinned binaries, catalog, PRUNE manifest.
- G2-18: T30 Step 6: P's `bench commit` pushes and timestamps the commitment before the first game.
- G2-19: T20 madness `card` is the exiled card; the test checks its zone.
- G2-20: T24 visits follow-up keys in sorted order.
- G2-21: T23 caches every response of the current game and clears at each accepted reset; test and Review Focus 4 updated; T29 notes.
- G2-22: T25 `KeepDecisions`, off by default.
- G2-23: T19a numbers trigger instances over the item's visible fields.
- G2-24: T13 `ActionContext.Since`; `ResolveSource` skips older abilities while the seat announces its action; T22 sets `Since`.
- G2-25: T14 `CastMethod(o, alternateMode)`: Omen is `other`, alternative costs keyed by `AltCostIndex`; T29 lists the fail-closed modes.
- G2-26: T26 recovers bot panics, answers `internal_error` and `malformed_request`, `agent.Serve` keeps reading after an over-long line.
- G2-27: T24 `ProducesFacts` carries the mana production flags; T26 `Rebuild` restores them.
- G2-28: T21 comment and T29 notes list the cast payment window as a halt cause.
- G2-29: T19a `hand_move/library` selection gets a `Finish`.
- G2-30: T27 arrangement and order groups of three or more (the order block outside an arrangement), digests checked on replay, goldens without the extension.
- G2-31: T29 CI command with `-timeout`, `json` tags on the benchmark test, OS-neutral expected text; T23 smoke without `.exe`.
- G2-32: T19 split into T19a and T19b, T28 into T28a and T28b, T25 re-estimated at 0.75.
- T19b fix round 1: a lone dig remainder's ordering pick carries the presentational dest op ({Op: "dest", Option: -1, List: "bottom"}), never a followup:dig_bottom op — gorge moves a lone remainder without asking.
- Controller: T8 runs after T7 in wave 2 (wave table). `DeckID` and `DomainID` refuse repeated names: T3 Step 6 (applied in the wire follow-up), with T7, T23 and T25 taking the error.
