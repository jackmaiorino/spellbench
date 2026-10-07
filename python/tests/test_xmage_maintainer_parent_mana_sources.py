"""Parent payment staging fails before writes without its explicit inputs."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_maintainer_parent_mana_sources import PARENT_MANA_PINS, parent_mana_source
from xmage_maintainer_sources import stage


@pytest.mark.parametrize("sources", [{}, {key: "foreign" for key in PARENT_MANA_PINS}])
def test_parent_mana_refuses_missing_or_changed_lineage(sources):
    with pytest.raises(ValueError, match="all pinned April parent and choice"):
        parent_mana_source(sources)


@pytest.mark.parametrize("flag", [1, None, "true", {}, []])
def test_parent_mana_flag_requires_boolean_before_reads(tmp_path, flag):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {"parent_mana_callback": flag}}}
    with pytest.raises(ValueError, match="parent mana staging.*boolean"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_parent_payment_requires_activation_reservations(tmp_path):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {"parent_mana_callback": True}}}
    with pytest.raises(ValueError, match="requires the original activation player"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
