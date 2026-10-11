"""Retain narrowly proved, public until-end-of-turn effects for reconstruction."""
from __future__ import annotations

import copy


PROWESS = "Prowess <i>(Whenever you cast a noncreature spell, this creature gets +1/+1 until end of turn.)</i>"
DISTRACTION = "target creature gets -1/-0 until end of turn. <br>Draw a card."


def battlefield(observation):
    return {card["object_id"]: card for player in observation.get("players", [])
            for card in player.get("battlefield", []) if isinstance(card.get("object_id"), str)}


def resolution(before, after):
    """Recognize one visible stack resolution, never infer a modifier from stats alone."""
    stack = before.get("stack", [])
    if (not stack or stack[:-1] != after.get("stack", [])
            or any(before.get(key) != after.get(key) for key in ("viewer", "turn", "phase_step"))):
        return None
    top = stack[-1]
    if top.get("copy") is not False or top.get("face_down") is not False:
        return None
    if (top.get("stack_kind") == "triggered_ability" and top.get("text") == PROWESS
            and not top.get("targets")):
        kind, delta, target = "prowess", (1, 1), top.get("source") or {}
    elif (top.get("stack_kind") == "spell" and top.get("card_name") == "Fleeting Distraction"
          and top.get("text") == DISTRACTION and len(top.get("targets", [])) == 1):
        kind, delta, target = "fleeting_distraction", (-1, 0), top["targets"][0].get("object") or {}
    else:
        return None
    old, new = battlefield(before).get(target.get("object_id")), battlefield(after).get(target.get("object_id"))
    if old is None or new is None or any(old.get(key) is not False for key in ("copy", "face_down", "token")):
        return None
    if any(old.get(key) != target.get(key) for key in ("card_name", "owner_seat", "controller_seat", "zone")):
        return None
    if kind == "prowess" and (top.get("controller_seat") != old.get("controller_seat")
                               or "prowess" not in old.get("characteristics", {}).get("keywords", [])):
        return None
    expected = copy.deepcopy(old)
    for field, change in zip(("power", "toughness"), delta):
        value = expected.get("characteristics", {}).get(field)
        if type(value) is not int:
            return None
        expected["characteristics"][field] = value + change
    if expected != new:
        return None
    old_board, new_board = battlefield(before), battlefield(after)
    old_board[target["object_id"]] = expected
    if old_board != new_board:
        return None
    return {"kind": kind, "viewer": before["viewer"], "turn": before["turn"],
            "phase_step": before["phase_step"], "stack_before": copy.deepcopy(stack),
            "stack_after": copy.deepcopy(after["stack"]), "before": copy.deepcopy(old), "after": copy.deepcopy(new),
            "battlefield_before": copy.deepcopy(list(battlefield(before).values())),
            "battlefield_after": copy.deepcopy(list(new_board.values()))}


class PublicEffects:
    def __init__(self, seat):
        self.seat, self.previous, self.effects = seat, None, []

    def observe(self, observation):
        if observation.get("viewer") != self.seat:
            raise ValueError("public effect history belongs to another viewer")
        present = battlefield(observation)
        self.effects = [effect for effect in self.effects if effect["turn"] == observation.get("turn")
                        and effect["after"]["object_id"] in present]
        if self.previous is not None:
            effect = resolution(self.previous, observation)
            if effect is not None:
                if any(old["stack_before"][-1]["object_id"] == effect["stack_before"][-1]["object_id"]
                       for old in self.effects):
                    raise ValueError("public effect occurrence was already recorded")
                self.effects.append(effect)
        # No hands, libraries, graveyards or hidden engine state enter the witness.
        self.previous = {key: copy.deepcopy(observation.get(key)) for key in
                         ("viewer", "turn", "phase_step", "stack")}
        self.previous["players"] = [{"battlefield": copy.deepcopy(list(present.values()))}]

    def fields(self):
        return copy.deepcopy(self.effects)
