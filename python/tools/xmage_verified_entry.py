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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


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
    args = parser.parse_args()
    try:
        java, build, source = args.java.resolve(strict=True), args.build.resolve(strict=True), args.db.resolve(strict=True)
        if not java.is_file() or not source.is_dir():
            raise ValueError("Java and database inputs are invalid")
        verify_build(build, args.manifest, args.manifest_sha256)
        database = database_inputs(source, args.db_file)
        args.work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="spellbench-xmage-", dir=args.work) as temporary:
            directory = Path(temporary)
            shutil.copytree(source, directory / "db")
            verify_database(directory / "db", database)
            settings = ["-Dspellbench.stackText=true"] if args.stack_text else []
            return subprocess.run([str(java), "-Xmx2g", *settings, "-cp", str(build / "lib" / "*"),
                                   "mage.player.spellbench.server.EngineServer"],
                                  cwd=directory, check=False).returncode
    except (ValueError, OSError, KeyError, TypeError):
        print("XMage launch refused: invalid or changed pinned inputs", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
