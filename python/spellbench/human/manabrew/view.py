"""Our engine's observation of the human seat, as the Manabrew protocol's ``gameView`` (StateUpdate).

Only the human seat's own observation is used, so the view shows exactly what that seat may see: the opponent's
hand and both libraries are counts only. Field names follow the protocol documentation (CC-BY-4.0, see NOTICE).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from ..text import ABILITY_KINDS, stack_bottom_first

CARDS = json.loads(Path(__file__).with_name("cards.json").read_text(encoding="utf-8"))
STEPS = {"untap": "untap", "upkeep": "upkeep", "draw": "draw", "precombat_main": "main1",
         "beginning_of_combat": "combatBegin", "declare_attackers": "combatDeclareAttackers",
         "declare_blockers": "combatDeclareBlockers", "combat_damage": "combatDamage",
         "end_of_combat": "combatEnd", "postcombat_main": "main2", "end_step": "endOfTurn", "cleanup": "cleanup",
         "pregame": "upkeep"}
COLORS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
# The client's counter table is keyed "P1P1", "M1M1" and capitalised words ("Lore", "Loyalty", "Charge"); it hides a
# saga's "Lore" counters by that exact spelling.
COUNTERS = {"p1p1": "P1P1", "m1m1": "M1M1"}
SUPERTYPES = {"Basic", "Legendary", "Snow", "World", "Ongoing"}


def title(word: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in str(word).replace("_", " ").split(" "))


def counter_key(name: str) -> str:
    return COUNTERS.get(name) or title(name)


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
    keywords = [str(k) for k in chars.get("keywords") or []]
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
        "keywords": [title(k) for k in keywords], "grantedKeywords": [],
        "counters": {counter_key(k): v for k, v in (permanent.get("counters") or {}).items() if v},
        # the engine's flag is the fact before haste (spec 6.4): a creature with haste is not summoning sick
        "damage": permanent.get("damage") or 0,
        "summoningSick": bool(permanent.get("summoning_sick")) and "haste" not in keywords,
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
    host = attached_to(permanent.get("attached_to"))
    if host:
        dto["attachedTo"] = host
    if card.get("face_down"):
        dto["identity"]["name"], dto["text"], dto["manaCost"] = "", "", ""
    return dto


def attached_to(ref: Any) -> str | None:
    """The object an Aura or Equipment is attached to. The engine's reference is a target reference
    (``{"object": {"object_id": ...}}``), the same shape as a stack target or an attack target."""
    if not isinstance(ref, Mapping):
        return None
    obj = ref.get("object") if isinstance(ref.get("object"), Mapping) else ref
    return obj.get("object_id") or None


def named_card(name: str, owner: Any, controller: Any, object_id: str) -> dict[str, Any]:
    """An engine-shaped card record built from a name alone (the adapter's card data), for a card the engine says the
    viewer knows by name or an ability's source that has left the board."""
    info = CARDS.get(name) or {}
    front, _, back = str(info.get("type_line") or "").partition(" - ")
    words = [w for w in front.split() if w != "Token"]
    cost = str(info.get("mana_cost") or "")
    symbols = re.findall(r"\{([^}]*)\}", cost)
    value = sum(int(s) if s.isdigit() else 0 if s == "X" else 1 for s in symbols)
    chars = {"colors": [c for c, letter in COLORS.items() if letter in cost], "mana_value": value,
             "types": [w.lower() for w in words if w not in SUPERTYPES],
             "supertypes": [w.lower() for w in words if w in SUPERTYPES], "subtypes": [w.lower() for w in back.split()],
             "power": info.get("power"), "toughness": info.get("toughness"), "keywords": []}
    return {"object_id": object_id, "card_name": name, "owner_seat": owner, "controller_seat": controller,
            "token": str(info.get("type_line") or "").startswith("Token"), "characteristics": chars}


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


def ability_line(rules: Any, kind: Any, source_zone: Any) -> str:
    """The line of the source card's rules text that a stack ability is, when that is certain: a triggered ability is
    a "When/Whenever/At" line (a cast trigger when its source is itself on the stack), an activated one a line with a
    cost before a colon. Several candidates (the engine does not say which ability it is) give "", so the client
    highlights nothing rather than every line."""
    lines = [line.strip() for line in str(rules or "").split("\n") if line.strip()]
    if kind == "triggered_ability":
        picks = [line for line in lines if re.match(r"(?i)(when|whenever|at)\b", line)]
        cast = [line for line in picks if re.match(r"(?i)when you cast\b", line)]
        picks = cast if source_zone == "stack" else [line for line in picks if line not in cast]
    elif kind == "activated_ability":
        picks = [line for line in lines if ":" in line and not re.match(r"(?i)(when|whenever|at)\b", line)]
    else:
        return ""
    return picks[0] if len(picks) == 1 else ""


def find_object(observation: Mapping[str, Any], object_id: Any) -> tuple[Mapping[str, Any], str] | None:
    """A record of the viewer's observation by object id: a stack object or a card in a zone the viewer sees."""
    for entry in observation.get("stack") or []:
        if entry.get("object_id") == object_id:
            return entry, "stack"
    return find_card(observation, object_id)


def source_card(entry: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> dict[str, Any] | None:
    """The card a stack object shows: the spell itself, or for an ability the card it came from (its record while the
    viewer can see it, else built from the name the engine gives). ``None`` when the viewer is not told the card."""
    if entry.get("stack_kind") == "spell":
        if entry.get("characteristics") is None or not entry.get("card_name"):
            return None
        return card_dto(entry, seats, "stack")
    source = entry.get("source") if isinstance(entry.get("source"), Mapping) else {}
    found = find_object(observation, source.get("object_id")) if source.get("object_id") else None
    if found:
        record = found[0]
    else:
        name = source.get("card_name") or entry.get("card_name")
        if not name:
            return None
        record = named_card(name, source.get("owner_seat") or entry.get("owner_seat"),
                            source.get("controller_seat") or entry.get("controller_seat"),
                            source.get("object_id") or entry.get("object_id"))
    card = card_dto(record, seats, "stack")
    if not card["identity"]["name"]:
        return None
    # the picture of the source on the stack, not its state on the board
    card.update({"tapped": False, "isAttacking": False, "summoningSick": False, "damage": 0, "counters": {},
                 "attachmentIds": [], "phasedOut": False})
    for key in ("attachedTo", "attackTargetId", "attackingPlayerId"):
        card.pop(key, None)
    return card


def stack_dto(entry: Mapping[str, Any], seats: Seats, observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    name = entry.get("card_name") or ""
    info = CARDS.get(name) or {}
    kind = entry.get("stack_kind")
    chars = entry.get("characteristics") or {}
    source = entry.get("source") if isinstance(entry.get("source"), Mapping) else None
    if kind in ABILITY_KINDS:
        text = ability_line(info.get("text"), kind, (source or {}).get("zone"))
    else:
        text = entry.get("text") or info.get("text", "")
    dto = {
        "id": entry.get("object_id"), "sourceId": (source or {}).get("object_id") or entry.get("object_id"),
        "controllerId": seats.pid(entry.get("controller_seat")), "ownerId": seats.pid(entry.get("owner_seat")),
        "identity": {"name": name, "setCode": "", "cardNumber": "", "isToken": False}, "text": text,
        "isPermanentSpell": kind == "spell" and bool({"creature", "artifact", "enchantment", "land",
                                                      "planeswalker"} & set(chars.get("types") or [])),
        "isCasting": False,
        "targets": [t for t in (target_ref(ref, seats) for ref in entry.get("targets") or []) if t is not None],
    }
    card = source_card(entry, observation, seats) if observation is not None else None
    if card is not None:  # the client draws the card, flashes a cast and sounds a resolution from it
        dto["sourceCard"] = card
    return dto


def end_statuses(terminal: Mapping[str, Any] | None, seats: Seats) -> dict[str, str]:
    """Player statuses once the game is over, by player id: the loser reads "lost", or "conceded" when the game ended
    by a concession; the winner (named by ``winnerId``) and a draw stay "playing"."""
    winner = (terminal or {}).get("winner")
    if winner not in seats.ids:
        return {}
    ended = {str(terminal.get("classification")), str(terminal.get("reason"))}
    word = "conceded" if "conceded" in ended else "lost"
    return {pid: word for seat, pid in seats.ids.items() if seat != winner}


def game_view(observation: Mapping[str, Any], seats: Seats, game_id: str, *, game_over: bool = False,
              winner: str | None = None, starter: str | None = None,
              terminal: Mapping[str, Any] | None = None) -> dict[str, Any]:
    players, zones = [], []
    blocks = []
    attachments: dict[str, list[str]] = {}
    designated: dict[str, str] = {}  # designation -> player id (monarch, initiative)
    for player in observation.get("players") or []:
        seat = player.get("seat")
        pid = seats.pid(seat)
        pool = player.get("mana_pool") or {}
        designations = player.get("designations") or []
        for designation in ("monarch", "initiative"):
            if designation in designations:
                designated[designation] = pid
        players.append({
            "id": pid, "name": seats.names.get(pid, pid), "status": "playing", "isHuman": seat == seats.human_seat,
            "life": player.get("life") or 0, "maxHandSize": 7, "unlimitedHandSize": False,
            "landsPlayedThisTurn": player.get("lands_played_this_turn") or 0, "maxLandPlaysPerTurn": 1,
            "unlimitedLandPlays": False, "cardsDrawnThisTurn": 0, "damagePrevention": 0, "isExtraTurn": False,
            "extraTurnCount": 0, "playerKeywords": [], "commanderCasts": {},
            "counters": {"poison": player["poison"]} if player.get("poison") else {},
            "manaPool": {k: v for k, v in pool.items() if v}, "commanderDamage": {},
            "hasCityBlessing": "city_blessing" in designations,
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
            # cards the engine says the viewer knows by name (seen in a public zone, revealed, tracked) show face up;
            # the engine gives no position in the hand, so they come first
            known = [k["card_name"] for k in observation.get("known") or []
                     if k.get("zone") == "hand" and k.get("owner_seat") == seat and k.get("card_name")][:count]
            cards = [visible(named_card(name, seat, seat, f"{pid}-hand-{i}"), seats, "hand")
                     for i, name in enumerate(known)]
            cards += [{"visibility": "hidden", "id": f"{pid}-hand-{i}"} for i in range(len(known), count)]
            zones.append({"zone": "hand", "ownerId": pid, "cards": cards, "count": count})
        zones.append({"zone": "library", "ownerId": pid, "cards": [], "count": player.get("library_count") or 0})
        for zone in ("graveyard", "exile"):
            cards = [visible(c, seats, zone) for c in reversed(player.get(zone) or [])]  # top first
            zones.append({"zone": zone, "ownerId": pid, "cards": cards, "count": len(cards)})
    for zone in zones:
        for card in zone["cards"]:
            if card.get("visibility") == "visible":
                card["attachmentIds"] = attachments.get(card["id"], [])
    # the client reads the last entry as the top of the stack; the engine lists the top first
    stack = [stack_dto(entry, seats, observation) for entry in stack_bottom_first(observation.get("stack"))]
    if game_over and terminal:
        for player in players:
            player["status"] = end_statuses(terminal, seats).get(player["id"], "playing")
        if winner is None and terminal.get("winner") in seats.ids:
            winner = seats.pid(terminal["winner"])
    return {
        "gameId": game_id, "turn": turn_number(observation, starter),
        "step": STEPS.get(observation.get("phase_step"), "main1"), "combatAssignments": blocks,
        "activePlayerId": seats.pid(observation.get("active_seat")),
        "priorityPlayerId": seats.pid(observation.get("priority_seat") or observation.get("active_seat")),
        "players": players, "zones": zones, "stack": stack, "gameOver": game_over, "winnerId": winner,
        "monarchId": designated.get("monarch"), "initiativeHolderId": designated.get("initiative"), "dayTime": "neither",
        "checkpoints": [], "restoreVote": None, "snapshotRecording": False,
    }


def turn_number(observation: Mapping[str, Any], starter: str | None) -> int:
    """The protocol counts every player's turn; the engine counts rounds (both players' turns, the same number),
    starting with the seat that took the first turn (``starter``: the game's ``starting_seat``, p0 unless told)."""
    rounds = observation.get("turn") or 0
    if not rounds:
        return rounds
    return 2 * (rounds - 1) + (1 if observation.get("active_seat") == (starter or "p0") else 2)


def find_card(observation: Mapping[str, Any], object_id: str) -> tuple[Mapping[str, Any], str] | None:
    for player in observation.get("players") or []:
        for zone in ("battlefield", "hand", "graveyard", "exile"):
            for card in player.get(zone) or []:
                if card.get("object_id") == object_id:
                    return card, zone
    return None
