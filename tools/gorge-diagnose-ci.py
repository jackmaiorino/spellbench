"""Capture one failed native seed's first public reconstruction exhaustion.

This correctness diagnostic cannot qualify any entrant or run other seeds.
It adds logging to a disposable build overlay, leaving production source,
teacher settings, seeds and the shared 64/8/5000 budget unchanged.
"""
import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request

from gorge_ci_exchange import extract_pinned, sha

RESERVE=60*2**30
CAP=4*2**30
RESULT_CAP=128*2**20
WALL=3600
SCOPE='one game49 first public failure diagnostic only'


def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def validate_inputs(value):
    budget=value.get('conservative_reserved_total_usd')
    storage=value.get('diagnostic_storage_reservation_usd')
    if (value.get('launch_authorized') is not True or value.get('scope')!=SCOPE or
            value.get('game_indices')!=[49] or value.get('production_changes') is not False or
            value.get('repository_private') is not False or value.get('rated_games')!=0 or
            type(budget) not in (int,float) or not math.isfinite(budget) or not 0<=budget<=10 or
            type(storage) not in (int,float) or not math.isfinite(storage) or not .01<=storage<=budget or
            type(value.get('release_asset_id')) is not int or value['release_asset_id']<=0 or
            type(value.get('release_id')) is not int or value['release_id']<=0):
        raise RuntimeError('Diagnostic scope, budget or private inputs are not admitted')
    for key in ('archive_sha256','registry_sha256','runtime_source_commit','runtime_seal_sha256','failed_native_seal_sha256'):
        size=40 if key=='runtime_source_commit' else 64
        if not isinstance(value.get(key),str) or len(value[key])!=size or any(c not in '0123456789abcdef' for c in value[key]):
            raise RuntimeError('Diagnostic input pin is absent: '+key)
    if set(value['files'])!={'BUILD.json','REGISTRY.json','registry.gob.gz'}:
        raise RuntimeError('Diagnostic input inventory differs')


def capture_overlay(text):
    anchor='\tvar work SpellbenchReconstruction\n'
    if text.count(anchor)!=1 or text.count('"math/rand/v2"')!=1:
        raise RuntimeError('Pinned reconstruction capture context changed')
    hook=r'''
    defer func() {
        if work.BudgetExhausted == 0 || os.Getenv("GORGE_DIAGNOSTIC_CAPTURE_DIR") == "" { return }
        decks := make([][]string,len(setup.Decks))
        for p,deck := range setup.Decks { for _,card := range deck { decks[p]=append(decks[p],card.Faces[0].Name) } }
        data,err:=json.Marshal(map[string]any{"names":setup.Names,"decks":decks,"starting_life":setup.StartingLife,"mulligans":setup.Mulligans,"history":h,"options":opts,"public_reconstruction":work,"scope":"Declared decks and actor-visible history only; no live hidden state","phase":"first_budget_exhaustion"})
        if err!=nil {panic(err)}
        target:=os.Getenv("GORGE_DIAGNOSTIC_CAPTURE_DIR")+"/PUBLIC-PROJECTION.json"
        f,err:=os.OpenFile(target+".pending",os.O_WRONLY|os.O_CREATE|os.O_EXCL,0600)
        if err!=nil {panic(err)}
        if _,err=f.Write(data);err!=nil {panic(err)}
        if err=f.Sync();err!=nil {panic(err)}
        if err=f.Close();err!=nil {panic(err)}
        if err=os.Rename(target+".pending",target);err!=nil {panic(err)}
        os.Exit(97)
    }()
'''
    return text.replace('"math/rand/v2"','"math/rand/v2"\n\t"os"',1).replace(anchor,anchor+hook,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    inputs=json.loads(args.inputs.read_bytes())
    validate_inputs(inputs)
    if (os.environ.get('GITHUB_ACTIONS')!='true' or
            os.environ.get('GITHUB_REPOSITORY')!='jackmaiorino/spellbench' or
            os.environ.get('GITHUB_RUN_ATTEMPT')!='1'):
        raise RuntimeError('Only the original standard public CI attempt is admitted')
    source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    if source!=os.environ['GITHUB_SHA']:
        raise RuntimeError('Diagnostic source differs from its CI identity')
    sys.path.insert(0,str(repo/'python'))
    from spellbench.arena import machine
    from spellbench.arena.allocation import Placement
    Placement.parse(inputs['placement'])
    job=args.job.resolve()
    if job.exists() or machine.free_bytes(job.parent)<RESERVE+CAP:
        raise RuntimeError('Diagnostic requires a fresh root and its storage reserve')
    job.mkdir()
    output=job/'diagnostic'
    output.mkdir()
    write(output/'INPUTS.json',inputs)
    spec=importlib.util.spec_from_file_location('gorge_production_build',repo/'tools/gorge-build-runtime.py')
    build=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    started=time.monotonic()
    manifest=dict(scope=SCOPE,source_commit=source,runtime_source_commit=inputs['runtime_source_commit'],
        failed_native_seal_sha256=inputs['failed_native_seal_sha256'],placement=inputs['placement'],
        game_indices=[49],wall_cap_seconds=WALL,cap_bytes=CAP,result_cap_bytes=RESULT_CAP,reserve_bytes=RESERVE,
        actual_usable_cpus=machine.usable_cpus(),actual_memory_bytes=machine.total_memory(),
        production_changes=False,native_qualification_passed=False,rated_games=0,gpu_ordinal=None)
    write(output/'MANIFEST.json',manifest)
    if manifest['actual_usable_cpus']<4 or not manifest['actual_memory_bytes'] or manifest['actual_memory_bytes']<8*2**30:
        raise RuntimeError('Runner lacks the bounded diagnostic resources')

    def guard():
        if (time.monotonic()-started>WALL or (job/'STOP').exists() or
                machine.free_bytes(job)<RESERVE or
                sum(p.stat().st_size for p in job.rglob('*') if p.is_file())>CAP or
                sum(p.stat().st_size for p in output.rglob('*') if p.is_file())>RESULT_CAP-8*2**20):
            raise RuntimeError('Diagnostic wall, STOP, storage cap or reserve reached')

    env={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY','GH_DEBUG')}
    env.pop('GORGE_DIAGNOSTIC_TEACHER_PARALLELISM',None)
    phase='download'
    passed=False
    def run(name,command,*,cwd=repo,timeout=180,allowed=(0,),run_env=env):
        guard()
        begin=time.monotonic()
        write(output/(name+'-COMMAND.json'),dict(command=command,cwd=str(cwd),timeout=timeout))
        with (output/(name+'.stdout')).open('xb') as stdout,(output/(name+'.stderr')).open('xb') as stderr:
            process=subprocess.Popen(command,cwd=cwd,env=run_env,stdout=stdout,stderr=stderr,start_new_session=True)
            try:
                while process.poll() is None:
                    guard()
                    if time.monotonic()-begin>timeout:raise TimeoutError(name)
                    metrics=dict(elapsed_seconds=time.monotonic()-started,pid=process.pid,phase=phase,
                        load_average=os.getloadavg(),free_bytes=machine.free_bytes(job))
                    for label,path in [('stat','stat'),('memory','status'),('io','io')]:
                        try:metrics[label]=Path(f'/proc/{process.pid}/{path}').read_text()
                        except FileNotFoundError:pass
                    with (output/'METRICS.jsonl').open('a') as stream:stream.write(json.dumps(metrics)+'\n')
                    time.sleep(5)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait(timeout=10)
        write(output/(name+'-RECEIPT.json'),dict(exit_code=process.returncode,elapsed_seconds=time.monotonic()-begin))
        if process.returncode not in allowed:raise RuntimeError(name+' exit '+str(process.returncode))
        return process.returncode

    try:
        metadata=json.loads(subprocess.check_output(['gh','api',f"repos/jackmaiorino/spellbench/releases/{inputs['release_id']}"],timeout=60))
        asset=next(a for a in metadata['assets'] if a['id']==inputs['release_asset_id'])
        if (not metadata['draft'] or metadata['published_at'] is not None or
                not metadata['tag_name'].startswith('gorge-diagnostic-') or asset['size']>16*2**20 or
                asset['digest']!='sha256:'+inputs['archive_sha256']):
            raise RuntimeError('Diagnostic private input asset differs')
        archive=job/'input.zip'
        with archive.open('xb') as stream:
            subprocess.run(['gh','api',f"repos/jackmaiorino/spellbench/releases/assets/{asset['id']}",'-H',
                'Accept: application/octet-stream'],stdout=stream,stderr=subprocess.PIPE,check=True,timeout=180)
        if sha(archive)!=inputs['archive_sha256'] or archive.stat().st_size!=asset['size']:
            raise RuntimeError('Diagnostic input download differs')
        extract_pinned(archive,job/'input',cap_bytes=16*2**20)
        if {p.relative_to(job/'input').as_posix() for p in (job/'input').rglob('*') if p.is_file()}!=set(inputs['files']):
            raise RuntimeError('Diagnostic extracted inventory differs')
        for name,pin in inputs['files'].items():
            if sha(job/'input'/name)!=pin['sha256'] or (job/'input'/name).stat().st_size!=pin['bytes']:
                raise RuntimeError('Diagnostic frozen input differs: '+name)
        if sha(job/'input/registry.gob.gz')!=build.REGISTRY_SHA or inputs['registry_sha256']!=build.REGISTRY_SHA:
            raise RuntimeError('Diagnostic registry is not the frozen production bytes')
        production=json.loads((job/'input/BUILD.json').read_bytes())
        if production['source_commit']!=inputs['runtime_source_commit']:
            raise RuntimeError('Diagnostic build provenance differs from production source')
        run('fetch-runtime',['git','fetch','--depth=1','origin',inputs['runtime_source_commit']])
        if subprocess.check_output(['git','diff',inputs['runtime_source_commit'],'HEAD','--','engines/gorge'],cwd=repo):
            raise RuntimeError('Diagnostic production source differs from failed native input')
        phase='build'
        sdk=job/'go-sdk.tar.gz'
        with urllib.request.urlopen(build.SDK_URL,timeout=30) as response,sdk.open('xb') as stream:
            shutil.copyfileobj(response,stream)
        if sha(sdk)!=build.SDK_SHA or sdk.stat().st_size!=build.SDK_SIZE:
            raise RuntimeError('Pinned SDK differs')
        with tarfile.open(sdk) as handle:handle.extractall(job,filter='data')
        go=str(job/'go/bin/go')
        upstream=job/'upstream'
        module=repo/'engines/gorge'
        for name,pin in production['overlay_files'].items():
            if sha(module/name)!=pin:
                raise RuntimeError('Diagnostic source overlay differs: '+name)
        env.update(GOTOOLCHAIN='local',CGO_ENABLED='0',GOMAXPROCS='2',GOMEMLIMIT='2GiB',
            GORGE_SRC=str(upstream),GOCACHE=str(job/'go-cache'),GOMODCACHE=str(job/'go-mod-cache'))
        run('git-init',['git','init',str(upstream)])
        run('git-crlf',['git','config','core.autocrlf','true'],cwd=upstream)
        run('git-remote',['git','remote','add','origin','https://github.com/adams-shaun/gorge.git'],cwd=upstream)
        run('git-fetch',['git','fetch','--depth=1','origin',build.GORGE_PIN],cwd=upstream)
        run('git-checkout',['git','checkout','--detach','FETCH_HEAD'],cwd=upstream)
        if subprocess.check_output(['git','rev-parse','HEAD'],cwd=upstream,text=True).strip()!=build.GORGE_PIN:
            raise RuntimeError('Diagnostic upstream revision differs')
        fingerprint=__import__('hashlib').sha256()
        for path in sorted((upstream/'cards').glob('*.go')):
            if not path.name.endswith('_test.go'):fingerprint.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
        if fingerprint.hexdigest()[:32]!=build.FINGERPRINT:
            raise RuntimeError('Pinned upstream compiler fingerprint differs')
        run('setup',[sys.executable,str(module/'scripts/setup-dev.py')],cwd=module)
        overlay=json.loads((module/'go-overlay.json').read_bytes())
        modified=output/'diagnostic-public-redeal.go'
        modified.write_text(capture_overlay((module/'native-overlay/public_redeal.go.txt').read_text()))
        overlay['Replace'][str(upstream/'internal/searchprobe/spellbench_public_redeal.go')]=str(modified)
        write(output/'overlay.json',overlay)
        env['GOFLAGS']='-overlay='+str(output/'overlay.json')
        run('linked-compiler',[go,'test','-p','2','-count=1','-timeout=2m','-run',
            '^TestLinkedGorgeIsThePinnedCompiler$','./internal/gorgepin'],cwd=module)
        binary=output/'gorgequal-linux-amd64'
        run('build',[go,'build','-p','2','-trimpath','-buildvcs=false','-o',str(binary),'./cmd/gorgequal'],cwd=module,timeout=900)
        manifest.update(binary_sha256=sha(binary),compiler_sha256=sha(job/'go/pkg/tool/linux_amd64/compile'),
            linker_sha256=sha(job/'go/pkg/tool/linux_amd64/link'),sdk_sha256=build.SDK_SHA,
            go_version=subprocess.check_output([go,'version'],text=True).strip(),
            production_overlay_sha256=sha(module/'native-overlay/public_redeal.go.txt'),
            diagnostic_overlay_sha256=sha(modified),registry_sha256=build.REGISTRY_SHA)
        write(output/'MANIFEST.json',manifest)
        phase='first_public_failure'
        code=run('capture',[str(binary),'-games','4','-workers','1','-resample','7','-audit=true','-progress',
            '-registry',str(job/'input/registry.gob.gz'),'-registry-sha256',build.REGISTRY_SHA,
            '-game-indices','49','-out',str(output/'report.json')],cwd=module,timeout=3300,allowed=(0,1,97),
            run_env={**env,'GOMAXPROCS':'4','GORGE_DIAGNOSTIC_CAPTURE_DIR':str(output)})
        capture=output/'PUBLIC-PROJECTION.json'
        public=json.loads(capture.read_bytes())
        if (code!=97 or public['phase']!='first_budget_exhaustion' or not public['history']['ActorBoundaries'] or
                public['public_reconstruction']['BudgetExhausted']<1 or
                any(public['options'][k]!=v for k,v in [('Attempts',64),('Worlds',8),('MaxSubmits',5000)]) or
                any(public['history'].get(key) is not None for key in ('Engine','Observer')) or
                any(frame.get('Board',{}).get(key) is not None for frame in public['history']['Frames'] for key in ('Engine','Observer'))):
            raise RuntimeError('First public failure capture is absent or has changed scope')
        write(output/'CHECKS.json',dict(passed=True,capture_sha256=sha(capture),frames=len(public['history']['Frames']),
            game_index=49,exit_code=97,production_teacher_default=True,native_qualification_passed=False,rated_games=0))
        passed=True
    except Exception as exc:
        write(output/'FAILED.json',dict(phase=phase,error_type=type(exc).__name__,error=str(exc),rated_games=0))
        raise
    finally:
        write(output/'CLOSURE.json',dict(diagnostic_passed=passed,elapsed_seconds=time.monotonic()-started,
            native_qualification_passed=False,rated_games=0))


if __name__=='__main__':main()
