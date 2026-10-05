"""Prepare a logging-only replay of one hash-pinned actor-public projection.

This tool emits a JSON capsule on stdout. It builds and runs nothing. A guarded
job must store the capsule, register its artifact roots, and pin the resulting
test binary before execution. Replay is a component check, never game admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


def instrument(source: str, trace_root: str, *, trace_shuffle_failures: bool = False) -> str:
    """Add diagnostics without changing reconstruction choices or its budget."""
    def replace(before: str, after: str) -> None:
        nonlocal source
        if source.count(before) != 1:
            raise ValueError("Public reconstruction patch context changed: " + before[:80])
        source = source.replace(before, after, 1)

    replace('\t"reflect"', '\t"reflect"\n\t"os"')
    hook = r'''
    type witnessAttemptTrace struct {Reached,Failed int; Counts map[string]int; Got,Want Frame; Reason string}
    traces:=[]*witnessAttemptTrace{}
    record:=func(attempt,frame int,kind string,got,want Frame){
        tr:=traces[attempt];tr.Counts[kind]++
        if frame>tr.Failed {tr.Failed=frame;tr.Got=got;tr.Want=want;tr.Reason=kind}
    }
    defer func(){
        data,err:=json.Marshal(map[string]any{"work":work,"attempts":traces});if err!=nil{panic(err)}
        if err:=os.WriteFile(TRACE_PATH,data,0600);err!=nil{panic(err)}
    }()
'''.replace("TRACE_PATH", json.dumps(trace_root + "/TRACE.json"))
    replace('\tvar work SpellbenchReconstruction\n', '\tvar work SpellbenchReconstruction\n' + hook)
    replace('\t\twork.Attempts++\n', '\t\twork.Attempts++\n\t\ttraces=append(traces,&witnessAttemptTrace{Reached:-1,Failed:-1,Counts:map[string]int{}})\n')
    replace('\t\t\td := e.Pending()\n', '\t\t\ttraces[attempt].Reached=max(traces[attempt].Reached,frame)\n\t\t\td := e.Pending()\n')
    replace('if !spellbenchIdentityPrefix(identities, want.Identities) || !spellbenchEventPrefix(burst, want.Events) {\n\t\t\t\treturn nil, nil',
            'if !spellbenchIdentityPrefix(identities, want.Identities) || !spellbenchEventPrefix(burst, want.Events) {\n\t\t\t\tsnapshot:=got;snapshot.Identities=identities;snapshot.Events=burst;record(attempt,frame,"prefix:"+frameDifference(frame,snapshot,want),snapshot,want)\n\t\t\t\treturn nil, nil')
    replace('if !spellbenchFrameEqual(got, want) {\n\t\t\t\t\treturn nil, nil',
            'if !spellbenchFrameEqual(got, want) {\n\t\t\t\t\trecord(attempt,frame,"actor:"+frameDifference(frame,got,want),got,want)\n\t\t\t\t\treturn nil, nil')
    replace('in, err := c.Match(d, h.Answers[frame])\n\t\t\t\tif err != nil {\n\t\t\t\t\treturn nil, nil',
            'in, err := c.Match(d, h.Answers[frame])\n\t\t\t\tif err != nil {\n\t\t\t\t\trecord(attempt,frame,"actor_action:"+err.Error(),got,want)\n\t\t\t\t\treturn nil, nil')
    replace('if err := branch.SubmitHypothetical(in); err != nil {\n\t\t\t\t\tif errors.Is(err, errIncompatibleProposal) {\n\t\t\t\t\t\treturn true',
            'if err := branch.SubmitHypothetical(in); err != nil {\n\t\t\t\t\tif errors.Is(err, errIncompatibleProposal) {\n\t\t\t\t\t\trecord(attempt,frame,"opponent_submit:"+err.Error(),got,want)\n\t\t\t\t\t\treturn true')
    replace('if err := e.SubmitHypothetical(in); err != nil {\n\t\t\t\t\tif errors.Is(err, errIncompatibleProposal) {\n\t\t\t\t\t\treturn nil, nil',
            'if err := e.SubmitHypothetical(in); err != nil {\n\t\t\t\t\tif errors.Is(err, errIncompatibleProposal) {\n\t\t\t\t\t\trecord(attempt,frame,"actor_submit:"+err.Error(),got,want)\n\t\t\t\t\t\treturn nil, nil')
    if trace_shuffle_failures:
        replace('type witnessAttemptTrace struct {Reached,Failed int; Counts map[string]int; Got,Want Frame; Reason string}',
                'type witnessShuffleFailure struct {Frame int; Player state.PlayerID; Ordinal int; Hand,Library map[string]int; Epoch epochConstraints; Error string; ContextSource string}\n'
                'type witnessAttemptTrace struct {Reached,Failed int; Counts map[string]int; Got,Want Frame; Reason string; ShuffleFailures int; BestShuffle *witnessShuffleFailure}')
        replace('\tbasicSearches := spellbenchBasicSearches(setup, h)\n',
                '\tbasicSearches := spellbenchBasicSearches(setup, h)\n' + r'''
    plannerFrames:=map[*proposalState]int{}
    diagnosticPlanner:=func(p *proposalState) rules.ShufflePlanner {
        underlying:=spellbenchBasicSearchPlanner(p,basicSearches)
        return func(ctx rules.ShuffleContext)([]state.ObjID,error){
            order,err:=underlying(ctx)
            if err!=nil && errors.Is(err,errIncompatibleProposal) {
                tr:=traces[p.attempt];tr.ShuffleFailures++
                frame:=plannerFrames[p]
                if tr.BestShuffle==nil || frame>tr.BestShuffle.Frame {
                    snapshot:=&witnessShuffleFailure{Frame:frame,Player:ctx.Player,Ordinal:ctx.Ordinal,
                        Hand:map[string]int{},Library:map[string]int{},Epoch:p.epochs[epochKey{Player:ctx.Player,Ordinal:ctx.Ordinal}],
                        Error:err.Error(),ContextSource:"hypothetical_shuffle_proposal"}
                    for _,card:=range ctx.Hand {snapshot.Hand[card.Name]++}
                    for _,card:=range ctx.Library {snapshot.Library[card.Name]++}
                    tr.BestShuffle=snapshot
                }
            }
            return order,err
        }
    }
''')
        replace('e, err := rules.NewHypotheticalPlanned(cfg, tape, spellbenchBasicSearchPlanner(proposal, basicSearches))',
                'plannerFrames[proposal]=-1\n\t\te, err := rules.NewHypotheticalPlanned(cfg, tape, diagnosticPlanner(proposal))')
        replace('traces[attempt].Reached=max(traces[attempt].Reached,frame)\n',
                'traces[attempt].Reached=max(traces[attempt].Reached,frame)\n\t\t\tpreviousPlannerFrame,hadPlannerFrame:=plannerFrames[p]\n\t\t\tplannerFrames[p]=frame\n'
                '\t\t\tdefer func(){if hadPlannerFrame {plannerFrames[p]=previousPlannerFrame} else {delete(plannerFrames,p)}}()\n')
        replace('branch := e.SpellbenchClonePlannedHypothesis(spellbenchBasicSearchPlanner(&pp, basicSearches))',
                'plannerFrames[&pp]=frame\n\t\t\t\tdefer delete(plannerFrames,&pp)\n\t\t\t\tbranch := e.SpellbenchClonePlannedHypothesis(diagnosticPlanner(&pp))')
        if 'proposalAttempt := attempt' in source:
            replace('plannerFrames:=map[*proposalState]int{}',
                    'plannerFrames:=map[*proposalState]int{}\n    traceAttempts:=map[int]int{}')
            replace('tr:=traces[p.attempt];tr.ShuffleFailures++',
                    'tr:=traces[traceAttempts[p.attempt]];tr.ShuffleFailures++')
            replace('\t\tproposal := &proposalState{',
                    '\t\ttraceAttempts[proposalAttempt]=attempt\n\t\tproposal := &proposalState{')
    return source


def prepare(projection_bytes: bytes, expected_sha: str, source: str, remote_root: str) -> dict:
    if hashlib.sha256(projection_bytes).hexdigest() != expected_sha:
        raise ValueError("Projection differs from its declared SHA-256")
    root = PurePosixPath(remote_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("Remote root must be an absolute normalized path")
    remote_root = str(root)
    value = json.loads(projection_bytes)
    history, options = value["history"], value["options"]
    if not history["ActorBoundaries"] or not history["Frames"]:
        raise ValueError("Projection must contain actor-public boundaries")
    actor = history["Actor"]
    if any(frame["Decision"]["Player"] != actor for frame in history["Frames"]):
        raise ValueError("Projection contains another player's private decision")
    if any(str(i) not in history["Answers"] for i in range(len(history["Frames"]) - 1)):
        raise ValueError("Projection omits a previous actor answer")
    if (options["Attempts"], options["Worlds"], options["MaxSubmits"]) != (64, 8, 5000):
        raise ValueError("Projection changed the native sampler budgets")
    redeal = options["Redeal"]
    if redeal is None or not redeal["SpellbenchPublic"] or redeal["Engine"] is not None or redeal["Observer"] is not None:
        raise ValueError("Projection must use the public seam without a live engine or observer")
    expected_work = value.get("public_reconstruction") or (value.get("result") or {}).get("PublicReconstruction")
    if not expected_work or expected_work["BudgetExhausted"] != 1:
        raise ValueError("Projection does not describe a captured reconstruction exhaustion")
    names, decks = value["names"], value["decks"]
    if len(names) < 2 or len(names) != len(decks) or not 0 <= actor < len(names):
        raise ValueError("Declared players and decks do not match")
    if any(not isinstance(name, str) for deck in decks for name in deck):
        raise ValueError("Decks must contain declared card names")
    trace_root = remote_root + "/trace-public-root"
    modified = instrument(source, trace_root)
    test = r'''package strategies
import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "os"
 "reflect"
 "testing"
 "github.com/adams-shaun/gorge/cards"
 "github.com/adams-shaun/gorge/internal/searchprobe"
)
func TestSavedPublicWitness(t *testing.T) {
 data,err:=os.ReadFile(FIXTURE);if err!=nil{t.Fatal(err)}
 digest:=sha256.Sum256(data);if hex.EncodeToString(digest[:])!=INPUT_SHA{t.Fatal("public input changed")}
 var v struct {Names []string `json:"names"`;Decks [][]string `json:"decks"`;StartingLife int32 `json:"starting_life"`;Mulligans int `json:"mulligans"`;History searchprobe.History `json:"history"`;Options searchprobe.SampleOptions `json:"options"`}
 if err:=json.Unmarshal(data,&v);err!=nil{t.Fatal(err)}
 registryData,err:=os.ReadFile(REGISTRY);if err!=nil{t.Fatal(err)}
 registryDigest:=sha256.Sum256(registryData);if hex.EncodeToString(registryDigest[:])!="42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937"{t.Fatal("registry changed")}
 reg,err:=cards.LoadRegistry(REGISTRY);if err!=nil{t.Fatal(err)}
 setup:=PublicGame{Names:v.Names,StartingLife:v.StartingLife,Mulligans:v.Mulligans,Tokens:reg.Tokens,Decks:make([][]*cards.Card,len(v.Decks))}
 for p,deck:=range v.Decks {for _,name:=range deck {card,ok:=reg.Lookup(name);if !ok{t.Fatal(name)};setup.Decks[p]=append(setup.Decks[p],card)}}
 if v.Options.Attempts!=64||v.Options.Worlds!=8||v.Options.MaxSubmits!=5000{t.Fatal("captured budgets changed")}
 root,work,replayErr:=searchprobe.SpellbenchReconstructRedeal(setup,v.History,v.Options)
 var expected searchprobe.SpellbenchReconstruction
 if err:=json.Unmarshal([]byte(EXPECTED_WORK),&expected);err!=nil{t.Fatal(err)}
 record:=map[string]any{"frames":len(v.History.Frames),"options":v.Options,"work":work,"expected_work":expected,"witness_constructed":root!=nil,"input_sha256":INPUT_SHA,"scope":"One exact public replay witness; no sampled worlds, completed games or native qualification"}
 if replayErr!=nil {record["error"]=replayErr.Error()}
 identical:=reflect.DeepEqual(work,expected)
 record["captured_work_identical"]=identical
 encoded,_:=json.MarshalIndent(record,"","  ");if err:=os.WriteFile(RESULT,encoded,0600);err!=nil{t.Fatal(err)}
 if !identical||root!=nil||replayErr==nil||replayErr.Error()!="public reconstruction submit budget exhausted"||work.BudgetExhausted!=1{t.Fatal("captured witness failure did not reproduce")}
}
'''
    for key, item in {
        "FIXTURE": remote_root + "/capture-001/PUBLIC-PROJECTION.json",
        "INPUT_SHA": expected_sha,
        "REGISTRY": remote_root + "/runtime/registry.gob.gz",
        "EXPECTED_WORK": json.dumps(expected_work, separators=(",", ":")),
        "RESULT": trace_root + "/RESULT.json",
    }.items():
        # Replace complete placeholder tokens so literals and comments survive.
        test = re.sub(r"\b" + key + r"\b", lambda _: json.dumps(item), test)
    return {
        "schema": "spellbench-gorge-public-witness-trace-capsule/v1",
        "projection_sha256": expected_sha,
        "projection_bytes": len(projection_bytes),
        "frames": len(history["Frames"]),
        "expected_work": expected_work,
        "options": options,
        "normalized_production_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "logging_source_sha256": hashlib.sha256(modified.encode()).hexdigest(),
        "logging_source": modified,
        "test_source": test,
        "test_name": "TestSavedPublicWitness",
        "scope": "Logging-only witness replay using exact captured options; no launch or game admission",
        "native_qualification_complete": False,
        "rated_games": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--projection-sha256", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--remote-root", default="/workspace/gorge")
    args = parser.parse_args()
    if args.projection.stat().st_size > 64 * 2**20:
        raise ValueError("Public projection exceeds the component input cap")
    capsule = prepare(args.projection.read_bytes(), args.projection_sha256,
                      args.source.read_text(encoding="utf-8"), args.remote_root)
    capsule["production_source_sha256"] = hashlib.sha256(args.source.read_bytes()).hexdigest()
    print(json.dumps(capsule))


if __name__ == "__main__":
    main()
