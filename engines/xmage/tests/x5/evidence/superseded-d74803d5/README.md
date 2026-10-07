# Superseded: X5 run on build `d74803d5`

History only. Main's reviewed build of `004913a` (lib digest `094733a7`) replaces this build; its X5 is in
`docs/llm-engine-verification-20261002.json`.

Build `d74803d5` was made on branch `xmage-x0-x1` (commit `71e32fc`), before Codex's privacy and provenance repair.
It ran the unchanged 10,112-game plan (`../../plan.json`) in three stretches through P's guard: 3,544 games on
The compute host (6 workers), then 6,568 on the primary desktop (12 workers). All games natural, 0 validator violations over 5,976,799
decisions, 0 halts, 0 truncations. Its identity-hash recheck stopped at 713 of 1,011 games, all equal.

| File | Content |
|---|---|
| `final2-summary.json` | per pool and workload: endings, attribution, decision kinds, engine counters |
| `final2-games.tsv.gz` | every game: machine, workload, ending, steps, game digest |
| `final2-hash-games.tsv.gz`, `final2-hash-determinism-partial.json` | the 713 rechecked games and their comparison |
| `allocation-final2-main-pc.json` | P's guard record on the primary desktop (the compute host's is `../allocation-computehost.json`) |
