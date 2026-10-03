# spellbench

A cross-engine Magic: The Gathering agent protocol and tournament arena.

Independently built rules engines (mtg-kernel, gorge, XMage, Manafold) and
independently built bots meet here: one wire protocol
(`spec/SPELLBENCH_PROTOCOL_V2.md`) and one arena that pairs bots, adjudicates
games, and publishes ratings per format.

The v1 spec stays for reference; committed v1 runs still validate through
the frozen legacy reader.

- `spec/`: the protocol authority. Engine-neutral; intended to become
  community-governed.
- `goldens/`: protocol conformance transcripts.
- `python/spellbench/`: reference implementation of both protocol roles,
  plus the arena (runner, bot registry, ratings, leaderboard).

## Quickstart

Needs Python 3.11+ and uv 0.11.29 or newer.

```
uv sync --extra test
uv run spellbench run examples/quickstart.json
uv run spellbench validate out/quickstart
uv run spellbench leaderboard out/quickstart
```

This plays the builtin bots (`uniform`, `heuristic`, `first`) on a fake
engine from the test suite. `validate` rechecks every digest and re-derives
every rating from the match ledger. A local try reports
`status: complete (unrated)`; a published rating needs the benchmark flow below.

## Real engines

Any executable that serves the environment role works. Check it first:
`uv run spellbench conformance engine --format pauper-bo1 --deck Burn -- path/to/engine`.
The mtg-kernel example expects `agent_bridge_v2` in a sibling checkout.
The XMage bridge and hosted Luna integration have their own build and
verification instructions under `engines/xmage/` and `docs/llm-rated-entry.md`.

## Write a bot

A bot is any program that serves the agent role on stdin/stdout:

```python
from spellbench.bot import serve

def choose(decision):
    for candidate in decision.candidates:
        if candidate.semantic["kind"] == "play_land":
            return candidate.candidate_id
    return decision.candidates[0].candidate_id

raise SystemExit(serve(choose=choose, name="my-bot", version="0.1.0"))
```

Enter it in a config's `bots` list as
`{"name": "my-bot", "version": "0.1.0", "type": "subprocess", "command": ["python", "my_bot.py"]}`.

No dependencies are needed: `examples/minimal_bot.py` is a complete bot in
15 lines of standard-library Python. Answers are strict JSON: integers only,
no duplicate keys and at most 64 nesting levels. A float, even in an extra
field, forfeits as `malformed_response`.

## Ratings

Matchups are seat-swapped game pairs. Each game has its own derived secret;
the run commits to its secret before play and reveals it afterwards.
Natural results and
forfeits (timeouts, illegal answers, crashes) are rated; engine halts and
capped games are recorded and excluded. Ratings come from an anchored
Bradley-Terry fit over complete pairs (draws count half, plus one virtual
draw per matchup) with paired-bootstrap 95% intervals, on an Elo scale with
the anchor at 1000.

## Running tournaments

- Before any game the arena starts the engine and every bot once; a config
  error stops it there.
- `time_control` bounds startup and each decision, and sets a per-game
  clock bank and increment. These are wall-clock limits, so leave CPU headroom.
- `workers` caps parallel games. The launch guard qualifies the engine and
  bots on fixed scheduled inputs; live hosted models can change choices on replay.
  A script that calls `run_tournament` with `workers` above 1 needs an
  `if __name__ == "__main__":` guard.

## Benchmarks

For LLM entries, [reference panels](docs/reference-panels.md) support adding
entrants without replaying compatible earlier evaluations. `bench prepare`
selects missing targets; normal committed, guarded runs play them; `bench compose`
refits saved results into a validated snapshot. The leaderboard labels comparisons
through shared opponents and leaves unplayed head-to-head matchups empty.

A benchmark is a folder under `benchmarks/` with a `benchmark.json`: an
engine, a deck pool, and a roster anchored on the builtin `uniform` bot
(Elo 1000, shown as "random"). Every matchup plays each pool deck in both
seats, and bots never play themselves.

```bash
uv run spellbench bench run benchmarks/<id> --unrated
```

The run plays the whole round robin into
`benchmarks/<id>/runs/<date>[-N]/` and validates it. Machine paths stay out
of the repo: `${NAME}` placeholders in engine
and bot commands resolve from the environment or from the git-ignored
`benchmarks/local.json`, for example
`{"MTG_KERNEL_BRIDGE": "C:/path/to/agent_bridge_v2.exe"}`.
Placeholders have no escape, so a literal `${` in a command or checkpoint
path is an error.

For a rated run, review and merge the definition first. Set
`SPELLBENCH_SECRETS_DIR` outside all worktrees, and set `SPELLBENCH_PIN_ROOT`
and `SPELLBENCH_ARTIFACT_REGISTER` in local values. The guard pins engine and
bot inputs, registers them and preserves a 60 GiB disk reserve.

Authors publish commitments through a PR, from their own branch at the
reviewed default branch's tip:

```text
uv run spellbench bench commit benchmarks/<id> --review-branch <your-branch> --placement "main-pc=used: measured fastest; haleyspc=slower: measured comparison; runpod=not_authorized: no lease authority"
```

The command commits and pushes only `COMMITMENT.json` to that branch, then
keeps the secret privately. Open a PR and wait for its review and merge.
Play is refused while the commitment is only on a side branch. In your own
run worktree at the reviewed commit, record a third-party timestamp link
for the commitment now on the default branch, then run:

```text
uv run spellbench bench run benchmarks/<id> --run <run-name> --proof <timestamp-link>
```

A substantial run compares serial and parallel completed games and needs a
placement note covering both PCs and RunPod. Compatible qualification
evidence is reused; actual timings and rules stay in the manifest. Preserve
qualification rows and private usage records with the run evidence.
Publish the compact validated results through a reviewed PR. `bench reveal`
publishes an aborted commitment, and `bench rerun` compares replayed ledger
rows. Hosted-model replays can differ; an engine replay with recorded
choices verifies a different property.

```bash
uv run spellbench site benchmarks site
```

This validates each benchmark's board run and newer publications, refuses
to build if one fails, and writes the static site: the Hero chart (Elo above random,
averaged over the benchmarks a bot entered), a page per benchmark, and the
method. Pending, aborted and withheld commitments stay visible. A complete
unrated v2 run does not replace a rated board run. CI checks that published
runs stay available and that each rated config matches its commitment's
definition. Pages validates and deploys on pushes to the public default branch.

## Trust

Bots run as your user. The protocol never shows them hidden state, but a
hostile bot process could read other processes or files. Run untrusted bots
under a separate low-privilege account or in a container.
The host validates every decision and sees only public observations;
fairness is validator-only. See section 13 of the v2 spec. The Luna child
uses separate confinement while its maintainer-owned host broker performs inference.

## Status

v2: 2-player best-of-one, stdio NDJSON, one decision at a time with
authoritative legal candidates, a neutral board view and live validation.
Read the spec's non-claims before building against it.

Benchmarks: `pauper-kernel` (eight Pauper decks on mtg-kernel) with the
builtin and submitted bots. Its existing board runs remain labelled
protocol v1. Luna's proposed two-deck XMage benchmark has no rated result
yet; `docs/llm-rated-entry.md` tracks its remaining live checks and publication.
