"""A scripted stand-in for the Manabrew client, for testing the room host end to end without a browser.

``python -m spellbench.human.manabrew.fake_client --room NAME [--relay ws://127.0.0.1:9443] [--out envelopes.jsonl]``
joins the room as a player, readies with a placeholder deck, and answers every prompt with a simple legal choice
(play a land if it can, otherwise cast the first spell, otherwise pass; first target; attack with everything; no
blocks; first option). It writes every envelope it receives to ``--out`` and exits after ``--games`` games.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from .ws import Closed, WebSocket


def action_text(action: Mapping[str, Any]) -> str:
    return str(action.get("label") or action.get("description") or "")


# The client's pass controls, ported from its source (src/stores/usePhaseStopStore.ts and src/hooks/usePromptEffects.ts,
# read only): a plain pass (Space, the PASS button) runs to the next stop; END TURN to the first stop of the next
# player's turn, through combat; on a stack the first sends no target and END TURN sends exhaustStack.
STEPS = ("upkeep", "draw", "main1", "combatBegin", "combatDeclareAttackers", "combatDeclareBlockers",
         "combatFirstStrikeDamage", "combatDamage", "combatEnd", "main2", "endOfTurn", "cleanup")
DEFAULT_SELF_STOPS = ("main1", "combatDeclareAttackers", "main2")
DEFAULT_OPPONENT_STOPS = ("endOfTurn",)


def next_stop(view: Mapping[str, Any], me: str, self_stops: tuple[str, ...] = DEFAULT_SELF_STOPS,
              opponent_stops: tuple[str, ...] = DEFAULT_OPPONENT_STOPS) -> dict[str, Any] | None:
    """getNextStop: the first (player, step) after the current one, in turn order, that the person has a stop at."""
    order = [p["id"] for p in view.get("players") or [] if p.get("status") == "playing"]
    active, step = view.get("activePlayerId"), view.get("step")
    if active not in order:
        return None
    start = order.index(active)
    here = STEPS.index(step) if step in STEPS else -1
    for slot in range(len(order) + 1):
        player = order[(start + slot) % len(order)]
        stops = self_stops if player == me else opponent_stops
        first = (here + 1 if here >= 0 else len(STEPS)) if slot == 0 else 0
        for phase in STEPS[first:]:
            if phase in stops:
                return {"playerId": player, "phase": phase}
    return None


def end_turn_stop(view: Mapping[str, Any], me: str, self_stops: tuple[str, ...] = DEFAULT_SELF_STOPS,
                  opponent_stops: tuple[str, ...] = DEFAULT_OPPONENT_STOPS) -> dict[str, Any] | None:
    """getEndTurnStop: the first stop from the start of the next player's turn, else that player's upkeep."""
    order = [p["id"] for p in view.get("players") or [] if p.get("status") == "playing"]
    active = view.get("activePlayerId")
    if active not in order:
        return None
    start = order.index(active)
    for slot in range(1, len(order) + 1):
        player = order[(start + slot) % len(order)]
        stops = self_stops if player == me else opponent_stops
        for phase in STEPS:
            if phase in stops:
                return {"playerId": player, "phase": phase}
    return {"playerId": order[(start + 1) % len(order)], "phase": "upkeep"}


def pass_output(view: Mapping[str, Any] | None, me: str, mode: str = "plain",
                self_stops: tuple[str, ...] = DEFAULT_SELF_STOPS,
                opponent_stops: tuple[str, ...] = DEFAULT_OPPONENT_STOPS) -> dict[str, Any]:
    """The pass output the client sends. ``plain``: no target (what this stand-in always sent); ``stops``: Space or
    the PASS button; ``end-turn``: the END TURN button and key."""
    out: dict[str, Any] = {"type": "pass", "exhaustStack": False}
    if view is None or mode == "plain":
        return out
    if view.get("stack"):
        out["exhaustStack"] = mode == "end-turn"
        return out
    if mode == "stops":
        target = next_stop(view, me, self_stops, opponent_stops)
        if target:
            out["until"] = {**target, "throughCombat": False}
    elif mode == "end-turn":
        target = end_turn_stop(view, me, self_stops, opponent_stops)
        if target:
            out["until"] = {**target, "throughCombat": True}
    return out


def answer(prompt: Mapping[str, Any], take: tuple[str, ...] = (), avoid: tuple[str, ...] = (), *,
           view: Mapping[str, Any] | None = None, me: str = "player-0", pass_mode: str = "plain",
           attack: bool = True, passive: bool = False, opening: dict[str, int] | None = None,
           take_steps: tuple[str, ...] = (), lands_only: bool = False) -> dict[str, Any] | None:
    """The scripted answer. ``take``: texts of actions to prefer (any action whose label or description contains one,
    case-insensitively, is taken before anything else), in any step or, with ``take_steps`` (``"endOfTurn"``, or
    ``"opponent:endOfTurn"`` and ``"self:upkeep"`` for one player's turn), only in those steps of the latest
    gameView; ``avoid``: texts of actions never taken; ``lands_only``: besides ``take``, play lands and cast nothing (a
    person who keeps their spells for the windows in ``take_steps``). ``view``: the latest
    gameView and ``me`` the person's player id, which the pass controls (``pass_mode``) read; ``attack``: whether to
    attack with everything; ``passive``: take no action but those in ``take`` (a person who only passes). ``opening``
    (a mutable ``{"mulligans": N}``) scripts the London opening: the first N keep-or-mulligan prompts answer
    mulligan, the next keeps; a put-back prompt picks the first ``count`` cards of the hand in the prompt's order."""
    data = prompt.get("input") or {}
    kind = data.get("type")
    if kind == "mulligan":
        left = (opening or {}).get("mulligans", 0)
        if left > 0:
            opening["mulligans"] = left - 1
            return {"type": "mulliganDecision", "keep": False}
        return {"type": "mulliganDecision", "keep": True}
    if kind == "mulliganPutBack":
        return {"type": "mulliganPutBackDecision", "cardIds": list(data.get("handCardIds") or [])[:int(data.get("count") or 0)]}
    if kind == "chooseAction":
        actions = [a for a in data.get("actions") or []
                   if not any(t.lower() in action_text(a).lower() for t in avoid)]
        wanted = [a for a in actions if a.get("type") != "undoMana" and not a.get("isManaAbility")
                  and any(t.lower() in action_text(a).lower() for t in take)]
        if take_steps:
            step = (view or {}).get("step")
            whose = "self" if (view or {}).get("activePlayerId") == me else "opponent"
            if step not in take_steps and f"{whose}:{step}" not in take_steps:
                wanted = []
        lands = [a for a in actions if a.get("type") == "cast" and str(a.get("label", "")).startswith("Play ")]
        spells = [a for a in actions if a.get("type") == "cast" and a not in lands]
        pick = (wanted or ([] if passive else lands or ([] if lands_only else spells)) or [None])[0]
        return {"type": "act", "actionId": pick["id"]} if pick else pass_output(view, me, pass_mode)
    if kind == "chooseBoardTargets":
        chosen = (data.get("candidates") or [])[:max(1, data.get("minTargets") or 0)]
        return {"type": "boardTargets", "chosen": chosen}
    if kind == "chooseAttackers":
        return {"type": "declareAttackers",
                "assignments": [{"attackerId": a["attackerId"], "targetId": a["validTargetIds"][0]}
                                for a in data.get("attackers") or [] if a.get("validTargetIds") and attack]}
    if kind == "chooseBlockers":
        return {"type": "declareBlockers", "assignments": []}
    if kind == "chooseFromSelection":
        return {"type": "selectionDecision", "chosenIndices": [0]}
    if kind == "chooseCards":
        return {"type": "chooseCardsDecision", "chosenCardIds": [c["id"] for c in (data.get("cards") or [])[:1]]}
    if kind == "chooseBoolean":
        return {"type": "decision", "value": True}
    if kind == "chooseNumber":
        return {"type": "numberDecision", "chosenNumber": data.get("min", 0)}
    if kind == "chooseColor":
        return {"type": "colorDecision", "chosenColors": {(data.get("validColors") or ["C"])[0]: 1}}
    if kind == "payManaCost":
        return {"type": "pay", "auto": True}
    return None  # gameOver and anything unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="ws://127.0.0.1:9443")
    parser.add_argument("--key", default="forge")
    parser.add_argument("--room", required=True)
    parser.add_argument("--username", default="tester")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--deck", default="Rally", help="the training deck to pick at the table")
    parser.add_argument("--take", default="", help="comma-separated texts of actions to take whenever offered "
                        "(for example the ninjutsu activation of a card)")
    parser.add_argument("--take-steps", default="",
                        help="comma-separated steps (StepKind names, or self:STEP and opponent:STEP for one player's "
                        "turn) in which --take applies; elsewhere those actions are not preferred. Default: any step")
    parser.add_argument("--avoid", default="", help="comma-separated texts of actions never to take")
    parser.add_argument("--pass-mode", choices=("plain", "stops", "end-turn"), default="plain",
                        help="what a pass sends: plain (no target), stops (Space: run to the next stop) or end-turn "
                        "(the END TURN button: through combat to the next player's first stop; exhaustStack on a stack)")
    parser.add_argument("--self-stops", default=",".join(DEFAULT_SELF_STOPS),
                        help="the client's own phase stops (StepKind names), for --pass-mode stops and end-turn")
    parser.add_argument("--no-attack", action="store_true", help="declare no attackers")
    parser.add_argument("--passive", action="store_true", help="play no land and cast no spell: only pass (and take --take)")
    parser.add_argument("--lands-only", action="store_true", help="play lands but cast no spell except those in --take")
    parser.add_argument("--concede-game", type=int, default=0,
                        help="concede this game (1, 2, ...) after --concede-after answered prompts")
    parser.add_argument("--concede-after", type=int, default=3)
    parser.add_argument("--mulligans", type=int, default=0,
                        help="London opening: take this many mulligans before keeping (each game)")
    parser.add_argument("--drop-game", type=int, default=0,
                        help="close the connection in this game after --concede-after answered prompts (a closed tab)")
    parser.add_argument("--leave-game", type=int, default=0,
                        help="leave the table (the client's Leave or Abandon) in this game after --concede-after "
                        "answered prompts, then wait --linger seconds for what follows")
    parser.add_argument("--leave-on-start", type=int, default=0,
                        help="leave the table the moment the relay announces this game, before the session's game "
                        "has begun")
    parser.add_argument("--linger", type=float, default=8.0, help="seconds to stay connected after leaving")
    args = parser.parse_args(argv)
    take = tuple(t for t in args.take.split(",") if t)
    avoid = tuple(t for t in args.avoid.split(",") if t)
    take_steps = tuple(t for t in args.take_steps.split(",") if t)
    self_stops = tuple(t for t in args.self_stops.split(",") if t)
    latest_view: dict[str, Any] | None = None
    out = args.out.open("w", encoding="utf-8") if args.out else None
    ws = WebSocket(args.relay)
    send = lambda m: ws.send(json.dumps(m))  # noqa: E731
    send({"type": "Authenticate", "username": args.username, "password": args.key, "service": False})
    joined, games, prompts, errors, slot = False, 0, 0, 0, "player-0"
    opening = {"mulligans": args.mulligans}
    in_game, conceded = 0, False
    started_room = None
    deck = {"name": "Placeholder", "format": "pauper", "sideboard": [],
            "cards": [{"identity": {"id": "Swamp", "name": "Swamp", "setCode": "", "cardNumber": ""}, "uris": {},
                       "color": "", "colorIdentity": [], "manaCost": "", "cmc": 0, "types": ["Land"],
                       "subtypes": ["Swamp"], "supertypes": ["Basic"], "text": ""}] * 60}
    started = time.time()
    while True:
        try:
            msg = json.loads(ws.recv())
        except Closed:
            break
        kind = msg.get("type")
        if kind == "AuthResult":
            send({"type": "ListRooms"})
        elif kind == "RoomList" and not joined:
            room = next((r for r in msg.get("rooms") or [] if r.get("room_name") == args.room), None)
            if room is None:
                time.sleep(1)
                send({"type": "ListRooms"})
                continue
            joined = True
            send({"type": "JoinRoom", "room_id": room["room_id"]})
            from . import decks as pool
            picked = pool.lobby_deck(args.deck) if args.deck in pool.DECKS else deck
            send({"type": "SetDeckSelection", "deck_name": picked["name"], "deck": picked, "commander_name": None})
            send({"type": "SetReady", "ready": True})
        elif kind == "RoomUpdate" and joined and (msg.get("room") or {}).get("status") == "Lobby":
            room = msg.get("room") or {}
            players = room.get("players") or []
            me = next((p for p in players if p.get("username") == args.username), None)
            if me is not None and not me.get("ready"):
                send({"type": "SetReady", "ready": True})
            elif (len(players) >= 2 and all(p.get("ready") and p.get("connected") for p in players)
                  and room.get("room_id") != started_room):
                started_room = room.get("room_id")
                send({"type": "StartGame", "format": "Pauper"})  # the room's controller starts, as the client does
        elif kind == "GameStarted":
            order = msg.get("player_order") or []
            slot = f"player-{order.index(args.username)}" if args.username in order else "player-0"
            if args.leave_on_start == games + 1:
                print(f"leaving the table as game {games + 1} is announced", flush=True)
                send({"type": "LeaveRoom"})
                time.sleep(args.linger)
                ws.close()
                return 0
        elif kind == "StateUpdate":
            envelope = msg.get("state") or {}
            if out:
                out.write(json.dumps(envelope) + "\n")
                out.flush()
            if envelope.get("kind") == "state":
                latest_view = (envelope.get("state") or {}).get("gameView") or latest_view
            elif envelope.get("kind") == "prompt":
                prompt = envelope["prompt"]
                if (prompt.get("input") or {}).get("type") == "gameOver":
                    games += 1
                    print(f"game {games} over after {round(time.time() - started)} s, {prompts} prompts, "
                          f"{errors} errors", flush=True)
                    if games >= args.games:
                        break
                    in_game, conceded = 0, False
                    opening["mulligans"] = args.mulligans
                    started_room, joined = None, False  # the table empties after a game: join it again
                    time.sleep(2)
                    send({"type": "ListRooms"})
                    continue
                output = answer(prompt, take, avoid, view=latest_view, me=slot, pass_mode=args.pass_mode,
                                attack=not args.no_attack, passive=args.passive, opening=opening,
                                take_steps=take_steps, lands_only=args.lands_only)
                if output is not None and output.get("type") == "pass" and (output.get("until") or output.get("exhaustStack")):
                    print(f"pass with {json.dumps({k: v for k, v in output.items() if k != 'type'})}", flush=True)
                if output is not None:
                    prompts += 1
                    in_game += 1
                    send({"type": "BroadcastState", "target_player": None,
                          "state": {"kind": "response", "fromPlayer": slot, "promptId": prompt["promptId"],
                                    "action": {"type": prompt["input"]["type"], "output": output}}})
                    if args.concede_game == games + 1 and in_game >= args.concede_after and not conceded:
                        conceded = True
                        print(f"conceding game {games + 1} after {in_game} prompts", flush=True)
                        send({"type": "BroadcastState", "target_player": None,
                              "state": {"kind": "directive", "fromPlayer": slot, "directive": {"type": "concede"}}})
                    if args.leave_game == games + 1 and in_game >= args.concede_after:
                        print(f"leaving the table in game {games + 1} after {in_game} prompts", flush=True)
                        send({"type": "LeaveRoom"})
                        time.sleep(args.linger)
                        ws.close()
                        return 0
                    if args.drop_game == games + 1 and in_game >= args.concede_after:
                        print(f"closing the connection in game {games + 1} after {in_game} prompts", flush=True)
                        ws.close()
                        return 0
            elif envelope.get("kind") == "error":
                errors += 1
                print(f"error: {envelope.get('error')}", flush=True)
        elif kind == "Error":
            print(f"relay error: {msg}", flush=True)
    ws.close()
    return 0 if games >= args.games else 1


if __name__ == "__main__":
    sys.exit(main())
