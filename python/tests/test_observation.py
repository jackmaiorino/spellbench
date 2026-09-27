"""The observation schema (spec 6)."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from spellbench.errors import ValidationError
from spellbench.observation import OBSERVATION_FLAGS, observation_objects, observation_references, validate_observation
from spellbench.observation import (CARD_TYPES, CHOSEN_KINDS, COLOR_ORDER, DAY_NIGHT, KNOWN_HOW, KNOWN_ZONES, PHASE_STEPS,
                                    STACK_KINDS, SUPERTYPES, ZONE_ARRAYS, zone_records)

from v2_sample_observation import SAMPLE_OBSERVATION


def _copy() -> dict:
    return copy.deepcopy(SAMPLE_OBSERVATION)


def _ref(record: dict) -> dict:
    return {key: record[key] for key in ("object_id", "card_name", "owner_seat", "controller_seat", "zone")}


def _spell() -> dict:
    bolt = SAMPLE_OBSERVATION["players"][0]["hand"][0]
    return {**_ref(bolt), "object_id": "o-8c1d2e3f4a5b6c7d", "zone": "stack", "stack_kind": "spell", "source": None,
            "face_down": False, "copy": False, "characteristics": copy.deepcopy(bolt["characteristics"]),
            "targets": [{"player": "p1"}], "divided": None, "modes": None, "x_value": None, "text": None}


def _face_down_exile(characteristics: dict | None) -> dict:
    return {"object_id": "o-5e5e5e5e5e5e5e5e", "card_name": None, "owner_seat": "p1", "controller_seat": "p1", "zone": "exile",
            "full_name": None, "face_down": True, "token": False, "copy": False, "characteristics": characteristics,
            "permanent": None, "exiled_by": None}


def test_the_spec_example_validates() -> None:
    assert validate_observation(_copy()) == SAMPLE_OBSERVATION
    assert len(OBSERVATION_FLAGS) == 13


def test_a_spell_on_the_stack_and_a_hidden_face_down_exile_pass() -> None:
    observation = _copy()
    observation["stack"] = [_spell()]
    observation["players"][1]["exile"].append(_face_down_exile(None))
    assert validate_observation(observation)


def _mutations():
    def at(path_fn, value):
        def edit(observation):
            path_fn(observation, value)
            return observation
        return edit
    swift = lambda o: o["players"][0]["battlefield"][0]
    return {
        "unknown field": lambda o: {**o, "x_extra": 1},
        "missing field": lambda o: {k: v for k, v in o.items() if k != "known"},
        "players order": lambda o: {**o, "players": list(reversed(o["players"]))},
        "mana pool key": at(lambda o, v: o["players"][0]["mana_pool"].update(X=v), 0),
        "color order": at(lambda o, v: swift(o)["characteristics"].update(colors=v), ["red", "white"]),
        "permanent on a hand card": at(lambda o, v: o["players"][0]["hand"][0].update(permanent=v), swift(SAMPLE_OBSERVATION)["permanent"]),
        "face-up card without characteristics": at(lambda o, v: o["players"][0]["hand"][0].update(characteristics=v), None),
        "record zone differs from its array": at(lambda o, v: swift(o).update(zone=v), "graveyard"),
        "battlefield controller": at(lambda o, v: swift(o).update(controller_seat=v), "p1"),
        "pregame with a turn": at(lambda o, v: o.update(phase_step=v), "pregame"),
        "power on a noncreature": at(lambda o, v: o["players"][0]["hand"][0]["characteristics"].update(power=v), 3),
        "known how": at(lambda o, v: o["known"][0].update(how=v), "guessed"),
        "counter name": at(lambda o, v: swift(o)["permanent"].update(counters=v), {"+1/+1": 1}),
        "NFD card name": at(lambda o, v: o["players"][0]["hand"][0].update(card_name=v), "Lim-Du\u0302l's Vault"),
        "attack target while not attacking": at(lambda o, v: swift(o)["permanent"].update(attack_target=v), {"player": "p1"}),
        "life above i32": at(lambda o, v: o["players"][1].update(life=v), 1 << 31),
        "known name null": at(lambda o, v: o["known"][1].update(card_name=v), None),                                   # R1-8
        "uncontrolled card with another controller": at(lambda o, v: o["players"][0]["hand"][0].update(controller_seat=v), "p1"),
        "spell with a source": lambda o: {**o, "stack": [{**_spell(), "source": _ref(swift(o))}]},
        "blocked attackers while not blocking": at(
            lambda o, v: o["players"][1]["battlefield"][0]["permanent"].update(blocked_attackers=v), [_ref(swift(SAMPLE_OBSERVATION))]),
        "hidden face-down exile with characteristics": at(lambda o, v: o["players"][1]["exile"].append(v), _face_down_exile(
            {"supertypes": [], "types": ["creature"], "subtypes": [], "colors": [], "mana_value": 0, "power": 2, "toughness": 2,
             "keywords": []})),
        "active seat null outside pregame": at(lambda o, v: o.update(active_seat=v), None),                           # R2-25
    }


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_invalid_observations_are_malformed(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_observation(_mutations()[name](_copy()))


def test_a_library_record_passes_the_schema_for_v5_to_report() -> None:
    observation = _copy()
    observation["players"][0]["hand"][0]["zone"] = "library"
    assert validate_observation(observation)


def test_walkers() -> None:
    observation = _copy()
    assert [path for path, _ in observation_objects(observation)] == [
        "players[0].hand[0]", "players[0].hand[1]", "players[0].battlefield[0]", "players[1].battlefield[0]",
    ]
    assert observation_references(observation) == []
    sprite = observation["players"][1]["battlefield"][0]
    swift = observation["players"][0]["battlefield"][0]
    swift["permanent"].update(attacking=True, attack_target={"player": "p1"})
    sprite["permanent"].update(blocking=True, blocked_attackers=[{k: swift[k] for k in ("object_id", "card_name", "owner_seat", "controller_seat", "zone")}])
    observation["known"].append({"owner_seat": "p1", "zone": "library", "card_name": "Island", "object_id": "o-794a5cb152c9620f",
                                 "position_from_top": 0, "position_from_bottom": None, "how": "looked_at"})
    validate_observation(observation)
    assert [path for path, _ in observation_references(observation)] == ["players[1].battlefield[0].permanent.blocked_attackers[0]"]
    held = dict(observation_objects(observation))
    assert held["known[2]"] == {"object_id": "o-794a5cb152c9620f", "card_name": "Island", "owner_seat": "p1",
                                "controller_seat": "p1", "zone": "library"}
    assert held["players[0].hand[0]"] == {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0",
                                          "controller_seat": "p0", "zone": "hand"}      # the 5-field reference (R1-7)


# Beyond the cases above: the spec's vocabularies, pregame, every link kind the walkers find, and rules no case above exercises.

SPEC = Path(__file__).resolve().parents[2] / "spec" / "SPELLBENCH_PROTOCOL_V2.md"


def _spec_words(prefix: str) -> tuple[str, ...]:
    """The backticked words of the one spec line starting with ``prefix``, comma lists split, in order."""
    (line,) = [line for line in SPEC.read_text(encoding="utf-8").splitlines() if line.startswith(prefix)]
    return tuple(word for span in re.findall(r"`([^`]+)`", line) for word in span.split(", "))


def _spec_table(heading: str) -> tuple[str, ...]:
    """The first backticked word of each table row under a spec heading, in order."""
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading) + 1
    end = next(index for index in range(start, len(lines)) if lines[index].startswith("#"))
    return tuple(match.group(1) for line in lines[start:end] if (match := re.match(r"\| `([a-z_]+)`", line)))


def test_the_vocabularies_are_the_spec_lists() -> None:
    assert _spec_words("- **Supertypes:**") == SUPERTYPES
    assert _spec_words("- **Card types:**") == CARD_TYPES and len(CARD_TYPES) == 15
    assert _spec_words("- **Colors:**") == COLOR_ORDER
    assert _spec_words("- **Chosen kinds:**") == CHOSEN_KINDS
    assert _spec_words("- **How.**") == ("how", *KNOWN_HOW)
    assert _spec_words("- **Zones.**")[:3] == ("zone", *KNOWN_ZONES)
    assert _spec_words("| `stack_kind` | string |") == ("stack_kind", *STACK_KINDS)
    assert _spec_words("| `day_night` | string or null |") == ("day_night", *DAY_NIGHT)
    assert _spec_words("| `phase_step` | string |") == ("phase_step", "pregame", "turn", *PHASE_STEPS[1:])
    assert len(PHASE_STEPS) == 13 and PHASE_STEPS[0] == "pregame"
    assert _spec_table("### 6.3 Player fields")[-5:] == ZONE_ARRAYS


def test_pregame_is_turn_0_and_may_have_no_active_seat() -> None:
    observation = _copy()
    observation.update(turn=0, phase_step="pregame", active_seat=None, priority_seat=None)
    assert validate_observation(observation)
    observation["active_seat"] = "p1"                                        # the starting player is decided
    assert validate_observation(observation)
    observation["phase_step"] = "upkeep"
    with pytest.raises(ValidationError, match="must be pregame exactly when turn is 0"):
        validate_observation(observation)


def _traits(types: list[str], *, supertypes=(), subtypes=(), colors=(), mana_value=0, power=None, toughness=None) -> dict:
    return {"supertypes": list(supertypes), "types": types, "subtypes": list(subtypes), "colors": list(colors),
            "mana_value": mana_value, "power": power, "toughness": toughness, "keywords": []}


def _state(**changes) -> dict:
    return {"tapped": False, "summoning_sick": False, "damage": 0, "counters": {}, "attached_to": None, "attacking": False,
            "attack_target": None, "blocking": False, "blocked_attackers": [], "phased_out": False, "statuses": [],
            "class_level": None, "chosen": [], **changes}


def _card(object_id: str, name: str, owner: str, zone: str, characteristics: dict, *, controller: str | None = None,
          permanent: dict | None = None, exiled_by: dict | None = None) -> dict:
    return {"object_id": object_id, "card_name": name, "owner_seat": owner, "controller_seat": controller or owner,
            "zone": zone, "full_name": None, "face_down": False, "token": False, "copy": False,
            "characteristics": characteristics, "permanent": permanent, "exiled_by": exiled_by}


CHOSEN = [("color", "red"), ("card_name", "Lightning Bolt"), ("creature_type", "time_lord"), ("card_type", "artifact"),
          ("land_type", "island"), ("number", "-3"), ("player", "p1"), ("mode", "Khans"), ("other", "")]


def _board() -> dict:
    """The example with every link kind: an attack on a planeswalker, an Aura, a stolen land, a card exiled by an
    exiling permanent, a spell and a trigger on the stack (one target gone), a pending trigger, and every chosen kind."""
    observation = _copy()
    p0, p1 = observation["players"]
    swift, sprite = p0["battlefield"][0], p1["battlefield"][0]
    karn = _card("o-7000000000000001", "Karn, Scion of Urza", "p1", "battlefield",
                 _traits(["planeswalker"], supertypes=["legendary"], subtypes=["karn"], mana_value=4),
                 permanent=_state(counters={"loyalty": 5}))
    journey = _card("o-7000000000000002", "Journey to Nowhere", "p1", "battlefield",
                    _traits(["enchantment"], colors=["white"], mana_value=2),
                    permanent=_state(chosen=[{"kind": kind, "value": value} for kind, value in CHOSEN]))
    rancor = _card("o-7000000000000003", "Rancor", "p0", "battlefield",
                   _traits(["enchantment"], subtypes=["aura"], colors=["green"], mana_value=1),
                   permanent=_state(attached_to={"object": _ref(swift)}))
    island = _card("o-7000000000000004", "Island", "p1", "battlefield",
                   _traits(["land"], supertypes=["basic"], subtypes=["island"]), controller="p0", permanent=_state())
    bears = _card("o-7000000000000005", "Grizzly Bears", "p0", "exile",
                  _traits(["creature"], subtypes=["bear"], colors=["green"], mana_value=2, power=2, toughness=2),
                  exiled_by=_ref(journey))
    swift["permanent"].update(attacking=True, attack_target={"object": _ref(karn)})
    p0["battlefield"] += [rancor, island]
    p0["exile"].append(bears)
    p1["battlefield"] += [karn, journey]
    bolt = {**_spell(), "targets": [{"object": _ref(karn)}]}
    trigger = {**_ref(sprite), "object_id": "o-7000000000000006", "zone": "stack", "stack_kind": "triggered_ability",
               "source": _ref(sprite), "face_down": False, "copy": False, "characteristics": None,
               "targets": [{"object": _ref(bolt)}, None], "divided": None, "modes": None, "x_value": None, "text": None}
    observation["stack"] = [bolt, trigger]
    observation["pending_triggers"] = [{"source": _ref(swift), "source_name": "Monastery Swiftspear", "controller_seat": "p0",
                                        "label": "prowess", "optional": False}]
    return observation


def test_every_link_kind_is_walked_and_equals_a_held_object() -> None:
    observation = _board()
    assert validate_observation(observation)
    references = observation_references(observation)
    assert [path for path, _ in references] == [
        "players[0].battlefield[0].permanent.attack_target.object",
        "players[0].battlefield[1].permanent.attached_to.object",
        "players[0].exile[0].exiled_by",
        "stack[0].targets[0].object",
        "stack[1].source",
        "stack[1].targets[0].object",
        "pending_triggers[0].source",
    ]
    held = {reference["object_id"]: reference for _, reference in observation_objects(observation)}
    assert all(held[reference["object_id"]] == reference for _, reference in references)    # what V4 compares (R1-7)
    assert [path for path, _ in observation_objects(observation)][-2:] == ["stack[0]", "stack[1]"]
    assert [(path, seat, record["owner_seat"]) for path, seat, record in zone_records(observation)] == [
        ("players[0].hand[0]", "p0", "p0"), ("players[0].hand[1]", "p0", "p0"),
        ("players[0].battlefield[0]", "p0", "p0"), ("players[0].battlefield[1]", "p0", "p0"),
        ("players[0].battlefield[2]", "p0", "p1"),                                           # the stolen Island
        ("players[0].exile[0]", "p0", "p0"),
        ("players[1].battlefield[0]", "p1", "p1"), ("players[1].battlefield[1]", "p1", "p1"),
        ("players[1].battlefield[2]", "p1", "p1"),
    ]


def _morph() -> dict:
    """p1's face-down creature as the viewer p0 sees it: nameless, with face-down characteristics (spec 6.4, 6.8)."""
    return {**_card("o-fd00000000000001", None, "p1", "battlefield", _traits(["creature"], power=2, toughness=2),
                    permanent=_state()), "face_down": True}


def _morph_ability(name: str | None) -> dict:
    """A triggered ability of the morph on the stack, named after its source (spec 5.1)."""
    return {**_ref(_morph()), "object_id": "o-ab00000000000001", "card_name": name, "zone": "stack",
            "stack_kind": "triggered_ability", "source": _ref(_morph()), "face_down": False, "copy": False,
            "characteristics": None, "targets": [], "divided": None, "modes": None, "x_value": None, "text": None}


def _morph_trigger(name: str | None) -> dict:
    """A pending trigger of the morph (spec 6.6)."""
    return {"source": _ref(_morph()), "source_name": name, "controller_seat": "p1", "label": None, "optional": False}


def test_a_hidden_identity_stays_hidden_in_every_name_field() -> None:
    # A nameless face-down card, an ability and a pending trigger sourced from it, all nameless (spec 5.1, 6.8).
    observation = _copy()
    observation["players"][1]["battlefield"].append(_morph())
    observation["players"][1]["exile"].append(_face_down_exile(None))
    observation.update(stack=[_morph_ability(None)], pending_triggers=[_morph_trigger(None)])
    assert validate_observation(observation)
    assert [path for path, _ in observation_references(observation)] == ["stack[0].source", "pending_triggers[0].source"]


def _more_mutations() -> dict:
    """Rules the cases above leave unexercised, each with the path its error names."""
    def edit(change):
        def apply(observation):
            change(observation)
            return observation
        return apply
    swift = lambda o: o["players"][0]["battlefield"][0]
    on_stack = lambda **fields: lambda o: {**o, "stack": [{**_spell(), **fields}]}
    chosen = lambda kind, value: edit(lambda o: swift(o)["permanent"].update(chosen=[{"kind": kind, "value": value}]))
    return {
        "a third player": (lambda o: {**o, "players": [*o["players"], copy.deepcopy(o["players"][1])]}, "players"),
        "seats labelled p1 then p0": (edit(lambda o: (o["players"][0].update(seat="p1"), o["players"][1].update(seat="p0"))),
                                      "players[0].seat"),
        "a null battlefield": (edit(lambda o: o["players"][0].update(battlefield=None)), "players[0].battlefield"),
        "a graveyard card owned by the other seat": (edit(lambda o: o["players"][0]["graveyard"].append(
            {**copy.deepcopy(o["players"][0]["hand"][0]), "owner_seat": "p1", "controller_seat": "p1", "zone": "graveyard"})),
            "players[0].graveyard[0].owner_seat"),
        "a battlefield card without permanent state": (edit(lambda o: swift(o).update(permanent=None)),
                                                       "players[0].battlefield[0].permanent"),
        "a named face-down exile without characteristics": (edit(lambda o: o["players"][1]["exile"].append(
            {**_face_down_exile(None), "card_name": "Grizzly Bears"})), "players[1].exile[0].characteristics"),   # spec 6.4
        "a stack entry outside the stack zone": (on_stack(zone="hand"), "stack[0].zone"),
        "a spell without characteristics": (on_stack(characteristics=None), "stack[0].characteristics"),
        "an ability with characteristics": (on_stack(stack_kind="activated_ability"), "stack[0].characteristics"),
        "an unknown card type": (edit(lambda o: o["players"][0]["hand"][1]["characteristics"].update(types=["tribal"])),
                                 "players[0].hand[1].characteristics.types[0]"),
        "an unknown supertype": (edit(lambda o: o["players"][0]["hand"][1]["characteristics"].update(supertypes=["Basic"])),
                                 "players[0].hand[1].characteristics.supertypes[0]"),
        "an exiled_by that is not an object reference": (edit(lambda o: o["players"][0]["hand"][0].update(exiled_by={"player": "p1"})),
                                                         "players[0].hand[0].exiled_by"),
        "a stack target that is not a target reference": (on_stack(targets=[{"player": "p2"}]), "stack[0].targets[0].player"),
        "a keyword not in snake case": (edit(lambda o: swift(o)["characteristics"].update(keywords=["first strike"])),
                                        "players[0].battlefield[0].characteristics.keywords[0]"),
        "a pending trigger without optional": (lambda o: {**o, "pending_triggers": [
            {"source": None, "source_name": None, "controller_seat": "p0", "label": None}]}, "pending_triggers[0]"),
        "a known card in a graveyard": (edit(lambda o: o["known"][0].update(zone="graveyard")), "known[0].zone"),
        "a known entry with an empty id": (edit(lambda o: o["known"][0].update(object_id="")), "known[0].object_id"),
        "a chosen color outside the colors": (chosen("color", "purple"), "players[0].battlefield[0].permanent.chosen[0].value"),
        "a chosen number not in decimal": (chosen("number", "07"), "players[0].battlefield[0].permanent.chosen[0].value"),
        "a chosen number beyond i32": (chosen("number", "2147483648"), "players[0].battlefield[0].permanent.chosen[0].value"),
        "a chosen number of 5000 digits": (chosen("number", "9" * 5000), "players[0].battlefield[0].permanent.chosen[0].value"),
        "day_night outside its vocabulary": (edit(lambda o: o.update(day_night="dusk")), "day_night"),
        "a priority seat in pregame": (edit(lambda o: o.update(turn=0, phase_step="pregame", active_seat=None,
                                                               priority_seat="p0")), "priority_seat"),     # spec 6.2
        # A face-down identity hidden by its reference is hidden in every other name field too (spec 5.1, 6.8).
        "a nameless face-down exile with a full name": (edit(lambda o: o["players"][1]["exile"].append(
            {**_face_down_exile(None), "full_name": "Delver of Secrets // Insectile Aberration"})),
            "players[1].exile[0].full_name"),
        "an ability named after its hidden source": (edit(lambda o: (
            o["players"][1]["battlefield"].append(_morph()), o.update(stack=[_morph_ability("Hooded Hydra")]))),
            "stack[0].card_name"),
        "a pending trigger naming its hidden source": (edit(lambda o: (
            o["players"][1]["battlefield"].append(_morph()), o.update(pending_triggers=[_morph_trigger("Hooded Hydra")]))),
            "pending_triggers[0].source_name"),
    }


@pytest.mark.parametrize("name", sorted(_more_mutations()))
def test_more_invalid_observations_name_the_offending_path(name: str) -> None:
    mutate, path = _more_mutations()[name]
    with pytest.raises(ValidationError, match="^" + re.escape(f"seat_decision.observation.{path}: ")):
        validate_observation(mutate(_copy()), "seat_decision.observation")
