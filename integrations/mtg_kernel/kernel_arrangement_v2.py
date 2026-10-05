"""Fixed 2n-1 actor-visible arrangements over the private kernel bridge.

All picks are buffered, including forced partitions and singleton ordering
picks. Only a completed plan can be bound to the legacy native choices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from kernel_observation_v2 import native_key, normalized_zones, legacy_id

DESTINATIONS = ("top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1")


class ArrangementError(ValueError):
    pass


class Arrangement:
    def __init__(self, cards: tuple[dict, ...], *, source: dict | None, purpose: str,
                 destinations: tuple[tuple[str, ...], ...], hand_minimum=0, hand_maximum=None):
        if not cards or len(cards) != len(destinations):
            raise ArrangementError("arrangement needs one destination set per looked-at card")
        if len({card["object_id"] for card in cards}) != len(cards):
            raise ArrangementError("looked-at cards must have distinct current IDs")
        if any(not options or len(set(options)) != len(options) or any(d not in DESTINATIONS for d in options)
               for options in destinations):
            raise ArrangementError("invalid arrangement destinations")
        if purpose not in ("scry", "dig", "look_at_top"):
            raise ArrangementError("unsupported kernel arrangement purpose")
        self.cards, self.source, self.purpose = cards, source, purpose
        self.destinations = destinations
        self.minimum = hand_minimum
        self.maximum = len(cards) if hand_maximum is None else hand_maximum
        if not 0 <= self.minimum <= self.maximum <= len(cards):
            raise ArrangementError("invalid hand partition bounds")
        self.partition = []
        self.order = []

    @property
    def substep_count(self):
        return 2 * len(self.cards) - 1

    @property
    def substep_index(self):
        return len(self.partition) + len(self.order)

    @property
    def finished(self):
        return self.substep_index == self.substep_count

    def _partition_choices(self):
        count = len(self.partition)
        chosen_hand = self.partition.count("hand")
        result = []
        for destination in self.destinations[count]:
            after = chosen_hand + (destination == "hand")
            later = self.destinations[count + 1:]
            forced = sum(options == ("hand",) for options in later)
            possible = sum("hand" in options for options in later)
            if after + forced <= self.maximum and after + possible >= self.minimum:
                result.append(destination)
        if not result:
            raise ArrangementError("partition has no valid completion")
        return result

    def _order_choices(self):
        for destination in DESTINATIONS:
            remaining = [card for card, chosen in zip(self.cards, self.partition)
                         if chosen == destination and card["object_id"] not in self.order]
            if remaining:
                # Identity order only. Names and IDs are licensed in this look.
                return sorted(remaining, key=lambda card: (card["card_name"], card["object_id"]))
        raise ArrangementError("ordering is already complete")

    def semantics(self):
        if self.finished:
            raise ArrangementError("arrangement is already complete")
        if len(self.partition) < len(self.cards):
            index = len(self.partition)
            return [{"kind": "arrange_card", "source": self.source, "purpose": self.purpose,
                     "card": self.cards[index], "card_index": index, "card_count": len(self.cards),
                     "destination": destination} for destination in self._partition_choices()]
        return [{"kind": "order_pick", "source": self.source, "purpose": "arrangement", "item": {"object": card},
                 "position": len(self.order), "count": len(self.cards)} for card in self._order_choices()]

    def choose(self, candidate_id):
        semantics = self.semantics()
        if type(candidate_id) is not int or not 0 <= candidate_id < len(semantics):
            raise ArrangementError("arrangement candidate is out of range")
        semantic = semantics[candidate_id]
        if semantic["kind"] == "arrange_card":
            self.partition.append(semantic["destination"])
        else:
            self.order.append(semantic["item"]["object"]["object_id"])
        return self.finished

    def result(self):
        if not self.finished:
            raise ArrangementError("arrangement is unfinished")
        # The last card of the whole arrangement is implied. Singleton picks
        # of earlier destination blocks have already been explicitly posed.
        ordered = self.order + [card["object_id"] for card in self._order_choices()]
        if len(ordered) != len(self.cards) or len(set(ordered)) != len(self.cards):
            raise ArrangementError("ordering is not a complete permutation")
        destinations = {card["object_id"]: destination for card, destination in zip(self.cards, self.partition)}
        return {destination: tuple(object_id for object_id in ordered if destinations[object_id] == destination)
                for destination in DESTINATIONS}


def native_arrangement(raw, support, projection):
    raw = normalized_zones(raw)
    choice = support.get("choice", {})
    purpose = choice.get("purpose")
    if purpose not in ("scry", "look_select", "look", "reveal_partition"):
        raise ArrangementError("native choice is not a supported library arrangement")
    effect = raw["projection"]["engine_context"]["pending_effect"]
    target_choice = effect["choice"]
    if target_choice["choice_kind"] != "targets" or target_choice["selected_targets"]:
        raise ArrangementError("arrangement must begin at an untouched native look")
    count = support.get("look_card_count")
    owner = support.get("look_owner")
    if type(count) is not int or count < 1 or owner not in ("p0", "p1"):
        raise ArrangementError("native look dimensions are absent")
    known = raw["known_library_cards"][0 if owner == "p0" else 1]
    prefix = sorted((entry for entry in known if entry["position"] < count), key=lambda entry: entry["position"])
    if len(prefix) != count or [entry["position"] for entry in prefix] != list(range(count)):
        raise ArrangementError("look prefix is not fully present in actor knowledge")
    cards = tuple(projection.stable_ref(entry["card"]["stable"]) for entry in prefix)
    if any(card is None for card in cards):
        raise ArrangementError("looked-at card has no current neutral reference")
    source = projection.effect_ref(effect, support)
    if purpose == "scry":
        options = (("top", "bottom"),) * count
        if choice["stage"] != "partition":
            raise ArrangementError("scry must begin before native partitioning")
        minimum, maximum = 0, count
    elif purpose == "look":
        options = (("top",),) * count
        minimum, maximum = 0, count
    else:
        matching = {native_key(target["object"]) for target in target_choice["legal_targets"]
                    if target["target_kind"] == "object"}
        if purpose == "reveal_partition":
            options = tuple(("hand",) if native_key(entry["card"]["stable"]) in matching else ("graveyard",)
                            for entry in prefix)
        else:
            options = tuple(("bottom", "hand") if native_key(entry["card"]["stable"]) in matching else ("bottom",)
                            for entry in prefix)
        if choice["stage"] == "partition":
            minimum, maximum = target_choice["min_targets"], target_choice["max_targets"]
        elif choice["stage"] == "bottom_order":
            # A root bottom ordering means no matching result was available.
            options = (("bottom",),) * count
            minimum, maximum = 0, 0
        else:
            raise ArrangementError("dig must begin before native choices")
    plan = Arrangement(cards, source=source, purpose={"look_select": "dig", "reveal_partition": "dig", "look": "look_at_top"}.get(purpose, purpose),
                       destinations=options, hand_minimum=minimum, hand_maximum=maximum)
    bindings = {card["object_id"]: legacy_id(entry["card"]["stable"]) for card, entry in zip(cards, prefix)}
    return plan, bindings


@dataclass(frozen=True)
class NativeArrangementBinding:
    game_id: str
    instance: str
    purpose: str
    cards: Mapping[str, str]


def native_arrangement_binding(root, cards):
    support = root["extensions"]["x_kernel_v2_support"]
    instance = support.get("effect_instance")
    purpose = support.get("choice", {}).get("purpose")
    if not isinstance(instance, str) or purpose not in ("scry", "look_select", "look", "reveal_partition", "mill", "put_on_top", "discard_order"):
        raise ArrangementError("arrangement lacks a captured native effect")
    return NativeArrangementBinding(root["game_id"], instance, purpose, dict(cards))


def native_arrangement_pick(view, result, binding):
    """One exact internal native pick for a completed neutral arrangement."""
    support = view["extensions"]["x_kernel_v2_support"]
    purpose, stage = support["choice"]["purpose"], support["choice"]["stage"]
    if (view.get("game_id"), support.get("effect_instance"), purpose) != (
        binding.game_id, binding.instance, binding.purpose
    ):
        raise ArrangementError("completed arrangement belongs to another game or effect")
    raw = json_observation(view)
    if purpose == "discard_order":
        selected, wanted = support["discard_selected_count"], result["graveyard"]
    else:
        choice = raw["projection"]["engine_context"]["pending_effect"]["choice"]
        selected = len(choice["selected_targets"])
    if purpose == "discard_order":
        pass
    elif purpose == "put_on_top":
        wanted = tuple(reversed(result["top"]))
        selected = support["hand_to_top"]["selected_count"]
    elif purpose == "mill":
        wanted = result["graveyard"]
    elif stage == "partition":
        wanted = result["bottom" if purpose == "scry" else "hand"]
    else:
        wanted = result["graveyard" if purpose == "reveal_partition" else "bottom" if stage == "bottom_order" else "top"]
        if purpose == "look":
            wanted = tuple(reversed(wanted))  # old chooser puts its first pick deepest
    if selected > len(wanted):
        raise ArrangementError("native arrangement exceeds the captured completed plan")
    candidate_object = None if selected == len(wanted) else binding.cards[wanted[selected]]
    allowed = set(view["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"])
    matching = []
    for candidate in view["candidates"]:
        semantic = candidate["semantic"]
        if candidate["candidate_id"] not in allowed:
            continue
        if candidate_object is None:
            matches = semantic["kind"] == "finish_effect_selection"
        else:
            matches = ((semantic["kind"] == "discard" and len(semantic["cards"]) == 1
                        and semantic["cards"][0]["object_id"] == candidate_object) if purpose == "discard_order" else
                       semantic["kind"] == "choose_effect_target" and semantic["target"].get("object", {}).get("object_id") == candidate_object)
        if matches:
            matching.append(candidate["candidate_id"])
    if len(matching) != 1:
        raise ArrangementError("completed neutral arrangement does not bind to one native row")
    return matching[0]


def json_observation(view):
    import json
    return json.loads(view["extensions"]["x_kernel_v5"]["observation_json"])
