"""Alternative printed spell forms across the public announcement/stack boundary."""
from copy import deepcopy

import pytest

from test_kernel_observation_v2 import KernelProjection, card, catalog, module, project, raw, stack


def registry():
    value = catalog()
    printed = value["cards"].pop("Island")
    printed.update(full_name="Sagu Wildling", x_count=0)
    printed["characteristics"].update(supertypes=[], types=["creature"], subtypes=["dragon"],
                                      colors=["green"], mana_value=5, power=3, toughness=3, keywords=["flying"])
    printed["spell_forms"] = {"omen": {"x_count": 0, "characteristics": {
        "supertypes": [], "types": ["sorcery"], "subtypes": [], "colors": ["green"],
        "mana_value": 1, "power": None, "toughness": None, "keywords": []}}}
    value["cards"]["Sagu Wildling"] = printed
    return value


def announcing():
    value = raw()
    value["own_hand"] = []
    value["projection"]["hand_counts"][0] = 0
    source = card(zone="Stack", zcc=1)["stable"]
    value["projection"]["engine_context"]["pending_cast"] = {
        "source": source, "chosen_targets": [], "mode_chosen": 1}
    return value, source


@pytest.mark.parametrize("keywords", [False, True])
@pytest.mark.parametrize("name", ["Sagu Wildling", "Fang Dragon"])
def test_omen_form_survives_announcement_placement_and_opponent_view(keywords, name):
    compiled = registry()
    metadata = compiled["cards"].pop("Sagu Wildling")
    if name == "Fang Dragon":
        metadata.update(full_name=name)
        metadata["characteristics"].update(colors=["red"], mana_value=7, power=6)
        metadata["spell_forms"]["omen"]["characteristics"].update(colors=["red"], mana_value=2)
    compiled["cards"][name] = metadata
    before = deepcopy(compiled)
    instance = KernelProjection(compiled, b"s" * 32, keywords=keywords)
    value, source = announcing()
    announced = project(instance, value, announcement_x_value=0, announcement_cast_method="omen")["stack"][0]
    expected = deepcopy(compiled["cards"][name]["spell_forms"]["omen"]["characteristics"])
    if not keywords:
        expected["keywords"] = None
    assert announced["characteristics"] == expected
    item = stack(source)
    item.update(stack_item_kind="spell", cast_method="omen", mode_chosen=0)
    value["projection"]["stack"] = [item]
    value["projection"]["engine_context"]["pending_cast"] = None
    placed = project(instance, value, stack_instances=["17"])["stack"][0]
    assert placed["object_id"] == announced["object_id"]
    assert placed["characteristics"] == expected
    value["acting_player"] = "p1"
    opponent = project(instance, value, stack_instances=["17"])["stack"][0]
    assert opponent["card_name"] == name
    assert opponent["characteristics"] == expected
    assert compiled == before


def test_alternative_form_uses_its_own_colors_and_x_count_not_the_creature():
    compiled = registry()
    metadata = compiled["cards"]["Sagu Wildling"]
    metadata["x_count"] = 3
    form = metadata["spell_forms"]["omen"]
    form["x_count"] = 2
    form["characteristics"].update(colors=["red", "blue"], mana_value=2)
    instance = KernelProjection(compiled, b"s" * 32, keywords=True)
    result = instance.spell_characteristics(metadata, 4, "omen")
    assert result["mana_value"] == 10
    assert result["colors"] == ["blue", "red"]
    assert instance.spell_characteristics(metadata, 4, "normal")["mana_value"] == 17
    bestowed = instance.spell_characteristics(metadata, 4, "bestow")
    assert bestowed["mana_value"] == 17
    assert bestowed["types"] == ["enchantment"] and bestowed["subtypes"] == ["aura"]


@pytest.mark.parametrize("alter", [
    lambda metadata: metadata.pop("spell_forms"),
    lambda metadata: metadata.update(spell_forms=[]),
    lambda metadata: metadata["spell_forms"].update(omen=None),
    lambda metadata: metadata["spell_forms"]["omen"].update(x_count=True),
    lambda metadata: metadata["spell_forms"]["omen"].update(x_count=-1),
    lambda metadata: metadata["spell_forms"]["omen"].update(characteristics=None),
    lambda metadata: metadata["spell_forms"]["omen"]["characteristics"].pop("keywords"),
    lambda metadata: metadata["spell_forms"]["omen"]["characteristics"].update(colors=["secret"]),
    lambda metadata: metadata["spell_forms"]["omen"]["characteristics"].update(types=["secret"]),
    lambda metadata: metadata["spell_forms"]["omen"]["characteristics"].update(mana_value=True),
    lambda metadata: metadata["spell_forms"]["omen"]["characteristics"].update(power="secret"),
])
def test_incomplete_or_malformed_omen_catalog_metadata_fails_closed(alter):
    compiled = registry()
    alter(compiled["cards"]["Sagu Wildling"])
    value, _ = announcing()
    with pytest.raises(module.ProjectionError, match="Omen spell"):
        project(KernelProjection(compiled, b"s" * 32), value,
                announcement_x_value=0, announcement_cast_method="omen")
