"""The advisor's planned line at the London human engine (``--line-seat``; ``x_advisor_line_v1``).

With the line enabled, every ordinary decision of the person's seat carries the line (its steps as protocol semantics,
how it ends, the result of a game end) and nothing else: no counts, no opponent choice, no timing. The bot's seat
never carries it, and the game is the same with and without it: every response, both seats', is byte-equal but for
the line. The line itself is played by the bridge on a clone (mtg-kernel's ``private_line``: the game is never
touched, the opponent's hidden hand never shows); here a stub scorer picks the person's steps.

Needs MTG_KERNEL_LONDON_HUMAN_BRIDGE (a bridge with ``private_line``) and MTG_KERNEL_PUBLIC_CATALOG.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

BRIDGE = os.environ.get("MTG_KERNEL_LONDON_HUMAN_BRIDGE")
CATALOG = os.environ.get("MTG_KERNEL_PUBLIC_CATALOG")
needs_bridge = pytest.mark.skipif(not (BRIDGE and CATALOG and Path(BRIDGE).exists()),
                                  reason="needs the London bridge and the public catalog")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[3] / "python"))

from kernel_engine_london_human_v1 import (FLAT, HISTORY, LINE, LINE_SCHEMA, LINE_STOPS, KernelEngine,  # noqa: E402
                                           NativePeer)
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402

PERSON, BOT = "p0", "p1"


class FirstNotPass:
    """A stub of the line's scorer: the first of the model's rows that is not a pass (a land, a spell, an attack),
    else the first row. Reads only what the real scorer is given."""

    def __init__(self) -> None:
        self.reads = 0

    def read(self, game_id, decision, extension):
        self.reads += 1
        rows = extension["row_candidate_ids"]
        kinds = [decision["candidates"][row]["semantic"].get("kind") for row in rows]
        top = next((i for i, kind in enumerate(kinds) if kind != "pass"), 0)
        return {"rows": [{"id": row, "p": 0.9 if i == top else 0.1 / len(rows)} for i, row in enumerate(rows)],
                "value": 0.0, "win": 0.5}

    def close(self) -> None:
        pass


class World:
    def __init__(self, seed: int, *, line: bool, person: str = "Elves", bot: str = "Burn",
                 line_seat: str | None = PERSON) -> None:
        self.catalog = json.loads(Path(CATALOG).read_bytes())
        self.peer = NativePeer(BRIDGE)
        self.scorer = FirstNotPass()
        self.engine = KernelEngine(self.peer, self.catalog, engine_windows_seat=PERSON, auto_graveyard_order=True,
                                   line_seat=line_seat, line_scorer=self.scorer)
        decks = {e["catalog_id"]: e["decklist"] for e in self.catalog["catalog"]}
        self.serial = 0
        names = [r["name"] for d in (person, bot) for r in decks[d]]
        rules = {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned",
                 "starting_seat": "p0", "card_name_domain": card_name_domain(names),
                 "extensions": [FLAT, HISTORY] + ([LINE] if line else []), "probe": False}
        self.current = self.send({"request_type": "reset", "game_id": f"line-{seed}", "format": "pauper-bo1",
                                  "seats": [{"seat": "p0", "deck": {"catalog_id": person, "deck_id": deck_id(decks[person])}},
                                            {"seat": "p1", "deck": {"catalog_id": bot, "deck_id": deck_id(decks[bot])}}],
                                  "rules": rules, "game_secret": hashlib.sha256(f"line-{seed}".encode()).hexdigest(),
                                  "max_decisions": 1 << 20, "max_steps": 1 << 20})

    def send(self, value: dict) -> dict:
        self.serial += 1
        request = {"protocol": "spellbench/v2", "request_id": f"q{self.serial}", **value}
        return wire.strict_json_loads(self.engine.handle(wire.canonical_json_dumps(request)))

    def answer(self, candidate: int) -> None:
        sd = self.current["seat_decision"]
        self.current = self.send({"request_type": "step", "game_id": self.current["game_id"],
                                  "expected_step": self.current["step"],
                                  "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})

    def close(self) -> None:
        self.peer.close()


def without_line(response: dict) -> str:
    value = json.loads(json.dumps(response))
    if value.get("response_type") == "decision":
        value["seat_decision"]["extensions"].pop(LINE, None)
    return wire.canonical_json_dumps(value)


def pick(sd: dict, rng: random.Random) -> int:
    """Both seats keep, play lands, cast what they can and attack; otherwise a seeded candidate."""
    semantics = [c["semantic"] for c in sd["candidates"]]
    keep = [i for i, s in enumerate(semantics) if s["kind"] == "mulligan" and s["keep"]]
    act = [i for i, s in enumerate(semantics) if s["kind"] in ("play_land", "cast_spell")]
    return (keep or act or [rng.randrange(len(semantics))])[0] if rng.random() < 0.8 else rng.randrange(len(semantics))


@needs_bridge
def test_the_line_is_on_the_persons_ordinary_decisions_only_and_the_game_is_the_same_without_it() -> None:
    stops, results, lined, unlined_person = Counter(), Counter(), 0, 0
    for seed in range(1, 5):
        on, off = World(seed, line=True), World(seed, line=False)
        rng = random.Random(seed)
        try:
            for _ in range(20_000):
                assert without_line(on.current) == without_line(off.current), f"seed {seed}"
                if on.current["response_type"] != "decision":
                    assert on.current["classification"] == "natural", on.current
                    break
                sd = on.current["seat_decision"]
                line = sd["extensions"].get(LINE)
                assert LINE not in off.current["seat_decision"]["extensions"]
                if sd["acting_seat"] == BOT:
                    assert line is None, "the bot's decisions never carry the line"
                elif line is None:
                    # a grouped choice (a block, an order) or the pregame: the line starts at ordinary decisions
                    unlined_person += 1
                    pregame = any(c["semantic"]["kind"] == "mulligan" or c["semantic"].get("purpose") == "mulligan_bottom"
                                  for c in sd["candidates"])
                    assert on.engine.buffer is not None or pregame, sd["context"]
                else:
                    lined += 1
                    assert set(line) == {"schema", "steps", "stop", "result"}, line
                    assert line["schema"] == LINE_SCHEMA and line["stop"] in LINE_STOPS and 1 <= len(line["steps"]) <= 8
                    assert all(isinstance(step, dict) and "kind" in step for step in line["steps"])
                    assert (line["result"] is not None) == line["stop"].startswith("game_end")
                    stops[line["stop"]] += 1
                    results[line["result"]] += 1
                choice = pick(sd, rng)
                on.answer(choice)
                off.answer(choice)
            else:
                pytest.fail(f"seed {seed}: the game did not end")
        finally:
            on.close()
            off.close()
    print(f"lines {lined}, person decisions without one {unlined_person}, stops {dict(stops)}, results {dict(results)}")
    assert lined > 100 and {"opponent_decision", "turn_ends", "unseen"} <= set(stops), dict(stops)


@needs_bridge
def test_the_line_is_refused_without_a_line_seat_and_declared_only_with_one() -> None:
    catalog = json.loads(Path(CATALOG).read_bytes())
    peer = NativePeer(BRIDGE)
    try:
        plain = KernelEngine(peer, catalog)
        assert LINE not in {e["name"] for e in plain.hello["extensions"]}
        lined = KernelEngine(peer, catalog, line_seat=PERSON, line_scorer=FirstNotPass())
        assert {"name": LINE, "native_ids": False} in lined.hello["extensions"]
    finally:
        peer.close()
    world = World(1, line=True, line_seat=None)
    try:
        assert world.current["response_type"] == "error", world.current
        assert world.current["error"]["code"] == "unsupported_rule"
    finally:
        world.close()


@needs_bridge
def test_what_a_line_shows_never_depends_on_time_and_its_failures_end_only_the_line(monkeypatch, tmp_path) -> None:
    """The same lines whatever the clock says (no wall-clock bound: the clone's speed depends on the opponent's
    windows, so on their hand); a broken bridge, a failing scorer or an unwritable timing file ends the line, never
    the game."""
    import kernel_engine_london_human_v1 as engine_module

    def lines(clock=None) -> list:
        world = World(3, line=True)
        rng = random.Random(3)
        out = []
        try:
            if clock is not None:
                monkeypatch.setattr(engine_module.time, "perf_counter", clock)
            for _ in range(400):
                if world.current["response_type"] != "decision":
                    break
                sd = world.current["seat_decision"]
                if LINE in sd["extensions"]:
                    out.append(sd["extensions"][LINE])
                world.answer(pick(sd, rng))
        finally:
            monkeypatch.undo()
            world.close()
        return out

    ticks = iter(range(10**9))
    assert lines() == lines(lambda: float(next(ticks)))  # each reading a second later: nothing changes

    world = World(4, line=True)
    rng = random.Random(4)
    try:
        world.engine.line_timing = tmp_path / "missing-folder" / "timing.jsonl"  # cannot be written
        original = world.peer.request
        failures = iter([BrokenPipeError("bridge pipe"), None, None])

        def flaky(value):
            if value.get("request_type") == "private_line":
                failure = next(failures, None)
                if failure is not None:
                    raise failure
            return original(value)

        world.peer.request = flaky
        seen = []
        for _ in range(400):
            if world.current["response_type"] != "decision":
                break
            sd = world.current["seat_decision"]
            if LINE in sd["extensions"]:
                seen.append(sd["extensions"][LINE]["stop"])
                if len(seen) >= 6:
                    break  # stay at this decision of the person's for the scorer failure below
            world.answer(pick(sd, rng))
        assert seen[0] == "unavailable" and len(set(seen)) > 1, seen  # the next lines play on

        class Failing(FirstNotPass):
            def read(self, game_id, decision, extension):
                raise engine_module.AdvisorError("the scorer answered something else")

        world.engine.line_scorer = Failing()
        assert world.engine.planned_line()["stop"] == "unavailable" and world.engine.line_scorer is None

        class Stalled(FirstNotPass):
            """Stops answering (as a scorer that stops reading its input blocks the request's write)."""

            def __init__(self) -> None:
                super().__init__()
                self.release, self.closed = threading.Event(), threading.Event()

            def read(self, game_id, decision, extension):
                self.release.wait(30)
                return super().read(game_id, decision, extension)

            def close(self) -> None:
                self.closed.set()

        stalled = Stalled()
        world.engine.line_scorer = stalled
        started = time.monotonic()
        assert world.engine.planned_line()["stop"] == "unavailable"
        assert time.monotonic() - started < engine_module.LINE_SCORER_TIMEOUT_S + 1.0
        assert world.engine.line_scorer is None and stalled.closed.wait(5)
        stalled.release.set()
    finally:
        world.close()


@needs_bridge
def test_a_line_costs_little() -> None:
    """Cost of the line at the wrapper (stub scorer: the bridge's clone steps and the wrapper's conversions)."""
    world = World(2, line=True)
    rng = random.Random(2)
    timings = []
    try:
        for _ in range(20_000):
            if world.current["response_type"] != "decision":
                break
            sd = world.current["seat_decision"]
            if sd["acting_seat"] == PERSON and LINE in sd["extensions"]:
                started = time.perf_counter()
                world.engine.planned_line()
                timings.append(time.perf_counter() - started)
            world.answer(pick(sd, rng))
    finally:
        world.close()
    timings.sort()
    print(f"lines {len(timings)}: median {timings[len(timings) // 2] * 1000:.1f} ms, "
          f"p95 {timings[int(len(timings) * 0.95)] * 1000:.1f} ms, max {timings[-1] * 1000:.1f} ms")
    assert timings and timings[-1] < 2.0


class Includes(FirstNotPass):
    """A stub scorer that blocks and attacks wherever the engine lets it: the first row that includes a creature
    (a native attack or block question), else as ``FirstNotPass``."""

    def read(self, game_id, decision, extension):
        rows = extension["row_candidate_ids"]
        semantics = [decision["candidates"][row]["semantic"] for row in rows]
        top = next((i for i, s in enumerate(semantics) if s.get("include") is True), None)
        if top is None:
            return super().read(game_id, decision, extension)
        self.reads += 1
        return {"rows": [{"id": row, "p": 0.9 if i == top else 0.1 / len(rows)} for i, row in enumerate(rows)],
                "value": 0.0, "win": 0.5}


@needs_bridge
def test_a_declaration_shows_the_whole_declaration_the_line_plays() -> None:
    """At the first question of the person's attack, the line's first steps answer every creature of the attack; at
    the first question of their block (the engine's untouched block root), the line plays the engine's blocker
    questions and shows the whole block, blocker by blocker in the order the person's screen asks them. Later
    questions of a block get no line."""
    from kernel_engine_london_human_v1 import BlockDeclaration

    attacks = blocks = blocking = 0
    for seed in range(1, 5):
        for person, bot in (("Faeries", "Burn"), ("Burn", "Faeries")):
            world = World(seed, line=True, person=person, bot=bot)
            world.engine.line_scorer = world.scorer = Includes()
            rng = random.Random(seed)
            try:
                for _ in range(20_000):
                    if world.current["response_type"] != "decision":
                        break
                    sd = world.current["seat_decision"]
                    kinds = {c["semantic"]["kind"] for c in sd["candidates"]}
                    line = sd["extensions"].get(LINE)
                    if sd["acting_seat"] == PERSON and kinds == {"declare_attack"} and sd["group"]["substep_index"] == 0:
                        count = sd["group"]["substep_count"]
                        assert line is not None
                        if line["stop"] not in ("unavailable", "unreadable"):
                            assert [s["kind"] for s in line["steps"][:count]] == ["declare_attack"] * count, line
                            attacks += 1
                    if sd["acting_seat"] == PERSON and kinds == {"declare_block"}:
                        buffer = world.engine.buffer
                        assert isinstance(buffer, BlockDeclaration)
                        if buffer.prefix:
                            assert line is None, "a later blocker's question carries no line"
                        else:
                            assert line is not None and line["stop"] in LINE_STOPS, line
                            blockers = [buffer.refs[b] for b in buffer.plan.blockers]
                            shown = line["steps"][:len(blockers)]
                            assert [s["kind"] for s in shown] == ["declare_block"] * len(blockers), line
                            assert [s["blocker"] for s in shown] == blockers
                            for step in shown:
                                attacker = step["attacker"]
                                assert attacker is None or attacker in buffer.refs.values()
                            blocks += 1
                            blocking += any(s["attacker"] is not None for s in shown)
                    world.answer(pick(sd, rng))
            finally:
                world.close()
    print(f"attack lines {attacks}, block lines {blocks}, with a block {blocking}")
    assert attacks > 10 and blocks > 5 and blocking > 0
