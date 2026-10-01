"""X4b: XMage golden transcripts in the spec 16 format, for the arrangement overrides: scry, surveil, library order on
top and on the bottom, and the London mulligan bottom (spec 7.5; design 3.8).

Each golden is one whole game of game 0 of the spec 16 vector run secret (or the first later game the golden's check
accepts), played through P's host (``host.game.play_game``, live validator on) with both seats played in process by
a fixed scripted bot (``BotSession``): all four directions, one canonical JSON line ``{"dir", "message"}`` per message,
and the game digest in ``index.json``. The decks are tiny, so a game ends naturally (a seat draws from an empty
library) within a few turns; every card is named, never hidden behind a catalog id, and the cards beside the one
under test are distinct and uncastable there (a five-mana or off-color card), so a draw tells which card it was.

The scripted bot answers each kind the same way every time: keep (or, in the London golden, mulligan twice), play a
land, else cast the first spell it can, never attack or block, decline every yes/no (no shuffle after Ponder), and in
an arrangement send card 0 to the second destination offered when the golden says so and the rest to the first, then
place items last candidate first (so the order differs from XMage's). A golden is kept only if its check holds: the
block was posed with the expected shape (2n - 1 decisions for an arrangement, Section 7.5) and the cards the seat drew
afterwards came off the library in the placed order (position 0 closest to the top), which is what XMage's inverted
top loop must give.

    PYTHONPATH=<p2>/python python goldens.py generate --out DIR -- <engine argv...>
    PYTHONPATH=<p2>/python python goldens.py check --dir DIR -- <engine argv...>

``check`` replays every golden two ways and exits 1 on any difference: P's engine replay
(``conformance.replay_engine_transcript``: the engine, given each recorded host request, must give each recorded
answer by value), and the whole game again through the host with the same bots, whose rows and digest must equal the
golden's byte for byte.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from spellbench import wire
from spellbench._schema import SEATS
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.bot import BotSession, Decision as BotDecision
from spellbench.conformance import replay_engine_transcript
from spellbench.digests import card_name_domain, deck_id, deck_rows
from spellbench.errors import MalformedJsonError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.messages import DeckRow, Limits, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret

SCHEMA = "spellbench-xmage-goldens/v2"
SECRET = RunSecret(bytes(range(32)))          # spec 16's vector run secret
FORMAT = "standard-2022-25-bo1"
BOT_VERSION = "1.0.0"
TIME_CONTROL = TimeControl(startup_ms=300000, game_start_ms=60000, bank_ms=600000, increment_ms=2000,
                           max_decision_ms=60000, engine_step_ms=300000)
LIMITS = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
                max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)
RESOURCES = Resources(cpus=1, memory_mb=4096, gpu=False, engine_cpus=1)
MAX_GAME_INDEX = 40                           # games of the vector secret tried before giving up on a golden


# ---------------------------------------------------------------------------
# peers (as P's tests/golden_helpers.py, which is not on the package path)
# ---------------------------------------------------------------------------


def _parse(line: bytes) -> Any:
    try:
        return wire.strict_json_loads(line)
    except MalformedJsonError:
        return line.decode("utf-8")


class RecordingPeer:
    def __init__(self, inner: Any, rows: Any, out_dir: str, in_dir: str) -> None:
        self.inner, self.rows, self.out_dir, self.in_dir = inner, rows, out_dir, in_dir

    def write_line(self, payload: bytes) -> None:
        self.inner.write_line(payload)
        self.rows.append((self.out_dir, _parse(payload)))

    def read_line(self) -> bytes:
        line = self.inner.read_line()
        self.rows.append((self.in_dir, _parse(line)))
        return line

    def set_timeout(self, seconds: float | None) -> None:
        setter = getattr(self.inner, "set_timeout", None)
        if setter is not None:
            setter(seconds)

    def stderr_text(self) -> str:
        reader = getattr(self.inner, "stderr_text", None)
        return reader() if reader is not None else ""

    def close(self) -> None:
        self.inner.close()


class InProcessBot:
    def __init__(self, session: BotSession) -> None:
        self.session, self.pending = session, []

    def write_line(self, payload: bytes) -> None:
        self.pending.append(self.session.handle_line(payload))

    def read_line(self) -> bytes:
        return wire.strip_line_terminator(self.pending.pop(0))

    def close(self) -> None:
        pass


class GameRows:
    """One game's rows in pipe order; the seats' start exchanges (on the host's start threads) p0's first."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, Any]] = []
        self.starts: dict[str, list] = {seat: [] for seat in SEATS}
        self.thread = threading.get_ident()

    def append(self, row: tuple[str, Any], seat: str | None = None) -> None:
        if seat is not None and threading.get_ident() != self.thread:
            self.starts[seat].append(row)
            return
        self._place()
        self.rows.append(row)

    def done(self) -> list[tuple[str, Any]]:
        self._place()
        return list(self.rows)

    def _place(self) -> None:
        for seat in SEATS:
            self.rows.extend(self.starts[seat])
            self.starts[seat].clear()


@dataclass(frozen=True)
class SeatRows:
    game: GameRows
    seat: str

    def append(self, row: tuple[str, Any]) -> None:
        self.game.append(row, self.seat)


# ---------------------------------------------------------------------------
# the scripted bot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Script:
    """How the scripted bot answers: ``second_for_first`` sends arrangement card 0 to the second destination."""

    mulligans: int = 0
    second_for_first: bool = False

    def pick(self, decision: BotDecision) -> int:
        cands = decision.candidates
        sem = [c.semantic for c in cands]
        kinds = [s["kind"] for s in sem]
        if kinds[0] == "mulligan" or "mulligan" in kinds:
            taken = sem[0]["mulligans_taken"]
            want = taken >= self.mulligans
            return next(c.candidate_id for c in cands if c.semantic.get("keep") == want)
        if "play_land" in kinds:
            return kinds.index("play_land")
        if "cast_spell" in kinds:
            return kinds.index("cast_spell")
        if kinds[0] == "pass":
            return 0
        if kinds[0] == "arrange_card":
            index = sem[0]["card_index"]
            if self.second_for_first and index == 0 and len(cands) > 1:
                return cands[1].candidate_id
            return cands[0].candidate_id
        if kinds[0] == "order_pick":
            return cands[-1].candidate_id
        for k, s in enumerate(sem):
            if s["kind"] in ("declare_attack", "declare_block") and (s.get("defender", 1) is None
                                                                      or s.get("attacker", 1) is None):
                return k
        return 0


# ---------------------------------------------------------------------------
# the goldens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Golden:
    deck: tuple[tuple[str, int], ...]
    mulligan: str
    script: Any                       # .pick(BotDecision) -> candidate_id, for both seats
    purpose: str                      # the arrangement or order purpose the golden is for
    where: str                        # "top" or "bottom": where the placed block lands
    deck1: tuple[tuple[str, int], ...] | None = None   # p1's deck when it differs from p0's


FILLERS = (("Air Elemental", 1), ("Serra Angel", 1), ("Colossal Dreadmaw", 1), ("Shivan Dragon", 1))

GOLDENS: dict[str, Golden] = {
    # Preordain: scry 2, both cards kept on top in the reverse of XMage's look order
    "xmage_scry": Golden((("Island", 4), ("Preordain", 3)) + FILLERS, "none", Script(), "scry", "top"),
    # Curate: surveil 2, card 0 to the graveyard, card 1 on top
    "xmage_surveil": Golden((("Island", 5), ("Curate", 3)) + FILLERS, "none", Script(second_for_first=True),
                            "surveil", "top"),
    # Ponder: the top three cards back in any order (library_top, the inverted top loop), no shuffle, then a draw
    "xmage_library_top": Golden((("Island", 4), ("Ponder", 3)) + FILLERS, "none", Script(), "library_top", "top"),
    # Impulse: one of four into the hand, the other three on the bottom in any order (library_bottom)
    "xmage_library_bottom": Golden((("Island", 4), ("Impulse", 2), ("Craw Wurm", 1), ("Hill Giant", 1)) + FILLERS,
                                   "none", Script(), "library_bottom", "bottom"),
    # London mulligan: two mulligans, then the two bottom cards placed last candidate first (mulligan_bottom)
    "xmage_london_bottom": Golden((("Island", 4), ("Craw Wurm", 1), ("Hill Giant", 1)) + FILLERS, "london",
                                  Script(mulligans=2), "mulligan_bottom", "bottom"),
}


def _deck(deck: tuple[tuple[str, int], ...]) -> tuple[WireDeck, OwnDeck, list[str]]:
    rows = deck_rows([{"name": n, "count": c} for n, c in deck], "golden deck")
    identifier = deck_id(rows)
    decklist = tuple(DeckRow(r["name"], r["count"]) for r in rows)
    return WireDeck(identifier, decklist=decklist), OwnDeck(identifier, "x4", decklist), [r["name"] for r in rows]


def _setup(golden: Golden, game: int) -> GameSetup:
    wire0, own0, names0 = _deck(golden.deck)
    wire1, own1, names1 = _deck(golden.deck1 or golden.deck)
    rules = Rules.from_json({
        "opponent_decklist": "visible",
        "mulligan": golden.mulligan,
        "starting_player": "host_assigned",
        "starting_seat": "p0",
        "card_name_domain": card_name_domain(names0 + names1),
        "extensions": [],
        "probe": False,
    })
    return GameSetup(game_index=game, game_id=SECRET.game_id(game), game_secret_hex=SECRET.game_secret(game).hex(),
                     format=FORMAT, wire_decks=(wire0, wire1), own_decks=(own0, own1), rules=rules,
                     time_control=TIME_CONTROL, limits=LIMITS, resources=RESOURCES,
                     agent_seeds=(SECRET.agent_seed(game, "p0"), SECRET.agent_seed(game, "p1")))


def play(name: str, golden: Golden, game: int, argv: list[str]) -> tuple[list[tuple[str, Any]], Any]:
    rows = GameRows()
    peer = wire.SubprocessPeer(list(argv), timeout_s=300.0)
    engine = EngineProcess(peer=RecordingPeer(peer, rows, "host_to_engine", "engine_to_host"))
    seats: dict[str, SubprocessDriver] = {}
    try:
        engine.hello()
        setup = _setup(golden, game)
        bot_name = f"x4b-{name.removeprefix('xmage_').replace('_', '-')}"
        for seat in SEATS:
            spec = BotSpec(name=bot_name, version=BOT_VERSION, type="subprocess", command=("in-process",))

            def factory(seat=seat):
                session = BotSession(choose=golden.script.pick, name=bot_name, version=BOT_VERSION)
                return AgentProcess(peer=RecordingPeer(InProcessBot(session), SeatRows(rows, seat),
                                                       "host_to_agent", "agent_to_host"))

            seats[seat] = SubprocessDriver(spec, startup_ms=TIME_CONTROL.startup_ms, agent_factory=factory)
        result = play_game(setup, engine=engine, seats=seats, clock_ns=lambda: 0)
    finally:
        for driver in seats.values():
            driver.close()
        engine.close()
    return rows.done(), result


# ---------------------------------------------------------------------------
# the check: shape of the posed group, and the draws that follow
# ---------------------------------------------------------------------------


def _decisions(rows):
    """(step, seat_decision, answered candidate semantic) for each engine decision, in order."""
    out = []
    pending = None
    for direction, message in rows:
        if direction == "engine_to_host" and isinstance(message, dict) and message.get("seat_decision"):
            pending = (message["step"], message["seat_decision"])
        elif direction == "host_to_engine" and isinstance(message, dict) and message.get("request_type") == "step":
            if pending is not None:
                cid = message["selection"]["candidate_id"]
                out.append((pending[0], pending[1], pending[1]["candidates"][cid]["semantic"]))
                pending = None
    return out


def _hand(sd) -> list[str] | None:
    obs = sd["observation"]
    for p in obs["players"]:
        if p["seat"] == sd["acting_seat"] and p["hand"] is not None:
            return [c["card_name"] for c in p["hand"]]
    return None


def check_game(golden: Golden, rows) -> dict[str, Any]:
    """The first block of the golden's purpose for any seat: its shape, the placed order, and the seat's later draws."""
    decisions = _decisions(rows)
    facts: dict[str, Any] = {"purpose": golden.purpose, "ok": False}
    start = None
    for i, (_, sd, _) in enumerate(decisions):
        kinds = {c["semantic"]["kind"] for c in sd["candidates"]}
        purposes = {c["semantic"].get("purpose") for c in sd["candidates"]}
        if golden.purpose in ("scry", "surveil"):
            hit = "arrange_card" in kinds and golden.purpose in purposes
        else:
            hit = "order_pick" in kinds and golden.purpose in purposes
        if hit:
            start = i
            break
    if start is None:
        facts["why"] = "the golden's block was never posed"
        return facts
    seat = decisions[start][1]["acting_seat"]
    group = decisions[start][1]["group"]
    block = [d for d in decisions[start:start + group["substep_count"]]]
    if any(d[1]["group"]["group_id"] != group["group_id"] or d[1]["acting_seat"] != seat for d in block):
        facts["why"] = "the group was interrupted"
        return facts
    facts["seat"] = seat
    facts["substep_count"] = group["substep_count"]
    # names of the looked-at / ordered objects, by object id, from the block's own observations
    names: dict[str, str] = {}
    for _, sd, _ in block:
        for k in sd["observation"].get("known", []):
            if k.get("object_id") and k.get("card_name"):
                names[k["object_id"]] = k["card_name"]
        for p in sd["observation"]["players"]:
            for zone in ("hand", "battlefield", "graveyard", "exile"):
                for r in p.get(zone) or []:
                    names[r["object_id"]] = r["card_name"]
    destination: dict[str, str] = {}
    placed: list[str] = []
    for _, sd, answer in block:
        if answer["kind"] == "arrange_card":
            destination[answer["card"]["object_id"]] = answer["destination"]
        elif answer["kind"] == "order_pick":
            placed.append(answer["item"]["object"]["object_id"])
    # the implied last item: the one item of the block's last order_pick candidates not picked
    order_ids = {c["semantic"]["item"]["object"]["object_id"] for _, sd, _ in block for c in sd["candidates"]
                 if c["semantic"]["kind"] == "order_pick"}
    if golden.purpose in ("scry", "surveil"):
        order_ids |= set(destination)
    rest = sorted(order_ids - set(placed))
    if len(rest) == 1:
        placed.append(rest[0])
    if golden.purpose in ("scry", "surveil"):
        n = len(destination)
        facts["shape_ok"] = group["substep_count"] == 2 * n - 1
        placed = [o for o in placed if destination.get(o) == "top"]
        facts["destinations"] = [destination[o] for o in destination]
    else:
        facts["shape_ok"] = True
    facts["placed"] = [names.get(o, "?") for o in placed]
    # the cards the seat draws afterwards, one draw at a time (hand growth by exactly 1 at its next decisions)
    draws: list[str] = []
    previous = _hand(block[-1][1])
    for _, sd, _ in decisions[start + len(block):]:
        if sd["acting_seat"] != seat:
            continue
        hand = _hand(sd)
        if hand is None:
            continue
        if previous is not None and len(hand) == len(previous) + 1:
            grown = list(hand)
            for c in previous:
                if c in grown:
                    grown.remove(c)
            if len(grown) == 1:
                draws.append(grown[0])
        previous = hand
    facts["draws_after"] = draws
    want = facts["placed"]
    distinct = len(want) > 0 and len(set(want)) == len(want)
    if golden.where == "top" or golden.purpose == "library_bottom":
        # the next draws come off the top of the block (Impulse leaves only the block in the library); two draws,
        # since a later spell of the same deck may look at the library again
        k = min(2, len(want))
        facts["ok"] = facts["shape_ok"] and distinct and draws[:k] == want[:k]
    else:
        # the London bottom: the block comes off the library last, position 0 first
        found = [d for d in draws if d in want]
        facts["ok"] = facts["shape_ok"] and distinct and len(want) > 1 and found[-len(want):] == want
    return facts


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _render(rows) -> bytes:
    return b"".join(wire.canonical_json_line({"dir": d, "message": m}) for d, m in rows)


def generate(out: Path, argv: list[str]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {}
    failed = 0
    for name, golden in GOLDENS.items():
        tried = []
        for game in range(MAX_GAME_INDEX):
            rows, result = play(name, golden, game, argv)
            facts = check_game(golden, rows)
            ending = (result.outcome, result.classification, result.reason)
            tried.append({"game": game, "ending": ending, "ok": facts["ok"]})
            if facts["ok"] and result.classification == "natural" and result.violation is None:
                (out / f"{name}.transcript.jsonl").write_bytes(_render(rows))
                index[f"{name}.transcript.jsonl"] = {
                    "engine": "xmage", "game_index": game, "game_id": SECRET.game_id(game),
                    "game_digest": result.game_digest, "ending": list(ending),
                    "step_count": result.step_count, "decision_count": result.decision_count,
                    "check": facts, "roles": ["engine", "host"]}
                print(name, "game", game, result.game_digest, json.dumps(facts), flush=True)
                break
        else:
            failed += 1
            print(name, "NO GAME PASSED", json.dumps(tried), flush=True)
    doc = {"schema": SCHEMA, "run_secret": "spec 16 vector (bytes 0x00..0x1f)", "format": FORMAT,
           "notes": [
               "rows are canonical JSON {dir, message} per message as crossed the pipes (spec 16); the clock reads 0",
               "both seats run the same scripted bot in process (goldens.py Script); decks are named decklists",
               "check: the block's shape (2n - 1 for an arrangement), the placed order, and the seat's later draws",
           ],
           "transcripts": index}
    (out / "index.json").write_bytes(wire.canonical_json_line(doc))
    return 1 if failed else 0


def check(directory: Path, argv: list[str]) -> int:
    doc = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    bad = 0
    for file_name, entry in sorted(doc["transcripts"].items()):
        name = file_name.removesuffix(".transcript.jsonl")
        path = directory / file_name
        engine_diffs = replay_engine_transcript(list(argv), path, timeout_s=300.0)
        rows, result = play(name, GOLDENS[name], entry["game_index"], argv)
        same_rows = _render(rows) == path.read_bytes()
        same_digest = result.game_digest == entry["game_digest"]
        ok = not engine_diffs and same_rows and same_digest
        bad += 0 if ok else 1
        print(json.dumps({"golden": file_name, "engine_replay_differences": engine_diffs[:3],
                          "host_replay_rows_equal": same_rows, "digest": result.game_digest,
                          "digest_equal": same_digest, "verdict": "PASS" if ok else "FAIL"}), flush=True)
    print("goldens check verdict:", "PASS" if bad == 0 else "FAIL")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument("--out")
    parser.add_argument("--dir")
    raw = sys.argv[1:]
    cut = raw.index("--") if "--" in raw else len(raw)
    args = parser.parse_args(raw[:cut])
    argv = raw[cut + 1:]
    if args.command == "generate":
        return generate(Path(args.out), argv)
    return check(Path(args.dir), argv)


if __name__ == "__main__":
    sys.exit(main())
