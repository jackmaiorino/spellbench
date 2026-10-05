"""Summarize a saved actor-public capture without running a game or sampler.

Example:
    python tools/gorge-inspect-public-capture.py CAPTURE --gorge-source GORGE
"""

from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re
import subprocess

GORGE_COMMIT = "26257e0eda1779d739a07e835c6500b9c4dabc62"


def summarize(capture: Path, gorge_source: Path, recent_count: int) -> dict:
    raw = capture.read_bytes()
    data = json.loads(raw)
    history = data["history"]
    options = data["options"]
    # A live engine/observer is forbidden in an actor-public diagnostic.
    redeal = options["Redeal"]
    if redeal.get("Engine") is not None or redeal.get("Observer") is not None:
        raise ValueError("Capture contains a live Engine or Observer")
    if history.get("Engine") is not None or history.get("Observer") is not None:
        raise ValueError("History contains a live Engine or Observer")
    if not history["ActorBoundaries"] or not history["Frames"]:
        raise ValueError("Capture lacks actor-boundary public history")
    source = subprocess.check_output(
        ["git", "-C", str(gorge_source), "show", f"{GORGE_COMMIT}:events/event.go"],
        text=True,
    )
    block = source.split("GameStart Kind = iota", 1)[1].split("\n)", 1)[0]
    kinds = ["GameStart", *re.findall(r"^\t(\w+)\s*$", block, re.MULTILINE)]
    identities: dict = {}
    draws: Counter = Counter()
    epochs: Counter = Counter()
    counts: Counter = Counter()
    interesting = []
    recent: deque = deque(maxlen=recent_count)
    actor = history["Actor"]
    for index, frame in enumerate(history["Frames"]):
        if frame["Board"].get("Engine") is not None or frame["Board"].get("Observer") is not None:
            raise ValueError(f"Frame {index} contains a live Engine or Observer")
        if frame["Decision"]["Player"] != actor:
            raise ValueError(f"Frame {index} is not an actor boundary")
        for identity in frame.get("Identities") or []:
            identities[identity["ID"]] = identity
        for event_index, event in enumerate(frame.get("Events") or []):
            kind = kinds[event["Kind"]]
            player = event["Player"]
            if kind == "Draw":
                draws[player] += 1
            counts[kind] += 1
            identity = identities.get(event["Obj"], {})
            row = dict(
                frame=index, index=event_index, kind=kind, player=player,
                epoch=epochs[player], draws=draws[player],
                name=identity.get("Name"), owner=identity.get("Owner"),
                from_zone=event["From"], to_zone=event["To"],
                amount=event["Amount"], text=event["Text"],
            )
            if kind in ("Shuffle", "LibraryOrder", "Scry") or (
                kind == "MoveZone" and event["To"] == 1 and event["From"] not in (0, 1)
            ):
                interesting.append(row)
            recent.append(row)
            if kind == "Shuffle":
                epochs[player] += 1
                draws[player] = 0
    last_board = history["Frames"][-1]["Board"]
    return dict(
        capture=str(capture), capture_sha256=hashlib.sha256(raw).hexdigest(),
        gorge_commit=GORGE_COMMIT, actor=actor, frames=len(history["Frames"]),
        answer_count=len(history.get("Answers") or []), options=options,
        work=data["public_reconstruction"], event_counts=dict(sorted(counts.items())),
        interesting=interesting, recent_events=list(recent),
        last_board={k: last_board.get(k) for k in ("turn", "phase", "step", "priority", "active")},
        scope="Saved declared decks and actor-public events only; no game execution",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--gorge-source", type=Path, required=True)
    parser.add_argument("--recent", type=int, default=25)
    args = parser.parse_args()
    if args.recent < 0:
        parser.error("--recent must be nonnegative")
    print(json.dumps(summarize(args.capture, args.gorge_source, args.recent), indent=2))


if __name__ == "__main__":
    main()
