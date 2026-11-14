"""The Manabrew adapter: gameView from the human seat's observation, prompts from pending decisions, answers back."""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path

import pytest

from spellbench.human import relay
from spellbench.human.manabrew import prompts, view
from spellbench.human.manabrew.host import Bridge
from spellbench.human.server import Hub, make_server

from arena_helpers import builtin, ledger_rows, make_config, roomy_machine, run, subprocess_bot

ME, OPP = "p0", "p1"


def card(oid, name, seat, zone, *, types=("creature",), power=2, toughness=2, tapped=False, **permanent):
    entry = {"object_id": oid, "card_name": name, "full_name": name, "owner_seat": seat, "controller_seat": seat,
             "zone": zone, "token": False, "copy": False, "face_down": False,
             "characteristics": {"colors": ["red"], "keywords": [], "mana_value": 1, "power": power,
                                 "toughness": toughness, "subtypes": [], "supertypes": [], "types": list(types)}}
    if zone == "battlefield":
        entry["permanent"] = {"tapped": tapped, "attacking": False, "blocking": False, "blocked_attackers": [],
                              "counters": {}, "damage": 0, "summoning_sick": False, "attached_to": None, **permanent}
    return entry


def observation():
    return {"turn": 3, "active_seat": ME, "priority_seat": ME, "phase_step": "precombat_main", "stack": [],
            "players": [
                {"seat": ME, "life": 20, "hand": [card("h1", "Lightning Bolt", ME, "hand", types=("instant",))],
                 "hand_count": 1, "library_count": 50, "battlefield": [card("b1", "Krark-Clan Shaman", ME,
                                                                             "battlefield", power=1, toughness=1)],
                 "graveyard": [], "exile": [], "mana_pool": {"R": 1}, "lands_played_this_turn": 0},
                {"seat": OPP, "life": 17, "hand": None, "hand_count": 4, "library_count": 48,
                 "battlefield": [card("o1", "Writhing Chrysalis", OPP, "battlefield", counters={"p1p1": 1})],
                 "graveyard": [], "exile": [], "mana_pool": {}, "lands_played_this_turn": 1}]}


SEATS = view.Seats(ME, "player-1", "player-0", {"player-1": "human", "player-0": "Basilisk 2"})


class GameViewTest(unittest.TestCase):
    def test_view_shows_the_seat_and_hides_the_opponent_hand(self):
        gv = view.game_view(observation(), SEATS, "g1")
        json.dumps(gv)
        zones = {(z["zone"], z["ownerId"]): z for z in gv["zones"]}
        self.assertEqual(zones[("hand", "player-1")]["cards"][0]["identity"]["name"], "Lightning Bolt")
        opp_hand = zones[("hand", "player-0")]
        self.assertEqual(opp_hand["count"], 4)
        self.assertTrue(all(c == {"visibility": "hidden", "id": c["id"]} for c in opp_hand["cards"]))
        self.assertEqual(zones[("library", "player-0")]["cards"], [])
        chrysalis = zones[("battlefield", "player-0")]["cards"][0]
        self.assertEqual(chrysalis["counters"], {"P1P1": 1})
        self.assertIn("Eldrazi", chrysalis["text"])
        self.assertEqual(gv["step"], "main1")
        self.assertEqual(gv["activePlayerId"], "player-1")
        self.assertEqual({p["id"]: p["life"] for p in gv["players"]}, {"player-1": 20, "player-0": 17})


class PromptTest(unittest.TestCase):
    def pending(self, candidates, *, kind="priority", screen="generic", prompt="Your priority"):
        return {"seq": 7, "prompt": prompt, "context": {"kind": kind}, "group": {}, "screen": screen,
                "candidates": [{"id": i, "kind": s["kind"], "text": t, "semantic": s} for i, (s, t) in
                               enumerate(candidates)]}

    def test_priority_is_choose_action(self):
        bolt = {"object_id": "h1", "card_name": "Lightning Bolt", "zone": "hand"}
        pending = self.pending([({"kind": "pass"}, "Pass"), ({"kind": "cast_spell", "source": bolt}, "Cast Lightning Bolt")])
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseAction")
        self.assertEqual(data["actions"], [{"id": "1", "type": "cast", "cardId": "h1", "mode": {"type": "normal"},
                                            "label": "Cast Lightning Bolt"}])
        self.assertEqual(answer({"type": "act", "actionId": "1"}), ("answer", 1))
        self.assertEqual(answer({"type": "pass", "exhaustStack": False}), ("answer", 0))
        with self.assertRaises(ValueError):
            answer({"type": "act", "actionId": "9"})

    def test_targets(self):
        shaman = {"object": {"object_id": "o1", "card_name": "Writhing Chrysalis", "zone": "battlefield"}}
        pending = self.pending([({"kind": "choose_target", "target": shaman}, "Target Writhing Chrysalis"),
                                ({"kind": "choose_target", "target": {"player": OPP}}, "Target opponent")],
                               kind="choice", prompt="Choose a target")
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseBoardTargets")
        self.assertEqual(data["candidates"], [{"kind": "card", "id": "o1"}, {"kind": "player", "id": "player-0"}])
        self.assertEqual(answer({"chosen": [{"kind": "player", "id": "player-0"}]}), ("answer", 1))

    def test_options_say_what_they_do(self):
        pending = self.pending([({"kind": "choose_option", "option_index": 0}, "Leave Swamp on top of your library"),
                                ({"kind": "choose_option", "option_index": 1}, "Put Swamp into your graveyard")],
                               kind="choice", prompt="Explore (Map Token) revealed Swamp")
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseFromSelection")
        self.assertEqual([o["label"] for o in data["options"]],
                         ["Leave Swamp on top of your library", "Put Swamp into your graveyard"])
        self.assertEqual(data["presentation"]["title"], "Explore (Map Token) revealed Swamp")
        self.assertEqual(answer({"chosenIndices": [1]}), ("answer", 1))

    def test_attack_becomes_a_plan(self):
        attacker = {"object_id": "b1", "card_name": "Krark-Clan Shaman"}
        pending = self.pending([({"kind": "declare_attack", "attacker": attacker, "defender": None}, "no attack"),
                                ({"kind": "declare_attack", "attacker": attacker, "defender": {"player": OPP}}, "attack")],
                               kind="choice", screen="attack")
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseAttackers")
        self.assertEqual(data["attackers"][0]["attackerId"], "b1")
        self.assertEqual(answer({"assignments": [{"attackerId": "b1", "targetId": "player-0"}]}),
                         ("plan", {"kind": "attack", "attackers": ["b1"]}))


if __name__ == "__main__":
    unittest.main()


# -- concession, a lost connection and the other directives -------------------------------------------------------------


class StubRelay:
    """Stands in for the host's relay connection: records what the host would send."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, message: dict) -> None:
        self.sent.append(message)


def bridge_in_game(hub: Hub | None = None) -> Bridge:
    hub = hub or Hub(opponent="Basilisk 2")
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Wildfire"}, "opponent_deck": {"name": "Rally"}})
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                    bot_deck=("Rally", []))
    bridge.host = StubRelay()
    bridge.human, bridge.order, bridge.game_id = "human", ["human", "Basilisk 2"], "g-1"
    bridge.seats = view.Seats(ME, "player-0", "player-1", {"player-0": "human", "player-1": "Basilisk 2"})
    return bridge


def directive(kind: str, **fields) -> dict:
    return {"kind": "directive", "fromPlayer": "player-0", "directive": {"type": kind, **fields}}


def test_a_concession_ends_the_game_as_a_loss_and_tells_the_client() -> None:
    bridge = bridge_in_game()
    bridge._on_response("human", directive("concede"))
    hub = bridge.hub
    assert hub.game_over["reason"] == "conceded" and hub.game_over["winner"] == OPP
    assert hub.results == [{"game_id": "g-1", "result": "loss", "reason": "conceded", "own_deck": "Wildfire", "seat": ME}]
    bridge._push(hub.state())  # the pump: the client is told the game is over and the room's game is ended
    kinds = [m["state"]["prompt"]["input"]["type"] for m in bridge.host.sent
             if m.get("state", {}).get("kind") == "prompt"]
    assert kinds == ["gameOver"]
    assert {"type": "EndGame", "game_id": "g-1"} in bridge.host.sent
    assert bridge.order is None  # ready for the next game
    bridge._on_response("human", directive("concede"))  # a second one (the client repeats) changes nothing
    assert len(hub.results) == 1


def test_other_directives_are_ignored_without_an_error() -> None:
    bridge = bridge_in_game()
    for body in (directive("startRecording"), directive("stopRecording"), directive("requestRepeat", iterations=3),
                 directive("repeatVote", voteId=1, accept=True), directive("setSnapshotRecording", enabled=True),
                 directive("requestRestore", checkpointId=1), directive("restoreVote", voteId=1, accept=False)):
        bridge._on_response("human", body)
    assert bridge.host.sent == [] and bridge.hub.game_over is None and bridge.hub.results == []
    bridge._on_response("someone else", directive("concede"))  # only the person at the table can concede
    assert bridge.hub.game_over is None


def test_a_lost_connection_ends_the_game_after_the_grace_period(capsys) -> None:
    bridge = bridge_in_game()
    bridge.DISCONNECT_GRACE_S = 0.1
    bridge._on_host(None, {"type": "PlayerDisconnected", "username": "human"})
    deadline = time.time() + 5
    while bridge.hub.game_over is None and time.time() < deadline:
        time.sleep(0.02)
    assert bridge.hub.game_over["reason"] == "connection_lost"
    assert bridge.hub.results[-1]["result"] == "loss"
    out = capsys.readouterr().out
    assert "disconnected during the game" in out and "connection_lost" in out and "press Start" in out


def test_coming_back_in_time_keeps_the_game() -> None:
    bridge = bridge_in_game()
    bridge.DISCONNECT_GRACE_S = 0.2
    bridge._on_host(None, {"type": "PlayerDisconnected", "username": "human"})
    bridge._on_host(None, {"type": "PlayerConnected", "username": "human"})
    time.sleep(0.5)
    assert bridge.hub.game_over is None
    bridge._on_host(None, {"type": "PlayerDisconnected", "username": "Basilisk 2"})  # not the person: nothing waits
    assert bridge._grace is None


def play_with_a_concession(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str):
    """Two games through the real arena and the human seat's relay. In game 1 the person concedes at ``when``:
    ``decision`` (a decision is open and unanswered), ``thinking`` (none is open: the engine is working on the
    bot's side) or ``prompt`` (a decision that is not a plain priority is open, or the second one if the game has
    none), each through the host's directive handler. Game 2 is played out."""
    roomy_machine(monkeypatch)
    hub = Hub(log_dir=tmp_path / "logs")
    bridge = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Bot",
                    bot_deck=("d", []))
    bridge.host = StubRelay()
    bridge.human = "human"
    server = make_server(hub)
    host, port = server.server_address[:2]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv(relay.URL_ENV, f"http://{host}:{port}")
    monkeypatch.setenv(relay.TOKEN_ENV, server.token)
    stop = threading.Event()
    conceded_at: list[str] = []

    def concede(label: str) -> None:
        bridge._on_response("human", directive("concede"))
        conceded_at.append(label)

    def player() -> None:
        seen = set()
        while not stop.is_set():
            with hub.cond:
                hub.cond.wait(0.02)
                pending, waiting, game = hub.pending, hub.hello_waiting, hub.game
            if waiting:
                hub.control("next", {})
                continue
            first = game is not None and game.get("number") == 1 and hub.game_over is None
            if first and not conceded_at:
                if when == "thinking":
                    if pending is None and hub.observation is not None and seen:
                        concede("thinking")  # a decision was answered, none is open now
                        continue
                elif pending is not None and pending["seq"] not in seen:
                    plain = (pending.get("context") or {}).get("kind") == "priority"
                    if when == "decision" or not plain or len(seen) >= 1:
                        concede(when)
                        continue
            if pending is not None and pending["seq"] not in seen:
                seen.add(pending["seq"])
                if pending["screen"] in ("attack", "block"):
                    hub.plan_with(pending["seq"], {"kind": pending["screen"], "attackers": [], "blocks": {}})
                else:
                    hub.answer_with(pending["seq"], pending["candidates"][-1]["id"])

    threading.Thread(target=player, daemon=True).start()
    human = subprocess_bot("human", [sys.executable, str(Path(relay.__file__).resolve())])
    human["version"] = relay.VERSION
    config = make_config(tmp_path / "run", [human, builtin("uniform", seed=3)], pairs=1, include_self_play=False)
    try:
        summary = run(config)
    finally:
        stop.set()
        server.shutdown()
    return hub, summary, conceded_at


@pytest.mark.parametrize("when", ["decision", "thinking", "prompt"])
def test_a_conceded_game_is_a_recorded_loss_and_the_next_game_completes(tmp_path, monkeypatch, when) -> None:
    hub, summary, conceded_at = play_with_a_concession(tmp_path, monkeypatch, when)
    assert conceded_at, "the person never got a chance to concede"
    assert summary.status == "complete"
    first, second = hub.results[0], hub.results[1]
    assert first["result"] == "loss" and first["reason"] == "conceded"
    assert second["reason"] != "conceded" and second["game_id"] != first["game_id"]  # game 2 was played
    assert len(hub.results) == 2  # the arena's own notice of game 1 did not add a second row
    rows = ledger_rows(tmp_path / "run")
    assert len(rows) == 2
    by_game = {row["game_id"]: row for row in rows}
    ledger_first = by_game[first["game_id"]]
    # The arena can only file the human seat's failure as a forfeit; the session's records say why.
    assert ledger_first["classification"] == "forfeit" and ledger_first["reason"] == "forfeit:agent_error"
    assert ledger_first["winner"] != next(s["seat"] for s in ledger_first["seats"] if s["name"] == "human")
    assert by_game[second["game_id"]]["classification"] == "natural"


def test_a_game_of_a_person_who_has_left_the_room_is_still_ended_at_the_relay() -> None:
    """The relay drops a disconnected person from the room; their game must still be ended so the table reopens."""
    bridge = bridge_in_game()
    bridge._maybe_start()  # nobody in the room: `human` is cleared, `last_human` keeps the name
    bridge.human, bridge.last_human = None, "human"
    bridge.hub.concede("connection_lost")
    bridge._push(bridge.hub.state())
    assert {"type": "EndGame", "game_id": "g-1"} in bridge.host.sent
    assert bridge.order is None


def test_a_response_with_no_open_decision_gets_an_error_so_the_client_unlocks() -> None:
    """The client disables its pass button until a prompt or an error arrives: a stray response must not vanish."""
    bridge = bridge_in_game()
    bridge._on_response("human", {"kind": "response", "fromPlayer": "player-0", "promptId": 4,
                                  "action": {"type": "chooseAction", "output": {"type": "pass", "exhaustStack": False}}})
    [sent] = bridge.host.sent
    assert sent["state"]["kind"] == "error" and sent["state"]["error"]["code"] == "stalePrompt"
    assert sent["state"]["error"]["promptId"] == 4


def test_the_table_is_opened_again_while_the_relay_still_holds_the_earlier_one() -> None:
    bridge = bridge_in_game()
    bridge.room_id, bridge.RELAY_RETRY_S, bridge._open_deadline = None, 0.05, time.time() + 5
    bridge._on_host(None, {"type": "Error", "code": "already_in_room", "message": "Already in room: abc"})
    deadline = time.time() + 2
    while not bridge.host.sent and time.time() < deadline:
        time.sleep(0.02)
    assert bridge.host.sent and bridge.host.sent[0]["type"] == "CreateRoom" and bridge.host.sent[0]["hosted"] is True


# -- the log keeps flowing past the hub's line limit ------------------------------------------------------------------


def log_messages(bridge: Bridge) -> list[str]:
    return [m["state"]["entry"]["message"] for m in bridge.host.sent if m.get("state", {}).get("kind") == "log"]


def test_every_log_line_reaches_a_client_that_joined_at_the_start_once_and_in_order() -> None:
    from spellbench.human.server import LOG_LIMIT
    bridge = bridge_in_game()
    hub = bridge.hub
    expected = [hub.log[0]["text"]]  # the game's first line
    batches = [1, 7, 40, LOG_LIMIT, 3, 250, 1, 599, 600, 5]  # no batch holds more than the hub keeps
    count, turn = 0, 0
    while count < 2000:
        for _ in range(batches[turn % len(batches)]):
            hub._note("you", f"line {count}")
            expected.append(f"line {count}")
            count += 1
        turn += 1
        bridge._push(hub.state())
    assert len(hub.log) == LOG_LIMIT and hub.log_total == len(expected) and len(expected) > 3 * LOG_LIMIT
    assert log_messages(bridge) == expected
    bridge._push(hub.state())  # nothing new: nothing sent again
    assert log_messages(bridge) == expected


def test_a_client_that_joins_late_gets_the_kept_tail_then_every_later_line() -> None:
    from spellbench.human.server import LOG_LIMIT
    hub = Hub(opponent="Basilisk 2")
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Wildfire"}, "opponent_deck": {"name": "Rally"}})
    for n in range(2000):
        hub._note("opp", f"early {n}")
    late = Bridge(hub, relay_url="ws://127.0.0.1:1", relay_key="k", room_name="Room", bot_name="Basilisk 2",
                  bot_deck=("Rally", []))
    late.host = StubRelay()
    late.human, late.order, late.game_id = "human", ["human", "Basilisk 2"], "g-1"
    late.seats = view.Seats(ME, "player-0", "player-1", {"player-0": "human", "player-1": "Basilisk 2"})
    tail = [line["text"] for line in hub.log]
    assert len(tail) == LOG_LIMIT and tail[-1] == "early 1999"
    late._push(hub.state())
    assert log_messages(late) == tail  # the newest lines the hub still has, in order
    later = []
    for n in range(300):
        hub._note("you", f"later {n}")
        later.append(f"later {n}")
        if n % 11 == 0:
            late._push(hub.state())
    late._push(hub.state())
    assert log_messages(late) == tail + later


def test_log_since_counts_lines_ever_appended() -> None:
    from spellbench.human.server import LOG_LIMIT
    hub = Hub()
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "A"}, "opponent_deck": {"name": "B"}})
    for n in range(2000):
        hub._note("you", f"l{n}")
    total = 2001  # the game's first line and 2000 more
    lines, cursor = hub.log_since(0)
    assert cursor == total and len(lines) == LOG_LIMIT and lines[-1]["text"] == "l1999"
    lines, cursor = hub.log_since(total - 10)
    assert [line["text"] for line in lines] == [f"l{n}" for n in range(1990, 2000)] and cursor == total
    assert hub.log_since(total) == ([], total)
    hub.game_start({"game_id": "g-2", "seat": ME, "own_deck": {"name": "A"}, "opponent_deck": {"name": "B"}})
    assert hub.log_total == 1  # a new game restarts the count with its first line


# -- the relay must be on this machine; a concession racing the engine's own end -----------------------------------------


def test_a_relay_that_is_not_on_this_machine_is_refused_unless_allowed() -> None:
    from spellbench.human.manabrew import ws
    for url in ("ws://127.0.0.1:9443", "ws://localhost:9443", "ws://[::1]:9443"):
        ws.require_loopback(url)
    for url in ("ws://192.168.1.20:9443", "ws://relay.example.com:9443", "ws://0.0.0.0:9443"):
        with pytest.raises(ValueError, match="not on this machine"):
            ws.require_loopback(url)
        with pytest.raises(ValueError, match="not on this machine"):
            ws.WebSocket(url)  # refused before any connection is made
        ws.require_loopback(url, allow_remote=True)


def test_the_session_refuses_a_remote_relay_before_starting(tmp_path) -> None:
    from spellbench.human import session
    argv = ["--client", "manabrew", "--relay-url", "ws://192.168.1.20:9443", "--local", str(tmp_path / "local.json"),
            "--out", str(tmp_path / "out")]
    with pytest.raises(SystemExit) as exit_info:
        session.main(argv)
    assert exit_info.value.code == 2 and not (tmp_path / "out").exists()


def test_a_concession_after_the_engine_ended_the_game_leaves_the_ledger_and_the_ends_file_agreeing() -> None:
    """The bot's move ended the game (the ledger files it natural) a moment before the person's concession reached
    the hub, which had not heard yet: the hub's row says conceded. The ledger is the truth; the ends file says nothing."""
    from spellbench.human import session
    won_by_the_bot = {"classification": "natural", "reason": "natural", "winner": OPP}
    row = {"game_id": "g-1", "result": "loss", "reason": "conceded", "seat": ME}
    assert session.person_end(row, won_by_the_bot) is None
    assert row["reason"] == "natural" and row["result"] == "loss"  # the page's row now says what the ledger says
    won_by_the_person = {"classification": "natural", "reason": "natural", "winner": ME}
    row = {"game_id": "g-1", "result": "loss", "reason": "connection_lost", "seat": ME}
    assert session.person_end(row, won_by_the_person) is None
    assert row["result"] == "win" and row["reason"] == "natural"  # the engine had already decided it
    # a real concession: the ledger filed a forfeit, so the ends file records why
    row = {"game_id": "g-1", "result": "loss", "reason": "conceded", "seat": ME}
    assert session.person_end(row, {"classification": "forfeit", "reason": "forfeit:agent_error", "winner": OPP}) == "conceded"
    assert row["reason"] == "conceded"
    assert session.person_end(dict(row), None) == "conceded"  # no ledger row to compare: the hub's word stands
    natural = {"game_id": "g-1", "result": "win", "reason": "natural", "seat": ME}
    assert session.person_end(natural, won_by_the_person) is None and natural["reason"] == "natural"
    assert session.person_end(None, None) is None
