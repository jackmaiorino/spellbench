"""Original sequential spell targets, owned paired inference and original chooser."""
from __future__ import annotations

import re

from spellbench import observation, wire
from xmage_jack_inference import validate_features
from xmage_jack_modes import ModeSession
from xmage_jack_sources import CALLBACK_SHA256, TARGET_VARIANT, MANA_PAYMENT_VARIANT
from xmage_neural_decisions import decision_hash

SOURCE_KEYS = ("encoder_source_sha256", "candidate_source_sha256", "target_rules_source_sha256",
               "mode_rules_source_sha256", "dialog_rules_source_sha256", "mana_payment_rules_source_sha256",
               "embedding_cache_sha256")
VARIANT = TARGET_VARIANT + "; " + MANA_PAYMENT_VARIANT


def _visible(start, decision):
    seat = start.get("seat")
    obs, context = decision.get("observation", {}), decision.get("context", {})
    source = context.get("source")
    if (seat not in ("p0", "p1") or decision.get("acting_seat") != seat or obs.get("viewer") != seat
            or context.get("kind") != "choice" or not isinstance(source, dict)
            or source.get("controller_seat") != seat or not source.get("card_name")):
        raise ValueError("Jack targets require the acting viewer's named source")
    try:
        refs = {}
        for _, ref in observation.observation_objects(obs):
            alias = ref["object_id"]
            if alias in refs and wire.canonical_json_dumps(refs[alias]) != wire.canonical_json_dumps(ref):
                raise ValueError("target observation aliases different objects")
            refs[alias] = ref
    except (KeyError, TypeError) as exc:
        raise ValueError("target observation is incomplete") from exc
    if source.get("object_id") not in refs or wire.canonical_json_dumps(source) != wire.canonical_json_dumps(refs[source["object_id"]]):
        raise ValueError("target source differs from its visible reference")
    seats = {player.get("seat") for player in obs.get("players", [])}
    return source, refs, seats


def _reference(value, refs, seats):
    if not isinstance(value, dict):
        raise ValueError("target needs a player or named visible object")
    if set(value) == {"player"} and value["player"] in seats and value["player"] in ("p0", "p1"):
        return
    if set(value) == {"object"} and isinstance(value["object"], dict):
        ref = value["object"]
        if (ref.get("card_name") and ref.get("object_id") in refs
                and wire.canonical_json_dumps(ref) == wire.canonical_json_dumps(refs[ref["object_id"]])):
            return
    raise ValueError("target differs from its named permitted reference")


def bound_view(start: dict, decision: dict) -> dict[int, dict]:
    source, refs, seats = _visible(start, decision)
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 4097:
        raise ValueError("target needs its complete offered action list")
    offered, targets, metadata, shared, finish = {}, set(), None, None, False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("invalid target action")
        cid, semantic = candidate.get("candidate_id"), candidate.get("semantic", {})
        if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in offered
                or not isinstance(semantic, dict) or wire.canonical_json_dumps(semantic.get("source")) != wire.canonical_json_dumps(source)):
            raise ValueError("target action is aliased or belongs to another source")
        slot, selected = semantic.get("slot"), semantic.get("selected_count")
        if any(type(v) is not int or not 0 <= v <= 4096 for v in (slot, selected)):
            raise ValueError("target slot and selected count need bounded integers")
        if shared is not None and shared != (slot, selected):
            raise ValueError("target actions disagree on slot or selected count")
        shared = slot, selected
        if semantic.get("kind") == "choose_target":
            minimum, maximum = semantic.get("minimum"), semantic.get("maximum")
            if (type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum <= 4096 or selected > maximum):
                raise ValueError("invalid target range")
            if metadata is not None and metadata != (minimum, maximum):
                raise ValueError("target actions disagree on range")
            metadata = minimum, maximum
            _reference(semantic.get("target"), refs, seats)
            key = wire.canonical_json_dumps(semantic["target"])
            if key in targets: raise ValueError("target action repeats a visible object")
            targets.add(key)
        elif semantic.get("kind") == "finish_target_selection" and not finish:
            finish = True
        else:
            raise ValueError("general spell targets exclude unrelated and repeated finish actions")
        offered[cid] = semantic
    if finish and metadata is not None and shared[1] < metadata[0]:
        raise ValueError("target STOP was offered before the public minimum")
    return offered


def validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    if (not isinstance(sources, dict) or set(sources) != set(SOURCE_KEYS)
            or any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in sources.values())):
        raise ValueError("target frame needs every original source pin")
    offered = bound_view(start, decision)
    expected = {"schema":"spellbench-jack-target-features/v1", "decision_sha256":decision_hash(decision),
                "game_start_sha256":decision_hash(start), "request_sha256":request_hash,
                "original_callback_sha256":CALLBACK_SHA256, "variant":VARIANT,
                "mana_payment_variant":MANA_PAYMENT_VARIANT, **sources}
    if wire.canonical_json_dumps({key:encoded.get(key) for key in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("target frame differs from its original sources, game, decision or replay request")
    count, total, order, names = (encoded.get(key) for key in ("candidate_count", "target_count", "original_targets", "original_names"))
    selected, minimum, maximum = (encoded.get(key) for key in ("selected_count", "minimum", "maximum"))
    if (type(total) is not int or not 1 <= total <= 4097 or type(count) is not int or count != min(64, total)
            or not isinstance(order, list) or len(order) != total or not isinstance(names, list) or len(names) != total
            or any(type(v) is not int for v in (selected, minimum, maximum))
            or not 0 <= minimum <= maximum <= 4096 or not 0 <= selected <= maximum):
        raise ValueError("target frame changed original count, order or range")
    flags = encoded.get("world_flags")
    if not isinstance(flags, list) or any(not isinstance(f, str) or f.startswith(("unsupported:", "horizon:")) for f in flags):
        raise ValueError("target frame has unsupported world flags")
    semantic_by_target = {}
    for cid, semantic in offered.items():
        if semantic["selected_count"] != selected:
            raise ValueError("target frame changed selected count")
        if semantic["kind"] == "choose_target" and (semantic["minimum"], semantic["maximum"]) != (minimum, maximum):
            raise ValueError("target frame changed public range")
        key = wire.canonical_json_dumps(semantic.get("target"))
        semantic_by_target[key] = cid
    _, refs, seats = _visible(start, decision)
    mapped, seen = {}, set()
    first_name, all_same = None, True
    for index, (target, name) in enumerate(zip(order, names)):
        key = wire.canonical_json_dumps(target)
        if key in seen or key not in semantic_by_target:
            raise ValueError("original target order repeats or introduces an unoffered action")
        seen.add(key); mapped[index] = semantic_by_target[key]
        if target is None:
            if index != 0 or name is not None or selected < minimum:
                raise ValueError("original STOP position or minimum changed")
            continue
        _reference(target, refs, seats)
        if "object" in target:
            if name != target["object"]["card_name"]: raise ValueError("original target name differs from its visible object")
        elif name is not None and name != target["player"]:
            raise ValueError("original player target name changed")
        if first_name is None: first_name = name
        elif first_name != name: all_same = False
    if seen != set(semantic_by_target):
        raise ValueError("original target order omitted an offered object or STOP")
    forced_index, reason = None, None
    if total == 1: forced_index, reason = 0, "single_option"
    elif all_same and first_name is not None:
        forced_index, reason = next(i for i, value in enumerate(order) if value is not None), "same_name"
    if forced_index is not None:
        if (encoded.get("kind") != "jack-target-forced" or type(encoded.get("forced_original_index")) is not int
                or encoded["forced_original_index"] != forced_index or encoded.get("reason") != reason
                or type(encoded.get("forced_candidate_id")) is not int or encoded["forced_candidate_id"] != mapped[forced_index]):
            raise ValueError("forced target differs from the original direct return")
        return None, {0:mapped[forced_index]}
    if encoded.get("kind") != "candidates": raise ValueError("nontrivial original target requires paired inference")
    validate_features(encoded)
    if encoded["head"] != "target" or encoded["candidate_mask"] != [True]*count+[False]*(64-count):
        raise ValueError("target head or original mask changed")
    rows = encoded.get("candidate_refs")
    if not isinstance(rows, list) or len(rows) != count: raise ValueError("target frame lost its slot bindings")
    bound = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"index", "candidate_id", "target"}:
            raise ValueError("invalid original target slot binding")
        index, cid = row["index"], row["candidate_id"]
        if (type(index) is not int or not 0 <= index < count or index in bound or type(cid) is not int or cid != mapped[index]
                or wire.canonical_json_dumps(row["target"]) != wire.canonical_json_dumps(order[index])):
            raise ValueError("original target slot maps to another public action")
        bound[index] = cid
    for i in range(64):
        ident, values = encoded["candidate_ids"][i], encoded["candidate_features"][i]
        if i < count and ident == 0 or i >= count and (ident != 0 or any(values)):
            raise ValueError("target frame changed active IDs or zero padding")
    return encoded, bound


class TargetSession(ModeSession):
    """Each original sequential target step consumes at most one model/chooser draw."""
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "jack-permitted-target"
    VARIANT = VARIANT
    bound_view = staticmethod(bound_view)
    validate_encoding = staticmethod(validate_encoding)
