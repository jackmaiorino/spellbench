"""Build the reviewed XMage kit and the pinned Exp1 decision encoder slice."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from xmage_encoder_sources import stage
from xmage_verified_entry import verify_build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--javac", default="javac")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    manifest = repo / "engines/xmage/releases.json"
    engine = args.engine.resolve()
    # Qualification uses the reviewed build, not an arbitrary release bundle.
    engine_manifest = engine / "BUILD-MANIFEST.json"
    engine_manifest_sha = hashlib.sha256(engine_manifest.read_bytes()).hexdigest()
    if engine_manifest_sha != "3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93":
        raise ValueError("encoder build needs the reviewed 004913a engine manifest")
    verify_build(engine, engine_manifest, engine_manifest_sha)
    jdk = subprocess.run([args.javac, "-version"], check=True, capture_output=True, text=True)
    version = (jdk.stdout + jdk.stderr).strip()
    if version != "javac 23.0.1":
        raise ValueError("preserve the engine qualification's JDK 23.0.1 pin")
    if args.out.exists():
        raise ValueError("model build needs a new job directory")
    staged = stage(json.loads(manifest.read_text()), args.inputs, args.out / "sources")
    paths = {k: args.out.resolve() / k for k in ("core", "kit", "model")}
    for directory in paths.values():
        directory.mkdir()
    common = [args.javac, "--release", "8", "-encoding", "UTF-8", "-nowarn", "-Xlint:-options"]
    source_sets = {"core": sorted((repo / "engines/xmage/kit/core/src").rglob("*.java")),
                   "kit": sorted((repo / "engines/xmage/kit/xmage/src").rglob("*.java")),
                   "model": sorted((repo / "engines/xmage/models/src").rglob("*.java"))
                            + sorted((args.out / "sources").rglob("*.java"))}
    hashes = {}
    for name, sources in source_sets.items():
        cp = os.pathsep.join(str(p) for p in ([paths["core"]] if name == "kit" else
                            [paths["core"], paths["kit"]] if name == "model" else []) + [engine / "lib/*"])
        subprocess.run(common + ["-cp", cp, "-d", str(paths[name])] + [str(p) for p in sources], check=True)
        for path in sources:
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    shutil.copytree(repo / "engines/xmage/kit/xmage/resources", paths["kit"], dirs_exist_ok=True)
    result = {"schema": "spellbench-draftzero-encoder-build/v1", "jdk": version,
              "engine_manifest_sha256": engine_manifest_sha,
              "inputs_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "source_sha256": hashes, "encoder_stage": staged,
              "scope": "priority, target and binary decision slices; no complete bot, original search or rating"}
    with (args.out / "BUILD.json").open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({"out": str(args.out), "jdk": version, "compiled": list(source_sets)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
