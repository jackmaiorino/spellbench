"""Run the unchanged native audit through measured throughput and a canonical host claim."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
if not __debug__: raise RuntimeError('This guarded launcher requires Python assertions enabled')
REPO=Path(__file__).resolve().parents[1];COLLAB=Path.home()/('IdeaProjects/collab-spellbench-gorge-preparation-20261003')
JOB=Path('D:/e-scratch/spellbench-gorge-native-20261006-126');COLD=Path('E:/')/JOB.name;STAGE=JOB/'native'
RUNTIME=Path('E:/spellbench-gorge-runtime-20261006-121');SCRIPT=REPO/'engines/gorge/scripts/qualify_native.py'
WALL=21600;CAP=2*2**30;RESERVE=60*2**30
sys.path.insert(0,'D:/mtg-kernel-codex-lead-20261002/python/tools');import host_reservation_v1 as host
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_bytes())
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8',newline='\n')
def placement_check():
 assert args.census and args.placement,'Fresh census and explicit placement are required'
 census_path=Path(args.census);census=read(census_path)
 now=datetime.datetime.now(datetime.timezone.utc)
 for record in [census,census['Desktop'],census['ComputeHost'],census['RunPod']]:
  checked=datetime.datetime.fromisoformat(record['checked_at_utc'].replace('Z','+00:00'))
  assert 0 <= (now-checked).total_seconds() <= 300,'Placement census must be refreshed'
 assert 'state=free' in census['Desktop']['canonical_reservation']
 assert census['RunPod']['inventory_status']=='HTTP200'
 assert census['budget']['conservative_reserved_total_usd']==9.99736347
 sys.path.insert(0,str(REPO/'python'))
 from spellbench.arena.allocation import Placement
 placement=Placement.parse(args.placement)
 assert [entry.machine for entry in placement.entries if entry.disposition=='used']==['main-pc'],'This recipe claims the local desktop host only'
 return census_path

def prepare():
 census_path=placement_check() # Reject absent or stale placement before roots or claims.
 assert not JOB.exists() and not COLD.exists() and host.status()['state']=='free'
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=REPO)
 assert read(RUNTIME/'SEAL.json')['runtime_build_passed'] and read(RUNTIME/'CLOSURE.json')['runtime_build_passed']
 build=read(RUNTIME/'BUILD.json')
 assert not subprocess.check_output(['git','diff',build['source_commit'],'HEAD','--','engines/gorge'],cwd=REPO)
 assert sha(RUNTIME/'SEAL.json')==sha(Path('D:/e-scratch')/RUNTIME.name/'SEAL.json')
 assert read(Path('E:/spellbench-gorge-public-trace-20261006-123')/'CHECKS.json')['saved_root_repaired']
 sys.path.insert(0,str(REPO/'python'))
 from spellbench.arena import machine
 from spellbench.arena.qualification import current_rules
 assert all(shutil.disk_usage(p).free>RESERVE+CAP for p in (JOB.parent,COLD.parent))
 cores=machine.usable_cpus();memory=machine.total_memory();assert memory is not None
 cap=max(n for n in range(2,min(cores,memory//2**30-2)+1) if current_rules().ladder_fits(320,n))
 placement=args.placement
 JOB.mkdir();COLD.mkdir();STAGE.mkdir();(STAGE/'runtime').mkdir();(COLD/'native/runtime').mkdir(parents=True)
 files={}
 for name in ('gorgequal-windows-amd64.exe','registry.gob.gz','REGISTRY.json'):
  pin=read(RUNTIME/'SEAL.json')['files'][name];assert sha(RUNTIME/name)==pin['sha256']
  for target in (STAGE/'runtime'/name,COLD/'native/runtime'/name):shutil.copyfile(RUNTIME/name,target);assert sha(target)==pin['sha256']
  files[name]=pin
 shutil.copyfile(Path(__file__),JOB/'RECIPE.py');shutil.copyfile(census_path,JOB/'HOSTS.json')
 manifest=dict(schema='spellbench-gorge-local-native/v1',phase='prepared',at_utc=stamp(),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
  runtime_source_commit=build['source_commit'],runtime_seal_sha256=sha(RUNTIME/'SEAL.json'),runtime_source_of_record=str(RUNTIME),files=files,runtime_builder_toolchain={key:build[key] for key in ('go_version','go_driver_sha256','compiler_sha256','linker_sha256')},
  script_sha256=sha(SCRIPT),parent_sha256=sha(Path(__file__)),usable_cpus=cores,memory_limit_bytes=memory,worker_cap=cap,worker_ladder=current_rules().ladder(cap),
  placement=placement,allocation_reason='Fresh actual free maintainer has exact production121 already staged; actual supported1/half/cap completed-work comparison selects workers by wall time, full audit refused without identical outputs',
  unused_capacity_reason='Fresh three-host placement records eligibility and total-turnaround reasoning; worker bound preserves the unchanged12percent qualification-time budget',
  projected_bytes=512*2**20,cap_bytes=CAP,reserve_bytes=RESERVE,wall_cap_seconds=WALL,rated_games=0,published_entries=0,gpu_ordinal=None,
  conservative_reserved_total_usd=9.99736347,new_cloud_spend_usd=0,provider_final_settlement_pending=True,
  source_of_record=str(COLD),recovery_root=str(JOB),guard_path='host_reservation_v1.dispatch -> this bounded parent -> qualify_native.py -> arena.throughput.plan_allocation -> qualified gorgequal callback',
  native_qualification_passed=False,reference_qualification_passed=False)
 write(JOB/'PREPARATION.json',manifest)
 for name in ('PREPARATION.json','RECIPE.py','HOSTS.json'):shutil.copyfile(JOB/name,COLD/name);assert sha(JOB/name)==sha(COLD/name)
 for root in (JOB,COLD):
  subprocess.run([sys.executable,str(COLLAB/'tools/artifact_register.py'),'add','--path',str(root),'--lane','spellbench-gorge','--owner','codex',
   '--status','live','--retention','keep-full','--purpose','Unchanged native audit after verified saved-root repair, guarded matched scaling, zero paid compute',
   '--doc',str(COLD/'PREPARATION.json'),'--regen','Exact production121 binaries, registry, qualification launcher and fixed audit seeds','--no-size'],check=True)
 print(json.dumps(dict(prepared=True,worker_cap=cap,worker_ladder=manifest['worker_ladder'],new_cloud_spend_usd=0)))
def dispatch():
 placement_check()
 prep=read(JOB/'PREPARATION.json')
 assert prep['placement']==args.placement
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()==prep['source_commit']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=REPO)
 assert sha(Path(__file__))==prep['parent_sha256'] and sha(SCRIPT)==prep['script_sha256']
 assert sha(RUNTIME/'SEAL.json')==prep['runtime_seal_sha256']
 assert not (JOB/'STOP').exists()
 for name,pin in prep['files'].items():assert sha(STAGE/'runtime'/name)==pin['sha256']
 assert not (JOB/'host-dispatch.json').exists() and host.status()['state']=='free'
 assert Path(sys.executable).resolve()==Path(sys._base_executable).resolve()
 result=host.dispatch(lane='spellbench-gorge',work_id='gorge-guarded-native126',release_condition='All contained native/replay descendants exited after guarded audit completion or numerical/environmental failure, maximum21600seconds; own parent recovers outputs, no rated games',
  command=[sys.executable,str(Path(__file__).resolve()),'--run'],cwd=str(REPO),busy_pattern=r'^(go|compile|link|gorgequal.*|public-witness.*|phase1_train|phase1_eval|cargo|rustc)\.exe$',
  transport_record=dict(kind='local-supported-native-audit',prepared_root=str(COLD),new_cloud_usd=0))
 write(JOB/'host-dispatch.json',result);print(json.dumps({k:result[k] for k in ('state','pid','generation')}))
def run():
 token=os.environ.get(host.TOKEN_ENV);assert token and host.status(token)['state']=='held'
 prep=read(JOB/'PREPARATION.json');assert sha(SCRIPT)==prep['script_sha256'] and sha(Path(__file__))==prep['parent_sha256']
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()==prep['source_commit']
 for name,pin in prep['files'].items():assert sha(STAGE/'runtime'/name)==pin['sha256']
 write(STAGE/'MANIFEST.json',prep)
 native=STAGE/'runtime/gorgequal-windows-amd64.exe'
 env={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY','GH_DEBUG')}
 env.update(GOMAXPROCS='1',GORGE_JOB_ROOT=str(JOB),GORGE_SOURCE_ROOT=str(REPO),GORGE_CLOUD_STAGE=str(STAGE),
  GORGE_NATIVE_QUALIFIER=str(native),GORGE_NATIVE_QUALIFIER_SHA256=sha(native),GORGE_REGISTRY=str(STAGE/'runtime/registry.gob.gz'),
  GORGE_NATIVE_WORKER_CAP=str(prep['worker_cap']),GORGE_NATIVE_CALLBACK_WALL_SECONDS='18000',SPELLBENCH_HOST_ALIAS='gorge-Maintainer-local',
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
     for path in STAGE.glob('*/stdout.jsonl'):
      with path.open('rb') as stream:stream.seek(offsets.get(path,0));fresh=stream.read();offsets[path]=stream.tell()
      lines=(partial.get(path,b'')+fresh).split(b'\n');partial[path]=lines.pop()
      for line in lines:
       try:row=json.loads(line).get('qualification_row',{})
       except (ValueError,UnicodeDecodeError):continue
       if row:rows+=1
       for cell,coverage in row.get('search_coverage',{}).items():
        if cell.endswith('redeal') and (coverage.get('ReconstructionBudgetExhausted',0) or coverage.get('RedealRefusals')):
         reason='existing_native_redeal_gate_failed';write(STAGE/'EARLY-NATIVE-FAILURE.json',dict(at_utc=stamp(),game=row.get('game'),cell=cell,coverage=coverage,gate='Unchanged Report.Clean zero-refusal gate'))
     children=host.live_descendants([(p.pid,host.creation_time(p.pid))])
     ids=[p.pid]+[c['pid'] for c in children]
     command='Get-Process -Id '+','.join(map(str,ids))+' -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Json -Compress'
     stats=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=20)
     metric=dict(at_utc=stamp(),elapsed_seconds=elapsed,streamed_native_rows=rows,stop_reason=reason,worker_cap=prep['worker_cap'],free_bytes_D=shutil.disk_usage(JOB).free,free_bytes_E=shutil.disk_usage(COLD).free,owned_process_stats=json.loads(stats.stdout) if stats.returncode==0 and stats.stdout.strip() else None)
     with (STAGE/'METRICS.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(metric)+'\n')
     write(STAGE/'CURRENT.json',metric)
     if reason:break
    time.sleep(1)
   if reason and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
   exit_code=p.wait(timeout=20)
   result=read(STAGE/'NATIVE-AUDIT.json') if (STAGE/'NATIVE-AUDIT.json').exists() else None
   passed=exit_code==0 and result is not None and result.get('passed') is True and reason is None
   write(STAGE/'RECEIPT.json',dict(at_utc=stamp(),exit_code=exit_code,stop_reason=reason,elapsed_seconds=time.monotonic()-start,native_passed=passed,rated_games=0))
 except BaseException as exc:
  failure=type(exc).__name__+': '+str(exc);write(STAGE/'PARENT-FAILED.json',dict(at_utc=stamp(),error=failure,traceback=traceback.format_exc()));passed=False
 finally:
  if p is not None and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True);p.wait(timeout=20)
  write(JOB/'CLOSURE.json',dict(at_utc=stamp(),native_passed=passed,error=failure,stop_reason=reason,elapsed_seconds=time.monotonic()-start,new_cloud_spend_usd=0,rated_games=0))
  for path in JOB.rglob('*'):
   if path.is_file():
    target=COLD/path.relative_to(JOB);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():assert sha(target)==sha(path)
    else:shutil.copyfile(path,target)
  assert all(sha(COLD/p.relative_to(JOB))==sha(p) for p in JOB.rglob('*') if p.is_file())
 if not passed:raise SystemExit(1)
parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--dispatch',action='store_true');parser.add_argument('--run',action='store_true');parser.add_argument('--census');parser.add_argument('--placement');args=parser.parse_args()
assert sum((args.prepare,args.dispatch,args.run))==1
prepare() if args.prepare else dispatch() if args.dispatch else run()
