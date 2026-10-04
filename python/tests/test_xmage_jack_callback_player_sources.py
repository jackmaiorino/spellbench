"""A complete callback stage must name all original components before asset reads."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_jack_callback_player_sources import callback_player_source
from xmage_jack_sources import stage


def test_pinned_original_required():
    with pytest.raises(ValueError, match="pinned April callback bytes"):
        callback_player_source("foreign")


@pytest.mark.parametrize("flag", [1, None, {}, [], "true"])
def test_callback_flag_boolean_before_assets(tmp_path, flag):
    with pytest.raises(ValueError, match="callback player staging.*boolean"):
        stage({"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
               "inference_backends": {"jack-rl-april": {"callback_player": flag}}}, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("missing", ["priority_choice_player", "target_callback", "card_set_callback",
                                     "mode_callback", "dialog_callback", "combat_callback", "london_callback"])
def test_every_callback_required(tmp_path, missing):
    flags = dict.fromkeys(["priority_choice_player", "target_callback", "card_set_callback", "mode_callback",
                          "dialog_callback", "combat_callback", "london_callback"], True)
    flags.pop(missing)
    flags.update(callback_player=True, mulligan_encoder="original")
    with pytest.raises(ValueError, match="every original strategic callback"):
        stage({"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
               "inference_backends": {"jack-rl-april": flags}}, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_mulligan_encoder_required(tmp_path):
    flags = dict.fromkeys(["callback_player", "priority_choice_player", "target_callback", "card_set_callback",
                          "mode_callback", "dialog_callback", "combat_callback", "london_callback"], True)
    with pytest.raises(ValueError, match="original mulligan encoder"):
        stage({"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
               "inference_backends": {"jack-rl-april": flags}}, tmp_path, tmp_path / "out")
