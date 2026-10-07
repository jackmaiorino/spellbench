"""Bounded private draft-asset exchange for one owned CI qualification job.

No result is posted to an issue or public release. Assets remain unpublished
until they are recovered, verified and deleted by the owning job watcher.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import threading
import time
import zipfile

REPOSITORY = 'jackmaiorino/spellbench'
NAME = re.compile(r'[a-z0-9][a-z0-9_.-]{0,159}')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def extract_pinned(archive, destination, *, cap_bytes):
    destination = Path(destination)
    if destination.exists():
        raise RuntimeError('Extraction requires a new owned directory')
    with zipfile.ZipFile(archive) as zipped:
        names = set()
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or '..' in path.parts or ':' in item.filename or '\\' in item.orig_filename or
                    stat.S_ISLNK(item.external_attr >> 16) or item.filename in names):
                raise RuntimeError('Unsafe or duplicate qualification archive member')
            names.add(item.filename)
        if sum(item.file_size for item in zipped.infolist()) > cap_bytes:
            raise RuntimeError('Qualification extraction exceeds its declared cap')
        destination.mkdir(parents=True)
        zipped.extractall(destination)


class DraftExchange:
    def __init__(self, *, release_id, scratch, deadline, api_runner=subprocess.run):
        if type(release_id) is not int or release_id <= 0:
            raise ValueError('A declared draft release ID is required')
        self.release_id = release_id
        self.scratch = Path(scratch)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.deadline = deadline
        self.api_runner = api_runner
        self.api_env = {key: value for key, value in os.environ.items() if key != 'GH_DEBUG'}
        metadata = self.api(f'repos/{REPOSITORY}/releases/{release_id}')
        if (metadata.get('draft') is not True or metadata.get('published_at') is not None or
                not metadata.get('tag_name', '').startswith('gorge-reference-')):
            raise RuntimeError('Qualification exchange must remain an unpublished draft')
        self.upload_url = metadata['upload_url'].split('{')[0]
        self.sequence = 0
        self.sequence_lock = threading.Lock()

    def private_path(self, prefix, name):
        with self.sequence_lock:
            self.sequence += 1
            return self.scratch / f'{prefix}-{self.sequence}-{name}'

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Owned qualification exchange deadline reached')
        return remaining

    def api(self, endpoint, *options, binary_file=None, timeout=90):
        args = ['gh', 'api', endpoint, *options]
        limit = min(timeout, max(1, int(self.remaining())))
        if binary_file is None:
            result = self.api_runner(args, env=self.api_env, capture_output=True, check=True, timeout=limit)
            if len(result.stdout) > 4 * 2**20:
                raise RuntimeError('Qualification API metadata exceeds its cap')
            return json.loads(result.stdout)
        with Path(binary_file).open('xb') as stream:
            self.api_runner(args, env=self.api_env, stdout=stream, stderr=subprocess.PIPE, check=True, timeout=limit)

    def assets(self):
        pages = self.api(f'repos/{REPOSITORY}/releases/{self.release_id}/assets?per_page=100', '--paginate', '--slurp')
        assets = [item for page in pages for item in page]
        if len(assets) > 900 or len({item['name'] for item in assets}) != len(assets):
            raise RuntimeError('Qualification exchange inventory exceeds cap or has duplicate names')
        return {item['name']: item for item in assets}

    def upload(self, name, path, *, cap_bytes):
        path = Path(path)
        if NAME.fullmatch(name) is None or path.stat().st_size > cap_bytes:
            raise RuntimeError('Qualification asset name or bytes exceed its declaration')
        existing = self.assets().get(name)
        if existing:
            if existing.get('digest') != 'sha256:' + sha(path) or existing['size'] != path.stat().st_size:
                raise RuntimeError('An existing immutable qualification asset differs')
            return existing
        asset = self.api(self.upload_url + '?name=' + name, '-X', 'POST', '-H',
            'Content-Type: application/octet-stream', '--input', str(path), timeout=300)
        if asset['size'] != path.stat().st_size or asset.get('digest') != 'sha256:' + sha(path):
            raise RuntimeError('Uploaded qualification asset does not match its hash')
        return asset

    def put_json(self, name, value):
        if NAME.fullmatch(name) is None:
            raise RuntimeError('Invalid qualification asset name')
        path = self.private_path('private', name)
        with path.open('x') as stream:
            json.dump(value, stream)
            stream.write('\n')
        path.chmod(0o600)
        return self.upload(name, path, cap_bytes=2 * 2**20)

    def download(self, asset, destination, *, cap_bytes):
        if asset['size'] > cap_bytes or asset['state'] != 'uploaded':
            raise RuntimeError('Download does not fit its declared asset budget')
        destination = Path(destination)
        self.api(f"repos/{REPOSITORY}/releases/assets/{asset['id']}", '-H',
            'Accept: application/octet-stream', binary_file=destination, timeout=300)
        if destination.stat().st_size != asset['size'] or 'sha256:' + sha(destination) != asset.get('digest'):
            raise RuntimeError('Downloaded qualification asset differs from its hash')
        return destination

    def wait_json(self, name, *, poll_seconds=15):
        if NAME.fullmatch(name) is None:
            raise RuntimeError('Invalid qualification response name')
        while True:
            asset = self.assets().get(name)
            if asset:
                path = self.download(asset, self.private_path('received', name), cap_bytes=2*2**20)
                return json.loads(path.read_bytes())
            time.sleep(min(poll_seconds, self.remaining()))
