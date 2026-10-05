"""Run a supported native qualification or rated benchmark in an owned job.

The job manifest supplies a frozen runtime, individually pinned inputs, storage
budget and window. The existing trusted host helper is supplied by hash; it is
not a checkpoint or a downloaded community Python module. No paid compute is
created. Qualification uses kitrun.py qualify or the benchmark's plan_for
guard. Rated execution requires the pinned committed-benchmark entrypoint,
which retains the benchmark runner's throughput, commitment and result checks.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def put(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def tree_bytes(root: Path) -> int:
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        here = Path(directory)
        dirs[:] = [d for d in dirs if not (here/d).is_symlink() and not (here/d).is_junction()]
        total += sum((here/f).stat().st_size for f in files if not (here/f).is_symlink())
    return total


def storage(record: dict) -> int:
    roots = [Path(record[k]) for k in ("hot_root", "cold_root")]
    actual = sum(tree_bytes(root) for root in roots)
    projected = max(actual, record.get("projected_peak_physical_bytes", actual))
    if projected > record["storage_cap_bytes"]:
        raise RuntimeError("native job exceeded its declared aggregate storage cap")
    growth = projected - actual
    if any(shutil.disk_usage(root.anchor).free - growth < record["reserve_bytes"] for root in roots):
        raise RuntimeError("native job volume crossed the declared reserve")
    return actual


def progress_counts(prepared: dict, output: Path) -> dict[Path, int]:
    if prepared.get("execution_kind") == "rated_benchmark":
        progress = output / "matches.jsonl"
        paths = (progress,) if progress.exists() else ()
    elif prepared.get("qualification_kind") == "benchmark":
        directory = Path(prepared["benchmark"]["path"]).parent / ".qualification-records"
        paths = directory.glob("qualification-*/trial-*.jsonl")
    else:
        progress = output / "completed-games.jsonl"
        paths = (progress,) if progress.exists() else ()
    counts = {}
    for path in paths:
        with path.open("rb") as stream:
            counts[path] = sum(1 for _ in stream)
    return counts


def execution_kind(record: dict, prepared: dict) -> str:
    kind = record.get("execution_kind", "qualification")
    if kind not in ("qualification", "rated_benchmark"):
        raise ValueError("unknown native job execution kind")
    if prepared.get("execution_kind", "qualification") != kind:
        raise ValueError("native preparation and job execution kinds differ")
    if kind == "qualification" and record.get("qualification_only", True) is not True:
        raise ValueError("a qualification job must retain its qualification-only scope")
    if kind == "rated_benchmark":
        if record.get("qualification_only") is not False:
            raise ValueError("a rated benchmark cannot be labelled qualification-only")
        if prepared.get("qualification_kind") != "benchmark":
            raise ValueError("rated execution requires a pinned benchmark")
        entry = prepared.get("execution_entrypoint", {})
        path = Path(entry.get("path", ""))
        if (path.name != "xmage_native_benchmark_rated.py"
                or not path.resolve().is_relative_to(Path(record["hot_root"]).resolve())
                or not path.is_file() or sha(path) != entry.get("sha256")):
            raise ValueError("rated benchmark entrypoint differs from its owned pin")
        command = prepared.get("command", [])
        if len(command) < 2 or Path(command[1]).resolve() != path.resolve():
            raise ValueError("rated job does not launch its pinned benchmark entrypoint")
        if Path(command[0]).resolve() != Path(record["launcher_python"]["path"]).resolve():
            raise ValueError("rated job does not use its pinned base Python interpreter")
    return kind


def completed_since(prepared: dict, output: Path, baseline: dict[Path, int]) -> int:
    return sum(max(0, count - baseline.get(path, 0))
               for path, count in progress_counts(prepared, output).items())


def load(manifest: Path, digest: str):
    if sha(manifest) != digest:
        raise ValueError("native job manifest differs")
    record = json.loads(manifest.read_bytes())
    if record["schema"] != "spellbench-native-qualified-job/v1" or os.name != "nt":
        raise ValueError("this native reservation launcher requires its Windows job manifest")
    if os.environ.get("MTG_HOST_RESERVATION_TEST_ROOT"):
        raise ValueError("production qualification cannot use a test reservation root")
    if sha(Path(__file__)) != record["launcher_sha256"]:
        raise ValueError("native launcher source differs")
    launcher_python = record["launcher_python"]
    if sha(Path(launcher_python["path"])) != launcher_python["sha256"]:
        raise ValueError("base Python interpreter differs")
    preparation = Path(record["preparation"])
    if sha(preparation) != record["preparation_sha256"]:
        raise ValueError("frozen runtime preparation differs")
    prepared = json.loads(preparation.read_bytes())
    execution_kind(record, prepared)
    helper = Path(record["reservation_helper"])
    if helper.name != "host_reservation_v1.py" or sha(helper) != record["reservation_helper_sha256"]:
        raise ValueError("trusted reservation helper differs")
    module_spec = importlib.util.spec_from_file_location("native_host_reservation", helper)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if module.CANONICAL_ROOT != "C:/mtg-node/host-lock" or module.SCHEMA != "mtg-host-reservation/v1":
        raise ValueError("host helper does not use the canonical reservation")
    for item in (prepared["database"], *prepared["engine_jars"].values(), *prepared["kit_jars"].values()):
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("native pinned input differs")
    if sha(Path(prepared["toolchain"]["java"])) != prepared["toolchain"]["java_pin"]["sha256"]:
        raise ValueError("pinned Java executable differs")
    schedule_input = prepared["benchmark"] if prepared.get("qualification_kind") == "benchmark" else prepared["plan"]
    if sha(Path(schedule_input["path"])) != schedule_input["sha256"]:
        raise ValueError("frozen native schedule differs")
    storage(record)
    return record, prepared, module


def work(record: dict, prepared: dict, helper) -> int:
    token = os.environ.get(helper.TOKEN_ENV)
    status = helper.status(token)
    if (not token or status.get("token_fate") != "holds"
            or status.get("record", {}).get("lane") != "spellbench-xmage-native"
            or status.get("record", {}).get("work_id") != record["work_id"]):
        raise ValueError("native qualification requires this supervisor's active host claim")
    members = helper.job_members(None)
    supervisors = [event for event in status["events"] if event["kind"] == "adopt"
                   and event.get("contained") is True and event.get("nested") is False
                   and event["pid"] in members
                   and helper.creation_time(event["pid"]) == event["creation_time"]]
    if len(supervisors) != 1 or os.getpid() not in members:
        raise ValueError("native qualifier is outside its owned supervisor job")
    supervisor = supervisors[0]["pid"]
    parents = {pid: parent for pid, parent, _ in helper.process_table()}
    protected = {supervisor, os.getpid()}
    ancestor = os.getpid()
    for _ in range(64):
        if ancestor == supervisor:
            break
        ancestor = parents.get(ancestor)
        if ancestor not in members:
            raise ValueError("native controller is not the owned supervisor's descendant")
        protected.add(ancestor)
    else:
        raise ValueError("native controller ancestry is cyclic or too deep")
    hot = Path(record["hot_root"])
    attempt = Path(record["attempt_root"])
    env = dict(os.environ)
    env.update({k: v for k, v in prepared["environment"].items() if k != "PATH_PREFIX"})
    env["PATH"] = prepared["environment"]["PATH_PREFIX"] + os.pathsep + env["PATH"]
    qualifier_output = Path(prepared["command"][prepared["command"].index("--out") + 1])
    start = time.monotonic()
    kind = execution_kind(record, prepared)
    scope = ("rated benchmark execution; completion and ratings require a validated published result"
             if kind == "rated_benchmark" else "completed-game throughput qualification; no rated games")
    terminal = {"schema": "spellbench-native-job-terminal/v1", "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "source_revision": prepared["source_revision"], "manifest_sha256": record["manifest_sha256"],
                "execution_kind": kind, "scope": scope, "exit_code": 2}
    child = None
    try:
        with (attempt/"QUALIFY.log").open("xb") as log, (attempt/"MONITOR.jsonl").open("x", encoding="utf-8") as monitor:
            baseline = progress_counts(prepared, qualifier_output)
            child = subprocess.Popen(prepared["command"], cwd=hot, env=env, stdout=log, stderr=subprocess.STDOUT)
            terminal["child_pid"] = child.pid
            while child.poll() is None:
                if (hot/"STOP").exists():
                    raise RuntimeError("native job STOP file")
                if time.monotonic()-start > record["window_seconds"]:
                    raise RuntimeError("native job window expired")
                used = storage(record)
                completed = completed_since(prepared, qualifier_output, baseline)
                monitor.write(json.dumps({"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "elapsed_s": round(time.monotonic()-start, 3), "completed_game_rows": completed,
                    "aggregate_bytes": used, "owned_processes": helper.job_members(None)})+"\n")
                monitor.flush()
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
            terminal["exit_code"] = child.returncode
    except BaseException as exc:
        terminal["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        # The queried job is exactly this reservation's containment. Retain the
        # supervisor and this controller; terminate only their owned children
        # by both PID and creation time on a failure or surviving child.
        grace = time.monotonic()+2
        owned = [p for p in helper.job_members(None) if p not in protected]
        while owned and time.monotonic() < grace:
            time.sleep(0.1)
            owned = [p for p in helper.job_members(None) if p not in protected]
        terminal["forced_owned_children"] = owned
        if owned and terminal["exit_code"] == 0:
            terminal["exit_code"] = 2
        identities = [(pid, helper.creation_time(pid)) for pid in owned]
        for pid, creation in identities:
            if creation is not None:
                helper.terminate(pid, creation)
        until = time.monotonic()+10
        while any(helper.process_state(pid, creation) != "absent" for pid, creation in identities) and time.monotonic() < until:
            time.sleep(0.1)
        remaining = [pid for pid, creation in identities if helper.process_state(pid, creation) != "absent"]
        terminal.update(elapsed_s=round(time.monotonic()-start, 3), owned_children_remaining=remaining,
                        owned_child_cleanup_confirmed=not remaining)
        if remaining:
            terminal["exit_code"] = 2
        put(attempt/"TERMINAL.json", terminal)
    return terminal["exit_code"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dispatch", "work"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    record, prepared, helper = load(args.manifest, args.manifest_sha256)
    record["manifest_sha256"] = args.manifest_sha256
    if args.mode == "work":
        try:
            return work(record, prepared, helper)
        except BaseException as exc:
            put(Path(record["attempt_root"])/"STARTUP-ERROR.json", {"error": f"{type(exc).__name__}: {exc}",
                "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "qualifier_started": False})
            raise
    base_python = Path(record["launcher_python"]["path"])
    # Windows venv redirectors create a parent that waits for the actual
    # interpreter. It must never be mistaken for the contained supervisor.
    if Path(sys.executable).resolve() != base_python.resolve():
        return subprocess.run([str(base_python), str(Path(__file__).resolve()), "--mode", "dispatch",
            "--manifest", str(args.manifest.resolve()), "--manifest-sha256", args.manifest_sha256], check=False).returncode
    if os.environ.get(helper.TOKEN_ENV):
        raise ValueError("native qualification cannot borrow another task's claim")
    if helper.status()["state"] != "free":
        raise ValueError("canonical host is not free")
    hot = Path(record["hot_root"])
    attempt = Path(record["attempt_root"])
    if (attempt/"DISPATCH.json").exists() or (attempt/"QUALIFY.log").exists():
        raise ValueError("this prepared job was already dispatched; inspect its actual status before any recovery")
    command = [sys.executable, str(Path(__file__).resolve()), "--mode", "work", "--manifest", str(args.manifest.resolve()),
               "--manifest-sha256", args.manifest_sha256]
    result = helper.dispatch("spellbench-xmage-native", record["work_id"],
        "supported qualifier exit, declared window/cap/STOP and confirmed owned child cleanup", command, str(hot),
        busy_pattern=r"^(?:java|bo3_.*|native_.*|mtg_kernel.*)\.exe$",
        transport_record={"manifest": str(args.manifest.resolve()), "manifest_sha256": args.manifest_sha256})
    put(attempt/"DISPATCH.json", result)
    print(json.dumps({k: result.get(k) for k in ("state", "generation", "pid", "nested")}))
    return 0 if result["state"] in ("dispatched", "finished-before-handoff") else 2


if __name__ == "__main__":
    raise SystemExit(main())
