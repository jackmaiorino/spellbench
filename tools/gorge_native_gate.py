"""Verify sealed native qualification before reference evaluation.

This consumes the actual full audit, canonical primary store, callback receipt,
allocation, runtime pins and terminal recovery receipt. Component cases never
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


def schedule_blocks(policies):
    """Seed blocks gorgequal schedules for an ordered policy selection."""
    probes = [name for name in ('search', 'search-mana') if name in policies]
    return len(DECKS) * 4 * (2 + len(policies) + len(probes))


def declared_policies(manifest):
    """Accept every mode or an explicit ordered subset declared before launch."""
    policies = manifest.get('policies')
    selection = manifest.get('policy_selection', 'all')
    if selection == 'all':
        if policies != POLICIES:
            raise NativeAuditGateError('Audit roster, decks or frozen seed indices differ')
        return POLICIES
    if (not isinstance(policies, list) or not policies or selection != ','.join(policies) or
            policies != [name for name in POLICIES if name in policies]):
        raise NativeAuditGateError('Audit policy subset is not an ordered declared selection')
    return policies


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def evidence_layout(root):
    """Keep the actual execution platform and its terminal evidence explicit."""
    root = Path(root)
    hosted = (root / 'CI-TERMINAL.json').is_file()
    local = (root / 'LOCAL-TERMINAL.json').is_file()
    if hosted == local:
        raise NativeAuditGateError('Exactly one hosted or local terminal receipt is required')
    if hosted:
        return dict(kind='hosted-linux-amd64', terminal='CI-TERMINAL.json',
            cleanup='HOSTED-CLEANUP.json', prefix='artifact/', parent='artifact/CLOSURE.json',
            qualifier='gorgequal-linux-amd64')
    return dict(kind='local-windows-amd64', terminal='LOCAL-TERMINAL.json',
        cleanup='LOCAL-CLEANUP.json', prefix='native/', parent='native/RECEIPT.json',
        qualifier='gorgequal-windows-amd64.exe')


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

    layout = evidence_layout(root)
    cleanup_path = root / layout['cleanup']
    if (not cleanup_path.resolve().is_relative_to(root) or cleanup_path.is_symlink() or
            cleanup_path.is_junction() or not cleanup_path.is_file() or sha(cleanup_path) != cleanup_sha256):
        raise NativeAuditGateError('Terminal cleanup receipt is absent or differs')
    cleanup = json.loads(cleanup_path.read_bytes())
    closed = json.loads(evidence('RECOVERY.json').read_bytes())
    terminal = json.loads(evidence(layout['terminal']).read_bytes())
    if (cleanup.get('recovery_seal_sha256') != seal_sha256 or terminal.get('status') != 'completed' or
            closed.get('native_qualification_passed') is not True or
            closed.get('independent_recovery_verified') is not True or
            closed.get('launcher_source_commit') != terminal.get('head_sha') or
            closed.get('rated_games') != 0):
        raise NativeAuditGateError('The exact attempt did not finish and recover a full native pass')
    if layout['kind'] == 'hosted-linux-amd64':
        if (terminal.get('conclusion') != 'success' or closed.get('github_run_id') != terminal.get('id') or
                cleanup.get('hosted_artifact_deletion_verified') is not True or
                cleanup.get('draft_inputs_deletion_verified') is not True):
            raise NativeAuditGateError('Hosted termination or cleanup is incomplete')
    else:
        release = json.loads(evidence('HOST-RELEASE.json').read_bytes())
        closure = json.loads(evidence('CLOSURE.json').read_bytes())
        identity = terminal.get('execution_id')
        processes = release.get('processes')
        if (terminal.get('execution_kind') != layout['kind'] or terminal.get('exit_code') != 0 or
                terminal.get('stop_reason') is not None or not isinstance(identity, dict) or
                identity.get('lane') != 'spellbench-gorge' or
                type(identity.get('generation')) is not int or identity['generation'] < 1 or
                not isinstance(identity.get('host'), str) or not identity['host'] or
                not isinstance(identity.get('work_id'), str) or not identity['work_id'] or
                any(value.get('execution_id') != identity for value in (closed, release, cleanup)) or
                release.get('token_fate') != 'released' or release.get('outcome') != 'success' or
                not isinstance(processes, dict) or not processes or
                any(type(p.get('pid')) is not int or p['pid'] <= 0 or
                    type(p.get('creation_time')) is not int or p['creation_time'] <= 0 or
                    p.get('state') != 'absent' for p in processes.values()) or
                release.get('live_descendants') != [] or release.get('observation_errors') != [] or
                cleanup.get('host_release_verified') is not True or
                cleanup.get('independent_recovery_verified') is not True or
                'github_run_id' in closed or closure.get('native_passed') is not True or
                closure.get('error') is not None or closure.get('stop_reason') is not None or
                closure.get('rated_games') != 0):
            raise NativeAuditGateError('Local termination, owned process absence or canonical release is incomplete')
    prefix = layout['prefix']
    native = json.loads(evidence(prefix + 'NATIVE-AUDIT.json').read_bytes())
    manifest = json.loads(evidence(prefix + 'MANIFEST.json').read_bytes())
    parent = json.loads(evidence(layout['parent']).read_bytes())
    allocation = json.loads(evidence(prefix + 'ALLOCATION.json').read_bytes())
    policies = declared_policies(manifest)
    blocks = schedule_blocks(policies)
    if (native.get('passed') is not True or native.get('seed_blocks') != blocks or
            native.get('completed_games') != 2 * blocks or native.get('rated_games') != 0):
        raise NativeAuditGateError('The full declared native pass is absent')
    if (allocation != native.get('allocation') or allocation.get('kind') != 'substantial' or
            allocation.get('outputs_identical') is not True):
        raise NativeAuditGateError('Matched serial/parallel allocation is absent or differs')
    if parent.get('exit_code') != 0 or parent.get('stop_reason') is not None or parent.get('native_passed') is not True:
        raise NativeAuditGateError('The contained parent did not terminate successfully')
    build = json.loads(pinned('BUILD.json').read_bytes())
    native_hash, registry_hash = sha(pinned(layout['qualifier'])), sha(pinned('registry.gob.gz'))
    if (manifest.get('runtime_source_commit') != build.get('source_commit') or
            manifest.get('source_commit') != terminal.get('head_sha') or
            manifest.get('native_qualifier_sha256') != native_hash or
            manifest.get('registry_sha256') != registry_hash):
        raise NativeAuditGateError('Audit source, production executable or registry pin differs')
    if (layout['kind'] == 'local-windows-amd64' and
            manifest.get('runtime_seal_sha256') != runtime_seal_sha256):
        raise NativeAuditGateError('Local audit names a different sealed production runtime')
    if manifest.get('decks') != DECKS or manifest.get('fixed_seed_indices') != list(range(blocks)):
        raise NativeAuditGateError('Audit roster, decks or frozen seed indices differ')
    # Windows receipts must remain readable after recovery on a Linux worker.
    directory = native['full_report_path'].replace('\\', '/').split('/')[-2]
    if re.fullmatch(r'full-native-audit-\d+-workers-\d+', directory) is None:
        raise NativeAuditGateError('Full report does not name a full-audit callback')
    prefix += directory + '/'
    report = json.loads(evidence(prefix + 'report.json').read_bytes())
    receipt = json.loads(evidence(prefix + 'RECEIPT.json').read_bytes())
    primary = evidence(prefix + 'primary.jsonl')
    if (sha(primary) != native.get('primary_sha256') or receipt.get('primary_sha256') != sha(primary) or
            receipt.get('exit_code') != 0 or receipt.get('full_native_gate_passed') is not True):
        raise NativeAuditGateError('Primary output hash or successful callback differs')
    totals, rows = report['totals'], report['rows']
    if (report.get('policies') != policies or report.get('scheduled_games') != blocks or
            totals.get('Games') != blocks or totals.get('CompletedGames') != 2 * blocks or
            any(totals.get(key) != 0 for key in FAULTS)):
        raise NativeAuditGateError('Native schedule, completion or original fault gate failed')
    if ([row['game'] for row in rows] != list(range(blocks)) or
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
    for policy in (name for name in policies if name.startswith('search')):
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
        execution_kind=layout['kind'], native_qualifier_name=layout['qualifier'],
        native_sha256=native_hash, registry_sha256=registry_hash, primary_sha256=sha(primary),
        seed_blocks=blocks, completed_games=2 * blocks, outputs_identical=True, closed=True,
        # Full-roster verdicts keep their original shape for existing bundles.
        **({} if policies == POLICIES else dict(policies=policies)))
