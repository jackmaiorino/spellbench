"""Turn Spellbench engine transcripts plus kernel bot decision logs into Decision Studio recordings.

usage: convert.py --transcripts DIR_OR_FILE... --decisions DIR... --model NAME --out DIR

Transcripts are engine wire logs: engine_tap.py files or the operator recording's
engine.jsonl (both hold {"dir", "message"} lines). Decision logs come from
kernel_flat_bot.py --decision-log (spellbench-kernel-bot-log/v1). The featured
seat is the one whose decision log names --model, so the same converter reads
model-vs-model batches and games against a human. Each game becomes one
mtg-kernel-viewer-recording/v1 file (mtg-kernel viewer/src/recording.ts) from
the model's perspective: its hand and its legal menu with the model's softmax
over its logits and its value estimate; opposing hands stay hidden and opposing
decisions show only the executed move. OUT/index.json lists the games for the
review server. Outputs carry hidden game state: keep them local.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any, Iterator

SCHEMA = "mtg-kernel-viewer-recording/v1"
COLORS = ("W", "U", "B", "R", "G", "C")
HIDDEN = "Hidden card"
# Opposing choices whose text could name cards the featured seat never saw.
PRIVATE_KINDS = {"order", "arrange", "choose_name", "mulligan", "keep_or_mulligan", "select"}
VALUE_SCALE = "Value head output for the acting seat (higher is better for the model)."


def float_bits(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def read_lines(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def transcripts(paths: list[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.is_file() and re.search(r"(tap-.*|engine)\.jsonl(\.gz)?$", p.name))
        else:
            yield path


def games(path: Path) -> Iterator[dict]:
    """Split one wire transcript into games: reset, then alternating decisions and steps, then a terminal."""
    game = None
    for record in read_lines(path):
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        if record["dir"] == "host_to_engine" and message.get("request_type") == "reset":
            game = {"reset": message, "decisions": [], "selections": [], "terminal": None, "source": path}
        elif game is None:
            continue
        elif record["dir"] == "host_to_engine" and message.get("request_type") == "step":
            game["selections"].append(message["selection"]["candidate_id"])
        elif message.get("response_type") == "decision":
            game["decisions"].append(message)
        elif message.get("response_type") == "terminal":
            game["terminal"] = message
            yield game
            game = None
    if game is not None and game["decisions"]:
        yield game


def decision_logs(directories: list[Path], game_id: str) -> dict[str, dict]:
    """seat -> {"header", "name", "steps": {seat_step: record}} for each logged seat of one game."""
    logs = {}
    for path in (p for d in directories for p in d.glob(f"{game_id}.p[01].jsonl")):
        records = list(read_lines(path))
        if records and records[0].get("kind") == "header":
            header = records[0]
            # Only the kernel bot's log carries logits; a human client log (spellbench-human-log/v1) names the seat.
            model = header.get("schema") == "spellbench-kernel-bot-log/v1"
            logs[header["seat"]] = {"header": header, "name": header.get("bot_name") or header.get("label") or "Human",
                                    "steps": {r["step"]: r for r in records[1:] if model and r.get("kind") == "decision"}}
    return logs


def q64(weights: list[float]) -> list[str]:
    """Exact integer masses over 2^64 (largest remainder on integer weights), so the viewer's exact-sum check holds."""
    total = 1 << 64
    scaled = [int(w * (1 << 53)) for w in weights]
    whole = sum(scaled)
    masses = [s * total // whole for s in scaled]
    order = sorted(range(len(scaled)), key=lambda i: scaled[i] * total % whole, reverse=True)
    for i in order[:total - sum(masses)]:
        masses[i] += 1
    return [str(m) for m in masses]


def policy(decision: dict, log: dict | None, executed: int) -> dict | None:
    if log is None:
        return None
    sd = decision["seat_decision"]
    record = log["steps"].get(sd.get("seat_step"))
    rows = ((sd.get("extensions") or {}).get("x_kernel_flat_v4") or {}).get("row_candidate_ids")
    if record is None or not isinstance(rows, list) or len(record["logits_bits"]) != len(rows):
        return None
    logits = [float_bits(b) for b in record["logits_bits"]]
    top = max(logits)
    weights = [math.exp(x - top) for x in logits]
    by_candidate = [0.0] * len(sd["candidates"])
    for row, weight in zip(rows, weights):
        by_candidate[row] = weight
    value = record.get("value_bits")
    return {"kind": "hamilton_q64", "masses": q64(by_candidate), "sampled": executed,
            "value": float_bits(value) if isinstance(value, int) else 0.0, "valueScale": VALUE_SCALE}


class Projector:
    """Map observations to the viewer's board from the featured seat's side."""

    def __init__(self, perspective: str) -> None:
        self.perspective = perspective
        self.cards: dict[str, dict] = {}

    def card(self, record: dict) -> str:
        name = record.get("card_name") or record.get("full_name") or HIDDEN
        if name not in self.cards:
            ch = record.get("characteristics") or {}
            types = " ".join(t.title() for t in [*(ch.get("supertypes") or []), *(ch.get("types") or [])])
            subtypes = " ".join(t.title() for t in ch.get("subtypes") or [])
            keywords = ", ".join(k.replace("_", " ").title() for k in ch.get("keywords") or [] if isinstance(k, str))
            self.cards[name] = {
                "id": name, "name": name, "manaCost": "" if ch.get("mana_value") is None else f"MV {ch['mana_value']}",
                "type": f"{types} - {subtypes}" if subtypes else types, "rules": keywords,
                "image": None, "printing": None, "face": 0,
            }
        return name

    def obj(self, record: dict) -> dict:
        ch = record.get("characteristics") or {}
        permanent = record.get("permanent") or {}
        counters = permanent.get("counters") or {}
        if isinstance(counters, list):
            counters = {str(c.get("kind", c.get("name", "counter"))): int(c.get("count", 0)) for c in counters if isinstance(c, dict)}
        power, toughness = ch.get("power"), ch.get("toughness")
        return {
            "id": str(record["object_id"]), "card": self.card(record),
            "owner": record.get("owner_seat") or self.perspective, "controller": record.get("controller_seat") or record.get("owner_seat") or self.perspective,
            "tapped": bool(permanent.get("tapped")),
            "power": power if isinstance(power, int) else None, "toughness": toughness if isinstance(toughness, int) else None,
            "damage": max(0, int(permanent.get("damage") or 0)),
            "counters": {k: int(v) for k, v in counters.items() if isinstance(v, int) and v >= 0},
            "token": bool(record.get("token")),
        }

    def board(self, observation: dict) -> dict:
        players, exile, combat = [], [], []
        for seat in ("p0", "p1"):
            p = next(x for x in observation["players"] if x["seat"] == seat)
            pool = p.get("mana_pool") or {}
            hand = [self.obj(r) for r in p.get("hand") or []] if seat == self.perspective and observation.get("viewer") == seat else []
            players.append({
                "life": int(p["life"]), "handCount": int(p.get("hand_count") or 0), "libraryCount": int(p.get("library_count") or 0),
                "mana": [max(0, int(pool.get(c) or 0)) for c in COLORS],
                "battlefield": [self.obj(r) for r in p.get("battlefield") or []],
                "graveyard": [self.obj(r) for r in p.get("graveyard") or []], "hand": hand,
            })
            exile += [self.obj(r) for r in p.get("exile") or []]
            for r in p.get("battlefield") or []:
                if (r.get("permanent") or {}).get("attacking"):
                    combat.append({"attacker": str(r["object_id"]), "blockers": []})
        present = {o["id"] for pl in players for z in ("battlefield", "graveyard", "hand") for o in pl[z]} | {o["id"] for o in exile}
        by_attacker = {c["attacker"]: c for c in combat}
        for p in observation["players"]:
            for r in p.get("battlefield") or []:
                for attacker in object_refs((r.get("permanent") or {}).get("blocked_attackers") or []):
                    if attacker in by_attacker:
                        by_attacker[attacker]["blockers"].append(str(r["object_id"]))
        stack = []
        for i, s in enumerate(observation.get("stack") or []):
            source = s.get("source")
            source_id = str(source["object_id"]) if isinstance(source, dict) and str(source.get("object_id")) in present else None
            targets = list(object_refs(s.get("targets") or []))
            name = s.get("card_name") or (source.get("card_name") if isinstance(source, dict) else None) or s.get("text") or s.get("stack_kind") or "Stack item"
            if s.get("text") and s.get("stack_kind") != "spell":
                name = f"{name}: {s['text']}"
            stack.append({"id": f"stack-{s.get('object_id', i)}", "name": str(name)[:4096], "controller": s.get("controller_seat") or observation["active_seat"],
                          "source": source_id, "targets": targets})
        priority = observation.get("priority_seat") or observation["active_seat"]
        return {"turn": max(0, int(observation["turn"])), "phase": observation["phase_step"], "active": observation["active_seat"],
                "priority": priority, "players": players, "exile": exile, "stack": stack,
                "combat": [c for c in combat if c["attacker"] in present]}


def object_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        if value.get("object_id") is not None:
            yield str(value["object_id"])
        for v in value.values():
            yield from object_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from object_refs(v)


def visible_ids(*boards: dict) -> set[str]:
    ids = set()
    for b in boards:
        for p in b["players"]:
            for zone in ("battlefield", "graveyard", "hand"):
                ids |= {o["id"] for o in p[zone]}
        ids |= {o["id"] for o in b["exile"]} | {s["source"] for s in b["stack"] if s["source"]}
    return ids


def action(candidate: dict, index: int, visible: set[str], private: bool) -> dict:
    semantic = candidate.get("semantic") or {}
    kind = str(semantic.get("kind", "choice"))
    label = candidate.get("display_text") or kind.replace("_", " ")
    if private:
        label = f"Opponent: {kind.replace('_', ' ')} (private choice)"
    refs = [] if private else list(dict.fromkeys(r for r in object_refs(semantic) if r in visible))
    return {"index": index, "label": str(label)[:4096], "kind": kind, "refs": refs}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:96] or "game"


def convert(game: dict, logs: dict[str, dict], model: str) -> dict | None:
    perspective = next((seat for seat, log in logs.items() if log["header"].get("bot_name") == model), None)
    if perspective is None:
        return None
    reset, project = game["reset"], Projector(perspective)
    boards = [project.board(d["seat_decision"]["observation"]) for d in game["decisions"]]
    frames = []
    for i, decision in enumerate(game["decisions"]):
        sd = decision["seat_decision"]
        actor = sd["acting_seat"]
        if i >= len(game["selections"]):
            break
        chosen = game["selections"][i]
        executed = next(j for j, c in enumerate(sd["candidates"]) if c["candidate_id"] == chosen)
        board, after = boards[i], boards[i + 1] if i + 1 < len(boards) else boards[i]
        visible = visible_ids(board, after)
        terminal = None
        if i + 1 == len(game["decisions"]) and game["terminal"]:
            t = game["terminal"]
            terminal = {"kind": f"{t.get('classification')}: {t.get('reason')}", "winner": t.get("winner") if t.get("winner") in ("p0", "p1") else None}
        if actor == perspective:
            actions = [action(c, j, visible, False) for j, c in enumerate(sd["candidates"])]
            frame_policy = policy(decision, logs.get(actor), executed)
        else:
            kind = str((sd["candidates"][executed].get("semantic") or {}).get("kind", ""))
            actions = [action(sd["candidates"][executed], 0, visible, kind in PRIVATE_KINDS)]
            executed, frame_policy = 0, None
        frames.append({"id": f"d{i}", "key": {"episode": 0, "step": i, "physical": int(decision["step"]), "substep": 0, "actor": actor},
                       "board": board, "after": after, "actions": actions, "executed": executed,
                       "policy": frame_policy, "search": None, "terminal": terminal})
    if not frames:
        return None
    decks = [s["deck"].get("catalog_id") or s["deck"].get("deck_id", "deck") for s in reset["seats"]]
    names = [logs[s]["name"] if s in logs else "Opponent" for s in ("p0", "p1")]
    t = game["terminal"]
    winner = t.get("winner") if t else None
    result = "unfinished" if t is None else "draw" if winner not in ("p0", "p1") else "won" if winner == perspective else "lost"
    other = "p1" if perspective == "p0" else "p0"
    digest = hashlib.sha256(Path(game["source"]).read_bytes()).hexdigest()
    title = f"{decks[int(perspective[1])]} vs {decks[int(other[1])]} · model {result}"
    return {
        "schema": SCHEMA, "id": slug(f"{reset['game_id']}"), "title": title,
        "description": f"{names[int(perspective[1])]} ({perspective}) against {names[int(other[1])]}; {len(frames)} decisions; "
                       "policy masses are the softmax of the model's logits, the value is its value head.",
        "perspective": perspective, "complete": bool(t), "coverage": "every-step",
        "identity": {"source": reset["game_id"], "runtime": "spellbench engine transcript",
                     "checkpoint": logs[perspective]["header"].get("model_state_sha256", "unknown"),
                     "cardDatabase": "kernel catalog names", "sourceSha256": digest},
        "seats": [{"name": names[0], "deck": decks[0]}, {"name": names[1], "deck": decks[1]}],
        "cards": project.cards, "frames": frames, "bookmarks": [],
    }, {"subtitle": f"{names[int(other[1])]} · {len(frames)} decisions", "result": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transcripts", type=Path, nargs="+", required=True)
    parser.add_argument("--decisions", type=Path, nargs="+", default=[])
    parser.add_argument("--model", required=True, help="bot_name of the featured model in its decision log")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    index_path = args.out / "index.json"
    index = {g["id"]: g for g in json.loads(index_path.read_text())} if index_path.exists() else {}
    done = {(g.get("source"), g.get("source_bytes")) for g in index.values()}
    for path in transcripts(args.transcripts):
        source = (str(path), path.stat().st_size)
        if source in done:
            continue  # converted already and unchanged since
        for game in games(path):
            converted = convert(game, decision_logs(args.decisions, game["reset"]["game_id"]), args.model)
            if converted is None:
                continue
            recording, extra = converted
            file = f"{recording['id']}.json"
            (args.out / file).write_text(json.dumps(recording, separators=(",", ":")), encoding="utf-8")
            index[recording["id"]] = {"id": recording["id"], "file": file, "title": recording["title"], **extra,
                                      "source": source[0], "source_bytes": source[1]}
            print(f"{file}: {recording['title']} ({len(recording['frames'])} decisions)")
    index_path.write_text(json.dumps(sorted(index.values(), key=lambda g: g["id"]), indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
