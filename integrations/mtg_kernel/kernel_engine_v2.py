"""Spellbench v2 environment over the pinned private native kernel bridge.

Private observations, native IDs and clone requests stay in this process.
Buffered declarations commit only after their complete neutral group.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import subprocess
import sys
import zlib
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
from spellbench import wire
from spellbench._schema import OBSERVATION_FLAGS, V2_KINDS
from spellbench.candidates import family
from spellbench.digests import deck_id
from spellbench.errors import MalformedJsonError, ValidationError
from spellbench.messages import HelloRequest, ResetRequest, StepRequest, ValidateDeckRequest, EnvHelloOk
from kernel_observation_v2 import KernelProjection, ProjectionError
from kernel_history_v2 import SCHEMA as HISTORY, PublicHistory
from kernel_semantics_v2 import ordinary_semantic
from kernel_combat_v2 import native_block_plan, BlockDeclaration, legacy_block_assignment, native_block_pick
from kernel_arrangement_v2 import native_arrangement, native_arrangement_binding, native_arrangement_pick
from kernel_order_v2 import TriggerOrder
from kernel_selection_order_v2 import native_selection_order

FLAT = "x_kernel_flat_v4"
PROPOSALS = "mtg-kernel-spellbench-completion-proposals/v1"
PROPOSAL_ENCODING = "integer-rle-table/v1"


def pack_proposal_tensor(tensor):
    """Losslessly shorten float-bit words and signed metadata integers."""
    result = {}
    for key, values in tensor.items():
        runs = []
        for value in values:
            if runs and runs[-1][0] == value:
                runs[-1][1] += 1
            else:
                runs.append([value, 1])
        packed = {"length": len(values), "rle": runs}
        result[key] = packed if len(wire.canonical_json_dumps(packed)) < len(wire.canonical_json_dumps(values)) else values
    return result


def intern_proposal_vectors(proposals):
    """Store exact repeated arrays once, without changing any score input."""
    vectors, indices, indexed = [], {}, []
    for trajectory in proposals:
        steps = []
        for step in trajectory:
            tensor = {}
            for key, words in step["tensor"].items():
                encoded = wire.canonical_json_dumps(words)
                if encoded not in indices:
                    indices[encoded] = len(vectors)
                    vectors.append(words)
                tensor[key] = {"vector": indices[encoded]}
            steps.append({"tensor": tensor, "selected_row": step["selected_row"]})
        indexed.append(steps)
    return {"vectors": vectors, "proposals": indexed}


def error(request_id, code, message):
    return {"protocol": "spellbench/v2", "response_type": "error", "request_id": request_id,
            "error": {"code": code, "message": message}}


class NativePeer:
    def __init__(self, executable):
        self.executable = executable
        self.child = subprocess.Popen([executable, "--x-kernel-flat-v4", "--private-v2-support"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.serial = 0

    def request(self, value):
        self.serial += 1
        message = {"protocol": "spellbench/v1", "request_id": f"native-{self.serial}", **value}
        self.child.stdin.write(json.dumps(message, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        self.child.stdin.flush()
        line = self.child.stdout.readline(wire.MAX_LINE_BYTES + 1)
        if not line or len(line) > wire.MAX_LINE_BYTES:
            raise ProjectionError("native bridge ended or exceeded its line bound")
        return json.loads(line)

    def close(self):
        if not self.child.stdin.closed:
            self.child.stdin.close()
        try:
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=10)

    def restart(self):
        self.close()
        self.child = subprocess.Popen([self.executable, "--x-kernel-flat-v4", "--private-v2-support"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)


class KernelEngine:
    known_cards = False

    def __init__(self, peer, catalog, *, source_revision=None, known_cards=False):
        # known_cards needs a bridge that exports public history: `known` then
        # follows the Section 6.7 update table instead of the current look.
        self.peer, self.catalog, self.known_cards = peer, catalog, known_cards
        native = peer.request({"request_type": "hello"})
        if native["response_type"] != "hello_ok":
            raise ProjectionError("native bridge did not handshake")
        identity = native["engine"]
        identity = {**identity, "version": "pauper-v2.0.0", "source_revision": source_revision,
                    "rules_snapshot_id": identity["rules_snapshot_id"] + ":neutral-v2"}
        self.provenance = {"engine_name": identity["name"], "engine_version": identity["version"],
            "rules_snapshot_id": identity["rules_snapshot_id"], "card_pool_identity": identity["card_pool_identity"]}
        self.hello = {"protocol": "spellbench/v2", "response_type": "hello_ok", "request_id": "hello", "protocol_minor": 0,
            "engine": identity, "formats": ["pauper-bo1"], "deck_sources": ["catalog"], "catalog": catalog["catalog"],
            "rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]},
            "observation": {flag: flag in ("passed_seats", "keywords", "full_name", "exiled_by", "permanent_details", "designations") or
                            flag == "known_cards" and known_cards for flag in OBSERVATION_FLAGS},
            "decision_kinds": sorted(V2_KINDS),
            "engine_defaults": {"trigger_order": None, "replacement_order": "engine_order",
                "combat_damage_assignment": "engine_order", "mana_payment": "engine_autopay"},
            "rewind": False, "fairness": {"noninterference_probe": False},
            "extensions": [{"name": FLAT, "native_ids": True}, {"name": HISTORY, "native_ids": False}]}
        EnvHelloOk.from_json(self.hello)
        self.cache = None
        self.used = set()
        self.game = None
        self.pending = None

    def handle(self, payload):
        try:
            request = wire.strict_json_loads(payload)
        except MalformedJsonError as exc:
            code = "malformed_request" if isinstance(exc, wire.NotAnObjectError) else "malformed_json"
            return wire.canonical_json_line(error("", code, "invalid JSON request"))
        request_id = request.get("request_id", "")
        if not isinstance(request_id, str):
            request_id = ""
        if request.get("protocol") != "spellbench/v2":
            return wire.canonical_json_line(error(request_id, "protocol_mismatch", "requires spellbench/v2"))
        kind = request.get("request_type")
        types = {"hello": HelloRequest, "reset": ResetRequest, "step": StepRequest, "validate_deck": ValidateDeckRequest}
        try:
            if kind in types:
                types[kind].from_json(request)
            elif not request_id or not isinstance(kind, str):
                raise ValidationError("missing request identity")
        except ValidationError:
            # Validation errors may quote payloads. Never reflect reset secrets.
            return wire.canonical_json_line(error(request_id, "malformed_request", "invalid request fields"))
        if self.cache and request_id == self.cache[0]:
            if payload == self.cache[1]:
                return self.cache[2]
            return wire.canonical_json_line(error(request_id, "request_id_reuse_mismatch", "request bytes changed"))
        if kind == "hello":
            result = {**deepcopy(self.hello), "request_id": request_id}
        elif kind == "reset":
            result = self.reset(request)
        elif kind == "step":
            result = self.step(request)
        elif kind == "validate_deck":
            if request["format"] != "pauper-bo1":
                result = error(request_id, "unsupported_format", "requires pauper-bo1")
            elif request["deck"].get("catalog_id") not in {d["catalog_id"] for d in self.catalog["catalog"]}:
                result = error(request_id, "unsupported_deck", "requires a supported catalog deck")
            else:
                result = {"protocol": "spellbench/v2", "response_type": "deck_ok", "request_id": request_id}
        else:
            result = error(request_id, "unsupported_request", "unsupported request type")
        answer = wire.canonical_json_line(result)
        self.cache = request_id, payload, answer
        return answer

    def reset(self, request):
        rid = request["request_id"]
        if request["game_id"] in self.used:
            return error(rid, "malformed_request", "game id was already used")
        if self.game and self.pending:
            return error(rid, "game_already_active", "current game is active")
        if request["format"] != "pauper-bo1":
            return error(rid, "unsupported_format", "requires pauper-bo1")
        decks = {d["catalog_id"]: d["decklist"] for d in self.catalog["catalog"]}
        for seat in request["seats"]:
            deck = seat["deck"]
            if deck.get("catalog_id") not in decks:
                return error(rid, "unsupported_deck", "requires a supported catalog deck")
            if deck["deck_id"] != deck_id(decks[deck["catalog_id"]]):
                return error(rid, "deck_id_mismatch", "deck id differs from the compiled catalog")
        rules = request["rules"]
        if (rules["mulligan"] != "none" or rules["starting_player"] != "host_assigned" or rules["probe"] or
            any(name not in (FLAT, HISTORY) for name in rules["extensions"])):
            return error(rid, "unsupported_rule", "unsupported rules or extensions")
        self.used.add(request["game_id"])
        if self.game and self.current["response_type"] == "decision":
            # A neutral cap ends the game before an internal buffered group
            # commits. Reset the private child before accepting a new game.
            self.peer.restart()
            restarted = self.peer.request({"request_type": "hello"})
            if restarted["response_type"] != "hello_ok":
                raise ProjectionError("restarted native bridge did not handshake")
        self.game = request["game_id"]
        self.rules = rules
        self.max_steps, self.max_groups = request["max_steps"], request["max_decisions"]
        self.answered, self.completed = 0, 0
        self.seat_steps, self.group_ids = {"p0": 0, "p1": 0}, {"p0": 0, "p1": 0}
        self.buffer = None
        secret = bytes.fromhex(request["game_secret"])
        first = rules["starting_seat"]
        self.projection = KernelProjection(self.catalog, secret, first_seat=first, keywords=True)
        self.native_group = None
        self.history = PublicHistory()
        seats = request["seats"] if first == "p0" else list(reversed(request["seats"]))
        self.current = self.peer.request({"request_type": "reset", "game_id": self.game, "format": "pauper-bo1",
            "seats": [{"seat": f"p{i}", "deck": {"catalog_id": entry["deck"]["catalog_id"]}} for i, entry in enumerate(seats)],
            "game_seed": int.from_bytes(hmac.new(secret, b"spellbench-kernel-v2/rng", hashlib.sha256).digest()[:8], "little"),
            "max_decisions": (1 << 53) - 1, "max_steps": (1 << 53) - 1})
        self.absorb_history()
        return self.respond(rid)

    def step(self, request):
        rid = request["request_id"]
        if self.game is None:
            return error(rid, "step_before_reset", "no game was reset")
        if request["game_id"] != self.game:
            return error(rid, "game_id_mismatch", "game id differs")
        if self.pending is None:
            return error(rid, "game_already_terminal", "game is terminal")
        if request["expected_step"] != self.answered:
            return error(rid, "expected_step_mismatch", "pending step differs")
        candidate = request["selection"]["candidate_id"]
        sd = self.pending["seat_decision"]
        if candidate >= len(sd["candidates"]):
            return error(rid, "candidate_id_out_of_range", "candidate id is out of range")
        if request["selection"]["semantic_echo"] != sd["candidates"][candidate]["semantic"]:
            return error(rid, "semantic_echo_mismatch", "candidate semantic differs")
        seat = sd["acting_seat"]
        self.answered += 1
        self.seat_steps[seat] += 1
        if sd["group"]["substep_index"] + 1 == sd["group"]["substep_count"]:
            self.completed += 1
            self.group_ids[seat] += 1
        try:
            if self.buffer:
                if self.buffer.choose(candidate):
                    self.commit_buffer()
                    self.buffer = None
            else:
                self.native_step(self.native_candidates[candidate])
        except (ValueError, KeyError, IndexError) as exc:
            print(f"kernel_engine_v2: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return self.terminal(rid, "halted", f"engine_contract_failure:{type(exc).__name__}")
        return self.respond(rid)

    def native_step(self, candidate):
        self.current = self.peer.request({"request_type": "step", "game_id": self.game,
            "expected_step": self.current["step"], "selection": {"candidate_id": candidate,
            "semantic_echo": self.current["candidates"][candidate]["semantic"]}})
        self.absorb_history()

    def absorb_history(self):
        """Queue the public events of every production native decision.

        Only production responses carry the slice; a terminal has none, and
        nothing after it reaches an agent's decision."""
        if self.current.get("response_type") != "decision":
            return
        history = self.current["extensions"]["x_kernel_v2_support"].get("history")
        if history is None:
            if self.known_cards or HISTORY in self.rules["extensions"]:
                raise ProjectionError("native bridge sent no public history")
            return
        self.history.absorb(history)

    def commit_buffer(self):
        if isinstance(self.buffer, TriggerOrder):
            self.native_step(self.buffer.result())
            return
        if isinstance(self.buffer, BlockDeclaration):
            binding = legacy_block_assignment(self.root, self.buffer.plan, self.buffer.assignment())
            belongs = lambda view: view["extensions"]["x_kernel_v2_support"].get("block_declaration_instance") == binding.instance
            pick = lambda view: native_block_pick(view, binding)
        else:
            binding = native_arrangement_binding(self.root, self.arrangement_cards)
            result = self.buffer.result()
            belongs = lambda view: view["extensions"]["x_kernel_v2_support"].get("effect_instance") == binding.instance
            pick = lambda view: native_arrangement_pick(view, result, binding)
        for _ in range(4096):
            if self.current["response_type"] != "decision" or not belongs(self.current):
                return
            self.native_step(pick(self.current))
        raise ProjectionError("native buffered commit exceeded its bound")

    def proposal_extension(self, actor, candidate_count):
        proposals = []
        for candidate in range(candidate_count):
            plan = deepcopy(self.buffer)
            finished = plan.choose(candidate)
            while not finished:
                finished = plan.choose(0)
            if isinstance(plan, TriggerOrder):
                selected = plan.result()
                flat = self.root["extensions"][FLAT]
                proposals.append([{"tensor": pack_proposal_tensor(flat["tensor"]),
                    "selected_row": flat["row_candidate_ids"].index(selected)}])
                continue
            if isinstance(plan, BlockDeclaration):
                binding = legacy_block_assignment(self.root, plan.plan, plan.assignment())
                pick = lambda view: native_block_pick(view, binding)
            else:
                binding = native_arrangement_binding(self.root, self.arrangement_cards)
                result = plan.result()
                pick = lambda view: native_arrangement_pick(view, result, binding)
            view = self.root
            prefix, steps = [], []
            for _ in range(4096):
                selected = pick(view)
                flat = view["extensions"][FLAT]
                steps.append({"tensor": pack_proposal_tensor(flat["tensor"]),
                    "selected_row": flat["row_candidate_ids"].index(selected)})
                prefix.append(selected)
                answer = self.peer.request({"request_type": "preview_steps", "game_id": self.game,
                    "expected_step": self.root["step"], "candidate_ids": prefix})
                if answer["response_type"] == "private_complete":
                    break
                if answer["response_type"] == "error":
                    raise ProjectionError("private completion preview refused within its declaration")
                if answer["response_type"] != "private_preview":
                    raise ProjectionError("private completion preview returned an unexpected response")
                view = answer["view"]
            else:
                raise ProjectionError("private completion preview exceeded its bound")
            proposals.append(steps)
        original = self.root["extensions"][FLAT]
        payload = wire.canonical_json_dumps(intern_proposal_vectors(proposals))
        if len(payload) > 64 * 1024 * 1024:
            raise ProjectionError("completion proposal exceeds the decoded payload bound")
        extension = {"schema": PROPOSALS, "mapping": "deterministic-completion-logprob/v1", "tensor_encoding": PROPOSAL_ENCODING,
            **{key: original[key] for key in ("card_db_hash", "feature_contract_digest", "feature_encoding_digest")},
            "acting_seat": actor, "step": self.seat_steps[actor],
            "row_candidate_ids": list(range(candidate_count))}
        # Large graveyard orders repeat many tensor slices. The fast compressor
        # can miss those repetitions and exceed the unchanged wire limit.
        for level in (1, 9):
            extension["proposals_zlib"] = base64.b64encode(zlib.compress(payload, level=level)).decode("ascii")
            if len(wire.canonical_json_dumps(extension)) <= wire.MAX_LINE_BYTES - 262144:
                break
        extension_bytes = len(wire.canonical_json_dumps(extension))
        if extension_bytes > wire.MAX_LINE_BYTES - 262144:
            raise ProjectionError(f"completion proposal exceeds the wire bound: "
                f"decoded={len(payload)} encoded_extension={extension_bytes} "
                f"limit={wire.MAX_LINE_BYTES - 262144} candidates={candidate_count} "
                f"steps={sum(map(len, proposals))}")
        return extension

    def terminal(self, rid, outcome, reason, winner=None):
        self.pending = None
        return {"protocol": "spellbench/v2", "response_type": "terminal", "request_id": rid, "game_id": self.game,
            "outcome": outcome, "classification": "natural" if outcome in ("p0_win", "p1_win", "draw") else outcome,
            "winner": winner, "reason": reason, "step_count": self.answered, "decision_count": self.completed,
            "provenance": self.provenance}

    def respond(self, rid):
        if self.current["response_type"] == "terminal":
            current = self.current
            winner = None if current["winner"] is None else self.projection.seat(current["winner"])
            outcome = current["outcome"] if winner is None else winner + "_win"
            return self.terminal(rid, outcome, current["reason"], winner)
        if self.answered >= self.max_steps or self.completed >= self.max_groups:
            return self.terminal(rid, "truncated", "max_steps" if self.answered >= self.max_steps else "max_decisions")
        try:
            return self.pose(rid)
        except (ValueError, KeyError, IndexError) as exc:
            print(f"kernel_engine_v2: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return self.terminal(rid, "halted", f"engine_contract_failure:{type(exc).__name__}")

    def pose(self, rid):
        raw = json.loads(self.current["extensions"]["x_kernel_v5"]["observation_json"])
        support = self.current["extensions"]["x_kernel_v2_support"]
        knowledge = (self.history.knowledge(("p0", "p1").index(raw["acting_player"]))
                     if self.known_cards else None)
        observation = self.projection.project(raw, support, knowledge)
        actor = observation["viewer"]
        if self.buffer is None:
            if support.get("at_block_root") is True:
                plan, refs = native_block_plan(raw, support, self.projection)
                self.buffer = BlockDeclaration(plan, refs)
                self.root = deepcopy(self.current)
            elif support.get("choice", {}).get("purpose") in ("scry", "look_select", "look", "reveal_partition"):
                self.buffer, self.arrangement_cards = native_arrangement(raw, support, self.projection)
                self.root = deepcopy(self.current)
            elif support.get("choice", {}).get("purpose") in ("mill", "put_on_top", "discard_order"):
                self.buffer, self.arrangement_cards = native_selection_order(raw, support, self.projection, self.current)
                self.root = deepcopy(self.current)
            elif self.current["candidates"][0]["semantic"]["kind"] == "order_triggers":
                self.buffer = TriggerOrder(self.current, self.projection)
                self.root = deepcopy(self.current)
        if self.buffer:
            semantics = self.buffer.semantics()
            if isinstance(self.buffer, BlockDeclaration):
                index, count = len(self.buffer.prefix), len(self.buffer.plan.blockers)
            else:
                index, count = self.buffer.substep_index, self.buffer.substep_count
            extensions = ({FLAT: self.proposal_extension(actor, len(semantics))}
                          if FLAT in self.rules["extensions"] else {})
        else:
            ids = self.current["extensions"][FLAT]["row_candidate_ids"]
            converted = [(i, ordinary_semantic(self.current["candidates"][i]["semantic"], raw, support, self.projection,
                          self.current["group"], candidate_id=i)) for i in ids]
            converted.sort(key=lambda pair: (pair[1]["kind"] != "pass", wire.canonical_json_dumps(pair[1])))
            self.native_candidates = [i for i, _ in converted]
            semantics = [semantic for _, semantic in converted]
            group = self.current["group"]
            index, count = group["substep_index"], group["substep_count"]
            if any(semantic["kind"] in ("finish_target_selection", "finish_selection") for semantic in semantics):
                index, count = 0, 1
            elif all(semantic["kind"] in ("choose_target", "choose_cost_target", "select_object") for semantic in semantics):
                shape = semantics[0]
                if shape["minimum"] == shape["maximum"]:
                    index, count = shape["selected_count"], shape["maximum"]
                else:
                    index, count = 0, 1
            extensions = {}
            if FLAT in self.rules["extensions"]:
                extension = deepcopy(self.current["extensions"][FLAT])
                extension["acting_seat"], extension["step"] = actor, self.seat_steps[actor]
                extension["row_candidate_ids"] = [self.native_candidates.index(i) for i in ids]
                extensions[FLAT] = extension
        if HISTORY in self.rules["extensions"]:
            extensions[HISTORY] = self.history.drain(("p0", "p1").index(raw["acting_player"]), self.projection)
        kinds = {family(semantic["kind"]) for semantic in semantics}
        if len(kinds) != 1:
            raise ProjectionError("native decision mixes neutral choice and priority families")
        source_values = [semantic.get("source") for semantic in semantics]
        purposes = {semantic.get("purpose") for semantic in semantics}
        sd = {"acting_seat": actor, "seat_step": self.seat_steps[actor],
            "group": {"group_id": self.group_ids[actor], "substep_index": index, "substep_count": count},
            "context": {"kind": kinds.pop(), "source": source_values[0] if all(value == source_values[0] for value in source_values) else None,
                "purpose": purposes.pop() if len(purposes) == 1 else None, "text": None, "rewind": False},
            "observation": observation,
            "candidates": [{"candidate_id": i, "semantic": value, "display_text": None} for i, value in enumerate(semantics)],
            "extensions": extensions}
        self.pending = {"protocol": "spellbench/v2", "response_type": "decision", "request_id": rid,
            "game_id": self.game, "step": self.answered, "seat_decision": sd, "provenance": self.provenance}
        return self.pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--known-cards", action="store_true",
                        help="declare known_cards and track Section 6.7 knowledge (needs a history-exporting bridge)")
    args = parser.parse_args()
    peer = NativePeer(args.bridge)
    try:
        engine = KernelEngine(peer, json.loads(args.catalog.read_bytes()), source_revision=args.source_revision,
                             known_cards=args.known_cards)
        while True:
            try:
                payload = wire.read_line(sys.stdin.buffer)
            except MalformedJsonError:
                answer = wire.canonical_json_line(error("", "malformed_json", "invalid request framing"))
            else:
                if payload is None:
                    return 0
                answer = engine.handle(payload)
            sys.stdout.buffer.write(answer)
            sys.stdout.buffer.flush()
    finally:
        peer.close()


if __name__ == "__main__":
    sys.exit(main())
