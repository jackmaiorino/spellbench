# Local gorge reference qualification and recovery

Local reference qualification uses the original `reference_matrix.py` schedule and
the supported `bench_run.plan_for` allocation guard. It requires a recovered full
320-block/640-game native pass before its bounded host parent creates inputs.
The reference result still requires 140 games, 60 policy/deck cells, 160 closed
native participant receipts and the preselected search/Burn replay. These games
are unrated and create no rated commitment.

The runner retains `PREFLIGHT.json`, the participant joins and per-rung
`MEASUREMENT.json` records. The existing qualification finalizer retains its
private replay secret only after cleanup. `gorge_local_reference_result.py`
checks the frozen configuration, production file hashes, native proof binding,
original seeds/seats/decks, participant lifecycle, mapping and search gates,
actual serial/parallel ledger bytes and allocation digests/timings, and the
original replay bytes. A report's pass flag alone cannot establish qualification.

After the owned reference parent exits and its canonical reservation releases,
recover it with `tools/gorge_recover_local_reference.py`. Supply the two reference
roots, two production runtime roots, two recovered native roots, their observed
seal/cleanup hashes, host-tool directory, lane and exact work ID. The tool refuses
live, unknown or foreign process ownership before writing receipts. It independently
checks both native recoveries and both reference copies, preserves failed
verification as a failure, and writes matching E/D terminal, recovery, seal and
cleanup records. It starts, stops and releases no process.

For prepared local reference099, the expected work ID is
`gorge-guarded-reference099` and lane is `spellbench-gorge`. Current native098 is
still running; reference099 has not been prepared or launched. Engineering
fixture tests establish checker behavior, not a full native/reference pass or
playing strength. The USD10 limit and current resource reservations remain binding.
