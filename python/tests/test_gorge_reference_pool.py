"""Pool scheduling/admission tests with synthetic rows, no native games."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys

import pytest

from spellbench.arena.qualification import current_rules
from spellbench.arena.allocation import ThroughputError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gorge_reference_pool', ROOT/'tools/gorge_reference_pool.py')
pool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pool
spec.loader.exec_module(pool)
PLACEMENT = ('main-pc=unavailable: reserved; haleyspc=unavailable: priority; '
    'runpod=not_authorized: cap; github-actions=used: two distinct three-core slots')
VERDICT = dict(closed=True, seed_blocks=320, completed_games=640, outputs_identical=True,
    native_seal_sha256='native-seal-fixture', runtime_seal_sha256='runtime-seal-fixture')
NODES = tuple(pool.PoolNode(f'node-{i}', 4, 16*2**30, 90*2**30, 'source-fixture',
    'native-seal-fixture', 'runtime-seal-fixture') for i in range(2))


def make_pool(tmp_path, *, nodes=NODES, verdict=VERDICT, bad=None):
    calls = []
    clock_values = iter([0.0, 40.0, 50.0, 70.0, 80.0, 120.0, 130.0, 150.0, 160.0, 200.0])
    def execute(node, request):
        pool.admit_node_request(request, node=node, source_commit='source-fixture', native_verdict=verdict,
            runtime_pins={}, configuration={'fixture': True}, frozen_indices=range(140),pool_slots=len(nodes))
        calls.append((node.alias, request))
        results = []
        for index in request['indices']:
            row = {'game_index': index, 'classification': 'natural', 'fixture_only': True}
            if bad == 'divergence' and request['batch'] == 2: row['changed'] = True
            result = dict(index=index, row=row, seconds=10.0, violation=None, primary_digest=pool.primary_digest(row))
            if bad == 'digest': result['primary_digest'] = 'sha256:'+'0'*64
            if bad == 'failed': result['row']['classification'] = 'halted'
            if bad == 'nan': result['seconds'] = float('nan')
            results.append(result)
        if bad == 'omitted': results.pop()
        if bad == 'duplicate': results.append(results[0])
        return dict(batch=request['batch'], workload=request['workload'], node_alias=node.alias, results=results)
    value = pool.ReferencePool(nodes=nodes, execute_node=execute, source_commit='source-fixture',
        native_verdict=verdict, runtime_pins={}, configuration={'fixture': True}, indices=range(140),
        stage=tmp_path/'pool', placement=PLACEMENT, host='two-node-fixture',
        rules=replace(current_rules(),worker_selection='wall'), clock=lambda:next(clock_values))
    return value, calls


def test_pool_measures_same_games_then_admits_original_matrix_and_serial_replay(tmp_path):
    value, calls = make_pool(tmp_path)
    with pytest.raises(ThroughputError,match='matching admitted'):
        value.collect(2, range(140), phase='matrix', secret_hex='fixture-only')
    assert calls == []
    allocation = value.qualify(guard_secret_hex='fixture-only', sample=range(140))
    assert allocation.workers == 2 and allocation.outputs_identical
    assert allocation.cpu_count == 6 and allocation.per_game_cores == 3
    assert allocation.rules.worker_selection == 'wall'
    assert [tuple(request['indices']) for _,request in calls] == [(0,1,2,3),(0,2),(1,3)]
    wall, results = value.collect(2, range(140), phase='matrix', secret_hex='another-fixture-only')
    assert [result['index'] for result in results] == list(range(140))
    assert wall > 0
    value.collect(1, [5], phase='replay', secret_hex='another-fixture-only')
    assert calls[-1][1]['indices'] == (5,)


@pytest.mark.parametrize('bad',['digest','failed','nan','omitted','duplicate','divergence'])
def test_bad_or_changed_outputs_never_admit_substantial_collection(tmp_path,bad):
    value,calls = make_pool(tmp_path,bad=bad)
    with pytest.raises(ThroughputError):value.qualify(guard_secret_hex='fixture-only',sample=range(140))
    assert value.allocation is None
    with pytest.raises(ThroughputError):value.collect(2,range(140),phase='matrix',secret_hex='fixture-only')


@pytest.mark.parametrize('change',[dict(usable_cpus=2),dict(memory_bytes=2**30),dict(free_bytes=61*2**30),
    dict(source_commit='wrong'),dict(native_seal_sha256='wrong'),dict(runtime_seal_sha256='wrong'),dict(alias='node-1')])
def test_wrong_or_insufficient_nodes_fail_before_any_callback(tmp_path,change):
    with pytest.raises(ThroughputError):make_pool(tmp_path,nodes=(replace(NODES[0],**change),NODES[1]))


def test_node_cannot_bypass_comparison_by_labeling_full_work_as_a_probe(tmp_path):
    value,calls = make_pool(tmp_path)
    with pytest.raises(ThroughputError,match='bounded'):
        value.collect(1,range(140),phase='qualification',secret_hex='fixture-only')
    assert calls == []
    request = dict(source_commit='source-fixture',native_verdict=VERDICT,runtime_pins={},node_alias='node-0',
        per_game_cores=3,workers=1,configuration={'fixture':True},indices=list(range(140)),
        phase='qualification',batch=1,pool_slots=2)
    with pytest.raises(ThroughputError,match='bounded'):
        pool.admit_node_request(request,node=NODES[0],source_commit='source-fixture',native_verdict=VERDICT,
            runtime_pins={},configuration={'fixture':True},frozen_indices=range(140))


def test_matrix_cannot_drop_or_reorder_indices_after_admission(tmp_path):
    value,calls=make_pool(tmp_path)
    value.qualify(guard_secret_hex='fixture-only',sample=range(140))
    for indices in (range(139),list(reversed(range(140)))):
        with pytest.raises(ThroughputError,match='all 140'):
            value.collect(2,indices,phase='matrix',secret_hex='fixture-only')


def test_partition_preserves_noncontiguous_frozen_indices_and_rejects_duplicates():
    assert pool.partition([9,2,17,4],2)==((9,17),(2,4))
    for indices in ([],[1,1],[True],[-1]):
        with pytest.raises(ThroughputError):pool.partition(indices,2)


def test_four_nodes_measure_full_ladder_without_changing_per_game_resources(tmp_path):
    nodes=tuple(replace(NODES[0],alias=f'node-{i}') for i in range(4))
    value,calls=make_pool(tmp_path,nodes=nodes)
    allocation=value.qualify(guard_secret_hex='fixture-only',sample=range(140))
    assert allocation.cpu_count==12 and allocation.per_game_cores==3
    assert [trial.workers for trial in allocation.trials]==[1,2,4]
    assert all(tuple(trial.indices)==tuple(range(8)) for trial in allocation.trials)
    assert all(request['workers']==1 and request['pool_slots']==4 for _,request in calls)
