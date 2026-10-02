# X5m: fdn-mirror-v0, integration and first rated run (preparation)

Issue #24. Definition: `benchmarks/fdn-mirror-v0/benchmark.json` (schema `spellbench-benchmark/v2`). It parses with
P's loader on `main` (`fb80e58`), gives a valid arena config, and P's site builder
accepts it ("no published run yet"). Run script: `run_rated.sh`. Nothing has been run or published.

## Definition

| Field | Value |
|---|---|
| Format, pool | `fdn-limited-bo1`, the 16 `FDN_top_*` catalog decks, mirrors |
| Schedule | `uniform`, `heuristic`, `first`; no self-play: 3 matchups x 64 seat-swapped pairs = **384 games** |
| Clocks | 120 s per decision, 3,600 s bank, 2 s increment, 300 s startup and game start, 120 s engine step |
| Anchor, seeds | `uniform` (seed 11, Elo 1000), `stats_seed` 20261001, 2,000 bootstrap replicates |
| Workers | at most 12; P's guard chooses |
| Engine | main's verified entry: `${PYTHON} ${XMAGE_VERIFIED_ENTRY} --java ${JAVA} --build ${XMAGE_BUILD} --db ${XMAGE_DB} --work ${XMAGE_ENGINE_WORK} --manifest ${XMAGE_BUILD_MANIFEST} --manifest-sha256 3b54f3f6...` (the build of `004913a`, lib digest `094733a7`, as in `standard-mirror-xmage`) |

The staged copy of the definition on E: was not read again (E: was off limits). This one carries the staged values
(title, pool, 4 pairs per deck, `stats_seed`, bootstrap replicates, bot entries) with the frozen clock profile. The
summary wording is new.

**Engine pin.** P's launcher pins the files the engine command names (`bench/pinning.engine_files`). The verified
entry names the Python launcher, Java and the build manifest, and checks every jar against that manifest's hash
(given in the command) before Java starts, so the rated manifest covers the engine's bytes. The build must be the
exact one of `004913a` (its source revision is in the manifest and in `hello.source_revision`): CI's artifact
(build 36951158155, kept 30 days) or `scripts/build.sh` run in a checkout of that commit; `run_rated.sh` refuses any
other manifest.

## How P's stack makes a rated v2 run (main, `fb80e58`)

A run is rated only when `manifest.is_rated` holds: status `complete`, validator verdict `pass`, a commitment proof,
a measured allocation (P's guard), and pinned engine files. `spellbench bench` on `main` does all of it:

1. **`spellbench bench commit DIR --placement TEXT`** (`bench/commit.py`). Checks `SPELLBENCH_PIN_ROOT`,
   `SPELLBENCH_ARTIFACT_REGISTER` and the placement note first. Requires a clean work tree whose `HEAD` is the tip
   of `origin`'s default branch (`main`) and no untracked file in the benchmark folder. Generates the run secret in
   memory, writes `runs/<date>/COMMITMENT.json` (SHA-256 of the secret, benchmark id, run label), commits that file
   alone, **pushes the commit to `origin/main`**, and only then keeps the secret under `SPELLBENCH_SECRETS_DIR`
   (outside every git tree). `--review-branch` instead pushes to an author branch for a PR, and play is refused
   until it reaches `main`.
2. **Third-party timestamp** (spec 11.6): a commit date proves nothing, so the operator records the pushed commit
   somewhere dated by a third party: a comment on issue #24, a signed release, or an OpenTimestamps proof. Its link
   is the run's `--proof`.
3. **`spellbench bench run DIR --run NAME --proof URL`** (`bench/run.py`). Locks the run, refuses one already
   started, checks the secret against the commitment, the commitment against `origin/main` and the definition
   against the commitment commit. Then the guard: `plan_allocation` on games sampled across the matchups (reusing
   local evidence when compatible), refusing a run that would leave less than 60 GiB free. Pins the engine and bot
   files under `SPELLBENCH_PIN_ROOT` by SHA-256 and registers them (live) with the artifact register. Plays the
   schedule through `runner.run_tournament`: `config.json`, `registry.json`, the ledger `matches.jsonl` (one row per
   game, with its digest), the live validator, then `leaderboard.json`, `LEADERBOARD.md` (Elo against the anchor,
   bootstrap intervals) and `manifest.json` last, which **reveals the run secret**. Pins are then re-registered
   frozen and the run directory closed. A run that stops before its manifest is revealed (`REVEAL.json`).
4. **Publication.** The run directory is in the work tree only. Spec 11.6 publishes every committed run, also an
   aborted or invalid one: commit `runs/<NAME>/` and push it to `main`.
5. **Site.** `.github/workflows/pages.yml` runs on every push to `main`: `spellbench site benchmarks site`
   validates every benchmark's latest run (digests, ratings re-derived from the ledger) and deploys GitHub Pages
   (the repository is public).

Note: one engine process per game. P's runner (`runner.play_one`) starts a JVM and copies the 259 MB card database
for every game; X5's 184 games per minute used one engine per worker.

## Public steps the run takes

| # | Step | What becomes public | Command |
|---|---|---|---|
| 0 | Get the definition onto `main` | `benchmarks/fdn-mirror-v0/` (and anything else merged with it); the push redeploys the site, which then lists the benchmark with "no published run yet" | PR of `xmage-m1` (or of the benchmark folder alone) into `main` |
| 1 | Commitment | a commit on `main` adding `runs/<date>/COMMITMENT.json`; the site redeploys | `run_rated.sh commit --approved '<who, when>'` |
| 2 | Third-party timestamp | e.g. a comment on issue #24 naming the commit and the commitment hash | `gh issue comment 24 --body '<commit> <commitment>'` (manual) |
| 3 | Results | `runs/<date>/`: ledger, leaderboard, manifest with the revealed run secret | `run_rated.sh publish --run <date> --approved '<who, when>'` |
| 4 | Site | the ratings page for fdn-mirror-v0 | automatic on step 3's push |

`run_rated.sh prepare` stops before step 1 with a clearly marked STOP and touches nothing public. `play` happens
between steps 2 and 3 and writes only into the local run directory and the pin root.

## Runbook

1. Branch of `main` (clean work tree at its tip) holding `benchmarks/fdn-mirror-v0`; set `SB_REPO`, `SB_SCRATCH`
   (SSD), `XMAGE_BUILD` (CI's artifact of `004913a`) or `XMAGE_REPO` and `M2` to build it, `SPELLBENCH_PIN_ROOT` (`E:/pinned-binaries` per ARTIFACT-LAW, so the run needs E:),
   `SPELLBENCH_ARTIFACT_REGISTER` (`collab/tools/artifact_register.py`), `SPELLBENCH_SECRETS_DIR` (outside git) and
   `PLACEMENT`.
2. `run_rated.sh prepare [--rehearse]`: checks the tree and values, builds the engine if needed and checks its
   manifest against the pin, scans the card database,
   runs `validate_deck` over the catalog, and with `--rehearse` plays an unrated run of the same definition in a
   private copy outside the repository (guard, runner and validator end to end). Ends at **STOP**.
3. With Jack's confirmation: `run_rated.sh commit --approved '...'`, then the timestamp (step 2 above).
4. `run_rated.sh play --run <date> --proof <url>`: guard, pins, 384 games, validate, leaderboard.
5. With Jack's confirmation: `run_rated.sh publish --run <date> --approved '...'`. If `main` moved since the
   commitment, rebase the run commit on it (never force-push).

## Cost

| Item | Estimate |
|---|---|
| Games | 384 (the guard's qualification adds up to 3 rungs of 2 games per top-rung worker, at most 72 games) |
| Wall time at X5's measured 184 games/min (engine kept per worker) | about 2 min of games |
| Wall time with P's runner (engine per game: about 6 s to start alone, 15 to 35 s when 12 start at once, then 3 to 4 s of FDN play) | about 7 to 13 min of games (30 to 55 games/min) |
| Build, database scan, `validate_deck`, preflight (16 engine starts), guard | about 10 min on Jack's PC |
| Total, Jack's PC | **about 20 to 25 min**; with `--rehearse` about 40 min |
| Disk | engine scratch about 3 GiB transient (12 database copies), rows under 1 MB, pins of a few small files on the pin root |

## Branch

`xmage-m1` (from `main` at `fb80e58`). Step 0 is a PR of this branch, or of a branch carrying only
`benchmarks/fdn-mirror-v0/` and this folder, into `main`; after the merge `SB_REPO` is a clean work tree at the tip of
`main`.
