"""A smaller opt-in prompt encoding of the same player-visible view.

Three rewrites, each stated to the model in ``LEAN_INSTRUCTIONS``: object fields
holding null, false, an empty list or an empty object are omitted; each card
name's most common characteristics and full name are given once under
``card_defaults`` and referenced as ``"default"``; and object IDs become short per-game aliases.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, MutableMapping

from .prompt_json import canonical_json

LEAN_PROMPT_VERSION = "spellbench-llm/lean-v1"
LEAN_INSTRUCTIONS = (
    "The position uses a lean encoding. An omitted object field means null, false, an empty list or an "
    "empty object. An object whose characteristics is the string \"default\" has the characteristics and "
    "full_name of card_defaults[card_name]. Object IDs are short aliases such as o12; within one game the same "
    "alias always names the same object."
)
_SHARED = ("characteristics", "full_name")


def _empty(value: Any) -> bool:
    return value is None or value is False or (isinstance(value, (list, dict)) and not value)


def _card(value: dict[str, Any]) -> bool:
    return isinstance(value.get("card_name"), str) and "characteristics" in value


def lean_payload(payload: dict[str, Any], aliases: MutableMapping[str, str]) -> dict[str, Any]:
    """Rewrite ``payload``; ``aliases`` persists across a game's decisions so aliases stay stable."""

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            object_id = value.get("object_id")
            if isinstance(object_id, str) and object_id not in aliases:
                aliases[object_id] = f"o{len(aliases) + 1}"
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    def alias(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: alias(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [alias(child) for child in value]
        # Any string equal to a known object ID is that ID, including references such as attached_to.
        return aliases.get(value, value) if isinstance(value, str) else value

    def shared(value: dict[str, Any]) -> str:
        return canonical_json({key: value.get(key) for key in _SHARED})

    counts: dict[str, Counter[str]] = {}

    def count(value: Any) -> None:
        if isinstance(value, dict):
            if _card(value):
                counts.setdefault(value["card_name"], Counter())[shared(value)] += 1
            for child in value.values():
                count(child)
        elif isinstance(value, list):
            for child in value:
                count(child)

    collect(payload)
    aliased = alias(payload)
    count(aliased)
    # Ties go to the canonically smaller encoding, so the choice is deterministic.
    defaults = {name: min(counter, key=lambda key: (-counter[key], key)) for name, counter in counts.items()}

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            own: dict[str, Any] = {}
            if _card(value):
                if defaults[value["card_name"]] == shared(value):
                    value = {key: child for key, child in value.items() if key != "full_name"}
                    own = {"characteristics": "default"}
                else:
                    # An object's own values stay explicit, even null, so they never fall back to the defaults.
                    own = {key: strip(value.get(key)) for key in _SHARED}
            result = {key: strip(child) for key, child in value.items() if key not in own}
            return {**{key: child for key, child in result.items() if not _empty(child)}, **own}
        if isinstance(value, list):
            return [strip(child) for child in value]
        return value

    body = strip(aliased)
    body["card_defaults"] = {name: strip(json.loads(defaults[name])) for name in sorted(defaults)}
    return body
