"""Human-play London environment over the London-human native bridge.

A human-only copy of kernel_engine_v2.py (the rated board's engine, which is
never edited): it declares London mulligans, starts the bridge with
--pauper-london-human-v1 --x-kernel-flat-v7, forwards FlatV7 model input under
x_kernel_flat_v7, and poses the pregame as protocol `mulligan` decisions and
`order_pick` `mulligan_bottom` groups. It reads no hidden fact the pinned
engine does not: the other seat's hand and what it bottomed never leave the
bridge process. Not an engine input of any rated board.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import subprocess
import sys
import threading
import time
import zlib
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))
# The pinned helper modules (history, combat, arrangement, order) are imported
# unchanged from the parent folder; this folder holds only the London copies.
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parent))
from spellbench import wire
from spellbench._schema import OBSERVATION_FLAGS, V2_KINDS
from spellbench.candidates import family
from spellbench.digests import deck_id
from spellbench.errors import MalformedJsonError, ValidationError
from spellbench.messages import HelloRequest, ResetRequest, StepRequest, ValidateDeckRequest, EnvHelloOk
from kernel_observation_v2 import ProjectionError
from kernel_observation_london_human_v1 import LondonHumanProjection
from kernel_history_v2 import SCHEMA as HISTORY, PublicHistory
from kernel_semantics_london_human_v1 import ordinary_semantic
from kernel_combat_v2 import native_block_plan, BlockDeclaration, legacy_block_assignment, native_block_pick
from kernel_arrangement_v2 import native_arrangement, native_arrangement_binding, native_arrangement_pick
from kernel_order_v2 import TriggerOrder
from kernel_selection_order_v2 import SelectionOrder, native_selection_order
from spellbench.human import graveyard_order
from spellbench.human.advisor import Advisor, AdvisorError
from spellbench.builtins.uniform import SplitMix64
import kernel_flat_bot_london_human_v1 as flat_bot

FLAT = "x_kernel_flat_v7"
# The bot's seat answering its grouped decisions natively (``--native-seat``): its block declaration, card
# arrangement, selection order and trigger order are the engine's own questions, each put to the bot's model (its own
# scorer, ``--native-scorer``) with the engine's model input and sampled once, as the trainer's session samples
# every native question. The bridge is also told the seat (reset field ``trainer_choice_seats``): it resolves for
# that seat the single-option choices training resolves itself, as the trainer's session does, where the bridge's
# neutral choices would pose them (the other seat keeps them). Without the option the seat gets the protocol's
# grouped decision with completion proposals (deterministic-completion-logprob/v1), as on the rated board, and the
# bridge's neutral choices.
NATIVE_KINDS = ("block", "arrangement", "selection_order", "trigger_order")
NATIVE_LOG_SCHEMA = "spellbench-london-human-native-questions/v1"
# The bot process (kernel_flat_bot_london_human_v1) draws its own seeds from a stream of the game id and seat; the
# native questions draw theirs from a second stream of the same seed, so neither shifts the other.
NATIVE_STREAM_SUFFIX = "/native-questions"
NATIVE_GROUP_BOUND = 4096
# The training priority-window rules the bridge's reset field ``priority_windows`` takes for a bot seat
# (mtg-kernel priority_action_windows_v1); harness-v2 is the surface every earlier bot trained on.
ACTION_WINDOWS_RULES = ("action-windows-v1", "action-windows-end-step-v1")
ACTION_WINDOWS_RULE = "action-windows-v1"
BRIDGE_FLAGS = ["--x-kernel-flat-v7", "--pauper-london-human-v1", "--private-v2-support"]
ENGINE_VERSION = "pauper-london-human-v1"
SNAPSHOT_SUFFIX = ":neutral-v2:london-human-v1"
PROPOSALS = "mtg-kernel-spellbench-completion-proposals/v1"
PROPOSAL_ENCODING = "integer-rle-table/v1"
PREVIEW_CACHE_BYTES = 16 * 1024 * 1024  # response lines; parsed views take several times that
# The advisor's planned line (human play with an advisor only; ``KernelEngine.planned_line``).
LINE = "x_advisor_line_v1"
LINE_SCHEMA = "spellbench-advisor-line/v1"
LINE_STEPS = 8         # the person's choices in one line at most: the line's only bound (a block declaration counts
                       # once its whole declaration is played, and is never cut short)
LINE_NATIVE_IDS = 64   # the bridge's own bound of a line's native choices (``private_line``)
# The line scorer's time for all the reads of one line (seconds), the whole exchange (writing the request included)
# supervised from outside it. A scorer that runs past it is dropped for the session (closed off the decision's path)
# and the lines end "unavailable". The scorer reads only the person's own model input, which is the same whatever the
# opponent holds, so this deadline depends on no hidden card. The bridge is the game's own process and has no such
# deadline: a bridge that hangs hangs the game with or without the line.
LINE_SCORER_TIMEOUT_S = 2.0
# Why a line ends. From the bridge: the opponent decides something other than a bare priority pass; the next step
# would show a hidden card (a draw, a mill, a search, a look or reveal, the opponent's hand changing) or draw a random
# outcome, one reason "unseen" for both (which one a resolution produces can depend on the hidden cards); the turn
# ends; the game ends (with the result for the person: this turn, or a later one); the game ends without a result. From the planner: the next choice is a grouped one (a card order, a trigger
# order), which the line does not play; the bound of choices; the scorer cannot read the next choice or is gone. A
# block declaration is played: each of the engine's own blocker questions (attacker by attacker, "block it with this
# creature?") gets the model's top answer given its answers before, and the line shows the whole declaration that
# adds up to, blocker by blocker.
# No wall-clock bound: how long the clone takes depends on whether the opponent's windows were posed, which depends on
# their hidden hand, so time never decides what the line shows.
LINE_STOPS = ("opponent_decision", "unseen", "turn_ends", "game_end", "game_end_later_turn", "no_result",
              "grouped", "bound", "unreadable", "unavailable")
ARRANGEMENTS = ("scry", "look_select", "look", "reveal_partition", "mill", "put_on_top", "discard_order")


def _plain_ints(values):
    """True for a list of canonical JSON integers (no bools), whose canonical text is plain ``str(value)``."""
    return type(values) is list and all(type(value) is int and -wire.MAX_JSON_INT <= value <= wire.MAX_JSON_INT
                                        for value in values)


def _ints_length(values):
    """The length of the canonical JSON of a list of plain integers, without encoding it."""
    return 2 + sum(map(len, map(str, values))) + max(0, len(values) - 1)


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
        if _plain_ints(values):
            # The canonical lengths, counted: '{"length":N,"rle":[[v,c],...]}' against '[v,...]'.
            rle = 2 + sum(3 + len(str(value)) + len(str(count)) for value, count in runs) + max(0, len(runs) - 1)
            shorter = 17 + len(str(len(values))) + rle + 1 < _ints_length(values)
        else:
            shorter = len(wire.canonical_json_dumps(packed)) < len(wire.canonical_json_dumps(values))
        result[key] = packed if shorter else values
    return result


def _vector_key(words):
    """A key equal for two vectors exactly when their canonical JSON is equal."""
    if _plain_ints(words):
        return tuple(words)
    if (type(words) is dict and words.keys() == {"length", "rle"} and type(words["length"]) is int
            and type(words["rle"]) is list and all(type(run) is list and len(run) == 2 for run in words["rle"])
            and _plain_ints([words["length"], *(part for run in words["rle"] for part in run)])):
        return (words["length"], tuple(map(tuple, words["rle"])))
    return wire.canonical_json_dumps(words)


def intern_proposal_vectors(proposals, grouped=False):
    """Store exact repeated arrays once, without changing any score input.

    grouped lists the table by tensor key and then trajectory step instead of
    first use. Consecutive steps of a long order differ in a few rows, and
    grouping puts those near-copies next to each other where zlib's 32 KiB
    window can match them. The scorer resolves indices either way."""
    vectors, keys, indices, indexed = [], [], {}, []
    for trajectory in proposals:
        steps = []
        for position, step in enumerate(trajectory):
            tensor = {}
            for key, words in step["tensor"].items():
                encoded = _vector_key(words)
                if encoded not in indices:
                    indices[encoded] = len(vectors)
                    vectors.append(words)
                    keys.append((key, position))
                tensor[key] = {"vector": indices[encoded]}
            steps.append({"tensor": tensor, "selected_row": step["selected_row"]})
        indexed.append(steps)
    if grouped:
        order = sorted(range(len(vectors)), key=keys.__getitem__)
        rank = [0] * len(order)
        for new, old in enumerate(order):
            rank[old] = new
        vectors = [vectors[old] for old in order]
        for steps in indexed:
            for step in steps:
                for ref in step["tensor"].values():
                    ref["vector"] = rank[ref["vector"]]
    return {"vectors": vectors, "proposals": indexed}


class PreviewCache:
    """Private previews of one buffered declaration, keyed by native prefix.

    A preview is a pure function of the declaration's root and its native
    prefix, so a stored answer equals a fresh one. Every candidate's completion
    replays the declaration's shared prefix, which stays recently used; other
    entries leave oldest first once the stored response bytes pass the bound."""

    def __init__(self, bound=PREVIEW_CACHE_BYTES):
        self.entries, self.bytes, self.bound = OrderedDict(), 0, bound

    def get(self, key):
        stored = self.entries.get(key)
        if stored is None:
            return None
        self.entries.move_to_end(key)
        return stored[0]

    def put(self, key, entry, size):
        """Store [view or None when complete, packed tensor or None] and return it."""
        self.entries[key] = entry, size
        self.bytes += size
        while self.bytes > self.bound and len(self.entries) > 1:
            _, (_, dropped) = self.entries.popitem(last=False)
            self.bytes -= dropped
        return entry


def error(request_id, code, message):
    return {"protocol": "spellbench/v2", "response_type": "error", "request_id": request_id,
            "error": {"code": code, "message": message}}


def native_priority_windows(bot_seat, first_seat, rule):
    """The bridge's ``priority_windows`` for the bot's seat of the reset request: ``rule`` on the bot's bridge seat
    (its p0 is the starting seat), ``harness-v2`` on the other."""
    windows = ["harness-v2", "harness-v2"]
    windows[0 if bot_seat == first_seat else 1] = rule
    return windows


def native_seat_of(seat, first_seat):
    """The bridge seat of a reset-request seat: the bridge's p0 is the starting seat."""
    return ("p0", "p1")[(("p0", "p1").index(seat) + ("p0", "p1").index(first_seat)) % 2]


def acting_player(view):
    """The native acting player (p0 or p1 of the bridge) of a native decision."""
    return json.loads(view["extensions"]["x_kernel_v5"]["observation_json"])["acting_player"]


def check_native_scorer(scorer, expect_model_state=None):
    """Refuse a scorer the bot process itself would refuse (``KernelFlatBot``'s ready checks)."""
    ready = scorer.ready
    if (ready.get("feature_contract_digest"), ready.get("feature_encoding_digest")) != (
            flat_bot.FEATURE_CONTRACT_DIGEST, flat_bot.FEATURE_ENCODING_DIGEST):
        raise ValueError("the bot's scorer serves a different feature contract")
    if ready.get("sampler_identity") != flat_bot.SAMPLER_IDENTITY:
        raise ValueError(f"the bot's scorer sampler {ready.get('sampler_identity')!r} is not {flat_bot.SAMPLER_IDENTITY}")
    if ready.get("float_encoding") != flat_bot.FLOAT_ENCODING:
        raise ValueError(f"the bot's scorer float encoding {ready.get('float_encoding')!r} is not "
                         f"{flat_bot.FLOAT_ENCODING}")
    if ready.get("selection") not in (flat_bot.SAMPLED, flat_bot.ARGMAX):
        raise ValueError(f"unknown scorer selection {ready.get('selection')!r}")
    if expect_model_state is not None and ready.get("model_state_sha256") != expect_model_state:
        raise ValueError(f"the bot's scorer loaded model state {ready.get('model_state_sha256')}, expected "
                         f"{expect_model_state}")


def native_window_seats(person_seat, first_seat):
    """The bridge's seat list for the person's seat of the reset request. The bridge's p0 is the starting seat
    (``reset`` hands it the seats in turn order), so the person is its p0 exactly when they play first."""
    return ["p0" if person_seat == first_seat else "p1"]


def settle_graveyard_order(plan):
    """Finish the ordering step of cards going to a graveyard together that nobody is asked in a game without a
    reader: the step the protocol adds after a multi-card discard (the engine's own batch orderings, a mill above
    all, are already gone under the training rule). Each position takes the first card listed, which is the
    completion the bot's own proposals for the discard were scored with. True when ``plan`` was such an ordering
    (cards bound for a graveyard, nothing left to select) and is now complete; False, untouched, otherwise."""
    if not isinstance(plan, SelectionOrder) or plan.destination != "graveyard" or plan.selecting:
        return False
    while not plan.choose(0):
        pass
    return True


def graveyard_readers(decks, seats):
    """The cards of the two seats' deck lists that read graveyard order (``spellbench.human.graveyard_order``)."""
    names = {catalog: [row["name"] for row in rows] for catalog, rows in decks.items()}
    return graveyard_order.game_readers(names, [entry["deck"]["catalog_id"] for entry in seats])


def alias_flat(response):
    """The pinned helper modules (combat, arrangement, order, selection order) read the model input's row map
    under its V4 key. The bridge sends it as x_kernel_flat_v7; this process keeps an internal alias of the same
    object so those helpers run unchanged. The alias never leaves this process: every outbound extension is built
    from FLAT (x_kernel_flat_v7)."""
    for holder in (response, response.get("view") if isinstance(response, dict) else None):
        extensions = holder.get("extensions") if isinstance(holder, dict) else None
        if isinstance(extensions, dict) and FLAT in extensions:
            extensions["x_kernel_flat_v4"] = extensions[FLAT]
    return response


class NativePeer:
    def __init__(self, executable):
        self.executable = executable
        self.child = subprocess.Popen([executable, *BRIDGE_FLAGS],
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
        self.last_line_bytes = len(line)
        return alias_flat(json.loads(line))

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
        self.child = subprocess.Popen([self.executable, *BRIDGE_FLAGS],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)


class KernelEngine:
    known_cards = False

    def __init__(self, peer, catalog, *, source_revision=None, known_cards=False, engine_windows_seat=None,
                 auto_graveyard_order=False, line_seat=None, line_scorer=None, line_timing=None,
                 action_windows_seat=None, action_windows_rule=ACTION_WINDOWS_RULE, native_seat=None,
                 native_scorer=None, native_seed=0, native_log=None, native_trace=None):
        # known_cards needs a bridge that exports public history: `known` then
        # follows the Section 6.7 update table instead of the current look.
        self.peer, self.catalog, self.known_cards = peer, catalog, known_cards
        # The seat of a person (p0 or p1 of the reset request), or None. The
        # bridge gives that seat every engine priority window; the other seat
        # keeps the windows its model trained on.
        self.engine_windows_seat = engine_windows_seat
        # The bot's seat (p0 or p1 of the reset request) and the training window rule it plays on, or None. The
        # bridge offers that seat the priority windows its model trained with (action-windows-v1); without it the
        # seat keeps the HarnessV2 windows.
        if action_windows_seat is not None and action_windows_seat == engine_windows_seat:
            raise ValueError("a seat has either engine windows or a training window rule")
        self.action_windows_seat, self.action_windows_rule = action_windows_seat, action_windows_rule
        # True: in a game in which no card of either deck list reads graveyard order, the bridge applies the
        # training rule for it (nobody is asked); in a game with such a card both seats are asked, as the rules say.
        self.auto_graveyard_order = auto_graveyard_order
        # This game's graveyard order: None (not asked for), "settled", or "asked" with the reader cards.
        self.graveyard_order = None
        # The advisor's planned line (``planned_line``): the person's seat and a scorer of the wrapper's own (an
        # ``Advisor``, loaded with the advisor's checkpoint), or None. Only a game whose rules enable LINE gets it.
        self.line_seat, self.line_scorer = line_seat, line_scorer
        # A JSON-lines file each line's cost is written to (measurement only), or None.
        self.line_timing = line_timing
        # The bot's seat (p0 or p1 of the reset request) whose grouped decisions are played natively, the bot's own
        # scorer (``flat_bot.ScorerProcess``, ready-checked by ``check_native_scorer``), the bot's seed and a
        # JSON-lines log of every native question asked, or None.
        if native_seat is not None and (native_scorer is None or native_seat in (engine_windows_seat, line_seat)):
            raise ValueError("the native seat is the bot's: it needs the bot's scorer and is not the person's seat")
        self.native_seat, self.native_scorer, self.native_seed = native_seat, native_scorer, native_seed
        self.native_log = native_log
        # A folder that gets one replay trace per game (proof only, ``trace_native``), or None.
        self.native_trace, self.trace_path = native_trace, None
        native = peer.request({"request_type": "hello"})
        if native["response_type"] != "hello_ok":
            raise ProjectionError("native bridge did not handshake")
        identity = native["engine"]
        identity = {**identity, "version": ENGINE_VERSION, "source_revision": source_revision,
                    "rules_snapshot_id": identity["rules_snapshot_id"] + SNAPSHOT_SUFFIX}
        self.provenance = {"engine_name": identity["name"], "engine_version": identity["version"],
            "rules_snapshot_id": identity["rules_snapshot_id"], "card_pool_identity": identity["card_pool_identity"]}
        self.hello = {"protocol": "spellbench/v2", "response_type": "hello_ok", "request_id": "hello", "protocol_minor": 0,
            "engine": identity, "formats": ["pauper-bo1"], "deck_sources": ["catalog"], "catalog": catalog["catalog"],
            "rules_supported": {"mulligan": ["london"], "starting_player": ["host_assigned"]},
            "observation": {flag: flag in ("passed_seats", "keywords", "full_name", "exiled_by", "permanent_details", "designations") or
                            flag == "known_cards" and known_cards for flag in OBSERVATION_FLAGS},
            "decision_kinds": sorted(V2_KINDS),
            "engine_defaults": {"trigger_order": None, "replacement_order": "engine_order",
                "combat_damage_assignment": "engine_order", "mana_payment": "engine_autopay"},
            "rewind": False, "fairness": {"noninterference_probe": False},
            "extensions": [{"name": FLAT, "native_ids": True}, {"name": HISTORY, "native_ids": False}]
                          + ([{"name": LINE, "native_ids": False}] if line_seat is not None else [])}
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
        if (rules["mulligan"] != "london" or rules["starting_player"] != "host_assigned" or rules["probe"] or
            any(name not in (FLAT, HISTORY, LINE) for name in rules["extensions"])):
            return error(rid, "unsupported_rule", "unsupported rules or extensions")
        if LINE in rules["extensions"] and (self.line_seat is None or FLAT not in rules["extensions"]):
            return error(rid, "unsupported_rule", "the planned line needs --line-seat and the model input")
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
        self.buffer = self.previews = None
        self.graveyard_order = None
        if self.native_seat is not None:
            stream = flat_bot.seat_stream_seed(self.native_seed, self.game + NATIVE_STREAM_SUFFIX, self.native_seat)
            self.native_rng, self.native_asked = SplitMix64(stream), 0
            self.write_native({"kind": "header", "schema": NATIVE_LOG_SCHEMA, "game": self.game,
                               "seat": self.native_seat, "stream_seed": stream,
                               "model_state_sha256": self.native_scorer.ready.get("model_state_sha256"),
                               "selection": self.native_scorer.ready.get("selection")})
        secret = bytes.fromhex(request["game_secret"])
        first = rules["starting_seat"]
        self.projection = LondonHumanProjection(self.catalog, secret, first_seat=first, keywords=True)
        self.native_group = None
        self.history = PublicHistory()
        seats = request["seats"] if first == "p0" else list(reversed(request["seats"]))
        native = {"request_type": "reset", "game_id": self.game, "format": "pauper-bo1",
            "seats": [{"seat": f"p{i}", "deck": {"catalog_id": entry["deck"]["catalog_id"]}} for i, entry in enumerate(seats)],
            "game_seed": int.from_bytes(hmac.new(secret, b"spellbench-kernel-v2/rng", hashlib.sha256).digest()[:8], "little"),
            "max_decisions": (1 << 53) - 1, "max_steps": (1 << 53) - 1}
        if self.engine_windows_seat is not None:
            # Sent only when asked for: a bridge without the feature refuses the field, so a session never plays
            # without the windows it promised.
            native["engine_window_seats"] = native_window_seats(self.engine_windows_seat, first)
        if self.action_windows_seat is not None:
            # Likewise only when asked for: a bridge without the field refuses it.
            native["priority_windows"] = native_priority_windows(self.action_windows_seat, first,
                                                                 self.action_windows_rule)
        if self.native_seat is not None:
            # Likewise only when asked for: a bridge without the field refuses it.
            native["trainer_choice_seats"] = [native_seat_of(self.native_seat, first)]
        readers = graveyard_readers(decks, request["seats"]) if self.auto_graveyard_order else []
        if self.auto_graveyard_order and not readers:
            # Likewise only when asked for, and only where no card reads graveyard order.
            native["auto_graveyard_order"] = True
        self.current = self.peer.request(native)
        if self.native_trace is not None and self.current.get("response_type") != "error":
            self.trace_path = Path(self.native_trace) / f"{self.game}.jsonl"
            try:
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                self.trace_path.write_text("", encoding="utf-8")
            except OSError as exc:
                self.output_failed("trace", exc)
            self.trace_native({"t": "reset", "game_id": native["game_id"], "game_seed": native["game_seed"],
                               "decks": [seat["deck"]["catalog_id"] for seat in native["seats"]],
                               "engine_window_seats": native.get("engine_window_seats"),
                               "priority_windows": native.get("priority_windows"),
                               "auto_graveyard_order": native.get("auto_graveyard_order", False),
                               "trainer_choice_seats": native.get("trainer_choice_seats"),
                               "native_seat": (None if self.native_seat is None else
                                               native_seat_of(self.native_seat, first))})
        if self.current.get("response_type") == "error":
            self.game = self.pending = None
            print(f"kernel_engine_london_human_v1: the bridge refused the reset: {self.current.get('error')}",
                  file=sys.stderr, flush=True)
            if self.native_seat is not None:
                return error(rid, "unsupported_rule", "the native bridge refused this reset (the bot answering as "
                             "trained needs a bridge built with trainer_choice_seats)")
            if self.action_windows_seat is not None:
                return error(rid, "unsupported_rule", "the native bridge refused this reset (engine windows, bot "
                             "windows and the graveyard rule need a bridge built with them)")
            return error(rid, "unsupported_rule", "the native bridge refused this reset (engine windows and the "
                         "graveyard rule need a bridge built with them)")
        if self.auto_graveyard_order:
            support = (self.current.get("extensions") or {}).get("x_kernel_v2_support") or {}
            if readers:
                self.graveyard_order = {"how": "asked", "readers": readers}
            elif support.get("graveyard_order") == "settled" or self.current.get("response_type") != "decision":
                self.graveyard_order = {"how": "settled", "readers": []}
            else:
                # The engine found a reader the card data does not list (its own check, Delve). The session decided
                # from the same data that nobody is asked, so the game is not played: the data needs the card.
                self.game = self.pending = None
                print("kernel_engine_london_human_v1: the bridge refused the graveyard rule for a game the card data "
                      "calls order-free; graveyard_order_cards_v1.json lacks a reader card of this game",
                      file=sys.stderr, flush=True)
                return error(rid, "unsupported_rule", "a card of this game reads graveyard order but the card data "
                             "does not list it (graveyard_order_cards_v1.json); the game is not played")
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
                    self.buffer = self.previews = None
            else:
                self.native_step(self.native_candidates[candidate])
        except (ValueError, KeyError, IndexError) as exc:
            print(f"kernel_engine_v2: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return self.terminal(rid, "halted", f"engine_contract_failure:{type(exc).__name__}")
        return self.respond(rid)

    def native_step(self, candidate):
        if self.trace_path is not None:
            flat = self.current["extensions"].get(FLAT) or {}
            self.trace_native({"t": "step", "step": self.current["step"], "seat": acting_player(self.current),
                               "rows": flat.get("row_candidate_ids"), "candidate": candidate})
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

    def play_native_group(self):
        """The bot's grouped decision played as the trainer's session plays it: each of the engine's questions in
        it (a block declaration's attacker-by-attacker inclusions, an arrangement's or selection order's card by card
        picks, a trigger order) is put to the bot's model with the engine's own model input and answered with the row
        it samples, until play leaves the group. The group is the one the buffer at ``self.root`` was made for."""
        buffer, root = self.buffer, self.root
        root_support = root["extensions"]["x_kernel_v2_support"]
        if isinstance(buffer, BlockDeclaration):
            kind, key = "block", ("block_declaration_instance", root_support.get("block_declaration_instance"))
        elif isinstance(buffer, TriggerOrder):
            kind, key = "trigger_order", None  # one native question: the whole order
        else:
            kind = "selection_order" if isinstance(buffer, SelectionOrder) else "arrangement"
            key = ("effect_instance", native_arrangement_binding(root, self.arrangement_cards).instance)
        seat = acting_player(root)
        for _ in range(NATIVE_GROUP_BOUND):
            self.native_step(self.native_pick(kind))
            view = self.current
            if (key is None or view["response_type"] != "decision" or acting_player(view) != seat
                    or view["extensions"]["x_kernel_v2_support"].get(key[0]) != key[1]):
                return
        raise ProjectionError("the bot's native group exceeded its bound")

    def native_pick(self, kind):
        """The bot's answer to the engine's current question: the row its model samples from the engine's own model
        input (the bot process's request, with a seed of the native-question stream), as a native candidate id."""
        view = self.current
        flat = view["extensions"].get(FLAT)
        if not isinstance(flat, dict) or flat.get("schema") != flat_bot.EXTENSION_SCHEMA:
            raise ProjectionError("the bot's native question came without its model input")
        if flat.get("numeric_choice_v4_fill"):
            raise ProjectionError("the bot's native question is a numeric choice its model input cannot encode")
        rows = flat["row_candidate_ids"]
        candidates = len(view["candidates"])
        if self.trace_path is not None:
            self.trace_native({"t": "question", "group": kind, "step": view["step"], "seat": acting_player(view),
                               "rows": rows, "tensor": flat.get("tensor")})
        if (not rows or len(set(rows)) != len(rows) or sorted(rows) != list(range(candidates))
                or (flat["feature_contract_digest"], flat["feature_encoding_digest"])
                != (flat_bot.FEATURE_CONTRACT_DIGEST, flat_bot.FEATURE_ENCODING_DIGEST)):
            raise ProjectionError("the bot's native model input does not match the question")
        ready = self.native_scorer.ready
        self.native_asked += 1
        seed = self.native_rng.next() if ready["selection"] == flat_bot.SAMPLED else None
        request = {"schema": flat_bot.REQUEST_SCHEMA, "request_id": f"{self.game}:native:{self.native_asked}",
                   "game_id": self.game, "seat": self.native_seat, "step": self.native_asked,
                   "feature_contract_digest": flat_bot.FEATURE_CONTRACT_DIGEST,
                   "feature_encoding_digest": flat_bot.FEATURE_ENCODING_DIGEST,
                   "row_candidate_ids": rows, "sample_seed": seed, "tensor": flat["tensor"]}
        line, choice = self.native_scorer.score(request)
        if choice.get("schema") != flat_bot.CHOICE_SCHEMA or choice.get("request_id") != request["request_id"]:
            raise ProjectionError(f"the bot's scorer answered {choice.get('schema')!r} code {choice.get('code')!r}")
        if choice.get("request_sha256") != hashlib.sha256(line).hexdigest():
            raise ProjectionError("the bot's scorer hashed a different request")
        row = choice.get("selected_row")
        if type(row) is not int or not 0 <= row < len(rows) or choice.get("selected_candidate_id") != rows[row]:
            raise ProjectionError("the bot's scorer choice does not match the row map")
        self.write_native({"kind": "question", "game": self.game, "group": kind, "native_step": view["step"],
                           "asked": self.native_asked, "rows": len(rows), "candidate_id": rows[row],
                           "selected_row": row, "sample_seed": seed, "logits_bits": choice.get("logits_bits"),
                           "request_sha256": choice["request_sha256"]})
        return rows[row]

    def trace_native(self, record):
        """One line of this game's replay trace (``--native-trace``): the bridge reset, then every native step the
        wrapper sends (the acting player, the bridge's row map and the native candidate), and before each of the bot's
        native questions its model input as the bridge gave it. mtg-kernel replays it on the trainer's own session."""
        if self.trace_path is None:
            return
        try:
            with open(self.trace_path, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            self.output_failed("trace", exc)

    def write_native(self, record):
        if self.native_log is None:
            return
        try:
            with open(self.native_log, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            self.output_failed("log", exc)

    def output_failed(self, which, exc):
        """A record file that cannot be written is dropped for the rest of the session, with a log line; play goes
        on (a trace cut short fails its replay, which requires the trace to reach the game's end)."""
        print(f"kernel_engine_london_human_v1: the native-question {which} is not written from here on: {exc}",
              file=sys.stderr, flush=True)
        if which == "trace":
            self.native_trace = self.trace_path = None
        else:
            self.native_log = None

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
            entry = self.previews.get(()) or self.previews.put((), [self.root, None], 0)
            prefix, steps = [], []
            for _ in range(4096):
                view = entry[0]
                selected = pick(view)
                flat = view["extensions"][FLAT]
                if entry[1] is None:
                    entry[1] = pack_proposal_tensor(flat["tensor"])
                steps.append({"tensor": entry[1], "selected_row": flat["row_candidate_ids"].index(selected)})
                prefix.append(selected)
                key = tuple(prefix)
                entry = self.previews.get(key)
                if entry is None:
                    answer = self.peer.request({"request_type": "preview_steps", "game_id": self.game,
                        "expected_step": self.root["step"], "candidate_ids": prefix})
                    if answer["response_type"] == "error":
                        raise ProjectionError("private completion preview refused within its declaration")
                    if answer["response_type"] not in ("private_complete", "private_preview"):
                        raise ProjectionError("private completion preview returned an unexpected response")
                    view = answer["view"] if answer["response_type"] == "private_preview" else None
                    size = getattr(self.peer, "last_line_bytes", None)
                    entry = self.previews.put(key, [view, None], len(json.dumps(answer)) if size is None else size)
                if entry[0] is None:
                    break
            else:
                raise ProjectionError("private completion preview exceeded its bound")
            proposals.append(steps)
        original = self.root["extensions"][FLAT]
        extension = {"schema": PROPOSALS, "mapping": "deterministic-completion-logprob/v1", "tensor_encoding": PROPOSAL_ENCODING,
            **{key: original[key] for key in ("card_db_hash", "feature_contract_digest", "feature_encoding_digest")},
            "acting_seat": actor, "step": self.seat_steps[actor],
            "row_candidate_ids": list(range(candidate_count))}
        # Large graveyard orders repeat many tensor slices. The fast compressor
        # can miss those repetitions, and a whole-library mill also needs the
        # table grouped by key. First-use encodings are kept only while they
        # leave a quarter of the bound free, so a proposal near the limit moves
        # to the grouped table (about half the size) instead of riding the edge.
        # Proposals well under the bound keep their exact bytes.
        limit = wire.MAX_LINE_BYTES - 262144
        smallest = None
        for grouped, level in ((False, 1), (False, 9), (True, 9)):
            if level == 1 or grouped:
                payload = wire.canonical_json_dumps(intern_proposal_vectors(proposals, grouped=grouped))
                if len(payload) > 64 * 1024 * 1024:
                    raise ProjectionError("completion proposal exceeds the decoded payload bound")
            encoded = base64.b64encode(zlib.compress(payload, level=level)).decode("ascii")
            if smallest is None or len(encoded) < len(smallest):
                smallest = encoded
            extension["proposals_zlib"] = encoded
            if len(wire.canonical_json_dumps(extension)) <= limit * 3 // 4:
                break
        else:
            # Nothing left the margin: send the smallest encoding if it fits.
            extension["proposals_zlib"] = smallest
        extension_bytes = len(wire.canonical_json_dumps(extension))
        if extension_bytes > limit:
            raise ProjectionError(f"completion proposal exceeds the wire bound: "
                f"decoded={len(payload)} encoded_extension={extension_bytes} "
                f"limit={limit} candidates={candidate_count} "
                f"steps={sum(map(len, proposals))}")
        return extension

    def planned_line(self):
        """The advisor's planned line from the person's current decision (an ordinary one, not a grouped choice):
        the model's top choice, played on a clone of the game in the bridge (``private_line``; the game itself is
        never touched), then its top choice at the person's next decision, and so on, the opponent's bare priority
        passes taken for them, until the bridge or this planner ends it (``LINE_STOPS``, at most LINE_STEPS
        choices). Each step is the person's own choice as a protocol semantic (the client's words come from it), read
        from the person's own model input on the clone. Nothing else of the clone is kept: no counts, no opponent
        choice, no timing."""
        started = time.perf_counter()
        self._line_budget = LINE_SCORER_TIMEOUT_S
        try:
            steps, stop, result, ids = self._play_line()
        except (ProjectionError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            # The line never touches the game: whatever fails in it ends the line, never the game. (A bridge that is
            # gone fails the game's own next request too, with its own message.)
            print(f"kernel_engine_london_human_v1: planned line stopped: {type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)
            steps, stop, result, ids = [], "unavailable", None, []
        if self.line_timing is not None:
            try:  # a measurement only: a file that cannot be written never stops the game
                with open(self.line_timing, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"game": self.game, "step": self.current["step"], "choices": len(ids),
                                             "stop": stop, "seconds": round(time.perf_counter() - started, 6)}) + "\n")
            except OSError as exc:
                print(f"kernel_engine_london_human_v1: line timing not written: {exc}", file=sys.stderr, flush=True)
        return {"schema": LINE_SCHEMA, "steps": steps, "stop": stop, "result": result}

    def _play_line(self):
        projection = deepcopy(self.projection)  # the clone's objects never enter the game's own projection
        root, view = self.current, self.current
        ids, steps, stop, result = [], [], "bound", None
        block = None  # the block declaration being played (``_line_block_steps``)
        while True:
            raw = json.loads(view["extensions"]["x_kernel_v5"]["observation_json"])
            support = view["extensions"]["x_kernel_v2_support"]
            if view is not root:
                projection.project(raw, support, None)  # the clone view's objects, as the game's own views are
            if block is None and support.get("at_block_root") is True:
                # The person's block declaration, from the same public facts as the person's own block screen.
                plan, refs = native_block_plan(raw, support, projection)
                block = {"plan": plan, "refs": refs, "instance": support["block_declaration_instance"], "picks": []}
            if (block is None and len(steps) >= LINE_STEPS) or len(ids) >= LINE_NATIVE_IDS:
                stop = "bound"
                break
            pick = self._line_pick(view)
            if pick is None:
                stop = "unreadable" if self.line_scorer is not None else "unavailable"
                break
            if block is not None:
                block["picks"].append(view["candidates"][pick]["semantic"])
            else:
                steps.append(ordinary_semantic(view["candidates"][pick]["semantic"], raw, support, projection,
                                               view["group"], candidate_id=pick))
            ids.append(pick)
            answer = self.peer.request({"request_type": "private_line", "game_id": self.game,
                                        "expected_step": root["step"], "candidate_ids": ids})
            kind = answer.get("response_type")
            if kind == "private_line_stop" and answer.get("reason") in LINE_STOPS:
                stop, result = answer["reason"], answer.get("result")
                break
            if kind != "private_line":
                stop = "unavailable"
                break
            view = answer["view"]
            support = view["extensions"]["x_kernel_v2_support"]
            if block is not None and not (support.get("block_declaration_instance") == block["instance"]
                                          and all(candidate["semantic"]["kind"] == "choose_blocker_inclusion"
                                                  for candidate in view["candidates"])):
                steps.extend(_line_block_steps(block))  # the declaration is complete
                block = None
            if (support.get("choice", {}).get("purpose") in ARRANGEMENTS
                    or view["candidates"][0]["semantic"]["kind"] == "order_triggers"):
                stop = "grouped"
                break
        if block is not None and stop not in ("bound", "unreadable", "unavailable"):
            # A stop from the bridge inside a declaration follows its last answer: within a declaration nothing hidden
            # or random happens and only the person decides, so the bridge stops only once play has left it. A line
            # cut inside a declaration by this planner shows none of it.
            steps.extend(_line_block_steps(block))
        return steps, stop, result, ids

    def _line_pick(self, view):
        """The scorer's top row (the first of the highest, as the panel orders them) of a native decision of the
        person's, as a native candidate id; None when it cannot read it. A scorer that fails is dropped."""
        if self.line_scorer is None:
            return None
        decision = {"candidates": view["candidates"], "acting_seat": self.line_seat, "seat_step": 0}
        scorer, box = self.line_scorer, {}

        def exchange():
            try:
                box["read"] = scorer.read(f"line:{self.game}", decision, view["extensions"].get(FLAT))
            except Exception as exc:  # noqa: BLE001 - any failure of the scorer drops it
                box["error"] = exc

        # The whole exchange (writing the request, reading the answer) runs in a thread of its own, so a scorer that
        # stops reading cannot hold the decision past the line's budget.
        worker = threading.Thread(target=exchange, daemon=True, name="planned-line-scorer")
        began = time.monotonic()
        worker.start()
        worker.join(max(0.0, self._line_budget))
        self._line_budget -= time.monotonic() - began
        if worker.is_alive() or "error" in box:
            why = box.get("error") or f"no answer within the line's {LINE_SCORER_TIMEOUT_S:g} s"
            print(f"kernel_engine_london_human_v1: the planned line's scorer is dropped: {why}", file=sys.stderr,
                  flush=True)
            self.line_scorer = None
            threading.Thread(target=scorer.close, daemon=True, name="planned-line-scorer-close").start()
            return None
        read = box["read"]
        if "unavailable" in read or not read.get("rows"):
            return None
        top = max(read["rows"], key=lambda row: row["p"])  # max keeps the first of equal rows
        return top["id"]

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
            if self.buffer is not None:
                self.previews = PreviewCache()
        if (self.graveyard_order or {}).get("how") == "settled" and settle_graveyard_order(self.buffer):
            # Either seat: nothing is posed, and the bridge gets the native picks of a seat that took the first
            # candidate of every ordering substep.
            self.commit_buffer()
            self.buffer = self.previews = None
            return self.respond(rid)
        if self.buffer is not None and actor == self.native_seat:
            # The bot's grouped decision: nothing is posed to the protocol; the engine's own questions go to the
            # bot's model one at a time.
            self.play_native_group()
            self.buffer = self.previews = None
            return self.respond(rid)
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
            if all(semantic["kind"] == "order_pick" and semantic["purpose"] == "mulligan_bottom" for semantic in semantics):
                # One native bottom decision per card: the group is the seat's k bottoms in order.
                index, count = semantics[0]["position"], semantics[0]["count"]
            elif any(semantic["kind"] in ("finish_target_selection", "finish_selection") for semantic in semantics):
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
        if (LINE in self.rules["extensions"] and actor == self.line_seat
                and (self.buffer is None or (isinstance(self.buffer, BlockDeclaration) and not self.buffer.prefix))
                and not any(semantic["kind"] == "mulligan" or semantic.get("purpose") == "mulligan_bottom"
                            for semantic in semantics)):
            # An ordinary decision of the person's after the pregame, or the first question of their block declaration
            # (the line plays the whole declaration from the engine's untouched root); a later blocker's question, an
            # order, a mulligan or a bottom gets no line.
            extensions[LINE] = self.planned_line()
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


def _line_block_steps(block):
    """The block declaration a planned line played, blocker by blocker in the order the person's block screen asks
    them (public battlefield order), as the person's own block semantics. The engine asked attacker by attacker
    ("block this attacker with this creature?"); a blocker the model included for an attacker blocks it."""
    plan, refs = block["plan"], block["refs"]
    keys = {f"obj-{key[0]:06}-z{key[1]:04}": key for key in (*plan.blockers, *plan.minimums)}
    blocks = {}
    for semantic in block["picks"]:
        if semantic.get("include") is True:
            blocks[keys[semantic["blocker"]["object_id"]]] = keys[semantic["attacker"]["object_id"]]
    return [{"kind": "declare_block", "blocker": refs[blocker],
             "attacker": refs[blocks[blocker]] if blocker in blocks else None} for blocker in plan.blockers]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--known-cards", action="store_true",
                        help="declare known_cards and track Section 6.7 knowledge (needs a history-exporting bridge)")
    parser.add_argument("--engine-windows-seat", choices=("p0", "p1"),
                        help="the seat of a person: the bridge gives it every engine priority window (upkeep, draw, "
                             "beginning of combat, combat damage, end of combat, end step, its own spell on the "
                             "stack); the other seat keeps the windows its model trained on")
    parser.add_argument("--action-windows-seat", choices=("p0", "p1"),
                        help="the seat of a bot: the bridge offers it the priority windows its model trained with "
                             "(--action-windows-rule, default action-windows-v1: a window wherever it has a real "
                             "action, in every step and while holding priority); not the --engine-windows-seat")
    parser.add_argument("--action-windows-rule", choices=ACTION_WINDOWS_RULES, default=ACTION_WINDOWS_RULE,
                        help="with --action-windows-seat: the training window rule")
    parser.add_argument("--auto-graveyard-order", action="store_true",
                        help="in a game in which no card of either deck list reads graveyard order "
                             "(spellbench.human.graveyard_order), neither seat is asked to order cards put into a "
                             "graveyard together: the bridge applies the rule the bots trained with "
                             "(resolution-boundary-v1). In a game with such a card both seats are asked")
    parser.add_argument("--line-seat", choices=("p0", "p1"),
                        help="human play with an advisor: the person's seat, whose decisions carry the advisor's "
                             "planned line (x_advisor_line_v1) when the game's rules enable it")
    parser.add_argument("--line-scorer", default=None,
                        help="with --line-seat: the advisor's scorer command line, as a JSON list (the session's "
                             "advisor scorer: spellbench.human.advisor.scorer_argv)")
    parser.add_argument("--native-seat", choices=("p0", "p1"),
                        help="the seat of a bot whose block declarations, card arrangements, selection orders and "
                             "trigger orders are the engine's own questions, each sampled once by the bot's model "
                             "(--native-scorer) as the trainer's session samples them; not the person's seat")
    parser.add_argument("--native-scorer", default=None,
                        help="with --native-seat: the bot's scorer command line, as a JSON list (the bot's own "
                             "--scorer, --scorer-arg and --config: spellbench.human.advisor.scorer_argv)")
    parser.add_argument("--native-seed", type=int, default=0,
                        help="with --native-seat: the bot's --seed (its native questions use a second stream of it)")
    parser.add_argument("--native-expect-model-state", default=None, metavar="SHA256",
                        help="with --native-seat: the model state the bot's scorer must load (the bot's own "
                             "--expect-model-state)")
    parser.add_argument("--native-log", type=Path, default=None,
                        help="with --native-seat: append each native question asked (game, group kind, rows, the "
                             "sampled row and its seed) to this JSON-lines file")
    parser.add_argument("--native-trace", type=Path, default=None,
                        help="proof only: write one replay trace per game to this folder (every native step and the "
                             "model input of each of the bot's native questions)")
    parser.add_argument("--line-timing", type=Path, default=None,
                        help="with --line-seat: append each line's cost (seconds, choices, stop) to this JSON-lines "
                             "file")
    args = parser.parse_args()
    if args.action_windows_seat is not None and args.action_windows_seat == args.engine_windows_seat:
        parser.error("--action-windows-seat and --engine-windows-seat name different seats (a person and a bot)")
    if (args.line_scorer is not None or args.line_timing is not None) and args.line_seat is None:
        parser.error("--line-scorer and --line-timing go with --line-seat")
    if (args.native_seat is None) != (args.native_scorer is None):
        parser.error("--native-seat and --native-scorer go together")
    if args.native_seat is None and (args.native_log is not None or args.native_expect_model_state is not None
                                     or args.native_seed != 0):
        parser.error("--native-seed, --native-expect-model-state and --native-log go with --native-seat")
    if args.native_seat is not None and args.native_seat in (args.engine_windows_seat, args.line_seat):
        parser.error("--native-seat names the bot's seat, not the person's")
    if args.native_seed < 0:
        parser.error("--native-seed must be nonnegative")
    if args.known_cards:
        # The Section 6.7 knowledge tracker has not been taught the pregame's draws and bottoms; the London human
        # board does not declare known_cards.
        parser.error("--known-cards is not supported by the London human engine")
    scorer = None
    if args.line_scorer is not None:
        argv = json.loads(args.line_scorer)
        if not isinstance(argv, list) or not argv or not all(isinstance(word, str) for word in argv):
            parser.error("--line-scorer must be a JSON list of strings")
        try:
            scorer = Advisor(argv, name="planned-line", answer_timeout_s=LINE_SCORER_TIMEOUT_S)
        except AdvisorError as exc:
            parser.error(f"--line-scorer: {exc}")
    native = None
    if args.native_scorer is not None:
        argv = json.loads(args.native_scorer)
        if not isinstance(argv, list) or not argv or not all(isinstance(word, str) for word in argv):
            parser.error("--native-scorer must be a JSON list of strings")
        try:
            native = flat_bot.ScorerProcess(argv)
            check_native_scorer(native, args.native_expect_model_state)
        except (flat_bot.BotError, ValueError, OSError) as exc:
            if native is not None:
                native.close()
            parser.error(f"--native-scorer: {exc}")
    peer = NativePeer(args.bridge)
    try:
        engine = KernelEngine(peer, json.loads(args.catalog.read_bytes()), source_revision=args.source_revision,
                             known_cards=args.known_cards, engine_windows_seat=args.engine_windows_seat,
                             auto_graveyard_order=args.auto_graveyard_order, line_seat=args.line_seat,
                             line_scorer=scorer, line_timing=args.line_timing,
                             action_windows_seat=args.action_windows_seat,
                             action_windows_rule=args.action_windows_rule, native_seat=args.native_seat,
                             native_scorer=native, native_seed=args.native_seed, native_log=args.native_log,
                             native_trace=args.native_trace)
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
        if scorer is not None:
            scorer.close()
        if native is not None:
            native.close()


if __name__ == "__main__":
    sys.exit(main())
