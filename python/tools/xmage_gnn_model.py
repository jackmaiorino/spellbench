"""One owned, confined DraftZero FDN graph network process for the graph search pipe.

The Java search sends encoded graph states; this session forwards each one to
the no-network container and returns the per-node priority and target scores,
the use logits and the value, as DraftZero's graph server returns them.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path

from spellbench import wire
from xmage_checkpoint_backend import cleanup_container
from xmage_gnn_backend import ARCHITECTURE, pinned_command
from xmage_neural_decisions import close_resources, load_response

GRAPH_FIELDS = ("indices", "values", "edge_child", "edge_parent", "edge_label")
MAX_NODES = 1 << 16
MAX_EDGES = 1 << 17
FEATURE_BINS = 2147483647


def validate_graph(graph) -> int:
    """The encoded state's node count; refuse anything but five bounded integer arrays."""
    if not isinstance(graph, dict) or set(graph) != set(GRAPH_FIELDS):
        raise ValueError("graph state needs exactly its node and edge arrays")
    for key in GRAPH_FIELDS:
        if not isinstance(graph[key], list) or any(type(x) is not int for x in graph[key]):
            raise ValueError("graph state arrays must hold integers")
    nodes, edges = len(graph["indices"]), len(graph["edge_child"])
    if not 0 < nodes <= MAX_NODES or len(graph["values"]) != nodes:
        raise ValueError("graph state has an invalid node count")
    if edges > MAX_EDGES or len(graph["edge_parent"]) != edges or len(graph["edge_label"]) != edges:
        raise ValueError("graph state has an invalid edge count")
    if any(not 0 <= x < FEATURE_BINS for x in graph["indices"]) or any(
            not 0 <= x < nodes for key in ("edge_child", "edge_parent") for x in graph[key]):
        raise ValueError("graph state ids or edges are outside their envelope")
    return nodes


def validate_heads(scores: dict, nodes: int) -> None:
    for key in ("priority", "target"):
        values = scores.get(key)
        if not isinstance(values, list) or len(values) != nodes or any(
                x is not None and (type(x) not in (int, float) or not math.isfinite(x)) for x in values):
            raise ValueError("graph network node scores are invalid")
    use, value = scores.get("use"), scores.get("value")
    if (not isinstance(use, list) or len(use) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in use)
            or type(value) not in (int, float) or not -1 <= value <= 1):
        raise ValueError("graph network use or value output is invalid")


class GraphInference:
    """The confined graph network, with a shared request deadline; any failure poisons it."""
    input_field = "graph"

    def __init__(self, manifest: dict, root: Path, image: str, *, startup_s: float = 120,
                 peer_factory=wire.SubprocessPeer, on_owned=None, on_close=None):
        self.architecture = ARCHITECTURE
        config = manifest.get("inference_backends", {}).get(ARCHITECTURE, {})
        assets = {a["id"]: a for a in manifest["assets"]}
        self.checkpoint = config["checkpoints"][0]
        self.container = "spellbench-xmage-" + uuid.uuid4().hex
        self.argv = pinned_command(manifest, root, image, "serve", self.container)
        self.peer = None
        self.closed = self.failed = False
        self.cleanup = None
        self.sequence = 0
        self.on_close = on_close
        self.coverage = {"leaf_occurrences": 0, "leaf_occurrences_in_vocab": 0, "calls": 0}
        pins = {"model": assets[self.checkpoint]["sha256"], "vocab": assets[config["vocab"]]["sha256"],
                "config": assets[config["config"]]["sha256"], "graph_net": assets[config["model"]]["sha256"]}
        try:
            if on_owned is not None:
                on_owned(self.container)
            self.peer = peer_factory(self.argv, timeout_s=startup_s)
            self.ready = load_response(self.peer.read_line())
            if (self.ready.get("ready") is not True or self.ready.get("architecture") != ARCHITECTURE
                    or self.ready.get("input_sha256") != pins or self.ready.get("dtype") != "float32"):
                raise ValueError("graph network readiness does not match its pinned release inputs")
        except BaseException as exc:
            self.failed = True
            cleanup_error = None
            try:
                self.close()
            except Exception as failure:
                cleanup_error = str(failure)
            failure = RuntimeError("graph network startup failed: " + str(exc))
            failure.cleanup, failure.cleanup_error = self.cleanup, cleanup_error
            raise failure from exc

    def score(self, graph, *, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("graph network session is closed or has failed")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("graph inference needs a positive finite remaining clock")
        deadline = time.monotonic() + timeout_s
        try:
            nodes = validate_graph(graph)
            self.sequence += 1
            rid = str(self.sequence)
            self.peer.set_timeout(max(0, deadline - time.monotonic()))
            self.peer.write_line(json.dumps({"id": rid, "state": graph, "heads": True},
                                            separators=(",", ":"), allow_nan=False).encode())
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("graph inference exhausted its shared write/read clock")
            self.peer.set_timeout(remaining)
            scores = load_response(self.peer.read_line())
            if scores.get("id") != rid:
                raise ValueError("graph network returned a stale or mismatched request id")
            validate_heads(scores, nodes)
            coverage = scores.get("coverage", {})
            self.coverage["calls"] += 1
            for key in ("leaf_occurrences", "leaf_occurrences_in_vocab"):
                self.coverage[key] += int(coverage.get(key, 0))
            if time.monotonic() > deadline:
                raise TimeoutError("graph inference exhausted its shared validation clock")
            return {k: scores[k] for k in ("priority", "target", "use", "value")}
        except BaseException as failure:
            self.failed = True
            close_resources(self, failure=failure)
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.on_close is not None:
            # Leaf vocabulary coverage is the guard against XMage string drift.
            self.on_close({"event": "graph_network_coverage", **self.coverage})
        try:
            if self.peer is not None:
                self.peer.close()
        finally:
            self.cleanup = cleanup_container(self.container)
        if not self.cleanup["confirmed_absent"]:
            raise RuntimeError("owned graph network container cleanup could not be confirmed")
