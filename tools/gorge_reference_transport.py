"""Private dispatch and recovery for persistent reference workers.

The owning CI launcher still provides wall/resource supervision and recovery
of all exchange assets. These functions neither start CI nor publish a release.
"""
import json
from pathlib import Path
import re
import time
import zipfile

from gorge_ci_exchange import NAME, sha


def read_json(client, asset):
    path = client.private_path('received', asset['name'])
    client.download(asset, path, cap_bytes=2*2**20)
    return json.loads(path.read_bytes())


class NodeTransport:
    def __init__(self, client, *, poll_seconds=15, sleep=time.sleep):
        self.client, self.poll_seconds, self.sleep = client, poll_seconds, sleep

    def __call__(self, node, request):
        base = f"{node.alias}-batch-{request['batch']}"
        if NAME.fullmatch(base + '.json') is None:
            raise ValueError('Invalid owned worker or batch identity')
        self.client.put_json('request-' + base + '.json', request)
        while True:
            assets = self.client.assets()
            failed = assets.get('failure-' + base + '.json')
            if failed:
                failure = read_json(self.client, failed)
                raise RuntimeError(f"Reference worker {node.alias} failed batch {request['batch']}: "
                                   + failure['error_type'] + ': ' + failure['detail'])
            response = assets.get('response-' + base + '.json')
            if response:
                return read_json(self.client, response)
            self.sleep(min(self.poll_seconds, self.client.remaining()))

    def ready(self, alias):
        while True:
            assets = self.client.assets()
            failure = assets.get(f'supervised-{alias}.json')
            if failure:
                terminal = read_json(self.client, failure)
                if terminal['exit_code'] != 0 or terminal['stop_reason'] is not None:
                    raise RuntimeError(f'Reference worker {alias} failed before pool readiness')
            ready = assets.get(f'ready-{alias}.json')
            if ready:
                return read_json(self.client, ready)
            self.sleep(min(self.poll_seconds, self.client.remaining()))

    def stop(self, nodes):
        for node in nodes:
            self.client.put_json(f'stop-{node.alias}.json', dict(node_alias=node.alias,
                scope='stop this owned reference worker and preserve recovery', rated_games=0))


def snapshot_worker(worker, client, *, cap_bytes=256*2**20):
    """Return every worker receipt, including failures, as a bounded archive."""
    stage = Path(worker.stage).resolve()
    archive = client.private_path('recovery', f'{worker.node.alias}.zip')
    if archive.resolve().is_relative_to(stage):
        raise RuntimeError('Worker recovery must be outside the archived stage')
    files = {}
    for path in sorted(stage.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError('Worker recovery contains a link outside its owned stage')
        if path.is_file():
            files[path.relative_to(stage).as_posix()] = dict(bytes=path.stat().st_size, sha256=sha(path))
    if sum(value['bytes'] for value in files.values()) > cap_bytes - 2*2**20:
        raise RuntimeError('Worker recovery exceeds its declared uncompressed budget')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in files:
            zipped.write(stage / name, name)
        zipped.writestr('RECOVERY-INVENTORY.json', json.dumps(dict(files=files,
            node=worker.node.__dict__, native_verdict=worker.native_verdict,
            rated_games=0)) + '\n')
    return client.upload(f'recovery-{worker.node.alias}.zip', archive, cap_bytes=cap_bytes)


def serve_node(worker, client, *, poll_seconds=15, sleep=time.sleep):
    """One worker remains on its original VM for comparison, matrix and replay."""
    alias = worker.node.alias
    if NAME.fullmatch(f'ready-{alias}.json') is None:
        raise ValueError('Invalid owned worker identity')
    prefix = 'request-' + alias + '-batch-'
    pattern = re.compile(re.escape(prefix) + r'([1-7])\.json')
    client.put_json(f'ready-{alias}.json', dict(node=worker.node.__dict__,
        native_verdict=worker.native_verdict, runtime_pins=worker.runtime_pins,
        configuration=worker.cfg.to_json(), indices=worker.indices,
        per_node_game_slots=1, rated_games=0))
    last_batch = 0
    try:
        while True:
            worker.resource_guard()
            assets = client.assets()
            if f'stop-{alias}.json' in assets:
                break
            pending = sorted((int(match[1]), asset) for name, asset in assets.items()
                             if (match := pattern.fullmatch(name)) and int(match[1]) > last_batch)
            if not pending:
                sleep(min(poll_seconds, client.remaining()))
                continue
            if len(pending) != 1:
                raise RuntimeError('Coordinator queued another dispatch before worker completion')
            batch, asset = pending[0]
            base = f'{alias}-batch-{batch}'
            try:
                response = worker.execute(read_json(client, asset))
                client.put_json('response-' + base + '.json', response)
            except BaseException as error:
                client.put_json('failure-' + base + '.json', dict(batch=batch, node_alias=alias,
                    error_type=type(error).__name__, detail=str(error), rated_games=0))
                raise
            last_batch = batch
    finally:
        # Recovery happens before the owning watcher deletes the exchange.
        asset = snapshot_worker(worker, client)
        client.put_json(f'closed-{alias}.json', dict(node_alias=alias,
            recovery_asset_id=asset['id'], recovery_asset_digest=asset['digest'],
            last_completed_batch=last_batch, rated_games=0))
