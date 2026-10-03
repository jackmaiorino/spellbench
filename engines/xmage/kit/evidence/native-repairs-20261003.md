# Native kit repairs, 2026-10-03

Version 0.3.0 repairs the renamed-card reconstruction and slow-exit paths found
in the original soak. The frozen native benchmark passes complete-game
throughput qualification. Rated evaluation and publication remain unfinished.

The front retains only card names previously present in its seat's observations.
An unknown renamed nontoken can be rebuilt from that same object's earlier
observed name; its visible aura then reapplies the effect. The world carries
`approximate:renamed_object`. An unseen origin is never inferred from a deck,
a hidden hand, or another seat's history. Token substitution is refused.

Closing the front prevents later runner starts and forcibly ends its owned
runner, confirming exit within a bounded wait. Before the host's two-second
exit grace expires, the front can remove only the explicitly assigned
`kit-agent-*` directory under its launcher parent. It does not sweep siblings.
Linked directories and a mismatched parent are refused.
Windows file-handle release gets at most 900 ms of cleanup retries. An actual
launcher test first exposed that delay; its failed receipt is retained.

| Verification | Observed result |
|---|---|
| Existing core checks | 12 pass |
| Existing front checks | 16 pass |
| Existing termination checks | 5 pass |
| Rename history, real child shutdown and directory boundaries | 9 pass; stubborn child exit confirmed in 0 ms on this check |
| Real Witness Protection fixture through both front/runner pairs | 8 pass; priority and combat searches succeed; aura reapplies the name and 1/1 characteristics; late observer declines |
| Actual launcher startup, game end and EOF | Pass after the Windows retry fix; its temporary directory is gone and the sibling remains |
| Actual Windows junction | Cleanup refused; target retained |
| DraftZero priority fixture after the shared reconstruction repair | Bit-identical output SHA-256 `acd765676c2c1ad9ac64c17cfe091e9e7fc65f298a892ca196a83ef4e54d3611` |
| Supported launcher planning | Nine distinct native policies accepted; H1 plus its skill-6 alias refused |

The successful native build uses JDK 23.0.1 and the reviewed engine jar digest
`094733a77d5e5b9a6a881c104e7c70ea289f64e98a327c7a4b1937796025a0a8`.
The build now takes `jar` from the running pinned JDK; an initial attempt found
the older JDK 8 archiver on Windows PATH and failed before producing jars.

The source of record is the SHA-256-verified cold snapshot
`E:/spellbench-xmage-all-20261002/native-repairs-001/SEALED.json`
(SHA-256 `115e42417b72661fce0ed0787df99d1ed94d4d2a18bd987a27a64777e7ed3247`).
The owned hot job is its recovery copy. The snapshot retains `core-checks-002/`,
`recovery-check-001.jsonl`, `encoder-check-001/rename-check-004.jsonl` (passing
priority and combat), earlier failed check receipts, `agent-exit-check-002.json`
(passing), `agent-exit-check-001.json` (failed Windows file release),
`cleanup-link-check-001/REPORT.json`, and `native-kit-005/KIT-MANIFEST.json`.
Combat decisions and cached combat substeps now retain their world's approximation flags.
The snapshot records the input source commit, every copied file hash and the
final jars pinned in `E:/pinned-binaries/`. Tested class bytes match those jars.

The historical clock profiles and measurements are unchanged. A prospective
`kit-20261003` profile gives each decision 600 seconds, with the existing bank
and increment. It needs matched serial/parallel qualification and deterministic
game replay; it is not a passed fix for the old deadline-dependent replays.
Any rated benchmark using it must declare that clock and rerate its anchors.
No substantial evaluation was launched and no new rating is claimed.

The new native qualification job is registered at
`D:/e-scratch/spellbench-xmage-native-20261003-001` and
`E:/spellbench-xmage-native-20261003-001`, with a separate 16 GiB aggregate cap,
12 GiB projected peak and 60 GiB volume reserve. The supported qualifier is
contained by its own canonical Windows reservation and has a 90-minute bound.
No new paid allocation, GPU run or rated game is included.

| Attempt | Observed result |
|---|---|
| 001, generation 102 | Windows venv redirector and supervisor identity differed; qualifier did not start. Owned supervisor stopped and claim release confirmed. |
| 002, generation 103 | Preflight ran, then malformed placement text was refused; zero games. Owned children exited and claim released. |
| 003, generation 104 | All 24 serial games ended naturally, with zero validator violations. Report generation lacked `e4.py`; no parallel rung or allocation verdict. Owned children exited and claim released. |
| 004 | Prepared, unlaunched. Both report modules are present; empty and retained-game report generation pass. Exact completed rung timings are now checkpointed before reporting. |

Attempt 003 uses arena source `0e306267e87919ca71ea7f9ce2800918fa2eeba0`
and the unchanged native kit 005. Its manifest SHA-256 is
`404d7cae0965037ad5ccdd2bcf66ea6616ac497ac12b108aab6738930c7d4cdf`.
`RECOVERED-REPORT-003.json` has SHA-256
`5ccb0d59cbdd91e16902755dc040b17d29cfefcd130ba287f921a883d0eebabc`.
The original analysis modules are unchanged. The exact complete rung wall time
was not retained before reporting failed, so the restored report does not
claim a completed throughput measurement.

Prepared attempt 004 uses source
`b97a68fc9b1084e512afb6b1894dae4cf9b17af0`, archive SHA-256
`27da3dd5fc37d4616349a6b58a41951e7d0c8e68bb413f45b11d0528f5c314df`,
and manifest SHA-256
`7a21cd0436b7b4c1d00f5f12337ee7bdee49bc9fa794412e46cb95bf425d0d35`.
The plan, seeds, native inputs and clock are unchanged. It needs a fresh resource
check and its own claim before launch. The prospective `fdn-native-v1` rating
definition has a complete 11-entry round robin; it still needs its own guarded
qualification, complete paired results, replay and publication.

To avoid measuring the soak schedule and then measuring the different rating
schedule, `python/tools/xmage_native_benchmark_qualify.py` now calls the rating
benchmark's existing `bench.run.plan_for` guard directly. Its cache is keyed by
the full config, command file hashes, arena version, hardware and sampling
rules, exactly as the later benchmark launch. Two small fake-engine checks
confirm that changed definitions are refused and that a real later launch can
reuse the prepared evidence without creating a rated run. This is engineering
validation; the native benchmark remains unqualified. The Windows supervisor
also monitors the benchmark's actual completed trial ledgers.

Native qualification additionally requires natural completion and identical
substantial-run outputs across worker counts. Cached evidence must retain the
matching trial rows: their indices and canonical output digests are checked
against the allocation before reuse can certify native play. A small real
fake-engine test covers reuse and refuses it after its raw rows are missing.

Attempt 007, generation 113, refuses malformed placement separators before
starting games. Its 0.561-second failure and confirmed owned cleanup are
retained on D and reread on E; backup SHA-256 is
`5fd6d152d4c219626d7e6a0110025fc78d0985eaec0993f022a858464b42d3f5`.
The actual placement parser accepts the corrected descriptions. Attempt 008,
generation 114, started the frozen benchmark's serial rung through the same
supported guard. Manifest SHA-256 is
`90d96ad91536395b91a99dc6303cf4ad09ad9eb0f7eac930e7ed63c30e4bd6a2`;
preparation SHA-256 is
`e03cfb06391c861305c05a0e0c54365d625faf92613cf2f8117c9c787ea2c9a6`.
Fresh local, Haley and RunPod records are pinned in that preparation. Haley's
queued training priority and the separate gorge lease remain reserved. The
qualification has the original 90-minute, 16 GiB and 60 GiB reserve limits.
That attempt completed successfully in 2,599.317 seconds, released generation
114, and left no forced or remaining owned children. Its 48 measured games
all ended naturally. Each rung's 16 rows has the same primary store SHA-256,
`cf499e44ddcb3a6b98e04231fd040357c994258a90eff64a59bde84d71cef487`.

| Workers | Matched batch wall seconds | Completed game busy seconds |
|---|---:|---:|
| 1 | 985.455 | 985.205 |
| 4 | 734.585 | 1,126.712 |
| 8 | 727.849 | 1,504.446 |

The guard selects eight workers. The observed matched batch speedup over
serial is 1.354x; one long MCTS game dominates these heterogeneous batches.
The guard's completed-work projection for all 7,040 games is about 23 hours.
This projection is planning evidence, not a completed rating run.
The qualification report binds seven launch files, including the executable,
entry script, Java, card database, build manifest and agent launcher. Runtime
preparation additionally pins the engine and kit jars. The workload digest is
`sha256:82f762812a04deb9bf7d18ac517b5abdcaae9f7af96b6739ef12facdfbf185c6`.

Seventeen report, ledger, manifest and launcher files were copied and reread
in `E:/spellbench-xmage-native-20261003-001/qualification-001/`.
`CLOSURE.json` has SHA-256
`c11e1417c269dd2bc7de6f0361dce66d7bfe54f24801cd4ba9d67cc98c4631bf`;
the qualification report has SHA-256
`4656ff57c699c4d8d10f9c4950f7073da1858706ddf3118435e48dfe40dbf964`.
An additive `EVIDENCE-SUPPLEMENT.json` records the separately reread
`throughput-evidence.jsonl`, SHA-256
`0da4034618b6ed9830cdaad68b6f11a2cfa1c506b9015f3a0f683034edd19c0f`.
The sealed closure is unchanged. The full benchmark definition and public run
commitment still need the existing review and merge path before rated play;
the rated ledger, post-run replay and result publication do not yet exist.
