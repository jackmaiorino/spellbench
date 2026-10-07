"""Original general-target policy for spell, cost and visible object callbacks."""
from __future__ import annotations

import copy

from spellbench import wire
import xmage_maintainer_targets as original
from xmage_neural_decisions import decision_hash

SOURCE_KEYS = original.SOURCE_KEYS
VARIANT = original.VARIANT.replace(
    "acting-player named-source spell targets only; cost, provided-card and divided-target callbacks unqualified",
    "acting-player named-source spell, cost and general object selections; provided-card, divided-target and opponent callbacks unqualified")
FIELDS = {
    "choose_target": {"kind", "source", "slot", "target", "selected_count", "minimum", "maximum"},
    "finish_target_selection": {"kind", "source", "slot", "selected_count"},
    "choose_cost_target": {"kind", "source", "cost_kind", "candidate", "selected_count", "minimum", "maximum"},
    "select_object": {"kind", "source", "purpose", "choice", "selected_count", "minimum", "maximum"},
    "finish_selection": {"kind", "source", "purpose", "selected_count"},
}


def normalize_decision(decision: dict, slot: int) -> dict:
    if type(slot) is not int or not 0 <= slot <= 4096:
        raise ValueError("general target slot needs a bounded integer")
    candidates = decision.get("candidates") if isinstance(decision, dict) else None
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 4097:
        raise ValueError("general target needs its complete offered action list")
    normalized = copy.deepcopy(decision)
    group = None
    for candidate in normalized["candidates"]:
        semantic = candidate.get("semantic") if isinstance(candidate, dict) else None
        if not isinstance(semantic, dict): raise ValueError("general target action is incomplete")
        kind = semantic.get("kind")
        if not isinstance(kind, str) or kind not in FIELDS or set(semantic) != FIELDS[kind]:
            raise ValueError("general target fields differ from the wire action")
        family = {"finish_target_selection":"choose_target", "finish_selection":"select_object"}.get(kind, kind)
        label = semantic.get("purpose") if family == "select_object" else semantic.get("cost_kind") if family == "choose_cost_target" else ""
        if family != "choose_target" and (not isinstance(label, str) or not 1 <= len(label) <= 128):
            raise ValueError("general target action needs a bounded purpose or cost kind")
        if group is not None and group != (family, label):
            raise ValueError("general target actions mix callback families or purposes")
        group = family, label
        if kind == "choose_cost_target":
            semantic["target"] = {"object":semantic.pop("candidate")}
            semantic.pop("cost_kind"); semantic.update(kind="choose_target", slot=slot)
        elif kind == "select_object":
            semantic["target"] = semantic.pop("choice")
            semantic.pop("purpose"); semantic.update(kind="choose_target", slot=slot)
        elif kind == "finish_selection":
            semantic.pop("purpose"); semantic.update(kind="finish_target_selection", slot=slot)
    return normalized


def bound_view(start: dict, decision: dict) -> dict[int, dict]:
    original.bound_view(start, normalize_decision(decision, 0))
    return {candidate["candidate_id"]: copy.deepcopy(candidate["semantic"]) for candidate in decision["candidates"]}


def validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    bound_view(start, decision)
    if not isinstance(encoded, dict): raise ValueError("general target frame is missing")
    slot = encoded.get("target_slot")
    normalized = normalize_decision(decision, slot)
    expected = {"schema":"spellbench-maintainer-general-target-features/v1", "variant":VARIANT,
                "decision_sha256":decision_hash(decision), "normalized_decision_sha256":decision_hash(normalized)}
    if wire.canonical_json_dumps({key:encoded.get(key) for key in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("general target frame changed its source variant, public decision or callback mapping")
    projected = copy.deepcopy(encoded)
    projected.update(schema="spellbench-maintainer-target-features/v1", variant=original.VARIANT,
                     decision_sha256=decision_hash(normalized))
    features, slots = original.validate_encoding(start, normalized, projected, sources, request_hash)
    return (encoded if features is not None else None), slots


class GeneralTargetSession(original.TargetSession):
    """Own the same paired networks, original chooser, clock and cleanup for general choices."""
    ENCODER = "maintainer-permitted-general-target"
    VARIANT = VARIANT
    bound_view = staticmethod(bound_view)
    validate_encoding = staticmethod(validate_encoding)
