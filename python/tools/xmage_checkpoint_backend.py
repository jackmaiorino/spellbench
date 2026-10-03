"""Launch pinned XMage model inference inside a network-disabled container.

Probe verifies loading and repeated inference, without playing a game. Serve
accepts encoded-feature requests on stdin for the separate fair game adapter.
It never loads checkpoints or imports community model code on the host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from xmage_release_assets import prepare_root, validate_asset, verify


def cleanup_container(name: str) -> dict:
    """Remove this launcher's container, retaining a Docker failure as evidence."""
    try:
        proc = subprocess.run(["docker", "rm", "--force", name], capture_output=True, text=True, timeout=15)
        removed = proc.returncode == 0 or "No such container" in proc.stderr
        return {"confirmed_absent": removed, "exit_code": proc.returncode, "stderr": proc.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"confirmed_absent": False, "error": str(exc)}


def pinned_command(manifest: dict, root: Path, checkpoint_id: str, image: str, mode: str,
                   container_name: str | None = None) -> list[str]:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("model image must be an immutable local image SHA-256, not a tag")
    if mode not in ("probe", "serve"):
        raise ValueError("unsupported checkpoint backend mode")
    root = prepare_root(root)
    candidates = [(name, config) for name, config in manifest["inference_backends"].items()
                  if checkpoint_id in config["checkpoints"]]
    if len(candidates) != 1:
        raise ValueError("checkpoint has no pinned inference backend")
    architecture, config = candidates[0]
    if architecture not in ("draftzero-exp1", "magezero-v02"):
        raise ValueError("unsupported checkpoint architecture")
    assets = {a["id"]: a for a in manifest["assets"]}
    if len(assets) != len(manifest["assets"]):
        raise ValueError("duplicate release input id")
    checkpoint = assets[checkpoint_id]
    checkpoint_format = checkpoint.get("checkpoint_format", "torch-gzip")
    if checkpoint_format not in ("torch", "torch-gzip", "magezero-mz"):
        raise ValueError("unsupported checkpoint format")
    expected_export = checkpoint.get("export_metadata")
    if architecture == "magezero-v02":
        if (not isinstance(checkpoint.get("deck_id"), str)
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", checkpoint["deck_id"])
                or not isinstance(checkpoint.get("deck_association_evidence"), str)
                or not checkpoint["deck_association_evidence"].strip()):
            raise ValueError("MageZero checkpoint needs its deck association and evidence")
    if checkpoint_format == "magezero-mz":
        if architecture != "magezero-v02":
            raise ValueError("MageZero exports require the MageZero architecture")
        if (not isinstance(expected_export, dict) or set(expected_export) != {"deck", "version"}
                or not isinstance(expected_export["deck"], str) or not expected_export["deck"].strip()
                or len(expected_export["deck"]) > 128
                or type(expected_export["version"]) is not int or expected_export["version"] < 0):
            raise ValueError("MageZero export needs a pinned deck name and version")
    elif expected_export is not None:
        raise ValueError("export metadata requires a MageZero .mz bundle")
    checkpoint_path = "/inputs/checkpoint." + {"torch": "pt", "torch-gzip": "pt.gz", "magezero-mz": "mz"}[checkpoint_format]
    mounts = {checkpoint_id: checkpoint_path, config["model"]: "/inputs/source/model.py",
              config["feature_vocab_code"]: "/inputs/source/vocab.py"}
    if architecture == "draftzero-exp1":
        mounts[config["action_vocab"]] = "/inputs/actions.tsv"
    argv = ["docker", "run", "--rm", "--interactive", "--network", "none", "--read-only",
            "--cpus", "1", "--memory", "3g", "--memory-swap", "3g", "--pids-limit", "64",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"]
    if container_name:
        if not re.fullmatch(r"spellbench-xmage-[a-f0-9]{32}", container_name):
            raise ValueError("invalid owned container name")
        argv.extend(["--name", container_name])
    for aid, destination in mounts.items():
        asset = assets[aid]
        validate_asset(asset)
        path = root / asset["filename"]
        verify(path, asset)
        if any(x in str(path) for x in (",", "\n", "\r")):
            raise ValueError("input path cannot be expressed as one read-only Docker mount")
        argv.extend(["--mount", f"type=bind,src={path},dst={destination},readonly"])
    argv.extend([image, mode, "--checkpoint", checkpoint_path, "--checkpoint-sha256",
                 assets[checkpoint_id]["sha256"], "--source", "/inputs/source", "--model-sha256",
                 assets[config["model"]]["sha256"], "--vocab-sha256",
                 assets[config["feature_vocab_code"]]["sha256"], "--architecture", architecture,
                 "--checkpoint-format", checkpoint_format])
    if expected_export is not None:
        argv.extend(["--export-deck", expected_export["deck"], "--export-version", str(expected_export["version"])])
    if architecture == "draftzero-exp1":
        argv.extend(["--actions", "/inputs/actions.tsv", "--actions-sha256", assets[config["action_vocab"]]["sha256"]])
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "serve"))
    parser.add_argument("--manifest", type=Path, default=Path("engines/xmage/releases.json"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True, help="docker image inspect --format '{{.Id}}' IMAGE")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.mode == "probe" and args.report is None:
        raise ValueError("checkpoint probes require a saved report")
    if args.mode == "serve" and args.report is not None:
        raise ValueError("serve reports readiness and results on stdout")
    # Reserve this receipt before Docker starts. A failure preserves diagnostics
    # in the job directory and cannot overwrite an earlier qualification receipt.
    report = None
    container_name = None
    started = False
    if args.report:
        parent = prepare_root(args.report.parent)
        report = (parent / args.report.name).open("x", encoding="utf-8", newline="\n")
    try:
        raw = args.manifest.read_bytes()
        container_name = "spellbench-xmage-" + uuid.uuid4().hex
        argv = pinned_command(json.loads(raw), args.root, args.checkpoint, args.image, args.mode, container_name)
        started = True
        if args.mode == "serve":
            return subprocess.call(argv)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(argv, input="", text=True, capture_output=True, timeout=90)
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(argv, 124, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes)
                                               else exc.stdout or "", "checkpoint probe exceeded 90 seconds")
        result = {"schema": "spellbench-xmage-checkpoint-launch/v1", "checkpoint": args.checkpoint,
                  "manifest_sha256": hashlib.sha256(raw).hexdigest(), "argv": argv,
                  "container_image": args.image, "exit_code": proc.returncode,
                  "elapsed_seconds": round(time.monotonic() - t0, 3), "stderr": proc.stderr}
        if proc.returncode == 0:
            result["probe"] = json.loads(proc.stdout)
        else:
            result["stdout"] = proc.stdout
        result["cleanup"] = cleanup_container(container_name)
        container_name = None
        if not result["cleanup"]["confirmed_absent"]:
            result["exit_code"] = proc.returncode or 125
            sys.stderr.write("checkpoint container cleanup could not be confirmed; see saved report\n")
        json.dump(result, report, indent=2, allow_nan=False)
        report.write("\n")
        print(json.dumps({"checkpoint": args.checkpoint, "exit_code": result["exit_code"],
                          "report": str(args.report), "elapsed_seconds": result["elapsed_seconds"]}))
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
        return result["exit_code"]
    finally:
        if container_name and started:
            # Remove only this launcher's generated container, including after a
            # timeout. Killing just the Docker client would leave it running.
            cleanup = cleanup_container(container_name)
            if not cleanup["confirmed_absent"]:
                sys.stderr.write("checkpoint container cleanup could not be confirmed: " + json.dumps(cleanup) + "\n")
        if report:
            report.close()


if __name__ == "__main__":
    raise SystemExit(main())
