"""The kinds tour (Task 26): one scripted game that offers every v2.0 decision kind at least once.

Played entirely from p0's seat (nothing here needs a second acting seat): pregame, a run of
priority actions, a series of self-contained spells and choices, a combat, and a rewind. Engine
args ``--london --toss --rewind`` (spec 12.2, 8): no observation flag is declared, so every
optional field of spec 6.9 is null throughout (R2-12), which keeps every decision's board state
minimal and focused on candidate shapes rather than realism.

``pick`` is the tour's answer function (R2-2): candidate 0 is always legal, and for a priority
decision (spec 7.1: pass is candidate 0 whenever it is legal) the script always places the action
it wants taken last in the candidate list, so picking the last candidate is how the tour ever
does anything but pass. Every other decision's desired answer is placed at candidate 0 by the
script itself, so candidate 0 (the default) already picks it.
"""

from __future__ import annotations

from fake_v2_world import Posed, Scenario, StackItem

PASS = {"kind": "pass"}


def pick(sd: dict) -> int:
    """The last candidate for a priority decision offering more than pass, candidate 0 otherwise."""
    candidates = sd["candidates"]
    if sd["context"]["kind"] == "priority" and len(candidates) > 1:
        return len(candidates) - 1
    return 0


def _script(world):
    # --- Pregame: choose_starting_player, a mulligan taken then kept, its bottomed card. ---
    world.turn, world.phase_step = 0, "pregame"
    world.active_seat = world.priority_seat = None
    yield Posed("p0", [{"kind": "choose_starting_player", "player": s} for s in ("p0", "p1")])

    first_hand = [world.add("Mountain", owner="p0", zone="hand") for _ in range(7)]
    yield Posed("p0", [{"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": False},
                       {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True}])
    for card in first_hand:
        world.move(card, "library")
    world.mulligans["p0"] = 1
    mtn, spike, edict, temper, isl_a, isl_b, isl_c = (
        world.add("Mountain", owner="p0", zone="hand"), world.add("Spikefield Hazard", owner="p0", zone="hand"),
        world.add("Chainer's Edict", owner="p0", zone="hand"), world.add("Fiery Temper", owner="p0", zone="hand"),
        world.add("Island", owner="p0", zone="hand"), world.add("Island", owner="p0", zone="hand"),
        world.add("Island", owner="p0", zone="hand"))
    yield Posed("p0", [{"kind": "mulligan", "hand_size": 7, "mulligans_taken": 1, "keep": True},
                       {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 1, "keep": False}])
    bottomed = yield Posed("p0", [{"kind": "order_pick", "source": None, "purpose": "mulligan_bottom",
                                   "item": {"object": {"$obj": card}}, "position": 0, "count": 1}
                                  for card in (isl_c, isl_a, isl_b, mtn, spike, edict, temper)])
    world.move((isl_c, isl_a, isl_b, mtn, spike, edict, temper)[bottomed], "library")

    world.turn, world.phase_step, world.active_seat, world.priority_seat = 1, "precombat_main", "p0", "p0"

    # The permanents the rest of the tour needs, already in play.
    relic = world.add("Relic of Progenitus", owner="p0", zone="battlefield")
    fathom = world.add("Fathom Seer", owner="p0", zone="battlefield", face_down=True)
    needle = world.add("Pithing Needle", owner="p0", zone="battlefield")
    bears0 = world.add("Grizzly Bears", owner="p0", zone="battlefield")
    swift = world.add("Monastery Swiftspear", owner="p0", zone="battlefield")
    sprite1 = world.add("Spellstutter Sprite", owner="p1", zone="battlefield")
    bears1 = world.add("Grizzly Bears", owner="p1", zone="battlefield")
    lib_search = [world.add("Mountain", owner="p0", zone="library") for _ in range(2)]
    lib_scry = [world.add("Island", owner="p0", zone="library") for _ in range(2)]
    lib_pile = [world.add("Counterspell", owner="p0", zone="library"), world.add("Brainstorm", owner="p0", zone="library")]

    # --- Priority: play_land (both faces), cast_spell + choose_cast_method, special_action,
    #     activate_mana_ability, activate_ability. ---
    # Both play_land faces are offered (spec 7.2: face 1 is the back of a modal double-faced land);
    # the tour actually plays the Mountain, since a later step needs an untapped mana source.
    yield Posed("p0", [PASS, {"kind": "play_land", "source": {"$obj": spike}, "face": 1},
                       {"kind": "play_land", "source": {"$obj": mtn}, "face": 0}])
    world.move(mtn, "battlefield")
    mountain_bf = mtn

    yield Posed("p0", [PASS, {"kind": "cast_spell", "source": {"$obj": edict}, "method": None}])
    world.move(edict, "stack")
    world.stack.append(StackItem(edict, "spell", None, []))
    yield Posed("p0", [{"kind": "choose_cast_method", "source": {"$obj": edict}, "method": "flashback"},
                       {"kind": "choose_cast_method", "source": {"$obj": edict}, "method": "normal"}],
                source={"$obj": edict})
    world.move(edict, "graveyard")

    yield Posed("p0", [PASS, {"kind": "special_action", "source": {"$obj": fathom}, "action": "turn_face_up"}])
    world.objects[fathom].face_down = False   # a face turn-up is not a zone change (CR 707)

    yield Posed("p0", [PASS, {"kind": "activate_mana_ability", "source": {"$obj": mountain_bf}, "ability_index": 0,
                              "mana_choice": "R", "cost_target": None}])
    world.mana_pool["p0"]["R"] += 1

    yield Posed("p0", [PASS, {"kind": "activate_ability", "source": {"$obj": relic}, "ability_index": 0}])

    # --- A fixed two-target spell: one group of two choose_target. ---
    flicker = world.add("Ghostly Flicker", owner="p0", zone="stack")
    world.stack.append(StackItem(flicker, "spell", None, [None, None]))
    yield Posed("p0", [{"kind": "choose_target", "source": {"$obj": flicker}, "slot": 0,
                        "target": {"object": {"$obj": relic}}, "selected_count": 0, "minimum": 2, "maximum": 2},
                       {"kind": "choose_target", "source": {"$obj": flicker}, "slot": 0,
                        "target": {"object": {"$obj": needle}}, "selected_count": 0, "minimum": 2, "maximum": 2}],
                substep=(0, 2), source={"$obj": flicker})
    yield Posed("p0", [{"kind": "choose_target", "source": {"$obj": flicker}, "slot": 0,
                        "target": {"object": {"$obj": needle}}, "selected_count": 1, "minimum": 2, "maximum": 2}],
                substep=(1, 2), source={"$obj": flicker})
    world.move(flicker, "graveyard")

    # --- A variable-target spell: choose_target then finish_target_selection, one group each. ---
    forked = world.add("Forked Bolt", owner="p0", zone="stack")
    world.stack.append(StackItem(forked, "spell", None, [None]))
    yield Posed("p0", [{"kind": "choose_target", "source": {"$obj": forked}, "slot": 0,
                        "target": {"object": {"$obj": sprite1}}, "selected_count": 0, "minimum": 1, "maximum": 2},
                       {"kind": "choose_target", "source": {"$obj": forked}, "slot": 0,
                        "target": {"object": {"$obj": bears1}}, "selected_count": 0, "minimum": 1, "maximum": 2}],
                source={"$obj": forked})
    yield Posed("p0", [{"kind": "finish_target_selection", "source": {"$obj": forked}, "slot": 0, "selected_count": 1},
                       {"kind": "choose_target", "source": {"$obj": forked}, "slot": 0,
                        "target": {"object": {"$obj": bears1}}, "selected_count": 1, "minimum": 1, "maximum": 2}],
                source={"$obj": forked})
    world.move(forked, "graveyard")

    # --- Burst Lightning: choose_cost_target, optional_cost (kicker), choose_cost_option. ---
    burst = world.add("Burst Lightning", owner="p0", zone="stack")
    world.stack.append(StackItem(burst, "spell", None, [None]))
    yield Posed("p0", [{"kind": "choose_cost_target", "source": {"$obj": burst}, "cost_kind": "tap",
                        "candidate": {"$obj": mountain_bf}, "selected_count": 0, "minimum": 1, "maximum": 1},
                       {"kind": "choose_cost_target", "source": {"$obj": burst}, "cost_kind": "tap",
                        "candidate": {"$obj": bears0}, "selected_count": 0, "minimum": 1, "maximum": 1}],
                source={"$obj": burst})
    yield Posed("p0", [{"kind": "optional_cost", "source": {"$obj": burst}, "cost": "kicker", "pay": True},
                       {"kind": "optional_cost", "source": {"$obj": burst}, "cost": "kicker", "pay": False}],
                source={"$obj": burst})
    yield Posed("p0", [{"kind": "choose_cost_option", "source": {"$obj": burst}, "choice": "pay_life"},
                       {"kind": "choose_cost_option", "source": {"$obj": burst}, "choice": "discard_a_card"}],
                source={"$obj": burst})
    world.move(burst, "graveyard")

    # --- Cryptic Command: "choose two" modes, a fixed group of two choose_spell_mode. ---
    cryptic = world.add("Cryptic Command", owner="p0", zone="stack")
    world.stack.append(StackItem(cryptic, "spell", None, [], modes=[0, 2]))
    yield Posed("p0", [{"kind": "choose_spell_mode", "source": {"$obj": cryptic}, "mode_index": index, "mode_count": 4,
                        "selected_count": 0, "minimum": 2, "maximum": 2} for index in range(4)],
                substep=(0, 2), source={"$obj": cryptic})
    yield Posed("p0", [{"kind": "choose_spell_mode", "source": {"$obj": cryptic}, "mode_index": index, "mode_count": 4,
                        "selected_count": 1, "minimum": 2, "maximum": 2} for index in (1, 2, 3)],
                substep=(1, 2), source={"$obj": cryptic})
    world.move(cryptic, "graveyard")

    # --- Borrowed Hostility: "one or more" modes, ended by finish_selection with purpose modes. ---
    escalate = world.add("Borrowed Hostility", owner="p0", zone="stack")
    world.stack.append(StackItem(escalate, "spell", None, [None], modes=[0]))
    yield Posed("p0", [{"kind": "choose_spell_mode", "source": {"$obj": escalate}, "mode_index": 0, "mode_count": 2,
                        "selected_count": 0, "minimum": 1, "maximum": 2},
                       {"kind": "choose_spell_mode", "source": {"$obj": escalate}, "mode_index": 1, "mode_count": 2,
                        "selected_count": 0, "minimum": 1, "maximum": 2}],
                source={"$obj": escalate})
    yield Posed("p0", [{"kind": "finish_selection", "source": {"$obj": escalate}, "purpose": "modes", "selected_count": 1},
                       {"kind": "choose_spell_mode", "source": {"$obj": escalate}, "mode_index": 1, "mode_count": 2,
                        "selected_count": 1, "minimum": 1, "maximum": 2}],
                source={"$obj": escalate})
    world.move(escalate, "graveyard")

    # --- A resolution-time mana payment (context.purpose: mana_payment, spec 7.1): first with an empty pool,
    #     offering only activate_mana_ability and optional_cost pay: false; re-posed once the pool covers the
    #     cost, now also offering pay: true (R2-22). ---
    counter = world.add("Counterspell", owner="p0", zone="stack")
    world.stack.append(StackItem(counter, "spell", None, [None]))
    yield Posed("p0", [{"kind": "activate_mana_ability", "source": {"$obj": mountain_bf}, "ability_index": 0,
                        "mana_choice": "R", "cost_target": None},
                       {"kind": "optional_cost", "source": {"$obj": counter}, "cost": "unless_payment", "pay": False}],
                kind="choice", purpose="mana_payment", source={"$obj": counter})
    world.mana_pool["p0"]["R"] += 1
    yield Posed("p0", [{"kind": "optional_cost", "source": {"$obj": counter}, "cost": "unless_payment", "pay": True},
                       {"kind": "optional_cost", "source": {"$obj": counter}, "cost": "unless_payment", "pay": False}],
                kind="choice", purpose="mana_payment", source={"$obj": counter})
    world.mana_pool["p0"]["R"] -= 1
    world.move(counter, "graveyard")

    # --- choose_option, choose_color, choose_number (X), choose_boolean, choose_name. ---
    yield Posed("p0", [{"kind": "choose_option", "source": None, "purpose": "effect_option", "option_index": 0,
                        "option_count": 2, "option_label": None},
                       {"kind": "choose_option", "source": None, "purpose": "effect_option", "option_index": 1,
                        "option_count": 2, "option_label": None}])
    yield Posed("p0", [{"kind": "choose_color", "source": None, "purpose": "mana", "color": "red"},
                       {"kind": "choose_color", "source": None, "purpose": "mana", "color": "blue"}])

    fireball = world.add("Fireball", owner="p0", zone="stack")
    world.stack.append(StackItem(fireball, "spell", None, [], x_value=2))
    yield Posed("p0", [{"kind": "choose_number", "source": {"$obj": fireball}, "purpose": "x_value", "value": value,
                        "minimum": 0, "maximum": 4} for value in (2, 0, 1, 3, 4)], source={"$obj": fireball})
    world.move(fireball, "graveyard")

    yield Posed("p0", [{"kind": "choose_boolean", "source": None, "purpose": "may_ability", "value": True},
                       {"kind": "choose_boolean", "source": None, "purpose": "may_ability", "value": False}])
    yield Posed("p0", [{"kind": "choose_name", "source": {"$obj": needle}, "purpose": "card_name", "value": "Mountain"},
                       {"kind": "choose_name", "source": {"$obj": needle}, "purpose": "card_name", "value": "Grizzly Bears"}],
                source={"$obj": needle})

    # --- A fixed discard of two, then optional_cast on the madness card it discarded. ---
    # Two of (Fiery Temper, the two remaining Islands) are still in hand; the mulligan bottomed one card.
    discard_pool = [card for card in (temper, isl_a, isl_b) if world.objects[card].zone == "hand"][:2]
    for index in range(2):
        picked = yield Posed("p0", [{"kind": "select_object", "source": None, "purpose": "discard",
                                     "choice": {"object": {"$obj": card}}, "selected_count": index,
                                     "minimum": 2, "maximum": 2} for card in discard_pool],
                              substep=(index, 2))
        world.move(discard_pool.pop(picked), "graveyard")

    yield Posed("p0", [{"kind": "optional_cast", "card": {"$obj": temper}, "method": "madness", "cast_it": True},
                       {"kind": "optional_cast", "card": {"$obj": temper}, "method": "madness", "cast_it": False}])

    # --- A library search: select_object candidates in (card_name, object_id) order, ended by finish_selection. ---
    ids = {card: world.look("p0", card) for card in lib_search}
    ordered = sorted(lib_search, key=lambda card: (world.objects[card].name, ids[card]))
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": world.objects[card].name,
                          "object_id": None, "position_from_top": None, "position_from_bottom": None,
                          "how": "searching", "internal": card} for card in lib_search]
    yield Posed("p0", [{"kind": "finish_selection", "source": None, "purpose": "search", "selected_count": 0}]
                + [{"kind": "select_object", "source": None, "purpose": "search",
                   "choice": {"object": {"$obj": card}}, "selected_count": 0, "minimum": 0, "maximum": 1}
                  for card in ordered])
    world.end_looks("p0")
    world.known["p0"] = []

    # --- Preordain: scry 2, one fixed group of three (2n - 1). ---
    preordain = world.add("Preordain", owner="p0", zone="stack")
    world.stack.append(StackItem(preordain, "spell", None, []))
    top, second = lib_scry
    scry_ids = {card: world.look("p0", card) for card in (top, second)}
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": world.objects[card].name, "object_id": None,
                          "position_from_top": index, "position_from_bottom": None, "how": "looked_at", "internal": card}
                         for index, card in enumerate((top, second))]
    # candidates[] referencing different hidden (library) cards must sort by (card_name, object_id) (V5, spec 7.1).
    scry_order = sorted((top, second), key=lambda card: (world.objects[card].name, scry_ids[card]))
    yield Posed("p0", [{"kind": "arrange_card", "source": {"$obj": preordain}, "purpose": "scry", "card": {"$obj": top},
                        "card_index": 0, "card_count": 2, "destination": destination} for destination in ("top", "bottom")],
                substep=(0, 3), source={"$obj": preordain})
    yield Posed("p0", [{"kind": "arrange_card", "source": {"$obj": preordain}, "purpose": "scry", "card": {"$obj": second},
                        "card_index": 1, "card_count": 2, "destination": destination} for destination in ("top", "bottom")],
                substep=(1, 3), source={"$obj": preordain})
    yield Posed("p0", [{"kind": "order_pick", "source": {"$obj": preordain}, "purpose": "arrangement",
                        "item": {"object": {"$obj": card}}, "position": 0, "count": 2} for card in scry_order],
                substep=(2, 3), source={"$obj": preordain})
    world.end_looks("p0")
    world.known["p0"] = []
    world.move(preordain, "graveyard")

    # --- choose_replacement, offered while two replacement effects still apply. ---
    yield Posed("p0", [{"kind": "choose_replacement", "affected": {"player": "p0"}, "event": "damage",
                        "replacement_source": None, "replacement_index": index, "replacement_count": 2}
                       for index in (0, 1)])

    # --- Fact or Fiction: a pile split (arrangement) then choose_pile. ---
    fact = world.add("Fact or Fiction", owner="p0", zone="stack")
    world.stack.append(StackItem(fact, "spell", None, []))
    pile_a, pile_b = lib_pile
    world.look("p0", pile_a)
    world.look("p0", pile_b)
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": world.objects[card].name, "object_id": None,
                          "position_from_top": index, "position_from_bottom": None, "how": "revealed", "internal": card}
                         for index, card in enumerate((pile_a, pile_b))]
    yield Posed("p0", [{"kind": "arrange_card", "source": {"$obj": fact}, "purpose": "pile_split", "card": {"$obj": pile_a},
                        "card_index": 0, "card_count": 2, "destination": destination} for destination in ("pile_0", "pile_1")],
                substep=(0, 3), source={"$obj": fact})
    yield Posed("p0", [{"kind": "arrange_card", "source": {"$obj": fact}, "purpose": "pile_split", "card": {"$obj": pile_b},
                        "card_index": 1, "card_count": 2, "destination": destination} for destination in ("pile_1", "pile_0")],
                substep=(1, 3), source={"$obj": fact})
    yield Posed("p0", [{"kind": "order_pick", "source": {"$obj": fact}, "purpose": "arrangement",
                        "item": {"object": {"$obj": pile_a}}, "position": 0, "count": 2}],
                substep=(2, 3), source={"$obj": fact})
    chosen_pile = yield Posed("p0", [{"kind": "choose_pile", "source": {"$obj": fact}, "purpose": "effect",
                                      "pile_index": index, "piles": [[{"$obj": pile_a}], [{"$obj": pile_b}]]}
                                     for index in (0, 1)], source={"$obj": fact})
    world.end_looks("p0")
    world.known["p0"] = []
    world.move(pile_a, "hand" if chosen_pile == 0 else "graveyard")
    world.move(pile_b, "graveyard" if chosen_pile == 0 else "hand")
    world.move(fact, "graveyard")

    # --- Three triggers, ordered by two order_pick decisions (the last position implied, R2-9). ---
    sources = [swift, bears0, sprite1]
    picked = yield Posed("p0", [{"kind": "order_pick", "source": None, "purpose": "triggers",
                                 "item": {"trigger": {"source": {"$obj": source}, "source_name": world.objects[source].name,
                                                      "ability_index": 0, "event_objects": [], "instance": 0, "label": None}},
                                 "position": 0, "count": 3} for source in sources],
                         substep=(0, 2))
    sources.pop(picked)               # each candidate_id indexes this decision's own candidate list
    picked = yield Posed("p0", [{"kind": "order_pick", "source": None, "purpose": "triggers",
                                 "item": {"trigger": {"source": {"$obj": source}, "source_name": world.objects[source].name,
                                                      "ability_index": 0, "event_objects": [], "instance": 0, "label": None}},
                                 "position": 1, "count": 3} for source in sources],
                         substep=(1, 2))
    sources.pop(picked)
    # position 2 (the last, sources[0]) is implied and not posed.

    # --- Combat: attacks, blocks, combat damage. ---
    world.phase_step = "declare_attackers"
    yield Posed("p0", [{"kind": "declare_attack", "attacker": {"$obj": swift}, "defender": {"player": "p1"}},
                       {"kind": "declare_attack", "attacker": {"$obj": swift}, "defender": None}],
                substep=(0, 2))
    yield Posed("p0", [{"kind": "declare_attack", "attacker": {"$obj": bears0}, "defender": None},
                       {"kind": "declare_attack", "attacker": {"$obj": bears0}, "defender": {"player": "p1"}}],
                substep=(1, 2))

    world.phase_step = "declare_blockers"
    yield Posed("p0", [{"kind": "declare_block", "blocker": {"$obj": swift}, "attacker": {"$obj": sprite1}},
                       {"kind": "declare_block", "blocker": {"$obj": swift}, "attacker": None}],
                substep=(0, 3))
    yield Posed("p0", [{"kind": "declare_block", "blocker": {"$obj": bears0}, "attacker": {"$obj": sprite1}},
                       {"kind": "declare_block", "blocker": {"$obj": bears0}, "attacker": None}],
                substep=(1, 3))
    yield Posed("p0", [{"kind": "declare_block", "blocker": {"$obj": bears0}, "attacker": {"$obj": bears1}},
                       {"kind": "declare_block", "blocker": {"$obj": bears0}, "attacker": None}],
                substep=(2, 3))

    world.phase_step = "combat_damage"
    yield Posed("p0", [{"kind": "distribute", "source": {"$obj": bears1}, "purpose": "combat_damage",
                        "recipient": {"object": {"$obj": swift}}, "amount": amount, "remaining": 2} for amount in (0, 1, 2)],
                substep=(0, 2))
    yield Posed("p0", [{"kind": "distribute", "source": {"$obj": bears1}, "purpose": "combat_damage",
                        "recipient": {"player": "p1"}, "amount": amount, "remaining": 1} for amount in (0, 1)],
                substep=(1, 2))

    world.turn, world.phase_step = 2, "precombat_main"

    # --- The rewind: a cast that cannot be completed is undone, and priority is re-posed (spec 8). ---
    bolt = world.add("Lightning Bolt", owner="p0", zone="hand")
    yield Posed("p0", [PASS, {"kind": "cast_spell", "source": {"$obj": bolt}, "method": "normal"}])
    world.move(bolt, "stack")
    world.stack.append(StackItem(bolt, "spell", None, []))
    yield Posed("p0", [{"kind": "choose_target", "source": {"$obj": bolt}, "slot": 0,
                        "target": {"player": "p1"}, "selected_count": 0, "minimum": 1, "maximum": 1}],
                source={"$obj": bolt})
    world.move(bolt, "hand")
    yield Posed("p0", [PASS], rewind=True)


SCENARIO = Scenario(
    name="kinds",
    decklist=[
        {"name": "Mountain", "count": 10}, {"name": "Island", "count": 10}, {"name": "Spikefield Hazard", "count": 2},
        {"name": "Chainer's Edict", "count": 2}, {"name": "Fiery Temper", "count": 2},
        {"name": "Relic of Progenitus", "count": 1}, {"name": "Fathom Seer", "count": 1}, {"name": "Pithing Needle", "count": 1},
        {"name": "Grizzly Bears", "count": 2}, {"name": "Monastery Swiftspear", "count": 1},
        {"name": "Spellstutter Sprite", "count": 1}, {"name": "Ghostly Flicker", "count": 1}, {"name": "Forked Bolt", "count": 1},
        {"name": "Burst Lightning", "count": 1}, {"name": "Cryptic Command", "count": 1}, {"name": "Borrowed Hostility", "count": 1},
        {"name": "Counterspell", "count": 2}, {"name": "Brainstorm", "count": 1}, {"name": "Preordain", "count": 1},
        {"name": "Fact or Fiction", "count": 1}, {"name": "Fireball", "count": 1}, {"name": "Lightning Bolt", "count": 1},
    ],
    engine_args=("--london", "--toss", "--rewind"),
    script=_script,
)
