"""Human-readable text for candidates, prompts and public history events (spec 6, 7 and x_public_history_v1)."""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping

PHASES = {
    "pregame": "Pregame", "untap": "Untap", "upkeep": "Upkeep", "draw": "Draw",
    "precombat_main": "Main 1", "beginning_of_combat": "Begin combat", "declare_attackers": "Attackers",
    "declare_blockers": "Blockers", "combat_damage": "Damage", "end_of_combat": "End combat",
    "postcombat_main": "Main 2", "end_step": "End step", "cleanup": "Cleanup",
}
# The step in a sentence ("your declare attackers step").
STEP_NAMES = {
    "pregame": "pregame", "untap": "untap step", "upkeep": "upkeep", "draw": "draw step", "precombat_main": "first main phase",
    "beginning_of_combat": "beginning of combat", "declare_attackers": "declare attackers step",
    "declare_blockers": "declare blockers step", "combat_damage": "combat damage step", "end_of_combat": "end of combat",
    "postcombat_main": "second main phase", "end_step": "end step", "cleanup": "cleanup step",
}
MAIN_STEPS = ("precombat_main", "postcombat_main")


def where(observation: Mapping[str, Any], me: str | None) -> str:
    """Where the game is, for "why do I have priority": whose turn and which step ("the opponent's declare blockers
    step")."""
    step = observation.get("phase_step")
    owner = "your" if observation.get("active_seat") == me else "the opponent's"
    return f"{owner} {STEP_NAMES.get(step, str(step).replace('_', ' '))}"


ABILITY_KINDS = ("activated_ability", "triggered_ability")

# The engine's observation lists the stack TOP FIRST: index 0 resolves next and a new object appears at index 0
# (the kernel adapter reverses its native bottom-first order, integrations/mtg_kernel/kernel_observation_v2.py,
# "native bottom-first; protocol top-first"; recorded games: every pop and push seen between two decisions was at
# index 0). The spec text (Section 6.2) says the opposite and the xmage engine follows it, so this is the one place
# that knows the order: every reader of the stack end goes through ``stack_top`` or ``stack_bottom_first``.
STACK_TOP_FIRST = True


def stack_top(stack: Any) -> Mapping[str, Any] | None:
    """The stack object that resolves next, or ``None`` when the stack is empty."""
    if not stack:
        return None
    return stack[0] if STACK_TOP_FIRST else stack[-1]


def stack_bottom_first(stack: Any) -> list[Any]:
    """The stack from the bottom up (the last entry is the top), the order the Manabrew client draws."""
    entries = list(stack or [])
    return entries[::-1] if STACK_TOP_FIRST else entries


_CARD_TEXT: dict[str, str] | None = None


def _rules_text(name: str | None) -> str:
    """Rules text of a Pauper-pool card (the adapter's own data file), or an empty string."""
    global _CARD_TEXT
    if _CARD_TEXT is None:
        try:
            import json
            from pathlib import Path
            data = json.loads(Path(__file__).with_name("manabrew").joinpath("cards.json").read_text(encoding="utf-8"))
            _CARD_TEXT = {k: str(v.get("text") or "") for k, v in data.items()}
        except (OSError, ValueError):
            _CARD_TEXT = {}
    return _CARD_TEXT.get(name or "", "")


def mode_label(semantic: Mapping[str, Any]) -> str:
    """What a mode of a modal spell does: its bullet from the card's rules text (modes are in Oracle order), or for a
    bestow card (two modes) the two ways to cast it. Falls back to the mode's number."""
    index, count = int(semantic.get("mode_index", 0)), semantic.get("mode_count")
    name = (semantic.get("source") or {}).get("card_name") if isinstance(semantic.get("source"), Mapping) else None
    rules = _rules_text(name)
    bullets = [line[1:].strip() for line in rules.splitlines() if line.startswith("*")]
    if len(bullets) == count and index < len(bullets):
        return f"Mode {index + 1}: {bullets[index]}"
    if count == 2 and rules.startswith("Bestow"):
        return ["Cast it as a creature", "Cast it with bestow (an Aura on a target creature)"][min(index, 1)]
    return f"Mode {index + 1} of {count}"


# Keyword abilities that are activated from a card's own zone (reminder text in parentheses follows the cost).
_HAND_ACTIVATION = re.compile(r"(?i)^((commander )?ninjutsu|[a-z]*cycling|channel|transmute|bloodrush)\b")
_BOARD_KEYWORD_ACTIVATION = re.compile(r"(?i)^(equip|crew|outlast|level up|reconfigure|fortify|unearth)\b")
_TRIGGER_LINE = re.compile(r"(?i)^(when|whenever|at)\b")


def ability_rules(semantic: Mapping[str, Any]) -> str:
    """The line of the source card's rules text that an activate_ability candidate runs, when that is certain: the
    card's only activated ability for the zone it is activated from (a colon outside reminder text on the board, a
    ninjutsu or cycling line in hand). Several lines give "" (the engine's ability_index does not say which)."""
    source = semantic.get("source") if isinstance(semantic.get("source"), Mapping) else {}
    lines = [line.strip() for line in _rules_text(source.get("card_name")).split("\n") if line.strip()]
    if source.get("zone") in ("battlefield", "stack"):
        picks = [line for line in lines if _board_activation(line)]
    else:
        picks = [line for line in lines if _HAND_ACTIVATION.match(line)]
    return picks[0] if len(picks) == 1 else ""


def _board_activation(line: str) -> bool:
    bare = re.sub(r"\([^)]*\)", "", line).strip()
    if _TRIGGER_LINE.match(bare):
        return False
    cost, colon, effect = bare.partition(":")
    if colon and effect.strip().lower().startswith("add "):  # a mana ability is offered as its own candidate
        return False
    return bool(colon) or bool(_BOARD_KEYWORD_ACTIVATION.match(bare))


def seat_name(seat: Any, me: str | None) -> str:
    if seat is None:
        return "?"
    return "You" if seat == me else "Opp"


def card(ref: Any, me: str | None = None, *, whose: bool = False) -> str:
    """An object reference as its card name, optionally marked with its controller."""
    if not isinstance(ref, Mapping):
        return "(gone)"
    name = ref.get("card_name")
    if not name:  # the pauper-kernel-v2 observation leaves some ability names out (spellbench issue 259)
        name = "an unnamed card's ability" if ref.get("stack_kind") in ABILITY_KINDS else "a hidden card"
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


def stack_targets(entry: Any, me: str | None) -> str:
    """A stack object's chosen targets as text ("Drossforge Bridge (opp), you"), or "" when it has none."""
    if not isinstance(entry, Mapping):
        return ""
    return ", ".join(target(ref, me) for ref in entry.get("targets") or [])


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


COST_OPTIONS = {"discard": "Discard a card", "sacrifice_land": "Sacrifice a land"}
_MANA = r"((?:\{[^}]+\})+)"


def optional_cost_phrase(semantic: Mapping[str, Any]) -> str:
    """What an optional_cost candidate pays, from the source card's rules text where it says so ("{B}", "the kicker
    cost ({R})"), else the cost's kind and the card ("the optional cost of Nihil Spellbomb")."""
    kind = str(semantic.get("cost"))
    source = semantic.get("source") if isinstance(semantic.get("source"), Mapping) else {}
    name = source.get("card_name")
    rules = _rules_text(name)
    found = None
    if kind == "kicker":
        found = re.search(r"Kicker " + _MANA, rules)
        found = f"the kicker cost ({found.group(1)})" if found else None
    elif kind == "unless_payment":
        found = re.search(r"unless [^.]*? pays " + _MANA, rules)
        found = found.group(1) if found else None
    elif kind in ("copy", "other"):
        found = re.search(r"may pay " + _MANA, rules)
        found = found.group(1) if found else None
        if found and kind == "copy":
            found += " to copy the spell"
    elif kind == "additional":
        found = re.search(r"(?i)you may ([^.]*?)\. If you do", rules)
        found = f"the additional cost ({found.group(1)})" if found else None
    if found:
        return found
    return f"the {kind.replace('_', ' ')} cost" + (f" of {name}" if name else "")


ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth")


def trigger_rank(semantic: Mapping[str, Any]) -> str:
    """When the trigger an order_pick offers resolves ("first", "second", "last"). The engine's position is the order
    triggers are put on the stack (mtg-kernel Action::OrderTriggers: "last index resolves first"), so position 0
    resolves last. "" when the position and count are not usable."""
    count, position = semantic.get("count"), semantic.get("position")
    if not (isinstance(count, int) and isinstance(position, int) and count > 1 and 0 <= position < count):
        return ""
    rank = count - position
    if rank == count:
        return "last"
    return ORDINALS[rank - 1] if rank <= len(ORDINALS) else f"number {rank}"


def candidate(semantic: Mapping[str, Any], me: str | None, lands: frozenset[str] | None = None) -> str:
    """One candidate as a short imperative phrase. ``lands`` (object ids) tells tapped lands from costed mana sources."""
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
        verb = "Tap" if lands is None or (s.get("source") or {}).get("object_id") in lands else "Activate"
        paid = s.get("cost_target")  # the object this activation's cost uses up (Saruli Caretaker: another creature)
        return (f"{verb} {card(s.get('source'))} for mana" + (f" ({mana})" if mana else "")
                + (f" (cost: {target(paid, me)})" if paid else ""))
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
        return mode_label(s)
    if kind == "choose_option":
        return s.get("option_label") or f"Option {s.get('option_index', 0) + 1} of {s.get('option_count')}"
    if kind == "choose_color":
        return str(s.get("color", "")).capitalize()
    if kind == "choose_number":
        return f"X = {s.get('value')}" if s.get("purpose") == "x_value" else str(s.get("value"))
    if kind == "choose_boolean":
        return "Yes" if s.get("value") else "No"
    if kind == "choose_name":
        return str(s.get("value"))
    if kind == "select_object":
        return f"{str(s.get('purpose', '')).replace('_', ' ').capitalize()}: {target(s.get('choice'), me)}"
    if kind == "finish_selection":
        return "Done selecting"
    if kind == "optional_cost":
        return f"{'Pay' if s.get('pay') else 'Do not pay'} {optional_cost_phrase(s)}"
    if kind == "choose_cost_option":
        return COST_OPTIONS.get(str(s.get("choice")), str(s.get("choice", "")).replace("_", " ").capitalize())
    if kind == "optional_cast":
        return f"{'Cast' if s.get('cast_it') else 'Do not cast'} {card(s.get('card'))} ({s.get('method')})"
    if kind == "mulligan":
        return "Keep" if s.get("keep") else f"Mulligan (hand of {s.get('hand_size')})"
    if kind == "order_pick" and s.get("purpose") == "mulligan_bottom":
        return f"Bottom {card((s.get('item') or {}).get('object'))}"
    if kind == "order_pick":
        item = s.get("item") or {}
        name = card(item["object"]) if "object" in item else (
            (item.get("trigger") or {}).get("label") or (item.get("trigger") or {}).get("source_name") or "trigger")
        if s.get("purpose") == "triggers" and trigger_rank(s):
            return f"{name}: resolves {trigger_rank(s)}"
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


# Sources whose two-way effect option is an explore of a nonland top card (mtg-kernel ExploreNonlandTop): option 0
# leaves the revealed card on top, option 1 puts it into the graveyard. The protocol's choose_option carries only the
# source and the option number (the kernel adapter sets option_label to null), so the page derives the labels here.
EXPLORE_SOURCES = frozenset({"Map Token"})

# Effect options of the pool's cards whose program order is known (a prompt line and a label per option index):
# mtg-kernel tests/winding_way.rs (option 0 Creature, option 1 Land) and src/trigger.rs (Ninja of the Deep Hours and
# Moon-Circuit Hacker: option 0 does nothing, option 1 draws; a recorded Ninja game took option 1 and its hand grew).
EFFECT_OPTION_LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Winding Way": ("choose a card type (the top four cards of your library are revealed; that type goes to your "
                    "hand, the rest to your graveyard)", ("Creature", "Land")),
    "Ninja of the Deep Hours": ("draw a card?", ("Do not draw", "Draw a card")),
    "Moon-Circuit Hacker": ("draw a card? (then discard a card unless it entered this turn)",
                            ("Do not draw", "Draw a card")),
}


def _known_top(observation: Mapping[str, Any], me: str | None) -> str | None:
    for entry in observation.get("known") or []:
        if (isinstance(entry, Mapping) and entry.get("zone") == "library" and entry.get("owner_seat") == me
                and entry.get("position_from_top") == 0 and entry.get("card_name")):
            return str(entry["card_name"])
    return None


def effect_options(decision: Mapping[str, Any], me: str | None) -> tuple[str, dict[int, str]] | None:
    """For a choose_option decision: a prompt line and a label per candidate id, or None for other decisions.

    An explore names the revealed card ("Leave it on top of your library" / "Put it into your graveyard"); any other
    effect option names its source and its position, since the protocol does not say what each option does."""
    candidates = [c for c in decision.get("candidates") or [] if isinstance(c, Mapping)]
    semantics = [c.get("semantic") or {} for c in candidates]
    if not semantics or any(s.get("kind") != "choose_option" for s in semantics):
        return None
    source = (decision.get("context") or {}).get("source") or semantics[0].get("source")
    name = card(source) if isinstance(source, Mapping) else "the effect"
    count = semantics[0].get("option_count")
    top = _known_top(decision.get("observation") or {}, me)
    if name in EXPLORE_SOURCES and count == 2:
        seen = top or "the card"
        words = {0: f"Leave {seen} on top of your library", 1: f"Put {seen} into your graveyard"}
        return (f"Explore ({name}) revealed {seen}",
                {c["candidate_id"]: s.get("option_label") or words.get(s.get("option_index"), "?")
                 for c, s in zip(candidates, semantics)})
    known = EFFECT_OPTION_LABELS.get(name)
    if known is not None and len(known[1]) == count:
        return (f"{name}: {known[0]}",
                {c["candidate_id"]: s.get("option_label") or known[1][min(int(s.get("option_index", 0)), count - 1)]
                 for c, s in zip(candidates, semantics)})
    note = f"; your library's top card is {top}" if top else ""
    return (f"{name}: choose one of {count} effects (the engine does not describe them{note})",
            {c["candidate_id"]: s.get("option_label") or f"{name}: effect {s.get('option_index', 0) + 1} of {count}"
             for c, s in zip(candidates, semantics)})


# What a typed choice is asking, by (kind, purpose); the protocol's purpose vocabularies name the reason.
PURPOSE_TITLES = {
    ("choose_boolean", "may_ability"): "Use the optional ability? (Yes or No)",
    ("choose_boolean", "optional_trigger"): "Use the optional trigger? (Yes or No)",
    ("choose_boolean", "may_cast"): "Cast it? (Yes or No)",
    ("choose_boolean", "reveal"): "Reveal it? (Yes or No)",
    ("choose_number", "x_value"): "Choose the value of X",
    ("choose_number", "cost_repetitions"): "How many times to pay the optional cost?",
    ("choose_number", "life_payment"): "How much life to pay?",
    ("choose_number", "amount"): "Choose an amount",
    ("choose_color", "mana"): "Choose a color of mana",
    ("choose_color", "protection"): "Choose a color to protect from",
    ("choose_color", "effect"): "Choose a color",
    ("order_pick", "mulligan_bottom"): "Put a card on the bottom of your library",
}


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
            top = stack_top(stack)
            who = seat_name(top.get("controller_seat"), me)
            return f"{who}: {card(top)} on the stack. Respond?"
        if observation.get("phase_step") in MAIN_STEPS and observation.get("active_seat") == me:
            return f"Your priority ({PHASES.get(observation.get('phase_step'), observation.get('phase_step'))})"
        return f"Your priority in {where(observation, me)}"
    if kinds == {"order_pick"}:
        first = candidates[0].get("semantic") or {}
        if first.get("purpose") == "triggers" and trigger_rank(first):
            return f"Order your triggers: choose the one that resolves {trigger_rank(first)}" + step
    purpose = context.get("purpose")
    for kind in kinds:
        titled = PURPOSE_TITLES.get((kind, purpose))
        if titled:
            return titled + of + step
    label = {
        "choose_target": "Choose a target", "declare_attack": "Declare attackers",
        "declare_block": "Declare blockers", "mulligan": "Keep or mulligan?",
        "choose_starting_player": "Play or draw?", "arrange_card": "Arrange", "order_pick": "Order",
        "select_object": "Select", "choose_boolean": "Choose", "optional_cost": "Pay the cost?",
        "choose_cost_option": "Choose how to pay the cost",
        "choose_spell_mode": "Choose a mode", "choose_number": "Choose a number",
        "choose_cost_target": "Pay the cost", "distribute": "Distribute", "choose_color": "Choose a color",
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
