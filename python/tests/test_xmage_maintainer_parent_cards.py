"""Inherited choices retain exact card bindings, completion and owned lifecycle."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_maintainer_parent_cards as parent
from xmage_maintainer_selection import GREEDY, MaintainerSelectionSession
from xmage_maintainer_sources import CALLBACK_SHA256, MANA_PAYMENT_VARIANT, parent_card_sources, stage
from xmage_neural_decisions import decision_hash
from test_xmage_maintainer_card_sets import fixture as card_fixture, SOURCES as CARD_SOURCES
from test_xmage_maintainer_inference import Peer
from test_xmage_maintainer_modes import Model

SOURCES = {**CARD_SOURCES, **{key:format(i+3, "x")*64 for i, key in enumerate(parent.PARENT_KEYS)}}


def setup(*, stop=False, finish=False, same=False, single=False, many=False,
          edit_decision=None, edit_frame=None, edit_ready=None):
    start, decision, anchor, replay, _, cards = card_fixture(stop=stop or finish, same=same, single=single, many=many)
    order = [None if not group else group[0] for group in cards["original_groups"]]
    ids = [group[0] for group in cards["public_group_ids"]]
    index = 0 if finish else len(order)-1
    encoded = {"schema":"spellbench-maintainer-parent-card-features/v1", "kind":"maintainer-parent-card-choice",
        "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
        "original_callback_sha256":CALLBACK_SHA256, "variant":parent.VARIANT, "mana_payment_variant":MANA_PAYMENT_VARIANT,
        "world_flags":[], "original_targets":order, "public_target_ids":ids,
        "chosen_index":index, "chosen_candidate_id":ids[index], "rule":"implicit_finish" if finish else "good_target",
        "selected_count":0, "minimum":cards["minimum"], "maximum":cards["maximum"], **SOURCES}
    ready = {"ready":True, "encoder":parent.ParentCardSession.ENCODER, "variant":parent.VARIANT,
        "mana_payment_variant":MANA_PAYMENT_VARIANT, "original_callback_sha256":CALLBACK_SHA256, "embedding_count":4, **SOURCES}
    if edit_decision: edit_decision(decision)
    encoded["request_sha256"] = decision_hash({"id":"1", "game_start":start, "decision":decision,
        "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    if edit_frame: edit_frame(encoded)
    if edit_ready: edit_ready(ready)
    peer = Peer([ready, {"id":"1", "ok":True, "encoded":encoded}])
    chooser = Peer([{"ready":True, "selection":"maintainer-original-no-training", "profile":GREEDY,
        "seed":7, "callback_source_sha256":CALLBACK_SHA256}])
    selector = MaintainerSelectionSession(chooser, profile=GREEDY, seed=7)
    model = Model(start); model.encoding["card_embeddings_sha256"] = SOURCES["embedding_cache_sha256"]
    try: owned = parent.ParentCardSession(peer, model, selector, game_start=start, sources=SOURCES)
    except BaseException:
        assert peer.closed and chooser.closed and model.closed == 1
        raise
    return owned, decision, anchor, replay, peer, model, chooser, encoded


def choose(values):
    owned, decision, anchor, replay = values[:4]
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


@pytest.mark.parametrize("options", [{}, {"same":True}, {"single":True}, {"stop":True}, {"finish":True}, {"many":True}])
def test_original_determined_choice_uses_no_model_or_selection_or_copy_stream(options):
    values = setup(**options)
    result = choose(values)
    cid = values[7]["chosen_candidate_id"]
    assert result["selection"] == {"candidate_id":cid, "semantic_echo":next(c["semantic"] for c in values[1]["candidates"] if c["candidate_id"] == cid)}
    assert result["scores"] is None and not values[5].requests and not values[6].writes
    assert values[0].selection.sequence == 0 and not hasattr(values[0], "copy_rng")
    assert all(0 < value <= 5 for value in values[4].timeouts)
    values[0].close(); assert values[4].closed and values[6].closed and values[5].closed == 1


def test_public_id_remapping_and_wire_reordering_preserve_original_choice():
    left, right = setup(same=True), setup(same=True)
    decision, encoded = right[1], right[7]
    decision["candidates"].reverse()
    for candidate in decision["candidates"]: candidate["candidate_id"] += 500
    encoded["public_target_ids"] = [cid+500 for cid in encoded["public_target_ids"]]
    encoded["chosen_candidate_id"] += 500; encoded["decision_sha256"] = decision_hash(decision)
    encoded["request_sha256"] = decision_hash({"id":"1", "game_start":right[0].start, "decision":decision,
        "anchor":right[2], "replay":right[3], "world_seed":"1"*64, "id_seed":"2"*64})
    right[4].rows[0] = json.dumps({"id":"1", "ok":True, "encoded":encoded}).encode()
    a, b = choose(left), choose(right)
    assert a["selection"]["semantic_echo"] == b["selection"]["semantic_echo"]
    assert a["selection"]["candidate_id"]+500 == b["selection"]["candidate_id"]
    left[0].close(); right[0].close()


def test_parent_range_is_original_not_capped_to_remaining_cards():
    values = setup(single=True)
    values[1]["candidates"][0]["semantic"].update(maximum=4096)
    frame = values[7]; frame.update(maximum=4096, decision_sha256=decision_hash(values[1]))
    assert parent.validate_encoding(values[0].start, values[1], frame, SOURCES, frame["request_sha256"])[1] == {0:100}


def test_sole_legal_implicit_finish_is_supported():
    values = setup(finish=True)
    values[1]["candidates"] = [values[1]["candidates"][-1]]
    frame = values[7]; frame.update(original_targets=[None], public_target_ids=[9], chosen_index=0, chosen_candidate_id=9,
                                   decision_sha256=decision_hash(values[1]))
    assert parent.validate_encoding(values[0].start, values[1], frame, SOURCES, frame["request_sha256"]) == (None, {0:9})


@pytest.mark.parametrize("edit", [
    lambda f:f.update(schema="spellbench-maintainer-card-set-features/v1"), lambda f:f.update(kind="candidates"),
    lambda f:f.update(variant="substituted"), lambda f:f.update(request_sha256="0"*64),
    lambda f:f.update(parent_selector_source_sha256="0"*64), lambda f:f.update(parent_comparator_source_sha256="0"*64),
    lambda f:f.update(parent_permanent_source_sha256="0"*64), lambda f:f.update(parent_scoring_source_sha256="0"*64),
    lambda f:f.update(parent_card_rules_source_sha256="0"*64), lambda f:f.update(card_set_rules_source_sha256="0"*64),
    lambda f:f.update(head="card_select"), lambda f:f.update(selected_count=True), lambda f:f.update(minimum=-1),
    lambda f:f.update(maximum=0), lambda f:f.update(maximum=4097), lambda f:f.update(rule="unknown"),
    lambda f:f.update(rule="implicit_finish"), lambda f:f.update(chosen_index=True), lambda f:f.update(chosen_index=2),
    lambda f:f.update(chosen_candidate_id=True), lambda f:f.update(chosen_candidate_id=101),
    lambda f:f["original_targets"].reverse(), lambda f:f["public_target_ids"].reverse(),
    lambda f:f["public_target_ids"].__setitem__(0, True), lambda f:f["original_targets"].pop(),
    lambda f:f.update(world_flags=["unsupported:library"]), lambda f:f.update(world_flags=["horizon:replay"]),
])
def test_bad_parent_frame_closes_all_owners_before_any_neural_or_rng_draw(edit):
    values = setup(edit_frame=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes and values[0].selection.sequence == 0
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("edit", [
    lambda d:d["candidates"][0]["semantic"].update(kind="choose_cost_target"),
    lambda d:d["candidates"][0]["semantic"].update(choice={"player":"p0"}),
    lambda d:d["candidates"][0]["semantic"]["choice"]["object"].update(object_id="hidden"),
    lambda d:d["candidates"][0].update(candidate_id=True),
])
def test_invalid_parent_wire_never_reaches_encoder(edit):
    values = setup(edit_decision=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[4].writes and not values[5].requests and not values[6].writes


@pytest.mark.parametrize("edit", [lambda r:r.update(encoder="maintainer-permitted-card-set"),
                                 lambda r:r.update(parent_card_rules_source_sha256="0"*64)])
def test_parent_startup_requires_its_own_original_source_identity(edit):
    with pytest.raises(ValueError): setup(edit_ready=edit)


def test_parent_extraction_requires_all_exact_original_sources():
    with pytest.raises(ValueError, match="every exact April"): parent_card_sources({})


@pytest.mark.parametrize("flag", [1, "yes", [], {}])
def test_parent_source_flag_requires_explicit_boolean(flag, tmp_path):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{"parent_card_callback":flag}}}
    with pytest.raises(ValueError, match="explicit boolean"): stage(manifest, tmp_path, tmp_path/"output")


def test_parent_source_flag_requires_original_neural_prefix(tmp_path):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{"parent_card_callback":True}}}
    with pytest.raises(ValueError, match="neural card"): stage(manifest, tmp_path, tmp_path/"output")
