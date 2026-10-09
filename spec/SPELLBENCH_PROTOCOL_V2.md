# Spellbench Protocol v2

Status: v2.0, draft for community review. This document is the authority for the `spellbench/v2` wire protocol. It is standalone: a reader does not need the v1 specification. v2 is a clean break from `spellbench/v1`; no v1 message is valid in v2.

- **Strictness.** Engines and the host fail closed: anything this document does not license is invalid. Agents are lenient (Section 4.2), so a trivial bot is easy to write.
- **Scope.** v2 is 2-player best-of-one only. It does not claim a spectator or presentation event stream, a public event history, match play (BO3) or sideboarding, simultaneous decisions, multiplayer or Commander, a cross-engine replay-execution format, or a universal card-rules database.
- **Reserved features.** Some features are specified but reserved for a later minor version (Section 4.5).
- **Fairness.** Every v2.0 engine is labelled "fairness: validator only". The host validates every decision against the rules it can check, but it has no ground truth about hidden state. Section 13 lists the residual channels, including wall-clock timing.

The protocol is engine-neutral and is intended to become community-governed. Annexes A to C describe, informatively, how the first three engine adapters (mtg-kernel, gorge, XMage through the CABT bridge) meet it.

Design precedents: mtg-kernel `kernel_rl_jsonl` v5 and its search redaction; the Manafold decision protocol and information model; the mnfl replay-format profiles; gorge's per-seat view and decision contract; the CABT legal-option bridge for XMage; the DraftZero `StateSpec`; the Phase and Argentum decision surfaces; OpenSpiel and PettingZoo information-state conventions; RFC 8785 (JSON canonicalization).

## 1. Purpose

Spellbench lets any bot play Magic: The Gathering on any rules engine through one wire protocol, so independently built engines and models can meet in a shared tournament arena. The engine offers one decision at a time to exactly one seat. Each decision carries an ordered list of authoritative legal candidates and a neutral board view from that seat's perspective. The bot answers by picking one candidate.

Engines never see the opposing bot. No message or field licensed to a bot carries hidden state. The host checks every decision before a bot sees it. The residual channels this does not close are listed in Section 13.

## 2. Transport and framing

- A participant (engine or agent) is a child process of the host. Messages are newline-delimited JSON (NDJSON) over stdin/stdout: exactly one JSON object per line, UTF-8, `\n` line terminator. `\r\n` is tolerated on read.
- stderr is diagnostics only and is never part of the protocol. The host never forwards one process's stderr to another.
- One request line produces exactly one response line, in order. A sender must not pipeline: at most one request is outstanding per process.
- Strict JSON, for engines and the host:
  - receivers reject duplicate object keys, non-object top-level values, numbers with a fraction or an exponent, nesting deeper than 64 levels, and unpaired surrogate escapes (I-JSON, RFC 7493, which RFC 8785 relies on);
  - all protocol numbers are integer literals with `|x| <= 2^53 - 1`.
- Line length: every reader accepts lines up to 8 MiB and rejects longer ones. A reader built on a line scanner must raise its default buffer (Go's `bufio.Scanner` defaults to 64 KiB).
- Closing stdin ends the process. There is no quit message.
- One engine process hosts at most one active game. One agent process serves exactly one seat of one game at a time. In verified runs, each game gets a fresh agent sandbox (Section 11.7).

## 3. Roles and topology

Two roles exist. The **environment role** is served by a rules engine. The **agent role** is served by a bot. A tournament host is the only client of both:

```
host --hello/reset/step--> engine process (environment role)
host --hello/game_start/choose/game_over--> agent process (agent role, one per seat)
```

The engine answers `reset` and `step` with a `decision` for one seat, or a `terminal`. A decision has two parts:
- the **binding** (`step`), for the host and the engine only;
- the **seat decision** (`seat_decision`), everything the acting seat may know.

The host validates each seat decision (Section 11.3) and forwards its own canonical re-serialization of it (Section 4.3) to the agent holding the acting seat. It then returns the agent's selection to the engine.

Each agent sees only its own seat's decisions. The protocol contains no way for an agent to request the opposing seat's private state, and engines must not expose one.

## 4. Common conventions

### 4.1 Envelope fields

- **Requests** carry `request_type` (string), `protocol` (`"spellbench/v2"`) and `request_id` (nonempty string, unique per process from this sender). A `request_id` the host sends to an agent encodes nothing beyond that agent's own request count. The recommended form is `"r-<n>"`, where n counts requests sent to that agent process.
- **Responses** carry `response_type`, `protocol`, and the echoed `request_id`. An error answering a request whose `request_id` cannot be read (unparseable JSON, a missing or non-string id) carries `""`.
- **Protocol value.** A `protocol` other than `"spellbench/v2"` fails with `protocol_mismatch`; a missing or non-string `protocol` fails with `malformed_request`.
- **Retransmission (engines).** Retransmitting the identical request (same `request_id`, identical payload) returns the cached response without side effects. Reusing a `request_id` with a different payload fails with `request_id_reuse_mismatch`. Requests that fail parsing are never cached.
- **Retransmission (agents).** Hosts do not retransmit to agents in v2.0, so agents need no cache.

### 4.2 Strictness, leniency and evolution

- **Engines and the host are strict.**
  - They reject unknown fields with `malformed_request`. The one exception is keys matching `x_[a-z0-9_]+` in `seat_decision.extensions`, the only engine extension point (Section 14).
  - Every field listed for a message or object is required. Nullable fields are sent as explicit `null`, never omitted.
- **Agents are lenient.**
  - They ignore unknown fields anywhere in what they receive.
  - They may skip validating anything they do not read, and may parse leniently.
  - The host, in turn, ignores unknown fields and `x_` keys in agent responses (Section 10).
- **Minor versions.**
  - The host's `hello` carries `protocol_minor` (u32). An engine answers with `protocol_minor` no greater than the host's, and both then use the smaller value.
  - A minor version may add optional fields, vocabulary values, decision kinds, requests or error codes. A sender uses them only when the negotiated minor includes them.
  - v2.0 is minor 0.
- **Breaking changes.** A minor version never renames, removes or reinterprets anything. Such a change requires `spellbench/v3`.

### 4.3 Canonical JSON and digests

Canonical JSON is RFC 8785 (JSON Canonicalization Scheme). Protocol keys are ASCII and protocol numbers are integers, so it amounts to:
- object keys sorted by code point;
- separators `,` and `:`, and no whitespace;
- integers in shortest decimal form;
- strings with only `"`, `\` and control characters escaped (`\b \f \n \r \t`, or `\u00xx` in lowercase hex), and every other character written as raw UTF-8.

Canonical JSON is the host's business:
- The host forwards the canonical re-serialization of each validated `seat_decision`.
- The host computes every digest the protocol defines over canonical JSON.
- Engines may serialize their responses in any valid JSON layout. They need not reproduce the host's bytes.

The host computes these identifiers:

| Identifier | Input | Form |
|---|---|---|
| `deck_id` | the decklist as rows `{"count", "name"}`, one row per distinct name, sorted by name in code point order | `"sha256:"` + 64 lowercase hex |
| `card_name_domain.domain_id` | the names array, sorted in code point order | `"sha256:"` + 64 lowercase hex |
| `game_digest` | the chain of Section 11.8 | `"sha256:"` + 64 lowercase hex |

Test vectors are in Section 16.

### 4.4 Seats, integers, strings and card names

- Seats are `"p0"` and `"p1"`.
- Non-negative counters and identifiers (`step`, `seat_step`, `group_id`, `agent_seed`, `max_decisions`, `max_steps`, `turn`, time values in milliseconds) are integers in `[0, 2^53 - 1]`.
- Indices, counts and amounts (`candidate_id`, `substep_index`, `substep_count`, `hand_count`, `mana_value`, `damage`, counter values, and so on) are u32.
- Life, power, toughness and `choose_number` values are i32.
- Vocabulary values are lowercase snake_case (`[a-z][a-z0-9_]*`) unless stated otherwise.
- **Card names** are Scryfall Oracle names in Unicode NFC. Decklists name a multi-face card by its full name, `"A // B"`. Object references name the face currently up (Section 5.1).

### 4.5 Conformance levels and reserved features

**v2.0 conformance** covers:
- the envelope and transport (Sections 2 to 4);
- routing, canonical forwarding and the live validator (Section 11);
- the observation with its knowledge rules (Section 6);
- the v2.0 decision kinds and engine defaults (Section 7);
- decks and information rules (Section 12);
- clocks, limits and forfeits;
- secrets, isolation and the per-game digest;
- the fairness contract (Section 13), golden transcripts with test vectors, and error codes.

**Reserved features** are specified here, but v2.0 engines do not emit them and v2.0 hosts do not send them. A later minor version enables each one, and it becomes required when the first engine or benchmark that needs it ships. They are:
- the noninterference probe (`probe_resample`, Section 9.7);
- fixed-deck benchmarks (Section 15);
- the `pay_mana`, `narrow_name` and `narrow_number` kinds (Section 7.7);
- extensions with native ids in rated runs, unless a benchmark lists them after an audit (Section 14);
- enforcement of `resources` beyond declaring them (Section 11.4).

## 5. Object and target references

### 5.1 Object references

An object reference is game-scoped and observer-relative:

```json
{"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
```

- `object_id`: an opaque string, per Section 5.3.
- `card_name`: the Oracle name of the face currently up (a transformed card reads as its back face). It is `null` for an object whose identity is hidden from the observing seat. For an ability on the stack, it is the name of the ability's source.
- `owner_seat` and `controller_seat`: seats. An object without a controller (a card in a graveyard, library, hand or exile) has its owner as controller.
- `zone`: one of `library, hand, battlefield, graveyard, stack, exile, command`.
- **Must match.** Every non-null object reference in a decision equals, field for field, the observation record with the same `object_id` (Section 6).
- **Absent objects become null.** A reference to an object that is no longer in the observation is sent as `null`. Examples: a stack target that left the battlefield, a planeswalker that was being attacked and is gone, an exiling object that left.

### 5.2 Target references

A target reference is exactly one of `{"player": "p0" | "p1"}` or `{"object": <object reference>}`.

### 5.3 Object identity

- **Fresh on zone change.** An object that changes zones is a new object (CR 400.7) and gets a new `object_id`.
- **Fresh on each look.** An object in a zone hidden from the viewer (a library, or the other seat's hand) gets a fresh `object_id` each time an effect shows it to the viewer. Within one effect's decisions the id is stable.
- **Never reused.** An id never appears in two zones, and an id that has left a seat's observation never returns to it.
- **Per viewer.** Ids belong to one observing seat. The same object has different ids in the two seats' decisions.
- **Carries nothing hidden.** An id carries no information beyond that seat's observation. It is not, and is not derived reversibly from, a physical card id, a deck-slot index, a library position, or a counter that advances on events hidden from the seat.
- **Deterministic.** Ids are a function of the game secret (Section 11.6), the viewer, and the engine's internal identity of the object. A rerun of the same game with the same secret and the same answers reproduces every id.
- **Unique.** Two live objects never share an id in one seat's decision. An engine that detects a collision ends the game `halted`.

Recommended construction. Any construction meeting the rules above is conforming.

```
id_key    = HMAC-SHA256(key = game_secret (32 bytes), message = ASCII "spellbench/v2/object-id")
object_id = "o-" + lowercase hex of the first 8 bytes of HMAC-SHA256(key = id_key, message = M)
M         = UTF-8 "<viewer>:<internal key>"                 for objects in zones visible to the viewer
M         = UTF-8 "<viewer>:<internal key>:look:<n>"        for objects in zones hidden from the viewer
```

- The internal key is any engine string that identifies the object during its stay in its current zone and changes on every zone change (for example `"<internal id>:z<zone change count>"`).
- `n` counts, per viewer, the effects that have shown that object to the viewer during its stay in the zone.
- The internal key, `id_key` and the game secret never reach agents.

Note: per-viewer ids prevent correlating an object across the two seats' streams. Fresh ids per look stop a viewer from telling whether a card it saw earlier is the same card now (for example, whether a known card was put back on top of a library).

## 6. Observation

Every `seat_decision` carries `observation`: the acting seat's information state and nothing more (`viewer` equals `acting_seat`).

### 6.1 Example

The example comes from an engine whose optional observation flags (Section 6.9) are `designations`, `passed_seats`, `pending_triggers`, `keywords`, `exiled_by`, `permanent_details` and `known_cards` true, and `poison`, `player_counters`, `player_progress`, `day_night`, `full_name` and `stack_text` false. Object ids here are illustrative.

```json
{
  "viewer": "p0",
  "turn": 5,
  "phase_step": "precombat_main",
  "active_seat": "p0",
  "priority_seat": "p0",
  "passed_seats": [],
  "day_night": null,
  "players": [
    {
      "seat": "p0", "life": 14, "poison": null, "counters": null,
      "mana_pool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
      "lands_played_this_turn": 0, "mulligans_taken": 0, "designations": [], "progress": null,
      "hand_count": 2, "library_count": 46,
      "hand": [
        {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand",
         "full_name": null, "face_down": false, "token": false, "copy": false,
         "characteristics": {"supertypes": [], "types": ["instant"], "subtypes": [], "colors": ["red"],
                             "mana_value": 1, "power": null, "toughness": null, "keywords": []},
         "permanent": null, "exiled_by": null},
        {"object_id": "o-2b8e4dafc6031912", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand",
         "full_name": null, "face_down": false, "token": false, "copy": false,
         "characteristics": {"supertypes": ["basic"], "types": ["land"], "subtypes": ["mountain"], "colors": [],
                             "mana_value": 0, "power": null, "toughness": null, "keywords": []},
         "permanent": null, "exiled_by": null}
      ],
      "battlefield": [
        {"object_id": "o-4da06fc1e8253b34", "card_name": "Monastery Swiftspear", "owner_seat": "p0", "controller_seat": "p0", "zone": "battlefield",
         "full_name": null, "face_down": false, "token": false, "copy": false,
         "characteristics": {"supertypes": [], "types": ["creature"], "subtypes": ["human", "monk"], "colors": ["red"],
                             "mana_value": 1, "power": 2, "toughness": 3, "keywords": ["haste", "prowess"]},
         "permanent": {"tapped": false, "summoning_sick": false, "damage": 0, "counters": {"p1p1": 1},
                       "attached_to": null, "attacking": false, "attack_target": null,
                       "blocking": false, "blocked_attackers": [], "phased_out": false,
                       "statuses": [], "class_level": null, "chosen": []},
         "exiled_by": null}
      ],
      "graveyard": [],
      "exile": [],
      "command": []
    },
    {
      "seat": "p1", "life": 11, "poison": null, "counters": null,
      "mana_pool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
      "lands_played_this_turn": 0, "mulligans_taken": 1, "designations": [], "progress": null,
      "hand_count": 3, "library_count": 47,
      "hand": null,
      "battlefield": [
        {"object_id": "o-6fc281e30a475d56", "card_name": "Spellstutter Sprite", "owner_seat": "p1", "controller_seat": "p1", "zone": "battlefield",
         "full_name": null, "face_down": false, "token": false, "copy": false,
         "characteristics": {"supertypes": [], "types": ["creature"], "subtypes": ["faerie", "wizard"], "colors": ["blue"],
                             "mana_value": 2, "power": 1, "toughness": 1, "keywords": ["flash", "flying"]},
         "permanent": {"tapped": true, "summoning_sick": false, "damage": 0, "counters": {},
                       "attached_to": null, "attacking": false, "attack_target": null,
                       "blocking": false, "blocked_attackers": [], "phased_out": false,
                       "statuses": [], "class_level": null, "chosen": []},
         "exiled_by": null}
      ],
      "graveyard": [],
      "exile": [],
      "command": []
    }
  ],
  "stack": [],
  "pending_triggers": [],
  "known": [
    {"owner_seat": "p0", "zone": "library", "card_name": "Mountain", "object_id": null,
     "position_from_top": 0, "position_from_bottom": null, "how": "looked_at"},
    {"owner_seat": "p1", "zone": "hand", "card_name": "Counterspell", "object_id": null,
     "position_from_top": null, "position_from_bottom": null, "how": "revealed"}
  ]
}
```

### 6.2 Game fields

| Field | Type | Meaning |
|---|---|---|
| `viewer` | seat | the observing seat; equals `acting_seat` |
| `turn` | integer | game turn number: 1 on the first turn, counting both players' turns; 0 before the first turn |
| `phase_step` | string | `pregame` (mulligans and the starting-player choice, with `turn` 0) or one of `untap, upkeep, draw, precombat_main, beginning_of_combat, declare_attackers, declare_blockers, combat_damage, end_of_combat, postcombat_main, end_step, cleanup` |
| `active_seat` | seat or null | the active player; `null` only in `pregame` before the starting player is decided |
| `priority_seat` | seat or null | the seat holding priority; `null` while no player has priority (resolution, turn-based actions, `pregame`) |
| `passed_seats` | array of seats, or null | optional: seats that have passed priority in succession since the stack or the step last changed |
| `day_night` | string or null | optional: `day`, `night`, or `none` (neither has occurred yet) |
| `players` | array | exactly two entries, `p0` then `p1` (Section 6.3) |
| `stack` | array | stack entries; index 0 is the bottom and the last entry resolves first (Section 6.5) |
| `pending_triggers` | array or null | optional: triggered abilities waiting to be put on the stack (Section 6.6) |
| `known` | array | knowledge of cards in hidden zones (Section 6.7); always an array |

### 6.3 Player fields

| Field | Type | Meaning |
|---|---|---|
| `seat` | seat | |
| `life` | i32 | life total |
| `poison` | u32 or null | optional: poison counters |
| `counters` | object or null | optional: other player counters by canonical name (Section 6.10), for example `{"energy": 2}` |
| `mana_pool` | object | floating mana, exactly the keys `W, U, B, R, G, C` with u32 values; public (CR 106.4) |
| `lands_played_this_turn` | u32 | |
| `mulligans_taken` | u32 | mulligans this player took this game (public) |
| `designations` | array or null | optional: designations this player has (Section 6.10) |
| `progress` | object or null | optional: `{"dungeon": string or null, "dungeon_room": string or null, "ring_tempted": u32, "speed": u32 or null}` |
| `hand_count` | u32 | cards in hand |
| `library_count` | u32 | cards in library |
| `hand` | array or null | the viewer's own hand as object records in engine order; `null` for the other seat |
| `battlefield` | array | permanents this seat controls, oldest first |
| `graveyard` | array | cards this seat owns, oldest first (index 0 is the bottom) |
| `exile` | array | cards this seat owns, oldest first; face-down cards per Section 6.8 |
| `command` | array | command-zone objects this seat owns (emblems, and so on) |

For the viewer, `hand` has exactly `hand_count` records. No object record in any zone array has zone `library`: library knowledge is carried only by `known`.

### 6.4 Object records

An object record is an object reference (Section 5.1) plus these fields, all always present:

| Field | Type | Meaning |
|---|---|---|
| `full_name` | string or null | optional: the Oracle full name of a multi-face card (`"A // B"`) |
| `face_down` | bool | |
| `token` | bool | |
| `copy` | bool | the object is a copy of a card or permanent (a token created as a copy is `token: true, copy: true`) |
| `characteristics` | object or null | current values after continuous effects; `null` only for a face-down card outside the battlefield and the stack whose identity is hidden from the viewer |
| `permanent` | object or null | non-null exactly when `zone` is `battlefield` |
| `exiled_by` | object reference or null | optional: the object whose effect exiled this card and may return it; `null` when there is none or it has left |

`characteristics`:

| Field | Type | Meaning |
|---|---|---|
| `supertypes` | array of strings | Section 6.10 |
| `types` | array of strings | Section 6.10 |
| `subtypes` | array of strings | normalized per Section 6.10 |
| `colors` | array of strings | subset of `white, blue, black, red, green`, in that order |
| `mana_value` | u32 | |
| `power`, `toughness` | i32 or null | creatures only |
| `keywords` | array of strings, or null | optional: keyword abilities the object has (Section 6.10) |

Face-down permanents and spells show their face-down characteristics (CR 708.2, 708.4), for example a nameless 2/2 colorless creature. `card_name` is then `null` unless the viewer may look at the object (Section 6.8).

`permanent`:

| Field | Type | Meaning |
|---|---|---|
| `tapped` | bool | |
| `summoning_sick` | bool | not continuously controlled by its controller since that player's most recent turn began (CR 302.6); the fact, before haste |
| `damage` | u32 | damage marked this turn |
| `counters` | object | counters by canonical name (Section 6.10); `{}` when none |
| `attached_to` | target reference or null | what this Aura or Equipment is attached to |
| `attacking` | bool | the creature is an attacking creature |
| `attack_target` | target reference or null | the player, planeswalker or battle it attacks; `null` when not attacking or when that permanent has left |
| `blocking` | bool | the creature is a blocking creature (it stays one after the attacker is removed, CR 509.1h) |
| `blocked_attackers` | array of object references | the attackers it blocks that are still on the battlefield |
| `phased_out` | bool | |
| `statuses` | array of strings, or null | optional (`permanent_details`): public statuses (Section 6.10); `[]` when none |
| `class_level` | u32 or null | optional (`permanent_details`): the level of a Class; `null` for other permanents |
| `chosen` | array or null | optional (`permanent_details`): public values chosen for this permanent, each `{"kind": string, "value": string}` (Section 6.10), for example Pithing Needle's named card; `[]` when none |

### 6.5 Stack entries

| Field | Type | Meaning |
|---|---|---|
| `object_id`, `card_name`, `owner_seat`, `controller_seat`, `zone` | reference fields | `zone` is `stack`; the entry can be targeted by this reference |
| `stack_kind` | string | `spell`, `activated_ability` or `triggered_ability` |
| `source` | object reference or null | for an ability, its source while that object still exists; `null` for spells and for abilities whose source has left |
| `face_down` | bool | a face-down spell; its `card_name` is `null` unless its controller is the viewer |
| `copy` | bool | a copy of a spell or ability |
| `characteristics` | object or null | spells only (Section 6.4; face-down spells show face-down characteristics); `null` for abilities |
| `targets` | array of target references or nulls | chosen targets in target order; a target that no longer exists is `null` |
| `divided` | array of u32, or null | the amounts divided among `targets` as announced (CR 601.2d), or `null` |
| `modes` | array of u32, or null | chosen mode indices, or `null` for a non-modal object |
| `x_value` | u32 or null | the announced value of X, or `null` |
| `text` | string or null | optional: human-facing description |

### 6.6 Pending triggers

Entries of `pending_triggers`, in the order they would be put on the stack under the engine's current ordering: `{"source": <reference or null>, "source_name": <string or null>, "controller_seat": seat, "label": <string or null>, "optional": bool}`.

Triggered abilities waiting to be put on the stack are public, except one whose source is in a zone hidden from the viewer and not revealed (for example a trigger from a card in the other seat's hand). That one is omitted from the viewer's list.

### 6.7 Knowledge

`known` lists what the viewer knows about cards in hidden zones. It is name-level and positional, never object-level. Each entry is:

```json
{"owner_seat": "p1", "zone": "hand", "card_name": "Counterspell", "object_id": null,
 "position_from_top": null, "position_from_bottom": null, "how": "revealed"}
```

- **Zones.** `zone` is `hand` or `library`. The viewer's own hand is never listed here; it is in `players[viewer].hand`.
- **How.** `how` is `revealed`, `looked_at`, `from_public_zone`, `own_placement`, `searching` or `tracked` (a known library card followed into a hand).
- **Hand entries** describe the other seat's hand, and their positions are `null`. The number of hand entries for a seat never exceeds its `hand_count`.
- **Library entries** have exactly one non-null position (0 is the top or the bottom card), except `how: "searching"`, where both may be `null`.
- **Object ids.** `object_id` is `null`, except for cards being looked at, revealed or searched in the current decision, which carry fresh object ids (Section 5.3). A reference to such a card is `{object_id, card_name, owner_seat, controller_seat, zone}`, with `controller_seat` equal to `owner_seat`. Every object a candidate references appears in a zone array, on the stack, or here.
- **Order.** Entries are sorted by `owner_seat`, `zone`, `card_name`, `position_from_top`, `position_from_bottom`, `how`, `object_id` (nulls first), so their order encodes nothing hidden.
- **Declaring knowledge.** An engine sets `known_cards` true only if it implements the update table below. With `known_cards` false, `known` lists only the cards being looked at, revealed or searched in the current decision. Under-informing is allowed when declared; over-informing never is.

Update table (applied from the viewer's perspective, in event order):

| Event | Update |
|---|---|
| A card moves from a public zone to the other seat's hand | add a hand entry with its name (`from_public_zone`) |
| A card the viewer knows at a library position moves to that library owner's hand | move the knowledge to a hand entry (`tracked`) |
| The other seat's hand is revealed to the viewer | replace that hand's entries with the revealed cards (`revealed`) |
| A card leaves the other seat's hand to a public zone, or is revealed as it leaves | remove one entry with that name, if any |
| A card leaves the other seat's hand to a hidden zone, unidentified to the viewer (for example put on top of a library, or exiled face down) | once per departing card, every name's count of entries c becomes max(0, c - 1) |
| The other seat's hand is shuffled into a library, exchanged, or otherwise randomized | remove all of that hand's entries |
| A library is shuffled | remove all of that library's entries |
| The viewer looks at or reveals library cards, or places its own cards at known positions | add entries with their positions (`looked_at`, `revealed`, `own_placement`) |
| A card leaves the top (or bottom) of a library | remove the entry at that end, and renumber the other entries counted from that end |
| A card is put on the top (or bottom) of a library | renumber the entries counted from that end; add an entry if the viewer knows the card |
| Cards of a library are rearranged by a choice hidden from the viewer (the other seat scries, surveils or orders cards) | remove the viewer's entries for every card that could have moved |
| A card is put into a library at a position the viewer cannot compute, or at an intermediate position | remove every entry the insertion makes ambiguous |
| A card leaves a library from a position the viewer does not know (for example a tutor without a shuffle) | remove every entry the removal makes ambiguous |

### 6.8 What is hidden

Never present in an observation, a candidate, a context, an extension, or any text sent to a seat:

- the identity of any card in the other seat's hand, or in either library, beyond Section 6.7;
- library order beyond the viewer's known positions (the viewer's own library included);
- the identity and printed characteristics of a face-down object, except to the players the rules and the effect let look at it:
  - on the battlefield and the stack, its controller (CR 708.5);
  - in exile, the players the exiling effect lets look (for example the player allowed to cast a card exiled face down by Gonti, Lord of Luxury, or the owner of a foretold card), and nobody else;
- the other seat's decklist, unless the benchmark shows it (Section 12.2);
- the other seat's pending or unrevealed choices (for example the order of its mulligan bottom cards, or a secretly chosen name);
- random state, secrets, and any result of future randomness;
- engine-internal identities and counters (Section 5.3), and anything about the other seat's decisions, candidates or timing.

Note: cards that let a player look at face-down permanents they do not control are out of scope for v2.0 benchmarks.

### 6.9 Optional fields

Thirteen observation fields are optional. The engine declares each as a boolean flag in `hello_ok.observation` (Section 9.1):

| Flag | Field |
|---|---|
| `poison` | `players[].poison` |
| `player_counters` | `players[].counters` |
| `designations` | `players[].designations` |
| `player_progress` | `players[].progress` |
| `day_night` | `day_night` |
| `passed_seats` | `passed_seats` |
| `pending_triggers` | `pending_triggers` |
| `keywords` | `characteristics.keywords` |
| `full_name` | `full_name` |
| `exiled_by` | `exiled_by` |
| `stack_text` | stack entries' `text` |
| `permanent_details` | `permanent.statuses`, `permanent.class_level`, `permanent.chosen` |
| `known_cards` | whether `known` follows the update table of Section 6.7 |

- A field is non-null only if its flag is true. A field whose flag is false is always present and always `null` (`known` stays an array).
- With its flag true, a field is `null` only in these cases:
  - `full_name` for single-faced cards;
  - `exiled_by` for cards exiled without a returning link, or whose exiling object has left;
  - stack `text` where the engine has none;
  - `class_level` for permanents that are not Classes.
- Every other field is required for every engine.

### 6.10 Vocabularies

- **Supertypes:** `basic, legendary, ongoing, snow, world`.
- **Card types:** `artifact, battle, conspiracy, creature, dungeon, enchantment, instant, kindred, land, phenomenon, plane, planeswalker, scheme, sorcery, vanguard`.
- **Subtypes:** the Comprehensive Rules spelling, normalized as follows. Keywords, counter names, statuses and designations below use the same normalization.
  - lowercase;
  - apostrophes removed;
  - spaces and hyphens become `_`.

  For example `human`, `urzas`, `time_lord`.
- **Colors:** `white, blue, black, red, green`.
- **Counters:** power/toughness counters are `p` or `m` for each sign followed by the digits, for example `p1p1`, `m1m1`, `m0m1`, `p1p0`. Other counters use the counter's normalized name, for example `loyalty`, `defense`, `charge`, `stun`, `lore`, `shield`, `oil`, `energy`, `experience`.
- **Keywords:** CR 702 keyword names, without parameters, for example `flying`, `first_strike`, `protection`, `ward`, `landwalk`.
- **Statuses:** `goaded, suspected, monstrous, renowned, saddled, solved, unlocked_left, unlocked_right, flipped`, or another public status.
- **Chosen kinds:** `color, card_name, creature_type, card_type, land_type, number, player, mode, other`. Values are strings: names as in Section 4.4, numbers in decimal, players as seats.
- **Designations:** `monarch`, `initiative`, `city_blessing`, or another designation.
- **Mana symbols** in `mana_pool` and `mana_choice`: `W, U, B, R, G, C`.

## 7. Candidate semantics

### 7.1 Rules

- **One pick per decision.** Every decision is a choice of exactly one candidate from the authoritative ordered list. A candidate is `{"candidate_id": <u32, dense index into the list>, "semantic": {...}, "display_text": <string or null>}`.
  - `semantic` is a tagged object: `kind` plus the fields listed for that kind, all required, no others allowed.
  - A conforming engine never emits an unknown `kind` or vocabulary value. Strict receivers reject one with `malformed_request`.
- **Distinct.** The candidates of one decision have pairwise-distinct `semantic` values.
- **Pass first.** Whenever `pass` is legal, it is candidate 0.
- **Decomposition.** An answer with several parts (multiple targets, attack and block declarations, orders, arrangements, distributions) is decomposed into a sequence of decisions, grouped per Section 8.
- **No dead ends.** Every candidate must be extendable to a legal complete answer. This covers required attackers, blocking restrictions such as menace, minimum counts, pile sizes, distribution minimums and payable costs.
  - An engine that cannot guarantee this for a decision poses it as one enumerated decision.
  - If it declares `rewind` (Section 8), it abandons the group and re-poses the priority decision without the failing candidate.
  - Otherwise it ends the game `halted`.
- **At most 4096 candidates.** In v2.0, an engine whose decision would exceed 4096 candidates ends the game `halted` with reason `engine_contract_failure:candidate_limit`. The reserved narrowing kinds (Section 7.7) will lift this.
  - Engines bound open domains to game-relevant values. For example, a number naming a mana value is bounded by the largest mana value in the benchmark's card pool, and a payment by what can be paid.
  - A deck whose cards need a domain that cannot be bounded within 4096 fails `unsupported_deck` at preflight, rather than halting mid-game.
- **Deterministic order.** Candidate order depends only on what the acting seat can see. Candidates that reference cards in hidden zones (a library, or the other seat's hand) appear, among themselves, in order of the referenced card's `card_name`, then `object_id`.
- **`display_text`** is human-facing, may differ between engine builds, and is subject to Section 6.8.

A decision's `context.kind` is `priority` when its candidates are priority kinds (Section 7.2), and `choice` when they are choice kinds (Section 7.3). The families do not mix, with one exception, for paying a mana cost during resolution (CR 605.3a), so that engines which float mana before paying can pay "unless" and ward costs:
- A decision whose candidates are `optional_cost` for a cost with a mana component (for example `unless_payment`) may also offer `activate_mana_ability`. Such a decision has `context.purpose: "mana_payment"`.
- It is re-posed after each activation.
- `pay: true` is offered only once the mana pool covers the mana cost, while `pay: false` is always offered.

### 7.2 Priority kinds

| kind | fields | meaning |
|---|---|---|
| `pass` | (none) | pass priority |
| `play_land` | `source`, `face` (u32) | play the referenced land with face `face` up (0 is the front; for modal double-faced and similar lands, 1 is the back) |
| `cast_spell` | `source`, `method` | cast the referenced card; `method` from Section 7.4, or `null` when a `choose_cast_method` decision follows |
| `activate_mana_ability` | `source`, `ability_index` (u32), `mana_choice`, `cost_target` | activate a mana ability; `mana_choice`: a mana symbol or `null`; `cost_target`: target reference or `null` (an additional cost object) |
| `activate_ability` | `source`, `ability_index` (u32) | activate a non-mana activated ability |
| `special_action` | `source`, `action` | a special action (Section 7.4) |

Every `source` is an object reference. `ability_index` is the 0-based index of the ability among the object's activated abilities of the same class (mana or non-mana), in Oracle text order, followed by abilities granted by other effects in timestamp order.

### 7.3 Choice kinds

`R` is an object reference and `T` a target reference; fields marked `R|null` may be `null` when no single object is the source.

In choice kinds, `source` refers to the spell or ability being cast, activated or resolving: its stack entry. The stack entry is in `observation.stack` from the moment the spell or ability is put on the stack (CR 601.2a, 602.2a, 603.3d), so a source typed `R` always exists, even when the card or permanent it came from has left.
- Where no stack entry exists (a turn-based action, a static ability, a replacement effect), `source` refers to the current visible incarnation of the source object.
- Such fields are typed `R|null`, and are `null` when that object no longer exists.

| kind | fields | meaning |
|---|---|---|
| `choose_target` | `source` R, `slot` u32, `target` T, `selected_count`, `minimum`, `maximum` (u32) | choose one target for target requirement `slot` (0-based, Oracle order) |
| `finish_target_selection` | `source` R, `slot` u32, `selected_count` u32 | stop choosing targets for a variable-count requirement |
| `choose_cost_target` | `source` R, `cost_kind`, `candidate` R, `selected_count`, `minimum`, `maximum` (u32) | pay a cost by choosing the referenced object |
| `choose_cast_method` | `source` R, `method` | how the referenced card is cast |
| `choose_spell_mode` | `source` R, `mode_index`, `mode_count`, `selected_count`, `minimum`, `maximum` (u32) | choose one mode of a modal spell or ability |
| `choose_option` | `source` R\|null, `purpose`, `option_index` u32, `option_count` u32, `option_label` string\|null | choose among an effect's printed options |
| `choose_color` | `source` R\|null, `purpose`, `color` | `color` from Section 6.10 |
| `choose_number` | `source` R\|null, `purpose`, `value`, `minimum`, `maximum` (i32) | one candidate per legal value |
| `choose_boolean` | `source` R\|null, `purpose`, `value` bool | a yes/no decision |
| `choose_name` | `source` R\|null, `purpose`, `value` string | name a card, a type or another word |
| `select_object` | `source` R\|null, `purpose`, `choice` T, `selected_count`, `minimum`, `maximum` (u32) | pick one more object or player for a non-targeted selection |
| `finish_selection` | `source` R\|null, `purpose`, `selected_count` u32 | end a variable-size selection |
| `optional_cost` | `source` R, `cost`, `pay` bool | pay or decline an optional cost |
| `choose_cost_option` | `source` R, `choice` string | choose among alternative cost payments; `choice` is an open snake_case value defined by the engine (for example `discard`, `sacrifice_land`, `decline`) |
| `optional_cast` | `card` R, `method`, `cast_it` bool | cast or decline an offered card (madness, miracle, cascade, and similar) |
| `mulligan` | `hand_size` u32, `mulligans_taken` u32, `keep` bool | keep the hand or take a mulligan |
| `order_pick` | `source` R\|null, `purpose`, `item`, `position` u32, `count` u32 | place the next item of an ordered block |
| `arrange_card` | `source` R\|null, `purpose`, `card` R, `card_index` u32, `card_count` u32, `destination` | send one looked-at card to a destination |
| `choose_replacement` | `affected` T, `event`, `replacement_source` R\|null, `replacement_index` u32, `replacement_count` u32 | choose which replacement or prevention effect applies next (CR 616.1) |
| `choose_starting_player` | `player` seat | the toss winner chooses who takes the first turn (CR 103.1) |
| `declare_attack` | `attacker` R, `defender` T\|null | declare one creature's attack, or (`null`) that it does not attack |
| `declare_block` | `blocker` R, `attacker` R\|null | declare one creature's block, or (`null`) that it does not block |
| `distribute` | `source` R\|null, `purpose`, `recipient` T, `amount` u32, `remaining` u32 | assign an amount to one recipient of a division |
| `choose_pile` | `source` R\|null, `purpose`, `pile_index` u32, `piles` (array of two arrays of R) | choose one of two piles |

`order_pick.item` is `{"object": R}` or `{"trigger": {"source": R|null, "source_name": string|null, "ability_index": u32|null, "event_objects": [R], "instance": u32, "label": string|null}}`. In a trigger item:
- `ability_index` counts the source's triggered abilities in Oracle order.
- `event_objects` lists the current visible incarnations of the objects involved in the triggering event (for example the dead creature's card, now in a graveyard), and omits objects that no longer exist.
- `instance` numbers, from 0, triggers that are otherwise identical.

Field constraints (a violation is `malformed_request`):

- `choose_target`, `choose_cost_target`, `select_object`: `minimum <= maximum`, `selected_count < maximum`.
- `choose_spell_mode`: `mode_index < mode_count`, `minimum <= maximum <= mode_count`, `selected_count < maximum`.
- `choose_option`: `option_index < option_count`.
- `choose_number`: `minimum <= value <= maximum`.
- `order_pick`: `position < count`. `arrange_card`: `card_index < card_count`.
- `choose_replacement`: `2 <= replacement_count`, `replacement_index < replacement_count`.
- `distribute`: `amount <= remaining`.
- `choose_pile`: `pile_index` is 0 or 1, and `piles` has exactly two arrays.

### 7.4 Vocabularies

Each `purpose` list ends in `other`, used for engine prompts that cannot be classified. A more specific value is used whenever it applies.

| Field | Values |
|---|---|
| `select_object.purpose`, `finish_selection.purpose` | `discard, sacrifice, exile, destroy, return_to_hand, search, reveal, put_onto_battlefield, put_into_hand, put_into_graveyard, legend_rule, tap, untap, delve, convoke, attach, keep, vote, modes, other` |
| `choose_boolean.purpose` | `may_ability, optional_trigger, may_cast, change_copy_targets, optional_replacement, reveal, other` |
| `choose_number.purpose` | `x_value, amount, life_payment, cost_repetitions, vote, other` |
| `choose_option.purpose` | `effect_option, top_or_bottom, odd_or_even, vote, other` |
| `choose_color.purpose` | `mana, protection, effect, other` |
| `choose_name.purpose` | `card_name, creature_type, card_type, land_type, basic_land_type, other` |
| `order_pick.purpose` | `triggers, library_top, library_bottom, mulligan_bottom, arrangement, other` |
| `arrange_card.purpose` | `scry, surveil, dig, look_at_top, pile_split, other` |
| `arrange_card.destination` | `top, bottom, graveyard, exile, hand, battlefield, pile_0, pile_1` |
| `distribute.purpose` | `damage, combat_damage, counters, mana, life, other` |
| `choose_pile.purpose` | `effect, other` |
| `method` (`cast_spell`, `choose_cast_method`, `optional_cast`) | `normal, alternative, flashback, escape, evoke, overload, adventure, disturb, foretell, plot, mdfc_back, split_left, split_right, fuse, prototype, morph, disguise, madness, miracle, cascade, discover, rebound, suspend, free, other` |
| `optional_cost.cost` | `kicker, buyback, entwine, conspire, casualty, bargain, gift, offspring, copy, unless_payment, additional, other` |
| `choose_cost_target.cost_kind` | `sacrifice, discard, exile, tap, untap, return_to_hand, reveal, remove_counter, other` |
| `special_action.action` | `turn_face_up, plot, foretell, suspend, unlock_door, other` |
| `choose_replacement.event` | `zone_change, damage, draw, enter_battlefield, counters, life, other` |

### 7.5 Semantics by family

**Targets.** Each target requirement (`slot`) is filled one target per decision.
- A fixed-count requirement (`minimum` equals `maximum`) is a fixed group of `maximum` decisions.
- A variable-count requirement offers `finish_target_selection` once `selected_count >= minimum`, one group per decision.
- Targets already chosen for a slot are not offered again unless the rules allow it.

**Selections.** `select_object` picks one more object or player per decision; `selected_count` counts earlier picks, and picks already made are not offered again unless the rules allow repeats.
- A fixed-count selection is a fixed group. A variable-count selection offers `finish_selection` once `selected_count >= minimum`.
- A library search always allows finding nothing (CR 701.19b): the engine sets `minimum` to 0.
- When the order of the selected objects matters afterwards, an `order_pick` block follows as its own group.

**Modes.** A modal choice picks one mode per decision. "Choose two" is a fixed group of two picks. "Choose one or more" offers `finish_selection` with `purpose: "modes"` once `minimum` is met.

**Mulligan** (London, CR 103.5).
- The pregame decision offers `keep: true`, plus `keep: false` while a further mulligan is allowed. `hand_size` is the number of cards in the hand being decided on.
- After keeping with `mulligans_taken` k > 0, the seat puts k cards from its hand on the bottom. This is an `order_pick` group with `purpose: "mulligan_bottom"`, `count` k, one item per hand card, and all k picks posed.

```text
{"kind": "mulligan", "hand_size": 7, "mulligans_taken": 1, "keep": true}
{"kind": "order_pick", "purpose": "mulligan_bottom", "source": null, "item": {"object": R}, "position": 0, "count": 1}
```

**Ordering.** An `order_pick` block places `count` items, one position per decision starting at 0. The candidates are the items not yet placed. What `position` means depends on `purpose`:
- `triggers`: position 0 is put on the stack first and resolves last (CR 603.3b).
- `library_top`, `library_bottom`, `mulligan_bottom`: the placed cards form a contiguous block, and position 0 is its card closest to the top of the library.

When the items offered are exactly the items to place, the last position is implied and not posed.

**Arrangement** (scry, surveil, dig, look at the top, splitting into piles). An arrangement of `card_count` = n cards is one fixed group of 2n - 1 decisions, whatever the choices. That is so the number of decisions does not depend on the hidden arrangement.
1. **Partition.** There are n `arrange_card` decisions, one per looked-at card, top card first. The candidates are the destinations that keep the arrangement legal; a forced destination is still posed.
2. **Ordering.** There are n - 1 `order_pick` decisions with `purpose: "arrangement"`, `count` n, and `position` 0 to n - 2.
   - They place the cards destination by destination, in the order `top, bottom, graveyard, exile, hand, battlefield, pile_0, pile_1`. The candidates of each pick are the unplaced cards of the current destination.
   - Within a library destination, earlier picks lie closer to the top of the library. Within other destinations, earlier picks come first.
   - A pick whose destination has one unplaced card is posed with that single candidate. Only the final pick of the whole arrangement (position n - 1) is implied.

A scry 2 that keeps both cards on top:

```json
{"kind": "arrange_card", "purpose": "scry", "source": {"object_id": "o-8c1d2e3f4a5b6c7d", "card_name": "Preordain", "owner_seat": "p0", "controller_seat": "p0", "zone": "stack"}, "card": {"object_id": "o-794a5cb152c9620f", "card_name": "Island", "owner_seat": "p0", "controller_seat": "p0", "zone": "library"}, "card_index": 0, "card_count": 2, "destination": "top"}
```

```text
{"kind": "arrange_card", "purpose": "scry", "source": R_preordain, "card": R_brainstorm, "card_index": 1, "card_count": 2, "destination": "top"}
{"kind": "order_pick", "purpose": "arrangement", "source": R_preordain, "item": {"object": R_brainstorm}, "position": 0, "count": 2}
```

The looked-at cards appear in `known` with `how: "looked_at"` and fresh object ids while the arrangement is decided.

**Naming.** `choose_name` values come from a public domain:
- `card_name`: the benchmark's `card_name_domain` (Section 12.2);
- `creature_type`, `land_type`, `basic_land_type`: normalized subtypes of that kind;
- `card_type`: the card types of Section 6.10.

A card-name domain is never derived from information hidden from the seat. Colors use `choose_color`. Numbers use `choose_number`.

```text
{"kind": "choose_name", "purpose": "card_name", "source": R, "value": "Lightning Bolt"}
{"kind": "choose_name", "purpose": "creature_type", "source": R, "value": "faerie"}
```

**Replacement order.** When two or more replacement or prevention effects apply to one event, the affected player (or the controller of the affected object) chooses one with `choose_replacement`. The decision is posed again while two or more still apply. An optional replacement then asks `choose_boolean` with `purpose: "optional_replacement"`.

**Starting player.** Posed only when the rules say `toss_winner_chooses` (Section 12.2): the toss winner gets one candidate per seat.

**Numbers and X.** For X, `purpose` is `x_value`, `source` is the spell or ability, and the range is bounded by what can be paid. Repetitions of an optional cost (multikicker, replicate) follow the `optional_cost` decision as `choose_number` with `purpose: "cost_repetitions"`.

```text
{"kind": "choose_number", "purpose": "x_value", "source": R, "value": 2, "minimum": 0, "maximum": 4}
```

**Costs.**
- `optional_cost` asks whether to pay an optional cost. "Counter unless its controller pays" is `cost: "unless_payment"`, asked of the payer.
- `choose_cost_option` chooses among alternative ways to pay a cost.
- `choose_cost_target` pays a cost by choosing objects, one per decision.
- A card castable in several ways from its zone is offered as `cast_spell` with `method` set, or as `cast_spell` with `method: null` followed by `choose_cast_method`.
- A mana cost asked during resolution may be paid by activating mana abilities offered in the same decision (Section 7.1).

```text
{"kind": "optional_cost", "source": R, "cost": "kicker", "pay": true}
{"kind": "optional_cast", "card": R, "method": "madness", "cast_it": false}
```

**Combat.**
- Attackers are declared with one `declare_attack` decision per creature that can attack, in a deterministic order, as one group. `defender` is each legal player, planeswalker or battle. `null` means the creature does not attack, and is not offered for a creature that must attack.
- Blockers are declared with one `declare_block` decision per potential blocker, as one group. A creature that can block additional attackers gets one decision per additional block. `attacker` candidates are each attacker it may still legally block, plus `null`, and every candidate keeps the declaration completable (menace, required blocks).
- Combat damage among several blockers, or with trample, is assigned with `distribute` (`purpose: "combat_damage"`) unless the engine declares a default (Section 7.6).

**Distribution.** There is one `distribute` decision per recipient, in the order the recipients were chosen, as one group. `remaining` is the amount still to assign, including this recipient's. Candidates are the legal amounts that leave enough for later recipients' minimums.

**Piles.** Splitting cards into two piles is an arrangement with destinations `pile_0` and `pile_1`. Choosing a pile uses `choose_pile`.

### 7.6 Engine defaults

An engine may answer these decisions itself, for both seats, only under a declared rule:

| Decision | Declared where | Rule |
|---|---|---|
| mulligan | `reset.rules.mulligan: "none"` (Section 12.2) | both seats keep their opening hands |
| starting player | `reset.rules.starting_player: "host_assigned"` | the seat named by `starting_seat` takes the first turn |
| trigger order | `hello_ok.engine_defaults.trigger_order: "engine_order"` | APNAP, then the engine's timestamp order |
| replacement order | `hello_ok.engine_defaults.replacement_order: "engine_order"` | the engine's order |
| combat damage assignment | `hello_ok.engine_defaults.combat_damage_assignment: "engine_order"` | lethal damage to each blocker in the engine's order, the rest to the last blocker, or to the defender with trample |
| mana payment | `hello_ok.engine_defaults.mana_payment: "engine_autopay"` | the engine pays costs from the seat's sources |

- An `engine_defaults` entry of `null` means the decision is offered through its kind. If that kind is also absent from `decision_kinds`, the decision is never posed, and a deck that needs it fails `unsupported_deck`.
- Every other decision must be offered when it arises: targets, selections, modes, arrangement, naming, numbers and X, costs, attacks, blocks, distributions other than combat damage, and piles.

Note: auto-payment is allowed because several engines pay costs through their own planners. Benchmarks show every default in force on their page, since defaults change play strength.

`engine_autopay` governs paying a cost. An engine may also offer ordinary priority activations through the existing `activate_mana_ability` kind when it declares that kind in `decision_kinds`. Such a decision has `context.kind: "priority"` and `context.purpose: null`; the seat may float mana before taking another priority action. This does not expose payment choices answered by the declared default. The `mana_payment` exception in Section 7.1 applies when a mana activation appears in a **choice** decision. `activate_ability` continues to mean a non-mana ability.

### 7.7 Reserved kinds

These kinds are specified for a later minor version. v2.0 engines do not emit them.

| kind | fields | meaning |
|---|---|---|
| `pay_mana` | `paying_for` R, `source` R\|null, `ability_index` u32\|null, `mana_choice`, `cost_target` T\|null | pay part of a cost with the referenced source's mana ability, or (`source` `null`) with floating mana of `mana_choice` |
| `narrow_name` | `source` R\|null, `purpose`, `prefix` string | restrict a name domain larger than 4096 to names starting with `prefix` |
| `narrow_number` | `source` R\|null, `purpose`, `minimum`, `maximum` (i32) | restrict a number domain larger than 4096 to this range |

- An engine that asks for payment during casting poses `pay_mana` until the cost is paid.
- Narrowing decisions offer disjoint prefixes or ranges covering the remaining domain. They repeat, one group per decision, until the domain fits within 4096; then `choose_name` or `choose_number` follows.

## 8. Decision groups (substeps)

An engine that decomposes one physical game decision into several wire decisions marks them with `group` in `seat_decision`.

- **Per seat.** `group_id` counts that seat's groups: it starts at 0 and advances by exactly 1 after each completed or abandoned group of that seat.
- **Fixed size.** Within a group, `substep_index` runs `0..substep_count-1`, and `substep_count` is fixed for the whole group and known at its first substep.
- **What forms a group.** Multi-substep groups are fixed-size decompositions only:
  - attack and block declarations;
  - fixed-count targets and fixed-count selections;
  - fixed-count modes;
  - arrangements (2n - 1 decisions);
  - order blocks, including the mulligan bottom block;
  - distributions.

  A variable-length sequence (targets or selections ended by a finish candidate) is one group per decision.
- **Posing.** Every substep of a group is posed, even with a single candidate. The only exception is the implied last position of an order block (Section 7.5).
- **Exclusivity.** While a group is partial, the engine poses no decision to the other seat.
- **Interruption.** Only a `halted` terminal, a host adjudication (Section 11.5), or a rewind may interrupt a partial group. An interrupted or rewound group does not count toward `decision_count`.
- **Rewind.** An engine that declares `rewind: true` in `hello_ok` may find, at any decision after a priority action and before that seat's next priority decision, that the action cannot be completed (for example a cast whose final payment fails). It then:
  - undoes everything since that action;
  - re-poses the priority decision without the failing candidate, with `context.rewind: true`.

  Every group started or completed since the action is abandoned: it does not count toward `decision_count`, and its `group_id` is not reused. `seat_step` and the binding `step` keep counting the answered decisions.
- **No decomposition.** An engine without decomposition emits `substep_index: 0, substep_count: 1`, with `group_id` equal to that seat's physical decision count.

## 9. Environment role messages

### 9.1 `hello`

Request: `{request_type: "hello", protocol, request_id, protocol_minor}`.

Response `hello_ok` (the example is illustrative):

```json
{
  "response_type": "hello_ok",
  "protocol": "spellbench/v2",
  "request_id": "h-1",
  "protocol_minor": 0,
  "engine": {"name": "mtg-kernel", "version": "0.0.5", "source_revision": null,
             "rules_snapshot_id": "opaque engine string", "card_pool_identity": "opaque engine string"},
  "formats": ["pauper-bo1"],
  "deck_sources": ["catalog"],
  "catalog": [
    {"catalog_id": "Burn", "name": "Burn",
     "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]}
  ],
  "rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]},
  "observation": {"poison": false, "player_counters": false, "designations": true, "player_progress": false,
                  "day_night": false, "passed_seats": true, "pending_triggers": true, "keywords": true,
                  "full_name": false, "exiled_by": true, "stack_text": false, "permanent_details": true, "known_cards": true},
  "decision_kinds": ["pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability",
                     "special_action", "choose_target", "finish_target_selection", "choose_cost_target",
                     "choose_cast_method", "choose_spell_mode", "choose_option", "choose_color", "choose_number",
                     "choose_boolean", "select_object", "finish_selection", "optional_cost", "choose_cost_option",
                     "optional_cast", "order_pick", "arrange_card", "declare_attack", "declare_block"],
  "engine_defaults": {"trigger_order": null, "replacement_order": null,
                      "combat_damage_assignment": "engine_order", "mana_payment": null},
  "rewind": false,
  "fairness": {"noninterference_probe": false},
  "extensions": [{"name": "x_kernel_v5", "native_ids": true}]
}
```

| Field | Rule |
|---|---|
| `protocol_minor` | the negotiated minor version, no greater than the request's (Section 4.2) |
| `engine` | `name`, `version` (nonempty strings), `source_revision` (string or null), `rules_snapshot_id`, `card_pool_identity` (opaque nonempty strings; equality between two engines is meaningful only if they agree on the naming scheme) |
| `formats` | nonempty array of format ids the engine plays, for example `pauper-bo1` |
| `deck_sources` | nonempty subset of `catalog` (the engine's named decks) and `decklist` (decks given as data) |
| `catalog` | every catalog deck: `catalog_id`, `name`, and `decklist` (rows `{"name", "count"}` with Oracle names and count at least 1); empty when `deck_sources` lacks `catalog`. The host computes each `deck_id`. |
| `rules_supported` | `mulligan`: nonempty subset of `london, none`; `starting_player`: nonempty subset of `host_assigned, toss_winner_chooses` |
| `observation` | exactly the thirteen flags of Section 6.9 |
| `decision_kinds` | every v2.0 kind the engine may emit; must include `pass`, `play_land`, `cast_spell`, `declare_attack` and `declare_block` |
| `engine_defaults` | exactly `trigger_order`, `replacement_order`, `combat_damage_assignment` (each `null` or `"engine_order"`) and `mana_payment` (`null` or `"engine_autopay"`) (Section 7.6) |
| `rewind` | whether the engine may abandon a group and re-pose a priority decision (Section 8) |
| `fairness` | `noninterference_probe`: whether the engine implements Section 9.7 (reserved) |
| `extensions` | the `x_` keys the engine can emit, each `{"name", "native_ids"}`; `native_ids` is true when the payload carries engine-native object identities (Section 14) |

### 9.2 `reset`

The example uses the test-vector run secret of Section 16 (game index 0).

```json
{
  "request_type": "reset",
  "protocol": "spellbench/v2",
  "request_id": "h-2",
  "game_id": "g-f67d7fe78c792984",
  "format": "pauper-bo1",
  "seats": [
    {"seat": "p0", "deck": {"deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2", "catalog_id": "Burn"}},
    {"seat": "p1", "deck": {"deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2", "catalog_id": "Burn"}}
  ],
  "rules": {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
            "card_name_domain": {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]},
            "extensions": [], "probe": false},
  "game_secret": "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e",
  "max_decisions": 10000,
  "max_steps": 100000
}
```

- **`game_id`** is the opaque id of Section 11.6. It is unique per engine process; reusing one is `malformed_request`.
- **`format`** must appear in `hello_ok.formats`, else `unsupported_format`.
- **`seats`** lists exactly `p0` then `p1`, else `malformed_request`.
- **Decks.** A deck is exactly `{deck_id, catalog_id}` or `{deck_id, decklist}`. Any other shape is `malformed_request`.
  - `deck_id` is computed by the host. An engine may check it and fail `deck_id_mismatch`, but is not required to.
  - A source missing from `deck_sources`, an unknown `catalog_id`, or cards the engine cannot play (or whose decisions it cannot offer) are `unsupported_deck`. Engines never substitute a deck.
- **`rules`** is the information-rules object of Section 12.2, which the host also sends to both agents. `rules.extensions` is an array of the extension names the engine may emit in this game; it emits no others. A value outside `rules_supported`, an extension not in `hello_ok.extensions`, or `probe: true` from an engine without the probe is `unsupported_rule`.
- **`game_secret`** is 64 lowercase hex characters (256 bits) and seeds all of the game's randomness and object ids (Section 11.6).
- **Caps.** The host sets both caps. `max_decisions` caps physical decisions (groups) and `max_steps` caps individual decisions. An engine that cannot count groups applies `max_steps` to both. Reaching either cap ends the game as `truncated`.
- **`reset` while a game is active** fails `game_already_active`.

Response: the first `decision` (Section 9.3), or `terminal` for a degenerate game, or `error`.

### 9.3 `decision` (response)

```json
{
  "response_type": "decision",
  "protocol": "spellbench/v2",
  "request_id": "h-7",
  "game_id": "g-f67d7fe78c792984",
  "step": 14,
  "seat_decision": {
    "acting_seat": "p0",
    "seat_step": 6,
    "group": {"group_id": 5, "substep_index": 0, "substep_count": 1},
    "context": {"kind": "priority", "source": null, "purpose": null, "text": null, "rewind": false},
    "observation": {"viewer": "p0", "...": "the full observation of Section 6"},
    "candidates": [
      {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Pass priority"},
      {"candidate_id": 1, "semantic": {"kind": "play_land", "source": {"object_id": "o-2b8e4dafc6031912", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}, "face": 0}, "display_text": "Play Mountain"},
      {"candidate_id": 2, "semantic": {"kind": "cast_spell", "source": {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}, "method": "normal"}, "display_text": "Cast Lightning Bolt"}
    ],
    "extensions": {}
  },
  "provenance": {"engine_name": "mtg-kernel", "engine_version": "0.0.5",
                 "rules_snapshot_id": "opaque engine string", "card_pool_identity": "opaque engine string"}
}
```

- **`step`** (host and engine binding only, never forwarded) is 0 for the decision returned by `reset` and increases by exactly 1 per answered decision of either seat.
- **`seat_decision`** is validated by the host and forwarded to the agent as canonical JSON:
  - `acting_seat`: the seat that decides.
  - `seat_step`: 0 for this seat's first decision, increasing by exactly 1 per answered decision of this seat.
  - `group`: Section 8.
  - `context`: `{kind, source, purpose, text, rewind}`.
    - `kind` is `priority` or `choice` (Section 7.1).
    - `source` (object reference or null) and `purpose` (string or null) repeat the candidates' shared source and purpose when there is one.
    - `text` is optional human-facing prompt text.
    - `rewind` is true only on a re-posed priority decision (Section 8).
  - `observation`: Section 6.
  - `candidates`: nonempty, dense, ordered, at most 4096 (Section 7).
  - `extensions`: Section 14.
- **`provenance`** repeats the hello engine identity. Hosts pin the first value per process and treat drift as an engine contract failure.

### 9.4 `step`

```json
{
  "request_type": "step",
  "protocol": "spellbench/v2",
  "request_id": "h-8",
  "game_id": "g-f67d7fe78c792984",
  "expected_step": 14,
  "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
}
```

The host always supplies `semantic_echo`, copied from the candidate it forwarded. The engine validates in this order:
1. `step_before_reset`: no game has been reset.
2. `game_id_mismatch`.
3. `game_already_terminal`.
4. `expected_step_mismatch`: `expected_step` is not the pending decision's `step`.
5. `candidate_id_out_of_range`.
6. `semantic_echo_mismatch`: `semantic_echo` is not equal, field for field, to that candidate's `semantic`.

This double binding is the protocol's stale-candidate guard.

Response: the next `decision`, or `terminal`.

### 9.5 `terminal` (response)

```json
{
  "response_type": "terminal",
  "protocol": "spellbench/v2",
  "request_id": "h-9",
  "game_id": "g-f67d7fe78c792984",
  "outcome": "p0_win",
  "classification": "natural",
  "winner": "p0",
  "reason": "p1_life_zero",
  "step_count": 412,
  "decision_count": 388,
  "provenance": {"engine_name": "mtg-kernel", "engine_version": "0.0.5",
                 "rules_snapshot_id": "opaque engine string", "card_pool_identity": "opaque engine string"}
}
```

- **Outcome and classification.** `outcome` is `p0_win | p1_win | draw | truncated | halted`, and `classification` is `natural | truncated | halted`.
  - A natural terminal pairs outcome and winner as `p0_win`/`p0`, `p1_win`/`p1`, `draw`/`null`.
  - A truncated or halted terminal has the matching outcome and `winner: null`.
  - Engines never emit the host-only classification `forfeit` (Section 11.5).
- **Counts.** `step_count` counts the game's answered decisions (both seats). `decision_count` counts its completed groups (both seats). These stay between the host and the engine (see Section 10.4).
- **`reason`** is a short nonempty phrase (for example `p1_life_zero`) that names no hidden card.
- **Unrepresentable states.** An engine that meets a state it cannot represent never emits a partial decision: it ends the game `halted`, with a reason beginning `engine_contract_failure:`.

### 9.6 `validate_deck` (optional)

Request: `{request_type: "validate_deck", protocol, request_id, format, deck}`, where `deck` is `{"catalog_id": ...}` or `{"decklist": [...]}`.

Response: `{"response_type": "deck_ok", "protocol", "request_id"}`, or `error` with `unsupported_format` or `unsupported_deck` (the message names the unsupported cards).

Engines that do not implement this request answer `unsupported_request`. It never affects a game in progress.

### 9.7 `probe_resample` (reserved)

A test-only request.
- An engine without the probe answers `unsupported_request`.
- An engine with the probe answers `probe_refused` unless the game was reset with `rules.probe: true`, which hosts never set in rated runs.

Request: `{request_type: "probe_resample", protocol, request_id, game_id, samples: u32}`.

For the pending decision, the engine does the following, `samples` times:
1. Fork the game.
2. Redraw everything hidden from the acting seat, consistently with that seat's knowledge (Section 6.7):
   - the other seat's unknown hand cards, from the unseen part of its list;
   - both libraries, shuffled below known positions;
   - the other seat's list itself when `opponent_decklist` is `hidden`, from the benchmark's deck pool.
3. Rebuild the acting seat's decision.

Response: `{"response_type": "probe_result", "protocol", "request_id", "game_id", "worlds": [<seat_decision>, ...]}`.

The host compares the canonical digest of each world's whole `seat_decision` with the real one's, and all must be equal. The probe does not change the real game.

### 9.8 `error` (response)

`{response_type: "error", protocol, request_id, error: {code, message}}`. `message` is human-facing only. `code` is closed:

| Code | Meaning |
|---|---|
| `malformed_json` | invalid JSON, duplicate keys, numbers with a fraction or an exponent, integers outside the bound, nesting over 64 levels, invalid UTF-8, an unpaired surrogate escape, or a line over 8 MiB |
| `malformed_request` | a non-object top level; missing, mistyped or unknown fields; a bad `request_type`, seat, deck shape, kind, vocabulary value or constraint; a reused `game_id` |
| `protocol_mismatch` | a string `protocol` other than `spellbench/v2` |
| `request_id_reuse_mismatch` | a cached `request_id` with a different payload |
| `step_before_reset` | `step` or `probe_resample` before any `reset` |
| `game_already_active` | `reset` while a game is active |
| `game_id_mismatch` | a request naming another game |
| `expected_step_mismatch` | `expected_step` is not the pending decision's `step` |
| `candidate_id_out_of_range` | `candidate_id` outside the current list |
| `semantic_echo_mismatch` | the echo differs from the candidate's `semantic` |
| `unsupported_format` | a format not in `hello_ok.formats` |
| `unsupported_deck` | a deck the engine cannot play (Section 9.2) |
| `deck_id_mismatch` | optional engine check: `deck_id` does not match the list |
| `unsupported_rule` | a `rules` value the engine does not support |
| `unsupported_request` | an optional or reserved request the engine does not implement |
| `probe_refused` | `probe_resample` in a game not reset with `rules.probe: true` |
| `game_already_terminal` | a request after the game's terminal |

## 10. Agent role messages

Agents are lenient readers (Section 4.2). The host reads agent responses leniently too: it ignores unknown fields and `x_` keys, and needs only the fields marked required below.

### 10.1 `hello`

Request `{request_type: "hello", protocol, request_id, protocol_minor}`; response `hello_ok`:

```json
{
  "response_type": "hello_ok",
  "protocol": "spellbench/v2",
  "request_id": "r-0",
  "bot": {"name": "uniform", "version": "2.0.0"},
  "requires": {"observation": [], "extensions": []},
  "extensions_accepted": []
}
```

- **Required:** `response_type`, `protocol`, `request_id`, and `bot` (a nonempty `name` and `version`).
- **Optional, empty by default:**
  - `requires.observation`: optional observation flags (Section 6.9) the bot cannot play without;
  - `requires.extensions`: extension names the bot cannot play without;
  - `extensions_accepted`: extension names the bot reads (informative).

### 10.2 `game_start`

```json
{
  "request_type": "game_start",
  "protocol": "spellbench/v2",
  "request_id": "r-1",
  "game_id": "g-f67d7fe78c792984",
  "seat": "p0",
  "format": "pauper-bo1",
  "own_deck": {"deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2", "name": "Burn",
               "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]},
  "opponent_deck": {"deck_id": "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2", "name": "Burn",
                    "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]},
  "rules": {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
            "card_name_domain": {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]},
            "extensions": [], "probe": false},
  "engine": {"name": "mtg-kernel", "version": "0.0.5", "source_revision": null,
             "rules_snapshot_id": "opaque engine string", "card_pool_identity": "opaque engine string"},
  "engine_profile": {"rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]},
                     "observation": {"poison": false, "player_counters": false, "designations": true, "player_progress": false,
                                     "day_night": false, "passed_seats": true, "pending_triggers": true, "keywords": true,
                                     "full_name": false, "exiled_by": true, "stack_text": false, "permanent_details": true, "known_cards": true},
                     "decision_kinds": ["pass", "play_land", "cast_spell", "declare_attack", "declare_block"],
                     "engine_defaults": {"trigger_order": null, "replacement_order": null,
                                         "combat_damage_assignment": "engine_order", "mana_payment": null},
                     "rewind": false,
                     "fairness": {"noninterference_probe": false},
                     "extensions": [{"name": "x_kernel_v5", "native_ids": true}]},
  "time_control": {"startup_ms": 120000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
                   "max_decision_ms": 60000, "engine_step_ms": 120000},
  "limits": {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 500,
             "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999},
  "resources": {"cpus": 1, "memory_mb": 4096, "gpu": false, "engine_cpus": 1},
  "agent_seed": 8103969398531465
}
```

- **`game_id`** is opaque (Section 11.6).
- **Decks.** `own_deck` always carries the seat's full list: `{deck_id, name, decklist}`. `opponent_deck` has the same shape when `rules.opponent_decklist` is `visible`, and is `null` when it is `hidden`.
- **`rules`** is the same object the engine received in `reset`.
- **`engine`** is the engine identity.
- **`engine_profile`** copies `rules_supported`, `observation`, `decision_kinds`, `engine_defaults`, `rewind`, `fairness` and `extensions` from the engine's `hello_ok`, so a bot knows which optional fields it will receive. (The example abridges `decision_kinds`.)
- **`time_control`, `limits` and `resources`:** Section 11.4.
- **`agent_seed`:** Section 11.6.

Response: `{response_type: "ack", protocol, request_id}`.

### 10.3 `choose`

```json
{
  "request_type": "choose",
  "protocol": "spellbench/v2",
  "request_id": "r-7",
  "game_id": "g-f67d7fe78c792984",
  "decision": {"acting_seat": "p0", "seat_step": 6, "...": "the validated seat_decision, as canonical JSON"},
  "clock": {"remaining_ms": 540000, "max_decision_ms": 60000}
}
```

`clock.remaining_ms` is the seat's remaining bank when the request is sent. `max_decision_ms` caps this decision.

Response `choice`:

```json
{
  "response_type": "choice",
  "protocol": "spellbench/v2",
  "request_id": "r-7",
  "selection": {"candidate_id": 0}
}
```

- **Required:** `response_type`, `protocol`, `request_id`, and `selection.candidate_id`.
- **Optional:** `selection.seat_step` and `selection.semantic_echo`. When present, they must equal the decision's `seat_step` and the chosen candidate's `semantic`, or the answer is an invalid selection.
- **Ignored:** extra fields and `x_` keys anywhere in the response. They are never a forfeit.

### 10.4 `game_over`

Request: `{request_type: "game_over", protocol, request_id, game_id, terminal: {outcome, classification, winner, reason, seat_step_count}}`.
- `seat_step_count` counts this seat's answered decisions. The game's global counts are not sent to agents.
- `classification` may also be `forfeit` (Section 11.5).

Response: `ack`. After `game_over`, the agent process serves no further requests for that game.

### 10.5 Agent error codes

An agent answers a request it cannot serve with an `error` response carrying one of these codes. The host treats any error answering `choose` as the forfeit cause `agent_error`, after which no decision is pending.

| Code | Meaning |
|---|---|
| `malformed_json` | the request line is not valid JSON |
| `malformed_request` | the request lacks something the agent needs |
| `protocol_mismatch` | the `protocol` is not `spellbench/v2` |
| `unknown_game` | a `choose` or `game_over` names a game the agent is not serving |
| `game_already_active` | a `game_start` arrives while another game is active |
| `decision_pending` | another request arrives while a `choose` is unanswered (a host bug, since hosts never pipeline or retransmit to agents) |
| `internal_error` | the agent failed internally |

### 10.6 The minimal agent

A conforming agent needs only this:

- `hello`: answer `hello_ok` with a bot name and version.
- `game_start`: answer `ack`.
- `choose`: answer `choice` with one candidate's `candidate_id`. A bot that always picks candidate 0 (which is `pass` whenever passing is legal), or a uniformly random candidate seeded from `agent_seed`, is conforming.
- `game_over`: answer `ack`.

Everything else is optional: echoing, error responses, and reading the observation, the context, the extensions or the clock. The host validates every seat decision before forwarding it (Section 11.3), so an agent may rely on it being well formed.

The reference implementation of both roles, the host and the builtin bots is `python/spellbench` (to be written for v2). This document does not prescribe its internals.

## 11. Host

### 11.1 Preflight

Before any game, the host does the following:
1. Publish the run's commitment (Section 11.6).
2. Start the engine and exchange `hello`, then start or check each agent entry and exchange `hello`.
3. Check each agent's `requires` against the engine's `hello_ok` and the benchmark's enabled extensions. An unmet requirement refuses that entry as a configuration error, not a forfeit.
4. Resolve every benchmark deck to its list and `deck_id` (catalog decks through `hello_ok.catalog`).
5. Check the benchmark's rules against `rules_supported`, and check that each per-seat per-game cap is strictly below half of the matching game cap.

A configuration error stops the run before any game.

### 11.2 Routing and forwarding

For each engine `decision`:
1. Validate `seat_decision` (Section 11.3).
2. Send `choose` to the agent holding `acting_seat`, with the canonical re-serialization of the validated `seat_decision`.
3. Check the `choice`: `candidate_id` is in range, and the optional echoes match.
4. Send `step` to the engine with `expected_step` set to the decision's `step` and `semantic_echo` copied from the chosen candidate.

The host forwards nothing else from the engine: not engine stderr, not the other seat's messages, and nothing derived from them. Every `request_id` and `game_id` an agent receives encodes nothing beyond that agent's own messages (Sections 4.1 and 11.6). After a terminal or an adjudication, the host sends `game_over` to both agents.

### 11.3 Live validation

The host validates every `seat_decision` before forwarding it:

| Rule | Check |
|---|---|
| V1 schema | every field, type, vocabulary value and kind constraint of Sections 6 and 7; candidates nonempty, dense, at most 4096, pairwise-distinct semantics, `pass` at 0 when present; no reserved kind; card names in NFC; `choose_name` values within their domain |
| V2 seat | `observation.viewer` equals `acting_seat` |
| V3 counters | `seat_step` is contiguous per seat; `group` continues or advances per Section 8; no decision for the other seat while a group is partial; a partial group ends early only when that seat's next decision is a rewind |
| V4 references | every non-null object reference (candidates, context, attachments, attack targets, blocked attackers, stack sources and targets, pending triggers, `exiled_by`) equals the observation record with that id; ids are unique within the observation |
| V5 hidden zones | the other seat's `hand` is `null`; the viewer's `hand` has `hand_count` records; no zone array holds a `library` object; `known` entries obey the shape, count and order rules of Section 6.7; candidates that reference hidden-zone cards are in `(card_name, object_id)` order |
| V6 face-down | a face-down object on the battlefield or the stack not controlled by the viewer has `card_name` and `full_name` `null` |
| V7 id freshness | an id never appears with two zones in this seat's stream, and never returns after leaving it |
| V8 declarations | kinds are in `decision_kinds`; an optional field is non-null only if its flag is true, and with the flag true it is `null` only in the cases Section 6.9 lists; extension keys are in `rules.extensions` |
| V9 context | `context.kind` matches the candidate family; `activate_mana_ability` appears in a choice decision only with `context.purpose` `mana_payment` and `optional_cost` candidates (Section 7.1) |
| V10 provenance | the engine identity has not drifted |

A violation:
- halts that game as an engine halt (`halted`, reason `host_validator:<rule>`), with `game_over` to both agents;
- discards the engine process's game, and the host restarts the engine before any further game;
- marks the run invalid. An invalid run is published as invalid (Section 11.6), never as rated, and the host may stop it at once.

The ledger records whose selection preceded the violation (Section 11.5).

The run manifest records the verdict:

```json
"validator": {"version": "spellbench-live-validator/2.0", "verdict": "pass", "decisions_checked": 181234, "violations": []}
```

The validator checks what it can see. It cannot tell whether a `known` entry, a text or an extension payload is faithful to hidden state; that is what the reserved probe and adapter audits are for.

Published runs do not store per-decision transcripts: a full board on every decision would be about 1 GB per run. The per-game digest (Section 11.8) makes reruns checkable instead. Hosts may write local debug transcripts, which are never published.

### 11.4 Clocks, limits and resources

Each benchmark declares:

```json
"time_control": {"startup_ms": 300000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
                 "max_decision_ms": 60000, "engine_step_ms": 120000},
"limits": {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 500,
           "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999},
"resources": {"cpus": 4, "memory_mb": 16384, "gpu": false, "engine_cpus": 1}
```

- **`startup_ms`** bounds process start to `hello_ok`, which covers model loading. A failure at preflight is a configuration error; during a run it is a forfeit.
- **`game_start_ms`** bounds the `ack` to `game_start`.
- **The clock.** Each seat starts a game with `bank_ms`. A decision's time is the wall time from sending `choose` to receiving the complete `choice` line. It is subtracted from the bank, then `increment_ms` is added. A decision that exceeds `max_decision_ms` or the remaining bank is a forfeit (`timeout`).
- **`engine_step_ms`** bounds each engine response. Exceeding it halts the game (engine fault).
- **`max_decisions` and `max_steps`** are the engine's caps (Section 9.2).
- **`max_seat_decisions_per_turn`** caps a seat's answered decisions in one turn (by `observation.turn`).
- **`max_seat_decisions_per_game` and `max_seat_steps_per_game`** cap a seat's completed groups and answered decisions over the whole game. Each is strictly below half of the matching game cap (`max_decisions`, `max_steps`). Two seats within their caps therefore never jointly reach a game cap, so a losing seat cannot run a game into an unrated truncation. Normal games stay far below all of these caps.
- **Stalling.** When a seat reaches one of these caps, the host ends the game. It counts each seat's real choices (non-pass selections among two or more candidates) over a trailing window: the last 250 decisions answered by either seat, taken together, not the whole turn or game.
  - If either seat made a real choice in the window, the seat with more real choices in the window forfeits with cause `stalling`. On a tie, the seat that reached the cap forfeits.
  - Otherwise the recent play was a loop of mandatory actions, and the host records a draw with reason `mandatory_loop` (CR 104.4b).
  - A loop that fires the other seat's "may" triggers makes that seat's answers count as real choices too.
- **`resources`** declares the cores, memory and GPU of each agent (`cpus`, `memory_mb`, `gpu`) and the engine's cores (`engine_cpus`). The host runs games in parallel only while the declared cores of every running game, agents and engine, are free. Enforcement beyond this declaration (container limits) is reserved.
- **Enforcement** is the host's. The protocol only declares budgets.

A game reproduces exactly only when the bots do not depend on wall time. Bots should use fixed search budgets (simulations, not seconds) seeded from `agent_seed`.

### 11.5 Adjudication and rating admissibility

- **Forfeit.** A seat loses by forfeit for any of these causes:
  - `timeout`;
  - `stalling`;
  - `malformed_response` (unparseable, or missing a required field);
  - `invalid_selection` (an out-of-range `candidate_id`, or an echo that does not match);
  - `agent_error`;
  - `transport_error`.
- **Forfeit terminal.** The host records `outcome` as the other seat's win, `classification` `forfeit`, `winner` the other seat, and `reason` `forfeit:<cause>`. It sends that terminal in `game_over` to the agents.
- **Engine halt.** An engine error, an engine timeout, a live-validation violation, or provenance drift is recorded as `halted`.
- **Mandatory-loop draw.** A draw the host records at a cap (Section 11.4) has outcome `draw`, classification `natural`, `winner` `null` and reason `mandatory_loop`.
- **Rated games.** `natural` terminals (`p0_win`, `p1_win`, `draw`) and `forfeit` games enter ratings. `truncated` and `halted` games are recorded and excluded.
- **Attribution.**
  - For every halted or truncated game, the ledger records `last_selection`: the seat and entry whose selection immediately preceded the halt or truncation, or `null`.
  - The benchmark publishes per-entry halt and truncation rates.
  - A benchmark may quarantine an entry whose selections repeatedly precede engine halts or validator violations, and the manifest records every quarantine.

### 11.6 Secrets

Constructions (all HMAC-SHA256 keys are raw bytes; `decimal(i)` is the base-10 ASCII form of i without leading zeros):

```
run_secret        32 bytes from a cryptographically secure generator, fresh for each run
commitment        lowercase hex of SHA-256(run_secret)
game index i      the 0-based position of the game in the run's schedule, as recorded in the ledger
game_secret(i)    HMAC-SHA256(key = run_secret, message = ASCII "spellbench/v2/game:" + decimal(i))
game_id(i)        "g-" + lowercase hex of the first 8 bytes of
                  HMAC-SHA256(key = run_secret, message = ASCII "spellbench/v2/game-id:" + decimal(i))
agent_seed(i, s)  the first 8 bytes of HMAC-SHA256(key = run_secret,
                  message = ASCII "spellbench/v2/agent-seed:" + decimal(i) + ":" + s),
                  read as a big-endian integer and masked to its low 53 bits
```

- **Commitment first.** Before the first game, the host publishes the commitment, with the benchmark id and the run label.
  - It publishes it as a pushed commit to the benchmark's public repository, together with a third-party timestamp: for example a comment on a hosted issue, a signed release, or an OpenTimestamps proof. A commit date alone is set by its author and proves nothing.
  - A run whose commitment was not provably public before its first game is never rated.
- **Every committed run is published,** including aborted and invalid runs, with its status and its revealed `run_secret`. Anyone can then recompute every game secret, id and agent seed, and rerun the schedule.
- **One secret per game.** `reset.game_secret` is the lowercase hex of `game_secret(i)`, and no two games share a secret.
  - The two games of a seat-swapped pair have independent secrets, so the arena gives up common random numbers for fairness.
  - Ratings stay paired over the two games of each pair.
  - Note: a shared seed would let a bot that played one game of a pair know the other game's hidden cards.
- **Opaque ids.** `game_id(i)` is the only game id the engine and the agents see; it encodes nothing about the schedule.
- **Engine randomness.** Engines derive every random stream (each shuffle, each random selection, each coin flip) and their object ids (Section 5.3) from the game secret.
  - Streams are separated by seat and purpose, and each is seeded with at least 64 bits.
  - No single stream feeds both seats' hidden zones.
  - No generator with less than 64 bits of state (for example `java.util.Random`, 48 bits) is used for hidden randomness.
  - Recommended stream seed: HMAC-SHA256(key = game_secret, message = ASCII `"spellbench/v2/rng:<seat or shared>:<purpose>:<n>"`).
- **Nothing reaches agents.** Agents never receive the run secret, a game secret, or a value computed from a game secret. `agent_seed` depends only on the run secret and the game index, and a game's secrets are revealed only after the run.

### 11.7 Isolation

- **Verified entries.**
  - Each game gets a fresh sandbox for the agent. No writable state outlives the game or is shared with another game, including games running at the same time.
  - The sandbox has no network access and no access to the engine process, its files, or the host's secrets.
  - A bot's only input is its own seat's messages in that game.
- **Self-reported runs** (bots run by their authors) cannot claim these guarantees, and are labelled self-reported.
- **Remote seats.** A host may play a seat through a relay to a bot on its author's own machine. The relay forwards only that seat's agent messages, and the engine, the secrets and the validator stay with the host. The seat's clock includes the network, and a lost connection is a forfeit. A run with a remote seat is self-reported. The reference relay and its handshake are in `docs/remote-seats.md`.

### 11.8 Game digest

Each ledger row carries `game_digest`, a SHA-256 chain over the game's engine traffic, where `||` is byte concatenation and `d` is 32 bytes:

```
d = SHA-256(ASCII "spellbench/v2/game-digest" || canonical(reset request minus request_id))
for each distinct engine response to this game, and each distinct step request, in order
(a retransmitted request and its cached response are chained once):
    d = SHA-256(d || canonical(message minus request_id))
if the host adjudicates the game (forfeit, halt, or mandatory-loop draw):
    d = SHA-256(d || canonical({"adjudication": {"classification", "outcome", "reason", "winner"}}))
game_digest = "sha256:" + lowercase hex of d
```

The adjudication record is appended for every ending the host records itself: forfeits, host-detected halts, and mandatory-loop draws (Section 11.5). The chain covers the engine's responses and the selections. It excludes agent traffic, so the clock and other wall-clock values never enter it. After the run secret is revealed, a rerun with the same engine, bots and selections reproduces every digest.

## 12. Decks and information rules

### 12.1 Decks

- A decklist is an array of rows `{"name": <Oracle name, NFC; "A // B" for multi-face cards>, "count": <u32, at least 1>}` with distinct names (main deck only; v2 is best-of-one).
- The host computes `deck_id` (Section 4.3).
- Engines publish their catalog decks with full lists in `hello_ok.catalog`, so the host can send decklists to agents.
- Each agent always receives its own full list (`game_start.own_deck`).

### 12.2 Information rules

The `rules` object, sent in `reset` and `game_start`:

| Field | Values and rule |
|---|---|
| `opponent_decklist` | `visible` or `hidden`. Rotating deck pools use `visible`, since both seats play the same list. Fixed-deck benchmarks default to `hidden` and may choose `visible`. |
| `mulligan` | `london` or `none`. A benchmark uses `london` wherever its engine supports it, and `none` only as the engine's declared default. The benchmark page shows the rule, because it changes deck balance. |
| `starting_player` | `host_assigned` or `toss_winner_chooses`. Benchmarks use `host_assigned` with `starting_seat` `p0`, since seat-swapped pairs already balance play and draw. |
| `starting_seat` | `p0` or `p1` with `host_assigned`; `null` with `toss_winner_chooses` |
| `card_name_domain` | `{domain_id, names}`: the public names a `card_name` choice offers. Rotating pools use every name in the benchmark's deck pool; fixed-deck benchmarks use every name in all registered entry decks. It is never derived from information hidden from a seat. |
| `extensions` | array of the extension names enabled for this game (Section 14) |
| `probe` | `true` only in conformance games that use the reserved probe; never in rated runs |

Every benchmark publishes its information rules, and every run manifest records them in the same shape as the wire, together with the engine facts that affect play:

```json
"information_rules": {
  "rules": {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
            "card_name_domain": {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]},
            "extensions": [], "probe": false},
  "engine_defaults": {"trigger_order": null, "replacement_order": null, "combat_damage_assignment": "engine_order", "mana_payment": null},
  "observation": {"poison": false, "player_counters": false, "designations": true, "player_progress": false,
                  "day_night": false, "passed_seats": true, "pending_triggers": true, "keywords": true,
                  "full_name": false, "exiled_by": true, "stack_text": false, "permanent_details": true, "known_cards": true},
  "native_id_extensions": [],
  "fairness_label": "validator only"
}
```

- `fairness_label` is `validator only` or `validator and probe` (Section 16).
- `native_id_extensions` lists audited extensions allowed in rated games, each `{"name", "audit"}`, where `audit` references the published audit (Section 14).

## 13. Fairness contract

- **F1, perspective.** Everything a seat receives (the forwarded `seat_decision` with its extensions, `game_start`, `game_over`) is a function of that seat's information state only.
- **F2, never send.** Section 6.8 lists what is hidden. Beyond it, engines never send:
  - engine-internal or physical identities, or ids stable across zone changes or looks;
  - global counters (the binding `step`, global group or object counters, session step indices);
  - anything about the other seat's decisions, candidates or timing;
  - text (`display_text`, `context.text`, stack `text`, `reason`) that reveals any of these.
- **F3, decision shape.** Whether a decision is posed, its candidate set, its order, and the size of its group never depend on facts hidden from the acting seat. For example, a library search always allows finding nothing, and arrangements have a fixed size.
- **F4, extensions.** `x_` payloads obey Sections 5.3 and 6.8 and F2 in full. `native_ids: true` waives only the rule that ids change across zones and looks; it never waives counters or hidden information (Section 14).
- **F5, host.** The host follows Sections 11.2 (forward only the canonical `seat_decision`), 11.3 (validate live), 11.6 (secrets) and 11.7 (isolation).
- **F6, declared rules.** Every benchmark publishes its information rules, and every run manifest records them with the validator verdict (Sections 11.3 and 12.2).

Residual channels that v2.0 does not close:

1. **Timing.** Wall-clock time between a seat's decisions reflects the other seat's thinking time, the number of its decisions (variable-length selections, searches, optional loops) and machine load. Bots may measure it.
2. **Adapter faithfulness.** The validator has no ground truth about hidden state. An adapter that leaks through `known` entries, display or context text, candidate labels, or extension payloads goes undetected until the reserved probe or an audit finds it. Every v2.0 engine is therefore "fairness: validator only".
3. **Rules errors.** An engine that implements a card wrongly can reveal or hide information the rules would not.
4. **Operator trust.** The operator holds the run secret during the run. Publishing the commitment first prevents choosing favourable secrets after the fact, but not a leak by the operator.
5. **Self-reported runs.** They have none of the isolation guarantees of Section 11.7. A bot run by its author can keep memory across games and machines.

## 14. Extensions

- **Placement.** `seat_decision.extensions` is the only engine extension point. It is an object whose keys match `x_[a-z0-9_]+`, are declared in `hello_ok.extensions`, and are enabled in `rules.extensions`; any other key is `malformed_request`.
- **Handling.** Extensions are engine-specific and optional to emit. Readers that do not know one ignore it. Hosts forward them inside the canonical `seat_decision`.
- **Native payloads.** Extensions let engine-native models play without a neutral re-encoding. For example, `x_kernel_v5` carries mtg-kernel's observation and legal actions, and `x_gorge_view_v1` carries gorge's per-seat view. A payload that holds numbers outside the integer bound carries them as strings, such as JSON text.
- **What a payload obeys.** Every payload obeys Sections 5.3 and 6.8 and F2:
  - no global counters, no session step indices, and no identities or counts that advance on hidden events;
  - no digest or hash computed over values the payload hides or rewrites (for example a stable id hashed over zone change counts), since a bot could re-derive the values by search.

  `native_ids: true` waives only identity freshness (ids stable across zones and looks).
- **Native ids in rated runs** are reserved. A rated benchmark enables an extension with `native_ids: true` only after an audit, and lists it with that audit in `information_rules.native_id_extensions`. The audit shows that, for that benchmark's card pool:
  - its stable ids carry nothing hidden;
  - none of its digests can be re-derived from hidden or rewritten data.
- **Event history.** v2 carries no public event history. An engine may offer one as an `x_` extension first.

Note on native ids: identities that persist across zone changes can reveal copies moving through hidden zones even without face-down cards, which is why they need an audit. Note on event history: the observation plus `known` covers the surveyed models (DraftZero's position rebuilding, pauper_sim, gorge's bots).

## 15. Fixed-deck benchmarks (reserved)

A fixed-deck ("bring your own deck") benchmark rates entries, where an entry is a pilot plus a deck. It is reserved: specified here, and required when the first benchmark that needs it ships.

- **Definition.** The benchmark declares `pairing: "fixed_deck"` (rotating benchmarks are `rotating_pool`). It lists entries `{"entry", "bot", "deck", "display"}` instead of a deck pool; `deck` is `{name, decklist}` or `{name, catalog_id}`.
- **Schedule.**
  - Every pair of entries plays seat-swapped game pairs, and each entry always plays its own deck.
  - Entries that share a pilot or an author never meet, so no author can throw games between their own entries.
  - Game ids are opaque, so a bot cannot infer which entry, or which hidden decklist, it faces.
- **Messages.** In `reset`, each seat's deck is its entry's deck. In `game_start`, `own_deck` is the entry's deck and `opponent_deck` follows `rules.opponent_decklist` (default `hidden`). `card_name_domain` spans all registered entry decks.
- **Ledger.** Rows add `entry_p0`, `entry_p1`, `pilot_id_p0`, `pilot_id_p1`, `deck_id_p0` and `deck_id_p1`.
- **Ratings.** Ratings are per entry, with slices by pilot and by deck.
  - The host adds one builtin `uniform` entry per distinct deck ("random with this deck"). The fit anchors the first of them, by `deck_id`, at 1000.
  - An entry's pilot margin is its Elo minus the Elo of `uniform` with the same deck, so deck strength cancels. Cross-benchmark charts use pilot margins for fixed-deck benchmarks.
- **Preflight.** Every entry's deck passes `validate_deck` and format legality before any game.

Note: one global random pilot with a reference deck would mix deck strength into skill.

## 16. Conformance

- **Fail closed.** Engines and the host emit only licensed messages, reject everything else with the pinned error codes, and never guess at an unlisted kind, vocabulary value, format or field. Agents follow Section 4.2.
- **Golden transcripts** live in `goldens/protocol_v2/*.transcript.jsonl`, one message per line as `{"dir": "host_to_engine" | "engine_to_host" | "host_to_agent" | "agent_to_host", "message": {...}}`.
  - They cover every message type, every v2.0 decision kind, each group shape (including a full arrangement and a rewind), and every error code.
  - Each carries its expected game digest. The reference stack replays them in both roles; engine adapters replay the environment-role portion.
- **Live validation** (Section 11.3) runs on every rated game. Its verdict is part of the run.
- **Fairness labels.**
  - An engine that passes the reserved noninterference probe, on sampled decisions across a benchmark's pool, is labelled "fairness: validator and probe" for that benchmark.
  - Otherwise it is labelled "fairness: validator only". Every v2.0 engine is.
- **Timeouts** exist outside the protocol, as declared budgets enforced by the host (Section 11.4). A slow or stuck participant loses its process, and the host adjudicates the game.

Test vectors (`run_secret` = the bytes 0x00, 0x01, ..., 0x1f):

| Value | Result |
|---|---|
| `commitment` | `630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd` |
| `game_secret(0)` | `7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e` |
| `game_secret(1)` | `952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e` |
| `game_id(0)`, `game_id(1)` | `g-f67d7fe78c792984`, `g-bb341404cf686511` |
| `agent_seed(0, "p0")`, `agent_seed(0, "p1")` | `8103969398531465`, `1382627979884484` |
| `agent_seed(1, "p0")`, `agent_seed(1, "p1")` | `4616060983342951`, `7705961899067306` |
| `id_key` for game 0 (Section 5.3) | `842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6` |
| object id, game 0, message `p0:card-17:z2` / `p1:card-17:z2` | `o-0a3647243d16bf78` / `o-e5e4b7ed2a0730e4` |
| object id, game 0, message `p0:card-17:z2:look:0` / `p0:card-17:z2:look:1` | `o-794a5cb152c9620f` / `o-e18a35822cc60e1c` |
| stream seed, game 0, `spellbench/v2/rng:p1:library_shuffle:0` (first 8 bytes) | `8a28fd4db75719b1` |
| `deck_id` of `[{"count":4,"name":"Lightning Bolt"},{"count":18,"name":"Mountain"}]` | `sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2` |
| `domain_id` of `["Lightning Bolt","Mountain"]` | `sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697` |
| SHA-256 of the canonical form of `{"b":"Chainer's Edict","a":"Lim-D\u00fbl's Vault","c":"tab\there"}` (NFC; the u-circumflex is the raw UTF-8 bytes `c3 bb`, the apostrophes unescaped, the tab written `\t`) | `041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377` |
| first chain value `d` of Section 11.8 for the `reset` example of Section 9.2 | `a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3` |

## 17. Changelog from v1

**Protocol, envelope and forwarding**
- Protocol string `spellbench/v2`; no v1 compatibility. Minor versions (`protocol_minor`) allow additive growth.
- Engines and the host stay strict. Agents are lenient readers, and extra fields in agent responses are ignored.
- `decision` split into the binding `step` (never forwarded) and `seat_decision`. v1's global `step` and `group_id` revealed the other seat's hidden decision counts. The host now forwards its own canonical re-serialization (RFC 8785).
- New per-seat `seat_step` and per-seat group ids.
- `state_summary` replaced by the full `observation` (Section 6), with knowledge rules and an update table.
- `candidates_sha256` removed from the wire; the host computes digests itself.

**Identity and names**
- Object ids are fresh on every zone change (MUST, was SHOULD) and on every look into a hidden zone. They are per viewer and keyed by the game secret.
- A reference to an absent object is sent as `null`.
- Card names are Oracle names in NFC (`"A // B"` in decklists, the face name in references).
- Integers are bounded by 2^53 - 1, with no fraction or exponent; nesting depth is capped at 64.

**Candidate kinds changed**
- `play_land` gains `face`.
- `cast_spell` gains `method`, and `choose_cast_mode` becomes `choose_cast_method` with named methods.
- `activate_mana_ability` gains `ability_index`; `ability_index` is pinned to Oracle order.
- `plot_spell` becomes `special_action` (`plot`).
- `choose_target` gains `slot`, `selected_count`, `minimum` and `maximum` (replacing `remaining`); `finish_target_selection` gains `slot`.
- `choose_cost_target` replaces `remaining` with `selected_count`, `minimum` and `maximum`.
- `choose_spell_mode` gains `selected_count`, `minimum` and `maximum`.
- `choose_option`, `choose_color`, `choose_number` and `choose_boolean` gain `purpose`, and `choose_option` gains `option_label`.
- `choose_effect_target`, `finish_effect_selection` and `discard` become `select_object` and `finish_selection`.
- `choose_kicker`, `choose_optional_cost_use` and `choose_spell_copy_payment` become `optional_cost`.
- `choose_optional_cost_which` becomes `choose_cost_option`, with `source`.
- `choose_spell_copy_retarget` becomes `choose_boolean` (`change_copy_targets`).
- `choose_madness_cast` becomes `optional_cast`.
- `choose_attacker_inclusion` and `choose_blocker_inclusion` become `declare_attack` (with the defender) and `declare_block` (one decision per blocker).
- `order_triggers` (one candidate per permutation) becomes sequential `order_pick` with distinguishable trigger items.

**Candidate kinds added and decomposition**
- New kinds: `mulligan`, `order_pick`, `arrange_card`, `choose_name`, `choose_replacement`, `choose_starting_player`, `distribute`, `choose_pile`, `special_action`, `optional_cast`.
- Reserved kinds: `pay_mana`, `narrow_name`, `narrow_number`.
- New decomposition rules: distinct candidates, `pass` first, no dead ends with an optional declared rewind, the 4096 cap, hidden-zone candidate order, fixed-size groups (arrangements fixed at 2n - 1), and the implied last order position.

**Messages**
- Engine `hello_ok`:
  - `capabilities.decklists_as_data` replaced by `deck_sources` and `catalog` (full decklists);
  - new `protocol_minor`, `rules_supported`, `observation` flags, `decision_kinds`, `engine_defaults` (with "never posed" semantics), `rewind` and `fairness`;
  - `extensions` become objects with `native_ids`.
- Agent `hello_ok` gains optional `requires`.
- `reset`: the integer `game_seed` is replaced by a 256-bit `game_secret`; decks carry a host-computed `deck_id`; new `rules`, including enabled extensions.
- `game_start`:
  - `decks` replaced by `own_deck` and `opponent_deck` (per rule);
  - new `rules`, `engine_profile`, `time_control`, `limits`, `resources` and `agent_seed`;
  - the game id is opaque.
- `choose` gains `clock`. In `choice`, only `candidate_id` is required; the echoes are optional.
- `game_over` carries the seat's own `seat_step_count` instead of global counts.
- The host-only terminal classification `forfeit` is formalized, with causes including `stalling`.
- New optional request `validate_deck`; new reserved request `probe_resample`, which returns whole seat decisions.
- New engine error codes: `deck_id_mismatch` (optional check), `unsupported_rule`, `unsupported_request`, `probe_refused`. The agent error codes are defined, and `no_pending_decision` is removed.

**Observation additions**
- `mulligans_taken`, `progress`, and permanent `statuses`, `class_level` and `chosen` (the last three behind the `permanent_details` flag).
- `attacking` split into a flag and `attack_target`; `blocking` split into a flag and `blocked_attackers`.
- Stack `divided`, with nullable stack targets.
- Face-down visibility follows the exiling effect.
- The `pregame` phase; nullable `active_seat` and `priority_seat`.

**Hosting and fairness**
- New fairness contract with an explicit list of residual channels.
- Live host validation with a run verdict; no published transcripts; a per-game digest chain.
- Per-game secrets with a published commitment, independent secrets for the two games of a pair, and opaque ids.
- Fresh verified sandboxes per game.
- Declared clocks, limits and resources:
  - per-turn and per-game stalling caps, the per-game caps below half of the game caps;
  - blame by non-pass selections, and a mandatory-loop draw.
- Information rules; halt and truncation attribution.
- Reserved fixed-deck benchmarks.

## Annex A. mtg-kernel bridge (informative)

What the `agent_bridge_v2` adapter implements, from the kernel's `ObservationV5` and legal actions.

- **Envelope:** the `seat_decision` split and per-seat `seat_step` and group ids.
- **Randomness and ids:** seed all randomness from `game_secret` (separate streams per seat and purpose), and use per-viewer object ids with fresh ids per look (Section 5.3). v1 used `obj-<arena_id>-z<zone_change_count>`, whose arena id is a physical identity that persists across zones.
- **Observation:**

| Observation | Kernel source |
|---|---|
| life, hand and library counts | `life_totals`, `hand_counts`, `library_counts` |
| `mana_pool` | `mana_pools` |
| `lands_played_this_turn` | `player_status.lands_played_this_turn` |
| permanent fields | `CardPublicV2` (tapped, summoning_sick, damage, counters: `plus1_plus1` becomes `p1p1` and so on, is_token; `goaded_by` becomes the `goaded` status) |
| `characteristics` | type flags, subtype ids mapped to names, effective power and toughness, color mask, keyword flags |
| `attached_to`, `exiled_by` | object relations `AttachedTo`, `ExiledBy` |
| `stack` | `StackItemPublicV2` (source, controller, targets, kind, mode, X, copy) |
| `attacking`, `attack_target`, `blocking`, `blocked_attackers` | the combat projection |
| `hand` | `own_hand` |
| `known` | `known_library_cards` (positions); `known_hand_cards` converted to name-level entries; the update table of Section 6.7 |
| `designations` | `initiative` |

- **Kinds:**
  - the kernel's typed selection purposes (`EffectTargetSelectionPurpose`) map to `purpose`;
  - the scry stages (bottom subset, bottom order, retained top order) and `OrderLookedLibraryTop` map to the fixed-size arrangement;
  - `OrderTriggers` maps to sequential `order_pick`;
  - `ChooseCastMode` maps to `choose_cast_method`;
  - kicker, optional costs, copy payment and madness map to `optional_cost`, `choose_cost_option` and `optional_cast`;
  - attacker and blocker inclusion scans map to `declare_attack` and `declare_block`. They must meet the no-dead-end rule: fix the known dead ends (a declined goaded attacker, a lone blocker on a menace attacker), or keep the affected decks out.
- **Declarations:**
  - `rules_supported`: `mulligan: ["none"]` and `starting_player: ["host_assigned"]` (the session does not surface mulligans);
  - optional flags `poison`, `player_counters`, `player_progress`, `day_night`, `full_name` and `stack_text` off;
  - `combat_damage_assignment: "engine_order"` if the session assigns combat damage itself;
  - naming, replacement order, distribution and piles absent from `decision_kinds` (the Pauper pool needs none; mana abilities are offered at priority and during cost payment);
  - decks the policy surface cannot represent keep failing `unsupported_deck`.
- **`x_kernel_v5` before any use:**
  - rewrite `step_index` and `physical_decision_id` to `seat_step` and `group_id`;
  - strip or zero every `zone_change_count`;
  - recompute over the rewritten references, or drop, every `LegalActionV5.stable_id`, the `visible_projection_hash`, and any other digest over rewritten fields (zeroing `zone_change_count` is fair only with this);
  - convert `known_hand_cards` to name level.

  Its arena ids remain native ids (`native_ids: true`), so rated runs need the audit of Section 14. Planned kernel-native feature extensions are audited the same way before use.
- **Fairness note:** the kernel already hides a library search's match count from the non-chooser. v2 extends the same principle to the envelope.

## Annex B. gorge (informative)

What a gorge environment adapter (a Go stdio command serving two seats in constructed formats) implements.

- **Randomness and ids:** gorge is deterministic and event-sourced. The adapter seeds its streams from `game_secret` (separate per seat and purpose) and emits per-viewer object ids instead of gorge's small integer object ids.
- **Observation:** from gorge's seat projection (`view.Project` with visibility `seat`; never `public` or `omniscient`). Fields the view lacks are completed from engine state:
  - the token flag, colors, mana value, lands played this turn and mulligans taken;
  - card types parsed from the type line;
  - `blocking` and `blocked_attackers`, inverted from `blocked_by`;
  - `known`, per the update table (or declare `known_cards` false).
- **Kinds:**
  - `KPriority` to the priority kinds, with `pass` first; `concede` is not offered, since the host handles concession.
  - `KTarget` to `choose_target` and `finish_target_selection`.
  - `KAttackers` and `KBlockers` (subset answers) to `declare_attack` and `declare_block` groups. gorge's own validators (required attackers, block quotas, minimum and maximum blockers) keep every candidate completable.
  - `KMulligan`: the keep/mulligan ask to `mulligan`; the bottom ask (one option per card) to `order_pick` `mulligan_bottom`.
  - `KModes` to `choose_spell_mode`; unless-pay modes to `optional_cost` `unless_payment`.
  - `KTriggerOrder` to `order_pick` `triggers`. gorge's first choice is put on the stack first, which is position 0.
  - `KTriggerOptional` to `choose_boolean` `optional_trigger`.
  - `KChoose`, by option vocabulary: `x` and `number` to `choose_number`; `exile` (delve) to `select_object` `delve`; `sacrifice` to `choose_cost_target`; `discard` to `select_object` `discard`; `search` to `select_object` `search`; `dig` to the arrangement; `name` and `type` to `choose_name`; yes/no may-cast to `optional_cast`; `keep` (legend rule) to `select_object` `legend_rule`.
  - `KReplacement` to `choose_replacement` (mana-color replacements to `choose_color` `mana`; apply or decline to `choose_boolean` `optional_replacement`).
  - `KArrange` to the fixed-size arrangement: pile A stays on top in answer order, with index 0 topmost; pile B goes to the option kind's destination.
  - `KStartingPlayer` to `choose_starting_player`.
  - `KCommanderZone` does not arise, since Commander is out of scope.
- **Extension:** `x_gorge_view_v1` carries the seat-visibility view and the native physical decision. A Go agent wrapping gorge's bots (the default bot, `lethal-pressure`, the learned scorer) computes one native answer and plays it across the group's substeps. The view carries gorge's native object ids, stable across zones, so the extension is `native_ids: true` and needs the audit of Section 14 for rated runs.
- **Declarations:**
  - `rules_supported.mulligan: ["london", "none"]`;
  - optional flags off where the view lacks them;
  - `mana_payment: "engine_autopay"` if mana abilities are not offered at priority.

## Annex C. XMage via CABT (informative)

What an XMage environment adapter built on the CABT bridge (an XMage overlay with a fail-closed NDJSON legal-option server) implements.

- **Server:** a Spellbench environment-role server beside `CabtProtocolServer`, reusing its session, prompt builders and fail-closed validation, with both seats as bridge players.
- **Observation:** projected for the acting seat. XMage's per-player client views, which already hide opponents' hands from human clients, are the starting point. `known` follows the update table, from XMage's revealed and looked-at records.
- **Kinds:**

| XMage prompt (CABT) | v2 kind |
|---|---|
| `PRIORITY` | priority kinds |
| `CHOOSE_TARGET`, `CHOOSE` (targets, card choices) | `choose_target`, or `select_object` with the purpose of the call site (`other` when unknown) |
| `CHOOSE_USE` | `choose_boolean`, or `optional_cost` for optional costs |
| `CHOOSE_CHOICE` | `choose_color`, `choose_name` or `choose_option`, by choice type |
| `CHOOSE_MODE` | `choose_spell_mode` |
| `ANNOUNCE_X`, `GET_AMOUNT` | `choose_number` (`x_value`, `amount`) |
| `GET_MULTI_AMOUNT` | `distribute` |
| `CHOOSE_TRIGGERED_ABILITY` | `order_pick` `triggers` (already sequential) |
| `CHOOSE_REPLACEMENT_EFFECT` | `choose_replacement` |
| `CHOOSE_PILE` | `choose_pile` |
| `PLAY_MANA` | `mana_payment: "engine_autopay"` in v2.0 (`pay_mana` is reserved) |
| `SELECT_ATTACKERS`, `SELECT_BLOCKERS` | `declare_attack`, `declare_block` groups |
| `CHOOSE_MULLIGAN` | `mulligan` |

- **Arrangement:** the bridge player overrides scry, surveil and the London bottom placement to emit the fixed-size arrangement and `order_pick`. Without the overrides they reach the seat as generic card choices (`select_object` `other`).
- **No dead ends:** XMage checks playability heuristically and rolls back failed casts, so the adapter declares `rewind: true` and uses the rewind of Section 8 instead of halting.
- **Determinism and secrecy:**
  - restore main-deck order before the seeded shuffle (CABT does this for new sessions);
  - replace every hidden-randomness source with generators seeded per stream from `game_secret`, never the shared `java.util.Random` (48 bits of state);
  - make object UUIDs deterministic per game, instead of `UUID.randomUUID`;
  - never let hash-map iteration order reach candidate order or an `engine_order` default (sort by stable keys);
  - use one card database copy per JVM, and one game per process at a time.
- **No simulations:** never answer a seat decision from a copied or simulated game (CABT already refuses prompts from simulation games).
- **Declarations:**
  - distribution of divided damage (`chooseTargetAmount`, which fails closed in CABT today) absent from `decision_kinds` until surfaced; decks that need it fail `unsupported_deck`;
  - `starting_player: ["host_assigned"]` until the pregame play-first question is surfaced;
  - `mana_payment: "engine_autopay"`.
