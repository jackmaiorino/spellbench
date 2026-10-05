# Public search identity audit for the pinned gorge Pauper pool

Status: current identity review and full qualification remain incomplete.
Production runtime048 uses Spellbench source
`aee0564`, whose gorge/arena code matches engine source
`e3c84a133aa826a59be3c07f1644c2401d477e95`. The full Go suite passed for that
engine source. All seven production binaries are pinned on independent E/D
copies under runtime seal
`b4a17891e93b69c58cf5b8036853428e2366d750f4a43d7e35988e0c8a7c95ef`.
[The current job](gorge-runtime048-native-20261005.json) is running its
supported matched serial/parallel qualification. No full qualification or
playing-strength result is claimed.

The current public carry, hand-return and pass-ordering repair passed all four
unchanged saved actor-public inputs under the original 64-attempt/eight-world/
5000-submit limits:

| Public frames | Worlds | Proposals | Submits | Nodes | Exhaustions |
| --- | --- | --- | --- | --- | --- |
| 364 | 8 | 1 | 729 | 11 | 0 |
| 410 | 8 | 1 | 831 | 19 | 0 |
| 478 | 8 | 2 | 2412 | 1330 | 0 |
| 596 | 8 | 1 | 1220 | 31 | 0 |

Only364 has a captured native diagnostic baseline; all23 fields remain
identical. The other three rows have no native baseline. The pinned component
binary includes logging of hypothetical shuffle failures. The seven production
binaries use the original production overlay without that component logger.
[Current source review inputs](gorge-identity-review-inputs-20261005.json)
record exact hashes, unchanged emitters, affected functions and remaining gates.

Relative to the benchmark's prior audit pin `b01aaff`, only the reconstruction
implementation, its added regression overlay and the two-line test overlay
registration changed. The public collector, event projection, payment witness,
known-card projection, comparison and strategy history files are byte-compatible
with that pin. The new runtime logic reads actor-public identities/events,
projected hand sizes and constraints compiled from that history. Pass preference
uses the decision of an engine created by `NewHypotheticalPlanned`, rather than
a live game engine. It orders an already legal pass without removing alternatives.
Carry guidance tracks public names returned from visible zones, removes credit
on observed exits, and clears uncertain credit after an opaque exit. Its optional
prefix ends before the first public reorder; it still counts later consumption.
Alternate proposals retain the original constraints. Accepted completions still
replay every actor-public frame and pass the unchanged native known-card checks.

Runtime033 and040 failed their unchanged redeal gates; those historical receipts
remain failed. Component success above cannot qualify either old runtime or the
current complete12-mode panel. The benchmark still names the old `b01aaff` audit
URL. Before rated commitment, that URL must name a reviewed current audit;
qualification and benchmark review remain required. The rest of this document
retains earlier source checks and their stated limits.

The earlier inspection verified observer identities and
private-event filtering, but missed incorrect native choice ownership. Its
fairness conclusion cannot be reused for qualification or rated play.

The pinned Cleansing Wildfire script assigns its library search to the targeted
land's controller. The engine instead assigned confirmation and offered library
cards to the caster. That exposed another player's private library despite the
collector correctly filtering offers by the engine's reported chooser. Filtering
by chooser is insufficient when the engine assigns the wrong chooser.

The generated `effects/zone.go` overlay now defaults library confirmation, look
and pick to the searched player. Explicit `Chooser` selectors retain precedence;
the separate object-valued move path retains its controller default. This follows
[Forge's hidden-origin resolution at the pinned source](https://github.com/Card-Forge/forge/blob/95f04e8a04c8925fa97cb226fc3341cabcc90a53/forge-game/src/main/java/forge/game/ability/effects/ChangeZoneEffect.java#L840).
The native bot constructors, policies, weights and search budgets are unchanged.
This engine correction must be disclosed with the benchmark's source variant.

Two real-card regressions now pass. Only the land's controller receives the 52
private library offers. Reversing the unseen library tail changes those private
offers while preserving byte-identical caster history. The extended check also
selects different physical Forest copies and verifies byte-identical caster
history through the completed public outcome. After the controller
chooses a Forest and declines the optional shuffle, the caster's legitimate
26-frame public history reconstructs coherently in 52 submits, without exhausting
the existing budget. These fixtures play zero complete games.
The [correctness and runtime record](gorge-library-owner-repair-20261003.json)
links the sealed test logs, independently verified recovery and corrected inputs.

Earlier Cleansing Wildfire fixtures and saved 97- and 166-frame histories used
the incorrect chooser. Their sealed records remain mechanical replay evidence
for those old runtimes; they provide no fairness qualification and cannot be
replayed as current-engine inputs. A fresh current-runtime qualification and
review remain required. The field inspection below is retained with that limit.

The corrected runtime016 completed 280 native seed blocks and their replays,
560 natural games, without halts, truncations, validator violations, digest
mismatches, resampling failures, forced choices or mapping fallbacks. Eight
ordinary modes pass their native gates across the five decks. The four search
modes fail: five stock mode/deck cells have no covered search decisions, and
redeal modes record reconstruction exhaustion or refused roots. Three Wildfire
refusals at seed index 50 report a known Drossforge Bridge without an object.
The [sealed native audit](gorge-runtime016-native-audit-20261003.json) records
these failures. This does not complete identity review, reference-host clock
and isolation qualification, ratings or publication.

The Wildfire refusal was reproduced in a sealed 449-frame public input. A
public return placed Drossforge Bridge in the opponent's hand at frame 156.
An unseen draw at frame 173 retired its collector copy link. The known-card
projection kept the retired physical reference, including after a later public
Bridge play introduced a fresh reference at frame 180.

The projection now retires hand copy claims with private mixing while retaining
anonymous name/count minima. A visible exit consumes that name claim. Native
redeal pins matching hypothetical hand slots without creating observer links.
The saved 449-frame history supplies eight worlds in one public reconstruction
proposal and 1,006 submits, with no refusal or exhaustion. The earlier physical
reference is absent, the known name survives the hidden draw, and the later
public exit consumes it. Boundary tests, all strategy tests, native known-card
tests, vet and diff checks pass. See the
[repair record](gorge-known-hand-repair-20261003.json). Runtime016 search
qualification predates this change; a rebuilt runtime and fresh compatible
qualification remain required. Native policies and search budgets are unchanged.

A separate 94-frame Wildfire history exhausted public reconstruction after
5,000 submits. The replay now preserves weak public name/count bounds after
opening London bottoming, without restoring physical copy links or unseen
positions. Those bounds stop at affected library mutation, reorder, shuffle,
copying, unknown tokens or token names that collide with declared deck cards.
Ordinary declared tokens absent from the decks preserve the draw bounds.
Public spells count when they appear on the stack, before their effects can
draw more cards. Initial, observed basic-land searches also guide their
filtered relative order, including the actor's own Twisted Landscape subtype
filter. The fold preserves earlier actor draw positions and leaves nonmatching
cards unconstrained. These changes apply only to public replay witnesses;
the native weighted rejection sampler, policies and budgets are unchanged.

The exact saved history now supplies eight redealt worlds in one proposal and
194 submits. All its native rejection counters remain identical. A legal
62-frame London/filtered-search regression reconstructs in 151 submits, keeps
every known-card claim, and receives byte-identical history when unseen,
nonmatching library cards change order. The
[repair evidence](gorge-public-london-search-repair-20261004.json) retains the
failed candidates and the corpus-environment retry. Complete qualification and
review remain pending.

Runtime022 exposed a later 132-frame Wildfire failure after the earlier explore
repair. Keeping the London bounds through ordinary token creation and counting
the visible stack spell supplies eight known-card-valid worlds in 267 submits,
with all 23 emitted native diagnostics identical. Two legal token/stack cases
preserve complete actor history when unseen opponent cards change order. All
60 affected cases, vet and diff checks pass. The
[repair record](gorge-public-london-token-repair-20261004.json) and
[released cloud record](gorge-runtime022-cloud-20261004.json) preserve the failed
qualification and exact public diagnosis. This saved repair requires a new
runtime and compatible complete qualification before ratings or publication.

Runtime023 retained 13 failed public roots after actor London bottoming, Lembas
scry and a later shuffle. The public witness now tracks observed draw, explore
and top-window positions in each owned shuffle, preserving original positions
through observed London bottoms and provable actor arrangements. Later shuffle
sizes use visible library sizes and recorded draws or moves with a known owner.
Unrecorded complement orders and unknown mutations stop the optional fold.
Earlier conservative opponent London bounds also survive when proposing a spare
opening bottom, including after events in another library. All 13 roots supply
eight known-card-valid worlds in 284 to 628 submits, with every emitted native
diagnostic unchanged. Eight legal arrangement cases preserve complete history
under unseen tail permutations. All 69 affected checks, vet and diff pass.
The [repair record](gorge-public-arrange-repair-20261004.json) preserves passing
and failed attempts. Fresh complete qualification and identity review remain
required; these local checks play zero complete games.

Runtime024's mana-search failure was reproduced at a 157-frame public boundary.
The second owned Twisted Landscape search followed an earlier shuffle, with
cards already in hand. Public basic-search guidance now uses the observed
shuffle epoch and preserves that hand outside the shuffled library. The saved
eligible root supplies eight known-card-valid worlds in 319 submits with every
emitted native diagnostic unchanged. All 13 earlier Wildfire failure roots
still pass. Pending-search witness and answered-priority regressions preserve
history under unseen nonmatching tail swaps. Existing strategy and arrangement
checks passed; the two new fixture cases were corrected to compare the same
native known-card reporting settings and respect shipped search eligibility.
Those corrected cases, vet and diff checks pass. The
[mana diagnosis and repair record](gorge-mana-diagnosis-20261004.json) retains
every failed attempt. Rally's separate target-mapping failure, full
qualification, review, ratings and publication remain unfinished.

Runtime033 corrects the public witness's scry prefix bound using observed draw
counts, the printed constant maximum look count and the public bottom count.
Keeping and reordering the same window does not advance the untouched tail;
bottoming advances it only by the observed bottom count. The cursor stores
counts without card identities, resets at shuffle and disables guidance after
uncertain library mutations or unrecognized look bounds. The 81,400-case
prefix check enumerates hidden keep/bottom orders; it does not establish
whole-game noninterference or native qualification.

Public replay proposals also share the existing 5,000-submit total so that one
incompatible hypothetical shuffle cannot consume it all. Each proposal receives
at most a quarter of that total or three submits per actor frame, whichever is
larger, bounded by the remaining total. The native weighted sampler, policies,
weights, 64 proposal attempts, eight requested worlds and total node limit are
unchanged. This wrapper search change must accompany the source-variant
disclosure; it changes how witnesses are found and is not a playing-strength
result. The saved 364-frame root supplies eight known-card-valid worlds in one
proposal and 783 submits, with all 23 recorded native diagnostics identical.
The saved 410-frame root supplies eight worlds in two proposals and 2,107
submits; it has no captured native diagnostic baseline, so no diagnostic
equality is claimed for it. Neither root exhausts the total budget. The
[sealed component results](gorge-public-roots032-20261005.json) retain the
traces. Those component results and
[successful Go CI](https://github.com/jackmaiorino/spellbench/actions/runs/37250007216)
do not replace a complete current-runtime native audit, reference matrix or
identity review. The earlier failed panels remain failed.

The next source preserves basic-search guidance through an actor's completed
explore when its revealed top card moves to hand or graveyard. That observed
removal consumes one original-shuffle position and preserves the remaining
filtered relative order. It does not restore guidance already disabled by
another library mutation. The change uses only the actor-public explore marker,
known ownership and recorded zone move; native policies and sampler settings
remain unchanged.

The sealed 478-frame public failure exhausted 5,000 submits after its actor's
Nyxborn Hydra explore sent a revealed card to the graveyard. Logging-only
[reproduction](gorge-witness-trace037-20261005.json) showed a later Twisted
Landscape search reversing the actor's observed Mountain/Swamp offers.
[Component039](gorge-public-roots039-20261005.json) now supplies eight
known-card-valid worlds for that input in two proposals and 2,493 submits, with
zero exhaustion. The earlier 364- and 410-frame inputs still pass in 783 and
2,107 submits. All 23 captured native diagnostics remain identical for364;
neither410 nor478 has a captured native diagnostic baseline. The explore-then-
search regression and public-search suite pass on source98558dd, and complete Go CI later passed for engine sourcee3c84a1. These are component results from a pinned test binary,
not a production qualification or a playing-strength result. A rebuilt
production runtime, complete native/reference audits and identity review remain
required before rating.

The scope is the five catalog decks in `pauper-gorge`, gorge revision
`26257e0eda1779d739a07e835c6500b9c4dabc62`, Forge revision
`95f04e8a04c8925fa97cb226fc3341cabcc90a53`, and the public-history implementation
baseline in Spellbench `042c1912541f4a4251bd9e96a1912b299a4a742b`, with the
payment-history fields and London owner scope reviewed below. Runtime registry SHA-256:
`42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937`.
Changes to that implementation, pool, compiler or registry require checking
this audit's compatibility before reuse.

## Complete pool and reachable behavior

[The generated census](gorge-card-pool-census-20261003.json) contains all 83
distinct catalog cards, eight reachable token scripts and 62 behavior symbols.
The read-only `spellbench-gorge-audit` command checks the hash-pinned registry,
follows every face, linked ability chain and SVar ability, includes token
dependencies recursively, and adds Investigate's implicit Clue dependency.
Unsupported cards or missing/unsupported tokens stop the census. The output
contains names and behavior symbols, without card scripts or compiled IR.
Embalm's generated Sacred Cat copy uses the already included public face.

| Behavior | Pool carriers and native source | Information treatment |
|---|---|---|
| Draw, discard, discard costs, cycling, typecycling, madness | Draw/Discard in `effects/cardflow.go`; costs and keyword expansion in `rules` and `cards` | Private draws retain only their public shape for the other seat. Discards and face-up exile are visible zone changes. An unseen hidden-to-hidden move retires other-seat hidden copy links conservatively. |
| Library search and return to hand/library | ChangeZone/ChangeZoneAll in `effects/zone.go`; Brainstorm, Land Grant, Gatecreeper Vine, Squadron Hawk, cycling searches, Twisted Landscape, Cleansing Wildfire, Lembas, graveyard returns and Mesmeric Fiend | Only the acting chooser receives offers for a private search. Typed fetches have explicit public reveals or enter public zones. Library ordering payloads are removed. Shuffle and the other seat's private reordering retire library copy links; anonymous known-name membership may remain. |
| Private look, dig and scry | Dig/DigUntil/Scry in `effects/cardflow.go`, `rules/arrange.go`; Lead the Stampede, Winding Way, Preordain, Lembas, impulse effects and Balustrade Spy | Private look Notes are owner-only. Explicit reveals, mill and face-up exile are public. Private opponent asks and answers are removed, including their count. Only the actor's own observed arrangements retain copy position knowledge. |
| Explore through a Map token | `effects/explore.go` | The top card is explicitly revealed before its public outcome. The opponent's private election transcript is removed. |
| Face-up permanent, token, spell and ability effects | Mana, damage, life, counters, pump, tap/untap, destruction, countering, public choices, token/copy creation, Effect/Cleanup and their triggers/replacements/statics | Derived facts describe visible objects, printed abilities, public zones or the actor's own offers. Object-valued fields use observer aliases. A stack ability retains its public name after its source leaves, but cannot name an unobserved or retired hidden incarnation of that source. |

The census closes the source inspection to this pool. It includes all reachable
API, keyword, trigger, replacement and static families, including the eight
token behaviors. This pool has no face-down library/exile mechanism, planar or
commander objects, opponent blind library offers, or continuous library-top
look grant. Those mechanisms are outside this audit. Plot, madness, adventures,
bestow, the Saga transition and embalm use their ordinary visible zones here.

## Fields and identities

`strategies/history.go` captures owned values, then coalesces them at the
actor's own observation boundaries. `public_history.go.txt` drops both seats'
DecisionAsk/DecisionMade events, opponent answer transcripts and private
opponent Notes. `Delta.from`, answer indices and `native_index` are actor-local;
the raw feed index and event `Seq` are absent. Internal folded asks are the
actor's own offers under this pool's open-look effects. No opponent boundary
or offer count enters the payload.

`public_collector.go.txt` and the pinned observation overlay allocate monotonic
observer IDs only from displayed cards, permitted reveals/looks and visible
zone transitions. Their allocation does not advance for an unseen card.
`Frame.Board` is a seat projection with its in-memory continuation removed.
Card IDs, stack/source/target IDs, combat references, pending sources and
potential-action objects are rewritten. Native card `Token` strings are
removed. Secret Shuffle and LibraryOrder events carry no ordered IDs for
either seat. Observed events have no engine sequence or log hash.

Identity introductions and retirement are folded in event order before the
current board. A reveal followed by shuffle cannot restore the shuffled copy's
old link. The collector preserves an actor's answered arrangement, but retires
the other seat's private arrangement. The initial source binding of a stack
ability stays retired after a shuffle even if the same physical card is drawn
and receives a new visible identity.

The companion `x_gorge_view_v1` uses fresh per-seat incarnation aliases and
declares `native_ids:false`. `SearchAliases` joins current source/option and
offered payment cast/mana-source
aliases to already observed history references. Its internal HMAC identity keys
and move counters are absent from both extensions. Native decision sequence,
group labels and option indices are rewritten. Payment action/plan hashes are
recomputed from the rewritten actor-local decision and visible cast/mana-source
aliases; native plan hashes and source zone counters are absent.

An actor's exclusive payment answer is a comparable action with an optional
`SpellbenchPayment` string containing its complete semantic witness. The cast
and activation sources use the same observer-local identities. This string
contains an empty plan ID and zero source zone counters, without the native
action ID. Matching compares independently offered hypothetical witnesses in
that representation, then submits the target world's exact offer. The other
seat's payment answers remain excluded with its other private answers. Normal
non-payment actions and non-public native history retain their encoding.

The two London move sites in `rules/mulligan.go` emit `mulligan` and `bottomed`
for their asking player's own hand. The public sampler uses that observed
ownership to invalidate that player's library cursor. It does not infer a
hidden card identity, position or name. Other moves with an unknown owner
still invalidate all potentially affected native library cursors. This keeps an
opponent's London bottoming from discarding constraints on the actor's later
observed draws.

The public replay witness separately preserves actor opening-shuffle draw
positions when public library sizes uniquely identify a single anonymous
library move's owner. It accounts for all recorded draws and named library
moves, and refuses this inference for multiple unnamed moves, missing sizes
or unexplained changes. It never uses the effect controller as ownership.
Actor mutations, reordering, later shuffles, token/copy creation and exhaustion
stop this guidance. The native proposal compiler and weighted sampler are
unchanged.

For a single anonymous London bottom, an unmutated opening library may need
one spare card beyond the later public name bounds. The public witness can
place a declared card absent from those bounds in an opening slot and prefer
that legal hypothetical bottom. It does not infer the live bottom's name.
Any later shuffle or library movement, library ordering, token/copy creation,
multiple anonymous bottoms or conflict with an existing public position
disables this optional proposal. All alternatives, submit limits, native
proposal weights, complete public replay matching and known-card checks
remain in force.

The agent reconstructs hypothetical worlds from public setup and received
history. It receives no original engine, live hidden zones, chance prefix,
generator state, game secret or engine event log. Hypothetical worlds and their
search values therefore cannot recover the live game's hidden state through a
transported digest. Starvation/refusal statistics concern those reconstructions.

## Observed checks and limits

- A real atomic actor cast formerly failed replay at frame 21 with an empty
  ordinary choice list. Its repaired, canonically transported history accepts
  64/64 proposals and supplies eight worlds. A changed mana-residue witness is
  rejected, and the history test checks digest/counter stripping, observer
  references and preservation of the original native selection.
- A real atomic opponent cast rejects all native-policy proposals, then public
  reconstruction supplies eight redealt worlds in 64 submits without sending
  the opponent's payment answer to the actor.
- A legal opponent London mulligan followed by three distinct actor draws
  formerly exhausted 5,000 reconstruction submits. Restoring the actor's
  independent constraints accepts 24/64 native proposals and supplies eight
  worlds. These are correctness fixtures within the shipped budgets.

- A captured 47-frame history with an actor London mulligan exhausted 5,000
  public reconstruction submits because later actor-visible draws lost their
  positional guidance. London bottoms append behind the undrawn library.
  The public witness now preserves those known draw names until another
  library mutation or exhaustion of the original library. It reconstructs
  eight worlds in one proposal and 109 submits, with all 22 recorded native
  sampler fields unchanged. A legal two-seat London fixture verifies later
  draws, known-card constraints and identical actor histories under an unseen
  opponent land-order permutation. See
  [actor London repair](gorge-actor-london-draws-repair-20261004.json).

- A captured 96-frame CawGates history exhausted 5,000 reconstruction submits
  after an opponent Islandcycling search discarded guidance for later named
  actor draws. The public witness now supplies eight worlds in 224 submits,
  with all 22 recorded native sampler fields unchanged. A legal real-card
  search fixture supplies eight worlds in 122 submits and preserves complete
  actor history under different unseen opponent library orders. All 51
  affected strategy cases pass from one pinned binary across a retained suite
  wall-cap attempt and completion of its unfinished cases; Go vet and diff
  checks pass. See
  [Caw opening draw repair](gorge-caw-opening-draws-repair-20261004.json).

- A captured 316-frame Spy history exhausted 5,000 reconstruction submits
  when its single anonymous London bottom removed a hypothetical copy needed
  by later public discards. Optional spare-card guidance now supplies eight
  worlds in 648 submits; every world passes the known-card check and all 22
  recorded native sampler fields remain identical. A legal fixture with 12
  later opponent discards preserves complete actor history under different
  unseen opponent library tails. All 52 current affected strategy cases,
  Go vet and diff checks pass. See
  [Spy London bottom repair](gorge-spy-london-bottom-repair-20261004.json).

- A captured 110-frame Wildfire history exhausted 5,000 reconstruction
  submits because its actor-visible explore revealed Twisted Landscape while
  the hypothetical top card was Writhing Chrysalis. Public explore records and
  the pending nonland election now constrain that opening-library position.
  Normal battlefield token creation preserves the remaining library order.
  The same history supplies eight known-card-valid worlds in 220 submits,
  preserving all 22 recorded native sampler fields and the 64/8/5000 budgets.
  Legal land, kept nonland, discarded nonland and pending-choice fixtures
  preserve complete actor history under changes to the unseen library tail.
  All 57 affected strategy cases, Go vet and diff checks pass. See
  [public explore repair](gorge-public-explore-repair-20261004.json).
  Runtime021 emitted nine natural blocks before completed rows 48, 52 and 104
  failed the unchanged reconstruction gate. Its pod is deleted and all
  [terminal evidence](gorge-runtime021-cloud-20261004.json) is sealed.
  Current full qualification remains unfinished.

- `TestFullPoolHiddenCardsDoNotChangePublicHistory` passed for all 83 cards.
  Each variant creates a fresh engine and fresh collector, places the card in
  the opponent's actual hidden hand/library, and compares the complete actor
  seat decisions including both extensions at initial mulligan and first
  priority. The fixture checks the installed hidden objects directly. This
  exercises all pool definitions at genesis; it does not execute every effect.
- The shuffle/reorder, anonymous membership, hidden draw, chronology and stack
  source regressions passed, including legal play of the pinned Lembas and a
  separate redraw identity regression. See
  [public-history evidence](gorge-public-history-checks-20261003.json).
- A complete ordinary-bot game and deterministic replay passed on each of the
  five decks with live histories, valid identity bindings and no recorded
  literal-name leaks or semantic inconsistency. The literal-name check alone
  is insufficient to establish noninterference; this audit also inspects the
  fields and reachable emitters above.
- The rebuilt Windows binaries passed a complete Rally mirror and its replay
  through the Python reference host, with identical canonical game digest,
  416 validated steps, no validator violation and all child processes closed.
  Real engine and search-agent startup timeout checks also closed their
  processes. Details: [reference-host evidence](gorge-reference-host-checks-20261003.json).

- The exact failed Rally seed retained target 123, a ceased token, in a copied
  Chain Lightning target ask. Keeping the inherited target is a legal decline
  of new targets. The adapter now represents that option as
  `choose_boolean(change_copy_targets, false)` while preserving the native
  option index. The branch requires a single inherited object target on a
  stack copy and a matching ceased token. It does not create a current object
  reference. The real native ask, protocol validation, public extension and
  agent checks pass for keeping the target and retargeting a player. Keeping
  correctly fizzles the copy; retargeting deals three damage. All affected
  mapping, extension, agent, observation and validator tests, Go vet and diff
  checks pass. The separate 47-frame Rally reconstruction still exhausts the
  shipped budget. See [copy target repair](gorge-copy-target-repair-20261004.json).

- Public top exiles now retain consumed opening-prefix and later hand-exit
  constraints only for recognized printed effects, exact public stack sources,
  observed new exile membership and consistent library-size changes. This
  repairs the saved Rally failure in 91 submits. Actor-owned ordered look
  notes preserve their known top-card window, repairing Spy in 367 submits.
  All 16 saved failure roots produce eight known-card-valid worlds with
  identical native diagnostics. Legal printed-effect fixtures preserve full
  history under unseen-tail swaps; all affected strategy cases, vet and diff
  checks pass. These checks preserve the 64/8/5000 budgets and native sampler.
  See [public Dig repair](gorge-public-dig-repair-20261004.json). Complete
  qualification still requires the next immutable runtime and native panel.

- Runtime025's guarded local attempt completed 13 natural serial pilot blocks.
  Wildfire seed 52 still recorded 26 public reconstruction-budget failures, so
  it was stopped under the existing gate before a measured allocation or full
  audit. Rally seed 108 now completes with 23 covered search decisions and no
  reconstruction exhaustion or mapping failures. The frozen inputs, partial
  output and terminal state are sealed with verified independent recovery;
  canonical generation 170 has released. Two rejected placement-note
  preparations remain retained. See the
  [closed local attempt](gorge-runtime025-local-native-20261004.json).
  The prepared reference matrix remains gated on complete native qualification.

- The new public replay repair resolves Wildfire's saved 260-frame failure
  in 551 submits and returns eight known-card-valid worlds. It selects the
  observed stacked ability on Twisted Landscape and proposes a feasible
  retained hand across later shuffles. All 17 saved failure roots preserve
  native sampler diagnostics and pass known-card checks. All 45 affected
  strategy tests pass, including legal activation and retained-hand fixtures
  with identical public history under unseen tail swaps. Correct Go vet and
  diff checks pass separately after a verification helper substituted the
  test binary for those commands. That failed helper attempt remains sealed.
  See [public ability repair](gorge-public-ability-repair-20261004.json).
  Complete native qualification, reference qualification and ratings remain
  unfinished; no prior failed audit is qualified by these local checks.

This is a source and information audit for the stated pool. Full twelve-mode
qualification, compatible guarded throughput evidence, rated games and public ratings
remain separate delivery work. Timing, public canonical-envelope limits and
the other residual channels listed in protocol section 13 remain as declared
by the protocol. No playing-strength result is claimed by these checks.
