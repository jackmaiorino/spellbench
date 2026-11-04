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
import hashlib
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
        self._native_seats = {"p0": "p0", "p1": "p1"}
        self._groups, self._internal = [], self._new_internal()
        self._committing, self._commit_steps, self._group_info, self._wire = False, [], None, []

    def reset(self, request):
        rules = request.get("rules", {})
        names = rules.get("extensions", [])
        self.infoset_on = INFOSET in names
        if self.infoset_on:
            # The base adapter knows only its own extensions; it never reads
            # this one, so the request it sees omits it.
            request = {**request, "rules": {**rules, "extensions": [n for n in names if n != INFOSET]}}
        # A new game's statistics start before its first decision is posed
        # (inside the reset); a rejected reset keeps the active game's.
        kept = (self._composition, self._native_seats, self._groups, self._internal)
        self._composition = {"groups": 0, "wall_us": 0, "max_wall_us": 0, "unavailable": {}}
        self._groups, self._internal = [], self._new_internal()
        first = rules.get("starting_seat", "p0")
        # The native bridge seats the starting player as p0 (kernel_engine_v2
        # reset); its receipt counts by native seat.
        self._native_seats = {"p0": "p0", "p1": "p1"} if first == "p0" else {"p0": "p1", "p1": "p0"}
        result = super().reset(request)
        if result.get("response_type") != "error":
            self.rules = {**self.rules, "extensions": list(names)}
        else:
            self._composition, self._native_seats, self._groups, self._internal = kept
        return result

    @staticmethod
    def _new_internal():
        return {seat: {"eligible": 0, "refusals": {}} for seat in ("p0", "p1")}

    @staticmethod
    def _native_actor(view):
        return json.loads(view["extensions"]["x_kernel_v5"]["observation_json"])["acting_player"]

    def step(self, request):
        # The wire answers of the open group, for the commit check (G6).
        recorded = False
        if getattr(self, "buffer", None) is not None and isinstance(request.get("selection"), dict):
            candidate = request["selection"].get("candidate_id")
            if type(candidate) is int:
                self._wire.append(candidate)
                recorded = True
        result = super().step(request)
        if recorded and result.get("response_type") == "error" and self._wire:
            self._wire.pop()
        return result

    def native_step(self, candidate):
        if self._committing:
            self._commit_steps.append((self.current, candidate))
        super().native_step(candidate)

    def commit_buffer(self):
        """Commits the group, then checks the commit (fairness gate G6) and
        tallies the group's internal native decisions: those the bridge poses
        while the group commits and no bot is shown (receipt reconciliation)."""
        # The planned trajectory, read before the bridge moves (previews of
        # the root are valid only until then; evicted ones are fetched again).
        planned = None
        if self.infoset_on and self._group_info is not None and self._group_info["composition"] is not None:
            planned = self.trajectory(self.buffer)
        wire, self._wire = list(self._wire), []
        self._committing, self._commit_steps = True, []
        try:
            super().commit_buffer()
        finally:
            self._committing = False
        steps, self._commit_steps = self._commit_steps, []
        for view, _ in steps[1:]:
            native = self.current_infoset(view)
            if native is None:
                continue
            side = self._internal[self._native_actor(view)]
            side["eligible"] += 1
            if "refusal" in native:
                key = f"{native['refusal']}:{native.get('refusal_detail', 'unclassified')}"
                side["refusals"][key] = side["refusals"].get(key, 0) + 1
        if self.infoset_on and self._group_info is not None:
            self._groups.append(self.commit_check(steps, self._group_info, planned, wire))
        self._group_info = None

    @staticmethod
    def current_infoset(view):
        native = view.get("extensions", {}).get(INFOSET)
        return native if isinstance(native, dict) else None

    @staticmethod
    def tensor_digest(flat_extension):
        """sha256 of a point's x_kernel_flat_v4 tensor (canonical JSON)."""
        text = json.dumps(flat_extension.get("tensor"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    def commit_check(self, steps, info, planned, wire):
        """G6: every committed native point is the planned (previewed) point
        the composition was built from (candidates and x_kernel_flat_v4
        equal) with the planned row picked, and the planned keys are the
        composition row of the group's wire answer: the rows Pi induced. The
        committed points' tensor digests go to the receipt for comparison
        with the entrant's walk (the imported state's points)."""
        record = {"type": info["type"], "root_seat": info["root_seat"], "points": len(steps),
                  "witness": info["witness"], "composition": info["composition"] is not None,
                  "committed_tensors": [self.tensor_digest(view["extensions"][FLAT]) for view, _ in steps]}
        if info["composition"] is None:
            return record
        planned = planned or []
        views_equal = len(planned) == len(steps) and all(
            p_view["candidates"] == view["candidates"] and p_view["extensions"][FLAT] == view["extensions"][FLAT]
            and p_pick == pick for (p_view, p_pick, _), (view, pick) in zip(planned, steps))
        committed = [key for _, _, key in planned]
        table = info["composition"]["keys"]
        expected = next(([table[k] for k in row["native"]] for row in info["composition"]["completions"]
                         if row["wire"] == wire), None)
        record.update(committed_keys=committed, expected_keys=expected, views_equal=views_equal, wire=wire,
                      keys_equal=expected is not None and committed == expected)
        return record

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
        record = {"receipt": "x_kernel_infoset_v1_adapter", "game_id": self.game, "composition": self._composition,
                  "native_seats": self._native_seats, "groups": self._groups, "internal": self._internal}
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
                allowed = isinstance(detail, str) and (
                    detail in R3_SUBCLASSES if code == "R3" else
                    detail == EXPORT_SUBCLASS or (code == "R2" and detail in R2_SURFACE_SUBCLASSES))
                if not allowed:
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
        self._group_info = {"type": type(self.buffer).__name__, "root_seat": self._native_actor(self.root),
                            "composition": composition, "witness": self.group_witness()}
        self._wire = []
        return extension

    def group_witness(self):
        """Design 13's AC3 witness classes this group belongs to."""
        buffer = self.buffer
        if isinstance(buffer, BlockDeclaration):
            plan = buffer.plan
            return {"multi_attacker": len(plan.minimums) >= 2, "multi_blocker": len(plan.blockers) >= 2}
        if isinstance(buffer, TriggerOrder):
            return {"three_triggers": len(buffer.items) >= 3}
        return {}

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
        found = self.trajectory(plan)
        if found is None or any(key is None for _, _, key in found):
            return None
        return [key for _, _, key in found]

    def trajectory(self, plan):
        """The native points a finished plan visits from the root, each as
        (preview view, selected candidate, canonical key), through the shared
        private preview cache (a missing entry is fetched); None when a point
        carries no keys."""
        if isinstance(plan, TriggerOrder):
            keys = self._row_keys(self.root)
            selected = plan.result()
            if keys is None:
                return None
            return [(self.root, selected, keys[self.root["extensions"][FLAT]["row_candidate_ids"].index(selected)])]
        if isinstance(plan, BlockDeclaration):
            binding = legacy_block_assignment(self.root, plan.plan, plan.assignment())
            pick = lambda view: native_block_pick(view, binding)
        else:
            binding = native_arrangement_binding(self.root, self.arrangement_cards)
            result = plan.result()
            pick = lambda view: native_arrangement_pick(view, result, binding)
        entry = self.previews.get(()) or self.previews.put((), [self.root, None], 0)
        prefix, found = [], []
        for _ in range(4096):
            view = entry[0]
            row_keys = self._row_keys(view)
            if row_keys is None:
                return None
            selected = pick(view)
            found.append((view, selected, row_keys[view["extensions"][FLAT]["row_candidate_ids"].index(selected)]))
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
                return found
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
