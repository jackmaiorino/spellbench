"""Neutral v2 vocabulary for the human-play London pregame.

Wraps the pinned `ordinary_semantic` (kernel_semantics_v2.py, never edited)
with the two native London kinds the human-play bridge adds: the keep or
mulligan answer and the choice of one card to put on the bottom. Every other
kind goes through the pinned function unchanged.

The bridge's engine bottoms a mulligan's cards right after the new seven are
drawn, one native decision per card, before the next keep or mulligan answer.
Each of those decisions is one substep of the protocol's `mulligan_bottom`
group (`position` counts the bottoms already made, `count` is the seat's
mulligans taken), so a client can pose the group as one put-back prompt.
"""
from __future__ import annotations

from kernel_observation_v2 import ProjectionError
from kernel_semantics_v2 import ordinary_semantic as pinned_ordinary_semantic
from spellbench.candidates import validate_semantic

NATIVE_SEATS = ("p0", "p1")


def ordinary_semantic(semantic, raw, support, projection, group, *, candidate_id=None):
    kind = semantic["kind"]
    if kind not in ("london_mulligan", "london_bottom"):
        return pinned_ordinary_semantic(semantic, raw, support, projection, group, candidate_id=candidate_id)
    london = support.get("london")
    if london is None or london.get("phase") not in ("announce", "bottom"):
        raise ProjectionError("a London choice outside a pending opening")
    actor = NATIVE_SEATS.index(raw["acting_player"])
    taken = london["mulligans_taken"][actor]
    if kind == "london_mulligan":
        if semantic["mulligan_count"] != taken or london["phase"] != "announce":
            raise ProjectionError("London mulligan count disagrees with the public count")
        result = {"kind": "mulligan", "hand_size": len(raw["own_hand"]), "mulligans_taken": taken,
                  "keep": not semantic["mulligan"]}
    else:
        remaining = semantic["remaining"]
        if london["phase"] != "bottom" or not 1 <= remaining <= taken:
            raise ProjectionError("London bottom count disagrees with the public count")
        result = {"kind": "order_pick", "source": None, "purpose": "mulligan_bottom",
                  "item": {"object": projection.legacy_ref(semantic["card"])},
                  "position": taken - remaining, "count": taken}
    validate_semantic(result)
    return result
