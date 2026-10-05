"""Verify sealed hosted native qualification before reference evaluation.

This consumes the actual full audit, canonical primary store, callback receipt,
allocation, runtime pins and hosted cleanup receipt. Component cases never
admit a reference run.
"""
import hashlib
import json
from pathlib import Path
import re

POLICIES = ['bot', 'bot-auto-pay', 'lethal-pressure', 'lethal-pressure-auto-pay', 'ar8', 'blocks',
            'explore', 'legacy', 'search', 'search-mana', 'search-redeal', 'search-mana-redeal']
DECKS = ['Wildfire', 'Rally', 'Spy', 'Burn', 'CawGates']
FAULTS = ['Halts', 'Truncations', 'Violations', 'DigestMismatch', 'ResampleFailures', 'LeakHits',
          'Inconsistent', 'ParityMismatch']


class NativeAuditGateError(RuntimeError):
    pass


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_native_audit(root, runtime, *, seal_sha256, runtime_seal_sha256, cleanup_sha256):
    root, runtime = Path(root).resolve(), Path(runtime).resolve()
    if not (root / 'SEAL.json').is_file() or sha(root / 'SEAL.json') != seal_sha256:
        raise NativeAuditGateError('Native attempt is not the declared sealed recovery')
    if not (runtime / 'SEAL.json').is_file() or sha(runtime / 'SEAL.json') != runtime_seal_sha256:
        raise NativeAuditGateError('Runtime is not the declared sealed production input')
    seal = json.loads((root / 'SEAL.json').read_bytes())
    runtime_seal = json.loads((runtime / 'SEAL.json').read_bytes())

    def sealed(base, index, relative):
        path = base / relative
        if (not path.resolve().is_relative_to(base) or path.is_symlink() or path.is_junction()
                or relative not in index['files']):
            raise NativeAuditGateError('Evidence is absent or escapes its sealed root: ' + relative)
        pin = index['files'][relative]
        if not path.is_file() or path.stat().st_size != pin['bytes'] or sha(path) != pin['sha256']:
            raise NativeAuditGateError('Evidence differs from its seal: ' + relative)
        return path

    def evidence(relative):
        return sealed(root, seal, relative)

    def pinned(name):
        return sealed(runtime, runtime_seal, name)

    cleanup_path = root / 'HOSTED-CLEANUP.json'
    if not cleanup_path.is_file() or sha(cleanup_path) != cleanup_sha256:
        raise NativeAuditGateError('Hosted cleanup receipt is absent or differs')
    cleanup = json.loads(cleanup_path.read_bytes())
    if (cleanup.get('recovery_seal_sha256') != seal_sha256 or
            cleanup.get('hosted_artifact_deletion_verified') is not True or
            cleanup.get('draft_inputs_deletion_verified') is not True):
        raise NativeAuditGateError('Hosted cleanup does not bind the recovered input and output')
    closed = json.loads(evidence('RECOVERY.json').read_bytes())
    terminal = json.loads(evidence('CI-TERMINAL.json').read_bytes())
    if (terminal.get('status') != 'completed' or terminal.get('conclusion') != 'success' or
            closed.get('native_qualification_passed') is not True or
            closed.get('independent_recovery_verified') is not True or
            closed.get('github_run_id') != terminal.get('id') or
            closed.get('launcher_source_commit') != terminal.get('head_sha') or
            closed.get('rated_games') != 0):
        raise NativeAuditGateError('The exact hosted attempt did not finish and recover a full native pass')
    native = json.loads(evidence('artifact/NATIVE-AUDIT.json').read_bytes())
    manifest = json.loads(evidence('artifact/MANIFEST.json').read_bytes())
    parent = json.loads(evidence('artifact/CLOSURE.json').read_bytes())
    allocation = json.loads(evidence('artifact/ALLOCATION.json').read_bytes())
    if (native.get('passed') is not True or native.get('seed_blocks') != 320 or
            native.get('completed_games') != 640 or native.get('rated_games') != 0):
        raise NativeAuditGateError('The full 320-block/640-game native pass is absent')
    if (allocation != native.get('allocation') or allocation.get('kind') != 'substantial' or
            allocation.get('outputs_identical') is not True):
        raise NativeAuditGateError('Matched serial/parallel allocation is absent or differs')
    if parent.get('exit_code') != 0 or parent.get('stop_reason') is not None or parent.get('native_passed') is not True:
        raise NativeAuditGateError('The contained parent did not terminate successfully')
    build = json.loads(pinned('BUILD.json').read_bytes())
    native_hash, registry_hash = sha(pinned('gorgequal-linux-amd64')), sha(pinned('registry.gob.gz'))
    if (manifest.get('runtime_source_commit') != build.get('source_commit') or
            manifest.get('source_commit') != terminal.get('head_sha') or
            manifest.get('native_qualifier_sha256') != native_hash or
            manifest.get('registry_sha256') != registry_hash):
        raise NativeAuditGateError('Audit source, production executable or registry pin differs')
    if (manifest.get('policies') != POLICIES or manifest.get('decks') != DECKS or
            manifest.get('fixed_seed_indices') != list(range(320))):
        raise NativeAuditGateError('Audit roster, decks or frozen seed indices differ')
    directory = Path(native['full_report_path']).parent.name
    if re.fullmatch(r'full-native-audit-\d+-workers-\d+', directory) is None:
        raise NativeAuditGateError('Full report does not name a full-audit callback')
    prefix = 'artifact/' + directory + '/'
    report = json.loads(evidence(prefix + 'report.json').read_bytes())
    receipt = json.loads(evidence(prefix + 'RECEIPT.json').read_bytes())
    primary = evidence(prefix + 'primary.jsonl')
    if (sha(primary) != native.get('primary_sha256') or receipt.get('primary_sha256') != sha(primary) or
            receipt.get('exit_code') != 0 or receipt.get('full_native_gate_passed') is not True):
        raise NativeAuditGateError('Primary output hash or successful callback differs')
    totals, rows = report['totals'], report['rows']
    if (report.get('policies') != POLICIES or report.get('scheduled_games') != 320 or
            totals.get('Games') != 320 or totals.get('CompletedGames') != 640 or
            any(totals.get(key) != 0 for key in FAULTS)):
        raise NativeAuditGateError('Native schedule, completion or original fault gate failed')
    if ([row['game'] for row in rows] != list(range(320)) or
            any(row.get('classification') != 'natural' or 'error' in row for row in rows)):
        raise NativeAuditGateError('A native seed is missing, reordered or non-natural')
    for section in ('gates', 'policy_gates'):
        if not report.get(section):
            raise NativeAuditGateError('Native mapping gate evidence is absent')
        for value in report[section].values():
            natives = value['AgentNatives']
            bad = value['ForcedNatives'] + value['FallbackNatives']
            if natives < 0 or bad < 0 or (100 * bad >= natives if natives else bad != 0):
                raise NativeAuditGateError('Native mapping fails its original one-percent gate')
    for policy in (name for name in POLICIES if name.startswith('search')):
        redealt = 0
        for deck in DECKS:
            value = report['search_coverage'][deck + '/' + policy]
            if value['Eligible'] <= 0 or value['Covered'] <= 0:
                raise NativeAuditGateError('Native search coverage is incomplete')
            redealt += value['Redealt']
            if policy.endswith('redeal') and (value['ReconstructionBudgetExhausted'] or value.get('RedealRefusals')):
                raise NativeAuditGateError('Public-root reconstruction refused or exhausted')
        if policy.endswith('redeal') and redealt == 0:
            raise NativeAuditGateError('The redeal policy accepted no redealt world')
    if [json.loads(line) for line in primary.read_bytes().splitlines()] != rows:
        raise NativeAuditGateError('Report and canonical primary store differ')
    return dict(native_root=str(root), native_seal_sha256=seal_sha256, cleanup_sha256=cleanup_sha256,
        runtime_root=str(runtime), runtime_seal_sha256=runtime_seal_sha256,
        runtime_source_commit=build['source_commit'], launcher_source_commit=terminal['head_sha'],
        native_sha256=native_hash, registry_sha256=registry_hash, primary_sha256=sha(primary),
        seed_blocks=320, completed_games=640, outputs_identical=True, closed=True)
