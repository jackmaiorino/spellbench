"""Resolve the full rated definition against pinned inputs; publish no commitment."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
repo=Path.cwd();collab=Path.home()/('IdeaProjects/collab-spellbench-gorge-preparation-20261003')
sys.path.insert(0,str(repo/'python'))
from spellbench.bench.definition import load_benchmark,substitute,placeholder_names
from spellbench.arena.config import TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.run_secret import RunSecret
from gorge_runtime_source import verify_runtime_source
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime',type=Path,default=Path('E:/spellbench-gorge-runtime-20261005-048'))
parser.add_argument('--runtime-seal-sha256',default='b4a17891e93b69c58cf5b8036853428e2366d750f4a43d7e35988e0c8a7c95ef')
parser.add_argument('--check-only',action='store_true',help='Verify the zero-game plan without writing records')
args=parser.parse_args()
runtime=args.runtime
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
seal=json.loads((runtime/'SEAL.json').read_bytes());build=json.loads((runtime/'BUILD.json').read_bytes())
assert sha(runtime/'SEAL.json')==args.runtime_seal_sha256
source_binding=verify_runtime_source(repo,build['source_commit'])
# Runtime identity covers compiled Go. This zero-game plan records current
# Python source differences; actual reference and throughput qualification
# must bind the current launcher before any rated admission.
launcher_changes=subprocess.check_output(['git','diff','--name-only',build['source_commit'],'HEAD','--','python/spellbench/arena','python/spellbench/bench'],text=True).splitlines()
names=['spellbench-gorge-env-windows-amd64.exe','spellbench-gorge-agent-windows-amd64.exe','registry.gob.gz']
for name in names:
    pin=seal['files'][name]
    assert sha(runtime/name)==sha(Path('D:/e-scratch')/runtime.name/name)==pin['sha256']
values=dict(GORGE_SPELLBENCH_ENV=str(runtime/names[0]),GORGE_SPELLBENCH_AGENT=str(runtime/names[1]),GORGE_REGISTRY=str(runtime/names[2]),GORGE_REGISTRY_SHA256=sha(runtime/names[2]))
benchmark=load_benchmark(repo/'benchmarks/pauper-gorge')
assert set(placeholder_names(benchmark))==set(values)
def resolve(v):
    if isinstance(v,str):return substitute(v,values)
    if isinstance(v,list):return [resolve(x) for x in v]
    if isinstance(v,dict):return {k:resolve(x) for k,x in v.items()}
    return v
config=TournamentConfig.from_json(resolve(benchmark.tournament_config('UNLAUNCHED-rated-handoff')))
roster=json.loads((repo/'docs/gorge-roster-20261002.json').read_bytes())
native=[b for b in config.to_json()['bots'] if b['name'].startswith('gorge-')]
assert len(native)==12 and len(config.to_json()['bots'])==14
assert {b['name'] for b in native}=={b['name'] for b in roster['entries'] if b.get('integration','').startswith('implemented')}
policies=[b['command'][b['command'].index('-policy')+1] for b in native]
assert len(set(policies))==12
contexts=schedule(config,RunSecret.from_hex('23'*32));assert len(contexts)==3640
register=collab/'tools/artifact_register.py';assert register.is_file()
planned=dict(SPELLBENCH_SECRETS_DIR='E:/spellbench-gorge-rated-secrets',SPELLBENCH_PIN_ROOT='E:/spellbench-gorge-rated-pins',SPELLBENCH_ARTIFACT_REGISTER=str(register),SPELLBENCH_ARTIFACT_OWNER='spellbench-gorge')
for name in ['SPELLBENCH_SECRETS_DIR','SPELLBENCH_PIN_ROOT']:
    path=Path(planned[name]);assert path.is_absolute()
    assert not any(p.name=='.git' for p in [path,*path.parents])
    nearest=path
    while not nearest.exists():nearest=nearest.parent
    assert subprocess.run(['git','-C',str(nearest),'rev-parse','--git-dir'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
record=dict(schema='spellbench-gorge-rated-handoff/v1',source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),runtime_source_commit=build['source_commit'],runtime_source_of_record=str(runtime),runtime_seal_sha256=sha(runtime/'SEAL.json'),benchmark_sha256=sha(repo/'benchmarks/pauper-gorge/benchmark.json'),resolved_runtime_values=values,planned_local_values=planned,planned_paths_created=False,matched_E_D_input_pins={name:seal['files'][name] for name in names},roster=[b['name'] for b in config.to_json()['bots']],policies=policies,deck_pool=[d.catalog_id or d.name for d in benchmark.deck_pool],scheduled_games=3640,full_round_robin=True,validation_seed_is_public_placeholder=True,run_secret_created=False,commitment_created=False,engine_processes_started=0,rated_games=0,launch_admitted=False,remaining=['Current320-block/640-game native qualification and matched serial/parallel hashes','Current140-game reference matrix,60cells,160native participant receipts and identical replay','Current identity/fair-play review and benchmark definition review/merge','Fresh reservations and useful-compute selection within the remaining all-in USD10 scope','Own author branch at reviewed default tip; bench commit with private secret outside Git; commitment PR review/merge and third-party timestamp','Supported bench run once, result validation/review, compact publication PR and verified Pages entries'],recipe_sha256=sha(Path(__file__)))
record.update(launcher_source_changes=launcher_changes,
    runtime_source_binding=source_binding,
    launcher_changed_source_sha256={name:sha(repo/name) for name in launcher_changes if (repo/name).is_file()},
    launcher_allocation_sha256=sha(repo/'python/spellbench/arena/allocation.py'),
    launcher_throughput_requalification_required=True)
if not args.check_only:
    for p in [repo/'docs/gorge-rated-handoff-20261005.json',collab/'ARTIFACTS/spellbench-gorge-rated-handoff-20261005.json']:
        p.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(runtime_inputs_verified=True,resolved_entrants=14,distinct_native_policies=12,scheduled_games=len(contexts),rated_games=0,launch_admitted=False)))
