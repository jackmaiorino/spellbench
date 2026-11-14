#!/usr/bin/env python3
"""Prove that the human-only London path left the rated board's inputs and identities byte-identical.

    python tools/rated_identity_check.py snapshot --rated-board <benchmark.json> --rated-local <local.json> --out before.json
    ... build and test the London path ...
    python tools/rated_identity_check.py compare before.json --rated-board ... --rated-local ... [--base <git rev>]

`snapshot` records the sha256 of every rated engine input (the files the rated board's `evaluation_engine_inputs`
names through the local values, the pinned bridge, scorer and catalog, `kernel_flat_bot.py`), of the repository's own
pinned copies of them, and the listening state of the given ports. `compare` repeats it and fails on any difference,
and checks with git that, since `--base`, nothing changed under `benchmarks/`, `spec/`, any
`integrations/mtg_kernel/*_v2.py`, `kernel_flat_bot.py` or the rated board's other engine files.

Exit 0 only if everything is equal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PINNED_GLOBS = ("integrations/mtg_kernel/*_v2.py", "integrations/mtg_kernel/kernel_flat_bot.py",
                "integrations/mtg_kernel/kernel_search_bot.py")
GUARDED_PATHS = ("benchmarks", "spec", "integrations/mtg_kernel/entrants")
OWNER_PORTS = (9443, 9444, 5180, 9450, 8765)


def sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def resolve(text: str, values: dict) -> str:
    return re.sub(r"\$\{([A-Z0-9_]+)\}", lambda m: values.get(m.group(1), m.group(0)), text)


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def snapshot(board_path: Path, local_path: Path) -> dict:
    board = json.loads(board_path.read_text(encoding="utf-8"))
    local = json.loads(local_path.read_text(encoding="utf-8"))
    files: dict[str, str | None] = {}
    named = list(board.get("evaluation_engine_inputs") or [])
    for key in ("MTG_KERNEL_V2_BRIDGE", "MTG_KERNEL_SCORER", "MTG_KERNEL_PUBLIC_CATALOG", "MTG_KERNEL_V2_BOT",
                "MTG_KERNEL_V2_ENGINE", "MTG_KERNEL_V2_INFOSET_ENGINE"):
        if key in local:
            named.append("${" + key + "}")
    for entry in named:
        path = resolve(entry, local)
        files[path] = sha256(Path(path))
    repo_files = {}
    for pattern in PINNED_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            repo_files[path.relative_to(REPO).as_posix()] = sha256(path)
    return {"schema": "london-human-rated-identity/v1",
            "rated_board_sha256": sha256(board_path), "rated_local_sha256": sha256(local_path),
            "rated_files": files, "repo_pinned_files": repo_files,
            "owner_ports": {str(port): listening(port) for port in OWNER_PORTS}}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--rated-board", type=Path, required=True)
        p.add_argument("--rated-local", type=Path, required=True)
        if name == "snapshot":
            p.add_argument("--out", type=Path, required=True)
        else:
            p.add_argument("before", type=Path)
            p.add_argument("--base", default="origin/claude/manabrew-adapter-20261114")
    args = parser.parse_args(argv)
    now = snapshot(args.rated_board, args.rated_local)
    if args.command == "snapshot":
        args.out.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"snapshot: {len(now['rated_files'])} rated files, {len(now['repo_pinned_files'])} repository pins -> {args.out}")
        return 0
    before = json.loads(args.before.read_text(encoding="utf-8"))
    problems: list[str] = []
    for key in ("rated_board_sha256", "rated_local_sha256", "rated_files", "repo_pinned_files"):
        if before[key] != now[key]:
            problems.append(f"{key} changed")
    for port, was in before["owner_ports"].items():
        if now["owner_ports"][port] != was:
            problems.append(f"owner port {port}: listening {was} -> {now['owner_ports'][port]} (not ours to change)")
    changed = git("diff", "--name-only", f"{args.base}..HEAD").split()
    guarded = [p for p in changed if p.startswith(tuple(g + "/" for g in GUARDED_PATHS))
               or re.fullmatch(r"integrations/mtg_kernel/[^/]+_v2\.py", p) or p == "integrations/mtg_kernel/kernel_flat_bot.py"]
    if guarded:
        problems.append(f"changed since {args.base}: {guarded}")
    if problems:
        print("RATED IDENTITY CHECK FAILED:\n  " + "\n  ".join(problems))
        return 1
    print(f"rated identity check: {len(now['rated_files'])} rated files and {len(now['repo_pinned_files'])} repository "
          f"pins equal their snapshot; nothing guarded changed since {args.base}; owner ports unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
