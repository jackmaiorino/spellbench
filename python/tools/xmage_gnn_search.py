"""Bind the DraftZero FDN graph network's played search to offered decisions.

One serial Java pipe (GnnBridgeMain) runs priority, replayed callback and combat
roots; each graph state it encodes is scored by the confined network
(xmage_gnn_model.GraphInference). The settings are the played configuration's
(danieljbrooks/draft-zero@2a461518, BenchPlayer with method "pimc"), with only
the simulation count chosen per entrant. Complete-game qualification and
ratings are separate requirements.
"""
from __future__ import annotations

import copy
import json
import sys

from xmage_neural_agent import NeuralAgent, PublicHistory
from xmage_neural_combat import (CombatPlan as PermittedPlan, combat_request as checked_combat_request,
                                 select_candidate, validate_result as validate_combat)
from xmage_neural_decisions import close_resources
from xmage_neural_rpc import NeuralSession
from xmage_neural_search import (root_family, search_request as checked_request,
                                 search_result as checked_result)

PROFILE = "draftzero-gnn-pimc-tree-v1"
READY = {"ready": True, "search": "draftzero-gnn-pimc-mixed", "operations": ["search", "combat"], "profile": PROFILE}
PLAYED = {"profile": PROFILE, "cPuct": "1", "priorTemp": "1.5", "priorBonus": "0.1", "discount": "0.99",
          "discountUnit": "ply", "leaf": "net", "opponentPriors": "uniform", "timeoutSeconds": "900",
          "maxIterations": 0}


def played_settings(simulations: int) -> dict:
    return validate_settings({**PLAYED, "simulations": simulations})


def validate_settings(settings: dict) -> dict:
    if not isinstance(settings, dict) or set(settings) != {*PLAYED, "simulations"}:
        raise ValueError("the graph network needs every explicit setting of its played search")
    if any(settings[k] != v or type(settings[k]) is not type(v) for k, v in PLAYED.items()):
        raise ValueError("graph network setting differs from its played configuration")
    if type(settings["simulations"]) is not int or not 2 <= settings["simulations"] <= 1000:
        raise ValueError("graph network simulations must be 2..1000")
    return copy.deepcopy(settings)


def budget(settings: dict) -> dict:
    return {"kind": "graph_tree_simulations", "requested": settings["simulations"],
            "timeout_seconds": settings["timeoutSeconds"]}


def _receipts(result: dict, calls: int) -> None:
    receipts = result.get("graph_search")
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("graph search returned no root receipts")
    total = 0
    for receipt in receipts:
        if (not isinstance(receipt, dict) or type(receipt.get("network_calls")) is not int
                or receipt["network_calls"] < 1 or type(receipt.get("simulations")) is not int
                or receipt.get("type") not in ("PRIORITY", "CHOOSE_TARGET", "CHOOSE_USE", "CHOOSE_NUM", "MAKE_CHOICE")):
            raise ValueError("graph search root receipt is invalid")
        total += receipt["network_calls"]
    if total != calls:
        raise ValueError("graph search has unaccounted network calls")


UNSUPPORTED = ("search world is unsupported: ", "callback anchor is unsupported: ", "combat world is unsupported: ")


def declining(decision: dict) -> dict:
    """The kit front's fallback (Front.fallback without a ranking): the declining candidate, else the first."""
    candidates = decision["candidates"]
    for candidate in candidates:
        sem = candidate["semantic"]
        kind = sem.get("kind", "")
        if (kind == "pass" or kind.startswith("finish_")
                or (kind == "choose_boolean" and sem.get("value") is False)
                or sem.get("pay") is False or sem.get("cast_it") is False
                or (kind == "declare_attack" and sem.get("defender") is None)
                or (kind == "declare_block" and sem.get("attacker") is None)):
            return {"candidate_id": candidate["candidate_id"], "semantic_echo": copy.deepcopy(sem)}
    return {"candidate_id": candidates[0]["candidate_id"], "semantic_echo": copy.deepcopy(candidates[0]["semantic"])}


def unsupported_result(record: dict, result: dict, calls: int) -> dict:
    """A world the kit does not search (horizon or unsupported flag), refused before any network call."""
    refusal = result.get("unsupported")
    if (set(result) != {"unsupported", "neural_calls"} or not isinstance(refusal, str)
            or not refusal.startswith(UNSUPPORTED) or result["neural_calls"] != 0 or calls != 0):
        raise ValueError("graph search reported an invalid unsupported world")
    flag = refusal.split(": ", 1)[1]
    if not flag.startswith(("horizon:", "unsupported:")):
        raise ValueError("graph search refused a world without a horizon or unsupported flag")
    return {"selection": declining(record["decision"]), "neural_calls": 0, "world_flags": [flag],
            "fallback": "kit_declining_unsearched_world", "unsupported": refusal}


class DecliningPlan:
    """The kit's declining answer for every declaration of a combat group it does not search."""
    def __init__(self, decision: dict, result: dict):
        self.result = copy.deepcopy(result)
        self.group = PermittedPlan._group(decision)
        if self.group["substep_index"] != 0:
            raise ValueError("combat plan needs the initial group substep")
        self.first_step, self.next_index, self.failed = decision.get("seat_step"), 0, False

    @property
    def complete(self):
        return self.next_index == self.group["substep_count"]

    def select(self, decision: dict) -> dict:
        if self.failed or self.complete:
            raise ValueError("combat plan is complete or failed")
        group = PermittedPlan._group(decision)
        if (group["group_id"] != self.group["group_id"] or group["substep_count"] != self.group["substep_count"]
                or group["substep_index"] != self.next_index
                or decision.get("seat_step") != self.first_step + self.next_index
                or decision.get("context", {}).get("rewind") is not False):
            self.failed = True
            raise ValueError("combat declaration group is stale, skipped or rewound")
        self.next_index += 1
        return declining(decision)


def report_unmatched(result: dict) -> dict:
    """BenchPlayer ignores searched options no original option matches; keep their keys visible."""
    odd = [r for r in result.get("graph_search", []) if isinstance(r, dict) and r.get("unmatched_options")]
    if odd:
        print(json.dumps({"event": "graph_unmatched_options", "receipts": odd}, separators=(",", ":"),
                         allow_nan=False)[:8000], file=sys.stderr, flush=True)
    return result


def search_request(record: dict, settings: dict) -> dict:
    settings = validate_settings(settings)
    decision = record.get("decision", {})
    observation = decision.get("observation", {})
    seat = record.get("game_start", {}).get("seat")
    if (decision.get("context", {}).get("rewind") is not False
            or seat not in ("p0", "p1") or observation.get("viewer") != seat
            or decision.get("acting_seat") != seat):
        raise ValueError("graph search requires a non-rewound own decision")
    root_family(decision)
    request = checked_request(record, settings["simulations"])
    request.pop("visits")
    return {**request, "settings": settings}


def search_result(record: dict, result: dict, settings: dict, calls: int) -> dict:
    settings = validate_settings(settings)
    if (validate_settings(result.get("settings")) != settings or "policy_width" in result
            or result.get("search_budget") != budget(settings) or type(calls) is not int or calls < 1):
        raise ValueError("graph search changed its settings or stopping rule")
    # Each root search runs its full simulation count; root visits omit removed dead options.
    checked_result(record, result, settings["simulations"], calls, expected_budget=budget(settings),
                   source_label="graph network", minimum_visits=False)
    _receipts(result, calls)
    if len(result["graph_search"]) != 1:
        raise ValueError("a search root reports exactly one graph search")
    return result


def combat_request(record: dict, settings: dict) -> dict:
    settings = validate_settings(settings)
    request = checked_combat_request(record, settings["simulations"])
    decision = request["decision"]
    observation = decision.get("observation", {})
    seat = request["game_start"].get("seat")
    attacking = decision["candidates"][0]["semantic"]["kind"] == "declare_attack"
    if (seat not in ("p0", "p1") or observation.get("viewer") != seat
            or decision.get("acting_seat") != seat or decision.get("context", {}).get("rewind") is not False
            or (observation.get("active_seat") == seat) != attacking
            or observation.get("phase_step") != ("declare_attackers" if attacking else "declare_blockers")
            or PermittedPlan._group(decision)["substep_index"] != 0):
        raise ValueError("graph combat requires an initial non-rewound own declaration")
    request.pop("visits")
    return {**request, "settings": settings}


def combat_result(record: dict, result: dict, settings: dict, calls: int) -> dict:
    settings = validate_settings(settings)
    if (validate_settings(result.get("settings")) != settings or "policy_width" in result
            or result.get("search_budget") != budget(settings) or type(calls) is not int or calls < 0):
        raise ValueError("graph combat changed its settings or stopping rule")
    validate_combat(record["decision"], result, settings["simulations"], calls,
                    minimum_visits=False, expected_budget=budget(settings))
    if calls:
        _receipts(result, calls)
    if len(result.get("graph_search", [])) != len(result["roots"]):
        raise ValueError("graph combat receipts differ from its roots")
    return {**result, "selection": select_candidate(record["decision"], result)}


class CombatPlan(PermittedPlan):
    def __init__(self, decision: dict, result: dict, *, settings: dict):
        settings = validate_settings(settings)
        combat_result({"decision": decision}, result, settings, result.get("neural_calls"))
        super().__init__(decision, result, visits=settings["simulations"], minimum_visits=False,
                         expected_budget=budget(settings))


class BridgeSession(NeuralSession):
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)
        if getattr(model, "architecture", None) != "draftzero-gnn":
            self.failed = True
            self.close()
            raise ValueError("the graph search pipe needs the confined graph network")

    def choose(self, record: dict, *, settings: dict, timeout_s: float) -> dict:
        try:
            request = search_request(record, settings)
            return self.exchange({**request, "operation": "search"}, timeout_s=timeout_s,
                                 validate=lambda result, calls: unsupported_result(record, result, calls)
                                 if "unsupported" in result else report_unmatched(
                                     search_result(record, result, request["settings"], calls)))
        except BaseException:
            self.failed = True
            self.close()
            raise

    def plan(self, record: dict, *, settings: dict, timeout_s: float) -> dict:
        try:
            request = combat_request(record, settings)
            return self.exchange({**request, "operation": "combat"}, timeout_s=timeout_s,
                                 validate=lambda result, calls: unsupported_result(record, result, calls)
                                 if "unsupported" in result else report_unmatched(
                                     combat_result(record, result, request["settings"], calls)))
        except BaseException:
            self.failed = True
            self.close()
            raise


def profile(settings: dict) -> dict:
    settings = validate_settings(settings)
    return {
        "name": "draftzero-gnn-permitted-world-pimc-tree-v1",
        "architecture": "draftzero-gnn",
        "tree": "BenchSearch one-world tree, fresh per received root",
        "search_budget": budget(settings),
        "settings": settings,
        "search_clock": "shared host decision clock; abort incomplete work",
        "opponent_hand_encoding": False,
        "world": "permitted sampled world (one deal; no second re-deal)",
        "mulligan": "keep (mulligans were off in the published games)",
        "unheaded_decisions": "MageZero v0.2 tree with uniform priors through the same graph search",
        "unsearched_worlds": "kit policy: a horizon or unsupported world is not searched; the declining candidate answers",
        "unsearched_families": "decisions no graph search root supports (trigger order, for one) take the kit's fallback: "
                               "the declining candidate, else the first",
        "callback_tolerances": "anchor-known characteristic gaps; which identical permanent a replayed payment tapped; "
                               "own draws the callback shows are pinned to the sampled library's top",
        "full_game_qualified": False,
    }


class SettingsSession:
    """Keep the frontend's simulation count bound to every graph operation."""
    def __init__(self, session, settings):
        self.session, self.model = session, session.model
        self.settings = validate_settings(settings)
        if getattr(self.model, "architecture", None) != "draftzero-gnn":
            failure = ValueError("graph frontend requires the confined graph network")
            close_resources(session, failure=failure)
            raise failure

    def _run(self, operation, record, visits, timeout_s):
        if type(visits) is not int or visits != self.settings["simulations"]:
            self.close()
            raise ValueError("graph frontend changed its declared simulation count")
        return operation(record, settings=copy.deepcopy(self.settings), timeout_s=timeout_s)

    def choose(self, record, *, visits, timeout_s):
        return self._run(self.session.choose, record, visits, timeout_s)

    def plan(self, record, *, visits, timeout_s):
        return self._run(self.session.plan, record, visits, timeout_s)

    def close(self):
        self.session.close()


class GraphHistory(PublicHistory):
    """PublicHistory, plus callbacks that follow this seat's own attack declarations.

    After a beginning-of-combat pass, the attack declaration group and then a
    callback (an attack trigger's target, say) arrive in the declare-attackers
    step. The Java replay re-declares the recorded group (attack_declarations)
    before the callback and compares the callback's whole observation.
    """
    def attack_group(self, decision):
        if self.anchor is None or self.anchor["selection"]["semantic_echo"].get("kind") != "pass":
            return 0
        previous, observation = self.anchor["decision"]["observation"], decision["observation"]
        if not (previous.get("phase_step") == "beginning_of_combat" and observation.get("phase_step") == "declare_attackers"
                and type(previous.get("turn")) is int and previous["turn"] == observation.get("turn")
                and previous.get("active_seat") == self.seat and not previous.get("stack")):
            return 0
        count, group = 0, None
        for entry in self.earlier:
            candidates = entry["decision"].get("candidates", [])
            if not candidates or any(c.get("semantic", {}).get("kind") != "declare_attack" for c in candidates):
                break
            step = entry["decision"].get("group", {})
            if group is None:
                group = step
            if (step.get("group_id") != group.get("group_id") or step.get("substep_index") != count
                    or step.get("substep_count") != group.get("substep_count")):
                return 0
            count += 1
        return count if group is not None and count == group.get("substep_count") else 0

    def callback(self, decision):
        attacks = self.attack_group(decision)
        if not attacks:
            record = super().callback(decision)
            record["replay"].update(characteristic_gaps=True, fungible_tapped=True, visible_draws=True)
            return record
        other = "p1" if self.seat == "p0" else "p0"
        passed = self.anchor["decision"]["observation"].get("passed_seats")
        if not isinstance(passed, list) or any(p not in ("p0", "p1") for p in passed):
            raise ValueError("callback anchor needs public passed-seat facts")
        return {"anchor": copy.deepcopy(self.anchor),
                "replay": {"priority_passes": [] if other in passed else [other],
                           "earlier": copy.deepcopy(self.earlier), "attack_declarations": attacks,
                           "characteristic_gaps": True, "fungible_tapped": True, "visible_draws": True}}


class GraphAgent(NeuralAgent):
    """One graph search session per public game."""
    history_factory = GraphHistory
    unsearched_family = staticmethod(declining)
    def __init__(self, factory, *, checkpoint: str, settings: dict, audit=None):
        declared = validate_settings(settings)

        def bound_factory():
            return SettingsSession(factory(), declared)

        def plan_factory(decision, result, *, visits):
            if type(visits) is not int or visits != declared["simulations"]:
                raise ValueError("graph combat changed its declared simulation count")
            if result.get("fallback") == "kit_declining_unsearched_world":
                return DecliningPlan(decision, result)
            return CombatPlan(decision, result, settings=declared)

        super().__init__(bound_factory, checkpoint=checkpoint, visits=declared["simulations"],
                         audit=audit, profile=profile(declared), plan_factory=plan_factory)
