"""One persistent reference worker with local admission and complete receipts.

The worker independently verifies the recovered native pass. It runs games
only through the existing arena runner, with one three-core slot. This module
does not create a lease, start a CI job, or publish ratings.
"""
from dataclasses import replace
import importlib.util
import json
import math
import os
from pathlib import Path

from spellbench.arena import machine, runner
from spellbench.arena.allocation import ThroughputError
from spellbench.arena.ledger import LedgerRow
from spellbench.arena.schedule import preflight, schedule
from spellbench.bench import definition, run as bench_run
from spellbench.file_pins import verify_files
from spellbench.run_secret import RunSecret

from gorge_native_gate import verify_native_audit
from gorge_reference_pool import (PoolNode, admit_node_request, portable_native_verdict,
                                  primary_digest)


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream)
        stream.write('\n')


def append_evidence(path, value):
    # Timing metadata contains seconds as floats; the canonical primary
    # ledger format deliberately excludes floats.
    with Path(path).open('a') as stream:
        stream.write(json.dumps(value) + '\n')


class RequestJournal:
    """Persist dispatch admission before launching; failed work is not retried."""

    def __init__(self, *, stage, node, source_commit, native_verdict, runtime_pins,
                 configuration, frozen_indices, replay_index, pool_slots, rules=None):
        self.stage = Path(stage)
        self.stage.mkdir(parents=True, exist_ok=True)
        # A worker restart requires explicit recovery of the original job.
        # Opening another journal cannot clear recorded dispatches.
        write_new(self.stage / 'JOURNAL-OWNER.json', dict(node_alias=node.alias, source_commit=source_commit))
        self.arguments = dict(node=node, source_commit=source_commit, native_verdict=native_verdict,
            runtime_pins=runtime_pins, configuration=configuration,
            frozen_indices=tuple(frozen_indices), pool_slots=pool_slots, rules=rules)
        self.replay_index = replay_index
        self.last_batch = 0
        self.workload = None
        self.qualification_count = 0
        self.guard_commitment = None
        self.matrix_commitment = None
        self.matrix_admitted = False
        self.replay_admitted = False

    def admit(self, request):
        admit_node_request(request, **self.arguments)
        if request.get('schema') != 'spellbench-gorge-reference-node-request/v1':
            raise ThroughputError('Unknown node request schema')
        batch = request.get('batch')
        if type(batch) is not int or not self.last_batch < batch <= 7:
            raise ThroughputError('Repeated, reordered or excessive node dispatch')
        if self.workload is not None and self.workload != request['workload']:
            raise ThroughputError('Persistent worker cannot change its pool workload')
        secret = RunSecret.from_hex(request['secret_hex'])
        commitment = secret.commitment()
        phase = request['phase']
        if phase == 'qualification':
            if (self.matrix_admitted or self.qualification_count >= 5 or
                    self.guard_commitment not in (None, commitment)):
                raise ThroughputError('Qualification dispatch changed secrets or exceeded its original comparison')
        elif phase == 'matrix':
            if self.matrix_admitted or not self.qualification_count or commitment == self.guard_commitment:
                raise ThroughputError('Full matrix needs prior comparison and a distinct matrix secret')
        elif (self.replay_admitted or not self.matrix_admitted or
              commitment != self.matrix_commitment or request['indices'] != [self.replay_index]):
            raise ThroughputError('Replay must repeat the one preselected original matrix seed')
        # Record only the secret commitment in the public recovery journal.
        write_new(self.stage / f'ADMISSION-{batch}.json', dict(batch=batch, phase=phase,
            indices=request['indices'], workload=request['workload'], secret_commitment=commitment,
            allocation=request['allocation'], pool_workers=request['pool_workers'], rated_games=0))
        self.last_batch, self.workload = batch, request['workload']
        if phase == 'qualification':
            self.qualification_count += 1
            self.guard_commitment = commitment
        elif phase == 'matrix':
            self.matrix_admitted = True
            self.matrix_commitment = commitment
        else:
            self.replay_admitted = True
        return secret


def load_original_helpers(source, stage):
    """Reuse the frozen selection and receipt rules without running main()."""
    previous = os.environ.get('GORGE_CLOUD_STAGE')
    os.environ['GORGE_CLOUD_STAGE'] = str(stage)
    try:
        spec = importlib.util.spec_from_file_location('gorge_original_reference_helpers',
            Path(source) / 'engines/gorge/scripts/reference_matrix.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop('GORGE_CLOUD_STAGE', None)
        else:
            os.environ['GORGE_CLOUD_STAGE'] = previous
    return module


class ReferenceWorker:
    def __init__(self, *, source, source_commit, cfg, stage, node_alias, pool_slots,
                 native_root, runtime, native_seal_sha256, runtime_seal_sha256, cleanup_sha256,
                 deadline, clock):
        self.source, self.stage, self.runtime = Path(source), Path(stage), Path(runtime)
        self.stage.mkdir(parents=True, exist_ok=True)
        self.cfg, self.deadline, self.clock = cfg, deadline, clock
        if cfg.per_game_cores() != 3:
            raise ThroughputError('Reference worker requires the original three-core game budget')
        # Do not accept a coordinator-supplied bool in place of the native audit.
        verdict = verify_native_audit(native_root, runtime, seal_sha256=native_seal_sha256,
            runtime_seal_sha256=runtime_seal_sha256, cleanup_sha256=cleanup_sha256)
        self.native_verdict = portable_native_verdict(verdict)
        memory = machine.total_memory()
        self.node = PoolNode(node_alias, machine.usable_cpus(), memory, machine.free_bytes(self.stage),
            source_commit, native_seal_sha256, runtime_seal_sha256)
        self.node.validate(source_commit, native_seal_sha256, runtime_seal_sha256, 3, 2*2**30)
        self.files = bench_run.run_files(cfg)
        verify_files(self.files)
        self.runtime_pins = [value.to_json() for value in self.files]
        self.helpers = load_original_helpers(source, stage)
        self.rules = replace(definition.load_benchmark(self.source / 'benchmarks/pauper-gorge').qualification_rules(),
                             worker_selection='wall')
        # Index/seat/deck selection is independent of the actual private secret.
        # This placeholder never starts an engine or becomes a played seed.
        selected, self.expected = self.helpers.select_matrix(schedule(cfg, RunSecret.from_hex('00'*32)))
        self.indices = tuple(context.game_index for context in selected)
        replay = next(context for context in selected if context.decks[0].catalog_id == 'Burn'
                      and any('search' in spec.name for _, spec in context.seat_specs))
        self.journal = RequestJournal(stage=self.stage / 'dispatches', node=self.node,
            source_commit=source_commit, native_verdict=self.native_verdict, runtime_pins=self.runtime_pins,
            configuration=cfg.to_json(), frozen_indices=self.indices, replay_index=replay.game_index,
            pool_slots=pool_slots, rules=self.rules)

    def resource_guard(self):
        if self.clock() >= self.deadline or (self.stage / 'STOP').exists():
            raise ThroughputError('Reference worker reached its wall cap or owned STOP')
        memory = machine.total_memory()
        current = PoolNode(self.node.alias, machine.usable_cpus(), memory, machine.free_bytes(self.stage),
            self.node.source_commit, self.node.native_seal_sha256, self.node.runtime_seal_sha256)
        current.validate(self.node.source_commit, self.node.native_seal_sha256,
            self.node.runtime_seal_sha256, 3, 2*2**30)
        if sum(path.stat().st_size for path in self.stage.rglob('*') if path.is_file()) > 2*2**30:
            raise ThroughputError('Reference worker exceeded its scratch cap')

    def execute(self, request):
        if any(os.environ.get(key) for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'RUNPOD_API_KEY')):
            raise ThroughputError('Transport credentials must be removed before launching an engine or bot')
        self.resource_guard()
        verify_files(self.files)
        secret = self.journal.admit(request)
        directory = self.stage / f"batch-{request['batch']}"
        directory.mkdir()
        audit = directory / 'native-audits'
        audit.mkdir()
        previous_audit = os.environ.get('GORGE_AGENT_AUDIT_DIR')
        os.environ['GORGE_AGENT_AUDIT_DIR'] = str(audit)
        results = []
        response = dict(batch=request['batch'], workload=request['workload'], node_alias=self.node.alias,
                        results=results, rated_games=0)
        try:
            setup = preflight(self.cfg, secret)
            entries = {entry.name: entry for entry in runner.registry_entries(self.cfg, self.cfg)}
            contexts = schedule(self.cfg, secret)
            chosen = [contexts[index] for index in request['indices']]
            def record(outcome):
                row = LedgerRow.from_json(outcome.row.to_json()).to_json()
                result = dict(index=row['game_index'], row=row, seconds=outcome.seconds,
                    primary_digest=primary_digest(row), diagnostics=list(outcome.diagnostics),
                    engine=outcome.engine, violation=outcome.violation)
                # Keep failed primary rows and diagnostics before applying gates.
                append_evidence(directory / 'results.jsonl', result)
                if (row['engine'] != setup.engine.provenance().to_json() or outcome.engine != setup.engine.to_json() or
                        row['game_id'] != secret.game_id(row['game_index']) or
                        row['classification'] != 'natural' or outcome.violation is not None or
                        not math.isfinite(outcome.seconds) or outcome.seconds <= 0):
                    raise ThroughputError('Reference game failed identity, seed, natural-terminal or timing checks')
                result['policy_receipts'] = self.helpers.join_receipts(row, audit)
                append_evidence(directory / 'joined.jsonl', result)
                results.append(result)
            run = runner.play_games(self.cfg, setup, chosen, run_secret=secret, entries=entries,
                workers=1, stop_on_violation=True, timed=True, on_outcome=record,
                guard=self.resource_guard, launch_files=self.files)
            if run.error is not None:
                raise run.error
            if run.stopped is not None or [result['index'] for result in results] != request['indices']:
                raise ThroughputError('Reference dispatch did not finish its exact frozen subset')
            self.resource_guard()
            write_new(directory / 'RESPONSE.json', response)
            return response
        except BaseException as error:
            write_new(directory / 'FAILURE.json', dict(batch=request['batch'], error_type=type(error).__name__,
                detail=str(error), completed_indices=[value['index'] for value in results], rated_games=0))
            raise
        finally:
            if previous_audit is None:
                os.environ.pop('GORGE_AGENT_AUDIT_DIR', None)
            else:
                os.environ['GORGE_AGENT_AUDIT_DIR'] = previous_audit
