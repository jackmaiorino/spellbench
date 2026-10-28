"""Human-readable text for candidates, prompts and public history events (spec 6, 7 and x_public_history_v1)."""

from __future__ import annotations

from typing import Any, Iterator, Mapping

PHASES = {
    "pregame": "Pregame", "untap": "Untap", "upkeep": "Upkeep", "draw": "Draw",
    "precombat_main": "Main 1", "beginning_of_combat": "Begin combat", "declare_attackers": "Attackers",
    "declare_blockers": "Blockers", "combat_damage": "Damage", "end_of_combat": "End combat",
    "postcombat_main": "Main 2", "end_step": "End step", "cleanup": "Cleanup",
}


def seat_name(seat: Any, me: str | None) -> str:
    if seat is None:
        return "?"
    return "You" if seat == me else "Opp"


def card(ref: Any, me: str | None = None, *, whose: bool = False) -> str:
    """An object reference as its card name, optionally marked with its controller."""
    if not isinstance(ref, Mapping):
        return "(gone)"
    name = ref.get("card_name") or "a hidden card"
    if whose and me is not None and ref.get("zone") in ("battlefield", "stack"):
        return f"{name} ({'yours' if ref.get('controller_seat') == me else 'opp'})"
    return name


def target(ref: Any, me: str | None) -> str:
    if not isinstance(ref, Mapping):
        return "(gone)"
    if "player" in ref:
        return "you" if ref["player"] == me else "opponent"
    obj = ref.get("object")
    text = card(obj, me, whose=True)
    zone = obj.get("zone") if isinstance(obj, Mapping) else None
    if zone and zone not in ("battlefield", "stack"):
        text += f" in {'your' if obj.get('owner_seat') == me else 'opp'} {zone}"
    return text


def refs(value: Any) -> Iterator[str]:
    """Every object id a semantic mentions, for highlighting cards on the board."""
    if isinstance(value, Mapping):
        object_id = value.get("object_id")
        if isinstance(object_id, str):
            yield object_id
        for key, item in value.items():
            if key != "object_id":
                yield from refs(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from refs(item)


def candidate(semantic: Mapping[str, Any], me: str | None) -> str:
    """One candidate as a short imperative phrase."""
    kind = semantic.get("kind")
    s = semantic
    if kind == "pass":
        return "Pass"
    if kind == "play_land":
        return f"Play {card(s.get('source'))}" + (" (back face)" if s.get("face") else "")
    if kind == "cast_spell":
        method = s.get("method")
        return f"Cast {card(s.get('source'))}" + (f" ({method})" if method not in (None, "normal") else "")
    if kind == "activate_mana_ability":
        mana = s.get("mana_choice")
        return f"Tap {card(s.get('source'))} for mana" + (f" ({mana})" if mana else "")
    if kind == "activate_ability":
        return f"Activate {card(s.get('source'), me, whose=True)}" + (
            f" (ability {s['ability_index'] + 1})" if s.get("ability_index") else "")
    if kind == "special_action":
        return f"{str(s.get('action', '')).replace('_', ' ').capitalize()} {card(s.get('source'))}"
    if kind == "choose_target":
        return f"Target {target(s.get('target'), me)}"
    if kind == "finish_target_selection":
        return "Done choosing targets"
    if kind == "choose_cost_target":
        return f"{str(s.get('cost_kind', '')).replace('_', ' ').capitalize()} {card(s.get('candidate'), me, whose=True)}"
    if kind in ("choose_cast_method",):
        return f"Cast as {s.get('method')}"
    if kind == "choose_spell_mode":
        return f"Mode {s.get('mode_index', 0) + 1} of {s.get('mode_count')}"
    if kind == "choose_option":
        return s.get("option_label") or f"Option {s.get('option_index', 0) + 1} of {s.get('option_count')}"
    if kind == "choose_color":
        return str(s.get("color", "")).capitalize()
    if kind == "choose_number":
        return str(s.get("value"))
    if kind == "choose_boolean":
        return "Yes" if s.get("value") else "No"
    if kind == "choose_name":
        return str(s.get("value"))
    if kind == "select_object":
        return f"{str(s.get('purpose', '')).replace('_', ' ').capitalize()}: {target(s.get('choice'), me)}"
    if kind == "finish_selection":
        return "Done selecting"
    if kind == "optional_cost":
        return f"{'Pay' if s.get('pay') else 'Do not pay'} {str(s.get('cost', '')).replace('_', ' ')}"
    if kind == "choose_cost_option":
        return str(s.get("choice", "")).replace("_", " ").capitalize()
    if kind == "optional_cast":
        return f"{'Cast' if s.get('cast_it') else 'Do not cast'} {card(s.get('card'))} ({s.get('method')})"
    if kind == "mulligan":
        return "Keep" if s.get("keep") else f"Mulligan (hand of {s.get('hand_size')})"
    if kind == "order_pick":
        item = s.get("item") or {}
        name = card(item["object"]) if "object" in item else (
            (item.get("trigger") or {}).get("label") or (item.get("trigger") or {}).get("source_name") or "trigger")
        return f"{name} at position {s.get('position', 0) + 1} of {s.get('count')}"
    if kind == "arrange_card":
        return f"{card(s.get('card'))} to {str(s.get('destination', '')).replace('_', ' ')}"
    if kind == "choose_replacement":
        return f"Apply {card(s.get('replacement_source'))} first"
    if kind == "choose_starting_player":
        return "Play first" if s.get("player") == me else "Draw first (opponent plays)"
    if kind == "declare_attack":
        defender = s.get("defender")
        if defender is None:
            return f"{card(s.get('attacker'))}: no attack"
        return f"{card(s.get('attacker'))} attacks {target(defender, me)}"
    if kind == "declare_block":
        if s.get("attacker") is None:
            return f"{card(s.get('blocker'))}: no block"
        return f"{card(s.get('blocker'))} blocks {card(s.get('attacker'))}"
    if kind == "distribute":
        return f"{s.get('amount')} to {target(s.get('recipient'), me)} ({s.get('remaining')} left)"
    if kind == "choose_pile":
        piles = s.get("piles") or [[], []]
        chosen = piles[s.get("pile_index", 0)] if len(piles) == 2 else []
        return f"Pile {s.get('pile_index', 0) + 1}: " + (", ".join(card(c) for c in chosen) or "empty")
    return str(kind)


def prompt(decision: Mapping[str, Any], me: str | None) -> str:
    """What the engine is asking, in one line."""
    context = decision.get("context") or {}
    candidates = decision.get("candidates") or []
    group = decision.get("group") or {}
    observation = decision.get("observation") or {}
    if context.get("text"):
        return str(context["text"])
    kinds = {c.get("semantic", {}).get("kind") for c in candidates}
    source = context.get("source")
    of = f" for {card(source)}" if isinstance(source, Mapping) else ""
    step = ""
    if (group.get("substep_count") or 1) > 1:
        step = f" ({group.get('substep_index', 0) + 1} of {group.get('substep_count')})"
    if context.get("kind") == "priority":
        stack = observation.get("stack") or []
        if stack:
            top = stack[-1]
            who = seat_name(top.get("controller_seat"), me)
            return f"{who}: {card(top)} on the stack. Respond?"
        return f"Your priority ({PHASES.get(observation.get('phase_step'), observation.get('phase_step'))})"
    purpose = context.get("purpose")
    label = {
        "choose_target": "Choose a target", "declare_attack": "Declare attackers",
        "declare_block": "Declare blockers", "mulligan": "Keep or mulligan?",
        "choose_starting_player": "Play or draw?", "arrange_card": "Arrange", "order_pick": "Order",
        "select_object": "Select", "choose_boolean": "Choose", "optional_cost": "Pay the cost?",
        "choose_spell_mode": "Choose a mode", "choose_number": "Choose a number",
        "choose_cost_target": "Pay the cost", "distribute": "Distribute",
    }
    for kind in kinds:
        if kind in label:
            text = label[kind]
            break
    else:
        text = "Choose"
    if purpose:
        text += f" ({str(purpose).replace('_', ' ')})"
    return text + of + step


def history(events: list[Any], me: str | None) -> Iterator[tuple[str, str]]:
    """``(side, text)`` lines for x_public_history_v1 events; side is ``you``, ``opp`` or ``game``."""
    for event in events:
        if not isinstance(event, Mapping):
            continue
        kind = event.get("kind")
        if kind == "turn_began":
            yield "game", f"Turn {event.get('turn')}: {'your' if event.get('active_seat') == me else 'opponent'} turn"
        elif kind == "draw":
            seat = event.get("seat")
            side = "you" if seat == me else "opp"
            if seat == me:
                yield side, f"You draw {card(event.get('card'))}"
            else:
                yield side, "Opp draws a card"
        elif kind == "zone_move":
            line = _move(event, me)
            if line is not None:
                yield line
        elif kind == "token_created":
            seat = event.get("controller_seat")
            yield ("you" if seat == me else "opp"), f"{seat_name(seat, me)} creates a {card(event.get('card'))} token"
        elif kind == "library_shuffled":
            yield "game", f"{seat_name(event.get('owner_seat'), me)} shuffles"
        elif kind == "library_rearranged":
            seat = event.get("owner_seat")
            yield ("you" if seat == me else "opp"), (
                f"{seat_name(seat, me)} rearranges library ({event.get('top_count')} top, "
                f"{event.get('bottom_count')} bottom)")
        elif kind == "looked_at":
            names = ", ".join(card(entry.get("card")) for entry in event.get("cards") or [])
            yield "you", f"You look at: {names}"
        elif kind == "card_revealed":
            seat = event.get("owner_seat")
            yield ("you" if seat == me else "opp"), f"{seat_name(seat, me)} reveals {card(event.get('card'))}"


def _move(event: Mapping[str, Any], me: str | None) -> tuple[str, str] | None:
    seat = event.get("owner_seat")
    who = seat_name(seat, me)
    side = "you" if seat == me else "opp"
    name = card(event.get("card"))
    source = (event.get("from") or {}).get("zone")
    to = (event.get("to") or {}).get("zone")
    verbs = {
        ("hand", "stack"): f"{who} casts {name}",
        ("hand", "battlefield"): f"{who} plays {name}",
        ("stack", "battlefield"): f"{name} resolves ({who.lower() if who == 'Opp' else 'yours'})",
        ("stack", "graveyard"): f"{name} resolves or is countered",
        ("battlefield", "graveyard"): f"{name} ({'yours' if seat == me else 'opp'}) goes to the graveyard",
        ("battlefield", "hand"): f"{name} returns to {'your' if seat == me else 'opp'} hand",
        ("battlefield", "exile"): f"{name} ({'yours' if seat == me else 'opp'}) is exiled",
        ("battlefield", "library"): f"{name} goes to {'your' if seat == me else 'opp'} library",
        ("hand", "graveyard"): f"{who} discards {name}",
        ("hand", "exile"): f"{who} exiles {name} from hand",
        ("hand", "library"): f"{who} puts {name} into library",
        ("library", "graveyard"): f"{name} milled from {'your' if seat == me else 'opp'} library",
        ("library", "hand"): f"{who} puts {name} into hand",
        ("library", "battlefield"): f"{name} enters from {'your' if seat == me else 'opp'} library",
        ("library", "exile"): f"{name} exiled from {'your' if seat == me else 'opp'} library",
        ("graveyard", "hand"): f"{who} returns {name} to hand",
        ("graveyard", "battlefield"): f"{name} returns to the battlefield",
        ("graveyard", "stack"): f"{who} casts {name} from the graveyard",
        ("graveyard", "exile"): f"{name} exiled from {'your' if seat == me else 'opp'} graveyard",
        ("exile", "battlefield"): f"{name} returns from exile",
        ("exile", "stack"): f"{who} casts {name} from exile",
        ("exile", "hand"): f"{name} returns from exile to hand",
        ("stack", "exile"): f"{name} is exiled from the stack",
        ("stack", "hand"): f"{name} returns to hand from the stack",
    }
    text = verbs.get((source, to))
    if text is None:
        if source == to:
            return None
        text = f"{name}: {source} to {to}"
    return side, text
