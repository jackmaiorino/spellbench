"""Wrapper-level proof of the bot's native groups (``--native-seat``): seeded games through the London human engine
with the real bridge and the bot's real scorer, one replay trace per game for mtg-kernel's replay test.

Every game: the bot's seat on its training window rule (action-windows-v1) with its grouped decisions native, the
person's seat on the HarnessV2 windows (no engine windows, so the trainer's other seat has the same windows), the
graveyard rule as human play has it, both seats' protocol decisions answered with seeded picks (the person's grouped
decisions through their proposals, as in play). The bot's scorer samples every native question. The engine writes
each game's trace (the bridge reset, every native step with its row map, the model input of each of the bot's native
questions); mtg-kernel ``human_native_groups_replay`` replays the traces on the trainer's own London session and
compares, at every one of the bot's native questions, the acting seat, the row count and the model input.

    python native_groups_proof_v1.py OUT --bridge EXE --catalog JSON --scorer-config JSON --scorer EXE
        [--seeds 7,31] [--expect-model-state SHA256]

Writes OUT/traces/<game>.jsonl, OUT/native.jsonl (the engine's native-question log) and OUT/summary.json (games,
natural endings, the bot's native questions by group kind, per game).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "python"))

import kernel_flat_bot_london_human_v1 as flat_bot  # noqa: E402
from kernel_engine_london_human_v1 import FLAT, HISTORY, KernelEngine, NativePeer, check_native_scorer  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402

# The decks human play offers (Elves and Wildfire are left out of London sessions: a numeric X the model input
# cannot encode).
DECKS = ["Rally", "Affinity", "Spy", "Burn", "CawGates", "Faeries"]
PERSON, BOT = "p0", "p1"


def reset_value(catalog: dict, game: str, *, first: str, person: str, bot: str) -> dict:
    decks = {e["catalog_id"]: e["decklist"] for e in catalog["catalog"]}
    names = [r["name"] for d in (person, bot) for r in decks[d]]
    rules = {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned",
             "starting_seat": first, "card_name_domain": card_name_domain(names),
             "extensions": [FLAT, HISTORY], "probe": False}
    return {"protocol": "spellbench/v2", "request_type": "reset", "game_id": game, "format": "pauper-bo1",
            "seats": [{"seat": "p0", "deck": {"catalog_id": person, "deck_id": deck_id(decks[person])}},
                      {"seat": "p1", "deck": {"catalog_id": bot, "deck_id": deck_id(decks[bot])}}],
            "rules": rules, "game_secret": hashlib.sha256(game.encode()).hexdigest(),
            "max_decisions": 1 << 20, "max_steps": 1 << 20}


def pick(sd: dict, rng: random.Random) -> int:
    """Keep, play lands, cast what can be cast; otherwise a seeded candidate."""
    semantics = [c["semantic"] for c in sd["candidates"]]
    keep = [i for i, s in enumerate(semantics) if s["kind"] == "mulligan" and s["keep"]]
    act = [i for i, s in enumerate(semantics) if s["kind"] in ("play_land", "cast_spell")]
    return (keep or act or [rng.randrange(len(semantics))])[0] if rng.random() < 0.8 else rng.randrange(len(semantics))


def play(args, catalog: dict, scorer, game: str, seed: int, *, first: str, person: str, bot: str) -> dict:
    peer = NativePeer(args.bridge)
    engine = KernelEngine(peer, catalog, auto_graveyard_order=True, action_windows_seat=BOT, native_seat=BOT,
                          native_scorer=scorer, native_seed=seed, native_log=args.out / "native.jsonl",
                          native_trace=args.out / "traces")
    serial = 0

    def send(value: dict) -> dict:
        nonlocal serial
        serial += 1
        return wire.strict_json_loads(engine.handle(wire.canonical_json_dumps({**value, "request_id": f"q{serial}"})))

    rng = random.Random(f"{game}:picks")
    try:
        current = send(reset_value(catalog, game, first=first, person=person, bot=bot))
        if current["response_type"] == "error":
            return {"game": game, "refused": current["error"]}
        for _ in range(60_000):
            if current["response_type"] != "decision":
                return {"game": game, "classification": current["classification"], "steps": current["step_count"]}
            sd = current["seat_decision"]
            candidate = pick(sd, rng)
            current = send({"protocol": "spellbench/v2", "request_type": "step", "game_id": game,
                            "expected_step": current["step"],
                            "selection": {"candidate_id": candidate,
                                          "semantic_echo": sd["candidates"][candidate]["semantic"]}})
        return {"game": game, "classification": "unfinished"}
    finally:
        peer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--scorer", required=True)
    parser.add_argument("--scorer-config", required=True)
    parser.add_argument("--expect-model-state", default=None)
    parser.add_argument("--seeds", default="7,31")
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} is not empty")
    args.out.mkdir(parents=True, exist_ok=True)
    catalog = json.loads(args.catalog.read_bytes())
    scorer = flat_bot.ScorerProcess([args.scorer, "--config", args.scorer_config])
    games = []
    try:
        check_native_scorer(scorer, args.expect_model_state)
        for index, deck in enumerate(DECKS):
            other = DECKS[(index + 3) % len(DECKS)]
            for decks in ((deck, deck), (deck, other)):
                for seed in (int(word) for word in args.seeds.split(",")):
                    for first in ("p0", "p1"):
                        game = f"native-{decks[0]}-{decks[1]}-s{seed}-{first}"
                        result = play(args, catalog, scorer, game, seed, first=first, person=decks[0], bot=decks[1])
                        games.append(result)
                        print(json.dumps(result), flush=True)
    finally:
        scorer.close()
    groups: Counter = Counter()
    per_game: dict[str, Counter] = {}
    log = args.out / "native.jsonl"
    for line in (log.read_text(encoding="utf-8").splitlines() if log.exists() else []):
        record = json.loads(line)
        if record["kind"] == "question":
            groups[record["group"]] += 1
            per_game.setdefault(record["game"], Counter())[record["group"]] += 1
    summary = {"schema": "spellbench-london-human-native-groups-proof/v1", "games": len(games),
               "natural": sum(1 for g in games if g.get("classification") == "natural"),
               "refused": [g for g in games if "refused" in g],
               "not_natural": [g for g in games if "refused" not in g and g.get("classification") != "natural"],
               "native_questions": dict(groups),
               "per_game": {game: dict(counts) for game, counts in sorted(per_game.items())},
               "model_state_sha256": scorer.ready.get("model_state_sha256")}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("games", "natural", "native_questions")}))
    return 0 if summary["natural"] == len(games) else 1


if __name__ == "__main__":
    sys.exit(main())
