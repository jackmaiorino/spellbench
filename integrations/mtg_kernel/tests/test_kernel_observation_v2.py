"""Neutral identities and public information, independent of native counters."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("kernel_observation_v2", Path(__file__).parents[1] / "kernel_observation_v2.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
KernelProjection = module.KernelProjection


def card(arena=19, zone="Hand", zcc=0, owner="p0", name="Island"):
    stable = {"arena_id": arena, "zone_change_count": zcc, "zone": zone,
              "owner": owner, "controller": owner, "card_db_id": 0}
    return {"stable": stable, "card_name": name, "tapped": False, "summoning_sick": False,
            "damage": 0, "counters": {key: 0 for key in module.COUNTERS}, "is_token": False,
            "characteristics": {"type_flags": {"land": True, "creature": False},
                                "effective_color_mask": 0, "effective_subtype_ids": [1],
                                "effective_power": None, "effective_toughness": None}}


def catalog():
    return {"schema": "spellbench-kernel-public-catalog/v1", "card_db_hash": "000000000000007b",
            "cards": {"Island": {"card_db_id": 0, "face": 0, "x_count": 0, "full_name": "Island",
                "characteristics": {"supertypes": ["basic"], "types": ["land"], "subtypes": ["island"],
                                    "colors": [], "mana_value": 0, "power": None, "toughness": None, "keywords": None}}},
            "subtypes": {"1": "island"}}


def raw():
    return {"acting_player": "p0", "card_db_hash": 123, "step_index": 982,
            "physical_decision_id": 321, "visible_projection_hash": 987654321,
            "own_hand": [card()], "known_library_cards": [[], []], "known_hand_cards": [[], []],
            "projection": {"turn": 1, "phase": "main1", "active_player": "p0", "priority_player": "p0",
                "life_totals": [20, 20], "mana_pools": [[0]*6, [0]*6], "hand_counts": [1, 7], "library_counts": [59, 53],
                "player_status": [{"lands_played_this_turn": 0}, {"lands_played_this_turn": 0}],
                "battlefield": [[], []], "graveyards": [[], []], "exile": [], "stack": [], "object_relations": [],
                "combat": {"ordered_attackers": [], "attacker_to_ordered_blockers": []},
                "engine_context": {"pending_effect": None, "priority_passes": [False, False]}}}


def adapter():
    return KernelProjection(catalog(), b"s"*32)


def project(instance, value, **support):
    return instance.project(value, {"stack_instances": [], **support})


def test_private_counters_and_arena_allocations_do_not_change_first_view():
    first = raw()
    second = deepcopy(first)
    second.update(step_index=1, physical_decision_id=2, visible_projection_hash=3)
    second["own_hand"][0]["stable"]["arena_id"] = 200019
    second["own_hand"][0]["stable"]["zone_change_count"] = 91
    assert project(adapter(), first) == project(adapter(), second)
    wire = json.dumps(project(adapter(), first))
    assert all(key not in wire for key in ("arena_id", "zone_change_count", "physical_decision_id", "visible_projection_hash"))
    assert project(adapter(), first)["players"][1]["hand"] is None


def test_object_ids_are_viewer_scoped_and_change_when_a_card_changes_zone():
    value = raw()
    value["own_hand"] = []
    value["projection"]["hand_counts"] = [0, 0]
    value["projection"]["battlefield"][0] = [card(zone="Battlefield")]
    instance = adapter()
    p0 = project(instance, value)["players"][0]["battlefield"][0]["object_id"]
    value["acting_player"] = "p1"
    p1 = project(instance, value)["players"][0]["battlefield"][0]["object_id"]
    assert p0 != p1
    value["acting_player"] = "p0"
    value["projection"]["battlefield"][0] = []
    value["projection"]["graveyards"][0] = [card(zone="Graveyard", zcc=1)]
    grave = project(instance, value)["players"][0]["graveyard"][0]["object_id"]
    assert grave not in (p0, p1)


def test_a_retired_visible_id_is_never_reissued():
    value = raw()
    instance = adapter()
    first = project(instance, value)["players"][0]["hand"][0]["object_id"]
    missing = deepcopy(value)
    missing["own_hand"] = []
    missing["projection"]["hand_counts"][0] = 0
    project(instance, missing)
    assert project(instance, value)["players"][0]["hand"][0]["object_id"] != first


def stack(source):
    return {"source": source, "controller": "p0", "stack_item_kind": "activated_ability", "face_index": 0,
            "is_copy": False, "targets": [], "mode_chosen": 0, "x_value": 0}


def test_same_source_abilities_keep_their_own_instance_ids():
    value = raw()
    permanent = card(zone="Battlefield")
    value["projection"]["battlefield"][0] = [permanent]
    value["own_hand"] = []
    value["projection"]["hand_counts"][0] = 0
    value["projection"]["stack"] = [stack(permanent["stable"]), stack(permanent["stable"])]
    instance = adapter()
    first = project(instance, value, stack_instances=["11", "12"])["stack"]
    assert first[0]["object_id"] != first[1]["object_id"]
    value["projection"]["stack"] = [stack(permanent["stable"])]
    later = project(instance, value, stack_instances=["11"])["stack"]
    assert later[0]["object_id"] == first[1]["object_id"]
    replacement = project(instance, value, stack_instances=["13"])["stack"]
    assert replacement[0]["object_id"] not in {item["object_id"] for item in first}


def test_departed_ability_source_becomes_null_without_reconnecting_to_new_incarnation():
    value = raw()
    value["projection"]["stack"] = [stack(card(zone="Battlefield")["stable"])]
    value["projection"]["graveyards"][0] = [card(zone="Graveyard", zcc=1)]
    observation = project(adapter(), value, stack_instances=["11"])
    assert observation["stack"][0]["source"] is None


def test_unrevealed_hidden_ability_source_does_not_disclose_registry_name():
    value = raw()
    value["projection"]["stack"] = [stack(card(arena=44, owner="p1")["stable"])]
    observation = project(adapter(), value, stack_instances=["11"])
    assert observation["stack"][0]["card_name"] is None


def test_pending_trigger_has_one_stack_identity_before_and_after_insertion():
    value = raw()
    value["projection"]["graveyards"][0] = [card(zone="Graveyard", zcc=1)]
    item = stack(card(zone="Battlefield")["stable"])
    item["stack_item_kind"] = "triggered_ability"
    instance = adapter()
    announced = project(instance, value, announcing_trigger={"instance": "71", "item": item})["stack"][0]
    assert announced["source"] is None
    assert announced["card_name"] == "Island"
    value["projection"]["stack"] = [item]
    inserted = project(instance, value, stack_instances=["71"])["stack"][0]
    assert inserted == announced
    with pytest.raises(module.ProjectionError, match="duplicates"):
        project(instance, value, stack_instances=["71"], announcing_trigger={"instance": "71", "item": item})


def test_detached_opponent_spell_keeps_the_exact_public_stack_item():
    value = raw()
    stable = card(zone="Stack", owner="p1", zcc=1)["stable"]
    item = stack(stable)
    item.update(stack_item_kind="spell", controller="p1", x_value=0)
    instance = adapter()
    value["projection"]["stack"] = [item]
    original = project(instance, value, stack_instances=["72"])["stack"][0]
    value["projection"]["stack"] = []
    value["projection"]["engine_context"]["pending_optional_cost"] = {"source": stable}
    detached = project(instance, value, detached_resolution={"instance": "72", "item": item}, resolving_stack_instance="72")["stack"][0]
    assert detached == original
    assert instance.effect_ref({"source": stable}, {"resolving_stack_instance": "72"})["object_id"] == original["object_id"]


def test_publicly_revealed_ninjutsu_source_name_survives_without_a_hand_reference():
    value = raw()
    revealed = card(arena=44, owner="p1")
    value["projection"]["stack"] = [stack(revealed["stable"])]
    value["known_hand_cards"][1] = [deepcopy(revealed)]
    observation = project(adapter(), value, stack_instances=["11"])
    assert observation["stack"][0]["card_name"] == "Island"
    assert observation["stack"][0]["source"] is None
    assert observation["players"][1]["hand"] is None
    assert observation["known"] == []
    # A fact about a different incarnation cannot license this name.
    value["known_hand_cards"][1][0]["stable"]["zone_change_count"] += 1
    assert project(adapter(), value, stack_instances=["11"])["stack"][0]["card_name"] is None


def test_chosen_x_and_bestow_form_survive_announcement_and_stack_placement():
    registry = catalog()
    metadata = registry["cards"].pop("Island")
    metadata.update(x_count=1, full_name="Nyxborn Hydra")
    metadata["characteristics"].update(types=["enchantment", "creature"], subtypes=["hydra"],
                                       supertypes=[], colors=["green"], mana_value=1, power=0, toughness=0)
    registry["cards"]["Nyxborn Hydra"] = metadata
    instance = KernelProjection(registry, b"s"*32)
    value = raw()
    value["own_hand"] = []
    value["projection"]["hand_counts"][0] = 0
    stable = card(zone="Stack", zcc=1)["stable"]
    value["projection"]["engine_context"]["pending_cast"] = {
        "source": stable, "chosen_targets": [], "mode_chosen": 1}
    announced = project(instance, value, announcement_x_value=3, announcement_cast_method="bestow")["stack"][0]
    assert announced["x_value"] == 3
    assert announced["characteristics"]["mana_value"] == 4
    assert announced["characteristics"]["types"] == ["enchantment"]
    assert announced["characteristics"]["subtypes"] == ["aura"]
    assert announced["characteristics"]["power"] is None
    item = stack(stable)
    item.update(stack_item_kind="spell", x_value=3, cast_method="bestow", mode_chosen=1)
    value["projection"]["stack"] = [item]
    value["projection"]["engine_context"]["pending_cast"] = None
    placed = project(instance, value, stack_instances=["17"])["stack"][0]
    assert placed["object_id"] == announced["object_id"]
    assert placed["characteristics"] == announced["characteristics"]


def test_historical_opponent_hand_knowledge_is_omitted_with_known_cards_false():
    value = raw()
    value["known_hand_cards"][1] = [card(owner="p1")]
    assert project(adapter(), value)["known"] == []


def test_database_and_stack_metadata_must_match():
    value = raw()
    value["card_db_hash"] += 1
    with pytest.raises(module.ProjectionError, match="different card database"):
        project(adapter(), value)
    with pytest.raises(module.ProjectionError, match="stack instances"):
        project(adapter(), raw(), stack_instances=["not-present"])


def target_choice(value, cards):
    value["projection"]["engine_context"]["pending_effect"] = {"choice": {
        "choice_kind": "targets", "legal_targets": [{"target_kind": "object", "object": card["stable"]} for card in cards],
        "selected_targets": []}}


def test_search_targets_have_fresh_unordered_known_refs_and_no_library_records():
    value = raw()
    target = card(arena=33, zone="Library")
    target_choice(value, [target])
    instance = adapter()
    first = project(instance, value, effect_instance="9:1", choice={"purpose": "search"})
    assert first["known"][0]["how"] == "searching"
    assert first["known"][0]["position_from_top"] is None
    first_id = first["known"][0]["object_id"]
    assert instance.stable_ref(module.normalized_zones(target["stable"]))["object_id"] == first_id
    value["physical_decision_id"] += 1
    assert project(instance, value, effect_instance="9:1", choice={"purpose": "search"})["known"][0]["object_id"] == first_id
    assert project(instance, value, effect_instance="10:1", choice={"purpose": "search"})["known"][0]["object_id"] != first_id


def test_current_revealed_hand_target_gets_ref_but_historical_knowledge_loses_it():
    value = raw()
    target = card(arena=33, owner="p1")
    value["known_hand_cards"][1] = [target]
    target_choice(value, [target])
    instance = adapter()
    revealed = project(instance, value, effect_instance="9:1")
    assert revealed["players"][1]["hand"] is None
    assert revealed["known"][0]["object_id"] is not None
    value["projection"]["engine_context"]["pending_effect"] = None
    assert project(instance, value)["known"] == []


def test_current_look_ids_survive_partition_and_ordering_but_not_new_effect():
    value = raw()
    target = card(arena=33, zone="Library")
    value["known_library_cards"][0] = [{"card": target, "position": 0}]
    target_choice(value, [target])
    instance = adapter()
    first = project(instance, value, effect_instance="9:1")["known"][0]
    assert first["position_from_top"] == 0
    value["physical_decision_id"] += 1
    assert project(instance, value, effect_instance="9:1")["known"][0]["object_id"] == first["object_id"]
    assert project(instance, value, effect_instance="10:1")["known"][0]["object_id"] != first["object_id"]


def test_unpositioned_current_library_cards_are_only_licensed_by_search():
    value = raw()
    target_choice(value, [card(arena=33, zone="Library")])
    with pytest.raises(module.ProjectionError, match="position"):
        project(adapter(), value, effect_instance="9:1", choice={"purpose": "scry"})


def test_dig_exposes_nonmatching_looked_at_cards_with_the_same_effect_ids():
    value = raw()
    first, second = card(arena=33, zone="Library"), card(arena=34, zone="Library")
    value["known_library_cards"][0] = [{"card": first, "position": 0}, {"card": second, "position": 1}]
    target_choice(value, [first])
    instance = adapter()
    support = {"effect_instance": "9:1", "look_owner": "p0", "look_card_count": 2}
    result = project(instance, value, **support)
    assert all(entry["object_id"] is not None and entry["how"] == "looked_at" for entry in result["known"])
    assert instance.stable_ref(module.normalized_zones(second["stable"])) is not None


def test_keywords_are_effective_when_supported_and_null_when_declined():
    value = raw()
    permanent = card(zone="Battlefield")
    flags = {name: False for name in module.KEYWORDS}
    flags.update(flying=True, trample=True, ward_generic=2, landwalk_mask=2)
    permanent["characteristics"]["effective_keywords"] = flags
    value["projection"]["battlefield"][0] = [permanent]
    value["own_hand"] = []
    value["projection"]["hand_counts"][0] = 0
    metadata = catalog()
    metadata["cards"]["Island"]["characteristics"]["keywords"] = ["lifelink"]
    support = {"public_keyword_extras": {module.legacy_id(permanent["stable"]): {"flash": False, "islandwalk": True, "cant_be_blocked": True}}}
    enabled = KernelProjection(metadata, b"s"*32, keywords=True)
    effective = project(enabled, value, **support)["players"][0]["battlefield"][0]["characteristics"]["keywords"]
    assert effective == ["cant_be_blocked", "flying", "islandwalk", "trample", "ward"]
    assert "lifelink" not in effective
    disabled = KernelProjection(metadata, b"s"*32, keywords=False)
    assert project(disabled, value)["players"][0]["battlefield"][0]["characteristics"]["keywords"] is None
    with pytest.raises(module.ProjectionError, match="keyword extras"):
        project(KernelProjection(metadata, b"s"*32, keywords=True), value)
    flags["landwalk_mask"] = 0
    assert "islandwalk" in project(enabled, value, **support)["players"][0]["battlefield"][0]["characteristics"]["keywords"]


def test_public_chosen_colors_and_initiative_follow_host_seat_mapping():
    value = raw()
    permanent = card(zone="Battlefield")
    permanent["chosen_color"] = "U"
    value["projection"]["battlefield"][0] = [permanent]
    value["projection"]["initiative"] = "p0"
    value["projection"]["monarch"] = "p1"
    metadata = catalog()
    metadata["subtypes"]["2"] = "island"
    permanent["characteristics"]["effective_subtype_ids"] = [1, 2]
    result = project(KernelProjection(metadata, b"s" * 32, first_seat="p1"), value)
    assert result["players"][1]["designations"] == ["initiative"]
    assert result["players"][0]["designations"] == ["monarch"]
    visible = result["players"][1]["battlefield"][0]
    assert visible["permanent"]["chosen"] == [{"kind": "color", "value": "blue"}]
    assert visible["characteristics"]["subtypes"] == ["island"]


def test_mana_ability_semantics_bind_the_exact_native_row_index(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    from kernel_semantics_v2 import ordinary_semantic
    value = raw()
    instance = adapter()
    project(instance, value)
    stable = module.normalized_zones(value["own_hand"][0]["stable"])
    semantic = {"kind": "activate_mana_ability", "source": {
        "object_id": module.legacy_id(stable), "card_name": "Island", "zone": "hand",
        "owner_seat": "p0", "controller_seat": "p0"}, "mana_choice": "U", "cost_target": None}
    result = ordinary_semantic(semantic, value, {"mana_ability_indices": {"7": 1}}, instance, {}, candidate_id=7)
    assert result["ability_index"] == 1
    with pytest.raises(ValueError, match="exact native index"):
        ordinary_semantic(semantic, value, {}, instance, {}, candidate_id=7)


def test_spell_copy_target_choice_is_announced_by_its_public_copy_item(monkeypatch):
    # Chain Lightning: after paying {R}{R}, the copier picks the copy's one
    # new target while the copy already sits on the stack.
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    from kernel_semantics_v2 import ordinary_semantic
    value = raw()
    parent = card(arena=60, zone="Stack", zcc=2)["stable"]
    copy = card(arena=122, zone="Stack")["stable"]
    items = [stack(parent), stack(copy)]
    for item in items:
        item["stack_item_kind"] = "spell"
    items[1]["is_copy"] = True
    value["projection"]["stack"] = items
    value["projection"]["engine_context"]["pending_spell_copy"] = {
        "parent": parent, "player": "p0", "stage": "target", "copy": copy,
        "inherited_target": {"target_kind": "player", "player": "p0"}}
    support = {"stack_instances": ["4", "5"]}
    instance = adapter()
    observation = instance.project(value, support)
    copied = next(item for item in observation["stack"] if item["copy"])
    stable = module.normalized_zones(copy)
    semantic = {"kind": "choose_target", "remaining": 1, "target": {"player": "p1"}, "source": {
        "object_id": module.legacy_id(stable), "card_name": "Island", "zone": "stack",
        "owner_seat": "p0", "controller_seat": "p0"}}
    result = ordinary_semantic(semantic, value, support, instance, {})
    assert result["source"]["object_id"] == copied["object_id"]
    assert (result["slot"], result["selected_count"], result["minimum"], result["maximum"]) == (0, 0, 1, 1)
    assert result["target"] == {"player": "p1"}
    semantic["source"]["object_id"] = module.legacy_id(module.normalized_zones(parent))
    with pytest.raises(ValueError, match="another source"):
        ordinary_semantic(semantic, value, support, instance, {})
    value["projection"]["engine_context"]["pending_spell_copy"]["stage"] = "retarget"
    with pytest.raises(ValueError, match="actor-visible announcement"):
        ordinary_semantic(semantic, value, support, instance, {})
