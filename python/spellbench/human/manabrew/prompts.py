"""The human seat's pending decision as a Manabrew prompt, and the client's answer back as our candidate.

``build(pending, observation, seats)`` returns ``(input, answer)``: the prompt input (``AgentPrompt.input``) and a
function that maps the client's ``PromptOutput`` to ``("answer", candidate_id)`` or ``("plan", plan)`` for the
play server (``Hub.answer_with`` / ``Hub.plan_with``), or raises ``Rejected`` (a ``ValueError`` that carries the
protocol error code) for an answer that names no candidate. Every decision kind is answerable: kinds without a
dedicated prompt become ``chooseFromSelection`` with our own candidate labels.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from .. import text as words
from . import view
from .view import CARDS, Seats

Answer = Callable[[Mapping[str, Any]], tuple[str, Any]]
PRIORITY_KINDS = {"pass", "cast_spell", "play_land", "activate_ability", "activate_mana_ability", "special_action"}
# The client's step names (StepKind) as the observation's: the inverse of view.STEPS, plus the first strike step the
# engine's observation has no name for.
STEP_OF = {client: ours for ours, client in view.STEPS.items() if ours != "pregame"}
STEP_OF["combatFirstStrikeDamage"] = "combat_damage"
COLOR_LETTERS ={"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C"}
LANDWALKS = {"plainswalk": "plains", "islandwalk": "island", "swampwalk": "swamp", "mountainwalk": "mountain",
             "forestwalk": "forest"}


class Rejected(ValueError):
    """An answer the session cannot take. ``code`` is the protocol's error code the client is told: ``unknownActionId``
    (an id or card the prompt did not offer), ``cancelNotAllowed`` or ``invalidShape`` (anything else malformed)."""

    def __init__(self, message: str, code: str = "invalidShape") -> None:
        super().__init__(message)
        self.code = code


def source_rules(pending: Mapping[str, Any]) -> str | None:
    """The rules text of the card a decision comes from (the adapter's card data), for the prompt's text box."""
    source = (pending.get("context") or {}).get("source")
    name = source.get("card_name") if isinstance(source, Mapping) else None
    return (CARDS.get(name or "") or {}).get("text") or None


def presentation(pending: Mapping[str, Any], *, text: str | None = None, targets: list | None = None) -> dict:
    out = {"title": str(pending.get("prompt") or "Choose"), "targets": targets or []}
    if pending.get("hint"):
        out["description"] = pending["hint"]
    text = text or source_rules(pending)
    if text:
        out["text"] = text
    return out


def hold_target(until: Any, seats: Seats) -> dict[str, Any] | None:
    """The client's ``PassUntil`` ({playerId, phase, throughCombat}) as the session's hold ({seat, step,
    through_combat}), or ``None`` for a missing or unusable one (then the pass is a plain pass: the session asks at
    more windows, never at fewer)."""
    if not isinstance(until, Mapping):
        return None
    seat, step = seats.seat(str(until.get("playerId"))), STEP_OF.get(until.get("phase"))
    if seat is None or step is None:
        return None
    return {"seat": seat, "step": step, "through_combat": bool(until.get("throughCombat"))}


def _cid(c: Mapping[str, Any]) -> str:
    return str(c["id"])


def _by_id(pending: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {_cid(c): c for c in pending.get("candidates") or []}


def _produced(semantic: Mapping[str, Any]) -> list[dict]:
    choice = semantic.get("mana_choice")
    if isinstance(choice, str) and choice:
        letters = [COLOR_LETTERS.get(choice.lower(), choice[:1].upper())] if len(choice) > 2 else list(choice.upper())
        return [{"color": letter, "amount": 1} for letter in letters if letter in "WUBRGC"]
    return []


def choose_action(pending: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    actions = []
    passing = None
    for c in pending.get("candidates") or []:
        s = c.get("semantic") or {}
        kind = s.get("kind")
        source = (s.get("source") or {}).get("object_id")
        if kind == "pass":
            passing = c["id"]
        elif kind in ("cast_spell", "play_land", "special_action"):
            actions.append({"id": _cid(c), "type": "cast", "cardId": source, "mode": {"type": "normal"},
                            "label": c.get("text") or kind})
        elif kind in ("activate_ability", "activate_mana_ability"):
            name = (s.get("source") or {}).get("card_name") or ""
            # the ability's own line of the card's rules text when that is certain, else the candidate's label
            described = (words.ability_rules(s) if kind == "activate_ability" else "") or c.get("text") \
                or CARDS.get(name, {}).get("text", "")
            if (s.get("source") or {}).get("zone") == "hand" and kind == "activate_ability":
                described += " (from your hand)"  # ninjutsu, cycling and the like: say where it is activated from
            actions.append({"id": _cid(c), "type": "activateAbility", "cardId": source,
                            "abilityIndex": s.get("ability_index") or 0,
                            "description": described,
                            "isManaAbility": kind == "activate_mana_ability",
                            **({"producedMana": _produced(s)} if kind == "activate_mana_ability" else {})})

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        if output.get("type") == "pass":
            if passing is None:
                raise Rejected("passing is not a choice here", "unknownActionId")
            # Every pass button sends where the pass should run to (the pass-until: a player's step, with
            # ``throughCombat`` for END TURN and NEXT TURN) and, on a stack, ``exhaustStack``. The session holds
            # the target (``Hub.pass_with``); a pass that names neither is a single pass.
            until = hold_target(output.get("until"), seats)
            if until is None and not output.get("exhaustStack"):
                return "answer", passing
            return "pass", {"until": until, "exhaust_stack": bool(output.get("exhaustStack"))}
        if output.get("type") == "act":
            action = str(output.get("actionId"))
            if action in _by_id(pending):
                return "answer", int(action)
            raise Rejected(f"action id {action!r} was not advertised by the prompt", "unknownActionId")
        raise Rejected("unknown action")

    return {"type": "chooseAction", "actions": actions}, answer


def _controlled_by_opponent(target: Any, me: str) -> bool | None:
    """Whether a target reference is the opponent's (a player, or an object they control); ``None`` when unknown."""
    if not isinstance(target, Mapping):
        return None
    if "player" in target:
        return target["player"] != me
    obj = target.get("object") if isinstance(target.get("object"), Mapping) else target
    seat = obj.get("controller_seat") or obj.get("owner_seat")
    return None if seat is None else seat != me


# What an effect does to its target, by the rules text of its source: a hostile one is drawn with the client's hostile
# (red) outline, a friendly one with the friendly (green) one.
HOSTILE_TEXT = re.compile(r"(?i)\bdamage\b|\bdestroy\b|\bexile target\b|\bcounter target\b|\bgets? -\d|\btap target\b|"
                          r"\bsacrifices?\b|\bowner's hand\b|\bloses?\b|\bfights?\b|\bgain control\b|\bdiscards?\b")
FRIENDLY_TEXT = re.compile(r"(?i)\bgains?\b|\+\d+/\+\d+|\bgets? \+|\bcounter on\b|\bfrom your graveyard\b|"
                           r"\buntap target\b|\bregenerate\b|\bhexproof\b|\bprotection from\b|\bexplores\b")


def targeting_hostile(semantics: list[Mapping[str, Any]], me: str, rules: str | None) -> bool:
    """Whether the targets of this decision are for harming: every candidate is the opponent's, or (candidates of
    both sides, a Bolt) the source's rules text is a hostile effect. Anything unclear is not hostile."""
    sides = [_controlled_by_opponent(s.get("target"), me) for s in semantics]
    known = [side for side in sides if side is not None]
    if known and len(known) == len(sides):
        if all(known):
            return True
        if not any(known):
            return False
    if not rules:
        return False
    rules = re.sub(r"\([^)]*\)", "", rules)  # reminder text ("you may cast this from your graveyard") says nothing
    return bool(HOSTILE_TEXT.search(rules)) and not FRIENDLY_TEXT.search(rules)


def board_targets(pending: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    candidates, by_ref, done, semantics = [], {}, None, []
    for c in pending.get("candidates") or []:
        s = c.get("semantic") or {}
        if s.get("kind") == "finish_target_selection":
            done = c["id"]
            continue
        ref = view.target_ref(s.get("target"), seats)
        if ref is not None:
            candidates.append(ref)
            semantics.append(s)
            by_ref[(ref["kind"], ref["id"])] = c["id"]
    source = ((pending.get("context") or {}).get("source") or {}).get("card_name")
    rules = CARDS.get(source or "", {}).get("text")
    first = semantics[0] if semantics else {}
    # the engine's own bounds and progress: Blood Fountain's "up to two" shows 0 of 2 and then Done after one
    minimum = first.get("minimum", 0 if done is not None else 1)
    maximum = first.get("maximum", 1)
    chosen = first.get("selected_count", 0)
    hostile = targeting_hostile(semantics, seats.human_seat, rules)
    data = {"type": "chooseBoardTargets", "presentation": presentation(pending, text=rules),
            "candidates": candidates, "hostile": hostile, "intent": "hostile" if hostile else "friendly",
            "minTargets": int(minimum), "maxTargets": max(int(maximum), int(minimum)), "chosenTargets": int(chosen),
            # a target prompt can be backed out of only where the engine can rewind; no engine here can (every
            # decision's context says rewind false, and the protocol has no candidate for a rewind), so no Cancel
            "cancellable": False}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        if output.get("type") == "cancel":
            raise Rejected("this prompt is not cancellable", "cancelNotAllowed")
        picked = output.get("chosen") or []
        if not picked:
            if done is None:
                raise Rejected("a target is required")
            return "answer", done
        ref = picked[0]
        key = (ref.get("kind"), ref.get("id"))
        if key not in by_ref:  # a card on the stack may come back as "card"
            key = next((k for k in by_ref if k[1] == ref.get("id")), key)
        if key in by_ref:
            return "answer", by_ref[key]
        raise Rejected("not a candidate target", "unknownActionId")

    return data, answer


def _object_of(semantic: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("candidate", "choice", "card", "object"):
        value = semantic.get(key)
        if isinstance(value, Mapping):
            obj = value.get("object") if isinstance(value.get("object"), Mapping) else value
            if obj.get("object_id"):
                return obj
    return None


def choose_cards(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer] | None:
    cards, by_id = [], {}
    for c in pending.get("candidates") or []:
        obj = _object_of(c.get("semantic") or {})
        if obj is None:
            return None
        found = view.find_card(observation, obj["object_id"])
        card = view.card_dto(found[0], seats, found[1]) if found else view.card_dto(
            {"object_id": obj["object_id"], "card_name": obj.get("card_name"), "controller_seat": obj.get("controller_seat"),
             "owner_seat": obj.get("owner_seat")}, seats, obj.get("zone") or "battlefield")
        cards.append(card)
        by_id[obj["object_id"]] = c["id"]
    data = {"type": "chooseCards", "presentation": presentation(pending), "cards": cards, "min": 1, "max": 1}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        chosen = output.get("chosenCardIds") or []
        if len(chosen) == 1 and chosen[0] in by_id:
            return "answer", by_id[chosen[0]]
        if len(chosen) == 1:
            raise Rejected("that card is not one of the offered cards", "unknownActionId")
        raise Rejected("choose exactly one of the offered cards")

    return data, answer


def selection(pending: Mapping[str, Any]) -> tuple[dict, Answer]:
    candidates = list(pending.get("candidates") or [])
    data = {"type": "chooseFromSelection", "presentation": presentation(pending),
            "options": [{"label": c.get("text") or str(c.get("kind")), "weight": 1, "canRepeat": False}
                        for c in candidates], "minTotal": 1, "maxTotal": 1}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        chosen = output.get("chosenIndices") or []
        if len(chosen) == 1 and 0 <= int(chosen[0]) < len(candidates):
            return "answer", candidates[int(chosen[0])]["id"]
        if len(chosen) == 1:
            raise Rejected("that option was not offered", "unknownActionId")
        raise Rejected("choose exactly one option")

    return data, answer


def boolean(pending: Mapping[str, Any]) -> tuple[dict, Answer] | None:
    yes = no = None
    for c in pending.get("candidates") or []:
        s = c.get("semantic") or {}
        value = s.get("value", s.get("pay", s.get("cast_it", s.get("keep"))))
        if value is True:
            yes = c
        elif value is False:
            no = c
    if yes is None or no is None or len(pending.get("candidates") or []) != 2:
        return None
    data = {"type": "chooseBoolean", "presentation": presentation(pending), "confirmLabel": yes.get("text") or "Yes",
            "denyLabel": no.get("text") or "No"}
    return data, lambda output: ("answer", yes["id"] if output.get("value") else no["id"])


def _keywords(card: Mapping[str, Any]) -> set[str]:
    return {str(k).lower() for k in (card.get("characteristics") or {}).get("keywords") or []}


def attackers(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    """The attack declaration as one prompt, when the creatures the engine will ask about are known for certain: the
    untapped creatures that are not summoning sick (or have haste) and have no defender. The engine asks about each
    in turn (``substep_count`` of them); when our list does not have that many, or lacks the one asked about now, the
    declaration is asked creature by creature (``selection``) so no creature is guessed or dropped."""
    me = seats.human_seat
    opponent = "p1" if me == "p0" else "p0"
    candidates = pending.get("candidates") or []
    mine = ((candidates[0].get("semantic") or {}).get("attacker") or {}) if candidates else {}
    count = (pending.get("group") or {}).get("substep_count") or 1
    options = []
    for player in observation.get("players") or []:
        if player.get("seat") != me:
            continue
        for card in player.get("battlefield") or []:
            permanent = card.get("permanent") or {}
            chars = card.get("characteristics") or {}
            keywords = _keywords(card)
            if ("creature" in (chars.get("types") or []) and not permanent.get("tapped")
                    and (not permanent.get("summoning_sick") or "haste" in keywords) and "defender" not in keywords):
                options.append(card.get("object_id"))
    first = mine.get("object_id")
    if len(options) != count or (first and first not in options):
        return selection(pending)
    if first:
        options.remove(first)
        options.insert(0, first)
    # an attack that is forced (no "no attack" candidate: goad, must attack) is known for the creature asked about now
    forced = bool(candidates) and not any(c["semantic"].get("defender") is None for c in candidates)
    target = seats.pid(opponent)
    data = {"type": "chooseAttackers",
            "attackers": [{"attackerId": oid, "validTargetIds": [target], "mustAttack": forced and oid == first}
                          for oid in options],
            "attackTargets": [{"id": target, "label": seats.names.get(target, "Opponent"), "kind": "player"}]}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        chosen = [a.get("attackerId") for a in output.get("assignments") or []]
        return "plan", {"kind": "attack", "attackers": chosen}

    return data, answer


def can_block(attacker: Mapping[str, Any], blocker: Mapping[str, Any]) -> bool:
    """Whether the blocker may block the attacker on evasion alone: flying needs flying or reach."""
    if "flying" in _keywords(attacker) and not {"flying", "reach"} & _keywords(blocker):
        return False
    return True


def unblockable(attacker: Mapping[str, Any], defender_lands: set[str]) -> bool:
    keywords = _keywords(attacker)
    return "cant_be_blocked" in keywords or any(LANDWALKS[k] in defender_lands for k in keywords if k in LANDWALKS)


def blockers(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats,
             error: str | None = None) -> tuple[dict, Answer]:
    """The block declaration as one prompt. Each attacker lists the blockers that may block it (flying and reach, the
    landwalks and "can't be blocked"; menace asks for two); the engine's own check of the first block still rules, and
    a block it refuses comes back as this prompt again with ``error`` (``Bridge`` sends it)."""
    me = seats.human_seat
    attacking, mine, lands = [], [], set()
    for player in observation.get("players") or []:
        for card in player.get("battlefield") or []:
            permanent = card.get("permanent") or {}
            chars = card.get("characteristics") or {}
            if player.get("seat") != me and permanent.get("attacking"):
                attacking.append(card)
            elif player.get("seat") == me:
                if "creature" in (chars.get("types") or []) and not permanent.get("tapped"):
                    mine.append(card)
                if "land" in (chars.get("types") or []):
                    lands.update(str(t).lower() for t in chars.get("subtypes") or [])
    entries = []
    for attacker in attacking:
        valid = [] if unblockable(attacker, lands) else [b.get("object_id") for b in mine if can_block(attacker, b)]
        entries.append({"attackerId": attacker.get("object_id"), "validBlockerIds": valid,
                        "minBlockers": 2 if "menace" in _keywords(attacker) else 0, "mustBeBlocked": False})
    ids = [b.get("object_id") for b in mine]
    data = {"type": "chooseBlockers", "attackers": entries, "availableBlockerIds": ids}
    if error:
        data["error"] = error

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        blocks = {a.get("blockerId"): a.get("attackerId") for a in output.get("assignments") or []}
        return "plan", {"kind": "block", "blocks": {b: blocks.get(b) for b in ids}}

    return data, answer


def build(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats,
          error: str | None = None) -> tuple[dict, Answer]:
    kinds = {c.get("kind") for c in pending.get("candidates") or []}
    context = pending.get("context") or {}
    if context.get("kind") == "priority" and kinds <= PRIORITY_KINDS:
        return choose_action(pending, seats)
    if pending.get("screen") == "attack":
        return attackers(pending, observation, seats)
    if pending.get("screen") == "block":
        return blockers(pending, observation, seats, error)
    if kinds <= {"choose_target", "finish_target_selection"} and "choose_target" in kinds:
        return board_targets(pending, seats)
    if kinds <= {"choose_cost_target", "select_object"}:
        built = choose_cards(pending, observation, seats)
        if built is not None:
            return built
    built = boolean(pending)
    if built is not None:
        return built
    return selection(pending)
