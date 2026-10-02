"""The LLM benchmark refuses changed jars and database bytes before Java starts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
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
        private = cwd / "db"
        assert private != source
        entry.verify_database(private, dict((Path(path).name, sha) for path, sha in declared))
        launched.append(args)
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
