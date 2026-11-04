"""Spellbench v2 environment for the W1 search entrant: kernel_engine_v2 plus x_kernel_infoset_v1.

The native bridge runs with --x-kernel-infoset-v1 and attaches, at every
eligible decision of the acting seat, the W1 producer's canonical state (a
function of that seat's information only) or a viewer-derived refusal code.
This adapter forwards it as the wire extension x_kernel_infoset_v1 and
translates the bridge's order map into wire terms:

* ordinary decisions: ``live_candidate_ids[i]`` is the wire candidate of the
  imported session's row i (the row the search's pick-v2 index names);
* the first substep of a buffered group (blocks, trigger order, arrangements)
  whose native root carries a payload: ``composition`` lists every complete
  group assignment the buffer accepts (the wire candidate index at each
  substep) with the canonical keys of the native rows it induces, in native
  order. The entrant's walk (W1 design section 7) tests compatibility against
  every completion, not the representative one.

Nothing private reaches the wire: the payload carries canonical handles only,
the candidate map names wire candidates and the keys are digests of canonical
action semantics. kernel_engine_v2.py itself is unchanged, so boards that do
not enable the extension keep their pinned engine bytes.
"""
from __future__ import annotations

import argparse
import os
import time
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
from spellbench import wire
from spellbench.errors import MalformedJsonError
from spellbench.messages import EnvHelloOk
from kernel_engine_v2 import FLAT, KernelEngine, NativePeer, ProjectionError, error
from kernel_combat_v2 import BlockDeclaration, legacy_block_assignment, native_block_pick
from kernel_arrangement_v2 import native_arrangement_binding, native_arrangement_pick
from kernel_order_v2 import TriggerOrder

INFOSET = "x_kernel_infoset_v1"
WIRE_SCHEMA = "mtg-kernel-spellbench-infoset/v1"
NATIVE_SCHEMA = "x_kernel_infoset_v1"
BRIDGE_FLAG = "--x-kernel-infoset-v1"
# Refusal subclasses (amendment 43.1 part 2): a code refused by the export
# itself is "export", except R3, which names whose library-search plan is
# pending (fairness gate G1); an R2 the payload refuses names the surface.
EXPORT_SUBCLASS = "export"
R2_SURFACE_SUBCLASSES = frozenset({"hunter_trigger_order", "optional_cost_reshape", "madness_reprompt",
                                   "discard_untracked", "opponent_discard", "combat_untracked",
                                   "other_surface"})
R3_SUBCLASSES = frozenset({"opponent", "plan_error"})
# Why a group carries no composition (fairness gate G3); each is a C5 fault.
COMPOSITION_UNAVAILABLE = ("composition_cap", "no_completions", "missing_preview_keys")
# The directory for engine-side receipts: the bridge's (it reads the variable)
# and this adapter's, one file per game.
RECEIPT_DIR_ENV = "W1_INFOSET_RECEIPT_DIR"
# A group whose buffer accepts more complete assignments than this carries
# no composition (the entrant answers it with its policy and counts why).
COMPLETION_CAP = 512


class InfosetPeer(NativePeer):
    """The native bridge with the producer on."""

    def __init__(self, executable):
        self.executable = executable
        self.child = self._spawn()
        self.serial = 0

    def _spawn(self):
        # The bridge inherits the environment, W1_INFOSET_RECEIPT_DIR included.
        return subprocess.Popen([self.executable, "--x-kernel-flat-v4", "--private-v2-support", BRIDGE_FLAG],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def restart(self):
        self.close()
        self.child = self._spawn()


def completions(plan, cap=COMPLETION_CAP):
    """Every complete assignment the buffer accepts from its current prefix:
    (wire candidate index per remaining substep, finished plan). None past cap."""
    found = []

    def walk(state, prefix):
        count = len(state.semantics())
        for candidate in range(count):
            nxt = deepcopy(state)
            if nxt.choose(candidate):
                found.append((prefix + (candidate,), nxt))
                if len(found) > cap:
                    raise OverflowError
            else:
                walk(nxt, prefix + (candidate,))

    try:
        walk(plan, ())
    except OverflowError:
        return None
    return found


class InfosetEngine(KernelEngine):
    def __init__(self, peer, catalog, **options):
        super().__init__(peer, catalog, **options)
        self.hello["extensions"] = [*self.hello["extensions"], {"name": INFOSET, "native_ids": False}]
        EnvHelloOk.from_json(self.hello)
        self.infoset_on = False
        self.receipt_dir = os.environ.get(RECEIPT_DIR_ENV) or None
        self._composition = {"groups": 0, "wall_us": 0, "max_wall_us": 0, "unavailable": {}}

    def reset(self, request):
        rules = request.get("rules", {})
        names = rules.get("extensions", [])
        self.infoset_on = INFOSET in names
        if self.infoset_on:
            # The base adapter knows only its own extensions; it never reads
            # this one, so the request it sees omits it.
            request = {**request, "rules": {**rules, "extensions": [n for n in names if n != INFOSET]}}
        result = super().reset(request)
        if result.get("response_type") != "error":
            self.rules = {**self.rules, "extensions": list(names)}
        self._composition = {"groups": 0, "wall_us": 0, "max_wall_us": 0, "unavailable": {}}
        return result

    def terminal(self, rid, outcome, reason, winner=None):
        result = super().terminal(rid, outcome, reason, winner)
        self.write_receipt()
        return result

    def write_receipt(self):
        """The adapter's engine-side receipt for the game just ended (G10):
        composition enumeration wall, groups and why any group had none."""
        if not (self.infoset_on and self.receipt_dir and self.game):
            return
        safe = "".join(c if c.isalnum() or c == "-" else "_" for c in self.game)
        record = {"receipt": "x_kernel_infoset_v1_adapter", "game_id": self.game, "composition": self._composition}
        Path(self.receipt_dir, f"{safe}.adapter.json").write_text(json.dumps(record, sort_keys=True) + "\n",
                                                                  encoding="utf-8")

    def pose(self, rid):
        opened = self.buffer is None
        result = super().pose(rid)
        if not self.infoset_on:
            return result
        native = self.current["extensions"].get(INFOSET)
        if self.buffer is None:
            extension = self.ordinary_extension(native)
        elif opened:
            extension = self.group_extension(native, len(result["seat_decision"]["candidates"]))
        else:
            extension = None
        if extension is not None:
            result["seat_decision"]["extensions"][INFOSET] = extension
        return result

    @staticmethod
    def _checked(native):
        if native is None:
            return None
        if not isinstance(native, dict) or native.get("schema") != NATIVE_SCHEMA:
            raise ProjectionError("native bridge sent an unknown infoset extension")
        if "refusal" in native:
            refusal = {"schema": WIRE_SCHEMA, "refusal": native["refusal"]}
            # The refusal's subclass (amendment 43.1 part 2): for R2 the
            # surface state the payload cannot carry, else "export".
            detail = native.get("refusal_detail")
            if detail is not None:
                code = native["refusal"]
                allowed = (detail in R3_SUBCLASSES if code == "R3" else
                           detail == EXPORT_SUBCLASS or (code == "R2" and detail in R2_SURFACE_SUBCLASSES))
                if not isinstance(detail, str) or not allowed:
                    raise ProjectionError("native infoset refusal_detail is not a subclass of its code")
                refusal["refusal_detail"] = detail
            return refusal
        if not isinstance(native.get("payload_json"), str):
            raise ProjectionError("native infoset extension lacks its payload")
        return {"schema": WIRE_SCHEMA, "payload_json": native["payload_json"]}

    def ordinary_extension(self, native):
        extension = self._checked(native)
        if extension is None or "refusal" in extension:
            return extension
        ids = self.current["extensions"][FLAT]["row_candidate_ids"]
        live_rows = native.get("live_rows")
        extension["live_candidate_ids"] = (None if live_rows is None else
                                           [self.native_candidates.index(ids[row]) for row in live_rows])
        return extension

    def group_extension(self, native, candidate_count):
        extension = self._checked(native)
        if extension is None or "refusal" in extension:
            return extension
        started = time.perf_counter_ns()
        composition, unavailable = self.composition(candidate_count)
        wall_us = (time.perf_counter_ns() - started) // 1000
        stats = self._composition
        stats["groups"] += 1
        stats["wall_us"] += wall_us
        stats["max_wall_us"] = max(stats["max_wall_us"], wall_us)
        extension["composition"] = composition
        if composition is None:
            extension["composition_unavailable"] = unavailable
            stats["unavailable"][unavailable] = stats["unavailable"].get(unavailable, 0) + 1
        return extension

    def composition(self, candidate_count):
        """(each completion's wire indices and native row keys, None) or (None,
        why): the group is too large, has no completions, or a native point
        carries no preview keys."""
        found = completions(self.buffer)
        if found is None:
            return None, "composition_cap"
        if not found or any(len(wire) < 1 for wire, _ in found):
            return None, "no_completions"
        if {wire[0] for wire, _ in found} != set(range(candidate_count)):
            raise ProjectionError("buffered completions do not cover the posed candidates")
        table, index, rows = [], {}, []
        for wire_choices, plan in found:
            keys = self.native_keys(plan)
            if keys is None:
                return None, "missing_preview_keys"
            encoded = []
            for key in keys:
                if key not in index:
                    index[key] = len(table)
                    table.append(key)
                encoded.append(index[key])
            rows.append({"wire": list(wire_choices), "native": encoded})
        return {"keys": table, "completions": rows}, None

    @staticmethod
    def _row_keys(view):
        keys = view["extensions"].get(INFOSET, {}).get("row_keys")
        return keys if isinstance(keys, list) else None

    def native_keys(self, plan):
        """The canonical keys of the native rows a finished plan induces, in
        native order, through the shared private preview cache."""
        if isinstance(plan, TriggerOrder):
            keys = self._row_keys(self.root)
            row = self.root["extensions"][FLAT]["row_candidate_ids"].index(plan.result())
            return None if keys is None else [keys[row]]
        if isinstance(plan, BlockDeclaration):
            binding = legacy_block_assignment(self.root, plan.plan, plan.assignment())
            pick = lambda view: native_block_pick(view, binding)
        else:
            binding = native_arrangement_binding(self.root, self.arrangement_cards)
            result = plan.result()
            pick = lambda view: native_arrangement_pick(view, result, binding)
        entry = self.previews.get(()) or self.previews.put((), [self.root, None], 0)
        prefix, keys = [], []
        for _ in range(4096):
            view = entry[0]
            row_keys = self._row_keys(view)
            if row_keys is None:
                return None
            selected = pick(view)
            keys.append(row_keys[view["extensions"][FLAT]["row_candidate_ids"].index(selected)])
            prefix.append(selected)
            entry = self.previews.get(tuple(prefix))
            if entry is None:
                answer = self.peer.request({"request_type": "preview_steps", "game_id": self.game,
                    "expected_step": self.root["step"], "candidate_ids": prefix})
                if answer["response_type"] not in ("private_complete", "private_preview"):
                    raise ProjectionError("private completion preview refused within its declaration")
                view = answer["view"] if answer["response_type"] == "private_preview" else None
                size = getattr(self.peer, "last_line_bytes", None)
                entry = self.previews.put(tuple(prefix), [view, None], len(json.dumps(answer)) if size is None else size)
            if entry[0] is None:
                return keys
        raise ProjectionError("private completion preview exceeded its bound")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--known-cards", action="store_true")
    args = parser.parse_args()
    peer = InfosetPeer(args.bridge)
    try:
        engine = InfosetEngine(peer, json.loads(args.catalog.read_bytes()), source_revision=args.source_revision,
                               known_cards=args.known_cards)
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
