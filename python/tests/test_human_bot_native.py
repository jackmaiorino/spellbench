"""The bot's native groups on the Manabrew path (``python -m spellbench.human --bot-native``): each game's engine
answers the bot's block declarations, card arrangements, selection orders and trigger orders natively with the
bot's own scorer (``--native-seat``, ``--native-scorer`` and the bot's seed and model state from its command).
Without the option nothing changes."""

from __future__ import annotations

import json

import pytest

from spellbench.human import session

BOT_COMMAND = ["python", "kernel_flat_bot_london_human_v1.py", "--scorer", "scorer.exe", "--config", "bot.json",
               "--name", "bot", "--version", "v", "--expect-model-state", "ab" * 32, "--decision-log", "logs"]
BASE = {"tournament_dir": "x", "engine": {"name": "mtg-kernel", "command": ["python", "engine.py", "--bridge", "b"]},
        "bots": [{"name": "human", "command": ["python", "relay.py"]}, {"name": "bot", "command": BOT_COMMAND}],
        "deck_pool": [], "matchups": [["human", "bot"]], "pairs_per_matchup": 8}


@pytest.mark.parametrize("human_first,bot", [(True, "p1"), (False, "p0")])
def test_each_picked_game_gives_its_engine_the_bots_seat_and_scorer(tmp_path, human_first: bool, bot: str) -> None:
    doc = session.picked_game_config(BASE, human_deck="Burn", bot_deck="Faeries", human_first=human_first,
                                     run_dir=tmp_path, opponent="bot", bot_windows=True, bot_native=True)
    assert doc["engine"]["command"] == [
        "python", "engine.py", "--bridge", "b", "--action-windows-seat", bot,
        "--native-seat", bot, "--native-scorer", json.dumps(["scorer.exe", "--config", "bot.json"]),
        "--native-log", str(tmp_path / "native.jsonl"), "--native-expect-model-state", "ab" * 32]
    assert BASE["engine"]["command"] == ["python", "engine.py", "--bridge", "b"]


def test_the_bots_seed_goes_with_it(tmp_path) -> None:
    base = json.loads(json.dumps(BASE))
    base["bots"][1]["command"] = [*BOT_COMMAND, "--seed", "17"]
    command = session.picked_game_config(base, human_deck="Burn", bot_deck="Faeries", human_first=True,
                                         run_dir=tmp_path, opponent="bot", bot_native=True)["engine"]["command"]
    assert command[command.index("--native-seed") + 1] == "17"


def test_without_the_option_the_game_config_is_unchanged(tmp_path) -> None:
    kwargs = dict(human_deck="Burn", bot_deck="Faeries", human_first=True, run_dir=tmp_path, opponent="bot",
                  full_priority=True, bot_windows=True)
    assert session.picked_game_config(BASE, **kwargs) == session.picked_game_config(BASE, **kwargs, bot_native=False)


def test_an_opponent_without_a_scorer_is_refused(tmp_path) -> None:
    with pytest.raises(SystemExit):
        session.picked_game_config(BASE, human_deck="Burn", bot_deck="Faeries", human_first=True, run_dir=tmp_path,
                                   opponent="human", bot_native=True)
