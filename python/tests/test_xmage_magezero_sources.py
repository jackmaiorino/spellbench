"""Source staging cannot alias Exp1 or execute an unverified encoder input."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_magezero_sources as source


def inputs(root):
    assets = []
    for name in source.NAMES:
        filename = name + ".java"
        data = ("package mage.player.ai.encoder;\n" + "\n".join(source.REWRITES.get(filename, {}))).encode()
        (root / ("magezero-v02-" + filename)).write_bytes(data)
        assets.append({"id": "magezero-v02-" + name.lower(), "filename": "magezero-v02-" + filename,
                       "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                       "kind": "source-code", "source_revision": source.REVISION})
    return {"schema": "spellbench-xmage-release-inputs/v1", "assets": assets}


def test_staged_names_do_not_collide_with_exp1_and_retain_recorded_hash_contract(tmp_path):
    manifest = inputs(tmp_path)
    result = source.stage(manifest, tmp_path, tmp_path / "staged")
    assert result["feature_hash_bins"] == 2147483647 and result["policy_width"] == 128
    for name in source.NAMES:
        raw = (tmp_path / "staged" / (name + ".java")).read_bytes()
        assert b"package spellbench.models.magezero.v02.encoder;" in raw
        assert b"package mage.player.ai.encoder;" not in raw
        assert hashlib.sha256(raw).hexdigest() == result["staged_source_sha256"][name + ".java"]
    assert json.loads((tmp_path / "staged/STAGE.json").read_bytes()) == result


@pytest.mark.parametrize("mutation", ["bytes", "revision", "duplicate", "missing-rewrite"])
def test_changed_or_ambiguous_input_is_refused_before_any_staged_output(tmp_path, mutation):
    manifest = inputs(tmp_path)
    asset = manifest["assets"][-1]
    if mutation == "bytes":
        (tmp_path / asset["filename"]).write_bytes(b"changed")
    elif mutation == "revision":
        asset["source_revision"] = "another fork"
    elif mutation == "duplicate":
        manifest["assets"].append(asset)
    else:
        raw = b"package mage.player.ai.encoder;"
        (tmp_path / asset["filename"]).write_bytes(raw)
        asset.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    with pytest.raises(ValueError):
        source.stage(manifest, tmp_path, tmp_path / "staged")
    assert not (tmp_path / "staged").exists()
