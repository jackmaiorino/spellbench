# Prospective budget amendment

`amend_idle_budget` in `spellbench.llm.budget_transfer` supports an explicitly
authorized request/token cap increase between evaluation phases. Stop the source
controllers first. The source must be mapped, sealed, healthy and have no pending
requests. Failed runs continue to use their separate recovery procedure.

The authority JSON uses `spellbench-llm-idle-budget-amendment/v1` and binds the
model, logical parent path, parent SHA-256, exact parent and approved limits,
boolean `no_cutoff`, `purpose: precommit-evaluation` and the explicit human
authorization in `user_authority`. Only `max_requests` and `max_reported_tokens`
may increase. Inflight limits, request settings, original timestamps and timeout
forfeit policy stay unchanged. An approved `no_cutoff: true` removes only the
overall deadline. Request timeouts, token reservations and every prior debit
remain enforced.

The caller supplies fresh successor and map paths in the existing bundle. A
SQLite admission lock and exclusive retirement claim select one successor.
The original database stays byte-identical; its accounting is inherited, with
the original transfer anchor and authority retained and rechecked on admission.
An interruption preserves partial evidence and cannot activate a second writer.
Never recreate or reset a ledger to apply the amendment.

The changed allowance forms a new qualification identity. Prepare and fingerprint
the actual source and evaluation inputs before qualifying the next phase. A
successful amendment alone is neither qualification nor formal launch authority.
