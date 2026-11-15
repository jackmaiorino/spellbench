#!/usr/bin/env python3
"""Generate the human-only London board `pauper-london-human-v1` from the rated board.

Human games are unrated. This writes a COPY of `pauper-ladder-v2` into a scratch folder, never into the repository's
`benchmarks/` and never over the rated board: the rated board's files are only read. The copy

- loses every ladder and rating field (as the human launchers already do),
- names the human-only London engine (`kernel_engine_london_human_v1.py`, the London bridge, `x_kernel_flat_v7`)
  and declares London mulligans (`rules.mulligan` stays `auto`, which resolves to London because that engine declares
  it),
- keeps the anchors (`uniform`, `heuristic`) and adds the London entrants registered by `add_london_entrant.py`,
- gets a local values file: the rated one plus the London placeholders.

Usage:
    python tools/make_london_human_board.py --rated-board <benchmarks/pauper-ladder-v2/benchmark.json> \
        --rated-local <benchmarks/local.json> --out <scratch>/human-benchmark/pauper-london-human-v1 \
        --registry <inputs>/london-entrants.json --bridge <agent_bridge_v1.exe> --engine-revision <commit>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BOARD_ID = "pauper-london-human-v1"
ENGINE = REPO / "integrations/mtg_kernel/london_human/kernel_engine_london_human_v1.py"
BOT = REPO / "integrations/mtg_kernel/london_human/kernel_flat_bot_london_human_v1.py"
LADDER_FIELDS = ("ladder", "opponent_panel", "evaluation_version", "evaluation_targets", "evaluation_matchups",
                 "evaluation_engine_identity", "evaluation_engine_inputs")
KEPT_BOTS = ("uniform", "heuristic")
KEEP_SEVEN_NAME_PART = "keep7"
KEEP_SEVEN_SUFFIX = " (keeps seven, test)"


def placeholder(name: str) -> str:
    return "MTG_KERNEL_LONDON_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def check_keep_seven(entrant: dict) -> None:
    """The keep-seven test mode and the name part ``keep7`` go together, in either direction."""
    name = entrant["name"]
    if bool(entrant.get("keep_seven_test")) != (KEEP_SEVEN_NAME_PART in name):
        raise SystemExit(f"{name}: a keep-seven test entrant's name carries {KEEP_SEVEN_NAME_PART!r} and no other "
                         f"entrant's does (keep_seven_test is {bool(entrant.get('keep_seven_test'))})")


def shown_label(entrant: dict) -> str:
    """The table name. A keep-seven test entrant always ends in ``(keeps seven, test)``, derived here and never
    taken from the registry; any other entrant that carries those words is refused."""
    label = entrant.get("label") or entrant["name"]
    plain = label[:-len(KEEP_SEVEN_SUFFIX)] if entrant.get("keep_seven_test") and label.endswith(KEEP_SEVEN_SUFFIX) else label
    if "keeps seven" in plain.lower():
        raise SystemExit(f"{entrant['name']}: the label {label!r} claims a keep-seven bot; only the test mode may")
    return plain + KEEP_SEVEN_SUFFIX if entrant.get("keep_seven_test") else plain


def rated_identity(board: dict) -> tuple[str | None, str | None]:
    """The owner and author fields the rated board's own mtg-kernel entries carry, copied (never written here)."""
    for bot in board.get("bots", []):
        if bot.get("engine") == "mtg-kernel" and bot.get("type") == "subprocess":
            return bot.get("owner"), (bot.get("display") or {}).get("author")
    return None, None


def bot_entry(entrant: dict, owner: str | None = None, author: str | None = None, allow_numeric_fill: bool = False) -> dict:
    check_keep_seven(entrant)
    name = entrant["name"]
    key = placeholder(name)
    command = ["${PYTHON}", "${MTG_KERNEL_LONDON_HUMAN_BOT}", "--scorer", "${MTG_KERNEL_SCORER}",
               "--config", "${" + key + "_SCORER_CONFIG}", "--name", name, "--version", "pauper-london-human-v1"]
    if entrant.get("model_state_sha256"):
        command += ["--expect-model-state", entrant["model_state_sha256"]]
    if entrant.get("keep_seven_test"):
        command += ["--test-keep-seven"]
    if allow_numeric_fill:
        command += ["--allow-numeric-v4-fill"]
    return {"name": name, "version": "pauper-london-human-v1", "type": "subprocess", "owner": owner,
            "engine": "mtg-kernel", "training_style_tags": ["reinforcement-learning"], "command": command,
            "checkpoint": "${" + key + "_CHECKPOINT}",
            "display": {"label": shown_label(entrant), "author": author, "url": None,
                        "description": entrant.get("description") or "A FlatV7 policy for London human play. Human "
                        "games are unrated and never training data."}}


def make(rated_board: Path, rated_local: Path, registry: Path, bridge: str, engine_revision: str,
         catalog: str | None = None, allow_numeric_fill: bool = False) -> tuple[dict, dict]:
    board = json.loads(rated_board.read_text(encoding="utf-8"))
    local = json.loads(rated_local.read_text(encoding="utf-8"))
    owner, author = rated_identity(board)
    for field in LADDER_FIELDS:
        board.pop(field, None)
    board["id"] = BOARD_ID
    board["title"] = "Pauper · mtg-kernel London (human play)"
    board["summary"] = ("A human-only copy of the pauper-ladder-v2 board with London mulligans for both seats. "
                        "Unrated: its engine, bridge and bots are not those of any rated board.")
    board["engine"] = {"name": "mtg-kernel", "command": [
        "${PYTHON}", "${MTG_KERNEL_LONDON_HUMAN_ENGINE}", "--bridge", "${MTG_KERNEL_LONDON_HUMAN_BRIDGE}",
        "--catalog", "${MTG_KERNEL_PUBLIC_CATALOG}", "--source-revision", engine_revision]}
    board["extensions"] = ["x_kernel_flat_v7", "x_public_history_v1"]
    board["native_id_audits"] = {"x_kernel_flat_v7": "docs/pauper-london-human-v1.md#visibility-and-policy-inputs"}
    entrants = json.loads(registry.read_text(encoding="utf-8")).get("entrants", [])
    for entrant in entrants:
        check_keep_seven(entrant)
    names = [entrant["name"] for entrant in entrants]
    if len(set(names)) != len(names) or len({placeholder(name) for name in names}) != len(names):
        raise SystemExit("duplicate entrant names in the registry (names that differ only in punctuation share "
                         "a placeholder and so a scorer config)")
    anchors = [bot for bot in board["bots"] if bot["name"] in KEPT_BOTS]
    if [bot["name"] for bot in anchors] != list(KEPT_BOTS):
        raise SystemExit("the rated board lost its uniform and heuristic anchors")
    for bot in anchors:
        bot.pop("evaluation_identity", None)
    board["bots"] = anchors + [bot_entry(entrant, owner, author, allow_numeric_fill) for entrant in entrants]
    values = dict(local)
    values["MTG_KERNEL_LONDON_HUMAN_ENGINE"] = str(ENGINE).replace("\\", "/")
    values["MTG_KERNEL_LONDON_HUMAN_BOT"] = str(BOT).replace("\\", "/")
    values["MTG_KERNEL_LONDON_HUMAN_BRIDGE"] = bridge
    if catalog:
        values["MTG_KERNEL_PUBLIC_CATALOG"] = catalog
    for entrant in entrants:
        key = placeholder(entrant["name"])
        values[key + "_SCORER_CONFIG"] = entrant["scorer_config"]
        values[key + "_CHECKPOINT"] = entrant["checkpoint"]
    return board, values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rated-board", type=Path, required=True)
    parser.add_argument("--rated-local", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="the human board folder to write (scratch, not benchmarks/)")
    parser.add_argument("--bridge", required=True, help="the London human agent_bridge_v1 executable")
    parser.add_argument("--engine-revision", required=True, help="the mtg-kernel commit the bridge was built from")
    parser.add_argument("--catalog", help="the public catalog, when the rated local file does not name it")
    parser.add_argument("--allow-numeric-fill", action="store_true",
                        help="FLOW TESTING ONLY: the learned bots score a numeric choice (Nyxborn Hydra's X) on its V4 "
                             "fill instead of refusing it")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    for guarded in (REPO / "benchmarks", args.rated_board.resolve().parent):
        if guarded == out or guarded in out.parents:
            raise SystemExit(f"refusing to write inside {guarded}: the rated board's folder is never written")
    board, values = make(args.rated_board, args.rated_local, args.registry, args.bridge, args.engine_revision, args.catalog,
                         args.allow_numeric_fill)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (out / "local.json").write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out / 'benchmark.json'} and {out / 'local.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
