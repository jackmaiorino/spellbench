"""Recover one terminal local native attempt; never launch or stop a process."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from gorge_native_gate import sha, verify_native_audit

CAP = 2 * 2**30
RESERVE = 60 * 2**30


def read(path):
    return json.loads(Path(path).read_bytes())


def owned_release(host, dispatch, *, lane, work_id):
    """Observe this reservation's fate, not merely an empty current lock."""
    token = dispatch['token']  # Kept internal; never return it or raw events.
    snapshot = host.status(token)
    if snapshot.get('test_root') is not False or snapshot.get('token_fate') != 'released':
        raise RuntimeError('The exact production reservation has not released')
    histories = [row for row in host._history(None) if row['token'] == token]
    if len(histories) != 1 or histories[0]['fate'] != 'released':
        raise RuntimeError('Canonical released reservation record is ambiguous')
    record = read(histories[0]['path'])
    identity = {name: record[name] for name in ('host', 'lane', 'work_id', 'generation')}
    if (identity['lane'] != lane or identity['work_id'] != work_id or
            identity['generation'] != dispatch['generation'] or record['token'] != token):
        raise RuntimeError('Released reservation belongs to a different execution')
    events, errors = host.read_events(token)
    releases = [event for event in events if event['kind'] == 'release']
    roots = tuple(dict.fromkeys(host._work_roots(events)))
    if errors or len(releases) != 1 or not roots:
        raise RuntimeError('Canonical release or owned process evidence is incomplete')
    processes = {str(i): dict(pid=pid, creation_time=creation, state=host.process_state(pid, creation))
                 for i, (pid, creation) in enumerate(roots)}
    descendants = host.live_descendants(roots)
    if any(value['state'] != 'absent' for value in processes.values()) or descendants:
        raise RuntimeError('Owned processes or descendants remain live or unknown')
    return dict(execution_id=identity, token_fate='released', outcome=releases[0]['outcome'],
        at_utc=releases[0]['at'], processes=processes, live_descendants=[], observation_errors=[])


def inventory(root):
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
            raise RuntimeError('Recovery contains an escaping or linked path')
        if path.is_file() and path.relative_to(root).as_posix() not in ('SEAL.json', 'LOCAL-CLEANUP.json'):
            files[path.relative_to(root).as_posix()] = dict(bytes=path.stat().st_size, sha256=sha(path))
    if sum(pin['bytes'] for pin in files.values()) > CAP:
        raise RuntimeError('Local native recovery exceeds its storage cap')
    return files


def put(root, name, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8')
    path = root / name
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError('Existing local recovery receipt differs: ' + name)
    else:
        with path.open('xb') as stream:
            stream.write(data)


def mirror(hot, cold):
    files = inventory(hot)
    copied = inventory(cold)
    if any(name not in files or pin != files[name] for name, pin in copied.items()):
        raise RuntimeError('Existing independent native recovery differs')
    for name, pin in files.items():
        source, destination = hot / name, cold / name
        if destination.exists():
            if destination.stat().st_size != pin['bytes'] or sha(destination) != pin['sha256']:
                raise RuntimeError('Existing independent native recovery differs: ' + name)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    if inventory(cold) != files:
        raise RuntimeError('Independent native inventory differs')
    return files


def recover(*, hot, cold, runtime, runtime_recovery, runtime_seal_sha256, host, lane, work_id):
    hot, cold = Path(hot).resolve(), Path(cold).resolve()
    if hot == cold or hot.is_relative_to(cold) or cold.is_relative_to(hot):
        raise RuntimeError('Recovery needs two separate owned roots')
    if any(not root.is_dir() or root.is_symlink() or root.is_junction() for root in (hot, cold)):
        raise RuntimeError('Recovery roots must already be owned ordinary directories')
    inventory(hot)
    inventory(cold)
    # All liveness observations precede any write or copy. An observation
    # failure never terminates, reclaims, releases or restarts this job.
    release = owned_release(host, read(hot / 'host-dispatch.json'), lane=lane, work_id=work_id)
    if any(shutil.disk_usage(root).free < RESERVE + CAP for root in (hot, cold)):
        raise RuntimeError('Local recovery cannot preserve the storage reserve')
    for root in (Path(runtime), Path(runtime_recovery)):
        if sha(root / 'SEAL.json') != runtime_seal_sha256:
            raise RuntimeError('Production runtime recovery seal differs')
        for name, pin in read(root / 'SEAL.json')['files'].items():
            path = root / name
            if (not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or path.is_junction() or
                    path.stat().st_size != pin['bytes'] or sha(path) != pin['sha256']):
                raise RuntimeError('Production runtime recovery bytes differ')
    closure = read(hot / 'CLOSURE.json')
    if (hot / 'native/RECEIPT.json').exists():
        receipt = read(hot / 'native/RECEIPT.json')
    elif closure.get('error') and (hot / 'native/PARENT-FAILED.json').is_file():
        # Preserve an unknown child exit code after a recorded parent failure.
        # Canonical release proves termination, not a successful native result.
        receipt = dict(exit_code=None, stop_reason=closure.get('stop_reason'), native_passed=False)
    else:
        raise RuntimeError('Terminal parent receipt or explicit parent failure is missing')
    manifest = read(hot / 'native/MANIFEST.json' if (hot / 'native/MANIFEST.json').exists()
                    else hot / 'PREPARATION.json')
    native = read(hot / 'native/NATIVE-AUDIT.json') if (hot / 'native/NATIVE-AUDIT.json').exists() else {}
    passed = (release['outcome'] == 'success' and receipt['exit_code'] == 0 and
        receipt.get('stop_reason') is None and receipt.get('native_passed') is True and
        closure.get('native_passed') is True and closure.get('error') is None and
        closure.get('stop_reason') is None and native.get('passed') is True)
    mirror(hot, cold)
    terminal = dict(status='completed', exit_code=receipt['exit_code'], stop_reason=receipt.get('stop_reason'),
        head_sha=manifest['source_commit'], execution_kind='local-windows-amd64',
        execution_id=release['execution_id'], at_utc=release['at_utc'], error=closure.get('error'))
    recovery = dict(native_qualification_passed=passed, independent_recovery_verified=True,
        launcher_source_commit=manifest['source_commit'], execution_id=release['execution_id'], rated_games=0)
    for root in (hot, cold):
        put(root, 'LOCAL-TERMINAL.json', terminal)
        put(root, 'HOST-RELEASE.json', release)
        put(root, 'RECOVERY.json', recovery)
    files = mirror(hot, cold)
    seal = dict(files=files, source_of_record=str(cold), recovery_root=str(hot),
        independent_recovery_verified=True, bytes=sum(pin['bytes'] for pin in files.values()))
    for root in (hot, cold):
        put(root, 'SEAL.json', seal)
    seal_sha256 = sha(cold / 'SEAL.json')
    cleanup = dict(recovery_seal_sha256=seal_sha256, execution_id=release['execution_id'],
        host_release_verified=True, independent_recovery_verified=True)
    for root in (hot, cold):
        put(root, 'LOCAL-CLEANUP.json', cleanup)
    pins = dict(seal_sha256=seal_sha256, runtime_seal_sha256=runtime_seal_sha256,
        cleanup_sha256=sha(cold / 'LOCAL-CLEANUP.json'))
    if passed:
        first = verify_native_audit(hot, runtime, **pins)
        second = verify_native_audit(cold, runtime_recovery, **pins)
        for key in ('native_root', 'runtime_root'):
            first.pop(key); second.pop(key)
        if first != second:
            raise RuntimeError('Recovered native admission differs')
    return dict(**pins, native_qualification_passed=passed, independently_recovered=True, rated_games=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('hot', 'cold', 'runtime', 'runtime-recovery', 'host-tools'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('runtime-seal-sha256', 'lane', 'work-id'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.host_tools))
    import host_reservation_v1 as host
    print(json.dumps(recover(hot=args.hot, cold=args.cold, runtime=args.runtime,
        runtime_recovery=args.runtime_recovery, runtime_seal_sha256=args.runtime_seal_sha256,
        host=host, lane=args.lane, work_id=args.work_id)))


if __name__ == '__main__':
    main()
