"""Bind the ported Exp1 search to offered decisions and isolated neural scores.

The caller starts the reviewed Java build in its own working directory and
supplies an InferenceSession with a pinned checkpoint and confined container.
This bridge supports priority and saved-anchor target/binary/numeric/named roots.
It is not a rated agent.
"""
from __future__ import annotations

import math

from spellbench import wire
from xmage_neural_decisions import decision_hash
from xmage_neural_rpc import NeuralSession

READY = {"ready": True, "search": "draftzero-exp1-original-search"}


def root_family(decision: dict) -> str:
    if decision.get("context", {}).get("kind") == "priority":
        return "priority"
    kinds = {c.get("semantic", {}).get("kind") for c in decision.get("candidates", [])}
    if kinds and kinds <= {"choose_target", "choose_cost_target", "select_object",
                           "finish_target_selection", "finish_selection"}:
        return "target"
    if kinds and kinds <= {"choose_boolean", "optional_cost", "optional_cast"}:
        return "binary"
    if kinds == {"choose_number"}:
        return "numeric"
    if kinds and kinds <= {"choose_option", "choose_color", "choose_name"}:
        return "named"
    raise ValueError("this original search bridge supports priority, target, binary, numeric and named roots")


def validate_result(decision: dict, result: dict, visits: int, calls: int) -> None:
    actual = result.get("root_visits")
    budget = result.get("search_budget")
    if budget is not None and (not isinstance(budget, dict) or type(budget.get("requested")) is not int
                              or budget != {"kind": "minimum_root_visits_until_legal_future", "requested": visits}):
        raise ValueError("search changed its declared original stopping rule")
    if (result.get("decision_sha256") != decision_hash(decision)
            or type(actual) is not int or (actual < visits if budget is not None else actual != visits)
            or type(result.get("neural_calls")) is not int or result["neural_calls"] != calls):
        raise ValueError("search result is stale or did not complete the requested work")
    candidates = decision["candidates"]
    chosen = result.get("selection", {})
    offered = next((c for c in candidates if type(chosen.get("candidate_id")) is int
                    and c["candidate_id"] == chosen["candidate_id"]), None)
    if offered is None or offered["semantic"] != chosen.get("semantic_echo"):
        raise ValueError("search selected an unoffered or changed candidate")
    children = result.get("children")
    if not isinstance(children, list) or len(children) != len(candidates):
        raise ValueError("search root does not cover all offered actions")
    expected = {wire.canonical_json_dumps(c["semantic"]) for c in candidates}
    keys = [wire.canonical_json_dumps(c.get("semantic")) for c in children]
    if len(set(keys)) != len(keys) or set(keys) != expected:
        raise ValueError("search root has a missing, aliased or unoffered action")
    for child in children:
        if (type(child.get("pruned", False)) is not bool or type(child.get("excluded", False)) is not bool
                or type(child.get("selection_masked", False)) is not bool):
            raise ValueError("search root pruning status is invalid")
        pruned = child.get("pruned", False)
        excluded = child.get("excluded", False)
        masked = child.get("selection_masked", False)
        discarded = child.get("discarded_visits", 0)
        if (type(discarded) is not int or not 0 <= discarded <= actual
                or (not masked and discarded != 0)
                or (masked and (pruned or excluded or budget is None
                     or child.get("mask_reason") != "original Exp1 bestChild resets branches without a legal future"))):
            raise ValueError("search selection masking lacks original work accounting")
        if excluded and (pruned or decision.get("context", {}).get("purpose") != "search"
                         or child["semantic"].get("kind") != "finish_selection"
                         or child["semantic"].get("purpose") != "search"
                         or "library_fail_to_find_before_minimum" not in result.get("policy_restrictions", [])
                         or child.get("reason") != "original Exp1 library target expansion requires its minimum before finishing"):
            raise ValueError("search excluded an action outside its declared original policy restriction")
        inactive = pruned or excluded or masked
        if (type(child.get("visits")) is not int or not 0 <= child["visits"] <= actual
                or (inactive and (child["visits"] != 0 or child.get("value") is not None))
                or (not inactive and (type(child.get("value")) not in (int, float) or not math.isfinite(child["value"])))):
            raise ValueError("search root statistics are invalid")
    selected_branch = next(c for c in children if c["semantic"] == offered["semantic"])
    if (sum(c["visits"] + c.get("discarded_visits", 0) for c in children) != actual or selected_branch["visits"] <= 0
            or selected_branch["visits"] != max(c["visits"] for c in children)):
        raise ValueError("search visit statistics do not support its chosen action")
    flags = result.get("world_flags")
    if (not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("horizon:", "unsupported:")) for f in flags)):
        raise ValueError("search ran outside its supported world envelope")


def search_request(record: dict, visits: int) -> dict:
    if type(visits) is not int or not 2 <= visits <= 1000:
        raise ValueError("original search visit budget must be 2..1000")
    decision = record.get("decision", {})
    family = root_family(decision)
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("search root needs offered candidates")
    ids = [c.get("candidate_id") for c in candidates]
    if any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("search candidate ids are invalid or aliased")
    keys = [wire.canonical_json_dumps(c.get("semantic")) for c in candidates]
    if any(not isinstance(c.get("semantic"), dict) for c in candidates) or len(set(keys)) != len(keys):
        raise ValueError("search candidate semantics are invalid or aliased")
    request = {k: record[k] for k in ("game_start", "decision", "world_seed", "id_seed")}
    if family != "priority":
        if not isinstance(record.get("anchor"), dict) or not isinstance(record.get("replay"), dict):
            raise ValueError("callback search needs a saved priority anchor and explicit replay history")
        request.update(anchor=record["anchor"], replay=record["replay"])
    return {**request, "visits": visits}


def search_result(record: dict, result: dict, visits: int, calls: int) -> dict:
    decision = record["decision"]
    validate_result(decision, result, visits, calls)
    if root_family(decision) != "priority":
        expected = {"earlier": len(record["replay"]["earlier"]),
                    "priority_passes": len(record["replay"]["priority_passes"]),
                    "observation_identical": True}
        proof = result.get("replay")
        if (not isinstance(proof, dict) or proof != expected
                or type(proof.get("earlier")) is not int
                or type(proof.get("priority_passes")) is not int
                or proof.get("observation_identical") is not True):
            raise ValueError("callback result does not confirm its complete public replay")
    return result


class SearchSession(NeuralSession):
    """One private search pipe and checkpoint process, poisoned on any failure."""
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)

    def choose(self, record: dict, *, visits: int, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("search session is closed or has failed")
        request = search_request(record, visits)
        return self.exchange(request, timeout_s=timeout_s,
                             validate=lambda result, calls: search_result(record, result, visits, calls))
