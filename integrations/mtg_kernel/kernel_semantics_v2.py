"""Map ordinary actor-visible native choices to the neutral v2 vocabulary.

Aggregate blocker and library arrangement choices are handled separately.
This conversion never forwards native references or display strings.
"""
from __future__ import annotations

from kernel_observation_v2 import ProjectionError, normalized_zones
from spellbench.candidates import SELECT_PURPOSES, validate_semantic


def ordinary_semantic(semantic, raw, support, projection, group, *, candidate_id=None):
    kind = semantic["kind"]
    context = normalized_zones(raw)["projection"]["engine_context"]
    def source(nullable=False):
        if kind in ("play_land", "cast_spell", "activate_mana_ability", "activate_ability", "plot_spell"):
            return projection.legacy_ref(semantic.get("source"), nullable=nullable)
        instance = ((support.get("announcing_trigger") or {}).get("instance") or
                    (support.get("announcing_activation") or {}).get("instance") or
                    support.get("resolving_stack_instance"))
        if instance is not None:
            if instance not in projection.stack_refs:
                raise ProjectionError("choice lost its public stack instance")
            return projection.stack_refs[instance].copy()
        return projection.legacy_ref(semantic.get("source"), nullable=nullable)
    def target(value):
        if "player" in value:
            return {"player": projection.seat(value["player"])}
        return {"object": projection.legacy_ref(value["object"])}
    purpose = support.get("choice", {}).get("purpose", "other")
    pending_source = next((projection.stable_ref(context[field]["source"])
        for field in ("pending_cast", "pending_activation", "pending_optional_cost", "pending_optional_cost_sacrifice")
        if context.get(field)), None)
    if kind == "pass":
        result = {"kind": kind}
    elif kind == "play_land":
        result = {"kind": kind, "source": source(), "face": 0}
    elif kind == "cast_spell":
        result = {"kind": kind, "source": source(), "method": None}
    elif kind == "activate_mana_ability":
        index = support.get("mana_ability_indices", {}).get(str(candidate_id))
        if type(index) is not int or index < 0:
            raise ProjectionError("mana ability row lacks its exact native index")
        result = {"kind": kind, "source": source(), "ability_index": index,
                  "mana_choice": semantic["mana_choice"],
                  "cost_target": None if semantic["cost_target"] is None else target(semantic["cost_target"])}
    elif kind == "activate_ability":
        result = {"kind": kind, "source": source(), "ability_index": semantic["ability_index"]}
    elif kind == "plot_spell":
        result = {"kind": "special_action", "source": source(), "action": "plot"}
    elif kind == "choose_target":
        pending = context.get("pending_cast") or context.get("pending_activation")
        bounds = support.get("target_bounds")
        if (pending is not None or support.get("announcing_trigger")) and isinstance(bounds, dict):
            selected = bounds["selected_count"]
            minimum, maximum, slot = bounds["minimum"], bounds["maximum"], bounds["slot"]
        else:
            raise ProjectionError("target choice lacks its actor-visible announcement")
        # This native announcement chooses fixed targets in one slot. The
        # legacy remaining count is the remaining fixed cardinality.
        if maximum - selected != semantic["remaining"]:
            raise ProjectionError("target bounds disagree with the native remaining count")
        result = {"kind": kind, "source": source(), "slot": slot, "target": target(semantic["target"]),
                  "selected_count": selected, "minimum": minimum, "maximum": maximum}
    elif kind == "finish_target_selection":
        result = {"kind": kind, "source": source(), "slot": 0, "selected_count": semantic["selected_count"]}
    elif kind == "choose_cost_target":
        pending = context.get("pending_cast") or context.get("pending_activation") or context.get("pending_optional_cost_sacrifice")
        cost = {"sacrifice_lands": "sacrifice", "sacrifice_permanents": "sacrifice",
                "sacrifice_creatures": "sacrifice", "sacrifice_artifacts": "sacrifice",
                "exile_from_graveyard": "exile", "tap_permanents": "tap",
                "return_permanents_to_hand": "return_to_hand"}.get(semantic["cost_kind"])
        if pending is None or cost is None:
            raise ProjectionError("cost cardinality is not represented by the native announcement")
        selected = support.get("cost_selected_count")
        if type(selected) is not int:
            raise ProjectionError("native cost progress is not represented")
        maximum = selected + semantic["remaining"]
        result = {"kind": kind, "source": source(), "cost_kind": cost,
                  "candidate": projection.legacy_ref(semantic["candidate"]),
                  "selected_count": selected, "minimum": maximum, "maximum": maximum}
    elif kind == "choose_cast_mode":
        result = {"kind": "choose_cast_method", "source": source(), "method": semantic["mode"]}
    elif kind == "choose_spell_mode":
        result = {"kind": kind, "source": source(), "mode_index": semantic["mode_index"],
                  "mode_count": semantic["mode_count"], "selected_count": 0, "minimum": 1, "maximum": 1}
    elif kind == "choose_option":
        if purpose == "x_value":
            result = {"kind": "choose_number", "source": source(), "purpose": "x_value",
                      "value": semantic["option_index"], "minimum": 0, "maximum": semantic["option_count"] - 1}
        else:
            result = {"kind": kind, "source": source(True), "purpose": "effect_option",
                      "option_index": semantic["option_index"], "option_count": semantic["option_count"],
                      "option_label": None}
    elif kind in ("choose_effect_target", "finish_effect_selection"):
        if purpose in ("scry", "look_select", "look"):
            raise ProjectionError("native library arrangement needs a buffered v2 group")
        selection_purpose = purpose if purpose in SELECT_PURPOSES else "other"
        announcement = context.get("pending_cast") or context.get("pending_activation")
        if announcement and support.get("target_bounds"):
            bounds = support["target_bounds"]
            if kind == "choose_effect_target":
                if (bounds["minimum"], bounds["maximum"], bounds["selected_count"]) != (
                    semantic["min_targets"], semantic["max_targets"], semantic["selected_count"]):
                    raise ProjectionError("optional target choice disagrees with its announcement")
                result = {"kind": "choose_target", "source": source(), "slot": bounds["slot"],
                          "target": target(semantic["target"]), "selected_count": bounds["selected_count"],
                          "minimum": bounds["minimum"], "maximum": bounds["maximum"]}
            else:
                result = {"kind": "finish_target_selection", "source": source(), "slot": bounds["slot"],
                          "selected_count": semantic["selected_count"]}
        elif kind == "choose_effect_target":
            result = {"kind": "select_object", "source": source(True), "purpose": selection_purpose,
                      "choice": target(semantic["target"]), "selected_count": semantic["selected_count"],
                      "minimum": semantic["min_targets"], "maximum": semantic["max_targets"]}
        else:
            result = {"kind": "finish_selection", "source": source(True), "purpose": selection_purpose,
                      "selected_count": semantic["selected_count"]}
    elif kind == "choose_color":
        result = {"kind": kind, "source": source(True), "purpose": "effect", "color": semantic["color"]}
    elif kind == "choose_number":
        result = {"kind": kind, "source": source(True), "purpose": "x_value",
                  **{key: semantic[key] for key in ("value", "minimum", "maximum")}}
    elif kind == "choose_boolean":
        if purpose in ("unless_payment", "resolution_payment", "exile_payment"):
            result = {"kind": "optional_cost", "source": source(),
                      "cost": "unless_payment" if purpose == "unless_payment" else "other", "pay": semantic["value"]}
        else:
            result = {"kind": kind, "source": source(True), "purpose": "reveal" if purpose == "reveal" else "may_ability",
                      "value": semantic["value"]}
    elif kind in ("choose_kicker", "choose_spell_copy_payment"):
        result = {"kind": "optional_cost", "source": source(),
                  "cost": "kicker" if kind == "choose_kicker" else "copy", "pay": semantic["pay"]}
    elif kind in ("choose_optional_cost_use", "choose_optional_cost_which"):
        if pending_source is None:
            raise ProjectionError("optional cost source is not currently visible")
        result = ({"kind": "optional_cost", "source": pending_source, "cost": "additional", "pay": semantic["use_cost"]}
                  if kind == "choose_optional_cost_use" else
                  {"kind": "choose_cost_option", "source": pending_source, "choice": semantic["choice"]})
    elif kind == "choose_spell_copy_retarget":
        result = {"kind": "choose_boolean", "source": source(True), "purpose": "change_copy_targets",
                  "value": semantic["change_target"]}
    elif kind == "choose_madness_cast":
        result = {"kind": "optional_cast", "card": projection.legacy_ref(semantic["card"]),
                  "method": "madness", "cast_it": semantic["cast_it"]}
    elif kind == "discard":
        if len(semantic["cards"]) != 1:
            raise ProjectionError("native discard is not one card")
        result = {"kind": "select_object", "source": None, "purpose": "discard",
                  "choice": {"object": projection.legacy_ref(semantic["cards"][0])},
                  "selected_count": 0, "minimum": 1, "maximum": 1}
    elif kind == "choose_attacker_inclusion":
        attacker = projection.legacy_ref(semantic["attacker"])
        result = {"kind": "declare_attack", "attacker": attacker,
                  "defender": {"player": "p1" if attacker["controller_seat"] == "p0" else "p0"}
                  if semantic["include"] else None}
    else:
        raise ProjectionError(f"unmapped native choice family: {kind}")
    validate_semantic(result)
    return result
