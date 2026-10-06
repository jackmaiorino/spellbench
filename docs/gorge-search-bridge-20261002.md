# gorge public search bridge

Status: all twelve modes are implemented, with completed qualification attempts
that failed per-deck search coverage and reconstruction gates. No mode is fully
qualified, rated or published. The [current native audit and source repair](gorge-native-audit-20261003.json)
records 280 blocks, 552 natural games, four duplicated halts, and eight natural
repair replays. The observations below retain their original source scope.
The pinned engine also assigned an opponent library search to the wrong player.
Its ownership is now corrected; earlier runtime evidence cannot establish fair
information access for the corrected benchmark. The
[identity audit](gorge-native-identity-audit-20261003.md) records the finding,
source adaptation and current zero-game checks.
Source pin: `26257e0eda1779d739a07e835c6500b9c4dabc62`.

`search` and `search-mana` call the native `searchseat.Choose`, candidate builder,
sampler proposal and weighting code, rollout teacher and default bot. Runtime
defaults remain 8 worlds, 64 attempts, 6 candidates, zero margin, zero horizon,
5,000 submits, sample seed 54321 and one worker. The mana variant adds the native
mana arm. No model, clairvoyance or oracle evaluator is enabled.

Recorded actor answers now retain the native option's structured `ManaSymbol`.
Multi-color choices can share source, object and ability; dropping the symbol
made their semantic actions ambiguous and prevented both rejection replay and
public reconstruction. A real two-color fixture accepted no worlds before the
repair and supplies eight worlds for either color afterward. Only the public
collector fills this field. Native options and selected intents are unchanged;
the corrected history changes sampler conditioning and requires new qualification.

The agent receives public decklists, its seat observations and
`x_gorge_search_v1` deltas. A delta ends at the actor's own native decision;
opponent asks, answers, private board snapshots and decision counters are
removed. Answer indices count actor frames only. Retransmissions reuse the
existing native decision plan. Invalid deltas fail without changing history.
Collector failures use an opaque public code.

The internal API is accessed by a nested module and Go build overlays generated
by `engines/gorge/scripts/setup-dev.py`. The pinned source tree remains
unchanged. The overlays adapt the native observation boundary: replay comparison occurs
at actor boundaries, hypothetical setup honors the declared London mulligan
rule, and copy identities are retired when hidden movement or a blind shuffle
loses knowledge. Public events allocate and retire identities in chronological
order before the final board, including reveals and shuffles within one burst.
ID allocation remains monotonic across retirement. These
adaptations change the native full-feed sampler's observation digest and
conditioning. They do not establish identical play to an unadapted native game.

After a shuffle, known library membership retains minimum name counts without
physical copy references. The public known-card projection checks these counts;
native redeal reserves enough anonymous copies in the hypothetical library and
subtracts them from its remaining pool. They receive no observer binding. A
visible draw consumes the corresponding count; an unseen draw forgets unpositioned
membership, following the native tracker's conservative policy. Anonymous counts
overlap subsequently observed copies rather than being added twice.

For these configurations, `Choose` needs only the public turn from its engine
argument. The agent constructs that value locally. It has no real game engine,
hidden deal, future chance state, engine log or callback into the environment.
The redeal configurations use a marker to request public reconstruction; the
placeholder engine is never used as their redeal root.
The current engine profile declares the search extension with `native_ids:true`
because it carries IDs across observation boundaries. The
[pool identity audit](gorge-native-identity-audit-20261003.md) covers all 83 catalog
cards and eight reachable tokens for protocol sections 13 and 14. Rated
configuration must cite its published, compatible version.

Checks observed on local Go 1.27.1, CGO disabled, one process and `-p 1`:

- Native `Choose` versus the public bridge: attacker, cast and mana fixtures
  used rekeyed objects and required covered decisions, worlds and rollouts.
  Intent and trace matched with serial and two-worker sampling and rollouts.
  Both reduced and shipped budgets passed. At shipped settings each fixture
  accepted 64 of 64 proposals and produced 8 worlds. Attacker, cast and mana
  respectively completed 16, 40 and 16 rollouts, with none capped. These are
  constructed decision fixtures, not five-deck qualification or clock evidence.
- Hidden opening deals and future seeds produced identical initial deltas.
  Added opponent private ask frames did not change public history. A blind
  shuffle retired a previously seen copy. An unidentified move between an
  opponent's hidden zones also retired its copy links when `Event.Player` was
  the effect controller. The actor's visible hand retained its links. London
  setup reconstructed a mulligan.
- All five decks passed a 64-decision transport prefix with the public history
  profile enabled, ordinary bot versus uniform. Both actors consumed live,
  sequenced deltas with no decision transcript events; leak and inconsistency
  counters stayed zero. The per-step hidden-state probe rebuilds the current
  observation but retains cached history. It does not establish whole-history
  noninterference. Every prefix intentionally truncated; none is a rated game.
- Both modes replayed through the host with identical game digests at a declared
  small truncation cap. This is transport evidence, not a natural completion.
- Policy identities, payment mapping and effect equivalence, hidden payment
  rejection, agent errors, qualification coverage rejection and Go vet passed.
  Two native sampler prefix/history tests also passed with the overlay installed.

`search-redeal` and `search-mana-redeal` are now implemented. The original
64-proposal sampler runs first. If it starves, a local hypothetical replay
branches legal opponent intents and immediately rejects mismatching public
events, identity introductions, boards or actor decisions. It uses the native
public epoch planner and the actor's recorded answers, then feeds the completed
root to the unchanged native pool derivation, known-card checks and uniform
redeal, with the anonymous membership adaptation above. No accepted native-policy
proposal or original engine is required.
The extra work has at most 64 proposals, 5,000 total submits across all branches
and proposals, and 160,000 enumeration nodes. It is charged to the same agent
clock and reported separately, including exhaustion and redeal refusals.
Hypothetical branches clone their own observer and rebind their shuffle planner;
rollout clones continue to use the upstream clone and fresh-chance behavior.

A named full-library basic-land search can guide the replay witness using its
observed membership and relative order. After a library removal, public draw
and removal counts give a weaker prefix bound: a card that was drawn came from
the first draws-plus-removals positions of the original library. The bound
subtracts named library exits and all unknown removals from public name counts.
Library additions, reorders, later shuffles and copied or ambiguous token cards
end this additional guidance. No absolute position of an unseen card is assumed.
A public hand exit before any post-shuffle draw requires that card to be in the
pre-shuffle hand. The witness carries the native sampler's corresponding
zero-draw deadline into the earlier weak prefix bound, subtracting library
exits and unknown removals there too.
London bounds also count public spells while on the stack, before a draw
effect resolves. Declared ordinary tokens whose names are absent from the
decks preserve those bounds. Unknown tokens, deck-name collisions, copying
and affected library mutations keep the optional guidance disabled. The saved
132-frame Wildfire failure now supplies eight valid worlds in 267 submits,
with all 23 emitted native diagnostics unchanged. Legal stack and later-land
cases preserve complete actor history under unseen opponent-tail changes.
All 60 affected cases, vet and diff checks passed; complete qualification
remains required. See the
[current repair](gorge-public-london-token-repair-20261004.json).
The replay also tries legal intents suggested by the next public action before
its other alternatives. Both changes affect witness construction only; native
world sampling, weights, scoring and the shared reconstruction budgets remain
unchanged. Historical corpus fixtures reconstructed the 52-option search in 45
submits and a declined-shuffle search followed by a later land play in 303
submits. Those fixtures used the incorrect native chooser and are retained only
as mechanical replay evidence. They do not qualify current information access.

The new constructed fixture deliberately makes an opponent pass with land in
hand. All 64 native-policy proposals fail; public reconstruction succeeds in
one proposal and 124 submits. Eight native redealt worlds then yield the same
intent and values as redeal from the source fixture engine, with 16 terminal
rollouts and none capped. Two source games with different hidden card names
and future seeds, but fixed public discards, produce identical public histories
and reconstructed worlds. Budget exhaustion refuses the root. Accepted native
attacker, cast and mana fixtures also retain shipped-budget and parallel parity.
Additional tests preserve anonymous known-library membership after a shuffle in
16 native fallback worlds, reject a world without the unique known member,
retire the old copy reference, and check visible and unseen draws. Two injected
knowledge histories with different hidden drawn names have identical complete
history bytes and projections. These are injected knowledge fixtures.

A separate fixture casts the pinned corpus's actual Lembas, answers its scry,
and sacrifices it through legal native intents. Its graveyard trigger returns
it to the library and shuffles while the food ability remains on the stack.
An earlier declined land drop makes all 64 native-policy proposals fail.
Public reconstruction succeeds in one proposal and 122 submits, then produces
8 redealt worlds satisfying anonymous Lembas membership. The fixture found
that the collector could reintroduce a shuffled source through a stack entry;
public capture now removes hidden stack-source references and pending triggers
from hidden sources, following the canonical observation and view extension.
Stack entries retain their first observed source binding only while it remains
live. A separate injected-draw regression failed when a later visible Lembas
restored the old ability's copy link; it now stays unlinked.
This is a bounded reconstruction check, not full search qualification.

Opponent private library reorders also retire copy links and retain anonymous
name counts. A regression failed before the fix and now passes. The actor's
own answered arrangement retains its legitimate copy and top-position claim.

One complete ordinary-bot mirror game per deck, plus its deterministic replay,
passed through the public-history host profile. All five ended naturally, with
live actor-only histories, valid identity introductions and aliases, and zero
leak or candidate inconsistency counters. Wildfire, Rally, Spy, Burn and CawGates
respectively used 1,937, 458, 422, 681 and 809 host steps. These correctness games
do not establish complete search qualification, whole-history noninterference
for the full card pool, or reference-host clocks and isolation. Commands, hashes
and bounds are recorded in `docs/gorge-public-history-checks-20261003.json`.

The previous adapter head `2eb26b8` passed the full hosted Go suite in
[run 37098528350](https://github.com/jackmaiorino/spellbench/actions/runs/37098528350),
including bounded ordinary qualification. All nested strategy tests and
affected policy, payment and qualification checks passed locally after the
redeal addition. The full hosted run at `e4a5b42` failed in the benchmark test's
old one-extension expectation; it is now corrected to verify both extensions,
the search launch mode and its native-ID flag. The focused check passed. Both
hosted Python suites at that head passed; current source needs fresh full CI.

The event audit preserves completed scry bottom counts. They are observable
game results: the [judge communication guidance](https://blogs.magicjudges.org/rulestips/2015/07/scrying-forever-its-now-an-evergreen-keyword-ability/)
permits opponents to know top and bottom counts, while card identities and order
remain hidden. Native secret `LibraryOrder` events carry only an occurrence;
their full library payload is removed even for the owner. This inspection does
not complete the event-emitter audit for the full benchmark card pool.

`gorgequal` reports eligibility, attempts, accepted proposals, worlds, covered
decisions, covered kinds, rollouts, submit counts, capped rollouts and delegation
reasons per deck and policy, with redealt worlds and public reconstruction
attempts, submits, enumeration nodes, exhaustion and refusal reasons reported
separately. A selected search policy must have a covered
decision on every deck to pass. Native search delegation is recorded separately
from the existing under-1% adapter mapping fallback gate.
Each selected redeal mode must also supply fallback worlds somewhere in its
five-deck qualification, with no reconstruction exhaustion or refused root.
Ordinary accepted replay alone cannot qualify a redeal implementation.

The frozen-registry launch path now names actual runtime bytes and a required
SHA-256. The freeze command verifies card scripts against the source digest,
records token script bytes and recompiles independently of development caches.
Fixture tests reject altered registry bytes and forged source lock labels;
they preserve loaded card and token definitions. The pinned runtime registry
has now been compiled once and preserved with exact hashes, six Windows/Linux
binaries, their compiler/linker and a container image. The engine and search
agent passed startup in a network-disabled, read-only container with one CPU
and 1 GiB memory; Windows and Linux hello profiles matched exactly. See
`docs/gorge-runtime-preparation-20261003.json` for commands, hashes and verified
cold/recovery locations. This is preparation; no games or allocation
qualification were run with these binaries.
Those preserved binaries predate the public redeal implementation; rebuild and
preserve new runtime bytes before qualifying the complete roster.

The updated preparation at `aa7364e` now preserves fresh Windows/Linux binaries
for the complete roster and reuses the exact registry above. All twelve modes
and the engine passed restricted Linux container startup with profiles identical
to Windows. A repeated Windows engine build produced the same retained binary
hash, and normal exit left no containers for the new image. See
`docs/gorge-runtime-preparation-20261003-002.json` for hashes, build commands and
verified D/E copies. These checks cover hello and normal exit only; forced
termination, complete reference-host games, clocks and allocation remain pending.
Those binaries precede the private-reorder and stack-source fixes above and
must be rebuilt before qualification.

Preparation `042c191` now preserves another six Windows/Linux binaries with
those fixes, using the same exact registry. The engine and all twelve modes
again passed restricted hello with identical Windows profiles and normal-exit
cleanup; a repeated engine build reproduced its retained hash. New artifacts
are at `E:/spellbench-gorge-runtime-20261003-003`, with verified D recovery and
the earlier sealed versions retained. Commands and hashes are in
`docs/gorge-runtime-preparation-20261003-003.json`. No substantial evaluation
or allocation qualification was launched. The fresh availability check found
Jack's canonical reservation free and the previously observed formal PID
absent, without inferring a research result. Haley's queued training window
keeps priority; RunPod's read-only inventory still returned HTTP 403.

The complete pool census and source audit are recorded in the linked identity
audit. A fresh-capture hidden-state test passed across all 83 cards, and the
rebuilt Windows runtimes passed a Rally reference-host replay plus startup and
decision timeout cleanup. These checks leave full mode/deck qualification,
shipped-budget clock evidence and guarded completed-work throughput to finish.
Freeze the complete roster before evaluation. All twelve playable strategies are
implemented; none is qualified, rated or published.
The draft benchmark now lists all twelve plus uniform and heuristic. Its
search profile, artifact versions and roster must pass qualification and be
frozen before any rated run.

The supported guarded allocation probe reached two natural Wildfire games,
then the reference host rejected an interactive Nihil Spellbomb mana decision
under the incorrectly declared `engine_autopay` default (V8, spec 7.6). The
guard stopped without valid throughput evidence or rated games, and canonical
host generation 99 released. The full failed records remain at
`D:/e-scratch/spellbench-gorge-qualification-20261003-002`.

The declaration now leaves `mana_payment` null: upstream atomic cast witnesses
coexist with interactive triggered-cost payment. Native policy behavior and the
reference validator are unchanged. The existing Spellbomb fixture passes in
both manual and cast-witness modes; native atomic-cast commitment and pool-only
effect equivalence also pass. The failed allocation probe used an unsaved
throwaway secret, so its exact third game is not claimed as replayed. A fresh
pinned runtime and guarded comparison remain required.

Runtime `b6c8282` now preserves fresh Windows/Linux binaries for the corrected
declaration at `E:/spellbench-gorge-runtime-20261003-004`, with verified D
recovery. All twelve modes passed restricted startup and the engine build
reproduced its hash. A new public Wildfire fixture, uniform against
lethal-pressure, reached interactive mana at step 265 and ended naturally after
560 validated steps. Its replay produced the identical canonical digest and all
three child processes closed. This is a new fixture, not a replay of failed
attempt002. See [payment evidence](gorge-reference-payment-check-20261003.json)
and [runtime pins](gorge-runtime-preparation-20261003-004.json). No mode is yet
qualified, rated or published.

The real command's game-start check found a separate integration omission:
only `search` and `search-mana` loaded the registry, leaving both redeal modes
unable to start. It also found the auto-pay agents' stale requirement for the
incorrect global `engine_autopay` declaration. The command now loads the static
registry for all search modes, and auto-pay policies consume offered cast
witnesses without claiming that the engine answers triggered-cost mana. The
old runtime004 fails both seats for those four modes; its records are retained.
Affected agent tests and vet pass. Fresh runtime bytes and real game-start
checks for all twelve modes remain required before the guarded retry.

Runtime `e2dab41` is now preserved at
`E:/spellbench-gorge-runtime-20261003-005`, with verified D recovery. The actual
reference-host game-start check passes all twelve modes in both seats, including
the eight handshakes that failed against runtime004. Every process closed.
The source and limit statement are in
[game-start evidence](gorge-game-start-checks-20261003.json). These handshakes do
not execute search or qualify completed games. XMage holds a separate canonical
reservation while the gorge retry is prepared.

An optional aggregate policy receipt now exposes real subprocess coverage to
the operator at process close. It shares the existing qualification fold and
records native mapping counts, eligible/covered search, worlds, rollouts and
public-root reconstruction/refusal work. It serializes public session labels
and counters only. Search options, RNG streams, actor inputs and the game wire
are unchanged. The supported guarded probe can collect these receipts to verify
actual search coverage and compare it across worker rungs.

Public reconstruction now guides an unmodified initial opponent library from
a named full basic-land search. It conditions the number of each basic drawn
before that search and the relative order of the offered matches. Nonbasic
positions and hidden hand identities remain sampled. A strict printed-ability
allowlist excludes restricted, blind and ambiguous searches. Every proposed
root must still replay the complete actor-visible history within the original
attempt and submit limits before supplying the native redeal.

The historical Cleansing Wildfire fixture exposed 52 ordered opponent basics
because the pinned engine assigned its library choice to the wrong player.
Its 45-submit replay and the saved seed50, 97-frame and 166-frame repairs are
mechanical evidence for that faulty runtime. They do not establish permitted
information or current-runtime qualification. The original sealed histories,
failures and results are retained rather than transplanted into the corrected
engine.

The generated engine overlay now assigns library confirmation, look and pick
to the searched player unless an explicit `Chooser` selects otherwise. This
matches the pinned Forge hidden-origin implementation. Only the targeted land's
controller receives Cleansing Wildfire's private choices. Real-card regression
tests check that different unseen library order changes the controller's offers
while leaving byte-identical caster history. The legitimate public outcome
reconstructs its 26 caster frames in 52 submits. Affected effects, rules and
all nested strategy tests, vet and the diff check pass. These are zero-game
correctness checks; full qualification remains unfinished. Native bot policies,
primary sampling, weights, chooser/scorer, rollout limits and reconstruction
budgets retain their pinned implementation. The engine rules correction is an
explicit source adaptation, recorded in the
[updated identity audit](gorge-native-identity-audit-20261003.md).

The corrected runtime016 audit completed 280 seed blocks and their replays,
560 natural games. All native validator, digest, resampling, consistency and
mapping checks passed. Eight ordinary modes pass their native gates. Search
qualification remains unsuccessful: five stock mode/deck cells have zero
coverage, and both redeal modes retain reconstruction exhaustion or refusal.
Three Wildfire/search-redeal refusals at seed index 50 name a missing known
Drossforge Bridge. The full failed result is preserved in the
[current audit record](gorge-runtime016-native-audit-20261003.json).

The guarded allocation comparison completed identical 26-block inputs at one,
six and thirteen workers. All three primary outputs have the same SHA-256;
thirteen workers were 4.80 times faster than serial. The canonical supervisor
released generation 146 with no live descendants. These are placement and
native correctness results, with zero rated games. Full hosted CI passed at
`af29003`; the later test-only outcome extension passed its affected local tests.
No mode is fully qualified, rated or published.

A focused seed50 diagnostic reproduced the missing Drossforge Bridge reference
in 449 actor-visible frames. Private mixing had retired an opponent hand copy
link while known-card projection still required it. The projection now retains
anonymous hand name/count minima and native redeal pins matching hypothetical
slots. It creates no observer binding. Visible exits consume the known name.
The same saved history now supplies eight redealt worlds in 1,006 submits,
without exhaustion or refusal. All affected strategy and native knowledge tests,
vet and diff checks pass. The
[sealed repair evidence](gorge-known-hand-repair-20261003.json) preserves the
original failure and both verification attempts. Policies and budgets remain
unchanged. This source change requires a new frozen runtime and search
qualification before rated play; runtime016's failed search report is retained.

The later runtime021 qualification emitted nine natural blocks and their
replays, then stopped because rows 48, 52 and 104 fail the unchanged
zero-reconstruction-refusal gate. A saved Wildfire history identifies an
actor-visible explore top-card mismatch. The public witness now uses completed
explore records and the pending nonland election to constrain that position;
normal battlefield token creation preserves the original library order. The
same 110-frame history supplies eight known-card-valid worlds in 220 submits,
with all 22 recorded native sampler fields and 64/8/5000 budgets identical.
Legal land, kept nonland, discarded nonland and pending-choice fixtures
preserve complete actor history under changes to the unseen tail. All 57
affected strategy cases, Go vet and diff checks pass. The
[repair evidence](gorge-public-explore-repair-20261004.json) and
[released cloud attempt](gorge-runtime021-cloud-20261004.json) are sealed with
independent recovery copies. Current full qualification remains unfinished.

The later seed52 capture extends the failing actor-public history to 410 frames.
An exact logging-only replay reproduced frame 355's Forest/Vault of Whispers
identity mismatch. A tighter scry prefix bound alone preserved the 364-frame
repair but still exhausted the 410-frame case. Both results remain retained.

The witness search now shares its existing 5,000-submit total among fixed-shuffle
proposals, giving each a bounded allowance based on history length. Native
sampler weights, policies, rollout settings and 64/8/5000 options remain unchanged.
The public scry bound uses only draw counts, bottom counts and declared look
limits; 81,400 enumerated hidden-order paths satisfy it. Both exact saved roots
now yield eight known-card-valid worlds: 364 frames use 783 submits in one proposal,
and 410 frames use 2,107 submits in two proposals, with zero budget exhaustion.
The 364-frame capture also verifies unchanged native sampler diagnostics; the 410
capture has no full native diagnostics baseline. The
[sealed component regression](gorge-public-roots032-20261005.json) retains all
inputs, runtime pins, traces, release and billing evidence with independent
recovery. This test binary is not a production runtime, and full native/reference
qualification, ratings and publication remain unfinished.

## Native129 reconstruction repairs (2026-10-06)

The native129 qualification halted at game 51 on a Wildfire search-redeal budget
exhaustion. The repairs below change only the replay witness: the guidance that
proposes opponent shuffle orders and preferred opponent intents for the public
reconstruction. Native sampler proposals, weights, policies, rollout settings and
the 64/8/5000 options are unchanged. Each repair has a unit fixture that also
checks the native compiled constraints are untouched.

- Split payment taps are offered as observed payment plans, shortest first.
- Carry guidance counts fixed top positions before adding held-card deadlines.
- Typed landcycling searches and arranged nonbasic windows keep the basic-search fold.
- Same-direction anonymous library moves are attributed by library size change.
- London bottoms keep revealed-until, declined-search and scry draw bounds, and
  every anonymous bottom proposes a never-public spare.
- A complete revealed hand proposes its entry order.
- Brainstorm-style draw-and-put-back keeps actor positions and opponent draw bounds.
- Verified reveal-until windows count their hidden moves as consumed top positions,
  and a land-free reveal that empties the library is accepted.
- An opponent's explore records the revealed top card as a position.

All 113 earlier saved captures except 11 pass, including every native129 capture.
A 40-game screen of the redeal modes (seed indices 48-55, 104-111, 160-167,
216-223 and 272-279) went from 197 exhaustions in 10 games to 179 of 1,797
reconstruction attempts in 7 games. Burn and Rally are clean. Two long Wildfire
mana-redeal games (54 and 55) hold 150 of the 179. They need hidden-hand contents
carried across many shuffles, which the current carry guidance cannot express.
Excluding them, the rate is 29 of 1,647 (1.8%), still above the proposed v2
counted-fallback cap of 1%. Qualification, the reference matrix and ratings remain
unfinished.
