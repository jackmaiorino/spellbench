# Original Jack combat wiring

The private April callback at `750b3ff88c98f00a0d3218a54c16198b69b8a24c`
has SHA-256 `b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6`.
The optional `combat_callback` stage extracts its actual attack/block loops,
blocker filtering and attacker enumeration. Only inference/selection transport,
training records, game logging and exception fallback change. Private source
bytes remain outside this repository.

The port retains original candidate order and 64 slots, attack/block head
mapping, DONE-last multi-selection, separate defender selection, descending
attacker power ordering, blocker removal and `resetPassed`. The original chooser
draws the complete permutation before the callback stops at DONE. Both combat
phases retain the same cached permitted base state. Physical card-copy RNG is
unused. Unexpected nested combat callbacks refuse.

Actual private-source staging creates sixteen bodies. All fifteen earlier
staged bodies remain byte-identical. The combat body SHA-256 is
`b6c6e060dad08833e3044de049f001c0bf1be5b1be781e951bd7c883041f5f64`.
The private manifest is `jack-backend-inputs-001/INPUTS-012.json` and the staged
source is `jack-combat-wiring-001/private-sources/CombatRules.java` beneath the
owned XMage evidence root. These records prove staging, not Java execution.

Python component checks exercise the full sequential draw after DONE, separate
defender rounds, shared clocks, original head/mask/padding, stale request and
round IDs, observed-choice receipts, returned-plan binding, cached base state,
source readiness and owned cleanup. Existing Exp1 combat plans keep their search
validation; Jack uses its own original multi-selection receipts.

Guarded native combat, actual paired-weight combat inference, exact checkpoint
deck associations, the complete Jack frontend, full games, throughput
qualification, ratings and publication remain unfinished.
