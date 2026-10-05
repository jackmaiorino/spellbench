# Local native recovery before reference admission

`tools/gorge_native_gate.py` accepts an independently recovered, sealed full
native audit from hosted Linux or local Windows. Both paths retain the original
320-block/640-game completion, natural seed order, fault, mapping, search,
redeal, matched throughput and canonical output checks. Component fixtures
and partial attempts do not admit reference collection.

For local Windows, retain the actual `native/` directory. Its full audit,
manifest, allocation, parent `RECEIPT.json`, callback report, callback receipt
and primary store must be sealed. Also seal the parent's root `CLOSURE.json`,
`RECOVERY.json`, `LOCAL-TERMINAL.json` and `HOST-RELEASE.json` only after the
owned attempt is terminal and its independent E/D recovery is verified.

`LOCAL-TERMINAL.json` records `status: completed`, the actual `exit_code` and
`stop_reason`, `head_sha` matching the execution manifest, and
`execution_kind: local-windows-amd64`. Its `execution_id` contains the actual
canonical `host`, `lane: spellbench-gorge`, `work_id` and positive `generation`.
The same identity binds recovery, host release and cleanup receipts. Local
recovery declares no GitHub run ID or CI success.

`HOST-RELEASE.json` requires an observed canonical `token_fate: released` and
`outcome: success`. Its nonempty `processes` object records each captured owned
PID, process creation time and observed `state: absent`. It also records empty
`live_descendants` and `observation_errors`. Unknown process state, live
descendants, reclaimed ownership or a mismatched generation refuses admission.
Capture this evidence from the canonical host module after the existing
supervisor releases; a missing lock alone does not prove this attempt released.
Keep reservation tokens out of portable receipts and Git.

`RECOVERY.json` binds the execution identity and `launcher_source_commit`,
declares the actual `native_qualification_passed`,
`independent_recovery_verified` and `rated_games: 0`. After the sealed E/D
inventory has been compared, write an identical external `LOCAL-CLEANUP.json`
in both roots with `recovery_seal_sha256`, `execution_id`,
`host_release_verified` and `independent_recovery_verified`. The caller pins
this receipt's SHA-256 separately from the recovery seal.

The production seal binds the actual Windows qualifier and registry used by
the audit. A portable reference bundle preserves that Windows qualifier's
identity alongside the Linux engine and agent from the sealed build. It does
not relabel the audit as Linux evidence. The Linux reference processes still
require the actual 140-game reference matrix, 60 cells, 160 native participant
receipts, clocks, cleanup and preselected replay before rated admission.

Native077 is currently active, unsealed and unqualified. Its existing bounded
parent owns completion, recovery and canonical release. This receipt format
adds no launch, rerun, paid allocation or admission for that unfinished job.
