"""Compilation on CI cannot relax the reviewed runtime or source pins."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_model_build import reviewed_model_register, verify_model_engine


def test_reviewed_model_register_only_changes_the_audited_source_counter_trigger():
    path = Path(__file__).parents[2] / "engines/xmage/kit/xmage/resources/spellbench/kit/xmage/register.json"
    raw = path.read_bytes()
    original = json.loads(raw)
    result = json.loads(reviewed_model_register(raw))
    assert path.read_bytes() == raw
    before = original["cards"].pop("Brineborn Cutthroat")
    after = result["cards"].pop("Brineborn Cutthroat")
    assert original == result
    assert before["triggers"] == "event_data"
    assert after["triggers"] == "event_free" and after["status"] == "supported"
    assert before["class"] == after["class"]
    assert before["trigger_classes"] == after["trigger_classes"]


@pytest.mark.parametrize("field,value", [
    ("class", "mage.cards.other.ChangedCard"),
    ("reading_classes", ["AddCountersSourceEffect", "CapturedEventEffect"]),
    ("trigger_classes", ["OtherTriggeredAbility"]),
    ("optional_costs", ["KickerAbility"]),
])
def test_model_trigger_audit_refuses_changed_or_additional_unreviewed_mechanics(field, value):
    path = Path(__file__).parents[2] / "engines/xmage/kit/xmage/resources/spellbench/kit/xmage/register.json"
    register = json.loads(path.read_bytes())
    register["cards"]["Brineborn Cutthroat"][field] = value
    with pytest.raises(ValueError, match="no longer matches"):
        reviewed_model_register(json.dumps(register).encode())


def engine_fixture(root):
    releases = json.loads((Path(__file__).parents[2] / "engines/xmage/releases.json").read_bytes())
    (root / "lib").mkdir()
    data = b"synthetic compile-check jar"
    (root / "lib/engine.jar").write_bytes(data)
    identity = {"xmage_commit": releases["sources"]["xmage"]["revision"],
                "cabt_commit": releases["sources"]["cabt"]["revision"], "patch_series": "applied",
                "jars": {"engine.jar": hashlib.sha256(data).hexdigest()}}
    (root / "BUILD-MANIFEST.json").write_text(json.dumps(identity))
    return identity


def test_compile_engine_is_refused_by_the_default_runtime_pin(tmp_path):
    engine_fixture(tmp_path)
    with pytest.raises(ValueError, match="reviewed 004913a"):
        verify_model_engine(tmp_path)
    actual = verify_model_engine(tmp_path, compile_only=True)
    assert actual == hashlib.sha256((tmp_path / "BUILD-MANIFEST.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("field", ["xmage_commit", "cabt_commit", "patch_series", "private_inputs"])
def test_compile_mode_preserves_public_source_pins_and_excludes_private_inputs(tmp_path, field):
    identity = engine_fixture(tmp_path)
    if field != "private_inputs":
        identity[field] = "changed"
        (tmp_path / "BUILD-MANIFEST.json").write_text(json.dumps(identity))
    with pytest.raises(ValueError, match="pinned public engine"):
        verify_model_engine(tmp_path, compile_only=True, private_inputs=field == "private_inputs")


@pytest.mark.parametrize("mutation", ["changed-jar", "undeclared-jar"])
def test_compile_mode_still_hashes_the_actual_classpath(tmp_path, mutation):
    engine_fixture(tmp_path)
    (tmp_path / ("lib/engine.jar" if mutation == "changed-jar" else "lib/extra.jar")).write_bytes(b"different")
    with pytest.raises(ValueError, match="jar changed|undeclared jars"):
        verify_model_engine(tmp_path, compile_only=True)
