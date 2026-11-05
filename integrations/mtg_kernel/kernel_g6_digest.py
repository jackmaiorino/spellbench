"""Point tensor digests for the commit check (fairness gate G6).

The entrant's walk records, at each native point it decides, the digest of
the x_kernel_flat_v4 tensor of its imported state; the adapter records the
digest of the committed (native) point. The two differ, by design, when the
export's knowledge of the opponent's hand differs from the native engine's
known-hand rows: the export's own check allows it (x_kernel_infoset_v1 R5: a
released same-name copy may stay in the engine's rows), and its knowledge
follows V's information (name-level departures, put-back draws) where the
engine's rows follow object identity.

``known_hand_masked_digest`` digests the tensor without that one component:
the KnownOpponentHand objects with their relations, the opponent's
known-hand count in the state, and the state's digest of the canonical
observation (which includes the known hand). ``known_hand_digest`` digests
the known opponent hand itself (its card ids, sorted). G6 accepts a point
whose full digests differ only when the masked digests are equal and the
known hands differ, and reports it as a known-hand divergence; any other
difference is a failure. At such a point what only the observation digest
carries (for example subtype identities, of which the object features keep
the count) is not compared: the walk's pool returns no observation, so a
digest of it without the known hand needs the kernel. The functions are
defined for one feature encoding; for any other they return None (full
digests only).
"""
from __future__ import annotations

import hashlib
import json
import struct
from typing import Any

# The x_kernel_flat_v4 feature encoding the mask's layout belongs to
# (kernel_flat_bot.FEATURE_ENCODING_DIGEST).
MASK_ENCODING_DIGEST = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"
KNOWN_OPPONENT_HAND = 18  # FlatObjectGroupV2::KnownOpponentHand
STATE_DIM = 219
# state[71]: the opponent's KnownHand relations / 16; state[123:219]: the
# 96-value digest of the canonical observation.
STATE_KNOWN_OPPONENT_HAND = 71
STATE_OBSERVATION_DIGEST = 123


def tensor_digest(tensor: Any) -> str:
    """sha256 of a tensor's canonical JSON (the G6 point digest)."""
    text = json.dumps(tensor, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _rows(flat: list, count: int) -> list[list] | None:
    if count == 0:
        return [] if not flat else None
    if len(flat) % count:
        return None
    width = len(flat) // count
    return [flat[i * width:(i + 1) * width] for i in range(count)]


def known_hand_digest(flat_extension: dict[str, Any]) -> str | None:
    """sha256 of the sorted card ids of the point's KnownOpponentHand objects,
    or None when the extension is not of the mask's encoding."""
    if flat_extension.get("feature_encoding_digest") != MASK_ENCODING_DIGEST:
        return None
    try:
        t = flat_extension["tensor"]
        cards = sorted(c for g, c in zip(t["object_groups"], t["object_card_ids"], strict=True)
                       if g == KNOWN_OPPONENT_HAND)
    except (KeyError, TypeError, ValueError):
        return None
    return tensor_digest(cards)


def known_hand_masked_digest(flat_extension: dict[str, Any]) -> str | None:
    """The point digest without V's knowledge of the opponent's hand, or None
    when the extension is not of the mask's encoding or its tensor does not
    have the layout the mask assumes."""
    if flat_extension.get("feature_encoding_digest") != MASK_ENCODING_DIGEST:
        return None
    t = flat_extension.get("tensor")
    try:
        groups, cards, nodes = t["object_groups"], t["object_card_ids"], t["object_node_ids"]
        state = t["state"]
        n = len(groups)
        if len(cards) != n or nodes != list(range(n)) or len(state) != STATE_DIM:
            return None
        drop = {i for i, g in enumerate(groups) if g == KNOWN_OPPONENT_HAND}
        if state[STATE_KNOWN_OPPONENT_HAND] != _f32_bits(len(drop) / 16.0):
            return None
        objects = _rows(t["object_features"], n)
        src, dst = t["edge_source_indices"], t["edge_target_indices"]
        edges = _rows(t["edge_features"], len(src))
        refs = t["action_ref_node_indices"]
        if objects is None or edges is None or len(dst) != len(src):
            return None
        if any(not 0 <= x < n for x in (*src, *dst, *refs)) or any(x in drop for x in refs):
            return None
        keep = [i for i in range(n) if i not in drop]
        index = {old: new for new, old in enumerate(keep)}
        kept_edges = [j for j in range(len(src)) if src[j] not in drop and dst[j] not in drop]
        masked = {
            **t,
            "object_groups": [groups[i] for i in keep],
            "object_card_ids": [cards[i] for i in keep],
            "object_node_ids": list(range(len(keep))),
            "object_features": [x for i in keep for x in objects[i]],
            "edge_source_indices": [index[src[j]] for j in kept_edges],
            "edge_target_indices": [index[dst[j]] for j in kept_edges],
            "edge_features": [x for j in kept_edges for x in edges[j]],
            "action_ref_node_indices": [index[x] for x in refs],
            "state": state[:STATE_KNOWN_OPPONENT_HAND] + state[STATE_KNOWN_OPPONENT_HAND + 1:STATE_OBSERVATION_DIGEST],
        }
    except (KeyError, TypeError):
        return None
    return tensor_digest(masked)
