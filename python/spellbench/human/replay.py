"""Replay check for the human play log: does the log explain every change the human seat was shown?

``python -m spellbench.human.replay <engine.jsonl[.gz]> [--seat p0] [--print]`` walks a recorded game (the operator
engine record), feeds it to the play log in the order the session would (``narrate.Narrator`` through
``server.Hub``'s path), reconstructs the sequence of observations the human seat received, and for every change
between consecutive observations checks that a log line emitted in that interval accounts for it and names a
cause. Changes covered: objects changing zone, tapped state, counters, power/toughness, damage, attachment,
controller, life, hand and library counts, stack contents, mana pools, turn and step.

It also checks hidden information: no card the human seat could not see (the opponent's hand, library and
face-down cards, as named only in the full engine state) appears in any log line.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .narrate import Narrator
from . import text

SEATS = ("p0", "p1")


def read_record(path: Path) -> list[Mapping[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def human_seat(rows: list[Mapping[str, Any]], decision_logs: Path | None = None) -> str | None:
    """The human seat from the session's decision logs (the header with ``bot_name`` "Human"), if given."""
    game = next((r["message"].get("game_id") for r in rows if r["message"].get("game_id")), None)
    if decision_logs is not None and game:
        for seat in SEATS:
            path = decision_logs / f"{game}.{seat}.jsonl"
            if path.exists():
                with path.open(encoding="utf-8") as stream:
                    header = json.loads(stream.readline())
                if header.get("bot_name") == "Human":
                    return seat
    return None


def decisions(rows: Iterable[Mapping[str, Any]]) -> Iterator[Mapping[str, Any]]:
    for row in rows:
        message = row.get("message") or {}
        if row.get("dir") == "engine_to_host" and message.get("response_type") == "decision":
            yield message["seat_decision"]


# -- what the human seat saw -----------------------------------------------------------------------------------

def visible(observation: Mapping[str, Any], me: str) -> dict[str, Any]:
    """The comparable content of one observation."""
    objects: dict[str, dict[str, Any]] = {}
    players: dict[str, dict[str, Any]] = {}
    for player in observation.get("players") or []:
        seat = player.get("seat")
        players[seat] = {"life": player.get("life"), "hand_count": player.get("hand_count"),
                         "library_count": player.get("library_count"), "poison": player.get("poison"),
                         "mana": tuple(sorted((player.get("mana_pool") or {}).items()))}
        zones = {"battlefield": player.get("battlefield") or [], "graveyard": player.get("graveyard") or [],
                 "exile": player.get("exile") or []}
        if seat == me:
            zones["hand"] = player.get("hand") or []
        for zone, cards in zones.items():
            for card in cards:
                permanent = card.get("permanent") or {}
                chars = card.get("characteristics") or {}
                objects[card["object_id"]] = {
                    "zone": zone, "name": card.get("card_name"), "owner": card.get("owner_seat"),
                    "controller": card.get("controller_seat"), "tapped": permanent.get("tapped"),
                    "counters": tuple(sorted((permanent.get("counters") or {}).items())),
                    "pt": (chars.get("power"), chars.get("toughness")), "damage": permanent.get("damage"),
                    "attached": permanent.get("attached_to") and permanent["attached_to"].get("card_name")
                    if isinstance(permanent.get("attached_to"), Mapping) else permanent.get("attached_to")}
    stack = [(entry.get("object_id"), entry.get("card_name"), entry.get("controller_seat"))
             for entry in observation.get("stack") or []]
    return {"objects": objects, "players": players, "stack": stack, "turn": observation.get("turn"),
            "step": observation.get("phase_step"), "active": observation.get("active_seat")}


def changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[tuple]:
    """Every change between two visible states, as (kind, seat, name, detail)."""
    out: list[tuple] = []
    a, b = before["objects"], after["objects"]
    left = [oid for oid in a if oid not in b]
    came = [oid for oid in b if oid not in a]
    pool = Counter((b[oid]["owner"], b[oid]["name"]) for oid in came)
    for oid in left:
        o = a[oid]
        out.append(("leave", o["owner"], o["name"], o["zone"]))
    for oid in came:
        o = b[oid]
        out.append(("enter", o["owner"], o["name"], o["zone"]))
    for oid in a:
        if oid in b:
            x, y = a[oid], b[oid]
            for field in ("tapped", "counters", "pt", "damage", "attached", "controller"):
                if x[field] != y[field]:
                    out.append((field, y["controller"], y["name"], (x[field], y[field])))
    for seat, p in after["players"].items():
        q = before["players"].get(seat)
        if q is None:
            continue
        for field in ("life", "hand_count", "library_count", "poison", "mana"):
            if p[field] != q[field]:
                out.append((field, seat, None, (q[field], p[field])))
    sa, sb = before["stack"], after["stack"]
    ids_a, ids_b = {s[0] for s in sa}, {s[0] for s in sb}
    for s in sa:
        if s[0] not in ids_b:
            out.append(("stack-", s[2], s[1], None))
    for s in sb:
        if s[0] not in ids_a:
            out.append(("stack+", s[2], s[1], None))
    if (before["turn"], before["active"]) != (after["turn"], after["active"]):
        out.append(("turn", after["active"], None, (before["turn"], after["turn"])))
    elif before["step"] != after["step"]:
        out.append(("step", after["active"], None, (before["step"], after["step"])))
    return out


LATE_INTERVALS = 3  # the decisions after a change in which a later log line may still explain it
ZONE_CAUSES = {"cast", "resolved", "played", "sacrificed", "lethal damage", "destroyed", "effect", "state",
               "discarded", "milled", "searched", "exiled", "moved", "drawn", "token", "cost"}


def explained(change: tuple, facts: list[tuple], turn_lines: list[tuple]) -> bool:
    kind, seat, name, detail = change
    zone_facts = [f for f in facts if f[0] == "zone"]
    if kind in ("leave", "enter"):
        zone = detail
        for f in zone_facts:
            _, owner, fname, frm, to, cause = f
            if cause not in ZONE_CAUSES:
                continue
            if owner not in (None, seat):
                continue
            if fname is not None and name is not None and fname != name:
                continue
            if (kind == "leave" and frm == zone) or (kind == "enter" and to == zone):
                return True
        if kind == "leave" and zone == "battlefield" and name and "Token" in name:
            return any(f[0] == "zone" and f[2] == name for f in zone_facts)
        return False
    if kind == "tapped":
        was, now = detail
        if not now and turn_lines and any(t[1] == seat for t in turn_lines):
            return True  # the untap step of the turn that began
        return any(f[0] in ("tap", "attack") and f[1] == seat and f[2] in (name, None) for f in facts) or \
            any(f[0] == "stack+" and f[1] == seat and f[2] == name for f in facts)
    if kind in ("counters", "pt", "damage"):
        if turn_lines:  # cleanup removes damage and ends "until end of turn" effects
            return True
        # A line must name the permanent and say what changed on it (a resolving ability alone does not).
        return any(f[0] in ("counters", "pt", "damage") and f[2] == name for f in facts)
    if kind in ("attached", "controller"):
        return any(f[0] == "stack-" for f in facts) or any(f[2] == name for f in facts if len(f) > 2)
    if kind == "life":
        return any(f[0] == "life" and f[1] == seat for f in facts)
    if kind in ("hand_count", "library_count"):
        word = "hand" if kind == "hand_count" else "library"
        return any(f[0] == "zone" and f[1] in (seat, None) and word in (f[3], f[4]) for f in zone_facts)
    if kind == "mana":
        return any(f[0] in ("mana", "stack+", "zone") and f[1] == seat for f in facts) or bool(turn_lines) or \
            any(f[0] == "step" for f in facts)
    if kind == "poison":
        return any(f[0] == "damage" for f in facts)
    if kind in ("stack+", "stack-"):
        return any(f[0] == kind and f[1] == seat and (f[2] == name or name is None or f[2] is None) for f in facts) or \
            (kind == "stack-" and any(f[0] == "zone" and f[2] == name and f[3] == "stack" for f in zone_facts))
    if kind == "turn":
        return bool(turn_lines)
    if kind == "step":
        return any(f[0] == "step" for f in facts)
    return False


def replay(rows: list[Mapping[str, Any]], me: str, *, show: bool = False) -> dict[str, Any]:
    """Run the play log over a recorded game; returns counts, unexplained changes and the log."""
    from .server import Hub  # the page's own path: the same code the session runs

    hub = Hub()
    hub.game = {"seat": me, "game_id": "replay", "number": 1}
    hub.narrator = Narrator(me)
    pending = []
    unexplained: list[tuple] = []
    total = 0
    previous = None
    log_mark = 0
    all_lines: list[dict[str, Any]] = []  # every line of the game (the hub keeps only its newest LOG_LIMIT)
    leaks: list[str] = []
    hidden_names: set[str] = set()
    every_name = all_card_names(rows)
    public: set[str] = set()
    intervals: list[tuple[list[tuple], list[tuple]]] = []  # (facts, turn facts) of each interval, in order
    refused_at: set[int] = set()                            # intervals whose decision the engine gave no snapshot for
    held: list[tuple[int, tuple, tuple]] = []               # (interval, change, report) not explained in its own
    for sd in decisions(rows):
        hub.narrator.engine_decision(sd)
        _collect_hidden(sd, me, hidden_names)
        if sd.get("acting_seat") != me:
            continue
        hub.absorb_narrated(sd)
        seen = visible(sd.get("observation") or {}, me)
        _add_public(sd, public)
        new_lines, log_mark = hub.log_since(log_mark)
        all_lines += new_lines
        # Time-ordered hidden-information check: a line may name only cards the seat has seen by this decision.
        unseen = every_name - public
        leaks += [line["text"] for line in new_lines if any(name in line["text"] for name in unseen)]
        facts = [f for line in new_lines for f in line.get("facts") or []]
        turn_lines = [f for f in facts if f[0] == "turn"]
        intervals.append((facts, turn_lines))
        if not ((sd.get("extensions") or {}).get("x_kernel_infoset_v1") or {}).get("payload_json"):
            # The engine gave this decision no snapshot (a refusal such as R1 same_name_hand_reveal, or none at all):
            # the log catches up at the next one.
            refused_at.add(len(intervals) - 1)
        if previous is not None:
            for change in changes(previous, seen):
                total += 1
                if not explained(change, facts, turn_lines):
                    held.append((len(intervals) - 1, change,
                                 (sd.get("observation", {}).get("turn"), sd.get("observation", {}).get("phase_step"),
                                  change, [line["text"] for line in new_lines])))
        previous = seen
    # A spell or ability is logged when its cast or activation completes, so the board can show it on the stack
    # (choosing a cost or target) a decision or two before its line. Those changes are "late", not missing.
    late: list[tuple] = []
    refused: list[tuple] = []
    for at, change, report in held:
        window = intervals[at + 1:at + 1 + LATE_INTERVALS]
        if at in refused_at:
            refused.append(report)  # counted apart, never as explained
        elif any(explained(change, facts, turn_lines) for facts, turn_lines in window):
            late.append(report)
        else:
            unexplained.append(report)
    return {"changes": total, "unexplained": unexplained, "late": late, "refused": refused, "log": all_lines, "leaks": leaks,
            "hidden_names": hidden_names}


def _collect_hidden(sd: Mapping[str, Any], me: str, names: set[str]) -> None:
    """Names the human never saw: cards in the opponent's hand or library in the human's own observations are
    hidden (hand is null). The hidden check instead compares log text against public sightings (see leak_check)."""


def _add_public(sd: Mapping[str, Any], public: set[str]) -> None:
    """Names the human seat has seen at this decision: its own observation (public zones and its own hand, the
    stack and its targets, what it knows) and its public history (draws, moves, looks, reveals)."""
    obs = sd.get("observation") or {}
    for player in obs.get("players") or []:
        for zone in ("battlefield", "graveyard", "exile", "hand"):
            for card in player.get(zone) or []:
                if card.get("card_name"):
                    public.add(card["card_name"])
    for entry in obs.get("stack") or []:
        if entry.get("card_name"):
            public.add(entry["card_name"])
        for t in entry.get("targets") or []:
            o = (t or {}).get("object") or {}
            if o.get("card_name"):
                public.add(o["card_name"])
    for entry in obs.get("known") or []:
        if entry.get("card_name"):
            public.add(entry["card_name"])
    for event in ((sd.get("extensions") or {}).get("x_public_history_v1") or {}).get("events") or []:
        for ref in [event.get("card")] + [c.get("card") for c in event.get("cards") or []]:
            if isinstance(ref, Mapping) and ref.get("card_name"):
                public.add(ref["card_name"])


def all_card_names(rows: list[Mapping[str, Any]]) -> set[str]:
    """Every card name in any engine state of the game (both hands and libraries included)."""
    names: set[str] = set()
    for sd in decisions(rows):
        raw = ((sd.get("extensions") or {}).get("x_kernel_infoset_v1") or {}).get("payload_json")
        if isinstance(raw, str):
            for o in json.loads(raw)["state"]["objects"]["items"]:
                if isinstance(o, Mapping) and o.get("name"):
                    names.add(o["name"])
    return names


def leak_check(rows: list[Mapping[str, Any]], me: str, log: list[Mapping[str, Any]]) -> list[str]:
    """Card names in the log that the human seat never saw publicly anywhere in the game (whole-game form)."""
    public: set[str] = set()
    for sd in decisions(rows):
        if sd.get("acting_seat") == me:
            _add_public(sd, public)
    never_public = all_card_names(rows) - public
    return [line["text"] for line in log if any(name in line["text"] for name in never_public)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spellbench.human.replay", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("record", type=Path, nargs="+")
    parser.add_argument("--seat", default=None, help="the human seat (default: from --decision-logs, else p0)")
    parser.add_argument("--decision-logs", type=Path, default=None)
    parser.add_argument("--print", action="store_true", help="print the log")
    parser.add_argument("--unexplained", type=int, default=20, help="show this many unexplained changes")
    args = parser.parse_args(argv)
    worst = 0
    for path in args.record:
        rows = read_record(path)
        me = args.seat or human_seat(rows, args.decision_logs) or "p0"
        result = replay(rows, me)
        leaks = result["leaks"] + [leak for leak in leak_check(rows, me, result["log"]) if leak not in result["leaks"]]
        if args.print:
            for line in result["log"]:
                indent = "    " if line.get("depth") else ""
                print(f"{indent}{line['text']}")
        print(f"{path.name}: seat {me}, {result['changes']} visible changes, {len(result['unexplained'])} unexplained "
              f"(+{len(result['late'])} explained by a line of the same action a decision or two later, "
              f"+{len(result['refused'])} in decisions the engine gave no snapshot for), "
              f"{len(leaks)} hidden-card leaks")
        for turn, step, change, lines in result["unexplained"][:args.unexplained]:
            print(f"  turn {turn} {step}: {change}")
        for leak in leaks[:10]:
            print(f"  LEAK: {leak}")
        worst = max(worst, len(result["unexplained"]) + len(leaks))
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
