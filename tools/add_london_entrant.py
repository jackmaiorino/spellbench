#!/usr/bin/env python3
"""Register a FlatV7 checkpoint as a London human-play opponent.

One command turns an exported checkpoint JSON (the container `export` output of a V7 chain checkpoint, or a V4
checkpoint that the scorer reads under the V7 feature transfer) into a bot the London launcher can play:

1. writes its scorer config (the V7 feature identity as `feature_transfer`, `play_import` and the selection method
   copied from a base config such as Basilisk 2's),
2. starts the pinned scorer on it, checks that it reports the V7 digests, and records its `model_state_sha256`,
3. adds the entrant to the registry the board generator reads (`make_london_human_board.py`).

The bot's mulligan and bottom choices are the model's own: nothing here sets a rule or a lean. `--keep-seven-test`
registers the same checkpoint as a TEST entrant whose bot keeps every opening hand without scoring it (for checking
the human's London flow against an ordinary game while a model's mulligan play is untrained). `--keep-after-mulligan-rule`
registers a model whose seven-card decision and put-backs are its own but whose Keep or Mulligan question after a first
mulligan is answered by a declared rule (keep): a stopgap, named `...keep6...` and labelled so in the table name.

    python tools/add_london_entrant.py --name chains-a-c4-london-test --label "Basilisk 2 (London test)" \
        --checkpoint-json <c4-u1048576.json> --scorer <spellbench_scorer_v1.exe> --base-config <Basilisk 2 config>
    play_manabrew_london.ps1 -Opponent chains-a-c4-london-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

V7_CONTRACT = "1f894f0dcaaeb4e5ac0233e3f39d866c0dddca494f1afc8152107bded0551a4d"
V7_ENCODING = "4c592d136a74240f40b12c638203ab1758ed3cd63748ab7cd2788a60a78850a3"
SCHEMA = "mtg-kernel-spellbench-scorer-config/v1"
READY = "mtg-kernel-spellbench-scorer-ready/v1"
DEFAULT_INPUTS = Path("E:/londonplay-20261114/inputs")
KEEP_RULE_NOTE = ("mulligan decision at seven from the network (partly trained, level still unstable); "
                  "keeps any six by rule")  # the same words as make_london_human_board.KEEP_RULE_NOTE
LEAN_END_UPDATE = 32768  # arm M: the training-only keep offset reaches exactly zero at this fork update


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scorer_config(base: dict, checkpoint: Path, checkpoint_sha256: str) -> dict:
    source = base["source"]
    return {"schema": SCHEMA, "selection": base["selection"], "source": {
        "play_import": source["play_import"],
        "feature_transfer": {"expected_feature_contract_digest": V7_CONTRACT,
                             "expected_feature_encoding_digest": V7_ENCODING},
        "checkpoint": {"path": str(checkpoint).replace("\\", "/"), "sha256": checkpoint_sha256}}}


def chain_label(chain: str, fork_updates: int, lean_end: int) -> tuple[str, bool]:
    """The table name of a chain state and whether the training-only keep lean was still active when the state was
    saved (any state up to ``lean_end`` fork updates trained with a nonzero lean; the lean is never applied at play)."""
    # The offset of fork update u (counting from 0) is b0 * (1 - u / lean_end) for u < lean_end and exactly zero from
    # lean_end on. A state saved after N updates has trained on update N - 1 last, so the lean was active in its
    # training exactly when N <= lean_end (N = lean_end: the last update had a tiny nonzero offset).
    active = fork_updates <= lean_end
    return (f"{chain} at {fork_updates:,} updates (keep lean "
            f"{'still active in training' if active else 'already zero in training'})"), active


def probe(scorer: Path, config: Path) -> dict:
    """The scorer's ready record for ``config``: it must serve the V7 identity."""
    child = subprocess.Popen([str(scorer), "--config", str(config)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    try:
        line = child.stdout.readline()
        ready = json.loads(line) if line else {}
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()
    if ready.get("schema") != READY:
        raise SystemExit(f"the scorer did not become ready on {config}: {child.stderr.read().decode(errors='replace')[:400]}")
    if (ready.get("feature_contract_digest"), ready.get("feature_encoding_digest")) != (V7_CONTRACT, V7_ENCODING):
        raise SystemExit("the scorer does not serve the FlatV7 identity for this checkpoint")
    return ready


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="the bot's name (the launcher's -Opponent)")
    parser.add_argument("--label", help="the name shown in the table (default: the bot's name); not with --chain")
    parser.add_argument("--chain", help="a chain state's name, for example 'arm M m1': the table name is then derived "
                                        "as '<chain> at <N> updates (keep lean ...)' from --fork-updates")
    parser.add_argument("--fork-updates", type=int, help="the chain state's update count since its fork")
    parser.add_argument("--lean-end-update", type=int, default=LEAN_END_UPDATE,
                        help="the fork update at which the training-only keep offset reached zero (default: %(default)s)")
    parser.add_argument("--description")
    parser.add_argument("--checkpoint-json", type=Path, required=True)
    parser.add_argument("--sha256", help="the checkpoint's sha256 (checked against the file; default: computed)")
    parser.add_argument("--scorer", type=Path, required=True, help="the pinned spellbench_scorer_v1 executable")
    parser.add_argument("--base-config", type=Path, required=True,
                        help="a scorer config whose play_import and selection this one copies (Basilisk 2's)")
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--keep-seven-test", action="store_true",
                        help="TEST entrant: the bot keeps every hand without scoring it")
    parser.add_argument("--keep-after-mulligan-rule", action="store_true",
                        help="the bot keeps any hand after its first mulligan without scoring it; the name must "
                             "contain keep6 (and only such an entrant's may)")
    args = parser.parse_args(argv)
    checkpoint = args.checkpoint_json.resolve()
    actual = sha256_file(checkpoint)
    if args.sha256 and args.sha256.lower() != actual:
        raise SystemExit(f"{checkpoint} hashes to {actual}, not {args.sha256}")
    if args.keep_seven_test and "keep7" not in args.name:
        raise SystemExit("a keep-seven test entrant's name must contain keep7, so it is never mistaken for a learned one")
    if not args.keep_seven_test and "keep7" in args.name:
        raise SystemExit("only a --keep-seven-test entrant may carry keep7 in its name")
    if args.keep_after_mulligan_rule and "keep6" not in args.name:
        raise SystemExit("a keep-after-mulligan entrant's name must contain keep6, so it is never mistaken for a learned one")
    if not args.keep_after_mulligan_rule and "keep6" in args.name:
        raise SystemExit("only a --keep-after-mulligan-rule entrant may carry keep6 in its name")
    if args.keep_after_mulligan_rule and args.keep_seven_test:
        raise SystemExit("--keep-after-mulligan-rule and --keep-seven-test are different bots: not both")
    label, lean_active = args.label, None
    if args.keep_seven_test:  # the table name of a test entrant always says so (the board generator derives it again)
        plain = (label or args.name).removesuffix(" (keeps seven, test)")
        label = plain + " (keeps seven, test)"
    if args.chain or args.fork_updates is not None:
        if not args.chain or args.fork_updates is None or args.fork_updates < 0:
            raise SystemExit("--chain and --fork-updates (a nonnegative count) go together")
        if args.label or args.keep_seven_test:
            raise SystemExit("--chain derives the table name: do not pass --label or --keep-seven-test with it")
        label, lean_active = chain_label(args.chain, args.fork_updates, args.lean_end_update)
        if args.keep_after_mulligan_rule:  # the table name says the rule: the chain state, then the stopgap's own words
            label = f"{args.chain} at {args.fork_updates:,} updates: {KEEP_RULE_NOTE}"
    elif args.keep_after_mulligan_rule:
        label = (label or args.name).removesuffix(": " + KEEP_RULE_NOTE) + ": " + KEEP_RULE_NOTE
    base = json.loads(args.base_config.read_text(encoding="utf-8"))
    args.inputs_dir.mkdir(parents=True, exist_ok=True)
    config = args.inputs_dir / f"{args.name}.scorer.json"
    config.write_text(json.dumps(scorer_config(base, checkpoint, actual), indent=2) + "\n", encoding="utf-8", newline="\n")
    ready = probe(args.scorer, config)
    state = ready["model_state_sha256"]
    registry = args.registry or args.inputs_dir / "london-entrants.json"
    document = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else {"entrants": []}
    document["entrants"] = [e for e in document["entrants"] if e["name"] != args.name]
    description = args.description
    if args.keep_after_mulligan_rule and not description:
        description = ("STOPGAP entrant: at seven cards the model decides Keep or Mulligan itself, as it samples every "
                       "decision (no keep lean at play time). After one mulligan the bot keeps any hand by a declared rule, "
                       "without asking the model; its put-back choice is its own. Not the finished mulligan model.")
    elif lean_active is not None and not description:
        description = ("A chain state of the arm M mulligan lineage, played as saved: its mulligan and bottom choices are "
                       "the model's own. The keep lean of its training is never applied at play time.")
    document["entrants"].append({
        "name": args.name, "label": label or args.name, "description": description,
        "chain": ({"name": args.chain, "fork_updates": args.fork_updates, "lean_end_update": args.lean_end_update,
                   "lean_active_when_saved": lean_active} if lean_active is not None else None),
        "scorer_config": str(config).replace("\\", "/"), "checkpoint": str(checkpoint).replace("\\", "/"),
        "checkpoint_sha256": actual, "model_state_sha256": state, "selection": base["selection"],
        "keep_seven_test": bool(args.keep_seven_test),
        "keep_after_mulligan_rule": bool(args.keep_after_mulligan_rule)})
    registry.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"registered {args.name}: scorer config {config}")
    print(f"  table name: {label or args.name}")
    print(f"  checkpoint sha256 {actual}\n  model state sha256 {state}\n  adam step {ready.get('model', {}).get('adam_step')}")
    print(f"  play it: play_manabrew_london.ps1 -Opponent {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
