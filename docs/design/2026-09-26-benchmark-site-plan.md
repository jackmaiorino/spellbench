# Benchmark Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a static leaderboard site for Spellbench benchmarks (rotating deck pools, per-deck ratings, a cross-benchmark Hero chart), built only from committed, re-validated tournament runs.

**Architecture:** The arena gains deck pools, a self-play switch, recorded-versus-executed commands, and per-deck rating slices. A new `spellbench.bench` package reads `benchmarks/<id>/benchmark.json` and runs a benchmark into a dated run directory. A new `spellbench.site` package computes the Hero table, renders static HTML with inline SVG from plain view-model dicts, and builds the site after validating every latest run. Two CLI subcommands (`bench run`, `site`) and a Pages workflow expose it.

**Tech Stack:** Python 3.11+ standard library only at runtime; pytest; uv (>= 0.11.29); GitHub Actions and GitHub Pages.

**Spec:** `docs/design/2026-09-26-benchmark-site.md`

## Global Constraints

- Runtime code uses the Python standard library only: `dependencies = []` in `pyproject.toml` stays empty; pytest is the only test dependency.
- Never write an em-dash (U+2014) anywhere: code, comments, HTML copy, docs, commit messages. Use commas, colons, parentheses, or separate sentences.
- No attribution lines in commit messages.
- Published artifacts (run directories and site output) are deterministic: no timestamps, no absolute or machine-specific paths, sorted iteration, `\n` line endings on every OS. An unchanged input rebuilds byte for byte.
- Hashed JSON artifacts go through `store.canonical_bytes` / `store.write_json_atomic` (canonical JSON, integers only, |x| <= 2^53).
- Strict inputs: unknown fields in `benchmark.json`, `proposed.json`, `local.json`, and tournament configs are errors, and every error names the offending field.
- Existing tournament configs keep working unchanged (`decks` pairs; `include_self_play` defaults to true).
- Every string from a benchmark file or a ledger is HTML-escaped in the site. Links taken from data are emitted only for `http://` and `https://` URLs.
- The site loads nothing external: plain HTML, inline SVG, one inline `<style>`, a few lines of inline `<script>`, no fonts or libraries. Colors are CSS variables with light and dark themes. Pages read well at 375 px width.
- Tests run from the repo root with `uv run pytest python/tests -q`. The whole suite stays green (309 passed, 3 skipped before this plan).
- Third-party GitHub Actions are pinned by full commit SHA with a version comment, as in `.github/workflows/ci.yml`.

## Review Focus

1. A benchmark folder committed before its first run (no `runs/`, or only an unpublished partial run directory): the site build still succeeds, shows the card as not yet run, and warns. `bench run` picks the next free run name. (Tests: Task 4, Task 8.)
2. Hostile or odd display data: `<script>` in a label, quotes in attributes, a `javascript:` URL, very long names at phone width. Escaped, never linked, layout intact. (Tests: Task 4, Task 6, Task 8.)
3. A run directory left by a crashed run (no `manifest.json`) that sorts after the last published run: latest-run selection skips it, the site shows the published run and warns. (Tests: Task 4, Task 8.)
4. `benchmark.json` edited after its latest run (a bot added, removed, or relabelled): the site still renders the run's bots, falling back to registry name and owner, and warns that the definition changed since the run. (Test: Task 8.)
5. A deck slice where the anchor bot has no complete pair (every game of that deck halted, for example): the slice is reported as not rated with a reason; the leaderboard, `validate`, and the site keep working. (Tests: Task 3, Task 8.)

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `python/spellbench/arena/runner.py` | 1, 2 | deck pools, self-play switch, per-deck preflight, recorded vs executed commands, output directory |
| `python/spellbench/arena/validate.py` (new) | 2 | `validate_tournament_dir`, moved out of `cli.py` so library code can call it without importing the CLI |
| `python/spellbench/arena/leaderboard.py` | 3 | `slices.deck` in `leaderboard.json` and a "By deck" markdown section |
| `python/spellbench/bench/definition.py` (new) | 4 | `benchmark.json` and `proposed.json` parsing, placeholders, run-directory names |
| `python/spellbench/bench/run.py` (new) | 7 | run a benchmark into `runs/<date>[-N]/` and validate it |
| `python/spellbench/site/hero.py` (new) | 5 | Hero table from leaderboard documents |
| `python/spellbench/site/render.py` (new) | 6 | pure HTML from view-model dicts |
| `python/spellbench/site/build.py` (new) | 8 | validate runs, build view models, write the site |
| `python/spellbench/arena/cli.py` | 2, 7, 8 | re-export validate; `bench run` and `site` subcommands |
| `benchmarks/pauper-kernel/benchmark.json`, `benchmarks/proposed.json` (new) | 7 | the launch benchmark and the proposed cards |
| `.github/workflows/pages.yml` (new), `README.md` | 9 | deploy and docs |

## Execution Notes (controller)

- Wave 1, in parallel, one git worktree and branch per implementer: Tasks 1 and 2 (one implementer, in order), Task 3, Task 4, Task 5, Task 6. Tasks 5 and 6 both create `python/spellbench/site/__init__.py` with identical bytes.
- Wave 2, after wave 1 is merged into `benchmark-site`: Tasks 7, 8, 9 in parallel. Tasks 7 and 8 both add a subcommand to `cli.py`; the controller resolves that merge.
- Then the controller runs `pauper-kernel` on the real bridge (builtin bots), commits the run, builds the site, publishes a private preview, and dispatches the final whole-branch review.

---

### Task 1: Deck pools and the self-play switch

**Files:**
- Modify: `python/spellbench/arena/runner.py` (module docstring, `matchup_indexes`, `TournamentConfig`, `_GameContext`, `_play_game_row`, `_preflight`, `_schedule`, `schedule_mismatches`)
- Modify: `python/tests/arena_helpers.py` (`make_config` gains `deck_pool`)
- Modify: `python/tests/fake_arena_engine.py` (one active game per process, like the mtg-kernel bridge)
- Create: `python/tests/test_arena_schedule.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `TournamentConfig.decks: tuple[models.Deck, models.Deck] | None` (None when a pool is used)
  - new trailing fields `TournamentConfig.deck_pool: tuple[models.Deck, ...] | None = None` and `TournamentConfig.include_self_play: bool = True`
  - `TournamentConfig.decks_for_pair(pair_index: int) -> tuple[models.Deck, models.Deck]`
  - `TournamentConfig.preflight_deck_pairs() -> tuple[tuple[models.Deck, models.Deck], ...]`
  - `matchup_indexes(bot_count: int, *, include_self_play: bool = True) -> list[tuple[int, int]]`
  - config JSON: `deck_pool` (nonempty list of distinct deck objects, exclusive with `decks`); `include_self_play` (JSON boolean, default true). `to_json()` writes exactly one of `decks` / `deck_pool` and always writes `include_self_play`.
  - `_GameContext.decks: tuple[models.Deck, models.Deck]`

Background: `models.Deck` is a frozen, hashable dataclass (`catalog_id` or `decklist`). Ledger rows already record each game's decks, so per-pair decks need no ledger change. The mtg-kernel bridge refuses a `reset` while a game is active (`game_already_active`, spec section 2), so the preflight must use a fresh engine process for every deck pairing.

- [ ] **Step 1: Write the failing tests**

Add to `python/tests/arena_helpers.py`, replacing `make_config`:

```python
def make_config(
    directory: Path,
    bots: list[dict[str, Any]],
    *,
    engine: Path = FAKE_ARENA_ENGINE,
    decks: tuple[str, str] = ("Burn", "Burn"),
    deck_pool: tuple[str, ...] | None = None,
    pairs: int = 2,
    **extra: Any,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "schema": "spellbench-tournament-config/v1",
        "tournament_dir": str(directory),
        "format": "pauper-bo1",
        "decks": [{"catalog_id": decks[0]}, {"catalog_id": decks[1]}],
        "engine": {"command": [sys.executable, str(engine)], "timeout_ms": 30_000},
        "bots": bots,
        "pairs_per_matchup": pairs,
        "base_seed": 12345,
        "bootstrap_replicates": 1000,
    }
    if deck_pool is not None:
        del config["decks"]
        config["deck_pool"] = [{"catalog_id": deck} for deck in deck_pool]
    config.update(extra)
    return config
```

Create `python/tests/test_arena_schedule.py`:

```python
"""Deck pools and the self-play switch: what the round-robin schedules."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import runner
from spellbench.arena.cli import validate_tournament_dir

from arena_helpers import builtin, ledger_rows, make_config, run

POOL = ("Burn", "Elves", "Faeries")
BOTS = [builtin("heuristic"), builtin("first")]


def _pool_config(directory: Path, **extra: Any) -> dict[str, Any]:
    return make_config(directory, BOTS, deck_pool=POOL, pairs=6, include_self_play=False, **extra)


def test_each_pair_plays_the_next_pool_deck_in_both_seats(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "t"))
    rows = ledger_rows(tmp_path / "t")
    assert len(rows) == 12  # one matchup x 6 pairs x 2 games
    for row in rows:
        expected = POOL[row["pair_index"] % len(POOL)]
        assert [deck["catalog_id"] for deck in row["decks"]] == [expected, expected]
    per_deck = Counter(row["decks"][0]["catalog_id"] for row in rows)
    assert per_deck == {"Burn": 4, "Elves": 4, "Faeries": 4}  # 2 pairs x 2 games per deck


def test_a_pool_schedule_is_identical_across_runs(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "a"))
    run(_pool_config(tmp_path / "b"))
    assert (tmp_path / "a" / "matches.jsonl").read_bytes() == (tmp_path / "b" / "matches.jsonl").read_bytes()


def test_pairs_per_matchup_must_be_a_multiple_of_the_pool_size(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS, deck_pool=POOL, pairs=4)
    with pytest.raises(runner.TournamentError, match="multiple"):
        runner.TournamentConfig.from_json(config)


def test_decks_and_a_deck_pool_are_exclusive(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS, deck_pool=POOL, pairs=3)
    config["decks"] = [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}]
    with pytest.raises(runner.TournamentError, match="deck_pool"):
        runner.TournamentConfig.from_json(config)


def test_a_config_needs_decks_or_a_deck_pool(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS)
    del config["decks"]
    with pytest.raises(runner.TournamentError, match="decks"):
        runner.TournamentConfig.from_json(config)


@pytest.mark.parametrize("pool", [[], [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], "Burn"])
def test_a_deck_pool_is_a_nonempty_list_of_distinct_decks(tmp_path: Path, pool: Any) -> None:
    config = make_config(tmp_path / "t", BOTS, pairs=2)
    del config["decks"]
    config["deck_pool"] = pool
    with pytest.raises(runner.TournamentError, match="deck_pool"):
        runner.TournamentConfig.from_json(config)


def test_self_play_off_schedules_no_mirror_matchups(tmp_path: Path) -> None:
    bots = [builtin("heuristic"), builtin("first"), builtin("uniform", seed=11)]
    run(make_config(tmp_path / "t", bots, pairs=2, include_self_play=False))
    rows = ledger_rows(tmp_path / "t")
    assert len(rows) == 3 * 2 * 2  # 3 matchups x 2 pairs x 2 games
    assert all(row["seats"][0]["name"] != row["seats"][1]["name"] for row in rows)
    assert sorted({row["matchup_index"] for row in rows}) == [0, 1, 2]


def test_self_play_is_on_by_default(tmp_path: Path) -> None:
    run(make_config(tmp_path / "t", BOTS, pairs=1))
    seatings = {(row["seats"][0]["name"], row["seats"][1]["name"]) for row in ledger_rows(tmp_path / "t")}
    assert ("heuristic", "heuristic") in seatings and ("first", "first") in seatings


def test_self_play_off_needs_two_bots(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", [builtin("heuristic")], include_self_play=False)
    with pytest.raises(runner.TournamentError, match="two bots"):
        runner.TournamentConfig.from_json(config)


def test_include_self_play_must_be_a_boolean(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS, include_self_play=0)
    with pytest.raises(runner.TournamentError, match="include_self_play"):
        runner.TournamentConfig.from_json(config)


def test_preflight_tries_every_pool_deck_before_any_game(tmp_path: Path) -> None:
    # "Refuse" (a fake-engine hook) is second in the pool, so a preflight of
    # the first deck alone would miss it.
    directory = tmp_path / "t"
    config = make_config(directory, BOTS, deck_pool=("Burn", "Refuse"), pairs=2, include_self_play=False)
    with pytest.raises(runner.TournamentError, match="unsupported_deck"):
        run(config)
    assert not directory.exists()


def test_preflight_gives_each_pool_deck_its_own_engine_process(tmp_path: Path) -> None:
    # An engine hosts one active game per process (spec section 2), and the
    # fake engine refuses a second reset as the mtg-kernel bridge does, so a
    # preflight that reused one process across decks would fail here.
    assert run(_pool_config(tmp_path / "t")).games_rated == 12


def test_the_recorded_config_keeps_the_pool_and_the_switch(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "t"))
    recorded = json.loads((tmp_path / "t" / "config.json").read_text(encoding="utf-8"))
    assert "decks" not in recorded
    assert recorded["deck_pool"] == [{"catalog_id": deck} for deck in POOL]
    assert recorded["include_self_play"] is False


def test_a_fixed_deck_config_records_its_decks_and_self_play_on(tmp_path: Path) -> None:
    run(make_config(tmp_path / "t", BOTS, pairs=1))
    recorded = json.loads((tmp_path / "t" / "config.json").read_text(encoding="utf-8"))
    assert recorded["decks"] == [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}]
    assert "deck_pool" not in recorded and recorded["include_self_play"] is True


def test_validate_accepts_pool_and_self_play_off_tournaments(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "t"))
    assert validate_tournament_dir(tmp_path / "t") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_schedule.py -q`
Expected: FAIL. Pool configs are rejected with `fields mismatch: ... extra=['deck_pool']` or `extra=['include_self_play']`; the self-play-default and fixed-deck tests fail on the missing `include_self_play` key.

- [ ] **Step 3: Make the fake engine host one game at a time**

In `python/tests/fake_arena_engine.py`, add to the module docstring: "Hosts one game at a time, like the mtg-kernel bridge: a `reset` while a game is active answers `game_already_active` (spec section 2)." In `main()`, add `active = False` beside the other state. Add a branch before the other reset branches:

```python
            elif kind == "reset" and active:
                message = ErrorResponse(
                    request_id=request_id,
                    code="game_already_active",
                    message="this engine process already hosts an active game",
                ).to_json()
```

In the normal `reset` branch, reset per-game state and mark the game active: `step = 0`, `scores = {"p0": 0, "p1": 0}`, `active = True`. Wherever a terminal is emitted (the `Halt` hook, the natural end, and the `max_steps` truncation), set `active = False`.

- [ ] **Step 4: Implement deck pools and the switch in `runner.py`**

Replace `matchup_indexes`:

```python
def matchup_indexes(bot_count: int, *, include_self_play: bool = True) -> list[tuple[int, int]]:
    """Unordered bot-list index pairs in schedule order; mirrors unless self-play is off."""
    return [
        (i, j)
        for i, j in combinations_with_replacement(range(bot_count), 2)
        if include_self_play or i != j
    ]
```

In `TournamentConfig`: change `decks` to `tuple[models.Deck, models.Deck] | None`, append the two fields after `startup_timeout_ms`, and add the two methods:

```python
    deck_pool: tuple[models.Deck, ...] | None = None
    include_self_play: bool = True

    def decks_for_pair(self, pair_index: int) -> tuple[models.Deck, models.Deck]:
        """The (p0, p1) decks of both games of pair ``pair_index``."""
        if self.deck_pool is None:
            assert self.decks is not None
            return self.decks
        deck = self.deck_pool[pair_index % len(self.deck_pool)]
        return (deck, deck)

    def preflight_deck_pairs(self) -> tuple[tuple[models.Deck, models.Deck], ...]:
        """Every deck pairing the schedule uses, in first-use order."""
        if self.deck_pool is None:
            assert self.decks is not None
            return (self.decks,)
        return tuple((deck, deck) for deck in self.deck_pool)
```

`to_json()`: drop the unconditional `"decks"` entry, add `"include_self_play": self.include_self_play`, then write `doc["decks"] = [deck.to_json() for deck in self.decks]` when `deck_pool` is None, else `doc["deck_pool"] = [deck.to_json() for deck in self.deck_pool]`.

`from_json()`:
- add `"deck_pool"` and `"include_self_play"` to `allowed`; remove `"decks"` from `required`;
- after the schema check:

```python
        has_decks, has_pool = "decks" in value, "deck_pool" in value
        if has_decks and has_pool:
            raise TournamentError(f"{context}: give decks or deck_pool, not both")
        if not has_decks and not has_pool:
            raise TournamentError(f"{context}: requires decks (a fixed pair) or deck_pool")
        decks: tuple[models.Deck, models.Deck] | None = None
        deck_pool: tuple[models.Deck, ...] | None = None
        if has_decks:
            ...  # the existing two-deck parsing, assigning decks = (first, second)
        else:
            raw_pool = value["deck_pool"]
            if not isinstance(raw_pool, list) or not raw_pool:
                raise TournamentError(f"{context}.deck_pool: must be a nonempty list of decks")
            try:
                deck_pool = tuple(
                    models.Deck.from_json(item, f"{context}.deck_pool[{i}]") for i, item in enumerate(raw_pool)
                )
            except ValidationError as exc:
                raise TournamentError(str(exc)) from exc
            if len(set(deck_pool)) != len(deck_pool):
                raise TournamentError(f"{context}.deck_pool: decks must be distinct")
```

- after `pairs_per_matchup` is parsed:

```python
        if deck_pool is not None and pairs_per_matchup % len(deck_pool):
            raise TournamentError(
                f"{context}.pairs_per_matchup: {pairs_per_matchup} is not a multiple of the "
                f"{len(deck_pool)} deck_pool decks (every matchup plays every deck equally)"
            )
        include_self_play = value.get("include_self_play", True)
        if type(include_self_play) is not bool:
            raise TournamentError(f"{context}.include_self_play: must be true or false")
        if not include_self_play and len(bots) < 2:
            raise TournamentError(f"{context}.include_self_play: false needs at least two bots")
```

- pass `decks=decks, deck_pool=deck_pool, include_self_play=include_self_play` to `cls(...)`.

`_GameContext`: add `decks: tuple[models.Deck, models.Deck]` as its last field. `_schedule`: iterate `matchup_indexes(len(config.bots), include_self_play=config.include_self_play)` and pass `decks=config.decks_for_pair(pair_index)` to every context. `_play_game_row`: use `ctx.decks` for `decks_json`, for `driver.start(decks=...)`, and for `engine.reset(decks=...)`. `schedule_mismatches`: compare each row against `(ctx.decks[0].to_json(), ctx.decks[1].to_json())` inside the loop.

Split the engine half of `_preflight` into a helper and call it once per deck pairing, each with its own engine process:

```python
def _preflight_engine(
    config: TournamentConfig, pin: _EnginePin, decks: tuple[models.Deck, models.Deck], game_id: str
) -> None:
    """One engine process: hello, the pinned identity, the format, one reset."""
    try:
        engine = EngineProcess(list(config.engine_command), timeout_s=config.engine_timeout_ms / 1000.0)
    except TransportError as exc:
        raise TournamentError(f"engine failed to start: {exc}") from exc
    try:
        hello = engine.hello()
        pin.check(hello.engine)
        if config.format not in hello.formats:
            raise TournamentError(
                f"engine does not support format {config.format!r}: offers {sorted(hello.formats)}"
            )
        engine.reset(
            game_id=game_id,
            format=config.format,
            decks=decks,
            game_seed=config.base_seed,
            max_decisions=config.max_decisions,
            max_steps=config.max_steps,
        )
    except (TransportError, RemoteError, ProtocolError) as exc:
        labels = [deck.to_json() for deck in decks]
        raise TournamentError(
            f"preflight: the engine could not start a game with decks {labels}: {exc}"
        ) from exc
    finally:
        engine.close()
```

In `_preflight`, replace the engine block with:

```python
    # One engine process per deck pairing: an engine hosts one active game
    # at a time (spec section 2), and the preflight never finishes its game.
    for index, decks in enumerate(config.preflight_deck_pairs()):
        _preflight_engine(config, pin, decks, f"preflight-{index}")
```

(Preflight game ids still start with `preflight`, which the fake engine's `Rendezvous` hook relies on.) Update the module docstring's schedule paragraph: mirrors are included unless `include_self_play` is false; with a `deck_pool`, pair `p` plays `deck_pool[p % len(deck_pool)]` in both seats and `pairs_per_matchup` is a multiple of the pool size; the preflight resets each deck pairing in its own engine process.

- [ ] **Step 5: Run the new tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_schedule.py -q`
Expected: PASS (16 passed).
Run: `uv run pytest python/tests -q`
Expected: all pass (325 passed, 3 skipped, give or take the parametrized count).

- [ ] **Step 6: Commit**

```bash
git add python/spellbench/arena/runner.py python/tests/arena_helpers.py python/tests/fake_arena_engine.py python/tests/test_arena_schedule.py
git commit -m "Arena: deck pools, a self-play switch, and a per-deck preflight"
```

### Task 2: Recorded versus executed commands, and a validate module

**Files:**
- Modify: `python/spellbench/arena/runner.py` (`BotSpec.registry_entry`, `run_tournament`, new `_executed_config`)
- Create: `python/spellbench/arena/validate.py` (moved `validate_tournament_dir`)
- Modify: `python/spellbench/arena/cli.py` (import `validate_tournament_dir` from the new module; the name stays importable from `cli`)
- Create: `python/tests/test_arena_resolve.py`

**Interfaces:**
- Consumes: Task 1's `TournamentConfig` (unchanged by this task).
- Produces:
  - `run_tournament(config: TournamentConfig, *, on_game: Callable[[store.LedgerRow], None] | None = None, resolve: Callable[[str], str] | None = None, output_dir: str | Path | None = None) -> TournamentSummary`
  - `BotSpec.registry_entry(self, *, checkpoint_path: str | None = None) -> registry.RegistryEntry`
  - `spellbench.arena.validate.validate_tournament_dir(directory: Path) -> list[str]` (also still importable as `spellbench.arena.cli.validate_tournament_dir`)
- Semantics: `resolve` maps every engine command part, every subprocess bot command part, and every checkpoint path to the string used to start processes and read files. `config.json`, `registry.json`, bot ids, and the ledger record the unresolved strings; a checkpoint's bytes are hashed from its resolved path. `output_dir` publishes into that directory instead of `config.tournament_dir`, which is still recorded as written.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_resolve.py`:

```python
"""Recorded versus executed commands: placeholders stay in the artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import registry, runner
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import FAKE_ARENA_ENGINE, builtin, make_config, subprocess_bot

VALUES = {"${PY}": sys.executable, "${ENGINE}": str(FAKE_ARENA_ENGINE)}
PUBLISHED = ("manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md")
BOT_COMMAND = ["${PY}", "-m", "spellbench.arena.cli", "bot", "heuristic"]


def resolve(text: str) -> str:
    for placeholder, value in VALUES.items():
        text = text.replace(placeholder, value)
    return text


def _config(tmp_path: Path, bot: dict[str, Any] | None = None, **extra: Any) -> runner.TournamentConfig:
    bots = [bot or subprocess_bot("heuristic", BOT_COMMAND), builtin("first")]
    config = make_config(tmp_path / "unused", bots, pairs=1, include_self_play=False, **extra)
    config["tournament_dir"] = "runs/2026-09-26"
    config["engine"]["command"] = ["${PY}", "${ENGINE}"]
    return runner.TournamentConfig.from_json(config)


def test_processes_run_resolved_commands_and_artifacts_keep_the_written_ones(tmp_path: Path) -> None:
    out = tmp_path / "out"
    summary = runner.run_tournament(_config(tmp_path, workers=2), resolve=resolve, output_dir=out)
    assert summary.games_rated == 2
    assert summary.tournament_dir == out
    recorded = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert recorded["tournament_dir"] == "runs/2026-09-26"
    assert recorded["engine"]["command"] == ["${PY}", "${ENGINE}"]
    assert recorded["bots"][0]["command"] == BOT_COMMAND
    entries = {entry.name: entry for entry in registry.read_registry(out / "registry.json")}
    written = registry.subprocess_descriptor("heuristic", "1.0.0", BOT_COMMAND)
    assert entries["heuristic"].bot_id == registry.bot_id_from_descriptor(written)
    assert validate_tournament_dir(out) == []


def test_no_published_file_contains_a_resolved_value(tmp_path: Path) -> None:
    out = tmp_path / "out"
    runner.run_tournament(_config(tmp_path), resolve=resolve, output_dir=out)
    for name in PUBLISHED:
        text = (out / name).read_text(encoding="utf-8")
        for value in VALUES.values():
            assert value not in text, name
            assert json.dumps(value)[1:-1] not in text, name  # the JSON-escaped spelling


def test_output_dir_replaces_the_recorded_tournament_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.run_tournament(_config(tmp_path), resolve=resolve, output_dir=tmp_path / "out")
    assert not (tmp_path / "runs").exists()
    assert (tmp_path / "out" / "manifest.json").is_file()


def test_a_checkpoint_is_hashed_from_its_resolved_path_and_recorded_as_written(tmp_path: Path) -> None:
    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"model bytes")
    bot = subprocess_bot("heuristic", BOT_COMMAND, checkpoint="${CKPT}")
    out = tmp_path / "out"
    runner.run_tournament(
        _config(tmp_path, bot),
        resolve=lambda text: resolve(text).replace("${CKPT}", str(weights)),
        output_dir=out,
    )
    recorded = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert recorded["bots"][0]["checkpoint"] == "${CKPT}"
    entry = next(item for item in registry.read_registry(out / "registry.json") if item.name == "heuristic")
    expected = registry.subprocess_descriptor(
        "heuristic", "1.0.0", BOT_COMMAND, weights_sha256=registry.checkpoint_sha256(weights)
    )
    assert entry.bot_id == registry.bot_id_from_descriptor(expected)


def test_validate_is_still_importable_from_the_cli_module() -> None:
    from spellbench.arena import cli

    assert cli.validate_tournament_dir is validate_tournament_dir
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_resolve.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'spellbench.arena.validate'`.

- [ ] **Step 3: Move `validate_tournament_dir` into `arena/validate.py`**

Create `python/spellbench/arena/validate.py` holding `validate_tournament_dir` exactly as it is in `cli.py` today (same docstring and checks), with a module docstring: "Re-verify a published tournament directory from its files alone." Import what it needs (`Path`, `models`, `ValidationError`, `leaderboard`, `registry`, `runner`, `store`). In `cli.py`, delete the function and add `from .validate import validate_tournament_dir` so `_cmd_validate` and existing importers keep working. Remove imports that `cli.py` no longer uses.

- [ ] **Step 4: Implement recorded versus executed commands in `runner.py`**

Add `replace` to the `dataclasses` import. Change `BotSpec.registry_entry`:

```python
    def registry_entry(self, *, checkpoint_path: str | None = None) -> registry.RegistryEntry:
        """This bot's registry entry. The descriptor records the command as
        written; ``checkpoint_path`` (the resolved path, when the recorded
        one holds a placeholder) is where the checkpoint bytes are read."""
        if self.type == "builtin":
            descriptor = registry.builtin_descriptor(self.name, self.version)
        else:
            path = self.checkpoint if checkpoint_path is None else checkpoint_path
            weights = registry.checkpoint_sha256(Path(path)) if path is not None else None
            descriptor = registry.subprocess_descriptor(
                self.name, self.version, self.command, weights_sha256=weights
            )
        ...  # build_entry unchanged
```

Add above `run_tournament`:

```python
def _executed_config(config: TournamentConfig, resolve: Callable[[str], str]) -> TournamentConfig:
    """``config`` with every command part and checkpoint path passed through ``resolve``."""
    bots = tuple(
        replace(
            spec,
            command=tuple(resolve(part) for part in spec.command),
            checkpoint=None if spec.checkpoint is None else resolve(spec.checkpoint),
        )
        for spec in config.bots
    )
    return replace(config, engine_command=tuple(resolve(part) for part in config.engine_command), bots=bots)
```

Rewrite the head of `run_tournament` (the rest keeps its structure; games run with `executed`, artifacts come from `config`):

```python
def run_tournament(
    config: TournamentConfig,
    *,
    on_game: Callable[[store.LedgerRow], None] | None = None,
    resolve: Callable[[str], str] | None = None,
    output_dir: str | Path | None = None,
) -> TournamentSummary:
    """Run the full schedule and publish the tournament artifacts.

    ``resolve`` maps each engine and bot command part and checkpoint path to
    the string that starts the process or locates the file; every published
    artifact records ``config`` as written. ``output_dir`` publishes into
    that directory instead of ``config.tournament_dir``.
    """
    executed = config if resolve is None else _executed_config(config, resolve)
    pin = _EnginePin()
    _preflight(executed, pin)
    directory = Path(config.tournament_dir if output_dir is None else output_dir)
    store.prepare_tournament_dir(directory)
    entries_list = [
        spec.registry_entry(checkpoint_path=run_spec.checkpoint)
        for spec, run_spec in zip(config.bots, executed.bots)
    ]
    entries = {entry.name: entry for entry in entries_list}
    anchor_bot_id = entries[config.rating_anchor].bot_id
```

Below that, pass `executed` (not `config`) to `_play_game`, `_play_game_in_worker`, and `_schedule`; keep `config` for `config.to_json()`, `manifest_body`, and `build_leaderboard` arguments. The executed config is a plain dataclass, so it pickles to spawned workers; `resolve` itself never leaves the parent process. `TournamentConfig.anchor_bot_id()` is now unused: delete it if a repo-wide search finds no other caller.

- [ ] **Step 5: Run the new tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_resolve.py -q`
Expected: PASS (5 passed).
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add python/spellbench/arena/runner.py python/spellbench/arena/validate.py python/spellbench/arena/cli.py python/tests/test_arena_resolve.py
git commit -m "Arena: record commands as written, run them resolved; validate module"
```

### Task 3: Deck slices in the leaderboard

**Files:**
- Modify: `python/spellbench/arena/leaderboard.py`
- Create: `python/tests/test_arena_slices.py`

**Interfaces:**
- Consumes: ledger rows as today (each `LedgerRow.decks` is the game's `(p0 deck, p1 deck)` JSON pair).
- Produces:
  - `deck_slice_seed(base_seed: int, ordinal: int) -> int`
  - `leaderboard.json` gains the top-level key `"slices": {"deck": [DeckSlice, ...]}`. `DeckSlice` is:

```json
{
  "label": "Burn",
  "decks": [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
  "status": "ok",
  "fit_error": null,
  "games": {"total": 24, "rated": 24, "truncated": 0, "halted": 0, "forfeit": 0},
  "rating_bootstrap": {"status": "ok", "replicates": 2000, "failed_replicates": 0, "seed": 123},
  "rows": ["...same objects as the top-level rows..."]
}
```

  - `status` is `ok`, `no_rated_games`, or `fit_failed` (exactly the top-level status values); `label` is the catalog id, `"<p0> vs <p1>"` when the seats' decks differ, and `"decklist <first 12 hex of sha256(canonical deck JSON)>"` for a decklist deck.
  - Contract: `slices.deck` lists one slice per distinct deck pairing, sorted by `store.canonical_bytes(list(row.decks))`, and is `[]` unless the rows hold at least two distinct pairings. Slice `k` equals `build_leaderboard(<that pairing's rows>, entries, anchor_bot_id=<same>, base_seed=deck_slice_seed(base_seed, k), bootstrap_replicates=<same>, format=<same>)` on the keys `status`, `fit_error`, `games`, `rows`, and `bt.rating_bootstrap` (as `rating_bootstrap`).
  - `LEADERBOARD.md` gains a `## By deck` section (after the subratings, before the notes) when slices exist: `### <label>`, then the main table's columns for that slice, or `skipped: <status>` plus ` (<fit_error>)` when the slice is not ok.
  - `NOTES` gains: `"deck slices (when games use more than one deck pairing): each pairing's ratings recomputed from its games alone, with the same anchor and prior and stats seeds derived per slice"`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_arena_slices.py`:

```python
"""Deck slices: per-deck ratings recomputed from each deck's games alone."""

from __future__ import annotations

from spellbench import models
from spellbench.arena import leaderboard, registry, store

PROVENANCE = models.Provenance("fake", "0", "rules", "pool")
ALPHA, BETA, GAMMA = (
    registry.build_entry(name=name, version="1.0.0", descriptor=registry.builtin_descriptor(name, "1.0.0"))
    for name in ("alpha", "beta", "gamma")
)
ENTRIES = [ALPHA, BETA, GAMMA]
BASE_SEED = 7


def _row(matchup: int, pair: int, game: int, a, b, decks: tuple[str, str], result: str) -> store.LedgerRow:
    """Game ``game`` of pair ``pair`` of matchup (a, b).

    Game 0 seats a at p0, game 1 seats b at p0. ``result`` is "a" or "b"
    (that bot wins), "draw", or "halted".
    """
    p0, p1 = (a, b) if game == 0 else (b, a)
    seats = tuple(
        store.LedgerSeat(seat=seat, bot_id=entry.bot_id, name=entry.name, version=entry.version)
        for seat, entry in (("p0", p0), ("p1", p1))
    )
    if result == "halted":
        outcome, classification, winner = "halted", "halted", None
    elif result == "draw":
        outcome, classification, winner = "draw", "natural", None
    else:
        winner_entry = a if result == "a" else b
        winner = "p0" if winner_entry is p0 else "p1"
        outcome, classification = f"{winner}_win", "natural"
    return store.LedgerRow(
        game_id=f"m{matchup:04d}p{pair:04d}g{game}",
        matchup_index=matchup,
        pair_index=pair,
        game_index=game,
        format="pauper-bo1",
        game_seed=1,
        seats=seats,
        decks=({"catalog_id": decks[0]}, {"catalog_id": decks[1]}),
        outcome=outcome,
        classification=classification,
        winner=winner,
        winner_bot_id=None if winner is None else (p0 if winner == "p0" else p1).bot_id,
        reason="test",
        adjudication=None,
        step_count=1,
        decision_count=1,
        engine=PROVENANCE,
    )


def _pairs(matchup: int, a, b, schedule: list[tuple[str, str, str]]) -> list[store.LedgerRow]:
    """One matchup; ``schedule[p]`` is (deck, game 0 result, game 1 result) of pair p."""
    rows = []
    for pair, (deck, first, second) in enumerate(schedule):
        rows.append(_row(matchup, pair, 0, a, b, (deck, deck), first))
        rows.append(_row(matchup, pair, 1, a, b, (deck, deck), second))
    return rows


# A two-deck pool alternating by pair: alpha is strongest on Burn, beta on Elves.
ROWS = (
    _pairs(0, ALPHA, BETA, [("Burn", "a", "a"), ("Elves", "b", "b"), ("Burn", "a", "draw"), ("Elves", "b", "a")])
    + _pairs(1, ALPHA, GAMMA, [("Burn", "a", "a"), ("Elves", "draw", "draw"), ("Burn", "a", "b"), ("Elves", "b", "b")])
    + _pairs(2, BETA, GAMMA, [("Burn", "b", "a"), ("Elves", "a", "a"), ("Burn", "draw", "a"), ("Elves", "a", "draw")])
)


def _build(rows, base_seed: int = BASE_SEED):
    return leaderboard.build_leaderboard(
        rows, ENTRIES, anchor_bot_id=ALPHA.bot_id, base_seed=base_seed, bootstrap_replicates=1000, format="pauper-bo1"
    )


def test_one_slice_per_deck_in_sorted_order() -> None:
    document, _ = _build(ROWS)
    slices = document["slices"]["deck"]
    assert [deck_slice["label"] for deck_slice in slices] == ["Burn", "Elves"]
    assert slices[0]["decks"] == [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}]


def test_a_slice_equals_a_recomputation_from_that_decks_rows() -> None:
    document, _ = _build(ROWS)
    for ordinal, deck_slice in enumerate(document["slices"]["deck"]):
        deck = deck_slice["decks"][0]["catalog_id"]
        deck_rows = [row for row in ROWS if row.decks[0]["catalog_id"] == deck]
        direct, _ = _build(deck_rows, base_seed=leaderboard.deck_slice_seed(BASE_SEED, ordinal))
        assert deck_slice["status"] == direct["status"] == "ok"
        assert deck_slice["fit_error"] is None
        assert deck_slice["rows"] == direct["rows"]
        assert deck_slice["games"] == direct["games"]
        assert deck_slice["rating_bootstrap"] == direct["bt"]["rating_bootstrap"]
        assert direct["slices"]["deck"] == []


def test_slices_keep_the_overall_anchor() -> None:
    document, _ = _build(ROWS)
    for deck_slice in document["slices"]["deck"]:
        anchor = next(row for row in deck_slice["rows"] if row["bot_id"] == ALPHA.bot_id)
        assert anchor["elo_milli"] == 1_000_000


def test_decks_split_the_ratings() -> None:
    document, _ = _build(ROWS)
    by_deck = {s["label"]: {row["name"]: row for row in s["rows"]} for s in document["slices"]["deck"]}
    assert by_deck["Burn"]["beta"]["elo_milli"] < 1_000_000 < by_deck["Elves"]["beta"]["elo_milli"]


def test_a_single_pairing_ledger_has_no_slices() -> None:
    burn_only = [row for row in ROWS if row.decks[0]["catalog_id"] == "Burn"]
    document, markdown = _build(burn_only)
    assert document["slices"] == {"deck": []}
    assert "## By deck" not in markdown


def test_a_slice_without_a_rated_anchor_is_reported_not_raised() -> None:
    # Both Elves games between alpha and beta halted, so the anchor (alpha)
    # has no complete pair on Elves and that slice cannot be anchored.
    rows = _pairs(0, ALPHA, BETA, [("Burn", "a", "a"), ("Elves", "halted", "halted")]) + _pairs(
        1, BETA, GAMMA, [("Burn", "a", "b"), ("Elves", "a", "draw")]
    )
    document, markdown = _build(rows)
    assert document["status"] == "ok"
    elves = next(s for s in document["slices"]["deck"] if s["label"] == "Elves")
    assert elves["status"] == "fit_failed" and elves["fit_error"]
    assert elves["games"]["halted"] == 2
    assert not any(row["rated"] for row in elves["rows"])
    assert "skipped: fit_failed" in markdown


def test_mixed_seat_decks_get_a_versus_label() -> None:
    rows = [
        _row(0, 0, 0, ALPHA, BETA, ("Faeries", "Affinity"), "a"),
        _row(0, 0, 1, ALPHA, BETA, ("Faeries", "Affinity"), "b"),
        _row(0, 1, 0, ALPHA, BETA, ("Burn", "Burn"), "a"),
        _row(0, 1, 1, ALPHA, BETA, ("Burn", "Burn"), "a"),
    ]
    document, _ = _build(rows)
    assert [s["label"] for s in document["slices"]["deck"]] == ["Burn", "Faeries vs Affinity"]


def test_the_markdown_lists_each_deck() -> None:
    _, markdown = _build(ROWS)
    assert "## By deck" in markdown
    assert markdown.index("### Burn") < markdown.index("### Elves") < markdown.index("## Notes")


def test_deck_slice_seeds_stay_in_the_protocol_range() -> None:
    seeds = {leaderboard.deck_slice_seed(2**53, ordinal) for ordinal in range(8)}
    assert len(seeds) == 8 and all(0 <= seed < 2**53 for seed in seeds)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_arena_slices.py -q`
Expected: FAIL with `KeyError: 'slices'` and `AttributeError: ... has no attribute 'deck_slice_seed'`.

- [ ] **Step 3: Implement the slices**

In `leaderboard.py`:

1. Add the seed derivation next to the other stats seeds, and document it in the module docstring's seed block as `deck_slice_seed(k) = SM64(base_seed ^ 0x5350_5f44_4543_4b53 ^ k * 0x9e3779b97f4a7c15) & (2**53 - 1)`, where `k` is the slice's ordinal and the slice's own stats seeds derive from it exactly as the overall ones derive from `base_seed`:

```python
_DECK_SLICE_DOMAIN = 0x5350_5F44_4543_4B53  # "SP_DECKS"


def deck_slice_seed(base_seed: int, ordinal: int) -> int:
    mixed = (base_seed ^ _DECK_SLICE_DOMAIN ^ (ordinal * _GOLDEN_RATIO_64)) & _MASK64
    return ratings.splitmix64_next(mixed) & _MAX_JSON_INT
```

2. Rename the body of `build_leaderboard` (everything that builds `document`) to `_build_document(rows, entries, *, anchor_bot_id, base_seed, bootstrap_replicates, format) -> dict[str, Any]`. `build_leaderboard` becomes:

```python
def build_leaderboard(rows, entries, *, anchor_bot_id, base_seed, bootstrap_replicates, format):
    """Build the leaderboard JSON document and the markdown rendering."""
    document = _build_document(
        rows, entries, anchor_bot_id=anchor_bot_id, base_seed=base_seed,
        bootstrap_replicates=bootstrap_replicates, format=format,
    )
    document["slices"] = {
        "deck": _deck_slices(
            rows, entries, anchor_bot_id=anchor_bot_id, base_seed=base_seed,
            bootstrap_replicates=bootstrap_replicates, format=format,
        )
    }
    return document, render_markdown(document)
```

(keep the existing parameter annotations). Add:

```python
def _deck_label(deck: dict[str, Any]) -> str:
    if "catalog_id" in deck:
        return deck["catalog_id"]
    return "decklist " + store.sha256_hex(store.canonical_bytes(deck))[:12]


def _pairing_label(decks: Sequence[dict[str, Any]]) -> str:
    first, second = (_deck_label(deck) for deck in decks)
    return first if decks[0] == decks[1] else f"{first} vs {second}"


def _deck_slices(rows, entries, *, anchor_bot_id, base_seed, bootstrap_replicates, format) -> list[dict[str, Any]]:
    """Per-deck-pairing ratings; empty unless the ledger holds two or more pairings."""
    groups: dict[bytes, list[store.LedgerRow]] = {}
    for row in rows:
        groups.setdefault(store.canonical_bytes(list(row.decks)), []).append(row)
    if len(groups) < 2:
        return []
    slices = []
    for ordinal, key in enumerate(sorted(groups)):
        pairing_rows = groups[key]
        doc = _build_document(
            pairing_rows, entries, anchor_bot_id=anchor_bot_id,
            base_seed=deck_slice_seed(base_seed, ordinal),
            bootstrap_replicates=bootstrap_replicates, format=format,
        )
        slices.append(
            {
                "label": _pairing_label(pairing_rows[0].decks),
                "decks": list(pairing_rows[0].decks),
                "status": doc["status"],
                "fit_error": doc["fit_error"],
                "games": doc["games"],
                "rating_bootstrap": doc["bt"]["rating_bootstrap"],
                "rows": doc["rows"],
            }
        )
    return slices
```

3. Append the new line to `NOTES`.

4. In `render_markdown`, extract the main table's row formatting into `_table_row(row) -> str` and use it for the main table and each slice. After the subratings block and before `## Notes`, add:

```python
    deck_slices = document["slices"]["deck"]
    if deck_slices:
        lines += ["", "## By deck", ""]
        for deck_slice in deck_slices:
            lines += [f"### {deck_slice['label']}", ""]
            if deck_slice["status"] != "ok":
                reason = deck_slice["status"]
                if deck_slice["fit_error"]:
                    reason += f" ({deck_slice['fit_error']})"
                lines += [f"skipped: {reason}", ""]
                continue
            lines += [_TABLE_HEADER, _TABLE_RULE]
            lines += [_table_row(row) for row in deck_slice["rows"]]
            lines.append("")
```

where `_TABLE_HEADER` and `_TABLE_RULE` are the two existing header lines of the main table, now module constants used by both tables.

- [ ] **Step 4: Run the new tests, then the whole suite**

Run: `uv run pytest python/tests/test_arena_slices.py -q`
Expected: PASS (9 passed).
Run: `uv run pytest python/tests -q`
Expected: all pass (`validate` recomputes the new key, so existing end-to-end tests exercise it).

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/arena/leaderboard.py python/tests/test_arena_slices.py
git commit -m "Leaderboard: per-deck rating slices"
```

### Task 4: Benchmark definitions

**Files:**
- Create: `python/spellbench/bench/__init__.py` with exactly one line: `"""Benchmarks: definitions under benchmarks/<id>/ and their runs."""`
- Create: `python/spellbench/bench/definition.py`
- Create: `python/tests/test_bench_definition.py`

**Interfaces:**
- Consumes: `spellbench.arena.runner` default constants (`DEFAULT_ENGINE_TIMEOUT_MS`, `DEFAULT_CHOOSE_TIMEOUT_MS`, `DEFAULT_STARTUP_TIMEOUT_MS`, `DEFAULT_BOOTSTRAP_REPLICATES`, `DEFAULT_WORKERS`), `spellbench.arena.store.CONFIG_SCHEMA` and `MANIFEST_NAME`, `spellbench.wire.strict_json_loads`.
- Produces (all in `spellbench.bench.definition`):

```python
BENCHMARK_SCHEMA = "spellbench-benchmark/v1"
PROPOSED_SCHEMA = "spellbench-proposed-benchmarks/v1"
ANCHOR_BOT = "uniform"
BENCHMARK_FILE = "benchmark.json"
PROPOSED_FILE = "proposed.json"
LOCAL_VALUES_FILE = "local.json"
RUNS_DIR = "runs"
PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
RUN_NAME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-([1-9][0-9]*))?$")

class BenchmarkError(ValueError): ...

@dataclass(frozen=True)
class BotDisplay:
    label: str
    author: str
    description: str
    url: str | None

@dataclass(frozen=True)
class BenchmarkBot:
    name: str
    entry: dict[str, Any]    # the arena bot entry as written, without "display"
    display: BotDisplay

@dataclass(frozen=True)
class Benchmark:
    id: str
    title: str
    summary: str
    format: str
    engine_name: str
    engine_command: tuple[str, ...]
    engine_timeout_ms: int
    deck_pool: tuple[str, ...]
    pairs_per_deck: int
    base_seed: int
    choose_timeout_ms: int
    startup_timeout_ms: int
    bootstrap_replicates: int
    workers: int
    bots: tuple[BenchmarkBot, ...]

    def bot(self, name: str) -> BenchmarkBot | None: ...
    def tournament_config(self, tournament_dir: str) -> dict[str, Any]: ...

@dataclass(frozen=True)
class ProposedBenchmark:
    title: str
    summary: str
    needs: str

def parse_benchmark(value: Any) -> Benchmark
def load_benchmark(directory: Path) -> Benchmark            # the id must equal directory.name
def find_benchmarks(benchmarks_dir: Path) -> list[Path]     # sorted child dirs holding benchmark.json
def load_proposed(benchmarks_dir: Path) -> tuple[ProposedBenchmark, ...]   # () when proposed.json is absent
def placeholder_names(benchmark: Benchmark) -> tuple[str, ...]
def load_local_values(benchmarks_dir: Path) -> dict[str, str]              # {} when local.json is absent
def placeholder_values(names: Iterable[str], local: Mapping[str, str], environ: Mapping[str, str]) -> dict[str, str]
def substitute(text: str, values: Mapping[str, str]) -> str
def run_sort_key(name: str) -> tuple[str, int]
def published_runs(benchmark_dir: Path) -> list[Path]
def unpublished_runs(benchmark_dir: Path) -> list[Path]
def latest_run_dir(benchmark_dir: Path) -> Path | None
def next_run_name(benchmark_dir: Path, date: str) -> str
```

Rules:
- `benchmark.json` keys: required `schema, id, title, summary, format, engine, deck_pool, pairs_per_deck, base_seed, bots`; optional `choose_timeout_ms, startup_timeout_ms, bootstrap_replicates, workers` (runner defaults when absent). Any other key is an error naming it.
- `schema` equals `BENCHMARK_SCHEMA`. `id` matches `^[a-z0-9][a-z0-9-]{0,63}$`. `title`, `summary`, `format` are nonempty strings.
- `engine`: required `name` (nonempty string) and `command` (nonempty list of nonempty strings), optional `timeout_ms`; nothing else.
- `deck_pool`: nonempty list of distinct nonempty strings (catalog ids). `pairs_per_deck`: integer >= 1. `base_seed`: integer in [0, 2^53]. Optional integers: >= 1. Integers are `type(x) is int` (booleans are rejected).
- `bots`: nonempty list of objects. Each has `name` (nonempty string) and `display`, an object with exactly `label`, `author`, `description` (nonempty strings) and `url` (null, or a string that starts with `https://` or `http://` and contains no whitespace or control characters). Names are unique. The roster includes a bot named `uniform` with `"type": "builtin"`. Other bot fields pass through untouched; the arena validates them when the tournament config is parsed.
- `tournament_config(tournament_dir)` returns a fresh dict: `schema` = `store.CONFIG_SCHEMA`, `tournament_dir`, `format`, `deck_pool` = `[{"catalog_id": id} ...]`, `engine` = `{"command": [...], "timeout_ms": ...}`, `bots` = deep copies of the entries (no `display`), `pairs_per_matchup` = `pairs_per_deck * len(deck_pool)`, `base_seed`, `choose_timeout_ms`, `startup_timeout_ms`, `bootstrap_replicates`, `workers`, `rating_anchor` = `"uniform"`, `include_self_play` = `False`.
- Placeholders are `${NAME}` anywhere inside the engine command parts, subprocess bot command parts (strings in an entry's `command` list), and `checkpoint` strings. `placeholder_names` returns the sorted unique names. `placeholder_values` resolves each name from `environ` first, then `local`; an unset or empty value is unresolved; any unresolved name raises `BenchmarkError` naming every unresolved name (sorted). `substitute` replaces each placeholder verbatim (backslashes stay backslashes) and raises `BenchmarkError` on a name it has no value for.
- `local.json` lives in the benchmarks directory: a strict JSON object mapping names (matching `[A-Za-z_][A-Za-z0-9_]*`) to strings.
- `proposed.json`: `{"schema": PROPOSED_SCHEMA, "proposed": [{"title", "summary", "needs"}, ...]}`, all nonempty strings, strict keys.
- Run names: `YYYY-MM-DD` or `YYYY-MM-DD-N` with N >= 2 (the first run of a day has no suffix). `run_sort_key("2026-09-26") == ("2026-09-26", 1)`. `published_runs` lists `runs/` children whose name matches and that hold `manifest.json`, sorted by `run_sort_key`; `unpublished_runs` lists matching children without one; `latest_run_dir` is the last published run or None. `next_run_name` validates `date` (the pattern without a suffix and a real calendar date via `datetime.date.fromisoformat`) and returns the first of `date`, `date-2`, `date-3`, ... with no existing directory under `runs/`, published or not.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_bench_definition.py`:

```python
"""Benchmark definitions: parsing, placeholders, and run-directory names."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import runner
from spellbench.bench import definition
from spellbench.bench.definition import BenchmarkError


def _value(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "spellbench-benchmark/v1",
        "id": "pauper-kernel",
        "title": "Pauper on mtg-kernel",
        "summary": "Eight Pauper decks.",
        "format": "pauper-bo1",
        "engine": {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}"], "timeout_ms": 120000},
        "deck_pool": ["Burn", "Elves"],
        "pairs_per_deck": 2,
        "base_seed": 7,
        "bots": [
            {
                "name": "uniform",
                "version": "1.0.0",
                "type": "builtin",
                "seed": 11,
                "display": {"label": "random", "author": "Spellbench", "description": "Uniform.", "url": None},
            },
            {
                "name": "mybot",
                "version": "2.0",
                "type": "subprocess",
                "command": ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"],
                "checkpoint": "${CKPT_DIR}/model.bin",
                "display": {
                    "label": "My Bot",
                    "author": "someone",
                    "description": "A test bot.",
                    "url": "https://example.com/bot",
                },
            },
        ],
    }
    value.update(changes)
    return value


def _write(directory: Path, value: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "benchmark.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    return directory


def test_a_valid_definition_parses_with_runner_defaults() -> None:
    benchmark = definition.parse_benchmark(_value())
    assert benchmark.id == "pauper-kernel"
    assert benchmark.engine_name == "mtg-kernel"
    assert benchmark.engine_command == ("${MTG_KERNEL_BRIDGE}",)
    assert benchmark.deck_pool == ("Burn", "Elves")
    assert benchmark.choose_timeout_ms == runner.DEFAULT_CHOOSE_TIMEOUT_MS
    assert benchmark.startup_timeout_ms == runner.DEFAULT_STARTUP_TIMEOUT_MS
    assert benchmark.bootstrap_replicates == runner.DEFAULT_BOOTSTRAP_REPLICATES
    assert benchmark.workers == runner.DEFAULT_WORKERS
    assert [bot.name for bot in benchmark.bots] == ["uniform", "mybot"]
    assert benchmark.bot("mybot").display.url == "https://example.com/bot"
    assert "display" not in benchmark.bot("mybot").entry
    assert benchmark.bot("nobody") is None


def test_unknown_top_level_fields_are_errors() -> None:
    with pytest.raises(BenchmarkError, match="colour"):
        definition.parse_benchmark(_value(colour="blue"))


def test_missing_fields_are_errors() -> None:
    value = _value()
    del value["deck_pool"]
    with pytest.raises(BenchmarkError, match="deck_pool"):
        definition.parse_benchmark(value)


def test_unknown_display_fields_are_errors() -> None:
    value = _value()
    value["bots"][0]["display"]["colour"] = "blue"
    with pytest.raises(BenchmarkError, match="colour"):
        definition.parse_benchmark(value)


def test_the_roster_must_include_the_builtin_uniform_bot() -> None:
    value = _value()
    value["bots"] = value["bots"][1:]
    with pytest.raises(BenchmarkError, match="uniform"):
        definition.parse_benchmark(value)


def test_bot_names_are_unique() -> None:
    value = _value()
    value["bots"][1]["name"] = "uniform"
    with pytest.raises(BenchmarkError, match="unique"):
        definition.parse_benchmark(value)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x.org", "example.com", " https://x.org", "https://x.org/a b"])
def test_display_urls_must_be_plain_http_links(url: str) -> None:
    value = _value()
    value["bots"][1]["display"]["url"] = url
    with pytest.raises(BenchmarkError, match="url"):
        definition.parse_benchmark(value)


@pytest.mark.parametrize("bench_id", ["Pauper", "pauper kernel", "-x", "a/b", "", "a" * 65])
def test_ids_are_url_safe(bench_id: str) -> None:
    with pytest.raises(BenchmarkError, match="id"):
        definition.parse_benchmark(_value(id=bench_id))


@pytest.mark.parametrize("pool", [[], ["Burn", "Burn"], [""], "Burn", [1]])
def test_the_deck_pool_is_a_list_of_distinct_catalog_ids(pool: Any) -> None:
    with pytest.raises(BenchmarkError, match="deck_pool"):
        definition.parse_benchmark(_value(deck_pool=pool))


@pytest.mark.parametrize("field,bad", [("pairs_per_deck", True), ("pairs_per_deck", 0), ("base_seed", -1), ("workers", "8")])
def test_integers_are_checked(field: str, bad: Any) -> None:
    with pytest.raises(BenchmarkError, match=field):
        definition.parse_benchmark(_value(**{field: bad}))


def test_the_tournament_config_rotates_the_pool_without_self_play() -> None:
    config = definition.parse_benchmark(_value()).tournament_config("runs/2026-09-26")
    assert config["schema"] == "spellbench-tournament-config/v1"
    assert config["tournament_dir"] == "runs/2026-09-26"
    assert config["deck_pool"] == [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}]
    assert "decks" not in config
    assert config["pairs_per_matchup"] == 4
    assert config["rating_anchor"] == "uniform"
    assert config["include_self_play"] is False
    assert config["engine"] == {"command": ["${MTG_KERNEL_BRIDGE}"], "timeout_ms": 120000}
    assert config["bots"][1]["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]
    assert all("display" not in bot for bot in config["bots"])


def test_the_tournament_config_is_a_fresh_copy() -> None:
    benchmark = definition.parse_benchmark(_value())
    config = benchmark.tournament_config("runs/x")
    config["bots"][1]["command"].append("--oops")
    assert benchmark.tournament_config("runs/x")["bots"][1]["command"] == ["${PYTHON}", "--model=${CKPT_DIR}/model.bin"]


def test_load_benchmark_requires_the_folder_name_to_match_the_id(tmp_path: Path) -> None:
    assert definition.load_benchmark(_write(tmp_path / "pauper-kernel", _value())).id == "pauper-kernel"
    with pytest.raises(BenchmarkError, match="id"):
        definition.load_benchmark(_write(tmp_path / "other", _value()))


def test_load_benchmark_rejects_non_strict_json(tmp_path: Path) -> None:
    directory = tmp_path / "pauper-kernel"
    directory.mkdir()
    (directory / "benchmark.json").write_text('{"schema": 1.5}', encoding="utf-8")
    with pytest.raises(BenchmarkError):
        definition.load_benchmark(directory)


def test_find_benchmarks_lists_folders_with_a_definition_in_order(tmp_path: Path) -> None:
    _write(tmp_path / "b", _value(id="b"))
    _write(tmp_path / "a", _value(id="a"))
    (tmp_path / "c").mkdir()
    (tmp_path / "local.json").write_text("{}", encoding="utf-8")
    assert definition.find_benchmarks(tmp_path) == [tmp_path / "a", tmp_path / "b"]


def test_placeholder_names_cover_engine_bot_commands_and_checkpoints() -> None:
    benchmark = definition.parse_benchmark(_value())
    assert definition.placeholder_names(benchmark) == ("CKPT_DIR", "MTG_KERNEL_BRIDGE", "PYTHON")


def test_the_environment_beats_local_values() -> None:
    values = definition.placeholder_values(
        ["PYTHON", "CKPT_DIR", "MTG_KERNEL_BRIDGE"],
        {"PYTHON": "py-local", "CKPT_DIR": "C:\\models"},
        {"PYTHON": "py-env", "MTG_KERNEL_BRIDGE": "bridge"},
    )
    assert values == {"PYTHON": "py-env", "CKPT_DIR": "C:\\models", "MTG_KERNEL_BRIDGE": "bridge"}


def test_every_unresolved_placeholder_is_named() -> None:
    with pytest.raises(BenchmarkError) as caught:
        definition.placeholder_values(["A", "B", "C"], {"A": "x"}, {"C": ""})
    assert "B" in str(caught.value) and "C" in str(caught.value) and "'A'" not in str(caught.value)


def test_substitute_replaces_embedded_placeholders_verbatim() -> None:
    assert definition.substitute("--model=${CKPT_DIR}/model.bin", {"CKPT_DIR": "C:\\models"}) == "--model=C:\\models/model.bin"
    assert definition.substitute("no placeholders", {}) == "no placeholders"
    with pytest.raises(BenchmarkError, match="MISSING"):
        definition.substitute("${MISSING}", {})


def test_local_values_are_strict(tmp_path: Path) -> None:
    assert definition.load_local_values(tmp_path) == {}
    (tmp_path / "local.json").write_text('{"MTG_KERNEL_BRIDGE": "C:/bridge.exe"}', encoding="utf-8")
    assert definition.load_local_values(tmp_path) == {"MTG_KERNEL_BRIDGE": "C:/bridge.exe"}
    for bad in ('{"A": 1}', '{"not a name": "x"}', "[]"):
        (tmp_path / "local.json").write_text(bad, encoding="utf-8")
        with pytest.raises(BenchmarkError):
            definition.load_local_values(tmp_path)


def _run(benchmark_dir: Path, name: str, *, published: bool = True) -> Path:
    directory = benchmark_dir / "runs" / name
    directory.mkdir(parents=True)
    if published:
        (directory / "manifest.json").write_text("{}\n", encoding="utf-8")
    return directory


def test_next_run_name_takes_the_first_free_suffix(tmp_path: Path) -> None:
    assert definition.next_run_name(tmp_path, "2026-09-26") == "2026-09-26"
    _run(tmp_path, "2026-09-26")
    assert definition.next_run_name(tmp_path, "2026-09-26") == "2026-09-26-2"
    _run(tmp_path, "2026-09-26-2", published=False)  # a crashed run still takes its name
    assert definition.next_run_name(tmp_path, "2026-09-26") == "2026-09-26-3"


@pytest.mark.parametrize("date", ["2026-13-01", "26-09-2026", "2026-09-26-2", "today", "2026-02-30"])
def test_run_dates_are_real_calendar_dates(tmp_path: Path, date: str) -> None:
    with pytest.raises(BenchmarkError, match="date"):
        definition.next_run_name(tmp_path, date)


def test_the_latest_run_is_the_latest_date_then_the_highest_suffix(tmp_path: Path) -> None:
    for name in ("2026-09-25-3", "2026-09-26", "2026-09-26-2", "2026-09-26-10"):
        _run(tmp_path, name)
    (tmp_path / "runs" / "notes").mkdir()
    assert definition.latest_run_dir(tmp_path) == tmp_path / "runs" / "2026-09-26-10"
    assert [run.name for run in definition.published_runs(tmp_path)] == [
        "2026-09-25-3", "2026-09-26", "2026-09-26-2", "2026-09-26-10",
    ]


def test_unpublished_runs_are_skipped_but_listed(tmp_path: Path) -> None:
    _run(tmp_path, "2026-09-26")
    _run(tmp_path, "2026-09-27", published=False)
    assert definition.latest_run_dir(tmp_path) == tmp_path / "runs" / "2026-09-26"
    assert definition.unpublished_runs(tmp_path) == [tmp_path / "runs" / "2026-09-27"]


def test_no_runs_means_no_latest_run(tmp_path: Path) -> None:
    assert definition.latest_run_dir(tmp_path) is None
    assert definition.published_runs(tmp_path) == []


def test_proposed_benchmarks(tmp_path: Path) -> None:
    assert definition.load_proposed(tmp_path) == ()
    proposed = {
        "schema": "spellbench-proposed-benchmarks/v1",
        "proposed": [{"title": "FDN Limited", "summary": "Foundations limited.", "needs": "an engine"}],
    }
    (tmp_path / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8")
    assert definition.load_proposed(tmp_path) == (
        definition.ProposedBenchmark(title="FDN Limited", summary="Foundations limited.", needs="an engine"),
    )
    proposed["proposed"][0]["colour"] = "blue"
    (tmp_path / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="colour"):
        definition.load_proposed(tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_bench_definition.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'spellbench.bench'`.

- [ ] **Step 3: Implement `definition.py`**

Write the module to the Interfaces and Rules above. Implementation notes:
- Read files with `path.read_bytes()` and parse with `spellbench.wire.strict_json_loads` (which rejects floats, duplicate keys, and non-object tops); wrap its `MalformedJsonError` and `OSError` as `BenchmarkError` naming the file.
- Collect missing and unknown keys the way `runner._bot_spec_from_json` does: `f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}"`.
- `substitute` must use a function replacement so backslashes in values are copied verbatim:

```python
def substitute(text: str, values: Mapping[str, str]) -> str:
    """``text`` with each ``${NAME}`` replaced by ``values[NAME]`` verbatim."""

    def value_of(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise BenchmarkError(f"no value for placeholder ${{{name}}}")
        return values[name]

    return PLACEHOLDER_PATTERN.sub(value_of, text)
```

- `placeholder_values`:

```python
def placeholder_values(
    names: Iterable[str], local: Mapping[str, str], environ: Mapping[str, str]
) -> dict[str, str]:
    """Resolve each name from the environment first, then local.json."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in sorted(set(names)):
        value = environ.get(name) or local.get(name)
        if value:
            values[name] = value
        else:
            missing.append(name)
    if missing:
        raise BenchmarkError(
            f"unresolved placeholders {missing}: set them in the environment or in benchmarks/{LOCAL_VALUES_FILE}"
        )
    return values
```

- `find_benchmarks` returns `sorted(child for child in benchmarks_dir.iterdir() if (child / BENCHMARK_FILE).is_file())` (an empty list when the directory is missing).
- `load_benchmark` raises `BenchmarkError(f"{directory}: id {benchmark.id!r} does not match the folder name {directory.name!r}")` on a mismatch.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest python/tests/test_bench_definition.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/bench/__init__.py python/spellbench/bench/definition.py python/tests/test_bench_definition.py
git commit -m "Benchmarks: definitions, placeholders, and run names"
```

### Task 5: The Hero table

**Files:**
- Create: `python/spellbench/site/__init__.py` with exactly one line: `"""Static benchmark site: the Hero table, HTML rendering, and the build."""`
- Create: `python/spellbench/site/hero.py`
- Create: `python/tests/test_site_hero.py`

**Interfaces:**
- Consumes: leaderboard documents (`leaderboard.json`): `status`, `anchor.name`, and `rows[*]` with `name`, `rated`, `elo_milli`, `ci95_elo_milli`.
- Produces:

```python
ANCHOR_NAME = "uniform"
Z95 = 1.96

@dataclass(frozen=True)
class HeroChip:
    benchmark_id: str
    margin: float            # Elo above the anchor in that benchmark
    lower: float | None      # interval bounds in the same units; None without an interval
    upper: float | None

@dataclass(frozen=True)
class HeroRow:
    name: str
    score: float
    lower: float | None
    upper: float | None
    approximate: bool        # combined from several benchmarks
    reference: bool          # the anchor's row, fixed at 0
    chips: tuple[HeroChip, ...]

@dataclass(frozen=True)
class HeroTable:
    rows: tuple[HeroRow, ...]
    benchmark_ids: tuple[str, ...]   # benchmarks in the chart, input order
    warnings: tuple[str, ...]

def hero_table(
    leaderboards: Sequence[tuple[str, Mapping[str, Any]]], *, anchor_name: str = ANCHOR_NAME
) -> HeroTable
```

Rules (spec section 3):
- A benchmark enters the chart when its document's `anchor.name == anchor_name` and `status == "ok"`. Otherwise it is left out with a warning naming the benchmark id and the reason (`anchored on 'heuristic', not 'uniform'`, or `leaderboard status 'fit_failed'`).
- Within an included benchmark, each rated row other than the anchor contributes a chip: `margin = (elo_milli - 1_000_000) / 1000`, bounds `(ci95_elo_milli[k] - 1_000_000) / 1000`, or None when `ci95_elo_milli` is null. Unrated rows contribute nothing. Bots match across benchmarks by `name`.
- A bot's score is `math.fsum(margins) / n` over its n chips. With n == 1 the interval is that chip's interval (asymmetric intervals stay asymmetric) and `approximate` is False. With n >= 2: `approximate` is True; if any chip lacks an interval, `lower` and `upper` are None; else `se = math.sqrt(math.fsum(((c.upper - c.lower) / (2 * Z95)) ** 2 for c in chips)) / n` and the interval is `score -/+ Z95 * se`.
- The anchor's reference row (`reference=True`, score, lower, upper all 0.0, one 0.0 chip per included benchmark) is present when at least one benchmark is included.
- Rows are sorted by `(-score, name)`; chips follow the input benchmark order.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_site_hero.py`:

```python
"""The Hero table: Elo above the random bot, averaged across benchmarks."""

from __future__ import annotations

import math
from typing import Any

import pytest

from spellbench.site.hero import HeroChip, hero_table


def _row(name: str, elo: int, ci: tuple[int, int] | None, rated: bool = True) -> dict[str, Any]:
    return {"name": name, "rated": rated, "elo_milli": elo if rated else None, "ci95_elo_milli": None if ci is None else list(ci)}


def _board(*rows: dict[str, Any], anchor: str = "uniform", status: str = "ok") -> dict[str, Any]:
    """A leaderboard document reduced to the fields the Hero table reads."""
    anchor_row = _row(anchor, 1_000_000, (1_000_000, 1_000_000))
    return {"status": status, "anchor": {"bot_id": "a" * 64, "name": anchor, "version": "1.0.0"}, "rows": [anchor_row, *rows]}


def _by_name(table) -> dict[str, Any]:
    return {row.name: row for row in table.rows}


def test_one_benchmark_uses_its_own_interval() -> None:
    table = hero_table([("pauper", _board(_row("heuristic", 1_101_000, (1_052_000, 1_150_500))))])
    row = _by_name(table)["heuristic"]
    assert (row.score, row.lower, row.upper, row.approximate, row.reference) == (101.0, 52.0, 150.5, False, False)
    assert row.chips == (HeroChip("pauper", 101.0, 52.0, 150.5),)
    assert table.benchmark_ids == ("pauper",) and table.warnings == ()


def test_random_is_the_reference_row_at_zero_and_rows_rank_by_score() -> None:
    table = hero_table(
        [("pauper", _board(_row("first", 985_000, (950_000, 1_020_000)), _row("heuristic", 1_101_000, (1_050_000, 1_150_000))))]
    )
    assert [row.name for row in table.rows] == ["heuristic", "uniform", "first"]
    reference = _by_name(table)["uniform"]
    assert (reference.score, reference.lower, reference.upper, reference.reference) == (0.0, 0.0, 0.0, True)
    assert reference.chips == (HeroChip("pauper", 0.0, 0.0, 0.0),)


def test_two_benchmarks_average_and_combine_standard_errors() -> None:
    # Half-widths 39.2 and 58.8 Elo are standard errors of 20 and 30.
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_060_800, 1_139_200)))),
            ("b", _board(_row("heuristic", 1_200_000, (1_141_200, 1_258_800)))),
        ]
    )
    row = _by_name(table)["heuristic"]
    se = math.sqrt(20.0**2 + 30.0**2) / 2
    assert row.score == pytest.approx(150.0)
    assert row.lower == pytest.approx(150.0 - 1.96 * se)
    assert row.upper == pytest.approx(150.0 + 1.96 * se)
    assert row.approximate is True
    assert [chip.benchmark_id for chip in row.chips] == ["a", "b"]


def test_a_bot_in_one_of_two_benchmarks_keeps_that_interval() -> None:
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_060_800, 1_139_200)))),
            ("b", _board(_row("g115", 1_420_000, (1_380_000, 1_470_000)))),
        ]
    )
    row = _by_name(table)["g115"]
    assert (row.score, row.lower, row.upper, row.approximate) == (420.0, 380.0, 470.0, False)


def test_an_unanchored_benchmark_is_left_out_with_a_warning() -> None:
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_060_800, 1_139_200)))),
            ("x", _board(_row("uniform", 900_000, (850_000, 950_000)), anchor="heuristic")),
        ]
    )
    assert table.benchmark_ids == ("a",)
    assert len(table.warnings) == 1 and "x" in table.warnings[0] and "heuristic" in table.warnings[0]
    assert all(chip.benchmark_id == "a" for row in table.rows for chip in row.chips)


def test_a_benchmark_whose_fit_failed_is_left_out_with_a_warning() -> None:
    table = hero_table([("a", _board(status="fit_failed"))])
    assert table.rows == () and table.benchmark_ids == ()
    assert "fit_failed" in table.warnings[0]


def test_missing_intervals_propagate() -> None:
    single = _by_name(hero_table([("a", _board(_row("heuristic", 1_100_000, None)))]))["heuristic"]
    assert (single.lower, single.upper, single.approximate) == (None, None, False)
    double = _by_name(
        hero_table(
            [
                ("a", _board(_row("heuristic", 1_100_000, None))),
                ("b", _board(_row("heuristic", 1_200_000, (1_141_200, 1_258_800)))),
            ]
        )
    )["heuristic"]
    assert (double.lower, double.upper, double.approximate) == (None, None, True)


def test_unrated_rows_are_skipped_and_ties_break_by_name() -> None:
    table = hero_table(
        [
            (
                "a",
                _board(
                    _row("zeta", 1_050_000, (1_000_000, 1_100_000)),
                    _row("alpha", 1_050_000, (1_000_000, 1_100_000)),
                    _row("ghost", 0, None, rated=False),
                ),
            )
        ]
    )
    assert [row.name for row in table.rows] == ["alpha", "zeta", "uniform"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_site_hero.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'spellbench.site'`.

- [ ] **Step 3: Implement `hero.py`**

```python
"""The Hero table: each bot's Elo above the random bot, across benchmarks.

For bot ``i`` in benchmark ``b``, ``margin(i, b)`` is its Elo display minus
1000 (the anchor, the builtin ``uniform`` bot, is fixed at 1000), with the
interval from ``b``'s leaderboard. The Hero score is the mean margin over
the benchmarks ``i`` entered. One benchmark keeps its own interval; several
combine per-benchmark standard errors (half-width / 1.96) as
``sqrt(sum(se^2)) / n``, an approximation the site labels as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ANCHOR_NAME = "uniform"
Z95 = 1.96
_ANCHOR_ELO_MILLI = 1_000_000


# (dataclasses exactly as in the Interfaces block)


def _elo_above_anchor(elo_milli: int) -> float:
    return (elo_milli - _ANCHOR_ELO_MILLI) / 1000


def hero_table(
    leaderboards: Sequence[tuple[str, Mapping[str, Any]]], *, anchor_name: str = ANCHOR_NAME
) -> HeroTable:
    """Rank bots by mean Elo above ``anchor_name`` over the benchmarks they entered."""
    chips: dict[str, list[HeroChip]] = {}
    included: list[str] = []
    warnings: list[str] = []
    for benchmark_id, document in leaderboards:
        anchor = document["anchor"]["name"]
        if anchor != anchor_name:
            warnings.append(
                f"{benchmark_id}: anchored on {anchor!r}, not {anchor_name!r}; left out of the Hero chart"
            )
            continue
        if document["status"] != "ok":
            warnings.append(
                f"{benchmark_id}: leaderboard status {document['status']!r}; left out of the Hero chart"
            )
            continue
        included.append(benchmark_id)
        for row in document["rows"]:
            if not row["rated"] or row["name"] == anchor_name:
                continue
            interval = row["ci95_elo_milli"]
            chips.setdefault(row["name"], []).append(
                HeroChip(
                    benchmark_id=benchmark_id,
                    margin=_elo_above_anchor(row["elo_milli"]),
                    lower=None if interval is None else _elo_above_anchor(interval[0]),
                    upper=None if interval is None else _elo_above_anchor(interval[1]),
                )
            )
    rows = [_combine(name, tuple(bot_chips)) for name, bot_chips in chips.items()]
    if included:
        rows.append(
            HeroRow(
                name=anchor_name, score=0.0, lower=0.0, upper=0.0, approximate=False, reference=True,
                chips=tuple(HeroChip(benchmark_id, 0.0, 0.0, 0.0) for benchmark_id in included),
            )
        )
    rows.sort(key=lambda row: (-row.score, row.name))
    return HeroTable(rows=tuple(rows), benchmark_ids=tuple(included), warnings=tuple(warnings))


def _combine(name: str, chips: tuple[HeroChip, ...]) -> HeroRow:
    count = len(chips)
    score = math.fsum(chip.margin for chip in chips) / count
    if count == 1:
        return HeroRow(name, score, chips[0].lower, chips[0].upper, False, False, chips)
    if any(chip.lower is None or chip.upper is None for chip in chips):
        return HeroRow(name, score, None, None, True, False, chips)
    se = math.sqrt(math.fsum(((chip.upper - chip.lower) / (2 * Z95)) ** 2 for chip in chips)) / count
    return HeroRow(name, score, score - Z95 * se, score + Z95 * se, True, False, chips)
```

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest python/tests/test_site_hero.py -q`
Expected: PASS (8 passed).
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/site/__init__.py python/spellbench/site/hero.py python/tests/test_site_hero.py
git commit -m "Site: the Hero table"
```

### Task 6: The site renderer

**Files:**
- Create: `python/spellbench/site/__init__.py` with exactly one line: `"""Static benchmark site: the Hero table, HTML rendering, and the build."""` (Task 5 creates the same bytes; keep them identical)
- Create: `python/spellbench/site/render.py`
- Create: `python/tests/test_site_render.py`

**Interfaces:**
- Consumes: view-model dicts (below). No other module: the renderer is pure.
- Produces:

```python
def render_home(view: Mapping[str, Any]) -> str       # index.html at the site root
def render_benchmark(view: Mapping[str, Any]) -> str  # b/<id>/index.html
def render_join(view: Mapping[str, Any]) -> str       # join.html at the site root
def render_method(view: Mapping[str, Any]) -> str     # method.html at the site root
def format_elo(elo_milli: int) -> str                 # f"{elo_milli / 1000:.0f}": 1_101_499 -> "1101"
def format_margin(value: float) -> str                # round(value): "+101", "\u221215" (U+2212 minus), "0"
def format_share(score: float) -> str                 # f"{score * 100:.0f}%": 0.6 -> "60%"
```

View models (the same contract appears in Task 8, which builds them):

```python
SiteView = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": "https://github.com/jackmaiorino/spellbench"}

HomeView = {
    "site": SiteView,
    "hero": {
        "rows": [HeroRowView, ...],    # ranked; may be empty
        "benchmark_count": int,        # benchmarks in the chart
        "approximate": bool,           # some row combines several benchmarks
    },
    "benchmarks": [BenchmarkCardView, ...],   # sorted by id
    "proposed": [ProposedCardView, ...],      # file order
}
HeroRowView = {
    "name": str, "label": str, "author": str,
    "score": float, "lower": float | None, "upper": float | None,
    "approximate": bool, "reference": bool,
    "chips": [{"benchmark_id": str, "margin": float}, ...],
}
BenchmarkCardView = {
    "id": str, "title": str, "summary": str, "engine_name": str,
    "deck_count": int, "bot_count": int,
    "games": int | None,       # None: no published run yet
    "run_name": str | None,    # "2026-09-26" or "2026-09-26-2"; None: no run
    "href": str | None,        # "b/<id>/index.html", relative to the site root; None: no run
}
ProposedCardView = {"title": str, "summary": str, "needs": str}

BenchmarkPageView = {
    "site": SiteView,
    "id": str, "title": str, "summary": str, "format": str,
    "engine": {"name": str, "version": str, "source_revision": str | None, "rules_snapshot_id": str, "card_pool_identity": str},
    "decks": [str, ...],       # deck labels in pool order
    "pairs_per_deck": int,
    "run": {
        "name": str,
        "games": {"total": int, "rated": int, "forfeit": int, "truncated": int, "halted": int},
        "manifest_sha256": str,
        "files": [{"name": str, "href": str, "bytes": int}, ...],   # href relative to the page: "run/matches.jsonl"
        "validate_command": str,                                     # "spellbench validate benchmarks/<id>/runs/<name>"
    },
    "overall": [LeaderRowView, ...],                                           # leaderboard order
    "deck_tables": [{"label": str, "status": str, "reason": str | None, "rows": [LeaderRowView, ...]}, ...],
    "style_tables": [{"tag": str, "rows": [LeaderRowView, ...]}, ...],        # sorted by tag; rows keep overall order and ranks
    "grid": {
        "names": [str, ...],    # bots in overall order
        "labels": [str, ...],   # their display labels
        "cells": [[GridCell | None, ...], ...],   # cells[i][j]: bot i against bot j; None on the diagonal or with no complete pair
    },
}
LeaderRowView = {
    "rank": int | None, "name": str, "label": str, "author": str, "url": str | None, "description": str,
    "tags": [str, ...], "anchor": bool,
    "elo_milli": int | None, "ci_elo_milli": [int, int] | None,
    "wins": int, "draws": int, "losses": int, "games": int, "forfeits": int,
}
GridCell = {"score": float, "games": int}   # bot i's share of the points against bot j, 0..1

InfoPageView = {"site": SiteView}   # join and method pages
```

Markup contract (tests and Task 8 rely on it):
- Every page is a complete document: `<!doctype html>`, `<html lang="en">`, `<meta charset="utf-8">`, `<meta name="viewport" content="width=device-width, initial-scale=1">`, `<meta name="color-scheme" content="light dark">`, a `<title>`, one inline `<style>`, and it ends with `</html>\n`. No `\r`, no U+2014.
- Links are relative and explicit: root pages link `index.html`, `join.html`, `method.html`, `b/<id>/index.html`; benchmark pages link `../../index.html`, `../../join.html`, `../../method.html`, and their run files by `run["files"][*]["href"]`. Never link a bare directory.
- Header on every page: the wordmark, the tagline, and navigation (Leaderboard `index.html#hero`, Benchmarks `index.html#benchmarks`, Join, Method). Footer: "Every rating is re-derived from a committed match ledger with spellbench validate." and a link to `repo_url`.
- Home: `<section id="hero">` with the heading "Elo above the random bot", the subtitle "Each bot's Elo minus the random bot's, averaged over the benchmarks it entered. Bars show 95% intervals. The score compares skill above random across formats, not head-to-head results.", and when `approximate` the note "Intervals that combine several benchmarks are approximate." The rows are `<ol class="hero">` with one `<li data-bot="NAME">` per row: label and author, an inline SVG bar on a scale shared by all rows (zero line dashed; bar from 0 to the score, accent color when positive and warning color when negative; a whisker from lower to upper when both exist), the value `format_margin(score)`, and one chip per benchmark reading `"<benchmark_id> <format_margin(margin)>"`. The reference row reads "random" (its label) with "reference" and shows `0`. With no rows, show "No rated benchmark yet." instead of the list. Then the call to action: "Put your model on the benchmark", "Speak the Spellbench protocol, send us your bot, get rated.", and a link "How to join \u2192" to `join.html`. Then `<section id="benchmarks">`: a card per benchmark (title linked to `href` when not None; `engine_name`, deck count, bot count, games; "Latest run <run_name>" or "No published run yet"), then a dashed card per proposed benchmark ("Proposed", "needs <needs>", summary).
- Benchmark page: title, summary, meta line `"engine <name> <version> \u00b7 <N> decks \u00b7 same deck in both seats"`, download links for every run file plus "validated \u2713". Three tabs in a `<div data-tabs>`: Overall, By deck, By training style. The tab bar (`role="tablist"`, buttons `role="tab"`) is `hidden` in the HTML and revealed by the inline script, which also hides the inactive panels (`role="tabpanel"`); without script every panel shows, each with its own heading. Panels: `<section data-panel="overall">`; one `<section data-panel="deck" data-deck="LABEL">` per deck table; one `<section data-panel="style" data-tag="TAG">` per style table. Each leaderboard is a `<table>` with one `<tr data-bot="NAME">` per row whose cells show: rank (or "-"), label (linked when `url` starts with `http://` or `https://`) with its tags as chips and the author beneath, `format_elo(elo_milli)` (or "unrated"), an inline SVG interval bar on a scale shared by that table's rows (dot at the estimate, line from lower to upper; accent above 1000, warning below, muted for the anchor), W-D-L as `"<wins>-<draws>-<losses>"`, games, forfeits. A deck table whose status is not "ok" shows "Not rated: <reason or status>" instead of a table. With no deck tables the By deck panel says "This benchmark uses one deck pairing; see Overall."; with no style tables the By training style panel says "No training-style tags yet.". The anchor row is marked "anchor". Then the matchup grid: `<table class="grid">` with row and column headers from `labels`, and `<td data-row="NAME_I" data-col="NAME_J">` cells (attributes in that order, on every cell including empty ones) showing `format_share(score)` with `games` in the title attribute, tinted toward the accent color above 50% and the warning color below (use `color-mix(in srgb, var(--accent) N%, transparent)`), and an empty muted cell for None. Then engine identity (name, version, source revision, rules snapshot, card pool) and a "Re-check this run" box with `validate_command` and the manifest sha256.
- Join page (placeholder until sub-project D): "Put your model on the benchmark"; a paragraph: "Spellbench is a small protocol. The arena sends your bot one decision at a time as a line of JSON listing the legal choices, and your bot answers with the one it picks. Any language works: your bot is its own process reading standard input and writing standard output."; a list: read the protocol spec (`repo_url + "/blob/main/spec/SPELLBENCH_PROTOCOL_V1.md"`), start from the README's "Write a bot" section (`repo_url + "#write-a-bot"`), play your bot against the builtin bots with `spellbench run`; and "A submission guide and form are on the way. Until then, open an issue on the repository." linking `repo_url + "/issues"`.
- Method page ("How ratings work"), sections and copy:
  - Games: "Each benchmark is a round robin. Every matchup is played as pairs of games that share one random seed with the seats swapped, so both bots face the same shuffles. Each pair uses the next deck of the benchmark's pool in both seats, and a bot never plays itself."
  - What counts: "Wins, losses, and draws count. A bot that times out, crashes, or answers with an illegal choice forfeits that game, and a forfeit counts as a loss. Games the engine halts or stops at its step limit are recorded and left out."
  - Ratings: "Ratings come from a Bradley-Terry fit over complete seat-swapped pairs. A draw counts as half a win, and every matchup gets one extra virtual draw so a perfect record still has a finite rating. The random bot is the anchor: its Elo is fixed at 1000. The 95% intervals come from a bootstrap that resamples whole pairs within each matchup."
  - By deck: "Each deck's table is the same fit run on that deck's games alone, still anchored on the random bot."
  - Hero score: "A bot's Hero score is its Elo above the random bot, averaged over the benchmarks it entered. With one benchmark, its interval is that benchmark's interval. With several, the per-benchmark errors are combined as if independent, so the interval is approximate. The Hero score compares skill above random across formats; it is not a head-to-head result."
  - Check it yourself: "Every number on this site is re-derived from a committed match ledger. Clone the repository and run spellbench validate benchmarks/<id>/runs/<date>: it checks every file's hash and recomputes every rating from the ledger."

Design (follow the approved mockup at `.superpowers/sdd/2026-09-26-benchmark-site-plan/approved-mockup.html` in the main checkout: cards, muted secondary text, accent chips, the Elo interval rows):
- One inline stylesheet. Tokens on `:root` (light): `--bg #ffffff`, `--surface #f6f7f9`, `--text #1d2026`, `--muted #5d6470`, `--border #d9dde3`, `--accent #2a78d6`, `--accent-soft #e3eefb`, `--warn #eb6834`, `--good #1f8a4c`. Dark values (`--bg #111418`, `--surface #1a1e24`, `--text #e7eaee`, `--muted #9aa3ad`, `--border #2c323a`, `--accent #5b9df0`, `--accent-soft #1d2a3b`, `--warn #f08a5d`, `--good #4cc27f`) under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }` and again under `:root[data-theme="dark"] { ... }`. `body` sets `background: var(--bg)` and `color: var(--text)`, the system font stack, and no external font.
- A centered column (`max-width: 960px`) with a 16px side gutter; nothing scrolls horizontally at 375 px (wide tables sit in an `overflow-x: auto` wrapper).
- SVG coordinates are formatted with one decimal (`f"{x:.1f}"`) so output is stable; every SVG has `role="img"` and an `aria-label` stating the value and interval.
- Escape every data string with `html.escape(value, quote=True)`, attribute values included. A `url` that does not start with `http://` or `https://` is shown as text, never as a link.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_site_render.py`:

```python
"""The site renderer: pure HTML from view-model dicts."""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from spellbench.site import render

SITE = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": "https://github.com/jackmaiorino/spellbench"}


def _leader(name: str, label: str, rank: int | None, elo: int | None, ci: list[int] | None, **extra: Any) -> dict[str, Any]:
    row = {
        "rank": rank, "name": name, "label": label, "author": "Spellbench", "url": None, "description": f"{label} bot",
        "tags": ["baseline"], "anchor": name == "uniform", "elo_milli": elo, "ci_elo_milli": ci,
        "wins": 10, "draws": 2, "losses": 4, "games": 16, "forfeits": 1,
    }
    row.update(extra)
    return row


OVERALL = [
    _leader("heuristic", "heuristic", 1, 1_101_499, [1_052_000, 1_150_500], tags=["heuristic"]),
    _leader("uniform", "random", 2, 1_000_000, [1_000_000, 1_000_000]),
    _leader("first", "first", 3, 985_000, [950_000, 1_020_000]),
]

HOME: dict[str, Any] = {
    "site": SITE,
    "hero": {
        "rows": [
            {"name": "heuristic", "label": "heuristic", "author": "Spellbench", "score": 101.4, "lower": 52.0, "upper": 150.5,
             "approximate": False, "reference": False, "chips": [{"benchmark_id": "pauper-kernel", "margin": 101.4}]},
            {"name": "uniform", "label": "random", "author": "Spellbench", "score": 0.0, "lower": 0.0, "upper": 0.0,
             "approximate": False, "reference": True, "chips": [{"benchmark_id": "pauper-kernel", "margin": 0.0}]},
            {"name": "first", "label": "first", "author": "Spellbench", "score": -15.2, "lower": -50.0, "upper": 20.0,
             "approximate": False, "reference": False, "chips": [{"benchmark_id": "pauper-kernel", "margin": -15.2}]},
        ],
        "benchmark_count": 1,
        "approximate": False,
    },
    "benchmarks": [
        {"id": "pauper-kernel", "title": "Pauper \u00b7 mtg-kernel", "summary": "Eight Pauper decks.", "engine_name": "mtg-kernel",
         "deck_count": 8, "bot_count": 3, "games": 192, "run_name": "2026-09-26", "href": "b/pauper-kernel/index.html"},
        {"id": "new-one", "title": "New benchmark", "summary": "Not run yet.", "engine_name": "gorge",
         "deck_count": 2, "bot_count": 2, "games": None, "run_name": None, "href": None},
    ],
    "proposed": [{"title": "FDN Limited", "summary": "Foundations limited games.", "needs": "an engine"}],
}

BENCH: dict[str, Any] = {
    "site": SITE,
    "id": "pauper-kernel",
    "title": "Pauper \u00b7 mtg-kernel",
    "summary": "Eight Pauper decks.",
    "format": "pauper-bo1",
    "engine": {"name": "mtg-kernel", "version": "0.4.0", "source_revision": "abc123", "rules_snapshot_id": "rules-1", "card_pool_identity": "pool-1"},
    "decks": ["Burn", "Elves"],
    "pairs_per_deck": 4,
    "run": {
        "name": "2026-09-26",
        "games": {"total": 192, "rated": 190, "forfeit": 1, "truncated": 1, "halted": 1},
        "manifest_sha256": "f" * 64,
        "files": [{"name": "matches.jsonl", "href": "run/matches.jsonl", "bytes": 12345},
                  {"name": "manifest.json", "href": "run/manifest.json", "bytes": 999}],
        "validate_command": "spellbench validate benchmarks/pauper-kernel/runs/2026-09-26",
    },
    "overall": OVERALL,
    "deck_tables": [
        {"label": "Burn", "status": "ok", "reason": None, "rows": OVERALL},
        {"label": "Elves", "status": "fit_failed", "reason": "reference id is absent", "rows": []},
    ],
    "style_tables": [{"tag": "baseline", "rows": OVERALL[1:]}, {"tag": "heuristic", "rows": OVERALL[:1]}],
    "grid": {
        "names": ["heuristic", "uniform", "first"],
        "labels": ["heuristic", "random", "first"],
        "cells": [
            [None, {"score": 0.6, "games": 64}, {"score": 0.7, "games": 64}],
            [{"score": 0.4, "games": 64}, None, {"score": 0.55, "games": 64}],
            [{"score": 0.3, "games": 64}, {"score": 0.45, "games": 64}, None],
        ],
    },
}

INFO = {"site": SITE}


def _pages() -> dict[str, str]:
    return {
        "home": render.render_home(HOME),
        "benchmark": render.render_benchmark(BENCH),
        "join": render.render_join(INFO),
        "method": render.render_method(INFO),
    }


def _element(page: str, tag: str, attribute: str, value: str) -> str:
    match = re.search(rf'<{tag}\b[^>]*\b{attribute}="{re.escape(value)}"[^>]*>(.*?)</{tag}>', page, re.S)
    assert match, f"no <{tag} {attribute}={value!r}>"
    return re.sub(r"<[^>]+>", " ", match.group(1))


def test_format_helpers() -> None:
    assert render.format_elo(1_101_499) == "1101"
    assert render.format_elo(985_000) == "985"
    assert render.format_margin(101.4) == "+101"
    assert render.format_margin(-15.2) == "\u221215"
    assert render.format_margin(0.2) == "0" and render.format_margin(-0.4) == "0"
    assert render.format_share(0.6) == "60%" and render.format_share(0.333) == "33%"


def test_pages_are_complete_documents() -> None:
    for name, page in _pages().items():
        assert page.startswith("<!doctype html>"), name
        assert page.endswith("</html>\n"), name
        assert '<meta name="viewport"' in page and "<title>" in page, name
        assert "\r" not in page and "\u2014" not in page, name


def test_rendering_is_deterministic() -> None:
    assert _pages() == _pages()


def test_no_external_resources() -> None:
    for name, page in _pages().items():
        assert not re.search(r'\bsrc="(?:https?:)?//', page), name
        assert "<link" not in page and "@import" not in page, name


def test_hero_rows_show_label_and_margin() -> None:
    home = _pages()["home"]
    assert "+101" in _element(home, "li", "data-bot", "heuristic")
    assert "\u221215" in _element(home, "li", "data-bot", "first")
    reference = _element(home, "li", "data-bot", "uniform")
    assert "random" in reference and "0" in reference


def test_leaderboard_rows_show_the_formatted_numbers() -> None:
    page = _pages()["benchmark"]
    overall = page[page.index('data-panel="overall"'):]
    for row in OVERALL:
        text = _element(overall, "tr", "data-bot", row["name"])
        assert render.format_elo(row["elo_milli"]) in text
        assert f'{row["wins"]}-{row["draws"]}-{row["losses"]}' in text


def test_the_grid_shows_shares() -> None:
    page = _pages()["benchmark"]
    cell = re.search(r'<td\b[^>]*data-row="heuristic"[^>]*data-col="uniform"[^>]*>(.*?)</td>', page, re.S)
    assert cell and "60%" in cell.group(1)
    assert page.count('data-col="first"') == 3  # one cell per row, the diagonal included


def test_every_deck_and_style_gets_a_panel() -> None:
    page = _pages()["benchmark"]
    assert 'data-deck="Burn"' in page and 'data-deck="Elves"' in page
    assert "Not rated: reference id is absent" in page
    assert 'data-tag="baseline"' in page and 'data-tag="heuristic"' in page


def test_links_between_pages() -> None:
    pages = _pages()
    assert 'href="b/pauper-kernel/index.html"' in pages["home"]
    assert 'href="join.html"' in pages["home"] and 'href="method.html"' in pages["home"]
    assert 'href="../../index.html"' in pages["benchmark"]
    assert 'href="run/matches.jsonl"' in pages["benchmark"]


def test_a_benchmark_without_a_run_has_an_unlinked_card() -> None:
    home = _pages()["home"]
    assert "New benchmark" in home and "No published run yet" in home
    assert "b/new-one/" not in home


def test_proposed_cards() -> None:
    home = _pages()["home"]
    assert "FDN Limited" in home and "Proposed" in home and "an engine" in home


def test_an_empty_hero_says_so() -> None:
    view = copy.deepcopy(HOME)
    view["hero"] = {"rows": [], "benchmark_count": 0, "approximate": False}
    assert "No rated benchmark yet." in render.render_home(view)


def test_approximate_intervals_are_labelled() -> None:
    view = copy.deepcopy(HOME)
    view["hero"]["approximate"] = True
    assert "approximate" in render.render_home(view)


@pytest.mark.parametrize("hostile", ['<script>alert("x")</script>', '" onmouseover="alert(1)'])
def test_hostile_text_is_escaped(hostile: str) -> None:
    home = copy.deepcopy(HOME)
    home["hero"]["rows"][0]["label"] = hostile
    home["benchmarks"][0]["title"] = hostile
    bench = copy.deepcopy(BENCH)
    bench["overall"][0]["label"] = hostile
    bench["overall"][0]["author"] = hostile
    bench["grid"]["labels"][0] = hostile
    for page in (render.render_home(home), render.render_benchmark(bench)):
        assert "<script>alert" not in page
        assert 'onmouseover="alert' not in page


def test_only_http_urls_become_links() -> None:
    bench = copy.deepcopy(BENCH)
    bench["overall"][0]["url"] = "javascript:alert(1)"
    bench["overall"][2]["url"] = "https://example.com/first"
    page = render.render_benchmark(bench)
    assert 'href="javascript:' not in page
    assert 'href="https://example.com/first"' in page


def test_the_method_page_explains_the_rating() -> None:
    method = _pages()["method"]
    for phrase in ("seat", "forfeit", "virtual draw", "anchor", "Hero score", "spellbench validate"):
        assert phrase in method
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_site_render.py -q`
Expected: FAIL at collection with `ModuleNotFoundError` (`spellbench.site` or `spellbench.site.render`).

- [ ] **Step 3: Implement `render.py`**

Build the four pages to the markup contract and design notes above. Suggested structure: one private `_page(title, depth, body, site)` that emits the document shell (head, style, header, footer, and the tab script when the page has tabs), where `depth` is 0 for root pages and 2 for benchmark pages and prefixes every cross-page link with `"../" * depth`; small helpers `_e` (escape), `_link(url, text)` (links only for `http://` and `https://`), `_scale(values)` (min and max padded 8%, never a zero span), `_hero_bar(row, scale)`, `_interval_bar(row, scale)`, `_leader_table(rows)`, `_grid(grid)`. The tab script, verbatim:

```html
<script>
document.querySelectorAll("[data-tabs]").forEach(function (root) {
  var tabs = root.querySelectorAll('[role="tab"]');
  var panels = root.querySelectorAll('[role="tabpanel"]');
  root.querySelector('[role="tablist"]').hidden = false;
  function show(index) {
    tabs.forEach(function (tab, i) { tab.setAttribute("aria-selected", String(i === index)); });
    panels.forEach(function (panel, i) { panel.hidden = i !== index; });
  }
  tabs.forEach(function (tab, i) { tab.addEventListener("click", function () { show(i); }); });
  show(0);
});
</script>
```

Keep the page copy exactly as the contract gives it; write any extra microcopy in the same plain style (no em-dashes).

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest python/tests/test_site_render.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Look at the pages**

Write the four fixture pages to a scratch directory outside the repo (for example with a short script that imports the test module's `HOME`, `BENCH`, `INFO`) and open them in a browser at desktop width and at 375 px, light and dark. Fix anything that looks broken or cramped. Record what you checked in the report.

- [ ] **Step 6: Commit**

```bash
git add python/spellbench/site/__init__.py python/spellbench/site/render.py python/tests/test_site_render.py
git commit -m "Site: static HTML renderer"
```

### Task 7: Benchmark runs and `spellbench bench run`

**Files:**
- Create: `python/spellbench/bench/run.py`
- Modify: `python/spellbench/arena/cli.py` (the `bench` subcommand and usage text)
- Create: `python/tests/test_bench_run.py`
- Create: `benchmarks/pauper-kernel/benchmark.json`, `benchmarks/proposed.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 1 and 2 runner (`deck_pool`, `include_self_play`, `run_tournament(config, *, resolve=..., output_dir=...)`), `spellbench.arena.validate.validate_tournament_dir`, and Task 4's `definition` module (`load_benchmark`, `load_local_values`, `placeholder_names`, `placeholder_values`, `substitute`, `next_run_name`, `latest_run_dir`, `load_proposed`, `RUNS_DIR`, `BenchmarkError`).
- Produces:

```python
@dataclass(frozen=True)
class BenchmarkRun:
    run_dir: Path
    summary: runner.TournamentSummary
    failures: tuple[str, ...]      # validate failures; empty means OK

def run_benchmark(
    benchmark_dir: Path, *, date: str | None = None, environ: Mapping[str, str] | None = None
) -> BenchmarkRun
```

  CLI: `spellbench bench run BENCHMARK_DIR [--date YYYY-MM-DD]`. Prints `benchmark run published: <run_dir>`, the same games line as `spellbench run`, the leaderboard status, then `validate: OK` or one `FAIL <failure>` line each on stderr. Exit 0 on success, 1 on a validate failure or any `BenchmarkError` / `TournamentError` (as `error: ...`), 2 on usage errors.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_bench_run.py`:

```python
"""Benchmark runs: placeholders resolved at run time, dated run directories."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import cli, runner
from spellbench.bench import definition
from spellbench.bench.definition import BenchmarkError
from spellbench.bench.run import run_benchmark

from arena_helpers import FAKE_ARENA_ENGINE

REPO = Path(__file__).resolve().parents[2]
ENVIRON = {"PY": sys.executable, "FAKE_ENGINE": str(FAKE_ARENA_ENGINE)}
PUBLISHED = ("manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md")


def _bot(name: str, label: str, tag: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name, "version": "1.0.0", "type": "builtin", "training_style_tags": [tag], **extra,
        "display": {"label": label, "author": "Spellbench", "description": f"{label} bot", "url": None},
    }


def _write_benchmark(root: Path) -> Path:
    directory = root / "fake-pool"
    directory.mkdir(parents=True)
    value = {
        "schema": "spellbench-benchmark/v1",
        "id": "fake-pool",
        "title": "Fake pool",
        "summary": "Three decks on the fake arena engine.",
        "format": "pauper-bo1",
        "engine": {"name": "fake-arena-engine", "command": ["${PY}", "${FAKE_ENGINE}"], "timeout_ms": 30000},
        "deck_pool": ["Burn", "Elves", "Faeries"],
        "pairs_per_deck": 1,
        "base_seed": 99,
        "bootstrap_replicates": 1000,
        "bots": [_bot("uniform", "random", "baseline", seed=11), _bot("heuristic", "heuristic", "heuristic"), _bot("first", "first", "baseline")],
    }
    (directory / "benchmark.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    return directory


def test_a_run_publishes_a_dated_validated_directory(tmp_path: Path) -> None:
    result = run_benchmark(_write_benchmark(tmp_path), date="2026-09-26", environ=ENVIRON)
    assert result.run_dir == tmp_path / "fake-pool" / "runs" / "2026-09-26"
    assert result.failures == ()
    assert result.summary.games_total == 3 * 3 * 2  # 3 matchups x 3 pairs (one per deck) x 2 games
    assert (result.run_dir / "manifest.json").is_file()


def test_the_run_records_placeholders_and_no_local_paths(tmp_path: Path) -> None:
    result = run_benchmark(_write_benchmark(tmp_path), date="2026-09-26", environ=ENVIRON)
    recorded = json.loads((result.run_dir / "config.json").read_text(encoding="utf-8"))
    assert recorded["engine"]["command"] == ["${PY}", "${FAKE_ENGINE}"]
    assert recorded["tournament_dir"] == "runs/2026-09-26"
    for name in PUBLISHED:
        text = (result.run_dir / name).read_text(encoding="utf-8")
        for value in ENVIRON.values():
            assert value not in text and json.dumps(value)[1:-1] not in text, name


def test_a_second_run_the_same_day_gets_the_next_suffix(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    first = run_benchmark(directory, date="2026-09-26", environ=ENVIRON)
    second = run_benchmark(directory, date="2026-09-26", environ=ENVIRON)
    assert second.run_dir.name == "2026-09-26-2"
    assert definition.latest_run_dir(directory) == second.run_dir
    assert (first.run_dir / "matches.jsonl").read_bytes() == (second.run_dir / "matches.jsonl").read_bytes()


def test_unresolved_placeholders_fail_before_any_process(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    with pytest.raises(BenchmarkError) as caught:
        run_benchmark(directory, date="2026-09-26", environ={})
    assert "FAKE_ENGINE" in str(caught.value) and "PY" in str(caught.value)
    assert not (directory / "runs").exists()


def test_local_json_supplies_values_and_the_environment_wins(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    (tmp_path / "local.json").write_text(json.dumps({"PY": "no-such-python", "FAKE_ENGINE": str(FAKE_ARENA_ENGINE)}), encoding="utf-8")
    result = run_benchmark(directory, date="2026-09-26", environ={"PY": sys.executable})
    assert result.failures == ()


def test_the_cli_runs_a_benchmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for name, value in ENVIRON.items():
        monkeypatch.setenv(name, value)
    directory = _write_benchmark(tmp_path)
    assert cli.main(["bench", "run", str(directory), "--date", "2026-09-26"]) == 0
    assert "validate: OK" in capsys.readouterr().out


def test_cli_usage_and_input_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = _write_benchmark(tmp_path)
    assert cli.main(["bench"]) == 2
    assert cli.main(["bench", "run"]) == 2
    assert cli.main(["bench", "run", str(directory), "--date"]) == 2
    assert cli.main(["bench", "run", str(directory), "--date", "not-a-date"]) == 1
    assert "error:" in capsys.readouterr().err


def test_the_launch_definitions_parse() -> None:
    benchmark = definition.load_benchmark(REPO / "benchmarks" / "pauper-kernel")
    runner.TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
    assert definition.placeholder_names(benchmark) == ("MTG_KERNEL_BRIDGE",)
    assert benchmark.deck_pool == ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
    assert [bot.name for bot in benchmark.bots] == ["uniform", "heuristic", "first"]
    assert benchmark.bot("uniform").display.label == "random"
    assert [item.title for item in definition.load_proposed(REPO / "benchmarks")] == ["FDN Limited", "Standard 2022-25"]


@pytest.mark.parametrize(
    "path", ["benchmarks/local.json", "benchmarks/pauper-kernel/runs/2026-09-26/diagnostics.jsonl", "site/index.html"]
)
def test_local_values_diagnostics_and_site_output_are_git_ignored(path: str) -> None:
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=REPO)
    assert result.returncode == 0, path
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_bench_run.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'spellbench.bench.run'`.

- [ ] **Step 3: Implement `run.py` and the CLI**

```python
"""Run a benchmark: resolve placeholders, play the round robin, validate.

The run lands in ``<benchmark_dir>/runs/<date>[-N]/``. Its recorded config
keeps the definition's ``${NAME}`` placeholders; processes start with the
values from the environment or ``benchmarks/local.json`` (the environment
wins). An unresolved placeholder stops the run before any process starts.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..arena import runner
from ..arena.validate import validate_tournament_dir
from . import definition


@dataclass(frozen=True)
class BenchmarkRun:
    run_dir: Path
    summary: runner.TournamentSummary
    failures: tuple[str, ...]


def run_benchmark(
    benchmark_dir: Path, *, date: str | None = None, environ: Mapping[str, str] | None = None
) -> BenchmarkRun:
    benchmark = definition.load_benchmark(benchmark_dir)
    values = definition.placeholder_values(
        definition.placeholder_names(benchmark),
        definition.load_local_values(benchmark_dir.parent),
        os.environ if environ is None else environ,
    )
    name = definition.next_run_name(benchmark_dir, date or datetime.date.today().isoformat())
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    summary = runner.run_tournament(
        config, resolve=lambda text: definition.substitute(text, values), output_dir=run_dir
    )
    return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))
```

In `cli.py`: add `spellbench bench run BENCHMARK_DIR [--date YYYY-MM-DD]` to `_USAGE` and the module docstring; add `_cmd_bench(argv)` (usage errors return 2: no argv, a first word other than `run`, a missing directory, `--date` without a value, or unknown extra arguments); dispatch `if command == "bench": return _cmd_bench(rest)` in `main`. `BenchmarkError` subclasses `ValueError`, which `main` already reports as `error: ...` with exit 1. Output:

```python
    result = run_benchmark(Path(argv[1]), date=date)
    summary = result.summary
    print(f"benchmark run published: {result.run_dir}")
    print(
        f"games: {summary.games_total} total, {summary.games_rated} rated, "
        f"{summary.games_truncated} truncated, {summary.games_halted} halted, "
        f"{summary.games_forfeit} forfeit"
    )
    print(f"leaderboard status: {summary.leaderboard_status}")
    if result.failures:
        for failure in result.failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("validate: OK")
    return 0
```

- [ ] **Step 4: Add the launch definitions and ignore rules**

Create `benchmarks/pauper-kernel/benchmark.json`:

```json
{
  "schema": "spellbench-benchmark/v1",
  "id": "pauper-kernel",
  "title": "Pauper \u00b7 mtg-kernel",
  "summary": "Eight Pauper decks on the mtg-kernel rules engine; every matchup plays each deck in both seats.",
  "format": "pauper-bo1",
  "engine": {"name": "mtg-kernel", "command": ["${MTG_KERNEL_BRIDGE}"], "timeout_ms": 120000},
  "deck_pool": ["Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries"],
  "pairs_per_deck": 4,
  "base_seed": 20260926,
  "choose_timeout_ms": 30000,
  "startup_timeout_ms": 120000,
  "bootstrap_replicates": 2000,
  "workers": 8,
  "bots": [
    {
      "name": "uniform", "version": "1.0.0", "type": "builtin", "seed": 11, "owner": "spellbench",
      "training_style_tags": ["baseline"],
      "display": {"label": "random", "author": "Spellbench", "description": "Picks uniformly at random among the offered actions. The anchor: its Elo is fixed at 1000.", "url": null}
    },
    {
      "name": "heuristic", "version": "1.0.0", "type": "builtin", "owner": "spellbench",
      "training_style_tags": ["heuristic"],
      "display": {"label": "heuristic", "author": "Spellbench", "description": "Fixed priorities: play a land, cast a spell, activate an ability; attacks with everything and never blocks.", "url": null}
    },
    {
      "name": "first", "version": "1.0.0", "type": "builtin", "owner": "spellbench",
      "training_style_tags": ["baseline"],
      "display": {"label": "first", "author": "Spellbench", "description": "Always takes the first offered action.", "url": null}
    }
  ]
}
```

(Write the title with the literal middle dot character; the JSON escape above is equivalent.)

Create `benchmarks/proposed.json`:

```json
{
  "schema": "spellbench-proposed-benchmarks/v1",
  "proposed": [
    {"title": "FDN Limited", "summary": "Foundations limited games, the format several community draft models target.", "needs": "an engine"},
    {"title": "Standard 2022-25", "summary": "Constructed Standard with the 2022 to 2025 card pool.", "needs": "an engine"}
  ]
}
```

Append to `.gitignore`:

```
benchmarks/local.json
benchmarks/**/diagnostics.jsonl
/site/
```

- [ ] **Step 5: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest python/tests/test_bench_run.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add python/spellbench/bench/run.py python/spellbench/arena/cli.py python/tests/test_bench_run.py benchmarks/pauper-kernel/benchmark.json benchmarks/proposed.json .gitignore
git commit -m "Benchmarks: spellbench bench run and the launch definitions"
```

### Task 8: The site build and `spellbench site`

**Files:**
- Create: `python/spellbench/site/build.py`
- Modify: `python/spellbench/arena/cli.py` (the `site` subcommand and usage text)
- Create: `python/tests/test_site_build.py`

**Interfaces:**
- Consumes: Task 4 `definition` (`find_benchmarks`, `load_benchmark`, `load_proposed`, `latest_run_dir`, `unpublished_runs`, `Benchmark.bot`, `Benchmark.tournament_config`), Task 5 `hero.hero_table`, Task 6 `render.render_home` / `render_benchmark` / `render_join` / `render_method`, Task 2 `arena.validate.validate_tournament_dir`, Task 1 `runner.TournamentConfig` (`deck_pool`, `pairs_per_matchup`), Task 3 `slices.deck` in `leaderboard.json`, and `store` (`MANIFEST_NAME`, `DATA_FILE_NAMES`, `read_json`, `LEADERBOARD_SCHEMA`, `TOURNAMENT_SCHEMA`, `CONFIG_SCHEMA`, `sha256_hex`), `registry.read_registry`.
- Produces:

```python
REPO_URL = "https://github.com/jackmaiorino/spellbench"
SITE_MARKER = ".spellbench-site"
RUN_FILES = (store.MANIFEST_NAME, *store.DATA_FILE_NAMES)

class SiteError(ValueError): ...

def build_site(benchmarks_dir: Path, out_dir: Path) -> list[str]   # returns warnings; raises SiteError
```

  CLI: `spellbench site BENCHMARKS_DIR OUT_DIR`: prints each warning as `warning: ...` on stderr, then `site built: <out_dir>`; exit 0. `SiteError` exits 1 as `error: ...`. Usage errors exit 2.

View models: build exactly the dicts of this contract (the same contract Task 6 renders):

```python
SiteView = {"title": "Spellbench", "tagline": "cross-engine Magic bot benchmark", "repo_url": REPO_URL}

HomeView = {
    "site": SiteView,
    "hero": {"rows": [HeroRowView, ...], "benchmark_count": int, "approximate": bool},
    "benchmarks": [BenchmarkCardView, ...],   # sorted by id
    "proposed": [ProposedCardView, ...],      # file order
}
HeroRowView = {
    "name": str, "label": str, "author": str,
    "score": float, "lower": float | None, "upper": float | None,
    "approximate": bool, "reference": bool,
    "chips": [{"benchmark_id": str, "margin": float}, ...],
}
BenchmarkCardView = {
    "id": str, "title": str, "summary": str, "engine_name": str,
    "deck_count": int, "bot_count": int,
    "games": int | None, "run_name": str | None, "href": str | None,   # None when there is no published run
}
ProposedCardView = {"title": str, "summary": str, "needs": str}

BenchmarkPageView = {
    "site": SiteView,
    "id": str, "title": str, "summary": str, "format": str,
    "engine": {"name": str, "version": str, "source_revision": str | None, "rules_snapshot_id": str, "card_pool_identity": str},
    "decks": [str, ...], "pairs_per_deck": int,
    "run": {
        "name": str,
        "games": {"total": int, "rated": int, "forfeit": int, "truncated": int, "halted": int},
        "manifest_sha256": str,
        "files": [{"name": str, "href": str, "bytes": int}, ...],
        "validate_command": str,
    },
    "overall": [LeaderRowView, ...],
    "deck_tables": [{"label": str, "status": str, "reason": str | None, "rows": [LeaderRowView, ...]}, ...],
    "style_tables": [{"tag": str, "rows": [LeaderRowView, ...]}, ...],
    "grid": {"names": [str, ...], "labels": [str, ...], "cells": [[GridCell | None, ...], ...]},
}
LeaderRowView = {
    "rank": int | None, "name": str, "label": str, "author": str, "url": str | None, "description": str,
    "tags": [str, ...], "anchor": bool,
    "elo_milli": int | None, "ci_elo_milli": [int, int] | None,
    "wins": int, "draws": int, "losses": int, "games": int, "forfeits": int,
}
GridCell = {"score": float, "games": int}
InfoPageView = {"site": SiteView}
```

Build rules:
1. Plan every page in memory before writing anything; a refusal leaves `out_dir` untouched.
2. For each folder from `find_benchmarks(benchmarks_dir)`: `load_benchmark`, then `runner.TournamentConfig.from_json(benchmark.tournament_config("runs/check"))` so arena-level definition errors surface (`TournamentError` becomes `SiteError` naming the benchmark). Warn for each `unpublished_runs` entry (`"<id>: runs/<name> has no manifest.json (an unfinished run); showing <latest or 'no run'>"`). With no published run: warn `"<id>: no published run yet"`, add a card with `games`, `run_name`, `href` set to None, and no page.
3. Validate each latest run with `validate_tournament_dir`. Collect the failures of every benchmark; if any, raise one `SiteError` listing each as `"<id> runs/<name>: <failure>"`.
4. Read the run's `manifest.json`, `config.json` (`TournamentConfig.from_json`), `registry.json`, and `leaderboard.json`. If the run's bot names differ from the definition's, warn `"<id>: benchmark.json changed since run <name> (bots differ); rerun to publish the change"`.
5. Display lookup by bot name: the definition's `display` when the bot is in it, else `label = name`, `author = registry owner`, `description = ""`, `url = None`.
6. Leaderboard rows map from `leaderboard.json` `rows` in order: `forfeits = forfeit_losses`, `ci_elo_milli = ci95_elo_milli`, `tags = training_style_tags`, `anchor = bot_id == document["anchor"]["bot_id"]`. Deck tables map from `slices.deck` in order, with `reason = fit_error` or, for `no_rated_games`, `"no rated games"`, and `None` when ok. Style tables: for each tag (sorted) the overall rows that carry it.
7. Grid: for bots `i != j` in overall order, find the matchup whose `{a_bot_id, b_bot_id}` is `{id_i, id_j}`; `score = num / den` of `a_score` when bot i is `a`, else `1 - num / den`; `games = matchup["games"]`; None when there is no matchup or `a_score` is null.
8. Decks: the catalog ids of `config.deck_pool` in order (a fixed-pair config gives one label, `"<p0>"` or `"<p0> vs <p1>"`). `pairs_per_deck = pairs_per_matchup // len(deck_pool)` (the full `pairs_per_matchup` for a fixed pair).
9. Hero: `hero_table([(id, leaderboard) ...])` over the benchmarks with runs, in id order; add its warnings. Label and author for a hero row come from the first benchmark (id order) whose definition lists that bot name, else the name and `""`.
10. Output directory: if `out_dir` exists and is not empty, it must hold `SITE_MARKER`, or raise `SiteError("refusing to overwrite <out_dir>: it is not a spellbench site build")`. Delete it and write fresh: `SITE_MARKER` (one line: `spellbench site output; rebuilt by spellbench site`), `index.html`, `join.html`, `method.html`, `b/<id>/index.html`, and byte copies of `RUN_FILES` into `b/<id>/run/`. Write pages as `text.encode("utf-8")` bytes so line endings stay `\n` on Windows.
11. Determinism: sorted benchmarks and tags, no timestamps, no absolute paths in any page.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_site_build.py`:

```python
"""The site build: validated runs in, static pages out."""

from __future__ import annotations

import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from spellbench.arena import cli, runner
from spellbench.bench import definition
from spellbench.site import render
from spellbench.site.build import SiteError, build_site

from arena_helpers import FAKE_ARENA_ENGINE

RUN_FILES = ("manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md")
HOSTILE = '<script>alert("x")</script>'


def _bot(name: str, label: str, tag: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name, "version": "1.0.0", "type": "builtin", "training_style_tags": [tag], **extra,
        "display": {"label": label, "author": "Spellbench", "description": f"{name} bot", "url": None},
    }


def _definition(bench_id: str, labels: dict[str, str] | None = None) -> dict[str, Any]:
    labels = labels or {}
    return {
        "schema": "spellbench-benchmark/v1",
        "id": bench_id,
        "title": f"Bench {bench_id}",
        "summary": "Three decks on the fake arena engine.",
        "format": "pauper-bo1",
        "engine": {"name": "fake-arena-engine", "command": [sys.executable, str(FAKE_ARENA_ENGINE)], "timeout_ms": 30000},
        "deck_pool": ["Burn", "Elves", "Faeries"],
        "pairs_per_deck": 1,
        "base_seed": 99,
        "bootstrap_replicates": 1000,
        "bots": [
            _bot("uniform", labels.get("uniform", "random"), "baseline", seed=11),
            _bot("heuristic", labels.get("heuristic", "heuristic"), "heuristic"),
            _bot("first", labels.get("first", "first"), "baseline"),
        ],
    }


def _add_benchmark(root: Path, bench_id: str, *, runs: tuple[str, ...] = ("2026-09-26",), anchor: str | None = None,
                   labels: dict[str, str] | None = None) -> Path:
    directory = root / bench_id
    directory.mkdir(parents=True)
    (directory / "benchmark.json").write_text(json.dumps(_definition(bench_id, labels), indent=2), encoding="utf-8")
    benchmark = definition.load_benchmark(directory)
    for name in runs:
        config = benchmark.tournament_config(f"runs/{name}")
        if anchor is not None:
            config["rating_anchor"] = anchor
        runner.run_tournament(runner.TournamentConfig.from_json(config), output_dir=directory / "runs" / name)
    return directory


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Benchmarks alpha and beta with one run each, plus proposed.json."""
    root = tmp_path_factory.mktemp("benchmarks")
    _add_benchmark(root, "alpha")
    _add_benchmark(root, "beta")
    proposed = {"schema": "spellbench-proposed-benchmarks/v1",
                "proposed": [{"title": "FDN Limited", "summary": "Foundations limited games.", "needs": "an engine"}]}
    (root / "proposed.json").write_text(json.dumps(proposed), encoding="utf-8")
    return root


@pytest.fixture
def copy_tree(tree: Path, tmp_path: Path) -> Path:
    target = tmp_path / "benchmarks"
    shutil.copytree(tree, target)
    return target


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.links.append(value)


def _files(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file()}


def _element(page: str, tag: str, attribute: str, value: str) -> str:
    match = re.search(rf'<{tag}\b[^>]*\b{attribute}="{re.escape(value)}"[^>]*>(.*?)</{tag}>', page, re.S)
    assert match, f"no <{tag} {attribute}={value!r}>"
    return re.sub(r"<[^>]+>", " ", match.group(1))


def test_the_site_has_every_page_and_run_file(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    for page in ("index.html", "join.html", "method.html", "b/alpha/index.html", "b/beta/index.html"):
        assert (out / page).is_file(), page
    for name in RUN_FILES:
        assert (out / "b/alpha/run" / name).read_bytes() == (tree / "alpha/runs/2026-09-26" / name).read_bytes()


def test_every_internal_link_resolves(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    for page in out.rglob("*.html"):
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        for link in parser.links:
            parts = urlsplit(link)
            if parts.scheme or link.startswith("#"):
                continue
            assert (page.parent / parts.path).resolve().is_file(), f"{page.relative_to(out)} -> {link}"


def test_benchmark_numbers_match_the_leaderboard(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    overall = page[page.index('data-panel="overall"'):]
    board = json.loads((tree / "alpha/runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8"))
    for row in board["rows"]:
        text = _element(overall, "tr", "data-bot", row["name"])
        assert render.format_elo(row["elo_milli"]) in text
        assert f'{row["wins"]}-{row["draws"]}-{row["losses"]}' in text
    for deck in ("Burn", "Elves", "Faeries"):
        assert f'data-deck="{deck}"' in page


def test_the_hero_chart_uses_the_random_anchor(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "random" in _element(home, "li", "data-bot", "uniform")
    boards = [json.loads((tree / b / "runs/2026-09-26/leaderboard.json").read_text(encoding="utf-8")) for b in ("alpha", "beta")]
    margins = [(next(r for r in board["rows"] if r["name"] == "heuristic")["elo_milli"] - 1_000_000) / 1000 for board in boards]
    assert render.format_margin(sum(margins) / 2) in _element(home, "li", "data-bot", "heuristic")


def test_two_builds_are_byte_identical_with_unix_newlines(tree: Path, tmp_path: Path) -> None:
    build_site(tree, tmp_path / "one")
    build_site(tree, tmp_path / "two")
    one, two = _files(tmp_path / "one"), _files(tmp_path / "two")
    assert one == two
    assert all(b"\r\n" not in data for name, data in one.items() if name.endswith(".html"))


def test_a_rebuild_replaces_the_previous_output(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(tree, out)
    (out / "stale.html").write_text("old", encoding="utf-8")
    build_site(tree, out)
    assert not (out / "stale.html").exists()


def test_the_build_refuses_a_directory_it_did_not_make(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    out.mkdir()
    (out / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SiteError, match="refusing"):
        build_site(tree, out)
    assert (out / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_a_tampered_run_is_refused_and_nothing_is_written(copy_tree: Path, tmp_path: Path) -> None:
    ledger = copy_tree / "beta/runs/2026-09-26/matches.jsonl"
    data = ledger.read_bytes()
    ledger.write_bytes(data.replace(b'"reason":"score"', b'"reason":"SCORE"', 1))
    out = tmp_path / "site"
    with pytest.raises(SiteError, match="beta"):
        build_site(copy_tree, out)
    assert not out.exists()


def test_a_benchmark_without_a_run_gets_a_card_and_a_warning(copy_tree: Path, tmp_path: Path) -> None:
    fresh = copy_tree / "gamma"
    fresh.mkdir()
    (fresh / "benchmark.json").write_text(json.dumps(_definition("gamma"), indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("gamma" in warning and "no published run" in warning for warning in warnings)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "Bench gamma" in home and "No published run yet" in home
    assert not (out / "b/gamma").exists()


def test_an_unfinished_run_is_skipped_with_a_warning(copy_tree: Path, tmp_path: Path) -> None:
    unfinished = copy_tree / "alpha/runs/2026-09-27"
    unfinished.mkdir()
    (unfinished / "config.json").write_text("{}", encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("2026-09-27" in warning for warning in warnings)
    assert "2026-09-26" in (out / "b/alpha/index.html").read_text(encoding="utf-8")


def test_a_changed_definition_still_renders_the_run_and_warns(copy_tree: Path, tmp_path: Path) -> None:
    changed = _definition("alpha")
    changed["bots"] = changed["bots"][:2]  # "first" removed after the run
    (copy_tree / "alpha/benchmark.json").write_text(json.dumps(changed, indent=2), encoding="utf-8")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("alpha" in warning and "changed" in warning for warning in warnings)
    page = (out / "b/alpha/index.html").read_text(encoding="utf-8")
    assert "first" in _element(page[page.index('data-panel="overall"'):], "tr", "data-bot", "first")


def test_hostile_labels_are_escaped(tmp_path: Path) -> None:
    root = tmp_path / "benchmarks"
    _add_benchmark(root, "alpha", labels={"heuristic": HOSTILE})
    out = tmp_path / "site"
    build_site(root, out)
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert "<script>alert" not in text, page.name
    assert "&lt;script&gt;" in (out / "b/alpha/index.html").read_text(encoding="utf-8")


def test_an_unanchored_run_is_left_out_of_the_hero_chart(copy_tree: Path, tmp_path: Path) -> None:
    _add_benchmark(copy_tree, "delta", anchor="heuristic")
    out = tmp_path / "site"
    warnings = build_site(copy_tree, out)
    assert any("delta" in warning and "heuristic" in warning for warning in warnings)
    hero = (out / "index.html").read_text(encoding="utf-8")
    hero = hero[hero.index('id="hero"'):hero.index('id="benchmarks"')]
    assert "delta" not in hero and "alpha" in hero


def test_the_cli_builds_the_site(tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "site"
    assert cli.main(["site", str(tree), str(out)]) == 0
    assert "site built" in capsys.readouterr().out
    assert cli.main(["site", str(tree)]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest python/tests/test_site_build.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'spellbench.site.build'`.

- [ ] **Step 3: Implement `build.py` and the CLI**

Implement `build_site` to the build rules above. Keep view-model construction in small functions (`_home_view`, `_benchmark_view`, `_leader_rows`, `_grid`, `_display_of`) and the filesystem work in one place at the end. Add `spellbench site BENCHMARKS_DIR OUT_DIR` to `cli.py` (`_USAGE`, the module docstring, `_cmd_site`, and the dispatch in `main`); `SiteError` subclasses `ValueError`, which `main` already reports as `error: ...` with exit 1.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest python/tests/test_site_build.py -q`
Expected: PASS.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/spellbench/site/build.py python/spellbench/arena/cli.py python/tests/test_site_build.py
git commit -m "Site: build from validated runs; spellbench site"
```

### Task 9: Pages workflow and README

**Files:**
- Create: `.github/workflows/pages.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: the commands `spellbench bench run BENCHMARK_DIR [--date YYYY-MM-DD]` and `spellbench site BENCHMARKS_DIR OUT_DIR` (Tasks 7 and 8), the placeholder rules (Task 4), and `.gitignore`'s `/site/` entry (Task 7).
- Produces: a workflow that builds and deploys on pushes to `main`; README sections that document benchmarks and the site.

- [ ] **Step 1: Resolve the action SHAs**

For `actions/configure-pages`, `actions/upload-pages-artifact`, and `actions/deploy-pages`, find the latest release tag (`gh release list -R actions/<name> --limit 1`) and its commit SHA (`gh api repos/actions/<name>/commits/<tag> --jq .sha`). Reuse the checkout and setup-python pins from `ci.yml` exactly.

- [ ] **Step 2: Write the workflow**

```yaml
name: Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    name: Build the site
    runs-on: ubuntu-24.04
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7

      - name: Set up Python
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version-file: .python-version

      - name: Install uv
        run: python -m pip install --disable-pip-version-check uv==0.11.29

      - name: Sync the locked environment
        run: uv sync --locked

      - name: Validate every latest run and build the site
        run: uv run --no-sync spellbench site benchmarks site

      - name: Configure Pages
        uses: actions/configure-pages@<sha> # <tag>

      - name: Upload the site
        uses: actions/upload-pages-artifact@<sha> # <tag>
        with:
          path: site

  deploy:
    name: Deploy to GitHub Pages
    needs: build
    runs-on: ubuntu-24.04
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@<sha> # <tag>
```

Replace each `<sha> # <tag>` with the values from Step 1. Check the file parses (for example `uv run --no-project --with pyyaml python -c "import sys, yaml; yaml.safe_load(open(sys.argv[1]))" .github/workflows/pages.yml`).

- [ ] **Step 3: Update the README**

Add a `## Benchmarks` section after `## Running tournaments`, with this content (tilde fences below stand for triple-backtick `bash` fences in the README):

```markdown
## Benchmarks

A benchmark is a folder under `benchmarks/` with a `benchmark.json`: an
engine, a deck pool, and a roster anchored on the builtin `uniform` bot
(Elo 1000, shown as "random"). Every matchup plays each pool deck in both
seats, and bots never play themselves.

~~~bash
spellbench bench run benchmarks/pauper-kernel
~~~

The run replays the whole round robin into
`benchmarks/<id>/runs/<date>/` and validates it; commit the run to publish
it. Machine paths stay out of the repo: `${NAME}` placeholders in engine
and bot commands resolve from the environment or from the git-ignored
`benchmarks/local.json`, for example
`{"MTG_KERNEL_BRIDGE": "C:/path/to/agent_bridge_v1.exe"}`.

~~~bash
spellbench site benchmarks site
~~~

This re-validates each benchmark's latest run, refuses to build if one
fails, and writes the static site: the Hero chart (Elo above random,
averaged over the benchmarks a bot entered), a page per benchmark, and the
method. The Pages workflow builds and deploys it on every push to `main`.
```

In `## Status`, add one line: "Benchmarks: `pauper-kernel` (eight Pauper decks on mtg-kernel) with the builtin bots; more bots join through the protocol."

- [ ] **Step 4: Check the docs and run the suite**

Run: `grep -n $'\u2014' README.md .github/workflows/pages.yml` (Git Bash) or an equivalent search.
Expected: no output.
Run: `uv run pytest python/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/pages.yml README.md
git commit -m "Pages workflow and README: benchmarks and the site"
```
