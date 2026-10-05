"""Terminal failure recovery must preserve independent bytes before deletion."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import gorge_reference_bundle as bundle
import gorge_ci_exchange as exchange

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

watch=module('gorge_reference_watcher',ROOT/'tools/gorge-watch-reference.py')
fixtures=module('reference_recovery_bundle_fixture',ROOT/'python/tests/test_gorge_reference_bundle.py')
api_fixture=module('reference_recovery_api_fixture',ROOT/'python/tests/test_gorge_ci_exchange.py')


class API(api_fixture.FakeAPI):
    def __init__(self,hot,cold):
        super().__init__()
        self.hot,self.cold=hot,cold
        self.deleted=False

    def __call__(self,args,**kwargs):
        if args[2].endswith('/releases/17') and 'DELETE' in args:
            # No externally visible deletion before both independently checked
            # recovery seals are present and identical.
            assert (self.hot/'SEAL.json').read_bytes()==(self.cold/'SEAL.json').read_bytes()
            seal=json.loads((self.cold/'SEAL.json').read_bytes())
            assert all(exchange.sha(self.hot/name)==pin['sha256']==exchange.sha(self.cold/name)
                       for name,pin in seal['files'].items())
            self.deleted=True
            return subprocess.CompletedProcess(args,0,stdout=b'')
        if self.deleted and args[2].endswith('/releases/17'):
            return subprocess.CompletedProcess(args,1,stdout=b'',stderr=b'HTTP404')
        return super().__call__(args,**kwargs)


def prepared(tmp_path):
    arguments=fixtures.arguments(tmp_path)
    packed=bundle.pack_bundle(**arguments)
    hot,cold=tmp_path/'hot',tmp_path/'cold'
    hot.mkdir();cold.mkdir()
    api=API(hot,cold)
    client=exchange.DraftExchange(release_id=17,scratch=hot/'exchange',deadline=time.monotonic()+60,api_runner=api)
    asset=client.upload('reference-inputs.zip',arguments['destination']/'reference-inputs.zip',cap_bytes=256*2**20)
    inputs=dict(packed,release_asset_id=asset['id'],pool_slots=2,conservative_reserved_total_usd=9.96136347)
    run=dict(id=19,status='completed',conclusion='failure',head_sha='a'*40,run_attempt=1,
             name='gorge guarded reference pool',repository=dict(full_name='jackmaiorino/spellbench'))
    def logs(args,**kwargs):
        kwargs['stdout'].write(b'synthetic terminal failure log\n')
        return subprocess.CompletedProcess(args,0)
    return client,inputs,run,hot,cold,api,logs


def test_failed_reference_run_is_recovered_and_cleaned_without_a_pass_claim(tmp_path):
    client,inputs,run,hot,cold,api,logs=prepared(tmp_path)
    record,cleanup=watch.recover_terminal(client,run=run,inputs=inputs,head_sha='a'*40,
        hot=hot,cold=cold,source=ROOT,log_runner=logs)
    assert api.deleted and not record['reference_qualification_passed'] and record['rated_games']==0
    assert record['independent_recovery_verified'] and cleanup['hosted_exchange_deletion_verified']
    assert cleanup['recovery_seal_sha256']==exchange.sha(cold/'SEAL.json')
    assert (hot/'HOSTED-CLEANUP.json').read_bytes()==(cold/'HOSTED-CLEANUP.json').read_bytes()


@pytest.mark.parametrize('change',[dict(status='in_progress'),dict(head_sha='b'*40),dict(run_attempt=2),dict(name='other workflow')])
def test_changed_or_nonterminal_run_cannot_delete_the_exchange(tmp_path,change):
    client,inputs,run,hot,cold,api,logs=prepared(tmp_path)
    with pytest.raises(RuntimeError,match='original exact terminal'):
        watch.recover_terminal(client,run={**run,**change},inputs=inputs,head_sha='a'*40,
            hot=hot,cold=cold,source=ROOT,log_runner=logs)
    assert not api.deleted


def test_changed_input_asset_is_not_deleted_or_relabelled_as_recovered(tmp_path):
    client,inputs,run,hot,cold,api,logs=prepared(tmp_path)
    api.saved['reference-inputs.zip']['metadata']['digest']='sha256:'+'0'*64
    with pytest.raises(RuntimeError,match='input asset changed'):
        watch.recover_terminal(client,run=run,inputs=inputs,head_sha='a'*40,
            hot=hot,cold=cold,source=ROOT,log_runner=logs)
    assert not api.deleted and not (cold/'SEAL.json').exists()
