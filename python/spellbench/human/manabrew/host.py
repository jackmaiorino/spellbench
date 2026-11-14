"""The human seat of a Spellbench session, played through an unmodified Manabrew client.

This process is a room host on a Manabrew relay running on this machine (``manabrew-server``, unmodified): it
creates a hosted room, seats the bot through a second relay session, and starts a game when the person who joined
from the client is ready. During the game it sends the person the board (``state`` envelopes with a full
``gameView`` built from the human seat's own observation), the causal play log (``log`` envelopes) and each pending
decision (``prompt`` envelopes), and turns the client's answers into the play server's answers. The bot, the engine
and the session are the ordinary ``spellbench.human`` ones: nothing the bot observes changes.

Wire formats: the relay messages and envelopes follow the upstream relay as read at the commit named in NOTICE.md;
the engine-client messages follow the Manabrew protocol documentation (CC-BY-4.0).
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any, Mapping

from . import prompts, view
from .ws import Closed, WebSocket

HOST_NAME = "spellbench-host"
PROTOCOL_VERSION = 6  # the client lists a table as joinable only when this matches its own protocol version
LOG_TYPES = {"game": "info", "you": "action", "opp": "action"}


def _deck(name: str, decklist: list[Mapping[str, Any]]) -> dict[str, Any]:
    cards = []
    for entry in decklist:
        info = view.CARDS.get(entry["name"], {})
        types = (info.get("type_line") or "").split(" - ")[0].split()
        for _ in range(int(entry.get("count", 1))):
            cards.append({"identity": {"id": entry["name"], "name": entry["name"], "setCode": "", "cardNumber": ""},
                          "uris": {}, "color": "", "colorIdentity": [], "manaCost": info.get("mana_cost", ""),
                          "cmc": 0, "types": types, "subtypes": [], "supertypes": [], "text": info.get("text", "")})
    return {"name": name, "format": "pauper", "cards": cards, "sideboard": []}


def pool_deck() -> tuple[str, list[dict[str, Any]]]:
    """The bot's lobby deck: lobby metadata only (the session schedules the real decks). It names one basic land,
    so the client looks up no other card names for it."""
    return "Decks set by the session", [{"name": "Mountain", "count": 60}]


class Session:
    """One authenticated relay connection with a reader thread."""

    def __init__(self, url: str, key: str, username: str, *, service: bool, on_message) -> None:
        self.ws = WebSocket(url)
        self.username = username
        self.send({"type": "Authenticate", "username": username, "password": key, "service": service})
        reply = json.loads(self.ws.recv())
        if reply.get("type") != "AuthResult" or not reply.get("success"):
            raise RuntimeError(f"relay refused {username}: {reply}")
        self.player_id = reply.get("player_id")
        self.on_message = on_message
        self.alive = True
        threading.Thread(target=self._read, daemon=True, name=f"relay-{username}").start()
        threading.Thread(target=self._ping, daemon=True, name=f"ping-{username}").start()

    def send(self, message: Mapping[str, Any]) -> None:
        self.ws.send(json.dumps(message, separators=(",", ":")))

    def _read(self) -> None:
        try:
            while True:
                self.on_message(self, json.loads(self.ws.recv()))
        except (Closed, OSError) as exc:
            print(f"relay session {self.username} closed: {exc}", flush=True)
        except Exception:  # noqa: BLE001 - keep the session's reason on the console
            traceback.print_exc()
        self.alive = False

    def _ping(self) -> None:
        while self.alive:
            time.sleep(20)
            try:
                self.send({"type": "Ping"})
            except OSError:
                return


class Bridge:
    def __init__(self, hub, *, relay_url: str, relay_key: str, room_name: str, bot_name: str,
                 bot_deck: tuple[str, list[Mapping[str, Any]]]) -> None:
        self.hub = hub
        self.url, self.key = relay_url, relay_key
        self.room_name = room_name
        self.bot_name = bot_name
        self.bot_deck = bot_deck
        self.lock = threading.RLock()
        self.room: dict[str, Any] | None = None
        self.room_id: str | None = None
        self.human: str | None = None
        self.order: list[str] | None = None
        self.game_id: str | None = None
        self.seats: view.Seats | None = None
        self.prompt: dict[str, Any] | None = None  # {"seq", "answer", "type"}
        self.sent_log = 0
        self.sent_view: str | None = None
        self.starting = False
        self.fallback_seq: int | None = None
        self.starter: str | None = None  # the seat that took the first turn  # a combat plan did not fit: ask substep by substep

    # -- relay ---------------------------------------------------------------------------------------------------

    def start(self) -> None:
        self.host = Session(self.url, self.key, HOST_NAME, service=True, on_message=self._on_host)
        self.host.send({"type": "CreateRoom", "room_name": self.room_name, "max_players": 2, "format": "Pauper",
                        "protocol_version": PROTOCOL_VERSION, "hosted": True, "engine": "Manabrew"})
        threading.Thread(target=self._pump, daemon=True, name="manabrew-pump").start()

    def _on_host(self, session: Session, msg: Mapping[str, Any]) -> None:
        kind = msg.get("type")
        with self.lock:
            if kind == "RoomCreated":
                self.room_id, self.room = msg["room_id"], msg.get("room")
                print(f"  Manabrew room '{self.room_name}' is open on {self.url}", flush=True)
                self.bot = Session(self.url, self.key, self.bot_name, service=False, on_message=self._on_bot)
                self.bot.send({"type": "JoinRoom", "room_id": self.room_id, "as_bot": True})
            elif kind == "RoomUpdate":
                self.room = msg.get("room")
                self._maybe_start()
                self._reseat_bot()
            elif kind == "GameStarted":
                self.order = list(msg.get("player_order") or [])
                self.game_id = msg.get("game_id")
                self.starting = False
                self.hub.control("start", {})
            elif kind == "StateUpdate":
                self._on_response(msg.get("from_player"), msg.get("state") or {})
            elif kind == "Error":
                print(f"  relay error: {msg.get('code')}: {msg.get('message')}", flush=True)

    def _reseat_bot(self) -> None:
        """After a game the relay returns the table to its lobby without its seats: seat the bot again."""
        room = self.room or {}
        players = room.get("players") or []
        if (room.get("status") == "Lobby" and getattr(self, "bot", None) is not None
                and not any(p.get("username") == self.bot_name for p in players)
                and time.time() - getattr(self, "_bot_join_at", 0) > 3):
            self._bot_join_at = time.time()
            self._bot_seated = False
            self.bot.send({"type": "JoinRoom", "room_id": self.room_id, "as_bot": True})

    def _on_bot(self, session: Session, msg: Mapping[str, Any]) -> None:
        if msg.get("type") == "RoomUpdate" and not getattr(self, "_bot_seated", False):
            players = (msg.get("room") or {}).get("players") or []
            if any(p.get("username") == self.bot_name for p in players):
                self._bot_seated = True
                session.send({"type": "SetDeckSelection", "deck_name": self.bot_deck[0],
                              "deck": _deck(*self.bot_deck), "commander_name": None})
                session.send({"type": "SetReady", "ready": True})

    def _maybe_start(self) -> None:
        """Track the person in the room. The relay lets only the room's controller (the first human player) start
        a game, so the person presses Start in the client; GameStarted then readies the session's next game."""
        room = self.room or {}
        humans = [p for p in room.get("players") or [] if not p.get("is_bot") and p.get("username") != HOST_NAME]
        self.human = humans[0]["username"] if humans else None

    # -- game ----------------------------------------------------------------------------------------------------

    def _envelope(self, body: dict[str, Any]) -> None:
        self.host.send({"type": "BroadcastState", "state": body, "target_player": self.human})

    def _pump(self) -> None:
        version = -1
        while True:
            state = self.hub.wait_state(version, timeout=5.0)
            version = state["version"]
            try:
                with self.lock:
                    self._push(state)
                    if state.get("hello_waiting") and self.room is not None:
                        self._maybe_start()
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    def _push(self, state: Mapping[str, Any]) -> None:
        game = state.get("game")
        if not game or self.human is None or self.order is None:
            return
        if self.seats is None or self.seats.human_seat != game.get("seat"):
            human_index = self.order.index(self.human) if self.human in self.order else 0
            bot_index = 1 - human_index
            names = {f"player-{human_index}": self.human, f"player-{bot_index}": self.bot_name}
            self.seats = view.Seats(game.get("seat"), f"player-{human_index}", f"player-{bot_index}", names)
            self.sent_log, self.sent_view, self.prompt, self.starter = 0, None, None, None
        observation = state.get("observation")
        over = state.get("game_over")
        if observation:
            winner = None
            if over and over.get("winner"):
                winner = self.seats.pid(over.get("winner"))
            if observation.get("turn") == 1 and self.starter is None:
                self.starter = observation.get("active_seat")
            gv = view.game_view(observation, self.seats, self.game_id or str(game.get("game_id")),
                                game_over=bool(over), winner=winner, starter=self.starter)
            raw = json.dumps(gv, sort_keys=True)
            if raw != self.sent_view:
                self.sent_view = raw
                self._envelope({"kind": "state", "forPlayer": self.seats.pid(game.get("seat")),
                                "state": {"gameView": gv}})
        log = state.get("log") or []
        for line in log[self.sent_log:]:
            self._envelope({"kind": "log", "fromPlayer": HOST_NAME, "entry": {
                "entryType": LOG_TYPES.get(line.get("side"), "info"),
                "message": ("  " if line.get("depth") else "") + str(line.get("text")),
                "timestampMs": int(time.time() * 1000)}})
        self.sent_log = len(log)
        pending = state.get("pending")
        if pending and (self.prompt is None or self.prompt["seq"] != pending["seq"]):
            self._send_prompt(pending, observation or {})
        if over and self.game_id and not getattr(self, "_ended", None) == self.game_id:
            self._ended = self.game_id
            self._envelope({"kind": "prompt", "forPlayer": self.seats.pid(game.get("seat")),
                            "prompt": {"promptId": 1_000_000 + len(state.get("results") or []),
                                       "decidingPlayerId": self.seats.pid(game.get("seat")),
                                       "input": {"type": "gameOver"}}})
            self.host.send({"type": "EndGame", "game_id": self.game_id})
            self.order, self.seats = None, None

    def _send_prompt(self, pending: Mapping[str, Any], observation: Mapping[str, Any]) -> None:
        if self.fallback_seq == pending["seq"]:
            data, answer = prompts.selection(pending)
        else:
            data, answer = prompts.build(pending, observation, self.seats)
        self.prompt = {"seq": pending["seq"], "answer": answer, "type": data["type"]}
        me = self.seats.pid(self.seats.human_seat)
        prompt = {"promptId": pending["seq"], "decidingPlayerId": me, "input": data}
        source = (pending.get("context") or {}).get("source")
        if isinstance(source, Mapping) and source.get("object_id"):
            found = view.find_card(observation, source["object_id"])
            if found:
                prompt["sourceCard"] = view.card_dto(found[0], self.seats, found[1])
        self._envelope({"kind": "prompt", "forPlayer": me, "prompt": prompt})

    def _on_response(self, sender: str | None, envelope: Mapping[str, Any]) -> None:
        if sender != self.human or envelope.get("kind") != "response" or self.prompt is None:
            return
        me = self.seats.pid(self.seats.human_seat) if self.seats else None
        if envelope.get("promptId") != self.prompt["seq"]:
            self._error(me, "stalePrompt", "that prompt is no longer open", envelope.get("promptId"))
            return
        action = envelope.get("action") or {}
        output = action.get("output") if isinstance(action.get("output"), Mapping) else action
        try:
            how, value = self.prompt["answer"](output)
        except (ValueError, TypeError, KeyError) as exc:
            self._error(me, "invalidShape", str(exc), envelope.get("promptId"))
            return
        seq = self.prompt["seq"]
        error = self.hub.answer_with(seq, int(value)) if how == "answer" else self.hub.plan_with(seq, value)
        if error is not None:
            if how == "plan":
                self.fallback_seq = seq
                self.prompt = None  # re-sent as a substep choice on the next pump
            self._error(me, "unknownActionId", error, seq)

    def _error(self, me: str | None, code: str, message: str, prompt_id: Any) -> None:
        self._envelope({"kind": "error", "forPlayer": me, "error": {"code": code, "message": message,
                                                                      "promptId": prompt_id}})
