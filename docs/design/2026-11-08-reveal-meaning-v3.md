# Opt-in reveal-meaning protocol core

This is the protocol-core dependency for
[mtg-kernel #543](https://github.com/jackmaiorino/mtg-kernel/issues/543), following
the independently reviewed kernel design at `a8c0df37ce267948254a45d474d9dfb52b0c2766`.
Both W1 AC5 soak jobs completed in collab commit `ec83ac0b`, with exit-zero
arena/report receipts and unchanged pins. The 4k-k1 fault bound failed and the
16k-k4 bound passed. Those results and entrants remain frozen; they do not
qualify this successor.

`spellbench.reveal_meaning_v3` defines an opt-in `x_reveal_meaning_v3` extension
whose batches contain complete atomic public operations. Each operation has
a contiguous viewer-local sequence and closed event objects. An arrival token
is its operation sequence and event position. It is never a native object ID.

An arrival must advertise either a continuously public transfer from a public
zone, with a known name, or an explicit public search-and-reveal outcome whose
name is supplied by a same-operation reveal. The adapter is responsible for
proving this public evidence before using the producer. The core does not
inspect an omniscient engine state and cannot certify an adapter's projection.
Known library transfers without an explicit search outcome are conservatively
unsupported here until their public evidence has a reviewed representation.

`moved` refines that operation's eligible arrival. `present` establishes a
name-level lower bound of one. Repeated delivery of the exact same operation
is idempotent; changed duplicates, stale or ambiguous links, owner/name changes,
unknown fields and anonymous-draw arrival evidence refuse atomically. An
unlinked presence claim may overlap named arrivals, so their lower bounds
combine by maximum. Named and unknown departures lower surviving constraints
without consulting hidden physical copies. A shuffle or loss of visible
correspondence expires same-operation links. Historical tokens cannot acquire
new bindings.

The producer/reducer tests check this protocol core for both owner seats,
repeated reveals, named arrivals, explicit search outcomes, invalid links,
departures and atomic rejection. They are not native two-world tests.

Remaining #543 work: event-time visible evidence in the kernel producer;
integration with the actual Spellbench adapter and schema validator; the
kernel reducer consuming the same stream; four reveal-class end-to-end and
paired-world tests; and exact frozen W1 byte-compatibility checks. No existing
engine or entrant imports this core, and this change alone does not lift R1
refusals or replace fallback D.
