"""Two persistent synthetic workers exchange receipts without external calls."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import gorge_ci_exchange as exchange
import gorge_reference_pool as pool
import gorge_reference_transport as transport

spec = importlib.util.spec_from_file_location('exchange_fixture_api',ROOT/'python/tests/test_gorge_ci_exchange.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class LockedAPI(fixture.FakeAPI):
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()

    def __call__(self,args,**kwargs):
        with self.lock:
            return super().__call__(args,**kwargs)


def client(api, scratch):
    return exchange.DraftExchange(release_id=17,scratch=scratch,
        deadline=time.monotonic()+30,api_runner=api)


def worker_fixture(tmp_path,index,*,fail=False):
    node = pool.PoolNode(f'node-{index}',4,16*2**30,90*2**30,'synthetic-source','native-fixture','runtime-fixture')
    stage = tmp_path/f'worker-{index}'
    stage.mkdir()
    calls = []
    def execute(request):
        calls.append(request)
        (stage/f"RECEIPT-{request['batch']}.json").write_text(json.dumps(dict(batch=request['batch'],fixture=True)))
        if fail:
            (stage/'FAILURE.json').write_text('{"error":"synthetic failure"}')
            raise ValueError('synthetic failure')
        return dict(batch=request['batch'],node_alias=node.alias,workload=request['workload'],results=[])
    value = SimpleNamespace(node=node,stage=stage,cfg=SimpleNamespace(to_json=lambda:{'fixture':True}),
        indices=(9,2,17,4),runtime_pins=[],native_verdict={'fixture':True},execute=execute,
        resource_guard=lambda:None)
    return value,calls


def test_two_persistent_workers_keep_skipped_batches_and_recover_every_receipt(tmp_path):
    api = LockedAPI()
    controller = client(api,tmp_path/'controller-exchange')
    connection = transport.NodeTransport(controller,poll_seconds=.002)
    nodes = [worker_fixture(tmp_path,index) for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        running = [executor.submit(transport.serve_node,value,client(api,tmp_path/f'exchange-{index}'),
                   poll_seconds=.002) for index,(value,_) in enumerate(nodes)]
        for index,(value,_) in enumerate(nodes):
            controller.wait_json(f'ready-node-{index}.json',poll_seconds=.002)
        for batch,active in ((1,[nodes[0]]),(2,nodes),(3,nodes),(4,[nodes[0]])):
            with ThreadPoolExecutor(max_workers=2) as dispatch:
                responses = [dispatch.submit(connection,value.node,
                    dict(batch=batch,workload='synthetic-workload',indices=[9],secret_hex='private-fixture'))
                    for value,_ in active]
                assert [future.result()['batch'] for future in responses]==[batch]*len(active)
        connection.stop([value.node for value,_ in nodes])
        for future in running:
            future.result(timeout=5)
    assert [[request['batch'] for request in calls] for _,calls in nodes]==[[1,2,3,4],[2,3]]
    assets = controller.assets()
    for index,expected in ((0,[1,2,3,4]),(1,[2,3])):
        closed = controller.wait_json(f'closed-node-{index}.json',poll_seconds=.002)
        archive = controller.download(assets[f'recovery-node-{index}.zip'],tmp_path/f'recovered-{index}.zip',cap_bytes=2**20)
        assert closed['recovery_asset_digest']=='sha256:'+exchange.sha(archive)
        with zipfile.ZipFile(archive) as zipped:
            inventory=json.loads(zipped.read('RECOVERY-INVENTORY.json'))
            assert set(inventory['files'])=={f'RECEIPT-{batch}.json' for batch in expected}
            assert inventory['rated_games']==0


def test_failure_reaches_coordinator_and_keeps_worker_recovery(tmp_path):
    api = LockedAPI()
    value,calls = worker_fixture(tmp_path,0,fail=True)
    controller = client(api,tmp_path/'controller')
    connection = transport.NodeTransport(controller,poll_seconds=.002)
    with ThreadPoolExecutor(max_workers=1) as executor:
        running=executor.submit(transport.serve_node,value,client(api,tmp_path/'worker-exchange'),poll_seconds=.002)
        controller.wait_json('ready-node-0.json',poll_seconds=.002)
        with pytest.raises(RuntimeError,match='ValueError: synthetic failure'):
            connection(value.node,dict(batch=1,workload='fixture',indices=[9]))
        with pytest.raises(ValueError,match='synthetic failure'):
            running.result(timeout=5)
    assert controller.wait_json('closed-node-0.json',poll_seconds=.002)['last_completed_batch']==0
    archive=controller.download(controller.assets()['recovery-node-0.zip'],tmp_path/'failed.zip',cap_bytes=2**20)
    with zipfile.ZipFile(archive) as zipped:
        assert 'FAILURE.json' in zipped.namelist()


def test_recovery_never_archives_itself_or_exceeds_budget(tmp_path):
    api = LockedAPI()
    value,_ = worker_fixture(tmp_path,0)
    (value.stage/'RECEIPT.json').write_text('{}')
    with pytest.raises(RuntimeError,match='outside'):
        transport.snapshot_worker(value,client(api,value.stage/'exchange'))
    with pytest.raises(RuntimeError,match='uncompressed budget'):
        transport.snapshot_worker(value,client(api,tmp_path/'exchange'),cap_bytes=1)
