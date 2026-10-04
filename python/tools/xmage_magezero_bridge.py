"""Use MageZero search and combat on one serial, owned 128-slot model pipe."""
from __future__ import annotations

from xmage_neural_rpc import NeuralSession
from xmage_magezero_search import search_request, search_result
from xmage_magezero_combat import combat_request, combat_result

READY = {"ready": True, "search": "magezero-v02-original-mixed",
         "operations": ["search", "combat"], "policy_width": 128}


class BridgeSession(NeuralSession):
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)
        if getattr(model, "architecture", None) != "magezero-v02":
            self.failed = True
            self.close()
            raise ValueError("MageZero mixed bridge needs its own pinned 128-slot checkpoint")

    def choose(self, record: dict, *, settings: dict, timeout_s: float) -> dict:
        try:
            request = search_request(record, settings)
            return self.exchange({**request, "operation": "search"}, timeout_s=timeout_s,
                                 validate=lambda result, calls: search_result(record, result, request["settings"], calls))
        except BaseException:
            self.failed = True
            self.close()
            raise

    def plan(self, record: dict, *, settings: dict, timeout_s: float) -> dict:
        try:
            request = combat_request(record, settings)
            return self.exchange({**request, "operation": "combat"}, timeout_s=timeout_s,
                                 validate=lambda result, calls: combat_result(record, result, request["settings"], calls))
        except BaseException:
            self.failed = True
            self.close()
            raise
