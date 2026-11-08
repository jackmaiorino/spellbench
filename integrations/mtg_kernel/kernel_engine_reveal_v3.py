"""Opt-in neutral engine with event-time public reveal transcripts.

This profile supplies reveal-derived hand constraints through its extension.
It does not declare complete historical known_cards support or forward the
legacy history/tensor extensions. The existing v2 entrypoint stays unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from kernel_engine_v2 import KernelEngine, NativePeer, error
from kernel_observation_v2 import ProjectionError
from kernel_reveal_v3 import RevealHistoryV3, SCHEMA, SEATS
from spellbench import wire
from spellbench.errors import MalformedJsonError
from spellbench.messages import EnvHelloOk


class RevealNativePeerV3(NativePeer):
    def __init__(self, executable):
        self.executable, self.serial = executable, 0
        self._start()

    def _start(self):
        self.child = subprocess.Popen(
            [self.executable, "--x-kernel-flat-v4", "--private-v2-support", "--reveal-meaning-v3"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def restart(self):
        self.close()
        self._start()


class _CheckedRevealPeerV3:
    """Validate private framing before inherited neutral code reads it."""
    def __init__(self, peer):
        self.peer, self.identity = peer, None

    def __getattr__(self, name):
        return getattr(self.peer, name)

    def request(self, value):
        result = self.peer.request(value)
        if type(result) is not dict:
            raise ProjectionError("native reveal response must be an object")
        if value["request_type"] == "hello":
            identity = result.get("engine")
            if result.get("response_type") != "hello_ok" or type(identity) is not dict:
                raise ProjectionError("native reveal bridge did not handshake")
            if self.identity is not None and identity != self.identity:
                raise ProjectionError("native reveal bridge identity changed on restart")
            self.identity = deepcopy(identity)
        return result


class KernelRevealEngineV3(KernelEngine):
    def __init__(self, peer, catalog, *, source_revision=None):
        super().__init__(_CheckedRevealPeerV3(peer), catalog,
                         source_revision=source_revision, known_cards=False)
        identity = self.hello["engine"]
        identity["version"] = "pauper-reveal-v3.0.0"
        identity["rules_snapshot_id"] += ":reveal-meaning-v3"
        self.provenance.update(engine_version=identity["version"],
                               rules_snapshot_id=identity["rules_snapshot_id"])
        self.hello["extensions"] = [{"name": SCHEMA, "native_ids": False}]
        EnvHelloOk.from_json(self.hello)
        self._reveal_game = None
        self.reveal_history = RevealHistoryV3()

    def reset(self, request):
        if request["rules"]["extensions"] != [SCHEMA]:
            return error(request["request_id"], "unsupported_rule",
                         "this profile requires only x_reveal_meaning_v3")
        # Base v2 performs all reset admission and neutral grouping, with its
        # original extension set disabled. This class alone emits the new one.
        base = deepcopy(request)
        base["rules"]["extensions"] = []
        try:
            return super().reset(base)
        except (ValueError, KeyError, IndexError, OSError):
            # Restart can fail before base reset binds the new game. The
            # failure still answers this reset, with no decisions performed.
            self.game = request["game_id"]
            self.used.add(self.game)
            self.answered = self.completed = 0
            self._reveal_game = self.game
            self.reveal_history = RevealHistoryV3()
            # The private child is no longer trusted. Base reset restarts a
            # child left at a decision after a neutral terminal/cap.
            self.current = {"response_type": "decision"}
            return self.terminal(request["request_id"], "halted", "reveal_projection_failure")

    def absorb_history(self):
        if type(self.current) is not dict or self.current.get("response_type") not in ("decision", "terminal"):
            raise ProjectionError("native reveal response is not a decision or terminal")
        if self._reveal_game != self.game:
            self.reveal_history = RevealHistoryV3()
            self._reveal_game = self.game
        extensions = self.current.get("extensions")
        if type(extensions) is not dict:
            raise ProjectionError("malformed native reveal extensions")
        support = extensions.get("x_kernel_v2_support")
        if type(support) is not dict:
            raise ProjectionError("malformed native reveal support")
        # Consume only the already projected public operation streams. Never
        # infer a hand link or name from the omniscient legacy history slice.
        self.reveal_history.absorb(support.get("reveal_meaning_v3"))

    def hand_constraints(self, viewer):
        return self.reveal_history.known_hand(viewer, self.projection.seat)

    def pose(self, rid):
        response = super().pose(rid)
        raw = json.loads(self.current["extensions"]["x_kernel_v5"]["observation_json"])
        viewer = SEATS.index(raw["acting_player"])
        counts = {self.projection.seat(seat): raw["projection"]["hand_counts"][i]
                  for i, seat in enumerate(SEATS)}
        minimum = Counter()
        for fact in self.hand_constraints(viewer):
            minimum[fact["owner_seat"]] += fact["minimum"]
        if any(value > counts[owner] for owner, value in minimum.items()):
            raise ProjectionError("public reveal constraints exceed a public hand count")
        response["seat_decision"]["extensions"][SCHEMA] = self.reveal_history.drain(
            viewer, self.projection.seat)
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    peer = RevealNativePeerV3(args.bridge)
    try:
        engine = KernelRevealEngineV3(peer, json.loads(args.catalog.read_bytes()),
                                      source_revision=args.source_revision)
        while True:
            try:
                payload = wire.read_line(sys.stdin.buffer)
            except MalformedJsonError:
                answer = wire.canonical_json_line(error("", "malformed_json", "invalid request framing"))
            else:
                if payload is None:
                    return 0
                answer = engine.handle(payload)
            sys.stdout.buffer.write(answer)
            sys.stdout.buffer.flush()
    finally:
        peer.close()


if __name__ == "__main__":
    sys.exit(main())
