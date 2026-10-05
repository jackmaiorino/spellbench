"""Build the reviewed XMage kit, pinned encoder and optional original search."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from xmage_encoder_sources import stage
from xmage_jack_sources import stage as stage_jack
from xmage_magezero_sources import stage as stage_magezero
from xmage_magezero_search_sources import stage as stage_magezero_search
from xmage_search_sources import stage as stage_search
from xmage_verified_entry import verify_build
from xmage_release_assets import verify


def verify_model_engine(engine: Path, *, compile_only=False, private_inputs=False) -> str:
    engine_manifest = engine / "BUILD-MANIFEST.json"
    engine_manifest_sha = hashlib.sha256(engine_manifest.read_bytes()).hexdigest()
    if compile_only:
        identity = json.loads(engine_manifest.read_bytes())
        manifest = Path(__file__).resolve().parents[2] / "engines/xmage/releases.json"
        releases = json.loads(manifest.read_bytes())
        if (identity.get("xmage_commit") != releases["sources"]["xmage"]["revision"]
                or identity.get("cabt_commit") != releases["sources"]["cabt"]["revision"]
                or identity.get("patch_series") != "applied" or private_inputs):
            raise ValueError("CI compilation needs pinned public engine sources and no private inputs")
    elif engine_manifest_sha != "3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93":
        raise ValueError("encoder build needs the reviewed 004913a engine manifest")
    verify_build(engine, engine_manifest, engine_manifest_sha)
    return engine_manifest_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--search-inputs", type=Path, help="verified Exp1 search source input root")
    parser.add_argument("--magezero-inputs", type=Path, help="verified public MageZero v0.2 encoder input root")
    parser.add_argument("--magezero-search-inputs", type=Path, help="verified original MageZero v0.2 search source input root")
    parser.add_argument("--compile-only", action="store_true", help="CI compilation against a freshly pinned engine; cannot qualify play")
    parser.add_argument("--jack-inputs", type=Path, help="owned private Jack encoder input root")
    parser.add_argument("--jack-manifest", type=Path, help="private pinned Jack input manifest")
    args = parser.parse_args()
    if bool(args.jack_inputs) != bool(args.jack_manifest):
        raise ValueError("Jack build needs both its private inputs and manifest")
    if args.magezero_search_inputs and not args.magezero_inputs:
        raise ValueError("MageZero search requires its separately pinned original encoder")
    repo = Path(__file__).resolve().parents[2]
    manifest = repo / "engines/xmage/releases.json"
    engine = args.engine.resolve()
    # Qualification uses the reviewed build, not an arbitrary release bundle.
    engine_manifest_sha = verify_model_engine(engine, compile_only=args.compile_only,
                                             private_inputs=bool(args.jack_inputs))
    jdk = subprocess.run([args.javac, "-version"], check=True, capture_output=True, text=True)
    version = (jdk.stdout + jdk.stderr).strip()
    if version != "javac 23.0.1":
        raise ValueError("preserve the engine qualification's JDK 23.0.1 pin")
    if args.out.exists():
        raise ValueError("model build needs a new job directory")
    staged = stage(json.loads(manifest.read_text()), args.inputs, args.out / "sources")
    search = stage_search(json.loads(manifest.read_text()), args.search_inputs, args.out / "search-sources") if args.search_inputs else None
    magezero = stage_magezero(json.loads(manifest.read_text()), args.magezero_inputs,
                             args.out / "magezero-sources") if args.magezero_inputs else None
    magezero_search = stage_magezero_search(json.loads(manifest.read_text()), args.magezero_search_inputs,
                                           args.out / "magezero-search-sources") if args.magezero_search_inputs else None
    jack = stage_jack(json.loads(args.jack_manifest.read_bytes()), args.jack_inputs,
                      args.out / "jack-sources") if args.jack_inputs else None
    dependencies = []
    if search or magezero_search:
        search_assets = {a["id"]: a for a in json.loads(manifest.read_text())["assets"]}
        math_asset = search_assets["draftzero-exp1-search-commonsmath3"]
        dependency = (args.search_inputs or args.magezero_search_inputs) / math_asset["filename"]
        verify(dependency, math_asset)
        dependencies.append(dependency.resolve())
    paths = {k: args.out.resolve() / k for k in ("core", "kit", "model")}
    for directory in paths.values():
        directory.mkdir()
    common = [args.javac, "--release", "8", "-encoding", "UTF-8", "-nowarn", "-Xlint:-options"]
    source_sets = {"core": sorted((repo / "engines/xmage/kit/core/src").rglob("*.java")),
                   "kit": sorted((repo / "engines/xmage/kit/xmage/src").rglob("*.java")),
                   "model": sorted((repo / "engines/xmage/models/src").rglob("*.java"))
                            + sorted((args.out / "sources").rglob("*.java"))}
    if search:
        source_sets["model"] += sorted((args.out / "search-sources").rglob("*.java"))
    else:
        source_sets["model"] = [p for p in source_sets["model"] if "exp1" not in p.parts
                                and p.name not in ("ModelSearchMain.java", "ModelReplay.java", "ModelSearchCallbackCheck.java",
                                                   "ModelCombatMain.java", "ModelCombatCheck.java", "ModelBridgeMain.java",
                                                   "JackModeEncoder.java", "JackModeEncoderMain.java",
                                                   "JackDialogEncoder.java", "JackDialogEncoderMain.java", "JackDialogReplay.java", "JackInheritedChoices.java", "JackNamedChoices.java", "JackManaReplay.java", "JackManaReplayCheck.java",
                                                   "JackTargetEncoder.java", "JackTargetEncoderMain.java",
                                                   "JackGeneralTargetEncoder.java", "JackGeneralTargetEncoderMain.java",
                                                   "JackGeneralTargetNormalizationCheck.java",
                                                   "JackCardSetEncoder.java", "JackCardSetEncoderMain.java",
                                                   "JackParentCardEncoder.java", "JackParentCardEncoderMain.java", "JackCombatMain.java",
                                                   "JackLondonMain.java", "JackLondonPlan.java", "JackCombatPlan.java")]
    if jack:
        source_sets["model"] += sorted((args.out / "jack-sources").rglob("*.java"))
    if magezero:
        source_sets["model"] += sorted((args.out / "magezero-sources").rglob("*.java"))
    else:
        source_sets["model"] = [p for p in source_sets["model"] if not p.name.startswith("MageZero")]
    if magezero_search:
        source_sets["model"] += sorted((args.out / "magezero-search-sources").rglob("*.java"))
    else:
        source_sets["model"] = [p for p in source_sets["model"]
                                if not ("magezero" in p.parts and "search" in p.parts)
                                and not p.name.startswith("MageZeroSearch")]
    hashes = {}
    for name, sources in source_sets.items():
        cp = os.pathsep.join(str(p) for p in ([paths["core"]] if name == "kit" else
                            [paths["core"], paths["kit"]] if name == "model" else []) + [engine / "lib/*"] + dependencies)
        subprocess.run(common + ["-cp", cp, "-d", str(paths[name])] + [str(p) for p in sources], check=True)
        for path in sources:
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    resources = repo / "engines/xmage/kit/xmage/resources"
    shutil.copytree(resources, paths["kit"], dirs_exist_ok=True)
    resource_hashes = {}
    for source in sorted(p for p in resources.rglob("*") if p.is_file()):
        relative = source.relative_to(resources)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256((paths["kit"] / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("model build resource copy differs")
        resource_hashes[relative.as_posix()] = digest
    result = {"schema": "spellbench-draftzero-encoder-build/v1", "jdk": version,
              "engine_manifest_sha256": engine_manifest_sha,
              "inputs_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "source_sha256": hashes, "resource_files_sha256": resource_hashes, "encoder_stage": staged,
              "search_stage": search,
              "magezero_stage": magezero,
              "magezero_search_stage": magezero_search,
              "jack_stage": jack,
              "jack_inputs_manifest_sha256": hashlib.sha256(args.jack_manifest.read_bytes()).hexdigest() if jack else None,
              "dependency_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies},
              "class_files_sha256": {str(p.relative_to(args.out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for d in paths.values() for p in sorted(d.rglob("*.class"))},
              "scope": ("original priority, saved-anchor callbacks and combat plans; no complete agent or rating" if search else
                        "priority, target and binary decision slices; no complete bot, original search or rating")}
    if args.compile_only:
        result.update(schema="spellbench-draftzero-model-compile/v1", reviewed_runtime=False,
                      scope="compilation only; no runtime, checkpoint, game or rating qualification")
    with (args.out / "BUILD.json").open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({"out": str(args.out), "jdk": version, "compiled": list(source_sets)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
