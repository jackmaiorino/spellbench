# gorge public search bridge

Status: implementation with bounded correctness checks. No full qualification,
rated games or publication. Source pin: `26257e0eda1779d739a07e835c6500b9c4dabc62`.

`search` and `search-mana` call the native `searchseat.Choose`, candidate builder,
sampler proposal and weighting code, rollout teacher and default bot. Runtime
defaults remain 8 worlds, 64 attempts, 6 candidates, zero margin, zero horizon,
5,000 submits, sample seed 54321 and one worker. The mana variant adds the native
mana arm. No model, clairvoyance or oracle evaluator is enabled.

The agent receives public decklists, its seat observations and
`x_gorge_search_v1` deltas. A delta ends at the actor's own native decision;
opponent asks, answers, private board snapshots and decision counters are
removed. Answer indices count actor frames only. Retransmissions reuse the
existing native decision plan. Invalid deltas fail without changing history.
Collector failures use an opaque public code.

The internal API is accessed by a nested module and Go build overlays generated
by `engines/gorge/scripts/setup-dev.py`. The pinned source tree remains
unchanged. The overlays adapt three native behaviors: replay comparison occurs
at actor boundaries, hypothetical setup honors the declared London mulligan
rule, and copy identities are retired when hidden movement or a blind shuffle
loses knowledge. ID allocation remains monotonic across retirement. These
adaptations change the native full-feed sampler's observation digest and
conditioning. They do not establish identical play to an unadapted native game.

For these two modes, `Choose` needs only the public turn from its engine
argument. The agent constructs that value locally. It has no real game engine,
hidden deal, future chance state, engine log or callback into the environment.
The current engine profile declares the search extension with `native_ids:true`
because it carries IDs across observation boundaries. Rated use still needs the
published identity audit required by protocol sections 13 and 14.

Checks observed on local Go 1.27.1, CGO disabled, one process and `-p 1`:

- Native `Choose` versus the public bridge: attacker, cast and mana fixtures
  used rekeyed objects and required covered decisions, worlds and rollouts.
  Serial and two-worker sampling and rollout answers matched exactly. These
  fixtures deliberately use smaller budgets; a separate test pins shipped defaults.
- Hidden opening deals and future seeds produced identical initial deltas.
  Added opponent private ask frames did not change public history. A blind
  shuffle retired a previously seen copy. London setup reconstructed a mulligan.
- Both modes replayed through the host with identical game digests at a declared
  small truncation cap. This is transport evidence, not a natural completion.
- Policy identities, payment mapping and effect equivalence, hidden payment
  rejection, agent errors, qualification coverage rejection and Go vet passed.
  Two native sampler prefix/history tests also passed with the overlay installed.

`gorgequal` reports eligibility, attempts, accepted proposals, worlds, covered
decisions, covered kinds, rollouts, submit counts, capped rollouts and delegation
reasons per deck and policy. A selected search policy must have a covered
decision on every deck to pass. Native search delegation is recorded separately
from the existing under-1% adapter mapping fallback gate.

Remaining work: audit complete histories on all five decks, preserve legal
mapping at shipped budgets under reference-host clocks, bind the actual corpus
cache, qualify isolation and guarded completed-work throughput, and freeze the
complete roster before evaluation. `search-redeal` and `search-mana-redeal`
remain explicitly refused: their native fallback clones a real engine, and an
equivalent public reconstruction that also handles zero accepted proposals is
not implemented. They remain unfinished inventory entries.
