# Luna integration review, October 1

Jack authorized review in this chat or fresh subagents, and authorized the necessary merges. Three independent read-only Codex subagents reviewed the protocol foundation/release, LLM stack, and engine source. Their actual model identifiers were unavailable, so no specific model is claimed. None ran tests, read account credentials or ran inference.

The protocol reviewer found no blocking source defect. Actual qualification, a public commitment, complete validated measurement and the deployed row remain necessary. The fixed 48-game schedule and its stochastic-output rules remain unchanged.

LLM findings and disposition:

| Finding | Disposition |
| --- | --- |
| Ordinary parallel profile-lock contention terminates the run | Accepted. Hosted renewal waits and reloads under the lock; sign-in remains immediate. A host authorization child bounds the entire exchange, including slow reads, at 40 seconds. Failure is recorded before unlocking, and waiters check shared failure. |
| Recorded pins were not checked by the process launcher | Accepted. Qualification and workers receive the same hashes; originals are checked before launches, after games and before publication. An input change cannot publish a rating, including after the final row. |
| 120-second freshness can expire during ordinary play | Accepted. Require 1,800 seconds. The observed grant lasts 3,600 seconds. This practical margin does not guarantee unusually long games; expiry remains terminal. No mid-game renewal or inference retry. |
| Java expands undeclared uppercase `.JAR` files | Accepted. Reject those archives without changing the frozen wildcard ordering. |

Engine findings: concealed exile names affect public ordering; resumed IDs are accepted without build/plan binding; the direct run command bypasses qualification/reserve enforcement; replay comparison permits partial intersections and the shell suppresses failure. These require source repairs and new final build verification before rated execution. Preserve prior corrected partial evidence and failed old-build replay. The existing staged corrected build is preparation, not approval for a future repaired engine.

Source regressions cover real process lock waiting, timeout, horizon/short grants, failure ordering, changed inputs at launch and after the final game, and uppercase archives. The reviewer found no material remaining source blocker at `8d12a1c`. The hard authorization-child deadline is 40 seconds; SQLite check/failure errors can add two waits, so there is no universal 55-second total claim. Ledger unavailability remains terminal. Both transport jobs and the actual-container check passed at that head. The Linux full suite found an outdated cleanup-test wrapper missing the new launch-file keyword; that wrapper is repaired here. Current repaired-head full results remain pending. The prior full suites at `6d21a83` passed on Linux and Windows. No Luna rating is claimed.
