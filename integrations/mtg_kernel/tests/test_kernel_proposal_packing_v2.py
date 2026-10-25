"""The counted packing lengths and tuple interning keys equal their canonical-JSON definitions."""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))
from kernel_engine_v2 import intern_proposal_vectors, pack_proposal_tensor
from spellbench import wire
from spellbench.errors import ValidationError

POOL = [0, 1, -1, 7, 1065353216, -2147483648, wire.MAX_JSON_INT, -wire.MAX_JSON_INT, 12345678901]


def reference_pack(tensor):
    """The original definition: the shorter canonical encoding, the plain list on a tie."""
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


def reference_intern(proposals, grouped):
    """The original definition, keyed by canonical bytes."""
    vectors, keys, indices, indexed = [], [], {}, []
    for trajectory in proposals:
        steps = []
        for position, step in enumerate(trajectory):
            tensor = {}
            for key, words in step["tensor"].items():
                encoded = wire.canonical_json_dumps(words)
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


def words(rng):
    n = rng.choice([0, 1, 2, 3, 5, 17, 64, 300])
    pool = POOL[:3] if rng.random() < 0.5 else POOL
    if rng.random() < 0.1:
        pool = pool + [True, False]
    return [rng.choice(pool) for _ in range(n)]


@pytest.mark.parametrize("seed", range(4))
def test_packing_and_interning_keep_the_canonical_bytes(seed):
    rng = random.Random(seed)
    for _ in range(400):
        tensor = {f"k{i}": words(rng) for i in range(rng.randint(1, 6))}
        assert wire.canonical_json_dumps(pack_proposal_tensor(tensor)) == wire.canonical_json_dumps(reference_pack(tensor))
        proposals = [[{"tensor": pack_proposal_tensor({f"k{i}": words(rng) if rng.random() < 0.5 else [0, 0, 1]
                                                       for i in range(3)}), "selected_row": 0}
                      for _ in range(rng.randint(1, 4))] for _ in range(rng.randint(1, 4))]
        for grouped in (False, True):
            assert (wire.canonical_json_dumps(intern_proposal_vectors(proposals, grouped))
                    == wire.canonical_json_dumps(reference_intern(proposals, grouped)))


@pytest.mark.parametrize("values", [[wire.MAX_JSON_INT + 1], [1.5]])
def test_non_canonical_words_still_fail_as_before(values):
    with pytest.raises(ValidationError):
        reference_pack({"k": values})
    with pytest.raises(ValidationError):
        pack_proposal_tensor({"k": values})
