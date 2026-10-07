"""CI admission refuses missing native recovery, scope, budget and placement."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('gorge_reference_ci',ROOT/'tools/gorge-reference-ci.py')
ci=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def inputs():
    return dict(schema='spellbench-gorge-ci-reference-inputs/v1',launch_authorized=True,
        scope='reference qualification only',repository_private=False,pool_slots=4,
        conservative_reserved_total_usd=9.96136347,release_id=17,release_asset_id=1,
        archive_bytes=1024,extracted_bytes=2048,archive_sha256='a'*64,native_seal_sha256='b'*64,
        runtime_seal_sha256='c'*64,cleanup_sha256='d'*64,billing_seal_sha256='e'*64,
        benchmark_sha256=ci.BENCHMARK,registry_sha256=ci.REGISTRY,runtime_source_commit='f'*40,
        placement='main-pc=unavailable: reserved; computehost=unavailable: priority; runpod=not_authorized: cap; github-actions=used: synthetic',
        resource_census={host:dict(checked=True) for host in ('main-pc','computehost','runpod')},
        files={'runtime/fixture':dict(bytes=2048,sha256='a'*64)})


def test_shipped_control_cannot_launch_without_actual_native_and_dispatch_inputs():
    value=json.loads((ROOT/'docs/gorge-ci-reference-inputs.json').read_bytes())
    assert value['launch_authorized'] is False and value['rated_games']==0
    with pytest.raises(RuntimeError,match='dispatch admission'):
        ci.validate_inputs(value)


def test_bounded_two_and_four_node_candidates_need_exact_inputs():
    for count in (2,4):
        value=inputs()
        value['pool_slots']=count
        assert 0<ci.validate_inputs(value)<ci.CAP


@pytest.mark.parametrize('field,changed',[
    ('launch_authorized',False),('scope','rated evaluation'),('pool_slots',8),('pool_slots',True),
    ('repository_private',True),('conservative_reserved_total_usd',10.01),
    ('conservative_reserved_total_usd',float('nan')),('native_seal_sha256',None),
    ('cleanup_sha256','bad'),('release_id',0),('archive_bytes',257*2**20),
    ('extracted_bytes',513*2**20),('benchmark_sha256','a'*64),('registry_sha256','a'*64),
    ('runtime_source_commit','bad'),('resource_census',{}),('files',{}),
])
def test_inadmissible_ci_request_fails_before_external_calls(field,changed):
    value={**inputs(),field:changed}
    with pytest.raises((RuntimeError,ValueError,TypeError)):
        ci.validate_inputs(value)


def test_complete_recovery_must_fit_the_coordinator_scratch_cap():
    value={**inputs(),'archive_bytes':256*2**20,'extracted_bytes':512*2**20}
    with pytest.raises(RuntimeError,match='Complete reference recovery'):
        ci.validate_inputs(value)
