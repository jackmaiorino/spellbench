"""Persistent dispatch checks use synthetic receipts, with no native games."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from spellbench.arena.allocation import ThroughputError
from spellbench.arena.throughput import current_rules

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import gorge_reference_pool as pool
import gorge_reference_worker as worker

VERDICT = dict(closed=True, seed_blocks=320, completed_games=640, outputs_identical=True,
    native_seal_sha256='native-fixture', runtime_seal_sha256='runtime-fixture')
NODES = tuple(pool.PoolNode(f'node-{i}', 4, 16*2**30, 90*2**30, 'source-fixture',
    'native-fixture', 'runtime-fixture') for i in range(2))
PLACEMENT = ('main-pc=unavailable: reserved; haleyspc=unavailable: priority; '
    'runpod=not_authorized: cap; github-actions=used: two synthetic slots')


def inputs(tmp_path):
    requests = []
    def execute(node, request):
        # Round trip the wire representation, including lists versus tuples.
        request = json.loads(json.dumps(request))
        requests.append(request)
        results = []
        for index in request['indices']:
            row = dict(game_index=index, classification='natural', synthetic_fixture=True)
            results.append(dict(index=index, row=row, seconds=10.0, violation=None,
                                primary_digest=pool.primary_digest(row)))
        return dict(batch=request['batch'], node_alias=node.alias, workload=request['workload'], results=results)
    times = iter([0.0,40.0,50.0,70.0,80.0,120.0,130.0,150.0])
    value = pool.ReferencePool(nodes=NODES, execute_node=execute, source_commit='source-fixture',
        native_verdict=VERDICT, runtime_pins=[], configuration={'synthetic_fixture':True},
        indices=range(140), stage=tmp_path/'pool', placement=PLACEMENT, host='fixture',
        rules=replace(current_rules(),worker_selection='wall'), clock=lambda:next(times))
    value.qualify(guard_secret_hex='11'*32, sample=range(140))
    value.collect(2, range(140), phase='matrix', secret_hex='22'*32)
    value.collect(1, [5], phase='replay', secret_hex='22'*32)
    return value, [request for request in requests if request['node_alias']=='node-0']


def journal(tmp_path):
    return worker.RequestJournal(stage=tmp_path/'journal', node=NODES[0], source_commit='source-fixture',
        native_verdict=VERDICT, runtime_pins=[], configuration={'synthetic_fixture':True},
        frozen_indices=range(140), replay_index=5, pool_slots=2)


def test_one_original_matrix_and_preselected_serial_replay_are_admitted(tmp_path):
    value, requests = inputs(tmp_path)
    log = journal(tmp_path)
    for request in requests:
        assert log.admit(request).hex()==request['secret_hex']
    assert log.qualification_count==2 and log.matrix_admitted and log.replay_admitted
    assert json.loads((tmp_path/'journal/ADMISSION-3.json').read_bytes())['indices']==list(range(0,140,2))
    assert '22'*32 not in (tmp_path/'journal/ADMISSION-3.json').read_text()
    assert len(list((tmp_path/'pool').glob('*/node-*-response.json')))==6


def test_repeat_and_worker_restart_do_not_dispatch_again(tmp_path):
    _, requests = inputs(tmp_path)
    log = journal(tmp_path)
    log.admit(requests[0])
    with pytest.raises(ThroughputError,match='Repeated'):
        log.admit(requests[0])
    with pytest.raises(FileExistsError):
        journal(tmp_path)


@pytest.mark.parametrize('field,changed',[
    ('schema','other-schema'), ('secret_hex','secret-never-valid'), ('batch',True),
    ('pool_workers',4), ('workload','sha256:'+'0'*64),
])
def test_changed_dispatch_fails_before_admission(tmp_path,field,changed):
    _, requests = inputs(tmp_path)
    log = journal(tmp_path)
    bad = {**requests[0],field:changed}
    with pytest.raises((ThroughputError,ValueError)):
        log.admit(bad)
    assert not list((tmp_path/'journal').glob('ADMISSION-*.json'))


def test_matrix_cannot_change_measured_rules_partition_or_private_secret(tmp_path):
    _, requests = inputs(tmp_path)
    log = journal(tmp_path)
    log.admit(requests[0])
    log.admit(requests[1])
    for change in (dict(indices=list(range(140))),dict(secret_hex='11'*32)):
        with pytest.raises(ThroughputError):
            log.admit({**requests[2],**change})
    changed = json.loads(json.dumps(requests[2]))
    changed['pool_descriptor']['qualification_rules']['worker_selection']='busy'
    changed['workload']=pool.workload_id(changed['pool_descriptor'])
    with pytest.raises(ThroughputError,match='original pool workload'):
        log.admit(changed)
    assert not log.matrix_admitted


def test_probe_cannot_change_secret_or_run_after_matrix(tmp_path):
    _, requests = inputs(tmp_path)
    log = journal(tmp_path)
    log.admit(requests[0])
    with pytest.raises(ThroughputError,match='changed secrets'):
        log.admit({**requests[1],'secret_hex':'33'*32})
    log.admit(requests[1])
    log.admit(requests[2])
    with pytest.raises(ThroughputError,match='exceeded its original'):
        log.admit({**requests[1],'batch':4})


def test_replay_cannot_change_seed_or_preselected_index(tmp_path):
    _, requests = inputs(tmp_path)
    log = journal(tmp_path)
    for request in requests[:3]:
        log.admit(request)
    for change in (dict(indices=[6]),dict(secret_hex='33'*32)):
        with pytest.raises(ThroughputError,match='preselected'):
            log.admit({**requests[3],**change})
    assert not log.replay_admitted


def test_worker_refuses_transport_credentials_before_runner_launch(monkeypatch):
    value = object.__new__(worker.ReferenceWorker)
    monkeypatch.setenv('GH_TOKEN','synthetic-credential')
    with pytest.raises(ThroughputError,match='credentials must be removed'):
        value.execute({})


def test_portable_native_proof_binds_hashes_without_local_paths():
    assert pool.portable_native_verdict(dict(VERDICT,native_root='host-a/native',runtime_root='host-a/runtime'))==VERDICT


def test_worker_constructor_verifies_native_pass_before_any_runner_preflight(monkeypatch,tmp_path):
    from spellbench.arena.config import TournamentConfig
    from spellbench.bench.definition import load_benchmark
    cfg = TournamentConfig.from_json(load_benchmark(ROOT/'benchmarks/pauper-gorge').tournament_config(str(tmp_path/'diag')))
    seen = []
    def failed_gate(*args,**kwargs):
        seen.append((args,kwargs))
        raise worker.ThroughputError('synthetic invalid native pass')
    monkeypatch.setattr(worker,'verify_native_audit',failed_gate)
    def no_preflight(*args,**kwargs):
        pytest.fail('Native gate failure reached runner preflight')
    monkeypatch.setattr(worker,'preflight',no_preflight)
    with pytest.raises(ThroughputError,match='invalid native'):
        worker.ReferenceWorker(source=ROOT,source_commit='fixture',cfg=cfg,stage=tmp_path/'worker',
            node_alias='node-0',pool_slots=2,native_root=tmp_path/'native',runtime=tmp_path/'runtime',
            native_seal_sha256='fixture',runtime_seal_sha256='fixture',cleanup_sha256='fixture',
            deadline=60,clock=lambda:0)
    assert len(seen)==1


@pytest.mark.parametrize('failure',[None,'identity','missing_receipt','changed_game_id'])
def test_worker_uses_supported_runner_and_preserves_failed_evidence(monkeypatch,tmp_path,failure):
    from spellbench.arena.ledger import LedgerRow
    from spellbench.run_secret import RunSecret
    spec=importlib.util.spec_from_file_location('worker_ledger_fixture',ROOT/'python/tests/test_ledger.py')
    fixture=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    secret=RunSecret.from_hex('44'*32)
    value=object.__new__(worker.ReferenceWorker)
    value.stage=tmp_path/'worker'
    value.stage.mkdir()
    value.cfg=object()
    value.node=NODES[0]
    value.files=()
    value.resource_guard=lambda:None
    value.journal=SimpleNamespace(admit=lambda request:secret)
    value.helpers=worker.load_original_helpers(ROOT,value.stage)
    full_identity={**fixture.ENGINE,'synthetic_extra_identity_field':'full identity'}
    setup=SimpleNamespace(engine=SimpleNamespace(to_json=lambda:full_identity,
        provenance=lambda:SimpleNamespace(to_json=lambda:fixture.ENGINE)))
    row=fixture.row(game_id=secret.game_id(0))
    row['seats'][0]['name']='gorge-search'
    if failure=='changed_game_id':
        row['game_id']='g-'+'0'*16
    monkeypatch.setattr(worker,'preflight',lambda *args:setup)
    monkeypatch.setattr(worker.runner,'registry_entries',lambda *args:[])
    monkeypatch.setattr(worker,'schedule',lambda *args:[SimpleNamespace(game_index=0)])
    called=[]
    def play(cfg,actual_setup,chosen,**kwargs):
        called.append(kwargs)
        assert actual_setup is setup and cfg is value.cfg
        assert kwargs['workers']==1 and kwargs['timed'] and kwargs['stop_on_violation']
        assert kwargs['launch_files']==() and kwargs['run_secret'] is secret
        if failure!='missing_receipt':
            audit=Path(worker.os.environ['GORGE_AGENT_AUDIT_DIR'])
            (audit/'gorge-agent-synthetic.json').write_text(json.dumps(dict(
                schema='spellbench-gorge-policy-audit/v1',game_id=row['game_id'],seat='p0',
                bot_name='gorge-search',version='1',game_started=True,game_over_received=True)))
        engine={**full_identity,'engine_version':'changed'} if failure=='identity' else full_identity
        outcome=worker.runner.TimedOutcome(row=LedgerRow.from_json(row),diagnostics=('synthetic diagnostic',),
            violation=None,engine=engine,seconds=1.0)
        kwargs['on_outcome'](outcome)
        return SimpleNamespace(error=None,stopped=None)
    monkeypatch.setattr(worker.runner,'play_games',play)
    for key in ('GH_TOKEN','GITHUB_TOKEN','RUNPOD_API_KEY'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('GORGE_AGENT_AUDIT_DIR','previous-audit-directory')
    request=dict(batch=1,workload='fixture-only',indices=[0])
    if failure is None:
        response=value.execute(request)
        assert len(response['results'][0]['policy_receipts'])==1
        assert (value.stage/'batch-1/RESPONSE.json').is_file()
    else:
        with pytest.raises((ThroughputError,RuntimeError)):
            value.execute(request)
        assert (value.stage/'batch-1/FAILURE.json').is_file()
        assert not (value.stage/'batch-1/RESPONSE.json').exists()
    assert len(called)==1
    raw=json.loads((value.stage/'batch-1/results.jsonl').read_text())
    assert raw['diagnostics']==['synthetic diagnostic']
    assert worker.os.environ['GORGE_AGENT_AUDIT_DIR']=='previous-audit-directory'
