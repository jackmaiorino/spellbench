"""Fetch pinned public XMage release inputs without executing or unpickling them.

Archive inspection reads only ZIP directory entries. Checkpoints remain opaque
bytes on this host and must be opened in the existing no-network sandbox.
This command prepares inputs; evaluated games still use the guarded arena.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def regular_tree(root: Path) -> int:
    """Count this job's bytes; refuse links and junctions instead of following them."""
    size = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if is_link(path):
                raise ValueError(f"release input tree contains a link: {path}")
            if path.is_file():
                size += path.stat().st_size
    return size


def prepare_root(root: Path) -> Path:
    root = root.absolute()
    for path in (root, *root.parents):
        if is_link(path):
            raise ValueError("release input root must not traverse a link")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def verify(path: Path, asset: dict) -> dict:
    if is_link(path) or not path.is_file():
        raise ValueError("release asset must be a regular file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    size = path.stat().st_size
    if size != asset["bytes"] or digest != asset["sha256"]:
        raise ValueError(f"release asset does not match its pin: {asset['id']}")
    return {"id": asset["id"], "filename": path.name, "bytes": size, "sha256": digest}


def validate_asset(asset: dict) -> None:
    name = asset["filename"]
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
            or name.endswith(".") or Path(name).name != name):
        raise ValueError("invalid release asset filename")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", asset["id"]):
        raise ValueError("invalid release asset id")
    if not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"]):
        raise ValueError("release asset needs a SHA-256 pin")
    if type(asset["bytes"]) is not int or asset["bytes"] <= 0:
        raise ValueError("release asset needs a positive byte count")
    if not asset["url"].startswith("https://"):
        raise ValueError("release asset needs an HTTPS source")
    if asset.get("transport", "bytes") not in ("bytes", "github-raw-blob"):
        raise ValueError("unsupported release input transport")
    if asset.get("transport") == "github-raw-blob" and not re.fullmatch(
            r"https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/git/blobs/[a-f0-9]{40}", asset["url"]):
        raise ValueError("raw GitHub input must identify one public Git blob")


def fetch(root: Path, asset: dict, storage: dict, *, opener=urllib.request.urlopen) -> dict:
    validate_asset(asset)
    root = prepare_root(root)
    dest = root / asset["filename"]
    if dest.exists() or dest.is_symlink():
        return verify(dest, asset)
    usage = regular_tree(root)
    cap, reserve = storage["cap_bytes"], storage["reserve_bytes"]
    if type(cap) is not int or type(reserve) is not int or cap <= 0 or reserve < 0:
        raise ValueError("invalid storage budget")
    if usage + asset["bytes"] > cap:
        raise ValueError("release download would exceed the job byte cap")
    if shutil.disk_usage(root).free - asset["bytes"] < reserve:
        raise ValueError("release download would cross the free-space reserve")
    # Exclusive creation prevents a second preparer from replacing a verified input.
    part = root / f"{asset['filename']}.{time.time_ns()}.{os.getpid()}.part"
    headers = {"User-Agent": "spellbench-release-inputs/1"}
    if asset.get("transport") == "github-raw-blob":
        headers["Accept"] = "application/vnd.github.raw+json"
    request = urllib.request.Request(asset["url"], headers=headers)
    digest, total = hashlib.sha256(), 0
    with part.open("xb") as output, opener(request, timeout=60) as response:
        while chunk := response.read(2**20):
            total += len(chunk)
            if total > asset["bytes"]:
                raise ValueError("release server exceeded the pinned byte count")
            if shutil.disk_usage(root).free - len(chunk) < reserve:
                raise ValueError("release download reached the free-space reserve")
            output.write(chunk)
            digest.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    if total != asset["bytes"] or digest.hexdigest() != asset["sha256"]:
        raise ValueError(f"download failed size or SHA-256 verification: {asset['id']}")
    # A hard link atomically refuses to overwrite a concurrently prepared input.
    # Both paths belong to this job and sit on the same volume.
    try:
        os.link(part, dest)
    except FileExistsError:
        verify(dest, asset)
    part.unlink()
    return verify(dest, asset)


def archive_report(path: Path, asset: dict) -> dict:
    report = verify(path, asset)
    decks, weights, entries = [], [], []
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                raise ValueError("release ZIP has a non-relative member")
            if item.is_dir():
                continue
            entries.append([item.filename, item.file_size, item.CRC])
            if name.suffix.lower() == ".dck":
                decks.append(item.filename)
            if any(item.filename.lower().endswith(s) for s in
                   (".pt", ".pt.gz", ".pth", ".onnx", ".safetensors", ".pkl", ".pickle", ".mz")):
                weights.append({"path": item.filename, "bytes": item.file_size})
    report.update({"archive_files": len(entries), "deck_files": decks, "weight_files": weights,
                   "directory_sha256": hashlib.sha256(json.dumps(sorted(entries), separators=(",", ":"),
                                                              ensure_ascii=True).encode()).hexdigest(),
                   "inspection": "ZIP directory only; no member extracted or executed"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "verify", "archives"))
    parser.add_argument("--manifest", type=Path, default=Path("engines/xmage/releases.json"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--asset", action="append", help="asset id; repeat to select several (default: all)")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release inputs manifest")
    assets = manifest["assets"]
    if len({a["id"] for a in assets}) != len(assets) or len({a["filename"] for a in assets}) != len(assets):
        raise ValueError("release input ids and filenames must be unique")
    if args.asset:
        if set(args.asset) - {a["id"] for a in assets}:
            raise ValueError("unknown release asset")
        assets = [a for a in assets if a["id"] in args.asset]
    root = prepare_root(args.root)
    results = []
    for asset in assets:
        validate_asset(asset)
        path = root / asset["filename"]
        if args.action == "fetch":
            result = fetch(root, asset, manifest["storage"])
        elif args.action == "archives" and asset["kind"] == "engine-bundle":
            result = archive_report(path, asset)
        else:
            result = verify(path, asset)
        results.append(result)
        print(json.dumps({"verified": result["id"], "bytes": result["bytes"], "sha256": result["sha256"]}), flush=True)
    report = {"schema": "spellbench-xmage-release-receipt/v1",
              "input_manifest_sha256": hashlib.sha256(raw).hexdigest(), "assets": results,
              "execution": "opaque input preparation; no checkpoint loaded; no games run"}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
