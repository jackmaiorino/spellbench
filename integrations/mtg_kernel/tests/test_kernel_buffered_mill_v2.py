"""Synthetic private mill contract, with no native process or game execution.

The native MillLibraryBatch grants its owner temporary prefix knowledge before
the move. A private preview clones that pending choice, then completes exactly
its declared target set. These views exercise the adapter as one combined path.
"""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import zlib

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_engine_v2 import FLAT, KernelEngine, pack_proposal_tensor
from kernel_flat_bot import TENSOR_KEYS
from kernel_observation_v2 import KernelProjection, ProjectionError, legacy_id, normalized_zones
from spellbench import wire
from test_kernel_observation_v2 import card, catalog, raw, stack


class MillPeer:
    """Model only the bridge's fixed mill choice and clone-preview contract."""

    def __init__(self, count):
        self.count = count
        self.committed = []
        self.preview_prefixes = []
        self.cards = [card(arena=100 + i, zone="Library") for i in range(count)]
        self.source = card(arena=19, zone="Battlefield")
        self.root = self.view([])

    def view(self, prefix):
        value = raw()
        value["own_hand"] = []
        value["projection"]["hand_counts"][0] = 0
        value["projection"]["library_counts"][0] = self.count
        value["projection"]["battlefield"][0] = [self.source]
        value["known_library_cards"][0] = [
            {"card": item, "position": index} for index, item in enumerate(self.cards)]
        effect = {"source": self.source["stable"], "choice": {
            "choice_kind": "targets", "min_targets": self.count, "max_targets": self.count,
            "selected_targets": [{"target_kind": "object", "object": self.cards[i]["stable"]} for i in prefix],
            "legal_targets": [{"target_kind": "object", "object": item["stable"]}
                              for i, item in enumerate(self.cards) if i not in prefix]}}
        value["projection"]["engine_context"]["pending_effect"] = effect
        # Normal pending-effect choices retain their resolving item on the stack.
        item = stack(self.source["stable"])
        value["projection"]["stack"] = [item]
        remaining = [i for i in range(self.count) if i not in prefix]
        candidates = [{"candidate_id": index, "semantic": {
            "kind": "choose_effect_target", "target": {"object": {
                "object_id": legacy_id(normalized_zones(self.cards[i]["stable"]))}}}}
            for index, i in enumerate(remaining)]
        # Exercise the row map: rows are deliberately in reverse candidate order.
        tensor = {key: [] for key in TENSOR_KEYS}
        tensor.update(state=[0x80000000, 0x7FC00001, 0xFFFFFFFF, len(prefix)] + [0] * 128,
                      object_card_ids=[-1] + remaining, action_features=[0] * len(remaining))
        return {"game_id": "synthetic-mill", "response_type": "decision", "step": len(prefix),
                "candidates": candidates, "extensions": {
                    "x_kernel_v5": {"observation_json": json.dumps(value)},
                    "x_kernel_v2_support": {"stack_instances": ["91"], "effect_instance": "91:1",
                        "resolving_stack_instance": "91",
                        "choice": {"purpose": "mill", "stage": "graveyard_order"}},
                    FLAT: {"card_db_hash": "000000000000007b", "feature_contract_digest": "a" * 64,
                           "feature_encoding_digest": "b" * 64,
                           "row_candidate_ids": list(reversed(range(len(remaining)))), "tensor": tensor}}}

    def advance(self, prefix, candidate):
        remaining = [i for i in range(self.count) if i not in prefix]
        assert 0 <= candidate < len(remaining)
        return prefix + [remaining[candidate]]

    def request(self, request):
        assert request["game_id"] == "synthetic-mill"
        if request["request_type"] == "preview_steps":
            assert request["expected_step"] == 0
            prefix = []
            for candidate in request["candidate_ids"]:
                prefix = self.advance(prefix, candidate)
            self.preview_prefixes.append(tuple(prefix))
            assert len(prefix) <= self.count
            if len(prefix) == self.count:
                return {"response_type": "private_complete"}
            return {"response_type": "private_preview", "view": self.view(prefix)}
        assert request["request_type"] == "step"
        assert request["expected_step"] == len(self.committed)
        view = self.view(self.committed)
        selection = request["selection"]
        assert selection["semantic_echo"] == view["candidates"][selection["candidate_id"]]["semantic"]
        self.committed = self.advance(self.committed, selection["candidate_id"])
        if len(self.committed) == self.count:
            return {"response_type": "terminal", "winner": None, "outcome": "draw", "reason": "game_over"}
        return self.view(self.committed)


def engine_for(peer):
    engine = KernelEngine.__new__(KernelEngine)
    engine.peer = peer
    engine.game = "synthetic-mill"
    engine.current = deepcopy(peer.root)
    engine.projection = KernelProjection(catalog(), b"s" * 32)
    engine.buffer = None
    engine.answered = engine.completed = 0
    engine.seat_steps = {"p0": 0, "p1": 0}
    engine.group_ids = {"p0": 0, "p1": 0}
    engine.rules = {"extensions": [FLAT]}
    engine.provenance = {}
    return engine


def unpack(extension):
    decoded = zlib.decompress(base64.b64decode(extension["proposals_zlib"]))
    assert len(decoded) <= 64 * 1024 * 1024
    assert len(wire.canonical_json_dumps(extension)) <= wire.MAX_LINE_BYTES - 262144
    table = json.loads(decoded)
    return [[{"selected_row": step["selected_row"],
              "tensor": {key: table["vectors"][ref["vector"]] for key, ref in step["tensor"].items()}}
             for step in proposal] for proposal in table["proposals"]]


def test_whole_library_mill_projects_previews_and_commits_without_changing_root():
    peer = MillPeer(60)
    engine = engine_for(peer)
    root = deepcopy(peer.root)
    answer = engine.pose("first")
    sd = answer["seat_decision"]
    assert sd["group"]["substep_count"] == 59
    assert len(sd["observation"]["known"]) == 60
    assert sd["observation"]["players"][1]["hand"] is None
    proposals = unpack(sd["extensions"][FLAT])
    assert len(proposals) == len(sd["candidates"]) == 60
    assert engine.current == engine.root == peer.root == root
    assert peer.committed == []
    # Each neutral candidate gets a complete deterministic native trajectory.
    for candidate, proposal in zip(sd["candidates"], proposals):
        first_object = candidate["semantic"]["item"]["object"]["object_id"]
        native_object = engine.arrangement_cards[first_object]
        first_id = next(i for i, item in enumerate(peer.cards)
                        if legacy_id(normalized_zones(item["stable"])) == native_object)
        neutral_order = [first_object] + [c["object_id"] for c in sorted(engine.buffer.cards,
                          key=lambda c: (c["card_name"], c["object_id"])) if c["object_id"] != first_object]
        assert len(proposal) == 60
        prefix = []
        for neutral, step in zip(neutral_order, proposal):
            view = peer.view(prefix)
            wanted = engine.arrangement_cards[neutral]
            selected = next(c["candidate_id"] for c in view["candidates"]
                            if c["semantic"]["target"]["object"]["object_id"] == wanted)
            flat = view["extensions"][FLAT]
            assert step == {"tensor": pack_proposal_tensor(flat["tensor"]),
                            "selected_row": flat["row_candidate_ids"].index(selected)}
            prefix = peer.advance(prefix, selected)
        assert prefix[0] == first_id
        assert sorted(prefix) == list(range(60))
    # Take a non-first pick, complete the neutral plan, then commit its exact order.
    engine.buffer.choose(59)
    continuation = engine.pose("second")["seat_decision"]
    assert len(continuation["candidates"]) == 59
    assert continuation["group"]["substep_index"] == 1
    assert len(unpack(continuation["extensions"][FLAT])) == 59
    assert engine.current == engine.root == peer.root == root and peer.committed == []
    while len(engine.buffer.order) < engine.buffer.count - 1:
        engine.buffer.choose(0)
    expected = [engine.arrangement_cards[obj] for obj in engine.buffer.result()["graveyard"]]
    engine.commit_buffer()
    assert [legacy_id(normalized_zones(peer.cards[i]["stable"])) for i in peer.committed] == expected
    assert peer.root == root
    assert engine.current["response_type"] == "terminal"


@pytest.mark.parametrize("invalid", ["knowledge", "effect"])
def test_mill_projection_rejects_unlicensed_library_objects_before_preview(invalid):
    peer = MillPeer(3)
    engine = engine_for(peer)
    support = engine.current["extensions"]["x_kernel_v2_support"]
    if invalid == "knowledge":
        value = json.loads(engine.current["extensions"]["x_kernel_v5"]["observation_json"])
        value["known_library_cards"][0] = []
        engine.current["extensions"]["x_kernel_v5"]["observation_json"] = json.dumps(value)
    else:
        support.pop("effect_instance")
    with pytest.raises(ProjectionError, match="actor-visible position|private effect instance"):
        engine.pose("invalid")
    assert peer.preview_prefixes == [] and peer.committed == []


def test_preview_from_another_effect_cannot_supply_completion_proposals():
    peer = MillPeer(3)
    engine = engine_for(peer)
    original_request = peer.request

    def wrong_effect(request):
        answer = original_request(request)
        if answer["response_type"] == "private_preview":
            answer["view"]["extensions"]["x_kernel_v2_support"]["effect_instance"] = "other:effect"
        return answer

    peer.request = wrong_effect
    with pytest.raises(ValueError, match="another game or effect"):
        engine.pose("invalid-preview")
    assert peer.committed == [] and engine.current == peer.root
