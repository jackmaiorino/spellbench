"""Bot windows on the Manabrew path (``python -m spellbench.human --bot-windows``): each game's engine is told the bot's
seat (``--action-windows-seat``), which the bridge offers the priority windows its model trained with
(action-windows-v1), and every game says so on the table and in its log. Without the option nothing changes."""

from __future__ import annotations

import json

import pytest

from spellbench.human import session
from spellbench.human.server import BOT_WINDOWS_NOTE, FULL_PRIORITY_BOT_WINDOWS_NOTE, FULL_PRIORITY_NOTE, Hub

BASE = {"tournament_dir": "x", "engine": {"name": "mtg-kernel", "command": ["python", "engine.py", "--bridge", "b"]},
        "deck_pool": [], "matchups": [["human", "bot"]], "pairs_per_matchup": 8}


@pytest.mark.parametrize("human_first,person,bot", [(True, "p0", "p1"), (False, "p1", "p0")])
def test_each_picked_game_names_the_bots_seat_to_its_engine(tmp_path, human_first: bool, person: str, bot: str) -> None:
    doc = session.picked_game_config(BASE, human_deck="Burn", bot_deck="Faeries", human_first=human_first,
                                     run_dir=tmp_path, opponent="bot", full_priority=True, bot_windows=True)
    assert doc["engine"]["command"] == ["python", "engine.py", "--bridge", "b", "--engine-windows-seat", person,
                                        "--action-windows-seat", bot]
    assert BASE["engine"]["command"] == ["python", "engine.py", "--bridge", "b"]


@pytest.mark.parametrize("human_first", [True, False])
def test_without_the_option_the_game_config_is_unchanged(tmp_path, human_first: bool) -> None:
    kwargs = dict(human_deck="Burn", bot_deck="Faeries", human_first=human_first, run_dir=tmp_path, opponent="bot",
                  full_priority=True, auto_graveyard_order=True)
    doc = session.picked_game_config(BASE, **kwargs)
    assert doc == session.picked_game_config(BASE, **kwargs, bot_windows=False)
    assert doc["engine"]["command"] == ["python", "engine.py", "--bridge", "b", "--engine-windows-seat",
                                        "p0" if human_first else "p1", "--auto-graveyard-order"]


def test_the_option_needs_the_manabrew_client(capsys) -> None:
    with pytest.raises(SystemExit):
        session.main(["--local", "x", "--out", "y", "--bot-windows"])
    assert "--bot-windows" in capsys.readouterr().err


def test_every_game_says_the_bot_plays_on_its_training_windows(tmp_path) -> None:
    start = {"game_id": "g-9", "seat": "p0", "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}}
    hub = Hub(real_action_stops=True, full_priority=True, bot_windows=True, client_autopass=True, log_dir=tmp_path)
    hub.game_start(start)
    texts = [line["text"] for line in hub.log]
    assert texts.count(BOT_WINDOWS_NOTE) == 1 and texts.count(FULL_PRIORITY_BOT_WINDOWS_NOTE) == 1
    assert FULL_PRIORITY_NOTE not in texts  # it says the bot does not respond in those steps, no longer true
    hub._log_file.flush()
    header = json.loads((tmp_path / "g-9.p0.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert header["bot_windows"] == "action-windows-v1" and header["full_priority"] is True
    plain = Hub(real_action_stops=True, full_priority=True, client_autopass=True, log_dir=tmp_path / "plain")
    plain.game_start(start)
    assert BOT_WINDOWS_NOTE not in [line["text"] for line in plain.log]
    plain._log_file.flush()
    header = json.loads((tmp_path / "plain" / "g-9.p0.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "bot_windows" not in header
