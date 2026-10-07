"""Recheck recovered reference rows, participant joins, allocation and replay."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

from spellbench.arena import config, runner, store
from spellbench.arena.allocation import Allocation, ThroughputError
from spellbench.arena.ledger import LedgerDeck
from spellbench.arena.registry import RegistryEntry
from spellbench.arena.schedule import schedule
from spellbench.arena.throughput import sample_order, workload_id
from spellbench.bench import definition
from spellbench.messages import EngineIdentity
from spellbench.run_secret import RunSecret

from gorge_ci_exchange import sha
from gorge_reference_coordinator import validate_matrix
from gorge_reference_pool import PoolNode, portable_native_verdict
from gorge_reference_worker import load_original_helpers


def read(path):
    return json.loads(Path(path).read_bytes())


def verify_reference_result(stage, *, source, inputs, head_sha, native_verdict):
    stage=Path(stage)
    manifest,report,preflight=read(stage/'MANIFEST.json'),read(stage/'MATRIX.json'),read(stage/'PREFLIGHT.json')
    if (manifest['source_commit']!=head_sha or manifest['source_inputs']!=inputs or
            manifest['native_verdict']!=portable_native_verdict(native_verdict) or
            report['full_native_audit_passed'] is not True or
            report['native_audit_seal_sha256']!=inputs['native_seal_sha256'] or
            manifest['rated_games']!=0 or report['rated_games']!=0):
        raise ThroughputError('Recovered reference source, native proof or scope differs')
    cfg=config.TournamentConfig.from_json(manifest['configuration'])
    benchmark=definition.load_benchmark(Path(source)/'benchmarks/pauper-gorge')
    if sha(Path(source)/'benchmarks/pauper-gorge/benchmark.json')!=inputs['benchmark_sha256']:
        raise ThroughputError('Reference result is not bound to the frozen benchmark')
    values=dict(GORGE_SPELLBENCH_ENV=cfg.engine_command[0],
        GORGE_SPELLBENCH_AGENT=next(bot.command[0] for bot in cfg.bots if bot.name.startswith('gorge-')),
        GORGE_REGISTRY=cfg.engine_command[cfg.engine_command.index('-registry')+1],
        GORGE_REGISTRY_SHA256=inputs['registry_sha256'])
    blueprint=config.TournamentConfig.from_json(benchmark.tournament_config(cfg.tournament_dir))
    blueprint=runner.executed_config(blueprint,lambda text:definition.substitute(text,values))
    if cfg.to_json()!=blueprint.to_json():
        raise ThroughputError('Reference result changed the original roster, decks, settings or clocks')
    secret=RunSecret.from_hex(read(stage/'PRIVATE-MATRIX-SECRET.json')['secret_hex'])
    guard=RunSecret.from_hex(read(stage/'PRIVATE-GUARD-SECRET.json')['secret_hex'])
    if (secret.commitment()!=manifest['matrix_secret_commitment'] or
            guard.commitment()!=manifest['guard_secret_commitment'] or guard==secret):
        raise ThroughputError('Reference result changed its original private seed binding')
    helpers=load_original_helpers(source,stage)
    chosen,expected=helpers.select_matrix(schedule(cfg,secret))
    indices=[context.game_index for context in chosen]
    matchups={}
    for position,context in enumerate(chosen):
        matchups.setdefault(context.matchup_index,[]).append(position)
    sample=sample_order(list(matchups.values()))
    if manifest['selected_indices']!=indices or manifest['qualification_sample']!=list(sample):
        raise ThroughputError('Reference result changed its original matrix or representative sample')
    rules=replace(benchmark.qualification_rules(),worker_selection='wall')
    allocation=Allocation.from_json(report['allocation'])
    pool=read(stage/'pool/POOL.json')
    nodes=[PoolNode(**value) for value in pool['nodes']]
    if len(nodes)!=inputs['pool_slots']:
        raise ThroughputError('Reference result has a different worker inventory')
    for node in nodes:
        node.validate(head_sha,inputs['native_seal_sha256'],inputs['runtime_seal_sha256'],3,2*2**30)
    descriptor=dict(kind='gorge-reference-pool/v1',source_commit=head_sha,
        native_verdict=portable_native_verdict(native_verdict),runtime_pins=manifest['runtime_pins'],
        configuration=cfg.to_json(),indices=indices,nodes=[node.__dict__ for node in nodes],
        per_game_cores=3,qualification_rules=rules.to_json())
    if (allocation.kind!='substantial' or allocation.outputs_identical is not True or allocation.rules!=rules or
            allocation.games_total!=140 or allocation.cpu_count!=3*len(nodes) or allocation.per_game_cores!=3 or
            allocation.workload!=workload_id(descriptor) or pool['workload']!=allocation.workload or
            [trial.workers for trial in allocation.trials]!=list(rules.ladder(len(nodes))) or
            any(trial.indices!=tuple(sample[:rules.probe_size(140,len(nodes))]) for trial in allocation.trials) or
            read(stage/'pool/ALLOCATION.json')!=report['allocation']):
        raise ThroughputError('Reference result lacks the original complete matching throughput allocation')
    parsed=[RegistryEntry.from_json(value) for value in preflight['registry']]
    entries={entry.name:entry for entry in parsed}
    if (len(entries)!=len(cfg.bots) or
            preflight['registry']!=[entry.to_json() for entry in runner.registry_entries(cfg,cfg)]):
        raise ThroughputError('Recovered reference participants differ from the original registry')
    deck_values={value['catalog_id']:LedgerDeck.from_json(value['ledger']) for value in preflight['decks']}
    if len(deck_values)!=5:
        raise ThroughputError('Recovered reference deck preflight is incomplete')
    decks={spec:SimpleNamespace(ledger=lambda value=deck_values[spec.catalog_id]:value) for spec in cfg.deck_specs()}
    setup=SimpleNamespace(engine=EngineIdentity.from_json(preflight['engine']),decks=decks)
    directories=list((stage/'pool').glob('matrix-*-workers-*'))
    if len(directories)!=1:
        raise ThroughputError('Recovered reference result omitted or repeated the matrix')
    results_by_index={}
    for path in directories[0].glob('node-*-response.json'):
        response=read(path)
        if response['workload']!=allocation.workload:
            raise ThroughputError('A recovered node response belongs to another pool')
        for result in response['results']:
            if result['index'] in results_by_index:
                raise ThroughputError('Recovered reference workers duplicated a game')
            results_by_index[result['index']]=result
    if set(results_by_index)!=set(indices):
        raise ThroughputError('Recovered reference workers omitted an original game')
    results=[results_by_index[index] for index in indices]
    aggregates,joins,failures=validate_matrix(results,chosen=chosen,expected=expected,secret=secret,
        setup=setup,entries=entries,helpers=helpers,cfg=cfg)
    ledger=b''.join(store.canonical_bytes(result['row'])+b'\n' for result in results)
    if (failures or report['passed'] is not True or report['failures'] or report['completed_games']!=140 or
            report['native_participant_receipts']!=160 or report['cells']!=aggregates or
            (stage/'matches.jsonl').read_bytes()!=ledger or sha(stage/'matches.jsonl')!=report['ledger_sha256'] or
            [json.loads(line) for line in (stage/'policy-joins.jsonl').read_bytes().splitlines()]!=joins):
        raise ThroughputError('Recovered original matrix, native joins or unchanged numerical gates failed')
    replay=next(context.game_index for context in chosen if context.decks[0].catalog_id=='Burn'
                and any('search' in spec.name for _,spec in context.seat_specs))
    original=store.canonical_bytes(results_by_index[replay]['row'])+b'\n'
    if (report['replay_identical'] is not True or report['replay_game_index']!=replay or
            manifest['preselected_replay_index']!=replay or (stage/'replay-original.jsonl').read_bytes()!=original or
            (stage/'replay.jsonl').read_bytes()!=original or sha(stage/'replay.jsonl')!=report['replay_store_sha256']):
        raise ThroughputError('Recovered preselected search/Burn replay differs from its primary bytes')
    return dict(passed=True,completed_games=140,cells=60,native_participant_receipts=160,
        replay_identical=True,outputs_identical=True,workers=allocation.workers,
        ledger_sha256=report['ledger_sha256'],source_commit=head_sha,rated_games=0)
