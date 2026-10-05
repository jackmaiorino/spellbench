"""Build and replay three sealed public prefixes on a bounded public CI runner."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import zipfile

from gorge_ci_exchange import DraftExchange, extract_pinned, sha

REGISTRY = "42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937"
CASES = (
    (93, "d722bb33bf2ab583f3bb3837f7e3e332efbdbebaf30a9fcfa7214d5524214955"),
    (113, "c18f35eae6bd5269ffce77211c82ed739a0cc46423c6795d13e233248a536c64"),
    (123, "3585338514ed1a6f9c825851829352b7d8ce86dec57b3d04eb98784456dc3989"),
)
RESERVE = 60 * 2**30
CAP = 4 * 2**30
WALL = 2400


def positive_test(capsule):
    test = capsule["test_source"]
    old = 'if !identical||root!=nil||replayErr==nil||replayErr.Error()!="public reconstruction submit budget exhausted"||work.BudgetExhausted!=1{t.Fatal("captured witness failure did not reproduce")}'
    assert test.count(old) == 1
    test = test.replace(old, 'if root==nil||replayErr!=nil||work.BudgetExhausted!=0||work.Submits>v.Options.MaxSubmits{t.Fatalf("saved public repair failed: %v work=%+v",replayErr,work)}')
    anchor = 'encoded,_:=json.MarshalIndent(record,"","  ")'
    assert test.count(anchor) == 1
    checks = r'''
 known,err:=searchprobe.ProjectKnownCards(v.History);if err!=nil{t.Fatal(err)}
 if root!=nil {if err:=known.Holds(searchprobe.World{Engine:root.Engine,Observer:root.Observer});err!=nil{t.Fatal(err)}}
 if root!=nil && replayErr==nil {
   opts:=v.Options;opts.Redeal=&searchprobe.RedealBase{}
   before,err:=searchprobe.Sample(setup,v.History,opts);if err!=nil{t.Fatal(err)}
   opts.Redeal=&searchprobe.RedealBase{SpellbenchPublic:true}
   after,err:=searchprobe.Sample(setup,v.History,opts);if err!=nil{t.Fatal(err)}
   leftBytes,_:=json.Marshal(before);rightBytes,_:=json.Marshal(after)
   var left,right map[string]any;json.Unmarshal(leftBytes,&left);json.Unmarshal(rightBytes,&right)
   for _,key:=range []string{"PublicReconstruction","RedealRefused","Redealt"}{delete(left,key);delete(right,key)}
   equal:=reflect.DeepEqual(left,right)
   record["native_diagnostics_identical"]=equal;record["redealt_worlds"]=len(after.Worlds)
   record["redeal_refused"]=after.RedealRefused
   if !equal || len(after.Worlds)!=8 || after.RedealRefused!="" || after.PublicReconstruction==nil || after.PublicReconstruction.BudgetExhausted!=0 {t.Fatal("native pool changed or redeal failed")}
   for _,world:=range after.Worlds {if err:=known.Holds(world);err!=nil{t.Fatal(err)}}
   record["known_card_checks_passed"]=true
 }
 record["scope"]="One exact public replay and eight native pool checks; no completed games or qualification"
'''
    return test.replace(anchor, checks + anchor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--asset-id", type=int, required=True)
    parser.add_argument("--archive-sha256", required=True)
    args = parser.parse_args()
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("GITHUB_REPOSITORY") == "jackmaiorino/spellbench"
    repo = Path(__file__).resolve().parents[1]
    job = args.job.resolve()
    assert not job.exists()
    assert shutil.disk_usage(job.parent).free > RESERVE + CAP
    job.mkdir(); result = job / "result"; result.mkdir()
    started = time.monotonic(); failure = None
    exchange = DraftExchange(release_id=args.release_id, scratch=job/"exchange", deadline=started+WALL+180)
    def put(name, value):
        (result/name).write_text(json.dumps(value, indent=2)+"\n")
    def guard():
        if time.monotonic()-started > WALL or (job/"STOP").exists():
            raise RuntimeError("Replay wall or STOP reached")
        if shutil.disk_usage(job).free < RESERVE or sum(p.stat().st_size for p in job.rglob("*") if p.is_file()) > CAP:
            raise RuntimeError("Replay storage cap or reserve reached")
    env = {k:v for k,v in os.environ.items() if k not in ("GH_TOKEN","GITHUB_TOKEN","RUNPOD_API_KEY","GH_DEBUG")}
    def run(name, command, cwd, timeout=180):
        guard(); begin=time.monotonic()
        put(name+"-COMMAND.json", dict(command=command,cwd=str(cwd),timeout=timeout))
        with (result/(name+".stdout")).open("xb") as out, (result/(name+".stderr")).open("xb") as err:
            process=subprocess.Popen(command,cwd=cwd,env=env,stdout=out,stderr=err,start_new_session=True)
            try:
                while process.poll() is None:
                    guard()
                    if time.monotonic()-begin > timeout: raise TimeoutError(name)
                    time.sleep(1)
            finally:
                if process.poll() is None: os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=20)
        put(name+"-RECEIPT.json",dict(exit_code=process.returncode,seconds=time.monotonic()-begin))
        if process.returncode: raise RuntimeError(name+" failed")
    try:
        asset=next(a for a in exchange.assets().values() if a["id"]==args.asset_id)
        assert asset["digest"]=="sha256:"+args.archive_sha256
        archive=exchange.download(asset,job/"inputs.zip",cap_bytes=8*2**20)
        inputs=job/"inputs";extract_pinned(archive,inputs,cap_bytes=8*2**20)
        expected={"registry.gob.gz":REGISTRY,**{f"case-{i:03}.json":h for i,(_,h) in enumerate(CASES,1)}}
        assert {p.name for p in inputs.iterdir()}==set(expected)
        assert all(p.is_file() and sha(p)==expected[p.name] for p in inputs.iterdir())
        # The existing exact SDK/compiler/build guard runs no games.
        build=job/"build"
        run("production-build",[sys.executable,str(repo/"tools/gorge-build-runtime.py"),"--job",str(build)],repo,1250)
        manifest=json.loads((build/"runtime/BUILD.json").read_bytes())
        assert manifest["runtime_build_passed"] and manifest["source_commit"]==os.environ["GITHUB_SHA"]
        runtime=result/"runtime";shutil.copytree(build/"runtime",runtime)
        shutil.copyfile(inputs/"registry.gob.gz",runtime/"registry.gob.gz")
        spec=importlib.util.spec_from_file_location("trace",repo/"python/tools/gorge_public_trace.py")
        trace=importlib.util.module_from_spec(spec);spec.loader.exec_module(trace)
        module=repo/"engines/gorge";source=(module/"native-overlay/public_redeal.go.txt").read_text()
        header=None;tests=[]
        for i,(frames,digest) in enumerate(CASES,1):
            case=result/f"case-{i:03}";case.mkdir();(case/"capture-001").mkdir();(case/"trace-public-root").mkdir()
            shutil.copyfile(inputs/f"case-{i:03}.json",case/"capture-001/PUBLIC-PROJECTION.json")
            (case/"runtime").mkdir();shutil.copyfile(inputs/"registry.gob.gz",case/"runtime/registry.gob.gz")
            capsule=trace.prepare((inputs/f"case-{i:03}.json").read_bytes(),digest,source,str(case))
            assert capsule["frames"]==frames
            test=positive_test(capsule)
            if header is None: header=test.split("func TestSavedPublicWitness",1)[0]
            tests.append(test[test.index("func TestSavedPublicWitness"):].replace("func TestSavedPublicWitness(",f"func TestSavedPublicWitness{i:03}(",1))
            (case/"CAPSULE.json").write_text(json.dumps(capsule,indent=2)+"\n")
        generated=result/"saved-public-witness_test.go";generated.write_text(header+"\n".join(tests))
        overlay=json.loads((module/"go-overlay.json").read_bytes())
        overlay["Replace"][str(module/"strategies/zz_saved_public_ci_test.go")]=str(generated)
        (result/"overlay.json").write_text(json.dumps(overlay))
        env.update(GOTOOLCHAIN="local",CGO_ENABLED="0",GOMAXPROCS="2",GOMEMLIMIT="2GiB",GORGE_SRC=str(build/"upstream"),GOCACHE=str(build/"go-cache"),GOMODCACHE=str(build/"go-mod-cache"),GOFLAGS="-overlay="+str(result/"overlay.json"))
        go=build/"go/bin/go";binary=result/"public-witness-tests-linux-amd64"
        run("build-component",[str(go),"test","-c","-p","2","-trimpath","-buildvcs=false","-o",str(binary),"./strategies"],module,600)
        pin=result/"pinned-binaries"/sha(binary);pin.mkdir(parents=True);shutil.copyfile(binary,pin/binary.name)
        put("PINNED-BINARY.json",dict(sha256=sha(binary),path=str(pin/binary.name)))
        run("public-replays",[str(pin/binary.name),"-test.run=^TestSavedPublicWitness","-test.v","-test.timeout=5m"],module,330)
        checks=[json.loads((result/f"case-{i:03}/trace-public-root/RESULT.json").read_bytes()) for i in range(1,4)]
        assert all(c["witness_constructed"] and c["work"]["BudgetExhausted"]==0 and c["known_card_checks_passed"] and c["native_diagnostics_identical"] and c["redealt_worlds"]==8 for c in checks)
        put("CHECKS.json",dict(passed=True,cases=checks,native_qualification_complete=False,rated_games=0))
    except BaseException as exc:
        failure=type(exc).__name__+": "+str(exc)
        put("FAILED.json",dict(error=failure))
    finally:
        put("CLOSURE.json",dict(component_passed=failure is None,error=failure,source_commit=os.environ["GITHUB_SHA"],elapsed_seconds=time.monotonic()-started,native_qualification_complete=False,rated_games=0,new_cloud_spend_usd=0))
        # Keep binaries, capsules, failures and results private for independent E/D recovery.
        output=job/"result.zip"
        with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(result.rglob("*")):
                if path.is_file(): zipped.write(path,path.relative_to(result).as_posix())
        uploaded=exchange.upload("replay-"+os.environ["GITHUB_RUN_ID"]+"-"+os.environ["GITHUB_RUN_ATTEMPT"]+".zip",output,cap_bytes=256*2**20)
        print(json.dumps(dict(component_passed=failure is None,result_asset_id=uploaded["id"],result_sha256=sha(output),result_bytes=output.stat().st_size,native_qualification_complete=False,rated_games=0,new_cloud_spend_usd=0)))
    if failure: raise SystemExit(1)


if __name__=="__main__":main()
