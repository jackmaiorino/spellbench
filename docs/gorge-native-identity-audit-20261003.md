# Public search identity audit for the pinned gorge Pauper pool

Status: incomplete. The earlier inspection verified observer identities and
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
positions. That guidance stops at later library mutation, reorder, shuffle or
token/copy creation. Initial, observed basic-land searches also guide their
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
still invalidate all potentially affected library cursors. This keeps an
opponent's London bottoming from discarding constraints on the actor's later
observed draws.

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

This is a source and information audit for the stated pool. Full twelve-mode
qualification, compatible guarded throughput evidence, rated games and public ratings
remain separate delivery work. Timing, public canonical-envelope limits and
the other residual channels listed in protocol section 13 remain as declared
by the protocol. No playing-strength result is claimed by these checks.
