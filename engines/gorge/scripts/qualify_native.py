"""Qualify native audit throughput before running all fixed-seed audit blocks.

Each block contains an audited game and its deterministic replay. This is
unrated adapter qualification. The full gorgequal gates remain authoritative.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

JOB = Path(os.environ.get('GORGE_JOB_ROOT','/workspace/gorge'))
SOURCE = Path(os.environ.get('GORGE_SOURCE_ROOT',str(JOB/'source')))
sys.path.insert(0,str(SOURCE/'python'))
from spellbench.arena import machine, store
from spellbench.arena.throughput import PlayedGame, plan_allocation, workload_id, check_reserve

STAGE = Path(os.environ['GORGE_CLOUD_STAGE'])
NATIVE = Path(os.environ['GORGE_NATIVE_QUALIFIER'])
REGISTRY = Path(os.environ.get('GORGE_REGISTRY',str(JOB/'runtime009/registry.gob.gz')))
REGISTRY_SHA = '42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937'
POLICIES = ['bot','bot-auto-pay','lethal-pressure','lethal-pressure-auto-pay','ar8','blocks',
            'explore','legacy','search','search-mana','search-redeal','search-mana-redeal']
DECKS = ['Wildfire','Rally','Spy','Burn','CawGates']
PAIRINGS = ['uniform/uniform','bot/lethal-pressure']+[p+'/uniform' for p in POLICIES]
GAMES = [(d,p,g) for d in DECKS for p in PAIRINGS for g in range(4)]

def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n')
    os.replace(temporary,path)

def assigned_free(path):
    free=machine.free_bytes(path)
    if Path(path).resolve().is_relative_to(Path('/workspace')):
        used=int(subprocess.check_output(['du','-s','-B','1','/workspace'],text=True,timeout=10).split()[0])
        return min(free,100_000_000_000-used)
    return free

def valid_completed(report):
    totals=report['totals']
    faults=['Halts','Truncations','Violations','DigestMismatch','ResampleFailures',
            'LeakHits','Inconsistent','ParityMismatch']
    return (totals['Games'] == len(report['rows']) and
            totals['CompletedGames'] == 2*len(report['rows']) and
            all(totals[k]==0 for k in faults) and
            all(row['classification']=='natural' and 'error' not in row for row in report['rows']))

def main():
    cap = int(os.environ.get('GORGE_NATIVE_WORKER_CAP','12'))
    if cap < 2:
        raise RuntimeError('Native audit worker cap must allow measured parallel collection')
    expected_native=os.environ['GORGE_NATIVE_QUALIFIER_SHA256']
    if sha(NATIVE)!=expected_native or sha(REGISTRY)!=REGISTRY_SHA:
        raise RuntimeError('Native audit input differs from its pin')
    manifest=json.loads((STAGE/'MANIFEST.json').read_bytes())
    manifest.update(native_qualifier_sha256=expected_native, registry_sha256=REGISTRY_SHA,
        unit='fixed-seed audit block containing two completed games', fixed_seed_indices=list(range(len(GAMES))),
        policies=POLICIES, decks=DECKS, games_per_deck_pairing=4, resample_every=7,
        native_run_secret='gorge-qualification-run-secret!!',
        guard_path='engines/gorge/scripts/qualify_native.py -> arena.throughput.plan_allocation -> bounded gorgequal callback',
        scope='native validator, determinism, leak, consistency, resample, intent parity, mapping and search gates; unrated')
    write(STAGE/'MANIFEST.json',manifest)
    trial=0
    def execute(workers,indices,label):
        nonlocal trial
        trial+=1
        directory=STAGE/f'{label}-{trial}-workers-{workers}'
        directory.mkdir()
        output=directory/'report.json'
        args=[str(NATIVE),'-games','4','-workers',str(workers),'-resample','7','-audit=true',
              '-progress','-registry',str(REGISTRY),'-registry-sha256',REGISTRY_SHA,'-out',str(output)]
        if indices is not None: args += ['-game-indices',','.join(str(i) for i in indices)]
        write(directory/'COMMAND.json',{'command':args,'GOMAXPROCS':workers,'at_utc':stamp()})
        if sha(NATIVE)!=expected_native or sha(REGISTRY)!=REGISTRY_SHA:
            raise RuntimeError('Native launch input changed')
        start=time.perf_counter()
        with (directory/'stdout.jsonl').open('xb') as out,(directory/'stderr.log').open('xb') as err:
            result=subprocess.run(args,env=dict(os.environ,GOMAXPROCS=str(workers)),stdout=out,stderr=err,timeout=2700)
        report=json.loads(output.read_bytes())
        if report['policies']!=POLICIES or report['scheduled_games']!=len(GAMES):
            raise RuntimeError('Native schedule differs from its declaration')
        selected=list(range(len(GAMES))) if indices is None else sorted(indices)
        if [r['game'] for r in report['rows']]!=selected:
            raise RuntimeError('Native audit omitted, duplicated or renumbered a fixed seed')
        if not valid_completed(report):
            raise RuntimeError('Native audited games and replays did not complete cleanly')
        primary=directory/'primary.jsonl'
        for row in report['rows']:
            index=row['game']
            deck,pairing,_=GAMES[index]
            if row['deck']!=deck or row['pairing']!=pairing:
                raise RuntimeError('Fixed seed names a different deck or pairing')
            store.append_ledger_row(primary,row)
        wall=time.perf_counter()-start
        write(directory/'RECEIPT.json',{'at_utc':stamp(),'workers':workers,'blocks':len(selected),
            'completed_games':2*len(selected),'wall_seconds':wall,'exit_code':result.returncode,
            'primary_sha256':sha(primary),'full_native_gate_passed':indices is None and result.returncode==0})
        print(json.dumps({'native_trial_closed':label,'blocks':len(selected),'completed_games':2*len(selected),
                          'workers':workers,'wall_seconds':wall,'exit_code':result.returncode,'at_utc':stamp()}),flush=True)
        return wall,report,directory,result.returncode
    def play(workers,positions):
        wall,report,directory,_=execute(workers,positions,'qualification')
        by_index={row['game']:row for row in report['rows']}
        played=[]
        for index in positions:
            row=by_index[index]
            canonical=store.canonical_bytes(row)+b'\n'
            played.append(PlayedGame(index=index,seconds=report['game_seconds'][str(index)],
                digest='sha256:'+hashlib.sha256(store.canonical_bytes(row)).hexdigest(),row_bytes=len(canonical)))
        return wall,tuple(played)
    # Include all four search modes on all five decks in the first24 blocks.
    order=sorted(range(len(GAMES)),key=lambda i:(not GAMES[i][1].startswith('search'),GAMES[i][2],i))
    placement=os.environ.get('GORGE_PLACEMENT') or ('main-pc=unavailable: peer XMage short guarded correctness claims retain their announced priority; '
               'haleyspc=unavailable: queued training-performance window retains priority per CODEX811; '
               'runpod=used: owned13.6-core CFS CPU allocation under separate gorge USD10 total cap, native audit worker cap12')
    facts=machine.machine_facts({'run_dir':STAGE,'pin_root':STAGE},memory=machine.total_memory,
        gpus=machine.nvidia_gpus,disk_free=assigned_free)
    workload=workload_id({'kind':'gorge-native-audit/v1','binary':expected_native,'registry':REGISTRY_SHA,
        'policies':POLICIES,'decks':DECKS,'games_per_pairing':4,'resample_every':7,'fixed_seed_indices':list(range(len(GAMES)))})
    allocation=plan_allocation(games_total=len(GAMES),cap=cap,per_game_cores=1,play=play,placement=placement,
        host=os.environ['SPELLBENCH_HOST_ALIAS'],sample=order,workload=workload,
        evidence=STAGE/'throughput-evidence.json',machine=facts,cap_bytes=2*2**30)
    write(STAGE/'ALLOCATION.json',allocation.to_json())
    if allocation.kind!='substantial' or allocation.outputs_identical is not True:
        raise RuntimeError('Native audit needs observed matched parallel scaling with identical primary rows')
    check_reserve(machine.machine_facts({'run_dir':STAGE,'pin_root':STAGE},memory=lambda:None,gpus=tuple,
        disk_free=assigned_free),allocation.budget.projected_bytes)
    wall,report,directory,exit_code=execute(allocation.workers,None,'full-native-audit')
    result={'schema':'spellbench-gorge-guarded-native-audit/v1','at_utc':stamp(),
        'passed':exit_code==0,'full_report_path':str(directory/'report.json'),'primary_sha256':sha(directory/'primary.jsonl'),
        'seed_blocks':len(report['rows']),'completed_games':report['totals']['CompletedGames'],
        'wall_seconds':wall,'allocation':allocation.to_json(),'rated_games':0}
    write(STAGE/'NATIVE-AUDIT.json',result)
    return exit_code

if __name__=='__main__':
    try:sys.exit(main())
    except BaseException as exc:
        if isinstance(exc,SystemExit):raise
        write(STAGE/'FAILED.json',{'at_utc':stamp(),'error_type':type(exc).__name__,'error':str(exc),'rated_games':0})
        raise
