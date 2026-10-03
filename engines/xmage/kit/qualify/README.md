# Change 8: qualification and soak (ran 2026-10-02, results in `../evidence/README.md`)

`kitrun.py` plays the kit entries through P's host on `fdn-mirror-v0`'s pool (the sixteen FDN decks, mirrors,
seat-swapped pairs) and enforces the third review's change 8 criteria; `launch.sh` holds the per-machine commands.

Qualification accepts `--storage-cap-bytes` to record a declared output cap in
the allocation guard. `completed-games.jsonl` flushes each finished game's row,
digest and elapsed time while a rung is running. `qualify-games.jsonl` retains
the deterministic order used for the completed serial/parallel comparison.
An interrupted rung is unfinished; its completed-game log is retained.

`python/tools/xmage_native_qualified_job.py` wraps the supported qualifier in a
hash-pinned Windows host-reservation helper. Its job manifest binds a frozen
runtime and input hashes, an aggregate storage cap, reserve and time window.
It acquires its own canonical claim, performs the busy refusal before dispatch,
and supervises only its contained children. STOP, timeout or storage failure
closes those children by PID and creation time. Forced cleanup after a nominal
successful qualifier is reported as a failure. It creates no cloud allocation.

| Step | What it does | Guard |
|---|---|---|
| `plan` | one shared plan: each admitted entry against `heuristic` and `uniform` (256 pairs each, 1,024 games per entry), the declared cross-entry games (kit-mad-1 against kit-mad-k, 64 pairs), the clock profile, entry identities and public descriptions, a master secret | refuses decks the register does not admit, custom identities, and kit-mcts without `--allow-mcts` |
| `qualify` | P's `plan_allocation`: one worker, then the ladder up to the cap, on identical games sampled across the schedule; game digests compared across worker counts; per rung the kit's decision tails, combat search costs, bank use per game, cap firings (combat attack and block separately), restarts, wrapper and cap rates, E4, leftover agent directories | P's disk reserve (60 GiB on the run and pin volumes) and placement record |
| `run` | the soak with the qualified worker count, per machine share | refuses without `QUALIFICATION.json` for this plan, engine build, kit jars, entries, clock and P commit on this host; a substantial run needs identical outputs across worker counts; the reserve is checked again before the first game |
| `run` options | `LIMIT` and `TAIL` take the first or last N remaining games of the part, `SKIP_ROWS` another machine's rows: a rebalanced tail with no game played twice | |
| `replay` | R-1: twenty games spread over the run, replayed serially, digests compared (`GAME_IDS`: chosen games instead, `REPLAY-SELECTED.json`) | the same guard |
| `summarize` | `SOAK-SUMMARY.json`: zero `invalid_selection` and `malformed_response`, no live-validator violation, complete schedule, coverage per deck and seat, non-natural endings with diagnostics, per-game isolation, wrapper and cap rates by kind and mechanic, E4 over all MAD and MCTS work, decision tails and bank use | |

Per-game isolation: every kit seat is a fresh agent process per game (front and runner in a private temporary
directory with its own database copy, removed on exit); leftovers are recorded and then removed. Each kit seat
writes its own log (`--log-dir`: `<game_id>-<seat>.jsonl`).

Clock profile (coordinator decision, 2026-10-01): `kit`, for qualification, the soak and `fdn-mirror-v0` itself,
every entry and builtin alike: 120 s per decision, 3,600 s bank, 2 s increment, 300 s startup and game start, 120 s
engine step (the staged `benchmark.json` carries the same values).
