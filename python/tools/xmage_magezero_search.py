"""Bind original MageZero v0.2 search to a confined 128-slot model.

Callers must supply explicit source settings or select the diagnostic profile.
Replayed dialog roots require a saved public anchor and complete observation match.
Combat, full games and trained-weight qualification remain unfinished.
"""
from __future__ import annotations

import copy
import math
import re

from xmage_neural_rpc import NeuralSession
from xmage_neural_search import (root_family, search_request as checked_request,
                                 search_result as checked_result)

READY = {"ready": True, "search": "magezero-v02-original-search", "policy_width": 128}
ORIGINAL_DEFAULT_SETTINGS = {
    "profile": "original-source-time-or-visits", "searchBudget": 1000, "searchTimeout": "4",
    "backpropDiscount": "0.99", "priorTemp": "1.5", "priorBonus": "0.1",
    "noNoise": True, "dirichletNoiseEps": "0", "selectionTemperature": "0",
    "noPolicyPriority": True, "noPolicyTarget": True, "noPolicyUse": True, "noPolicyOpponent": True,
}
_DECIMALS = {"searchTimeout": (0, 600), "backpropDiscount": (0, 1),
             "priorTemp": (0, math.inf), "priorBonus": (0, math.inf),
             "dirichletNoiseEps": (0, 0), "selectionTemperature": (0, 0)}
_BOOLEANS = ("noNoise", "noPolicyPriority", "noPolicyTarget", "noPolicyUse", "noPolicyOpponent")


def diagnostic_settings(visits: int) -> dict:
    settings = copy.deepcopy(ORIGINAL_DEFAULT_SETTINGS)
    settings.update(profile="minimum-visits-diagnostic", searchBudget=visits, searchTimeout="600")
    for key in _BOOLEANS[1:]:
        settings[key] = False
    return validate_settings(settings)


def validate_settings(settings: dict) -> dict:
    if not isinstance(settings, dict) or set(settings) != set(ORIGINAL_DEFAULT_SETTINGS):
        raise ValueError("MageZero needs every explicit original search setting")
    if settings["profile"] not in ("original-source-time-or-visits", "minimum-visits-diagnostic"):
        raise ValueError("unsupported MageZero stopping profile")
    if type(settings["searchBudget"]) is not int or not 2 <= settings["searchBudget"] <= 1000:
        raise ValueError("MageZero visit budget must be 2..1000")
    for name, (minimum, maximum) in _DECIMALS.items():
        raw = settings[name]
        if not isinstance(raw, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", raw) is None:
            raise ValueError("MageZero decimal settings require explicit finite decimal strings")
        value = float(raw)
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError("MageZero search setting is outside its supported envelope")
        if name in ("searchTimeout", "priorTemp") and value == 0:
            raise ValueError("MageZero timeout and prior temperature must be positive")
    if any(type(settings[key]) is not bool for key in _BOOLEANS) or settings["noNoise"] is not True:
        raise ValueError("MageZero search bridge requires deterministic no-noise selection")
    if settings["profile"] == "minimum-visits-diagnostic":
        expected = {**ORIGINAL_DEFAULT_SETTINGS, "profile": "minimum-visits-diagnostic",
                    "searchBudget": settings["searchBudget"], "searchTimeout": "600"}
        expected.update({key: False for key in _BOOLEANS[1:]})
        if settings != expected:
            raise ValueError("MageZero diagnostic profile requires its exact declared settings")
    return copy.deepcopy(settings)


def budget(settings: dict) -> dict:
    kind = ("minimum_root_visits_until_legal_future" if settings["profile"] == "minimum-visits-diagnostic"
            else "original_source_time_or_visits_until_legal_future")
    return {"kind": kind, "requested": settings["searchBudget"], "timeout_seconds": settings["searchTimeout"]}


def search_request(record: dict, settings: dict) -> dict:
    settings = validate_settings(settings)
    decision = record.get("decision", {})
    observation = decision.get("observation", {})
    context = decision.get("context", {})
    seat = record.get("game_start", {}).get("seat")
    if (context.get("rewind") is not False
            or seat not in ("p0", "p1") or observation.get("viewer") != seat
            or decision.get("acting_seat") != seat):
        raise ValueError("MageZero search requires a non-rewound own decision")
    root_family(decision)
    request = checked_request(record, settings["searchBudget"])
    request.pop("visits")
    return {**request, "settings": settings}


def search_result(record: dict, result: dict, settings: dict, calls: int) -> dict:
    settings = validate_settings(settings)
    echoed = validate_settings(result.get("settings"))
    if (echoed != settings or result.get("policy_width") != 128 or type(result.get("policy_width")) is not int
            or type(calls) is not int or calls < 1):
        raise ValueError("MageZero search changed its architecture or explicit settings")
    if result.get("search_budget") != budget(settings):
        raise ValueError("MageZero search changed its original stopping rule")
    checked_result(record, result, settings["searchBudget"], calls,
                   expected_budget=budget(settings), source_label="MageZero",
                   minimum_visits=settings["profile"] == "minimum-visits-diagnostic")
    return result


class SearchSession(NeuralSession):
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)
        if getattr(model, "architecture", None) != "magezero-v02":
            self.failed = True
            self.close()
            raise ValueError("MageZero original search needs its own pinned 128-slot checkpoint")

    def choose(self, record: dict, *, settings: dict, timeout_s: float) -> dict:
        try:
            request = search_request(record, settings)
            return self.exchange(request, timeout_s=timeout_s,
                                 validate=lambda result, calls: search_result(record, result, request["settings"], calls))
        except BaseException:
            self.failed = True
            self.close()
            raise
