"""Run the supported native qualifier under an owned Windows host reservation.

The job manifest supplies a frozen runtime, individually pinned inputs, storage
budget and window. The existing trusted host helper is supplied by hash; it is
not a checkpoint or a downloaded community Python module. No paid compute is
created. The child command remains kitrun.py qualify, with its scaling guard.
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
    if actual > record["storage_cap_bytes"]:
        raise RuntimeError("native job exceeded its declared aggregate storage cap")
    if any(shutil.disk_usage(root.anchor).free < record["reserve_bytes"] for root in roots):
        raise RuntimeError("native job volume crossed the declared reserve")
    return actual


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
    preparation = Path(record["preparation"])
    if sha(preparation) != record["preparation_sha256"]:
        raise ValueError("frozen runtime preparation differs")
    prepared = json.loads(preparation.read_bytes())
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
    if sha(Path(prepared["plan"]["path"])) != prepared["plan"]["sha256"]:
        raise ValueError("frozen native plan differs")
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
    if os.getpid() not in members or os.getppid() not in members:
        raise ValueError("native qualifier is outside its owned supervisor job")
    hot = Path(record["hot_root"])
    env = dict(os.environ)
    env.update({k: v for k, v in prepared["environment"].items() if k != "PATH_PREFIX"})
    env["PATH"] = prepared["environment"]["PATH_PREFIX"] + os.pathsep + env["PATH"]
    start = time.monotonic()
    terminal = {"schema": "spellbench-native-job-terminal/v1", "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "source_revision": prepared["source_revision"], "manifest_sha256": record["manifest_sha256"],
                "scope": "completed-game throughput qualification; no rated games", "exit_code": 2}
    child = None
    try:
        with (hot/"QUALIFY.log").open("xb") as log, (hot/"MONITOR.jsonl").open("x", encoding="utf-8") as monitor:
            child = subprocess.Popen(prepared["command"], cwd=hot, env=env, stdout=log, stderr=subprocess.STDOUT)
            terminal["child_pid"] = child.pid
            while child.poll() is None:
                if (hot/"STOP").exists():
                    raise RuntimeError("native job STOP file")
                if time.monotonic()-start > record["window_seconds"]:
                    raise RuntimeError("native qualification window expired")
                used = storage(record)
                progress = hot/"qualification/completed-games.jsonl"
                completed = sum(1 for _ in progress.open("rb")) if progress.exists() else 0
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
        owned = [p for p in helper.job_members(None) if p not in (os.getpid(), os.getppid())]
        while owned and time.monotonic() < grace:
            time.sleep(0.1)
            owned = [p for p in helper.job_members(None) if p not in (os.getpid(), os.getppid())]
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
        put(hot/"TERMINAL.json", terminal)
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
        return work(record, prepared, helper)
    if os.environ.get(helper.TOKEN_ENV):
        raise ValueError("native qualification cannot borrow another task's claim")
    if helper.status()["state"] != "free":
        raise ValueError("canonical host is not free")
    hot = Path(record["hot_root"])
    if (hot/"DISPATCH.json").exists() or (hot/"QUALIFY.log").exists():
        raise ValueError("this prepared job was already dispatched; inspect its actual status before any recovery")
    command = [sys.executable, str(Path(__file__).resolve()), "--mode", "work", "--manifest", str(args.manifest.resolve()),
               "--manifest-sha256", args.manifest_sha256]
    result = helper.dispatch("spellbench-xmage-native", record["work_id"],
        "supported qualifier exit, declared window/cap/STOP and confirmed owned child cleanup", command, str(hot),
        busy_pattern=r"^(?:java|bo3_.*|native_.*|mtg_kernel.*)\.exe$",
        transport_record={"manifest": str(args.manifest.resolve()), "manifest_sha256": args.manifest_sha256})
    put(hot/"DISPATCH.json", result)
    print(json.dumps({k: result.get(k) for k in ("state", "generation", "pid", "nested")}))
    return 0 if result["state"] in ("dispatched", "finished-before-handoff") else 2


if __name__ == "__main__":
    raise SystemExit(main())
