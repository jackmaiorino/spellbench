"""Small native clone/replay correctness check, with zero model requests.

Run two identical native games. Only one receives private preview requests;
every actual response through the terminal must still be byte-equivalent.
This does not qualify throughput or establish playing strength.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path

from kernel_observation_v2 import KernelProjection
from kernel_combat_v2 import native_block_plan, BlockDeclaration, legacy_block_assignment, native_block_pick
from kernel_arrangement_v2 import native_arrangement, native_arrangement_binding, native_arrangement_pick


class Peer:
    def __init__(self, executable):
        self.child = subprocess.Popen([executable, "--x-kernel-flat-v4", "--private-v2-support"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def request(self, value):
        self.child.stdin.write(json.dumps(value, sort_keys=True).encode() + b"\n")
        self.child.stdin.flush()
        line = self.child.stdout.readline()
        if not line:
            raise RuntimeError(f"bridge stopped: {self.child.stderr.read(4096).decode()}")
        return json.loads(line)

    def close(self):
        self.child.stdin.close()
        try:
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=10)


def check(executable, catalog, deck, seed):
    operated, baseline, fresh = Peer(executable), Peer(executable), Peer(executable)
    serial = 0
    game_id = f"preview-check-{deck}-{seed}"
    def request(value, *, both=False):
        nonlocal serial
        serial += 1
        message = {"protocol": "spellbench/v1", "request_id": f"q{serial}", **value}
        result = operated.request(message)
        if both:
            control = baseline.request(message)
            assert result == control, "preview changed an authoritative native response"
            assert fresh.request(message) == control, "fresh preview control changed authoritative state"
        elif value["request_type"] == "preview_steps":
            # Empty prefixes reset the private prefix cache to the root. The
            # next full prefix therefore replays from a fresh authoritative clone.
            fresh.request({**message, "request_id": f"fresh-root-{serial}", "candidate_ids": []})
            assert fresh.request(message) == result, "cached preview differs from a fresh clone"
        return result
    try:
        request({"request_type": "hello"}, both=True)
        current = request({"request_type": "reset", "game_id": game_id, "format": "pauper-bo1",
            "seats": [{"seat": "p0", "deck": {"catalog_id": deck}}, {"seat": "p1", "deck": {"catalog_id": deck}}],
            "game_seed": seed, "max_decisions": 512, "max_steps": 4096}, both=True)
        projector = KernelProjection(catalog, b"s"*32, keywords=True)
        rng = random.Random(101)
        transcript = hashlib.sha256()
        seen = {"blocker": {"successful": 0, "boundary_refused": 0},
                "arrangement": {"successful": 0, "boundary_refused": 0}}
        steps = 0
        while current["response_type"] == "decision":
            raw = json.loads(current["extensions"]["x_kernel_v5"]["observation_json"])
            support = current["extensions"]["x_kernel_v2_support"]
            neutral = projector.project(raw, support)
            assert all(player["hand"] is None for player in neutral["players"] if player["seat"] != neutral["viewer"])
            transcript.update(json.dumps(current, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            binder = None
            family = None
            if support.get("at_block_root") is True and seen["blocker"]["boundary_refused"] == 0:
                plan, refs = native_block_plan(raw, support, projector)
                declaration = BlockDeclaration(plan, refs)
                while not declaration.choose(0):
                    pass
                binding = legacy_block_assignment(current, plan, declaration.assignment())
                binder = lambda view: native_block_pick(view, binding)
                family = "blocker"
            elif support.get("choice", {}).get("purpose") in ("scry", "look_select", "look") and seen["arrangement"]["boundary_refused"] == 0:
                plan, cards = native_arrangement(raw, support, projector)
                binding = native_arrangement_binding(current, cards)
                while not plan.choose(0):
                    pass
                arrangement = plan.result()
                binder = lambda view: native_arrangement_pick(view, arrangement, binding)
                family = "arrangement"
            if binder is not None:
                prefix = []
                peek = request({"request_type": "preview_steps", "game_id": game_id,
                    "expected_step": current["step"], "candidate_ids": prefix})
                assert peek["response_type"] == "private_preview", peek
                assert peek["view"]["extensions"] == current["extensions"]
                seen[family]["successful"] += 1
                while len(prefix) <= 256:
                    prefix.append(binder(peek["view"]))
                    peek = request({"request_type": "preview_steps", "game_id": game_id,
                        "expected_step": current["step"], "candidate_ids": prefix})
                    if peek["response_type"] == "private_complete":
                        seen[family]["boundary_refused"] += 1
                        # An overlong prefix must fail rather than silently
                        # accept its valid initial completion.
                        overlong = request({"request_type": "preview_steps", "game_id": game_id,
                            "expected_step": current["step"], "candidate_ids": prefix + [0]})
                        assert overlong["response_type"] == "error", overlong
                        break
                    assert peek["response_type"] == "private_preview", peek
                    seen[family]["successful"] += 1
                else:
                    raise RuntimeError("small preview fixture exceeded 256 private steps")
            rows = current["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"]
            chosen = rows[rng.randrange(len(rows))]
            current = request({"request_type": "step", "game_id": game_id, "expected_step": current["step"],
                "selection": {"candidate_id": chosen, "semantic_echo": current["candidates"][chosen]["semantic"]}}, both=True)
            steps += 1
        assert current["response_type"] == "terminal", current
        assert current["classification"] == "natural", "fixture did not complete naturally"
        return {"deck": deck, "seed": seed, "steps": steps, "preview_checks": seen,
                "authoritative_trace_sha256": transcript.hexdigest(), "result": current["outcome"],
                "operated_equals_control": True, "cached_preview_equals_fresh": True, "model_requests": 0}
    finally:
        operated.close()
        baseline.close()
        fresh.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_bytes())
    records = [check(args.bridge, catalog, deck, 5151) for deck in ("Affinity", "Wildfire")]
    for family in ("blocker", "arrangement"):
        assert sum(record["preview_checks"][family]["successful"] for record in records) > 0, family
        assert sum(record["preview_checks"][family]["boundary_refused"] for record in records) > 0, family
    result = {"schema": "spellbench-kernel-private-preview-replay-check/v1", "records": records, "model_requests": 0,
              "bridge_sha256": hashlib.sha256(Path(args.bridge).read_bytes()).hexdigest(),
              "catalog_sha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
