"""The LLM benchmark's XMage entry rejects a changed classpath before launch."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("xmage_entry", Path(__file__).parents[1] / "tools/xmage_verified_entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def inputs(tmp_path):
    build = tmp_path / "build"
    (build / "lib").mkdir(parents=True)
    jar = build / "lib" / "engine.jar"
    jar.write_bytes(b"pinned jar fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"jars": {jar.name: hashlib.sha256(jar.read_bytes()).hexdigest()}}))
    return build, jar, manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_all_declared_jars_match_the_fixed_manifest(tmp_path):
    build, jar, manifest, digest = inputs(tmp_path)
    assert entry.verify_build(build, manifest, digest) == [jar]


@pytest.mark.parametrize("mutation", ["jar", "manifest", "extra", "uppercase", "missing"])
def test_changed_or_undeclared_inputs_are_refused(tmp_path, mutation):
    build, jar, manifest, digest = inputs(tmp_path)
    if mutation == "jar":
        jar.write_bytes(b"changed")
    elif mutation == "manifest":
        manifest.write_text("{}")
    elif mutation == "extra":
        (build / "lib" / "extra.jar").write_bytes(b"extra")
    elif mutation == "uppercase":
        (build / "lib" / "extra.JAR").write_bytes(b"extra")
    else:
        jar.unlink()
    with pytest.raises((ValueError, OSError)):
        entry.verify_build(build, manifest, digest)
