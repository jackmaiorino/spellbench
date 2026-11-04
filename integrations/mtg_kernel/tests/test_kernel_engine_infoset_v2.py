"""The entrant's engine adapter: order map translation and buffered completions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_engine_infoset_v2 as engine
from kernel_combat_v2 import BlockDeclaration, BlockPlan
from kernel_order_v2 import TriggerOrder


class Projection:
    @staticmethod
    def legacy_ref(source, nullable=False):
        return {"object_id": source["id"]}


def trigger_root():
    """A native order_triggers point: three sources, six permutation rows in
    an arbitrary native order; the bridge's lockstep rows map to candidate
    ids through row_candidate_ids, and each row has a canonical key."""
    sources = [{"id": n, "card_name": f"T{n}"} for n in range(3)]
    orders = [[2, 1, 0], [0, 1, 2], [1, 2, 0], [0, 2, 1], [2, 0, 1], [1, 0, 2]]
    candidates = [{"candidate_id": i, "semantic": {"kind": "order_triggers", "pending_sources": sources, "order": o}}
                  for i, o in enumerate(orders)]
    rows = [3, 5, 0, 1, 4, 2]  # lockstep row r executes candidate rows[r]
    return {"candidates": candidates, "step": 9, "extensions": {
        "x_kernel_flat_v4": {"row_candidate_ids": rows},
        engine.INFOSET: {"schema": engine.NATIVE_SCHEMA, "payload_json": "{}",
                         "row_keys": [f"key-{''.join(map(str, orders[c]))}" for c in rows]}}}


def bare_engine():
    e = object.__new__(engine.InfosetEngine)
    e.previews = None
    return e


def test_completions_enumerate_every_trigger_order_and_cap():
    root = trigger_root()
    plan = TriggerOrder(root, Projection())
    found = engine.completions(plan)
    assert sorted(w for w, _ in found) == [(a, b) for a in range(3) for b in range(2)]
    assert engine.completions(plan, cap=5) is None
    # The plan itself is untouched.
    assert plan.prefix == ()


def test_trigger_composition_keys_each_permutation_through_the_lockstep_rows():
    root = trigger_root()
    e = bare_engine()
    e.root = root
    e.buffer = TriggerOrder(root, Projection())
    composition = e.composition(3)
    seen = {}
    for row in composition["completions"]:
        first, second = row["wire"]
        order = [first, [x for x in range(3) if x != first][second]]
        order.append(3 - sum(order))
        (key,) = row["native"]
        seen[tuple(order)] = composition["keys"][key]
    assert seen == {tuple(o): "key-" + "".join(map(str, o)) for o in
                    ([2, 1, 0], [0, 1, 2], [1, 2, 0], [0, 2, 1], [2, 0, 1], [1, 0, 2])}


def test_ordinary_order_map_names_wire_candidates():
    e = bare_engine()
    e.current = {"extensions": {"x_kernel_flat_v4": {"row_candidate_ids": [7, 4, 9]}}}
    e.native_candidates = [9, 7, 4]  # wire order: candidate ids re-sorted by semantic
    native = {"schema": engine.NATIVE_SCHEMA, "payload_json": "{}", "live_rows": [2, 0, 1], "row_keys": ["a", "b", "c"]}
    extension = e.ordinary_extension(native)
    # Imported row 0 is lockstep row 2 (native id 9, wire 0), and so on.
    assert extension == {"schema": engine.WIRE_SCHEMA, "payload_json": "{}", "live_candidate_ids": [0, 1, 2]}
    native["live_rows"] = None
    assert e.ordinary_extension(native)["live_candidate_ids"] is None
    assert e.ordinary_extension({"schema": engine.NATIVE_SCHEMA, "refusal": "R8"}) == {
        "schema": engine.WIRE_SCHEMA, "refusal": "R8"}
    assert e.ordinary_extension({"schema": engine.NATIVE_SCHEMA, "refusal": "R2", "refusal_detail": "discard_untracked"}) == {
        "schema": engine.WIRE_SCHEMA, "refusal": "R2", "refusal_detail": "discard_untracked"}
    assert e.ordinary_extension({"schema": engine.NATIVE_SCHEMA, "refusal": "R8", "refusal_detail": "export"}) == {
        "schema": engine.WIRE_SCHEMA, "refusal": "R8", "refusal_detail": "export"}
    for code, detail in (("R2", "a free text detail"), ("R2", "discard_reshape"), ("R8", "discard_untracked"),
                         ("R2", 3)):
        with pytest.raises(engine.ProjectionError):
            e.ordinary_extension({"schema": engine.NATIVE_SCHEMA, "refusal": code, "refusal_detail": detail})
    assert e.ordinary_extension(None) is None


def test_block_completions_cover_every_legal_declaration():
    plan = BlockPlan(("b1", "b2"), {"b1": ("a1", "a2"), "b2": ("a1", "a2")}, {"a1": 1, "a2": 1})
    found = engine.completions(BlockDeclaration(plan, {k: {"object_id": k} for k in ("a1", "a2", "b1", "b2")}))
    assignments = {tuple(p.prefix) for _, p in found}
    assert len(assignments) == 9
    assert all(plan.completion(a) == a for a in assignments)
