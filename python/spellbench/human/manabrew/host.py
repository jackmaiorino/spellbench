"""The human seat of a Spellbench session, played through a Manabrew client.

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
import os
import threading
import time
import traceback
from typing import Any, Mapping

import queue

from ..server import log_since
from . import decks, prompts, view
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

    def __init__(self, url: str, key: str, username: str, *, service: bool, on_message,
                 allow_remote: bool = False) -> None:
        self.ws = WebSocket(url, allow_remote=allow_remote)
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
                 bot_deck: tuple[str, list[Mapping[str, Any]]], bot_deck_for=None,
                 allow_remote_relay: bool = False) -> None:
        self.hub = hub
        self.allow_remote_relay = allow_remote_relay
        self.url, self.key = relay_url, relay_key
        self.room_name = room_name
        self.bot_name = bot_name
        self.bot_deck = bot_deck
        self.lock = threading.RLock()
        self.room: dict[str, Any] | None = None
        self.room_id: str | None = None
        self.human: str | None = None
        self.last_human: str | None = None  # the person's name once they have left the room, to end their game
        self.order: list[str] | None = None
        self.game_id: str | None = None
        self.seats: view.Seats | None = None
        self.prompt: dict[str, Any] | None = None  # {"seq", "answer", "type"}
        self.sent_log = 0
        self.sent_view: str | None = None
        self.starting = False
        self._grace: threading.Timer | None = None
        self.fallback_seq: int | None = None
        self.starter: str | None = None  # the seat that took the first turn
        # Deck picks: the person's table pick (a board deck, or None), the bot's deck for it, and each started game.
        self.bot_deck_for = bot_deck_for or (lambda deck: deck)
        self.human_pick: str | None = None
        self.bot_lobby: str | None = None
        self.starts: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.dealt: dict[str, Any] | None = None  # {"human": deck, "bot": deck} of the game being played  # a combat plan did not fit: ask substep by substep

    # -- relay ---------------------------------------------------------------------------------------------------

    RELAY_RETRY_S = 5.0
    RELAY_PATIENCE_S = 240.0  # the relay frees a killed session's seat and table after a few minutes

    def start(self) -> None:
        """Take the host seat and open the table. A session ended abruptly (a relaunch) leaves its seat and table
        with the relay for a while; the relay refuses the new one until then, so wait and try again."""
        deadline = time.time() + self.RELAY_PATIENCE_S
        while True:
            try:
                self.host = Session(self.url, self.key, HOST_NAME, service=True, on_message=self._on_host,
                                    allow_remote=self.allow_remote_relay)
                break
            except RuntimeError as exc:
                if "taken" not in str(exc) or time.time() > deadline:
                    raise
                print(f"  the relay still holds the host seat of the earlier session; trying again ({exc})", flush=True)
                time.sleep(self.RELAY_RETRY_S)
        self._open_deadline = deadline
        self._create_room()
        threading.Thread(target=self._pump, daemon=True, name="manabrew-pump").start()

    def _create_room(self) -> None:
        self.host.send({"type": "CreateRoom", "room_name": self.room_name, "max_players": 2, "format": "Pauper",
                        "protocol_version": PROTOCOL_VERSION, "hosted": True, "engine": "Manabrew"})

    def _retry_create(self) -> None:
        with self.lock:
            if self.room_id is None:
                self._create_room()

    def _on_host(self, session: Session, msg: Mapping[str, Any]) -> None:
        kind = msg.get("type")
        with self.lock:
            if kind == "RoomCreated":
                self.room_id, self.room = msg["room_id"], msg.get("room")
                print(f"  Manabrew room '{self.room_name}' is open on {self.url}", flush=True)
                self.bot = Session(self.url, self.key, self.bot_name, service=False, on_message=self._on_bot,
                                   allow_remote=self.allow_remote_relay)
                self.bot.send({"type": "JoinRoom", "room_id": self.room_id, "as_bot": True})
            elif kind == "RoomUpdate":
                self.room = msg.get("room")
                self._maybe_start()
                self._reseat_bot()
            elif kind == "GameStarted":
                self.order = list(msg.get("player_order") or [])
                self.game_id = msg.get("game_id")
                # Until the session's next game begins, the play server still shows the last one: not this game's.
                self.stale_game = (self.hub.game or {}).get("game_id") if self.hub.game_over else None
                self.starting = False
                picked = next((decks.catalog_id(d.get("deck_name") or (d.get("deck") or {}).get("name"))
                               for d in msg.get("player_decks") or [] if d.get("username") == self.human), None)
                self.starts.put({"human_pick": picked if picked is not None else self.human_pick,
                                 "picked_name": next((d.get("deck_name") for d in msg.get("player_decks") or []
                                                      if d.get("username") == self.human), None)})
                self.hub.control("start", {})
            elif kind == "StateUpdate":
                self._on_response(msg.get("from_player"), msg.get("state") or {})
            elif kind in ("PlayerDisconnected", "PlayerLeft") and msg.get("username") == (self.human or self.last_human):
                self._human_gone()
            elif kind == "PlayerConnected" and msg.get("username") == (self.human or self.last_human):
                self._human_back()
            elif kind == "Error":
                print(f"  relay error: {msg.get('code')}: {msg.get('message')}", flush=True)
                if msg.get("code") == "already_in_room" and self.room_id is None and time.time() < getattr(
                        self, "_open_deadline", 0):  # the earlier session's table is still there: try again soon
                    threading.Timer(self.RELAY_RETRY_S, self._retry_create).start()

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
                self.bot_lobby = None
                session.send({"type": "SetDeckSelection", "deck_name": self.bot_deck[0],
                              "deck": _deck(*self.bot_deck), "commander_name": None})
                session.send({"type": "SetReady", "ready": True})
                room = msg.get("room") or {}
                if all(p.get("is_bot") for p in players):  # the table's only seat controls it: restore a Pauper duel
                    if room.get("format") != "Pauper":
                        session.send({"type": "SetFormat", "format": "Pauper"})
                    if room.get("max_players") != 2:
                        session.send({"type": "SetMaxPlayers", "max_players": 2})

    def _maybe_start(self) -> None:
        """Track the person in the room. The relay lets only the room's controller (the first human player) start
        a game, so the person presses Start in the client; GameStarted then readies the session's next game."""
        room = self.room or {}
        humans = [p for p in room.get("players") or [] if not p.get("is_bot") and p.get("username") != HOST_NAME]
        self.human = humans[0]["username"] if humans else None
        if self.human:
            self.last_human = self.human
        if humans:
            self.human_pick = decks.catalog_id(humans[0].get("selected_deck_name"))
            # The bot selects the deck it will really play against this pick, so both lobby decks are true.
            want = self.bot_deck_for(self.human_pick) if self.human_pick else None
            if want and want != self.bot_lobby and getattr(self, "bot", None) is not None:
                self.bot_lobby = want
                self.bot.send({"type": "SetDeckSelection", "deck_name": decks.label(want),
                               "deck": decks.lobby_deck(want), "commander_name": None})
                self.bot.send({"type": "SetReady", "ready": True})

    # -- game ----------------------------------------------------------------------------------------------------

    def next_start(self) -> dict[str, Any]:
        """Block until the person starts a game at the table; returns their pick (a board deck or None)."""
        return self.starts.get()

    def announce(self, text: str) -> None:
        """A line at the top of the play log (the client's log panel and the session's log)."""
        self.hub.announce(text)

    def _envelope(self, body: dict[str, Any]) -> None:
        self.host.send({"type": "BroadcastState", "state": body, "target_player": self.human or self.last_human})

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
        if not game or (self.human or self.last_human) is None or self.order is None:
            return
        if game.get("game_id") == getattr(self, "stale_game", None):
            return
        if self.seats is None or self.seats.human_seat != game.get("seat"):
            person = self.human or self.last_human
            human_index = self.order.index(person) if person in self.order else 0
            bot_index = 1 - human_index
            dealt = self.dealt or {}
            names = {f"player-{human_index}": f"{person} ({dealt.get('human', '?')})",
                     f"player-{bot_index}": f"{self.bot_name} ({dealt.get('bot', '?')})"}
            self.seats = view.Seats(game.get("seat"), f"player-{human_index}", f"player-{bot_index}", names)
            self.sent_log, self.sent_view, self.prompt, self.starter = 0, None, None, None
        observation = state.get("observation")
        over = state.get("game_over")
        if observation:
            winner = None
            if over and over.get("winner"):
                winner = self.seats.pid(over.get("winner"))
            # the seat that took the first turn is the game's own setting, not the first turn this seat saw
            self.starter = (game.get("rules") or {}).get("starting_seat") or "p0"
            gv = view.game_view(observation, self.seats, self.game_id or str(game.get("game_id")),
                                game_over=bool(over), winner=winner, starter=self.starter, terminal=over)
            raw = json.dumps(gv, sort_keys=True)
            if raw != self.sent_view:
                self.sent_view = raw
                self._envelope({"kind": "state", "forPlayer": self.seats.pid(game.get("seat")),
                                "state": {"gameView": gv}})
        log = state.get("log") or []
        # sent_log counts lines ever sent (the hub keeps only its newest lines, so a list length is no cursor).
        fresh, self.sent_log = log_since(log, state.get("log_total", len(log)), self.sent_log)
        for line in fresh:
            self._envelope({"kind": "log", "fromPlayer": HOST_NAME, "entry": {
                "entryType": LOG_TYPES.get(line.get("side"), "info"),
                "message": ("  " if line.get("depth") else "") + str(line.get("text")),
                "timestampMs": int(time.time() * 1000)}})
        pending = state.get("pending")
        if pending and (self.prompt is None or self.prompt["seq"] != pending["seq"]):
            self._send_prompt(pending, observation or {})
        if over and self.game_id and getattr(self, "_ended", None) != game.get("game_id"):
            self._ended = game.get("game_id")
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

    def _on_directive(self, directive: Mapping[str, Any]) -> None:
        """A client-to-engine directive (fire and forget, not tied to a prompt). Concede ends the game now as the
        person's loss; recording, restore and repeat requests are not offered here and are ignored without an error."""
        if directive.get("type") != "concede":
            return
        if self.hub.concede("conceded"):
            print("\n  You conceded: the game is recorded as a loss (conceded). Join the table and press Start "
                  "for the next game.", flush=True)

    # The person's connection: a short drop may come back (the client reconnects), a long one ends the game.
    DISCONNECT_GRACE_S = float(os.environ.get("MANABREW_DISCONNECT_GRACE_S", "90"))

    def _human_gone(self) -> None:
        """The person's socket closed or they left the table while a game was in progress."""
        game = self.hub.game
        if self._grace is not None or self.order is None or game is None or self.hub.game_over is not None:
            return
        print(f"\n  {self.human} disconnected during the game. Waiting {int(self.DISCONNECT_GRACE_S)} s for the "
              f"browser to come back (reload the page and join the table again); then the game is recorded as lost "
              f"(connection_lost) and the next game can start.", flush=True)
        self._grace = threading.Timer(self.DISCONNECT_GRACE_S, self._grace_over, args=(game.get("game_id"),))
        self._grace.daemon = True
        self._grace.start()

    def _grace_over(self, game_id: Any) -> None:
        with self.lock:
            self._grace = None
            if (self.hub.game or {}).get("game_id") == game_id and self.hub.concede("connection_lost"):
                print("\n  The person did not return: the game is recorded as a loss (connection_lost). Join the "
                      "table and press Start for the next game.", flush=True)

    def _human_back(self) -> None:
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None
            print(f"\n  {self.human} is back; the game continues.", flush=True)

    def _on_response(self, sender: str | None, envelope: Mapping[str, Any]) -> None:
        if sender != self.human:
            return
        if envelope.get("kind") == "directive":
            self._on_directive(envelope.get("directive") or {})
            return
        if envelope.get("kind") != "response":
            return
        me = self.seats.pid(self.seats.human_seat) if self.seats else None
        if self.prompt is None:
            # The client keeps its pass button disabled ("waiting") until a new prompt or an error arrives, so a
            # response that finds no open decision is answered with an error instead of being dropped silently.
            self._error(me, "stalePrompt", "no decision is open right now", envelope.get("promptId"))
            return
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
        if how == "answer":
            error = self.hub.answer_with(seq, int(value))
        elif how == "pass_turn":
            error = self.hub.pass_turn(seq, **value)
        else:
            error = self.hub.plan_with(seq, value)
        if error is not None:
            if how == "plan":
                self.fallback_seq = seq
                self.prompt = None  # re-sent as a substep choice on the next pump
            self._error(me, "unknownActionId", error, seq)

    def _error(self, me: str | None, code: str, message: str, prompt_id: Any) -> None:
        self._envelope({"kind": "error", "forPlayer": me, "error": {"code": code, "message": message,
                                                                      "promptId": prompt_id}})
