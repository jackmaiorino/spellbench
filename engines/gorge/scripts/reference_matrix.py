"""Guarded reference-host qualification of all twelve gorge modes and five decks."""
import datetime
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

JOB = Path(os.environ.get('GORGE_JOB_ROOT','/workspace/gorge'))
ROOT = JOB/'source'
sys.path.insert(0, str(ROOT / 'python'))
from spellbench.arena import config, runner, store
from spellbench.arena.schedule import preflight, schedule
from spellbench.bench import definition, run as bench_run
from spellbench.arena.throughput import Placement, resource_bound, usable_cpus
from spellbench.run_secret import RunSecret

STAGE = Path(os.environ['GORGE_CLOUD_STAGE'])
RUNTIME = Path(os.environ.get('GORGE_CLOUD_RUNTIME',str(JOB/'runtime')))

def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, path)

def private_secret(path, secret):
    with path.open('x') as handle:
        json.dump({'schema':'spellbench-private-qualification-secret/v1', 'rated':False,
                   'secret_hex':secret.hex(), 'commitment':secret.commitment()}, handle)
        handle.write('\n')
    path.chmod(0o600)

def join_receipts(row, directory):
    values = [json.loads(p.read_bytes()) for p in directory.glob('gorge-agent-*.json')]
    joined = []
    for seat in row['seats']:
        if not seat['name'].startswith('gorge-'):
            continue
        matching = [v for v in values if v['game_id'] == row['game_id']
                    and v['seat'] == seat['seat'] and v['bot_name'] == seat['name']]
        if len(matching) != 1:
            raise RuntimeError('Expected one closed native receipt per game and seat')
        value = matching[0]
        if value['schema'] != 'spellbench-gorge-policy-audit/v1' or value['version'] != seat['version']:
            raise RuntimeError('Native receipt identity differs from the ledger')
        if not value['game_started'] or not value['game_over_received']:
            raise RuntimeError('Native receipt lacks the complete game lifecycle')
        joined.append(value)
    return joined

def mapping_pass(native, bad):
    return 100 * bad < native if native else bad == 0

def main():
    started = time.perf_counter()
    placement = os.environ['GORGE_PLACEMENT']
    Placement.parse(placement)
    assigned = int(os.environ['GORGE_ASSIGNED_DISK_BYTES'])
    os.environ['GOMAXPROCS'] = '1'
    values = {'GORGE_SPELLBENCH_ENV':str(RUNTIME/'spellbench-gorge-env-linux-amd64'),
              'GORGE_SPELLBENCH_AGENT':str(RUNTIME/'spellbench-gorge-agent-linux-amd64'),
              'GORGE_REGISTRY':str(RUNTIME/'registry.gob.gz'),
              'GORGE_REGISTRY_SHA256':'42ddaff112267bb2554d1cdb5c09a7637c70f6f738bc4e21911b191fa7d19937'}
    original_free = bench_run.machine.free_bytes
    def assigned_free(path):
        actual = original_free(path)
        if Path(path).resolve().is_relative_to(Path('/workspace')):
            used = int(subprocess.check_output(['du','-s','-B','1','/workspace'], text=True, timeout=10).split()[0])
            return min(actual, assigned - used)
        return actual
    bench_run.machine.free_bytes = assigned_free
    benchmark = definition.load_benchmark(ROOT/'benchmarks/pauper-gorge')
    cfg = config.TournamentConfig.from_json(benchmark.tournament_config(str(STAGE/'diagnostics')))
    cfg = runner.executed_config(cfg, lambda text: definition.substitute(text, values))
    configured_workers = cfg.workers
    rules = benchmark.qualification_rules()
    eligible_workers = min(configured_workers, resource_bound(usable_cpus(), cfg.per_game_cores()))
    # This shorter unrated matrix needs its own measured ladder. A bound that
    # cannot fit the qualification budget would select the small-run path,
    # which only probes serially before using its configured workers.
    measured_bounds = [workers for workers in range(2, eligible_workers + 1)
                       if rules.ladder_fits(120, workers)]
    if not measured_bounds:
        raise RuntimeError('No parallel reference-host ladder fits the current resources and qualification budget')
    cfg = replace(cfg, workers=max(measured_bounds))
    files = bench_run.run_files(cfg)
    prior_secret = os.environ.get('GORGE_MATRIX_SECRET_FILE')
    secret = (RunSecret.from_hex(json.loads(Path(prior_secret).read_bytes())['secret_hex'])
              if prior_secret else RunSecret.generate())
    private_secret(STAGE/'PRIVATE-MATRIX-SECRET.json', secret)
    contexts = schedule(cfg, secret)
    chosen = [c for c in contexts if c.pair_index < 5
              and any(s.name == 'uniform' for _, s in c.seat_specs)
              and any(s.name.startswith('gorge-') for _, s in c.seat_specs)]
    # Search games first gives the guarded sample representative expensive work.
    chosen.sort(key=lambda c: (not any('search' in s.name for _, s in c.seat_specs), c.game_index))
    if len(chosen) != 120:
        raise RuntimeError('Frozen all-mode/all-deck matrix must contain 120 games')
    expected = {(next(s.name for _,s in c.seat_specs if s.name.startswith('gorge-')), c.decks[0].catalog_id)
                for c in chosen}
    if len(expected) != 60:
        raise RuntimeError('Matrix omits a policy/deck cell')
    manifest = json.loads((STAGE/'MANIFEST.json').read_bytes())
    manifest.update(started_at_utc=stamp(), executed_config=cfg.to_json(),
                    launch_files=[f.to_json() for f in files], python=sys.version,
                    configured_benchmark_workers=configured_workers,
                    reference_qualification_worker_bound=cfg.workers,
                    reference_qualification_rules=rules.to_json(),
                    secret_commitment=secret.commitment(), selected_indices=[c.game_index for c in chosen],
                    prior_qualification_secret=prior_secret,
                    expected_cells=[list(cell) for cell in sorted(expected)],
                    scope='reference-host clocks, lifecycle, native mapping and search coverage; not native leak/parity qualification or ratings')
    write(STAGE/'MANIFEST.json', manifest)
    original_qualification = bench_run.qualification_play
    state = {'trial':0, 'directory':None}
    def preserve(*args, **kwargs):
        play = original_qualification(*args, **kwargs)
        cells = dict(zip(play.__code__.co_freevars, play.__closure__ or ()))
        guard_secret = cells['secret'].cell_contents
        private_secret(STAGE/'PRIVATE-GUARD-SECRET.json', guard_secret)
        def measured(workers, positions):
            state['trial'] += 1
            directory = STAGE/'guard-native-audits'/f"trial-{state['trial']}-workers-{workers}"
            directory.mkdir(parents=True)
            state['directory'] = directory
            os.environ['GORGE_AGENT_AUDIT_DIR'] = str(directory)
            return play(workers, positions)
        return measured
    bench_run.qualification_play = preserve
    original_append = store.append_ledger_row
    def journal(path, value):
        original_append(path, value)
    def guard_record(path, row):
        original_append(path, row)
        journal(state['directory']/'joined.jsonl', {'game_index':row['game_index'], 'policy_receipts':join_receipts(row, state['directory'])})
        print(json.dumps({'guard_game':row['game_index'], 'classification':row['classification'], 'at_utc':stamp()}), flush=True)
        if row['classification'] != 'natural':
            raise RuntimeError('Guard sample did not complete naturally')
    store.append_ledger_row = guard_record
    try:
        allocation = bench_run.plan_for(cfg, games=[c.game_index for c in chosen], placement=placement,
            evidence=STAGE/'throughput-evidence.json', volumes={'run_dir':STAGE}, files=files,
            rules=rules)
    finally:
        store.append_ledger_row = original_append
        bench_run.qualification_play = original_qualification
    write(STAGE/'ALLOCATION.json', allocation.to_json())
    if allocation.kind != 'substantial' or allocation.outputs_identical is not True:
        raise RuntimeError('The reference-host matrix requires completed serial/parallel scaling with identical primary rows')
    setup = preflight(cfg, secret)
    entries = {e.name:e for e in runner.registry_entries(cfg,cfg)}
    directory = STAGE/'matrix-native-audits'
    directory.mkdir()
    os.environ['GORGE_AGENT_AUDIT_DIR'] = str(directory)
    ledger = STAGE/'matches.jsonl'
    aggregates = {}
    bad_rows = []
    seconds = []
    def record(outcome):
        row = outcome.row.to_json()
        original_append(ledger, row)
        receipts = join_receipts(row, directory)
        journal(STAGE/'policy-joins.jsonl', {'game_index':row['game_index'], 'game_id':row['game_id'],
                'decks':row['decks'], 'policy_receipts':receipts})
        context = contexts[row['game_index']]
        for receipt in receipts:
            key = receipt['bot_name']+'/'+context.decks[0].catalog_id
            aggregate = aggregates.setdefault(key, {'policy':receipt['policy'], 'games':0,
                'native_decisions':0, 'bad_native_decisions':0, 'search':{}})
            aggregate['games'] += 1
            aggregate['native_decisions'] += receipt['native_decisions']
            aggregate['bad_native_decisions'] += receipt['ForcedNatives']+receipt['FallbackNatives']
            for key2,value in receipt['search'].items():
                if isinstance(value,int):
                    aggregate['search'][key2] = aggregate['search'].get(key2,0)+value
                elif isinstance(value,dict):
                    target = aggregate['search'].setdefault(key2,{})
                    for reason,count in value.items(): target[reason]=target.get(reason,0)+count
        if row['classification'] != 'natural': bad_rows.append(row['game_index'])
        seconds.append({'game_index':row['game_index'], 'seconds':outcome.seconds})
        write(STAGE/'PROGRESS.json', {'at_utc':stamp(), 'completed_games':len(seconds),
            'expected_games':120, 'bad_rows':bad_rows, 'aggregates':aggregates})
        print(json.dumps({'matrix_game':row['game_index'], 'classification':row['classification'],
                          'seconds':outcome.seconds, 'completed':len(seconds), 'at_utc':stamp()}), flush=True)
    result = runner.play_games(cfg, setup, chosen, run_secret=secret, entries=entries,
        workers=allocation.workers, stop_on_violation=True, timed=True, on_outcome=record, launch_files=files)
    if result.error is not None: raise result.error
    failures = []
    redealt = {}
    for key, aggregate in aggregates.items():
        if aggregate['games'] != 2: failures.append(key+': incomplete seat pair')
        if not mapping_pass(aggregate['native_decisions'], aggregate['bad_native_decisions']):
            failures.append(key+': native mapping is not under one percent')
        policy = aggregate['policy']
        if policy.startswith('search'):
            search = aggregate['search']
            if search.get('Eligible',0) == 0 or search.get('Covered',0) == 0:
                failures.append(key+': no eligible and covered native search')
            if policy.endswith('redeal'):
                redealt[policy] = redealt.get(policy,0)+search.get('Redealt',0)
                if search.get('ReconstructionBudgetExhausted',0) or search.get('RedealRefusals',{}):
                    failures.append(key+': redeal reconstruction refused or exhausted')
    for policy,n in redealt.items():
        if n == 0: failures.append(policy+': no accepted redealt world')
    if bad_rows: failures.append('non-natural matrix games: '+str(bad_rows))
    if len(aggregates) != 60 or len(seconds) != 120: failures.append('incomplete matrix')
    if len(seconds) != 120:
        report = {'schema':'spellbench-gorge-reference-host-matrix/v1', 'at_utc':stamp(),
            'passed':False, 'failures':failures, 'completed_games':len(seconds), 'cells':aggregates,
            'allocation':allocation.to_json(), 'game_seconds':seconds, 'wall_seconds':time.perf_counter()-started,
            'ledger_sha256':hashlib.sha256(ledger.read_bytes()).hexdigest(),
            'replay_identical':False, 'replay_status':'not reached after incomplete matrix',
            'rated_games':0, 'full_native_audit_passed':False}
        write(STAGE/'MATRIX.json', report)
        return 1
    # Replay a search/Burn seed, fixed from labels before any outcome is inspected.
    replay_context = next(c for c in chosen if c.decks[0].catalog_id == 'Burn'
                          and any('search' in s.name for _,s in c.seat_specs))
    replay_dir = STAGE/'replay-native-audits'
    replay_dir.mkdir()
    os.environ['GORGE_AGENT_AUDIT_DIR'] = str(replay_dir)
    replay_result = runner.play_games(cfg, setup, [replay_context], run_secret=secret, entries=entries,
        workers=1, stop_on_violation=True, timed=True, launch_files=files)
    if replay_result.error is not None: raise replay_result.error
    replay_row = replay_result.outcomes[0].row.to_json()
    original_row = next(json.loads(line) for line in ledger.read_text().splitlines()
                        if json.loads(line)['game_index'] == replay_context.game_index)
    original_append(STAGE/'replay-original.jsonl', original_row)
    original_append(STAGE/'replay.jsonl', replay_row)
    replay_identical = (STAGE/'replay-original.jsonl').read_bytes() == (STAGE/'replay.jsonl').read_bytes()
    if not replay_identical: failures.append('search/Burn seed replay differs')
    report = {'schema':'spellbench-gorge-reference-host-matrix/v1', 'at_utc':stamp(),
        'passed':not failures, 'failures':failures, 'completed_games':len(seconds), 'cells':aggregates,
        'allocation':allocation.to_json(), 'game_seconds':seconds, 'wall_seconds':time.perf_counter()-started,
        'ledger_sha256':hashlib.sha256(ledger.read_bytes()).hexdigest(),
        'replay_identical':replay_identical, 'replay_game_index':replay_context.game_index,
        'replay_store_sha256':hashlib.sha256((STAGE/'replay.jsonl').read_bytes()).hexdigest(),
        'rated_games':0, 'full_native_audit_passed':False}
    write(STAGE/'MATRIX.json', report)
    print(json.dumps({'matrix_closed':{'passed':not failures,'failures':failures,'games':len(seconds),
                                     'wall_seconds':report['wall_seconds']}}), flush=True)
    return 0 if not failures else 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except BaseException as exc:
        if isinstance(exc,SystemExit): raise
        write(STAGE/'FAILED.json', {'at_utc':stamp(), 'error_type':type(exc).__name__,
                                  'error':str(exc), 'rated_games':0})
        raise
