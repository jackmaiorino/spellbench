"""Private priority extraction refuses altered input and ambiguous configuration."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_maintainer_priority_sources import priority_source
from xmage_maintainer_sources import stage


def test_priority_extraction_requires_original_source_bytes():
    with pytest.raises(ValueError, match="pinned April callback"):
        priority_source("untrusted or altered source")


@pytest.mark.parametrize("flag", [1, None, "true", {}])
def test_priority_stage_refuses_nonboolean_flag_before_reading_private_sources(tmp_path, flag):
    manifest = {"schema": "spellbench-xmage-release-inputs/v1", "assets": [],
                "inference_backends": {"maintainer-rl-april": {"priority_callback": flag}}}
    with pytest.raises(ValueError, match="priority staging.*boolean"):
        stage(manifest, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
