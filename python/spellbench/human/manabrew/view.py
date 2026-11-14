"""Our engine's observation of the human seat, as the Manabrew protocol's ``gameView`` (StateUpdate).

Only the human seat's own observation is used, so the view shows exactly what that seat may see: the opponent's
hand and both libraries are counts only. Field names follow the protocol documentation (CC-BY-4.0, see NOTICE).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

CARDS = json.loads(Path(__file__).with_name("cards.json").read_text(encoding="utf-8"))
STEPS = {"untap": "untap", "upkeep": "upkeep", "draw": "draw", "precombat_main": "main1",
         "beginning_of_combat": "combatBegin", "declare_attackers": "combatDeclareAttackers",
         "declare_blockers": "combatDeclareBlockers", "combat_damage": "combatDamage",
         "end_of_combat": "combatEnd", "postcombat_main": "main2", "end_step": "endOfTurn", "cleanup": "cleanup",
         "pregame": "upkeep"}
COLORS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
COUNTERS = {"p1p1": "P1P1", "m1m1": "M1M1", "stun": "STUN", "lore": "LORE"}


def title(word: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in str(word).replace("_", " ").split(" "))


class Seats:
    """Our seats ("p0", "p1") and the protocol's player ids ("player-<index in the relay's player order>")."""

    def __init__(self, human_seat: str, human_id: str, bot_id: str, names: Mapping[str, str]) -> None:
        self.human_seat = human_seat
        other = "p1" if human_seat == "p0" else "p0"
        self.ids = {human_seat: human_id, other: bot_id}
        self.names = names  # player id -> display name

    def pid(self, seat: Any) -> str:
        return self.ids.get(seat, str(seat))

    def seat(self, pid: str) -> str | None:
        return next((s for s, p in self.ids.items() if p == pid), None)


def card_dto(card: Mapping[str, Any], seats: Seats, zone: str) -> dict[str, Any]:
    name = card.get("card_name") or ""
    info = CARDS.get(name) or CARDS.get(card.get("full_name") or "") or {}
    chars = card.get("characteristics") or {}
    permanent = card.get("permanent") or {}
    colors = "".join(COLORS.get(c, "") for c in chars.get("colors") or [])
    power, toughness = chars.get("power"), chars.get("toughness")
    attack = permanent.get("attack_target")
    dto: dict[str, Any] = {
        "id": card.get("object_id"),
        "identity": {"name": name, "setCode": "", "cardNumber": "", "isToken": bool(card.get("token"))},
        "color": colors, "manaCost": info.get("mana_cost", ""), "cmc": chars.get("mana_value") or 0,
        "types": [title(t) for t in chars.get("types") or []],
        "subtypes": [title(t) for t in chars.get("subtypes") or []],
        "supertypes": [title(t) for t in chars.get("supertypes") or []],
        "power": None if power is None else str(power), "toughness": None if toughness is None else str(toughness),
        "classLevels": [], "sagaChapters": [], "text": info.get("text", ""), "choices": [],
        "controllerId": seats.pid(card.get("controller_seat")), "ownerId": seats.pid(card.get("owner_seat")),
        "tapped": bool(permanent.get("tapped")), "isCrewed": False, "isAttacking": bool(permanent.get("attacking")),
        "keywords": [title(k) for k in chars.get("keywords") or []], "grantedKeywords": [],
        "counters": {COUNTERS.get(k, k.upper()): v for k, v in (permanent.get("counters") or {}).items() if v},
        "damage": permanent.get("damage") or 0, "summoningSick": bool(permanent.get("summoning_sick")),
        "isCopy": bool(card.get("copy")), "isDoubleFaced": "//" in (card.get("full_name") or ""),
        "isTransformed": False, "isFaceDown": bool(card.get("face_down")), "isBestowed": False, "phasedOut":
        bool(permanent.get("phased_out")), "exerted": False, "isRingBearer": False, "attachmentIds": [],
        "mergedCardIds": [], "isMadnessExiled": False, "isPlotted": False, "isWarpExiled": False, "foil": False,
        "wouldDieInCombat": False, "zone": zone,
    }
    for key, value in (("basePower", info.get("power")), ("baseToughness", info.get("toughness"))):
        if isinstance(value, str) and value.lstrip("-").isdigit():
            dto[key] = int(value)
    if isinstance(attack, Mapping):
        if "player" in attack:
            dto["attackTargetId"] = dto["attackingPlayerId"] = seats.pid(attack["player"])
        elif isinstance(attack.get("object"), Mapping):
            dto["attackTargetId"] = attack["object"].get("object_id")
    attached = permanent.get("attached_to")
    if isinstance(attached, Mapping) and attached.get("object_id"):
        dto["attachedTo"] = attached["object_id"]
    if card.get("face_down"):
        dto["identity"]["name"], dto["text"], dto["manaCost"] = "", "", ""
    return dto


def visible(card: Mapping[str, Any], seats: Seats, zone: str) -> dict[str, Any]:
    return {"visibility": "visible", **card_dto(card, seats, zone)}


def target_ref(ref: Any, seats: Seats) -> dict[str, Any] | None:
    if not isinstance(ref, Mapping):
        return None
    if "player" in ref:
        return {"kind": "player", "id": seats.pid(ref["player"])}
    obj = ref.get("object") if "object" in ref else ref
    if isinstance(obj, Mapping) and obj.get("object_id"):
        return {"kind": "spell" if obj.get("zone") == "stack" else "card", "id": obj["object_id"]}
    return None


def stack_dto(entry: Mapping[str, Any], seats: Seats) -> dict[str, Any]:
    name = entry.get("card_name") or ""
    info = CARDS.get(name) or {}
    kind = entry.get("stack_kind")
    chars = entry.get("characteristics") or {}
    source = entry.get("source") if isinstance(entry.get("source"), Mapping) else None
    text = entry.get("text") or info.get("text", "")
    if kind == "triggered_ability":
        text = f"Triggered ability of {name}. {info.get('text', '')}".strip()
    elif kind == "activated_ability":
        text = f"Activated ability of {name}. {info.get('text', '')}".strip()
    return {
        "id": entry.get("object_id"), "sourceId": (source or {}).get("object_id") or entry.get("object_id"),
        "controllerId": seats.pid(entry.get("controller_seat")), "ownerId": seats.pid(entry.get("owner_seat")),
        "identity": {"name": name, "setCode": "", "cardNumber": "", "isToken": False}, "text": text,
        "isPermanentSpell": kind == "spell" and bool({"creature", "artifact", "enchantment", "land",
                                                      "planeswalker"} & set(chars.get("types") or [])),
        "isCasting": False,
        "targets": [t for t in (target_ref(ref, seats) for ref in entry.get("targets") or []) if t is not None],
    }


def game_view(observation: Mapping[str, Any], seats: Seats, game_id: str, *, game_over: bool = False,
              winner: str | None = None) -> dict[str, Any]:
    players, zones = [], []
    blocks = []
    attachments: dict[str, list[str]] = {}
    for player in observation.get("players") or []:
        seat = player.get("seat")
        pid = seats.pid(seat)
        pool = player.get("mana_pool") or {}
        players.append({
            "id": pid, "name": seats.names.get(pid, pid), "status": "playing", "isHuman": seat == seats.human_seat,
            "life": player.get("life") or 0, "maxHandSize": 7, "unlimitedHandSize": False,
            "landsPlayedThisTurn": player.get("lands_played_this_turn") or 0, "maxLandPlaysPerTurn": 1,
            "unlimitedLandPlays": False, "cardsDrawnThisTurn": 0, "damagePrevention": 0, "isExtraTurn": False,
            "extraTurnCount": 0, "playerKeywords": [], "commanderCasts": {},
            "counters": {"poison": player["poison"]} if player.get("poison") else {},
            "manaPool": {k: v for k, v in pool.items() if v}, "commanderDamage": {}, "hasCityBlessing": False,
            "hasEnduringStory": False, "ringLevel": 0, "speed": 0,
        })
        battlefield = [visible(c, seats, "battlefield") for c in player.get("battlefield") or []]
        for card, raw in zip(battlefield, player.get("battlefield") or []):
            if card.get("attachedTo"):
                attachments.setdefault(card["attachedTo"], []).append(card["id"])
            for attacker in (raw.get("permanent") or {}).get("blocked_attackers") or []:
                if isinstance(attacker, Mapping):
                    blocks.append({"blockerId": card["id"], "attackerId": attacker.get("object_id")})
        hand = player.get("hand")
        zones.append({"zone": "battlefield", "ownerId": pid, "cards": battlefield, "count": len(battlefield)})
        if hand is not None:
            cards = [visible(c, seats, "hand") for c in hand]
            zones.append({"zone": "hand", "ownerId": pid, "cards": cards, "count": len(cards)})
        else:
            count = player.get("hand_count") or 0
            zones.append({"zone": "hand", "ownerId": pid,
                          "cards": [{"visibility": "hidden", "id": f"{pid}-hand-{i}"} for i in range(count)],
                          "count": count})
        zones.append({"zone": "library", "ownerId": pid, "cards": [], "count": player.get("library_count") or 0})
        for zone in ("graveyard", "exile"):
            cards = [visible(c, seats, zone) for c in reversed(player.get(zone) or [])]  # top first
            zones.append({"zone": zone, "ownerId": pid, "cards": cards, "count": len(cards)})
    for zone in zones:
        for card in zone["cards"]:
            if card.get("visibility") == "visible":
                card["attachmentIds"] = attachments.get(card["id"], [])
    stack = [stack_dto(entry, seats) for entry in reversed(observation.get("stack") or [])]  # top first
    return {
        "gameId": game_id, "turn": observation.get("turn") or 0,
        "step": STEPS.get(observation.get("phase_step"), "main1"), "combatAssignments": blocks,
        "activePlayerId": seats.pid(observation.get("active_seat")),
        "priorityPlayerId": seats.pid(observation.get("priority_seat") or observation.get("active_seat")),
        "players": players, "zones": zones, "stack": stack, "gameOver": game_over, "winnerId": winner,
        "monarchId": None, "initiativeHolderId": None, "dayTime": "neither", "checkpoints": [], "restoreVote": None,
        "snapshotRecording": False,
    }


def find_card(observation: Mapping[str, Any], object_id: str) -> tuple[Mapping[str, Any], str] | None:
    for player in observation.get("players") or []:
        for zone in ("battlefield", "hand", "graveyard", "exile"):
            for card in player.get(zone) or []:
                if card.get("object_id") == object_id:
                    return card, zone
    return None
