"""Run the unchanged native audit for the ten non-redeal modes through measured throughput and a canonical compute host claim."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
if not __debug__: raise RuntimeError('This guarded launcher requires Python assertions enabled')
INPUT=Path('C:/mtg-node/spellbench-gorge-staging-20261007-133')
REPO=INPUT/'source';JOB=Path('C:/mtg-node/spellbench-gorge-native-20261007-134');STAGE=JOB/'native'
RUNTIME=INPUT/'runtime';SCRIPT=REPO/'engines/gorge/scripts/qualify_native.py'
WALL=21600;WORKERS=8;POLICIES='bot,bot-auto-pay,lethal-pressure,lethal-pressure-auto-pay,ar8,blocks,explore,legacy,search,search-mana';CAP=2*2**30;RESERVE=60*2**30
sys.dont_write_bytecode=True
sys.path.insert(0,str(INPUT));import host_reservation_v1 as host
assert os.name=='nt' and host.HOST=='COMPUTEHOST','This launcher only claims compute host'
sys.path.insert(0,str(REPO/'python'));sys.path.insert(0,str(REPO/'tools'))
def inputs_check():
 staging=json.loads((INPUT/'STAGING.json').read_bytes())
 assert staging['runtime_source_binding']['compiled_gorge_source_identical'] is True
 assert staging['runtime_source_commit']=='0be859f989edfc050ace2094f3821a1ac9312c51'
 assert sha(INPUT/'source.tar')==staging['source_archive_sha256']
 assert sha(INPUT/'host_reservation_v1.py')==staging['host_module_sha256']
 assert sha(RUNTIME/'SEAL.json')==staging['runtime_seal_sha256']=='2f92a15a12d0154184a99e202914e7ef6e6f96af3a4f55693493709879bf1482'
 assert sha(SCRIPT)==staging['native_script_sha256']
 assert sha(Path(__file__))==staging['native_parent_sha256']
 return staging

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
 assert not census['ComputeHost']['host_lock_exists'] and host.status()['state']=='free'
 assert census['RunPod']['inventory_status']=='HTTP200'
 assert census['budget']['conservative_reserved_total_usd']==9.99736347
 sys.path.insert(0,str(REPO/'python'))
 from spellbench.arena.allocation import Placement
 placement=Placement.parse(args.placement)
 assert [entry.machine for entry in placement.entries if entry.disposition=='used']==['computehost'],'This recipe claims the compute host only'
 return census_path

def prepare():
 census_path=placement_check() # Reject absent or stale placement before roots or claims.
 assert not JOB.exists() and host.status()['state']=='free'
 staging=inputs_check()
 assert read(RUNTIME/'SEAL.json')['runtime_build_passed'] and read(RUNTIME/'CLOSURE.json')['runtime_build_passed']
 build=read(RUNTIME/'BUILD.json')
 assert staging['runtime_source_commit']==build['source_commit']
 sys.path.insert(0,str(REPO/'python'))
 from spellbench.arena import machine
 from spellbench.arena.qualification import current_rules
 assert all(shutil.disk_usage(p).free>RESERVE+CAP for p in (JOB.parent,))
 cores=machine.usable_cpus();memory=machine.total_memory();assert memory is not None
 cap=min(WORKERS,max(n for n in range(2,min(cores,memory//2**30-2)+1) if current_rules().ladder_fits(280,n)))
 placement=args.placement
 JOB.mkdir();STAGE.mkdir();(STAGE/'runtime').mkdir()
 files={}
 for name in ('gorgequal-windows-amd64.exe','registry.gob.gz','REGISTRY.json'):
  pin=read(RUNTIME/'SEAL.json')['files'][name];assert sha(RUNTIME/name)==pin['sha256']
  for target in (STAGE/'runtime'/name,):shutil.copyfile(RUNTIME/name,target);assert sha(target)==pin['sha256']
  files[name]=pin
 shutil.copyfile(Path(__file__),JOB/'RECIPE.py');shutil.copyfile(census_path,JOB/'HOSTS.json')
 manifest=dict(schema='spellbench-gorge-local-native/v1',phase='prepared',at_utc=stamp(),source_commit=staging['source_commit'],source_archive_sha256=staging['source_archive_sha256'],
  runtime_source_commit=build['source_commit'],runtime_seal_sha256=sha(RUNTIME/'SEAL.json'),runtime_source_of_record=str(RUNTIME),files=files,runtime_builder_toolchain={key:build[key] for key in ('go_version','go_driver_sha256','compiler_sha256','linker_sha256')},
  script_sha256=sha(SCRIPT),parent_sha256=sha(Path(__file__)),usable_cpus=cores,memory_limit_bytes=memory,worker_cap=cap,worker_ladder=current_rules().ladder(cap),
  placement=placement,allocation_reason='Fresh actual free compute host has exact production130 staged; native129 measured 8 and 16 workers at matched wall time, so cap8 keeps the compute host usable; actual supported1/half/cap completed-work comparison selects workers by wall time, full audit refused without identical outputs',native_policies=POLICIES.split(','),process_priority='BelowNormal',
  unused_capacity_reason='Fresh three-host placement records eligibility and total-turnaround reasoning; worker bound preserves the unchanged12percent qualification-time budget',
  projected_bytes=512*2**20,cap_bytes=CAP,reserve_bytes=RESERVE,wall_cap_seconds=WALL,rated_games=0,published_entries=0,gpu_ordinal=None,
  conservative_reserved_total_usd=9.99736347,new_cloud_spend_usd=0,provider_final_settlement_pending=True,
  source_of_record=str(JOB),recovery_root=None,independent_recovery_pending=True,guard_path='host_reservation_v1.dispatch -> this bounded parent -> qualify_native.py -> arena.throughput.plan_allocation -> qualified gorgequal callback',
  native_qualification_passed=False,reference_qualification_passed=False)
 write(JOB/'PREPARATION.json',manifest)

 print(json.dumps(dict(prepared=True,worker_cap=cap,worker_ladder=manifest['worker_ladder'],new_cloud_spend_usd=0)))
def dispatch():
 placement_check()
 prep=read(JOB/'PREPARATION.json')
 assert prep['placement']==args.placement
 assert inputs_check()['source_commit']==prep['source_commit'] and sha(INPUT/'source.tar')==prep['source_archive_sha256']
 assert sha(Path(__file__))==prep['parent_sha256'] and sha(SCRIPT)==prep['script_sha256']
 assert sha(RUNTIME/'SEAL.json')==prep['runtime_seal_sha256']
 assert not (JOB/'STOP').exists()
 for name,pin in prep['files'].items():assert sha(STAGE/'runtime'/name)==pin['sha256']
 assert not (JOB/'host-dispatch.json').exists() and host.status()['state']=='free'
 assert Path(sys.executable).resolve()==Path(sys._base_executable).resolve()
 result=host.dispatch(lane='spellbench-gorge',work_id='gorge-guarded-native134',release_condition='All contained native/replay descendants exited after guarded audit completion or numerical/environmental failure, maximum21600seconds; own parent recovers outputs, no rated games',
  command=[sys.executable,str(Path(__file__).resolve()),'--run'],cwd=str(REPO),busy_pattern=r'^(go|compile|link|gorgequal.*|public-witness.*|phase1_train|phase1_eval|cargo|rustc)\.exe$',
  transport_record=dict(kind='local-supported-native-audit',prepared_root=str(JOB),new_cloud_usd=0))
 write(JOB/'host-dispatch.json',result);print(json.dumps({k:result[k] for k in ('state','pid','generation')}))
def run():
 token=os.environ.get(host.TOKEN_ENV);assert token and host.status(token)['state']=='held'
 import ctypes;k=ctypes.windll.kernel32;k.GetCurrentProcess.restype=ctypes.c_void_p;k.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
 assert k.SetPriorityClass(k.GetCurrentProcess(),0x4000) # BelowNormal, inherited by the audit
 prep=read(JOB/'PREPARATION.json');assert sha(SCRIPT)==prep['script_sha256'] and sha(Path(__file__))==prep['parent_sha256']
 assert inputs_check()['source_commit']==prep['source_commit'] and sha(INPUT/'source.tar')==prep['source_archive_sha256']
 for name,pin in prep['files'].items():assert sha(STAGE/'runtime'/name)==pin['sha256']
 write(STAGE/'MANIFEST.json',prep)
 native=STAGE/'runtime/gorgequal-windows-amd64.exe'
 env={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY','GH_DEBUG')}
 env.update(GOMAXPROCS='1',GORGE_JOB_ROOT=str(JOB),GORGE_SOURCE_ROOT=str(REPO),GORGE_CLOUD_STAGE=str(STAGE),
  GORGE_NATIVE_QUALIFIER=str(native),GORGE_NATIVE_QUALIFIER_SHA256=sha(native),GORGE_REGISTRY=str(STAGE/'runtime/registry.gob.gz'),
  GORGE_NATIVE_WORKER_CAP=str(prep['worker_cap']),GORGE_NATIVE_CALLBACK_WALL_SECONDS='18000',SPELLBENCH_HOST_ALIAS='gorge-ComputeHost-native',
  GORGE_PLACEMENT=prep['placement'],GORGE_NATIVE_POLICIES=','.join(prep['native_policies']),PYTHONUNBUFFERED='1')
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
     command='Get-Process -Id '+','.join(map(str,ids))+' -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,WorkingSet64,PriorityClass | ConvertTo-Json -Compress'
     stats=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=20)
     metric=dict(at_utc=stamp(),elapsed_seconds=elapsed,streamed_native_rows=rows,stop_reason=reason,worker_cap=prep['worker_cap'],free_bytes_C=shutil.disk_usage(JOB).free,owned_process_stats=json.loads(stats.stdout) if stats.returncode==0 and stats.stdout.strip() else None)
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

 if not passed:raise SystemExit(1)
parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--dispatch',action='store_true');parser.add_argument('--run',action='store_true');parser.add_argument('--release-check',action='store_true');parser.add_argument('--census');parser.add_argument('--placement');args=parser.parse_args()
assert sum((args.prepare,args.dispatch,args.run,args.release_check))==1
if args.release_check:
 from gorge_recover_local_native import owned_release
 print(json.dumps(owned_release(host,read(JOB/'host-dispatch.json'),lane='spellbench-gorge',work_id='gorge-guarded-native134')))
else:prepare() if args.prepare else dispatch() if args.dispatch else run()
