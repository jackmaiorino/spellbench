# Native kit repairs, 2026-10-03

Version 0.3.0 repairs the renamed-card reconstruction and slow-exit paths found
in the original soak. It remains unqualified and unrated.

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

Evidence currently belongs to the owned job
`D:/e-scratch/spellbench-xmage-all-20261002`: `core-checks-002/`,
`recovery-check-001.jsonl`, `encoder-check-001/rename-check-004.jsonl` (passing
priority and combat), earlier failed check receipts, `agent-exit-check-002.json`
(passing), `agent-exit-check-001.json` (failed Windows file release),
`cleanup-link-check-001/REPORT.json`, and `native-kit-005/KIT-MANIFEST.json`.
Combat decisions and cached combat substeps now retain their world's approximation flags.
The immutable cold snapshot records their
hashes after this slice is committed.

The historical clock profiles and measurements are unchanged. A prospective
`kit-20261003` profile gives each decision 600 seconds, with the existing bank
and increment. It needs matched serial/parallel qualification and deterministic
game replay; it is not a passed fix for the old deadline-dependent replays.
Any rated benchmark using it must declare that clock and rerate its anchors.
No substantial evaluation was launched and no new rating is claimed.
