"""Verify the public lifecycle, history and clock before full-game qualification."""
import copy
import hmac
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_agent as agent
from spellbench import wire
from spellbench.agent_messages import Clock
from spellbench.bot import Decision, GameOver, GameStart
from xmage_neural_decisions import decision_hash
from test_xmage_neural_combat import fixture as combat_fixture, later_decision

CHECKPOINT = "draftzero-exp1-gen33"


def game(game_id="opaque", seat="p0", seed=12):
    return {"protocol": "spellbench/v2", "request_id": "start", "request_type": "game_start",
            "game_id": game_id, "seat": seat, "agent_seed": seed,
            "own_deck": {"decklist": [{"name": "Swamp", "count": 40}]},
            "opponent_deck": None, "rules": {"opponent_decklist": "hidden"},
            "engine_profile": {"observation": {"passed_seats": True, "keywords": True}}}


def decision(*semantics, step=0, phase="precombat_main", stack=None):
    return {"acting_seat": "p0", "seat_step": step,
            "context": {"kind": "priority" if all(s["kind"] in ("pass", "cast_spell", "play_land")
                                                  for s in semantics) else "choice", "rewind": False},
            "observation": {"viewer": "p0", "turn": 1, "phase_step": phase,
                            "passed_seats": [], "stack": stack or [], "players": []},
            "candidates": [{"candidate_id": 10 + i, "semantic": semantic} for i, semantic in enumerate(semantics)]}


def view(value, *, game_id="opaque", clock=None):
    return Decision.from_request({"protocol": "spellbench/v2", "request_id": "choose",
                                  "request_type": "choose", "game_id": game_id, "decision": value,
                                  "clock": clock or Clock(5000, 2000).to_json()})


class Session:
    def __init__(self, indices=(), checkpoint=CHECKPOINT):
        self.model = SimpleNamespace(checkpoint=checkpoint)
        self.indices = iter(indices)
        self.requests, self.closed = [], False

    def choose(self, record, *, visits, timeout_s):
        self.requests.append((copy.deepcopy(record), visits, timeout_s))
        candidate = record["decision"]["candidates"][next(self.indices)]
        return {"checkpoint": self.model.checkpoint, "neural_calls": 3,
                "selection": {"candidate_id": candidate["candidate_id"], "semantic_echo": candidate["semantic"]}}

    def plan(self, record, *, visits, timeout_s):
        self.requests.append((copy.deepcopy(record), visits, timeout_s))
        _, result = combat_fixture("attack")
        result.update(decision_sha256=decision_hash(record["decision"]), checkpoint=self.model.checkpoint)
        return result

    def close(self):
        self.closed = True


def ready(session=None, **kwargs):
    session = session or Session()
    bot = agent.NeuralAgent(lambda: session, checkpoint=CHECKPOINT, visits=2, **kwargs)
    bot.on_game_start(GameStart.from_request(game()))
    return bot, session


def test_protocol_hello_start_mulligan_choice_and_terminal_close_owned_session():
    session = Session([1])
    bot = agent.NeuralAgent(lambda: session, checkpoint=CHECKPOINT, visits=2)
    public = bot.public_session(name="test-model", version="pinned")
    def exchange(request):
        return json.loads(public.handle_line(wire.canonical_json_dumps(request)))
    hello = exchange({"protocol": "spellbench/v2", "request_id": "hello", "request_type": "hello"})
    assert hello["bot"] == {"name": "test-model", "version": "pinned"}
    assert hello["requires"]["observation"] == ["passed_seats", "keywords"]
    assert exchange(game())["response_type"] == "ack"
    mulligan = view(decision({"kind": "mulligan", "keep": False}, {"kind": "mulligan", "keep": True}, phase="pregame"))
    assert exchange(mulligan.raw)["selection"]["candidate_id"] == 11
    priority = view(decision({"kind": "pass"}, {"kind": "play_land"}, step=1))
    assert exchange(priority.raw)["selection"]["candidate_id"] == 11
    assert len(session.requests) == 1
    terminal = exchange({"protocol": "spellbench/v2", "request_id": "over", "request_type": "game_over",
                         "game_id": "opaque", "terminal": {}})
    assert terminal["response_type"] == "ack" and session.closed and bot.game is None


def test_seeds_match_java_hmac_and_ignore_opaque_ids_injected_history_and_clock():
    records = []
    for opaque, clock in (("first-game", 2000), ("second-game", 3000)):
        session = Session([0])
        bot = agent.NeuralAgent(lambda: session, checkpoint=CHECKPOINT, visits=2)
        start = game(opaque)
        start["hidden_engine_state"] = {"library_order": "forbidden"}
        bot.on_game_start(GameStart.from_request(start))
        received = decision({"kind": "pass"}, {"kind": "play_land"})
        received.update(x_history={"loyalty_used": ["spoofed"]}, x_observation_flags={"opponent_hand": True},
                        hidden_engine_state="forbidden")
        bot.choose(view(received, game_id=opaque, clock=Clock(clock, clock).to_json()))
        records.append(session.requests[0][0])
        bot.close()
    assert records[0] == records[1]
    record = records[0]
    key = hmac.digest((12).to_bytes(8, "big"), b"spellbench-xmage-kit/v1/game", "sha256")
    assert record["world_seed"] == hmac.digest(key, b"world:0:0", "sha256").hex()
    assert record["id_seed"] == hmac.digest(key, b"ids", "sha256").hex()
    assert record["decision"]["x_history"] == {"loyalty_used": [], "card_origins": {}}
    assert "hidden_engine_state" not in record["decision"] and "hidden_engine_state" not in record["game_start"]
    assert "game_id" not in record["game_start"]


@pytest.mark.parametrize("passed,expected", [([], ["p1"]), (["p1"], [])])
def test_resolution_replay_uses_latest_stack_anchor_and_public_passed_seats(passed, expected):
    bot, session = ready(Session([0, 1, 0]))
    stack = [{"object_id": "public-stack", "stack_kind": "triggered_ability"}]
    priority = decision({"kind": "pass"}, {"kind": "play_land"}, stack=stack)
    priority["observation"]["passed_seats"] = passed
    assert bot.choose(view(priority)) == 10
    binary = decision({"kind": "choose_boolean", "value": False}, {"kind": "choose_boolean", "value": True},
                      step=1, stack=stack)
    assert bot.choose(view(binary)) == 11
    target = decision({"kind": "select_object", "object": {"object_id": "known-land"}},
                      {"kind": "finish_selection"}, step=2, stack=stack)
    assert bot.choose(view(target)) == 10
    replay = session.requests[-1][0]
    assert replay["anchor"]["decision"]["seat_step"] == 0
    assert replay["replay"]["priority_passes"] == expected
    assert replay["replay"]["earlier"][0]["selection"]["semantic_echo"] == {"kind": "choose_boolean", "value": True}


def test_casting_callback_keeps_own_action_and_forced_prefix_then_priority_replaces_anchor():
    bot, session = ready(Session([1, 0, 0]))
    priority = decision({"kind": "pass"}, {"kind": "cast_spell", "source": {"object_id": "spell"}})
    bot.choose(view(priority))
    forced = decision({"kind": "choose_number", "value": 1}, step=1)
    assert bot.choose(view(forced)) == 10
    target = decision({"kind": "choose_target", "target": {"player": "p0"}},
                      {"kind": "choose_target", "target": {"player": "p1"}}, step=2)
    bot.choose(view(target))
    replay = session.requests[-1][0]
    assert replay["anchor"]["selection"]["semantic_echo"]["kind"] == "cast_spell"
    assert replay["replay"]["priority_passes"] == []
    assert len(replay["replay"]["earlier"]) == 1
    bot.choose(view(decision({"kind": "pass"}, {"kind": "play_land"}, step=3)))
    assert bot.history.anchor["decision"]["seat_step"] == 3 and bot.history.earlier == []
    assert len(session.requests) == 3


def cleanup_decisions():
    anchor = decision({"kind": "pass"}, phase="end_step")
    anchor["observation"].update(active_seat="p0", priority_seat="p0")
    callback = decision(*[
        {"kind": "select_object", "purpose": "discard", "minimum": 1, "maximum": 1,
         "selected_count": 0, "source": None,
         "choice": {"object": {"object_id": f"card-{i}", "card_name": "Swamp",
                                "zone": "hand", "owner_seat": "p0", "controller_seat": "p0"}}}
        for i in range(2)], step=1, phase="cleanup")
    callback["context"].update(purpose="discard", source=None)
    callback["observation"].update(active_seat="p0", priority_seat=None, passed_seats=["p0", "p1"])
    return anchor, callback


def test_cleanup_discard_replays_recorded_end_step_and_keeps_earlier_discard_choices():
    bot, session = ready(Session([0, 1]))
    anchor, callback = cleanup_decisions()
    assert bot.choose(view(anchor)) == 10
    assert bot.choose(view(callback)) == 10
    later = copy.deepcopy(callback)
    later["seat_step"] = 2
    assert bot.choose(view(later)) == 11
    first, second = [request[0] for request in session.requests]
    assert first["anchor"]["decision"]["observation"]["phase_step"] == "end_step"
    assert first["replay"] == {"priority_passes": ["p1"], "earlier": []}
    assert second["replay"]["priority_passes"] == ["p1"]
    assert len(second["replay"]["earlier"]) == 1
    assert second["replay"]["earlier"][0]["selection"]["semantic_echo"] == callback["candidates"][0]["semantic"]


@pytest.mark.parametrize("fault", ["new-turn", "wrong-phase", "other-active", "pending-priority",
                                  "missing-pass", "duplicate-pass", "stack-response", "other-hand",
                                  "other-controller", "wrong-zone", "source", "purpose", "multi-select"])
def test_cleanup_transition_refuses_unrecorded_responses_or_unbound_discards_before_search(fault):
    bot, session = ready(Session([0]))
    anchor, callback = cleanup_decisions()
    observation, semantic = callback["observation"], callback["candidates"][0]["semantic"]
    if fault == "new-turn":
        observation["turn"] = 2
    elif fault == "wrong-phase":
        anchor["observation"]["phase_step"] = "postcombat_main"
    elif fault == "other-active":
        observation["active_seat"] = "p1"
    elif fault == "pending-priority":
        observation["priority_seat"] = "p1"
    elif fault == "missing-pass":
        observation["passed_seats"] = ["p0"]
    elif fault == "duplicate-pass":
        observation["passed_seats"] = ["p0", "p0"]
    elif fault == "stack-response":
        observation["stack"] = [{"object_id": "response", "stack_kind": "spell"}]
    elif fault == "other-hand":
        semantic["choice"]["object"]["owner_seat"] = "p1"
    elif fault == "other-controller":
        semantic["choice"]["object"]["controller_seat"] = "p1"
    elif fault == "wrong-zone":
        semantic["choice"]["object"]["zone"] = "battlefield"
    elif fault == "source":
        callback["context"]["source"] = {"object_id": "ability"}
    elif fault == "purpose":
        callback["context"]["purpose"] = "sacrifice"
    elif fault == "multi-select":
        semantic["maximum"] = 2
    bot.choose(view(anchor))
    with pytest.raises(ValueError):
        bot.choose(view(callback))
    assert bot.failed and session.closed and session.requests == []


def step_trigger_decisions():
    anchor = decision({"kind": "pass"}, phase="postcombat_main")
    anchor["observation"].update(active_seat="p0", priority_seat="p0")
    source = {"card_name": "Needletooth Pack", "object_id": "trigger", "zone": "stack",
              "owner_seat": "p0", "controller_seat": "p0"}
    callback = decision(*[
        {"kind": "choose_target", "minimum": 1, "maximum": 1, "selected_count": 0, "slot": 0, "source": source,
         "target": {"object": {"object_id": f"creature-{i}", "zone": "battlefield",
                               "owner_seat": "p0", "controller_seat": "p0"}}}
        for i in range(2)], step=1, phase="end_step",
        stack=[{"object_id": "trigger", "stack_kind": "triggered_ability", "controller_seat": "p0"}])
    callback["context"].update(source=source)
    callback["observation"].update(active_seat="p0", priority_seat=None)
    return anchor, callback


def test_next_step_trigger_callback_replays_the_recorded_empty_stack_pass():
    bot, session = ready(Session([1]))
    anchor, callback = step_trigger_decisions()
    assert bot.choose(view(anchor)) == 10
    assert bot.choose(view(callback)) == 11
    (record, _, _), = session.requests
    assert record["anchor"]["decision"]["observation"]["phase_step"] == "postcombat_main"
    assert record["replay"] == {"priority_passes": ["p1"], "earlier": []}


@pytest.mark.parametrize("fault", ["new-turn", "skipped-step", "last-step", "other-active", "pending-priority",
                                   "passed", "stacked-anchor", "empty-stack", "spell", "other-trigger",
                                   "unstacked-source", "other-source"])
def test_next_step_trigger_refuses_anything_but_an_own_trigger_as_the_next_step_begins(fault):
    bot, session = ready(Session([0]))
    anchor, callback = step_trigger_decisions()
    observation = callback["observation"]
    if fault == "new-turn":
        observation["turn"] = 2
    elif fault == "skipped-step":
        anchor["observation"]["phase_step"] = "end_of_combat"
    elif fault == "last-step":
        anchor["observation"]["phase_step"] = "cleanup"
        observation["phase_step"] = "untap"
    elif fault == "other-active":
        observation["active_seat"] = "p1"
    elif fault == "pending-priority":
        observation["priority_seat"] = "p0"
    elif fault == "passed":
        observation["passed_seats"] = ["p1"]
    elif fault == "stacked-anchor":
        anchor["observation"]["stack"] = [{"object_id": "earlier", "stack_kind": "spell"}]
    elif fault == "empty-stack":
        observation["stack"] = []
    elif fault == "spell":
        observation["stack"][0]["stack_kind"] = "spell"
    elif fault == "other-trigger":
        observation["stack"].append({"object_id": "theirs", "stack_kind": "triggered_ability",
                                     "controller_seat": "p1"})
    elif fault == "unstacked-source":
        callback["context"]["source"] = dict(callback["context"]["source"], zone="battlefield")
    elif fault == "other-source":
        callback["context"]["source"] = dict(callback["context"]["source"], object_id="elsewhere")
    bot.choose(view(anchor))
    with pytest.raises(ValueError, match="crossed an unrecorded turn or phase transition"):
        bot.choose(view(callback))
    assert bot.failed and session.closed and session.requests == []


def test_entire_combat_group_reuses_one_original_neural_plan():
    bot, session = ready()
    record, _ = combat_fixture()
    initial = record["decision"]
    assert bot.choose(view(initial)) == 7
    later = later_decision(record, "attack")
    assert bot.choose(view(later)) == 19
    assert bot.plan.complete and len(session.requests) == 1


@pytest.mark.parametrize("fault", ["skip-group", "changed-state", "rewind", "wrong-seat", "stale-step",
                                  "unsupported", "unbound-callback", "expired-clock", "empty-pass-callback"])
def test_history_or_policy_failure_closes_session_and_never_returns_a_fallback(fault):
    bot, session = ready(Session([0]))
    received = decision({"kind": "pass"}, {"kind": "play_land"})
    if fault in ("skip-group", "changed-state"):
        record, _ = combat_fixture()
        bot.choose(view(record["decision"]))
        if fault == "changed-state":
            received = later_decision(record, "attack")
            received["observation"]["turn"] = 99
        else:
            received["seat_step"] = 11
    elif fault == "rewind":
        received["context"]["rewind"] = True
    elif fault == "wrong-seat":
        received["acting_seat"] = "p1"
    elif fault == "stale-step":
        bot.choose(view(received))
    elif fault == "unsupported":
        received = decision({"kind": "order_objects"})
    elif fault in ("unbound-callback", "empty-pass-callback"):
        if fault == "empty-pass-callback":
            bot.choose(view(received))
        received = decision({"kind": "choose_boolean", "value": False}, {"kind": "choose_boolean", "value": True},
                            step=1 if fault == "empty-pass-callback" else 0)
    clock = Clock(0, 1000).to_json() if fault == "expired-clock" else None
    with pytest.raises((ValueError, TimeoutError)):
        bot.choose(view(received, clock=clock))
    assert bot.failed and session.closed
    count = len(session.requests)
    with pytest.raises(ValueError, match="inactive or has failed"):
        bot.choose(view(received))
    assert len(session.requests) == count


def test_preprocessing_and_postvalidation_share_the_original_decision_deadline(monkeypatch):
    bot, session = ready(Session([0]))
    clock = [0.0]
    monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])
    observe = bot.history.observe
    def slow_observe(*args):
        observe(*args)
        clock[0] = 0.4
    bot.history.observe = slow_observe
    original_choose = session.choose
    def slow_result(*args, **kwargs):
        result = original_choose(*args, **kwargs)
        assert kwargs["timeout_s"] == pytest.approx(0.55)
        clock[0] = 0.96
        return result
    session.choose = slow_result
    with pytest.raises(TimeoutError, match="shared decision clock"):
        bot.choose(view(decision({"kind": "pass"}, {"kind": "play_land"}),
                        clock=Clock(1000, 1000).to_json()))
    assert bot.failed and session.closed and bot.step is None


def test_visible_name_and_loyalty_history_never_uses_hidden_hand_or_unconfirmed_activation():
    history = agent.PublicHistory("p0")
    own = {"seat": "p0", "hand": [{"object_id": "card", "card_name": "Original"}],
           "battlefield": [{"object_id": "walker", "card_name": "Walker",
                            "permanent": {"counters": {"loyalty": 3}}}]}
    observation = {"viewer": "p0", "turn": 1, "phase_step": "precombat_main",
                   "players": [own, {"seat": "p1", "hand": None}], "stack": []}
    history.observe(observation)
    selected = {"candidate_id": 10, "semantic_echo": {"kind": "activate_ability", "source": {"object_id": "walker"}}}
    history.selected({"context": {"kind": "priority"}, "observation": observation}, selected)
    assert history.fields(observation)["loyalty_used"] == []
    own["hand"][0]["card_name"] = "Changed"
    own["battlefield"][0]["permanent"]["counters"]["loyalty"] = 2
    history.observe(observation)
    assert history.fields(observation) == {"loyalty_used": ["walker"], "card_origins": {"card": "Original"}}
    observation["turn"] = 2
    history.observe(observation)
    assert history.fields(observation)["loyalty_used"] == []


def test_ability_uses_count_only_activations_confirmed_on_the_stack_for_permanents_still_here():
    history = agent.PublicHistory("p0")
    own = {"seat": "p0", "battlefield": [{"object_id": "librarian", "card_name": "Mild-Mannered Librarian"}]}
    observation = {"viewer": "p0", "turn": 10, "phase_step": "precombat_main",
                   "players": [own, {"seat": "p1", "hand": None}], "stack": []}
    ability = {"object_id": "o-ability", "stack_kind": "activated_ability", "source": {"object_id": "librarian"}}
    use = {"candidate_id": 2, "semantic_echo": {"kind": "activate_ability", "ability_index": 0,
                                                 "source": {"object_id": "librarian"}}}

    def activate(confirmed):
        history.observe(observation)
        history.selected({"context": {"kind": "priority"}, "observation": copy.deepcopy(observation)}, use)
        observation["stack"] = [ability] if confirmed else []
        history.observe(observation)
        observation["stack"] = []
        history.observe(observation)

    activate(False)                                   # a cancelled activation never reaches the stack
    assert "ability_uses" not in history.fields(observation)
    activate(True)
    activate(True)
    assert history.fields(observation)["ability_uses"] == [
        {"object_id": "librarian", "ability_index": 0, "turn": 10, "this_turn": 2, "total": 2}]
    observation["turn"] = 11
    activate(True)                                    # a new turn restarts this turn's count, not the total
    assert history.fields(observation)["ability_uses"] == [
        {"object_id": "librarian", "ability_index": 0, "turn": 11, "this_turn": 1, "total": 3}]
    history.selected({"context": {"kind": "priority"}, "observation": copy.deepcopy(observation)}, use)
    observation["turn"] = 12                          # a pending use expires with its turn
    observation["stack"] = [ability]
    history.observe(observation)
    assert history.fields(observation)["ability_uses"][0]["total"] == 3
    own["battlefield"] = []                           # a permanent that left is a new object if it returns
    assert "ability_uses" not in history.fields(observation)


def test_world_builder_restores_own_ability_uses_as_xmage_stores_them():
    java = (Path(__file__).parents[2] / "engines/xmage/kit/xmage/src/spellbench/kit/xmage/WorldBuilder.java").read_text()
    # ActivatedAbilityImpl.setActivationInfo: three state values keyed by the ability's original id and source zone.
    for key in ("activationsTurn", "activationsCount", "totalActivations"):
        assert f'getCardZoneString("{key}" + id, used.getSourceId(), game)' in java
    assert 'Json.arr(spec.history, "ability_uses")' in java and "p.isControlledBy(world.player(world.viewer))" in java


@pytest.mark.parametrize("fault", ["checkpoint", "hidden-deck", "missing-passes"])
def test_startup_refuses_unbound_checkpoint_or_forbidden_deck_information(fault):
    session = Session(checkpoint="wrong" if fault == "checkpoint" else CHECKPOINT)
    bot = agent.NeuralAgent(lambda: session, checkpoint=CHECKPOINT)
    start = game()
    if fault == "hidden-deck":
        start["opponent_deck"] = {"decklist": [{"name": "Secret", "count": 40}]}
    elif fault == "missing-passes":
        start["engine_profile"]["observation"]["passed_seats"] = False
    with pytest.raises(ValueError):
        bot.on_game_start(GameStart.from_request(start))
    assert bot.failed and (session.closed if fault == "checkpoint" else not session.closed)


def test_game_over_rejects_other_game_without_closing_live_session():
    bot, session = ready()
    with pytest.raises(ValueError):
        bot.on_game_over(GameOver.from_request({"game_id": "other"}))
    assert not session.closed
    bot.on_game_over(GameOver.from_request({"game_id": "opaque"}))
    bot.close()
    assert session.closed


@pytest.mark.parametrize("phase", ["start", "choose", "choose-audit"])
def test_policy_failure_survives_shutdown_and_failure_audit_errors(phase):
    failure = ValueError("original policy failure")

    class FailingSession(Session):
        def choose(self, *args, **kwargs):
            raise failure

        def close(self):
            self.closed = True
            raise RuntimeError("session shutdown failed")

    def audit(event):
        if event["event"] == "neural_game_start" and phase == "start":
            raise failure
        if event["event"] == "neural_failure" and phase == "choose-audit":
            raise OSError("failure audit unavailable")

    session = FailingSession()
    bot = agent.NeuralAgent(lambda: session, checkpoint=CHECKPOINT, visits=2, audit=audit)
    if phase == "start":
        operation = lambda: bot.on_game_start(GameStart.from_request(game()))
    else:
        bot.on_game_start(GameStart.from_request(game()))
        operation = lambda: bot.choose(view(decision({"kind": "pass"}, {"kind": "play_land"})))
    with pytest.raises(ValueError) as caught:
        operation()
    assert caught.value is failure
    assert session.closed and bot.failed and bot.session is None
    assert any("session shutdown failed" in note for note in failure.__notes__)
    if phase == "choose-audit":
        assert any("failure audit unavailable" in note for note in failure.__notes__)


def test_simultaneous_triggers_take_the_original_first_trigger_without_search_or_history():
    bot, session = ready(Session([1]))
    bot.choose(view(decision({"kind": "pass"}, {"kind": "play_land"})))
    def trigger(name, position, count=3):
        return {"kind": "order_pick", "source": None, "purpose": "triggers", "position": position, "count": count,
                "item": {"trigger": {"source_name": name, "ability_index": 0, "instance": 0}}}
    first = decision(trigger("Spectral Sailor", 0), trigger("Burst Lightning", 0), trigger("Prowess", 0), step=1)
    assert bot.choose(view(first)) == 10
    second = decision(trigger("Burst Lightning", 1), trigger("Prowess", 1), step=2)
    assert bot.choose(view(second)) == 10
    assert len(session.requests) == 1 and bot.history.earlier == []
    for bad in (decision(trigger("A", 0), trigger("B", 1), step=3), decision(trigger("A", 0, count=3), step=3)):
        stale, _ = ready(Session([1]))
        stale.choose(view(decision({"kind": "pass"}, {"kind": "play_land"})))
        bad["seat_step"] = 1
        with pytest.raises(ValueError, match="remaining triggers"):
            stale.choose(view(bad))


def test_graph_and_magezero_agents_keep_their_own_trigger_answers():
    import xmage_gnn_search
    import xmage_magezero_agent
    assert agent.NeuralAgent.original_trigger_order is True
    assert xmage_gnn_search.GraphAgent.original_trigger_order is False
    assert xmage_magezero_agent.MageZeroAgent.original_trigger_order is False


def test_attack_trigger_callbacks_replay_the_recorded_declaration_group():
    history = agent.PublicHistory("p0")
    begin = {"turn": 5, "phase_step": "beginning_of_combat", "active_seat": "p0", "stack": [], "passed_seats": []}
    history.anchor = {"decision": {"context": {"kind": "priority"}, "observation": begin},
                      "selection": {"candidate_id": 1, "semantic_echo": {"kind": "pass"}}}
    def attack(index):
        return {"decision": {"group": {"group_id": 7, "substep_count": 2, "substep_index": index},
                             "candidates": [{"candidate_id": 1, "semantic": {"kind": "declare_attack"}}]},
                "selection": {"candidate_id": 1, "semantic_echo": {"kind": "declare_attack"}}}
    history.earlier = [attack(0), attack(1)]
    callback = {"observation": {"turn": 5, "phase_step": "declare_attackers", "viewer": "p0"},
                "candidates": [{"candidate_id": 3, "semantic": {"kind": "choose_target"}}]}
    assert history.callback(callback)["replay"] == {"priority_passes": ["p1"], "earlier": history.earlier,
                                                    "attack_declarations": 2}
    begin["passed_seats"] = ["p1"]
    assert history.callback(callback)["replay"]["priority_passes"] == []
    for broken in ([attack(0)], [attack(1), attack(0)]):   # an incomplete or reordered group is not replayable
        history.earlier = broken
        with pytest.raises(ValueError, match="phase transition"):
            history.callback(callback)


def _cast_observation(stack, graveyard=(), exile=(), turn=4, step="main_1"):
    other = {"seat": "p1", "graveyard": [{"card_name": n, "object_id": f"g-{i}"} for i, n in enumerate(graveyard)],
             "exile": [{"card_name": n, "object_id": f"x-{i}"} for i, n in enumerate(exile)]}
    return {"viewer": "p0", "turn": turn, "phase_step": step, "players": [{"seat": "p0"}, other],
            "stack": [{"stack_kind": "spell", "copy": False, "object_id": oid, "card_name": name, "controller_seat": seat}
                      for oid, name, seat in stack]}


def test_stack_casts_record_own_methods_and_kicker_answers_and_public_flashback_only():
    history = agent.PublicHistory("p0")
    history.observe(_cast_observation([]))
    cast = {"kind": "cast_spell", "method": "flashback",
            "source": {"card_name": "Think Twice", "object_id": "o-grave", "zone": "graveyard"}}
    history.selected({"observation": _cast_observation([]), "context": {"kind": "priority"}},
                     {"candidate_id": 1, "semantic_echo": cast})
    history.observe(_cast_observation([("o-new", "Think Twice", "p0")]))
    kicker = {"kind": "optional_cost", "cost": "kicker", "pay": True,
              "source": {"card_name": "Think Twice", "object_id": "o-new", "zone": "stack", "controller_seat": "p0"}}
    history.selected({"observation": _cast_observation([("o-new", "Think Twice", "p0")]), "context": {"kind": "choice"}},
                     {"candidate_id": 2, "semantic_echo": kicker})
    assert history.fields(history.previous)["stack_casts"] == {"o-new": {"method": "flashback", "kicker": 1}}

    # The other seat's spell on an otherwise unchanged stack: one card fewer in its public graveyard is flashback,
    # an unchanged graveyard is a normal cast; an exile change or a second new object leaves the cast unknown.
    base = [("o-new", "Think Twice", "p0")]
    for graveyard, exile, expected in ((("Think Twice",), (), {"method": "normal"}), ((), (), None)):
        history.observe(_cast_observation(base, graveyard=("Think Twice",), exile=exile))
        history.observe(_cast_observation(base + [("o-opp", "Think Twice", "p1")], graveyard=graveyard))
        assert history.casts.get("o-opp") == (expected or {"method": "flashback"})
        history.casts.pop("o-opp")
    history.observe(_cast_observation(base, graveyard=("Think Twice",)))
    history.observe(_cast_observation(base + [("o-opp", "Think Twice", "p1")], exile=("Think Twice",)))
    assert "o-opp" not in history.casts
    history.observe(_cast_observation(base, graveyard=("Think Twice",)))
    history.observe(_cast_observation(base + [("o-a", "Think Twice", "p1"), ("o-b", "Shock", "p1")]))
    assert not {"o-a", "o-b"} & set(history.casts)
    history.observe(_cast_observation(base, graveyard=("Think Twice",)))
    history.observe(_cast_observation(base + [("o-late", "Think Twice", "p1")], step="main_2"))
    assert "o-late" not in history.casts
    # A spell that left the stack drops its fact.
    history.observe(_cast_observation([]))
    assert "stack_casts" not in history.fields(history.previous)
