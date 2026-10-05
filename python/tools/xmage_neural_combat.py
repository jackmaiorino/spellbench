"""Bind original Exp1 combat plans and their neural work to permitted decisions."""
from __future__ import annotations

import math
import copy

from spellbench import wire
from xmage_neural_decisions import decision_hash
from xmage_neural_rpc import NeuralSession

READY = {"ready": True, "search": "draftzero-exp1-original-combat"}


def combat_kind(decision: dict) -> str:
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("combat needs offered declaration choices")
    kinds = {c.get("semantic", {}).get("kind") for c in candidates}
    if kinds == {"declare_attack"}:
        return "attack"
    if kinds == {"declare_block"}:
        return "block"
    raise ValueError("combat root must have one declaration family")


def battlefield(decision: dict) -> tuple[str, dict]:
    observation = decision.get("observation", {})
    viewer = observation.get("viewer")
    if viewer not in ("p0", "p1"):
        raise ValueError("combat needs an explicit acting viewer")
    objects = {}
    for player in observation.get("players", []):
        for record in player.get("battlefield", []):
            oid = record.get("object_id")
            if not isinstance(oid, str) or oid in objects:
                raise ValueError("combat battlefield object is missing or aliased")
            objects[oid] = record
    return viewer, objects


def target(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("combat target is invalid")
    if value.get("player") in ("p0", "p1"):
        return {"player": value["player"]}
    reference = value.get("object", value)
    if isinstance(reference, dict) and isinstance(reference.get("object_id"), str):
        return {"object_id": reference["object_id"]}
    raise ValueError("combat target has no permitted reference")


def validate_result(decision: dict, result: dict, visits: int, calls: int, *,
                    minimum_visits: bool = True, expected_budget: dict | None = None) -> None:
    family = combat_kind(decision)
    viewer, objects = battlefield(decision)
    if (result.get("decision_sha256") != decision_hash(decision) or result.get("combat") != family
            or type(result.get("neural_calls")) is not int or result["neural_calls"] != calls):
        raise ValueError("combat result is stale or has different neural work")
    flags = result.get("world_flags")
    if (not isinstance(flags, list)
            or any(not isinstance(flag, str) or flag.startswith(("unsupported:", "horizon:")) for flag in flags)):
        raise ValueError("combat ran outside its supported world envelope")
    pairs = result.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("combat plan is missing")
    seen = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("combat plan pair is invalid")
        name = "attacker" if family == "attack" else "blocker"
        oid = pair.get(name)
        own = objects.get(oid)
        if own is None or own.get("controller_seat") != viewer or oid in seen:
            raise ValueError("combat plan uses an unknown, opposing or duplicate creature")
        seen.add(oid)
        if family == "attack":
            defender = target(pair.get("defender"))
            if defender is None or defender.get("player") == viewer:
                raise ValueError("combat attack has no opposing defender")
            if "object_id" in defender and (defender["object_id"] not in objects
                    or objects[defender["object_id"]].get("controller_seat") == viewer):
                raise ValueError("combat defender is not a permitted opposing object")
        else:
            attacker = objects.get(pair.get("attacker"))
            if (attacker is None or attacker.get("controller_seat") == viewer
                    or attacker.get("permanent", {}).get("attacking") is not True):
                raise ValueError("combat block targets an unknown or nonattacking creature")
    roots = result.get("roots")
    if not isinstance(roots, list):
        raise ValueError("combat has no original search-root receipts")
    accounted = 0
    for index, root in enumerate(roots):
        actual = root.get("root_visits")
        neural = root.get("neural_calls")
        expected_type = "CHOOSE_USE" if family == "attack" else "CHOOSE_TARGET"
        if (type(root.get("index")) is not int or root["index"] != index or root.get("type") != expected_type
                or type(root.get("requested_minimum")) is not int
                or root["requested_minimum"] != (visits if minimum_visits else 0)
                or expected_budget is not None and root.get("search_budget") != expected_budget
                or type(actual) is not int or actual < 1 or minimum_visits and actual < visits
                or type(neural) is not int or neural <= 0):
            raise ValueError("combat root did not complete its original search budget")
        accounted += neural
        children = root.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError("combat root has no legal branches")
        keys = []
        spent = 0
        for child in children:
            action = child.get("action")
            if family == "attack":
                if type(action) is not bool:
                    raise ValueError("original attacker root is not binary")
            elif action is not None:
                obj = objects.get(action)
                if obj is None or obj.get("controller_seat") == viewer or obj.get("permanent", {}).get("attacking") is not True:
                    raise ValueError("original blocker root targets an unobserved attacker")
            keys.append(wire.canonical_json_dumps(action))
            count = child.get("visits")
            discarded = child.get("discarded_visits", 0)
            pruned, masked = child.get("pruned", False), child.get("selection_masked", False)
            if (type(pruned) is not bool or type(masked) is not bool or pruned and masked
                    or type(count) is not int or not 0 <= count <= actual
                    or type(discarded) is not int or not 0 <= discarded <= actual
                    or not masked and discarded != 0
                    or (pruned or masked) and (count != 0 or child.get("value") is not None)
                    or not (pruned or masked) and (type(child.get("value")) not in (int, float)
                                                 or not math.isfinite(child["value"]))):
                raise ValueError("combat root statistics are invalid")
            spent += count + discarded
        if len(set(keys)) != len(keys) or spent != actual:
            raise ValueError("combat root lost, aliased or invented search work")
        if family == "attack" and set(keys) != {b"true", b"false"}:
            raise ValueError("original attacker root does not cover both binary actions")
        selected = wire.canonical_json_dumps(root.get("selected"))
        branch = next((child for child, key in zip(children, keys) if key == selected), None)
        if (branch is None or branch["visits"] <= 0
                or branch["visits"] != max(child["visits"] for child in children)):
            raise ValueError("combat work does not support its original selection")
    if accounted != calls:
        raise ValueError("combat plan has unaccounted neural inference")


def select_candidate(decision: dict, result: dict) -> dict:
    """Bind this initial wire substep to the original complete plan."""
    family = combat_kind(decision)
    if result.get("decision_sha256") != decision_hash(decision) or result.get("combat") != family:
        raise ValueError("combat plan belongs to a different decision")
    name = "attacker" if family == "attack" else "blocker"
    ids = {c.get("semantic", {}).get(name, {}).get("object_id") for c in decision["candidates"]}
    if len(ids) != 1 or not isinstance(next(iter(ids)), str):
        raise ValueError("wire combat substep does not identify one creature")
    oid = next(iter(ids))
    matches = [pair for pair in result["pairs"] if pair[name] == oid]
    if len(matches) > 1:
        raise ValueError("combat plan aliases this creature")
    wanted = None if not matches else matches[0]["defender" if family == "attack" else "attacker"]
    offered = []
    for candidate in decision["candidates"]:
        semantic = candidate["semantic"]
        selected = semantic.get("defender" if family == "attack" else "attacker")
        if family == "attack":
            equal = target(selected) == target(wanted)
        else:
            equal = selected is None if wanted is None else isinstance(selected, dict) and selected.get("object_id") == wanted
        if equal:
            offered.append(candidate)
    if len(offered) != 1:
        raise ValueError("original combat assignment is unoffered or aliased")
    return {"candidate_id": offered[0]["candidate_id"], "semantic_echo": offered[0]["semantic"]}


class CombatPlan:
    """Retain a validated complete plan across one engine declaration group.

    Only the declarations already emitted may change the initial observation.
    The engine may hold those choices until the group completes.
    An unexpected public change, skipped substep or rewind poisons this plan.
    """
    def __init__(self, decision: dict, result: dict, *, visits: int,
                 minimum_visits: bool = True, expected_budget: dict | None = None):
        if type(visits) is not int or not 2 <= visits <= 1000:
            raise ValueError("combat visits must be 2..1000")
        validate_result(decision, result, visits, result.get("neural_calls"),
                        minimum_visits=minimum_visits, expected_budget=expected_budget)
        self._initialize(decision, result)

    def _initialize(self, decision, result):
        self.initial, self.result = copy.deepcopy(decision), copy.deepcopy(result)
        self.family = combat_kind(decision)
        self.viewer, self.objects = battlefield(self.initial)
        self.group = self._group(self.initial)
        if self.group["substep_index"] != 0:
            raise ValueError("combat plan needs the initial group substep")
        self.first_step = decision.get("seat_step")
        if type(self.first_step) is not int or not 0 <= self.first_step <= wire.MAX_JSON_INT:
            raise ValueError("combat plan needs its engine seat step")
        self.next_index, self.picks = 0, {}
        self.failed = False

    @staticmethod
    def _group(decision):
        group = decision.get("group")
        if (not isinstance(group, dict) or any(type(group.get(key)) is not int for key in
                ("group_id", "substep_count", "substep_index"))
                or not 0 <= group["group_id"] <= wire.MAX_JSON_INT
                or not 1 <= group["substep_count"] <= wire.MAX_JSON_INT
                or not 0 <= group["substep_index"] < group["substep_count"]):
            raise ValueError("combat needs its explicit engine declaration group")
        return group

    @property
    def complete(self):
        return self.next_index == self.group["substep_count"]

    def _state(self, decision):
        viewer, objects = battlefield(decision)
        if viewer != self.viewer or set(objects) != set(self.objects):
            raise ValueError("combat public battlefield changed outside its declarations")
        original = copy.deepcopy(self.initial["observation"])
        current = copy.deepcopy(decision["observation"])
        for snapshot in (original, current):
            for player in snapshot["players"]:
                for record in player.get("battlefield", []):
                    oid = record["object_id"]
                    chosen = self.picks.get(oid)
                    if chosen is None:
                        continue
                    permanent = record.get("permanent", {})
                    if snapshot is current and permanent != self.objects[oid].get("permanent", {}):
                        if self.family == "attack":
                            vigilance = "vigilance" in record.get("characteristics", {}).get("keywords", [])
                            if (permanent.get("attacking") is not True
                                    or permanent.get("tapped") is not (not vigilance)
                                    or target(permanent.get("attack_target")) != target(chosen)):
                                raise ValueError("combat observation differs from its emitted attack")
                        else:
                            blocked = permanent.get("blocked_attackers")
                            if (permanent.get("blocking") is not True or not isinstance(blocked, list)
                                    or [target(value) for value in blocked] != [{"object_id": chosen}]):
                                raise ValueError("combat observation differs from its emitted block")
                    fields = ("tapped", "attacking", "attack_target") if self.family == "attack" else ("blocking", "blocked_attackers")
                    for field in fields:
                        permanent.pop(field, None)
        if wire.canonical_json_dumps(original) != wire.canonical_json_dumps(current):
            raise ValueError("combat public state changed outside its emitted declarations")

    def select(self, decision: dict) -> dict:
        if self.failed or self.complete:
            raise ValueError("combat plan is complete or failed")
        try:
            group = self._group(decision)
            if (combat_kind(decision) != self.family or group["group_id"] != self.group["group_id"]
                    or group["substep_count"] != self.group["substep_count"]
                    or group["substep_index"] != self.next_index
                    or type(decision.get("seat_step")) is not int
                    or decision["seat_step"] != self.first_step + self.next_index
                    or decision.get("acting_seat") != self.viewer
                    or decision.get("context", {}).get("rewind") is not False):
                raise ValueError("combat declaration group is stale, skipped or rewound")
            self._state(decision)
            candidates = decision["candidates"]
            ids = [candidate.get("candidate_id") for candidate in candidates]
            if (any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError("combat candidate ids are invalid or aliased")
            # State and group validation, rather than a new search, authorizes
            # rebinding the original assignment to this later wire substep.
            result = {**self.result, "decision_sha256": decision_hash(decision)}
            selection = select_candidate(decision, result)
            semantic = selection["semantic_echo"]
            name, reference = ("attacker", "defender") if self.family == "attack" else ("blocker", "attacker")
            oid = semantic[name]["object_id"]
            if oid in self.picks or oid not in self.objects or self.objects[oid].get("controller_seat") != self.viewer:
                raise ValueError("combat declaration repeated or changed its creature")
            chosen = semantic[reference]
            self.picks[oid] = target(chosen) if self.family == "attack" else None if chosen is None else chosen["object_id"]
            self.next_index += 1
            return selection
        except BaseException:
            self.failed = True
            raise


def combat_request(record: dict, visits: int) -> dict:
    if type(visits) is not int or not 2 <= visits <= 1000:
        raise ValueError("combat visits must be 2..1000")
    decision = record.get("decision", {})
    combat_kind(decision)
    ids = [candidate.get("candidate_id") for candidate in decision["candidates"]]
    if any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("combat candidate ids are invalid or aliased")
    request = {key: record[key] for key in ("game_start", "decision", "world_seed", "id_seed")}
    return {**request, "visits": visits}


def combat_result(record: dict, result: dict, visits: int, calls: int) -> dict:
    decision = record["decision"]
    validate_result(decision, result, visits, calls)
    return {**result, "selection": select_candidate(decision, result)}


class CombatSession(NeuralSession):
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)

    def plan(self, record: dict, *, visits: int, timeout_s: float) -> dict:
        if self.closed or self.failed:
            raise ValueError("combat session is closed or failed")
        request = combat_request(record, visits)
        return self.exchange(request, timeout_s=timeout_s,
                             validate=lambda result, calls: combat_result(record, result, visits, calls))
