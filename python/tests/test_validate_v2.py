"""Validate v2 runs from their files alone, including invalid and aborted runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import spellbench
from spellbench.arena import store
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import HOSTILE_ENGINE, builtin, ledger_rows, make_config, manifest, run

BOTS = [builtin("uniform", seed=11), builtin("heuristic")]


def _run(tmp_path: Path, **kwargs) -> Path:
    directory = tmp_path / "t"
    run(make_config(directory, BOTS, pairs=2, include_self_play=False), **kwargs)
    return directory


def _rewrite(directory: Path, *, rows=None, edit=None) -> None:
    """Tamper with the run, then refresh the file digests so only the tampering can fail."""
    if rows is not None:
        (directory / "matches.jsonl").write_bytes(b"".join(store.canonical_bytes(row) + b"\n" for row in rows))
    document = manifest(directory)
    if edit is not None:
        edit(document)
    names = [entry["path"] for entry in document["files"]]
    document["files"] = [store.file_entry(directory / name, name) for name in names]
    store.write_json_atomic(directory / "manifest.json", document)


def _relabel_commitment(directory: Path) -> None:
    path = directory / "COMMITMENT.json"
    store.write_json_atomic(path, {**json.loads(path.read_text(encoding="utf-8")), "run_label": "some-other-run"})
    _rewrite(directory)


def _flip_first(rows: list[dict]) -> list[dict]:
    """Change game 0's result to another valid natural result."""
    first = rows[0]
    if first["outcome"] == "draw":
        flipped = {**first, "outcome": "p0_win", "winner": "p0", "winner_bot_id": first["seats"][0]["bot_id"]}
    else:
        flipped = {**first, "outcome": "draw", "winner": None, "winner_bot_id": None}
    return [flipped, *rows[1:]]


def test_complete_and_rated_runs_validate(tmp_path: Path) -> None:
    assert validate_tournament_dir(_run(tmp_path)) == []
    rated = tmp_path / "rated"
    run(make_config(rated, BOTS, pairs=2, include_self_play=False), rated=True)
    assert validate_tournament_dir(rated) == []


def test_an_invalid_run_validates_as_invalid(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("first"), builtin("heuristic")], engine=HOSTILE_ENGINE,
                    engine_args=("stale-reference",), pairs=2))
    assert validate_tournament_dir(directory) == []


def test_an_aborted_run_validates_as_aborted(tmp_path: Path) -> None:
    def stop(row) -> None:
        if row.game_index == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, on_game=stop)
    assert validate_tournament_dir(tmp_path / "t") == []


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        (lambda d: _rewrite(d, rows=_flip_first(ledger_rows(d))), "leaderboard.json"),
        (lambda d: _rewrite(d, rows=[{**r, "game_id": "g-0000000000000000"} if r["game_index"] == 0 else r for r in ledger_rows(d)]), "schedule"),
        (lambda d: _rewrite(d, edit=lambda m: m["secrets"].update(run_secret="11" * 32)), "commitment"),
        (lambda d: _rewrite(d, edit=lambda m: m["run"].update(rated=True)), "rated"),
        (lambda d: _rewrite(d, edit=lambda m: m["validator"].update(decisions_checked=1)), "validator"),
        (lambda d: _rewrite(d, edit=lambda m: m["information_rules"].update(fairness_label="validator and probe")), "fairness"),
        (lambda d: _rewrite(d, edit=lambda m: m["games"].update(natural=0)), "games"),
        (lambda d: (d / "LEADERBOARD.md").write_text("x", encoding="utf-8"), "digest mismatch: LEADERBOARD.md"),
        (_relabel_commitment, "commitment"),                                                # another run's label (R3-30)
        (lambda d: _rewrite(d, edit=lambda m: m["isolation"].update(self_reported=True)), "isolation"),       # R3-9
    ],
)
def test_tampering_is_caught(tmp_path: Path, tamper, expected: str) -> None:
    directory = _run(tmp_path)
    tamper(directory)
    failures = validate_tournament_dir(directory)
    assert any(expected in failure for failure in failures), failures


def test_a_rated_run_without_pinned_engine_files_is_caught(tmp_path: Path) -> None:
    directory = _run(tmp_path, rated=True)
    _rewrite(directory, edit=lambda m: m.update(engine_files=[]))
    assert any("rated" in failure for failure in validate_tournament_dir(directory))        # R3-7


def test_another_arena_version_gets_one_message(tmp_path: Path) -> None:
    directory = _run(tmp_path)
    _rewrite(directory, edit=lambda m: m["tournament"].update(arena_version="0.9.0"))
    assert validate_tournament_dir(directory) == [
        f"this run was made by spellbench arena 0.9.0; this is {spellbench.__version__}: rerun the benchmark, or validate with arena 0.9.0"
    ]


def test_an_unknown_schema_goes_to_the_legacy_path_and_fails_there(tmp_path: Path) -> None:
    directory = _run(tmp_path)
    _rewrite(directory, edit=lambda m: m.update(schema="spellbench-tournament/v9"))
    assert any("spellbench-tournament/v1" in failure for failure in validate_tournament_dir(directory))
