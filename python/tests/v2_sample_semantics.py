"""One valid semantic per v2.0 kind (spec 7.2, 7.3), for tests across tasks."""

from __future__ import annotations

R_BOLT = {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
R_MOUNTAIN = {"object_id": "o-2b8e4dafc6031912", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
R_SWIFTSPEAR = {"object_id": "o-4da06fc1e8253b34", "card_name": "Monastery Swiftspear", "owner_seat": "p0", "controller_seat": "p0", "zone": "battlefield"}
R_SPRITE = {"object_id": "o-6fc281e30a475d56", "card_name": "Spellstutter Sprite", "owner_seat": "p1", "controller_seat": "p1", "zone": "battlefield"}
R_STACK = {"object_id": "o-8c1d2e3f4a5b6c7d", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "stack"}

SAMPLES: dict[str, dict] = {
    "pass": {"kind": "pass"},
    "play_land": {"kind": "play_land", "source": R_MOUNTAIN, "face": 0},
    "cast_spell": {"kind": "cast_spell", "source": R_BOLT, "method": "normal"},
    "activate_mana_ability": {"kind": "activate_mana_ability", "source": R_SWIFTSPEAR, "ability_index": 0, "mana_choice": "R", "cost_target": None},
    "activate_ability": {"kind": "activate_ability", "source": R_SWIFTSPEAR, "ability_index": 0},
    "special_action": {"kind": "special_action", "source": R_BOLT, "action": "plot"},
    "choose_target": {"kind": "choose_target", "source": R_STACK, "slot": 0, "target": {"object": R_SPRITE}, "selected_count": 0, "minimum": 1, "maximum": 1},
    "finish_target_selection": {"kind": "finish_target_selection", "source": R_STACK, "slot": 0, "selected_count": 1},
    "choose_cost_target": {"kind": "choose_cost_target", "source": R_STACK, "cost_kind": "sacrifice", "candidate": R_SWIFTSPEAR, "selected_count": 0, "minimum": 1, "maximum": 1},
    "choose_cast_method": {"kind": "choose_cast_method", "source": R_BOLT, "method": "flashback"},
    "choose_spell_mode": {"kind": "choose_spell_mode", "source": R_STACK, "mode_index": 1, "mode_count": 3, "selected_count": 0, "minimum": 1, "maximum": 2},
    "choose_option": {"kind": "choose_option", "source": None, "purpose": "top_or_bottom", "option_index": 0, "option_count": 2, "option_label": "Top"},
    "choose_color": {"kind": "choose_color", "source": R_STACK, "purpose": "protection", "color": "red"},
    "choose_number": {"kind": "choose_number", "source": R_STACK, "purpose": "x_value", "value": 2, "minimum": 0, "maximum": 4},
    "choose_boolean": {"kind": "choose_boolean", "source": None, "purpose": "may_ability", "value": False},
    "choose_name": {"kind": "choose_name", "source": R_STACK, "purpose": "card_name", "value": "Lightning Bolt"},
    "select_object": {"kind": "select_object", "source": R_STACK, "purpose": "discard", "choice": {"object": R_MOUNTAIN}, "selected_count": 0, "minimum": 1, "maximum": 1},
    "finish_selection": {"kind": "finish_selection", "source": R_STACK, "purpose": "modes", "selected_count": 1},
    "optional_cost": {"kind": "optional_cost", "source": R_STACK, "cost": "kicker", "pay": True},
    "choose_cost_option": {"kind": "choose_cost_option", "source": R_STACK, "choice": "sacrifice_land"},
    "optional_cast": {"kind": "optional_cast", "card": R_BOLT, "method": "madness", "cast_it": False},
    "mulligan": {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 1, "keep": True},
    "order_pick": {"kind": "order_pick", "source": None, "purpose": "triggers", "position": 0, "count": 2,
                   "item": {"trigger": {"source": R_SWIFTSPEAR, "source_name": "Monastery Swiftspear", "ability_index": 0,
                                        "event_objects": [R_SPRITE], "instance": 0, "label": None}}},
    "arrange_card": {"kind": "arrange_card", "source": R_STACK, "purpose": "scry", "card": R_MOUNTAIN, "card_index": 0, "card_count": 2, "destination": "top"},
    "choose_replacement": {"kind": "choose_replacement", "affected": {"player": "p0"}, "event": "damage", "replacement_source": None, "replacement_index": 1, "replacement_count": 2},
    "choose_starting_player": {"kind": "choose_starting_player", "player": "p1"},
    "declare_attack": {"kind": "declare_attack", "attacker": R_SWIFTSPEAR, "defender": {"player": "p1"}},
    "declare_block": {"kind": "declare_block", "blocker": R_SPRITE, "attacker": None},
    "distribute": {"kind": "distribute", "source": R_STACK, "purpose": "damage", "recipient": {"object": R_SPRITE}, "amount": 1, "remaining": 3},
    "choose_pile": {"kind": "choose_pile", "source": None, "purpose": "effect", "pile_index": 1, "piles": [[R_BOLT], [R_MOUNTAIN, R_SWIFTSPEAR]]},
}


def seat_decision(semantics=None, *, observation=None, acting_seat="p0", kind="priority", source=None,
                  purpose=None, rewind=False, extensions=None) -> dict:
    """A seat decision over the spec 6.1 observation (Task 8's sample), for the validator tests of Tasks 14 to 16 and 22."""
    import copy

    from v2_sample_observation import SAMPLE_OBSERVATION  # imported late: Task 8 lands in the same wave

    semantics = [SAMPLES["pass"], SAMPLES["play_land"], SAMPLES["cast_spell"]] if semantics is None else semantics
    return {
        "acting_seat": acting_seat, "seat_step": 0, "group": {"group_id": 0, "substep_index": 0, "substep_count": 1},
        "context": {"kind": kind, "source": source, "purpose": purpose, "text": None, "rewind": rewind},
        "observation": copy.deepcopy(SAMPLE_OBSERVATION) if observation is None else observation,
        "candidates": [{"candidate_id": index, "semantic": copy.deepcopy(semantic), "display_text": None}
                       for index, semantic in enumerate(semantics)],
        "extensions": {} if extensions is None else extensions,
    }
