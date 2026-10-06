"""Recovered local rows must prove the same matrix, joins and fixed replay."""
import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from spellbench.arena import store
from spellbench.arena.allocation import ThroughputError
from spellbench.arena.allocation import MachineFacts, PlayedGame
from spellbench.arena.manifest import EngineFile
from spellbench.arena.throughput import plan_allocation, sample_order, workload_id
from spellbench.bench import definition
from spellbench.llm.run_budget import qualification_config
from spellbench.run_secret import RunSecret

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import gorge_local_reference_result as local
import gorge_reference_coordinator as coordinator


def write(path, value):
    path.write_text(json.dumps(value)+'\n')


@pytest.fixture
def recovered(tmp_path):
    spec = importlib.util.spec_from_file_location('local_reference_typed_rows',
        ROOT/'python/tests/test_gorge_reference_coordinator.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    results, args = fixture.matrix(tmp_path)
    aggregates, joins, failures = coordinator.validate_matrix(results, **args)
    assert not failures
    for result, join in zip(results, joins):
        store.append_ledger_row(tmp_path/'matches.jsonl', result['row'])
        store.append_ledger_row(tmp_path/'policy-joins.jsonl', join)
    secret, cfg = args['secret'], args['cfg']
    write(tmp_path/'PRIVATE-MATRIX-SECRET.json', dict(secret_hex=secret.hex()))
    manifest = dict(secret_commitment=secret.commitment(), selected_indices=[value['index'] for value in results])
    preflight = dict(engine=args['setup'].engine.to_json(),
        registry=[entry.to_json() for entry in args['entries'].values()],
        decks=[dict(catalog_id=spec.catalog_id, ledger=args['setup'].decks[spec].ledger().to_json())
               for spec in cfg.deck_specs()])
    replay = next(context.game_index for context in args['chosen'] if context.decks[0].catalog_id == 'Burn'
                  and any('search' in value.name for _, value in context.seat_specs))
    original = next(value['row'] for value in results if value['index'] == replay)
    store.append_ledger_row(tmp_path/'replay-original.jsonl', original)
    store.append_ledger_row(tmp_path/'replay.jsonl', original)
    report = dict(passed=True, failures=[], completed_games=140, cells=aggregates,
        native_participant_receipts=160, ledger_sha256=local.sha(tmp_path/'matches.jsonl'),
        game_seconds=[dict(game_index=value['index'], seconds=1.0) for value in results],
        replay_identical=True, replay_game_index=replay, replay_store_sha256=local.sha(tmp_path/'replay.jsonl'))
    return tmp_path, dict(source=ROOT, cfg=cfg, manifest=manifest, report=report, preflight=preflight)


def test_full_local_matrix_and_original_replay_are_checked_from_actual_bytes(recovered):
    stage, args = recovered
    verdict = local.verify_local_matrix(stage, **args)
    assert verdict['completed_games'] == 140 and verdict['native_participant_receipts'] == 160
    assert verdict['cells'] == 60 and verdict['replay_identical'] and verdict['rated_games'] == 0
    # A matrix-only check does not claim native, throughput or rated admission.
    assert 'passed' not in verdict and 'outputs_identical' not in verdict


@pytest.mark.parametrize('change', ['missing_row', 'changed_join', 'open_participant',
    'duplicate_deck', 'wrong_secret', 'wrong_sample', 'wrong_replay', 'noncanonical', 'invalid_time'])
def test_report_pass_flag_cannot_hide_changed_or_missing_local_evidence(recovered, change):
    stage, args = recovered
    if change == 'missing_row':
        path = stage/'matches.jsonl'; path.write_bytes(b'\n'.join(path.read_bytes().splitlines()[:-1])+b'\n')
    elif change in ('changed_join', 'open_participant'):
        values = local.rows(stage/'policy-joins.jsonl')
        if change == 'changed_join': values[0]['game_index'] += 1
        else: values[0]['policy_receipts'][0]['game_over_received'] = False
        (stage/'policy-joins.jsonl').write_bytes(b''.join(store.canonical_bytes(value)+b'\n' for value in values))
    elif change == 'duplicate_deck':
        args['preflight']['decks'].append(copy.deepcopy(args['preflight']['decks'][0]))
    elif change == 'wrong_secret':
        write(stage/'PRIVATE-MATRIX-SECRET.json', dict(secret_hex='44'*32))
    elif change == 'wrong_sample': args['manifest']['selected_indices'].reverse()
    elif change == 'wrong_replay':
        (stage/'replay.jsonl').write_bytes((stage/'matches.jsonl').read_bytes().splitlines()[0]+b'\n')
        args['report']['replay_store_sha256'] = local.sha(stage/'replay.jsonl')
    elif change == 'noncanonical':
        (stage/'matches.jsonl').write_text('\n'.join(json.dumps(value) for value in local.rows(stage/'matches.jsonl'))+'\n')
        args['report']['ledger_sha256'] = local.sha(stage/'matches.jsonl')
    else: args['report']['game_seconds'][0]['seconds'] = 0
    with pytest.raises(ThroughputError): local.verify_local_matrix(stage, **args)


def test_local_reference_checker_refuses_an_unclosed_native_audit_before_matrix_verification(tmp_path):
    native = dict(closed=False)
    write(tmp_path/'MANIFEST.json', dict(source_commit='fixture-only', native_proof=dict(native_verdict=native)))
    write(tmp_path/'MATRIX.json', dict(passed=True))
    with pytest.raises(ThroughputError, match='verified native proof'):
        local.verify_local_reference_result(tmp_path, source=ROOT, head_sha='fixture-only', native_verdict=native)


@pytest.fixture
def matched(recovered, monkeypatch):
    """Synthetic completed ledgers exercise recovery without starting engines."""
    stage, args = recovered
    rules = replace(definition.load_benchmark(ROOT/'benchmarks/pauper-gorge').qualification_rules(),
                    worker_selection='wall')
    bound = max(n for n in range(2, 9) if rules.ladder_fits(140, n))
    cfg = replace(args['cfg'], workers=bound)
    files = []
    runtime = stage/'runtime'; runtime.mkdir()
    inventory = {}
    for index, name in enumerate(('spellbench-gorge-env-windows-amd64.exe',
            'spellbench-gorge-agent-windows-amd64.exe', 'registry.gob.gz')):
        path = runtime/name; path.write_bytes(b'unit-test-only')
        pin = dict(bytes=path.stat().st_size, sha256=local.sha(path))
        inventory[name] = pin
        files.append(EngineFile(index=index, file_name=name, **pin, path=path))
    write(runtime/'SEAL.json', dict(files=inventory))
    monkeypatch.setattr(local.bench_run, 'run_files', lambda config: tuple(files))
    native = dict(closed=True, seed_blocks=320, completed_games=640, outputs_identical=True,
        native_seal_sha256='fixture-only', runtime_seal_sha256='fixture-only', runtime_source_commit='fixture-only',
        runtime_root=str(runtime), registry_sha256='${GORGE_REGISTRY_SHA256}')
    manifest = dict(args['manifest'], source_commit='fixture-only',
        native_proof=dict(native_verdict=local.portable_native_verdict(native)),
        runtime_seal_sha256='fixture-only', runtime_source_commit='fixture-only', rated_games=0,
        executed_config=cfg.to_json(), launch_files=[file.to_json() for file in files], usable_cpus=24,
        benchmark_sha256=local.sha(ROOT/'benchmarks/pauper-gorge/benchmark.json'))
    report = dict(args['report'], rated_games=0)
    primary = local.rows(stage/'matches.jsonl')
    by_index = {value['game_index']: value for value in primary}
    guard = RunSecret.from_hex('33'*32)
    chosen = manifest['selected_indices']
    contexts = local.schedule(cfg, guard)
    groups = {}
    for position, index in enumerate(chosen):groups.setdefault(contexts[index].matchup_index, []).append(position)
    sample = sample_order(list(groups.values()))
    qualification = stage/'.qualification-records/qualification-unit-test'; qualification.mkdir(parents=True)
    calls = []
    def play(workers, positions):
        number = len(calls)+1
        path = qualification/f'trial-{number}-workers-{workers}.jsonl'
        played = []
        for position in positions:
            row = copy.deepcopy(by_index[chosen[position]])
            row['game_id'] = guard.game_id(row['game_index'])
            store.append_ledger_row(path, row)
            played.append(PlayedGame(index=position, seconds=10.,
                digest='sha256:'+hashlib.sha256(store.canonical_bytes(row)).hexdigest(),
                row_bytes=len(store.canonical_bytes(row))+1))
        calls.append(dict(workers=workers, schedule_indices=[chosen[i] for i in positions]))
        audit = stage/f'guard-native-audits/trial-{number}-workers-{workers}'; audit.mkdir(parents=True)
        write(audit/'MEASUREMENT.json', dict(workers=workers, positions=list(positions),
            wall_seconds=len(positions)*10/workers,
            games=[dict(index=game.index, seconds=game.seconds, digest=game.digest, row_bytes=game.row_bytes) for game in played]))
        return len(positions)*10/workers, tuple(played)
    shape = {k:v for k,v in qualification_config(cfg).items() if k != 'tournament_dir'}
    workload = workload_id(dict(arena=local.__version__, config=shape, files=manifest['launch_files'], games=chosen))
    facts = MachineFacts(memory_bytes=32*2**30, gpus=(),
        free_bytes=(('pin_root',100*2**30), ('run_dir',100*2**30)))
    allocation = plan_allocation(games_total=140, cap=bound, per_game_cores=3, cpu_count=24,
        play=play, placement='main-pc=used: unit-test-only; haleyspc=unavailable: fixture; runpod=not_authorized: fixture',
        host='unit-test-only', sample=sample, workload=workload, machine=facts, rules=rules)
    report['allocation'] = allocation.to_json()
    write(stage/'ALLOCATION.json', allocation.to_json())
    write(qualification/'REPLAY.json', dict(schema='spellbench-qualification-replay/v1',
        harness_files={str(ROOT/name):local.sha(ROOT/name) for name in ('python/spellbench/bench/run.py', 'python/spellbench/arena/runner.py')},
        run_secret=guard.hex(), config=cfg.to_json(),
        files=manifest['launch_files'], arena_version=local.__version__, trials=calls))
    write(stage/'MANIFEST.json', manifest); write(stage/'MATRIX.json', report); write(stage/'PREFLIGHT.json', args['preflight'])
    return stage, native, qualification


def test_local_recovery_checks_complete_matched_primary_ledgers(matched):
    stage, native, _ = matched
    result = local.verify_local_reference_result(stage, source=ROOT, head_sha='fixture-only', native_verdict=native)
    assert result['passed'] and result['outputs_identical'] and result['completed_games'] == 140


def test_recovered_runtime_lookup_preserves_full_matrix_and_workload_bindings(matched):
    stage, native, _ = matched
    original = (stage/'MANIFEST.json').read_bytes()
    result = local.verify_local_reference_result(stage, source=ROOT, head_sha='fixture-only',
        native_verdict=native, recovered_runtime=native['runtime_root'])
    assert result['passed'] and result['outputs_identical'] and result['completed_games'] == 140
    assert (stage/'MANIFEST.json').read_bytes() == original


def test_local_recovery_requires_wall_selection_even_for_identical_primary_rows(matched):
    stage, native, _ = matched
    report = local.read(stage/'MATRIX.json')
    report['allocation']['rules']['worker_selection'] = 'busy'
    write(stage/'MATRIX.json', report)
    write(stage/'ALLOCATION.json', report['allocation'])
    with pytest.raises(ThroughputError, match='matched throughput evidence'):
        local.verify_local_reference_result(stage, source=ROOT, head_sha='fixture-only', native_verdict=native)


@pytest.fixture
def off_host_runtime(tmp_path):
    runtime = tmp_path/'recovered-runtime'
    runtime.mkdir()
    names = ('spellbench-gorge-env-windows-amd64.exe',
             'spellbench-gorge-agent-windows-amd64.exe', 'registry.gob.gz')
    pins = {}
    for number, name in enumerate(names):
        path = runtime/name
        path.write_bytes(('fixture-only-'+str(number)).encode())
        pins[name] = dict(bytes=path.stat().st_size, sha256=local.sha(path))
    write(runtime/'SEAL.json', dict(files=pins))
    values = dict(GORGE_SPELLBENCH_ENV='Z:/absent-gorge-recovery-fixture/'+names[0],
        GORGE_SPELLBENCH_AGENT='Z:/absent-gorge-recovery-fixture/'+names[1],
        GORGE_REGISTRY='Z:/absent-gorge-recovery-fixture/'+names[2],
        GORGE_REGISTRY_SHA256=pins[names[2]]['sha256'])
    cfg = local.config.TournamentConfig.from_json(
        definition.load_benchmark(ROOT/'benchmarks/pauper-gorge').tournament_config(str(tmp_path/'diag')))
    cfg = local.runner.executed_config(cfg, lambda text: definition.substitute(text, values))
    return cfg, runtime, pins


def test_off_host_recovery_hashes_actual_files_at_original_command_indices(off_host_runtime):
    cfg, runtime, pins = off_host_runtime
    original = copy.deepcopy(cfg.to_json())
    files = [value.to_json() for value in local.recovered_run_files(cfg, runtime)]
    assert files == [dict(index=index, file_name=name, **pins[name]) for index, name in (
        (0, 'spellbench-gorge-env-windows-amd64.exe'),
        (2, 'registry.gob.gz'), (0, 'spellbench-gorge-agent-windows-amd64.exe'))]
    assert cfg.to_json() == original


@pytest.mark.parametrize('name', ['spellbench-gorge-env-windows-amd64.exe',
    'spellbench-gorge-agent-windows-amd64.exe', 'registry.gob.gz'])
def test_off_host_recovery_refuses_changed_runtime_bytes(off_host_runtime, name):
    cfg, runtime, _ = off_host_runtime
    (runtime/name).write_bytes(b'changed-fixture-only')
    with pytest.raises(ThroughputError, match='Recovered runtime differs'):
        local.recovered_run_files(cfg, runtime)


def test_off_host_recovery_cannot_substitute_an_unverified_runtime_root(matched, tmp_path):
    stage, native, _ = matched
    with pytest.raises(ThroughputError, match='not the verified native input'):
        local.verify_local_reference_result(stage, source=ROOT, head_sha='fixture-only',
            native_verdict=native, recovered_runtime=tmp_path/'another-runtime')


@pytest.mark.parametrize('change', ['changed_parallel', 'missing_trial', 'reused_secret', 'changed_runtime', 'changed_clock', 'changed_timing'])
def test_local_recovery_rejects_throughput_or_binding_changes(matched, change):
    stage, native, qualification = matched
    if change == 'changed_parallel':
        path = next(qualification.glob('trial-2-*.jsonl'))
        values = local.rows(path); values[0]['game_id'] = RunSecret.from_hex('66'*32).game_id(values[0]['game_index'])
        path.write_bytes(b''.join(store.canonical_bytes(value)+b'\n' for value in values))
    elif change == 'missing_trial': next(qualification.glob('trial-2-*.jsonl')).unlink()
    elif change == 'reused_secret':
        value = local.read(qualification/'REPLAY.json'); value['run_secret'] = local.read(stage/'PRIVATE-MATRIX-SECRET.json')['secret_hex']
        write(qualification/'REPLAY.json', value)
    elif change == 'changed_runtime':
        value = local.read(stage/'runtime/SEAL.json'); value['files']['registry.gob.gz']['sha256'] = '0'*64
        write(stage/'runtime/SEAL.json', value)
    elif change == 'changed_clock':
        value = local.read(stage/'MANIFEST.json'); value['executed_config']['time_control']['bank_ms'] += 1
        write(stage/'MANIFEST.json', value)
    else:
        path = next((stage/'guard-native-audits').glob('trial-2-*/MEASUREMENT.json'))
        value = local.read(path); value['wall_seconds'] += 10; write(path, value)
    with pytest.raises((ThroughputError, FileNotFoundError)):
        local.verify_local_reference_result(stage, source=ROOT, head_sha='fixture-only', native_verdict=native)
