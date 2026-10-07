"""Collect and validate the unchanged gorge reference matrix across CI nodes."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from spellbench.arena import runner, store
from spellbench.arena.allocation import ThroughputError
from spellbench.arena.ledger import LedgerRow
from spellbench.arena.schedule import preflight, schedule
from spellbench.arena.throughput import sample_order
from spellbench.bench import definition, run as bench_run
from spellbench.run_secret import RunSecret

from gorge_reference_pool import PoolNode, ReferencePool, portable_native_verdict
from gorge_reference_transport import NodeTransport
from gorge_reference_worker import load_original_helpers, write_new


def validate_matrix(results, *, chosen, expected, secret, setup, entries, helpers, cfg):
    """Preserve original numerical gates and check each joined participant."""
    if [value['index'] for value in results] != [context.game_index for context in chosen]:
        raise ThroughputError('Matrix omitted or reordered an original reference game')
    aggregates, joins = {}, []
    receipts_count = 0
    for value, context in zip(results, chosen):
        row = LedgerRow.from_json(value['row']).to_json()
        wanted_seats = [dict(seat=seat, bot_id=entries[spec.name].bot_id,
            name=entries[spec.name].name, version=entries[spec.name].version) for seat, spec in context.seat_specs]
        wanted_decks = [setup.decks[spec].ledger().to_json() for spec in context.decks]
        if (row['game_id'] != secret.game_id(context.game_index) or row['format'] != cfg.format or
                row['matchup_index'] != context.matchup_index or row['pair_index'] != context.pair_index or
                row['pair_slot'] != context.pair_slot or row['seats'] != wanted_seats or row['decks'] != wanted_decks or
                row['engine'] != setup.engine.provenance().to_json() or value['engine'] != setup.engine.to_json() or
                row['classification'] != 'natural' or value.get('violation') is not None):
            raise ThroughputError('Matrix row differs from the pinned engine, original seeds, seats, decks or natural terminal')
        receipts = value.get('policy_receipts', [])
        native_seats = [seat for seat in row['seats'] if seat['name'].startswith('gorge-')]
        if len(receipts) != len(native_seats):
            raise ThroughputError('Matrix lacks one native participant receipt per original seat')
        for seat in native_seats:
            matches = [receipt for receipt in receipts if receipt.get('seat') == seat['seat']]
            if len(matches) != 1:
                raise ThroughputError('Matrix duplicated or misassigned a native participant receipt')
            receipt = matches[0]
            if (receipt.get('schema') != 'spellbench-gorge-policy-audit/v1' or
                    receipt.get('game_id') != row['game_id'] or receipt.get('bot_name') != seat['name'] or
                    receipt.get('policy') != seat['name'].removeprefix('gorge-') or
                    receipt.get('version') != seat['version'] or receipt.get('game_started') is not True or
                    receipt.get('game_over_received') is not True):
                raise ThroughputError('Matrix native receipt identity or closed lifecycle differs')
            for field in ('native_decisions', 'ForcedNatives', 'FallbackNatives'):
                if type(receipt.get(field)) is not int or receipt[field] < 0:
                    raise ThroughputError('Matrix native decision counters are invalid')
            key = seat['name'] + '/' + context.decks[0].catalog_id
            aggregate = aggregates.setdefault(key, dict(policy=receipt['policy'], games=0,
                native_decisions=0, bad_native_decisions=0, search={}))
            if aggregate['policy'] != receipt['policy']:
                raise ThroughputError('A native policy changed identity within its declared cell')
            aggregate['games'] += 1
            aggregate['native_decisions'] += receipt['native_decisions']
            aggregate['bad_native_decisions'] += receipt['ForcedNatives'] + receipt['FallbackNatives']
            for field, count in receipt['search'].items():
                if type(count) is int:
                    if count < 0:
                        raise ThroughputError('Matrix search counter is negative')
                    aggregate['search'][field] = aggregate['search'].get(field, 0) + count
                elif isinstance(count, dict):
                    target = aggregate['search'].setdefault(field, {})
                    for reason, number in count.items():
                        if type(number) is not int or number < 0:
                            raise ThroughputError('Matrix search reason counter is invalid')
                        target[reason] = target.get(reason, 0) + number
            receipts_count += 1
        joins.append(dict(game_index=row['game_index'], game_id=row['game_id'],
                          decks=row['decks'], policy_receipts=receipts))
    failures, redealt = [], {}
    for (name, deck), count in expected.items():
        key = name + '/' + deck
        aggregate = aggregates.get(key)
        if aggregate is None or aggregate['games'] != count:
            failures.append(key + ': incomplete declared seat pairs')
            continue
        if not helpers.mapping_pass(aggregate['native_decisions'], aggregate['bad_native_decisions']):
            failures.append(key + ': native mapping is not under one percent')
        policy = aggregate['policy']
        if policy.startswith('search'):
            search = aggregate['search']
            if search.get('Eligible', 0) == 0 or search.get('Covered', 0) == 0:
                failures.append(key + ': no eligible and covered native search')
            if policy.endswith('redeal'):
                redealt[policy] = redealt.get(policy, 0) + search.get('Redealt', 0)
                if search.get('ReconstructionBudgetExhausted', 0) or search.get('RedealRefusals', {}):
                    failures.append(key + ': redeal reconstruction refused or exhausted')
    for policy, count in redealt.items():
        if count == 0:
            failures.append(policy + ': no accepted redealt world')
    if len(aggregates) != len(expected) or len(results) != len(chosen) or receipts_count != sum(expected.values()):
        failures.append('incomplete original matrix or native participant receipts')
    return aggregates, joins, failures


def coordinate(*, source, source_commit, cfg, stage, client, inputs, native_verdict, clock):
    started = clock()
    stage = Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    helpers = load_original_helpers(source, stage)
    benchmark = definition.load_benchmark(Path(source) / 'benchmarks/pauper-gorge')
    rules = replace(benchmark.qualification_rules(), worker_selection='wall')
    files = bench_run.run_files(cfg)
    pins = [value.to_json() for value in files]
    portable = portable_native_verdict(native_verdict)
    template, expected = helpers.select_matrix(schedule(cfg, RunSecret.from_hex('00'*32)))
    indices = tuple(context.game_index for context in template)
    aliases = [f'node-{i}' for i in range(inputs['pool_slots'])]
    nodes = []
    transport = NodeTransport(client)
    planned_nodes = [SimpleNamespace(alias=alias) for alias in aliases]
    try:
        for alias in aliases:
            ready = transport.ready(alias)
            if (ready['native_verdict'] != portable or ready['runtime_pins'] != pins or
                    ready['configuration'] != cfg.to_json() or ready['indices'] != list(indices) or
                    ready['per_node_game_slots'] != 1 or ready['rated_games'] != 0):
                raise ThroughputError('A ready worker differs from the admitted reference inputs')
            node = PoolNode(**ready['node'])
            if node.alias != alias:
                raise ThroughputError('Ready worker alias differs from the declared pool')
            nodes.append(node)
    except BaseException:
        transport.stop(planned_nodes)
        raise
    try:
        pool = ReferencePool(nodes=nodes, execute_node=transport, source_commit=source_commit,
            native_verdict=portable, runtime_pins=pins, configuration=cfg.to_json(), indices=indices,
            stage=stage / 'pool', placement=inputs['placement'], host='gorge-github-reference-pool', rules=rules)
        guard_secret, matrix_secret = RunSecret.generate(), RunSecret.generate()
        for label, secret in (('GUARD', guard_secret), ('MATRIX', matrix_secret)):
            path = stage / f'PRIVATE-{label}-SECRET.json'
            write_new(path, dict(secret_hex=secret.hex(), commitment=secret.commitment(), rated=False))
            path.chmod(0o600)
        chosen, _ = helpers.select_matrix(schedule(cfg, matrix_secret))
        replay = next(context for context in chosen if context.decks[0].catalog_id == 'Burn'
                      and any('search' in spec.name for _, spec in context.seat_specs))
        matchups = {}
        for position, context in enumerate(chosen):
            matchups.setdefault(context.matchup_index, []).append(position)
        sample = sample_order(list(matchups.values()))
        write_new(stage / 'MANIFEST.json', dict(source_commit=source_commit, native_verdict=portable,
            source_inputs=inputs, configuration=cfg.to_json(), runtime_pins=pins,
            selected_indices=indices, qualification_sample=sample, preselected_replay_index=replay.game_index,
            guard_secret_commitment=guard_secret.commitment(), matrix_secret_commitment=matrix_secret.commitment(),
            reference_qualification_rules=rules.to_json(), expected_cells=60, expected_receipts=160,
            scope='reference qualification only', rated_games=0))
        allocation = pool.qualify(guard_secret_hex=guard_secret.hex(), sample=sample)
        # Coordinator preflight is a bounded identity/deck check after admission;
        # it is not an additional reference game or allocation measurement.
        setup = preflight(cfg, matrix_secret)
        entries = {entry.name: entry for entry in runner.registry_entries(cfg, cfg)}
        write_new(stage / 'PREFLIGHT.json', dict(engine=setup.engine.to_json(),
            registry=[entry.to_json() for entry in entries.values()],
            decks=[dict(catalog_id=spec.catalog_id, ledger=resolved.ledger().to_json())
                   for spec, resolved in setup.decks.items()]))
        wall, results = pool.collect(allocation.workers, indices, phase='matrix', secret_hex=matrix_secret.hex())
        aggregates, joins, failures = validate_matrix(results, chosen=chosen, expected=expected,
            secret=matrix_secret, setup=setup, entries=entries, helpers=helpers, cfg=cfg)
        ledger = stage / 'matches.jsonl'
        for value, join in zip(results, joins):
            store.append_ledger_row(ledger, value['row'])
            store.append_ledger_row(stage / 'policy-joins.jsonl', join)
        replay_identical = False
        if not failures:
            _, replayed = pool.collect(1, [replay.game_index], phase='replay', secret_hex=matrix_secret.hex())
            original = next(value['row'] for value in results if value['index'] == replay.game_index)
            store.append_ledger_row(stage / 'replay-original.jsonl', original)
            store.append_ledger_row(stage / 'replay.jsonl', replayed[0]['row'])
            replay_identical = (stage / 'replay-original.jsonl').read_bytes() == (stage / 'replay.jsonl').read_bytes()
            if not replay_identical:
                failures.append('search/Burn seed replay differs')
        report = dict(schema='spellbench-gorge-reference-host-matrix/v1', passed=not failures,
            failures=failures, completed_games=len(results), cells=aggregates,
            native_participant_receipts=sum(len(join['policy_receipts']) for join in joins),
            allocation=allocation.to_json(), game_seconds=[dict(game_index=value['index'], seconds=value['seconds']) for value in results],
            wall_seconds=clock() - started, matrix_collection_wall_seconds=wall,
            ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(), replay_identical=replay_identical,
            replay_game_index=replay.game_index, rated_games=0, full_native_audit_passed=True,
            native_audit_seal_sha256=portable['native_seal_sha256'])
        if replay_identical:
            report['replay_store_sha256'] = hashlib.sha256((stage / 'replay.jsonl').read_bytes()).hexdigest()
        write_new(stage / 'MATRIX.json', report)
        return report
    finally:
        transport.stop(planned_nodes)
