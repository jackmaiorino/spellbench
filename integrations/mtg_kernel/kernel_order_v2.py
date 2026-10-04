"""Sequential trigger ordering over the native legal permutation rows."""
from __future__ import annotations


class TriggerOrder:
    def __init__(self, root, projection):
        ids = root["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"]
        semantics = [root["candidates"][i]["semantic"] for i in ids]
        sources = semantics[0]["pending_sources"]
        if len(sources) < 2 or any(s["kind"] != "order_triggers" or s["pending_sources"] != sources for s in semantics):
            raise ValueError("native ordering lacks one common trigger list")
        self.items = [{"trigger": {"source": projection.legacy_ref(source, nullable=True),
            "source_name": source["card_name"] if projection.legacy_ref(source, nullable=True) else None,
            "ability_index": None, "event_objects": [], "instance": i, "label": None}}
            for i, source in enumerate(sources)]
        self.permutations = {tuple(s["order"]): i for i, s in zip(ids, semantics)}
        if any(sorted(order) != list(range(len(sources))) for order in self.permutations):
            raise ValueError("native trigger row is not a complete permutation")
        self.prefix = ()

    @property
    def substep_count(self):
        return len(self.items) - 1

    @property
    def substep_index(self):
        return len(self.prefix)

    def choices(self):
        return sorted({order[len(self.prefix)] for order in self.permutations if order[:len(self.prefix)] == self.prefix})

    def semantics(self):
        return [{"kind": "order_pick", "source": None, "purpose": "triggers", "item": self.items[index],
                 "position": len(self.prefix), "count": len(self.items)} for index in self.choices()]

    def choose(self, candidate):
        self.prefix += (self.choices()[candidate],)
        return len(self.prefix) == self.substep_count

    def result(self):
        matches = [candidate for order, candidate in self.permutations.items() if order[:len(self.prefix)] == self.prefix]
        if len(self.prefix) != self.substep_count or len(matches) != 1:
            raise ValueError("trigger order is not complete")
        return matches[0]
