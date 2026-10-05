"""Check game binding, shared clocks and ownership of the original-player peer."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_native_session as serving
from spellbench.errors import ValidationError
from xmage_jack_native_inference import JackNativeInferenceOwner, PROFILES
from test_xmage_jack_backend import IMAGE
from test_xmage_jack_inference import Peer, fixture
from test_xmage_jack_native_inference import packet


def setup(tmp_path, monkeypatch, *, scores=None):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    game.update(seat="p0", agent_seed=31)
    pair = Peer([ready, *(scores or [])])
    owner = JackNativeInferenceOwner(manifest, tmp_path, "policy", IMAGE, game_start=game,
        profile=PROFILES[0], seed=31, peer_factory=lambda *a, **k: pair)
    peer = Peer([])
    ready = {"schema": serving.SCHEMA, "ready": True, "callback_sha256": serving.CALLBACK_SHA256,
             "profile": owner.profile, "seed": owner.seed, "game_start_sha256": owner.start_sha256,
             "operations": ["decide"]}
    peer.rows = [json.dumps(ready).encode()]
    session = serving.JackNativeSession(peer, owner, startup_s=2)
    record = {"game_start": copy.deepcopy(game), "decision": {"acting_seat": "p0",
        "observation": {"viewer": "p0"}, "candidates": [
            {"candidate_id": 7, "semantic": {"kind": "mulligan", "keep": True}},
            {"candidate_id": 8, "semantic": {"kind": "mulligan", "keep": False}}]},
        "world_seed": "a" * 64, "id_seed": "b" * 64}
    return session, record, peer, pair, cleanup


def result(session, record, *, calls=0, rid="1"):
    message = {"schema": serving.SCHEMA, "id": rid, "operation": "decide", "event": "result", "ok": True,
            "result": {"decision_sha256": serving.digest(record["decision"]),
                "game_start_sha256": session.start_sha256, "profile": session.profile, "seed": session.seed,
                "inference_requests": calls, "full_original_player_qualified": False, "world_flags": [],
                "selection": {"candidate_id": 7, "semantic_echo": record["decision"]["candidates"][0]["semantic"]}}}
    if "anchor" in record:
        message["result"].update(original_activation_path=True,
                                 original_dialog_prefix_replayed=len(record["replay"]["earlier"]))
        if record["decision"].get("context", {}).get("kind") == "priority":
            message["result"].update(original_priority_continuation=True,original_activation_pass_deferred=False,
                priority_pass_after_activation=False,original_priority_state={"alternatives": [], "targets": []})
        if record["anchor"]["selection"]["semantic_echo"].get("kind") == "pass":
            message["result"].update(original_resolution_path=True, original_activation_path=False,
                                     original_priority_passes_replayed=len(record["replay"]["priority_passes"]))
    return message


def rows(peer, *messages):
    peer.rows.extend(json.dumps(message).encode() if isinstance(message, dict) else message for message in messages)


def test_shared_original_owner_and_increasing_decisions(tmp_path, monkeypatch):
    scores = {"id": "1", "probabilities": [0.25, 0.75] + [0] * 62, "value": 0}
    session, record, peer, pair, cleanup = setup(tmp_path, monkeypatch, scores=[scores])
    score = packet(session.owner)
    physical = packet(session.owner, "physical_copy", id=2, count=3)
    expected = result(session, record, calls=2)
    rows(peer, score, physical, expected)
    assert session.choose(record, timeout_s=2) == expected["result"]
    assert peer.writes[0]["id"] == "1" and peer.writes[0]["operation"] == "decide"
    assert peer.writes[1]["id"] == 1 and peer.writes[2]["id"] == 2
    assert session.owner.copy_draws == 1 and len(pair.writes) == 1
    rows(peer, result(session, record, rid="2"))
    assert session.choose(record, timeout_s=2)["selection"]["candidate_id"] == 7
    assert peer.writes[-1]["id"] == "2" and session.owner.sequence == 2
    session.close(); session.close()
    assert peer.closed and pair.closed and len(cleanup) == 1
    assert session.cleanup == {"close_called": True, "jvm_close_succeeded": True,
                               "inference_close_succeeded": True, "jvm_process_absent": None}
    with pytest.raises(ValueError, match="closed"):
        session.choose(record, timeout_s=2)


@pytest.mark.parametrize("field,value", [
    ("id", "2"), ("operation", "train"), ("event", "infer"), ("schema", "foreign"), ("ok", False),
])
def test_wrong_result_envelope_releases_peer_and_pair(tmp_path, monkeypatch, field, value):
    session, record, peer, pair, cleanup = setup(tmp_path, monkeypatch)
    message = result(session, record); message[field] = value; rows(peer, message)
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert peer.closed and pair.closed and len(cleanup) == 1 and session.failed


@pytest.mark.parametrize("field,value", [
    ("decision_sha256", "0" * 64), ("game_start_sha256", "0" * 64), ("seed", True),
    ("seed", 32), ("profile", PROFILES[1]), ("inference_requests", 1), ("inference_requests", False),
    ("full_original_player_qualified", True), ("world_flags", ["unsupported:hidden"]),
    ("selection", {"candidate_id": 99, "semantic_echo": {}}),
    ("selection", {"candidate_id": True, "semantic_echo": {}}),
    ("selection", {"candidate_id": 7, "semantic_echo": {"kind": "mulligan", "keep": False}}),
])
def test_wrong_identity_or_choice_cannot_escape_to_wire(tmp_path, monkeypatch, field, value):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    message = result(session, record); message["result"][field] = value; rows(peer, message)
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert peer.closed and pair.closed


@pytest.mark.parametrize("change", ["game", "viewer", "seed", "candidate", "reserved", "float"])
def test_invalid_public_request_refuses_before_jvm_write(tmp_path, monkeypatch, change):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    if change == "game": record["game_start"]["agent_seed"] += 1
    if change == "viewer": record["decision"]["observation"]["viewer"] = "p1"
    if change == "seed": record["world_seed"] = "0"
    if change == "candidate": record["decision"]["candidates"][1]["candidate_id"] = 7
    if change == "reserved": record["id"] = "foreign"
    if change == "float": record["decision"]["candidates"][0]["semantic"]["fraction"] = 0.5
    with pytest.raises((ValueError, TypeError, ValidationError)): session.choose(record, timeout_s=2)
    assert not peer.writes and peer.closed and pair.closed


def test_remaining_outer_clock_caps_every_native_request(tmp_path, monkeypatch):
    scores = {"id": "1", "probabilities": [0.25, 0.75] + [0] * 62, "value": 0}
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch, scores=[scores])
    clock = [0.0]; monkeypatch.setattr(serving.time, "monotonic", lambda: clock[0])
    read = peer.read_line
    def delayed_read():
        clock[0] += 0.4
        return read()
    peer.read_line = delayed_read
    captured = []; score = session.owner.session.score
    def delayed_score(features, *, timeout_s):
        captured.append(timeout_s); clock[0] += 0.5
        return score(features, timeout_s=timeout_s)
    session.owner.session.score = delayed_score
    rows(peer, packet(session.owner, remaining_s=100), result(session, record, calls=1))
    assert session.choose(record, timeout_s=2)["inference_requests"] == 1
    assert captured == [pytest.approx(1.6)] and peer.timeouts[-1] <= 1.1 + 1e-9
    session.close()


@pytest.mark.parametrize("problem", ["elapsed", "eof", "duplicate", "close", "stale-inference"])
def test_timeout_and_broken_stream_close_both_owners(tmp_path, monkeypatch, problem):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    if problem == "elapsed":
        clock = [0.0]; monkeypatch.setattr(serving.time, "monotonic", lambda: clock[0])
        message = result(session, record)
        def too_late():
            clock[0] = 3
            return json.dumps(message).encode()
        peer.read_line = too_late
    elif problem == "duplicate": rows(peer, b'{"schema":1,"schema":2}')
    elif problem == "close": rows(peer, packet(session.owner, "close"))
    elif problem == "stale-inference": rows(peer, packet(session.owner, "physical_copy", id=2, count=1))
    with pytest.raises((ValueError, TimeoutError, IndexError)): session.choose(record, timeout_s=2)
    assert peer.closed and pair.closed and session.owner.closed


def test_cleanup_keeps_original_error_and_attempts_both_closes(tmp_path, monkeypatch):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    message = result(session, record); message["id"] = "stale"; rows(peer, message)
    called = []
    def bad_jvm(): called.append("jvm"); raise RuntimeError("JVM close failed")
    close_owner = session.owner.close
    def bad_model():
        called.append("inference"); close_owner(); raise RuntimeError("model close failed")
    peer.close, session.owner.close = bad_jvm, bad_model
    with pytest.raises(ValueError, match="stale") as caught: session.choose(record, timeout_s=2)
    assert called == ["jvm", "inference"] and pair.closed
    assert "cleanup also failed" in caught.value.__notes__[0]
    assert session.cleanup["jvm_close_succeeded"] is False and session.cleanup["inference_close_succeeded"] is False


def test_readiness_requires_exact_boolean_and_closes_owned_resources(tmp_path, monkeypatch):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    game.update(seat="p0", agent_seed=31)
    pair = Peer([ready])
    owner = JackNativeInferenceOwner(manifest, tmp_path, "policy", IMAGE, game_start=game,
        profile=PROFILES[0], seed=31, peer_factory=lambda *a, **k: pair)
    ready = {"schema": serving.SCHEMA, "ready": 1, "callback_sha256": serving.CALLBACK_SHA256,
        "profile": owner.profile, "seed": owner.seed, "game_start_sha256": owner.start_sha256,
        "operations": ["decide"]}
    peer = Peer([ready])
    with pytest.raises(ValueError, match="readiness"):
        serving.JackNativeSession(peer, owner, startup_s=2)
    assert peer.closed and pair.closed and owner.closed and len(cleanup) == 1


def test_unconfirmed_jvm_exit_is_a_cleanup_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    session, _, peer, pair, _ = setup(tmp_path, monkeypatch)
    peer._proc = SimpleNamespace(poll=lambda: None)
    with pytest.raises(RuntimeError, match="remains running"):
        session.close()
    assert pair.closed and session.owner.closed
    assert session.cleanup["jvm_process_absent"] is False and session.cleanup["jvm_close_succeeded"] is False


def test_owner_cannot_change_the_declared_chooser_seed(tmp_path, monkeypatch):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    game.update(seat="p0", agent_seed=31)
    pair = Peer([ready])
    owner = JackNativeInferenceOwner(manifest, tmp_path, "policy", IMAGE, game_start=game,
        profile=PROFILES[0], seed=32, peer_factory=lambda *a, **k: pair)
    peer = Peer([])
    with pytest.raises(ValueError, match="declared game seed"):
        serving.JackNativeSession(peer, owner, startup_s=2)
    assert peer.closed and pair.closed and owner.closed and len(cleanup) == 1


def callback_record(record):
    root = {"acting_seat": "p0", "seat_step": 0, "context": {"kind": "priority"},
            "observation": {"viewer": "p0", "turn": 1, "phase_step": "precombat_main"},
            "candidates": [{"candidate_id": 1, "semantic": {"kind": "cast_spell"}}]}
    record["anchor"] = {"decision": root, "selection": {"candidate_id": 1,
        "semantic_echo": {"kind": "cast_spell"}}, "priority_pass_after_activation": True,
        "original_priority_state": {"alternatives": [], "targets": []}}
    record["replay"] = {"priority_passes": [], "earlier": []}
    record["decision"].update(seat_step=1, context={"kind": "choice"})
    record["decision"]["observation"].update(turn=1, phase_step="precombat_main")
    for candidate, value in zip(record["decision"]["candidates"], (False, True)):
        candidate["semantic"] = {"kind": "choose_boolean", "value": value}
    return record


def queued_record(record):
    callback_record(record)
    refs = [{"object_id": "q" + str(i), "card_name": "Forest" if i == 1 else "Island",
             "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"} for i in (1, 2)]
    record["anchor"]["decision"]["observation"]["players"] = [{"seat": "p0", "hand": copy.deepcopy(refs)}]
    record["anchor"]["original_priority_state"]["targets"] = [copy.deepcopy(refs[i]) for i in (1, 0, 1)]
    return record


def priority_record(record):
    callback_record(record);record["decision"]["context"]["kind"] = "priority"
    record["decision"]["candidates"][0]["semantic"] = {"kind": "pass"}
    record["decision"]["candidates"][1]["semantic"] = {"kind": "cast_spell"}
    return record


def resolution_record(record, *, already=False, priority=False):
    (priority_record if priority else callback_record)(record)
    root = record["anchor"]["decision"]; root["candidates"][0]["semantic"] = {"kind": "pass"}
    record["anchor"].update(selection={"candidate_id": 1, "semantic_echo": {"kind": "pass"}}, priority_pass_after_activation=False)
    root["observation"].update(stack=[{"card_name": "Visible spell"}], passed_seats=["p1"] if already else [])
    record["replay"]["priority_passes"] = [] if already else ["p1"]
    return record


@pytest.mark.parametrize("already", [False, True])
@pytest.mark.parametrize("priority", [False, True])
def test_private_serving_resolution_preserves_recorded_passes(tmp_path, monkeypatch, already, priority):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch); resolution_record(record, already=already, priority=priority)
    rows(peer, result(session, record)); chosen = session.choose(record, timeout_s=2)
    assert chosen["original_resolution_path"] and not chosen["original_activation_path"]
    assert chosen["original_priority_passes_replayed"] == (0 if already else 1)
    assert peer.writes[0]["replay"]["priority_passes"] == ([] if already else ["p1"])
    session.close(); assert peer.closed and pair.closed


@pytest.mark.parametrize("fault", ["missing-pass", "extra-pass", "empty-stack", "own-passed", "duplicate-passed", "phase"])
def test_private_serving_resolution_refuses_unrecorded_transition_before_write(tmp_path, monkeypatch, fault):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch); resolution_record(record)
    obs = record["anchor"]["decision"]["observation"]
    if fault == "missing-pass": record["replay"]["priority_passes"] = []
    if fault == "extra-pass": record["replay"]["priority_passes"].append("p1")
    if fault == "empty-stack": obs["stack"] = []
    if fault == "own-passed": obs["passed_seats"] = ["p0"]
    if fault == "duplicate-passed": obs["passed_seats"] = ["p1", "p1"]
    if fault == "phase": record["decision"]["observation"]["phase_step"] = "postcombat_main"
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert not peer.writes and peer.closed and pair.closed


@pytest.mark.parametrize("field,value", [("original_resolution_path", False), ("original_activation_path", True),
                                        ("original_priority_passes_replayed", 0), ("original_priority_passes_replayed", True)])
def test_private_serving_resolution_rejects_missing_path_or_wrong_pass_count(tmp_path, monkeypatch, field, value):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch); resolution_record(record)
    message = result(session, record); message["result"][field] = value;rows(peer, message)
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert peer.closed and pair.closed


def test_private_serving_accepts_original_zero_draw_priority_continuation(tmp_path, monkeypatch):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch);priority_record(record)
    rows(peer,result(session,record));chosen=session.choose(record,timeout_s=2)
    assert chosen["original_priority_continuation"] and chosen["inference_requests"] == 0
    assert peer.writes[0]["anchor"] == record["anchor"]
    session.close();assert peer.closed and pair.closed


@pytest.mark.parametrize("fault", ["continuation", "deferred", "choice", "prefix"])
def test_private_serving_refuses_missing_completion_or_substituted_pass(tmp_path,monkeypatch,fault):
    session,record,peer,pair,_=setup(tmp_path,monkeypatch);priority_record(record);message=result(session,record)
    if fault=="continuation":message["result"]["original_priority_continuation"]=False
    if fault=="deferred":message["result"]["original_activation_pass_deferred"]=1
    if fault=="prefix":message["result"]["original_dialog_prefix_replayed"]=1
    if fault=="choice":message["result"]["selection"]={"candidate_id":8,"semantic_echo":{"kind":"cast_spell"}}
    rows(peer,message)
    with pytest.raises(ValueError):session.choose(record,timeout_s=2)
    assert peer.closed and pair.closed


def test_complete_target_queue_preserves_order_and_duplicate_refs_in_transport(tmp_path, monkeypatch):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    queued_record(record)
    rows(peer, result(session, record))
    session.choose(record, timeout_s=2)
    assert [ref["object_id"] for ref in peer.writes[0]["anchor"]["original_priority_state"]["targets"]] == ["q2", "q1", "q2"]
    session.close(); assert peer.closed and pair.closed


@pytest.mark.parametrize("fault", ["missing", "shape", "hidden", "name", "owner", "oversized"])
def test_unbound_target_queue_refuses_before_any_jvm_write(tmp_path, monkeypatch, fault):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    queued_record(record)
    state = record["anchor"]["original_priority_state"]
    if fault == "missing": state.pop("targets")
    if fault == "shape": state["targets"] = {}
    if fault == "hidden": state["targets"][0]["object_id"] = "private"
    if fault == "name": state["targets"][0]["card_name"] = "different name"
    if fault == "owner": state["targets"][0]["controller_seat"] = "p1"
    if fault == "oversized": state["targets"] *= 1366
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert not peer.writes and peer.closed and pair.closed


@pytest.mark.parametrize("queue", [None, [{"object_id": "hidden"}], [None] * 4097])
def test_priority_result_cannot_supply_an_unbound_target_queue(tmp_path, monkeypatch, queue):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    record["decision"]["context"] = {"kind": "priority"}
    message = result(session, record)
    message["result"].update(priority_pass_after_activation=False,
                             original_priority_state={"alternatives": [], "targets": queue})
    rows(peer, message)
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert peer.closed and pair.closed


def test_native_session_transports_callback_anchor_state_and_earlier_selection(tmp_path, monkeypatch):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    callback_record(record)
    previous = copy.deepcopy(record["decision"])
    record["replay"]["earlier"].append({"decision": previous,
        "selection": {"candidate_id": 8, "semantic_echo": {"kind": "choose_boolean", "value": True}}})
    record["decision"]["seat_step"] = 2
    rows(peer, result(session, record))
    assert session.choose(record, timeout_s=2)["selection"]["candidate_id"] == 7
    assert peer.writes[0]["anchor"] == record["anchor"] and peer.writes[0]["replay"] == record["replay"]
    session.close(); assert peer.closed and pair.closed


@pytest.mark.parametrize("change", ["state", "pass", "viewer", "selection", "step", "missing", "foreign", "prefix"])
def test_invalid_native_callback_replay_refuses_before_jvm_write(tmp_path, monkeypatch, change):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    callback_record(record)
    if change == "state": record["anchor"]["original_priority_state"] = {"alternatives": "bad"}
    if change == "pass": record["replay"]["priority_passes"] = ["p1"]
    if change == "viewer": record["anchor"]["decision"]["observation"]["viewer"] = "p1"
    if change == "selection": record["anchor"]["selection"]["semantic_echo"] = {"kind": "pass"}
    if change == "step": record["decision"]["seat_step"] = 2
    if change == "missing": del record["anchor"]["priority_pass_after_activation"]
    if change == "foreign": record["anchor"]["private"] = True
    if change == "prefix": record["replay"]["earlier"] = [{"decision": copy.deepcopy(record["decision"])}]
    with pytest.raises(ValueError): session.choose(record, timeout_s=2)
    assert not peer.writes and peer.closed and pair.closed


@pytest.mark.parametrize("field,value", [("original_activation_path", 1),
    ("original_dialog_prefix_replayed", True), ("original_dialog_prefix_replayed", 1)])
def test_callback_receipt_cannot_hide_a_missing_original_activation_or_prefix(tmp_path, monkeypatch, field, value):
    session, record, peer, pair, _ = setup(tmp_path, monkeypatch)
    callback_record(record)
    message = result(session, record); message["result"][field] = value; rows(peer, message)
    with pytest.raises(ValueError, match="activation or replay prefix"):
        session.choose(record, timeout_s=2)
    assert peer.closed and pair.closed
