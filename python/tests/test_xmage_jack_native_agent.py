"""Check the original lifecycle without launching XMage or loading weights."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_native_agent as agent
from spellbench import wire
from spellbench.bot import GameStart
from xmage_jack_native_inference import PROFILES
from test_xmage_neural_agent import decision, game, view

CHECKPOINT = "jack-elves-pair"


class Session:
    def __init__(self, start, indices=(), pass_after=False):
        self.start = copy.deepcopy(start)
        self.checkpoint, self.profile, self.seed = CHECKPOINT, PROFILES[0], start["agent_seed"]
        self.indices, self.pass_after = iter(indices), pass_after
        self.requests, self.results, self.closed = [], [], False

    def choose(self, record, *, timeout_s):
        self.requests.append((copy.deepcopy(record), timeout_s))
        candidate = record["decision"]["candidates"][next(self.indices)]
        result = {"decision_sha256": agent.digest(record["decision"]),
                  "game_start_sha256": agent.digest(self.start), "profile": self.profile, "seed": self.seed,
                  "full_original_player_qualified": False, "inference_requests": 1, "world_flags": [],
                  "selection": {"candidate_id": candidate["candidate_id"], "semantic_echo": candidate["semantic"]},
                  "priority_pass_after_activation": self.pass_after,
                  "original_priority_state": {"alternatives": [{"source": {
                      "object_id": "spell", "card_name": "Test spell", "zone": "hand"},
                      "choices": ["alternate"]}]}}
        self.results.append(result)
        return result

    def close(self):
        self.closed = True


def ready(indices=(0,), **options):
    sessions = []
    def factory(start):
        session = Session(start, indices, **options)
        sessions.append(session)
        return session
    bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
    bot.on_game_start(GameStart.from_request(game()))
    return bot, sessions[0]


def priority(step=0):
    return decision({"kind": "pass"}, {"kind": "cast_spell", "source": {"object_id": "spell"}}, step=step)


def binary(step=1):
    return decision({"kind": "choose_boolean", "value": False},
                    {"kind": "choose_boolean", "value": True}, step=step)


def amount(step=2):
    return decision({"kind": "choose_number", "purpose": "x_value", "value": 0},
                    {"kind": "choose_number", "purpose": "x_value", "value": 1}, step=step)


def test_public_protocol_always_enters_original_mulligan_and_forced_callback_then_closes():
    sessions = []
    def factory(start):
        sessions.append(Session(start, [0, 1, 0]))
        return sessions[-1]
    bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
    public = bot.public_session(name="original-player", version="pinned")
    def exchange(value):
        return json.loads(public.handle_line(wire.canonical_json_dumps(value)))
    hello = exchange({"protocol": "spellbench/v2", "request_id": "hello", "request_type": "hello"})
    assert hello["requires"]["observation"] == ["passed_seats", "keywords"]
    assert exchange(game())["response_type"] == "ack"
    mulligan = decision({"kind": "mulligan", "keep": False}, {"kind": "mulligan", "keep": True}, phase="pregame")
    assert exchange(view(mulligan).raw)["selection"]["candidate_id"] == 10
    assert exchange(view(priority(1)).raw)["selection"]["candidate_id"] == 11
    forced = binary(2); forced["candidates"] = forced["candidates"][:1]
    assert exchange(view(forced).raw)["selection"]["candidate_id"] == 10
    assert len(sessions[0].requests) == 3
    assert exchange({"protocol": "spellbench/v2", "request_id": "end", "request_type": "game_over",
                     "game_id": "opaque", "terminal": {}})["response_type"] == "ack"
    assert sessions[0].closed and bot.game is None
    assert exchange(game())["response_type"] == "ack" and len(sessions) == 2
    bot.close()


def test_callback_chain_retains_actual_priority_state_seeds_and_exact_prefix():
    bot, session = ready([1, 1, 0, 0])
    bot.choose(view(priority()))
    bot.choose(view(binary()))
    bot.choose(view(amount()))
    root, first, second = [entry[0] for entry in session.requests]
    assert first["anchor"]["original_priority_state"] == session.results[0]["original_priority_state"]
    assert first["anchor"]["priority_pass_after_activation"] is False
    assert first["replay"]["earlier"] == [] and first["replay"]["priority_passes"] == []
    assert second["replay"]["earlier"][0]["selection"]["semantic_echo"] == {"kind": "choose_boolean", "value": True}
    assert (root["world_seed"], root["id_seed"]) == (first["world_seed"], first["id_seed"]) == (
        second["world_seed"], second["id_seed"])
    assert root["decision"]["seat_step"] == 0 and second["decision"]["seat_step"] == 2
    bot.choose(view(priority(3)))
    fresh = session.requests[-1][0]
    assert "anchor" not in fresh and fresh["world_seed"] != root["world_seed"]
    assert bot.history.anchor["decision"]["seat_step"] == 3 and bot.history.earlier == []
    bot.close()


@pytest.mark.parametrize("shape", ["multiple", "singleton", "exhausted", "optional-finish"])
def test_modes_use_original_session_and_join_binary_x_replay_prefix(shape):
    bot, session = ready([1, 0, 1, 0])
    bot.choose(view(priority()))
    source = {"object_id": "spell"}
    option = {"kind": "choose_spell_mode", "source": source, "mode_index": 0,
              "mode_count": 2, "selected_count": 0, "minimum": 1, "maximum": 1}
    finish = {"kind": "finish_selection", "source": source, "purpose": "modes", "selected_count": 0}
    semantics = [option]
    if shape == "multiple": semantics.append({**option, "mode_index": 1})
    if shape == "exhausted": semantics = [finish]
    if shape == "optional-finish": semantics.append(finish)
    received = decision(*semantics, step=1)
    bot.choose(view(received))
    bot.choose(view(binary(2)))
    bot.choose(view(amount(3)))
    root, mode, binary_record, x = [row[0] for row in session.requests]
    assert agent.family(mode["decision"]) == "mode"
    assert mode["replay"]["earlier"] == []
    assert binary_record["replay"]["earlier"][0]["selection"]["semantic_echo"] == semantics[0]
    assert len(x["replay"]["earlier"]) == 2
    assert all((r["world_seed"], r["id_seed"]) == (root["world_seed"], root["id_seed"])
               for r in (mode, binary_record, x))
    bot.close()


@pytest.mark.parametrize("semantic", [{"kind": "finish_selection", "purpose": "cards"},
                                     {"kind": "choose_boolean", "value": True}])
def test_mixed_mode_families_refuse_before_original_session(semantic):
    bot, session = ready([1])
    bot.choose(view(priority()))
    received = decision({"kind": "choose_spell_mode", "mode_index": 0}, semantic, step=1)
    with pytest.raises(ValueError, match="family is not connected"):
        bot.choose(view(received))
    assert session.closed and len(session.requests) == 1


def test_caller_result_and_audit_mutations_cannot_change_saved_priority_state():
    bot, session = ready([1, 0])
    bot.audit = lambda event: event.update(selection={"candidate_id": 999})
    received = priority()
    bot.choose(view(received))
    session.results[0]["original_priority_state"]["alternatives"].clear()
    session.results[0]["selection"]["semantic_echo"].clear()
    received["observation"]["phase_step"] = "postcombat_main"
    bot.choose(view(binary()))
    saved = session.requests[-1][0]["anchor"]
    assert saved["original_priority_state"]["alternatives"][0]["choices"] == ["alternate"]
    assert saved["selection"]["semantic_echo"]["kind"] == "cast_spell"
    bot.close()


def test_opaque_ids_clocks_and_injected_private_fields_do_not_change_original_record():
    records = []
    for opaque, milliseconds in (("one", 1500), ("two", 3000)):
        sessions = []
        def factory(start):
            sessions.append(Session(start, [0]))
            return sessions[-1]
        bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
        start = game(opaque); start["hidden_engine_state"] = {"library_order": "forbidden"}
        bot.on_game_start(GameStart.from_request(start))
        received = priority()
        received.update(hidden_engine_state="forbidden", x_history={"card_origins": "spoofed"},
                        x_observation_flags={"opponent_hand": True})
        bot.choose(view(received, game_id=opaque, clock={"remaining_ms": milliseconds,
                                                       "max_decision_ms": milliseconds}))
        records.append(sessions[0].requests[0][0]); bot.close()
    assert records[0] == records[1]
    assert records[0]["decision"]["x_history"] == {"loyalty_used": [], "card_origins": {}}
    assert "hidden_engine_state" not in records[0]["decision"] and "hidden_engine_state" not in records[0]["game_start"]


@pytest.mark.parametrize("change", ["rewind", "viewer", "game", "step", "clock", "unsupported", "no-anchor"])
def test_invalid_or_unconnected_choice_closes_without_entering_original_session(change):
    bot, session = ready()
    received, kwargs = priority(), {}
    if change == "rewind": received["context"]["rewind"] = True
    if change == "viewer": received["observation"]["viewer"] = "p1"
    if change == "game": kwargs["game_id"] = "foreign"
    if change == "step": received["seat_step"] = True
    if change == "clock": kwargs["clock"] = {"remaining_ms": 0, "max_decision_ms": 1000}
    if change == "unsupported": received = decision({"kind": "choose_key", "key": "a"})
    if change == "no-anchor": received = binary(0)
    with pytest.raises(ValueError): bot.choose(view(received, **kwargs))
    assert bot.failed and session.closed and not session.requests


@pytest.mark.parametrize("change", ["turn", "phase", "stale", "skipped"])
def test_changed_callback_cannot_replay_another_activation(change):
    bot, session = ready([1])
    bot.choose(view(priority()))
    received = binary()
    if change == "turn": received["observation"]["turn"] = 2
    if change == "phase": received["observation"]["phase_step"] = "combat"
    if change == "stale": received["seat_step"] = 0
    if change == "skipped": received["seat_step"] = 2
    with pytest.raises(ValueError): bot.choose(view(received))
    assert session.closed and len(session.requests) == 1


def test_pass_after_activation_is_retained_and_unconnected_continuation_refuses():
    bot, session = ready([1, 0], pass_after=True)
    bot.choose(view(priority()))
    bot.choose(view(binary()))
    assert session.requests[-1][0]["anchor"]["priority_pass_after_activation"] is True
    with pytest.raises(ValueError, match="continuation is not connected"):
        bot.choose(view(priority(2)))
    assert session.closed and len(session.requests) == 2


@pytest.mark.parametrize("field,value", [("checkpoint", "foreign"), ("profile", PROFILES[1]),
                                         ("seed", True), ("start", {"seat": "p1"})])
def test_factory_identity_failure_closes_the_created_session(field, value):
    sessions = []
    def factory(start):
        session = Session(start)
        setattr(session, field, value); sessions.append(session)
        return session
    bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
    with pytest.raises(ValueError, match="session differs"):
        bot.on_game_start(GameStart.from_request(game()))
    assert bot.failed and sessions[0].closed


def test_shared_frontend_clock_expires_before_history_can_accept_a_late_result(monkeypatch):
    bot, session = ready()
    clock = [0.0]; monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])
    choose = session.choose
    def delayed(record, **options):
        assert options["timeout_s"] == pytest.approx(1.9)
        result = choose(record, **options); clock[0] = 2.0
        return result
    session.choose = delayed
    with pytest.raises(TimeoutError): bot.choose(view(priority()))
    assert bot.failed and session.closed and bot.history.anchor is None and bot.step is None


@pytest.mark.parametrize("field,value", [("decision_sha256", "0" * 64), ("seed", True),
    ("priority_pass_after_activation", 1), ("original_priority_state", {"alternatives": "bad"}),
    ("selection", {"candidate_id": 999, "semantic_echo": {}})])
def test_invalid_original_receipt_cannot_be_saved(field, value):
    bot, session = ready()
    choose = session.choose
    def malformed(record, **options):
        result = choose(record, **options); result[field] = value
        return result
    session.choose = malformed
    with pytest.raises(ValueError): bot.choose(view(priority()))
    assert session.closed and bot.history.anchor is None


def test_original_error_survives_failed_cleanup():
    bot, session = ready()
    def cleanup(): raise RuntimeError("close failed")
    session.close = cleanup
    with pytest.raises(ValueError, match="rewound") as failure:
        received = priority(); received["context"]["rewind"] = True
        bot.choose(view(received))
    assert "cleanup also failed" in failure.value.__notes__[0]


def test_frontend_and_native_supervisor_share_one_actual_owner_through_callback_chain(tmp_path, monkeypatch):
    from test_xmage_jack_inference import fixture, Peer
    from test_xmage_jack_backend import IMAGE
    from test_xmage_jack_native_inference import packet
    from xmage_jack_native_inference import JackNativeInferenceOwner
    from xmage_jack_native_session import JackNativeSession, SCHEMA, CALLBACK_SHA256

    manifest, context, inference_ready, cleanup = fixture(tmp_path, monkeypatch)
    pair = Peer([inference_ready])
    owned = []
    class ServingPeer(Peer):
        def write_line(self, data):
            super().write_line(data)
            command = json.loads(data)
            if command.get("operation") != "decide":
                return
            record = command
            selection_index = 0 if "anchor" in record else 1
            candidate = record["decision"]["candidates"][selection_index]
            result = {"game_start_sha256": owner.start_sha256,
                      "decision_sha256": agent.digest(record["decision"]), "profile": owner.profile,
                      "seed": owner.seed, "inference_requests": 1, "full_original_player_qualified": False,
                      "world_flags": [], "selection": {"candidate_id": candidate["candidate_id"],
                                                         "semantic_echo": candidate["semantic"]},
                      "priority_pass_after_activation": False, "original_priority_state": {"alternatives": []}}
            if "anchor" in record:
                result.update(original_activation_path=True,
                              original_dialog_prefix_replayed=len(record["replay"]["earlier"]))
            self.rows.extend([json.dumps(packet(owner, "physical_copy", id=owner.sequence + 1, count=1)).encode(),
                json.dumps({"schema": SCHEMA, "id": command["id"], "operation": "decide",
                            "event": "result", "ok": True, "result": result}).encode()])

    def factory(start):
        nonlocal owner
        owner = JackNativeInferenceOwner(manifest, tmp_path, "policy", IMAGE, game_start=start,
            profile=PROFILES[0], seed=start["agent_seed"], peer_factory=lambda *a, **k: pair)
        peer = ServingPeer([{"schema": SCHEMA, "ready": True, "callback_sha256": CALLBACK_SHA256,
            "profile": owner.profile, "seed": owner.seed, "game_start_sha256": owner.start_sha256,
            "operations": ["decide"]}])
        owned.append((owner, peer))
        return JackNativeSession(peer, owner)

    owner = None
    bot = agent.JackNativeAgent(factory, checkpoint="policy", profile=PROFILES[0])
    start = game(); start["own_deck"] = context["own_deck"]
    bot.on_game_start(GameStart.from_request(start))
    assert [bot.choose(view(value)) for value in (priority(), binary(), amount())] == [11, 10, 10]
    assert len(owned) == 1 and owner.sequence == 3 and owner.copy_draws == 0
    commands = [c for c in owned[0][1].writes if c.get("operation") == "decide"]
    assert [c["id"] for c in commands] == ["1", "2", "3"]
    assert commands[-1]["replay"]["earlier"][0]["selection"]["semantic_echo"] == {
        "kind": "choose_boolean", "value": False}
    bot.close()
    assert owner.closed and owned[0][1].closed and pair.closed and len(cleanup) == 1
