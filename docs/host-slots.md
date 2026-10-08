# Core slots on reserved hosts

`python/tools/host_slots_v1.py` lets untimed work use the cores that timed work leaves idle. It works alongside the whole-host reservation (`host_reservation_v1.py` in mtg-kernel `python/tools`) and does not replace it.

The v1 lock at `C:/mtg-node/host-lock/<HOST>.lock` keeps its exact meaning. This tool never writes it, and existing launchers, rated runs and CI pause hooks need no change. Slot records live beside it, in `<HOST>.slots/`.

## Untimed work: claim cores

```
python host_slots_v1.py run --lane LANE --work-id WORK --cores N [--wait] [--wait-timeout S] [--priority below_normal] -- COMMAND...
python host_slots_v1.py submit --log FILE --lane LANE --work-id WORK --cores N -- COMMAND...
```

`run` claims N free cores and pins `COMMAND` and every process it starts to them, at below-normal priority by default. On Windows this uses a job object, so the whole tree also dies if the runner is killed. When the tree ends, the claim is freed.

With `--wait`, the claim queues and starts in arrival order once cores are free. Without `--wait`, it exits with code 3 when there is no room. `submit` starts a detached waiting `run` that logs to `FILE`, and returns the claim id immediately.

The command sees `HOST_SLOTS_CLAIM` and `HOST_SLOTS_CORES`. On Windows, `spellbench.arena.machine.usable_cpus()` counts only the pinned cores, so throughput planning sizes workers to the claim.

## Interaction with timed work

Whenever the v1 lock is held and leaves a claim no room, every process in the claim is suspended. It resumes when the room comes back. A lock leaves no room when it has no core declaration, or when its declaration overlaps the claim's cores. A claim that would start under such a lock waits before starting.

Untimed work therefore never runs on a timed run's cores. It may, however, run on other cores of the same machine at the same time, sharing cache, memory bandwidth and the power budget.

## Timed work: give back the cores you do not need

Inside the v1 supervisor, wrap the timed command:

```
host_reservation_v1.py supervise --token T -- python host_slots_v1.py timed --cores 0-7 -- COMMAND...
```

`timed` checks that `MTG_HOST_RESERVATION_TOKEN` holds the lock and declares the cores. It waits for any claim on those cores to suspend; if one does not within 60 s, it refuses with exit 6. It then pins `COMMAND` to those cores and removes the declaration when the command's tree ends. Untimed claims may then use the rest of the host.

A held lock with no declaration still reserves the whole host, which covers every launcher written before this tool.

Declaring is a change to a run's execution. For a rated run, qualify throughput with the same declaration and the same background load before the commitment names it. Launchers whose busy refusal matches process names (for example `java`) also see suspended claim processes.

## Per-host config

The optional file `<HOST>.slots/config.json` controls what claims may use:

```json
{"cores": "23-0", "keep_free": 0, "priority": "below_normal"}
```

- `cores` lists the cores untimed work may use, in order of preference. The default is every logical CPU, highest-numbered first, so claims stay off the low-numbered P cores of hybrid Intel parts, which timed work usually declares.
- `keep_free` is the number of those cores that are never handed out.
- `priority` is the default priority for claims.

On the compute host, its owner's use comes first. Set `keep_free` so the owner always has room, and keep `below_normal`. Use `topology` to see which logical CPUs share a physical core and each core's efficiency class (P cores rank higher).

## Status

`python host_slots_v1.py status` prints:

- the timed reservation (lane, work and declared cores, never the token)
- live claims and their state (`running` or `suspended`)
- the queue
- the free cores

Records whose process has exited are removed as they are read.

## Limits

- On Linux (WSL runners, tests), containment is a process group. A process that leaves the group escapes affinity bookkeeping and suspension.
- Cores above 63 (a second Windows processor group) are not supported.
- During a v1 reclaim the lock is briefly absent, so claims may resume for one poll interval (2 s).
