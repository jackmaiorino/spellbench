"""Reject compile-only, changed, injected and unpinned model runtime inputs."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_runtime as runtime


def fixture(tmp_path):
    build, engine = tmp_path / "build", tmp_path / "engine"
    (build / "model").mkdir(parents=True)
    (build / "kit").mkdir()
    (build / "core").mkdir()
    (build / "model/Main.class").write_bytes(b"compiled")
    (build / "kit/resource.txt").write_bytes(b"resource")
    release = tmp_path / "releases.json"
    release.write_bytes(b'{"public":true}')
    dependency = tmp_path / "commons-math.jar"
    dependency.write_bytes(b"dependency")
    metadata = {"schema": "spellbench-draftzero-encoder-build/v1", "jdk": "javac 23.0.1",
                "inputs_manifest_sha256": runtime.sha(release), "engine_manifest_sha256": runtime.REVIEWED_ENGINE,
                "search_stage": {"pinned": True},
                "class_files_sha256": {"model/Main.class": runtime.sha(build / "model/Main.class")},
                "resource_files_sha256": {"resource.txt": runtime.sha(build / "kit/resource.txt")},
                "dependency_sha256": {str(dependency): runtime.sha(dependency)}}
    return build, engine, release, metadata


@pytest.mark.parametrize("fault", [None, "windows-paths", "manifest", "class", "injected-class", "injected-resource", "resource", "dependency",
                                  "compile-only", "engine-pin", "source-pin", "escape", "windows-escape"])
def test_verified_runtime_checks_complete_model_tree_and_reviewed_engine_before_launch(tmp_path, monkeypatch, fault):
    build, engine, release, metadata = fixture(tmp_path)
    if fault == "windows-paths":
        metadata["class_files_sha256"] = {name.replace("/", "\\"): digest
                                          for name, digest in metadata["class_files_sha256"].items()}
    elif fault == "compile-only":
        metadata["schema"] = "spellbench-draftzero-model-compile/v1"
    elif fault == "engine-pin":
        metadata["engine_manifest_sha256"] = "0" * 64
    elif fault == "source-pin":
        metadata["inputs_manifest_sha256"] = "0" * 64
    elif fault in ("escape", "windows-escape"):
        metadata["resource_files_sha256"] = {"../foreign" if fault == "escape" else "C:/foreign": "0" * 64}
    manifest = build / "BUILD.json"
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    digest = runtime.sha(manifest)
    if fault == "manifest":
        manifest.write_bytes(b"changed")
    elif fault == "class":
        (build / "model/Main.class").write_bytes(b"changed")
    elif fault == "injected-class":
        (build / "core/Injected.class").write_bytes(b"injected")
    elif fault == "injected-resource":
        (build / "kit/undeclared-resource.txt").write_bytes(b"injected")
    elif fault == "resource":
        (build / "kit/resource.txt").write_bytes(b"changed")
    elif fault == "dependency":
        Path(next(iter(metadata["dependency_sha256"]))).write_bytes(b"changed")
    calls = []
    monkeypatch.setattr(runtime, "verify_build", lambda *args: calls.append(args))
    if fault in (None, "windows-paths"):
        assert runtime.verify_model_build(build, digest, engine, release) == metadata
        assert calls == [(engine, engine / "BUILD-MANIFEST.json", runtime.REVIEWED_ENGINE)]
    else:
        with pytest.raises(ValueError):
            runtime.verify_model_build(build, digest, engine, release)


def test_public_identity_changes_with_checkpoint_visits_build_and_confined_image():
    manifest = {"inference_backends": {"draftzero-exp1": {"checkpoints": ["gen0", "gen10", "gen33"]}},
                "assets": [{"id": name, "sha256": str(i) * 64} for i, name in enumerate(("gen0", "gen10", "gen33"))]}
    params = {"checkpoint": "gen33", "visits": 1000, "build_sha256": "a" * 64, "image": "sha256:" + "b" * 64,
              "manifest": manifest}
    original = runtime.identity(**params)
    assert original == runtime.identity(**params)
    for key, value in (("checkpoint", "gen0"), ("checkpoint", "gen10"), ("visits", 6),
                       ("build_sha256", "c" * 64), ("image", "sha256:" + "d" * 64)):
        assert runtime.identity(**{**params, key: value})["version"] != original["version"]
    with pytest.raises(ValueError):
        runtime.identity(**{**params, "checkpoint": "invented"})
    assert original["identity"]["profile"]["full_game_qualified"] is False
    assert len(original["identity"]["source_sha256"]) == 8


@pytest.mark.parametrize("fault", [None, "close", "container", "receipt", "primary-error"])
def test_cleanup_attempts_every_owned_container_after_shutdown_failure(tmp_path, monkeypatch, fault):
    work = tmp_path / "work"
    directory, sibling = work / "exp1-agent-owned", work / "sibling"
    directory.mkdir(parents=True)
    sibling.mkdir()
    (directory / "db.bin").write_bytes(b"keep for failure inspection")
    (sibling / "keep.bin").write_bytes(b"foreign work")
    previous = Path.cwd()
    monkeypatch.chdir(directory)
    names = ["spellbench-xmage-" + digit * 32 for digit in ("1", "2")]
    cleanup_calls = []
    failure = ValueError("original serving failure") if fault == "primary-error" else None

    class Agent:
        closed = False

        def close(self):
            self.closed = True
            if fault in ("close", "primary-error"):
                raise RuntimeError("agent shutdown failed")

    agent = Agent()

    def cleanup(name):
        cleanup_calls.append(name)
        return {"confirmed_absent": not (fault == "container" and name == names[0])}

    monkeypatch.setattr(runtime, "cleanup_container", cleanup)
    if fault == "receipt":
        (work / (names[0] + ".cleanup.json")).write_bytes(b"existing receipt")
    if fault in ("close", "container", "receipt"):
        with pytest.raises((RuntimeError, FileExistsError)):
            runtime.close_owned_runtime(agent, previous, work, directory, names)
    else:
        runtime.close_owned_runtime(agent, previous, work, directory, names, failure=failure)
    assert agent.closed and Path.cwd() == previous
    assert cleanup_calls == names
    assert json.loads((work / (names[1] + ".cleanup.json")).read_bytes())["confirmed_absent"] is True
    assert sibling.is_dir() and (sibling / "keep.bin").read_bytes() == b"foreign work"
    assert directory.exists() is (fault is not None)
    if failure is not None:
        assert failure.args == ("original serving failure",)
        assert "agent shutdown failed" in failure.__notes__[0]
