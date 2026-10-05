"""Recover a terminated owned local reference job without launching work."""
import argparse
from pathlib import Path
import sys
import shutil

from gorge_local_reference_result import verify_local_reference_result
from gorge_native_gate import verify_native_audit
from gorge_reference_pool import portable_native_verdict
from gorge_recover_local_native import CAP, RESERVE, inventory, mirror, owned_release, put, read, sha


def recover(*, hot, cold, runtime, runtime_recovery, runtime_seal_sha256,
            native, native_recovery, native_seal_sha256, native_cleanup_sha256,
            host, lane, work_id):
    hot, cold = Path(hot).resolve(), Path(cold).resolve()
    if hot == cold or hot.is_relative_to(cold) or cold.is_relative_to(hot):
        raise RuntimeError('Reference recovery needs two separate owned roots')
    if any(not p.is_dir() or p.is_symlink() or p.is_junction() for p in (hot, cold)):
        raise RuntimeError('Reference recovery roots must already be owned ordinary directories')
    inventory(hot); inventory(cold)
    # Prove actual termination and canonical release before any write or copy.
    release = owned_release(host, read(hot/'host-dispatch.json'), lane=lane, work_id=work_id)
    if any(shutil.disk_usage(p).free < RESERVE+CAP for p in (hot, cold)):
        raise RuntimeError('Reference recovery cannot preserve its storage reserve')
    pins = dict(seal_sha256=native_seal_sha256, runtime_seal_sha256=runtime_seal_sha256,
                cleanup_sha256=native_cleanup_sha256)
    first_native = verify_native_audit(native, runtime, **pins)
    second_native = verify_native_audit(native_recovery, runtime_recovery, **pins)
    if portable_native_verdict(first_native) != portable_native_verdict(second_native):
        raise RuntimeError('Reference recovery has different independent native proofs')
    closure = read(hot/'CLOSURE.json')
    if (hot/'reference/RECEIPT.json').exists():
        receipt = read(hot/'reference/RECEIPT.json')
    elif closure.get('error') and (hot/'reference/PARENT-FAILED.json').is_file():
        receipt = dict(exit_code=None, stop_reason=closure.get('stop_reason'), reference_passed=False)
    else:
        raise RuntimeError('Reference terminal receipt or explicit parent failure is missing')
    manifest = read(hot/'reference/MANIFEST.json' if (hot/'reference/MANIFEST.json').exists()
                    else hot/'PREPARATION.json')
    passed = (release['outcome'] == 'success' and receipt['exit_code'] == 0 and
        receipt.get('stop_reason') is None and receipt.get('reference_passed') is True and
        closure.get('reference_passed') is True and closure.get('error') is None and
        closure.get('stop_reason') is None)
    mirror(hot, cold)
    verified, failures = None, []
    if passed:
        try:
            first = verify_local_reference_result(hot/'reference', source=hot/'source',
                head_sha=manifest['source_commit'], native_verdict=first_native)
            second = verify_local_reference_result(cold/'reference', source=cold/'source',
                head_sha=manifest['source_commit'], native_verdict=second_native)
            if first != second:
                raise RuntimeError('Independent local reference verification differs')
            verified = first
        except Exception as error:
            passed = False
            failures.append(type(error).__name__+': '+str(error))
    terminal = dict(status='completed', exit_code=receipt['exit_code'], stop_reason=receipt.get('stop_reason'),
        head_sha=manifest['source_commit'], execution_kind='local-windows-reference',
        execution_id=release['execution_id'], at_utc=release['at_utc'], error=closure.get('error'))
    recovery = dict(reference_qualification_passed=passed, verification=verified, verification_failures=failures,
        native_audit_seal_sha256=native_seal_sha256, independent_recovery_verified=True,
        launcher_source_commit=manifest['source_commit'], execution_id=release['execution_id'], rated_games=0)
    for root in (hot, cold):
        put(root, 'LOCAL-TERMINAL.json', terminal)
        put(root, 'HOST-RELEASE.json', release)
        put(root, 'RECOVERY.json', recovery)
    files = mirror(hot, cold)
    seal = dict(files=files, source_of_record=str(cold), recovery_root=str(hot),
        independent_recovery_verified=True, bytes=sum(pin['bytes'] for pin in files.values()))
    for root in (hot, cold):put(root, 'SEAL.json', seal)
    seal_sha256 = sha(cold/'SEAL.json')
    cleanup = dict(recovery_seal_sha256=seal_sha256, execution_id=release['execution_id'],
        host_release_verified=True, independent_recovery_verified=True)
    for root in (hot, cold):put(root, 'LOCAL-CLEANUP.json', cleanup)
    return dict(seal_sha256=seal_sha256, cleanup_sha256=sha(cold/'LOCAL-CLEANUP.json'),
        reference_qualification_passed=passed, verification=verified,
        verification_failures=failures, independently_recovered=True, rated_games=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('hot', 'cold', 'runtime', 'runtime-recovery', 'native', 'native-recovery', 'host-tools'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('runtime-seal-sha256', 'native-seal-sha256', 'native-cleanup-sha256', 'lane', 'work-id'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.host_tools))
    import host_reservation_v1 as host
    import json
    print(json.dumps(recover(hot=args.hot, cold=args.cold, runtime=args.runtime,
        runtime_recovery=args.runtime_recovery, runtime_seal_sha256=args.runtime_seal_sha256,
        native=args.native, native_recovery=args.native_recovery, native_seal_sha256=args.native_seal_sha256,
        native_cleanup_sha256=args.native_cleanup_sha256, host=host, lane=args.lane, work_id=args.work_id)))


if __name__ == '__main__':main()
