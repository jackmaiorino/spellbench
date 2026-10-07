"""Activation plumbing is an explicit private source option with pinned bytes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_maintainer_activation_sources import activation_source
from xmage_maintainer_sources import stage


def test_activation_extraction_refuses_unpinned_callback_bytes():
    with pytest.raises(ValueError, match="pinned April callback"):
        activation_source("changed or foreign callback")


@pytest.mark.parametrize("flag", [1, None, "true", {}, []])
def test_activation_flag_requires_boolean_before_any_private_reads(tmp_path, flag):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "assets":[],
                "inference_backends":{"maintainer-rl-april":{"activation_callback":flag}}}
    with pytest.raises(ValueError, match="activation staging.*boolean"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_activation_dispatch_requires_original_priority_owner_rules(tmp_path):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "assets":[],
                "inference_backends":{"maintainer-rl-april":{"activation_callback":True}}}
    with pytest.raises(ValueError, match="requires the original priority rules"):
        stage(manifest, tmp_path, tmp_path / "out")
