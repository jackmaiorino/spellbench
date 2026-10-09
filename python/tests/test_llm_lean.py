"""The lean prompt must state the same visible position as the plain prompt, only smaller."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path

from spellbench.bot import Decision, GameOver, GameStart
from spellbench.llm.agent import AgentConfig, LlmAgent
from spellbench.llm.lean import LEAN_PROMPT_VERSION, lean_payload
from spellbench.llm.prompt import render_prompt, system_prompt
from spellbench.llm.provider import Completion
from v2_sample_semantics import SAMPLES, seat_decision


def item(payload=None, game_id='g'):
    return Decision.from_request({'game_id': game_id, 'decision': payload or seat_decision(),
                                  'clock': {'remaining_ms': 5000, 'max_decision_ms': 3000}})


def without_defaults(value):
    if isinstance(value, dict):
        stripped = {key: without_defaults(child) for key, child in value.items()}
        return {key: child for key, child in stripped.items()
                if not (child is None or child is False or child in ([], {}))}
    if isinstance(value, list):
        return [without_defaults(child) for child in value]
    return value


def read_lean(body, aliases):
    """Expand a lean body the way its instructions tell the model to, back to original IDs."""
    names = {short: original for original, short in aliases.items()}
    defaults = body.pop('card_defaults')

    def expand(value):
        if isinstance(value, dict):
            value = {key: expand(child) for key, child in value.items()}
            if value.get('characteristics') == 'default':
                shared = defaults[value['card_name']]
                value.update({key: copy.deepcopy(shared.get(key)) for key in ('characteristics', 'full_name')})
            return value
        if isinstance(value, list):
            return [expand(child) for child in value]
        return names.get(value, value) if isinstance(value, str) else value

    return without_defaults(expand(body))


def assert_same_position(decision, **kwargs):
    aliases = {}
    plain = json.loads(render_prompt(decision, max_bytes=2**20, **kwargs).messages[1]['content'])
    lean = render_prompt(decision, max_bytes=2**20, prompt_format='lean-v1', aliases=aliases, **kwargs)
    assert read_lean(json.loads(lean.messages[1]['content']), aliases) == without_defaults(plain)
    return plain, lean


def test_all_semantic_kinds_and_history_restore_without_mutation():
    decision = item(seat_decision(list(SAMPLES.values())))
    before = copy.deepcopy(decision)
    assert_same_position(decision, own_deck={'decklist': [{'count': 4, 'name': 'Lightning Bolt'}]},
                         history=[{'seat_step': 2, 'choice': SAMPLES['cast_spell']}])
    assert decision == before


def test_objects_that_differ_from_their_card_defaults_keep_their_own_values():
    payload = seat_decision()
    battlefield = payload['observation']['players'][0]['battlefield']
    for power in (2, 2, 5):
        changed = copy.deepcopy(battlefield[0])
        changed['object_id'] = f'{changed["object_id"]}-{power}-{len(battlefield)}'
        changed['characteristics']['power'] = power
        battlefield.append(changed)
    hidden = copy.deepcopy(battlefield[0])
    hidden.update(object_id='face-down', characteristics=None)
    battlefield.append(hidden)
    _, lean = assert_same_position(item(payload))
    objects = json.loads(lean.messages[1]['content'])['observation']['players'][0]['battlefield']
    assert objects[-1]['characteristics'] is None and objects[-1]['full_name'] is None


def test_golden_visible_positions_restore_and_shrink():
    goldens = Path(__file__).resolve().parents[2] / 'goldens/protocol_v2'
    checked = plain_bytes = lean_bytes = 0
    for path in goldens.glob('game_*tour.transcript.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            message = json.loads(line)['message']
            if message.get('request_type') != 'choose':
                continue
            decision = Decision.from_request(message)
            plain, lean = assert_same_position(decision)
            plain_bytes += render_prompt(decision, max_bytes=2**20).bytes
            lean_bytes += lean.bytes
            checked += 1
    assert checked > 20
    assert lean_bytes < plain_bytes * 0.8


def test_aliases_are_stable_within_a_game_and_reset_between_games():
    calls = []

    class Provider:
        def complete(self, prompt, *, timeout_s):
            calls.append(json.loads(prompt.messages[1]['content']))
            return Completion('{"candidate_id":1}', 'test', 50, 10)

    log = io.StringIO()
    agent = LlmAgent(Provider(), settings={'model': 'test'}, max_completion_tokens=32, log=log,
                     config=AgentConfig(prompt_format='lean-v1'))
    assert json.loads(log.getvalue().splitlines()[0])['prompt_version'] == LEAN_PROMPT_VERSION
    first, reordered = seat_decision(), seat_decision()
    reordered['observation']['players'].reverse()
    for game_id, payloads in (('g', (first, reordered)), ('h', (reordered,))):
        agent.on_game_start(GameStart.from_request({'game_id': game_id, 'seat': 'p0'}))
        for payload in payloads:
            assert agent.choose(item(payload, game_id)) == 1
        agent.on_game_over(GameOver.from_request({'game_id': game_id, 'terminal': {}}))
    ids = [{obj['card_name']: obj['object_id'] for player in call['observation']['players']
            for obj in player['battlefield']} for call in calls]
    assert ids[0] == ids[1] != ids[2]


def test_lean_payload_does_not_mutate_input_and_instructions_name_the_encoding():
    payload = {'observation': seat_decision()['observation']}
    before = copy.deepcopy(payload)
    lean_payload(payload, {})
    assert payload == before
    assert 'card_defaults' in system_prompt('lean-v1')
