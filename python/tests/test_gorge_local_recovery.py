"""Terminal observation and recovery failures; fixtures are not played games."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import gorge_recover_local_native as recovery

spec = importlib.util.spec_from_file_location('local_recovery_fixture', ROOT / 'python/tests/test_gorge_hosted_gate.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Host:
    def __init__(self, root, identity):
        record = root / 'released-reservation.json'
        fixture.write(record, dict(identity, token='fixture-reservation-token'))
        self.path = record
        self.fate, self.state, self.outcome, self.errors, self.descendants = 'released', 'absent', 'success', [], []

    def status(self, token):
        assert token == 'fixture-reservation-token'
        return dict(test_root=False, token_fate=self.fate)

    def _history(self, fate):
        return [dict(token='fixture-reservation-token', fate=self.fate, path=str(self.path))]

    def read_events(self, token):
        return [dict(kind='adopt', pid=123, creation_time=456),
            dict(kind='release', outcome=self.outcome, at='fixture-terminal-time')], self.errors

    def _work_roots(self, events):
        return [(123, 456)]

    def process_state(self, pid, creation):
        assert (pid, creation) == (123, 456)
        return self.state

    def live_descendants(self, roots):
        return self.descendants


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    native, runtime, pins = fixture.local_evidence(tmp_path)
    identity = json.loads((native / 'LOCAL-TERMINAL.json').read_bytes())['execution_id']
    for name in ('SEAL.json', 'LOCAL-TERMINAL.json', 'LOCAL-CLEANUP.json', 'RECOVERY.json', 'HOST-RELEASE.json'):
        (native / name).unlink()
    fixture.write(native / 'host-dispatch.json', dict(token='fixture-reservation-token', generation=identity['generation']))
    cold, runtime_cold = tmp_path / 'native-cold', tmp_path / 'runtime-cold'
    shutil.copytree(native, cold)
    shutil.copytree(runtime, runtime_cold)
    monkeypatch.setattr(recovery.shutil, 'disk_usage', lambda path: SimpleNamespace(free=2**40))
    return dict(hot=native, cold=cold, runtime=runtime, runtime_recovery=runtime_cold,
        runtime_seal_sha256=pins['runtime_seal_sha256'], host=Host(tmp_path, identity),
        lane=identity['lane'], work_id=identity['work_id'])


def test_terminal_local_fixture_recovers_idempotently_and_excludes_tokens_from_receipts(attempt):
    result = recovery.recover(**attempt)
    assert result['native_qualification_passed'] and result['rated_games'] == 0
    assert recovery.recover(**attempt) == result
    for name in ('SEAL.json', 'RECOVERY.json', 'LOCAL-TERMINAL.json', 'LOCAL-CLEANUP.json', 'HOST-RELEASE.json'):
        first, second = attempt['hot'] / name, attempt['cold'] / name
        assert first.read_bytes() == second.read_bytes()
        assert b'fixture-reservation-token' not in first.read_bytes()


@pytest.mark.parametrize('failure', ['held', 'unknown_fate', 'live', 'unknown_process', 'descendants',
    'unreadable_events', 'wrong_generation', 'wrong_work', 'changed_runtime', 'changed_cold', 'storage'])
def test_incomplete_or_mismatched_attempt_cannot_write_terminal_receipts(attempt, monkeypatch, failure):
    host = attempt['host']
    if failure == 'held': host.fate = 'holds'
    elif failure == 'unknown_fate': host.fate = 'unknown'
    elif failure == 'live': host.state = 'alive'
    elif failure == 'unknown_process': host.state = 'unknown'
    elif failure == 'descendants': host.descendants = [dict(pid=789)]
    elif failure == 'unreadable_events': host.errors = ['unreadable event']
    elif failure == 'wrong_generation':
        dispatch = json.loads((attempt['hot'] / 'host-dispatch.json').read_bytes())
        dispatch['generation'] += 1
        fixture.write(attempt['hot'] / 'host-dispatch.json', dispatch)
    elif failure == 'wrong_work': attempt['work_id'] = 'other-job'
    elif failure == 'changed_runtime': (attempt['runtime_recovery'] / 'registry.gob.gz').write_bytes(b'changed')
    elif failure == 'changed_cold': (attempt['cold'] / 'native/MANIFEST.json').write_text('{}')
    elif failure == 'storage':
        monkeypatch.setattr(recovery.shutil, 'disk_usage', lambda path: SimpleNamespace(free=recovery.RESERVE))
    with pytest.raises(RuntimeError):
        recovery.recover(**attempt)
    for root in (attempt['hot'], attempt['cold']):
        assert not (root / 'SEAL.json').exists() and not (root / 'LOCAL-TERMINAL.json').exists()


def test_terminal_native_failure_is_retained_without_native_admission(attempt):
    attempt['host'].outcome = 'failed'
    path = attempt['hot'] / 'native/RECEIPT.json'
    receipt = json.loads(path.read_bytes())
    receipt.update(exit_code=1, native_passed=False)
    fixture.write(path, receipt)
    shutil.copyfile(path, attempt['cold'] / 'native/RECEIPT.json')
    result = recovery.recover(**attempt)
    assert result['independently_recovered'] and not result['native_qualification_passed']
    pins = {key: result[key] for key in ('seal_sha256', 'runtime_seal_sha256', 'cleanup_sha256')}
    with pytest.raises(fixture.gate.NativeAuditGateError):
        fixture.gate.verify_native_audit(attempt['cold'], attempt['runtime_recovery'], **pins)


def test_recorded_parent_failure_recovers_with_unknown_native_exit_code(attempt):
    attempt['host'].outcome = 'failed'
    for root in (attempt['hot'], attempt['cold']):
        (root / 'native/RECEIPT.json').unlink()
        fixture.write(root / 'native/PARENT-FAILED.json', dict(error='fixture parent failure'))
        fixture.write(root / 'CLOSURE.json', dict(native_passed=False, error='fixture parent failure',
            stop_reason=None, rated_games=0))
    result = recovery.recover(**attempt)
    assert result['independently_recovered'] and not result['native_qualification_passed']
    terminal = json.loads((attempt['cold'] / 'LOCAL-TERMINAL.json').read_bytes())
    assert terminal['exit_code'] is None and terminal['error'] == 'fixture parent failure'
