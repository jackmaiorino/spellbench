"""Switch supported original search and combat roots on one warm private pipe.

This joins the qualified decision components. Pregame, transition history and
remaining callbacks must still be completed before this can serve full games.
"""
from __future__ import annotations

from xmage_neural_rpc import NeuralSession
from xmage_neural_search import search_request, search_result
from xmage_neural_combat import combat_request, combat_result

READY = {"ready": True, "search": "draftzero-exp1-original-mixed",
         "operations": ["search", "combat"]}


class BridgeSession(NeuralSession):
    """Share checkpoint identity, request sequence, failure and cleanup state."""
    def __init__(self, peer, model):
        super().__init__(peer, model, ready=READY)

    def choose(self, record: dict, *, visits: int, timeout_s: float) -> dict:
        request = search_request(record, visits)
        return self.exchange({**request, "operation": "search"}, timeout_s=timeout_s,
                             validate=lambda result, calls: search_result(record, result, visits, calls))

    def plan(self, record: dict, *, visits: int, timeout_s: float) -> dict:
        request = combat_request(record, visits)
        return self.exchange({**request, "operation": "combat"}, timeout_s=timeout_s,
                             validate=lambda result, calls: combat_result(record, result, visits, calls))
