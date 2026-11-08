"""Neutral environment for the reveal-aware canonical search successor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from kernel_engine_infoset_v2 import (
    InfosetEngine, R1_REVEAL_SUBCLASSES, R1_SUBCLASSES, R2_SURFACE_SUBCLASSES,
    R3_SUBCLASSES, R3B_SUBCLASSES,
)
from kernel_engine_reveal_v3 import KernelRevealEngineV3, RevealNativePeerV3, SCHEMA, SEATS
from kernel_engine_v2 import FLAT, ProjectionError, error
from spellbench import wire
from spellbench.errors import MalformedJsonError
from spellbench.messages import EnvHelloOk

INFOSET = "x_kernel_infoset_reveal_v4"
WIRE_SCHEMA = "mtg-kernel-spellbench-infoset-reveal/v4"
BRIDGE_FLAG = "--x-kernel-infoset-reveal-v4"
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_REFUSALS = {
    "R1": R1_SUBCLASSES | R1_REVEAL_SUBCLASSES,
    "R2": R2_SURFACE_SUBCLASSES | {"export"},
    "R3": R3_SUBCLASSES,
    "R3b": R3B_SUBCLASSES,
    **{code: {"export"} for code in ("R1b", "R4", "R5", "R6", "R7", "R8", "R8b")},
}


def is_digest(value):
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def checked_payload(text, hand, viewer=None):
    """Read only the public envelope; the native worker verifies its digest."""
    if type(text) is not str:
        raise ProjectionError("reveal search payload is not JSON text")
    try:
        value = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ProjectionError("malformed reveal search payload") from exc
    if (type(value) is not dict or value.get("schema") != INFOSET or
            not is_digest(value.get("sha256")) or not is_digest(value.get("state_sha256")) or
            type(value.get("viewer")) is not int or value["viewer"] not in (0, 1) or
            (viewer is not None and value["viewer"] != viewer)):
        raise ProjectionError("wrong reveal search payload identity")
    facts = value.get("reveal_hand")
    if (type(facts) is not list or any(type(row) is not dict or set(row) != {"card_name", "minimum"}
            or type(row["minimum"]) is not int for row in facts) or facts != hand):
        raise ProjectionError("search hand minima differ from the viewer's reveal transcript")
    return value


def opponent_hand(facts, actor):
    return [{"card_name": row["card_name"], "minimum": row["minimum"]}
            for row in facts if row["owner_seat"] != actor]


class RevealSearchNativePeerV4(RevealNativePeerV3):
    def _start(self):
        self.child = subprocess.Popen([self.executable, BRIDGE_FLAG],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def request(self, request):
        result = super().request(request)
        if request["request_type"] == "hello":
            extensions = result.get("extensions") if type(result) is dict else None
            if type(extensions) is not list or INFOSET not in extensions:
                raise ProjectionError("native bridge lacks the reveal search profile")
        return result


class KernelRevealSearchEngineV4(KernelRevealEngineV3):
    # The old and new profiles use the same neutral buffer plans. Bind that
    # traversal to this profile's row-key reader and the original preview cache.
    composition = InfosetEngine.composition
    native_keys = InfosetEngine.native_keys
    trajectory = InfosetEngine.trajectory

    def __init__(self, peer, catalog, **options):
        super().__init__(peer, catalog, **options)
        identity = self.hello["engine"]
        identity["version"] = "pauper-reveal-search-v4.0.0"
        identity["rules_snapshot_id"] += ":canonical-search-v4"
        self.provenance.update(engine_version=identity["version"],
                               rules_snapshot_id=identity["rules_snapshot_id"])
        self.hello["extensions"].append({"name": INFOSET, "native_ids": False})
        EnvHelloOk.from_json(self.hello)
        self._group_search = False
        self._expected_commit = None

    def reset(self, request):
        names = request["rules"]["extensions"]
        if (len(names) != 2 or set(names) != {SCHEMA, INFOSET} or
                request["rules"]["opponent_decklist"] != "visible"):
            return error(request["request_id"], "unsupported_rule",
                         "this profile requires visible decklists and both reveal extensions")
        return super().reset({**request, "rules": {**request["rules"], "extensions": [SCHEMA]}})

    @staticmethod
    def _row_keys(view):
        ext = view["extensions"].get(INFOSET)
        if ext is None:
            return None
        if type(ext) is not dict or ext.get("schema") != INFOSET:
            raise ProjectionError("unknown reveal search preview schema")
        keys = ext.get("row_keys")
        if keys is None:
            return None
        ids = view["extensions"][FLAT]["row_candidate_ids"]
        if type(keys) is not list or len(keys) != len(ids) or not all(map(is_digest, keys)):
            raise ProjectionError("malformed reveal search preview row keys")
        return keys

    def pose(self, request_id):
        opened = self.buffer is None
        response = super().pose(request_id)
        if opened:
            self._group_search = False
        if self.buffer is not None and not opened:
            return response
        sd = response["seat_decision"]
        native = self.current["extensions"].get(INFOSET)
        if native is None:
            return response
        if type(native) is not dict or native.get("schema") != INFOSET:
            raise ProjectionError("unknown reveal search extension schema")
        if "refusal" in native:
            code, detail = native["refusal"], native.get("refusal_detail")
            if (set(native) != {"schema", "refusal", "refusal_detail"} or
                    type(code) is not str or type(detail) is not str or detail not in _REFUSALS.get(code, ())):
                raise ProjectionError("unknown reveal search refusal")
            sd["extensions"][INFOSET] = {"schema": WIRE_SCHEMA, "refusal": code,
                                          "refusal_detail": detail}
            return response

        if set(native) != {"schema", "payload_json", "live_rows", "row_keys"}:
            raise ProjectionError("unexpected reveal search extension fields")
        actor = sd["acting_seat"]
        viewer = next(index for index, seat in enumerate(SEATS) if self.projection.seat(seat) == actor)
        hand = opponent_hand(self.hand_constraints(viewer), actor)
        checked_payload(native["payload_json"], hand, viewer)
        extension = {"schema": WIRE_SCHEMA, "payload_json": native["payload_json"]}
        if self.buffer is None:
            ids = self.current["extensions"][FLAT]["row_candidate_ids"]
            rows = native["live_rows"]
            if rows is not None and (type(rows) is not list or any(type(row) is not int for row in rows)
                                     or sorted(rows) != list(range(len(ids)))):
                raise ProjectionError("reveal search row map is not a bijection")
            extension["live_candidate_ids"] = (None if rows is None else
                                               [self.native_candidates.index(ids[row]) for row in rows])
        else:
            composition, unavailable = self.composition(len(sd["candidates"]))
            extension["composition"] = composition
            if unavailable is not None:
                extension["composition_unavailable"] = unavailable
            self._group_search = composition is not None
        sd["extensions"][INFOSET] = extension
        return response

    def commit_buffer(self):
        if self._group_search:
            planned = self.trajectory(self.buffer)
            if planned is None:
                raise ProjectionError("reveal search lost a buffered completion")
            self._expected_commit = iter(planned)
        try:
            super().commit_buffer()
            if self._expected_commit is not None and next(self._expected_commit, None) is not None:
                raise ProjectionError("reveal search committed a shorter buffered completion")
        finally:
            self._expected_commit = None
            self._group_search = False

    def native_step(self, candidate):
        if self._expected_commit is not None:
            expected = next(self._expected_commit, None)
            if (expected is None or candidate != expected[1] or
                    self.current["step"] != expected[0]["step"] or
                    self.current["candidates"][candidate] != expected[0]["candidates"][candidate]):
                raise ProjectionError("reveal search buffered commit differs from the preview")
        super().native_step(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    peer = RevealSearchNativePeerV4(args.bridge)
    try:
        engine = KernelRevealSearchEngineV4(peer, json.loads(args.catalog.read_bytes()),
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
