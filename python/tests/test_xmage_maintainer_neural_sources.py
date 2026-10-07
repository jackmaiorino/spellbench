"""The shared neural path requires the pinned original callbacks and cache."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_maintainer_neural_sources import neural_selection_source
from xmage_maintainer_sources import stage


def test_changed_original_callback_refused():
    with pytest.raises(ValueError, match="pinned April callback bytes"):
        neural_selection_source("foreign")


@pytest.mark.parametrize("flag", [None, 1, "true", {}, []])
def test_neural_flag_requires_boolean_before_reads(tmp_path, flag):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {"neural_selection": flag}}}
    with pytest.raises(ValueError, match="neural selection staging.*boolean"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("flag", [False, None])
def test_neural_requires_original_cached_rules(tmp_path, flag):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {
                    "neural_selection": True, "priority_callback": flag}}}
    with pytest.raises(ValueError, match="original cached priority rules"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
