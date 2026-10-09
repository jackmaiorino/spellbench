# Bounded stages within a cumulative allowance

A qualification may have a smaller authorized request/token allowance than the
cumulative ledger. Optional hosted flags `--admission-scope PATH` and
`--admission-scope-sha256 SHA256` enforce that smaller stage without changing
the ledger policy, resetting charges or granting more cumulative allowance.
The ordinary hosted launch guard forwards and checks both flags.

The UTF-8 JSON scope uses `spellbench-llm-admission-scope/v1` and exactly these
fields: `schema`, `model`, `budget` (the mapped logical active ledger path),
`budget_map_sha256`, `baseline_requests`, `baseline_accounted_tokens`,
`max_additional_requests`, `max_additional_tokens` and `user_authority`.
Both additional limits must be positive integers. The baseline must equal the
immutable mapped initial snapshot's accounting, including inherited and
imported debits and every unknown usage reservation. Retain the actual scoped
human decision as authority; a template is not authorization.

Every reservation rechecks the scope hash and binding under the existing
SQLite admission lock. The effective ceiling is the smaller of the cumulative
cap and baseline plus stage allowance. All pending request reservations consume
that ceiling. Failed calls with unknown usage retain their full reservation.
Restarting a broker neither changes the baseline nor restores spent allowance.
Scope exhaustion refuses before a provider call, stops qualification through
the ordinary hosted-budget guard and does not mark the broader cumulative pool
failed. Logging, child transport and integrity failures retain their existing
failure behavior; already admitted calls can still settle their actual usage.

For the authorized prospective Luna stage, the baseline is 4,837 requests /
31,136,214 accounted tokens and the additional ceilings are 4,096 requests /
12,000,000 tokens. Cumulative caps remain 27,000 requests / 180,000,000 tokens,
four inflight; per-game limits remain 256 calls / 750,000 tokens. Separately
bound the qualification controller to at most 16 Luna games, including at most
one optional serial consistency rung, and call only supported `bench.run.plan_for`.
Stop after the planner returns or fails. This scope does not authorize formal
evaluation, a public commitment, paid hosts, GPUs or a changed frozen board.
