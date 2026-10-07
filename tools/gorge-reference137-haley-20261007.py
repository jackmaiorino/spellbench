"""Haley-only contained reference qualification of the natively qualified gorge modes.

This parent retains the exact source archive and production runtime130 and plays
only the original matrix games whose native seats name modes in the recovered
native134 verdict. Success still requires terminal release and independent E/D recovery.
"""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
if not __debug__: raise RuntimeError('This guarded launcher requires Python assertions enabled')
INPUT=Path('C:/mtg-node/spellbench-gorge-haley-staging-20261007-133')
JOB=Path('C:/mtg-node/spellbench-gorge-haley-reference-20261007-137');STAGE=JOB/'reference'
REPO=JOB/'source';RUNTIME=INPUT/'runtime';SCRIPT=REPO/'engines/gorge/scripts/reference_matrix.py'
PROOF=Path('C:/mtg-node/spellbench-gorge-reference-proof-20261007-135')
SOURCE_INPUT=Path('C:/mtg-node/spellbench-gorge-reference-source-20261007-136')
WALL=21600;CAP=2*2**30;RESERVE=60*2**30
with (INPUT/'host_reservation_v1.py').open('rb') as stream:
 assert hashlib.file_digest(stream,'sha256').hexdigest()=='a736f9cc617db898aba1b150eb92193cae80dd500cbd5419a6e0867eeb5a9570'
sys.dont_write_bytecode=True
sys.path.insert(0,str(INPUT));import host_reservation_v1 as host
assert os.name=='nt' and host.HOST=='HALEYSPC','This launcher only claims Haley'

def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_bytes())
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8',newline='\n')
def check():
 if not (PROOF/'BUNDLE.json').is_file():
  raise RuntimeError('Native134 positive bundle absent; no Haley job created')
 assert args.bundle_sha256 and sha(PROOF/'BUNDLE.json')==args.bundle_sha256
 bundle=read(PROOF/'BUNDLE.json')
 assert bundle['independent_recovery_verified'] is True and bundle['rated_games']==0
 assert bundle['runtime_seal_sha256']=='2f92a15a12d0154184a99e202914e7ef6e6f96af3a4f55693493709879bf1482'
 assert sha(RUNTIME/'SEAL.json')==bundle['runtime_seal_sha256']
 sys.path.insert(0,str(INPUT/'source/tools'));sys.path.insert(0,str(INPUT/'source/python'))
 from gorge_native_gate import verify_native_audit
 from gorge_reference_pool import portable_native_verdict
 verdict=verify_native_audit(PROOF/'input/native',RUNTIME,seal_sha256=bundle['native_seal_sha256'],
  runtime_seal_sha256=bundle['runtime_seal_sha256'],cleanup_sha256=bundle['cleanup_sha256'])
 assert portable_native_verdict(verdict)==bundle['native_verdict']
 assert args.source_record_sha256 and sha(SOURCE_INPUT/'SOURCE.json')==args.source_record_sha256
 source=read(SOURCE_INPUT/'SOURCE.json')
 assert source['runtime_seal_sha256']==bundle['runtime_seal_sha256']
 assert source['source_binding']['compiled_gorge_source_identical'] is True
 assert sha(SOURCE_INPUT/'source.tar')==source['source_archive_sha256']
 assert verdict['policies']==bundle['native_verdict']['policies'] and verdict['closed'] is True
 return dict(native_verdict=portable_native_verdict(verdict),source_binding=source['source_binding'],
  source_commit=source['source_commit'],source_archive_sha256=source['source_archive_sha256'],
  source_record_sha256=args.source_record_sha256)

def placement_check():
 assert args.census and args.placement
 census_path=Path(args.census);census=read(census_path)
 now=datetime.datetime.now(datetime.timezone.utc)
 for record in [census,census['Jack'],census['Haley'],census['RunPod']]:
  checked=datetime.datetime.fromisoformat(record['checked_at_utc'].replace('Z','+00:00'))
  assert 0 <= (now-checked).total_seconds() <= 300,'Placement census must be refreshed'
 assert not census['Haley']['host_lock_exists'] and host.status()['state']=='free'
 assert census['RunPod']['inventory_status']=='HTTP200'
 assert census['budget']['conservative_reserved_total_usd']==9.99736347
 from spellbench.arena.allocation import Placement
 placement=Placement.parse(args.placement)
 assert [entry.machine for entry in placement.entries if entry.disposition=='used']==['haleyspc'],'This recipe claims Haley only'
 return census_path

def prepare():
 proof=check() # Actual positive proof before creating the owned job root.
 assert proof['native_verdict']['closed'] is True
 assert not JOB.exists() and host.status()['state']=='free'
 census_path=placement_check()
 from spellbench.arena import machine
 from spellbench.bench.definition import load_benchmark
 benchmark=load_benchmark(INPUT/'source/benchmarks/pauper-gorge')
 cores=machine.usable_cpus()
 rules=benchmark.qualification_rules()
 bound=max(n for n in range(2,min(8,cores//3)+1) if rules.ladder_fits(120,n))
 assert all(shutil.disk_usage(p).free>RESERVE+CAP for p in (JOB.parent,))
 JOB.mkdir();STAGE.mkdir();(STAGE/'runtime').mkdir()
 build=read(RUNTIME/'BUILD.json');files={}
 for name in ('spellbench-gorge-env-windows-amd64.exe','spellbench-gorge-agent-windows-amd64.exe','registry.gob.gz','REGISTRY.json'):
  pin=read(RUNTIME/'SEAL.json')['files'][name];assert sha(RUNTIME/name)==pin['sha256']
  shutil.copyfile(RUNTIME/name,STAGE/'runtime'/name);assert sha(STAGE/'runtime'/name)==pin['sha256'];files[name]=pin
 head=proof['source_commit']
 shutil.copyfile(SOURCE_INPUT/'source.tar',JOB/'source.tar')
 import tarfile
 with tarfile.open(JOB/'source.tar') as archive:archive.extractall(JOB/'source',filter='data')
 assert sha(REPO/'benchmarks/pauper-gorge/benchmark.json')=='86b53f6de6807515e68fd0983c666627ca30e9f98efbbacbe0b65985a9a5882f'
 sys.path.insert(0,str(REPO/'tools'));from gorge_reference_selection import declared_matrix_policies
 policies=declared_matrix_policies(proof['native_verdict']['policies'])
 shutil.copyfile(Path(__file__),JOB/'RECIPE.py');shutil.copyfile(census_path,JOB/'HOSTS.json')
 manifest=dict(schema='spellbench-gorge-local-reference/v1',phase='prepared',at_utc=stamp(),source_commit=head,
  runtime_source_commit=build['source_commit'],runtime_seal_sha256=sha(RUNTIME/'SEAL.json'),runtime_source_of_record=str(RUNTIME),
  files=files,native_proof=dict(native_verdict=proof['native_verdict'],source_binding=proof['source_binding']),source_archive_sha256=sha(JOB/'source.tar'),source_record_sha256=proof['source_record_sha256'],
  benchmark_sha256=sha(REPO/'benchmarks/pauper-gorge/benchmark.json'),
  runtime_builder_toolchain={key:read(RUNTIME/'BUILD.json')[key] for key in ('go_version','go_driver_sha256','compiler_sha256','linker_sha256')},matrix_policies=','.join(policies),process_priority='BelowNormal',
  script_sha256=sha(SCRIPT),parent_sha256=sha(Path(__file__)),usable_cpus=cores,memory_limit_bytes=machine.total_memory(),
  placement=args.placement,worker_cap=bound,per_game_cores=3,expected_matrix_games=120,expected_cells=50,expected_native_participant_receipts=140,
  cap_bytes=CAP,reserve_bytes=RESERVE,wall_cap_seconds=WALL,rated_games=0,published_entries=0,gpu_ordinal=None,
  conservative_reserved_total_usd=9.99736347,new_cloud_spend_usd=0,provider_final_settlement_pending=True,
  source_of_record=str(JOB),recovery_root=None,independent_recovery_pending=True,
  guard_path='host_reservation_v1.dispatch -> bounded parent -> reference_matrix.py -> bench_run.plan_for -> supported arena runner',
  native_qualification_passed=True,reference_qualification_passed=False)
 write(JOB/'PREPARATION.json',manifest)
 assert sum(p.stat().st_size for p in JOB.rglob('*') if p.is_file())<CAP
 print(json.dumps(dict(prepared=True,rated_games=0,new_cloud_spend_usd=0)))

def dispatch():
 proof=check()
 placement_check()
 prep=read(JOB/'PREPARATION.json')
 assert prep['native_proof']==dict(native_verdict=proof['native_verdict'],source_binding=proof['source_binding']) and prep['placement']==args.placement
 assert prep['source_record_sha256']==proof['source_record_sha256']
 assert sha(SOURCE_INPUT/'SOURCE.json')==prep['source_record_sha256']
 assert prep['source_commit']==read(SOURCE_INPUT/'SOURCE.json')['source_commit']
 assert sha(JOB/'source.tar')==prep['source_archive_sha256']
 assert sha(Path(__file__))==prep['parent_sha256'] and sha(SCRIPT)==prep['script_sha256']
 assert not (JOB/'STOP').exists() and host.status()['state']=='free'
 assert not (JOB/'host-dispatch.json').exists()
 result=host.dispatch(lane='spellbench-gorge',work_id='gorge-guarded-reference137',release_condition='All contained reference/replay descendants exited after guarded matrix completion or numerical/environmental failure, maximum21600seconds; own parent recovers outputs, no rated games',
  command=[sys.executable,str(Path(__file__).resolve()),'--run'],cwd=str(REPO),busy_pattern=r'^(go|compile|link|gorgequal.*|spellbench-gorge-.*|public-witness.*|phase1_train|phase1_eval|cargo|rustc)\.exe$',
  transport_record=dict(kind='local-supported-reference-matrix',prepared_root=str(JOB),new_cloud_usd=0))
 write(JOB/'host-dispatch.json',result);print(json.dumps({k:result[k] for k in ('state','pid','generation')}))
def run():
 token=os.environ.get(host.TOKEN_ENV);assert token and host.status(token)['state']=='held'
 import ctypes;k=ctypes.windll.kernel32;k.GetCurrentProcess.restype=ctypes.c_void_p;k.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
 assert k.SetPriorityClass(k.GetCurrentProcess(),0x4000) # BelowNormal, inherited by the matrix
 prep=read(JOB/'PREPARATION.json');assert sha(SCRIPT)==prep['script_sha256'] and sha(Path(__file__))==prep['parent_sha256']
 assert sha(SOURCE_INPUT/'SOURCE.json')==prep['source_record_sha256']
 assert prep['source_commit']==read(SOURCE_INPUT/'SOURCE.json')['source_commit']
 assert sha(JOB/'source.tar')==prep['source_archive_sha256']
 for name,pin in prep['files'].items():assert sha(STAGE/'runtime'/name)==pin['sha256']
 write(STAGE/'MANIFEST.json',prep)
 runtime=STAGE/'runtime'
 env={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY','GH_DEBUG')}
 env.update(GOMAXPROCS='1',GORGE_JOB_ROOT=str(JOB),GORGE_CLOUD_STAGE=str(STAGE),
  GORGE_CLOUD_RUNTIME=str(runtime),GORGE_ASSIGNED_DISK_BYTES=str(CAP),SPELLBENCH_HOST_ALIAS='gorge-Haley-local-reference',
  GORGE_PLACEMENT=prep['placement'],GORGE_MATRIX_POLICIES=prep['matrix_policies'],PYTHONUNBUFFERED='1')
 args=[sys.executable,str(SCRIPT)]
 write(STAGE/'COMMAND.json',dict(command=args,guard_path=prep['guard_path']))
 start=time.monotonic();reason=None;failure=None;last_metrics=-60;offsets={};partial={};rows=0;p=None
 try:
  with (STAGE/'stdout.jsonl').open('xb') as stdout,(STAGE/'stderr.log').open('xb') as stderr:
   p=subprocess.Popen(args,cwd=REPO,env=env,stdout=stdout,stderr=stderr,creationflags=0x4000)
   while p.poll() is None:
    elapsed=time.monotonic()-start
    if elapsed>WALL or (JOB/'STOP').exists():reason='wall_or_STOP';break
    if elapsed-last_metrics>=60:
     last_metrics=elapsed
     if sum(f.stat().st_size for f in JOB.rglob('*') if f.is_file())>CAP or any(shutil.disk_usage(root).free<RESERVE for root in (JOB,)):reason='storage_cap_or_reserve';break
     if (STAGE/'PROGRESS.json').is_file():rows=read(STAGE/'PROGRESS.json')['completed_games']
     children=host.live_descendants([(p.pid,host.creation_time(p.pid))])
     ids=[p.pid]+[c['pid'] for c in children]
     command='Get-Process -Id '+','.join(map(str,ids))+' -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,WorkingSet64,PriorityClass | ConvertTo-Json -Compress'
     stats=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=20)
     metric=dict(at_utc=stamp(),elapsed_seconds=elapsed,completed_matrix_games=rows,stop_reason=reason,worker_cap=prep['worker_cap'],free_bytes_C=shutil.disk_usage(JOB).free,owned_process_stats=json.loads(stats.stdout) if stats.returncode==0 and stats.stdout.strip() else None)
     with (STAGE/'METRICS.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(metric)+'\n')
     write(STAGE/'CURRENT.json',metric)
     if reason:break
    time.sleep(1)
   if reason and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
   exit_code=p.wait(timeout=20)
   result=read(STAGE/'MATRIX.json') if (STAGE/'MATRIX.json').exists() else None
   passed=exit_code==0 and result is not None and result.get('passed') is True and reason is None
   if passed:
    joins=[json.loads(line) for line in (STAGE/'policy-joins.jsonl').read_text().splitlines()]
    passed=(result['completed_games']==prep['expected_matrix_games'] and len(result['cells'])==prep['expected_cells'] and result['replay_identical'] is True and not result['failures'] and len(joins)==prep['expected_matrix_games'] and sum(len(row['policy_receipts']) for row in joins)==prep['expected_native_participant_receipts'])
   write(STAGE/'RECEIPT.json',dict(at_utc=stamp(),exit_code=exit_code,stop_reason=reason,elapsed_seconds=time.monotonic()-start,reference_passed=passed,rated_games=0))
 except BaseException as exc:
  failure=type(exc).__name__+': '+str(exc);write(STAGE/'PARENT-FAILED.json',dict(at_utc=stamp(),error=failure,traceback=traceback.format_exc()));passed=False
 finally:
  if p is not None and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True);p.wait(timeout=20)
  write(JOB/'CLOSURE.json',dict(at_utc=stamp(),reference_passed=passed,error=failure,stop_reason=reason,elapsed_seconds=time.monotonic()-start,new_cloud_spend_usd=0,rated_games=0))
 if not passed:raise SystemExit(1)
def release_check():
 sys.path.insert(0,str(INPUT/'source/tools'))
 from gorge_recover_local_native import owned_release,put
 assert (JOB/'CLOSURE.json').is_file()
 result=owned_release(host,read(JOB/'host-dispatch.json'),lane='spellbench-gorge',work_id='gorge-guarded-reference137')
 put(JOB,'HOST-RELEASE.json',result)
 print(json.dumps(result))

parser=argparse.ArgumentParser();parser.add_argument('--release-check',action='store_true');parser.add_argument('--bundle-sha256');parser.add_argument('--source-record-sha256');parser.add_argument('--prepare',action='store_true');parser.add_argument('--dispatch',action='store_true');parser.add_argument('--run',action='store_true');parser.add_argument('--check',action='store_true');parser.add_argument('--census');parser.add_argument('--placement');args=parser.parse_args()
assert sum((args.prepare,args.dispatch,args.run,args.check,args.release_check))==1
release_check() if args.release_check else print(json.dumps(check())) if args.check else prepare() if args.prepare else dispatch() if args.dispatch else run()
