"""Spellbench v2 environment over the pinned private native kernel bridge.

Private observations, native IDs and clone requests stay in this process.
Buffered declarations commit only after their complete neutral group.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import itertools
import json
import operator
import subprocess
import sys
import zlib
from collections import OrderedDict
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
from kernel_arrangement_v2 import (
    ArrangementViewIndex, indexed_arrangement_pick, native_arrangement,
    native_arrangement_binding, native_arrangement_pick,
)
from kernel_order_v2 import TriggerOrder
from kernel_selection_order_v2 import SelectionOrder, native_selection_order

FLAT = "x_kernel_flat_v4"
PROPOSALS = "mtg-kernel-spellbench-completion-proposals/v1"
PROPOSAL_ENCODING = "integer-rle-table/v1"
PREVIEW_CACHE_BYTES = 16 * 1024 * 1024  # response lines; parsed views take several times that

_INT_TYPE_SET = {int}
_MAX_JSON_INT = wire.MAX_JSON_INT
_MIN_JSON_INT = -wire.MAX_JSON_INT
_RLE_KEYS = frozenset({"length", "rle"})
_eq = operator.eq
_ne = operator.ne
_sub = operator.sub
_gt = operator.gt
_islice = itertools.islice
_compress = itertools.compress
_repeat = itertools.repeat


def _plain_ints_bounds(values):
    """Return (True, min_val, max_val) for a list of canonical JSON integers, else (False, 0, 0)."""
    if type(values) is not list:
        return False, 0, 0
    if not values:
        return True, 0, 0
    if set(map(type, values)) != _INT_TYPE_SET:
        return False, 0, 0
    lo = min(values)
    hi = max(values)
    if lo < _MIN_JSON_INT or hi > _MAX_JSON_INT:
        return False, 0, 0
    return True, lo, hi


def _plain_ints(values):
    """True for a list of canonical JSON integers (no bools), whose canonical text is plain ``str(value)``."""
    return _plain_ints_bounds(values)[0]


def _ints_length(values):
    """The length of the canonical JSON of a list of plain integers, without encoding it."""
    return 2 + sum(map(len, map(str, values))) + max(0, len(values) - 1)


def _pack_plain_ints(values, lo, hi):
    """Losslessly RLE-pack a validated plain-int list iff its canonical JSON is strictly shorter."""
    n = len(values)
    if n < 2:
        return values
    eq_vals = list(_compress(values, map(_eq, values, _islice(values, 1, None))))
    eq_count = len(eq_vals)
    if eq_count == 0:
        return values
    r = n - eq_count
    # Plain length = 1 + n + sum(c_i * d(v_i));
    # RLE length = 19 + d(n) + 4 * r + sum(d(v_i) + d(c_i)).
    # RLE < plain iff sum_{c_i > 1}((c_i - 1) * d(v_i) - (d(c_i) - 1)) > 18 + d(n) + 5 * r - n.
    threshold = 18 + len(str(n)) + 5 * r - n
    max_d = max(len(str(lo)), len(str(hi)))
    # Each 0 in eq_vals contributes d(0) = 1, each non-zero <= max_d, and d(c_i) - 1 >= 0.
    non_zero_eq = eq_count - eq_vals.count(0)
    if eq_count + non_zero_eq * (max_d - 1) <= threshold:
        return values
    starts = [0, *_compress(range(1, n), map(_ne, values, _islice(values, 1, None))), n]
    counts = list(map(_sub, _islice(starts, 1, None), starts))
    gt1 = list(map(_gt, counts, _repeat(1)))
    savings = 0
    _len = len
    _str = str
    for idx, c in zip(_compress(starts, gt1), _compress(counts, gt1)):
        v = values[idx]
        dv = 1 if 0 <= v < 10 else _len(_str(v))
        if c < 10:
            savings += (c - 1) * dv
        else:
            savings += (c - 1) * dv - (_len(_str(c)) - 1)
    if savings > threshold:
        return {"length": n, "rle": list(map(list, zip(map(values.__getitem__, _islice(starts, r)), counts)))}
    return values


def _pack_non_plain(values):
    runs = []
    for value in values:
        if runs and runs[-1][0] == value:
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    packed = {"length": len(values), "rle": runs}
    shorter = len(wire.canonical_json_dumps(packed)) < len(wire.canonical_json_dumps(values))
    return packed if shorter else values


def pack_proposal_tensor(tensor):
    """Losslessly shorten float-bit words and signed metadata integers."""
    result = {}
    for key, values in tensor.items():
        plain, lo, hi = _plain_ints_bounds(values)
        if plain:
            result[key] = _pack_plain_ints(values, lo, hi)
        else:
            result[key] = _pack_non_plain(values)
    return result


def _is_plain_rle(item):
    if (type(item) is not dict or item.keys() != _RLE_KEYS
            or type(item["length"]) is not int
            or not (_MIN_JSON_INT <= item["length"] <= _MAX_JSON_INT)
            or type(item["rle"]) is not list):
        return False
    return all(
        type(run) is list and len(run) == 2
        and type(run[0]) is int and type(run[1]) is int
        and _MIN_JSON_INT <= run[0] <= _MAX_JSON_INT
        and _MIN_JSON_INT <= run[1] <= _MAX_JSON_INT
        for run in item["rle"]
    )


def _encode_packed_tensor(packed):
    """Encode an already-packed tensor to per-key canonical JSON bytes if all keys/values are plain."""
    encoded = {}
    for key, item in packed.items():
        if type(key) is not str or not key.isascii():
            return None, False
        if type(item) is list:
            if not item:
                encoded[key] = b"[]"
                continue
            if not _plain_ints_bounds(item)[0]:
                return None, False
        elif not _is_plain_rle(item):
            return None, False
        encoded[key] = json.dumps(item, separators=(",", ":")).encode("ascii")
    return encoded, True


def _pack_and_encode_tensor(tensor, previews):
    """Pack a tensor and produce each key's canonical JSON bytes when all keys/values are plain ASCII/int."""
    packed = {}
    encoded = {}
    all_plain = True
    use_key_cache = previews is not None and previews.bound > 0
    for key, values in tensor.items():
        if type(key) is not str or not key.isascii():
            all_plain = False
        plain, lo, hi = _plain_ints_bounds(values)
        if plain:
            if not values:
                packed[key] = values
                if all_plain:
                    encoded[key] = b"[]"
                continue
            cache_key = (key, len(values))
            if use_key_cache:
                cached = previews.get_key_cache(cache_key)
                if cached is not None and values == cached[0]:
                    packed[key] = cached[1]
                    if all_plain:
                        encoded[key] = cached[2]
                    continue
            item = _pack_plain_ints(values, lo, hi)
            packed[key] = item
            if all_plain:
                # Plain int lists and {"length": int, "rle": [[int, int], ...]} are already
                # canonical ASCII JSON with keys in UTF-16 order ("length" < "rle").
                raw = json.dumps(item, separators=(",", ":")).encode("ascii")
                encoded[key] = raw
                if use_key_cache:
                    previews.put_key_cache(cache_key, values, item, raw)
        else:
            all_plain = False
            packed[key] = _pack_non_plain(values)
    if not all_plain:
        return packed, None, False
    return packed, encoded, True


def _vector_key(words):
    """A key equal for two vectors exactly when their canonical JSON is equal."""
    if _plain_ints(words):
        return tuple(words)
    if _is_plain_rle(words):
        return (words["length"], tuple(map(tuple, words["rle"])))
    return wire.canonical_json_dumps(words)


def intern_proposal_vectors(proposals, grouped=False):
    """Store exact repeated arrays once, without changing any score input.

    grouped lists the table by tensor key and then trajectory step instead of
    first use. Consecutive steps of a long order differ in a few rows, and
    grouping puts those near-copies next to each other where zlib's 32 KiB
    window can match them. The scorer resolves indices either way."""
    vectors, keys, indices, indexed = [], [], {}, []
    seen_ids = {}
    for trajectory in proposals:
        steps = []
        for position, step in enumerate(trajectory):
            tensor = {}
            for key, words in step["tensor"].items():
                wid = id(words)
                idx = seen_ids.get(wid)
                if idx is None:
                    encoded = _vector_key(words)
                    idx = indices.get(encoded)
                    if idx is None:
                        idx = len(vectors)
                        indices[encoded] = idx
                        vectors.append(words)
                        keys.append((key, position))
                    seen_ids[wid] = idx
                tensor[key] = {"vector": idx}
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


def _encode_plain_proposal_tables(encoded_proposals):
    """Build exact canonical JSON bytes for ungrouped (and lazily grouped) interned tables.

    Callers guarantee every key is an ASCII str and every vector is already exact canonical
    ASCII JSON bytes (plain int list or plain int RLE object). Keys are encoded through
    wire.canonical_json_dumps (ensure_ascii=False) so ASCII DEL (0x7f) and all control
    characters match origin/main byte-for-byte."""
    vectors = []
    keys = []
    indices = {}
    step_idx_cache = {}
    step_json_u = {}
    sorted_key_cache = {}
    traj_step_wids = []
    traj_strs = []

    for trajectory in encoded_proposals:
        step_strs = []
        step_wids = []
        for position, (vec_map, selected_row) in enumerate(trajectory):
            wid = id(vec_map)
            tensor_json = step_json_u.get(wid)
            if tensor_json is None:
                tensor_idx = {}
                for key, raw in vec_map.items():
                    idx = indices.get(raw)
                    if idx is None:
                        idx = len(vectors)
                        indices[raw] = idx
                        vectors.append(raw)
                        keys.append((key, position))
                    tensor_idx[key] = idx
                key_tuple = tuple(vec_map)
                sorted_keys = sorted_key_cache.get(key_tuple)
                if sorted_keys is None:
                    sorted_keys = tuple(
                        (k, wire.canonical_json_dumps(k).decode("ascii"))
                        for k in sorted(key_tuple)
                    )
                    sorted_key_cache[key_tuple] = sorted_keys
                tensor_json = "{" + ",".join(
                    f'{k_json}:{{"vector":{tensor_idx[k]}}}' for k, k_json in sorted_keys
                ) + "}"
                step_idx_cache[wid] = (tensor_idx, sorted_keys)
                step_json_u[wid] = tensor_json
            step_wids.append((wid, selected_row))
            step_strs.append(f'{{"selected_row":{selected_row},"tensor":{tensor_json}}}')
        traj_step_wids.append(step_wids)
        traj_strs.append("[" + ",".join(step_strs) + "]")

    proposals_u = ("[" + ",".join(traj_strs) + "]").encode("ascii")
    payload_u = b'{"proposals":' + proposals_u + b',"vectors":[' + b",".join(vectors) + b"]}"

    def build_grouped():
        order = sorted(range(len(vectors)), key=keys.__getitem__)
        rank = [0] * len(order)
        for new, old in enumerate(order):
            rank[old] = new
        step_json_g = {}
        g_traj_strs = []
        for step_wids in traj_step_wids:
            g_step_strs = []
            for wid, selected_row in step_wids:
                tensor_json = step_json_g.get(wid)
                if tensor_json is None:
                    tensor_idx, sorted_keys = step_idx_cache[wid]
                    tensor_json = "{" + ",".join(
                        f'{k_json}:{{"vector":{rank[tensor_idx[k]]}}}' for k, k_json in sorted_keys
                    ) + "}"
                    step_json_g[wid] = tensor_json
                g_step_strs.append(f'{{"selected_row":{selected_row},"tensor":{tensor_json}}}')
            g_traj_strs.append("[" + ",".join(g_step_strs) + "]")
        proposals_g = ("[" + ",".join(g_traj_strs) + "]").encode("ascii")
        return b'{"proposals":' + proposals_g + b',"vectors":[' + b",".join(vectors[old] for old in order) + b"]}"

    return payload_u, build_grouped


def _nested_key_bytes(value):
    if isinstance(value, str):
        return len(value) + 16
    if isinstance(value, tuple):
        return 32 + sum(_nested_key_bytes(item) for item in value)
    return 16


def _meta_entry_bytes(vec_bytes, view_index):
    size = 64
    if vec_bytes is not None:
        size += sum(len(k) + len(raw) + 32 for k, raw in vec_bytes.items())
    if view_index is not None:
        size += 64
        if view_index.row_of_candidate is not None:
            size += 16 * len(view_index.row_of_candidate)
        if view_index.matches is not None:
            size += sum((len(k) if isinstance(k, str) else 8) + 16 for k in view_index.matches)
    return size


def _key_cache_entry_bytes(values, item, raw):
    rle_bytes = 0 if item is values else 16 * len(item["rle"])
    return 64 + len(raw) + 8 * len(values) + rle_bytes


def _carried_entry_bytes(plan_key, native_picks, entry_gens, selected_rows):
    return (
        64
        + _nested_key_bytes(plan_key)
        + 16 * (len(native_picks) + len(entry_gens) + len(selected_rows))
    )


class PreviewCache:
    """Private previews of one buffered declaration, keyed by native prefix.

    A preview is a pure function of the declaration's root and its native
    prefix, so a stored answer equals a fresh one. Every candidate's completion
    replays the declaration's shared prefix, which stays recently used; other
    entries leave oldest first once the stored response bytes pass the bound.

    Derived caches (meta, key_cache, carried) count against the same total byte
    bound, are disabled when bound <= 0, and are trimmed before entries are
    affected so entry eviction and bridge calls stay identical to origin/main."""

    def __init__(self, bound=PREVIEW_CACHE_BYTES):
        self.entries, self.bytes, self.bound = OrderedDict(), 0, bound
        self._entry_bytes = 0
        self._entry_gen = {}
        self._next_gen = 1
        self.meta = OrderedDict()
        self._meta_bytes = 0
        self.key_cache = OrderedDict()
        self._key_cache_bytes = 0
        self.carried = OrderedDict()
        self._carried_bytes = 0
        self.carried_order = []

    def _sync_bytes(self):
        self.bytes = (
            self._entry_bytes
            + self._meta_bytes
            + self._key_cache_bytes
            + self._carried_bytes
        )

    def _trim_extras(self, reserve=0, *, allow_evict_carried=True):
        """Evict derived caches until total bytes + reserve <= bound (or derived caches are empty)."""
        if reserve > 0:
            floor = self._entry_bytes + (0 if allow_evict_carried else self._carried_bytes)
            if self.bound <= 0 or floor + reserve > self.bound:
                return False
        limit = self.bound - reserve
        while self.bytes > limit and self.key_cache:
            _, dropped = self.key_cache.popitem(last=False)
            self._key_cache_bytes -= dropped[3]
            self._sync_bytes()
        while self.bytes > limit and self.meta:
            _, dropped = self.meta.popitem(last=False)
            self._meta_bytes -= dropped[3]
            self._sync_bytes()
        if allow_evict_carried:
            while self.bytes > limit and self.carried:
                _, dropped = self.carried.popitem(last=False)
                self._carried_bytes -= dropped[4]
                self._sync_bytes()
        return self.bound > 0 and self.bytes <= limit

    def get(self, key):
        stored = self.entries.get(key)
        if stored is None:
            return None
        self.entries.move_to_end(key)
        if key in self.meta:
            self.meta.move_to_end(key)
        return stored[0]

    def entry_gen(self, key):
        return self._entry_gen.get(key)

    def put(self, key, entry, size):
        """Store [view or None when complete, packed tensor or None] and return it."""
        old = self.entries.get(key)
        if old is not None:
            self._entry_bytes -= old[1]
            self.entries.move_to_end(key)
        old_meta = self.meta.pop(key, None)
        if old_meta is not None:
            self._meta_bytes -= old_meta[3]
        self.entries[key] = entry, size
        self._entry_bytes += size
        if self.bound > 0:
            self._entry_gen[key] = self._next_gen
            self._next_gen += 1
        while self._entry_bytes > self.bound and len(self.entries) > 1:
            dropped_key, (_, dropped) = self.entries.popitem(last=False)
            self._entry_bytes -= dropped
            self._entry_gen.pop(dropped_key, None)
            dropped_meta = self.meta.pop(dropped_key, None)
            if dropped_meta is not None:
                self._meta_bytes -= dropped_meta[3]
        self._sync_bytes()
        if self.bytes > self.bound:
            self._trim_extras()
        return entry

    def get_meta(self, key):
        stored = self.meta.get(key)
        if stored is None:
            return None
        self.meta.move_to_end(key)
        return stored

    def put_meta(self, key, vec_bytes, all_plain, view_index):
        if self.bound <= 0 or key not in self.entries:
            return
        old = self.meta.pop(key, None)
        if old is not None:
            self._meta_bytes -= old[3]
            self._sync_bytes()
        size = _meta_entry_bytes(vec_bytes, view_index)
        if self._trim_extras(reserve=size, allow_evict_carried=False):
            self.meta[key] = (vec_bytes, all_plain, view_index, size)
            self._meta_bytes += size
            self._sync_bytes()
        elif vec_bytes is not None and view_index is not None:
            # Keep at least the small view index if vec_bytes did not fit.
            idx_size = _meta_entry_bytes(None, view_index)
            if self._trim_extras(reserve=idx_size, allow_evict_carried=False):
                self.meta[key] = (None, all_plain, view_index, idx_size)
                self._meta_bytes += idx_size
                self._sync_bytes()

    def get_key_cache(self, cache_key):
        if self.bound <= 0:
            return None
        stored = self.key_cache.get(cache_key)
        if stored is None:
            return None
        self.key_cache.move_to_end(cache_key)
        return stored

    def put_key_cache(self, cache_key, values, item, raw):
        if self.bound <= 0:
            return
        old = self.key_cache.pop(cache_key, None)
        if old is not None:
            self._key_cache_bytes -= old[3]
            self._sync_bytes()
        size = _key_cache_entry_bytes(values, item, raw)
        # Key cache may evict older key_cache items, never meta/carried/entries.
        floor = self._entry_bytes + self._meta_bytes + self._carried_bytes
        if floor + size > self.bound:
            return
        limit = self.bound - size
        while self.bytes > limit and self.key_cache:
            _, dropped = self.key_cache.popitem(last=False)
            self._key_cache_bytes -= dropped[3]
            self._sync_bytes()
        if self.bytes <= limit:
            self.key_cache[cache_key] = (values, item, raw, size)
            self._key_cache_bytes += size
            self._sync_bytes()

    def put_carried(self, plan_key, native_picks, entry_gens, selected_rows, prefix_verified):
        if self.bound <= 0:
            return False
        old = self.carried.pop(plan_key, None)
        if old is not None:
            self._carried_bytes -= old[4]
            self._sync_bytes()
        size = _carried_entry_bytes(plan_key, native_picks, entry_gens, selected_rows)
        if self._trim_extras(reserve=size):
            self.carried[plan_key] = (native_picks, entry_gens, selected_rows, prefix_verified, size)
            self._carried_bytes += size
            self._sync_bytes()
            return True
        return False

    def clear_carried(self):
        self.carried.clear()
        self._carried_bytes = 0
        self.carried_order = []
        self._sync_bytes()

    def select_candidate(self, candidate):
        """Keep only the chosen candidate's carried completion after a buffered pick."""
        kept = None
        plan_key = None
        if 0 <= candidate < len(self.carried_order):
            plan_key = self.carried_order[candidate]
            if plan_key is not None:
                kept = self.carried.get(plan_key)
        self.carried.clear()
        self._carried_bytes = 0
        if kept is not None:
            self.carried[plan_key] = kept
            self._carried_bytes = kept[4]
        self.carried_order = []
        self._sync_bytes()


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
        self.last_line_bytes = len(line)
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
        self.buffer = self.previews = None
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
                    self.buffer = self.previews = None
                elif isinstance(self.previews, PreviewCache):
                    self.previews.select_candidate(candidate)
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

    def _pack_view(self, key, entry, previews, use_cache):
        """Ensure packed tensor and canonical vector bytes are available for a preview entry."""
        cached_meta = previews.get_meta(key) if (use_cache and previews.bound > 0) else None
        if cached_meta is not None and entry[1] is not None and (cached_meta[0] is not None or not cached_meta[1]):
            return entry[1], cached_meta[0], cached_meta[1]
        if entry[1] is not None:
            packed = entry[1]
            vec_bytes, all_plain = _encode_packed_tensor(packed)
        else:
            flat = entry[0]["extensions"][FLAT]
            packed, vec_bytes, all_plain = _pack_and_encode_tensor(
                flat["tensor"], previews if (use_cache and previews.bound > 0) else None
            )
            entry[1] = packed
        if use_cache and previews.bound > 0 and key in previews.entries:
            view_index = cached_meta[2] if cached_meta is not None else None
            previews.put_meta(key, vec_bytes, all_plain, view_index)
        return packed, vec_bytes, all_plain

    def _arrangement_index(self, key, view, binding, previews, use_cache):
        """Return a cached ArrangementViewIndex for one preview view."""
        cached_meta = previews.get_meta(key) if (use_cache and previews.bound > 0) else None
        if cached_meta is not None and cached_meta[2] is not None:
            return cached_meta[2]
        view_index = ArrangementViewIndex(view, binding)
        if use_cache and previews.bound > 0 and key in previews.entries:
            vec_bytes = cached_meta[0] if cached_meta is not None else None
            all_plain = cached_meta[1] if cached_meta is not None else True
            previews.put_meta(key, vec_bytes, all_plain, view_index)
        return view_index

    def _fetch_preview(self, prefix, key, previews):
        answer = self.peer.request({"request_type": "preview_steps", "game_id": self.game,
            "expected_step": self.root["step"], "candidate_ids": prefix})
        if answer["response_type"] == "error":
            raise ProjectionError("private completion preview refused within its declaration")
        if answer["response_type"] not in ("private_complete", "private_preview"):
            raise ProjectionError("private completion preview returned an unexpected response")
        view = answer["view"] if answer["response_type"] == "private_preview" else None
        size = getattr(self.peer, "last_line_bytes", None)
        entry_size = len(json.dumps(answer)) if size is None else size
        return previews.put(key, [view, None], entry_size)

    def proposal_extension(self, actor, candidate_count):
        previews = self.previews
        use_cache = isinstance(previews, PreviewCache)
        cache_bound = previews.bound if use_cache else 0
        prev_carried = dict(previews.carried) if (use_cache and cache_bound > 0) else {}
        if use_cache:
            previews.clear_carried()
        carried_order = []
        encoded_proposals = []
        plain_proposals = []
        all_plain = True

        buf = self.buffer
        is_trigger = isinstance(buf, TriggerOrder)
        is_block = isinstance(buf, BlockDeclaration)
        is_pure_order = isinstance(buf, SelectionOrder) and not buf.selecting
        arr_binding = None if (is_trigger or is_block) else native_arrangement_binding(self.root, self.arrangement_cards)
        is_graveyard_order = (
            use_cache and cache_bound > 0 and is_pure_order
            and buf.destination == "graveyard"
            and arr_binding.purpose in ("mill", "discard_order")
        )
        shared_depth = len(buf.order) if is_graveyard_order else 0
        can_share_prefix = is_graveyard_order and shared_depth > 0
        shared_enc = shared_plain = shared_picks = shared_key_gens = shared_rows = None
        shared_all_plain = True
        order_prefix_ids = tuple(c["object_id"] for c in buf.order) if is_pure_order else ()
        pure_choices = [c["object_id"] for c in buf.choices()] if is_pure_order else None

        trigger_packed = trigger_vec_bytes = trigger_row_map = None
        if is_trigger and candidate_count:
            flat = self.root["extensions"][FLAT]
            trigger_packed, trigger_vec_bytes, trigger_plain = _pack_and_encode_tensor(
                flat["tensor"], previews if (use_cache and cache_bound > 0) else None
            )
            if not trigger_plain:
                all_plain = False
            trigger_row_map = {}
            for row, cid in enumerate(flat["row_candidate_ids"]):
                if cid not in trigger_row_map:
                    trigger_row_map[cid] = row

        for candidate in range(candidate_count):
            if is_pure_order:
                picked_id = pure_choices[candidate]
                result = {buf.destination: order_prefix_ids + (picked_id,)
                          + tuple(oid for i, oid in enumerate(pure_choices) if i != candidate)}
                plan_key = ("arr", arr_binding.purpose, buf.destination, result[buf.destination])
            else:
                plan = deepcopy(buf)
                finished = plan.choose(candidate)
                while not finished:
                    finished = plan.choose(0)
                if is_trigger:
                    selected = plan.result()
                    row = trigger_row_map[selected]
                    encoded_proposals.append([(trigger_vec_bytes, row)])
                    plain_proposals.append([{"tensor": trigger_packed, "selected_row": row}])
                    continue
                if is_block:
                    block_binding = legacy_block_assignment(self.root, plan.plan, plan.assignment())
                    plan_key = ("block", tuple(plan.prefix))
                else:
                    result = plan.result()
                    plan_key = ("arr", arr_binding.purpose, tuple(sorted(result.items())))

            # Touch/insert root entry first so cache eviction and LRU order match origin/main.
            root_entry = previews.get(()) or previews.put((), [self.root, None], 0)

            carried_hit = prev_carried.get(plan_key)
            if carried_hit is not None and use_cache and cache_bound > 0:
                native_picks, entry_gens, selected_rows, prefix_verified, _ = carried_hit
                if previews.entry_gen(()) == entry_gens[0]:
                    prefix_keys = tuple(native_picks[:k] for k in range(1, len(native_picks) + 1))
                    if all(previews.entry_gen(k) == g for k, g in zip(prefix_keys, entry_gens[1:])):
                        # Every prefix of this completion is still live in previews.entries
                        # without eviction, so origin/main would make zero bridge calls.
                        enc_steps = []
                        pl_steps = []
                        traj_plain = True
                        cur_key = ()
                        cur_entry = root_entry
                        for step_idx, row in enumerate(selected_rows):
                            packed, vec_bytes, step_plain = self._pack_view(cur_key, cur_entry, previews, use_cache)
                            if not step_plain:
                                traj_plain = False
                            enc_steps.append((vec_bytes, row))
                            pl_steps.append({"tensor": packed, "selected_row": row})
                            cur_key = prefix_keys[step_idx]
                            cur_entry = previews.get(cur_key)
                        encoded_proposals.append(enc_steps)
                        plain_proposals.append(pl_steps)
                        if not traj_plain:
                            all_plain = False
                        if candidate == 0 and can_share_prefix and prefix_verified and len(native_picks) > shared_depth:
                            shared_enc = enc_steps[:shared_depth]
                            shared_plain = pl_steps[:shared_depth]
                            shared_picks = native_picks[:shared_depth]
                            shared_rows = selected_rows[:shared_depth]
                            shared_key_gens = tuple(zip(((),) + prefix_keys[:shared_depth], entry_gens[:shared_depth + 1]))
                            shared_all_plain = traj_plain
                        if previews.put_carried(plan_key, native_picks, entry_gens, selected_rows, prefix_verified):
                            carried_order.append(plan_key)
                        else:
                            carried_order.append(None)
                        continue

            enc_steps = []
            pl_steps = []
            traj_plain = True
            prefix_verified = is_graveyard_order

            if (candidate > 0 and shared_key_gens is not None
                    and all(previews.entry_gen(k) == g for k, g in shared_key_gens)):
                enc_steps = list(shared_enc)
                pl_steps = list(shared_plain)
                if not shared_all_plain:
                    traj_plain = False
                prefix = list(shared_picks)
                step_rows = list(shared_rows)
                step_entry_gens = [g for _, g in shared_key_gens]
                entry = root_entry
                for k, _ in shared_key_gens[1:]:
                    entry = previews.get(k)
                key = shared_picks
                step_num = shared_depth
            else:
                key = ()
                entry = root_entry
                prefix = []
                step_rows = []
                step_entry_gens = [previews.entry_gen(())] if (use_cache and cache_bound > 0) else []
                step_num = 0

            for _ in range(4096 - step_num):
                view = entry[0]
                if view is None:
                    break
                if is_block:
                    selected = native_block_pick(view, block_binding)
                    row = view["extensions"][FLAT]["row_candidate_ids"].index(selected)
                else:
                    view_index = self._arrangement_index(key, view, arr_binding, previews, use_cache)
                    if prefix_verified and view_index.selected != step_num:
                        prefix_verified = False
                    if view_index.matches is not None:
                        selected = indexed_arrangement_pick(view_index, result, arr_binding)
                        row = view_index.row_of_candidate[selected]
                    else:
                        selected = native_arrangement_pick(view, result, arr_binding)
                        row = view["extensions"][FLAT]["row_candidate_ids"].index(selected)
                packed, vec_bytes, step_plain = self._pack_view(key, entry, previews, use_cache)
                if not step_plain:
                    traj_plain = False
                enc_steps.append((vec_bytes, row))
                pl_steps.append({"tensor": packed, "selected_row": row})
                step_rows.append(row)
                prefix.append(selected)
                key = tuple(prefix)
                entry = previews.get(key)
                if entry is None:
                    entry = self._fetch_preview(prefix, key, previews)
                if use_cache and cache_bound > 0:
                    step_entry_gens.append(previews.entry_gen(key))
                step_num += 1
                if entry[0] is None:
                    break
            else:
                raise ProjectionError("private completion preview exceeded its bound")

            native_picks = tuple(prefix)
            encoded_proposals.append(enc_steps)
            plain_proposals.append(pl_steps)
            if not traj_plain:
                all_plain = False
            if use_cache and cache_bound > 0:
                entry_gens_tuple = tuple(step_entry_gens)
                rows_tuple = tuple(step_rows)
                if (candidate == 0 and can_share_prefix and prefix_verified
                        and len(native_picks) > shared_depth):
                    prefix_keys = ((),) + tuple(native_picks[:k] for k in range(1, shared_depth + 1))
                    if all(previews.entry_gen(k) == g for k, g in zip(prefix_keys, entry_gens_tuple[:shared_depth + 1])):
                        shared_enc = enc_steps[:shared_depth]
                        shared_plain = pl_steps[:shared_depth]
                        shared_picks = native_picks[:shared_depth]
                        shared_rows = rows_tuple[:shared_depth]
                        shared_key_gens = tuple(zip(prefix_keys, entry_gens_tuple[:shared_depth + 1]))
                        shared_all_plain = traj_plain
                all_keys = ((),) + tuple(native_picks[:k] for k in range(1, len(native_picks) + 1))
                if (all(g is not None and previews.entry_gen(k) == g for k, g in zip(all_keys, entry_gens_tuple))
                        and previews.put_carried(plan_key, native_picks, entry_gens_tuple, rows_tuple, prefix_verified)):
                    carried_order.append(plan_key)
                else:
                    carried_order.append(None)

        if use_cache and cache_bound > 0:
            previews.carried_order = carried_order

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
        margin = limit * 3 // 4

        if all_plain:
            payload_u, build_grouped = _encode_plain_proposal_tables(encoded_proposals)
        else:
            payload_u = wire.canonical_json_dumps(intern_proposal_vectors(plain_proposals, grouped=False))
            build_grouped = lambda: wire.canonical_json_dumps(intern_proposal_vectors(plain_proposals, grouped=True))

        decoded_len = len(payload_u)
        if decoded_len > 64 * 1024 * 1024:
            raise ProjectionError("completion proposal exceeds the decoded payload bound")

        extension["proposals_zlib"] = ""
        base_len = len(wire.canonical_json_dumps(extension))

        # One-shot zlib.compress matches origin/main byte-for-byte on every zlib (including zlib-ng).
        c1 = zlib.compress(payload_u, level=1)
        b1 = 4 * ((len(c1) + 2) // 3)
        best_raw, best_b64_len = c1, b1
        if base_len + b1 <= margin:
            chosen = c1
        else:
            c9 = zlib.compress(payload_u, level=9)
            b9 = 4 * ((len(c9) + 2) // 3)
            if b9 < best_b64_len:
                best_raw, best_b64_len = c9, b9
            if base_len + b9 <= margin:
                chosen = c9
            else:
                payload_g = build_grouped()
                decoded_len = len(payload_g)
                if decoded_len > 64 * 1024 * 1024:
                    raise ProjectionError("completion proposal exceeds the decoded payload bound")
                cg9 = zlib.compress(payload_g, level=9)
                bg9 = 4 * ((len(cg9) + 2) // 3)
                if bg9 < best_b64_len:
                    best_raw, best_b64_len = cg9, bg9
                if base_len + bg9 <= margin:
                    chosen = cg9
                else:
                    # Nothing left the margin: send the smallest base64 encoding, earliest on ties.
                    chosen = best_raw

        encoded = base64.b64encode(chosen).decode("ascii")
        extension["proposals_zlib"] = encoded
        extension_bytes = base_len + len(encoded)
        if extension_bytes > limit:
            raise ProjectionError(f"completion proposal exceeds the wire bound: "
                f"decoded={decoded_len} encoded_extension={extension_bytes} "
                f"limit={limit} candidates={candidate_count} "
                f"steps={sum(map(len, encoded_proposals))}")
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
            if self.buffer is not None:
                self.previews = PreviewCache()
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
