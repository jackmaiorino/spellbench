"""The board tour (Task 26): one scripted game whose board carries every field of spec 6.2 to 6.6
and every optional field of spec 6.9 (R2-10), played from p0's seat.

Public state (life, poison, counters, mana pool, progress, the battlefield, graveyards, exile,
command and the stack) is visible to p0 in its own observation whichever seat holds it, so one
seat's tour is enough to show both players' fields at once. The World nulls out every optional
field on its own when the engine does not declare its flag (spec 6.9), so this script builds one
rich board regardless of how the engine (``--all-flags`` or no flags) was started; play_tour reuses
it for both.
"""

from __future__ import annotations

from fake_v2_world import Posed, Scenario, StackItem

PASS = {"kind": "pass"}


def _script(world):
    # --- Pregame: a seven-card hand, kept (turn 0, both seats null, spec 6.2). ---
    world.turn, world.phase_step = 0, "pregame"
    world.active_seat = world.priority_seat = None
    for _ in range(7):
        world.add("Mountain", owner="p0", zone="hand")
    yield Posed("p0", [{"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True},
                       {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": False}])

    world.turn, world.phase_step, world.active_seat, world.priority_seat = 1, "precombat_main", "p0", "p0"

    # --- Game-level fields (spec 6.2): passed seats, day (then night below), knowledge. ---
    world.passed_seats = ["p0"]
    world.day_night = "day"
    lib_card = world.add("Island", owner="p0", zone="library")
    world.look("p0", lib_card)
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": "Island", "object_id": None,
                          "position_from_top": 0, "position_from_bottom": None, "how": "looked_at", "internal": lib_card}]

    # --- Player fields (spec 6.3): poison, counters, mana, lands played, mulligans, designations, progress. ---
    world.poison["p0"] = 3
    world.counters["p0"] = {"energy": 2}
    world.mana_pool["p0"]["R"] = 1
    world.lands_played["p0"] = 1
    world.mulligans["p1"] = 1                             # "one mulligan taken by p1"
    world.designations["p0"] = ["monarch"]
    world.progress["p0"] = {"dungeon": None, "dungeon_room": "Cave Entrance", "ring_tempted": 1, "speed": 2}
    world.add("Lightning Bolt", owner="p0", zone="graveyard")
    world.add("Chandra, Torch of Defiance Emblem", owner="p0", zone="command")

    # --- Pending triggers (spec 6.6): one visible, one from a card in p1's hand that p0's list omits. ---
    relic = world.add("Relic of Progenitus", owner="p0", zone="battlefield")
    world.pending_triggers.append({"source": relic, "source_name": "Relic of Progenitus", "controller_seat": "p0",
                                   "label": None, "optional": False})
    hidden_source = world.add("Fiery Temper", owner="p1", zone="hand")
    world.pending_triggers.append({"source": hidden_source, "source_name": "Fiery Temper", "controller_seat": "p1",
                                   "label": None, "optional": True})

    # --- Object records (spec 6.4): a modal double-faced card's full_name, tapped, phased out, counters. ---
    world.add("Spikefield Cave", owner="p0", zone="battlefield", tapped=True, phased_out=True, counters={"charge": 1})

    # A face-down creature of each seat: p0 sees its own name, p1's shows card_name null (CR 708.5).
    world.add("Fathom Seer", owner="p0", zone="battlefield", face_down=True)
    world.add("Fathom Seer", owner="p1", zone="battlefield", face_down=True)

    # A face-down exiled card p0 may not look at: characteristics null too (spec 6.4, 6.8).
    world.add("Fathom Seer", owner="p1", zone="exile", face_down=True)

    # A creature exiled with a returning link (spec 6.4).
    journey = world.add("Journey to Nowhere", owner="p0", zone="battlefield")
    world.add("Grizzly Bears", owner="p1", zone="exile", exiled_by=journey)

    # A token copy.
    world.add("Grizzly Bears", owner="p0", zone="battlefield", token=True, copy=True)

    # Summoning sick, marked damage, permanent counters, all on one creature.
    world.add("Grizzly Bears", owner="p0", zone="battlefield", summoning_sick=True, damage=2, counters={"p1p1": 1})

    # An Aura, attached.
    aura_target = world.add("Grizzly Bears", owner="p0", zone="battlefield")
    world.add("Rancor", owner="p0", zone="battlefield", attached_to={"object": {"$obj": aura_target}})

    # A creature attacking a planeswalker.
    chandra = world.add("Chandra, Torch of Defiance", owner="p1", zone="battlefield", counters={"loyalty": 4})
    world.add("Monastery Swiftspear", owner="p0", zone="battlefield", tapped=True,
              attack_target={"object": {"$obj": chandra}})

    # A blocker with blocked_attackers; Spellstutter Sprite also carries keywords (flash, flying).
    attacker = world.add("Spellstutter Sprite", owner="p1", zone="battlefield")
    world.add("Grizzly Bears", owner="p0", zone="battlefield", blocking=[attacker])

    # Goaded.
    world.add("Grizzly Bears", owner="p1", zone="battlefield", statuses=["goaded"])

    # A Class at level 2.
    world.add("Barbarian Class", owner="p0", zone="battlefield", class_level=2)

    # A chosen card name.
    world.add("Pithing Needle", owner="p0", zone="battlefield", chosen=[{"kind": "card_name", "value": "Rancor"}])

    # --- Stack entries (spec 6.5): a spell, an activated ability, a triggered ability whose source has left. ---
    face_down_spell = world.add("Forked Bolt", owner="p0", zone="stack", face_down=True, copy=True)
    world.stack.append(StackItem(face_down_spell, "spell", None, [None, {"player": "p1"}],
                                 divided=[1, 1], modes=[0], x_value=2, text="deals damage divided as chosen"))
    ability_source = world.add("Relic of Progenitus", owner="p0", zone="battlefield")
    ability = world.add("Relic of Progenitus", owner="p0", zone="stack")
    world.stack.append(StackItem(ability, "activated_ability", ability_source, [{"player": "p1"}],
                                 text="exile all graveyards"))
    departed_trigger = world.add("Lightning Bolt", owner="p0", zone="stack")
    world.stack.append(StackItem(departed_trigger, "triggered_ability", None, []))

    yield Posed("p0", [PASS])            # the "day" snapshot: every feature above

    world.day_night = "night"
    yield Posed("p0", [PASS])            # the "night" snapshot


SCENARIO = Scenario(
    name="board",
    decklist=[{"name": "Mountain", "count": 20}, {"name": "Island", "count": 4}, {"name": "Lightning Bolt", "count": 4},
              {"name": "Fiery Temper", "count": 2}, {"name": "Relic of Progenitus", "count": 2},
              {"name": "Spikefield Cave", "count": 1}, {"name": "Fathom Seer", "count": 3},
              {"name": "Journey to Nowhere", "count": 1}, {"name": "Grizzly Bears", "count": 6},
              {"name": "Rancor", "count": 1}, {"name": "Chandra, Torch of Defiance", "count": 1},
              {"name": "Monastery Swiftspear", "count": 1}, {"name": "Spellstutter Sprite", "count": 1},
              {"name": "Barbarian Class", "count": 1}, {"name": "Pithing Needle", "count": 1},
              {"name": "Forked Bolt", "count": 1}, {"name": "Chandra, Torch of Defiance Emblem", "count": 1}],
    engine_args=("--london",),
    script=_script,
)
