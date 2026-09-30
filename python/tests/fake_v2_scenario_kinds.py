"""The kinds tour (Task 26): one scripted game that offers every v2.0 decision kind at least once.

Engine args ``--london --toss --rewind`` (spec 12.2, 8); no observation flag is declared, so every optional
field of spec 6.9 is null throughout (R2-12). The game follows the brief's order: the pregame, p0's turn 9 (the
priority actions, targets, modes, choices, a discard, a search, costs, a mana payment, triggers and a scry), and
p0's turn 11 (combat, a pile split and a rewind). Each seat decides what the rules give it: p1 takes its own
mulligan decision, declares blocks and assigns its blocker's damage, and splits Fact or Fiction's piles.

The tour is not a full game. Turns 1 to 8 and 10 happen off screen, and so do the decisions between two posed
ones (priority passes, spells cast without a posed ``cast_spell``, resolutions, other trigger orders); mana
costs are not tracked, except that a land that makes mana is tapped and the mana payment of spec 7.1 starts
from an empty pool (R2-22).

Answers (fix round 1): ``pick`` is the tour's answer function (R2-2), and every later step follows the answer
the script receives. A step whose later steps assume one particular answer poses its decision through ``ask``
with ``expect``, which raises ``UnexpectedAnswer`` on any other answer, so a picker that answers differently
stops the tour loudly instead of letting it carry on as if the assumed answer had been given.
"""

from __future__ import annotations

from spellbench.digests import card_name_domain

from fake_v2_world import CARDS, Posed, Scenario, StackItem

PASS = {"kind": "pass"}
SPIKEFIELD = "Spikefield Hazard // Spikefield Cave"
# Spec 7.5: an arrangement orders its cards destination by destination, in this order.
DESTINATION_ORDER = ("top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1")
# The cards the tour draws after the pregame, top card first.
P0_LIBRARY = ("Mountain", "Preordain", "Fact or Fiction", "Island", "Brainstorm", "Lightning Bolt", "Counterspell",
              "Island", "Mountain", "Brainstorm", "Island", "Mountain", "Island", "Lightning Bolt", "Counterspell",
              "Brainstorm", "Mountain", "Island", "Brainstorm", "Counterspell")
P1_LIBRARY = ("Island", "Lightning Bolt", "Brainstorm", "Mountain", "Counterspell", "Island", "Mountain", "Brainstorm")


class UnexpectedAnswer(AssertionError):
    """A decision was answered with a candidate the script's later steps do not follow."""


def pick(sd: dict) -> int:
    """The last candidate for a priority decision offering more than pass, candidate 0 otherwise.

    Pass is candidate 0 whenever it is legal (spec 7.1), so the script lists the action it takes last in a
    priority decision; every other decision takes candidate 0. ``ask`` checks each answer a later step assumes.
    """
    candidates = sd["candidates"]
    if sd["context"]["kind"] == "priority" and len(candidates) > 1:
        return len(candidates) - 1
    return 0


def ask(posed: Posed, expect: dict | None = None):
    """Pose one decision and return the chosen candidate as posed; ``expect`` is the one later steps assume."""
    chosen = posed.candidates[(yield posed)]
    if expect is not None and chosen != expect:
        raise UnexpectedAnswer(f"the script assumes {posed.seat} answers {expect}, not {chosen}")
    return chosen


# Candidate and board helpers. Internal ids are ints; a Posed reference is {"$obj": n}.

def _ref(internal: int) -> dict:
    return {"$obj": internal}


def _target(internal: int) -> dict:
    return {"object": {"$obj": internal}}


def _internal(target: dict) -> int:
    return target["object"]["$obj"]


def _mulligan(hand_size: int, taken: int, keep: bool) -> dict:
    return {"kind": "mulligan", "hand_size": hand_size, "mulligans_taken": taken, "keep": keep}


def _cast(card: int, method: str | None) -> dict:
    return {"kind": "cast_spell", "source": _ref(card), "method": method}


def _library(world, seat: str, *names: str) -> list[int]:
    return [world.add(name, owner=seat, zone="library") for name in names]


def _zone(world, seat: str, zone: str) -> list[int]:
    """The objects of a zone that ``seat`` owns (or controls, on the battlefield), oldest first."""
    key = "controller" if zone == "battlefield" else "owner"
    return [internal for internal, obj in world.objects.items() if obj.zone == zone and getattr(obj, key) == seat]


def _draw(world, seat: str, count: int = 1) -> None:
    for card in world.libraries[seat][:count]:
        world.move(card, "hand")


def _to_bottom(world, card: int) -> None:
    library = world.libraries[world.objects[card].owner]
    world.move(card, "library", library_position=len(library) - (card in library))


def _types(world, internal: int) -> list[str]:
    obj = world.objects[internal]
    return ["creature"] if obj.face_down else CARDS[obj.name]["types"]


def _creatures(world, *seats: str) -> list[int]:
    return [internal for seat in seats for internal in _zone(world, seat, "battlefield")
            if "creature" in _types(world, internal)]


def _any_targets(world) -> list[dict]:
    """Every player, then every creature, p1's first: the choices of "any target" in this tour."""
    return [{"player": "p1"}, {"player": "p0"}] + [_target(creature) for creature in _creatures(world, "p1", "p0")]


def _item(world, internal: int) -> StackItem:
    return next(item for item in world.stack if item.internal == internal)


def _spell(world, name: str, owner: str = "p0", **choices) -> int:
    """A spell cast off screen, now on the stack with nothing chosen yet (spec 6.5)."""
    spell = world.add(name, owner=owner, zone="stack")
    world.stack.append(StackItem(spell, "spell", None, [], **choices))
    return spell


def _ability(world, name: str, kind: str, source: int | None) -> int:
    """An ability on the stack, an object named after its source (spec 5.1); ``source`` None once it has left."""
    ability = world.add(name, owner="p0", zone="stack")
    world.stack.append(StackItem(ability, kind, source, []))
    return ability


def _resolved(world, ability: int) -> None:
    """An ability leaves the stack: its object is outside every observation from now on."""
    world.stack[:] = [item for item in world.stack if item.internal != ability]


def _deal(world, target: dict, amount: int) -> None:
    if "player" in target:
        world.life[target["player"]] -= amount
    else:
        world.objects[_internal(target)].damage += amount


def _destroy_lethal(world) -> None:
    """State-based actions: a creature with lethal damage is destroyed (CR 704.5g)."""
    for creature in _creatures(world, "p0", "p1"):
        obj = world.objects[creature]
        toughness = 2 if obj.face_down else CARDS[obj.name]["toughness"]
        if obj.damage >= toughness:
            world.move(creature, "graveyard")


def _choose_targets(world, seat: str, spell: int, slot: int, choices: list[dict], minimum: int, maximum: int):
    """One target per decision (spec 7.5), each answer added to the stack entry's targets.

    A fixed count (``minimum == maximum``) is one group; a variable count offers ``finish_target_selection``
    once ``minimum`` is met, one group per decision. Targets already chosen are not offered again.
    """
    item, chosen = _item(world, spell), []
    fixed = minimum == maximum
    while len(chosen) < maximum:
        offers = [{"kind": "choose_target", "source": _ref(spell), "slot": slot, "target": target,
                   "selected_count": len(chosen), "minimum": minimum, "maximum": maximum}
                  for target in choices if target not in chosen]
        if not fixed and len(chosen) >= minimum:
            offers.insert(0, {"kind": "finish_target_selection", "source": _ref(spell), "slot": slot,
                              "selected_count": len(chosen)})
        answer = yield from ask(Posed(seat, offers, substep=(len(chosen), maximum) if fixed else (0, 1),
                                      source=_ref(spell)))
        if answer["kind"] == "finish_target_selection":
            break
        chosen.append(answer["target"])
        item.targets.append(answer["target"])
    return chosen


def _choose_modes(world, seat: str, spell: int, legal: list[int], mode_count: int, minimum: int, maximum: int):
    """One mode per decision (spec 7.5); the stack entry shows the modes chosen so far, in index order."""
    item, chosen = _item(world, spell), []
    fixed = minimum == maximum
    while len(chosen) < maximum:
        offers = [{"kind": "choose_spell_mode", "source": _ref(spell), "mode_index": mode, "mode_count": mode_count,
                   "selected_count": len(chosen), "minimum": minimum, "maximum": maximum}
                  for mode in legal if mode not in chosen]
        if not fixed and len(chosen) >= minimum:
            offers.insert(0, {"kind": "finish_selection", "source": _ref(spell), "purpose": "modes",
                              "selected_count": len(chosen)})
        answer = yield from ask(Posed(seat, offers, substep=(len(chosen), maximum) if fixed else (0, 1),
                                      source=_ref(spell)))
        if answer["kind"] == "finish_selection":
            break
        chosen.append(answer["mode_index"])
        item.modes = sorted(chosen)
    return sorted(chosen)


def _arrange(world, seat: str, source: int, purpose: str, cards: list[int], destinations, look_ids: dict[int, str]):
    """An arrangement of n looked-at cards: n partition decisions, then n - 1 order picks (spec 7.5).

    ``destinations(card_index, placed)`` lists a card's candidate destinations given the earlier ones. Returns
    the cards grouped by destination, each group in the order the picks placed it.
    """
    n, placed = len(cards), {}
    for index, card in enumerate(cards):
        answer = yield from ask(Posed(seat, [{"kind": "arrange_card", "source": _ref(source), "purpose": purpose,
                                              "card": _ref(card), "card_index": index, "card_count": n,
                                              "destination": destination}
                                             for destination in destinations(index, dict(placed))],
                                      substep=(index, 2 * n - 1), source=_ref(source)))
        placed[card] = answer["destination"]
    order = {destination: [] for destination in DESTINATION_ORDER}
    for position in range(n - 1):
        current = next(d for d in DESTINATION_ORDER if len(order[d]) < sum(v == d for v in placed.values()))
        unplaced = sorted((card for card in cards if placed[card] == current and card not in order[current]),
                          key=lambda card: (world.objects[card].name, look_ids[card]))
        answer = yield from ask(Posed(seat, [{"kind": "order_pick", "source": _ref(source), "purpose": "arrangement",
                                              "item": {"object": _ref(card)}, "position": position, "count": n}
                                             for card in unplaced],
                                      substep=(n + position, 2 * n - 1), source=_ref(source)))
        order[current].append(answer["item"]["object"]["$obj"])
    last = next(card for card in cards if card not in sum(order.values(), []))
    order[placed[last]].append(last)                       # the final position is implied (spec 7.5)
    return order


def _script(world):
    domain = card_name_domain(row["name"] for row in DECKLIST)["names"]

    # --- Pregame: the toss winner (p0) chooses who starts; then London mulligans, p0 first (spec 7.5, 7.6). ---
    world.turn, world.phase_step, world.active_seat, world.priority_seat = 0, "pregame", None, None
    _library(world, "p0", "Mountain", "Mountain", "Island", "Grizzly Bears", "Lightning Bolt", "Mountain", "Island",
             "Burst Lightning", "Island", "Fiery Temper", "Chainer's Edict", SPIKEFIELD, "Fathom Seer",
             "Faithless Looting", *P0_LIBRARY)
    _library(world, "p1", "Island", "Island", "Island", "Spellstutter Sprite", "Night Market Guard", "Force Spike",
             "Mountain", *P1_LIBRARY)
    yield from ask(Posed("p0", [{"kind": "choose_starting_player", "player": seat} for seat in ("p0", "p1")]),
                   expect={"kind": "choose_starting_player", "player": "p0"})
    world.active_seat = "p0"                   # decided: active_seat is null only before that (spec 6.2)
    _draw(world, "p0", 7)
    _draw(world, "p1", 7)
    yield from ask(Posed("p0", [_mulligan(7, 0, False), _mulligan(7, 0, True)]), expect=_mulligan(7, 0, False))
    yield from ask(Posed("p1", [_mulligan(7, 0, True), _mulligan(7, 0, False)]), expect=_mulligan(7, 0, True))
    for card in _zone(world, "p0", "hand"):    # p0's mulligan: its hand is shuffled away, a new seven drawn
        _to_bottom(world, card)
    world.mulligans["p0"] = 1
    _draw(world, "p0", 7)
    yield from ask(Posed("p0", [_mulligan(7, 1, True), _mulligan(7, 1, False)]), expect=_mulligan(7, 1, True))
    hand = _zone(world, "p0", "hand")
    bottoms = [{"kind": "order_pick", "source": None, "purpose": "mulligan_bottom", "item": {"object": _ref(card)},
                "position": 0, "count": 1} for card in hand]
    yield from ask(Posed("p0", bottoms), expect=bottoms[0])   # the Burst Lightning; the rest is played below
    _to_bottom(world, hand[0])

    # --- Turns 1 to 8 off screen: lands and creatures played, cards drawn. Turn 9, p0's precombat main. ---
    temper, edict, spike, seer, looting = _zone(world, "p0", "hand")[1:]
    world.move(_zone(world, "p0", "hand")[0], "battlefield")                 # the kept Island, played on turn 1
    island, mountain, wilds, relic, bears = (world.add(name, owner="p0", zone="battlefield") for name in
                                             ("Island", "Mountain", "Evolving Wilds", "Relic of Progenitus",
                                              "Grizzly Bears"))
    for card in _zone(world, "p1", "hand"):
        if world.objects[card].name in ("Island", "Spellstutter Sprite", "Night Market Guard"):
            world.move(card, "battlefield")
    for permanent in _zone(world, "p0", "battlefield") + _zone(world, "p1", "battlefield"):
        world.objects[permanent].summoning_sick = False
    _draw(world, "p0", 4)
    _draw(world, "p1", 4)
    sprite, guard = _creatures(world, "p1")
    mountain_in_hand, preordain, fact = _zone(world, "p0", "hand")[5:8]
    world.turn, world.phase_step, world.priority_seat = 9, "precombat_main", "p0"

    # --- Priority: play_land (the Mountain's face 0, the modal double-faced card's face 1). ---
    cave = {"kind": "play_land", "source": _ref(spike), "face": 1}
    yield from ask(Posed("p0", [PASS, {"kind": "play_land", "source": _ref(mountain_in_hand), "face": 0}, cave]),
                   expect=cave)
    world.move(spike, "battlefield")
    world.objects[spike].name = "Spikefield Cave"          # played as its back face (spec 5.1)
    world.lands_played["p0"] = 1
    # As Spikefield Cave enters, p0 may pay 3 life; if it does not, the land enters tapped.
    options = [{"kind": "choose_cost_option", "source": _ref(spike), "choice": choice}
               for choice in ("pay_life", "enter_tapped")]
    yield from ask(Posed("p0", options, source=_ref(spike)), expect=options[0])   # the Cave taps for mana below
    world.life["p0"] -= 3

    # --- cast_spell with method null, then choose_cast_method: Fathom Seer cast face down (morph). ---
    yield from ask(Posed("p0", [PASS, _cast(seer, None)]), expect=_cast(seer, None))
    world.move(seer, "stack")
    world.stack.append(StackItem(seer, "spell", None, []))
    methods = [{"kind": "choose_cast_method", "source": _ref(seer), "method": method} for method in ("morph", "normal")]
    yield from ask(Posed("p0", methods, source=_ref(seer)), expect=methods[0])   # turned face up below
    world.objects[seer].face_down = True
    world.move(seer, "battlefield", face_down=True)          # the face-down 2/2 resolves (CR 708.4)

    # --- special_action: turn it face up, paying its morph cost, two Islands (choose_cost_target, a group of 2). ---
    face_up = {"kind": "special_action", "source": _ref(seer), "action": "turn_face_up"}
    yield from ask(Posed("p0", [PASS, face_up]), expect=face_up)
    islands, returned = [land for land in _zone(world, "p0", "battlefield") if world.objects[land].name == "Island"], []
    for index in range(2):
        answer = yield from ask(Posed("p0", [{"kind": "choose_cost_target", "source": _ref(seer),
                                               "cost_kind": "return_to_hand", "candidate": _ref(land),
                                               "selected_count": index, "minimum": 2, "maximum": 2}
                                              for land in islands if land not in returned],
                                      substep=(index, 2), source=_ref(seer)))
        returned.append(answer["candidate"]["$obj"])
    for land in returned:
        world.move(land, "hand")
    world.objects[seer].face_down = False                  # a face turn is not a zone change (CR 708.8)
    seer_trigger = _ability(world, "Fathom Seer", "triggered_ability", seer)   # when turned face up, draw two

    # --- activate_mana_ability (the Cave's red), spent at once on activate_ability (Relic's {1} ability). ---
    red = {"kind": "activate_mana_ability", "source": _ref(spike), "ability_index": 0, "mana_choice": "R",
           "cost_target": None}
    yield from ask(Posed("p0", [PASS, red]), expect=red)
    world.objects[spike].tapped = True
    world.mana_pool["p0"]["R"] += 1
    relic_ability = {"kind": "activate_ability", "source": _ref(relic), "ability_index": 1}
    yield from ask(Posed("p0", [PASS, relic_ability]), expect=relic_ability)
    world.mana_pool["p0"]["R"] -= 1                        # {1}, and Relic exiles itself as a cost
    world.move(relic, "exile")
    exile_all = _ability(world, "Relic of Progenitus", "activated_ability", None)   # its source has left
    _resolved(world, exile_all)                            # exile all graveyards (empty), draw a card
    _draw(world, "p0")
    _resolved(world, seer_trigger)
    _draw(world, "p0", 2)

    # --- A fixed two-target spell: Ghostly Flicker, one group of two choose_target. ---
    flicker = _spell(world, "Ghostly Flicker")
    mine = [_target(permanent) for permanent in _zone(world, "p0", "battlefield")
            if {"artifact", "creature", "land"} & set(_types(world, permanent))]
    flickered = yield from _choose_targets(world, "p0", flicker, 0, mine, 2, 2)
    for target in flickered:                               # exiled, then returned as new objects (CR 400.7)
        world.move(_internal(target), "exile")
        world.move(_internal(target), "battlefield")
    world.move(flicker, "graveyard")

    # --- A variable-target spell: Forked Bolt, choose_target then finish_target_selection, one group each. ---
    forked = _spell(world, "Forked Bolt")
    chosen = yield from _choose_targets(world, "p0", forked, 0, _any_targets(world), 1, 2)
    for target in chosen:                                  # 2 damage divided among one or two targets
        _deal(world, target, 2 // len(chosen))
    _destroy_lethal(world)
    world.move(forked, "graveyard")

    # --- "Choose two" (Cryptic Command, a group of two choose_spell_mode), then its target. ---
    cryptic = _spell(world, "Cryptic Command", modes=[])
    # Mode 0 counters target spell, and no other spell is on the stack, so it cannot be chosen (CR 700.2a).
    modes = yield from _choose_modes(world, "p0", cryptic, [1, 2, 3], 4, 2, 2)
    bounce = []
    if 1 in modes:                                         # return target permanent to its owner's hand
        permanents = [_target(p) for seat in ("p1", "p0") for p in _zone(world, seat, "battlefield")]
        bounce = yield from _choose_targets(world, "p0", cryptic, 0, permanents, 1, 1)
    for target in bounce:
        world.move(_internal(target), "hand")
    if 2 in modes:                                         # tap all creatures your opponents control
        for creature in _creatures(world, "p1"):
            world.objects[creature].tapped = True
    if 3 in modes:
        _draw(world, "p0")
    world.move(cryptic, "graveyard")

    # --- "One or more" (Borrowed Hostility, escalate) ended by finish_selection with purpose modes. ---
    hostility = _spell(world, "Borrowed Hostility", modes=[])
    modes = yield from _choose_modes(world, "p0", hostility, [0, 1], 2, 1, 2)
    for slot, _ in enumerate(modes):                       # each mode targets a creature
        yield from _choose_targets(world, "p0", hostility, slot, [_target(c) for c in _creatures(world, "p0", "p1")],
                                   1, 1)
    world.move(hostility, "graveyard")

    # --- choose_option, choose_color, choose_number (Fireball's X), choose_boolean, choose_name. ---
    yield from ask(Posed("p0", [{"kind": "choose_option", "source": None, "purpose": "effect_option",
                                 "option_index": index, "option_count": 2, "option_label": None} for index in (0, 1)]))
    yield from ask(Posed("p0", [{"kind": "choose_color", "source": None, "purpose": "mana", "color": color}
                                for color in ("red", "blue")]))
    fireball = _spell(world, "Fireball")                   # X is announced before targets (CR 601.2b)
    answer = yield from ask(Posed("p0", [{"kind": "choose_number", "source": _ref(fireball), "purpose": "x_value",
                                          "value": value, "minimum": 0, "maximum": 2} for value in (2, 1, 0)],
                                  source=_ref(fireball)))
    x_value = _item(world, fireball).x_value = answer["value"]
    chosen = yield from _choose_targets(world, "p0", fireball, 0, _any_targets(world), 1, len(_any_targets(world)))
    for target in chosen:                                  # X damage divided evenly, rounded down
        _deal(world, target, x_value // len(chosen))
    _destroy_lethal(world)
    world.move(fireball, "graveyard")
    yield from ask(Posed("p0", [{"kind": "choose_boolean", "source": None, "purpose": "may_ability", "value": value}
                                for value in (True, False)]))
    needle = _spell(world, "Pithing Needle")               # as it enters, name a card (resolution: no priority)
    world.priority_seat = None
    answer = yield from ask(Posed("p0", [{"kind": "choose_name", "source": _ref(needle), "purpose": "card_name",
                                          "value": name} for name in domain], source=_ref(needle)))
    world.move(needle, "battlefield")
    world.objects[needle].chosen = [{"kind": "card_name", "value": answer["value"]}]
    world.priority_seat = "p0"

    # --- A fixed discard of two (Faithless Looting: draw two, then discard two); Fiery Temper has madness. ---
    yield from ask(Posed("p0", [PASS, _cast(looting, "normal")]), expect=_cast(looting, "normal"))
    world.move(looting, "stack")
    world.stack.append(StackItem(looting, "spell", None, []))
    world.priority_seat = None
    _draw(world, "p0", 2)
    for index, assumed in enumerate((temper, edict)):     # the madness step and the rewind below need these two
        discards = [{"kind": "select_object", "source": _ref(looting), "purpose": "discard", "choice": _target(card),
                     "selected_count": index, "minimum": 2, "maximum": 2} for card in _zone(world, "p0", "hand")]
        yield from ask(Posed("p0", discards, substep=(index, 2), source=_ref(looting)),
                       expect=next(d for d in discards if d["choice"] == _target(assumed)))
        world.move(assumed, "exile" if assumed == temper else "graveyard")   # madness: discarded into exile
    world.move(looting, "graveyard")
    madness = _ability(world, "Fiery Temper", "triggered_ability", temper)
    world.priority_seat = "p0"

    # --- A library search (Evolving Wilds), ended by finish_selection with nothing found (CR 701.19b). ---
    fetch = {"kind": "activate_ability", "source": _ref(wilds), "ability_index": 0}
    yield from ask(Posed("p0", [PASS, fetch]), expect=fetch)
    world.move(wilds, "graveyard")                         # {T}, sacrifice it: the cost
    search = _ability(world, "Evolving Wilds", "activated_ability", None)
    world.priority_seat = None
    basics = [card for card in world.libraries["p0"] if "basic" in CARDS[world.objects[card].name]["supertypes"]]
    ids = {card: world.look("p0", card) for card in basics}
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": world.objects[card].name,
                          "object_id": None, "position_from_top": None, "position_from_bottom": None,
                          "how": "searching", "internal": card} for card in basics]
    answer = yield from ask(Posed("p0", [{"kind": "finish_selection", "source": _ref(search), "purpose": "search",
                                          "selected_count": 0}]
                                  + [{"kind": "select_object", "source": _ref(search), "purpose": "search",
                                      "choice": _target(card), "selected_count": 0, "minimum": 0, "maximum": 1}
                                     for card in sorted(basics, key=lambda card: (world.objects[card].name, ids[card]))],
                                  source=_ref(search)))
    world.end_looks("p0")
    world.known["p0"] = []
    if answer["kind"] == "select_object":                  # a basic land, onto the battlefield tapped
        world.move(_internal(answer["choice"]), "battlefield")
        world.objects[_internal(answer["choice"])].tapped = True
    _resolved(world, search)
    world.priority_seat = "p0"

    # --- optional_cost (Burst Lightning's kicker) and its target; the madness trigger waits below it. ---
    burst = _spell(world, "Burst Lightning")
    kicker = yield from ask(Posed("p0", [{"kind": "optional_cost", "source": _ref(burst), "cost": "kicker", "pay": pay}
                                         for pay in (True, False)], source=_ref(burst)))
    chosen = yield from _choose_targets(world, "p0", burst, 0, _any_targets(world), 1, 1)
    _deal(world, chosen[0], 4 if kicker["pay"] else 2)
    _destroy_lethal(world)
    world.move(burst, "graveyard")
    world.priority_seat = None                             # the madness trigger resolves: optional_cast
    answer = yield from ask(Posed("p0", [{"kind": "optional_cast", "card": _ref(temper), "method": "madness",
                                          "cast_it": cast_it} for cast_it in (True, False)]))
    if answer["cast_it"]:                                  # cast while the trigger resolves, above it
        world.move(temper, "stack")
        world.stack.append(StackItem(temper, "spell", None, []))
        chosen = yield from _choose_targets(world, "p0", temper, 0, _any_targets(world), 1, 1)
        _resolved(world, madness)
        _deal(world, chosen[0], 3)
        _destroy_lethal(world)
    _resolved(world, madness)
    world.move(temper, "graveyard")

    # --- A resolution-time payment (spec 7.1): p1's Force Spike resolves; p0 may pay its {1} or lose the spell.
    #     (A plain Counterspell imposes no unless-payment, and Mana Leak's {3} would break the one-activation
    #     payment below.)
    bolt = _spell(world, "Lightning Bolt")
    _item(world, bolt).targets.append({"player": "p1"})
    counter = next(card for card in _zone(world, "p1", "hand") if world.objects[card].name == "Force Spike")
    world.move(counter, "stack")
    world.stack.append(StackItem(counter, "spell", None, [_target(bolt)]))

    def payment(pool_covers: bool) -> list[dict]:
        pays = [{"kind": "optional_cost", "source": _ref(counter), "cost": "unless_payment", "pay": pay}
                for pay in ((True, False) if pool_covers else (False,))]
        mana = [{"kind": "activate_mana_ability", "source": _ref(land), "ability_index": 0, "mana_choice": "R",
                 "cost_target": None} for land in _zone(world, "p0", "battlefield")
                if world.objects[land].name == "Mountain" and not world.objects[land].tapped]
        return pays + mana if pool_covers else mana + pays

    first = payment(False)                                 # the pool is empty: no pay: true yet (R2-22)
    yield from ask(Posed("p0", first, kind="choice", purpose="mana_payment", source=_ref(counter)), expect=first[0])
    world.objects[first[0]["source"]["$obj"]].tapped = True
    world.mana_pool["p0"]["R"] += 1
    answer = yield from ask(Posed("p0", payment(True), kind="choice", purpose="mana_payment", source=_ref(counter)))
    world.move(counter, "graveyard")
    if answer["kind"] == "optional_cost" and answer["pay"]:
        world.mana_pool["p0"]["R"] -= 1                    # paid: the Bolt resolves
        _deal(world, {"player": "p1"}, 3)
    world.move(bolt, "graveyard")
    world.priority_seat = "p0"

    # --- Three prowess triggers (Monastery Swiftspears cast off screen), ordered by two order_pick decisions. ---
    swiftspears = [world.add("Monastery Swiftspear", owner="p0", zone="battlefield", summoning_sick=True)
                   for _ in range(3)]
    yield from ask(Posed("p0", [PASS, _cast(preordain, "normal")]), expect=_cast(preordain, "normal"))
    world.move(preordain, "stack")
    world.stack.append(StackItem(preordain, "spell", None, []))
    world.priority_seat = None                             # triggers go on the stack before anyone gets priority
    ordered = []
    for position in range(2):                              # the last position is implied (spec 7.5; R2-9)
        answer = yield from ask(Posed("p0", [{"kind": "order_pick", "source": None, "purpose": "triggers",
                                              "item": {"trigger": {"source": _ref(swift),
                                                                   "source_name": "Monastery Swiftspear",
                                                                   "ability_index": 0,
                                                                   "event_objects": [_ref(preordain)],
                                                                   "instance": 0, "label": None}},
                                              "position": position, "count": 3}
                                             for swift in swiftspears if swift not in ordered],
                                      substep=(position, 2)))
        ordered.append(answer["item"]["trigger"]["source"]["$obj"])

    # --- Preordain resolves: scry 2 (one group of three), then draw. The prowess triggers resolved first. ---
    top = world.libraries["p0"][:2]
    ids = {card: world.look("p0", card) for card in top}
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": world.objects[card].name,
                          "object_id": None, "position_from_top": index, "position_from_bottom": None,
                          "how": "looked_at", "internal": card} for index, card in enumerate(top)]
    order = yield from _arrange(world, "p0", preordain, "scry", top, lambda index, placed: ("top", "bottom"), ids)
    world.end_looks("p0")                                  # before the library is reordered
    world.known["p0"] = []
    rest = world.libraries["p0"][2:]
    world.libraries["p0"][:] = order["top"] + rest + order["bottom"]
    _draw(world, "p0")
    world.move(preordain, "graveyard")
    world.priority_seat = "p0"

    # --- choose_replacement, offered while two replacement effects apply to one event (CR 616.1). ---
    yield from ask(Posed("p0", [{"kind": "choose_replacement", "affected": {"player": "p0"}, "event": "damage",
                                 "replacement_source": None, "replacement_index": index, "replacement_count": 2}
                                for index in (0, 1)]))

    # --- Turn 10 off screen: p1 destroys one Swiftspear and the Fathom Seer. Turn 11: combat. ---
    for creature in (swiftspears[2], seer):
        world.move(creature, "graveyard")
    for seat in ("p0", "p1"):
        world.mana_pool[seat] = dict.fromkeys(world.mana_pool[seat], 0)
        world.lands_played[seat] = 0
        for permanent in _zone(world, seat, "battlefield"):
            obj = world.objects[permanent]
            obj.tapped, obj.summoning_sick, obj.damage = False, False, 0
    _draw(world, "p1")
    _draw(world, "p0")
    world.turn, world.phase_step, world.priority_seat = 11, "declare_attackers", None   # a turn-based action
    attackers = _creatures(world, "p0")
    held_back = attackers[-1]                            # p0 declines to attack with the newest Swiftspear
    for index, creature in enumerate(attackers):           # the active player attacks (CR 508.1)
        defenders = (None, {"player": "p1"}) if creature == held_back else ({"player": "p1"}, None)
        answer = yield from ask(Posed("p0", [{"kind": "declare_attack", "attacker": _ref(creature), "defender": defender}
                                             for defender in defenders],
                                      substep=(index, len(attackers))))
        if answer["defender"] is not None:
            world.objects[creature].attack_target = answer["defender"]
            world.objects[creature].tapped = True
    attacking = [creature for creature in attackers if world.objects[creature].attack_target is not None]

    # Blocks: the defending player, one decision per potential blocker and one more for an additional block,
    # which the Night Market Guard's text ("can block an additional creature each combat") allows it to make.
    world.phase_step = "declare_blockers"
    blocks = [sprite, guard, guard]
    for index, blocker in enumerate(blocks):
        blocked = world.objects[blocker].blocking or []
        answer = yield from ask(Posed("p1", [{"kind": "declare_block", "blocker": _ref(blocker), "attacker": attacker}
                                             for attacker in [_ref(a) for a in attacking if a not in blocked] + [None]],
                                      substep=(index, len(blocks))))
        if answer["attacker"] is not None:
            world.objects[blocker].blocking = blocked + [answer["attacker"]["$obj"]]

    # Combat damage: each division is one distribute group, the attacking player's first (CR 510.1).
    world.phase_step = "combat_damage"
    assigned: list[tuple[dict, int]] = []
    blockers_of = {attacker: [b for b in dict.fromkeys(blocks) if attacker in (world.objects[b].blocking or [])]
                   for attacker in attacking}
    divisions = [("p0", attacker, blockers_of[attacker]) for attacker in attacking]
    divisions += [("p1", blocker, world.objects[blocker].blocking or []) for blocker in dict.fromkeys(blocks)]
    for seat, source, recipients in divisions:
        power = CARDS[world.objects[source].name]["power"]
        if len(recipients) < 2:                            # nothing to divide
            assigned += [(_target(recipient), power) for recipient in recipients]
            continue
        remaining = power
        for index, recipient in enumerate(recipients):
            last = index == len(recipients) - 1            # the last recipient takes the rest
            answer = yield from ask(Posed(seat, [{"kind": "distribute", "source": _ref(source),
                                                  "purpose": "combat_damage", "recipient": _target(recipient),
                                                  "amount": amount, "remaining": remaining}
                                                 for amount in ([remaining] if last else range(remaining + 1))],
                                          substep=(index, len(recipients))))
            assigned.append((_target(recipient), answer["amount"]))
            remaining -= answer["amount"]
    for target, amount in assigned:                        # dealt at once, then state-based actions
        _deal(world, target, amount)
    _destroy_lethal(world)
    for creature in _creatures(world, "p0", "p1"):        # combat ends (CR 506.4)
        world.objects[creature].attack_target = world.objects[creature].blocking = None
    world.phase_step, world.priority_seat = "postcombat_main", "p0"

    # --- A pile split (Fact or Fiction: p1 splits the top five, p0 chooses a pile). ---
    yield from ask(Posed("p0", [PASS, _cast(fact, "normal")]), expect=_cast(fact, "normal"))
    world.move(fact, "stack")
    world.stack.append(StackItem(fact, "spell", None, []))
    world.priority_seat = None
    revealed = world.libraries["p0"][:5]
    looks = {seat: {card: world.look(seat, card) for card in revealed} for seat in ("p0", "p1")}
    for seat in ("p0", "p1"):
        world.known[seat] = [{"owner_seat": "p0", "zone": "library", "card_name": world.objects[card].name,
                              "object_id": None, "position_from_top": index, "position_from_bottom": None,
                              "how": "revealed", "internal": card} for index, card in enumerate(revealed)]

    def pile_first(index: int, placed: dict) -> tuple[str, str]:   # the smaller pile so far first
        sizes = [sum(d == pile for d in placed.values()) for pile in ("pile_0", "pile_1")]
        return ("pile_1", "pile_0") if sizes[1] < sizes[0] else ("pile_0", "pile_1")

    piles = yield from _arrange(world, "p1", fact, "pile_split", revealed, pile_first, looks["p1"])
    split = [[_ref(card) for card in piles["pile_0"]], [_ref(card) for card in piles["pile_1"]]]
    answer = yield from ask(Posed("p0", [{"kind": "choose_pile", "source": _ref(fact), "purpose": "effect",
                                          "pile_index": index, "piles": split} for index in (0, 1)],
                                  source=_ref(fact)))
    for seat in ("p0", "p1"):
        world.end_looks(seat)
        world.known[seat] = []
    for index, pile in enumerate(("pile_0", "pile_1")):
        for card in piles[pile]:
            world.move(card, "hand" if index == answer["pile_index"] else "graveyard")
    world.move(fact, "graveyard")
    world.priority_seat = "p0"

    # --- The rewind (spec 8): Chainer's Edict cast with flashback from the graveyard; its {5}{B}{B} cannot be
    #     paid, so the cast is undone and priority is re-posed without it. ---
    flashback = _cast(edict, "flashback")
    yield from ask(Posed("p0", [PASS, flashback]), expect=flashback)
    world.move(edict, "stack")
    world.stack.append(StackItem(edict, "spell", None, []))
    yield from _choose_targets(world, "p0", edict, 0, [{"player": "p1"}, {"player": "p0"}], 1, 1)
    world.move(edict, "graveyard")
    yield Posed("p0", [PASS], rewind=True)


DECKLIST = [
    {"name": "Mountain", "count": 8}, {"name": "Island", "count": 10}, {"name": SPIKEFIELD, "count": 1},
    {"name": "Fathom Seer", "count": 1}, {"name": "Relic of Progenitus", "count": 1},
    {"name": "Evolving Wilds", "count": 1}, {"name": "Grizzly Bears", "count": 2},
    {"name": "Night Market Guard", "count": 1},
    {"name": "Spellstutter Sprite", "count": 1}, {"name": "Monastery Swiftspear", "count": 3},
    {"name": "Ghostly Flicker", "count": 1}, {"name": "Forked Bolt", "count": 1}, {"name": "Cryptic Command", "count": 1},
    {"name": "Borrowed Hostility", "count": 1}, {"name": "Fireball", "count": 1}, {"name": "Pithing Needle", "count": 1},
    {"name": "Faithless Looting", "count": 1}, {"name": "Fiery Temper", "count": 1}, {"name": "Chainer's Edict", "count": 1},
    {"name": "Burst Lightning", "count": 2}, {"name": "Lightning Bolt", "count": 4}, {"name": "Counterspell", "count": 3},
    {"name": "Force Spike", "count": 1},
    {"name": "Brainstorm", "count": 4}, {"name": "Preordain", "count": 1}, {"name": "Fact or Fiction", "count": 1},
]

SCENARIO = Scenario(
    name="kinds",
    decklist=DECKLIST,
    engine_args=("--london", "--toss", "--rewind"),
    script=_script,
)
