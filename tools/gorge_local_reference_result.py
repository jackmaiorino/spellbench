"""Recheck the direct local matrix and its actual serial/parallel ledgers.

The caller first verifies terminal recovery and both sealed native inputs.
This checker starts no process and does not admit rated play.
"""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from spellbench import __version__
from spellbench.arena import config, runner, store
from spellbench.arena.allocation import Allocation, ThroughputError
from spellbench.arena.ledger import LedgerDeck, LedgerRow
from spellbench.arena.registry import RegistryEntry
from spellbench.arena.schedule import schedule
from spellbench.arena.throughput import resource_bound, sample_order, workload_id
from spellbench.bench import definition, run as bench_run
from spellbench.llm.run_budget import qualification_config
from spellbench.messages import EngineIdentity
from spellbench.run_secret import RunSecret

from gorge_ci_exchange import sha
from gorge_reference_coordinator import validate_matrix
from gorge_reference_pool import portable_native_verdict
from gorge_reference_worker import load_original_helpers


def read(path):
    return json.loads(Path(path).read_bytes())


def rows(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines()]


def retained_setup(cfg, preflight):
    parsed = [RegistryEntry.from_json(value) for value in preflight['registry']]
    entries = {entry.name: entry for entry in parsed}
    if (len(entries) != len(cfg.bots) or
            preflight['registry'] != [entry.to_json() for entry in runner.registry_entries(cfg, cfg)]):
        raise ThroughputError('Local reference registry differs from its original participants')
    values = {value['catalog_id']: LedgerDeck.from_json(value['ledger']) for value in preflight['decks']}
    if len(values) != 5 or len(preflight['decks']) != 5 or set(values) != {s.catalog_id for s in cfg.deck_specs()}:
        raise ThroughputError('Local reference preflight omits or duplicates a declared deck')
    decks = {spec: SimpleNamespace(ledger=lambda value=values[spec.catalog_id]: value) for spec in cfg.deck_specs()}
    return SimpleNamespace(engine=EngineIdentity.from_json(preflight['engine']), decks=decks), entries


def verify_local_matrix(stage, *, source, cfg, manifest, report, preflight):
    """Use the same full numerical and identity gates as the distributed matrix."""
    stage = Path(stage)
    secret = RunSecret.from_hex(read(stage/'PRIVATE-MATRIX-SECRET.json')['secret_hex'])
    if secret.commitment() != manifest['secret_commitment']:
        raise ThroughputError('Local matrix private seed differs from its recorded commitment')
    helpers = load_original_helpers(source, stage)
    chosen, expected = helpers.select_matrix(schedule(cfg, secret))
    indices = [context.game_index for context in chosen]
    if manifest['selected_indices'] != indices:
        raise ThroughputError('Local matrix changed its original seed, seat or deck selection')
    setup, entries = retained_setup(cfg, preflight)
    primary, joined = rows(stage/'matches.jsonl'), rows(stage/'policy-joins.jsonl')
    times = report['game_seconds']
    if (len(primary) != 140 or len(joined) != 140 or len(times) != 140 or
            [value['game_index'] for value in times] != indices or
            any(type(value['seconds']) not in (int, float) or not math.isfinite(value['seconds']) or
                value['seconds'] <= 0 for value in times)):
        raise ThroughputError('Local matrix lacks complete original rows, joins or usable timings')
    results = [dict(index=row['game_index'], row=row, engine=preflight['engine'], violation=None,
                    policy_receipts=join['policy_receipts']) for row, join in zip(primary, joined)]
    aggregates, expected_joins, failures = validate_matrix(results, chosen=chosen, expected=expected,
        secret=secret, setup=setup, entries=entries, helpers=helpers, cfg=cfg)
    canonical = b''.join(store.canonical_bytes(value)+b'\n' for value in primary)
    if (failures or report['passed'] is not True or report['failures'] or report['completed_games'] != 140 or
            report['native_participant_receipts'] != 160 or report['cells'] != aggregates or
            joined != expected_joins or (stage/'matches.jsonl').read_bytes() != canonical or
            sha(stage/'matches.jsonl') != report['ledger_sha256']):
        raise ThroughputError('Local matrix rows, participant evidence or numerical gates failed')
    replay = next(context.game_index for context in chosen if context.decks[0].catalog_id == 'Burn'
                  and any('search' in spec.name for _, spec in context.seat_specs))
    original = store.canonical_bytes(next(value for value in primary if value['game_index'] == replay))+b'\n'
    if (report['replay_identical'] is not True or report['replay_game_index'] != replay or
            (stage/'replay-original.jsonl').read_bytes() != original or
            (stage/'replay.jsonl').read_bytes() != original or sha(stage/'replay.jsonl') != report['replay_store_sha256']):
        raise ThroughputError('Local preselected search/Burn replay differs from the original row')
    return dict(completed_games=140, cells=60, native_participant_receipts=160, replay_identical=True,
                ledger_sha256=report['ledger_sha256'], rated_games=0)


def verify_local_reference_result(stage, *, source, head_sha, native_verdict):
    stage = Path(stage)
    manifest, report = read(stage/'MANIFEST.json'), read(stage/'MATRIX.json')
    native = portable_native_verdict(native_verdict)
    if (manifest['source_commit'] != head_sha or manifest['native_proof']['native_verdict'] != native or
            native.get('closed') is not True or native.get('seed_blocks') != 320 or
            native.get('completed_games') != 640 or native.get('outputs_identical') is not True or
            manifest['runtime_seal_sha256'] != native['runtime_seal_sha256'] or
            manifest['runtime_source_commit'] != native['runtime_source_commit'] or
            manifest['rated_games'] != 0 or report['rated_games'] != 0):
        raise ThroughputError('Local reference source, verified native proof or unrated scope differs')
    cfg = config.TournamentConfig.from_json(manifest['executed_config'])
    benchmark = definition.load_benchmark(Path(source)/'benchmarks/pauper-gorge')
    if sha(Path(source)/'benchmarks/pauper-gorge/benchmark.json') != manifest['benchmark_sha256']:
        raise ThroughputError('Local reference changed its frozen benchmark input')
    values = dict(GORGE_SPELLBENCH_ENV=cfg.engine_command[0],
        GORGE_SPELLBENCH_AGENT=next(bot.command[0] for bot in cfg.bots if bot.name.startswith('gorge-')),
        GORGE_REGISTRY=cfg.engine_command[cfg.engine_command.index('-registry')+1],
        GORGE_REGISTRY_SHA256=native['registry_sha256'])
    blueprint = config.TournamentConfig.from_json(benchmark.tournament_config(cfg.tournament_dir))
    blueprint = runner.executed_config(blueprint, lambda text: definition.substitute(text, values))
    allocation = Allocation.from_json(report['allocation'])
    rules = benchmark.qualification_rules()
    eligible = min(blueprint.workers, resource_bound(allocation.cpu_count, cfg.per_game_cores()))
    bounds = [n for n in range(2, eligible+1) if rules.ladder_fits(140, n)]
    if not bounds or cfg.to_json() != replace(blueprint, workers=max(bounds)).to_json():
        raise ThroughputError('Local reference changed the roster, clocks or fitting worker bound')
    files = [value.to_json() for value in bench_run.run_files(cfg)]
    runtime = read(Path(native_verdict['runtime_root'])/'SEAL.json')['files']
    for name in ('spellbench-gorge-env-windows-amd64.exe', 'spellbench-gorge-agent-windows-amd64.exe', 'registry.gob.gz'):
        expected = runtime[name]
        matching = [value for value in files if value['file_name'] == name]
        if not matching or any(value['sha256'] != expected['sha256'] or value['bytes'] != expected['bytes'] for value in matching):
            raise ThroughputError('Local reference executable or registry differs from the verified production runtime')
    shape = {key: value for key, value in qualification_config(cfg).items() if key != 'tournament_dir'}
    identity = dict(arena=__version__, config=shape, files=files, games=manifest['selected_indices'])
    if (allocation.kind != 'substantial' or allocation.outputs_identical is not True or allocation.reused or
            allocation.games_total != 140 or allocation.per_game_cores != 3 or allocation.rules != rules or
            allocation.cpu_count != manifest['usable_cpus'] or
            allocation.workload != workload_id(identity) or manifest['launch_files'] != files or
            read(stage/'ALLOCATION.json') != report['allocation'] or
            [trial.workers for trial in allocation.trials] != list(rules.ladder(cfg.workers))):
        raise ThroughputError('Local reference lacks its original matched throughput evidence')
    directories = list((stage/'.qualification-records').glob('qualification-*'))
    if len(directories) != 1:
        raise ThroughputError('Local reference omitted or repeated its measured qualification')
    qualification = directories[0]
    replay = read(qualification/'REPLAY.json')
    guard = RunSecret.from_hex(replay['run_secret'])
    expected_harness = {'python/spellbench/bench/run.py', 'python/spellbench/arena/runner.py'}
    harness = {next((suffix for suffix in expected_harness if name.replace('\\', '/').endswith('/'+suffix)), name): digest
               for name, digest in replay['harness_files'].items()}
    if (replay['schema'] != 'spellbench-qualification-replay/v1' or
            harness != {name:sha(Path(source)/name) for name in expected_harness} or
            guard.commitment() == manifest['secret_commitment'] or replay['config'] != cfg.to_json() or
            replay['files'] != files or replay['arena_version'] != __version__):
        raise ThroughputError('Local qualification changed its configuration or reused the matrix secret')
    contexts = schedule(cfg, guard)
    groups = {}
    for position, index in enumerate(manifest['selected_indices']):
        groups.setdefault(contexts[index].matchup_index, []).append(position)
    sample = tuple(sample_order(list(groups.values()))[:rules.probe_size(140, cfg.workers)])
    declarations = [dict(workers=trial.workers, schedule_indices=[manifest['selected_indices'][i] for i in sample])
                    for trial in allocation.trials]
    if replay['trials'] != declarations:
        raise ThroughputError('Local qualification replay record changed its representative sample')
    baseline = None
    setup, entries = retained_setup(cfg, read(stage/'PREFLIGHT.json'))
    for number, trial in enumerate(allocation.trials, 1):
        path = qualification/f'trial-{number}-workers-{trial.workers}.jsonl'
        observed = [LedgerRow.from_json(value).to_json() for value in rows(path)]
        indices = [manifest['selected_indices'][i] for i in sample]
        if trial.indices != sample or [value['game_index'] for value in observed] != indices:
            raise ThroughputError('Local qualification ledger omitted or reordered a measured seed')
        for row, index in zip(observed, indices):
            context = contexts[index]
            seats = [dict(seat=seat, bot_id=entries[spec.name].bot_id, name=spec.name, version=spec.version)
                     for seat, spec in context.seat_specs]
            if (row['classification'] != 'natural' or row['game_id'] != guard.game_id(index) or
                    row['format'] != cfg.format or row['matchup_index'] != context.matchup_index or
                    row['pair_index'] != context.pair_index or row['pair_slot'] != context.pair_slot or
                    row['seats'] != seats or row['decks'] != [setup.decks[s].ledger().to_json() for s in context.decks] or
                    row['engine'] != setup.engine.provenance().to_json()):
                raise ThroughputError('Local measured game changed its seed, participants or natural terminal')
        primary = b''.join(store.canonical_bytes(value)+b'\n' for value in observed)
        digests = ['sha256:'+hashlib.sha256(store.canonical_bytes(value)).hexdigest() for value in observed]
        digest = 'sha256:'+hashlib.sha256(''.join(value+'\n' for value in digests).encode('ascii')).hexdigest()
        measurement = read(stage/f'guard-native-audits/trial-{number}-workers-{trial.workers}/MEASUREMENT.json')
        measured = measurement['games']
        if (measurement['workers'] != trial.workers or measurement['positions'] != list(sample) or
                len(measured) != len(observed) or [value['index'] for value in measured] != list(sample) or
                [value['digest'] for value in measured] != digests or
                [value['row_bytes'] for value in measured] != [len(store.canonical_bytes(row))+1 for row in observed] or
                any(type(value['seconds']) not in (int, float) or not math.isfinite(value['seconds']) or
                    value['seconds'] <= 0 for value in measured) or
                type(measurement['wall_seconds']) not in (int, float) or
                not math.isfinite(measurement['wall_seconds']) or measurement['wall_seconds'] <= 0 or
                round(measurement['wall_seconds']*1000) != trial.seconds_milli or
                round(sum(value['seconds'] for value in measured)*1000) != trial.busy_milli or
                path.read_bytes() != primary or trial.outputs_digest != digest or trial.row_bytes != len(primary)):
            raise ThroughputError('Local measured primary ledger differs from its allocation digest')
        if baseline is not None and baseline != primary:
            raise ThroughputError('Local serial and parallel primary ledgers differ')
        baseline = primary
    verified = verify_local_matrix(stage, source=source, cfg=cfg, manifest=manifest, report=report,
                                   preflight=read(stage/'PREFLIGHT.json'))
    return dict(verified, passed=True, outputs_identical=True, workers=allocation.workers,
                source_commit=head_sha, native_audit_seal_sha256=native['native_seal_sha256'])
