"""The LLM benchmark refuses changed jars and database bytes before Java starts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spellbench.arena.config import TournamentConfig
from spellbench.bench.definition import load_benchmark, substitute
from spellbench.bench.run import run_files
from spellbench.file_pins import PinningError, verify_files

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


REVIEWED_MODEL_ENGINE = "3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93"


def overlay_inputs(tmp_path):
    build = tmp_path / "overlay"
    classes = {}
    for name in ("server/EngineServer", "server/EngineProfile", "server/GameSession",
                 "observe/ObservationBuilder", "observe/StackAbilityText"):
        relative = "kit/mage/player/spellbench/" + name + ".class"
        path = build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
        classes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    resource = build / "kit/mage/player/spellbench/catalog.json"
    resource.write_bytes(b"synthetic public profile")
    metadata = {"schema": "spellbench-draftzero-encoder-build/v1", "jdk": "javac 23.0.1",
                "current_overlay_compiled": True, "engine_manifest_sha256": REVIEWED_MODEL_ENGINE,
                "class_files_sha256": classes,
                "resource_files_sha256": {"mage/player/spellbench/catalog.json":
                                          hashlib.sha256(resource.read_bytes()).hexdigest()}}
    return build, metadata


def overlay_pin(build, metadata):
    manifest = build / "BUILD.json"
    manifest.write_text(json.dumps(metadata))
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_overlay_checks_only_the_game_kit_and_accepts_windows_build_paths(tmp_path):
    build, metadata = overlay_inputs(tmp_path)
    metadata["class_files_sha256"] = {name.replace("/", "\\"): digest
                                      for name, digest in metadata["class_files_sha256"].items()}
    # Neither model classes nor model dependencies enter the engine classpath.
    (build / "model").mkdir()
    (build / "model/unused.class").write_bytes(b"not loaded by the game")
    digest = overlay_pin(build, metadata)
    assert entry.verify_overlay(build, digest, REVIEWED_MODEL_ENGINE) == build / "kit"


@pytest.mark.parametrize("mutation", ["manifest", "class", "resource", "extra", "missing",
                                     "compile-only", "engine", "old-overlay", "jdk",
                                     "missing-implementation", "escape", "alias", "resource-class"])
def test_overlay_refuses_changed_files_and_ineligible_builds(tmp_path, mutation):
    build, metadata = overlay_inputs(tmp_path)
    first = next(iter(metadata["class_files_sha256"]))
    if mutation == "compile-only":
        metadata.update(schema="spellbench-draftzero-model-compile/v1", reviewed_runtime=False)
    elif mutation == "engine":
        metadata["engine_manifest_sha256"] = "0" * 64
    elif mutation == "old-overlay":
        metadata["current_overlay_compiled"] = False
    elif mutation == "jdk":
        metadata["jdk"] = "javac 24"
    elif mutation == "missing-implementation":
        del metadata["class_files_sha256"][first]
        (build / first).unlink()
    elif mutation == "escape":
        metadata["resource_files_sha256"]["../outside"] = "0" * 64
    elif mutation == "alias":
        metadata["class_files_sha256"][first.replace("/", "\\")] = metadata["class_files_sha256"][first]
    elif mutation == "resource-class":
        metadata["resource_files_sha256"][first.removeprefix("kit/")] = metadata["class_files_sha256"][first]
    digest = overlay_pin(build, metadata)
    if mutation == "manifest":
        (build / "BUILD.json").write_text("{}")
    elif mutation == "class":
        (build / first).write_bytes(b"changed class")
    elif mutation == "resource":
        (build / "kit/mage/player/spellbench/catalog.json").write_bytes(b"changed catalog")
    elif mutation == "extra":
        (build / "kit/undeclared.txt").write_bytes(b"injected resource")
    elif mutation == "missing":
        (build / first).unlink()
    with pytest.raises((ValueError, OSError)):
        entry.verify_overlay(build, digest, REVIEWED_MODEL_ENGINE)


def test_overlay_refuses_linked_classpath_inputs(tmp_path):
    build, metadata = overlay_inputs(tmp_path)
    first = next(iter(metadata["class_files_sha256"]))
    target = tmp_path / "outside.class"
    target.write_bytes((build / first).read_bytes())
    (build / first).unlink()
    try:
        (build / first).symlink_to(target)
    except OSError:
        pytest.skip("creating symlinks requires privileges on this host")
    with pytest.raises(ValueError, match="link"):
        entry.verify_overlay(build, overlay_pin(build, metadata), REVIEWED_MODEL_ENGINE)


def test_overlay_cannot_change_the_reviewed_engine_association(tmp_path):
    build, metadata = overlay_inputs(tmp_path)
    metadata["engine_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="reviewed engine"):
        entry.verify_overlay(build, overlay_pin(build, metadata), "0" * 64)


@pytest.mark.parametrize("flag,value", [("--overlay-manifest", "BUILD.json"),
                                       ("--overlay-build-sha256", "1" * 64)])
def test_overlay_launch_needs_both_manifest_and_digest(tmp_path, monkeypatch, flag, value):
    build, _, manifest, digest = inputs(tmp_path)
    source, declared = database(tmp_path)
    command = ["xmage_verified_entry.py", "--java", sys.executable, "--build", str(build),
               "--db", str(source), "--work", str(tmp_path / "work"),
               "--manifest", str(manifest), "--manifest-sha256", digest, flag, value]
    for path, sha256 in declared:
        command += ["--db-file", path, sha256]
    monkeypatch.setattr(sys, "argv", command)
    monkeypatch.setattr(entry.subprocess, "run", lambda *a, **kw: pytest.fail("Java must not start"))
    assert entry.main() == 2


@pytest.mark.parametrize("overlay", [False, True])
@pytest.mark.parametrize("stack_text", [False, True])
def test_launch_declares_stack_text_only_when_explicitly_requested(tmp_path, monkeypatch, stack_text, overlay):
    build, _, manifest, digest = inputs(tmp_path)
    java = tmp_path / "java"
    java.write_text("synthetic executable")
    database = tmp_path / "db"
    database.mkdir()
    source = database / "cards.h2.mv.db"
    source.write_bytes(b"synthetic database")
    argv = ["xmage_verified_entry", "--java", str(java), "--build", str(build),
            "--db", str(database), "--db-file", str(source), hashlib.sha256(source.read_bytes()).hexdigest(),
            "--work", str(tmp_path / "work"), "--manifest", str(manifest), "--manifest-sha256", digest]
    if stack_text:
        argv.append("--stack-text")
    if overlay:
        argv += ["--overlay-manifest", str(tmp_path / "overlay/BUILD.json"), "--overlay-build-sha256", "1" * 64]
        def verify_overlay(path, expected, engine):
            assert path == tmp_path / "overlay" and expected == "1" * 64 and engine == digest
            return path / "kit"
        monkeypatch.setattr(entry, "verify_overlay", verify_overlay)
    launched = []

    def run(command, **kwargs):
        launched.append(command)
        assert (Path(kwargs["cwd"]) / "db/cards.h2.mv.db").read_bytes() == source.read_bytes()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(entry.subprocess, "run", run)
    assert entry.main() == 0
    assert len(launched) == 1
    assert ("-Dspellbench.stackText=true" in launched[0]) == stack_text
    classpath = launched[0][launched[0].index("-cp") + 1]
    assert classpath == os.pathsep.join(([str(tmp_path / "overlay/kit")] if overlay else [])
                                      + [str(build / "lib/*")])


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


def database(tmp_path):
    source = tmp_path / "db"
    source.mkdir()
    declared = []
    for name in ("cards.h2.mv.db", "cards.h2.trace.db"):
        path = source / name
        path.write_bytes(name.encode())
        declared.append([str(path), hashlib.sha256(path.read_bytes()).hexdigest()])
    return source, declared


@pytest.mark.parametrize("mutation", ["none", "changed", "extra", "missing", "during-copy"])
def test_database_is_verified_before_java_opens_its_private_copy(tmp_path, monkeypatch, mutation):
    build, _, manifest, digest = inputs(tmp_path)
    source, declared = database(tmp_path)
    command = ["xmage_verified_entry.py", "--java", sys.executable, "--build", str(build),
               "--db", str(source), "--work", str(tmp_path / "work"),
               "--manifest", str(manifest), "--manifest-sha256", digest]
    for path, sha256 in declared:
        command += ["--db-file", path, sha256]
    monkeypatch.setattr(sys, "argv", command)
    launched = []

    def launch(args, *, cwd, check):
        launched.append(args)
        private = cwd / "db"
        assert private != source
        entry.verify_database(private, dict((Path(path).name, sha) for path, sha in declared))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(entry.subprocess, "run", launch)
    if mutation == "changed":
        (source / "cards.h2.mv.db").write_bytes(b"changed")
    elif mutation == "extra":
        (source / "undeclared.db").write_bytes(b"extra")
    elif mutation == "missing":
        (source / "cards.h2.trace.db").unlink()
    elif mutation == "during-copy":
        real_copy = entry.shutil.copytree

        def copy_then_mutate(src, dst):
            result = real_copy(src, dst)
            (dst / "cards.h2.mv.db").write_bytes(b"changed during copying")
            return result

        monkeypatch.setattr(entry.shutil, "copytree", copy_then_mutate)
    assert entry.main() == (0 if mutation == "none" else 2)
    assert bool(launched) == (mutation == "none")


@pytest.mark.parametrize("mutation", ["outside", "duplicate", "bad-hash"])
def test_database_declarations_cannot_escape_or_alias_the_input_set(tmp_path, mutation):
    source, declared = database(tmp_path)
    if mutation == "outside":
        outside = tmp_path / "cards.h2.mv.db"
        outside.write_bytes(b"outside")
        declared[0][0] = str(outside)
    elif mutation == "duplicate":
        declared.append(declared[0])
    else:
        declared[0][1] = "not-a-sha256"
    with pytest.raises(ValueError):
        entry.database_inputs(source.resolve(), declared)


def test_benchmark_database_sources_are_in_the_arena_launch_and_publication_checks(tmp_path):
    source, _ = database(tmp_path)
    root = Path(__file__).parents[2]
    bench = load_benchmark(root / "benchmarks/standard-mirror-xmage")
    values = {"PYTHON": sys.executable, "JAVA": sys.executable,
              "XMAGE_VERIFIED_ENTRY": str(root / "python/tools/xmage_verified_entry.py"),
              "XMAGE_BUILD": str(tmp_path / "build"), "XMAGE_DB": str(source),
              "XMAGE_ENGINE_WORK": str(tmp_path / "work"),
              "XMAGE_BUILD_MANIFEST": str(tmp_path / "manifest.json")}
    doc = bench.tournament_config("out/test")
    doc["engine"]["command"] = [substitute(part, values) for part in doc["engine"]["command"]]
    doc["bots"] = [bot for bot in doc["bots"] if bot["type"] == "builtin"]
    files = run_files(TournamentConfig.from_json(doc))
    assert {file.path for file in files if file.file_name.startswith("cards.h2.")} == {
        (source / "cards.h2.mv.db").absolute(), (source / "cards.h2.trace.db").absolute()}
    verify_files(files)
    (source / "cards.h2.mv.db").write_bytes(b"changed after the final game")
    with pytest.raises(PinningError, match="changed"):
        verify_files(files)
