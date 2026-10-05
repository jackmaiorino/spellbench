"""Build production binaries on a standard CI runner; execute no games."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.request

GORGE_PIN = "26257e0eda1779d739a07e835c6500b9c4dabc62"
FORGE_PIN = "95f04e8a04c8925fa97cb226fc3341cabcc90a53"
SDK_SHA = "63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445"
SDK_SIZE = 70553950
SDK_URL = "https://go.dev/dl/go1.27.1.linux-amd64.tar.gz"
FINGERPRINT = "4e081d8104fbe09256edb9fa696ce6f7"
REGISTRY_SHA = "42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    job = args.job.resolve()
    repo = Path(__file__).resolve().parents[1]
    module = repo / "engines/gorge"
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("GITHUB_REPOSITORY") == "jackmaiorino/spellbench"
    assert not job.exists(), "Use a fresh owned job root"
    job.mkdir(parents=True)
    output = job / "runtime"
    output.mkdir()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert source == os.environ["GITHUB_SHA"]
    manifest = dict(
        schema="spellbench-gorge-runtime-preparation/v1",
        at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        adapter_commit=source, source_commit=source,
        gorge_commit=GORGE_PIN, forge_commit=FORGE_PIN,
        github_run_id=os.environ["GITHUB_RUN_ID"],
        github_run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
        build_host="standard GitHub-hosted ubuntu-24.04 public-repository runner",
        GOMAXPROCS=2, GOMEMLIMIT="2GiB", CGO_ENABLED=0,
        projected_bytes=2 * 2**30, cap_bytes=4 * 2**30,
        output_cap_bytes=256 * 2**20, reserve_bytes=60 * 2**30,
        wall_cap_seconds=1200, artifact_retention_days=1,
        registry_reuse=dict(sha256=REGISTRY_SHA,
            reason="Compose with independently verified existing registry after recovery; no registry is uploaded"),
        files=[], build_commands=[], phase="prepared", runtime_build_passed=False,
        registry_present=False, throughput_qualified=False, isolation_verified=False,
        native_qualification_complete=False, reference_qualification_complete=False,
        rated_games=0, published_entries=0,
    )
    write(output / "BUILD.json", manifest)
    started = time.monotonic()

    def guard() -> None:
        if time.monotonic() - started > manifest["wall_cap_seconds"]:
            raise TimeoutError("Production build wall cap")
        if shutil.disk_usage(job).free < manifest["reserve_bytes"]:
            raise RuntimeError("Target storage below mandatory60GiB reserve")
        if sum(p.stat().st_size for p in job.rglob("*") if p.is_file()) > manifest["cap_bytes"]:
            raise RuntimeError("Build scratch byte cap")
        if sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) > manifest["output_cap_bytes"]:
            raise RuntimeError("Upload byte cap")

    def run(name: str, command: list[str], env: dict, cwd: Path, timeout: int = 180) -> None:
        guard()
        begin = time.monotonic()
        write(output / (name + "-COMMAND.json"), dict(command=command, cwd=str(cwd), timeout=timeout))
        with (output / (name + ".stdout")).open("wb") as stdout, (output / (name + ".stderr")).open("wb") as stderr:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                while process.poll() is None:
                    guard()
                    if time.monotonic() - begin > timeout:
                        raise TimeoutError(name)
                    time.sleep(2)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
        write(output / (name + "-RECEIPT.json"), dict(exit_code=process.returncode, elapsed_seconds=time.monotonic() - begin))
        if process.returncode:
            raise RuntimeError(name + " exit " + str(process.returncode))

    try:
        guard()
        archive = job / "go-sdk.tar.gz"
        with urllib.request.urlopen(SDK_URL, timeout=30) as response, archive.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        assert archive.stat().st_size == SDK_SIZE and sha(archive) == SDK_SHA
        with tarfile.open(archive) as handle:
            handle.extractall(job, filter="data")
        go = job / "go/bin/go"
        upstream = job / "upstream"
        env = dict(os.environ, GOTOOLCHAIN="local", CGO_ENABLED="0", GOMAXPROCS="2",
                   GOMEMLIMIT="2GiB", GORGE_SRC=str(upstream), GOCACHE=str(job / "go-cache"),
                   GOMODCACHE=str(job / "go-mod-cache"))
        run("git-init", ["git", "init", str(upstream)], env, job)
        run("git-crlf", ["git", "config", "core.autocrlf", "true"], env, upstream)
        run("git-remote", ["git", "remote", "add", "origin", "https://github.com/adams-shaun/gorge.git"], env, upstream)
        run("git-fetch", ["git", "fetch", "--depth", "1", "origin", GORGE_PIN], env, upstream)
        run("git-checkout", ["git", "checkout", "--detach", "FETCH_HEAD"], env, upstream)
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip() == GORGE_PIN
        fingerprint = hashlib.sha256()
        for path in sorted((upstream / "cards").glob("*.go")):
            if not path.name.endswith("_test.go"):
                fingerprint.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        assert fingerprint.hexdigest()[:32] == FINGERPRINT
        run("setup", ["python3", str(module / "scripts/setup-dev.py")], env, module)
        env["GOFLAGS"] = "-overlay=" + str(module / "go-overlay.json")
        run("linked-compiler", [str(go), "test", "-p", "2", "-count=1", "-timeout=2m",
                               "-run", "^TestLinkedGorgeIsThePinnedCompiler$", "./internal/gorgepin"], env, module)
        manifest.update(
            go_version=subprocess.check_output([str(go), "version"], text=True).strip(),
            go_driver_sha256=sha(go), compiler_sha256=sha(job / "go/pkg/tool/linux_amd64/compile"),
            linker_sha256=sha(job / "go/pkg/tool/linux_amd64/link"), linux_sdk_sha256=SDK_SHA,
            source_fingerprint_passed=True, linked_compiler_test_passed=True,
            production_overlay_sha256=sha(module / "native-overlay/public_redeal.go.txt"),
            overlay_files={p.relative_to(module).as_posix(): sha(p) for p in sorted((module / "native-overlay").glob("*")) if p.is_file()},
            runtime_stage="production", phase="building",
        )
        for platform, commands in (
            ("windows", ["spellbench-gorge-corpus", "spellbench-gorge-env", "spellbench-gorge-agent", "gorgequal"]),
            ("linux", ["spellbench-gorge-env", "spellbench-gorge-agent", "gorgequal"]),
        ):
            for command in commands:
                name = f"{command}-{platform}-amd64" + (".exe" if platform == "windows" else "")
                target = output / name
                build = [str(go), "build", "-p", "2", "-trimpath", "-buildvcs=false", "-o", str(target), "./cmd/" + command]
                manifest["build_commands"].append(build)
                run("build-" + name, build, dict(env, GOOS=platform, GOARCH="amd64"), module, timeout=300)
                manifest["files"].append(dict(name=name, sha256=sha(target), bytes=target.stat().st_size, platform=platform, kind="binary"))
                write(output / "BUILD.json", manifest)
        guard()
        assert len(manifest["files"]) == 7
        manifest.update(phase="built_awaiting_independent_recovery", runtime_build_passed=True)
    except Exception as error:
        manifest.update(phase="build_failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        write(output / "BUILD.json", manifest)
        write(output / "CLOSURE.json", dict(phase=manifest["phase"], runtime_build_passed=manifest["runtime_build_passed"],
            elapsed_seconds=time.monotonic() - started, native_qualification_complete=False, rated_games=0))


if __name__ == "__main__":
    main()
