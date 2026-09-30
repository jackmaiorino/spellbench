"""The fake engine's board model keeps the spec's id and visibility rules."""

from __future__ import annotations

import copy
import unicodedata

import pytest

from spellbench.run_secret import RunSecret

from fake_v2_world import CARDS, Posed, Scenario, StackItem, World

GAME0 = RunSecret(bytes(range(32))).game_secret(0)
FLAGS_OFF = dict.fromkeys(("poison", "player_counters", "designations", "player_progress", "day_night", "passed_seats",
                           "pending_triggers", "keywords", "full_name", "exiled_by", "stack_text", "permanent_details",
                           "known_cards"), False)


def test_ids_follow_the_spec_16_vectors() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    world.add("Island", owner="p0", zone="library", internal=17)
    world.move(17, "hand")
    world.move(17, "library")                       # two zone changes: "card-17:z2"
    assert world.look("p0", 17) == "o-794a5cb152c9620f"
    assert world.look("p0", 17) == "o-794a5cb152c9620f"   # stable within one effect
    world.end_looks("p0")
    assert world.look("p0", 17) == "o-e18a35822cc60e1c"   # fresh on the next look
    visible = World(GAME0, flags=FLAGS_OFF)                # the plain-id vector: a visible object at z2
    visible.add("Island", owner="p0", zone="hand", internal=17)
    visible.move(17, "graveyard")
    visible.move(17, "exile")
    assert (visible.object_id("p0", 17), visible.object_id("p1", 17)) == ("o-0a3647243d16bf78", "o-e5e4b7ed2a0730e4")


def test_a_zone_change_gives_a_fresh_id_per_viewer() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    bears = world.add("Grizzly Bears", owner="p1", zone="battlefield")
    before = {seat: world.object_id(seat, bears) for seat in ("p0", "p1")}
    world.move(bears, "graveyard")
    after = {seat: world.object_id(seat, bears) for seat in ("p0", "p1")}
    assert before["p0"] != before["p1"] and all(before[seat] != after[seat] for seat in ("p0", "p1"))


def test_hidden_information_stays_hidden() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    world.add("Counterspell", owner="p1", zone="hand")
    morph = world.add("Grizzly Bears", owner="p1", zone="battlefield", face_down=True)
    world.add("Mountain", owner="p0", zone="library")
    view = world.observation("p0")
    assert view["players"][1]["hand"] is None and view["players"][1]["hand_count"] == 1
    (record,) = view["players"][1]["battlefield"]
    assert record["card_name"] is None and record["characteristics"]["power"] == 2 and record["characteristics"]["colors"] == []
    assert world.observation("p1")["players"][1]["battlefield"][0]["card_name"] == "Grizzly Bears"
    assert all(entry["zone"] != "library" for player in view["players"] for zone in ("battlefield", "graveyard", "exile", "command")
               for entry in player[zone])
    world.move(morph, "graveyard")
    assert world.reference("p0", morph)["zone"] == "graveyard"


def test_optional_fields_follow_the_flags() -> None:
    off = World(GAME0, flags=FLAGS_OFF).observation("p0")
    assert off["day_night"] is None and off["passed_seats"] is None and off["pending_triggers"] is None
    assert off["players"][0]["poison"] is None and off["known"] == []
    on = World(GAME0, flags=dict.fromkeys(FLAGS_OFF, True)).observation("p0")
    assert on["day_night"] in ("day", "night", "none") and on["passed_seats"] == [] and on["players"][0]["poison"] == 0
    assert on["players"][0]["progress"] == {"dungeon": None, "dungeon_room": None, "ring_tempted": 0, "speed": None}
    assert (on["turn"], on["phase_step"], on["active_seat"]) == (1, "precombat_main", "p0")       # R1-10 defaults


def test_known_entries_follow_the_looks_and_the_flag() -> None:
    world = World(GAME0, flags={**FLAGS_OFF, "known_cards": True})
    island = world.add("Island", owner="p0", zone="library")
    world.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": "Island", "object_id": None,
                          "position_from_top": 0, "position_from_bottom": None, "how": "looked_at", "internal": island}]
    look = world.look("p0", island)
    assert world.observation("p0")["known"][0]["object_id"] == look                # in the current looks: its look id
    world.end_looks("p0")
    (entry,) = world.observation("p0")["known"]
    assert entry["object_id"] is None and "internal" not in entry                  # the look ended: stripped
    blind = World(GAME0, flags=FLAGS_OFF)                                          # known_cards off (R2-6)
    card = blind.add("Island", owner="p0", zone="library")
    blind.known["p0"] = [{"owner_seat": "p0", "zone": "library", "card_name": "Island", "object_id": None,
                          "position_from_top": 0, "position_from_bottom": None, "how": "looked_at", "internal": card}]
    assert blind.observation("p0")["known"] == []                                  # not looked at in this decision
    blind.look("p0", card)
    assert [entry["object_id"] for entry in blind.observation("p0")["known"]] == [blind.look("p0", card)]


def test_a_face_down_exiled_card_hides_its_characteristics_too() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    world.add("Grizzly Bears", owner="p1", zone="exile", face_down=True)
    (record,) = world.observation("p0")["players"][1]["exile"]
    assert record["card_name"] is None and record["characteristics"] is None      # R1-13


# Beyond the brief's tests: the hooks the fake engine and its tours build on.

FLAGS_ON = dict.fromkeys(FLAGS_OFF, True)
VAULT = "Lim-D" + chr(0xFB) + "l's Vault"                                          # NFC, as spec 16 writes it
COLOR_ORDER = ("white", "blue", "black", "red", "green")                            # spec 6.4


def _named(view: dict, seat: int, zone: str) -> dict[str, dict]:
    return {record["card_name"]: record for record in view["players"][seat][zone]}


def test_references_to_an_object_that_left_become_null() -> None:
    world = World(GAME0, flags=FLAGS_ON)
    walker = world.add("Chandra, Torch of Defiance", owner="p1", zone="battlefield", counters={"loyalty": 4})
    world.add("Monastery Swiftspear", owner="p0", zone="battlefield", attack_target={"object": {"$obj": walker}})
    bears = world.add("Grizzly Bears", owner="p0", zone="battlefield", attack_target={"player": "p1"})
    world.add("Rancor", owner="p0", zone="battlefield", attached_to={"object": {"$obj": bears}})
    world.add("Spellstutter Sprite", owner="p1", zone="battlefield", blocking=[bears])
    journey = world.add("Journey to Nowhere", owner="p0", zone="battlefield")
    world.add("Fathom Seer", owner="p1", zone="exile", exiled_by=journey)
    bolt = world.add("Lightning Bolt", owner="p0", zone="stack")
    world.stack.append(StackItem(bolt, "spell", None, [{"object": {"$obj": walker}}]))
    world.pending_triggers.append({"source": journey, "source_name": "Journey to Nowhere", "controller_seat": "p0",
                                   "label": None, "optional": False})
    view = world.observation("p0")
    mine, theirs = _named(view, 0, "battlefield"), _named(view, 1, "battlefield")
    walker_ref, bears_ref, journey_ref = (world.reference("p0", n) for n in (walker, bears, journey))
    assert mine["Monastery Swiftspear"]["permanent"]["attack_target"] == {"object": walker_ref}
    assert view["stack"][0]["targets"] == [{"object": walker_ref}]
    assert mine["Rancor"]["permanent"]["attached_to"] == {"object": bears_ref}
    assert theirs["Spellstutter Sprite"]["permanent"]["blocked_attackers"] == [bears_ref]
    assert _named(view, 1, "exile")["Fathom Seer"]["exiled_by"] == view["pending_triggers"][0]["source"] == journey_ref
    world.move(walker, "graveyard")
    world.move(bears, "hand")
    world.move(journey, "graveyard")
    view = world.observation("p0")
    mine, theirs = _named(view, 0, "battlefield"), _named(view, 1, "battlefield")
    swiftspear, sprite = mine["Monastery Swiftspear"]["permanent"], theirs["Spellstutter Sprite"]["permanent"]
    assert (swiftspear["attacking"], swiftspear["attack_target"]) == (True, None)          # spec 6.4
    assert view["stack"][0]["targets"] == [None]                                            # spec 6.5
    assert mine["Rancor"]["permanent"]["attached_to"] is None
    assert (sprite["blocking"], sprite["blocked_attackers"]) == (True, [])                 # CR 509.1h
    assert _named(view, 1, "exile")["Fathom Seer"]["exiled_by"] is None
    trigger = view["pending_triggers"][0]
    assert (trigger["source"], trigger["source_name"]) == (None, "Journey to Nowhere")
    assert world.reference("p0", walker)["object_id"] != walker_ref["object_id"]            # a new object (spec 5.3)


def test_every_optional_field_follows_its_flag() -> None:
    def optional_values(flags: dict) -> list:
        world = World(GAME0, flags=flags)
        world.add("Spikefield Hazard", owner="p0", zone="hand")
        journey = world.add("Journey to Nowhere", owner="p0", zone="battlefield")
        world.add("Barbarian Class", owner="p0", zone="battlefield")
        world.add("Grizzly Bears", owner="p1", zone="exile", exiled_by=journey)
        bolt = world.add("Lightning Bolt", owner="p0", zone="stack")
        world.stack.append(StackItem(bolt, "spell", None, [{"player": "p1"}], text="3 damage to p1"))
        world.pending_triggers.append({"source": journey, "source_name": "Journey to Nowhere", "controller_seat": "p0",
                                       "label": None, "optional": False})
        view = world.observation("p0")
        (hazard,), (_, barbarian), (exiled,) = (view["players"][0]["hand"], view["players"][0]["battlefield"],
                                                view["players"][1]["exile"])
        game = [view[name] for name in ("passed_seats", "day_night", "pending_triggers")]
        players = [player[name] for player in view["players"]
                   for name in ("poison", "counters", "designations", "progress")]
        records = [hazard["full_name"], exiled["exiled_by"], hazard["characteristics"]["keywords"]]
        details = [barbarian["permanent"][name] for name in ("statuses", "class_level", "chosen")]
        return game + players + records + [view["stack"][0]["text"]] + details

    assert all(value is None for value in optional_values(FLAGS_OFF))                         # spec 6.9
    assert all(value is not None for value in optional_values(FLAGS_ON))


def test_stack_entries_resolve_per_viewer() -> None:
    world = World(GAME0, flags=FLAGS_ON)
    relic = world.add("Relic of Progenitus", owner="p0", zone="battlefield")
    ability = world.add("Relic of Progenitus", owner="p0", zone="stack")                   # named after its source
    world.stack.append(StackItem(ability, "activated_ability", relic, [{"player": "p1"}], text="p1 exiles a card"))
    seer = world.add("Fathom Seer", owner="p1", zone="stack", face_down=True)              # cast face down
    world.stack.append(StackItem(seer, "spell", None, []))
    bolt = world.add("Forked Bolt", owner="p0", zone="stack", copy=True)
    world.stack.append(StackItem(bolt, "spell", None, [{"player": "p1"}, {"object": {"$obj": relic}}], divided=[1, 1]))
    activated, face_down, copied = world.observation("p0")["stack"]
    assert (activated["card_name"], activated["source"], activated["characteristics"], activated["text"]) == (
        "Relic of Progenitus", world.reference("p0", relic), None, "p1 exiles a card")
    assert face_down["card_name"] is None and face_down["characteristics"]["power"] == 2       # spec 6.5, 6.8
    assert world.observation("p1")["stack"][1]["card_name"] == "Fathom Seer"                  # its controller looks
    assert copied["copy"] and copied["divided"] == [1, 1]
    assert copied["targets"] == [{"player": "p1"}, {"object": world.reference("p0", relic)}]
    world.flags["stack_text"] = False
    assert world.observation("p0")["stack"][0]["text"] is None
    world.move(seer, "battlefield", face_down=True)                                          # it resolves
    assert [item.internal for item in world.stack] == [ability, bolt]
    world.stack.append(StackItem(world.add("Counterspell", owner="p1", zone="hand"), "spell", None, []))
    with pytest.raises(ValueError, match="not on the stack"):
        world.observation("p0")


def test_a_stack_item_may_come_before_or_after_its_object_moves_onto_the_stack() -> None:
    for item_first in (True, False):
        world = World(GAME0, flags=FLAGS_OFF)
        bolt = world.add("Lightning Bolt", owner="p0", zone="hand")
        item = StackItem(bolt, "spell", None, [{"player": "p1"}])
        if item_first:
            world.stack.append(item)
        world.move(bolt, "stack")
        if not item_first:
            world.stack.append(item)
        (entry,) = world.observation("p1")["stack"]
        assert (entry["card_name"], entry["object_id"]) == ("Lightning Bolt", world.object_id("p1", bolt)), item_first
        world.move(bolt, "graveyard")                                                         # leaving drops the item
        assert world.stack == []


def test_a_face_down_source_hides_the_name_of_its_triggers_and_abilities() -> None:
    world = World(GAME0, flags=FLAGS_ON)                                                     # a ward trigger, say
    seer = world.add("Fathom Seer", owner="p1", zone="battlefield", face_down=True)
    world.pending_triggers.append({"source": seer, "source_name": "Fathom Seer", "controller_seat": "p1",
                                   "label": "ward", "optional": False})
    for viewer, name in (("p0", None), ("p1", "Fathom Seer")):                             # the controller may know it
        (trigger,) = world.observation(viewer)["pending_triggers"]
        assert (trigger["source_name"], trigger["source"]["card_name"]) == (name, name), viewer
    world.pending_triggers.clear()
    ward = world.add("Fathom Seer", owner="p1", zone="stack")                               # named after its source
    world.stack.append(StackItem(ward, "triggered_ability", seer, []))
    for viewer, name in (("p0", None), ("p1", "Fathom Seer")):
        (entry,) = world.observation(viewer)["stack"]
        assert (entry["card_name"], entry["source"]["card_name"], world.reference(viewer, ward)["card_name"]) == (
            name, name, name), viewer
    world.objects[seer].face_down = False                                                    # turned face up
    assert world.observation("p0")["stack"][0]["card_name"] == "Fathom Seer"


def test_face_down_objects_show_their_name_to_who_may_look() -> None:
    world = World(GAME0, flags=FLAGS_ON)
    world.add("Brainstorm", owner="p1", zone="exile", face_down=True, face_down_visible_to=("p1",))   # foretold-like
    world.add("Fathom Seer", owner="p0", zone="battlefield", face_down=True)
    (allowed,) = world.observation("p1")["players"][1]["exile"]
    (hidden,) = world.observation("p0")["players"][1]["exile"]
    assert (allowed["card_name"], allowed["characteristics"]["types"]) == ("Brainstorm", ["instant"])
    assert (hidden["card_name"], hidden["characteristics"]) == (None, None)                 # spec 6.8
    (own,) = world.observation("p0")["players"][0]["battlefield"]                            # CR 708.5
    characteristics = own["characteristics"]
    assert (own["card_name"], characteristics["types"], characteristics["colors"], characteristics["power"]) == (
        "Fathom Seer", ["creature"], [], 2)


def test_an_observation_shares_nothing_with_the_world() -> None:
    world = World(GAME0, flags=FLAGS_ON)
    world.add("Pithing Needle", owner="p0", zone="battlefield", counters={"charge": 1},
              chosen=[{"kind": "card_name", "value": "Rancor"}])
    view = world.observation("p0")
    expected = copy.deepcopy(view)
    needle = view["players"][0]["battlefield"][0]["permanent"]
    needle["counters"]["charge"], needle["chosen"][0]["value"] = 9, "Fireball"
    view["players"][0]["progress"]["ring_tempted"], view["players"][0]["mana_pool"]["R"] = 3, 2
    assert world.observation("p0") == expected


def test_a_pending_trigger_from_a_hidden_card_is_omitted() -> None:
    world = World(GAME0, flags=FLAGS_ON)
    temper = world.add("Fiery Temper", owner="p1", zone="hand")
    world.pending_triggers.append({"source": temper, "source_name": "Fiery Temper", "controller_seat": "p1",
                                   "label": None, "optional": True})
    assert world.observation("p0")["pending_triggers"] == []                                  # spec 6.6
    assert world.observation("p1")["pending_triggers"][0]["source"] == world.reference("p1", temper)
    shown = world.look("p0", temper)                                                          # revealed to p0
    assert world.observation("p0")["pending_triggers"][0]["source"]["object_id"] == shown


def test_a_zone_change_makes_a_fresh_object() -> None:
    world = World(GAME0, flags=FLAGS_ON)
    cave = world.add("Spikefield Cave", owner="p0", zone="battlefield", tapped=True, phased_out=True,
                     counters={"charge": 1})
    (record,) = world.observation("p0")["players"][0]["battlefield"]
    assert record["full_name"] == "Spikefield Hazard // Spikefield Cave" and record["permanent"]["tapped"]
    world.move(cave, "hand")
    (card,) = world.observation("p0")["players"][0]["hand"]
    assert (card["card_name"], card["characteristics"]["types"]) == ("Spikefield Hazard", ["instant"])   # front face
    world.move(cave, "battlefield", controller="p1")
    world.objects[cave].name = "Spikefield Cave"                                              # played as its back face
    obj = world.objects[cave]
    assert (obj.tapped, obj.phased_out, obj.counters, obj.summoning_sick) == (False, False, {}, True)
    (record,) = world.observation("p0")["players"][1]["battlefield"]                          # p1 controls it
    assert (record["card_name"], record["owner_seat"], record["controller_seat"]) == ("Spikefield Cave", "p0", "p1")
    journey = world.add("Journey to Nowhere", owner="p0", zone="battlefield")
    seer = world.add("Fathom Seer", owner="p1", zone="exile", face_down=True, face_down_visible_to=("p1",),
                     exiled_by=journey)
    swift = world.add("Monastery Swiftspear", owner="p0", zone="battlefield", attack_target={"player": "p1"})
    world.move(seer, "battlefield")                                                           # returned
    world.move(swift, "battlefield")                                                          # flickered
    returned, flickered = world.objects[seer], world.objects[swift]
    assert (returned.exiled_by, returned.face_down_visible_to, flickered.attack_target) == (None, (), None)
    hazard = world.add("Spikefield Hazard // Spikefield Cave", owner="p0", zone="library")    # a decklist's full name
    assert world.objects[hazard].name == "Spikefield Hazard"


def test_libraries_list_cards_from_the_top() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    top, bottom = world.add("Island", owner="p0", zone="library"), world.add("Mountain", owner="p0", zone="library")
    bolt = world.add("Lightning Bolt", owner="p0", zone="hand")
    world.move(bolt, "library", library_position=1)
    assert world.libraries["p0"] == [top, bolt, bottom]
    world.move(top, "library", library_position=2)                                           # below the other two
    assert world.libraries["p0"] == [bolt, bottom, top] and world.observation("p0")["players"][0]["library_count"] == 3
    with pytest.raises(ValueError, match="library_position"):
        world.move(bolt, "library", library_position=3)
    world.libraries["p0"].remove(bottom)                                                     # out of step with the zone
    with pytest.raises(ValueError, match="libraries"):
        world.observation("p0")


def test_permanent_details_follow_the_flag_and_the_class_subtype() -> None:
    named = [{"kind": "card_name", "value": "Relic of Progenitus"}]
    world = World(GAME0, flags=FLAGS_ON)
    barbarian = world.add("Barbarian Class", owner="p0", zone="battlefield")
    world.add("Pithing Needle", owner="p0", zone="battlefield", chosen=named)

    def details() -> list[tuple]:
        return [(record["permanent"]["class_level"], record["permanent"]["chosen"])
                for record in world.observation("p0")["players"][0]["battlefield"]]

    assert details() == [(1, []), (None, named)]                                             # a Class enters at level 1
    world.objects[barbarian].class_level = 2
    assert details() == [(2, []), (None, named)]
    world.flags["permanent_details"] = False
    assert details() == [(None, None), (None, None)]


def test_known_entries_come_out_in_the_spec_order() -> None:
    def entry(owner, zone, name, top=None, bottom=None, how="looked_at") -> dict:
        return {"owner_seat": owner, "zone": zone, "card_name": name, "object_id": None,
                "position_from_top": top, "position_from_bottom": bottom, "how": how}

    world = World(GAME0, flags={**FLAGS_OFF, "known_cards": True})
    written = [entry("p1", "hand", "Counterspell", how="revealed"), entry("p0", "library", "Island", top=1),
               entry("p0", "library", "Island", bottom=0), entry("p0", "library", "Brainstorm", top=2)]
    world.known["p0"] = list(written)
    assert world.observation("p0")["known"] == [written[3], written[2], written[1], written[0]]   # nulls first (6.7)


def test_looks_are_per_viewer_and_a_zone_change_ends_them() -> None:
    world = World(GAME0, flags=FLAGS_OFF)
    card = world.add("Counterspell", owner="p1", zone="hand")
    assert world.reference("p0", card) is None                                               # hidden and not shown
    shown = world.look("p0", card)
    assert world.reference("p0", card) == {"object_id": shown, "card_name": "Counterspell", "owner_seat": "p1",
                                           "controller_seat": "p1", "zone": "hand"}
    assert world.reference("p1", card)["object_id"] == world.object_id("p1", card) != shown
    world.move(card, "library")                                                              # a new stay
    assert world.reference("p0", card) is None and world.look("p0", card) != shown
    looks = {seat: world.look(seat, card) for seat in ("p0", "p1")}
    world.end_looks("p0")                                                                    # per viewer
    assert world.look("p1", card) == looks["p1"] and world.look("p0", card) != looks["p0"]


@pytest.mark.parametrize(
    "build",
    [
        lambda w: w.add("Black Lotus", owner="p0", zone="hand"),
        lambda w: w.add("Island", owner="p0", zone="hand", controller="p1"),
        lambda w: w.add("Island", owner="p0", zone="graveyard", face_down=True),
        lambda w: w.add("Island", owner="p0", zone="hand", internal=w.add("Island", owner="p0", zone="hand")),
        lambda w: w.object_id("p1", w.add("Island", owner="p0", zone="library")),
        lambda w: w.look("p1", w.add("Island", owner="p0", zone="graveyard")),
        lambda w: w.target("p0", {"object": 3}),
        lambda w: (w.known["p0"].append({"owner_seat": "p1", "zone": "hand", "card_name": "Island", "object_id": "o-1",
                                         "position_from_top": None, "position_from_bottom": None, "how": "revealed"}),
                   w.observation("p0")),
        lambda w: World(GAME0, flags={"known_cards": True}),
        lambda w: _twice_on_the_stack(w),
        lambda w: w.reference("p0", {"$obj": w.add("Island", owner="p0", zone="hand")}),
        lambda w: w.add("Grizzly Bears", owner="p1", zone="battlefield",
                        exiled_by=w.add("Journey to Nowhere", owner="p0", zone="battlefield")),
    ],
    ids=["unknown card", "controller outside the battlefield", "face down in a graveyard", "reused internal id",
         "plain id of a library card", "look at a public card", "target without $obj", "known entry with an id",
         "missing flags", "two stack items for one object", "$obj where an internal id goes",
         "exiled_by outside exile"],
)
def test_the_world_refuses_what_the_spec_cannot_show(build) -> None:
    with pytest.raises(ValueError):
        build(World(GAME0, flags=FLAGS_OFF))


def _twice_on_the_stack(world: World) -> None:
    ability = world.add("Relic of Progenitus", owner="p0", zone="stack")          # one object per activation
    world.stack.extend(StackItem(ability, "activated_ability", None, []) for _ in range(2))
    world.observation("p0")


def test_posed_and_scenario_defaults() -> None:
    first, second = Posed("p0", [{"kind": "pass"}]), Posed("p1", [{"kind": "pass"}])
    assert (first.substep, first.kind, first.source, first.rewind, first.extensions) == ((0, 1), None, None, False, {})
    assert first.extensions is not second.extensions                                        # no shared default (R1-10)
    assert Scenario("empty", [], (), lambda world: iter(())).outcome == ("draw", None, "scenario_complete")


def test_the_fixture_cards_carry_spec_6_characteristics() -> None:
    assert {"Mountain", "Island", "Lightning Bolt", "Counterspell", "Brainstorm", "Preordain", "Grizzly Bears",
            "Monastery Swiftspear", "Spellstutter Sprite", "Chainer's Edict", VAULT, "Barbarian Class",
            "Relic of Progenitus", "Pithing Needle", "Journey to Nowhere", "Rancor", "Fact or Fiction",
            "Force Spike", "Night Market Guard"} <= set(CARDS)
    for name, card in CARDS.items():
        assert unicodedata.is_normalized("NFC", name), name
        assert card["colors"] == [color for color in COLOR_ORDER if color in card["colors"]], name
        assert (card["power"] is None) == (card["toughness"] is None) == ("creature" not in card["types"]), name
        assert card["full_name"] is None or name in card["full_name"].split(" // "), name
    features = set().union(*(card["types"] + card["subtypes"] + card["keywords"] for card in CARDS.values()))
    assert {"planeswalker", "aura", "morph", "kicker", "madness"} <= features
    assert any(card["full_name"] for card in CARDS.values())                                # "A // B"


def test_the_t26b_cards_match_their_oracle_text() -> None:
    """T26b: Force Spike's {1} unless-cost and Night Market Guard's extra block are what the kinds tour plays."""
    spike = CARDS["Force Spike"]                       # "Counter target spell unless its controller pays {1}."
    assert (spike["types"], spike["colors"], spike["mana_value"], spike["keywords"]) == (["instant"], ["blue"], 1, [])
    guard = CARDS["Night Market Guard"]                # "can block an additional creature each combat"
    assert (guard["types"], guard["subtypes"], guard["colors"], guard["mana_value"]) == (
        ["artifact", "creature"], ["construct"], [], 3)
    assert (guard["power"], guard["toughness"], guard["keywords"]) == (3, 1, [])
