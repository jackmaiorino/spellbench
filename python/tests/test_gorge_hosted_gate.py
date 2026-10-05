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
    runtime, native = tmp_path / 'runtime', tmp_path / 'native'
    runtime.mkdir(); native.mkdir()
    (runtime / 'gorgequal-linux-amd64').write_bytes(b'fixture-only-binary')
    (runtime / 'registry.gob.gz').write_bytes(b'fixture-only-registry')
    write(runtime / 'BUILD.json', {'source_commit': 'runtime-source'})
    runtime_seal = seal(runtime)
    rows = [{'game': i, 'classification': 'natural'} for i in range(320)]
    callback = native / 'artifact/full-native-audit-3-workers-2'
    callback.mkdir(parents=True)
    primary = callback / 'primary.jsonl'
    primary.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    allocation = {'kind': 'substantial', 'outputs_identical': True}
    write(native / 'CI-TERMINAL.json', {'status': 'completed', 'conclusion': 'success', 'id': 17, 'head_sha': 'launcher-source'})
    write(native / 'RECOVERY.json', {'native_qualification_passed': True, 'independent_recovery_verified': True,
        'github_run_id': 17, 'launcher_source_commit': 'launcher-source', 'rated_games': 0})
    write(native / 'artifact/NATIVE-AUDIT.json', {'passed': True, 'seed_blocks': 320, 'completed_games': 640,
        'rated_games': 0, 'allocation': allocation, 'full_report_path': '/remote/' + callback.name + '/report.json',
        'primary_sha256': gate.sha(primary)})
    write(native / 'artifact/ALLOCATION.json', allocation)
    write(native / 'artifact/CLOSURE.json', {'exit_code': 0, 'stop_reason': None, 'native_passed': True})
    write(native / 'artifact/MANIFEST.json', {'runtime_source_commit': 'runtime-source', 'source_commit': 'launcher-source',
        'native_qualifier_sha256': gate.sha(runtime / 'gorgequal-linux-amd64'),
        'registry_sha256': gate.sha(runtime / 'registry.gob.gz'), 'policies': gate.POLICIES,
        'decks': gate.DECKS, 'fixed_seed_indices': list(range(320))})
    report = {'policies': gate.POLICIES, 'scheduled_games': 320, 'rows': rows,
        'totals': {'Games': 320, 'CompletedGames': 640, **dict.fromkeys(gate.FAULTS, 0)},
        'gates': {'fixture': {'AgentNatives': 1000, 'ForcedNatives': 0, 'FallbackNatives': 0}},
        'policy_gates': {'fixture': {'AgentNatives': 1000, 'ForcedNatives': 0, 'FallbackNatives': 0}},
        'search_coverage': {deck + '/' + policy: {'Eligible': 1, 'Covered': 1, 'Redealt': 1,
            'ReconstructionBudgetExhausted': 0, 'RedealRefusals': {}}
            for deck in gate.DECKS for policy in gate.POLICIES if policy.startswith('search')}}
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
