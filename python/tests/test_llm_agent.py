"""LLM input boundaries, charged failures, clocks, and per-game state."""

from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest

from spellbench.bot import Decision, GameOver, GameStart
from spellbench.llm.agent import AgentConfig, LlmAgent, parse_choice
from spellbench.llm.prompt import CardCatalog, render_prompt
from spellbench.llm.provider import Completion, ProviderError

from v2_sample_semantics import SAMPLES, seat_decision


def decision(*, forced=False, step=0) -> Decision:
    payload = seat_decision([SAMPLES["pass"]] if forced else None,
                            extensions={"x_native": {"secret": "MUST-NOT-REACH-MODEL"}})
    payload["seat_step"] = step
    return Decision.from_request({"game_id": "g", "decision": payload,
                                  "clock": {"remaining_ms": 5000, "max_decision_ms": 3000},
                                  "game_secret": "MUST-NOT-REACH-MODEL"})


def game(game_id="g") -> GameStart:
    return GameStart.from_request({"game_id": game_id, "seat": "p0", "agent_seed": 123456789,
                                   "own_deck": {"decklist": [{"count": 4, "name": "Lightning Bolt"}]},
                                   "opponent_deck": {"secret": "MUST-NOT-REACH-MODEL"}})


class Provider:
    def __init__(self, result=None):
        self.result = result or Completion('{"candidate_id":1}', "snapshot-model", 50, 10)
        self.calls = []

    def complete(self, prompt, *, timeout_s):
        self.calls.append((prompt, timeout_s))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def agent(provider=None, **kwargs):
    provider = provider or Provider()
    log = io.StringIO()
    bot = LlmAgent(provider, settings={"model": "test"}, max_completion_tokens=32, log=log, **kwargs)
    bot.on_game_start(game())
    return bot, provider, log


def events(log):
    return [json.loads(line) for line in log.getvalue().splitlines()]


def test_prompt_contains_complete_core_view_and_no_native_or_raw_state():
    item = decision()
    prompt = render_prompt(item, own_deck=game().own_deck)
    body = json.loads(prompt.messages[1]["content"])
    assert body["observation"] == item.observation
    assert body["candidates"] == [vars(candidate) for candidate in item.candidates]
    assert "MUST-NOT-REACH-MODEL" not in json.dumps(prompt.messages)
    assert "clock" not in body and "extensions" not in body
    assert prompt.sha256 == render_prompt(item, own_deck=game().own_deck).sha256
    changed = replace(item, candidates=item.candidates[:-1])
    assert prompt.sha256 != render_prompt(changed, own_deck=game().own_deck).sha256


@pytest.mark.parametrize("change", ["opponent_hand", "viewer", "own_hand"])
def test_invalid_player_visibility_is_rejected_before_inference(change):
    item = decision()
    if change == "opponent_hand":
        item.observation["players"][1]["hand"] = [{"card_name": "Secret Card"}]
    elif change == "viewer":
        item.observation["viewer"] = "p1"
    else:
        item.observation["players"][0]["hand"] = None
    bot, provider, log = agent()
    with pytest.raises(ValueError):
        bot.choose(item)
    assert not provider.calls
    assert events(log)[-1]["status"] == "error"


def test_catalog_only_sends_text_for_known_names_and_records_missing_names(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"schema": "spellbench-card-text/v1", "cards": {
        "Lightning Bolt": "3 damage to any target", "Secret Card": "SECRET-TEXT"}}), encoding="utf-8")
    catalog = CardCatalog.load(path)
    prompt = render_prompt(decision(), catalog=catalog)
    body = json.loads(prompt.messages[1]["content"])
    assert body["card_text"] == {"Lightning Bolt": "3 damage to any target"}
    assert "Mountain" in body["missing_card_text"]
    assert "SECRET-TEXT" not in json.dumps(body)
    bot, _, log = agent(catalog=catalog)
    assert events(log)[0]["catalog_sha256"] == catalog.sha256


def test_prompt_cap_rejects_whole_decision_without_truncating_actions():
    with pytest.raises(ValueError, match="no candidates were truncated"):
        render_prompt(decision(), max_bytes=10)


@pytest.mark.parametrize("text", ['{"candidate_id":true}', '{"candidate_id":1.0}', '{"candidate_id":"1"}',
                                  '{"candidate_id":1,"other":0}', '{"candidate_id":1,"candidate_id":0}',
                                  '```json\n{"candidate_id":1}\n```', '[1]', '{"candidate_id":99}'])
def test_bad_model_choices_are_rejected(text):
    with pytest.raises(ProviderError):
        parse_choice(text, {0, 1})


def test_candidate_id_is_membership_not_array_index():
    assert parse_choice('{"candidate_id":42}', {7, 42}) == 42


def test_forced_choice_makes_no_call_and_is_logged():
    bot, provider, log = agent()
    assert bot.choose(decision(forced=True)) == 0
    assert not provider.calls
    assert events(log)[-1]["status"] == "forced"
    assert events(log)[-1]["tokens"] == 0


def test_success_records_actual_usage_and_resets_bounded_history_per_game():
    bot, provider, log = agent(config=AgentConfig(history_decisions=1, record_prompts=True))
    assert bot.choose(decision()) == 1
    assert bot.choose(decision(step=1)) == 1
    body = json.loads(provider.calls[-1][0].messages[1]["content"])
    assert len(body["own_decision_history"]) == 1
    assert events(log)[-1]["tokens"] == 120
    assert events(log)[-1]["returned_model"] == "snapshot-model"
    assert "messages" in events(log)[-1]
    bot.on_game_over(GameOver.from_request({"game_id": "g", "terminal": {}}))
    bot.on_game_start(game())
    assert bot.choose(decision()) == 1
    assert json.loads(provider.calls[-1][0].messages[1]["content"])["own_decision_history"] == []
    assert events(log)[-1]["tokens"] == 60


def test_unknown_usage_failure_is_counted_and_cannot_retry_or_use_forced_fallback():
    bot, provider, log = agent(Provider(ProviderError("http_429")))
    with pytest.raises(ProviderError, match="http_429"):
        bot.choose(decision())
    failure = events(log)[-1]
    assert failure["calls"] == 1 and failure["unknown_usage"] is True
    with pytest.raises(ProviderError, match="game_already_failed"):
        bot.choose(decision(forced=True))
    assert len(provider.calls) == 1


def test_invalid_selection_preserves_known_charged_usage():
    bot, provider, log = agent(Provider(Completion('{"candidate_id":99}', "test", 50, 10)))
    with pytest.raises(ProviderError, match="unoffered_candidate"):
        bot.choose(decision())
    failure = events(log)[-1]
    assert failure["tokens"] == 60 and failure["unknown_usage"] is False


def test_call_and_token_reservations_stop_before_another_request():
    bot, provider, log = agent(config=AgentConfig(max_calls_per_game=1))
    assert bot.choose(decision()) == 1
    with pytest.raises(ProviderError, match="call_budget_exhausted"):
        bot.choose(decision(step=1))
    assert len(provider.calls) == 1
    bot, provider, log = agent(config=AgentConfig(max_tokens_per_game=20))
    with pytest.raises(ProviderError, match="token_budget_exhausted"):
        bot.choose(decision())
    assert not provider.calls


def test_host_clock_bounds_request_and_render_time_is_subtracted():
    times = iter([0, 0.5, 0.6, 0.6])
    bot, provider, _ = agent(monotonic=lambda: next(times))
    assert bot.choose(decision()) == 1
    assert provider.calls[0][1] == pytest.approx(2.4)


def test_expired_clock_makes_no_call():
    bot, provider, log = agent()
    item = replace(decision(), clock={"remaining_ms": 50, "max_decision_ms": 3000})
    with pytest.raises(ProviderError, match="deadline_exhausted"):
        bot.choose(item)
    assert not provider.calls


def test_actual_token_budget_overrun_does_not_return_a_choice():
    bot, _, log = agent(Provider(Completion('{"candidate_id":1}', "test", 300_000, 10)))
    with pytest.raises(ProviderError, match="token_budget_exceeded"):
        bot.choose(decision())
    assert events(log)[-1]["tokens"] == 300_010


def history_decision(events, *, step, forced=False):
    item = decision(forced=forced, step=step)
    item.extensions["x_public_history_v1"] = {"schema": "x_public_history_v1", "events": events}
    return item


def test_public_history_is_opt_in_and_never_reaches_the_default_prompt():
    bot, provider, _ = agent()
    bot.choose(history_decision([{"kind": "turn_began", "turn": 1, "active_seat": "p0"}], step=0))
    body = json.loads(provider.calls[0][0].messages[1]["content"])
    assert "public_history" not in body and "turn_began" not in json.dumps(provider.calls[0][0].messages)
    assert body["prompt_version"] == "spellbench-llm/v1"


def test_public_history_accumulates_deltas_including_forced_choices_and_keeps_the_latest_events():
    bot, provider, log = agent(config=AgentConfig(public_history_events=2))
    draw = {"kind": "draw", "seat": "p0", "card": None}
    bot.choose(history_decision([{"kind": "turn_began", "turn": 1, "active_seat": "p0"}], step=0, forced=True))
    bot.choose(history_decision([draw], step=1))
    bot.choose(history_decision([draw], step=1))  # retransmission repeats its delta
    shuffle = {"kind": "library_shuffled", "owner_seat": "p1"}
    bot.choose(history_decision([shuffle], step=2))
    bodies = [json.loads(prompt.messages[1]["content"]) for prompt, _ in provider.calls]
    assert bodies[0]["public_history"] == {"events": [{"kind": "turn_began", "turn": 1, "active_seat": "p0"}, draw],
                                           "omitted_earlier_events": 0}
    assert bodies[1]["public_history"] == bodies[0]["public_history"]
    assert bodies[2]["public_history"] == {"events": [draw, shuffle], "omitted_earlier_events": 1}
    assert bodies[2]["prompt_version"] == "spellbench-llm/v1+public-history-v1"
    assert "public_history lists" in provider.calls[0][0].messages[0]["content"]
    assert "MUST-NOT-REACH-MODEL" not in json.dumps(provider.calls[-1][0].messages)
    assert events(log)[0]["prompt_version"] == "spellbench-llm/v1+public-history-v1"
    bot.on_game_over(GameOver.from_request({"game_id": "g", "terminal": {"winner": "p0"}}))
    bot.on_game_start(game())
    bot.choose(history_decision([], step=0))
    assert json.loads(provider.calls[-1][0].messages[1]["content"])["public_history"]["events"] == []


@pytest.mark.parametrize("extension", [None, {"schema": "other", "events": []}, {"schema": "x_public_history_v1"},
                                       {"schema": "x_public_history_v1", "events": [{"card": None}]}])
def test_accepted_public_history_must_be_present_and_well_formed(extension):
    bot, provider, log = agent(config=AgentConfig(public_history_events=8))
    item = decision(step=0)
    if extension is not None:
        item.extensions["x_public_history_v1"] = extension
    with pytest.raises(ValueError):
        bot.choose(item)
    assert not provider.calls
    assert events(log)[-1]["error"] == "invalid_observation_or_prompt"
