"""Recorded versus executed commands: placeholders stay in the artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import registry
from spellbench.arena.validate import validate_tournament_dir
from spellbench.errors import ValidationError

from arena_helpers import FAKE_ENGINE, builtin, make_config, run, subprocess_bot

VALUES = {"${PY}": sys.executable, "${ENGINE}": str(FAKE_ENGINE)}
PUBLISHED = (
    "manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md",
    "COMMITMENT.json",
)
BOT_COMMAND = ["${PY}", "-m", "spellbench.arena.cli", "bot", "heuristic"]


def resolve(text: str) -> str:
    for placeholder, value in VALUES.items():
        text = text.replace(placeholder, value)
    return text


def _config(tmp_path: Path, bot: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    bots = [bot or subprocess_bot("heuristic", BOT_COMMAND, version="2.0.0"), builtin("first")]
    config = make_config(tmp_path / "unused", bots, pairs=1, include_self_play=False, **extra)
    config["tournament_dir"] = "runs/2026-09-26"
    config["engine"]["command"] = ["${PY}", "${ENGINE}"]
    return config


def test_processes_run_resolved_commands_and_artifacts_keep_the_written_ones(tmp_path: Path) -> None:
    out = tmp_path / "out"
    summary = run(_config(tmp_path, workers=2), resolve=resolve, output_dir=out)
    assert summary.games_rated == 2
    assert summary.games_forfeit == 0  # a bot started from its recorded command would forfeit
    assert summary.tournament_dir == out
    recorded = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert recorded["tournament_dir"] == "runs/2026-09-26"
    assert recorded["engine"]["command"] == ["${PY}", "${ENGINE}"]
    assert recorded["bots"][0]["command"] == BOT_COMMAND
    entries = {entry.name: entry for entry in registry.read_registry(out / "registry.json")}
    written = registry.subprocess_descriptor("heuristic", "2.0.0", BOT_COMMAND)
    assert entries["heuristic"].bot_id == registry.bot_id_from_descriptor(written)
    assert validate_tournament_dir(out) == []


def test_no_published_file_contains_a_resolved_value(tmp_path: Path) -> None:
    out = tmp_path / "out"
    summary = run(_config(tmp_path), resolve=resolve, output_dir=out)
    assert summary.games_rated == 2
    assert summary.games_forfeit == 0  # a bot started from its recorded command would forfeit
    for name in PUBLISHED:
        text = (out / name).read_text(encoding="utf-8")
        for value in VALUES.values():
            assert value not in text, name
            assert json.dumps(value)[1:-1] not in text, name  # the JSON-escaped spelling


def test_output_dir_replaces_the_recorded_tournament_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    run(_config(tmp_path), resolve=resolve, output_dir=tmp_path / "out")
    assert not (tmp_path / "runs").exists()
    assert (tmp_path / "out" / "manifest.json").is_file()


def test_a_checkpoint_is_hashed_from_its_resolved_path_and_recorded_as_written(tmp_path: Path) -> None:
    weights = tmp_path / "weights.bin"
    weights.write_bytes(b"model bytes")
    bot = subprocess_bot("heuristic", BOT_COMMAND, version="2.0.0", checkpoint="${CKPT}")
    out = tmp_path / "out"
    run(
        _config(tmp_path, bot),
        resolve=lambda text: resolve(text).replace("${CKPT}", str(weights)),
        output_dir=out,
    )
    recorded = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert recorded["bots"][0]["checkpoint"] == "${CKPT}"
    entry = next(item for item in registry.read_registry(out / "registry.json") if item.name == "heuristic")
    expected = registry.subprocess_descriptor(
        "heuristic", "2.0.0", BOT_COMMAND, weights_sha256=registry.checkpoint_sha256(weights)
    )
    assert entry.bot_id == registry.bot_id_from_descriptor(expected)


def test_an_unreadable_checkpoint_stops_the_run_before_the_directory_exists(tmp_path: Path) -> None:
    missing = tmp_path / "missing.bin"
    bot = subprocess_bot("heuristic", BOT_COMMAND, version="2.0.0", checkpoint="${CKPT}")
    out = tmp_path / "out"
    with pytest.raises(ValidationError, match="checkpoint is not readable") as excinfo:
        run(
            _config(tmp_path, bot),
            resolve=lambda text: resolve(text).replace("${CKPT}", str(missing)),
            output_dir=out,
        )
    assert str(missing) in str(excinfo.value)
    assert not out.exists()


def test_validate_is_still_importable_from_the_cli_module() -> None:
    from spellbench.arena import cli

    assert cli.validate_tournament_dir is validate_tournament_dir
