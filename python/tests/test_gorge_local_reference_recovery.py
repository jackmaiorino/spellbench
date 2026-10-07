"""Local reference recovery requires actual terminal ownership before writes."""
import importlib.util
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import gorge_recover_local_reference as recovery

spec = importlib.util.spec_from_file_location('reference_recovery_host_fixture', ROOT/'python/tests/test_gorge_local_recovery.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery.shutil, 'disk_usage', lambda path: SimpleNamespace(free=2**40))
    native, runtime, pins = fixture.fixture.local_evidence(tmp_path)
    native_cold, runtime_cold = tmp_path/'native-cold', tmp_path/'runtime-cold'
    shutil.copytree(native, native_cold); shutil.copytree(runtime, runtime_cold)
    hot, cold = tmp_path/'reference-hot', tmp_path/'reference-cold'
    hot.mkdir(); cold.mkdir(); (hot/'reference').mkdir()
    identity = dict(host='unit-test-only', lane='spellbench-gorge', work_id='reference-fixture', generation=1)
    host = fixture.Host(tmp_path, identity)
    recovery.put(hot, 'host-dispatch.json', dict(token='fixture-reservation-token', generation=1))
    recovery.put(hot, 'CLOSURE.json', dict(reference_passed=True, error=None, stop_reason=None))
    recovery.put(hot, 'reference/RECEIPT.json', dict(exit_code=0, reference_passed=True, stop_reason=None))
    recovery.put(hot, 'reference/MANIFEST.json', dict(source_commit='fixture-only'))
    monkeypatch.setattr(recovery, 'verify_local_reference_result', lambda *args, **kwargs:
        dict(passed=True, source_commit='fixture-only', rated_games=0))
    return dict(hot=hot, cold=cold, runtime=runtime, runtime_recovery=runtime_cold,
        runtime_seal_sha256=pins['runtime_seal_sha256'], native=native, native_recovery=native_cold,
        native_seal_sha256=pins['seal_sha256'], native_cleanup_sha256=pins['cleanup_sha256'],
        host=host, lane='spellbench-gorge', work_id='reference-fixture')


def test_terminal_reference_recovery_is_independent_idempotent_and_token_free(attempt):
    result = recovery.recover(**attempt)
    assert result['reference_qualification_passed'] and result['rated_games'] == 0
    assert recovery.recover(**attempt) == result
    for name in ('SEAL.json', 'LOCAL-CLEANUP.json', 'RECOVERY.json', 'HOST-RELEASE.json', 'LOCAL-TERMINAL.json'):
        first, second = attempt['hot']/name, attempt['cold']/name
        assert first.read_bytes() == second.read_bytes()
        assert b'fixture-reservation-token' not in first.read_bytes()


def test_external_release_observer_retains_the_same_terminal_recovery(attempt):
    observed = []
    def observe(host, dispatch, *, lane, work_id):
        observed.append((lane, work_id, dispatch['generation']))
        return recovery.owned_release(host, dispatch, lane=lane, work_id=work_id)
    result = recovery.recover(**attempt, release_observer=observe)
    assert result['reference_qualification_passed']
    assert observed == [('spellbench-gorge', 'reference-fixture', 1)]


@pytest.mark.parametrize('change', ['generation', 'work_id', 'live_process', 'live_descendant',
    'missing_process_identity', 'boolean_generation'])
def test_changed_external_release_is_refused_before_recovery_writes(attempt, change):
    def observe(host, dispatch, *, lane, work_id):
        result = recovery.owned_release(host, dispatch, lane=lane, work_id=work_id)
        if change == 'generation': result['execution_id']['generation'] += 1
        elif change == 'work_id': result['execution_id']['work_id'] = 'another-reference'
        elif change == 'live_process': next(iter(result['processes'].values()))['state'] = 'alive'
        elif change == 'live_descendant': result['live_descendants'] = [dict(pid=123)]
        elif change == 'missing_process_identity': next(iter(result['processes'].values())).pop('creation_time')
        else: result['execution_id']['generation'] = True
        return result
    with pytest.raises(RuntimeError, match='exact reference execution'):
        recovery.recover(**attempt, release_observer=observe)
    for root in (attempt['hot'], attempt['cold']):
        assert not (root/'SEAL.json').exists() and not (root/'LOCAL-TERMINAL.json').exists()


@pytest.mark.parametrize('failure', ['held', 'live', 'wrong_work', 'changed_native', 'changed_cold', 'storage'])
def test_active_or_changed_reference_attempt_cannot_create_terminal_receipts(attempt, monkeypatch, failure):
    if failure == 'held': attempt['host'].fate = 'holds'
    elif failure == 'live': attempt['host'].state = 'alive'
    elif failure == 'wrong_work': attempt['work_id'] = 'another-job'
    elif failure == 'changed_native': (attempt['native_recovery']/'SEAL.json').write_text('{}')
    elif failure == 'storage':
        monkeypatch.setattr(recovery.shutil, 'disk_usage',
            lambda path: SimpleNamespace(free=recovery.RESERVE+recovery.CAP-1))
    else: recovery.put(attempt['cold'], 'unexpected.json', dict(changed=True))
    with pytest.raises(RuntimeError): recovery.recover(**attempt)
    for root in (attempt['hot'], attempt['cold']):
        assert not (root/'SEAL.json').exists() and not (root/'LOCAL-TERMINAL.json').exists()


def test_claimed_reference_pass_with_failed_verification_is_retained_as_failed(attempt, monkeypatch):
    def failed(*args, **kwargs):raise RuntimeError('fixture-only changed participant evidence')
    monkeypatch.setattr(recovery, 'verify_local_reference_result', failed)
    result = recovery.recover(**attempt)
    assert result['independently_recovered'] and not result['reference_qualification_passed']
    assert result['verification_failures'] == ['RuntimeError: fixture-only changed participant evidence']
    assert recovery.read(attempt['cold']/'reference/RECEIPT.json')['reference_passed'] is True
