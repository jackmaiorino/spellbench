"""The board tour (Task 26): a scripted game whose decisions show every field of spec 6.2 to 6.6 and every
optional field of spec 6.9 (R2-10), read from p0's seat after a pregame in which both seats are asked.

Public state (life, poison, counters, mana pool, progress, the battlefield, graveyards, exile, command and the
stack) is visible to p0 whichever seat holds it, so p0's decisions show both players' fields. The World nulls
every optional field whose flag the engine does not declare (spec 6.9), so the same script serves the
``--all-flags`` run and the run without flags.

Decisions after the pregame (each a legal state, the turns between them off screen): turn 5 opens with p0
ordering the two triggers its just-cast Fireball set off — the one window in which a trigger can still be
waiting to go on the stack (spec 6.6, CR 117.5 and 603.3); then, the stack built and both seats passed, p0
chooses the card p1's Relic of Progenitus ability exiles as it resolves; turn 5 again, in the declare
blockers step (an attack on a planeswalker, a blocker and the attacker it blocks); and turn 7, which became
night because p1 cast no spell in turn 6 (CR 730.2), with a face-down spell on the stack.
Answers: candidate 0 (the tour has no ``pick``); ``ask`` stops the tour loudly if the pregame is answered
otherwise.
"""

from __future__ import annotations

from fake_v2_scenario_kinds import SPIKEFIELD, ask
from fake_v2_world import Posed, Scenario, StackItem

PASS = {"kind": "pass"}


def _mulligan(hand_size: int, taken: int, keep: bool) -> dict:
    return {"kind": "mulligan", "hand_size": hand_size, "mulligans_taken": taken, "keep": keep}


def _hand(world, seat: str) -> list[int]:
    return [internal for internal, obj in world.objects.items() if obj.zone == "hand" and obj.owner == seat]


def _draw(world, seat: str, count: int) -> None:
    for card in world.libraries[seat][:count]:
        world.move(card, "hand")


def _to_bottom(world, card: int) -> None:
    library = world.libraries[world.objects[card].owner]
    world.move(card, "library", library_position=len(library) - (card in library))


def _script(world):
    # --- Pregame (turn 0, both seats null, spec 6.2): p0 keeps its seven; p1 takes one mulligan (London). ---
    world.turn, world.phase_step, world.active_seat, world.priority_seat = 0, "pregame", None, None
    for name in ("Mountain",) * 7 + ("Island",) * 3:
        world.add(name, owner="p0", zone="library")
    for name in ("Island", "Island", "Mountain", "Lightning Bolt", "Grizzly Bears", "Island", "Mountain") * 2:
        world.add(name, owner="p1", zone="library")
    _draw(world, "p0", 7)
    _draw(world, "p1", 7)
    yield from ask(Posed("p0", [_mulligan(7, 0, True), _mulligan(7, 0, False)]), expect=_mulligan(7, 0, True))
    yield from ask(Posed("p1", [_mulligan(7, 0, False), _mulligan(7, 0, True)]), expect=_mulligan(7, 0, False))
    for card in _hand(world, "p1"):                        # shuffled away, and a new seven drawn (CR 103.5)
        _to_bottom(world, card)
    world.mulligans["p1"] = 1
    _draw(world, "p1", 7)
    yield from ask(Posed("p1", [_mulligan(7, 1, True), _mulligan(7, 1, False)]), expect=_mulligan(7, 1, True))
    answer = yield from ask(Posed("p1", [{"kind": "order_pick", "source": None, "purpose": "mulligan_bottom",
                                          "item": {"object": {"$obj": card}}, "position": 0, "count": 1}
                                         for card in _hand(world, "p1")]))
    _to_bottom(world, answer["item"]["object"]["$obj"])

    # --- Turn 5, p0's precombat main (turns 1 to 4 off screen). ---
    world.turn, world.phase_step, world.active_seat = 5, "precombat_main", "p0"
    world.day_night = "day"
    # Knowledge (spec 6.7): p0 looked at its top card earlier. Name-level, so shown only under known_cards.
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": "Island", "object_id": None,
                          "position_from_top": 0, "position_from_bottom": None, "how": "looked_at"}]
    # Player fields (spec 6.3).
    world.poison["p0"] = 3
    world.counters["p0"] = {"energy": 2}
    world.mana_pool["p0"]["R"] = 1
    world.lands_played["p0"] = 1
    world.designations["p0"] = ["monarch"]
    world.progress["p0"] = {"dungeon": "Lost Mine of Phandelver", "dungeon_room": "Cave Entrance",
                            "ring_tempted": 1, "speed": 2}
    world.add("Lightning Bolt", owner="p0", zone="graveyard")
    world.add("Rancor", owner="p0", zone="graveyard")      # its enchanted creature died this turn
    emblem = world.add("Chandra, Torch of Defiance Emblem", owner="p0", zone="command")   # not a deck card
    # Object records (spec 6.4): a modal double-faced land (full_name), tapped, phased out, with a counter.
    world.add("Spikefield Cave", owner="p0", zone="battlefield", tapped=True, phased_out=True, counters={"charge": 1})
    # A face-down creature of each seat: p0 sees its own name, p1's shows card_name null (CR 708.5).
    world.add("Fathom Seer", owner="p0", zone="battlefield", face_down=True)
    world.add("Fathom Seer", owner="p1", zone="battlefield", face_down=True)
    # A face-down exiled card p0 may not look at: characteristics null too (spec 6.4, 6.8).
    world.add("Fathom Seer", owner="p1", zone="exile", face_down=True)
    journey = world.add("Journey to Nowhere", owner="p0", zone="battlefield")
    world.add("Grizzly Bears", owner="p1", zone="exile", exiled_by=journey)        # it may return the card
    world.add("Grizzly Bears", owner="p0", zone="battlefield", token=True, copy=True)
    world.add("Grizzly Bears", owner="p0", zone="battlefield", summoning_sick=True, damage=1, counters={"p1p1": 1})
    bears = world.add("Grizzly Bears", owner="p0", zone="battlefield")
    world.add("Rancor", owner="p0", zone="battlefield", attached_to={"object": {"$obj": bears}})
    swiftspear = world.add("Monastery Swiftspear", owner="p0", zone="battlefield")
    world.add("Barbarian Class", owner="p0", zone="battlefield", class_level=2)
    world.add("Pithing Needle", owner="p0", zone="battlefield", chosen=[{"kind": "card_name", "value": "Rancor"}])
    chandra = world.add("Chandra, Torch of Defiance", owner="p1", zone="battlefield", counters={"loyalty": 4})
    sprite = world.add("Spellstutter Sprite", owner="p1", zone="battlefield")
    world.add("Grizzly Bears", owner="p1", zone="battlefield", statuses=["goaded"])
    relic = world.add("Relic of Progenitus", owner="p1", zone="battlefield", tapped=True)

    # p0 has just cast its Fireball (X 2), a red noncreature spell: the Swiftspear's prowess trigger and
    # the trigger of p0's red-spell emblem are waiting to go on the stack (spec 6.6). A waiting trigger
    # goes on the stack before anyone next receives priority (CR 117.5, 603.3), so an observation can
    # show one only in a window without priority — here, while p0 orders its two triggers. The Relic
    # decision below can therefore show none pending.
    fireball = world.add("Fireball", owner="p0", zone="stack")
    world.stack.append(StackItem(fireball, "spell", None, [{"player": "p1"}], x_value=2))
    waiting = ((swiftspear, "Monastery Swiftspear"), (emblem, "Chandra, Torch of Defiance Emblem"))
    world.pending_triggers = [{"source": source, "source_name": name, "controller_seat": "p0", "label": None,
                               "optional": False} for source, name in waiting]
    yield from ask(Posed("p0", [{"kind": "order_pick", "source": None, "purpose": "triggers",
                                 "item": {"trigger": {"source": {"$obj": source}, "source_name": name,
                                                      "ability_index": 0, "event_objects": [{"$obj": fireball}],
                                                      "instance": 0, "label": None}},
                                 "position": 0, "count": 2} for source, name in waiting]))

    # Off screen the two triggers go on the stack and resolve, and the stack (spec 6.5) builds on the
    # Fireball, bottom first: a copy of p0's Forked Bolt whose first target left, with the damage divided
    # as announced; p1's Cryptic Command (modes: counter target spell, draw a card) countering the
    # Fireball; p0's Rancor trigger, whose source left the battlefield; and p1's Relic ability. Both seats
    # passed, so the Relic ability resolves now.
    world.pending_triggers = []
    copy = world.add("Forked Bolt", owner="p0", zone="stack", copy=True)
    world.stack.append(StackItem(copy, "spell", None, [{"object": None}, {"player": "p1"}], divided=[1, 1],
                                 text="Forked Bolt deals 2 damage divided as you choose among one or two targets."))
    cryptic = world.add("Cryptic Command", owner="p1", zone="stack")
    world.stack.append(StackItem(cryptic, "spell", None, [{"object": {"$obj": fireball}}], modes=[0, 3]))
    rancor_trigger = world.add("Rancor", owner="p0", zone="stack")
    world.stack.append(StackItem(rancor_trigger, "triggered_ability", None, []))
    ability = world.add("Relic of Progenitus", owner="p1", zone="stack")
    world.stack.append(StackItem(ability, "activated_ability", relic, [{"player": "p0"}],
                                 text="Target player exiles a card from their graveyard."))
    world.passed_seats = ["p0", "p1"]                      # both passed: the Relic ability resolves
    graveyard = [internal for internal, obj in world.objects.items() if obj.zone == "graveyard" and obj.owner == "p0"]
    answer = yield from ask(Posed("p0", [{"kind": "select_object", "source": {"$obj": ability}, "purpose": "exile",
                                          "choice": {"object": {"$obj": card}}, "selected_count": 0, "minimum": 1,
                                          "maximum": 1} for card in graveyard], source={"$obj": ability}))
    world.move(answer["choice"]["object"]["$obj"], "exile")

    # Off screen: the stack resolves top first. Rancor returns to its owner's hand, the copy deals its 1
    # damage to p1 and ceases to exist, the Cryptic Command counters the Fireball and p1 draws; combat begins.
    world.stack.clear()
    for card, obj in list(world.objects.items()):
        if obj.zone == "graveyard" and obj.name == "Rancor":
            world.move(card, "hand")
    world.life["p1"] -= 1
    for spell in (fireball, cryptic):
        world.move(spell, "graveyard")
    _draw(world, "p1", 1)
    world.passed_seats, world.known["p0"] = [], []
    world.mana_pool["p0"]["R"] = 0
    # --- Turn 5, declare blockers step: p0's Swiftspear attacks Chandra, and its Bears, blocked by the Sprite. ---
    world.phase_step, world.priority_seat = "declare_blockers", "p0"
    for attacker, defender in ((swiftspear, {"object": {"$obj": chandra}}), (bears, {"player": "p1"})):
        world.objects[attacker].attack_target, world.objects[attacker].tapped = defender, True
    world.objects[sprite].blocking = [bears]
    yield from ask(Posed("p0", [PASS]))

    # --- Turn 7, night: p1 cast no spell in turn 6. p0 has just cast a face-down Fathom Seer (morph). ---
    for obj in world.objects.values():                   # combat ended; the untap steps of turns 6 and 7
        if obj.zone == "battlefield":
            obj.attack_target = obj.blocking = None
            obj.tapped, obj.phased_out, obj.damage, obj.summoning_sick = False, False, 0, False
    world.turn, world.phase_step, world.day_night = 7, "precombat_main", "night"
    world.lands_played["p0"] = 0
    morph = world.add("Fathom Seer", owner="p0", zone="stack", face_down=True)
    world.stack.append(StackItem(morph, "spell", None, []))     # a textless 2/2: no target, mode or X (CR 708.4)
    yield from ask(Posed("p0", [PASS]))


SCENARIO = Scenario(
    name="board",
    decklist=[{"name": "Mountain", "count": 16}, {"name": "Island", "count": 8}, {"name": SPIKEFIELD, "count": 1},
              {"name": "Lightning Bolt", "count": 2}, {"name": "Relic of Progenitus", "count": 1},
              {"name": "Fathom Seer", "count": 2},
              {"name": "Journey to Nowhere", "count": 1}, {"name": "Grizzly Bears", "count": 4},
              {"name": "Rancor", "count": 2}, {"name": "Chandra, Torch of Defiance", "count": 1},
              {"name": "Monastery Swiftspear", "count": 1}, {"name": "Spellstutter Sprite", "count": 1},
              {"name": "Barbarian Class", "count": 1}, {"name": "Pithing Needle", "count": 1},
              {"name": "Forked Bolt", "count": 1}, {"name": "Fireball", "count": 1}, {"name": "Cryptic Command", "count": 1}],
    engine_args=("--london",),
    script=_script,
)
