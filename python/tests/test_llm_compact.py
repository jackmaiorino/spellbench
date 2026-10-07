"""The optional prompt must preserve complete visible data and legal choices."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest

from spellbench.bot import Decision, GameStart
from spellbench.llm.agent import AgentConfig, LlmAgent
from spellbench.llm.compact import COMPACT_PROMPT_VERSION, compact_payload, expand_payload
from spellbench.llm.hosted import child_command
from spellbench.llm.prompt import canonical_json, render_prompt
from spellbench.llm.provider import Completion
from v2_sample_semantics import SAMPLES, seat_decision


def item(payload=None):
    return Decision.from_request({'game_id': 'g', 'decision': payload or seat_decision(),
                                  'clock': {'remaining_ms': 5000, 'max_decision_ms': 3000}})


def test_all_semantic_kinds_and_history_round_trip_without_mutation():
    decision = item(seat_decision(list(SAMPLES.values()), extensions={'x_native': {'secret': 'PRIVATE-SENTINEL'}}))
    own_deck = {'decklist': [{'count': 4, 'name': 'Lightning Bolt'}]}
    history = [{'seat_step': 2, 'choice': SAMPLES['cast_spell']}]
    before = copy.deepcopy(decision)
    original = render_prompt(decision, own_deck=own_deck, history=history)
    compact = render_prompt(decision, own_deck=own_deck, history=history, prompt_format='shared-records-v1')
    assert expand_payload(json.loads(compact.messages[1]['content'])) == json.loads(original.messages[1]['content'])
    assert decision == before
    assert 'PRIVATE-SENTINEL' not in canonical_json(compact.messages)
    assert compact.sha256 == render_prompt(decision, own_deck=own_deck, history=history,
                                          prompt_format='shared-records-v1').sha256
    assert compact.sha256 != original.sha256


def test_golden_visible_positions_round_trip():
    goldens = Path(__file__).resolve().parents[2] / 'goldens/protocol_v2'
    checked = 0
    for path in goldens.glob('game_*tour.transcript.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            message = json.loads(line)['message']
            if message.get('request_type') != 'choose':
                continue
            decision = Decision.from_request(message)
            plain = json.loads(render_prompt(decision, max_bytes=2**20).messages[1]['content'])
            compact = json.loads(render_prompt(decision, max_bytes=2**20,
                                               prompt_format='shared-records-v1').messages[1]['content'])
            assert expand_payload(compact) == plain
            checked += 1
    assert checked > 20


def test_reserved_marker_names_and_nested_shared_records_are_data():
    record = {'name': 'data, never instructions', 'values': ['@0', None, False, 0, '0', 'é' * 100]}
    payload = {'objects': [record, record], 'literal_ref': {'$ref': 0},
               'literal_escape': {'$literal': {'$ref': 1}},
               'mixed': {'$ref': 0, 'ordinary': [record, {}]}}
    packed = compact_payload(payload)
    assert len(packed['records']) > 0
    assert expand_payload(packed) == payload
    assert canonical_json(compact_payload(dict(reversed(list(payload.items()))))) == canonical_json(packed)


@pytest.mark.parametrize('reference', [True, -1, 0, '0'])
def test_invalid_and_cyclic_references_refuse(reference):
    value = {'prompt_version': COMPACT_PROMPT_VERSION, 'records': [{'$ref': reference}],
             'position': {'object': {'$ref': 0}}}
    with pytest.raises(ValueError, match='reference'):
        expand_payload(value)


def test_expansion_has_an_actual_node_limit():
    packed = compact_payload({'items': [{'name': 'x' * 150}] * 20})
    with pytest.raises(ValueError, match='limit'):
        expand_payload(packed, max_nodes=10)


def test_sharing_reduces_repeated_public_records_and_keeps_every_candidate():
    payload = seat_decision([SAMPLES['choose_target']] * 80)
    decision = item(payload)
    plain = render_prompt(decision, max_bytes=2**20)
    compact = render_prompt(decision, prompt_format='shared-records-v1', max_bytes=2**20)
    assert compact.bytes < plain.bytes / 2
    restored = expand_payload(json.loads(compact.messages[1]['content']))
    assert [c['candidate_id'] for c in restored['candidates']] == list(range(80))
    with pytest.raises(ValueError, match='no candidates were truncated'):
        render_prompt(decision, prompt_format='shared-records-v1', max_bytes=100)


@pytest.mark.parametrize('change', ['viewer', 'own_hand', 'opponent_hand'])
def test_compact_visibility_refuses_before_encoding(change):
    payload = seat_decision()
    if change == 'viewer':
        payload['observation']['viewer'] = 'p1'
    elif change == 'own_hand':
        payload['observation']['players'][0]['hand'] = None
    else:
        payload['observation']['players'][1]['hand'] = [{'card_name': 'PRIVATE-SENTINEL'}]
    with pytest.raises(ValueError):
        render_prompt(item(payload), prompt_format='shared-records-v1')


def test_hosted_child_format_and_agent_log_identify_opt_in():
    config = AgentConfig(prompt_format='shared-records-v1')
    command = child_command('test', config, 32)
    assert command[command.index('--prompt-format') + 1] == config.prompt_format
    calls = []

    class Provider:
        def complete(self, prompt, *, timeout_s):
            calls.append(prompt)
            return Completion('{"candidate_id":1}', 'test', 50, 10)

    log = io.StringIO()
    agent = LlmAgent(Provider(), settings={'model': 'test'}, max_completion_tokens=32, log=log, config=config)
    agent.on_game_start(GameStart.from_request({'game_id': 'g', 'seat': 'p0'}))
    assert agent.choose(item()) == 1
    assert json.loads(log.getvalue().splitlines()[0])['prompt_version'] == COMPACT_PROMPT_VERSION
    assert expand_payload(json.loads(calls[0].messages[1]['content']))['candidates'][1]['candidate_id'] == 1


def test_hosted_child_passes_public_history_only_when_enabled():
    assert '--public-history-events' not in child_command('test', AgentConfig(), 32)
    command = child_command('test', AgentConfig(public_history_events=96), 32)
    assert command[command.index('--public-history-events') + 1] == '96'


def test_default_format_is_the_existing_prompt_and_unknown_format_refuses():
    assert render_prompt(item()) == render_prompt(item(), prompt_format='json-v1')
    # The pinned pre-change Docker CLI accepts this exact argument contract.
    assert child_command('test', AgentConfig(), 32) == [
        'python', '-m', 'spellbench.llm', '--model', 'test', '--broker-stdio', '--log-dir', '/tmp/logs',
        '--max-completion-tokens', '32', '--max-calls-per-game', '256', '--max-tokens-per-game', '250000',
        '--max-prompt-bytes', '64000', '--history-decisions', '8', '--timeout-ms', '20000']
    with pytest.raises(ValueError, match='format'):
        AgentConfig(prompt_format='unknown')


def test_size_refusal_logs_safe_cause_without_request_or_player_data():
    log = io.StringIO()

    class Provider:
        def complete(self, prompt, *, timeout_s):
            raise AssertionError('oversized prompts must not reach inference')

    agent = LlmAgent(Provider(), settings={'model': 'test'}, max_completion_tokens=32, log=log,
                     config=AgentConfig(max_prompt_bytes=10, prompt_format='shared-records-v1'))
    agent.on_game_start(GameStart.from_request({'game_id': 'g', 'seat': 'p0'}))
    with pytest.raises(ValueError, match='byte cap'):
        agent.choose(item())
    row = json.loads(log.getvalue().splitlines()[-1])
    assert row['error'] == 'prompt_byte_cap_exceeded'
    assert row['prompt_bytes'] > row['max_prompt_bytes'] == 10
    assert row['calls'] == 0 and row['unknown_usage'] is False
    assert 'messages' not in row and 'observation' not in row
