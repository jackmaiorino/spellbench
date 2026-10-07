"""Original YES/NO and X slots, paired scoring and game-owned Java choice."""
from __future__ import annotations

import copy
import struct
import re

from spellbench import observation, wire
from xmage_maintainer_inference import validate_features
from xmage_maintainer_modes import ModeSession
from xmage_maintainer_sources import CALLBACK_SHA256, DIALOG_VARIANT, MANA_PAYMENT_VARIANT
from xmage_neural_decisions import decision_hash

SOURCE_KEYS = ("encoder_source_sha256", "candidate_source_sha256", "dialog_rules_source_sha256", "embedding_cache_sha256")
PAYMENT_SOURCE_KEYS = SOURCE_KEYS + ("mana_payment_rules_source_sha256",)
DIALOG_PAYMENT_VARIANT = DIALOG_VARIANT + "; " + MANA_PAYMENT_VARIANT
MAX_INT = 2**31 - 1


def value(semantic: dict):
    kind = semantic.get("kind")
    if kind == "choose_boolean" and type(semantic.get("value")) is bool:
        return semantic["value"]
    if kind == "optional_cost" and type(semantic.get("pay")) is bool and isinstance(semantic.get("cost"), str) and semantic["cost"]:
        return semantic["pay"]
    if kind == "choose_cast_method" and semantic.get("method") in ("normal", "evoke", "alternative"):
        return semantic["method"] != "normal"
    if kind == "choose_number" and type(semantic.get("value")) is int and semantic.get("purpose") == "x_value":
        return semantic["value"]
    raise ValueError("the maintainer's dialog needs its actual binary or X semantic")


def view(start: dict, decision: dict):
    obs, context = decision.get("observation", {}), decision.get("context", {})
    seat, source = start.get("seat"), context.get("source")
    if (seat not in ("p0", "p1") or seat != decision.get("acting_seat") or seat != obs.get("viewer")
            or context.get("kind") != "choice"):
        raise ValueError("the maintainer's dialog belongs to another acting viewer or callback")
    if source is not None:
        if not isinstance(source, dict) or not source.get("card_name"):
            raise ValueError("the maintainer's dialog source must be a named permitted reference")
        try:
            refs = [ref for _, ref in observation.observation_objects(obs) if ref["object_id"] == source.get("object_id")]
        except (KeyError, TypeError) as exc:
            raise ValueError("dialog source observation is incomplete") from exc
        if not refs or any(wire.canonical_json_dumps(ref) != wire.canonical_json_dumps(source) for ref in refs):
            raise ValueError("dialog source differs from its visible reference")
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 4096:
        raise ValueError("dialog needs its offered action list")
    offered, by_value, family, shared, bounds = {}, {}, None, None, None
    for candidate in candidates:
        cid, semantic = candidate.get("candidate_id"), candidate.get("semantic", {})
        if (type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT or cid in offered
                or wire.canonical_json_dumps(semantic.get("source")) != wire.canonical_json_dumps(source)):
            raise ValueError("dialog actions are aliased or belong to another source")
        chosen, kind = value(semantic), semantic["kind"]
        if chosen in by_value:
            raise ValueError("dialog has repeated original semantic values")
        metadata = copy.deepcopy(semantic)
        metadata.pop("value" if kind in ("choose_boolean", "choose_number") else "pay" if kind == "optional_cost" else "method")
        if family is not None and (kind != family or wire.canonical_json_dumps(metadata) != wire.canonical_json_dumps(shared)):
            raise ValueError("dialog actions disagree on their callback metadata")
        if kind == "choose_number":
            lo, hi = semantic.get("minimum"), semantic.get("maximum")
            if (type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= MAX_INT
                    or hi-lo+1 > 4096 or not lo <= chosen <= hi):
                raise ValueError("X action has an invalid offered range")
            bounds = (lo, hi)
        family, shared = kind, metadata
        offered[cid] = semantic; by_value[chosen] = cid
    if bounds is not None and set(by_value) != set(range(bounds[0], bounds[1]+1)):
        raise ValueError("X decision omits part of its offered range")
    return "announce_x" if bounds is not None else "choose_use", offered, by_value, bounds


def bound_view(start: dict, decision: dict) -> dict:
    return view(start, decision)[1]


def token_id(key: str) -> int:
    # These fixed keys contain only ASCII. Match the original Java hash and floorMod.
    result = 0
    for char in key:
        result = (31*result + ord(char)) & 0xffffffff
    if result >= 2**31:
        result -= 2**32
    return 1 + result % 65535


def f32(number):
    return struct.unpack("!f", struct.pack("!f", number))[0]


def validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    return _validate_encoding(start, decision, encoded, sources, request_hash, original_payment=False)


def validate_payment_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str):
    return _validate_encoding(start, decision, encoded, sources, request_hash, original_payment=True)


def _validate_encoding(start: dict, decision: dict, encoded: dict, sources: dict, request_hash: str, *, original_payment):
    keys = PAYMENT_SOURCE_KEYS if original_payment else SOURCE_KEYS
    if (not isinstance(sources, dict) or set(sources) != set(keys)
            or any(not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v) for v in sources.values())):
        raise ValueError("dialog frame needs every original staged source pin")
    callback, offered, by_value, bounds = view(start, decision)
    expected = {"schema":"spellbench-maintainer-dialog-features/v1", "callback":callback,
                "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
                "request_sha256":request_hash, "original_callback_sha256":CALLBACK_SHA256,
                "variant":DIALOG_PAYMENT_VARIANT if original_payment else DIALOG_VARIANT, **sources}
    if original_payment:
        expected["mana_payment_variant"] = MANA_PAYMENT_VARIANT
    if wire.canonical_json_dumps({key:encoded.get(key) for key in expected}) != wire.canonical_json_dumps(expected):
        raise ValueError("dialog frame differs from its original sources, game, decision or replay request")
    flags = encoded.get("world_flags")
    if (not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags)
            or any(flag.startswith(("unsupported:", "horizon:")) for flag in flags)):
        raise ValueError("dialog frame has unsupported reconstruction flags")
    count, values = encoded.get("candidate_count"), encoded.get("original_values")
    if type(count) is not int or not 1 <= count <= 64 or not isinstance(values, list) or len(values) != count:
        raise ValueError("dialog frame has an invalid original candidate count")
    if callback == "announce_x":
        lo, hi, actual_lo, actual_hi = (encoded.get(key) for key in (
            "real_minimum", "real_maximum", "original_minimum", "original_maximum"))
        mana = encoded.get("is_mana_pay")
        if (any(type(number) is not int for number in (lo, hi, actual_lo, actual_hi))
                or type(mana) is not bool or not -2**31 <= actual_hi <= MAX_INT
                or actual_lo != bounds[0] or lo != actual_lo or not lo <= hi <= bounds[1]
                or bounds[1] > max(actual_lo, actual_hi)
                or hi > max(lo, min(20, actual_hi))
                or not mana and hi != max(lo, min(20, actual_hi))
                or any(type(number) is not int for number in values) or values != list(range(lo, hi+1))):
            raise ValueError("dialog frame changed the original X cap, bounds or integer order")
    elif any(type(chosen) is not bool for chosen in values):
        raise ValueError("original binary choices must be booleans")
    if encoded.get("kind") == "maintainer-dialog-forced":
        chosen, cid = encoded.get("forced_value"), encoded.get("forced_candidate_id")
        reason = "original_x_single_value" if callback == "announce_x" else "original_mana_feasibility_gate"
        expected_type = int if callback == "announce_x" else bool
        if (count != 1 or type(chosen) is not expected_type or values != [chosen]
                or encoded.get("reason") != reason or type(cid) is not int or by_value.get(chosen) != cid):
            raise ValueError("forced dialog differs from the original callback's direct return")
        return None, {0:cid}
    if callback == "choose_use" and values != [True, False]:
        raise ValueError("dialog frame changed the original YES then NO order")
    if count < 2:
        raise ValueError("a single original dialog return must bypass inference")
    validate_features(encoded)
    if encoded["head"] != "action" or encoded["candidate_mask"] != [True]*count + [False]*(64-count):
        raise ValueError("dialog frame changed the original head or candidate mask")
    for index in range(64):
        row, ident = encoded["candidate_features"][index], encoded["candidate_ids"][index]
        if index >= count:
            if ident != 0 or any(row):
                raise ValueError("dialog padding differs from the original fixed slots")
            continue
        chosen = values[index]
        key = "ANNOUNCE_X:" + str(chosen) if callback == "announce_x" else "CHOOSE_USE_" + ("YES" if chosen else "NO")
        if ident != token_id(key) or row[0] != (15/16 if callback == "announce_x" else 12/16):
            raise ValueError("dialog candidate token or original action-type feature differs")
        if callback == "choose_use":
            if row[1] != (0 if chosen else 1) or row[26] != (1 if chosen else 0):
                raise ValueError("binary candidate features changed the original YES/NO meaning")
        elif row[10] != f32(min(chosen, 20)/20) or not 0 <= row[13] <= 1 or not 0 <= row[14] <= 1:
            raise ValueError("X candidate features changed the original magnitude or budget range")
    refs = encoded.get("candidate_refs")
    if not isinstance(refs, list):
        raise ValueError("dialog needs its offered action bindings")
    bound, used = {}, set()
    for ref in refs:
        index, cid, chosen = (ref.get(key) for key in ("index", "candidate_id", "value"))
        expected_type = int if callback == "announce_x" else bool
        if (type(index) is not int or not 0 <= index < count or index in bound or type(cid) is not int or cid in used
                or type(chosen) is not expected_type or chosen != values[index] or by_value.get(chosen) != cid):
            raise ValueError("original dialog slot is unbound, repeated or not offered")
        bound[index] = cid; used.add(cid)
    if set(bound) != set(range(count)):
        raise ValueError("original dialog slots have incomplete offered bindings")
    features = {key:encoded[key] for key in ("kind", "head", "sequence", "padding", "token_ids", "candidate_features",
                                           "candidate_ids", "candidate_mask")}
    return features, bound


class DialogSession(ModeSession):
    """Own the original dialog encoder, paired model and one chooser history."""
    SOURCE_KEYS = SOURCE_KEYS
    ENCODER = "maintainer-permitted-dialog"
    VARIANT = DIALOG_VARIANT
    bound_view = staticmethod(bound_view)
    validate_encoding = staticmethod(validate_encoding)


class PaymentDialogSession(DialogSession):
    """Pin the original payment rules throughout original binary/X replay."""
    SOURCE_KEYS = PAYMENT_SOURCE_KEYS
    ENCODER = "maintainer-permitted-dialog-payment"
    VARIANT = DIALOG_PAYMENT_VARIANT
    validate_encoding = staticmethod(validate_payment_encoding)
