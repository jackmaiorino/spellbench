# Gorge compute host native requalification (2026-10-07)

Unrated native audits of the non-redeal gorge modes on the compute host, after the
native129 reconstruction repairs (PR #155, 9c5fb5d). Zero rated games, zero
cloud spend. The maintainer then chose (02:13Z) to rate gorge bots only on the
pauper-kernel-v2 board, so no pauper-gorge reference matrix, roster change or
rated run followed.

## Runtime

Runtime130 was built locally under the canonical primary desktop reservation (generation 308)
from 0be859f with the native121 recipe (go1.27.1, `-trimpath`), after the rules,
searchprobe and strategies public replay tests passed. Its compiled Go is
identical to 9c5fb5d; the only engine-tree change is that
`qualify_native.py` passes `gorgequal -policies` for an explicit subset.
Seal `2f92a15a…` at `E:/spellbench-gorge-runtime-20261007-130` (D:/e-scratch copy).

## Native audits

Both ran under the compute host canonical lock at BelowNormal priority with an 8-worker
cap; the supported 1/4/8 ladder selected 8 workers with identical primary rows.
Both completed every block with zero halts, truncations, violations, digest
mismatches, leaks, inconsistencies, resample failures or parity mismatches, and
every mapping gate passed. Both failed only the existing search-coverage gate
(eligible and covered native search per deck), so neither is a native pass.

| Run | Modes | Blocks | Ladder 1/4/8 (s) | Search cells with zero covered decisions |
|---|---|---|---|---|
| native134 | 8 non-search + search + search-mana | 280 | 745 / 235 / 146 | search on Wildfire, Spy, CawGates |
| native139 | 8 non-search + search-mana | 240 | 1129 / 375 / 277 | search-mana on CawGates |

Every failed search attempt ended in `insufficient worlds/ESS` or
`fewer_than_two_candidates`; there were no reconstruction exhaustions. Search-mana
covered one CawGates decision in native134 and none in native139, so its coverage
on that deck is marginal rather than broken. The eight non-search modes passed
every deck in both runs.

| Run | Root (E: and D:/e-scratch) | Source | Seal | Cleanup |
|---|---|---|---|---|
| native132 | `spellbench-gorge-native-20261007-132` | 251f317 | failed launch, no games | none |
| native134 | `spellbench-gorge-native-20261007-134` | b62aa56 | `8e9ca5d1…` | `19450b06…` |
| native139 | `spellbench-gorge-native-20261007-139` | f5f2c2f | `4cf5cc67…` | `d17830bd…` |

Native132 exited before any game because its priority call passed a truncated
process handle; it released its lock and is kept as a failed-attempt record.

## Code

- `qualify_native.py` and `tools/gorge_native_gate.py` accept an explicit,
  ordered policy subset declared before launch; the full roster is unchanged.
- `tools/gorge_reference_selection.py` and the local reference checks can
  restrict the frozen matrix to natively qualified modes. They are tested but
  unused after the maintainer's decision.
