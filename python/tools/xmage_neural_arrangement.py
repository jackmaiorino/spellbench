"""Keep one original Exp1 scry/surveil operation across its wire group."""
from __future__ import annotations

import copy
import math

from spellbench import wire
from xmage_neural_combat import CombatPlan
from xmage_neural_decisions import decision_hash

PLAN_FIELDS = ("arrangement", "cards", "destinations", "order", "target_script")


def initial(decision):
    candidates = decision.get("candidates", [])
    purpose = decision.get("context", {}).get("purpose")
    if purpose not in ("scry", "surveil") or not candidates:
        raise ValueError("arrangement needs its original scry or surveil menu")
    count = candidates[0].get("semantic", {}).get("card_count")
    group = CombatPlan._group(decision)
    if (type(count) is not int or not 1 <= count <= 64 or group["substep_index"] != 0
            or group["substep_count"] != 2 * count - 1):
        raise ValueError("arrangement requires the complete initial group")
    viewer = decision.get("observation", {}).get("viewer")
    if viewer not in ("p0", "p1") or decision.get("acting_seat") != viewer:
        raise ValueError("arrangement belongs to another viewer")
    positions = {}
    for card in decision.get("observation", {}).get("known", []):
        position = card.get("position_from_top")
        if card.get("owner_seat") == viewer and card.get("zone") == "library" and type(position) is int and 0 <= position < count:
            if position in positions or card.get("how") != "looked_at" or not isinstance(card.get("object_id"), str):
                raise ValueError("arrangement top-card knowledge is missing or aliased")
            positions[position] = card
    if set(positions) != set(range(count)):
        raise ValueError("arrangement lacks every visible top-card position")
    cards = [positions[i]["object_id"] for i in range(count)]
    if len(set(cards)) != count:
        raise ValueError("arrangement aliases visible top cards")
    refs = {card["object_id"]: {"object_id": card["object_id"], "card_name": card["card_name"],
            "owner_seat": viewer, "controller_seat": viewer, "zone": "library"} for card in positions.values()}
    return purpose, cards, refs


def request(record, visits):
    initial(record["decision"])
    if type(visits) is not int or not 2 <= visits <= 1000:
        raise ValueError("arrangement needs its original visit budget")
    if not isinstance(record.get("anchor"), dict) or not isinstance(record.get("replay"), dict):
        raise ValueError("arrangement needs a saved priority anchor and public replay")
    return {**{k: record[k] for k in ("game_start", "decision", "world_seed", "id_seed", "anchor", "replay")}, "visits": visits}


def _roots(result, cards, visits, calls, minimum_visits, expected_budget):
    roots, script = result.get("roots"), result.get("target_script")
    if not isinstance(roots, list) or not isinstance(script, list) or not script:
        raise ValueError("arrangement lacks original roots or target script")
    root_index = accounted = 0
    stages = []
    for frame in script:
        stage, possible, choices = frame.get("stage"), frame.get("possible"), frame.get("choices")
        minimum, maximum = frame.get("minimum"), frame.get("maximum")
        if (stage not in ("partition", "top_order", "bottom_order") or not isinstance(possible, list)
                or len(set(possible)) != len(possible) or not set(possible) <= set(cards)
                or not isinstance(choices, list) or type(minimum) is not int or type(maximum) is not int
                or not (minimum == 0 and maximum == len(cards) if stage == "partition" else minimum == maximum == 1)):
            raise ValueError("arrangement original callback script is invalid")
        stages.append(stage)
        remaining = set(possible)
        selected = 0
        for i, choice in enumerate(choices):
            options = remaining | ({None} if selected >= minimum else set())
            if choice not in options or not remaining or selected >= maximum:
                raise ValueError("arrangement target script changed original legality")
            if len(options) > 1:
                if root_index >= len(roots):
                    raise ValueError("arrangement target script lacks search work")
                root = roots[root_index]
                actual, neural = root.get("root_visits"), root.get("neural_calls")
                if (root.get("index") != root_index or type(root.get("index")) is not int
                        or root.get("type") != "CHOOSE_TARGET" or root.get("stage") != stage
                        or root.get("selected") != choice or root.get("search_budget") != expected_budget
                        or root.get("requested_minimum") != (visits if minimum_visits else 0)
                        or type(actual) is not int or actual < (visits if minimum_visits else 1)
                        or type(neural) is not int or neural <= 0):
                    raise ValueError("arrangement root did not complete its original search budget")
                children = root.get("children")
                if not isinstance(children, list) or {c.get("action") for c in children} != options or len(children) != len(options):
                    raise ValueError("arrangement root lost or aliased an original target branch")
                spent = 0
                for child in children:
                    n, discarded = child.get("visits"), child.get("discarded_visits", 0)
                    pruned, masked = child.get("pruned", False), child.get("selection_masked", False)
                    if (type(n) is not int or not 0 <= n <= actual or type(discarded) is not int or not 0 <= discarded <= actual
                            or type(pruned) is not bool or type(masked) is not bool or pruned and masked
                            or not masked and discarded != 0 or (pruned or masked) and (n != 0 or child.get("value") is not None)
                            or not (pruned or masked) and (type(child.get("value")) not in (int, float) or not math.isfinite(child["value"]))):
                        raise ValueError("arrangement root statistics are invalid")
                    spent += n + discarded
                chosen = next(c for c in children if c["action"] == choice)
                if spent != actual or chosen["visits"] <= 0 or chosen["visits"] != max(c["visits"] for c in children):
                    raise ValueError("arrangement work does not support its chosen branch")
                root_index += 1
                accounted += neural
            if choice is None:
                if i != len(choices) - 1:
                    raise ValueError("arrangement script continues after STOP")
            else:
                remaining.remove(choice)
                selected += 1
        if remaining and selected < maximum and (not choices or choices[-1] is not None):
            raise ValueError("arrangement script stops before original completion")
    if root_index != len(roots) or accounted != calls or stages[0] != "partition" or stages.count("partition") != 1:
        raise ValueError("arrangement has unaccounted work or changed callback order")


def validate(decision, result, visits, calls, *, minimum_visits=True, expected_budget=None):
    purpose, cards, _ = initial(decision)
    expected_budget = expected_budget or {"kind": "minimum_root_visits_until_legal_future", "requested": visits}
    if (result.get("decision_sha256") != decision_hash(decision) or result.get("arrangement") != purpose
            or result.get("cards") != cards or type(result.get("neural_calls")) is not int or result["neural_calls"] != calls
            or result.get("search_budget") != expected_budget):
        raise ValueError("arrangement result is stale or changed its work identity")
    flags = result.get("world_flags")
    if not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("horizon:", "unsupported:")) for f in flags):
        raise ValueError("arrangement exceeded its permitted world envelope")
    destinations, order = result.get("destinations"), result.get("order")
    away = "graveyard" if purpose == "surveil" else "bottom"
    if (not isinstance(destinations, dict) or set(destinations) != set(cards) or set(destinations.values()) - {"top", away}
            or not isinstance(order, list) or len(order) != len(cards) or set(order) != set(cards)
            or [destinations[c] for c in order] != sorted((destinations[c] for c in order), key=lambda d: d != "top")):
        raise ValueError("arrangement did not place each visible card exactly once")
    _roots(result, cards, visits, calls, minimum_visits, expected_budget)
    script = result["target_script"]
    moved = [c for c in script[0]["choices"] if c is not None]
    if set(moved) != {c for c in cards if destinations[c] == away} or set(script[0]["possible"]) != set(cards):
        raise ValueError("arrangement partitions differ from original target choices")
    expected_order = []
    expected_stages = ["partition"]
    for destination, stage in ((away, "bottom_order"), ("top", "top_order")):
        members = {c for c in cards if destinations[c] == destination}
        frames = [f for f in script[1:] if f["stage"] == stage]
        if destination == away and purpose == "surveil":
            if frames:
                raise ValueError("surveil invented a graveyard order search")
            continue
        if len(frames) != max(0, len(members) - 1):
            raise ValueError("arrangement changed original placement callback count")
        chosen = []
        for frame in frames:
            if set(frame["possible"]) != members or len(frame["choices"]) != 1 or frame["choices"][0] not in members:
                raise ValueError("arrangement placement differs from original remaining cards")
            pick = frame["choices"][0]
            chosen.append(pick)
            members.remove(pick)
        chosen.extend(members)
        if destination == "top":
            chosen.reverse()
            expected_order = chosen + expected_order
        else:
            expected_order.extend(chosen)
        expected_stages.extend([stage] * len(frames))
    if purpose == "surveil":
        expected_order.extend(moved)
    if order != expected_order or [f["stage"] for f in script] != expected_stages:
        raise ValueError("arrangement wire order differs from original physical placement")


def result(record, value, visits, calls, **kwargs):
    validate(record["decision"], value, visits, calls, **kwargs)
    proof = {"earlier": len(record["replay"]["earlier"]), "priority_passes": len(record["replay"]["priority_passes"]),
             "observation_identical": True}
    if value.get("replay") != proof or value.get("replay", {}).get("observation_identical") is not True:
        raise ValueError("arrangement did not confirm the complete public replay")
    return value


class ArrangementPlan:
    def __init__(self, decision, value, *, visits, minimum_visits=True, expected_budget=None):
        validate(decision, value, visits, value.get("neural_calls"), minimum_visits=minimum_visits, expected_budget=expected_budget)
        self.initial, self.value = copy.deepcopy(decision), copy.deepcopy(value)
        self.purpose, self.cards, self.refs = initial(decision)
        self.group = CombatPlan._group(decision)
        self.next_index, self.failed = 0, False

    @property
    def complete(self):
        return self.next_index == self.group["substep_count"]

    def history(self):
        return {key: copy.deepcopy(self.value[key]) for key in PLAN_FIELDS}

    def select(self, decision):
        if self.failed or self.complete:
            raise ValueError("arrangement plan is complete or failed")
        try:
            group = CombatPlan._group(decision)
            step, n = self.next_index, len(self.cards)
            context, original_context = decision.get("context", {}), self.initial["context"]
            if (group["group_id"] != self.group["group_id"] or group["substep_count"] != 2 * n - 1
                    or group["substep_index"] != step or decision.get("seat_step") != self.initial["seat_step"] + step
                    or decision.get("acting_seat") != self.initial["acting_seat"] or context.get("rewind") is not False
                    or context.get("source") != original_context.get("source")
                    or decision.get("observation") != self.initial["observation"]):
                raise ValueError("arrangement group changed, skipped or rewound")
            away = "graveyard" if self.purpose == "surveil" else "bottom"
            selected = None
            keys, ids = set(), set()
            for candidate in decision["candidates"]:
                cid, action = candidate.get("candidate_id"), candidate.get("semantic", {})
                if type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in ids:
                    raise ValueError("arrangement candidate id is invalid or aliased")
                ids.add(cid)
                if action.get("source") != original_context.get("source"):
                    raise ValueError("arrangement source changed")
                if step < n:
                    key = action.get("destination")
                    if (action.get("kind") != "arrange_card" or action.get("purpose") != self.purpose
                            or action.get("card_count") != n or action.get("card_index") != step
                            or action.get("card") != self.refs[self.cards[step]] or key not in ("top", away)):
                        raise ValueError("arrangement partition menu changed")
                    wanted = self.value["destinations"][self.cards[step]]
                    allowed = {"top", away}
                else:
                    position = step - n
                    ref = action.get("item", {}).get("object", {})
                    key = ref.get("object_id")
                    wanted = self.value["order"][position]
                    destination = self.value["destinations"][wanted]
                    allowed = {c for c in self.value["order"][position:] if self.value["destinations"][c] == destination}
                    if (action.get("kind") != "order_pick" or action.get("purpose") != "arrangement"
                            or action.get("position") != position or action.get("count") != n
                            or key not in allowed or ref != self.refs.get(key)):
                        raise ValueError("arrangement order menu changed")
                if key in keys:
                    raise ValueError("arrangement aliases a choice")
                keys.add(key)
                if key == wanted:
                    selected = {"candidate_id": cid, "semantic_echo": action}
            if keys != allowed or selected is None:
                raise ValueError("original arrangement choice is unoffered")
            self.next_index += 1
            return selected
        except BaseException:
            self.failed = True
            raise
