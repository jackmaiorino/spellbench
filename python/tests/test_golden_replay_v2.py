"""Replay the v2 goldens in both roles (spec 16)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.bot import BotSession
from spellbench.conformance import replay_engine_transcript
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.messages import Limits, ResetRequest, Resources, TimeControl

from conftest import ScriptedPeer
from golden_helpers import GOLDENS_V2_DIR, golden_index, load_transcript_v2

TESTS = Path(__file__).resolve().parent
INDEX = golden_index()


def exchanges_by_seat(rows) -> dict[str, list[tuple[dict, dict]]]:
    """(request, answer) per seat: hellos and game_overs go p0 then p1, game_start names its seat, choose its acting seat."""
    pairs: dict[str, list] = {"p0": [], "p1": []}
    hellos = overs = 0
    pending = None
    for direction, message in rows:
        if direction == "host_to_agent":
            kind = message["request_type"]
            if kind == "hello":
                seat, hellos = ("p0", "p1")[hellos], hellos + 1
            elif kind == "game_start":
                seat = message["seat"]
            elif kind == "choose":
                seat = message["decision"]["acting_seat"]
            else:
                seat, overs = ("p0", "p1")[overs], overs + 1
            pending = (seat, message)
        elif direction == "agent_to_host":
            seat, request = pending
            pairs[seat].append((request, message))
    return pairs


def setup_from(rows) -> GameSetup:
    reset = ResetRequest.from_json(next(m for d, m in rows if d == "host_to_engine" and m["request_type"] == "reset"))
    starts = {m["seat"]: m for d, m in rows if d == "host_to_agent" and m["request_type"] == "game_start"}
    first = starts["p0"]
    return GameSetup(game_index=0, game_id=reset.game_id, game_secret_hex=reset.game_secret, format=reset.format,
                     wire_decks=reset.seats, own_decks=(OwnDeck.from_json(starts["p0"]["own_deck"]), OwnDeck.from_json(starts["p1"]["own_deck"])),
                     rules=reset.rules, time_control=TimeControl.from_json(first["time_control"]),
                     limits=Limits.from_json(first["limits"]), resources=Resources.from_json(first["resources"]),
                     agent_seeds=(starts["p0"]["agent_seed"], starts["p1"]["agent_seed"]))


@pytest.mark.parametrize("name", sorted(n for n, entry in INDEX.items() if "host" in entry["roles"]))
def test_the_host_replays_every_game_byte_for_byte(name: str) -> None:
    rows = load_transcript_v2(name)
    engine_peer = ScriptedPeer([wire.canonical_json_dumps(m) for d, m in rows if d == "engine_to_host"])
    engine = EngineProcess(peer=engine_peer)
    engine.hello()
    pairs = exchanges_by_seat(rows)
    peers = {seat: ScriptedPeer([wire.canonical_json_dumps(answer) for _, answer in seat_pairs]) for seat, seat_pairs in pairs.items()}
    seats = {}
    for seat, seat_pairs in pairs.items():
        bot = next(answer["bot"] for request, answer in seat_pairs if request["request_type"] == "hello")
        spec = BotSpec(name=bot["name"], version=bot["version"], type="subprocess", command=("recorded",))
        seats[seat] = SubprocessDriver(spec, startup_ms=30_000, agent_factory=lambda seat=seat: AgentProcess(peer=peers[seat]))
    result = play_game(setup_from(rows), engine=engine, seats=seats, clock_ns=lambda: 0)
    assert engine_peer.sent == [wire.canonical_json_dumps(m) for d, m in rows if d == "host_to_engine"]
    for seat, seat_pairs in pairs.items():
        assert peers[seat].sent == [wire.canonical_json_dumps(request) for request, _ in seat_pairs], seat
    assert result.game_digest == INDEX[name]["game_digest"]


def _sessions(name: str, rows) -> list[list[tuple]]:
    if name.startswith("agent_error_"):
        requests = [m for d, m in rows if d == "host_to_agent"]
        answers = [m for d, m in rows if d == "agent_to_host"]
        return [list(zip(requests, answers))]
    return list(exchanges_by_seat(rows).values())


@pytest.mark.parametrize("name", sorted(n for n, entry in INDEX.items() if "bot_server" in entry["roles"]))
def test_the_bot_server_replays_every_answer_byte_for_byte(name: str) -> None:
    for pairs in _sessions(name, load_transcript_v2(name)):
        hello = next((a for r, a in pairs if isinstance(r, dict) and r.get("request_type") == "hello"), None) or {}
        picks = iter([a["selection"]["candidate_id"] if a["response_type"] == "choice" else 99
                      for r, a in pairs if isinstance(r, dict) and r.get("request_type") == "choose"])
        requires = hello.get("requires", {})
        session = BotSession(choose=lambda decision: next(picks), name=hello.get("bot", {}).get("name", "golden"),
                             version=hello.get("bot", {}).get("version", "1.0.0"),
                             requires_observation=tuple(requires.get("observation", ())),
                             requires_extensions=tuple(requires.get("extensions", ())),
                             extensions_accepted=tuple(hello.get("extensions_accepted", ())))
        for request, answer in pairs:
            line = request.encode("utf-8") if isinstance(request, str) else wire.canonical_json_dumps(request)
            assert session.handle_line(line) == wire.canonical_json_line(answer)


@pytest.mark.parametrize("name", sorted(n for n, entry in INDEX.items() if "engine" in entry["roles"]))
def test_the_fake_engine_replays_every_engine_answer(name: str, tmp_path: Path) -> None:
    entry = INDEX[name]
    argv = [sys.executable, str(TESTS / entry["engine"]), *entry["engine_args"]]
    path = GOLDENS_V2_DIR / name
    rows = load_transcript_v2(name)
    if any(direction not in ("host_to_engine", "engine_to_host") for direction, _ in rows):
        # replay_engine_transcript takes engine rows only, so a game transcript is replayed as its engine subsequence.
        path = tmp_path / name
        view = ({"dir": direction, "message": message} for direction, message in rows if direction in ("host_to_engine", "engine_to_host"))
        path.write_bytes(b"".join(wire.canonical_json_line(row) for row in view))
    assert replay_engine_transcript(argv, path) == []
