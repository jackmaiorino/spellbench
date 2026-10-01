# Change 8: qualification and soak (prepared, not run)

`kitrun.py` plays the kit entries through P's host on `fdn-mirror-v0`'s pool (the sixteen FDN decks, mirrors,
seat-swapped pairs) and enforces the third review's change 8 criteria; `launch.sh` holds the per-machine commands.

| Step | What it does | Guard |
|---|---|---|
| `plan` | one shared plan: each admitted entry against `heuristic` and `uniform` (256 pairs each, 1,024 games per entry), the declared cross-entry games (kit-mad-1 against kit-mad-k, 64 pairs), the clock profile, entry identities and public descriptions, a master secret | refuses decks the register does not admit, custom identities, and kit-mcts without `--allow-mcts` |
| `qualify` | P's `plan_allocation`: one worker, then the ladder up to the cap, on identical games sampled across the schedule; game digests compared across worker counts; per rung the kit's decision tails, combat search costs, bank use per game, cap firings (combat attack and block separately), restarts, wrapper and cap rates, E4, leftover agent directories | P's disk reserve (60 GiB on the run and pin volumes) and placement record |
| `run` | the soak with the qualified worker count, per machine share | refuses without `QUALIFICATION.json` for this plan, engine build, kit jars, entries, clock and P commit on this host; a substantial run needs identical outputs across worker counts; the reserve is checked again before the first game |
| `replay` | R-1: twenty games spread over the run, replayed serially, digests compared | the same guard |
| `summarize` | `SOAK-SUMMARY.json`: zero `invalid_selection` and `malformed_response`, no live-validator violation, complete schedule, coverage per deck and seat, non-natural endings with diagnostics, per-game isolation, wrapper and cap rates by kind and mechanic, E4 over all MAD and MCTS work, decision tails and bank use | |

Per-game isolation: every kit seat is a fresh agent process per game (front and runner in a private temporary
directory with its own database copy, removed on exit); leftovers are recorded and then removed. Each kit seat
writes its own log (`--log-dir`: `<game_id>-<seat>.jsonl`).

Open choice for the coordinator: the clock profile. The default is the staged benchmark's (`fdn-mirror-v0`: 30 s
per decision, 600 s bank, 2 s increment, 60 s game start, 180 s startup); `--clock kit` is the smoke profile
(120 s, 3,600 s, 2 s, 300 s, 300 s) proposed for kit-mcts. kit-mad-k's slowest decisions in the smoke games were 70
and 87 s, so under 30 s some of its searches end at the runner's safety deadline (tagged `cap`); qualification
measures how often.
