"""Launch the DraftZero FDN graph network inside a network-disabled container.

`check` runs the release's goldens through the serving path and saves the
receipt. `serve` accepts encoded graph states on stdin for the game adapter.
The release's weights and Python never load on the host: each pinned input is
verified here, then mounted read-only into the `gnn` image target.

    docker build --target gnn --tag spellbench-xmage-models:gnn integrations/xmage-models
    python python/tools/xmage_gnn_backend.py check --root INPUT_ROOT --image sha256:ID --report RECEIPT.json
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

from xmage_checkpoint_backend import cleanup_container
from xmage_release_assets import prepare_root, validate_asset, verify

ARCHITECTURE = "draftzero-gnn"
MOUNTS = {"checkpoint": ("model", "/inputs/model.safetensors"), "vocab": ("vocab", "/inputs/vocab.json"),
          "config": ("config", "/inputs/config.json"), "model": ("graph_net", "/inputs/graph_net.py")}


def pinned_command(manifest: dict, root: Path, image: str, mode: str, container_name: str | None = None) -> list[str]:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("model image must be an immutable local image SHA-256, not a tag")
    if mode not in ("check", "serve"):
        raise ValueError("unsupported graph network backend mode")
    config = manifest.get("inference_backends", {}).get(ARCHITECTURE)
    if not config or len(config.get("checkpoints", [])) != 1 or config.get("checkpoint_format") != "safetensors":
        raise ValueError("the graph network needs exactly one pinned safetensors checkpoint")
    assets = {a["id"]: a for a in manifest["assets"]}
    if len(assets) != len(manifest["assets"]):
        raise ValueError("duplicate release input id")
    root = prepare_root(root)
    ids = {key: config["checkpoints"][0] if key == "checkpoint" else config[key] for key in MOUNTS}
    if mode == "check":
        ids["goldens"] = config["goldens"]
    if len(set(ids.values())) != len(ids):
        raise ValueError("graph network inputs must be distinct assets")
    argv = ["docker", "run", "--rm", "--interactive", "--network", "none", "--read-only",
            "--cpus", "1", "--memory", "3g", "--memory-swap", "3g", "--pids-limit", "64",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"]
    if container_name:
        if not re.fullmatch(r"spellbench-xmage-[a-f0-9]{32}", container_name):
            raise ValueError("invalid owned container name")
        argv.extend(["--name", container_name])
    destinations = {**{key: dst for key, (_, dst) in MOUNTS.items()}, "goldens": "/inputs/goldens.jsonl.gz"}
    for key, aid in ids.items():
        asset = assets[aid]
        validate_asset(asset)
        path = root / asset["filename"]
        verify(path, asset)
        if any(x in str(path) for x in (",", "\n", "\r")):
            raise ValueError("input path cannot be expressed as one read-only Docker mount")
        argv.extend(["--mount", f"type=bind,src={path},dst={destinations[key]},readonly"])
    argv.extend([image, mode])
    for key, (flag, dst) in MOUNTS.items():
        argv.extend([f"--{flag.replace('_', '-')}", dst, f"--{flag.replace('_', '-')}-sha256", assets[ids[key]]["sha256"]])
    if mode == "check":
        argv.extend(["--goldens", destinations["goldens"], "--goldens-sha256", assets[ids["goldens"]]["sha256"]])
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "serve"))
    parser.add_argument("--manifest", type=Path, default=Path("engines/xmage/releases.json"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--image", required=True, help="docker image inspect --format '{{.Id}}' IMAGE")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if (args.mode == "check") != (args.report is not None):
        raise ValueError("a check saves exactly one report; serve reports on stdout")
    report = None
    container_name = None
    if args.report:
        parent = prepare_root(args.report.parent)
        report = (parent / args.report.name).open("x", encoding="utf-8", newline="\n")
    try:
        raw = args.manifest.read_bytes()
        container_name = "spellbench-xmage-" + uuid.uuid4().hex
        argv = pinned_command(json.loads(raw), args.root, args.image, args.mode, container_name)
        if args.mode == "serve":
            return subprocess.call(argv)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(argv, input="", text=True, capture_output=True, timeout=args.timeout)
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
            proc = subprocess.CompletedProcess(argv, 124, out, f"graph network check exceeded {args.timeout} seconds")
        result = {"schema": "spellbench-draftzero-gnn-launch/v1", "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                  "argv": argv, "container_image": args.image, "exit_code": proc.returncode,
                  "elapsed_seconds": round(time.monotonic() - t0, 3), "stderr": proc.stderr}
        if proc.returncode == 0:
            result["check"] = json.loads(proc.stdout)
        else:
            result["stdout"] = proc.stdout
        result["cleanup"] = cleanup_container(container_name)
        container_name = None
        if not result["cleanup"]["confirmed_absent"]:
            result["exit_code"] = proc.returncode or 125
        json.dump(result, report, indent=2, allow_nan=False)
        report.write("\n")
        summary = {"exit_code": result["exit_code"], "report": str(args.report)}
        if "check" in result:
            summary.update({k: result["check"][k] for k in ("max_abs_diff", "argmax_agree", "states")})
        print(json.dumps(summary))
        return result["exit_code"]
    finally:
        if container_name:
            cleanup = cleanup_container(container_name)
            if not cleanup["confirmed_absent"]:
                sys.stderr.write("graph network container cleanup could not be confirmed: " + json.dumps(cleanup) + "\n")
        if report:
            report.close()


if __name__ == "__main__":
    raise SystemExit(main())
