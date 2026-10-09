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

## Carry forward separately authorized smoke debits

An explicit prospective amendment can also supply `debit_ledgers` to
`amend_idle_budget`. This imports settled charges into the same cumulative
allowance; it does not reopen the smoke budgets or add their caps. Copy each
sealed source into the mapped bundle, preserving its original bytes outside
the bundle. Use `sealed_debit_imports(..., model=budget.model,
forbidden_paths=debit_ancestry_paths(budget.path, budget.paths))` to obtain the
exact `debit_imports` list, and include that list in the authority JSON. The
authority's `user_authority` must explicitly authorize carrying those charges
forward. Existing limits may stay unchanged.

Each imported ledger must be independent, with no continuation, deadline
extension, successor or continuation-origin marker, no pending requests, and an
expired deadline or a terminal failure. Retain and inspect original sidecar
metadata before copying sources; removing a marker does not make a source
independent. The helper rejects
duplicate files and request overlap with another imported ledger, any primary
ancestor, or a previous import. It compares recorded request start time plus
prompt hash, and provider response IDs when available. Unknown usage retains
the entire original reservation. Failure counts remain historical charges;
they do not invent an active failure in the new successor.

The successor map retains each imported database by SHA-256. Every admission
rechecks its sealed contents, exact totals, independent request set and approved
scope. Later continuations inherit those charges once, and budget relocation
retains the imported evidence. Do not edit source databases, insert synthetic
request rows, reset allowances or copy credentials to perform consolidation.
Only apply the real amendment after the scoped human decision. An offline
synthetic fixture or prepared authority template is not that decision.
