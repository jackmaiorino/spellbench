"""Original card groups keep their head, copy bindings, seeded stream and refusal scope."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_maintainer_card_sets as cards
from xmage_maintainer_selection import GREEDY, MaintainerSelectionSession
from xmage_maintainer_sources import CALLBACK_SHA256, MANA_PAYMENT_VARIANT, card_set_source, stage
from xmage_neural_decisions import decision_hash
from test_xmage_maintainer_inference import Peer
from test_xmage_maintainer_modes import fixture as mode_fixture, Model
from test_xmage_maintainer_targets import SOURCES as TARGET_SOURCES

SOURCES = {**TARGET_SOURCES, "card_set_rules_source_sha256":"2"*64}


def fixture(*, stop=False, same=False, single=False, deduplicated=False, many=False):
    start, decision, anchor, replay, _, encoded = mode_fixture()
    count = 70 if many else 1 if single else 2
    refs = [{"object_id":f"copy-{i}", "card_name":"Forest" if same else f"Card {i}",
             "controller_seat":"p0", "owner_seat":"p0", "zone":"hand"} for i in range(count)]
    decision["observation"]["players"][0]["hand"] = copy.deepcopy(refs)
    decision["candidates"] = [{"candidate_id":i+100, "semantic":{"kind":"select_object", "purpose":"cards",
        "source":decision["context"]["source"], "selected_count":0, "minimum":0 if stop else 1,
        "maximum":1, "choice":{"object":copy.deepcopy(ref)}}} for i, ref in enumerate(refs)]
    ordered = [{"object":copy.deepcopy(ref)} for ref in reversed(refs)]
    groups = [ordered] if same and deduplicated else [[ref] for ref in ordered]
    ids = [[100+i for i in reversed(range(count))]] if same and deduplicated else [[100+i] for i in reversed(range(count))]
    if stop:
        decision["candidates"].append({"candidate_id":9, "semantic":{"kind":"finish_selection", "purpose":"cards",
            "source":decision["context"]["source"], "selected_count":0}})
        groups.insert(0, []); ids.insert(0, [9])
    slots = min(64, len(groups))
    for name in ("available_count", "original_mode_indices"): encoded.pop(name)
    encoded.update(schema="spellbench-maintainer-card-set-features/v1", head="card_select", variant=cards.VARIANT,
        mana_payment_variant=MANA_PAYMENT_VARIANT, group_count=len(groups), candidate_count=slots,
        original_groups=groups, public_group_ids=ids, deduplicated=deduplicated, selected_count=0,
        minimum=0 if stop else 1, maximum=1, decision_sha256=decision_hash(decision), **SOURCES)
    encoded["candidate_refs"] = [{"index":i, "candidate_ids":ids[i], "cards":groups[i]} for i in range(slots)]
    encoded["candidate_features"] = [[i+0.25]+[0]*47 if i < slots else [0]*48 for i in range(64)]
    encoded["candidate_ids"] = [i+70 if i < slots else 0 for i in range(64)]
    encoded["candidate_mask"] = [True]*slots+[False]*(64-slots)
    if len(groups) == 1: encoded.update(kind="maintainer-card-set-forced", forced_group_index=0)
    ready = {"ready":True, "encoder":cards.CardSetSession.ENCODER, "variant":cards.VARIANT,
        "mana_payment_variant":MANA_PAYMENT_VARIANT, "original_callback_sha256":CALLBACK_SHA256, "embedding_count":4, **SOURCES}
    return start, decision, anchor, replay, ready, encoded


def setup(*, edit_decision=None, edit_frame=None, edit_ready=None, chosen=0, **kwargs):
    start, decision, anchor, replay, ready, encoded = fixture(**kwargs)
    if edit_decision: edit_decision(decision)
    encoded["request_sha256"] = decision_hash({"id":"1", "game_start":start, "decision":decision,
        "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    if edit_frame: edit_frame(encoded)
    if edit_ready: edit_ready(ready)
    peer = Peer([ready, {"id":"1", "ok":True, "encoded":encoded}])
    chooser = Peer([{"ready":True, "selection":"maintainer-original-no-training", "profile":GREEDY,
        "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":[chosen]}])
    selector = MaintainerSelectionSession(chooser, profile=GREEDY, seed=7)
    model = Model(start); model.encoding["card_embeddings_sha256"] = SOURCES["embedding_cache_sha256"]
    count = encoded["candidate_count"]; model.scores["probabilities"] = [1/count]*count+[0]*(64-count)
    try: owned = cards.CardSetSession(peer, model, selector, game_start=start, sources=SOURCES)
    except BaseException:
        assert peer.closed and chooser.closed and model.closed == 1
        raise
    return owned, decision, anchor, replay, peer, model, chooser, encoded


def choose(values):
    owned, decision, anchor, replay = values[:4]
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


def test_distinct_card_groups_use_original_head_and_features_and_shared_clock():
    values = setup(chosen=1)
    result = choose(values)
    assert result["selection"] == {"candidate_id":100, "semantic_echo":values[1]["candidates"][0]["semantic"]}
    features, timeout = values[5].requests[0]
    assert features["head"] == "card_select" and features["candidate_features"] == values[7]["candidate_features"]
    assert values[0].copy_draws == 0 and values[0].selection.sequence == 1
    assert 0 < values[6].timeouts[0] <= timeout <= values[4].timeouts[0] <= 5
    values[0].close(); assert values[4].closed and values[6].closed and values[5].closed == 1


def test_single_card_bypasses_both_inference_and_all_selection_streams():
    values = setup(single=True)
    assert choose(values)["selection"]["candidate_id"] == 100
    assert not values[5].requests and not values[6].writes
    assert values[0].copy_draws == values[0].selection.sequence == 0
    values[0].close()


def test_duplicate_name_group_uses_reproducible_copy_stream_and_bypasses_neural_rng():
    left, right = setup(same=True, deduplicated=True), setup(same=True, deduplicated=True)
    first, second = choose(left), choose(right)
    assert first == second and first["selection"]["candidate_id"] in (100, 101)
    for values in (left, right):
        assert values[0].copy_draws == 1 and values[0].selection.sequence == 0
        assert not values[5].requests and not values[6].writes
        values[0].close()


def test_same_named_unmerged_cards_still_require_original_neural_selection():
    values = setup(same=True)
    assert choose(values)["selection"]["candidate_id"] == 101
    assert len(values[5].requests) == values[0].selection.sequence == 1
    assert values[0].copy_draws == 0
    values[0].close()


def test_optional_duplicate_name_group_preserves_scored_stop_in_first_slot():
    values = setup(same=True, deduplicated=True, stop=True)
    assert choose(values)["selection"]["semantic_echo"]["kind"] == "finish_selection"
    assert values[5].requests[0][0]["original_groups"][0] == []
    assert values[0].copy_draws == 0 and values[0].selection.sequence == 1
    values[0].close()


def test_card_groups_truncate_only_original_neural_slots_at_64():
    values = setup(many=True, chosen=63)
    assert choose(values)["selection"]["candidate_id"] == 106
    assert values[6].writes[0]["count"] == 64
    assert len(values[7]["original_groups"]) == 70 and len(values[5].requests[0][0]["candidate_refs"]) == 64
    values[0].close()


def test_public_ids_and_wire_order_do_not_change_copy_group_semantics_or_features():
    left, right = setup(same=True, deduplicated=True), setup(same=True, deduplicated=True)
    decision, encoded = right[1], right[7]
    decision["candidates"].reverse()
    for candidate in decision["candidates"]: candidate["candidate_id"] += 500
    encoded["public_group_ids"] = [[cid+500 for cid in group] for group in encoded["public_group_ids"]]
    for ref in encoded["candidate_refs"]: ref["candidate_ids"] = [cid+500 for cid in ref["candidate_ids"]]
    encoded["decision_sha256"] = decision_hash(decision)
    encoded["request_sha256"] = decision_hash({"id":"1", "game_start":right[0].start, "decision":decision,
        "anchor":right[2], "replay":right[3], "world_seed":"1"*64, "id_seed":"2"*64})
    right[4].rows[0] = json.dumps({"id":"1", "ok":True, "encoded":encoded}).encode()
    a, b = choose(left), choose(right)
    assert a["selection"]["semantic_echo"] == b["selection"]["semantic_echo"]
    assert a["selection"]["candidate_id"] + 500 == b["selection"]["candidate_id"]
    assert left[7]["candidate_features"] == right[7]["candidate_features"]
    left[0].close(); right[0].close()


@pytest.mark.parametrize("edit", [
    lambda d:d["candidates"][0]["semantic"].update(kind="choose_cost_target"),
    lambda d:d["candidates"][0]["semantic"].update(purpose=True),
    lambda d:d["candidates"][0]["semantic"].update(choice={"player":"p0"}),
    lambda d:d["candidates"][0]["semantic"].update(target={"object":{}}),
    lambda d:d["candidates"][0]["semantic"]["choice"]["object"].update(object_id="hidden"),
    lambda d:d["candidates"][0]["semantic"]["choice"]["object"].update(card_name="Hidden"),
    lambda d:d["candidates"][0].update(candidate_id=True),
])
def test_invalid_card_wire_refuses_before_encoder_or_either_rng(edit):
    values = setup(edit_decision=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[4].writes and not values[5].requests and not values[6].writes
    assert values[0].copy_draws == 0
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("edit", [
    lambda f:f.update(schema="spellbench-maintainer-general-target-features/v1"),
    lambda f:f.update(variant="unseeded"), lambda f:f.update(request_sha256="0"*64),
    lambda f:f.update(card_set_rules_source_sha256="0"*64), lambda f:f.update(head="target"),
    lambda f:f.update(group_count=True), lambda f:f.update(deduplicated=1),
    lambda f:f.update(selected_count=True), lambda f:f.update(minimum=-1),
    lambda f:f.update(maximum=3), lambda f:f.update(kind="maintainer-card-set-forced"),
    lambda f:f["original_groups"].reverse(), lambda f:f["public_group_ids"][0].append(100),
    lambda f:f["public_group_ids"][0].__setitem__(0, True),
    lambda f:f["public_group_ids"][0].__setitem__(0, 100),
    lambda f:f["candidate_refs"][0].update(index=True), lambda f:f["candidate_refs"][0].update(candidate_ids=[100]),
    lambda f:f["candidate_refs"][0].update(cards=[]),
    lambda f:f["candidate_ids"].__setitem__(2, 1),
    lambda f:f["candidate_features"][2].__setitem__(0, 1),
    lambda f:f.update(world_flags=["unsupported:library"]),
])
def test_invalid_card_frame_refuses_before_model_and_both_rngs(edit):
    values = setup(edit_frame=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes and values[0].copy_draws == 0
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("edit", [
    lambda f:f["public_group_ids"][0].reverse(),
    lambda f:f.update(deduplicated=False),
    lambda f:f["original_groups"][0][0]["object"].update(card_name="Different"),
    lambda f:f.update(forced_group_index=True), lambda f:f.update(forced_group_index=1),
])
def test_bad_forced_copy_group_cannot_bypass_validation(edit):
    values = setup(same=True, deduplicated=True, edit_frame=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes and values[0].copy_draws == 0


@pytest.mark.parametrize("edit", [lambda r:r.update(encoder="maintainer-permitted-general-target"),
                                 lambda r:r.update(card_set_rules_source_sha256="0"*64)])
def test_card_pipe_requires_its_own_ready_identity(edit):
    with pytest.raises(ValueError): setup(edit_ready=edit)


def test_card_extraction_refuses_unpinned_original_source():
    with pytest.raises(ValueError, match="pinned April"): card_set_source("unreviewed callback")


@pytest.mark.parametrize("flag", [1, "yes", [], {}])
def test_card_source_flag_requires_an_explicit_boolean(flag, tmp_path):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{"card_set_callback":flag}}}
    with pytest.raises(ValueError, match="explicit boolean"): stage(manifest, tmp_path, tmp_path/"output")
    assert not (tmp_path/"output").exists()


def test_card_source_flag_requires_original_prefix_rules(tmp_path):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{"card_set_callback":True}}}
    with pytest.raises(ValueError, match="general target"): stage(manifest, tmp_path, tmp_path/"output")


def test_copy_stream_initialization_failure_closes_every_existing_owner(monkeypatch):
    def refused_seed(*args): raise ValueError("copy stream initialization failed")
    monkeypatch.setattr(cards.random, "Random", refused_seed)
    with pytest.raises(ValueError, match="initialization failed"): setup()
