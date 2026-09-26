# Spellbench Protocol v1

Status: v1, draft for community review. This document is the authority for the
`spellbench/v1` wire protocol. Implementations must fail closed: anything this
document does not license is invalid. v1 is 2-player best-of-one only. It does
not claim a spectator/presentation event stream, match play (BO3) or
sideboarding, simultaneous decisions, a cross-engine replay-execution format,
or a universal card-rules database. The protocol is engine-neutral and is
intended to become community-governed; the reference implementation and the
first engine adapter are the mtg-kernel bridge (`agent_bridge_v1`).

## 1. Purpose

Spellbench lets any bot play Magic: The Gathering on any rules engine through
one wire protocol, so independently built engines and models can meet in a
shared tournament arena. One decision at a time is offered to exactly one
seat, as an ordered list of authoritative legal candidates. The bot answers
by picking one candidate. Engines never see the opposing bot; bots never see
hidden state.

Design precedents: mtg-kernel `kernel_rl_jsonl` v5, Manafold
`DECISION_PROTOCOL.md` / `ML_ENVIRONMENT.md`, the mnfl replay-format profiles,
OpenSpiel / PettingZoo information-state conventions.

## 2. Transport and framing

- A participant (engine or agent) is a child process. Messages are
  newline-delimited JSON (NDJSON) over stdin/stdout: exactly one compact JSON
  object per line, UTF-8, `\n` line terminator. `\r\n` is tolerated on read.
- stderr is diagnostics only and is never part of the protocol.
- One request line produces exactly one response line, in order. A sender
  must not pipeline: at most one request is outstanding per process.
- Strict JSON: receivers reject duplicate object keys, non-finite or
  fractional numbers, and non-object top-level values. All protocol numbers
  are integers within the IEEE-754 safe range (`|x| <= 2^53`).
- A line longer than 8 MiB is rejected.
- Closing stdin ends the process. There is no quit message.
- One engine process hosts at most one active game. One agent process may
  serve exactly one seat of one game at a time.

## 3. Roles and topology

Two roles exist. The **environment role** is served by a rules engine. The
**agent role** is served by a bot. A tournament host is the only client of
both:

```
host ──reset/step──▶ engine process (environment role)
host ──game_start/choose/game_over──▶ agent process (agent role, one per seat)
```

The host routes each decision to the agent holding the acting seat and routes
the selection back to the engine. Each agent sees only its own seat's
decisions. The protocol contains no way for an agent to request the opposing
seat's private state; engines must not expose one.

## 4. Common conventions

### 4.1 Envelope fields

Every request carries `request_type` (string), `protocol`
(`"spellbench/v1"`), and `request_id` (string, unique per process from this
sender). Every response carries `response_type`, `protocol`, and the echoed
`request_id`. A `protocol` value other than `"spellbench/v1"` fails with
`protocol_mismatch`.

Retransmitting the identical request (same `request_id`, byte-identical
payload) returns the cached response without side effects; engines MUST and
agents SHOULD support this single-entry idempotent retry. Reusing a
`request_id` with a different payload fails with `request_id_reuse_mismatch`.

### 4.2 Strictness and evolution

Receivers reject unknown fields with `malformed_request`, except fields whose
name matches `x_[a-z0-9_]+` at the designated extension points (Section 9).
Within `spellbench/v1` no field is renamed, reordered, removed, or
reinterpreted. Any change that is not purely additive documentation requires
a new protocol version string.

### 4.3 Canonical JSON and hashes

Canonical JSON: UTF-8, object keys sorted by code point, separators `,` and
`:`, no insignificant whitespace, integers only, strings byte-exact.

`candidates_sha256` in a decision is the lowercase hex SHA-256 of the
canonical JSON of the candidates array reduced to its semantic content:
an array of objects `{"candidate_id": <id>, "semantic": {...}}` in decision
order, with `display_text` excluded (display text is human-facing and may
vary between engine builds).

### 4.4 Seats and ranges

Seats are `"p0"` and `"p1"`. Integer ranges: `step`, `game` counters, seeds,
`group_id` are u64; `candidate_id`, `substep_index`, `substep_count`,
`mode_index`, `option_index`, counts are u32; life and `choose_number` values
are i32.

## 5. Object and target references

An object reference is game-scoped and observer-relative:

```json
{
  "object_id": "obj-000041",
  "card_name": "Lightning Bolt",
  "owner_seat": "p0",
  "controller_seat": "p0",
  "zone": "hand"
}
```

- `object_id` is opaque, chosen by the engine, unique among live objects in
  this game. Engines SHOULD reissue an object's id when it changes zones and
  MUST NOT emit a candidate referencing an id that is stale at emission time.
- `zone` is one of `library, hand, battlefield, graveyard, stack, exile,
  command`.
- `card_name` is the printed English card name, or `null` for an object whose
  identity is hidden from the observing seat (engines must not leak hidden
  identities through references or display text).

A target reference is exactly one of `{"player": "p0"|"p1"}` or
`{"object": <object reference>}`.

## 6. Candidate semantics

Every decision is a choice of exactly one candidate from the authoritative
ordered list. Multi-step operations (multi-target spells, combat
declarations, multi-card ordering) are always decomposed by the engine into a
sequence of such decisions; see Section 8 for grouping.

A candidate is `{"candidate_id": <dense u32 index into this list>,
"semantic": {...}, "display_text": <string|null>}`. `semantic` is a tagged
object: field `kind` plus the fields below. Unknown `kind` values are
`malformed_request` on send and MUST NOT be emitted by a conforming engine.

| kind | additional fields | meaning |
|---|---|---|
| `pass` | — | pass priority / decline an optional prompt |
| `play_land` | `source` | play the referenced land |
| `cast_spell` | `source` | cast the referenced spell (cost/mode fixed by enumeration) |
| `activate_mana_ability` | `source`, `mana_choice`, `cost_target` | `mana_choice`: `"W","U","B","R","G","C"` or null; `cost_target`: target ref or null |
| `activate_ability` | `source`, `ability_index` (u32) | non-mana activated ability |
| `plot_spell` | `source` | plot the referenced card |
| `choose_target` | `source`, `remaining` (u32), `target` | one target of a multi-target sequence |
| `choose_cost_target` | `source`, `cost_kind` (string), `remaining` (u32), `candidate` (object ref) | pay a cost by choosing the referenced object |
| `choose_cast_mode` | `source`, `mode`: `"normal"` or `"alternative"` | |
| `choose_kicker` | `source`, `pay` (bool) | |
| `choose_spell_mode` | `source`, `mode_index`, `mode_count` (u32) | |
| `choose_option` | `source`, `option_index`, `option_count` (u32) | choose among an effect's printed options |
| `choose_effect_target` | `source`, `target`, `selected_count`, `min_targets`, `max_targets` (u32) | |
| `finish_effect_selection` | `source`, `selected_count` (u32) | finish a variable-size selection |
| `choose_color` | `source`, `color`: `"white","blue","black","red","green"` | colorless is not a color |
| `choose_number` | `source`, `value`, `minimum`, `maximum` (i32) | one candidate per legal value |
| `choose_boolean` | `source`, `value` (bool) | |
| `finish_target_selection` | `source`, `selected_count` (u32) | |
| `choose_optional_cost_use` | `use_cost` (bool) | |
| `choose_optional_cost_which` | `choice` (string) | v1 documents `"discard"`, `"sacrifice_land"`; other lowercase snake_case values may appear |
| `choose_spell_copy_payment` | `source`, `pay` (bool) | |
| `choose_spell_copy_retarget` | `source`, `change_target` (bool) | |
| `choose_madness_cast` | `card` (object ref), `cast_it` (bool) | |
| `discard` | `cards` (array of object ref, exactly one entry in v1) | |
| `choose_attacker_inclusion` | `attacker` (object ref), `include` (bool) | one creature of an ordered attacker scan |
| `choose_blocker_inclusion` | `attacker`, `blocker` (object refs), `include` (bool) | one blocker/attacker pair of an ordered scan |
| `order_triggers` | `pending_sources` (array of object ref), `order` (array of u32) | `order[i]` = original index placed at position `i`; one candidate per permutation |

`source` fields are object references. Fields listed for a kind are required
and no others are allowed.

## 7. Environment role messages

### 7.1 `hello`

Request: `{request_type: "hello", protocol, request_id}`.

Response `hello_ok`:

```json
{
  "response_type": "hello_ok",
  "protocol": "spellbench/v1",
  "request_id": "h-1",
  "engine": {
    "name": "mtg-kernel",
    "version": "0.0.4-spike",
    "source_revision": "0123abcd… or null",
    "rules_snapshot_id": "opaque engine string",
    "card_pool_identity": "opaque engine string"
  },
  "formats": ["pauper-bo1"],
  "capabilities": {"decklists_as_data": false},
  "extensions": ["x_kernel_v5"]
}
```

`rules_snapshot_id` and `card_pool_identity` are opaque; equality between two
engines is meaningful only if the engines agree on the naming scheme.
`extensions` lists the `x_*` keys the engine may emit (Section 9).

### 7.2 `reset`

Request:

```json
{
  "request_type": "reset",
  "protocol": "spellbench/v1",
  "request_id": "h-2",
  "game_id": "g-0001",
  "format": "pauper-bo1",
  "seats": [
    {"seat": "p0", "deck": {"catalog_id": "Burn"}},
    {"seat": "p1", "deck": {"decklist": [{"name": "Island", "count": 20}, {"name": "…", "count": 40}]}}
  ],
  "game_seed": 12345,
  "max_decisions": 10000,
  "max_steps": 100000
}
```

`game_id` is a host-chosen string, unique per engine process. `format` must
appear in the engine's `hello.formats`, else `unsupported_format`. A deck is
exactly one of `catalog_id` (engine's catalog) or `decklist` (name+count
rows); engines without decklist support fail `unsupported_deck` (they must
never silently substitute). `max_decisions` caps physical decisions (Section
8); `max_steps` caps individual decisions (steps); engines without the
distinction set both from `max_steps`. Reaching either cap ends the game as
`truncated`. `reset` while a game is active fails `game_already_active`.

Response: the first `decision` (Section 7.3), or `terminal` for a degenerate
game, or `error`.

### 7.3 `decision` (response)

```json
{
  "response_type": "decision",
  "protocol": "spellbench/v1",
  "request_id": "h-2",
  "game_id": "g-0001",
  "step": 0,
  "acting_seat": "p0",
  "group": {"group_id": 0, "substep_index": 0, "substep_count": 1},
  "state_summary": {
    "turn": 1,
    "phase_step": "precombat_main",
    "active_seat": "p0",
    "priority_seat": "p0",
    "seats": [
      {"seat": "p0", "life": 20, "hand_count": 7, "library_count": 53,
       "graveyard_count": 0, "battlefield_count": 0},
      {"seat": "p1", "life": 20, "hand_count": 7, "library_count": 53,
       "graveyard_count": 0, "battlefield_count": 0}
    ],
    "stack_count": 0
  },
  "candidates": [
    {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Pass priority"}
  ],
  "candidates_sha256": "64 hex chars",
  "provenance": {"engine_name": "mtg-kernel", "engine_version": "0.0.4-spike",
                 "rules_snapshot_id": "…", "card_pool_identity": "…"},
  "extensions": {}
}
```

- `step` is 0 for the decision returned by `reset` and increases by exactly 1
  per answered decision. `candidates` is nonempty.
- `phase_step` is one of `untap, upkeep, draw, precombat_main,
  beginning_of_combat, declare_attackers, declare_blockers, combat_damage,
  end_of_combat, postcombat_main, end_step, cleanup`.
- `state_summary` is the entire neutral observation in v1: it contains only
  public scalars and counts, never hidden card identities. Richer
  observations are engine-specific extensions (Section 9). A fuller neutral
  board projection is a v2 candidate and is not claimed here.
- `provenance` repeats the hello engine identity. Hosts pin the first value
  per process and fail on drift.

### 7.4 `step`

Request:

```json
{
  "request_type": "step",
  "protocol": "spellbench/v1",
  "request_id": "h-3",
  "game_id": "g-0001",
  "expected_step": 0,
  "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
}
```

`expected_step` must equal the `step` of the decision being answered
(`expected_step_mismatch`). `selection.candidate_id` must index the current
candidate list (`candidate_id_out_of_range`) and `selection.semantic_echo`
must equal that candidate's `semantic` exactly, field for field
(`semantic_echo_mismatch`). This double binding is the protocol's
stale-candidate guard.

Response: the next `decision`, or `terminal`.

### 7.5 `terminal` (response)

```json
{
  "response_type": "terminal",
  "protocol": "spellbench/v1",
  "request_id": "h-9",
  "game_id": "g-0001",
  "outcome": "p0_win",
  "classification": "natural",
  "winner": "p0",
  "reason": "p1_life_zero",
  "step_count": 412,
  "decision_count": 388,
  "provenance": {"engine_name": "…", "…": "…"}
}
```

- `outcome`: `p0_win | p1_win | draw | truncated | halted`.
  `classification`: `natural | truncated | halted`. A natural terminal has
  outcome/winner pairs `p0_win`/`p0`, `p1_win`/`p1`, `draw`/null; truncated
  and halted have `winner: null` when unassigned by rule.
- Only `natural` terminals with outcome `p0_win`, `p1_win`, or `draw` are
  admissible for ratings. `truncated` (cap reached) and `halted` (engine
  contract failure) games are recorded and excluded.
- `step_count` and `decision_count` are the totals for the completed game.

### 7.6 `error` (response)

`{response_type: "error", protocol, request_id, error: {code, message}}`.
`message` is human-facing only; `code` is closed:

`malformed_json, malformed_request, protocol_mismatch,
request_id_reuse_mismatch, step_before_reset, game_already_active,
game_id_mismatch, expected_step_mismatch, candidate_id_out_of_range,
semantic_echo_mismatch, unsupported_format, unsupported_deck,
game_already_terminal`

## 8. Decision groups (substeps)

Engines that decompose one physical game decision (for example an
include/exclude scan over attackers) into several wire decisions mark them
with `group`: equal `group_id` and `acting_seat`, `substep_index` running
`0..substep_count-1`, `substep_count` fixed across the group. `group_id`
advances by exactly 1 after a completed group. A terminal must not interrupt
a partial group: an engine that cannot complete a group fails the whole game
as `halted`. Engines without decomposition always emit `substep_index: 0,
substep_count: 1` with `group_id` equal to the physical decision count.

## 9. Extensions

A decision may carry an `extensions` object whose keys match
`x_[a-z0-9_]+`; any other key is `malformed_request`. Extensions are
engine-specific, optional to emit, and ignored by readers that do not know
them. The mtg-kernel bridge emits `x_kernel_v5` carrying the raw
`ObservationV5` and `LegalActionV5` payloads so that kernel-native models can
play without a neutral re-encoding. Hosts pass extensions through unchanged.

## 10. Agent role messages

### 10.1 `hello`

Request `{request_type: "hello", protocol, request_id}`; response
`hello_ok`:

```json
{
  "response_type": "hello_ok",
  "protocol": "spellbench/v1",
  "request_id": "h-1",
  "bot": {"name": "uniform", "version": "1.0.0"},
  "extensions_accepted": []
}
```

### 10.2 `game_start`

Request:

```json
{
  "request_type": "game_start",
  "protocol": "spellbench/v1",
  "request_id": "h-2",
  "game_id": "g-0001",
  "seat": "p0",
  "format": "pauper-bo1",
  "decks": [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
  "engine": {"name": "mtg-kernel", "version": "0.0.4-spike",
             "source_revision": null, "rules_snapshot_id": "…",
             "card_pool_identity": "…"}
}
```

`decks` is ordered by seat (`p0` first); a bot that requires its own seat's
list reads `decks[seat]`. Response: `{response_type: "ack", protocol,
request_id}`. An agent serving a new `game_id` while one is active fails
`game_already_active` (one game per agent process).

### 10.3 `choose`

Request:

```json
{
  "request_type": "choose",
  "protocol": "spellbench/v1",
  "request_id": "h-3",
  "game_id": "g-0001",
  "decision": { …the exact decision object received from the engine… }
}
```

Response `choice`:

```json
{
  "response_type": "choice",
  "protocol": "spellbench/v1",
  "request_id": "h-3",
  "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
}
```

The host forwards `selection` to the engine in a `step` request. The agent
MUST answer a pending decision before any other request; a second request of
any type while a decision is pending fails `decision_pending` (except a
retransmitted identical `choose`, Section 4.1).

### 10.4 `game_over`

Request `{request_type: "game_over", protocol, request_id, game_id,
terminal: {outcome, classification, winner, reason, step_count,
decision_count}}`. Response: `ack`. After `game_over` the agent process
serves no further requests for that game.

### 10.5 Agent error codes

`malformed_json, malformed_request, protocol_mismatch,
request_id_reuse_mismatch, unknown_game, no_pending_decision,
decision_pending, game_already_active, internal_error`

## 11. Conformance

- Golden transcripts live in `goldens/protocol_v1/*.transcript.jsonl`, one
  message per line as `{"dir": "host_to_engine"|"engine_to_host"|
  "host_to_agent"|"agent_to_host", "message": {...}}`. The reference Python
  stack replays them byte-exactly in both roles; engine adapters should
  replay the environment-role portion.
- An implementation fails closed: it emits only licensed messages, rejects
  everything else with the pinned error codes, and never guesses at an
  unlisted `kind`, `format`, or field.
- There are no timeouts in the protocol. Hosts enforce wall-clock budgets
  externally; a slow or stuck participant loses its process, and the host
  adjudicates the game (forfeit) outside the protocol.
