"""Original matrix validation on synthetic typed rows; no native execution."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import time

import pytest

from spellbench.arena.config import TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.bench.definition import load_benchmark
from spellbench.run_secret import RunSecret

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import gorge_reference_coordinator as coordinator
import gorge_reference_worker as worker


def matrix(tmp_path):
    spec=importlib.util.spec_from_file_location('coordinator_ledger_fixture',ROOT/'python/tests/test_ledger.py')
    fixture=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    cfg=TournamentConfig.from_json(load_benchmark(ROOT/'benchmarks/pauper-gorge').tournament_config(str(tmp_path/'diag')))
    secret=RunSecret.from_hex('55'*32)
    helpers=worker.load_original_helpers(ROOT,tmp_path/'stage')
    chosen,expected=helpers.select_matrix(schedule(cfg,secret))
    entries={bot.name:SimpleNamespace(name=bot.name,version=bot.version,
        bot_id=hashlib.sha256(bot.name.encode()).hexdigest()) for bot in cfg.bots}
    decks={spec:SimpleNamespace(ledger=lambda spec=spec:SimpleNamespace(to_json=lambda:dict(
        deck_id='sha256:'+hashlib.sha256(spec.catalog_id.encode()).hexdigest(),name=spec.catalog_id,catalog_id=spec.catalog_id)))
        for context in chosen for spec in context.decks}
    full_engine={**fixture.ENGINE,'identity_fixture':'full hello'}
    setup=SimpleNamespace(decks=decks,engine=SimpleNamespace(to_json=lambda:full_engine,
        provenance=lambda:SimpleNamespace(to_json=lambda:fixture.ENGINE)))
    results=[]
    for context in chosen:
        seats=[dict(seat=seat,bot_id=entries[bot.name].bot_id,name=bot.name,version=bot.version)
               for seat,bot in context.seat_specs]
        row=fixture.row(game_index=context.game_index,game_id=secret.game_id(context.game_index),
            matchup_index=context.matchup_index,pair_index=context.pair_index,pair_slot=context.pair_slot,
            seats=seats,decks=[setup.decks[spec].ledger().to_json() for spec in context.decks],
            winner_bot_id=seats[0]['bot_id'])
        receipts=[]
        for seat in seats:
            if seat['name'].startswith('gorge-'):
                receipts.append(dict(schema='spellbench-gorge-policy-audit/v1',game_id=row['game_id'],
                    seat=seat['seat'],bot_name=seat['name'],version=seat['version'],
                    game_started=True,game_over_received=True,policy=seat['name'].removeprefix('gorge-'),
                    native_decisions=1000,ForcedNatives=0,FallbackNatives=0,
                    search=dict(Eligible=1,Covered=1,Redealt=1,ReconstructionBudgetExhausted=0,RedealRefusals={})))
        results.append(dict(index=context.game_index,row=row,engine=full_engine,violation=None,policy_receipts=receipts))
    arguments=dict(chosen=chosen,expected=expected,secret=secret,setup=setup,entries=entries,helpers=helpers,cfg=cfg)
    return results,arguments


def test_complete_original_matrix_has_all_cells_and_native_receipts(tmp_path):
    results,arguments=matrix(tmp_path)
    aggregates,joins,failures=coordinator.validate_matrix(results,**arguments)
    assert len(aggregates)==60 and len(joins)==140 and not failures
    assert sum(len(join['policy_receipts']) for join in joins)==160


@pytest.mark.parametrize('kind',['one_percent','uncovered','refusal','exhaustion','no_redealt'])
def test_original_numerical_gates_are_not_relaxed(tmp_path,kind):
    results,arguments=matrix(tmp_path)
    for value in results:
        for receipt in value['policy_receipts']:
            if kind=='one_percent':
                receipt['ForcedNatives']=10
            elif kind=='uncovered':
                receipt['search']['Covered']=0
            elif kind=='refusal':
                receipt['search']['RedealRefusals']={'synthetic':1}
            elif kind=='exhaustion':
                receipt['search']['ReconstructionBudgetExhausted']=1
            else:
                receipt['search']['Redealt']=0
    _,_,failures=coordinator.validate_matrix(results,**arguments)
    assert failures


@pytest.mark.parametrize('kind',['missing','reorder','duplicate_receipt','missing_receipt','open_lifecycle',
                                'wrong_version','wrong_policy','wrong_engine','wrong_seed','wrong_deck'])
def test_missing_or_changed_evidence_never_validates_the_matrix(tmp_path,kind):
    results,arguments=matrix(tmp_path)
    if kind=='missing':results.pop()
    elif kind=='reorder':results.reverse()
    elif kind=='duplicate_receipt':results[0]['policy_receipts'].append(copy.deepcopy(results[0]['policy_receipts'][0]))
    elif kind=='missing_receipt':results[0]['policy_receipts'].clear()
    elif kind=='open_lifecycle':results[0]['policy_receipts'][0]['game_over_received']=False
    elif kind=='wrong_version':results[0]['policy_receipts'][0]['version']='wrong'
    elif kind=='wrong_policy':results[0]['policy_receipts'][0]['policy']='bot'
    elif kind=='wrong_engine':results[0]['engine']={**results[0]['engine'],'engine_version':'wrong'}
    elif kind=='wrong_seed':results[0]['row']['game_id']='g-'+'0'*16
    else:results[0]['row']['decks'][0]={**results[0]['row']['decks'][0],'catalog_id':'other'}
    with pytest.raises(coordinator.ThroughputError):
        coordinator.validate_matrix(results,**arguments)


def test_coordinator_runs_real_guard_then_full_synthetic_matrix_and_identical_replay(monkeypatch,tmp_path):
    fixture_spec=importlib.util.spec_from_file_location('coordinator_transport_fixture',ROOT/'python/tests/test_gorge_reference_transport.py')
    fixture=importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    import gorge_reference_pool as pool
    import gorge_reference_transport as transport
    original_rows,args=matrix(tmp_path)
    cfg=args['cfg']
    verdict=dict(closed=True,seed_blocks=320,completed_games=640,outputs_identical=True,
                 native_seal_sha256='native-fixture',runtime_seal_sha256='runtime-fixture')
    api=fixture.LockedAPI()
    controller=fixture.client(api,tmp_path/'coordinator-exchange')
    monkeypatch.setattr(coordinator.bench_run,'run_files',lambda cfg:())
    monkeypatch.setattr(coordinator,'preflight',lambda cfg,secret:args['setup'])
    monkeypatch.setattr(coordinator.runner,'registry_entries',lambda *unused:list(args['entries'].values()))
    class FastTransport(transport.NodeTransport):
        def __init__(self,client):
            super().__init__(client,poll_seconds=.002)
    monkeypatch.setattr(coordinator,'NodeTransport',FastTransport)
    real_pool=pool.ReferencePool
    def timed_pool(**kwargs):
        times=iter([0.0,40.0,50.0,70.0,80.0,120.0,130.0,150.0])
        return real_pool(**kwargs,clock=lambda:next(times))
    monkeypatch.setattr(coordinator,'ReferencePool',timed_pool)
    workers=[]
    all_calls=[]
    for index in range(2):
        value,calls=fixture.worker_fixture(tmp_path,index)
        value.node=replace(value.node,source_commit='source-fixture')
        value.cfg=cfg
        value.native_verdict=verdict
        value.indices=tuple(context.game_index for context in args['chosen'])
        value.journal=worker.RequestJournal(stage=value.stage/'dispatches',node=value.node,
            source_commit='source-fixture',native_verdict=verdict,runtime_pins=[],configuration=cfg.to_json(),
            frozen_indices=value.indices,replay_index=next(context.game_index for context in args['chosen']
                if context.decks[0].catalog_id=='Burn' and any('search' in spec.name for _,spec in context.seat_specs)),pool_slots=2)
        def execute(request,value=value,calls=calls):
            value.journal.admit(request)
            calls.append(request)
            secret=RunSecret.from_hex(request['secret_hex'])
            by_index={entry['index']:copy.deepcopy(entry) for entry in original_rows}
            results=[]
            for index in request['indices']:
                result=by_index[index]
                result['row']['game_id']=secret.game_id(index)
                for receipt in result['policy_receipts']:
                    receipt['game_id']=secret.game_id(index)
                result.update(seconds=10.0,primary_digest=pool.primary_digest(result['row']))
                results.append(result)
            return dict(batch=request['batch'],node_alias=value.node.alias,workload=request['workload'],results=results)
        value.execute=execute
        workers.append(value)
        all_calls.append(calls)
    inputs=dict(pool_slots=2,placement=
        'main-pc=unavailable: reserved; haleyspc=unavailable: priority; runpod=not_authorized: cap; github-actions=used: synthetic')
    with ThreadPoolExecutor(max_workers=2) as executor:
        running=[executor.submit(transport.serve_node,value,fixture.client(api,tmp_path/f'node-exchange-{index}'),
                                 poll_seconds=.002) for index,value in enumerate(workers)]
        report=coordinator.coordinate(source=ROOT,source_commit='source-fixture',cfg=cfg,
            stage=tmp_path/'coordinator',client=controller,inputs=inputs,native_verdict=verdict,clock=time.monotonic)
        for future in running:
            future.result(timeout=5)
    assert report['passed'] and report['completed_games']==140 and len(report['cells'])==60
    assert report['native_participant_receipts']==160 and report['replay_identical']
    assert report['allocation']['workers']==2 and report['allocation']['outputs_identical']
    assert [[request['phase'] for request in calls] for calls in all_calls]==[
        ['qualification','qualification','matrix','replay'],['qualification','matrix']]
    assert (tmp_path/'coordinator/replay-original.jsonl').read_bytes()==(tmp_path/'coordinator/replay.jsonl').read_bytes()
