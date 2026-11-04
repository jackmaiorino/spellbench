"""Spellbench v2 agent for the W1 search entrant: b512 plus root-parallel s4a search.

collab LANES/lead/W1-ENTRANT-DESIGN.md v7 (sections 2, 4, 5 and 7). The bot
extends kernel_flat_bot (the rated b512 policy bot, unchanged) with an
s4a-serve pool of K single-threaded worker processes:

* At an eligible decision the engine (kernel_engine_infoset_v2.py) attaches
  x_kernel_infoset_v1: the canonical information-set payload, or a refusal
  code. The pool searches the payload at budget b (tree k gets
  floor(b/K) + (1 if k < b mod K) native transitions, seeds
  RootSeeds(w1-entrant-v1, root id, k)) and picks with pick-v2; the pick is an
  index into the imported menu, which ``live_candidate_ids`` maps to a wire
  candidate.
* Spending (section 2): each game has an allowance of A units; a search is
  charged its transitions plus a_units. Before a search, avail = (game
  remainder) - a_units, or min(group remainder, game remainder) - a_units in
  a buffered group (cap 2 x (B + a_units)); the bot searches at
  b = min(B, avail) only if avail >= B/4. The meter never reads a clock, so
  reruns are identical on any host.
* Buffered groups (section 7): the walk decides native points on the local
  state (the imported root stepped by the bot's own picks), searched when
  eligible and allowed, else by policy; a wire candidate is compatible when
  some complete assignment starting with it induces the plan's rows. It
  answers when one candidate is compatible or the native points run out
  (then the lowest compatible index).
* Otherwise, and on every refusal or fault, the bot plays b512 sampled-wide-v1
  exactly as kernel_flat_bot does, with one draw per wire decision from the
  same per-seat stream.

Every decision writes a receipt to the decision log; game_over writes the
game's availability record: decisions by outcome and refusal or fault type.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spellbench.bot import Decision, GameOver, GameStart, serve  # noqa: E402
from spellbench.builtins.uniform import SplitMix64  # noqa: E402
import kernel_flat_bot as flat  # noqa: E402
from kernel_flat_bot import BotError, KernelFlatBot, ScorerProcess  # noqa: E402

INFOSET = "x_kernel_infoset_v1"
INFOSET_SCHEMA = "mtg-kernel-spellbench-infoset/v1"
ENTRANT_SCHEMA = "spellbench-kernel-search-entrant/v1"
SEED_MODEL = "w1-entrant-v1"
WALK_DOMAIN = b"spellbench-kernel-search-bot/walk-policy/v1"
# Policy outcomes that are C5 faults (design 5 and 6.7): refusals, a missing
# order map, failed searches, composition no-match, a lost group. R3 is not
# one: amendment 43.1 makes an R3 decision ineligible (counted separately).
FAULTS = ("R1", "R1b", "R2", "R4", "R5", "R6", "R7", "R8", "R8b",
          "order_map_missing", "incomplete", "pool_error", "no_match", "group_lost", "composition_cap",
          "no_completions", "missing_preview_keys", "tree_fault")
# Policy outcomes that are not C5 faults: an ineligible decision, the
# allowance, an opponent's library search (R3, amendment 43.1) and the
# continuation points of a group already counted at its root. Every other
# reason is a fault, unknown refusal codes included (fairness gate G2).
NOT_FAULTS = ("ineligible", "allowance", "R3")
COMPOSITION_UNAVAILABLE = ("composition_cap", "no_completions", "missing_preview_keys")


def is_fault(reason: str) -> bool:
    return reason in FAULTS or not (reason in NOT_FAULTS or reason.startswith("group_"))


class _OneDraw:
    """Stands in for the policy stream for one base-class answer: the draw
    this wire decision already took."""

    def __init__(self, value: int) -> None:
        self.value = value

    def next(self) -> int:
        return self.value


class PoolProcess:
    """`regret_census_v1 mode=s4a-serve`: K persistent worker processes."""

    def __init__(self, executable: str, source: str, workers: int) -> None:
        if os.path.basename(executable) == executable:
            executable = shutil.which(executable) or executable
        env = {**os.environ, "W1_SERVE_K": str(workers)}
        self._proc = subprocess.Popen([executable, f"source={source}", "mode=s4a-serve", "out=-"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)

    def request_line(self, line: bytes) -> dict[str, Any]:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        try:
            self._proc.stdin.write(line + b"\n")
            self._proc.stdin.flush()
        except OSError as exc:
            raise BotError(f"search pool input closed: {exc}") from exc
        answer = self._proc.stdout.readline()
        if not answer:
            raise BotError(f"search pool exited (code {self._proc.poll()})")
        value = json.loads(answer)
        if not isinstance(value, dict):
            raise BotError("search pool sent a non-object record")
        return value

    def close(self) -> None:
        if self._proc.stdin is not None and not self._proc.stdin.closed:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def load_entrant(path: Path) -> dict[str, Any]:
    entrant = json.loads(path.read_bytes())
    if entrant.get("schema") != ENTRANT_SCHEMA:
        raise BotError(f"{path}: not a {ENTRANT_SCHEMA} file")
    for key in ("workers", "budget", "allowance", "a_units", "group_cap"):
        if type(entrant.get(key)) is not int or entrant[key] <= 0:
            raise BotError(f"{path}: {key} must be a positive integer")
    if entrant["group_cap"] != 2 * (entrant["budget"] + entrant["a_units"]):
        raise BotError(f"{path}: group_cap must be 2 x (budget + a_units) (design 2, ruling 37.5)")
    if entrant.get("seed_model") != SEED_MODEL:
        raise BotError(f"{path}: seed_model must be {SEED_MODEL}")
    return entrant


def spend(budget: int, a_units: int, game_remaining: int, group_remaining: int | None) -> int | None:
    """Section 2's rule, a_units reserved first: the next search's budget, or None (policy)."""
    remaining = game_remaining if group_remaining is None else min(group_remaining, game_remaining)
    avail = remaining - a_units
    if avail < 0 or 4 * avail < budget:
        return None
    return min(budget, avail)


def search_line(root_id: str, budget: int, a_units: int, payload_json: str, path: list[int]) -> bytes:
    """The pool request, with the payload's bytes embedded verbatim."""
    head = json.dumps({"a_units": a_units, "budget": budget, "path": path}, separators=(",", ":"))
    return (head[:-1] + ',"payload":' + payload_json + ',"root_id":' + json.dumps(root_id) + "}").encode("utf-8")


def point_line(payload_json: str, path: list[int]) -> bytes:
    return ('{"op":"point","path":' + json.dumps(path, separators=(",", ":")) + ',"payload":' + payload_json
            + "}").encode("utf-8")


class KernelSearchBot(KernelFlatBot):
    def __init__(self, scorer: ScorerProcess, pool: PoolProcess, entrant: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(scorer, **kwargs)
        if self._selection != flat.SAMPLED:
            raise BotError("the search entrant's policy is sampled-wide-v1")
        self._pool = pool
        self._entrant = entrant
        self._k, self._b, self._a = entrant["workers"], entrant["budget"], entrant["a_units"]
        self._group_cap = entrant["group_cap"]
        self._game_remaining = entrant["allowance"]
        self._group: dict[str, Any] | None = None
        self._tally: Counter[str] = Counter()
        self._game_id: str | None = None
        self._walk_rng: SplitMix64 | None = None
        self._charged_wall_us = 0
        self._last_fault = ""
        # Whether the current eligible unit (an ordinary decision, or a
        # buffered group) already has a C5 fault: AC5's bound counts units.
        self._unit_faulted = False

    # -- game lifecycle --------------------------------------------------

    def on_game_start(self, request: GameStart) -> None:
        super().on_game_start(request)
        self._game_id = request.game_id
        self._game_remaining = self._entrant["allowance"]
        self._group = None
        self._tally = Counter()
        self._charged_wall_us = 0
        stream = flat.seat_stream_seed(self._seed, request.game_id, str(request.seat))
        digest = hashlib.sha256(WALK_DOMAIN + b"\0" + stream.to_bytes(8, "big")).digest()
        self._walk_rng = SplitMix64(int.from_bytes(digest[:8], "big"))
        self._write_log({"kind": "entrant", "entrant": self._entrant})

    def on_game_over(self, request: GameOver) -> None:
        # C5 faults (design 5, AC5): eligible decisions (a buffered group
        # counts once) with at least one refusal, missing order map, failed
        # search or tree, composition no-match or cap, or lost group. Events
        # by reason stay in the tally as fault:<reason>.
        faults = self._tally["c5_units"]
        self._write_log({
            "kind": "availability", "game_id": request.game_id, "tally": dict(sorted(self._tally.items())),
            "eligible": self._tally["eligible"],
            "searched_decisions": self._tally["searched"] + self._tally["searched_groups"],
            "c5_faults": faults, "r3_ineligible": self._tally["r3_ineligible"],
            "allowance_remaining": self._game_remaining,
            "allowance": self._entrant["allowance"], "charged_wall_us": self._charged_wall_us,
        })
        super().on_game_over(request)

    def close(self) -> None:
        super().close()
        self._pool.close()

    # -- answers ---------------------------------------------------------

    def choose(self, decision: Decision) -> int:
        started = time.perf_counter_ns()
        assert self._rng is not None
        seed = self._rng.next()
        try:
            flat_ext = decision.extensions.get(flat.EXTENSION)
            buffered = isinstance(flat_ext, dict) and flat_ext.get("schema") == flat.PROPOSAL_SCHEMA
            if buffered:
                return self._group_choose(decision, seed)
            self._group = None
            self._unit_faulted = False
            return self._ordinary_choose(decision, seed)
        finally:
            self._charged_wall_us += (time.perf_counter_ns() - started) // 1000

    def _fault(self, reason: str) -> None:
        self._tally[f"fault:{reason}"] += 1
        if not self._unit_faulted:
            self._unit_faulted = True
            self._tally["c5_units"] += 1

    def _policy(self, decision: Decision, seed: int, reason: str) -> int:
        """kernel_flat_bot's answer with this decision's draw; a fault reason is counted."""
        self._tally[f"policy:{reason}"] += 1
        if is_fault(reason):
            self._fault(reason)
        rng, self._rng = self._rng, _OneDraw(seed)
        try:
            answer = super().choose(decision)
        finally:
            self._rng = rng
        self._write_log({"kind": "policy", "step": decision.seat_step, "reason": reason})
        return answer

    def _extension(self, decision: Decision) -> tuple[dict[str, Any] | None, str | None]:
        """(extension, reason it cannot be searched)."""
        ext = decision.extensions.get(INFOSET)
        if ext is None:
            return None, "ineligible"
        if not isinstance(ext, dict) or ext.get("schema") != INFOSET_SCHEMA:
            raise self._fail("x_kernel_infoset_v1 has an unknown schema")
        if "refusal" in ext:
            # Every refusal is classified (amendment 43.1 part 2): by code and
            # the bridge's subclass, once per decision or group root.
            self._tally[f"refusal:{ext['refusal']}:{ext.get('refusal_detail', 'unclassified')}"] += 1
        if ext.get("refusal") == "R3" and ext.get("refusal_detail") == "opponent":
            # Amendment 43.1: an opponent's library search pending makes the
            # decision ineligible by definition; counted and reported. Any
            # other R3 (fairness gate G1) is eligible and a C5 fault.
            self._tally["r3_ineligible"] += 1
            return ext, "R3"
        self._tally["eligible"] += 1
        if "refusal" in ext:
            code = str(ext["refusal"])
            if code == "R3":
                return ext, f"R3:{ext.get('refusal_detail', 'unclassified')}"
            # A refusal is always a fault: a code that collides with a policy
            # reason that is not one is renamed so it cannot escape C5.
            return ext, code if is_fault(code) else f"refusal:{code}"
        if not isinstance(ext.get("payload_json"), str):
            raise self._fail("x_kernel_infoset_v1 lacks its payload")
        return ext, None

    def _ordinary_choose(self, decision: Decision, seed: int) -> int:
        ext, reason = self._extension(decision)
        if reason is not None:
            return self._policy(decision, seed, reason)
        assert ext is not None
        live = ext.get("live_candidate_ids")
        if live is None:
            return self._policy(decision, seed, "order_map_missing")
        if (not isinstance(live, list) or len(set(live)) != len(live) or len(live) != len(decision.candidates)
                or any(type(c) is not int or not 0 <= c < len(decision.candidates) for c in live)):
            raise self._fail("live_candidate_ids is not a bijection onto the candidates")
        budget = spend(self._b, self._a, self._game_remaining, None)
        if budget is None:
            return self._policy(decision, seed, "allowance")
        payload = json.loads(ext["payload_json"])
        pick = self._search(decision, ext["payload_json"], payload, [], budget, None)
        if pick is not None and not 0 <= pick < len(live):
            self._write_log({"kind": "fault", "step": decision.seat_step, "detail": "pick outside the order map"})
            self._last_fault, pick = "pool_error", None
        if pick is None:
            return self._policy(decision, seed, self._last_fault)
        self._tally["searched"] += 1
        answer = live[pick]
        self._write_log({"kind": "answer", "step": decision.seat_step, "candidate_id": answer, "live_index": pick})
        return answer

    def _root_id(self, payload: dict[str, Any], point: int) -> str:
        return f"{self._game_id}/{self._seat}/{payload['own_decision_index']}/{point}"

    def _search(self, decision: Decision, payload_json: str, payload: dict[str, Any], path: list[int],
                budget: int, group: dict[str, Any] | None) -> int | None:
        """One merged search; charges it; the pick-v2 index or None (fault in _last_fault)."""
        root_id = self._root_id(payload, len(path))
        started = time.perf_counter_ns()
        try:
            answer = self._pool.request_line(search_line(root_id, budget, self._a, payload_json, path))
        except (BotError, OSError, ValueError) as exc:
            # The pool is gone: the attempt is charged its whole budget
            # (section 2 charges failed attempts; its spend is unknown).
            answer = {"ok": False, "error": f"transport: {exc}", "charge": budget + self._a}
        wall_us = (time.perf_counter_ns() - started) // 1000
        if answer.get("ok") is not True:
            # A failed attempt costs at least a_units (fairness gate G4), even
            # when the pool failed before dispatching any tree.
            charge = max(int(answer.get("charge") or 0), self._a)
            self._charge(charge, group)
            self._last_fault = "pool_error"
            self._write_log({"kind": "search", "step": decision.seat_step, "root_id": root_id, "budget": budget,
                             "charge": charge, "error": answer.get("error"), "wall_us": wall_us,
                             "allowance_remaining": self._game_remaining,
                             "group_remaining": None if group is None else group["remaining"]})
            return None
        search = answer["search"]
        if search.get("root_id") != root_id or search.get("budget") != budget or search.get("a_units") != self._a:
            raise self._fail("search pool answered another request")
        if search.get("payload_sha256") != payload.get("sha256"):
            raise self._fail("search pool searched another payload")
        charge = int(search["charge"])
        self._charge(charge, group)
        self._tally["searches"] += 1
        trees = answer.get("trees", [])
        self._write_log({
            "kind": "search", "step": decision.seat_step, "root_id": root_id, "point": len(path),
            "payload_sha256": payload.get("sha256"), "host": answer.get("host"), "k": answer.get("k"),
            "budget": budget, "a_units": self._a, "units": search["units"], "charge": charge,
            "allowance_remaining": self._game_remaining,
            "group_remaining": None if group is None else group["remaining"],
            "tree_digests": search["tree_digests"], "tree_transitions": [t.get("transitions") for t in trees],
            "merged": search["merged"], "pick": search["pick"], "stage": search["stage"],
            "excluded": search["excluded"], "incomplete": search["incomplete"],
            "wall_us": wall_us, "pool_wall_seconds": answer.get("wall_seconds"),
            "tree_cpu_seconds": [t.get("cpu_seconds") for t in trees],
        })
        if search["excluded"] or any(t.get("faults") for t in trees):
            # Design 4 and 5: a tree with no root, a differing menu or a worker
            # failure is excluded and counted, even when the others still pick.
            self._fault("tree_fault")
        if search["incomplete"] or search["pick"] is None:
            self._last_fault = "incomplete"
            return None
        return int(search["pick"])

    def _charge(self, charge: int, group: dict[str, Any] | None) -> None:
        self._game_remaining -= charge
        self._tally["units_charged"] += charge
        if group is not None:
            group["remaining"] -= charge

    # -- buffered groups (design 7) ----------------------------------------

    def _group_choose(self, decision: Decision, seed: int) -> int:
        group_id = decision.group.get("group_id")
        index = decision.group.get("substep_index")
        count = decision.group.get("substep_count")
        continuing = self._group is not None and self._group.get("continues")
        if index == 0 and continuing and INFOSET not in decision.extensions:
            # One adapter buffer can span two wire groups (a selection, then
            # the order of the selected cards): the plan carries over.
            self._group.update(id=group_id, continues=False, offset=len(self._group["prefix"]))
        elif index == 0:
            self._unit_faulted = False
            self._group = self._open_group(decision, group_id)
        elif (self._group is None or self._group["id"] != group_id
              or len(self._group["prefix"]) - self._group.get("offset", 0) != index):
            self._group = {"id": group_id, "mode": "policy", "reason": "group_lost", "prefix": [None] * index}
            self._unit_faulted = False
            self._fault("group_lost")
        g = self._group
        if g["mode"] == "walk":
            g["walked"] = True
            answer = self._walk(decision, g)
        else:
            answer = None
        if answer is None:
            # A group's root is tallied by its reason; later substeps and a
            # walk's no-match fallback as group continuations.
            opened_policy = index == 0 and g["mode"] == "policy" and not g.get("walked")
            answer = self._policy(decision, seed, g["reason"] if opened_policy else f"group_{g['reason']}")
        else:
            self._tally["walk"] += 1
        g["prefix"].append(answer)
        if type(index) is int and type(count) is int and index + 1 == count:
            p = g["prefix"]
            if any(w[:len(p)] == p and len(w) > len(p) for w, _ in g.get("completions", [])):
                g["continues"] = True
            else:
                self._group = None
        return answer

    def _open_group(self, decision: Decision, group_id: Any) -> dict[str, Any]:
        g: dict[str, Any] = {"id": group_id, "prefix": [], "path": [], "plan": [], "mode": "policy",
                             "remaining": self._group_cap}
        ext, reason = self._extension(decision)
        if reason is None:
            assert ext is not None
            composition = ext.get("composition")
            if composition is None:
                why = ext.get("composition_unavailable", "composition_cap")
                reason = why if why in COMPOSITION_UNAVAILABLE else "composition_cap"
            else:
                # The walk runs whatever the allowance: each native point is
                # searched when eligible and allowed, else decided by policy.
                g.update(mode="walk", payload_json=ext["payload_json"], payload=json.loads(ext["payload_json"]),
                         keys=composition["keys"],
                         completions=[(c["wire"], [composition["keys"][k] for k in c["native"]])
                                      for c in composition["completions"]])
        g["reason"] = reason
        return g

    def _compatible(self, g: dict[str, Any]) -> list[tuple[list[int], list[str]]]:
        p, plan = g["prefix"], g["plan"]
        return [(w, n) for w, n in g["completions"]
                if w[:len(p)] == p and len(w) > len(p) and n[:len(plan)] == plan]

    def _walk(self, decision: Decision, g: dict[str, Any]) -> int | None:
        """Section 7's walk for this substep, or None after a no-match (policy)."""
        depth = len(g["prefix"])
        while True:
            compatible = self._compatible(g)
            choices = sorted({w[depth] for w, _ in compatible})
            if not choices:
                g.update(mode="policy", reason="no_match")
                self._fault("no_match")
                return None
            if len(choices) == 1 or all(len(n) == len(g["plan"]) for _, n in compatible):
                answer = choices[0]
                if not 0 <= answer < len(decision.candidates):
                    raise self._fail("composition names a candidate outside the decision")
                self._write_log({"kind": "answer", "step": decision.seat_step, "candidate_id": answer,
                                 "group_plan": len(g["plan"]), "compatible": choices})
                return answer
            outcome = self._decide_point(decision, g)
            if outcome == "failed":
                return None
            if outcome == "exhausted":
                answer = choices[0]
                self._write_log({"kind": "answer", "step": decision.seat_step, "candidate_id": answer,
                                 "group_plan": len(g["plan"]), "compatible": choices, "points_exhausted": True})
                return answer

    def _decide_point(self, decision: Decision, g: dict[str, Any]) -> str:
        """Decides the next native point on the local state: "decided", "exhausted"
        (no viewer point is left) or "failed" (the pool could not answer: the
        rest of the group is policy, a counted fault)."""
        try:
            answer = self._pool.request_line(point_line(g["payload_json"], g["path"]))
            point = answer["point"] if answer.get("ok") is True else None
        except (BotError, OSError, ValueError, KeyError) as exc:
            answer, point = {"error": f"transport: {exc}"}, None
        if point is None or (point.get("viewer_decision") and not isinstance(point.get("keys"), list)):
            self._write_log({"kind": "fault", "step": decision.seat_step, "detail": str(answer.get("error"))})
            g.update(mode="policy", reason="pool_error")
            self._fault("pool_error")
            return "failed"
        if not point.get("viewer_decision"):
            return "exhausted"
        keys = point["keys"]
        budget = spend(self._b, self._a, self._game_remaining, g["remaining"]) if point["eligible"] else None
        pick = None
        if budget is not None:
            pick = self._search(decision, g["payload_json"], g["payload"], g["path"], budget, g)
            if pick is not None and not 0 <= pick < len(keys):
                self._last_fault, pick = "pool_error", None
            if pick is None:
                self._fault(self._last_fault)
            else:
                self._tally["searched_points"] += 1
                if not g.get("searched"):
                    g["searched"] = True
                    self._tally["searched_groups"] += 1
        elif point["eligible"]:
            self._tally["allowance_points"] += 1
            if not g.get("allowance_limited"):
                # Counted once per group, in the same unit as `eligible`.
                g["allowance_limited"] = True
                self._tally["allowance_groups"] += 1
        if pick is None:
            pick = self._point_policy(decision, point["flat"], len(g["path"]))
            self._tally["policy_points"] += 1
        g["plan"].append(keys[pick])
        g["path"].append(pick)
        return "decided"

    def _point_policy(self, decision: Decision, point_flat: dict[str, Any], point: int) -> int:
        """b512 sampled-wide-v1 at a native point of the local state."""
        if (point_flat.get("feature_contract_digest"), point_flat.get("feature_encoding_digest"),
                point_flat.get("card_db_hash")) != (flat.FEATURE_CONTRACT_DIGEST, flat.FEATURE_ENCODING_DIGEST,
                                                   self._card_db):
            raise self._fail("group point tensor identity does not match the model")
        rows = point_flat["row_candidate_ids"]
        assert self._walk_rng is not None
        seed = self._walk_rng.next()
        request = {
            "schema": flat.REQUEST_SCHEMA, "request_id": f"{decision.game_id}:{decision.seat_step}:p{point}",
            "game_id": decision.game_id, "seat": decision.acting_seat, "step": decision.seat_step,
            "feature_contract_digest": flat.FEATURE_CONTRACT_DIGEST,
            "feature_encoding_digest": flat.FEATURE_ENCODING_DIGEST,
            "row_candidate_ids": rows, "sample_seed": seed, "tensor": point_flat["tensor"],
        }
        line, choice = self._scorer.score(request)
        if choice.get("schema") != flat.CHOICE_SCHEMA or choice.get("request_id") != request["request_id"]:
            raise self._fail(f"scorer answered {choice.get('schema')!r} code {choice.get('code')!r}")
        if choice.get("request_sha256") != hashlib.sha256(line).hexdigest():
            raise self._fail("scorer hashed a different request")
        row = choice.get("selected_row")
        if type(row) is not int or not 0 <= row < len(rows):
            raise self._fail("scorer choice does not match the point's rows")
        self._write_log({"kind": "point_policy", "step": decision.seat_step, "point": point, "row": row,
                         "sample_seed": seed, "request_sha256": choice["request_sha256"]})
        return rows[row]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scorer", required=True, help="spellbench_scorer_v1 executable")
    parser.add_argument("--scorer-arg", action="append", default=[], help="argument placed before --config")
    parser.add_argument("--config", required=True, help="scorer config JSON (also the search pool's source)")
    parser.add_argument("--pool", required=True, help="regret_census_v1 executable (mode s4a-serve)")
    parser.add_argument("--entrant", required=True, type=Path, help=f"{ENTRANT_SCHEMA} constants file")
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--decision-log", type=Path, default=None)
    parser.add_argument("--expect-model-state", metavar="SHA256", default=None)
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    pool = None
    try:
        entrant = load_entrant(args.entrant)
        scorer = ScorerProcess([args.scorer, *args.scorer_arg, "--config", args.config])
        pool = PoolProcess(args.pool, args.config, entrant["workers"])
        bot = KernelSearchBot(
            scorer, pool, entrant, seed=args.seed, decision_log=args.decision_log, name=args.name,
            version=args.version, expect_model_state=args.expect_model_state,
        )
    except (BotError, OSError, ValueError) as exc:
        print(f"kernel_search_bot: {exc}", file=sys.stderr)
        if pool is not None:
            pool.close()
        return 1
    try:
        return serve(bot, name=args.name, version=args.version,
                     requires_extensions=(flat.EXTENSION, INFOSET), extensions_accepted=(flat.EXTENSION, INFOSET))
    finally:
        bot.close()


if __name__ == "__main__":
    sys.exit(main())
