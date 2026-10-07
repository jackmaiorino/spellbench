"""Structural and tamper checks for the gate; fixtures are not played games."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gorge_native_gate', ROOT / 'tools/gorge_native_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')


def seal(root):
    files = {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': gate.sha(p)}
             for p in root.rglob('*') if p.is_file() and p.name != 'SEAL.json'}
    write(root / 'SEAL.json', {'files': files})
    return gate.sha(root / 'SEAL.json')


@pytest.fixture
def evidence(tmp_path):
    return build_evidence(tmp_path)


def build_evidence(tmp_path, policies=None):
    selection = 'all' if policies is None else ','.join(policies)
    policies = gate.POLICIES if policies is None else policies
    blocks = gate.schedule_blocks(policies)
    runtime, native = tmp_path / 'runtime', tmp_path / 'native'
    runtime.mkdir(); native.mkdir()
    (runtime / 'gorgequal-linux-amd64').write_bytes(b'fixture-only-binary')
    (runtime / 'registry.gob.gz').write_bytes(b'fixture-only-registry')
    write(runtime / 'BUILD.json', {'source_commit': 'runtime-source'})
    runtime_seal = seal(runtime)
    rows = [{'game': i, 'classification': 'natural'} for i in range(blocks)]
    callback = native / 'artifact/full-native-audit-3-workers-2'
    callback.mkdir(parents=True)
    primary = callback / 'primary.jsonl'
    primary.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    allocation = {'kind': 'substantial', 'outputs_identical': True}
    write(native / 'CI-TERMINAL.json', {'status': 'completed', 'conclusion': 'success', 'id': 17, 'head_sha': 'launcher-source'})
    write(native / 'RECOVERY.json', {'native_qualification_passed': True, 'independent_recovery_verified': True,
        'github_run_id': 17, 'launcher_source_commit': 'launcher-source', 'rated_games': 0})
    write(native / 'artifact/NATIVE-AUDIT.json', {'passed': True, 'seed_blocks': blocks, 'completed_games': 2 * blocks,
        'rated_games': 0, 'allocation': allocation, 'full_report_path': '/remote/' + callback.name + '/report.json',
        'primary_sha256': gate.sha(primary)})
    write(native / 'artifact/ALLOCATION.json', allocation)
    write(native / 'artifact/CLOSURE.json', {'exit_code': 0, 'stop_reason': None, 'native_passed': True})
    write(native / 'artifact/MANIFEST.json', {'runtime_source_commit': 'runtime-source', 'source_commit': 'launcher-source',
        'native_qualifier_sha256': gate.sha(runtime / 'gorgequal-linux-amd64'),
        'registry_sha256': gate.sha(runtime / 'registry.gob.gz'), 'policies': policies,
        'policy_selection': selection, 'decks': gate.DECKS, 'fixed_seed_indices': list(range(blocks))})
    report = {'policies': policies, 'scheduled_games': blocks, 'rows': rows,
        'totals': {'Games': blocks, 'CompletedGames': 2 * blocks, **dict.fromkeys(gate.FAULTS, 0)},
        'gates': {'fixture': {'AgentNatives': 1000, 'ForcedNatives': 0, 'FallbackNatives': 0}},
        'policy_gates': {'fixture': {'AgentNatives': 1000, 'ForcedNatives': 0, 'FallbackNatives': 0}},
        'search_coverage': {deck + '/' + policy: {'Eligible': 1, 'Covered': 1, 'Redealt': 1,
            'ReconstructionBudgetExhausted': 0, 'RedealRefusals': {}}
            for deck in gate.DECKS for policy in policies if policy.startswith('search')}}
    write(callback / 'report.json', report)
    write(callback / 'RECEIPT.json', {'primary_sha256': gate.sha(primary), 'exit_code': 0, 'full_native_gate_passed': True})
    native_seal = seal(native)
    write(native / 'HOSTED-CLEANUP.json', {'recovery_seal_sha256': native_seal,
        'hosted_artifact_deletion_verified': True, 'draft_inputs_deletion_verified': True})
    pins = dict(seal_sha256=native_seal, runtime_seal_sha256=runtime_seal,
        cleanup_sha256=gate.sha(native / 'HOSTED-CLEANUP.json'))
    return native, runtime, pins


def test_complete_structural_fixture_and_byte_tampering(evidence):
    native, runtime, pins = evidence
    assert gate.verify_native_audit(native, runtime, **pins)['completed_games'] == 640
    (native / 'artifact/MANIFEST.json').write_text('{}')
    with pytest.raises(gate.NativeAuditGateError, match='differs from its seal'):
        gate.verify_native_audit(native, runtime, **pins)


def test_declared_policy_subset_passes_only_with_its_own_schedule(tmp_path):
    subset = gate.POLICIES[:10]
    native, runtime, pins = build_evidence(tmp_path, subset)
    verdict = gate.verify_native_audit(native, runtime, **pins)
    assert (verdict['policies'], verdict['seed_blocks'], verdict['completed_games']) == (subset, 280, 560)
    manifest = json.loads((native / 'artifact/MANIFEST.json').read_bytes())
    for change in ({'policy_selection': 'all'}, {'policy_selection': ','.join(reversed(subset))},
                   {'policies': list(reversed(subset)), 'policy_selection': ','.join(reversed(subset))},
                   {'fixed_seed_indices': list(range(320))}):
        write(native / 'artifact/MANIFEST.json', {**manifest, **change})
        pins['seal_sha256'] = seal(native)
        cleanup = json.loads((native / 'HOSTED-CLEANUP.json').read_bytes())
        write(native / 'HOSTED-CLEANUP.json', {**cleanup, 'recovery_seal_sha256': pins['seal_sha256']})
        pins['cleanup_sha256'] = gate.sha(native / 'HOSTED-CLEANUP.json')
        with pytest.raises(gate.NativeAuditGateError, match='^Audit'):
            gate.verify_native_audit(native, runtime, **pins)


def local_evidence(tmp_path):
    native, runtime, pins = build_evidence(tmp_path)
    (native / 'artifact').rename(native / 'native')
    (native / 'native/CLOSURE.json').rename(native / 'native/RECEIPT.json')
    (native / 'CI-TERMINAL.json').unlink()
    (native / 'HOSTED-CLEANUP.json').unlink()
    (runtime / 'gorgequal-windows-amd64.exe').write_bytes(b'fixture-only-windows-binary')
    (runtime / 'SEAL.json').unlink()
    pins['runtime_seal_sha256'] = seal(runtime)
    identity = dict(host='fixture-pc', lane='spellbench-gorge', work_id='fixture-native', generation=193)
    write(native / 'LOCAL-TERMINAL.json', dict(status='completed', exit_code=0, stop_reason=None,
        head_sha='launcher-source', execution_kind='local-windows-amd64', execution_id=identity))
    write(native / 'HOST-RELEASE.json', dict(execution_id=identity, token_fate='released', outcome='success',
        processes={'supervisor': dict(pid=123, creation_time=456, state='absent')},
        live_descendants=[], observation_errors=[]))
    write(native / 'CLOSURE.json', dict(native_passed=True, error=None, stop_reason=None, rated_games=0))
    write(native / 'RECOVERY.json', dict(native_qualification_passed=True, independent_recovery_verified=True,
        launcher_source_commit='launcher-source', execution_id=identity, rated_games=0))
    manifest_path = native / 'native/MANIFEST.json'
    manifest = json.loads(manifest_path.read_bytes())
    manifest['native_qualifier_sha256'] = gate.sha(runtime / 'gorgequal-windows-amd64.exe')
    manifest['runtime_seal_sha256'] = pins['runtime_seal_sha256']
    write(manifest_path, manifest)
    audit_path = native / 'native/NATIVE-AUDIT.json'
    audit = json.loads(audit_path.read_bytes())
    audit['full_report_path'] = r'D:\fixture\native\full-native-audit-3-workers-2\report.json'
    write(audit_path, audit)
    pins['seal_sha256'] = seal(native)
    write(native / 'LOCAL-CLEANUP.json', dict(recovery_seal_sha256=pins['seal_sha256'], execution_id=identity,
        host_release_verified=True, independent_recovery_verified=True))
    pins['cleanup_sha256'] = gate.sha(native / 'LOCAL-CLEANUP.json')
    return native, runtime, pins


def test_local_native_pass_keeps_actual_windows_qualifier_identity(tmp_path):
    native, runtime, pins = local_evidence(tmp_path)
    verdict = gate.verify_native_audit(native, runtime, **pins)
    assert verdict['execution_kind'] == 'local-windows-amd64'
    assert verdict['native_sha256'] == gate.sha(runtime / 'gorgequal-windows-amd64.exe')
    assert verdict['native_sha256'] != gate.sha(runtime / 'gorgequal-linux-amd64')


@pytest.mark.parametrize('mutation', ['failed_parent', 'live_process', 'unknown_process', 'no_processes',
    'unreleased', 'reclaimed', 'different_generation', 'descendants', 'observation_error', 'no_recovery',
    'fake_ci', 'linux_hash', 'runtime_seal', 'failed_closure', 'missing_release', 'missing_cleanup',
    'native_fault', 'native_refusal'])
def test_local_resealed_invalid_execution_or_native_proof_is_refused(tmp_path, mutation):
    native, runtime, pins = local_evidence(tmp_path)
    cleanup_path = native / 'LOCAL-CLEANUP.json'
    cleanup = json.loads(cleanup_path.read_bytes())
    cleanup_path.unlink()  # External seal binding, never self-seal the cleanup receipt.
    if mutation == 'missing_release':
        (native / 'HOST-RELEASE.json').unlink()
    elif mutation == 'fake_ci':
        write(native / 'CI-TERMINAL.json', dict(status='completed', conclusion='success'))
    else:
        path = {'failed_parent': 'native/RECEIPT.json', 'no_recovery': 'RECOVERY.json',
            'linux_hash': 'native/MANIFEST.json', 'runtime_seal': 'native/MANIFEST.json',
            'failed_closure': 'CLOSURE.json', 'native_fault': 'native/full-native-audit-3-workers-2/report.json',
            'native_refusal': 'native/full-native-audit-3-workers-2/report.json'}.get(mutation, 'HOST-RELEASE.json')
        value = json.loads((native / path).read_bytes())
        if mutation == 'failed_parent': value['exit_code'] = 1
        elif mutation == 'live_process': value['processes']['supervisor']['state'] = 'alive'
        elif mutation == 'unknown_process': value['processes']['supervisor']['state'] = 'unknown'
        elif mutation == 'no_processes': value['processes'] = {}
        elif mutation in ('unreleased', 'reclaimed'): value['token_fate'] = mutation
        elif mutation == 'different_generation': value['execution_id']['generation'] += 1
        elif mutation == 'descendants': value['live_descendants'] = [dict(pid=789)]
        elif mutation == 'observation_error': value['observation_errors'] = ['access denied']
        elif mutation == 'no_recovery': value['independent_recovery_verified'] = False
        elif mutation == 'linux_hash': value['native_qualifier_sha256'] = gate.sha(runtime / 'gorgequal-linux-amd64')
        elif mutation == 'runtime_seal': value['runtime_seal_sha256'] = 'another-runtime-seal'
        elif mutation == 'failed_closure': value['error'] = 'recovery failed'
        elif mutation == 'native_fault': value['totals']['LeakHits'] = 1
        elif mutation == 'native_refusal': value['search_coverage']['Burn/search-redeal']['RedealRefusals'] = {'fixture': 1}
        write(native / path, value)
    pins['seal_sha256'] = seal(native)
    if mutation != 'missing_cleanup':
        cleanup['recovery_seal_sha256'] = pins['seal_sha256']
        write(cleanup_path, cleanup)
        pins['cleanup_sha256'] = gate.sha(cleanup_path)
    with pytest.raises(gate.NativeAuditGateError):
        gate.verify_native_audit(native, runtime, **pins)


@pytest.mark.parametrize('mutation', ['failed_ci', 'missing_cleanup', 'incomplete_audit', 'different_source',
    'no_parallel', 'callback_failed', 'fault', 'missing_seed', 'mapping', 'zero_mapping_bad',
    'missing_search', 'refusal', 'no_redealt', 'changed_primary'])
def test_semantically_invalid_resealed_fixtures_are_refused(evidence, mutation):
    native, runtime, pins = evidence
    callback = native / 'artifact/full-native-audit-3-workers-2'
    if mutation == 'missing_cleanup':
        (native / 'HOSTED-CLEANUP.json').unlink()
    elif mutation == 'changed_primary':
        (callback / 'primary.jsonl').write_text('{}\n')
    else:
        path = {'failed_ci': native / 'CI-TERMINAL.json', 'incomplete_audit': native / 'artifact/NATIVE-AUDIT.json',
            'different_source': native / 'artifact/MANIFEST.json', 'no_parallel': native / 'artifact/ALLOCATION.json',
            'callback_failed': callback / 'RECEIPT.json'}.get(mutation, callback / 'report.json')
        value = json.loads(path.read_bytes())
        if mutation == 'failed_ci': value['conclusion'] = 'failure'
        elif mutation == 'incomplete_audit': value['seed_blocks'] = 319
        elif mutation == 'different_source': value['runtime_source_commit'] = 'another-source'
        elif mutation == 'no_parallel': value['outputs_identical'] = False
        elif mutation == 'callback_failed': value['full_native_gate_passed'] = False
        elif mutation == 'fault': value['totals']['ParityMismatch'] = 1
        elif mutation == 'missing_seed': value['rows'].pop()
        elif mutation == 'mapping': value['gates']['fixture']['ForcedNatives'] = 10
        elif mutation == 'zero_mapping_bad': value['gates']['fixture'].update(AgentNatives=0, ForcedNatives=1)
        elif mutation == 'missing_search': value['search_coverage']['Burn/search']['Covered'] = 0
        elif mutation == 'refusal': value['search_coverage']['Burn/search-redeal']['RedealRefusals'] = {'fixture': 1}
        elif mutation == 'no_redealt':
            for key, coverage in value['search_coverage'].items():
                if key.endswith('/search-redeal'): coverage['Redealt'] = 0
        write(path, value)
    # Preserve the original declared runtime. Reseal only the adversarial audit
    # fixture so these tests reach semantic gates rather than a byte mismatch.
    (native / 'SEAL.json').unlink()
    pins['seal_sha256'] = seal(native)
    if mutation != 'missing_cleanup':
        write(native / 'HOSTED-CLEANUP.json', {'recovery_seal_sha256': pins['seal_sha256'],
            'hosted_artifact_deletion_verified': True, 'draft_inputs_deletion_verified': True})
        pins['cleanup_sha256'] = gate.sha(native / 'HOSTED-CLEANUP.json')
    with pytest.raises(gate.NativeAuditGateError):
        gate.verify_native_audit(native, runtime, **pins)
