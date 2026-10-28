# Human play client: state at pause (2026-10-28 evening)

Paused at the coordinator's direction (program focus moved to the Spy combo). Remove this file before the PR.

## Works
- `python/spellbench/human/`: relay agent (`relay.py`), play server (`server.py`), keyboard page (`page.html`),
  card-named log text (`text.py`), session launcher (`session.py`, `python -m spellbench.human`).
- `python/tools/human_session.ps1`: one-command launcher, optionally inside a host_slots claim.
- Machine wrapper outside the repo: `D:\e-scratch\human-anchor-20261028\play.ps1` (Jack's paths, b512, 16 games).
- `python/tests/test_human_client.py`: 8 tests pass, including a full fake-engine game through the relay.
- Checked by hand in a browser against the fake engine: start, number keys, auto-pass to next main, end screen, N.

## Left
1. Live test against b512 on the real kernel engine (never ran: host_slots queue). Command, from the worktree:
   `python -B D:/mtg-ci/hooks/host_slots_v1.py run --lane human-client --work-id smoke1 --cores 2 --wait --cwd python -- D:/e-scratch/sb-throughput-20261019/inputs/py/source/.venv/Scripts/python.exe -u -m spellbench.human --games 2 --decks Burn --local D:/spellbench-wt/claude-oh1-parent-20261022/benchmarks/local.json --out D:/e-scratch/human-anchor-20261028/test1 --name smoke1 --port 8766 --no-browser`
   then drive it with `python python/tests/human_autoplay.py "<printed URL>" --games 2`, then one game by hand in the browser.
   Check: ledger rows, both decision logs, engine record size per game (cap 128 MiB; the flat tensor may be large).
2. Misplay viewer request (local_c3e93484): put b512's `--decision-log` and the human log in one directory
   (today `decision-logs/oh2-r2s1-b512` and `decision-logs/human`), and either keep the operator engine recording
   (its engine.jsonl works) or wrap the engine with `misplay_review/engine_tap.py --out TAPDIR -- <engine cmd>`.
   Suggested dirs: `D:/e-scratch/misplay-review-20261028/human/{decisions,tap}`.
3. Point `play.ps1` at a merged-main checkout, open the spellbench PR (body draft: D:/e-scratch/human-anchor-20261028/pr-body-draft.md),
   review, merge on green, send the launch command to the coordinator.
