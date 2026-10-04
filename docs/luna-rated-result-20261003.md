# GPT-6 Luna: complete rated panel, 2026-10-03

The publicly committed unchanged 48-game panel completed with all 32 Luna games and 24 complete seat-swapped pairs. The supported validator passes on Linux and Windows, and the static site build selects this complete rated run. A fresh read-only result reviewer verified the ledger, pair swaps, ratings, file hashes and cumulative allowance before publication.

| Luna matchup | Wins | Paired bootstrap 95% score interval |
| --- | ---: | ---: |
| All opponents | 23/32 | See anchored rating interval below |
| heuristic | 9/16 (56.25%) | 37.5% to 75% |
| uniform | 14/16 (87.5%) | 68.75% to 100% |

Luna's anchored Elo is **1292.6**, with a paired bootstrap 95% interval of **1163.0 to 1476.2** (uniform fixed at 1000, 2,000 resamples). Its first-place rank describes this panel. The heuristic comparison has a paired sign-test p-value of 1.0 and does not establish superiority. This two-deck mirror panel does not establish competitive Standard or wider metagame strength. Hosted model outputs can vary.

There were 47 natural finishes and one rated forfeit. In game 22, Luna had consumed 716,475 tokens in 103 calls. Its next prompt (33,449 bytes) plus the fixed 1,024-token reservation would bring admission accounting to 750,948, above the unchanged 750,000 per-game cap. The child refused before another provider call; `unknown_usage:false`. This local cap refusal is the recorded generic agent-error forfeit. It remains in the ledger and ratings.

Cumulative accounting is **3,914 of 5,000 requests** and **17,201,695 of 20,000,000 accounted tokens**, including every earlier debit, seven inherited unknown requests, 59,355 uncertain tokens and three inherited host failures. There are zero pending or new failed/unknown requests. Fresh qualification used 60 calls and the formal panel used 1,550. Inflight cap 4 and the absence of an overall benchmark cutoff remain unchanged. The prior 2026-10-02-3 attempt remains aborted and unrated; no prefix is composed into this run.

Source `205fba24d4cbbd83ccd43c91b840b396aec7f865`, engine `004913a4fd8e2455f8dfcbcd73a15c568a56bcc2`. Public commitment [PR71](https://github.com/jackmaiorino/spellbench/pull/71) merged at 07:46:31 UTC, before the supported guarded formal launch at 08:19:13 UTC; it completed exit 0 at 10:48:29 UTC. The fresh qualified cloud allocation reused exact throughput evidence. Its recorded engine replay matched 408/408 exchanges byte-for-byte with zero model calls. The manifest explicitly records **unsandboxed, self-reported isolation**; this run uses the trusted child adapter without OS confinement.

RunPod CPU3g2/8 ran at USD0.08/hour on the existing volume, under its approved fixed four-hour lease. Pod842qs8tfojssm7 is confirmed EXITED at 11:01:26 UTC, before the 11:20:39 hard release. Its guardian was disabled only after this confirmation. The rotating profile was separately recovered into an owner-protected Windows DPAPI backup, with no credentials in the archive or Git.

Source of record: `E:/spellbench-luna-approved-evidence-20261003/sealed-formal-attempt-001/`, with an independent retained copy on network volumehzaciff5xy. The 113,261,345-byte sealed archive contains 533 indexed files (332,598,096 logical bytes); all indexed sizes and SHA-256s matched the independent cold copy. Earlier failure/abort evidence is retained. No evidence is pruned.

| Artifact | SHA-256 |
| --- | --- |
| manifest.json | `1f7970dcbae47ccdaa849de8e10d839be1c32b0e724af86b5fbe121384623680` |
| matches.jsonl | `750c955bb4fff5331e661703cce5f4fa7ce552c100dc32bbcc4549ddd1b2adfb` |
| leaderboard.json | `92633dcbeb64a714539a476630c0671529b0e947606308a1623e74dc0e1c20c7` |
| cold evidence.tar.gz | `1226127c3cf371cda0388ead601750f81001a079274760670846c483ebceac34` |
| cold INDEX.json | `cbfc9a92dceca669a4022fec55e5d2c5aa0a0ddbfde16f3c012e3c7e63a95436` |

[Full leaderboard](../benchmarks/standard-mirror-xmage/runs/2026-10-03/LEADERBOARD.md), [saved manifest](../benchmarks/standard-mirror-xmage/runs/2026-10-03/manifest.json).
