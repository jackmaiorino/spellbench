"""Original provided-card inference and an owned deterministic physical-copy stream."""
from __future__ import annotations

import hashlib
import random
import re

from spellbench import wire
import xmage_maintainer_general_targets as general
import xmage_maintainer_targets as targets
from xmage_maintainer_inference import validate_features
from xmage_maintainer_modes import ModeSession
from xmage_maintainer_sources import CALLBACK_SHA256, CARD_SET_VARIANT, MANA_PAYMENT_VARIANT
from xmage_neural_decisions import decision_hash

SOURCE_KEYS = (*targets.SOURCE_KEYS, "card_set_rules_source_sha256")
VARIANT = CARD_SET_VARIANT + "; " + MANA_PAYMENT_VARIANT
KINDS = {"select_object", "finish_selection", "choose_target", "finish_target_selection"}


def bound_view(start: dict, decision: dict) -> dict[int, dict]:
    offered = general.bound_view(start, decision)
    for semantic in offered.values():
        if semantic["kind"] not in KINDS:
            raise ValueError("provided cards exclude unrelated wire actions")
        if semantic["kind"] in ("select_object", "choose_target"):
            card = semantic.get("choice", semantic.get("target"))
            if not isinstance(card, dict) or set(card) != {"object"}:
                raise ValueError("provided-card choices must name visible card objects")
    return offered


def validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    if (not isinstance(sources, dict) or set(sources) != set(SOURCE_KEYS)
            or any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in sources.values())):
        raise ValueError("card frame needs every original source pin")
    offered = bound_view(start, decision)
    if not isinstance(encoded, dict): raise ValueError("provided-card frame is missing")
    expected = {"schema":"spellbench-maintainer-card-set-features/v1", "decision_sha256":decision_hash(decision),
                "game_start_sha256":decision_hash(start), "request_sha256":request_hash,
                "original_callback_sha256":CALLBACK_SHA256, "variant":VARIANT,
                "mana_payment_variant":MANA_PAYMENT_VARIANT, **sources}
    if wire.canonical_json_dumps({key:encoded.get(key) for key in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("card frame differs from its original sources, game, decision or request")
    total, count, groups, ids, deduplicated = (encoded.get(key) for key in
        ("group_count", "candidate_count", "original_groups", "public_group_ids", "deduplicated"))
    selected, minimum, maximum = (encoded.get(key) for key in ("selected_count", "minimum", "maximum"))
    if (type(total) is not int or not 1 <= total <= 4097 or type(count) is not int or count != min(64, total)
            or not isinstance(groups, list) or len(groups) != total or not isinstance(ids, list) or len(ids) != total
            or type(deduplicated) is not bool or any(type(v) is not int for v in (selected, minimum, maximum))
            or not 0 <= minimum <= maximum <= 4096 or not 0 <= selected < maximum):
        raise ValueError("card frame changed its original groups, direct return or range")
    flags = encoded.get("world_flags")
    if not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("unsupported:", "horizon:")) for f in flags):
        raise ValueError("card frame has unsupported world flags")
    by_card = {}
    for cid, semantic in offered.items():
        if semantic["selected_count"] != selected: raise ValueError("card frame changed selected count")
        if semantic["kind"] in ("select_object", "choose_target"):
            if (semantic["minimum"], semantic["maximum"]) != (minimum, maximum):
                raise ValueError("card frame changed the public range")
            card = semantic.get("choice", semantic.get("target"))
        else: card = None
        by_card[wire.canonical_json_dumps(card)] = cid
    _, visible, seats = targets._visible(start, decision)
    seen, names, bound, copies, stop = set(), set(), {}, 0, False
    for index, (group, members) in enumerate(zip(groups, ids)):
        if (not isinstance(group, list) or not isinstance(members, list)
                or len(members) != (len(group) if group else 1) or not members
                or any(type(cid) is not int for cid in members)):
            raise ValueError("card group lost its physical-copy bindings")
        if not group:
            if index != 0 or selected < minimum or members != [by_card.get(b"null")]:
                raise ValueError("card STOP position, minimum or action changed")
            seen.add(b"null"); stop = True
        else:
            if not deduplicated and len(group) != 1: raise ValueError("unmerged original cards acquired a name group")
            name = None
            for card, cid in zip(group, members):
                if not isinstance(card, dict) or set(card) != {"object"}: raise ValueError("original card group contains a player or unknown object")
                targets._reference(card, visible, seats)
                key = wire.canonical_json_dumps(card)
                if key in seen or by_card.get(key) != cid: raise ValueError("card group repeats, omits or aliases an offered copy")
                seen.add(key); copies += 1
                current = card["object"]["card_name"]
                if name is not None and name != current: raise ValueError("original name group mixes different cards")
                name = current
            if deduplicated and name in names: raise ValueError("original name appears in multiple groups")
            names.add(name)
        bound[index] = members[:]
    if (seen != set(by_card) or copies < 1 or copies > 4096 or maximum > selected + copies
            or stop != (selected >= minimum)):
        raise ValueError("card groups changed the complete offered set, capacity or original STOP gate")
    if total == 1:
        if (encoded.get("kind") != "maintainer-card-set-forced" or type(encoded.get("forced_group_index")) is not int
                or encoded["forced_group_index"] != 0):
            raise ValueError("single original card group must bypass inference")
        return None, {0:bound[0]}
    if encoded.get("kind") != "candidates": raise ValueError("nontrivial card groups require paired inference")
    validate_features(encoded)
    if encoded["head"] != "card_select" or encoded["candidate_mask"] != [True]*count+[False]*(64-count):
        raise ValueError("provided cards changed the original head or mask")
    refs = encoded.get("candidate_refs")
    if not isinstance(refs, list) or len(refs) != count: raise ValueError("card frame lost its group slots")
    used = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"index", "candidate_ids", "cards"}:
            raise ValueError("invalid original card group slot")
        index = ref["index"]
        if (type(index) is not int or not 0 <= index < count or index in used
                or wire.canonical_json_dumps(ref["candidate_ids"]) != wire.canonical_json_dumps(bound[index])
                or wire.canonical_json_dumps(ref["cards"]) != wire.canonical_json_dumps(groups[index])):
            raise ValueError("original card slot maps to another physical-copy group")
        used.add(index)
    for i in range(64):
        ident, values = encoded["candidate_ids"][i], encoded["candidate_features"][i]
        if i < count and ident == 0 or i >= count and (ident != 0 or any(values)):
            raise ValueError("card frame changed original active IDs or zero padding")
    return encoded, {i:bound[i] for i in range(count)}


class CardSetSession(ModeSession):
    """Choose an original group, then a copy using a separate game-owned seeded stream."""
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "maintainer-permitted-card-set"
    VARIANT = VARIANT
    bound_view = staticmethod(bound_view)
    validate_encoding = staticmethod(validate_encoding)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            seed = hashlib.sha256(b"spellbench-maintainer-card-copy-mt19937/v1\0" + wire.canonical_json_dumps(self.start)).digest()
            self.copy_rng = random.Random(int.from_bytes(seed, "big"))
            self.copy_draws = 0
        except BaseException:
            self.failed = True; self.close(); raise

    def select_candidate(self, encoded, bound, index):
        members = bound[index]
        if len(members) == 1: return members[0]
        self.copy_draws += 1
        return members[self.copy_rng.randrange(len(members))]
