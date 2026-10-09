"""Isolated inference for the DraftZero FDN graph network (danbrooks/draftzero-fdn-gnn).

Use only through the no-network `gnn` image target. The host mounts the pinned
release files read-only under /inputs and passes their SHA-256 pins. The
network code is the release's own graph_net.py (MageZero's NetGraph), imported
from that mount after its pin is checked; the weights load from safetensors,
so nothing is unpickled.

A request is one encoded state in MageZero's graph-server layout plus the
decision it was encoded at:

    {"id": ..., "state": {"indices", "values", "edge_child", "edge_parent", "edge_label"},
     "graph_type": 0 | 3 | 5 | null, "options": [[node index, ...], ...]}

The response carries one logit per option (log-sum-exp of the option's node
scores under the head the decision reads, or the use head's [no, yes]), the
use logits, value = tanh(value_x), value_x and the leaf vocabulary coverage.
graph_type null asks for the value only.

    check   run the release's goldens through the serving path and report
    serve   NDJSON requests on stdin after a readiness line
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path

PRIORITY, CHOOSE_TARGET, CHOOSE_USE = 0, 3, 5
MAX_NODES = 1 << 16
MAX_EDGES = 1 << 17
INPUTS = ("model", "vocab", "config", "graph_net")


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_pin(path: Path, expected: str) -> None:
    if not path.is_file() or path.is_symlink() or file_hash(path) != expected:
        raise ValueError(f"graph network input changed: {path.name}")


class Runtime:
    def __init__(self, paths: dict[str, Path], pins: dict[str, str]):
        # The confinement boundary is the host's Docker command; this refusal
        # catches an accidental direct invocation on the host.
        if not Path("/.dockerenv").is_file():
            raise ValueError("graph network loading requires the no-network container launcher")
        for name in INPUTS:
            check_pin(paths[name], pins[name])
        import numpy as np
        import torch
        from safetensors.torch import load_file
        self.np, self.torch = np, torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        spec = importlib.util.spec_from_file_location("draftzero_gnn_graph_net", paths["graph_net"])
        gn = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = gn
        spec.loader.exec_module(gn)
        self.gn = gn
        config = json.loads(paths["config"].read_text(encoding="utf-8"))
        vocab = json.loads(paths["vocab"].read_text(encoding="utf-8"))
        if config.get("feature_hash", {}).get("bins") != gn.GLOBAL_MAX or gn.GLOBAL_MAX != 2147483647:
            raise ValueError("graph network release uses a different feature hash range")
        if config["node_types"] != {t.name: int(t) for t in gn.NodeType}:
            raise ValueError("graph network node types differ from the release config")
        if config["value_bounds"] != gn.VALUE_BOUNDS:
            raise ValueError("graph network value buckets differ from the release config")
        self.leaves, self.edges = self._vocab(vocab["leaf_ids"]), self._vocab(vocab["edge_ids"])
        if len(vocab["leaf_ids"]) != config["num_leaves"] or len(vocab["edge_ids"]) != config["num_edge_labels"]:
            raise ValueError("graph network vocabulary sizes differ from the release config")
        self.model = gn.NetGraph(len(vocab["leaf_ids"]), len(vocab["edge_ids"]), config["arch"])
        self.model.load_state_dict(load_file(str(paths["model"])), strict=True)
        self.model = self.model.to("cpu").eval()
        parameters = sum(p.numel() for p in self.model.parameters())
        if parameters != config["parameters"]:
            raise ValueError("graph network parameter count differs from the release config")
        self.summary = {"architecture": "draftzero-gnn", "release": config["name"], "parameters": parameters,
                        "input_sha256": dict(pins), "num_leaves": len(vocab["leaf_ids"]),
                        "num_edge_labels": len(vocab["edge_ids"]), "feature_hash_bins": gn.GLOBAL_MAX,
                        "dependencies": {name: version(name) for name in ("torch", "numpy", "safetensors")},
                        "device": "cpu", "dtype": "float32", "threads": 1, "unpickled": False}

    def _vocab(self, ids):
        np = self.np
        ids = np.asarray(ids, np.int64)
        if len(np.unique(ids)) != len(ids):
            raise ValueError("graph network vocabulary has duplicate ids")
        order = np.argsort(ids, kind="stable")
        return ids, order, ids[order]

    def _lookup(self, vocab, raw):
        np = self.np
        ids, order, ordered = vocab
        raw = np.asarray(raw, np.int64)
        pos = np.minimum(np.searchsorted(ordered, raw), len(ids) - 1)
        return np.where(ordered[pos] == raw, order[pos], -1)

    def _graph(self, state: dict):
        np, torch, gn = self.np, self.torch, self.gn
        if not isinstance(state, dict) or set(state) != {"indices", "values", "edge_child", "edge_parent", "edge_label"}:
            raise ValueError("encoded state needs exactly indices, values and the three edge arrays")
        arrays = {}
        for key, value in state.items():
            if not isinstance(value, list) or any(type(x) is not int for x in value):
                raise ValueError(f"encoded state field {key} must be a list of integers")
            arrays[key] = np.asarray(value, np.int64)
        n, e = len(arrays["indices"]), len(arrays["edge_child"])
        if not 0 < n <= MAX_NODES or len(arrays["values"]) != n:
            raise ValueError("encoded state has an invalid node count")
        if e > MAX_EDGES or len(arrays["edge_parent"]) != e or len(arrays["edge_label"]) != e:
            raise ValueError("encoded state has an invalid edge count")
        if (arrays["indices"] < 0).any() or (arrays["indices"] >= gn.GLOBAL_MAX).any():
            raise ValueError("encoded node ids must be in the feature hash range")
        for key in ("edge_child", "edge_parent"):
            if e and ((arrays[key] < 0).any() or (arrays[key] >= n).any()):
                raise ValueError("encoded edges must refer to the state's nodes")
        types = gn.node_types(arrays["indices"])
        leaf = types == gn.NodeType.LEAF
        rows = np.where(leaf, self._lookup(self.leaves, arrays["indices"]), -1)
        labels = self._lookup(self.edges, arrays["edge_label"]) + 1
        if not (rows >= 0).any():
            raise ValueError("graph network vocabulary contains none of the encoded leaves")
        t = lambda x: torch.from_numpy(np.ascontiguousarray(x, np.int64))
        graphs = gn.Graphs(t(types), t(rows), t(arrays["values"]), torch.tensor([0, n]),
                           t(arrays["edge_child"]), t(arrays["edge_parent"]), t(labels))
        coverage = {"leaf_occurrences": int(leaf.sum()), "leaf_occurrences_in_vocab": int((rows >= 0).sum()),
                    "edges": e, "edge_labels_in_vocab": int((labels > 0).sum())}
        return graphs, types, coverage

    def evaluate(self, state: dict, graph_type, options) -> dict:
        np, torch, gn = self.np, self.torch, self.gn
        graphs, types, coverage = self._graph(state)
        n = len(types)
        if graph_type is not None and graph_type not in (PRIORITY, CHOOSE_TARGET, CHOOSE_USE):
            raise ValueError("graph network reads only priority, target and yes/no decisions")
        if graph_type is None:
            if options:
                raise ValueError("a value-only request carries no options")
        elif not isinstance(options, list) or not options or any(
                not isinstance(o, list) or any(type(k) is not int or not 0 <= k < n for k in o) for o in options):
            raise ValueError("options must be non-empty lists of the state's node indices")
        with torch.inference_mode():
            out = self.model(graphs)
        use = out.use[0].double().tolist()
        value_x = float(out.value_x[0])
        if not all(map(math.isfinite, use + [value_x])):
            raise ValueError("graph network returned non-finite use or value outputs")
        logits = []
        if graph_type == CHOOSE_USE:
            if len(options) > 2:
                raise ValueError("a yes/no decision has at most two options")
            logits = use[:len(options)]
        elif graph_type is not None:
            scores = (out.priority if graph_type == PRIORITY else out.target).numpy()
            readable = (gn.PRIORITY_TYPES if graph_type == PRIORITY else gn.TARGET_TYPES)
            for nodes in options:
                if not nodes:
                    raise ValueError("an option at a headed decision needs at least one graph node")
                if any(types[k] not in readable for k in nodes):
                    raise ValueError("an option node is not a node type this decision's head reads")
                x = scores[np.asarray(nodes, np.int64)].astype(np.float64)
                m = x.max()
                if not np.isfinite(m):
                    raise ValueError("graph network returned a non-finite option score")
                logits.append(float(m + np.log(np.exp(x - m).sum())))
        return {"option_logits": logits, "use": use, "value": math.tanh(value_x), "value_x": value_x,
                "coverage": coverage}


def check(runtime: Runtime, goldens: Path, goldens_sha256: str) -> dict:
    check_pin(goldens, goldens_sha256)
    with gzip.open(goldens, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    worst = {"option_logits": 0.0, "value_x": 0.0, "value": 0.0, "use": 0.0}
    agree, by_type, timings, leaf_hits, leaf_total = 0, {}, [], 0, 0
    repeat = None
    for i, g in enumerate(rows):
        t0 = time.perf_counter()
        r = runtime.evaluate(g["state"], g["graph_type"], g["options"])
        timings.append(time.perf_counter() - t0)
        want = g["expected"]
        worst["option_logits"] = max(worst["option_logits"],
                                     max(abs(a - b) for a, b in zip(r["option_logits"], want["option_logits"])))
        if len(r["option_logits"]) != len(want["option_logits"]):
            raise ValueError("serving path option count differs from a golden")
        worst["value_x"] = max(worst["value_x"], abs(r["value_x"] - want["value_x"]))
        worst["value"] = max(worst["value"], abs(r["value"] - want["value"]))
        worst["use"] = max(worst["use"], max(abs(a - b) for a, b in zip(r["use"], want["use"])))
        ok = max(range(len(r["option_logits"])), key=r["option_logits"].__getitem__) == \
            max(range(len(want["option_logits"])), key=want["option_logits"].__getitem__)
        agree += ok
        key = str(g["graph_type"])
        by_type[key] = by_type.get(key, 0) + 1
        leaf_hits += r["coverage"]["leaf_occurrences_in_vocab"]
        leaf_total += r["coverage"]["leaf_occurrences"]
        if i == 0:
            repeat = runtime.evaluate(g["state"], g["graph_type"], g["options"]) == r
    ms = sorted(x * 1000 for x in timings[10:])
    return {"schema": "spellbench-draftzero-gnn-serving-check/v1", **runtime.summary,
            "goldens_sha256": goldens_sha256, "states": len(rows), "graph_types": by_type,
            "max_abs_diff": worst, "argmax_agree": agree, "repeated_inference_identical": repeat,
            "golden_leaf_occurrences_in_vocab": leaf_hits / leaf_total,
            "single_call_ms_after_warmup": {"calls": len(ms), "median": round(statistics.median(ms), 3),
                                             "p90": round(ms[len(ms) * 9 // 10], 3), "max": round(ms[-1], 3)},
            "scope": "serving path against the release goldens; no Magic game, encoder or rating"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "serve"))
    for name in INPUTS:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
        parser.add_argument(f"--{name.replace('_', '-')}-sha256", required=True)
    parser.add_argument("--goldens", type=Path)
    parser.add_argument("--goldens-sha256")
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in INPUTS}
    pins = {name: getattr(args, name + "_sha256") for name in INPUTS}
    runtime = Runtime(paths, pins)
    if args.mode == "check":
        if args.goldens is None or args.goldens_sha256 is None:
            raise ValueError("the serving check requires the pinned goldens")
        print(json.dumps(check(runtime, args.goldens, args.goldens_sha256), sort_keys=True, allow_nan=False), flush=True)
        return 0
    print(json.dumps({"ready": True, **runtime.summary}, sort_keys=True), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        result = runtime.evaluate(request["state"], request.get("graph_type"), request.get("options", []))
        print(json.dumps({"id": request["id"], **result}, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
