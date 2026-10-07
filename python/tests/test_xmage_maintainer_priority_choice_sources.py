"""Original player dispatch cannot be staged without inherited and neural paths."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_maintainer_priority_choice_sources import priority_choice_source
from xmage_maintainer_sources import stage


def test_original_callback_revision_required():
    with pytest.raises(ValueError, match="pinned April callback bytes"):
        priority_choice_source("foreign")


@pytest.mark.parametrize("flag", [1, None, {}, [], "true"])
def test_flag_requires_boolean_before_asset_reads(tmp_path, flag):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {"priority_choice_player": flag}}}
    with pytest.raises(ValueError, match="priority/choice player staging.*boolean"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("options", [{}, {"parent_dialog_callback": True}, {"neural_selection": True}])
def test_inherited_and_neural_paths_required(tmp_path, options):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {"priority_choice_player": True, **options}}}
    with pytest.raises(ValueError, match="original parent dialogs and neural selection"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
