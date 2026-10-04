"""Inherited dialogs require their original lineage and owned source options."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_jack_parent_dialog_sources import parent_dialog_source
from xmage_jack_sources import PARENT_SOURCE_PINS, stage


@pytest.mark.parametrize("sources", [{}, {key: "foreign" for key in PARENT_SOURCE_PINS}])
def test_parent_dialog_refuses_changed_lineage(sources):
    with pytest.raises(ValueError, match="every pinned April parent"):
        parent_dialog_source(sources, "foreign")


@pytest.mark.parametrize("flag", [1, None, "true", {}, []])
def test_parent_dialog_flag_requires_boolean_before_reads(tmp_path, flag):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"jack-rl-april": {"parent_dialog_callback": flag}}}
    with pytest.raises(ValueError, match="parent dialog staging.*boolean"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("options", [{}, {"parent_mana_callback": True}, {"parent_card_callback": True}])
def test_parent_dialog_requires_original_payment_and_scoring(tmp_path, options):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"jack-rl-april": {"parent_dialog_callback": True, **options}}}
    with pytest.raises(ValueError, match="original parent mana and scoring"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
