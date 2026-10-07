"""Diagnostic admission and logging preserve the single failing seed scope."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('gorge_diagnostic_ci',ROOT/'tools/gorge-diagnose-ci.py')
diagnostic=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def inputs():
    return dict(launch_authorized=True,scope=diagnostic.SCOPE,game_indices=[49],production_changes=False,
        repository_private=False,rated_games=0,conservative_reserved_total_usd=9.97136347,
        diagnostic_storage_reservation_usd=.01,release_id=1,release_asset_id=2,
        archive_sha256='a'*64,registry_sha256='b'*64,runtime_source_commit='c'*40,
        runtime_seal_sha256='d'*64,failed_native_seal_sha256='e'*64,
        files={'BUILD.json':{},'REGISTRY.json':{},'registry.gob.gz':{}})


@pytest.mark.parametrize('key,value',[
    ('launch_authorized',False),('game_indices',[49,52]),('production_changes',True),
    ('rated_games',1),('conservative_reserved_total_usd',10.01),
    ('conservative_reserved_total_usd',float('nan')),('diagnostic_storage_reservation_usd',0),
    ('runtime_source_commit',None),('release_asset_id',True),('repository_private',True)])
def test_changed_or_unfunded_scope_is_refused(key,value):
    candidate=inputs()
    candidate[key]=value
    with pytest.raises((RuntimeError,TypeError)):
        diagnostic.validate_inputs(candidate)


def test_capture_is_a_single_insert_after_the_work_declaration():
    diagnostic.validate_inputs(inputs())
    original=(ROOT/'engines/gorge/native-overlay/public_redeal.go.txt').read_text()
    changed=diagnostic.capture_overlay(original)
    assert changed.count('os.Exit(97)')==1
    assert changed.index('os.Exit(97)')<changed.index('if !h.ActorBoundaries')
    assert original[original.index('\tif !h.ActorBoundaries'):]==changed[changed.index('\tif !h.ActorBoundaries'):]
    assert 'actor-visible history only; no live hidden state' in changed
