"""Transport integrity checks using a fake API and local archives only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gorge_ci_exchange',ROOT/'tools/gorge_ci_exchange.py')
exchange=importlib.util.module_from_spec(spec)
spec.loader.exec_module(exchange)


class FakeAPI:
    def __init__(self,draft=True):
        self.draft=draft
        self.saved={}
        self.calls=[]

    def __call__(self,args,**kwargs):
        self.calls.append(args)
        endpoint=args[2]
        if endpoint.endswith('/releases/17'):
            value=dict(draft=self.draft,published_at=None,tag_name='gorge-reference-fixture',
                upload_url='https://uploads.github.com/repos/jackmaiorino/spellbench/releases/17/assets{?name}')
        elif 'assets?per_page' in endpoint:
            value=[[asset['metadata'] for asset in self.saved.values()]]
        elif endpoint.startswith('https://uploads.'):
            name=endpoint.split('?name=')[1]
            data=Path(args[args.index('--input')+1]).read_bytes()
            metadata=dict(id=len(self.saved)+1,name=name,size=len(data),state='uploaded',
                digest='sha256:'+hashlib.sha256(data).hexdigest())
            self.saved[name]=dict(metadata=metadata,data=data)
            value=metadata
        else:
            asset=next(asset for asset in self.saved.values() if endpoint.endswith('/'+str(asset['metadata']['id'])))
            kwargs['stdout'].write(asset['data'])
            return subprocess.CompletedProcess(args,0)
        return subprocess.CompletedProcess(args,0,stdout=json.dumps(value).encode())


def test_private_json_roundtrip_and_immutable_idempotent_upload(tmp_path):
    api=FakeAPI()
    client=exchange.DraftExchange(release_id=17,scratch=tmp_path/'scratch',deadline=time.monotonic()+60,api_runner=api)
    value={'indices':[5,9],'secret_hex':'fixture-only-never-a-credential'}
    first=client.put_json('request-1.json',value)
    assert client.wait_json('request-1.json')==value
    assert client.put_json('request-1.json',value)['id']==first['id']
    with pytest.raises(RuntimeError,match='immutable'):
        client.put_json('request-1.json',{'indices':[10]})
    assert all('fixture-only-never-a-credential' not in part for args in api.calls for part in args)


def test_published_or_wrong_draft_cannot_be_used(tmp_path):
    with pytest.raises(RuntimeError,match='unpublished'):
        exchange.DraftExchange(release_id=17,scratch=tmp_path,deadline=time.monotonic()+60,api_runner=FakeAPI(False))


def test_download_rejects_changed_bytes(tmp_path):
    api=FakeAPI()
    client=exchange.DraftExchange(release_id=17,scratch=tmp_path/'scratch',deadline=time.monotonic()+60,api_runner=api)
    asset=client.put_json('request-1.json',{'fixture':True})
    api.saved['request-1.json']['data']=b'tampered'
    with pytest.raises(RuntimeError,match='differs'):
        client.download(asset,tmp_path/'bad.json',cap_bytes=1024)


@pytest.mark.parametrize('name',['../escape','/absolute','C:/drive','a\\escape'])
def test_archive_paths_cannot_escape_owned_extraction(tmp_path,name):
    archive=tmp_path/'bad.zip'
    info=zipfile.ZipInfo('fixture')
    info.filename=name
    with zipfile.ZipFile(archive,'w') as zipped:zipped.writestr(info,b'fixture')
    with pytest.raises(RuntimeError,match='Unsafe'):
        exchange.extract_pinned(archive,tmp_path/'out',cap_bytes=1024)
    assert not (tmp_path/'out').exists()


def test_archive_cap_and_regular_extraction(tmp_path):
    archive=tmp_path/'good.zip'
    with zipfile.ZipFile(archive,'w') as zipped:zipped.writestr('evidence/receipt.json',b'{}')
    with pytest.raises(RuntimeError,match='cap'):
        exchange.extract_pinned(archive,tmp_path/'too-small',cap_bytes=1)
    exchange.extract_pinned(archive,tmp_path/'out',cap_bytes=1024)
    assert (tmp_path/'out/evidence/receipt.json').read_bytes()==b'{}'
