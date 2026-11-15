"""The Manabrew host's lifecycle: leaving and dropping, a lost relay, the log's delivery, failures, decks and the clock."""

from __future__ import annotations

import json
import random
import socket
import struct
import threading
import time
from typing import Any

import pytest

from spellbench.human import session
from spellbench.human.manabrew import decks, host as manabrew_host, view
from spellbench.human.manabrew.host import Bridge, RelayLost, bank_label
from spellbench.human.server import Hub

from test_human_manabrew import ME, OPP, StubRelay, bridge_in_game, observation

PERSON = {"type": "PlayerLeft", "room_id": "r", "username": "human"}


def sent_kinds(bridge: Bridge) -> list[str]:
    return [m["state"]["kind"] for m in bridge.host.sent if m.get("type") == "BroadcastState"]


def log_lines(bridge: Bridge) -> list[str]:
    return [m["state"]["entry"]["message"] for m in bridge.host.sent if m.get("state", {}).get("kind") == "log"]


def end_game_sent(bridge: Bridge, game_id: str = "g-1") -> bool:
    return {"type": "EndGame", "game_id": game_id} in bridge.host.sent


def bridge_before_the_game(hub: Hub | None = None) -> Bridge:
    """The relay has said GameStarted for a game the arena has not begun: the order is known, no game is live."""
    bridge = Bridge(hub or Hub(opponent="Basilisk 2"), relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room",
                    bot_name="Basilisk 2", bot_deck=("Rally", []))
    bridge.host = StubRelay()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-2"
    return bridge


def start_arena_game(hub: Hub, game_id: str) -> None:
    hub.game_start({"game_id": game_id, "seat": ME, "own_deck": {"name": "Wildfire"}, "opponent_deck": {"name": "Rally"}})


# -- item 5: leaving the table is a concession at once; the table's reconnect timeout is ours -----------------------------


def test_leaving_the_table_during_a_game_is_a_concession_at_once(capsys) -> None:
    bridge = bridge_in_game()
    started = time.monotonic()
    bridge._on_host(None, PERSON)  # the relay's PlayerLeft: no PlayerDisconnected before it, so the person chose to go
    assert time.monotonic() - started < 1.0 and bridge._grace is None
    hub = bridge.hub
    assert hub.game_over["reason"] == "conceded" and hub.game_over["winner"] == OPP
    assert hub.results[-1]["result"] == "loss"
    bridge._push(hub.state())
    assert end_game_sent(bridge) and bridge.order is None
    out = capsys.readouterr().out
    assert "left the table" in out and "conceded" in out and "press Start" in out


def test_the_relay_giving_up_a_dropped_seat_is_a_lost_connection() -> None:
    bridge = bridge_in_game()
    bridge.DISCONNECT_GRACE_S = 60
    bridge._on_host(None, {"type": "PlayerDisconnected", "username": "human"})
    assert bridge._grace is not None
    bridge._on_host(None, PERSON)  # the relay forfeited the seat before this host's own wait was over
    assert bridge._grace is None
    assert bridge.hub.game_over["reason"] == "connection_lost"


def test_a_player_who_is_not_the_person_leaving_changes_nothing() -> None:
    bridge = bridge_in_game()
    bridge._on_host(None, {**PERSON, "username": "Basilisk 2"})
    assert bridge.hub.game_over is None


def test_a_departure_after_the_game_has_ended_is_ignored() -> None:
    bridge = bridge_in_game()
    bridge.hub.concede("conceded")
    bridge._push(bridge.hub.state())  # EndGame; the table is between games
    bridge.host.sent.clear()
    bridge._on_host(None, PERSON)
    assert bridge.host.sent == [] and bridge._gone is None


@pytest.mark.parametrize("grace, expected", [(90.0, 90), (60.0, 60), (5.0, 10), (500.0, 90)])
def test_the_table_is_created_with_the_reconnect_timeout_of_this_host(grace, expected) -> None:
    bridge = bridge_in_game()
    bridge.DISCONNECT_GRACE_S = grace  # the relay accepts 10 to 90 s and forfeits a dropped seat 5 s after that
    bridge.host.sent.clear()
    bridge._create_room()
    [created] = bridge.host.sent
    assert created["type"] == "CreateRoom" and created["reconnect_timeout_s"] == expected


# -- item 6: leaving between the relay's GameStarted and the arena's game_start -------------------------------------------


def test_leaving_before_the_game_begins_ends_it_when_it_appears(capsys) -> None:
    bridge = bridge_before_the_game()
    bridge._on_host(None, PERSON)  # the arena has no game yet
    assert bridge._gone == "conceded" and bridge.hub.game is None
    start_arena_game(bridge.hub, "g-2")
    bridge.game_id = "g-2"
    bridge._push(bridge.hub.state())  # the game's first view
    assert bridge.hub.game_over["reason"] == "conceded" and bridge._gone is None
    bridge._push(bridge.hub.state())
    assert end_game_sent(bridge, "g-2") and bridge.order is None
    assert "before the game began" in capsys.readouterr().out


def test_leaving_before_a_second_game_begins_ends_that_game_not_the_last_one() -> None:
    bridge = bridge_in_game()
    bridge.hub.concede("conceded")
    bridge._push(bridge.hub.state())  # game 1 over and ended at the relay
    bridge.order, bridge.seats, bridge.game_id = ["human", "Basilisk 2"], None, "g-2"
    bridge.stale_game = "g-1"
    bridge._on_host(None, PERSON)  # the hub still shows game 1, which is over: no live game
    assert bridge._gone == "conceded"
    start_arena_game(bridge.hub, "g-2")
    bridge._push(bridge.hub.state())
    assert bridge.hub.game_over["reason"] == "conceded" and bridge.hub.game["game_id"] == "g-2"
    assert [r["game_id"] for r in bridge.hub.results] == ["g-1", "g-2"]


def test_a_drop_before_the_game_begins_is_lost_after_the_grace_period_unless_the_person_returns() -> None:
    bridge = bridge_before_the_game()
    bridge.DISCONNECT_GRACE_S = 0.1
    bridge._on_host(None, {"type": "PlayerDisconnected", "username": "human"})
    deadline = time.time() + 5
    while bridge._gone is None and time.time() < deadline:
        time.sleep(0.02)
    assert bridge._gone == "connection_lost"
    again = bridge_before_the_game()
    again.DISCONNECT_GRACE_S = 0.2
    again._on_host(None, {"type": "PlayerDisconnected", "username": "human"})
    again._on_host(None, {"type": "PlayerConnected", "username": "human"})
    time.sleep(0.5)
    assert again._gone is None


def test_a_game_that_starts_while_the_person_is_still_away_is_lost_when_the_grace_ends() -> None:
    bridge = bridge_before_the_game()
    bridge.DISCONNECT_GRACE_S = 0.3
    bridge._on_host(None, {"type": "PlayerDisconnected", "username": "human"})
    start_arena_game(bridge.hub, "g-2")
    deadline = time.time() + 5
    while bridge.hub.game_over is None and time.time() < deadline:
        time.sleep(0.02)
    assert bridge.hub.game_over["reason"] == "connection_lost"


# -- item 7: a lost relay connection ends the session loudly ---------------------------------------------------------------


class FakeRelay:
    """A relay on a socket on this machine that answers just enough of the host's conversation, for a real
    ``Session`` to connect to; ``drop()`` closes every connection."""

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.url = f"ws://127.0.0.1:{self.server.getsockname()[1]}"
        self.received: list[dict[str, Any]] = []
        self.connections: list[socket.socket] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connections.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _frame(text: str) -> bytes:
        payload = text.encode()
        n = len(payload)
        head = bytes([0x81, n]) if n < 126 else bytes([0x81, 126]) + struct.pack(">H", n)
        return head + payload

    @staticmethod
    def _read(conn: socket.socket, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise OSError("closed")
            data += chunk
        return data

    def _serve(self, conn: socket.socket) -> None:
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(4096)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            while True:
                b0, b1 = self._read(conn, 2)
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._read(conn, 2))[0]
                mask = self._read(conn, 4)
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read(conn, n)))
                if b0 & 0x0F != 0x1:
                    continue
                message = json.loads(payload)
                self.received.append(message)
                if message["type"] == "Authenticate":
                    conn.sendall(self._frame(json.dumps({"type": "AuthResult", "success": True,
                                                         "player_id": message["username"]})))
                elif message["type"] == "CreateRoom":
                    conn.sendall(self._frame(json.dumps({"type": "RoomCreated", "room_id": "room-1", "room_name": "R",
                                                         "room": {"players": [], "status": "Lobby"},
                                                         "resume_token": "token-1"})))
        except OSError:
            return

    def drop(self) -> None:
        for conn in self.connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self.drop()
        self.server.close()


def test_a_lost_relay_connection_ends_the_session_loudly_within_seconds(capsys) -> None:
    relay = FakeRelay()
    hub = Hub(opponent="Basilisk 2")
    bridge = Bridge(hub, relay_url=relay.url, relay_key="k", room_name="Room", bot_name="Basilisk 2", bot_deck=("d", []))
    try:
        bridge.start()
        deadline = time.time() + 5
        while bridge.resume_token is None and time.time() < deadline:
            time.sleep(0.02)
        assert bridge.resume_token == "token-1"
        deadline = time.time() + 5
        while sum(m["type"] == "Authenticate" for m in relay.received) < 2 and time.time() < deadline:
            time.sleep(0.02)
        auths = [m for m in relay.received if m["type"] == "Authenticate"]
        assert sorted((m["username"], m["service"]) for m in auths) == [("Basilisk 2", True), ("spellbench-host", True)]
        create = next(m for m in relay.received if m["type"] == "CreateRoom")
        assert create["reconnect_timeout_s"] == 90
        hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "A"}, "opponent_deck": {"name": "B"}})
        bridge.order = ["human", "Basilisk 2"]
        started = time.monotonic()
        relay.drop()
        deadline = time.time() + 5
        while bridge.relay_lost is None and time.time() < deadline:
            time.sleep(0.02)
        assert bridge.relay_lost is not None and time.monotonic() - started < 3.0
        assert hub.game_over["reason"] == "relay_lost"  # the game in progress ends at once
        with pytest.raises(RelayLost, match="relay connection"):
            bridge.next_start()
        out = capsys.readouterr().out
        assert "RELAY LOST" in out and "This session is ending" in out and "relay_lost" in out
    finally:
        bridge.close()
        relay.close()


def test_next_start_returns_a_start_and_raises_once_the_relay_is_lost() -> None:
    bridge = bridge_in_game()
    bridge.starts.put({"human_pick": "Burn"})
    assert bridge.next_start() == {"human_pick": "Burn"}
    threading.Timer(0.2, lambda: bridge._relay_closed(type("S", (), {"username": "spellbench-host"})(), "boom")).start()
    with pytest.raises(RelayLost, match="boom"):
        bridge.next_start()


# -- item 14: the log reaches a client whose panel did not exist yet --------------------------------------------------------


def new_game_bridge() -> Bridge:
    bridge = bridge_in_game()
    bridge.seats = None  # the game's first view creates the seats and holds the log back
    bridge.dealt = {"human": "Wildfire", "bot": "Rally", "differs": False}
    return bridge


def test_the_opening_lines_are_held_until_the_client_can_show_them() -> None:
    bridge = new_game_bridge()
    opening = [line["text"] for line in bridge.hub.log]
    assert opening
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == []  # the panel is not there yet
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == []
    bridge._on_response("human", {"kind": "response", "promptId": 99})  # the person answers: the client is up
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == opening
    bridge.hub.say("a later line")
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == opening + ["a later line"]  # then every line goes out once, as it comes


def test_held_lines_go_out_when_the_mount_window_has_passed() -> None:
    bridge = new_game_bridge()
    opening = [line["text"] for line in bridge.hub.log]
    bridge._push(bridge.hub.state())
    assert bridge._log_hold_until > time.time() + 1  # held for the mount window
    bridge._log_hold_until = time.time() - 0.01
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == opening


def test_the_end_of_a_game_releases_the_held_lines() -> None:
    bridge = new_game_bridge()
    bridge._push(bridge.hub.state())
    bridge.hub.concede("conceded")
    bridge._push(bridge.hub.state())
    assert log_lines(bridge)[-1].startswith("Game over")


def test_a_reconnecting_client_gets_the_whole_log_again_once_its_panel_can_show_it() -> None:
    bridge = bridge_in_game()
    for n in range(5):
        bridge.hub.say(f"line {n}")
    bridge._push(bridge.hub.state())
    first = log_lines(bridge)
    assert len(first) == 6  # the game line and five more
    bridge.host.sent.clear()
    bridge._on_host(None, {"type": "PlayerConnected", "username": "human"})  # the page was reloaded
    assert bridge.sent_log == 0 and bridge._log_hold_until > time.time() + 1
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == []  # its panel does not exist yet
    bridge._log_hold_until = 0.0
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == first
    bridge._push(bridge.hub.state())
    assert log_lines(bridge) == first  # and only once


def test_a_person_who_comes_back_between_games_changes_nothing() -> None:
    bridge = bridge_in_game()
    bridge.order, bridge.seats = None, None
    bridge._on_host(None, {"type": "PlayerConnected", "username": "human"})
    assert bridge._log_hold_until == 0.0


# -- item 22: a failure ends the game loudly -------------------------------------------------------------------------------


def test_an_exception_in_the_push_sends_a_fatal_envelope_and_ends_the_game(monkeypatch, capsys) -> None:
    bridge = bridge_in_game()
    bridge.hub.observation = observation()

    def broken(*args, **kwargs):
        raise KeyError("zones")

    monkeypatch.setattr(view, "game_view", broken)
    version = bridge._pump_once(-1)
    assert version >= 0
    fatal = [m["state"] for m in bridge.host.sent if m.get("state", {}).get("kind") == "fatal"]
    assert len(fatal) == 1 and "KeyError" in fatal[0]["message"] and "press Start" in fatal[0]["message"]
    assert end_game_sent(bridge) and bridge.order is None
    assert bridge.hub.game_over["reason"] == "host_fault" and bridge.hub.results[-1]["result"] == "loss"
    assert "internal error" in capsys.readouterr().out
    monkeypatch.undo()
    assert bridge._pump_once(version) >= version  # the pump goes on: nothing left to push


def test_a_failure_of_the_wait_itself_is_guarded_too(monkeypatch) -> None:
    bridge = bridge_in_game()
    bridge.order, bridge.seats = None, None  # no game running: only the traceback, the table is untouched
    monkeypatch.setattr(bridge.hub, "wait_state", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wait failed")))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert bridge._pump_once(4) == 4
    assert bridge.host.sent == []


def test_a_send_on_a_dead_relay_connection_is_reported_as_a_lost_relay(capsys) -> None:
    bridge = bridge_in_game()
    bridge.host = type("Dead", (), {"username": "spellbench-host", "send": lambda self, m: (_ for _ in ()).throw(
        ConnectionResetError("reset"))})()
    bridge._fault(ConnectionResetError("reset"))  # the pump found the connection dead before its reader did
    assert bridge.relay_lost and "reset" in bridge.relay_lost
    assert bridge.hub.game_over["reason"] == "relay_lost"
    assert "RELAY LOST" in capsys.readouterr().out


def test_an_exception_in_a_relay_handler_is_not_silent(capsys) -> None:
    bridge = bridge_in_game()
    bridge._on_host(None, {"type": "RoomUpdate", "room": 5})  # not a room: the handler fails
    assert end_game_sent(bridge) and bridge.hub.game_over["reason"] == "host_fault"
    assert "internal error" in capsys.readouterr().out


def test_a_failure_before_the_arena_game_exists_ends_it_when_it_appears() -> None:
    bridge = bridge_before_the_game()
    bridge._fault(RuntimeError("early"))
    assert bridge._gone == "host_fault"
    start_arena_game(bridge.hub, "g-2")
    bridge._push(bridge.hub.state())
    assert bridge.hub.game_over["reason"] == "host_fault"


# -- item 26: the deck dealt and the deck in the lobby ---------------------------------------------------------------------


def test_the_bots_random_deck_is_drawn_once_per_game_and_matches_the_old_draw_order() -> None:
    order = list(decks.ORDER)
    plan = session.DeckPlan(["Wildfire", "Rally"], "random", order, random.Random("s:opponent-deck"))
    same = random.Random("s:opponent-deck")
    expected = [same.choice(order) for _ in range(4)]
    assert plan.bot("Wildfire", 0) == plan.bot("Rally", 0) == expected[0]  # the lobby asks, then the game asks
    assert [plan.bot("Wildfire", n) for n in (1, 2, 3, 3, 2)] == [expected[1], expected[2], expected[3], expected[3],
                                                                   expected[2]]


def test_the_plan_deals_the_pick_or_the_rotation_and_the_bot_mirrors_or_keeps_its_deck() -> None:
    rotation = ["Wildfire", "Rally", "Elves"]
    mirror = session.DeckPlan(rotation, "mirror", list(decks.ORDER), random.Random(0))
    assert mirror.human("Burn", 5) == "Burn" and mirror.human(None, 4) == "Rally"
    assert mirror.bot(mirror.human(None, 4), 4) == "Rally"  # a pick that is no training deck: the rotation's, mirrored
    fixed = session.DeckPlan(rotation, "Spy", list(decks.ORDER), random.Random(0))
    assert fixed.bot("Burn", 0) == "Spy"


def test_a_pick_that_is_not_dealt_is_announced() -> None:
    assert session.pick_note({"human_pick": "Burn", "picked_name": "Burn"}, "Burn") == ""
    note = session.pick_note({"human_pick": None, "picked_name": "My Own Deck"}, "Rally")
    assert "My Own Deck" in note and "not a training deck" in note and "dealt Rally" in note
    assert "no training deck" in session.pick_note({"human_pick": None, "picked_name": None}, "Rally")
    assert chr(0x2014) not in note


def test_the_bots_lobby_deck_is_the_deck_it_will_play_for_any_pick() -> None:
    bridge = bridge_in_game()
    bridge.bot = StubRelay()
    plan = session.DeckPlan(["Wildfire", "Rally"], "mirror", list(decks.ORDER), random.Random(0))
    bridge.bot_deck_for = lambda pick: plan.bot(plan.human(pick, 0), 0)
    bridge.room = {"players": [{"username": "human", "is_bot": False, "selected_deck_name": "My Own Deck"}]}
    bridge._maybe_start()
    [select, ready] = bridge.bot.sent
    assert select["type"] == "SetDeckSelection" and select["deck_name"] == decks.label("Wildfire")  # not the placeholder
    assert ready == {"type": "SetReady", "ready": True}
    bridge.room = {"players": [{"username": "human", "is_bot": False,
                                "selected_deck_name": decks.label("Burn")}]}
    bridge._maybe_start()
    assert bridge.bot.sent[-2]["deck_name"] == decks.label("Burn")  # a training pick: mirrored


def test_the_name_row_says_when_the_deck_is_not_the_persons_pick() -> None:
    bridge = new_game_bridge()
    bridge.dealt = {"human": "Rally", "bot": "Rally", "differs": True}
    bridge._push(bridge.hub.state())
    assert bridge.seats.names["player-0"] == "human (Rally, not your pick)"
    bridge = new_game_bridge()
    bridge._push(bridge.hub.state())
    assert bridge.seats.names["player-0"] == "human (Wildfire)"


# -- item 27: the decision bank is visible ---------------------------------------------------------------------------------


def test_bank_label() -> None:
    assert bank_label(None) == ""
    assert bank_label(30 * 60_000) == "30 min left"
    assert bank_label(9 * 60_000 + 1000) == "10 min left"  # whole minutes, rounded up
    assert bank_label(120_000) == "2 min left"
    assert bank_label(119_000) == "1:50 left" and bank_label(65_000) == "1:00 left" and bank_label(9_999) == "0:00 left"
    assert bank_label(-5) == "0:00 left"


def test_the_bank_shows_beside_the_name_and_warns_at_ten_five_two_and_one_minutes() -> None:
    bridge = new_game_bridge()
    hub = bridge.hub
    bridge._push(hub.state())
    base = bridge._name_base["player-0"]

    def tick(left_ms: int, *, deciding: bool = False) -> list[str]:
        hub.clock = {"remaining_ms": left_ms, "max_decision_ms": 1, "at": int(time.time() * 1000)}
        hub.pending = {"seq": 1} if deciding else None
        bridge._push(hub.state())
        return [line["text"] for line in hub.log if line["text"].startswith("Your clock")]

    assert tick(25 * 60_000) == []
    assert bridge.seats.names["player-0"] == f"{base}, 25 min left"
    assert len(tick(9 * 60_000 + 59_000)) == 1  # under 10 minutes
    assert len(tick(9 * 60_000)) == 1  # not again
    lines = tick(4 * 60_000)
    assert len(lines) == 2 and "5 minutes" in lines[-1]
    lines = tick(100_000)
    assert len(lines) == 3 and "2 minutes" in lines[-1]
    assert bridge.seats.names["player-0"] == f"{base}, 1:40 left"
    lines = tick(55_000)
    assert len(lines) == 4 and "1 minute left" in lines[-1] and "lost on time" in lines[-1]
    assert len(tick(10_000)) == 4  # each warning once


def test_a_bank_that_is_already_low_gives_one_warning_for_the_lowest_threshold() -> None:
    bridge = new_game_bridge()
    hub = bridge.hub
    bridge._push(hub.state())
    hub.clock = {"remaining_ms": 50_000, "max_decision_ms": 1, "at": int(time.time() * 1000)}
    bridge._push(hub.state())
    lines = [line["text"] for line in hub.log if line["text"].startswith("Your clock")]
    assert len(lines) == 1 and "1 minute left" in lines[0]


def test_the_clock_of_the_decision_in_front_of_the_person_keeps_running() -> None:
    bridge = new_game_bridge()
    hub = bridge.hub
    bridge._push(hub.state())
    base = bridge._name_base["player-0"]
    hub.clock = {"remaining_ms": 11 * 60_000, "max_decision_ms": 1, "at": int(time.time() * 1000) - 90_000}
    hub.pending = {"seq": 1}  # the person has been deciding for 90 s
    bridge._push(hub.state())
    assert bridge.seats.names["player-0"] == f"{base}, 10 min left"  # 9.5 minutes, rounded up
    assert any(line["text"].startswith("Your clock: 10 minutes") for line in hub.log)


def test_the_bank_is_not_shown_once_the_game_is_over() -> None:
    bridge = new_game_bridge()
    hub = bridge.hub
    bridge._push(hub.state())
    hub.concede("conceded")
    hub.clock = {"remaining_ms": 30_000, "max_decision_ms": 1, "at": int(time.time() * 1000)}
    bridge._push(hub.state())
    assert not any(line["text"].startswith("Your clock") for line in hub.log)


# -- cosmetic: the bot is a service session --------------------------------------------------------------------------------


def test_the_bot_joins_as_a_service_session(monkeypatch) -> None:
    made: list[dict[str, Any]] = []

    class Recorder(StubRelay):
        def __init__(self, url, key, username, **kwargs) -> None:
            super().__init__()
            self.username = username
            made.append({"username": username, **kwargs})

    monkeypatch.setattr(manabrew_host, "Session", Recorder)
    bridge = bridge_in_game()
    bridge._on_host(None, {"type": "RoomCreated", "room_id": "r1", "room": {}, "resume_token": "t"})
    [bot] = made
    assert bot["username"] == "Basilisk 2" and bot["service"] is True
    assert bridge.resume_token == "t" and bridge.bot.sent == [{"type": "JoinRoom", "room_id": "r1", "as_bot": True}]


# -- the session's records ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["conceded", "connection_lost", "relay_lost", "host_fault"])
def test_a_game_the_session_ended_is_filed_with_its_reason_when_the_ledger_has_a_forfeit(reason) -> None:
    final = {"game_id": "g", "reason": reason, "result": "loss", "seat": ME}
    assert session.person_end(final, {"classification": "forfeit", "winner": OPP}) == reason
    assert session.person_end(dict(final), None) == reason
    natural = dict(final)  # the engine had already ended it: the ledger's natural result stands
    assert session.person_end(natural, {"classification": "natural", "winner": ME, "reason": "game_over"}) is None
    assert natural["reason"] == "game_over" and natural["result"] == "win"
