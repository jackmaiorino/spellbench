from types import SimpleNamespace

from spellbench.arena import machine
from spellbench.arena.throughput import resource_bound


def linux_container(monkeypatch, files, *, affinity=32, physical_memory=128 * 2**30):
    monkeypatch.setattr(machine, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(machine, "os", SimpleNamespace(
        name="posix", cpu_count=lambda: 32, sched_getaffinity=lambda _: set(range(affinity)),
        sysconf=lambda name: 4096 if name == "SC_PAGE_SIZE" else physical_memory // 4096))
    monkeypatch.setattr(machine, "_cgroup_text", files.get)


def test_legacy_runpod_quota_prevents_eight_worker_overcommit(monkeypatch):
    linux_container(monkeypatch, {
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "1360000",
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes": "60999999488",
    })
    assert machine.usable_cpus() == 14
    assert resource_bound(machine.usable_cpus(), 3) == 4
    assert machine.total_memory() == 60999999488


def test_combined_legacy_cpu_mount_and_unlimited_memory(monkeypatch):
    linux_container(monkeypatch, {
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us": "400000",
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us": "100000",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712",
    })
    assert machine.usable_cpus() == 4
    assert machine.total_memory() == 128 * 2**30


def test_v2_quota_and_affinity_both_bound_available_cores(monkeypatch):
    linux_container(monkeypatch, {
        "/sys/fs/cgroup/cpu.max": "800000 100000",
        "/sys/fs/cgroup/memory.max": str(8 * 2**30),
    }, affinity=4)
    assert machine.usable_cpus() == 4
    assert machine.total_memory() == 8 * 2**30


def test_unlimited_and_malformed_controller_values_keep_physical_bounds(monkeypatch):
    linux_container(monkeypatch, {
        "/sys/fs/cgroup/cpu.max": "max 100000",
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1",
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
        "/sys/fs/cgroup/memory.max": "max",
    }, affinity=12)
    assert machine.usable_cpus() == 12
    assert machine.total_memory() == 128 * 2**30
    assert machine.usable_cpus(7) == 7
