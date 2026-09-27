"""The scenario runner's own test scenario (Task 21): group numbering, counting, a rewind, a context override."""

from __future__ import annotations

from fake_v2_world import Posed, Scenario, StackItem

PASS = {"kind": "pass"}


def _script(world):
    bolt = world.add("Lightning Bolt", owner="p0", zone="hand")
    islands = [world.add("Island", owner="p0", zone="hand") for _ in range(2)]
    mountain = world.add("Mountain", owner="p0", zone="battlefield")
    swiftspear = world.add("Monastery Swiftspear", owner="p0", zone="battlefield")
    bears = world.add("Grizzly Bears", owner="p1", zone="battlefield")
    # A two-substep group: a fixed discard of two, one pick per substep.
    for index in range(2):
        picked = yield Posed("p0", [{"kind": "select_object", "source": None, "purpose": "discard",
                                     "choice": {"object": {"$obj": card}}, "selected_count": index,
                                     "minimum": 2, "maximum": 2} for card in islands], substep=(index, 2))
        world.move(islands.pop(picked), "graveyard")
    # A non-pass priority action: Lightning Bolt is cast.
    yield Posed("p0", [PASS, {"kind": "cast_spell", "source": {"$obj": bolt}, "method": "normal"}])
    world.move(bolt, "stack")
    world.stack.append(StackItem(bolt, "spell", None, []))
    # One completed choice group: its target.
    yield Posed("p0", [{"kind": "choose_target", "source": {"$obj": bolt}, "slot": 0, "target": target,
                        "selected_count": 0, "minimum": 1, "maximum": 1}
                       for target in ({"player": "p1"}, {"object": {"$obj": bears}})], source={"$obj": bolt})
    # A partial group: an additional cost of two sacrifices, abandoned after its first pick.
    yield Posed("p0", [{"kind": "choose_cost_target", "source": {"$obj": bolt}, "cost_kind": "sacrifice",
                        "candidate": {"$obj": permanent}, "selected_count": 0, "minimum": 2, "maximum": 2}
                       for permanent in (mountain, swiftspear)], substep=(0, 2), source={"$obj": bolt})
    # The rewind: the cast cannot be completed, so it is undone and priority re-posed without it (spec 8).
    world.stack.clear()
    world.move(bolt, "hand")
    yield Posed("p0", [PASS], rewind=True)
    # A context override: a mana ability offered in a choice decision to pay a cost (spec 7.1).
    yield Posed("p0", [{"kind": "activate_mana_ability", "source": {"$obj": mountain}, "ability_index": 0,
                        "mana_choice": "R", "cost_target": None},
                       {"kind": "optional_cost", "source": {"$obj": swiftspear}, "cost": "unless_payment", "pay": False}],
                kind="choice", purpose="mana_payment")


SCENARIO = Scenario(
    name="smoke",
    decklist=[{"name": "Grizzly Bears", "count": 4}, {"name": "Island", "count": 16}, {"name": "Lightning Bolt", "count": 4},
              {"name": "Monastery Swiftspear", "count": 4}, {"name": "Mountain", "count": 16}],
    engine_args=("--rewind",),
    script=_script,
)
