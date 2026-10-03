# E4 horizon threshold (written before the E4 measurement)

Design A0 revision 3, Section 9.1 E4: horizon and truncation counts are measured on S1 to S9 and both DraftZero
positions against a threshold written into the slice plan before measuring. Committed 2026-10-01, before the E4
measurement run (`kit/evidence/e4-horizon.json`). One incidental reading came earlier: the S7 (e) H3 searches on the
cantrip position, at the debugging rollout cap of 400 priority callbacks, truncated 50 and 55 of 60 rollouts. That
reading is why the H3 clause below names its cap.

Thresholds:

1. MAD horizon (design 5.6). Per priority anchor whose stack holds a flagged (approximate) object: if more than 25% of
   that decision's evaluated root alternatives end at the horizon (`horizon:mad` counted against root alternatives),
   the stack-object kind (the flag's cause: `stack_ability_identity`, `stack_source_ambiguous`,
   `stack_placeholder`, `stack_source_recreated`) moves to "approximate without search": the kit answers such
   decisions with its declining candidate, tagged wrapper, and the register lists the kind as approximate.
2. MCTS truncation. Truncated rollouts (horizon or rollout cap) above 50% of completed iterations at the H3 entry's
   rollout cap mean the search is not meaningful at that cap: either the cap rises (cost measured) or H3 stays
   unadmitted. Horizon-only truncations above 25% move the kind as in clause 1.
3. Pending triggers dropped (`approximate:pending_triggers_dropped`): above 10% of priority anchors in the slice's
   game set, pending-trigger rebuild becomes A1 build-out work before the soak.
