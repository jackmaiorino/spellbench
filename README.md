# spellbench

A cross-engine Magic: The Gathering agent protocol and tournament arena.

Independently built rules engines (mtg-kernel, gorge, XMage, Manafold) and
independently built bots meet here: one wire protocol
(`spec/SPELLBENCH_PROTOCOL_V1.md`) and one arena that pairs bots, adjudicates
games, and publishes ratings per format.

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
every rating from the match ledger.

## Real engines

Any executable that serves the environment role works. For mtg-kernel,
build `agent_bridge_v1` in a sibling checkout
(`cargo build --release --locked --bin agent_bridge_v1`), then
`uv run spellbench run examples/mtg-kernel.json`. To check an engine
against the reference validators:
`SPELLBENCH_ENGINE_BIN=<path> uv run pytest python/tests/test_engine_conformance.py`.

## Write a bot

A bot is any program that serves the agent role on stdin/stdout:

```python
from spellbench import agent_server

def choose(decision):
    for candidate in decision.candidates:
        if candidate.semantic["kind"] == "play_land":
            return candidate.candidate_id
    return 0

raise SystemExit(agent_server.serve(choose=choose, bot_name="my-bot", bot_version="0.1.0"))
```

Enter it in a config's `bots` list as
`{"name": "my-bot", "version": "0.1.0", "type": "subprocess", "command": ["python", "my_bot.py"]}`.

## Ratings

Matchups are seat-swapped game pairs sharing a seed. Natural results and
forfeits (timeouts, illegal answers, crashes) are rated; engine halts and
capped games are recorded and excluded. Ratings come from an anchored
Bradley-Terry fit over complete pairs (draws count half, plus one virtual
draw per matchup) with paired-bootstrap 95% intervals, on an Elo scale with
the anchor at 1000.

## Running tournaments

- Before any game the arena starts the engine and every bot once; a config
  error stops it there.
- `startup_timeout_ms` bounds a bot's start-up (model loading);
  `choose_timeout_ms` bounds each decision. Both are wall-clock, so leave
  CPU headroom.
- `workers` plays games in parallel processes without changing any result.
  A script that calls `run_tournament` with `workers` above 1 needs an
  `if __name__ == "__main__":` guard.

## Benchmarks

A benchmark is a folder under `benchmarks/` with a `benchmark.json`: an
engine, a deck pool, and a roster anchored on the builtin `uniform` bot
(Elo 1000, shown as "random"). Every matchup plays each pool deck in both
seats, and bots never play themselves.

```bash
uv run spellbench bench run benchmarks/pauper-kernel
```

The run replays the whole round robin into
`benchmarks/<id>/runs/<date>/` and validates it; commit the run to publish
it. Machine paths stay out of the repo: `${NAME}` placeholders in engine
and bot commands resolve from the environment or from the git-ignored
`benchmarks/local.json`, for example
`{"MTG_KERNEL_BRIDGE": "C:/path/to/agent_bridge_v1.exe"}`.
Placeholders have no escape, so a literal `${` in a command or checkpoint
path is an error.

```bash
uv run spellbench site benchmarks site
```

This re-validates each benchmark's latest run, refuses to build if one
fails, and writes the static site: the Hero chart (Elo above random,
averaged over the benchmarks a bot entered), a page per benchmark, and the
method. The Pages workflow builds and deploys it on every push to `main`.

## Trust

Bots run as your user. The protocol never shows them hidden state, but a
hostile bot process could read other processes or files. Run untrusted bots
under a separate low-privilege account or in a container.

## Status

v1: 2-player best-of-one, stdio NDJSON, one decision at a time with
authoritative legal candidates. Read the spec's non-claims before building
against it.

Benchmarks: `pauper-kernel` (eight Pauper decks on mtg-kernel) with the
builtin bots; more bots join through the protocol.
