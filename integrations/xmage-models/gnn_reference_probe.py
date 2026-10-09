"""Reference check for the DraftZero FDN graph network, run only inside the network-less model container.

The release directory is mounted read-only at /release. Its files are verified against the release's
SHA256SUMS before the author's loader (gnn_release.py, graph_net.py) is imported from that mount.
Prints one JSON report: the golden comparison and the CPU time of single-state network calls.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

RELEASE = Path("/release")


def verify(release: Path) -> dict:
    rows = {}
    for line in (release / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        rows[name.strip()] = digest
    for name, digest in rows.items():
        if hashlib.sha256((release / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"hash mismatch: {name}")
    return rows


def main() -> int:
    hashes = verify(RELEASE)
    sys.path.insert(0, str(RELEASE))
    import numpy as np
    import torch
    import gnn_release as r

    torch.set_num_threads(1)
    started = time.perf_counter()
    check = r.check(RELEASE)
    check_seconds = time.perf_counter() - started

    model, leaves, edges, _ = r.load(RELEASE)
    goldens = r.read_goldens(RELEASE / "goldens.jsonl.gz")
    for g in goldens[:10]:  # warm-up, not timed
        r.evaluate(model, [g["state"]], leaves, edges)
    per_call, nodes, coverage = [], [], [0, 0]
    for g in goldens:
        t = time.perf_counter()
        r.evaluate(model, [g["state"]], leaves, edges)
        per_call.append(time.perf_counter() - t)
        ids = np.asarray(g["state"]["indices"], np.int64)
        leaf = r.gn.node_types(ids) == r.gn.NodeType.LEAF
        nodes.append(len(ids))
        coverage[0] += int(leaf.sum())
        coverage[1] += int((leaves.lookup(ids[leaf]) >= 0).sum())
    ms = sorted(x * 1000 for x in per_call)
    report = {
        "schema": "spellbench-draftzero-gnn-reference-probe/v1",
        "release_sha256": hashes,
        "packages": {"torch": torch.__version__, "numpy": np.__version__,
                     "safetensors": __import__("safetensors").__version__, "python": sys.version.split()[0]},
        "torch_threads": torch.get_num_threads(),
        "check": check,
        "check_seconds": round(check_seconds, 3),
        "single_call_ms": {"calls": len(ms), "median": round(statistics.median(ms), 3),
                           "p10": round(ms[len(ms) // 10], 3), "p90": round(ms[len(ms) * 9 // 10], 3),
                           "max": round(ms[-1], 3)},
        "nodes_per_state": {"median": statistics.median(nodes), "max": max(nodes)},
        "golden_leaf_occurrences_in_vocab": coverage[1] / coverage[0],
        "graph_types": {str(k): sum(1 for g in goldens if g["graph_type"] == k) for k in (0, 3, 5)},
    }
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
