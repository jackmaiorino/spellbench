"""The human seat's pending decision as a Manabrew prompt, and the client's answer back as our candidate.

``build(pending, observation, seats)`` returns ``(input, answer)``: the prompt input (``AgentPrompt.input``) and a
function that maps the client's ``PromptOutput`` to ``("answer", candidate_id)`` or ``("plan", plan)`` for the
play server (``Hub.answer_with`` / ``Hub.plan_with``), or raises ``ValueError`` for an answer that names no
candidate. Every decision kind is answerable: kinds without a dedicated prompt become ``chooseFromSelection`` with
our own candidate labels.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from . import view
from .view import CARDS, Seats

Answer = Callable[[Mapping[str, Any]], tuple[str, Any]]
PRIORITY_KINDS = {"pass", "cast_spell", "play_land", "activate_ability", "activate_mana_ability", "special_action"}
COLOR_LETTERS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C"}


def presentation(pending: Mapping[str, Any], *, text: str | None = None, targets: list | None = None) -> dict:
    out = {"title": str(pending.get("prompt") or "Choose"), "targets": targets or []}
    if pending.get("hint"):
        out["description"] = pending["hint"]
    if text:
        out["text"] = text
    return out


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
            actions.append({"id": _cid(c), "type": "activateAbility", "cardId": source,
                            "abilityIndex": s.get("ability_index") or 0,
                            "description": c.get("text") or CARDS.get(name, {}).get("text", ""),
                            "isManaAbility": kind == "activate_mana_ability",
                            **({"producedMana": _produced(s)} if kind == "activate_mana_ability" else {})})

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        if output.get("type") == "pass":
            if passing is None:
                raise ValueError("passing is not a choice here")
            return "answer", passing
        if output.get("type") == "act":
            action = str(output.get("actionId"))
            if action in _by_id(pending):
                return "answer", int(action)
        raise ValueError("unknown action")

    return {"type": "chooseAction", "actions": actions}, answer


def board_targets(pending: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    candidates, by_ref, done = [], {}, None
    for c in pending.get("candidates") or []:
        s = c.get("semantic") or {}
        if s.get("kind") == "finish_target_selection":
            done = c["id"]
            continue
        ref = view.target_ref(s.get("target"), seats)
        if ref is not None:
            candidates.append(ref)
            by_ref[(ref["kind"], ref["id"])] = c["id"]
    source = ((pending.get("context") or {}).get("source") or {}).get("card_name")
    data = {"type": "chooseBoardTargets", "presentation": presentation(pending, text=CARDS.get(source or "", {}).get("text")),
            "candidates": candidates, "hostile": False, "intent": "hostile", "minTargets": 0 if done is not None else 1,
            "maxTargets": 1, "chosenTargets": 0, "cancellable": False}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        chosen = output.get("chosen") or []
        if not chosen:
            if done is None:
                raise ValueError("a target is required")
            return "answer", done
        ref = chosen[0]
        key = (ref.get("kind"), ref.get("id"))
        if key not in by_ref:  # a card on the stack may come back as "card"
            key = next((k for k in by_ref if k[1] == ref.get("id")), key)
        if key in by_ref:
            return "answer", by_ref[key]
        raise ValueError("not a candidate target")

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
        raise ValueError("choose exactly one of the offered cards")

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
        raise ValueError("choose exactly one option")

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


def _hand(observation: Mapping[str, Any], seats: Seats) -> list[Mapping[str, Any]]:
    for player in observation.get("players") or []:
        if player.get("seat") == seats.human_seat:
            return list(player.get("hand") or [])
    return []


def mulligan(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer] | None:
    """London keep or mulligan: Manabrew's ``mulligan`` prompt (Keep and Mulligan buttons, the count as a badge)."""
    keep = mull = None
    taken = 0
    for c in pending.get("candidates") or []:
        s = c.get("semantic") or {}
        taken = s.get("mulligans_taken", taken)
        if s.get("keep") is True:
            keep = c
        elif s.get("keep") is False:
            mull = c
    if keep is None:
        return None
    data = {"type": "mulligan", "handCardIds": [card.get("object_id") for card in _hand(observation, seats)],
            "mulliganCount": int(taken)}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        if output.get("type") != "mulliganDecision" or not isinstance(output.get("keep"), bool):
            raise ValueError("answer keep or mulligan")
        if output["keep"]:
            return "answer", keep["id"]
        if mull is None:
            raise ValueError("no further mulligan is allowed")
        return "answer", mull["id"]

    return data, answer


def put_back(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer] | None:
    """The first substep of a ``mulligan_bottom`` group as Manabrew's ``mulliganPutBack`` prompt: the person picks
    all ``count`` cards at once, and the picks come back in click order as the group's substeps."""
    candidates = [c for c in pending.get("candidates") or []
                  if (c.get("semantic") or {}).get("purpose") == "mulligan_bottom"]
    if not candidates or len(candidates) != len(pending.get("candidates") or []):
        return None
    count = int((candidates[0]["semantic"] or {}).get("count") or 1)
    hand = _hand(observation, seats)
    ids = [((c["semantic"].get("item") or {}).get("object") or {}).get("object_id") for c in candidates]
    if any(i is None for i in ids) or sorted(ids) != sorted(card.get("object_id") for card in hand):
        return None  # the offered cards are not the whole visible hand: fall back to a plain selection
    data = {"type": "mulliganPutBack", "handCardIds": [card.get("object_id") for card in hand],
            "cards": [view.card_dto(card, seats, "hand") for card in hand], "count": count}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        picked = output.get("cardIds") if output.get("type") == "mulliganPutBackDecision" else None
        if (not isinstance(picked, list) or len(picked) != count or len(set(picked)) != count
                or any(p not in ids for p in picked)):
            raise ValueError(f"choose exactly {count} different cards from your hand")
        return "plan", {"kind": "bottom", "cards": list(picked)}

    return data, answer


def attackers(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    me = seats.human_seat
    opponent = "p1" if me == "p0" else "p0"
    first = ((pending.get("candidates") or [{}])[0].get("semantic") or {}).get("attacker") or {}
    count = (pending.get("group") or {}).get("substep_count") or 1
    options = []
    for player in observation.get("players") or []:
        if player.get("seat") != me:
            continue
        for card in player.get("battlefield") or []:
            permanent = card.get("permanent") or {}
            chars = card.get("characteristics") or {}
            haste = "haste" in (chars.get("keywords") or [])
            if ("creature" in (chars.get("types") or []) and not permanent.get("tapped")
                    and (not permanent.get("summoning_sick") or haste)):
                options.append(card.get("object_id"))
    if first.get("object_id") in options:
        options.remove(first["object_id"])
    options = ([first["object_id"]] if first.get("object_id") else []) + options
    options = options[:count]
    target = seats.pid(opponent)
    data = {"type": "chooseAttackers",
            "attackers": [{"attackerId": oid, "validTargetIds": [target], "mustAttack": False} for oid in options],
            "attackTargets": [{"id": target, "label": seats.names.get(target, "Opponent"), "kind": "player"}]}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        chosen = [a.get("attackerId") for a in output.get("assignments") or []]
        return "plan", {"kind": "attack", "attackers": chosen}

    return data, answer


def blockers(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    me = seats.human_seat
    attacking, mine = [], []
    for player in observation.get("players") or []:
        for card in player.get("battlefield") or []:
            permanent = card.get("permanent") or {}
            if player.get("seat") != me and permanent.get("attacking"):
                attacking.append(card.get("object_id"))
            elif (player.get("seat") == me and "creature" in ((card.get("characteristics") or {}).get("types") or [])
                  and not permanent.get("tapped")):
                mine.append(card.get("object_id"))
    data = {"type": "chooseBlockers",
            "attackers": [{"attackerId": a, "validBlockerIds": mine, "minBlockers": 0, "mustBeBlocked": False}
                          for a in attacking], "availableBlockerIds": mine}

    def answer(output: Mapping[str, Any]) -> tuple[str, Any]:
        blocks = {a.get("blockerId"): a.get("attackerId") for a in output.get("assignments") or []}
        return "plan", {"kind": "block", "blocks": {b: blocks.get(b) for b in mine}}

    return data, answer


def build(pending: Mapping[str, Any], observation: Mapping[str, Any], seats: Seats) -> tuple[dict, Answer]:
    kinds = {c.get("kind") for c in pending.get("candidates") or []}
    context = pending.get("context") or {}
    if context.get("kind") == "priority" and kinds <= PRIORITY_KINDS:
        return choose_action(pending, seats)
    if kinds == {"mulligan"}:
        built = mulligan(pending, observation, seats)
        if built is not None:
            return built
    if pending.get("screen") == "bottom":
        built = put_back(pending, observation, seats)
        if built is not None:
            return built
    if pending.get("screen") == "attack":
        return attackers(pending, observation, seats)
    if pending.get("screen") == "block":
        return blockers(pending, observation, seats)
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
