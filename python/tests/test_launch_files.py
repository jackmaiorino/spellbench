"""Changed executed inputs stop launches and cannot produce a rated manifest."""

import json
import sys

import pytest

from spellbench.arena import runner
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.bench.pinning import PinningError, engine_files

from arena_helpers import builtin, make_config, run


def test_changed_declared_input_stops_before_engine_creation(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"original")
    files = engine_files([sys.executable], extra=[checkpoint])
    checkpoint.write_bytes(b"changed")
    monkeypatch.setattr(runner, "EngineProcess", lambda *args, **kwargs: pytest.fail("changed input launched"))
    with pytest.raises(PinningError, match="changed"):
        runner.play_one(None, None, None, "", {}, launch_files=files)


def test_input_changed_after_driver_construction_stops_actual_agent_spawn(tmp_path):
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"original")
    files = engine_files([sys.executable], extra=[checkpoint])
    spec = BotSpec("luna", "0.1", "subprocess", command=(sys.executable,))
    driver = SubprocessDriver(spec, startup_ms=1000, launch_files=files,
                              agent_factory=lambda: pytest.fail("changed input spawned an agent"))
    checkpoint.write_bytes(b"changed")
    with pytest.raises(PinningError, match="changed"):
        driver.start({}, timeout_s=1)


@pytest.mark.parametrize("change_after", [0, 1])
def test_changed_input_after_a_game_cannot_publish_a_rating(tmp_path, change_after):
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"original")
    files = engine_files([sys.executable], extra=[checkpoint])
    directory = tmp_path / "run"
    config = make_config(directory, [builtin("uniform"), builtin("first")], pairs=1)

    def mutate(row):
        if row.game_index == change_after:
            checkpoint.write_bytes(b"changed")

    with pytest.raises(PinningError, match="changed"):
        run(config, rated=True, launch_files=files, on_game=mutate)
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["run"]["rated"] is False
    assert manifest["engine_files"] == []
    assert len((directory / "matches.jsonl").read_text().splitlines()) == change_after + 1
    assert manifest["secrets"]["run_secret"]  # retain the public commitment's reveal
