"""Launch the pinned XMage v2 engine with a private database per process.

This is a host launcher, not a new rules implementation. Every jar is checked
against the committed build-manifest hash before Java starts. The arena owns
timeouts and process-tree cleanup. The source database is never opened by Java.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


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
    if {path.name for path in (build / "lib").glob("*.jar")} != set(jars):
        raise ValueError("XMage classpath has undeclared jars")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        java, build, source = args.java.resolve(strict=True), args.build.resolve(strict=True), args.db.resolve(strict=True)
        if not java.is_file() or not source.is_dir():
            raise ValueError("Java and database inputs are invalid")
        verify_build(build, args.manifest, args.manifest_sha256)
        args.work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="spellbench-xmage-", dir=args.work) as temporary:
            directory = Path(temporary)
            shutil.copytree(source, directory / "db")
            return subprocess.run([str(java), "-Xmx2g", "-cp", str(build / "lib" / "*"),
                                   "mage.player.spellbench.server.EngineServer"],
                                  cwd=directory, check=False).returncode
    except (ValueError, OSError, KeyError, TypeError):
        print("XMage launch refused: invalid or changed pinned inputs", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
