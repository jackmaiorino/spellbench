# `x_public_history_v1` and the kernel knowledge tracker

Status: specification draft for step 1 of #143, 2026-10-06. Parent design:
[pauper-kernel v2](2026-10-06-pauper-kernel-v2.md), changes C3 and C8.

## Purpose

World-model agents (gorge search-redeal, the XMage fair variants) rebuild hidden
zones from a seat's information only. The v2 observation shows the current board.
They also need the ordered public events that constrain hidden zones: draws,
shuffles, reveals, looks, library exits and insertions. This extension carries
those events, and the same stream drives the Section 6.7 update table, so
`pauper-kernel-v2` can declare `known_cards: true`.

## Wire shape

`seat_decision.extensions.x_public_history_v1` is present on every decision of a
game that enables it:

```json
{"schema": "x_public_history_v1",
 "events": [
   {"kind": "turn_began", "turn": 3, "active_seat": "p1"},
   {"kind": "draw", "seat": "p1", "card": null},
   {"kind": "zone_move", "owner_seat": "p1", "card": {"object_id": "9f2c…", "card_name": "Lightning Bolt", "owner_seat": "p1"},
    "from": {"zone": "hand"}, "to": {"zone": "stack"}},
   {"kind": "library_shuffled", "owner_seat": "p0"},
   {"kind": "library_rearranged", "owner_seat": "p1", "top_count": 1, "bottom_count": 1}
 ]}
```

- **Delta.** `events` holds every event the viewer could observe since the
  viewer's previous decision in this game, in the order they happened, up to
  the current decision. On the viewer's first decision, it starts at the
  beginning of the game, including the opening shuffles and draws.
- **Retransmission.** A retransmitted decision carries the same bytes. A rewind
  (Section 8) carries an empty delta, because a rejected selection changes no
  public fact.
- **Ids.** A `card` is `{object_id, card_name, owner_seat}`, or `null` when the
  viewer cannot identify it. `object_id` is the id the card has in this
  decision's observation (Section 5.3), and only when the card has not moved
  since the event. Otherwise it is `null`, so an id never links a card across
  a zone change. The extension declares `native_ids: false`.
- **No counters.** Events carry no index, step number, timestamp or global
  counter. A turn number appears only in `turn_began`, which is public.
- **Order.** Order is the engine's commit order, so it reveals nothing beyond
  what the board already shows.

### Event kinds

| Kind | Fields | Viewer sees the card when |
|---|---|---|
| `turn_began` | `turn`, `active_seat` | n/a |
| `draw` | `seat`, `card` | the viewer is the drawer |
| `zone_move` | `owner_seat`, `card`, `from`, `to` | either zone is public, or the viewer owns the card |
| `library_shuffled` | `owner_seat` | n/a |
| `card_revealed` | `owner_seat`, `zone` (`hand`), `card` | sent only to the seat it was revealed to |
| `looked_at` | `owner_seat`, `cards` (each a `card` with `position_from_top` or `position_from_bottom`) | sent only to the seat that looked, or that ordered the cards |
| `library_rearranged` | `owner_seat`, `top_count`, `bottom_count` | counts only; never identities or order |
| `token_created` | `card`, `controller_seat` | always (battlefield) |

- `from` and `to` are `{"zone", "position_from_top"?}`. A library position
  appears only when the engine records it as publicly determined (a mill or an
  impulse from the top, "put on top"). An ambiguous position is omitted. A draw
  is always from the top.
- Spell casts appear as a `zone_move` to the stack. Spell copies are not cards
  and appear only on the observation's stack.
- Life, damage, tapping, counters and combat are left out. The observation
  already carries their results, and no hidden-zone inference needs their order.
- A whole-hand reveal is a run of `card_revealed` events.

## Fairness

The stream obeys F2 and F4 in full. Three rules keep it safe:

1. **Count, never identity.** A hidden-to-hidden move the viewer does not own
   becomes a `zone_move` with `card: null`, so the viewer learns that a card
   moved, which the counts in the observation already show.
2. **Opponent choices stay private.** The other seat's scry, surveil or
   arrangement appears only as `library_rearranged` with public counts (judge
   guidance permits top and bottom counts). Mulligan bottoms appear as
   `zone_move` hand to library with `card: null` and no position.
3. **Shape independence (F3).** Whether an event appears never depends on
   hidden facts. A failed search still produces its `zone_move` events (none)
   and its `library_shuffled`.

The Section 14 audit for the eight-deck pool must show that every event kind
the pool can produce follows these three rules, using a two-world test. Pairs
of games that differ only in hidden cards and future randomness must produce
byte-identical streams for the viewer whenever their public play is identical.
Gorge's `x_gorge_search_v1` audit uses the same method.

## Knowledge tracker

`kernel_engine_v2.py --known-cards` declares `known_cards: true`. It needs a
bridge that exports public history, and it fails closed without one. The
adapter then applies the Section 6.7 update table to the same native stream,
per viewer, inside `kernel_history_v2.py`:

- **Libraries.** Position facts follow the journal notes in order: looks,
  reorders, scry, shuffles, and removal and insertion shifts. This mirrors
  the kernel's own per-observer `library_knowledge` exactly. Every decision
  compares the two by position, card and name, and any difference halts the
  game as an engine contract failure.
- **The other seat's hand.** Facts are name-level:
  - `from_public_zone` when a card returns from a public zone;
  - `tracked` when a known library card reaches its owner's hand;
  - `revealed` from hand reveals.
  A card that leaves identified takes its fact with it. One that leaves to a
  hidden zone costs every name one fact, and no remaining fact stays tied to
  a single copy. A card revealed in the current decision carries its id and
  stands in for one fact of its name. Every decision checks that the facts
  are a sub-multiset of the true hand and never exceed its count.
- **Not cross-checked.** The kernel's object-level `hand_knowledge` is more
  exact than the spec allows after a hidden departure, so the hand side
  checks against the true hand instead.

Evidence: 16 complete games (8 decks × 2 starting seats) ran through the
locally built bridge with `--known-cards` and the history extension.
- 15 ended naturally, and the Elves game with p0 starting hit the existing
  combat halt.
- Every decision passed the live validator, every library comparison agreed
  with the kernel, and every replay was byte-identical.

## Native sources

The private bridge (`mtg-kernel/src/agent_bridge_v1.rs` on the
`spellbench-pauper-v2` lane) answers each decision with the acting seat's
`ObservationV5`. Most events already exist natively:

| Event | Native source | Gap |
|---|---|---|
| `zone_move`, `draw`, `token_created` | `state.engine.event_history`: `ZoneChange`, `Draw`, `CreateToken`, `SpellCast` | the bridge does not export it yet |
| `library_shuffled` | `shuffle_library` in `state.rs` | the bridge resets in legacy randomness mode, which keeps no per-owner shuffle ordinal, so this needs a journal entry |
| `card_revealed`, `looked_at` | `reveal_hand_card`, `reveal_library_top`, `reveal_library_position` | no journal entry; only the resulting knowledge state |
| `library_rearranged` | scry, surveil and look-and-order resolutions | no public count record |
| `turn_began` | `UpkeepBegan` and the turn counter | none |

### Native change

The native change is one append-only journal plus an export, with no change to
rules behavior:

1. Add `observation_journal: Vec<ObservationEventV1>` beside `event_history` in
   the engine state. Reveal, look, shuffle and hidden-rearrangement call sites
   append to it with exact native identities. The library shuffle commit is
   one such call site. It is engine-internal and never
   read by rules or triggers.
2. On each production decision, the bridge's private support gains a
   `history` field: the omniscient slice of `event_history`, the journal and
   newly allocated objects (owner and printed name) since the previous
   production decision, each with its absolute offset. Private previews never
   carry it or advance it. It goes to the trusted Python adapter only, never to
   an agent.
3. The Python adapter (`integrations/mtg_kernel/kernel_history_v2.py`) checks
   that slices are contiguous, projects each one per viewer under the rules
   above, and keeps each seat's queue until that seat's next decision.

The journal changes the engine identity, which is intended: the board moves to
`evaluation_version` `pauper-neutral-v2.1.0` (design C8). The existing `x_kernel_flat_v4`
tensor and the g115, a48 and c12 policies are unchanged.

## Tests

- Unit: each event kind's per-viewer projection, including the null-card and
  count-only cases.
- Two-world: for each of the eight decks, games that differ only in hidden
  cards and seeds, with forced identical public play, yield identical viewer
  streams.
- Tracker parity: over complete games on all eight decks, the adapter's `known`
  equals the kernel's knowledge state at every decision.
- Consumer: gorge's public collector rebuilds the same hypothetical root from
  this stream as from `x_gorge_search_v1` on a recorded game. This runs in step 2.
