"""Replay recorded Spellbench kernel games and ask the native bridge whether a win was proven available.

usage: win_check.py --transcripts DIR... --decisions DIR... --model NAME --engine-py PATH --bridge EXE
                    --catalog JSON --source-revision REV --out FILE [--nodes N] [--focus-nodes N] [--depth D]

Each transcript (engine_tap.py or operator engine.jsonl) is replayed through
the same kernel_engine_v2.py that played it (--engine-py), driving a native
bridge built with the private win_search request. Every engine answer must
equal the recorded one, or the game stops as a replay mismatch. At each
native decision of the model's seat (from its decision log), the bridge
clones the live session and searches the rest of the turn: the model's
choices OR, the opponent's AND, on the true state with hidden cards
(mtg-kernel win_search_v1). Verdicts are proven, refuted or unknown, with the
node and depth bounds and whether the search completed.

Budgets: every checked decision gets --nodes; a declared screen gives
--focus-nodes to decisions whose candidates name a Spy combo piece (Balustrade
Spy, Dread Return, Lotleth Giant). The screen only allocates budget and never
decides a verdict.

A turn counts as combo-available when any of its checked decisions is
proven; taken when the model won the game during that turn; missed
otherwise. OUT gets one JSON line per checked decision and a final summary
line. Outputs carry hidden game state: keep them local.
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

HEAVY = ("tensor", "proposals", "proposals_zlib")
COMBO_CARDS = ("Balustrade Spy", "Dread Return", "Lotleth Giant")


def read_lines(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def slim(message):
    decision = message.get("seat_decision") if isinstance(message, dict) else None
    extensions = decision.get("extensions") if isinstance(decision, dict) else None
    flat = extensions.get("x_kernel_flat_v4") if isinstance(extensions, dict) else None
    if isinstance(flat, dict):
        extensions["x_kernel_flat_v4"] = {k: v for k, v in flat.items() if k not in HEAVY}
    return message


def hero_seat(directories, game_id, model):
    for path in (p for d in directories for p in d.glob(f"{game_id}.p[01].jsonl")):
        header = next(read_lines(path), {})
        if header.get("kind") == "header" and header.get("bot_name") == model:
            return header["seat"]
    return None


def screened(seat_decision):
    return any(name in json.dumps(c.get("display_text", "")) for c in seat_decision["candidates"] for name in COMBO_CARDS)


def check_game(records, engine_module, args, out):
    """Replay one game; returns (rows, summary-entry) or a mismatch reason."""
    peer = engine_module.NativePeer(str(args.bridge))
    try:
        engine = engine_module.KernelEngine(peer, json.loads(args.catalog.read_bytes()),
                                            source_revision=args.source_revision, known_cards=True)
        reset = next(r["message"] for r in records if r["message"].get("request_type") == "reset")
        hero = hero_seat(args.decisions, reset["game_id"], args.model)
        if hero is None:
            return None
        deck = reset["seats"][int(hero[1])]["deck"].get("catalog_id")
        rows, searched, decision_index, outcome, last_turn = [], set(), -1, None, None
        expected = iter([r for r in records if r["dir"] == "engine_to_host"])
        for record in records:
            if record["dir"] != "host_to_engine":
                continue
            message = record["message"]
            answer = json.loads(engine.handle(engine_module.wire.canonical_json_dumps(message)))
            recorded = next(expected, None)
            if recorded is None or slim(answer) != recorded["message"]:
                return {"game_id": reset["game_id"], "hero": hero, "deck": deck, "replay": "mismatch",
                        "at_request": message.get("request_type"), "decisions": decision_index + 1}, rows
            if answer.get("response_type") == "terminal":
                outcome = answer
                break
            if answer.get("response_type") != "decision":
                continue
            decision_index += 1
            sd = answer["seat_decision"]
            last_turn = sd["observation"]["turn"]
            native = engine.current
            if sd["acting_seat"] != hero or native.get("response_type") != "decision" or native["step"] in searched:
                continue
            searched.add(native["step"])
            focus = screened(sd)
            budget = args.focus_nodes if focus else args.nodes
            started = time.perf_counter()
            result = peer.request({"request_type": "win_search", "game_id": engine.game, "expected_step": native["step"],
                                   "max_nodes": budget, "max_depth": args.depth,
                                   "world_seeds": [(native["step"] << 8) + k for k in range(args.worlds)]})
            if result.get("response_type") != "private_win_search":
                raise RuntimeError(f"bridge refused win_search: {result}")
            obs = sd["observation"]
            row = {"runtime": args.runtime, "source": "spellbench", "game_id": reset["game_id"], "hero": hero, "deck": deck, "decision": f"d{decision_index}",
                   "native_step": native["step"], "turn": obs["turn"], "phase": obs["phase_step"],
                   "screen": focus, "verdict": result["oracle"]["verdict"], "oracle": result["oracle"],
                   "robust": result["robust"], "max_nodes": budget, "max_depth": args.depth,
                   "seconds": round(time.perf_counter() - started, 3)}
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
        return {"runtime": args.runtime, "game_id": reset["game_id"], "hero": hero, "deck": deck, "replay": "verified" if outcome else "unfinished",
                "winner": (outcome or {}).get("winner"), "final_turn": last_turn,
                "decisions": decision_index + 1}, rows
    finally:
        peer.close()


def summarize(games, rows):
    by_turn = {}
    for row in rows:
        by_turn.setdefault((row["game_id"], row["turn"]), []).append(row)
    available, taken, missed = [], [], []
    final = {g["game_id"]: g for g in games}
    for (game_id, turn), turn_rows in sorted(by_turn.items()):
        proven = [r for r in turn_rows if r["verdict"] == "proven"]
        if not proven:
            continue
        game = final[game_id]
        entry = {"game_id": game_id, "turn": turn, "first_proven": proven[0]["decision"],
                 "proven_decisions": [r["decision"] for r in proven]}
        available.append(entry)
        won_now = game.get("winner") == game["hero"] and game.get("final_turn") == turn
        (taken if won_now else missed).append(entry)
    return {"kind": "summary", "runtime": sorted({g["runtime"] for g in games}), "games": len(games), "replay_verified": sum(g["replay"] == "verified" for g in games),
            "checked_decisions": len(rows), "proven": sum(r["verdict"] == "proven" for r in rows),
            "refuted": sum(r["verdict"] == "refuted" for r in rows), "unknown": sum(r["verdict"] == "unknown" for r in rows),
            "available_turns": len(available), "taken": len(taken), "missed": len(missed),
            "taken_refs": taken, "missed_refs": missed, "model_wins": sum(g.get("winner") == g["hero"] for g in games)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transcripts", type=Path, nargs="+", required=True)
    parser.add_argument("--decisions", type=Path, nargs="+", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--engine-py", type=Path, required=True, help="the kernel_engine_v2.py that played the games")
    parser.add_argument("--bridge", type=Path, required=True, help="agent_bridge_v1 built with win_search")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--runtime", required=True,
                        help="runtime identity of the played games, e.g. historical@92ec2393 (the Spellbench bridge has no runtime_rules)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=2000)
    parser.add_argument("--focus-nodes", type=int, default=200000)
    parser.add_argument("--depth", type=int, default=400)
    parser.add_argument("--worlds", type=int, default=4, help="resampled worlds for the robust estimand")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(args.engine_py.parent))
    spec = importlib.util.spec_from_file_location("kernel_engine_v2", args.engine_py)
    engine_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine_module)
    paths = []
    for path in args.transcripts:
        paths += sorted(p for p in path.rglob("*") if re.search(r"(tap-.*|engine)\.jsonl(\.gz)?$", p.name)) if path.is_dir() else [path]
    games, rows = [], []
    with args.out.open("w", encoding="utf-8") as out:
        for path in paths:
            records = list(read_lines(path))
            if not any(r["message"].get("request_type") == "reset" for r in records if isinstance(r.get("message"), dict)):
                continue
            checked = check_game(records, engine_module, args, out)
            if checked is None:
                continue
            game, game_rows = checked
            games.append(game)
            rows += game_rows
            out.write(json.dumps({"kind": "game", **game}) + "\n")
            out.flush()
            print(json.dumps(game), flush=True)
        summary = summarize(games, rows)
        out.write(json.dumps(summary) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("_refs")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
