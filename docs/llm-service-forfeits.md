# Hosted service availability

`--allow-http503-forfeits` is an explicit prospective policy. The hosted command
and budget must both select it. It changes only a durably settled provider
`http_503` failure: that game forfeits and a fresh broker may serve the next
scheduled game. The failed request is never retried. Its complete uncertain
reservation stays charged against the cumulative budget. Defaults remain
terminal for HTTP503, and all other HTTP failures remain terminal.

Logging, child protocol, choice validation, authentication, renewal, cleanup,
accounting and abandoned pending requests still stop the evaluation, including
errors occurring after a provider503. A failed broker cannot infer or renew
again. Report HTTP503 forfeits separately and include them in declared scores;
this evaluates the system with its service availability. Shortened games do
not establish reduced inference cost or representative completed-work speed.

`--allow-provider-failure-forfeits` (budget schema `spellbench-llm-run-budget/v5`)
widens the same rule to any durably settled provider failure code, for example
`inference_failed` or `http_429`. Budget-owned `run_budget_*` failures, such as a
returned model mismatch, stay terminal. Each forfeited request still counts, and
unknown usage keeps its full reservation charged, so the request and token caps
still bound the run. A persistent provider fault now forfeits games one by one
until a cap stops admission, so watch the `active_provider_failure_forfeits`
summary count. Continuations, transfers and recoveries keep this policy exactly,
with one exception: `increase_failed_run_limits(..., enable_provider_failure_forfeits=True)`
may enable it once on a failed parent without it, when the limit-increase authority
also records `"enable_provider_failure_forfeits": true`. The successor's
continuation records the enable; nothing can remove the policy.

A failure receipt's retained run may also be the `REVEAL.json` of a committed run
that aborted before publishing any game (`spellbench-run-reveal/v1`, status
`aborted`, exactly the reveal fields). Its hash binds as `retained_run_sha256`.

`continue_stopped_qualification` supports one exclusive mapped successor for a
stopped **precommit** qualification whose sole new terminal request is HTTP503.
It requires a retained `spellbench-llm-stopped-qualification/v1` receipt binding
the actual source, failed row, dispatch, completion and original map hashes, limits,
cutoff, absent processes and absence of a formal commitment. Every request,
known token, failed/unknown count, uncertain reservation and host failure is
inherited. Failed parent bytes remain unchanged; its exclusive claim retires
admission before the successor map is published. Fresh outputs, including
initial snapshot and origin, cannot replace earlier evidence.

This is neither a formal-run recovery nor a fabricated aborted tournament.
Do not resume the stopped game. Use a distinct prepared source and new supported
qualification identity, reconcile usage forecasts using representative games,
then complete the independent design and public commitment gates. Recovery
does not increase caps, remove a finite cutoff or authorize a formal run.
