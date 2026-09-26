# spellbench

A cross-engine Magic: The Gathering agent protocol and tournament arena.

Independently built MTG rules engines (mtg-kernel, gorge, XMage, Manafold)
and independently built bots meet here: one wire protocol
(`spec/SPELLBENCH_PROTOCOL_V1.md`), one arena that pairs bots, adjudicates
games, and publishes ratings and leaderboards per format.

- `spec/`: the Spellbench Protocol authority. Engine-neutral; intended to
  become community-governed.
- `goldens/`: protocol conformance transcripts.
- `python/spellbench/`: reference implementation of both protocol roles,
  plus the arena (match runner, bot registry, ratings, leaderboard).

## Status

v1: 2-player best-of-one, stdio NDJSON, one decision at a time with
authoritative legal candidates. See the spec's non-claims before designing
against it.
