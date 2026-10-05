"""Guarded reference collection across independent three-core game slots.

The pool is a logical allocation, not a claim that its coordinator has six
local cores. Each node admits one game at a time on observed resources. The
supported throughput guard measures dispatch, collection and serialization.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

from spellbench.arena.allocation import Allocation, MachineFacts, PlayedGame, ThroughputError
from spellbench.arena.machine import RESERVE_BYTES
from spellbench.arena.throughput import current_rules, plan_allocation, workload_id
from spellbench.arena import store


@dataclass(frozen=True)
class PoolNode:
    alias: str
    usable_cpus: int
    memory_bytes: int
    free_bytes: int
    source_commit: str
    native_seal_sha256: str
    runtime_seal_sha256: str

    def validate(self, source, native_seal, runtime_seal, per_game_cores, cap_bytes):
        if (type(self.alias) is not str or not self.alias.strip() or type(self.usable_cpus) is not int or self.usable_cpus < per_game_cores or
                type(self.memory_bytes) is not int or self.memory_bytes < 8 * 2**30 or
                type(self.free_bytes) is not int or self.free_bytes < RESERVE_BYTES + cap_bytes):
            raise ThroughputError('A pool node cannot admit one declared game slot and storage reserve')
        if (self.source_commit != source or self.native_seal_sha256 != native_seal or
                self.runtime_seal_sha256 != runtime_seal):
            raise ThroughputError('A pool node has different source or admitted native/runtime evidence')


def partition(indices, workers):
    """Assign each frozen index once; recombine in the original input order."""
    if type(workers) is not int or workers not in (1, 2, 4):
        raise ThroughputError('The reference pool supports one, two or four measured game slots')
    indices = tuple(indices)
    if not indices or len(indices) != len(set(indices)) or any(type(i) is not int or i < 0 for i in indices):
        raise ThroughputError('Pool requests need distinct nonnegative frozen indices')
    return tuple(indices[node::workers] for node in range(workers))


def primary_digest(row):
    return 'sha256:' + hashlib.sha256(store.canonical_bytes(row)).hexdigest()


def portable_native_verdict(verdict):
    """Bind semantic evidence across machines without local absolute paths."""
    return {key: value for key, value in verdict.items() if key not in ('native_root', 'runtime_root')}


class ReferencePool:
    """A transport-independent guard; execute_node must enforce local admission.

    execute_node(node, request) returns one serialized result per requested
    index, each with its canonical row, measured game seconds and receipts.
    Node requests carry the full allocation only after the guard admits it.
    """

    def __init__(self, *, nodes, execute_node, source_commit, native_verdict, runtime_pins,
                 configuration, indices, stage, placement, host, rules, clock=time.perf_counter):
        self.nodes = tuple(nodes)
        self.execute_node = execute_node
        self.source_commit = source_commit
        self.native_verdict = json.loads(json.dumps(native_verdict))
        self.runtime_pins = json.loads(json.dumps(runtime_pins))
        self.configuration = json.loads(json.dumps(configuration))
        self.indices = tuple(indices)
        self.stage = Path(stage)
        self.placement, self.host, self.rules = placement, host, rules
        self.clock = clock
        self.per_game_cores = 3
        self.cap_bytes = 2 * 2**30
        self.allocation = None
        self.trial = 0
        if rules.worker_selection != 'wall':
            raise ThroughputError('Distributed collection selects by measured wall completion including transport')
        if (native_verdict.get('closed') is not True or native_verdict.get('seed_blocks') != 320 or
                native_verdict.get('completed_games') != 640 or native_verdict.get('outputs_identical') is not True):
            raise ThroughputError('A full, closed native pass is required before reference collection')
        if len(self.nodes) not in (2, 4) or len({node.alias for node in self.nodes}) != len(self.nodes):
            raise ThroughputError('Reference collection requires two or four distinct admitted nodes')
        self.slots = len(self.nodes)
        for node in self.nodes:
            node.validate(source_commit, native_verdict['native_seal_sha256'],
                native_verdict['runtime_seal_sha256'], self.per_game_cores, self.cap_bytes)
        partition(self.indices, 2)
        if len(self.indices) != 140:
            raise ThroughputError('The unchanged reference matrix contains 140 games')
        self.stage.mkdir(parents=True, exist_ok=True)
        self.descriptor = dict(kind='gorge-reference-pool/v1', source_commit=source_commit,
            native_verdict=self.native_verdict, runtime_pins=self.runtime_pins, configuration=self.configuration,
            indices=list(self.indices), nodes=[node.__dict__ for node in self.nodes], per_game_cores=self.per_game_cores,
            qualification_rules=self.rules.to_json())
        self.workload = workload_id(self.descriptor)
        self.machine = MachineFacts(memory_bytes=sum(node.memory_bytes for node in self.nodes), gpus=(),
            free_bytes=(('pin_root', min(node.free_bytes for node in self.nodes)),
                        ('run_dir', min(node.free_bytes for node in self.nodes))))
        self._write('POOL.json', dict(nodes=[node.__dict__ for node in self.nodes],
            assigned_game_cores=3*self.slots, per_node_game_slots=1, coordinator_is_game_worker=False,
            workload=self.workload, indices=self.indices, native_verdict=native_verdict,
            source_commit=source_commit, per_game_cores=3, cap_bytes=self.cap_bytes,
            reserve_bytes=RESERVE_BYTES, placement=placement, scope='reference qualification only', rated_games=0))

    def _write(self, name, value):
        (self.stage / name).write_text(json.dumps(value, indent=2) + '\n')

    def collect(self, workers, indices, *, phase, secret_hex):
        indices = tuple(indices)
        if workers > self.slots:
            raise ThroughputError('Requested workers exceed the admitted node count')
        groups = partition(indices, workers)
        if not set(indices) <= set(self.indices):
            raise ThroughputError('A pool request escaped the frozen reference indices')
        if phase not in ('qualification', 'matrix', 'replay'):
            raise ThroughputError('Unknown reference collection phase')
        if phase == 'qualification' and (len(indices) > 2*self.slots or self.trial >= 5):
            raise ThroughputError('Qualification exceeds the bounded supported scaling comparison')
        if phase == 'matrix' and indices != self.indices:
            raise ThroughputError('Full reference collection must preserve all 140 indices in order')
        if phase == 'replay' and len(indices) != 1:
            raise ThroughputError('Replay must contain one preselected original game')
        if phase != 'qualification':
            if (self.allocation is None or self.allocation.kind != 'substantial' or
                    self.allocation.outputs_identical is not True or workers != self.allocation.workers):
                # Replay deliberately runs one original seed serially.
                if not (phase == 'replay' and workers == 1 and self.allocation is not None and
                        self.allocation.kind == 'substantial' and self.allocation.outputs_identical is True):
                    raise ThroughputError('Substantial reference collection lacks a matching admitted allocation')
        self.trial += 1
        batch = self.trial
        started = self.clock()
        directory = self.stage / f'{phase}-{batch}-workers-{workers}'
        directory.mkdir()
        def execute(node_index):
            request = dict(schema='spellbench-gorge-reference-node-request/v1', batch=batch,
                node_alias=self.nodes[node_index].alias, phase=phase, indices=groups[node_index],
                source_commit=self.source_commit, workload=self.workload, configuration=self.configuration,
                pool_descriptor=self.descriptor, pool_workers=workers,
                runtime_pins=self.runtime_pins, native_verdict=self.native_verdict,
                per_game_cores=3, workers=1, pool_slots=self.slots, secret_hex=secret_hex,
                allocation=None if self.allocation is None else self.allocation.to_json())
            try:
                response = self.execute_node(self.nodes[node_index], request)
            except BaseException as error:
                (directory / f'node-{node_index}-FAILURE.json').write_text(json.dumps(dict(
                    batch=batch, node_alias=self.nodes[node_index].alias, error_type=type(error).__name__,
                    detail=str(error), workload=self.workload, rated_games=0)) + '\n')
                raise
            # Keep the complete returned evidence, including rejected rows,
            # receipts and diagnostics, before interpreting it.
            (directory / f'node-{node_index}-response.json').write_text(json.dumps(response) + '\n')
            return response
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(execute, i) for i in range(workers) if groups[i]]
            responses = [future.result() for future in futures]
        by_index = {}
        for node_index, response in enumerate(responses):
            if response.get('workload') != self.workload or response.get('batch') != batch:
                raise ThroughputError('A node response belongs to another allocation or batch')
            if response.get('node_alias') != self.nodes[node_index].alias:
                raise ThroughputError('A node response belongs to another worker')
            for result in response['results']:
                index = result['index']
                row = result['row']
                if (type(index) is not int or index in by_index or index not in groups[node_index] or row['game_index'] != index or
                        row.get('classification') != 'natural' or result.get('violation') is not None or
                        type(result.get('seconds')) not in (int, float) or not math.isfinite(result['seconds']) or result['seconds'] <= 0 or
                        primary_digest(row) != result.get('primary_digest')):
                    raise ThroughputError('A node omitted, duplicated, changed or failed a frozen game')
                by_index[index] = result
        if set(by_index) != set(indices):
            raise ThroughputError('A node response omitted a frozen game')
        ordered = tuple(by_index[index] for index in indices)
        # Persist collection before stopping the timing clock: transfer and
        # canonical serialization are part of useful completed-work throughput.
        with (directory / 'primary.jsonl').open('xb') as stream:
            for result in ordered:
                stream.write(store.canonical_bytes(result['row']) + b'\n')
        wall = self.clock() - started
        (directory / 'RECEIPT.json').write_text(json.dumps(dict(workers=workers, phase=phase,
            indices=indices, wall_seconds=wall, primary_sha256=hashlib.sha256((directory/'primary.jsonl').read_bytes()).hexdigest(),
            assigned_nodes=[node.alias for node in self.nodes[:workers]], workload=self.workload, rated_games=0), indent=2)+'\n')
        return wall, ordered

    def qualify(self, *, guard_secret_hex, sample):
        def play(workers, positions):
            indices = [self.indices[position] for position in positions]
            wall, results = self.collect(workers, indices, phase='qualification', secret_hex=guard_secret_hex)
            return wall, tuple(PlayedGame(index=position, seconds=result['seconds'],
                digest=primary_digest(result['row']), row_bytes=len(store.canonical_bytes(result['row']))+1)
                for position, result in zip(positions, results))
        allocation = plan_allocation(games_total=140, cap=self.slots, cpu_count=3*self.slots, per_game_cores=3,
            play=play, placement=self.placement, host=self.host, sample=sample,
            workload=self.workload, machine=self.machine, rules=self.rules,
            evidence=self.stage/'throughput-evidence.json', cap_bytes=self.cap_bytes)
        if allocation.kind != 'substantial' or allocation.outputs_identical is not True:
            raise ThroughputError('Reference collection needs observed matching serial/parallel outputs')
        self.allocation = allocation
        self._write('ALLOCATION.json', allocation.to_json())
        return allocation


def admit_node_request(request, *, node, source_commit, native_verdict, runtime_pins, configuration, frozen_indices,
                       pool_slots=2, rules=None):
    """The worker boundary checks local capacity and substantial admission."""
    node.validate(source_commit, native_verdict['native_seal_sha256'], native_verdict['runtime_seal_sha256'], 3, 2*2**30)
    if (request.get('source_commit') != source_commit or request.get('native_verdict') != native_verdict or
            request.get('runtime_pins') != runtime_pins or request.get('node_alias') != node.alias or
            request.get('per_game_cores') != 3 or request.get('workers') != 1 or
            request.get('configuration') != configuration or request.get('pool_slots') != pool_slots):
        raise ThroughputError('Node request source, evidence, input pins or resource budget differs')
    partition(request['indices'], 1)
    if request.get('phase') not in ('qualification', 'matrix', 'replay'):
        raise ThroughputError('Unknown node request phase')
    if not set(request['indices']) <= set(frozen_indices):
        raise ThroughputError('Node request escaped the original reference indices')
    if pool_slots not in (2, 4):
        raise ThroughputError('Unknown node pool size')
    if request['phase'] == 'qualification' and (len(request['indices']) > 2*pool_slots or type(request['batch']) is not int or request['batch'] not in (1, 2, 3, 4, 5)):
        raise ThroughputError('Unadmitted node request exceeds the bounded scaling comparison')
    descriptor = request.get('pool_descriptor')
    rules = replace(current_rules(), worker_selection='wall') if rules is None else rules
    if (not isinstance(descriptor, dict) or descriptor.get('kind') != 'gorge-reference-pool/v1' or
            descriptor.get('source_commit') != source_commit or descriptor.get('native_verdict') != native_verdict or
            descriptor.get('runtime_pins') != runtime_pins or descriptor.get('configuration') != configuration or
            descriptor.get('indices') != list(frozen_indices) or descriptor.get('per_game_cores') != 3 or
            descriptor.get('qualification_rules') != rules.to_json() or
            request.get('workload') != workload_id(descriptor)):
        raise ThroughputError('Node request does not bind the original pool workload')
    node_values = descriptor.get('nodes', [])
    if len(node_values) != pool_slots or len({value['alias'] for value in node_values}) != pool_slots:
        raise ThroughputError('Node request has a different pool inventory')
    if node.__dict__ not in node_values:
        raise ThroughputError('Node request omitted its independently observed worker')
    for value in node_values:
        PoolNode(**value).validate(source_commit, native_verdict['native_seal_sha256'],
            native_verdict['runtime_seal_sha256'], 3, 2*2**30)
    workers = request.get('pool_workers')
    if type(workers) is not int or workers not in (1, 2, 4) or workers > pool_slots:
        raise ThroughputError('Node request has an invalid pool worker count')
    position = next(i for i, value in enumerate(node_values) if value['alias'] == node.alias)
    if position >= workers:
        raise ThroughputError('Node is outside this trial allocation')
    if request['phase'] != 'qualification':
        allocation = Allocation.from_json(request['allocation'])
        if (allocation.kind != 'substantial' or allocation.outputs_identical is not True or
                allocation.workload != request['workload'] or allocation.games_total != 140 or
                allocation.per_game_cores != 3 or allocation.cpu_count != 3*pool_slots or
                allocation.rules != rules or
                (request['phase'] == 'matrix' and (workers != allocation.workers or
                  tuple(request['indices']) != partition(frozen_indices, workers)[position])) or
                (request['phase'] == 'replay' and (workers != 1 or len(request['indices']) != 1))):
            raise ThroughputError('Node request lacks the matching measured pool admission')
