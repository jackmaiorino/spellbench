# X5 summary reporting repair

The reviewed engine from `004913a4fd8e2455f8dfcbcd73a15c568a56bcc2` completed the unchanged 10,112-game plan on the bounded RunPod CPU lease. All games ended naturally, with zero validator violations and no host halts. All 1,011 selected identity-hash-mode replays matched, with no missing or unexpected IDs. The final summary command then failed while writing its verdict: `store.write_json_atomic` rejects floating-point rates, means and medians, which this diagnostic report intentionally contains.

The repair writes the complete diagnostic report, including its verdict, once through the existing atomic byte writer. Ordinary JSON rejects non-finite numbers. Protocol, tournament and rated artifacts retain their existing canonical integer-only writer. The complete-ID, mismatch, violation and natural-ending criteria are unchanged.

Two regressions use real small host ledger rows: a complete natural panel writes floating-point diagnostics with `PASS` and returns zero; an incomplete panel writes `FAIL` and returns one. Local tests remain deferred during CLAIM #808. CI checks and source review are pending.

The original failed summary, completion record, logs, rows, stats, source and engine binaries remain preserved on network volume `hzaciff5xy`; the pod is confirmed stopped. Re-analysis will use the repaired summary command on those same immutable rows and stats, writing a new report and a separate verification manifest. The original failure record will not be overwritten. No game, seed, engine binary, result criterion or replay selection is changed or rerun.

This is engine verification for the Luna entry, with no model calls or rating. Issue #23 also lists golden and paired-world checks whose committed evidence predates this build; the panel/replay alone does not close that broader issue. The live Luna path still needs qualification, recorded-choice host/engine replay, a public commitment, the fixed rated schedule and verified Pages publication.
