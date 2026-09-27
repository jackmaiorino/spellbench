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
- `C:\Users\Jack\IdeaProjects\spellbench\spec\SPELLBENCH_PROTOCOL_V2.md`, branch `board-program`, commit `7e9e73f`. Annex B describes gorge informatively. Where this plan departs from Annex B, it says why.
- Background: `C:\Users\Jack\AppData\Local\Temp\claude\C--Users-Jack-IdeaProjects\157aeb44-0d40-4f26-8ee2-2b800f31ba9e\scratchpad\gorge-adapter-brief.md`.
- Evidence probes: `D:\community\gorge-scratch\probe\cmd\{census5,sourceprobe,plannerprobe,catalogprobe}`, logs in `D:\community\gorge-scratch\logs\`.

## Global Constraints

- **Protocol authority:** `spellbench/v2`, `protocol_minor` 0, frozen at spec commit `7e9e73f`. The environment role is strict (Section 4.2); anything the spec does not license is rejected with its pinned error code, and unrepresentable states end the game `halted` with reason `engine_contract_failure:<cause>`.
- **Where the adapter lives:** a separate Go module at `C:\Users\Jack\IdeaProjects\spellbench\engines\gorge`, module path `github.com/jackmaiorino/spellbench/engines/gorge`, license MIT (the Spellbench repository license). It requires `github.com/adams-shaun/gorge v0.0.0-20260927030508-26257e0eda17`, resolved locally through a git-ignored `go.work` replace to `D:/community/gorge` (commit `26257e0eda1779d739a07e835c6500b9c4dabc62`). Why not a fork branch of gorge:
  - (a) No engine change is needed. `rules.NewHypotheticalPlanned` (planner per player and ordinal) plus a forced toss gives the Section 11.6 streams, proven by `D:\community\gorge-scratch\probe\cmd\plannerprobe` on 20 live games with zero unplanned draws.
  - (b) The adapter implements the Spellbench spec, so it belongs next to the spec, its goldens and sub-project P's conformance harness.
  - (c) gorge churns daily (6,204 commits, head committed the day of the pin). A pinned import isolates us; the pin moves by a deliberate task.
  - (d) gorge's in-tree process rules (test budgets, dependency order, time-import whitelist, closing approximations register) never apply to our code.
  - (e) The packages are self-contained, so they can later move under `gorge/cmd/` if gorge's maintainer wants to own them.
  - Cost: `internal/policynet` cannot be imported from outside gorge, so the PolicyNet bot needs an exported loader upstream. It is out of scope here.
- **gorge's tree is read-only.** No tracked gorge file is modified and nothing is committed there. gorge's per-package test budgets (`TEST_HISTORY.md` `budget_s`) and dependency-order rules (`internal/archtest`) apply to anything placed inside gorge's tree. This plan places nothing there; the rules bind any later upstream PR.
- **Forge scripts are never shipped.** They are GPL-3.0 and are never vendored, embedded, committed or published. The corpus lives only in `D:\community\gorge\.cards` (gitignored), fetched by `forgec fetch -ref 95f04e8a04c8925fa97cb226fc3341cabcc90a53`. Binaries load it at run time through `-corpus` or `GORGE_CARDS`.
- **Toolchain and caches:** Go 1.27.1 at `D:\tools\go1.27.1\go\bin`, `GOTOOLCHAIN=local`, `CGO_ENABLED=0`, `GOCACHE=D:/community/go-cache/build`, `GOMODCACHE=D:/community/go-cache/mod`. Every command in this plan runs in Git Bash from `C:/Users/Jack/IdeaProjects/spellbench/engines/gorge` after `source scripts/env.sh`. Builds use no network.
- **Randomness (Section 11.6):**
  - Library shuffle n of seat s uses `rand.New(rand.NewChaCha8(HMAC-SHA256(game_secret, "spellbench/v2/rng:<s>:library_shuffle:<n>")))`, Fisher-Yates over the planner's input.
  - The toss is not random: the chance prefix `{Bound: 2, Value: starting_seat}` forces it.
  - `rules.Config.Seed` is the first 8 bytes of HMAC(game_secret, `"spellbench/v2/rng:shared:gorge_seed:0"`).
  - Any engine draw the planner did not supply halts the game with `engine_contract_failure:unplanned_randomness`.
- **Declared engine profile (hello_ok):**
  - `formats ["pauper-bo1"]`, `deck_sources ["catalog"]`;
  - `rules_supported {"mulligan":["london","none"],"starting_player":["host_assigned"]}`;
  - observation flags true only for `pending_triggers` and `keywords`;
  - `engine_defaults` all `null`, `rewind false`, `fairness {"noninterference_probe":false}`;
  - `extensions [{"name":"x_gorge_view_v1","native_ids":false}]`;
  - `decision_kinds`: the 25 kinds `pass, play_land, cast_spell, activate_mana_ability, activate_ability, special_action, choose_target, finish_target_selection, choose_cost_target, choose_spell_mode, choose_color, choose_number, choose_boolean, choose_name, select_object, finish_selection, optional_cost, optional_cast, mulligan, order_pick, arrange_card, choose_replacement, declare_attack, declare_block, distribute`.
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
  - Parallel tasks use separate worktrees `C:\Users\Jack\IdeaProjects\spellbench-wt\g<N>` on branches `gorge-adapter-g<N>`, merged into `gorge-adapter` in wave order.
  - Nothing is pushed or published without Jack.
- **House rules:** no em-dashes anywhere (code, comments, docs, commits); concise docs; name projects, not people.
- **Compute policy.** Before the rated run (Task 30), apply `C:/Users/Jack/COMPUTE-POLICY.md`:
  - measure serial and parallel completed games per second on Jack's PC;
  - check HaleysPC and RunPod availability;
  - record the choice in the run manifest;
  - launch only through P's supported host launcher.

## Review Focus

1. **Name normalization.** Decks named with ASCII-folded or NFD names (`Troll of Khazad-dum`, `Lo\u0301rien Revealed`), or a host whose `deck_id` rows use `"A // B"` names, must give `unsupported_deck` or matching ids, never a crash or silent substitution. Pinned in Task 7 (`TestDeckIDsMatchHostComputation`, `TestAsciiFoldedNameIsNotSubstituted`).
2. **Echo equality.** A `step` whose `semantic_echo` has the candidate's fields in another key order, or with nested object references re-serialized, must be accepted; an echo with one extra or one changed field must be `semantic_echo_mismatch`. Pinned in Task 22 (`TestEchoComparesParsedFieldsNotBytes`).
3. **Caps.** A cap that would land inside a fixed group (attack declarations, arrangements) must end the game `truncated` before the group starts, with `decision_count` excluding it. The engine must never interrupt a partial group, which Section 8 forbids for truncation. Pinned in Task 22 (`TestCapNeverSplitsAGroup`).
4. **Retransmission.** A retransmitted `step` after the engine has already answered it returns the cached bytes without advancing. The same `request_id` with different bytes, including an older id, returns `request_id_reuse_mismatch`. Pinned in Task 23 (`TestRetransmissionIsIdempotentAndReuseFails`).
5. **Canonicalized payloads.** The Go agent must reconstruct gorge types from the host's canonical re-serialization: sorted keys, integers re-printed, extension object reordered. Pinned in Task 26 (`TestAgentDecodesCanonicalizedPayload`).

---

## File Structure

All paths are relative to `C:\Users\Jack\IdeaProjects\spellbench\engines\gorge` unless absolute.

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
| `internal/session/` | one game: loop, counters, groups, caps, terminals, halts, internal answers; the qualification audit (resample self-check, leak scan, realized intents) |
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

Each row is one task of about half a day unless noted; tasks in one wave run in parallel in separate worktrees.

| Wave | Tasks (effort, depends on) |
|---|---|
| 0 | T1 scaffold and pin (0.5) |
| 1 | T2 strict JSON and framing (0.5, T1); T3 canonical JSON and digests (0.5, T1); T4 secrets (0.5, T1); T5 v2 types (0.5, T1) |
| 2 | T6 envelope and requests (0.5, T2 T5); T7 catalog (0.5, T1 T3); T8 game construction (0.5, T4 T7); T9 validator subset (0.5, T5) |
| 3 | T10 identity (0.5, T4 T8); T11 observation I (0.5, T5 T10); T12 observation II (0.5, T11) |
| 4 | T13 mapping framework (0.5, T12); T14 priority (0.5, T13); T15 mana abilities (0.5, T13) |
| 5 | T16 combat (0.75, T13); T17 targets and costs (0.5, T13); T18 selections and modes (0.5, T13); T19 ordering and arrangement (1.0, T13); T20 simple choices (0.5, T13); T21 resolution payments (0.5, T13 T15) |
| 6 | T22 session (0.5, T6 T8 T12 T14 to T21); T24 x_gorge_view_v1 (0.75, T14 to T21) |
| 7 | T23 environment server and binary (0.5, T6 T22 T24); T26 Go agent (1.0, T24) |
| 8 | T25 mini-host and test agents (0.5, T3 T4 T9 T23) |
| 9 | T27 goldens (0.5, T25); T28 qualification (1.0, T25 T26) |
| 10 | T29 benchmark and engine notes (0.5, T7 T28) |
| 11 | T30 integration with sub-project P and rated run (0.75, P deliverables P1 to P4) |

- **Effort:** about 17.25 agent-days in total, 16.5 before P's deliverables land.
- **Critical path:** T1, T3, T7, T8, T10, T11, T12, T13, T19, T24, then T23 and T25 (or T26, equal length), then T28, T29 = 8.25 days of work. T30 (0.75) follows once P lands, about 9 days elapsed with enough parallel agents. With three agents, expect 11 to 12 working days.
- **Slack:** the wave-1 and wave-5 tasks off the path (T2, T4, T5, T6, T9, T14 to T18, T20, T21) and T27.

## What this plan needs from sub-project P

| P deliverable | Used by | Interim without it |
|---|---|---|
| P1 v2 reference host with the live validator (V1 to V10), canonical forwarding, secrets and commitment, clocks, forfeits, digest | T30 rated run, validator verdict | Go mini-host plus validator subset (T9, T25), run in T28 |
| P2 `spellbench-benchmark/v2` schema and loader (rotating pool, rules, time_control, limits, resources, per-game extension enablement) | T29 final validation, T30 | T29 writes the file against the spec fields and a Go shape test |
| P3 v2 builtin bots (uniform anchor, heuristic, first) | T30 ratings | Go `uniform` and `first` test agents (T25) |
| P4 v2 engine conformance harness and `goldens/protocol_v2` envelope and error goldens, replayable by any engine with engine identity masked | T30 conformance | engine-specific Go goldens and error-table tests (T23, T27) |
| P5 host policy: enable `x_gorge_view_v1` only in games where an entry `requires` it (payload about 14 KB per decision) | T30 throughput | enable it in every game (correct, slower) |

## Decisions for the controller

1. **Adapter location.** Recommended: `engines/gorge` inside the Spellbench repository, MIT, pinned import. The alternative is a standalone Apache-2.0 repository, easier to hand to gorge's maintainer.
2. **Unless-cost payment (Chain Lightning copy, Spell Pierce).** gorge asks pay/decline before its mana window, so v2's "`pay: false` is always offered" cannot hold after floating mana inside that window. Recommended: offer `optional_cost` pay:true only when the floating pool already covers the cost, with no activation candidates (7.1 says "may"), and document it. Alternatives: declare `mana_payment: "engine_autopay"` (changes the whole mana model), or ask upstream for a window-first unless flow.
3. **Hybrid pip allocation** (Burning-Tree Emissary's `{R/G}` paid from a pool holding both). v2.0 has no kind for allocating floating mana (`pay_mana` is reserved). Recommended: the engine answers with gorge's first offered option and documents it; alternative: pose `choose_color` with purpose `mana`.
4. **Mulligan rule for `pauper-gorge`.** Section 12.2 says `london` wherever supported, which makes the cross-engine comparison with `pauper-kernel` (`none`) not like for like. Recommended: `london`, per the spec.
5. **Publishing.** Pushing `gorge-adapter`, publishing the benchmark, and offering the adapter to gorge's maintainer are Jack's to send.
6. **What "gorge-bot" means on the leaderboard.** Through the adapter the bot sees per-seat ids and name-sorted hidden options (F1), so its games are not byte-identical to native gorge games. Recommended: rate it as `gorge-bot` with that note, and qualify it by intent parity (Task 28: the adapter commits exactly the move the bot chose). The alternative, native-identical play, would need native ids and engine-ordered hidden options, which F1 rules out.

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
cd /c/Users/Jack/IdeaProjects/spellbench && git switch board-program && git switch -c gorge-adapter
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
  - `type wire.DeckRow struct{ Name string; Count int }` (JSON `name`, `count`), `func wire.DeckID(rows []DeckRow) string`, `func wire.DomainID(names []string) string`;
  - `func wire.WithoutRequestID(msg []byte) ([]byte, error)`;
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
  - `type Semantic struct{ Kind string; Fields map[string]any }` with `MarshalJSON` and `func (Semantic) Check() error`;
  - `var KindFields map[string][]string` (the 30 kinds) and `var PriorityKinds map[string]bool`;
  - the constructors listed in Step 3;
  - `type Candidate`, `type Group`, `type Context`, `type SeatDecision`, `type Observation`, `type PlayerObs`, `type ObjectRecord`, `type Characteristics`, `type Permanent`, `type StackEntry`, `type PendingTrigger`, `type Known`, `type ManaPool`, `type OrderItem`, `type TriggerItem`;
  - `type Provenance`, `type Engine`, `type HelloOK`, `type DecisionResponse`, `type TerminalResponse`, `type ErrorResponse`, `type ErrorBody`, `type DeckOK`.

- [ ] **Step 1: Write the failing test**

`internal/protocol/kinds_test.go`:

```go
package protocol_test

import (
	"encoding/json"
	"sort"
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

func TestConstructorsEmitExactlyTheSpecFields(t *testing.T) {
	name := "Lightning Bolt"
	r := protocol.ObjectRef{ObjectID: "o-0a3647243d16bf78", CardName: &name, OwnerSeat: "p0", ControllerSeat: "p0", Zone: "hand"}
	tgt := protocol.PlayerTarget("p1")
	for _, s := range []protocol.Semantic{
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
	} {
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
		protocol.ChooseTarget(r, 0, protocol.PlayerTarget("p0"), 1, 1, 1),  // selected_count < maximum
		protocol.ChooseSpellMode(r, 2, 2, 0, 1, 1),                          // mode_index < mode_count
		protocol.ChooseNumber(nil, "amount", 5, 0, 4),                       // minimum <= value <= maximum
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/protocol/`
Expected: FAIL with `undefined: protocol.KindFields`.

- [ ] **Step 3: Write minimal implementation**

`internal/protocol/refs.go`:

```go
// Package protocol holds the Spellbench v2 wire types this engine emits and reads.
package protocol

import "encoding/json"

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

func (t *TargetRef) UnmarshalJSON(b []byte) error {
	var m struct {
		Player *string    `json:"player"`
		Object *ObjectRef `json:"object"`
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return err
	}
	t.Player, t.Object = m.Player, m.Object
	return nil
}

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
	"encoding/json"
	"fmt"
	"slices"
)

// KindFields is Section 7.2 and 7.3: each kind's fields, all required, no others.
var KindFields = map[string][]string{
	"pass":                    {},
	"play_land":               {"source", "face"},
	"cast_spell":              {"source", "method"},
	"activate_mana_ability":   {"source", "ability_index", "mana_choice", "cost_target"},
	"activate_ability":        {"source", "ability_index"},
	"special_action":          {"source", "action"},
	"choose_target":           {"source", "slot", "target", "selected_count", "minimum", "maximum"},
	"finish_target_selection": {"source", "slot", "selected_count"},
	"choose_cost_target":      {"source", "cost_kind", "candidate", "selected_count", "minimum", "maximum"},
	"choose_cast_method":      {"source", "method"},
	"choose_spell_mode":       {"source", "mode_index", "mode_count", "selected_count", "minimum", "maximum"},
	"choose_option":           {"source", "purpose", "option_index", "option_count", "option_label"},
	"choose_color":            {"source", "purpose", "color"},
	"choose_number":           {"source", "purpose", "value", "minimum", "maximum"},
	"choose_boolean":          {"source", "purpose", "value"},
	"choose_name":             {"source", "purpose", "value"},
	"select_object":           {"source", "purpose", "choice", "selected_count", "minimum", "maximum"},
	"finish_selection":        {"source", "purpose", "selected_count"},
	"optional_cost":           {"source", "cost", "pay"},
	"choose_cost_option":      {"source", "choice"},
	"optional_cast":           {"card", "method", "cast_it"},
	"mulligan":                {"hand_size", "mulligans_taken", "keep"},
	"order_pick":              {"source", "purpose", "item", "position", "count"},
	"arrange_card":            {"source", "purpose", "card", "card_index", "card_count", "destination"},
	"choose_replacement":      {"affected", "event", "replacement_source", "replacement_index", "replacement_count"},
	"choose_starting_player":  {"player"},
	"declare_attack":          {"attacker", "defender"},
	"declare_block":           {"blocker", "attacker"},
	"distribute":              {"source", "purpose", "recipient", "amount", "remaining"},
	"choose_pile":             {"source", "purpose", "pile_index", "piles"},
}

var PriorityKinds = map[string]bool{"pass": true, "play_land": true, "cast_spell": true,
	"activate_mana_ability": true, "activate_ability": true, "special_action": true}

// Vocab is Section 6.10 and 7.4, keyed "<kind>.<field>" or a shared name.
var Vocab = map[string][]string{
	"select_object.purpose":    {"discard", "sacrifice", "exile", "destroy", "return_to_hand", "search", "reveal", "put_onto_battlefield", "put_into_hand", "put_into_graveyard", "legend_rule", "tap", "untap", "delve", "convoke", "attach", "keep", "vote", "modes", "other"},
	"finish_selection.purpose": {"discard", "sacrifice", "exile", "destroy", "return_to_hand", "search", "reveal", "put_onto_battlefield", "put_into_hand", "put_into_graveyard", "legend_rule", "tap", "untap", "delve", "convoke", "attach", "keep", "vote", "modes", "other"},
	"choose_boolean.purpose":   {"may_ability", "optional_trigger", "may_cast", "change_copy_targets", "optional_replacement", "reveal", "other"},
	"choose_number.purpose":    {"x_value", "amount", "life_payment", "cost_repetitions", "vote", "other"},
	"choose_option.purpose":    {"effect_option", "top_or_bottom", "odd_or_even", "vote", "other"},
	"choose_color.purpose":     {"mana", "protection", "effect", "other"},
	"choose_name.purpose":      {"card_name", "creature_type", "card_type", "land_type", "basic_land_type", "other"},
	"order_pick.purpose":       {"triggers", "library_top", "library_bottom", "mulligan_bottom", "arrangement", "other"},
	"arrange_card.purpose":     {"scry", "surveil", "dig", "look_at_top", "pile_split", "other"},
	"arrange_card.destination": {"top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1"},
	"distribute.purpose":       {"damage", "combat_damage", "counters", "mana", "life", "other"},
	"choose_pile.purpose":      {"effect", "other"},
	"method":                   {"normal", "alternative", "flashback", "escape", "evoke", "overload", "adventure", "disturb", "foretell", "plot", "mdfc_back", "split_left", "split_right", "fuse", "prototype", "morph", "disguise", "madness", "miracle", "cascade", "discover", "rebound", "suspend", "free", "other"},
	"optional_cost.cost":       {"kicker", "buyback", "entwine", "conspire", "casualty", "bargain", "gift", "offspring", "copy", "unless_payment", "additional", "other"},
	"choose_cost_target.cost_kind": {"sacrifice", "discard", "exile", "tap", "untap", "return_to_hand", "reveal", "remove_counter", "other"},
	"special_action.action":    {"turn_face_up", "plot", "foretell", "suspend", "unlock_door", "other"},
	"choose_replacement.event": {"zone_change", "damage", "draw", "enter_battlefield", "counters", "life", "other"},
	"color":                    {"white", "blue", "black", "red", "green"},
	"mana_symbol":              {"W", "U", "B", "R", "G", "C"},
	"card_type":                {"artifact", "battle", "conspiracy", "creature", "dungeon", "enchantment", "instant", "kindred", "land", "phenomenon", "plane", "planeswalker", "scheme", "sorcery", "vanguard"},
}

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

func sem(kind string, kv ...any) Semantic {
	f := make(map[string]any, len(kv)/2)
	for i := 0; i < len(kv); i += 2 {
		f[kv[i].(string)] = kv[i+1]
	}
	return Semantic{Kind: kind, Fields: f}
}

func Pass() Semantic                                 { return sem("pass") }
func PlayLand(src ObjectRef, face uint32) Semantic    { return sem("play_land", "source", src, "face", face) }
func CastSpell(src ObjectRef, method string) Semantic { return sem("cast_spell", "source", src, "method", method) }
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

func u(s Semantic, k string) uint32 { v, _ := s.Fields[k].(uint32); return v }

func inVocab(list, v string) bool { return slices.Contains(Vocab[list], v) }

// Check enforces Section 7.3's field constraints and the vocabularies.
func (s Semantic) Check() error {
	want, ok := KindFields[s.Kind]
	if !ok {
		return fmt.Errorf("unknown kind %q", s.Kind)
	}
	if len(want) != len(s.Fields) {
		return fmt.Errorf("%s has %d fields, want %d", s.Kind, len(s.Fields), len(want))
	}
	for _, f := range want {
		if _, ok := s.Fields[f]; !ok {
			return fmt.Errorf("%s lacks %s", s.Kind, f)
		}
	}
	str := func(k string) string { v, _ := s.Fields[k].(string); return v }
	switch s.Kind {
	case "choose_target", "choose_cost_target", "select_object":
		if !(u(s, "minimum") <= u(s, "maximum") && u(s, "selected_count") < u(s, "maximum")) {
			return fmt.Errorf("%s counts out of range", s.Kind)
		}
	case "choose_spell_mode":
		if !(u(s, "mode_index") < u(s, "mode_count") && u(s, "minimum") <= u(s, "maximum") &&
			u(s, "maximum") <= u(s, "mode_count") && u(s, "selected_count") < u(s, "maximum")) {
			return fmt.Errorf("choose_spell_mode counts out of range")
		}
	case "choose_number":
		v, lo, hi := s.Fields["value"].(int32), s.Fields["minimum"].(int32), s.Fields["maximum"].(int32)
		if !(lo <= v && v <= hi) {
			return fmt.Errorf("choose_number %d outside [%d,%d]", v, lo, hi)
		}
	case "order_pick":
		if !(u(s, "position") < u(s, "count")) {
			return fmt.Errorf("order_pick position out of range")
		}
	case "arrange_card":
		if !(u(s, "card_index") < u(s, "card_count")) || !inVocab("arrange_card.destination", str("destination")) {
			return fmt.Errorf("arrange_card out of range")
		}
	case "choose_replacement":
		if !(2 <= u(s, "replacement_count") && u(s, "replacement_index") < u(s, "replacement_count")) {
			return fmt.Errorf("choose_replacement counts out of range")
		}
	case "distribute":
		if !(u(s, "amount") <= u(s, "remaining")) {
			return fmt.Errorf("distribute amount exceeds remaining")
		}
	case "choose_color":
		if !inVocab("color", str("color")) {
			return fmt.Errorf("color %q", str("color"))
		}
	case "cast_spell", "optional_cast":
		if !inVocab("method", str("method")) {
			return fmt.Errorf("method %q", str("method"))
		}
	}
	for _, f := range []string{"purpose", "cost", "cost_kind", "action", "event"} {
		if v, ok := s.Fields[f].(string); ok {
			if list, ok := Vocab[s.Kind+"."+f]; ok && !slices.Contains(list, v) {
				return fmt.Errorf("%s.%s %q not in vocabulary", s.Kind, f, v)
			}
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
	Tapped           bool              `json:"tapped"`
	SummoningSick    bool              `json:"summoning_sick"`
	Damage           uint32            `json:"damage"`
	Counters         map[string]uint32 `json:"counters"`
	AttachedTo       *TargetRef        `json:"attached_to"`
	Attacking        bool              `json:"attacking"`
	AttackTarget     *TargetRef        `json:"attack_target"`
	Blocking         bool              `json:"blocking"`
	BlockedAttackers []ObjectRef       `json:"blocked_attackers"`
	PhasedOut        bool              `json:"phased_out"`
	Statuses         []string          `json:"statuses"`
	ClassLevel       *uint32           `json:"class_level"`
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
	Progress            *struct{}         `json:"progress"`
	HandCount           uint32            `json:"hand_count"`
	LibraryCount        uint32            `json:"library_count"`
	Hand                []ObjectRecord    `json:"hand"`
	Battlefield         []ObjectRecord    `json:"battlefield"`
	Graveyard           []ObjectRecord    `json:"graveyard"`
	Exile               []ObjectRecord    `json:"exile"`
	Command             []ObjectRecord    `json:"command"`
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
	ActingSeat  string                     `json:"acting_seat"`
	SeatStep    uint64                     `json:"seat_step"`
	Group       Group                      `json:"group"`
	Context     Context                    `json:"context"`
	Observation Observation                `json:"observation"`
	Candidates  []Candidate                `json:"candidates"`
	Extensions  map[string]json.RawMessage `json:"extensions"`
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
	ProtocolMinor  uint64              `json:"protocol_minor"`
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
Expected: `--- PASS: TestThirtyKinds`, `--- PASS: TestConstructorsEmitExactlyTheSpecFields`, `--- PASS: TestCheckEnforcesFieldConstraints`, `--- PASS: TestTargetRefAndNullableFields`.

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

func getStr(o obj, k string) (string, error) {
	var s string
	if err := json.Unmarshal(o[k], &s); err != nil {
		return "", fmt.Errorf("%s is not a string", k)
	}
	return s, nil
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
	p, ok := o["protocol"]
	if !ok {
		return req, Errf(CodeMalformedRequest, "missing protocol")
	}
	var ps string
	if json.Unmarshal(p, &ps) != nil {
		return req, Errf(CodeMalformedRequest, "protocol is not a string")
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
	m, err := getU64(o, "protocol_minor")
	req.Hello = &HelloReq{ProtocolMinor: m}
	return err
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
		err = json.Unmarshal(d["decklist"], &s.Decklist)
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
	if err := json.Unmarshal(dom["names"], &r.Names); err != nil {
		return r, errors.New("card_name_domain.names")
	}
	if err := json.Unmarshal(o["extensions"], &r.Extensions); err != nil || r.Extensions == nil {
		return r, errors.New("extensions")
	}
	if err := json.Unmarshal(o["probe"], &r.Probe); err != nil {
		return r, errors.New("probe")
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
		err = json.Unmarshal(d["decklist"], &v.Deck.Decklist)
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
	p.Samples, err = getU64(o, "samples")
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
- Consumes: `wire.DeckRow`, `wire.DeckID` (Task 3), `testcorpus.Registry` (Task 1).
- Produces:
  - `type catalog.Deck struct{ CatalogID, Name string; Rows []wire.DeckRow }` with `func (Deck) DeckID() string`;
  - `func catalog.Decks() []Deck` (five decks, benchmark order Wildfire, Rally, Spy, Burn, CawGates);
  - `func catalog.ByID(id string) (Deck, bool)`;
  - `func catalog.Resolve(reg *cards.Registry, d Deck) ([]*cards.Card, error)` (row order, expanded by count);
  - `func catalog.Preflight(reg *cards.Registry) error`;
  - `func catalog.PoolNames() []string` (sorted distinct names).

- [ ] **Step 1: Write the failing test**

`internal/catalog/catalog_test.go`:

```go
package catalog_test

import (
	"strings"
	"testing"

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
	if got := wire.DomainID(catalog.PoolNames()); got != "sha256:ab186e0272634f91dad9dd7b5765f33b69b3dc91bdfb1f6e43879be6ea49ba5b" {
		t.Errorf("pool domain_id %s", got)
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
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

type Deck struct {
	CatalogID, Name string
	Rows            []wire.DeckRow
}

func (d Deck) DeckID() string { return wire.DeckID(d.Rows) }

var decks = []Deck{
	{CatalogID: "Wildfire", Name: "Wildfire", Rows: []wire.DeckRow{
		{"Twisted Landscape", 4}, {"Fanatical Offering", 4}, {"Ichor Wellspring", 3}, {"Blood Fountain", 1},
		{"Drossforge Bridge", 4}, {"Slagwoods Bridge", 4}, {"Writhing Chrysalis", 4}, {"Nyxborn Hydra", 1},
		{"Vault of Whispers", 1}, {"Cleansing Wildfire", 4}, {"Lembas", 3}, {"Makeshift Munitions", 1},
		{"Cast Down", 4}, {"Nihil Spellbomb", 4}, {"Swamp", 3}, {"Mountain", 2}, {"Forest", 2},
		{"Refurbished Familiar", 4}, {"Krark-Clan Shaman", 3}, {"Eviscerator's Insight", 1}, {"Toxin Analysis", 2},
		{"Pulse of Murasa", 1},
	}},
	{CatalogID: "Rally", Name: "Rally", Rows: []wire.DeckRow{
		{"Clockwork Percussionist", 4}, {"Voldaren Epicure", 4}, {"Goblin Bushwhacker", 4},
		{"Goblin Tomb Raider", 4}, {"Burning-Tree Emissary", 4}, {"Galvanic Blast", 4},
		{"Experimental Synthesizer", 3}, {"Lightning Bolt", 4}, {"Reckless Impulse", 4},
		{"Rally at the Hornburg", 4}, {"Great Furnace", 4}, {"Mountain", 14}, {"Chain Lightning", 2},
		{"End the Festivities", 1},
	}},
	{CatalogID: "Spy", Name: "Spy", Rows: []wire.DeckRow{
		{"Mesmeric Fiend", 2}, {"Overgrown Battlement", 4}, {"Saruli Caretaker", 4}, {"Gatecreeper Vine", 3},
		{"Sagu Wildling // Roost Seek", 4}, {"Generous Ent", 4}, {"Lead the Stampede", 4}, {"Winding Way", 4},
		{"Land Grant", 4}, {"Balustrade Spy", 4}, {"Lotleth Giant", 2}, {"Dread Return", 2}, {"Swamp", 1},
		{"Forest", 3}, {"Wall of Roots", 3}, {"Masked Vandal", 3}, {"Quirion Ranger", 2},
		{"Troll of Khazad-dûm", 1}, {"Lotus Petal", 2}, {"Tinder Wall", 2}, {"Elves of Deep Shadow", 2},
	}},
	{CatalogID: "Burn", Name: "Burn", Rows: []wire.DeckRow{
		{"Sneaky Snacker", 4}, {"Faithless Looting", 2}, {"Highway Robbery", 4}, {"Masked Meower", 4},
		{"Lightning Bolt", 4}, {"Mountain", 18}, {"Grab the Prize", 4}, {"Fireblast", 4}, {"Guttersnipe", 4},
		{"Fiery Temper", 4}, {"Voldaren Epicure", 4}, {"Lava Dart", 4},
	}},
	{CatalogID: "CawGates", Name: "CawGates", Rows: []wire.DeckRow{
		{"Island", 4}, {"Citadel Gate", 4}, {"Counterspell", 4}, {"Heap Gate", 2}, {"Idyllic Beachfront", 1},
		{"Brainstorm", 3}, {"Journey to Nowhere", 4}, {"Lórien Revealed", 3}, {"Outlaw Medic", 2},
		{"Basilisk Gate", 4}, {"Sacred Cat", 4}, {"Sea Gate", 4}, {"Azorius Guildgate", 2},
		{"The Modern Age // Vector Glider", 4}, {"Thraben Charm", 2}, {"Prismatic Strands", 4},
		{"Squadron Hawk", 4}, {"Spell Pierce", 2}, {"Preordain", 2}, {"Guardian of the Guildpact", 1},
	}},
}

func Decks() []Deck { return decks }

func ByID(id string) (Deck, bool) {
	for _, d := range decks {
		if d.CatalogID == id {
			return d, true
		}
	}
	return Deck{}, false
}

// lookup resolves an Oracle name exactly: gorge's NormalizeName keeps
// diacritics, and the front face of "A // B" must name a card whose faces
// join to exactly that full name.
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
// (every primitive its script names is implemented).
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
Expected: `--- PASS: TestDeckIDsMatchHostComputation`, `--- PASS: TestEveryCatalogCardResolvesAndIsFullyPlayable`, `--- PASS: TestAsciiFoldedNameIsNotSubstituted`.

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

- [ ] **Step 1: Write the failing test**

`internal/gamecfg/game_test.go`:

```go
package gamecfg_test

import (
	"context"
	"errors"
	"testing"

	"github.com/adams-shaun/gorge/cards"
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
Expected: `--- PASS: TestStartingSeatIsForcedAndGamesAreDeterministic`, `--- PASS: TestSeatOneLibraryIsIndependentOfSeatZero`, `--- PASS: TestUnplannedRandomnessIsDetected`.

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
  - `func (*Stream) Check(sd protocol.SeatDecision) error`, which returns a `*validate.Violation{Rule, Msg string}` naming V1 to V9.

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

var extKey = regexp.MustCompile(`^x_[a-z0-9_]+$`)

// EqualRef compares references by value (CardName is a pointer).
func EqualRef(a, b protocol.ObjectRef) bool {
	return a.ObjectID == b.ObjectID && a.OwnerSeat == b.OwnerSeat && a.ControllerSeat == b.ControllerSeat &&
		a.Zone == b.Zone && (a.CardName == nil) == (b.CardName == nil) && (a.CardName == nil || *a.CardName == *b.CardName)
}

// records collects every object record and reference of the observation by id.
func records(o protocol.Observation) (map[string]protocol.ObjectRef, error) {
	out := map[string]protocol.ObjectRef{}
	add := func(r protocol.ObjectRef) error {
		if prev, ok := out[r.ObjectID]; ok && !EqualRef(prev, r) {
			return vio("V4", "id %s names two different records", r.ObjectID)
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
	// V1 candidates
	if len(sd.Candidates) == 0 || len(sd.Candidates) > 4096 {
		return vio("V1", "%d candidates", len(sd.Candidates))
	}
	seen := map[string]bool{}
	priority := 0
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
	}
	// V9
	switch {
	case sd.Context.Kind == "priority" && priority != len(sd.Candidates):
		return vio("V9", "priority context with choice candidates")
	case sd.Context.Kind == "choice" && priority > 0:
		for _, c := range sd.Candidates {
			if protocol.PriorityKinds[c.Semantic.Kind] && c.Semantic.Kind != "activate_mana_ability" {
				return vio("V9", "choice context with %s", c.Semantic.Kind)
			}
		}
		if sd.Context.Purpose == nil || *sd.Context.Purpose != "mana_payment" {
			return vio("V9", "activate_mana_ability in a choice decision without mana_payment")
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
	// V8 optional fields
	if !s.p.Flags["day_night"] && o.DayNight != nil {
		return vio("V8", "day_night set without its flag")
	}
	if !s.p.Flags["passed_seats"] && o.PassedSeats != nil {
		return vio("V8", "passed_seats set without its flag")
	}
	if s.p.Flags["pending_triggers"] != (o.PendingTriggers != nil) {
		return vio("V8", "pending_triggers presence does not match its flag")
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
	for _, c := range sd.Candidates {
		if err := walkRefs(c.Semantic, func(r protocol.ObjectRef) error {
			if rec, ok := recs[r.ObjectID]; !ok || !EqualRef(rec, r) {
				return vio("V4", "candidate references %s, not equal to its observation record", r.ObjectID)
			}
			return nil
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
Expected: `--- PASS: TestValidSequencePasses`, `--- PASS: TestViolationsNameTheirRule`, `--- PASS: TestIDFreshnessAcrossTheSeatStream`.

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
  - look handling: `func (*Tracker) OpenLook(viewer state.PlayerID)`, `func (*Tracker) LookID(viewer state.PlayerID, id state.ObjID) (string, error)`, `func (*Tracker) CloseLook(viewer state.PlayerID)`;
  - `var identity.ErrIDCollision`, `var identity.ErrShadowDiverged`;
  - `testgame.New(t, reg, deck0, deck1 string, secretByte byte, mulligan string) *gamecfg.Game`;
  - `testgame.RunUntil(t, g, bots [2]seat.Seat, pred func(*rules.Engine) bool, maxIntents int) bool`;
  - `testgame.Bots(seed uint64) [2]seat.Seat`.

Design note: gorge keeps one `ObjID` across zone changes. Section 5.3 needs a fresh id on every zone change, including round trips inside one engine step: a London mulligan moves hand to library to hand inside one `Submit`. The tracker therefore replays each new engine event through `events.Apply` on a shadow `state.Game` and counts every zone change exactly. A shadow that disagrees with the engine is a hard error (`halted`).

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
		t.Skip("card never left hand in this seed; pick another seed if this fires")
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	after, _ := tr.VisibleID(0, card)
	if after == inHand {
		t.Fatalf("id %s survived a zone change", after)
	}
}

func TestMulliganRoundTripGivesFreshIDs(t *testing.T) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, "Spy", "Spy", 2, "london")
	tr := identity.New(g.E, g.Secret)
	d := g.E.Pending()
	if d.Kind != decision.KMulligan {
		t.Fatalf("first decision %s, want mulligan", d.Kind)
	}
	before := map[string]bool{}
	for _, id := range g.E.G.Zone(state.ZHand, d.Player) {
		oid, _ := tr.VisibleID(d.Player, id)
		before[oid] = true
	}
	var mull int
	for _, o := range d.Options {
		if o.Kind == "mulligan" {
			mull = o.Index
		}
	}
	if err := g.Submit(decision.Intent{Seq: d.Seq, Player: d.Player, Choices: []int{mull}}); err != nil {
		t.Fatal(err)
	}
	if err := tr.Sync(g.E); err != nil {
		t.Fatal(err)
	}
	for _, id := range g.E.G.Zone(state.ZHand, d.Player) {
		oid, _ := tr.VisibleID(d.Player, id)
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
	tr.CloseLook(0)
	if a != b || a == c {
		t.Fatalf("look ids %s %s %s", a, b, c)
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

type Tracker struct {
	sec     *secrets.Game
	shadow  *state.Game
	applied int
	moves   map[state.ObjID]uint32
	looks   map[lookKey]uint32
	open    [2]map[string]uint32
	seen    [2]map[string]string
	zbuf    []state.Zone
}

func New(e *rules.Engine, sec *secrets.Game) *Tracker {
	return &Tracker{sec: sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: map[state.ObjID]uint32{}, looks: map[lookKey]uint32{},
		seen: [2]map[string]string{{}, {}}}
}

// Sync folds the events appended since the last call into the shadow game,
// counting every zone change per object, then checks the shadow against the engine.
func (t *Tracker) Sync(e *rules.Engine) error {
	for ; t.applied < len(e.L.Events); t.applied++ {
		t.zbuf = t.zbuf[:0]
		for i := range t.shadow.Objs {
			t.zbuf = append(t.zbuf, t.shadow.Objs[i].Zone)
		}
		events.Apply(t.shadow, e.L.Events[t.applied])
		for i := range t.zbuf {
			if t.shadow.Objs[i].Zone != t.zbuf[i] {
				t.moves[t.shadow.Objs[i].ID]++
			}
		}
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

// Key is the internal key of Section 5.3: stable for one stay in one zone.
func (t *Tracker) Key(id state.ObjID) string { return fmt.Sprintf("%d:z%d", id, t.moves[id]) }

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

// OpenLook starts one effect's look for viewer; CloseLook ends it.
func (t *Tracker) OpenLook(viewer state.PlayerID) { t.open[viewer] = map[string]uint32{} }

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
- Test: `internal/observe/project_test.go`, `internal/observe/vocab_test.go`

**Interfaces:**
- Consumes: `identity.Tracker` (Task 10), protocol types (Task 5), `testgame` (Task 10).
- Produces:
  - `var observe.Flags map[string]bool` (the 13 flags, true only for `pending_triggers` and `keywords`);
  - `type observe.Projector struct{ E *rules.Engine; IDs *identity.Tracker; Mulls [2]uint32 }` and `type observe.State struct{ PriorityHolder *state.PlayerID; Known []protocol.Known }`;
  - `func (*Projector) Observation(viewer state.PlayerID, st State) (protocol.Observation, error)`;
  - `func (*Projector) Ref(viewer state.PlayerID, id state.ObjID) (*protocol.ObjectRef, error)` (nil when absent or hidden);
  - `func (*Projector) Record(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRecord, error)`;
  - `func (*Projector) LookRef(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRef, error)` (a hidden-zone object shown by the open look);
  - vocab helpers: `observe.Seat(p) string`, `observe.PhaseStep(g) string`, `observe.Visible(viewer, o) bool`, `observe.MayLook(viewer, o) bool`, `observe.Normalize(s) string`, `observe.Counter(kind) string`, `observe.Keywords([]string) []string`, `observe.Colors(letters string) []string`.

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
	"strings"
	"testing"

	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
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
	for _, name := range []string{"Counterspell", "Brainstorm", "Squadron Hawk"} { // CawGates cards p0 cannot see
		for _, rec := range obs.Players[1].Battlefield {
			if rec.CardName != nil && *rec.CardName == name && rec.Zone != "battlefield" {
				t.Fatalf("hidden %s visible", name)
			}
		}
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
		if src := p.E.G.Obj(o.Source); src != nil && src.Face() != nil {
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

// LookRef references a hidden-zone object the open look shows to viewer.
func (p *Projector) LookRef(viewer state.PlayerID, id state.ObjID) (protocol.ObjectRef, error) {
	o := p.E.G.Obj(id)
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
	if f := o.Face(); f != nil {
		c.ManaValue = uint32(max(0, botpolicy.CmcOf(f.ManaCost)))
	}
	if slices.Contains(c.Types, "creature") {
		pw, tg := d.Power, d.Toughness
		c.Power, c.Toughness = &pw, &tg
	}
	return c
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

Also in this task, add stubs that Task 12 replaces: `func (b *builder) permanent(o *state.Object) (*protocol.Permanent, error)` returning tapped, summoning sick, damage and counters only, and `func (b *builder) stackAndPending(obs *protocol.Observation, v view.View) error { return nil }`. Task 12 owns both bodies.

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
Expected: `--- PASS: TestVocabularyNormalization`, `--- PASS: TestObservationHidesTheOtherHandAndLibraries`, `--- PASS: TestCharacteristicsOfBasicLandAndBolt`.

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
- Consumes: Task 11's `builder`, `Projector`, `Ref`, `Characteristics`.
- Produces:
  - full `(*builder).permanent` (attached_to, attacking, attack_target, blocking and blocked_attackers inverted from `BlockedBy`);
  - `(*builder).stackAndPending`: stack entries, pending triggers, with triggers whose source is hidden from the viewer omitted (Section 6.6);
  - `func observe.SortKnown(ks []protocol.Known)`;
  - `func observe.KnownEntry(ref protocol.ObjectRef, how string, fromTop *uint32) protocol.Known`.

- [ ] **Step 1: Write the failing test**

`internal/observe/combat_stack_test.go`:

```go
package observe_test

import (
	"testing"

	"github.com/adams-shaun/gorge/rules"
	"github.com/adams-shaun/gorge/state"
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
			if e.G.Objs[i].IsAttacking && len(e.G.Objs[i].BlockedBy) > 0 {
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/observe/ -run 'Blocking|StackEntry|SortKnown'`
Expected: FAIL: `undefined: observe.SortKnown`, and the combat test fails on `blockers 0` against the Task 11 stub.

- [ ] **Step 3: Write minimal implementation**

Delete the two stubs from `project.go` and create `internal/observe/combat_stack.go`:

```go
package observe

import (
	"strings"

	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

func (b *builder) blockMap() map[state.ObjID][]state.ObjID {
	if b.blocking == nil {
		b.blocking = map[state.ObjID][]state.ObjID{}
		g := b.p.E.G
		for i := range g.Objs {
			a := &g.Objs[i]
			if a.Zone == state.ZBattlefield && a.IsAttacking {
				for _, blk := range a.BlockedBy {
					b.blocking[blk] = append(b.blocking[blk], a.ID)
				}
			}
		}
	}
	return b.blocking
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
			r, err := b.p.Ref(b.viewer, o.AttackingBattle)
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
	for _, a := range b.blockMap()[o.ID] {
		pm.Blocking = true
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

var stackKinds = map[string]string{"spell": "spell", "trigger": "triggered_ability", "ability": "activated_ability"}

func (b *builder) stackAndPending(obs *protocol.Observation, v view.View) error {
	g := b.p.E.G
	for _, sv := range v.Stack {
		o := g.Obj(sv.ID)
		ref, err := b.p.Ref(b.viewer, sv.ID)
		if err != nil || ref == nil {
			return err
		}
		se := protocol.StackEntry{ObjectRef: *ref, StackKind: stackKinds[sv.Kind], FaceDown: o.FaceDown, Copy: o.IsCopy,
			Targets: []*protocol.TargetRef{}}
		if o.Ability != nil {
			if src := g.Obj(o.Source); src != nil && src.Incarnation == o.SourceIncarnation {
				if se.Source, err = b.p.Ref(b.viewer, o.Source); err != nil {
					return err
				}
			}
		} else {
			se.Characteristics = b.p.Characteristics(b.viewer, o)
		}
		for _, t := range o.Targets {
			if t.IsPlayer {
				pt := protocol.PlayerTarget(Seat(t.Player))
				se.Targets = append(se.Targets, &pt)
				continue
			}
			r, err := b.p.Ref(b.viewer, t.Obj)
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
Expected: all observe tests PASS (five tests).

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
  - `type mapping.ActionContext struct{ Seat state.PlayerID; Obj state.ObjID }`;
  - `type mapping.NativeOp struct{ Op string; Option int; Followup []int; List string; Position int; Unit state.ObjID; Covers []int }` (JSON tags `op`, `option`, `followup`, `list`, `position`, `unit`, `covers`);
  - `type mapping.Cand struct{ Sem protocol.Semantic; Op NativeOp; Hidden bool; SortName, SortID string }`;
  - `type mapping.Pose struct{ Seat state.PlayerID; Context protocol.Context; GroupStart bool; SubstepIndex, SubstepCount uint32; Candidates []Cand; Known []protocol.Known; Look bool; Native *decision.Decision; Followups map[string]*decision.Decision; Splits [][]int32 }`;
  - `type mapping.Transaction interface{ Pose() (*Pose, error); Answer(i int) (commit []decision.Intent, done bool, err error) }`;
  - `func mapping.Begin(env *Env, d *decision.Decision) (Transaction, error)`, `func mapping.Register(route string, f Builder)`, `type mapping.Builder func(*Env, *decision.Decision) (Transaction, error)`, `func mapping.Route(d *decision.Decision) string`;
  - `func mapping.ResolveSource(env *Env, d *decision.Decision) (*protocol.ObjectRef, error)` and `func mapping.MustSource(env *Env, d *decision.Decision) (protocol.ObjectRef, error)`;
  - `func mapping.Accepts(env *Env, ins ...decision.Intent) bool`, `func mapping.Intent(d *decision.Decision, choices ...int) decision.Intent`;
  - `func mapping.Finalize(p *Pose) error` (pass first, hidden-zone candidate order, distinct semantics, 4096 cap);
  - `type mapping.PickSpec` and `func mapping.NewPick(env *Env, s PickSpec) Transaction` (the generic one-pick-per-decision subset transaction used by Tasks 17 to 19), plus the unexported helper `allOptions(d)`;
  - `func mapping.SingleChoice(env *Env, d *decision.Decision, ctx protocol.Context, sem func(decision.Option) (protocol.Semantic, bool, error)) (Transaction, error)`, with the unexported `singleTx` (an `after` hook field) and `choice(src, purpose)`, used by Tasks 20 and 21;
  - errors `mapping.ErrDeadEnd`, `mapping.ErrUnmapped`, `mapping.ErrCandidateLimit`, `mapping.ErrDuplicate`, `mapping.ErrUnresolvableSource`;
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

type ActionContext struct {
	Seat state.PlayerID
	Obj  state.ObjID
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
// partition, Task 19), "amount" (a distribute amount).
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
	Splits                     [][]int32
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
//     or Decision.Source itself when it is on the stack;
//  2. the current visible incarnation of Decision.Source;
//  3. the object of the acting seat's last priority action (gorge chooses an
//     activated ability's targets and costs before pushing it: sourceprobe);
//  4. nil.
func ResolveSource(env *Env, d *decision.Decision) (*protocol.ObjectRef, error) {
	g := env.G.E.G
	if d.Source != 0 {
		for i := len(g.Stack) - 1; i >= 0; i-- {
			if so := g.Obj(g.Stack[i]); so != nil && so.Ability != nil && so.Source == d.Source {
				return env.Obs.Ref(d.Player, g.Stack[i])
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
  - `func mapping.CastMethod(o decision.Option) (method string, optional string, special string, ok bool)`, with the mode tables below;
  - `func mapping.NonManaAbilityIndex(o *state.Object, abilityIdx int) uint32`.

Mode tables:
- method:
  - `"" mayplay mayflash` → `normal`; `flashback` → `flashback`; `plot_cast` → `plot`;
  - `bestowed surged blitzed emerged mutated` → `alternative`, as is any option with `AltCostIndex > 0`;
  - `escape` → `escape`; `madness` → `madness`; `miracle` → `miracle`; `foretell_cast` → `foretell`; `adventure_alt` → `adventure`; `split_alt` → `split_right`; `fuse` → `fuse`; `suspend_cast` → `suspend`; `modal_spell` → `mdfc_back`.
- optional cost: `kicked` → `kicker`, `buyback` → `buyback`, `entwined` → `entwine`, `conspired` → `conspire`, `casualty` → `casualty`, `offspring` → `offspring`.
- special action: cast `Mode` `plot` → `special_action` `plot`; priority kinds `turn_face_up` → `turn_face_up`, `unlock` → `unlock_door`.
- `concede` is never offered. Any other mode or kind fails closed as unmapped.
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
```

(`priority_test.go` also imports `github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'Priority|Kicker'`
Expected: FAIL with `engine_contract_failure:unmapped_decision:priority`.

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

// CastMethod classifies a "cast" option: a method, or an optional cost over
// the normal method, or a special action.
func CastMethod(o decision.Option) (method, optional, special string, ok bool) {
	if o.Mode == "plot" {
		return "", "", "plot", true
	}
	if c, ok := optionalCostModes[o.Mode]; ok {
		return "normal", c, "", true
	}
	if o.AltCostIndex > 0 {
		return "alternative", "", "", true
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
			method, optional, special, ok := CastMethod(o)
			if !ok {
				return nil, fmt.Errorf("%w:cast_mode/%s", ErrUnmapped, o.Mode)
			}
			if special != "" {
				p.Candidates = append(p.Candidates, Cand{Sem: protocol.SpecialAction(src, special), Op: NativeOp{Op: "choose", Option: o.Index}})
				continue
			}
			key := fmt.Sprint(o.Obj, "/", method)
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

The session fills each follow-up intent's `Seq` and `Player` from the engine's pending decision at commit time, and checks that the follow-up is the decision the lookahead saw (Task 22).

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'Priority|Kicker' -v`
Expected: `--- PASS: TestPriorityPassFirstAndNoConcede`, `--- PASS: TestKickerBecomesAFollowUpOptionalCost`.

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
- Consumes: framework (Task 13), `gamecfg.Game.Probe`.
- Produces:
  - replaces `mapping.ExpandActivate` (in `init()`);
  - `func mapping.ManaSymbol(o decision.Option) (string, bool)` (from `Option.ManaSymbol`, else a label ending `Add X`);
  - registered route `choose/mana`, which reaches the session only if a fold was missed; it fails closed.

Rules:
- The lookahead submits the activation on a clone.
- If the clone's next pending decision belongs to the same seat and is a mana follow-up, it is folded: colour options (`mana`) become `mana_choice`; single-object cost picks (`tapcost`, `sacrifice`, `discard`, `exile_cost`, `returncost`) become `cost_target`, recursing once for a colour after a cost.
- A plain source (basic land) is one candidate with `mana_choice: null`.
- `Followups` records each folded native follow-up decision, keyed `"<option>"` or `"<option>/<cost option>"`, for `x_gorge_view_v1`.

- [ ] **Step 1: Write the failing test**

`internal/mapping/mana_test.go`:

```go
package mapping_test

import (
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run DualLand`
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
		folds[key] = next
		var out []Cand
		for _, co := range next.Options {
			sym, ok := ManaSymbol(co)
			if !ok {
				return nil, nil, fmt.Errorf("%w:mana_option/%q", ErrUnmapped, co.Label)
			}
			out = append(out, Cand{Sem: protocol.ActivateManaAbility(src, 0, &sym, nil),
				Op: NativeOp{Op: "choose", Option: o.Index, Followup: []int{co.Index}}})
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
Expected: all mapping tests so far PASS, including `TestDualLandExpandsIntoOneCandidatePerColour`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: mana abilities folded with colour and cost lookahead"
```

---

### Task 16: Combat: declare_attack, declare_block, distribute

**Files:**
- Create: `internal/mapping/combat.go`
- Test: `internal/mapping/combat_test.go`

**Interfaces:**
- Consumes: framework (Task 13): `Accepts`, `Finalize`, `Intent`, `Register`.
- Produces:
  - registered routes `attackers`, `blockers`, `choose/division`;
  - `func mapping.Compositions(power int32, n int) [][]int32`, which reproduces gorge's `divisionOptions` enumeration order.

Rules (Section 7.5 Combat):
- One fixed group with one decision per creature that appears in the native options, in first-appearance order.
- A blocker whose group cap exceeds 1 gets one decision per additional block.
- Candidates: each legal defender (attack) or attacker (block), plus `null`.
- A candidate is offered only if some full declaration extending the current prefix is accepted by the engine: prefix alone, then the prefix repaired by `decision.FitRequired` (only if the repair keeps the prefix), then a bounded depth-first search.
- Division: one `distribute` per blocker, in gorge's blocker order; candidates are the amounts that appear in a legal composition consistent with the earlier picks.

- [ ] **Step 1: Write the failing test**

`internal/mapping/combat_test.go`:

```go
package mapping_test

import (
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
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
```

`combat_test.go` also imports `github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol`.

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'AttackGroup|Compositions'`
Expected: FAIL with `unmapped_decision:attackers` and `undefined: mapping.Compositions`.

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
	Register("choose/division", newDivision)
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
	if fr := t.d.FitRequired(prefix); len(fr) >= len(prefix) && slices.Equal(fr[:len(prefix)], prefix) && t.accepts(fr) {
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

type divisionTx struct {
	env      *Env
	d        *decision.Decision
	src      *protocol.ObjectRef
	blockers []protocol.ObjectRef
	splits   [][]int32
	power    int32
	chosen   []int32
	pose     *Pose
}

func newDivision(env *Env, d *decision.Decision) (Transaction, error) {
	g := env.G.E.G
	a := g.Obj(d.Source)
	if a == nil || len(d.Options) == 0 {
		return nil, fmt.Errorf("%w:division_without_attacker", ErrUnmapped)
	}
	power := int32(d.Options[len(d.Options)-1].Amount)
	var live []state.ObjID
	for _, b := range a.BlockedBy {
		if o := g.Obj(b); o != nil && o.Zone == state.ZBattlefield {
			live = append(live, b)
		}
	}
	splits := Compositions(power, len(live))
	if len(splits) != len(d.Options) {
		return nil, fmt.Errorf("%w:division_layout", ErrUnmapped)
	}
	t := &divisionTx{env: env, d: d, splits: splits, power: power}
	for i, o := range d.Options {
		parts := strings.Split(o.Label, ",")
		if int32(o.Amount) != splits[i][0] || len(parts) != len(live) {
			return nil, fmt.Errorf("%w:division_layout", ErrUnmapped)
		}
	}
	for _, b := range live {
		r, err := env.Obs.Ref(d.Player, b)
		if err != nil || r == nil {
			return nil, fmt.Errorf("%w:division_blocker", ErrUnmapped)
		}
		t.blockers = append(t.blockers, *r)
	}
	var err error
	t.src, err = env.Obs.Ref(d.Player, d.Source)
	return t, err
}

func (t *divisionTx) consistent(s []int32) bool { return slices.Equal(s[:len(t.chosen)], t.chosen) }

func (t *divisionTx) Pose() (*Pose, error) {
	r := len(t.chosen)
	var sum int32
	for _, v := range t.chosen {
		sum += v
	}
	p := &Pose{Seat: t.d.Player, Context: protocol.Context{Kind: "choice", Source: t.src, Purpose: purpose("combat_damage")},
		GroupStart: r == 0, SubstepIndex: uint32(r), SubstepCount: uint32(len(t.blockers)), Native: t.d, Splits: t.splits}
	seen := map[int32]bool{}
	for _, s := range t.splits {
		if t.consistent(s) && !seen[s[r]] {
			seen[s[r]] = true
			p.Candidates = append(p.Candidates, Cand{
				Sem: protocol.Distribute(t.src, "combat_damage", protocol.ObjectTarget(t.blockers[r]), uint32(s[r]), uint32(t.power-sum)),
				Op:  NativeOp{Op: "amount", Option: -1, Position: r}})
		}
	}
	if err := Finalize(p); err != nil {
		return nil, err
	}
	t.pose = p
	return p, nil
}

func (t *divisionTx) Answer(i int) ([]decision.Intent, bool, error) {
	t.chosen = append(t.chosen, int32(t.pose.Candidates[i].Sem.Fields["amount"].(uint32)))
	if len(t.chosen) < len(t.blockers) {
		return nil, false, nil
	}
	for k, s := range t.splits {
		if slices.Equal(s, t.chosen) {
			return []decision.Intent{Intent(t.d, k)}, true, nil
		}
	}
	return nil, false, ErrDeadEnd
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/mapping/ -run 'AttackGroup|Compositions' -v`
Expected: `--- PASS: TestAttackGroupHasOneDecisionPerCreature`, `--- PASS: TestCompositionsMatchGorgeOrder`.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: attack and block declarations with witnesses, combat damage distribution"
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
    - any library destination: delegated to the route `hand_move/library` registered by Task 19;
  - `choose/untap` (`untap`), `choose/keep` (`legend_rule`);
  - `modes/mode` (`choose_spell_mode`, `finish_selection` `modes` when variable).

- [ ] **Step 1: Write the failing test**

`internal/mapping/select_test.go`:

```go
package mapping_test

import (
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

func TestModalSpellUsesChooseSpellMode(t *testing.T) {
	g := untilPending(t, "CawGates", 1, func(d *decision.Decision, e *rules.Engine) bool {
		return d.Kind == decision.KModes && d.ResumeKind == "cast_modes"
	})
	env := envFor(t, g)
	tx, _ := mapping.Begin(env, g.E.Pending())
	p, _ := tx.Pose()
	c := p.Candidates[0].Sem
	if c.Kind != "choose_spell_mode" || c.Fields["mode_count"] != uint32(len(g.E.Pending().Options)) {
		t.Fatalf("%+v", c)
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

func newModes(env *Env, d *decision.Decision) (Transaction, error) {
	src, err := MustSource(env, d)
	if err != nil {
		return nil, err
	}
	n, lo, hi := uint32(len(d.Options)), uint32(d.Min), uint32(d.Max)
	purp := "modes"
	return NewPick(env, PickSpec{D: d, Options: allOptions(d), Context: protocol.Context{Kind: "choice", Source: &src},
		Sem: func(opt int, sel uint32) (Cand, error) {
			return Cand{Sem: protocol.ChooseSpellMode(src, uint32(opt), n, sel, lo, hi)}, nil
		},
		Finish: func(sel uint32) protocol.Semantic { return protocol.FinishSelection(&src, purp, sel) }}), nil
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

### Task 19: Ordering and arrangement

**Files:**
- Create: `internal/mapping/order.go`, `internal/mapping/arrange.go`
- Test: `internal/mapping/order_test.go`, `internal/mapping/arrange_test.go`

**Interfaces:**
- Consumes: framework, `Env.OpenLook`, `LookRef`, `KnownEntry`, `SortKnown`, `gamecfg.Game.Probe`.
- Native ops (read by Task 26's agent): partition candidates are `dest` (Option is the card's native option or -1, List the destination, Position the card index; `top` and `hand` are inside the native Choices). Ordering candidates are `list` (List `choices`, `rest` or `followup:dig_bottom`; Option the card's option in that decision; Position its place in the destination). Explore's partition candidates are `choose` with the destination option's index.
- Produces registered routes:
  - `trigger_order`: `order_pick` `triggers`, n-1 decisions, last implied;
  - `mulligan/bottom`: `order_pick` `mulligan_bottom`, all k posed;
  - `hand_move/library`: `select_object` fixed group, then `order_pick` `library_top`;
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
	newLib := c.G.Zone(state.ZLibrary, d.Player)
	if newLib[0] != top1 || newLib[len(newLib)-1] != top0 {
		t.Fatalf("library top %d bottom %d, want %d and %d", newLib[0], newLib[len(newLib)-1], top1, top0)
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

Run: `go test ./internal/mapping/ -run 'Scry|Dig|TriggerOrder|MulliganBottom'`
Expected: FAIL with `unmapped_decision:arrange/bottom` and similar.

- [ ] **Step 3: Write minimal implementation**

`internal/mapping/order.go`:

```go
package mapping

import (
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
		key := fmt.Sprint(o.Obj)
		item := protocol.TriggerItem{Source: src, SourceName: name, EventObjects: []protocol.ObjectRef{}, Instance: instances[key]}
		instances[key]++
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
		}})
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

Run: `go test ./internal/mapping/ -run 'Scry|Dig|TriggerOrder|MulliganBottom' -v`
Expected: all four PASS.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/mapping && git commit -m "gorge adapter: order picks and fixed-size arrangements (scry, dig, explore, Brainstorm)"
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
  - `trigger_optional/optional` (`choose_boolean` `optional_trigger`), `trigger_optional/madness` (`optional_cast` `madness`);
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
		card, err := MustSource(env, d)
		if err != nil {
			return nil, err
		}
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
  - `func mapping.Internal(d *decision.Decision) (decision.Intent, bool)`, the decisions the engine answers itself. v2.0 has no kind for allocating floating mana to a hybrid pip, since `pay_mana` is reserved, so `choose/pay_pip` is answered with gorge's first offered option. This is the engine's payment procedure, not a player decision, and is recorded in the engine notes (Task 29) and as controller decision 3.

Rules:
- **Unless costs** (gorge `KModes` pay/decline, ResumeKind `unless_pay`) become `optional_cost`.
  - `cost` is `unless_payment` when `ResumeSA.API` is `Counter`, `copy` when the API names a copy, else `other`.
  - `pay: true` is offered only when a clone shows paying opens no `unless_mana` window, meaning the floating pool already covers the cost (controller decision 2). No activation candidates.
- **Trigger costs** (window first): gorge's `choose/mana_window` (activate options plus done) becomes one decision with `context.purpose` `mana_payment`:
  - `optional_cost pay:false`, whose op answers done and then decline (the pay/decline ask is the follow-up keyed by done's option index);
  - one `activate_mana_ability` per window activation, folded like Task 15;
  - `optional_cost pay:true`, only when a clone shows that done leads to a pay/decline ask offering pay.
  - Each activation commits and the session re-poses the next window as a new decision.
  - A window whose done does not lead to a trigger-cost ask (a cast payment window, or `unless_mana`) fails closed.
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
	in, ok := mapping.Internal(d)
	if !ok || len(in.Choices) != 1 || in.Choices[0] != 0 {
		t.Fatalf("internal answer %v %v", in, ok)
	}
	if _, ok := mapping.Internal(&decision.Decision{Kind: decision.KPriority}); ok {
		t.Fatal("priority answered internally")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/mapping/ -run 'Spellbomb|UnlessPay|HybridPip'`
Expected: FAIL with `undefined: mapping.Internal`.

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
}

// Internal returns the answer for decisions the engine makes itself.
func Internal(d *decision.Decision) (decision.Intent, bool) {
	if d.Kind == decision.KChoose && Route(d) == "choose/pay_pip" {
		return Intent(d, d.Options[0].Index), true
	}
	return decision.Intent{}, false
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
- Consumes: `gamecfg`, `identity`, `observe`, `mapping` (Begin, Internal, error values), `protocol`.
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

- [ ] **Step 1: Write the failing test**

`internal/session/session_test.go`:

```go
package session_test

import (
	"encoding/json"
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

func TestEchoComparesParsedFieldsNotBytes(t *testing.T) {
	g := start(t, "Burn", 4000)
	dec, _ := g.Pending()
	c := dec.SeatDecision.Candidates[len(dec.SeatDecision.Candidates)-1].Semantic
	var m map[string]any
	json.Unmarshal(echo(t, c), &m)
	reordered, _ := json.Marshal(m) // map keys come back sorted: a different byte order than the struct fields
	if !session.EchoEqual(reordered, c) {
		t.Fatal("reordered echo rejected")
	}
	m["x_extra"] = 1
	extra, _ := json.Marshal(m)
	if session.EchoEqual(extra, c) {
		t.Fatal("echo with an extra field accepted")
	}
	if perr := g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: 0, Echo: extra}); perr == nil || perr.Code != protocol.CodeSemanticEchoMismatch {
		t.Fatalf("got %v", perr)
	}
}

func TestCapNeverSplitsAGroup(t *testing.T) {
	g := start(t, "Rally", 4000)
	var groupStep uint64
	for found := false; !found; {
		dec, term := g.Pending()
		if term != nil {
			t.Skip("no multi-substep group in this seed")
		}
		sd := dec.SeatDecision
		if sd.Group.SubstepIndex == 0 && sd.Group.SubstepCount >= 2 {
			groupStep, found = dec.Step, true
			break
		}
		g.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: 0, Echo: echo(t, sd.Candidates[0].Semantic)})
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
		h.Step(&protocol.StepReq{GameID: "g-t", ExpectedStep: dec.Step, CandidateID: 0, Echo: echo(t, dec.SeatDecision.Candidates[0].Semantic)})
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
			if in, ok := mapping.Internal(d); ok {
				if err := s.submit(in); err != nil {
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
	if p.Context.Kind == "priority" {
		if obj := s.actionObject(p.Candidates[i].Op); obj != 0 {
			s.env.Action = &mapping.ActionContext{Seat: seat, Obj: obj}
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
	for _, in := range commit {
		if err := s.submit(in); err != nil {
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

func (s *Game) submit(in decision.Intent) error {
	d := s.g.E.Pending()
	if d == nil {
		return errFollowup
	}
	if in.Seq == 0 {
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
  - `var server.DecisionKinds []string` (the 25 kinds);
  - the `spellbench-gorge-env` binary (`-corpus`, `-source-revision`).

Retransmission: the engine caches the last response. Every request id seen gets its payload's SHA-256.
- The identical last request returns the cached bytes.
- Any other reuse of an id returns `request_id_reuse_mismatch`, including an identical retransmission of an older request, which a host never sends because it never pipelines. This is recorded in the engine notes.

Parse failures are never cached.

Validation order:
- **Reset:** `game_already_active`, reused `game_id` (`malformed_request`), `unsupported_format`, per-seat deck checks (`unsupported_deck`, then `deck_id_mismatch`), rule checks (`unsupported_rule`, and `malformed_request` when `domain_id` does not hash its names).
- **Step:** `step_before_reset`, `game_id_mismatch`, then the session's order.

- [ ] **Step 1: Write the failing test**

`internal/server/server_test.go`:

```go
package server_test

import (
	"encoding/json"
	"fmt"
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
	line := fmt.Sprintf(`{"request_type":"reset","protocol":"spellbench/v2","request_id":%q,"game_id":%q,"format":"pauper-bo1","seats":[{"seat":"p0","deck":{"deck_id":%q,"catalog_id":%q}},{"seat":"p1","deck":{"deck_id":%q,"catalog_id":%q}}],"rules":{"opponent_decklist":"visible","mulligan":"london","starting_player":"host_assigned","starting_seat":"p0","card_name_domain":{"domain_id":%q,"names":%s},"extensions":["x_gorge_view_v1"],"probe":false},"game_secret":"%s","max_decisions":10000,"max_steps":100000}`,
		id, gameID, d.DeckID(), deck, d.DeckID(), deck, wire.DomainID(catalog.PoolNames()), names, strings.Repeat("ab", 32))
	if mutate != "" {
		parts := strings.SplitN(mutate, "=>", 2)
		line = strings.Replace(line, parts[0], parts[1], 1)
	}
	return []byte(line)
}

func TestHelloDeclaresTheProfile(t *testing.T) {
	s := server.New(testcorpus.Registry(t), nil)
	m := resp(t, s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":3}`)))
	if m["protocol_minor"].(float64) != 0 || len(m["decision_kinds"].([]any)) != 25 || len(m["catalog"].([]any)) != 5 ||
		len(m["observation"].(map[string]any)) != 13 || m["rewind"] != false {
		t.Fatalf("hello_ok %v", m)
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
	s.Handle([]byte(`{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-9","protocol_minor":0}`))
	if got := code(t, s.Handle(line)); got != "request_id_reuse_mismatch" {
		t.Fatalf("older identical retransmission: %s", got)
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

var DecisionKinds = []string{"pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability",
	"special_action", "choose_target", "finish_target_selection", "choose_cost_target", "choose_spell_mode",
	"choose_color", "choose_number", "choose_boolean", "choose_name", "select_object", "finish_selection",
	"optional_cost", "optional_cast", "mulligan", "order_pick", "arrange_card", "choose_replacement",
	"declare_attack", "declare_block", "distribute"}

func engineIdentity(sourceRevision *string) protocol.Engine {
	var ids []string
	for _, d := range catalog.Decks() {
		ids = append(ids, d.DeckID())
	}
	return protocol.Engine{Name: "gorge", Version: "gorge-" + gorgepin.GorgeCommit[:12] + "/spellbench-adapter-" + AdapterVersion,
		SourceRevision:   sourceRevision,
		RulesSnapshotID:  "gorge/" + gorgepin.GorgeCommit[:12] + "/ir-" + cards.CompilerFingerprint,
		CardPoolIdentity: "forge-" + gorgepin.ForgeRef[:12] + "/corpus-" + gorgepin.CorpusDigest[:16] + "/catalog-" + wire.DomainID(ids)[7:23]}
}

func provenance(e protocol.Engine) protocol.Provenance {
	return protocol.Provenance{EngineName: e.Name, EngineVersion: e.Version, RulesSnapshotID: e.RulesSnapshotID, CardPoolIdentity: e.CardPoolIdentity}
}

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
		EngineDefaults: map[string]*string{"trigger_order": nil, "replacement_order": nil, "combat_damage_assignment": nil, "mana_payment": nil},
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

type Server struct {
	reg      *cards.Registry
	engine   protocol.Engine
	game     *session.Game
	gameIDs  map[string]bool
	seen     map[string][32]byte
	lastID   string
	lastResp []byte
}

func New(reg *cards.Registry, sourceRevision *string) *Server {
	return &Server{reg: reg, engine: engineIdentity(sourceRevision), gameIDs: map[string]bool{}, seen: map[string][32]byte{}}
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
	if prev, ok := s.seen[req.ID]; ok {
		if prev == sum && req.ID == s.lastID {
			return s.lastResp
		}
		return errResp(req.ID, protocol.Errf(protocol.CodeRequestIDReuseMismatch, "request_id reused; only the latest request may be retransmitted"))
	}
	out := s.dispatch(req)
	s.seen[req.ID], s.lastID, s.lastResp = sum, req.ID, out
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
	case wire.DomainID(r.Rules.Names) != r.Rules.DomainID:
		return errResp(req.ID, protocol.Errf(protocol.CodeMalformedRequest, "card_name_domain.domain_id does not hash its names"))
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
			w.Write(append(errResp("", protocol.Errf(protocol.CodeMalformedJSON, "line exceeds 8 MiB")), '\n'))
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

Run: `go build -o bin/spellbench-gorge-env.exe ./cmd/spellbench-gorge-env && echo '{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1","protocol_minor":0}' | ./bin/spellbench-gorge-env.exe | head -c 120`
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
  - `type xview.Payload struct{ Version int; NativeIndex uint64; View view.View; Decision decision.Decision; Facts Facts; Followups map[string]decision.Decision; Ops []mapping.NativeOp; Splits [][]int32 }` (JSON keys `version`, `native_index`, `view`, `decision`, `policy_facts`, `followups`, `ops`, `splits`);
  - `type xview.Facts` and `type xview.OptionFacts`;
  - `type xview.Extender`, implementing `session.Extender`, with `func xview.New() *Extender` (per game: per-seat id tables);
  - `func (*Extender) Extend(env *mapping.Env, p *mapping.Pose, nativeIndex uint64) (map[string]json.RawMessage, error)`.

Audit rules (Section 14 with `native_ids: false`):
- **Ids:** every gorge object id in the payload is replaced by a per-seat integer. The integer is assigned in the order v2 ids first appear in that seat's stream, which the seat can compute itself, so it carries nothing hidden and is fresh wherever the v2 id is.
- **No global counters:** `Decision.Seq` is replaced by `native_index`, the seat's own count of native decisions.
- **No digests:** payment actions and fallbacks are dropped.
- **No hidden order:** options referencing hidden-zone cards are reordered by `(card_name, v2 id)` and renumbered, in the native decision and in every follow-up. Follow-up keys and every op are translated with the matching permutation.
- **Pending triggers** with hidden sources are dropped, as in the observation.

- [ ] **Step 1: Write the failing test**

`internal/xview/xview_test.go`:

```go
package xview_test

import (
	"encoding/json"
	"testing"

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/rules"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/identity"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/mapping"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testcorpus"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/testgame"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

func payloadAt(t *testing.T, deck string, pred func(*decision.Decision, *rules.Engine) bool) (xview.Payload, *mapping.Pose) {
	reg := testcorpus.Registry(t)
	g := testgame.New(t, reg, deck, deck, 1, "none")
	if !testgame.RunUntil(t, g, testgame.Bots(1), func(e *rules.Engine) bool { d := e.Pending(); return d != nil && pred(d, e) }, 30000) {
		t.Fatal("decision not reached")
	}
	tr := identity.New(g.E, g.Secret)
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
	return pl, p
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
```

`internal/xview/key_test.go` (internal: `followKey` is unexported):

```go
package xview

import "testing"

func TestFollowKeysFollowTheRenumbering(t *testing.T) {
	perm := []int{2, 0, 1}
	fperm := map[string][]int{"1": {1, 0}}
	for in, want := range map[string]string{"1": "0", "1/0": "0/1", "dig_bottom": "dig_bottom", "7": "7"} {
		if got := followKey(in, perm, fperm); got != want {
			t.Errorf("followKey(%q) = %q, want %q", in, got, want)
		}
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
	"fmt"
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

type Facts struct {
	Options                   []OptionFacts `json:"options"`
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
	Splits      [][]int32                    `json:"splits"`
}

type table struct {
	ints map[string]uint32
	next uint32
}

type Extender struct {
	tables [2]*table
	last   [2][]int // the seat's last native -> payload renumbering (audit only, Task 28)
}

func New() *Extender {
	return &Extender{tables: [2]*table{{ints: map[string]uint32{}}, {ints: map[string]uint32{}}}}
}

func (x *Extender) rekey(env *mapping.Env, seat state.PlayerID) (rekeyer, *error) {
	var firstErr error
	t := x.tables[seat]
	return func(id state.ObjID) state.ObjID {
		o := env.G.E.G.Obj(id)
		var v2 string
		var err error
		switch {
		case o == nil:
			err = fmt.Errorf("object %d missing", id)
		case observe.Visible(seat, o) || o.Zone == state.ZCeased:
			v2, err = env.IDs.VisibleID(seat, id)
		default:
			v2, err = env.IDs.LookID(seat, id) // only a look can show a hidden-zone object
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
	r, errp := x.rekey(env, seat)
	v := view.Project(e.G, e, seat, nil)
	v.Round = view.RoundOf(e.G, e.L.Events)
	kept := v.Pending[:0]
	for _, pv := range v.Pending {
		if o := e.G.Obj(pv.Source); o == nil || observe.Visible(seat, o) {
			kept = append(kept, pv)
		}
	}
	v.Pending = kept
	r.view(&v)
	d := p.Native.CloneValue()
	pl := Payload{Version: 1, NativeIndex: nativeIndex, Facts: facts(&d), Followups: map[string]decision.Decision{}, Splits: p.Splits}
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
	pl.Decision = d
	// Follow-ups are sorted the same way; their keys and every op that points
	// into them are translated with their own permutations.
	fperm := map[string][]int{}
	fds := map[string]decision.Decision{}
	for k, fd := range p.Followups {
		c := fd.CloneValue()
		fperm[k], _ = sortHidden(env, seat, &c)
		r.decision(&c, nativeIndex)
		fds[k] = c
	}
	for k, c := range fds {
		pl.Followups[followKey(k, perm, fperm)] = c
	}
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
Expected: `--- PASS: TestPayloadHasNoGlobalCountersOrDigests`, `--- PASS: TestSearchOptionsAreSortedAndIDsAreSmall`, `--- PASS: TestFollowKeysFollowTheRenumbering`.

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
- Consumes: `server.Server`, `validate`, `wire` (canonical, digest), `secrets` (host side), `catalog`, `protocol`.
- Produces:
  - `type minihost.Link interface{ Round(req []byte) ([]byte, error) }`;
  - `type minihost.Host struct{ RunSecret []byte; Engine Link; Profile validate.Profile; MaxSteps, MaxDecisions uint64 }`;
  - `func (*Host) Play(i uint64, deck catalog.Deck, mulligan string, extensions []string, agents [2]Link) (Result, error)`;
  - `type minihost.Result struct{ Terminal protocol.TerminalResponse; Digest string; Steps int; SeatDecisions [2][][]byte }` (the canonical `seat_decision` bytes, kept for leak scans);
  - `type minihost.EngineLink struct{ S *server.Server }`;
  - `type minihost.Uniform struct` and `type minihost.First struct` (in-process agents seeded from `game_start.agent_seed`).

The mini-host implements Sections 11.2 (canonical forwarding), 11.3 (validator subset), 11.6 (secrets, agent seeds, opaque ids) and 11.8 (digest). It has no clocks, adjudication or stalling; P's host owns those.

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
	n                      int
}

type Result struct {
	Terminal      protocol.TerminalResponse
	Digest        string
	Steps         int
	SeatDecisions [2][][]byte
}

func (h *Host) id() string { h.n++; return fmt.Sprintf("h-%d", h.n) }

func (h *Host) Play(i uint64, deck catalog.Deck, mulligan string, extensions []string, agents [2]Link) (Result, error) {
	var res Result
	gameID := secrets.GameID(h.RunSecret, i)
	names := catalog.PoolNames()
	seat0 := "p0"
	reset := map[string]any{"request_type": "reset", "protocol": protocol.Name, "request_id": h.id(), "game_id": gameID,
		"format": "pauper-bo1",
		"seats": []any{map[string]any{"seat": "p0", "deck": map[string]any{"deck_id": deck.DeckID(), "catalog_id": deck.CatalogID}},
			map[string]any{"seat": "p1", "deck": map[string]any{"deck_id": deck.DeckID(), "catalog_id": deck.CatalogID}}},
		"rules": map[string]any{"opponent_decklist": "visible", "mulligan": mulligan, "starting_player": "host_assigned",
			"starting_seat": seat0, "card_name_domain": map[string]any{"domain_id": wire.DomainID(names), "names": names},
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
		res.SeatDecisions[seat] = append(res.SeatDecisions[seat], canon)
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
- Consumes: `xview.Payload`, `mapping.NativeOp`, `seat.NewBot`, `seat.NewLethalPressureBot`.
- Produces:
  - `type agent.Server` with `func agent.New(policy string) (*Server, error)` (`bot` or `lethal-pressure`), `func (*Server) Handle(line []byte) []byte` and `func (*Server) Round(req []byte) ([]byte, error)` (a `minihost.Link`);
  - `func agent.Rebuild(p xview.Payload) (view.View, decision.Decision)` (applies the policy facts);
  - `func agent.Pick(p xview.Payload, sems []map[string]any, st *Plan, ask func(decision.Decision) decision.Intent) (int, bool)` (candidate semantics are read as generic JSON: `protocol.Semantic` has no decoder);
  - `type agent.Plan` and `func agent.NewPlan(native uint64, in decision.Intent) *Plan`;
  - `func (*Server) Fallbacks() int`, `func (*Server) Intents() map[uint64]decision.Intent` and `func (*Server) FellBack(native uint64) bool` (the current game's plans, for Task 28's parity audit);
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
  - `amount` matches the intended split;
  - `finish` matches when every intended pick is done.
- A decision with a single candidate is answered without counting a fallback.
- If nothing matches (the unless-cost restriction, controller decision 2), the agent falls back to `pay: false`, then `finish`, then candidate 0, and counts the fallback on stderr.

- [ ] **Step 1: Write the failing test**

`internal/agent/agent_test.go`:

```go
package agent_test

import (
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
		MaxSteps: 3000, MaxDecisions: 2999}
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
	if i, fell := agent.Pick(part, sems, pl, none); i != 1 || fell {
		t.Fatalf("card 0 went to candidate %d (fallback %v), want the bottom", i, fell)
	}
	order := xview.Payload{Ops: []mapping.NativeOp{
		{Op: "list", Option: 1, List: "rest", Position: 0},
		{Op: "list", Option: 0, List: "rest", Position: 0},
	}}
	if i, fell := agent.Pick(order, sems, pl, none); i != 1 || fell {
		t.Fatalf("first bottom card is candidate %d (fallback %v), want option 0", i, fell)
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
	"fmt"
	"os"

	"github.com/adams-shaun/gorge/cards"
	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/seat"
	"github.com/adams-shaun/gorge/state"
	"github.com/adams-shaun/gorge/view"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/xview"
)

type Server struct {
	policy    string
	bot       seat.Seat
	plan      *Plan
	fallbacks int
	intents   map[uint64]decision.Intent // the bot's plan per native index (parity audit)
	fell      map[uint64]bool
}

func New(policy string) (*Server, error) {
	if policy != "bot" && policy != "lethal-pressure" {
		return nil, fmt.Errorf("unknown policy %q", policy)
	}
	return &Server{policy: policy, intents: map[uint64]decision.Intent{}, fell: map[uint64]bool{}}, nil
}

func (s *Server) Fallbacks() int { return s.fallbacks }

// Intents and FellBack expose the current game's plans to Task 28's parity audit.
func (s *Server) Intents() map[uint64]decision.Intent { return s.intents }

func (s *Server) FellBack(native uint64) bool { return s.fell[native] }

func (s *Server) Round(req []byte) ([]byte, error) { return s.Handle(req), nil }

type candidate struct {
	CandidateID uint32         `json:"candidate_id"`
	Semantic    map[string]any `json:"semantic"` // protocol.Semantic has no decoder: read it generically
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

func (s *Server) Handle(line []byte) []byte {
	var q request
	dec := json.NewDecoder(bytes.NewReader(line))
	dec.UseNumber() // amounts compare as integers, never as floats
	if err := dec.Decode(&q); err != nil {
		return out(map[string]any{"response_type": "error", "protocol": protocol.Name, "request_id": "",
			"error": map[string]string{"code": "malformed_json", "message": err.Error()}})
	}
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
		s.intents, s.fell = map[uint64]decision.Intent{}, map[uint64]bool{}
		base["response_type"] = "ack"
	case "choose":
		base["response_type"] = "choice"
		base["selection"] = map[string]uint32{"candidate_id": s.choose(q)}
	default:
		base["response_type"] = "ack"
	}
	return out(base)
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
		in, _ := s.bot.Decide(context.Background(), vv, nd)
		return in
	}
	if s.plan == nil || s.plan.native != p.NativeIndex {
		s.plan = NewPlan(p.NativeIndex, ask(d))
		s.intents[p.NativeIndex] = s.plan.intent
	}
	sems := make([]map[string]any, len(cands))
	for i, c := range cands {
		sems[i] = c.Semantic
	}
	i, fell := Pick(p, sems, s.plan, ask)
	if fell {
		s.fallbacks++
		s.fell[p.NativeIndex] = true
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
func (pl *Plan) match(p xview.Payload, op mapping.NativeOp, sem map[string]any, ask func(decision.Decision) decision.Intent) bool {
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
	case "amount":
		if len(in.Choices) == 1 && in.Choices[0] < len(p.Splits) && op.Position < len(p.Splits[in.Choices[0]]) {
			return fmt.Sprint(sem["amount"]) == fmt.Sprint(p.Splits[in.Choices[0]][op.Position])
		}
	case "finish":
		return len(pl.used) >= len(in.Choices)
	}
	return false
}

// Pick returns the candidate matching the plan, and whether it fell back.
func Pick(p xview.Payload, sems []map[string]any, pl *Plan, ask func(decision.Decision) decision.Intent) (int, bool) {
	for i, op := range p.Ops {
		if pl.match(p, op, sems[i], ask) {
			if op.Op == "choose" {
				pl.used = append(pl.used, op.Option)
			}
			return i, false
		}
	}
	if len(sems) == 1 {
		return 0, false // a forced pick (an engine-fixed order, say) is not a fallback
	}
	for i, s := range sems {
		if s["kind"] == "optional_cost" && s["pay"] == false {
			return i, true
		}
	}
	for i, s := range sems {
		if s["kind"] == "finish_selection" || s["kind"] == "finish_target_selection" {
			return i, true
		}
	}
	return 0, true
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
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/wire"
)

func main() {
	policy := flag.String("policy", "bot", "bot or lethal-pressure")
	flag.Parse()
	s, err := agent.New(*policy)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	in := wire.NewReader(os.Stdin)
	w := bufio.NewWriter(os.Stdout)
	for {
		line, err := in.ReadLine()
		if err != nil {
			return
		}
		w.Write(append(s.Handle(line), '\n'))
		w.Flush()
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/agent/ -v -timeout 20m`
Expected: `--- PASS: TestPickFollowsAScryAnswer` and `--- PASS: TestAgentDecodesCanonicalizedPayload` (no `halted`, fallbacks at most 2% of steps).

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
  - `TestGoldensReplayByteExact`, which replays the `host_to_engine` lines into a fresh server and compares every `engine_to_host` line byte for byte;
  - `-update` regenerates the files.

Scenarios:
- `hello`;
- `reset_first_decision_<deck>` for the five decks;
- `uniform_game_burn` (Uniform agents, `max_steps` 300, full transcript with agent traffic);
- one file per error code: `malformed_json`, `malformed_request`, `protocol_mismatch`, `request_id_reuse_mismatch`, `step_before_reset`, `game_already_active`, `game_id_mismatch`, `expected_step_mismatch`, `candidate_id_out_of_range`, `semantic_echo_mismatch`, `unsupported_format`, `unsupported_deck`, `deck_id_mismatch`, `unsupported_rule`, `unsupported_request`, `game_already_terminal`;
- `arrangement`, `attack_declaration`, `order_pick` and `mana_payment`: the first seeded Uniform game (seeds 0 to 19, every deck) whose decisions reach that shape, replayed with `max_steps` ending right after that group, since a cap never splits a group.

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
	for _, f := range files {
		s := server.New(testcorpus.Registry(t), nil)
		fh, err := os.Open(f)
		if err != nil {
			t.Fatal(err)
		}
		sc := bufio.NewScanner(fh)
		sc.Buffer(make([]byte, 1<<20), 9<<20)
		var last []byte
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
		}
		fh.Close()
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

// firstGroup finds the first engine decision containing needle and returns
// the step its group started at and the group's size.
func firstGroup(recs []record, needle string) (start, size uint64, ok bool) {
	for _, r := range recs {
		if r.Dir != "engine_to_host" || !strings.Contains(string(r.Message), needle) {
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
		if json.Unmarshal(r.Message, &d) == nil && d.SeatDecision.Group.SubstepCount > 0 {
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
	burn := reset("r-1", "g-1", "Burn", "")
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
		{"game_already_active", [][]byte{burn, reset("r-2", "g-2", "Burn", "")}},
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
		}{"reset_first_decision_" + strings.ToLower(d.CatalogID), [][]byte{reset("r-1", "g-1", d.CatalogID, "")}})
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
	targets := []struct{ name, needle string }{
		{"arrangement", `"kind":"arrange_card"`},
		{"attack_declaration", `"kind":"declare_attack"`},
		{"order_pick", `"kind":"order_pick"`},
		{"mana_payment", `"purpose":"mana_payment"`},
	}
	for _, tg := range targets {
		found := false
		for i := uint64(0); i < 20 && !found; i++ {
			for _, d := range catalog.Decks() {
				full, _, err := playRecorded(reg, i, d, 3000)
				if err != nil {
					return err
				}
				start, size, ok := firstGroup(full, tg.needle)
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

### Task 28: Qualification: determinism, fairness, leaks, parity, throughput

**Files:**
- Create: `internal/session/resample.go`, `internal/session/audit.go`, `internal/identity/clone.go`, `internal/xview/clone.go`, `internal/server/audit.go`, `cmd/gorgequal/main.go`
- Modify: `internal/session/session.go` (the `Audit` switch, the leak scan in `present`, the realized intent in `answer`), `internal/server/server.go` (the `audit` field)
- Test: `internal/session/resample_test.go`, `internal/session/audit_test.go`, `cmd/gorgequal/main_test.go`

**Interfaces:**
- Consumes: `session.Game`, `minihost`, `agent` (`Intents`, `FellBack`, `Fallbacks`), `xview` (`last`), `validate`, `catalog`.
- Produces:
  - `func (*session.Game) ResampleCheck(r *rand.Rand) error`, `func (*identity.Tracker) CloneFor(e *rules.Engine) *Tracker`, `func (*xview.Extender) Clone() *Extender`, `func (*xview.Extender) Perm(seat state.PlayerID) []int`;
  - the audit: `session.Config.Audit`, `func session.LeakHits(sd []byte, hidden map[string]bool) int`, `type session.Realized struct{ Seat state.PlayerID; Native uint64; Kind decision.Kind; Intent decision.Intent }`, `func (*Game) Leaks() int`, `func (*Game) Realized() []Realized`;
  - `func (*server.Server) SetAudit(on bool)`, `Leaks() int`, `Realized() []session.Realized`, `ResampleCheck(r *rand.Rand) error`;
  - the `gorgequal` command: `-games N`, `-resample K` (a check before every K-th step, 0 for none), `-workers W`, `-audit` (default true), `-out report.json`;
  - a report with per deck and pairing counts: halts, truncations, validator violations, rerun digest mismatches, resample checks and failures, leak-scan hits, parity comparisons and mismatches, fallbacks, games per second, and Go memory (`runtime.MemStats.Sys`).

Checks:
1. **Determinism:** every game is played twice from the same run secret, once audited and once plain. The digests must match, which also shows the audit does not disturb the game.
2. **Validator:** the mini-host's validator subset checks every forwarded decision (Task 25).
3. **Resample self-check.** It stands in for the reserved Section 9.7 probe and does not change the fairness label. It runs at the first substep of a transaction, the only pose built from the current engine state:
   - clone the engine, the identity tracker and the extension's id tables;
   - permute every library except the positions the pose's `known` entries give and the cards the native decision offers;
   - swap each unpinned card of the other seat's hand with a random card of that seat's library, unless the seat is looking at that whole library (a search);
   - rebuild the whole `seat_decision`, including `x_gorge_view_v1`, and require canonical byte equality.
4. **Leak scan:** every string in a seat decision (the extension included; `choose_name` candidates skipped, their domain is public) is checked against the names of cards the seat cannot see. Those are the cards in the other seat's hand, in libraries or face down, minus every name the seat can see anywhere and every name in the decision's `known`. A hit is investigated, never whitelisted without the controller.
5. **Bot parity:** gorge's bot must play through the adapter exactly the moves it chose. For every completed native decision the session records the committed intent, renumbered into the extension's option order (`Perm`). It must equal the agent's plan for that native decision, except where the agent recorded a fallback. Attacker and blocker choices compare as sets, and pile-B order only when the bot gave one. Native-versus-adapter game identity is not expected: per-seat ids and sorted hidden options change the bot's inputs by design (engine notes, Task 29).
6. **Throughput:** plain games per second, serially and with W workers, for Task 30's compute qualification.

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
	if g.Leaks() != 0 {
		t.Fatalf("%d leak-scan hits", g.Leaks())
	}
	if len(g.Realized()) == 0 {
		t.Fatal("no realized intents recorded")
	}
}
```

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
		t.Fatalf("qualification not clean: %+v", rep.Totals)
	}
	if rep.Totals.ResampleChecks == 0 || rep.Totals.ParityCompared == 0 {
		t.Fatalf("checks did not run: %+v", rep.Totals)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/session/ -run 'Resampling|Leak|Audited' && go test ./cmd/gorgequal/`
Expected: FAIL with `g.ResampleCheck undefined`, `undefined: session.LeakHits` and `undefined: qualify`.

- [ ] **Step 3: Write minimal implementation**

`internal/identity/clone.go`:

```go
package identity

import (
	"maps"

	"github.com/adams-shaun/gorge/rules"
)

// CloneFor copies the tracker for a clone of the game (the resample
// self-check): the same move and look counters, open looks and minted ids,
// with the shadow re-pointed at e. The copy only mints; it never syncs.
func (t *Tracker) CloneFor(e *rules.Engine) *Tracker {
	c := &Tracker{sec: t.sec, shadow: e.G.Clone(), applied: len(e.L.Events),
		moves: maps.Clone(t.moves), looks: maps.Clone(t.looks)}
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
	}
	return c
}

// Perm is the native -> payload option renumbering of the seat's last
// payload. The audit reads it; no agent ever receives it.
func (x *Extender) Perm(seat state.PlayerID) []int { return x.last[seat] }
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
	// Only a transaction's first substep was posed from this very state;
	// later substeps carry answers the clone never saw.
	if s.resp == nil || s.native == nil || s.pose == nil || s.pose.SubstepIndex != 0 {
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

	"github.com/adams-shaun/gorge/decision"
	"github.com/adams-shaun/gorge/state"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/observe"
	"github.com/jackmaiorino/spellbench/engines/gorge/internal/protocol"
)

// Realized is a completed native decision's committed intent, renumbered
// into the x_gorge_view_v1 option order, for the bot parity audit.
type Realized struct {
	Seat   state.PlayerID
	Native uint64
	Kind   decision.Kind
	Intent decision.Intent
}

func (s *Game) Leaks() int { return s.leaks }

func (s *Game) Realized() []Realized { return s.realized }

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
// hand, libraries, face-down cards), minus every name the seat can see
// anywhere and every name the decision's known entries show.
func (s *Game) hiddenNames(seat state.PlayerID, known []protocol.Known) map[string]bool {
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
	for _, k := range known {
		seen[k.CardName] = true
	}
	for n := range seen {
		delete(hidden, n)
	}
	return hidden
}

// realize records a completed native decision's intent in the numbering the
// seat's agent saw.
func (s *Game) realize(seat state.PlayerID, in decision.Intent) {
	var perm []int
	if p, ok := s.cfg.Ext.(interface{ Perm(state.PlayerID) []int }); ok {
		perm = p.Perm(seat)
	}
	renum := func(xs []int) []int {
		out := make([]int, len(xs))
		for i, x := range xs {
			out[i] = x
			if x >= 0 && x < len(perm) {
				out[i] = perm[x]
			}
		}
		return out
	}
	s.realized = append(s.realized, Realized{Seat: seat, Native: s.nativeCount[seat], Kind: s.native.Kind,
		Intent: decision.Intent{Choices: renum(in.Choices), Rest: renum(in.Rest)}})
}
```

Modify `internal/session/session.go`:

```go
type Config struct {
	Reg        *cards.Registry
	Provenance protocol.Provenance
	Ext        Extender
	Audit      bool // qualification only: leak scan and realized intents
}
```

Add `leaks int` and `realized []Realized` to `Game`. In `present`, after the extensions are attached:

```go
	if s.cfg.Audit {
		b, err := json.Marshal(sd)
		if err != nil {
			return err
		}
		s.leaks += LeakHits(b, s.hiddenNames(p.Seat, known))
	}
```

In `answer`, record the intent before the next decision is posed (which would overwrite the extension's `last` permutation):

```go
	if done {
		if s.cfg.Audit && len(commit) > 0 {
			s.realize(seat, commit[0]) // commit[0] always answers the transaction's own native decision
		}
		s.tx = nil
		s.env.CloseLooks()
	}
```

Modify `internal/server/server.go`: add an `audit bool` field to `Server`, and in `reset` build `cfg := session.Config{Reg: s.reg, Provenance: provenance(s.engine), Audit: s.audit}`.

`internal/server/audit.go`:

```go
package server

import (
	"math/rand/v2"

	"github.com/jackmaiorino/spellbench/engines/gorge/internal/session"
)

// SetAudit turns the qualification audit on for games reset afterwards.
func (s *Server) SetAudit(on bool) { s.audit = on }

// Leaks, Realized and ResampleCheck report on the current game.
func (s *Server) Leaks() int {
	if s.game == nil {
		return 0
	}
	return s.game.Leaks()
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

`cmd/gorgequal/main.go`:

```go
// Command gorgequal runs the adapter's qualification: games per deck and
// pairing through the mini-host, with determinism, validator, resample,
// leak, parity and throughput checks.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
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
	ResampleChecks, ResampleFailures, LeakHits           int
	ParityCompared, ParityMismatch, Fallbacks            int
	GamesPerSecond                                       float64
	GoMemoryMB                                           uint64
}

type Report struct {
	Totals Totals           `json:"totals"`
	Rows   []map[string]any `json:"rows"`
}

func (r Report) Clean() bool {
	t := r.Totals
	return t.Games > 0 && t.Halts == 0 && t.Violations == 0 && t.DigestMismatch == 0 &&
		t.ResampleFailures == 0 && t.LeakHits == 0 && t.ParityMismatch == 0
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

// parity compares each realized intent of an agent seat with that agent's
// plan, skipping native decisions where the agent fell back.
func parity(realized []session.Realized, seats [2]minihost.Link) (compared, mismatched int) {
	for _, r := range realized {
		a, ok := seats[r.Seat].(*agent.Server)
		if !ok || a.FellBack(r.Native) {
			continue
		}
		compared++
		if want, ok := a.Intents()[r.Native]; !ok || !sameIntent(r.Kind, r.Intent, want) {
			mismatched++
			fmt.Fprintf(os.Stderr, "gorgequal: parity seat %d native %d %s: realized %v, planned %v\n", r.Seat, r.Native, r.Kind, r.Intent, want)
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
	rep := Report{}
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
				fb := 0
				for _, l := range seats {
					if ag, ok := l.(*agent.Server); ok {
						fb += ag.Fallbacks()
					}
				}
				compared, mismatched := parity(al.srv.Realized(), seats)
				leaks := al.srv.Leaks()
				row := map[string]any{"deck": j.deck.CatalogID, "pairing": j.pairing, "game": j.i, "steps": a.Steps,
					"outcome": a.Terminal.Outcome, "digest": a.Digest, "leaks": leaks, "parity_mismatch": mismatched, "fallbacks": fb}
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
				t.ParityCompared += compared
				t.ParityMismatch += mismatched
				t.Fallbacks += fb
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
	flag.BoolVar(&o.audit, "audit", true, "leak scan, parity and resample checks on the first run of each game")
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
	fmt.Printf("games %d halts %d truncated %d violations %d digest_mismatch %d resample_failed %d/%d leak_hits %d parity_mismatch %d/%d fallbacks %d games/s %.2f clean=%v\n",
		t.Games, t.Halts, t.Truncations, t.Violations, t.DigestMismatch, t.ResampleFailures, t.ResampleChecks,
		t.LeakHits, t.ParityMismatch, t.ParityCompared, t.Fallbacks, t.GamesPerSecond, rep.Clean())
	if !rep.Clean() {
		os.Exit(1)
	}
}
```

- [ ] **Step 4: Run tests and the qualification runs**

Run: `go test ./internal/session/ -run 'Resampling|Leak|Audited' -v -timeout 30m && go test ./cmd/gorgequal/ -v -timeout 30m`
Expected: `--- PASS: TestResamplingHiddenStateNeverChangesTheSeatDecision`, `--- PASS: TestLeakScanCountsAPlantedName`, `--- PASS: TestAuditedGameHasNoLeaksAndRecordsIntents`, `--- PASS: TestSmallQualificationIsClean`.

Run: `go run ./cmd/gorgequal -games 8 -workers 8 -out ../../out/gorgequal-audit.json`
Expected: `clean=true` over 120 games (5 decks x 3 pairings x 8), with `halts 0`, `violations 0`, `digest_mismatch 0`, `resample_failed 0/`, `leak_hits 0` and `parity_mismatch 0/`.

Run: `go run ./cmd/gorgequal -games 8 -workers 1 -audit=false -resample 0 -out ../../out/gorgequal-serial.json && go run ./cmd/gorgequal -games 8 -workers 8 -audit=false -resample 0 -out ../../out/gorgequal-w8.json`
Expected: both `clean=true`. Record both games/s figures for Task 30's compute qualification.

- [ ] **Step 5: Commit**

```bash
git add engines/gorge/internal/session engines/gorge/internal/identity engines/gorge/internal/xview engines/gorge/internal/server engines/gorge/cmd/gorgequal && git commit -m "gorge adapter: qualification with resample self-check, leak scan, bot parity and throughput"
```

---

### Task 29: Benchmark definition and engine notes

**Files:**
- Create: `C:\Users\Jack\IdeaProjects\spellbench\benchmarks\pauper-gorge\benchmark.json`
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
			Mulligan, StartingPlayer string
			Extensions               []string
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
	if !slices.Equal(b.DeckPool, ids) || b.Format != "pauper-bo1" || b.Rules.Mulligan != "london" {
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
Expected: FAIL with `open ../../../../benchmarks/pauper-gorge/benchmark.json: The system cannot find the path specified.`

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
2. The declared `hello_ok` profile (the Global Constraints line).
3. Engine procedures and limits:
   - No engine defaults are declared.
   - Hybrid-pip allocation from floating mana is engine-internal (gorge's first option).
   - Unless costs can be paid only from floating mana (no activation during the unless ask).
   - `known_cards` is false and there is no text channel.
   - Only `host_assigned` starting players; only the latest request is retransmittable.
   - Phased-out permanents are omitted (gorge's view treats them as absent).
   - `ability_index` follows gorge's compiled ability order.
   - A blocker stops reading as blocking once its attacker leaves combat.
   - Where gorge fixes a pile-B order (an arrange ask that is not Restable), each order pick offers one card. A dig_bottom ask with no take ask before it is an arrangement whose partitions are all `bottom`.
4. `x_gorge_view_v1`: payload fields, id re-keying and the audit (Task 24), `native_ids: false`. The wrapped bots see per-seat ids and name-sorted hidden options, so their games are not byte-identical to native gorge games; parity means the adapter commits exactly the intent the bot chose (Task 28).
5. How to run the qualification (Task 28) and the goldens (Task 27).

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

Run: `go build -o bin/ ./cmd/spellbench-gorge-env ./cmd/spellbench-gorge-agent`, then set in `benchmarks/local.json`: `"GORGE_SPELLBENCH_ENV": "C:/Users/Jack/IdeaProjects/spellbench/engines/gorge/bin/spellbench-gorge-env.exe"`, `"GORGE_SPELLBENCH_AGENT": ".../spellbench-gorge-agent.exe"`, `"GORGE_CARDS": "D:/community/gorge/.cards"`.
Expected: P2's loader validates `benchmarks/pauper-gorge/benchmark.json` with no error. If P2's schema differs from the draft fields, edit the file to P2's schema and rerun `TestBenchmarkMatchesTheEngineProfile`.

- [ ] **Step 2: Run P's engine conformance harness against the binary**

Run: P4's documented command with the engine command set to `bin/spellbench-gorge-env.exe -corpus D:/community/gorge/.cards`.
Expected: every envelope and error scenario passes with engine identity masked. Any failure is fixed in the owning task's package with a new test, then this step is rerun.

- [ ] **Step 3: Smoke tournament with the live validator**

Run: P1's tournament launcher on `pauper-gorge`, 1 pair per deck, all four bots.
Expected: validator verdict `pass`, zero `halted` games, gorge agents with zero `malformed_response` or `invalid_selection` forfeits.

- [ ] **Step 4: Compute qualification before the rated run** (`C:/Users/Jack/COMPUTE-POLICY.md`)
- Measure completed games per second with P's launcher at `workers` 1, 4, 8 and 16 on Jack's PC.
- Check HaleysPC and RunPod availability.
- Record the numbers and the chosen allocation in the run manifest.
Expected: the fastest qualified allocation is recorded, and the rated run launches only through P's supported launcher.

- [ ] **Step 5: Rated run and publication gate**

Run: P1's launcher with the recorded allocation and the published commitment.
Expected: a completed run with validator verdict `pass`, `fairness_label` `validator only`, `native_id_extensions` empty, and gorge-bot and gorge-lethal-pressure rated. Publishing the run and pushing branches wait for Jack.

- [ ] **Step 6: Commit**

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
| 6.7 known (`known_cards` false) | T18, T19 |
| 6.8 hidden | T11, T24, T28 |
| 7.1 rules | T13 |
| 7.2 to 7.5 kinds | T14 to T21 |
| 7.6 defaults (none declared; mulligan and starting player by rules) | T8, T23 |
| 8 groups and caps | T13, T22 |
| 9.1 to 9.8 messages and errors | T5, T6, T22, T23 |
| 11.3 validator | T9, T25, T30 |
| 11.4 limits | T29 |
| 11.6 secrets and streams | T4, T8 |
| 11.8 digest | T3, T25 |
| 12 decks and domain | T7, T23 |
| 13 fairness | T24, T28 |
| 14 extensions | T24 |
| 16 goldens and vectors | T3, T4, T27, T30 |

- **Gaps accepted:** `probe_resample` answers `unsupported_request`, as the spec allows for an engine without the probe. `choose_pile` and `choose_cost_option` are not declared; the pool needs neither.
- **Placeholder scan:** every step carries its code. Task 30 depends on P's commands, which it names by deliverable because P has not published them yet.
- **Type consistency:** `NativeOp` (T13) is used unchanged by T14 to T21, T24 and T26; its ops `choose`, `finish`, `none`, `cast`, `list`, `dest` and `amount` are matched one for one by `agent.Pick`, and follow-up keys (`"<option>"`, `"<option>/<follow-up option>"`, `dig_bottom`) are renumbered by `xview.followKey`. `Transaction.Answer` returns `([]decision.Intent, bool, error)` everywhere, and `Env.OpenLook` and `Env.CloseLooks` are used by T18, T19 and T22.
- **Review Focus:** each line has its test in T7, T22, T23 and T26.
