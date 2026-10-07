"""Build the reviewed XMage kit, pinned encoder and optional original search."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from xmage_encoder_sources import stage
from xmage_maintainer_sources import stage as stage_maintainer
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


def reviewed_model_register(raw: bytes) -> bytes:
    """Correct one audited static-scan false positive in the model's copy.

    Brineborn's pinned constructor uses a constant P1P1 source counter and
    StaticValue(0), with no event target pointer. AddCountersSourceEffect's
    appliedEffects read is replacement-effect bookkeeping, not spellCast
    data. No event object or hidden information is needed to resolve this
    already public stack trigger. The native kit register stays unchanged.
    """
    register = json.loads(raw)
    row = register["cards"]["Brineborn Cutthroat"]
    expected = {
        "class": "mage.cards.b.BrinebornCutthroat",
        "reading_classes": ["AddCountersSourceEffect"],
        "status": "approximate",
        "trigger_classes": ["SpellCastControllerTriggeredAbility"],
        "triggers": "event_data",
        "why": ["triggers read event data or captured values"],
    }
    if row != expected:
        raise ValueError("Brineborn model trigger audit no longer matches the pinned register")
    row.update(status="supported", triggers="event_free",
               model_resolution_audit="constant P1P1 source counter; no event target or dynamic amount")
    del row["why"]
    return (json.dumps(register, indent=1, sort_keys=True) + "\n").encode()


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
    parser.add_argument("--maintainer-inputs", type=Path, help="owned private maintainer encoder input root")
    parser.add_argument("--maintainer-manifest", type=Path, help="private pinned maintainer input manifest")
    parser.add_argument("--current-overlay", action="store_true",
                        help="compile the current public observation/decision overlay into the pinned kit classpath")
    args = parser.parse_args()
    if bool(args.maintainer_inputs) != bool(args.maintainer_manifest):
        raise ValueError("the maintainer's build needs both its private inputs and manifest")
    if args.magezero_search_inputs and not args.magezero_inputs:
        raise ValueError("MageZero search requires its separately pinned original encoder")
    repo = Path(__file__).resolve().parents[2]
    manifest = repo / "engines/xmage/releases.json"
    engine = args.engine.resolve()
    # Qualification uses the reviewed build, not an arbitrary release bundle.
    engine_manifest_sha = verify_model_engine(engine, compile_only=args.compile_only,
                                             private_inputs=bool(args.maintainer_inputs))
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
    maintainer = stage_maintainer(json.loads(args.maintainer_manifest.read_bytes()), args.maintainer_inputs,
                      args.out / "maintainer-sources") if args.maintainer_inputs else None
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
    if args.current_overlay:
        source_sets["kit"] += sorted((repo / "engines/xmage/overlay/src/main/java").rglob("*.java"))
    else:
        # WorldBuilder uses this public-rule renderer. The reviewed engine
        # predates it, so default builds need the helper without replacing
        # the engine's observation/server classes or enabling their flags.
        source_sets["kit"].append(repo / "engines/xmage/overlay/src/main/java/mage/player/spellbench/observe/StackAbilityText.java")
    if search:
        source_sets["model"] += sorted((args.out / "search-sources").rglob("*.java"))
    else:
        source_sets["model"] = [p for p in source_sets["model"] if "exp1" not in p.parts
                                and p.name not in ("ModelSearchMain.java", "ModelReplay.java", "ModelSearchCallbackCheck.java",
                                                   "ModelCombatMain.java", "ModelCombatCheck.java", "ModelBridgeMain.java",
                                                   "MaintainerModeEncoder.java", "MaintainerModeEncoderMain.java",
                                                   "MaintainerDialogEncoder.java", "MaintainerDialogEncoderMain.java", "MaintainerDialogReplay.java", "MaintainerInheritedChoices.java", "MaintainerTriggerOrder.java", "MaintainerLibraryOrder.java", "MaintainerTargetAmount.java", "MaintainerNamedChoices.java", "MaintainerManaReplay.java", "MaintainerManaReplayCheck.java",
                                                   "MaintainerTargetEncoder.java", "MaintainerTargetEncoderMain.java",
                                                   "MaintainerGeneralTargetEncoder.java", "MaintainerGeneralTargetEncoderMain.java",
                                                   "MaintainerGeneralTargetNormalizationCheck.java",
                                                   "MaintainerCardSetEncoder.java", "MaintainerCardSetEncoderMain.java",
                                                   "MaintainerParentCardEncoder.java", "MaintainerParentCardEncoderMain.java", "MaintainerCombatMain.java",
                                                   "MaintainerLondonMain.java", "MaintainerLondonPlan.java", "MaintainerCombatPlan.java")]
    if maintainer:
        source_sets["model"] += sorted((args.out / "maintainer-sources").rglob("*.java"))
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
    resource_roots = [resources]
    if args.current_overlay:
        overlay_resources = repo / "engines/xmage/overlay/src/main/resources"
        # These classpath resources must travel with the newly compiled overlay.
        shutil.copytree(overlay_resources, paths["kit"], dirs_exist_ok=True)
        resource_roots.append(overlay_resources)
    resource_hashes = {}
    for directory in resource_roots:
        for source in sorted(p for p in directory.rglob("*") if p.is_file()):
            relative = source.relative_to(directory)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256((paths["kit"] / relative).read_bytes()).hexdigest() != digest:
                raise ValueError("model build resource copy differs")
            resource_hashes[relative.as_posix()] = digest
    register_name = "spellbench/kit/xmage/register.json"
    model_register = paths["kit"] / register_name
    register_input_sha256 = hashlib.sha256(model_register.read_bytes()).hexdigest()
    model_register.write_bytes(reviewed_model_register(model_register.read_bytes()))
    resource_hashes[register_name] = hashlib.sha256(model_register.read_bytes()).hexdigest()
    result = {"schema": "spellbench-draftzero-encoder-build/v1", "jdk": version,
              "engine_manifest_sha256": engine_manifest_sha,
              "inputs_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "source_sha256": hashes, "resource_files_sha256": resource_hashes, "encoder_stage": staged,
              "model_register_input_sha256": register_input_sha256,
              "reviewed_model_stack_triggers": ["Brineborn Cutthroat"],
              "search_stage": search,
              "magezero_stage": magezero,
              "magezero_search_stage": magezero_search,
              "maintainer_stage": maintainer,
              "maintainer_inputs_manifest_sha256": hashlib.sha256(args.maintainer_manifest.read_bytes()).hexdigest() if maintainer else None,
              "current_overlay_compiled": args.current_overlay,
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
