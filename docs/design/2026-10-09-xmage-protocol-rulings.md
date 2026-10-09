# XMage protocol rulings, 2026-10-09

Status: disposition of [issue #40][issue40], including its complete body and
three question comments. On 2026-10-09, the maintainer accepted all seven R1-R7
recommendations in response to the explicit sign-off question: "Accept all seven
(recommended)". They are the accepted future implementation contract. Existing
rules below remain binding until separately scoped implementation and admission
under a new negotiated protocol minor and evaluation version. Acceptance is not
implementation or authorization to change frozen boards or run benchmarks.

Reviewed main: `ec0bbed05951cd565e94d320e3b66d55bb2d53aa`. Source links below pin
that revision so later edits cannot silently change the evidence. This document
changes no benchmark, protocol schema, engine input, clock,
resource declaration, golden or evaluation fingerprint. No games or
compute measurements were run for this review.

## Consumers and disposition keys

`pauper-kernel-v2` uses mtg-kernel and evaluation version
`pauper-neutral-v2.1.0`. XMage MAD/MCTS enter through the kit as ordinary agents
with `engine: "any"`; XMage is their world model, not the board engine.
[The board definition][pauper] and [merged PR #178][pr178] establish this route.
[Issue #143][issue143] is now closed, but explicitly identified Q8/Q23 and Q15
as dependencies. The [one-board design][route] and [public-history design][history]
remain useful context; their older status paragraphs are not current run status.

The XMage wire still has consumers: [fdn-mirror-v0][fdn0],
[fdn-native-v1][fdn1] and [fdn-draftzero-v1][fdndz]. The existing
[standard-mirror-xmage definition][standard] also uses mirror decks, not
Section 15 fixed-deck entries. Closing #13 and #35 did not remove these engine
definitions. [Issue #36][issue36] retains learned-entry delivery and the older
non-mirror Limited/Standard manifest requests; this document does not complete
that work or admit unavailable learned entries.

- **A: answered by main.** Existing normative text, implemented behavior or a
  merged decision answers the question. An identified adapter gap is not a new
  permission to change frozen inputs, and structural validation is not proof of
  adapter faithfulness.
- **B: superseded / no live consumer of the requested feature.** The one-board
  route replaced the request, or current boards do not use the requested wire
  feature. This does not retire the FDN boards or declare future work delivered.
- **C: accepted future ruling.** A current board or its host needs the
  implementation. R1-R7 give the accepted rationale and concrete future change;
  existing behavior and pins remain unchanged.

## Complete question table

The original Q1-Q15 are in the [issue body][issue40]; Q16-Q23,
Q24-Q27 and Q28-Q33 are in [comment 1][questions16],
[comment 2][questions24] and [comment 3][questions28], respectively.

| Item | Question | Disposition and answer | Source |
|---|---|---|---|
| 1 | Publicly granted keywords on a face-down object | **A.** Section 6.4 exposes current face-down characteristics; 6.8 hides printed identity, not a public grant. V6 constrains names, not public granted keywords. The ward-only XMage projection is conservative implementation behavior, not a normative prohibition; a faithful public-grant correction must preserve hidden printed abilities and wait for new pins. | [Spec 6.4][s64], [V6][v6], [ward-only implementation][ward] |
| 2 | `card_name: null` for a nameless face-up copy | **A.** Use `null`, not an empty or invented name. Main's observation builder explicitly handles this case and the nullable observation name permits it. | [Nameless normalization][nameless], [observation name validation][names] |
| 3 | Token name convention | **C.** Accepted R1: serialize the token's public in-game name in NFC; do not substitute a Scryfall label or append a suffix merely for serialization. Make the exception to the Oracle-card-name rule explicit. | [Object names][s51], [current token/permanent projection][tokens] |
| 4 | Positionless looked-at library cards with `known_cards: false` | **A.** Main uses the permitted `searching`/null-position representation for a current library look with unknown position. It does not assert order or retain knowledge after the look. This is the existing conservative v2.0 representation, not permission to encode an unknown position as known. | [Spec 6.7][s67], [Looks contract][looks] |
| 5 | Seat-history-based `<key>:r<n>` ids after rollback | **A.** Allowed if the same secret and answers reproduce ids and ids never return. Main's viewer-local incarnation scheme implements that requirement; counters for unseen events remain forbidden. | [Spec 5.3][s53], [ViewerIds][viewerids] |
| 6 | Public trigger whose source later moves to a hidden zone | **A.** Current Section 6.6 omits a trigger whose source is currently hidden and unrevealed; the builder does the same. A public-event/provenance-based alternative would change the information rule and require a separate future proposal. | [Spec 6.6][s66], [pending-trigger filter][pending] |
| 7 | Published-pool priors under hidden decklists | **B.** Current mirror pools disclose the opponent list, so the requested hidden-pool restriction has no current board consumer. Static, provenance-declared model knowledge is distinct from runtime access; any future hidden-list board must decide that policy before use and keep runtime inputs seat-only. | [Information rules][s122], [seat-only inputs][s117], [mirror definitions][fdn0] |
| 8 | D6a: engine answers pass-only priority | **C.** Accepted R2, shared with Q23: retain posing now; add an opt-in, negotiated pass-only engine default for the next evaluation version. There is no current exception for priority in Section 7.6. | [Engine defaults][s76], [group posing][s8], [#143 dependency][issue143] |
| 9 | D6b: autopay includes convoke, delve, improvise | **A.** Main's payment planner explicitly includes their object choices under `engine_autopay`. This applies while paying a cost, not to unrelated selections or the choice to incur an optional cost; the `select_object` purpose vocabulary is not a requirement to pose choices owned by a declared payment default. | [Spec 7.6][s76], [PayChoice contract][paychoice] |
| 10 | D6c: remainder on first versus last blocker | **A.** The declared `engine_order` default requires remainder on the last blocker (or trample defender). XMage declares no damage default and poses `distribute`; its upstream default therefore does not license a different wire rule. | [Spec 7.6][s76], [XMage defaults][defaults], [distribution mapping][distribution] |
| 11 | S1-S6: rotating pairs, hidden pools, two deck ids, FDN legality, clocks, attribution | **B (partly A).** Current FDN format, mirror deck pool and board-wide clocks exist. Distinct-deck `rotating_pairs`, hidden rotating lists, dual deck ids and a manifest-expressible legality/provenance bundle remain future features with no consumer in these mirror definitions; the parser rejects non-`rotating_pool` pairing. Keep the remaining manifest work in #36, not as an implicit completion of X6. Pauper retains one clock for all entrants. | [FDN definition][fdn0], [pairing refusal][pairing], [one-board clock policy][clockdesign], [#36][issue36] |
| 12 | S7-S8: enable fixed-deck Standard and legality manifest | **B.** Standard mirror exists; fixed-deck Standard does not. Section 15 remains reserved and the parser refuses it. The proposed legality-list format is not implemented by format naming or card-resolution validation. Revisit with the future fixed-deck deliverable in #36. | [Section 15][s15], [pairing refusal][pairing], [Standard mirror][standard] |
| 13 | Public activation, combat and stack additions | **C (partly A).** Trigger-order items already have `ability_index`/`event_objects`; stack and pending-trigger records do not. Activation-use history, a separate first-strike damage step, attacker `blocked`, cast method and paid costs remain absent from core observation. Accepted R3 adds truthful, versioned public fields; optional mana restrictions need their own complete representation. | [Permanent and stack schema][s65], [trigger items][triggeritems], [phase vocabulary][phasevocab], [history design][history] |
| 14 | Agent `requires.engine` | **B.** For the Pauper route, the explicit replacement is an ordinary `engine: "any"` world-model agent. Native entries retain registry engine metadata and observation/extension requirements. The wire does not implement `requires.engine`; this disposition does not claim engine metadata already enforces a new compatibility handshake. | [Route C2 and question disposition][route], [agent requirements][s101], [registry metadata][registry] |
| 15 | Search-agent clocks and declared resources | **C (partly A).** Clocks and a shared per-seat resource block already exist. Per-entrant CPU/memory/scratch declarations and memory-aware admission do not follow from C2's illustrative JSON. Accepted R4 retains a board-wide clock and adds measured, fingerprinted per-entrant resources. The cited 2 GB/300 MB are estimates, not qualification evidence. | [Spec 11.4][s114], [current defaults and BotSpec][config], [CPU accounting][cores], [Route C2/C7][route] |
| 16 | Rewind abandons intervening groups of either seat | **A.** Section 8 explicitly abandons every group begun or completed since the action, including the other seat's groups; answered step counters continue and group ids are never reused. | [Spec 8][s8] |
| 17 | London bottoming after keep | **A.** Required: Section 7.5 bottoms k cards after keeping. The XMage overlay implements the after-keep ordering instead of repeated earlier bottoming. | [London rule][london], [London overlay][londonoverlay] |
| 18 | `rules_snapshot_id` includes rules-affecting overlays | **C.** Accepted R5: include semantic overlay code. Main hashes the core pin and patch series into this string but copies the decision/autopay/mulligan overlay afterwards. Other input hashes provide additional provenance, not this missing semantic identity. Change the identity and regenerate pins only in a new evaluation version. | [Identity construction][buildidentity], [engine identity contract][s91] |
| 19 | Replacement `affected: choosing seat`, `event: other` | **C.** Accepted R6: `other` may mean a genuine other event type, not unknown callback data; the choosing player must not substitute for an affected object. Capture the public affected entity/event at the call site, or explicitly declare an engine replacement-order default and disclose the changed decision surface. | [Replacement semantics][replacement], [current placeholder][replacementcode] |
| 20 | Trigger items with `event_objects: []`, `label: null` | **C (partly A).** Null labels are allowed. Empty event objects are correct only when no event object has a current visible incarnation; blanket emptiness does not meet the semantic definition. Accepted R6 captures public event participants and uses current viewer references. | [Trigger-item definition][triggeritems], [current trigger items][triggercode] |
| 21 | Whole looked-at hand or only candidates in `known` | **A.** Main shows the whole current look, including exposed cards that are not selectable. `known_cards: false` does not require candidate-only knowledge; Section 6.7 also permits declared under-informing, so whole-look projection is allowed and implemented rather than a new universal completeness rule. Never add cards the effect did not expose. | [Spec 6.7][s67], [whole-look mapping][wholelook] |
| 22 | Force no attack/block after three rejected declarations | **A.** No: the no-dead-end rule still applies. Main has a completability oracle, and three rejected declarations halt rather than silently restricting play to no attack/block. This supersedes the interim workaround. | [Oracle][oracle], [rejection handling][combatcode], [no-dead-end rule][nodeadend] |
| 23 | D6a follow-up: mostly single-candidate decisions | **C.** Same ruling as Q8/R2. The reported fraction is historical motivation, not a fresh timing measurement or authority for elision. | [Question comment][questions16], [engine defaults][s76] |
| 24 | Land-versus-cast decision kind | **A.** Existing generic `choose_option` with public `play_land` / `cast:<method>` labels is the implemented representation. No new kind is needed for this preliminary option; it must still lead to the corresponding legal action and expose no hidden facts. | [Option schema][options], [land/cast mapping][landcast] |
| 25 | Forced null block after declining an additional block | **A.** A forced single-candidate substep is permitted and must be posed. It is valid only where the combat oracle proves the partial declaration completable; it is not covered by pass-only R2. | [Spec 8][s8], [combat oracle][oracle] |
| 26 | Never offer attacks/blocks with a tax | **B.** The requested Propaganda/Ghostly Prison payment path has no live consumer in the current mirror pools. This is not a general license to omit legal declarations. Before admitting a pool that needs combat taxes, add complete cost-aware declaration/payment mapping or refuse that deck; do not relabel a mandatory tax as an optional cost. | [Current catalog][catalog], [FDN pools][fdn0], [Standard pool][standard], [no-dead-end rule][nodeadend], [callback-free oracle limit][oracle] |
| 27 | Cut large goldens short | **A.** Main uses small purpose-built decks that end naturally within a few turns, preserving terminal and digest coverage. Do not replace that with a rated-game cap or an unexplained partial transcript. | [Golden fixture contract][goldencontract], [conformance goldens][s16] |
| 28 | Reject front-face-only deck names | **A.** Section 12.1 requires full NFC Oracle `A // B` names for multi-face deck rows; engine resolver aliases do not override that contract. Main's catalog was corrected. A further resolver/preflight rejection repair is implementation work under new pins, not a new naming-policy question. | [Deck names][s121], [corrected catalog receipt][catalogreceipt], [current resolver use][deckvalidation] |
| 29 | Any-combination mana as a group of color choices | **A.** Main represents one `choose_color`, purpose `mana`, per unit, as a fixed group with bounds checked for completion. `distribute` requires a recipient and is not the correct scalar color allocation shape. | [Mana-color group][manacolors], [distribution rule][s75distribution] |
| 30 | Label multi-line `choose_number` amounts | **B.** The schema has source/purpose plus public context/display text; a new semantic amount label is an optional wire enhancement, not a current requirement. The documented Glissa multi-line callback is in the wider Standard catalog, outside the current two-deck Standard board and FDN pools. Revisit when a live pool needs it; use public row labels and never hidden counters as an identifier. | [Number schema][options], [multi-amount mapping][multiamount], [catalog][catalog], [Standard pool][standard] |
| 31 | Rewind a cast with no complete target set | **A.** Yes, with declared rewind: Section 7.1 permits abandoning an unfinishable action and Section 8 removes the failing priority candidate. Without rewind, the engine must offer only completable candidates. | [No-dead-end rule][nodeadend], [Spec 8][s8] |
| 32 | Reuse an engine process across games | **C (partly A).** Wire reset supports sequential games, but the arena still starts a fresh engine for each game. Accepted R7 allows opt-in worker-local reuse after state/cache isolation and cross-order replay checks. Agent sandboxes remain fresh per game. | [EngineProcess reset][reset], [arena process lifecycle][runner], [agent isolation][s117] |
| 33 | Exclude catalog from golden comparisons | **A.** Keep the existing full handshake comparison: `hello_ok` contains the catalog and goldens cover it. Main deliberately regenerated fixtures after catalog changes. Smaller stable fixture catalogs may reduce churn, but do not silently remove declaration coverage or weaken pinned equality. | [Golden catalog receipt][goldenreceipt], [strict golden comparison][goldencompare], [conformance goldens][s16] |
| probe_resample | Enable the reserved optional noninterference probe | **A.** Keep disabled for current XMage: `noninterference_probe: false`, `unsupported_request`, validator-only label. The kernel's two-world/history audit and the kit's reconstruction are not this engine request. Enabling it later requires Section 9.7 whole-seat-decision equality, knowledge-consistent resampling and proof the real game is unchanged before claiming validator-and-probe. | [Reserved probe][probe], [XMage declaration][defaults], [request refusal][proberefusal], [fairness labels][s16] |

## Accepted future rulings

### R1. Token names (Q3)

Use the public name of the token object after the game's name-changing effects,
normalized to NFC. A serializer must not rename it to match a card database's
token label. The rationale is that tokens need not have a printed Oracle card
entry and a viewer must see the object's actual public name. Amend Sections 5.1
and 6.3 to distinguish card face names from token/current nameless names; add
normalization examples, including copied and explicitly named tokens. Audit
`ObservationBuilder.permanent` and world-model name lookup against that rule.
Any projection or lookup correction changes engine/entrant inputs and waits for
the next evaluation version. Existing transcripts retain their recorded names.

### R2. Pass-only priority (Q8 and Q23, D6a)

Keep every current priority decision on the wire. Agents may answer a forced
choice without running their model; that still preserves the host exchange,
seat counters, public-history delivery and clock increment.

For a subsequent negotiated minor, add an opt-in
`engine_defaults.pass_only_priority: "engine_pass"` (absent/off on minor 0).
Only a physical **priority** point with exactly one legal candidate, `pass`,
may be resolved internally. Never elide a forced selection, combat slot,
arrangement, rewind boundary or another partial group. Engines must not infer
the condition from hidden opponent options or an incomplete candidate scan.

The benefit is avoiding repeated world reconstruction for an action with no
choice. The cost is a changed decision surface: fewer agent messages and clock
increments, different step/group counts and digests, and potentially different
agent random streams. Amend Sections 7.6, 8, 9.1 and 11.4; update strict parsers,
declaration validation and both relevant engine adapters. Specify that an
elided point consumes no wire step/group or increment, accumulates all
viewer-visible history for the next posed decision, and cannot erase a pending
rewind. Keep an internal deterministic work bound so a pass loop cannot hang
inside one engine step. Test mixed pass/action play, both seats' history deltas,
rewinds and terminal counts before any future board enables it. Use a new
`evaluation_version` and engine fingerprint; do not retrofit published games.

### R3. Public decision state (Q13)

Add an additive, negotiated observation revision containing:
per-permanent public activation-use records, `first_strike_damage`, attacker
`blocked`, stack/pending-trigger public `ability_index` and `event_objects`, and
spell cast `method` plus announced/paid optional costs. These facts distinguish
states with different legal actions or outcomes, so candidate lists alone are
insufficient for world reconstruction. `blocked` must remain true after the last
blocker leaves if the attacker is still blocked; it is not simply a nonempty
blocker list. Activation records must cover public limits and reset at the
appropriate rules boundary, rather than just counting current loyalty counters.

Amend Sections 6.2-6.6 and the strict observation parser. Populate fields from
authoritative committed public events in `kernel_observation_v2.py` and the
XMage observation builder, with viewer-local references and null/empty values
only where truthful. Old minor behavior remains readable and unchanged. Do not
infer missing event identities from hidden engine state. The existing history
extension is an input source, not evidence these core fields already exist.
Defer optional mana spending restrictions until a complete public representation
is specified. Every enabled observation change needs a new engine fingerprint
and evaluation version, including a new compatible reference-panel snapshot.

### R4. Search resources and clock (Q15)

Retain one measured time control per board, shared by all entrants. The current
Pauper values are already in the benchmark; C7's illustrative starting profile
does not replace them. Keep deterministic search work budgets separately
identified; resource declarations do not authorize wall-time tuning or new runs.

Add per-entrant `resources` to `BotSpec`/benchmark parsing and fingerprints,
resolving absent values to the existing shared block. Declare CPU, memory, GPU
use and writable scratch, based on the actual admitted process profile. Forward
each seat's effective declaration in `game_start`; engine cores remain a host
reservation. Update arena allocation to sum the actual two seat allocations and
engine allocation, checking available CPU, memory and scratch before launch.
Keep writable scratch game-local and clean it with the seat sandbox. Update
Sections 10.2 and 11.4 with the effective-resource rule and a negotiated scratch
field. A declaration is not evidence of container enforcement.

Rationale: a shared 4096 MB/default CPU allocation does not implement C2's
per-entrant scheduling, and estimates cannot qualify search agents. Existing
resource/clock pins remain untouched; introduce the schema and measured
allocations in a new evaluation version. This ruling requests no measurements
in this task and grants no paid-compute authority.

### R5. Semantic engine identity (Q18)

Include the rules-affecting overlay in `rules_snapshot_id`, using a canonical
digest of the ordered core patches plus decision/autopay/mulligan sources or a
versioned semantic-overlay artifact. Record the construction in the build
manifest and `engines/xmage/README.md`; update `scripts/build.sh` only with new
evaluation pins. Keep `card_pool_identity` scoped to card data and card-rule
sources. Rationale: equal rules identities should not hide different mulligan or
payment behavior. The current artifact/source hashes remain valid historical
pins; this ruling does not invalidate old evidence or recompute it in place.

### R6. Truthful callback semantics (Q19 and Q20)

Reject the blanket placeholder policy. In replacement choices, capture the
actual public affected player/object and event type at the callback's public
event origin. `event: "other"` is for another event kind, not missing knowledge;
an object-affecting event cannot be presented as affecting its controller.
When that cannot be implemented for an admitted surface, propose the existing
declared replacement-order engine default for that surface, with clear
disclosure and new pins; do not quietly change the current declaration.

For trigger items, preserve nullable labels, but record every public event
participant with a current visible incarnation using that viewer's current
reference. `[]` is appropriate only when there are no such objects. Extend the
XMage callback/event capture and `SeatPlayer` mapping, with regressions for
multiple triggers from the same source, departed sources and replacement events
affecting objects. This follows the existing typed semantics instead of treating
validator acceptance as proof of meaning. Clarify the unknown-versus-`other`
distinction in Section 7.4. Any added information/default or engine correction
must wait for a new evaluation version and cannot loosen the hidden-state boundary.

### R7. Engine process reuse (Q32)

Allow opt-in reuse of one engine per arena worker, with at most one active
game at a time and fresh agent sandboxes for every game. Leave fresh-process
execution as the default until qualified. Reuse must clear game/RNG/id/decision
and observation state, verify the same pinned engine identity, and restart a
worker's engine after a fault; no subsequent game may inherit private state.

Update the worker executor/runner lifecycle, not the seat isolation contract.
Verify fresh-versus-reused equality of primary rows/digests over permuted game
orders, including a failed prior game and known global cache cases. Rationale:
startup amortization may improve completed-work throughput, but the historical
rate quoted in #40 is not proof for current builds. Benchmark manifests must
record the execution mode, use a new evaluation version and preserve current
fresh-process pins. Throughput qualification, if later authorized, uses the
supported launcher and current resource policy; none is run here.

## Sign-off and version boundary

The maintainer accepted these seven decisions on 2026-10-09:

1. **Q3 / R1:** use the public in-game NFC token name and document the card-name exception.
2. **Q8 and Q23 / R2:** add negotiated pass-only priority elision, opt-in only for a new evaluation version.
3. **Q13 / R3:** add the public-state revision; defer incomplete mana-restriction metadata.
4. **Q15 / R4:** adopt measured per-entrant resources with CPU/memory/scratch admission and one board-wide clock.
5. **Q18 / R5:** include rules-affecting overlay code in the rules snapshot identity.
6. **Q19 and Q20 / R6:** require truthful affected-event and trigger-participant semantics; permit a disclosed replacement-order default only under new pins.
7. **Q32 / R7:** allow opt-in engine reuse only after state-isolation and cross-order replay qualification.

These are accepted requirements for the **next evaluation_version**, not
amendments to `pauper-neutral-v2.1.0`, existing FDN definitions or committed run inputs.
Wire additions also require negotiated protocol-minor handling; an evaluation
version bump alone cannot override strict v2.0 field/default rules. Old behavior,
goldens and fingerprints remain reproducible. This completes #40's maintainer
sign-off; implementation and admission evidence still belong to their delivery
lanes. None of the B dispositions authorizes opening a
new board or claiming the unfinished #36 work complete.

## Sources

[issue40]: https://github.com/jackmaiorino/spellbench/issues/40
[issue36]: https://github.com/jackmaiorino/spellbench/issues/36
[issue143]: https://github.com/jackmaiorino/spellbench/issues/143
[questions16]: https://github.com/jackmaiorino/spellbench/issues/40#issuecomment-5927855295
[questions24]: https://github.com/jackmaiorino/spellbench/issues/40#issuecomment-5930110706
[questions28]: https://github.com/jackmaiorino/spellbench/issues/40#issuecomment-5935024755
[pr178]: https://github.com/jackmaiorino/spellbench/pull/178
[pauper]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/benchmarks/pauper-kernel-v2/benchmark.json#L1-L96
[fdn0]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/benchmarks/fdn-mirror-v0/benchmark.json#L1-L57
[fdn1]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/benchmarks/fdn-native-v1/benchmark.json#L1-L63
[fdndz]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/benchmarks/fdn-draftzero-v1/benchmark.json#L1-L70
[standard]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/benchmarks/standard-mirror-xmage/benchmark.json#L1-L48
[route]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/docs/design/2026-10-06-pauper-kernel-v2.md
[history]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/docs/design/2026-10-06-public-history-v1.md
[clockdesign]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/docs/design/2026-10-06-pauper-kernel-v2.md#L175-L181
[s51]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L128-L140
[s53]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L146-L169
[s64]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L303-L319
[s65]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L321-L359
[s66]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L355-L359
[s67]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L361-L394
[v6]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1129
[s76]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L662-L680
[s8]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L699-L718
[s91]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L760-L770
[s101]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L976-L980
[s114]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1152-L1178
[s117]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1230-L1237
[s121]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1257-L1262
[s122]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1264-L1276
[s15]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1335-L1351
[s16]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L1353-L1364
[nodeadend]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L463-L477
[triggeritems]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L531-L534
[options]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L511-L524
[replacement]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L631
[london]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L583-L597
[s75distribution]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L658
[probe]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/spec/SPELLBENCH_PROTOCOL_V2.md#L913-L931
[ward]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/ObservationBuilder.java#L480-L498
[tokens]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/ObservationBuilder.java#L384-L401
[nameless]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/ObservationBuilder.java#L868-L873
[names]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/_schema.py#L205-L214
[looks]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/Looks.java#L20-L58
[viewerids]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/ViewerIds.java#L10-L17
[pending]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/ObservationBuilder.java#L645-L664
[paychoice]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/PayChoice.java#L27-L35
[defaults]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/server/EngineProfile.java#L168-L183
[distribution]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L2127-L2155
[pairing]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/bench/definition.py#L317-L331
[config]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/arena/config.py#L34-L70
[cores]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/arena/config.py#L376-L381
[registry]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/arena/config.py#L130-L159
[phasevocab]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/observation.py#L53-L68
[londonoverlay]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/LondonAfterKeep.java
[buildidentity]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/scripts/build.sh#L74-L96
[replacementcode]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L2740-L2767
[triggercode]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L2657-L2683
[oracle]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/CombatOracle.java#L21-L45
[combatcode]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L2431-L2443
[landcast]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L610-L650
[catalog]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/resources/mage/player/spellbench/catalog.json
[catalogreceipt]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/README.md#L157
[deckvalidation]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/server/EngineServer.java#L270-L284
[goldencontract]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/tests/x4s2/goldens.py#L1-L25
[manacolors]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L2200-L2252
[multiamount]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L2266-L2325
[reset]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/host/engine_process.py#L146-L169
[runner]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/python/spellbench/arena/runner.py#L276-L310
[goldenreceipt]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/tests/x4s2/README.md#L61-L64
[goldencompare]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/tests/x4s2/goldens.py#L438-L452
[proberefusal]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/server/EngineServer.java#L149-L155
[wholelook]: https://github.com/jackmaiorino/spellbench/blob/ec0bbed05951cd565e94d320e3b66d55bb2d53aa/engines/xmage/overlay/src/main/java/mage/player/spellbench/decide/SeatPlayer.java#L1026-L1034
