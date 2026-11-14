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


def answer(prompt: Mapping[str, Any]) -> dict[str, Any] | None:
    data = prompt.get("input") or {}
    kind = data.get("type")
    if kind == "chooseAction":
        actions = data.get("actions") or []
        lands = [a for a in actions if a.get("type") == "cast" and str(a.get("label", "")).startswith("Play ")]
        spells = [a for a in actions if a.get("type") == "cast" and a not in lands]
        pick = (lands or spells or [None])[0]
        return {"type": "act", "actionId": pick["id"]} if pick else {"type": "pass", "exhaustStack": False}
    if kind == "chooseBoardTargets":
        chosen = (data.get("candidates") or [])[:max(1, data.get("minTargets") or 0)]
        return {"type": "boardTargets", "chosen": chosen}
    if kind == "chooseAttackers":
        return {"type": "declareAttackers",
                "assignments": [{"attackerId": a["attackerId"], "targetId": a["validTargetIds"][0]}
                                for a in data.get("attackers") or [] if a.get("validTargetIds")]}
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
    args = parser.parse_args(argv)
    out = args.out.open("w", encoding="utf-8") if args.out else None
    ws = WebSocket(args.relay)
    send = lambda m: ws.send(json.dumps(m))  # noqa: E731
    send({"type": "Authenticate", "username": args.username, "password": args.key, "service": False})
    joined, games, prompts, errors, slot = False, 0, 0, 0, "player-0"
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
            send({"type": "SetDeckSelection", "deck_name": "Placeholder", "deck": deck, "commander_name": None})
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
                send({"type": "StartGame", "format": None})  # the room's controller starts, as the client does
        elif kind == "GameStarted":
            order = msg.get("player_order") or []
            slot = f"player-{order.index(args.username)}" if args.username in order else "player-0"
        elif kind == "StateUpdate":
            envelope = msg.get("state") or {}
            if out:
                out.write(json.dumps(envelope) + "\n")
                out.flush()
            if envelope.get("kind") == "prompt":
                prompt = envelope["prompt"]
                if (prompt.get("input") or {}).get("type") == "gameOver":
                    games += 1
                    print(f"game {games} over after {round(time.time() - started)} s, {prompts} prompts, "
                          f"{errors} errors", flush=True)
                    if games >= args.games:
                        break
                    started_room, joined = None, False  # the table empties after a game: join it again
                    time.sleep(2)
                    send({"type": "ListRooms"})
                    continue
                output = answer(prompt)
                if output is not None:
                    prompts += 1
                    send({"type": "BroadcastState", "target_player": None,
                          "state": {"kind": "response", "fromPlayer": slot, "promptId": prompt["promptId"],
                                    "action": {"type": prompt["input"]["type"], "output": output}}})
            elif envelope.get("kind") == "error":
                errors += 1
                print(f"error: {envelope.get('error')}", flush=True)
        elif kind == "Error":
            print(f"relay error: {msg}", flush=True)
    ws.close()
    return 0 if games >= args.games else 1


if __name__ == "__main__":
    sys.exit(main())
