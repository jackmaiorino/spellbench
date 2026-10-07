"""Recover the exact released compute-host reference job to D/E; never launch work."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

if not __debug__:
    raise RuntimeError('This recovery tool requires Python assertions enabled')
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'python'))
from gorge_ci_exchange import sha
from gorge_native_gate import verify_native_audit
from gorge_reference_pool import portable_native_verdict
from gorge_recover_local_reference import recover

NATIVE = Path('E:/spellbench-gorge-hosted-native-20261005-107')
RUNTIME = Path('E:/spellbench-gorge-runtime-20261005-108')
HOT = Path('D:/e-scratch/spellbench-gorge-computehost-reference-20261006-111')
COLD = Path('E:/')/HOT.name
REMOTE_JOB = 'C:/mtg-node/spellbench-gorge-reference-20261006-111'
REMOTE_PARENT = 'C:/mtg-node/spellbench-gorge-launcher-20261006-111/parent-current.py'
PARENT_SHA = 'a4cd03ce0dc5c1c678a52ab1a6462a690f9618a22680826133a3971ca0841ce6'
CAP, RESERVE = 2*2**30, 60*2**30
# The compute host's SSH login (user@address) and its Python come from the environment.
SSH = os.environ.get('COMPUTE_HOST_SSH', 'compute-host')
PYTHON = os.environ.get('COMPUTE_HOST_PYTHON', 'python.exe')


def remote_python(source):
    encoded = base64.b64encode(source.encode()).decode()
    command = ("$script=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+
        "')); & '"+PYTHON+"' -B -c $script; if($LASTEXITCODE -ne 0){throw 'Owned recovery observation failed'}")
    argument = base64.b64encode(command.encode('utf-16le')).decode()
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=8', SSH, 'powershell.exe', '-NoProfile',
        '-NonInteractive', '-EncodedCommand', argument], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:]+result.stdout[-2000:])
    return json.loads(result.stdout)


def native_inputs():
    names = ('SEAL.json', 'HOSTED-CLEANUP.json')
    if any(not (NATIVE/name).is_file() for name in names):
        raise RuntimeError('Native107 positive terminal recovery is still pending')
    pins = dict(seal_sha256=sha(NATIVE/'SEAL.json'), cleanup_sha256=sha(NATIVE/'HOSTED-CLEANUP.json'),
        runtime_seal_sha256='411fa9f41914bfca0f04a72c4ed5899b8cbf14c5bb0a5a32af31b25b2f6c06a7')
    first = verify_native_audit(NATIVE, RUNTIME, **pins)
    second = verify_native_audit(Path('D:/e-scratch')/NATIVE.name,
        Path('D:/e-scratch')/RUNTIME.name, **pins)
    if portable_native_verdict(first) != portable_native_verdict(second):
        raise RuntimeError('Independent native inputs differ')
    return pins


def observe_release(unused_host, dispatch, *, lane, work_id):
    # The reservation token remains on the compute host. Its standard collector checks
    # canonical history, the exact generation and every owned process there.
    result = remote_python(f'''
import hashlib,json,pathlib,subprocess,sys
p=pathlib.Path({REMOTE_PARENT!r})
with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()=={PARENT_SHA!r}
r=subprocess.run([sys.executable,'-B',str(p),'--release-check'],capture_output=True,text=True,timeout=90)
if r.returncode:raise RuntimeError(r.stderr[-2000:])
print(r.stdout.strip())
''')
    identity = result['execution_id']
    if (identity['host'] != 'COMPUTEHOST' or identity['lane'] != lane or
            identity['work_id'] != work_id or identity['generation'] != dispatch['generation']):
        raise RuntimeError('the compute host release is not the exact copied reference execution')
    return result


def fetch_terminal():
    # Observe real terminal ownership before creating either local directory.
    record = remote_python(f'''
import hashlib,json,pathlib,sys,tarfile
sys.dont_write_bytecode=True
sys.path.insert(0,'C:/mtg-node/spellbench-gorge-staging-20261006-110')
sys.path.insert(0,'C:/mtg-node/spellbench-gorge-staging-20261006-110/source/tools')
import host_reservation_v1 as host
from gorge_recover_local_native import owned_release,inventory,put
root=pathlib.Path({REMOTE_JOB!r})
if not (root/'CLOSURE.json').is_file():raise RuntimeError('the compute host reference is not terminal')
dispatch=json.loads((root/'host-dispatch.json').read_bytes())
release=owned_release(host,dispatch,lane='spellbench-gorge',work_id='gorge-guarded-reference111')
assert release['execution_id']['host']=='COMPUTEHOST'
put(root,'HOST-RELEASE.json',release)
files=inventory(root)
archive=pathlib.Path('C:/mtg-node/spellbench-gorge-launcher-20261006-111/reference-recovery.tar')
metadata=archive.with_suffix('.json')
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
if archive.exists():
 record=json.loads(metadata.read_bytes())
 assert record['files']==files and record['sha256']==digest(archive)
else:
 with tarfile.open(archive,'x') as t:
  for name in sorted(files):t.add(root/name,arcname=name,recursive=False)
 record=dict(sha256=digest(archive),bytes=archive.stat().st_size,files=files,execution_id=release['execution_id'])
 metadata.write_text(json.dumps(record,indent=2)+'\\n',encoding='utf-8')
assert record['bytes'] <= {CAP+64*2**20}
print(json.dumps(record))
''')
    identity = record['execution_id']
    if (identity['host'] != 'COMPUTEHOST' or identity['lane'] != 'spellbench-gorge' or
            identity['work_id'] != 'gorge-guarded-reference111'):
        raise RuntimeError('Remote archive names a different execution')
    if any(shutil.disk_usage(p.parent).free < RESERVE+2*CAP for p in (HOT, COLD)):
        raise RuntimeError('Reference recovery cannot preserve its two-drive storage reserve')
    if HOT.exists() or COLD.exists():
        raise RuntimeError('Owned recovery roots already exist; inspect and resume that recovery')
    HOT.mkdir(); COLD.mkdir()
    archive = HOT/'TRANSPORT.tar'
    subprocess.run(['scp', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        SSH+':/C:/mtg-node/spellbench-gorge-launcher-20261006-111/reference-recovery.tar',
        'TRANSPORT.tar'], cwd=HOT, check=True, timeout=180)
    if sha(archive) != record['sha256'] or archive.stat().st_size != record['bytes']:
        raise RuntimeError('Recovered archive differs from its observed bytes')
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if (len(members) != len(record['files']) or {m.name for m in members} != set(record['files']) or
                any(not m.isfile() or not (HOT/m.name).resolve().is_relative_to(HOT.resolve()) or
                    m.size != record['files'][m.name]['bytes'] for m in members)):
            raise RuntimeError('Reference transport contains undeclared or escaping data')
        source.extractall(HOT, filter='data')
    for name, pin in record['files'].items():
        if sha(HOT/name) != pin['sha256']:
            raise RuntimeError('Extracted reference input differs: '+name)
    # Remove only the verified temporary transport file, leaving every original
    # job byte to the existing bounded inventory and independent recovery.
    archive.unlink()
    (HOT/'TRANSPORT-RECEIPT.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    try:
        pins = native_inputs()
    except RuntimeError as error:
        if not args.check_only:
            raise
        print(json.dumps(dict(ready=False, reason=str(error), recovery_started=False)))
        return
    if args.check_only:
        print(json.dumps(dict(native_inputs_ready=True, recovery_started=False)))
        return
    fetch_terminal()
    result = recover(hot=HOT, cold=COLD, runtime=RUNTIME,
        runtime_recovery=Path('D:/e-scratch')/RUNTIME.name,
        runtime_seal_sha256=pins['runtime_seal_sha256'], native=NATIVE,
        native_recovery=Path('D:/e-scratch')/NATIVE.name,
        native_seal_sha256=pins['seal_sha256'], native_cleanup_sha256=pins['cleanup_sha256'],
        host=None, lane='spellbench-gorge', work_id='gorge-guarded-reference111',
        release_observer=observe_release)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
