"""One line per game of a human session (evaluation only): outcome, how it ended, and why.

usage: python -m spellbench.human.outcomes RUN_DIR [DECISION_LOG_DIR]
Reads the run's ledger (RUN_DIR/matches.jsonl) and manifest, and, beside the run, the session's ends file
(``<session>.ends.jsonl``, written by ``spellbench.human.session`` for a game the person ended). Each line: game
number, deck, the human's seat (p0 plays first), result for the human, the ledger's classification and reason
(game_over is a natural ending; forfeit:timeout is a spent bank; halted and truncated carry their cause), turns and
human decisions when the decision log has them. A game the person conceded, or whose browser never came back, shows
``conceded`` or ``connection_lost`` as its reason: the arena can only file that as a forfeit of the human seat
(``forfeit:agent_error``), which is shown after it. Same output as the earlier script for every other game.
"""
import json
import sys
from pathlib import Path


def ends_for(run: Path) -> dict:
    """The session's record of person-ended games, by game id (the run directory is ``<session>-gNN``)."""
    session = run.name.rsplit("-g", 1)[0]
    path = run.parent / f"{session}.ends.jsonl"
    if not path.exists():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            found[entry["game_id"]] = entry
    return found


def main(argv: list) -> int:
    run = Path(argv[0])
    logs = Path(argv[1]) if len(argv) > 1 else None
    ledger = run / "matches.jsonl"
    rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()] if ledger.exists() else []
    ends = ends_for(run)
    natural = 0
    for r in sorted(rows, key=lambda r: r["game_index"]):
        seats = {s["name"]: s["seat"] for s in r["seats"]}
        me = seats.get("human")
        if r.get("winner") is None:
            result = "draw" if r["classification"] == "natural" else "no result"
        else:
            result = "WIN" if r["winner"] == me else "loss"
        natural += r["classification"] == "natural"
        deck = r["decks"][0].get("name") or r["decks"][0].get("catalog_id")
        extra = ""
        if logs is not None:
            log = logs / f"{r['game_id']}.{me}.jsonl"
            if log.exists():
                entries = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
                asked = sum(1 for e in entries if e.get("kind") == "decision" and e.get("how") == "human")
                turns = max((e.get("turn") or 0 for e in entries if e.get("kind") == "decision"), default=0)
                extra = f" turns {turns} human-decisions {asked}"
        ended = ends.get(r["game_id"])
        how = f"{r['classification']}: {r.get('reason')}"
        if ended:
            how = f"{ended['reason']} (by you; the ledger files it as {how})"
        print(f"game {r['game_index'] + 1:2d} {deck:9s} you {me} ({'first' if me == 'p0' else 'second'}) "
              f"{result:9s} {how}{extra}")
    manifest = run / "manifest.json"
    status = json.loads(manifest.read_text(encoding="utf-8")).get("leaderboard_status") if manifest.exists() else "running"
    games = json.loads(manifest.read_text(encoding="utf-8")).get("games", {}) if manifest.exists() else {}
    print(f"{len(rows)} games recorded, {natural} natural; scheduled {games.get('scheduled', '?')}; "
          f"run {'published' if manifest.exists() else 'not yet published'} (leaderboard status {status}, not a game result)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
