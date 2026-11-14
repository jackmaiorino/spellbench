"""A causal play log for the human seat, from the engine's own committed events (display only).

The kernel engine attaches ``x_kernel_infoset_v1`` to most decisions: the engine state as the acting seat may know
it, including ``engine.event_history`` (every committed event: casts, taps, mana, sacrifices, damage, life, zone
changes, tokens, counters) and the stack items with their sources, targets, paid costs and effects. The session's
operator engine record (``engine-records/hot/<game>/engine.jsonl``) holds those decisions for both seats as they
happen. ``Narrator`` reads them in order and turns the events into log lines that say what happened and why
("Opp sacrifices Eldrazi Spawn Token for {C}", "Krark-Clan Shaman deals 1 damage to ...", "Eldrazi Spawn Token
(opp) dies (lethal damage)").

Hidden information. A snapshot taken from the bot's decision knows the bot's hand, so names come from a snapshot
only for objects in public zones (battlefield, graveyard, stack, face-up exile) and for spells as they are cast
(public identity). Draws and every move into a hand or library are narrated from the human seat's own
``x_public_history_v1`` (the adapter names exactly what that seat may see), aligned to the engine events by kind
and order. The bot's step selections are never shown; only their public results are.

Each line carries ``facts``: what it accounts for, for the replay check (``spellbench.human.replay``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import text

PUBLIC_ZONES = frozenset({"Battlefield", "Graveyard", "Stack", "Exile"})
HIDDEN_ZONES = frozenset({"Hand", "Library"})
ZONE_WORD = {"Battlefield": "battlefield", "Graveyard": "graveyard", "Stack": "stack", "Exile": "exile",
             "Hand": "hand", "Library": "library", "Command": "command"}
COLOR_ORDER = "WUBRGC"
# Spells whose resolution destroys its target (the pool's destroy effects), for "is destroyed" over "dies".
DESTROY_SPELLS = frozenset({"Cast Down", "Cleansing Wildfire", "Thraben Charm"})
# Short text for activated abilities whose stack item carries no inline effect (keyed by source name and index).
ABILITY_TEXT = {
    ("Krark-Clan Shaman", 0): "1 damage to each creature without flying",
    ("Makeshift Munitions", 0): "1 damage to any target",
    ("Nihil Spellbomb", 0): "exile target player's graveyard",
    ("Nihil Spellbomb", 1): "draw a card",
    ("Blood Fountain", 0): "return up to two creature cards from your graveyard to your hand",
    ("Map Token", 0): "target creature you control explores",
    ("Experimental Synthesizer", 0): "create a 2/2 Samurai with vigilance",
    ("Cryogen Relic", 0): "put a stun counter on up to one target tapped creature",
    ("Lembas", 0): "gain 3 life",
    ("Harrier Strix", 0): "draw a card, then discard a card",
    ("Timberwatch Elf", 0): "target creature gets +X/+X until end of turn (X = number of Elves)",
    ("Quirion Ranger", 0): "return a Forest you control to its owner's hand: untap target creature",
    ("Wellwisher", 0): "gain 1 life for each Elf on the battlefield",
    ("Tinder Wall", 0): "2 damage to target creature it blocks",
    ("Masked Meower", 0): "draw a card, then discard a card",
    ("Basilisk Gate", 0): "target creature gets +X/+0 (X = number of Gates you control)",
    ("Heap Gate", 0): "create a Treasure token",
    ("Twisted Landscape", 0): "search for a basic Swamp, Mountain or Forest, put it onto the battlefield tapped",
    ("Black Mage's Rod", 0): "equip",
    ("Hunter's Blowgun", 0): "equip",
    ("Toxin Analysis", 0): "investigate",
}


def seat_word(seat: str | None, me: str | None) -> str:
    return "You" if seat == me else "Opp"


def whose(seat: str | None, me: str | None) -> str:
    return "yours" if seat == me else "opp"


def mana_text(colors: list[str]) -> str:
    ordered = sorted(colors, key=lambda c: COLOR_ORDER.index(c) if c in COLOR_ORDER else 9)
    return "".join(f"{{{c}}}" for c in ordered)


def humanize(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i:
            out.append(" ")
        out.append(ch.lower())
    return "".join(out)


class Snapshot:
    """One engine state from a decision's infoset, with names restricted to what the human seat may know."""

    def __init__(self, payload: Mapping[str, Any], acting_seat: str, me: str, native_me: int) -> None:
        self.state = payload["state"]
        self.viewer_is_me = acting_seat == me
        self.me = me
        self.native_me = native_me
        self.objects: list[Any] = self.state["objects"]["items"]
        self.events: list[Any] = self.state["engine"]["event_history"]
        self.stack: list[Any] = self.state.get("stack") or []
        self.card_defs = {o["card_def"]: o["name"] for o in self.objects if isinstance(o, Mapping)
                          and o.get("zone") in PUBLIC_ZONES}

    def seat(self, native: Any) -> str | None:
        if native is None:
            return None
        other = "p1" if self.me == "p0" else "p0"
        return self.me if native == self.native_me else other

    def obj(self, index: Any) -> Mapping[str, Any] | None:
        if isinstance(index, int) and 0 <= index < len(self.objects) and isinstance(self.objects[index], Mapping):
            return self.objects[index]
        return None

    def name(self, index: Any, *, allow_command: bool = False) -> str | None:
        """The object's name if the human seat may know it: public zones always; the last-known copy the engine
        keeps for a public object (zone "Command") only where the caller knows the object was public."""
        o = self.obj(index)
        if o is None:
            return None
        zone = o.get("zone")
        if zone in PUBLIC_ZONES and not o.get("face_down"):
            return o.get("name")
        if zone == "Command" and allow_command:
            return o.get("name")
        if zone == "Hand" and self.viewer_is_me and o.get("owner") == self.native_me:
            return o.get("name")
        return None

    def controller(self, index: Any) -> str | None:
        o = self.obj(index)
        return None if o is None else self.seat(o.get("controller"))

    def owner(self, index: Any) -> str | None:
        o = self.obj(index)
        return None if o is None else self.seat(o.get("owner"))

    def stack_ids(self) -> dict[int, Mapping[str, Any]]:
        return {item["v4"]["stack_item_id"]: item for item in self.stack if isinstance(item, Mapping)
                and isinstance(item.get("v4"), Mapping)}


class Line(dict):
    """One log line: ``side`` (you/opp/game), ``text``, ``depth`` (0 header, 1 effect), ``facts``."""


def describe_effect(effect: Any, snap: Snapshot | None, controller: str | None, me: str | None) -> str:
    """Short text for an inline effect program (the stack item's own description of what it will do)."""
    if effect is None:
        return ""
    if isinstance(effect, str):
        return humanize(effect)
    if not isinstance(effect, Mapping) or len(effect) != 1:
        return ""
    (op, body), = effect.items()
    you = "you" if controller == me else "they"
    if op == "Sequence" and isinstance(body, list):
        parts = [describe_effect(item, snap, controller, me) for item in body]
        merged: list[str] = []
        for part in parts:
            if merged and part == merged[-1].split(" (x")[0]:
                count = int(merged[-1].split(" (x")[1].rstrip(")")) + 1 if " (x" in merged[-1] else 2
                merged[-1] = f"{part} (x{count})"
            elif part:
                merged.append(part)
        return ", then ".join(merged)
    if op == "DrawCards":
        n = body.get("count", 1)
        return f"draw {n} card{'s' if n != 1 else ''}"
    if op == "Scry":
        return f"scry {body.get('count', 1)}"
    if op == "GainLife":
        return f"gain {body.get('amount')} life"
    if op == "CreateToken":
        return "create a token"
    if op == "DamageAllCreatures":
        flt = body.get("filter") or {}
        extra = " without flying" if isinstance(flt, Mapping) and "WithoutKeyword" in flt else ""
        return f"{body.get('amount')} damage to each creature{extra}"
    if op == "ExploreTarget":
        return "target creature explores (reveal the top card: a land goes to hand; otherwise +1/+1 counter and "\
               "the card stays on top or goes to the graveyard)"
    if op == "PutPlusOnePlusOneCounterOnBoundObject":
        return "put a +1/+1 counter on it"
    if op == "ExilePlayersGraveyard":
        return "exile target player's graveyard"
    if op == "Conditional":
        then = describe_effect(body.get("then"), snap, controller, me)
        other = describe_effect(body.get("else_"), snap, controller, me)
        cond = humanize(str(body.get("cond", "")))
        return f"if {cond}: {then}" + (f"; otherwise {other}" if other else "")
    if op == "MayPayManaThen":
        cost = mana_text(body.get("colored") or []) + (f"{{{body['generic']}}}" if body.get("generic") else "")
        return f"{you} may pay {cost} to {describe_effect(body.get('then'), snap, controller, me)}"
    return humanize(op)


class Narrator:
    """Turns the engine record of one game into log lines for the human seat ``me``."""

    def __init__(self, me: str) -> None:
        self.me = me
        self.native_me: int | None = None
        self.offset = 0                      # engine events already narrated
        self.last: Snapshot | None = None    # previous snapshot with a payload
        self.seen_items: dict[int, Mapping[str, Any]] = {}  # stack_item_id -> item, as last seen
        self.announced: set[int] = set()     # stack items already given a cast/activate/trigger line
        self.token_names: dict[int, str] = {}
        self.pending_lines: list[tuple[int, Line]] = []    # (event index, line) not yet merged with history
        self.slots: list[tuple[int, str]] = []  # engine events the public history mirrors, awaiting it
        self.backlog: list[Any] = []            # public history events past the narrated engine events
        self.damaged: dict[tuple[str | None, str], str] = {}
        self.step: tuple[Any, Any, Any] | None = None
        self.resolver_hint: str | None = None

    # -- engine side -----------------------------------------------------------------------------------------

    def engine_decision(self, seat_decision: Mapping[str, Any]) -> None:
        """Feed one engine decision (either seat) in record order."""
        infoset = (seat_decision.get("extensions") or {}).get("x_kernel_infoset_v1") or {}
        raw = infoset.get("payload_json")
        observation = seat_decision.get("observation") or {}
        step = (observation.get("turn"), observation.get("active_seat"), observation.get("phase_step"))
        if isinstance(raw, str):
            self._snapshot(json.loads(raw), seat_decision, observation)
        # A step marker wherever a decision (either seat) shows a new step; it follows that span's events.
        if step != self.step and step[2] is not None:
            name = text.PHASES.get(step[2], step[2])
            whose_turn = "your" if step[1] == self.me else "opp's"
            self.pending_lines.append((self.offset - 0.2, Line(side="game", depth=0, text=f"{name} ({whose_turn} turn)",
                                                              facts=[("step",)], step=True)))
            self.step = step

    def _snapshot(self, payload: Mapping[str, Any], seat_decision: Mapping[str, Any],
                  observation: Mapping[str, Any]) -> None:
        acting = seat_decision.get("acting_seat")
        if self.native_me is None:
            viewer = payload.get("viewer")
            self.native_me = viewer if acting == self.me else 1 - viewer
        snap = Snapshot(payload, acting, self.me, self.native_me)
        events = snap.events
        if len(events) < self.offset:  # never expected: the history only grows
            self.offset = 0
        window = list(enumerate(events[self.offset:], start=self.offset))
        self.offset = len(events)
        self._window(window, snap, observation)
        self.last = snap

    def _window(self, window: list[tuple[int, Any]], snap: Snapshot, observation: Mapping[str, Any]) -> None:
        me = self.me
        before = self.seen_items
        now = snap.stack_ids()
        # A spell is announced by its SpellCast event (an unfinished cast sits on the stack under another id);
        # abilities are announced when first seen.
        new_items = [sid for sid in now if sid not in before and sid not in self.announced
                     and now[sid].get("kind") != "Spell"]
        gone = [sid for sid in before if sid not in now and sid in self.announced]
        cast_at = {}
        for index, ev in window:
            if isinstance(ev, Mapping) and "PublishedCastIdentityV1" in ev:
                sid = (ev["PublishedCastIdentityV1"].get("receipt") or {}).get("stack_item_id")
                cast_at[sid] = index
        out: list[tuple[int, Line]] = []
        start = window[0][0] if window else self.offset
        end = window[-1][0] if window else self.offset

        def add(index: int, line: Line) -> None:
            out.append((index, line))

        # Resolutions: an item that left the stack. Its effects follow in this window.
        resolving: list[Mapping[str, Any]] = [before[sid] for sid in reversed(list(before)) if sid in gone]
        for item in resolving:
            label = self._item_label(item)
            controller = item["_controller"]
            line = Line(side="you" if controller == me else "opp", depth=0,
                        text=f"{label['name']} ({whose(controller, me)}) resolves",
                        facts=[("stack-", controller, label["name"])])
            add(start - 0.5, line)

        # Casts and activations: a new stack item. Costs paid for it are folded into its line.
        cost_events: dict[int, int] = {}  # event index -> stack item id it paid for
        for sid in new_items:
            item = now[sid]
            refs = item["v4"].get("paid_cost_refs") or []
            for ref in refs:
                for index, ev in window:
                    body = ev.get("ZoneChange") if isinstance(ev, Mapping) else None
                    if body and body.get("object") == ref.get("object") and body.get("from") == "Battlefield":
                        cost_events[index] = sid
                        # the Sacrificed event just before it is the same cost
                        prev = index - 1
                        if prev >= start and isinstance(events_at(window, prev), Mapping) and "Sacrificed" in events_at(window, prev):
                            cost_events[prev] = sid

        i = 0
        tap_group: list[tuple[int, str | None, str | None]] = []  # (index, name, controller)
        mana_colors: list[str] = []
        group_seat: str | None = None
        group_at = start

        def flush_mana() -> None:
            nonlocal tap_group, mana_colors, group_seat
            if tap_group or mana_colors:
                names = [n or "a permanent" for _, n, _ in tap_group]
                who = group_seat
                facts: list[tuple] = [("mana", who)]
                facts += [("tap", c, n) for _, n, c in tap_group]
                txt = f"{seat_word(who, me)} tap{'s' if who != me else ''} " + ", ".join(names)
                if mana_colors:
                    txt += f" for {mana_text(mana_colors)}"
                add(group_at, Line(side="you" if who == me else "opp", depth=1, text=txt, facts=facts))
            tap_group, mana_colors, group_seat = [], [], None

        last_cast_receipt: Mapping[str, Any] | None = None
        spell_costs: list[str] = []
        spell_targets: list[str] = []
        self.resolver_hint = None
        while i < len(window):
            index, ev = window[i]
            if not isinstance(ev, Mapping) or len(ev) != 1:
                i += 1
                continue
            (kind, body), = ev.items()
            if kind == "Tap":
                if index in cost_events:
                    i += 1
                    continue
                o = body.get("object")
                c = snap.controller(o)
                nm = snap.name(o, allow_command=True)
                nxt = window[i + 1][1] if i + 1 < len(window) else None
                if isinstance(nxt, Mapping) and "ManaAdded" in nxt:
                    if group_seat not in (None, c):
                        flush_mana()
                    if not tap_group and not mana_colors:
                        group_at = index
                    group_seat = c
                    tap_group.append((index, nm, c))
                    mana_colors += nxt["ManaAdded"].get("colors") or []
                    i += 2
                    continue
                flush_mana()
                if self._tap_for_item(nm, c, new_items, now):
                    i += 1
                    continue
                if self._attacking(observation, nm, c):
                    i += 1
                    continue  # the attack line covers it
                sac = next((j for j in range(i + 1, min(i + 4, len(window)))
                            if isinstance(window[j][1], Mapping) and "Sacrificed" in window[j][1]
                            and snap.name(window[j][1]["Sacrificed"].get("object"), allow_command=True) == nm), None)
                if sac is not None and nm:
                    # an ability that cost "{T}, sacrifice": activated and resolved before any decision saw it
                    zc = window[sac + 1][1].get("ZoneChange") if sac + 1 < len(window) and isinstance(window[sac + 1][1], Mapping) else None
                    if zc is not None:
                        self.slots.append((window[sac + 1][0], "zone_move"))
                    text_ = ABILITY_TEXT.get((nm, 0))
                    add(index, Line(side="you" if c == me else "opp", depth=0,
                                    text=f"{seat_word(c, me)} activate{'s' if c != me else ''} {nm} (tapping and "
                                         f"sacrificing it)" + (f": {text_}" if text_ else ""),
                                    facts=[("tap", c, nm), ("zone", c, nm, "battlefield", "graveyard", "cost")]))
                    self.resolver_hint = nm
                    for j in range(i + 1, sac):  # payment between the tap and the sacrifice stays in the mana line
                        pass
                    window = window[:sac] + window[sac + (2 if zc is not None else 1):]
                    i += 1
                    continue
                add(index, Line(side="you" if c == me else "opp", depth=1,
                                text=f"{nm or 'A permanent'} ({whose(c, me)}) becomes tapped",
                                facts=[("tap", c, nm)]))
                i += 1
                continue
            if kind == "ManaAdded":
                who = snap.seat(body.get("player"))
                if group_seat not in (None, who):
                    flush_mana()
                if not tap_group and not mana_colors:
                    group_at = index
                group_seat = who
                mana_colors += body.get("colors") or []
                i += 1
                continue
            flush_mana()
            if kind == "Sacrificed":
                nxt = window[i + 1][1] if i + 1 < len(window) else None
                zc = nxt.get("ZoneChange") if isinstance(nxt, Mapping) else None
                name = snap.name(body.get("object"), allow_command=True)
                controller = snap.seat(body.get("controller_before"))
                if index in cost_events:
                    i += 1
                    continue
                if zc is not None:
                    self.slots.append((window[i + 1][0], "zone_move"))
                if zc is not None and self._feeds_cast(window, i + 2):
                    spell_costs.append(f"sacrificing {name or 'a permanent'}")
                    i += 2
                    continue
                after = window[i + 2][1] if i + 2 < len(window) else None
                if zc is not None and isinstance(after, Mapping) and "ManaAdded" in after:
                    colors = after["ManaAdded"].get("colors") or []
                    add(index, Line(side="you" if controller == me else "opp", depth=1,
                                    text=f"{seat_word(controller, me)} sacrifice{'s' if controller != me else ''} "
                                         f"{name or 'a permanent'} for {mana_text(colors)}",
                                    facts=[("zone", controller, name, "battlefield", "graveyard", "sacrificed"),
                                           ("mana", controller)]))
                    i += 3
                    continue
                if zc is not None:
                    add(index, Line(side="you" if controller == me else "opp", depth=1,
                                    text=f"{seat_word(controller, me)} sacrifice{'s' if controller != me else ''} "
                                         f"{name or 'a permanent'}",
                                    facts=[("zone", controller, name, "battlefield",
                                            ZONE_WORD.get(zc.get("to"), "graveyard"), "sacrificed")]))
                    i += 2
                    continue
                i += 1
                continue
            if kind == "PublishedCastIdentityV1":
                last_cast_receipt = body.get("receipt") or {}
                i += 1
                continue
            if kind == "Targeted":
                o = body.get("target")
                obj = snap.obj(o)
                if obj is not None and obj.get("zone_change_count") == body.get("target_zone_change_count"):
                    nm = snap.name(o)
                    if nm:
                        spell_targets.append(f"{nm} ({whose(snap.controller(o), me)})")
                i += 1
                continue
            if kind == "SpellCast":
                receipt = last_cast_receipt or {}
                last_cast_receipt = None
                if receipt.get("origin_zone") not in (None, "Stack"):
                    self.slots.append((index, "zone_move"))
                caster = snap.seat(body.get("controller"))
                ident = (receipt.get("public_identity") or {}).get("Known") or {}
                name = snap.card_defs.get(ident.get("card_def")) or snap.name(body.get("spell"), allow_command=True)
                sid = receipt.get("stack_item_id")
                item = now.get(sid) if sid is not None else None
                origin = ZONE_WORD.get(receipt.get("origin_zone"), "hand")
                detail = self._item_detail(item, snap) if item is not None else (
                    f" (targeting {', '.join(spell_targets)})" if spell_targets else "")
                spell_targets = []
                if item is None:
                    self.resolver_hint = name  # cast and resolved before any decision saw it
                costs = f" ({', '.join(spell_costs)})" if spell_costs else ""
                spell_costs = []
                where = "" if origin == "hand" else f" from {'your' if caster == me else 'opp'} {origin}"
                txt = f"{seat_word(caster, me)} cast{'s' if caster != me else ''} {name or 'a spell'}{where}{detail}{costs}"
                if sid is not None:
                    self.announced.add(sid)
                facts = [("zone", snap.seat(receipt.get("owner")), name, origin, "stack", "cast"), ("stack+", caster, name)]
                facts += [("zone", caster, None, "battlefield", "graveyard", "cost") for _ in costs.split(",") if costs]
                add(index, Line(side="you" if caster == me else "opp", depth=0, text=txt, facts=facts))
                i += 1
                continue
            if kind == "ZoneChange":
                self.slots.append((index, "zone_move"))
                if index in cost_events:
                    i += 1
                    continue
                line = self._zone_line(body, snap, resolving)
                if line is not None:
                    add(index, line)
                i += 1
                continue
            if kind == "Draw":
                if body.get("object") is not None:
                    self.slots.append((index, "draw"))
                i += 1
                continue
            if kind == "UpkeepBegan":
                self.slots.append((index, "turn_began"))
                self.damaged.clear()
                i += 1
                continue
            if kind == "Damage":
                j = i
                src = body.get("source")
                src_name = snap.name(src, allow_command=True)
                src_ctl = snap.controller(src)
                hits: list[str] = []
                facts: list[tuple] = []
                while j < len(window) and isinstance(window[j][1], Mapping) and "Damage" in window[j][1] \
                        and snap.name(window[j][1]["Damage"].get("source"), allow_command=True) == src_name:
                    d = window[j][1]["Damage"]
                    tgt = d.get("target") or {}
                    amount = d.get("amount")
                    if "Player" in tgt:
                        who = snap.seat(tgt["Player"])
                        hits.append(f"{amount} to {'you' if who == me else 'Opp'}")
                        facts.append(("life", who))
                    else:
                        o = tgt.get("Object")
                        nm = snap.name(o, allow_command=True) or "a creature"
                        ctl = snap.controller(o)
                        hits.append(f"{amount} to {nm} ({whose(ctl, me)})")
                        facts.append(("damage", ctl, nm))
                        self.damaged[(ctl, nm)] = src_name or "damage"
                    j += 1
                combat = any(isinstance(window[k][1], Mapping) and "CombatDamageToPlayer" in window[k][1]
                             for k in range(i, min(j + 1, len(window))))
                word = "combat damage" if combat or observation.get("phase_step") == "combat_damage" else "damage"
                add(index, Line(side="you" if src_ctl == me else "opp", depth=1,
                                text=f"{src_name or 'A source'} ({whose(src_ctl, me)}) deals {word}: " + ", ".join(hits),
                                facts=facts))
                i = j
                continue
            if kind == "CombatDamageToPlayer":
                i += 1
                continue
            if kind in ("LifeGain", "LifeLoss"):
                who = snap.seat(body.get("player"))
                verb = "gain" if kind == "LifeGain" else "lose"
                add(index, Line(side="you" if who == me else "opp", depth=1,
                                text=f"{seat_word(who, me)} {verb}{'s' if who != me else ''} {body.get('amount')} life",
                                facts=[("life", who)]))
                i += 1
                continue
            if kind == "CreateToken":
                o = body.get("object")
                nm = snap.name(o, allow_command=True) or "a token"
                who = snap.seat(body.get("controller"))
                add(index, Line(side="you" if who == me else "opp", depth=1,
                                text=f"{seat_word(who, me)} create{'s' if who != me else ''} {nm}",
                                facts=[("zone", who, nm, None, "battlefield", "token")]))
                self.slots.append((index, "token_created"))
                i += 1
                continue
            if kind == "PlusOneCountersAdded":
                o = body.get("object")
                nm = snap.name(o, allow_command=True)
                ctl = snap.controller(o)
                n = body.get("count") or body.get("amount") or 1
                add(index, Line(side="you" if ctl == me else "opp", depth=1,
                                text=f"{nm or 'A permanent'} ({whose(ctl, me)}) gets {n} +1/+1 counter{'s' if n != 1 else ''}",
                                facts=[("counters", ctl, nm), ("pt", ctl, nm)]))
                i += 1
                continue
            if kind == "DeclaredAttacker":
                i += 1
                continue
            if kind in ("Transformed", "TurnedFaceUp"):
                o = body.get("object") if isinstance(body, Mapping) else None
                add(index, Line(side="game", depth=1, text=f"{snap.name(o) or 'A permanent'} {humanize(kind)}",
                                facts=[("pt", snap.controller(o), snap.name(o))]))
                i += 1
                continue
            i += 1
        flush_mana()

        # New stack items without a cast line: activated and triggered abilities.
        for sid in new_items:
            if sid in self.announced:
                continue
            item = now[sid]
            label = self._item_label(item, snap)
            controller = label["controller"]
            detail = self._item_detail(item, snap)
            costs = self._paid_costs(item, snap)
            at = min([k for k, v in cost_events.items() if v == sid], default=end + 0.25)
            if item.get("kind") == "ActivatedAbility":
                txt = f"{seat_word(controller, me)} activate{'s' if controller != me else ''} {label['name']}{costs}{detail}"
            elif item.get("kind") == "TriggeredAbility":
                txt = f"{label['name']} ({whose(controller, me)}) triggers{detail}"
            else:
                txt = f"{label['name']} ({whose(controller, me)}) goes on the stack{detail}"
            facts = [("stack+", controller, label["name"])]
            for ref in item["v4"].get("paid_cost_refs") or []:
                nm = snap.name(ref.get("object"), allow_command=True)
                facts.append(("zone", snap.seat(ref.get("controller")), nm, "battlefield",
                              ZONE_WORD.get(ref.get("zone"), "graveyard"), "cost"))
            if item.get("kind") == "ActivatedAbility":
                facts.append(("tap", controller, label["name"]))
            self.announced.add(sid)
            add(at, Line(side="you" if controller == me else "opp", depth=0, text=txt, facts=facts))

        # Remember the stack as last seen (with names resolved while the items were visible).
        seen: dict[int, Mapping[str, Any]] = {}
        for sid, item in now.items():
            entry = dict(item)
            label = self._item_label(item, snap)
            entry["_name"], entry["_controller"] = label["name"], label["controller"]
            seen[sid] = entry
        self.seen_items = seen
        out.sort(key=lambda pair: pair[0])
        self.pending_lines.extend(out)

    # -- helpers -----------------------------------------------------------------------------------------------

    def _item_label(self, item: Mapping[str, Any], snap: Snapshot | None = None) -> dict[str, Any]:
        if "_name" in item:
            return {"name": item["_name"], "controller": item["_controller"]}
        snap = snap or self.last
        name = None
        contract = item["v4"].get("ability_source_contract") or item["v4"].get("source_contract") or {}
        if snap is not None:
            name = snap.card_defs.get(contract.get("card_def")) or snap.name(item.get("source"), allow_command=True)
        controller = snap.seat(item.get("controller")) if snap is not None else None
        return {"name": name or "an ability", "controller": controller}

    def _item_detail(self, item: Mapping[str, Any], snap: Snapshot) -> str:
        parts = []
        label = self._item_label(item, snap)
        targets = []
        for target in item.get("targets") or []:
            if isinstance(target, Mapping) and "Player" in target:
                targets.append("you" if snap.seat(target["Player"]) == self.me else "Opp")
            elif isinstance(target, Mapping) and "Object" in target:
                o = target["Object"]
                nm = snap.name(o)
                targets.append(f"{nm} ({whose(snap.controller(o), self.me)})" if nm else "a card")
        if item.get("kind") != "Spell" and item.get("mode_chosen"):
            parts.append(f"mode {item['mode_chosen'] + 1}")
        x = item["v4"].get("x_value")
        if x:
            parts.append(f"X={x}")
        effect = describe_effect(item.get("inline_effect"), snap, label["controller"], self.me)
        if not effect and item.get("kind") == "ActivatedAbility":
            effect = ABILITY_TEXT.get((label["name"], item["v4"].get("activated_ability_index") or 0), "")
        txt = ""
        if effect:
            txt += f": {effect}"
        if targets:
            txt += f" (targeting {', '.join(targets)})"
        if parts:
            txt += f" [{', '.join(parts)}]"
        return txt

    def _paid_costs(self, item: Mapping[str, Any], snap: Snapshot) -> str:
        names = []
        for ref in item["v4"].get("paid_cost_refs") or []:
            nm = snap.name(ref.get("object"), allow_command=True)
            src = item.get("source")
            if ref.get("object") == src or (nm and nm == self._item_label(item, snap)["name"] and ref.get("zone") == "Graveyard"):
                names.append("sacrificing itself")
            elif ref.get("zone") == "Graveyard":
                names.append(f"sacrificing {nm or 'a permanent'}")
            elif ref.get("zone") == "Exile":
                names.append(f"exiling {nm or 'a card'}")
            else:
                names.append(f"paying with {nm or 'a permanent'}")
        return f" ({', '.join(names)})" if names else ""

    @staticmethod
    def _attacking(observation: Mapping[str, Any], name: str | None, controller: str | None) -> bool:
        for player in observation.get("players") or []:
            for card in player.get("battlefield") or []:
                if (card.get("card_name") == name and card.get("controller_seat") == controller
                        and (card.get("permanent") or {}).get("attacking")):
                    return True
        return False

    @staticmethod
    def _feeds_cast(window: list[tuple[int, Any]], k: int) -> bool:
        """Whether only payment events lie between position ``k`` and a SpellCast (a cost paid for that spell)."""
        while k < len(window):
            ev = window[k][1]
            kind = next(iter(ev)) if isinstance(ev, Mapping) and ev else None
            if kind == "SpellCast":
                return True
            if kind not in ("Tap", "ManaAdded", "Targeted", "PublishedCastIdentityV1"):
                return False
            k += 1
        return False

    def _tap_for_item(self, name: str | None, controller: str | None, new_items: list[int],
                      now: Mapping[int, Mapping[str, Any]]) -> bool:
        return any(self._item_label(now[sid])["name"] == name and self._item_label(now[sid])["controller"] == controller
                   and now[sid].get("kind") == "ActivatedAbility" for sid in new_items)

    def _zone_line(self, body: Mapping[str, Any], snap: Snapshot, resolving: list[Mapping[str, Any]]) -> Line | None:
        me = self.me
        src, dst = body.get("from"), body.get("to")
        o = body.get("object")
        owner = snap.owner(o)
        controller = snap.seat(body.get("controller_before"))
        if dst in HIDDEN_ZONES:
            return None  # named from the seat's public history, aligned in merge()
        name = snap.name(o, allow_command=True)
        if src == "Hand" and dst == "Stack":
            return None  # the cast line covers it
        frm, to = ZONE_WORD.get(src, src), ZONE_WORD.get(dst, dst)
        side = "you" if (controller or owner) == me else "opp"
        mark = f"{name or 'A card'} ({whose(controller or owner, me)})"
        resolver = next((item["_name"] for item in resolving), None) or self.resolver_hint
        if src == "Stack" and dst == "Battlefield":
            return Line(side=side, depth=1, text=f"{name} enters the battlefield",
                        facts=[("zone", owner, name, "stack", "battlefield", "resolved"), ("stack-", controller, name)])
        if src == "Stack" and dst == "Graveyard":
            return Line(side=side, depth=1, text=f"{name} goes to the graveyard",
                        facts=[("zone", owner, name, "stack", "graveyard", "resolved"), ("stack-", controller, name)],
                        quiet=True)
        if src == "Hand" and dst == "Battlefield":
            return Line(side=side, depth=0, text=f"{seat_word(owner, me)} play{'s' if owner != me else ''} {name}",
                        facts=[("zone", owner, name, "hand", "battlefield", "played")])
        if src == "Battlefield" and dst == "Graveyard":
            key = (controller, name)
            if key in self.damaged:
                cause, why = "lethal damage", f"dies (lethal damage from {self.damaged[key]})"
            elif resolver in DESTROY_SPELLS:
                cause, why = "destroyed", f"is destroyed by {resolver}"
            elif resolver:
                cause, why = "effect", f"is put into the graveyard by {resolver}"
            else:
                cause, why = "state", "is put into the graveyard (state-based: 0 toughness or a rule)"
            return Line(side=side, depth=1, text=f"{mark} {why}",
                        facts=[("zone", owner, name, "battlefield", "graveyard", cause)])
        if src == "Hand" and dst == "Graveyard":
            return Line(side=side, depth=1, text=f"{seat_word(owner, me)} discard{'s' if owner != me else ''} {name}",
                        facts=[("zone", owner, name, "hand", "graveyard", "discarded")])
        if src == "Library" and dst == "Graveyard":
            return Line(side=side, depth=1, text=f"{name} is milled from {'your' if owner == me else 'opp'} library",
                        facts=[("zone", owner, name, "library", "graveyard", "milled")])
        if src == "Library" and dst == "Battlefield":
            by = f" by {resolver}" if resolver else ""
            return Line(side=side, depth=1, text=f"{name} is put onto the battlefield from {'your' if owner == me else 'opp'} "
                                                 f"library{by}",
                        facts=[("zone", owner, name, "library", "battlefield", "searched")])
        if dst == "Exile":
            by = f" by {resolver}" if resolver else ""
            return Line(side=side, depth=1, text=f"{mark} is exiled from {frm}{by}",
                        facts=[("zone", owner, name, frm, "exile", "exiled")])
        by = f" by {resolver}" if resolver else ""
        return Line(side=side, depth=1, text=f"{mark} moves from {frm} to {to}{by}",
                    facts=[("zone", owner, name, frm, to, "moved")])

    # -- the seat's public history: names for hidden moves -----------------------------------------------------

    def merge(self, history: list[Any]) -> list[Line]:
        """Combine pending engine lines with the human seat's public history (draws, moves into hands and
        libraries, looks, reveals, shuffles) and return the lines to append to the log, in causal order.

        The public history mirrors the engine's Draw, ZoneChange, SpellCast, CreateToken and UpkeepBegan events one
        for one and in order, so each such history event is placed at its engine event; a look, reveal or shuffle
        goes just before the next mirrored event. History past the last narrated engine event (the engine refused a
        snapshot) waits for the next call."""
        events = [e for e in self.backlog + list(history) if isinstance(e, Mapping)]
        self.backlog = []
        slots = self.slots
        k = 0
        placed: list[tuple[Mapping[str, Any], float | None]] = []
        for n, event in enumerate(events):
            kind = event.get("kind")
            if kind in ("draw", "zone_move", "token_created", "turn_began"):
                if k >= len(slots):
                    self.backlog = events[n:]
                    break
                index, slot_kind = slots[k]
                k += 1
                placed.append((event, float(index) if slot_kind == kind else None))
            else:
                placed.append((event, None))
        self.slots = slots[k:]
        tail = max([i for i, _ in self.pending_lines] + [self.offset - 0.5]) + 0.05
        extra: list[tuple[float, Line]] = []
        next_index = tail
        for event, index in reversed(placed):  # notes take the position just before the next mirrored event
            if index is None:
                next_index -= 0.001
                index = next_index
            else:
                next_index = index + 0.05
                index += 0.1
            kind = event.get("kind")
            if kind == "token_created":
                continue  # the engine line names it
            if kind == "zone_move" and (event.get("to") or {}).get("zone") not in ("hand", "library"):
                continue  # public destinations come from the engine events
            line = self._history_line(event)
            if line is not None:
                extra.append((index, line))
        merged = sorted(self.pending_lines + extra, key=lambda pair: pair[0])
        self.pending_lines = []
        return self._collapse([line for _, line in merged])

    @staticmethod
    def _collapse(lines: list[Line]) -> list[Line]:
        """Consecutive draws by one player become one line ("You draw A, B", "Opp draws 7 cards")."""
        out: list[Line] = []
        run: list[Line] = []
        grouped: list[Line] = []
        for line in lines + [Line(side="", text="", facts=[])]:  # a run of draws of both players (an opening hand)
            if line.get("draw"):
                run.append(line)
                continue
            if len(run) > 2 and len({r["side"] for r in run}) == 2:
                for side in ("you", "opp"):
                    mine = [r for r in run if r["side"] == side]
                    if mine:
                        grouped.append(Line(mine[0], names=[n for r in mine for n in r["names"]],
                                            facts=[f for r in mine for f in r["facts"]], text=mine[0]["text"]))
                        grouped[-1]["text"] = ("You draw " + ", ".join(grouped[-1]["names"])) if side == "you" else                             f"Opp draws {len(grouped[-1]['names'])} cards"
                        grouped[-1]["draw"] = False
            else:
                grouped.extend(run)
            run = []
            if line["side"]:
                grouped.append(line)
        lines = grouped
        for line in lines:
            prev = out[-1] if out else None
            if prev is not None and line.get("draw") and prev.get("draw") and line["side"] == prev["side"]:
                names = prev["names"] + line["names"]
                if line["side"] == "you":
                    txt = "You draw " + ", ".join(names)
                else:
                    txt = f"Opp draws {len(names)} cards"
                out[-1] = Line(prev, text=txt, names=names, facts=prev["facts"] + line["facts"])
                continue
            out.append(line)
        return out

    def _history_line(self, event: Mapping[str, Any]) -> Line | None:
        me = self.me
        kind = event.get("kind")
        if kind == "turn_began":
            seat = event.get("active_seat")
            return Line(side="game", depth=0, text=f"Turn {event.get('turn')}: {'your' if seat == me else 'opponent'} turn",
                        facts=[("turn", seat)], header=True)
        if kind == "draw":
            seat = event.get("seat")
            if seat == me:
                return Line(side="you", depth=1, text=f"You draw {text.card(event.get('card'))}", draw=True,
                            names=[text.card(event.get("card"))],
                            facts=[("zone", seat, text.card(event.get("card")), "library", "hand", "drawn")])
            return Line(side="opp", depth=1, text="Opp draws a card", draw=True, names=["?"],
                        facts=[("zone", seat, None, "library", "hand", "drawn")])
        if kind == "zone_move":
            seat = event.get("owner_seat")
            card = event.get("card")
            name = text.card(card) if isinstance(card, Mapping) and card.get("card_name") else None
            frm = (event.get("from") or {}).get("zone")
            to = (event.get("to") or {}).get("zone")
            who = seat_word(seat, me)
            s = "" if seat == me else "s"
            if frm == "library" and to == "hand":
                txt = f"{who} put{s} {name or 'a card'} from library into hand"
            elif to == "hand":
                txt = f"{name or 'A card'} returns to {'your' if seat == me else 'opp'} hand from {frm}"
            elif to == "library":
                txt = f"{who} put{s} {name or 'a card'} from {frm} into library"
            else:
                txt = f"{name or 'A card'}: {frm} to {to}"
            return Line(side="you" if seat == me else "opp", depth=1, text=txt,
                        facts=[("zone", seat, name, frm, to, "moved")])
        if kind == "looked_at":
            names = ", ".join(text.card(entry.get("card")) for entry in event.get("cards") or [])
            return Line(side="you", depth=1, text=f"You look at: {names}", facts=[("look", me)])
        if kind == "card_revealed":
            seat = event.get("owner_seat")
            return Line(side="you" if seat == me else "opp", depth=1,
                        text=f"{seat_word(seat, me)} reveal{'s' if seat != me else ''} {text.card(event.get('card'))}",
                        facts=[("reveal", seat)])
        if kind == "library_shuffled":
            seat = event.get("owner_seat")
            return Line(side="game", depth=1, text=f"{seat_word(seat, me)} shuffle{'s' if seat != me else ''} "
                                                   f"{'your' if seat == me else 'their'} library", facts=[])
        if kind == "library_rearranged":
            seat = event.get("owner_seat")
            return Line(side="game", depth=1, text=f"{seat_word(seat, me)} put{'s' if seat != me else ''} "
                                                   f"{event.get('top_count')} on top and {event.get('bottom_count')} on "
                                                   f"the bottom of {'your' if seat == me else 'their'} library", facts=[])
        return None


def events_at(window: list[tuple[int, Any]], index: int) -> Any:
    for i, ev in window:
        if i == index:
            return ev
    return None


class RecordTail:
    """Reads new lines of a growing engine record (``engine.jsonl``) without disturbing its writer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.position = 0
        self.partial = b""

    def read(self) -> Iterator[Mapping[str, Any]]:
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.position)
                data = stream.read()
                self.position = stream.tell()
        except OSError:
            return
        data = self.partial + data
        lines = data.split(b"\n")
        self.partial = lines.pop()
        for raw in lines:
            if raw.strip():
                yield json.loads(raw)
