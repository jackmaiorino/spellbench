"""Bind the original inherited card policy without a model or selection draw."""
from __future__ import annotations

import re

from spellbench import wire
from xmage_jack_card_sets import SOURCE_KEYS as CARD_SOURCE_KEYS, bound_view
from xmage_jack_modes import ModeSession
from xmage_jack_sources import CALLBACK_SHA256, MANA_PAYMENT_VARIANT, PARENT_CARD_VARIANT
from xmage_neural_decisions import decision_hash

PARENT_KEYS = ("parent_card_rules_source_sha256", "parent_selector_source_sha256", "parent_comparator_source_sha256",
               "parent_permanent_source_sha256", "parent_scoring_source_sha256", "parent_magic_ability_source_sha256")
SOURCE_KEYS = (*CARD_SOURCE_KEYS, *PARENT_KEYS)
VARIANT = PARENT_CARD_VARIANT + "; " + MANA_PAYMENT_VARIANT
FRAME_KEYS = {"schema", "kind", "decision_sha256", "game_start_sha256", "request_sha256", "original_callback_sha256",
              "variant", "mana_payment_variant", "world_flags", "original_targets", "public_target_ids", "chosen_index",
              "chosen_candidate_id", "rule", "selected_count", "minimum", "maximum", *SOURCE_KEYS}


def validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    if (not isinstance(sources, dict) or set(sources) != set(SOURCE_KEYS)
            or any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in sources.values())):
        raise ValueError("parent card frame needs every original source pin")
    offered = bound_view(start, decision)
    if not isinstance(encoded, dict) or set(encoded) != FRAME_KEYS:
        raise ValueError("parent card frame fields differ from the original policy binding")
    expected = {"schema":"spellbench-jack-parent-card-features/v1", "kind":"jack-parent-card-choice",
                "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start), "request_sha256":request_hash,
                "original_callback_sha256":CALLBACK_SHA256, "variant":VARIANT, "mana_payment_variant":MANA_PAYMENT_VARIANT, **sources}
    if wire.canonical_json_dumps({k:encoded.get(k) for k in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("parent card frame differs from its sources, game, decision or request")
    selected, minimum, maximum = (encoded[k] for k in ("selected_count", "minimum", "maximum"))
    if (any(type(v) is not int for v in (selected, minimum, maximum))
            or not 0 <= minimum <= maximum <= 4096 or not 0 <= selected < maximum):
        raise ValueError("parent card frame changed the original range")
    flags, order, ids = (encoded[k] for k in ("world_flags", "original_targets", "public_target_ids"))
    if (not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("unsupported:", "horizon:")) for f in flags)
            or not isinstance(order, list) or not 1 <= len(order) <= 4097 or not isinstance(ids, list) or len(ids) != len(order)):
        raise ValueError("parent card frame changed its world or original target list")
    by_target = {}
    for cid, semantic in offered.items():
        if semantic["selected_count"] != selected: raise ValueError("parent card frame changed selected count")
        if semantic["kind"] in ("select_object", "choose_target"):
            if (semantic["minimum"], semantic["maximum"]) != (minimum, maximum):
                raise ValueError("parent card frame changed the public range")
            card = semantic.get("choice", semantic.get("target"))
        else: card = None
        by_target[wire.canonical_json_dumps(card)] = cid
    seen = set()
    for index, (card, cid) in enumerate(zip(order, ids)):
        key = wire.canonical_json_dumps(card)
        if type(cid) is not int or key in seen or by_target.get(key) != cid:
            raise ValueError("parent card order repeats or aliases an offered action")
        seen.add(key)
        if card is None and (index != 0 or selected < minimum):
            raise ValueError("parent card STOP precedes its original minimum")
    if seen != set(by_target) or (b"null" in seen) != (selected >= minimum):
        raise ValueError("parent card frame changed the complete offered set or STOP gate")
    index, cid, rule = (encoded[k] for k in ("chosen_index", "chosen_candidate_id", "rule"))
    if (type(index) is not int or not 0 <= index < len(order) or type(cid) is not int or cid != ids[index]
            or rule not in ("good_target", "bad_target", "implicit_finish")
            or (order[index] is None) != (rule == "implicit_finish")):
        raise ValueError("parent card choice differs from its original selected object or completion")
    return None, {0:cid}


class ParentCardSession(ModeSession):
    """Own the existing lifecycle and clock while accepting only the determined parent pick."""
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "jack-permitted-parent-card"
    VARIANT = VARIANT
    bound_view = staticmethod(bound_view)
    validate_encoding = staticmethod(validate_encoding)
