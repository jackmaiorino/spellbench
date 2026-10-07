"""Watch one exact reference CI run, recover to two roots, then delete hosting.

This watcher never reruns CI, changes an allocation, or starts games. Its
default polling backs off to fifteen minutes after unchanged observations.
"""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'python'))
from gorge_ci_exchange import DraftExchange, NAME, extract_pinned, sha
from gorge_native_gate import verify_native_audit
from gorge_reference_result import verify_reference_result
from gorge_reference_worker import write_new

REPOSITORY='jackmaiorino/spellbench'
RESERVE=60*2**30
CAP=4*2**30


def verify_archive(directory):
    inventory=json.loads((directory/'RECOVERY-INVENTORY.json').read_bytes())
    files={path.relative_to(directory).as_posix():path for path in directory.rglob('*') if path.is_file()}
    if set(files)!=set(inventory['files'])|{'RECOVERY-INVENTORY.json'}:
        raise RuntimeError('A worker archive differs from its complete recovery inventory')
    for name,pin in inventory['files'].items():
        if files[name].stat().st_size!=pin['bytes'] or sha(files[name])!=pin['sha256']:
            raise RuntimeError('A recovered worker file differs from its archive inventory')
    if inventory['rated_games']!=0:
        raise RuntimeError('Reference recovery contains out-of-scope rated work')
    return inventory


def mirror_and_seal(hot,cold):
    files={path.relative_to(hot).as_posix():dict(bytes=path.stat().st_size,sha256=sha(path))
           for path in hot.rglob('*') if path.is_file()}
    if sum(value['bytes'] for value in files.values())>CAP:
        raise RuntimeError('Reference recovery exceeds its admitted local storage cap')
    for name,pin in files.items():
        destination=cold/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            if destination.stat().st_size!=pin['bytes'] or sha(destination)!=pin['sha256']:
                raise RuntimeError('Existing independent reference recovery differs')
        else:
            shutil.copyfile(hot/name,destination)
        if sha(destination)!=pin['sha256']:
            raise RuntimeError('Independent reference recovery failed verification')
    seal=dict(files=files,source_of_record=str(cold),recovery_root=str(hot),
        bytes=sum(value['bytes'] for value in files.values()),independent_recovery_verified=True)
    for base in (hot,cold):
        write_new(base/'SEAL.json',seal)
    return sha(cold/'SEAL.json')


def recover_terminal(client, *, run, inputs, head_sha, hot, cold, source, log_runner=subprocess.run):
    if (run['status']!='completed' or run['head_sha']!=head_sha or run['run_attempt']!=1 or
            run['name']!='gorge guarded reference pool' or run['repository']['full_name']!=REPOSITORY):
        raise RuntimeError('Reference recovery does not name the original exact terminal workflow')
    write_new(hot/'CI-TERMINAL.json',run)
    assets=client.assets()
    if any(NAME.fullmatch(name) is None for name in assets):
        raise RuntimeError('Owned reference exchange contains an unsafe asset name')
    declared=[asset for asset in assets.values() if asset['id']==inputs['release_asset_id']]
    if (len(declared)!=1 or declared[0]['digest']!='sha256:'+inputs['archive_sha256'] or
            declared[0]['size']!=inputs['archive_bytes']):
        raise RuntimeError('Owned reference input asset changed before recovery')
    compressed=sum(asset['size'] for asset in assets.values())
    role_caps=sum(8*2**20 if name.endswith('-supervision.zip') else 256*2**20
                  for name in assets if name.startswith('recovery-') and name.endswith('.zip'))
    projected=compressed+role_caps+inputs['extracted_bytes']+64*2**20
    if projected>CAP or any(shutil.disk_usage(base).free<RESERVE+projected for base in (hot,cold)):
        raise RuntimeError('Complete reference recovery cannot preserve its storage cap and reserve')
    write_new(hot/'RECOVERY-ADMISSION.json',dict(projected_bytes=projected,cap_bytes=CAP,reserve_bytes=RESERVE))
    write_new(hot/'ASSET-METADATA.json',list(assets.values()))
    downloads=hot/'assets'
    downloads.mkdir()
    roles=hot/'roles'
    roles.mkdir()
    for name,asset in assets.items():
        budget=256*2**20 if name.endswith('.zip') else 2*2**20
        path=client.download(asset,downloads/name,cap_bytes=budget)
        if name.startswith('recovery-') and name.endswith('.zip'):
            role=name[len('recovery-'):-len('.zip')]
            cap=8*2**20 if role.endswith('-supervision') else 256*2**20
            extract_pinned(path,roles/role,cap_bytes=cap)
            verify_archive(roles/role)
    bundle=hot/'input'
    extract_pinned(downloads/declared[0]['name'],bundle,cap_bytes=inputs['extracted_bytes'])
    paths={path.relative_to(bundle).as_posix():path for path in bundle.rglob('*') if path.is_file()}
    if set(paths)!=set(inputs['files']) or any(sha(paths[name])!=pin['sha256'] or
        paths[name].stat().st_size!=pin['bytes'] for name,pin in inputs['files'].items()):
        raise RuntimeError('Recovered reference source inputs differ from their complete pins')
    with (hot/'WORKFLOW.log').open('xb') as output:
        log_runner(['gh','run','view',str(run['id']),'--repo',REPOSITORY,'--log'],
            env=client.api_env,stdout=output,stderr=subprocess.PIPE,check=True,timeout=180)
    if (hot/'WORKFLOW.log').stat().st_size>64*2**20:
        raise RuntimeError('Reference terminal workflow log exceeds its recovery budget')
    failures=[]
    passed=False
    verification=None
    if run['conclusion']=='success':
        try:
            verdict=verify_native_audit(bundle/'native',bundle/'runtime',seal_sha256=inputs['native_seal_sha256'],
                runtime_seal_sha256=inputs['runtime_seal_sha256'],cleanup_sha256=inputs['cleanup_sha256'])
            required=['coordinator',*[f'node-{i}' for i in range(inputs['pool_slots'])]]
            for role in required:
                terminal=json.loads((downloads/f'supervised-{role}.json').read_bytes())
                if (terminal['exit_code']!=0 or terminal['stop_reason'] is not None or terminal['rated_games']!=0 or
                        terminal['recovery_asset_digest']!=assets[f'recovery-{role}.zip']['digest']):
                    raise RuntimeError('A reference role did not terminate and recover successfully')
                if not (roles/(role+'-supervision')/'CLOSURE.json').is_file():
                    raise RuntimeError('A reference role lacks its actual supervisor closure')
                closure=json.loads((roles/(role+'-supervision')/'CLOSURE.json').read_bytes())
                if closure['exit_code']!=0 or closure['stop_reason'] is not None:
                    raise RuntimeError('A reference supervisor stopped or failed its original role')
            verification=verify_reference_result(roles/'coordinator',source=source,inputs=inputs,
                head_sha=head_sha,native_verdict=verdict)
            passed=verification['passed']
        except Exception as error:
            failures.append(type(error).__name__+': '+str(error))
    else:
        failures.append('Original reference workflow ended with '+str(run['conclusion']))
    record=dict(github_run_id=run['id'],launcher_source_commit=head_sha,conclusion=run['conclusion'],
        reference_qualification_passed=passed,verification=verification,verification_failures=failures,
        independent_recovery_verified=True,hosted_exchange_deleted=False,
        conservative_reserved_total_usd=inputs['conservative_reserved_total_usd'],provider_settlement_pending=True,rated_games=0)
    write_new(hot/'RECOVERY.json',record)
    # Keep the exact consumer implementation with the recovered terminal record.
    shutil.copyfile(Path(__file__),hot/'WATCHER.py')
    shutil.copyfile(Path(source)/'tools/gorge_reference_result.py',hot/'RESULT-VERIFIER.py')
    seal=mirror_and_seal(hot,cold)
    # Delete only this already recovered, still unpublished owned exchange.
    metadata=client.api(f'repos/{REPOSITORY}/releases/{client.release_id}')
    if metadata['draft'] is not True or metadata['published_at'] is not None:
        raise RuntimeError('Reference exchange is no longer the owned unpublished draft')
    client.api_runner(['gh','api',f'repos/{REPOSITORY}/releases/{client.release_id}','--method','DELETE'],
        env=client.api_env,capture_output=True,check=True,timeout=90)
    absent=client.api_runner(['gh','api',f'repos/{REPOSITORY}/releases/{client.release_id}'],
        env=client.api_env,capture_output=True,timeout=60)
    if absent.returncode==0 or b'404' not in absent.stderr:
        raise RuntimeError('Recovered reference exchange deletion is not verified')
    cleanup=dict(recovery_seal_sha256=seal,exchange_release_id=client.release_id,
        hosted_exchange_deletion_verified=True,reference_qualification_passed=passed,rated_games=0)
    for base in (hot,cold):
        write_new(base/'HOSTED-CLEANUP.json',cleanup)
    if sha(hot/'HOSTED-CLEANUP.json')!=sha(cold/'HOSTED-CLEANUP.json'):
        raise RuntimeError('Reference cleanup receipts did not recover identically')
    return record,cleanup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--run-id',type=int,required=True)
    parser.add_argument('--head-sha',required=True)
    parser.add_argument('--hot',type=Path,required=True)
    parser.add_argument('--cold',type=Path,required=True)
    args=parser.parse_args()
    if args.run_id<=0 or re.fullmatch('[0-9a-f]{40}',args.head_sha) is None:
        raise RuntimeError('Watcher requires the exact original run and source')
    spec=importlib.util.spec_from_file_location('gorge_reference_ci_controls',SOURCE/'tools/gorge-reference-ci.py')
    controls=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controls)
    inputs=json.loads(args.inputs.read_bytes())
    controls.validate_inputs(inputs)
    hot,cold=args.hot.resolve(),args.cold.resolve()
    if hot==cold or hot.exists() or cold.exists():
        raise RuntimeError('Watcher requires two new owned recovery roots; never duplicate an existing watcher')
    if any(shutil.disk_usage(base.parent).free<RESERVE+CAP for base in (hot,cold)):
        raise RuntimeError('Reference watcher cannot preserve its declared recovery reserve')
    for base in (hot,cold):
        base.mkdir(parents=True)
        write_new(base/'OWNER.json',dict(pid=os.getpid(),run_id=args.run_id,head_sha=args.head_sha,
            scope='Watch/recover exact original reference run only; no rerun, allocation or games'))
    write_new(hot/'INPUTS.json',inputs)
    client=DraftExchange(release_id=inputs['release_id'],scratch=hot/'exchange',deadline=time.monotonic()+12*3600)
    previous=None
    unchanged=0
    while True:
        run=client.api(f'repos/{REPOSITORY}/actions/runs/{args.run_id}')
        if run['head_sha']!=args.head_sha or run['run_attempt']!=1:
            raise RuntimeError('Watcher refuses a changed run or rerun')
        current=(run['status'],run['conclusion'])
        if current!=previous:
            print(json.dumps(dict(run_id=args.run_id,status=run['status'],conclusion=run['conclusion'])),flush=True)
            unchanged=0
        else:
            unchanged+=1
        previous=current
        if run['status']=='completed':
            break
        time.sleep(min(60 if unchanged==0 else (300 if unchanged==1 else 900),client.remaining()))
    record,cleanup=recover_terminal(client,run=run,inputs=inputs,head_sha=args.head_sha,hot=hot,cold=cold,source=SOURCE)
    print(json.dumps(dict(run_id=args.run_id,reference_qualification_passed=record['reference_qualification_passed'],
                         failures=record['verification_failures'],cleanup=cleanup)),flush=True)


if __name__=='__main__':
    main()
