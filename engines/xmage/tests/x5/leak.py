"""X5 paired-world leak tests (spec Section 13 F1 and F3; design draft Section 6).

One game secret, two hidden worlds: world A is the engine as built; world B runs the same game with
``-Dspellbench.test.worldSalt=SEAT:B`` (``rng.GameRandom``), which reseeds only that seat's own streams (its library
order, so its opening hand, its draws and its random cards). Shared streams (starting player, coin flips) and the
object-id stream are untouched, and every seat's bot gets the same seed in both worlds. The other seat, the
observer, has the same information in both worlds until the public state diverges, so its whole ``seat_decision``
stream must be byte-identical after canonicalization until then.

Canonicalization: canonical JSON (spec 4.3) with every object id renamed by its first appearance in that seat's
stream (ids are pseudorandom functions of the internal identity, spec 5.3, so a different physical Island played in
world B gets a different id; the renaming keeps every equality between ids and drops only their values).

At the first index where the observer's two streams differ, the difference is classified from the two decisions:
- ``public``: the public part of the observation differs (everything except the observer's own hand and ``known``):
  a legitimate divergence, which ends the comparison;
- ``own_hand``: only the observer's own hand differs (it drew different cards, possible only when the salted seat
  is the observer itself);
- ``own_look``: only ``known`` entries of the observer's own library differ (a scry or a look it caused);
- ``UNEXPLAINED``: the public state and the observer's own hand are equal, yet the decision differs (candidates,
  context, group, or ``known`` entries about the other seat): a leak, and the test fails.
Streams that end at different lengths with an equal prefix are classified ``public`` (the games ended differently).

Positions:
- ``counterspell``: observer p0 (``uniform``, catalog deck Standard16-RG, on the play) against p1 (36 Island and 4
  Counterspell, scripted: keeps, plays an Island whenever it can, never casts, never blocks); salt p1. A pair is
  kept when p1's opening hand holds a Counterspell in world A and none in world B (two more lands).
- ``cantrip``: p0 (20 Island and 20 Opt, scripted: keeps, plays a land, casts Opt whenever it can, scry to the top)
  against observer p1 (``uniform``, catalog deck Standard-MonoU); salt p0, so p0's library tops differ. A pair is
  kept when p0's opening hands have the same names in both worlds. Both seats' streams are compared: p1's must
  show no unexplained divergence, and p0's first divergence must be ``own_look`` or ``own_hand``.
- ``random``: catalog decks of both pools (mirror), ``uniform`` against ``uniform``, the salted seat alternating;
  the observer is the other seat.

    python leak.py --position counterspell|cantrip|random --pairs N --out DIR [--workers W] [--start I] -- ENGINE...
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing
import multiprocessing.util
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from spellbench.arena.config import CONFIG_SCHEMA, DEFAULT_TIME_CONTROL, TournamentConfig
from spellbench.arena.drivers import BuiltinDriver
from spellbench.arena.schedule import EnginePin, game_setup, preflight, schedule
from spellbench.builtins import BUILTIN_VERSIONS, create_builtin_bot
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.run_secret import RunSecret
from spellbench.wire import canonical_json_dumps

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parents[1] / "overlay/src/main/resources/mage/player/spellbench/catalog.json"
STANDARD = "standard-2022-25-bo1"
FDN = "fdn-limited-bo1"
OBJECT_ID = re.compile(r"o-[0-9a-f]{16}")
SALT_B = "B"
BOUND_MS = 300_000


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------


def _kind(candidate) -> str:
    return candidate.semantic.get("kind", "")


class LandsOnly:
    """Keeps, plays a land whenever it can, otherwise the first candidate (pass, no block, ...); never casts."""

    name, version = "x5-lands-only", "1"

    def choose(self, decision) -> int:
        for c in decision.candidates:
            if _kind(c) == "mulligan" and c.semantic.get("keep") is True:
                return c.candidate_id
        for c in decision.candidates:
            if _kind(c) == "play_land":
                return c.candidate_id
        return decision.candidates[0].candidate_id


class Cantripper:
    """Keeps, plays a land, casts any spell it can (Opt), sends looked-at cards to the top, else the first one."""

    name, version = "x5-cantripper", "1"

    def choose(self, decision) -> int:
        for wanted in (("mulligan", lambda s: s.get("keep") is True), ("play_land", None), ("cast_spell", None),
                       ("arrange_card", lambda s: s.get("destination") == "top")):
            for c in decision.candidates:
                if _kind(c) == wanted[0] and (wanted[1] is None or wanted[1](c.semantic)):
                    return c.candidate_id
        return decision.candidates[0].candidate_id


class Recording:
    """Wraps a bot and records every forwarded seat_decision (the ``decision`` of each ``choose`` request)."""

    def __init__(self, inner, log: list) -> None:
        self.inner, self.log = inner, log
        self.name, self.version = getattr(inner, "name", "bot"), getattr(inner, "version", "1")

    def on_game_start(self, game) -> None:
        hook = getattr(self.inner, "on_game_start", None)
        if hook is not None:
            hook(game)

    def choose(self, decision) -> int:
        self.log.append(decision.raw.get("decision"))
        return self.inner.choose(decision)

    def on_game_over(self, game_over) -> None:
        hook = getattr(self.inner, "on_game_over", None)
        if hook is not None:
            hook(game_over)


# ---------------------------------------------------------------------------
# Canonicalization and comparison
# ---------------------------------------------------------------------------


def canonical_stream(stream: list[dict]) -> list[bytes]:
    names: dict[str, str] = {}

    def rename(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: rename(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [rename(v) for v in value]
        if isinstance(value, str) and OBJECT_ID.fullmatch(value):
            if value not in names:
                names[value] = f"id{len(names)}"
            return names[value]
        return value

    return [canonical_json_dumps(rename(d)) for d in stream]


def _public(observation: dict) -> dict:
    obs = dict(observation)
    obs.pop("known", None)
    obs["players"] = [{k: v for k, v in p.items() if k != "hand"} for p in obs.get("players", [])]
    return obs


def _own_hand(observation: dict) -> Any:
    viewer = observation.get("viewer")
    return [p.get("hand") for p in observation.get("players", []) if p.get("seat") == viewer]


def classify(a: dict, b: dict) -> str:
    """Why the observer's decisions ``a`` and ``b`` (already renamed) differ."""
    oa, ob = a.get("observation", {}), b.get("observation", {})
    if _public(oa) != _public(ob):
        return "public"
    if _own_hand(oa) != _own_hand(ob):
        return "own_hand"
    ka, kb = oa.get("known", []), ob.get("known", [])
    viewer = oa.get("viewer")
    diff = [k for k in ka if k not in kb] + [k for k in kb if k not in ka]
    rest_a = {k: v for k, v in a.items() if k != "observation"}
    rest_b = {k: v for k, v in b.items() if k != "observation"}
    if diff and all(k.get("owner_seat") == viewer and k.get("zone") == "library" for k in diff):
        return "own_look"
    if rest_a == rest_b and not diff:
        return "public"  # unreachable: equal canonical bytes
    return "UNEXPLAINED"


def compare(stream_a: list[dict], stream_b: list[dict]) -> dict[str, Any]:
    ca, cb = canonical_stream(stream_a), canonical_stream(stream_b)
    n = min(len(ca), len(cb))
    for k in range(n):
        if ca[k] != cb[k]:
            ra, rb = json.loads(ca[k]), json.loads(cb[k])
            return {"identical_prefix": k, "lengths": [len(ca), len(cb)], "first_divergence": classify(ra, rb),
                    "kind": (ra.get("context") or {}).get("kind"), "turn": ra.get("observation", {}).get("turn")}
    if len(ca) == len(cb):
        return {"identical_prefix": n, "lengths": [len(ca), len(cb)], "first_divergence": None}
    return {"identical_prefix": n, "lengths": [len(ca), len(cb)], "first_divergence": "public"}


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def _catalog() -> list[dict]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _deck(catalog_id: str) -> dict:
    return {"catalog_id": catalog_id}


def position_spec(position: str) -> dict[str, Any]:
    """Configs (one per deck pairing), seat bots, the salted seat and the observers of a position."""
    if position == "counterspell":
        return {"configs": [("cs", STANDARD, _deck("Standard16-RG"),
                             {"name": "x5-counterspell", "decklist": [{"name": "Counterspell", "count": 4},
                                                                      {"name": "Island", "count": 36}]})],
                "bots": {"p0": "uniform", "p1": LandsOnly}, "salted": "p1", "observers": ["p0"], "start": "p0"}
    if position == "cantrip":
        return {"configs": [("ct", STANDARD, {"name": "x5-cantrip", "decklist": [{"name": "Island", "count": 20},
                                                                                {"name": "Opt", "count": 20}]},
                             _deck("Standard-MonoU"))],
                "bots": {"p0": Cantripper, "p1": "uniform"}, "salted": "p0", "observers": ["p1", "p0"],
                "start": "p0"}
    if position == "random":
        configs = [(d["catalog_id"], d["formats"][0], _deck(d["catalog_id"]), _deck(d["catalog_id"]))
                   for d in _catalog()]
        return {"configs": configs, "bots": {"p0": "uniform", "p1": "uniform"}, "salted": None,
                "observers": None, "start": "p0"}
    raise ValueError(position)


def make_config(label: str, fmt: str, deck0: dict, deck1: dict, engine: list[str], start: str) -> TournamentConfig:
    return TournamentConfig.from_json({
        "schema": CONFIG_SCHEMA,
        "tournament_dir": f"x5-leak-{label}",
        "format": fmt,
        "decks": [deck0, deck1],
        "engine": {"command": list(engine)},
        "bots": [{"name": "uniform", "version": BUILTIN_VERSIONS["uniform"], "type": "builtin"}],
        "pairs_per_matchup": 1,
        "stats_seed": 0,
        "include_self_play": True,
        "rules": {"starting_player": "host_assigned", "starting_seat": start},
        "time_control": {**DEFAULT_TIME_CONTROL.to_json(), "startup_ms": BOUND_MS, "engine_step_ms": BOUND_MS},
        "bootstrap_replicates": 1000,
    })


_W: dict[str, Any] = {}


def _open_engine(argv: list[str], salt: str | None) -> EngineProcess:
    saved = os.environ.get("JAVA_TOOL_OPTIONS")
    if salt is not None:
        os.environ["JAVA_TOOL_OPTIONS"] = f"-Dspellbench.test.worldSalt={salt}"
    else:
        os.environ.pop("JAVA_TOOL_OPTIONS", None)
    try:
        engine = EngineProcess(list(argv), timeout_s=BOUND_MS / 1000)
        engine.hello()
    finally:
        if saved is None:
            os.environ.pop("JAVA_TOOL_OPTIONS", None)
        else:
            os.environ["JAVA_TOOL_OPTIONS"] = saved
    return engine


def _close() -> None:
    engines = _W.get("engines", {})
    for engine in engines.values():
        engine.close()
    engines.clear()


def _init(argv: list[str], position: str, setups: dict, secret_hex: str) -> None:
    _W.update(argv=argv, position=position, setups=setups, secret=RunSecret.from_hex(secret_hex), engines={})
    multiprocessing.util.Finalize(None, _close, exitpriority=10)


def _engine(world: str, salted: str) -> EngineProcess:
    key = (world, salted)
    if key not in _W["engines"]:
        _W["engines"][key] = _open_engine(_W["argv"], None if world == "A" else f"{salted}:{SALT_B}")
    return _W["engines"][key]


def _bot(spec_or_class):
    """A factory: a builtin by name (seeded from the game's agent_seed at game_start), or a scripted bot class."""
    if isinstance(spec_or_class, str):
        return lambda: create_builtin_bot(spec_or_class, seed=0)
    return spec_or_class


def play_pair(task: tuple[int, int]) -> dict[str, Any]:
    """Game ``index`` of config ``ci`` in both worlds; returns both seats' streams and the endings."""
    ci, index = task
    spec = position_spec(_W["position"])
    label, fmt, deck0, deck1 = spec["configs"][ci]
    config = make_config(label, fmt, deck0, deck1, _W["argv"], spec["start"])
    setup = _W["setups"][label]
    secret = _W["secret"]
    salted = spec["salted"] or ("p1" if index % 2 else "p0")
    contexts = {c.game_index: c for c in schedule(config, secret)}
    out: dict[str, Any] = {"config": label, "index": index, "salted": salted}
    # the schedule has two games (one seat-swapped pair); the leak test uses its own index for the secret
    context = contexts[0]
    game = game_setup(config, setup, context, secret)
    game = dataclasses.replace(game, game_index=index, game_id=secret.game_id(index),
                               game_secret_hex=secret.game_secret(index).hex(),
                               agent_seeds=(secret.agent_seed(index, "p0"), secret.agent_seed(index, "p1")))
    for world in ("A", "B"):
        logs = {"p0": [], "p1": []}
        seats = {}
        for seat in ("p0", "p1"):
            inner_factory = _bot(spec["bots"][seat])
            seats[seat] = BuiltinDriver(context.seat_specs[0][1],
                                        factory=lambda f=inner_factory, s=seat: Recording(f(), logs[s]))
        engine = _engine(world, salted)
        start = time.monotonic()
        try:
            result = play_game(game, engine=engine, seats=seats)
        finally:
            for d in seats.values():
                d.close()
        if (result.adjudication or {}).get("kind") == "halt":
            engine.close()
            del _W["engines"][(world, salted)]
        out[world] = {"streams": logs, "outcome": result.outcome, "reason": result.reason,
                      "classification": result.classification, "violation": result.violation,
                      "steps": result.step_count, "seconds": round(time.monotonic() - start, 2)}
    return out


def _hand_names(stream: list[dict]) -> list[str] | None:
    if not stream:
        return None
    obs = stream[0].get("observation", {})
    hands = _own_hand(obs)
    if not hands or hands[0] is None:
        return None
    return sorted(card.get("card_name") for card in hands[0])


def keep_pair(position: str, pair: dict[str, Any]) -> tuple[bool, str]:
    if position == "counterspell":
        a, b = _hand_names(pair["A"]["streams"]["p1"]), _hand_names(pair["B"]["streams"]["p1"])
        ok = a is not None and b is not None and "Counterspell" in a and "Counterspell" not in b
        return ok, f"p1 hand A={a} B={b}"
    if position == "cantrip":
        a, b = _hand_names(pair["A"]["streams"]["p0"]), _hand_names(pair["B"]["streams"]["p0"])
        return a is not None and a == b, f"p0 hand A={a} B={b}"
    return True, ""


def main(argv: list[str]) -> int:
    split = argv.index("--")
    options, engine = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--position", required=True, choices=("counterspell", "cantrip", "random"))
    parser.add_argument("--pairs", type=int, required=True, help="pairs to keep")
    parser.add_argument("--max-tries", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--secret", default="5f684ea840da640a5e2111e347f6c523795d150d0357611177e1fc9bec8516e5")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(options)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    spec = position_spec(args.position)
    secret = RunSecret.from_hex(args.secret)
    setups = {}
    pin = EnginePin()
    for label, fmt, deck0, deck1 in spec["configs"]:
        setups[label] = preflight(make_config(label, fmt, deck0, deck1, engine, spec["start"]), secret, pin=pin)
    n_configs = len(spec["configs"])
    tries = args.max_tries or args.pairs * (8 if args.position != "random" else 1)
    tasks = [(i % n_configs, 1000 + i) for i in range(tries)]
    ctx = multiprocessing.get_context("spawn")
    pool = ctx.Pool(args.workers, initializer=_init, initargs=(engine, args.position, setups, args.secret))
    kept: list[dict[str, Any]] = []
    tally: Counter[str] = Counter()
    results = (out / f"{args.position}-pairs.jsonl").open("w", encoding="utf-8", newline="\n")
    try:
        for pair in pool.imap(play_pair, tasks, chunksize=1):
            ok, why = keep_pair(args.position, pair)
            tally["played"] += 1
            if not ok:
                tally["not_kept"] += 1
                continue
            observers = spec["observers"] or [("p0" if pair["salted"] == "p1" else "p1")]
            row = {"config": pair["config"], "index": pair["index"], "salted": pair["salted"], "condition": why,
                   "endings": {w: {k: pair[w][k] for k in ("outcome", "reason", "classification", "steps",
                                                           "violation")} for w in ("A", "B")},
                   "observers": {}}
            for seat in observers:
                row["observers"][seat] = compare(pair["A"]["streams"][seat], pair["B"]["streams"][seat])
                tally[f"{seat}:{row['observers'][seat]['first_divergence']}"] += 1
            if args.position == "cantrip":
                # the looks inside p1's window: p0's scry decisions whose looked-at cards differ between worlds
                row["p0_scry_decisions"] = [sum(1 for d in pair[w]["streams"]["p0"]
                                                if (d.get("context") or {}).get("purpose") == "scry")
                                            for w in ("A", "B")]
            results.write(json.dumps(row, sort_keys=True) + "\n")
            results.flush()
            kept.append(row)
            if len(kept) >= args.pairs:
                break
        pool.close()
        pool.join()
    except BaseException:
        pool.terminate()
        raise
    finally:
        results.close()
    unexplained = [r for r in kept for s, c in r["observers"].items() if c["first_divergence"] == "UNEXPLAINED"]
    violations = [r for r in kept for w in ("A", "B") if r["endings"][w]["violation"]]
    compared = sum(c["identical_prefix"] for r in kept for c in r["observers"].values())
    summary = {"position": args.position, "pairs_kept": len(kept), "tally": dict(tally),
               "decisions_compared_identical": compared,
               "whole_game_identical": sum(1 for r in kept for c in r["observers"].values()
                                           if c["first_divergence"] is None),
               "unexplained": len(unexplained), "violations": len(violations),
               "verdict": "PASS" if kept and not unexplained and not violations else "FAIL"}
    (out / f"{args.position}-summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8",
                                                       newline="\n")
    print(json.dumps(summary, indent=1))
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
