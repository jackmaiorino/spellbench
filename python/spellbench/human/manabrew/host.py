"""The human seat of a Spellbench session, played through a Manabrew client.

This process is a room host on a Manabrew relay running on this machine (``manabrew-server``, unmodified): it
creates a hosted room, seats the bot through a second relay session, and starts a game when the person who joined
from the client is ready. During the game it sends the person the board (``state`` envelopes with a full
``gameView`` built from the human seat's own observation), the causal play log (``log`` envelopes) and each pending
decision (``prompt`` envelopes), and turns the client's answers into the play server's answers. The bot, the engine
and the session are the ordinary ``spellbench.human`` ones: nothing the bot observes changes.

Priority windows: a window at which the person has nothing but passing and mana abilities is answered by the session
and never sent, so the client's AUTOPASS countdown and its Full control setting have nothing to act on: Full control is
not supported (the person is asked at every window with a real action, and at no other). The client's pass-until and
exhaustStack reach ``Hub.pass_with``; every position at which the stack changed is drawn in order (``Hub.frames``).

The person's seat: a person who leaves the table mid-game concedes at once; one whose connection drops has the table's
reconnect timeout (the same on the relay and here) to come back, and one who goes between the relay's GameStarted and
the arena's first view of the game loses that game when it appears. A lost relay connection ends the session loudly.
An unhandled failure sends the client a fatal envelope and ends the game. The log is held back until the client can
show it, the decision bank is shown beside the person's name, and the deck dealt is said when it is not the pick.

Wire formats: the relay messages and envelopes follow the upstream relay as read at the commit named in NOTICE.md;
the engine-client messages follow the Manabrew protocol documentation (CC-BY-4.0).
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
import traceback
from typing import Any, Mapping

import queue

from ..server import log_since
from ..text import ABILITY_KINDS
from . import decks, prompts, view
from .ws import Closed, WebSocket

HOST_NAME = "spellbench-host"
PROTOCOL_VERSION = 6  # the client lists a table as joinable only when this matches its own protocol version
LOG_TYPES = {"game": "info", "you": "action", "opp": "action"}
RELAY_RECONNECT_MIN_S, RELAY_RECONNECT_MAX_S = 10, 90  # the relay clamps a table's reconnect timeout to this range
# The client's log panel mounts a few seconds after the board (4.5 s measured on a software-rendered browser), so a
# line sent in the first seconds of a game, or just after a reload, can arrive before it exists and be lost.
LOG_MOUNT_WINDOW_S = 8.0
BANK_WARNINGS_S = (600, 300, 120, 60)  # remaining decision bank, in seconds, at which the log says so


class RelayLost(RuntimeError):
    """The connection to the relay was lost: the session cannot go on and ends (see ``Bridge._relay_closed``)."""


def bank_label(left_ms: float | None) -> str:
    """The person's remaining decision bank as it is shown beside their name: whole minutes (rounded up) while there
    are two or more, then minutes and seconds in steps of ten seconds."""
    if left_ms is None:
        return ""
    left = max(0, int(left_ms // 1000))
    if left >= 120:
        return f"{-(-left // 60)} min left"
    return f"{left // 60}:{left % 60 // 10 * 10:02d} left"


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
                 allow_remote: bool = False, on_close=None) -> None:
        self.ws = WebSocket(url, allow_remote=allow_remote)
        self.username = username
        self.on_close = on_close
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
        reason = "the relay closed the connection"
        try:
            while True:
                try:
                    message = json.loads(self.ws.recv())
                except ValueError:  # one unreadable message does not end the connection
                    print(f"relay session {self.username}: a message that is not JSON was ignored", flush=True)
                    continue
                self.on_message(self, message)
        except (Closed, OSError) as exc:
            reason = str(exc) or type(exc).__name__
            print(f"relay session {self.username} closed: {reason}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep the session's reason on the console
            traceback.print_exc()
            reason = f"{type(exc).__name__}: {exc}"
        self.alive = False
        if self.on_close is not None:
            try:
                self.on_close(self, reason)
            except Exception:  # noqa: BLE001
                traceback.print_exc()

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
        self.sent_frames = 0  # the hub's stack-changing positions already drawn (Hub.frames_total)
        self.sent_view: str | None = None
        self.starting = False
        self._grace: threading.Timer | None = None
        self.fallback_seq: int | None = None
        self.resent_seq: int | None = None  # the decision whose block declaration was already asked again
        self._fresh_ids = itertools.count(2_000_000)  # prompt ids of prompts sent again (apart from decision numbers)
        self.starter: str | None = None  # the seat that took the first turn
        # Deck picks: the person's table pick (a board deck, or None), the bot's deck for it, and each started game.
        self.bot_deck_for = bot_deck_for or (lambda deck: deck)
        self.human_pick: str | None = None
        self.bot_lobby: str | None = None
        self.starts: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
        # {"human": deck, "bot": deck, "differs": the person's pick was not dealt} of the game being played
        self.dealt: dict[str, Any] | None = None
        # Lifecycle. ``_gone``: why the person's game ended before the arena's game existed (they left or dropped
        # between the relay's GameStarted and the game's first view); it ends that game when it appears.
        self._gone: str | None = None
        self._closing = False
        self.relay_lost: str | None = None
        self.resume_token: str | None = None  # the relay's token for ResumeRoom (kept, not used: see _relay_closed)
        # Log delivery (see _send_log): until when log lines are held back (a new game's start, a reload).
        self._log_hold_until = 0.0
        # The decision bank (see _bank): the names without the clock, and the warnings already given this game.
        self._name_base: dict[str, str] = {}
        self._bank_warned: set[int] = set()

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
                                    allow_remote=self.allow_remote_relay, on_close=self._relay_closed)
                break
            except RuntimeError as exc:
                if "taken" not in str(exc) or time.time() > deadline:
                    raise
                print(f"  the relay still holds the host seat of the earlier session; trying again ({exc})", flush=True)
                time.sleep(self.RELAY_RETRY_S)
        self._open_deadline = deadline
        self._create_room()
        threading.Thread(target=self._pump, daemon=True, name="manabrew-pump").start()

    def reconnect_timeout_s(self) -> int:
        """The table's reconnect timeout: how long the relay keeps a dropped person's seat (it forfeits it five seconds
        later and tells the room ``PlayerLeft``). It is our own grace period, so the relay and this host agree about
        when a game without its person is over; the relay accepts 10 to 90 s (its default is 60)."""
        return int(min(max(self.DISCONNECT_GRACE_S, RELAY_RECONNECT_MIN_S), RELAY_RECONNECT_MAX_S))

    def _create_room(self) -> None:
        self.host.send({"type": "CreateRoom", "room_name": self.room_name, "max_players": 2, "format": "Pauper",
                        "protocol_version": PROTOCOL_VERSION, "hosted": True, "engine": "Manabrew",
                        "reconnect_timeout_s": self.reconnect_timeout_s()})

    def _retry_create(self) -> None:
        with self.lock:
            if self.room_id is None:
                self._create_room()

    def _on_host(self, session: Session, msg: Mapping[str, Any]) -> None:
        try:
            self._handle_host(session, msg)
        except Exception as exc:  # noqa: BLE001 - a handler's failure ends the game loudly, not the connection quietly
            self._fault(exc)

    def _handle_host(self, session: Session, msg: Mapping[str, Any]) -> None:
        kind = msg.get("type")
        with self.lock:
            if kind == "RoomCreated":
                self.room_id, self.room = msg["room_id"], msg.get("room")
                self.resume_token = msg.get("resume_token")
                print(f"  Manabrew room '{self.room_name}' is open on {self.url}", flush=True)
                # A service session is not listed among the online players and gets no chat (the table still seats it).
                self.bot = Session(self.url, self.key, self.bot_name, service=True, on_message=self._on_bot,
                                   allow_remote=self.allow_remote_relay, on_close=self._relay_closed)
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
                self._gone = None
                self.hub.control("start", {})
            elif kind == "StateUpdate":
                self._on_response(msg.get("from_player"), msg.get("state") or {})
            elif kind in ("PlayerDisconnected", "PlayerLeft") and msg.get("username") == (self.human or self.last_human):
                self._human_gone(left=kind == "PlayerLeft")
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
        try:
            self._handle_bot(session, msg)
        except Exception as exc:  # noqa: BLE001
            self._fault(exc)

    def _handle_bot(self, session: Session, msg: Mapping[str, Any]) -> None:
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
            # The bot selects, as soon as the person is at the table, the deck it will really play: the session
            # decides it from the pick (a pick that is not a training deck, or none, gets the rotation's deck), so
            # its lobby deck is the real one (never the placeholder).
            want = self.bot_deck_for(self.human_pick)
            if want and want != self.bot_lobby and getattr(self, "bot", None) is not None:
                self.bot_lobby = want
                self.bot.send({"type": "SetDeckSelection", "deck_name": decks.label(want),
                               "deck": decks.lobby_deck(want), "commander_name": None})
                self.bot.send({"type": "SetReady", "ready": True})

    # -- game ----------------------------------------------------------------------------------------------------

    def next_start(self) -> dict[str, Any]:
        """Block until the person starts a game at the table; returns their pick (a board deck or None). Raises
        ``RelayLost`` once the relay connection has been lost: the session cannot go on."""
        while True:
            if self.relay_lost:
                raise RelayLost(self.relay_lost)
            try:
                start = self.starts.get(timeout=1.0)
            except queue.Empty:
                continue
            if start is not None:
                return start

    def announce(self, text: str) -> None:
        """A line at the top of the play log (the client's log panel and the session's log)."""
        self.hub.announce(text)

    def _envelope(self, body: dict[str, Any]) -> None:
        self.host.send({"type": "BroadcastState", "state": body, "target_player": self.human or self.last_human})

    def _pump(self) -> None:
        version = -1
        while not self._closing:
            version = self._pump_once(version)

    def _pump_once(self, version: int) -> int:
        """Wait for the play server's next state and send the client what changed. The wait is inside the guarded
        block: whatever fails here ends the game loudly (``_fault``), and the pump goes on with the next one."""
        try:
            wait = 1.0 if time.time() < self._log_hold_until else 5.0  # held log lines go out as soon as the hold ends
            state = self.hub.wait_state(version, timeout=wait, frames_from=self.sent_frames)
            version = state["version"]
            with self.lock:
                self._push(state)
                if state.get("hello_waiting") and self.room is not None:
                    self._maybe_start()
        except Exception as exc:  # noqa: BLE001
            self._fault(exc)
            time.sleep(1.0)
        return version

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
            # The name rows say which deck each side was dealt, and when that is not the person's table pick.
            mark = ", not your pick" if dealt.get("differs") else ""
            names = {f"player-{human_index}": f"{person} ({dealt.get('human', '?')}{mark})",
                     f"player-{bot_index}": f"{self.bot_name} ({dealt.get('bot', '?')})"}
            self.seats = view.Seats(game.get("seat"), f"player-{human_index}", f"player-{bot_index}", names)
            self._name_base = dict(names)
            self.sent_log, self.sent_view, self.prompt, self.starter = 0, None, None, None
            self.sent_frames = 0
            self.resent_seq = None
            self._bank_warned = set()
            self._log_hold_until = time.time() + LOG_MOUNT_WINDOW_S  # see _send_log
            if self._gone is not None:  # the person left between the relay's GameStarted and this game's first view
                reason, self._gone = self._gone, None
                if self.hub.concede(reason):
                    print(f"\n  {person} had left before the game began: it is recorded as a loss ({reason}). Join "
                          f"the table and press Start for the next game.", flush=True)
                return  # the game is over now: the next pump sends the client its end
        observation = state.get("observation")
        over = state.get("game_over")
        self._bank(state, over)
        # Every decision at which the stack changed is drawn, in order, even when the session answered it at once and
        # the engine has moved on: an opponent's spell is on the board before it resolves.
        frames = [] if over else (state.get("frames") or [])[-self.FRAMES_SHOWN:]
        for frame in frames:
            if self._send_view(frame, game, None) and frame is not frames[-1]:
                time.sleep(self.FRAME_GAP_S)
        self.sent_frames = state.get("frames_total", self.sent_frames)
        if observation:
            self._send_view(observation, game, over)
        self._send_log(state, bool(over))
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

    def _send_log(self, state: Mapping[str, Any], over: bool) -> None:
        """Send the log lines the client has not been given. The client's log panel does not exist until a few
        seconds after the board (and again after a reload), and a line that arrives before it is lost, so the lines of
        a game are held for ``LOG_MOUNT_WINDOW_S`` after its first view, or after the client reconnects, or until the
        person's first answer proves the client is up (``_on_response``), or the game ends; then every line since the
        start (the hub's newest 600) goes out once, in order."""
        if not over and time.time() < self._log_hold_until:
            return
        log = state.get("log") or []
        # sent_log counts lines ever sent (the hub keeps only its newest lines, so a list length is no cursor).
        fresh, self.sent_log = log_since(log, state.get("log_total", len(log)), self.sent_log)
        for line in fresh:
            self._envelope({"kind": "log", "fromPlayer": HOST_NAME, "entry": {
                "entryType": LOG_TYPES.get(line.get("side"), "info"),
                "message": ("  " if line.get("depth") else "") + str(line.get("text")),
                "timestampMs": int(time.time() * 1000)}})

    def _bank(self, state: Mapping[str, Any], over: Any) -> None:
        """Show the person's decision bank: the time left beside their name, and a log line when it falls below
        10, 5, 2 and 1 minutes (a spent bank loses the game on time; the protocol has no clock of its own)."""
        clock = state.get("clock") or {}
        remaining = clock.get("remaining_ms")
        if over or remaining is None or self.seats is None:
            return
        left = remaining
        if state.get("pending"):  # the clock of the decision in front of the person is running
            left -= max(0, (state.get("now") or clock.get("at") or 0) - (clock.get("at") or 0))
        pid = self.seats.pid(self.seats.human_seat)
        base = self._name_base.get(pid)
        if base is not None:
            self.seats.names[pid] = f"{base}, {bank_label(left)}"
        due = [t for t in BANK_WARNINGS_S if left <= t * 1000 and t not in self._bank_warned]
        if due:
            self._bank_warned.update(due)
            minutes = min(due) // 60
            self.hub.say(f"Your clock: {minutes} minute{'s' if minutes != 1 else ''} left in your decision bank. "
                         f"When it is spent the game is lost on time.")

    FRAME_GAP_S = 0.2  # between two drawn stack positions, so the client renders each
    FRAMES_SHOWN = 8   # at most this many of the newest (a long run of passes does not delay the next prompt)

    def _send_view(self, observation: Mapping[str, Any], game: Mapping[str, Any], over: Mapping[str, Any] | None) -> bool:
        """Send the board for ``observation`` if it differs from the one last sent; returns whether it was sent."""
        winner = None
        if over and over.get("winner"):
            winner = self.seats.pid(over.get("winner"))
        # the seat that took the first turn is the game's own setting, not the first turn this seat saw
        self.starter = (game.get("rules") or {}).get("starting_seat") or "p0"
        gv = view.game_view(observation, self.seats, self.game_id or str(game.get("game_id")),
                            game_over=bool(over), winner=winner, starter=self.starter, terminal=over)
        raw = json.dumps(gv, sort_keys=True)
        if raw == self.sent_view:
            return False
        self.sent_view = raw
        self._envelope({"kind": "state", "forPlayer": self.seats.pid(game.get("seat")), "state": {"gameView": gv}})
        return True

    def _send_prompt(self, pending: Mapping[str, Any], observation: Mapping[str, Any], *, error: str | None = None,
                     fresh: bool = False) -> None:
        """Send a pending decision as a prompt. ``fresh`` sends it again under a new prompt id (``error``: why the
        answer to the last one was refused, shown by the combat prompt), the way their engines mint one per prompt."""
        if self.fallback_seq == pending["seq"]:
            data, answer = prompts.selection(pending)
        else:
            data, answer = prompts.build(pending, observation, self.seats, error)
        wire_id = next(self._fresh_ids) if fresh else pending["seq"]
        self.prompt = {"seq": pending["seq"], "id": wire_id, "answer": answer, "type": data["type"]}
        me = self.seats.pid(self.seats.human_seat)
        prompt = {"promptId": wire_id, "decidingPlayerId": me, "input": data}
        source = (pending.get("context") or {}).get("source")
        if isinstance(source, Mapping) and source.get("object_id"):
            self._source_of(prompt, source, observation)
        self._envelope({"kind": "prompt", "forPlayer": me, "prompt": prompt})

    def _source_of(self, prompt: dict[str, Any], source: Mapping[str, Any], observation: Mapping[str, Any]) -> None:
        """The card a choice comes from, for the client's card art and casting arrow. A choice is made while its spell
        or ability is on the stack, so the source is looked up there first (``view.find_object``): a spell is the
        card, an ability is its source card (``view.source_card``, built from the name when the card has left the
        board), and the line of its rules text the ability is goes with it when that is certain."""
        found = view.find_object(observation, source["object_id"])
        if not found:
            return
        record, zone = found
        if zone != "stack":
            prompt["sourceCard"] = view.card_dto(record, self.seats, zone)
            return
        card = view.source_card(record, observation, self.seats)
        if card is not None:
            prompt["sourceCard"] = card
        if record.get("stack_kind") in ABILITY_KINDS:
            line = view.ability_line((view.CARDS.get(record.get("card_name") or "") or {}).get("text"),
                                     record.get("stack_kind"), (record.get("source") or {}).get("zone"))
            if line:
                prompt["sourceAbilityText"] = line

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

    def _person(self) -> str:
        return self.human or self.last_human or "the person"

    def _live_game(self) -> bool:
        """The arena's game for the current table start exists and is not over."""
        return self.hub.game is not None and self.hub.game_over is None

    def _human_gone(self, left: bool = False) -> None:
        """The person's socket closed (``left`` False: the relay keeps their seat for the grace period, which this
        host counts too), or they left the table or the relay gave their seat up (``left`` True: the seat is gone
        and nothing can bring the game back, so it ends now). Both count from the relay's GameStarted: a game that
        has not appeared yet (the arena is still starting it) is ended the moment it does."""
        if self.order is None:  # no game has been started at this table (or it has ended)
            return
        if left:
            timed_out = self._grace is not None  # the relay forfeited a seat this host was already waiting for
            self._cancel_grace()
            self._end_person("connection_lost" if timed_out else "conceded")
            return
        if self._grace is not None:
            return
        live = self.hub.game.get("game_id") if self._live_game() else None
        print(f"\n  {self._person()} disconnected {'during the game' if live else 'as the game was starting'}. "
              f"Waiting {int(self.DISCONNECT_GRACE_S)} s for the browser to come back (reload the page); then the "
              f"game is recorded as lost (connection_lost) and the next game can start.", flush=True)
        self._grace = threading.Timer(self.DISCONNECT_GRACE_S, self._grace_over, args=(live,))
        self._grace.daemon = True
        self._grace.start()

    def _cancel_grace(self) -> None:
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None

    def _end_person(self, reason: str) -> None:
        """End the game of a person who is gone, as their loss (``conceded``: they left the table; ``connection_lost``:
        they did not come back). A game the arena has not started yet is ended when its first view appears."""
        if self._live_game():
            if self.hub.concede(reason):
                if reason == "conceded":
                    print(f"\n  {self._person()} left the table during the game: it is recorded as a loss "
                          f"(conceded). Join the table and press Start for the next game.", flush=True)
                else:
                    print("\n  The person did not return: the game is recorded as a loss (connection_lost). Join the "
                          "table and press Start for the next game.", flush=True)
        elif self.order is not None:
            self._gone = reason
            print(f"\n  {self._person()} is gone before the game began: it will be recorded as a loss ({reason}) "
                  f"as soon as it starts.", flush=True)

    def _grace_over(self, game_id: Any) -> None:
        with self.lock:
            self._grace = None
            if game_id is not None and (self.hub.game or {}).get("game_id") != game_id:
                return  # another game now: the one this wait was for is over
            if self.order is not None:
                self._end_person("connection_lost")

    def _human_back(self) -> None:
        """The person's client reconnected (the relay's PlayerConnected). A reloaded client has an empty log panel
        (the relay replays the last board and the open decision, not the log), so the log goes out again in full."""
        if self._grace is not None:
            self._cancel_grace()
            print(f"\n  {self._person()} is back; the game continues.", flush=True)
        if self.seats is not None and self.order is not None:
            self.sent_log = 0
            self._log_hold_until = time.time() + LOG_MOUNT_WINDOW_S

    # -- failures ------------------------------------------------------------------------------------------------

    def _fault(self, exc: BaseException) -> None:
        """An unhandled exception in the host: say so on the console, tell the client (a ``fatal`` envelope, which
        its game screen shows with a way back to the lobby), end the room's game and the session's game as a loss
        (``host_fault``; the ledger can only file it as the human seat's forfeit), so the table is usable again."""
        if self._closing or self.relay_lost:
            return  # the session is ending on purpose, or a lost relay (reported loudly) is the cause
        if isinstance(exc, (OSError, Closed)) and hasattr(getattr(self, "host", None), "username"):
            self._relay_closed(self.host, f"{type(exc).__name__}: {exc}")  # a send on a dead connection: the relay
            return
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        with self.lock:
            if self.order is None:
                return  # no game is running: the table is untouched
            message = (f"The Spellbench host hit an internal error ({type(exc).__name__}: {exc}) and ended this "
                       f"game. Leave the game, join the table and press Start to play the next one.")
            print(f"\n  {message}", flush=True)
            live = self._live_game()
            if live:
                self.hub.concede("host_fault")
            try:
                self._envelope({"kind": "fatal", "message": message})
                if live and self.game_id:
                    self.host.send({"type": "EndGame", "game_id": self.game_id})
            except Exception:  # noqa: BLE001 - a dead socket is reported by its own close
                traceback.print_exc()
            if live:
                self.order, self.seats = None, None
            else:
                self._gone = "host_fault"  # the game the arena is starting is ended when it appears

    def _relay_closed(self, session: Session, reason: str) -> None:
        """A relay connection of this session closed: the table, the room and the client's game are gone with it, so
        the session ends loudly instead of waiting for a person nobody can reach (the client freezes and, a minute
        later, blames a player who did not reconnect). The game in progress is ended as a loss (``relay_lost``) so
        the arena finishes it at once, and ``next_start`` raises ``RelayLost``.

        What a full recovery would take (not done): keep ``resume_token`` from ``RoomCreated``; reconnect and
        authenticate under the same host name (the relay holds the seat for ``reconnect_timeout_s`` and a session
        reclaim keeps the room), or after a relay restart send ``ResumeRoom`` with the room's id and token, name,
        player order, deck infos, ``bot_players`` and ``game_id``; seat the bot again; then resend the last board and
        the open prompt (``sent_view = prompt = None``) and the log. That needs a reconnecting WebSocket in ``ws.py``
        and a relay to test against that is killed and restarted mid-game."""
        if self._closing or self.relay_lost:
            return
        self.relay_lost = f"the relay connection of {session.username} was lost ({reason})"
        bar = "=" * 78
        print(f"\n{bar}\n  RELAY LOST: {self.relay_lost}.\n  The table and the client's game are gone. This session "
              f"is ending; start it again.\n{bar}", flush=True)
        with self.lock:
            self._cancel_grace()
            if self._live_game() and self.hub.concede("relay_lost"):
                print("  The game in progress is recorded as a loss (relay_lost).", flush=True)
        self.starts.put(None)

    def close(self) -> None:
        """Stop the pump and close the relay connections (the session is ending on purpose)."""
        self._closing = True
        self._cancel_grace()
        for name in ("host", "bot"):
            session = getattr(self, name, None)
            if session is not None and hasattr(session, "ws"):
                session.ws.close()

    def _on_response(self, sender: str | None, envelope: Mapping[str, Any]) -> None:
        if sender != (self.human or self.last_human):  # a table update without the person clears self.human; their
            return                                      # answers are still theirs (as for the board and prompts)
        if envelope.get("kind") == "directive":
            self._on_directive(envelope.get("directive") or {})
            return
        if envelope.get("kind") != "response":
            return
        self._log_hold_until = 0.0  # the client answered, so its log panel exists: held log lines go out (_send_log)
        me = self.seats.pid(self.seats.human_seat) if self.seats else None
        if self.prompt is None:
            # The client keeps its pass button disabled ("waiting") until a new prompt or an error arrives, so a
            # response that finds no open decision is answered with an error instead of being dropped silently.
            self._error(me, "stalePrompt", "no decision is open right now", envelope.get("promptId"))
            return
        if envelope.get("promptId") != self.prompt.get("id", self.prompt["seq"]):
            self._error(me, "stalePrompt", "that prompt is no longer open", envelope.get("promptId"))
            return
        action = envelope.get("action") or {}
        wrapped = isinstance(action.get("output"), Mapping)
        output = action["output"] if wrapped else action
        if wrapped and isinstance(action.get("type"), str) and action["type"] != self.prompt["type"]:
            self._error(me, "wrongPromptType", "response output does not match the prompt type",
                        envelope.get("promptId"))
            return
        try:
            how, value = self.prompt["answer"](output)
        except (ValueError, TypeError, KeyError) as exc:  # Rejected carries its protocol code
            self._error(me, getattr(exc, "code", "invalidShape"), str(exc), envelope.get("promptId"))
            return
        seq = self.prompt["seq"]
        if how == "answer":
            error = self.hub.answer_with(seq, int(value))
        elif how == "pass":  # a pass with the client's pass-until and exhaustStack (prompts.hold_target)
            error = self.hub.pass_with(seq, value["until"], exhaust_stack=value["exhaust_stack"])
        else:
            error = self.hub.plan_with(seq, value)
        if error is not None:
            pending = self.hub.pending
            if (how == "plan" and self.prompt["type"] == "chooseBlockers" and self.resent_seq != seq
                    and pending is not None and pending["seq"] == seq):
                # The engine refused a block the prompt allowed. Ask for the whole declaration again, under a new
                # prompt id with the reason, instead of switching to the one-by-one choice (asked only if that fails).
                self.resent_seq = seq
                self._send_prompt(pending, self.hub.observation or {}, fresh=True, error=(
                    "That block is not allowed: a blocker cannot block that attacker. Choose the blocks again."))
                return
            if how == "plan":
                self.fallback_seq = seq
                self.prompt = None  # re-sent as a substep choice on the next pump
            self._error(me, "unknownActionId", error, seq)

    def _error(self, me: str | None, code: str, message: str, prompt_id: Any) -> None:
        self._envelope({"kind": "error", "forPlayer": me, "error": {"code": code, "message": message,
                                                                      "promptId": prompt_id}})
