"""Launch the pinned XMage v2 engine with a private database per process.

This is a host launcher, not a new rules implementation. Every jar and private
database copy is checked against committed hashes before Java starts. Database
files are explicit command arguments so the arena also pins and checks their
source bytes. The arena owns timeouts and process-tree cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


def database_inputs(source: Path, declared: list[list[str]]) -> dict[str, str]:
    """Require named, regular database files directly inside the source directory."""
    expected = {}
    for name, digest in declared:
        path = Path(name)
        if (path.is_symlink() or not path.is_file() or path.resolve().parent != source
                or path.name in expected or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
            raise ValueError("invalid database input")
        expected[path.name] = digest
    if not expected or {path.name for path in source.iterdir()} != set(expected):
        raise ValueError("XMage database has undeclared inputs")
    return expected


def verify_database(directory: Path, expected: dict[str, str]) -> None:
    """Verify the private copy, including changes during the copy, before Java opens it."""
    if {path.name for path in directory.iterdir()} != set(expected):
        raise ValueError("XMage database has undeclared inputs")
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("database input must be a regular file")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("XMage database changed")


def verify_build(build: Path, manifest: Path, expected_sha256: str) -> list[Path]:
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("XMage build manifest changed")
    jars = json.loads(raw)["jars"]
    if not isinstance(jars, dict) or not jars:
        raise ValueError("XMage build manifest has no jars")
    files = []
    for name, expected in sorted(jars.items()):
        if Path(name).name != name or "/" in name or "\\" in name or not name.endswith(".jar"):
            raise ValueError("invalid jar name")
        path = build / "lib" / name
        if path.is_symlink():
            raise ValueError("jar must be a regular file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(2**20), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("XMage jar changed")
        files.append(path)
    if {path.name for path in (build / "lib").iterdir() if path.suffix in (".jar", ".JAR")} != set(jars):
        raise ValueError("XMage classpath has undeclared jars")
    return files


def verify_overlay(build: Path, expected_sha256: str, engine_sha256: str) -> Path:
    """Load only the pinned kit overlay compiled against the reviewed model engine.

    Model/core classes and dependencies are not added to the game classpath.
    Compilation-only manifests cannot authorize this runtime path.
    """
    build = build.absolute()
    manifest = build / "BUILD.json"

    def linked(path: Path) -> bool:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()

    def checked_file(path: Path) -> str:
        if any(linked(parent) for parent in (path, *path.parents)):
            raise ValueError("overlay input traverses a link")
        if not path.is_file():
            raise ValueError("overlay input must be a regular file")
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    if checked_file(manifest) != expected_sha256:
        raise ValueError("overlay manifest changed")
    metadata = json.loads(manifest.read_bytes())
    if (not isinstance(metadata, dict)
            or metadata.get("schema") != "spellbench-draftzero-encoder-build/v1"
            or metadata.get("current_overlay_compiled") is not True
            or metadata.get("reviewed_runtime") is False
            or metadata.get("jdk") != "javac 23.0.1"
            or engine_sha256 != "3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93"
            or metadata.get("engine_manifest_sha256") != engine_sha256):
        raise ValueError("overlay needs its reviewed engine and runtime build")

    def paths(declared):
        if not isinstance(declared, dict) or not declared:
            raise ValueError("overlay has no pinned runtime files")
        normalized = {}
        for name, digest in declared.items():
            if not isinstance(name, str) or not isinstance(digest, str):
                raise ValueError("invalid overlay declaration")
            name = name.replace("\\", "/")
            relative = PurePosixPath(name)
            if (":" in name or relative.is_absolute() or name in normalized
                    or ".." in relative.parts or name != relative.as_posix()
                    or re.fullmatch("[a-f0-9]{64}", digest) is None):
                raise ValueError("invalid overlay path or digest")
            normalized[name] = digest
        return normalized

    classes = paths(metadata.get("class_files_sha256"))
    if any(not name.startswith(("core/", "kit/", "model/")) or not name.endswith(".class")
           for name in classes):
        raise ValueError("invalid overlay class directories")
    declared = {name.removeprefix("kit/"): digest for name, digest in classes.items()
                if name.startswith("kit/")}
    required = {"mage/player/spellbench/" + name + ".class" for name in (
        "server/EngineServer", "server/EngineProfile", "server/GameSession",
        "observe/ObservationBuilder", "observe/StackAbilityText")}
    if not required.issubset(declared):
        raise ValueError("overlay lacks the public stack observation implementation")
    resources = paths(metadata.get("resource_files_sha256"))
    if "mage/player/spellbench/catalog.json" not in resources:
        raise ValueError("overlay lacks its pinned public catalog")
    if set(resources) & set(declared) or any(name.endswith(".class") for name in resources):
        raise ValueError("overlay resources cannot replace classes")
    declared.update(resources)
    kit = build / "kit"
    actual = set()
    for path in (kit, *kit.rglob("*")):
        if linked(path):
            raise ValueError("overlay classpath contains a link")
        if path.is_file():
            actual.add(path.relative_to(kit).as_posix())
    if actual != set(declared):
        raise ValueError("overlay classpath has missing or undeclared files")
    for name, digest in declared.items():
        if checked_file(kit / name) != digest:
            raise ValueError("overlay runtime file changed")
    return kit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--db-file", nargs=2, action="append", required=True, metavar=("PATH", "SHA256"))
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--stack-text", action="store_true",
                        help="Declare public stack ability rules text in the engine profile")
    parser.add_argument("--overlay-manifest", type=Path,
                        help="BUILD.json of the pinned model build containing the current game overlay")
    parser.add_argument("--overlay-build-sha256", help="SHA-256 of the overlay build's BUILD.json")
    args = parser.parse_args()
    try:
        java, build, source = args.java.resolve(strict=True), args.build.resolve(strict=True), args.db.resolve(strict=True)
        if not java.is_file() or not source.is_dir():
            raise ValueError("Java and database inputs are invalid")
        verify_build(build, args.manifest, args.manifest_sha256)
        if bool(args.overlay_manifest) != bool(args.overlay_build_sha256):
            raise ValueError("overlay needs both its build and manifest pin")
        classpath = str(build / "lib" / "*")
        if args.overlay_manifest:
            if args.overlay_manifest.name != "BUILD.json":
                raise ValueError("overlay manifest must name its build's BUILD.json")
            kit = verify_overlay(args.overlay_manifest.parent, args.overlay_build_sha256, args.manifest_sha256)
            classpath = os.pathsep.join((str(kit), classpath))
        database = database_inputs(source, args.db_file)
        args.work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="spellbench-xmage-", dir=args.work) as temporary:
            directory = Path(temporary)
            shutil.copytree(source, directory / "db")
            verify_database(directory / "db", database)
            settings = ["-Dspellbench.stackText=true"] if args.stack_text else []
            return subprocess.run([str(java), "-Xmx2g", *settings, "-cp", classpath,
                                   "mage.player.spellbench.server.EngineServer"],
                                  cwd=directory, check=False).returncode
    except (ValueError, OSError, KeyError, TypeError):
        print("XMage launch refused: invalid or changed pinned inputs", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
