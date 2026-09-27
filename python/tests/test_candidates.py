"""Candidate semantics: the 30 v2.0 kinds, their vocabularies and constraints (spec 7)."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from spellbench import candidates
from spellbench.candidates import (
    CHOICE_KINDS, PRIORITY_KINDS, RESERVED_KINDS, V2_KINDS, family, object_references, validate_candidate, validate_semantic,
)
from spellbench.errors import ValidationError

from v2_sample_semantics import R_MOUNTAIN, R_SPRITE, R_STACK, R_SWIFTSPEAR, SAMPLES


def test_the_samples_cover_exactly_the_v2_kinds() -> None:
    assert set(SAMPLES) == V2_KINDS and len(V2_KINDS) == 30
    assert len(PRIORITY_KINDS) == 6 and len(CHOICE_KINDS) == 24


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_every_sample_validates_unchanged(kind: str) -> None:
    semantic = copy.deepcopy(SAMPLES[kind])
    assert validate_semantic(semantic) == SAMPLES[kind]
    assert family(kind) == ("priority" if kind in PRIORITY_KINDS else "choice")


@pytest.mark.parametrize("kind", sorted(RESERVED_KINDS))
def test_reserved_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        validate_semantic({"kind": kind})


def _edit(kind: str, **changes) -> dict:
    return {**copy.deepcopy(SAMPLES[kind]), **changes}


@pytest.mark.parametrize(
    "semantic",
    [
        {"kind": "choose_cast_mode"},                                     # a v1 kind
        _edit("play_land", extra=1),                                      # unknown field
        {k: v for k, v in SAMPLES["play_land"].items() if k != "face"},   # missing field
        _edit("choose_target", selected_count=1, maximum=1),              # selected_count < maximum
        _edit("choose_target", minimum=2, maximum=1),
        _edit("choose_spell_mode", maximum=4),                            # maximum <= mode_count
        _edit("choose_spell_mode", mode_index=3),
        _edit("choose_option", option_index=2),
        _edit("choose_number", value=5),
        _edit("order_pick", position=2),
        _edit("arrange_card", card_index=2),
        _edit("choose_replacement", replacement_count=1, replacement_index=0),
        _edit("distribute", amount=4),
        _edit("choose_pile", pile_index=2),
        _edit("choose_pile", piles=[[], [], []]),
        _edit("choose_color", color="purple"),
        _edit("cast_spell", method="sideways"),
        _edit("choose_cost_option", choice="Sacrifice Land"),
        _edit("select_object", purpose="discard_all"),
        _edit("mulligan", keep=1),
        _edit("choose_number", value=True),
        _edit("declare_attack", defender={"player": "p0", "object": R_SPRITE}),
        _edit("order_pick", item={"object": R_SPRITE, "trigger": {}}),
    ],
)
def test_invalid_semantics_are_malformed(semantic: dict) -> None:
    with pytest.raises(ValidationError):
        validate_semantic(semantic)


def test_nullable_fields() -> None:
    assert validate_semantic(_edit("cast_spell", method=None))["method"] is None
    assert validate_semantic(_edit("declare_attack", defender=None))["defender"] is None
    with pytest.raises(ValidationError):
        validate_semantic(_edit("choose_target", source=None))   # R, not R|null


def test_candidates_are_exactly_three_fields() -> None:
    candidate = {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}
    assert validate_candidate(candidate) == candidate
    with pytest.raises(ValidationError):
        validate_candidate({**candidate, "x_extra": 1})


def test_object_references_walk_every_reference() -> None:
    paths = [path for path, _ in object_references(SAMPLES["order_pick"])]
    assert paths == ["item.trigger.event_objects[0]", "item.trigger.source"]
    assert [ref for _, ref in object_references(SAMPLES["declare_block"])] == [R_SPRITE]
    assert len(object_references(SAMPLES["choose_pile"])) == 3
    assert object_references(SAMPLES["declare_attack"]) == [("attacker", R_SWIFTSPEAR)]


# Cross-checks against the frozen spec text and a model walk, so no hand-copied table goes unverified.

SPEC = Path(__file__).resolve().parents[2] / "spec" / "SPELLBENCH_PROTOCOL_V2.md"


def _spec_lines(heading: str) -> list[str]:
    """The lines under a heading of the frozen spec, up to the next heading."""
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading) + 1
    end = next(index for index in range(start, len(lines)) if lines[index].startswith("#"))
    return lines[start:end]


def _table(heading: str) -> list[list[str]]:
    """The body rows of the table under a heading, split into cells on unescaped pipes."""
    return [[cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
            for line in _spec_lines(heading) if line.startswith("| `")]


def _valid(semantic: dict) -> bool:
    try:
        validate_semantic(semantic)
    except ValidationError:
        return False
    return True


def test_fields_and_reference_nullability_follow_the_spec_tables() -> None:
    rows = _table("### 7.2 Priority kinds") + _table("### 7.3 Choice kinds")
    assert [row[0].strip("`") for row in rows] == [*PRIORITY_KINDS, *CHOICE_KINDS]
    for kind_cell, fields, _meaning in rows:
        kind = kind_cell.strip("`")
        assert sorted(SAMPLES[kind]) == sorted(["kind", *re.findall(r"`([a-z_]+)`", fields)]), kind
        for name, null in re.findall(r"`([a-z_]+)` [RT](\\\|null)?(?![a-z])", fields):   # R, R|null, T, T|null
            assert _valid({**SAMPLES[kind], name: None}) == bool(null), f"{kind}.{name}"
    for kind in PRIORITY_KINDS[1:]:   # spec 7.2: every source is an object reference
        assert not _valid({**SAMPLES[kind], "source": None}), kind


def _vocabulary_rows() -> list[tuple[list[tuple[str, str]], tuple[str, ...]]]:
    """Each spec 7.4 row as its (kind, field) pairs and values, then the spec 6.10 colors and mana symbols."""
    rows = []
    for label, values in _table("### 7.4 Vocabularies"):
        names = re.findall(r"`([a-z_.]+)`", label)   # `kind.field`, ... or `field` (`kind`, ...)
        pairs = [tuple(name.split(".")) for name in names] if "." in names[0] else [(kind, names[0]) for kind in names[1:]]
        rows.append((pairs, tuple(values.strip("`").split(", "))))
    for line in _spec_lines("### 6.10 Vocabularies"):
        last_code = re.findall(r"`([^`]+)`", line)[-1:]
        if line.startswith("- **Colors:**"):
            rows.append(([("choose_color", "color")], tuple(last_code[0].split(", "))))
        if line.startswith("- **Mana symbols**"):
            rows.append(([("activate_mana_ability", "mana_choice")], tuple(last_code[0].split(", "))))
    return rows


NULLABLE_VOCABULARY_FIELDS = {("cast_spell", "method"), ("activate_mana_ability", "mana_choice")}   # spec 7.2: "or null"


def test_vocabularies_are_the_spec_tables_and_bind_their_fields() -> None:
    rows = _vocabulary_rows()
    assert [values for _, values in rows] == [
        candidates.SELECT_PURPOSES, candidates.BOOLEAN_PURPOSES, candidates.NUMBER_PURPOSES, candidates.OPTION_PURPOSES,
        candidates.COLOR_PURPOSES, candidates.NAME_PURPOSES, candidates.ORDER_PURPOSES, candidates.ARRANGE_PURPOSES,
        candidates.ARRANGE_DESTINATIONS, candidates.DISTRIBUTE_PURPOSES, candidates.PILE_PURPOSES, candidates.CAST_METHODS,
        candidates.OPTIONAL_COSTS, candidates.COST_KINDS, candidates.SPECIAL_ACTIONS, candidates.REPLACEMENT_EVENTS,
        candidates.COLORS, candidates.MANA_SYMBOLS,
    ]
    every_value = sorted({value for _, values in rows for value in values} | {"Red", "discard_all"})
    for pairs, values in rows:
        for kind, field in pairs:
            accepted = [value for value in every_value if _valid({**SAMPLES[kind], field: value})]
            assert accepted == sorted(values), f"{kind}.{field}"
            assert _valid({**SAMPLES[kind], field: None}) == ((kind, field) in NULLABLE_VOCABULARY_FIELDS), f"{kind}.{field}"


def _walk(value, path: str = "") -> list[tuple[str, dict]]:
    """A model walk: every dict with exactly the five reference fields, depth first in sorted key order."""
    if isinstance(value, dict):
        if set(value) == {"object_id", "card_name", "owner_seat", "controller_seat", "zone"}:
            return [(path, value)]
        return [found for key in sorted(value) for found in _walk(value[key], f"{path}.{key}" if path else key)]
    if isinstance(value, list):
        return [found for index, item in enumerate(value) for found in _walk(item, f"{path}[{index}]")]
    return []


FILLED = [   # the samples' null references filled in, and the other order item
    {**SAMPLES["activate_mana_ability"], "cost_target": {"object": R_SPRITE}},
    {**SAMPLES["choose_option"], "source": R_STACK},
    {**SAMPLES["choose_boolean"], "source": R_STACK},
    {**SAMPLES["order_pick"], "source": R_STACK, "item": {"object": R_MOUNTAIN}},
    {**SAMPLES["choose_replacement"], "affected": {"object": R_SPRITE}, "replacement_source": R_SWIFTSPEAR},
    {**SAMPLES["declare_attack"], "defender": {"object": R_SPRITE}},
    {**SAMPLES["declare_block"], "attacker": R_SWIFTSPEAR},
    {**SAMPLES["choose_pile"], "source": R_STACK},
]


@pytest.mark.parametrize("semantic", [*SAMPLES.values(), *FILLED], ids=lambda semantic: semantic["kind"])
def test_object_references_match_a_model_walk(semantic: dict) -> None:
    assert validate_semantic(semantic) is semantic
    assert object_references(semantic) == _walk(semantic)


_TRIGGER = SAMPLES["order_pick"]["item"]["trigger"]


@pytest.mark.parametrize(
    "semantic",
    [
        _edit("order_pick", item={"trigger": {k: v for k, v in _TRIGGER.items() if k != "label"}}),
        _edit("order_pick", item={"trigger": {**_TRIGGER, "source_name": "Lim-Du" + chr(0x302) + "l's Vault"}}),   # NFD
        _edit("order_pick", item={"trigger": {**_TRIGGER, "event_objects": [None]}}),
        _edit("order_pick", item={"trigger": {**_TRIGGER, "ability_index": -1}}),
        _edit("order_pick", item={"trigger": {**_TRIGGER, "instance": None}}),
        _edit("order_pick", item={"object": None}),
        _edit("order_pick", item={"card": R_SPRITE}),
        _edit("choose_pile", piles=[[R_MOUNTAIN]]),
        _edit("choose_pile", piles=[[R_MOUNTAIN], [None]]),
        _edit("choose_number", value=1 << 31, maximum=1 << 31),
        _edit("choose_option", option_label=3),
        _edit("choose_name", value=""),
        _edit("choose_starting_player", player="p2"),
    ],
)
def test_nested_shapes_are_checked(semantic: dict) -> None:
    with pytest.raises(ValidationError):
        validate_semantic(semantic)


def test_null_trigger_fields_empty_piles_and_negative_numbers_pass() -> None:
    bare = {**_TRIGGER, "source": None, "source_name": None, "ability_index": None, "event_objects": [], "label": "Upkeep"}
    assert object_references(validate_semantic(_edit("order_pick", item={"trigger": bare}))) == []
    validate_semantic(_edit("choose_pile", piles=[[], [R_MOUNTAIN, R_SWIFTSPEAR]]))
    validate_semantic(_edit("choose_number", minimum=-(1 << 31), value=-1))


@pytest.mark.parametrize(
    "edit", [{"candidate_id": -1}, {"candidate_id": True}, {"candidate_id": 1 << 32}, {"display_text": 7},
             {"semantic": {"kind": "pay_mana"}}, {"semantic": {}}, {"semantic": None}, {"semantic": {"kind": ["pass"]}}],
)
def test_candidate_fields_are_typed(edit: dict) -> None:
    with pytest.raises(ValidationError):
        validate_candidate({"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None, **edit})


def test_errors_name_the_path_and_family_refuses_other_kinds() -> None:
    semantic = {**SAMPLES["choose_target"], "target": {"object": {**R_SPRITE, "zone": "deck"}}}
    with pytest.raises(ValidationError, match=r"^candidates\[2\]\.semantic\.target\.object\.zone: "):
        validate_candidate({"candidate_id": 2, "semantic": semantic, "display_text": None}, "candidates[2]")
    for kind in [*sorted(RESERVED_KINDS), "choose_cast_mode", None]:
        with pytest.raises(ValidationError):
            family(kind)
