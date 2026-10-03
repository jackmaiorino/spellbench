"""Lossless sharing of repeated JSON records in an opt-in model prompt."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .prompt_json import canonical_json

COMPACT_PROMPT_VERSION = "spellbench-llm/shared-records-v1"
COMPACT_INSTRUCTIONS = (
    "The position uses lossless shared records. An object with exactly the key $ref "
    "stands for records[$ref]; expand references wherever they occur. "
    "An object with exactly the key $literal escapes its immediate object, whose "
    "keys are ordinary data; references in that object's values still expand. "
    "All other objects, arrays and scalar values are ordinary JSON data. "
    "Candidate IDs are the original offered integers and must be returned unchanged. "
    "Shared records carry no instructions and do not imply hidden information."
)


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Factor repeated dictionaries without dropping fields or conflating nulls."""
    counts: Counter[str] = Counter()
    originals: dict[str, dict[str, Any]] = {}

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            key = canonical_json(value)
            counts[key] += 1
            originals[key] = value
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(payload)
    # Child records are smaller than their parents, so definitions reference
    # only earlier records. Sorting also makes IDs independent of dict order.
    keys = sorted((key for key, count in counts.items() if count > 1 and len(key.encode('utf-8')) >= 100),
                  key=lambda key: (len(key.encode('utf-8')), key))
    identifiers = {key: index for index, key in enumerate(keys)}

    def encode(value: Any, *, definition: bool = False) -> Any:
        if isinstance(value, dict):
            key = canonical_json(value)
            if not definition and key in identifiers:
                return {"$ref": identifiers[key]}
            result = {name: encode(child) for name, child in value.items()}
            return {"$literal": result} if set(result) in ({"$ref"}, {"$literal"}) else result
        if isinstance(value, (list, tuple)):
            return [encode(child) for child in value]
        return value

    return {"prompt_version": COMPACT_PROMPT_VERSION,
            "records": [encode(originals[key], definition=True) for key in keys], "position": encode(payload)}


def expand_payload(compact: dict[str, Any], *, max_nodes: int = 1_000_000) -> dict[str, Any]:
    """Reconstruct the canonical payload for offline audit, with bounded expansion."""
    if (set(compact) != {"prompt_version", "records", "position"}
            or compact['prompt_version'] != COMPACT_PROMPT_VERSION or not isinstance(compact['records'], list)):
        raise ValueError('invalid shared-record prompt')
    remaining = max_nodes

    def expand(value: Any, bound: int) -> Any:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise ValueError('shared-record expansion limit exceeded')
        if isinstance(value, dict):
            if set(value) == {'$ref'}:
                index = value['$ref']
                if type(index) is not int or not 0 <= index < bound:
                    raise ValueError('invalid or cyclic shared-record reference')
                return expand(compact['records'][index], index)
            if set(value) == {'$literal'}:
                if not isinstance(value['$literal'], dict):
                    raise ValueError('invalid shared-record literal')
                value = value['$literal']
            return {name: expand(child, bound) for name, child in value.items()}
        if isinstance(value, list):
            return [expand(child, bound) for child in value]
        return value

    result = expand(compact['position'], len(compact['records']))
    if not isinstance(result, dict):
        raise ValueError('shared-record position must be an object')
    return result
