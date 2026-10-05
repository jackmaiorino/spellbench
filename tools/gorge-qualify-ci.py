"""Run the supported native qualification on a standard public GitHub runner.

Inputs arrive as a hash-pinned draft release asset. All simulation goes through
qualify_native.py and its matched completed-work throughput guard.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import zipfile

RESERVE = 60 * 2**30
CAP = 2 * 2**30
UPLOAD_CAP = 256 * 2**20
WALL = 5 * 3600


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    job = args.job.resolve()
    job.mkdir()
    stage = job / 'native'
    stage.mkdir()
    inputs = json.loads(args.inputs.read_bytes())
    write(stage / 'INPUTS.json', inputs)
    if inputs['conservative_reserved_total_usd'] > 10 or inputs['scope'] != 'native qualification only':
        raise RuntimeError('Native CI has no admitted budget or scope')
    if os.environ.get('GITHUB_REPOSITORY') != 'jackmaiorino/spellbench' or inputs['repository_private']:
        raise RuntimeError('Only the declared standard public repository runner is eligible')
    sys.path.insert(0, str(source / 'python'))
    from spellbench.arena import machine
    from spellbench.arena.qualification import current_rules
    from spellbench.arena.allocation import Placement
    Placement.parse(inputs['placement'])
    archive = job / 'runtime.zip'
    asset = inputs['release_asset_id']
    if type(asset) is not int or asset <= 0:
        raise ValueError('Invalid draft asset ID')
    with archive.open('xb') as output:
        subprocess.run(['gh', 'api', f'repos/jackmaiorino/spellbench/releases/assets/{asset}',
                        '-H', 'Accept: application/octet-stream'], stdout=output, check=True, timeout=300)
    if sha(archive) != inputs['archive_sha256'] or archive.stat().st_size > 128 * 2**20:
        raise RuntimeError('Runtime archive differs from its pin or byte budget')
    runtime = job / 'runtime'
    runtime.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)) or set(names) != set(inputs['files']):
            raise RuntimeError('Runtime archive file inventory differs')
        if sum(item.file_size for item in zipped.infolist()) > 128 * 2**20:
            raise RuntimeError('Runtime extraction exceeds byte budget')
        for name in names:
            if Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('Runtime archive paths must be plain file names')
            with zipped.open(name) as incoming, (runtime / name).open('xb') as output:
                shutil.copyfileobj(incoming, output)
            if sha(runtime / name) != inputs['files'][name]['sha256']:
                raise RuntimeError('Extracted runtime input differs from its pin')
            if name.endswith('linux-amd64'):
                (runtime / name).chmod(0o700)
    # Go identity is independent of the Python placement addition. Current
    # Python source is recorded and requalified, never inherited from RunPod.
    subprocess.run(['git', 'fetch', '--depth=1', 'origin', inputs['runtime_source_commit']], check=True, timeout=90)
    if subprocess.check_output(['git', 'diff', inputs['runtime_source_commit'], 'HEAD', '--', 'engines/gorge']):
        raise RuntimeError('Compiled engine source differs from the pinned runtime')
    cores, memory = machine.usable_cpus(), machine.total_memory()
    if memory is None:
        raise RuntimeError('Runner memory limit is unavailable')
    choices = [n for n in range(2, min(cores, max(1, memory // 2**30 - 2)) + 1)
               if current_rules().ladder_fits(320, n)]
    if not choices or machine.free_bytes(job) < RESERVE + CAP:
        raise RuntimeError('Runner cannot satisfy parallel or storage qualification')
    cap = max(choices)
    script = source / 'engines/gorge/scripts/qualify_native.py'
    write(stage / 'MANIFEST.json', dict(schema='spellbench-gorge-ci-native/v1', at_utc=stamp(),
        phase='prepared', source_commit=os.environ['GITHUB_SHA'], runtime_source_commit=inputs['runtime_source_commit'],
        script_sha256=sha(script), parent_sha256=sha(Path(__file__)), usable_cpus=cores, memory_limit_bytes=memory,
        worker_cap=cap, worker_ladder=current_rules().ladder(cap), placement=inputs['placement'],
        projected_bytes=256 * 2**20, cap_bytes=CAP, uploaded_bytes_cap=UPLOAD_CAP,
        reserve_bytes=RESERVE, wall_cap_seconds=WALL, rated_games=0, gpu_ordinal=None,
        guard_path='gorge-qualify-ci.py -> qualify_native.py -> arena.throughput.plan_allocation'))
    native = runtime / 'gorgequal-linux-amd64'
    env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN', 'RUNPOD_API_KEY')}
    env.update(GOMAXPROCS='1', GORGE_JOB_ROOT=str(job), GORGE_SOURCE_ROOT=str(source), GORGE_CLOUD_STAGE=str(stage),
        GORGE_NATIVE_QUALIFIER=str(native), GORGE_NATIVE_QUALIFIER_SHA256=sha(native),
        GORGE_REGISTRY=str(runtime / 'registry.gob.gz'), GORGE_NATIVE_WORKER_CAP=str(cap),
        GORGE_NATIVE_CALLBACK_WALL_SECONDS=str(WALL - 120), SPELLBENCH_HOST_ALIAS='gorge-github-standard',
        GORGE_PLACEMENT=inputs['placement'], PYTHONUNBUFFERED='1')
    started = time.monotonic()
    reason = None
    offsets, partial = {}, {}
    with (stage / 'stdout.jsonl').open('xb') as stdout, (stage / 'stderr.log').open('xb') as stderr:
        process = subprocess.Popen([sys.executable, str(script)], cwd=source, env=env,
            stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                size = sum(p.stat().st_size for p in job.rglob('*') if p.is_file())
                result_size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
                if elapsed > WALL or (job / 'STOP').exists():
                    reason = 'wall_or_STOP'
                if size > CAP or result_size > UPLOAD_CAP - 32 * 2**20 or machine.free_bytes(job) < RESERVE:
                    reason = 'storage_cap_or_reserve'
                for path in stage.glob('*/stdout.jsonl'):
                    with path.open('rb') as stream:
                        stream.seek(offsets.get(path, 0))
                        fresh = stream.read()
                        offsets[path] = stream.tell()
                    lines = (partial.get(path, b'') + fresh).split(b'\n')
                    partial[path] = lines.pop()
                    for line in lines:
                        try:
                            row = json.loads(line).get('qualification_row', {})
                        except (ValueError, UnicodeDecodeError):
                            continue
                        for cell, coverage in row.get('search_coverage', {}).items():
                            if cell.endswith('redeal') and (coverage.get('ReconstructionBudgetExhausted', 0) or coverage.get('RedealRefusals')):
                                reason = 'existing_native_redeal_gate_failed'
                                write(stage / 'EARLY-NATIVE-FAILURE.json', dict(at_utc=stamp(), game=row.get('game'),
                                    cell=cell, coverage=coverage, gate='Unchanged Report.Clean zero-refusal gate'))
                sample = dict(at_utc=stamp(), elapsed_seconds=elapsed, bytes=size,
                    free_bytes=machine.free_bytes(job), stop_reason=reason,
                    load_average=os.getloadavg(), cpu_stat=Path('/proc/stat').read_text().splitlines()[0])
                with (stage / 'METRICS.jsonl').open('a') as stream:
                    stream.write(json.dumps(sample) + '\n')
                print(json.dumps(sample), flush=True)
                if reason:
                    break
                time.sleep(60)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    write(stage / 'CLOSURE.json', dict(at_utc=stamp(), exit_code=process.returncode, stop_reason=reason,
        elapsed_seconds=time.monotonic() - started, native_passed=process.returncode == 0 and reason is None, rated_games=0))
    return process.returncode if process.returncode else (1 if reason else 0)


if __name__ == '__main__':
    sys.exit(main())
