"""Supervised CI entry point for the unchanged, unrated gorge reference pool."""
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'python'))
from spellbench.arena import config, machine, runner
from spellbench.arena.allocation import Placement
from spellbench.bench import definition

from gorge_ci_exchange import DraftExchange, extract_pinned, sha
from gorge_native_gate import verify_native_audit
from gorge_reference_coordinator import coordinate
from gorge_reference_pool import PoolNode, portable_native_verdict
from gorge_reference_transport import snapshot_worker
from gorge_reference_worker import ReferenceWorker, write_new
from gorge_runtime_source import verify_runtime_source

REPOSITORY = 'jackmaiorino/spellbench'
BENCHMARK = '21359cfc5c288c797797f50449003c3a39e7aac1605502d365e7e3a11bbf1817'
REGISTRY = '42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937'
CAP = 2*2**30
RESERVE = 60*2**30
RECOVERY_CAP = 256*2**20
WALL = 5*3600
PRIVATE_KEYS = ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY')


def validate_inputs(value):
    if (value.get('schema') != 'spellbench-gorge-ci-reference-inputs/v1' or
            value.get('launch_authorized') is not True or value.get('scope') != 'reference qualification only' or
            value.get('repository_private') is not False or type(value.get('pool_slots')) is not int or
            value['pool_slots'] not in (2,4)):
        raise RuntimeError('Reference CI lacks the original bounded scope and actual dispatch admission')
    amount = value.get('conservative_reserved_total_usd')
    if type(amount) not in (int,float) or not math.isfinite(amount) or not 0 <= amount <= 10:
        raise RuntimeError('Reference CI does not fit the maintainer\'s all-in USD10 cap')
    for key in ('release_id','release_asset_id','archive_bytes','extracted_bytes'):
        if type(value.get(key)) is not int or value[key] <= 0:
            raise RuntimeError('Reference CI lacks an exact owned draft input asset')
    if value['archive_bytes'] > 256*2**20 or value['extracted_bytes'] > 512*2**20:
        raise RuntimeError('Reference input archive exceeds its declared budget')
    for key in ('archive_sha256','native_seal_sha256','runtime_seal_sha256','cleanup_sha256','billing_seal_sha256'):
        if type(value.get(key)) is not str or re.fullmatch('[0-9a-f]{64}',value[key]) is None:
            raise RuntimeError('Reference CI lacks exact input, native recovery or billing pins')
    if value.get('benchmark_sha256') != BENCHMARK or value.get('registry_sha256') != REGISTRY:
        raise RuntimeError('Reference benchmark or registry changed')
    if (type(value.get('runtime_source_commit')) is not str or
            re.fullmatch('[0-9a-f]{40}',value['runtime_source_commit']) is None):
        raise RuntimeError('Reference CI lacks the compiled source pin')
    Placement.parse(value['placement'])
    census = value.get('resource_census',{})
    if any(census.get(host,{}).get('checked') is not True for host in ('main-pc','computehost','runpod')):
        raise RuntimeError('Reference dispatch lacks actual checks of all required placements')
    files = value.get('files')
    if not isinstance(files,dict) or not files:
        raise RuntimeError('Reference input inventory is absent')
    # Count all node recovery archives and coordinator/scratch evidence, so the
    # coordinator can recover every worker without breaching its own cap.
    projected = (value['archive_bytes'] + value['extracted_bytes'] +
                 (value['pool_slots']+1)*RECOVERY_CAP + 64*2**20)
    if projected > CAP:
        raise RuntimeError('Complete reference recovery does not fit the unchanged scratch cap')
    return projected


def prepare(job, inputs, client):
    validate_inputs(inputs)
    if (os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or sys.platform != 'linux'):
        raise RuntimeError('Reference CI requires the declared standard public Linux runner')
    if client.api(f'repos/{REPOSITORY}')['private']:
        raise RuntimeError('Reference runner minutes are not admitted for a private repository')
    job = Path(job)
    if machine.free_bytes(job) < RESERVE+CAP or machine.usable_cpus() < 3 or (machine.total_memory() or 0) < 8*2**30:
        raise RuntimeError('Hosted runner cannot preserve the declared CPU, memory and storage budget')
    assets = client.assets()
    matches = [asset for asset in assets.values() if asset['id']==inputs['release_asset_id']]
    if len(matches)!=1 or matches[0]['size']!=inputs['archive_bytes'] or matches[0]['digest']!='sha256:'+inputs['archive_sha256']:
        raise RuntimeError('Reference source archive differs from the declared draft input')
    archive = client.download(matches[0],job/'inputs.zip',cap_bytes=256*2**20)
    extracted = job/'input'
    extract_pinned(archive,extracted,cap_bytes=inputs['extracted_bytes'])
    paths = {path.relative_to(extracted).as_posix():path for path in extracted.rglob('*') if path.is_file()}
    if set(paths)!=set(inputs['files']) or sum(path.stat().st_size for path in paths.values())!=inputs['extracted_bytes']:
        raise RuntimeError('Reference extraction differs from its exact inventory')
    for name,path in paths.items():
        pin = inputs['files'][name]
        if path.stat().st_size!=pin['bytes'] or sha(path)!=pin['sha256']:
            raise RuntimeError('Extracted reference evidence differs from its input pin')
    native,runtime = extracted/'native',extracted/'runtime'
    for name in ('spellbench-gorge-env-linux-amd64','spellbench-gorge-agent-linux-amd64'):
        path = runtime/name
        sealed = json.loads((runtime/'SEAL.json').read_bytes())['files'][name]
        if sha(path)!=sealed['sha256'] or path.stat().st_size!=sealed['bytes']:
            raise RuntimeError('A production reference executable differs from its runtime seal')
        path.chmod(0o700)
    verdict = verify_native_audit(native,runtime,seal_sha256=inputs['native_seal_sha256'],
        runtime_seal_sha256=inputs['runtime_seal_sha256'],cleanup_sha256=inputs['cleanup_sha256'])
    if verdict['runtime_source_commit']!=inputs['runtime_source_commit'] or sha(runtime/'registry.gob.gz')!=REGISTRY:
        raise RuntimeError('Compiled source or registry differs from the native pass')
    subprocess.run(['git','fetch','--depth=1','origin',inputs['runtime_source_commit']],cwd=SOURCE,check=True,timeout=90)
    source_binding = verify_runtime_source(SOURCE, inputs['runtime_source_commit'])
    write_new(job/'RUNTIME-SOURCE.json', source_binding)
    benchmark_path = SOURCE/'benchmarks/pauper-gorge/benchmark.json'
    if sha(benchmark_path)!=BENCHMARK:
        raise RuntimeError('The frozen original benchmark changed')
    benchmark = definition.load_benchmark(benchmark_path.parent)
    values = dict(GORGE_SPELLBENCH_ENV=str(runtime/'spellbench-gorge-env-linux-amd64'),
        GORGE_SPELLBENCH_AGENT=str(runtime/'spellbench-gorge-agent-linux-amd64'),
        GORGE_REGISTRY=str(runtime/'registry.gob.gz'),GORGE_REGISTRY_SHA256=REGISTRY)
    cfg = config.TournamentConfig.from_json(benchmark.tournament_config(str(job/'diagnostics')))
    cfg = runner.executed_config(cfg,lambda text:definition.substitute(text,values))
    if cfg.per_game_cores()!=3 or cfg.workers!=8:
        raise RuntimeError('Original per-game resources or configured worker bound changed')
    return cfg,verdict,native,runtime


def client_for(job, inputs, deadline):
    return DraftExchange(release_id=inputs['release_id'],scratch=Path(job)/'exchange',deadline=deadline)


def inner(args, inputs):
    # Save API credentials in the transport client before clearing the process
    # environment inherited by every native engine and agent.
    client = client_for(args.job,inputs,args.deadline+300)
    for key in PRIVATE_KEYS:
        os.environ.pop(key,None)
    os.environ['GOMAXPROCS']='1'
    cfg,verdict,native,runtime = prepare(args.job,inputs,client)
    stage = args.job/'results'/args.role
    stage.mkdir(parents=True)
    source_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip()
    if source_commit!=os.environ['GITHUB_SHA']:
        raise RuntimeError('Actual checkout differs from the dispatched source')
    facts = PoolNode(args.role,machine.usable_cpus(),machine.total_memory(),machine.free_bytes(args.job),
        source_commit,inputs['native_seal_sha256'],inputs['runtime_seal_sha256'])
    write_new(stage/'OWNER.json',dict(node=facts.__dict__,native_verdict=portable_native_verdict(verdict),rated_games=0))
    if args.role=='prepare':
        if os.environ.get('GITHUB_OUTPUT'):
            with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
                stream.write('nodes='+json.dumps([f'node-{i}' for i in range(inputs['pool_slots'])])+'\n')
        return 0
    if args.role=='coordinator':
        report = coordinate(source=SOURCE,source_commit=source_commit,cfg=cfg,stage=stage,
            client=client,inputs=inputs,native_verdict=verdict,clock=time.monotonic)
        for i in range(inputs['pool_slots']):
            client.wait_json(f'closed-node-{i}.json')
        return 0 if report['passed'] else 1
    from gorge_reference_transport import serve_node
    worker = ReferenceWorker(source=SOURCE,source_commit=source_commit,cfg=cfg,stage=stage,
        node_alias=args.role,pool_slots=inputs['pool_slots'],native_root=native,runtime=runtime,
        native_seal_sha256=inputs['native_seal_sha256'],runtime_seal_sha256=inputs['runtime_seal_sha256'],
        cleanup_sha256=inputs['cleanup_sha256'],deadline=args.deadline,clock=time.monotonic)
    serve_node(worker,client)
    return 0


def process_metrics(group):
    values = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            pid = int(path.name)
            if os.getpgid(pid)!=group:
                continue
            fields = (path/'stat').read_text().rsplit(')',1)[1].split()
            io = {}
            for line in (path/'io').read_text().splitlines():
                key,value = line.split(':',1)
                if key in ('read_bytes','write_bytes'):
                    io[key] = int(value)
            values.append(dict(pid=pid,cpu_ticks=int(fields[11])+int(fields[12]),
                rss_bytes=int(fields[21])*os.sysconf('SC_PAGE_SIZE'),io=io))
        except (OSError,ValueError,IndexError):
            continue
    return values


def stop_group(process):
    try:
        os.killpg(process.pid,signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass
    finally:
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass


def supervise(args, inputs):
    projected = validate_inputs(inputs)
    args.job.mkdir(parents=True)
    started = time.monotonic()
    args.deadline = started+WALL
    client = client_for(args.job,inputs,args.deadline+300)
    control = args.job/'SUPERVISION'
    control.mkdir()
    write_new(control/'ADMISSION.json',dict(inputs=inputs,projected_bytes=projected,cap_bytes=CAP,
        reserve_bytes=RESERVE,wall_cap_seconds=WALL,rated_games=0))
    stage = args.job/'results'/args.role
    command = [sys.executable,str(Path(__file__).resolve()),'--inner','--role',args.role,
        '--job',str(args.job),'--inputs',str(args.inputs),'--deadline',str(args.deadline)]
    reason = None
    with (control/'stdout.log').open('xb') as stdout,(control/'stderr.log').open('xb') as stderr:
        process = subprocess.Popen(command,cwd=SOURCE,stdout=stdout,stderr=stderr,start_new_session=True)
        try:
            while process.poll() is None:
                size = sum(path.stat().st_size for path in args.job.rglob('*') if path.is_file())
                result_size = sum(path.stat().st_size for path in stage.rglob('*') if path.is_file())
                supervision_size = sum(path.stat().st_size for path in control.rglob('*') if path.is_file())
                free = machine.free_bytes(args.job)
                if time.monotonic()>=args.deadline or (args.job/'STOP').exists():
                    reason = 'wall_or_owned_STOP'
                if size>CAP or free<RESERVE:
                    reason = 'storage_cap_or_reserve'
                if result_size>RECOVERY_CAP-32*2**20 or supervision_size>6*2**20:
                    reason = 'bounded_result_recovery_budget'
                record = dict(at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    elapsed_seconds=time.monotonic()-started,bytes=size,result_bytes=result_size,
                    supervision_bytes=supervision_size,free_bytes=free,
                    usable_cpus=machine.usable_cpus(),memory_limit_bytes=machine.total_memory(),
                    processes=process_metrics(process.pid),stop_reason=reason)
                with (control/'METRICS.jsonl').open('a') as stream:
                    stream.write(json.dumps(record)+'\n')
                # Only compact counters go to public CI logs, never private
                # requests, run secrets or credential-bearing environments.
                print(json.dumps({key:record[key] for key in ('at_utc','elapsed_seconds','bytes','stop_reason')}),flush=True)
                if reason:
                    break
                time.sleep(60)
        finally:
            stop_group(process)
    write_new(control/'CLOSURE.json',dict(exit_code=process.returncode,stop_reason=reason,
        elapsed_seconds=time.monotonic()-started,rated_games=0))
    if args.role!='prepare':
        existing = client.assets().get(f'recovery-{args.role}.zip')
        if existing is None:
            stage.mkdir(parents=True,exist_ok=True)
            owner_path = stage/'OWNER.json'
            if owner_path.is_file():
                owner = json.loads(owner_path.read_bytes())
            else:
                owner = dict(node=PoolNode(args.role,machine.usable_cpus(),machine.total_memory(),machine.free_bytes(args.job),
                    os.environ['GITHUB_SHA'],inputs['native_seal_sha256'],inputs['runtime_seal_sha256']).__dict__,
                    native_verdict=dict(closed=False))
            write_new(stage/'SUPERVISED-CLOSURE.json',json.loads((control/'CLOSURE.json').read_bytes()))
            existing = snapshot_worker(SimpleNamespace(stage=stage,node=PoolNode(**owner['node']),
                native_verdict=owner['native_verdict']),client)
        client.put_json(f'supervised-{args.role}.json',dict(recovery_asset_id=existing['id'],
            recovery_asset_digest=existing['digest'],exit_code=process.returncode,stop_reason=reason,rated_games=0))
    # Preserve the supervisor's process usage, stdout and stderr even if the
    # worker already closed its own archive or failed during input verification.
    owner_path = stage/'OWNER.json'
    if owner_path.is_file():
        owner = json.loads(owner_path.read_bytes())
    else:
        owner = dict(node=PoolNode(args.role,machine.usable_cpus(),machine.total_memory(),machine.free_bytes(args.job),
            os.environ['GITHUB_SHA'],inputs['native_seal_sha256'],inputs['runtime_seal_sha256']).__dict__,
            native_verdict=dict(closed=False))
    node = PoolNode(**{**owner['node'],'alias':args.role+'-supervision'})
    snapshot_worker(SimpleNamespace(stage=control,node=node,native_verdict=owner['native_verdict']),
        client,cap_bytes=8*2**20)
    return process.returncode if process.returncode else (1 if reason else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--role',required=True,choices=['prepare','coordinator','node-0','node-1','node-2','node-3'])
    parser.add_argument('--inner',action='store_true')
    parser.add_argument('--deadline',type=float)
    args = parser.parse_args()
    args.inputs = args.inputs.resolve()
    inputs = json.loads(args.inputs.read_bytes())
    validate_inputs(inputs)
    if args.role.startswith('node-') and int(args.role.split('-')[1])>=inputs['pool_slots']:
        raise RuntimeError('Worker lies outside the admitted node count')
    if args.inner:
        if args.deadline is None:
            raise RuntimeError('Inner worker needs its existing supervisor deadline')
        return inner(args,inputs)
    return supervise(args,inputs)


if __name__=='__main__':
    sys.exit(main())
