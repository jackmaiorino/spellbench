"""The bot's native groups on the Manabrew path (``python -m spellbench.human --bot-native``): each game's engine
answers the bot's block declarations, card arrangements, selection orders and trigger orders natively with the
bot's own scorer (``--native-seat``, ``--native-scorer`` and the bot's seed and model state, read from its command with
the bot's own parser). Without the option nothing changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spellbench.human import session

BOT = str(Path(__file__).resolve().parents[2] / "integrations/mtg_kernel/london_human/kernel_flat_bot_london_human_v1.py")
BOT_COMMAND = ["python", BOT, "--scorer", "scorer.exe", "--config", "bot.json", "--name", "bot", "--version", "v",
               "--expect-model-state", "ab" * 32, "--decision-log", "logs"]
BASE = {"tournament_dir": "x", "engine": {"name": "mtg-kernel", "command": ["python", "engine.py", "--bridge", "b"]},
        "bots": [{"name": "human", "command": ["python", "relay.py"]}, {"name": "bot", "command": BOT_COMMAND}],
        "deck_pool": [], "matchups": [["human", "bot"]], "pairs_per_matchup": 8}


def native(tmp_path, command: list[str]) -> list[str]:
    base = json.loads(json.dumps(BASE))
    base["bots"][1]["command"] = command
    doc = session.picked_game_config(base, human_deck="Burn", bot_deck="Faeries", human_first=True,
                                     run_dir=tmp_path, opponent="bot", bot_native=True)
    return doc["engine"]["command"][4:]


def value(command: list[str], flag: str) -> str | None:
    return command[command.index(flag) + 1] if flag in command else None


@pytest.mark.parametrize("human_first,bot", [(True, "p1"), (False, "p0")])
def test_each_picked_game_gives_its_engine_the_bots_seat_and_scorer(tmp_path, human_first: bool, bot: str) -> None:
    doc = session.picked_game_config(BASE, human_deck="Burn", bot_deck="Faeries", human_first=human_first,
                                     run_dir=tmp_path, opponent="bot", bot_windows=True, bot_native=True)
    assert doc["engine"]["command"] == [
        "python", "engine.py", "--bridge", "b", "--action-windows-seat", bot,
        "--native-seat", bot, "--native-scorer", json.dumps(["scorer.exe", "--config", "bot.json"]),
        "--native-log", str(tmp_path / "native.jsonl"), "--native-seed", "0", "--native-expect-model-state", "ab" * 32]
    assert BASE["engine"]["command"] == ["python", "engine.py", "--bridge", "b"]


def test_the_bots_own_syntax_and_precedence(tmp_path) -> None:
    """--flag=value, a repeated flag (the last wins) and --scorer-arg read as the bot reads them."""
    command = native(tmp_path, [*BOT_COMMAND, "--seed=17"])
    assert value(command, "--native-seed") == "17"
    command = native(tmp_path, [*BOT_COMMAND, "--seed", "3", "--seed", "9"])
    assert value(command, "--native-seed") == "9"
    command = native(tmp_path, [*BOT_COMMAND[:6], "--scorer-arg=scorer.py", "--scorer-arg=-q", *BOT_COMMAND[6:]])
    assert json.loads(value(command, "--native-scorer")) == ["scorer.exe", "scorer.py", "-q", "--config", "bot.json"]
    command = native(tmp_path, [*BOT_COMMAND[:10], "--expect-model-state=" + "cd" * 32])
    assert value(command, "--native-expect-model-state") == "cd" * 32


def test_interpreter_options_before_the_bot_script(tmp_path) -> None:
    command = native(tmp_path, ["python", "-u", "-X", "utf8", *BOT_COMMAND[1:], "--seed", "5"])
    assert value(command, "--native-seed") == "5"
    assert json.loads(value(command, "--native-scorer")) == ["scorer.exe", "--config", "bot.json"]


def test_without_the_option_the_game_config_is_unchanged(tmp_path) -> None:
    kwargs = dict(human_deck="Burn", bot_deck="Faeries", human_first=True, run_dir=tmp_path, opponent="bot",
                  full_priority=True, bot_windows=True)
    assert session.picked_game_config(BASE, **kwargs) == session.picked_game_config(BASE, **kwargs, bot_native=False)


@pytest.mark.parametrize("command", [["python", "relay.py"], ["python", BOT, "--name", "bot"]])
def test_an_opponent_the_bots_parser_does_not_take_is_refused(tmp_path, command: list[str]) -> None:
    with pytest.raises(SystemExit):
        native(tmp_path, command)
