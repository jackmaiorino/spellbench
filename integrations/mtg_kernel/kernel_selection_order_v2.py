"""Buffered fixed selections and independent n-1 ordering blocks."""
from __future__ import annotations

from kernel_observation_v2 import legacy_id, normalized_zones


class SelectionOrder:
    def __init__(self, cards, *, source, count, destination, select, selection_purpose="other"):
        self.cards = tuple(cards)
        if not 1 <= count <= len(cards) or len({c["object_id"] for c in cards}) != len(cards):
            raise ValueError("selection/order dimensions are invalid")
        self.source, self.count, self.destination = source, count, destination
        self.selection_purpose = selection_purpose
        self.selected = [] if select else list(self.cards)
        self.order = []
        self.selecting = select
        if not select and count != len(cards):
            raise ValueError("pure ordering must bind its whole offered set")

    @property
    def substep_count(self):
        return self.count if self.selecting else self.count - 1

    @property
    def substep_index(self):
        return len(self.selected) if self.selecting else len(self.order)

    def choices(self):
        excluded = {c["object_id"] for c in (self.selected if self.selecting else self.order)}
        pool = self.cards if self.selecting else self.selected
        return sorted((c for c in pool if c["object_id"] not in excluded),
                      key=lambda c: (c["card_name"], c["object_id"]))

    def semantics(self):
        if self.selecting:
            return [{"kind": "select_object", "source": self.source, "purpose": self.selection_purpose,
                     "choice": {"object": c}, "selected_count": len(self.selected),
                     "minimum": self.count, "maximum": self.count} for c in self.choices()]
        return [{"kind": "order_pick", "source": self.source,
                 "purpose": "library_top" if self.destination == "top" else "other",
                 "item": {"object": c}, "position": len(self.order), "count": self.count}
                for c in self.choices()]

    def choose(self, candidate):
        choices = self.choices()
        if type(candidate) is not int or not 0 <= candidate < len(choices):
            raise ValueError("selection/order candidate is out of range")
        if self.selecting:
            self.selected.append(choices[candidate])
            if len(self.selected) == self.count:
                self.selecting = False
                return self.count == 1
            return False
        self.order.append(choices[candidate])
        return len(self.order) == self.count - 1

    def result(self):
        if self.selecting or len(self.order) != self.count - 1:
            raise ValueError("selection/order is incomplete")
        return {self.destination: tuple(c["object_id"] for c in self.order + self.choices())}


def native_selection_order(raw, support, projection, root=None):
    context = normalized_zones(raw)["projection"]["engine_context"]
    purpose = support["choice"]["purpose"]
    if purpose == "discard_order":
        if root is None or root["group"]["substep_index"] != 0:
            raise ValueError("discard selection did not begin at its root")
        allowed = root["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"]
        semantics = [root["candidates"][i]["semantic"] for i in allowed]
        if any(s["kind"] != "discard" or len(s["cards"]) != 1 for s in semantics):
            raise ValueError("discard row is not an exact single card")
        cards = [projection.legacy_ref(s["cards"][0]) for s in semantics]
        plan = SelectionOrder(cards, source=None, count=support["discard_count"],
            destination="graveyard", select=True, selection_purpose="discard")
        return plan, {c["object_id"]: s["cards"][0]["object_id"] for c, s in zip(cards, semantics)}
    effect = context["pending_effect"]
    choice = effect["choice"]
    if choice["choice_kind"] != "targets" or choice["selected_targets"]:
        raise ValueError("selection/order needs an untouched native root")
    targets = choice["legal_targets"]
    if any(t["target_kind"] != "object" for t in targets):
        raise ValueError("selection/order contains a player")
    cards = [projection.stable_ref(t["object"]) for t in targets]
    if any(c is None for c in cards):
        raise ValueError("selection/order has an unlicensed card")
    if purpose == "put_on_top":
        progress = support["hand_to_top"]
        if progress["selected_count"] != 0 or progress["total"] != progress["remaining"]:
            raise ValueError("hand-to-top declaration did not begin at its root")
        count = min(progress["remaining"], len(cards))
        destination, select = "top", True
    elif purpose == "mill":
        count = len(cards)
        if count < 2 or choice["min_targets"] != count or choice["max_targets"] != count:
            raise ValueError("graveyard ordering lacks its complete bound set")
        destination, select = "graveyard", False
    else:
        raise ValueError("unsupported selection/order purpose")
    plan = SelectionOrder(cards, source=projection.effect_ref(effect, support),
                          count=count, destination=destination, select=select)
    return plan, {c["object_id"]: legacy_id(t["object"]) for c, t in zip(cards, targets)}
