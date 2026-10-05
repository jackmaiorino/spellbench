"""Exact minimal bundle recovery with native structural fixtures only."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import gorge_reference_bundle as bundle
spec=importlib.util.spec_from_file_location('bundle_native_fixture',ROOT/'python/tests/test_gorge_hosted_gate.py')
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def arguments(tmp_path):
    native,runtime,pins=fixture.evidence.__wrapped__(tmp_path)
    for name in ('REGISTRY.json','spellbench-gorge-env-linux-amd64','spellbench-gorge-agent-linux-amd64'):
        (runtime/name).write_bytes(b'structural-fixture-only')
    (runtime/'SEAL.json').unlink()
    pins['runtime_seal_sha256']=fixture.seal(runtime)
    shutil.copytree(native,tmp_path/'native-cold')
    shutil.copytree(runtime,tmp_path/'runtime-cold')
    return dict(native=native,runtime=runtime,native_recovery=tmp_path/'native-cold',runtime_recovery=tmp_path/'runtime-cold',
        native_seal_sha256=pins['seal_sha256'],runtime_seal_sha256=pins['runtime_seal_sha256'],
        cleanup_sha256=pins['cleanup_sha256'],destination=tmp_path/'bundle',recovery=tmp_path/'bundle-cold')


def test_minimal_exact_bundle_preserves_declared_seals_and_independent_recovery(tmp_path):
    args=arguments(tmp_path)
    result=bundle.pack_bundle(**args)
    assert result['independent_recovery_verified'] and result['rated_games']==0
    assert result['native_verdict']['completed_games']==640 # Fixture counts, no played games.
    assert not result['private_secret_created'] and not result['evaluation_started']
    assert len(result['files'])==18
    for base in (args['destination'],args['recovery']):
        seal=json.loads((base/'SEAL.json').read_bytes())
        assert bundle.sha(base/result['archive_name'])==result['archive_sha256']
        assert all(bundle.sha(base/name)==pin['sha256'] for name,pin in seal['files'].items())
    assert (args['destination']/'SEAL.json').read_bytes()==(args['recovery']/'SEAL.json').read_bytes()


@pytest.mark.parametrize('failure',['no_cleanup','changed_native_recovery','changed_runtime_recovery','changed_agent','existing_root'])
def test_unverified_bundle_never_creates_dispatch_inputs(tmp_path,failure):
    args=arguments(tmp_path)
    if failure=='no_cleanup':(args['native']/'HOSTED-CLEANUP.json').unlink()
    elif failure=='changed_native_recovery':(args['native_recovery']/'artifact/MANIFEST.json').write_text('{}')
    elif failure=='changed_runtime_recovery':(args['runtime_recovery']/'registry.gob.gz').write_bytes(b'changed')
    elif failure=='changed_agent':(args['runtime']/'spellbench-gorge-agent-linux-amd64').write_bytes(b'changed')
    else:args['destination'].mkdir()
    with pytest.raises((bundle.NativeAuditGateError,RuntimeError,FileNotFoundError)):
        bundle.pack_bundle(**args)
    assert not args['recovery'].exists()
    assert not (args['destination']/'BUNDLE.json').exists()
