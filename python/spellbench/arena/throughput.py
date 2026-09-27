"""The useful-compute guard (COMPUTE-POLICY.md): how many games a run plays at once, and the evidence for it.

The public names of the guard, re-exported from the modules that hold them:

- :mod:`.allocation`: the allocation record the manifest carries, its parts
  (trials, placement, machine facts, budget, spot check) and the rules it
  is checked against;
- :mod:`.qualification`: planning an allocation before the first game
  (probe, scaling comparison, reuse of local evidence, reserve and budget);
- :mod:`.machine`: cores, memory, GPUs, free space and CPU use;
- :mod:`.monitor`: warnings while the run plays.

Patch module constants where they are read: ``qualification.SUBSTANTIAL_RUN_SECONDS``,
not a copy re-exported here.
"""

from __future__ import annotations

from .allocation import (
    ALLOCATION_KINDS,
    PLACEMENT_DISPOSITIONS,
    PLACEMENT_MACHINES,
    QUALIFY_BUDGET_PERCENT,
    QUALIFY_GAMES_PER_WORKER,
    VOLUME_ROLES,
    Allocation,
    Budget,
    MachineFacts,
    MachinePlacement,
    Placement,
    PlayedGame,
    SpotCheck,
    ThroughputError,
    Trial,
    resource_bound,
    spot_check_game,
    worker_ladder,
)
from .machine import RESERVE_BYTES, CpuSampler, check_reserve, free_bytes, machine_facts, nvidia_gpus, total_memory
from .monitor import IDLE_WINDOWS, RATE_FLOOR_PERCENT, RATE_MIN_GAMES, IdleMonitor, warning_sink
from .qualification import EVIDENCE_SCHEMA, PROBE_GAMES, SUBSTANTIAL_RUN_SECONDS, plan_allocation, sample_order, workload_id

__all__ = [
    "ALLOCATION_KINDS",
    "EVIDENCE_SCHEMA",
    "IDLE_WINDOWS",
    "PLACEMENT_DISPOSITIONS",
    "PLACEMENT_MACHINES",
    "PROBE_GAMES",
    "QUALIFY_BUDGET_PERCENT",
    "QUALIFY_GAMES_PER_WORKER",
    "RATE_FLOOR_PERCENT",
    "RATE_MIN_GAMES",
    "RESERVE_BYTES",
    "SUBSTANTIAL_RUN_SECONDS",
    "VOLUME_ROLES",
    "Allocation",
    "Budget",
    "CpuSampler",
    "IdleMonitor",
    "MachineFacts",
    "MachinePlacement",
    "Placement",
    "PlayedGame",
    "SpotCheck",
    "ThroughputError",
    "Trial",
    "check_reserve",
    "free_bytes",
    "machine_facts",
    "nvidia_gpus",
    "plan_allocation",
    "resource_bound",
    "sample_order",
    "spot_check_game",
    "total_memory",
    "warning_sink",
    "worker_ladder",
    "workload_id",
]
