# Guarded XMage rated execution

The native job controller supports `execution_kind: rated_benchmark` for the normal committed benchmark runner. This is execution wiring. It does not qualify an agent, authorize a new allocation, or establish a published rating.

Prepare the complete benchmark and qualify its serial/parallel completed-work throughput with the supported launcher. Publish a fresh commitment through `bench commit` on an owned review branch and integrate that commitment before play. Keep the secret outside every Git worktree. The historical aborted FDN commitment stays disclosed and is never reused.

The job manifest sets `execution_kind` to `rated_benchmark` and `qualification_only` to `false`. The hash-pinned preparation sets the same execution kind, `qualification_kind: benchmark`, the unchanged benchmark path/hash, and `execution_entrypoint` with the owned `xmage_native_benchmark_rated.py` path and SHA-256. Its command uses the manifest's pinned base Python interpreter:

```text
python xmage_native_benchmark_rated.py --benchmark BENCHMARK_DIR --benchmark-sha256 SHA256 --run RUN_NAME --proof PUBLIC_TIMESTAMP --out BENCHMARK_DIR/runs/RUN_NAME --host-guard host_reservation_v1.py --host-work-id WORK_ID
```

Dispatch through `xmage_native_qualified_job.py` using the frozen job manifest and its SHA-256. Preserve the current canonical reservation, owned containment, declared window, projected storage cap, volume reserve, STOP handling and child cleanup. The rated entrypoint refuses a raw call outside the declared production job. It delegates commitment, definition, once-only secret/lock, throughput, pinned-input and result-validation checks to `bench.run.run_benchmark`.

Rated monitoring counts new rows of that run's `matches.jsonl`. It does not count qualification trials. The completion report requires the full scheduled game count, a complete rated manifest and no validation failures; it reports rated, halted, truncated and forfeited games separately. Replay and public site delivery remain separate required steps. A controller exit alone does not prove either.

On interruption or refusal, retain the commitment, logs, partial ledger and terminal state. The normal benchmark runner reveals failures it can finalize. If the outer guard must terminate its process, inspect and close that same attempt after confirmed owned cleanup; publish its required reveal before preparing another identity. Never restart a started commitment because its process stopped.

Existing manifests without `execution_kind` remain qualification-only. Completed frozen qualification artifacts and launchers are unchanged. Prepare a new manifest when adopting a changed controller or workload, and let the normal throughput guard determine whether retained evidence is compatible.

## Sharing the host by core

A manifest may declare `cores` (for example `"0-15"`) together with `host_slots`, the path and SHA-256 of a pinned `host_slots_v1.py`. The worker then runs the pinned command under `host_slots_v1.py timed --cores SPEC`, so untimed work and CI can use the other cores. The busy refusal then ignores a `java`, `bo3_*`, `native_*` or `mtg_kernel*` process only when its CPU affinity is readable and lies entirely outside the declared cores. Overlapping, unpinned and unreadable processes still refuse the launch. Without `cores`, the whole host is reserved and every name match refuses, as before. Declaring cores changes a run's execution: qualify with the same declaration under the same background load before a commitment names it.
