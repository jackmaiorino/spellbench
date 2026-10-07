"""Prepare or run current reference qualification after positive native107 recovery."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
if not __debug__: raise RuntimeError('This guarded launcher requires Python assertions enabled')
REPO=Path(__file__).resolve().parents[1];COLLAB=Path('C:/Users/Jack/IdeaProjects/collab-spellbench-gorge-preparation-20261003')
JOB=Path('D:/e-scratch/spellbench-gorge-reference-20261006-112');COLD=Path('E:/')/JOB.name;STAGE=JOB/'reference'
RUNTIME=Path('E:/spellbench-gorge-runtime-20261005-108');SCRIPT=REPO/'engines/gorge/scripts/reference_matrix.py'
WALL=21600;CAP=2*2**30;RESERVE=60*2**30
sys.path.insert(0,'D:/mtg-kernel-codex-lead-20261002/python/tools');import host_reservation_v1 as host
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_bytes())
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8',newline='\n')
def check():
 sys.path.insert(0,str(REPO/'tools'));sys.path.insert(0,str(REPO/'python'))
 from gorge_native_gate import verify_native_audit
 from gorge_runtime_source import verify_runtime_source
 from gorge_reference_pool import portable_native_verdict
 assert args.native_seal_sha256 and args.cleanup_sha256
 native=Path('E:/spellbench-gorge-hosted-native-20261005-107')
 runtime_pin='411fa9f41914bfca0f04a72c4ed5899b8cbf14c5bb0a5a32af31b25b2f6c06a7'
 kw=dict(seal_sha256=args.native_seal_sha256,runtime_seal_sha256=runtime_pin,cleanup_sha256=args.cleanup_sha256)
 first=verify_native_audit(native,RUNTIME,**kw)
 second=verify_native_audit(Path('D:/e-scratch')/native.name,Path('D:/e-scratch')/RUNTIME.name,**kw)
 assert portable_native_verdict(first)==portable_native_verdict(second)
 binding=verify_runtime_source(REPO,read(RUNTIME/'BUILD.json')['source_commit'])
 return dict(native_verdict=portable_native_verdict(first),source_binding=binding)

def placement_check():
 assert args.census and args.placement
 census_path=Path(args.census);census=read(census_path)
 now=datetime.datetime.now(datetime.timezone.utc)
 for record in [census,census['Jack'],census['Haley'],census['RunPod']]:
  checked=datetime.datetime.fromisoformat(record['checked_at_utc'].replace('Z','+00:00'))
  assert 0 <= (now-checked).total_seconds() <= 300,'Placement census must be refreshed'
 assert census['Jack']['canonical_reservation_snapshot']['state']=='free'
 assert census['RunPod']['inventory_status']=='HTTP200'
 assert census['budget']['conservative_reserved_total_usd']==9.99736347
 from spellbench.arena.allocation import Placement
 placement=Placement.parse(args.placement)
 assert [entry.machine for entry in placement.entries if entry.disposition=='used']==['main-pc'],'This recipe claims the local Jack host only'
 return census_path

def prepare():
 proof=check() # Actual positive proof before creating either owned root.
 assert proof['native_verdict']['closed'] is True
 assert not JOB.exists() and not COLD.exists() and host.status()['state']=='free'
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=REPO)
 census_path=placement_check()
 from spellbench.arena import machine
 assert all(shutil.disk_usage(p).free>RESERVE+CAP for p in (JOB.parent,COLD.parent))
 JOB.mkdir();COLD.mkdir();STAGE.mkdir();(STAGE/'runtime').mkdir()
 build=read(RUNTIME/'BUILD.json');files={}
 for name in ('spellbench-gorge-env-windows-amd64.exe','spellbench-gorge-agent-windows-amd64.exe','registry.gob.gz','REGISTRY.json'):
  pin=read(RUNTIME/'SEAL.json')['files'][name];assert sha(RUNTIME/name)==pin['sha256']
  shutil.copyfile(RUNTIME/name,STAGE/'runtime'/name);assert sha(STAGE/'runtime'/name)==pin['sha256'];files[name]=pin
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
 subprocess.run(['git','archive','--format=tar','--output='+str(JOB/'source.tar'),head],cwd=REPO,check=True)
 import tarfile
 with tarfile.open(JOB/'source.tar') as archive:archive.extractall(JOB/'source',filter='data')
 assert sha(JOB/'source/engines/gorge/scripts/reference_matrix.py')==sha(SCRIPT)
 shutil.copyfile(Path(__file__),JOB/'RECIPE.py');shutil.copyfile(census_path,JOB/'HOSTS.json')
 manifest=dict(schema='spellbench-gorge-local-reference/v1',phase='prepared',at_utc=stamp(),source_commit=head,
  runtime_source_commit=build['source_commit'],runtime_seal_sha256=sha(RUNTIME/'SEAL.json'),runtime_source_of_record=str(RUNTIME),
  files=files,native_proof=proof,source_archive_sha256=sha(JOB/'source.tar'),
  benchmark_sha256=sha(REPO/'benchmarks/pauper-gorge/benchmark.json'),
  runtime_builder_toolchain={key:read(RUNTIME/'CI-BUILD.json')[key] for key in ('go_version','go_driver_sha256','compiler_sha256','linker_sha256','linux_sdk_sha256')},
  script_sha256=sha(SCRIPT),parent_sha256=sha(Path(__file__)),usable_cpus=machine.usable_cpus(),memory_limit_bytes=machine.total_memory(),
  placement=args.placement,worker_cap=8,per_game_cores=3,expected_matrix_games=140,expected_cells=60,expected_native_participant_receipts=160,
  cap_bytes=CAP,reserve_bytes=RESERVE,wall_cap_seconds=WALL,rated_games=0,published_entries=0,gpu_ordinal=None,
  conservative_reserved_total_usd=9.99736347,new_cloud_spend_usd=0,provider_final_settlement_pending=True,
  source_of_record=str(COLD),recovery_root=str(JOB),
  guard_path='host_reservation_v1.dispatch -> bounded parent -> reference_matrix.py -> bench_run.plan_for -> supported arena runner',
  native_qualification_passed=True,reference_qualification_passed=False)
 write(JOB/'PREPARATION.json',manifest)
 assert sum(p.stat().st_size for p in JOB.rglob('*') if p.is_file())<CAP
 for path in JOB.rglob('*'):
  if path.is_file():
   target=COLD/path.relative_to(JOB);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);assert sha(target)==sha(path)
 for root in (JOB,COLD):
  subprocess.run([sys.executable,str(COLLAB/'tools/artifact_register.py'),'add','--path',str(root),'--lane','spellbench-gorge','--owner','codex',
   '--status','live','--retention','keep-full','--purpose','Guarded original140-game local reference qualification after independently recovered native pass',
   '--doc',str(COLD/'PREPARATION.json'),'--regen','Exact runtime108, recovered native107 pass, current benchmark and supported matched scaling','--no-size'],check=True)
 print(json.dumps(dict(prepared=True,rated_games=0,new_cloud_spend_usd=0)))

def dispatch():
 proof=check()
 placement_check()
 prep=read(JOB/'PREPARATION.json')
 assert prep['native_proof']==proof and prep['placement']==args.placement
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()==prep['source_commit']
 assert sha(Path(__file__))==prep['parent_sha256'] and sha(SCRIPT)==prep['script_sha256']
 assert not (JOB/'STOP').exists() and host.status()['state']=='free'
 assert not (JOB/'host-dispatch.json').exists()
 result=host.dispatch(lane='spellbench-gorge',work_id='gorge-guarded-reference112',release_condition='All contained reference/replay descendants exited after guarded matrix completion or numerical/environmental failure, maximum21600seconds; own parent recovers outputs, no rated games',
  command=[sys.executable,str(Path(__file__).resolve()),'--run'],cwd=str(REPO),busy_pattern=r'^(go|compile|link|gorgequal.*|spellbench-gorge-.*|public-witness.*|phase1_train|phase1_eval|cargo|rustc)\.exe$',
  transport_record=dict(kind='local-supported-reference-matrix',prepared_root=str(COLD),new_cloud_usd=0))
 write(JOB/'host-dispatch.json',result);print(json.dumps({k:result[k] for k in ('state','pid','generation')}))
def run():
 token=os.environ.get(host.TOKEN_ENV);assert token and host.status(token)['state']=='held'
 prep=read(JOB/'PREPARATION.json');assert sha(SCRIPT)==prep['script_sha256'] and sha(Path(__file__))==prep['parent_sha256']
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()==prep['source_commit']
 for name,pin in prep['files'].items():assert sha(STAGE/'runtime'/name)==pin['sha256']
 write(STAGE/'MANIFEST.json',prep)
 runtime=STAGE/'runtime'
 env={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY','GH_DEBUG')}
 env.update(GOMAXPROCS='1',GORGE_JOB_ROOT=str(JOB),GORGE_CLOUD_STAGE=str(STAGE),
  GORGE_CLOUD_RUNTIME=str(runtime),GORGE_ASSIGNED_DISK_BYTES=str(CAP),SPELLBENCH_HOST_ALIAS='gorge-Jack-local-reference',
  GORGE_PLACEMENT=prep['placement'],PYTHONUNBUFFERED='1')
 args=[str(REPO/'.venv/Scripts/python.exe'),str(SCRIPT)]
 write(STAGE/'COMMAND.json',dict(command=args,guard_path=prep['guard_path']))
 start=time.monotonic();reason=None;failure=None;last_metrics=-60;offsets={};partial={};rows=0;p=None
 try:
  with (STAGE/'stdout.jsonl').open('xb') as stdout,(STAGE/'stderr.log').open('xb') as stderr:
   p=subprocess.Popen(args,cwd=REPO,env=env,stdout=stdout,stderr=stderr)
   while p.poll() is None:
    elapsed=time.monotonic()-start
    if elapsed>WALL or (JOB/'STOP').exists():reason='wall_or_STOP';break
    if elapsed-last_metrics>=60:
     last_metrics=elapsed
     if sum(f.stat().st_size for f in JOB.rglob('*') if f.is_file())>CAP or any(shutil.disk_usage(root).free<RESERVE for root in (JOB,COLD)):reason='storage_cap_or_reserve';break
     if (STAGE/'PROGRESS.json').is_file():rows=read(STAGE/'PROGRESS.json')['completed_games']
     children=host.live_descendants([(p.pid,host.creation_time(p.pid))])
     ids=[p.pid]+[c['pid'] for c in children]
     command='Get-Process -Id '+','.join(map(str,ids))+' -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Json -Compress'
     stats=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=20)
     metric=dict(at_utc=stamp(),elapsed_seconds=elapsed,completed_matrix_games=rows,stop_reason=reason,worker_cap=prep['worker_cap'],free_bytes_D=shutil.disk_usage(JOB).free,free_bytes_E=shutil.disk_usage(COLD).free,owned_process_stats=json.loads(stats.stdout) if stats.returncode==0 and stats.stdout.strip() else None)
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
    passed=(result['completed_games']==140 and len(result['cells'])==60 and result['replay_identical'] is True and not result['failures'] and len(joins)==140 and sum(len(row['policy_receipts']) for row in joins)==160)
   write(STAGE/'RECEIPT.json',dict(at_utc=stamp(),exit_code=exit_code,stop_reason=reason,elapsed_seconds=time.monotonic()-start,reference_passed=passed,rated_games=0))
 except BaseException as exc:
  failure=type(exc).__name__+': '+str(exc);write(STAGE/'PARENT-FAILED.json',dict(at_utc=stamp(),error=failure,traceback=traceback.format_exc()));passed=False
 finally:
  if p is not None and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True);p.wait(timeout=20)
  write(JOB/'CLOSURE.json',dict(at_utc=stamp(),reference_passed=passed,error=failure,stop_reason=reason,elapsed_seconds=time.monotonic()-start,new_cloud_spend_usd=0,rated_games=0))
  for path in JOB.rglob('*'):
   if path.is_file():
    target=COLD/path.relative_to(JOB);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():assert sha(target)==sha(path)
    else:shutil.copyfile(path,target)
  assert all(sha(COLD/p.relative_to(JOB))==sha(p) for p in JOB.rglob('*') if p.is_file())
 if not passed:raise SystemExit(1)
parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--dispatch',action='store_true');parser.add_argument('--run',action='store_true');parser.add_argument('--check',action='store_true');parser.add_argument('--native-seal-sha256');parser.add_argument('--cleanup-sha256');parser.add_argument('--census');parser.add_argument('--placement');args=parser.parse_args()
assert sum((args.prepare,args.dispatch,args.run,args.check))==1
print(json.dumps(check())) if args.check else prepare() if args.prepare else dispatch() if args.dispatch else run()
