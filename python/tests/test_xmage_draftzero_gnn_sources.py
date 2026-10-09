"""The graph network's pinned sources stage only with their declared, recorded edits."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_draftzero_gnn_sources as source

MANIFEST = json.loads((Path(__file__).parents[2] / "engines/xmage/releases.json").read_text(encoding="utf-8"))
# An owned input root holding the pinned draft-zero files (fetched with xmage_release_assets.py).
PINNED = os.environ.get("SPELLBENCH_DRAFTZERO_GNN_SOURCES")


def synthetic(root):
    manifest = json.loads(json.dumps(MANIFEST))
    for asset in manifest["assets"]:
        if asset["id"].startswith("draftzero-gnn-src-"):
            data = ("// synthetic " + asset["id"] + "\n").encode()
            (root / asset["filename"]).write_bytes(data)
            asset.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    return manifest


@pytest.mark.parametrize("mutation", ["missing-edit", "bytes", "revision", "manifest-revision"])
def test_changed_or_unpinned_inputs_are_refused_before_any_output(tmp_path, mutation):
    manifest = synthetic(tmp_path)
    asset = next(a for a in manifest["assets"] if a["id"] == "draftzero-gnn-src-stateencoder")
    if mutation == "bytes":
        (tmp_path / asset["filename"]).write_bytes(b"changed")
    elif mutation == "revision":
        asset["source_revision"] = "another fork"
    elif mutation == "manifest-revision":
        manifest["sources"]["draftzero_gnn"]["revision"] = "0" * 40
    with pytest.raises(ValueError):
        source.stage(manifest, tmp_path, tmp_path / "staged")
    assert not (tmp_path / "staged").exists()


@pytest.mark.skipif(not PINNED, reason="set SPELLBENCH_DRAFTZERO_GNN_SOURCES to the pinned source input root")
def test_pinned_sources_stage_into_their_namespaces_with_every_edit_recorded(tmp_path):
    result = source.stage(MANIFEST, Path(PINNED), tmp_path / "staged")
    staged = {p.name: p for p in (tmp_path / "staged").rglob("*.java")}
    assert set(staged) == {name + ".java" for name in source.SOURCES}
    for name, (_, package, _) in source.SOURCES.items():
        text = staged[name + ".java"].read_text(encoding="utf-8")
        assert f"package {package};" in text and hashlib.sha256(text.encode()).hexdigest() == \
            result["staged_source_sha256"][name + ".java"]
        for forbidden in ("List.of(", "import org.draftzero", "package org.draftzero", "TargetImpl.STOP_CHOOSING",
                          "getPlayerHistory()", "GameStateEvaluator3.", "import java.net.http", "import com.google.gson",
                          "import org.msgpack"):
            assert forbidden not in text, (name, forbidden)
    bench = staged["BenchSearch.java"].read_text(encoding="utf-8")
    assert "public static Result searchTree(" in bench and "searchIS(" not in bench
    net = staged["GraphNet.java"].read_text(encoding="utf-8")
    assert "GraphRecord.arrays(eng.getGame(), eng.targetPlayer, eng.playerId, q.ask, false)" in net
    encoder = staged["StateEncoder.java"].read_text(encoding="utf-8")
    assert "GLOBAL_SEED       = 0x9E3779B185EBCA87L" in encoder and "perfectInfo = true" in encoder
    assert json.loads((tmp_path / "staged/STAGE.json").read_text(encoding="utf-8")) == result
