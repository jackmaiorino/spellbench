"""Opt-in reveal-aware search entrant with a seeded uniform fallback."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
import json
import os
import subprocess
import sys

from kernel_engine_reveal_search_v4 import (
    INFOSET, WIRE_SCHEMA, ProjectionError, checked_payload, is_digest, opponent_hand,
)
from kernel_search_bot import BotError, PoolProcess, point_line, search_line, spend
from spellbench.bot import serve
from spellbench.builtins.uniform import SplitMix64, UniformBot
from spellbench.reveal_meaning_v3 import RevealReducerV3, SCHEMA

NAME = "kernel-reveal-search-v4"
VERSION = "4.0.0"


class RevealPoolV4(PoolProcess):
    def __init__(self, executable, source, workers):
        self._proc = subprocess.Popen(
            [executable, f"source={source}", "mode=s4a-serve-reveal-v4", "out=-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            env={**os.environ, "REVEAL_V4_SERVE_K": str(workers)},
        )


@dataclass
class GroupSearchV4:
    group_id: int
    text: str
    payload: dict
    remaining: int
    completions: list[tuple[list[int], list[str]]]
    path: list[int] = field(default_factory=list)


def group_completions(value, offered):
    if type(value) is not dict or set(value) != {"keys", "completions"}:
        raise ProjectionError("malformed reveal search composition")
    keys, rows = value["keys"], value["completions"]
    if (type(keys) is not list or not all(map(is_digest, keys)) or len(keys) != len(set(keys)) or
            type(rows) is not list or not 0 < len(rows) <= 512):
        raise ProjectionError("malformed reveal search completion table")
    choices, seen = [], set()
    for row in rows:
        if type(row) is not dict or set(row) != {"wire", "native"}:
            raise ProjectionError("malformed reveal search completion")
        wire, native = row["wire"], row["native"]
        if (type(wire) is not list or not wire or any(type(i) is not int or i < 0 for i in wire) or
                type(native) is not list or not 0 < len(native) <= 4096 or
                any(type(i) is not int or not 0 <= i < len(keys) for i in native) or tuple(wire) in seen):
            raise ProjectionError("invalid reveal search completion")
        choices.append((wire, [keys[i] for i in native]))
        seen.add(tuple(wire))
    if {wire[0] for wire, _ in choices} != offered:
        raise ProjectionError("reveal search completions do not cover the root")
    return choices


class RevealSearchBotV4(UniformBot):
    def __init__(self, pool, *, budget, allowance, a_units):
        super().__init__()
        if any(type(value) is not int or value < 1 for value in (budget, allowance, a_units)):
            raise ValueError("search budget, allowance and overhead must be positive integers")
        self.pool, self.budget, self.allowance, self.a_units = pool, budget, allowance, a_units
        self.remaining = allowance
        self.reducer = RevealReducerV3()
        self.group = None
        self.points = None
        self.tally = Counter()

    def on_game_start(self, game):
        super().on_game_start(game)
        self.reducer = RevealReducerV3()
        self.group = None
        self.points = SplitMix64((game.agent_seed or 0) ^ 0x543B1A5)
        self.remaining = self.allowance
        self.tally.clear()

    def on_game_over(self, game):
        print(json.dumps({"receipt": NAME, "game_id": game.game_id,
                          "spent": self.allowance - self.remaining, "tally": self.tally},
                         sort_keys=True), file=sys.stderr, flush=True)
        self.group = self.points = None
        super().on_game_over(game)

    def _search(self, decision, text, payload, path, width, group=None):
        budget = spend(self.budget, self.a_units, self.remaining,
                       None if group is None else group.remaining)
        if budget is None:
            self.tally["allowance"] += 1
            return None
        root = f"{decision.game_id}/{payload['viewer']}/{payload['sha256']}/{len(path)}"
        charge = self.a_units
        try:
            answer = self.pool.request_line(search_line(root, budget, self.a_units, text, path))
            search = answer.get("search") if answer.get("ok") is True else None
            if type(search) is dict and search.get("root_id") == root:
                reported, units = search.get("charge"), search.get("units")
                if (type(reported) is int and type(units) is int and 0 <= units <= budget and
                        reported == units + self.a_units):
                    charge = reported
                    pick = search.get("pick")
                    if (search.get("payload_sha256") == payload["sha256"] and
                            search.get("incomplete") is False and type(pick) is int and 0 <= pick < width):
                        self.tally["searched_points"] += 1
                        return pick
            elif answer.get("root_id") == root:
                reported = answer.get("charge")
                if type(reported) is int and self.a_units <= reported <= budget + self.a_units:
                    charge = reported
        except (BotError, OSError, ValueError, KeyError):
            pass
        finally:
            self.remaining -= charge
            if group is not None:
                group.remaining -= charge
        self.tally["search_fault"] += 1
        return None

    def _point(self, decision, group, compatible):
        try:
            answer = self.pool.request_line(point_line(group.text, group.path))
            point = answer.get("point") if answer.get("ok") is True else None
        except (BotError, OSError, ValueError, KeyError):
            point = None
        if type(point) is not dict or point.get("viewer_decision") is not True:
            self.tally["group_point_unavailable"] += 1
            return None
        keys = point.get("keys")
        if type(keys) is not list or not keys or not all(map(is_digest, keys)):
            self.tally["group_keys_unavailable"] += 1
            return None
        usable = [index for index, key in enumerate(keys) if key in compatible]
        if not usable:
            self.tally["group_no_match"] += 1
            return None
        pick = (self._search(decision, group.text, group.payload, group.path, len(keys), group)
                if point.get("eligible") is True else None)
        if pick not in usable:
            if pick is not None:
                self.tally["group_search_pick_unmapped"] += 1
            pick = usable[self.points.next() % len(usable)]
        group.path.append(pick)
        return keys[pick]

    def _group_pick(self, decision, group, index, offered):
        while group.completions:
            choices = {wire[index] for wire, _ in group.completions if len(wire) > index}
            if not choices or not choices <= offered:
                break
            depth = len(group.path)
            compatible = {native[depth] for _, native in group.completions if len(native) > depth}
            if len(choices) == 1 or not compatible:
                pick = min(choices)
                group.completions = [(wire, native) for wire, native in group.completions
                                     if len(wire) > index and wire[index] == pick]
                return pick
            key = self._point(decision, group, compatible)
            if key is None:
                break
            group.completions = [(wire, native) for wire, native in group.completions
                                 if len(native) > depth and native[depth] == key]
        self.group = None
        self.tally["group_fallback"] += 1
        return None

    def choose(self, decision):
        fallback = super().choose(decision)
        self.reducer.absorb(decision.extensions.get(SCHEMA))
        offered = {candidate.candidate_id for candidate in decision.candidates}
        group_id, index = decision.group["group_id"], decision.group["substep_index"]
        if self.group is not None:
            if index > 0 and self.group.group_id == group_id:
                pick = self._group_pick(decision, self.group, index, offered)
                return fallback if pick is None else pick
            self.group = None

        ext = decision.extensions.get(INFOSET)
        if ext is None:
            self.tally["no_infoset"] += 1
            return fallback
        if type(ext) is not dict or ext.get("schema") != WIRE_SCHEMA:
            raise ProjectionError("unknown reveal search extension")
        if "refusal" in ext:
            self.tally[ext["refusal"]] += 1
            return fallback
        text = ext.get("payload_json")
        payload = checked_payload(text, opponent_hand(self.reducer.known_hand(), decision.acting_seat))
        if "composition" in ext:
            if ext["composition"] is None:
                self.tally["composition_unavailable"] += 1
                return fallback
            if index != 0:
                raise ProjectionError("reveal search composition was delivered after its root")
            self.group = GroupSearchV4(group_id, text, payload, 2 * (self.budget + self.a_units),
                                       group_completions(ext["composition"], offered))
            pick = self._group_pick(decision, self.group, index, offered)
            return fallback if pick is None else pick

        rows = ext.get("live_candidate_ids")
        if rows is None:
            self.tally["order_map_missing"] += 1
            return fallback
        if (type(rows) is not list or any(type(row) is not int for row in rows) or
                len(rows) != len(offered) or set(rows) != offered):
            raise ProjectionError("invalid reveal search candidate map")
        pick = self._search(decision, text, payload, [], len(rows))
        return fallback if pick is None else rows[pick]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--source", required=True)
    for key in ("workers", "budget", "allowance", "a-units"):
        parser.add_argument(f"--{key}", required=True, type=int)
    args = parser.parse_args()
    if min(args.workers, args.budget, args.allowance, args.a_units) <= 0:
        parser.error("worker count and search limits must be positive")
    pool = RevealPoolV4(args.worker, args.source, args.workers)
    try:
        bot = RevealSearchBotV4(pool, budget=args.budget, allowance=args.allowance, a_units=args.a_units)
        return serve(bot, name=NAME, version=VERSION, requires_extensions=(SCHEMA, INFOSET),
                     extensions_accepted=(SCHEMA, INFOSET))
    finally:
        pool.close()


if __name__ == "__main__":
    sys.exit(main())
